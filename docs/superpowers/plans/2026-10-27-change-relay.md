# Change Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A change request on a finished realization run goes charter → planning documents (relay, each owner decides) → affected build sections, with documents revised as new versions and their readers agreeing first.

**Architecture:** Pure logic (graph, verdict parsing, check carry-over, charter diff, validator problems) lives in a new module `j2_relay.py` and is tested without a run. `j2.py` gets the wiring: the change goes to Identity on the change path, a new handoff kind `relay` walks the planning nodes, code registers planning revisions, agreement and affected calls follow, and Adaptation's build proposal is bound by the relay result. Everything is off unless the run is a realization website run with a change open.

**Tech Stack:** Python 3.14, existing J2 (`j2.py`, `j2_realization.py`, `llm.ask` with per-call `mock`), mock mode via `STUDIO_MOCK=1`.

**Spec:** `docs/superpowers/specs/2026-10-27-change-relay-design.md`

## Global Constraints

- Only when `self.realization` is true, the output is the website, and `self.change` is open. A run without a change request behaves exactly as today.
- No stage, document or workflow name in code or prompts (`realization_test.py` "no scenario" checks extend to `j2_relay.py`).
- Base J2 prompts unchanged: `plain_unchanged` passes for both `board="0"` and `board="1"`.
- `python realization_test.py` passes; `python j2_flow_test.py --fast` passes except the known `artifacts_tab` assertion.
- Planning revisions are priced as one `fix` part; verdict, agreement and affected calls add to `self.calls`, not credits.
- Kept versions are named `<stem>.v<k><ext>` beside the file (`design.md` → `design.v1.md`).
- Objection rounds: at most 2 (`RELAY_MAX_ROUNDS = 2`). Malformed verdict: one retry, then `no-change` with a system post.
- Commit author `fo@testlify.com`; never commit `docs/tax-comparison/` or `runs-broken/`.

## Review Focus

1. Every planning node says `no-change` (e.g. "change the button label wording" that no document pins): the change must still reach the build. Expected: relay records "no document changed", the validator's affected-only rule is off for this change, Adaptation proposes as today against the charter diff. Test in Task 8.
2. A second change after the first closed: the relay must use the latest revision of each planning node (W-19 revises W-2), not the original. Test in Task 1.
3. Budget runs short while the relay is registering a planning revision: the run pauses on the existing budget question and, after "add credits", resumes the relay where it stopped (`self.change["phase"]` survives). Test in Task 6.
4. The Requester answers "Finish as it is" while a change is open: `change.json` closes the change with `"closed": "finished by the Requester"` and the run ends as today. Test in Task 9.
5. A charter edit renames an item a workflow covers: coverage must follow the number, not the old text, so the item is not reported uncovered. Test in Task 3.

---

### Task 1: Planning graph

**Files:**
- Create: `j2_relay.py`
- Create: `relay_test.py` (same `ok()` style and env setup as `realization_test.py:1-30`)

**Interfaces:**
- Produces:
  - `planning_nodes(workflows: list[dict], site_file: str) -> list[dict]` — latest revision of every workflow whose `outputs` hold a file other than `site_file`; each node `{"id", "name", "root": str (id of the original), "outputs", "parents": list[str] (root ids of planning workflows named in dependencies)}`.
  - `relay_waves(nodes: list[dict]) -> list[list[str]]` — root ids in dependency order, nodes ready together in one wave.
  - `build_candidates(workflows: list[dict], changed_roots: list[str], site_file: str) -> list[str]` — latest-revision ids of built site sections whose `dependencies`, followed transitively through any workflow, reach a changed root.
  - `latest(workflows, root) -> dict` — the newest workflow whose `revises` chain ends at `root` (or the root itself).

- [ ] **Step 1: Write the failing tests** using a fixture copied from `runs/j2-20261027-142038/workflows.json` (ids, names, outputs, dependencies, revises only; stored inline in the test):

```python
nodes = relay.planning_nodes(BASE_WFS, "index.html")
ok([n["root"] for n in nodes] == ["W-1", "W-2", "W-3", "W-4"], "planning nodes are the four file workflows")
ok(relay.relay_waves(nodes) == [["W-1"], ["W-2", "W-3", "W-4"]], "design, copy and architecture answer together")
c = relay.build_candidates(BASE_WFS, ["W-2"], "index.html")
ok("W-15" in c and "W-17" in c, "nav (W-11, latest W-15, reached via W-10) and the race board (W-14, latest W-17) are reached")
ok("W-5" not in c and "W-16" in c, "a revised section is named by its latest revision")
two = BASE_WFS + [{"id": "W-19", "name": "design-guide r2", "outputs": ["design.md"], "dependencies": ["product-spec"], "revises": "W-2", "status": "done"}]
ok(relay.latest(two, "W-2")["id"] == "W-19" and [n["id"] for n in relay.planning_nodes(two, "index.html")][1] == "W-19",
   "a second change uses the latest revision of each planning node")
```

