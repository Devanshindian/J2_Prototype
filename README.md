# Agent Studio: three agents and a user build a website together

Product, Design and Development share one group chat with the user. Tell them what
you want ("I want a hospital website") and they ask questions, plan, get your
approval, build, review each other's work, and take change requests.

## Run

```bash
pip install -r requirements.txt
# Paste your key into .env (GEMINI_API_KEY= or ANTHROPIC_API_KEY=), or export it in the shell.
python server.py                  # opens http://127.0.0.1:8770
```

No key? `STUDIO_MOCK=1 python server.py` runs scripted agents. Add `STUDIO_MOCK_DELAY=4` to make each
mock reply stream over 4 seconds, so you can see the progress UI. The mock is written
for the hospital demo; real mode handles any kind of website.
If both keys are set, Claude is used. Claude defaults to `claude-sonnet-4-5`
(override with `ANTHROPIC_MODEL`); Gemini tries `gemini-3.8-flash`, then `gemini-3.5-flash` if busy (override
with `GEMINI_MODEL`, a comma-separated list). On Gemini's free tier, Google may use prompts to improve its
products, so don't send real customer data through a free key.

## The agents

| Agent | Job | Output |
|---|---|---|
| Product | Talks to the user, writes the brief, **decides who speaks next** | Brief (JSON), routing |
| Design | Turns the brief into a spec; reviews every built version | Palette, fonts, sections; review with issues |
| Development | Builds the site as one HTML file; applies fixes and user changes | `site/vN.html` |
| User | Answers questions, approves the plan, asks for changes | |

## How they communicate

- **One shared chat.** Every agent reads the full conversation plus the current
  brief, design spec and latest site, so nobody works without context.
- **Product moderates.** After each message Product picks the next speaker
  (`user`, `design`, `development` or `done`). Agents never talk over each other.
- **Design and Development talk directly.** Either can ask the other one question when blocked
  ("@Design, menu as tabs or one list?"); the answer goes straight back, with no Product hand-off.
  At most 2 questions per user message. Development can push back on a review issue in its
  message, and Design's next review accepts the reason or insists with one.
- **Fixed hand-offs skip the model.** When only one next step makes sense (spec → plan to
  the user, build → Design review, review → fix or deliver), code posts Product's message
  and routes it. Product's model is only asked after the user speaks. This cuts a full run
  from about 19 calls to 12 (mock run, hospital demo); the spec check adds 1, and each
  teammate question adds 2. Those messages are tagged
  "routed without an AI call" in the chat.
- **Messages use @names** (`@Design, please review v1`) so the chat reads like a real team.

## The flow

1. User gives a brief → Product asks 2-3 questions
2. Product writes the brief → Design proposes a spec → Development checks it can be built
   (once per project; if not, Design revises)
3. Product shows the plan → **user approves** (or asks for changes, which go back to Design)
4. Development builds v1 → Design reviews it
5. Issues? Development fixes (or pushes back with a reason) → Design reviews again (max 2 rounds)
6. Product delivers → user asks for changes or says done

## Guardrails (enforced in code, not left to the model)

- No building before the user approves the plan.
- At most 24 agent turns per run and 2 Design ↔ Development fix rounds.
- The user can't type while an agent is working, so turns never collide.

## Seeing what the agents are doing

- A step tracker under the header: Questions → Brief → Design → Approval → Build → Review → Delivered.
- Under the chat, the working agent's task, seconds elapsed, and reply size so far. For Development
  it also shows the section being written, and for edits a bar comparing size with the previous version.
- The preview shows the page as Development streams it, refreshed every 2.5 seconds.
- Retries and model switches (for example "gemini-3.8-flash is busy (503), trying the next option")
  appear in the status line and are no longer silent.

## Speed settings

- Replies are streamed, so progress is visible and long Development replies don't block.
- Product and Design use a small Gemini thinking budget (512 tokens); Development keeps full thinking.
- On a 503 or 429, the next model in `GEMINI_MODEL` is tried at once; one 4 s pause, then one more
  round, then the error is shown.

## Files

- `agents/*.md`: each agent's rules (`team.md` is shared by all). Edit these to change behaviour; changes apply on the next message, no restart
- `studio.py`: the three agents, their reply formats, the moderator loop and the gates
- `server.py`: local web server and API (`/api/state`, `/api/say`, `/api/reset`, `/site/vN`, `/site/live`)
- `ui.html`: group chat on the left; Preview, Brief, Design and Code tabs on the right
- `mock_site.py`: scripted site used only in mock mode
- `projects/<timestamp>/`: `transcript.jsonl`, `brief.json`, `design.json`, `site/v1.html…`

## Known limits

- Gemini free tier allows 20 requests per day per model (seen on 2026-09-29). A full
  run takes about 6-12 calls, so expect roughly one site a day on a free key.

- Tested end to end in mock mode only. With a real key, a very large site can hit
  the 16k-token output limit for Development.
- One project at a time; no login; the site is a single HTML file.

## Conflict demo: budget negotiation with a CEO

`python negotiate.py` runs a separate, terminal-only demo. Marketing, Engineering and Sales split a
$10,000 launch budget. Each has a private minimum, and the minimums add up to more than the budget, so they
have to argue. Nothing is scripted: each turn the speaking agent reads the whole chat and decides to
propose a split, accept, reject, or escalate, and who speaks next.

