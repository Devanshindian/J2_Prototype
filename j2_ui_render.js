// Browser-free render of j2_ui.html for tests: node j2_ui_render.js <j2_ui.html> <state.json> [previews.json] [docs.json]
// Runs the page's script against a stub DOM and prints {simple, sprog, cards: {workflow id: html}} as JSON.
const fs = require("fs"), vm = require("vm");
const [html, statePath, previewPath, docsPath] = process.argv.slice(2);
const noop = () => noop;
const el = () => new Proxy({innerHTML: "", textContent: "", value: "", style: {}, dataset: {}, disabled: false, open: false,
  classList: {toggle: noop, add: noop, remove: noop, contains: () => false}, children: [], scrollHeight: 0},
  {get: (t, k) => k in t ? t[k] : k === "querySelectorAll" ? () => [] : noop, set: (t, k, v) => (t[k] = v, true)});
const els = {};
const ctx = vm.createContext({
  document: {getElementById: id => els[id] || (els[id] = el()), querySelector: () => el(), querySelectorAll: () => [],
             body: el(), addEventListener: noop, createElement: el},
  location: {search: "", href: "", hash: ""}, localStorage: {getItem: () => null, setItem: noop}, CSS: {escape: x => x}, matchMedia: () => ({matches: true, addEventListener: noop}),
  fetch: () => Promise.reject(new Error("no network")), setTimeout: noop, setInterval: noop, requestAnimationFrame: noop,
  console, URLSearchParams, Date, JSON, Math, Set, Map, Promise});
const src = fs.readFileSync(html, "utf8"), scripts = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const d3file = require("path").join(__dirname, "vendor", "d3.min.js");      // the page's one library (the Map's Tree view), as the page loads it
if (/<script src="vendor\/d3\.min\.js"><\/script>/.test(src) && fs.existsSync(d3file)) vm.runInContext(fs.readFileSync(d3file, "utf8"), ctx);
vm.runInContext(scripts[scripts.length - 1][1], ctx);
const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
state.allChat = state.chat;
const previews = previewPath ? JSON.parse(fs.readFileSync(previewPath, "utf8")) : {};
const docs = docsPath ? JSON.parse(fs.readFileSync(docsPath, "utf8")) : {docs: {}};
const out = vm.runInContext(`(s, p, d) => { if (typeof PREVIEWS !== "undefined") Object.assign(PREVIEWS, p);
  if (typeof CTX !== "undefined") CTX = s; if (typeof MAP !== "undefined") { Object.assign(MAP, d.map || {}); MAPPIN = d.mappin || ""; MAPFILT = d.mapfilt || ""; WFSTEP = d.wfstep || []; }
  if (typeof TREE !== "undefined"){ MAPVIEW = d.mapview || "tree"; Object.assign(TREE, {open: "", wf: "", c: null, zoom: null}, d.tree || {}); }
  if (typeof PLAN !== "undefined"){ for (const k of Object.keys(PLAN)) delete PLAN[k]; Object.assign(PLAN, d.plan || {found: false}); }
  if (typeof ARTS !== "undefined"){ Object.assign(ARTS, d.artifacts || {}); ARTOPEN = d.artopen || ""; Object.assign(ARTTEXT, d.arttext || {}); }
  if (typeof BOARD !== "undefined"){ BOARD.entries.length = 0; BOARD.entries.push(...(d.board || [])); }
  if (typeof STORY !== "undefined" && d.story){ Object.assign(STORY, d.story); RUNLIST = d.runs || []; STORYCMP = d.storycmp || STORYCMP; }
  if (typeof DOCS !== "undefined"){ Object.assign(DOCS, d.docs); FOCUS = d.focus || {}; Object.assign(REFS, d.refs || {}); (d.open || []).forEach(k => FOLD.add(k)); CHFOCUS = d.chfocus || 0; OTAG = d.otag || ""; STAGE_AUDITS.length = 0; STAGE_AUDITS.push(...(d.stage_audits || [])); }
  renderSimple(s);
  return {simple: $("smsgs").innerHTML, sprog: $("sprog").innerHTML,
          cards: Object.fromEntries(s.workflows.map(w => [w.id, atomCards(s, w)])), workflows: typeof renderWorkflows === "function" ? renderWorkflows(s) : "", charter: typeof renderCharter === "function" ? renderCharter(s) : "", docs: typeof renderDocs === "function" ? renderDocs() : "", artifacts: typeof renderArtifacts === "function" ? renderArtifacts() : "", map: typeof renderMap === "function" ? renderMap(MAP) : "", board: typeof renderBoard === "function" ? renderBoard() : "", story: typeof renderStory === "function" ? renderStory() : "", needs: typeof renderNeeds === "function" ? renderNeeds(s) : "", needcount: typeof needsYou === "function" ? needsYou(s).length : -1, branches: typeof MAPBRANCH !== "undefined" ? MAPBRANCH : [], pages: typeof MAPPAGES !== "undefined" ? MAPPAGES : [], given: typeof mapGiven === "function" ? mapGiven(MAP) : [], tree: typeof MAPTREE !== "undefined" ? MAPTREE : null, focusall: d.focusall && typeof treeFocusAll === "function" ? treeFocusAll(MAP) : null, rail: typeof railModel === "function" ? railModel(s, MAP, d.railtabs || []) : null, prio: typeof prioModel === "function" ? prioModel(s) : null, priorities: typeof renderPriorities === "function" ? renderPriorities(s) : "", agent: typeof renderAgent === "function" && d.agent ? renderAgent(d.agent) : ""}; }`, ctx)(state, previews, docs);
console.log(JSON.stringify(out));
