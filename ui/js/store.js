// Holds the latest state. Chat and backstage arrive as deltas and are merged by id.
// Local-only bits (messages still sending, panel state) live here too.

export function createStore() {
  const listeners = new Set();
  let runId = undefined;

  const store = {
    s: {
      run: null,
      status: "idle",
      status_text: "",
      usage: null,
      decision: null,
      chat: [],
      backstage: [],
      working_now: null,
      plan: null,
      deliverables: [],
      ended: null,
      settings: { no_questions: false },
      control: { paused: false, pausing: false, stopping: false },
    },
    // the kingdom view (/api/v2/map): flows arrive as deltas and are kept by id
    map: { departments: [], units: [], buildings: [], flows: [], attention: null, status: "idle", counts: { done: 0, total: 0 } },
    mapLoaded: false,
    lastFlowId: 0,
    loaded: false,
    connection: "ok",
    pending: [], // {key, text, afterId, waiting}
    lastChatId: 0,
    lastBackId: 0,

    /** Merge a /state response. Returns true if the run changed and a full refetch is needed. */
    apply(data) {
      if (!data) return false;
      const id = data.run?.id ?? "";
      if (runId !== undefined && id !== runId) {
        runId = id;
        this.s.chat = [];
        this.s.backstage = [];
        this.lastChatId = 0;
        this.lastBackId = 0;
        this.map.flows = [];
        this.lastFlowId = 0;
        return true;
      }
      runId = id;

      const { chat = [], backstage = [], ...rest } = data;
      Object.assign(this.s, rest);
      mergeById(this.s.chat, chat);
      mergeById(this.s.backstage, backstage);
      // Only one line can be active: the newest one the server marks.
      if (backstage.length) {
        const fresh = new Map(backstage.map((b) => [b.id, b.active]));
        this.s.backstage.forEach((b) => {
          if (!fresh.has(b.id)) b.active = false;
        });
      }
      this.lastChatId = maxId(this.s.chat, this.lastChatId);
      this.lastBackId = maxId(this.s.backstage, this.lastBackId);

      // A pending message is confirmed once the server shows a newer message from "you".
      this.pending = this.pending.filter(
        (p) => !this.s.chat.some((m) => m.from === "you" && m.id > p.afterId)
      );
      this.loaded = true;
      this.emit();
      return false;
    },

    /** Merge a /map response: everything but the flows is replaced; new flows are appended by id. */
    applyMap(data) {
      if (!data) return;
      const { flows = [], ...rest } = data;
      Object.assign(this.map, rest);
      for (const f of flows) {
        if (f.id > this.lastFlowId) {
          this.map.flows.push(f);
          this.lastFlowId = f.id;
        }
      }
      if (this.map.flows.length > 80) this.map.flows.splice(0, this.map.flows.length - 80);
      this.mapLoaded = true;
      this.emit();
    },

    addPending(text) {
      const p = { key: Math.random().toString(36).slice(2), text, afterId: this.lastChatId, waiting: false };
      this.pending.push(p);
      this.emit();
      return p;
    },
    markPending(p, waiting) {
      p.waiting = waiting;
      this.emit();
    },
    dropPending(p) {
      this.pending = this.pending.filter((x) => x !== p);
      this.emit();
    },

    setConnection(c) {
      if (c === this.connection) return;
      this.connection = c;
      this.emit();
    },

    /** Forget everything (used after "Start something new"). */
    reset() {
      runId = undefined;
      this.s.chat = [];
      this.s.backstage = [];
      this.s.decision = null;
      this.s.ended = null;
      this.s.status = "idle";
      this.s.plan = null;
      this.s.deliverables = [];
      this.s.usage = null;
      this.s.settings = { no_questions: false };
      this.s.control = { paused: false, pausing: false, stopping: false };
      this.map = { departments: [], units: [], buildings: [], flows: [], attention: null, status: "idle", counts: { done: 0, total: 0 } };
      this.lastFlowId = 0;
      this.pending = [];
      this.lastChatId = 0;
      this.lastBackId = 0;
      this.emit();
    },

    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    emit() {
      for (const fn of listeners) fn(this);
    },
  };
  return store;
}

function mergeById(list, items) {
  for (const it of items) {
    const i = list.findIndex((x) => x.id === it.id);
    if (i >= 0) list[i] = it;
    else list.push(it);
  }
  list.sort((a, b) => a.id - b.id);
}

function maxId(list, floor) {
  return list.reduce((m, x) => Math.max(m, x.id || 0), floor);
}
