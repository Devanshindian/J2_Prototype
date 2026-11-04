// The first-run coach mark: three steps, once, then never again (localStorage). Each step rings a spot on the map
// and says one short line. "Next" moves on; "Got it" or Esc ends it.

import { h } from "../dom.js";

const KEY = "j2-kingdom-coach";

export function coachSeen() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return true; // no storage: never nag
  }
}

export function markCoachSeen() {
  try {
    localStorage.setItem(KEY, "1");
  } catch {
    /* fine */
  }
}

/**
 * showCoach(container, steps, onDone)
 * steps: [{text, rect: () => DOMRect | null}] (rects in viewport coordinates; the ring is placed over them).
 */
export function showCoach(container, steps, onDone) {
  const ring = h("span", { class: "coach-ring", "aria-hidden": "true" });
  const text = h("p", { class: "coach-text", id: "coach-text" });
  const count = h("span", { class: "coach-count tnum", "aria-hidden": "true" });
  const next = h("button", { class: "btn btn-ink btn-sm", type: "button" }, "Next");
  const skip = h("button", { class: "btn btn-quiet btn-sm", type: "button" }, "Skip");
  const card = h("div", { class: "coach-card", role: "dialog", "aria-labelledby": "coach-text" }, text, h("div", { class: "coach-row" }, count, skip, next));
  const el = h("div", { class: "coach", "data-no-gesture": "" }, ring, card);
  container.append(el);
  let i = 0;

  function place() {
    const s = steps[i];
    const box = container.getBoundingClientRect();
    const r = s.rect?.();
    text.textContent = s.text;
    count.textContent = `${i + 1} / ${steps.length}`;
    next.textContent = i === steps.length - 1 ? "Got it" : "Next";
    skip.hidden = i === steps.length - 1;
    if (r && r.width) {
      const pad = 14;
      ring.hidden = false;
      ring.style.left = `${r.left - box.left - pad}px`;
      ring.style.top = `${r.top - box.top - pad}px`;
      ring.style.width = `${r.width + pad * 2}px`;
      ring.style.height = `${r.height + pad * 2}px`;
      // the card sits under the ring, or above it when there is no room
      const cw = card.offsetWidth || 300, ch = card.offsetHeight || 120;
      let x = r.left - box.left + r.width / 2 - cw / 2;
      let y = r.bottom - box.top + pad + 12;
      if (y + ch > box.height - 12) y = r.top - box.top - pad - 12 - ch;
      x = Math.max(12, Math.min(box.width - cw - 12, x));
      y = Math.max(12, y);
      card.style.left = `${x}px`;
      card.style.top = `${y}px`;
    } else {
      ring.hidden = true;
      card.style.left = `${Math.max(12, box.width / 2 - (card.offsetWidth || 300) / 2)}px`;
      card.style.top = `${Math.max(12, box.height / 2 - 60)}px`;
    }
    next.focus({ preventScroll: true });
  }

  function done() {
    markCoachSeen();
    el.classList.add("is-out");
    setTimeout(() => el.remove(), 220);
    document.removeEventListener("keydown", onKey);
    onDone?.();
  }
  function onKey(e) {
    if (e.key === "Escape") done();
  }
  next.addEventListener("click", () => {
    if (i >= steps.length - 1) return done();
    i++;
    place();
  });
  skip.addEventListener("click", done);
  document.addEventListener("keydown", onKey);
  requestAnimationFrame(() => {
    el.classList.add("is-in");
    place();
  });
  return { el, done, step: () => i };
}
