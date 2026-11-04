"""Offline checks of the realization planner (j2_realization.py): python realization_test.py

The rules (plan_faults), the judge's cap and roll-ups, holds and routes, the planning part of agents/j2/adaptation.md,
and whole planning runs in mock mode: a plan that passes on the second look and one that never passes. No AI calls.
"""
import copy
import json
import os
import re
import sys
import tempfile

os.environ["STUDIO_MOCK"] = "1"          # before llm is imported
os.environ.pop("STUDIO_PROVIDER", None)
import j2_realization as R               # noqa: E402

GOAL = {"statement": "A coffee shop site", "done_when": ["menu", "hours and location", "signature drinks", "contact form"]}
passed = 0


def ok(cond, label):
    global passed
    if not cond:
        sys.exit(f"FAIL: {label}")
    passed += 1


def faults_of(mutate, goal=GOAL):
    p = R.mock_plan(goal)
    mutate(p)
    return R.plan_faults(p, goal)


def has(faults, text):
    return any(text in f for f in faults)


def wf(p, name):
    return next(w for w in p["workflows"] if w["name"] == name)


# ---- the rules
ok(R.plan_faults(R.mock_plan(GOAL), GOAL) == [], "the mock plan follows every rule")
ok(has(faults_of(lambda p: wf(p, "Build item 2").update(delivers=[1, 2])), "R2: item 1"), "R2: double delivery")
ok(has(faults_of(lambda p: wf(p, "Build item 3").update(delivers=[])), "R1: item 3"), "R1: item with no delivery")
ok(not has(faults_of(lambda p: (wf(p, "Build item 3").update(delivers=[]), p.update(deferred=[{"item": 3, "until": "probe"}]))),
           "R1: item 3"), "a deferred item needs no delivery now")
ok(has(faults_of(lambda p: wf(p, "Build item 1").update(delivers=[9])), "item 9 does not exist"), "unknown item")
ok(has(faults_of(lambda p: wf(p, "Build item 1").update(inputs_from=["Nope"])), "'Nope'"), "unknown inputs_from")
ok(has(faults_of(lambda p: wf(p, "Plan").update(inputs_from=["Build item 1"])), "cycle"), "inputs_from cycle")
ok(has(faults_of(lambda p: p["stages"][1].update(thinking="users")), "R3"), "R3: shared kind of thinking")
ok(has(faults_of(lambda p: p["stages"][0].pop("method")), "R6: stage product has no method"), "R6: method key required")
ok(has(faults_of(lambda p: p["stages"][0].update(owns_factors=[])), "R1: brief factor"), "R1: brief factor unowned")
ok(has(faults_of(lambda p: p["factors"][0].update(stages=["build"])), "must agree"), "factor and owner disagree")
ok(has(faults_of(lambda p: p["factors"][0].update(quote="")), "quotes the charter"), "brief factor needs a quote")
ok(has(faults_of(lambda p: p["factors"].append({"name": "x", "source": "research", "why": "y", "stages": []})),
       "research.md#R-n"), "research factor needs a citation")
ok(has(faults_of(lambda p: p["factors"].append({"name": "t", "source": "budget", "why": "y", "stages": ["build"]})),
       "budget factors"), "budget factors own no stage")


def research(p, **kw):
    w = {"name": "Look up", "stage": "product", "certainty": "analyze", "approach": "Read 3 sources.", "goal": "g",
         "done_test": "entry written", "delivers": [], "informs": [3], "inputs_from": [],
         "research": {"question": "q", "feeds": "Plan", "min_sources": 3, "output": "research.md#R-1"}}
    w.update(kw)
    p["workflows"].append(w)
    wf(p, "Plan")["inputs_from"] = ["Look up"]


ok(faults_of(research) == [], "a well-formed research workflow passes")
ok(has(faults_of(lambda p: research(p, delivers=[3])), "delivers no item"), "research delivers nothing")
ok(has(faults_of(lambda p: research(p, stage="build")), "never build"), "research is never in build")
ok(has(faults_of(lambda p: research(p, research={"question": "q", "feeds": "f", "min_sources": 2,
                                                  "output": "research.md#R-1"})), "min_sources"), "3+ sources")
