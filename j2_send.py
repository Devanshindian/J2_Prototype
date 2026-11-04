"""Send deeds: a test email and a test Slack message built by code from a finished document, and milestone emails.

A send is dry-run (the default: nothing leaves, the deed stays open), mock (an in-process recorder, for tests) or live
(J2_SEND_MODE=live: email only, by SMTP with STARTTLS, after the Requester said yes once in the run). The recipient comes
only from J2_TEST_EMAIL and J2_TEST_SLACK_TARGET, never from the brief, and allowed() refuses anything else. Each email has
a key (run, atom, goal) and is never sent twice; at most J2_SEND_CAP (default 10) go out live per run. Receipts hold a
masked recipient, hashes, the SMTP code and an error class: never an address in full, a secret or the server's own text.
SMTP settings are read only from the environment (J2_SMTP_HOST, _PORT, _USER, _PASSWORD, _FROM).
Whether a brief asks for a send or for milestone updates is the output classifier's reading of the message (j2.py
_classify_output, agents/j2/output-classifier.md), never keyword matching here.
"""
import hashlib
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage

DEEDS = {"send_email": {"channel": "email", "var": "J2_TEST_EMAIL", "words": "test email", "label": "Send a test email"},
         "send_slack_message": {"channel": "slack", "var": "J2_TEST_SLACK_TARGET", "words": "test Slack message",
                                "label": "Send a test Slack message"},
         # a milestone email: code sends one when a goal of the run is reached (j2.py _milestone), never asked for by name
         "milestone_email": {"channel": "email", "var": "J2_TEST_EMAIL", "words": "milestone email", "label": "Email"}}
TARGET_VAR = {d["channel"]: d["var"] for d in DEEDS.values()}
MODES = ("dry-run", "mock", "live")      # any other J2_SEND_MODE falls back to dry-run
SMTP_VARS = ("J2_SMTP_HOST", "J2_SMTP_PORT", "J2_SMTP_USER", "J2_SMTP_PASSWORD", "J2_SMTP_FROM")
WHY = {"auth": "the SMTP server did not accept the login", "connection": "could not reach the SMTP server",
       "refused": "the SMTP server refused the message", "smtp": "the SMTP server returned an error",
       "duplicate": "this email was already sent in this run"}      # plain words by code: never the server's own text
SENT = []      # the mock recorder: every message a mock send "delivered" (tests read it; reset() empties it)

_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SLACK_TARGET = re.compile(r"(?<![\w@])([#@][\w.-]+)")


def clip(text, n=200):
    """At most n characters, never cut mid-word: the last full sentence that fits, else the last whole word and "..."."""
    text = str(text or "").strip()
    if len(text) <= n:
        return text
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text[:n + 1])]
    if ends:
        return text[:ends[-1]]
    cut = text[:n - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "..."


def milestone(project, goal, version, checks, summary):
    """{subject, body} of a milestone email, by code from the run's own record: no link, no address, no model."""
    clean = lambda t: re.sub(r"\s+", " ", _ADDRESS.sub("[address]", re.sub(r"https?://\S+|www\.\S+", "[link]", str(t or "")))).strip()
    body = [f"Goal: {goal} done", f"Version: {version if version is not None else 'not recorded'}",
            f"Checks passed: {checks[0]} of {checks[1]}" if checks[1] else "Checks passed: none recorded",
            f"Summary: {clip(clean(summary)) or 'not recorded'}"]
    return {"subject": f"J2 · {clean(project)} · {goal} done", "body": "\n".join(body)}


def mode():
    m = os.getenv("J2_SEND_MODE", "dry-run").strip().lower()
    return m if m in MODES else "dry-run"


def cap():
    try:
        return max(int(os.getenv("J2_SEND_CAP", "10")), 0)
    except ValueError:
        return 10


def tls_context():
    """The certificate check for STARTTLS (the tests' fake server swaps in its own certificate here)."""
    return ssl.create_default_context()


def smtp_send(msg):
    """One email by SMTP: STARTTLS, login, send, 20 s timeout. {sent, code, error, why}: error is a class only (settings,
    auth, connection, refused, smtp) and why is code's plain words, never a setting's value or the server's text."""
    missing = [v for v in SMTP_VARS if not os.getenv(v, "").strip()]
    if missing:
        return {"sent": False, "code": None, "error": "settings", "why": f"{', '.join(missing)} not set, so nothing is sent"}
    env = {v: os.getenv(v).strip() for v in SMTP_VARS}
    if not env["J2_SMTP_PORT"].isdigit():
        return {"sent": False, "code": None, "error": "settings", "why": "J2_SMTP_PORT is not a number, so nothing is sent"}
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = env["J2_SMTP_FROM"], msg["to"], msg.get("subject") or "J2"
    m.set_content(msg["body"])
    try:
        with smtplib.SMTP(env["J2_SMTP_HOST"], int(env["J2_SMTP_PORT"]), timeout=20) as s:
            s.starttls(context=tls_context())
            s.login(env["J2_SMTP_USER"], env["J2_SMTP_PASSWORD"])
            s.send_message(m)      # raises unless the server answered 250 to the message
        return {"sent": True, "code": 250, "error": None, "why": None}
    except smtplib.SMTPAuthenticationError as e:
        err, code = "auth", e.smtp_code
    except smtplib.SMTPRecipientsRefused as e:
        err, code = "refused", next((c for c, _ in e.recipients.values()), None)
    except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
        err, code = "refused", e.smtp_code
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ssl.SSLError) as e:
        err, code = "connection", getattr(e, "smtp_code", None)
    except smtplib.SMTPException as e:
        err, code = "smtp", getattr(e, "smtp_code", None)
    except OSError:      # refused, unreachable, timed out
        err, code = "connection", None
    return {"sent": False, "code": code, "error": err, "why": WHY[err]}


