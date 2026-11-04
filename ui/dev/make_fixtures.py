"""Writes ui/dev/fixtures/*.json: one /api/v2/state snapshot per UI state.

Run: python3 ui/dev/make_fixtures.py
Extra keys used only by fixture mode (stripped before the UI sees them):
  _sim   simulated movement while working (backstage lines, usage per tick, preview bump, map fill rate)
  _next  which fixture to load after an answer: {"<option_id>" | "say" | "*" | "new" | "stop": "<fixture>"}
  map    the kingdom view's data (served by the fixture api as /api/v2/map; the simulator moves it)
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")
# the plan card's model choice (api-contract.md, proposal.models; the real list comes from llm.MODEL_TIERS)
MODELS = [{"id": "fable", "label": "Fable · best quality", "suggested": False, "multiplier": 1.5},
          {"id": "opus", "label": "Opus · great", "suggested": False, "multiplier": 1.3},
          {"id": "sonnet", "label": "Sonnet · balanced", "suggested": True, "multiplier": 1.0},
          {"id": "haiku", "label": "Haiku · fastest, cheapest", "suggested": False, "multiplier": 0.8}]
SITE = "/ui/dev/samples/site.html"

REQUEST = "A one-page website for my physio clinic in Indiranagar. Services, hours, and a way to book on WhatsApp."


def chat(*rows):
    """Chat lines: ("you" | "team", text), or a record() dict (an answered decision's compact record)."""
    out = []
    for i, row in enumerate(rows):
        t = f"10:{15 + i:02d}:0{i % 10}"
        if isinstance(row, dict):
            out.append({"id": i + 1, "t": t, "from": "team", "kind": "record", **row})
        else:
            out.append({"id": i + 1, "t": t, "from": row[0], "text": row[1]})
    return out


def record(title, summary, answer, detail=()):
    return {"title": title, "summary": summary, "answer": answer, "detail": list(detail)}


PLAN_RECORD = record("Plan approved", "A one-page website for Still Water Physio · 7 parts · about 2.1M", "Approved")
LOOK_RECORD = record("Look: Warm and friendly", "Warm tones and rounded shapes; feels like being welcomed in.", "Warm and friendly")
LOOKS = [
    {"id": "s1", "label": "Calm and airy", "gets": "Light, spacious and quiet; suits a place people visit to feel better.",
     "usage": 0, "suggested": False, "preview_url": "/ui/dev/samples/preview-1.html",
     "inspired_by": {"label": "cruip/open-react-template", "url": "https://github.com/cruip/open-react-template"}},
    {"id": "s2", "label": "Warm and friendly", "gets": "Warm tones and rounded shapes; feels like being welcomed in.",
     "usage": 0, "suggested": True, "preview_url": "/ui/dev/samples/preview-2.html",
     "inspired_by": {"label": "Land-book: health and wellness", "url": "https://land-book.com/"}},
    {"id": "s3", "label": "Clean and clinical", "gets": "Crisp, precise and trustworthy; suits a professional practice.",
     "usage": 0, "suggested": False, "preview_url": "/ui/dev/samples/preview-3.html",
     "inspired_by": {"label": "Physio clinic live site", "url": "https://www.physio.co.uk/"}},
]


# "See details": the structured, plain detail behind a few lines (api-contract.md, backstage detail.kind). Lines not
# listed here carry an empty generic detail (no "See details").
PLAN_STAGES = [
    {"name": "Planning", "parts": [
        {"name": "Brief", "purpose": "What the site must say and do, in one page.", "waits_for": [], "share": "200k", "share_pct": 12}]},
    {"name": "Design", "parts": [
        {"name": "Look and feel", "purpose": "Calm colours and type that suit a clinic.", "waits_for": ["Brief"], "share": "250k", "share_pct": 15}]},
    {"name": "Building", "parts": [
        {"name": "Services list", "purpose": "The three main treatments, in plain words.", "waits_for": ["Brief"], "share": "260k", "share_pct": 16},
        {"name": "Opening hours", "purpose": "When the clinic is open, including Sunday.", "waits_for": ["Services list"], "share": "200k", "share_pct": 12},
        {"name": "Booking on WhatsApp", "purpose": "Lets visitors ask for an appointment on WhatsApp.", "waits_for": ["Opening hours"], "share": "300k", "share_pct": 18},
        {"name": "Questions people ask", "purpose": "Short answers about cost, parking and first visits.", "waits_for": ["Services list"], "share": "180k", "share_pct": 11}]},
    {"name": "Checking", "parts": [
        {"name": "Phone and computer check", "purpose": "Makes sure it reads well on every screen.", "waits_for": ["Booking on WhatsApp", "Questions people ask"], "share": "240k", "share_pct": 15}]},
]
DETAILS = {
    "Here are 7 parts, about 2.1M in total.": {
        "kind": "plan", "decided": "Parts: Brief, Look and feel, Services list, Opening hours, Booking on WhatsApp, "
                                   "Questions people ask, Phone and computer check.",
        "why": "Every item on the checklist has a part that delivers it, and the booking part is the biggest because it "
               "is the one thing the brief asks visitors to do.",
        "summary": "7 parts in 4 stages.", "stages": PLAN_STAGES, "total": "1.6M",
        "confidence": "The plan reviewer is very sure of this plan (95%).", "not_ready": []},
    "Fits. Keep the FAQ short so the booking part has room.": {
        "kind": "budget", "decided": "Decision: grant.",
        "why": "The total sits under the budget, and the booking part keeps the largest share because it is on the "
               "checklist twice.",
        "summary": "Granted: 7 parts, 1.6M in total.",
        "rows": [{"label": "Brief", "value": "200k"}, {"label": "Look and feel", "value": "250k"},
                 {"label": "Services list", "value": "260k"}, {"label": "Opening hours", "value": "200k"},
                 {"label": "Booking on WhatsApp", "value": "300k"},
                 {"label": "Questions people ask", "value": "180k (asked 220k)"},
                 {"label": "Phone and computer check", "value": "240k"}]},
    "The plan covers everything they asked for.": {
        "kind": "checks", "decided": "Verdict: pass.", "why": None,
        "what": "The plan reviewer read every part against your checklist.", "summary": "All 4 passed.",
        "items": [{"name": "Every checklist item has a part", "pass": True, "reason": "Eight items, each covered once."},
                  {"name": "Each part can start", "pass": True, "reason": "Nothing waits on a part that doesn't exist."},
                  {"name": "Each part has a check that proves it", "pass": True, "reason": None},
                  {"name": "The facts come from your brief", "pass": True, "reason": "Hours and number are yours, not made up."}]},
    "They chose the warm look. Build with it.": {
        "kind": "decision", "decided": None, "why": None, "asked": "Which look should the website have?",
        "chosen": "Warm and friendly", "by": "You"},
    "Sunday is missing. Say it's closed.": {
        "kind": "checks", "decided": "Not done yet: one check failed.",
        "why": "The checklist says the hours must cover every day of the week, and Sunday isn't on the page.",
        "what": "Code ran the checks for Opening hours.", "summary": "2 of 3 passed, 1 did not.",
        "items": [{"name": "The hours section is on the page", "pass": True, "reason": "Found under Opening hours."},
                  {"name": "Saturday shows the short day", "pass": True, "reason": "Saturday 9 to 2."},
                  {"name": "Every day of the week is listed", "pass": False, "reason": "Sunday isn't on the page."}]},
    "On track. About 1.1M left for four parts.": {
        "kind": "budget", "decided": None, "why": None, "summary": "Every share fits, so the work runs now.",
        "rows": [{"label": "Booking on WhatsApp", "value": "300k share, 0 used"},
                 {"label": "Used so far", "value": "1.3M of 2.4M"}, {"label": "Left to use", "value": "1.1M"}]},
    "Writing the hours section now.": {
        "kind": "generic", "decided": None,
        "why": "The hours they gave cover Monday to Saturday, so I am writing those first and asking about Sunday."},
}


def detail(text):
    d = DETAILS.get(text)
    return dict(d) if d else {"kind": "generic", "decided": None, "why": None}


def back(rows, active_last=True):
    out = []
    for i, (f, to, text) in enumerate(rows):
        out.append({"id": i + 1, "t": f"10:{16 + i // 3:02d}:{(i * 7) % 60:02d}", "from": f, "to": to, "text": text,
                    "active": active_last and i == len(rows) - 1, "detail": detail(text)})
    return out


def task(tid, name, summary, status, usage, share, waits=None):
    return {"id": tid, "name": name, "summary": summary, "status": status,
            "waits_for": waits or [], "usage": usage, "share": share}


def site_plan(stage="building"):
    """The physio plan at a given point: 'proposal', 'building', 'done', 'done_open'."""
    s = {
        "proposal": dict(brief="waiting", look="waiting", svc="waiting", hours="waiting", book="waiting", faq="waiting", check="waiting"),
        "building": dict(brief="done", look="done", svc="done", hours="working", book="waiting", faq="working", check="waiting"),
        "done": dict(brief="done", look="done", svc="done", hours="done", book="done", faq="done", check="done"),
        "done_open": dict(brief="done", look="done", svc="done", hours="needs_fix", book="done", faq="done", check="done"),
        "stopped": dict(brief="done", look="done", svc="done", hours="done", book="working", faq="skipped", check="skipped"),
    }[stage]
    u = {
        "proposal": dict(brief=0, look=0, svc=0, hours=0, book=0, faq=0, check=0),
        "building": dict(brief=180000, look=210000, svc=240000, hours=96000, book=0, faq=41000, check=0),
        "done": dict(brief=180000, look=210000, svc=240000, hours=170000, book=260000, faq=150000, check=190000),
        "done_open": dict(brief=180000, look=210000, svc=240000, hours=200000, book=260000, faq=150000, check=210000),
        "stopped": dict(brief=180000, look=210000, svc=240000, hours=170000, book=120000, faq=0, check=0),
    }[stage]
    return {"groups": [
        {"name": "Planning", "tasks": [
            task("W-1", "Brief", "What the site must say and do, in one page.", s["brief"], u["brief"], 200000)]},
        {"name": "Design", "tasks": [
            task("W-2", "Look and feel", "Calm colours and type that suit a clinic.", s["look"], u["look"], 250000, ["Brief"])]},
        {"name": "Building", "tasks": [
            task("W-3", "Services list", "The three main treatments, in plain words.", s["svc"], u["svc"], 260000, ["Brief"]),
            task("W-4", "Opening hours", "When the clinic is open, including Sunday.", s["hours"], u["hours"], 200000, ["Services list"]),
            task("W-5", "Booking on WhatsApp", "Lets visitors ask for an appointment on WhatsApp.", s["book"], u["book"], 300000, ["Opening hours"]),
            task("W-6", "Questions people ask", "Short answers about cost, parking and first visits.", s["faq"], u["faq"], 180000, ["Services list"])]},
        {"name": "Checking", "tasks": [
            task("W-7", "Phone and computer check", "Makes sure it reads well on every screen.", s["check"], u["check"], 240000,
                 ["Booking on WhatsApp", "Questions people ask"])]},
    ]}


PARTS = ["Brief", "Look and feel", "Services list", "Opening hours", "Booking on WhatsApp", "Questions people ask",
         "Phone and computer check"]

BACKSTAGE = [
    ("Client lead", "Planner", "They want one page: services, hours and WhatsApp booking."),
    ("Planner", "Budget lead", "Here are 7 parts, about 2.1M in total."),
    ("Budget lead", "Planner", "Fits. Keep the FAQ short so the booking part has room."),
    ("Plan reviewer", "Planner", "The plan covers everything they asked for."),
    ("Client lead", "Planner", "They chose the warm look. Build with it."),
    ("Scheduler", "Builder · Brief", "You're first. The others wait on you."),
    ("Builder · Brief", "Gatekeeper", "Brief is written. Ready for a look."),
    ("Gatekeeper", "Scheduler", "Brief passes. Design can start."),
    ("Builder · Look and feel", "Gatekeeper", "Colours and type picked. Sage green, warm sand."),
    ("Builder · Services list", "Gatekeeper", "Three services written, each one short."),
    ("Gatekeeper", "Scheduler", "Services list passes."),
    ("Scheduler", "Builder · Opening hours", "Your turn. Use the hours they gave."),
    ("Builder · Opening hours", "Gatekeeper", "Writing the hours section now."),
]

SIM_LINES = [
    {"from": "Builder · Opening hours", "to": "Gatekeeper", "text": "Hours are in. Saturday closes at 2pm.", "status_text": "Building your opening hours"},
    {"from": "Gatekeeper", "to": "Builder · Opening hours", "text": "Sunday is missing. Say it's closed.", "status_text": "Fixing the opening hours"},
    {"from": "Builder · Opening hours", "to": "Gatekeeper", "text": "Added: Sunday, closed.", "status_text": "Checking the opening hours"},
    {"from": "Quality check", "to": "Scheduler", "text": "Hours read well on a phone.", "status_text": "Checking the opening hours"},
    {"from": "Scheduler", "to": "Builder · Booking on WhatsApp", "text": "You're up next. The hours are ready.", "status_text": "Building your booking button"},
    {"from": "Builder · Booking on WhatsApp", "to": "Gatekeeper", "text": "Drafting the message visitors will send.", "status_text": "Building your booking button"},
    {"from": "Budget lead", "to": "Scheduler", "text": "On track. About 1.1M left for four parts.", "status_text": "Building your booking button"},
]


SIM_LINES = [{**ln, "detail": detail(ln["text"])} for ln in SIM_LINES]


def usage(spent, budget=2400000, estimate=2100000):
    if budget is None:
        return {"budget": None, "spent": spent, "margin_at": None, "estimate": estimate,
                "by_phase": {"planning": spent, "building": 0, "checking": 0, "other": 0}}
    return {"budget": budget, "spent": spent, "margin_at": int(budget * 0.85), "estimate": estimate,
            "by_phase": {"planning": 600000, "building": max(0, spent - 750000), "checking": 150000, "other": 0}}


def base(run_id, title="Still Water Physio"):
    return {"run": {"id": run_id, "saved": False, "title": title}, "status": "working", "status_text": "",
            "usage": None, "decision": None, "chat": [], "backstage": [], "working_now": None,
            "plan": None, "deliverables": [], "ended": None, "settings": {"no_questions": False},
            "control": {"paused": False, "pausing": False, "stopping": False},
            "map": {"departments": [], "units": [], "buildings": [], "flows": [], "attention": None, "counts": {"done": 0, "total": 0}}}


# ---- the kingdom view's map (api-contract.md, /api/v2/map) ----
DEPS = {"W-1": [], "W-2": ["W-1"], "W-3": ["W-1"], "W-4": ["W-3"], "W-5": ["W-4"], "W-6": ["W-3"], "W-7": ["W-5", "W-6"]}
CORE = [("u-identity", "client", "Client lead"), ("u-adaptation", "planner", "Planner"), ("u-priority", "budget", "Budget lead"),
        ("u-coordination", "scheduler", "Scheduler"), ("u-validator", "gatekeeper", "Gatekeeper"), ("u-audit", "quality", "Quality check")]
DOING_CORE = {"u-identity": "Reading your request", "u-adaptation": "Planning the work", "u-priority": "Agreeing the usage",
              "u-coordination": "Scheduling the work", "u-validator": "Checking the plan", "u-audit": "Checking the result"}
FIX_LINE = {"W-4": "Sunday isn't shown as closed"}
# "See output" (api-contract.md /api/v2/output): what each finished part made, by kind
OUT_KIND = {"W-1": "notes", "W-2": "style", "D-1": "notes", "D-2": "document", "D-3": "document", "D-4": "document",
            "D-5": "document", "D-6": "document"}
OUTPUTS = {
    "W-1": {"id": "W-1", "name": "Brief", "kind": "notes", "points": [
        "Hero: the clinic's name, Indiranagar, and one Book on WhatsApp button.",
        "Services: three treatments, each with a one-line description and a price.",
        "Opening hours: every day of the week, Sunday closed.", "Booking: a WhatsApp link with a short prefilled message.",
        "Questions people ask: cost, parking, first visit.", "Footer: address, phone and a map link."],
        "markdown": "# Still Water Physio: page plan\n\nOne page for Still Water Physio in Indiranagar. Every later part "
                    "follows this document. Copy every name, price and time exactly as written here.\n\n"
                    "## Section order\n\n| # | Section | Built by |\n|---|---|---|\n| 1 | Hero | hero part |\n"
                    "| 2 | Services | services part |\n| 3 | Opening hours | hours part |\n| 4 | Booking | booking part |\n"
                    "| 5 | Questions people ask | questions part |\n\n## Hero\n\n- The clinic's name, Indiranagar, and one "
                    "**Book on WhatsApp** button that links to the booking section.\n\n## Services\n\n- Sports injury "
                    "rehab: Rs 1,200 a session\n- Back and neck care: Rs 1,000 a session\n- Home visits: Rs 1,800 a visit\n\n"
                    "## Opening hours\n\nMonday to Saturday, 8am to 8pm. Sunday closed."},
    "W-2": {"id": "W-2", "name": "Look and feel", "kind": "style", "look": "Warm and friendly",
            "palette": [{"name": "Primary", "hex": "#b5522a"}, {"name": "Secondary", "hex": "#f6e7dc"},
                        {"name": "Accent", "hex": "#2a6f5f"}, {"name": "Background", "hex": "#fffaf5"},
                        {"name": "Text", "hex": "#2b1d16"}, {"name": "Muted", "hex": "#6e5a4f"}],
            "fonts": {"heading": "'Trebuchet MS', sans-serif", "body": "system-ui, sans-serif"}, "radius": "18px",
            "rules": ["Warm, rounded and friendly, with one terracotta accent for every main button.",
                      "Terracotta stays an accent: buttons, icons and thin rules only.",
                      "Write facts exactly: prices and hours as the brief gives them."]},
    "W-3": {"id": "W-3", "name": "Services list", "kind": "section", "anchor": "services", "url": "/ui/dev/samples/preview-2.html"},
    "W-4": {"id": "W-4", "name": "Opening hours", "kind": "section", "anchor": "hours", "url": "/ui/dev/samples/preview-2.html"},
    "W-5": {"id": "W-5", "name": "Booking on WhatsApp", "kind": "section", "anchor": "book", "url": "/ui/dev/samples/preview-2.html"},
    "W-6": {"id": "W-6", "name": "Questions people ask", "kind": "section", "anchor": "faq", "url": "/ui/dev/samples/preview-2.html"},
    "W-7": {"id": "W-7", "name": "Phone and computer check", "kind": "page", "url": "/ui/dev/samples/preview-2.html"},
    "R-1": {"id": "R-1", "name": "Research", "kind": "research", "question": "What do strong physio clinic sites do?",
            "sources": [{"url": "https://www.physio.co.uk/", "label": "physio.co.uk", "note": "A large clinic site: booking first, prices shown plainly"},
                        {"url": "https://land-book.com/", "label": "land-book.com", "note": "A gallery of clinic landing pages, for layout"}]},
}


def unit_of_label(label, units):
    return "castle" if label == "You" else next((u["id"] for u in units if u["label"] == label), None)


def map_of(plan, status, depts=(("d-website", "Website", "website"),), dept_of=None, core_dept=None, deps=DEPS,
           core_working=(), attention=None, backstage=(), flows_from=3):
    """The map for a fixture: departments, the core units (in the current department), a builder at every working
    part, one building per plan task with its progress, and the newest hand-offs of the backstage as flows."""
    cur = core_dept or depts[-1][0]
    tasks = [t for g in plan["groups"] for t in g["tasks"]] if plan else []
    units = []
    for uid, role, label in CORE:
        st = "working" if uid in core_working and status == "working" else "waiting" if uid == "u-identity" and status == "needs_you" else "idle"
        units.append({"id": uid, "role": role, "label": label, "dept": cur, "at": cur, "state": st,
                      "doing": DOING_CORE[uid] if st == "working" else "Waiting for your answer" if st == "waiting" else ""})
    buildings = []
    for t in tasks:
        st = t["status"]
        share = t["share"] or 0
        prog = {"done": 1.0, "working": round(0.1 + 0.8 * (t["usage"] / share if share else 0.4), 2), "needs_fix": 0.7}.get(st, 0.0)
        doing = {"done": "Done", "skipped": "Left out", "needs_fix": FIX_LINE.get(t["id"], "Needs a fix"),
                 "working": f"Building {t['name'].lower()}",
                 "waiting": (f"Waits for {', '.join(t['waits_for'][:-1])} and {t['waits_for'][-1]}" if len(t["waits_for"]) > 1 else
                            f"Waits for {t['waits_for'][0]}") if t["waits_for"] else "Waiting its turn"}[st]
        d = (dept_of or {}).get(t["id"], cur)
        buildings.append({"id": t["id"], "name": t["name"], "dept": d, "progress": prog, "state": st,
                          "depends_on": list(deps.get(t["id"], [])), "usage": t["usage"], "share": share, "doing": doing,
                          "output": {"kind": OUT_KIND.get(t["id"], "section")} if st == "done" else None})
        if st == "working" or st == "needs_fix":
            units.append({"id": f"u-{t['id']}", "role": "builder", "label": f"Builder · {t['name']}", "dept": d, "at": t["id"],
                          "state": "working" if st == "working" and status == "working" else "idle",
                          "doing": doing if st == "working" and status == "working" else ""})
    flows = []
    for i, (f, to, text) in enumerate(list(backstage)[-flows_from:] if flows_from else []):
        a, b = unit_of_label(f, units), unit_of_label(to, units)
        if a and b and a != b:
            flows.append({"id": i + 1, "from": a, "to": b, "t": f"10:{20 + i:02d}:00", "what": text.split(". ")[0]})
    return {"departments": [{"id": i, "name": n, "kind": k} for i, n, k in depts], "units": units, "buildings": buildings,
            "flows": flows, "attention": attention if status == "needs_you" else None,
            "counts": {"done": sum(b["state"] == "done" for b in buildings), "total": len(buildings)}}


def site(state, version):
    return [{"kind": "website", "label": "Website", "state": state, "version": version, "url": SITE,
             "download": SITE}]


F = {}

# start: idle, empty
s = base("fx-start", None)
s["run"]["title"] = None
s["status"] = "idle"
s["_next"] = {"say": "proposal"}
F["start"] = s

# confirm: the AI is unsure what to make
s = base("fx-confirm")
s.update(status="needs_you", usage=usage(60000, None, None),
         chat=chat(("you", "Something for my physio clinic, people should be able to book."),
                   ("team", "Happy to help. One quick check first.")),
         backstage=back(BACKSTAGE[:1], False))
s["decision"] = {"id": "d-1", "kind": "confirm", "happening": "A one-page website with WhatsApp booking, right?",
                 "why": "This decides what we plan. A website is about 2M usage; adding a PRD is about 0.6M more.",
                 "options": [
                     {"id": "site", "label": "A website", "gets": "One page: services, hours, booking.", "usage": None, "suggested": True},
                     {"id": "both", "label": "A PRD, then a website", "gets": "A short requirements doc first.", "usage": None, "suggested": False},
                     {"id": "prd", "label": "Just a PRD", "gets": "Requirements only, no site.", "usage": None, "suggested": False}],
                 "fields": [], "allow_text": True, "proposal": None}
s["_next"] = {"*": "proposal"}
s["map"] = map_of(None, "needs_you", attention="u-identity", backstage=BACKSTAGE[:1])
F["confirm"] = s

# proposal
s = base("fx-proposal")
s.update(status="needs_you", usage=usage(180000, None), plan=site_plan("proposal"),
         chat=chat(("you", REQUEST), ("team", "Thanks. Here's what I'd make.")),
         backstage=back(BACKSTAGE[:4], False))
s["decision"] = {"id": "d-2", "kind": "proposal", "happening": "The plan is ready.", "why": "",
                 "options": [
                     {"id": "approve", "label": "Approve", "gets": "Budget set to 2.4M (the estimate plus a safety margin).", "usage": 2100000, "suggested": True},
                     {"id": "smaller", "label": "Make it smaller", "gets": "A trimmed plan that uses less.", "usage": None, "suggested": False},
                     {"id": "not_this", "label": "Not this", "gets": "Tell us what to change.", "usage": None, "suggested": False}],
                 "fields": [], "allow_text": False,
                 "proposal": {"summary": "A one-page website for Still Water Physio.", "parts": PARTS, "estimate": 2100000,
                              "models": MODELS}}
s["_next"] = {"approve": "working", "not_this": "proposal"}
s["map"] = map_of(site_plan("proposal"), "needs_you", attention="u-identity", backstage=BACKSTAGE[:4])
F["proposal"] = s

# style: after the plan is approved, pick a look (three previews, one suggested)
s = base("fx-style")
s.update(status="needs_you", usage=usage(260000, None), plan=site_plan("proposal"),
         chat=chat(("you", REQUEST), ("team", "Thanks. Here's what I'd make."), PLAN_RECORD, ("you", "Approved"),
                   ("team", "Thanks. One quick choice before we build: the look.")),
         backstage=back(BACKSTAGE[:4] + [("Client lead", "Planner", "Studied three strong physio and clinic sites; "
                                                                    "three looks drawn from them.")], False))
s["decision"] = {"id": "d-3", "kind": "style", "happening": "Pick a look for your website.",
                 "why": "Three directions drawn from real sites of this kind; we suggest Warm and friendly.",
                 "options": LOOKS, "fields": [], "allow_text": True, "proposal": None}
s["_next"] = {"*": "working"}
s["map"] = map_of(site_plan("proposal"), "needs_you", attention="u-identity", backstage=BACKSTAGE[:4])
F["style"] = s

# design (feedback 3): the four quick design cards after the look, each option with a sample drawn from the chosen
# look (built by j2_design, the same code the backend uses)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import j2_design  # noqa: E402
_guide = j2_design.mock_directions()[1]["guide"]
for _i, _q in enumerate(j2_design.design_questions(_guide)):
    s = base(f"fx-design-{_q['topic']}")
    s.update(status="needs_you", usage=usage(270000, None), plan=site_plan("proposal"),
             chat=chat(("you", REQUEST), ("team", "Thanks. Here's what I'd make."), PLAN_RECORD, ("you", "Approved"),
                       ("team", "Warm and friendly it is. A few quick choices on the details.")),
             backstage=back(BACKSTAGE[:4], False))
    s["decision"] = {"id": f"d-{4 + _i}", "kind": "design", "topic": _q["topic"], "step": {"n": _i + 1, "of": 4},
                     "happening": _q["happening"], "why": _q["why"],
                     "options": [{**{k: o[k] for k in ("id", "label", "gets", "suggested", "sample")}, "usage": 0}
                                 for o in _q["options"]], "fields": [], "allow_text": True, "proposal": None}
    s["_next"] = {"*": "working"}
    s["map"] = map_of(site_plan("proposal"), "needs_you", attention="u-identity", backstage=BACKSTAGE[:4])
    F[f"design_{_q['topic']}"] = s

# planning: before the proposal; the planner is at work (who's working: its token glows, the top bar names it)
s = base("fx-planning")
s.update(status="working", status_text="Planner is planning the parts", usage=usage(90000, None, None),
         chat=chat(("you", REQUEST), ("team", "Thanks. I'm planning the parts now.")),
         backstage=back([("Client lead", "Planner", "They want one page: services, hours and WhatsApp booking."),
                         ("Gatekeeper", "Planner", "The brief is complete: 8 things to check at the end. Work can start.")]),
         working_now={"who": "Planner", "task_id": None})
s["map"] = map_of(None, "working", core_working=("u-adaptation",), backstage=BACKSTAGE[:1])
s["map"]["units"][1]["doing"] = "Planning the parts"
s["_next"] = {"stop": "stopped"}
F["planning"] = s

# working
s = base("fx-working")
s.update(status="working", status_text="Building your opening hours", usage=usage(1200000),
         plan=site_plan("building"), working_now={"who": "Builder · Opening hours", "task_id": "W-4"},
         deliverables=site("working", 3),
         chat=chat(("you", REQUEST), ("team", "Thanks. Here's what I'd make."), PLAN_RECORD, ("you", "Approved"),
                   ("team", "Thanks. One quick choice before we build: the look."), LOOK_RECORD,
                   ("you", "Warm and friendly"),
                   ("team", "Building now. The brief, the look and the services list are done."),
                   ("team", "I'll check in if I need anything from you.")),
         backstage=back(BACKSTAGE))
s["_sim"] = {"lines": SIM_LINES, "spend": 30000, "bump_every": 2, "fill": 0.05}
s["_next"] = {"stop": "stopped"}
s["map"] = map_of(site_plan("building"), "working", core_working=("u-validator",), backstage=BACKSTAGE)
F["working"] = s

# paused: the person pressed Pause; the team holds between steps
s = copy.deepcopy(F["working"])
s["run"]["id"] = "fx-paused"
s.update(status="paused", status_text="Paused", control={"paused": True, "pausing": False, "stopping": False})
s["chat"].append({"id": len(s["chat"]) + 1, "t": "10:24:10", "from": "team", "kind": "record", "title": "Paused",
                  "summary": "The team holds between steps until you resume.", "answer": "", "detail": []})
s["backstage"][-1]["active"] = False
s["map"] = map_of(site_plan("building"), "paused", backstage=BACKSTAGE)
s.pop("_sim", None)
s["_next"] = {"stop": "stopped"}
F["paused"] = s

# facts: things only the user knows
s = copy.deepcopy(F["working"])
s["run"]["id"] = "fx-facts"
s.update(status="needs_you", status_text="", usage=usage(1250000))
s["chat"] = s["chat"][:7]       # through the look record and "Warm and friendly"
s["backstage"][-1]["active"] = False
s["backstage"].append({"id": 13, "t": "10:20:11", "from": "Builder · Opening hours", "to": "Client lead",
                       "text": "I need the real hours and the WhatsApp number.", "active": False})
s["decision"] = {"id": "d-3", "kind": "facts", "happening": "Two things only you know.",
                 "why": "The hours and booking parts need them. Without them we use placeholders you'd edit later.",
                 "options": [
                     {"id": "answer", "label": "Use these", "gets": "Real hours and a working booking button.", "usage": 0, "suggested": True},
                     {"id": "skip", "label": "Skip for now", "gets": "Placeholders you can change later.", "usage": 0, "suggested": False}],
                 "fields": [
                     {"id": "hours", "label": "Opening hours", "placeholder": "Mon to Fri 8 to 8, Sat 9 to 2, Sun closed"},
                     {"id": "whatsapp", "label": "WhatsApp number", "placeholder": "+91 98…"}],
                 "allow_text": False, "proposal": None}
s.pop("_sim", None)
s["_next"] = {"*": "working"}
s["map"] = map_of(site_plan("building"), "needs_you", attention="W-4", backstage=BACKSTAGE + [("Builder · Opening hours", "Client lead", "I need the real hours and the WhatsApp number.")])
F["facts"] = s

# usage running out
s = copy.deepcopy(F["working"])
s["run"]["id"] = "fx-usage"
s.update(status="needs_you", status_text="", usage=usage(2090000))
s["plan"] = site_plan("building")
for g in s["plan"]["groups"]:
    for t in g["tasks"]:
        if t["id"] == "W-4":
            t.update(status="done", usage=200000)
        if t["id"] == "W-5":
            t.update(status="working", usage=290000)
s["working_now"] = {"who": "Builder · Booking on WhatsApp", "task_id": "W-5"}
s["backstage"][-1]["active"] = False
s["backstage"].append({"id": 13, "t": "10:31:40", "from": "Budget lead", "to": "Client lead",
                       "text": "We're near the limit with two parts left. Asking them.", "active": False})
s["decision"] = {"id": "d-5", "kind": "usage", "happening": "Usage is running low with 2 parts left.",
                 "why": "You've used 2.1M of 2.4M. The FAQ and the final check need about 400k.",
                 "options": [
                     {"id": "add", "label": "Add 400k and finish", "gets": "Everything in the plan, checked.", "usage": 400000, "suggested": True},
                     {"id": "finish", "label": "Finish without the FAQ", "gets": "The site, checked, with no questions section.", "usage": 190000, "suggested": False},
                     {"id": "stop", "label": "Stop here", "gets": "Keep what's built so far.", "usage": 0, "suggested": False}],
                 "fields": [], "allow_text": True, "proposal": None}
s.pop("_sim", None)
s["_next"] = {"add": "working", "finish": "done_open", "stop": "stopped"}
s["map"] = map_of(s["plan"], "needs_you", attention="u-priority", backstage=BACKSTAGE + [("Budget lead", "Client lead", "We're near the limit with two parts left. Asking them.")])
F["usage"] = s

# problem the team can't solve alone
s = copy.deepcopy(F["working"])
s["run"]["id"] = "fx-problem"
s.update(status="needs_you", status_text="", usage=usage(2100000))
s["backstage"][-1]["active"] = False
s["decision"] = {"id": "d-4", "kind": "problem",
                 "happening": "The website is ready, except the hours section doesn't show Sunday as closed.",
                 "why": "Fixing it uses about 80k more (you have 300k left).",
                 "options": [
                     {"id": "fix", "label": "Fix it", "gets": "Sunday shows as closed.", "usage": 80000, "suggested": True},
                     {"id": "leave", "label": "Leave it", "gets": "Finish now, with this one gap.", "usage": 0, "suggested": False}],
                 "fields": [], "allow_text": True, "proposal": None}
s.pop("_sim", None)
s["_next"] = {"fix": "working", "leave": "done_open"}
s["plan"] = site_plan("done_open")
s["map"] = map_of(s["plan"], "needs_you", attention="W-4", backstage=BACKSTAGE + [("Quality check", "Client lead", "Six of seven parts pass. The hours section doesn't show Sunday as closed.")])
F["problem"] = s

# done
s = base("fx-done")
s.update(status="done", usage=usage(1810000), plan=site_plan("done"), deliverables=site("done", 7),
         chat=chat(("you", REQUEST), ("team", "Thanks. Here's what I'd make."), ("you", "Approve"),
                   ("team", "Building now. The brief, the look and the services list are done."),
                   ("team", "All seven parts passed their checks.")),
         backstage=back(BACKSTAGE + [("Quality check", "Client lead", "Every part passes on phone and computer.")], False))
s["ended"] = {"kind": "done", "text": "Your website is ready.", "open_items": []}
s["_next"] = {"new": "start"}
s["map"] = map_of(site_plan("done"), "done", backstage=BACKSTAGE)
F["done"] = s

# done with one thing open
s = copy.deepcopy(F["done"])
s["run"]["id"] = "fx-done-open"
s.update(status="done_open", plan=site_plan("done_open"), usage=usage(2150000))
s["chat"][-1]["text"] = "Six of seven parts passed. One small thing is still open."
s["ended"] = {"kind": "done_open", "text": "Your website is ready, with one thing open.",
              "open_items": ["The hours section doesn't show Sunday as closed."]}
s["map"] = map_of(site_plan("done_open"), "done_open", backstage=BACKSTAGE)
F["done_open"] = s

# stopped
s = base("fx-stopped")
s.update(status="stopped", usage=usage(1340000), plan=site_plan("stopped"), deliverables=site("draft", 5),
         chat=chat(("you", REQUEST), ("team", "Thanks. Here's what I'd make."), ("you", "Approve"),
                   ("team", "Building now. The brief, the look and the services list are done."),
                   ("you", "Stop here please, I'll come back to it.")),
         backstage=back(BACKSTAGE, False))
s["ended"] = {"kind": "stopped", "text": "Stopped because you asked. What's built so far is saved.", "open_items": []}
s["_next"] = {"new": "start"}
s["map"] = map_of(site_plan("stopped"), "stopped", backstage=BACKSTAGE)
F["stopped"] = s

# crashed
s = base("fx-crashed")
s.update(status="crashed", usage=usage(980000), plan=site_plan("building"), deliverables=site("draft", 2),
         chat=chat(("you", REQUEST), ("team", "Thanks. Here's what I'd make."), ("you", "Approve"),
                   ("team", "Building now. The brief, the look and the services list are done.")),
         backstage=back(BACKSTAGE, False))
s["ended"] = {"kind": "crashed", "text": "It stopped while building the opening hours.", "open_items": []}
s["_next"] = {"new": "start"}
s["map"] = map_of(site_plan("building"), "crashed", backstage=BACKSTAGE)
F["crashed"] = s

# a document run: PRD done, HLD draft, LLD being written
DOC_BACK = [
    ("Client lead", "Planner", "They want a PRD, an HLD and an LLD for a clinic booking app."),
    ("Planner", "Budget lead", "Three documents, 6 parts, about 1.6M."),
    ("Budget lead", "Planner", "Fits."),
    ("Builder · PRD", "Gatekeeper", "PRD is written: goals, features, what's out of scope."),
    ("Gatekeeper", "Scheduler", "PRD passes."),
    ("Builder · HLD", "Gatekeeper", "The main parts and how a booking flows."),
    ("Gatekeeper", "Builder · HLD", "Good. Add the open choices at the end."),
    ("Builder · LLD", "Gatekeeper", "Writing the tables and the API now."),
]
s = base("fx-docs", "Clinic Booking App")
s.update(status="working", status_text="Writing the low-level design", usage=usage(820000, 1900000, 1600000),
         working_now={"who": "Builder · LLD", "task_id": "D-5"},
         chat=chat(("you", "A PRD, HLD and LLD for a simple appointment booking app for clinics."),
                   ("team", "Thanks. Here's what I'd make."), ("you", "Approve"),
                   ("team", "The PRD is done. Working on the designs now.")),
         backstage=back(DOC_BACK))
s["plan"] = {"groups": [
    {"name": "Planning", "tasks": [task("D-1", "Brief", "Who the app is for and what it must do.", "done", 120000, 150000)]},
    {"name": "Writing", "tasks": [
        task("D-2", "PRD", "Goals, features and what's out of scope.", "done", 260000, 300000, ["Brief"]),
        task("D-3", "HLD", "The main parts and how they fit.", "done", 240000, 300000, ["PRD"]),
        task("D-4", "Data and API", "Tables and endpoints for the LLD.", "done", 150000, 250000, ["HLD"]),
        task("D-5", "LLD", "The detailed design, part by part.", "working", 50000, 350000, ["Data and API"])]},
    {"name": "Checking", "tasks": [task("D-6", "Consistency check", "The three documents agree with each other.", "waiting", 0, 200000, ["LLD"])]},
]}
s["deliverables"] = [
    {"kind": "prd", "label": "PRD", "state": "done", "version": 2, "url": "/ui/dev/samples/prd.md", "download": "/ui/dev/samples/prd.md"},
    {"kind": "hld", "label": "HLD", "state": "draft", "version": 1, "url": "/ui/dev/samples/hld.md", "download": "/ui/dev/samples/hld.md"},
    {"kind": "lld", "label": "LLD", "state": "working", "version": 1, "url": "/ui/dev/samples/lld.md", "download": None},
]
s["_sim"] = {"lines": [
    {"from": "Builder · LLD", "to": "Gatekeeper", "text": "Tables done. Writing the reminder job.", "status_text": "Writing the low-level design"},
    {"from": "Gatekeeper", "to": "Builder · LLD", "text": "Add the error cases for a lost hold.", "status_text": "Writing the low-level design"},
    {"from": "Builder · LLD", "to": "Gatekeeper", "text": "Error cases added.", "status_text": "Checking the low-level design"},
], "spend": 12000, "bump_every": 4, "fill": 0.03}
DOC_DEPTS = (("d-prd", "PRD", "prd"), ("d-hld", "HLD", "hld"), ("d-lld", "LLD", "lld"))
DOC_DEPT_OF = {"D-1": "d-prd", "D-2": "d-prd", "D-3": "d-hld", "D-4": "d-lld", "D-5": "d-lld", "D-6": "d-lld"}
DOC_DEPS = {"D-1": [], "D-2": ["D-1"], "D-3": ["D-2"], "D-4": ["D-3"], "D-5": ["D-4"], "D-6": ["D-5"]}
s["map"] = map_of(s["plan"], "working", depts=DOC_DEPTS, dept_of=DOC_DEPT_OF, deps=DOC_DEPS, core_working=("u-validator",),
                  backstage=DOC_BACK)
F["docs"] = s

# graph8: a real-ish 8-part website plan (the shape of a live run: everything waits on the plan and the look, the
# navigation waits on every section), with long part names, to check roads, labels and the auto-fit
G8 = [("W-1", "Product section map", "done", 60000, 60000, []),
      ("W-2", "Style guide", "done", 80000, 80000, ["W-1"]),
      ("W-3", "Header section", "done", 120000, 120000, ["W-1", "W-2"]),
      ("W-4", "Contact section", "done", 100000, 100000, ["W-1", "W-2"]),
      ("W-5", "Menu & flowers section with prices and the WhatsApp order call to action", "working", 70000, 150000, ["W-1", "W-2"]),
      ("W-6", "Hours section", "working", 30000, 90000, ["W-1", "W-2"]),
      ("W-7", "WhatsApp order button", "waiting", 0, 80000, ["W-1", "W-2", "W-5"]),
      ("W-8", "Page shell & navigation", "waiting", 0, 140000, ["W-1", "W-2", "W-3", "W-4", "W-5", "W-7", "W-6"])]
G8_PLAN = {"groups": [{"name": "Building", "tasks": [task(i, n, "", st, u, sh, [x for (j, x, *_r) in G8 if j in d])
                                                    for i, n, st, u, sh, d in G8]}]}
s = base("fx-graph8", "Bloom Cafe")
s.update(status="working", status_text="Building: Menu & flowers section and Hours section", usage=usage(1500000, 2600000, 2300000),
         plan=G8_PLAN, working_now={"who": "Builder · Hours section", "task_id": "W-6"}, deliverables=site("working", 4),
         chat=chat(("you", "A one-page website for Bloom Cafe: menu, flowers, hours, contact and WhatsApp orders."),
                   ("team", "Building now.")),
         backstage=back(BACKSTAGE[:4]))
s["map"] = map_of(G8_PLAN, "working", deps={i: d for i, _n, _s, _u, _sh, d in G8}, backstage=BACKSTAGE[:4])
for b_ in s["map"]["buildings"]:
    if b_["id"] == "W-2":
        b_["output"] = {"kind": "style"}
    elif b_["id"] == "W-1":
        b_["output"] = {"kind": "notes"}
s["_next"] = {"stop": "stopped"}
F["graph8"] = s

# graph14 / graph20: the shape of the live 14-part Neel Studio run (one plan, three planning parts, eight sections that
# all wait on the copy and the look, one shell that waits on everything), and a 20-part version, to check that the map
# uses the screen's width (a wide column wraps into sub-columns) instead of a tall narrow column
G14 = [("W-1", "Plan scope & flow", "done", 90000, 90000, []),
       ("W-2", "Write site copy", "done", 110000, 110000, ["W-1"]),
       ("W-3", "Design style guide", "done", 80000, 80000, ["W-1"]),
       ("W-4", "Engineering WhatsApp integration", "done", 70000, 70000, ["W-1"]),
       ("W-5", "Home hero", "done", 90000, 90000, ["W-1", "W-2", "W-3"]),
       ("W-6", "Services section", "working", 40000, 100000, ["W-1", "W-2", "W-3"]),
       ("W-7", "Portfolio section", "working", 30000, 120000, ["W-1", "W-2", "W-3"]),
       ("W-8", "Process section", "waiting", 0, 80000, ["W-2", "W-3"]),
       ("W-9", "Team section", "waiting", 0, 80000, ["W-2", "W-3"]),
       ("W-11", "FAQ section", "waiting", 0, 80000, ["W-2", "W-3"]),
       ("W-12", "Contact info section", "waiting", 0, 70000, ["W-2", "W-3"]),
       ("W-13", "Contact form", "waiting", 0, 90000, ["W-1", "W-4", "W-3"]),
       ("W-10", "Testimonials section", "waiting", 0, 70000, ["W-2", "W-3"]),
       ("W-14", "Site shell & integration", "waiting", 0, 140000,
        ["W-5", "W-6", "W-7", "W-8", "W-9", "W-11", "W-12", "W-13", "W-10", "W-3", "W-4"])]
G20 = G14[:-1] + [("W-15", "Pricing table", "waiting", 0, 80000, ["W-2", "W-3"]),
                  ("W-16", "Gallery of finished homes", "waiting", 0, 90000, ["W-2", "W-3"]),
                  ("W-18", "Newsletter sign-up", "waiting", 0, 60000, ["W-2", "W-3", "W-4"]),
                  ("W-19", "Location map", "waiting", 0, 50000, ["W-2", "W-3"]),
                  ("W-20", "Research: strong studio sites", "done", 60000, 60000, ["W-1"])] + G14[-1:] + [
       ("W-21", "Phone and computer check", "waiting", 0, 60000, ["W-14"])]


def graph_fixture(rows, run_id, purpose=True):
    plan = {"groups": [{"name": "Building", "tasks": [
        task(i, n, f"Makes the {n.lower()} for the Neel Studio page, following the plan, the copy and the look." if purpose else "",
             st, u, sh, [x for (j, x, *_r) in rows if j in d]) for i, n, st, u, sh, d in rows]}]}
    s = base(run_id, "Neel Studio")
    s.update(status="working", status_text="Building: Services section and Portfolio section", usage=usage(1500000, 2600000, 2300000),
             plan=plan, working_now={"who": "Builder · Services section", "task_id": "W-6"}, deliverables=site("working", 4),
             chat=chat(("you", "A one-page website for Neel Studio, an interior design studio in Bengaluru."), ("team", "Building now.")),
             backstage=back(BACKSTAGE[:4]))
    s["map"] = map_of(plan, "working", deps={i: d for i, _n, _s, _u, _sh, d in rows}, backstage=BACKSTAGE[:4])
    for b_ in s["map"]["buildings"]:
        b_["output"] = {"W-1": {"kind": "notes"}, "W-2": {"kind": "notes"}, "W-3": {"kind": "style"}, "W-4": {"kind": "notes"},
                        "W-5": {"kind": "section"}, "W-20": {"kind": "research"}}.get(b_["id"]) if b_["state"] == "done" else None
    s["_next"] = {"stop": "stopped"}
    return s


F["graph14"] = graph_fixture(G14, "fx-graph14")
F["graph20"] = graph_fixture(G20, "fx-graph20")

RUNS = [
    {"id": "fx-done", "title": "Still Water Physio", "status": "done", "spent": 1810000, "when": "Today, 10:42", "fixture": "done"},
    {"id": "fx-docs", "title": "Clinic Booking App", "status": "working", "spent": 820000, "when": "Today, 09:10", "fixture": "docs"},
    {"id": "fx-stopped", "title": "Corner Bakery", "status": "stopped", "spent": 640000, "when": "Yesterday", "fixture": "stopped"},
]

for _f in F.values():
    _f["_outputs"] = OUTPUTS
os.makedirs(OUT, exist_ok=True)
for name, data in F.items():
    with open(os.path.join(OUT, f"{name}.json"), "w") as f:
        json.dump(data, f, indent=2)
with open(os.path.join(OUT, "_runs.json"), "w") as f:
    json.dump(RUNS, f, indent=2)
print("wrote", len(F) + 1, "files to", OUT)
