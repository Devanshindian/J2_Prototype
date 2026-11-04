# Setup: running the J2 demo

J2 is a group of AI agents (Identity, Adaptation, Priority, Coordination, Audit) that build a website from your
brief in a group chat. You type the brief in a local web page; the agents ask you questions, plan, build and
check the site. See `README.md` for how the flow works.

## What you need

| Need | Why |
|---|---|
| Python 3.9 or newer | Runs the server (`python3 --version` to check) |
| **Claude Code CLI, logged in to a Claude subscription** (Pro or Max) | The normal way to run: every agent call goes through `claude -p` on your subscription, so no API key and no API bill |
| Google Chrome (optional) | Audit screenshots the site at 360px and 1280px. Without Chrome, Audit judges from code only. Set `J2_CHROME=/path/to/chrome` if it is not in the usual place |
| An API key (optional) | Only if you do not use the Claude subscription: `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` |

### Install and log in to Claude Code

```bash
npm install -g @anthropic-ai/claude-code   # or see https://docs.claude.com/en/docs/claude-code
claude                                      # first run: log in with your Claude account, then exit
claude -p "say hi"                          # check: should print a reply
```

The server removes `ANTHROPIC_API_KEY` from the environment it gives `claude -p`, so subscription runs never bill
the API, even if the key is set.

## One-time setup

```bash
git clone https://github.com/<your-github-username>/J2_Prototype.git
cd J2_Prototype
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: fill in only what you use. .env is never committed
```

## Run it

Always activate the virtual env first:

```bash
source .venv/bin/activate
```

### Normal run: your Claude subscription (recommended)

```bash
STUDIO_PROVIDER=claude-cli python3 j2_server.py
```

Opens http://127.0.0.1:8773. Write what you want, approve the plan, and answer the team's questions.

### Clean test run: no memory, no delay

```bash
J2_FIXES=0 J2_MEMORY=0 STUDIO_PROVIDER=claude-cli J2_DELAY=0 python3 j2_server.py
```

- `J2_FIXES=0`: baseline flow, as close to the J2 diagram as possible
- `J2_MEMORY=0`: no lessons read or written, so runs do not affect each other
- `J2_DELAY=0`: no pause between AI calls (the pause is only for free-tier API rate limits)

### Usage and the proposal

The budget is real usage in tokens, measured on every AI call. You don't pick it up front: after the team
understands your request, it shows a proposal (what it will make, its parts and the estimated usage). Approve sets
the budget to the estimate plus a 15% margin (`J2_MARGIN_PCT`). When usage reaches the margin, the run pauses and you
choose: keep going (type an amount like `300k` or `1.5M`), leave items out, or finish as it is.

- `J2_TOKEN_BUDGET=3000000` fixes the budget and skips the proposal (a developer override; the tests use it).
- `J2_TOKEN_CAP` is the most your approvals can raise it to (default: twice the approved budget).
- The old `J2_BUDGET` / `J2_BUDGET_CAP` still work: one old credit = 20,000 tokens.

### What gets made

- There are no output buttons. Write what you want: "a website for my clinic", "a PRD", "the design docs", "a PRD and
  then the website". An AI reader decides what to make from your message (`agents/j2/output-classifier.md`): a
  website, documents in the order PRD, HLD, LLD, or documents and then the website. When it isn't sure, it asks you
  to confirm in one click ("A PRD and a website, right?").
- The details question comes first. When a website is also asked for, the team asks once, before the first document,
  for what only you know (menu and prices, hours, address, contact, form fields). The answers go to every later stage.
- `J2_OUTPUT=prd` (or `website`, `hld`, `lld`) picks the output for every run and skips the reader.

### Pages

- `http://127.0.0.1:8773/` is the new page (`ui/`, on the `/api/v2` routes).
- `http://127.0.0.1:8773/legacy` is the older page with the Simple view, the Detailed view and the Map.

### Other ways to run

```bash
# With the fixes turned on (over-budget rulings go back to Priority once; change requests go to Identity first)
J2_FIXES=1 STUDIO_PROVIDER=claude-cli python3 j2_server.py

# Pick the Claude model (default: sonnet)
CLAUDE_CLI_MODEL=opus STUDIO_PROVIDER=claude-cli python3 j2_server.py

# API key instead of the subscription: leave STUDIO_PROVIDER empty and set ANTHROPIC_API_KEY or GEMINI_API_KEY in .env
python3 j2_server.py

# Offline demo: scripted agents, no Claude and no key needed
STUDIO_MOCK=1 python3 j2_server.py

# Different port, or do not open a browser
STUDIO_PROVIDER=claude-cli python3 j2_server.py --port 8780 --no-browser
```

