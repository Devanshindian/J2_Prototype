// Browser-free solar systems, for tests: node j2_graph_layout.js <j2_ui.html> <maps.json>   (maps.json: {run: j2_map.build(run)}, or {name: {constellations}})
// Runs the page's script against a stub DOM and prints, for every artifact of every map: the layout at rest (consOf: nodes, label boxes, lines) and, for every
// node that can be focused, what the focus lights and consumes; for every workflow, its own sun (consWfOf). A "states" list on a map entry ({id, fan, grp})
// lays those out too (the scale rules).
const fs = require("fs"), vm = require("vm");
const noop = () => noop;
const el = () => new Proxy({innerHTML: "", textContent: "", value: "", style: {}, dataset: {}, classList: {toggle: noop, add: noop, remove: noop, contains: () => false}, children: []},
  {get: (t, k) => k in t ? t[k] : k === "querySelectorAll" ? () => [] : noop, set: (t, k, v) => (t[k] = v, true)});
const els = {};
const ctx = vm.createContext({document: {getElementById: id => els[id] || (els[id] = el()), querySelector: () => el(), querySelectorAll: () => [], body: el(), addEventListener: noop, createElement: el},
  location: {search: "", href: "", hash: ""}, localStorage: {getItem: () => null, setItem: noop}, CSS: {escape: x => x}, matchMedia: () => ({matches: true, addEventListener: noop}),
  fetch: () => Promise.reject(new Error("no network")), setTimeout: noop, setInterval: noop, requestAnimationFrame: noop, console, URLSearchParams, Date, JSON, Math, Set, Map, Promise});
const scripts = [...fs.readFileSync(process.argv[2], "utf8").matchAll(/<script>([\s\S]*?)<\/script>/g)];
vm.runInContext(scripts[scripts.length - 1][1], ctx);
const maps = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(vm.runInContext(`(maps) => { const res = [];
  const view = G => ({nodes: G.nodes.map(n => ({id: n.id, kind: n.kind, role: n.role || null, x: n.x || 0, y: n.y || 0, box: n.box || [-n.r, -n.r, n.r, n.r], slot: n.slot ? n.slot.section || n.slot.builder : null,
      label: (n.lead || n.kind === "input" || n.kind === "group" || G.kind === "wf") && n.label && n.label.box ? {box: n.label.box, lines: n.label.lines} : null})), rest: G.rest.map(e => ({from: e.from, to: e.to, kind: e.kind, cls: e.cls, pts: e.pts})),
    quiet: G.quiet, left: G.left || null, right: G.right || null, html: consHtml({nodes: []}, G).length});
  for (const [run, m] of Object.entries(maps)){ m.nodes = m.nodes || [];
    const st = s => Object.assign({id: "", focus: "", fan: {}, grp: {}}, s);
    for (const id of Object.keys(m.constellations || {})){ const G = consOf(m, id, st({})), focus = {};
      for (const n of G.nodes) if (n.kind !== "centre" && n.kind !== "part"){ const F = consOf(m, id, st({focus: n.id}));
        focus[n.id] = {lit: [...F.lit].sort(), eat: [...F.eat].sort(), lines: F.lines.map(e => [e.from, e.to, e.kind])}; }
      res.push({run, id, rest: view(G), again: JSON.stringify(view(consOf(m, id, st({})))) === JSON.stringify(view(G)), focus}); }
    for (const w of Object.keys(consIndex(m).wf)){ const G = consWfOf(m, w); res.push({run, wf: w, rest: view(G), again: JSON.stringify(view(consWfOf(m, w))) === JSON.stringify(view(G))}); }
    for (const s of m.states || []){ const G = consOf(m, s.id, st(s)); res.push({run, id: s.id, state: s, rest: view(G)}); } }
  return res; }`, ctx)(maps)));
