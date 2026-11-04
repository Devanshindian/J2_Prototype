// A thin usage bar: used of budget, with an optional safety-margin tick.

import { h } from "../dom.js";
import { fmtUsage, ratio } from "../format.js";

/**
 * createUsageBar({label: true|false, size: "sm"|"xs"})
 * Returns {el, update({used, total, margin})}.
 */
export function createUsageBar({ label = true, size = "sm", name = "Usage" } = {}) {
  const fill = h("span", { class: "ubar-fill" });
  const tick = h("span", { class: "ubar-tick", hidden: true });
  const track = h("span", { class: "ubar-track" }, fill, tick);
  const text = label ? h("span", { class: "ubar-label tnum" }) : null;
  const el = h("span", { class: `ubar ubar-${size}`, role: "meter", "aria-label": name, "aria-valuemin": 0 }, track, text);

  function update({ used = 0, total = 0, margin = null } = {}) {
    const r = ratio(used, total);
    fill.style.setProperty("--r", r.toFixed(4)); // scaleX, so growth is a transform (no layout)
    el.classList.toggle("is-over", !!margin && used >= margin);
    el.classList.toggle("is-empty", !total);
    if (margin && total) {
      tick.hidden = false;
      tick.style.left = `${(ratio(margin, total) * 100).toFixed(2)}%`;
    } else tick.hidden = true;
    const words = total ? `${fmtUsage(used)} of ${fmtUsage(total)}` : used ? `${fmtUsage(used)} used` : "";
    if (text) text.textContent = words;
    el.setAttribute("aria-valuemax", total || 0);
    el.setAttribute("aria-valuenow", Math.min(used || 0, total || 0));
    el.setAttribute("aria-valuetext", words || "Not started");
  }

  return { el, update };
}
