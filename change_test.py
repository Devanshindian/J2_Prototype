"""Offline checks of the charter change (j2_change.py): python change_test.py

The planning graph ported from the change relay, the replies its calls must give, the charter diff on charter numbers,
item owners, and the decision rule. No AI calls.
"""
import os
import re
import sys
import tempfile

os.environ["STUDIO_MOCK"] = "1"          # before llm is imported
os.environ.pop("STUDIO_PROVIDER", None)
import j2_change as ch                   # noqa: E402

passed = 0


def ok(cond, label):
    global passed
    if not cond:
        sys.exit(f"FAIL: {label}")
    passed += 1


def W(i, name, outputs, deps, revises=None, covers=(), status="done"):
    return {"id": f"W-{i}", "name": name, "outputs": outputs, "dependencies": deps, "revises": revises,
            "covers": list(covers), "status": status}


def is_doc(w):
    """A test stand-in for j2.is_artifact: every output is a file other than the site file."""
    return bool(w["outputs"]) and all(o != "index.html" for o in w["outputs"])


SITE = ["index.html"]
# J2_Relay runs/j2-20261027-142038/workflows.json (the relay's baseline): ids, names, outputs, dependencies, revises
BASE_WFS = [
    W(1, "product-spec", ["spec.md"], []),
    W(2, "design-guide", ["design.md"], ["product-spec"]),
    W(3, "copy-deck", ["copy.md"], ["product-spec"]),
    W(4, "architecture", ["architecture.md"], ["product-spec"]),
    W(5, "build-shell-styles", SITE, ["design-guide", "architecture"]),
    W(6, "build-game-core", SITE, ["build-shell-styles", "architecture", "design-guide"]),
    W(7, "build-puzzle-engine", SITE, ["build-game-core", "architecture", "product-spec"]),
    W(8, "build-help-tools", SITE, ["build-puzzle-engine", "copy-deck", "product-spec"]),
    W(9, "build-howto-messages", SITE, ["build-help-tools", "copy-deck"]),
    W(10, "build-progress-storage", SITE, ["build-howto-messages", "architecture", "product-spec", "copy-deck"]),
    W(11, "build-final-wiring", SITE, ["build-progress-storage"]),
    W(12, "fix-startup-restore", SITE, ["build-progress-storage"], "W-11"),
    W(13, "fix-static-numbers", SITE, ["build-progress-storage"], "W-10"),
    W(14, "build-two-player-race", SITE, ["build-final-wiring", "build-progress-storage"]),
    W(15, "fix-nav-two-player", SITE, ["build-final-wiring", "build-two-player-race"], "W-11"),
    W(16, "restyle-dark-minimal", SITE, ["build-final-wiring", "build-two-player-race"], "W-5"),
    W(17, "fix-race-board-dark", SITE, ["build-two-player-race", "restyle-dark-minimal"], "W-14"),
    W(18, "fix-grid-render", SITE, ["build-game-core", "build-help-tools", "build-puzzle-engine"], "W-6"),
]

# ---- Task 1: the planning graph (ported from J2_Relay relay_test.py; the site test is passed in as is_doc)
nodes = ch.planning_nodes(BASE_WFS, is_doc)
ok([n["root"] for n in nodes] == ["W-1", "W-2", "W-3", "W-4"], "planning nodes are the four file workflows")
ok(nodes[1]["parents"] == ["W-1"] and nodes[0]["parents"] == [], "a node's parents are the planning workflows it depends on")
ok(ch.relay_waves(nodes) == [["W-1"], ["W-2", "W-3", "W-4"]], "design, copy and architecture answer together")
c = ch.build_candidates(BASE_WFS, ["W-2"], is_doc)
ok("W-15" in c and "W-17" in c,
   "nav (W-11, latest W-15, reached via W-10) and the race board (W-14, latest W-17) are reached")
ok("W-5" not in c and "W-16" in c and "W-11" not in c, "a revised section is named by its latest revision")
ok(len(c) == len(set(c)) and all(ch.latest(BASE_WFS, x)["id"] == x for x in c), "each section once, by its latest id")
ok(ch.build_candidates(BASE_WFS, [], is_doc) == [], "no changed document, no candidates")
two = BASE_WFS + [W(19, "design-guide r2", ["design.md"], ["product-spec"], "W-2")]
ok(ch.latest(two, "W-2")["id"] == "W-19" and [n["id"] for n in ch.planning_nodes(two, is_doc)][1] == "W-19",
   "a second change uses the latest revision of each planning node")
ok(ch.latest(two, "W-19")["id"] == "W-19" and ch.planning_nodes(two, is_doc)[1]["root"] == "W-2",
   "a revision's root is the original workflow")
ok(ch.direct_readers(BASE_WFS, "W-2") == ["W-16", "W-18"] and ch.direct_readers(BASE_WFS, "W-1")[:3] == ["W-2", "W-3", "W-4"],
   "a document's direct readers, by latest revision: design is read by styles and game core")
ok([n["root"] for n in ch.planning_nodes(BASE_WFS, lambda w: w["name"] == "architecture")] == ["W-4"],
   "what counts as a document is the caller's test, not a file name in code")

# ---- the replies: Relay's "affected? what?" call
ok(ch.parse_affected('{"affected":false,"what":""}') == {"affected": False, "what": ""}, "affected parses")
ok(ch.parse_affected('Here: {"affected":true,"what":"level names"}') == {"affected": True, "what": "level names"},
   "affected parses with text around the JSON")
ok(ch.parse_affected('{"affected":true}') is None, "affected needs what")
ok(ch.parse_affected('{"affected":"yes","what":"x"}') is None, "affected must be true or false")
ok(ch.parse_affected("sure, looks fine") is None and ch.parse_affected(None) is None, "prose is not a reply")

# ---- Task 2: intents (the charter diff on charter numbers) and item owners
# runs/sudoku4/j2-20261026-121214: goal.json (items shortened) and workflows.json (ids, names, covers, revises, status)
ITEMS = ["One HTML file, no sign-up, no ads", "9x9 board with number pad, erase and undo",
         "Three levels (Easy, Medium, Hard) and New Game", "Every puzzle has one solution", "Beginner help",
         "Hint explains where to look", "Saves progress and resumes", "Reasons to come back",
         "Warm, uncluttered layout", "No JavaScript errors, no overflow"]
SUDOKU = {"statement": "A friendly, uncluttered Sudoku game in one web page", "audience": "Casual players on a phone",
          "charter_items": list(ITEMS), "done_when": list(ITEMS),
          "rules": ["No sign-up, no login and no ads", "Everything lives in one HTML file"],
          "standards": ["Phone-first", "Help never reveals an answer"]}


def changed(**kw):
    g = {k: (list(v) if isinstance(v, list) else v) for k, v in SUDOKU.items()}
    g.update(kw)
    return g


RENAMED = "Three levels (Gentle, Steady, Tricky) and New Game"
renamed = changed(done_when=ITEMS[:2] + [RENAMED] + ITEMS[3:])
d = ch.charter_diff(SUDOKU, renamed)
ok(d["removed"] == [3] and d["added"] == [11], "an edit is remove + add")
ok(not d["goal_changed"] and d["rules"] == {"added": [], "removed": []} and d["standards"] == {"added": [], "removed": []},
   "an item edit changes nothing else")
