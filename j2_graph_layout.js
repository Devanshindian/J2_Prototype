// Browser-free layout of the open-team graph, for tests: node j2_graph_layout.js <j2_ui.html> <maps.json>   (maps.json: {run: j2_map.build(run)})
// Runs the page's script against a stub DOM and prints, for every team with a graph, treeGraphOf's boxes, edges and how many edges had to cross a box.
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
console.log(JSON.stringify(vm.runInContext(`(maps) => { const res = []; for (const [run, m] of Object.entries(maps)){ const L = mapTree(m);
  for (const t of (m.teams || [])){ const F = L.stages[t.id] ? treeGraphOf(m, L, t.id) : null; if (!F) continue; const g = F.g;
    res.push({run, team: t.id, nodes: g.nodes.map(n => ({id: n.id, kind: n.kind, box: n.box, x: n.x, y: n.y, col: n.col, row: n.row})), edges: g.edges.map(e => ({from: e.from, to: e.to, kind: e.kind, loop: e.loop, clear: e.clear, pts: e.pts.filter((p, i) => i % 5 === 0)})), unclear: g.unclear, frame: g.frame}); } } return res; }`, ctx)(maps)));
