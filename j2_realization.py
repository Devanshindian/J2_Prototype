"""Realization axis for Adaptation (the planning part of agents/j2/adaptation.md, docs/realization-axis.md): plan, check, judge, revise.

plan_goal(goal) runs the planning half on its own, outside J2's loop. Nothing is built here.
1. Adaptation proposes factors, stages and workflows (adaptation.md: its Realization and Certainty sections).
2. Code checks the rules (plan_faults); a plan with faults is sent back once with the faults named.
3. A separate judge call answers a yes/no checklist about every workflow (confidence-judge.md): fixed questions under six
   checks, item questions written once per charter, and one per owned factor. Code computes each score from the
   answers and rolls scores up: a stage is its weakest workflow, the plan its weakest stage. A revision the judge
   calls no better can't score higher; near the gate the judge looks twice and the lower result counts.
4. Below 0.80, Adaptation revises for the weakest check and the judge scores again, up to three rounds.
5. Whatever is still below 0.80 is not_ready and not funded; workflows behind it, and behind a blocking Requester fact,
   are held.
The returned record (and trace.json / report.md when out_dir is given) keeps every round.
"""
import json
import os
import re
import time

import llm

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS = os.path.join(HERE, "agents", "j2")
THRESHOLD = 0.80
MAX_ROUNDS = 3          # revision rounds after the first judgement
TIERS = ("strategy", "capability", "architecture", "feature", "contract", "implementation")


def load_stages():
    """The stage list (agents/j2/stages.json): one entry per kind of thinking Adaptation may plan by."""
    with open(os.path.join(AGENTS, "stages.json"), encoding="utf-8") as f:
        return json.load(f)["stages"]


STAGES = tuple(s["id"] for s in load_stages())


def stage_table():
    """The Realization section's stage table, rendered from stages.json, grouped."""
    st = load_stages()
    rows = ["| Stage | Kind of thinking | Tiers | Output | How to approach | Use it when |", "|---|---|---|---|---|---|"]
    for g in dict.fromkeys(s["group"] for s in st):
        rows.append(f"| **{g}** | | | | | |")
        rows += [f"| `{s['id']}` | {s['thinking']} | {', '.join(t.title() for t in s['tiers'])} | {s['output']} | "
                 f"{s['approach']} | {s['use_when']}" + (f". Note: {s['note']}" if s.get("note") else "") + " |" for s in st
                 if s["group"] == g]
    return "\n".join(rows)
SOURCES = ("brief", "general", "research", "budget")
CHECKS = ("inputs", "method", "done_test", "factors", "zone_fit", "size", "fits")     # fits: G0, on a change only
ANSWERS = ("yes", "partly", "no")
CITATION = re.compile(r"^research\.md#R-\d+$")

# ---- certainty (adaptation.md, Certainty section), the same rule J2_CERTAINTY uses in the earlier prototype
ZONES = ("operate", "analyze", "experiment", "stabilize")       # Cynefin: Clear, Complicated, Complex, Chaotic
SIGNALS = ("broken", "reaction", "facts_given", "known_pattern", "open_choices")
EXPERIMENT_FIELDS = ("hypothesis", "signal", "fails_if", "limit")


def lst(x):
    return x if isinstance(x, list) else []


def as_int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def signal_answer(signals, k):
    """yes, no or unknown, from {"answer": ..., "evidence": ...} or a bare string."""
    v = (signals or {}).get(k)
    a = str((v.get("answer") if isinstance(v, dict) else v) or "unknown").strip().lower()
    return a if a in ("yes", "no") else "unknown"


def certainty_zone(signals):
    """The Certainty section's rule: broken -> stabilize; reaction -> experiment; facts, pattern and no open choices ->
    operate; else analyze. Two or more unknowns move one zone toward less certainty."""
    a = lambda k: signal_answer(signals, k)
    if a("broken") == "yes":
        return "stabilize"
    if a("reaction") == "yes":
        zone = "experiment"
    elif a("facts_given") == "yes" and a("known_pattern") == "yes" and a("open_choices") == "no":
        zone = "operate"
    else:
        zone = "analyze"
    if sum(a(k) == "unknown" for k in SIGNALS) >= 2 and zone in ("operate", "analyze"):
        zone = ZONES[ZONES.index(zone) + 1]
    return zone


def certainty_faults(p):
    """The certainty reading must follow its own signals, and each workflow's shape must match its zone."""
    ca = p.get("certainty_assessment") if isinstance(p.get("certainty_assessment"), dict) else {}
    zone, sig = str(ca.get("zone") or "").lower(), ca.get("signals") if isinstance(ca.get("signals"), dict) else {}
    if zone not in ZONES:
        return [f"certainty_assessment.zone must be one of {', '.join(ZONES)}"]
    out = []
    miss = [k for k in SIGNALS if not isinstance(sig.get(k), dict) or sig[k].get("answer") is None]
    if miss:
        out.append(f"certainty_assessment.signals lacks {', '.join(miss)} (each {{answer: yes|no|unknown, evidence}})")
    elif certainty_zone(sig) != zone:
        out.append(f"your signals give {certainty_zone(sig)} by the Certainty rule, but zone says {zone}: fix "
                   "the signals or the zone, and shape the workflows to match")
    an = p.get("analysis") if isinstance(p.get("analysis"), dict) else {}
    if zone == "analyze" and not (an.get("chosen") and an.get("options")):
        out.append("zone analyze needs analysis with options and chosen")
    wfs = [w for w in lst(p.get("workflows")) if isinstance(w, dict)]
    probes = [w for w in wfs if str(w.get("certainty") or "").lower() == "experiment"]
    if zone == "experiment" and not 1 <= len(probes) <= 3:
        out.append(f"zone experiment needs 1 to 3 experiment workflows (has {len(probes)})")
    for w in wfs:
        n, z = w.get("name") or "?", str(w.get("certainty") or "").lower()
        if z not in ZONES:
            out.append(f"workflow {n}: certainty must be one of {', '.join(ZONES)}")
        elif z == "experiment":
            ex = w.get("experiment") if isinstance(w.get("experiment"), dict) else {}
            if lack := [f for f in EXPERIMENT_FIELDS if not ex.get(f)]:
                out.append(f"workflow {n}: experiment lacks {', '.join(lack)}")
        if not str(w.get("approach") or "").strip():
            out.append(f"workflow {n}: approach is empty")
    return out


# ---- the realization rules (Realization section, Step 2 and "Research workflows")

def kind(w):
    """research, deliver or decide: derived, never stored."""
    return "research" if isinstance(w.get("research"), dict) else "deliver" if lst(w.get("delivers")) else "decide"


def _cycle(wfs):
    """The first workflow found on an inputs_from cycle, or None."""
    deps = {w.get("name"): [d for d in lst(w.get("inputs_from"))] for w in wfs}
    state = {}

    def visit(n):
        state[n] = 1
        for d in deps.get(n, []):
            if state.get(d) == 1 or (d in deps and state.get(d) is None and visit(d)):
                return True
        state[n] = 2
        return False
    return next((n for n in deps if state.get(n) is None and visit(n)), None)


