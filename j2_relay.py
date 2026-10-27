"""The change relay: a change on a finished realization run goes charter -> planning documents -> affected build
sections (docs/superpowers/specs/2026-10-27-change-relay-design.md).

Pure logic, no AI calls and no run state: the planning graph read from a run's workflows, the replies the relay's
calls must give, the charter diff, the checks a revision carries, and the validator's rules while a change is open.
j2.py does the wiring. Nothing here names a stage, a document or a workflow: everything comes from the run."""


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
