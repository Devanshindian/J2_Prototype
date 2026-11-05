// Talks to /api/v2/* (see api-contract.md), or to a local fixture when ?fixture=<name> is set.
// Both sources expose the same interface: getState(since, bsince), getMap(since), say, decide, newRun, runs,
// settings, control.

const BASE = "/api/v2";

export class ApiError extends Error {
  constructor(status, message) {
    super(message || `HTTP ${status}`);
    this.status = status;
  }
}

async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty body is fine */
  }
  if (!res.ok) throw new ApiError(res.status, data?.error);
  return data;
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Retry while the server answers 409 (a turn is running). Gentle backoff, about a minute in total. */
async function retryOn409(fn, onWaiting) {
  const delays = [800, 1500, 2500, 4000, 5000, 5000, 6000, 8000, 8000, 10000, 10000];
  for (let i = 0; ; i++) {
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 409 || i >= delays.length) throw e;
      onWaiting?.(true);
      await wait(delays[i]);
    }
  }
}

export class HttpApi {
  constructor({ run } = {}) {
    this.run = run || null;
  }
  getState(since = 0, bsince = 0) {
    const q = new URLSearchParams({ since, bsince });
    if (this.run) q.set("run", this.run);
    return request("GET", `${BASE}/state?${q}`);
  }
  say(text, onWaiting) {
    return retryOn409(() => request("POST", `${BASE}/say`, { text }), onWaiting);
  }
  decide(body) {
    // 409 here means the decision is no longer open: the caller just refreshes.
    return request("POST", `${BASE}/decide`, body);
  }
  newRun(onWaiting) {
    return retryOn409(() => request("POST", `${BASE}/new`, {}), onWaiting);
  }
  runs() {
    return request("GET", `${BASE}/runs`);
  }
  /** Run settings: {no_questions: bool}. Returns {ok, settings}. */
  settings(body) {
    return request("POST", `${BASE}/settings`, body);
  }
  /** The kingdom view's data (departments, units, buildings, flows after `since`, attention). */
  getMap(since = 0) {
    const q = new URLSearchParams({ since });
    if (this.run) q.set("run", this.run);
    return request("GET", `${BASE}/map?${q}`);
  }
  /** A control: {action: pause|resume|stop|skip|redo|note, target?, text?}. 409 with {error} when it can't apply. */
  control(body) {
    return request("POST", `${BASE}/control`, body);
  }
  /** "See output": what a finished part made (api-contract.md, /api/v2/output). */
  output(id) {
    const q = new URLSearchParams({ id });
    if (this.run) q.set("run", this.run);
    return request("GET", `${BASE}/output?${q}`);
  }
  /** The studio view's centre: a deliverable as it stands (api-contract.md, /api/v2/live). `kind` empty = current. */
  live(kind) {
    const q = new URLSearchParams();
    if (kind) q.set("kind", kind);
    if (this.run) q.set("run", this.run);
    return request("GET", `${BASE}/live?${q}`);
  }
}

/* ------------------------------------------------------------------ */
/* Fixture mode: a local stand-in for the backend, with a little life. */
/* ------------------------------------------------------------------ */

const FIXTURES = "/ui/dev/fixtures";
const clone = (o) => JSON.parse(JSON.stringify(o));
const now = () => new Date().toTimeString().slice(0, 8);

export class FixtureApi {
  constructor(name) {
    this.name = name;
    this.s = null;
    this.ready = this.load(name);
    this.tickEvery = 2200;
    this.lastTick = Date.now();
    this.ticks = 0;
    this.linePos = 0;
    this.flowId = 0;
  }

