"""Charter change: a second prompt on a finished realization run, split into intents, each decided once
(docs/superpowers/specs/2026-10-30-charter-change-design.md).

No run state: the planning graph read from a run's workflows (ported from the change relay), the replies its calls
must give, the charter diff on charter numbers, item owners, the decision rule, and the change planner's calls (through
j2_realization's Session). j2.py does the wiring.
Nothing here names a stage, a document or a workflow: everything comes from the run. What counts as a planning
document is the caller's test (is_doc; j2 passes is_artifact)."""
import llm
import j2_realization as R


# ---- the planning graph: workflows by id and name, revision chains, documents and their readers
def _index(workflows):
    """Every workflow by id and by name."""
    ix = {}
    for w in workflows:
        ix[str(w.get("id"))] = w
        if w.get("name"):
            ix.setdefault(str(w["name"]), w)
    return ix


def ix_get(workflows, ref):
    """A workflow by id or name, or None."""
    return _index(workflows).get(str(ref))


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


def latest(workflows, root):
    """The newest workflow whose revises chain ends at root's root (the root itself when nothing revised it)."""
    r = _root_id(workflows, root)
    family = [w for w in workflows if _root_id(workflows, w["id"]) == r]
    return family[-1] if family else None


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


def planning_nodes(workflows, is_doc):
    """The latest revision of every planning document workflow (is_doc), in plan order. Each: {"id", "name", "root",
    "outputs", "parents"}; parents are the root ids of the planning workflows it depends on."""
    roots = _roots_in_order(workflows, is_doc)
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
    """Latest ids of the workflows (documents or builds) that name root, or any revision of it, in their dependencies."""
    r, out = _root_id(workflows, root), []
    for w in workflows:
        wr = _root_id(workflows, w["id"])
        if wr != r and r in _dep_roots(workflows, w):
            lid = latest(workflows, wr)["id"]
            if lid not in out:
                out.append(lid)
    return out


def build_candidates(workflows, changed_roots, is_doc):
    """Latest ids of the built workflows (not is_doc) whose dependencies, followed through any workflow (every
    revision of it), reach a changed planning root."""
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
    for r in _roots_in_order(workflows, lambda w: not is_doc(w)):
        w = latest(workflows, r)
        if w.get("status") == "done" and reaches(r, {r}):
            out.append(w["id"])
    return out


# ---- the replies: each call answers in JSON, checked here (None = malformed, the caller retries once)
def _obj(reply):
    try:
        d = llm.extract_json(str(reply)) if reply else None
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def parse_affected(reply):
    """{"affected": bool, "what": str}."""
    d = _obj(reply)
    if not d or not isinstance(d.get("affected"), bool) or not isinstance(d.get("what"), str):
        return None
    return {"affected": d["affected"], "what": d["what"]}


# ---- step 2, intents: what Identity changed, by charter number (charter_items position + 1; an item is active while
# its text is in done_when). An edit is a removed number plus an added one; a revert finds its old number again.
def _numbers(base, new):
    """Charter number of every item text: the newest charter_items list known, then new texts in done_when order."""
    items = list(new.get("charter_items") or base.get("charter_items") or base.get("done_when") or [])
    for t in base.get("charter_items") or []:
        if t not in items:
            items.append(t)
    for t in list(base.get("done_when") or []) + list(new.get("done_when") or []):
        if t not in items:
            items.append(t)
    return {t: i + 1 for i, t in enumerate(items)}


def _text_diff(old, new):
    old, new = list(old or []), list(new or [])
    return {"added": [t for t in new if t not in old], "removed": [t for t in old if t not in new]}


def charter_diff(base, new):
    """{"added": [n], "removed": [n], "rules": {"added", "removed"}, "standards": {...}, "goal_changed": bool}: active
    items by charter number, rules and standards by text; goal_changed when the statement or audience differs."""
    no = _numbers(base, new)
    was = {no[t] for t in base.get("done_when") or []}
    now = {no[t] for t in new.get("done_when") or []}
    same = lambda k: str(base.get(k) or "").strip() == str(new.get(k) or "").strip()
    return {"added": sorted(now - was), "removed": sorted(was - now),
            "rules": _text_diff(base.get("rules"), new.get("rules")),
            "standards": _text_diff(base.get("standards"), new.get("standards")),
            "goal_changed": not (same("statement") and same("audience"))}


