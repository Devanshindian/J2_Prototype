// A side sheet that slides in from the right (a full-height sheet on phones, where its header is
// also a drag handle: swipe down to dismiss). Closed sheets are inert, so they never take focus.
// Focus returns to the opener on close.

import { h, icon } from "../dom.js";

const DISMISS_PX = 110; // drag further than this and the sheet closes
const DISMISS_V = 0.6; // or fling it faster than this (px per ms)
const isPhone = () => window.matchMedia("(max-width: 720px)").matches;

export function createSheet({ id, title, cls = "", onClose }) {
  const titleEl = h("h2", { class: "sheet-title", id: `${id}-title`, tabindex: "-1" }, title);
  const sub = h("span", { class: "sheet-sub tnum" });
  const extra = h("div", { class: "sheet-tools" });
  const closeBtn = h("button", { class: "icon-btn", type: "button", "aria-label": `Close ${title.toLowerCase()}` }, icon("close"));
  const grip = h("span", { class: "sheet-grip", "aria-hidden": "true" });
  const head = h("header", { class: "sheet-head" }, grip, h("div", { class: "sheet-heading" }, titleEl, sub), extra, closeBtn);
  const body = h("div", { class: "sheet-body" });
  const el = h("aside", { class: `sheet ${cls}`, id, role: "dialog", "aria-labelledby": `${id}-title`, inert: true, "aria-hidden": "true" }, head, body);

  let opener = null;
  const api = {
    el,
    body,
    head,
    tools: extra,
    sub,
    isOpen: false,
    open(trigger) {
      if (api.isOpen) return;
      opener = trigger || document.activeElement;
      api.isOpen = true;
      el.inert = false;
      el.removeAttribute("aria-hidden");
      el.classList.add("is-open");
      requestAnimationFrame(() => titleEl.focus({ preventScroll: true }));
    },
    close({ restoreFocus = true } = {}) {
      if (!api.isOpen) return;
      api.isOpen = false;
      el.classList.remove("is-open");
      el.inert = true;
      el.setAttribute("aria-hidden", "true");
      if (restoreFocus && opener && document.contains(opener)) opener.focus({ preventScroll: true });
      onClose?.();
    },
  };
  closeBtn.addEventListener("click", () => api.close());
  attachSwipeDown(el, head, api);
  return api;
}

/* Phones: drag the header down. The sheet follows the finger (rAF), then either closes or springs back. */
function attachSwipeDown(el, head, api) {
  let pid = null;
  let y0 = 0;
  let t0 = 0;
  let dy = 0;
  let raf = 0;

  head.addEventListener("pointerdown", (e) => {
    if (!isPhone() || !api.isOpen || pid != null || !e.isPrimary) return;
    // a tap on a control is not a drag: with the pointer captured, the label's click would land on the head
    if (e.target.closest("button, a, input, label")) return;
    pid = e.pointerId;
    y0 = e.clientY;
    t0 = e.timeStamp;
    dy = 0;
    try {
      head.setPointerCapture(pid);
    } catch {
      /* pointer already gone */
    }
    el.classList.add("is-dragging");
  });

  head.addEventListener("pointermove", (e) => {
    if (e.pointerId !== pid) return;
    dy = Math.max(0, e.clientY - y0);
    if (!raf) raf = requestAnimationFrame(apply);
  });

  function apply() {
    raf = 0;
    if (pid == null) return;
    el.style.transform = `translateY(${dy}px)`;
  }

  function end(e) {
    if (e.pointerId !== pid) return;
    pid = null;
    cancelAnimationFrame(raf);
    raf = 0;
    el.classList.remove("is-dragging");
    el.style.transform = "";
    const elapsed = e.timeStamp - t0;
    const v = elapsed > 50 ? dy / elapsed : 0; // a fling: a real swipe, not a jittery tap
    if (dy > DISMISS_PX || (v > DISMISS_V && dy > 24)) api.close();
  }
  head.addEventListener("pointerup", end);
  head.addEventListener("pointercancel", end);
}
