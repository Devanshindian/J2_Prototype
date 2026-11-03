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
# live 31 Oct: Identity appended the change to the statement ("... The hint now also teaches: ..."); that is the same
# goal with a note, not a new one, so it must route by items, not re-plan
noted = changed(statement=SUDOKU["statement"] + " The hint now also teaches the technique it uses.")
ok(not ch.charter_diff(SUDOKU, noted)["goal_changed"], "a sentence added after the statement → not a goal change")
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
ok(ch.decide("added", {"owner": None, "stage": "build", "stage_in_plan": True}, None) == "C",
   "no owner, the stage that must decide it is in the plan → C")
ok(ch.decide("added", {"owner": None, "stage": "learning", "stage_in_plan": False}, None) == "D",
   "no owner, the stage that must decide it is not in the plan → D")
ok(ch.decide("added", NONE, None) == "D", "no owner and no stage → D")
ok(ch.decide("added", OWNED, {"score": 0.80, "weakest_part": "how"}) == "A", "owner at the gate → A")
ok(ch.decide("added", OWNED, SIZE) == "C", "weakest part size → C straight away, no fix")
ok(ch.decide("added", OWNED, LOW) == "B", "the edited owner below the gate, not size → B (one improvement)")
ok(ch.decide("added", OWNED, LOW, after_fix={"score": 0.86, "weakest_part": None}) == "B",
   "improved and judged again ≥ 0.80 → final B")
ok(ch.decide("added", OWNED, LOW, after_fix={"score": 0.79, "weakest_part": "how"}) == "C", "B judged again 0.79 → C")
ok(ch.decide("added", dict(OWNED, too_big=True), HIGH) == "C" and ch.decide("added", OWNED) == "C",
   "an owner the item is too big for → C; no score for the edited owner (a reply lacked it) → C")
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
ok(m[11]["stage"] == "growth" and not m[11]["stage_in_plan"] and ch.decide("added", m[11], None) == "D"
   and ch.decide("added", m[12], None) == "D", "the deciding stage is not in the plan (or none is named): D")
sess = R.Session(log=quiet)
m = ch.match(sess, TWO, PLAN, [11, 12], lambda: json.dumps({"intents": [{"item": 11, "owner": None, "stage": "social",
                                                                          "why": ""}, {"item": 12, "owner": "Hint"}]}))
ok(sess.calls == 2 and m[11]["unread"] and "'social' is not a stage id" in sess.trail[1]["user"],
   "a stage id not in the stage table is sent back once")
mt_ = R.match_task(TWO, PLAN, [11])
ok("STAGE TABLE" in mt_ and "`learning`" in mt_ and "whether or not that stage is in the plan" in mt_
   and "only when the plan's planning workflows already decide everything" in mt_,
   "the match call names the deciding stage from the full stage table; a making stage only when the docs decide all")
SCENARIO = re.compile(r"sudoku|hint|level|puzzle|board|product plan|style guide|technical design|engineering|design",
                      re.I)


def wording(task, goal, plan, *texts):
    """A prompt without the run's own text (charter, plan, item texts): what code wrote."""
    out = task.replace(R.charter_text(goal, True), "").replace(json.dumps(plan, ensure_ascii=False), "")
    out = out.replace(R.stage_table(), "")
    for t in texts:
        out = out.replace(t, "")
    return out


ok(not SCENARIO.search(wording(R.match_task(TWO, PLAN, [11]), TWO, PLAN, "Daily challenge")),
   "the match prompt names no scenario")
ok(not SCENARIO.search(R.CHANGE_QUESTIONS[0][3] + prompt.split("CHANGE: ")[1].split(":\n")[0]),
   "G0 and the judge's change note name no scenario")

# ---- Task 5: act. The owner is edited (or dropped), judged and improved once; C and D place new workflows
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

# B: the edited owner judged on its own; below the gate, one improvement call that returns only that workflow
TEACH = changed(charter_items=ITEMS + ["Hints teach the technique"], done_when=ITEMS + ["Hints teach the technique"])
ck = R.checklist_items(None, TEACH, items=[11])
EDITED = {**PLAN, "workflows": [dict(w, delivers=[6, 11]) if w["name"] == "Hint" else w for w in PLAN["workflows"]]}
seen.clear()
sess = R.Session(log=quiet)
first = ch.judged(sess, TEACH, EDITED, ck, jmock({"Hint": ["Z1"]}), ["Hint"], {"Hint": [11]})
ok(list(first) == ["Hint"] and first["Hint"]["score"] == 0.70 and first["Hint"]["weakest_part"] == "how"
   and list(seen[-1]) == ["Hint"] and "G0" in seen[-1]["Hint"], "the edited owner is judged alone, with G0 and its items")
ok(ch.judged(R.Session(log=quiet), TEACH, EDITED, ck, lambda spec: json.dumps({"answers": []}), ["Hint"], {"Hint": [11]})
   == {}, "a judge reply that lacks the workflow (twice) gives no score, not a silent 0")
hint2 = dict(wf_of(PLAN, "Hint"), approach="Teach the named technique behind each hint.", delivers=[6], stage="design")
sess = R.Session(log=quiet)
better, lacked = ch.improve(sess, TEACH, EDITED, first, lambda names: json.dumps({"workflows": [hint2]}))
w = wf_of(better, "Hint")
ok(sess.calls == 1 and not lacked and w["approach"].startswith("Teach") and w["delivers"] == [6, 11] and w["stage"] == "build"
   and len(names_of(better)) == len(names_of(PLAN)), "B: one improvement call; code keeps its name, stage and delivers")