def plan_faults(p, goal, items=None):
    """What a plan breaks: [] when it follows the Realization and Certainty sections. Each fault names what to fix.
    items: the active charter numbers (a change); by default done-when positions 1 to n."""
    out = []
    for k in ("factors", "unplaced", "stages", "workflows", "open_facts"):
        if not isinstance(p.get(k), list):
            out.append(f"{k} must be a list")
    span = None if items is None else ", ".join(map(str, sorted(set(items))))
    items = set(range(1, len(goal.get("done_when") or []) + 1)) if items is None else set(items)
    span = span or f"1 to {len(items)}"
    factors = [f for f in lst(p.get("factors")) if isinstance(f, dict)]
    stages = [s for s in lst(p.get("stages")) if isinstance(s, dict)]
    wfs = [w for w in lst(p.get("workflows")) if isinstance(w, dict)]
    if not factors:
        out.append("factors is empty: list what is consequential to the output")
    if not wfs:
        return out + ["workflows is empty"]

    sid = [s.get("id") for s in stages]
    for x in sorted({x for x in sid if sid.count(x) > 1}, key=str):
        out.append(f"stage {x} appears twice")
    thinking = [str(s.get("thinking") or "").strip().lower() for s in stages]
    for t in sorted({t for t in thinking if t and thinking.count(t) > 1}):
        out.append(f"R3: two stages share the kind of thinking '{t}'")
    for s in stages:
        i = s.get("id")
        if i not in STAGES:
            out.append(f"stage {i!r} is not one of {', '.join(STAGES)}")
            continue
        for k in ("thinking", "goal", "done_test"):
            if not str(s.get(k) or "").strip():
                out.append(f"R6: stage {i} has no {k}")
        if "method" not in s:
            out.append(f"R6: stage {i} has no method (write null when no standard method exists)")
        if not lst(s.get("tiers")) or any(t not in TIERS for t in lst(s.get("tiers"))):
            out.append(f"stage {i}: tiers must be some of {', '.join(TIERS)}")
        for d in lst(s.get("inputs_from")):
            if d not in sid:
                out.append(f"stage {i}: inputs_from names {d}, which is not a stage in this plan")

    owned = {}
    for s in stages:
        for n in lst(s.get("owns_factors")):
            owned.setdefault(n, set()).add(s.get("id"))
    names = [f.get("name") for f in factors]
    for f in factors:
        n, src, xs = f.get("name") or "?", f.get("source"), set(lst(f.get("stages")))
        if src not in SOURCES:
            out.append(f"factor {n}: source must be one of {', '.join(SOURCES)}")
        if src == "brief" and not str(f.get("quote") or "").strip():
            out.append(f"factor {n}: a brief factor quotes the charter")
        if src == "research" and not CITATION.match(str(f.get("citation") or "")):
            out.append(f"factor {n}: a research factor cites its research.md entry (research.md#R-n)")
        if src == "budget":
            if xs:
                out.append(f"factor {n}: budget factors constrain every stage and own none (stages must be [])")
            continue
        if src == "brief" and not owned.get(n):
            out.append(f"R1: brief factor '{n}' is owned by no stage")
        if xs != owned.get(n, set()):
            out.append(f"factor {n}: its stages {sorted(xs)} and the stages that list it in owns_factors "
                       f"{sorted(owned.get(n, set()))} must agree")
    for n in owned:
        if n not in names:
            out.append(f"a stage owns '{n}', which is not in factors")

    wnames = [w.get("name") for w in wfs]
    for x in sorted({x for x in wnames if wnames.count(x) > 1}, key=str):
        out.append(f"workflow name '{x}' appears twice")
    deferred = {as_int(d.get("item")) for d in lst(p.get("deferred")) if isinstance(d, dict)}
    delivered = {}
    for w in wfs:
        n = w.get("name") or "?"
        if w.get("stage") not in sid:
            out.append(f"workflow {n}: stage {w.get('stage')} is not in stages")
        for k in ("goal", "done_test"):
            if not str(w.get(k) or "").strip():
                out.append(f"workflow {n}: {k} is empty")
        for i in lst(w.get("delivers")) + lst(w.get("informs")):
            if i not in items:
                out.append(f"workflow {n}: item {i} does not exist (done-when items are {span})")
        for i in lst(w.get("delivers")):
            delivered.setdefault(i, []).append(n)
        for d in lst(w.get("inputs_from")):
            if d not in wnames:
                out.append(f"workflow {n}: inputs_from names '{d}', which is not a workflow in this plan")
        r = w.get("research")
        if r is not None:
            if not isinstance(r, dict):
                out.append(f"workflow {n}: research must be an object")
                continue
            if lack := [k for k in ("question", "feeds", "output") if not str(r.get(k) or "").strip()]:
                out.append(f"workflow {n}: research lacks {', '.join(lack)}")
            if as_int(r.get("min_sources")) < 3:
                out.append(f"workflow {n}: research needs min_sources of at least 3")
            if r.get("output") and not CITATION.match(str(r.get("output"))):
                out.append(f"workflow {n}: research output is its research.md entry (research.md#R-n)")
            if lst(w.get("delivers")):
                out.append(f"workflow {n}: a research workflow delivers no item; it informs")
            if w.get("stage") == "build":
                out.append(f"workflow {n}: a research workflow sits in the stage that owns the question, never build")
    for i in sorted(items - deferred):
        who = delivered.get(i, [])
        if not who:
            out.append(f"R1: item {i} has no delivering workflow")
        elif len(who) > 1:
            out.append(f"R2: item {i} is delivered by {', '.join(who)}; one delivers, the others inform")
    for s in stages:
        mine = [w for w in wfs if w.get("stage") == s.get("id")]
        if not lst(s.get("owns_factors")) and not any(lst(w.get("delivers")) or lst(w.get("informs")) for w in mine):
            out.append(f"R4: stage {s.get('id')} owns no factor and none of its workflows touches an item")
        if not mine:
            out.append(f"stage {s.get('id')} has no workflows")
    if c := _cycle(wfs):
        out.append(f"workflow {c} is on an inputs_from cycle")
    for o in lst(p.get("open_facts")):
        if not isinstance(o, dict) or o.get("workflow") not in wnames or not isinstance(o.get("blocking"), bool):
            out.append(f"open fact {o!r}: needs fact, workflow (a workflow in this plan), blocking (true|false), "
                       "handling")
    return out + certainty_faults(p)


# ---- the judge's checklist (confidence-judge.md): yes/no answers, code computes the score
# Borrowed: fixed binary questions instead of a free score (CheckEval), code-fixed weights and leaves (DeepEval DAG),
# item questions written once per plan and frozen across rounds (TICK), comparison for revisions, a second look near
# the gate (self-consistency).

BASE = 0.95
CRITICAL = 0.25          # one critical "no" alone puts a workflow below the gate
BORDER = 0.05            # within this of the gate, the judge looks twice and the lower result counts
QUESTIONS = (            # id, check, weight, question
    ("I1", "inputs", 0.25, "Everything it needs is in the charter or made by a workflow it lists in inputs_from."),
    ("I2", "inputs", 0.25, "Nothing it needs is a fact only the Requester knows that the plan neither lists in "
                           "open_facts nor writes as an assumption."),
    ("M1", "method", 0.25, "A known method or pattern, or a decision workflow it reads from, tells it how to make its "
                           "output."),
    ("M2", "method", 0.08, "Where several valid approaches exist, the plan has already chosen one (a decide or analysis "
                           "workflow it reads, or the analysis named in its approach). n/a if only one approach makes "
                           "sense."),
    ("D1", "done_test", 0.25, "The done-test names something observable: a file, page element, section, behaviour or "
                              "document heading."),
    ("D2", "done_test", 0.08, "The done-test states a pass line: a number, a count, an exact text or an explicit "
                              "condition."),
    ("D3", "done_test", 0.10, "The done-test checks behaviour or content, not only that something exists."),
    ("D4", "done_test", 0.06, "Code or Audit can run the done-test without a judgement call."),
    ("Z1", "zone_fit", 0.25, "Its shape matches its certainty zone under the Certainty section: direct build for operate; options "
                             "weighed and one chosen for analyze; hypothesis, signal, fails_if and limit for experiment; "
                             "fix-only for stabilize."),
    ("S1", "size", 0.15, "It needs only one kind of thinking (it does not mix, for example, deciding what to say with "
                         "deciding how it looks)."),
    ("S2", "size", 0.08, "It fits one builder's run: one coherent output, not a bundle of unrelated ones."),
)
CHANGE_QUESTIONS = (     # asked only when the charter changed (j2_change): the owner of a changed item must fit it
    ("G0", "fits", 0.25, "The changed done-when items listed for it under CHANGE are this workflow's own job: the same "
                         "kind of thinking and output as its goal, not a second job added on."),
)
ITEM_WEIGHT, FACTOR_WEIGHT = 0.10, 0.08
JUDGE_ANSWERS = ("yes", "no", "n/a")


