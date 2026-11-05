"""The v2 page's data (/api/v2/state, api-contract.md in j2-revamp/): one honest status, usage, the open decision, the
chat (only the user and the team's one voice), the backstage (the agents' own messages, in plain words), the plan and
the deliverables. Built by code from a live J2Run or a saved run folder; no model call.
"""
import datetime
import json
import os
import re

import j2
import j2_usage

VOCAB = {"identity": "Client lead", "adaptation": "Planner", "priority": "Budget lead", "validator": "Gatekeeper",
         "coordination": "Scheduler", "audit": "Quality check", "system": "Checks", "user": "You",
         "realization-adaptation": "Planner", "realization-judge": "Plan reviewer"}
STATUS = {"running": "working", "waiting_on_you": "needs_you", "done": "done", "done_with_open_items": "done_open",
          "stopped": "stopped", "paused": "stopped", "crashed": "crashed", "saved": "stopped"}
# The kingdom view (/api/v2/map): the agents as units with a role each, the departments as villages.
ROLES = {"identity": "client", "adaptation": "planner", "priority": "budget", "validator": "gatekeeper",
         "coordination": "scheduler", "audit": "quality", "realization-judge": "reviewer", "realization-adaptation": "planner"}
CORE_UNITS = ("identity", "adaptation", "priority", "validator", "coordination", "audit")
MAP_FLOWS = 24          # the newest hand-offs the map route returns
ENDED = ("done", "done_open", "stopped", "crashed")
LABELS = {"website": "Website", "prd": "PRD", "hld": "HLD", "lld": "LLD"}
GROUPS = {"build": "Building", "product": "Planning", "design": "Design", "content": "Content", "engineering": "Planning",
          "prd": "Product requirements", "hld": "High-level design", "lld": "Low-level design", "website": "Building"}
DOING = {"identity": "Reading your request", "adaptation": "Planning the work", "priority": "Agreeing the usage",
         "coordination": "Scheduling the work", "audit": "Checking the result", "validator": "Checking the plan",
         # the helper calls (run.thinking names them while they run): never the bare "Working" for minutes
         "design-research": "Studying sites like yours", "style-directions": "Drawing three looks for you",
         "realization-adaptation": "Planning the work", "realization-judge": "Checking the plan",
         "work-order-review": "Checking the plan", "check-judge": "Checking the result",
         "quality-judge": "Checking the result", "condition-double-check": "Checking the result",
         "output-classifier": "Reading your request", "reviewer": "Writing up the run"}
# Who is working, named, for the top bar's status ("Planner is planning the parts"). The helper calls (run.thinking
# names them while they run) belong to the manager whose step they serve; the map lights that manager's token.
HELPER_UNIT = {"realization-adaptation": "adaptation", "realization-judge": "adaptation", "design-research": "adaptation",
               "style-directions": "adaptation", "work-order-review": "validator", "check-judge": "audit",
               "quality-judge": "audit", "condition-double-check": "audit", "output-classifier": "identity",
               "reviewer": "identity"}
NAMED_DOING = {"identity": "is reading your request", "adaptation": "is planning the parts",
               "priority": "is agreeing the usage", "coordination": "is scheduling the work",
               "validator": "is checking the plan", "audit": "is reviewing the {noun}",
               "design-research": "is studying sites like yours", "style-directions": "is drawing three looks for you",
               "realization-judge": "is checking the plan", "work-order-review": "is checking the work orders",
               "output-classifier": "is reading your request", "reviewer": "is writing up the run"}


def named_doing(fn, kind="website"):
    """The top bar's line for a manager at work: its name and what it is doing, e.g. "Quality check is reviewing the
    page". A helper call is named for the manager it serves."""
    unit = HELPER_UNIT.get(fn, fn)
    if unit not in VOCAB:
        return DOING.get(fn, "Working")
    what = NAMED_DOING.get(fn) or NAMED_DOING.get(unit) or "is working"
    return f"{VOCAB[unit]} {what.format(noun='page' if kind == 'website' else 'document')}"


CODES = re.compile(r"\s*\((?:[^()]*\b(?:[FRCPNHLQD]-?\d+|J2\.[a-h])\b[^()]*)\)|\bJ2\.[a-h]\b:?\s*|"
                   r"\b(?:[FRCQD]-\d+(?:\.a\d+)?|[PNHL]\d{1,2})\b")
# The internal words a person never reads in the chat or the backstage (api-contract.md), as plain words.
INTERNAL = ((r"\bwork atoms?\b", "task"), (r"\batoms?\b", "task"), (r"\benvelopes?\b", "usage share"),
            (r"(^|[.!?]\s+)Charter\b", r"\1The brief"), (r"\bthe charter'?s\b", "the brief's"), (r"\bcharters?\b", "brief"),
            (r"\bworkflow agents?\b", "builders"), (r"\bworkflows\b", "parts"), (r"\bworkflow\b", "part"),
            (r"\b(?:the )?Requester'?s\b", "your"), (r"\b(?:the )?Requester(?: \(you\))?\b", "you"),
            (r"\bJ2 routes?\b", "team rule"), (r"(?<![.#\w-])J2\b(?![-\w])", "the team"),   # never inside ".j2-nav"
            (r"\brate[- ]card\b", "usual usage"),
            (r"\s*Saved L-[\d-]+(?:, L-[\d-]+)* to memory\.", " Saved a lesson for next time."),
            (r"\s*Saved P-[\d-]+ \(([^)]*)\)\.", r" Kept for the next \1 run."),
            (r"\bUsing lesson L-[\d-]+:", "Using a lesson from an earlier run:"),
            (r"\bUsing playbook P-[\d-]+(?: \(([^)]*)\))?", lambda m: f"Using what an earlier {m[1] or 'similar'} run taught"),
            (r"^Exported (\w+)\.docx from \w+\.md\.", lambda m: f"Exported the {m[1].upper()} as a Word file too."))
TOKENS = re.compile(r"\b(\d{4,})\s*tokens?\b", re.I)
PAIR = re.compile(r"\b(\d{5,})\s*/\s*(\d{5,})\b")          # spent/budget in tokens
BARE = re.compile(r"\b(\d{5,})(?= of \d)|(?<=share now )(\d{5,})\b")                    # "47896 of 12k usage": the first amount, short too
YOU_VERB = re.compile(r"\byou (has|is|was|decides|answers|asks|says|wants|knows|needs|chooses|picks|adds|approves|"
                      r"confirms|gives|sends|keeps|drops|accepts)\b")
YOU_FIX = {"has": "have", "is": "are", "was": "were"}
AT = re.compile(r"^\s*@[\w-]+(?:\s+Builder)?[,:]?\s*")


def who_name(fn, names):
    """The vocabulary name of an agent: Client lead, Planner, ..., or "Builder · {task name}"."""
    if j2.is_wf_agent(fn):
        return f"Builder · {names.get(fn) or 'a part'}"
    return VOCAB.get(str(fn), str(fn).replace("-", " ").capitalize() if fn else "")


def plain_task(text):
    """A workflow name or purpose in plain words: no ids or codes, first sentence, short."""
    t = CODES.sub("", j2.pretty_name(text)).strip(" .:-")
    t = re.sub(r"^(?:Fix|Revise)\s+(?:item\s+)?(?:W-\d+\s*)?", lambda m: m.group(0).split()[0] + " ", t).strip()
    t = re.sub(r"\s+", " ", t)
    t = re.split(r"(?<=[.!?])\s", t)[0]
    return (t[:117].rsplit(" ", 1)[0] + "…") if len(t) > 120 else t


NAME_VERB = re.compile(r"^(?:Build|Design)\s+(?:the\s+)?(?=\S)", re.I)


def plain_name(text):
    """A part's name as a person reads it, the same in the plan, the map and the details: plain_task, then a leading
    "Build " / "Design " goes when what is left still names the thing (two words or more), "call to action" reads
    "button", "nav" reads "navigation" and "and" reads "&". "build_page_shell_and_nav" reads "Page shell & navigation"."""
    t = plain_task(text)
    rest = NAME_VERB.sub("", t)
    if rest != t and len(rest.split()) >= 2:
        t = rest[:1].upper() + rest[1:]
    t = re.sub(r"\bcall to action\b", "button", t, flags=re.I)
    t = re.sub(r"\bnav\b", "navigation", t, flags=re.I)
    return re.sub(r"\s+and\s+", " & ", t)


def plain_words(text, names):
    """Text in plain words, whole: tags and codes out, ids as task names, the functions by their vocabulary names,
    no internal words (credits, atom, envelope, charter, done-when, workflow), amounts as usage."""
    t = AT.sub("", str(text or ""))
    t = re.sub(r"(?m)^\s*@[\w-]+(?:\s+Builder)?[,:]?\s*", "", t)
    t = re.sub(r"\bW-\d+(?:\.a\d+)?\b(?:\s+Builder)?", lambda m: names.get(m.group(0).split()[0].split(".")[0]) or
               "a part", t)
    for fn, name in VOCAB.items():
        if fn in j2.NAMES and fn not in ("user", "system"):
            t = re.sub(rf"\b{j2.NAMES[fn]}\b", name, t)
    t = j2.pretty_name(t)                  # "W-1 plan_page_content" reads "Plan page content Plan page content" ...
    t = re.sub(r"\b([A-Z][\w&':, -]{2,60}?) \1\b", r"\1", t)       # ... and "Booking form Booking form" reads once
    t = CODES.sub("", t)
    t = PAIR.sub(lambda m: f"{j2_usage.short(int(m[1]))} of {j2_usage.short(int(m[2]))}", t)
    t = TOKENS.sub(lambda m: f"{j2_usage.short(int(m[1]))} usage", t)
    t = BARE.sub(lambda m: j2_usage.short(int(m[1] or m[2])), t)
    for pat, rep_ in j2.PLAIN_WORDS + INTERNAL:
        t = re.sub(pat, rep_, t, flags=re.I)
    t = YOU_VERB.sub(lambda m: "you " + YOU_FIX.get(m[1], m[1][:-1]), t)
    t = re.sub(r"\s+(?:on|with|about|for|to)\s*:", ":", t)          # a code removed before a colon
    t = re.sub(r":\s*:", ":", re.sub(r"\(\s*\)", "", t))
    t = re.sub(r"\s+([,;:.])", r"\1", t)
    t = re.sub(r"(^|[.!?:]\s+)you\b", lambda m: m[1] + "You", t)
    t = re.sub(r"((?:^|[!?]|(?<!\be\.g)(?<!\bi\.e)\.)\s+)([a-z])", lambda m: m[1] + m[2].upper(), t)   # a sentence starts upper
    t = j2.pretty_name(t)                                            # a model's snake_case part names, as words
    return scrub(re.sub(r"[ \t]+", " ", t).strip())


# What a person never reads in the backstage or its detail (api-contract.md): the run's file names and raw large
# numbers. A file reads as what it is ("the plan notes"); a 6-9 digit amount reads as usage ("1.6M"). A phone number
# (a + before it, or 10+ digits) is left as it is.
FILE_WORDS = {"realization": "the plan notes", "research": "the research notes", "design": "the design notes",
              "index": "the page", "prd": "the PRD", "hld": "the HLD", "lld": "the LLD", "style": "the style guide", "report": "the run report", "conditions": "the rules"}
FILE = re.compile(r"(?:\b[Tt]he site file\s+)?(?<![\w/.-])((?:[\w-]+/)*([\w-]+)(?:-v\d+)?\.(?:md|json|jsonl|html?|py|txt|css|"
                  r"js|docx))\b")
