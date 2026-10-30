"""Offline checks of the charter change (j2_change.py): python change_test.py

The planning graph ported from the change relay, the replies its calls must give, the charter diff on charter numbers,
item owners, and the decision rule. No AI calls.
"""
import os
import sys

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

print(f"change_test: {passed} checks passed")