def records(run_dir):
    """Every send record in a run's receipts.jsonl (the memory of what was sent, so a retried or resumed run never resends)."""
    path = os.path.join(run_dir or "", "receipts.jsonl")
    if not run_dir or not os.path.exists(path):
        return []
    return [r for r in (json.loads(x) for x in open(path, encoding="utf-8") if x.strip()) if r.get("type") == "deed-send-record"]


def digest(s):
    return hashlib.sha256(str(s).encode("utf-8")).hexdigest()


def mask(to):
    """Enough to recognise the target, not enough to use it: d***@testlify.com, #t***."""
    to = str(to or "")
    local, at, domain = to.partition("@") if "@" in to[1:] else (to, "", "")
    return f"{local[:1]}***{at}{domain}" if at else f"{to[:2]}***"


def target(channel):
    """The one configured test target of a channel; "" when its variable is not set."""
    return (os.getenv(TARGET_VAR.get(channel, ""), "") or "").strip()


def allowed(channel, to):
    """(ok, reason): True only when `to` is the one configured test target. Everything is refused when the variable is
    unset. One recipient: no list, no cc or bcc, no CR or LF. Reasons name variables, never values."""
    var = TARGET_VAR.get(channel)
    if not var:
        return False, f"unknown channel {channel!r}"
    want = target(channel)
    if not want:
        return False, f"{var} is not set, so nothing is sent"
    if not isinstance(to, str):
        return False, "exactly one recipient is allowed"
    if re.search(r"[\r\n]", to):
        return False, "the recipient has a line break"
    to = to.strip()
    if re.search(r"[\s,;]", to):
        return False, "exactly one recipient is allowed"
    if to.lower() != want.lower():
        return False, f"the recipient is not the one in {var}"
    return True, ""


def names_other(kind, *texts):
    """True when the brief names a recipient other than the configured test target (an address, or a Slack channel or
    person). The brief never chooses the recipient; code uses this only to tell the Requester."""
    text = " ".join(str(t or "") for t in texts)
    want = target(DEEDS[kind]["channel"]).lower().lstrip("#@")
    named = _ADDRESS.findall(text) if kind == "send_email" else [m.lstrip("#@") for m in _SLACK_TARGET.findall(text)]
    return any(n.lower().lstrip("#@") != want for n in named)


def build(kind, name, text):
    """{subject, body} for a finished document, by code: its file name, hash and section headings. No model writes it."""
    heads = [m.group(1).strip() for m in re.finditer(r"^#{2}\s+(.+?)\s*#*\s*$", text, re.M)]
    lines = [f"J2 test send: {name} is ready.", f"File: {name} (sha256 {digest(text)[:12]})",
             "Sections: " + (", ".join(heads) if heads else "none")]
    if kind == "send_email":
        return {"subject": f"J2 test: {name}", "body": "\n".join(lines)}
    return {"subject": None, "body": " | ".join(lines)}


def deliver(msg, how=None):
    """Refuses a recipient that is not the configured test target, here as the last guard, then sends by `how` (the mode;
    live is email only, a Slack send stays dry-run). Returns {sent, result, refused, code, error, why}."""
    how = how or mode()
    out = {"sent": False, "result": "refused", "refused": None, "code": None, "error": None, "why": None}
    ok, why = allowed(msg.get("channel"), msg.get("to"))
    if not ok:
        return {**out, "refused": why}
    if set(msg) - {"channel", "to", "subject", "body"}:
        return {**out, "refused": "only channel, to, subject and body are allowed (no cc or bcc)"}
    if how == "mock":
        SENT.append(dict(msg))
        return {**out, "sent": True, "result": "mock"}
    if how == "live" and msg["channel"] == "email":
        r = smtp_send(msg)
        return {**out, **r, "result": "sent" if r["sent"] else "failed"}
    return {**out, "result": "dry-run"}


