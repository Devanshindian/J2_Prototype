// The backstage: the agents talking to each other in plain words, newest at the bottom, plus what is
// being built right now (every builder at work, each with its own usage bar). Sits behind the chat,
// blurred, until locked open. A line with more behind it says "See details": a tap (or Enter) opens the centre
// panel (detailpanel.js) with what is really happening, in plain words.

import { h } from "../dom.js";
import { createUsageBar } from "./usagebar.js";

const MAX_LINES = 120;

export function createBackstage({ onDetails } = {}) {
  const title = h("h2", { class: "bs-title", id: "bs-title", tabindex: "-1" }, "Behind the scenes");
  const lines = h("ol", { class: "bs-lines", "aria-labelledby": "bs-title" });
  const scroller = h("div", { class: "bs-scroll" }, lines);
  const nowLabel = h("span", { class: "bs-now-label" }, "Now");
  const nowList = h("ul", { class: "bs-now-list" });
  const now = h("div", { class: "bs-now", hidden: true }, nowLabel, nowList);
  const empty = h("p", { class: "bs-empty" }, "Quiet for now.");
  const inner = h("div", { class: "bs-inner" }, title, empty, scroller, now);
  const el = h("div", { class: "backstage", id: "backstage", "aria-hidden": "true", inert: true }, inner);

  const shown = new Map(); // id -> li
  const nowRows = new Map(); // task id -> {el, bar, name}
  let settled = false; // after the first paint, new lines ease in
  let nowKey = "";

  function update(s) {
    const working = s.status === "working";
    const atBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40;
    let appended = false;

    for (const b of s.backstage) {
      let li = shown.get(b.id);
      if (!li) {
        li = line(b, onDetails);
        if (settled) li.classList.add("is-new");
        shown.set(b.id, li);
        lines.append(li);
        appended = true;
      }
      li.classList.toggle("is-active", !!b.active && working);
    }
    // forget lines the store no longer has (new run)
    for (const [id, li] of shown) {
      if (!s.backstage.some((b) => b.id === id)) {
        li.remove();
        shown.delete(id);
      }
    }
    if (shown.size === 0) settled = false;
    else if (s.backstage.length) settled = true;
    while (lines.children.length > MAX_LINES) {
      const first = lines.firstElementChild;
      shown.forEach((v, k) => v === first && shown.delete(k));
      first.remove();
    }
    empty.hidden = s.backstage.length > 0;

    updateNow(s, working);

    el.classList.toggle("is-alive", working);
    // Stick to the bottom only if the reader was already there, and only when something new came in.
    if (appended && atBottom) scroller.scrollTop = scroller.scrollHeight;
  }

  /** Every part being built right now (several builders can work at once), else whoever holds the turn. */
  function updateNow(s, working) {
    const tasks = working ? workingTasks(s) : [];
    const key = tasks.map((t) => t.id).join(",");
    if (!working || !tasks.length) {
      now.hidden = true;
      nowKey = "";
      return;
    }
    now.hidden = false;
    if (key !== nowKey) {
      nowKey = key;
      for (const id of [...nowRows.keys()]) if (!tasks.some((t) => t.id === id)) nowRows.delete(id);
      nowList.replaceChildren(
        ...tasks.map((t) => {
          let r = nowRows.get(t.id);
          if (!r) {
            const bar = createUsageBar({ size: "sm", name: `${t.name} usage` });
            const name = h("span", { class: "bs-now-who" });
            r = { el: h("li", { class: "bs-now-row" }, name, bar.el), bar, name };
            nowRows.set(t.id, r);
          }
          return r.el;
        })
      );
      nowLabel.textContent = tasks.length > 1 ? `Now · ${tasks.length} at once` : "Now";
    }
    for (const t of tasks) {
      const r = nowRows.get(t.id);
      if (!r) continue;
      if (r.name.textContent !== t.name) r.name.textContent = t.name;
      r.bar.el.hidden = !t.share;
      r.bar.update({ used: t.usage || 0, total: t.share || 0 });
    }
  }

  function setOpen(open) {
    el.inert = !open;
    el.setAttribute("aria-hidden", String(!open));
    if (open) {
      scroller.scrollTop = scroller.scrollHeight;
      requestAnimationFrame(() => title.focus({ preventScroll: true }));
    }
  }

  return { el, update, setOpen };
}

/** The plan's working tasks, named as the backstage names them; else the one agent holding the turn. */
function workingTasks(s) {
  const out = [];
  for (const g of s.plan?.groups || []) {
    for (const t of g.tasks || []) if (t.status === "working") out.push({ id: t.id, name: `Builder · ${t.name}`, usage: t.usage, share: t.share });
  }
  if (out.length) return out;
  const wn = s.working_now;
  if (!wn?.who) return [];
  const task = findTask(s.plan, wn.task_id);
  return [{ id: wn.task_id || wn.who, name: wn.who, usage: task?.usage || 0, share: task?.share || 0 }];
}

function line(b, onDetails) {
  const who = b.to
    ? h("span", { class: "bs-who" }, h("span", { class: "bs-from" }, b.from), h("span", { class: "bs-arrow", "aria-label": "to" }, " → "), h("span", { class: "bs-to" }, b.to))
    : h("span", { class: "bs-who" }, h("span", { class: "bs-from" }, b.from));
  const head = h("div", { class: "bs-head" }, who, h("span", { class: "bs-text" }, b.text));
  const li = h("li", { class: "bs-line" }, head);
  if (!hasDetails(b.detail) || !onDetails) return li;

  // "See details": the whole line opens the centre panel; the quiet link says so
  li.classList.add("has-more");
  const more = h("button", { class: "linkish bs-see", type: "button", tabindex: "-1", "aria-hidden": "true" }, "See details");
  head.append(more);
  head.setAttribute("role", "button");
  head.setAttribute("tabindex", "0");
  head.setAttribute("aria-haspopup", "dialog");
  head.setAttribute("aria-label", `${b.from}${b.to ? ` to ${b.to}` : ""}: ${b.text}. See details`);
  const go = () => onDetails(b, head);
  head.addEventListener("click", (e) => {
    // a click that selects text is reading, not tapping
    if (window.getSelection()?.toString()) return;
    e.preventDefault();
    go();
  });
  head.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      go();
    }
  });
  return li;
}

/** A line has something more to show: a structured kind, or a plain decision or reason. */
function hasDetails(d) {
  if (!d) return false;
  if (d.kind && d.kind !== "generic") return true;
  return !!(d.decided || d.why);
}

function findTask(plan, id) {
  if (!plan || !id) return null;
  for (const g of plan.groups || []) for (const t of g.tasks || []) if (t.id === id) return t;
  return null;
}
