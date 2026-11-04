// Wires the store, the API (or a fixture) and the components together. The kingdom map is the screen at rest;
// the conversation, the plan and the result are sheets; a decision or an ending rises as a card from the bottom.

import { HttpApi, FixtureApi, startPolling } from "./api.js";
import { createStore } from "./store.js";
import { $, h, icon, reducedMotion } from "./dom.js";
import { fmtUsage, ratio, statusWord, TASK_STATUS } from "./format.js";
import { createStatus } from "./components/status.js";
import { createUsageBar } from "./components/usagebar.js";
import { createPlanSheet } from "./components/plansheet.js";
import { createResultPanel } from "./components/resultpanel.js";
import { createConvSheet } from "./components/convsheet.js";
import { createBackstage } from "./components/backstage.js";
import { createKingdom } from "./components/kingdom.js";
import { createBubble } from "./components/bubble.js";
import { createDetailPanel } from "./components/detailpanel.js";
import { createTooltip } from "./components/tooltip.js";
import { coachSeen, showCoach } from "./components/coach.js";
import { renderDecision } from "./components/decision.js";
import { renderProposal } from "./components/proposal.js";
import { ending as renderEnding } from "./components/chat.js";
import { attachLockGesture } from "./components/lockgesture.js";

const params = new URLSearchParams(location.search);
const fixture = params.get("fixture");
const pastRun = params.get("run");
const readOnly = !!pastRun;
const api = fixture ? new FixtureApi(fixture) : new HttpApi({ run: pastRun });
const store = createStore();
const isPhone = () => window.matchMedia("(max-width: 720px)").matches;

const ROLE_WORD = { client: "Client lead", planner: "Planner", reviewer: "Plan reviewer", budget: "Budget lead", gatekeeper: "Gatekeeper", scheduler: "Scheduler", quality: "Quality check", builder: "Builder" };
const UNIT_STATE = { idle: "Resting", working: "Working", waiting: "Waiting for you" };

/* ---------- elements ---------- */
const startEl = $("#start");
const workEl = $("#work");
const stage = $("#stage");
const eyeBtn = $("#eye-btn");
const planBtn = $("#plan-btn");
const resultBtn = $("#result-btn");
const convBtn = $("#conv-btn");
const pauseBtn = $("#pause-btn");
const stopBtn = $("#stop-btn");
const backBtn = $("#back-btn");
const attnEl = $("#attn");
const attnCard = $("#attn-card");
const toastEl = $("#toast");
const announcer = $("#announcer");

eyeBtn.append(icon("eye", 20));
convBtn.append(icon("chat", 20), Object.assign(document.createElement("span"), { className: "btn-word", textContent: "Chat" }));
resultBtn.append(icon("result", 20));
pauseBtn.append(icon("pause", 20));
stopBtn.append(icon("stop", 20));
$("#zoom-in").append(icon("plus", 16));
$("#zoom-out").append(icon("minus", 16));
$("#zoom-fit").append(icon("fit", 16));

/* ---------- components ---------- */
const status = createStatus();
$("#status-slot").append(status.el);

const usage = createUsageBar({ size: "sm", name: "Usage" });
$("#usage-slot").append(usage.el);
const usageLine = $("#usage-line span");

const kingdom = createKingdom({ onTap: tapNode, onBackground: () => (bubble.open ? bubble.hide() : locked && unlock()),
  onZoom: () => {
    $("#zoom-fit").classList.toggle("is-hint", kingdom.userMoved);
    $("#zoom-in").disabled = kingdom.atMax;
    $("#zoom-out").disabled = kingdom.atMin;
  } });
$("#map-slot").append(kingdom.el);
$("#mini-slot").append(kingdom.mini);
const bubble = createBubble({ container: stage });
const tip = createTooltip({ container: stage, map: kingdom.el, describe: describeNode, nodeRect: (id) => kingdom.nodeRect(id),
  blocked: (g) => (bubble.open && bubble.current?.id === g.dataset.id) || kingdom.el.classList.contains("is-panning") });

