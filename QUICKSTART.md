# J2: quick start (new UI)

J2 is a team of AI agents that plans, builds and checks a website, or PRD / HLD / LLD documents, from a short brief.
This branch (`revamp`) adds the new UI: a live map of the team at work, and words only when you're needed.

## What you need

- macOS or Linux with Python 3.9+.
- **Claude Code CLI, logged in** (`claude`, then sign in). Every agent call goes through `claude -p` on your own
  subscription, so there's no API key.
- Google Chrome. It's used to check the built page.

## Install (once)

```bash
git clone https://github.com/Devanshindian/J2_Prototype.git
cd J2_Prototype
git checkout revamp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
claude -p "say hi"          # should print a reply; if not, run `claude` and log in
```

## Run

```bash
STUDIO_PROVIDER=claude-cli .venv/bin/python j2_server.py
```

This opens http://127.0.0.1:8773.

1. Type what you want made: a website, a PRD, or "design docs and a website".
2. Approve the plan. Pick a model there: Fable (best), Opus, Sonnet (default) or Haiku (cheapest).
3. Watch the map:
   - **Houses** are parts of the work, and they fill up as they're built.
   - **Tap a house** to see what it's doing, or its output once it's done.
   - **Hold and slide** to see the team talking.
   - **Chat** and **Result** are at the top right.
4. **"Decide for me"** (top bar) makes the team decide everything itself, up to a usage cap.

## Good to know

- **Usage:** a run uses roughly 1 to 4M tokens of your Claude usage. Opus and Fable cost more than Sonnet.
- **Free demo:** `STUDIO_MOCK=1 .venv/bin/python j2_server.py --port 8799` runs it with sample data and no Claude
  calls. Open http://127.0.0.1:8799/?fixture=working.
- **Old detailed view:** http://127.0.0.1:8773/legacy
- **More detail:** settings are in `SETUP.md`, and how it works is in `README.md`.
