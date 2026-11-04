// The kingdom view: a live SVG map of the team at work (j2-revamp/j2-kingdom-view-plan.md).
//
// Three kinds of thing: people (unit tokens), buildings (the parts, tiles that fill with progress) and roads
// (dependencies). Departments are villages. Hand-offs travel as small lights along a trail that appears just for
// them. Positions are assigned once per node id and never move during a run; new parts grow in place.
// Everything that moves uses transforms and opacity only; the lights run on requestAnimationFrame. With reduced
// motion the map is static (no lights, no pulses, no gliding).
//
// Layout (feedback 2): tidy columns by dependency depth, rows ordered to keep roads from crossing, only direct
// dependencies drawn (a transitive reduction). The team row, the client lead and the castle scale with the size of
// the village, so they never look tiny next to a big plan; nodes glide to their new spot when the plan grows.

import { reducedMotion } from "../dom.js";

const NS = "http://www.w3.org/2000/svg";
const CX = 176; // building column spacing (room for a two-line name under each tile)
const RY = 116; // building row spacing
const BW = 76; // tile width
const BH = 50; // tile height
const LABEL_W = 150; // a part's name wraps within this width, at most two lines
const TEAM_GAP = 92; // between team tokens (their names sit under them)
const UNIT_R = 14;
const CORE_ORDER = ["planner", "budget", "scheduler", "gatekeeper", "quality", "reviewer"];
const MAX_LIGHTS = 3;
const LIGHT_MS = 1500;
const ARRIVE_MS = 700;
const MIN_K = 0.22; // zoomed right out: villages, not units
const MAX_K = 2.6;
const FIT_MAX_K = 1.25; // auto-fit never draws the map larger than this (a small plan stays calm, not huge)
const PART_FONT_MIN = 10.5; // a part's name is at least this many screen pixels at the fitted zoom
const WRAP_RY = 112; // row pitch in a wrapped group: room for a road lane between rows
const V_SLACK = 1.12; // auto-fit fits the width and lets the height run over by up to 12% (a little scrolling)

// simple geometric glyphs per role, drawn in a 24-unit box (stroke only)
const GLYPH = {
  client: "M4 5h16v10H9l-5 4z",
  planner: "M5 6h14M5 12h14M5 18h9",
  budget: "M12 4a8 8 0 1 1 0 16a8 8 0 1 1 0-16M8.5 12h7",
  scheduler: "M12 4a8 8 0 1 1 0 16a8 8 0 1 1 0-16M12 8v4l3 2",
  gatekeeper: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  quality: "M12 4a8 8 0 1 1 0 16a8 8 0 1 1 0-16M8 12l3 3 5-6",
  reviewer: "M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6M12 9.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5",
  builder: "M4 16h16M6 16a6 6 0 0 1 12 0M12 8v2",
};
// the castle (you): two slim towers with pointed roofs flanking a crenellated keep and its gate, a little flag on top
// (it waves only while you're needed). Drawn in a 40 x 36 box centred on 0, its base at y 16.
const CASTLE = "M-19 16V-7L-15 -15L-11 -7V-2H-8V-5H-5V-2H-2V-5H2V-2H5V-5H8V-2H11V-7L15 -15L19 -7V16Z";
const CASTLE_SHADE = "M-15 -15L-11 -7V16H-15ZM15 -15L19 -7V16H15ZM-11 -2H11V1H-11Z";
const CASTLE_ROOF = "M-19 -7L-15 -15L-11 -7ZM11 -7L15 -15L19 -7Z";
const CASTLE_GATE = "M-4 16V10a4 4 0 0 1 8 0V16ZM-16.2 -1h2.4v4h-2.4ZM13.8 -1h2.4v4h-2.4Z";
const CASTLE_FLAG = "M0 -17C3 -18.4 5.6 -15.6 9 -16.6V-11.6C5.6 -10.6 3 -13.4 0 -12Z";
const CASTLE_Y = 30; // the castle's centre, above the client lead (x the lead's, so they line up exactly)
const CASTLE_LABEL_Y = 32; // "You", centred under the castle's base with a small gap
const CASTLE_ROAD_Y = 40; // the dotted road starts below the label, never through it

function svg(tag, attrs, ...children) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null && v !== false) el.setAttribute(k, String(v));
  for (const c of children) if (c) el.append(c);
  return el;
}
const ease = (t) => 1 - Math.pow(1 - t, 3);

/** The wave on top of a tile's fill: two gentle humps per tile width, drawn twice as wide so it can slide. */
function wavePath() {
  const w = 76, a = 2.2;
  let d = `M${-w} 0`;
  for (let x = -w; x < w; x += w / 2) d += ` q${w / 8} ${-a} ${w / 4} 0 t${w / 4} 0`;
  return `${d} V8 H${-w} Z`;
}

let measureCtx = null;
/** Words wrapped to `max` px, at most two lines; the second is cut with "…" if the name is longer. */
function wrap(text, max, font) {
  measureCtx = measureCtx || document.createElement("canvas").getContext("2d");
  measureCtx.font = font;
  const w = (s) => measureCtx.measureText(s).width;
  const words = text.split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (const word of words) {
    const t = cur ? `${cur} ${word}` : word;
    if (w(t) <= max || !cur) cur = t;
    else {
      lines.push(cur);
      cur = word;
    }
  }
  if (cur) lines.push(cur);
  if (lines.length <= 2 && lines.every((l) => w(l) <= max)) return lines;
  const out = lines.slice(0, 2);
  let last = lines.length > 2 ? `${out[1]} ${lines.slice(2).join(" ")}` : out[out.length - 1];
  while (last.length > 1 && w(last + "…") > max) last = last.slice(0, -1);
  out[out.length - 1] = last.replace(/[\s,;:.&-]+$/, "") + "…";
  if (w(out[0]) > max) {
    let f = out[0];
    while (f.length > 1 && w(f + "…") > max) f = f.slice(0, -1);
    out[0] = f + "…";
    return out.slice(0, 1);
  }
  return out;
}

