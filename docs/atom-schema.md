# atom/1: the work atom schema

One standard shape for a work atom. `j2_schema.atom_view(atom)` builds it from a stored atom; nothing stored is renamed.
`runs/<id>/atoms.json` holds the views at the end of a run: `{"schema": "atom/1", "atoms": [...], "warnings": [...]}`.
The machine form is `docs/atom-schema.json`.

## Fields

| Field | Meaning | Comes from today's atom |
|---|---|---|
| id, workflow, name, owner, status, attempt | who and where | id, workflow id, workflow name, how.agent, status (see Status), attempts |
| goal, how, constraints, context | what it was asked | same names |
| defined_output | what must exist when it is done | expected_output |
| verification | list of `{check, applies_to, method, met, evidence}` | results (the receipts) |
| output | list of `{verb, name, form, ref}` | agent_output, receipts |
| depends_on, used_by | lists of `{atom, why}` | recorded by the run (see Edges) |
| notes | plain words, 1 to 2 sentences | human_output |
| details | optional free object, specific to the output | agent_output (selectors, ids, anchor), expected_output (elements) |

Website words (selectors, elements, sections) are never standard fields: they live in `details`.

## Status

Exactly four values: `open`, `closed`, `verify_failed`, `abandoned`.

| Today's name | Value | Note |
|---|---|---|
| atom `passed` | closed | clean |
| atom `escalated` | verify_failed | clean |
| atom `failed`, workflow not running or 3 attempts used | verify_failed | `failed` is also written after an attempt that will be retried, so it is only final by the workflow status or the attempt count |
| atom `failed`, workflow `running`, under 3 attempts | open | retry in progress |
| no status yet | open | clean while the run is live |
| no status yet, run ended, workflow not `done` (registered, held, running) | abandoned | clean: never built |
| no status yet, workflow `unfunded` | abandoned | clean |
| no status yet, workflow `done` | open | does not map cleanly: stored before atoms had a status; kept open, not forced |
| atom `could not run` | open | does not map cleanly: the check had no browser; it is neither failed nor verified |
| workflow `registered`, `held`, `running`, `done`, `failed`, `unfunded` | not an atom status | used only to decide the atom's value above |

Dropped or left-out items have no atom status of their own: an atom of a workflow the run never built is `abandoned` once
the run has ended.

## Output items: verb, name, form, ref

Each item is `{verb, name, form, ref}`.

- `verb`: `make` (gives an artifact) or `do` (gives a deed). The noun follows from the verb; it is not stored.
- `form`: open-ended; unknown forms are recorded, never rejected. Makes start from `doc`, `code`, `page`, `test`, `plan`,
  `skill`, `app`. Dos: `behaviour`, `fetch`, `send`. A built website section is make, form `page`, ref its anchor
  (`site/index.html#hero`); PRD, HLD and LLD are make, form `doc`, ref file and heading (`prd.md#Problem`). Their files use
  the same forms by extension (`.md`, `.docx` are `doc`, `.html` is `page`). There is no `section` form.
- `ref`: a file path, a section anchor, a document heading or a receipt id (`W-3.a1:1`, atom and attempt in `receipts.jsonl`).
- An atom may hold several items of either verb (for example one make and three do). Atoms are not split. The atom's kind is
  derived by code (`make`, `do` or `mixed`) and never stored. A mixed atom is valid; it shows "mixed" on its card and gets
  an informational warning in `atoms.json`.
- A deed's `details.scope` is `self` (it acts only on the thing built) or `external` (it reaches outside).

## Checks by verb

Each check names the output item it is about in `applies_to`.

| Verb | Check | Meaning | Produced today |
|---|---|---|---|
| make | exists | the thing is there | yes (element-count, heading-present, section-not-empty, file-exists, grep-count) |
| make | valid | it breaks no rule | yes (named-test, tap-targets, ids-unique) |
| make | meets the defined output | it is what "done when" asked | yes (facts-present, lld-slice) |
| do | receipt | a receipt exists and shows success; evidence is the receipt id from `receipts.jsonl` | yes, for behaviour steps run in Chrome or by the fake driver (scope self) |
| do, scope external | receipt | the same, for fetching data or sending | send: yes, in test mode only (see Send deeds); fetch: defined, nothing produces it yet |

## Send deeds (test mode, phase 1)

`send_email` and `send_slack_message` are do items of form `send`, scope `external`, one atom each, built by code after the
documents (no charter, plan, builder or audit; no model writes the message). The brief only triggers them (a send verb
near "email" or "Slack"). The recipient comes only from `J2_TEST_EMAIL` and `J2_TEST_SLACK_TARGET`; anything else is
refused and a brief that names another recipient is told so. The one check, `deed-send`, reads the send receipt in
`receipts.jsonl` (masked recipient and hash, body and document hashes, mode, no secret) and never sends.

| `J2_SEND_MODE` | What happens | Check | Atom |
|---|---|---|---|
| `dry-run` (default) | nothing is sent; note "Not sent (dry run)" | does not pass (could not run) | open |
| `mock` | one message goes to an in-process recorder, nothing leaves the machine | passes | closed |
| `live`, sent | one email by SMTP (STARTTLS) to the test address; note "Sent to your test address (m***@...)" | passes | closed |
| `live`, not sent | SMTP settings missing, auth, connection or refused, or over `J2_SEND_CAP`; note "Not sent: <why>" | does not pass (could not run) | open |
| `live`, the Requester said No | every send of the run stays a dry run | does not pass (could not run) | open |
| target unset or refused | nothing is sent | fails | verify_failed |

Live mode asks the Requester once a run, before the first email. An email's key (run id, atom id, goal) is in its
receipt; a key already sent is never sent again. A Slack webhook is not built yet: a Slack send stays a dry run.
Price: `rates_deed` in `agents/j2/rates.json` (placeholder, 5 each; `J2_RATES=0` makes it free), funded by the stage gate.

## Edges

`depends_on` is recorded from what the builder's prompt actually held, where the prompt is made:

- the manifest lines of other atoms (J2_SLIM=1): one edge per atom listed;
- an LLD slice: the LLD atoms that wrote the slice's sections, elements and fields;
- the HLD component summary: the HLD Components atoms;
- a document builder's charter: the PRD Requirements atoms (HLD, LLD), the HLD Components atoms (LLD).

`used_by` is the same edges from the other side, built by code. When a builder was given the whole page and no edge can
be attributed, edges come from the workflow's declared dependencies; if it has none, they stay empty. Edges are never
guessed. Runs stored before this schema have no record of what a prompt held, so only declared dependencies apply.

## Warnings (never change an outcome, a prompt or a retry)

An edge to a missing atom; a cycle; an atom whose output is never used and is not a final output (forms `page`,
`doc`, `send`); an output item without a verb.
