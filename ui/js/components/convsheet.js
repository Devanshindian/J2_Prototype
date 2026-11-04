// The Conversation sheet: the chat (you and the team, one voice) with its composer, and one quiet switch to the
// team's own talk (the backstage lines; "See details" opens the centre panel). A side sheet on a laptop, a full-height sheet on a phone.

import { h } from "../dom.js";
import { createSheet } from "./sheet.js";
import { createChat } from "./chat.js";
import { createBackstage } from "./backstage.js";

export function createConvSheet({ onClose, onAnswer, actions, readOnly = false, onDetails } = {}) {
  const sheet = createSheet({ id: "conv-sheet", title: "Conversation", cls: "sheet-conv", onClose });

  const chat = createChat({ onAnswer, actions, readOnly, inlineCards: false });
  const chatScroll = h("div", { id: "chat-scroll", class: "chat-scroll", tabindex: -1 }, chat.el);
  const workingLine = h("p", { id: "working-line", class: "working-line", hidden: true }, h("span", { class: "working-dot", "aria-hidden": "true" }), h("span", { id: "working-text" }), h("span", { class: "working-dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")));
  const input = h("textarea", { id: "composer-input", class: "composer-input", rows: 1, placeholder: "Write a message…" });
  const sendBtn = h("button", { id: "composer-send", class: "send-btn", type: "submit", "aria-label": "Send", disabled: true });
  const composer = h("form", { id: "composer", class: "composer" }, h("label", { class: "sr-only", for: "composer-input" }, "Message"), input, sendBtn);
  const composerWrap = h("div", { class: "composer-wrap" }, workingLine, composer);
  const chatView = h("div", { class: "conv-view conv-chat" }, chatScroll, composerWrap);

  const backstage = createBackstage({ onDetails });
  const teamView = h("div", { class: "conv-view conv-team", hidden: true }, backstage.el);

  const tabChat = h("button", { class: "seg is-on", type: "button", role: "tab", "aria-selected": "true", id: "conv-tab-chat" }, "Chat");
  const tabTeam = h("button", { class: "seg", type: "button", role: "tab", "aria-selected": "false", id: "conv-tab-team" }, "Team talk");
  const seg = h("div", { class: "segs", role: "tablist", "aria-label": "Conversation views" }, tabChat, tabTeam);
  // "Decide for me" during a run, under the composer at every width (main.js binds every [data-decide], in sync with
  // the top bar's and the start screen's)
  const decideInput = h("input", { id: "decide-conv-input", type: "checkbox", role: "switch", "aria-describedby": "decide-conv-tip", "data-decide": "" });
  const decide = h("label", { class: "switch conv-decide", id: "decide-conv-switch" }, decideInput,
    h("span", { class: "switch-track", "aria-hidden": "true" }, h("span", { class: "switch-thumb" })),
    h("span", { class: "switch-text" }, "Decide for me"),
    h("span", { class: "tip", id: "decide-conv-tip", role: "tooltip" }, "When this is on, the team runs on its own: it approves the plan, picks the look and design details, answers small questions with the suggested option and tops up usage up to twice the estimate. It stops and asks only at that limit."));
  sheet.tools.append(seg);
  if (!readOnly) composerWrap.append(h("div", { class: "composer-under" }, decide));
  sheet.body.append(chatView, teamView);
  sheet.body.classList.add("conv-body");

  let which = "chat";
  function select(w) {
    which = w;
    const team = w === "team";
    tabChat.classList.toggle("is-on", !team);
    tabTeam.classList.toggle("is-on", team);
    tabChat.setAttribute("aria-selected", String(!team));
    tabTeam.setAttribute("aria-selected", String(team));
    chatView.hidden = team;
    teamView.hidden = !team;
    backstage.setOpen(team && sheet.isOpen);
    if (!team) requestAnimationFrame(() => (chatScroll.scrollTop = chatScroll.scrollHeight));
  }
  tabChat.addEventListener("click", () => select("chat"));
  tabTeam.addEventListener("click", () => select("team"));

  const open0 = sheet.open;
  sheet.open = (trigger) => {
    open0(trigger);
    backstage.setOpen(which === "team");
    if (which === "chat") requestAnimationFrame(() => (chatScroll.scrollTop = chatScroll.scrollHeight));
  };
  const close0 = sheet.close;
  sheet.close = (o) => {
    close0(o);
    backstage.setOpen(false);
  };

  return {
    sheet,
    chat,
    backstage,
    chatScroll,
    input,
    sendBtn,
    composer,
    workingLine,
    decideInput,
    select,
    get view() {
      return which;
    },
  };
}