it = sess.trail[0]["user"]
ok("Improve only" in it and "missing:" in it and "11. Hints teach the technique" in it
   and not SCENARIO.search(it.split("THE JUDGE SCORED")[1].replace("Hint", "")), "the improvement reads the judge's notes")
sess = R.Session(log=quiet)
same, lacked = ch.improve(sess, TEACH, EDITED, first, lambda names: json.dumps({"workflows": [wf_of(PLAN, "Page shell")]}))
ok(sess.calls == 2 and lacked == ["Hint"] and same == EDITED, "an improvement reply without the workflow: lacked (→ C)")

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
merged, new, faults = ch.place(sess, SHARE, PLAN, [11], ACTIVE, lambda: placed(), {11: "D"})
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
                               lambda: (tries.append(1), placed("social" if len(tries) == 1 else "growth"))[1],
                               {11: "D"})
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
ok(any("item 11 goes in a stage already in the plan" in f for f in ch.placement_faults(json.loads(placed()), PLAN,
                                                                                    {11: "C"}))
   and any("add no new stage" in f for f in ch.placement_faults(json.loads(placed()), PLAN, {11: "C"})),
   "a C item placed in a new stage is a fault")
build_new_ok = {**build_new, "workflows": [P("Streaks", "build", [11], inputs=["Product plan"])]}
ok(any("item 11 goes in the new stage" in f for f in ch.placement_faults(build_new_ok, PLAN, {11: "D"}))
   and any("goes in the new stage growth" in f for f in ch.placement_faults(json.loads(placed("learning")), PLAN, {11: "D"}, {11: "growth"}))
   and not ch.placement_faults(build_new_ok, PLAN, {11: "C"}) and not ch.placement_faults(json.loads(placed()), PLAN, {11: "D"}),
   "a D item placed in a stage of the plan is a fault; each in its own place passes")
sess = R.Session(log=quiet)
ch.place(sess, SHARE, PLAN, [11], ACTIVE, lambda: placed(), {11: "C"})
ok("(in a stage already in the plan)" in sess.trail[0]["user"] and "add no new stage" in sess.trail[1]["user"],
   "placement is told each item's route, and a C item put in a new stage is sent back")

# ---- Task 6: plan_change, the eleven Sudoku prompts as scripted mock scenarios (spec, Success table)
def goal_with(*new, drop=()):
    """The charter after Identity: new item texts take the next charter numbers; drop: charter numbers removed."""
    keep = [t for i, t in enumerate(ITEMS, 1) if i not in drop]
    return changed(charter_items=ITEMS + list(new), done_when=keep + list(new))


LACKS = "lacks"


def scripted(match=(), fails=(), edits=None, improve=None, places=()):
    """Mock replies and a count of each kind of call. match: the match reply's intents; fails: per judge call,
    {workflow: [question ids answered no]} or LACKS (a reply with no answers); edits: {owner: (fields changed, docs)}
    or {owner: LACKS} (default: no change, no docs); improve: fields the improvement changes, or LACKS; places:
    placement replies, in order."""
    n = {"match": 0, "judge": 0, "edit": 0, "improve": 0, "place": 0}

    def judge(spec):
        n["judge"] += 1
        f = fails[n["judge"] - 1] if n["judge"] <= len(fails) else None
        return json.dumps({"answers": []}) if f == LACKS else R.mock_judge(spec, fail=f, compare="better")

    def edit(owner):
        n["edit"] += 1
        e = (edits or {}).get(owner, ({}, []))
        if e == LACKS:
            return json.dumps({"docs": []})
        return json.dumps({"workflow": dict(wf_of(PLAN, owner), **e[0]), "docs": e[1]})

    def imp(names):
        n["improve"] += 1
        wfs = [] if improve == LACKS else [dict(wf_of(PLAN, x) if any(w["name"] == x for w in PLAN["workflows"]) else
                                                {"name": x}, **(improve or {})) for x in names]
        return json.dumps({"workflows": wfs, "changes": []})

    def place():
        n["place"] += 1
        return json.dumps(places[min(n["place"], len(places)) - 1])

    def m():
        n["match"] += 1
        return json.dumps({"intents": list(match)})

    return {"match": m, "judge": judge, "edit": edit, "improve": imp, "place": place}, n


def change(new, **script):
    mocks, n = scripted(**script)
    rec = ch.plan_change(SUDOKU, new, PLAN, SUDOKU_WFS, mocks=mocks, log=quiet)
    return rec, n, {x["item"]: x["final"] for x in rec["intents"]}


def mt(item, owner=None, stage=None, too_big=False):
    return {"item": item, "owner": owner, "too_big": too_big, "stage": stage, "why": "scripted"}


def placement(stages=(), workflows=()):
    return {"factors": [], "stages": list(stages), "workflows": list(workflows), "why": "scripted"}


# 1. Rename the levels: A on Levels and new game (remove + add, one edit); Product plan first
rec, n, dec = change(goal_with(RENAMED, drop=[3]), match=[mt(11, "Levels and new game")],
                     edits={"Levels and new game": ({"goal": "Renamed levels"}, ["Product plan"])})
ok(dec == {3: "A", 11: "A"} and rec["docs"] == ["Product plan", "Technical design"]
   and rec["revise"] == ["Levels and new game"] and not rec["new"] and not rec["replan"],
   "rename the levels: A on Levels and new game; Product plan first (and Technical design, which informed item 3)")