- They settle it themselves if all three accept the same split.
- Escalation to the CEO unlocks after 6 turns; after 10 turns without agreement the CEO is called anyway.
- The CEO picks a middle ground with conditions. Each agent accepts with a plan or objects once;
  objections get one final ruling from the CEO.
- Code enforces only the limits: splits must add up, no early escalation, the turn cap.

**Live web page:** `python negotiate_server.py` opens http://127.0.0.1:8771. Press Start to watch the chat,
the split on the table against each department's private minimum, the CEO's reserve, and the final decision.
Offline preview: `STUDIO_MOCK=1 STUDIO_MOCK_DELAY=1 python negotiate_server.py`.

Edit `scenarios/budget.json` (goal, budget, roles, private goals, limits) or `scenarios/rules.md`, or pass
another scenario: `python negotiate.py scenarios/mine.json`. Output goes to `runs/<timestamp>/`
(`transcript.jsonl`, `summary.md`). A run takes about 10-16 short model calls. `STUDIO_MOCK=1` uses simple
rule-based agents for an offline check. Live runs pause 4 s between calls to stay under the free tier's
per-minute limit (`NEGOTIATE_DELAY=3` to change it).

## J2 mode: J2 agents build a website or documents in a group chat (test of J2, no Sutra)

```bash
source .venv/bin/activate
STUDIO_PROVIDER=claude-cli python j2_server.py   # opens http://127.0.0.1:8773, runs on your Claude subscription
python j2_server.py                              # same page, uses the API keys in .env instead
STUDIO_MOCK=1 python j2_server.py                # offline demo, scripted agents
```

