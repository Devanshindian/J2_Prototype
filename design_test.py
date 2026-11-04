"""Offline checks for step 11 (design research and the style choice), mock mode. Run:
    .venv/bin/python -W ignore design_test.py
Covers: the research prompt is derived from the charter (no fixed keyword list); the R-design entry's plumbing
(parsing, sources, research.md); the three directions (validated guides, inspired_by); preview rendering; the style
decision (shape, preview_url, pick, auto-pick with no_questions); the chosen guide reaching the builders (style step
without a model call, R-design and the bar in every site builder's prompt); the quality judge (R-8) and the answered-
decision record in the chat."""
import json
import os
import re
import sys
import tempfile
import time

os.environ["STUDIO_MOCK"] = "1"
os.environ.setdefault("J2_RUNS_DIR", tempfile.mkdtemp(prefix="j2-design-test-"))
os.environ.setdefault("J2_MEMORY_FILE", os.path.join(os.environ["J2_RUNS_DIR"], "lessons.jsonl"))      # never the real memory/
os.environ.setdefault("J2_PLAYBOOK_FILE", os.path.join(os.environ["J2_RUNS_DIR"], "playbooks.jsonl"))
os.environ.pop("J2_TOKEN_BUDGET", None)        # the proposal pause is the point: the style choice follows it
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import j2            # noqa: E402
import j2_design     # noqa: E402
import j2_v2         # noqa: E402
import llm           # noqa: E402

checks = []
BRIEF = ("A one-page website for Still Water Physio in Indiranagar, Bangalore. Services with prices, hours Mon-Sat "
         "8am-8pm, book on WhatsApp +91 98765 43210.")
FACTS = "Hours Mon-Sat 8am-8pm. WhatsApp +91 98765 43210. Address 12 100 Feet Road, Indiranagar."


def ok(cond, what):
    assert cond, what
    checks.append(what)


def wait(run):
    for _ in range(3000):
        if run.status == "waiting":
            return
        time.sleep(0.02)
    raise AssertionError("the run did not settle")


def until(run, kind, answer=None):
    """Answer what the mock asks until the open decision is `kind` (returned), answering facts with FACTS."""
    for _ in range(8):
        d = run.legacy_decision()
        if not d:
            return None
        if d["kind"] == kind:
            return d
        if d["kind"] == "facts":
            run.decide(d["id"], None, text=FACTS)
        elif d["kind"] == "proposal":
            run.decide(d["id"], "approve")
        else:
            run.decide(d["id"], next(o for o in d["options"] if o["suggested"])["id"])
        wait(run)
    return None


# 1. the research question comes from the charter, never a fixed list
physio = {"site_name": "Still Water Physio", "business_type": "a physiotherapy clinic", "audience": "people with injuries",
          "done_when": ["Services with prices are listed", "Visitors can book an appointment on WhatsApp",
                        "Opening hours are shown"]}
cafe = {"site_name": "Little Fig", "business_type": "a cafe", "audience": "neighbours looking for breakfast",
        "done_when": ["The menu with prices is shown", "Visitors can order on the phone", "Opening hours are shown"]}
p1, p2 = j2_design.problem(physio), j2_design.problem(cafe)
ok(p1["business"] == "a physiotherapy clinic" and "book an appointment" in p1["actions"] and "check opening hours" in p1["actions"],
   "the problem is read from the charter: business type and the visitors' actions")
ok("browse the menu" in p2["actions"] and "place an order" in p2["actions"] and "book an appointment" not in p2["actions"],
   "a different charter gives different actions")
r1, r2 = j2_design.research_prompt(physio), j2_design.research_prompt(cafe)
ok("physiotherapy clinic" in r1 and "people with injuries" in r1 and "book an appointment" in r1, "the prompt names the charter's problem")
ok("cafe" in r2 and "physio" not in r2.lower(), "no fixed keyword list: the cafe prompt carries no physio words")
ok(f"at most {j2_design.MAX_QUERIES} searches" in r1 and f"at most {j2_design.MAX_FETCHES} pages" in r1,
   "the research call is bounded in the prompt")
ok(j2.DESIGN_BUDGET_USD > 0 and "--max-budget-usd" in llm.cli_command(["--system-prompt", "s"], ["--output-format", "json"],
                                                                       "high", tools=["web", "github"], max_budget_usd=0.75),
   "the CLI call carries a spend cap")