ok(rec["calls"] == 3 and n["edit"] == 1 and n["judge"] == 1, "an A intent takes 3 calls: match, edit, judge the edited owner")
ok(wf_of(rec["plan"], "Levels and new game")["delivers"] == [11] and rec["intents"][0]["owner"] == "Levels and new game"
   and rec["intents"][1]["path"] == ["edit", "judged 0.95", "A"],
   "the removed number's owner comes from the run's workflows; the added one replaces it; the path is recorded")

rec, n, dec = change(goal_with(RENAMED, drop=[3]), match=[mt(11, "Levels and new game")],
                     edits={"Levels and new game": ({"goal": "Renamed levels"}, [])})
ok(rec["docs"] == ["Product plan", "Technical design"],
   "an edit moves the item to a new number: every planning doc that informed the old number is revised")

# 2. Add dark mode: A on Look and layout; Style guide and Technical design first
rec, n, dec = change(goal_with("Dark mode"), match=[mt(11, "Look and layout")],
                     edits={"Look and layout": ({}, ["Technical design", "Style guide"])})
ok(dec == {11: "A"} and rec["docs"] == ["Style guide", "Technical design"] and rec["revise"] == ["Look and layout"]
   and rec["calls"] == 3 and not rec["replan"], "dark mode: A on Look and layout; Style guide, Technical design first")

# 3. Teach techniques in hints: the edited Hint is below the gate, one improvement passes → B
rec, n, dec = change(goal_with("Hints teach the technique"), match=[mt(11, "Hint")], fails=[{"Hint": ["Z1"]}],
                     edits={"Hint": ({}, ["Product plan"])}, improve={"approach": "Teach the technique behind each hint."})
x = rec["intents"][0]
ok(x["final"] == "B" and x["score"] == 0.70 and x["after_fix"] == 0.95 and n["improve"] == 1 and rec["calls"] == 5
   and x["path"] == ["edit", "judged 0.70", "improved", "judged 0.95", "B"],
   "teach techniques: edit, judged 0.70, one improvement, judged 0.95 → B")
ok(rec["revise"] == ["Hint"] and rec["docs"] == ["Product plan"] and not rec["new"]
   and wf_of(rec["plan"], "Hint")["approach"].startswith("Teach") and wf_of(rec["plan"], "Hint")["delivers"] == [6, 11],
   "B keeps the improved owner, delivering the item; the edit's planning docs come first")
# on a second failure the intent goes to C, not another round; the owner keeps its old version
rec, n, dec = change(goal_with("Hints teach the technique"), match=[mt(11, "Hint")],
                     fails=[{"Hint": ["Z1"]}, {"Hint": ["Z1"]}], improve={"approach": "Same."},
                     places=[placement(workflows=[P("Technique lessons", "build", [11], inputs=["Product plan", "Hint"])])])
ok(dec == {11: "C"} and n["improve"] == 1 and n["place"] == 1 and rec["new"] == ["Technique lessons"]
   and wf_of(rec["plan"], "Hint") == wf_of(PLAN, "Hint") and "Hint" not in rec["revise"] and not rec["replan"],
   "B still below after its one improvement → C; neither the edit nor the improvement is kept")
# the edited owner fails on size → C straight away, no improvement call
rec, n, dec = change(goal_with("Streaks, best times and a daily goal"), match=[mt(11, "Reasons to come back")],
                     fails=[{"Reasons to come back": ["S1", "S2"]}], places=[placement(workflows=[
                         P("Come-back panel", "build", [11], inputs=["Product plan", "Board and number pad"])])])
ok(dec == {11: "C"} and n["improve"] == 0 and rec["intents"][0]["path"] == ["edit", "judged 0.72", "C"],
   "the edited owner's weakest part is size → C, no improvement call")

# 4. Remove save and resume: A remove; Save dropped; Technical design re-homes storage first; no call
rec, n, dec = change(goal_with(drop=[7]))
ok(dec == {7: "A"} and rec["drop"] == ["Save and resume"] and rec["docs"] == ["Technical design"]
   and rec["revise"] == ["Reasons to come back", "Page wiring"] and rec["calls"] == 0 and not rec["replan"],
   "remove save: dropped with no call; Technical design first, then the workflows that read it")

# 5. Richer come-back features: too big for its owner → C directly, two new build workflows, no edit
COMEBACK = [P("Play history", "build", informs=[11], inputs=["Technical design", "Page shell"]),
            P("Come-back panel", "build", [11], inputs=["Product plan", "Play history", "Board and number pad"])]
rec, n, dec = change(goal_with("Streaks, best times and a daily goal"),
                     match=[mt(11, "Reasons to come back", too_big=True)], places=[placement(workflows=COMEBACK)])
ok(dec == {11: "C"} and n["edit"] == 0 and n["improve"] == 0 and n["place"] == 1 and rec["intents"][0]["path"] == ["C"]
   and rec["new"] == ["Play history", "Come-back panel"] and rec["calls"] == 3 and not rec["replan"],
   "richer come-back: too big for its owner → C straight away, two new workflows, 3 calls")
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
rec, n, dec = change(daily, match=[mt(11, "Levels and new game"), mt(12, None, "build"), mt(13, None, "growth")],
                     edits={"Levels and new game": ({}, ["Product plan"])},
                     places=[placement([GROWTH], GROW)])
