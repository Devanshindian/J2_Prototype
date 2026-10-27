"""Offline checks of the change relay (j2_relay.py and its wiring in j2.py): python relay_test.py

A change on a finished realization run goes charter -> planning documents (each owner decides) -> affected build
sections. The graph, the replies, the charter diff and the carried checks are tested on their own; the wiring is
tested on mock runs. No AI calls.
"""
import json
import os
import sys

os.environ["STUDIO_MOCK"] = "1"          # before llm is imported
os.environ.pop("STUDIO_PROVIDER", None)
import j2_relay as relay                 # noqa: E402

passed = 0


def ok(cond, label):
    global passed
    if not cond:
        sys.exit(f"FAIL: {label}")
    passed += 1


def W(i, name, outputs, deps, revises=None):
    return {"id": f"W-{i}", "name": name, "outputs": outputs, "dependencies": deps, "revises": revises, "status": "done"}


SITE = ["index.html"]
# runs/j2-20261027-142038/workflows.json (the baseline): ids, names, outputs, dependencies and revises only
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

# ---- Task 1: the planning graph
nodes = relay.planning_nodes(BASE_WFS, "index.html")
ok([n["root"] for n in nodes] == ["W-1", "W-2", "W-3", "W-4"], "planning nodes are the four file workflows")
ok(nodes[1]["parents"] == ["W-1"] and nodes[0]["parents"] == [], "a node's parents are the planning workflows it depends on")
ok(relay.relay_waves(nodes) == [["W-1"], ["W-2", "W-3", "W-4"]], "design, copy and architecture answer together")
c = relay.build_candidates(BASE_WFS, ["W-2"], "index.html")
ok("W-15" in c and "W-17" in c,
   "nav (W-11, latest W-15, reached via W-10) and the race board (W-14, latest W-17) are reached")
ok("W-5" not in c and "W-16" in c and "W-11" not in c, "a revised section is named by its latest revision")
ok(len(c) == len(set(c)) and all(relay.latest(BASE_WFS, x)["id"] == x for x in c), "each section once, by its latest id")
ok(relay.build_candidates(BASE_WFS, [], "index.html") == [], "no changed document, no candidates")
two = BASE_WFS + [W(19, "design-guide r2", ["design.md"], ["product-spec"], "W-2")]
ok(relay.latest(two, "W-2")["id"] == "W-19" and [n["id"] for n in relay.planning_nodes(two, "index.html")][1] == "W-19",
   "a second change uses the latest revision of each planning node")
ok(relay.latest(two, "W-19")["id"] == "W-19" and relay.planning_nodes(two, "index.html")[1]["root"] == "W-2",
   "a revision's root is the original workflow")

ok(relay.direct_readers(BASE_WFS, "W-2") == ["W-16", "W-18"] and relay.direct_readers(BASE_WFS, "W-1")[:3] == ["W-2", "W-3", "W-4"],
   "a document's direct readers, by latest revision: design is read by styles and game core")

# ---- Task 2: the replies the relay's calls must give
ok(relay.parse_verdict('{"verdict":"change-here","reason":"palette","changes":["Dark palette"]}')["changes"] == ["Dark palette"],
   "a change verdict parses")
ok(relay.parse_verdict('Here: {"verdict":"no-change","reason":"same product","changes":[]}')["verdict"] == "no-change",
   "a no-change verdict parses, with text around the JSON")
ok(relay.parse_verdict('{"verdict":"change-here","reason":"x","changes":[]}') is None, "change-here needs changes")
ok(relay.parse_verdict('{"verdict":"no-change","reason":"x","changes":["y"]}') is None, "no-change carries no changes")
ok(relay.parse_verdict('{"verdict":"maybe","reason":"x","changes":[]}') is None, "an unknown verdict is refused")
ok(relay.parse_verdict("sure, looks fine") is None and relay.parse_verdict(None) is None, "prose is not a verdict")
ok(relay.parse_agreement('{"agree":false,"reason":"needs own state"}', build=False) == {"agree": False, "reason": "needs own state"},
   "a planning reader objects")
