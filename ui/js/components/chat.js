// The chat: one voice ("the team") and the user. Messages are appended by id, never repainted.
// Below the messages sit, in order: messages still sending, the open decision, and the ending.

import { h } from "../dom.js";
import { renderDecision } from "./decision.js";
import { renderProposal } from "./proposal.js";

export function createChat({ onAnswer, actions, readOnly = false, inlineCards = true }) {
  const msgs = h("div", { class: "msgs", role: "log", "aria-label": "Conversation" });
  const pendingBox = h("div", { class: "pending" });
  const decisionSlot = h("div", { class: "decision-slot" });
  const endingSlot = h("div", { class: "ending-slot" });
  const el = h("div", { class: "chat-col" }, msgs, pendingBox, decisionSlot, endingSlot);

  const shown = new Map();
  let lastFrom = null;
  let decisionKey = "";
  let endingKey = "";
  let pendingKey = "";
  let settled = false; // after the first paint, new lines ease in

  function update(store) {
    const s = store.s;
    let added = false;

    if (s.chat.length === 0 && shown.size) {
      msgs.replaceChildren();
      shown.clear();
      lastFrom = null;
      settled = false;
    }
    for (const m of s.chat) {
      if (shown.has(m.id)) continue;
      if (m.kind === "record") {
        // an answered decision stays as a quiet one-line record (what was approved / picked / sent)
        const node = record(m);
        if (settled) node.classList.add("is-new");
        msgs.append(node);
        shown.set(m.id, node);
        lastFrom = null;
        added = true;
        continue;
      }
      const from = m.from === "you" ? "you" : "team";
      const node = message(from, m.text, from !== lastFrom, m.t);
      if (settled) node.classList.add("is-new");
      msgs.append(node);
      shown.set(m.id, node);
      lastFrom = from;
      added = true;
    }
    if (s.chat.length) settled = true;

    const pk = store.pending.map((p) => p.key + p.waiting).join(",");
    if (pk !== pendingKey) {
      pendingKey = pk;
      pendingBox.replaceChildren(
        ...store.pending.map((p) => {
          const node = message("you", p.text, lastFrom !== "you", null);
          node.classList.add("is-pending");
          node.append(h("span", { class: "msg-note" }, p.waiting ? "Waiting for the team to finish a step" : "Sending"));
          return node;
        })
      );
      added = true;
    }

    const d = inlineCards ? s.decision : null;
    const dk = d ? `${d.id}|${d.kind}|${d.proposal?.estimate ?? ""}` : "";
    if (dk !== decisionKey) {
      decisionKey = dk;
      decisionSlot.replaceChildren();
      if (d) {
        const opts = { onAnswer: (body) => onAnswer(d, body), readOnly };
        decisionSlot.append(d.kind === "proposal" ? renderProposal(d, opts) : renderDecision(d, opts));
      }
      added = true;
    }

    const e = inlineCards ? s.ended : null;
    const ek = e ? JSON.stringify(e) + s.deliverables?.some((x) => x.url) : "";
    if (ek !== endingKey) {
      endingKey = ek;
      endingSlot.replaceChildren();
      if (e && !readOnly) endingSlot.append(ending(e, s, actions));
      added = true;
    }
    return added;
  }

  return { el, update };
}

/** A quiet one-line record of an answered decision: a check, the title and the summary. A proposal's record can
 * expand to show its parts. */
function record(m) {
  const head = h(
    "span",
    { class: "record-head" },
    h("span", { class: "record-check", "aria-hidden": "true" }),
    h("span", { class: "record-title" }, m.title || ""),
    m.summary ? h("span", { class: "record-summary" }, m.summary) : null
  );
  if (m.detail?.length) {
    return h(
      "details",
      { class: "record record-open", title: m.t || null },
      h("summary", null, head, h("span", { class: "record-more", "aria-hidden": "true" })),
      h("ul", { class: "record-list" }, m.detail.map((x) => h("li", null, x)))
    );
  }
  return h("div", { class: "record", title: m.t || null }, head);
}

function message(from, text, showName, t) {
  // Blank lines split paragraphs; a single newline (a short list from the team) is a line break.
  const paras = String(text || "")
    .split(/\n{2,}/)
    .map((p) => h("p", null, p.split("\n").flatMap((ln, i) => (i ? [h("br"), ln] : [ln]))));
  return h(
    "div",
    { class: `msg from-${from}${showName ? " is-first" : ""}` },
    showName && from === "team" ? h("span", { class: "msg-name" }, "The team") : null,
    h("div", { class: "bubble", title: t || null }, paras)
  );
}

const ENDING_KICKER = {
  done: "Done",
  done_open: "Done, with one thing open",
  stopped: "Stopped",
  crashed: "Not finished",
};

export function ending(e, s, actions) {
  const kind = e.kind || "done";
  const hasResult = s.deliverables?.some((d) => d.url);
  const open = e.open_items || [];
  const kicker = kind === "done_open" && open.length > 1 ? `Done, with ${open.length} things open` : ENDING_KICKER[kind];
  const btn = (label, cls, fn) => {
    const b = h("button", { class: `btn ${cls}`, type: "button" }, label);
    b.addEventListener("click", () => fn(b));
    return b;
  };

  const block = h("section", { class: `ending ending-${kind}`, "aria-label": kicker }, h("p", { class: "ending-kicker" }, h("span", { class: "dot", "aria-hidden": "true" }), kicker));

  if (kind === "crashed") {
    block.append(h("p", { class: "ending-text" }, "Something broke. Try again."));
    if (e.text && e.text.trim() !== "Something broke. Try again.") block.append(h("p", { class: "ending-sub" }, e.text));
    block.append(
      h("div", { class: "card-actions" }, btn("Try again", "btn-ink", actions.retry), btn("Details", "btn-quiet", actions.details), hasResult ? btn("See what was made", "btn-quiet", actions.openResult) : null)
    );
    return block;
  }

  if (e.text) block.append(h("p", { class: "ending-text" }, e.text));
  if (kind === "done_open" && open.length) {
    block.append(h("ul", { class: "open-items" }, open.map((x) => h("li", null, x))));
  }

  const row = h("div", { class: "card-actions" });
  if (kind === "done_open") {
    if (hasResult) row.append(btn("Result", "btn-secondary", actions.openResult));
    row.append(btn("Fix it", "btn-ink", (b) => actions.fix(open, b)));
    row.append(btn("Start something new", "btn-quiet", actions.startNew));
  } else {
    if (hasResult) row.append(btn(kind === "stopped" ? "See what was made" : "See the result", "btn-secondary", actions.openResult));
    row.append(btn("Start something new", "btn-ink", actions.startNew));
  }
  block.append(row);
  return block;
}