ok(not ch.diff_empty(d), "an edit is a change")
reverted = changed(charter_items=ITEMS + [RENAMED], done_when=list(ITEMS))   # J2 appended the renamed text as 11
ok(ch.diff_empty(ch.charter_diff(SUDOKU, reverted)), "a revert diffs to nothing")
after = changed(charter_items=ITEMS + [RENAMED], done_when=ITEMS[:2] + [RENAMED] + ITEMS[3:])
d = ch.charter_diff(after, reverted)
ok(d["added"] == [3] and d["removed"] == [11], "a revert brings back the old number, not a new one")
ok(ch.charter_diff(after, changed(charter_items=ITEMS + [RENAMED], done_when=[RENAMED] + ITEMS[:2] + ITEMS[3:]))
   == ch.charter_diff(after, after), "numbers come from the charter, not done_when positions")
ok(ch.diff_empty(ch.charter_diff(SUDOKU, changed())), "an unchanged charter is an empty diff")
killer = changed(audience="Puzzle fans who want Killer Sudoku")
ok(ch.charter_diff(SUDOKU, killer)["goal_changed"], "audience change → re-plan")
ok(ch.charter_diff(SUDOKU, changed(statement="A Killer Sudoku game"))["goal_changed"] and not ch.diff_empty(
   ch.charter_diff(SUDOKU, killer)), "statement change → re-plan; a goal change is not an empty diff")
removed = changed(done_when=ITEMS[:6] + ITEMS[7:])
d = ch.charter_diff(SUDOKU, removed)
ok(d["removed"] == [7] and d["added"] == [], "a dropped item is removed, by its number")
two = changed(done_when=ITEMS + ["Daily Challenge", "Share result", "Daily Challenge"])
ok(ch.charter_diff(SUDOKU, two)["added"] == [11, 12], "new items take the next numbers, in order; a repeat is one item")
d = ch.charter_diff(SUDOKU, changed(standards=["Phone-first", "Dark mode available"], rules=SUDOKU["rules"] + ["No sound"]))
ok(d["standards"] == {"added": ["Dark mode available"], "removed": ["Help never reveals an answer"]}
   and d["rules"] == {"added": ["No sound"], "removed": []} and not ch.diff_empty(d), "rules and standards diff by text")


def S(i, name, covers, revises=None, status="done"):
    return {"id": f"W-{i}", "name": name, "covers": covers, "revises": revises, "status": status}


SUDOKU_WFS = [S(1, "Product plan", []), S(2, "Style guide", []), S(3, "Technical design", []), S(4, "Page shell", [1]),
              S(5, "Puzzle engine", [4]), S(6, "Board and number pad", [2]), S(7, "Look and layout", [9]),
              S(8, "Levels and new game", [3]), S(9, "Beginner help", [5]), S(10, "Hint", [6]),
              S(11, "Save and resume", [7]), S(12, "Reasons to come back", [8]), S(13, "How to play", []),
              S(14, "Page wiring", [10]), S(15, "Board and number pad fix", [2], "W-6")]
owners = ch.owner_index(SUDOKU_WFS)
ok(owners[2] == "W-15", "a revision replaces its original as owner")
ok(owners == {1: "W-4", 2: "W-15", 3: "W-8", 4: "W-5", 5: "W-9", 6: "W-10", 7: "W-11", 8: "W-12", 9: "W-7", 10: "W-14"},
   "every Sudoku item has exactly one owner")
dropped = [dict(w, status="dropped") if w["id"] == "W-11" else w for w in SUDOKU_WFS]
ok(7 not in ch.owner_index(dropped), "a dropped workflow owns nothing")
moved = SUDOKU_WFS + [S(16, "Levels and new game r2", [11], "W-8")]
ok(ch.owner_index(moved)[11] == "W-16" and 3 not in ch.owner_index(moved), "a revision's covers replace its original's")

# ---- Task 3: the decision rule (the judge answers, code decides)
import j2_realization as R               # noqa: E402  (only for settle's real output shape)
OWNED, NONE = {"owner": "Hint", "stage": None}, {"owner": None, "stage": None}
HIGH, LOW, SIZE = {"score": 0.95, "weakest_part": None}, {"score": 0.77, "weakest_part": "how"},     {"score": 0.62, "weakest_part": "size"}
ok(ch.decide("removed", NONE, None) == "A" and ch.decide("removed", OWNED, LOW) == "A", "removed → A, whatever the scores")
ok(ch.decide("added", {"owner": None, "stage": "build"}, None) == "C", "no owner, a stage in the plan owns it → C")
ok(ch.decide("added", NONE, None) == "D", "no owner and no stage → D")
ok(ch.decide("added", OWNED, {"score": 0.80, "weakest_part": "how"}) == "A", "owner at the gate → A")
ok(ch.decide("added", OWNED, SIZE) == "C", "weakest part size → C straight away, no fix")
ok(ch.decide("added", OWNED, LOW) == "B", "below the gate, not size → B (one fix)")
ok(ch.decide("added", OWNED, LOW, after_fix={"score": 0.86, "weakest_part": None}) == "A", "B judged again ≥ 0.80 → A")
ok(ch.decide("added", OWNED, LOW, after_fix={"score": 0.79, "weakest_part": "how"}) == "C", "B judged again 0.79 → C")
ok(ch.PART == {"done_test": "goal", "inputs": "context", "method": "how", "zone_fit": "how", "factors": "constraints",
               "size": "size", "fits": "goal"} and set(R.CHECKS) <= set(ch.PART), "every check has a work-atom part")


def judged(no=(), extra=()):
    """settle's real output for one workflow answering "no" to the given question ids and "yes" to the rest."""
    spec = {i: (check, w, text) for i, check, w, text in R.QUESTIONS + tuple(extra)}
    s = R.settle({"a": {i: {"answer": "no" if i in no else "yes", "note": ""} for i in spec}}, spec)
    return s, {"score": s["score"], "weakest_part": ch.weakest_part(s, spec)}


s, sc = judged()
ok(s["score"] == 0.95 and sc["weakest_part"] is None and ch.decide("added", OWNED, sc) == "A", "judge today 0.95 → A")
s, sc = judged(no=("Z1",))
ok(s["score"] == 0.70 and sc["weakest_part"] == "how" and ch.decide("added", OWNED, sc) == "B",
   "judge today 0.70, weakest how → B")
s, sc = judged(no=("I1",))
ok(s["score"] == 0.70 and sc["weakest_part"] == "context" and ch.decide("added", OWNED, sc) == "B",
   "judge today 0.70, weakest context → B")
s, sc = judged(no=("S1", "S2", "M2", "D3", "D4"))
ok(s["score"] == 0.48 and sc["weakest_part"] == "size" and ch.decide("added", OWNED, sc) == "C",
   "a low score lost mostly on size → C")
s, sc = judged(no=("S1", "S2"))
ok(s["score"] == 0.72 and sc["weakest_part"] == "size" and ch.decide("added", OWNED, sc) == "C",
   "judge today 0.72, weakest size → C")