  async load(name) {
    const res = await fetch(`${FIXTURES}/${name}.json`, { cache: "no-store" });
    if (!res.ok) throw new Error(`No fixture named "${name}"`);
    this.s = await res.json();
    this.name = name;
    this.ticks = 0;
    this.linePos = 0;
    this.lastTick = Date.now();
    const m = this.s.map || (this.s.map = { departments: [], units: [], buildings: [], flows: [], attention: null, counts: { done: 0, total: 0 } });
    m.flows = m.flows || [];
    // flow ids keep climbing across fixtures, so a fixture change never re-shows an old light
    this.flowId = Math.max(this.flowId, ...m.flows.map((f) => f.id || 0), 0);
    for (const f of m.flows) if (!f.id) f.id = ++this.flowId;
  }

  nextId(list) {
    return list.reduce((m, x) => Math.max(m, x.id || 0), 0) + 1;
  }

  /** Simulated movement while "working": new backstage lines, usage growing, preview version bumps. */
  tick() {
    const s = this.s;
    const sim = s._sim;
    if (!sim || s.status !== "working") return;
    const due = Math.floor((Date.now() - this.lastTick) / this.tickEvery);
    for (let i = 0; i < Math.min(due, 3); i++) this.step(s, sim);
    if (due > 0) this.lastTick = Date.now();
  }

  step(s, sim) {
    this.ticks++;
    const pool = sim.lines || [];
    if (pool.length) {
      const line = pool[this.linePos++ % pool.length];
      s.backstage.forEach((b) => (b.active = false));
      const { status_text, ...rest } = line;
      s.backstage.push({ id: this.nextId(s.backstage), t: now(), detail: { kind: "generic", decided: null, why: null }, ...rest, active: true });
      if (line.status_text) s.status_text = line.status_text;
      this.addFlow(line.from, line.to, line.text);
    }
    this.advanceMap(s, sim);
    const u = s.usage;
    if (u && u.budget) {
      const add = sim.spend || 15000;
      u.spent = Math.min(Math.round(u.budget * 0.97), (u.spent || 0) + add);
      if (u.by_phase) u.by_phase.building = (u.by_phase.building || 0) + add;
      const task = findTask(s.plan, s.working_now?.task_id);
      if (task) task.usage = Math.min(task.share || Infinity, (task.usage || 0) + Math.round(add * 0.7));
    }
    if (sim.bump_every && this.ticks % sim.bump_every === 0) {
      for (const d of s.deliverables || []) {
        if (d.state === "working" || d.state === "draft") d.version = (d.version || 1) + 1;
      }
    }
  }

  async getState(since = 0, bsince = 0) {
    await this.ready;
    this.tick();
    const out = clone(this.s);
    delete out._sim;
    delete out._next;
    delete out.map;
    out.chat = (out.chat || []).filter((m) => m.id > since);
    out.backstage = (out.backstage || []).filter((m) => m.id > bsince);
    return out;
  }

  async getMap(since = 0) {
    await this.ready;
    this.tick();
    const m = clone(this.s.map);
    m.flows = (m.flows || []).filter((f) => f.id > since).slice(-24);
    m.status = this.s.status;
    return m;
  }

  /** A hand-off between two units (by their labels; "You" is the castle) becomes a travelling light. */
  addFlow(fromLabel, toLabel, what) {
    const m = this.s.map;
    const find = (label) => (label === "You" ? "castle" : (m.units || []).find((u) => u.label === label)?.id);
    const from = find(fromLabel);
    const to = find(toLabel);
    if (!from || !to || from === to) return;
    m.flows.push({ id: ++this.flowId, from, to, t: now(), what: String(what || "").split(". ")[0] });
    if (m.flows.length > 40) m.flows.splice(0, m.flows.length - 40);
    const u = (m.units || []).find((x) => x.id === from);
    if (u && u.role !== "builder") u.doing = String(what || "");
  }

