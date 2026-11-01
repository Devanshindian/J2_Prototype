"""Charter change: a second prompt on a finished realization run, split into intents, each decided once
(docs/superpowers/specs/2026-10-30-charter-change-design.md).

No run state: the planning graph read from a run's workflows (ported from the change relay), the replies its calls
must give, the charter diff on charter numbers, item owners, the decision rule, and the change planner's calls (through
j2_realization's Session). j2.py does the wiring.
Nothing here names a stage, a document or a workflow: everything comes from the run. What counts as a planning
document is the caller's test (is_doc; j2 passes is_artifact)."""
import json
import os

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
    items by charter number, rules and standards by text; goal_changed when the statement or audience differs. A
    statement that only gains text after the old one (Identity noting the change) is the same goal."""
    no = _numbers(base, new)
    was = {no[t] for t in base.get("done_when") or []}
    now = {no[t] for t in new.get("done_when") or []}
    old_s, new_s = (str(x.get("statement") or "").strip() for x in (base, new))
    same_goal = new_s == old_s or bool(old_s) and new_s.startswith(old_s)
    same_aud = str(base.get("audience") or "").strip() == str(new.get("audience") or "").strip()
    return {"added": sorted(now - was), "removed": sorted(was - now),
            "rules": _text_diff(base.get("rules"), new.get("rules")),
            "standards": _text_diff(base.get("standards"), new.get("standards")),
            "goal_changed": not (same_goal and same_aud)}


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


# ---- step 3, the decision: the match call answers, code decides each intent once. A: the owner is edited and passes
# the judge; B: the edited owner is improved once and passes; C: a new workflow in a stage of the plan; D: a new stage.
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


def decide(kind, match, score=None, after_fix=None):
    """"A" | "B" | "C" | "D" for one intent. kind is "added" or "removed"; match = {"owner", "too_big", "stage"} from the
    match call (unread: its reply was malformed twice, so placement looks at it); score = {"score", "weakest_part"} of
    the owner after the edit (None: the edit or the judge's reply lacked it); after_fix = its score after the one
    improvement. "B" without after_fix means: improve once, then decide again."""
    if kind == "removed":
        return "A"
    if not match.get("owner"):
        return "C" if match.get("stage_in_plan") or match.get("unread") else "D"
    if match.get("too_big") or score is None:
        return "C"
    if score["score"] >= THRESHOLD:
        return "A"
    if score.get("weakest_part") == "size":
        return "C"
    if after_fix is None:
        return "B"
    return "B" if after_fix["score"] >= THRESHOLD else "C"


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
    """{charter number: {"owner", "too_big", "stage", "stage_in_plan", "why"}} for the added items, from one match call
    (G0 asked of every workflow; with no owner, the stage from stages.json whose thinking must decide the item).
    stage_in_plan is code's: C when it is in the plan, D when not. An item the reply still lacks after one retry is
    unread."""
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
            elif not isinstance(x.get("too_big", False), bool):
                out.append(f"item {n}: too_big must be true or false")
            elif not x.get("owner") and x.get("stage") not in R.STAGES + (None,):
                out.append(f"item {n}: stage {x['stage']!r} is not a stage id of the stage table")
            else:
                st = None if x.get("owner") else x.get("stage")
                got[n] = {"owner": x.get("owner"), "too_big": bool(x.get("owner") and x.get("too_big")), "stage": st,
                          "stage_in_plan": st in stages, "why": str(x.get("why") or "")}
        if miss := [n for n in items if n not in got]:
            out.append(f"no answer for item {', '.join(map(str, miss))}")
        return got, out

    got, _ = ask_checked(s, "judge", R.judge_system(), R.match_task(goal, plan, items), mock, check)
    return {n: got.get(n) or {"owner": None, "too_big": False, "stage": None, "stage_in_plan": False,
                              "why": "the match reply was unreadable", "unread": True}
            for n in items}


# ---- step 4, act: the owner is edited (a workflow left with nothing is dropped), judged and improved once if needed;
# C and D place new workflows. Each takes the current plan and returns a new one; the caller's plan is never changed.
def _wfs(plan):
    return [w for w in R.lst(plan.get("workflows")) if isinstance(w, dict)]


def planning(wfs):
    """Names of the planning workflows: decide workflows that set their stage's direction, so they read no workflow of
    their own stage (a decide workflow that reads its stage's builds, such as written help, is not one)."""
    stage = {w.get("name"): w.get("stage") for w in wfs}
    return [w["name"] for w in wfs if R.kind(w) == "decide"
            and not any(stage.get(d) == w.get("stage") for d in R.lst(w.get("inputs_from")))]


def _planning(plan, w):
    """The planning workflows w reads (inputs_from), in plan order."""
    return [n for n in planning(_wfs(plan)) if n in R.lst(w.get("inputs_from"))]


def _put(plan, w):
    """The plan with the workflow of w's name replaced by w."""
    return {**plan, "workflows": [w if x.get("name") == w.get("name") else x for x in _wfs(plan)]}


def strip(plan, removed):
    """The plan with removed charter numbers taken out of every workflow's delivers and informs."""
    gone = set(removed)
    return {**plan, "workflows": [{**w, "delivers": [i for i in R.lst(w.get("delivers")) if i not in gone],
                                   "informs": [i for i in R.lst(w.get("informs")) if i not in gone]} for w in _wfs(plan)]}


def _drop(plan, name):
    """(plan without the workflow, the workflows that read it): its readers stop reading it."""
    readers = [w["name"] for w in _wfs(plan) if name in R.lst(w.get("inputs_from"))]
    wfs = [{**w, "inputs_from": [d for d in R.lst(w.get("inputs_from")) if d != name]} for w in _wfs(plan)
           if w.get("name") != name]
    facts = [o for o in R.lst(plan.get("open_facts")) if not (isinstance(o, dict) and o.get("workflow") == name)]
    return {**plan, "workflows": wfs, "open_facts": facts}, readers


def edit(s, goal, plan, owner, added, removed, mock):
    """A: the owner takes on the added charter numbers and lets go of the removed ones. Removed only and left with
    nothing: dropped, no call. Otherwise one scoped edit call (sent back once); code keeps delivers right whatever the
    reply says. {"plan", "docs", "dropped", "readers", "ok"}; ok False when the edit reply stayed unreadable (the
    removal still happens in code; the added items are the caller's to place)."""
    plan = strip(plan, removed)
    w = next(x for x in _wfs(plan) if x.get("name") == owner)
    out = {"plan": plan, "docs": [], "dropped": [], "readers": [], "ok": True}
    if not added and not R.lst(w.get("delivers")) and not R.lst(w.get("informs")):
        out["plan"], out["readers"] = _drop(plan, owner)
        out.update(docs=_planning(plan, w), dropped=[owner])
        return out
    decide = planning(_wfs(plan))

    def check(r):
        new, docs = (r or {}).get("workflow"), (r or {}).get("docs")
        faults = [] if isinstance(new, dict) else ["workflow must be the edited workflow, as one object"]
        if not isinstance(docs, list) or any(d not in decide for d in docs):
            faults.append(f"docs must name planning workflows of the plan only: {', '.join(decide)}")
        return (new, docs), faults

    intents = [{"item": n, "kind": "removed"} for n in removed] + [{"item": n, "kind": "added"} for n in added]
    (new, docs), faults = ask_checked(s, "adaptation", R.planner_system(), R.edit_task(goal, plan, owner, intents),
                                      mock, check)
    if faults:
        out.update(docs=_planning(plan, w), ok=False)
        return out
    new = {**w, **new, "name": owner}
    new["delivers"] = [i for i in R.lst(new.get("delivers")) if i not in removed] + [
        i for i in added if i not in R.lst(new.get("delivers"))]
    new["informs"] = [i for i in R.lst(new.get("informs")) if i not in removed]
    out["plan"], out["docs"] = _put(plan, new), [d for d in decide if d in docs]
    if not new["delivers"] and not new["informs"]:
        out["plan"], out["readers"] = _drop(out["plan"], owner)
        out["dropped"] = [owner]
    return out


def judged(s, goal, plan, checklist, mock, names, change=None, previous=None):
    """{name: the judge's settled result + "weakest_part"} for the named workflows the judge's reply answered; a name
    its reply lacked (after the judge's own retry) is left out, so the caller routes it, never reads a silent 0."""
    sc, faults = s.judge(goal, plan, checklist, mock, previous=previous, names=list(names), change=change)
    lacked = {n for f in faults if f.startswith("no answers for ") for n in f[len("no answers for "):].split(", ")}
    spec = R.judge_spec(plan, checklist, list(names), change)
    return {n: {**sc[n], "weakest_part": weakest_part(sc[n], spec[n])} for n in names if n in sc and n not in lacked}


def improve(s, goal, plan, low, mock):
    """One improvement call for the workflows in low ({name: settled result}), given the judge's missing notes; the
    reply holds only those workflows. Code keeps each one's name, stage and delivers. (plan, names the reply lacked)."""
    def check(r):
        got = {w.get("name"): w for w in R.lst((r or {}).get("workflows")) if isinstance(w, dict) and w.get("name") in low}
        return got, ([f"no improved workflow for {', '.join(n for n in low if n not in got)}"] if len(got) < len(low)
                     else [])

    got, _ = ask_checked(s, "adaptation", R.planner_system(), R.improve_task(goal, plan, low), lambda: mock(list(low)),
                         check)
    for n, w in got.items():
        old = next(x for x in _wfs(plan) if x.get("name") == n)
        plan = _put(plan, {**old, **w, "name": n, "stage": old.get("stage"), "delivers": R.lst(old.get("delivers"))})
    return plan, [n for n in low if n not in got]


def placement_faults(placed, plan, routes=None, stages=None):
    """What a placement breaks beyond the plan rules: new stages are new and each holds its own planning workflow;
    every new workflow reads a planning workflow of its stage (in a stage without one, any planning workflow of the
    plan); new names are new. routes ({item: "C" | "D"}): a C item is delivered in a stage of the plan, a D item in a
    new stage (stages: {item: the stage named for it}, which a D item must use), and a new stage is added only for a
    D item."""
    out = [f"{k} must be a list" for k in ("factors", "stages", "workflows") if not isinstance(placed.get(k), list)]
    new = [w for w in R.lst(placed.get("workflows")) if isinstance(w, dict)]
    if not new:
        out.append("workflows is empty: place every new item")
    have = {x.get("id") for x in R.lst(plan.get("stages")) if isinstance(x, dict)}
    for st in R.lst(placed.get("stages")):
        i = st.get("id") if isinstance(st, dict) else None
        if i in have:
            out.append(f"stage {i} is already in the plan: add only new stages")
        elif not any(w.get("stage") == i and w.get("name") in planning(new) for w in new):
            out.append(f"new stage {i} needs its own decide workflow")
    if routes is not None:
        d_items = [n for n, r in routes.items() if r == "D"]
        if R.lst(placed.get("stages")) and not d_items:
            out.append("add no new stage: every item here goes in a stage already in the plan")
        for w in new:
            for i in R.lst(w.get("delivers")):
                if routes.get(i) == "C" and w.get("stage") not in have:
                    out.append(f"workflow {w.get('name')}: item {i} goes in a stage already in the plan, not "
                               f"{w.get('stage')}")
                elif routes.get(i) == "D" and (w.get("stage") in have or (stages or {}).get(i, w.get("stage")) != w.get("stage")):
                    out.append(f"workflow {w.get('name')}: item {i} goes in the new stage "
                               f"{(stages or {}).get(i) or 'from the stage table'}, not {w.get('stage')}")
    old = [w.get("name") for w in _wfs(plan)]
    every = _wfs(plan) + new
    plans = planning(every)
    for w in new:
        n, reads = w.get("name"), R.lst(w.get("inputs_from"))
        if n in old:
            out.append(f"workflow {n}: the plan already has a workflow of that name")
        own = [x["name"] for x in every if x.get("name") in plans and x.get("stage") == w.get("stage") and x is not w]
        if own and n not in plans and not set(own) & set(reads):
            out.append(f"workflow {n}: list its stage's decide workflow ({', '.join(own)}) in inputs_from")
        elif not own and n not in plans and not set(plans) & set(reads):
            out.append(f"workflow {n}: its stage has no planning decide workflow, so list one of the plan's "
                       f"({', '.join(plans)}) in inputs_from")
    return out


def merge(plan, placed):
    """The plan with the placement's factors, stages and workflows added; a new factor owned by a stage already in
    the plan is added to that stage's owns_factors."""
    factors = [f for f in R.lst(placed.get("factors")) if isinstance(f, dict)]
    stages = [{**x, "owns_factors": R.lst(x.get("owns_factors")) + [f["name"] for f in factors if x.get("id") in
                                                                     R.lst(f.get("stages")) and f.get("name") not in
                                                                     R.lst(x.get("owns_factors"))]}
              for x in R.lst(plan.get("stages")) if isinstance(x, dict)]
    return {**plan, "factors": R.lst(plan.get("factors")) + factors,
            "stages": stages + [x for x in R.lst(placed.get("stages")) if isinstance(x, dict)],
            "workflows": _wfs(plan) + [w for w in R.lst(placed.get("workflows")) if isinstance(w, dict)]}


def place(s, goal, plan, items, active, mock, routes=None, stages=None):
    """C and D: one placement call for the items no workflow takes on, told each item's route, checked on the merged
    plan (placement_faults and plan_faults on the active charter numbers) and sent back once with its faults named.
    (merged plan, the new workflows' names, faults still open)."""
    def check(r):
        placed = r if isinstance(r, dict) else {}
        merged = merge(plan, placed)
        return (merged, placed), placement_faults(placed, plan, routes, stages) + R.plan_faults(merged, goal, items=active)

    (merged, placed), faults = ask_checked(s, "adaptation", R.planner_system(),
                                           R.placement_task(goal, plan, items, routes, stages), mock, check)
    return merged, [w.get("name") for w in R.lst(placed.get("workflows")) if isinstance(w, dict)], faults


# ---- steps 2 to 6: plan a change
def default_mocks(goal, plan, added):
    """Offline replies (llm.MOCK): no workflow owns a new item, so each becomes one new workflow in the stage of the
    plan's last delivering workflow, reading the plan's first planning workflow; the judge answers yes throughout."""
    wfs = _wfs(plan)
    last = next((w for w in reversed(wfs) if R.lst(w.get("delivers"))), wfs[-1] if wfs else {})
    first = planning(wfs)[:1]
    new = [{"name": f"Change item {n}", "stage": last.get("stage"), "certainty": "operate", "certainty_signals": ["mock"],
            "approach": "Direct build from the plan.", "goal": f"Item {n} is real", "done_test": f"Item {n} passes its check",
            "delivers": [n], "informs": [], "inputs_from": first, "experiment": None, "research": None} for n in added]
    return {"match": lambda: json.dumps({"intents": [{"item": n, "owner": None, "too_big": False,
                                                      "stage": last.get("stage"), "why": "mock"} for n in added]}),
            "judge": lambda spec: R.mock_judge(spec, compare="better"),
            "edit": lambda owner: json.dumps({"workflow": next(w for w in wfs if w.get("name") == owner), "docs": []}),
            "improve": lambda names: json.dumps({"workflows": [w for w in wfs if w.get("name") in names], "changes": []}),
            "place": lambda: json.dumps({"factors": [], "stages": [], "workflows": new, "why": "mock"})}


def _owner(plan, workflows, n):
    """The plan workflow that owns charter number n: the run's owner (its revision chain's original name), else the
    plan workflow that delivers it."""
    wid = owner_index(workflows).get(n)
    name = ix_get(workflows, _root_id(workflows, wid))["name"] if wid else None
    names = [w.get("name") for w in _wfs(plan)]
    if name in names:
        return name
    return next((w["name"] for w in _wfs(plan) if n in R.lst(w.get("delivers"))), None)


ROUTE = {"A": "the existing workflow takes it", "B": "the existing workflow, improved once", "C": "a new workflow",
         "D": "a new stage"}


def summary(rec):
    """The change plan in one line for the Requester and the team."""
    said = "; ".join(f"item {x['item']} " + ("dropped" if x["kind"] == "removed" else "left out for now" if
                                             x.get("left_out") else ROUTE[x["final"]])
                     + (f" ({x['owner']})" if x["owner"] and x["final"] in "AB" else "") for x in rec["intents"])
    return (f"{said}. Planning documents first: {', '.join(rec['docs']) or 'none'}; then revise "
            f"{', '.join(rec['revise']) or 'none'}; new {', '.join(rec['new']) or 'none'}"
            + (f"; dropped {', '.join(rec['drop'])}" if rec["drop"] else "") + ".")


def plan_change(base_goal, new_goal, plan, workflows, mocks=None, log=print, out_dir=None):
    """Steps 2 to 6 of a charter change on a realization plan (base_goal: the charter it was planned for; plan: its
    realization plan; workflows: the run's workflows). Step 3 is one match call; code decides each intent: a removed
    item is taken off its owner (A); an added item with an owner that can take it on is edited into the owner and
    judged: passing is A, a size failure is C, else one improvement and a second judgement (B if it passes, else C);
    too big for its owner is C; no owner is C when the stage whose thinking must decide it is in the plan, else D (a
    new stage). Planning docs (planning workflows that a revised or new workflow reads, and new stages' planning
    workflows) are revised first. New workflows below the gate get one improvement call; still below, they and what
    reads them are held (held, as on a first plan) and their items are left out (left_out, with the judge's notes),
    and the rest goes ahead. A goal change, a rule or standard change with no item change, or a plan rule fault the
    retry did not fix is a full re-plan (replan). mocks: {"match", "judge", "edit", "improve", "place"} callables
    for offline runs, used only when llm.MOCK."""
    s = R.Session(log)
    d = charter_diff(base_goal, new_goal)
    rec = {"diff": d, "intents": [], "plan": plan, "revise": [], "new": [], "drop": [], "docs": [], "replan": False,
           "faults": [], "held": {}, "left_out": []}

    def done():
        rec.update(calls=s.calls, seconds=round(s.seconds, 1))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "change.json"), "w", encoding="utf-8") as f:
                json.dump({**rec, "trail": s.trail}, f, ensure_ascii=False, indent=1)
        return rec

    if diff_empty(d):
        return done()
    if d["goal_changed"] or not (d["added"] or d["removed"]):
        rec["replan"] = True
        return done()
    goal, added, removed = new_goal, d["added"], d["removed"]
    mocks = mocks or default_mocks(goal, plan, added)
    active = [n for n, _ in R.numbered(goal)]

    # step 3: one match call for the added items; the routes that need no edit are decided now
    m = match(s, goal, plan, added, mocks["match"]) if added else {}
    for n in removed:
        rec["intents"].append({"item": n, "kind": "removed", "owner": _owner(plan, workflows, n), "stage": None,
                               "too_big": False, "path": ["removed"], "score": None, "after_fix": None, "final": "A",
                               "why": "removed from the charter"})
    for n in added:
        x = m[n]
        first = "edit" if x["owner"] and not x["too_big"] else decide("added", x)
        rec["intents"].append({"item": n, "kind": "added", "owner": x["owner"], "stage": x["stage"],
                               "too_big": x["too_big"], "path": [first], "score": None, "after_fix": None,
                               "final": None if first == "edit" else first, "why": x["why"]})

    # step 4: act. Each owner gets one edit call (its removals and additions together); an owner that took on items
    # is judged, and improved once when below the gate; then C and D are placed together
    cur, docs, revise = strip(plan, removed), [], []
    by_owner = {}
    for x in rec["intents"]:
        if x["owner"] and (x["kind"] == "removed" or x["final"] is None):
            by_owner.setdefault(x["owner"], {"added": [], "removed": []})[x["kind"]].append(x)
    checklist = R.checklist_items(None, goal, items=added)       # one K question per added item, no call
    for o, g in by_owner.items():
        items = [x["item"] for x in g["added"]]
        before = cur
        r = edit(s, goal, cur, o, items, [x["item"] for x in g["removed"]], lambda o=o: mocks["edit"](o))
        route, note, fixed = None, None, r["plan"]
        if items and not r["ok"]:
            route, note = "C", "the edit reply lacked the workflow"
        elif items:
            change = {o: items}
            sc = judged(s, goal, fixed, checklist, mocks["judge"], [o], change).get(o)
            for x in g["added"]:
                x["score"] = sc and sc["score"]
                x["path"].append(f"judged {sc['score']:.2f}" if sc else "judge reply lacked it")
            route = decide("added", {"owner": o}, sc)
            note = None if sc else "the judge's reply lacked the edited workflow"
            if route == "B":
                fixed, lacked = improve(s, goal, fixed, {o: sc}, mocks["improve"])
                after = None if lacked else judged(s, goal, fixed, checklist, mocks["judge"], [o], change,
                                                   previous={"plan": r["plan"], "scores": {o: sc}}).get(o)
                route = decide("added", {"owner": o}, sc, after or {"score": 0.0})
                note = ("the improvement reply lacked the workflow" if lacked else
                        None if after else "the judge's reply lacked the improved workflow")
                for x in g["added"]:
                    x["after_fix"] = after and after["score"]
                    x["path"] += ["improved", f"judged {after['score']:.2f}" if after else "lacked"]
        for x in g["added"]:
            x["final"], x["why"] = route, note or x["why"]
            x["path"].append(route)
        if route == "C":           # the owner keeps what it had, less any removed item; the added items are placed
            w = next(x for x in _wfs(before) if x.get("name") == o)
            fixed, r = before, {"docs": _planning(before, w) if g["removed"] else [], "dropped": [], "readers": []}
            if g["removed"] and not R.lst(w.get("delivers")) and not R.lst(w.get("informs")):
                (fixed, r["readers"]), r["dropped"] = _drop(before, o), [o]
        cur, docs, revise = fixed, docs + r["docs"], revise + r["readers"]
        rec["drop"] += r["dropped"]
        if not r["dropped"] and (route in ("A", "B") or g["removed"]):
            (docs if o in planning(_wfs(cur)) else revise).append(o)      # an edited planning workflow is a doc
    routes = {x["item"]: x["final"] for x in rec["intents"] if x["final"] in ("C", "D")}
    rec["held"], rec["left_out"] = {}, []
    if routes:
        stages = {x["item"]: x["stage"] for x in rec["intents"] if x["item"] in routes and x["stage"]}
        cur, new, faults = place(s, goal, cur, list(routes), active, mocks["place"], routes, stages)
        rec["new"], rec["faults"] = new, faults
        # step 6: the new workflows are judged; those below the gate get one improvement call, then a second look
        if not faults and new:
            ck = R.checklist_items(None, goal, items=list(routes))
            sc = judged(s, goal, cur, ck, mocks["judge"], new, change={})
            low = {n: sc.get(n) or {"score": 0.0, "weakest": None, "missing": ["the judge's reply lacked it"]}
                   for n in new if n not in sc or sc[n]["score"] < R.THRESHOLD}
            if low:
                cur, lacked = improve(s, goal, cur, low, mocks["improve"])
                again = judged(s, goal, cur, ck, mocks["judge"], [n for n in low if n not in lacked], change={})
                # as on a first plan: a workflow still below the gate is not ready, and it and whatever reads it are
                # held; their items are left out with the judge's notes, and the rest of the change goes ahead
                still = {n: again.get(n) or low[n] for n in low if n not in again or again[n]["score"] < R.THRESHOLD}
                rec["held"] = R.holds(cur, list(still)) if still else {}
                for w in _wfs(cur):
                    n = w.get("name")
                    if n in rec["held"]:
                        why = (f"{n} is not ready ({still[n]['score']:.2f}): " + "; ".join(still[n]["missing"][:2])
                               if n in still else f"{n} waits on a workflow that is not ready")
                        rec["left_out"] += [{"item": i, "reason": why} for i in R.lst(w.get("delivers")) if i in routes]
                gone = {x["item"] for x in rec["left_out"]}
                for x in rec["intents"]:
                    if x["item"] in gone:
                        x.update(left_out=True, why=next(y["reason"] for y in rec["left_out"] if y["item"] == x["item"]))
                rec["new"] = new = [n for n in new if n not in rec["held"]]
        wfs = _wfs(cur)
        docs += [n for n in planning(wfs) if n in new]
        for w in wfs:
            if w.get("name") in new:
                docs += _planning(cur, w)

    # steps 5 and 6: planning docs first; the merged plan is checked on the active charter numbers. An edit moves an
    # item to a new number, so every planning doc that informed the old number (strip took it out) is revised too.
    if added and removed:
        docs += [w["name"] for w in _wfs(plan) if w.get("name") in planning(_wfs(plan))
                 and set(removed) & set(R.lst(w.get("informs")))]
    rec["faults"] = list(dict.fromkeys(rec["faults"] + R.plan_faults(cur, goal, items=active)))
    order = [w.get("name") for w in _wfs(cur)]
    rec["docs"] = [n for n in order if n in docs]
    rec["docs"] = [n for n in rec["docs"] if n not in rec["held"]]
    rec["revise"] = [n for n in order if n in revise and n not in rec["docs"] and n not in rec["new"]
                     and n not in rec["held"]]
    rec.update(plan=cur, replan=bool(rec["faults"]))
    log("  change: " + ", ".join(f"{x['item']} {x['final']}" for x in rec["intents"]) + f"; docs {rec['docs']}; "
        f"revise {rec['revise']}; new {rec['new']}; drop {rec['drop']}" + ("; re-plan" if rec["replan"] else ""))
    return done()