# ---- Task 4: the judge for a change. A realization plan shaped like runs/sudoku4/j2-20261026-121214 realization.json
import hashlib                           # noqa: E402
import json                              # noqa: E402

SIG = {k: {"answer": a, "evidence": "fixture"} for k, a in zip(R.SIGNALS, ("no", "no", "yes", "yes", "yes"))}


def P(name, stage, delivers=(), informs=(), inputs=(), certainty="operate"):
    return {"name": name, "stage": stage, "certainty": certainty, "certainty_signals": ["fixture"],
            "approach": f"{name}: follow the plan.", "goal": f"{name} is done", "done_test": f"{name} passes its check",
            "delivers": list(delivers), "informs": list(informs), "inputs_from": list(inputs), "experiment": None,
            "research": None}


def stage(sid, thinking, tiers, owns, inputs):
    return {"id": sid, "thinking": thinking, "tiers": tiers, "goal": f"{sid} done", "done_test": f"{sid} checked",
            "method": "fixture", "owns_factors": owns, "inputs_from": inputs}


def D(name, stage_id, informs, inputs=()):
    return P(name, stage_id, informs=informs, inputs=inputs, certainty="analyze")


PLAN = {
    "certainty_assessment": {"zone": "analyze", "signals": SIG, "rationale": "fixture"},
    "analysis": {"options": ["a", "b"], "chosen": "a", "why": "fixture", "assumptions": []}, "deferred": [],
    "factors": [{"name": "Help never reveals an answer", "source": "brief", "quote": "help", "citation": None,
                 "why": "fixture", "stages": ["product"]},
                {"name": "Warm, uncluttered look", "source": "brief", "quote": "warm", "citation": None, "why": "fixture",
                 "stages": ["design"]},
                {"name": "One HTML file", "source": "brief", "quote": "one file", "citation": None, "why": "fixture",
                 "stages": ["engineering"]}],
    "unplaced": [],
    "stages": [stage("product", "users and scope", ["capability", "feature"], ["Help never reveals an answer"], []),
               stage("design", "experience", ["feature"], ["Warm, uncluttered look"], ["product"]),
               stage("engineering", "structure", ["architecture"], ["One HTML file"], ["product"]),
               stage("build", "making", ["implementation"], [], ["product", "design", "engineering"])],
    "workflows": [
        D("Product plan", "product", [1, 3, 5, 6, 8]),
        D("Style guide", "design", [2, 5, 8, 9], ["Product plan"]),
        D("Technical design", "engineering", [1, 2, 3, 4, 5, 6, 7, 8], ["Product plan"]),
        P("Page shell", "build", [1], inputs=["Technical design", "Product plan"]),
        P("Puzzle engine", "build", [4], inputs=["Technical design", "Product plan", "Page shell"]),
        P("Board and number pad", "build", [2], inputs=["Page shell", "Puzzle engine", "Technical design", "Style guide"]),
        P("Look and layout", "build", [9], inputs=["Style guide", "Page shell", "Board and number pad"]),
        P("Levels and new game", "build", [3], inputs=["Board and number pad", "Puzzle engine", "Product plan",
                                                       "Technical design"]),
        P("Beginner help", "build", [5], inputs=["Board and number pad", "Product plan", "Style guide", "Technical design"]),
        P("Hint", "build", [6], inputs=["Board and number pad", "Puzzle engine", "Technical design", "Product plan"]),
        P("Save and resume", "build", [7], inputs=["Board and number pad", "Levels and new game", "Technical design",
                                                   "Beginner help"]),
        P("Reasons to come back", "build", [8], inputs=["Save and resume", "Board and number pad", "Levels and new game",
                                                        "Product plan", "Style guide", "Technical design"]),
        P("How to play", "build", informs=[5, 6, 10], inputs=["Page shell", "Product plan", "Style guide"]),
        P("Page wiring", "build", [10], inputs=["Page shell", "Look and layout", "Puzzle engine", "Board and number pad",
                                               "Levels and new game", "Beginner help", "Hint", "Save and resume",
                                               "Reasons to come back", "How to play", "Technical design",
                                               "Product plan"])],
    "open_facts": [], "not_ready": []}
ok(R.plan_faults(PLAN, SUDOKU) == [], "the fixture plan follows every rule")
quiet = lambda *_: None

# Phase A follow-ups: weakest_part sums by work-atom part; a revision with no covers keeps its original as owner
s, sc = judged(no=("G0", "I1", "D4"), extra=R.CHANGE_QUESTIONS)
ok(s["weakest"] == "inputs" and sc["weakest_part"] == "goal",
   "the part that lost the most (goal: G0 0.25 + D4 0.06) wins over the single check that lost the most (inputs)")
ok(ch.weakest_part({"failed": []}, {}) is None, "nothing lost, no weakest part")
blank = SUDOKU_WFS + [S(16, "Hint fix", [], "W-10")]
ok(ch.owner_index(blank)[6] == "W-10", "a revision with empty covers does not erase its original's ownership")

# the first plan is unchanged: spec, scores and the prompts the judge and planner read
GOAL = {"statement": "A coffee shop site", "done_when": ["menu", "hours and location", "signature drinks", "contact form"]}
h = lambda x: hashlib.sha256(x.encode()).hexdigest()[:16]
mp = R.mock_plan(GOAL)
cl = R.checklist_items(json.loads(R.default_mocks(GOAL)["checklist"]()), GOAL)
spec = R.question_spec(mp, cl)
ok(h(json.dumps(spec, sort_keys=True)) == "a18591ac18206877", "first-plan question spec unchanged (snapshot)")
got = []
for fail in ([], ["D1"], ["D3", "K1"], ["S1"], ["M2", "Z1"], ["S1", "S2", "F1"]):
    for n in ("Plan", "Build item 1"):
        x = R.settle(json.loads(R.mock_judge({"x": spec[n]}, fail={"x": fail}))["answers"][0], spec[n])
        got.append((x["score"], x["weakest"], x["capped"]))
ok(got == [(0.95, None, False)] * 2 + [(0.7, "done_test", False)] * 2 + [(0.85, "done_test", False),
   (0.75, "done_test", False)] + [(0.79, "size", True)] * 2 + [(0.62, "zone_fit", False)] * 2
   + [(0.64, "size", False), (0.72, "size", False)], "first-plan settle scores unchanged (snapshot)")
low = {"Plan": {"score": 0.7, "weakest": "method", "missing": ["x"]}}
ok((h(R.checklist_task(GOAL)), h(R.judge_task(GOAL, mp, spec, {})), h(R.revise_task(GOAL, True, mp, low)))
   == ("75a238c164bdb721", "ac43f64ab27dbe1d", "93b518065a7f988c"), "first-plan checklist, judge and revise prompts unchanged")
ok(R.question_spec(mp, cl, names=None) == spec and "fits" in R.CHECKS and not any(q[0] == "G0" for q in R.QUESTIONS),
   "names=None is the whole plan; G0 is not a first-plan question")