ok(dec == {11: "A", 12: "C", 13: "D"} and rec["new"] == ["Growth plan", "Share result", "Daily streak"]
   and rec["docs"] == ["Product plan", "Growth plan"] and not rec["replan"], "daily challenge: A, C, D (growth)")
ok(not rec["held"] and not rec["left_out"], "nothing held when every new workflow passes")
ok(R.plan_faults(rec["plan"], daily, items=range(1, 14)) == [] and rec["calls"] == 5,
   "three intents in five calls; the merged plan passes the rules on charter numbers")

# 8. Learn mode: D (learning), D, A
LEARN = {**GROWTH, "id": "learning", "thinking": "teaching", "goal": "people learn the techniques"}
LESSONS = [D("Lesson plan", "learning", [11, 12], ["Product plan"]),
           P("Lessons", "learning", [11], inputs=["Lesson plan", "Page shell"]),
           P("Practice sets", "learning", [12], inputs=["Lesson plan", "Puzzle engine"])]
learn = goal_with("Learn mode with guided lessons", "Practice puzzles per technique", "Hints link to the lesson")
rec, n, dec = change(learn, match=[mt(11, None, "learning"), mt(12, None, "learning"), mt(13, "Hint")],
                     places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
ok(dec == {11: "D", 12: "D", 13: "A"} and "learning" in [s_["id"] for s_ in rec["plan"]["stages"]]
   and rec["docs"] == ["Product plan", "Lesson plan"] and rec["revise"] == ["Hint"] and not rec["replan"],
   "learn mode: D (learning), D, A")
# step 6: new workflows below the gate get one improvement call for those workflows only, then a second look
rec, n, dec = change(learn, match=[mt(11, None, "learning"), mt(12, None, "learning"), mt(13, "Hint")], fails=[None, {"Lessons": ["I1"]}],
                     improve={"inputs_from": ["Lesson plan", "Page shell", "Practice sets"]},
                     places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
ok(not rec["replan"] and n["improve"] == 1 and n["judge"] == 3 and "Practice sets" in wf_of(rec["plan"], "Lessons")["inputs_from"],
   "a new workflow missing an input: one repair call, judged again, kept")
ok("Lessons" in rec["new"] and json.loads(scripted(improve={})[0]["improve"](["Lessons"]))["workflows"][0]["name"] == "Lessons",
   "the repair reply holds only the low workflows")
rec, n, dec = change(learn, match=[mt(11, None, "learning"), mt(12, None, "learning"), mt(13, "Hint")], fails=[None, {"Lessons": ["I1"]}, {"Lessons": ["I1"]}],
                     places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
x = rec["intents"][0]
ok(not rec["replan"] and n["improve"] == 1 and rec["held"] == {"Lessons": "not_ready"}
   and rec["left_out"] == [{"item": 11, "reason": "Lessons is not ready (0.70): no step for the goal"}]
   and x["left_out"] and rec["new"] == ["Lesson plan", "Practice sets"] and rec["intents"][1]["final"] == "D",
   "still below the gate after its repair: held as not ready, its item left out with the judge's note, the rest goes on")
ok("item 11 left out for now" in ch.summary(rec), "the summary says the item is left out")
# live 2 Nov (runs/j2-20261102-120952 item 20, P2, P4-P6): a workflow still below the gate after its improvement
# mixed two kinds of work or missed an input, and was held with everything behind it. Improve first, break down
# second: it is split into smaller workflows in its stage, which are judged; only a part still below is held.
SPLIT = {"splits": [{"workflow": "Lessons", "into": [
    P("Lesson texts", "learning", [], inputs=["Lesson plan"]),
    P("Lesson screens", "learning", [11], inputs=["Lesson texts", "Page shell"])]}]}
mocks, n = scripted(match=[mt(11, None, "learning"), mt(12, None, "learning"), mt(13, "Hint")],
                    fails=[None, {"Lessons": ["I1"]}, {"Lessons": ["I1"]}],
                    places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
asked = []
mocks["breakdown"] = lambda names: (asked.append(list(names)), json.dumps(SPLIT))[1]
rec = ch.plan_change(SUDOKU, learn, PLAN, SUDOKU_WFS, mocks=mocks, log=quiet)
ok(asked == [["Lessons"]] and not rec["held"] and not rec["left_out"] and rec["broken_down"] == {"Lessons": ["Lesson texts", "Lesson screens"]}
   and "Lessons" not in rec["new"] and {"Lesson texts", "Lesson screens"} <= set(rec["new"])
   and wf_of(rec["plan"], "Lesson screens")["delivers"] == [11] and "broken down" in rec["intents"][0]["path"]
   and not rec["replan"], "still below the gate after its improvement: broken down into parts that pass, nothing held")
# a break-down reply that loses the item is refused: the workflow is held as before
mocks, n = scripted(match=[mt(11, None, "learning"), mt(12, None, "learning"), mt(13, "Hint")],
                    fails=[None, {"Lessons": ["I1"]}, {"Lessons": ["I1"]}],
                    places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
mocks["breakdown"] = lambda names: json.dumps({"splits": [{"workflow": "Lessons", "into": [
    P("Lesson texts", "learning", [], inputs=["Lesson plan"])]}]})
rec = ch.plan_change(SUDOKU, learn, PLAN, SUDOKU_WFS, mocks=mocks, log=quiet)
ok(rec["held"] == {"Lessons": "not_ready"} and not rec.get("broken_down"),
   "a break-down that drops the workflow's item is refused, and the workflow is held as before")
ok("Break each one down" in R.breakdown_task(learn, PLAN, {"Lessons": {"score": 0.5, "weakest": "I1", "missing": []}}),
   "the break-down call asks for smaller workflows, one kind of work each")
# live 2 Nov (runs/j2-20261102-130338 0.70 -> 0.55, P3 0.70 -> 0.62): the improvement round can score lower; the
# better version is kept
mocks, n = scripted(match=[mt(11, None, "learning"), mt(12, None, "learning"), mt(13, "Hint")],
                    fails=[None, {"Lessons": ["I1"]}, {"Lessons": ["I1", "I2", "M1"]}],
                    improve={"goal": "worse"},
                    places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
rec = ch.plan_change(SUDOKU, learn, PLAN, SUDOKU_WFS, mocks=mocks, log=quiet)
ok(wf_of(rec["plan"], "Lessons")["goal"] != "worse" and rec["left_out"][0]["reason"].startswith("Lessons is not ready (0.70)"),
   "an improvement that scores lower is not kept: the better version and its score stand")
# live 2 Nov (runs/j2-20261102-111726): naming the technique in the hint opened a new learning stage (D) although
# the hint workflow already shows that message. The match call is told an item on an output's own content is its job.
ok("already shows" in R.match_task(learn, PLAN, [13]), "the match call names the owner of what an output already shows")
# a held planning workflow holds what reads it too
rec, n, dec = change(daily, match=[mt(11, "Levels and new game"), mt(12, None, "build"), mt(13, None, "growth")],
                     fails=[None, {"Growth plan": ["M1"]}, {"Growth plan": ["M1"]}], places=[placement([GROWTH], GROW)])
ok(not rec["replan"] and rec["held"] == {"Growth plan": "not_ready", "Share result": "waiting_on_dependency"}
   and [x["item"] for x in rec["left_out"]] == [13] and "waits on" in rec["left_out"][0]["reason"]
   and rec["new"] == ["Daily streak"] and "Growth plan" not in rec["docs"],
   "workflows behind a held one are held; only their items are left out")
# D is chosen when the deciding stage is missing, and placement is told its id
mocks, n = scripted(match=[mt(11, None, "learning"), mt(12, None, "learning"), mt(13, "Hint")],
                    places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": LESSONS}])
rec = ch.plan_change(SUDOKU, learn, PLAN, SUDOKU_WFS, mocks=mocks, log=quiet)
ok([x["final"] for x in rec["intents"]] == ["D", "D", "A"] and [x["stage"] for x in rec["intents"]][:2] == ["learning"] * 2,
   "the deciding stage (learning) is not in the plan → D with that stage")
with tempfile.TemporaryDirectory() as td:
    ch.plan_change(SUDOKU, learn, PLAN, SUDOKU_WFS, mocks=scripted(
        match=[mt(11, None, "learning"), mt(12, None, "build"), mt(13, "Hint")],
        places=[{"factors": [], "stages": [dict(LEARN, inputs_from=["product"])], "workflows": [
            LESSONS[0], LESSONS[1], P("Practice sets", "build", [12], inputs=["Lesson plan", "Puzzle engine"])]}])[0],
        log=quiet, out_dir=td)
    trail = json.load(open(os.path.join(td, "change.json"), encoding="utf-8"))["trail"]
    pt = next(t["user"] for t in trail if "NEW DONE-WHEN ITEMS no workflow" in t["user"])
    ok("(in a new stage from the stage table: learning)" in pt and "(in a stage already in the plan: build)" in pt,
       "placement is told each item's route and stage: D with the new stage's id, C with the plan stage")
# replan only for plan rule faults the retry did not fix
rec, n, dec = change(goal_with("Dark mode"), match=[mt(11, None, "build")], fails=[{"Dark theme": ["D1"]}] * 3,
                     places=[placement(workflows=[P("Dark theme", "build", [11], inputs=["Style guide"])])])
ok(not rec["replan"] and rec["left_out"][0]["item"] == 11 and not rec["faults"], "a weak workflow alone never re-plans")

# 9-11. Online races (Identity asks, the charter is unchanged), ship by tonight (nothing in the charter moves), Killer
for label, new in (("online races", changed()), ("ship by tonight", changed(open_inputs=["ship by tonight"]))):
    rec, n, dec = change(new)
    ok(not rec["intents"] and rec["calls"] == 0 and not rec["replan"] and rec["plan"] == PLAN, f"{label}: no plan change")
rec, n, dec = change(killer)
ok(rec["replan"] and rec["calls"] == 0 and not rec["intents"], "make it Killer: a full re-plan, no change planning")
rec, n, dec = change(changed(rules=SUDOKU["rules"] + ["No sound"]))
ok(rec["replan"] and rec["calls"] == 0, "a rule or standard change with no item change is re-planned in full")

# a reply missing the expected workflow sends the intent to C with a note: never a silent 0, never a crash
THEME = placement(workflows=[P("Dark theme", "build", [11], inputs=["Style guide", "Look and layout"])])
for label, script in (("edit", {"edits": {"Look and layout": LACKS}}), ("judge", {"fails": [LACKS, LACKS]}),
                      ("improvement", {"fails": [{"Look and layout": ["Z1"]}], "improve": LACKS})):
    rec, n, dec = change(goal_with("Dark mode"), match=[mt(11, "Look and layout")], places=[THEME], **script)
    x = rec["intents"][0]
    ok(dec == {11: "C"} and "lacked" in x["why"] and rec["new"] == ["Dark theme"] and not rec["replan"]
       and wf_of(rec["plan"], "Look and layout") == wf_of(PLAN, "Look and layout"),
       f"the {label} reply lacks the workflow → C with a note, the owner unchanged")
# Placement is told the route: a C item put in a new stage is sent back
rec, n, dec = change(goal_with("Share the day's result"), match=[mt(11, None, "build")],
                     places=[placement([GROWTH], [D("Growth plan", "growth", [11], ["Product plan"]),
                                                  P("Share result", "growth", [11], inputs=["Growth plan"])]),
                             placement(workflows=[P("Share result", "build", [11], inputs=["Product plan"])])])
ok(dec == {11: "C"} and n["place"] == 2 and "growth" not in [s_["id"] for s_ in rec["plan"]["stages"]] and not rec["replan"],
   "a C item goes in a stage of the plan: a new stage is refused and placed again")

# failures never mean "no change"
rec, n, dec = change(goal_with("Dark mode"), match=[], places=[THEME])
ok(dec == {11: "C"} and n["match"] == 2 and rec["new"] == ["Dark theme"] and not rec["replan"],
   "match unreadable twice: the intent is placed (C), not dropped")
rec, n, dec = change(goal_with("Dark mode"), match=[mt(11, None, "build")], places=[placement()])
ok(rec["replan"] and n["place"] == 2 and rec["faults"], "a placement still failing after one retry → full re-plan")
rec = ch.plan_change(SUDOKU, goal_with("Dark mode"), PLAN, SUDOKU_WFS, log=quiet)
ok(rec["intents"][0]["final"] == "C" and rec["new"] and not rec["replan"], "the default mocks place a new item offline")
ok(ch.summary(rec).startswith("item 11 a new workflow. Planning documents first: Product plan"),
   "the one-line summary names each route in words")
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
    m["match"] = lambda: json.dumps({"intents": [{"item": n, "owner": "Build item 3", "too_big": False, "stage": None,
                                                  "why": "mock"}
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


# Relay v1's agreement, ported: a reader may object; the doc goes back for a round (at most 2), then Identity rules
run, names, asked, new = relay_run({"Design": "object-once"})
log = json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))[-1]
ok("Plan (change 1, round 1)" in names and "Plan (change 1, round 2)" not in names and asked["Design"]["round"] == 1
   and asked["Design"]["agree"] and [a["name"] for a in log["objections"]] == ["Design"] and not log["rulings"]
   and run.outcome.startswith("Done"),
   "relay: an objection sends the doc back once; its readers answer again on the new version and the run ends Done")
ok(any(m.get("relay") == "objection" and "round 1" in m["text"] for m in run.chat)
   and any("objects to Plan (change 1)" in m["text"] for m in run.chat), "the objection and the round are posted")
kept = [f for f in os.listdir(os.path.join(run.dir, "artifacts")) if re.fullmatch(r"plan\.v\d+\.md", f)]
ok(len(kept) == 2 and new[0].get("kept") == "artifacts/plan.v1.md",
   "each revision of a planning doc keeps the file it overwrites (plan.v1.md, plan.v2.md)")
run, names, asked, new = relay_run({"Design": "object"})
log = json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))[-1]
ok("Plan (change 1, round 2)" in names and "Plan (change 1, round 3)" not in names
   and [r["keep"] for r in log["rulings"]] == ["latest"] and len(log["objections"]) == 3 and run.outcome.startswith("Done"),
   "after 2 objection rounds Identity rules (latest by default) and the walk goes on")
run, names, asked, new = relay_run({"Design": "object", "ruling": "previous"})
art = os.path.join(run.dir, "artifacts")
last = next(w for w in run._all_wfs() if w["name"] == "Plan (change 1, round 2)")
ok(open(os.path.join(art, "plan.md"), encoding="utf-8").read()
   == open(os.path.join(run.dir, last["kept"]), encoding="utf-8").read()
   and [r["keep"] for r in json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))[-1]["rulings"]]
   == ["previous"], "a 'previous' ruling puts back the version the last round overwrote")
ok(any("Do you agree with it? Object only if it breaks what you make" in t for f, t in TASKS if f.startswith("W-"))
   and any("revision round 2, after objections" in t for f, t in TASKS if f.startswith("W-")),
   "the reader's question asks for agreement and names the round")
# A revision's checks follow the charter: removed strings are not looked for; a doc keeps its headings
gone = ["At least three difficulty levels (such as Easy, Medium and Hard) can be chosen"]
ver = [{"type": "facts-present", "target": ["Easy, Medium and Hard", "New Game"], "expect": True},
       {"type": "facts-present", "target": "Easy, Medium and Hard", "expect": True},
       {"type": "heading-present", "target": "Old", "expect": True}]
out = ch.carry_checks(ver, gone, "# Plan\n\n## Levels\ntext\n## Levels\n")
ok(out[0]["target"] == ["New Game"] and len([c for c in out if c["type"] == "facts-present"]) == 1
   and [c["target"] for c in out if c["type"] == "heading-present"] == ["Plan", "Levels"] and ver[0]["target"][0].startswith("Easy"),
   "carry_checks: removed charter strings dropped (a check left empty goes), the old file's headings kept, input untouched")
ok(ch.parse_agreement('{"agree": false, "reason": "breaks the grid", "affected": true, "what": "x"}')["agree"] is False
   and ch.parse_agreement('{"agree": true, "affected": false, "what": ""}') is None,
   "an agreement reply needs agree, a reason, affected and what")
run, names, asked, new = relay_run({})
log = json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))[-1]
ok(log["gone"] == [t for t in old if t not in run.goal["done_when"]] and len(log["gone"]) == 1
   and log["objections"] == [] and log["rulings"] == [],
   "change.json records the charter strings the change removed, and no objections or rulings when every reader agreed")

def weak_mocks(goal, plan, added):
    """No workflow owns the new item; its new workflow stays below the gate after its one repair."""
    m = BASE_CH_MOCKS(goal, plan, added)
    m["judge"] = lambda spec: R.mock_judge(spec, fail={n: ["I1"] for n in spec if n.startswith("Change item")})
    return m


run = built_run()
TASKS.clear()
new, msgs = change_after_done(run, "Add a print button",
                              lambda g: {**g, "done_when": list(g["done_when"]) + ["A print button"]}, weak_mocks)
log = json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))[-1]
n_new = len(run.goal["charter_items"])
ok(not log["replan"] and [x["item"] for x in log["left_out"]] == [n_new] and log["held"],
   "J2: a new workflow still below the gate is held and its item left out; no re-plan")