ok(relay.parse_agreement('{"agree":true,"reason":"ok"}', build=True) is None, "a build reader must say affected")
ok(relay.parse_agreement('{"agree":true,"reason":"ok","affected":true,"what":"race board colours"}', build=True)
   == {"agree": True, "reason": "ok", "affected": True, "what": "race board colours"}, "a build reader agrees and says affected")
ok(relay.parse_agreement('{"agree":"yes","reason":"ok"}', build=False) is None, "agree must be true or false")
ok(relay.parse_affected('{"affected":false,"what":""}') == {"affected": False, "what": ""}, "affected parses")
ok(relay.parse_affected('{"affected":true}') is None, "affected needs what")

# ---- Task 3: the charter diff; an edited item keeps its number and its coverage
WARM, DARK = "Warm, friendly, uncluttered look and tone", "Dark, minimal, uncluttered look and tone"
old = {"charter_items": ["A", "B"], "done_when": ["A", "B"], "standards": [WARM], "rules": ["No ads"]}
new = {"done_when": ["A", "B2", "C"], "standards": [DARK], "rules": ["No ads"]}
d = relay.charter_diff(old, new)
ok(d["added"] == [(3, "C")] and d["edited"] == [(2, "B", "B2")] and d["removed"] == [],
   "the diff names items by charter number: one edited, one added")
ok(d["standards"]["edited"] == [(WARM, DARK)] and d["rules"] == {"added": [], "edited": [], "removed": []},
   "the diff names the edited standard; unchanged rules give nothing")
d2 = relay.charter_diff({"charter_items": ["A", "B", "C"], "done_when": ["A", "C"]}, {"done_when": ["A"]})
ok(d2["removed"] == [(3, "C")] and d2["edited"] == [] and d2["added"] == [], "a dropped item is removed, by its number")
ok(not relay.diff_empty(d) and relay.diff_empty(relay.charter_diff(old, dict(old))), "an unchanged charter is an empty diff")

import j2_flow_test as F      # noqa: E402  (sets J2's test env: temp runs and memory)
j2 = F.j2
j2.j2_check.tap_targets, j2.j2_check.behavior = F.fake_tap_targets, F.fake_behavior
j2.j2_check.check, j2.j2_check.find_chrome = F.fake_check, lambda: None
r = j2.J2Run()
r.goal = {"charter_items": ["A", "B", "C"], "done_when": ["A", "B2", "C"]}
r.workflows = [{"id": "W-9", "covers": [2], "covers_text": ["B"], "status": "done"}]
r._follow_edits({"added": [], "removed": [], "edited": [(2, "B", "B2")]})
ok(r.workflows[0]["covers_text"] == ["B2"] and r.goal["charter_items"][1] == "B2",
   "an edited item keeps its charter number and stays covered by the workflow that covered it")
ok(r._wf_items(r.workflows[0]) == [2] and r._no("B2") == 2, "J2 sees the edited item as covered, at number 2")

# ---- Task 4: a revision's checks follow the charter
DESIGN = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests_data", "relay_design.md"), encoding="utf-8").read()
W2_CHECKS = [{"text": "design.md exists", "type": "file-exists", "target": "design.md", "expect": True, "item": 1},
             {"text": "Design standards appear", "type": "facts-present",
              "target": ["Large tap targets and readable numbers", WARM], "expect": True, "item": 2}]
heads = relay.headings_of(DESIGN)
ok(heads and all(not h.startswith("#") for h in heads) and len(heads) == len(set(heads)), "headings come out without #, once each")
dd = relay.charter_diff({"charter_items": [], "done_when": [], "standards": ["Large tap targets and readable numbers", WARM]},
                        {"done_when": [], "standards": ["Large tap targets and readable numbers", DARK]})