const details = createDetailPanel();
// "Look behind" (hold and slide, or the eye): the team talk as a calm overlay over the map, the agents at work lit
const behind = createBackstage({ onDetails: (line, trigger) => details.open(line, { trigger }) });
const behindEl = h("div", { class: "behind", id: "behind", "data-no-gesture": "" }, behind.el);
stage.append(behindEl);
const conv = createConvSheet({ onClose: () => (details.close({ restoreFocus: false }), syncPanels()), onAnswer: answer, actions: endingActions(), readOnly,
  onDetails: (line, trigger) => details.open(line, { trigger }) });
const plan = createPlanSheet({ onClose: syncPanels });
const result = createResultPanel({ onClose: syncPanels });
$("#sheets").append(conv.sheet.el, plan.el, result.el);
const chat = conv.chat;
const chatScroll = conv.chatScroll;
const input = conv.input;
const sendBtn = conv.sendBtn;
const composer = conv.composer;
const workingLine = conv.workingLine;
const workingText = $("#working-text");
sendBtn.append(icon("arrow", 18));

/* ---------- helpers ---------- */
let toastTimer = null;
function toast(text, ms = 4000) {
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastEl.hidden = true), ms);
}
function announce(text) {
  announcer.textContent = "";
  setTimeout(() => (announcer.textContent = text), 50);
}
const nearBottom = () => chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 120;
function scrollToBottom(smooth = true) {
  chatScroll.scrollTo({ top: chatScroll.scrollHeight, behavior: smooth && !reducedMotion() ? "smooth" : "auto" });
}

/* ---------- sending ---------- */
let poller = null;

async function send(text) {
  text = text.trim();
  if (!text || readOnly) return false;
  const p = store.addPending(text);
  scrollToBottom();
  try {
    await api.say(text, (w) => store.markPending(p, w));
    store.markPending(p, false);
    poller?.now();
    return true;
  } catch (e) {
    store.dropPending(p);
    toast(e?.status === 409 ? "The team is still busy. Try again in a moment." : "That message didn't go through. Try again.");
    return false;
  }
}

async function answer(d, body) {
  try {
    await api.decide({ decision_id: d.id, option_id: body.option_id, text: body.text || "", fields: body.fields || {},
      ...(body.model ? { model: body.model } : {}) });
    poller?.now();
  } catch (e) {
    if (e?.status === 409) {
      toast("That question was already answered.");
      poller?.now();
    }
    throw e;
  }
}

async function startNew(btn) {
  if (btn) btn.disabled = true;
  try {
    await api.newRun(() => toast("Finishing the current step first…"));
    closePanels();
    unlock();
    bubble.hide();
    store.reset();
    kingdom.reset();
    autoOpened.clear();
    if (readOnly) location.href = location.pathname + (fixture ? `?fixture=start` : "");
    poller?.now();
  } catch {
    toast("Couldn't start a new one yet. Try again in a moment.");
    if (btn) btn.disabled = false;
  }
}

function endingActions() {
  return {
    startNew,
    openResult: () => openPanel("result"),
    details: () => window.open("/legacy", "_blank", "noopener"),
    fix: (open, btn) => {
      btn.disabled = true;
      send(open.length ? `Please fix this: ${open.join("; ")}` : "Please fix what's open.").finally(() => (btn.disabled = false));
    },
    retry: async (btn) => {
      const first = store.s.chat.find((m) => m.from === "you")?.text;
      await startNew(btn);
      if (first) send(first);
    },
  };
}

/* ---------- controls (pause / resume / stop / skip / redo / note) ---------- */
async function control(body, okText) {
  try {
    const r = await api.control(body);
    if (okText) toast(okText, 2500);
    poller?.now();
    return r;
  } catch (e) {
    toast(e?.message && e.status === 409 ? firstCap(e.message) : "That didn't go through. Try again.");
    throw e;
  }
}
const firstCap = (s) => (s ? s[0].toUpperCase() + s.slice(1) + (/[.!?]$/.test(s) ? "" : ".") : s);

let stopArmed = 0;
pauseBtn.addEventListener("click", () => {
  const s = store.s;
  const paused = s.status === "paused" || s.control?.pausing;
  control({ action: paused ? "resume" : "pause" }).catch(() => {});
});
stopBtn.addEventListener("click", () => {
  if (Date.now() - stopArmed > 3000) {
    stopArmed = Date.now();
    stopBtn.classList.add("is-armed");
    toast("Tap Stop again to end the run. What's built so far is kept.", 3000);
    setTimeout(() => stopBtn.classList.remove("is-armed"), 3000);
    return;
  }
  stopArmed = 0;
  stopBtn.classList.remove("is-armed");
  control({ action: "stop" }).catch(() => {});
});