**Two pages, one server.**
- `/` is the new page (`ui/`, built on the v2 API in `j2_v2.py`, contract in `j2-revamp/api-contract.md`). You write
  what you want in one box. Then the screen is the kingdom view: a live map of the team at work (the castle is you,
  round tokens are the team, tiles are the parts filling up as they are built, lights travel for hand-offs). A
  question rises as one decision card; tap anything for a bubble; hold and slide for labels and controls (Skip, Redo,
  Note); Pause, Resume and Stop at the top (`/api/v2/control`). The conversation (your messages, the team's one voice,
  and the agents' own talk in plain words) is one icon away. See `j2-revamp/HANDOFF.md`.
- `/legacy` is the older page (`j2_ui.html`): the Simple view, the Detailed view, the Map and the Internals tabs
  described further down. Its routes (`/api/state`, `/api/say`, `/api/output`, ...) still work.

**What gets made.** There are no output buttons. You just write what you want ("a website for my physio clinic",
"a PRD and then the site", "the design docs"). A separate AI reader (`agents/j2/output-classifier.md`) reads your
first message and returns what to make (website, PRD, HLD, LLD, in that order), any sends, and whether it is sure.
Sure: the team goes ahead and the proposal names it. Not sure: one confirm question ("A PRD and a website, right?")
with your answer one click away, or type what you want. Nothing is picked by keyword matching. `/api/output` still
lets the legacy page and tests pick explicitly (`{"type": "prd"}` or `{"stages": ["prd", "website"]}`).

**The proposal.** After the charter, you approve a plan before anything is built: what will be made, its parts and
the estimated usage. Approve sets the budget to the estimate plus a margin (`J2_MARGIN_PCT`, 15%). "Make it smaller"
trims optional parts (never a must-keep item). "Not this" sends your words back to intake. `J2_TOKEN_BUDGET` skips
the proposal with a fixed budget (a developer override, used by the tests).

**Usage, not credits.** The budget is real usage in tokens, measured on every model call (managers, builders, the
work-order review, AI checks, planning, the chat summary, the reviewer). `calls.jsonl` has each call's full usage and
its phase (planning, building, checking, other). Estimates come from past runs (`j2_usage.py`). There is no price
list and no rate card. When usage reaches the margin line, code pauses between turns and you decide: keep going (with
an amount), leave items out, or finish as it is.

You type as the Requester. The flow follows `docs/j2-flow.jpg` and the J2 page (J2.a to J2.h). Only Identity talks to
you.

| Participant | File | Job |
|---|---|---|
| Identity | `agents/j2/identity.md` (official) | J2.a: asks until it has enough, records the charter; J2.d: resolves conflicts; J2.h: is it workable? |
| Adaptation | `adaptation.md` (official, plus the planning part) | J2.b: plans by stage and certainty, proposes workflows, reads lessons; disputes a finding or a HOLD |
| Priority | `priority.md` (official) | J2.c: GRANT / COUNTER / REFUSE token shares; checks usage is free before a run; one top-up |
| Coordination | `coordination.md` (official) | J2.f: orders the ready work into batches |
| Audit | `audit.md` (official) | J2.g: files PASS / NEEDS_REVISION findings against the done-when list, all to Identity |
| W-1 Builder, W-2 Builder, ... | `builder.md` | One agent per registered workflow; writes only its own section |
| Validator | code in `j2.py` + `work-order-review.md` | J2.e: code's free checks, then one AI review per batch; creates the workflow's agent |
| Judges | `confidence-judge.md`, `check-judge.md`, `condition-double-check.md` | Score the plan; answer AI checks; double-check a condition that may be a false alarm |

`team.md` and `builder.md` are ours and describe the current flow; the five function files are the official ones
and are never edited by this code.

### The loop

1. **J2.a** Identity asks as many rounds as it needs, as one facts decision (a form with one field per question).
   It works out the business type and what its visitors need, and asks you to confirm. A fact only you know that
   you can't give yet is **to be confirmed**; that item isn't met.
2. **The proposal**, then **J2.b**. With realization on (`J2_REALIZATION`, default on), Adaptation plans by stage
   and certainty (`j2_realization.py`): factors, stages from the stage guide (`agents/j2/stages.json`: each stage
   says what it covers, what it isn't for, what usually feeds it, an example workflow and an example done-test),
   then workflows. A separate judge scores every workflow; below 0.80 Adaptation revises, up to three rounds. A
   workflow still not ready becomes one decision: add information, try anyway (built and marked at risk) or skip it
   (its items leave the checklist). Each question has its own record (`realization-questions.json`). With tools on
   (`J2_TOOLS`), the planner may search the web and read public GitHub repositories, and may plan research
   workflows.
3. **J2.c** Priority grants each workflow a token share. The bargain is bounded by four hops, fifteen minutes and its
   spend (`J2_BARGAIN_CALLS`); past any bound, both positions go to Identity (J2.d).
4. **J2.e** The validator registers each agreed workflow:
   - Code's free checks first: required fields, the work-atom rules, a usage estimate, nothing Priority refused, it
     covers an item or fixes a finding, in a document only that document's sections, and every dependency names a
     workflow of this run or of the batch (by id, name or "W-2 Name"), with no loops. Dependencies are stored as
     W-ids (`depends_on`).
   - Then one AI work-order review for the whole batch (`work-order-review.md`): does it build (not check or
     report), is its goal specific, do its tests prove its items, are its steps enough, is it one output. A "no" is
     the rejection reason, sent back to Adaptation.
   - An essential rejection (a must-keep item, or work others depend on) registers nothing of the batch and sends it
     back once; the second time you decide (add information, leave it out, stop).
   - Checks are code checks (file, element, count, facts, named tests, behaviour steps) plus optional AI checks
     (`ai-judge`: a yes/no question with a concrete pass line, judged on the section, the page or a screenshot by
     `check-judge.md`; receipts say `"by": "ai"`). An atom always keeps at least one code check.
5. **J2.f** Coordination orders the ready work. **Code enforces the order**: a workflow whose dependencies aren't
   done is held whatever the reply says; one waiting on a failed workflow goes to Adaptation once, then to you (try
   again, skip, stop). A fix that redoes the failed workflow releases the wait.
   - **Style first:** before any section, the first workflow writes the style as its own step. A website gets a
     style guide (palette, fonts, spacing, buttons, cards and motion: entrance, timing, easing, hover, scroll and a
     reduced-motion rule), turned into CSS variables (`--j2-primary`, `--j2-duration`, ...) and classes (`j2-btn`,
     `j2-card`, `j2-reveal`, `j2-hover`), saved as `style.json` (`kind: site`). A document chain gets one house
     style (tone, voice, reading level, heading format, id formats, terms, words to avoid), written once and kept
     for the HLD and LLD, saved as `doc-style.json` (`kind: doc`).
   - **Parallel builders:** independent ready workflows with their own sections build at the same time
     (`J2_PARALLEL`, default 3), each writing only its own section. Code assembles the page once per batch and runs
     every check on the whole page after the batch. A workflow whose checks fail carries on alone; the others keep
     their result. Mock runs pass the calls through an ordered gate, so ids and messages are the same every run.
   - **Neighbours:** a builder sees the full text of the sections next to its own and of what it depends on, plus a
     short list of the rest (`J2_NEIGHBOURS=0`: the list only; `J2_SLIM=0`: the whole page, the old path).
   - **One limit:** a token share plus a leeway (`J2_LEEWAY_PCT`, 25%). A builder keeps working until its checks
     pass or the share plus leeway is used; then Priority is asked once about a top-up. `MAX_CHECK_ATTEMPTS` (5)
     bounds quality attempts, not cost.
   - **Research:** a research workflow may search the web and read GitHub (read only), learns from examples without
     copying, and writes entry `R-n` in `research.md` with at least three cited sources. The workflows that depend on
     it get that entry in their prompt.
   - **Polish:** when every builder is done and no check is failing, code adds one polish workflow before the final
     Audit (`kind: polish`, code-made, so the work-order review never sees it). It sees the whole page or document
     and the style and may edit any section. Code re-runs every check that passed; if one now fails, every section
     goes back as it was. `J2_POLISH=0` turns it off.
6. **J2.g** Audit checks the result and files every finding to Identity, plus the design and usability rubric on a
   website (R-1 to R-7; code measures contrast, headings, tap targets and alt text). Necessary conditions
   (`conditions/*.json`) are checked by code. A condition marked `overridable` that fails on what may be a false
   alarm gets an AI double-check with a quote (`condition-double-check.md`): a false alarm is marked met and logged
   backstage; a real one is fixed, or you accept it.
7. **J2.h** Identity: is it **workable**? Code decides (`workable()`), never a model: every done-when item passes,
   every rubric item and necessary condition is met, and on a website there are no JS errors, no overflow at 360px
   and 1280px, forms submit and in-page links resolve. Identity can't tell you it's finished while code says it
   isn't. Not workable: back to J2.b.

**Limits never stop a run silently.** You decide (keep going with an amount, leave items out, finish as it is) when
usage reaches the margin, after `J2_MAX_CYCLES` (6) cycles, when the same failure comes back twice, after 2 cycles
that registered nothing, or at the per-cycle turn cap. A typed amount like `300k` or `1.5M` is understood.
"Finish as it is" ends `done_with_open_items` with the open items listed.

**Questions.** Every pause is one decision in one format (`_decision`): what is happening, why it matters, and two
to four options, each with what you get and the usage it needs, one suggested. Kinds: `proposal`, `facts`,
`usage`, `problem`, `confirm`. "Don't ask me any questions" in the brief, or `POST /api/v2/settings
{"no_questions": true}`, takes the suggested option for anything that isn't essential and logs it backstage (the
proposal, usage running out and an essential gap are still asked).

Identity talks to two audiences, one message per addressee: `to_requester` in plain words and `to_agents` for the
team. Between agents, the `say` line is one or two plain sentences with no codes; the structured fields keep every
id. Code checks the mix and regenerates once, then uses a template.

### Adaptation's memory (J2.h learns)

- When Audit confirms a fix worked (a problem in one audit is gone in the next and a workflow ran in between),
  Adaptation writes a lesson. Code appends it to `memory/lessons.jsonl` with the problem, cause, fix, run id,
  cycle and workflows.
- At J2.b, code picks the 5 lessons that share the most words with the current gap. Adaptation names the one
  it used (`lesson_used`; shown as a tag in the chat).
- `J2_MEMORY=0` turns memory off: nothing is read or written. Use it for clean test runs; the default is on.
  `J2_MEMORY_FILE` moves the file.
- The **Lessons** tab lists every lesson. Clear memory deletes the file after a confirm prompt.
- **Playbooks (plans, not only fixes):** when a run ends Done, Adaptation saves a playbook for that kind of
  business in `memory/playbooks.jsonl` (`J2_PLAYBOOK_FILE` moves it). One playbook per run; a later Done after
  a change request replaces it. It holds:
  - recorded by code: workflows in build order, costs, what failed and what fixed it, and the measured outcome
    (cycles, whether Audit passed the first time, AI calls, the changes you asked for)
  - written by Adaptation: the sections, mistakes to avoid and advice

  At its first J2.b for a brief, Adaptation reads up to 2 playbooks for the **same business type only**,
  closest brief first. A cafe's plan is never offered to a clothing shop. Lessons and playbooks written by mock
  runs are marked `mock` and never reach a live run. It says which it used (`playbook_used`) and what it changed (`playbook_changes`). Only Done runs
  save one. A `J2_FORCE_AUDIT_FAIL` run's playbook is marked test and follows the test-lesson rule.
  `J2_MEMORY=0` turns off lessons and playbooks alike.
- The **Playbooks** tab lists them, with a progress record per business type: runs, first-pass Audit rate,
  cycles and AI calls per run, and each run in order, so you can see whether it's improving. Clear playbooks
  is there too.

### Behind-the-scenes view

- **Agents panel** (next to the chat): one lane per agent (the five functions, the validator as code, each
  workflow agent). Each lane shows its live status (idle, working, waiting on someone, blocked) and what it's
  on; several builders can be working at once. Workflow agents also show the section they own, attempts, retries,
  usage against their share and share cap, and the last check result. Click a lane to open its latest message.
- **Detail view**: click any agent message (or a timeline step). It shows:
  - what it read: inputs summarised by code (charter, ledger, workflows, findings, proposal, lessons, task), with
    a toggle for the full system prompt, prompt and raw reply
  - what it decided: the structured reply
  - why: the `reason` field, which code adds to every agent's reply format
  - usage: AI calls, tokens and seconds in that step

  Tokens come from the provider (claude-cli, the Anthropic API and Gemini report them); mock mode has a fake meter
  (about 4 characters a token) so budget logic can be tested offline. Code-written messages say "no AI call".
- **Timeline** tab: every step in order on one line, coloured by agent, with each J2 step (J2.a to J2.h)
  marked. Click a step for its details.
- **Saved runs**: the picker in the header opens any `runs/j2-*` folder read-only in the same view (`?run=` in
  the URL). This covers its chat, lanes, timeline, details, site versions and report. Runs from before this
  change open too, but without the per-call details.
- **No secrets**: every server response passes through `redact()` in `j2_server.py`. Every `.env` value and any
  environment variable named like a key, token, secret, password or auth is replaced with `[redacted]`. The
  page never receives request headers.

Each AI call is saved in `runs/j2-*/calls.jsonl` (inputs, full prompt, raw reply, reason, phase, full usage,
seconds). Calls outside the agents' turns (the output classifier, the work-order review, AI checks, double-checks,
the planner and judge, the chat summary, the reviewer) are marked `"extra": true`. Each section is in
`sections.json`.

