# Charter Change Implementation Plan (version 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second prompt on a realization website run is split into intents; the judge decides each intent once,
with confidence (A existing, B one fix, C new workflow, D new stage); planning docs change first; then check, build,
Relay and audit.

**Architecture:** Pure logic and the change planner in a new module `j2_change.py` (no import of `j2`).
`j2_realization.py` gets small backward-compatible options (`items=`, `names=`, `only=`, G0, `placement_task`).
`j2.py` gets one handoff kind `change` that reuses the `_realization_plan` hand-off pattern.

**Tech Stack:** Python 3.14, J2 (`j2.py`, `j2_realization.py`, `llm.ask` with per-call `mock`), `STUDIO_MOCK=1`.

**Spec:** `docs/superpowers/specs/2026-10-30-charter-change-design.md`

## Global Constraints

- Branch `charter-change`, stacked on `identity-atomic-items` (the Identity one-outcome-per-item rule, 94bffd0 +
  47d8ea7), which sits on `origin/main` bdd8602. Do not push `change-relay`.
- Windows: run Python with `PYTHONUTF8=1`. Commit as `fo <fo@testlify.com>` (`git -c user.name=fo -c user.email=fo@testlify.com`).
- Baseline (30 Oct): `python realization_test.py` 76 checks pass. `python j2_flow_test.py --fast` stops at an existing
  assertion about `site/shots/v4.png` records, on main too; run the relevant flow tests by name instead
  (`import j2_flow_test as t; t.<name>()`), and always `plain_unchanged` (3 calls, see `j2_flow_test.py` ~L8926).
- On only for realization website runs with `J2_CHANGE=1`. A run without a change behaves exactly as today; first-plan
  judge scores do not change.
- No stage, document or workflow name in code or prompts (extend `realization_test.py` "no scenario" checks).
- Item ids are charter numbers, never `done_when` positions.
- Every LLM step has a mock and a malformed-reply path; a malformed reply never means "no change".
- `python realization_test.py` and `python change_test.py` pass; `python j2_flow_test.py --fast` has no new failures.
- Never commit `docs/tax-comparison/` or `runs-broken/`.

## Review Focus

1. Richer come-back features: size fails → C straight away; no revise call is made (count calls).
2. Teach techniques: B makes exactly one revise call; on a second failure the intent goes to C, not another round.
3. Daily Challenge: three intents decided independently; merged plan passes `plan_faults(items=)`.
4. Remove save and resume: Save dropped; Technical design revised before Reasons to come back.
5. Revert of a rename diffs to nothing against the last full plan; no judge call.

---

### Task 0: Branch and baseline

- [ ] `git fetch origin && git switch -c charter-change origin/main`
- [ ] Copy spec and plan into `docs/superpowers/`; record existing failures of `j2_flow_test.py --fast` here.
- [ ] Commit "Charter change v2: spec and plan".

### Task 1: Port Relay's graph logic (code)

**Files:** create `j2_change.py`, `change_test.py` (`ok()` style and env setup of `realization_test.py:1-30`).
Source: `J2_Relay/j2_relay.py:13-197`, tests `J2_Relay/relay_test.py:52-133`.

- `planning_nodes(workflows, is_doc)`, `relay_waves(nodes)`, `direct_readers(workflows, root)`,
  `build_candidates(workflows, roots, is_doc)`, `latest(workflows, root)`, `parse_affected(text)`.
  `is_doc` is passed in (j2 passes `is_artifact`) instead of the hard-coded `index.html`.

- [x] Port the Task 1–2 tests (graph, replies) failing → port code → pass → commit.

### Task 2: Intents and owners (code)

- `charter_diff(base, new) -> {"added": [n], "removed": [n], "rules": {"added","removed"}, "standards": {...},
  "goal_changed": bool}` on charter numbers (`charter_items` index + 1, active = text still in `done_when`).
  `goal_changed` = `statement` or `audience` differs.
- `diff_empty(d) -> bool`; `owner_index(workflows) -> {n: wf_id}` (latest revision, dropped excluded).

```python
d = ch.charter_diff(SUDOKU, renamed)          # item 3 text edited
ok(d["removed"] == [3] and d["added"] == [11], "an edit is remove + add")
ok(ch.diff_empty(ch.charter_diff(SUDOKU, reverted)), "a revert diffs to nothing")
ok(ch.charter_diff(SUDOKU, killer)["goal_changed"], "audience change → re-plan")
ok(ch.owner_index(SUDOKU_WFS)[2] == "W-15", "a revision replaces its original as owner")
```
- [x] Failing tests → implement → pass → commit.

### Task 3: The decision rule (code)

- `decide(kind, match, score) -> "A"|"B"|"C"|"D"` with `match = {"owner": name|None, "stage": id|None}`,
  `score = {"score", "weakest_part"}` and `after_fix` for the second look:
  removed → A; no owner and a plan stage → C; no owner, no stage → D; score ≥ 0.80 → A; weakest_part == "size" → C;
  else B; B re-judged ≥ 0.80 → A, else C.
