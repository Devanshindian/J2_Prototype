// The Plan sheet: one plain row per part, grouped under quiet stage headings.
// Rows are keyed by task id and patched in place, so a poll that only moves a usage bar
// animates the bar instead of repainting the list.

import { h } from "../dom.js";
import { TASK_STATUS, usageText } from "../format.js";
import { createSheet } from "./sheet.js";
import { createUsageBar } from "./usagebar.js";

export function createPlanSheet({ onClose } = {}) {
  const sheet = createSheet({ id: "plan-sheet", title: "Plan", cls: "sheet-plan", onClose });
  // Total usage, shown here only on very narrow screens where the top bar has no room for it.
  const usageEl = h("span", { class: "sheet-usage tnum" });
  sheet.sub.after(usageEl);

  const rows = new Map(); // task id -> row handle
  let shapeKey = ""; // groups and the order of their tasks

  function update(plan, workingNow, usage) {
    usageEl.textContent = usageText(usage);

    const groups = plan?.groups?.filter((g) => g.tasks?.length) || [];
    const all = groups.flatMap((g) => g.tasks);
    const done = all.filter((t) => t.status === "done").length;
    const subText = all.length ? `${done} of ${all.length} done` : "";
    if (sheet.sub.textContent !== subText) sheet.sub.textContent = subText;

    const key = groups.map((g) => `${g.name}:${g.tasks.map((t) => t.id).join(",")}`).join("|");
    if (key !== shapeKey) {
      shapeKey = key;
      rebuild(groups);
    }
    for (const t of all) rows.get(t.id)?.patch(t, workingNow?.task_id === t.id);
  }

  function rebuild(groups) {
    const scroll = sheet.body.scrollTop;
    const keep = new Set(groups.flatMap((g) => g.tasks.map((t) => t.id)));
    for (const id of [...rows.keys()]) if (!keep.has(id)) rows.delete(id);
    sheet.body.replaceChildren();
    if (!groups.length) {
      sheet.body.append(h("p", { class: "empty" }, "The plan shows up here once it's ready."));
      return;
    }
    for (const g of groups) {
      const gid = `pg-${g.name.replace(/\W+/g, "-").toLowerCase()}`;
      const list = h("ul", { class: "plan-list" });
      for (const t of g.tasks) {
        let r = rows.get(t.id);
        if (!r) {
          r = row();
          rows.set(t.id, r);
        }
        list.append(r.el);
      }
      sheet.body.append(h("section", { class: "plan-group", "aria-labelledby": gid }, h("h3", { class: "plan-group-name", id: gid }, g.name), list));
    }
    sheet.body.scrollTop = scroll;
  }

  return Object.assign(sheet, { update });
}

function row() {
  const name = h("span", { class: "task-name" });
  const statusWord = document.createTextNode("");
  const status = h("span", { class: "task-status" }, h("span", { class: "dot", "aria-hidden": "true" }), statusWord);
  const summary = h("p", { class: "task-summary", hidden: true });
  const waits = h("p", { class: "task-waits", hidden: true });
  const bar = createUsageBar({ size: "xs", name: "usage" });
  bar.el.hidden = true;
  const el = h("li", { class: "task" }, h("div", { class: "task-top" }, name, status), summary, waits, bar.el);

  let last = "";
  function patch(t, isNow) {
    const st = t.status || "waiting";
    const key = JSON.stringify([t.name, t.summary, st, t.waits_for, t.usage, t.share, isNow]);
    if (key === last) return;
    last = key;
    setText(name, t.name);
    el.className = `task st-${st}${isNow ? " is-now" : ""}`;
    setText(statusWord, TASK_STATUS[st] || st);
    summary.hidden = !t.summary;
    setText(summary, t.summary || "");
    const w = t.waits_for?.length && st !== "done" ? `Waits for: ${t.waits_for.join(", ")}` : "";
    waits.hidden = !w;
    setText(waits, w);
    bar.el.hidden = !t.share;
    bar.el.setAttribute("aria-label", `${t.name} usage`);
    bar.update({ used: t.usage || 0, total: t.share || 0 });
  }
  return { el, patch };
}

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}
