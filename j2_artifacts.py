"""Artifacts of a run, listed from artifacts/types.json (read-only; j2.py's flow does not read the list).

rows(run_dir) scans a run folder against the list: one row per deliverable the run built and per record file it kept.
write(run_dir) saves those rows as artifacts.json at the end of a run; listing(run_dir) reads that file, or scans an older
run that has none. Code only, no model call.
"""
import glob
import hashlib
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES_PATH = os.path.join(HERE, "artifacts", "types.json")
OPEN = {"doc": "text", "data": "text", "page": "preview", "image": "image"}      # how the Artifacts tab shows a form
TEXT = {".md": "text/markdown", ".json": "application/json", ".jsonl": "text/plain", ".txt": "text/plain",
        ".html": "text/html", ".png": "image/png"}
MAX_BYTES = 2_000_000


def load_types():
    with open(TYPES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _read(d, name, default=None):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _num(path):
    m = re.search(r"(\d+)", os.path.basename(path))
    return int(m.group(1)) if m else 0


def _stat(d, rel):
    p = os.path.join(d, rel)
    with open(p, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return sha, time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(p)))


def _version(d, t, single):
    """The latest build of a deliverable, from the version files in site/: hld-v3.md, v3.html (a one-document run keeps
    plain names: v3.md)."""
    site = os.path.join(d, "site")
    if not os.path.isdir(site):
        return None
    if t["form"] == "page":
        pat = r"v(\d+)\.html"
    else:
        pat = rf"{t['name']}-v(\d+)\.md" + (r"|v(\d+)\.md" if single else "")
    n = [int(next(g for g in m.groups() if g)) for f in os.listdir(site) for m in [re.fullmatch(pat, f)] if m]
    return max(n) if n else None


def _atoms(d):
    """The atom/1 views of a run: atoms.json, else built from the stored workflows (older runs)."""
    rows = (_read(d, "atoms.json", {}) or {}).get("atoms")
    if rows is None:
        import j2_schema
        rows = j2_schema.run_views(_read(d, "workflows.json", []) or [], ended=True)[0]
    return rows


def _board(d, atoms):
    """What the message board (board/1) changed and re-checked, per deliverable type: {type: {"changed_by": [Q-n],
    "rechecked_after": [Q-n]}}, from board.json only. Empty when the run has no board."""
    entries = (_read(d, "board.json", {}) or {}).get("entries") or []
    wf_of = {v["id"]: v.get("workflow") for v in atoms}
    out = {}
    for e in entries:
        up = e.get("artifact_update") or {}
        if up.get("doc"):
            out.setdefault(up["doc"], {}).setdefault("changed_by", []).append(e["id"])
            # the changed document itself: its own conditions and the owner's checks were re-run
            out[up["doc"]].setdefault("rechecked_after", []).append(e["id"])
        for x in e.get("impact") or []:
            wid = wf_of.get(x.get("atom"))
            if wid:
                out.setdefault(("_wf", wid), {}).setdefault("rechecked_after", []).append(e["id"])
    return out


def rows(d, types=None):
    """[{name, type, kind, form, file, deliverable, workflows, depends_on, version, sha256, time}] for a run folder,
    plus changed_by and rechecked_after when the message board changed or re-checked it."""
    types = types or load_types()
    if not d or not os.path.isdir(d):
        return []
    atoms, docs, out = _atoms(d), _read(d, "documents.json", {}) or {}, []
    board = _board(d, atoms)
    for t in types["types"]:
        files = [os.path.relpath(p, d) for p in sorted(glob.glob(os.path.join(d, t["file"])), key=_num)] \
            if "*" in t["file"] else [t["file"]] if os.path.isfile(os.path.join(d, t["file"])) else []
        wf = []
        if t["kind"] == "type":
            rx = re.compile(t["workflow"]["refs"])
            wf = sorted({v["workflow"] for v in atoms for o in v.get("output") or []
                         if o.get("verb") == "make" and rx.search(str(o.get("ref") or ""))}, key=_num)
        changed = sorted(set((board.get(t["name"]) or {}).get("changed_by") or []), key=_num)
        rechecked = sorted({q for w in wf for q in (board.get(("_wf", w)) or {}).get("rechecked_after") or []}
                           | set((board.get(t["name"]) or {}).get("rechecked_after") or []), key=_num)
        for rel in files:
            sha, when = _stat(d, rel)
            out.append({"name": t["label"] if len(files) == 1 or t["kind"] == "type" else
                        f"{t['label']} {os.path.splitext(os.path.basename(rel))[0]}",
                        "type": t["name"], "kind": t["kind"], "form": t["form"], "file": rel, "deliverable": t["deliverable"],
                        "workflows": wf, "depends_on": list(t["depends_on"]) if "depends_on" in t else [],
                        "version": _version(d, t, len(docs) <= 1) if t["kind"] == "type" else None,
                        **({"changed_by": changed} if changed else {}),
                        **({"rechecked_after": rechecked} if rechecked else {}),
                        "sha256": sha, "time": when})
    built = {r["type"] for r in out}
    for r in out:      # what it depends on in this run: only the types that were built
        r["depends_on"] = [x for x in r["depends_on"] if x in built]
    return out


