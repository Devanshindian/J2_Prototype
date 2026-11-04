// Decision cards in the standard question format:
// what's happening, why it matters, 2-4 options (one Suggested), optional own answer, optional fields.

import { h } from "../dom.js";
import { optionUsage } from "../format.js";

const KICKER = {
  facts: "Only you know this",
  usage: "Usage",
  problem: "Needs your call",
  confirm: "Quick check",
  style: "Your look",
};

let uid = 0;

/**
 * renderDecision(decision, {onAnswer, readOnly}) -> element
 * onAnswer({option_id, text, fields}) returns a promise; the card locks while it runs.
 */
export function renderDecision(d, { onAnswer, readOnly = false } = {}) {
  const id = `dc-${++uid}`;
  const card = h("section", { class: `card decision kind-${d.kind}`, "aria-labelledby": `${id}-t`, "data-no-gesture": "" });
  const err = h("p", { class: "card-error", role: "alert", hidden: true });

  card.append(
    h("p", { class: "card-kicker" }, d.kind === "design" && d.step ? `Your look · ${d.step.n} of ${d.step.of}` : KICKER[d.kind] || "Needs you"),
    h("h2", { class: "card-title", id: `${id}-t` }, d.happening || ""),
    d.why ? h("p", { class: "card-why" }, d.why) : null
  );

  // facts the user fills in
  const inputs = {};
  if (d.fields?.length) {
    const fs = h("div", { class: "fields" });
    for (const f of d.fields) {
      const fid = `${id}-${f.id}`;
      const input = h("input", { id: fid, class: "input", type: "text", placeholder: f.placeholder || "", autocomplete: "off" });
      inputs[f.id] = input;
      const field = h("div", { class: "field" }, h("label", { class: "field-label", for: fid }, f.label), input);
      // the team's suggested answers: one tap fills the box (still editable)
      if (f.choices?.length) {
        const chips = h("div", { class: "field-choices", role: "group", "aria-label": "Suggested answers" });
        for (const ch of f.choices) {
          const b = h("button", { class: "choice-chip", type: "button", disabled: readOnly }, ch);
          b.addEventListener("click", () => {
            input.value = ch;
            for (const o of chips.children) o.classList.toggle("is-picked", o === b);
            input.focus();
          });
          chips.append(b);
        }
        field.append(chips);
      }
      fs.append(field);
    }
    card.append(fs);
  }

  const collectFields = () => Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value.trim()]));

  async function answer(option_id, text, btn) {
    if (readOnly || card.classList.contains("is-busy")) return;
    card.classList.add("is-busy");
    card.setAttribute("aria-busy", "true");
    btn?.classList.add("is-chosen");
    err.hidden = true;
    for (const b of card.querySelectorAll("button, input, textarea")) b.disabled = true;
    try {
      await onAnswer({ option_id, text: text || "", fields: collectFields() });
    } catch (e) {
      if (e?.status === 409) return; // the caller refreshes; the card will be replaced
      card.classList.remove("is-busy");
      card.removeAttribute("aria-busy");
      btn?.classList.remove("is-chosen");
      for (const b of card.querySelectorAll("button, input, textarea")) b.disabled = false;
      err.textContent = "That didn't go through. Try again.";
      err.hidden = false;
    }
  }

  // options
  const opts = d.options || [];
  if (d.kind === "style" && opts.length) {
    card.append(styleGrid(opts, answer, readOnly));
  } else if (d.kind === "design" && opts.length) {
    card.append(designGrid(d.topic, opts, answer, readOnly));
  } else if (opts.length) {
    const list = h("div", { class: "options", role: "group", "aria-label": "Choices" });
    for (const o of opts) {
      const cost = optionUsage(o.usage);
      const btn = h(
        "button",
        { class: `option${o.suggested ? " is-suggested" : ""}`, type: "button", disabled: readOnly },
        h("span", { class: "option-head" }, h("span", { class: "option-label" }, o.label), o.suggested ? h("span", { class: "tag" }, "Suggested") : null),
        o.gets || cost ? h("span", { class: "option-meta" }, [o.gets, cost].filter(Boolean).join(" · ")) : null
      );
      btn.addEventListener("click", () => answer(o.id, "", btn));
      list.append(btn);
    }
    card.append(list);
  } else if (d.fields?.length) {
    const send = h("button", { class: "btn btn-primary", type: "button", disabled: readOnly }, "Send");
    send.addEventListener("click", () => answer(null, "", send));
    card.append(h("div", { class: "card-actions" }, send));
  }

  if (d.allow_text && !readOnly) card.append(ownAnswer((text, btn) => answer(null, text, btn), id));
  card.append(err);
  return card;
}