ok(j2.tools_for("design") == ["web", "github"], "the design research has the read-only web and GitHub tools")

# 2. the entry's plumbing
entry, err = j2_design.parse_research("<<<FILE\n" + j2_design.mock_research(physio) + "FILE>>>")
ok(entry and entry.startswith("## R-design") and len(j2_design.sources(entry)) == 3 and not err, "the fixture entry parses")
ok("Section order" in j2_design.patterns(entry) and "**Findings" not in j2_design.patterns(entry), "patterns() returns the Patterns part")
bad, err = j2_design.parse_research("## R-design: x\n\n**Sources:**\n- https://a.com\n\n**Findings:** f\n\n**Patterns:** p")
ok(bad is None and "needs at least 3" in err, "too few sources is refused")
ok(j2.research_entries("## R-1: a\nx\n\n## R-design: b\ny\n").keys() == {"R-1", "R-design"}, "research.md reads R-design beside R-n")

# 3. the directions
dirs, err = j2_design.parse_directions(json.dumps({"directions": j2_design.mock_directions()}), j2.check_style, llm.extract_json)
ok(dirs and len(dirs) == 3 and [d["id"] for d in dirs] == ["s1", "s2", "s3"] and sum(d["suggested"] for d in dirs) == 1, "three directions, one suggested")
ok(all(d["guide"]["palette"]["primary"] and d["guide"]["motion"]["duration"] and d["guide"]["imagery"]["approach"]
       and d["guide"]["layout"]["pattern"] and d["inspired_by"]["url"].startswith("http") for d in dirs),
   "each is a complete guide (palette, motion, imagery, layout) with an inspired-by url")
two = json.dumps({"directions": j2_design.mock_directions()[:2]})
ok(j2_design.parse_directions(two, j2.check_style, llm.extract_json)[0] is None, "two directions are refused")
broken = j2_design.mock_directions()
broken[1]["guide"]["palette"]["primary"] = "red"
r, err = j2_design.parse_directions(json.dumps({"directions": broken}), j2.check_style, llm.extract_json)
ok(r is None and "direction 2" in err and "hex" in err, "a guide without hex colours is refused with the reason")
pale = j2_design.mock_directions()
pale[0]["guide"]["palette"]["primary"] = "#e8906a"          # white on this is about 2.4:1
pale[0]["guide"]["buttons"]["primary"] = "background:#e8906a;color:#fff;padding:14px 24px"
r, err = j2_design.parse_directions(json.dumps({"directions": pale}), j2.check_style, llm.extract_json)
g0 = r[0]["guide"]
ok(j2_design.contrast(g0["palette"]["primary"], "#ffffff") >= 4.5 and g0["palette"]["primary"] in g0["buttons"]["primary"]
   and "code darkened" in g0["notes"], "a primary too pale for white button text is darkened by code, buttons updated")
ok(j2_design.parse_directions(json.dumps({"directions": j2_design.mock_directions()}), j2.check_style, llm.extract_json)[0][0]["guide"]["palette"]
   == j2_design.mock_directions()[0]["guide"]["palette"], "a palette that already meets AA is left alone")
broken_json = json.dumps({"directions": j2_design.mock_directions()}).replace('}}, {"id": "s2"', '}}}, {"id": "s2"', 1)
ok(j2_design.parse_directions(broken_json, j2.check_style, llm.extract_json)[0] is not None, "an over-closed brace (a real reply's habit) is repaired")
html = j2_design.preview_html(dirs[0], physio, j2.style_css(dirs[0]["guide"]))
ok("<h1>Still Water Physio</h1>" in html and 'class="j2-btn"' in html and "Book an appointment" in html and "<svg" in html,
   "the preview has a hero with the business name, the main action as the button and drawn visuals")

# 4. a run: facts, proposal, the style decision, the pick, the build with the chosen guide, R-8
asked, real_ask = [], llm.ask


def spy(system, user, mock, **kw):
    asked.append((system, user, kw))
    return real_ask(system, user, mock, **kw)


