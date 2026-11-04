// The proposal card: the first and main decision. Approve / Make it smaller / Not this.

import { h, icon } from "../dom.js";
import { fmtUsage } from "../format.js";
import { ownAnswer } from "./decision.js";

let uid = 0;

export function renderProposal(d, { onAnswer, readOnly = false } = {}) {
  const id = `pc-${++uid}`;
  const p = d.proposal || {};
  const parts = p.parts || [];
  const estimate = p.estimate ?? null;
  const opt = (k) => (d.options || []).find((o) => o.id === k) || { id: k };

  const card = h("section", { class: "card decision proposal", "aria-labelledby": `${id}-t`, "data-no-gesture": "" });
  const err = h("p", { class: "card-error", role: "alert", hidden: true });

  card.append(h("p", { class: "card-kicker" }, "Here's the plan"), h("h2", { class: "card-title", id: `${id}-t` }, p.summary || d.happening || ""));

  if (parts.length) {
    const shown = parts.slice(0, 3).join(", ");
    const more = parts.length > 3 ? `, and ${parts.length - 3} more` : "";
    const list = h("ol", { class: "parts-list", id: `${id}-parts`, hidden: true }, parts.map((x) => h("li", null, x)));
    const toggle = h(
      "button",
      { class: "linkish", type: "button", "aria-expanded": "false", "aria-controls": `${id}-parts` },
      h("span", { class: "linkish-text" }, "See the parts"),
      icon("chevron", 14)
    );
    toggle.addEventListener("click", () => {
      const open = list.hidden;
      list.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.querySelector(".linkish-text").textContent = open ? "Hide the parts" : "See the parts";
    });
    card.append(h("p", { class: "card-line" }, `${parts.length} parts: ${shown}${more}. `, toggle), list);
  }

  // The model choice (api-contract.md, proposal.models): one quiet row of radio pills, the suggested one preselected.
  // The estimate line re-renders for the chosen model's rough multiplier ("about").
  const models = Array.isArray(p.models) ? p.models : [];
  let model = models.find((m) => m.suggested)?.id || models[0]?.id || null;
  const estEl = h("strong", { class: "tnum" });
  const estimateFor = (id) => Math.round(estimate * ((models.find((m) => m.id === id) || {}).multiplier || 1));
  const paintEstimate = () => {
    if (estimate == null) return;
    estEl.textContent = `about ${fmtUsage(model ? estimateFor(model) : estimate)}`;
  };
  if (estimate != null) {
    paintEstimate();
    card.append(h("p", { class: "card-line card-estimate" }, "Estimated usage: ", estEl));
  }
  if (models.length && !readOnly) {
    const name = `${id}-model`;
    const pills = models.map((m) => {
      const input = h("input", { type: "radio", name, value: m.id, id: `${name}-${m.id}`, class: "model-radio" });
      if (m.id === model) input.checked = true;
      input.addEventListener("change", () => {
        if (!input.checked) return;
        model = m.id;
        paintEstimate();
        pills.forEach((l) => l.classList.toggle("is-on", l.querySelector("input").checked));
      });
      const [head, tail] = String(m.label || m.id).split(" · ");
      return h("label", { class: "model-pill" + (m.id === model ? " is-on" : ""), for: `${name}-${m.id}` }, input,
        h("span", { class: "model-pill-name" }, head), tail ? h("span", { class: "model-pill-note" }, tail) : null);
    });
    card.append(h("fieldset", { class: "model-choice" }, h("legend", { class: "model-legend" }, "Model"), h("div", { class: "model-pills" }, pills)));
  }
  // The estimate line above already says the usage; keep only what else the team notes (e.g. what was left out).
  const why = estimate != null ? (d.why || "").replace(/\s*It should use about \S+ of usage\.?/, "").trim() : d.why;
  if (why) card.append(h("p", { class: "card-why" }, why));

  async function answer(option_id, text, btn) {
    if (readOnly || card.classList.contains("is-busy")) return;
    card.classList.add("is-busy");
    card.setAttribute("aria-busy", "true");
    btn?.classList.add("is-chosen");
    err.hidden = true;
    const controls = card.querySelectorAll("button:not(.linkish), input");
    controls.forEach((b) => (b.disabled = true));
    try {
      await onAnswer({ option_id, text: text || "", fields: {}, ...(model && option_id === "approve" ? { model } : {}) });
    } catch (e) {
      if (e?.status === 409) return;
      card.classList.remove("is-busy");
      card.removeAttribute("aria-busy");
      btn?.classList.remove("is-chosen");
      controls.forEach((b) => (b.disabled = false));
      err.textContent = "That didn't go through. Try again.";
      err.hidden = false;
    }
  }

  const approve = h("button", { class: "btn btn-primary", type: "button", title: opt("approve").gets || "" }, opt("approve").label || "Approve");
  const smaller = h("button", { class: "btn btn-secondary", type: "button", title: opt("smaller").gets || "" }, opt("smaller").label || "Make it smaller");
  const notThis = h("button", { class: "btn btn-quiet", type: "button", "aria-expanded": "false" }, opt("not_this").label || "Not this");
  approve.addEventListener("click", () => answer("approve", "", approve));
  smaller.addEventListener("click", () => answer("smaller", "", smaller));

  const change = ownAnswer((text, btn) => answer("not_this", text, btn), id, "What should change?");
  change.hidden = true;
  notThis.addEventListener("click", () => {
    change.hidden = !change.hidden;
    notThis.setAttribute("aria-expanded", String(!change.hidden));
    if (!change.hidden) change.querySelector("input").focus();
  });

  if (!readOnly) card.append(h("div", { class: "card-actions" }, approve, smaller, notThis), change);
  card.append(err);
  return card;
}
