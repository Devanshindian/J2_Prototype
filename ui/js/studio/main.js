// The studio view (the default page; ?view=kingdom keeps the map view). The output is the screen: the website or
// document being built, live, in the centre. The team (five friendly people) and the plan sit in a left rail on a
// laptop and in a bottom dock on a phone. A question shows twice: inline at the section it is about, and from Asha in
// the team panel; either answers it through the same /api/v2/decide. Same API, store and polling as the map view.

import { HttpApi, FixtureApi, startPolling } from "../api.js";
import { createStore } from "../store.js";
import { $, h, icon } from "../dom.js";
import { fmtUsage, ratio, statusWord, DELIVERABLE_LABEL } from "../format.js";
import { renderDecision, ownAnswer } from "../components/decision.js";
import { renderProposal } from "../components/proposal.js";
import { ending as renderEnding } from "../components/chat.js";
import { createDetailPanel } from "../components/detailpanel.js";
import { avatar, TEAM } from "./people.js";
import { PEOPLE, SHORT, partsOf, teamModel, logOf, teamWords, andList } from "./team.js";
import { createOutput } from "./output.js";

const params = new URLSearchParams(location.search);
const fixture = params.get("fixture");
const pastRun = params.get("run");
const readOnly = !!pastRun;
const api = fixture ? new FixtureApi(fixture) : new HttpApi({ run: pastRun });
const store = createStore();
const isPhone = () => window.matchMedia("(max-width: 820px)").matches;
const ENDED = ["done", "done_open", "stopped", "crashed"];

/* ---------- elements ---------- */
const startEl = $("#start");
const workEl = $("#work");
const drawer = $("#st-drawer");
const dbody = $("#st-dbody");
const nudge = $("#st-nudge");
const toastEl = $("#st-toast");
const announcer = $("#announcer");
const pauseBtn = $("#st-pause");
const stopBtn = $("#st-stop");
const openBtn = $("#st-open");
pauseBtn.append(icon("pause", 18));
stopBtn.append(icon("stop", 18));
$("#st-nudge-av").innerHTML = avatar("asha", 26, { prop: false });
$("#start-team").innerHTML = PEOPLE.map((k) => `<span class="st-face" title="${TEAM[k].name}, ${TEAM[k].role}">${avatar(k, 40, { prop: false })}</span>`).join("")
  + `<span class="st-start-line">Asha, Mira, Kabir, Dev and Nora are ready.</span>`;
{
  const q = new URLSearchParams(location.search);
  q.set("view", "kingdom");
  $("#st-mapview").href = `/?${q}`;
}

const details = createDetailPanel();
const output = createOutput({ el: $("#st-out"), onTag: tagClicked });
output.onScroll = syncNudge;

/* ---------- helpers ---------- */
function toast(text, ms = 2800) {
  toastEl.textContent = text;
  toastEl.classList.add("on");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => toastEl.classList.remove("on"), ms);
}
function announce(text) {
  announcer.textContent = "";
  setTimeout(() => (announcer.textContent = text), 50);
}
const firstCap = (s) => (s ? s[0].toUpperCase() + s.slice(1) + (/[.!?]$/.test(s) ? "" : ".") : s);
const lower1 = (s) => (s ? s[0].toLowerCase() + s.slice(1) : s);

/* ---------- talking to the team ---------- */
let poller = null;

async function send(text) {
  text = text.trim();
  if (!text || readOnly) return false;
  const p = store.addPending(text);
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
    closeDrawer();
    poller?.now();
  } catch (e) {
    if (e?.status === 409) {
      toast("That question was already answered.");
      poller?.now();
    }
    throw e;
  }
}

async function control(body, okText) {
  try {
    const r = await api.control(body);
    if (okText) toast(okText);
    poller?.now();
    return r;
  } catch (e) {
    toast(e?.message && e.status === 409 ? firstCap(e.message) : "That didn't go through. Try again.");
    throw e;
  }
}

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