ok(R.kind({"research": {}}) == "research" and R.kind({"delivers": [1]}) == "deliver" and R.kind({}) == "decide",
   "kind is derived")
ok(has(faults_of(lambda p: p["certainty_assessment"].update(zone="operate")), "your signals give analyze"),
   "certainty: zone must follow the signals")
ok(has(faults_of(lambda p: wf(p, "Plan").update(approach="")), "approach is empty"), "certainty: approach required")

# ---- no worked scenario in the planner's prompt: the plan comes from the charter, realization and certainty only
doc = R.adaptation_part("PLANNING")
ok("```json" not in doc and not re.search(r"coffee|cafe|sudoku", R.planner_system(), re.I),
   "the planning part of adaptation.md carries no example plan for any scenario")
# ---- realization and certainty live in adaptation.md: the planner gets both, the judge certainty, Adaptation's role neither
ok(not os.path.exists(os.path.join(R.AGENTS, "realization.md")) and not os.path.exists(os.path.join(R.AGENTS, "certainty.md"))
   and R.adaptation_part("REALIZATION") and R.adaptation_part("CERTAINTY")
   and R.adaptation_part("REALIZATION") in R.adaptation_part("PLANNING")
   and R.adaptation_part("CERTAINTY") in R.adaptation_part("PLANNING"),
   "realization and certainty are two sections of adaptation.md, not separate files")
ok("The four zones" in R.planner_system() and "Step 1: factors" in R.planner_system()
   and "The four zones" in R.judge_system() and "Step 1: factors" not in R.judge_system(),
   "the planner reads both sections; the judge reads the Certainty section only")

# ---- the judge: checklist, code-computed scores, roll-up, holds, route
p = R.mock_plan(GOAL)
checklist = R.checklist_items(json.loads(R.default_mocks(GOAL)["checklist"]()), GOAL)
spec = R.question_spec(p, checklist)
ok(set(spec["Build item 2"]) == {q[0] for q in R.QUESTIONS} | {"K2"}, "a build workflow gets the fixed questions + "
   "the item question for what it delivers")
ok("F1" in spec["Plan"] and "F1" not in spec["Build item 1"], "factor questions go to the stage that owns the factor")
ok([k["id"] for k in R.checklist_items({"items": [{"item": 2, "question": "q"}]}, GOAL)] == ["K1", "K2", "K3", "K4"],
   "missing item questions fall back to one per item")


def score(fail, q=None):
    q = q or spec["Build item 1"]
    return R.settle(json.loads(R.mock_judge({"x": q}, fail={"x": fail}))["answers"][0], q)


ok(score([])["score"] == 0.95 and score([])["weakest"] is None, "all yes: 0.95")
s = score(["D1"])
ok(s["score"] == 0.70 and s["checks"]["done_test"] == "no" and s["weakest"] == "done_test", "a critical no: 0.70")
ok(score(["D3"])["score"] == 0.85 and score(["D3"])["checks"]["done_test"] == "partly", "a minor no: 0.85, partly")
s = score(["D3", "K1"])
ok(s["score"] == 0.75 and s["failed"][0] in ("D3", "K1"), "behaviour unchecked and item unverified: 0.75")
s = score(["D2", "D4"])
ok(s["checks"]["done_test"] == "partly" and s["score"] == 0.81, "two small failures under 0.15: partly, 0.81")
s = score(["S1"])
ok(s["checks"]["size"] == "no" and s["capped"] and s["score"] == 0.79, "a 0.15 failure is a no: 0.80 capped to 0.79")
s = R.settle({"a": {}}, spec["Build item 1"])
ok(s["score"] == 0 and len(s["failed"]) == len(spec["Build item 1"]), "unanswered questions count as no")
s = score(["I2"])
s["missing"] = ["ask: the price"]
ok(R.route(s) == "identity", "an ask: gap routes to Identity")
s["missing"] = ["research: x"]
ok(R.route(s) == "priority", "other gaps go to Priority")
_, faults = R.judge_faults({"answers": [{"workflow": "Plan", "a": {"I1": {"answer": "maybe"}}}, {"workflow": "Nope"}]},
                           spec)