- [ ] **Step 2: Run to verify it fails**
Run: `python relay_test.py` — Expected: `ModuleNotFoundError: j2_relay`
- [ ] **Step 3: Implement the four functions in `j2_relay.py`.** Dependencies name workflows by name or id; resolve both. `revises` chains are followed to the root.
- [ ] **Step 4: Run** `python relay_test.py` — Expected: all checks pass
- [ ] **Step 5: Commit** `git add j2_relay.py relay_test.py && git commit -m "Relay: planning graph, waves and build candidates"`

### Task 2: Verdict and agreement replies

**Files:** Modify `j2_relay.py`; Test `relay_test.py`

**Interfaces:**
- Produces:
  - `parse_verdict(reply: str) -> dict | None` — `{"verdict": "no-change"|"change-here", "reason": str, "changes": list[str]}`; None when not JSON, verdict unknown, or `changes` empty with `change-here` / non-empty with `no-change`.
  - `parse_agreement(reply: str, build: bool) -> dict | None` — `{"agree": bool, "reason": str}` plus `{"affected": bool, "what": str}` when `build`; None when a required key is missing.
  - `parse_affected(reply: str) -> dict | None` — `{"affected": bool, "what": str}`.

- [ ] **Step 1: Failing tests**

```python
ok(relay.parse_verdict('{"verdict":"change-here","reason":"palette","changes":["Dark palette"]}')["changes"] == ["Dark palette"], "a change verdict parses")
ok(relay.parse_verdict('{"verdict":"change-here","reason":"x","changes":[]}') is None, "change-here needs changes")
ok(relay.parse_verdict('{"verdict":"no-change","reason":"x","changes":["y"]}') is None, "no-change carries no changes")
ok(relay.parse_verdict("sure, looks fine") is None, "prose is not a verdict")
ok(relay.parse_agreement('{"agree":false,"reason":"needs own state"}', build=False) == {"agree": False, "reason": "needs own state"}, "planning reader objects")
ok(relay.parse_agreement('{"agree":true,"reason":"ok"}', build=True) is None, "a build reader must say affected")
```

- [ ] **Step 2: Run** — Expected: FAIL `AttributeError: parse_verdict`
- [ ] **Step 3: Implement** with `json.loads` on the first `{...}` block in the reply (same extraction J2 uses for other replies).
- [ ] **Step 4: Run** — Expected: PASS
- [ ] **Step 5: Commit** `"Relay: verdict, agreement and affected replies"`

### Task 3: Charter diff and coverage that follows the number

**Files:** Modify `j2_relay.py`, `j2.py` (the charter save at ~3866-3884); Test `relay_test.py`

**Interfaces:**
- Produces:
  - `charter_diff(old: dict, new: dict) -> dict` — `{"added": [(n, text)], "edited": [(n, old, new)], "removed": [(n, text)], "standards": {"added": [], "edited": [(old, new)], "removed": []}, "rules": {same}}`; items by number from `charter_items`, standards/rules paired by position.
  - `J2Run._follow_edits(diff: dict) -> None` in `j2.py` — sets `covers_text` of every workflow covering an edited number to the new text.

- [ ] **Step 1: Failing tests**

```python
old = {"charter_items": ["A", "B"], "done_when": ["A", "B"], "standards": ["Warm, friendly, uncluttered look and tone"], "rules": ["No ads"]}
new = {"charter_items": ["A", "B2", "C"], "done_when": ["A", "B2", "C"], "standards": ["Dark, minimal, uncluttered look and tone"], "rules": ["No ads"]}
d = relay.charter_diff(old, new)
ok(d["added"] == [(3, "C")] and d["edited"] == [(2, "B", "B2")] and d["standards"]["edited"] == [("Warm, friendly, uncluttered look and tone", "Dark, minimal, uncluttered look and tone")], "the diff names items by number and the edited standard")
r = j2.J2Run(); r.workflows = [{"id": "W-9", "covers": [2], "covers_text": ["B"], "status": "done"}]
r._follow_edits(d)
ok(r.workflows[0]["covers_text"] == ["B2"], "an edited item stays covered by the workflow that covered its number")
```

- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: Implement**; in `j2.py` call `_follow_edits(charter_diff(old, self.goal))` where the change path saves the new charter, only when `self.change` is open.
- [ ] **Step 4: Run** `python relay_test.py && python realization_test.py` — Expected: PASS
- [ ] **Step 5: Commit** `"Relay: charter diff; edited items keep their coverage"`

### Task 4: Revision checks carried from the predecessor

**Files:** Modify `j2_relay.py`; Test `relay_test.py`