async function startNew(btn) {
  if (btn) btn.disabled = true;
  try {
    await api.newRun(() => toast("Finishing the current step first…"));
    closeDrawer();
    store.reset();
    live = null;
    liveSig = "";
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
    openResult: () => openDeliverable(),
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

let recentLoaded = false;
async function loadRecent() {
  if (recentLoaded) return;
  recentLoaded = true;
  try {
    const runs = (await api.runs()) || [];
    $("#recent-list").replaceChildren(...runs.slice(0, 5).map((r) => {
      const href = r.fixture ? `?fixture=${encodeURIComponent(r.fixture)}` : `?run=${encodeURIComponent(r.id)}`;
      return h("li", null, h("a", { class: "recent-item", href }, h("span", { class: "recent-name" }, r.title || "Untitled"),
        h("span", { class: "recent-meta tnum" }, [statusWord(r.status), r.spent ? fmtUsage(r.spent) : "", r.when].filter(Boolean).join(" · "))));
    }));
    $("#recent").hidden = runs.length === 0;
  } catch {
    /* the recent list is optional */
  }
}

/* ---------- Decide for me (POST /api/v2/settings no_questions); every switch on the page shows the same state ---------- */
const decideBtns = [...document.querySelectorAll("[data-decide]")];
let decidePending = false;
function syncDecide(on) {
  for (const b of decideBtns) b.setAttribute("aria-checked", String(!!on));
}
for (const b of decideBtns) {
  b.addEventListener("click", async () => {
    if (decidePending) return;
    const want = b.getAttribute("aria-checked") !== "true";
    decidePending = true;
    syncDecide(want);
    try {
      const r = await api.settings({ no_questions: want });
      store.s.settings = { ...(store.s.settings || {}), ...(r?.settings || { no_questions: want }) };
      syncDecide(!!store.s.settings.no_questions);
      if (r?.answered) toast("Decided for you: the team took the suggested answer.");
      else toast(want ? "Decide for me is on: the team answers its own questions" : "Decide for me is off: questions come to you");
      poller?.now();
    } catch {
      syncDecide(!want);
      toast("That setting didn't save. Try again.");
    } finally {
      decidePending = false;
    }
  });
}

/* ---------- the deliverable shown in the centre (a switcher when a run makes several) ---------- */
let chosenKind = params.get("kind") || "";     // empty = follow what's being made now
let live = null;
let liveSig = "";
let liveAt = 0;
let liveBusy = false;

function currentKind(s) {
  const ds = s.deliverables || [];
  if (chosenKind && ds.some((d) => d.kind === chosenKind)) return chosenKind;
  return (ds.find((d) => d.state === "working" || d.state === "draft") || [...ds].reverse().find((d) => d.state !== "todo") || ds[ds.length - 1])?.kind || "";
}

/** Fetches the live output when something that changes it moved (a part's state, a new version), or every few s. */
async function refreshLive(force = false) {
  const s = store.s;
  const m = store.map;
  const kind = currentKind(s);
  const sig = [kind, s.status, (m.buildings || []).map((b) => `${b.id}:${b.state}`).join(","), (s.deliverables || []).map((d) => `${d.kind}${d.state}${d.version || 0}`).join(",")].join("|");
  if (liveBusy || (!force && sig === liveSig && Date.now() - liveAt < (s.status === "working" ? 4000 : 30000))) return;
  liveBusy = true;
  liveSig = sig;
  liveAt = Date.now();
  try {
    const l = await api.live(kind && (s.deliverables || []).length > 1 ? kind : "");
    if (l) {
      live = l;
      render();
    }
  } catch {
    /* the next poll tries again */
  } finally {
    liveBusy = false;
  }
}

function openDeliverable(kind) {
  const d = (store.s.deliverables || []).find((x) => x.kind === (kind || currentKind(store.s)));
  const url = d?.url ? d.url + (pastRun && !d.url.includes("run=") ? `${d.url.includes("?") ? "&" : "?"}run=${encodeURIComponent(pastRun)}` : "") : null;
  if (url) window.open(url, "_blank", "noopener");
  else toast("Nothing to open yet. It shows here as it's built.");
}
openBtn.addEventListener("click", () => openDeliverable());

/* ---------- the question: one card inline at its section, one from Asha in the team panel ---------- */
let qKey = "";
let qInline = null;
let decidedKey = "";
let decidedNode = null;

function questionAbout(d, parts) {
  const p = parts.find((x) => x.step === "ask");
  return { part: p || null, about: p ? `about the ${lower1(p.name)}` : d.kind === "proposal" ? "about the plan" : d.kind === "style" || d.kind === "design" ? "about the look" : d.kind === "facts" ? "about your details" : d.kind === "usage" ? "about usage" : "for you" };
}

function questionCard(d, parts, where) {
  const { part, about } = questionAbout(d, parts);
  const opts = { onAnswer: (body) => answer(d, body), readOnly };
  const inner = d.kind === "proposal" ? renderProposal(d, opts) : renderDecision(d, opts);
  const waits = part ? `${TEAM[part.person].name} waits on this. Everything else keeps going.` : d.kind === "proposal" ? "Nothing is built until you say go." : "The team waits on this.";
  const show = where === "panel" && part?.anchor ? h("button", { class: "st-link", type: "button", onclick: () => goPart(part) }, "Show me where") : null;
  // in Asha's own panel her name is already the heading: the card just says what it is about
  const head = where === "panel" ? h("p", { class: "st-qabout" }, `A question ${about}`)
    : h("div", { class: "st-qhead" }, h("span", { class: "st-qav", html: avatar("asha", 34) }), h("div", null, h("b", null, "Asha"), h("small", null, about)));
  return h("div", { class: `st-qcard kind-${d.kind}`, "data-no-gesture": "" }, head, inner, h("p", { class: "st-qnote" }, show, show ? " · " : null, waits));
}

/** The "Decided for you" lines: what Decide for me chose lately, each with Change (a message to Asha). */
function decidedStrip(s) {
  if (readOnly || ENDED.includes(s.status) || !s.settings?.no_questions) return null;
  const recs = s.chat.filter((m) => m.kind === "record" && m.answer === "Decided for you").slice(-2);
  if (!recs.length) return null;
  const k = recs.map((r) => r.id).join(",");
  if (k === decidedKey && decidedNode) return decidedNode;
  decidedKey = k;
  decidedNode = h("div", { class: "st-decided-list" }, ...recs.map((r) => {
    const change = h("button", { class: "st-link", type: "button" }, "Change");
    change.addEventListener("click", () => openMate("asha", { draft: `About "${r.title}": I'd rather ` }));
    return h("div", { class: "st-decided" }, h("span", { class: "st-qav", html: avatar("asha", 22, { prop: false }) }),
      h("span", null, "Decided for you: ", h("b", null, r.title), r.summary ? ` (${r.summary})` : "", " · recommended"), change);
  }));
  return decidedNode;
}

/* ---------- the drawer (desktop: slides in from the right of the output; phone: a sheet from the bottom) ---------- */
let drawerFor = "";
let drawerSig = "";
let drawerDraft = "";

function openDrawerWith(kind, nodes) {
  drawerFor = kind;
  dbody.replaceChildren(...nodes.filter(Boolean));
  drawer.classList.add("open");
  document.body.classList.add("with-drawer");
}
function closeDrawer() {
  drawer.classList.remove("open");
  document.body.classList.remove("with-drawer");
  drawerFor = "";
  drawerSig = "";
}
$("#st-dclose").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && drawer.classList.contains("open") && !document.querySelector(".dpanel:not([hidden])")) closeDrawer();
});