def numbered(goal):
    """The active done-when items as (charter number, text): the charter number is the charter_items position + 1, so
    it never moves after a drop (positions when there is no charter_items, as on a first plan)."""
    done = list(goal.get("done_when") or [])
    charter = list(goal.get("charter_items") or done)
    charter += [t for t in done if t not in charter]
    return sorted((charter.index(t) + 1, t) for t in dict.fromkeys(done))


def fallback_checklist(goal, items=None):
    """One item question per done-when item (items: only these charter numbers), for when the checklist call fails."""
    rows = enumerate(goal.get("done_when") or [], 1) if items is None else [(n, t) for n, t in numbered(goal) if n in items]
    return [{"id": f"K{i}", "item": i, "question": f"The done-test verifies, by behaviour or content: {d}"} for i, d in rows]


def checklist_items(r, goal, items=None):
    """The judge's per-plan item questions (TICK), numbered K1..; falls back to one question per item. items: only these
    charter numbers (a change)."""
    want = set(range(1, len(goal.get("done_when") or []) + 1)) if items is None else set(items)
    rows = [x for x in lst((r or {}).get("items")) if isinstance(x, dict)
            and as_int(x.get("item")) in want and str(x.get("question") or "").strip()]
    if {as_int(x["item"]) for x in rows} != want:
        have = {as_int(x["item"]) for x in rows}
        rows += [x for x in fallback_checklist(goal, items) if x["item"] not in have]
    return [{"id": f"K{i}", "item": as_int(x["item"]), "question": str(x["question"]).strip()}
            for i, x in enumerate(sorted(rows, key=lambda x: as_int(x["item"])), 1)]


def question_spec(p, checklist, names=None):
    """Workflow name -> {question id: (check, weight, text)}: the fixed questions, plus K questions for the items it
    delivers and F questions for the factors its stage owns. names: only these workflows."""
    factors = [f for f in lst(p.get("factors")) if isinstance(f, dict)]
    fid = {f.get("name"): f"F{i}" for i, f in enumerate(factors, 1)}
    why = {f.get("name"): f.get("why") or "" for f in factors}
    owns = {s.get("id"): lst(s.get("owns_factors")) for s in lst(p.get("stages")) if isinstance(s, dict)}
    spec = {}
    for w in lst(p.get("workflows")):
        if not isinstance(w, dict) or (names is not None and w.get("name") not in names):
            continue
        q = {i: (c, wt, t) for i, c, wt, t in QUESTIONS}
        for k in checklist:
            if k["item"] in lst(w.get("delivers")):
                q[k["id"]] = ("done_test", ITEM_WEIGHT, k["question"])
        for name in owns.get(w.get("stage"), []):
            if name in fid:
                q[fid[name]] = ("factors", FACTOR_WEIGHT,
                                f"Factor '{name}' ({why[name]}) is addressed: by this workflow, or clearly by another "
                                f"workflow in the {w.get('stage')} stage. Answer no only if no workflow in the stage "
                                "addresses it.")
        spec[w.get("name")] = q
    return spec


def judge_spec(p, checklist, names=None, change=None):
    """question_spec, plus on a change ({workflow: the charter numbers it is asked to take on}) G0 and the K questions
    of those items for each of those workflows."""
    spec = question_spec(p, checklist, names)
    for n, its in (change or {}).items():
        if n in spec:
            spec[n].update({i: (c, wt, t) for i, c, wt, t in CHANGE_QUESTIONS})
            spec[n].update({k["id"]: ("done_test", ITEM_WEIGHT, k["question"]) for k in checklist if k["item"] in its})
    return spec


def judge_faults(r, spec):
    """Answers by workflow name, and what the judge's reply lacks. Unanswered questions count as no."""
    got, out = {}, []
    for a in lst((r or {}).get("answers")):
        n = a.get("workflow") if isinstance(a, dict) else None
        if n not in spec:
            out.append(f"answered {n!r}, which is not a workflow to judge")
            continue
        got[n] = a
    if miss := [n for n in spec if n not in got]:
        out.append(f"no answers for {', '.join(map(str, miss))}")
    for n, a in got.items():
        ans = a.get("a") if isinstance(a.get("a"), dict) else {}
        if bad := [i for i in spec[n] if _answer(ans, i) not in JUDGE_ANSWERS]:
            out.append(f"{n}: {', '.join(bad)} need answer yes|no|n/a")
    return got, out


def _answer(answers, k):
    v = (answers or {}).get(k)
    return str((v.get("answer") if isinstance(v, dict) else v) or "").strip().lower()


def _note(answers, k):
    v = (answers or {}).get(k)
    return str(v.get("note") or "").strip() if isinstance(v, dict) else ""


def settle(a, spec):
    """Code's score from one workflow's answers: 0.95 less the weight of each "no" (unanswered counts as no). A check is
    "no" when a critical question failed or its failures weigh 0.15 or more; any such check keeps the score below
    the gate. weakest is the check that lost the most."""
    ans = (a or {}).get("a") if isinstance((a or {}).get("a"), dict) else {}
    lost, critical, failed = {k: 0.0 for k in CHECKS}, set(), []
    for i, (check, weight, text) in spec.items():
        if _answer(ans, i) in ("yes", "n/a"):
            continue
        lost[check] += weight
        if weight >= CRITICAL:
            critical.add(check)
        failed.append((weight, i, _note(ans, i) or f"{i}: {text}"))
    checks = {k: "no" if k in critical or lost[k] >= 0.15 - 1e-9 else "partly" if lost[k] else "yes" for k in CHECKS}
    score = round(max(0.0, BASE - sum(lost.values())), 2)
    capped = any(v == "no" for v in checks.values()) and score >= THRESHOLD
    if capped:
        score = round(THRESHOLD - 0.01, 2)
    weakest = max(CHECKS, key=lambda k: lost[k]) if any(lost.values()) else None
    return {"score": score, "weakest": weakest, "capped": capped, "checks": checks,
            "missing": [note for _, _, note in sorted(failed, key=lambda x: -x[0])],
            "failed": [i for _, i, _ in sorted(failed, key=lambda x: -x[0])],
            "compare": (a or {}).get("compare")}


def rollup(p, scores):
    """Stage confidence = its weakest workflow; plan confidence = its weakest stage; stage zone = its least certain
    workflow (derived for the Map, never read)."""
    stages = {}
    for w in lst(p.get("workflows")):
        st = stages.setdefault(w.get("stage"), {"confidence": 1.0, "zone": None})
        if w.get("name") in scores:
            st["confidence"] = min(st["confidence"], scores[w["name"]]["score"])
        z = str(w.get("certainty") or "").lower()
        if z in ZONES and (st["zone"] is None or ZONES.index(z) > ZONES.index(st["zone"])):
            st["zone"] = z
    plan = min((s["confidence"] for s in stages.values()), default=0.0)
    return stages, plan


def route(s):
    """Where a workflow still below the gate goes: identity when a Requester fact or decision would close it,
    else priority (a risk Priority may fund explicitly as at_risk)."""
    return "identity" if any(m.lower().startswith("ask:") for m in s["missing"]) else "priority"


def blocked(p):
    """Workflows named by a blocking Requester fact: they wait for Identity's answer."""
    return {o["workflow"] for o in lst(p.get("open_facts"))
            if isinstance(o, dict) and o.get("blocking") is True and o.get("workflow")}


def only_asks(s):
    """Every gap the judge named is a Requester fact: no revision can close it, only Identity's answer."""
    return bool(s["missing"]) and all(m.lower().startswith("ask:") for m in s["missing"])


