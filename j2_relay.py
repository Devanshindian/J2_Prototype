"""The change relay: a change on a finished realization run goes charter -> planning documents -> affected build
sections (docs/superpowers/specs/2026-10-27-change-relay-design.md).

Pure logic, no AI calls and no run state: the planning graph read from a run's workflows, the replies the relay's
calls must give, the charter diff, the checks a revision carries, and the validator's rules while a change is open.
j2.py does the wiring. Nothing here names a stage, a document or a workflow: everything comes from the run."""
import copy
import re

import llm


def _index(workflows):
    """Every workflow by id and by name."""
    ix = {}
    for w in workflows:
        ix[str(w.get("id"))] = w
        if w.get("name"):
            ix.setdefault(str(w["name"]), w)
    return ix


def _root_id(workflows, wid):
    """The original workflow a revision chain ends at (a workflow that revises nothing is its own root)."""
    ix, seen, cur = _index(workflows), set(), ix_get(workflows, wid)
    while cur and cur.get("revises") and cur["id"] not in seen:
        seen.add(cur["id"])
        nxt = ix.get(str(cur["revises"]))
        if not nxt:
            break
        cur = nxt
    return cur["id"] if cur else None


def ix_get(workflows, ref):
    """A workflow by id or name, or None."""
    return _index(workflows).get(str(ref))


def latest(workflows, root):
    """The newest workflow whose revises chain ends at root's root (the root itself when nothing revised it)."""
    r = _root_id(workflows, root)
    family = [w for w in workflows if _root_id(workflows, w["id"]) == r]
    return family[-1] if family else None


def _is_site(w, site_file):
    return site_file in (w.get("outputs") or [])


def _is_planning(w, site_file):
    outs = w.get("outputs") or []
    return bool(outs) and not _is_site(w, site_file)


def _roots_in_order(workflows, keep):
    out = []
    for w in workflows:
        r = _root_id(workflows, w["id"])
        if keep(w) and r not in out:
            out.append(r)
    return out


def _dep_roots(workflows, w):
    """Root ids of the workflows w depends on (by name or id), in order, without w's own root."""
    own, out = _root_id(workflows, w["id"]), []
    for d in w.get("dependencies") or []:
        t = ix_get(workflows, d)
        r = _root_id(workflows, t["id"]) if t else None
        if r and r != own and r not in out:
            out.append(r)
    return out


def planning_nodes(workflows, site_file):
    """The latest revision of every workflow whose output is a file other than the site file, in plan order. Each:
    {"id", "name", "root", "outputs", "parents"}; parents are the root ids of the planning workflows it depends on."""
    roots = _roots_in_order(workflows, lambda w: _is_planning(w, site_file))
    nodes = []
    for r in roots:
        w = latest(workflows, r)
        nodes.append({"id": w["id"], "name": ix_get(workflows, r)["name"], "root": r, "outputs": w.get("outputs") or [],
                      "parents": [p for p in _dep_roots(workflows, w) if p in roots]})
    return nodes


def relay_waves(nodes):
    """Root ids in dependency order: each wave holds the nodes whose parents have all answered, in plan order."""
    done, left, waves = set(), [n["root"] for n in nodes], []
    parents = {n["root"]: [p for p in n["parents"] if p in {m["root"] for m in nodes}] for n in nodes}
    while left:
        wave = [r for r in left if all(p in done for p in parents[r])]
        if not wave:                       # a cycle: ask the rest together rather than never
            wave = list(left)
        waves.append(wave)
        done.update(wave)
        left = [r for r in left if r not in done]
    return waves


def direct_readers(workflows, root):
    """Latest ids of the workflows (planning or site) that name root, or any revision of it, in their dependencies."""
    r, out = _root_id(workflows, root), []
    for w in workflows:
        wr = _root_id(workflows, w["id"])
        if wr != r and r in _dep_roots(workflows, w):
            lid = latest(workflows, wr)["id"]
            if lid not in out:
                out.append(lid)
    return out

def build_candidates(workflows, changed_roots, site_file):
    """Latest ids of the built site sections whose dependencies, followed through any workflow (every revision of
    it), reach a changed planning root."""
    changed = {_root_id(workflows, r) for r in changed_roots} - {None}
    if not changed:
        return []
    edges = {}
    for w in workflows:
        edges.setdefault(_root_id(workflows, w["id"]), set()).update(_dep_roots(workflows, w))

    def reaches(r, seen):
        for d in edges.get(r, ()):
            if d in changed or (d not in seen and (seen.add(d) or reaches(d, seen))):
                return True
        return False

    out = []
    for r in _roots_in_order(workflows, lambda w: _is_site(w, site_file)):
        w = latest(workflows, r)
        if w.get("status") == "done" and reaches(r, {r}):
            out.append(w["id"])
    return out


# ---- the replies: each relay call answers in JSON, checked here (None = malformed, the caller retries once)
VERDICTS = ("no-change", "change-here")


def _obj(reply):
    try:
        d = llm.extract_json(str(reply)) if reply else None
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _text(d, key):
    return isinstance(d.get(key), str)