BIG = re.compile(r"(?<![\d+.,])(\d{6,9})(?![\d,]|\.\d)")


def scrub(t):
    t = re.sub(r"\s*Details in [\w./-]+\.\w+\.?", "", str(t or ""))
    t = re.sub(r"```\s*markdown block", "document block", t)
    t = FILE.sub(lambda m: ("The page file" if m.group(0)[:1] in "Tt" and m.group(0).lower().startswith("the site file")
                            else FILE_WORDS.get(m[2].lower().split("-")[0], "the run notes")), t)
    t = BIG.sub(lambda m: j2_usage.short(int(m[1])), t)
    t = re.sub(r"\busage usage\b", "usage", t)
    return t


def scrub_all(x):
    """scrub() over every string of a detail payload (a safety net: the builders below already write plain words)."""
    if isinstance(x, str):
        return scrub(x)
    if isinstance(x, list):
        return [scrub_all(v) for v in x]
    if isinstance(x, dict):
        return {k: scrub_all(v) for k, v in x.items()}
    return x


def plain_line(text, names, cap=160, sentences=2):
    """An agent's message or a system line as one short plain line (its first line, at most `sentences` sentences)."""
    t = plain_words(str(text or "").split("\n")[0], names)
    t = re.sub(r"\s+", " ", t).strip()
    parts = re.split(r"(?<=[.!?])\s", t)
    t = " ".join(parts[:sentences])
    return (t[:cap - 1].rsplit(" ", 1)[0] + "…") if len(t) > cap else t


def decided_text(reply, m, names):
    """The structured decision behind an agent's message, as one plain paragraph: its decision, verdict or ruling,
    the parts it names, Audit's findings, the order, holds, instructions. None when the message carries none."""
    r, out = reply if isinstance(reply, dict) else {}, []
    for k, label in (("decision", "Decision"), ("verdict", "Verdict"), ("ruling", "Ruling")):
        v = r.get(k) or (m.get(k) if k == "decision" else None)
        if isinstance(v, str) and v.strip():
            out.append(f"{label}: {v.replace('_', ' ').lower()}.")
    wfs = r.get("workflows") if isinstance(r.get("workflows"), list) else r.get("proposal")
    if isinstance(wfs, list) and wfs:
        nm = [plain_name(x.get("name") if isinstance(x, dict) else x) for x in wfs]
        out.append(f"Parts: {', '.join(n for n in nm if n)}.")
    if isinstance(r.get("findings"), list) and r["findings"]:
        bad = [f for f in r["findings"] if isinstance(f, dict) and not str(f.get("verdict", "")).upper().startswith("PASS")]
        out.append(f"{len(r['findings'])} findings, {len(bad)} need work" + (
            ": " + "; ".join(plain_task(f.get("criterion")) for f in bad[:4]) if bad else "") + ".")
    if isinstance(r.get("order"), list) and r["order"]:
        out.append("Order: " + ", ".join(names.get(str(i)) or "a part" for i in r["order"]) + ".")
    if isinstance(r.get("holds"), list) and r["holds"]:
        out.append(f"On hold: {', '.join(names.get(str(x.get('id'))) or 'a part' for x in r['holds'] if isinstance(x, dict))}.")
    for k in ("instruction", "instruction_to_adaptation", "answer", "clause"):
        if isinstance(r.get(k), str) and r[k].strip():
            out.append(("Rule used: " if k == "clause" else "") + r[k].strip().rstrip(".") + ".")
    if isinstance(r.get("done"), bool):
        out.append("Done." if r["done"] else "Not done yet.")
    if isinstance(r.get("enough"), bool):
        out.append("Enough to start." if r["enough"] else "More details are needed first.")
    if isinstance(r.get("approved"), bool):
        out.append("Approved." if r["approved"] else "Not approved.")
    if isinstance(r.get("false_alarm"), bool):
        out.append("A false alarm." if r["false_alarm"] else "A real problem.")
    text = plain_words(" ".join(out), names)
    return (text[:599].rsplit(" ", 1)[0] + "…") if len(text) > 600 else (text or None)


def detail_of(m, names, calls, ctx=None):
    """A backstage line's detail ("See details", api-contract.md): `kind` (plan | checks | budget | decision | generic)
    with that kind's plain fields, plus decided (the structured decision, plain) and why (the agent's own reason, plain)
    on every kind. Built by code from the run's own data (the realization plan, the parts, check results, usage); the
    agents' original text is not sent (it stays on /legacy)."""
    recs = [calls[c] for c in m.get("calls") or [] if c in calls]
    last = recs[-1] if recs else {}
    reason = last.get("reason")
    why = plain_line(reason, names, cap=400, sentences=4) if reason and reason != j2.J2Run.MOCK_REASON else None
    reply = last.get("reply") if isinstance(last.get("reply"), dict) else {}
    ctx = ctx or {}
    out = {"kind": "generic", "decided": decided_text(reply, m, names), "why": why or None}
    for fn in (plan_detail, checks_detail, budget_detail, decision_detail):
        try:
            extra = fn(m, reply, names, ctx)
        except Exception:            # a detail never breaks the state: the plain line and decided/why still go out
            extra = None
        if extra:
            out.update(extra)
            break
    return scrub_all(out)


def _sure(c):
    """The plan reviewer's confidence in plain words."""
    c = float(c or 0)
    word = "very sure" if c >= 0.9 else "fairly sure" if c >= 0.8 else "not fully sure" if c >= 0.6 else "unsure"
    return f"The plan reviewer is {word} of this plan ({round(c * 100)}%)."


def _stage_name(k):
    return GROUPS.get(str(k or ""), pretty(str(k or "Parts")))


def pretty(t):
    t = j2.pretty_name(str(t or "")).strip()
    return t[:1].upper() + t[1:]


def _registered(name, ctx):
    key = plain_name(name).lower()
    return next((w for w in ctx.get("wfs") or [] if plain_name(w.get("name")).lower() == key), None)


def _parts_payload(parts):
    """Parts grouped by stage (no usage: the plan reads as what is made and in what order, feedback 4)."""
    stages, order = {}, []
    for p in parts:
        st = p.pop("stage")
        if st not in stages:
            stages[st] = []
            order.append(st)
        stages[st].append(p)
    return [{"name": s, "parts": stages[s]} for s in order]


def _plan_summary(parts, stages):
    """The plan's one count line, from the grouping shown (never a second count from elsewhere)."""
    n, k = len(parts), len(stages)
    return f"{n} part{'s' * (n != 1)} in {k} stage{'s' * (k != 1)}."


def plain_full(text, names):
    """A part's purpose in plain words, whole (no cut, every sentence), on one line."""
    return re.sub(r"\s+", " ", plain_words(re.sub(r"\s*\n\s*", " ", str(text or "")), names)).strip()


def plan_detail(m, reply, names, ctx):
    """The planner's plan line: every part with its plain name, one-line purpose, stage, what it waits for and its
    usage share; plus the plan reviewer's confidence (realization plan) in plain words."""
    real = ctx.get("real")
    if m.get("realization") and isinstance(real, dict) and isinstance(real.get("plan"), dict):
        import j2_realization
        wfs = j2_realization.run_order([w for w in real["plan"].get("workflows") or [] if isinstance(w, dict)])
        nm = {w.get("name"): plain_name(w.get("name")) for w in wfs}
        parts = [{"name": nm[w.get("name")], "stage": _stage_name(w.get("stage")),
                  "purpose": plain_full(w.get("goal") or w.get("approach") or "", names),
                  "waits_for": [nm.get(d) or plain_name(d) for d in w.get("inputs_from") or [] if d]} for w in wfs]
        stages = _parts_payload(parts)
        low = [plain_name(x.get("workflow")) for x in real.get("not_ready") or [] if isinstance(x, dict)]
        return {"kind": "plan", "summary": _plan_summary(parts, stages), "stages": stages,
                "confidence": _sure(real.get("plan_confidence")), "not_ready": low}
    wfs = reply.get("workflows") if m.get("who") == "adaptation" else None
    if isinstance(wfs, list) and wfs and all(isinstance(w, dict) for w in wfs):
        nm = {w.get("name"): plain_name(w.get("name")) for w in wfs}
        parts = [{"name": nm[w.get("name")], "stage": _stage_name(w.get("stage")) if w.get("stage") else "Parts",
                  "purpose": plain_full((_registered(w.get("name"), ctx) or {}).get("purpose") or w.get("purpose")
                                        or w.get("completion_check") or w.get("goal_gap") or "", names),
                  "waits_for": [names.get(str(d)) or nm.get(d) or plain_name(d) for d in
                                (w.get("dependencies") or w.get("depends_on") or []) if d]} for w in wfs]
        stages = _parts_payload(parts)
        return {"kind": "plan", "summary": _plan_summary(parts, stages), "stages": stages,
                "confidence": None, "not_ready": []}
    return None


CHECK_ROW = re.compile(r"\b([A-Z]\d{1,2}) (met|NOT MET|WARNING)(?: \(([^()]*(?:\([^()]*\)[^()]*)*)\))?")


def _conditions_text():
    out = {}
    for f in ("website.json", "prd.json", "hld.json", "lld.json"):
        try:
            out.update({c["id"]: c["text"] for c in j2.load_conditions(f)})
        except (OSError, ValueError, KeyError):
            pass
    return out


def _item(name, ok, reason, names):
    return {"name": plain_line(name, names, cap=120, sentences=1) or "A check", "pass": bool(ok),
            "reason": plain_line(reason or "", names, cap=160, sentences=1) or None}


def checks_detail(m, reply, names, ctx):
    """A check or quality line: what was checked and the result, each with one plain reason."""
    text, who = str(m.get("text") or ""), m.get("who")
    items = []
    if who == "audit" and isinstance(reply.get("findings"), list):
        for f in reply["findings"]:
            if isinstance(f, dict):
                items.append(_item(f.get("criterion"), str(f.get("verdict", "")).upper().startswith("PASS"),
                                   f.get("evidence") or f.get("reason"), names))
        for r in reply.get("rubric") or []:
            if isinstance(r, dict) and r.get("criterion"):
                items.append(_item(r.get("criterion"), str(r.get("verdict", "")).upper().startswith("PASS"),
                                   r.get("evidence"), names))
        what = "Quality check read the result against your checklist."
    elif m.get("mechanical") and text.startswith("Necessary conditions"):
        conds = _conditions_text()
        for cid, verdict, ev in CHECK_ROW.findall(text):
            items.append(_item(conds.get(cid) or "A required rule", verdict != "NOT MET",
                               ev if verdict != "met" else "", names))
        what = "Code checked the rules every result must meet."
    elif m.get("mechanical") and text.startswith("Mechanical check"):
        body = re.sub(r"^Mechanical check by code:\s*", "", text)
        for seg in [s.strip() for s in body.split(";") if ":" in s]:
            label, res = [x.strip() for x in seg.split(":", 1)]
            good = bool(re.match(r"(?:none|no\b|0\b|ok\b|clean)", res, re.I))
            items.append(_item(label[:1].upper() + label[1:], good, res, names))
        what = "Code opened the page on a phone and a computer."
    elif m.get("checks") or text.startswith("Code ran") or text.startswith("Code checked the whole"):
        wid = m.get("checks")
        w = next((x for x in ctx.get("wfs") or [] if x.get("id") == wid), None) if wid else None
        att = re.search(r"attempt (\d+) of", text)
        for a in (w or {}).get("atoms") or []:
            for r in a.get("results") or []:
                if att and r.get("attempt") and str(r.get("attempt")) != att[1]:
                    continue
                items.append(_item(r.get("check"), r.get("pass"), r.get("evidence"), names))
        if not items:
            for seg in re.findall(r"(W-\d+)\s+(passed|\d+ failed)", text):
                items.append({"name": names.get(seg[0]) or "A part", "pass": seg[1] == "passed",
                              "reason": None if seg[1] == "passed" else f"{seg[1].split()[0]} check failed" if
                              seg[1].startswith("1 ") else f"{seg[1].split()[0]} checks failed"})
        what = f"Code ran the checks for {names.get(wid) or 'this part'}." if wid else "Code checked every part."
    elif m.get("rejected") and text.startswith("Validator rejected"):
        mm = re.match(r"Validator rejected '([^']+)': (.*)", text, re.S)
        if mm:
            items.append({"name": pretty(mm[1]), "pass": False, "reason": rejection_reason(mm[2])[:1].upper()
                          + rejection_reason(mm[2])[1:]})
        what = "The gatekeeper read the part's work order before anything was built."
    else:
        return None
    if not items:
        return None
    good = sum(1 for i in items if i["pass"])
    summary = (f"All {len(items)} passed." if good == len(items) else
               f"{good} of {len(items)} passed, {len(items) - good} did not.")
    return {"kind": "checks", "what": what, "summary": summary, "items": items}