Provider order: `STUDIO_PROVIDER=claude-cli` wins. Otherwise `ANTHROPIC_API_KEY`, then `GEMINI_API_KEY`, then mock.

### Optional features (off by default)

```bash
# Message board: a blocked builder can ask the agent that knows, and later builders reuse the answer
J2_BOARD=1 STUDIO_PROVIDER=claude-cli python3 j2_server.py

# Offline board demo: type a clothing-shop brief (products, filters, order on WhatsApp); the order builder asks one question on purpose
J2_BOARD=1 J2_FORCE_QUESTION=order STUDIO_MOCK=1 python3 j2_server.py

# The same with the functions asking (Identity, Priority and Audit each ask one question):
J2_BOARD=1 J2_FIXES=1 J2_FORCE_QUESTION=identity,priority,audit STUDIO_MOCK=1 python3 j2_server.py
# or the whole demo without a browser, saved to runs/:
python3 j2_flow_test.py --fast --board-demo

# Templates: every work atom shows the prompt template it was sent through, the reply model its reply
# passed and the output template its section follows (the "Template" block on the atom card, Detailed view)
J2_TEMPLATES=1 STUDIO_PROVIDER=claude-cli python3 j2_server.py

# Offline templates demo: the Still Point documents-plus-website brief, nothing to install
J2_TEMPLATES=1 STUDIO_MOCK=1 python3 j2_server.py
# or the two demo runs without a browser, saved to runs/ (clean, and with planted failures):
python3 j2_flow_test.py --fast --template-demo
python3 j2_flow_test.py --fast --template-demo --template-fail-demo

# Milestone emails: one per goal reached (each document, then the site). Dry run: nothing is sent
J2_MILESTONE_EMAILS=1 J2_TEST_EMAIL=you@example.com STUDIO_PROVIDER=claude-cli python3 j2_server.py
```

Sends (a test email or Slack message asked for in the brief, and milestone emails) are dry run by default.
`J2_SEND_MODE=live` sends real email by SMTP after you say yes once in the run (see `README.md`). They go only to
`J2_TEST_EMAIL` or `J2_TEST_SLACK_TARGET`, never to an address in the brief. With the variable unset, nothing is sent.
Asking in the brief ("email me updates") also turns milestone emails on.

The legacy page (`/legacy`) opens in the Simple view. "See how it works" opens the Detailed view, which starts on the
Map. The rail on the left switches between Map, Chat (the Simple view) and Internals (the other tabs, including Board
when the board is on). On a phone the rail runs along the bottom.

## Settings

Set any of these before `python3 j2_server.py`, like the examples above.

| Setting | Default | What it does |
|---|---|---|
| `STUDIO_PROVIDER` | unset | `claude-cli` runs on your Claude subscription |
| `CLAUDE_CLI_MODEL` | `sonnet` | Model for `claude -p` |
| `STUDIO_MOCK` | off | `1` runs offline with scripted agents. Mock also runs when no provider or key is set |
| `J2_FIXES` | 0 | `1` turns on the two flow fixes |
| `J2_TOKEN_BUDGET` | unset | A fixed usage budget in tokens; skips the proposal |
| `J2_MARGIN_PCT` | 15 | The safety margin: the run pauses and asks when usage reaches budget minus this share |
| `J2_TOKEN_CAP` | 2 x budget | The most your approvals can raise the budget to |
| `J2_LEEWAY_PCT` | 25 | A workflow may use its token share plus this much before a top-up is asked |
| `J2_PARALLEL` | 3 | Builders that work at the same time (`1` = one at a time) |
| `J2_TOOLS` | on | Read-only web search and fetch and read-only GitHub (`gh repo view`, `gh search`) for the planner, the research workflows and the design research. `0` turns them off. Needs `claude-cli`; GitHub needs `gh` logged in |
| `J2_DESIGN` | on | Websites: design research from the brief's problem and a style choice (three looks with previews) right after the proposal is approved. `0` turns both off (the first builder writes the style guide, as before) |
| `J2_DESIGN_BUDGET_USD` | 0.75 | Spend cap for the one design research call (`claude --max-budget-usd`); the prompt also allows only a few searches and fetches |
| `J2_POLISH` | on | `0` turns off the polish step before the final check |
| `J2_NEIGHBOURS` | on | `0` gives builders only a short list of the other sections, not their neighbours' full text |
| `J2_MEMORY` | 1 | `0` turns lessons and playbooks off |
| `J2_REALIZATION` | 1 | On by default: Adaptation plans by stage and certainty, a separate judge scores every workflow before the build, and a part that isn't ready becomes a question for you (add information, try anyway, skip it). Writes `realization.json`, `realization.md` and `realization-questions.json`. `0` turns it off (the classic path) |
| `J2_DELAY` | 2 | Seconds between AI calls |
| `J2_MAX_CYCLES` | 6 | Plan, build, audit cycles before Identity asks you what to do |
| `J2_MAX_TURNS` | 30 | Agent turns per cycle |
| `J2_LIMIT_ADD_TOKENS` | 600000 | The least "keep going" adds when the budget runs out |
| `J2_SLIM` | on | Builders get their neighbours' sections in full plus a short list of the others, not the whole page. `0` turns it off |
| `J2_OUTPUT` | unset | Picks the output for every run and skips the AI reader |
| `J2_RUNS_DIR` | `runs/` | Folder runs are saved to |
| `J2_SHARE_FLOOR` | 0.8 | A part's usage share far under what that kind of work usually uses is raised to this part of it |
| `J2_SHARE_FAR_UNDER` | 0.5 | "Far under": a share below this part of the usual usage |
| `J2_KEEP_TEST_RUNS` | off | 1 keeps the flow suite's temp folder of mock runs (removed at exit otherwise) |
| `J2_CHROME` | auto | Path to Chrome for Audit screenshots |
| `J2_OVERRIDE_KEY` | unset | Owner override key, set in `.env` only (see `README.md`) |
| `J2_BOARD` | off | `1` turns on the message board (builders then run one at a time) |
| `J2_FORCE_QUESTION` | off | Mock-only test switch: a comma list of askers, each asking one question. A function (`identity`, `adaptation`, `priority`, `coordination`, `audit`) or a builder (workflow id or role word) |
| `J2_MILESTONE_EMAILS` | off | `1` writes a milestone email per goal reached (dry run) |
| `J2_SEND_MODE` | `dry-run` | `dry-run`, `mock` (tests) or `live` (real email by SMTP, after you say yes once a run) |
| `J2_TEST_EMAIL` | unset | The only address a send may go to |
| `J2_TEST_SLACK_TARGET` | unset | The only Slack target a send may go to |