llm.ask = spy
try:
    run = j2.J2Run()
    run.user_says(BRIEF)
    wait(run)
    d = until(run, "proposal")
    ok(d and d["kind"] == "proposal", "the proposal comes first")
    est_with = d["proposal"]["estimate"]
    ok(run._design_due() and est_with >= run._design_share(), "the estimate includes the design research share")
    run.decide(d["id"], "approve")
    wait(run)
    d = run.legacy_decision()
    ok(d and d["kind"] == "style" and len(d["options"]) == 3 and not j2.J2Run.decision_problems(d),
       "after approve: a style decision in the standard format")
    ok([o["id"] for o in d["options"]] == ["s1", "s2", "s3"] and sum(o["suggested"] for o in d["options"]) == 1
       and all(o["preview_url"] == f"/design/preview-{i}.html" and o["inspired_by"]["url"] for i, o in enumerate(d["options"], 1)),
       "options carry preview_url and inspired_by; one suggested")
    for i in (1, 2, 3):
        p = os.path.join(run.dir, "design", f"preview-{i}.html")
        ok(os.path.exists(p) and "j2-btn" in open(p, encoding="utf-8").read(), f"preview {i} is rendered in the run folder")
    text = open(os.path.join(run.dir, "research.md"), encoding="utf-8").read()
    ok("## R-design" in text and len(j2.research_sources(j2.research_entries(text)["R-design"])) >= 3,
       "R-design is in research.md with its sources")
    ok(run.design and len(run.design["directions"]) == 3 and os.path.exists(os.path.join(run.dir, "design.json")), "design.json is saved")
    v2 = run.v2_snapshot()
    ok(v2["decision"]["kind"] == "style" and v2["decision"]["options"][0]["preview_url"] and v2["status"] == "needs_you",
       "the v2 state carries the style decision with previews")
    ok(any(s and "design-research.md" not in s and "Design research" in s for s, _, _ in asked), "the research call used its prompt file")
    research_calls = [(s, u, kw) for s, u, kw in asked if "THE PROBLEM (from the brief)" in u]
    ok(research_calls and research_calls[0][2].get("tools") == ["web", "github"] and research_calls[0][2].get("max_budget_usd") == j2.DESIGN_BUDGET_USD,
       "the research call has the tools and the spend cap")
    ok(any("Write exactly 3 distinct broad style directions" in u for _, u, _ in asked), "the directions call ran")
    rec = [m for m in v2["chat"] if m.get("kind") == "record"]
    ok(any(m["title"] == "Plan approved" and m["answer"] == "Approved" and m["detail"] for m in rec), "the approved plan is a record in the chat")
    ok(any(m["title"] == "Facts added" for m in rec), "the answered facts are a record in the chat")
    chat = v2["chat"]
    i = next(i for i, m in enumerate(chat) if m.get("kind") == "record" and m["title"] == "Plan approved")
    ok(chat[i + 1]["from"] == "you" and chat[i + 1]["text"] == "Approved", "the user's bubble reads Approved after the record")
    before = len(asked)
    run.decide(d["id"], "s1")
    wait(run)
    # feedback 3: four quick design cards follow the look, each built by code from the chosen guide
    topics, picks = [], {"fonts": "modern", "palette": "deeper", "layout": "airy", "imagery": "icons"}
    for _ in range(4):
        dd = run.legacy_decision()
        ok(dd and dd["kind"] == "design" and not j2.J2Run.decision_problems(dd) and dd["step"]["of"] == 4
           and sum(o["suggested"] for o in dd["options"]) == 1 and all(o.get("sample") for o in dd["options"]),
           f"design card {len(topics) + 1}: standard format, one suggested, a visual sample per option")
        topics.append(dd["topic"])
        sv = run.v2_snapshot()["decision"]
        ok(sv["kind"] == "design" and sv["topic"] == dd["topic"] and sv["options"][0]["sample"], "the v2 state carries the design card")
        if dd["topic"] == "fonts":
            ok(dd["options"][0]["sample"]["heading"] == run.chosen_style["fonts"]["heading"], "fonts: the look's own pairing is the first option")
        if dd["topic"] == "palette":
            ok(all(j2_design.contrast(o["sample"]["palette"]["primary"], "#ffffff") >= 4.5 for o in dd["options"]),
               "palette: every option keeps readable button text")
        if dd["topic"] == "imagery":
            ok([o["label"] for o in dd["options"]] == ["Drawn illustrations", "Icons only", "Photo-style placeholders", "Minimal shapes"],
               "imagery: illustrations, icons, photo-style placeholders, minimal shapes")
        okd, why = run.decide(dd["id"], picks[dd["topic"]])
        ok(okd, f"picked {picks[dd['topic']]}: {why}")
        wait(run)
    ok(topics == ["fonts", "palette", "layout", "imagery"], f"the four cards in order: {topics}")
    ok(run.outcome and run.outcome.startswith("Done"), f"the run ends done: {run.outcome}")
    ok(run.style and run.style.get("direction") == "Calm and airy" and run.design["chosen"] == "s1", "the picked direction is the style guide")
    ok(run.style["owner_choices"] == {"fonts": "Modern sans", "palette": "Deeper tones", "layout": "Airy single column",
                                      "imagery": "Icons only"} and run.style["layout"]["pattern"] == "single-column"
       and run.style["imagery"]["approach"] == "icons" and run.style["fonts"]["heading"].startswith("'Avenir Next'"),
       "the design picks refine the style guide builders follow")
    saved = json.load(open(os.path.join(run.dir, "style.json")))
    ok(saved["kind"] == "site" and saved["chosen"] and saved["direction"] == "Calm and airy", "style.json records the chosen look")
    ok(run.sections.get("style") and run.style["palette"]["primary"] in run.sections["style"]["head"], "the style section's head is the chosen guide's CSS")
    ok(not any("STYLE GUIDE STEP" in u for _, u, _ in asked[before:]), "no builder wrote a style guide: the pick replaced that step")
    builds = [u for _, u, _ in asked[before:] if "YOU OWN SECTION" in u]
    ok(builds and all("research.md#R-design" in u and "THE BAR" in u for u in builds), "every site builder gets R-design and the bar")
    ok(all("Calm and airy" in u or run.style["palette"]["primary"] in u for u in builds), "every site builder gets the chosen guide")
    a = run.audits[-1]
    r8 = next(r for r in a["rubric"] if r["id"] == "R-8")
    ok(r8["verdict"] == "PASS" and r8["note"].startswith("Mock:") and a["all_pass"], "R-8 is judged by code's quality judge (pass)")
    ok(any(m.get("style_step") and "look you picked" in m["text"] for m in run.chat), "the backstage says the style is the picked look")
    v2 = run.v2_snapshot()
    ok(any(m.get("kind") == "record" and m["title"] == "Look: Calm and airy" for m in v2["chat"]), "the picked look is a record in the chat")
    ok(any(m.get("kind") == "record" and m["title"] == "Fonts: Modern sans" for m in v2["chat"])
       and any(m.get("kind") == "record" and m["title"] == "Imagery: Icons only" for m in v2["chat"]), "each design pick is a record in the chat")
    ok(all(not j2_v2.CODES.search(m.get("text") or m.get("title", "") + m.get("summary", "")) for m in v2["chat"]), "chat lines and records read plain")
    saved_v2 = j2_v2.saved(os.path.basename(run.dir), 0, 0)
    ok(any(m.get("kind") == "record" and m["title"] == "Plan approved" for m in saved_v2["chat"]), "a saved run shows the records too")
