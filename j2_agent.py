"""Agent view (agent/1): who one agent talked to and how it decided, read from a run's own chat.jsonl and calls.jsonl.

view(run_dir, who) returns its summary, its conversations grouped by counterpart and one card per AI call (what it was given,
its stated reason, its reply). Read-only, code only; nothing new is captured. The page turns ids into names (personas, workflow
short names) and every response goes through the server's redact().
"""
import json
import os
import re

TECH_MAX = 40_000      # prompt, system text and raw output are kept for "Show technical details", cut to this many characters
FUNCS = ("identity", "adaptation", "priority", "coordination", "audit", "validator")
MENTION = re.compile(r"^@(Requester|User|Identity|Adaptation|Priority|Coordination|Audit|Validator|W-\d+)\b", re.I)


def _jsonl(d, name):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []


def _read(d, name, default=None):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def messages(d):
    """The chat's messages (the meta line left out)."""
    return [m for m in _jsonl(d, "chat.jsonl") if not m.get("meta") and m.get("who")]


def recipients(m):
    """Who a message was for, from what the chat recorded: next, audience, to_user, and an @name it starts with."""
    out = []
    for k in (m.get("next"), m.get("audience")):
        if k:
            out.append(str(k))
    if m.get("to_user"):
        out.append("user")
    hit = MENTION.match(str(m.get("text") or ""))
    if hit:
        n = hit.group(1)
        out.append("user" if n.lower() in ("requester", "user") else n if n.upper().startswith("W-") else n.lower())
    return [x for x in dict.fromkeys(out) if x != m.get("who")]


def _short(v, n=600):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n - 1] + "…"


def _reply(c):
    """The reply as sentences and labelled lines: to_requester and say as text; other short fields as lines; long ones by size."""
    r, rest = c.get("reply"), ""
    if not isinstance(r, dict):      # a builder's reply: a JSON record, then the code it wrote
        raw = str(c.get("raw") or "")
        try:
            r, end = json.JSONDecoder().raw_decode(raw[raw.index("{"):]) if "{" in raw else (None, 0)
            rest = raw[raw.index("{") + end:].strip()
        except ValueError:
            r = None
    if not isinstance(r, dict):
        return {"text": [], "fields": [], "reason": None, "note": "the reply was not a record (see technical details)" if c.get("raw") else "no reply recorded"}
    text = [str(r[k]) for k in ("to_requester", "say", "human_output") if isinstance(r.get(k), str) and r[k].strip()]
    fields = []
    for k, v in r.items():
        if k in ("to_requester", "say", "human_output", "reason") or v in (None, "", [], {}):
            continue
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        fields.append([k, s if len(s) <= 400 else f"{len(s):,} characters (in the technical details)"])
    return {"text": text, "fields": fields, "reason": r.get("reason") if isinstance(r.get("reason"), str) else None, "note": f"and {len(rest):,} characters of code (in the technical details)" if rest else None}


def load(d):
    """The run's records the view reads, once: (chat messages, AI calls, workflow short names)."""
    return (messages(d), [c for c in _jsonl(d, "calls.jsonl") if not c.get("extra")],
            {w["id"]: w.get("name") or w["id"] for w in _read(d, "workflows.json", []) or [] if isinstance(w, dict) and w.get("id")})


def view(d, who, loaded=None):
    """agent/1 for one agent (a function id, or a workflow id W-n) in a run folder. loaded: load(d), to reuse."""
    who = str(who or "")
    if not d or not os.path.isdir(d) or not who:
        return {"schema": "agent/1", "who": who, "found": False}
    chat, every, names = loaded or load(d)
    calls = [c for c in every if str(c.get("fn")) == who]
    groups, order = {}, []
    for m in chat:
        to = recipients(m)
        if m["who"] == who:
            peers = to or [None]      # posted with no one named: its own group
        elif who in to:
            peers = [m["who"]]
        else:
            continue
        for p in peers:
            if p not in groups:
                groups[p] = []
                order.append(p)
            groups[p].append({"id": m.get("id"), "t": m.get("t"), "step": m.get("step"), "from": m["who"], "to": to,
                              "text": str(m.get("text") or ""), "sent": m["who"] == who})
    talks = [{"with": p, "count": len(groups[p]), "messages": groups[p]} for p in order]
    thinking = []
    for c in calls:
        rep = _reply(c)
        thinking.append({"id": c.get("id"), "step": c.get("step"), "cycle": c.get("cycle"), "t": c.get("t"), "seconds": c.get("seconds"),
                         "model": c.get("model"), "tokens": c.get("tokens"), "atom": c.get("atom"),
                         "given": [[str(x[0]), _short(x[1])] for x in (c.get("inputs") or []) if isinstance(x, (list, tuple)) and len(x) == 2],
                         "reason": c.get("reason") or rep["reason"], "reply": rep,
                         "technical": {k: (str(c.get(k) or "")[:TECH_MAX]) for k in ("system", "prompt", "raw")}})
    busiest = max(talks, key=lambda g: g["count"]) if talks else None
    models = sorted({c.get("model") for c in calls if c.get("model")})
    tok = {"input": sum(int((c.get("tokens") or {}).get("input") or 0) for c in calls),
           "output": sum(int((c.get("tokens") or {}).get("output") or 0) for c in calls)}
    return {"schema": "agent/1", "who": who, "found": bool(calls or talks), "names": names,
            "summary": {"calls": len(calls), "seconds": round(sum(float(c.get("seconds") or 0) for c in calls), 1), "models": models,
                        "tokens": tok, "messages": sum(1 for m in chat if m["who"] == who),
                        "most": {"with": busiest["with"], "count": busiest["count"]} if busiest else None},
            "conversations": talks, "thinking": thinking}