told = [m for m in msgs if m["who"] == "identity" and m.get("to_user") and "left out for now" in m["text"]]
ok(told and '"A print button"' in told[0]["text"] and "Everything else in the change goes ahead" in told[0]["text"],
   "the Requester is told in plain words which item is left out and why")
ok(any("LEAVE OUT these items" in t for f, t in TASKS if f == "adaptation") and not any(
    w["name"].startswith("Change item") for w in new), "Adaptation's change plan leaves the held item out")

# ---- Task 9: live 31 Oct, the hint change (runs/j2-20261031-213453 msgs 144-192)
# it came in with 10 credits left: Priority cut both planning-doc revisions, the change never left "plan", and the
# validator refused every later fix. A change that costs more than what's left asks for the credits first.
run = built_run()
run.budget = run.spent + 1
new, msgs = change_after_done(run, "Rename the levels", renamed)
raised = next((i for i, m in enumerate(msgs) if m["who"] == "system" and m["text"].startswith("Budget raised")), None)
reg = next((i for i, m in enumerate(msgs) if m["who"] == "validator" and "(change 1)" in m["text"]), None)
ok(raised is not None and reg is not None and raised < reg
   and [w["name"] for w in new] == ["Plan (change 1)", "Build item 3 (change 1)"],
   "a change costing more than what's left asks for credits before Priority, then builds docs first")