def write(d):
    """artifacts.json in the run folder (additive: nothing else is touched)."""
    r = {"schema": "artifacts/1", "rows": rows(d)}
    with open(os.path.join(d, "artifacts.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    return r


def listing(d):
    """What the Artifacts tab shows: the saved artifacts.json when the run has one, else the same rows built by
    scanning the folder. Each row gets its type's label, tag, colour and how to open it."""
    types = load_types()
    by = {t["name"]: t for t in types["types"]}
    saved = _read(d, "artifacts.json") if d else None
    base = saved["rows"] if saved else rows(d, types)
    full = [{**r, "label": by[r["type"]]["label"], "tag": by[r["type"]]["tag"], "color": by[r["type"]]["color"],
             "open": OPEN[r["form"]], "depends_on_labels": [by[x]["label"] for x in r["depends_on"] if x in by],
             "saved": bool(saved)} for r in base if r["type"] in by]
    return {"deliverables": [r for r in full if r["deliverable"]], "records": [r for r in full if not r["deliverable"]]}


def served(d, name):
    """The path of a file named in the run's artifact rows (saved, or found now by the types list), else None. Nothing
    else is ever served."""
    name = str(name or "")
    if not d or ".." in name.split("/") or os.path.isabs(name):
        return None
    ok = {r["file"] for r in (listing(d)["deliverables"] + listing(d)["records"])} | {r["file"].replace(os.sep, "/")
                                                                                     for r in rows(d)}
    if name not in ok:
        ok |= set(tree_files(tree(d)))      # the tree's files: versions, the style guide, exports and the run's other records
    p = os.path.join(d, name)
    return p if name in ok and os.path.isfile(p) and os.path.getsize(p) <= MAX_BYTES else None


# ---------------------------------------------------------------------------------------------------------------- the tree
# The Artifacts tab as a tree (artifacts-tree/1): Plan, Specs (the style guide with them), Deliverable, Proof (the screenshots as
# Verification proof, then the check records, then the run's other files as Run records). Makers, readers and statuses come
# from j2_map.build, the same data the Map draws, so the two always agree; the files come from listing() and the run folder, each
# exactly once. Nothing names a run, a workflow or a stage: only file kinds (types.json) and the map's own fields.
TREE_STATUS = {"filed": "filed", "done_unchecked": "checks did not pass", "fault": "failed", "left_open": "open", "running": "open",
               "waiting": "open", "waiting_on_you": "open", "not_made": "not made", "idle": "filed"}
RECORD_MAKER = {"goal.json": "Client Lead (Identity)", "realization.json": "Adaptation (scored by the confidence judge)", "audits.json": "Quality Reviewer (Audit)", "receipts.jsonl": "Checker (automatic)",
                "chat.jsonl": "every function (the chat)", "calls.jsonl": "every function (AI calls)"}      # who writes each kind of record
PROOF = ("receipts.jsonl", "audits.json", "conditions.json")
RECORD_NAME = {"calls.jsonl": "AI calls", "outputs.jsonl": "Workflow outputs", "map.json": "Map data", "artifacts.json": "Artifact list",
               "report.json": "Run report (data)", "sections.json": "Sections", "documents.json": "Documents record"}      # files types.json does not list


def _lines(d, f):
    try:
        with open(os.path.join(d, f), encoding="utf-8") as fh:
            return sum(1 for x in fh if x.strip())
    except OSError:
        return 0


def sections_of(d, decks):
    """{deck id: (record file, {section id: entry})}: a document's sections from its stage-<doc>.json, the one box still in work
    from sections.json (as j2_map places them)."""
    out, current = {}, []
    for n in decks:
        k = n["id"].split(":", 1)[1]
        rec = _read(d, f"stage-{k}.json")
        if isinstance(rec, dict) and isinstance(rec.get("sections"), dict):
            out[n["id"]] = (f"stage-{k}.json", rec["sections"])
        else:
            current.append(n)
    cur = _read(d, "sections.json")
    if len(current) == 1 and isinstance(cur, dict) and cur:
        out[current[0]["id"]] = ("sections.json", cur)
    return out


def _code_summary(text, page):
    """What a section holds, in plain words: lines of HTML, CSS rules and lines of JS (a page), else lines of text."""
    text = str(text or "")
    if not page:
        n = sum(1 for x in text.splitlines() if x.strip())
        return f"{n} line{'s' if n != 1 else ''} of text"
    css = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I))
    js = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", text, re.S | re.I))
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    k = lambda n, w: f"{n} {w}{'s' if n != 1 else ''}"
    return ", ".join([k(sum(1 for x in html.splitlines() if x.strip()), "line") + " of HTML", k(css.count("{"), "CSS rule"),
                      k(sum(1 for x in js.splitlines() if x.strip()), "line") + " of JS"])