### Map

The **Map** tab draws the run as a metro line, built by code from the run's own files (`j2_map.py`, no model
call). Schema: `docs/map-schema.md`.
- **Trunk:** the Charter, then each deliverable (PRD, HLD, LLD, website) in order, joined by steps named by what
  their workflows do (Write, Build, Send). Deliverable labels sit below the line, team labels above.
- **Branches:** side jobs (a send deed, a milestone email) leave the trunk at the document they were built from,
  so they never sit between two documents. A milestone email hangs under the goal it reports.
- **Functions row:** Identity, Adaptation, Priority, Coordination and Audit, with calls, seconds and tokens. Each
  links to the tab that shows its work.
- Colours show status only. A chip row and the top line give the state ("Waiting on you", "Done", ...) and the
  checks passed; the outcome line names any open items. A legend lists the kinds drawn.
- Wide screens get a left-to-right drawing; under 900px it is drawn top to bottom.
- `runs/j2-*/map.json` is written beside `atoms.json`. `/api/map` serves the same shape for a live run, a saved
  run, and old runs (rebuilt from the folder). Anything the run did not record is shown as "not recorded".

### Message board (`J2_BOARD=1`, off by default)

A blocked agent can ask the one that knows instead of guessing (`j2_board.py`, schema `board/1`). **Askers:** the
five functions (Identity, Adaptation, Priority, Coordination, Audit) and the workflow builders. **Targets:** a
workflow, including a done one from an earlier cycle, or another function.
- **Ask:** the asker posts one question ("@<target> Q-1: ..."). A builder asks at most one per atom, a function at
  most one per turn. A function's reply format carries the field as `board_question` (every function format
  already uses "question" for the Requester or for a policy question); a builder's is `question`.
