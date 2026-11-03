"""Mechanical check of a built site, run by code before Audit (audit.md: "Run mechanical checks first").

Renders the page in headless Chrome at phone (360px) and desktop (1280px) width and reports what code can
measure: JavaScript errors, horizontal overflow, in-page links that point nowhere, external resources and size.
Forms: in the phone frame each form is filled with sample values and submitted (navigation is blocked). A form
fails when it has no submit control, throws a JS error on submit, or never fires its submit event although every
field is valid. Sample values a field's own rules reject (e.g. a pattern) are reported, not counted as a failure.
Design measurements for Audit's rubric (design()): text contrast against its background (WCAG AA: 4.5, or 3 for
large text), tap targets under TAP_MIN px at phone width (inline links inside text are exempt), images without alt,
h1 count and skipped heading levels, fonts in use, nav and in-page links, styled actions on the first screen.
screenshot() renders both widths side by side into one PNG for Audit to look at.
Headless Chrome won't make a window narrower than 500px, so each width is an iframe inside a wrapper page.
It never judges content; Audit does that. If Chrome isn't found, it says so and Audit works from the code alone.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile

WIDTHS = {"phone": 360, "desktop": 1280}
TAP_MIN = int(os.getenv("J2_TAP_MIN", "44"))   # px; WCAG 2.5.5 (AAA) and the common phone guideline
CAPTURE = ("<script>window.__j2e=[];addEventListener('error',e=>__j2e.push(String(e.message||e)));"
           "addEventListener('unhandledrejection',e=>__j2e.push('Unhandled promise rejection: '+String(e.reason)));"
           "</script>")
WRAPPER = """<!doctype html><html><body>%s
<script>
const out = {}, frames = [...document.querySelectorAll('iframe')];
let left = frames.length;
const SAMPLE = {email:'test@example.com', tel:'5550100', number:'1', range:'1', date:'2030-01-15', time:'10:00',
  'datetime-local':'2030-01-15T10:00', month:'2030-01', week:'2030-W03', url:'https://example.com', color:'#336699'};
