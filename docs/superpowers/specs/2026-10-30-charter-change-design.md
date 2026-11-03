# Charter change: decide each intent once, with confidence

Framework (version 2, after the 30 Oct call): https://claude.ai/artifact/3raCPuYmm41ysVMBrqxLxW
Base: `origin/main` at `bdd8602`. Relay logic to port from: branch `change-relay` (J2_Relay, `ed1173a`).

## Intent

A second prompt becomes a change in the charter, split into single intents. For each intent the judge decides the
treatment once, with a confidence, and code acts on the confident answer: use the existing workflow (A), make one
small fix (B), add a workflow in an existing stage (C), or add a stage from the catalogue (D). Every route ends the
same way: planning docs first, check, build, Relay, audit.

## Inputs from the 30 Oct call (Sankalp)

1. Break a combined prompt into individual intents and treat each one separately.
2. Decide by confidence: act on the most confident treatment (≥ 0.80). Do not try the existing workflow, improve it
   three times and only then go new. If nothing is confident, take the next most confident, cheap step: one small fix.
3. Judge the size at step 3, not after failed rounds.
4. Simple: reuse what exists; add nothing new without need.
5. Structure the judge's questions (by work-atom part), then simplify.
6. Publish the framework on the Adaptation page of the native documentation.

## Goals

1. Each intent gets exactly one decision at step 3; at most one small-fix try before C.
2. Realization and certainty run only for C, D and a full re-plan. The rest of the plan is kept.
3. Planning docs are revised before any build that reads them; Relay walks workflow → artifact → workflow and stops
   where nothing changes.
4. After the change every item has exactly one owner (R1, R2 on the merged plan).
5. A run without a change request behaves exactly as today. First-plan judge scores are unchanged.

## Success (Sudoku re-runs)

| Prompt | Expected |
|---|---|
| Rename the levels | A on Levels and new game; Product plan first |
| Add dark mode | A on Look and layout; Style guide, Technical design first |
| Teach techniques in hints | B on Hint (edit, one improvement) |
| Remove save and resume | A remove; Save dropped; Technical design re-homes storage first |
| Richer come-back features | C directly (size), 2–3 new build workflows, no improve rounds |
| Import a newspaper puzzle | C + A |
| Daily Challenge | A, C, D (growth) |
| Learn mode | D (learning), D, A |
| Online races | Identity asks |
| Ship by tonight | no plan change |
| Make it Killer Sudoku | full re-plan |

Judge-and-plan calls for one A intent: at most 3 (match, edit with its docs list, judge). For one B intent: 5. For one C intent: at most 5.

## Non-goals (deferred, one at a time later)

Mid-run prompts, freeze check of old workflows, a separate constraints question,
asking only readers of the changed section, growing the catalogue, the style guide's two owners, document runs.

## What exists (deep dive, origin/main bdd8602)

| Need | Exists | Reuse |
|---|---|---|
| Charter update after done | `user_says` j2.py:3285 sets `feedback`; `_identity_intake` :3874 (with `J2_FIXES=1`) returns an updated charter | as-is |
| Stable item numbers | `charter_items` append-only (:4013-4017); `covers` holds charter numbers; `covers_text` | as-is |
| Item → owner | forward `covers` only | small new function |
| Charter diff | `j2_relay.charter_diff` (positional) on change-relay | port, re-key on charter numbers |
| Judge | `QUESTIONS`, `question_spec` :320, `judge_task` :540, `settle` :373, `Session.judge` :602 | extend: `names=`, `items=`, G0 |
| Small fix | `revise_task` :519, `REVISE_FMT` axes, compare | extend: `only=`, one round |
| New workflow / stage | `plan_task` :512, `PLAN_FMT`, `stage_table`, `certainty_zone` :77 | new `placement_task` (variant of plan_task) |
| Merged-plan rules | `plan_faults` :149 (R1–R4, R6, R2 single delivery, unknown stage, cycle, certainty) | extend: `items=` |
| Hand-off to the run | `_realization_plan` :5421 text to Adaptation; `revises` re-runs a builder (:6191) | same pattern |
| Relay graph | `j2_relay.py` waves, readers, `build_candidates`, `parse_affected` | port |
| Build, audit | Coordination by `dependencies`; full audit | as-is |

Realization positions: `plan_faults` and `checklist_items` count `done_when` positions. On the first plan positions
equal charter numbers. The change path passes charter numbers (`items=`) instead.

## How it works

### Step 1. Identity (no new format)

- The change goes through `_identity_intake` as today (`J2_FIXES` path) and returns the updated charter. Identity
  asks the Requester first when the prompt is unclear or breaks a rule.
- Code rules after the charter comes back: no item, rule or standard changed → no plan change. `statement` or
  `audience` changed → full re-plan.

### Step 2. Intents (code)

- `charter_diff(base, new)` on charter numbers: `added` (new numbers), `removed` (numbers no longer in `done_when`),
  `rules`, `standards`. An edit is a removed number plus an added number. A revert reuses the old number, so it diffs
  to nothing against the base.