- **Board first:** every agent prompt, functions and builders, holds "BOARD (answered questions; check here before
  asking)". A question the board already answers is refused and the asker pointed at it ("already answered in
  Q-1"): 60% or more of its content words are already in that entry's question.
- **Answer:** one short answer-only call that may not ask back; its usage is counted like any call. A
  workflow answers from its recorded section and `agent_output`, and a correction to its own section is applied
  and marked "Updated by Q-1"; a function answers from the run's record. Nothing recorded is "not recorded".
- **Reuse:** a later agent names the entry it used instead of asking again. Its message carries "[read Q-1]",
  `used_by` records the atom or the function, and a builder's prompt records a `depends_on` edge.
- An unanswered question ("not mine") leaves the asker on the normal path.
- Saved in `board.json` and `board.jsonl`, with `asked_by_role` ("function" or "builder") and `answered_from`
  (`{workflow, version}` or `{function}`). The **Board** tab under Internals lists the entries, and atom cards
  show "Asked / Answered / Used Q-n". With the flag unset, no board files are written and the flow is unchanged.
- **Board story** (the first entry under Internals, shown only when the run has a `board.json`; also
  `?view=detail&tab=story` or `#story`): one flow strip per question (Doubt, Ask, Answer, Deliverable change
  (highlighted), Re-checked by code), then the impact grouped by deliverable, a numbers row and a compare picker
  for another saved run. Built by code from the run's own files (`j2_story.py`, schema `story/1`, served read-only
  at `/api/story`); anything the run didn't record reads "not recorded".

**Doc changes from the board.** In a design-document run an answer may correct the document itself:
`artifact_update` names `{doc, section, text, reason}`.
- Only the atom that **owns** that section (`documents.json`) may change it; anything else is refused with the
  reason. A **PRD** change is never applied from the board: it goes to Identity as a change request on the
  existing path, and the entry records that.
- Code replaces that section of `<kind>.md`, appends "Version n: Q-k, <reason>.", writes the new version file and
  the `.docx` again, and refreshes what reads it (the chain, the charter, the LLD blueprint).
- It then re-runs that document's conditions (P1-P8 / H1-H6 / L1-L6) and the owner's checks, with no AI call:
  receipts carry `"trigger": "Q-k"` and `audits.json` gets a `{"kind": "recheck"}` entry.
