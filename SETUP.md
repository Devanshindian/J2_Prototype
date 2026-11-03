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

Opens http://127.0.0.1:8773. Type a brief (or pick an example card) and answer the team's questions.

### Clean test run: no memory, no delay

```bash
J2_FIXES=0 J2_MEMORY=0 STUDIO_PROVIDER=claude-cli J2_DELAY=0 python3 j2_server.py
```

- `J2_FIXES=0`: baseline flow, as close to the J2 diagram as possible
- `J2_MEMORY=0`: no lessons read or written, so runs do not affect each other
- `J2_DELAY=0`: no pause between AI calls (the pause is only for free-tier API rate limits)

### Which budget fits which run

The budget is counted in work credits. Set it with `J2_BUDGET` (the default is 100).

| Run | Budget |
|---|---|
| A short test run, or a small website. Budget pressure shows up early | `J2_BUDGET=40` |
| A normal one-page website | the default, 100 |
| One document (PRD, HLD or LLD) | not measured live. Start with the default and raise it if the team runs out |
| A full documents-plus-website run | `J2_BUDGET=500` or more. One measured live run used all 500 credits, so the default of 100 is too low |
| A test email, Slack message or milestone email | 5 credits each, on top of the run. A milestone email the credits can't cover is skipped and the run goes on |

`J2_BUDGET_CAP` (default 2 x the budget) is the most your approvals can raise it to.

### Design docs and websites

- Asking for "design docs" (or "design documents", or a PRD, HLD or LLD by name) builds those documents, in the order
  PRD, HLD, LLD. Naming one or two builds exactly those.
- A website is built from the documents only when the brief also names a website. With no document asked for, the
  run is the normal website flow.
- The details question comes first. When a website is also asked for, the team asks once, before the first document,
  for what only you know (menu and prices, hours, address, contact, form fields). The answers go to every later stage.

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

# Milestone emails: one per goal reached (each document, then the site). Dry run: nothing is sent
J2_MILESTONE_EMAILS=1 J2_TEST_EMAIL=you@example.com STUDIO_PROVIDER=claude-cli python3 j2_server.py
```

Sends (a test email or Slack message asked for in the brief, and milestone emails) are dry run only. Live sending
is not built yet. They go only to `J2_TEST_EMAIL` or `J2_TEST_SLACK_TARGET`, never to an address in the brief. With
the variable unset, nothing is sent. Asking in the brief ("email me updates") also turns milestone emails on.

The page opens in the Simple view. "See how it works" opens the Detailed view, which starts on the Map. The rail
on the left switches between Map, Chat (the Simple view) and Internals (the other tabs, including Board when the
board is on). On a phone the rail runs along the bottom.

## Settings

Set any of these before `python3 j2_server.py`, like the examples above.

| Setting | Default | What it does |
|---|---|---|
| `STUDIO_PROVIDER` | unset | `claude-cli` runs on your Claude subscription |
| `CLAUDE_CLI_MODEL` | `sonnet` | Model for `claude -p` |
| `STUDIO_MOCK` | off | `1` runs offline with scripted agents. Mock also runs when no provider or key is set |
| `J2_FIXES` | 0 | `1` turns on the two flow fixes |
| `J2_BUDGET` | 100 | Starting budget, in work credits (see "Which budget fits which run") |
| `J2_BUDGET_CAP` | 2 x budget | Most your approvals can raise the budget to |
| `J2_MEMORY` | 1 | `0` turns lessons and playbooks off |
| `J2_REALIZATION` | 1 | On by default: Adaptation's first plan of a website run goes through realization and certainty (the planning part of `agents/j2/adaptation.md`), a separate judge scores every workflow before the build, and planning files are written under `artifacts/` for the build to read. Writes `realization.json` and `realization.md` in the run folder. `0` turns it off (the classic path) |
| `J2_DELAY` | 2 | Seconds between AI calls |
| `J2_MAX_CYCLES` | 6 | Plan, build, audit cycles before Identity asks you what to do |
| `J2_MAX_TURNS` | 30 | Agent turns per cycle |
| `J2_LIMIT_ADD` | 30 | Budget "keep working" adds when the budget runs out |
| `J2_RATES` | 1 | `0` turns the rate card off |
| `J2_SLIM` | on | Builders get their own section plus a short list of the other sections, not the whole page. `0` turns it off |
| `J2_RUNS_DIR` | `runs/` | Folder runs are saved to |
| `J2_CHROME` | auto | Path to Chrome for Audit screenshots |
| `J2_OVERRIDE_KEY` | unset | Owner override key, set in `.env` only (see `README.md`) |
| `J2_BOARD` | off | `1` turns on the message board |
| `J2_FORCE_QUESTION` | off | Mock-only test switch: a comma list of askers, each asking one question. A function (`identity`, `adaptation`, `priority`, `coordination`, `audit`) or a builder (workflow id or role word) |
| `J2_MILESTONE_EMAILS` | off | `1` writes a milestone email per goal reached (dry run) |
| `J2_SEND_MODE` | `dry-run` | `dry-run` or `mock` (tests). Live sending is not built |
| `J2_TEST_EMAIL` | unset | The only address a send may go to |
| `J2_TEST_SLACK_TARGET` | unset
 | The only Slack target a send may go to |

## Checks

```bash
python3 j2_flow_test.py --fast             # offline flow test in mock mode, no browser steps. About 35 seconds
python3 j2_flow_test.py --fast --browser   # adds the tests that drive the page in Chrome. About 8 to 9 minutes
python3 j2_flow_test.py                    # the full test, both J2_FIXES modes. Longest
python3 j2_check.py site.html              # render check on any HTML page
python3 realization_test.py                # realization planner, judge and J2 runs with J2_REALIZATION, offline
```

`plain_unchanged` is one of the checks. It compares the plain website path (no documents asked for) with a fixed
checkpoint commit, so a change that alters the plain path shows up. It runs twice: with `J2_SLIM=0` against the
older commit, and with the default against the commit made right after `J2_SLIM` became the default.

## Where output goes

Each run is saved under `runs/` (or `J2_RUNS_DIR`): chat log, AI calls, site versions, screenshots. Also:

- `atoms.json`: every work atom of the run in the `atom/1` shape, with its warnings. The shape is described in
  `docs/atom-schema.md` (machine form: `docs/atom-schema.json`)
- the document files of a documents run: `prd.md`, `hld.md`, `lld.md`, and `.docx` copies (needs `python-docx`)
- `map.json`: the Map tab's drawing data, built by code from the run's files. Described in `docs/map-schema.md`
- `board.json` and `board.jsonl`: the message board, only when `J2_BOARD=1`

Past runs open read-only from the page. Lessons are kept in `memory/`, which is git-ignored. A few reference runs are tracked; new runs are ignored by git.

## Troubleshooting

| Problem | Fix |
|---|---|
| `claude -p failed` | Run `claude -p "say hi"` in a terminal. If it fails, log in again with `claude` |
| `claude: command not found` | Install Claude Code and make sure it is on your `PATH` |
| `Chrome not found` in Audit | Install Chrome or set `J2_CHROME` |
| Port 8773 in use | Add `--port 8780` |
| Run is in mock mode, or saved to a temporary folder | An earlier `export STUDIO_MOCK=1` or `export J2_RUNS_DIR=...` is still set in that Terminal window. Run `unset STUDIO_MOCK J2_RUNS_DIR`, or open a new window |