ok(has(faults, "no answers for") and has(faults, "need answer") and has(faults, "'Nope'"), "judge reply faults")
sc = {w["name"]: {"score": 0.9} for w in p["workflows"]}
sc["Build item 2"]["score"] = 0.7
stages, conf = R.rollup(p, sc)
ok(conf == 0.7 and stages["product"]["confidence"] == 0.9 and stages["product"]["zone"] == "analyze",
   "weakest-link roll-up; stage zone derived")
p["open_facts"] = [{"fact": "price", "workflow": "Plan", "blocking": True, "handling": "ask"}]
h = R.holds(p, [])
ok(h["Plan"] == "waiting_on_identity" and h["Build item 4"] == "waiting_on_dependency", "a blocking fact holds its branch")
p["open_facts"] = []
ok(R.holds(p, ["Build item 1"]) == {"Build item 1": "not_ready"}, "not_ready holds only what reads from it")

# ---- whole runs (mock)
log = lambda *_: None
r = R.plan_goal(GOAL, log=log)
ok(r["history"]["Build item 1"] == [0.70, 0.95] and not r["not_ready"] and r["calls"] == 5 and len(r["rounds"]) == 2,
   "checklist + plan + judge, then one revision passes (5 calls)")
ok(r["plan_confidence"] == 0.95 and "Plan confidence **0.95**" in R.report(r) and len(r["checklist"]) == 4,
   "roll-up, report and frozen checklist")
never = R.default_mocks(GOAL)
never["judge"] = lambda rnd, p, spec: R.mock_judge(spec, fail={"Plan": ["M1"]})
r = R.plan_goal(GOAL, log=log, mocks=never)
ok(len(r["rounds"]) == R.MAX_ROUNDS + 1 and [x["workflow"] for x in r["not_ready"]] == ["Plan"],
   "still below after three rounds: not_ready")
ok(len(r["held"]) == 5 and r["held"]["Build item 2"] == "waiting_on_dependency", "everything that reads it is held")
same = R.default_mocks(GOAL)     # the revision changes the workflow, the judge says it is no better, yet answers all yes
same["judge"] = lambda rnd, p, spec: R.mock_judge(spec, fail={"Build item 1": ["D1"]} if rnd == 0 else None,
                                                 compare="same")
r = R.plan_goal(GOAL, log=log, mocks=same)
ok(r["history"]["Build item 1"] == [0.70] * (R.MAX_ROUNDS + 1) and r["scores"]["Build item 1"].get("held_by_compare")
   and r["not_ready"][0]["workflow"] == "Build item 1",
   "a revision the judge calls 'same' can't score higher, and stays held while unchanged")
border = R.default_mocks(GOAL)   # first look 0.81 (two small failures), second look 0.70: the lower counts
looks = []
border["judge"] = lambda rnd, p, spec: (looks.append(1), R.mock_judge(
    spec, fail={"Plan": ["D2", "D4"] if len(looks) == 1 else ["D1"]}))[1]
r = R.plan_goal(GOAL, log=log, mocks=border)
ok(r["rounds"][0]["scores"]["Plan"]["second_look"] == [0.81, 0.70] and r["history"]["Plan"][0] == 0.70,
   "near the gate the judge looks twice and the lower result counts")
blocking = R.default_mocks(GOAL)
blocking["plan"] = lambda rnd: json.dumps({**R.mock_plan(GOAL), "open_facts": [
    {"fact": "price", "workflow": "Build item 1", "blocking": True, "handling": "ask Identity"}]})
blocking["judge"] = lambda rnd, p, spec: R.mock_judge(spec, fail={"Build item 1": ["I2"]}, note="ask: the price")
r = R.plan_goal(GOAL, log=log, mocks=blocking)
ok(r["calls"] == 3 and len(r["rounds"]) == 1, "a workflow behind a blocking fact is not revised (loan-app pilot)")
ok(not r["not_ready"] and r["held"] == {"Build item 1": "waiting_on_identity"}
   and r["waiting_on_identity"][0]["ask"] == ["ask: the price"], "it waits on Identity with its question")
