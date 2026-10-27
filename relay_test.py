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

print(f"relay_test: {passed} checks passed")