function openMate(key, { draft } = {}) {
  if (draft != null) drawerDraft = draft;
  drawerSig = "";
  drawerFor = `mate:${key}`;
  renderDrawer(true);
}
function openPlan() {
  drawerSig = "";
  drawerFor = "plan";
  renderDrawer(true);
}

function renderDrawer(force = false) {
  if (!drawerFor || (!force && !drawer.classList.contains("open"))) return;
  const s = store.s;
  const parts = partsOf(s, store.map, live);
  const team = teamModel(s, store.map, parts);
  if (drawerFor === "plan") {
    const sig = `plan|${parts.map((p) => p.id + p.step).join(",")}`;
    if (!force && sig === drawerSig) return;
    drawerSig = sig;
    return openDrawerWith("plan", [h("h4", { class: "st-dtitle" }, "The plan ", h("span", { class: "st-counter tnum" }, planCount(parts))), h("div", { class: "st-plan" }, planList(parts))]);
  }
  const key = drawerFor.slice(5);
  const m = team[key];
  if (!m) return;
  const d = key === "asha" && s.decision ? s.decision : null;
  const log = logOf(key, s, parts, key === "asha" ? 5 : 4);
  const sig = `${key}|${d?.id || ""}|${m.line}|${m.parts.map((p) => p.id + p.step).join(",")}|${log.map((l) => l.id).join(",")}`;
  if (!force && sig === drawerSig) return;
  drawerSig = sig;
  const headEl = h("div", { class: "st-dhead" }, h("span", { html: avatar(key, 52) }), h("div", null, h("h4", { class: "st-dtitle" }, m.name), h("small", null, TEAM[key].role)));
  const nodes = [headEl];
  if (d) nodes.push(questionCard(d, parts, "panel"));
  else nodes.push(h("p", { class: "st-now" }, h("b", null, "Now: "), m.line));
  if (m.parts.length) {
    nodes.push(h("h3", { class: "st-dk" }, "Parts"), h("div", { class: "st-log" }, ...m.parts.map((p) => h("div", null,
      h("button", { class: "st-link", type: "button", onclick: () => goPart(p) }, p.name), ` · ${stepWord(p)}`))));
  }
  if (key === "nora") nodes.push(h("p", { class: "st-dnote" }, "Nora checks every part against your brief before it counts as done."));
  if (log.length) nodes.push(h("h3", { class: "st-dk" }, "Recent"), h("div", { class: "st-log" }, ...log.map((l) => h("div", null, h("b", null, l.to ? `${l.from} → ${l.to}: ` : `${l.from}: `), l.text))));
  if (key === "asha" && !readOnly) {
    const form = ownAnswer(async (text, btn) => {
      btn.disabled = true;
      const ok = await send(text);
      if (ok) {
        drawerDraft = "";
        toast("Sent to Asha.");
        form.querySelector("input").value = "";
      }
      btn.disabled = false;
    }, "st-say", s.decision ? "Or tell Asha something else" : "Tell Asha something (a change, a fact)");
    const inp = form.querySelector("input");
    if (drawerDraft) {
      inp.value = drawerDraft;
      form.querySelector("button").disabled = false;
      setTimeout(() => inp.focus(), 60);
    }
    inp.addEventListener("input", () => (drawerDraft = inp.value));
    nodes.push(h("h3", { class: "st-dk" }, "Message"), form);
  }
  openDrawerWith(drawerFor, nodes);
}