# the change path: charter numbers, a subset of workflows, G0
ADD = changed(charter_items=ITEMS + ["Daily challenge"], done_when=ITEMS[:6] + ITEMS[7:] + ["Daily challenge"])
ok(R.numbered(ADD)[-1] == (11, "Daily challenge") and (7, ITEMS[6]) not in R.numbered(ADD)
   and R.numbered(GOAL) == list(enumerate(GOAL["done_when"], 1)), "items by charter number; positions without charter_items")
ok("  11. Daily challenge" in R.charter_text(ADD, by_number=True) and "  10. Daily challenge" in R.charter_text(ADD),
   "the change path shows charter numbers; the first plan keeps positions")
ck = R.checklist_items(None, ADD, items=[11])
ok(ck == [{"id": "K1", "item": 11, "question": "The done-test verifies, by behaviour or content: Daily challenge"}],
   "item questions only for the changed items, by charter number (fallback, no call)")
ok(R.checklist_items({"items": [{"item": 11, "question": "q11"}, {"item": 3, "question": "q3"}]}, ADD, items=[11])
   == [{"id": "K1", "item": 11, "question": "q11"}], "a question for an unchanged item is ignored")
ok("11. Daily challenge" in R.checklist_task(ADD, items=[11]) and "items 11" in R.checklist_task(ADD, items=[11]),
   "the checklist call can be asked for the changed items only")
sub = R.question_spec(PLAN, ck, names=["Hint", "Levels and new game"])
ok(list(sub) == ["Levels and new game", "Hint"], "a subset spec has only the named workflows")
seen = []


def jmock(fail=None, compare="better"):
    def f(spec):
        seen.append(spec)
        return R.mock_judge(spec, fail=fail, compare=compare)
    return f


sess = R.Session(log=quiet)
sc, _ = sess.judge(ADD, PLAN, ck, jmock({"Hint": ["G0"]}), names=["Hint", "Levels and new game"],
                   change={"Hint": [11], "Levels and new game": [11]})
ok(set(seen[0]) == {"Hint", "Levels and new game"} and "G0" in seen[0]["Hint"] and "K1" in seen[0]["Hint"],
   "the change judge asks the owners G0 and the K questions of their changed items")
ok(sc["Hint"]["score"] == 0.70 and sc["Hint"]["checks"]["fits"] == "no" and sc["Levels and new game"]["score"] == 0.95,
   "G0 no caps the score below the gate")
ok(ch.weakest_part(sc["Hint"], seen[0]["Hint"]) == "goal", "G0 is the goal part")
prompt = sess.trail[-1]["user"]
ok("CHANGE" in prompt and "  11. Daily challenge" in prompt, "the change judge reads charter numbers and the change")

# the match call: G0 for every workflow, the stage question when no one owns it
TWO = changed(charter_items=ITEMS + ["Daily challenge", "Teach techniques"],
              done_when=ITEMS + ["Daily challenge", "Teach techniques"])
mreply = json.dumps({"intents": [{"item": 11, "owner": None, "stage": "build", "why": "a new screen"},
                                 {"item": 12, "owner": "Hint", "stage": None, "why": "hints"}]})
sess = R.Session(log=quiet)
m = ch.match(sess, TWO, PLAN, [11, 12], lambda: mreply)
ok(m[11]["owner"] is None and m[11]["stage"] == "build" and m[12]["owner"] == "Hint" and sess.calls == 1,
   "mock match gives owner and stage in one call")
ok("11. Daily challenge" in sess.trail[0]["user"] and "G0" in sess.trail[0]["user"], "the match call asks G0 by charter number")
sess = R.Session(log=quiet)
m = ch.match(sess, TWO, PLAN, [11, 12], lambda: json.dumps({"intents": [{"item": 11, "owner": "Nope", "stage": None,
                                                                          "why": ""}]}))
ok(sess.calls == 2 and m[11]["unread"] and m[12]["unread"] and ch.decide("added", m[11], None) == "C",
   "a match reply malformed twice: the intent is decided C, never dropped")
m = ch.match(R.Session(log=quiet), TWO, PLAN, [11, 12],
             lambda: json.dumps({"intents": [{"item": 11, "owner": None, "stage": "growth", "why": "x"},
                                             {"item": 12, "owner": None, "stage": None, "why": "y"}]}))
ok(m[11]["stage"] is None and ch.decide("added", m[11], None) == "D", "a stage not in the plan is no stage: D")
SCENARIO = re.compile(r"sudoku|hint|level|puzzle|board|product plan|style guide|technical design|engineering|design",
                      re.I)


def wording(task, goal, plan, *texts):
    """A prompt without the run's own text (charter, plan, item texts): what code wrote."""
    out = task.replace(R.charter_text(goal, True), "").replace(json.dumps(plan, ensure_ascii=False), "")
    for t in texts:
        out = out.replace(t, "")
    return out


ok(not SCENARIO.search(wording(R.match_task(TWO, PLAN, [11]), TWO, PLAN, "Daily challenge")),
   "the match prompt names no scenario")
ok(not SCENARIO.search(R.CHANGE_QUESTIONS[0][3] + prompt.split("CHANGE: ")[1].split(":\n")[0]),
   "G0 and the judge's change note name no scenario")

# ---- Task 5: act. A edits the owner (or drops it), B makes one fix, C and D place new workflows
def names_of(p):
    return [w["name"] for w in p["workflows"]]


def wf_of(p, name):
    return next(w for w in p["workflows"] if w["name"] == name)


NO_SAVE = changed(done_when=ITEMS[:6] + ITEMS[7:])                     # item 7 removed
ok(R.plan_faults(PLAN, NO_SAVE, items=[1, 2, 3, 4, 5, 6, 8, 9, 10])[:1] == ["workflow Technical design: item 7 does not exist "
   "(done-when items are 1, 2, 3, 4, 5, 6, 8, 9, 10)"], "plan_faults(items=) checks charter numbers, not positions")
ok(R.plan_faults(PLAN, SUDOKU, items=range(1, 11)) == [] and R.plan_faults(PLAN, NO_SAVE) != [],
   "items= on the first plan's numbers is the default check")

# A, remove: the owner is left with nothing, so it is dropped without a call; whatever read it stops reading it
sess = R.Session(log=quiet)
a = ch.edit(sess, NO_SAVE, PLAN, "Save and resume", [], [7], lambda: "never asked")
ok(sess.calls == 0 and "Save and resume" not in names_of(a["plan"]) and a["dropped"] == ["Save and resume"],
   "A remove drops the workflow left delivering nothing, with no call")
ok(a["readers"] == ["Reasons to come back", "Page wiring"]
   and all("Save and resume" not in w["inputs_from"] for w in a["plan"]["workflows"]), "its readers stop reading it")
ok(a["docs"] == ["Technical design"] and 7 not in wf_of(a["plan"], "Technical design")["informs"]
   and R.plan_faults(a["plan"], NO_SAVE, items=[1, 2, 3, 4, 5, 6, 8, 9, 10]) == [],
   "the planning docs it read are revised first; the plan passes on the charter numbers left")
ok(PLAN["workflows"][10]["name"] == "Save and resume", "the caller's plan is not changed")