cc = relay.carry_checks(W2_CHECKS, dd, DESIGN)
fp = [c for c in cc if c["type"] == "facts-present"]
ok(fp and fp[0]["target"] == ["Large tap targets and readable numbers", DARK], "the facts check targets the new standard")
ok(not any("warm" in json.dumps(c).lower() for c in cc), "no check keeps the word the change removed")
ok({c["target"] for c in cc if c["type"] == "heading-present"} == set(heads), "every earlier heading must still be there")
ok(any(c["type"] == "file-exists" for c in cc) and W2_CHECKS[1]["target"][1] == WARM, "other checks carry over; the input is not changed")
gone = relay.charter_diff({"charter_items": [], "done_when": [], "standards": [WARM, "X"]}, {"done_when": [], "standards": ["X"]})
ok(not [c for c in relay.carry_checks(W2_CHECKS, gone, DESIGN) if c["type"] == "facts-present" and WARM in c["target"]],
   "a removed standard is dropped from the facts check")

# ---- Task 5: a change in a realization run goes to Identity on the change path
import llm  # noqa: E402
prompts, real_ask = [], llm.ask


def spy(system, user, mock, **kw):
    prompts.append(user)
    return real_ask(system, user, mock, **kw)


def done_run(on=True, script=None, plan=None):
    """A mock realization run (Brew Lab) to Done, with J2_FIXES=0 as the default install has it."""
    os.environ["J2_REALIZATION"], os.environ["J2_FIXES"] = ("1" if on else "0"), "0"
    real_mocks = j2.j2_realization.default_mocks
    if plan:
        j2.j2_realization.default_mocks = lambda goal: {**real_mocks(goal), "plan": lambda rnd: json.dumps(plan(goal)),
                                                         "revise": lambda rnd: json.dumps(plan(goal))}
    try:
        run = j2.J2Run()
        run.budget = 400                 # room for a change; the budget tests set budget = spent themselves
        run.relay_script = dict(script or {})
        F.say(run, F.BREW_LAB)
        F.finish(run)
    finally:
        j2.j2_realization.default_mocks = real_mocks
    assert run.outcome.startswith("Done"), run.outcome
    return run


def change(run, text):
    prompts.clear()
    llm.ask = spy
    try:
        F.say(run, text)
        F.finish(run)
    finally:
        llm.ask = real_ask


run = done_run()
change(run, "Make the look dark and minimal")
asked = [p for p in prompts if "THE REQUESTER ASKED FOR A CHANGE" in p]
ok(len(asked) == 1, "Identity got the change on the change path once, with J2_FIXES=0")
ok("edit or remove what it contradicts" in asked[0] and "standards" in asked[0], "and may edit what the change contradicts")
ok(run.change and run.change["id"] == "C-1" and "charter" in run.change["history"], "the change opened and passed the charter")
ok(os.path.exists(os.path.join(run.dir, "change.json")), "change.json is written")
ok([t for _, t in run.change["diff"]["added"]] == ["Change: Make the look dark and minimal"],
   "the charter diff records the item Identity added for the change")
plain = done_run(on=False)
change(plain, "Make the look dark and minimal")
ok(not any("THE REQUESTER ASKED FOR A CHANGE" in p for p in prompts) and plain.change is None
   and not os.path.exists(os.path.join(plain.dir, "change.json")), "J2_REALIZATION=0: the J2_FIXES=0 path is unchanged")

# ---- Task 6: a planning file can be revised; the earlier version is kept
run = done_run()
plan_wf = next(w for w in run._all_wfs() if w["name"] == "Plan")
art = os.path.join(run.dir, "artifacts", "plan.md")
before_text = open(art, encoding="utf-8").read()
node = {"id": plan_wf["id"], "name": "Plan", "root": plan_wf["id"], "outputs": plan_wf["outputs"], "parents": []}
run.change = {"id": "C-1", "diff": relay.charter_diff(run.goal, run.goal), "nodes": {}}
spent0 = run.spent
rid = run._register_doc_revision(node, ["Add a short section on opening offers"], "the Requester asked for offers")
rv = run._wf(rid)
ok(rv and rv["revises"] == plan_wf["id"] and rv["outputs"] == plan_wf["outputs"] and rv["status"] == "registered",
   "a planning revision is registered by code, revising the planning workflow, with the same file")
ok(rv["name"] == "Plan r2" and rv["section"] == plan_wf["section"] and rv.get("relay") == "C-1",
   "it is named after the original, owns the same section, and is tagged with the change")