asks = R.default_mocks(GOAL)
asks["judge"] = lambda rnd, p, spec: R.mock_judge(spec, fail={"Build item 2": ["I2"]}, note="ask: the hours")
r = R.plan_goal(GOAL, log=log, mocks=asks)
ok(r["calls"] == 3 and r["not_ready"][0]["route"] == "identity", "gaps that are all asks skip revision, route Identity")
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "x")
    R.plan_goal(GOAL, log=log, out_dir=out)
    ok(os.path.exists(os.path.join(out, "trace.json")) and os.path.exists(os.path.join(out, "report.md")),
       "trace and report written")

# ---- inside J2 (mock): off by default; on, the first website plan goes through realization
import j2_flow_test as F      # noqa: E402  (sets J2's test env: temp runs and memory)
j2 = F.j2
j2.j2_check.tap_targets, j2.j2_check.behavior = F.fake_tap_targets, F.fake_behavior
j2.j2_check.check, j2.j2_check.find_chrome = F.fake_check, lambda: None
_was = os.environ.pop("J2_REALIZATION", None)
ok(j2.realization_on(), "realization and certainty are on by default (J2_REALIZATION unset)")
os.environ["J2_REALIZATION"] = "0"
ok(not j2.realization_on(), "J2_REALIZATION=0 turns them off")
if _was is None:
    os.environ.pop("J2_REALIZATION", None)
else:
    os.environ["J2_REALIZATION"] = _was
ok("Realization: cut" not in j2.system_prompt("adaptation", "x") and "The four zones" not in j2.system_prompt("adaptation", "x")
   and "# Adaptation Agent" in j2.system_prompt("adaptation", "x"), "Adaptation's own role leaves out the planning part")
prompts, real_ask = [], R.llm.ask


def spy(system, user, mock, **kw):
    prompts.append(user)
    return real_ask(system, user, mock, **kw)


def j2_run(on, mocks=None):
    os.environ["J2_REALIZATION"] = "1" if on else "0"
    prompts.clear()
    R.llm.ask = spy
    real_mocks = R.default_mocks
    if mocks:
        R.default_mocks = lambda goal: mocks(goal)
    try:
        run = j2.J2Run()
        F.say(run, F.BREW_LAB)
        F.finish(run)
    finally:
        R.llm.ask, R.default_mocks = real_ask, real_mocks
    return run


def head(run):
    with open(os.path.join(run.dir, "chat.jsonl"), encoding="utf-8") as f:
        return json.loads(f.readline())


run = j2_run(False)
ok(run.outcome.startswith("Done") and not os.path.exists(os.path.join(run.dir, "realization.json"))
   and "realization" not in F.summary(run) and head(run)["realization"] == 0, "J2 with the switch off: unchanged")
ok(not any("FILE WORKFLOWS ON THE TABLE" in p for p in prompts), "J2 with the switch off: Priority gets no file-workflow note")
run = j2_run(True)
s = F.summary(run)["realization"]
ok(run.outcome.startswith("Done") and s["applied"] and s["plan_confidence"] == 0.95
   and s["workflows"] == 1 + len(run.goal["done_when"])
   and head(run)["realization"] == 1, "J2 with the switch on: the run ends Done with a judged plan")
ok(all(os.path.exists(os.path.join(run.dir, f)) for f in ("realization.json", "realization.md"))
   and not os.path.exists(os.path.join(run.dir, "decisions.md")), "realization.json and realization.md are written, "
   "no decisions.md")
ok([r["name"] for r in s["proposal_brief"]] == ["Plan"] + [f"Build item {i}" for i in range(1, len(run.goal["done_when"]) + 1)]
   and any("REALIZATION PLAN (judged before any build" in p and "estimated_resources.tokens" in p for p in prompts),
   "Adaptation's task carries every planned workflow in run order, and says it estimates each budget itself")
plan_wf = next(w for w in run._all_wfs() if w["name"] == "Plan")
ok(plan_wf["id"] == "W-1" and plan_wf["status"] == "done" and plan_wf["cost"] == j2.similar_usage({"parts": ["artifact"]})
   and not plan_wf["covers"]
   and os.path.exists(os.path.join(run.dir, "artifacts", "plan.md"))
   and all(a["status"] == "passed" for a in plan_wf["atoms"]),
   "the planning workflow is a funded J2 workflow, W-1, costs what similar work used (tokens), and writes the file it named "
   "with its checks passing")