def holds(p, not_ready):
    """Workflow name -> why it is held: behind a blocking Requester fact, not_ready itself, or downstream of either."""
    wfs = [w for w in lst(p.get("workflows")) if isinstance(w, dict)]
    held = {n: "waiting_on_identity" for n in blocked(p)}
    for n in not_ready:
        held.setdefault(n, "not_ready")
    changed = True
    while changed:
        changed = False
        for w in wfs:
            if w.get("name") not in held and any(d in held for d in lst(w.get("inputs_from"))):
                held[w["name"]] = "waiting_on_dependency"
                changed = True
    return held


# ---- the calls

PLAN_FMT = """{
 "certainty_assessment": {"zone": "operate"|"analyze"|"experiment"|"stabilize", "signals": {"broken"|"reaction"|"facts_given"|"known_pattern"|"open_choices": {"answer": "yes"|"no"|"unknown", "evidence": str}}, "rationale": str},
 "analysis": {"options": [str], "chosen": str, "why": str, "assumptions": [str]}|null,
 "deferred": [{"item": int, "until": str}],
 "factors": [{"name": str, "source": "brief"|"general"|"research"|"budget", "quote": str|null, "citation": str|null, "why": str, "stages": [stage id]}],
 "unplaced": [{"name": str, "why": str}],
 "stages": [{"id": str (a stage id from the stage table in the Realization section), "thinking": str, "tiers": ["strategy"|"capability"|"architecture"|"feature"|"contract"|"implementation"], "goal": str, "done_test": str, "method": str|null, "owns_factors": [factor name], "inputs_from": [stage id]}],
 "workflows": [{"name": str (unique), "stage": stage id, "certainty": zone, "certainty_signals": [str], "approach": str (one sentence), "goal": str, "done_test": str (observable, pass/fail), "delivers": [item number], "informs": [item number], "inputs_from": [workflow name], "experiment": {"hypothesis": str, "signal": str, "fails_if": str, "limit": str}|null, "research": {"question": str, "feeds": str, "min_sources": int (3 or more), "output": "research.md#R-n"}|null}],
 "open_facts": [{"fact": str, "workflow": workflow name, "blocking": bool, "handling": str}],
 "not_ready": []
}"""
REVISE_FMT = PLAN_FMT[:-2] + ',\n "changes": [{"workflow": str, "weakest": str, "remedy": str, "axis": "ask"|"research:find"|"research:method"|"certainty:analyze"|"certainty:experiment"|"certainty:stabilize"|"certainty:reread"|"realization:add"|"realization:deepen"|"realization:split"|"rewrite"}]\n}'
JUDGE_FMT = """{"answers": [{"workflow": str, "a": {"<question id>": {"answer": "yes"|"no"|"n/a", "note": str (required for no: what is missing; start with ask:, research: or probe: when it is missing information)}}, "compare": "better"|"same"|"worse"|null (only for workflows listed under REVISED)}]}"""
CHECKLIST_FMT = """{"items": [{"item": int (done-when number), "question": str}]}"""
EDIT_FMT = """{"workflow": {the edited workflow, with the same keys as the plan's workflows}, "docs": [name of a planning workflow in the plan whose written decision must change first]}"""
PLACE_FMT = """{"factors": [new factor, as in the plan], "stages": [new stage, as in the plan; [] when none], "workflows": [new workflow, as in the plan], "why": str}"""
IMPROVE_FMT = """{"workflows": [each workflow named above, improved, with the same keys as the plan's workflows], "changes": [{"workflow": str, "remedy": str}]}"""
MATCH_FMT = """{"intents": [{"item": int (charter number), "owner": str|null (the one workflow whose job it is), "too_big": bool (true when taking it on would make the owner need more than one kind of thinking or more than one builder's run), "stage": str|null (when owner is null: the id of the stage in the plan whose kind of thinking it needs, or null), "why": str}]}"""


def _read(name):
    with open(os.path.join(AGENTS, name), encoding="utf-8") as f:
        return f.read()


PART = "<!-- {0}:START[^>]*-->\n?(.*?)<!-- {0}:END -->"
PLANNING_PART = re.compile(r"\s*" + PART.format("PLANNING"), re.S)      # stripped from Adaptation's role (j2.py)


def adaptation_part(name):
    """A marked part of adaptation.md: "PLANNING" (all of it), "REALIZATION" or "CERTAINTY"."""
    m = re.search(PART.format(name), _read("adaptation.md"), re.S)
    return m.group(1).strip() if m else ""


def planner_system():
    return ("You are Adaptation in J2, the department's planner. Identity has set the goal; you decide how it becomes "
            "real. Follow the planning part of adaptation.md below exactly: the Realization section says where to cut, "
            "the Certainty section what kind of cut each workflow gets. Reply with one JSON object and nothing else.\n\n"
            + adaptation_part("PLANNING").replace("<!-- STAGE TABLE -->", stage_table()))


def judge_system():
    return (_read("confidence-judge.md") + "\n\nThe Certainty section of adaptation.md, for the zone_fit check:\n\n"
            + adaptation_part("CERTAINTY") + "\n\nReply with one JSON object and nothing else.")


def charter_text(goal, by_number=False):
    """What Adaptation and the judge read of Identity's charter. by_number: items by charter number (a change)."""
    lines = [f"STATEMENT: {goal.get('statement', '')}"]
    for k in ("audience", "standards", "rules"):
        if goal.get(k):
            v = goal[k]
            lines.append(f"{k.upper()}: " + ("; ".join(v) if isinstance(v, list) else str(v)))
    lines.append("DONE WHEN:")
    lines += [f"  {i}. {d}" for i, d in (numbered(goal) if by_number else enumerate(goal.get("done_when") or [], 1))]
    for k in ("open_inputs", "to_be_confirmed"):
        if goal.get(k):
            lines.append(f"{k.upper()}: " + "; ".join(goal[k]))
    return "\n".join(lines)


def _web_note(web):
    return ("WEB ACCESS: research workflows in this run can read outside sources." if web else
            "WEB ACCESS: none in this run. Do not plan research workflows; keep such factors general and mark them "
            "unverified in why.")


def plan_task(goal, web, extra=""):
    return (f"CHARTER (from Identity):\n{charter_text(goal)}\n\n{_web_note(web)}{extra}\n\nPlan how this goal becomes real. "
            "Work through the Realization section's Steps 1 to 3: factors, stages, then workflows inside the stages, each with "
            "its certainty zone. Every done-when item is delivered by exactly one workflow (or deferred). A separate "
            f"judge will score each workflow afterwards; you don't score.\n\nReply format:\n{PLAN_FMT}")


def revise_task(goal, web, plan, low, extra="", only=None):
    """only (a change's one small fix): revise just these workflows, keeping their names; the charter by number."""
    if only is not None:
        low = {n: s for n, s in low.items() if n in only}
    lines = [f"- {n}: score {s['score']:.2f}, weakest {s['weakest']}; missing: " + ("; ".join(s["missing"]) or "-")
             for n, s in low.items()]
    how = ("Revise the plan (the Realization section's Step 5): for each workflow above, apply the remedy "
           "for its weakest check. Keep every other workflow exactly as it is, with the same name. Keep a revised "
           "workflow's name unless you split it." if only is None else
           "Revise only the workflows above, as one small fix (the Realization section's Step 5): apply the remedy for "
           "each one's weakest check without splitting it, and keep its name. Keep every other workflow exactly as it "
           "is, with the same name.")
    return (f"CHARTER (from Identity):\n{charter_text(goal, only is not None)}\n\n{_web_note(web)}{extra}\n\nYOUR CURRENT PLAN:\n"
            f"{json.dumps(plan, ensure_ascii=False)}\n\nTHE JUDGE SCORED THESE WORKFLOWS BELOW {THRESHOLD:.2f}:\n"
            + "\n".join(lines) + f"\n\n{how} Name each change in changes.\n\nReply with the full plan in this "
            f"format:\n{REVISE_FMT}")