def send(kind, name, text, artifact=None, built=None, run_dir=None, key=None, confirmed=False):
    """Build the message, send it to the configured target, and return the receipt record. The recipient is read from the
    environment here and nowhere else. built: {subject, body} made by the caller (a milestone). Live only when the Requester
    said yes (confirmed), else dry-run. key (run, atom, goal): never sent twice; live sends stop at cap()."""
    ch = DEEDS[kind]["channel"]
    msg = {"channel": ch, "to": target(ch), **(built or build(kind, name, text))}
    how = mode() if mode() != "live" or confirmed else "dry-run"
    if ch != "email" and how == "live":
        how = "dry-run"
    past = records(run_dir)
    if key and any(r.get("key") == key and r.get("sent") for r in past):
        res = {"sent": False, "result": "skipped", "refused": None, "code": None, "error": "duplicate", "why": WHY["duplicate"]}
    elif how == "live" and sum(1 for r in past if r.get("mode") == "live" and r.get("sent")) >= cap():
        res = {"sent": False, "result": "skipped", "refused": None, "code": None, "error": "cap",
               "why": f"the cap of {cap()} live emails for this run is reached (J2_SEND_CAP)"}
    else:
        res = deliver(msg, how)
    return {"deed": kind, "channel": ch, "mode": how, "key": key, "to_masked": mask(msg["to"]) if msg["to"] else None,
            "to_hash": digest(msg["to"].lower())[:16] if msg["to"] else None, "subject": msg["subject"],
            "body_sha256": digest(msg["body"]), "body_chars": len(msg["body"]), "artifact": artifact,
            "artifact_sha256": digest(text), "transport": {"mock": "mock-recorder", "sent": "smtp", "failed": "smtp"}.get(res["result"]),
            "sent": res["sent"], "result": res["result"], "refused": res["refused"], "smtp_code": res["code"],
            "error": res["error"], "why": res["why"]}


def read_record(run_dir, atom_id):
    """The latest send record of an atom in receipts.jsonl, or None."""
    return next((r for r in reversed(records(run_dir)) if r.get("atom") == atom_id), None)


def check(c, run_dir):
    """{actual, pass, evidence} for a deed-send check. It only reads: the record in receipts.jsonl and the artifact on
    disk. It never sends. pass None = not sent, and the atom stays open: a dry run, or a live send that failed or was
    skipped (the reason is the evidence)."""
    rec = read_record(run_dir, c.get("atom"))
    if not rec:
        return {"actual": None, "pass": False, "evidence": "no send receipt in receipts.jsonl"}
    if rec.get("refused"):
        return {"actual": rec.get("result"), "pass": False, "evidence": f"not sent: {rec['refused']}"}
    if rec.get("error") == "duplicate":
        return {"actual": rec.get("result"), "pass": True, "evidence": f"already sent to {rec['to_masked']}; not sent again"}
    if rec.get("error"):
        return {"actual": rec.get("result"), "pass": None,
                "evidence": f"{'Skipped' if rec.get('result') == 'skipped' else 'Failed'} ({rec['error']}): {rec['why']}"}
    kind, art = rec.get("deed"), rec.get("artifact")
    path = os.path.join(run_dir, art or "")
    if kind not in DEEDS or not art or not os.path.isfile(path):
        return {"actual": None, "pass": False, "evidence": "the receipt does not name a document that exists"}
    text = open(path, encoding="utf-8").read()
    body_ok = kind == "milestone_email" or digest(build(kind, art, text)["body"]) == rec.get("body_sha256")      # a milestone's body is built from the run record, not the file alone
    if digest(text) != rec.get("artifact_sha256") or not body_ok:
        return {"actual": None, "pass": False, "evidence": f"{art} changed since the receipt was written"}
    want = target(rec.get("channel"))
    if not want or digest(want.lower())[:16] != rec.get("to_hash"):
        return {"actual": None, "pass": False, "evidence": f"the receipt's recipient is not the one in {TARGET_VAR[rec['channel']]}"}
    if rec.get("mode") == "dry-run" or not rec.get("sent"):
        return {"actual": rec.get("result"), "pass": None, "evidence": "Not sent (dry run)"}
    if rec.get("mode") == "live":
        return {"actual": rec.get("result"), "pass": True, "evidence": f"Sent by SMTP to {rec['to_masked']} (code "
                f"{rec.get('smtp_code')}, {rec['body_chars']} characters)"}
    return {"actual": rec.get("result"), "pass": True,
            "evidence": f"{rec['result']} send recorded to {rec['to_masked']} ({rec['body_chars']} characters)"}
