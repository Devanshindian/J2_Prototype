// The top-bar status: one dot and one word. What is happening right now lives above the composer.

import { h } from "../dom.js";
import { STATUS, statusWord, statusShort } from "../format.js";

export function createStatus() {
  const dot = h("span", { class: "dot", "aria-hidden": "true" });
  const long = h("span", { class: "sw-long" });
  const short = h("span", { class: "sw-short" });
  const word = h("span", { class: "status-word", role: "status", "aria-live": "polite" }, long, short);
  const el = h("div", { class: "status" }, dot, word);

  let last = "";
  function update({ status, ended, connection, sending, control, status_text }) {
    let st = status || "idle";
    if (sending && st === "idle") st = "working";
    const lost = connection === "lost";
    const tone = lost ? "idle" : (STATUS[st] || STATUS.idle).tone;
    // a pause or stop asked for lands between turns, and a real builder turn can take minutes: say so in the word
    // the backend's own line says when it lands ("Pausing after this step…"); the phone keeps the short word
    const askedShort = st === "working" && (control?.stopping ? "Stopping…" : control?.pausing ? "Pausing…" : "");
    const asked = askedShort && (/^(Pausing|Stopping)\b/.test(status_text || "") ? status_text : askedShort);
    const w = lost ? "Reconnecting" : asked || statusWord(st, ended);
    const doing = st === "working" && !asked && !lost ? String(status_text || "").replace(/[\s.…]+$/u, "") : "";
    const wl = doing && doing.toLowerCase() !== String(w).toLowerCase() ? `${w} · ${doing}` : w;
    const ws = lost ? w : askedShort || statusShort(st, ended);
    const key = `${tone}|${wl}`;
    if (key === last) return;
    last = key;
    el.dataset.tone = tone;
    long.textContent = wl;
    short.textContent = ws;
  }
  return { el, update };
}