def diff_empty(d):
    """Nothing to plan: no item, rule or standard changed and the goal is the same."""
    return not (d["added"] or d["removed"] or d["goal_changed"]
                or any(d[k][x] for k in ("rules", "standards") for x in ("added", "removed")))


LIVE = ("registered", "held", "running", "done")      # as j2: a dropped, failed or unfunded workflow owns nothing


def owner_index(workflows):
    """{charter number: id of the workflow that owns it}: per revision chain, the covers of the newest live workflow
    that covers anything (a fix that names no items does not take ownership away)."""
    out = {}
    for r in _roots_in_order(workflows, lambda w: True):
        live = [w for w in workflows if _root_id(workflows, w["id"]) == r and w.get("status") in LIVE and w.get("covers")]
        if live:
            for n in live[-1].get("covers") or []:
                out[int(n)] = live[-1]["id"]
    return out


# ---- step 3, the decision: the judge answers, code decides each intent once. A uses the existing workflow, B makes
# one small fix, C adds a workflow in a stage of the plan, D adds a stage.
THRESHOLD = 0.80          # as j2_realization.THRESHOLD
PART = {"done_test": "goal", "inputs": "context", "method": "how", "zone_fit": "how", "factors": "constraints",
        "size": "size", "fits": "goal"}         # a work-atom label over the judge's checks; weights do not change


def weakest_part(settled, spec):
    """The work-atom part that lost the most in j2_realization.settle's result: each failed question's weight counts
    for its check's part (spec: the workflow's {question id: (check, weight, text)}). None when nothing was lost."""
    lost = {}
    for i in (settled or {}).get("failed") or []:
        if i in spec:
            part = PART[spec[i][0]]
            lost[part] = lost.get(part, 0) + spec[i][1]
    return max(lost, key=lost.get) if lost else None


def decide(kind, match, score, after_fix=None):
    """"A" | "B" | "C" | "D" for one intent. kind is "added" or "removed"; match = {"owner", "stage"} from the match
    call (unread: its reply was malformed twice, so placement looks at it); score = {"score", "weakest_part"} for the
    owner; after_fix = the owner's score after the one fix (B)."""
    if kind == "removed":
        return "A"
    if not match.get("owner"):
        return "C" if match.get("stage") or match.get("unread") else "D"
    if score["score"] >= THRESHOLD:
        return "A"
    if score.get("weakest_part") == "size":
        return "C"
    if after_fix is None:
        return "B"
    return "A" if after_fix["score"] >= THRESHOLD else "C"


# ---- the calls (j2_realization's Session; every reply is checked here and sent back once with its faults named)
def ask_checked(s, who, system, task, mock, check):
    """(result, faults): one call, and one more naming the faults when its reply breaks check(reply) -> (result,
    faults); the reply with fewer faults counts."""
    got, faults = check(s.ask(who, system, task, mock))
    if faults:
        got2, f2 = check(s.ask(who, system, task + "\n\nYOUR REPLY LACKED:\n- " + "\n- ".join(faults)
                               + "\nSend the whole reply again.", mock))
        if len(f2) <= len(faults):
            got, faults = got2, f2
    return got, faults


def match(s, goal, plan, items, mock):
    """{charter number: {"owner", "stage", "why"}} for the added items, from one match call (G0 asked of every
    workflow). A stage not in the plan counts as none; an item the reply still lacks after one retry is unread."""
    names = {w.get("name") for w in R.lst(plan.get("workflows")) if isinstance(w, dict)}
    stages = {x.get("id") for x in R.lst(plan.get("stages")) if isinstance(x, dict)}

    def check(r):
        got, out = {}, []
        for x in R.lst((r or {}).get("intents")):
            n = R.as_int(x.get("item")) if isinstance(x, dict) else 0
            if n not in items:
                out.append(f"item {n} is not a new item")
            elif x.get("owner") is not None and x["owner"] not in names:
                out.append(f"item {n}: owner {x['owner']!r} is not a workflow in the plan")
            else:
                got[n] = {"owner": x.get("owner"), "stage": x.get("stage") if x.get("stage") in stages else None,
                          "why": str(x.get("why") or "")}
        if miss := [n for n in items if n not in got]:
            out.append(f"no answer for item {', '.join(map(str, miss))}")
        return got, out

    got, _ = ask_checked(s, "judge", R.judge_system(), R.match_task(goal, plan, items), mock, check)
    return {n: got.get(n) or {"owner": None, "stage": None, "why": "the match reply was unreadable", "unread": True}
            for n in items}