def parse_verdict(reply):
    """{"verdict": "no-change" | "change-here", "reason": str, "changes": [str]}: changes is non-empty exactly when
    the verdict is change-here."""
    d = _obj(reply)
    if not d or d.get("verdict") not in VERDICTS or not _text(d, "reason"):
        return None
    ch = d.get("changes", [])
    if not isinstance(ch, list) or not all(isinstance(x, str) and x.strip() for x in ch):
        return None
    if bool(ch) != (d["verdict"] == "change-here"):
        return None
    return {"verdict": d["verdict"], "reason": d["reason"], "changes": ch}


def parse_affected(reply):
    """{"affected": bool, "what": str}."""
    d = _obj(reply)
    if not d or not isinstance(d.get("affected"), bool) or not _text(d, "what"):
        return None
    return {"affected": d["affected"], "what": d["what"]}


def parse_agreement(reply, build):
    """{"agree": bool, "reason": str}, plus affected and what for a build section."""
    d = _obj(reply)
    if not d or not isinstance(d.get("agree"), bool) or not _text(d, "reason"):
        return None
    out = {"agree": d["agree"], "reason": d["reason"]}
    if build:
        a = parse_affected(reply)
        if not a:
            return None
        out.update(a)
    return out


# ---- the charter diff: what Identity changed, by charter number (an edit keeps its number)
def _pair(old, new):
    """Positional pairing of two lists of strings: an item that changed in place is an edit; the rest are removed or
    added. Returns (edited [(i, old, new)], removed [i], added [j]) by list index."""
    edited, removed, added = [], [], []
    for i, o in enumerate(old):
        if o in new:
            continue
        if i < len(new) and new[i] not in old:
            edited.append((i, o, new[i]))
        else:
            removed.append(i)
    taken = {e[0] for e in edited}
    added = [j for j, n in enumerate(new) if n not in old and j not in taken]
    return edited, removed, added


def _list_diff(old, new):
    edited, removed, added = _pair(list(old or []), list(new or []))
    return {"added": [new[j] for j in added], "edited": [(o, n) for _, o, n in edited],
            "removed": [old[i] for i in removed]}


def charter_diff(old, new):
    """Done-when items by charter number (old charter_items numbering; an added item takes the next number) plus
    the standards and rules: {"added": [(n, text)], "edited": [(n, old, new)], "removed": [(n, text)],
    "standards": {"added", "edited", "removed"}, "rules": {...}}."""
    items = list(old.get("charter_items") or old.get("done_when") or [])
    no = lambda t: items.index(t) + 1 if t in items else None
    o, n = list(old.get("done_when") or []), list(new.get("done_when") or [])
    edited, removed, added = _pair(o, n)
    nxt = len(items)
    adds = []
    for j in added:
        nxt += 1
        adds.append((nxt, n[j]))
    return {"added": adds, "edited": [(no(a), a, b) for _, a, b in edited], "removed": [(no(o[i]), o[i]) for i in removed],
            "standards": _list_diff(old.get("standards"), new.get("standards")),
            "rules": _list_diff(old.get("rules"), new.get("rules"))}


def diff_empty(d):
    return not (d["added"] or d["edited"] or d["removed"]
                or any(d[k][x] for k in ("standards", "rules") for x in ("added", "edited", "removed")))


# ---- the checks a planning revision carries: its predecessor's, following the charter, plus every earlier heading
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)


def headings_of(text):
    """The markdown headings of a document, without the #, in order, once each."""
    out = []
    for h in HEADING.findall(text or ""):
        if h not in out:
            out.append(h)
    return out


def _swaps(diff):
    """(old, new) for every edited charter string and (old, None) for every removed one."""
    sw = [(o, n) for _, o, n in diff.get("edited") or []] + [(o, None) for _, o in diff.get("removed") or []]
    for k in ("standards", "rules"):
        sw += list(diff.get(k, {}).get("edited") or []) + [(o, None) for o in diff.get(k, {}).get("removed") or []]
    return [(o, n) for o, n in sw if o]


def _swap(text, swaps):
    for o, n in swaps:
        if text == o or (len(text) >= 8 and text in o):
            return n
    return text


def carry_checks(verification, diff, old_text):
    """The predecessor's checks with facts-present text that came from an edited charter string replaced by the new
    string (dropped when the string was removed; a facts check left with nothing is dropped), plus a
    heading-present check for every heading of the old file. The input is not changed."""
    swaps, out = _swaps(diff), []
    for c in copy.deepcopy(verification or []):
        if c.get("type") == "facts-present":
            t = c.get("target")
            vals = [_swap(x, swaps) for x in (t if isinstance(t, list) else [t])]
            vals = [x for x in vals if x]
            if not vals:
                continue
            c["target"] = vals if isinstance(t, list) else vals[0]
        if c.get("type") == "heading-present":
            continue                          # replaced by the full list below
        out.append(c)
    out += [{"text": f"The document still has the heading {h}.", "type": "heading-present", "target": h, "expect": True}
            for h in headings_of(old_text)]
    return out