ok(not json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))[-1].get("cut"),
   "funded in full: nothing in the change plan is cut")
# live 1 Nov (runs/j2-20261101-130032): with 0 credits left the loop's out-of-budget check asked first, and after the
# raise the run went to a plain Adaptation proposal: the change was never planned (no change.json, no docs first)
run = built_run()
run.budget = run.spent
new, msgs = change_after_done(run, "Rename the levels", renamed)
ok(os.path.exists(os.path.join(run.dir, "change.json"))
   and [w["name"] for w in new] == ["Plan (change 1)", "Build item 3 (change 1)"],
   "a change that arrives with nothing left is still planned as a change once the Requester adds credits")


def twin(w, name, **kw):
    """A proposal copied from a registered workflow: same outputs, checks, covers and price."""
    keep = ("goal_gap", "purpose", "outputs", "completion_check", "dependencies", "parts", "estimated_resources", "atoms", "cost",
            "envelope")
    out = {k: copy.deepcopy(w[k]) for k in keep if w.get(k) is not None}
    out["atoms"] = [{k: v for k, v in a.items() if k not in ("id", "status", "results", "attempts")}
                    for a in out.get("atoms") or []]
    return {**out, "name": name, "covers": list(w.get("covers") or []), **kw}


import copy                              # noqa: E402
# Priority funds part of the change plan: what it cut is recorded, the change builds, and later fixes are not refused
run = built_run()
run.budget += 100
src = next(w for w in run.workflows if w["name"] == "Build item 3")
run.change = {"id": "C-1", "rows": [], "allowed": ["Plan (change 1)", "Build item 3 (change 1)"], "phase": "plan",
              "relayed": [], "asked": {}, "request": "x", "left_out": []}