ok(run.spent - spent0 == rv["cost"] > 0, "it is charged like any workflow")
ok(any(c["type"] == "heading-present" for c in rv["atoms"][0]["verification"])
   and "opening offers" in json.dumps(rv["atoms"][0]["how"]), "its checks keep the old headings; its task names the change")
run._run_artifact(rv, {"name": rv["name"]}, 3)
kept = os.path.join(run.dir, "artifacts", "plan.v1.md")
ok(rv["status"] == "done" and os.path.exists(kept) and open(kept, encoding="utf-8").read() == before_text,
   "the revision ran; the earlier version is kept as plan.v1.md")
now = open(art, encoding="utf-8").read()
ok(now != before_text and all(h in relay.headings_of(now) for h in relay.headings_of(before_text)),
   "plan.md is the new version and keeps every earlier heading")
rid2 = run._register_doc_revision({**node, "id": rid}, ["One more change"], "again")
run._run_artifact(run._wf(rid2), {"name": "x"}, 3)
ok(run._wf(rid2)["name"] == "Plan r3" and run._wf(rid2)["revises"] == rid
   and os.path.exists(os.path.join(run.dir, "artifacts", "plan.v2.md")), "a second revision is r3 and keeps plan.v2.md")
broke = done_run()
broke.change = {"id": "C-1", "diff": relay.charter_diff(broke.goal, broke.goal), "nodes": {}}
broke.budget = broke.spent
pw = next(w for w in broke._all_wfs() if w["name"] == "Plan")
ok(broke._register_doc_revision({**node, "id": pw["id"], "root": pw["id"]}, ["x"], "y") is None
   and broke.change.get("short") and "budget" in broke.change["short"], "out of budget: nothing registered, the reason kept")

# ---- Task 7: the relay walks the planning documents in order, each owner decides, readers agree
def three_docs(goal):
    """Plan, then Design and Arch side by side (both read Plan); Build item 1 reads Design, Build item 2 reads Arch,
    Build item 3 reads only Build item 1 (so it reaches Design through another section)."""
    p = j2.j2_realization.mock_plan(goal)
    base = p["workflows"][0]
    p["workflows"][1:1] = [{**base, "name": "Design", "stage": "design", "inputs_from": ["Plan"], "informs": []},
                           {**base, "name": "Arch", "stage": "engineering", "inputs_from": ["Plan"], "informs": []}]
    for w in p["workflows"]:
        w["inputs_from"] = {"Build item 1": ["Design"], "Build item 2": ["Arch"], "Build item 3": ["Build item 1"]}.get(
            w["name"], w["inputs_from"])
    p["stages"][1:1] = [{**p["stages"][0], "id": "design", "inputs_from": ["product"], "owns_factors": []},
                        {**p["stages"][0], "id": "engineering", "inputs_from": ["product"], "owns_factors": []}]
    return p


def posts(run, kind):
    return [m for m in run.chat if m.get("relay") == kind and m.get("change") == run.change["id"]]


def wf_named(run, name):
    return next(w for w in run._all_wfs() if w["name"] == name)


run = done_run(plan=three_docs, script={"Design": "change-here"})
ok([w["name"] for w in run._all_wfs() if j2.is_artifact(w)] == ["Plan", "Design", "Arch"], "the test plan has three documents")
change(run, "Make the look dark and minimal")
v = posts(run, "verdict")
ok([m["node"] for m in v] == ["Plan", "Design", "Arch"], "verdicts in dependency order: Plan, then Design and Arch")
ok(run.change["waves"] == [[wf_named(run, "Plan")["id"]], [wf_named(run, "Design")["id"], wf_named(run, "Arch")["id"]]],
   "Design and Arch answer in the same wave")
nd = {n["name"]: n for n in run.change["nodes"].values()}
ok(nd["Design"]["verdict"] == "change-here" and nd["Plan"]["verdict"] == nd["Arch"]["verdict"] == "no-change",
   "each owner's verdict is recorded")
