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

print(f"relay_test: {passed} checks passed")
