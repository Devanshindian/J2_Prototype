// "See details": a centre panel over the map with what a team-talk line is really about, in plain words, built
// from the line's structured detail (api-contract.md, backstage detail.kind): the plan (parts by stage, what each
// waits for, the plan reviewer's confidence), checks (each with a pass or fail and one reason),
// budget numbers, a decision (asked and chosen), or what was decided and why. Not a blocking modal: a click
// anywhere outside it, Esc or Back closes it, and the person is back where they were.

import { h, icon } from "../dom.js";
import { renderMarkdown } from "../markdown.js";

const TITLES = { plan: "The plan", checks: "What was checked", budget: "Usage", decision: "A decision", generic: "What happened" };

export function createDetailPanel() {
  const back = h("button", { class: "btn btn-quiet btn-sm dp-back", type: "button" }, icon("back", 15), h("span", null, "Back"));
  const eyebrow = h("p", { class: "dp-eyebrow" });
  const title = h("h2", { class: "dp-title", id: "dp-title", tabindex: "-1" });
  const line = h("p", { class: "dp-line" });
  const body = h("div", { class: "dp-body" });
  const statusTag = h("span", { class: "dp-status", hidden: true });
  const tools = h("div", { class: "dp-tools", hidden: true });
  const noteRow = h("form", { class: "dp-note-row", hidden: true });
  const titleRow = h("div", { class: "dp-title-row" }, h("div", { class: "dp-title-wrap" }, title, statusTag), tools);
  const card = h("section", { class: "dp-card", role: "dialog", "aria-modal": "false", "aria-labelledby": "dp-title", "data-no-gesture": "" },
    h("div", { class: "dp-head" }, back), eyebrow, titleRow, noteRow, line, body);
  const el = h("div", { class: "dpanel", id: "detail-panel", hidden: true }, card);
  document.body.append(el);

  let opener = null;

  function close({ restoreFocus = true } = {}) {
    if (el.hidden) return;
    el.hidden = true;
    el.classList.remove("is-in", "is-output");
    document.body.classList.remove("with-output");
    body.replaceChildren(); // an output's preview frame stops loading
    if (restoreFocus && opener && document.contains(opener)) opener.focus({ preventScroll: true });
    opener = null;
  }

  /** open(line, {trigger}): `line` is a backstage line with its structured detail. */
  function open(b, { trigger } = {}) {
    const d = b.detail || {};
    const kind = TITLES[d.kind] ? d.kind : "generic";
    opener = trigger || document.activeElement;
    el.dataset.kind = kind;
    el.classList.remove("is-output");
    document.body.classList.remove("with-output");
    statusTag.hidden = tools.hidden = noteRow.hidden = true;
    eyebrow.hidden = false;
    eyebrow.textContent = b.to ? `${b.from} → ${b.to}` : b.from || "";
    title.textContent = TITLES[kind];
    // the plan's own count line replaces the message (one count, from the plan shown below)
    line.textContent = kind === "plan" ? "" : b.text || "";
    line.hidden = !line.textContent;
    body.replaceChildren(...render(kind, d));
    el.hidden = false;
    card.scrollTop = 0;
    requestAnimationFrame(() => el.classList.add("is-in"));
    requestAnimationFrame(() => title.focus({ preventScroll: true }));
  }

  /**
   * openOutput(payload, {status, controls, docUrl, trigger}): a finished part's real output (/api/v2/output) in the
   * same centred panel, large, the map dimmed behind: the file it wrote (rendered), the look, the built section in the
   * page preview, or the sources it read. The header names the part and its status and carries its controls
   * (Redo, Note) as small buttons.
   */
  function openOutput(o, { status = "Done", controls = [], docUrl = null, trigger } = {}) {
    opener = trigger || document.activeElement;
    el.dataset.kind = `output-${o.kind}`;
    el.classList.add("is-output");
    document.body.classList.add("with-output");
    eyebrow.hidden = true;
    title.textContent = o.name;
    statusTag.textContent = status;
    statusTag.hidden = !status;
    line.textContent = OUT_LINES[o.kind] || "";
    line.hidden = !line.textContent;
    renderTools(controls);
    body.replaceChildren(...outputView(o, docUrl));
    el.hidden = false;
    card.scrollTop = 0;
    requestAnimationFrame(() => el.classList.add("is-in"));
    requestAnimationFrame(() => title.focus({ preventScroll: true }));
  }

  function renderTools(controls) {
    noteRow.hidden = true;
    noteRow.replaceChildren();
    tools.replaceChildren(...controls.map((c) => {
      const b = h("button", { class: "btn btn-quiet btn-sm", type: "button" }, c.icon ? icon(c.icon, 14) : null, h("span", null, c.label));
      b.addEventListener("click", async () => {
        if (c.note) return openNote(c);
        b.disabled = true;
        try {
          await c.onClick?.(b);
          close();
        } catch {
          /* the caller already said why (a toast) */
        } finally {
          b.disabled = false;
        }
      });
      return b;
    }));
    tools.hidden = !controls.length;
  }

  function openNote(c) {
    const input = h("input", { class: "input", type: "text", placeholder: c.placeholder || "A short note", "aria-label": "Your note", maxlength: 200 });
    const send = h("button", { class: "btn btn-ink btn-sm", type: "submit", disabled: true }, "Send");
    input.addEventListener("input", () => (send.disabled = !input.value.trim()));
    noteRow.replaceChildren(input, send);
    noteRow.hidden = false;
    noteRow.onsubmit = async (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) return;
      send.disabled = input.disabled = true;
      try {
        await c.onClick?.(send, v);
        noteRow.hidden = true;
        noteRow.replaceChildren();
      } catch {
        send.disabled = input.disabled = false;
      }
    };
    input.focus();
  }

  back.addEventListener("click", () => close());
  // a press anywhere outside the card closes it (and still does what it was for: the map, a sheet, another line)
  document.addEventListener(
    "pointerdown",
    (e) => {
      if (el.hidden || card.contains(e.target)) return;
      close({ restoreFocus: false });
    },
    true
  );
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "Escape" || el.hidden) return;
      e.stopImmediatePropagation(); // one Esc closes the panel only; the sheet under it stays open
      e.preventDefault();
      close();
    },
    true
  );

  return {
    el,
    open,
    openOutput,
    close,
    get isOpen() {
      return !el.hidden;
    },
  };
}