revs = [w for w in run._all_wfs() if w.get("relay") == run.change["id"]]
dfile = j2.artifact_path(wf_named(run, "Design"))
ok([w["name"] for w in revs] == ["Design r2"] and revs[0]["status"] == "done"
   and os.path.exists(os.path.join(run.dir, dfile.replace(".md", ".v1.md"))), "one revision of Design, its old version kept")
ok(nd["Design"]["revisions"] == [revs[0]["id"]] and run.change["documents_changed"] == [nd["Design"]["root"]],
   "change.json names the document that changed")
ag = posts(run, "agreement")
ok(ag and all(m["node"] == "Design" for m in ag) and {m["reader"] for m in ag} == {"Build item 1"},
   "Design's direct reader (Build item 1) is asked to agree")
ok("relay" in run.change["history"] and run.outcome.startswith("Done"), "the run goes on and ends Done")

run = done_run(plan=three_docs, script={"Design": "change-here", "Build item 1->Design": "object-once"})
change(run, "Make the look dark and minimal")
revs = [w["name"] for w in run._all_wfs() if w.get("relay") == run.change["id"]]
ok(revs == ["Design r2", "Design r3"] and [m["agree"] for m in posts(run, "agreement")] == [False, True],
   "one objection: a second revision, then agreement")

run = done_run(plan=three_docs, script={"Design": "change-here", "Build item 1->Design": "object"})
change(run, "Make the look dark and minimal")
revs = [w["name"] for w in run._all_wfs() if w.get("relay") == run.change["id"]]
ok(revs == ["Design r2", "Design r3"] and len(posts(run, "ruling")) == 1, "two objections: Identity rules, no third revision")

run = done_run(plan=three_docs, script={"Plan": "garbage"})
change(run, "Make the look dark and minimal")
ok(any(m["who"] == "system" and "Plan" in m["text"] and "no-change" in m["text"] for m in run.chat)
   and run.change["nodes"][wf_named(run, "Plan")["id"]]["verdict"] == "no-change", "a malformed verdict: one retry, then no-change")

run = done_run(plan=three_docs, script={"Design": "change-here"})
run.budget = run.spent
change(run, "Make the look dark and minimal")
revs = [w for w in run._all_wfs() if w.get("relay") == run.change["id"]]
ok(revs and revs[0]["status"] == "done" and run.budget > run.spent - 1 and "build" in run.change["history"],
   "out of budget mid-relay: the run asks, gets credits, and the relay resumes where it stopped")

# ---- Task 8: only affected sections are revised; the validator holds the line
CH = {"phase": "build", "changed_names": ["design-guide", "W-2"], "affected_refs": ["W-17", "W-14", "build-two-player-race"]}
PLAN_NAMES = {"product-spec", "design-guide", "copy-deck", "architecture", "W-1", "W-2", "W-3", "W-4"}
site = lambda **kw: {"outputs": ["index.html"], **kw}
ok(relay.change_problems(site(revises="W-17"), CH, PLAN_NAMES) == [], "revising an affected section is fine")
ok(any("not marked affected" in x for x in relay.change_problems(site(revises="W-9"), CH, PLAN_NAMES)),
   "revising a section the relay did not mark affected is refused")
ok(relay.change_problems(site(revises="W-9", fixes=["F-3"]), CH, PLAN_NAMES) == [], "a fix for an Audit finding is exempt")
ok(any("names no planning document" in x for x in relay.change_problems(site(dependencies=["build-final-wiring"]), CH, PLAN_NAMES)),
   "a new section must name the planning documents it reads")
ok(any("no revised planning document" in x for x in relay.change_problems(site(dependencies=["copy-deck"]), CH, PLAN_NAMES)),
   "a new section must follow from a revised document")
ok(relay.change_problems(site(dependencies=["design-guide", "build-final-wiring"]), CH, PLAN_NAMES) == [],
   "a new section that reads the revised document is fine")
ok(any("relay has not finished" in x for x in relay.change_problems(site(revises="W-17"), {**CH, "phase": "relay"}, PLAN_NAMES)),
   "no build work before the relay has finished")
ok(relay.change_problems({"outputs": ["design.md"], "revises": "W-2"}, {**CH, "phase": "relay"}, PLAN_NAMES) == [],
   "planning work is not build work")