run.changes = [{"id": "C-1"}]
got, refused, _ = run._register([twin(src, "Build item 3 (change 1)", revises=src["id"])])
ok(got and run.change["phase"] == "build" and run.change.get("cut") == ["Plan (change 1)"],
   "a change row Priority didn't fund is recorded as cut and the change moves on to build")
_, refused, _ = run._register([{"name": "Extra section"}])
ok(refused and "not in the change plan" not in refused[0], "once the change builds, a later fix isn't refused for scope")
run.change = None

# live 2 Nov (runs/j2-20261102-111726 W-29, runs/j2-20261102-140419 build-learn-practice): Priority funded a change
# row, the validator refused it, and it was recorded as cut. In L2b it was never resent and item 17 failed Audit.
# A row the validator refused is resent, not cut, and the empty queue goes back to Adaptation before Audit.
run = built_run()
run.budget += 100
src = next(w for w in run.workflows if w["name"] == "Build item 3")
run.change = {"id": "C-1", "rows": [{"name": "Plan (change 1)", "covers": []}], "phase": "plan", "relayed": [],
              "allowed": ["Plan (change 1)", "Build item 3 (change 1)"], "asked": {}, "request": "x", "left_out": []}
run.changes = [{"id": "C-1"}]
got, refused, _ = run._register([twin(src, "Build item 3 (change 1)", revises=src["id"]),
                                 twin(src, "Plan (change 1)", outputs=[])])