TOK = r"(\d+)\s*tokens?"


def _u(n):
    return j2_usage.short(int(n))


def budget_detail(m, reply, names, ctx):
    """A budget line: the numbers in human form (1.6M, not 1607715), as labelled rows."""
    text, who, rows = str(m.get("text") or ""), m.get("who"), []
    nm = lambda wid: names.get(wid.split(".")[0]) or "a part"
    if who == "priority" and isinstance(reply.get("workflows"), list) and reply["workflows"]:
        for w in reply["workflows"]:
            if not isinstance(w, dict):
                continue
            got, asked = int(j2.granted(w) or 0), int(j2.as_int(w.get("estimate")) or 0)
            rows.append({"label": plain_name(w.get("name")) or "A part",
                         "value": _u(got) + (f" (asked {_u(asked)})" if asked and asked != got else "")})
        dec = str(reply.get("decision") or "").replace("_", " ").lower()
        total = sum(int(j2.granted(w) or 0) for w in reply["workflows"] if isinstance(w, dict))
        summary = (f"{'Granted' if dec.startswith('grant') else pretty(dec) or 'Shares'}: "
                   f"{len(rows)} part{'s' * (len(rows) != 1)}, {_u(total)} in total.")
        return {"kind": "budget", "summary": summary, "rows": rows}
    if mm := re.search(rf"Usage budget set from the approved plan: {TOK} \(estimate (\d+) plus the (\d+)% margin\)", text):
        rows = [{"label": "Budget", "value": _u(mm[1])}, {"label": "Plan's rough figure", "value": _u(mm[2])},
                {"label": "Safety margin", "value": f"{mm[3]}%"}]
        return {"kind": "budget", "summary": "The budget is the approved plan plus a safety margin.", "rows": rows}
    if mm := re.search(rf"Usage budget raised[^:]*: (\d+) -> {TOK}\. Remaining: (\d+)", text):
        rows = [{"label": "Budget before", "value": _u(mm[1])}, {"label": "Budget now", "value": _u(mm[2])},
                {"label": "Left to use", "value": _u(mm[3])}]
        return {"kind": "budget", "summary": "You approved more usage.", "rows": rows}
    if text.startswith("Released"):
        rows = [{"label": nm(w), "value": f"{_u(n)} set aside"} for n, w in re.findall(rf"{TOK} from (W-[\d.a]+)", text)]
        if mm := re.search(r"Usage: (\d+)/(\d+)", text):
            rows.append({"label": "Used so far", "value": f"{_u(mm[1])} of {_u(mm[2])}"})
        return {"kind": "budget", "summary": "Parts that must wait give their share back until they run.",
                "rows": rows} if rows else None
    if mm := re.search(rf"topped up (W-[\d.a]+): \+{TOK} \(share now (\d+)\)", text):
        return {"kind": "budget", "summary": f"The budget lead gave {nm(mm[1])} a little more room.",
                "rows": [{"label": "Added", "value": _u(mm[2])}, {"label": "Share now", "value": _u(mm[3])}]}
    if mm := re.search(rf"The usage left \({TOK}\) can't cover (.*?)\.", text):
        return {"kind": "budget", "summary": "What's left isn't enough for the next step; you decide.",
                "rows": [{"label": "Left to use", "value": _u(mm[1])}, {"label": "Not covered", "value": plain_line(mm[2], names)}]}
    if who == "priority" and text.lstrip("@").split(" ", 2)[-1].startswith("Usage check"):
        for w, n in re.findall(rf"(W-[\d.a]+) {TOK}", text):
            rows.append({"label": nm(w), "value": _u(n)})
        if mm := re.search(rf"Usage check for (W-[\d.a]+): its share fits \({TOK}, (\d+) used", text):
            rows.append({"label": nm(mm[1]), "value": f"{_u(mm[2])} share, {_u(mm[3])} used"})
        if mm := re.search(r"Usage (\d+)/(\d+)", text):
            rows.append({"label": "Used so far", "value": f"{_u(mm[1])} of {_u(mm[2])}"})
        return {"kind": "budget", "summary": "Every share fits, so the work runs now.", "rows": rows} if rows else None
    if who == "priority" and (mm := re.search(rf"\((\d+) of {TOK} left\)", text)):
        return {"kind": "budget", "summary": "The budget lead agreed the shares.",
                "rows": [{"label": "Granted", "value": _u(mm[1])}, {"label": "Left to use", "value": _u(mm[2])}]}
    return None


def decision_detail(m, reply, names, ctx):
    """A decision or record: what was asked and what was chosen."""
    text = str(m.get("text") or "")
    if m.get("auto_decision") and (mm := re.match(r"Decided without asking[^:]*:\s*(.*?)\s*Chosen:\s*(.*?)\.?$", text, re.S)):
        return {"kind": "decision", "asked": plain_line(mm[1], names, cap=200), "chosen": plain_line(mm[2], names),
                "by": "The team, because Decide for me is on (it takes the suggested answer)."}
    if mm := re.match(r"(Left out|Accepted as it is) on the Requester's decision: (.*?)\.?$", text, re.S):
        what = plain_line(mm[2], names)
        return {"kind": "decision", "asked": f"What to do with {what[:1].lower() + what[1:]}",
                "chosen": "Leave it out" if mm[1] == "Left out" else "Accept it as it is", "by": "You"}
    if m.get("who") in ("identity", "coordination") and (reply.get("decision") or reply.get("ruling")):
        chosen = str(reply.get("ruling") or reply.get("decision") or "").replace("_", " ").strip()
        chosen = chosen[:1].upper() + chosen[1:]
        ask = reply.get("question") or reply.get("conflict") or reply.get("asked")
        return {"kind": "decision", "asked": plain_line(ask, names, cap=200) if isinstance(ask, str) else None,
                "chosen": plain_line(chosen[:1].upper() + chosen[1:].lower() if chosen.isupper() else chosen, names,
                                     cap=200), "by": who_name(m.get("who"), names)}
    return None


def to_user(m):
    return m["who"] == "user" or (m["who"] == "identity" and bool(m.get("to_user"))) or bool(m.get("record"))


OPTION_LINE = re.compile(r"^\s*(?:\d+\.\s*)?Option \d+:.*$", re.M)