- `PART = {"done_test": "goal", "inputs": "context", "method": "how", "zone_fit": "how", "factors": "constraints",
  "size": "size", "fits": "goal"}` and `weakest_part(settled)`.

- [x] Tests: one per rule row; the four judge-today presets (0.95 → A, 0.77 how → B, 0.70 context → B, 0.62 size →
      C); `after_fix` 0.79 → C. Commit.

### Task 4: Judge for a change (LLM, mock first)

**Files:** `j2_realization.py`, `agents/j2/confidence-judge.md`, `change_test.py`.

- `checklist_task(goal, items=None)`, `checklist_items(r, goal, items=None)`: questions only for `items`
  (charter numbers).
- `question_spec(p, checklist, names=None)` and `Session.judge(..., names=None)`: only the named workflows.
- `CHECKS` gains `fits`; `QUESTIONS` stays; `CHANGE_QUESTIONS = (("G0", "fits", 0.25, "..."),)` added only by the
  change path.
- `match_task(goal, plan, intents)` + `MATCH_FMT = {"intents": [{"item": n, "owner": str|null, "stage": str|null,
  "why": str}]}`: G0 for every workflow in one call, with the stage question when no one owns it. Malformed twice →
  the intent is decided C (placement looks at it); it is never dropped.

- [x] Tests: subset spec has only named workflows; first-plan spec keys and scores unchanged (Sudoku fixture
      snapshot); mock match gives owner/stage; G0 "no" caps the score. Commit.
- Note: `confidence-judge.md` is left unchanged so the first-plan judge system prompt stays byte-identical; G0 is
  explained in `judge_task`'s CHANGE note. Phase A follow-ups folded in: `weakest_part(settled, spec)` sums by part;
  `owner_index` skips revisions with empty covers.

### Task 5: Act — A, B, C/D (LLM, mock first)

- A: `edit_task(goal, plan, owner, intents)` — scoped revise; workflow with empty delivers and informs is dropped.
- B: `revise_task(goal, web, plan, low, extra, only=[owner])`, one round, then `Session.judge(names=[owner])`.
- C/D: `placement_task(goal, plan, items)` + `PLACE_FMT` (new factors, new stages, new workflows, certainty for the
  new items). Stage ids from `stages.json`; a new stage must hold a planning (decide) workflow, and every new
  workflow lists its stage's planning workflow in `inputs_from`. Merge, `plan_faults(merged, goal, items=active)`,
  one retry with faults named.

- [ ] Tests: A remove drops Save; B makes one revise call and then routes C on failure; placement of "Share result"
      adds stage `growth` with a planning workflow; unknown stage `social` → retry. Commit.

### Task 6: plan_change orchestrator (steps 2–6)

- `plan_change(base_goal, new_goal, plan, workflows, mocks=None, log=print, out_dir=None) -> record`
  `record = {"diff", "intents": [{"item", "kind", "owner", "decision", "score", "why"}], "plan", "revise": [...],
  "new": [...], "drop": [...], "docs": [...], "replan": bool, "calls", "seconds"}`.
- docs = planning workflows in `inputs_from` of revised or new workflows, plus new stages' planning workflows.
- Check: judge changed + new; `plan_faults`; failure after one retry → `replan=True`.

- [ ] Tests: the 11 Sudoku prompts as scripted mock scenarios; assert decision per intent, `docs`, `replan` and call
      counts (A intent ≤ 3 calls; size → C makes no revise call). Commit.

### Task 7: Into the run

**Files:** `j2.py`.

- [ ] `_change_applies()`: `J2_CHANGE=1`, realization website run, `realization.json` present, `self.feedback`.
- [ ] After `_identity_intake` saves the new charter: keep `goal.v<k>.json`; no diff → no plan change; `goal_changed`
      → full re-plan (`_realization_applies` allowed once); else handoff `change` → `_turn_change(h)` calls
      `plan_change`, saves `change.json`, posts a one-line summary, and hands Adaptation fixed text (doc revisions
      first, then `revises` and new workflows), like `_realization_plan` :5421.
- [ ] Validator while a change is open: a workflow not in the change plan is refused.
- [ ] Mock run: "Rename the levels" registers the Product plan revision before the Levels revision, nothing else.
- [ ] Commit.

### Task 8: Relay from revised docs

- [ ] After a doc revision is built: `direct_readers` not already in the change plan → one "affected? what?" call
      each; affected → revision registered; walk in `relay_waves` order; stop at "no"; unreadable after one retry →
      affected.
- [ ] Tests: How to play reached through Product plan; garbled reply → revised; "no" stops the walk. Commit.

### Task 9: Record, docs and real runs

- [ ] `change.json` (append-only) and a "Changes" section in `report.md`.
- [ ] Publish the framework on the Adaptation page of the native docs (location to confirm).
- [ ] Real Sudoku run, then the 11 prompts one at a time with `J2_CHANGE=1`; record decision, docs, workflows,
      calls, credits and minutes per prompt in `docs/charter-change-results.md`. Turn `J2_CHANGE` on by default only
      if the routes match or each difference is explained.