finally:
    llm.ask = real_ask

# 5. no_questions: the suggested look is taken without asking and logged backstage
run2 = j2.J2Run()
run2.set_no_questions(True)
run2.user_says(BRIEF)
wait(run2)
ok(run2.legacy_decision() is None, "Decide for me: no proposal, look or design question was asked")
ok(run2.design and run2.design["chosen"] == "s2" and run2.chosen_style["direction"] == "Warm and friendly",
   "the suggested direction was picked")
ok(any(e["type"] == "auto_decision" and "Pick a look" in e["detail"] for e in run2.events)
   and any(m.get("auto_decision") and "Warm and friendly" in m["text"] for m in run2.chat), "the auto-pick is logged backstage")
ok(not any(m.get("pause") for m in run2.chat) and sum(1 for e in run2.events if e["type"] == "auto_decision" and
   any(w in e["detail"] for w in ("fonts", "colours", "laid out", "pictures"))) == 4,
   "Decide for me: the four design questions are taken with the suggested picks and logged")
ok(len(run2.style.get("owner_choices") or {}) == 4, "Decide for me: the suggested picks refine the guide")
ok(run2.outcome and run2.outcome.startswith("Done") and run2.style["direction"] == "Warm and friendly", "the run builds with it")

# 6. the quality judge on its own, and the fail path
run3 = j2.J2Run()
run3.goal = j2.mock_charter(BRIEF)
q = run3._quality_judge("<html><body><h1>x</h1></body></html>", None)
ok(q["pass"] is True and q["evidence"].startswith("Mock:"), "the quality judge runs (mock passes)")
os.environ["J2_FORCE_QUALITY_FAIL"] = "1"
try:
    q = run3._quality_judge("<html><body><h1>x</h1></body></html>", None)
    ok(q["pass"] is False, "J2_FORCE_QUALITY_FAIL=1 fails it")
    rub = run3._audit_rubric([{"id": rid, "verdict": "PASS", "evidence": "fine"} for rid, _ in j2.RUBRIC], {})
    row = next(r for r in rub if r["id"] == "R-8")
    row.update(verdict="NEEDS_REVISION", note=q["evidence"], **{"pass": False})     # what _turn_audit does with the judge's verdict
    ok(not all(r["pass"] for r in rub), "a failing R-8 blocks all_pass like any rubric item")