/* ---------- composer ---------- */
function autosize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}
input.addEventListener("input", () => {
  sendBtn.disabled = !input.value.trim();
  autosize();
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    composer.requestSubmit();
  }
});
composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value;
  if (!text.trim()) return;
  input.value = "";
  sendBtn.disabled = true;
  autosize();
  const ok = await send(text);
  if (!ok && !input.value) {
    input.value = text;
    sendBtn.disabled = false;
    autosize();
  }
});

/* ---------- start screen ---------- */
const startForm = $("#start-form");
const startInput = $("#start-input");
const startGo = $("#start-go");
startInput.addEventListener("input", () => (startGo.disabled = !startInput.value.trim()));
startInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    startForm.requestSubmit();
  }
});
startForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = startInput.value.trim();
  if (!text) return;
  startInput.value = "";
  startGo.disabled = true;
  send(text);
});
for (const b of document.querySelectorAll("[data-try]")) {
  b.addEventListener("click", () => {
    startInput.value = b.dataset.try;
    startGo.disabled = false;
    startInput.focus();
  });
}

// "Decide for me": the run setting no_questions (POST /api/v2/settings). Off by default; the state is the truth.
// Three switches share it: the start screen's, the top bar's (a laptop) and the Conversation sheet's (a phone).
// Switched on while a small question is open, the backend answers it at once (`answered` in the reply).
const decideInputs = [$("#decide-input"), $("#decide-run-input"), conv.decideInput];
let decidePending = false;
function syncDecide(on) {
  for (const i of decideInputs) if (i.checked !== on) i.checked = on;
}
for (const input of decideInputs) {
  input.addEventListener("change", async () => {
    const want = input.checked;
    decidePending = true;
    for (const i of decideInputs) i.disabled = true;
    try {
      const r = await api.settings({ no_questions: want });
      store.s.settings = { ...(store.s.settings || {}), ...(r?.settings || { no_questions: want }) };
      syncDecide(!!store.s.settings.no_questions);
      if (r?.answered) toast("The team took the suggested answer to the open question.");
    } catch {
      syncDecide(!want);
      toast("That setting didn't save. Try again.");
    } finally {
      decidePending = false;
      for (const i of decideInputs) i.disabled = false;
    }
  });
}

let recentLoaded = false;
async function loadRecent() {
  if (recentLoaded) return;
  recentLoaded = true;
  try {
    const runs = (await api.runs()) || [];
    const list = $("#recent-list");
    list.replaceChildren(
      ...runs.slice(0, 5).map((r) => {
        const href = r.fixture ? `?fixture=${encodeURIComponent(r.fixture)}` : `?run=${encodeURIComponent(r.id)}`;
        return h(
          "li",
          null,
          h(
            "a",
            { class: "recent-item", href },
            h("span", { class: "recent-name" }, r.title || "Untitled"),
            h("span", { class: "recent-meta tnum" }, [statusWord(r.status), r.spent ? fmtUsage(r.spent) : "", r.when].filter(Boolean).join(" · "))
          )
        );
      })
    );
    $("#recent").hidden = runs.length === 0;
  } catch {
    /* the recent list is optional */
  }
}

