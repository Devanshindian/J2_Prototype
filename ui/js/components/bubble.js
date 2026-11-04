// The tap bubble: what a node is, what it is doing in one plain line, its progress and usage, and one or two
// controls. Sits next to the node on a laptop; on a phone it is a bottom sheet. Esc or a tap elsewhere closes it.

import { h, icon } from "../dom.js";
import { fmtUsage, ratio } from "../format.js";

const isPhone = () => window.matchMedia("(max-width: 720px)").matches;
const MARGIN = 10;

export function createBubble({ container }) {
  const title = h("p", { class: "bub-title" });
  const sub = h("p", { class: "bub-sub" });
  const line = h("p", { class: "bub-line" });
  const meter = h("div", { class: "bub-meter", hidden: true }, h("span", { class: "bub-meter-fill" }));
  const meta = h("p", { class: "bub-meta tnum" });
  const actions = h("div", { class: "bub-actions" });
  const noteForm = h("form", { class: "bub-note", hidden: true });
  const closeBtn = h("button", { class: "icon-btn bub-close", type: "button", "aria-label": "Close" }, icon("close", 16));
  const arrow = h("span", { class: "bub-arrow", "aria-hidden": "true" });
  const el = h("section", { class: "kbub", role: "dialog", "aria-labelledby": "bub-title", "data-no-gesture": "", hidden: true }, arrow, closeBtn, title, sub, line, meter, meta, actions, noteForm);
  title.id = "bub-title";
  container.append(el);

  let current = null; // {id, kind}
  let onClose = null;

  function hide() {
    if (el.hidden) return;
    el.hidden = true;
    el.className = "kbub";
    current = null;
    onClose?.();
  }
  closeBtn.addEventListener("click", hide);

  /**
   * show({id, kind, title, sub, line, progress, used, share, controls: [{label, icon, kind, onClick, note}], anchor})
   * anchor: a DOMRect in viewport coordinates (the node). controls with `note: true` open a one-line note box.
   */
  function show(o) {
    current = { id: o.id, kind: o.kind };
    onClose = o.onClose || null;
    title.textContent = o.title || "";
    sub.textContent = o.sub || "";
    sub.hidden = !o.sub;
    line.textContent = o.line || "";
    line.hidden = !o.line;
    const hasMeter = typeof o.progress === "number";
    meter.hidden = !hasMeter;
    if (hasMeter) meter.firstChild.style.transform = `scaleX(${Math.max(0, Math.min(1, o.progress)).toFixed(3)})`;
    const bits = [];
    if (hasMeter) bits.push(`${Math.round(o.progress * 100)}%`);
    if (o.share) bits.push(`${fmtUsage(o.used || 0)} of ${fmtUsage(o.share)}`);
    else if (o.used) bits.push(`${fmtUsage(o.used)} used`);
    meta.textContent = bits.join(" · ");
    meta.hidden = !bits.length;
    noteForm.hidden = true;
    noteForm.replaceChildren();
    actions.replaceChildren(
      ...(o.controls || []).map((c) => {
        const b = h("button", { class: `btn btn-sm ${c.kind === "primary" ? "btn-ink" : "btn-quiet"}`, type: "button", title: c.title || null }, c.icon ? icon(c.icon, 15) : null, h("span", null, c.label));
        b.addEventListener("click", async () => {
          if (c.note) return openNote(c);
          b.disabled = true;
          try {
            await c.onClick?.(b);
          } catch {
            /* the caller already said why (a toast) */
          } finally {
            b.disabled = false;
          }
        });
        return b;
      })
    );
    actions.hidden = !(o.controls || []).length;
    el.hidden = false;
    el.className = `kbub kind-${o.kind || "node"}${isPhone() ? " is-sheet" : ""}`;
    if (!isPhone()) position(o.anchor);
    requestAnimationFrame(() => el.classList.add("is-in"));
    (actions.querySelector("button") || closeBtn).focus({ preventScroll: true });
  }

  function openNote(c) {
    const input = h("input", { class: "input", type: "text", placeholder: c.placeholder || "A short note for the planner", "aria-label": "Your note", maxlength: 200 });
    const send = h("button", { class: "btn btn-ink btn-sm", type: "submit", disabled: true }, "Send");
    input.addEventListener("input", () => (send.disabled = !input.value.trim()));
    noteForm.replaceChildren(input, send);
    noteForm.hidden = false;
    noteForm.onsubmit = async (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) return;
      send.disabled = true;
      input.disabled = true;
      try {
        await c.onClick?.(send, v);
        hide();
      } catch {
        send.disabled = false;
        input.disabled = false;
      }
    };
    input.focus();
  }

  /** Place the bubble beside the node: to the right when there is room, else left, else below; clamped to the map. */
  function position(anchor) {
    const box = container.getBoundingClientRect();
    if (!anchor) anchor = { left: box.left + box.width / 2, right: box.left + box.width / 2, top: box.top + box.height / 2, bottom: box.top + box.height / 2, width: 0, height: 0 };
    el.style.left = "0px";
    el.style.top = "0px";
    const w = el.offsetWidth, hgt = el.offsetHeight;
    const ax = anchor.left - box.left, ay = anchor.top - box.top;
    const aw = anchor.width, ah = anchor.height;
    let side = "right";
    let x = ax + aw + 14, y = ay + ah / 2 - hgt / 2;
    if (x + w > box.width - MARGIN) {
      side = "left";
      x = ax - 14 - w;
    }
    if (x < MARGIN) {
      side = "below";
      x = ax + aw / 2 - w / 2;
      y = ay + ah + 14;
    }
    x = Math.max(MARGIN, Math.min(box.width - w - MARGIN, x));
    y = Math.max(MARGIN, Math.min(box.height - hgt - MARGIN, y));
    el.style.left = `${Math.round(x)}px`;
    el.style.top = `${Math.round(y)}px`;
    el.dataset.side = side;
    // the little arrow points at the node
    const cx = ax + aw / 2 - x, cy = ay + ah / 2 - y;
    arrow.style.left = side === "below" ? `${Math.max(14, Math.min(w - 14, cx))}px` : side === "right" ? "-6px" : `${w - 6}px`;
    arrow.style.top = side === "below" ? "-6px" : `${Math.max(14, Math.min(hgt - 14, cy))}px`;
  }

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || el.hidden) return;
    hide();
    e.stopImmediatePropagation(); // one Esc closes the bubble only; the next one reaches the sheets and the mode
  });

  return {
    el,
    show,
    hide,
    get open() {
      return !el.hidden;
    },
    get current() {
      return current;
    },
  };
}
