// Hold-and-slide to look behind the chat.
//
//   press            a small ring appears under the pointer and fills over the hold (~450ms)
//   hold completes   a pill appears: "Slide to look behind →" with a thumb under the pointer
//   slide right      the thumb follows the pointer (slight resistance) and the backstage sharpens
//                    in step with the distance (a scrub, not a switch)
//   cross ~60px      snaps to locked; release before that springs back
//
// Pointer events, so mouse, pen and touch all work. It never starts on text, buttons, inputs or
// links, and it cancels if the pointer moves first (scrolling), if text gets selected, or if the
// browser takes the pointer away (pointercancel). All visual follow-through runs on rAF.

import { h, icon } from "../dom.js";

const HOLD_MS = 450;
const SLIDE_PX = 60;
const MOVE_TOLERANCE = 8; // px of travel before the hold completes = the user is scrolling
const TOUCH_LIFT = 64; // px above a finger, so the finger never covers the ring or pill
const RESIST = 0.9; // the thumb trails the pointer a little before the snap
const NOT_EMPTY = ".bubble, .card, .ending, button, a, input, textarea, select, label, [data-no-gesture], [contenteditable]";
const RING_R = 17;
const RING_C = (2 * Math.PI * RING_R).toFixed(2);

export function attachLockGesture(area, { onPress, onArm, onProgress, onLock, onCancel, enabled = () => true, hint: hintText = () => "Slide to look behind", notEmpty = NOT_EMPTY } = {}) {
  // the hold ring
  const arc = svgEl("circle", { class: "hold-ring-arc", cx: 20, cy: 20, r: RING_R, "stroke-dasharray": RING_C, "stroke-dashoffset": RING_C });
  const ring = h("div", { class: "hold-ring", "aria-hidden": "true", hidden: true });
  ring.append(svgEl("svg", { viewBox: "0 0 40 40", width: 40, height: 40 }, svgEl("circle", { class: "hold-ring-bg", cx: 20, cy: 20, r: RING_R }), arc));
  ring.style.setProperty("--hold-ms", `${HOLD_MS}ms`);

  // the slide pill
  const knob = h("span", { class: "lock-knob" }, icon("eye", 18));
  const hintLabel = h("span", null, hintText());
  const hint = h("span", { class: "lock-hint" }, hintLabel, icon("arrow", 14));
  const handle = h("div", { class: "lock-handle", "aria-hidden": "true", hidden: true }, h("span", { class: "lock-track" }, hint), knob);
  document.body.append(ring, handle);

  let state = "idle"; // idle | pressing | armed | settling
  let timer = null;
  let hideTimer = null;
  let raf = 0;
  let pid = null;
  let x0 = 0;
  let y0 = 0;
  let dx = 0;
  let lift = 0;

  function cleanPointer() {
    clearTimeout(timer);
    timer = null;
    cancelAnimationFrame(raf);
    raf = 0;
    if (pid != null && area.hasPointerCapture?.(pid)) area.releasePointerCapture(pid);
    document.body.classList.remove("is-gesturing");
    document.body.classList.remove("is-pressing");
  }

  function hideRing() {
    ring.hidden = true;
    ring.classList.remove("is-filling");
  }

  function hideHandle(delay = 0) {
    clearTimeout(hideTimer);
    const done = () => {
      handle.hidden = true;
      handle.className = "lock-handle";
      handle.style.setProperty("--x", "0px");
      handle.style.setProperty("--p", "0");
      state = state === "settling" ? "idle" : state;
      pid = state === "idle" ? null : pid;
    };
    if (delay) hideTimer = setTimeout(done, delay);
    else done();
  }

  function idle() {
    cleanPointer();
    hideRing();
    hideHandle();
    state = "idle";
    pid = null;
  }

  /* ---- press ---- */
  area.addEventListener("pointerdown", (e) => {
    if (!enabled() || state !== "idle" || !e.isPrimary) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (e.target.closest(notEmpty)) return;
    if (e.pointerType === "mouse" && e.offsetX > area.clientWidth) return; // the scrollbar
    const sel = window.getSelection?.();
    if (sel && !sel.isCollapsed) return;

    state = "pressing";
    pid = e.pointerId;
    x0 = e.clientX;
    y0 = e.clientY;
    dx = 0;
    lift = e.pointerType === "touch" ? TOUCH_LIFT : 0;

    ring.style.left = `${x0}px`;
    ring.style.top = `${y0 - lift}px`;
    ring.hidden = false;
    ring.classList.remove("is-filling");
    void ring.offsetWidth; // restart the fill from zero
    ring.classList.add("is-filling");
    // from the first press no text is selected under the moving pointer (the map's labels went blue in a real browser)
    document.body.classList.add("is-pressing");
    onPress?.();
    timer = setTimeout(arm, HOLD_MS);
  });

  /* ---- hold complete ---- */
  function arm() {
    if (state !== "pressing") return;
    const sel = window.getSelection?.();
    if (sel && !sel.isCollapsed) return idle(); // the user is selecting text
    state = "armed";
    try {
      area.setPointerCapture(pid);
    } catch {
      /* pointer already gone */
    }
    document.body.classList.add("is-gesturing");
    hideRing();

    hintLabel.textContent = hintText();
    handle.hidden = false;
    handle.className = "lock-handle is-live";
    handle.style.setProperty("--x", "0px");
    handle.style.setProperty("--p", "0");
    // the thumb sits under the pointer; keep the whole pill on screen
    const w = handle.offsetWidth || 240;
    const left = Math.min(x0, window.innerWidth - 8 - w + 22);
    handle.style.left = `${Math.max(8 + 22, left)}px`;
    handle.style.top = `${y0 - lift}px`;

    navigator.vibrate?.(8);
    onArm?.();
  }

  /* ---- slide ---- */
  area.addEventListener("pointermove", (e) => {
    if (e.pointerId !== pid) return;
    if (state === "pressing") {
      if (Math.hypot(e.clientX - x0, e.clientY - y0) > MOVE_TOLERANCE) idle();
      return;
    }
    if (state !== "armed") return;
    dx = e.clientX - x0;
    if (!raf) raf = requestAnimationFrame(frame);
  });

  function frame() {
    raf = 0;
    if (state !== "armed") return;
    const p = Math.max(0, Math.min(1, dx / SLIDE_PX));
    handle.style.setProperty("--x", `${thumbX(dx)}px`);
    handle.style.setProperty("--p", p.toFixed(3));
    onProgress?.(p);
    if (dx >= SLIDE_PX) snap();
  }

  function thumbX(d) {
    if (d < 0) return -Math.min(10, Math.sqrt(-d) * 1.6); // a little give when pulled the wrong way
    if (d <= SLIDE_PX) return d * RESIST;
    return SLIDE_PX + (d - SLIDE_PX) * 0.15; // past the end: rubber band
  }

  /* ---- crossed the line: lock ---- */
  function snap() {
    state = "settling";
    cleanPointer();
    handle.className = "lock-handle is-live is-snapped";
    handle.style.setProperty("--x", `${SLIDE_PX}px`);
    handle.style.setProperty("--p", "1");
    navigator.vibrate?.(12);
    onLock?.();
    hideHandle(260);
  }

  /* ---- let go early: spring back ---- */
  function release() {
    state = "settling";
    cleanPointer();
    handle.className = "lock-handle is-live is-returning";
    handle.style.setProperty("--x", "0px");
    handle.style.setProperty("--p", "0");
    onCancel?.();
    hideHandle(220);
  }

  const end = (e) => {
    if (e.pointerId !== pid) return;
    if (state === "pressing") return idle();
    if (state === "armed") {
      if (e.type === "pointerup" && e.clientX - x0 >= SLIDE_PX) return snap(); // a fast flick past the line
      return release();
    }
    if (state === "settling") pid = null; // the pill is fading out on its own
  };
  area.addEventListener("pointerup", end);
  area.addEventListener("pointercancel", end);
  // only the area's own capture matters: a child (the map's svg) losing its capture to the area is not an end
  area.addEventListener("lostpointercapture", (e) => e.target === area && state === "armed" && end(e));

  // Anything that steals the interaction cancels it cleanly.
  const cancelIfActive = () => (state === "pressing" ? idle() : state === "armed" ? release() : null);
  window.addEventListener("blur", cancelIfActive);
  document.addEventListener("visibilitychange", () => document.hidden && cancelIfActive());
  area.addEventListener("wheel", cancelIfActive, { passive: true });
  document.addEventListener("keydown", (e) => e.key === "Escape" && cancelIfActive());
  area.addEventListener("contextmenu", (e) => state !== "idle" && e.preventDefault());

  return { cancel: cancelIfActive };
}

function svgEl(tag, attrs, ...children) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, String(v));
  el.append(...children);
  return el;
}