/* ---------- panels (one open at a time) ---------- */
const SHEETS = { conv: conv.sheet, plan, result };
const TRIGGERS = { conv: convBtn, plan: planBtn, result: resultBtn };
function openPanel(which, trigger) {
  const a = SHEETS[which];
  for (const [k, s] of Object.entries(SHEETS)) if (k !== which && s.isOpen) s.close({ restoreFocus: false });
  if (a.isOpen) return a.close();
  bubble.hide();
  a.open(trigger || TRIGGERS[which]);
  if (which === "conv") convUnread = 0;
  syncPanels();
}
function closePanels() {
  for (const s of Object.values(SHEETS)) s.close({ restoreFocus: false });
  syncPanels();
}
function syncPanels() {
  for (const [k, s] of Object.entries(SHEETS)) {
    TRIGGERS[k].setAttribute("aria-expanded", String(s.isOpen));
    document.body.classList.toggle(`with-${k}`, s.isOpen);
  }
  if (conv.sheet.isOpen) convBtn.classList.remove("has-dot");
  // On phones a sheet covers everything; keep focus out of what is underneath.
  workEl.inert = isPhone() && Object.values(SHEETS).some((s) => s.isOpen);
}
planBtn.addEventListener("click", () => openPanel("plan", planBtn));
resultBtn.addEventListener("click", () => openPanel("result", resultBtn));
convBtn.addEventListener("click", () => openPanel("conv", convBtn));
window.addEventListener("resize", syncPanels);
// the centred Result closes on a press anywhere outside it (the Result button toggles it itself)
document.addEventListener("pointerdown", (e) => {
  if (!result.isOpen || isPhone() || result.el.contains(e.target) || resultBtn.contains(e.target)) return;
  if (e.target.closest?.(".dpanel, .toast")) return;
  result.close({ restoreFocus: false });
  syncPanels();
}, true);

/* ---------- calm mode <-> interaction mode (hold and slide, the eye button, Back to calm) ---------- */
let locked = false;
let lockOpener = null;

function lock(opener = null) {
  if (locked) return;
  locked = true;
  const active = document.activeElement;
  lockOpener = opener || (active && active !== document.body && stage.contains(active) ? active : null);
  stage.classList.add("is-locked");
  stage.classList.remove("is-peek");
  stage.style.removeProperty("--lock-p");
  kingdom.setMode("interact");
  bubble.hide();
  tip.hide();
  behind.update(store.s);
  behind.setOpen(true);
  if (window.innerWidth >= 1100) kingdom.setInset({ left: behindEl.offsetWidth + 40 });
  backBtn.hidden = false;
  eyeBtn.setAttribute("aria-pressed", "true");
  eyeBtn.setAttribute("aria-label", "Back to the map");
}
function unlock() {
  if (!locked) return;
  locked = false;
  stage.classList.remove("is-locked");
  kingdom.setMode("calm");
  behind.setOpen(false);
  kingdom.setInset({ left: 0 });
  backBtn.hidden = true;
  eyeBtn.setAttribute("aria-pressed", "false");
  eyeBtn.setAttribute("aria-label", "See the team talking");
  const target = lockOpener && document.contains(lockOpener) ? lockOpener : kingdom.el;
  lockOpener = null;
  if (target === kingdom.el) kingdom.el.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}
eyeBtn.addEventListener("click", () => (locked ? unlock() : lock(eyeBtn)));
backBtn.addEventListener("click", unlock);

attachLockGesture(kingdom.el, {
  enabled: () => !workEl.hidden && !bubble.open,
  hint: () => (locked ? "Slide back to the map" : "Slide to see the team talking"),
  notEmpty: ".bubble, .kbub, .card, .ending, .behind, button, a, input, textarea, select, label, [data-no-gesture], [contenteditable], .k-node",
  onArm: () => {
    if (!locked) behind.update(store.s);
    stage.style.setProperty("--lock-p", "0");
    stage.classList.add("is-peek");
  },
  onProgress: (p) => stage.style.setProperty("--lock-p", p.toFixed(3)),
  onCancel: () => {
    stage.classList.remove("is-peek");
    stage.style.removeProperty("--lock-p");
  },
  onLock: () => {
    stage.classList.remove("is-peek");
    stage.style.removeProperty("--lock-p");
    locked ? unlock() : lock(null);
  },
});

$("#zoom-in").addEventListener("click", () => kingdom.zoomIn());
$("#zoom-out").addEventListener("click", () => kingdom.zoomOut());
$("#zoom-fit").addEventListener("click", () => kingdom.fit());

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (bubble.open) return; // the bubble closes itself
  for (const s of Object.values(SHEETS)) if (s.isOpen) return s.close(), syncPanels();
  if (locked) return unlock();
});

// Zoom belongs to the map alone: ctrl + wheel (a trackpad pinch) and Safari's pinch never zoom the page, whatever is
// under the pointer (the map handles its own; panels just scroll).
document.addEventListener("wheel", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.target.closest?.(".k-map")) e.preventDefault();
}, { passive: false });
for (const ev of ["gesturestart", "gesturechange", "gestureend"]) document.addEventListener(ev, (e) => e.preventDefault(), { passive: false });

