"""Step 11: problem-based design research and the style choice for website runs.

Pure helpers, no run state (j2.py's J2Run calls them):
- research_prompt(charter): the research question derived from the charter (business type, visitors, their key
  actions), never a fixed keyword list; parse_research(raw) checks the R-design entry it gets back.
- directions_prompt(...) / parse_directions(raw, check): three distinct style directions, each a complete style
  guide (palette, fonts, spacing, motion, imagery approach, layout pattern) plus an "inspired by" source.
- preview_html(direction, charter, head): the tiny page (hero, one section, a button) code renders per direction.
- mock_research(charter) / mock_directions(): deterministic fixtures for mock mode.
"""
import html
import json
import re

DESIGN_ID = "R-design"                 # the entry id in research.md
MIN_SOURCES = 3                        # distinct URLs the entry must cite
MAX_QUERIES = 3                        # gh / web searches the research call may run (bounded by prompt and budget)
MAX_FETCHES = 3                        # page fetches the research call may run
N_DIRECTIONS = 3
IMAGERY = ("illustration", "photo-free", "icons", "pattern", "gradient", "mixed", "photo-placeholders", "shapes")
LAYOUTS = ("single-column", "split-hero", "grid-cards", "editorial", "full-bleed", "alternating")

RESEARCH_HEAD = re.compile(r"(?m)^##\s+R-design\b.*$")
URL = re.compile(r"https?://[^\s)>\]\"']+")


def _actions(charter):
    """The visitors' key actions, read from the charter's done-when items (book, order, call, browse...)."""
    verbs = {"book": "book an appointment", "appointment": "book an appointment", "whatsapp": "message on WhatsApp",
             "order": "place an order", "menu": "browse the menu", "price": "compare prices", "call": "call",
             "phone": "call", "hour": "check opening hours", "open": "check opening hours", "map": "find the place",
             "address": "find the place", "contact": "get in touch", "form": "send a request", "sign": "sign up",
             "subscribe": "subscribe", "download": "download", "buy": "buy", "cart": "buy", "service": "browse services"}
    found = []
    for item in (charter or {}).get("done_when") or []:
        low = str(item).lower()
        for k, v in verbs.items():
            if k in low and v not in found:
                found.append(v)
    # the main action first (what the site is for), then the rest in the charter's order
    first = ("book an appointment", "place an order", "buy", "message on WhatsApp", "send a request", "sign up",
             "subscribe", "download", "call", "get in touch")
    found.sort(key=lambda v: first.index(v) if v in first else len(first))
    return found[:6] or ["read about the business and get in touch"]


def problem(charter):
    """{business, visitors, actions, name, place}: the problem the research starts from, all from the charter."""
    g = charter or {}
    return {"business": str(g.get("business_type") or g.get("statement") or "a small local business").strip(),
            "name": str(g.get("site_name") or "").strip(),
            "visitors": str(g.get("audience") or "local visitors on their phones").strip(),
            "actions": _actions(g),
            "rules": [str(x) for x in (g.get("rules") or [])][:5]}


def research_prompt(charter):
    """The user prompt for the design research call. Every search term comes from the charter."""
    p = problem(charter)
    return (f"THE PROBLEM (from the brief):\n- Business: {p['business']}" + (f" ({p['name']})" if p["name"] else "")
            + f"\n- Visitors: {p['visitors']}\n- What visitors need to do: {', '.join(p['actions'])}\n"
            + (f"- Rules from the brief: {'; '.join(p['rules'])}\n" if p["rules"] else "")
            + f"\nDerive your searches from this problem: this kind of business, these visitors and these actions. "
              f"Run at most {MAX_QUERIES} searches in total (`gh search repos <terms> --sort stars --limit 5` for "
              f"landing-page or site templates for this kind of business, or a web search for curated design "
              f"example lists and live sites) and fetch at most {MAX_FETCHES} pages. Stop as soon as you have "
              f"{MIN_SOURCES} strong, relevant examples. Then write the entry {DESIGN_ID} in the format given.")