const OUT_LINES = { style: "Colours, type, buttons and the rules every builder follows.", research: "The sources it read, one line each." };

function outputView(o, docUrl) {
  const out = [];
  if (o.kind === "style") {
    if (o.look) out.push(h("p", { class: "dp-summary" }, o.look));
    if (o.palette?.length) {
      out.push(h("ul", { class: "dp-swatches", "aria-label": "Colours" }, o.palette.map((c) =>
        h("li", { class: "dp-swatch" }, h("span", { class: "dp-chip", style: { background: c.hex } }), h("span", { class: "dp-swatch-name" }, c.name), h("span", { class: "dp-swatch-hex tnum" }, c.hex.toUpperCase())))));
    }
    const pal = Object.fromEntries((o.palette || []).map((c) => [c.name.toLowerCase(), c.hex]));
    const fontH = o.fonts?.heading || "inherit", fontB = o.fonts?.body || "inherit";
    const radius = o.radius || "10px";
    const sample = h("div", { class: "dp-sample", style: { background: pal.background || pal.surface || "#fff", color: pal.text || "#111", fontFamily: fontB } },
      h("p", { class: "dp-sample-h", style: { fontFamily: fontH } }, "A heading in this look"),
      h("p", { class: "dp-sample-b" }, "Body text reads like this, in the body font."),
      h("div", { class: "dp-sample-row" },
        h("span", { class: "dp-sample-btn", style: { background: pal.primary || "#333", color: pal.background || "#fff", borderRadius: radius } }, "Main button"),
        h("span", { class: "dp-sample-btn", style: { background: pal.secondary || "transparent", color: pal.text || "#111", borderRadius: radius, border: `1px solid ${pal.muted || "rgba(0,0,0,.2)"}` } }, "Second button")));
    out.push(sample);
    if (o.fonts?.heading || o.fonts?.body) out.push(pair("Fonts", [o.fonts.heading && `Headings: ${firstFont(o.fonts.heading)}`, o.fonts.body && `Body: ${firstFont(o.fonts.body)}`].filter(Boolean).join(" · ")));
    if (o.rules?.length) out.push(h("div", { class: "dp-pair" }, h("p", { class: "dp-label" }, "Key rules"), h("ul", { class: "dp-rules" }, o.rules.map((t) => h("li", null, t)))));
  } else if (o.kind === "notes" || o.kind === "document") {
    if (o.markdown) out.push(h("article", { class: "doc dp-doc", html: renderMarkdown(o.markdown) }));
    else if (o.kind === "document" && docUrl) out.push(docFrom(docUrl));
    else if (o.points?.length) out.push(h("ol", { class: "dp-points" }, o.points.map((t) => h("li", null, t))));
    else out.push(h("p", { class: "dp-quiet" }, "This part kept its notes for the builders; there is nothing more to show."));
  } else if (o.kind === "research") {
    if (o.question) out.push(pair("Question", o.question));
    if (o.sources?.length) {
      out.push(h("ul", { class: "dp-sources" }, o.sources.map((x) =>
        h("li", null, h("a", { href: x.url, target: "_blank", rel: "noopener" }, x.label), x.note ? h("span", { class: "dp-source-note" }, x.note) : null))));
    } else out.push(h("p", { class: "dp-quiet" }, "No sources were recorded."));
  } else if (o.kind === "section" || o.kind === "page") {
    if (o.url) {
      const anchor = String(o.anchor || "").replace(/[^\w-]/g, "");
      out.push(h("iframe", { class: "dp-frame", title: `${o.name} on the page`, sandbox: "allow-scripts allow-popups allow-popups-to-escape-sandbox",
        loading: "eager", src: o.url + (anchor ? `#${anchor}` : "") }));
    } else out.push(h("p", { class: "dp-quiet" }, "The page shows up here once it has been put together."));
  }
  return out;
}

