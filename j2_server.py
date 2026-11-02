"""Live page for the J2 department demo.

Run:  python j2_server.py                         opens http://127.0.0.1:8773
      STUDIO_MOCK=1 python j2_server.py           offline, scripted functions
Every response goes through redact(): API keys, tokens and .env values never reach the page.
"""
import argparse
import http.server
import json
import os
import re
import webbrowser
from urllib.parse import parse_qs, urlparse

import j2
import j2_agent
import j2_artifacts
import j2_map
import j2_story
import llm
from j2 import HERE, J2Run, clear_lessons

RUN = J2Run()
VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")      # never HERE: tests point HERE at a temp page
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def secrets():
    """Values the page must never show: every .env value and any env var whose name looks like a credential."""
    vals = {v for k, v in os.environ.items() if any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH"))}
    try:
        with open(os.path.join(HERE, ".env"), encoding="utf-8") as f:
            vals |= {ln.split("=", 1)[1].strip().strip("\"'") for ln in f if "=" in ln and not ln.lstrip().startswith("#")}
    except OSError:
        pass
    return sorted((v for v in vals if len(v) >= 8), key=len, reverse=True)


def redact(text):
    for v in secrets():
        text = text.replace(v, "[redacted]")
    return text


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", name="prd.docx"):
        if ctype in ("image/png", DOCX):     # a screenshot or a .docx: binary, no text to redact
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if ctype == DOCX:
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.end_headers()
            return self.wfile.write(body)
        data = redact(body if isinstance(body, str) else body.decode("utf-8", "replace")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "j2_ui.html"), encoding="utf-8") as f:
                return self._send(200, f.read(), "text/html")
        if u.path == "/vendor/d3.min.js":      # the Map's Tree view library, served from this folder (no CDN: the page works offline)
            with open(os.path.join(VENDOR, "d3.min.js"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            return self.wfile.write(body)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        run = q.get("run")              # a saved run's folder name, opened read-only
        if run and run == os.path.basename(RUN.dir) and not os.path.isdir(RUN.dir):
            run = None                  # the live run's id before its folder exists (no prompt sent yet): the live run, empty
        if u.path == "/api/state":
            since = int(q.get("since", "0"))
            snap = j2.saved_snapshot(run, since) if run else {**RUN.snapshot(since), "saved": None}
            return self._send(200, json.dumps(snap, ensure_ascii=False)) if snap else self._send(404, '{"error": "no such run"}')
        if u.path == "/api/runs":
            return self._send(200, json.dumps({"live": os.path.basename(RUN.dir), "runs": j2.list_runs()}))
        if u.path == "/api/call":       # one AI call in full, for the detail view's "full text" toggle
            d = j2.saved_dir(run) if run else RUN.dir
            rec = j2.call_record(d, int(q.get("id", "0") or 0))
            return self._send(200, json.dumps(rec, ensure_ascii=False)) if rec else self._send(404, '{"error": "no such call"}')
        if u.path == "/api/preview":    # an atom's section by its anchor id, from the built page, for the atom card's frame
            r = RUN if not run else None
            sd = j2.saved_dir(run)
            wfs = r._all_wfs() if r else (j2._read(sd, "workflows.json", []) if sd else [])          # a missing run has no workflows
            at = next((a for w in wfs for a in w.get("atoms") or [] if a["id"] == q.get("atom")), None)
            ao = (at or {}).get("agent_output") or {}
            if ao.get("kind") == "doc":          # a document atom: its section as the page renders markdown
                bd = r.dir if r else sd
                body = j2.atom_section_body(bd, wfs, q.get("atom")) if bd and os.path.isdir(bd) else None
                return self._send(200, json.dumps({"anchor": None, "html": j2.md_html(body, "Section") if body else None}))
            anchor = ao.get("anchor")
            page = r.sites[-1] if r and r.sites else ""
            if run and j2.saved_dir(run):
                p = os.path.join(j2.saved_dir(run), "site", "index.html")
                page = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
            return self._send(200, json.dumps({"anchor": anchor, "html": j2.preview_doc(page, anchor) if anchor else None}))
        if u.path == "/api/docs":       # the Documents tab: prd.md, hld.md, lld.md of a run, read-only, only those names
            d = j2.saved_dir(run) if run else RUN.dir
            d = d if d and os.path.isdir(d) else None                               # a missing run folder: the empty shape below
            made = (j2._read(d, "documents.json", {}) if d else {}) if run else RUN.docs   # the documents run's record, with the workflows that built each
            out = {}
            for k in ("prd", "hld", "lld"):
                try:
                    with open(os.path.join(d, f"{k}.md"), encoding="utf-8") as f:
                        text = f.read()
                except (OSError, TypeError):
                    text = None
                out[k] = {"asked": text is not None or k in made or (not run and k in RUN.docset), "text": text,
                          "workflows": (made.get(k) or {}).get("workflows", [])}
            return self._send(200, json.dumps(out, ensure_ascii=False))
        if u.path == "/api/map":        # the Map tab: the run's work in order (map/1); a running run is drawn from its live state
            d = j2.saved_dir(run) if run else RUN.dir
            live = None
            if not run and RUN.status == "running" or (not run and RUN.paused):
                live = {"snapshot": RUN.snapshot(), "stages": list(RUN.stages), "stage_words": j2.J2Run.STAGE_WORDS,
                        "board": RUN.board}
            return self._send(200, json.dumps(j2_map.build(d if d and os.path.isdir(d) else None, live), ensure_ascii=False))
        if u.path == "/api/plan":       # the Workflows tab: the stages the Strategist chose and the replans (realization.json)
            d = j2.saved_dir(run) if run else RUN.dir
            return self._send(200, json.dumps(j2_map.plan_view(d if d and os.path.isdir(d) else None), ensure_ascii=False))
        if u.path == "/api/artifacts":  # the Artifacts tab: deliverables, then evidence and records (artifacts/types.json)
            d = j2.saved_dir(run) if run else RUN.dir
            return self._send(200, json.dumps(j2_artifacts.listing(d if d and os.path.isdir(d) else None), ensure_ascii=False))
        if u.path == "/api/agent":      # one agent's conversations and AI calls (agent/1), from the run's chat.jsonl and calls.jsonl
            d = j2.saved_dir(run) if run else RUN.dir
            return self._send(200, json.dumps(j2_agent.view(d if d and os.path.isdir(d) else None, q.get("who")), ensure_ascii=False))
        if u.path == "/api/code":       # the text behind a Code or Sections row of the Artifacts tree, read-only
            d = j2.saved_dir(run) if run else RUN.dir
            txt = j2_artifacts.code_text(d if d and os.path.isdir(d) else None, q.get("deck"), q.get("section"))
            return self._send(200, txt, "text/plain") if txt is not None else self._send(404, "not found", "text/plain")
        if u.path == "/api/artifacts/tree":      # the Artifacts tab as a tree (artifacts-tree/1), made from the same data as the Map
            d = j2.saved_dir(run) if run else RUN.dir
            live = {"snapshot": RUN.snapshot(), "stages": list(RUN.stages), "stage_words": j2.J2Run.STAGE_WORDS, "board": RUN.board} \
                if not run and (RUN.status == "running" or RUN.paused) else None
            ok = d and os.path.isdir(d)
            return self._send(200, json.dumps(j2_artifacts.tree(d, j2_map.build(d, live)) if ok else j2_artifacts.tree(None), ensure_ascii=False))
        if u.path == "/api/artifact":   # one file the run's artifact list names, read-only; nothing else is served
            d = j2.saved_dir(run) if run else RUN.dir
            p = j2_artifacts.served(d if d and os.path.isdir(d) else None, q.get("name"))
            if not p:
                return self._send(404, "not found", "text/plain")
            ext = os.path.splitext(p)[1]
            with open(p, "rb") as f:
                data = f.read()
            return self._send(200, data, "image/png") if ext == ".png" else self._send(200, data, DOCX, os.path.basename(p)) if ext == ".docx" else \
                self._send(200, data, "text/html" if ext == ".html" else "text/plain")
        if u.path == "/api/story":      # the Board story view: what each board question did (story/1), live or saved
            d = j2.saved_dir(run) if run else RUN.dir
            live = None
            if not run and (RUN.status in ("running", "waiting") or RUN.paused):
                live = {"snapshot": RUN.snapshot(), "board": RUN.board}
            return self._send(200, json.dumps(j2_story.build(d if d and os.path.isdir(d) else None, live),
                                              ensure_ascii=False))
        if u.path == "/api/board":      # the Board tab: message board entries (board/1), live or saved
            if not run and RUN.status in ("running", "waiting") or (not run and RUN.paused):
                return self._send(200, json.dumps(RUN.board, ensure_ascii=False))
            d = j2.saved_dir(run) if run else RUN.dir
            out = j2._read(d, "board.json", {}) if d and os.path.isdir(d) else {}
            return self._send(200, json.dumps(out or {"schema": "board/1", "entries": []}, ensure_ascii=False))
        if u.path == "/api/audits":     # earlier stages' audits, condensed to ids and results, for a revise atom's Fixes line
            d = j2.saved_dir(run) if run else RUN.dir
            d = d if d and os.path.isdir(d) else None                               # a missing run folder: no audits
            pick = lambda rows, *keys: [{k: r.get(k) for k in keys if k in r} for r in rows or []]
            out = [{"stage": st.get("stage"), "cycle": a.get("cycle"), "results": pick(a.get("results"), "id", "verdict", "pass"),
                    "extra_issues": pick(a.get("extra_issues"), "id", "verdict"), "rubric": pick(a.get("rubric"), "id", "verdict", "pass"),
                    "conditions": pick(a.get("conditions"), "id", "met")}
                   for f in sorted(os.listdir(d) if d else []) if re.fullmatch(r"stage-\w+\.json", f)
                   for st in [j2._read(d, f, {}) or {}] for a in st.get("audits") or []]
            return self._send(200, json.dumps(out, ensure_ascii=False))
        if u.path == "/api/refs":       # ids the cards name, with their text: conditions/*.json and every output type's rubric
            conds = {}
            for n in ("website", "prd", "hld", "lld"):
                conds.update({c["id"]: c["text"] for c in j2.load_conditions(f"{n}.json")})
            rub = {i: t for o in j2.OUTPUTS.values() for i, t in o.get("rubric") or ()}
            return self._send(200, json.dumps({"conditions": conds, "rubric": rub}, ensure_ascii=False))
        if u.path.startswith("/shot/"):        # the screenshot Audit looked at for site vN
            d, n = (j2.saved_dir(run) if run else RUN.dir), u.path.rsplit("/", 1)[-1]
            path = os.path.join(d or "", "site", "shots", f"v{n}.png")
            if not (d and n.isdigit() and os.path.exists(path)):
                return self._send(404, "not found", "text/plain")
            with open(path, "rb") as f:
                return self._send(200, f.read(), "image/png")
        if u.path.startswith("/file/"):        # a document run's prd.md or prd.docx, to download
            d, name = (j2.saved_dir(run) if run else RUN.dir), u.path.rsplit("/", 1)[-1]
            o = j2.OUTPUTS[j2.saved_output(d) if run else RUN.output]
            allowed = [o["file"], o["file"][:-3] + ".docx"] if o.get("file") else []
            allowed += [f for k in j2._read(d or "", "documents.json", {}) for f in (f"{k}.md", f"{k}.docx")]   # design documents
            path = os.path.join(d or "", name)
            if name not in allowed or not os.path.exists(path):
                return self._send(404, "not found", "text/plain")
            with open(path, "rb") as f:
                data = f.read()
            return self._send(200, data, DOCX, name) if name.endswith(".docx") else \
                self._send(200, data, "text/markdown")
        if u.path.startswith("/site/") and run:
            d, key = j2.saved_dir(run), u.path.rsplit("/", 1)[-1]
            site = os.path.join(d or "", "site")
            num = lambda f: int(f[1:].split(".")[0])
            vs = sorted((f for f in os.listdir(site) if re.fullmatch(r"v\d+\.(?:html|md)", f)), key=num) \
                if d and os.path.isdir(site) else []
            name = vs[-1] if key == "latest" and vs else next((f for f in vs if f.split(".")[0] == key), None)
            if not name:
                return self._send(200, "<p style='font:14px system-ui;color:#667;padding:24px'>No site in this run.</p>",
                                  "text/html")
            with open(os.path.join(site, name), encoding="utf-8") as f:
                text = f.read()
            return self._send(200, j2.md_html(text) if name.endswith(".md") else text, "text/html")
        if u.path.startswith("/site/"):
            if not RUN.sites:
                return self._send(200, "<p style='font:15px system-ui;color:#667;padding:24px'>Your "
                                       f"{'document' if RUN.doc else 'website'} will appear here once it's built.</p>",
                                  "text/html")
            key = u.path.rsplit("/", 1)[-1]
            i = len(RUN.sites) if key == "latest" else int(key.lstrip("v") or 0)
            if not 1 <= i <= len(RUN.sites):
                return self._send(404, "not found", "text/plain")
            return self._send(200, j2.md_html(RUN.sites[i - 1], RUN.out["label"]) if RUN.doc else RUN.sites[i - 1],
                              "text/html")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/say":
            text = (body.get("text") or "").strip()
            if not text:
                return self._send(400, '{"error": "empty"}')
            ok = RUN.user_says(text)
            return self._send(200 if ok else 409, json.dumps({"ok": ok}))
        if self.path == "/api/playbooks/clear":    # the Playbooks tab's "Clear playbooks" (the page confirms first)
            return self._send(200, json.dumps({"ok": True, "cleared": j2.clear_playbooks()}))
        if self.path == "/api/lessons/clear":      # the Lessons tab's "Clear memory" (the page confirms first)
            return self._send(200, json.dumps({"ok": True, "cleared": clear_lessons()}))
        if self.path == "/api/output":           # the start page's output type, before the first message
            ok = RUN.set_output(body.get("type"))
            return self._send(200 if ok else 409, json.dumps({"ok": ok, "output": RUN.output}))
        if self.path == "/api/reset":
            if RUN.status == "running":
                return self._send(409, '{"ok": false}')
            RUN.reset()
            return self._send(200, '{"ok": true}')
        self._send(404, "{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8773)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print("Mode:", "MOCK (scripted functions)" if llm.MOCK else f"{llm.PROVIDER} ({llm.MODEL})")
    print("Open:", url)
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