function stepWord(p) {
  return { done: "done", doing: "in progress", fix: "fixing", next: "next up", skip: "left out", ask: "waiting on you" }[p.step] || "";
}

/* ---------- parts: scroll the output to them, or open what they made ---------- */
function goPart(p) {
  if (isPhone()) closeDrawer();
  if (p.anchor && output.goTo(p.anchor)) return;
  if (p.state === "done" && p.output) return openOutputOf(p);
  toast(p.anchor ? `${p.name} isn't on the page yet.` : `${p.name} is notes for the team, not a section of the page.`);
}

async function openOutputOf(p) {
  let o;
  try {
    o = await api.output(p.id);
  } catch {
    toast("That output couldn't be loaded. Try again in a moment.");
    return;
  }
  const docUrl = o.kind === "document" && o.doc ? (store.s.deliverables || []).find((d) => d.kind === o.doc)?.url || null : null;
  details.openOutput(o, { status: `${TEAM[p.person].name} · ${p.state === "done" ? "Done" : stepWord(p)}`, controls: controlsFor(p), docUrl });
}

function controlsFor(p) {
  if (readOnly || !p || p.id.startsWith("p-")) return [];
  const st = store.s.status;
  const liveRun = st === "working" || st === "paused" || st === "needs_you";
  const note = { label: "Note", icon: "note", note: true, placeholder: `A short note about ${p.name.toLowerCase()}`, onClick: (btn, text) => control({ action: "note", target: p.id, text }, "Noted. The team will see it.") };
  const redo = { label: "Redo", icon: "redo", onClick: () => control({ action: "redo", target: p.id }, `${p.name} will be built again.`) };
  if (p.state === "done") return [redo, note];
  return liveRun ? [note] : [];
}