# A, an edit (remove + add): one call; the reply's docs are the planning docs to revise; code keeps delivers right
RENAMED_GOAL = changed(charter_items=ITEMS + [RENAMED], done_when=ITEMS[:2] + [RENAMED] + ITEMS[3:])
levels = dict(wf_of(PLAN, "Levels and new game"), goal="Three renamed levels and New Game", delivers=[3])
sess = R.Session(log=quiet)
a = ch.edit(sess, RENAMED_GOAL, PLAN, "Levels and new game", [11], [3],
            lambda: json.dumps({"workflow": levels, "docs": ["Product plan"]}))
w = wf_of(a["plan"], "Levels and new game")
ok(sess.calls == 1 and w["delivers"] == [11] and w["goal"] == "Three renamed levels and New Game" and a["docs"] == ["Product plan"],
   "A edit: one call; the removed number leaves delivers and the added one joins")
ok(a["ok"] and R.plan_faults(a["plan"], RENAMED_GOAL, items=[1, 2, 4, 5, 6, 7, 8, 9, 10, 11]) == [], "the edited plan passes")
et = sess.trail[0]["user"]
ok("  11. " + RENAMED in et and f"item 3 ({ITEMS[2]})" in et
   and not SCENARIO.search(wording(et.split("THE PLAN:")[0] + et.split("THE CHANGE FOR")[1], RENAMED_GOAL, PLAN,
                                   RENAMED, ITEMS[2], "Levels and new game")),
   "the edit prompt names the added and removed items by charter number, and no scenario")
sess = R.Session(log=quiet)
a = ch.edit(sess, RENAMED_GOAL, PLAN, "Levels and new game", [11], [3],
            lambda: json.dumps({"workflow": levels, "docs": ["Nope"]}))
ok(sess.calls == 2 and not a["ok"], "docs naming no planning workflow: sent back once, then the edit fails")

# B: one fix (one revise call), judged again on the owner only; still below → C
TEACH = changed(charter_items=ITEMS + ["Hints teach the technique"], done_when=ITEMS + ["Hints teach the technique"])
ck = R.checklist_items(None, TEACH, items=[11])
low_hint = {"Hint": R.settle(json.loads(R.mock_judge(R.judge_spec(PLAN, ck, ["Hint"], {"Hint": [11]}),
                                                     fail={"Hint": ["M2", "D3"]}))["answers"][0],
                             R.judge_spec(PLAN, ck, ["Hint"], {"Hint": [11]})["Hint"])}
ok(low_hint["Hint"]["score"] == 0.77, "the fixture's B case: Hint 0.77")
hint2 = dict(wf_of(PLAN, "Hint"), approach="Teach the named technique behind each hint.", delivers=[6, 11])
seen.clear()
sess = R.Session(log=quiet)
mocks = {"revise": lambda owner: json.dumps({**PLAN, "workflows": [hint2]}), "judge": jmock({"Hint": ["D1"]})}
plan_b, after = ch.fix(sess, TEACH, PLAN, "Hint", [11], low_hint, ck, mocks)
ok(sess.calls == 2 and [x["who"] for x in sess.trail] == ["adaptation", "judge"] and list(seen[-1]) == ["Hint"],
   "B: exactly one revise call, then the judge on the owner only")
ok(after["score"] == 0.70 and ch.decide("added", {"owner": "Hint"}, {"score": 0.77, "weakest_part": "goal"}, after) == "C",
   "B still below the gate after its fix → C, not another round")
ok("Revise only" in sess.trail[0]["user"] and "11. Hints teach the technique" in sess.trail[0]["user"],
   "the one fix is scoped to the owner and reads charter numbers")
sess = R.Session(log=quiet)
plan_b, after = ch.fix(sess, TEACH, PLAN, "Hint", [11], low_hint, ck, {**mocks, "judge": jmock()})
ok(after["score"] >= 0.80 and wf_of(plan_b, "Hint")["delivers"] == [6, 11] and len(names_of(plan_b)) == len(names_of(PLAN)),
   "B passing: the fixed owner replaces the old one and nothing else changes")
sess = R.Session(log=quiet)
plan_b, after = ch.fix(sess, TEACH, PLAN, "Hint", [11], low_hint, ck, {**mocks, "revise": lambda owner: "not json"})
ok(sess.calls == 1 and after["score"] == 0 and plan_b == PLAN, "an unreadable fix is a failed fix (→ C), not a second try")

# C/D: placement. A new stage from stages.json holds its own planning workflow; new workflows read their stage's one
SHARE = changed(charter_items=ITEMS + ["Share result"], done_when=ITEMS + ["Share result"])
ACTIVE = list(range(1, 12))
GROWTH = {"id": "growth", "thinking": "reach and sharing", "tiers": ["feature"], "goal": "people share",
          "done_test": "a share path exists", "method": "share loop", "owns_factors": [], "inputs_from": ["product"]}


def placed(stage_id="growth", inputs=("Growth plan",), planning=True):
    st = dict(GROWTH, id=stage_id)
    wfs = ([D("Growth plan", stage_id, [11], ["Product plan"])] if planning else []) + [
        P("Share result", stage_id, [11], inputs=list(inputs) + ["Board and number pad"])]
    return json.dumps({"factors": [], "stages": [st], "workflows": wfs})


sess = R.Session(log=quiet)
merged, new, faults = ch.place(sess, SHARE, PLAN, [11], ACTIVE, lambda: placed())
ok(sess.calls == 1 and not faults and [s_["id"] for s_ in merged["stages"]][-1] == "growth"
   and names_of(merged)[-2:] == ["Growth plan", "Share result"] and R.kind(wf_of(merged, "Growth plan")) == "decide",
   "placement of a sharing item adds stage growth with its planning workflow")
ok(names_of(merged)[:len(PLAN["workflows"])] == names_of(PLAN) and R.plan_faults(merged, SHARE, items=ACTIVE) == [],
   "the plan is kept and the merged plan passes the rules")
pt = sess.trail[0]["user"]
ok(not SCENARIO.search(wording(pt.split("Reply format:")[0], SHARE, PLAN, "Share result")),
   "the placement prompt names no scenario")
tries = []
sess = R.Session(log=quiet)
merged, new, faults = ch.place(sess, SHARE, PLAN, [11], ACTIVE,
                               lambda: (tries.append(1), placed("social" if len(tries) == 1 else "growth"))[1])
ok(sess.calls == 2 and not faults and "growth" in [s_["id"] for s_ in merged["stages"]]
   and "'social' is not one of" in sess.trail[1]["user"], "unknown stage social → one retry with the fault named")
ok(any("needs its own decide workflow" in f for f in ch.placement_faults(json.loads(placed(planning=False)), PLAN)),
   "a new stage without a planning workflow is a fault")
ok(any("Growth plan" in f and "inputs_from" in f for f in ch.placement_faults(json.loads(placed(inputs=())), PLAN)),
   "a new workflow that does not read its stage's planning workflow is a fault")
build_new = {"factors": [], "stages": [], "workflows": [P("Streaks", "build", [11], inputs=["Page shell"])]}
ok(any("decide workflow" in f for f in ch.placement_faults(build_new, PLAN))
   and not ch.placement_faults({**build_new, "workflows": [P("Streaks", "build", [11], inputs=["Product plan"])]}, PLAN),
   "in a stage without a planning workflow, a new workflow reads one of the plan's planning workflows")