export function createKingdom({ onTap, onBackground, onZoom } = {}) {
  const world = svg("g", { class: "k-world" });
  const layers = {
    depts: svg("g", { class: "k-depts" }),
    roads: svg("g", { class: "k-roads" }),
    trails: svg("g", { class: "k-trails" }),
    buildings: svg("g", { class: "k-buildings" }),
    units: svg("g", { class: "k-units" }),
    castle: svg("g", { class: "k-castles" }),
    lights: svg("g", { class: "k-lights" }),
  };
  world.append(layers.depts, layers.roads, layers.trails, layers.buildings, layers.castle, layers.units, layers.lights);
  const root = svg("svg", { class: "k-svg", role: "group", "aria-label": "The team at work" }, world);
  const el = document.createElement("div");
  el.className = "k-map";
  el.id = "k-map";
  el.tabIndex = -1;
  el.append(root);

  // the mini-map (shown by the caller when there is more than one department)
  const miniWorld = svg("g", { class: "k-mini-world" });
  const miniView = svg("rect", { class: "k-mini-view", rx: 3 });
  const miniSvg = svg("svg", { class: "k-mini-svg", viewBox: "0 0 160 96" }, miniWorld, miniView);
  const mini = document.createElement("button");
  mini.type = "button";
  mini.className = "k-mini";
  mini.setAttribute("aria-label", "Map overview. Click to move the view.");
  mini.append(miniSvg);

  const pos = new Map(); // node id -> {x, y}
  const nodes = new Map(); // node id -> {g, kind, data, dept}
  const deptEls = new Map(); // dept id -> {g, rect, name, box}
  const roadEls = new Map(); // "a>b" -> path
  const seen = new Set(); // flow ids already shown (or skipped on first load)
  const queue = []; // flows waiting for a free light
  const lights = []; // {flow, g, trail, len, t0, to}
  let first = true;
  let raf = 0;
  let bbox = { x: 0, y: 0, w: 400, h: 300 };
  let lastBoxKey = "";
  const view = { k: 1, tx: 0, ty: 0 };
  let userMoved = false;
  let autoMoved = false;
  let mode = "calm";
  let currentMap = null;
  let attentionId = null;
  let attentionSeen = null;
  let unitScale = 1;
  let reduced = new Map(); // building id -> its direct dependencies (the roads drawn)
  let hoverId = null;
  const slot = new Map(); // building id -> {sub, gx, ry}: its sub-column in a wrapped group and the group's left x
  let partFont = 12; // the part names' size in map units (see layout)
  let rowsCap = 0; // the rows the current layout wraps its columns at (re-laid out when the screen changes enough)

  /* ---------------------------------------------------------------- layout */

  function depthOf(b, byId, memo, stack = new Set()) {
    if (memo.has(b.id)) return memo.get(b.id);
    if (stack.has(b.id)) return 0;
    stack.add(b.id);
    let d = 0;
    for (const dep of b.depends_on || []) {
      const x = byId.get(dep);
      if (x) d = Math.max(d, depthOf(x, byId, memo, stack) + 1);
    }
    memo.set(b.id, d);
    return d;
  }

  /** The direct dependencies only: a road a -> c is dropped when c also reaches a through another dependency. */
  function directDeps(blds) {
    const byId = new Map(blds.map((b) => [b.id, b]));
    const reach = new Map();
    const reachOf = (id, stack = new Set()) => {
      if (reach.has(id)) return reach.get(id);
      const out = new Set();
      if (stack.has(id)) return out;
      stack.add(id);
      for (const d of byId.get(id)?.depends_on || []) {
        if (!byId.has(d)) continue;
        out.add(d);
        for (const x of reachOf(d, stack)) out.add(x);
      }
      reach.set(id, out);
      return out;
    };
    const out = new Map();
    for (const b of blds) {
      const deps = [...new Set((b.depends_on || []).filter((d) => byId.has(d) && d !== b.id))];
      out.set(b.id, deps.filter((d) => !deps.some((o) => o !== d && reachOf(o).has(d))));
    }
    return out;
  }

  /** The village scale: 1 for a small plan, up to 1.7 for a wide one (the team, client lead and castle grow with it). */
  function scaleFor(map) {
    let widest = 1;
    const depts = map.departments?.length ? map.departments : [{ id: "d-main" }];
    const ids = new Set(depts.map((d) => d.id));
    depts.forEach((d, di) => {
      const blds = map.buildings.filter((b) => b.dept === d.id || (!ids.has(b.dept) && di === depts.length - 1));
      const memo = new Map(), byId = new Map(blds.map((b) => [b.id, b]));
      const cols = Math.max(1, ...blds.map((b) => depthOf(b, byId, memo) + 1));
      widest = Math.max(widest, cols);
    });
    return Math.max(1, Math.min(1.5, 0.8 + widest * 0.13));
  }

  /** The map's free area (clear of an inset), for choosing how a plan's columns wrap. */
  function viewArea() {
    const w = (el.clientWidth || 1280) - inset.left, hgt = Math.max(160, (el.clientHeight || 720) - inset.bottom);
    const narrow = w < 720;
    return { w: w - (narrow ? 28 : 96), h: hgt - (narrow ? 40 : 92) };
  }

  /** The fit scale for a world of width w and height h: width first, with a little vertical overflow allowed. */
  function fitScale(w, h, area = viewArea()) {
    return Math.max(MIN_K, Math.min(FIT_MAX_K, area.w / w, (area.h * V_SLACK) / h));
  }

  /** Spacing by plan size: roomy for a few parts, compact (never cramped) for many. */
  function spacingFor(n) {
    const t = Math.max(0, Math.min(1, (n - 8) / 10)); // 8 parts or fewer: roomy; 18 or more: compact
    return { cx: Math.round(CX - t * 18), ry: Math.round(RY - t * 12), gap: 30 };
  }

  /**
   * Place one department's dependency columns with at most `maxRows` rows: a column with more parts wraps into a
   * small grid of sub-columns, filled row by row, so the vertical order (fewest crossings) is kept. Roads into a back
   * sub-column run along the gap above their row (see roadPath), never through the tiles in front.
   * Returns x and y offsets per part (with its sub-column and its group's left edge) plus the block's span and height.
   */
  function placeCols(cols, maxRows, sp) {
    const at = new Map();
    let x = 0, height = 0, first = true;
    const groups = cols.filter(Boolean);
    const wraps = groups.some((c) => c.length > maxRows);
    const ry = wraps ? Math.max(sp.ry, WRAP_RY) : sp.ry;
    for (const col of groups) {
      const s = Math.max(1, Math.ceil(col.length / maxRows));
      const rows = Math.ceil(col.length / s);
      if (!first) x += sp.cx + (wraps ? sp.gap : 0);
      first = false;
      const hgt = (rows - 1) * ry;
      const gx = x;
      col.forEach((b, i) => {
        const sub = i % s, row = Math.floor(i / s);
        at.set(b.id, { x: gx + sub * sp.cx, y: row * ry - hgt / 2, sub, gx, ry });
      });
      x += (s - 1) * sp.cx;
      height = Math.max(height, hgt);
    }
    return { at, span: x, height };
  }

  /** Positions for every node, worked out fresh from the plan each time: columns by dependency depth, left to right;
   * a tall column wraps so the whole picture is about as wide as the screen and the parts are drawn as large as fit. */
  function layout(map) {
    const depts = map.departments?.length ? map.departments : [{ id: "d-main", name: "", kind: "" }];
    const deptIds = new Set(depts.map((d) => d.id));
    const k = scaleFor(map);
    unitScale = k;
    const clientY = 112 * k, teamY = 178 * k, by = teamY + 32 * k + 78;
    const next = new Map();
    const deps = directDeps(map.buildings);
    reduced = deps;
    slot.clear();
    const sp = spacingFor(map.buildings.length);
    // each department's dependency columns, each column ordered by where its parts' dependencies sit
    const plans = depts.map((d, di) => {
      const blds = map.buildings.filter((b) => b.dept === d.id || (!deptIds.has(b.dept) && di === depts.length - 1));
      const core = map.units.filter((u) => u.role !== "builder" && (u.dept === d.id || (!deptIds.has(u.dept) && di === depts.length - 1)));
      const mine = new Map(blds.map((b) => [b.id, b]));
      const memo = new Map();
      const cols = [];
      for (const b of blds) {
        const c = depthOf(b, mine, memo);
        (cols[c] = cols[c] || []).push(b);
      }
      const rowOf = new Map();
      cols.forEach((col, c) => {
        if (!col) return;
        if (c > 0) {
          const bary = (b) => {
            const ds = (deps.get(b.id) || []).filter((x) => rowOf.has(x));
            return ds.length ? ds.reduce((n, x) => n + rowOf.get(x), 0) / ds.length : 1e3;
          };
          col.sort((a, b) => bary(a) - bary(b));
        }
        col.forEach((b, r) => rowOf.set(b.id, r - (col.length - 1) / 2));
      });
      const ring = CORE_ORDER.map((r) => core.find((u) => u.role === r)).filter(Boolean);
      return { d, cols, core, ring, teamW: Math.max(0, ring.length - 1) * TEAM_GAP * k };
    });
    // how many rows at most: the choice that draws the parts largest on this screen (width first); among choices
    // within a few per cent of the largest, the widest (fewest rows: horizontal flow)
    const tallest = Math.max(1, ...plans.flatMap((p) => p.cols.map((c) => (c ? c.length : 0))));
    const measure = (rows) => {
      const placed = plans.map((p) => placeCols(p.cols, rows, sp));
      const widths = placed.map((pl, i) => Math.max(pl.span + BW + 160, plans[i].teamW + 160 * k, 340));
      const w = widths.reduce((n, x) => n + x, 0) + 90 * (plans.length - 1);
      const h = by + Math.max(0, ...placed.map((pl) => pl.height)) + BH / 2 + 74 + 20;
      return { rows, placed, widths, k: fitScale(w, h) };
    };
    const all = [];
    for (let r = tallest; r >= 1; r--) all.push(measure(r));
    const kMax = Math.max(...all.map((m) => m.k));
    const best = all.filter((m) => m.k >= kMax * 0.96).pop(); // the widest flow among the near-largest
    rowsCap = best.rows;
    // part names stay readable once fitted: at least about 10.5px on screen, so a compact plan draws them a bit larger
    partFont = Math.round(Math.max(12, Math.min(14, PART_FONT_MIN / best.k)) * 2) / 2;
    el.style.setProperty("--k-part-font", `${partFont}px`);
    let ox = 0;
    const boxes = new Map();
    plans.forEach((p, i) => {
      const pl = best.placed[i], width = best.widths[i];
      const left = ox, cx = left + width / 2;
      const client = p.core.find((u) => u.role === "client");
      p.ring.forEach((u, j) => next.set(u.id, { x: cx - p.teamW / 2 + j * TEAM_GAP * k, y: teamY }));
      if (client) next.set(client.id, { x: cx, y: clientY });
      const bx0 = cx - pl.span / 2, midY = by + pl.height / 2;
      for (const [id, o] of pl.at) {
        next.set(id, { x: bx0 + o.x, y: midY + o.y });
        slot.set(id, { sub: o.sub, gx: bx0 + o.gx, ry: o.ry });
      }
      boxes.set(p.d.id, { left, width, cx, hasCore: p.core.length > 0, bottom: by + pl.height });
      ox += width + 90;
    });
    // builders sit at their building
    for (const u of map.units) {
      if (u.role !== "builder") continue;
      const b = next.get(u.at);
      next.set(u.id, b ? { x: b.x - BW / 2 - 12, y: b.y - BH / 2 - 4 } : { x: ox / 2, y: by });
    }
    // the castle (the person) sits above the client lead
    const total = Math.max(ox - 90, 340);
    const lead = map.units.find((u) => u.role === "client");
    next.set("castle", { x: lead && next.get(lead.id) ? next.get(lead.id).x : total / 2, y: CASTLE_Y * k });
    pos.clear();
    for (const [id, p] of next) pos.set(id, p);
    const cp = pos.get("castle");
    // department boxes from where their nodes actually are
    const out = new Map();
    for (const d of depts) {
      const bx = boxes.get(d.id);
      const pts = [...map.buildings, ...map.units]
        .filter((n) => n.dept === d.id || (!deptIds.has(n.dept) && d === depts[depts.length - 1]))
        .map((n) => pos.get(n.id)).filter(Boolean);
      let x0 = bx.left, x1 = bx.left + bx.width, y0 = bx.hasCore ? 72 * k : by - BH / 2 - 60, y1 = bx.bottom + RY - 30;
      if (pts.length) {
        x0 = Math.min(x0, ...pts.map((p) => p.x - 80));
        x1 = Math.max(x1, ...pts.map((p) => p.x + 80));
        y1 = Math.max(y1, ...pts.map((p) => p.y + 74));
      }
      out.set(d.id, { x: x0, y: y0, w: x1 - x0, h: y1 - y0, name: d.name, kind: d.kind });
    }
    const xs = [...out.values()];
    bbox = {
      x: Math.min(...xs.map((b) => b.x), cp.x - 40),
      y: 0,
      w: Math.max(...xs.map((b) => b.x + b.w), cp.x + 40) - Math.min(...xs.map((b) => b.x), cp.x - 40),
      h: Math.max(...xs.map((b) => b.y + b.h)) + 20,
    };
    return out;
  }

  /** Move a node to its spot: a CSS transform, so a node that moves when the plan grows glides there. */
  function moveTo(n, p, scale = 1) {
    const t = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px)${scale !== 1 ? ` scale(${scale.toFixed(3)})` : ""}`;
    if (n.g.style.transform !== t) n.g.style.transform = t;
    n.g.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`); // read by the checks; CSS wins
  }

  /* ---------------------------------------------------------------- render */

  function node(id, kind, build) {
    let n = nodes.get(id);
    if (n) return n;
    // units and parts take keyboard focus (Tab): focus shows the hover card, Enter or Space opens the bubble
    const focusable = kind === "unit" || kind === "bld";
    const g = svg("g", { class: `k-node k-${kind}`, "data-id": id, "data-kind": kind, tabindex: focusable ? 0 : -1, role: focusable ? "button" : null });
    const inner = svg("g", { class: "k-inner" });
    g.append(inner);
    build(inner, g);
    n = { g, inner, kind, id };
    nodes.set(id, n);
    return n;
  }

  function label(text, y) {
    const t = svg("text", { class: "k-label", y, "text-anchor": "middle" });
    t.textContent = text;
    return t;
  }

  /** A part's name under its tile: always shown, wrapped on words into at most two lines, the second cut with "…". */
  function setPartLabel(t, name) {
    if (t.dataset.name === name && t.dataset.font === String(partFont)) return;
    t.dataset.name = name;
    t.dataset.font = String(partFont);
    const lines = wrap(String(name || ""), LABEL_W, `500 ${partFont}px Instrument Sans, system-ui, sans-serif`);
    t.replaceChildren(...lines.map((ln, i) => {
      const s = svg("tspan", { x: 0, dy: i ? "1.2em" : 0 });
      s.textContent = ln;
      return s;
    }));
    const tt = t.querySelector("title") || svg("title");
    tt.textContent = name;
    t.prepend(tt);
  }

  function renderDepts(boxes) {
    for (const [id, box] of boxes) {
      let d = deptEls.get(id);
      if (!d) {
        const rect = svg("rect", { class: "k-dept-ground", rx: 44 });
        const name = svg("text", { class: "k-dept-name" });
        const g = svg("g", { class: "k-dept", "data-id": id }, rect, name);
        layers.depts.append(g);
        d = { g, rect, name };
        deptEls.set(id, d);
      }
      d.rect.setAttribute("x", box.x);
      d.rect.setAttribute("y", box.y);
      d.rect.setAttribute("width", box.w);
      d.rect.setAttribute("height", box.h);
      d.name.setAttribute("x", box.x + 28);
      d.name.setAttribute("y", box.y + 34);
      if (d.name.textContent !== box.name) d.name.textContent = box.name;
    }
    for (const [id, d] of deptEls) {
      if (!boxes.has(id)) {
        d.g.remove();
        deptEls.delete(id);
      }
    }
  }

  /** A road from the right side of one tile to the left side of the next: a gentle S-curve. A road that skips columns
   * leaves and arrives level, so it doesn't run straight across the tiles in between. */
  function roadPath(a, b, to) {
    const x0 = a.x + BW / 2 + 4, x1 = b.x - BW / 2 - 4;
    const sl = to && slot.get(to);
    if (sl && sl.sub > 0 && sl.gx - BW / 2 - 8 > x0) {
      // a back sub-column: in to the group's edge, along the lane in the gap above the target's row, then down into it
      const lane = b.y - sl.ry / 2, gx = sl.gx - BW / 2 - 14, ex = x1 - 18;
      const c = Math.min((gx - x0) * 0.5, 70);
      return `M${x0} ${a.y} C${x0 + c} ${a.y} ${gx - c} ${lane} ${gx} ${lane} L${ex} ${lane} C${ex + 12} ${lane} ${x1 - 10} ${b.y} ${x1} ${b.y}`;
    }
    const dx = Math.max(24, x1 - x0);
    const c = Math.min(dx * 0.5, 70);
    return `M${x0} ${a.y} C${x0 + c} ${a.y} ${x1 - c} ${b.y} ${x1} ${b.y}`;
  }

  function renderRoads(map) {
    const keep = new Set();
    const byId = new Map(map.buildings.map((b) => [b.id, b]));
    const client = map.units.find((u) => u.role === "client");
    if (client && pos.get(client.id) && pos.get("castle")) {
      keep.add("castle>client");
      let p = roadEls.get("castle>client");
      if (!p) {
        p = svg("path", { class: "k-road k-road-castle" });
        layers.roads.append(p);
        roadEls.set("castle>client", p);
      }
      const a = pos.get("castle"), b = pos.get(client.id);
      const d = `M${a.x} ${a.y + CASTLE_ROAD_Y * unitScale} L${b.x} ${b.y - (UNIT_R + 4) * unitScale}`;
      if (p.getAttribute("d") !== d) p.setAttribute("d", d);
    }
    for (const b of map.buildings) {
      for (const dep of reduced.get(b.id) || []) {
        const key = `${dep}>${b.id}`;
        keep.add(key);
        let p = roadEls.get(key);
        if (!p) {
          p = svg("path", { class: "k-road", "data-from": dep, "data-to": b.id });
          layers.roads.append(p);
          roadEls.set(key, p);
        }
        const d = roadPath(pos.get(dep), pos.get(b.id), b.id);
        if (p.getAttribute("d") !== d) p.setAttribute("d", d);
        const from = byId.get(dep);
        p.classList.toggle("is-open", b.state === "waiting" && from.state !== "done");
        p.classList.toggle("is-ready", b.state === "waiting" && from.state === "done");
        p.classList.toggle("is-done", from.state === "done" && (b.state === "done" || b.state === "working" || b.state === "needs_fix"));
        p.classList.toggle("is-off", b.state === "skipped" || from.state === "skipped");
      }
    }
    for (const [key, p] of roadEls) {
      if (!keep.has(key)) {
        p.remove();
        roadEls.delete(key);
      }
    }
    applyHover();
  }

  /** Pointing at a part lights its own roads (in and out) and quiets the rest. */
  function applyHover() {
    el.classList.toggle("has-hover", !!hoverId);
    for (const [key, p] of roadEls) {
      const on = !!hoverId && (p.dataset.from === hoverId || p.dataset.to === hoverId);
      p.classList.toggle("is-hl", on);
    }
  }

  function renderBuildings(map) {
    const keep = new Set();
    for (const b of map.buildings) {
      keep.add(b.id);
      const n = node(b.id, "bld", (inner, g) => {
        const clipId = `k-clip-${b.id.replace(/[^\w-]/g, "_")}`;
        const clip = svg("clipPath", { id: clipId }, svg("rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, rx: 10 }));
        // the fill rises like water in a glass: a tall body moved up by its progress, with a soft wave on top
        const water = svg("g", { class: "k-water" },
          svg("path", { class: "k-wave", d: wavePath() }),
          svg("rect", { class: "k-bld-fill", x: -BW, y: 0, width: BW * 2, height: BH + 6 }));
        inner.append(
          clip,
          svg("ellipse", { class: "k-glow", cx: 0, cy: BH / 2 + 4, rx: BW * 0.62, ry: 12 }),
          svg("rect", { class: "k-bld-base", x: -BW / 2, y: -BH / 2, width: BW, height: BH, rx: 10 }),
          svg("g", { "clip-path": `url(#${clipId})` }, water),
          svg("rect", { class: "k-bld-outline", x: -BW / 2, y: -BH / 2, width: BW, height: BH, rx: 10 }),
          svg("path", { class: "k-bld-roof", d: `M${-BW / 2 + 6} ${-BH / 2 + 1} L0 ${-BH / 2 - 15} L${BW / 2 - 6} ${-BH / 2 + 1} Z` }),
          svg("path", { class: "k-bld-check", d: "M-8 1l5 5 10-11" }),
          svg("path", { class: "k-bld-mark", d: `M${BW / 2 - 4} ${-BH / 2 - 6} l7 12 h-14z` }),
          svg("rect", { class: "k-ring", x: -BW / 2 - 8, y: -BH / 2 - 8, width: BW + 16, height: BH + 16, rx: 16 }),
          svg("text", { class: "k-label k-part-label", y: BH / 2 + 17, "text-anchor": "middle" })
        );
        if (!first) g.classList.add("is-new");
        layers.buildings.append(g);
      });
      n.g.setAttribute("aria-label", b.name);
      moveTo(n, pos.get(b.id));
      n.g.dataset.state = b.state;
      n.data = b;
      const prog = b.state === "done" ? 1 : b.state === "skipped" ? 0 : Math.max(0, Math.min(1, b.progress || 0));
      const water = n.inner.querySelector(".k-water");
      const want = `translateY(${(BH / 2 - prog * BH - (prog >= 1 ? 6 : 0)).toFixed(2)}px)`;
      if (water.style.transform !== want) water.style.transform = want;
      setPartLabel(n.inner.querySelector(".k-part-label"), b.name);
      n.g.classList.toggle("is-working", b.state === "working");
      n.g.classList.toggle("is-done", b.state === "done");
      n.g.classList.toggle("is-fix", b.state === "needs_fix");
      n.g.classList.toggle("is-skipped", b.state === "skipped");
      n.g.classList.toggle("is-waiting", b.state === "waiting");
      n.g.classList.toggle("has-output", !!b.output);
    }
    for (const [id, n] of nodes) {
      if (n.kind === "bld" && !keep.has(id)) {
        n.g.remove();
        nodes.delete(id);
      }
    }
  }

  function renderUnits(map, working) {
    const keep = new Set();
    for (const u of map.units) {
      keep.add(u.id);
      const n = node(u.id, "unit", (inner, g) => {
        inner.append(
          svg("circle", { class: "k-pulse", r: UNIT_R + 2 }),
          svg("circle", { class: "k-ring", r: UNIT_R + 9 }),
          svg("circle", { class: "k-body", r: UNIT_R }),
          svg("path", { class: "k-glyph", d: GLYPH[u.role] || GLYPH.builder, transform: `translate(${-UNIT_R / 2 - 1} ${-UNIT_R / 2 - 1}) scale(0.66)` }),
          label(u.label, UNIT_R + 18)
        );
        g.setAttribute("aria-label", u.label);
        g.dataset.role = u.role;
        if (!first) g.classList.add("is-new");
        layers.units.append(g);
      });
      moveTo(n, pos.get(u.id), u.role === "builder" ? 1 : unitScale);
      n.data = u;
      const lbl = n.inner.querySelector(".k-label");
      if (lbl.textContent !== u.label) lbl.textContent = u.label;
      n.g.dataset.state = u.state;
      n.g.classList.toggle("is-working", u.state === "working" && working);
      n.g.classList.toggle("is-waiting", u.state === "waiting");
    }
    for (const [id, n] of nodes) {
      if (n.kind === "unit" && !keep.has(id)) {
        n.g.classList.add("is-gone");
        setTimeout(() => n.g.remove(), 400);
        nodes.delete(id);
      }
    }
  }

  function renderCastle() {
    const n = node("castle", "castle", (inner, g) => {
      inner.append(
        svg("circle", { class: "k-ring", r: 34 }),
        svg("ellipse", { class: "k-castle-shadow", cx: 0, cy: 17, rx: 21, ry: 3 }),
        svg("path", { class: "k-castle-body", d: CASTLE }),
        svg("path", { class: "k-castle-shade", d: CASTLE_SHADE }),
        svg("path", { class: "k-castle-roof", d: CASTLE_ROOF }),
        svg("path", { class: "k-castle-gate", d: CASTLE_GATE }),
        svg("path", { class: "k-castle-pole", d: "M0 -4.5V-17.5" }),
        svg("path", { class: "k-castle-flag", d: CASTLE_FLAG }),
        label("You", CASTLE_LABEL_Y)
      );
      g.setAttribute("aria-label", "You");
      layers.castle.append(g);
    });
    moveTo(n, pos.get("castle"), unitScale);
  }

  /* ---------------------------------------------------------------- lights (hand-offs) */

  function trailPath(a, b) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.hypot(dx, dy) || 1;
    const bow = Math.min(60, d * 0.18);
    const mx = (a.x + b.x) / 2 - (dy / d) * bow;
    const my = (a.y + b.y) / 2 + (dx / d) * bow;
    return `M${a.x} ${a.y} Q${mx} ${my} ${b.x} ${b.y}`;
  }

  function startLight(flow) {
    const a = pos.get(flow.from), b = pos.get(flow.to);
    if (!a || !b) return false;
    const trail = svg("path", { class: "k-trail", d: trailPath(a, b) });
    const g = svg("g", { class: "k-light", "data-flow": flow.id }, svg("circle", { class: "k-light-halo", r: 9 }), svg("circle", { class: "k-light-dot", r: 3.5 }));
    g.dataset.what = flow.what || "";
    layers.trails.append(trail);
    layers.lights.append(g);
    requestAnimationFrame(() => trail.classList.add("is-on"));
    lights.push({ flow, g, trail, len: trail.getTotalLength(), t0: performance.now(), to: flow.to });
    return true;
  }

  function pump() {
    while (lights.length < MAX_LIGHTS && queue.length) {
      const f = queue.shift();
      startLight(f);
    }
    if ((lights.length || queue.length) && !raf) raf = requestAnimationFrame(frame);
  }

  function frame(now) {
    raf = 0;
    for (const L of [...lights]) {
      const t = Math.min(1, (now - L.t0) / LIGHT_MS);
      const p = L.trail.getPointAtLength(ease(t) * L.len);
      L.g.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
      L.g.style.opacity = t < 0.12 ? (t / 0.12).toFixed(2) : t > 0.86 ? ((1 - t) / 0.14).toFixed(2) : "1";
      if (t >= 1) {
        lights.splice(lights.indexOf(L), 1);
        L.g.remove();
        L.trail.classList.remove("is-on");
        setTimeout(() => L.trail.remove(), 500);
        const target = nodes.get(L.to);
        if (target) {
          target.g.classList.add("is-arrive");
          setTimeout(() => target.g.classList.remove("is-arrive"), ARRIVE_MS);
        }
      }
    }
    if (lights.length < MAX_LIGHTS && queue.length) pump();
    if (lights.length) raf = requestAnimationFrame(frame);
  }

  function takeFlows(map) {
    const still = reducedMotion() || document.hidden;
    for (const f of map.flows || []) {
      if (seen.has(f.id)) continue;
      seen.add(f.id);
      if (first || still) continue;
      queue.push(f);
    }
    if (queue.length > 8) queue.splice(0, queue.length - 8); // never a backlog of lights
    pump();
  }

  /* ---------------------------------------------------------------- view: fit, zoom, pan */

  // `view` is where the map is going; `shown` is where it is drawn. The person's own zoom and pan (wheel, trackpad
  // pinch, Safari's gesture, a drag, two fingers) land at once, every event, drawn through the SVG transform
  // attribute (crisp names at every zoom); only the buttons and fit ease over a short tween. When the person takes
  // over, a running tween stops where it is drawn (settle), so an ease never fights their fingers, and auto-fit waits
  // until they press fit (userMoved).
  const shown = { k: 1, tx: 0, ty: 0 };
  let tween = null;
  let lastInput = -1e9; // when the person last zoomed or panned (auto moves hold off for a moment after)
  const WHEEL_K = 0.01; // scale *= exp(-deltaY * WHEEL_K) per normalised wheel pixel
  const WHEEL_STEP_MAX = 40; // one event's |deltaY| is capped: a mouse notch is ~1.5x, a pinch event a few per cent
  const LINE_PX = 16; // deltaMode 1 (lines) in pixels
  const HOLD_MS = 1200; // auto moves wait this long after the person's last zoom or pan
  function draw() {
    world.setAttribute("transform", `translate(${shown.tx.toFixed(2)} ${shown.ty.toFixed(2)}) scale(${shown.k.toFixed(4)})`);
  }
  function tick(now) {
    if (!tween) return;
    const t = Math.min(1, (now - tween.t0) / tween.ms);
    const e = 1 - Math.pow(1 - t, 3);
    // k and the offsets ease together, so the zoom's anchor stays put the whole way
    for (const key of ["k", "tx", "ty"]) shown[key] = tween.from[key] + (view[key] - tween.from[key]) * e;
    draw();
    if (t < 1) requestAnimationFrame(tick);
    else tween = null;
  }
  function settle() {
    if (!tween) return;
    tween = null;
    Object.assign(view, shown);
  }
  function userInput() {
    userMoved = true;
    lastInput = performance.now();
  }
  const holding = () => performance.now() - lastInput < HOLD_MS;
  function applyView(animate) {
    const ms = animate === true ? 320 : typeof animate === "number" ? animate : 0;
    if (!ms || reducedMotion()) {
      tween = null;
      Object.assign(shown, view);
      draw();
    } else {
      const running = !!tween;
      tween = { from: { ...shown }, t0: performance.now(), ms };
      if (!running) requestAnimationFrame(tick);
    }
    updateMini();
    onZoom?.(view.k);
  }

  let inset = { left: 0, bottom: 0 };
  function fit(animate = true) {
    const w = (el.clientWidth || 800) - inset.left, hgt = Math.max(160, (el.clientHeight || 600) - inset.bottom);
    const narrow = w < 720;
    const padX = narrow ? 14 : 48, padTop = narrow ? 16 : 28, padBottom = narrow ? 24 : 64;
    // width first: the whole width shows; the height may run over a little (the top stays in view, pan for the rest)
    const k = fitScale(bbox.w, bbox.h, { w: w - padX * 2, h: hgt - padTop - padBottom });
    view.k = k;
    view.tx = inset.left + (w - bbox.w * k) / 2 - bbox.x * k;
    const free = Math.max(0, hgt - padTop - padBottom - bbox.h * k);
    view.ty = padTop + free * (narrow ? 0.18 : 0.4) - bbox.y * k;
    userMoved = false;
    autoMoved = false;
    applyView(animate);
  }

  function zoomAt(factor, cx, cy, animate = false) {
    if (!animate) settle();
    const k = Math.max(MIN_K, Math.min(MAX_K, view.k * factor));
    const r = k / view.k;
    view.tx = cx - (cx - view.tx) * r;
    view.ty = cy - (cy - view.ty) * r;
    view.k = k;
    userInput();
    applyView(animate);
  }

  /** Pan (smoothly) so a node sits inside the visible box {top, bottom} of the map, if it is not already. */
  function ensureVisible(id, { bottom = el.clientHeight, top = 0 } = {}) {
    const p = pos.get(id);
    if (!p || userMoved || holding()) return; // never move the map under the person's hands
    const sy = p.y * view.k + view.ty;
    const sx = p.x * view.k + view.tx;
    let dy = 0, dx = 0;
    if (sy > bottom - 60) dy = bottom - 60 - sy;
    if (sy < top + 60) dy = top + 60 - sy;
    if (sx < 60) dx = 60 - sx;
    if (sx > el.clientWidth - 60) dx = el.clientWidth - 60 - sx;
    if (dx || dy) {
      view.tx += dx;
      view.ty += dy;
      autoMoved = true;
      applyView(true);
    }
  }

  function updateMini() {
    if (mini.hidden) return;
    const sx = 160 / bbox.w, sy = 96 / bbox.h;
    const s = Math.min(sx, sy);
    const ox = (160 - bbox.w * s) / 2 - bbox.x * s, oy = (96 - bbox.h * s) / 2 - bbox.y * s;
    miniWorld.setAttribute("transform", `translate(${ox} ${oy}) scale(${s})`);
    const w = el.clientWidth, hgt = el.clientHeight;
    const vx = (0 - view.tx) / view.k, vy = (0 - view.ty) / view.k;
    const vw = w / view.k, vh = hgt / view.k;
    miniView.setAttribute("x", ox + vx * s);
    miniView.setAttribute("y", oy + vy * s);
    miniView.setAttribute("width", Math.max(4, vw * s));
    miniView.setAttribute("height", Math.max(4, vh * s));
  }

  function renderMini(boxes) {
    miniWorld.replaceChildren(
      ...[...boxes.values()].map((b) => svg("rect", { class: "k-mini-dept", x: b.x, y: b.y, width: b.w, height: b.h, rx: 40 })),
      ...[...nodes.values()].filter((n) => n.kind === "bld").map((n) => {
        const p = pos.get(n.id);
        return svg("rect", { class: `k-mini-bld is-${n.data?.state || "waiting"}`, x: p.x - BW / 2, y: p.y - BH / 2, width: BW, height: BH, rx: 10 });
      })
    );
  }

  mini.addEventListener("click", (e) => {
    const r = miniSvg.getBoundingClientRect();
    const sx = 160 / bbox.w, sy = 96 / bbox.h;
    const s = Math.min(sx, sy);
    const ox = (160 - bbox.w * s) / 2 - bbox.x * s, oy = (96 - bbox.h * s) / 2 - bbox.y * s;
    const mx = ((e.clientX - r.left) / r.width) * 160, my = ((e.clientY - r.top) / r.height) * 96;
    const wx = (mx - ox) / s, wy = (my - oy) / s;
    view.tx = el.clientWidth / 2 - wx * view.k;
    view.ty = el.clientHeight / 2 - wy * view.k;
    userMoved = true;
    applyView(true);
  });

  /* ---------------------------------------------------------------- pointer: tap, pan, pinch, wheel */

  const pointers = new Map();
  let drag = null; // {x, y, tx, ty, moved}
  let pinch = null; // {d, k, cx, cy}

  root.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try {
      root.setPointerCapture(e.pointerId);
    } catch {
      /* fine */
    }
    settle();
    if (pointers.size === 1) {
      drag = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false, target: e.target.closest(".k-node") };
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: view.k, tx: view.tx, ty: view.ty, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
      drag = null;
    }
  });
  root.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const r = el.getBoundingClientRect();
      const k = Math.max(MIN_K, Math.min(MAX_K, pinch.k * (d / pinch.d)));
      const cx = pinch.cx - r.left, cy = pinch.cy - r.top;
      const ratio = k / pinch.k;
      view.k = k;
      view.tx = cx - (cx - pinch.tx) * ratio;
      view.ty = cy - (cy - pinch.ty) * ratio;
      userInput();
      applyView(false);
      return;
    }
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) > 6) {
      drag.moved = true;
      el.classList.add("is-panning");
    }
    if (drag.moved) {
      view.tx = drag.tx + dx;
      view.ty = drag.ty + dy;
      userInput();
      applyView(false);
    }
  });
  const up = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (pinch && pointers.size < 2) pinch = null;
    if (drag && pointers.size === 0) {
      const moved = drag.moved;
      const target = drag.target;
      drag = null;
      el.classList.remove("is-panning");
      if (!moved && e.type === "pointerup") {
        if (target && nodes.has(target.dataset.id)) onTap?.(nodes.get(target.dataset.id), { x: e.clientX, y: e.clientY });
        else if (e.target.closest(".k-light")) onTap?.({ kind: "light", id: e.target.closest(".k-light").dataset.flow, data: { what: e.target.closest(".k-light").dataset.what } }, { x: e.clientX, y: e.clientY });
        else onBackground?.();
      }
    }
  };
  root.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const g = e.target.closest?.(".k-node");
    if (!g || !nodes.has(g.dataset.id)) return;
    e.preventDefault();
    const r = g.getBoundingClientRect();
    onTap?.(nodes.get(g.dataset.id), { x: r.left + r.width / 2, y: r.top + r.height / 2 });
  });
  root.addEventListener("pointerup", up);
  root.addEventListener("pointercancel", up);
  // the hold-and-slide gesture takes the pointer over after a hold: forget the press, it is not a tap or a pan
  root.addEventListener("lostpointercapture", (e) => {
    if (e.target !== root || !pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    drag = null;
    pinch = null;
    el.classList.remove("is-panning");
  });
  // Zoom belongs to the map alone (feedback 2): a trackpad pinch (it arrives as ctrl + wheel) or ctrl + scroll zooms
  // the map, never the page; a plain two-finger scroll pans it. Safari's own pinch gestures are taken over too.
  // A trackpad pinch arrives as ctrl + wheel: spreading the fingers sends a negative deltaY and zooms IN toward the
  // pointer, pinching sends a positive one and zooms out; ctrl + a mouse wheel does the same in bigger steps. Deltas
  // are normalised (lines and pages to pixels) and capped per event; the point under the pointer stays put.
  let gesturing = false;
  root.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      if (gesturing && e.ctrlKey) return; // Safari: its gesture events below carry this pinch
      const r = el.getBoundingClientRect();
      const unit = e.deltaMode === 1 ? LINE_PX : e.deltaMode === 2 ? el.clientHeight || 600 : 1;
      const dy = e.deltaY * unit, dx = e.deltaX * unit;
      if (e.ctrlKey || e.metaKey) {
        const step = Math.max(-WHEEL_STEP_MAX, Math.min(WHEEL_STEP_MAX, dy));
        if (step) zoomAt(Math.exp(-step * WHEEL_K), e.clientX - r.left, e.clientY - r.top);
      } else {
        settle();
        view.tx -= dx;
        view.ty -= dy;
        userInput();
        applyView(false);
      }
    },
    { passive: false }
  );
  // Safari's own pinch: gesturechange carries the scale since the gesture began
  let gestureK = 1;
  el.addEventListener("gesturestart", (e) => {
    e.preventDefault();
    settle();
    gesturing = true;
    gestureK = 1;
  });
  el.addEventListener("gesturechange", (e) => {
    e.preventDefault();
    const sc = Number(e.scale) || 1;
    const r = el.getBoundingClientRect();
    zoomAt(sc / gestureK, (e.clientX ?? r.left + r.width / 2) - r.left, (e.clientY ?? r.top + r.height / 2) - r.top);
    gestureK = sc;
  });
  el.addEventListener("gestureend", (e) => {
    e.preventDefault();
    gesturing = false;
  });

  // pointing at a part lights its roads
  root.addEventListener("pointerover", (e) => {
    const g = e.target.closest?.(".k-bld");
    const id = g ? g.dataset.id : null;
    if (id !== hoverId) {
      hoverId = id;
      applyHover();
    }
  });
  root.addEventListener("pointerleave", () => {
    hoverId = null;
    applyHover();
  });
  root.addEventListener("dblclick", (e) => {
    const r = el.getBoundingClientRect();
    zoomAt(1.5, e.clientX - r.left, e.clientY - r.top, 200);
  });

  let resizeTimer = 0;
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (currentMap && !userMoved && !holding()) {
          const was = rowsCap;
          layout(currentMap);
          if (rowsCap !== was) return update(currentMap, lastOpts); // the screen changed shape: wrap the columns anew
        }
        if (!userMoved && !autoMoved && !holding() && currentMap) fit(false);
        else updateMini();
      }, 60);
    }).observe(el);
  }

  /* ---------------------------------------------------------------- public */

  let lastOpts = {};
  function update(map, opts = {}) {
    if (!map) return;
    const { status, attention } = opts;
    lastOpts = opts;
    currentMap = map;
    const working = status === "working";
    const boxes = layout(map);
    renderDepts(boxes);
    renderBuildings(map);
    renderUnits(map, working);
    renderCastle();
    renderRoads(map);
    for (const n of nodes.values()) n.g.classList.toggle("is-attn", !!attention && n.id === attention);
    el.classList.toggle("is-quiet", !working);
    el.dataset.status = status || "";
    mini.hidden = (map.departments?.length || 0) < 2;
    el.dataset.depts = (map.departments?.length || 0) > 1 ? "many" : "one";
    renderMini(boxes);
    takeFlows(map);
    const key = `${bbox.x}|${bbox.w}|${bbox.h}|${map.departments?.length}`;
    if (key !== lastBoxKey) {
      lastBoxKey = key;
      if (!userMoved && !autoMoved && !holding()) fit(!first);
      else {
        if (autoMoved && attention) attentionSeen = null; // the world grew: keep the node the card is about in view
        updateMini();
      }
    } else if (!attention && autoMoved && !userMoved && !holding()) {
      fit(true); // the card has gone: back to the whole picture
    }
    if (!attention) attentionSeen = null;
    attentionId = attention || null;
    first = false;
  }

  function setMode(m) {
    mode = m;
    el.classList.toggle("is-interact", m === "interact");
  }

  function nodeRect(id) {
    const n = nodes.get(id);
    if (!n) return null;
    const body = n.inner.querySelector(".k-body, .k-bld-outline, .k-castle-body") || n.g;
    return body.getBoundingClientRect();
  }

  function reset() {
    pos.clear();
    for (const n of nodes.values()) n.g.remove();
    nodes.clear();
    for (const d of deptEls.values()) d.g.remove();
    deptEls.clear();
    for (const p of roadEls.values()) p.remove();
    roadEls.clear();
    seen.clear();
    queue.length = 0;
    for (const L of lights) {
      L.g.remove();
      L.trail.remove();
    }
    lights.length = 0;
    first = true;
    userMoved = false;
    lastInput = -1e9;
    tween = null;
    lastBoxKey = "";
    attentionSeen = null;
  }

  return {
    el,
    mini,
    update,
    setMode,
    fit: () => fit(true),
    /** Keep the map clear of an overlay: on its left (look behind) or at the bottom (a question card), refitting
     * unless the person moved it. */
    setInset({ left = inset.left, bottom = inset.bottom } = {}) {
      if (inset.left === left && Math.abs(inset.bottom - bottom) < 8) return;
      inset = { left, bottom };
      if (!userMoved && !holding() && currentMap) fit(true);
    },
    // the buttons zoom about the middle of the visible map (clear of an inset), in the same steps both ways
    zoomIn: () => zoomAt(1.3, inset.left + (el.clientWidth - inset.left) / 2, (el.clientHeight - inset.bottom) / 2, 180),
    zoomOut: () => zoomAt(1 / 1.3, inset.left + (el.clientWidth - inset.left) / 2, (el.clientHeight - inset.bottom) / 2, 180),
    get atMin() {
      return view.k <= MIN_K + 1e-6;
    },
    get atMax() {
      return view.k >= MAX_K - 1e-6;
    },
    nodeRect,
    ensureVisible,
    /** Once per decision: keep the node the card is about in view, above the card. */
    showAttention(id, bottom) {
      if (!id || id === attentionSeen || !pos.get(id)) return;
      attentionSeen = id;
      ensureVisible(id, { bottom });
    },
    node: (id) => nodes.get(id),
    reset,
    get scale() {
      return view.k;
    },
    /** The person moved or zoomed the map themselves: auto-fit waits until they press fit. */
    get userMoved() {
      return userMoved;
    },
    get unitScale() {
      return unitScale;
    },
    get bbox() {
      return { ...bbox };
    },
    get activeLights() {
      return lights.length;
    },
    get mode() {
      return mode;
    },
    get attention() {
      return attentionId;
    },
  };
}
