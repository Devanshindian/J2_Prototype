// The studio team: five friendly people instead of six org boxes. Built by code from the run's state and map:
// Asha is the lead (the client lead, and the planner's work; she asks the questions), Nora checks (the gatekeeper,
// the quality check and the plan reviewer), and the makers are grouped by what a part is (the map's `kind` per part):
// Mira writes, Kabir designs, Dev builds. The budget lead and the scheduler stay out of sight.

export const PEOPLE = ["asha", "mira", "kabir", "dev", "nora"];
export const SHORT = { asha: "lead", mira: "writer", kabir: "designer", dev: "builder", nora: "checker" };
export const COLOR = { asha: "#3D5A80", mira: "#C8553D", kabir: "#2A9D8F", dev: "#C98A1B", nora: "#6D597A" };
export const KIND_PERSON = { writer: "mira", designer: "kabir", builder: "dev" };
const ROLE_PERSON = { client: "asha", planner: "asha", reviewer: "nora", gatekeeper: "nora", quality: "nora" };
const LABEL_PERSON = { "Client lead": "asha", Planner: "asha", "Plan reviewer": "nora", Gatekeeper: "nora", "Quality check": "nora" };
const NAME = { asha: "Asha", mira: "Mira", kabir: "Kabir", dev: "Dev", nora: "Nora" };

/** Plan step state for a part: done, doing, fix (needs a fix), next (waiting), skip; "ask" when a question is about it. */
const STEP = { done: "done", working: "doing", needs_fix: "fix", waiting: "next", skipped: "skip" };

export const andList = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
const count = (n) => (n === 1 ? "one part" : `${n} parts`);
/** "Team section" reads "Team" in a one-line "On Team and FAQ" (the plan keeps the full name). */
const short = (name) => name.replace(/\s+(section|part)$/i, "") || name;

/** Every part in plan order, joined with its map building: id, name, state, step, kind, person, anchor, output. */
export function partsOf(s, map, live) {
  const bs = new Map((map.buildings || []).map((b) => [b.id, b]));
  const tasks = (s.plan?.groups || []).flatMap((g) => g.tasks || []);
  const rows = tasks.length ? tasks.map((t) => ({ t, b: bs.get(t.id) })) : (map.buildings || []).map((b) => ({ t: null, b }));
  const attention = s.decision ? map.attention : null;
  return rows.map(({ t, b }) => {
    const id = t?.id || b.id;
    const state = b?.state || t?.status || "waiting";
    const kind = b?.kind || live?.part_kinds?.[id] || "builder";
    return {
      id,
      name: t?.name || b?.name || id,
      summary: t?.summary || "",
      state,
      step: attention === id ? "ask" : STEP[state] || "next",
      kind,
      person: KIND_PERSON[kind] || "dev",
      anchor: live?.anchors?.[id] || null,
      dept: b?.dept || null,
      output: b?.output || null,
      doing: b?.doing || "",
    };
  });
}

/** Who said a backstage line ("Builder · FAQ" is the person who makes the FAQ part), or null for the hidden roles. */
export function personOfLabel(label, parts) {
  if (!label) return null;
  if (label === "You") return "you";
  if (label.startsWith("Builder · ")) {
    const nm = label.slice("Builder · ".length);
    return parts.find((p) => p.name === nm)?.person || "dev";
  }
  return LABEL_PERSON[label] || null;
}

/** A status line in the team's words: "Planner is planning the parts" reads "Asha is planning the parts". */
export function teamWords(text) {
  return String(text || "")
    .replace(/^(Client lead|Planner)\b/, "Asha")
    .replace(/^(Quality check|Gatekeeper|Plan reviewer)\b/, "Nora")
    .replace(/^(Budget lead|Scheduler)\b/, "The team");
}

/** The team panel's model: per person, a one-line "now", their parts, and whether they wait on the person. */
export function teamModel(s, map, parts) {
  const units = map.units || [];
  const unit = (role) => units.find((u) => u.role === role) || null;
  const question = !!s.decision;
  const qPart = question ? parts.find((p) => p.step === "ask") : null;
  const live = !["done", "done_open", "stopped", "crashed", "idle"].includes(s.status);
  const out = {};
  for (const k of PEOPLE) out[k] = { key: k, name: NAME[k], role: SHORT[k], parts: [], line: "", busy: false, asks: false };
  for (const p of parts) out[p.person]?.parts.push(p);

  // Asha: the questions, the brief, the plan
  const client = unit("client");
  const planner = unit("planner");
  if (question) {
    out.asha.line = "Has one question for you";
    out.asha.asks = true;
  } else if (planner?.state === "working") {
    out.asha.line = planner.doing || "Planning the parts";
    out.asha.busy = true;
  } else if (client?.state === "working") {
    out.asha.line = client.doing || "Reading your request";
    out.asha.busy = true;
  } else out.asha.line = live ? "Keeping things on track" : s.status === "idle" ? "Ready when you are" : "Wrapped up the run";

  // Nora: the checks
  const checker = ["quality", "gatekeeper", "reviewer"].map(unit).find((u) => u?.state === "working");
  out.nora.line = checker ? checker.doing || "Checking" : "Checks each part as it finishes";
  out.nora.busy = !!checker;

  // the makers: what they are on now, in the part names
  for (const k of ["mira", "kabir", "dev"]) {
    const m = out[k];
    const on = m.parts.filter((p) => p.state === "working");
    const fix = m.parts.filter((p) => p.state === "needs_fix");
    if (qPart && qPart.person === k) {
      m.line = "Waiting on your answer";
      m.busy = true;
    } else if (on.length) {
      m.line = `On ${andList(on.slice(0, 3).map((p) => short(p.name)))}${on.length > 3 ? ` and ${on.length - 3} more` : ""}`;
      m.busy = true;
    } else if (fix.length && live) m.line = `${fix[0].name} needs a fix`;
    else if (!m.parts.length) m.line = live ? "Free for the next part" : "Nothing for this run";
    else {
      const done = m.parts.filter((p) => p.state === "done").length;
      const left = m.parts.filter((p) => p.state !== "done" && p.state !== "skipped").length;
      m.line = live ? (done ? `Finished ${count(done)}, free for the next` : "Free for the next part")
        : `Finished ${count(done)}${left ? `, ${left} still open` : ""}`;
    }
  }
  return out;
}

/** The recent log for one person: team-talk lines they said or got, and (Asha) the team's own chat lines. */
export function logOf(key, s, parts, limit = 4) {
  const rows = [];
  for (const b of s.backstage || []) {
    const from = personOfLabel(b.from, parts);
    const to = personOfLabel(b.to, parts);
    if (from !== key && to !== key) continue;
    rows.push({ id: b.id, t: b.t, from: from === "you" ? "You" : NAME[from] || "The team", to: to && to !== from ? (to === "you" ? "you" : NAME[to] || "") : "", text: b.text });
  }
  if (key === "asha") {
    for (const m of s.chat || []) {
      if (m.kind === "record") rows.push({ id: m.id + 0.5, t: m.t, from: m.answer === "Decided for you" ? "Asha" : "You", to: "", text: `${m.title}${m.answer && m.answer !== "Decided for you" ? `: ${m.answer}` : ""}` });
      else if (m.from === "team" && m.text) rows.push({ id: m.id + 0.5, t: m.t, from: "Asha", to: "you", text: m.text });
      else if (m.from === "you" && m.text) rows.push({ id: m.id + 0.5, t: m.t, from: "You", to: "", text: m.text });
    }
  }
  rows.sort((a, b) => (a.t || "").localeCompare(b.t || "") || a.id - b.id);
  return rows.slice(-limit);
}