- The change **propagates along content edges only**, from the changed atom and transitively: the named allowlist
  in `j2_schema.CONTENT_EDGES` (the PRD's requirements, the HLD's components or summary, an LLD slice, a declared
  dependency) is what says a section was built from another. A manifest listing ("its section, anchor and
  selectors were listed") and a `board Q-n` edge record what a prompt held, not what the work was built from, so a
  change never travels along them, and a sibling section of the same document is not impacted without a content
  edge of its own. No content edge means `impact: []`. Each atom the closure reaches is re-checked and marked
  `rechecked` (as it is built, if it comes later); one that fails goes to Adaptation as a revise priced as a fix.
- Records: `from_version`/`to_version` and `impact` on the entry (every atom the closure reached, with what its
  re-check found), `changed_by`/`rechecked_after` on the artifact rows, `stale`/`rechecked` and "Updated by Q-k" on
  the atoms, an `asks` line between the two deliverables on the Map with the version bump and "re-checked after
  Q-k", an **Impact** column on the Board tab, and two chat lines: the change ("HLD v6 -> v7 (Q-1): the Components
  section is replaced ...") and, when the run stops, the tally, whose numbers are `impact` itself ("HLD v6 -> v7
  (Q-1). Re-checked: 12 passed, 0 sent to Adaptation."). The Simple view is unchanged.

`J2_FORCE_QUESTION=<comma list>` (mock mode only) is a test switch like `J2_FORCE_AUDIT_FAIL`: each named asker
asks one question, once per run. A name is a function (`identity`, `adaptation`, `priority`, `coordination`,
`audit`), a builder (a workflow id, or a role word matched against its name, such as `order`), or a document
(`hld`, `lld`: that document's builder asks the document it was built from). Agents never see the switch; humans
see it labelled in the chat.

**Demo** (offline, mock mode, saved to `runs/`):

```bash
python3 j2_flow_test.py --fast --board-demo
```

It builds the Thread & Loom boutique (prices, timings and address from the brief) to Done, then asks for "a section
for visiting hours", and prints the run id and its page URL. Three questions are asked, each once: Identity asks
the workflow that built the timings where they are, Adaptation reuses that answer and plans a revise of that
workflow's section as a fix, Priority asks Adaptation whether the change is new work or a fix, the revise
builder reuses the answer, and Audit asks the products workflow which attribute holds the price, then reads its own
entry back on the next audit. The same run with `J2_BOARD` unset writes no board file and asks nothing. (Builders
don't run in parallel while the board is on.)

The document demo is the same command with `--board-doc-demo`: it writes the PRD, HLD and LLD for Still Point Yoga
and then the website, and the LLD's Interactive elements builder asks the HLD's Components atom how the booking is
sent. The HLD owner answers from the address in the brief and corrects its own section, so the HLD gains a version,
H1-H6 pass again, and every atom the recorded edges reach is re-checked.

### Sends: test messages and milestone emails

`j2_send.py` sends nothing by default (dry run). Live sending is email only, by SMTP (Python `smtplib`, STARTTLS).
- **Send deeds:** a brief that asks to email or Slack the finished document ("send it to me by email") gets a
  deed stage. Whether it asks is the output classifier's reading of the message, not keyword matching; a mere
  mention of an email address or a Slack link isn't a send.
- **Milestone emails:** one email per goal reached (each document filed and checked, or the site workable),
  built by code from the run's record: goal, version, checks passed and a one-line summary, with links and
  addresses removed. They are opt-in: set `J2_MILESTONE_EMAILS=1`, or ask in the brief ("email me updates"; the
  output classifier reads it). Built by code, they use no model call and no usage.
- **Recipient:** taken only from `J2_TEST_EMAIL` / `J2_TEST_SLACK_TARGET`, never from the brief. Anything else
  is refused, and nothing is sent when the variable is unset.
- **Mode:** `J2_SEND_MODE` is `dry-run` (default: nothing leaves, the deed stays open), `mock` (an in-process
  recorder, for tests) or `live` (a real email by SMTP; a Slack send stays a dry run).
- **Live:** the first email of a run asks you once in Needs you: "Send real emails to your test address during
  this run?" No keeps every send of that run a dry run. Each email has a key (run id, atom id, goal) and is never
  sent twice, even on a retry or a resumed run. At most `J2_SEND_CAP` (default 10) go out per run; the rest are
  skipped and recorded. A missing SMTP setting refuses that send, records why and the run goes on. A sent email
  closes its atom; a failed one stays open with the reason. The Map says "Email · PRD done · sent" or "· failed".
- **Receipts:** hold the mode, sent, the SMTP code, a masked recipient (`d***@example.com`), hashes and the time;
  on a failure, an error class (`settings`, `auth`, `connection`, `refused`, `smtp`), never the server's text. Never
  a full address, a password or any setting's value.

### Modes and settings

`J2_FIXES` (default 0) is shown in the page header and on the first line of `chat.jsonl`:
- `J2_FIXES=0` is the baseline, as close to the diagram as possible. An Identity ruling goes straight to the
  validator (J2.d -> J2.e). A change request after done goes straight to Adaptation (J2.b).
- `J2_FIXES=1` turns on two fixes:
  - An Identity ruling that costs more than Priority granted goes back to Priority (J2.c) once. Priority's
    answer is final; if the ruling is still over budget, Identity asks you.
  - A change request after done goes to Identity at J2.a first, then J2.b.

Settings:

| Setting | Default | What it does |
|---|---|---|
| `J2_TOKEN_BUDGET` | unset | A fixed usage budget in tokens (developer override): no proposal pause. Unset, the budget is the approved proposal's estimate plus the margin |
| `J2_MARGIN_PCT` | 15 | The safety margin: code pauses and asks when usage reaches budget minus this share |
| `J2_TOKEN_CAP` | 2 x budget | The most your approvals can raise the budget to |
| `J2_LEEWAY_PCT` | 25 | A workflow may use its token share plus this much before Priority is asked about a top-up |
| `J2_LIMIT_ADD_TOKENS` | 600000 | The least "keep going" adds when the budget ran out |
| `J2_PARALLEL` | 3 | Builders that run at once in one batch (1 = one at a time) |
| `J2_TOOLS` | on | Read-only web search and fetch and read-only GitHub (`gh repo view`, `gh search`) for the planner and research workflows only. 0 turns them off. Needs `claude-cli` (and `gh` logged in for GitHub) |
| `J2_TOOL_TIMEOUT` | 1800 | Seconds a tool-using CLI call may take (plain calls: 900) |
| `J2_DESIGN` | on | Websites: design research from the brief's problem (R-design in research.md) and a style choice (three looks with previews) right after the proposal is approved. 0 turns both off |
| `J2_DESIGN_BUDGET_USD` | 0.75 | Spend cap for the one design research call (`claude --max-budget-usd`); the prompt also allows only a few searches and fetches |
| `J2_POLISH` | on | 0 turns off the polish step before the final Audit |
| `J2_NEIGHBOURS` | on | 0 gives builders only the short list of other sections, not their neighbours' full text |
| `J2_REALIZATION` | on | 0 turns off planning by stage and certainty (and the judge) |
| `J2_MAX_CYCLES` | 6 | Cycles before Identity asks what to do |
| `J2_BARGAIN_MINUTES` | 15 | J2.c time bound |
| `J2_BARGAIN_CALLS` | 8 | J2.c spend bound (AI calls) |
| `J2_MEMORY` | 1 | 0 turns lessons off |
| `J2_MAX_TURNS` | 30 | Agent turns per cycle, at least; a cycle gets max(this, 10 + 4 × workflows registered in it). J2.h after a passing Audit always runs |
| `J2_SLIM` | on | 0 sends builders the whole page (the old path) instead of their neighbours and a list of the others |
| `J2_RUNS_DIR` | `runs/` | Folder runs are saved to |
| `J2_SHARE_FLOOR` | 0.8 | A part's usage share far under what that kind of work usually uses is raised to this part of it |
| `J2_SHARE_FAR_UNDER` | 0.5 | "Far under": a share below this part of the usual usage |
| `J2_KEEP_TEST_RUNS` | off | 1 keeps the flow suite's temp folder of mock runs (removed at exit otherwise) |
| `J2_OUTPUT` | unset | Picks the output for every run (`website`, `prd`, `hld` or `lld`) and skips the output classifier. Unset, the classifier reads the first message. A website must meet `conditions/website.json`; a document is six markdown sections checked by code (no browser) with its own conditions file and rubric, and ends with `<kind>.md` and `<kind>.docx` (needs `python-docx`) |
| `J2_FORCE_AUDIT_FAIL` | off | Test switch, see below |
| `J2_MEMORY_TEST_LESSONS` | off | 1 lets J2.b read test lessons (demo runs only), see below |
| `J2_BOARD` | off | 1 turns on the message board, see "Message board" |
| `J2_MILESTONE_EMAILS` | off | 1 sends a milestone email per goal reached (dry run) |
| `J2_SEND_MODE` | `dry-run` | `dry-run`, `mock` or `live` (real email by SMTP, after you say yes once a run) |
| `J2_SEND_CAP` | 10 | The most live emails one run sends |
| `J2_SMTP_HOST`, `J2_SMTP_PORT`, `J2_SMTP_USER`, `J2_SMTP_PASSWORD`, `J2_SMTP_FROM` | unset | SMTP for live mode (in `.env` only) |
| `J2_TEST_EMAIL` | unset | The only address a send may go to |
| `J2_TEST_SLACK_TARGET` | unset | The only Slack target a send may go to |
| `J2_OVERRIDE_KEY` | unset | Owner override key, `.env` only, see below |

Old names still read: `J2_BUDGET` / `J2_BUDGET_CAP` / `J2_LIMIT_ADD` (one old credit = 20,000 tokens).

**Mock-only test switches** (agents never see them): `J2_FORCE_QUESTION` (each named asker asks one board
question), `J2_FORCE_REVIEW_FAIL=<name words>` (the work-order review says no), `J2_FORCE_AI_CHECK_FAIL=1|<words>`
(an AI check fails), `J2_FORCE_CONDITION_DOUBT=<id>` and `J2_MOCK_FALSE_ALARM=1` (the false-alarm double-check),
`J2_FORCE_OUTPUT_UNSURE=1` (the output classifier isn't sure, so the confirm question shows), `J2_FORCE_POLISH_BREAK=1`
(the polish breaks a check and is undone), `J2_MOCK_RESEARCH=1` (the mock plan has a research workflow).

**Owner override: `J2_OVERRIDE_KEY`.** Set it in `.env` (never committed; `.env.example` lists the name only). A
message that starts with the key followed by a command is applied by code, not by an agent: `budget +N` adds N
tokens (`+5M`, `+300k`; the cap doesn't apply), `ship` ends the run as it is (`done_with_open_items`), `drop <item>` leaves out a done-when
item by number or words. A visible "Owner override applied: ..." note is posted. The key itself is never posted,
stored in the run files or sent to an agent, and the server redacts it from every response.

**Test switch for live runs: `J2_FORCE_AUDIT_FAIL=<done-when item number>`.** It is off unless the variable is
set. In cycle 1 only (Audit's first check), Audit's result for that item is overridden to `NEEDS_REVISION`.

**The agents can't tell it's a test.** They see a normal Audit finding with a concrete, plausible issue chosen
from the item's words, for example "Sunday is missing from the opening hours list, so the hours aren't
complete." Set your own with `J2_FORCE_AUDIT_NOTE="..."`.
- The notes are content gaps only, never overflow or JS claims, so the render check can't contradict them.
- Audit's chat line for that check is written by code from the findings as filed, so it can't say "all pass".
- Messages flagged as tests are never put in any agent's prompt (`chat_view()`), and neither are the test fields
  (`forced_test`, `real_verdict`).
- A mock test scans every saved prompt in `calls.jsonl` to make sure.

The labels are for humans only:
- a red "TEST SWITCH" system note, with Audit's real verdict
- a "TEST: item N forced to fail" tag on Audit's message
- a red badge in the header (also when the run is opened later as a saved run)
- `force_audit_fail` in `chat.jsonl` (first line) and `summary.json`
- `forced_test` and `real_verdict` on the finding in `audits.json`

Audit can still withdraw the finding if Adaptation disputes it and the page shows the item is met. That's the
agents' own judgment, not a leak.

Everything after runs normally: Identity sends it back, Adaptation proposes a fix, the workflow agent runs it,
and Audit re-checks for real. If the fix passes, the lesson is saved. It is marked `"test": true` and by
default is never read back at J2.b, so a forced failure can't steer real runs.

`J2_MEMORY_TEST_LESSONS=1` (opt-in, for demo runs only) lets Adaptation read test lessons at J2.b, so a demo can
show a lesson being saved in one run and used in the next. When a test lesson is used, it's flagged in:
- the chat: a red "used TEST LESSON" tag on Adaptation's message and a "TEST LESSON" system note
- the Agents panel: a "test lesson" badge on Adaptation's lane
- the header badge and the Lessons tab
- `summary.json` (`test_lessons`, and `"test": true` on the lesson used) An item number the charter doesn't have is
ignored, with a warning. The switch is recorded in `chat.jsonl` (first line) and in `summary.json`.

```bash
J2_FORCE_AUDIT_FAIL=2 STUDIO_PROVIDER=claude-cli python j2_server.py   # exercise the fix-and-learn loop live
```

**Our interpretation of "its spend" in J2.c:** the J2 page bounds the bargain by "four hops, fifteen minutes and
its spend" but gives no number for the spend. We read it as the AI calls the bargain itself uses and set the
bound at **8 calls** (four hops x two sides). Change it with `J2_BARGAIN_CALLS`.

Conflicts: any two agents that disagree get 4 attempts to settle it. Then Identity rules from the charter, or
asks you one question with options and rules on your answer. Every conflict is in the Conflicts tab and
`runs/j2-*/conflicts.json`, including what triggered the escalation: 4 attempts, the time bound or the spend
bound.

When a run ends, `runs/j2-*/summary.json` is written at once, before the reviewer's AI call (which can take a
minute or more), so it exists as soon as the chat says the run ended. It is also written when the reviewer
fails or the run crashes. It records (written by code, no AI call):
- run: mode, model, brief, status (`done`, `done_with_open_items`, `stopped`, `crashed`), AI calls
- budget: measured usage (budget, spent, margin line, estimate, by phase and by workflow), raises
- what happened: questions to you, conflicts, validator rejections, HOLDs, audits, limits hit
- the result: workable problems still open, to-be-confirmed facts, items you dropped, each done-when item's
  pass/fail
- agents: each workflow agent (section, status, calls, retries, usage), lessons saved and used, route-check violations
- settings: `no_questions`

### Tests

```bash
python3 j2_flow_test.py --fast    # offline, mock mode, no Chrome steps, about 5 minutes
python3 j2_flow_test.py --fast --browser   # adds the Chrome-driven tests
python3 j2_flow_test.py           # offline, mock mode, both J2_FIXES modes; --chat prints the chats
python3 realization_test.py       # the planner, the judge, the stage guide and planning gaps, in mock mode
python3 v2_test.py                # the v2 API walked like the new page does (proposal, decisions, settings, saved runs)
python3 kingdom_test.py           # the kingdom view's routes: /api/v2/map and /api/v2/control (pause, stop, skip, redo, note)
python j2_check.py site.html      # the render check on any page
```

`j2_flow_test.py` keeps every lesson and playbook in a temp folder, set before `j2` is imported, and ends by checking
that the real `memory/` files are byte-for-byte unchanged. It runs with a fixed `J2_TOKEN_BUDGET` and with the polish
step off (the storyline tests count workflows and sections as they were); `polish_step` turns it on.

What the suites cover, in short:
- the original flows, both `J2_FIXES` modes; one agent per workflow, sections and order, `revises`
- limits and decisions: same failure twice, the cycle limit, to-be-confirmed facts, the margin pause, the decision
  format, `no_questions`
- usage: every call counted (summary, reviewer, planner and judge included), shares, the one top-up
- the validator: code's free checks, the batched work-order review, `ai-judge` checks and their receipts, essential
  rejections, the document section guard
- finishing: false alarms and the double-check, the done-claim guard, no writing ahead
- step 5: the stage guide, planning gaps as decisions, dependencies resolved, loop-checked and enforced by code
- step 6: the style guide step with motion, the documents' house style, parallel batches (deterministic in mock),
  neighbours in the prompt, the polish step and its undo
- step 7: the exact `--tools` / `--allowedTools` flags, `J2_TOOLS=0`, `research.md` written and read
- step 8: the output classifier (mock reading), the confirm question, picked outputs, no trigger words in
  `artifacts/types.json`
- the legacy page's views, the Map, the board, sends and milestone emails, saved runs, `plain_unchanged` (the plain
  website flow against an older commit, with the style step and parallel batches allowed for)

### Still different from the J2 page

- **Root (J2.e)**: the page says Root checks granted workflows against standards ("designed; not yet built").
  Here code checks fields, dependencies, refusals and usage, and one AI review per batch checks the work orders.
- **Library workflows**: the page has Adaptation pick from a Library or make custom ones. Here every workflow
  is custom.
- **Engines and triggers**: the page has each function as an engine that wakes when its records exist. Here one
  loop hands the turn from agent to agent; only builders run in parallel, in batches.
- **Audit timing**: Audit runs once the build queue is empty, not after every workflow (fewer calls).
- **"Core" done-when items**: every done-when item counts as core; the charter has no core / optional split.
- **"Its spend" in J2.c**: our number (8 AI calls), see above.
- **Lesson relevance**: word overlap, not meaning; fine for a small file. Playbooks match on business type
  first, then shared words.
- **Rubric R-1, R-4, R-5** (styling, main action, navigation) are Audit's judgment on the screenshot. Only R-2,
  R-3, R-6 and R-7 are measured by code. Screenshots go to the model in live runs only. Image input through
  `claude -p` (stream-json) is implemented but not yet tried on a live run.
- **Executors**: the official files have no executor. The workflow agents use our own `builder.md`.
- **CEO**: where the official files say CEO, J2 reads it as you, reached only through Identity.
- **No-progress limit**: a run with 2 cycles that registered nothing also triggers Identity's question, a guard
  that isn't on the page.