sess = R.Session(log=quiet)
merged, new, faults = ch.place(sess, SHARE, PLAN, [11], ACTIVE, lambda: "{}")
ok(sess.calls == 2 and faults and any("R1: item 11" in f for f in faults), "an empty placement keeps its faults (→ re-plan)")

# ---- Task 6: plan_change, the eleven Sudoku prompts as scripted mock scenarios (spec, Success table)
def goal_with(*new, drop=()):
    """The charter after Identity: new item texts take the next charter numbers; drop: charter numbers removed."""
    keep = [t for i, t in enumerate(ITEMS, 1) if i not in drop]
    return changed(charter_items=ITEMS + list(new), done_when=keep + list(new))


def scripted(match=(), fails=(), edits=None, revise=None, places=()):
    """Mock replies and a count of each kind of call. match: the match reply's intents; fails: per judge call,
    {workflow: [question ids answered no]}; edits: {owner: (fields changed, docs)}; revise: fields the one fix changes;
    places: placement replies, in order."""
    n = {"match": 0, "judge": 0, "edit": 0, "revise": 0, "place": 0}

    def judge(spec):
        n["judge"] += 1
        return R.mock_judge(spec, fail=fails[n["judge"] - 1] if n["judge"] <= len(fails) else None, compare="better")

    def edit(owner):
        n["edit"] += 1
        fields, docs = edits[owner]
        return json.dumps({"workflow": dict(wf_of(PLAN, owner), **fields), "docs": docs})

    def rev(owner):
        n["revise"] += 1
        return json.dumps({**PLAN, "workflows": [dict(wf_of(PLAN, owner), **revise)]})

    def place():
        n["place"] += 1
        return json.dumps(places[min(n["place"], len(places)) - 1])

    def m():
        n["match"] += 1
        return json.dumps({"intents": list(match)})

    return {"match": m, "judge": judge, "edit": edit, "revise": rev, "place": place}, n


def change(new, **script):
    mocks, n = scripted(**script)
    rec = ch.plan_change(SUDOKU, new, PLAN, SUDOKU_WFS, mocks=mocks, log=quiet)
    return rec, n, {x["item"]: x["final"] for x in rec["intents"]}


def mt(item, owner=None, stage=None):
    return {"item": item, "owner": owner, "stage": stage, "why": "scripted"}


def placement(stages=(), workflows=()):
    return {"factors": [], "stages": list(stages), "workflows": list(workflows), "why": "scripted"}


# 1. Rename the levels: A on Levels and new game (remove + add, one edit); Product plan first
rec, n, dec = change(goal_with(RENAMED, drop=[3]), match=[mt(11, "Levels and new game")],
                     edits={"Levels and new game": ({"goal": "Renamed levels"}, ["Product plan"])})
ok(dec == {3: "A", 11: "A"} and rec["docs"] == ["Product plan", "Technical design"]
   and rec["revise"] == ["Levels and new game"] and not rec["new"] and not rec["replan"],
   "rename the levels: A on Levels and new game; Product plan first (and Technical design, which informed item 3)")
ok(rec["calls"] == 3 and n["edit"] == 1, "an A intent takes at most 3 calls (match, score, edit with its docs list)")
ok(wf_of(rec["plan"], "Levels and new game")["delivers"] == [11] and rec["intents"][0]["owner"] == "Levels and new game",
   "the removed number's owner comes from the run's workflows; the added one replaces it")

rec, n, dec = change(goal_with(RENAMED, drop=[3]), match=[mt(11, "Levels and new game")],
                     edits={"Levels and new game": ({"goal": "Renamed levels"}, [])})
ok(rec["docs"] == ["Product plan", "Technical design"],
   "an edit moves the item to a new number: every planning doc that informed the old number is revised")

# 2. Add dark mode: A on Look and layout; Style guide and Technical design first
rec, n, dec = change(goal_with("Dark mode"), match=[mt(11, "Look and layout")],
                     edits={"Look and layout": ({}, ["Technical design", "Style guide"])})
ok(dec == {11: "A"} and rec["docs"] == ["Style guide", "Technical design"] and rec["revise"] == ["Look and layout"]
   and rec["calls"] == 3 and not rec["replan"], "dark mode: A on Look and layout; Style guide, Technical design first")

# 3. Teach techniques in hints: B → A on Hint, one fix
rec, n, dec = change(goal_with("Hints teach the technique"), match=[mt(11, "Hint")], fails=[{"Hint": ["Z1"]}],
                     revise={"approach": "Teach the technique behind each hint."})
x = rec["intents"][0]
ok(x["decision"] == "B" and x["final"] == "A" and x["score"] == 0.70 and n["revise"] == 1 and rec["calls"] == 4,
   "teach techniques: B → A on Hint with exactly one revise call")
ok(rec["revise"] == ["Hint"] and rec["docs"] == ["Product plan", "Technical design"] and not rec["new"],
   "the fixed owner's planning docs come first")
# Review focus 2: on a second failure the intent goes to C, not another round
rec, n, dec = change(goal_with("Hints teach the technique"), match=[mt(11, "Hint")],
                     fails=[{"Hint": ["Z1"]}, {"Hint": ["Z1"]}], revise={"approach": "Same."},
                     places=[placement(workflows=[P("Technique lessons", "build", [11], inputs=["Product plan", "Hint"])])])
ok(dec == {11: "C"} and n["revise"] == 1 and n["place"] == 1 and rec["new"] == ["Technique lessons"]
   and wf_of(rec["plan"], "Hint") == wf_of(PLAN, "Hint") and not rec["replan"],
   "B still below after its one fix → C; the failed fix is not kept")

# 4. Remove save and resume: A remove; Save dropped; Technical design re-homes storage first; no call
rec, n, dec = change(goal_with(drop=[7]))
ok(dec == {7: "A"} and rec["drop"] == ["Save and resume"] and rec["docs"] == ["Technical design"]
   and rec["revise"] == ["Reasons to come back", "Page wiring"] and rec["calls"] == 0 and not rec["replan"],
   "remove save: dropped with no call; Technical design first, then the workflows that read it")

# 5. Richer come-back features: C directly (size), 2 new build workflows, no revise call
COMEBACK = [P("Play history", "build", informs=[11], inputs=["Technical design", "Page shell"]),
            P("Come-back panel", "build", [11], inputs=["Product plan", "Play history", "Board and number pad"])]
rec, n, dec = change(goal_with("Streaks, best times and a daily goal"), match=[mt(11, "Reasons to come back")],
                     fails=[{"Reasons to come back": ["S1", "S2"]}], places=[placement(workflows=COMEBACK)])
x = rec["intents"][0]
ok(x["decision"] == "C" and x["weakest_part"] == "size" and n["revise"] == 0 and n["place"] == 1
   and rec["new"] == ["Play history", "Come-back panel"] and rec["calls"] == 4 and not rec["replan"],
   "richer come-back: size → C straight away, no revise call, two new workflows (≤ 5 calls)")
ok(rec["docs"] == ["Product plan", "Technical design"] and not rec["revise"], "the new workflows' planning docs first")

