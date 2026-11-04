"""Offline check of the v2 API (/api/v2/*, j2-revamp/api-contract.md) in mock mode: python v2_test.py

Walks a mock run through the server the way the new page does: the start state, a facts question answered from a form,
the proposal (make it smaller, a stale answer refused, approve), the run to done, deltas, the runs list, a saved run,
and a PRD run whose deliverable url returns raw markdown. No J2_TOKEN_BUDGET here: the proposal pause is the point.
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

os.environ["STUDIO_MOCK"] = "1"
os.environ["J2_MEMORY"] = "0"
os.environ["J2_REALIZATION"] = "0"
os.environ.pop("J2_TOKEN_BUDGET", None)
os.environ.pop("J2_BUDGET", None)
TMP = tempfile.mkdtemp(prefix="j2-v2-test-")
os.environ["J2_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["J2_MEMORY_FILE"] = os.path.join(TMP, "lessons.jsonl")
os.environ["J2_PLAYBOOK_FILE"] = os.path.join(TMP, "playbooks.jsonl")
import j2  # noqa: E402
import j2_server  # noqa: E402

for k in ("J2_SEND_MODE", *j2.j2_send.SMTP_VARS, "J2_SEND_CAP"):
    os.environ.pop(k, None)
j2.j2_check.find_chrome = lambda: None          # no browser: the render check reads the page statically
j2.j2_check.check = lambda html: {"available": True, **j2.j2_check.static_checks(html), "phone": {"width": 360, "overflow_px": 0},
                                  "desktop": {"width": 1280, "overflow_px": 0}, "js_errors": [], "design": {},
                                  "form_results": [{"index": i + 1, "has_submit": True, "submitted": True, "invalid": [],
                                                    "errors_during": [], "ok": True}
                                                   for i in range(j2.j2_check.static_checks(html)["forms"])]}
j2.j2_check.tap_targets = lambda html, selector, min_px=44: {"available": True, "roots": 1, "checked": 0, "small_count": 0,
                                                            "small": []}

BREW_LAB = ("A one-page website for Brew Lab, a small specialty coffee shop in Indiranagar, Bengaluru. Visitors should "
            "see the menu with prices, the opening hours, and where to find us, and be able to pre-order a coffee for "
            "pickup. It should feel warm and modern and work well on a phone. Include a section about our beans and the "
            "farms they come from, and a simple loyalty-card explainer (buy 9, get the 10th free).")
PRD_BRIEF = ("Write a PRD for Brew Lab's pre-order app. Users: coffee lovers and office staff. Problem: people can't see "
             "the menu or order ahead. Must-have features: see the menu with prices, pre-order a coffee, find the shop, "
             "read the opening hours. Constraints: one page only. Success: 30 pre-orders per week.")
STATUSES = ("idle", "working", "needs_you", "paused", "done", "done_open", "stopped", "crashed")
NAMES = {"Client lead", "Planner", "Plan reviewer", "Budget lead", "Gatekeeper", "Scheduler", "Quality check", "Checks"}
CODE = re.compile(r"\bW-\d+\b|\bF-\d+\b|\bJ2\.[a-h]\b|\b(?:Identity|Adaptation|Priority|Coordination|credits?|atoms?)\b")
# Everything a person reads in the chat and the backstage (api-contract.md): no codes, no function names, no internal
# words. The detail ("See details") is scanned whole: every string in it, however deep.
INTERNAL = re.compile(r"\bJ2\.[a-h]\b|\b[WFCPNHLQ]-\d+\b|\b[PNHL]\d{1,2}\b|\b(?:Identity|Adaptation|Priority|"
                      r"Coordination|Validator|Audit|Requester)\b|(?i:\b(?:credits?|atoms?|envelopes?|charters?|"
                      r"done[- ]when|workflows?|tokens?)\b)")


def scan_words(st, what):
    """Fails on any internal word in the chat and the backstage of a state."""
    texts = [("chat", m.get("text") or f"{m.get('title', '')} {m.get('summary', '')}") for m in st["chat"]]
    for b in st["backstage"]:
        texts += [("backstage", b["text"]), ("from", b["from"]), ("to", b["to"] or "")]
        texts += [("detail", t) for t in strings(b["detail"])]
    bad = [(k, t) for k, t in texts if INTERNAL.search(t)]
    ok(not bad, (f"{what}: no internal words in the chat or the backstage", bad[:6]))
    leaks = [(b["text"], t) for b in st["backstage"] for t in [b["text"], *strings(b["detail"])] if LEAK.search(t)]
    ok(not leaks, (f"{what}: no file names (*.md, *.json) or raw large numbers in the backstage or its details", leaks[:4]))


# A person never reads a run file's name or a raw token count (a run of 6 to 9 digits; a phone number has 10 or more).
LEAK = re.compile(r"\b[\w-]+\.(?:md|json|jsonl)\b|(?<![\d+])\d{6,9}(?!\d)")


def strings(x):
    """Every string in a detail payload, and every number as text (a raw 1607715 is a leak too)."""
    if isinstance(x, str):
        return [x]
    if isinstance(x, bool) or x is None:
        return []
    if isinstance(x, (int, float)):
        return [str(x)]
    if isinstance(x, list):
        return [s for v in x for s in strings(v)]
    if isinstance(x, dict):
        return [s for v in x.values() for s in strings(v)]
    return []
checks = []
DETAIL_KEYS = {"plan": {"summary", "stages", "total", "confidence", "not_ready"}, "checks": {"what", "summary", "items"},
               "budget": {"summary", "rows"}, "decision": {"asked", "chosen", "by"}, "generic": set()}

srv = j2_server.http.server.ThreadingHTTPServer(("127.0.0.1", 0), j2_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def ok(cond, what):
    assert cond, what
    checks.append(what)


def get(path, raw=False):
    with urllib.request.urlopen(BASE + path) as r:
        body = r.read()
        return (body, r.headers.get("Content-Type")) if raw else json.loads(body)


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def settle():
    """Poll like the page: until the run is no longer working."""
    for _ in range(3000):
        st = get("/api/v2/state")
        if st["status"] != "working":
            return st
        time.sleep(0.02)
    raise AssertionError("the run never settled")


def shape(st):
    ok(set(st) == {"run", "status", "status_text", "usage", "decision", "chat", "backstage", "working_now", "plan",
                   "deliverables", "ended", "settings", "control"}, "state has exactly the contract's keys")
    ok(set(st["control"]) == {"paused", "pausing", "stopping"} and all(isinstance(v, bool) for v in st["control"].values()),
       "control carries paused, pausing and stopping")
    ok(st["status"] in STATUSES and isinstance(st["usage"]["spent"], int), "status is in the enum; spent is a number")
    ok(set(st["usage"]) == {"budget", "spent", "margin_at", "estimate", "by_phase", "web_searches", "web_fetches"},
       "usage has the contract's keys")
    ok(isinstance(st["settings"].get("no_questions"), bool), "settings carry no_questions")
    for m in st["chat"]:
        if m.get("kind") == "record":        # an answered decision's compact record (api-contract.md)
            ok(set(m) == {"id", "t", "from", "kind", "title", "summary", "answer", "detail"} and m["from"] == "team"
               and m["title"] and not CODE.search(m["title"] + m["summary"]), f"record line keys and plain words: {m['title']}")
            continue
        ok(set(m) == {"id", "t", "from", "text"} and m["from"] in ("you", "team"), "chat lines: you or the team only")
    for b in st["backstage"]:
        ok(set(b) == {"id", "t", "from", "to", "text", "active", "detail"}, "backstage line keys")
        d = b["detail"]
        ok({"kind", "decided", "why"} <= set(d) and "full" not in d
           and d["kind"] in ("plan", "checks", "budget", "decision", "generic"),
           "backstage detail: a kind with decided and why, never the agents' original text")
        ok(set(d) <= {"kind", "decided", "why"} | DETAIL_KEYS[d["kind"]], f"backstage detail keys for {d['kind']}: {sorted(d)}")
        ok(b["from"] in NAMES or b["from"].startswith("Builder · "), f"backstage speaker is a vocabulary name: {b['from']}")
        ok(not CODE.search(b["text"]), f"backstage line has no codes: {b['text']}")
    for g in st["plan"]["groups"]:
        for t in g["tasks"]:
            ok(set(t) == {"id", "name", "summary", "status", "waits_for", "usage", "share"}
               and t["status"] in ("waiting", "working", "done", "needs_fix", "skipped"), "plan task keys and status")
            ok(not CODE.search(t["name"] + " " + t["summary"]), f"plan task in plain words: {t['name']}")
    for d in st["deliverables"]:
        ok(set(d) == {"kind", "label", "state", "version", "url", "download"} and d["state"] in ("todo", "working", "draft", "done"),
           "deliverable keys and state")
    dec = st["decision"]
    if dec:
        ok(set(dec) == {"id", "kind", "happening", "why", "options", "fields", "allow_text", "proposal"}
           | ({"topic", "step"} if dec["kind"] == "design" else set()), "decision keys (a design card adds topic and step)")
        ok(dec["kind"] in ("proposal", "facts", "usage", "problem", "confirm", "style", "design") and 2 <= len(dec["options"]) <= 4
           and sum(o["suggested"] for o in dec["options"]) == 1, "decision: 2-4 options, exactly one suggested")
        ok(all(set(o) == ({"id", "label", "gets", "usage", "suggested"} | ({"preview_url", "inspired_by"} if dec["kind"] == "style" else {"sample"} if dec["kind"] == "design" else set()))
               for o in dec["options"]), "decision option keys (a style option adds preview_url and inspired_by)")


# 1. start: idle, empty chat, the new page at /, the old one at /legacy
j2_server.RUN.reset()
st = get("/api/v2/state")
shape(st)
ok(st["status"] == "idle" and st["chat"] == [] and st["usage"]["spent"] == 0 and st["usage"]["budget"] is None,
   "a fresh run is idle with spent 0 and no budget yet")
page, ctype = get("/", raw=True)
ok(ctype.startswith("text/html") and (b"/ui/" in page or b"new page" in page), "GET / serves the new page (ui/index.html)")
ok(b'id="lanes"' in get("/legacy", raw=True)[0], "GET /legacy serves the old page")
if os.path.isdir(j2_server.UI_DIR):
    some = next((os.path.relpath(os.path.join(r, f), j2_server.UI_DIR) for r, _, fs in os.walk(j2_server.UI_DIR)
                 for f in fs if f.endswith(".js")), None)
    if some:
        body, ct = get("/ui/" + some.replace(os.sep, "/"), raw=True)
        ok(ct.startswith("text/javascript") and body, "GET /ui/* serves the page's files")
try:
    get("/ui/../j2.py", raw=True)
    ok(False, "no path tricks under /ui/")
except urllib.error.HTTPError as e:
    ok(e.code == 404, "no path tricks under /ui/")

# 2. a vague brief: the facts question comes back as a decision with fields, answered from the form (option_id null)
code, r = post("/api/v2/say", {"text": "a website for my cafe"})
ok(code == 200 and r == {"ok": True}, "say starts the run")
st = settle()
shape(st)
dec = st["decision"]
ok(st["status"] == "needs_you" and dec["kind"] == "facts" and dec["fields"], "a facts question carries fields")
ok(os.path.exists(os.path.join(j2_server.RUN.dir, "summary.json")) and
   j2._read(j2_server.RUN.dir, "summary.json")["status"] == "paused", "summary.json is written on a pause")
fields = {f["id"]: v for f, v in zip(dec["fields"], ["Little Fig, in Koramangala, Bengaluru",
                                                      "Our menu with prices, opening hours and where to find us",
                                                      "Cozy and simple, and it must work on phones"])}
code, r = post("/api/v2/decide", {"decision_id": dec["id"], "option_id": None, "text": "", "fields": fields})
ok(code == 200, "a facts form answers with option_id null and fields")
st = settle()
shape(st)
dec = st["decision"]
ok(dec and dec["kind"] == "proposal" and [o["id"] for o in dec["options"]] == ["approve", "smaller", "not_this"],
   "after intake: the proposal, with approve / smaller / not this")
ok(dec["proposal"]["estimate"] > 0 and dec["proposal"]["parts"] and st["usage"]["estimate"] == dec["proposal"]["estimate"]
   and st["usage"]["budget"] is None, "the proposal carries parts and an estimate; the budget is still unset")
ok(not CODE.search(dec["happening"] + dec["why"]), "the proposal reads in plain words")
ok(st["plan"]["groups"] and st["plan"]["groups"][0]["name"] == "Planned", "before registration the plan is the proposal's parts")

# 3. make it smaller: a new proposal; the old decision id is refused
old = dec
code, r = post("/api/v2/decide", {"decision_id": old["id"], "option_id": "smaller", "text": "", "fields": {}})
ok(code == 200, "make it smaller is accepted")
st = settle()
dec = st["decision"]
ok(dec and dec["kind"] == "proposal" and dec["id"] != old["id"], "a new proposal follows")
ok(dec["proposal"]["estimate"] <= old["proposal"]["estimate"] and len(dec["proposal"]["parts"]) <= len(old["proposal"]["parts"]),
   "the smaller plan is no bigger")
code, r = post("/api/v2/decide", {"decision_id": old["id"], "option_id": "approve", "text": "", "fields": {}})
ok(code == 409 and r.get("error"), "a stale decision answer gets 409 with an error")

# 4. approve: budget = estimate x (1 + margin), building starts, the run ends done
est = dec["proposal"]["estimate"]
# the model choice on the plan card (api-contract.md, proposal.models): four tiers, one suggested, plain labels
models = dec["proposal"].get("models") or []
ok([m["id"] for m in models] == ["fable", "opus", "sonnet", "haiku"] and sum(m["suggested"] for m in models) == 1
   and all(set(m) == {"id", "label", "suggested", "multiplier"} and " · " in m["label"] for m in models),
   "the proposal carries the model choice: 4 tiers, one suggested, label and multiplier each")
ok(next(m["id"] for m in models if m["suggested"]) == "sonnet", "Sonnet is the suggested model by default")
code, r = post("/api/v2/decide", {"decision_id": dec["id"], "option_id": "approve", "text": "", "fields": {}, "model": "gpt"})
ok(code == 409 and "model" in r.get("error", ""), "an unknown model is refused with a plain reason")
code, r = post("/api/v2/decide", {"decision_id": dec["id"], "option_id": "approve", "text": "", "fields": {}, "model": "haiku"})
ok(code == 200, "approve is accepted")
est = int(est * next(m["multiplier"] for m in models if m["id"] == "haiku"))   # the estimate is scaled for the chosen tier
# step 11: a website run picks a look right after the proposal: 3 previews (served), one suggested, inspired_by links
st = settle()
shape(st)
sd = st["decision"]
ok(sd and sd["kind"] == "style" and len(sd["options"]) == 3 and sum(o["suggested"] for o in sd["options"]) == 1,
   "after approve: the style decision with 3 options, one suggested")
ok(all(o["preview_url"].startswith("/design/preview-") and o["inspired_by"].get("label") and o["inspired_by"].get("url")
       for o in sd["options"]), "every look carries a preview url and an inspired-by source")
body, ctype = get(sd["options"][0]["preview_url"], raw=True)
ok(ctype.startswith("text/html") and b"j2-btn" in body and b"<h1>" in body, "the preview page is served from the run folder")
chat_all = get("/api/v2/state?since=0")["chat"]
rec = [m for m in chat_all if m.get("kind") == "record"]
ok(any(m["title"] == "Plan approved" and m["answer"] == "Approved" and m["detail"] for m in rec),
   "the approved plan stays in the chat as a record with its parts")
i = next(i for i, m in enumerate(chat_all) if m.get("kind") == "record" and m["title"] == "Plan approved")
ok(chat_all[i + 1]["from"] == "you" and chat_all[i + 1]["text"] == "Approved", "the user's bubble reads Approved, right after the record")
pick = next(o for o in sd["options"] if not o["suggested"])
code, r = post("/api/v2/decide", {"decision_id": sd["id"], "option_id": pick["id"], "text": "", "fields": {}})
ok(code == 200, "a look is picked")
for _ in range(10):          # anything else the mock asks (a conflict, a limit): take the suggested option
    st = settle()
    if not st["decision"]:
        break
    sug = next(o for o in st["decision"]["options"] if o["suggested"])
    post("/api/v2/decide", {"decision_id": st["decision"]["id"], "option_id": sug["id"], "text": "", "fields": {}})
shape(st)
ok(st["usage"]["budget"] == est * (100 + j2.MARGIN_PCT) // 100 and st["usage"]["margin_at"] < st["usage"]["budget"],
   "approve sets the budget to the estimate plus the margin")
ok(st["status"] in ("done", "done_open") and st["ended"] and st["ended"]["kind"] == st["status"], "the run ends done")
chat_all = get("/api/v2/state?since=0")["chat"]
ok(any(m.get("kind") == "record" and m["title"] == f"Look: {pick['label']}" and m["answer"] == pick["label"] for m in chat_all),
   "the picked look stays in the chat as a record")
ok(j2_server.RUN.style and j2_server.RUN.style.get("direction") == pick["label"]
   and j2_server.RUN.style["palette"]["primary"] in j2_server.RUN.sites[-1], "the chosen look is the run's style guide and is in the page")
ok(st["usage"]["spent"] > 0 and st["usage"]["by_phase"]["planning"] > 0 and st["usage"]["by_phase"]["building"] > 0,
   "usage is measured, by phase")
ok(st["chat"][0]["from"] == "you" and any(m["from"] == "team" for m in st["chat"])
   and not any(m.get("text", "").startswith("Validator") for m in st["chat"]), "the chat has only the user and the team")
ok(st["backstage"] and any(b["from"] == "Planner" for b in st["backstage"])
   and any(b["from"].startswith("Builder · ") for b in st["backstage"]), "the backstage names agents by the vocabulary")
scan_words(st, "a website run")
ok(any(b["detail"]["decided"] for b in st["backstage"]), "some backstage lines carry their structured decision in plain words")
ok(not any("full" in b["detail"] for b in st["backstage"]), "the agents' original text is never sent (it stays on /legacy)")
kinds = {b["detail"]["kind"] for b in st["backstage"]}
ok({"checks", "budget"} <= kinds, ("a website run's backstage carries structured check and budget details", kinds))
chk = next(b["detail"] for b in st["backstage"] if b["detail"]["kind"] == "checks")
ok(chk["items"] and all(set(i) == {"name", "pass", "reason"} and isinstance(i["pass"], bool) for i in chk["items"]),
   "a checks detail lists what was checked, each with a pass or fail and a plain reason")
bud = next(b["detail"] for b in st["backstage"] if b["detail"]["kind"] == "budget")
ok(bud["rows"] and all(re.fullmatch(r"[\d.]+[kM]?(?: .*)?|\d+%|[A-Z].*", r["value"]) for r in bud["rows"]),
   ("a budget detail's numbers are human amounts", bud["rows"]))
tasks = [t for g in st["plan"]["groups"] for t in g["tasks"]]
ok(tasks and all(t["share"] > 0 for t in tasks) and any(t["status"] == "done" for t in tasks), "plan tasks with shares")
site = next(d for d in st["deliverables"] if d["kind"] == "website")
ok(site["state"] == "done" and site["url"], "the website deliverable is done with a url")
html, ct = get(site["url"], raw=True)
ok(ct.startswith("text/html") and b"<html" in html.lower(), "the website url returns the page")
calls = [json.loads(x) for x in open(os.path.join(j2_server.RUN.dir, "calls.jsonl"), encoding="utf-8")]
ok(all(c.get("phase") in j2.PHASES and c.get("usage", {}).get("total") is not None and "tokens" in c for c in calls)
   and sum(c["usage"]["total"] for c in calls) == j2_server.RUN.spent, "every call is counted in calls.jsonl, with its phase")

# 5. deltas: nothing new after the last ids
last_c, last_b = st["chat"][-1]["id"], st["backstage"][-1]["id"]
d = get(f"/api/v2/state?since={last_c}&bsince={last_b}")
ok(d["chat"] == [] and d["backstage"] == [], "chat and backstage are deltas after since / bsince")
ok(not any(b["active"] for b in d["backstage"]), "nothing is active once the run ended")

# 6. runs list and the saved view
rid = os.path.basename(j2_server.RUN.dir)
rs = get("/api/v2/runs")
mine = next((x for x in rs if x["id"] == rid), None)
ok(mine and set(mine) == {"id", "title", "status", "spent", "when"} and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", mine["when"])
   and mine["spent"] > 0, "/api/v2/runs lists the run with an ISO time and its usage")
sv = get(f"/api/v2/state?run={rid}")
shape(sv)
ok(sv["run"]["saved"] and sv["status"] == st["status"] and sv["decision"] is None and sv["usage"]["spent"] == st["usage"]["spent"],
   ("a saved run reads back read-only, with its usage", sv["status"], st["status"], sv["usage"], st["usage"]))

# 7. new run, a PRD: proposal approved, the document's url is raw markdown
code, r = post("/api/v2/new", {})
ok(code == 200 and get("/api/v2/state")["status"] == "idle", "new starts a fresh run")
post("/api/v2/say", {"text": PRD_BRIEF})
for _ in range(10):
    st = settle()
    if not st["decision"]:
        break
    dec = st["decision"]
    if dec["kind"] == "facts":
        post("/api/v2/decide", {"decision_id": dec["id"], "option_id": None,
                                "text": "Users: coffee lovers. Problem: no pre-orders. Features: menu, pre-order.", "fields": {}})
    else:
        sug = next(o for o in dec["options"] if o["suggested"])
        post("/api/v2/decide", {"decision_id": dec["id"], "option_id": sug["id"], "text": "", "fields": {}})
scan_words(st, "a PRD run")
prd = next(d for d in st["deliverables"] if d["kind"] == "prd")
ok(st["status"] in ("done", "done_open") and prd["url"], "the PRD run ends with a deliverable url")
text, ct = get(prd["url"], raw=True)
ok(ct.startswith("text/markdown") and text.decode().lstrip().startswith("#"), "a document url returns raw markdown")

# 7b. run settings and picked outputs (step 8): POST /api/v2/settings, /api/output with stages
code, r = post("/api/v2/new", {})
code, r = post("/api/v2/settings", {"no_questions": True})
ok(code == 200 and r == {"ok": True, "settings": {"no_questions": True}} and j2_server.RUN.no_questions
   and get("/api/v2/state")["settings"]["no_questions"] is True, "/api/v2/settings turns no_questions on; the state shows it")
ok("model" in get("/api/v2/state")["settings"], "the state's settings carry the run's model choice (None before the plan)")
code, r = post("/api/v2/settings", {"no_questions": "yes"})
ok(code == 400 and "error" in r, "a setting that isn't true or false is refused")
code, r = post("/api/v2/settings", {"no_questions": False})
ok(code == 200 and not j2_server.RUN.no_questions, "and off again")

# 7c. "Decide for me" switched on DURING a run (the top bar / Conversation sheet switch): a small open question is
# answered at once the auto way, the plan approval stays open, off stops the auto answers from then on
post("/api/v2/new", {})
post("/api/v2/say", {"text": "a website for my cafe"})
st = settle()
ok(st["status"] == "needs_you" and st["decision"]["kind"] == "facts", "7c: a facts question is open before the switch")
code, r = post("/api/v2/settings", {"no_questions": True})
ok(code == 200 and r.get("answered") == st["decision"]["id"],
   ("switched on mid-run: the open facts question is answered at once and the reply names it", code, r))
st2 = settle()
ok(st2["status"] in ("done", "done_open") and not st2["decision"],
   ("feedback 3: with the switch on the run goes on by itself (plan approved, look and design picked) to an ending",
    st2["status"], (st2.get("decision") or {}).get("kind")))
bs = [x["text"] for x in get("/api/v2/state?bsince=0")["backstage"]]
ok(any(t.startswith("You asked the team to decide small things") for t in bs) and
   any(t.startswith("Decided without asking") for t in bs), ("team talk records the switch and the answer in plain words", bs[-4:]))
ok(any(m.get("kind") == "record" and m["title"] == "Plan approved" and m["answer"] == "Decided for you"
       for m in get("/api/v2/state")["chat"]), "the auto-approved plan is a record in the chat")
code, r = post("/api/v2/settings", {"no_questions": False})
bs = [x["text"] for x in get("/api/v2/state?bsince=0")["backstage"]]
ok(code == 200 and not j2_server.RUN.no_questions and any(t.startswith("You'll be asked") for t in bs),
   "off again, recorded in team talk")
# off: the team decides nothing by itself (the plan approval is asked)
post("/api/v2/new", {})
post("/api/v2/say", {"text": "a website for my cafe"})
st = settle()
post("/api/v2/decide", {"decision_id": st["decision"]["id"], "option_id": None, "text": "Hours 8-8, MG Road", "fields": {}})
st3 = settle()
ok(st3["status"] == "needs_you" and st3["decision"]["kind"] == "proposal",
   ("with the switch off the plan approval is asked", st3["status"], (st3.get("decision") or {}).get("kind")))
post("/api/v2/new", {})
code, r = post("/api/output", {"stages": ["website", "prd"]})
ok(code == 200 and r["stages"] == ["prd", "website"] and r["output"] == "prd", "/api/output takes a chain of stages, in order")
code, r = post("/api/output", {"type": "prd"})
ok(code == 200 and r["output"] == "prd", ("/api/output still takes one type (the legacy page)", code, r))
# a plan row's waits_for names the tasks it waits for (5c): code's live waits
run_ = j2_server.RUN
run_.goal = j2.mock_charter(BREW_LAB)
run_.output_picked = True
w1 = {"id": "W-1", "name": "Menu", "status": "running", "section": "W-1", "envelope": {"token_share": 1}, "atoms": []}
w2 = {"id": "W-2", "name": "Order form", "status": "held", "section": "W-2", "depends_on": ["W-1"], "envelope": {"token_share": 1},
      "atoms": []}
run_.workflows = [w1, w2]
tasks = {t["id"]: t for g in j2_server.RUN.v2_snapshot()["plan"]["groups"] for t in g["tasks"]}
ok(tasks["W-2"]["waits_for"] == ["Menu"] and tasks["W-1"]["waits_for"] == [], "plan rows: waits_for by task name")
w1["status"] = "done"
tasks = {t["id"]: t for g in j2_server.RUN.v2_snapshot()["plan"]["groups"] for t in g["tasks"]}
ok(tasks["W-2"]["waits_for"] == [], "nothing to wait for once it is done")
post("/api/v2/new", {})

# 8. the rules behind the page, as unit checks
# (a) Identity can never tell the user it's finished while code says it isn't; the status is code's
r = j2.J2Run()
r.goal = j2.mock_charter(BREW_LAB)
r.audits = [{"cycle": 1, "version": 1, "all_pass": False, "mechanical": {"available": False, "note": "x"}, "rubric": [],
             "conditions": [], "results": [{"id": "F-1", "item": 1, "criterion": r.goal["done_when"][0],
                                            "verdict": "NEEDS_REVISION", "pass": False}]}]
m = r.post("identity", "Your website is ready and I'm calling this done.", to_user=True)
ok(m["text"].startswith("@Requester Not finished yet.") and "ready" not in m["text"]
   and any(e["type"] == "done_claim" for e in r.events), "a done claim while not workable is replaced by code's status")
m = r.post("identity", "We're still working on the hours.", to_user=True)
ok("Not finished yet" not in m["text"], "a message that claims nothing is left alone")
r.paused = None
ok(r.run_status()[0] in ("running", "paused") and r.snapshot()["run_status"]["status"] == r.run_status()[0],
   "snapshot carries the one status")
# (b) workable: code finishes the stage whatever Identity replied
r = j2.J2Run()
r.goal = {"done_when": ["a"], "site_name": "X"}
r.sites = ["<html></html>"]
r.audits = [{"cycle": 1, "version": 1, "all_pass": True, "mechanical": {"available": True}, "rubric": [], "conditions": [],
             "results": [{"id": "F-1", "item": 1, "criterion": "a", "verdict": "PASS", "pass": True}]}]
j2.j2_check.problems = (lambda f: (lambda mech: []))(j2.j2_check.problems)
r.call = lambda fn, fmt, task, mock, **k: {"to_requester": "Still working on it.", "done": False, "next": "Adaptation"}
r._identity_audit({})
ok(r.outcome and r.outcome.startswith("Done") and r.turn is None
   and any(e["type"] == "done_by_code" for e in r.events) and "Still working" not in r.chat[-1]["text"],
   "a workable site is finished by code even when Identity didn't say done")
# (c) the margin: usage past budget - margin pauses with a usage decision, never dies
r = j2.J2Run()
r.goal, r.budget, r.budget_set, r.spent = j2.mock_charter(BREW_LAB), 1_000_000, True, 900_000
r.sites = ["<html></html>"]
r._handoff("coordination", kind="schedule")
ok(r._margin_pause() and r.turn == "identity" and r.handoff["kind"] == "limit" and r.handoff["margin"],
   "usage inside the margin hands the turn to Identity for the usage decision")
r.call = lambda fn, fmt, task, mock, **k: {"say": "The usage is nearly used up."}
r._identity_limit(r.handoff)
d = r.paused["decision"]
ok(d["kind"] == "usage" and not j2.J2Run.decision_problems(d) and r.legacy_decision() is d, "a usage decision in the one format")
ok(not r._margin_pause(), "asked once per budget level")
# (d) a builder out of share: Priority tops it up once, only when usage is free
r = j2.J2Run()
w = {"id": "W-1", "name": "Menu", "status": "running", "charged": True, "envelope": {"token_share": 1000, "leeway_pct": 25}, "cost": 1000}
r.workflows = [w]
r.usage["by_workflow"]["W-1"] = 1300
ok(r._share_cap(w) == 1250 and r._top_up(w) and j2.granted(w) == 1500 and not r._top_up(w), "one top-up of half a share")
r.budget = r.spent + 100
w2 = {**w, "id": "W-2", "envelope": {"token_share": 1000}, "topped_up": False}
r.workflows.append(w2)
ok(not r._top_up(w2), "no top-up without usage free")
# (e) the question format: a reply that breaks it is rewritten by code
bad = {"happening": "Identity says W-3 failed F-2 " * 8, "why": "x", "options": [{"id": "a", "label": "A", "gets": "", "suggested": True},
       {"id": "b", "label": "B", "gets": "", "suggested": True}], "fields": []}
ok(len(j2.J2Run.decision_problems(bad)) >= 3, "decision_problems names long lines, two suggested and internal words")
r = j2.J2Run()
r.goal = {"done_when": ["a"]}
d = r._decision("problem", bad["happening"], "Credits ran out.", bad["options"])
ok(not j2.J2Run.decision_problems(d), "code rewrites a decision that breaks the format")
# (f) every call is counted: the chat summary and the reviewer go through the one accounting path
r = j2.J2Run()
before = r.spent
r._summarize([{"id": i, "who": "adaptation", "text": "hello " * 20, "t": "", "step": 1} for i in range(1, 5)])
rows = [json.loads(x) for x in open(os.path.join(r.dir, "calls.jsonl"), encoding="utf-8")]
ok(rows[-1]["fn"] == "summary" and rows[-1]["extra"] and rows[-1]["phase"] == "other"
   and r.spent - before == rows[-1]["usage"]["total"] > 0, "the chat summary call is counted, phase other")
ok(j2.llm.cli_meta({"usage": {"input_tokens": 1, "cache_read_input_tokens": 9, "output_tokens": 5,
                              "output_tokens_details": {"thinking_tokens": 2}, "server_tool_use": {"web_search_requests": 1}},
                    "modelUsage": {"claude-haiku-4-5": {"outputTokens": 1}, "claude-sonnet-4-5": {"outputTokens": 5}},
                    "total_cost_usd": 0.01}, "sonnet")
   == {"model": "claude-sonnet-4-5", "duration_ms": None, "input_tokens": 10, "fresh_input_tokens": 1, "cache_read_tokens": 9,
       "cache_creation_tokens": 0, "output_tokens": 5, "thinking_tokens": 2, "cost_usd": 0.01, "web_searches": 1,
       "web_fetches": 0}, "the CLI's usage is parsed in full; the model is the one with the most output tokens")

# "See details" on the planner's plan line (feedback 2): the actual plan from the realization result, plain; no file
# names or raw numbers anywhere in a detail, whatever the agents wrote.
import j2_v2  # noqa: E402
real = {"plan_confidence": 0.95, "not_ready": [], "plan": {"stages": [{"id": "product"}, {"id": "build"}], "workflows": [
    {"name": "define_product_scope", "stage": "product", "goal": "Decide the page's sections, mapped to the done-when items.",
     "inputs_from": []},
    {"name": "build_menu_section", "stage": "build", "goal": "Build the menu with prices.", "inputs_from": ["define_product_scope"]}]}}
reg = [{"id": "W-1", "name": "define_product_scope", "envelope": {"token_share": 1207715}},
       {"id": "W-2", "name": "build_menu_section", "envelope": {"token_share": 400000}}]
line = {"id": 9, "t": "10:00:00", "who": "adaptation", "realization": True,
        "text": "Plan by realization and certainty: stages product, build; 2 workflows; the judge's plan confidence is 0.95. "
                "Details in realization.md."}
bl = j2_v2.backstage_lines([line], {}, 0, False, {}, {"real": real, "wfs": reg})[0]
d = bl["detail"]
ok(d["kind"] == "plan" and [s["name"] for s in d["stages"]] == ["Planning", "Building"]
   and d["stages"][1]["parts"][0]["name"] == "Menu section" and d["stages"][1]["parts"][0]["waits_for"] == ["Define product scope"]
   and not any(k in p for s in d["stages"] for p in s["parts"] for k in ("share", "share_pct")) and "total" not in d
   and d["summary"] == "2 parts in 2 stages."
   and "very sure" in d["confidence"] and "checklist" in d["stages"][0]["parts"][0]["purpose"],
   ("the plan line's detail is the real plan: parts by stage, purpose, waits for, the reviewer's confidence, no usage", d))
# feedback 4: one stage count (the line agrees with the grouping: product and engineering are both "Planning"), and a
# long purpose is shown whole, never cut with "…"
long_goal = ("Decide every section of the page and the order they run in, mapped one to one to the checklist items. "
             "Write the form fields and the exact wording rules that every later builder copies word for word, so "
             "nothing has to be guessed and no fact is changed on the way.")
real4 = {"plan_confidence": 0.9, "not_ready": [], "plan": {"stages": [{"id": "product"}, {"id": "engineering"}, {"id": "build"}],
         "workflows": [{"name": "plan_scope", "stage": "product", "goal": long_goal, "inputs_from": []},
                       {"name": "spec_whatsapp", "stage": "engineering", "goal": "Spec the form.", "inputs_from": ["plan_scope"]},
                       {"name": "build_hero", "stage": "build", "goal": "Build the hero.", "inputs_from": ["plan_scope"]}]}}
line4 = {"id": 10, "t": "10:00:00", "who": "adaptation", "realization": True,
         "text": "Plan by realization and certainty: stages product, engineering, build; 3 workflows; the judge's plan "
                 "confidence is 0.9. Details in realization.md."}
bl4 = j2_v2.backstage_lines([line4], {}, 0, False, {}, {"real": real4, "wfs": []})[0]
p0 = bl4["detail"]["stages"][0]["parts"][0]["purpose"]
ok(bl4["detail"]["summary"] == "3 parts in 2 stages." and "3 parts in 2 stages" in bl4["text"],
   ("one stage count: the line and the panel agree", bl4["text"], bl4["detail"]["summary"]))
ok("…" not in p0 and p0.endswith("on the way.") and "every later builder" in p0, ("a purpose is whole", p0))
ok(not LEAK.search(bl["text"]) and not any(LEAK.search(t) for t in strings(d)) and "realization" not in bl["text"].lower(),
   ("the plan line names no file and no raw number", bl["text"]))
for raw in ("Usage budget raised on the Requester's approval: 2591614 -> 3191614 tokens. Remaining: 888338.",
            "Usage budget set from the approved plan: 1126253 tokens (estimate 979351 plus the 15% margin).",
            "W-11 attempt 1 can't be used: the reply has no ```markdown block with your section. Wrote research.md."):
    b = j2_v2.backstage_lines([{"id": 1, "who": "system", "text": raw}], {"W-11": "Menu"}, 0, False)[0]
    ok(not LEAK.search(b["text"]) and not any(LEAK.search(t) for t in strings(b["detail"])), ("budget lines read human amounts", b))
b = j2_v2.backstage_lines([{"id": 1, "who": "system", "text": "Usage budget raised on the Requester's approval: 2591614 -> "
                            "3191614 tokens. Remaining: 888338."}], {}, 0, False)[0]["detail"]
ok(b["kind"] == "budget" and [r["value"] for r in b["rows"]] == ["2.6M", "3.2M", "888k"], ("a raise reads before, now, left", b))
b = j2_v2.backstage_lines([{"id": 1, "who": "system", "auto_decision": "d-3", "text": "Decided without asking (no questions for "
                            "this run): Pick a look for your website. Chosen: Warm and friendly."}], {}, 0, False)[0]["detail"]
ok(b["kind"] == "decision" and b["chosen"] == "Warm and friendly" and "look" in b["asked"], ("a decision reads asked and chosen", b))

srv.shutdown()
# Feedback 3: "Decide for me" runs on its own. The first message is the only input: the plan is approved with the
# suggested model, the look and the four design questions take the suggested picks, every auto decision leaves a
# backstage line and a chat record "Decided for you"; usage is topped up up to J2_AUTO_CAP_X x the approved estimate,
# then it stops and asks.
def _settle(run):
    for _ in range(5000):
        if run.status == "waiting":
            return
        time.sleep(0.02)
    raise AssertionError("the run did not settle")


auto = j2.J2Run()
auto.set_no_questions(True)
auto.user_says("A one-page website for Little Fig cafe in Indiranagar. Menu with prices, opening hours.")
_settle(auto)
ok(auto.legacy_decision() is None and auto.outcome and auto.outcome.startswith(("Done", "Done with open items")),
   ("autonomous: the run reaches an ending with no input after the first message", auto.outcome))
ok([m for m in auto.chat if m["who"] == "user"].__len__() == 1, "autonomous: the only user message is the first one")
ok(auto.proposals and auto.proposals[-1].get("approved") and auto.model_tier == j2.llm.DEFAULT_TIER,
   "autonomous: the plan was approved with the suggested model")
recs = [m["record"] for m in auto.chat if m.get("record")]
ok(all(r.get("answer") == "Decided for you" for r in recs) and {r["kind"] for r in recs} >= {"proposal", "style", "design"}
   and sum(r["kind"] == "design" for r in recs) == 4, ("autonomous: every auto decision is a chat record", [r["title"] for r in recs]))
autos = [m for m in auto.chat if m.get("auto_decision")]
ok(len(autos) >= 6 and all("Decided without asking" in m["text"] or "Not asking" in m["text"] for m in autos),
   "autonomous: every auto decision is a plain backstage line")
ok(auto.style.get("owner_choices") and len(auto.style["owner_choices"]) == 4, "autonomous: the design picks refine the guide")
v = auto.v2_snapshot()
ok(sum(1 for m in v["chat"] if m.get("kind") == "record" and m["answer"] == "Decided for you") == len(recs),
   "autonomous: the records reach the v2 chat")
# the top-up and the cap
cap_run = j2.J2Run()
cap_run.no_questions = True
cap_run.goal, cap_run.estimate, cap_run.budget, cap_run.budget_set = j2.mock_charter(BREW_LAB), 1_000_000, 1_150_000, True
cap_run.proposals = [{"estimate": 1_000_000, "approved": True, "budget": 1_150_000}]
ok(cap_run._auto_cap() == int(1_000_000 * j2.AUTO_CAP_X), "the safety cap is J2_AUTO_CAP_X x the approved estimate")
opts = [{"id": "continue", "label": "Keep going", "gets": "Add 400k and keep going.", "usage": 400_000, "suggested": True},
        {"id": "ship", "label": "Finish as it is", "gets": "You get it as it is.", "usage": 0, "suggested": False}]
got = []
cap_run._handoff = lambda to, **h: got.append(h)
cap_run._decision("usage", "The work you approved is used up.", "Keeping going uses about 400k more.", opts,
                  handoff={"kind": "requester_answered"})
ok(got and got[-1].get("option") == "continue" and got[-1].get("auto_add") == 400_000 and cap_run.legacy_decision() is None,
   "under the cap: usage is topped up without asking")
ok(any(m.get("record", {}).get("answer") == "Decided for you" and "Topped up" in m["record"]["summary"] for m in cap_run.chat),
   "the top-up is a chat record")
cap_run.budget = int(1_000_000 * j2.AUTO_CAP_X) - 300_000
got.clear()
cap_run._decision("usage", "The work you approved is used up.", "Keeping going uses about 400k more.", opts,
                  handoff={"kind": "requester_answered"})
ok(got and got[-1].get("auto_add") == 300_000, "near the cap: the top-up is cut to what is left under it")
cap_run.budget = int(1_000_000 * j2.AUTO_CAP_X)
got.clear()
cap_run.paused = None
d = cap_run._decision("usage", "The work you approved is used up.", "Keeping going uses about 400k more.", opts,
                      handoff={"kind": "requester_answered"})
ok(not got and cap_run.legacy_decision() is d and "usage limit" in d["why"] and not j2.J2Run.decision_problems(d),
   "cap reached: it stops and asks")
ok(any(e["type"] == "auto_cap" for e in cap_run.events) and any("stopped topping up" in m["text"] for m in cap_run.chat),
   "cap reached: logged backstage")
# facts only the owner knows: labelled assumptions, not a question
fx = j2.J2Run()
fx.no_questions = True
got = []
fx._handoff = lambda to, **h: got.append(h)
fx._ask_facts("", [{"question": "What is the street address?", "options": []}], "info", {"kind": "intake"},
              "A few details are missing before we start.", "Your answers go straight into what we make.")
ok(got and "assumption" in got[-1]["answer"].lower() and fx.legacy_decision() is None,
   "facts with Decide for me: the team goes ahead with labelled assumptions")
ok(any(m.get("record", {}).get("title") == "Facts: going ahead with assumptions" for m in fx.chat), "the assumption is a chat record")

print(f"v2_test: {len(checks)} checks passed")