**Interfaces:**
- Produces:
  - `headings_of(text: str) -> list[str]` — markdown headings in order.
  - `carry_checks(verification: list[dict], diff: dict, old_text: str) -> list[dict]` — predecessor checks with facts-present `target` text edited per `diff` (standards, rules and items; replaced by the new string, dropped when removed), plus one `heading-present` check per heading of `old_text`.

- [ ] **Step 1: Failing test** with W-2's real atom (`workflows.json`, W-2 `atoms[0].verification`) and the diff from Task 3: the facts-present check on "Warm, friendly, uncluttered look and tone" now targets "Dark, minimal, uncluttered look and tone"; every heading of the run's `artifacts/design.md` has a heading-present check; no check targets the word "warm".
- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** — Expected: PASS
- [ ] **Step 5: Commit** `"Relay: a revision's checks follow the charter"`

### Task 5: The change goes to Identity, and Identity may edit what it contradicts

**Files:** Modify `j2.py` (`user_says` ~3198, `_run` dispatch ~3285-3292, J2.a change prompt ~3748-3754); Test `relay_test.py`

**Interfaces:**
- Produces: `J2Run.change: dict | None` — `{"id": "C-n", "request": str, "phase": "charter"|"relay"|"agree"|"build"|"audit"|"closed", "diff": dict, "nodes": {}, "affected": [], "post_fixes": [], "messages": int, "calls": int, "credits": int}`; saved as `change.json` (list of all changes) on every phase change.
- Produces: `J2Run._relay_on() -> bool` — `self.realization and not self.doc and not self.blueprint and self.change is not None`.

- [ ] **Step 1: Failing test** — a mock realization run (`j2_run(True)` from `realization_test.py`, `J2_FIXES=0`) to Done, then `F.say(run, "Make the look dark and minimal")`: Identity got the change path task once (the prompt has "THE REQUESTER ASKED FOR A CHANGE"), its prompt says "edit or remove what it contradicts", `run.change["phase"]` passed `"charter"`, and `change.json` exists. The same steps with `J2_REALIZATION=0` leave the J2_FIXES=0 path unchanged (no Identity change task, no `change.json`).
- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: Implement:** open `self.change` in `user_says` when done and not paused and realization website; in the dispatch, a realization change goes to `("identity", kind="intake", change=..., mark=...)` regardless of `self.fixes`; the realization-only prompt text replaces "keep everything already in it" and names standards and rules. After the charter is stamped, hand off `("relay", kind="relay")` instead of Adaptation.
- [ ] **Step 4: Run** `python relay_test.py && python realization_test.py && python j2_flow_test.py --fast` — Expected: PASS (flow test: all but `artifacts_tab`)
- [ ] **Step 5: Commit** `"Relay: a change in a realization run goes to Identity on the change path"`

### Task 6: Revising a planning file

**Files:** Modify `j2.py` (`_register` ~6003-6010, `_run_artifact` ~6440-6490); Test `relay_test.py`