# 6. Import a newspaper puzzle: C + A
rec, n, dec = change(goal_with("Type in a puzzle from a newspaper", "An entered puzzle is checked for one solution"),
                     match=[mt(11, None, "build"), mt(12, "Puzzle engine")],
                     edits={"Puzzle engine": ({}, ["Technical design"])},
                     places=[placement(workflows=[P("Puzzle entry", "build", [11], inputs=["Product plan", "Puzzle engine"])])])
ok(dec == {11: "C", 12: "A"} and rec["new"] == ["Puzzle entry"] and rec["revise"] == ["Puzzle engine"]
   and rec["docs"] == ["Product plan", "Technical design"] and rec["calls"] == 5 and not rec["replan"],
   "import a puzzle: C + A")

# 7. Daily Challenge: A, C, D (growth), decided independently; the merged plan passes plan_faults(items=)
GROW = [D("Growth plan", "growth", [13], ["Product plan"]),
        P("Share result", "growth", [13], inputs=["Growth plan", "Board and number pad"]),
        P("Daily streak", "build", [12], inputs=["Product plan", "Levels and new game"])]
daily = goal_with("A daily puzzle, the same for everyone", "A daily streak", "Share the day's result")
rec, n, dec = change(daily, match=[mt(11, "Levels and new game"), mt(12, None, "build"), mt(13)],
                     edits={"Levels and new game": ({}, ["Product plan"])},
                     places=[placement([GROWTH], GROW)])
ok(dec == {11: "A", 12: "C", 13: "D"} and rec["new"] == ["Growth plan", "Share result", "Daily streak"]
   and rec["docs"] == ["Product plan", "Growth plan"] and not rec["replan"], "daily challenge: A, C, D (growth)")
ok(R.plan_faults(rec["plan"], daily, items=range(1, 14)) == [] and rec["calls"] == 5,
   "three intents in five calls; the merged plan passes the rules on charter numbers")

# 8. Learn mode: D (learning), D, A
LEARN = {**GROWTH, "id": "learning", "thinking": "teaching", "goal": "people learn the techniques"}
LESSONS = [D("Lesson plan", "learning", [11, 12], ["Product plan"]),
           P("Lessons", "learning", [11], inputs=["Lesson plan", "Page shell"]),
           P("Practice sets", "learning", [12], inputs=["Lesson plan", "Puzzle engine"])]
rec, n, dec = change(goal_with("Learn mode with guided lessons", "Practice puzzles per technique",
                               "Hints link to the lesson"),
                     match=[mt(11), mt(12), mt(13, "Hint")], edits={"Hint": ({}, [])},
                     places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
ok(dec == {11: "D", 12: "D", 13: "A"} and "learning" in [s_["id"] for s_ in rec["plan"]["stages"]]
   and rec["docs"] == ["Product plan", "Lesson plan"] and rec["revise"] == ["Hint"] and not rec["replan"],
   "learn mode: D (learning), D, A")

# 9-11. Online races (Identity asks, the charter is unchanged), ship by tonight (nothing in the charter moves), Killer
for label, new in (("online races", changed()), ("ship by tonight", changed(open_inputs=["ship by tonight"]))):
    rec, n, dec = change(new)
    ok(not rec["intents"] and rec["calls"] == 0 and not rec["replan"] and rec["plan"] == PLAN, f"{label}: no plan change")
rec, n, dec = change(killer)
ok(rec["replan"] and rec["calls"] == 0 and not rec["intents"], "make it Killer: a full re-plan, no change planning")
rec, n, dec = change(changed(rules=SUDOKU["rules"] + ["No sound"]))
ok(rec["replan"] and rec["calls"] == 0, "a rule or standard change with no item change is re-planned in full")

# failures never mean "no change"
rec, n, dec = change(goal_with("Dark mode"), match=[], places=[placement(
    workflows=[P("Dark theme", "build", [11], inputs=["Style guide", "Look and layout"])])])
ok(dec == {11: "C"} and n["match"] == 2 and rec["new"] == ["Dark theme"] and not rec["replan"],
   "match unreadable twice: the intent is placed (C), not dropped")
rec, n, dec = change(goal_with("Dark mode"), match=[mt(11, None, "build")], places=[placement()])
ok(rec["replan"] and n["place"] == 2 and rec["faults"], "a placement still failing after one retry → full re-plan")
rec, n, dec = change(goal_with("Dark mode"), match=[mt(11, None, "build")], fails=[{"Dark theme": ["D1"]}] * 3,
                     places=[placement(workflows=[P("Dark theme", "build", [11], inputs=["Style guide"])])])
ok(rec["replan"] and n["place"] == 2 and n["judge"] == 2, "a new workflow below the gate: placed once more, then re-plan")
rec = ch.plan_change(SUDOKU, goal_with("Dark mode"), PLAN, SUDOKU_WFS, log=quiet)
ok(rec["intents"][0]["final"] == "C" and rec["new"] and not rec["replan"], "the default mocks place a new item offline")
with tempfile.TemporaryDirectory() as td:
    ch.plan_change(SUDOKU, goal_with("Dark mode"), PLAN, SUDOKU_WFS, log=quiet, out_dir=td)
    ok(json.load(open(os.path.join(td, "change.json"), encoding="utf-8"))["trail"], "change.json keeps every call")

# ---- Task 7: into the run (mock J2 with realization on): J2_CHANGE=1 routes a change after done through Identity,
# plan_change and a fixed hand-off to Adaptation
import j2_flow_test as F      # noqa: E402  (sets J2's test env: temp runs and memory)
j2 = F.j2
j2.j2_check.tap_targets, j2.j2_check.behavior = F.fake_tap_targets, F.fake_behavior
j2.j2_check.check, j2.j2_check.find_chrome = F.fake_check, lambda: None
os.environ["J2_REALIZATION"] = "1"
BASE_CH_MOCKS = ch.default_mocks


def rename_mocks(goal, plan, added):
    """The judge finds item 3's builder owns the renamed item (A) and names the planning workflow to revise first."""
    m = BASE_CH_MOCKS(goal, plan, added)
    m["match"] = lambda: json.dumps({"intents": [{"item": n, "owner": "Build item 3", "stage": None, "why": "mock"}
                                                 for n in added]})
    m["edit"] = lambda owner: json.dumps({"workflow": wf_of(plan, owner), "docs": ["Plan"]})
    return m


def built_run(on=True):
    os.environ["J2_CHANGE"] = "1" if on else "0"
    run = j2.J2Run()
    F.say(run, F.BREW_LAB)
    F.finish(run)
    assert run.outcome.startswith("Done") and run.real, run.outcome
    return run


TASKS = []


def change_after_done(run, text, charter, mocks=rename_mocks):
    """The Requester asks for a change; Identity's mock returns charter(old goal) as the updated charter."""
    call = run.call

    def spy(fn, fmt, task, mock, **kw):
        TASKS.append((fn, task))
        if fn == "identity" and "ASKED FOR A CHANGE" in task:
            mock = lambda: json.dumps({"to_requester": "Charter updated for your change.", "to_agents": "@Adaptation "
                                       "Charter updated.", "enough": True, "next": "Adaptation", "goal": charter(run.goal)})
        return call(fn, fmt, task, mock, **kw)
    run.call, ch.default_mocks = spy, mocks
    try:
        n0, c0 = len(run._all_wfs()), len(run.chat)
        F.say(run, text)
        F.finish(run)
    finally:
        ch.default_mocks = BASE_CH_MOCKS
    return run._all_wfs()[n0:], run.chat[c0:]


def renamed(g):
    return {**g, "done_when": [("Three levels, renamed: Easy, Medium, Hard" if i == 2 else t)
                               for i, t in enumerate(g["done_when"])]}


run = built_run()
old = list(run.goal["done_when"])
new, msgs = change_after_done(run, "Rename the levels", renamed)
names = [w["name"] for w in new]
ok(names == ["Plan (change 1)", "Build item 3 (change 1)"] and new[0]["revises"] == "W-1" and new[1]["revises"] == "W-4",
   "rename: the planning-doc revision is registered before the build revision, and nothing else")
ok(j2.is_artifact(new[0]) and "Plan (change 1)" in new[1]["dependencies"] and all(w["status"] == "done" for w in new),
   "the build revision waits for the doc revision; both are built")
ok(run.outcome.startswith("Done"), "the run ends Done after the change")
ok(json.load(open(os.path.join(run.dir, "goal.v1.json"), encoding="utf-8"))["done_when"] == old,
   "the previous charter is kept as goal.v1.json")
log = json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))
ok(isinstance(log, list) and len(log) == 1 and log[0]["request"] == "Rename the levels" and log[0]["docs"] == ["Plan"]
   and log[0]["revise"] == ["Build item 3"] and {x["final"] for x in log[0]["intents"]} == {"A"},
   "change.json is a list with one record: A on the owner, the planning doc first")