/**
 * The style choice (kind "style"): the three looks side by side (stacked on phones), each a live preview page,
 * its name, one line, the Suggested tag and an "Inspired by" link. One click on a look picks it.
 */
function styleGrid(opts, answer, readOnly) {
  const grid = h("div", { class: "styles", role: "group", "aria-label": "Looks" });
  const frames = [];
  for (const o of opts) {
    const iframe = o.preview_url
      ? h("iframe", { class: "style-preview", src: o.preview_url, loading: "lazy", tabindex: "-1", title: `${o.label} preview`, scrolling: "no", sandbox: "" })
      : null;
    const frame = h("div", { class: "style-frame", "aria-hidden": "true" }, iframe);
    if (iframe) frames.push(frame);
    const btn = h(
      "button",
      { class: `style-pick${o.suggested ? " is-suggested" : ""}`, type: "button", disabled: readOnly, "aria-label": `Pick ${o.label}` },
      frame,
      h("span", { class: "style-text" }, h("span", { class: "option-head" }, h("span", { class: "option-label" }, o.label), o.suggested ? h("span", { class: "tag" }, "Suggested") : null), o.gets ? h("span", { class: "option-meta" }, o.gets) : null)
    );
    btn.addEventListener("click", () => answer(o.id, "", btn));
    const by = o.inspired_by?.url
      ? h("a", { class: "style-by", href: o.inspired_by.url, target: "_blank", rel: "noopener noreferrer" }, `Inspired by ${o.inspired_by.label || o.inspired_by.url}`)
      : o.inspired_by?.label
        ? h("span", { class: "style-by" }, `Inspired by ${o.inspired_by.label}`)
        : null;
    grid.append(h("div", { class: "style-opt" }, btn, by));
  }
  // the preview page is laid out at 1000px and scaled to the frame, so each look shows its desktop hero
  const fit = () => {
    for (const f of frames) {
      const w = f.clientWidth;
      if (w) f.style.setProperty("--k", String(w / 1000));
    }
  };
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(fit);
    for (const f of frames) ro.observe(f);
  }
  requestAnimationFrame(fit);
  return grid;
}

/**
 * The quick design questions after the look (kind "design", feedback 3): fonts, colours, layout, imagery. Each option
 * shows its own sample, drawn from the chosen look (`sample` from the backend): live type, swatches with a button and
 * a card, a wireframe, a small picture. One click picks.
 */
