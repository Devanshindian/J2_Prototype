"""Offline check of the studio view's backend (j2-revamp/api-contract.md: map buildings `kind`, GET /api/v2/live,
GET /api/v2/live/site) in mock mode: .venv/bin/python -W ignore studio_test.py

Covers: the writer / designer / builder rules on real part names (a website run and a documents chain); a mock
website run walked through the server (the sketch before any part, placeholders with section anchors while it
builds, the whole page at the end, every anchor on the page, a stable key); a mock PRD run's blocks with the parts
that wrote them; a hand-built saved run folder (a website, and a documents chain whose website never started); the
deliverable a finished chain never started reads "todo"; / serves the studio view and ?view=kingdom the map view.
"""
import atexit
import json
import os
import re
import shutil
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
TMP = tempfile.mkdtemp(prefix="j2-studio-test-")
atexit.register(shutil.rmtree, TMP, True)     # runs and memory files of this check never pile up
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
KINDS = ("writer", "designer", "builder")
checks = []

srv = j2_server.http.server.ThreadingHTTPServer(("127.0.0.1", 0), j2_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def ok(cond, what):
    assert cond, what
    checks.append(what)


def raw(path):
    with urllib.request.urlopen(BASE + path) as r:
        return r.read().decode("utf-8")


def get(path):
    return json.loads(raw(path))


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def settle(timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = get("/api/v2/state")
        if st["status"] not in ("working", "paused"):
            return st
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the run to settle")


def answer_all(stop=None):
    """Answer every question with the suggested option (facts typed, the plan approved) until the run ends, or until
    `stop(state)` is true (returned)."""
    for _ in range(40):
        st = settle()
        if stop and stop(st):
            return st
        d = st["decision"]
        if not d:
            return st
        if d["kind"] == "facts":
            post("/api/v2/decide", {"decision_id": d["id"], "option_id": None, "text": FACTS, "fields": {}})
        elif d["kind"] == "proposal":
            post("/api/v2/decide", {"decision_id": d["id"], "option_id": "approve", "text": "", "fields": {}})
        else:
            sug = next((o for o in d["options"] if o["suggested"]), d["options"][0])
            post("/api/v2/decide", {"decision_id": d["id"], "option_id": sug["id"], "text": "", "fields": {}})
    return get("/api/v2/state")


def live_shape(lv, what):
    ok({"kind", "doc", "title", "anchors", "part_kinds", "key"} <= set(lv) and lv["kind"] in ("website", "document"),
       f"{what}: the live payload has the contract's keys")
    ok(all(v in KINDS for v in lv["part_kinds"].values()), f"{what}: every part has a kind")
    ok(re.fullmatch(r"[0-9a-f]{12}", lv["key"]), f"{what}: the key is a short hash")


# 1. the kind rules on real part names (the Neel Studio website run, a documents chain)
site_names = {"plan_scope_and_flow": ("product", "writer"), "write_site_copy": ("content", "writer"),
              "design_style_guide": ("design", "designer"), "engineering_whatsapp_integration": ("engineering", "builder"),
              "build_home_hero": ("build", "designer"), "build_services_section": ("build", "writer"),
              "build_portfolio_section": ("build", "designer"), "build_faq_section": ("build", "writer"),
              "build_contact_info_section": ("build", "writer"), "build_contact_form": ("build", "builder"),
              "build_site_shell_and_integration": ("build", "builder"), "Testimonials section": ("build", "writer"),
              "Add testimonials link to nav": ("build", "builder"), "Redesign testimonials empty state": ("build", "designer"),
              "Add site footer": (None, "builder"), "Make sections visible by default": ("build", "builder")}
for name, (stage, want) in site_names.items():
    ok(j2_v2.part_kind({"name": name, "stage": stage, "parts": ["page_section"] if stage == "build" else []}, stage) == want,
       f"kind: {name} is the {want}'s")
ok(j2_v2.part_kind({"name": "Polish", "kind": "polish"}, "build") == "designer", "kind: the website polish is the designer's")
ok(j2_v2.part_kind({"name": "Polish", "kind": "polish"}, "prd") == "writer", "kind: a document's polish is the writer's")
for name, want in (("PRD Problem", "writer"), ("PRD Success metrics", "writer"), ("HLD Components", "builder"),
                   ("HLD Data flow", "builder"), ("HLD Risks", "writer"), ("LLD Form fields", "builder")):
    ok(j2_v2.part_kind({"name": name, "parts": ["doc_section"]}, name[:3].lower()) == want, f"kind: {name} is the {want}'s")
ok(j2_v2.part_kind({"name": "Something else"}, None) == "builder", "kind: a part nothing matches falls back to the builder")

# 2. the studio view is the page at /; the map view stays at ?view=kingdom
ok('src="/ui/js/studio/main.js"' in raw("/"), "/ serves the studio view")
ok('src="/ui/js/main.js"' in raw("/?view=kingdom"), "/?view=kingdom serves the map view")

# 3. a mock website run through the server
j2_server.RUN.reset()
lv = get("/api/v2/live")
live_shape(lv, "fresh")
ok(lv["kind"] == "website" and not lv["started"] and lv["url"] is None and lv["anchors"] == {}, "fresh: nothing started, no page yet")
post("/api/v2/say", {"text": BRIEF})
st = answer_all(stop=lambda s: (s["decision"] or {}).get("kind") == "proposal")
m = get("/api/v2/map")
ok(m["buildings"] and all(b["kind"] in KINDS for b in m["buildings"]), "proposal: the planned parts carry a kind")
# pause once the parts are registered, so the page is caught half built
post("/api/v2/settings", {"no_questions": True})
code, r, t0 = None, None, time.time()
while time.time() - t0 < 30:
    st = get("/api/v2/state")
    if st["status"] == "working" and any(b["id"].startswith("W-") for b in get("/api/v2/map")["buildings"]):
        code, r = post("/api/v2/control", {"action": "pause"})
        if code == 200:
            break
    elif st["status"] not in ("working", "needs_you"):
        break
    time.sleep(0.002)
ok(code == 200, "pause is accepted once the parts are registered")
t0 = time.time()
while get("/api/v2/state")["status"] != "paused" and time.time() - t0 < 20:
    time.sleep(0.01)
m = get("/api/v2/map")
ok(all(b["kind"] in KINDS for b in m["buildings"]), "paused: every part on the map has a kind")
lv = get("/api/v2/live")
live_shape(lv, "paused")
ok(lv["started"] and lv["url"] == "/api/v2/live/site", "paused: the page has started")
page = raw("/api/v2/live/site")
secs = set(re.findall(r'data-j2-section="([\w-]+)"', page))
ok(secs and set(lv["anchors"].values()) <= secs, "paused: every part's anchor is on the page")
ok(set(lv["pending"]) <= secs and all(f'data-j2-section="{s}" data-j2-wait="1"' in page for s in lv["pending"]),
   "paused: each section still to come is a placeholder with its anchor")
ok(lv["key"] == get("/api/v2/live")["key"], "paused: the key is stable while nothing moves")
before = lv["key"]
post("/api/v2/control", {"action": "resume"})
st = answer_all()
ok(st["status"] in ("done", "done_open"), f"the website run ends ({st['status']})")
lv = get("/api/v2/live")
live_shape(lv, "end")
page = raw("/api/v2/live/site")
ok(lv["built"] and lv["pending"] == [] and "data-j2-wait=\"1\"" not in page, "end: every section is built, no placeholder left")
ok(set(lv["anchors"].values()) <= set(re.findall(r'data-j2-section="([\w-]+)"', page)), "end: every anchor is on the page")
ok(lv["key"] != before, "end: the key moved as the page grew")
run_id = st["run"]["id"]
ok(get(f"/api/v2/live?run={run_id}")["anchors"] == lv["anchors"], "the saved copy of the run gives the same anchors")
ok("data-j2-section" in raw(f"/api/v2/live/site?run={run_id}"), "the saved run's page has its anchors")
ok(get("/api/v2/live?kind=prd")["kind"] == "website", "a kind the run doesn't make falls back to what it makes")


class Racy(dict):
    """The run's sections while a builder thread writes one mid-read (the dict is shared with the build threads)."""
    def items(self):
        it = iter(dict.items(self))
        yield next(it)
        self[f"W-race-{len(self)}"] = {"owner": "W-race", "head": "", "body": "<p>late</p>"}
        yield from it


keep = j2_server.RUN.sections
j2_server.RUN.sections = Racy(keep)
try:
    snap, html_now = j2_v2.studio_live(j2_server.RUN)
    ok(snap["kind"] == "website" and html_now, "live: a section written while the page is read never breaks /api/v2/live")
finally:
    j2_server.RUN.sections = keep

# 4. a mock PRD run: blocks, each with the parts that wrote it
post("/api/v2/new", {})
post("/api/output", {"type": "prd"})
post("/api/v2/say", {"text": "A PRD for a simple appointment booking app for physio clinics. Patients book a slot."})
st = answer_all()
lv = get("/api/v2/live")
live_shape(lv, "prd")
ok(lv["kind"] == "document" and lv["doc"] == "prd" and lv["blocks"], "prd: the live payload is the document in blocks")
ok(all({"anchor", "parts", "state", "markdown", "name", "note"} <= set(b) for b in lv["blocks"]), "prd: blocks have the contract's keys")
done = [b for b in lv["blocks"] if b["markdown"]]
ok(done and all(b["markdown"].lstrip().startswith("## ") for b in done), "prd: written blocks start with their heading")
ok(any(b["parts"] for b in done) and all(p in lv["anchors"] for b in done for p in b["parts"]), "prd: blocks name the parts that wrote them")
ok(all(lv["part_kinds"][p] in KINDS for b in done for p in b["parts"]), "prd: those parts have a kind")

# 5. pure parts: a hand-made run folder (a website half built; a documents chain whose website never started)
wfs = [{"id": "W-1", "name": "build_home_hero", "stage": "build", "status": "done", "section": "W-1", "parts": ["page_section"]},
       {"id": "W-2", "name": "build_contact_form", "stage": "build", "status": "registered", "section": "W-2", "parts": ["form"]},
       {"id": "W-3", "name": "Trim hero CTA", "stage": "build", "status": "running", "section": "W-1", "parts": ["fix"]},
       {"id": "W-4", "name": "write_site_copy", "stage": "content", "status": "done", "section": "W-4", "parts": ["artifact"], "outputs": ["copy.md"]},
       {"id": "W-5", "name": "build_footer", "stage": "build", "status": "done", "section": "W-5", "parts": ["page_section"]}]
sections = {"style": {"owner": "W-1", "head": "<style>body{margin:0}</style>", "body": ""},
            "W-1": {"owner": "W-1", "head": "", "body": '<section id="hero"><h1>Hello</h1></section>'},
            "W-5": {"owner": "W-5", "head": "", "body": "<footer><p>Bye</p></footer>"}}
html_out, anchors, pending = j2_v2.live_site("Test", wfs, sections)
ok(anchors == {"W-1": "W-1", "W-2": "W-2", "W-3": "W-1", "W-5": "W-5"}, "site: parts map to their sections (a fix to the one it revises; notes have none)")
ok(pending == ["W-2"] and 'data-j2-section="W-2" data-j2-wait="1"' in html_out, "site: the form still to come is a placeholder")
ok(html_out.index('data-j2-section="W-1"') < html_out.index('data-j2-section="W-2"') < html_out.index('data-j2-section="W-5"'),
   "site: the placeholder sits where its part lands (before the footer)")
ok('<section data-j2-section="W-1" id="hero">' in html_out, "site: the section's own markup is kept, the anchor added")
ok("Coming up" in html_out and "Not built" in j2_v2.live_site("Test", wfs, sections, ended=True)[0], "site: a placeholder says coming up, or not built once ended")
rd = os.path.join(TMP, "runs", "j2-20991231-101500")
os.makedirs(os.path.join(rd, "site"))
for name, data in (("workflows.json", wfs), ("sections.json", sections), ("goal.json", {"site_name": "Test Cafe"}),
                   ("summary.json", {"outcome": "done"})):
    with open(os.path.join(rd, name), "w", encoding="utf-8") as f:
        json.dump(data, f)
with open(os.path.join(rd, "chat.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"meta": True, "output": "website"}) + "\n")
lv = get("/api/v2/live?run=j2-20991231-101500")
ok(lv["title"] == "Test Cafe" and lv["url"] == "/api/v2/live/site?run=j2-20991231-101500" and "Not built" in raw(lv["url"]),
   "saved: a half-built site opens with its placeholders marked not built")
rd2 = os.path.join(TMP, "runs", "j2-20991231-101600")
os.makedirs(os.path.join(rd2, "site"))
dw = [{"id": "W-1", "name": "PRD Problem", "status": "done", "section": "W-1", "parts": ["doc_section"]},
      {"id": "W-2", "name": "PRD Users", "status": "done", "section": "W-2", "parts": ["doc_section"]}]
dsec = {"W-1": {"owner": "W-1", "head": "", "body": "## Problem\n\nBooking is slow."},
        "W-2": {"owner": "W-2", "head": "", "body": "## Users\n\nClinics."}}
for name, data in (("workflows.json", dw), ("sections.json", dsec), ("goal.json", {"product_name": "Booky"}),
                   ("documents.json", {"prd": {"file": "prd.md", "workflows": ["W-1", "W-2"]}}),
                   ("summary.json", {"design_documents": {"stages": ["prd", "website"]}}), ("stage-prd.json", {"sections": dsec})):
    with open(os.path.join(rd2, name), "w", encoding="utf-8") as f:
        json.dump(data, f)
with open(os.path.join(rd2, "prd.md"), "w", encoding="utf-8") as f:
    f.write("# Booky\n\n## Problem\n\nBooking is slow.\n\n## Users\n\nClinics.\n")
with open(os.path.join(rd2, "chat.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"meta": True, "output": "prd"}) + "\n")
lv = get("/api/v2/live?run=j2-20991231-101600")
ok(lv["kind"] == "document" and lv["doc"] == "prd" and [b["parts"] for b in lv["blocks"]] == [["W-1"], ["W-2"]],
   "saved chain: opens on the PRD (its website never started), each block with its part")
lw = get("/api/v2/live?run=j2-20991231-101600&kind=website")
ok(lw["kind"] == "website" and not lw["started"] and lw["url"] is None, "saved chain: the website reads as not started")
dl = j2_v2.deliverables(["prd", "website"], {"prd"}, "website", 0, rd2, saved_name="x", finished=True)
ok([d["state"] for d in dl] == ["done", "todo"], "a finished chain's website that made nothing is todo, not done")

print(f"studio_test: {len(checks)} checks passed")