ok(any(m["who"] == "adaptation" and m.get("change") and "Plan" in m["text"] for m in msgs),
   "Adaptation posts a one-line summary of the change plan")
ok(any("CHANGE PLAN" in t for f, t in TASKS if f == "adaptation"),
   "Adaptation gets the change plan as fixed text")
d = ch.charter_diff(run.real_base, {**run.goal, "done_when": old})
ok(run.real_base["done_when"] == run.goal["done_when"] and d["added"] == [3] and d["removed"] == [len(run.goal["charter_items"])],
   "the next change diffs against this change's charter: undoing the rename brings item 3 back, it is not 'no change'")
n_new = len(run.goal["charter_items"])
ok(any(n_new in (w.get("delivers") or []) for w in run.real["plan"]["workflows"])
   and not any(3 in (w.get("delivers") or []) for w in run.real["plan"]["workflows"]),
   "and against this change's plan: the owner now delivers the renamed item")
run.change["phase"] = "plan"
_, refused, _ = run._register([{"name": "Extra section"}])
ok(refused and "not in the change plan" in refused[0], "while a change is open, a workflow not in its plan is refused")
run.change["phase"] = "closed"

run = built_run()
new, msgs = change_after_done(run, "Make it nicer", lambda g: dict(g))
ok(not new and run.outcome.startswith("Done") and not os.path.exists(os.path.join(run.dir, "change.json"))
   and any(m["who"] == "identity" and m.get("to_user") and "stay as they are" in m["text"] for m in msgs),
   "no item, rule or standard changed: no plan change, and the Requester is told so")
run = built_run()
run.budget += 200           # a full re-plan builds the whole plan again
new, msgs = change_after_done(run, "No sound effects", lambda g: {**g, "rules": list(g.get("rules") or []) + ["No sound"]})
ok(any(m["who"] == "identity" and m.get("to_user") and "rules or standards" in m["text"] and "whole plan" in m["text"]
       for m in msgs) and run.outcome.startswith("Done"),
   "a rule-only change is a full re-plan, and the Requester is told why")
run = built_run(on=False)
new, msgs = change_after_done(run, "Rename the levels", renamed)
ok(not os.path.exists(os.path.join(run.dir, "change.json")) and not any(w["name"].endswith("(change 1)") for w in new),
   "J2_CHANGE=0: a change after done takes today's path")

# ---- Task 8: Relay from revised docs. After a planning doc's revision is built, each direct reader the change plan
# doesn't revise is asked once "affected? what?"; affected (or unreadable after one retry) → a revision; "no" stops
R_BASE = R.default_mocks


def doc_chain_mocks(goal):
    """The mock realization plan with a second planning doc, Design, that reads Plan; Build item 1 reads only Design."""
    m = R_BASE(goal)

    def plan(rnd):
        p = R.mock_plan(goal)
        p["workflows"].insert(1, dict(p["workflows"][0], name="Design", informs=[1], inputs_from=["Plan"]))
        p["workflows"][2]["inputs_from"] = ["Design"]
        return json.dumps(p)
    m.update(plan=plan, revise=plan, judge=lambda rnd, p, spec: R.mock_judge(spec, compare="better"))
    return m


def relay_run(script):
    R.default_mocks = doc_chain_mocks
    try:
        run = built_run()
    finally:
        R.default_mocks = R_BASE
    run.relay_script, run.budget = script, run.budget + 50      # room for the relay's revisions
    new, msgs = change_after_done(run, "Rename the levels", renamed)
    asked = {x["name"]: x for x in json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))[-1]["relay"]}
    return run, [w["name"] for w in new], asked, new


run, names, asked, new = relay_run({"Design": "affected", "Build item 1": "garbage"})
ok(names == ["Plan (change 1)", "Build item 3 (change 1)", "Design (change 1)", "Build item 1 (change 1)"]
   and run.outcome.startswith("Done"), "relay: the affected doc and the reader behind it are revised, and the run ends Done")
ok(asked["Design"]["affected"] and asked["Design"]["doc"] == "Plan (change 1)" and asked["Build item 1"]["doc"] == "Design (change 1)"
   and "Build item 3" not in asked, "a reader linked only through a doc is reached; the change plan's own workflows are not asked")
ok(asked["Build item 1"]["affected"] and "no readable" in asked["Build item 1"]["what"]
   and "Design (change 1)" in new[3]["dependencies"] and new[3]["revises"] == "W-3",
   "a garbled reply after one retry counts as affected: the reader is revised after the doc")
ok(all(not asked[f"Build item {i}"]["affected"] for i in (2, 4, 5, 6, 7)), "the other readers of Plan said no")
run, names, asked, new = relay_run({})
ok(names == ["Plan (change 1)", "Build item 3 (change 1)"] and not asked["Design"]["affected"]
   and "Build item 1" not in asked and run.outcome.startswith("Done"), "a doc that says no stops the walk below it")
plan_text = next(t for f, t in TASKS if f == "adaptation" and "CHANGE PLAN" in t).split("CHANGE PLAN")[1].split("\n[")[0]
relay_text = next(t for f, t in TASKS if f.startswith("W-") and "JUST REVISED" in t).split("ARTIFACTS YOU READ")[0]
ok(not SCENARIO.search(plan_text) and not SCENARIO.search(relay_text.split("\n", 1)[1].replace("artifacts/plan.md", "")),
   "the change plan's hand-off and the relay question name no scenario")

os.environ.pop("J2_CHANGE", None)

print(f"change_test: {passed} checks passed")