def parse_research(raw):
    """(entry text, None) from the reply's <<<FILE ... FILE>>> block (or its whole text), or (None, why). The entry
    needs the R-design heading, at least MIN_SOURCES distinct URLs, Findings and Patterns."""
    text = str(raw or "")
    m = re.search(r"^<<<FILE[ \t]*\n(.*?)\n?^FILE>>>", text, re.S | re.M)
    body = (m.group(1) if m else text).strip()
    if not body:
        return None, "the reply is empty"
    if not RESEARCH_HEAD.search(body):
        body = f"## {DESIGN_ID}: what makes a strong site for this kind of business\n\n{body}"
    body = body[RESEARCH_HEAD.search(body).start():]
    urls = list(dict.fromkeys(URL.findall(body)))
    if len(urls) < MIN_SOURCES:
        return None, f"the entry cites {len(urls)} source URL(s); it needs at least {MIN_SOURCES} distinct sources"
    for need in ("Findings", "Patterns"):
        if not re.search(rf"\*\*{need}", body, re.I) and not re.search(rf"(?m)^#+\s*{need}", body, re.I):
            return None, f"the entry has no **{need}:** part"
    return body.strip() + "\n", None


def patterns(entry):
    """The **Patterns:** part of the entry (what builders follow), or the whole entry when it has no such part."""
    m = re.search(r"\*\*Patterns:?\*\*:?\s*(.*?)(?=\n\*\*[A-Z]|\Z)", entry or "", re.S)
    return (m.group(1).strip() if m else str(entry or "").strip())


def sources(entry):
    return list(dict.fromkeys(URL.findall(entry or "")))


def mock_research(charter):
    """A deterministic fixture entry (mock mode): the same shape a real entry has."""
    p = problem(charter)
    acts = ", ".join(p["actions"])
    return (f"## {DESIGN_ID}: what makes a strong site for {p['business']}\n\n"
            f"**Question:** What do the best sites for {p['business']} do, for visitors who want to {acts}?\n\n"
            "**Sources:**\n- https://github.com/example/local-business-landing (mock, 1,200 stars)\n"
            "- https://example.com/design-gallery/small-business-sites (mock)\n"
            "- https://example.org/live-site-of-this-kind (mock)\n\n"
            "**Findings:**\n- The hero states the business, the place and the one main action in the first screen "
            "(github.com/example/local-business-landing).\n- Prices, hours and the address sit in their own clear "
            "sections with real numbers, never behind a click (example.com/design-gallery).\n- One accent colour, one "
            "display font, generous spacing and small inline icons do most of the visual work (example.org).\n\n"
            "**Patterns:**\n- Section order: hero with the main action, what is offered (with prices), proof or detail, "
            "hours and place, a closing call to action.\n- Layout: a split hero, then cards in a 2 or 3 column grid "
            "that stacks on phones.\n- Typography: one display face for headings, a plain readable body face, large "
            "line height.\n- Imagery: inline SVG icons and soft gradient shapes drawn in code; no stock photos.\n"
            "- Motion: a short fade-up as sections scroll in, a gentle hover lift on cards and buttons.\n"
            "- Calls to action: one primary button repeated in the hero and at the end, a secondary one for the "
            "second action.\n\n**What changes in the plan:** Every builder follows these patterns; the style "
            "directions are drawn from them.\n")


def directions_prompt(charter, entry, style_fmt):
    """The user prompt for the three style directions."""
    p = problem(charter)
    return (f"THE PROBLEM: {p['business']}" + (f" ({p['name']})" if p["name"] else "") + f"; visitors: {p['visitors']}; "
            f"they need to {', '.join(p['actions'])}.\n\nDESIGN RESEARCH ({DESIGN_ID}, cited sources):\n{entry}\n\n"
            f"Write exactly {N_DIRECTIONS} distinct broad style directions for this site, drawn from the research. "
            "Each is a complete style guide a builder can follow without asking anything, plus the one source that "
            "inspired it (one of the research's sources, or another real site you can name with its URL).\n"
            "Reply with one JSON object: {\"directions\": [{\"name\": str (2 to 4 words, e.g. \"Calm and airy\"), "
            "\"line\": str (one plain sentence: what it feels like and who it suits, under 120 characters), "
            "\"suggested\": bool (exactly one true: the best fit for this business), \"inspired_by\": {\"label\": "
            "str (the site or repo name), \"url\": str (its URL)}, \"guide\": " + style_fmt.rstrip()[:-1] + ", "
            f"\"imagery\": {{\"approach\": one of {list(IMAGERY)}, \"notes\": str (one line: what is drawn in code, "
            f"e.g. inline SVG icons, gradient shapes)}}, \"layout\": {{\"pattern\": one of {list(LAYOUTS)}, \"notes\": "
            "str (one line: how sections and the hero are arranged)}}}}]}. imagery and layout sit INSIDE guide, as "
            "its last two keys. Valid JSON only: no comments, no trailing commas, double quotes only inside CSS "
            "values are forbidden (use single quotes for font names). The three must differ clearly in palette, type "
            "and mood; all must meet WCAG AA contrast with buttons at least 44px tall.")