  /** The map lives: working parts fill up; a full one is done, its builder rests, and the next part whose
   * dependencies are done starts with a new builder (the plan and the team's talk move with it). */
  advanceMap(s, sim) {
    const m = s.map;
    if (!m?.buildings?.length) return;
    const rate = sim.fill || 0.07;
    const byId = Object.fromEntries(m.buildings.map((b) => [b.id, b]));
    const planTask = (id) => findTask(s.plan, id);
    for (const b of m.buildings) {
      if (b.state !== "working") continue;
      b.progress = Math.min(1, +(b.progress + rate * (0.6 + Math.random() * 0.8)).toFixed(3));
      if (b.share) b.usage = Math.min(b.share, Math.round(b.share * (0.1 + 0.85 * b.progress)));
      if (b.progress >= 1) {
        b.state = "done";
        b.doing = "Done";
        const t = planTask(b.id);
        if (t) t.status = "done";
        m.units = m.units.filter((u) => u.id !== `u-${b.id}`);
        this.addFlow(`Builder · ${b.name}`, "Gatekeeper", `${b.name} is in.`);
      }
    }
    // start the next part(s) when fewer than two work at once
    let working = m.buildings.filter((b) => b.state === "working");
    for (const b of m.buildings) {
      if (working.length >= 2) break;
      if (b.state !== "waiting" || !b.depends_on.every((d) => byId[d]?.state === "done" || byId[d]?.state === "skipped")) continue;
      b.state = "working";
      b.progress = 0.08;
      b.doing = `Starting on ${b.name.toLowerCase()}`;
      const t = planTask(b.id);
      if (t) {
        t.status = "working";
        t.waits_for = [];
      }
      m.units.push({ id: `u-${b.id}`, role: "builder", label: `Builder · ${b.name}`, dept: b.dept, at: b.id, state: "working", doing: b.doing });
      this.addFlow("Scheduler", `Builder · ${b.name}`, `Your turn: ${b.name.toLowerCase()}.`);
      working = m.buildings.filter((x) => x.state === "working");
    }
    for (const b of m.buildings) {
      if (b.state === "waiting") {
        const open = b.depends_on.filter((d) => byId[d] && byId[d].state !== "done" && byId[d].state !== "skipped").map((d) => byId[d].name);
        b.doing = open.length ? `Waits for ${open.join(" and ")}` : "Waiting its turn";
        const t = planTask(b.id);
        if (t) t.waits_for = open;
      }
    }
    m.counts = { done: m.buildings.filter((b) => b.state === "done").length, total: m.buildings.length };
    const first = working[0];
    if (first) {
      s.working_now = { who: `Builder · ${first.name}`, task_id: first.id };
      if (!sim.lines?.length) s.status_text = `Building ${first.name.toLowerCase()}`;
    }
  }

