"""Writes the studio view's fixtures from a real saved run (the Neel Studio website, runs/j2-20261104-122421):
ui/dev/fixtures/studio_ask.json (building, one question about the contact form), studio_auto.json (building with
Decide for me on, one "Decided for you" line) and ui/dev/samples/studio-site.html (the page as the live route
assembles it: real sections, a placeholder for the footer still to come).

Run from the repo root: .venv/bin/python ui/dev/make_studio_fixtures.py [run id]
Fixture mode serves `_live` as /api/v2/live (see api.js FixtureApi.live).
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import j2_v2  # noqa: E402

RUN = sys.argv[1] if len(sys.argv) > 1 else "j2-20261104-122421"
OUT = os.path.join(ROOT, "ui", "dev", "fixtures")
SAMPLE = "/ui/dev/samples/studio-site.html"
# the moment shown: these parts are being built, the contact form waits on the person, the footer is still to come
WORKING = {"W-9", "W-11"}
ASK = "W-13"
WAITING = {"W-23", "W-26", "W-27", "W-22"}


def main():
    st = j2_v2.saved(RUN)
    m = j2_v2.map_saved(RUN)
    if not st or not m:
        sys.exit(f"no saved run {RUN} in runs/")
    payload, page = j2_v2.studio_saved(RUN, "website")
    with open(os.path.join(ROOT, "ui", "dev", "samples", "studio-site.html"), "w", encoding="utf-8") as f:
        f.write(page.replace("Not built in this run", "Coming up").replace("not built in this run", "coming up"))
    for b in m["buildings"]:
        if b["id"] in WORKING or b["id"] == ASK:
            b.update(state="working", progress=0.5, doing="Writing it now", output=None)
        elif b["id"] in WAITING:
            b.update(state="waiting", progress=0.0, doing="Waiting its turn", output=None)
    m["counts"] = {"done": sum(b["state"] == "done" for b in m["buildings"]), "total": len(m["buildings"])}
    for g in st["plan"]["groups"]:
        for t in g["tasks"]:
            b = next((x for x in m["buildings"] if x["id"] == t["id"]), None)
            if b:
                t["status"] = b["state"]
    for u in m["units"]:
        u["state"] = "idle"
    st.update(status="needs_you", status_text="Asha has a question for you", ended=None,
              run={"id": "j2-studio-fixture", "saved": False, "title": "Neel Studio"},
              usage={**st["usage"], "spent": 1700000, "budget": 3500000, "margin_at": 3000000})
    st["decision"] = {"id": "d-21", "kind": "problem", "happening": "Where should messages from the contact form go?",
                      "why": "The form is built; it needs a place to send each request.",
                      "options": [{"id": "wa", "label": "WhatsApp +91 98860 55443", "gets": "Each request opens a WhatsApp chat.", "usage": 0, "suggested": True},
                                  {"id": "email", "label": "Email", "gets": "Each request comes to your inbox.", "usage": 0, "suggested": False},
                                  {"id": "both", "label": "Both", "gets": "WhatsApp, with an email copy.", "usage": 12000, "suggested": False}],
                      "fields": [], "allow_text": True, "proposal": None}
    st["settings"] = {"no_questions": False, "model": "sonnet"}
    st["deliverables"] = [{"kind": "website", "label": "Website", "state": "working", "version": 9, "url": SAMPLE, "download": None}]
    m.update(status="needs_you", attention=ASK, flows=[])
    live = {**payload, "url": SAMPLE, "key": "fixture-1"}
    ask = {**st, "map": m, "_live": {"current": live, "website": live},
           "_next": {"*": "studio_after"}, "_outputs": {}}
    after = copy.deepcopy(ask)
    after.update(status="working", status_text="Building: Team section and FAQ section", decision=None)
    after["map"].update(status="working", attention=None)
    after["_next"] = {}
    auto = copy.deepcopy(after)
    auto["settings"] = {"no_questions": True, "model": "sonnet"}
    nid = max((c["id"] for c in auto["chat"]), default=0) + 1
    auto["chat"].append({"id": nid, "t": "11:02:10", "from": "team", "kind": "record", "title": "Contact form: WhatsApp +91 98860 55443",
                         "summary": "", "answer": "Decided for you", "detail": []})
    for name, data in (("studio_ask", ask), ("studio_after", after), ("studio_auto", auto)):
        with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    print("wrote studio_ask, studio_after, studio_auto and samples/studio-site.html")


if __name__ == "__main__":
    main()
