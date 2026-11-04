// The Result panel: one tab per deliverable. Live preview for the website, rendered markdown for documents. On a
// laptop it opens as a large centred panel over a softened map (a click outside, Esc or Result again closes it).

import { h, icon } from "../dom.js";
import { DELIVERABLE_LABEL } from "../format.js";
import { renderMarkdown } from "../markdown.js";
import { createSheet } from "./sheet.js";

const STATE_WORD = { todo: "Not started", working: "Draft", draft: "Draft", done: "" };
const withVersion = (url, v) => (v == null ? url : `${url}${url.includes("?") ? "&" : "?"}_v=${encodeURIComponent(v)}`);

export function createResultPanel({ onClose } = {}) {
  const sheet = createSheet({ id: "result-panel", title: "Result", cls: "sheet-result", onClose });

  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Things made" });
  const stateTag = h("span", { class: "tag tag-draft", hidden: true }, "Draft");
  const versionEl = h("span", { class: "result-version tnum" });
  const fullBtn = h("a", { class: "btn btn-quiet btn-sm", target: "_blank", rel: "noopener" }, icon("external", 16), h("span", null, "Open full screen"));
  const expandBtn = h("button", { class: "btn btn-quiet btn-sm", type: "button", "aria-pressed": "false" }, icon("expand", 16), h("span", null, "Full screen"));
  const dlBtn = h("a", { class: "btn btn-quiet btn-sm", download: "" }, icon("download", 16), h("span", null, "Download"));
  const bar = h("div", { class: "result-bar" }, h("div", { class: "result-meta" }, stateTag, versionEl), h("div", { class: "result-actions" }, fullBtn, expandBtn, dlBtn));
  const view = h("div", { class: "result-view", role: "tabpanel", id: "result-view", tabindex: "0" });
  sheet.body.append(tabs, bar, view);
  sheet.body.classList.add("result-body");

  expandBtn.addEventListener("click", () => {
    const on = !sheet.el.classList.contains("is-expanded");
    sheet.el.classList.toggle("is-expanded", on);
    expandBtn.setAttribute("aria-pressed", String(on));
    expandBtn.replaceChildren(icon(on ? "collapse" : "expand", 16), h("span", null, on ? "Exit full screen" : "Full screen"));
  });

  let items = [];
  let selected = null;
  let picked = false;        // the person chose this tab: it stays, even when it is empty
  let tabsKey = "";
  let viewKey = "";
  let docCache = new Map();
  let hash = ""; // a section of the page to show ("See output" on a built part)

  function pickDefault() {
    // keep the person's tab, unless it shows nothing while another deliverable has something (a live documents run
    // opened its Result on an unstarted Website tab, past a finished PRD and HLD)
    const has = (d) => d.state !== "todo";
    if (selected && items.some((d) => d.kind === selected && (picked || has(d) || !items.some(has)))) return;
    const ready = items.find((d) => has(d) && d.kind === "website") || [...items].reverse().find(has) || items[0];
    selected = ready?.kind || null;
  }

  function renderTabs() {
    const key = JSON.stringify(items.map((d) => [d.kind, d.label, d.state, selected]));
    if (key === tabsKey) return;
    tabsKey = key;
    tabs.replaceChildren();
    tabs.hidden = items.length < 2;
    for (const d of items) {
      const on = d.kind === selected;
      const t = h(
        "button",
        { class: "tab", role: "tab", type: "button", id: `tab-${d.kind}`, "aria-selected": String(on), "aria-controls": "result-view", tabindex: on ? "0" : "-1" },
        d.label || DELIVERABLE_LABEL[d.kind] || d.kind,
        d.state !== "done" ? h("span", { class: `tab-state st-${d.state}`, "aria-label": STATE_WORD[d.state] || d.state }) : null
      );
      t.addEventListener("click", () => select(d.kind));
      tabs.append(t);
    }
    view.setAttribute("aria-labelledby", selected ? `tab-${selected}` : "");
  }

  tabs.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    const i = items.findIndex((d) => d.kind === selected);
    let n = i;
    if (e.key === "ArrowRight") n = (i + 1) % items.length;
    if (e.key === "ArrowLeft") n = (i - 1 + items.length) % items.length;
    if (e.key === "Home") n = 0;
    if (e.key === "End") n = items.length - 1;
    e.preventDefault();
    select(items[n].kind);
    tabs.querySelector(`#tab-${items[n].kind}`)?.focus();
  });

  function select(kind) {
    selected = kind;
    picked = true;
    render();
  }

  function render() {
    renderTabs();
    const d = items.find((x) => x.kind === selected);
    const draft = d && d.state !== "done";
    stateTag.hidden = !draft;
    stateTag.textContent = d ? STATE_WORD[d.state] || "Draft" : "";
    versionEl.textContent = d?.version ? `Version ${d.version}` : "";
    bar.hidden = !d;

    const isSite = d?.kind === "website";
    fullBtn.hidden = !isSite || !d?.url;
    if (d?.url) fullBtn.href = d.url;
    expandBtn.hidden = isSite || !d?.url;
    dlBtn.hidden = !d?.download;
    if (d?.download) dlBtn.href = d.download;

    const key = d ? `${d.kind}|${d.url}|${d.version}|${d.state}` : "none";
    if (key === viewKey) return;
    const sameDoc = viewKey.split("|")[0] === d?.kind;
    viewKey = key;

    if (!d) return showEmpty("Results show up here as they're made.");
    if (!d.url) return showEmpty(d.state === "todo" ? "Not started yet." : "Being made. It shows up here soon.");
    if (isSite) return showSite(d, sameDoc);
    return showDoc(d, sameDoc);
  }

  function showEmpty(text) {
    view.className = "result-view is-empty";
    view.replaceChildren(h("p", { class: "empty" }, text));
  }

  // Website: load the new version in a hidden frame on top of the old one, fade it in once it has
  // loaded, and only then drop the old frame. The preview never flashes blank between versions.
  function showSite(d, sameDoc) {
    view.className = "result-view is-site";
    const src = withVersion(d.url, d.version) + (hash ? `#${hash}` : "");
    const frame = h("iframe", {
      class: "site-frame is-loading",
      title: `${d.label || "Website"} preview`,
      sandbox: "allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox",
      loading: "eager",
      src,
    });
    const old = sameDoc ? [...view.querySelectorAll("iframe")] : [];
    if (!sameDoc) view.replaceChildren();
    let shown = false;
    const reveal = () => {
      if (shown) return;
      shown = true;
      frame.classList.remove("is-loading");
      // the fade is --t-slow (260ms); remove the old frame once the new one is fully opaque
      setTimeout(() => old.forEach((f) => f.remove()), 320);
    };
    frame.addEventListener("load", reveal);
    setTimeout(reveal, 4000); // never stay invisible if load never fires
    view.append(frame);
  }

  async function showDoc(d, sameDoc) {
    view.className = "result-view is-doc";
    const myKey = viewKey;
    const scroll = sameDoc ? view.scrollTop : 0;
    if (!sameDoc) view.replaceChildren(h("p", { class: "empty" }, "Loading…"));
    try {
      const ck = `${d.url}|${d.version}`;
      let text = docCache.get(ck);
      if (text == null) {
        const res = await fetch(withVersion(d.url, d.version), { cache: "no-store" });
        if (!res.ok) throw new Error(res.status);
        text = await res.text();
        docCache.set(ck, text);
      }
      if (myKey !== viewKey) return;
      if (/^\s*(<!doctype|<html)/i.test(text)) {
        // The server sent HTML rather than markdown: show it framed, unscripted.
        view.replaceChildren(h("iframe", { class: "site-frame", title: d.label, sandbox: "", src: withVersion(d.url, d.version) }));
        return;
      }
      const article = h("article", { class: "doc", html: renderMarkdown(text) });
      view.replaceChildren(article);
      view.scrollTop = scroll;
    } catch {
      if (myKey === viewKey) showEmpty("This couldn't be loaded. It will try again on the next update.");
      viewKey = "";
    }
  }

  function update(deliverables) {
    items = (deliverables || []).filter(Boolean);
    pickDefault();
    render();
  }

  /** Show the website scrolled to one section (a built part's output). */
  function showSection(id) {
    hash = String(id || "").replace(/[^\w-]/g, "");
    selected = "website";
    picked = true;
    const f = view.querySelector("iframe.site-frame:last-child");
    if (f && viewKey.startsWith("website|")) {
      f.src = f.src.split("#")[0] + (hash ? `#${hash}` : ""); // only the fragment changes: the page scrolls there
      renderTabs();
      return;
    }
    viewKey = "";
    render();
  }

  return Object.assign(sheet, { update, select, showSection, hasContent: () => items.some((d) => d.url) });
}