  async control(body) {
    await this.ready;
    await wait(200);
    const s = this.s;
    const a = body.action;
    const rec = (title, summary) => s.chat.push({ id: this.nextId(s.chat), t: now(), from: "team", kind: "record", title, summary, answer: "", detail: [] });
    if (a === "pause") {
      if (s.status !== "working") throw new ApiError(409, "nothing is running right now");
      s.control = { paused: false, pausing: true, stopping: false };
      s.status_text = "Pausing…";
      setTimeout(() => {
        if (!s.control.pausing) return;
        s.control = { paused: true, pausing: false, stopping: false };
        s.status = "paused";
        s.status_text = "Paused";
        s.map.units.forEach((u) => (u.state = u.state === "working" ? "idle" : u.state));
        rec("Paused", "The team holds between steps until you resume.");
      }, 900);
      return { ok: true, state: "pausing" };
    }
    if (a === "resume") {
      if (!s.control?.paused && !s.control?.pausing) throw new ApiError(409, "it isn't paused");
      s.control = { paused: false, pausing: false, stopping: false };
      s.status = "working";
      s.status_text = "Building";
      s.map.units.forEach((u) => (u.state = u.role === "builder" ? "working" : u.state));
      rec("Resumed", "");
      this.lastTick = Date.now();
      return { ok: true, state: "running" };
    }
    if (a === "stop") {
      if (!["working", "paused", "needs_you"].includes(s.status)) throw new ApiError(409, "nothing is running right now");
      s.control = { paused: false, pausing: false, stopping: true };
      s.status_text = "Stopping…";
      setTimeout(() => this.goTo(s._next?.stop || "stopped", 0), 900);
      return { ok: true, state: "stopping" };
    }
    const b = (s.map.buildings || []).find((x) => x.id === body.target);
    if (!b) throw new ApiError(409, "no such part");
    if (a === "skip") {
      if (b.state !== "waiting" && b.state !== "needs_fix") throw new ApiError(409, b.state === "done" ? "it's already done" : "it can't be skipped now");
      b.state = "skipped";
      b.progress = 0;
      b.doing = "Left out";
      const t = findTask(s.plan, b.id);
      if (t) t.status = "skipped";
      rec(`Skipped: ${b.name}`, "Left out of the plan on your decision.");
      s.map.counts = { done: s.map.buildings.filter((x) => x.state === "done").length, total: s.map.buildings.length };
      return { ok: true, state: "applied" };
    }
    if (a === "redo") {
      if (b.state !== "done" && b.state !== "needs_fix") throw new ApiError(409, "it isn't built yet");
      b.state = "working";
      b.progress = 0.08;
      b.doing = body.text || "Building it again";
      const t = findTask(s.plan, b.id);
      if (t) t.status = "working";
      if (!s.map.units.some((u) => u.id === `u-${b.id}`)) s.map.units.push({ id: `u-${b.id}`, role: "builder", label: `Builder · ${b.name}`, dept: b.dept, at: b.id, state: "working", doing: b.doing });
      rec(`Redo: ${b.name}`, body.text || "Built again on your decision.");
      if (s.status !== "working") {
        s.status = "working";
        s.status_text = `Building ${b.name.toLowerCase()} again`;
        s.ended = null;
      }
      return { ok: true, state: "queued" };
    }
    if (a === "note") {
      if (!body.text) throw new ApiError(400, "write the note first");
      rec(`Note for ${b.name}`, body.text);
      return { ok: true, state: "applied" };
    }
    throw new ApiError(400, "unknown action");
  }

  pushChat(from, text) {
    this.s.chat.push({ id: this.nextId(this.s.chat), t: now(), from, text });
  }

  async goTo(name, delay = 900) {
    await wait(delay);
    await this.load(name);
  }

  async say(text) {
    await this.ready;
    await wait(250);
    this.pushChat("you", text);
    const next = this.s._next?.say;
    if (next) {
      this.s.status = "working";
      this.s.status_text = "Reading your request";
      this.goTo(next, 1600);
    } else {
      setTimeout(() => this.pushChat("team", "Noted. I'll fold that in."), 1200);
    }
    return { ok: true };
  }

  async decide({ decision_id, option_id, text, fields }) {
    await this.ready;
    await wait(300);
    const d = this.s.decision;
    if (!d || d.id !== decision_id) throw new ApiError(409, "That question is no longer open.");
    const opt = d.options.find((o) => o.id === option_id);
    const filled = Object.values(fields || {}).filter(Boolean);
    this.pushChat("you", text || (filled.length ? filled.join(" · ") : opt?.label || "OK"));

    // "Make it smaller": trim the proposal in place and ask again.
    if (d.kind === "proposal" && option_id === "smaller") {
      const p = d.proposal;
      p.estimate = Math.round(p.estimate * 0.72);
      if (p.parts.length > 3) p.parts = p.parts.slice(0, -2);
      p.summary = p.summary.replace(/^A /, "A smaller ");
      d.id = d.id + "s";
      this.s.usage.estimate = p.estimate;
      this.pushChat("team", "Here's a smaller version.");
      return { ok: true };
    }

    this.s.decision = null;
    this.s.status = "working";
    this.s.status_text = "On it";
    const next = this.s._next?.[option_id] || this.s._next?.["*"];
    if (next) this.goTo(next);
    return { ok: true };
  }

  async newRun() {
    await wait(200);
    await this.load(this.s?._next?.new || "start");
    return { ok: true };
  }