Other mock-only test switches are listed in `README.md` ("Modes and settings").

## Checks

```bash
python3 j2_flow_test.py --fast             # offline flow test in mock mode, no browser steps. About 5 minutes
python3 j2_flow_test.py --fast --browser   # adds the tests that drive the page in Chrome. About 8 to 9 minutes
python3 j2_flow_test.py                    # the full test, both J2_FIXES modes. Longest
python3 j2_check.py site.html              # render check on any HTML page
python3 realization_test.py                # realization planner, judge and J2 runs with J2_REALIZATION, offline
python3 v2_test.py                         # the v2 API, walked like the new page does, offline
python3 kingdom_test.py                    # the kingdom view's map and control routes, offline
```

`plain_unchanged` is one of the checks. It compares the plain website path (no documents asked for) with a fixed
checkpoint commit, so a change that alters the plain path shows up. It runs with `J2_SLIM=0` against the older
commit and with the default against the commit made right after `J2_SLIM` became the default. The style guide step
and parallel batches are the two allowed differences: run one builder at a time, the agents speak in the checkpoint's
order once the style step is left out; run in parallel, the page, its sections and the outcome are the same.

## Where output goes

Each run is saved under `runs/` (or `J2_RUNS_DIR`): chat log, AI calls, site versions, screenshots. Also:

- `atoms.json`: every work atom of the run in the `atom/1` shape, with its warnings. The shape is described in
  `docs/atom-schema.md` (machine form: `docs/atom-schema.json`)
- the document files of a documents run: `prd.md`, `hld.md`, `lld.md`, and `.docx` copies (needs `python-docx`)
- `map.json`: the Map tab's drawing data, built by code from the run's files. Described in `docs/map-schema.md`
- `board.json` and `board.jsonl`: the message board, only when `J2_BOARD=1`
- `style.json` (the website's style guide, `kind: site`) and `doc-style.json` (the documents' house style, `kind: doc`)
- `research.md`: research workflows' entries (R-1, R-2, ...) with their sources
- `output-choice.json`: what the AI reader decided to make and why; `settings.json`: run settings (`no_questions`)

Past runs open read-only from the page. Lessons are kept in `memory/`, which is git-ignored. A few reference runs are tracked; new runs are ignored by git.

## Troubleshooting

| Problem | Fix |
|---|---|
| `claude -p failed` | Run `claude -p "say hi"` in a terminal. If it fails, log in again with `claude` |
| `claude: command not found` | Install Claude Code and make sure it is on your `PATH` |
| `Chrome not found` in Audit | Install Chrome or set `J2_CHROME` |
| Port 8773 in use | Add `--port 8780` |
| Run is in mock mode, or saved to a temporary folder | An earlier `export STUDIO_MOCK=1` or `export J2_RUNS_DIR=...` is still set in that Terminal window. Run `unset STUDIO_MOCK J2_RUNS_DIR`, or open a new window |