**Interfaces:**
- Produces: `_register` keeps `revises` for a target whose `outputs` are a planning file (same `outputs`, `section` = the target's id); `_run_artifact` copies the existing file to `<stem>.v<k><ext>` before writing, `k` = number of kept versions + 1.
- Produces: `J2Run._register_doc_revision(node: dict, changes: list[str], reason: str) -> str` — registers the revision workflow (name `"<node name> r<k>"`, `revises` node id, `parts: ["fix"]`, checks from `carry_checks`, steps = the changes), returns its id.

- [ ] **Step 1: Failing test** — mock run to Done; `rid = run._register_doc_revision(plan_node, ["Add a section on X"], "test")`; run the queue: `run._wf(rid)["revises"] == "W-1"`, status done, `artifacts/plan.v1.md` holds the old text, `artifacts/plan.md` is new. Review Focus 3: set `run.budget = run.spent` first → run pauses on the budget question; `F.say(run, "Add 50 work credits and keep going.")` → the revision completes and `run.change["phase"]` is unchanged.
- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** all three test files — Expected: PASS
- [ ] **Step 5: Commit** `"Relay: planning files can be revised; earlier versions are kept"`

### Task 7: The relay walk and agreement

**Files:** Modify `j2.py` (new handoff kind `relay`, method `_relay(h)`; queue-empty hand-off ~where "Queue empty ... Audit checks" is posted); Test `relay_test.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4, 6.
- Produces: `J2Run._relay(h)` — per wave, asks each node's agent (system prompt of that workflow's agent; task: change, `self.change["diff"]`, its file, parent revisions in this change) for a verdict with a `mock()` that reads `self.relay_script.get(node_name, "no-change")`; posts one chat line per verdict with `change=<id>`; registers a revision for each `change-here` and lets Coordination run it; when the queue empties with phase `relay`, asks each direct reader for agreement (mock from `self.relay_script.get(f"{reader}->{node}", "agree")`); an objection re-registers a revision with the reason (max `RELAY_MAX_ROUNDS`), then Identity picks a version (`kind="relay_ruling"`); then the next wave.
- Produces: `J2Run.relay_script: dict` (tests only; empty by default).

- [ ] **Step 1: Failing tests** with a mock plan of three planning workflows (`Spec` product, `Design` design ← Spec, `Arch` engineering ← Spec) and builds depending on them (extend `blocked_mocks`' pattern: override `m["plan"]`):
  - `relay_script={"Design": "change-here"}`: verdict posts in order Spec, then Design and Arch together; one revision of Design, done; `design.v1.md` kept; Spec and Arch not revised; `change.json` node verdicts recorded.
  - `relay_script={"Design": "change-here", "Build A->Design": "object"}`: one objection, a second revision, then agreement; 2 objections in a row → Identity ruling posted, no third revision.
  - malformed verdict (`relay_script={"Spec": "garbage"}`): one retry, then `no-change` and a system post naming Spec.
- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** all three test files — Expected: PASS
- [ ] **Step 5: Commit** `"Relay: the walk through the planning documents, with agreement"`

### Task 8: Affected build sections and the validator rule

**Files:** Modify `j2.py` (after the last wave: affected calls; Adaptation's change task; `_register` validation); Test `relay_test.py`

**Interfaces:**
- Consumes: `build_candidates`, `parse_affected`.
- Produces: `self.change["affected"]: list[{"id", "what"}]`; Adaptation's task gains `CHANGE <id>: revise exactly these sections ... ; add a new section only where a revised document calls for one; a new section lists in dependencies every planning workflow it reads.`
- Produces: `j2_relay.change_problems(proposal: dict, change: dict, planning_names: set[str]) -> list[str]` — the four validator rules from the spec §5; empty when no document changed (Review Focus 1) except the dependencies rule.

- [ ] **Step 1: Failing tests**
  - `change_problems` unit tests: a revision of a section not in `affected` → "not marked affected by the relay"; a new section whose dependencies name no planning workflow → "names no planning document"; a revision citing an Audit finding passes; proposal before relay finished → "the relay has not finished".
  - Mock run, `relay_script={"Design": "change-here", "Build item 2": "affected"}`: Adaptation's task names exactly Build item 2's latest id; the registered build revision revises it; the run ends Done; `change.json` phase `closed`.
  - Review Focus 1: `relay_script={}` (all no-change): `change.json` has `"documents_changed": []`, Adaptation proposes as today, the run ends Done.
- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** all three test files — Expected: PASS
- [ ] **Step 5: Commit** `"Relay: only affected sections are revised; the validator holds the line"`

### Task 9: Records, report and the off switches

**Files:** Modify `j2.py` (`report.json`/`summary.json` writers ~8111-8130; "Finish as it is" handling); Test `relay_test.py`, `j2_flow_test.py`

- [ ] **Step 1: Failing tests**
  - after Task 8's run: `report.json["changes"][0]` has `messages`, `calls`, `credits`, `documents_changed`, `affected`, `post_fixes`.
  - Review Focus 4: change open, Requester answers "Finish as it is" → `change.json` closed `"finished by the Requester"`.
  - `realization_test.py` no-scenario check covers `j2_relay.py` (no stage ids from `stages.json`, no "design"/"spec"/"architecture" literals).
  - `plain_unchanged` (both board variants) and the `J2_REALIZATION=0` run unchanged.
- [ ] **Step 2: Run** — Expected: FAIL on the report keys
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `python relay_test.py && python realization_test.py && python j2_flow_test.py --fast` — Expected: PASS except `artifacts_tab`
- [ ] **Step 5: Commit** `"Relay: per-change records and report"`

### Task 10: Real re-run against the baseline (verification)

- [ ] **Step 1:** start a server on a new port (8787) from `J2_Realization`, `J2_DELAY=0 J2_MEMORY=0 J2_BUDGET=400`; post the same Sudoku brief; finish it.
- [ ] **Step 2:** send A, B, C one at a time after Done, raising the budget when asked; snapshot after each with `snap.py`.
- [ ] **Step 3:** check the spec's Success list item by item: charter diff per case; documents changed per case (A spec/design/copy/architecture, B design, C architecture) with `.v1` files kept; B reaches the race board, A's nav has the race link in the first build, C revises both boards; no build registration before the relay finished (chat order); headless smoke test on the final site.
- [ ] **Step 4:** add a "after" column to the baseline page and publish it; report numbers per change next to the baseline.
- [ ] **Step 5:** commit nothing from `runs/`; push the branch only when the Requester asks.