def edit_task(goal, plan, owner, intents):
    """A change's A route: a scoped edit of one workflow. intents: [{"item": charter number, "kind": "added"|"removed"}]."""
    texts = dict(enumerate(goal.get("charter_items") or goal.get("done_when") or [], 1))
    lines = [f"- it now also delivers item {x['item']}: {texts.get(x['item'], '')}" if x["kind"] == "added" else
             f"- item {x['item']} ({texts.get(x['item'], '')}) is no longer in the charter: it stops delivering and "
             "informing it" for x in intents]
    return (f"CHARTER (from Identity):\n{charter_text(goal, True)}\n\nTHE PLAN:\n{json.dumps(plan, ensure_ascii=False)}"
            f"\n\nTHE CHANGE FOR WORKFLOW {owner!r}:\n" + "\n".join(lines) + "\n\nEdit only this workflow, as little as the "
            "change needs: modify, extend or remove. Rewrite its goal, approach and done-test to match, add the new items "
            "to delivers and take the removed ones out of delivers and informs. Keep its name, stage and certainty zone. "
            "If it is left with nothing to deliver or inform, return it with both empty: it is dropped. In docs, name the "
            "planning workflows of the plan (decide workflows that set a stage's direction) whose written decision must "
            f"change before this workflow is built again; [] when none must.\n\nReply format:\n{EDIT_FMT}")


def placement_task(goal, plan, items, routes=None):
    """A change's C and D routes: new workflows for these items. routes: {item: "C" | "D"}: a C item goes in a stage
    already in the plan, a D item in a new stage from the stage table (default C)."""
    where = {"C": "in a stage already in the plan", "D": "in a new stage from the stage table"}
    new = "\n".join(f"  {n}. {t} ({where[(routes or {}).get(n, 'C')]})" for n, t in numbered(goal) if n in items)
    return (f"CHARTER (from Identity):\n{charter_text(goal, True)}\n\nTHE PLAN (keep it; add to it):\n"
            f"{json.dumps(plan, ensure_ascii=False)}\n\nNEW DONE-WHEN ITEMS no workflow in the plan owns (charter "
            f"numbers, and where each goes):\n{new}\n\nPlace these items only (the Realization section's Steps 1 to 3). "
            "Put each item's new workflows where it says: in a stage of the plan whose kind of thinking they need, or "
            "in a new stage (add no new stage for any other item). Give each new stage its own decide workflow that "
            "sets its direction. Every new workflow lists in inputs_from a decide workflow of its stage (in a stage without one, "
            "a decide workflow of the plan it follows). Each new item is delivered by exactly one new workflow; each "
            "new workflow gets its certainty zone, read from its own signals. Add factors only for what is new and "
            "consequential. Don't repeat or change anything already in the plan.\n\n"
            f"Reply format:\n{PLACE_FMT}")


def improve_task(goal, plan, low):
    """A change's improvement round: only the workflows in low ({name: the judge's settled result}) are rewritten."""
    lines = [f"- {n}: score {s['score']:.2f}, weakest {s['weakest']}; missing: " + ("; ".join(s["missing"]) or "-")
             for n, s in low.items()]
    return (f"CHARTER (from Identity):\n{charter_text(goal, True)}\n\nTHE PLAN:\n{json.dumps(plan, ensure_ascii=False)}"
            f"\n\nTHE JUDGE SCORED THESE WORKFLOWS BELOW {THRESHOLD:.2f}:\n" + "\n".join(lines) + "\n\nImprove only "
            "these workflows, once (the Realization section's Step 5): close the gaps named, for example by reading a "
            "workflow of the plan that makes what is missing (inputs_from) or by making the done-test checkable. Keep "
            "each one's name, stage and delivers; don't split it. Reply with only these workflows.\n\n"
            f"Reply format:\n{IMPROVE_FMT}")


def checklist_task(goal, items=None):
    which = "each done-when item" if items is None else f"each of done-when items {', '.join(map(str, items))}"
    return (f"CHARTER (from Identity):\n{charter_text(goal, items is not None)}\n\nWrite the item questions for this "
            f"charter: for {which}, 1 to 3 yes/no questions, each asking whether a done-test verifies one concrete, "
            "checkable part of that item. Use the charter's own numbers and words, and ask about behaviour or content, not only "
            "presence. Example, for 'a round lasts exactly 30 seconds, then the end screen appears': 'Does a check "
            "verify that a round ends after exactly 30 seconds?' and 'Does a check verify that the end screen appears "
            "when the round ends?'. The questions are frozen for every round of this plan.\n\n"
            f"Reply format:\n{CHECKLIST_FMT}")


def match_task(goal, plan, items):
    """The change path's first call: G0 for every workflow of the plan, for each new item (charter numbers)."""
    new = "\n".join(f"  {n}. {t}" for n, t in numbered(goal) if n in items)
    return (f"CHARTER (from Identity):\n{charter_text(goal, True)}\n\nTHE PLAN:\n{json.dumps(plan, ensure_ascii=False)}"
            f"\n\nNEW DONE-WHEN ITEMS (charter numbers):\n{new}\n\nFor each new item, ask every workflow in the plan "
            "G0: is this item its own job, the same kind of thinking and output as its goal, so that a small edit of it "
            "would deliver the item? Name the one workflow that answers yes as owner, and say in too_big whether taking "
            "it on would make that workflow need more than one kind of thinking or more than one builder's run. When "
            "no workflow answers yes, owner is null: then name the stage in the plan whose kind of thinking the item "
            "needs, or null when no stage in the plan has it. Don't plan or score anything.\n\n"
            f"Reply format:\n{MATCH_FMT}")


def judge_task(goal, plan, spec, revised, change=None):
    qs = [{"workflow": n, "questions": {i: t for i, (_, _, t) in q.items()}} for n, q in spec.items()]
    rev = ""
    if revised:
        rev = ("\n\nREVISED since the last round: say in compare whether each new version closes the gaps named then "
               "(better, same or worse):\n" + json.dumps(revised, ensure_ascii=False))
    if change:
        rev += ("\n\nCHANGE: the charter changed. Each workflow below was edited to take on the done-when items listed "
                "for it (charter numbers); judge it as written now. G0 asks whether those items are its job at all:\n"
                + json.dumps(change))
    return (f"CHARTER (from Identity):\n{charter_text(goal, change is not None)}\n\n"
            f"THE PLAN:\n{json.dumps(plan, ensure_ascii=False)}\n\n"
            f"QUESTIONS, per workflow (answer every id):\n{json.dumps(qs, ensure_ascii=False)}{rev}\n\n"
            f"Reply format:\n{JUDGE_FMT}")