const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, String(v));
  for (const c of kids) if (c) el.append(c);
  return el;
}
const HEX = /^#[0-9a-f]{3,8}$/i;
const col = (p, k, dflt) => (p && HEX.test(String(p[k] || "")) ? p[k] : dflt);
const CSS_FONT = /^[^<>{}"\\;]*$/;
const loadedFonts = new Set();
function useFontCss(url) {
  if (!url || loadedFonts.has(url) || !/^https:\/\/fonts\.googleapis\.com\//.test(url)) return;
  loadedFonts.add(url);
  document.head.append(h("link", { rel: "stylesheet", href: url }));
}

function fontSample(x) {
  const hd = CSS_FONT.test(x.heading || "") ? x.heading : "serif";
  const bd = CSS_FONT.test(x.body || "") ? x.body : "sans-serif";
  useFontCss(x.google_fonts_url);
  const big = h("span", { class: "ds-font-aa" }, "Aa");
  big.style.fontFamily = hd;
  const head = h("span", { class: "ds-font-head" }, "Fresh every morning");
  head.style.fontFamily = hd;
  const body = h("span", { class: "ds-font-body" }, "Open daily from eight. Come in and say hello.");
  body.style.fontFamily = bd;
  return h("div", { class: "ds-sample ds-font" }, big, h("span", { class: "ds-font-text" }, head, body));
}

function paletteSample(x) {
  const p = x.palette || {};
  const keys = ["primary", "accent", "secondary", "surface", "text"];
  const sw = h("div", { class: "ds-swatches" }, ...keys.map((k) => {
    const c = h("span", { class: "ds-swatch", title: k });
    c.style.background = col(p, k, "#ccc");
    return c;
  }));
  const btn = h("span", { class: "ds-btn" }, "Book now");
  btn.style.background = col(p, "primary", "#555");
  btn.style.borderRadius = String(x.radius || "10px").replace(/[^0-9.a-z%]/gi, "");
  const card = h("span", { class: "ds-mini-card" }, h("b", {}, "Opening hours"), h("i", {}, "Mon to Sat, 8 to 8"));
  card.style.background = col(p, "surface", "#f4f4f4");
  card.style.color = col(p, "text", "#222");
  const box = h("div", { class: "ds-sample ds-palette" }, sw, h("div", { class: "ds-pal-row" }, btn, card));
  box.style.background = col(p, "background", "#fff");
  return box;
}

function layoutSample(x) {
  const p = x.palette || {};
  const pr = col(p, "primary", "#888"), su = col(p, "surface", "#eee"), tx = col(p, "text", "#333"), bg = col(p, "background", "#fff");
  const line = (x0, y, w, o = 0.55) => s("rect", { x: x0, y, width: w, height: 3, rx: 1.5, fill: tx, opacity: o });
  const kids = [s("rect", { x: 0, y: 0, width: 120, height: 80, fill: bg })];
  if (x.layout === "airy") {
    kids.push(line(38, 10, 44, 0.8), line(30, 18, 60), line(34, 24, 52), s("rect", { x: 48, y: 31, width: 24, height: 6, rx: 3, fill: pr }),
      s("rect", { x: 34, y: 46, width: 52, height: 12, rx: 3, fill: su }), s("rect", { x: 34, y: 62, width: 52, height: 12, rx: 3, fill: su }));
  } else if (x.layout === "two-column") {
    kids.push(line(10, 12, 40, 0.8), line(10, 20, 46), line(10, 26, 38), s("rect", { x: 10, y: 33, width: 22, height: 6, rx: 3, fill: pr }),
      s("rect", { x: 64, y: 8, width: 46, height: 34, rx: 4, fill: su }),
      s("rect", { x: 10, y: 50, width: 47, height: 22, rx: 3, fill: su }), s("rect", { x: 63, y: 50, width: 47, height: 22, rx: 3, fill: su }));
  } else {
    kids.push(s("rect", { x: 0, y: 0, width: 120, height: 38, fill: pr }),
      s("rect", { x: 14, y: 12, width: 56, height: 5, rx: 2.5, fill: "#fff", opacity: 0.95 }), s("rect", { x: 14, y: 22, width: 40, height: 3, rx: 1.5, fill: "#fff", opacity: 0.7 }),
      s("rect", { x: 0, y: 38, width: 120, height: 22, fill: su }), line(14, 47, 70),
      s("rect", { x: 0, y: 60, width: 120, height: 20, fill: bg }), line(14, 68, 50));
  }
  return h("div", { class: "ds-sample ds-layout" }, s("svg", { viewBox: "0 0 120 80", preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true" }, ...kids));
}

function imagerySample(x) {
  const p = x.palette || {};
  const pr = col(p, "primary", "#888"), ac = col(p, "accent", pr), su = col(p, "surface", "#eee"), bg = col(p, "background", "#fff");
  const kids = [s("rect", { x: 0, y: 0, width: 120, height: 80, fill: bg })];
  if (x.imagery === "illustration") {
    kids.push(s("circle", { cx: 86, cy: 26, r: 12, fill: ac, opacity: 0.55 }),
      s("path", { d: "M0 80 L0 58 Q30 40 58 56 T120 50 L120 80 Z", fill: pr, opacity: 0.35 }),
      s("path", { d: "M0 80 L0 66 Q40 54 74 66 T120 64 L120 80 Z", fill: pr, opacity: 0.6 }),
      s("path", { d: "M30 62 v-14 M30 50 q-6 -2 -6 -8 q6 0 6 8 M30 54 q6 -2 6 -8 q-6 0 -6 8", stroke: pr, "stroke-width": 1.6, fill: "none" }));
  } else if (x.imagery === "icons") {
    const icon = (cx, d) => s("g", { transform: `translate(${cx} 30)` }, s("circle", { r: 13, fill: su }), s("path", { d, stroke: pr, "stroke-width": 1.8, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" }));
    kids.push(icon(24, "M-5 -1 a5 5 0 1 1 10 0 a5 5 0 1 1 -10 0 M0 -1 v-3 M0 -1 l2 2"), icon(60, "M-6 -4 h12 v8 h-12z M-6 -1 h12"),
      icon(96, "M0 6 s-6 -5 -6 -9 a6 6 0 1 1 12 0 c0 4 -6 9 -6 9z"),
      ...[24, 60, 96].map((cx) => s("rect", { x: cx - 14, y: 52, width: 28, height: 3, rx: 1.5, fill: pr, opacity: 0.35 })));
  } else if (x.imagery === "photo") {
    const g = `ph-${Math.random().toString(36).slice(2, 8)}`;
    kids.push(s("defs", {}, s("linearGradient", { id: g, x1: 0, y1: 0, x2: 1, y2: 1 }, s("stop", { offset: 0, "stop-color": pr, "stop-opacity": 0.55 }), s("stop", { offset: 1, "stop-color": ac, "stop-opacity": 0.35 }))),
      s("rect", { x: 10, y: 10, width: 60, height: 44, rx: 6, fill: `url(#${g})` }),
      s("path", { d: "M16 48 l14 -14 l10 9 l8 -6 l16 11 z", fill: "#fff", opacity: 0.55 }), s("circle", { cx: 56, cy: 22, r: 5, fill: "#fff", opacity: 0.6 }),
      s("rect", { x: 78, y: 10, width: 32, height: 20, rx: 4, fill: `url(#${g})`, opacity: 0.8 }), s("rect", { x: 78, y: 34, width: 32, height: 20, rx: 4, fill: `url(#${g})`, opacity: 0.6 }),
      s("rect", { x: 10, y: 62, width: 40, height: 3, rx: 1.5, fill: pr, opacity: 0.4 }));
  } else {
    kids.push(s("circle", { cx: 92, cy: 24, r: 14, fill: "none", stroke: pr, "stroke-width": 1.5, opacity: 0.7 }),
      s("rect", { x: 14, y: 50, width: 18, height: 18, rx: 2, fill: ac, opacity: 0.4 }),
      s("path", { d: "M44 66 H106", stroke: pr, "stroke-width": 1.2, opacity: 0.5 }), s("path", { d: "M14 22 H58", stroke: pr, "stroke-width": 1.2, opacity: 0.35 }));
  }
  return h("div", { class: "ds-sample ds-imagery" }, s("svg", { viewBox: "0 0 120 80", preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true" }, ...kids));
}

const SAMPLE = { fonts: fontSample, palette: paletteSample, layout: layoutSample, imagery: imagerySample };

function designGrid(topic, opts, answer, readOnly) {
  const grid = h("div", { class: `design-opts topic-${topic || "x"}`, role: "group", "aria-label": "Choices" });
  for (const o of opts) {
    const make = SAMPLE[topic];
    let sample = null;
    try {
      sample = make && o.sample ? make(o.sample) : null;
    } catch {
      sample = null;
    }
    const btn = h(
      "button",
      { class: `design-pick${o.suggested ? " is-suggested" : ""}`, type: "button", disabled: readOnly, "data-option": o.id },
      sample,
      h("span", { class: "style-text" }, h("span", { class: "option-head" }, h("span", { class: "option-label" }, o.label), o.suggested ? h("span", { class: "tag" }, "Suggested") : null), o.gets ? h("span", { class: "option-meta" }, o.gets) : null)
    );
    btn.addEventListener("click", () => answer(o.id, "", btn));
    grid.append(btn);
  }
  return grid;
}

/** A one-line "your own answer" box with a Send button. */
export function ownAnswer(onSend, id, placeholder = "Or say it in your own words") {
  const input = h("input", { class: "input", type: "text", placeholder, "aria-label": placeholder, id: `${id}-own` });
  const send = h("button", { class: "btn btn-quiet", type: "submit", disabled: true }, "Send");
  input.addEventListener("input", () => (send.disabled = !input.value.trim()));
  const form = h("form", { class: "own-answer" }, input, send);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = input.value.trim();
    if (v) onSend(v, send);
  });
  return form;
}