/* ---------- tap bubbles ---------- */
function partOf(id) {
  return store.map.buildings.find((b) => b.id === id) || null;
}
/** A finished part opens its real output straight away in the centred panel (feedback 4): the file it wrote, the look,
 * its section in the page preview, or the sources it read; its controls (Redo, Note) sit in the panel's header. */
const outputOf = (b) => !!b?.output && b.state === "done";
let outputSeq = 0;
async function openOutput(b, trigger) {
  const seq = ++outputSeq;
  let o;
  try {
    o = await api.output(b.id);
  } catch {
    toast("That output couldn't be loaded. Try again in a moment.");
    return;
  }
  if (seq !== outputSeq) return; // a newer click won
  bubble.hide();
  tip.hide();
  const docUrl = o.kind === "document" && o.doc ? (store.s.deliverables || []).find((d) => d.kind === o.doc)?.url || null : null;
  details.openOutput(o, { status: TASK_STATUS[b.state] || "Done", controls: controlsFor(b), docUrl, trigger: trigger || kingdom.node(b.id)?.g });
}
function controlsFor(b) {
  if (readOnly || !b) return [];
  const st = store.s.status;
  const live = st === "working" || st === "paused" || st === "needs_you";
  const note = { label: "Note", icon: "note", note: true, placeholder: `A short note about ${b.name.toLowerCase()}`, onClick: (btn, text) => control({ action: "note", target: b.id, text }, "Noted. The planner will see it.") };
  const skip = { label: "Skip", icon: "skip", onClick: () => control({ action: "skip", target: b.id }, `Skipping ${b.name.toLowerCase()}.`).then(() => bubble.hide()) };
  const redo = { label: "Redo", icon: "redo", onClick: () => control({ action: "redo", target: b.id }, `${b.name} will be built again.`).then(() => bubble.hide()) };
  if (b.id.startsWith("p-")) return [];
  if (b.state === "waiting" || b.state === "needs_fix") return live ? [skip, note] : [];
  if (b.state === "done") return [redo, note];
  if (b.state === "working") return live ? [note] : [];
  return [];
}
/** The hover card's words for a node: what it is, what it is doing now, and (a part) how far along it is. */
function describeNode(id) {
  const n = kingdom.node(id);
  if (!n?.data) return null;
  if (n.kind === "unit") {
    const u = n.data;
    const b = u.role === "builder" ? partOf(u.at) : null;
    const line = u.doing || (b ? TASK_STATUS[b.state] || "" : u.state === "idle" ? "Resting until it's needed" : UNIT_STATE[u.state] || "");
    return { title: u.label || ROLE_WORD[u.role] || "", sub: u.role === "builder" ? "" : UNIT_STATE[u.state] || "", line, meta: b ? partMeta(b) : "" };
  }
  if (n.kind === "bld") {
    const b = n.data;
    return { title: b.name, sub: `Part · ${TASK_STATUS[b.state] || ""}`, line: b.doing && b.doing !== TASK_STATUS[b.state] ? b.doing : "", meta: partMeta(b) };
  }
  return null;
}
function partMeta(b) {
  const bits = [];
  if (b.state !== "waiting" && b.state !== "skipped" && typeof b.progress === "number") bits.push(`${Math.round((b.state === "done" ? 1 : b.progress) * 100)}%`);
  if (b.share) bits.push(`${fmtUsage(b.usage || 0)} of ${fmtUsage(b.share)}`);
  else if (b.usage) bits.push(`${fmtUsage(b.usage)} used`);
  return bits.join(" · ");
}

