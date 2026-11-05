// The centre of the studio view: the thing being built, live (/api/v2/live).
// - A website sits in a frame (the page as assembled so far; sections still to come are calm placeholders). A layer
//   inside the frame marks each section: who is on it, a check when done, a glow where a question waits. A new
//   version loads in a second frame behind the first and swaps in at the same scroll place, so nothing flashes.
// - A document (PRD, HLD, LLD) is drawn here from its blocks, one per section, with the same marks.
// - Before anything exists, a sketch: the planned parts as placeholders.
// The inline slot holds the open question (or the "Decided for you" lines) at the section it is about, or at the top.
// Inside the site frame it lives in a shadow root, so the page's own CSS never touches the card.

import { h } from "../dom.js";
import { renderMarkdown } from "../markdown.js";
import { avatar } from "./people.js";
import { COLOR } from "./team.js";

const FONTS = "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;600;700&family=Figtree:wght@400;500;600&display=swap";
const NAME = { asha: "Asha", mira: "Mira", kabir: "Kabir", dev: "Dev", nora: "Nora" };

// the shared card styles as text, for the shadow roots inside the site frame (:root becomes :host there)
let cssText = null;
function cardCss() {
  cssText ||= Promise.all(["/ui/styles/tokens.css", "/ui/styles/app.css", "/ui/styles/studio.css"].map((u) => fetch(u).then((r) => (r.ok ? r.text() : ""))))
    .then((all) => all.join("\n").replace(/:root(?![\w-])/g, ":host"))
    .catch(() => "");
  return cssText;
}
const HOST_CSS = ":host{all:initial;display:block;font-family:var(--font);color:var(--ink);font-size:16px;line-height:1.5;text-align:left}";
const LAYER_CSS = `
:host{all:initial}
.box{position:absolute;border-radius:10px;pointer-events:none;outline:2px solid transparent;outline-offset:3px;transition:outline-color .4s, box-shadow .4s}
.box.doing{outline-color:var(--c)}
.box.fix{outline:2px dashed #D9822B}
.box.ask{outline-color:#D9822B;animation:glow 2.2s ease-in-out infinite}
.box.flash{animation:flash 1.2s ease 2}
@keyframes glow{50%{box-shadow:0 0 0 8px #d9822b22}}
@keyframes flash{50%{box-shadow:0 0 0 6px #3D5A8033;background:#3D5A800d}}
.tag{position:absolute;right:14px;top:-13px;display:flex;align-items:center;gap:6px;background:var(--c);color:#fff;border:0;border-radius:999px;
  padding:3px 10px 3px 3px;font:600 12px/1.2 Figtree,system-ui,sans-serif;box-shadow:0 6px 16px -8px #0006;pointer-events:auto;cursor:pointer;white-space:nowrap}
.tag.soft{background:#fff;color:#686C66;border:1px solid #E2DED5;box-shadow:none}
.tag svg{border-radius:50%;display:block}
.tick{position:absolute;right:10px;top:10px;width:22px;height:22px;border-radius:50%;background:#eaf3ed;color:#3E8E5E;border:0;display:grid;place-items:center;
  font:700 11px/1 system-ui,sans-serif;pointer-events:auto;cursor:pointer;box-shadow:0 1px 3px #0002}
.tag:focus-visible,.tick:focus-visible{outline:2px solid #3D5A80;outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
`;