class Session:
    """One planning run: counts calls and time, and keeps every call for the trace."""

    def __init__(self, log=print):
        self.calls, self.seconds, self.log, self.trail = 0, 0.0, log, []

    def ask(self, who, system, user, mock):
        t0 = time.time()
        raw = llm.ask(system, user, mock, max_tokens=16000, effort="high", json_mode=True)
        dt = time.time() - t0
        self.calls += 1
        self.seconds += dt
        try:
            reply = llm.extract_json(raw)
        except ValueError:
            reply = None
        self.trail.append({"who": who, "seconds": round(dt, 1), "meta": dict(llm.LAST_META),
                           "user": user, "raw": raw, "parsed": reply is not None})
        self.log(f"  {who}: {dt:.0f}s" + ("" if reply is not None else " (reply was not JSON)"))
        return reply

    def plan(self, goal, task, mock):
        """A plan, sent back once with its faults named. Returns (plan, faults still open)."""
        p = self.ask("adaptation", planner_system(), task, mock) or {}
        faults = plan_faults(p, goal)
        if faults:
            self.log(f"  plan faults: {len(faults)}; sent back once")
            p2 = self.ask("adaptation", planner_system(), task + "\n\nTHE PLAN CHECK FAILED:\n- " + "\n- ".join(faults)
                          + "\nFix exactly these and send the whole plan again.", mock) or {}
            f2 = plan_faults(p2, goal)
            if len(f2) <= len(faults) and p2.get("workflows"):
                p, faults = p2, f2
        return p, faults

    def checklist(self, goal, mock):
        """The per-plan item questions (TICK), written once and frozen for every round."""
        return checklist_items(self.ask("judge", judge_system(), checklist_task(goal), mock), goal)

    def _answers(self, goal, plan, spec, revised, mock, change=None):
        task = judge_task(goal, plan, spec, revised, change)
        r = self.ask("judge", judge_system(), task, lambda: mock(spec))
        got, faults = judge_faults(r, spec)
        if faults:
            self.log(f"  judge faults: {len(faults)}; sent back once")
            r2 = self.ask("judge", judge_system(), task + "\n\nYOUR REPLY LACKED:\n- " + "\n- ".join(faults)
                          + "\nAnswer every question id for every workflow.", lambda: mock(spec))
            got2, f2 = judge_faults(r2, spec)
            if len(f2) <= len(faults):
                got, faults = got2, f2
        return {n: settle(got.get(n), q) for n, q in spec.items()}, faults

    def judge(self, goal, plan, checklist, mock, previous=None, names=None, change=None):
        """Scores for every workflow. previous: last round's {"plan", "scores"}. A revised workflow that is not better
        than before can't score higher than before; a workflow within BORDER of the gate is judged again and the
        lower result counts. names: judge only these workflows. change (a charter change, j2_change): {workflow: the
        charter numbers it is asked to take on}; those workflows also get G0 and the K questions of those items, and
        the charter is shown by charter number ({} for numbers alone)."""
        spec = judge_spec(plan, checklist, names, change)
        revised, kept = {}, {}
        if previous:
            old = {w.get("name"): w for w in lst(previous["plan"].get("workflows")) if isinstance(w, dict)}
            for w in lst(plan.get("workflows")):
                n = w.get("name")
                if n not in old or n not in previous["scores"]:
                    continue
                if json.dumps(old[n], sort_keys=True) != json.dumps(w, sort_keys=True):
                    revised[n] = {"previous_version": old[n], "gaps_named": previous["scores"][n]["missing"]}
                elif previous["scores"][n].get("held_by_compare"):
                    kept[n] = previous["scores"][n]["score"]     # unchanged since a revision that didn't help
        scores, faults = self._answers(goal, plan, spec, revised, mock, change)
        for n in revised:
            prev = previous["scores"][n]["score"]
            if str(scores[n].get("compare") or "").lower() in ("same", "worse") and scores[n]["score"] > prev:
                scores[n].update(score=prev, held_by_compare=True)
        for n, prev in kept.items():
            if scores[n]["score"] > prev:
                scores[n].update(score=prev, held_by_compare=True)
        border = {n: q for n, q in spec.items() if abs(scores[n]["score"] - THRESHOLD) < BORDER}
        if border:
            self.log(f"  second look near the gate: {', '.join(border)}")
            again, f2 = self._answers(goal, plan, border, {}, mock, change)
            faults += f2
            for n, s2 in again.items():
                first = scores[n]["score"]
                if s2["score"] < first:
                    scores[n] = s2
                scores[n]["second_look"] = [first, s2["score"]]
        return scores, faults