- `base` = the charter of the last full plan (`goal.v<k>.json` kept on every change).
- `owner_index(workflows)` → item → owner (latest revision, by `covers`).

### Step 3. Judge decides (LLM answers, code decides)

- Questions grouped by work-atom part (a label over the existing checks; weights unchanged):
  goal = G0 (new, change only) + D1–D4 + K; context = I1, I2; how = M1, M2, Z1; constraints = F; size = S1, S2.
- Step 3 is one call (match): for each added intent, G0 "is this intent this workflow's job?" asked of every
  workflow; for the owner, `too_big` (would taking it on make the owner exceed one kind of thinking or one builder's
  run); when no workflow says yes, "which stage, from the full stage table, must decide how this item works?" (teaching
  → learning, sharing → growth, what to measure → data; a making stage such as build only when the plan's planning
  documents already decide everything and only making is left). Code derives whether that stage is in the plan.
  Removed intents skip it. The owner is not scored before it is edited (live test, 30 Oct: an unedited owner fails its new item's K and
  context questions, so nearly everything went to B).
- `decide(intent, match, score, after_fix)` (code):
  - removed → A
  - no owner: the deciding stage is in the plan → C, else → D (with that stage id; live test, 30 Oct: asking for
    "the stage in the plan" always gave build, so D was never chosen)
  - owner and too_big → C
  - owner that fits → edit it (step 4), then judge the edited owner: ≥ 0.80 → A; weakest part = size → C; else B: one
    improvement given the judge's missing notes, judge again: ≥ 0.80 → B (improved and passed), else → C
- A reply (edit, improvement or judge) that lacks the expected workflow sends the intent to C with a note.
- The border second look (±0.05) stays as today.

### Step 4. Act

- Edit (A and B): one call returning only the owner, modified, extended or reduced, plus the planning docs to revise
  first. A workflow left delivering nothing is dropped. B adds one improvement call returning only the owner; if the
  intent ends in C, the owner keeps its old version (less any removed item).
- C, D: `placement_task(goal, plan, items, routes)` with the current plan as context, told each item's route: a C item
  goes in a stage of the plan, a D item in a new stage from `stages.json` with its own planning workflow
  (`placement_faults` enforces both). Each new workflow has stage, certainty zone, delivers, inputs_from naming its
  stage's planning workflow. Realization and certainty run here only.

### Step 5. Planning docs first

The planning workflows to revise = those that a changed or new workflow lists in `inputs_from`, plus the new stage's
planning workflow. Their revisions come first; build revisions depend on them.

### Step 6. Check

Changed owners were judged at step 4. Judge the new workflows (≥ 0.80); those below get one repair call for those
workflows only, given the judge's missing notes, then a second judgement. Then `plan_faults(merged, goal,
items=active)`; a placement is sent back once with its faults named. A new workflow still below 0.80 after its
repair is held as not ready, as on a first plan: it and the workflows behind it are left out of the change plan, their
items are listed as left out with the judge's notes (Adaptation gets them in `left_out`, the Requester is told in plain
words), and the rest of the change goes ahead. Only plan rule faults the retry did not fix mean a full re-plan.

### Step 7–9

Adaptation gets the change plan as fixed text (like `_realization_plan`): doc revisions, then revisions (`revises`)
and new workflows. After each doc revision is built, Relay asks its readers that the change plan did not already
revise whether they agree with it and whether their own output is affected (what must change), once each, stops at
"not affected", and treats an unreadable reply as agreed and affected. Audit runs as today.
`change.json` records intents, decisions, docs, workflows, calls and credits.

Relay agreement (3 Nov, ported from branch `change-relay`, Relay v1): a reader that objects sends the doc back for one
more revision registered by code, with the objections as its task, at most 2 rounds; its readers answer again on the
new version. Still objected to, Identity keeps the latest version or the previous one (the file each doc revision
overwrites is kept as `<name>.v<k>.<ext>`). Affected readers are revised only once the doc has settled. Revisions
registered by Relay carry their predecessor's checks without the charter strings the change removed (`gone` in
`change.json`), and a planning doc's revision must keep every heading the old file had. `change.json` adds
`objections`, `rulings` and `gone`. Relay v1's per-document verdicts are not ported: the change planner already
chooses the docs to revise.

### Switch

Only for realization website runs with `J2_CHANGE=1` (default 0 until the Sudoku re-runs match). Otherwise today's
path.

## Decisions taken (confirm with Sankalp)

- D1 "Next most confident" when nothing is confident = one small fix (B), the cheapest step that can prove itself.
- D2 An edit is remove + add; Identity's reply format does not change.
- D3 G0 is asked only on a change; the five-part grouping is a label, so first-plan scores do not move.
- D4 Prompts during a run are still refused (409) in this version.

## Left to the builder

Prompt wording, mock scripts, file name of kept charters.