/** A mark on the output was tapped: a finished section opens what it made; one in progress opens its maker. */
function tagClicked(sid) {
  const parts = partsOf(store.s, store.map, live);
  const mine = parts.filter((p) => p.anchor === sid);
  const busy = mine.find((p) => p.step === "ask") || mine.find((p) => p.step === "doing" || p.step === "fix");
  if (busy?.step === "ask") return openMate("asha");
  if (busy) return openMate(busy.person);
  const done = [...mine].reverse().find((p) => p.state === "done" && p.output);
  if (done) return openOutputOf(done);
  if (mine[0]) openMate(mine[0].person);
}

/* ---------- the team rail, the plan, the phone dock ---------- */
function planCount(parts) {
  const done = parts.filter((p) => p.state === "done").length;
  return parts.length ? `${done} / ${parts.length}` : "";
}

function planList(parts) {
  const ol = h("ol");
  for (const p of parts) {
    const ic = p.step === "done" ? "✓" : p.step === "ask" ? "?" : p.step === "fix" ? "!" : "";
    const b = h("button", { class: `st-step ${p.step}`, type: "button", title: `${TEAM[p.person].name} · ${stepWord(p)}` },
      h("span", { class: "st-ic", "aria-hidden": "true" }, ic), h("span", { class: "st-nm" }, p.name),
      h("span", { class: "st-who", html: avatar(p.person, 22, { prop: false }) }), h("span", { class: "sr-only" }, `, ${TEAM[p.person].name}, ${stepWord(p)}`));
    b.addEventListener("click", () => goPart(p));
    ol.append(h("li", null, b));
  }
  if (!parts.length) ol.append(h("li", { class: "st-plan-empty" }, "The plan shows here once Asha has it."));
  return ol;
}

let railSig = "";
function renderRail(s, parts, team) {
  const sig = JSON.stringify([PEOPLE.map((k) => [team[k].line, team[k].asks, team[k].busy]), parts.map((p) => [p.id, p.step, p.person, p.name, p.anchor, p.state])]);
  if (sig === railSig) return;
  railSig = sig;
  $("#st-team").replaceChildren(...PEOPLE.map((k) => {
    const m = team[k];
    const b = h("button", { class: `st-mate${m.busy ? " is-busy" : ""}`, type: "button", "data-mate": k },
      h("span", { class: "st-mav", html: avatar(k, 40) }),
      h("span", null, h("b", null, m.name), " ", h("span", { class: "st-role" }, `· ${SHORT[k]}`), h("small", null, m.line)),
      m.asks ? h("span", { class: "st-badge" }, "1 question") : null);
    b.addEventListener("click", () => openMate(k));
    return b;
  }));
  $("#st-plancount").textContent = planCount(parts);
  $("#st-planlist").replaceWith(Object.assign(planList(parts), { id: "st-planlist" }));
  // the phone dock: the faces (Asha with a dot when she has a question) and the plan button
  $("#st-dock").replaceChildren(...PEOPLE.map((k) => {
    const b = h("button", { class: `st-face${team[k].busy ? " is-busy" : ""}`, type: "button", "aria-label": `${team[k].name}, ${SHORT[k]}: ${team[k].line}`, "data-mate": k },
      h("span", { html: avatar(k, 40, { prop: false }) }), team[k].asks ? h("span", { class: "st-pip", "aria-hidden": "true" }) : null);
    b.addEventListener("click", () => openMate(k));
    return b;
  }), (() => {
    const b = h("button", { class: "st-planbtn tnum", type: "button", id: "st-planbtn" }, parts.length ? `Plan ${planCount(parts)}` : "Plan");
    b.addEventListener("click", openPlan);
    return b;
  })());
}

/* ---------- the top bar ---------- */
function statusLine(s, parts) {
  const done = parts.filter((p) => p.state === "done").length;
  const of = parts.length ? ` · ${done} of ${parts.length} parts done` : "";
  if (s.status === "needs_you") return "Asha has a question for you";
  if (s.status === "paused") return `Paused${of}`;
  if (s.status === "working") {
    if (s.control?.stopping || s.control?.pausing) return s.status_text;
    const t = teamWords(s.status_text || "Working").replace(/^Building: .*/, "Building");
    return `${t}${t === "Building" ? of : ""}`;
  }
  if (s.status === "done") return "Done · every part finished";
  if (s.status === "done_open") {
    const n = s.ended?.open_items?.length || 1;
    return `Done · ${n} ${n === 1 ? "thing" : "things"} open`;
  }
  return statusWord(s.status, s.ended);
}