  async runs() {
    const res = await fetch(`${FIXTURES}/_runs.json`, { cache: "no-store" });
    return res.ok ? res.json() : [];
  }

  async output(id) {
    await this.ready;
    await wait(80);
    const o = this.s._outputs?.[id];
    if (!o) throw new ApiError(404, "no such part");
    return clone(o);
  }

  /** The studio view's centre from a fixture: its `_live` when it has one, else a sketch of the parts on the map
   * (blocks with no text, so the page draws every part as a placeholder with who is on it). */
  async live(kind) {
    await this.ready;
    const l = this.s._live?.[kind || "current"] || this.s._live?.current;
    if (l) return clone(l);
    const bs = this.s.map?.buildings || [];
    const doc = (this.s.deliverables || []).find((d) => d.state === "working" || d.state === "draft")?.kind;
    const k = kind || (doc && doc !== "website" ? doc : "website");
    const blocks = bs.map((b) => ({ anchor: b.id, parts: [b.id], state: b.state === "done" ? "done" : "waiting",
      markdown: b.state === "done" ? `## ${b.name}\n\n${b.doing && b.doing !== "Done" ? b.doing : "Done."}` : null, name: b.name, note: "Coming up" }));
    return { kind: k === "website" ? "website" : "document", doc: k === "website" ? null : k, title: this.s.run?.title || "",
      blocks, url: null, started: false, built: false, sketch: true, pending: [], anchors: Object.fromEntries(bs.map((b) => [b.id, b.id])),
      part_kinds: {}, key: JSON.stringify(blocks.map((b) => [b.anchor, b.state])) };
  }

  async settings(body) {
    await this.ready;
    await wait(150);
    this.s.settings = { ...(this.s.settings || {}), ...body };
    return { ok: true, settings: this.s.settings };
  }
}

function findTask(plan, id) {
  if (!plan || !id) return null;
  for (const g of plan.groups || []) for (const t of g.tasks || []) if (t.id === id) return t;
  return null;
}

/* ------------------------------------------------------------------ */
/* Polling                                                             */
/* ------------------------------------------------------------------ */

/**
 * Polls about every second with since/bsince deltas, slows down when the tab is hidden
 * or the server is unreachable. store.apply() returns true when the run changed and a
 * full refetch is needed.
 */
export function startPolling(api, store, { interval = 1000 } = {}) {
  let timer = null;
  let stopped = false;
  let failures = 0;
  let busy = false;
  let again = false;

  async function once() {
    if (stopped) return;
    if (busy) {
      again = true; // a poll is in flight; run another right after it
      return;
    }
    busy = true;
    clearTimeout(timer);
    try {
      const [data, map] = await Promise.all([api.getState(store.lastChatId, store.lastBackId), api.getMap ? api.getMap(store.lastFlowId) : null]);
      failures = 0;
      store.setConnection("ok");
      if (store.apply(data)) {
        const [full, fullMap] = await Promise.all([api.getState(0, 0), api.getMap ? api.getMap(0) : null]);
        store.apply(full);
        if (fullMap) store.applyMap(fullMap);
      } else if (map) {
        store.applyMap(map);
      }
    } catch (e) {
      failures++;
      if (failures >= 2) store.setConnection("lost");
      // a bug in a render must never hide as "offline": say so in the console
      if (!(e instanceof ApiError) && !(e instanceof TypeError && /fetch|network/i.test(e.message))) console.error(e);
    }
    busy = false;
    if (again) {
      again = false;
      return once();
    }
    schedule();
  }

  function schedule() {
    if (stopped) return;
    clearTimeout(timer);
    let ms = interval;
    if (document.hidden) ms = 5000;
    if (failures) ms = Math.min(8000, 1000 * 2 ** Math.min(failures, 3));
    timer = setTimeout(once, ms);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !stopped) once();
  });

  once();
  return {
    now: () => once(),
    stop() {
      stopped = true;
      clearTimeout(timer);
    },
  };
}