finally:
    os.environ.pop("J2_FORCE_QUALITY_FAIL", None)
ok(dict(j2.RUBRIC)["R-8"].startswith("Complete and polished") and j2.OUTPUTS["website"]["rubric"] is j2.RUBRIC, "R-8 is in the website rubric")
ok(any("quality judge" in ln.lower() for ln in open(os.path.join(j2.J2_DIR, "quality-judge.md"), encoding="utf-8").read().splitlines()),
   "the quality judge has its prompt file")
ok("THE BAR" in open(os.path.join(j2.J2_DIR, "builder.md"), encoding="utf-8").read().upper()
   and "inline SVG" in open(os.path.join(j2.J2_DIR, "builder.md"), encoding="utf-8").read(), "builder.md states the bar")

# 7. J2_DESIGN=0: no research, no style choice
old = j2.DESIGN_ON
j2.DESIGN_ON = False
try:
    run4 = j2.J2Run()
    run4.user_says(BRIEF)
    wait(run4)
    d = until(run4, "proposal")
    run4.decide(d["id"], "approve")
    wait(run4)
    ok((run4.legacy_decision() or {}).get("kind") != "style" and run4.design is None, "J2_DESIGN=0: straight to building")
finally:
    j2.DESIGN_ON = old

# Phone overflow (a live page overflowed 126px at 390px and three fixes went to the hero): the guide's CSS carries the
# phone-safe defaults, the overflow evidence names the element and its section, and the page is assembled by role.
css = j2.style_css(j2.MOCK_STYLE)
ok("min-width:0" in css and "section *,header *,footer *,nav *,main *{max-width:100%}" in css and "overflow-wrap:anywhere" in css,
   "style guide CSS carries the phone-safe defaults")
mech = {"available": True, "phone": {"width": 360, "overflow_px": 156,
                                      "wide": [{"el": "div.j2-hours-content", "section": "#hours", "width": 492, "right": 516}]},
        "desktop": {"width": 1280, "overflow_px": 0}}
passed, why = j2._no_overflow({}, "<html></html>", mech)
ok(not passed and "div.j2-hours-content in #hours is 492px wide" in why and "owns #hours" in why,
   "overflow evidence names the element, its section and the owner to fix")
secs = {"W-4": {"owner": "W-4", "body": '<section id="home">h</section>'}, "W-7": {"owner": "W-7", "body": '<footer>f</footer>'},
        "W-8": {"owner": "W-8", "body": '<nav id="nav">n</nav>'}, "W-6": {"owner": "W-6", "body": '<section id="hours">x</section>'}}
order = re.findall(r"J2:(W-\d) start", j2.assemble("t", secs))
ok(order == ["W-8", "W-4", "W-6", "W-7"], f"page assembled by role: nav first, footer last ({order})")

print(f"design_test: {len(checks)} checks passed")
