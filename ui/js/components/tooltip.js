// The map's hover tooltip: point at a unit or a part (a mouse or trackpad; never on touch) and, after a short
// pause, a small card says what it is, what it is doing right now and, for a part, how far along it is. Keyboard
// focus on a node shows the same card. A click or tap still opens the full bubble with its controls.

import { h } from "../dom.js";

const DELAY = 250;
const GAP = 10;
const canHover = () => window.matchMedia("(hover: hover) and (pointer: fine)").matches;

export function createTooltip({ container, map, describe, nodeRect, blocked }) {
  const title = h("p", { class: "ktip-title" });
  const sub = h("p", { class: "ktip-sub" });
  const line = h("p", { class: "ktip-line" });
  const meta = h("p", { class: "ktip-meta tnum" });
  const el = h("div", { class: "ktip", id: "k-tip", role: "tooltip", hidden: true }, title, sub, line, meta);
  container.append(el);

  let timer = 0;
  let cur = null; // the node element shown (or waiting to show)

  function fill(d) {
    title.textContent = d.title || "";
    sub.textContent = d.sub || "";
    sub.hidden = !d.sub;
    line.textContent = d.line || "";
    line.hidden = !d.line;
    meta.textContent = d.meta || "";
    meta.hidden = !d.meta;
  }

  function place(g) {
    const box = container.getBoundingClientRect();
    const r = nodeRect(g.dataset.id) || g.getBoundingClientRect();
    el.style.left = "0px";
    el.style.top = "0px";
    const w = el.offsetWidth, hh = el.offsetHeight;
    let x = r.left - box.left + r.width / 2 - w / 2;
    let y = r.top - box.top - hh - GAP; // above the node, else below it
    if (y < 8) y = r.bottom - box.top + GAP;
    x = Math.max(8, Math.min(box.width - w - 8, x));
    y = Math.max(8, Math.min(box.height - hh - 8, y));
    el.style.left = `${Math.round(x)}px`;
    el.style.top = `${Math.round(y)}px`;
  }

  function show(g) {
    if (!g || !document.contains(g) || blocked?.(g)) return;
    const d = describe(g.dataset.id);
    if (!d) return;
    fill(d);
    el.hidden = false;
    place(g);
    g.setAttribute("aria-describedby", "k-tip");
    requestAnimationFrame(() => el.classList.add("is-in"));
  }

  function hide() {
    clearTimeout(timer);
    timer = 0;
    if (cur) cur.removeAttribute("aria-describedby");
    cur = null;
    if (el.hidden) return;
    el.hidden = true;
    el.classList.remove("is-in");
  }

  function later(g) {
    clearTimeout(timer);
    cur = g;
    timer = setTimeout(() => cur === g && show(g), DELAY);
  }

  const nodeOf = (t) => {
    const g = t?.closest?.(".k-node");
    return g && (g.dataset.kind === "unit" || g.dataset.kind === "bld") ? g : null;
  };

  map.addEventListener("pointerover", (e) => {
    if (e.pointerType !== "mouse" || !canHover()) return;
    const g = nodeOf(e.target);
    if (!g) return hide();
    if (g === cur) return;
    hide();
    later(g);
  });
  map.addEventListener("pointerout", (e) => {
    if (e.pointerType !== "mouse") return;
    const g = nodeOf(e.target);
    if (g && g === cur && !g.contains(e.relatedTarget)) hide();
  });
  // a press (tap, pan, the hold-and-slide gesture), a wheel zoom or leaving the map ends the hint
  map.addEventListener("pointerdown", hide);
  map.addEventListener("wheel", hide, { passive: true });
  map.addEventListener("pointerleave", hide);
  map.addEventListener("focusin", (e) => {
    const g = nodeOf(e.target);
    if (!g) return;
    hide();
    cur = g;
    show(g);
  });
  map.addEventListener("focusout", (e) => {
    if (nodeOf(e.target) === cur) hide();
  });

  return {
    el,
    hide,
    /** Keep the card on its node (and its words fresh) between polls. */
    refresh() {
      if (!cur || el.hidden) return;
      if (!document.contains(cur)) return hide();
      const d = describe(cur.dataset.id);
      if (!d) return hide();
      fill(d);
      place(cur);
    },
    get open() {
      return !el.hidden;
    },
  };
}