def code_text(d, deck, section=None):
    """The text a Code or Sections row opens: the full page (site/index.html) or one section's code or text; None if unknown."""
    import j2_map
    if not d or not os.path.isdir(d):
        return None
    if section is None:
        p = os.path.join(d, "site", "index.html")
        return open(p, encoding="utf-8").read() if deck == "work:website" and os.path.isfile(p) else None
    m = j2_map.build(d)
    src = sections_of(d, [n for n in m["nodes"] if n["id"] == deck]).get(deck)
    e = (src[1] if src else {}).get(section)
    return None if not isinstance(e, dict) else (e.get("head") or "") + (e.get("body") or "")


def _template_data(d, name):
    """{"template", "file"} when a run saved the data an artifact was rendered from (J2_ARTIFACT_SCHEMA=1:
    <kind>.json beside the document), else None. Read only; nothing is guessed."""
    f = f"{name}.json"
    rec = _read(d, f, None)
    if not isinstance(rec, dict) or rec.get("schema") != "artifact-schema/1":
        return None
    return {"template": rec.get("template") or "not recorded", "file": f, "version": rec.get("version")}


def tree(d, m=None):
    import j2_map
    if not d or not os.path.isdir(d):
        return {"schema": "artifacts-tree/1", "groups": []}
    m = m or j2_map.build(d)
    lst, types = listing(d), {t["file"]: t for t in load_types()["types"] if "*" not in t["file"]}
    rowsby = {r["file"]: r for r in lst["deliverables"] + lst["records"]}
    by = {n["id"]: n for n in m["nodes"]}
    made_step = {e["to"]: by[e["from"]] for e in m["edges"] if e["kind"] == "step" and by.get(e["from"], {}).get("kind") == "engine"}
    # who reads what, for the tree's Makers and Readers: the map draws a read from the artifact to the team (the step) that read it,
    # and the team to what it made, so an artifact's reader is the artifact its team made
    made_by_team = {e["from"]: e["to"] for e in m["edges"] if e["kind"] == "step" and by.get(e["from"], {}).get("kind") == "engine"}
    reads = [{**e, "to": made_by_team[e["to"]]} for e in m["edges"] if e["kind"] in ("step", "handoff") and e["from"] != "work:charter"
             and by.get(e["from"], {}).get("kind") == "work" and e["to"] in made_by_team]
    used = set()

    def size(f):
        return os.path.getsize(os.path.join(d, f)) if f and os.path.isfile(os.path.join(d, f)) else None

    def opener(f):
        r = rowsby.get(f)
        if r:
            return r["open"]
        ext = os.path.splitext(f or "")[1]
        return "image" if ext == ".png" else "preview" if ext == ".html" else "text"

    def item(name, f=None, made=None, status="filed", **kw):
        if f and (f in used or not os.path.isfile(os.path.join(d, f))):
            f = None      # each file once; a send has no file of its own (its receipt is under Proof)
        if f:
            used.add(f)
        return {"name": name, "file": f, "made_by": made, "status": status, "size": size(f), "open": opener(f) if f else None, **kw}

    def maker(n):
        st = made_step.get(n["id"])
        return {"persona": st["persona"], "workflows": list(n.get("workflows") or [])} if st else None

    def readers(nid):
        return sorted({w for e in reads if e["from"] == nid for w in e.get("readers") or []}, key=lambda w: int(re.sub(r"\D", "", w) or 0))

    def status(n):
        return n.get("send") or TREE_STATUS.get(n.get("status"), n.get("status") or "filed") if n.get("tag") == "Send" else TREE_STATUS.get(n.get("status"), "filed")

    # 1 Plan
    plan = []
    if "work:charter" in by or os.path.isfile(os.path.join(d, "goal.json")):
        wrote = any(e["kind"] == "speaks_to" and e["to"] == "work:charter" and e["from"] == "fn:identity" for e in m["edges"])
        plan.append(item("Charter", "goal.json", {"function": RECORD_MAKER["goal.json"]} if wrote else None))
    rz = _read(d, "realization.json")
    if rz is not None:
        st = rz.get("stages") or {}
        zone = (((rz.get("plan") or {}).get("certainty_assessment")) or {}).get("zone")
        note = [f"zone {zone}" if zone else "", f"{len(st)} stages: {', '.join(st)}" if st else "",
                f"plan confidence {rz['plan_confidence']}" if rz.get("plan_confidence") is not None else ""]
        kids = [item("Realization plan (text)", "realization.md", {"function": "code"})] if os.path.isfile(os.path.join(d, "realization.md")) else []
        plan.append(item("Realization plan", "realization.json", {"function": RECORD_MAKER["realization.json"]}, note=" · ".join(x for x in note if x), children=kids))
    wfs = _read(d, "workflows.json", []) or []
    if os.path.isfile(os.path.join(d, "workflows.json")):
        plan.append(item("Workflows", "workflows.json", {"function": "Validator (code)"}, note=f"{len(wfs)} workflows"))
    # 2 Specs: every decide workflow's file, with its maker and how many workflows read it
    specs = [item(n["label"], n.get("file"), maker(n), status(n), output=n.get("output") if n.get("output") != n["label"] else None, read_by=len(readers(n["id"])), node=n["id"])
             for n in m["nodes"] if n["kind"] == "work" and n.get("tag") == "Spec"]
    specs += [item(n["label"], n.get("file"), maker(n), status(n), node=n["id"], read_by=len(readers(n["id"])))      # the style guide is a guide too
              for n in m["nodes"] if n.get("tag") == "Style"]
    specs += [item(r["name"], f, None, note="no workflow recorded as its maker") for f, r in rowsby.items()
              if r["type"].startswith("workflow_files") and f not in used]
    # 3 Deliverable: each delivered output, with its sections, its versions and exports, and the sends that report it
    deck = [n for n in m["nodes"] if n["kind"] == "work" and n["id"] != "work:charter" and n.get("tag") not in ("Spec", "Style", "Send")]
    sends = [n for n in m["nodes"] if n.get("tag") == "Send"]
    placed_send = set()
    out = []
    secs = sections_of(d, deck)
    wf_name = {w["id"]: w.get("name") or w["id"] for w in wfs if isinstance(w, dict) and w.get("id")}
    persona_of = {}
    for n_ in m["nodes"]:
        if n_["kind"] == "engine":
            for w in n_.get("workflows") or []:
                persona_of.setdefault(w, n_.get("persona"))
    for n in deck:
        kids = []
        t0 = next((x for x in load_types()["types"] if x["kind"] == "type" and f"work:{x['name']}" == n["id"]), None)
        page = bool(t0 and t0["form"] == "page")
        rows_ = []
        for sid, e in (secs.get(n["id"], (None, {}))[1] or {}).items():
            if not isinstance(e, dict):
                continue
            owner = e.get("owner") or sid
            made = sid if sid in wf_name else owner      # the workflow that created it (the section is named by it), else its owner
            text = (e.get("head") or "") + (e.get("body") or "")
            rows_.append({"name": wf_name.get(made) if sid in wf_name else (e.get("workflow") or sid), "file": None, "status": "filed", "size": len(text.encode("utf-8")),
                          "made_by": {"persona": persona_of.get(made), "workflows": [made]}, "open": "code" if page else "codetext",
                          "code": {"deck": n["id"], "section": sid}, "section": sid,
                          **({"rewritten": {"by": owner, "name": wf_name.get(owner, owner)}} if owner != made else {}),
                          "note": _code_summary(text, page)})
        if page and os.path.isfile(os.path.join(d, "site", "index.html")):
            full = {"name": "Full page source", "file": None, "status": "filed", "size": os.path.getsize(os.path.join(d, "site", "index.html")),
                    "made_by": None, "open": "code", "code": {"deck": n["id"]}, "note": "site/index.html, read-only"}
            kids.append(full)
        if rows_:
            kids.append({"name": "Sections", "count": len(rows_), "collapsed": True, "children": rows_})
        t = next((x for x in load_types()["types"] if x["kind"] == "type" and f"work:{x['name']}" == n["id"]), None)
        site = os.path.join(d, "site")
        if t and os.path.isdir(site):
            pat = r"v(\d+)\.html" if t["form"] == "page" else rf"(?:{re.escape(t['name'])}-)?v(\d+)\.md"
            vs = sorted(((int(mm.group(1)), f"site/{f}") for f in os.listdir(site) for mm in [re.fullmatch(pat, f)] if mm))
            if t["form"] != "page" and any(re.fullmatch(rf"{re.escape(t['name'])}-v\d+\.md", f) for f in os.listdir(site)):
                vs = [(k, f) for k, f in vs if os.path.basename(f).startswith(t["name"] + "-")]      # several documents: only this one's
            if vs:
                kids.append({"name": "Versions", "count": len(vs), "collapsed": True,
                             "children": [item(f"v{k}", f, None, "filed") for k, f in vs]})
            base = os.path.splitext(n.get("file") or "")[0]
            for f in sorted(os.listdir(d)):
                if base and f.startswith(os.path.basename(base) + ".") and f != os.path.basename(n.get("file") or "") and f.endswith(".docx"):
                    kids.append(item("Word file", f, {"function": "code (export)"}))
        data = _template_data(d, t["name"])
        if data:
            kids.append(item(f"Template data ({data['template']})", data["file"], {"function": "code (the data the "
                                                                                   "builders sent)"},
                             note=f"rendered from {data['template']}"))
        for s_ in sends:
            if any(e["from"] == n["id"] and e["to"] == s_["id"] for e in reads):
                placed_send.add(s_["id"])
                kids.append(item(s_["label"], None, maker(s_), status(s_), node=s_["id"], note="receipt in Check results"))
        out.append(item(n["label"], n.get("file"), maker(n), status(n), version=n.get("version"), node=n["id"],
                        workflows=len(n.get("workflows") or []), children=kids))
    out += [item(s_["label"], None, maker(s_), status(s_), node=s_["id"], note="receipt in Check results") for s_ in sends if s_["id"] not in placed_send]
    # 4 Proof: the screenshots Audit took while checking (Verification proof), the check records, and every other file the run kept (Run records)
    proof = []
    shots = sorted((f for f, r in rowsby.items() if r["type"] == "screenshots" and f not in used), key=_num)
    if shots:
        proof.append({"name": "Verification proof", "count": len(shots), "collapsed": False, "shots": True,
                      "children": [item(r_["name"], f) for f in shots for r_ in [rowsby[f]]]})
    for f in PROOF:
        if os.path.isfile(os.path.join(d, f)):
            j = _read(d, f)
            n_ = _lines(d, f) if f.endswith(".jsonl") else len(j) if isinstance(j, (list, dict)) else 0
            proof.append(item({"receipts.jsonl": "Check results", "audits.json": "Audits", "conditions.json": "Necessary conditions"}[f], f,
                              {"function": RECORD_MAKER.get(f, "code")}, note=f"{n_} {('entr' + ('y' if n_ == 1 else 'ies')) if f.endswith('.jsonl') else 'item' + ('' if n_ == 1 else 's')}"))
    for f in sorted(os.listdir(d)):
        if re.fullmatch(r"stage-\w+\.json", f):
            proof.append(item(f"Stage record: {f[6:-5]}", f, {"function": "code"}, note=(lambda k: f"{k} audit{'' if k == 1 else 's'}")(len((_read(d, f, {}) or {}).get('audits') or []))))
    rec = []
    for f, r in rowsby.items():
        if f not in used:
            rec.append(item(r["name"], f, {"function": RECORD_MAKER.get(f, "code")}))
    for root, _, files in os.walk(d):
        for x in sorted(files):
            f = os.path.relpath(os.path.join(root, x), d).replace(os.sep, "/")
            if f not in used and not x.startswith("."):
                rec.append(item(types.get(f, {}).get("label") or RECORD_NAME.get(f) or f, f, {"function": RECORD_MAKER.get(f, "code")}))
    if rec:
        proof.append({"name": "Run records", "count": len(rec), "collapsed": True, "children": rec})
    groups = [("plan", "Plan", plan, False), ("specs", "Specs", specs, False), ("deliverables", "Deliverable" if len(out) == 1 else "Deliverables", out, False),
              ("proof", "Proof", proof, False)]
    return {"schema": "artifacts-tree/1", "groups": [{"id": k, "label": lab, "count": len(it), "collapsed": col, "items": it}
                                                       for k, lab, it, col in groups]}


def tree_files(t):
    """Every file the tree shows, once each (for serving and tests)."""
    out = []

    def walk(xs):
        for x in xs:
            if x.get("file"):
                out.append(x["file"])
            walk(x.get("children") or [])
    for g in t.get("groups") or []:
        walk(g["items"])
    return out