nochange = {**CH, "changed_names": [], "affected_refs": []}
ok(relay.change_problems(site(revises="W-9"), nochange, PLAN_NAMES) == [] and
   any("names no planning document" in x for x in relay.change_problems(site(dependencies=[]), nochange, PLAN_NAMES)),
   "no document changed: any section may be revised, but a new one still names its documents")

run = done_run(plan=three_docs, script={"Design": "change-here", "Build item 3": "affected"})
change(run, "Make the look dark and minimal")
b3 = wf_named(run, "Build item 3")
aff = posts(run, "affected")
ok({m["reader"] for m in aff} == {"Build item 3"}, "only sections not asked during agreement are asked whether they are affected")
ok([a["name"] for a in run.change["affected"]] == ["Build item 3"], "change.json lists the affected sections")
task = next((p for p in prompts if "CHANGE C-1: REVISE EXACTLY THESE SECTIONS" in p), "")
ok(b3["id"] in task.split("CHANGE C-1: REVISE EXACTLY THESE SECTIONS")[1][:300]
   and wf_named(run, "Build item 2")["id"] + " " not in task.split("CHANGE C-1: REVISE EXACTLY THESE SECTIONS")[1][:300],
   "Adaptation's task names exactly the affected section")
ok(any(w.get("revises") == b3["id"] and w["status"] == "done" for w in run._all_wfs()), "the affected section is revised")
ok(run.outcome.startswith("Done") and run.change["phase"] == "closed", "the run ends Done and the change is closed")

run = done_run(plan=three_docs, script={})
change(run, "Make the look dark and minimal")
ok(run.change["documents_changed"] == [] and any("No planning document changed" in m["text"] for m in posts(run, "done")),
   "no document changed: the relay says so")
ok(run.outcome.startswith("Done") and not posts(run, "affected"), "and the build goes on as today")

# ---- Task 9: per-change records, the Requester finishing, and no names in the relay
run = done_run(plan=three_docs, script={"Design": "change-here", "Build item 3": "affected"})
change(run, "Make the look dark and minimal")
rep = json.load(open(os.path.join(run.dir, "report.json"), encoding="utf-8"))
ch = rep.get("changes") or [{}]
ok(len(ch) == 1 and ch[0].get("id") == "C-1" and ch[0].get("documents_changed") == ["Design"] and ch[0].get("affected") == ["Build item 3"],
   "report.json lists the change, the document it changed and the section it affected")
ok(ch[0]["messages"] > 0 and ch[0]["calls"] > 0 and ch[0]["credits"] > 0 and isinstance(ch[0]["post_fixes"], list),
   "with its messages, calls, credits and post-build fixes")
saved = json.load(open(os.path.join(run.dir, "change.json"), encoding="utf-8"))
ok(saved[0]["phase"] == "closed" and saved[0]["closed"] and saved[0]["messages"] == ch[0]["messages"],
   "change.json holds the same totals once closed")

run = done_run(plan=three_docs, script={"Design": "change-here"})
run.budget = run.spent
llm.ask = spy
F.say(run, "Make the look dark and minimal")
ok(run.paused and run.paused["kind"] == "relay_budget", "out of budget mid-relay: the run asks")
F.say(run, "Finish as it is")
F.finish(run)
llm.ask = real_ask
ok(run.change["closed"] == "finished by the Requester" and run.change["phase"] == "closed"
   and not [w for w in run._all_wfs() if w.get("relay")], "the Requester finishes: the change closes, nothing is revised")

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "j2_relay.py"), encoding="utf-8").read()
stage_ids = [x["id"] for x in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents", "j2",
                                                    "stages.json"), encoding="utf-8"))["stages"]]
ok(stage_ids and not [x for x in stage_ids if f'"{x}"' in src or f"'{x}'" in src],
   "j2_relay.py names no stage: everything comes from the run")

# ---- Final review fixes (I1-I6): each test failed before its fix
# I1: the charter diff is taken against the charter as it was when the change opened, even when J2.a runs twice
run = done_run()
real_stamp, calls_ = run._stamp_check, []