function tapNode(node, point, { force = false } = {}) {
  if (!force) tip.hide();
  if (!node) return bubble.hide();
  if (!force && bubble.open && bubble.current?.id === node.id) return bubble.hide();
  const anchor = kingdom.nodeRect(node.id) || { left: point.x, top: point.y, width: 0, height: 0, right: point.x, bottom: point.y };
  // the controls (skip / redo / note) are always in the bubble: no mode to switch on first
  if (node.kind === "castle") {
    return bubble.show({ id: "castle", kind: "castle", title: "You", line: "Everything the team makes comes here.", anchor,
      controls: [{ label: "Conversation", icon: "chat", kind: "primary", onClick: () => { bubble.hide(); openPanel("conv"); } }] });
  }
  if (node.kind === "light") {
    return bubble.show({ id: `f-${node.id}`, kind: "light", title: "Handed over", line: node.data?.what || "", anchor });
  }
  if (node.kind === "unit") {
    const u = node.data || {};
    const b = u.role === "builder" ? partOf(u.at) : null;
    const line = u.doing || (b ? `${TASK_STATUS[b.state] || ""}` : UNIT_STATE[u.state] || "");
    let controls = [];
    if (u.role === "client") controls = [{ label: "Conversation", icon: "chat", onClick: () => { bubble.hide(); openPanel("conv"); } }];
    else if (b) controls = controlsFor(b);
    return bubble.show({ id: u.id, kind: "unit", title: u.label || ROLE_WORD[u.role] || "", sub: u.role === "builder" ? "Builder" : UNIT_STATE[u.state] || "", line, anchor,
      progress: b && b.state !== "waiting" ? b.progress : undefined, used: b?.usage, share: b?.share, controls });
  }
  const b = node.data || {};
  if (outputOf(b)) {
    bubble.hide();
    return force ? undefined : openOutput(b); // a bubble refresh never pops a panel open by itself
  }
  const ctl = controlsFor(b);
  return bubble.show({ id: b.id, kind: "part", title: b.name, sub: TASK_STATUS[b.state] || "", line: b.doing || "", anchor,
    progress: b.state === "waiting" || b.state === "skipped" ? undefined : b.progress, used: b.usage, share: b.share,
    controls: ctl });
}

/* ---------- the attention card (a decision, or the ending) ---------- */
let attnKey = "";
let lastDecisionId = null;
let lastEndingKey = "";
const autoOpened = new Set();

function renderAttention(s) {
  const d = s.decision;
  const e = s.ended;
  const key = d ? `d|${d.id}|${d.kind}|${d.proposal?.estimate ?? ""}` : e && !readOnly ? `e|${JSON.stringify(e)}|${s.deliverables?.some((x) => x.url)}` : "";
  if (key === attnKey) return;
  const had = attnKey;
  attnKey = key;
  attnCard.replaceChildren();
  if (d) {
    const opts = { onAnswer: (body) => answer(d, body), readOnly };
    attnCard.append(d.kind === "proposal" ? renderProposal(d, opts) : renderDecision(d, opts));
  } else if (e && !readOnly) {
    attnCard.append(renderEnding(e, s, endingActions()));
  }
  attnEl.hidden = !key;
  // the map fits in the space above the card, so no name sits half under its edge (feedback 2)
  requestAnimationFrame(() => kingdom.setInset({ bottom: key && !isPhone() ? attnCard.offsetHeight + 24 : 0 }));
  attnEl.classList.remove("is-up");
  if (key) requestAnimationFrame(() => attnEl.classList.add("is-up"));
  stage.classList.toggle("has-attn", !!key);
  if (key) bubble.hide();

  // an answered decision: the card has gone; its record is in the conversation
  if (had.startsWith("d|") && !d) {
    const rec = [...s.chat].reverse().find((m) => m.kind === "record");
    if (rec) toast(rec.title, 2500);
  }
}

/* ---------- render ---------- */
let convUnread = 0;
let lastTeamId = 0;
let coachShown = false;