ok(not hasattr(j2, "RATES") and run.usage["by_phase"]["planning"] > 0
   and any(c.get("fn", "").startswith("realization-") for c in j2._jsonl(run.dir, "calls.jsonl")),
   "no rate card: usage is measured, and the planner's and judge's calls are counted in calls.jsonl")
ok(plan_wf.get("stage") == "product" and all(w.get("stage") == "build" for w in run._all_wfs() if w["name"].startswith("Build item")),
   "each workflow records its plan stage when registered")
ok(any(r_["check"] == "artifacts/plan.md exists." and r_["pass"] for a in plan_wf["atoms"] for r_ in a.get("results") or []),
   "a file workflow's 'file exists' check passes on the file it wrote")
ok(any("FILE WORKFLOWS ON THE TABLE" in p and '"Plan"' in p and "fund them" in p for p in prompts),
   "Priority is told the file workflows are planned inputs to fund")
rf = j2.J2Run()
rf.realization = True
fw = {"outputs": ["specs/plan.md"], "dependencies": [], "atoms": [{"goal": "The plan is written", "constraints": ["Only the file"],
      "context": ["charter goal"], "how": {"kind": "AI", "agent": "Builder", "steps": "Write specs/plan.md"},
      "expected_output": [{"text": "The file is written", "kind": "file", "target": "specs/plan.md"}],
      "verification": [{"text": "The file exists", "type": "file-exists", "target": "specs/plan.md", "expect": True, "item": 1}]}]}
ok(rf._atom_problems(fw) == [], "the validator accepts 'the file exists' for a file workflow")
ok(any("ARTIFACTS YOU READ" in p and "artifacts/plan.md" in p and "YOU OWN SECTION" in p for p in prompts),
   "site builders read the artifact of the workflow they depend on")
ok(not any('"decisions_to_follow"' in p for p in prompts), "no side channel: builders get no decisions_to_follow")
ok(any(m["who"] == "adaptation" and m.get("realization") for m in run.chat), "Adaptation posts the plan in the chat")


BASE_MOCKS = R.default_mocks    # j2_run swaps R.default_mocks for blocked_mocks, which builds on the original


def blocked_mocks(goal):
    m = BASE_MOCKS(goal)
    m["plan"] = lambda rnd: json.dumps({**R.mock_plan(goal), "open_facts": [
        {"fact": "pickup hours", "workflow": "Build item 1", "blocking": True, "handling": "ask Identity"}]})
    m["judge"] = lambda rnd, p, spec: R.mock_judge(spec, fail={"Build item 1": ["I2"]}, note="ask: the pickup hours")
    return m


run = j2_run(True, blocked_mocks)
s = F.summary(run)["realization"]
asked = [m for m in run.chat if m["who"] == "adaptation" and m.get("act") == "POLICY_QUESTION"]
ok(asked and "pickup hours" in asked[0]["text"] and run.real_asked, "a blocking fact goes to Identity before proposing")
ok("Build item 1" in [r["name"] for r in s["proposal_brief"]] and run.outcome.startswith("Done"),
   "after Identity answers, the held workflow is proposed and the run ends Done")

ok(run.real_questions.get("fact:Build item 1", {}).get("asked") and not any(q["kind"] == "gap" for q in run.real_questions.values()),
   "5b: the blocking fact has its own question record")

# ---- 5a: the fuller stage guide, one compact block per stage
st = R.load_stages()
guide = R.stage_table()
ok(all(s.get(k) for s in st for k in ("covers", "not_for", "example_workflows", "example_done_test"))
   and all(isinstance(s.get("typical_inputs"), list) and set(s["typical_inputs"]) <= set(R.STAGES) for s in st),
   "every stage has covers, not_for, typical_inputs (real stage ids), example workflows and an example done-test")
ok(all(f"- `{s['id']}`" in guide for s in st) and guide.count("Covers:") == len(st) and guide.count("Not for:") == len(st)
   and guide.count("Example done-test:") == len(st) and "| Stage |" not in guide,
   "the planner reads one compact block per stage (no wide table), stage ids unchanged")
ok("Covers:" in R.planner_system() and "<!-- STAGE TABLE -->" not in R.planner_system(), "the guide replaces the marker")