def stamp_once_bad():
    calls_.append(1)
    return (False, "mock: rejected once") if len(calls_) == 1 else real_stamp()


run._stamp_check = stamp_once_bad
change(run, "Make the look dark and minimal")
ok(len(calls_) >= 2 and [t for _, t in run.change["diff"]["added"]] == ["Change: Make the look dark and minimal"],
   "I1: J2.a ran twice for the change and the diff still names what the change added")

# I6: an Audit fix that adds a section is exempt from the relay's rules
ok(relay.change_problems(site(dependencies=["build-final-wiring"], fixes=["F-1"]), CH, PLAN_NAMES) == [],
   "I6: a new section that fixes an Audit finding is not held to the relay's rules")

# I2: a budget pause in an objection round: after the credits, the paid-for revision is made
run = done_run(plan=three_docs, script={"Design": "change-here", "Build item 1->Design": "object-once"})
run.budget = run.spent + wf_named(run, "Design")["cost"]          # room for the first revision only
change(run, "Make the look dark and minimal")
revs = [w["name"] for w in run._all_wfs() if w.get("relay") == run.change["id"]]
ok(revs == ["Design r2", "Design r3"] and [m["agree"] for m in posts(run, "agreement")] == [False, True],
   "I2: out of budget in the objection round: after the credits, the second revision is made and agreed")

# I3: Finish on the relay's budget question ends the run, uncharges unbuilt relay work, and keeps the charter true
run = done_run(plan=three_docs, script={"Design": "change-here"})
goal0 = json.loads(json.dumps(run.goal))
run.budget = run.spent
llm.ask = spy
F.say(run, "Make the look dark and minimal")
F.say(run, "Finish as it is")
llm.ask = real_ask
ok(not run.paused and run.done and (run.outcome or "").startswith("Done")
   and any(m["who"] == "identity" and "leave your change out" in m["text"] for m in run.chat),
   "I3: Finish ends the run with no further question (the charter is back, so the site is Done)")
ok(run.goal["done_when"] == goal0["done_when"] and run.goal.get("standards") == goal0.get("standards"),
   "I3: no document was revised, so the charter goes back to what the product is")
ok(not [w for w in run._all_wfs() if w.get("relay") and w.get("charged")], "I3: nothing unbuilt stays charged")

# I5: a change starts a fresh cycle, so the previous cycle's turn count can't stop the relay
run = done_run(plan=three_docs, script={"Design": "change-here"})
run.cycle_turns = run._turn_cap() - 1
c0 = run.cycle
change(run, "Make the look dark and minimal")
done_at = next((i for i, m in enumerate(run.chat) if m.get("relay") == "done" and m.get("change") == run.change["id"]),
               len(run.chat))
ok(run.cycle > c0 and "build" in run.change["history"]
   and not any(m.get("pause") == "limit" for m in run.chat[run.change["chat0"]:done_at]),
   "I5: the relay runs in a new cycle and reaches the build without a turn-cap question")

# I4: a second change on the same run; Identity's "previous" ruling restores this change's own previous version
run = done_run(plan=three_docs, script={"Design": "change-here"})
change(run, "Make the look dark and minimal")
ok(run.change["id"] == "C-1" and run.change["phase"] == "closed", "I4: the first change closed")
run.relay_script = {"Design": "change-here", "Build item 1->Design": "object", "ruling": "previous"}
change(run, "Use a larger type size")
ok(run.change["id"] == "C-2" and len(run.changes) == 2, "I4: a second change opens as C-2")
c2 = [w for w in run._all_wfs() if w.get("relay") == "C-2"]
ok([w["name"] for w in c2] == ["Design r3", "Design r4"], "I4: C-2 revises the latest Design (r3, r4), not the original")
dpath = os.path.join(run.dir, j2.artifact_path(wf_named(run, "Design")))
ok(c2[-1].get("kept") and open(dpath, encoding="utf-8").read() == open(c2[-1]["kept"], encoding="utf-8").read()
   and len(posts(run, "ruling")) == 1, "I4: the ruling restores the version C-2's last revision replaced")

print(f"relay_test: {passed} checks passed")