def _lum(hex6):
    h = hex6.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    """WCAG contrast ratio between two hex colours."""
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _darken(hex6, k):
    h = hex6.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    return "#" + "".join(f"{int(int(h[i:i + 2], 16) * (1 - k)):02x}" for i in (0, 2, 4))


def ensure_contrast(guide, ratio=4.5):
    """Readable contrast by code (WCAG AA): white text on the primary (buttons), and the text colour on the
    background and surface. A colour that falls short is darkened step by step; every CSS string in the guide that
    named the old hex (buttons, card) is updated. Returns the changes made, as plain lines."""
    pal, notes = guide.get("palette") or {}, []

    def fix(key, against, label):
        old = str(pal.get(key) or "")
        if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}){1,2}", old):
            return
        new = old
        for _ in range(12):
            if all(contrast(new, x) >= ratio for x in against):
                break
            new = _darken(new, 0.08)
        if new != old:
            pal[key] = new
            for k in ("buttons", "card"):
                v = guide.get(k)
                if isinstance(v, dict):
                    guide[k] = {kk: str(vv).replace(old, new) for kk, vv in v.items()}
                elif isinstance(v, str):
                    guide[k] = v.replace(old, new)
            notes.append(f"{label} {old} -> {new} for {ratio}:1 contrast")

    fix("primary", ["#ffffff"], "primary")
    fix("text", [c for c in (pal.get("background"), pal.get("surface")) if c], "text")
    fix("muted", [c for c in (pal.get("background"), pal.get("surface")) if c], "muted")
    return notes


def repair_json(text):
    """The JSON object in `text` (code fences and prose around it stripped) with mismatched brackets dropped and
    unclosed ones closed: a model that writes `}}}, {` where the array continues has closed one object too many.
    String contents are left alone."""
    m = re.search(r"```(?:json)?\s*(\{.*)", text, re.S)
    body = (m.group(1) if m else text)
    body = body[body.find("{"):]
    out, stack, in_str, esc = [], [], False, False
    for ch in body:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            want = "{" if ch == "}" else "["
            if not stack or stack[-1] != want:
                continue            # a bracket that closes nothing (or the wrong thing): dropped
            stack.pop()
            if not stack:
                out.append(ch)
                break
        out.append(ch)
    out.append("".join("}" if b == "{" else "]" for b in reversed(stack)))
    return "".join(out)