/** A document's text (older servers send no markdown with a document part): the whole document, rendered. */
function docFrom(url) {
  const box = h("article", { class: "doc dp-doc" }, h("p", { class: "dp-quiet" }, "Loading…"));
  fetch(url, { cache: "no-store" }).then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
    .then((t) => (box.innerHTML = renderMarkdown(t)))
    .catch(() => box.replaceChildren(h("p", { class: "dp-quiet" }, "This couldn't be loaded. Try again in a moment.")));
  return box;
}

const firstFont = (f) => String(f).split(",")[0].replace(/['"]/g, "").trim();

function render(kind, d) {
  const out = [];
  if (kind === "plan") out.push(...planView(d));
  else if (kind === "checks") out.push(...checksView(d));
  else if (kind === "budget") out.push(...budgetView(d));
  else if (kind === "decision") out.push(...decisionView(d));
  if (kind === "generic" && d.decided) out.push(pair("Decided", d.decided));
  if (d.why) out.push(pair("Why", d.why));
  if (!out.length) out.push(h("p", { class: "dp-quiet" }, "Nothing more to show for this one."));
  return out;
}

function pair(label, text) {
  return h("div", { class: "dp-pair" }, h("p", { class: "dp-label" }, label), h("p", { class: "dp-text" }, text));
}

/** The plan as what gets made and in what order: one count line (from the stages shown), each part's purpose whole,
 * and when it starts. No usage here (feedback 4). */
function planView(d) {
  const out = [];
  const stages = (d.stages || []).filter((s) => s.parts?.length);
  const n = stages.reduce((k, s) => k + s.parts.length, 0);
  if (n) out.push(h("p", { class: "dp-summary" }, `${n} part${n === 1 ? "" : "s"} in ${stages.length} stage${stages.length === 1 ? "" : "s"}.`));
  if (d.confidence) out.push(h("p", { class: "dp-note" }, d.confidence));
  for (const s of stages) {
    const rows = s.parts.map((p) => h("li", { class: "dp-part" },
      h("p", { class: "dp-part-name" }, p.name),
      p.purpose ? h("p", { class: "dp-part-purpose" }, p.purpose) : null,
      h("p", { class: "dp-part-meta" }, p.waits_for?.length ? `Waits for ${joinWords(p.waits_for)}` : "Starts first")));
    out.push(h("section", { class: "dp-stage" }, h("h3", { class: "dp-stage-name" }, s.name), h("ol", { class: "dp-parts" }, rows)));
  }
  if (d.not_ready?.length) out.push(pair("Not ready yet", joinWords(d.not_ready)));
  return out;
}

function checksView(d) {
  const out = [];
  if (d.what) out.push(h("p", { class: "dp-summary" }, d.what));
  if (d.summary) out.push(h("p", { class: "dp-note" }, d.summary));
  out.push(h("ul", { class: "dp-checks" }, (d.items || []).map((it) =>
    h("li", { class: `dp-check ${it.pass ? "is-pass" : "is-fail"}` },
      h("span", { class: "dp-mark", "aria-hidden": "true" }, markSvg(it.pass)),
      h("div", { class: "dp-check-body" },
        h("p", { class: "dp-check-name" }, h("span", { class: "sr-only" }, it.pass ? "Passed: " : "Failed: "), it.name),
        it.reason ? h("p", { class: "dp-check-reason" }, it.reason) : null)))));
  return out;
}

function budgetView(d) {
  const out = [];
  if (d.summary) out.push(h("p", { class: "dp-summary" }, d.summary));
  if (d.rows?.length) out.push(h("dl", { class: "dp-rows" }, d.rows.flatMap((r) => [h("dt", null, r.label), h("dd", { class: "tnum" }, r.value)])));
  return out;
}

function decisionView(d) {
  const out = [];
  if (d.asked) out.push(pair("Asked", d.asked));
  if (d.chosen) out.push(pair("Chosen", d.chosen));
  if (d.by) out.push(pair("Decided by", d.by));
  if (d.decided && d.decided !== d.chosen) out.push(pair("What it means", d.decided));
  return out;
}

function markSvg(ok) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 16 16");
  s.setAttribute("width", "16");
  s.setAttribute("height", "16");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", ok ? "M3.5 8.5l3 3 6-7" : "M4.5 4.5l7 7M11.5 4.5l-7 7");
  s.append(p);
  return s;
}

function joinWords(a) {
  const x = (a || []).filter(Boolean);
  if (x.length <= 1) return x.join("");
  return `${x.slice(0, -1).join(", ")} and ${x[x.length - 1]}`;
}