function render() {
  const s = store.s;
  const m = store.map;
  const sending = store.pending.length > 0;
  const showStart = store.loaded && !readOnly && s.status === "idle" && s.chat.length === 0 && !sending && !s.decision;

  $("#offline").hidden = store.loaded || store.connection !== "lost";
  startEl.hidden = !showStart;
  workEl.hidden = !store.loaded || showStart;
  document.body.dataset.view = showStart ? "start" : "work";
  if (showStart) {
    loadRecent();
    closePanels();
    unlock();
    bubble.hide();
  }
  if (!decidePending) syncDecide(!!s.settings?.no_questions);
  const liveRun = !showStart && !readOnly && !["done", "done_open", "stopped", "crashed"].includes(s.status);
  $("#decide-run-switch").hidden = !liveRun;
  conv.decideInput.closest("label").hidden = !liveRun;
  document.title = s.run?.title ? `${s.run.title} · J2` : "J2";

  status.update({ status: s.status, ended: s.ended, connection: store.connection, sending, control: s.control,
                  status_text: s.status_text });
  status.el.title = s.status_text || "";

  // the resource bar: used of budget, parts done of total, the status dot. Numbers only.
  const u = s.usage || {};
  usage.update({ used: u.spent || 0, total: u.budget || 0, margin: u.margin_at });
  usage.el.hidden = !u.budget && !u.spent;
  usageLine.style.setProperty("--r", ratio(u.spent, u.budget).toFixed(4));
  usageLine.parentElement.classList.toggle("is-over", !!u.margin_at && u.spent >= u.margin_at);
  const total = m.counts?.total || 0;
  $("#parts-done").textContent = String(m.counts?.done || 0);
  $("#parts-total").textContent = String(total);
  planBtn.hidden = !total && !s.plan?.groups?.length;
  planBtn.disabled = !s.plan?.groups?.length;

  // global controls: pause / resume while it works, stop while anything is going
  const live = s.status === "working" || s.status === "paused";
  const pausedish = s.status === "paused" || s.control?.pausing;
  pauseBtn.hidden = !live || readOnly;
  pauseBtn.replaceChildren(icon(pausedish ? "play" : "pause", 20));
  pauseBtn.setAttribute("aria-label", pausedish ? "Resume" : "Pause");
  pauseBtn.title = pausedish ? "Resume" : "Pause";
  pauseBtn.classList.toggle("is-on", !!pausedish);
  pauseBtn.disabled = !!s.control?.stopping;
  stopBtn.hidden = !(live || s.status === "needs_you") || readOnly;
  stopBtn.disabled = !!s.control?.stopping;
  stage.classList.toggle("is-paused", s.status === "paused");

  const working = (s.status === "working" || (sending && s.status === "idle")) && !s.decision;
  workingLine.hidden = !working;
  const wt = sending && s.status !== "working" ? "Sending" : s.status_text || "Working";
  const cleanWt = wt.replace(/[\s.…]+$/u, "");
  if (workingText.textContent !== cleanWt) workingText.textContent = cleanWt;

  input.placeholder = s.ended && (s.ended.kind === "done" || s.ended.kind === "done_open") ? "Ask for a change…" : s.decision ? "Or write a message…" : "Write a message…";
  composer.hidden = readOnly;

  const hasResult = (s.deliverables || []).some((d) => d.url || d.state !== "todo");
  resultBtn.classList.toggle("has-dot", hasResult && !result.isOpen && (s.deliverables || []).some((d) => d.state === "done"));

  const stick = nearBottom();
  const added = chat.update(store);
  plan.update(s.plan, s.working_now, s.usage);
  result.update(s.deliverables);
  conv.backstage.update(s);
  if (locked || stage.classList.contains("is-peek")) behind.update(s); // drawn only while it can be seen
  if (added && stick) requestAnimationFrame(() => scrollToBottom());

  // unread dot on the conversation button: new words from the team while the sheet is closed
  const newestTeam = [...s.chat].reverse().find((x) => x.from === "team" && x.kind !== "record")?.id || 0;
  if (newestTeam > lastTeamId) {
    if (lastTeamId && !conv.sheet.isOpen) convUnread++;
    lastTeamId = newestTeam;
  }
  convBtn.classList.toggle("has-dot", convUnread > 0 && !conv.sheet.isOpen);

  // the map
  if (store.mapLoaded) {
    kingdom.update(m, { status: s.status, attention: s.decision ? m.attention : null });
    if (bubble.open && bubble.current && !bubble.current.id.startsWith("f-")) refreshBubble();
    tip.refresh();
  }
  stage.classList.toggle("is-alive", s.status === "working");
  renderAttention(s);
  if (s.decision && store.mapLoaded && store.map.attention) {
    // keep the node the question is about in view, above the card (once per decision)
    const target = store.map.attention;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const top = attnCard.getBoundingClientRect().top - stage.getBoundingClientRect().top;
      kingdom.showAttention(target, Math.max(120, top - 16));
    }));
  }

  // announcements
  const d = s.decision;
  if (d && d.id !== lastDecisionId) announce(`Needs you: ${d.kind === "proposal" ? d.proposal?.summary || "the plan is ready" : d.happening}`);
  lastDecisionId = d?.id || null;

  const ek = s.ended ? `${s.run?.id}|${s.ended.kind}` : "";
  if (ek && ek !== lastEndingKey) {
    announce(`${statusWord(s.status, s.ended)}. ${s.ended.kind === "crashed" ? "Something broke." : s.ended.text || ""}`);
    const runKey = s.run?.id || "run";
    if ((s.ended.kind === "done" || s.ended.kind === "done_open") && result.hasContent() && !autoOpened.has(runKey) && !readOnly) {
      autoOpened.add(runKey);
      if (!isPhone() && !wasAutoOpened(runKey)) setTimeout(() => !Object.values(SHEETS).some((x) => x.isOpen) && openPanel("result", resultBtn), 400);
    }
  }
  lastEndingKey = ek;

  maybeCoach();
}