def plan_goal(goal, web=True, out_dir=None, log=print, mocks=None, extra=""):
    """The planning half of realization for one charter. mocks: {"checklist", "plan", "revise", "judge"} callables for
    offline runs (plan and revise take the round; judge takes the round, the plan and the question spec), used only
    when llm.MOCK. extra: rules of the system the plan runs in (J2 passes its own), added to Adaptation's task."""
    mocks = mocks or default_mocks(goal)
    s = Session(log)
    checklist = s.checklist(goal, lambda: mocks["checklist"]())
    plan, faults = s.plan(goal, plan_task(goal, web, extra), lambda: mocks["plan"](0))
    rounds = [{"round": 0, "plan": plan, "plan_faults": faults, "changes": []}]
    scores, jf = s.judge(goal, plan, checklist, lambda spec: mocks["judge"](0, plan, spec))
    rounds[0].update(scores=scores, judge_faults=jf)
    history = {n: [sc["score"]] for n, sc in scores.items()}
    for rnd in range(1, MAX_ROUNDS + 1):
        # A workflow behind a blocking fact, or whose gaps are all Requester facts, waits for Identity: revising it
        # can't raise its score.
        waiting = blocked(plan)
        low = {n: sc for n, sc in scores.items()
               if sc["score"] < THRESHOLD and n not in waiting and not only_asks(sc)}
        if not low:
            break
        log(f"  round {rnd}: {len(low)} below {THRESHOLD:.2f}: {', '.join(low)}")
        new, faults = s.plan(goal, revise_task(goal, web, plan, low, extra), lambda: mocks["revise"](rnd))
        if not new.get("workflows"):
            log("  the revision came back empty; keeping the last plan")
            break
        previous = {"plan": plan, "scores": scores}
        plan = new
        scores, jf = s.judge(goal, plan, checklist, lambda spec: mocks["judge"](rnd, plan, spec), previous)
        for n, sc in scores.items():
            history.setdefault(n, []).append(sc["score"])
        rounds.append({"round": rnd, "plan": plan, "plan_faults": faults, "changes": lst(new.get("changes")),
                       "scores": scores, "judge_faults": jf})

    waiting = blocked(plan)
    not_ready = [{"workflow": n, "score": sc["score"], "weakest": sc["weakest"],
                  "stop_reason": (sc["missing"] or [f"weakest check: {sc['weakest']}"])[0], "route": route(sc)}
                 for n, sc in scores.items() if sc["score"] < THRESHOLD and n not in waiting]
    held = holds(plan, [x["workflow"] for x in not_ready])
    questions = [{"workflow": n, "score": scores[n]["score"] if n in scores else None,
                  "ask": [m for m in scores.get(n, {}).get("missing", []) if m.lower().startswith("ask:")]
                  or [o.get("fact") for o in lst(plan.get("open_facts")) if isinstance(o, dict) and o.get("workflow") == n]}
                 for n in sorted(waiting, key=str)]
    stages, plan_conf = rollup(plan, scores)
    result = {
        "goal": goal.get("statement"), "web": web, "provider": llm.PROVIDER, "model": llm.MODEL, "mock": llm.MOCK,
        "checklist": checklist,
        "plan": plan, "scores": scores, "history": history, "rounds": rounds, "not_ready": not_ready, "held": held,
        "waiting_on_identity": questions,
        "stages": stages, "plan_confidence": plan_conf, "plan_faults": rounds[-1]["plan_faults"],
        "calls": s.calls, "seconds": round(s.seconds, 1),
    }
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "trace.json"), "w", encoding="utf-8") as f:
            json.dump({**result, "trail": s.trail}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
            f.write(report(result))
    return result


# ---- decide workflows, done as Adaptation's analysis before the build (in J2 a function's thinking is not priced;
# building is). The written decisions are what build workflows read.

DECIDE_FMT = """{"decisions": [{"workflow": str (a decide workflow's name), "decision": str (the question it closes), "options": [{"option": str, "for": str, "against": str}] (2 or more), "chosen": str, "why": str, "failure_cases": [str] (1 or more: how this choice could still go wrong), "rules_for_builders": [str] (concrete things every workflow that reads it must do)}]}"""


def decide_workflows(p):
    return [w for w in lst(p.get("workflows")) if isinstance(w, dict) and kind(w) == "decide"]


def decision_faults(r, p):
    """Decisions by workflow name, and what the reply lacks: each decide workflow needs its question, 2+ options, the
    choice and why, 1+ failure case and 1+ rule for builders."""
    names = {w.get("name") for w in decide_workflows(p)}
    got, out = {}, []
    for d in lst((r or {}).get("decisions")):
        n = d.get("workflow") if isinstance(d, dict) else None
        if n not in names:
            out.append(f"decision for {n!r}, which is not a decide workflow in the plan")
            continue
        if len([o for o in lst(d.get("options")) if isinstance(o, dict) and str(o.get("option") or "").strip()]) < 2:
            out.append(f"{n}: weigh at least 2 options")
        for k in ("decision", "chosen", "why"):
            if not str(d.get(k) or "").strip():
                out.append(f"{n}: {k} is empty")
        for k in ("failure_cases", "rules_for_builders"):
            if not [x for x in lst(d.get(k)) if str(x).strip()]:
                out.append(f"{n}: {k} needs at least one entry")
        got[n] = d
    if miss := [n for n in names if n not in got]:
        out.append(f"no decision for {', '.join(map(str, miss))}")
    return got, out


def decide_task(goal, p):
    wfs = [{k: w.get(k) for k in ("name", "stage", "certainty", "approach", "goal", "done_test", "informs", "inputs_from")}
           for w in decide_workflows(p)]
    return (f"CHARTER (from Identity):\n{charter_text(goal)}\n\nTHE JUDGED PLAN:\n{json.dumps(p, ensure_ascii=False)}\n\n"
            f"DO THE WORK OF THESE DECIDE WORKFLOWS NOW, as written analysis, in order (a decision that reads another "
            f"follows it):\n{json.dumps(wfs, ensure_ascii=False)}\nEach decision must meet its workflow's done_test. "
            "Facts come from the charter only; anything else is an assumption and says so. rules_for_builders are "
            "what the build workflows that read this decision will be held to, so make them concrete and checkable."
            f"\n\nReply format:\n{DECIDE_FMT}")


def run_decisions(goal, p, log=print, mock=None):
    """The decide workflows' work, one call (sent back once with its faults named). {"decisions": {name: entry},
    "faults", "calls", "seconds", "trail"}."""
    s = Session(log)
    if not decide_workflows(p):
        return {"decisions": {}, "faults": [], "calls": 0, "seconds": 0.0, "trail": []}
    mock = mock or (lambda: mock_decisions(p))
    task = decide_task(goal, p)
    got, faults = decision_faults(s.ask("adaptation", planner_system(), task, mock), p)
    if faults:
        log(f"  decision faults: {len(faults)}; sent back once")
        got2, f2 = decision_faults(s.ask("adaptation", planner_system(), task + "\n\nTHE DECISIONS LACKED:\n- "
                                         + "\n- ".join(faults) + "\nSend every decision again.", mock), p)
        if len(f2) <= len(faults):
            got, faults = got2, f2
    return {"decisions": got, "faults": faults, "calls": s.calls, "seconds": round(s.seconds, 1), "trail": s.trail}


def decisions_md(decisions):
    out = ["# Decisions", "", "Written by Adaptation before the build; each build workflow follows the ones it reads.", ""]
    for n, d in decisions.items():
        out += [f"## {n}", "", f"**Decision:** {d.get('decision')}", "", "**Options:**"]
        out += [f"- {o.get('option')}: for {o.get('for') or '-'}; against {o.get('against') or '-'}"
                for o in lst(d.get("options")) if isinstance(o, dict)]
        out += ["", f"**Chosen:** {d.get('chosen')}", "", f"**Why:** {d.get('why')}", "", "**Could still fail if:**"]
        out += [f"- {x}" for x in lst(d.get("failure_cases"))]
        out += ["", "**Rules for builders:**"] + [f"- {x}" for x in lst(d.get("rules_for_builders"))] + [""]
    return "\n".join(out)


def decisions_for(p, decisions, names=(), items=()):
    """The decisions a build workflow follows: decide workflows upstream of it by inputs_from, or that inform an item it
    delivers (so a renamed workflow still gets the decisions about its items)."""
    by = {w.get("name"): w for w in lst(p.get("workflows")) if isinstance(w, dict)}
    up, stack = set(), [n for n in names if n in by]
    while stack:
        for d in lst(by[stack.pop()].get("inputs_from")):
            if d not in up and d in by:
                up.add(d)
                stack.append(d)
    return [{"from": n, "decision": d.get("decision"), "chosen": d.get("chosen"),
             "rules_for_builders": lst(d.get("rules_for_builders")), "could_fail_if": lst(d.get("failure_cases"))}
            for n, d in decisions.items() if n in up or set(lst(by.get(n, {}).get("informs"))) & set(items)]


def run_order(wfs):
    """The plan's workflows in dependency order (plan order kept among those ready together), so J2 numbers them
    W-1, W-2, ... in the order they can run."""
    names, out, done = {w.get("name") for w in wfs}, [], set()
    while len(out) < len(wfs):
        ready = [w for w in wfs if w.get("name") not in done
                 and all(d in done or d not in names for d in lst(w.get("inputs_from")))]
        nxt = ready[0] if ready else next(w for w in wfs if w.get("name") not in done)    # a cycle: plan order
        out.append(nxt)
        done.add(nxt.get("name"))
    return out


def proposal_brief(result, decisions=None, answered=False):
    """What Adaptation's J2 proposal follows: every workflow of the judged plan that is not held, in run order, each
    as a plain J2 workflow (Adaptation names its output), and the items to leave out with why. answered: Identity has
    answered the blocking facts, so the workflows waiting on them are proposed too. decisions: unused (kept for older
    callers)."""
    p, held = result["plan"], result["held"]
    wfs = run_order([w for w in lst(p.get("workflows")) if isinstance(w, dict)])
    names = {w.get("name") for w in wfs}
    go = [w for w in wfs if w.get("name") not in held or (answered and held[w["name"]] != "not_ready")]
    gone = {w.get("name") for w in go}
    left = [{"item": i, "reason": f"{w.get('name')} is {held[w['name']].replace('_', ' ')}: "
                                  + ("; ".join(result["scores"].get(w["name"], {}).get("missing", [])[:2]) or "see realization.md")}
            for w in wfs if w.get("name") not in gone for i in lst(w.get("delivers"))]
    rows = [{"name": w.get("name"), "stage": w.get("stage"), "certainty": w.get("certainty"), "approach": w.get("approach"),
             "goal": w.get("goal"), "done_test": w.get("done_test"), "covers": lst(w.get("delivers")),
             "informs": lst(w.get("informs")), "after": [d for d in lst(w.get("inputs_from")) if d in names],
             **({"experiment": w["experiment"]} if isinstance(w.get("experiment"), dict) else {})} for w in go]
    return rows, left


# ---- the report a person reads

def _cell(x):
    return str(x).replace("|", "/").replace("\n", " ")


def report(r):
    p, sc = r["plan"], r["scores"]
    out = [f"# Realization plan: {_cell(r['goal'])}", "",
           f"Plan confidence **{r['plan_confidence']:.2f}** · {len(lst(p.get('workflows')))} workflows · "
           f"{len(r['rounds']) - 1} revision round(s) · {r['calls']} AI calls · {r['seconds']:.0f}s · "
           f"{r['model'] or 'mock'}{' (mock)' if r['mock'] else ''} · web {'on' if r['web'] else 'off'}", ""]
    ca = p.get("certainty_assessment") or {}
    out += [f"Goal zone: `{ca.get('zone')}`. {_cell(ca.get('rationale') or '')}", "", "## Factors", "",
            "| Factor | Source | Stages | Why |", "|---|---|---|---|"]
    out += [f"| {_cell(f.get('name'))} | {f.get('source')} | {', '.join(lst(f.get('stages'))) or '-'} | "
            f"{_cell(f.get('why'))} |" for f in lst(p.get("factors")) if isinstance(f, dict)]
    if lst(p.get("unplaced")):
        out += ["", "Unplaced: " + "; ".join(_cell(u.get("name")) for u in lst(p.get("unplaced")) if isinstance(u, dict))]
    out += ["", "## Stages", "", "| Stage | Thinking | Zone (derived) | Confidence | Owns |", "|---|---|---|---|---|"]
    for s in lst(p.get("stages")):
        st = r["stages"].get(s.get("id"), {})
        out.append(f"| {s.get('id')} | {_cell(s.get('thinking'))} | {st.get('zone')} | "
                   f"{st.get('confidence', 0):.2f} | {_cell(', '.join(lst(s.get('owns_factors'))) or '-')} |")
    out += ["", "## Workflows", "", "| Workflow | Stage | Kind | Zone | Delivers | Informs | Reads | Scores | Held |",
            "|---|---|---|---|---|---|---|---|---|"]
    for w in lst(p.get("workflows")):
        n = w.get("name")
        hist = " → ".join(f"{x:.2f}" for x in r["history"].get(n, []))
        out.append(f"| {_cell(n)} | {w.get('stage')} | {kind(w)} | {w.get('certainty')} | "
                   f"{', '.join(map(str, lst(w.get('delivers')))) or '-'} | {', '.join(map(str, lst(w.get('informs')))) or '-'} | "
                   f"{_cell(', '.join(lst(w.get('inputs_from')))) or '-'} | {hist} | {r['held'].get(n, '')} |")
    for w in lst(p.get("workflows")):
        if kind(w) == "research":
            q = w["research"]
            out += ["", f"Research **{_cell(w.get('name'))}** ({w.get('stage')}): {_cell(q.get('question'))} → feeds "
                        f"{_cell(q.get('feeds'))}"]
    def flags(s):
        f = [" (capped)"] if s["capped"] else []
        if s.get("second_look"):
            f.append(" (looked twice: " + " / ".join(f"{x:.2f}" for x in s["second_look"]) + ")")
        if s.get("held_by_compare"):
            f.append(" (revision not better: held at the last score)")
        return "".join(f)
    out += ["", "## Judge, last round", "", "| Workflow | Score | Weakest | Failed | Missing |", "|---|---|---|---|---|"]
    out += [f"| {_cell(n)} | {s['score']:.2f}{flags(s)} | {s['weakest'] or '-'} | {', '.join(s['failed']) or '-'} | "
            f"{_cell('; '.join(s['missing'])) or '-'} |" for n, s in sc.items()]
    if r.get("checklist"):
        out += ["", "Item questions (frozen for this plan): " + "; ".join(
            f"{k['id']} (item {k['item']}): {_cell(k['question'])}" for k in r["checklist"])]
    for rd in r["rounds"][1:]:
        out += ["", f"## Round {rd['round']} changes", ""]
        out += [f"- **{_cell(c.get('workflow'))}** ({c.get('weakest')}, `{c.get('axis')}`): {_cell(c.get('remedy'))}"
                for c in rd["changes"] if isinstance(c, dict)] or ["- (none named)"]
    if r.get("waiting_on_identity"):
        out += ["", "## Waiting on Identity (held until the Requester answers, then judged again)", ""]
        out += [f"- **{_cell(x['workflow'])}**" + (f" {x['score']:.2f}" if x["score"] is not None else "") + ": "
                + _cell("; ".join(str(a) for a in x["ask"]) or "-") for x in r["waiting_on_identity"]]
    if r["not_ready"]:
        out += ["", "## Not ready (not funded)", ""]
        out += [f"- **{_cell(x['workflow'])}** {x['score']:.2f}, weakest {x['weakest']}, route {x['route']}: "
                f"{_cell(x['stop_reason'])}" for x in r["not_ready"]]
    if lst(p.get("open_facts")):
        out += ["", "## Open facts", ""]
        out += [f"- {_cell(o.get('fact'))} ({'blocking' if o.get('blocking') else 'non-blocking'}, "
                f"{_cell(o.get('workflow'))}): {_cell(o.get('handling'))}" for o in lst(p.get("open_facts")) if isinstance(o, dict)]
    if lst(p.get("deferred")):
        out += ["", "Deferred: " + "; ".join(f"item {d.get('item')} until {_cell(d.get('until'))}"
                                             for d in lst(p.get("deferred")) if isinstance(d, dict))]
    if r["plan_faults"]:
        out += ["", "## Plan faults still open", ""] + [f"- {_cell(f)}" for f in r["plan_faults"]]
    return "\n".join(out) + "\n"


# ---- offline replies (llm.MOCK): a plain plan, and a judge that passes everything on the second look

def mock_plan(goal):
    n = len(goal.get("done_when") or [])
    quote = (goal.get("statement") or "the goal")[:60]
    sig = {k: {"answer": a, "evidence": "mock"} for k, a in
           zip(SIGNALS, ("no", "no", "yes", "yes", "yes"))}
    wfs = [{"name": "Plan", "stage": "product", "certainty": "analyze", "certainty_signals": ["mock"],
            "approach": "Weigh the options and choose the structure first.", "goal": "One plan every build follows",
            "done_test": "Every done-when item has a place in the plan", "delivers": [], "informs": list(range(1, n + 1)),
            "inputs_from": [], "experiment": None, "research": None}]
    wfs += [{"name": f"Build item {i}", "stage": "build", "certainty": "operate", "certainty_signals": ["mock"],
             "approach": "Direct build from the plan.", "goal": f"Item {i} is real", "done_test": f"Item {i} passes its check",
             "delivers": [i], "informs": [], "inputs_from": ["Plan"], "experiment": None, "research": None}
            for i in range(1, n + 1)]
    return {"certainty_assessment": {"zone": "analyze", "signals": sig, "rationale": "Mock reading."},
            "analysis": {"options": ["a", "b"], "chosen": "a", "why": "mock", "assumptions": []}, "deferred": [],
            "factors": [{"name": "the goal", "source": "brief", "quote": quote, "citation": None, "why": "mock",
                         "stages": ["product"]}],
            "unplaced": [],
            "stages": [{"id": "product", "thinking": "users", "tiers": ["capability", "feature"], "goal": "A plan",
                        "done_test": "Plan covers every item", "method": "story mapping", "owns_factors": ["the goal"],
                        "inputs_from": []},
                       {"id": "build", "thinking": "making", "tiers": ["implementation"], "goal": "Every item built",
                        "done_test": "Checks pass", "method": "builder checks", "owns_factors": [],
                        "inputs_from": ["product"]}],
            "workflows": wfs, "open_facts": [], "not_ready": []}


def mock_decisions(p):
    return json.dumps({"decisions": [
        {"workflow": w.get("name"), "decision": f"How to approach {w.get('name')}",
         "options": [{"option": "a", "for": "simple", "against": "plain"}, {"option": "b", "for": "rich", "against": "costly"}],
         "chosen": "a", "why": "mock", "failure_cases": ["mock: visitors miss it"],
         "rules_for_builders": ["mock: keep every charter fact exact"]} for w in decide_workflows(p)]})


def mock_judge(spec, fail=None, note="no step for the goal", compare=None):
    """yes to every question, except fail: {workflow: [question ids]} answered no with the note."""
    fail = fail or {}
    return json.dumps({"answers": [
        {"workflow": n, "a": {i: {"answer": "no", "note": note} if i in fail.get(n, ()) else {"answer": "yes", "note": ""}
                              for i in q}, "compare": compare}
        for n, q in spec.items()]})


def default_mocks(goal):
    """The first build workflow fails D1 (critical: 0.70) on the first look and passes (0.95) after one revision."""
    def plan(rnd):
        p = mock_plan(goal)
        if rnd:
            p["workflows"][1]["done_test"] = "Item 1 is on the page and its check passes"
            p["changes"] = [{"workflow": "Build item 1", "weakest": "done_test", "remedy": "mock: named what to check",
                             "axis": "rewrite"}]
        return json.dumps(p)
    return {"plan": plan, "revise": plan,
            "checklist": lambda: json.dumps({"items": [{"item": i, "question": f"Is item {i} checked?"}
                                                       for i in range(1, len(goal.get("done_when") or []) + 1)]}),
            "judge": lambda rnd, p, spec: mock_judge(spec, fail={"Build item 1": ["D1"]} if rnd == 0 else None,
                                                     compare="better")}