function renderTop(s, parts) {
  $("#st-proj").textContent = s.run?.title || "J2";
  $("#st-status").textContent = statusLine(s, parts);
  const dot = $("#st-dot");
  dot.dataset.tone = s.status === "needs_you" ? "ask" : s.status === "working" ? "work" : s.status === "crashed" ? "bad" : ENDED.includes(s.status) ? "done" : "idle";
  const u = s.usage || {};
  $("#st-meter").hidden = !u.budget;
  if (u.budget) {
    $("#st-usebar").style.width = `${(ratio(u.spent, u.budget) * 100).toFixed(1)}%`;
    $("#st-usetxt").textContent = `${fmtUsage(u.spent || 0)} of ${fmtUsage(u.budget)} used`;
  }
  const liveRun = !readOnly && (s.status === "working" || s.status === "paused");
  const pausedish = s.status === "paused" || s.control?.pausing;
  pauseBtn.hidden = !liveRun;
  pauseBtn.replaceChildren(icon(pausedish ? "play" : "pause", 18));
  pauseBtn.setAttribute("aria-label", pausedish ? "Resume" : "Pause");
  pauseBtn.title = pausedish ? "Resume" : "Pause";
  pauseBtn.disabled = !!s.control?.stopping;
  stopBtn.hidden = readOnly || !(liveRun || s.status === "needs_you");
  stopBtn.disabled = !!s.control?.stopping;
  $("#st-auto").hidden = readOnly || ENDED.includes(s.status);
  const kind = currentKind(s);
  const d = (s.deliverables || []).find((x) => x.kind === kind);
  openBtn.hidden = !d?.url;
  openBtn.textContent = kind === "website" ? "Open the site" : `Open the ${DELIVERABLE_LABEL[kind] || "document"}`;
}

/* ---------- the switcher (several deliverables), the ending bar ---------- */
let switchSig = "";
function renderSwitch(s) {
  const ds = s.deliverables || [];
  const el = $("#st-switch");
  el.hidden = ds.length < 2;
  const cur = currentKind(s);
  const sig = ds.map((d) => d.kind + d.state).join(",") + cur;
  if (sig === switchSig) return;
  switchSig = sig;
  el.replaceChildren(...ds.map((d) => {
    const mark = d.state === "done" ? " ✓" : d.state === "working" || d.state === "draft" ? " ·" : "";
    const b = h("button", { class: `st-tab${d.kind === cur ? " is-on" : ""}${d.state === "todo" ? " is-todo" : ""}`, type: "button", role: "tab", "aria-selected": String(d.kind === cur) }, `${d.label || DELIVERABLE_LABEL[d.kind] || d.kind}${mark}`);
    b.addEventListener("click", () => {
      chosenKind = d.kind;
      live = null;
      refreshLive(true);
      render();
    });
    return b;
  }));
}

let endKey = "";
function renderEnd(s) {
  const e = s.ended;
  const bar = $("#st-endbar");
  const k = e && !readOnly ? `${s.run?.id}|${JSON.stringify(e)}|${(s.deliverables || []).some((d) => d.url)}` : "";
  if (k === endKey) return;
  endKey = k;
  bar.hidden = !k;
  bar.replaceChildren(...(k ? [renderEnding(e, s, endingActions())] : []));
}

/* ---------- the nudge: the question is off-screen ---------- */
function syncNudge() {
  const s = store.s;
  const where = s.decision ? output.inlineWhere() : null;
  const off = where !== "below" && where !== "above";
  nudge.classList.toggle("is-off", off);
  if (!off) {
    $("#st-nudge-text").textContent = `Asha has a question for you, further ${where === "below" ? "down" : "up"}`;
    $("#st-nudge-arrow").textContent = where === "below" ? "↓" : "↑";
  }
}
nudge.addEventListener("click", () => output.scrollToInline());

/* ---------- render ---------- */
let lastDecision = null;
let lastEnd = "";