# ---- 5b: a workflow still below the gate is a plain decision (add information, try anyway, skip it)
def never_mocks(goal):
    m = BASE_MOCKS(goal)
    m["judge"] = lambda rnd, p, spec: R.mock_judge(spec, fail={"Build item 1": ["D1"]}, compare="same")
    return m


def gap_run(answer=None, no_questions=False):
    os.environ["J2_REALIZATION"] = "1"
    real_mocks = R.default_mocks
    R.default_mocks = lambda goal: never_mocks(goal)
    try:
        run = j2.J2Run()
        if no_questions:
            run.set_no_questions(True)
        F.say(run, F.BREW_LAB)
        seen = []
        for _ in range(6):
            d = run.legacy_decision()
            if not d:
                break
            if d["happening"].startswith("We couldn't plan"):
                seen.append(d)
                assert run.decide(d["id"], answer)[0]
            else:
                F.say(run, "1")
            while run.status != "waiting":
                F.time.sleep(0.02)
    finally:
        R.default_mocks = real_mocks
    return run, seen


run, seen = gap_run("try")
q = run.real_questions["gap:Build item 1"]
ok(len(seen) == 1 and seen[0]["kind"] == "problem" and [o["id"] for o in seen[0]["options"]] == ["add_info", "try", "skip"]
   and not j2.J2Run.decision_problems(seen[0]) and "build item 1" in seen[0]["happening"],
   "a not-ready workflow becomes one problem decision in the standard format")
ok(q["choice"] == "try" and not q["auto"] and run.outcome.startswith("Done")
   and next(w for w in run._all_wfs() if w["name"] == "Build item 1").get("at_risk"),
   "try anyway: funded and built, marked at risk, recorded on its own question")
run, seen = gap_run("skip")
ok(run.real_questions["gap:Build item 1"]["choice"] == "skip" and not any(w["name"] == "Build item 1" for w in run._all_wfs())
   and run.real_questions["gap:Build item 1"]["dropped"][0] in run.goal["dropped_by_requester"]
   and run.goal["done_when"] == [c for c in run.goal["charter_items"] if c not in run.goal["dropped_by_requester"]],
   "skip it: left out with the Requester's choice, its item leaves the checklist")
run, seen = gap_run(None, no_questions=True)
ok(not seen and run.real_questions["gap:Build item 1"]["choice"] == "try" and run.real_questions["gap:Build item 1"]["auto"]
   and any(m.get("auto_decision") for m in run.chat) and run.outcome.startswith("Done"),
   "no questions: a gap only the plan can close takes 'try anyway', logged backstage")
os.environ["J2_REALIZATION"] = "0"

# The validator knows an id that a workflow this one depends on is told to create (not only the atom's own how)
atom = {"how": {"kind": "AI", "agent": "Builder", "steps": "Add the hint button #hint-btn"}, "constraints": [],
        "verification": [{"text": "The board is there", "type": "element-count", "target": "#board", "expect": 1}]}
ok(any("doesn't tell the builder to create" in x for x in j2.check_problems(atom, "", j2.CHECK_TYPES))
   and not j2.check_problems(atom, "", j2.CHECK_TYPES, j2.squash('"steps": "Create the 9x9 grid #board"')),
   "an id is unknown on its own, and known once an upstream workflow is told to create it")
r2 = j2.J2Run()
up = {"name": "Grid", "dependencies": [], "atoms": [{"how": {"steps": "Create the grid #board"}, "constraints": []}]}
down = {"name": "Hint", "dependencies": ["Grid"], "atoms": [atom]}
ok("#board" in r2._upstream_told(down, [up, down]) and r2._upstream_told(up, [up, down]) == "",
   "upstream text comes from the workflows it depends on, through the proposal")
# Id ranges (run 092021's W-6): "#pad-1 to #pad-9" and "#cell-0-0 to #cell-8-8" tell the builder to create every id
grid = {"how": {"kind": "AI", "agent": "Builder", "steps": "Inside #pad build #pad-1 to #pad-9 and #pad-erase; inside "
                "#board build 81 buttons #cell-0-0 to #cell-8-8"}, "constraints": [],
        "verification": [{"text": "Fill a cell", "type": "behavior-steps", "expect": True,
                          "target": ["click #cell-0-1", "click #pad-4", "expect-text #cell-0-1 4"]}]}