const TAP_MIN = %d;
function design(w, phone){
  const d = w.document, cs = el => w.getComputedStyle(el);
  const vis = el => { const r = el.getBoundingClientRect(), c = cs(el); return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none' && +c.opacity !== 0; };
  const rgb = c => (c.match(/[\d.]+/g) || []).map(Number);
  const rel = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = el => { for (; el && el.nodeType === 1; el = el.parentElement){ const c = cs(el);
      if (c.backgroundImage !== 'none') return null;          // text over an image or gradient: not measurable here
      const v = rgb(c.backgroundColor); if (v.length && (v.length < 4 || v[3] > 0.5)) return v.slice(0, 3); } return [255, 255, 255]; };
  const low = [], seen = new Set(); let checked = 0;
  const tw = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT);
  while (tw.nextNode() && checked < 400){ const el = tw.currentNode.parentElement;
    if (!tw.currentNode.textContent.trim() || !el || seen.has(el) || !vis(el)) continue; seen.add(el); checked++;
    const bg = bgOf(el); if (!bg) continue;
    const c = cs(el), a = rel(rgb(c.color)), b = rel(bg), ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const size = parseFloat(c.fontSize), need = size >= 24 || (+c.fontWeight >= 700 && size >= 18.66) ? 3 : 4.5;
    if (ratio < need) low.push(`"${tw.currentNode.textContent.trim().slice(0, 30)}" ${ratio.toFixed(2)}:1 (needs ${need}:1)`); }
  const lv = [...d.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(vis).map(h => +h.tagName[1]);
  const out = {contrast: {checked, low_count: low.length, low: low.slice(0, 6)},
    headings: {h1: d.querySelectorAll('h1').length, skipped_levels: lv.filter((x, i) => i && x > lv[i - 1] + 1).length},
    images_without_alt: [...d.querySelectorAll('img:not([alt])')].map(i => (i.getAttribute('src') || '').slice(0, 60)).slice(0, 6),
    images: d.querySelectorAll('img').length,
    fonts: [...new Set([...d.querySelectorAll('body *')].filter(vis).slice(0, 800).map(e => cs(e).fontFamily.split(',')[0].replace(/["']/g, '').trim()))].slice(0, 8),
    nav: {nav_elements: d.querySelectorAll('nav').length, in_page_links: d.querySelectorAll('a[href^="#"]').length},
    first_screen_actions: [...d.querySelectorAll('a[href],button')].filter(vis).filter(el => el.getBoundingClientRect().top < w.innerHeight)
      .filter(el => { const v = rgb(cs(el).backgroundColor); return v.length && (v.length < 4 || v[3] > 0); })
      .map(el => (el.textContent || '').trim().slice(0, 30)).slice(0, 8)};
  if (phone){
    const small = [...d.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,[role=button]')].filter(vis)
      .filter(el => !(el.tagName === 'A' && cs(el).display === 'inline' && el.closest('p,li,td,span')))   // links inside text are exempt
      .map(el => [el, el.getBoundingClientRect()]).filter(([, r]) => r.height < TAP_MIN || r.width < TAP_MIN);
    out.small_tap_targets = {min_px: TAP_MIN, count: small.length, examples: small.slice(0, 6).map(([el, r]) =>
      `${el.tagName.toLowerCase()} "${(el.textContent || el.value || el.name || '').trim().slice(0, 25)}" ${Math.round(r.width)}x${Math.round(r.height)}`)};
  }
  return out;
}
function testForms(w){
  return [...w.document.forms].map((f, i) => {
    const r = {index: i + 1, has_submit: !!f.querySelector('button:not([type=button]):not([type=reset]),input[type=submit],input[type=image]'),
               submitted: false, invalid: [], errors_during: []};
    for (const el of f.elements){
      const t = (el.type || '').toLowerCase();
      if (el.disabled || ['submit','button','reset','hidden','file','image','fieldset'].includes(t)) continue;
      if (el.tagName === 'SELECT'){ const o = [...el.options].find(o => o.value); if (o) el.value = o.value; }
      else if (t === 'checkbox' || t === 'radio') el.checked = true;
      else if (!el.value) el.value = SAMPLE[t] || 'Test';
    }
    const before = (w.__j2e || []).length;
    const stop = e => { if (e.target === f){ r.submitted = true; e.preventDefault(); } };
    w.addEventListener('submit', stop);   // bubble phase on window: runs after the page's own handlers
    try { f.requestSubmit(); } catch (e) { (w.__j2e = w.__j2e || []).push('Form submit: ' + String(e)); }
    w.removeEventListener('submit', stop);
    r.invalid = [...f.elements].filter(x => x.willValidate && !x.checkValidity()).map(x => x.name || x.id || x.type).slice(0, 5);
    r.before = before;
    return r;
  });
}
frames.forEach(f => f.addEventListener('load', () => setTimeout(() => {
  let w;
  try {
    w = f.contentWindow; const d = w.document.documentElement;
    out[f.dataset.name] = {width: w.innerWidth, scroll_width: d.scrollWidth, errors: w.__j2e || []};
    out[f.dataset.name].design = design(w, !!f.dataset.forms);
    if (f.dataset.forms) out[f.dataset.name].forms = testForms(w);
  } catch (e) { out[f.dataset.name] = {error: String(e)}; }
  setTimeout(() => {   // late errors from submit handlers
    try { const r = out[f.dataset.name]; (r.forms || []).forEach(x => { x.errors_during = (w.__j2e || []).slice(x.before); delete x.before; });
          r.errors = w.__j2e || r.errors; } catch (e) {}
    if (--left === 0) document.body.setAttribute('data-j2', JSON.stringify(out));
  }, 400);
}, 500)));
</script></body></html>"""


def run_chrome(cmd, timeout, text=True):
    """subprocess.run for headless Chrome, in its own process group. On a timeout the whole group is killed: subprocess.run
    kills only the main process, and the helpers it leaves hold the output pipes open, so a 90s timeout ran for 10+ minutes
    (and the helpers stayed behind).

    Each run also gets its own profile directory. Without one, every headless run shares the default profile with the
    browser the developer has open, and two of them can wait on the same profile lock until the timeout; a page that
    loaded in seconds on its own then hangs. A caller that passes --user-data-dir keeps it."""
    with tempfile.TemporaryDirectory(prefix="j2-chrome-") as profile:
        if not any(str(a).startswith("--user-data-dir") for a in cmd):
            cmd = list(cmd[:1]) + [f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"] + list(cmd[1:])
        return _chrome(cmd, timeout, text)


def _chrome(cmd, timeout, text=True):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg"):
            os.killpg(p.pid, signal.SIGKILL)
        else:      # Windows has no process groups: taskkill /T ends Chrome and the helpers it started
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        p.communicate()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def find_chrome():
    if os.getenv("J2_CHROME", "").lower() in ("none", "off", "0"):      # J2_CHROME=none: run as if Chrome is missing
        return None
    for p in (os.getenv("J2_CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if p and os.path.exists(p):
            return p
    return None


def static_checks(html):
    ids = set(re.findall(r'\bid\s*=\s*["\']?([^"\'\s>]+)', html))       # quoted or unquoted attribute
    anchors = set(re.findall(r'href\s*=\s*["\']?#([^"\'\s>]+)', html))
    return {"bytes": len(html.encode("utf-8")),
            "broken_in_page_links": sorted(a for a in anchors if a not in ids),
            "external_resources": sorted(set(re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)["\']', html))),
            "forms": len(re.findall(r"<form\b", html, re.I)), "scripts": len(re.findall(r"<script\b", html, re.I))}


def check(html):
    out = {"available": False, **static_checks(html)}
    chrome = find_chrome()
    if not chrome:
        out["note"] = "Chrome not found (set J2_CHROME); no render or script run."
        return out
    page = re.sub(r"(<head[^>]*>)", r"\1" + CAPTURE, html, count=1, flags=re.I)
    if page == html:
        page = CAPTURE + html
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "site.html"), "w", encoding="utf-8") as f:
            f.write(page)
        frames = "".join(f'<iframe data-name="{n}"{" data-forms=1" if n == "phone" else ""} src="site.html" '
                         f'style="width:{w}px;height:900px;border:0"></iframe>' for n, w in WIDTHS.items())
        with open(os.path.join(tmp, "wrap.html"), "w", encoding="utf-8") as f:
            f.write(WRAPPER % (frames, TAP_MIN))
        m = None
        for attempt in range(2):       # one retry: a rare Chrome hang mustn't count as "the site failed the check"
            try:
                p = run_chrome([chrome, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
                                    "--window-size=1400,1000", "--virtual-time-budget=4000", "--dump-dom",
                                    "file://" + os.path.join(tmp, "wrap.html")],
                                   timeout=90)
            except subprocess.TimeoutExpired:
                out["note"] = "Chrome timed out after 90s (twice)."
                continue
            m = re.search(r'data-j2="([^"]*)"', p.stdout)
            if m:
                break
            out["note"] = "Chrome ran but the page never finished loading in both widths (twice)."
    if not m:
        return out
    out.pop("note", None)
    raw = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    errors = []
    # In WIDTHS order, not the order the two frames happened to finish in: a run's recorded mechanical check (and
    # the prompt Audit reads) is then the same for the same page, whichever width loads first.
    for name in list(WIDTHS) + [k for k in raw if k not in WIDTHS]:
        r = raw.get(name)
        if r is None:
            continue
        if "error" in r:
            out[name] = {"note": r["error"]}
            continue
        out[name] = {"width": r["width"], "overflow_px": max(0, r["scroll_width"] - r["width"])}
        errors += [e for e in r["errors"] if e not in errors]
        if "forms" in r:
            out["form_results"] = [{**x, "ok": form_ok(x)} for x in r["forms"]]
        if "design" in r:
            out.setdefault("design", {})[name] = r["design"]
    out.update(available=True, js_errors=errors)
    return out


TAP_WRAPPER = """<!doctype html><html><body><iframe src="site.html" style="width:360px;height:900px;border:0"></iframe>
<script>const f = document.querySelector('iframe');
f.addEventListener('load', () => setTimeout(() => { let out;
  try {
    const w = f.contentWindow, d = w.document, cs = el => w.getComputedStyle(el), sel = %s, min = %d;
    const TAP = 'a[href],button,input:not([type=hidden]),select,textarea,[role=button]';
    const vis = el => { const r = el.getBoundingClientRect(), c = cs(el); return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none' && +c.opacity !== 0; };
    const roots = [...d.querySelectorAll(sel)];
    const taps = [...new Set(roots.flatMap(r => [r, ...r.querySelectorAll(TAP)]))].filter(el => el.matches(TAP));
    // A part hidden until the player gets there (a "solved" panel, a practice pad): shown for the measurement, so a
    // tap check on it measures its buttons instead of failing with none (runs/j2-20261102-111726 W-12, -140419 W-27)
    let revealed = false;
    if (roots.length && taps.length && !taps.some(vis)) {
      revealed = true;
      for (const t of taps) for (let e = t; e && e !== d.body; e = e.parentElement) {
        e.hidden = false;
        if (cs(e).display === 'none') e.style.setProperty('display', 'block', 'important');
        if (cs(e).visibility === 'hidden') e.style.setProperty('visibility', 'visible', 'important');
        if (+cs(e).opacity === 0) e.style.setProperty('opacity', '1', 'important'); } }
    const els = taps.filter(vis)
      .filter(el => !(el.tagName === 'A' && cs(el).display === 'inline' && el.closest('p,li,td,span')));   // links in text are exempt
    const small = els.map(el => [el, el.getBoundingClientRect()]).filter(([, r]) => r.height < min || r.width < min);
    out = {roots: roots.length, checked: els.length, revealed, small_count: small.length, small: small.slice(0, 6).map(([el, r]) =>
      `${el.tagName.toLowerCase()} "${(el.textContent || el.value || el.name || '').trim().slice(0, 25)}" ${Math.round(r.width)}x${Math.round(r.height)}`)};
  } catch (e) { out = {error: String(e)}; }
  document.body.setAttribute('data-j2', JSON.stringify(out)); }, 300));
</script></body></html>"""


def tap_targets(html, selector, min_px=TAP_MIN):
    """Tap targets inside the elements matching selector, measured in headless Chrome at 360px (phone width):
    {available, roots, checked, small_count, small}. Links inside running text are exempt, as in the R-6 check."""
    chrome = find_chrome()
    if not chrome:
        return {"available": False, "note": "Chrome not found (set J2_CHROME)"}
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "site.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(tmp, "wrap.html"), "w", encoding="utf-8") as f:
            f.write(TAP_WRAPPER % (json.dumps(selector), int(min_px)))
        for _ in range(2):             # one retry, as in check(): a Chrome hang isn't a failed check
            try:
                p = run_chrome([chrome, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
                                    "--window-size=400,1000", "--virtual-time-budget=3000", "--dump-dom",
                                    "file://" + os.path.join(tmp, "wrap.html")], timeout=60)
            except subprocess.TimeoutExpired:
                continue
            m = re.search(r'data-j2="([^"]*)"', p.stdout)
            if m:
                r = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<")
                               .replace("&gt;", ">"))
                return {"available": "error" not in r, **r}
    return {"available": False, "note": "Chrome ran but the page never reported (twice)"}


def form_ok(x):
    """Works = has a submit control, no JS error on submit, and the submit event fired (or a field's own rules
    rejected the sample value, which says nothing about the site)."""
    return x["has_submit"] and not x["errors_during"] and (x["submitted"] or bool(x["invalid"]))


def form_problem(x):
    if not x["has_submit"]:
        return f"form {x['index']} has no submit button"
    if x["errors_during"]:
        return f"form {x['index']} throws on submit: {x['errors_during'][0]}"
    return f"form {x['index']} never submits although every field is valid"


def design_problems(c):
    """Rubric items code can measure: {"R-2" contrast, "R-3" hierarchy, "R-6" tap targets, "R-7" alt text: [problems]}.
    Audit may not pass an item that has a measured problem. Empty when the render check didn't run."""
    d, out = c.get("design") or {}, {}
    for n, x in d.items():
        if x["contrast"]["low_count"]:
            out.setdefault("R-2", []).append(f"{n}: {x['contrast']['low_count']} text element(s) below WCAG AA contrast, "
                                             f"e.g. {'; '.join(x['contrast']['low'][:2])}")
    x = d.get("desktop") or d.get("phone")
    if x and x["headings"]["h1"] != 1:
        out.setdefault("R-3", []).append(f"{x['headings']['h1']} h1 headings (the page needs exactly one)")
    if x and x["headings"]["skipped_levels"]:
        out.setdefault("R-3", []).append(f"heading levels skipped {x['headings']['skipped_levels']} time(s)")
    t = (d.get("phone") or {}).get("small_tap_targets") or {}
    if t.get("count"):
        out["R-6"] = [f"{t['count']} tap target(s) under {t['min_px']}x{t['min_px']}px at 360px, e.g. "
                      + "; ".join(t["examples"][:3])]
    if x and x["images_without_alt"]:
        out["R-7"] = [f"{len(x['images_without_alt'])} image(s) without alt: {', '.join(x['images_without_alt'][:3])}"]
    return out


def screenshot(html, path):
    """Phone (360px) and desktop (1280px) first screens side by side in one PNG, for Audit. Returns path or None."""
    chrome = find_chrome()
    if not chrome:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "site.html"), "w", encoding="utf-8") as f:
            f.write(html)
        frames = "".join(f'<iframe src="site.html" style="width:{w}px;height:900px;border:0;margin-right:20px;'
                         f'background:#fff"></iframe>' for w in WIDTHS.values())
        with open(os.path.join(tmp, "shot.html"), "w", encoding="utf-8") as f:
            f.write(f'<!doctype html><body style="margin:0;background:#888;display:flex">{frames}</body>')
        try:
            run_chrome([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                            f"--window-size={sum(WIDTHS.values()) + 40},900", "--virtual-time-budget=4000",
                            f"--screenshot={os.path.abspath(path)}", "file://" + os.path.join(tmp, "shot.html")], timeout=90, text=False)
        except subprocess.TimeoutExpired:
            return None
    return path if os.path.exists(path) and os.path.getsize(path) > 0 else None


def summary(c):
    """One line for the chat."""
    if not c.get("available"):
        return f"Mechanical check unavailable: {c.get('note')} Static: {c['bytes'] / 1000:.0f} KB."
    parts = []
    for n in WIDTHS:
        r = c.get(n) or {}
        if "overflow_px" in r:
            parts.append(f"{n} {r['width']}px: " + (f"overflows by {r['overflow_px']}px" if r["overflow_px"]
                                                    else "no horizontal overflow"))
    parts.append(f"JS errors: {'; '.join(c['js_errors'][:3]) if c['js_errors'] else 'none'}")
    parts.append(f"broken in-page links: {', '.join(c['broken_in_page_links']) or 'none'}")
    fr = c.get("form_results") or []
    if fr:
        bad = [form_problem(x) for x in fr if not x["ok"]]
        parts.append(f"forms: {len(fr) - len(bad)} of {len(fr)} submit" + (f" ({'; '.join(bad)})" if bad else ""))
    dp = design_problems(c)
    parts.append("design measurements: " + ("; ".join(f"{k} {v[0]}" for k, v in dp.items()) if dp else "no problems"))
    parts.append(f"{c['bytes'] / 1000:.0f} KB, {len(c['external_resources'])} external resources")
    return "Mechanical check by code: " + "; ".join(parts) + "."


def problems(c):
    if not c.get("available"):
        return []
    out = [f"{n} overflow {c[n]['overflow_px']}px" for n in WIDTHS if (c.get(n) or {}).get("overflow_px")]
    return (out + [f"JS error: {e}" for e in c["js_errors"]] + [f"broken link #{a}" for a in c["broken_in_page_links"]]
            + [form_problem(x) for x in c.get("form_results") or [] if not x["ok"]])


# ---- behaviour steps: prove the page works, not only that things exist. The interpreter (Python) turns the steps
# into ops, a driver runs the ops (headless Chrome here, a fake one in the tests) and reports what it saw, and the
# interpreter judges the steps from those results, naming the failing step in plain words.
STEP_ARGS = {"set": 2, "click": 1, "scroll-to": 1, "wait": 1, "expect-visible": 1, "expect-hidden": 1,
             "expect-text": 2, "expect-number": 2, "expect-changed": 1, "expect-style-changed": 2, "expect-class": 2}
MAX_STEPS, MAX_WAIT = 8, 3
SETTLE_MS = 150      # after every action, so listeners and observers run before the next step reads the page


def parse_step(step):
    """{"verb", "sel", "arg"} for one step string; ValueError naming what's wrong."""
    parts = str(step or "").split(None, 1)
    verb = parts[0].lower() if parts else ""
    if verb not in STEP_ARGS:
        raise ValueError(f"step {step!r} starts with {verb!r}; allowed: {', '.join(STEP_ARGS)}")
    if verb == "wait":
        rest = parts[1].strip().rstrip("s") if len(parts) > 1 else ""
        try:
            sec = float(rest)
        except ValueError:
            raise ValueError(f"step {step!r}: wait needs a number of seconds") from None
        if not 0 < sec <= MAX_WAIT:
            raise ValueError(f"step {step!r}: wait is at most {MAX_WAIT} seconds")
        return {"verb": verb, "sel": None, "arg": sec}
    words = parts[1].split() if len(parts) > 1 else []
    # A selector may name an element inside another (".cell-selected .cell-value", "#grid > .cell"): every word after
    # the first that starts with # . [ : or is a combinator belongs to it, so a one-part step takes the whole rest and
    # a two-part step keeps at least one word for its value (runs/j2-20261102-140419 lost 4 workflows to this).
    n = 1
    while n < len(words) - (STEP_ARGS[verb] == 2) and (words[n][:1] in "#.[:" or words[n] in (">", "+", "~")
                                                        or words[n - 1] in (">", "+", "~")):
        n += 1
    rest = [" ".join(words[:n])] + ([" ".join(words[n:])] if words[n:] else []) if words else []
    if not rest or (STEP_ARGS[verb] == 2) != (len(rest) == 2):
        raise ValueError(f"step {step!r}: {verb} takes a selector" + (" and a value" if STEP_ARGS[verb] == 2 else " only"))
    return {"verb": verb, "sel": rest[0], "arg": rest[1].strip() if len(rest) == 2 else None}


def safe_number(expr):
    """(value, [number literals]) of an arithmetic expression: numbers, + - * / and brackets only."""
    import ast

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            lits.append(n.value)
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return ev(n.operand) * (-1 if isinstance(n.op, ast.USub) else 1)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(n.left), ev(n.right)
            return a + b if isinstance(n.op, ast.Add) else a - b if isinstance(n.op, ast.Sub) else \
                a * b if isinstance(n.op, ast.Mult) else a / b
        raise ValueError("only numbers, + - * / and brackets")
    lits = []
    try:
        return ev(ast.parse(str(expr).replace(",", ""), mode="eval")), lits
    except (SyntaxError, ZeroDivisionError) as e:
        raise ValueError(str(e)) from None


def compile_steps(steps):
    """(ops, plan): ops for the driver; plan[i] = (index of step i's own op, {snapshot key: op index}). Before every
    wait code reads the text of each expect-changed selector; before every click, each expect-style-changed value."""
    parsed = [parse_step(s) for s in steps]
    changed = sorted({p["sel"] for p in parsed if p["verb"] == "expect-changed"})
    styled = sorted({(p["sel"], p["arg"]) for p in parsed if p["verb"] == "expect-style-changed"})
    ops, plan = [], []
    for p in parsed:
        v, sel, arg, snaps = p["verb"], p["sel"], p["arg"], {}
        if v == "wait":
            for s in changed:
                snaps[("text", s)] = len(ops)
                ops.append({"read": "text", "sel": s})
            ops.append({"do": "wait", "ms": int(arg * 1000)})
        elif v == "click":
            for s, prop in styled:
                snaps[("style", s, prop)] = len(ops)
                ops.append({"read": "style", "sel": s, "prop": prop})
            ops.append({"do": "click", "sel": sel})
        elif v in ("set", "scroll-to"):
            ops.append({"do": "scroll" if v == "scroll-to" else "set", "sel": sel, "val": arg})
        elif v in ("expect-visible", "expect-hidden"):
            ops.append({"read": "visible", "sel": sel})
        elif v == "expect-class":
            ops.append({"read": "class", "sel": sel, "cls": arg})
        elif v == "expect-style-changed":
            ops.append({"read": "style", "sel": sel, "prop": arg})
        else:
            ops.append({"read": "text", "sel": sel})
        plan.append((len(ops) - 1, snaps))
    return ops, parsed, plan


def name_of(sel):
    """A selector in plain words: "#tshirt-size" -> "tshirt size"."""
    return re.sub(r"[-_]+", " ", str(sel).lstrip("#.")).strip()


def numbers_in(text):
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", re.sub(r"(?<=\d),(?=\d)", "", str(text)))]


def judge_steps(steps, results):
    """{actual, pass, evidence} from the driver's results; the first failing step is named in plain words."""
    ops, parsed, plan = compile_steps(steps)
    seen, after = {}, "on load"
    for i, (p, (at, snaps)) in enumerate(zip(parsed, plan), 1):
        if at >= len(results):
            return {"actual": {"failed_step": i}, "pass": None, "evidence": f"could not run: no result for step {i}"}
        for k, j in snaps.items():
            seen[k] = (results[j] or {}).get("v")
        r, v, sel, arg, nm = results[at] or {}, p["verb"], p["sel"], p["arg"], name_of(p["sel"])
        lead = f"{after}, " if after == "on load" else f"after {after}, "
        if r.get("missing"):
            why = f"{lead}nothing on the page matches {nm} (step {i}: {v})"
        elif r.get("error"):
            why = f"{lead}step {i} ({v} {nm}) could not be done: {r['error']}"
        else:
            got, why = r.get("v"), None
            if v in ("set", "click", "scroll-to", "wait"):
                after = f"waiting {arg:g}s" if v == "wait" else {"set": f"choosing {nm} {arg}", "click": f"clicking {nm}",
                                                                 "scroll-to": f"scrolling to {nm}"}[v]
                continue
            if v == "expect-visible" and not got:
                why = f"{lead}{nm} was still hidden"
            elif v == "expect-hidden" and got:
                why = f"{lead}{nm} was still visible"
            elif v == "expect-text" and " ".join(str(arg).split()).lower() not in " ".join(str(got).split()).lower():
                why = f"{lead}{nm} showed {str(got)[:80]!r}, not {arg!r}"
            elif v == "expect-number":
                want, nums = safe_number(arg)[0], numbers_in(got)
                if len(nums) != 1:
                    why = f"{lead}{nm} showed {str(got)[:80]!r}: could not tell which number is the total"
                elif abs(nums[0] - want) >= 0.005:
                    why = f"{lead}{nm} showed {str(got)[:80]!r}, expected {want:g} ({arg})"
            elif v == "expect-changed" and got == seen.get(("text", sel)):
                why = f"{lead}{nm} still showed {str(got)[:80]!r}"
            elif v == "expect-style-changed" and got == seen.get(("style", sel, arg)):
                why = f"{lead}the {arg} of {nm} stayed {got}"
            elif v == "expect-class" and not got:
                why = f"{lead}{nm} did not have the class {arg}"
        if why:
            return {"actual": {"failed_step": i, "step": steps[i - 1]}, "pass": False, "evidence": why}
    return {"actual": {"steps": len(steps)}, "pass": True, "evidence": f"all {len(steps)} step(s) behaved as expected"}


def run_steps(steps, execute):
    """Run behaviour steps with a driver: execute(ops) -> {"available", "results" | "note"}."""
    ops = compile_steps(steps)[0]
    r = execute(ops)
    if not r.get("available"):
        return {"actual": None, "pass": None, "evidence": f"could not run: {r.get('note')}"}
    return judge_steps(steps, r["results"])


BEHAVIOR_WRAPPER = """<!doctype html><html><body><iframe src="site.html" style="width:1280px;height:900px;border:0"></iframe>
<script>const f = document.querySelector('iframe'), ops = %s, SETTLE = %d;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const YES = /^(yes|true|on|1|checked|tick|ticked)$/i;
f.addEventListener('load', () => setTimeout(async () => { const out = [];
  const w = f.contentWindow, d = w.document;
  const fire = el => ['input', 'change'].forEach(t => el.dispatchEvent(new w.Event(t, {bubbles: true})));
  const vis = el => { for (let e = el; e && e.nodeType === 1; e = e.parentElement){ const c = w.getComputedStyle(e);
      if (c.display === 'none' || c.visibility === 'hidden' || e.hidden) return false; }
    const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const label = el => ((el.labels && el.labels[0] && el.labels[0].textContent) || el.value || '').trim().toLowerCase();
  for (const o of ops){ let r;
    try { const all = [...d.querySelectorAll(o.sel || 'body')], el = all[0];
      if (o.do === 'wait') { await sleep(o.ms); r = {v: true}; }
      else if (!el) r = {missing: true};
      else if (o.do === 'set') { const val = String(o.val), lc = val.toLowerCase();
        if (el.tagName === 'SELECT') { const opt = [...el.options].find(x => x.value.toLowerCase() === lc || x.textContent.trim().toLowerCase() === lc);
          if (!opt) throw new Error('no option ' + val); el.value = opt.value; fire(el); }
        else if (el.type === 'radio') { const rb = all.find(x => x.value.toLowerCase() === lc || label(x) === lc);
          if (!rb) throw new Error('no choice ' + val); rb.click(); }
        else if (el.type === 'checkbox') { if (el.checked !== YES.test(val)) el.click(); }
        else { el.focus(); el.value = val; fire(el); }
        r = {v: true}; await sleep(SETTLE); }
      else if (o.do === 'click') { el.click(); r = {v: true}; await sleep(SETTLE); }
      else if (o.do === 'scroll') { el.scrollIntoView(); w.dispatchEvent(new w.Event('scroll')); r = {v: true}; await sleep(SETTLE); }
      else if (o.read === 'visible') r = {v: vis(el)};
      else if (o.read === 'class') r = {v: el.classList.contains(o.cls)};
      else if (o.read === 'style') r = {v: w.getComputedStyle(el).getPropertyValue(o.prop)};
      else r = {v: /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) ? el.value : (el.innerText || el.textContent || '').trim()};
    } catch (e) { r = {error: String(e.message || e)}; }
    out.push(r); }
  document.body.setAttribute('data-j2', JSON.stringify({results: out})); }, 300));
</script></body></html>"""


def behavior(html, ops):
    """Driver for behaviour steps: runs the ops in headless Chrome (1280px frame, virtual time, so waits are fast and
    timers still fire) and returns {available, results}."""
    chrome = find_chrome()
    if not chrome:
        return {"available": False, "note": "Chrome not found (set J2_CHROME)"}
    budget = 3000 + sum(o.get("ms", 0) + SETTLE_MS for o in ops)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "site.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(tmp, "wrap.html"), "w", encoding="utf-8") as f:
            f.write(BEHAVIOR_WRAPPER % (json.dumps(ops), SETTLE_MS))
        for _ in range(2):             # one retry, as in check(): a Chrome hang isn't a failed check
            try:
                p = run_chrome([chrome, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
                                    "--window-size=1300,1000", f"--virtual-time-budget={budget}", "--dump-dom",
                                    "file://" + os.path.join(tmp, "wrap.html")], timeout=90)
            except subprocess.TimeoutExpired:
                continue
            m = re.search(r'data-j2="([^"]*)"', p.stdout)
            if m:
                r = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<")
                               .replace("&gt;", ">"))
                return {"available": True, **r}
    return {"available": False, "note": "Chrome ran but the page never reported (twice)"}


if __name__ == "__main__":   # python j2_check.py site.html [...]: print the mechanical check for each file
    import sys
    for path in sys.argv[1:] or sys.exit("usage: python j2_check.py site.html [...]"):
        with open(path, encoding="utf-8") as f:
            print(path, "->", summary(check(f.read())))