function render() {
  const s = store.s;
  const sending = store.pending.length > 0;
  const showStart = store.loaded && !readOnly && s.status === "idle" && s.chat.length === 0 && !sending && !s.decision;
  $("#offline").hidden = store.loaded || store.connection !== "lost";
  startEl.hidden = !showStart;
  workEl.hidden = !store.loaded || showStart;
  document.body.dataset.view = showStart ? "start" : "work";
  if (!decidePending) syncDecide(!!s.settings?.no_questions);
  document.title = s.run?.title ? `${s.run.title} · J2` : "J2";
  if (showStart) {
    loadRecent();
    closeDrawer();
    return;
  }
  if (!store.loaded) return;

  const parts = partsOf(s, store.map, live);
  const team = teamModel(s, store.map, parts);
  renderTop(s, parts);
  renderRail(s, parts, team);
  renderSwitch(s);
  renderEnd(s);

  // the centre: the live output (or, before the first answer from the server, the planned parts as a sketch)
  const kind = currentKind(s);
  let l = live && (!kind || (live.kind === "website" ? kind === "website" : live.doc === kind)) ? live : null;
  if (!l || (l.kind === "website" && !l.started)) l = sketch(s, parts, l, kind);
  output.update(l, parts);
  $("#st-url").textContent = l.kind === "website" ? `${l.title || "your site"} · live preview` : `${(l.doc || "").toUpperCase()} · live`;

  // the question, inline at its section (or at the top), and the decided lines while Decide for me is on
  const d = s.decision;
  const k = d ? `${d.id}|${d.kind}|${d.proposal?.estimate ?? ""}|${parts.find((x) => x.step === "ask")?.id || ""}` : "";
  if (k !== qKey) {
    qKey = k;
    qInline = d ? questionCard(d, parts, "inline") : null;
  }
  const { part } = d ? questionAbout(d, parts) : { part: null };
  const inl = qInline || decidedStrip(s);
  output.setInline(inl, qInline && part?.anchor && live?.anchors && Object.values(live.anchors).includes(part.anchor) ? part.anchor : null);
  syncNudge();
  renderDrawer();

  if (d && d.id !== lastDecision) {
    announce(`Asha has a question: ${d.kind === "proposal" ? d.proposal?.summary || "the plan is ready" : d.happening}`);
    if (!readOnly && output.inlineWhere() === "in") toast("Asha has a question for you");
  }
  lastDecision = d?.id || null;
  const ek = s.ended ? `${s.run?.id}|${s.ended.kind}` : "";
  if (ek && ek !== lastEnd) announce(`${statusWord(s.status, s.ended)}. ${s.ended.text || ""}`);
  lastEnd = ek;
  refreshLive();
}

/** Before the site exists: the planned parts as calm placeholders, each with who will make it. */
function sketch(s, parts, l, kind) {
  const isDoc = kind && kind !== "website";
  const blocks = parts.filter((p) => p.state !== "skipped").map((p) => ({ anchor: p.id, parts: [p.id], state: p.state === "done" ? "done" : "waiting", markdown: null, name: p.name,
    note: p.state === "done" ? "Done" : p.state === "working" ? `${TEAM[p.person].name} is on it` : "Coming up" }));
  const empty = s.status === "working" ? "Asha is reading your brief. The plan shows here in a moment." : ENDED.includes(s.status) ? "Nothing was built in this run." : "The plan shows here once Asha has it.";
  const anchors = Object.fromEntries(parts.map((p) => [p.id, p.id]));
  if (l?.kind === "website" && kind === "website" && !parts.length && (s.deliverables || []).length > 1) return { ...l, kind: "website", blocks: [], empty: "The website starts after the documents.", anchors, key: "sketch-later" };
  return { kind: isDoc ? "document" : "website", doc: isDoc ? kind : null, title: s.run?.title || "", started: false, blocks, empty, anchors, part_kinds: {},
    key: `sketch|${kind}|${blocks.map((b) => b.anchor + b.state + b.note).join(",")}|${empty}` };
}

/* ---------- boot ---------- */
if (readOnly) {
  const banner = $("#banner");
  banner.hidden = false;
  banner.append(h("span", null, "You're looking at a past run."), h("a", { href: location.pathname + (fixture ? `?fixture=${fixture}` : "") }, "Back to now"));
}
store.subscribe(render);
window.__j2 = { store, api, output }; // for the UI checks
if (fixture) api.ready.catch((e) => document.body.append(h("p", { class: "noscript" }, e.message)));
poller = startPolling(api, store);
