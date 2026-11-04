"""Offline check of the kingdom view's routes (j2-revamp/api-contract.md: GET /api/v2/map, POST /api/v2/control) in
mock mode: .venv/bin/python -W ignore kingdom_test.py

Walks a mock website run through the server: the map's shape at the start, during the proposal, while building and
when done; flows as deltas by `since`; pause (pausing -> paused, held between turns), a note and a skip applied while
paused, resume to the end; stop ending a run cleanly; redo as a change request after the end; the refusals (409/400);
a saved run's map; a two-stage documents run giving two departments; and a hand-built three-department map.
"""
import json
import os
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
TMP = tempfile.mkdtemp(prefix="j2-kingdom-test-")
os.environ["J2_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["J2_MEMORY_FILE"] = os.path.join(TMP, "lessons.jsonl")
os.environ["J2_PLAYBOOK_FILE"] = os.path.join(TMP, "playbooks.jsonl")
import j2  # noqa: E402
import j2_server  # noqa: E402
import j2_v2  # noqa: E402

for k in ("J2_SEND_MODE", *j2.j2_send.SMTP_VARS, "J2_SEND_CAP"):
    os.environ.pop(k, None)
j2.j2_check.find_chrome = lambda: None
j2.j2_check.check = lambda html: {"available": True, **j2.j2_check.static_checks(html), "phone": {"width": 360, "overflow_px": 0},
                                  "desktop": {"width": 1280, "overflow_px": 0}, "js_errors": [], "design": {},
                                  "form_results": [{"index": i + 1, "has_submit": True, "submitted": True, "invalid": [],
                                                    "errors_during": [], "ok": True}
                                                   for i in range(j2.j2_check.static_checks(html)["forms"])]}
j2.j2_check.tap_targets = lambda html, selector, min_px=44: {"available": True, "roots": 1, "checked": 0, "small_count": 0, "small": []}

BRIEF = ("A one-page website for Still Water Physio in Indiranagar, Bangalore. Services with prices, hours Mon-Sat "
         "8am-8pm, book on WhatsApp +91 98765 43210.")
FACTS = "Hours Mon-Sat 8am-8pm. WhatsApp +91 98765 43210. Address 12 100 Feet Road, Indiranagar."
ROLES = {"client", "planner", "reviewer", "budget", "gatekeeper", "scheduler", "builder", "quality"}
B_STATES = {"waiting", "working", "done", "needs_fix", "skipped"}
U_STATES = {"idle", "working", "waiting"}
checks = []

srv = j2_server.http.server.ThreadingHTTPServer(("127.0.0.1", 0), j2_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def ok(cond, what):
    assert cond, what
    checks.append(what)


def get(path):
    with urllib.request.urlopen(BASE + path) as r:
        return json.loads(r.read())


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def until(pred, what, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = get("/api/v2/state")
        if pred(st):
            return st
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}: status={get('/api/v2/state')['status']}")


def settle():
    return until(lambda st: st["status"] not in ("working", "paused"), "the run to settle")


def answer_until(kind=None, topic=None):
    """Answer what the mock asks (facts with FACTS, the proposal with approve, else the suggested option) until the
    open decision is `kind` (and its `topic`, for a design card) (returned) or the run ends (None)."""
    for _ in range(12):
        st = settle()
        d = st["decision"]
        if not d:
            return None
        if d["kind"] == kind and (topic is None or d.get("topic") == topic):
            return d
        if d["kind"] == "facts":
            post("/api/v2/decide", {"decision_id": d["id"], "option_id": None, "text": FACTS, "fields": {}})
        elif d["kind"] == "proposal":
            post("/api/v2/decide", {"decision_id": d["id"], "option_id": "approve", "text": "", "fields": {}})
        else:
            sug = next(o for o in d["options"] if o["suggested"])
            post("/api/v2/decide", {"decision_id": d["id"], "option_id": sug["id"], "text": "", "fields": {}})
    return None


def shape(m, what):
    ok(set(m) == {"departments", "units", "buildings", "flows", "attention", "status", "counts"}, f"{what}: map has the contract's keys")
    ok(m["departments"] and all(set(d) == {"id", "name", "kind"} for d in m["departments"]), f"{what}: departments")
    dids = {d["id"] for d in m["departments"]}
    for u in m["units"]:
        ok(set(u) == {"id", "role", "label", "dept", "at", "state", "doing"} and u["role"] in ROLES and u["state"] in U_STATES
           and u["dept"] in dids and isinstance(u["doing"], str), f"{what}: unit {u['id']} keys, role and state")
    bids = {b["id"] for b in m["buildings"]}
    for b in m["buildings"]:
        ok(set(b) == {"id", "name", "dept", "progress", "state", "depends_on", "usage", "share", "doing", "output"} and b["state"] in B_STATES
           and 0 <= b["progress"] <= 1 and b["dept"] in dids and all(d in bids for d in b["depends_on"]), f"{what}: building {b['id']} keys and state")
        ok(not j2_v2.CODES.search(b["name"]) and "W-" not in b["name"], f"{what}: building name in plain words: {b['name']}")
        ok((b["state"] == "done") == (b["progress"] == 1.0), f"{what}: done means full: {b['id']}")
    uids = {u["id"] for u in m["units"]} | {"castle"}
    for f in m["flows"]:
        ok(set(f) == {"id", "from", "to", "t", "what"} and f["from"] in uids and f["to"] in uids and f["from"] != f["to"]
           and isinstance(f["what"], str) and not j2_v2.CODES.search(f["what"]), f"{what}: flow keys, ends and plain words")
    ok(m["attention"] is None or m["attention"] in uids | bids, f"{what}: attention is a node id or null")
    ok(set(m["counts"]) == {"done", "total"} and m["counts"]["total"] == len(m["buildings"])
       and m["counts"]["done"] == sum(b["state"] == "done" for b in m["buildings"]), f"{what}: counts add up")


# 1. a fresh run: the map is empty but well-formed; the state carries the control block
j2_server.RUN.reset()
st = get("/api/v2/state")
ok(st["control"] == {"paused": False, "pausing": False, "stopping": False}, "the state carries control: paused, pausing, stopping")
m = get("/api/v2/map")
shape(m, "start")
ok(m["status"] == "idle" and m["buildings"] == [] and m["flows"] == [] and m["attention"] is None, "a fresh run's map is empty")
code, r = post("/api/v2/control", {"action": "pause"})
ok(code == 409 and r["error"], "pause with nothing running is refused with a reason")
code, r = post("/api/v2/control", {"action": "dance"})
ok(code == 400, "an unknown action is a 400")
code, r = post("/api/v2/control", {"action": "skip"})
ok(code == 400, "skip without a part is a 400")

# 2. the proposal: the client lead needs the person; the parts show as planned buildings in a chain
post("/api/v2/say", {"text": BRIEF})
d = answer_until("proposal")
ok(d and d["kind"] == "proposal", "the proposal is open")
m = get("/api/v2/map")
shape(m, "proposal")
ok(m["attention"] == "u-identity" and next(u for u in m["units"] if u["id"] == "u-identity")["state"] == "waiting",
   "during a decision the client lead is the attention node and waits")
ok(m["buildings"] and all(b["id"].startswith("p-") and b["state"] == "waiting" for b in m["buildings"]),
   "before registration the proposal's parts are waiting buildings")
ok(m["flows"] and any(f["to"] == "castle" for f in m["flows"]), "the question to the person is a flow to the castle")
code, r = post("/api/v2/control", {"action": "skip", "target": "p-1"})
ok(code == 409 and "planned" in r["error"], "a planned-only part can't be skipped yet")
code, r = post("/api/v2/control", {"action": "stop"})
ok(code == 200 and r["state"] == "stopped", "stop while waiting on a decision ends the run at once")
st = get("/api/v2/state")
ok(st["status"] == "stopped" and st["ended"]["kind"] == "stopped" and "Stop" in st["ended"]["text"]
   and any(c.get("kind") == "record" and c["title"] == "Stopped" for c in st["chat"]), "the stopped ending reads plainly, with a record in the chat")

# 3. a full run: pause while building, note and skip while paused, resume to the end
post("/api/v2/new", {})
post("/api/v2/say", {"text": BRIEF})
d = answer_until("style")
ok(d and d["kind"] == "style", "the style choice is open")
sug = next(o for o in d["options"] if o["suggested"])
post("/api/v2/decide", {"decision_id": d["id"], "option_id": sug["id"], "text": "", "fields": {}})
d = answer_until("design", "imagery")         # feedback 3: the last quick design card; building follows it
ok(d and d["kind"] == "design", "the design cards follow the look")
sug = next(o for o in d["options"] if o["suggested"])
post("/api/v2/decide", {"decision_id": d["id"], "option_id": sug["id"], "text": "", "fields": {}})
t0 = time.time()           # pause once the parts are registered (the mock plans in well under a second)
code, r = None, None
while time.time() - t0 < 30:
    st = get("/api/v2/state")
    if st["status"] == "needs_you":          # anything else the mock asks on the way: the suggested option
        sug = next(o for o in st["decision"]["options"] if o["suggested"])
        post("/api/v2/decide", {"decision_id": st["decision"]["id"], "option_id": sug["id"], "text": "", "fields": {}})
    elif st["status"] == "working" and any(b["id"].startswith("W-") for b in get("/api/v2/map")["buildings"]):
        code, r = post("/api/v2/control", {"action": "pause"})
        if code == 200:
            break
    elif st["status"] not in ("working",):
        break
    time.sleep(0.002)
ok(code == 200 and r["state"] in ("pausing", "paused"), ("pause is accepted while the run works", code, r, get("/api/v2/state")["status"], time.time() - t0))
st = until(lambda s: s["status"] == "paused", "paused")
ok(st["status"] == "paused" and st["control"]["paused"] and st["status_text"] == "Paused", "the run holds at a safe point: status paused")
ok(any(c.get("kind") == "record" and c["title"] == "Paused" for c in st["chat"]), "a Paused record in the chat")
m = get("/api/v2/map")
shape(m, "paused")
ok(m["status"] == "paused" and not any(u["state"] == "working" for u in m["units"]), "nothing works while paused")
run = j2_server.RUN
time.sleep(0.3)
ok(get("/api/v2/state")["status"] == "paused" and run.status == "running", "still held after a moment (the loop thread is alive)")
waiting = [b for b in m["buildings"] if b["state"] == "waiting"]
built = [b for b in m["buildings"] if b["state"] in ("done", "working")]
ok(m["buildings"], "the map has buildings while paused")
ok(all(u["at"] in {b["id"] for b in m["buildings"]} for u in m["units"] if u["role"] == "builder"), "builders sit at their buildings")
# a note on a part reaches its builder brief
target = (waiting or built or m["buildings"])[0]["id"]
code, r = post("/api/v2/control", {"action": "note", "target": target, "text": "Keep this one short."})
ok(code == 200, ("a note is accepted", code, r, target))
until(lambda s: any(c.get("kind") == "record" and c["title"].startswith("Note for") for c in s["chat"]), "the note record")
w = next(x for x in run._all_wfs() if x["id"] == target)
ok(run.ctl["notes"].get(target) == ["Keep this one short."] and run._builder_brief(w).get("notes_from_the_requester") == ["Keep this one short."],
   "the note is kept and reaches the part's builder brief")
code, r = post("/api/v2/control", {"action": "note", "target": target, "text": ""})
ok(code == 400, "an empty note is a 400")
if waiting:
    code, r = post("/api/v2/control", {"action": "skip", "target": waiting[0]["id"]})
    ok(code == 200, "skip on a waiting part is accepted while paused")
    until(lambda s: any(c.get("kind") == "record" and c["title"].startswith("Skipped") for c in s["chat"]), "the skip record")
    m2 = get("/api/v2/map")
    ok(next(b for b in m2["buildings"] if b["id"] == waiting[0]["id"])["state"] == "skipped", "the skipped part shows as skipped on the map")
    code, r = post("/api/v2/control", {"action": "skip", "target": waiting[0]["id"]})
    ok(code == 409, "skipping it again is refused")
if built:
    code, r = post("/api/v2/control", {"action": "redo", "target": built[0]["id"]})
    ok(code in (200, 409), "redo on a built part while paused is queued (or refused with a reason)")
code, r = post("/api/v2/control", {"action": "resume"})
ok(code == 200 and r["state"] == "running", "resume is accepted")
st = until(lambda s: s["status"] != "paused", "resumed")
ok(any(c.get("kind") == "record" and c["title"] == "Resumed" for c in get("/api/v2/state")["chat"]), "a Resumed record in the chat")
answer_until(None)
st = get("/api/v2/state")
ok(st["status"] in ("done", "done_open", "stopped"), ("the run ends after the resume", st["status"]))
m = get("/api/v2/map")
shape(m, "ended")
ok(m["counts"]["done"] >= 1 and all(u["state"] == "idle" for u in m["units"]) and m["attention"] is None, "at the end every unit is idle")
fix_ids = {b["id"] for b in m["buildings"] if b["state"] == "needs_fix"}
ok(all(u["at"] in fix_ids for u in m["units"] if u["role"] == "builder"), "once its part is done a builder leaves the map (it stays only at a part that needs a fix)")
flows = get("/api/v2/map?since=0")["flows"]
ok(flows and len(flows) <= j2_v2.MAP_FLOWS, "flows are the newest hand-offs")
last = flows[-1]["id"]
ok(get(f"/api/v2/map?since={last}")["flows"] == [], "flows are a delta by since")
mid = flows[len(flows) // 2]["id"]
ok(all(f["id"] > mid for f in get(f"/api/v2/map?since={mid}")["flows"]), "since keeps only newer flows")
# a builder's hand-off is a flow while the builder is on the map; once its part is done the builder leaves (above),
# so at a clean end its flows go too (a light would have nowhere to travel). The hand-offs themselves are in the chat.
if any(u["role"] == "builder" for u in m["units"]):
    ok(any(f["from"].startswith("u-W-") or f["to"].startswith("u-W-") for f in flows), ("builders' hand-offs are flows", [(f["from"], f["to"]) for f in flows]))
else:
    ok(not any(f["from"].startswith("u-W-") or f["to"].startswith("u-W-") for f in flows), "flows name only units still on the map")
    ok(any(x["who"].startswith("W-") and x.get("next") for x in j2_server.RUN.chat), "the builders' hand-offs are addressed to the next agent in the chat")
done_b = next((b for b in m["buildings"] if b["state"] == "done"), None)
code, r = post("/api/v2/control", {"action": "skip", "target": done_b["id"]})
ok(code == 409 and "done" in r["error"], "a done part can't be skipped")
rid = os.path.basename(run.dir)
ms = get(f"/api/v2/map?run={rid}")
shape(ms, "saved")
ok(ms["counts"] == m["counts"] and {b["id"] for b in ms["buildings"]} == {b["id"] for b in m["buildings"]}, "a saved run's map matches the live one")

# 4. redo after the end: a change request on the existing path
if st["status"] in ("done", "done_open"):
    code, r = post("/api/v2/control", {"action": "redo", "target": done_b["id"], "text": "Make it warmer."})
    ok(code == 200 and r["state"] == "running", "redo after the end starts a change request")
    st2 = until(lambda s: s["status"] == "working" or s["chat"][-1]["from"] == "you", "the redo message")
    ok(any(c.get("from") == "you" and c.get("text", "").startswith("Please redo the") and "Make it warmer." in c["text"] for c in get("/api/v2/state")["chat"]),
       "the redo is the person's own message in the chat")
    answer_until(None)
    ok(get("/api/v2/state")["status"] in ("done", "done_open", "stopped"), "the run ends again after the redo")

# 5. stop while building
post("/api/v2/new", {})
post("/api/v2/say", {"text": BRIEF})
d = answer_until("design", "imagery")
sug = next(o for o in d["options"] if o["suggested"])
post("/api/v2/decide", {"decision_id": d["id"], "option_id": sug["id"], "text": "", "fields": {}})
code, r = post("/api/v2/control", {"action": "stop"})
ok(code == 200 and r["state"] == "stopping", "stop is accepted while building")
st = until(lambda s: s["status"] not in ("working", "paused"), "stopped")
ok(st["status"] == "stopped" and st["ended"]["kind"] == "stopped" and "pressed Stop" in st["ended"]["text"], ("stop ends the run cleanly between turns", st["status"], st["ended"]))
ok(os.path.exists(os.path.join(j2_server.RUN.dir, "summary.json")) and j2._read(j2_server.RUN.dir, "summary.json")["status"] == "stopped",
   "the stopped run is saved")
code, r = post("/api/v2/control", {"action": "resume"})
ok(code == 409, "resume on a stopped run is refused")

# 5b. a pause asked for while a batch of builders works: the builders not started yet wait for the resume
real_ask = j2.llm.ask


def slow_ask(system, user, mock, **kw):
    if "YOU OWN SECTION" in user:        # a builder's call takes a while, like a real one
        time.sleep(1.2)
    return real_ask(system, user, mock, **kw)


j2.llm.ask = slow_ask
try:
    post("/api/v2/new", {})
    post("/api/v2/say", {"text": BRIEF})
    d = answer_until("design", "imagery")
    sug = next(o for o in d["options"] if o["suggested"])
    post("/api/v2/decide", {"decision_id": d["id"], "option_id": sug["id"], "text": "", "fields": {}})
    t0, code, r = time.time(), None, None
    while time.time() - t0 < 40:
        st = get("/api/v2/state")
        if st["status"] == "needs_you":
            sug = next(o for o in st["decision"]["options"] if o["suggested"])
            post("/api/v2/decide", {"decision_id": st["decision"]["id"], "option_id": sug["id"], "text": "", "fields": {}})
        elif st["status"] == "working" and any(b["state"] == "working" for b in get("/api/v2/map")["buildings"]):
            code, r = post("/api/v2/control", {"action": "pause"})
            break
        elif st["status"] not in ("working",):
            break
        time.sleep(0.02)
    ok(code == 200 and r["state"] == "pausing", ("pause asked for while a builder works", code, r))
    st = get("/api/v2/state")
    ok(st["status"] == "working" and st["control"]["pausing"] and st["status_text"] == "Pausing after this step…",
       ("the status says the pause lands after this step", st["status"], st["status_text"]))
    st = until(lambda s: s["status"] == "paused", "paused after the builder", timeout=40)
    batch = next((m for m in j2_server.RUN.chat if m.get("batch") and "work at the same time" in m["text"]), None)
    deferred = [m for m in j2_server.RUN.chat if m.get("batch") and m["text"].startswith("Not started yet, on your pause")]
    m = get("/api/v2/map")
    started = [b for b in m["buildings"] if b["state"] in ("done", "working", "needs_fix")]
    ok(batch is not None and deferred, ("a batch was running and the builders not started yet were put off", bool(batch), len(deferred)))
    ok(batch is None or len(started) < len(batch["batch"]), ("no further builder of the batch started after the pause", len(started), batch and len(batch["batch"])))
    ok(not any(u["state"] == "working" for u in m["units"]), "nothing works while paused")
    code, r = post("/api/v2/control", {"action": "resume"})
    ok(code == 200, "resume after the deferred batch")
    st = until(lambda s: s["status"] not in ("working", "paused") or s["status"] == "needs_you", "the run to go on", timeout=60)
    answer_until(None)
    st = get("/api/v2/state")
    ok(st["status"] in ("done", "done_open"), ("the put-off builders ran after the resume and the run ended", st["status"]))
    ok(all(w["status"] == "done" for w in j2_server.RUN.workflows if w.get("kind") != "polish"), "every part was built in the end")
finally:
    j2.llm.ask = real_ask

# 6. a documents chain: two stages give two departments; the look is chosen after the documents, before the website
post("/api/v2/new", {})
post("/api/output", {"stages": ["prd", "website"]})
post("/api/v2/say", {"text": BRIEF})
for _ in range(60):      # the mock's PRD never satisfies every condition: an owner accepts it as it is and goes on
    st = settle()
    d = st["decision"]
    if not d:
        break
    if d["kind"] == "facts":
        post("/api/v2/decide", {"decision_id": d["id"], "option_id": None, "text": FACTS, "fields": {}})
    elif d["kind"] == "proposal":
        post("/api/v2/decide", {"decision_id": d["id"], "option_id": "approve", "text": "", "fields": {}})
    else:
        pick = next((o for o in d["options"] if o["id"] == "ship" and d["kind"] in ("usage", "problem")), None) \
            or next(o for o in d["options"] if o["suggested"])
        post("/api/v2/decide", {"decision_id": d["id"], "option_id": pick["id"], "text": "", "fields": {}})
st = get("/api/v2/state")
m = get("/api/v2/map")
shape(m, "two stages")
texts = [c["text"] for c in j2_server.RUN.chat]
i_docs = next((i for i, t in enumerate(texts) if t.startswith("The documents are done. Now the website")), None)
i_look = next((i for i, t in enumerate(texts) if t.startswith("Design research:")), None)
diag = (i_docs, i_look, j2_server.RUN.stage_kind, list(j2_server.RUN.docs), [d["kind"] for d in j2_server.RUN.decisions], st["status"], texts[-3:])
ok(i_docs is not None and i_look is not None and i_look > i_docs, ("in a chain the look is chosen after the documents, just before the website", diag))
i_prop = next((i for i, t in enumerate(texts) if "Usage budget set from the approved plan" in t), None)
ok("prd" in j2_server.RUN.docs and i_prop is not None and i_prop < i_docs < i_look and (j2_server.RUN.design or {}).get("chosen"),
   ("the style decision comes after the proposal and the finished PRD, and a look was chosen", i_prop, i_docs, i_look, list(j2_server.RUN.docs)))
ok(j2_server.RUN.chosen_style and j2_server.RUN.chosen_style.get("direction"), "the website stage got the chosen look as its style guide")
ok(j2_v2.open_items(["the product requirements: done-when item 3 (F-3 NEEDS_REVISION): The Goals section lists the aims; "
                     "document rubric D-5 (NEEDS_REVISION): No invented facts: every fact comes from the brief",
                     "done-when item 1 (F-1 NEEDS_REVISION): The Purpose section is written",
                     "document rubric D-5 (NEEDS_REVISION): No invented facts: every fact comes from the brief or your answers",
                     "necessary condition H5 not met: No invented facts: every number comes from the brief (none)",
                     "necessary condition H6 not met: Nothing is \"to be confirmed\" (the document says 'to be confirmed'; all 1 fact(s) appear)",
                     "the low-level design"])
   == ["In the product requirements: The Goals section lists the aims",
       "In the product requirements: No invented facts: every fact comes from the brief",
       "The Purpose section is written",
       "Nothing is \"to be confirmed\"",
       "The low-level design, kept as it was"], ("open items: one per problem, named for its stage, no ids, counts or evidence, no repeats", j2_v2.open_items(["x"])))
ok([d["id"] for d in m["departments"]] == ["d-prd", "d-website"], ("a PRD then a website: two departments in order", m["departments"]))
ok({b["dept"] for b in m["buildings"]} >= {"d-prd"} and all(u["dept"] in ("d-prd", "d-website") for u in m["units"]),
   "buildings and units belong to their departments")

# 7. a hand-built three-department map (the fixture shape the UI's zoom and mini-map are tested with)
wfs = []
for i, k in enumerate(("prd", "hld", "lld"), 1):
    for n in range(2):
        wid = f"W-{(i - 1) * 2 + n + 1}"
        wfs.append({"id": wid, "name": f"{k.upper()} part {n + 1}", "status": "done" if i < 3 else ("running" if n == 0 else "registered"),
                    "stage": k, "depends_on": [f"W-{(i - 1) * 2 + n}"] if n else [], "envelope": {"token_share": 1000}, "usage": 500,
                    "atoms": [{"id": f"{wid}.a1", "status": "passed"}, {"id": f"{wid}.a2"}] if i == 3 and n == 0 else []})
chat = [{"id": 1, "t": "10:00:00", "who": "adaptation", "text": "@Priority Proposal: W-1 PRD part 1.", "next": "priority"},
        {"id": 2, "t": "10:00:01", "who": "W-5", "text": "@Coordination W-5 done.", "next": "coordination"}]
m = j2_v2.map_build(wfs, chat, ["prd", "hld", "lld"], lambda w: w["stage"], "lld", "working", {"W-5"}, "W-5", {}, 0)
shape(m, "three departments")
ok(len(m["departments"]) == 3 and {b["dept"] for b in m["buildings"]} == {"d-prd", "d-hld", "d-lld"}, "three departments, each with its buildings")
b5 = next(b for b in m["buildings"] if b["id"] == "W-5")
ok(b5["state"] == "working" and b5["progress"] == 0.5 and next(u for u in m["units"] if u["id"] == "u-W-5")["state"] == "working",
   "a running part with one of two atoms passed is half built; its builder works")
ok(next(b for b in m["buildings"] if b["id"] == "W-6")["doing"].startswith("Waits for "), "a waiting part says what it waits for")
ok([f["from"] + ">" + f["to"] for f in m["flows"]] == ["u-adaptation>u-priority", "u-W-5>u-coordination"], "flows are the hand-offs between units")
ok(all(u["dept"] == "d-lld" for u in m["units"] if u["role"] != "builder"), "the core units sit in the current department")

# Who's working (feedback 2): a manager's token is lit while it thinks, including the helper calls that serve it,
# and the top bar names it.
unit = lambda m, uid: next(u for u in m["units"] if u["id"] == uid)
for fns, turn, uid, doing in ((set(), "adaptation", "u-adaptation", "Planning the parts"),
                              ({"realization-adaptation"}, None, "u-adaptation", "Planning the parts"),
                              ({"design-research"}, None, "u-adaptation", "Studying sites like yours"),
                              ({"check-judge"}, "audit", "u-audit", "Reviewing the page"),
                              ({"work-order-review"}, "validator", "u-validator", "Checking the work orders")):
    m = j2_v2.map_build([], [], ["website"], lambda w: "website", "website", "working", fns, turn, {}, 0)
    ok(unit(m, uid)["state"] == "working" and unit(m, uid)["doing"] == doing
       and sum(u["state"] == "working" for u in m["units"]) == 1, (f"{uid} lit while {fns or turn} works", unit(m, uid)))
ok(j2_v2.named_doing("adaptation") == "Planner is planning the parts"
   and j2_v2.named_doing("audit") == "Quality check is reviewing the page"
   and j2_v2.named_doing("audit", "prd") == "Quality check is reviewing the document"
   and j2_v2.named_doing("quality-judge") == "Quality check is reviewing the page", "the top bar names the manager at work")
# Part names read plainly and the same everywhere (feedback 2)
ok(j2_v2.plain_name("build_page_shell_and_nav") == "Page shell & navigation"
   and j2_v2.plain_name("Build WhatsApp order call to action") == "WhatsApp order button"
   and j2_v2.plain_name("Booking form") == "Booking form", "part names drop a leading Build when it stays clear")
# "See output" (feedback 2): a finished part says what it made
ok(j2_v2.output_kind({"parts": ["page_section"], "outputs": ["index.html"]}, "website")["kind"] == "section"
   and j2_v2.output_kind({"name": "Style guide", "parts": ["styling"], "outputs": ["design_guide.md"]}, "design")["kind"] == "style"
   and j2_v2.output_kind({"research": {"output": "research.md#R-1"}, "outputs": ["research.md"]})["kind"] == "research"
   and j2_v2.output_kind({"parts": ["doc_section"], "outputs": ["section_map.md"]}, "product")["kind"] == "notes"
   and j2_v2.output_kind({"parts": ["doc_section"], "outputs": ["## Goals"]}, "prd") == {"kind": "document", "doc": "prd"},
   "a finished part's output kind")
# feedback 4: the output is the part's real file, whole and plain (no part ids, file names, element ids or CSS)
import re, shutil as _sh, tempfile as _tf  # noqa: E402
_d = _tf.mkdtemp(prefix="j2-ktest-out-")
os.makedirs(os.path.join(_d, "artifacts"))
with open(os.path.join(_d, "artifacts", "plan.md"), "w") as _f:
    _f.write("# Neel Studio: page plan\n\nEvery later workflow follows this file. Chosen by the Requester.\n\n"
             "## Section order\n\n| # | Section | Anchor id | Built by |\n|---|---|---|---|\n| 1 | Hero | `#hero` | W-2 |\n\n"
             "## Hero\n\n- Anchor: `#hero`\n- One button `#hero-cta` links to `#contact-form`, class `j2-btn`.\n"
             "- Price: Rs 2,50,000 onwards. Phone +91 98450 12345.\n")
with open(os.path.join(_d, "artifacts", "style.md"), "w") as _f:
    _f.write("# Style\n\n- **Rose stays an accent.** Use it for buttons and icons.\n- **Prices are `--j2-text`.** Not rose.\n")
_wfs = [{"id": "W-1", "name": "plan_scope_and_flow", "parts": ["doc_section"], "outputs": ["plan.md"], "status": "done"},
        {"id": "W-2", "name": "build_home_hero", "parts": ["page_section"], "outputs": ["index.html"], "status": "done"},
        {"id": "W-3", "name": "design_style_guide", "parts": ["design"], "outputs": ["style.md"], "status": "done"}]
_o = j2_v2.output_payload("W-1", _wfs, _d, {}, None, lambda w: None, None)
_md = _o["markdown"]
ok(_o["kind"] == "notes" and _md.startswith("# Neel Studio: page plan") and "Rs 2,50,000 onwards" in _md
   and "+91 98450 12345" in _md and "Home hero" in _md and "links to the contact form section" in _md
   and not re.search(r"W-\d|\.md\b|`|#hero|j2-|Anchor|workflow|Requester", _md) and "| Hero | Home hero |" in _md,
   ("a planning part's output is its whole file, plain", _md))
_o = j2_v2.output_payload("W-3", _wfs, _d, {}, {"direction": "Calm", "notes": "Quiet and airy.", "palette": {}}, lambda w: None, None)
ok(_o["kind"] == "style" and _o["rules"] == ["Quiet and airy.", "Rose stays an accent: Use it for buttons and icons."],
   ("the look's key rules in plain words", _o.get("rules")))
_sh.rmtree(_d, ignore_errors=True)

srv.shutdown()
print(f"kingdom_test: {len(checks)} checks passed")