ok(any("'#pad-4'" in x for x in j2.check_problems(grid, "", j2.CHECK_TYPES))
   and not j2.check_problems(grid, "", j2.CHECK_TYPES, ranges=True),
   "an id inside a written range is known in realization runs (base J2 still needs it written out)")
rc = {**grid, "how": {"steps": "Build 81 cells #cell-r-c (r and c 0 to 8) and #pad-1..#pad-9"}}
ok(not j2.check_problems(rc, "", j2.CHECK_TYPES, ranges=True)
   and j2.range_ids("cell-0-0 to cell-8-8").split()[-1] == "cell-8-8" and len(j2.range_ids("cell-0-0 to cell-8-8").split()) == 81
   and j2.range_ids("row-1 to row-9999") == "" and j2.range_ids("pad-9 to pad-1") == "",
   "r-c placeholders and '..' ranges expand; a huge or backwards range expands to nothing")
up_grid = {"name": "Grid", "dependencies": [], "atoms": [grid]}
helper = {"name": "Help", "dependencies": ["Grid"], "atoms": [{**grid, "how": {"steps": "Add #hint-btn"}}]}
r3 = j2.J2Run()
r3.realization = True
ok(not j2.check_problems(helper["atoms"][0], "", j2.CHECK_TYPES, r3._upstream_told(helper, [up_grid, helper]), ranges=True),
   "a range written by an upstream workflow counts for the workflows after it")
# A digit inside a name in a check's text is not a count ("One #pad-4 button" expects 1; "Buttons use j2-btn" expects 10)
cnt = {"how": {"steps": "Build #pad-4 and 10 buttons of class j2-btn"}, "constraints": [],
       "verification": [{"text": "One #pad-4 button", "type": "element-count", "target": "#pad-4", "expect": 1},
                        {"text": "Buttons use j2-btn", "type": "element-count", "target": ".j2-btn", "expect": 10}]}
bad = {**cnt, "verification": [{"text": "10 pad buttons", "type": "element-count", "target": ".j2-btn", "expect": 9}]}
ok(len(j2.check_problems(cnt, "", j2.CHECK_TYPES)) == 2 and not j2.check_problems(cnt, "", j2.CHECK_TYPES, ranges=True)
   and j2.check_problems(bad, "", j2.CHECK_TYPES, ranges=True),
   "numbers inside #pad-4 or j2-btn are not counts in realization runs; a real count that disagrees is still caught")
# Plan order: a planned workflow gets the id of its place in the plan, even when registered after later ones
r2.real_summary = {"proposal_brief": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}
ix = {"A": 0, "B": 1, "C": 2}
r2.workflows = [{"id": "W-2", "name": "B"}, {"id": "W-3", "name": "C"}]
ok(r2._next_wf_id("A", ix) == "W-1" and r2._next_wf_id("Fix B", ix) == "W-4" and j2.J2Run()._next_wf_id("X") == "W-1",
   "a late planned workflow takes its plan id (W-1); an unplanned one takes the next free id; plain runs count up")

# Live run 2026-11-04: Identity's to_be_confirmed entries are {criterion, fact} dicts; the planner's charter text
# must read them (it crashed joining them as strings), and an ai-judge check with no target must not crash coverage.
tbc_goal = {**GOAL, "to_be_confirmed": [{"criterion": "hours and location", "fact": "exact street address"}],
            "rules": ["one page", {"rule": "WhatsApp only"}]}
ct = R.charter_text(tbc_goal)
ok("TO_BE_CONFIRMED: hours and location - exact street address" in ct and "WhatsApp only" in ct,
   "the charter text reads to-be-confirmed dicts and dict rules")
cov = j2.cover_expected({"expected_output": [{"kind": "judged", "target": "Is the hero clear?"}, {"kind": "facts", "target": ["menu"]}],
                         "verification": [{"type": "ai-judge", "question": "Is the hero clear?", "expect": True},
                                          {"type": "ai-judge", "question": "Another?", "expect": True}]})["verification"]
ok(cov[0].get("item") == 1 and "item" not in cov[1] and any(c["type"] == "facts-present" and c.get("item") == 2 for c in cov),
   "expected-output coverage matches an ai-judge check by its question (no target) and adds the facts check")