export function createOutput({ el, onTag }) {
  let mode = "";            // "site" | "doc"
  let live = null;
  let parts = [];
  let key = "";
  let frame = null;         // the visible site frame
  let next = null;          // a newer version loading behind it
  let wantKey = "";
  let inline = { node: null, anchor: null, kind: "" };
  let docEl = null;
  let onScroll = () => {};
  let ended = false;        // the run has ended: a part that needs a fix is left open, nobody is fixing it
  const marks = new Map();  // section id -> {state, person}

  /* ---------- what each section shows: who is on it, done, waits for an answer ---------- */
  function computeMarks() {
    marks.clear();
    const bySec = new Map();
    for (const p of parts) if (p.anchor) (bySec.get(p.anchor) || bySec.set(p.anchor, []).get(p.anchor)).push(p);
    for (const [sid, ps] of bySec) {
      const pick = (step) => ps.find((p) => p.step === step);
      const ask = pick("ask"), doing = pick("doing"), fix = pick("fix");
      const p = ask || doing || fix || ps.find((x) => x.step === "next") || ps[ps.length - 1];
      const state = ask ? "ask" : doing ? "doing" : fix ? "fix" : ps.every((x) => x.step === "next" || x.step === "skip") ? "wait" : "done";
      marks.set(sid, { state, person: p.person, part: p });
    }
  }

  /* ---------- the site frame ---------- */
  function siteUrl(k) {
    return `${live.url}${live.url.includes("?") ? "&" : "?"}k=${encodeURIComponent(k)}`;
  }

  function loadSite(k) {
    wantKey = k;
    if (next) return; // one load at a time; the newest key loads right after
    const f = h("iframe", { class: "st-site is-next", title: `${live.title || "Your website"}, live`, src: siteUrl(k) });
    next = f;
    f.addEventListener("load", () => {
      const was = frame;
      const place = was ? scrollPlace(was) : null;
      next = null;
      if (wantKey !== k) {
        f.remove();
        return loadSite(wantKey);
      }
      frame = f;
      key = k;
      setupFrame(f);
      if (place) restorePlace(f, place);
      f.classList.remove("is-next");
      was?.remove();
      decorate();
    }, { once: true });
    el.append(f);
  }

  function scrollPlace(f) {
    try {
      const doc = f.contentDocument;
      for (const s of doc.querySelectorAll("[data-j2-section]")) {
        const r = s.getBoundingClientRect();
        if (r.bottom > 0) return { sid: s.dataset.j2Section, top: r.top, y: f.contentWindow.scrollY };
      }
      return { y: f.contentWindow.scrollY };
    } catch {
      return null;
    }
  }
  function restorePlace(f, p) {
    const win = f.contentWindow;
    const s = p.sid && f.contentDocument.querySelector(`[data-j2-section="${CSS.escape(p.sid)}"]`);
    const y = s ? s.getBoundingClientRect().top + win.scrollY - p.top : p.y;
    win.scrollTo({ top: Math.max(0, y), behavior: "instant" });
  }

  function setupFrame(f) {
    const doc = f.contentDocument;
    const win = f.contentWindow;
    if (!doc?.body) return;
    if (!doc.querySelector("link[data-j2-fonts]")) doc.head.append(Object.assign(doc.createElement("link"), { rel: "stylesheet", href: FONTS }));
    doc.querySelector("link[rel=stylesheet][href^='https://fonts.googleapis.com/css2?family=Bricolage']")?.setAttribute("data-j2-fonts", "");
    // a link that leaves the page opens in a new tab; links inside the page scroll inside the frame
    doc.addEventListener("click", (e) => {
      const a = e.target.closest?.("a[href]");
      if (!a) return;
      const href = a.getAttribute("href") || "";
      if (href.startsWith("#") || href.startsWith("javascript:")) return;
      e.preventDefault();
      window.open(a.href, "_blank", "noopener");
    });
    win.addEventListener("scroll", () => onScroll(), { passive: true });
    win.addEventListener("resize", () => layout());
    if (win.ResizeObserver) new win.ResizeObserver(() => layout()).observe(doc.documentElement);
    for (const ms of [300, 1200, 3000]) setTimeout(layout, ms); // fonts and images settle
  }

  /** The layer of marks and the inline slot, (re)placed in the current frame. */
  function decorate() {
    if (mode !== "site" || !frame) return;
    const doc = frame.contentDocument;
    if (!doc?.body) return;
    let layer = doc.querySelector("j2-layer");
    if (!layer) {
      layer = doc.createElement("j2-layer");
      layer.setAttribute("aria-hidden", "false");
      layer.style.cssText = "position:absolute;top:0;left:0;width:0;height:0;overflow:visible;z-index:2147483000;pointer-events:none;display:block;margin:0;padding:0;border:0";
      const root = layer.attachShadow({ mode: "open" });
      root.append(Object.assign(doc.createElement("style"), { textContent: LAYER_CSS }), doc.createElement("div"));
      root.addEventListener("click", (e) => {
        const t = e.target.closest?.("[data-sec]");
        if (t) onTag?.(t.dataset.sec);
      });
      doc.body.append(layer);
    }
    placeInline(doc);
    layout();
  }

  function placeInline(doc) {
    let host = doc.querySelector("j2-ask");
    if (!inline.node) {
      host?.remove();
      return;
    }
    if (!host) {
      host = doc.createElement("j2-ask");
      host.setAttribute("data-theme", "light");
      host.style.cssText = "display:block;position:relative;z-index:5;box-sizing:border-box;width:100%;max-width:640px;margin:18px auto 22px;padding:0 14px";
      const root = host.attachShadow({ mode: "open" });
      const style = doc.createElement("style");
      style.textContent = HOST_CSS;
      cardCss().then((t) => (style.textContent = HOST_CSS + t + HOST_CSS));
      root.append(style, doc.createElement("div"));
      if (frame.contentWindow.ResizeObserver) new frame.contentWindow.ResizeObserver(() => layout()).observe(host);
    }
    const slot = host.shadowRoot.lastElementChild;
    if (slot.firstChild !== inline.node) slot.replaceChildren(inline.node);
    // where: after the section the question is about, else at the top (after a header or nav)
    const target = inline.anchor && doc.querySelector(`[data-j2-section="${CSS.escape(inline.anchor)}"]`);
    const all = [...doc.querySelectorAll("[data-j2-section]")];
    let before = null;
    if (target) before = all[all.indexOf(target) + 1] || null;
    else before = all.find((x) => !/^(NAV|HEADER)$/.test(x.tagName) && !/fixed|sticky/.test(frame.contentWindow.getComputedStyle(x).position)) || null;
    const parent = before?.parentNode || (target ? target.parentNode : doc.body);
    if (target && !before) {
      if (host.previousElementSibling !== target) target.after(host);
    } else if (before) {
      if (host.nextElementSibling !== before) parent.insertBefore(host, before);
    } else if (doc.body.firstElementChild !== host) doc.body.prepend(host);
  }

  /** A section's area on the page: its tagged first element and the untagged elements after it (a section's markup
   * can be several top-level elements, and one part can build the whole page), leaving out a sticky or fixed bar
   * (it moves with the view; no frame around it). Null when nothing of it is drawn. */
  function sectionRect(s, win) {
    let top = Infinity, left = Infinity, right = -Infinity, bottom = -Infinity;
    for (let n = s; n; n = n.nextElementSibling) {
      if (n !== s && (n.hasAttribute("data-j2-section") || n.tagName === "J2-LAYER")) break;
      if (/^(J2-ASK|SCRIPT|STYLE|TEMPLATE)$/.test(n.tagName) || /fixed|sticky/.test(win.getComputedStyle(n).position)) continue;
      const r = n.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      top = Math.min(top, r.top);
      left = Math.min(left, r.left);
      right = Math.max(right, r.right);
      bottom = Math.max(bottom, r.bottom);
    }
    return top === Infinity ? null : { top, left, width: right - left, height: bottom - top };
  }

  function layout() {
    if (mode !== "site" || !frame) return;
    const doc = frame.contentDocument;
    const layer = doc?.querySelector("j2-layer");
    if (!layer) return;
    const box = layer.shadowRoot.lastElementChild;
    const base = layer.getBoundingClientRect();
    const win = frame.contentWindow;
    // the marks are kept per section and only redrawn when what they say changes, so a focused or hovered mark
    // survives the poll
    const kept = (box.__marks ||= new Map());
    const seen = new Set();
    for (const s of doc.querySelectorAll("[data-j2-section]")) {
      const sec = s.dataset.j2Section;
      const m = marks.get(sec);
      if (!m) continue;
      // our own placeholder says who is on it now (the page's sections are never touched)
      const note = s.dataset.j2Wait ? s.querySelector(".j2-wait-note") : null;
      if (note) {
        const want = m.state === "doing" ? `${NAME[m.person]} is on it` : m.state === "ask" ? "Waiting on your answer" : ended ? "Not built in this run" : "Coming up";
        if (note.textContent !== want) note.textContent = want;
      }
      const r = sectionRect(s, win);
      if (!r || r.height < 8) continue;
      seen.add(sec);
      const c = COLOR[m.person] || "#3D5A80";
      let d = kept.get(sec);
      if (!d) {
        d = doc.createElement("div");
        d.dataset.box = sec;
        kept.set(sec, d);
        box.append(d);
      }
      const sig = `${m.state}|${m.person}|${m.part.name}|${ended}`;
      if (d.__sig !== sig) {
        d.__sig = sig;
        d.className = `box ${m.state}`;
        if (m.state === "done") {
          d.innerHTML = `<button class="tick" type="button" data-sec="${esc(sec)}" title="Done. See what ${esc(m.part.name.toLowerCase())} made" aria-label="Done: ${esc(m.part.name)}. See what it made">✓</button>`;
        } else {
          const soft = m.state === "wait" ? " soft" : "";
          const verb = verbOf(m.state);
          d.innerHTML = `<button class="tag${soft}" type="button" data-sec="${esc(sec)}" style="--c:${c}" aria-label="${esc(NAME[m.person])} is on ${esc(m.part.name)}">${avatar(m.person, 22, { prop: false })}${esc(NAME[m.person])}${verb}</button>`;
        }
      }
      d.style.top = `${r.top - base.top}px`;
      d.style.left = `${r.left - base.left}px`;
      d.style.width = `${r.width}px`;
      d.style.height = `${r.height}px`;
      d.style.setProperty("--c", c);
    }
    for (const [sec, d] of kept) {
      if (seen.has(sec)) continue;
      d.remove();
      kept.delete(sec);
    }
    onScroll();
  }

  /* ---------- documents and the sketch ---------- */
  function renderDoc() {
    const blocks = live.blocks || [];
    const head = h("header", { class: "st-doc-head" },
      h("p", { class: "st-doc-kicker" }, live.kind === "document" ? (live.doc || "").toUpperCase() : "Website"),
      h("h1", { class: "st-doc-title" }, live.title || (live.kind === "document" ? "Your document" : "Your website")));
    const body = blocks.map((b) => {
      // in the sketch a finished part with no section yet (notes, the look) is a quiet line, not a skeleton
      const made = b.markdown == null && b.state === "done";
      const sec = h("section", { class: `st-block ${b.markdown == null ? "is-wait" : ""}${made ? " is-made" : ""}`, "data-anchor": b.anchor || "" });
      if (made) sec.append(h("p", { class: "st-wait-name" }, b.name || "A part"), h("p", { class: "st-wait-note" }, b.note || "Done"));
      else if (b.markdown == null) sec.append(h("p", { class: "st-wait-name" }, b.name || "A part"), h("p", { class: "st-wait-note" }, b.note || "Coming up"), h("i"), h("i"), h("i"));
      else sec.append(h("div", { class: "doc st-md", html: renderMarkdown(b.markdown) }));
      return sec;
    });
    const empty = !blocks.length ? h("p", { class: "st-doc-empty" }, live.empty || "The team is getting started.") : null;
    docEl = h("article", { class: "st-doc" }, head, empty, ...body);
    el.replaceChildren(docEl);
    key = live.key;
  }

  function decorateDoc() {
    if (mode !== "doc" || !docEl) return;
    for (const sec of docEl.querySelectorAll(".st-block")) {
      const m = marks.get(sec.dataset.anchor);
      // redrawn only when what the mark says changes, so a focused mark survives the poll
      const sig = m ? `${m.state}|${m.person}|${m.part.name}|${ended}` : "";
      if (sec.__markSig === sig) continue;
      sec.__markSig = sig;
      sec.querySelector(":scope > .st-mark")?.remove();
      sec.classList.remove("doing", "ask", "fix", "flash-keep");
      if (!m) continue;
      // a placeholder says who is on it now, as on the site (a part waiting on the person is not "on it")
      const note = sec.querySelector(":scope > .st-wait-note");
      if (note && (m.state === "doing" || m.state === "ask")) note.textContent = m.state === "ask" ? "Waiting on your answer" : `${NAME[m.person]} is on it`;
      sec.classList.toggle("doing", m.state === "doing");
      sec.classList.toggle("ask", m.state === "ask");
      sec.classList.toggle("fix", m.state === "fix");
      sec.style.setProperty("--c", COLOR[m.person]);
      const sid = sec.dataset.anchor;
      let mark;
      if (m.state === "done") mark = h("button", { class: "st-mark st-tick", type: "button", title: `Done. See what ${m.part.name.toLowerCase()} made`, "aria-label": `Done: ${m.part.name}. See what it made` }, "✓");
      else {
        const verb = verbOf(m.state);
        mark = h("button", { class: `st-mark st-tag${m.state === "wait" ? " soft" : ""}`, type: "button", style: `--c:${COLOR[m.person]}`, "aria-label": `${NAME[m.person]} is on ${m.part.name}` });
        mark.innerHTML = avatar(m.person, 22, { prop: false });
        mark.append(`${NAME[m.person]}${verb}`);
      }
      mark.addEventListener("click", () => onTag?.(sid));
      sec.append(mark);
    }
    // the inline slot
    let slot = docEl.querySelector(":scope > .st-inline");
    if (!inline.node) return slot?.remove();
    if (!slot) slot = h("div", { class: "st-inline" });
    if (slot.firstChild !== inline.node) slot.replaceChildren(inline.node);
    const target = inline.anchor && docEl.querySelector(`.st-block[data-anchor="${CSS.escape(inline.anchor)}"]`);
    if (target) {
      if (target.nextElementSibling !== slot) target.after(slot);
    } else {
      const head = docEl.querySelector(".st-doc-head");
      if (head.nextElementSibling !== slot) head.after(slot);
    }
  }

  /* ---------- public ---------- */
  function verbOf(state) {
    if (state === "wait") return ended ? " · not built" : " · next";
    if (state === "fix") return ended ? " · needs a fix" : " · fixing";
    return state === "ask" ? " · waiting on you" : "";
  }

  function update(l, ps, opts = {}) {
    parts = ps || [];
    ended = !!opts.ended;
    const siteMode = l && l.kind === "website" && l.url && l.started;
    const nextMode = siteMode ? "site" : "doc";
    const changed = !live || l.key !== live.key || nextMode !== mode || l.kind !== live.kind || l.doc !== live.doc;
    live = l;
    computeMarks();
    if (nextMode !== mode) {
      el.replaceChildren();
      frame = next = docEl = null;
      key = "";
      mode = nextMode;
    }
    el.dataset.mode = mode;
    if (mode === "site") {
      if (changed && l.key !== key) loadSite(l.key);
      decorate();
    } else {
      if (changed || !docEl) renderDoc();
      decorateDoc();
      onScroll();
    }
  }

  /** The inline slot: a question card (or the decided lines) at a section, or at the top when `anchor` is null. */
  function setInline(node, anchor, kind = "") {
    if (inline.node === node && inline.anchor === anchor) return;
    inline = { node, anchor, kind };
    if (mode === "site") decorate();
    else decorateDoc();
    onScroll();
  }

  function scroller() {
    return mode === "site" ? frame?.contentWindow : el;
  }
  function find(sel) {
    return mode === "site" ? frame?.contentDocument?.querySelector(sel) : docEl?.querySelector(sel);
  }
  /** How much of the frame's top a sticky or fixed header covers (so a section lands below it, not under it). */
  function coveredTop() {
    if (mode !== "site" || !frame) return 0;
    const win = frame.contentWindow;
    let y = 0;
    for (const x of frame.contentDocument.querySelectorAll("[data-j2-section], body > header, body > nav")) {
      if (!/fixed|sticky/.test(win.getComputedStyle(x).position)) continue;
      const r = x.getBoundingClientRect();
      if (r.top <= 4 && r.height < win.innerHeight / 3) y = Math.max(y, r.bottom);
    }
    return y;
  }
  function scrollToNode(n, smooth = true) {
    const sc = scroller();
    if (!n || !sc) return false;
    const top = n.getBoundingClientRect().top - (mode === "site" ? 0 : el.getBoundingClientRect().top) + (mode === "site" ? sc.scrollY : el.scrollTop) - 20 - coveredTop();
    sc.scrollTo({ top: Math.max(0, top), behavior: smooth && !matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "instant" });
    return true;
  }

  /** Scrolls the output to a section and flashes it; false when the part has no section here. */
  function goTo(anchor) {
    const sel = mode === "site" ? `[data-j2-section="${CSS.escape(anchor)}"]` : `.st-block[data-anchor="${CSS.escape(anchor)}"]`;
    const n = find(sel);
    if (!scrollToNode(n)) return false;
    const flashEl = mode === "site" ? frame.contentDocument.querySelector("j2-layer")?.shadowRoot.querySelector(`[data-box="${CSS.escape(anchor)}"]`) : n;
    if (flashEl) {
      flashEl.classList.remove("flash");
      void flashEl.offsetWidth;
      flashEl.classList.add("flash");
      setTimeout(() => flashEl.classList.remove("flash"), 2600);
    }
    return true;
  }

  /** Where the inline slot is against the view: "above", "below", "in" or null (no slot). */
  function inlineWhere() {
    if (!inline.node) return null;
    const n = mode === "site" ? frame?.contentDocument?.querySelector("j2-ask") : docEl?.querySelector(".st-inline");
    if (!n) return null;
    const r = n.getBoundingClientRect();
    const vh = mode === "site" ? frame.contentWindow.innerHeight : el.clientHeight;
    const top = mode === "site" ? r.top : r.top - el.getBoundingClientRect().top;
    if (top > vh - 70) return "below";
    if (top + Math.min(r.height, 120) < 0) return "above";
    return "in";
  }
  function scrollToInline() {
    scrollToNode(mode === "site" ? frame?.contentDocument?.querySelector("j2-ask") : docEl?.querySelector(".st-inline"));
  }

  el.addEventListener("scroll", () => onScroll(), { passive: true });
  window.addEventListener("resize", () => layout());

  return {
    update,
    setInline,
    goTo,
    inlineWhere,
    scrollToInline,
    set onScroll(fn) {
      onScroll = fn;
    },
    get mode() {
      return mode;
    },
  };
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