ok(got and run.change["phase"] == "build" and not run.change.get("cut") and run.change.get("resend") == ["Plan (change 1)"],
   "a change row the validator refused is to be resent, not cut")
got[0]["status"] = "done"
run._turn_coordination({"kind": "schedule"})
ok(run.turn == "adaptation" and "Plan (change 1)" in run.handoff.get("why", ""),
   "with a refused change row not yet resent, the empty queue goes back to Adaptation, not to Audit")
again, _, _ = run._register([twin(src, "Plan (change 1)")])
ok(again and again[0].get("change") == "C-1" and not run.change.get("resend"), "once resent and registered, nothing waits")
run.change["resend"], run.change["resend_asks"] = ["Gone (change 1)"], 2
again[0]["status"] = "done"
run._turn_coordination({"kind": "schedule"})
ok(run.turn == "audit" and "Gone (change 1)" in run.change.get("cut", []),
   "a refused row still not resent after two asks is cut, and Audit goes ahead")
run.change = None

# W-13..W-15 waited on a renamed dependency; W-17..W-19 replaced them, but they stayed "held": Identity listed their
# items as not built four times, and Coordination never handed the empty queue to Audit
run = built_run()
run.budget += 100
src = next(w for w in run.workflows if w["name"] == "Build item 3")
old = {**copy.deepcopy(src), "id": "W-90", "name": "Save and resume", "status": "held", "charged": False}
run.workflows.append(old)
got, _, _ = run._register([twin(src, "Save and resume")])
ok(got and old["status"] == "superseded" and old.get("superseded_by") == got[0]["id"],
   "a waiting workflow replaced by a new one with the same name is superseded")
got[0]["status"] = "done"
ok(not run._waiting_work() and not any("(not built yet)" in str(g) for g in run._open_list(run.audits[-1], [])),
   "a superseded workflow is no waiting work and its items are not reported as not built")

# the Requester finished with design checks open: those are accepted, and a later change isn't stopped by them again
a = copy.deepcopy(run.audits[-1])
a["rubric"] = list(a.get("rubric") or []) + [{"id": "R-6", "pass": False, "verdict": "NEEDS_REVISION",
                                              "criterion": "Tap targets are big enough on phones"}]
ok(any("R-6" in f for f in j2.workable(a)), "a failing design check stops workable")
run.audits.append(a)
run._accept_open()
ok("R-6" in run.accepted and not any("R-6" in f for f in j2.workable({**a, "accepted": run.accepted})),
   "after 'finish as it is', the open design check is accepted and no longer stops workable")

# live 2 Nov (runs/j2-20261102-130338 item 16, runs/j2-20261102-140419 item 14): the Requester finished with a
# done-when item failing; after a later change it stopped workable again and was sent back for fixes until the
# same-failure guard ended the run. A done-when item the Requester finished with is accepted too.
run = built_run()
a = copy.deepcopy(run.audits[-1])
r0 = a["results"][0]
r0.update({"pass": False, "verdict": "NEEDS_REVISION"})
run.audits.append(a)
run._accept_open()
a["accepted"] = list(run.accepted)
ok(r0["criterion"] in run.accepted and not j2.workable(a),
   "after 'finish as it is', a failing done-when item is accepted and no longer stops workable")
# runs/j2-20261102-111726 cycle 6: workable by code, but Identity sent the accepted items back to Adaptation
TASKS.clear()
call = run.call


def keeps_fixing(fn, fmt, task, mock, **kw):
    TASKS.append((fn, task))
    return {"to_requester": "", "to_agents": "@Adaptation Make the board bigger.", "say": "@Adaptation Make the board "
            "bigger.", "done": False, "clause": "done_when", "next": "Adaptation"}


run.call, run.outcome, run.turn = keeps_fixing, None, "identity"
run._identity_audit({})
run.call = call
told = [t for f, t in TASKS if f == "identity"]
ok(told and "ACCEPTED BY THE REQUESTER" in told[0] and r0["criterion"] in told[0], "Identity is told what was accepted")
ok(run.turn is None and str(run.outcome).startswith("Done") and "accepted" in run.outcome
   and "Make the board" not in run.chat[-1]["text"],
   "workable with only accepted items open: done, saying what was accepted, not another fix round")

# live 2 Nov (runs/j2-20261102-120952): +250 came in with 0 left; the change plan then needed 260. That limit came
# with nothing built since "keep going", so it was taken as stale and the "add more" option was dropped: the Requester
# could only leave out or finish, and Learn mode was never built. A limit that names the credits it needs is a new ask.
run = built_run()
run.budget = run.spent
run.last_limit = {"state": (len(run.sites), len(run.workflows), run.spent), "decision": "continue"}
run._identity_limit({"kind": "limit", "out_of_budget": True, "budget_needed": 10,
                     "reason": "Out of budget: change C-1 needs about 260 work credits and 250 are left.",
                     "resume": {"to": "adaptation", "handoff": {"kind": "propose"}}})
ok(run.paused and "continue" in run.paused["handoff"]["choices"]
   and any(o.startswith("Add 10 work credits") for o in run.paused["questions"][0]["options"]),
   "a change that needs more credits than were just added still offers to add them")
run.paused = None

os.environ.pop("J2_CHANGE", None)

print(f"change_test: {passed} checks passed")