/** The bubble follows its node's data between polls (progress, the one line, controls). */
function refreshBubble() {
  const id = bubble.current.id;
  const n = kingdom.node(id);
  if (!n) return bubble.hide();
  const was = bubble.el.querySelector(".bub-note:not([hidden])");
  if (was) return; // never yank a note box out from under the person
  const r = kingdom.nodeRect(id);
  const focused = document.activeElement;
  tapNode(n, { x: r?.left || 0, y: r?.top || 0 }, { force: true });
  bubble.el.classList.add("is-in");
  if (focused && focused.closest(".kbub") && document.contains(focused)) focused.focus({ preventScroll: true });
}

function wasAutoOpened(key) {
  try {
    const k = `j2-result-opened-${key}`;
    if (sessionStorage.getItem(k)) return true;
    sessionStorage.setItem(k, "1");
  } catch {
    /* storage unavailable: just open it */
  }
  return false;
}

/* ---------- the first-run coach mark (once) ---------- */
function maybeCoach() {
  if (coachShown || readOnly || workEl.hidden || !store.mapLoaded) return;
  const want = params.get("coach");
  if (want === "0" || (want !== "1" && coachSeen())) return;
  const m = store.map;
  if (!m.units.length || !m.buildings.length) return;
  coachShown = true;
  const rectOf = (id) => kingdom.nodeRect(id);
  const unit = m.units.find((u) => u.role === "planner") || m.units[0];
  const part = m.buildings.find((b) => b.state === "working") || m.buildings[0];
  const tapTarget = m.buildings.find((b) => b.state === "working") || m.units.find((u) => u.state === "working") || part;
  setTimeout(() => {
    showCoach(stage, [
      { text: "These are your team.", rect: () => rectOf(unit.id) },
      { text: "These are the parts being built.", rect: () => rectOf(part.id) },
      { text: "Tap anything to see what it's doing. Hold and slide on empty map to see the team talking.", rect: () => rectOf(tapTarget.id) },
    ]);
  }, 500);
}

/* ---------- boot ---------- */
if (readOnly) {
  const banner = $("#banner");
  banner.hidden = false;
  banner.append(h("span", null, "You're looking at a past run."), h("a", { href: location.pathname + (fixture ? `?fixture=${fixture}` : "") }, "Back to now"));
}

store.subscribe(render);
window.__j2 = { kingdom, store, api }; // for the UI checks
if (fixture) {
  api.ready.catch((e) => {
    document.body.append(h("p", { class: "noscript" }, e.message));
  });
}
poller = startPolling(api, store);

// Fixture mode only: open a sheet or a mode on load for screenshots (?open=conv|plan|result|backstage&tab=<kind>&mode=interact).
if (fixture && (params.get("open") || params.get("mode"))) {
  const want = params.get("open");
  const unsub = store.subscribe(() => {
    if (!store.loaded || !store.mapLoaded) return;
    unsub();
    setTimeout(() => {
      if (params.get("mode") === "interact") lock(null);
      if (want === "backstage") {
        openPanel("conv");
        conv.select("team");
      } else if (want) openPanel(want);
      if (params.get("tab")) result.select(params.get("tab"));
    }, 50);
  });
}