def question_text(text):
    """A question's chat text without what the decision card already shows: the numbered "Option N:" lines go, and a
    line that repeats an earlier line (the legacy question under Identity's own words) goes too."""
    lines, out, seen = OPTION_LINE.sub("", str(text or "")).split("\n"), [], []
    for ln in lines:
        key = re.sub(r"\s+", " ", ln).strip().lower().rstrip(".?!")
        if key and any(key in s for s in seen):
            continue
        if key:
            seen.append(key)
        out.append(ln.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def chat_lines(chat, since):
    """The chat: the user's messages and the team's (Identity's user-facing) messages, plain, after `since`. A
    question's text keeps Identity's words only; the options live on the decision card."""
    out = []
    for m in chat:
        if m["id"] <= since or not to_user(m):
            continue
        if m.get("record"):          # an answered decision's compact record (api-contract.md, chat kind "record")
            r = m["record"]
            out.append({"id": m["id"], "t": m.get("t"), "from": "team", "kind": "record", "title": str(r.get("title") or ""),
                        "summary": str(r.get("summary") or ""), "answer": str(r.get("answer") or ""),
                        "detail": [plain_name(x) if r.get("kind") == "proposal" else str(x) for x in r.get("detail") or []]})
            continue
        text = str(m["text"])
        if m["who"] == "identity":
            text = re.sub(r"^\s*(?:@\w+\b[,:]?\s*)+", "", text).strip()     # "@Requester @Adaptation ..." leads
            text = re.sub(r"\b(?:the )?Requester'?s\b", "your", text)
            text = re.sub(r"\b(?:the )?Requester(?: \(you\))?\b", "you", text)
            if m.get("pause"):
                text = question_text(text)
            text = j2.pretty_name(text)
            # code-written check lines quote the conditions' own words: the chat reads them as the person's words
            text = re.sub(r"\bthe charter or the Requester's answers\b", "your brief or your answers", text)
            text = re.sub(r"\bthe Requester's answers\b", "your answers", text)
            text = re.sub(r"\b(?:in|from) the charter\b", lambda m: m.group(0).split()[0] + " your brief", text)
            text = re.sub(r"\bcharter\b", "brief", text)
        out.append({"id": m["id"], "t": m.get("t"), "from": "you" if m["who"] == "user" else "team", "text": text})
    return out


# Fixed code-written lines whose plain-words pass alone reads badly (internal words, "is on:" eaten as a code's
# colon, a v0 preview), rewritten whole for the backstage. The originals stay in detail.full and the legacy page.
SYSTEM_LINES = (
    (re.compile(r"^Realization is on:.*", re.S), "The planner plans in stages, and a separate judge scores every part "
     "before anything is built."),
    (re.compile(r"^Plan by realization and certainty: stages ([^;]*); (\d+) (?:workflows|parts); the judge's plan "
                r"confidence is ([\d.]+)(?:; not ready: ([^.]*))?\. Details in realization\.md\.", re.S),
     lambda m: f"The plan: {m[2]} parts in {len({_stage_name(x.strip()) for x in m[1].split(',') if x.strip()})} stages. "
               f"The plan reviewer is "
               f"{round(float(m[3]) * 100)}% sure of it" + (f"; not ready yet: {m[4]}." if m[4] else ".")),
    (re.compile(r"^Validator rejected '([^']+)': (.*)", re.S),
     lambda m: f"Gatekeeper sent {j2.pretty_name(m[1])} back to the planner: " + rejection_reason(m[2])),
    (re.compile(r"^(.+?) is ESCALATED after (\d+) failed attempts with no fix\..*", re.S),
     r"\1 still fails its checks after \2 tries. The quality check looks at the result and the planner plans the fix."),
    (re.compile(r"^Charter valid: statement present, (\d+) checkable done-when items\. Work can start\.", re.S),
     r"The brief is complete: \1 things to check at the end. Work can start."),
    (re.compile(r"^Paused: Identity is waiting on the Requester \((.*?)\)\.\s.*?(?:v0 is in the preview\.\s*)?"
                r"Answer Identity's question above to continue\.", re.S), "Waiting for your answer."),
    (re.compile(r"^Paused: Identity is waiting on the Requester \((.*?)\)\.\s(\w+ v[1-9]\d* is in the preview\.).*",
                re.S), r"Waiting for your answer. \2"),
)


def rejection_reason(why):
    """A gatekeeper rejection's reason in plain words (the exact reason stays in the line's detail)."""
    w = str(why)
    if "facts-present lists" in w:
        return "one of its checks lists facts that aren't in your brief."
    if "has type" in w and "allowed" in w:
        return "one of its checks is a kind that can't run on this part."
    if "depends on" in w or "loop" in w:
        return "it waits on a part that doesn't exist or never could start."
    if "free to grant" in w or "usage" in w:
        return "it needs more usage than is left."
    if "required field" in w:
        return "its work order is incomplete."
    return "its work order doesn't meet the plan rules yet."


def system_line(text):
    text = AT.sub("", text)
    for pat, rep in SYSTEM_LINES:
        if pat.search(text):
            return pat.sub(rep, text, count=1)
    return text


def backstage_lines(chat, names, since, working, calls=None, ctx=None):
    """Agent-to-agent messages and system lines (checks, holds, false alarms: never in the chat), each one plain line
    with vocabulary names, after `since`, with its detail (detail_of). Lines are never re-sent; the newest is active
    while the run is working."""
    out, calls = [], calls or {}
    for m in chat:
        if m["id"] <= since or to_user(m):
            continue
        text = plain_line(system_line(str(m["text"])) if m["who"] in ("system", "validator", "adaptation") else m["text"],
                          names)
        text = text[:1].upper() + text[1:]
        if m.get("mechanical") and str(m["text"]).startswith("Necessary conditions"):
            rows = re.findall(r"\b[A-Z]\d{1,2} (met|NOT MET|WARNING)", str(m["text"]))
            bad = rows.count("NOT MET")
            text = f"Automatic checks: {len(rows) - bad} of {len(rows)} rules met" + (f", {bad} not met." if bad else ".")
        if not text:
            continue
        nxt = m.get("next")
        out.append({"id": m["id"], "t": m.get("t"), "from": who_name(m["who"], names),
                    "to": who_name(nxt, names) if nxt and nxt != "user" else None, "text": text, "active": False,
                    "detail": detail_of(m, names, calls, ctx)})
    if out and working:
        out[-1]["active"] = True
    return out


def task_status(w):
    s = w.get("status")
    atoms = [a.get("status") for a in w.get("atoms") or []]
    if s == "unfunded":
        return "skipped"
    if s == "failed" or (s == "done" and any(a in ("failed", "escalated") for a in atoms)):
        return "needs_fix"
    return {"done": "done", "running": "working"}.get(s, "waiting")


def plan_view(wfs, stage_of, proposal=None, usage=None):
    """Workflows grouped by stage, in plain words: name, one-line summary, status, waits for, usage and share. Before
    anything is registered, the proposal's parts are the plan (all waiting)."""
    names = {w["id"]: plain_name(w.get("name")) for w in wfs}
    by_name = {w.get("name"): w for w in wfs}
    groups, order = {}, []
    for w in wfs:
        g = GROUPS.get(stage_of(w), str(stage_of(w) or "Building").capitalize())
        if g not in groups:
            groups[g] = []
            order.append(g)
        used = (usage or {}).get(w["id"], w.get("usage") or 0)
        if "waiting_for" in w and w.get("status") in ("registered", "held"):     # 5c: code's live waits (W-ids)
            wait = [next((x for x in wfs if x["id"] == d), None) or {"id": d, "name": d} for d in w["waiting_for"]]
        elif w.get("status") in ("registered", "held"):
            deps = [next((x for x in wfs if x["id"] == d), None) or by_name.get(d)
                    for d in (w.get("depends_on") or w.get("dependencies") or [])]
            wait = [d for d in deps if d and d.get("status") != "done"]
        else:
            wait = []
        groups[g].append({"id": w["id"], "name": names[w["id"]] or w["id"],
                          "summary": plain_task(w.get("purpose") or w.get("goal_gap") or w.get("completion_check")),
                          "status": task_status(w),
                          "waits_for": [names.get(d["id"]) or plain_name(d.get("name")) for d in wait],
                          "usage": int(used or 0), "share": int(j2.granted(w) or 0)})
    if not wfs and proposal:
        order = ["Planned"]
        groups["Planned"] = [{"id": f"p-{i}", "name": plain_name(n), "summary": "", "status": "waiting", "waits_for": [],
                              "usage": 0, "share": 0} for i, n in enumerate(proposal.get("parts") or [], 1)]
    return {"groups": [{"name": g, "tasks": groups[g]} for g in order]}


STAGE_LEAD = re.compile(r"^(the (?:product requirements|high-level design|low-level design|website|[a-z -]{3,40})):\s+(?=\S)")


def _drop_tail_parens(t):
    """A trailing "(evidence ...)" removed, nested brackets included: "(the document says 'x'; all 1 fact(s) appear)"."""
    t = t.rstrip()
    while t.endswith(")"):
        depth, i = 0, len(t) - 1
        while i >= 0:
            depth += 1 if t[i] == ")" else -1 if t[i] == "(" else 0
            if depth == 0:
                break
            i -= 1
        if i <= 0:
            break
        t = t[:i].rstrip()
    return t


def _open_item(f):
    t = re.sub(r"^(?:done-when item|checklist items?|document rubric|design rubric|quality check) [^:]*:\s*", "", str(f))
    t = re.sub(r"^necessary condition \S+ not met:\s*", "", t)
    t = re.sub(r":\s*None$", "", t)
    return _drop_tail_parens(t).strip(" ;.")


def open_items(fails):
    """workable()'s problems as plain items: the checklist text, without its number, verdict or evidence. An earlier
    stage's record ("the product requirements: item; item") becomes one item per problem, named for its stage. The
    same problem reported twice (a quality check and a condition with the same lead) is listed once."""
    out, seen, last_stage = [], set(), None
    for f in fails or []:
        f, stage = str(f), None
        m = STAGE_LEAD.match(f)
        if m and re.match(r"(?:done-when item|checklist items?|document rubric|design rubric|necessary condition)\b", f[m.end():]):
            stage, f = m.group(1), f[m.end():]
        elif re.fullmatch(r"the [a-z -]{3,40}", f.strip()):            # a stage accepted as it was, nothing open
            out.append(f"{f.strip()[0].upper()}{f.strip()[1:]}, kept as it was")
            continue
        parts = [x for x in re.split(r";\s+(?=(?:done-when item|checklist items?|document rubric|design rubric|"
                                     r"necessary condition)\b)", f) if x.strip()] if stage else [f]
        for part in parts:
            t = _open_item(part)
            if not t:
                continue
            key = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
            lead_key = " ".join(key.split(" ")[:4]) if ":" in t[:48] else key
            # the same text is one item wherever it came from; the same lead ("No invented facts: ...") is one item
            # within a stage, and a bare item (the current stage's) is one with the last recorded stage's item of
            # that lead (a run that ends right after accepting a document lists that document's problems twice)
            if ("*", key) in seen or (stage or last_stage, lead_key) in seen:
                continue
            seen.add(("*", key)); seen.add((stage, lead_key))
            last_stage = stage or last_stage
            line = plain_line(t, {}, 140)
            out.append(f"In {stage}: {line}" if stage else line)
    return out


def iso_of(run_id):
    m = re.match(r"j2-(\d{8})-(\d{6})", str(run_id or ""))
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return None


def ended_view(status, outcome, fails, chat):
    if status not in ENDED:
        return None
    last = next((m["text"] for m in reversed(chat) if m["who"] == "identity" and m.get("to_user") and m.get("done")), None)
    text = {"done": re.sub(r"^\s*@Requester\s*", "", last or "") or "It's done.",
            "done_open": "Done, with some things still open.",
            "stopped": "Stopped.", "crashed": "Something broke. Try again."}[status]
    if status == "stopped" and outcome:
        t = plain_line(re.sub(r"^Stopped:?\s*", "", outcome), {}, 160)
        text = (t[0].upper() + t[1:]) if t else text              # "On your decision: nothing was built."
    return {"kind": status, "text": text, "open_items": open_items(fails) if status == "done_open" else []}


def deliverables(kinds, docs_done, cur_kind, cur_versions, run_dir, saved_name=None, finished=False):
    """One entry per thing made, in order: website, PRD, HLD, LLD. A document's url returns its raw markdown."""
    out, q = [], (f"?run={saved_name}" if saved_name else "")
    for k in kinds:
        if k not in LABELS:
            continue
        doc = k != "website"
        has_file = bool(run_dir) and os.path.exists(os.path.join(run_dir, f"{k}.md"))
        if k in docs_done or (finished and k == cur_kind and (cur_versions or has_file)):
            state = "done"
        elif finished and k == cur_kind:
            state = "todo"           # the run ended before this stage made anything (a chain's website never started)
        elif k == cur_kind:
            state = "draft" if cur_versions else "working"
        else:
            state = "todo"
        n = cur_versions if k == cur_kind else (1 if k in docs_done else 0)
        if doc:
            url = f"/api/v2/doc/{k}{q}" if (n or has_file) else None
            dl = f"/file/{k}.md{q}" if has_file else url
        else:
            url = (f"/site/v{n}{q}" if not saved_name else f"/site/latest{q}") if n else None
            dl = url
        out.append({"kind": k, "label": LABELS[k], "state": state, "version": n or None, "url": url, "download": dl})
    return out


def live(run, since=0, bsince=0):
    """/api/v2/state for the live run."""
    st, reason = run.run_status()
    status = "idle" if not run.chat else STATUS.get(st, "stopped")
    if status == "working" and not run.goal and not run.workflows:
        status = "working"
    wfs = run._wfs_view()
    names = {w["id"]: plain_name(w.get("name")) for w in wfs}
    fn = run.thinking or run.turn
    working = status == "working"
    # "Building: Build menu section" reads "Building: Menu section"
    bare = lambda n: (lambda t: t[:1].upper() + t[1:])(re.sub(r"^build(?:ing)?\s+(?:the\s+)?", "", n, flags=re.I) or n)
    running = [bare(names.get(w["id"]) or "a part") for w in wfs if w.get("status") == "running"]
    if status == "working":
        if j2.is_wf_agent(fn) and len(running) > 1:            # 6b: a batch of builders works at once
            text = f"Building: {j2.and_list(running[:4])}"
        else:
            text = (f"Building: {bare(names.get(fn) or 'a part')}" if j2.is_wf_agent(fn) else
                    "Client lead is going over the result" if fn == "identity" and any(w.get("status") == "done" for w in wfs)
                    else named_doing(fn, run.output if run.output in LABELS else "website"))
    elif status == "needs_you":
        text = ((run.legacy_decision() or {}).get("happening") or "The team needs your answer.")
    elif status == "idle":
        text = ""
    else:
        text = {"done": "Done", "done_open": "Done, with open items", "stopped": "Stopped",
                "crashed": "Something broke"}.get(status, "")
    ctl = control_view(run)
    if status == "working" and ctl["paused"]:          # held at a safe point by the person (the kingdom view)
        status, text, working = "paused", "Paused", False
    elif status == "working" and ctl["pausing"]:
        text = "Pausing after this step…"
    elif status == "working" and ctl["stopping"]:
        text = "Stopping after this step…"
    u = run.usage_view()
    d = None if status != "needs_you" else {k: v for k, v in (run.legacy_decision() or {}).items() if k != "legacy"}
    if d and isinstance(d.get("proposal"), dict) and d["proposal"].get("parts"):     # the same part names as plan and map
        d["proposal"] = {**d["proposal"], "parts": [plain_name(x) for x in d["proposal"]["parts"]]}
    stage_of_wf = {wid: k for k, v in run.docs.items() for wid in v.get("workflows") or []}
    stage_of = lambda w: w.get("stage") or stage_of_wf.get(w["id"]) or (run.stage_kind or run.output)
    kinds = list(run.stages or [run.output])
    last = run.audits[-1] if run.audits else None
    fails = (run.open_docs + (j2.workable(last) if last else [])) if status == "done_open" else []
    finished = status in ("done", "done_open")
    title = (run.goal or {}).get("site_name") or (run.goal or {}).get("product_name") or \
        (j2.short(run.request, 6) if run.request else "")
    return {"run": {"id": os.path.basename(run.dir), "saved": False, "title": title},
            "status": status, "status_text": text,
            "usage": {"budget": u["budget"], "spent": int(u["spent"] or 0), "margin_at": u["margin_at"],
                      "estimate": u["estimate"], "by_phase": u["by_phase"],
                      "web_searches": int(u.get("web_searches") or 0), "web_fetches": int(u.get("web_fetches") or 0)},
            "decision": d, "chat": chat_lines(run.chat, since),
            "backstage": backstage_lines(run.chat, names, bsince, working, {c["id"]: c for c in run.call_log},
                                         {"real": run.real, "wfs": run._all_wfs()}),
            "working_now": ({"who": who_name(fn, names), "task_id": fn if j2.is_wf_agent(fn) else None}
                            if working and fn else None),
            "plan": plan_view(wfs, stage_of, run.proposal, u["by_workflow"]),
            "deliverables": deliverables(kinds, set(run.docs), run.stage_kind or run.output, len(run.sites), run.dir,
                                         finished=finished),
            "ended": ended_view(status, run.outcome, fails, run.chat),
            "settings": {"no_questions": bool(run.no_questions), "model": run.model_tier}, "control": ctl}


def control_view(run):
    """The kingdom view's control state (api-contract.md): paused (held at a safe point), pausing / stopping (asked
    for, not yet reached)."""
    c = getattr(run, "ctl", None) or {}
    return {"paused": bool(c.get("paused")), "pausing": c.get("want") == "pause" and not c.get("paused"),
            "stopping": c.get("want") == "stop"}


def saved(name, since=0, bsince=0):
    """/api/v2/state for a saved run folder (read-only: no decision can be answered)."""
    d = j2.saved_dir(name)
    if not d:
        return None
    snap = j2.saved_snapshot(name)
    rows = j2._jsonl(d, "chat.jsonl")
    chat = [m for m in rows if not m.get("meta")]
    s = j2._read(d, "summary.json", {}) or {}
    wfs = snap["workflows"] or []
    names = {w["id"]: plain_name(w.get("name")) for w in wfs}
    st = (snap.get("run_status") or {}).get("status") or "stopped"
    status = STATUS.get(st, "stopped") if chat else "idle"
    if status in ("working", "needs_you"):
        status = "stopped"            # a saved run doesn't move and can't be answered
    docs = j2._read(d, "documents.json", {}) or {}
    stage_of_wf = {wid: k for k, v in docs.items() for wid in v.get("workflows") or []}
    kinds = list((s.get("design_documents") or {}).get("stages") or list(docs) or [snap["output"]])
    # An older run without documents.json / summary.json: every document file in the folder is a deliverable.
    on_disk = [k for k in ("prd", "hld", "lld") if os.path.exists(os.path.join(d, f"{k}.md"))]
    kinds = [k for k in ("prd", "hld", "lld") if k in kinds or k in on_disk] + [k for k in kinds if k not in ("prd", "hld", "lld")]
    docs_done = set(docs) | set(on_disk)
    if snap["output"] == "website" and "website" not in kinds:
        kinds = list(kinds) + ["website"]
    u = snap.get("usage") or {}
    tokens = u.get("measure") == "tokens"
    goal = snap.get("goal") or {}
    first = next((m["text"] for m in chat if m["who"] == "user"), "")
    finished = status in ("done", "done_open")
    cur = kinds[-1] if kinds else snap["output"]
    vs = j2.site_versions(os.path.join(d, "site"))
    # the current stage's versions only: a website's vN.html, or a document's <kind>-vN.md
    versions = len([f for f in vs if (f.endswith(".html") if cur == "website" else f.startswith(f"{cur}-"))])
    if cur == "website" and not versions and on_disk and not finished:
        cur = on_disk[-1]            # stopped while writing a document: the website never started
        versions = len([f for f in vs if f.startswith(f"{cur}-")])
    if not finished:
        docs_done.discard(cur)       # the document the run stopped in is a draft, not a filed document
    return {"run": {"id": name, "saved": True, "title": goal.get("site_name") or goal.get("product_name")
                    or j2.short(first, 6)},
            "status": status, "status_text": {"done": "Done", "done_open": "Done, with open items", "stopped": "Stopped",
                                              "crashed": "Something broke", "idle": ""}.get(status, ""),
            "usage": {"budget": u.get("budget") if tokens else None, "spent": int(u.get("spent") or 0) if tokens else 0,
                      "margin_at": u.get("margin_at"), "estimate": u.get("estimate"),
                      "by_phase": u.get("by_phase") or {k: 0 for k in j2.PHASES},
                      "web_searches": int(u.get("web_searches") or 0), "web_fetches": int(u.get("web_fetches") or 0)},
            "decision": None, "chat": chat_lines(chat, since),
            "backstage": backstage_lines(chat, names, bsince, False, saved_calls(d),
                                         {"real": j2._read(d, "realization.json", None), "wfs": wfs}),
            "working_now": None,
            "plan": plan_view(wfs, lambda w: w.get("stage") or stage_of_wf.get(w["id"]) or snap["output"], None,
                              u.get("by_workflow")),
            "deliverables": deliverables(kinds, docs_done, cur, versions, d, saved_name=name, finished=finished),
            "ended": ended_view(status, s.get("outcome"), s.get("workable") or [], chat) if chat else None,
            "settings": {"no_questions": bool((j2._read(d, "settings.json", {}) or {}).get("no_questions")),
                         "model": (j2._read(d, "settings.json", {}) or {}).get("model")},
            "control": {"paused": False, "pausing": False, "stopping": False}}


_CALLS = {}


def saved_calls(d):
    """A saved run's calls.jsonl as {call id: {reply, reason}} (agent calls only), cached by the file's size and time."""
    p = os.path.join(d, "calls.jsonl")
    try:
        st = os.stat(p)
    except OSError:
        return {}
    key = (p, st.st_size, st.st_mtime)
    if key not in _CALLS:
        out = {}
        with open(p, encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if not r.get("extra") and r.get("id") is not None:
                    out[r["id"]] = {"reply": r.get("reply"), "reason": r.get("reason")}
        _CALLS.clear()
        _CALLS[key] = out
    return _CALLS[key]


def runs(limit=30):
    """/api/v2/runs: [{id, title, status, spent, when}], newest first."""
    out = []
    for r in j2.list_runs(limit):
        d = j2.saved_dir(r["id"])
        s = j2._read(d, "summary.json", {}) or {}
        b = s.get("budget") or {}
        goal = j2._read(d, "goal.json", {}) or {}
        st = s.get("status") or "unfinished"
        out.append({"id": r["id"], "title": goal.get("site_name") or goal.get("product_name") or j2.short(r["brief"], 6),
                    "status": STATUS.get(st, "stopped"),
                    "spent": int(b.get("spent") or 0) if b.get("measure") == "tokens" else 0,
                    "when": iso_of(r["id"])})
    return out


def doc_text(run, kind, saved_name=None):
    """A document deliverable's raw markdown: the filed document, else (live) the current stage's latest version."""
    d = j2.saved_dir(saved_name) if saved_name else run.dir
    if kind not in ("prd", "hld", "lld") or not d:
        return None
    if not saved_name and run.stage_kind in (kind, None) and run.doc and run.output == kind and run.sites:
        return run.sites[-1]
    p = os.path.join(d, f"{kind}.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    vs = [f for f in j2.site_versions(os.path.join(d, "site")) if f.startswith(f"{kind}-") or
          (f.endswith(".md") and not re.match(r"\w+-v", f))]
    if vs:
        with open(os.path.join(d, "site", vs[-1]), encoding="utf-8") as f:
            return f.read()
    return None



# ------------------------------------------------------------------ the kingdom view: /api/v2/map

def unit_id(fn):
    return f"u-{fn}" if fn else None


def map_departments(kinds):
    return [{"id": f"d-{k}", "name": LABELS.get(k, str(k).capitalize()), "kind": k} for k in kinds]


def building_progress(w, state, usage):
    """How far one part is, 0..1, by code, from its plan state (task_status): done = 1; working = its atoms passed so
    far, else its usage against its share; a part that needs a fix keeps most of its fill; waiting and skipped = 0."""
    atoms = w.get("atoms") or []
    if state == "done":
        return 1.0
    if state == "working":
        if atoms:
            passed = sum(1 for a in atoms if a.get("status") == "passed")
            return round(0.1 + 0.8 * passed / len(atoms), 3)
        share = j2.granted(w) or 0
        return round(0.15 + 0.7 * min(1.0, (usage or 0) / share), 3) if share else 0.4
    if state == "needs_fix":
        return 0.7
    return 0.0


def building_doing(w, state, waits, last_line):
    """One plain line on what a part is up to: its builder's last words while working, what it waits for, or its state."""
    if state == "working":
        return last_line or f"Building {plain_name(w.get('name')).lower()}"
    if state == "waiting":
        return f"Waits for {j2.and_list(waits)}" if waits else "Waiting its turn"
    if state == "needs_fix":
        return plain_line(w.get("last_check") or "Needs a fix", {}, 110)
    if state == "skipped":
        return "Left out"
    return "Done"


def flows_of(chat, units, names, since, limit=MAP_FLOWS):
    """The hand-offs between units (a message addressed to the next agent) after `since`, newest `limit`, each with one
    plain line on what was handed over. The user is the castle."""
    out = []
    for m in chat:
        if m["id"] <= since or not m.get("next") or m["who"] in ("system",):
            continue
        frm = "castle" if m["who"] == "user" else unit_id(m["who"])
        to = "castle" if m["next"] == "user" else unit_id(m["next"])
        if (frm != "castle" and frm not in units) or (to != "castle" and to not in units) or frm == to:
            continue
        out.append({"id": m["id"], "from": frm, "to": to, "t": m.get("t"), "what": plain_line(m["text"], names, cap=100, sentences=1)})
    return out[-limit:]


def map_build(wfs, chat, kinds, stage_of, cur_kind, status, working_fns, turn, usage_by_wf, since, attention_wid=None,
              proposal=None, output_of=None):
    """The map data (api-contract.md, /api/v2/map) from a run's parts, chat and status. Pure assembly: every field comes
    from the run's own state."""
    names = {w["id"]: plain_name(w.get("name")) for w in wfs}
    working = status == "working"
    needs_you = status == "needs_you"
    kinds = [k for k in kinds if k in LABELS] or [cur_kind if cur_kind in LABELS else "website"]
    cur = f"d-{cur_kind}" if cur_kind in LABELS else f"d-{kinds[-1]}"
    depts = map_departments(kinds)
    last_by = {}
    for m in chat:
        if m["who"] not in ("system", "user"):
            last_by[m["who"]] = m
    units, buildings = [], []
    busy = {HELPER_UNIT.get(f, f) for f in working_fns} | ({HELPER_UNIT.get(turn, turn)} if turn else set())
    for fn in CORE_UNITS:
        state = "working" if working and fn in busy else             "waiting" if fn == "identity" and needs_you else "idle"
        # what it is doing right now: the step it is on (its own or a helper call it runs), never its last old words
        key = next((f for f in [*working_fns, turn] if f and HELPER_UNIT.get(f, f) == fn), fn)
        now = (NAMED_DOING.get(key) or NAMED_DOING.get(fn) or "").removeprefix("is ").format(
            noun="page" if cur_kind in (None, "website") else "document")
        doing = ((now[:1].upper() + now[1:]) if now else DOING.get(fn, "Working")) if state == "working" else \
            "Waiting for your answer" if state == "waiting" else ""
        units.append({"id": unit_id(fn), "role": ROLES[fn], "label": VOCAB[fn], "dept": cur, "at": cur, "state": state, "doing": doing})
    by_name = {w.get("name"): w for w in wfs}
    for w in wfs:
        k = stage_of(w)
        dept = f"d-{k}" if k in LABELS else cur
        st = task_status(w)
        if w.get("status") in ("registered", "held"):
            if "waiting_for" in w:
                waits = [names.get(d) or plain_name(d) for d in w["waiting_for"]]
            else:
                deps = [next((x for x in wfs if x["id"] == d), None) or by_name.get(d) for d in (w.get("depends_on") or [])]
                waits = [names.get(d["id"]) for d in deps if d and d.get("status") != "done"]
        else:
            waits = []
        last = last_by.get(w["id"])
        last_line = plain_line(last["text"], names, cap=110, sentences=1) if last else ""
        deps = [(next((x["id"] for x in wfs if x["id"] == d or x.get("name") == d), None)) for d in (w.get("depends_on") or [])]
        buildings.append({"id": w["id"], "name": names[w["id"]] or w["id"], "dept": dept, "progress": building_progress(w, st, usage_by_wf.get(w["id"], w.get("usage"))),
                          "state": st, "depends_on": [d for d in deps if d and d != w["id"]], "usage": int(usage_by_wf.get(w["id"], w.get("usage")) or 0),
                          "share": int(j2.granted(w) or 0), "doing": building_doing(w, st, waits, last_line),
                          "output": (output_of or output_kind)(w, k) if st == "done" else None, "kind": part_kind(w, k)})
        if w.get("status") == "running" or st == "needs_fix":      # a builder is on the map only while it is at its part
            bstate = "working" if st == "working" and working else "idle"
            units.append({"id": unit_id(w["id"]), "role": "builder", "label": f"Builder · {names[w['id']]}", "dept": dept,
                          "at": w["id"], "state": bstate, "doing": last_line if bstate == "working" else ""})
    if not wfs and proposal:          # before registration: the proposal's parts, all waiting, in one chain
        for i, n in enumerate(proposal.get("parts") or [], 1):
            buildings.append({"id": f"p-{i}", "name": plain_name(n), "dept": cur, "progress": 0.0, "state": "waiting",
                              "depends_on": [f"p-{i - 1}"] if i > 1 else [], "usage": 0, "share": 0, "doing": "Planned",
                              "output": None, "kind": part_kind({"name": n}, cur_kind)})
    ids = {u["id"] for u in units}
    done = sum(1 for b in buildings if b["state"] == "done")
    attention = None
    if needs_you:
        attention = attention_wid if attention_wid and any(b["id"] == attention_wid for b in buildings) else unit_id("identity")
    return {"departments": depts, "units": units, "buildings": buildings,
            "flows": flows_of(chat, ids, names, since), "attention": attention,
            "status": status, "counts": {"done": done, "total": len(buildings)}}


def attention_target(run):
    """The part an open decision is about (its handoff names a workflow), else None (the client lead)."""
    h = (run.paused or {}).get("handoff") or {}
    wid = h.get("wid") or next(iter(h.get("wids") or []), None)
    return str(wid) if wid else None


def map_live(run, since=0):
    """/api/v2/map for the live run."""
    st = live(run)
    wfs = run._wfs_view()
    stage_of_wf = {wid: k for k, v in run.docs.items() for wid in v.get("workflows") or []}
    stage_of = lambda w: w.get("stage") or stage_of_wf.get(w["id"]) or (run.stage_kind or run.output)
    kinds = list(run.stages or [run.output])
    cur = run.stage_kind or run.output
    status = st["status"]
    working_fns = set(run.thinking_all()) | {w["id"] for w in wfs if w.get("status") == "running"}
    return map_build(wfs, run.chat, kinds, stage_of, cur, status, working_fns, run.turn, run.usage_view()["by_workflow"], since,
                     attention_target(run), run.proposal)


def map_saved(name, since=0):
    """/api/v2/map for a saved run folder (nothing moves)."""
    d = j2.saved_dir(name)
    if not d:
        return None
    st = saved(name)
    snap = j2.saved_snapshot(name)
    chat = [m for m in j2._jsonl(d, "chat.jsonl") if not m.get("meta")]
    wfs = snap["workflows"] or []
    docs = j2._read(d, "documents.json", {}) or {}
    stage_of_wf = {wid: k for k, v in docs.items() for wid in v.get("workflows") or []}
    kinds = [x["kind"] for x in st["deliverables"]] or [snap["output"]]
    cur = kinds[-1]
    u = snap.get("usage") or {}
    return map_build(wfs, chat, kinds, lambda w: w.get("stage") or stage_of_wf.get(w["id"]) or snap["output"], cur,
                     st["status"], set(), None, u.get("by_workflow") or {}, since)


# ------------------------------------------------------------------ "See output": what a finished part made

def output_kind(w, stage=None):
    """What a finished part made, as the map's `output` ({"kind": ...}; the payload comes from /api/v2/output):
    research (the sources it found), section (a built part of the page, shown in the Result scrolled to it), style
    (the look: palette, fonts, buttons), notes (a planning file: the sections or points it set), document (a section of
    a PRD, HLD or LLD, shown in the Result) or page (the page as a whole)."""
    parts, outs = set(w.get("parts") or []), [str(o) for o in w.get("outputs") or []]
    if w.get("research") or any(o.split("#")[0] == "research.md" for o in outs):
        return {"kind": "research"}
    if stage in ("prd", "hld", "lld") or any(o.startswith("## ") or o in ("prd.md", "hld.md", "lld.md") for o in outs):
        doc = stage if stage in ("prd", "hld", "lld") else next((o[:3] for o in outs if o in ("prd.md", "hld.md", "lld.md")), None)
        return {"kind": "document", "doc": doc}
    if "page_section" in parts or "form" in parts:
        return {"kind": "section"}
    if re.search(r"\b(?:style|look|design|palette|brand)\b", f"{w.get('name')} {stage or ''}".replace("_", " "), re.I) and \
            not any(o.endswith(".html") for o in outs):
        return {"kind": "style"}
    if any(o.endswith(".md") for o in outs):
        return {"kind": "notes"}
    return {"kind": "page"}


def _md_points(text, limit=20):
    """A planning file's sections and points, plain: its headings (below the title) and list items."""
    out = []
    for ln in str(text or "").splitlines():
        m = re.match(r"^\s*(?:#{2,4}\s+|[-*]\s+|\d+[.)]\s+)(.+)$", ln)
        if m:
            t = plain_line(re.sub(r"[*_`]", "", m[1]), {}, cap=140, sentences=1)
            if t and t not in out:
                out.append(t)
        if len(out) >= limit:
            break
    return out


ANCHOR_COL = re.compile(r"^(?:anchor(?: id)?|id|selector|element id)$", re.I)


def _drop_table_cols(lines):
    """A markdown table without its anchor/id columns (internal codes a person never needs)."""
    cells = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    drop = {i for i, c in enumerate(cells[0]) if ANCHOR_COL.match(re.sub(r"[*_`]", "", c))}
    if not drop:
        return lines
    return ["| " + " | ".join(c for i, c in enumerate(row) if i not in drop) + " |" for row in cells]


def _id_words(x):
    """A page element id as words: "#contact-form" reads "contact form"."""
    return re.sub(r"^j2-", "", x.lstrip("#")).replace("-", " ").replace("_", " ").strip()


def _plain_codes(ln, table_row=False):
    """One line of a planning file without its code: an element id reads as the section it names ("links to the
    contact form section"), a class, CSS variable or attribute in backticks goes, and "done-when" reads "checklist"."""
    t = re.sub(r"\b(to|from|at|on|into|inside|under|above|below)\s+`#([\w-]+)`",
               lambda m: f"{m[1]} the {_id_words(m[2])} section", ln)
    t = re.sub(r"^(\s*(?:[-*]|\d+[.)])\s+)`#([\w-]+)`\s*:", lambda m: m[1] + _id_words(m[2]).capitalize() + ":", t)
    t = re.sub(r"`#([\w-]+)`", (lambda m: _id_words(m[1])) if table_row else "", t)
    t = re.sub(r"\s*\b(?:with |has |the )?(?:class|classes|selector|variable|attribute)\s+`[^`]*`", "", t)
    t = re.sub(r"\s*`(?:\.|--|j2-)[^`]*`|\s*`[^`]*(?:[=\"{};<>]|var\()[^`]*`", "", t)
    t = re.sub(r"`([A-Za-z][\w -]*:?)`", lambda m: re.sub(r"[-_]", " ", m[1]), t)     # a plain word: kept, unquoted
    t = re.sub(r"\s*`[^`]*`", "", t)                                                  # any other code: out
    t = re.sub(r"\bdone[-_ ]when items?\b", "checklist items", t, flags=re.I)
    t = re.sub(r"\bdone[-_ ]when\b", "checklist", t, flags=re.I)
    t = re.sub(r"\(\s*[,;]?\s*\)", "", t)
    t = re.sub(r"\(\s*[,;]\s*", "(", t)
    t = re.sub(r"\s+([,.;:])", r"\1", t) if not table_row else t
    return re.sub(r"(\S)  +", r"\1 ", t)


def artifact_markdown(text, names):
    """A file a planning part wrote (a page plan, the copy, a spec), as the person reads it: the team's words plain
    (the brief, parts, you), no part ids or codes, no file names, no anchor ids or CSS selectors, line by line so the
    markdown (headings, lists, tables) and every fact, price and phone number stay exactly as written."""
    out, table = [], []

    def flush():
        if table:
            out.extend(_drop_table_cols(table))
            table.clear()
    for ln in str(text or "").splitlines():
        if re.match(r"^\s*[-*]\s*(?:\*\*)?(?:anchor(?: id)?|selector|element id)s?(?:\*\*)?\s*:", ln, re.I):
            continue                                            # "- Anchor: `#hero`": a code, not content
        t = _plain_codes(ln, table_row=bool(re.match(r"^\s*\|", ln)))
        t = re.sub(r"\bW-\d+(?:\.a\d+)?\b", lambda m: names.get(m.group(0).split(".")[0]) or "a part", t)
        t = CODES.sub("", t)
        t = re.sub(r"\b(?:this|the) file\b", lambda m: "This document" if m.group(0)[0].isupper() else "this document", t, flags=re.I)
        t = re.sub(r"\b(?:no )?workflow registered\b", "no part planned", t)
        for pat, rep_ in INTERNAL:
            t = re.sub(pat, rep_, t, flags=re.I) if isinstance(rep_, str) else re.sub(pat, rep_, t)
        t = YOU_VERB.sub(lambda m: "you " + YOU_FIX.get(m[1], m[1][:-1]), t)
        t = FILE.sub(lambda m: FILE_WORDS.get(m[2].lower().split("-")[0], "the notes"), t)
        t = re.sub(r"\(\s*\)", "", t)
        t = re.sub(r"(^|[.!?]\s+)(you|your)\b", lambda m: m[1] + m[2].capitalize(), t)
        if re.match(r"^\s*\|.*\|\s*$", t):
            table.append(t)
            continue
        flush()
        out.append(t.rstrip())
    flush()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _read_artifact(run_dir, f):
    for cand in (os.path.join(run_dir, f), os.path.join(run_dir, "artifacts", os.path.basename(f))):
        try:
            with open(cand, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            continue
    return ""


def style_rules(text, st, limit=8):
    """The style guide's key rules in plain words: the look's own note, then the guide's bold-led rules ("**Rose stays
    an accent.** Use it for ...") as their lead plus the next sentence when it carries no code."""
    out = []
    note = (st or {}).get("notes")
    if isinstance(note, str) and note.strip():
        out.append(note.strip())
    for ln in str(text or "").splitlines():
        m = re.match(r"^\s*[-*]\s+\*\*(.+?)\*\*\s*(.*)$", ln)
        if not m:
            continue
        lead = m[1].strip()
        if "`" in lead or "--" in lead:
            continue
        rest = re.split(r"(?<=[.!?])\s", m[2].strip())[0] if m[2].strip() else ""
        if not rest or "`" in rest or re.search(r"--|[{};]|\bvar\(", rest):
            rest = ""
        if not rest and len(lead.split()) <= 2:
            continue                                            # "Section padding." alone says nothing
        rule = f"{lead.rstrip('.:')}: {rest}" if rest else lead.rstrip(":")
        rule = re.sub(r"\s+", " ", rule.replace("**", "")).strip()
        rule = re.sub(r"\b[Tt]he charter\b", "the brief", re.sub(r"\b(?:the )?Requester\b", "you", rule))
        if rule and rule not in out:
            out.append(rule)
        if len(out) >= limit:
            break
    return out


def _doc_part_md(w, sections, doc_text):
    """The part of a PRD, HLD or LLD this part wrote: its own section body, else its headings cut from the document."""
    body = (sections.get(w.get("section") or w.get("id")) or {}).get("body") or ""
    if body and not re.search(r"<(?:section|div|html)\b", body, re.I):
        return body.strip()
    heads = [str(o)[3:].strip().lower() for o in w.get("outputs") or [] if str(o).startswith("## ")]
    if not doc_text or not heads:
        return ""
    out, keep = [], False
    for ln in doc_text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)$", ln)
        if m and len(m[1]) <= 2:
            keep = len(m[1]) == 2 and any(re.sub(r"[*_`]", "", m[2]).strip().lower().startswith(h) for h in heads)
        if keep:
            out.append(ln)
    return "\n".join(out).strip()


def _source_notes(entry):
    """[{url, label, note}] for a research entry: each source line's URLs with the line's own words as its note."""
    out, seen = [], set()
    for ln in str(entry or "").splitlines():
        urls = re.findall(r"https?://[^\s)>\],]+", ln)
        if not urls:
            continue
        rest = re.sub(r"https?://[^\s)>\],]+", "", ln)
        m = re.search(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)", rest)
        note = (m[1] if m else rest).strip(" -*:,;")
        note = re.sub(r"\s*\band\s*$", "", re.sub(r"\s+", " ", note)).strip()
        for u in urls:
            u = u.rstrip(".")
            if u in seen:
                continue
            seen.add(u)
            out.append({"url": u, "label": re.sub(r"^https?://(?:www\.)?", "", u).split("/")[0],
                        "note": note[:1].upper() + note[1:] if note else ""})
    return out


def output_payload(wid, wfs, run_dir, sections, style, stage_of, version_url, doc_md=None):
    """/api/v2/output?id=W-n: the payload behind a finished part's "See output", from the run's own files."""
    w = next((x for x in wfs if x.get("id") == wid), None)
    if not w:
        return None
    k = output_kind(w, stage_of(w))
    name = plain_name(w.get("name"))
    names = {x.get("id"): plain_name(x.get("name")) for x in wfs}
    out = {"id": wid, "name": name, **k}
    if k["kind"] == "research":
        text = ""
        try:
            with open(os.path.join(run_dir, "research.md"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            pass
        entries = j2.research_entries(text)
        rid = j2.research_id(w)
        entry = entries.get(rid) if rid else next(iter(entries.values()), "")
        q = re.search(r"\*\*Question:\*\*\s*(.+)", entry or "")
        out.update(question=plain_line(q[1], {}, cap=200) if q else None, sources=_source_notes(entry)[:12])
    elif k["kind"] == "section":
        body = (sections.get(w.get("section") or wid) or {}).get("body") or ""
        m = re.search(r'\sid="([\w-]+)"', body)
        out.update(anchor=m[1] if m else None, url=version_url)
    elif k["kind"] == "style":
        st = style or {}
        pal = st.get("palette") or {}
        out.update(look=st.get("direction") or st.get("name"),
                   palette=[{"name": n.capitalize(), "hex": v} for n, v in pal.items()
                            if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}", v)][:8],
                   fonts={"heading": (st.get("fonts") or {}).get("heading"), "body": (st.get("fonts") or {}).get("body")},
                   radius=st.get("radius"))
        f = next((o for o in w.get("outputs") or [] if str(o).endswith(".md")), None)
        out.update(rules=style_rules(_read_artifact(run_dir, f) if f else "", st))
    elif k["kind"] == "notes":
        f = next((o for o in w.get("outputs") or [] if str(o).endswith(".md")), None)
        text = _read_artifact(run_dir, f) if f else ""
        out.update(points=_md_points(text), markdown=artifact_markdown(text, names) or None)
    elif k["kind"] == "document":
        md = _doc_part_md(w, sections, doc_md(k.get("doc")) if doc_md and k.get("doc") else "")
        out.update(markdown=artifact_markdown(j2.reader_words(md), names) or None)
    elif k["kind"] == "page":
        out.update(url=version_url)
    return out


def output_live(run, wid):
    wfs = run._all_wfs()
    stage_of_wf = {x: k for k, v in run.docs.items() for x in v.get("workflows") or []}
    stage_of = lambda w: stage_of_wf.get(w["id"]) or (run.stage_kind if run.doc else None) or w.get("stage")
    return output_payload(wid, wfs, run.dir, run.sections or {}, run.style, stage_of,
                          f"/site/v{len(run.sites)}" if run.sites else None, lambda kind: doc_text(run, kind))


def output_saved(name, wid):
    d = j2.saved_dir(name)
    if not d:
        return None
    snap = j2.saved_snapshot(name)
    docs = j2._read(d, "documents.json", {}) or {}
    stage_of_wf = {x: k for k, v in docs.items() for x in v.get("workflows") or []}
    return output_payload(wid, snap["workflows"] or [], d, j2._read(d, "sections.json", {}) or {},
                          j2._read(d, "style.json", None), lambda w: stage_of_wf.get(w["id"]) or w.get("stage"),
                          f"/site/latest?run={name}", lambda kind: doc_text(None, kind, name))


# ------------------------------------------------------------------ the studio view: who makes each part, the live output

# The studio view (ui/studio.html) shows the team as five friendly people, not six org boxes: the makers are grouped by
# what a part is. `part_kind` is that tag, by code from the part's own metadata (its name, its output, its stage):
# writer (copy, content, a document's prose), designer (the look, visual sections) or builder (forms, navigation, the
# shell, technical specs). The first rule that matches wins, so "Add testimonials link to nav" is a builder's part.
DOC_KINDS = ("prd", "hld", "lld")
KIND_BUILD = re.compile(r"\b(?:forms?|booking|nav|navigation|navbar|header|footer|shell|integrations?|whatsapp|maps?|"
                        r"filters?|search|scripts?|visible|links?|anchors?|overflow|responsive|interactive|engineering|"
                        r"apis?|database|data model|data flow|schema|architecture|components?|security|hosting|deploy\w*|"
                        r"infrastructure|file structure|performance|tests?|code)\b", re.I)
KIND_DESIGN = re.compile(r"\b(?:hero|banner|portfolio|gallery|showcase|visuals?|imagery|images?|photos?|illustrations?|"
                         r"style|look|palette|brand|logo|layout|design|redesign|polish|theme|empty state|scenes?|icons?|"
                         r"wireframes?|ux|ui)\b", re.I)
KIND_UX = re.compile(r"\b(?:wireframes?|ux|ui|visual design|look and feel|brand|style)\b", re.I)    # inside a document
KIND_WRITE = re.compile(r"\b(?:copy|text|content|faq|questions|about|story|team|testimonials?|reviews?|services?|menu|"
                        r"pricing|prices?|process|steps|how we work|hours|contact info|address|location|visit|scope|"
                        r"outline|brief|requirements?|problem|users?|personas?|goals?|metrics|research|purpose|risks?)\b",
                        re.I)
STAGE_KIND = {"content": "writer", "product": "writer", "design": "designer", "engineering": "builder", "build": "builder"}


def part_kind(w, stage=None):
    """writer | designer | builder: who on the studio team makes this part (api-contract.md, map buildings `kind`).
    By code from the part's name, its output kind and its stage; a part nothing matches falls back to its stage's
    kind (content and product: writer, design: designer), else builder."""
    name = str(w.get("name") or "").replace("_", " ")
    in_doc = stage in DOC_KINDS
    if w.get("kind") == "polish":
        return "writer" if in_doc else "designer"
    out = output_kind(w, stage)["kind"]
    if out == "style":
        return "designer"
    if out == "document" or in_doc:          # a section of a PRD, HLD or LLD: prose, unless it is technical or visual
        return "builder" if KIND_BUILD.search(name) else "designer" if KIND_UX.search(name) else "writer"
    for kind, rx in (("builder", KIND_BUILD), ("designer", KIND_DESIGN), ("writer", KIND_WRITE)):
        if rx.search(name):
            return kind
    if out == "research":
        return "writer"
    return STAGE_KIND.get(w.get("stage") or stage, "builder")


# The live output: what the centre of the studio view shows while the team works (/api/v2/live). A website is the page
# as assembled so far (assemble(), the same code every version uses): built sections are real, a section still to come
# is a calm placeholder, and every section's first element carries data-j2-section="<section id>" so the page can find
# it (a part maps to its section in `anchors`). A document is its current text in blocks, one per "## " section, each
# with the parts that wrote it; a section still to come is a placeholder block.
WAIT_CSS = ("<style>[data-j2-wait]{display:block;box-sizing:border-box;width:calc(100% - 32px);max-width:1080px;"
            "margin:24px auto;padding:28px 24px 22px;border:1.5px dashed #d8cfbf;border-radius:12px;background:transparent;"
            "color:#9b9284;font:15px/1.45 system-ui,-apple-system,sans-serif;text-align:left}"
            "[data-j2-wait] .j2-wait-name{margin:0 0 2px;font-weight:600;color:#7d7466}"
            "[data-j2-wait] .j2-wait-note{margin:0 0 14px;font-size:13px}"
            "[data-j2-wait] i{display:block;height:8px;border-radius:4px;background:#ebe5da;margin:8px 0;width:72%}"
            "[data-j2-wait] i+i{width:54%}[data-j2-wait] i+i+i{width:63%}</style>")
SECTION_PARTS = ("section", "page")


def _tag_first(body, sid):
    """The section's markup with data-j2-section on its first element (layout untouched); a section that starts with
    bare text gets a zero-size marker in front instead."""
    attr = f' data-j2-section="{sid}"'
    out, n = re.subn(r"^(\s*(?:<!--.*?-->\s*)*<[a-zA-Z][\w-]*)", lambda m: m.group(1) + attr, body, count=1, flags=re.S)
    return out if n else f'<j2-mark{attr} style="display:block;height:0"></j2-mark>' + body


def _wait_section(sid, name, ended):
    import html as _html
    nm = _html.escape(name or "This part")
    note = "Not built in this run" if ended else "Coming up"
    return (f'<section data-j2-section="{sid}" data-j2-wait="1" aria-label="{nm}: {note.lower()}">'
            f'<p class="j2-wait-name">{nm}</p><p class="j2-wait-note">{note}</p><i></i><i></i><i></i></section>')


def _plan_slots(wfs, has_body, is_slot):
    """Section id -> (index of the first part that writes it, that part), for the parts that make a section; and part
    id -> section id for every part whose section is on the page or will be."""
    first, anchors = {}, {}
    for i, w in enumerate(wfs):
        sid = w.get("section")
        if not sid or w.get("status") == "unfunded" or w.get("kind") == "polish":     # the polish revises the whole page
            continue
        if has_body(sid) or is_slot(w):
            first.setdefault(sid, (i, w))
            anchors[w["id"]] = sid
    return first, anchors


def _with_pending(real, first, has_body):
    """[(sid, real-or-None)]: the real items in their own order, each section still to come placed just before the
    first real one planned after it (so a placeholder sits where its part will land)."""
    queue = sorted((s for s in first if not has_body(s)), key=lambda s: first[s][0])
    out = []
    for sid, x in real:
        while queue and sid in first and first[queue[0]][0] < first[sid][0]:
            out.append((queue.pop(0), None))
        out.append((sid, x))
    return out + [(s, None) for s in queue]


def live_site(title, wfs, sections, ended=False):
    """(html, anchors, pending): the website as it stands, for the studio view's centre (see above)."""
    sections = sections or {}
    has_body = lambda s: bool((sections.get(s) or {}).get("body") or (sections.get(s) or {}).get("head"))   # a styling part writes only CSS
    first, anchors = _plan_slots(wfs, has_body, lambda w: output_kind(w, w.get("stage"))["kind"] in SECTION_PARTS)
    real = [(s, x) for s, x in sections.items() if s == "style" or (s in first and (x.get("body") or x.get("head")))]
    page = {}
    for sid, x in _with_pending(real, first, has_body):
        if x is None:
            page[sid] = {"owner": first[sid][1]["id"], "head": "", "body": _wait_section(sid, plain_name(first[sid][1].get("name")), ended)}
        else:
            page[sid] = {**x, "body": _tag_first(x["body"], sid) if x.get("body") else ""}
    anchors = {wid: sid for wid, sid in anchors.items() if (page.get(sid) or {}).get("body")}    # only what the page shows
    page = {"j2-wait": {"owner": "studio", "head": WAIT_CSS, "body": ""}, **page}
    pending = [s for s in first if not has_body(s)]
    return j2.assemble(title or "Your website", page), anchors, pending


def _split_doc(md):
    """[(heading or None, markdown)]: a document cut at its "## " headings; the "# title" line is left out."""
    blocks, cur, head = [], [], None
    for ln in str(md or "").splitlines():
        m = j2.MD_HEADING.match(ln)
        if m and len(m[1]) == 1 and not blocks and not any(x.strip() for x in cur):
            continue
        if m and len(m[1]) == 2:
            if head is not None or any(x.strip() for x in cur):
                blocks.append((head, "\n".join(cur).strip()))
            head, cur = m[2], [ln]
            continue
        cur.append(ln)
    if head is not None or any(x.strip() for x in cur):
        blocks.append((head, "\n".join(cur).strip()))
    return blocks


def live_doc(kind, wfs, sections, doc_md, ended=False):
    """(blocks, anchors): a PRD, HLD or LLD as it stands, one block per "## " section with the parts that wrote it;
    sections still to come are placeholder blocks (see above)."""
    sections = sections or {}
    has_body = lambda s: bool((sections.get(s) or {}).get("body"))
    is_slot = lambda w: bool({"doc_section", "requirements_section"} & set(w.get("parts") or []))
    first, anchors = _plan_slots(wfs, has_body, is_slot)
    key = lambda t: j2.squash(j2.strip_md(t or ""))
    by_head = {}
    for sid, x in sections.items():
        h = next((m[2] for ln in (x.get("body") or "").splitlines() if (m := j2.MD_HEADING.match(ln))), None)
        if h and sid in first:
            by_head.setdefault(key(h), sid)
    parts_of = {}
    for wid, sid in anchors.items():
        parts_of.setdefault(sid, []).append(wid)
    text = _split_doc(doc_md) if doc_md else [(None, (sections[s].get("body") or "").strip()) for s in first if has_body(s)]
    real = []
    for head, md in text:
        sid = by_head.get(key(head)) if head else None
        if sid is None and not doc_md:
            sid = next((s for s in first if has_body(s) and (sections[s].get("body") or "").strip() == md), None)
        real.append((sid, md))
    out, seen = [], set()
    for sid, md in _with_pending([(s if s not in seen and not seen.add(s) else None, md) for s, md in real], first, has_body):
        if md is None:
            out.append({"anchor": sid, "parts": parts_of.get(sid, []), "state": "waiting", "markdown": None,
                        "name": plain_name(first[sid][1].get("name")), "note": "Not written in this run" if ended else "Coming up"})
        else:
            out.append({"anchor": sid, "parts": parts_of.get(sid, []) if sid else [], "state": "done",
                        "markdown": j2.reader_words(md), "name": None, "note": None})
    return out, anchors


def live_payload(kind, title, wfs, sections, doc_md=None, ended=False, site_url="/api/v2/live/site"):
    """/api/v2/live for one deliverable (api-contract.md). Pure assembly from the run's own state."""
    import hashlib
    kinds = {w["id"]: part_kind(w, kind if kind in DOC_KINDS else w.get("stage")) for w in wfs}
    if kind in DOC_KINDS:
        blocks, anchors = live_doc(kind, wfs, sections, doc_md, ended)
        body = {"kind": "document", "doc": kind, "blocks": blocks}
    else:
        html_out, anchors, pending = live_site(title, wfs, sections, ended)
        has = any(s != "style" and (sections or {}).get(s, {}).get("body") for s in anchors.values())
        body = {"kind": "website", "doc": None, "url": site_url if anchors else None, "pending": pending,
                "started": bool(anchors), "built": bool(has)}
        blocks = html_out
    key = hashlib.sha1(json.dumps([body, blocks, anchors], sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return {**body, "title": title or "", "anchors": anchors, "part_kinds": kinds, "key": key}


def _live_kinds(kinds, cur):
    kinds = [k for k in kinds if k in LABELS] or ["website"]
    return kinds, (cur if cur in kinds else kinds[-1])


def studio_live(run, kind=None):
    """(payload, html or None) for the live run: the deliverable asked for (default: the one being made now)."""
    kinds, cur = _live_kinds(list(run.stages or [run.output]), run.stage_kind or run.output)
    kind = kind if kind in kinds else cur
    st, _ = run.run_status()
    ended = STATUS.get(st) in ENDED and bool(run.chat)
    title = (run.goal or {}).get("site_name") or (run.goal or {}).get("product_name") or \
        (j2.short(run.request, 6) if run.request else "")
    if kind == cur:
        # copies: the build threads write sections and register parts while the page is read
        wfs, sections = list(run.workflows), dict(run.sections or {})
        doc_md = run.sites[-1] if kind in DOC_KINDS and run.doc and run.sites else None
    elif kind in run.docs:
        ids = set(run.docs[kind].get("workflows") or [])
        wfs = [w for w in run.past_workflows if w["id"] in ids]
        sections = next((a.get("sections") or {} for a in run.stage_archive if a.get("stage") == kind), {})
        doc_md = doc_text(run, kind)
    else:
        wfs, sections, doc_md = [], {}, None
    if kind not in DOC_KINDS:
        html_out = live_site(title, wfs, sections, ended)[0]
        return live_payload(kind, title, wfs, sections, None, ended), html_out
    return live_payload(kind, title, wfs, sections, doc_md, ended), None


def studio_saved(name, kind=None):
    """(payload, html or None) for a saved run folder (nothing moves; a part never built reads "Not built")."""
    d = j2.saved_dir(name)
    if not d:
        return None, None
    s = j2._read(d, "summary.json", {}) or {}
    docs = j2._read(d, "documents.json", {}) or {}
    out = j2.saved_output(d)
    on_disk = [k for k in DOC_KINDS if os.path.exists(os.path.join(d, f"{k}.md"))]
    kinds = list((s.get("design_documents") or {}).get("stages") or list(docs) or [out])
    kinds = [k for k in DOC_KINDS if k in kinds or k in on_disk] + [k for k in kinds if k not in DOC_KINDS]
    if out == "website" and "website" not in kinds:
        kinds.append("website")
    wfs_all = j2._read(d, "workflows.json", []) or []
    mapped = {wid: k for k, v in docs.items() for wid in v.get("workflows") or []}
    unmapped = [w for w in wfs_all if w["id"] not in mapped]
    # the deliverable shown first: the last one with something in it (a chain stopped in its LLD opens on the LLD)
    has = lambda k: bool([w for w in wfs_all if mapped.get(w["id"]) == k] or (k in DOC_KINDS and k in on_disk)) or \
        (k not in DOC_KINDS and bool(unmapped)) or (k in DOC_KINDS and k not in docs and bool(unmapped))
    kinds, cur = _live_kinds(kinds, next((k for k in reversed(kinds) if has(k)), None))
    kind = kind if kind in kinds else cur
    goal = j2._read(d, "goal.json", {}) or {}
    title = goal.get("site_name") or goal.get("product_name") or ""
    if kind in docs:
        wfs = [w for w in wfs_all if mapped.get(w["id"]) == kind]
        sections = (j2._read(d, f"stage-{kind}.json", {}) or {}).get("sections") or j2._read(d, "sections.json", {}) or {}
    else:
        wfs, sections = unmapped, j2._read(d, "sections.json", {}) or {}
    url = f"/api/v2/live/site?run={name}"
    if kind not in DOC_KINDS:
        html_out = live_site(title, wfs, sections, True)[0]
        return live_payload(kind, title, wfs, sections, None, True, url), html_out
    return live_payload(kind, title, wfs, sections, doc_text(None, kind, name), True, url), None