def parse_directions(raw, check, extract_json):
    """([direction, ...], None) or (None, why). check(guide) returns the cleaned guide or raises ValueError (j2's
    style validation); extract_json is llm.extract_json."""
    try:
        data = extract_json(str(raw or ""))
    except ValueError:
        try:        # a real reply often over-closes a brace after the guide: drop mismatched brackets and try again
            data = json.loads(repair_json(str(raw or "")))
        except ValueError:
            return None, "the reply isn't JSON"
    rows = (data or {}).get("directions") if isinstance(data, dict) else data
    if not isinstance(rows, list) or len(rows) < N_DIRECTIONS:
        return None, f"the reply needs {N_DIRECTIONS} directions"
    out, names = [], set()
    for i, r in enumerate(rows[:N_DIRECTIONS], 1):
        if not isinstance(r, dict) or not isinstance(r.get("guide"), dict):
            return None, f"direction {i} has no guide object"
        name = re.sub(r"\s+", " ", str(r.get("name") or "")).strip()[:40]
        if not name or name.lower() in names:
            return None, f"direction {i} needs its own name"
        names.add(name.lower())
        try:
            guide = check(r["guide"])
        except ValueError as e:
            return None, f"direction {i} ({name}): {e}"
        fixed = ensure_contrast(guide)          # WCAG AA by code: buttons' white text, body text on its backgrounds
        if fixed:
            guide["notes"] = (str(guide.get("notes") or "") + " (code darkened: " + "; ".join(fixed) + ")").strip()
        img = next((x for x in (r["guide"].get("imagery"), r.get("imagery")) if isinstance(x, dict)), {})
        lay = next((x for x in (r["guide"].get("layout"), r.get("layout")) if isinstance(x, dict)), {})
        guide["imagery"] = {"approach": img.get("approach") if img.get("approach") in IMAGERY else "illustration",
                            "notes": str(img.get("notes") or "Inline SVG icons and soft shapes drawn in code.")[:200]}
        guide["layout"] = {"pattern": lay.get("pattern") if lay.get("pattern") in LAYOUTS else "split-hero",
                           "notes": str(lay.get("notes") or "A split hero, then stacked sections with cards.")[:200]}
        ins = r.get("inspired_by") if isinstance(r.get("inspired_by"), dict) else {}
        url = str(ins.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            url = ""
        out.append({"id": f"s{i}", "name": name, "line": str(r.get("line") or "").strip()[:160],
                    "suggested": bool(r.get("suggested")), "guide": guide,
                    "inspired_by": {"label": str(ins.get("label") or url or "a site of this kind").strip()[:60],
                                    "url": url}})
    if sum(d["suggested"] for d in out) != 1:
        for d in out:
            d["suggested"] = d is out[0]
    return out, None


def _guide(primary, secondary, accent, background, surface, text, muted, heading, body, gurl, radius, section,
           entrance, imagery, layout, notes):
    return {"palette": {"primary": primary, "secondary": secondary, "accent": accent, "background": background,
                        "surface": surface, "text": text, "muted": muted},
            "fonts": {"heading": heading, "body": body, "google_fonts_url": gurl},
            "spacing": {"unit": "8px", "section": section}, "radius": radius,
            "buttons": {"primary": f"background:{primary};color:#fff;padding:14px 24px;border-radius:{radius};"
                                   "min-height:44px;font-weight:600;border:0;text-decoration:none",
                        "secondary": f"background:{secondary};color:{text};padding:14px 24px;border-radius:{radius};"
                                     "min-height:44px;font-weight:600;border:0;text-decoration:none"},
            "card": f"background:{surface};border-radius:{radius};padding:24px;box-shadow:0 1px 2px rgba(0,0,0,.06)",
            "motion": {"entrance": entrance, "duration": "260ms", "easing": "cubic-bezier(.2,.7,.2,1)",
                       "hover": "transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.08)", "scroll": "smooth",
                       "reduced_motion": "No movement: sections appear at once and nothing slides."},
            "imagery": imagery, "layout": layout, "notes": notes}


def mock_directions():
    """Three deterministic directions (mock mode), the second suggested."""
    return [
        {"id": "s1", "name": "Calm and airy", "line": "Light, spacious and quiet; suits a place people visit to feel "
         "better.", "suggested": False,
         "inspired_by": {"label": "example/local-business-landing", "url": "https://github.com/example/local-business-landing"},
         "guide": _guide("#2f6f8f", "#e6eef3", "#c8742c", "#fbfcfd", "#f1f5f8", "#1c2a33", "#5a6b76",
                         "Georgia, 'Times New Roman', serif", "system-ui, -apple-system, 'Segoe UI', sans-serif", None,
                         "14px", "88px", "fade-up", {"approach": "illustration", "notes": "Soft gradient blobs and thin-line "
                         "SVG icons drawn in code."}, {"pattern": "split-hero", "notes": "Text left, a drawn illustration "
                         "right; sections stack with wide spacing."}, "Calm, readable, unhurried (mock)")},
        {"id": "s2", "name": "Warm and friendly", "line": "Warm tones and rounded shapes; feels like being welcomed in.",
         "suggested": True,
         "inspired_by": {"label": "Small business design gallery", "url": "https://example.com/design-gallery/small-business-sites"},
         "guide": _guide("#b5522a", "#f6e7dc", "#2a6f5f", "#fffaf5", "#fdf1e8", "#2b1d16", "#6e5a4f",
                         "'Trebuchet MS', 'Segoe UI', sans-serif", "system-ui, -apple-system, 'Segoe UI', sans-serif", None,
                         "18px", "80px", "fade-up", {"approach": "pattern", "notes": "A repeating dot pattern and filled "
                         "SVG icons with rounded corners, drawn in code."}, {"pattern": "grid-cards", "notes": "A centred "
                         "hero, then 3-column cards that stack on phones."}, "Warm, rounded, welcoming (mock)")},
        {"id": "s3", "name": "Clean and clinical", "line": "Crisp, precise and trustworthy; suits a professional practice.",
         "suggested": False,
         "inspired_by": {"label": "Live site of this kind", "url": "https://example.org/live-site-of-this-kind"},
         "guide": _guide("#1b4f72", "#eaf0f5", "#1f8a70", "#ffffff", "#f4f7fa", "#13232f", "#4f6372",
                         "system-ui, -apple-system, 'Segoe UI', sans-serif", "system-ui, -apple-system, 'Segoe UI', sans-serif",
                         None, "6px", "72px", "fade", {"approach": "icons", "notes": "Sharp two-tone SVG icons and thin "
                         "rules; no decorative shapes."}, {"pattern": "single-column", "notes": "A narrow single column "
                         "with a strong top bar and clear numbered sections."}, "Clean, exact, professional (mock)")},
    ]


def preview_html(direction, charter, head):
    """The tiny preview page for one direction: a hero, one section (three cards) and a button, in the guide's CSS
    (head is j2.style_css(guide)). Served from the run folder; shown inside the style decision card."""
    p = problem(charter)
    g = direction["guide"]
    name = html.escape(p["name"] or "Your business")
    act = html.escape(p["actions"][0].capitalize() if p["actions"] else "Get in touch")
    line = html.escape(direction.get("line") or "")
    pal = g["palette"]
    cards = "".join(f'<div class="j2-card j2-hover"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" '
                    f'stroke="{pal["primary"]}" stroke-width="1.8" aria-hidden="true">{icon}</svg><h3>{t}</h3>'
                    f'<p>{d}</p></div>'
                    for icon, t, d in (('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', "Hours",
                                        "Open six days a week, early to late."),
                                       ('<path d="M4 7h16v10H4z"/><path d="M4 11h16"/>', "Prices",
                                        "Clear prices for every service."),
                                       ('<path d="M12 21s-6-5.5-6-10a6 6 0 1 1 12 0c0 4.5-6 10-6 10z"/><circle cx="12" '
                                        'cy="11" r="2"/>', "Find us", "Easy to reach, easy to find.")))
    bleed = (f'<svg class="blob" viewBox="0 0 400 300" aria-hidden="true"><defs><linearGradient id="g" x1="0" y1="0" '
             f'x2="1" y2="1"><stop offset="0" stop-color="{pal["primary"]}" stop-opacity=".35"/><stop offset="1" '
             f'stop-color="{pal.get("accent", pal["primary"])}" stop-opacity=".25"/></linearGradient></defs>'
             '<path fill="url(#g)" d="M310 40c50 40 70 120 30 180s-130 80-200 50S20 150 60 90 230 0 310 40z"/></svg>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>{name}: {html.escape(direction["name"])}</title>{head}<style>'
            '.wrap{max-width:960px;margin:0 auto;padding:0 20px}.hero{display:grid;grid-template-columns:1.2fr 1fr;'
            'gap:24px;align-items:center;padding:48px 0 32px;position:relative}.hero h1{font-size:clamp(28px,4.5vw,'
            '44px);line-height:1.1;margin:0 0 12px}.hero p{color:var(--j2-muted,inherit);margin:0 0 20px;font-size:17px}'
            '.blob{width:100%;height:auto;max-height:220px}.cards{display:grid;grid-template-columns:repeat(3,1fr);'
            'gap:16px;padding:0 0 48px}.cards h3{margin:12px 0 6px;font-size:17px}.cards p{margin:0;color:var(--j2-muted,'
            'inherit);font-size:14px}.kicker{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var('
            '--j2-accent,var(--j2-primary));font-weight:600;margin:0 0 8px}@media (max-width:640px){.hero,.cards{'
            'grid-template-columns:1fr}.hero{padding:32px 0 24px}}</style></head><body>'
            f'<main class="wrap"><section class="hero j2-reveal"><div><p class="kicker">{html.escape(direction["name"])}'
            f'</p><h1>{name}</h1><p>{line}</p><a class="j2-btn" href="#">{act}</a></div>{bleed}</section>'
            f'<section class="cards j2-reveal">{cards}</section></main></body></html>')


# ---- the owner's design questions after the look (feedback 3): fonts, colours, layout, imagery. Code builds every
# option from the chosen direction's guide (no model call); one click each; the pick refines the guide builders follow.
REFINE_TOPICS = ("fonts", "palette", "layout", "imagery")
TOPIC_WORD = {"fonts": "Fonts", "palette": "Colours", "layout": "Layout", "imagery": "Imagery"}
FONT_PAIRS = (
    ("classic", "Classic serif", "Georgia, 'Times New Roman', serif", "system-ui, -apple-system, 'Segoe UI', sans-serif",
     "Serif headings with clean text: calm and trusted."),
    ("modern", "Modern sans", "'Avenir Next', 'Helvetica Neue', Arial, sans-serif",
     "system-ui, -apple-system, 'Segoe UI', sans-serif", "One clean sans throughout: crisp and current."),
    ("friendly", "Friendly rounded", "'Trebuchet MS', 'Segoe UI', sans-serif", "Verdana, 'Segoe UI', sans-serif",
     "Soft, open letters: warm and easy to approach."),
    ("editorial", "Editorial", "'Palatino Linotype', Palatino, 'Book Antiqua', serif", "Georgia, 'Times New Roman', serif",
     "A bookish serif throughout: considered and elegant."),
)
LAYOUT_CHOICES = (
    ("airy", "Airy single column", "single-column",
     "One calm column with wide spacing; easy to read on any screen.",
     "One centred column (max 760px of text) with generous vertical spacing; sections stack, cards in a single column or two."),
    ("two-column", "Two columns", "split-hero",
     "Text beside a visual, then sections in balanced columns.",
     "A split hero (text left, visual right), then sections in two balanced columns that stack on phones."),
    ("bold", "Bold full-bleed", "full-bleed",
     "Wide colour bands edge to edge; strong and confident.",
     "Full-width colour bands that alternate background and surface, with big headings; the content stays in the shared column."),
)
IMAGERY_CHOICES = (
    ("illustration", "Drawn illustrations", "illustration",
     "Soft scenes and shapes drawn in code.", "Inline SVG illustrations and soft gradient shapes drawn in code."),
    ("icons", "Icons only", "icons", "Clean line icons beside the text; no pictures.",
     "Inline SVG line icons only, one per card or item; no illustrations or photo panels."),
    ("photo", "Photo-style placeholders", "photo-placeholders",
     "Framed photo-like panels, ready for your own photos later.",
     "Photo-style panels drawn in code (rounded frames with soft gradient fills and a short caption), sized like "
     "photos; never an external image."),
    ("shapes", "Minimal shapes", "shapes", "A few quiet shapes and lines; lots of space.",
     "A few simple geometric shapes and thin rules drawn in code; mostly white space."),
)


def _rgb(hex6):
    h = hex6.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _shift(hex6, dl=0.0, ds=0.0):
    """The colour with its lightness and saturation moved (HLS), as hex."""
    import colorsys
    h, l, s = colorsys.rgb_to_hls(*_rgb(hex6))
    return _hex(colorsys.hls_to_rgb(h, max(0.0, min(1.0, l + dl)), max(0.0, min(1.0, s + ds))))


def _mix(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def _family(css):
    return re.split(r"\s*,\s*", str(css or ""))[0].strip("'\" ").lower()


def font_options(guide):
    f = guide.get("fonts") or {}
    own = {"id": "own", "label": "The look's own fonts", "gets": "The pairing that came with your look.",
           "suggested": True, "sample": {"heading": f.get("heading"), "body": f.get("body"),
                                         "google_fonts_url": f.get("google_fonts_url")}}
    alts = [p for p in FONT_PAIRS if _family(p[2]) != _family(f.get("heading"))][:2]
    return [own] + [{"id": i, "label": label, "gets": gets, "suggested": False,
                     "sample": {"heading": hd, "body": bd, "google_fonts_url": None}} for i, label, hd, bd, gets in alts]


def palette_options(guide):
    pal = dict(guide.get("palette") or {})
    deeper = {**pal, "primary": _shift(pal["primary"], -0.10, 0.08),
              "background": _mix(pal.get("background", "#ffffff"), pal["primary"], 0.035),
              "surface": _mix(pal.get("surface", "#ffffff"), pal["primary"], 0.07)}
    accent = pal.get("accent") or _shift(pal["primary"], 0.1)
    lead = {**pal, "primary": accent, "accent": pal["primary"],
            "secondary": _mix("#ffffff", accent, 0.12)}
    out = []
    for i, label, gets, p in (("own", "The look's colours", "The palette that came with your look.", pal),
                              ("deeper", "Deeper tones", "Richer, darker colours with a tinted background.", deeper),
                              ("accent", "Accent leads", "The accent colour takes the lead on buttons and headings.", lead)):
        g = {"palette": dict(p), "buttons": {}, "card": ""}
        ensure_contrast(g)
        out.append({"id": i, "label": label, "gets": gets, "suggested": i == "own",
                    "sample": {"palette": g["palette"], "radius": guide.get("radius") or "12px"}})
    return out


def layout_options(guide):
    pat = (guide.get("layout") or {}).get("pattern")
    sug = "airy" if pat in ("single-column", "editorial") else "bold" if pat == "full-bleed" else "two-column"
    pal = guide.get("palette") or {}
    return [{"id": i, "label": label, "gets": gets, "suggested": i == sug,
             "sample": {"layout": i, "palette": pal}} for i, label, _, gets, _ in LAYOUT_CHOICES]


def imagery_options(guide):
    ap = (guide.get("imagery") or {}).get("approach")
    sug = {"icons": "icons", "photo-free": "icons", "pattern": "shapes", "gradient": "shapes", "shapes": "shapes",
           "photo-placeholders": "photo"}.get(ap, "illustration")
    pal = guide.get("palette") or {}
    return [{"id": i, "label": label, "gets": gets, "suggested": i == sug,
             "sample": {"imagery": i, "palette": pal}} for i, label, _, gets, _ in IMAGERY_CHOICES]


def design_questions(guide):
    """The four quick questions after the look, in order: [{topic, happening, why, options}], every option with a
    `sample` the page renders (live type, swatches, a wireframe, a small picture)."""
    out = []
    for topic, happening, fn in (("fonts", "Pick the fonts for your website.", font_options),
                                 ("palette", "Pick the colours.", palette_options),
                                 ("layout", "Pick how the page is laid out.", layout_options),
                                 ("imagery", "Pick the kind of pictures.", imagery_options)):
        opts = fn(guide)
        sug = next(o for o in opts if o["suggested"])
        out.append({"topic": topic, "happening": happening,
                    "why": f"Shown in your chosen look; we suggest {sug['label'][:1].lower() + sug['label'][1:]}.",
                    "options": opts})
    return out


def _recolour(guide, old, new):
    """Every CSS string in the guide (buttons, card) that named an old palette hex names the new one (all at once,
    so a swap doesn't undo itself)."""
    pairs = [(o, new[k]) for k, o in old.items() if k in new and str(o).lower() != str(new[k]).lower() and o]
    def sub(v):
        v = str(v)
        for n, (o, _) in enumerate(pairs):
            v = re.sub(re.escape(str(o)), f"@@{n}@@", v, flags=re.I)
        for n, (_, x) in enumerate(pairs):
            v = v.replace(f"@@{n}@@", x)
        return v
    for k in ("buttons", "card"):
        v = guide.get(k)
        if isinstance(v, dict):
            guide[k] = {kk: sub(vv) for kk, vv in v.items()}
        elif isinstance(v, str):
            guide[k] = sub(v)


def apply_choice(guide, topic, opt):
    """The owner's pick (an option from design_questions) written into the guide builders follow. Returns the guide."""
    s = opt.get("sample") or {}
    if topic == "fonts" and s.get("heading") and s.get("body"):
        guide["fonts"] = {"heading": s["heading"], "body": s["body"], "google_fonts_url": s.get("google_fonts_url")}
    elif topic == "palette" and s.get("palette"):
        old = dict(guide.get("palette") or {})
        guide["palette"] = dict(s["palette"])
        _recolour(guide, old, guide["palette"])
        ensure_contrast(guide)
    elif topic == "layout":
        row = next((r for r in LAYOUT_CHOICES if r[0] == opt["id"]), None)
        if row:
            guide["layout"] = {"pattern": row[2], "notes": row[4]}
    elif topic == "imagery":
        row = next((r for r in IMAGERY_CHOICES if r[0] == opt["id"]), None)
        if row:
            guide["imagery"] = {"approach": row[2], "notes": row[4]}
    guide.setdefault("owner_choices", {})[topic] = opt.get("label")
    return guide


def dump(directions):
    """design.json's shape: the directions without anything the page can't show."""
    return json.loads(json.dumps(directions))