# A heading check with a list target is one check per heading (a live run failed one 5 times on the list's text), a
# file workflow's recheck reads its own file, and a measurement in a goal is not a fact that needs facts-present.
hv = j2.normalise_checks([{"verification": [{"text": "Headings present", "type": "heading-present",
                                             "target": ["Menu", "## Hours"], "expect": True}]}])[0]["verification"]
ok([c["target"] for c in hv] == ["Menu", "Hours"] and j2.doc_check(hv[1], "# Menu\nx\n## Hours\ny")["pass"]
   and j2.doc_check({"type": "heading-present", "target": ["Menu", "Prices"]}, "# Menu\nx")["pass"] is False,
   "a list heading check runs per heading")
ok(not j2.SPECIFIC.search(j2.MEASURE.sub(" ", "A layout guide for 360px and 1280px, 44x44 targets, 4.5:1, 3 columns"))
   and j2.SPECIFIC.search(j2.MEASURE.sub(" ", "Show Masala Dosa Rs 120")),
   "measurements in a goal are not facts; a price still is")

fsrc = j2.squash("Brew Lab coffee, 40 seats")
ok(j2.goal_names_fact("Opening hours 8am to 9pm are listed", fsrc) and j2.goal_names_fact("Latte Rs 180", fsrc)
   and j2.goal_names_fact("Seats 40 people", fsrc) and not j2.goal_names_fact("A success target within 30 days", fsrc)
   and not j2.goal_names_fact("40% of slots booked online", j2.squash("Brew Lab coffee")),
   "a goal's time, price or brief number needs facts-present; a number the brief doesn't give does not")

rr = j2.J2Run()
tbc = [{"criterion": "The page shows the clinic address in Indiranagar", "fact": "Exact street address of the clinic"}]
ok(rr._already_unknown({"question": "What is the full street address of the clinic?"}, tbc)
   and not rr._already_unknown({"question": "What are the opening hours on Sunday?"}, tbc),
   "a detail already marked to be confirmed is recognised, so it isn't asked again every round")

rq = j2.J2Run()
rq.budget = 1000000
rq._decision_from_question("problem", "Only you can give what's still missing.",
                           {"question": "q?", "options": ["Keep going: more work", "Finish as it is: the site as it is"]},
                           ["continue", "ship"], prefer="ship")
ok([o["id"] for o in rq.legacy_decision()["options"] if o["suggested"]] == ["ship"],
   "with only the Requester's facts missing and questions off, Finish as it is is the suggestion")

ra = j2.J2Run()
ra.no_questions, ra.budget = True, 10 ** 6
ra._decision("problem", "We need your address.", "Only you know it.",
             [{"id": "give", "label": "Give the exact address", "gets": "We add it", "suggested": True},
              {"id": "open", "label": "Leave it open", "gets": "It stays to be confirmed", "suggested": False}],
             to="identity", handoff={"kind": "question"})
rb = j2.J2Run()
rb.no_questions, rb.budget = True, 10 ** 6
rb._decision("problem", "We need your address.", "Only you know it.",
             [{"id": "give", "label": "Give the exact address", "gets": "We add it", "suggested": True},
              {"id": "share", "label": "Share it later", "gets": "Send it when ready", "suggested": False}],
             to="identity", handoff={"kind": "question"})
ok(ra.decisions[-1]["decision"] == "open" and rb.decisions[-1]["decision"] == "dont_know"
   and rb.handoff.get("free") == "I don't know yet.",
   "decide-for-me never takes an option that needs the person's own words")

rs = j2.J2Run()
rs.no_questions, rs.budget = True, 10 ** 6
rs._decision("problem", "Pick how to show prices.", "Your call.",
             [{"id": "big", "label": "Big type", "gets": "Prices in large type; send people to WhatsApp", "suggested": True},
              {"id": "small", "label": "Small list", "gets": "A plain list", "suggested": False}],
             to="identity", handoff={"kind": "question"})
ok(rs.decisions[-1]["decision"] == "big", "only an option whose label asks for the person's words is skipped, not one "
   "whose description mentions type or sending")

print(f"realization_test: {passed} checks passed")
