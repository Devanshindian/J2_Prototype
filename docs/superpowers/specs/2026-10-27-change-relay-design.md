# Change relay: every change goes through the planning chain

Status: draft for approval, 27 Oct 2026. Branch `realization-axis`.
Baseline it answers: run `runs/j2-20261027-142038`, report https://claude.ai/artifact/92kuh5Ub3XYpYyRUXydKhF

## Intent

When a J2 product changes, the change must go through the same planning chain that built it, the way a company
would: the charter first, then whichever planning document the change belongs to, agreed with the people who read
that document, then only the build sections that are affected. The founder's model (standup, 27 Oct): a change
always enters at the charter, the signal travels down the chain, each node either passes it on ("no change for
me") or says "the change starts here", and from there everything downstream follows. "That is the entire point
of realization." First make it work; optimise later.

Why now: the baseline showed that today every change skips the chain. Three change requests (add two-player, dark
theme, faster grid) were all built and the site works, but:

- the charter was never updated (`goal.json` still has the original 8 items and the "Warm, friendly" standard);
- no planning document was revised; build sections were revised (`revises: W-5`, `W-6`, `W-11`, `W-14`), so
  `design.md` still says warm cream and three nav links and `architecture.md` describes the old render;
- each revision reached one consumer only: the dark theme missed the race board (Audit found it, W-17), the nav
  missed the race section (W-15), the render fix missed the race board's own render.

## Goals

1. Every change request enters at the charter: Identity updates it (done-when items, standards and rules),
   keeping existing item numbers.
2. A relay walks the run's own planning chain in dependency order; each planning workflow's agent gives a verdict
   on its own document: `no-change` or `change-here` with what changes.
3. A `change-here` node revises its own document as a new version (the old one kept), and the workflows that read
   it agree or object before the revision counts.
4. Every built site section that depends on a revised document says whether it is affected; only affected
   sections are revised, and a new section is added only where a revised document calls for one.
5. Works for any plan: no stage, document or workflow name is written in code.

## Success (what the re-run must show)

Re-run the same Sudoku brief and the same three change requests, each sent after the run is done:

- all three built, and the old features still work (the baseline's headless Chrome smoke test);
- the charter carries each change (A: a new item; B: the look standard edited; C: a new checkable item);
- each change appears in the planning documents it belongs to (A: spec, design, copy, architecture; B: design;
  C: architecture), with the previous versions kept;
- B reaches every section that styles the page, including the race board; A's nav includes the race section
  without a later fix; C reaches both boards;
- no build workflow for the change is registered before the relay finishes;
- messages, calls and credits per change reported next to the baseline (messages A 43, B 31, C 18; credits A 81,
  B 59, C 40). Fewer is the founder's north star, but this round passes on correctness, not cost.

## Non-goals

- Deciding that a check is a false alarm (the Requester asked to leave it out for now).
- Audit findings during a run's first build: they keep today's fix path.
- Changing a run with no change request: the first build behaves exactly as today.
- Runs with `J2_REALIZATION=0`, document output types (PRD/HLD/LLD) and blueprint builds: unchanged.
- Starting a change lower down to save calls (the founder's later optimisation).
- Workflow-to-workflow messaging (Kaivan) and templates (Tishanth): the relay posts to the existing chat, which the
  board shows when `J2_BOARD=1`; it does not turn the board on.

## Anti-goals (a failure even if the site works)

- A planning document or charter standard that no longer describes the product.
- Code changed for a reason no document records.
- A section that depends on a changed document and was never asked.
- Any list of stage, document or workflow names in code.

## Constraints

- Only for realization runs (`J2_REALIZATION` on, website output), and only while a change is open.
- Base J2's prompts stay identical (`plain_unchanged` passes, both board variants); `j2_flow_test.py` and
  `realization_test.py` pass apart from the known `artifacts_tab` failure in `--fast` mode.
- Reuse what exists: J2.a's change path for the charter (`j2.py` ~3748, today only with `J2_FIXES=1`);
  `revises: "W-n"` and section ownership for build revisions (`j2.py` ~6003); `_run_artifact` for writing a
  planning file (`j2.py` ~6440); the existing budget question when credits run short.

## Approaches considered

1. **Relay, each owner decides (picked).** Code walks the chain; each planning workflow's agent judges only its
   own document. Matches the founder's model, takes the decision away from Adaptation (which took the shortcut in
   all three baseline cases), and every verdict is visible. Cost: one small call per planning document.
2. Adaptation maps the impact in one call. Cheaper, but the agent that shortcut today grades its own work and no
   node decides for itself. A later optimisation once 1 works.
3. Code derives the impact from charter `covers`. Free, but fails case C (a speed problem changes no charter
   item) and new features have no `covers` yet. Dropped.

## How it works (decided)

### 1. Entry

A Requester message after the run is done opens a change (today's change request). Messages during a run stay
refused, as today. The entry is one function, so another function can open a change later (the founder's
"another agent says the architecture won't scale"); in this round only the Requester does.

A change stays open from the message until the Audit after its build is accepted or the Requester finishes it.

### 2. Charter

Identity handles the change at J2.a through the existing change path, now on for change requests in realization
runs whatever `J2_FIXES` says. The change prompt changes from "keep everything already in it" to "keep everything
the change does not contradict; edit or remove what it contradicts", and it covers `standards` and `rules` as
well as done-when items. Numbers are kept (positions already map to numbers). When an item's text is edited,
code updates the stored `covers_text` of every workflow that covers that number, so coverage is not lost.

A change about how the product performs (case C) gets a checkable done-when item, e.g. "Tapping a cell updates the
board with no visible delay on a low-end phone".

`change.json` records the charter diff: items added, edited and removed, standards and rules edited.

### 3. The relay through the planning documents

- **Nodes:** the run's file workflows (an output other than the site file), from `workflows.json`, latest
  revision of each. **Edges:** `dependencies` between them.
- **Order:** dependency order. A node is asked once all its planning parents have answered; nodes ready at the same
  time are asked together.
- **Every node is asked**, even when its parents said `no-change` (case C: spec, design, copy say no change,
  architecture says change here).
- **The verdict call:** that workflow's own agent gets the change, the charter diff, its current file, and the
  revisions its parents made in this change. It returns JSON, checked by code:
  `{"verdict": "no-change" | "change-here", "reason": str, "changes": [str]}`, `changes` non-empty exactly when
  the verdict is `change-here`. One retry on a malformed reply, then `no-change` with a system note.
- **The revision:** code registers it directly from the verdict, with no Adaptation proposal: a new workflow id
  with `revises` set to the node's id, the same output path, and `dependencies` copied. Today `revises` only
  works for site sections; it is extended to file workflows. It is priced as one `fix` part from the rate card
  and charged like any workflow; a short budget pauses on the existing budget question. Before the file is
  rewritten, the current one is kept as `<name>.v<k>.<ext>` beside it.
- **The revision's checks:** its predecessor's checks, with any facts-present text that came from a charter
  string the change edited or removed replaced by the new charter string or dropped; plus a heading/section check
  that the file still has every heading it had before. The verdict's `changes` sentences are given to the builder
  as the task, not used as check strings.
- **Agreement:** every workflow that depends on the node directly, planning or build, answers on the revised file
  in one call: `{"agree": bool, "reason": str, "affected": bool, "what": str}` (`affected` and `what` only for
  build sections). An objection goes back to the owner with the reason as one more revision; at most 2 rounds.
  After that Identity chooses between the owner's latest version and the version before it, or asks the
  Requester; Identity writes no text itself.
- **Messages:** every verdict, revision and agreement is one short chat post carrying the change id, so the board
  (when on), the map and the debugger can show where the change entered.

### 4. The build

- **Who is asked:** every built site section whose dependency chain reaches a revised planning file, directly or
  through other sections, answers `{"affected": bool, "what": str}`. A section already asked in the agreement step
  is not asked again. (Through the chain, not only directly: in A the nav section W-11 reads the design guide only
  through W-10, and missing it is how the baseline needed W-15.)
- **Adaptation proposes the build work, bound by the relay result:** one revision (`revises: W-n`) per affected
  section with the relay's `what` in its goal, plus a new section only where a revised planning file calls for
  one (A: the race board). Priority prices it and Coordination runs it, as today.
- **New sections** must list in `dependencies` every planning workflow whose file they read.
- **Then Audit**, as today. Fixes for Audit findings after the change's build go through today's fix path and are
  exempt from the validator rule below; `change.json` records them as post-build fixes, so the re-run shows how
  many the relay failed to prevent.

### 5. Validator rule

While a change is open, before its build is accepted, the validator rejects:

- a build workflow registered before the relay finished;
- a revision of a section the relay did not mark affected (unless it fixes an Audit finding);
- a new section that no revised planning file calls for;
- a new section whose `dependencies` name no planning workflow.

### 6. Records

`change.json` per run: one entry per change with the request, the charter diff, each node's verdict and reason,
each revision (workflow id, from/to version file), each agreement and objection, the affected sections, the
post-build fixes, and messages, calls and credits for the change. `report.json` gains the same totals.

## Left to the builder

Prompt wording for the verdict, agreement and affected calls; how parallel answers are run; where the relay code
lives (a new module is fine); the exact message text; how a "calls for a new section" is read from a revised
planning file (e.g. a named section in the architecture's section table).

## Calls made by me, to check while reading

- Case C adds a charter item rather than passing a note.
- Identity may edit or remove charter standards and rules a change contradicts.
- Planning revisions are registered by code from the verdict and priced as one `fix` part; relay verdict and
  agreement calls cost calls, not credits.
- Build sections that read a document directly take part in its agreement, and answer `affected` in the same call.
- Affected-asking follows the dependency chain through sections, so most built sections are asked on most changes.
- Audit findings after the change's build keep today's fix path, recorded as post-build fixes.
- Objections cap at 2 rounds, then Identity picks a version or asks the Requester.
- A malformed verdict falls back to `no-change` after one retry.

## Decided by the Requester

- Changes during a run are out of this round; all three cases are sent after the run is done.
- The false-alarm case is out of this round.
- Approach 1, the relay.
- Every change enters at the charter (the founder's call on 27 Oct).
