"""The Map of a run (schema map/1): the work in order, drawn from what the run recorded. Version 1 has the Requester and
the Work row (artifacts with version and status, the steps between them, hand-offs); the Functions and Knows rows are
later versions (their node kinds are in the schema, nothing is drawn or invented for them).

build(run_dir, live=None) is code only, no model call: it reads artifacts.json (or scans the folder as j2_artifacts does),
atoms.json (atom/1), summary.json, goal.json and chat.jsonl. live is the running run's own state, so a run in progress
shows its current statuses: {"snapshot": run.snapshot(), "stages": [...], "stage_words": {...}}. Anything the run did not
record is listed in not_recorded and shown as "not recorded"; nothing is guessed. map.json is written beside atoms.json.
"""
import json
import os
import re

import j2_artifacts as A
import j2_realization as R

SCHEMA = "map/1"
NODE_KINDS = ("person", "function", "engine", "work", "know")      # v2 draws person, function, engine and work
EDGE_KINDS = ("handoff", "step", "speaks_to", "draws_on", "asks", "uses")   # asks/uses: the message board (board/1),
                                                                            # between deliverables only (J2_BOARD=1)
STATUSES = ("filed", "done_unchecked", "running", "waiting", "waiting_on_you", "fault", "left_open", "not_made", "idle")
WORDS = {"filed": "filed and checked", "done_unchecked": "done · checks did not pass", "running": "running now", "waiting_on_you": "waiting on you", "waiting": "waiting", "fault": "fault",
         "left_open": "left open", "not_made": "not made", "idle": "idle"}
FUNCS = ("identity", "adaptation", "priority", "coordination", "audit")
NAMES = {"identity": "Identity", "adaptation": "Adaptation", "priority": "Priority", "coordination": "Coordination", "audit": "Audit"}
# the existing tab that shows each function's work (declared here; a box links to it)
FN_TAB = {"identity": "charter", "adaptation": "workflows", "priority": "conflicts", "coordination": "timeline", "audit": "audit"}
# a team's persona when the stage records no role (the realization stages do): from what its step does, else what it makes
PERSONA_VERB = {"Write": "drafting", "Build": "building", "Send": "sending"}
PERSONA_TAG = {"PRD": "drafting", "HLD": "drafting", "LLD": "drafting", "Site": "building", "Send": "sending"}
PERSONA = {"drafting": {"PRD": "Product Analyst", "HLD": "Solution Architect", "LLD": "Technical Designer"}, "building": "Web Developer",
           "sending": "Messenger"}


def send_word(detail):
    """A send's one word from its atom's note: dry run, sent, skipped (class) or failed (class); "" when it has no note."""
    d = str(detail or "")
    m = re.match(r"(Skipped|Failed) \((\w+)\)", d)
    return "dry run" if re.search(r"dry run", d, re.I) else "sent" if re.match(r"(Sent|Already sent|The .* was sent)\b", d) \
        else f"{m.group(1).lower()} ({m.group(2)})" if m else "skipped (cap)" if d.startswith("Not sent: the cap of") else "failed" if d.startswith("Not sent:") else ""


STEP_VERB = {"doc-sections": "Write", "site-parts": "Build", "send": "Send", "decide": "Write", "style": "Make"}      # what the workflows of that kind do
LEGEND = [
    {"key": "function", "label": "function", "drawn": True},
    {"key": "engine", "label": "engine", "drawn": True},
    {"key": "work", "label": "work with its version", "drawn": True},
    {"key": "filed", "label": "filed and checked", "drawn": True},
    {"key": "done_unchecked", "label": "done · checks did not pass", "drawn": True},
    {"key": "running", "label": "running now", "drawn": True},
    {"key": "left_open", "label": "left open", "drawn": True},
    {"key": "waiting_on_you", "label": "waiting on you", "drawn": True},
    {"key": "fault", "label": "fault", "drawn": True},
    {"key": "not_made", "label": "not made", "drawn": True},
    {"key": "handoff", "label": "hand-off", "drawn": True},
    {"key": "speaks_to", "label": "speaks to", "drawn": True},
    {"key": "asks", "label": "asks (board)", "drawn": True},
    {"key": "uses", "label": "uses (board)", "drawn": True},
]


def file_label(path):
    """A deliverable's own name from its file: artifacts/hint-method.md is "Hint method"."""
    base = re.sub(r"[-_]+", " ", os.path.splitext(os.path.basename(str(path or "")))[0]).strip()
    return base[:1].upper() + base[1:]


def _read(d, name, default=None):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _jsonl(d, name):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []


def _num(wid):
    m = re.search(r"(\d+)", str(wid))
    return int(m.group(1)) if m else 10 ** 6


def empty(why="nothing to draw yet"):
    return {"schema": SCHEMA, "run": None, "live": False, "status": {"state": "not started", "state_status": "idle",
            "checks": {"passed": 0, "run": 0}}, "nodes": [], "edges": [], "legend": LEGEND, "built_from": [],
            "not_recorded": [why]}


def _unchecked(atoms, done):
    """The workflows set to done whose atom did not pass its checks (verify_failed, or still open). A send is never one: one
    not sent (a dry run, skipped or failed) says so on its own box."""
    send = lambda a: any(o.get("form") == "send" for o in a.get("output") or [])
    return sorted({a["workflow"] for a in atoms if a.get("workflow") in done and a.get("status") in ("verify_failed", "open") and not send(a)},
                  key=_num)


def _status(atoms, ended, has_files=True, done=()):
    """A work box's status from its atoms (atom closed = filed; open = running now, or left open once the run ended;
    verify_failed = fault; abandoned = not made). An atom of a workflow set to done that did not pass its checks is never
    filed and checked: the box is done_unchecked (done · checks did not pass) unless something else is worse."""
    bad = set(_unchecked(atoms, done))
    st = [a.get("status") for a in atoms if a.get("workflow") not in bad]
    if not st:
        s = "filed" if has_files or bad else "not_made"      # a file with no atoms recorded: it exists, nothing contradicts it
    elif "verify_failed" in st:
        s = "fault"
    elif all(x == "closed" for x in st):
        s = "filed"
    elif all(x == "abandoned" for x in st):
        s = "not_made"
    else:
        s = "left_open" if ended else "running"
    return "done_unchecked" if bad and s == "filed" else s


def _checks(atoms):
    c = [x for a in atoms for x in a.get("verification") or [] if x.get("met") is not None]
    return {"passed": sum(1 for x in c if x["met"] is True), "run": len(c)}


def _state_line(d, live, atoms, req_waiting):
    """(text, status) for the top pill: who is running now, or how the run ended."""
    if live:
        snap = live.get("snapshot") or {}
        if snap.get("paused"):
            return "Waiting on you", "waiting_on_you"
        work = [x for x in snap.get("lanes") or [] if x.get("status") == "working"]
        if work and snap.get("status") == "running":
            return f"{work[0]['name']} running", "running"
        return {"running": "Running", "waiting": "Waiting"}.get(snap.get("status"), "Idle"), "idle"
    s = _read(d, "summary.json") or {}
    if req_waiting:
        return "Waiting on you", "waiting_on_you"
    word = {"done": "Done", "done_with_open_items": "Done with open items", "stopped": "Stopped", "crashed": "Crashed"}.get(s.get("status"))
    return (word, "idle") if word else ("not recorded", "idle")


def _functions(chat, calls, snap, requester_waiting, nr):
    """The five function boxes. A running run: the lanes (working, waiting, blocked, idle). A finished one: the last known
    state from the chat, never "running": the line says what the function last did. Calls, seconds and tokens come from
    the call log."""
    lanes = {x["id"]: x for x in (snap or {}).get("lanes") or []}
    out = []
    for fn in FUNCS:
        mine = [c for c in calls if c.get("fn") == fn]
        said = [m for m in chat if m.get("who") == fn]
        last = (said[-1].get("text") or "")[:140] if said else ""
        node = {"id": f"fn:{fn}", "kind": "function", "row": "functions", "label": NAMES[fn], "status": "idle", "version": None,
                "tag": None, "color": f"--{fn}", "file": None, "workflows": [], "tab": FN_TAB[fn], "wait_on": None,
                "calls": len(mine), "seconds": round(sum(c.get("seconds") or 0 for c in mine), 1),
                "tokens": {"input": sum((c.get("tokens") or {}).get("input", 0) for c in mine),
                           "output": sum((c.get("tokens") or {}).get("output", 0) for c in mine)}}
        if snap is not None and fn in lanes:
            ln = lanes[fn]
            on = ln.get("on")
            node["status"] = {"working": "running", "waiting": "waiting", "blocked": "fault"}.get(ln.get("status"), "idle")
            if node["status"] == "waiting":
                node["wait_on"] = on
                if on == "Requester":      # "waiting on you" only while a question to the Requester is open (the same source as Needs you)
                    node["status"], node["wait_on"] = ("waiting_on_you", "you") if requester_waiting else ("idle", None)
            doing = (ln.get("doing") or "")[:140]
            node["detail"] = doing if node["status"] != "idle" else (f"last seen: {doing or last}" if (doing or last) else "no message recorded")
        else:
            if fn == "identity" and requester_waiting:
                node["status"], node["wait_on"] = "waiting_on_you", "you"
            node["detail"] = f"last seen: {last}" if last else "no message recorded"
        if not said and not snap:
            nr.append(f"what {NAMES[fn]} did (chat)")
        out.append(node)
    return out


def _work_lines(d, work, calls, docs, nr):
    """speaks_to edges from a function to a work box it acted on, from recorded data only: Identity to the Charter
    (goal.json); each function to a document by its AI calls in the range documents.json recorded; Audit to every box that
    has an audit in stage-*.json. Nothing else is drawn: the rest is listed as not recorded, never guessed."""
    audits = {}
    for f in sorted(os.listdir(d)):
        m = re.fullmatch(r"stage-(\w+)\.json", f)
        if m:
            audits[m.group(1)] = len((_read(d, f, {}) or {}).get("audits") or [])
    site = next((n for n in work if n["id"] == "work:website" and n.get("file")), None)
    if site and "website" not in audits and isinstance(_read(d, "audits.json"), list):      # a plain site run has no stage file: its audits are audits.json
        audits["website"] = len([a for a in _read(d, "audits.json") if (a or {}).get("kind") != "recheck"])
    out = []
    for n in work:
        if n["kind"] != "work" or n["status"] == "not_made":
            continue
        k = n["id"].split(":")[1]
        got = {}
        if k == "charter":
            out.append({"from": "fn:identity", "to": n["id"], "kind": "speaks_to", "label": "wrote the charter", "n": None, "basis": "recorded",
                        "source": {"file": "goal.json"}})
            continue
        rng = (docs.get(k) or {}).get("calls")
        if rng and calls:
            got = {fn: sum(1 for c in calls if c.get("fn") == fn and rng["from"] <= c.get("id", 0) <= rng["to"]) for fn in FUNCS}
            got = {fn: c for fn, c in got.items() if c}
            out += [{"from": f"fn:{fn}", "to": n["id"], "kind": "speaks_to", "label": "calls", "n": c, "basis": "recorded",
                     "source": {"file": "calls.jsonl", "field": "documents.json calls", "value": k}} for fn, c in got.items()]
        if audits.get(k) and "audit" not in got:
            out.append({"from": "fn:audit", "to": n["id"], "kind": "speaks_to", "label": "audits", "n": audits[k], "basis": "recorded",
                        "source": {"file": f"stage-{k}.json" if os.path.isfile(os.path.join(d, f"stage-{k}.json")) else "audits.json", "field": "audits"}})
            got["audit"] = audits[k]
        if not rng:      # no call range: only an audit count is recorded, or nothing
            nr.append(f"which other function worked on {n['label']} (only Audit is recorded)" if got else f"which function worked on {n['label']}: not recorded")
    return out


def _speaks(chat, have):
    """speaks_to edges with message counts: the Requester to Identity (their messages), Identity to the Requester
    (messages addressed to them), and function to function (chat who and next)."""
    edges, n = [], {}
    you = sum(1 for m in chat if m.get("who") == "user")
    back = sum(1 for m in chat if m.get("who") == "identity" and m.get("to_user"))
    for a, b, c in (("person:requester", "fn:identity", you), ("fn:identity", "person:requester", back)):
        if c:
            edges.append({"from": a, "to": b, "kind": "speaks_to", "label": None, "n": c, "basis": "recorded", "source": {"file": "chat.jsonl"}})
    for m in chat:
        a, b = m.get("who"), m.get("next")
        if a in FUNCS and b in FUNCS and a != b:
            n[(a, b)] = n.get((a, b), 0) + 1
    edges += [{"from": f"fn:{a}", "to": f"fn:{b}", "kind": "speaks_to", "label": None, "n": c, "basis": "recorded", "source": {"file": "chat.jsonl", "field": "next"}}
              for (a, b), c in sorted(n.items(), key=lambda x: (FUNCS.index(x[0][0]), FUNCS.index(x[0][1])))]
    return edges


def _board_note(row):
    """What the message board (board/1) did to this deliverable, for the node's own line: the ids that changed it and
    the ids it was re-checked after (artifacts.json, recorded data only)."""
    r = row or {}
    return ((f"; changed by {', '.join(r['changed_by'])}" if r.get("changed_by") else "")
            + (f"; re-checked after {', '.join(r['rechecked_after'])}" if r.get("rechecked_after") else ""))


def build(d, live=None):
    if not d or not os.path.isdir(d):
        return empty("run not found")
    types = A.load_types()
    by = {t["name"]: t for t in types["types"]}
    nr, built_from, ended = [], [], not live
    snap = (live or {}).get("snapshot") or {}
    # deliverable rows: the run's artifacts.json when it has one (a finished run), else a fresh scan of the folder
    saved = None if live else _read(d, "artifacts.json")
    rows = [r for r in (saved["rows"] if saved else A.rows(d, types)) if r["kind"] == "type"]
    built_from.append("artifacts.json" if saved else "folder scan (types.json)")
    if not saved and not live:
        nr.append("artifacts.json (rows rebuilt from the folder)")
    marks = {f"work:{r['type']}": r for r in rows}      # message board (board/1): what it changed and re-checked
    atoms = list(snap.get("atoms_v1", {}).values()) if live else None
    if atoms is None:
        atoms = A._atoms(d)
        built_from.append("atoms.json" if os.path.exists(os.path.join(d, "atoms.json")) else "workflows.json (atoms rebuilt)")
        if not os.path.exists(os.path.join(d, "atoms.json")):
            nr.append("atoms.json (atoms rebuilt from workflows.json)")
    else:
        built_from.append("live run")
    by_wf = {}
    for a in atoms:
        by_wf.setdefault(a["workflow"], []).append(a)
    nodes = []
    # the charter: Identity's, from goal.json
    if os.path.isfile(os.path.join(d, "goal.json")):
        nodes.append({"id": "work:charter", "kind": "work", "row": "work", "label": "Charter", "tag": "Charter", "color": "--charter",
                      "status": "filed", "version": None, "detail": "the plan every workflow reads", "note": "Every team reads the charter.", "file": "goal.json",
                      "workflows": [], "_order": -1})
        nr.append("version of Charter")
    # one node per deliverable the run built
    for r in rows:
        t = by[r["type"]]
        mine = [a for w in r["workflows"] for a in by_wf.get(w, [])]
        nodes.append({"id": f"work:{r['type']}", "kind": "work", "row": "work", "label": t["label"], "tag": t["tag"], "color": t["color"],
                      "status": _status(mine, ended), "version": r.get("version"),
                      "detail": f"{len(mine)} work atoms" if mine else "no work atoms recorded", "file": r["file"],
                      "workflows": r["workflows"], "template": t["workflow"]["template"], "_atoms": mine,
                      "_order": min((_num(w) for w in r["workflows"]), default=10 ** 5)})
        nodes[-1]["_made"] = {"file": "artifacts.json" if saved else "workflows.json", "field": "workflows", "value": r["type"]}
        if r.get("version") is None:
            nr.append(f"version of {t['label']}")
    # a send deed: atoms whose output has form send (deeds are not in types.json yet)
    for wid, ats in sorted(by_wf.items(), key=lambda x: _num(x[0])):
        sends = [a for a in ats if any(o.get("form") == "send" for o in a.get("output") or [])]
        if sends:
            nodes.append({"id": f"work:{wid}", "kind": "work", "row": "work", "label": sends[0].get("name") or "Send", "tag": "Send",
                          "color": "--other", "status": _status(sends, ended), "version": None,
                          "detail": "; ".join(a.get("notes") or "" for a in sends).strip() or "one deed", "file": "receipts.jsonl",
                          "workflows": [wid], "template": "send", "_atoms": sends, "_order": _num(wid),
                          "_made": {"file": "atoms.json" if os.path.exists(os.path.join(d, "atoms.json")) else "workflows.json", "workflow": wid, "field": "output", "value": "send"}})
            nr.append(f"version of {sends[0].get('name') or 'send'}")
    # every workflow in workflows.json sits on one deliverable: a decide workflow (realization) on its own spec, the rest by
    # their stage's deliverable, then by their section, then by their output refs (the rows above). One it can't place is
    # listed by id under not recorded, never dropped.
    wfs = [w for w in ((snap.get("workflows") if live else _read(d, "workflows.json", [])) or []) if isinstance(w, dict) and w.get("id")]
    wfs.sort(key=lambda w: _num(w["id"]))
    done = {w["id"] for w in wfs if w.get("status") == "done"}
    roles = {x["id"]: x for x in R.load_stages()}
    plan = {w.get("name"): w for w in ((((_read(d, "realization.json") or {}).get("plan") or {}).get("workflows")) or [])
            if isinstance(w, dict)}
    rowed = [n for n in nodes if n.get("template") not in (None, "send")]
    refs = {wid: n["id"] for n in rowed for wid in n["workflows"]}
    sends = {wid for n in nodes if n.get("template") == "send" for wid in n["workflows"]}
    secs, staged = {}, set()      # section id -> deliverable: stage-<doc>.json for an earlier document, sections.json for the current one
    for f in sorted(os.listdir(d)):
        m = re.fullmatch(r"stage-(\w+)\.json", f)
        if m and f"work:{m.group(1)}" in {n["id"] for n in rowed}:
            staged.add(f"work:{m.group(1)}")
            secs.update({k: f"work:{m.group(1)}" for k in ((_read(d, f, {}) or {}).get("sections") or {})})
    current = [n for n in rowed if n["id"] not in staged]
    if len(current) == 1:
        for k in _read(d, "sections.json", {}) or {}:
            secs.setdefault(k, current[0]["id"])
    mates = {}
    for w in wfs:
        if w.get("stage") and w["id"] in refs:
            mates.setdefault(w["stage"], []).append(refs[w["id"]])
    by_stage = {k: max(set(v), key=v.count) for k, v in mates.items()}
    holder, unplaced, why = {}, [], {}      # why: the record that put a workflow on its box (file, field, value)
    for w in wfs:
        wid, sec, stage = w["id"], w.get("section"), w.get("stage")
        if wid in sends:
            continue
        p = plan.get(w.get("proposal_id")) or plan.get(w.get("name"))
        decide = stage in roles and (R.kind(p) == "decide" if p else str(w.get("artifact") or "").startswith("artifacts/"))
        at = holder.get(sec) if sec and sec != wid else None
        rec = {"file": "workflows.json", "workflow": wid, "field": "section", "value": sec}
        if not at and decide and (w.get("artifact") or w.get("status") not in ("done", "failed")):      # finished with no file: not a spec, it sits with its stage
            at = f"work:{wid}"
            rec = {"file": "workflows.json", "workflow": wid, "field": "artifact", "value": w.get("artifact")} if w.get("artifact") else \
                {"file": "realization.json", "workflow": wid, "field": "kind", "value": "decide"}
            nodes.append({"id": at, "kind": "work", "row": "work", "label": file_label(w.get("artifact")) if w.get("artifact") else roles[stage]["output"],
                          "output": roles[stage]["output"], "tag": "Spec", "color": "--other",
                          "status": "not_made", "version": None, "detail": "", "file": w.get("artifact"), "workflows": [],
                          "template": "decide", "_atoms": [], "_order": _num(wid), "_team": roles[stage]["role"]})
        if not at and by_stage.get(stage):
            at, rec = by_stage[stage], {"file": "workflows.json", "workflow": wid, "field": "stage", "value": stage}
        if not at and secs.get(sec):
            at = secs[sec]
        if not at and refs.get(wid):
            at, rec = refs[wid], {"file": "artifacts.json" if saved else "workflows.json", "workflow": wid, "field": "workflows", "value": wid}
        if at:
            holder[wid], why[wid] = at, rec
        else:
            unplaced.append(wid)
    if unplaced:
        nr.append(f"workflows not placed on the map: {', '.join(unplaced)}")
    for n in nodes:
        if n.get("template") in (None, "send"):
            continue
        n["workflows"] = [w["id"] for w in wfs if holder.get(w["id"]) == n["id"]]
        n["_atoms"] = [a for wid in n["workflows"] for a in by_wf.get(wid, [])]
        n["status"] = _status(n["_atoms"], ended, has_files=n["template"] != "decide" or os.path.isfile(os.path.join(d, n["file"] or "")), done=done)
        n["detail"] = (f"{len(n['_atoms'])} work atoms" if n["_atoms"] else "no work atoms recorded") + _board_note(marks.get(n["id"]))
        n["_order"] = min((_num(x) for x in n["workflows"]), default=n["_order"])
        if n["workflows"] and why.get(n["workflows"][0]):
            n["_made"] = why[n["workflows"][0]]
        st = {w.get("stage") for w in wfs if w["id"] in n["workflows"]}
        if len(st) == 1 and next(iter(st)) in roles:
            n["_team"] = roles[next(iter(st))]["role"]
    # the style guide (style.json): a small deliverable made by the workflow with style_guide true, beside the one it belongs to
    sg = next((w for w in wfs if w.get("style_guide") and holder.get(w["id"])), None)
    if sg and os.path.isfile(os.path.join(d, "style.json")):
        par = next(n for n in nodes if n["id"] == holder[sg["id"]])
        nodes.append({"id": "work:style", "kind": "work", "row": "work", "label": file_label("style_guide"), "tag": "Style",      # named by the field that records it "color": "--other",
                      "status": "filed", "version": None, "detail": f"made by {sg['id']}", "file": "style.json", "workflows": [sg["id"]],
                      "template": "style", "_atoms": [], "_order": par["_order"] + 0.5, "_team": par.get("_team"),
                      "_made": {"file": "workflows.json", "workflow": sg["id"], "field": "style_guide", "value": True}})
    # planned but not built yet: a live run's stage list (or a saved run's) names what is still to come
    stages = list((live or {}).get("stages") or ((_read(d, "summary.json") or {}).get("design_documents") or {}).get("stages") or [])
    have = {n["id"] for n in nodes}
    words = (live or {}).get("stage_words") or {}
    late = 0
    for k in stages:
        if k in by and f"work:{k}" not in have:
            late += 1
            nodes.append({"id": f"work:{k}", "kind": "work", "row": "work", "label": by[k]["label"], "tag": by[k]["tag"], "color": by[k]["color"],
                          "status": "not_made", "version": None, "detail": "not started", "file": None, "workflows": [],
                          "template": by[k]["workflow"]["template"], "_atoms": [], "_order": 10 ** 5 + late,
                          "_made": {"file": "live run" if live else "summary.json", "field": "stages", "value": k}})
        elif k not in by and k in words and not any(n["tag"] == "Send" for n in nodes):
            late += 1
            nodes.append({"id": f"work:{k}", "kind": "work", "row": "work", "label": words[k][0].upper() + words[k][1:], "tag": "Send",
                          "color": "--other", "status": "not_made", "version": None, "detail": "not started", "file": None,
                          "workflows": [], "template": "send", "_atoms": [], "_order": 10 ** 5 + late,
                          "_made": {"file": "live run" if live else "summary.json", "field": "stages", "value": k}})
    nodes.sort(key=lambda n: n["_order"])
    # who reads what, from each workflow's own records: workflows.json dependencies, the realization plan's inputs_from and the atoms'
    # depends_on. A line from deliverable A to B means a workflow that made B lists one that made A; every line points producer ->
    # consumer and carries its record (source). Every team is given the Charter. Nothing is drawn from run order alone.
    edges, work = [], [n for n in nodes if n["kind"] == "work"]
    owner = {a["id"]: n["id"] for n in work for a in n.get("_atoms") or []}
    named = {}
    for w in wfs:
        named.update({k: w["id"] for k in (w.get("proposal_id"), w.get("name"), w["id"]) if k})
    atom_file = "atoms.json" if os.path.exists(os.path.join(d, "atoms.json")) else "workflows.json"
    reads = {}
    for w in wfs:
        p = plan.get(w.get("proposal_id")) or plan.get(w.get("name")) or {}
        got = [(named.get(x), {"file": "workflows.json", "workflow": w["id"], "field": "dependencies", "value": x}) for x in w.get("dependencies") or []]
        got += [(named.get(x), {"file": "realization.json", "workflow": w["id"], "field": "inputs_from", "value": x}) for x in p.get("inputs_from") or []]
        got += [(str(e.get("atom") or "").split(".")[0], {"file": atom_file, "workflow": w["id"], "field": "depends_on", "value": e.get("atom")})
                for a in by_wf.get(w["id"], []) for e in a.get("depends_on") or []]
        reads[w["id"]] = [(x, src) for x, src in got if x and x != w["id"]]
    on = {}
    for n in work:
        for wid in n.get("workflows") or []:
            on.setdefault(wid, []).append(n["id"])
    readers = {}
    for b in work:
        for wid in b.get("workflows") or []:
            for x, src in reads.get(wid, []):
                for a in on.get(x, []):
                    if a != b["id"]:
                        r = readers.setdefault((a, b["id"]), {"ids": [], "source": src, "sources": []})
                        if wid not in r["ids"]:
                            r["ids"].append(wid)
                        if src not in r["sources"]:
                            r["sources"].append(src)
    # (the reads are drawn below, from the artifact to the team that read it: never artifact to artifact)
    # the trunk (Line view): every deliverable but a send, in an order where each comes after what it reads (run order breaks ties)
    pre = {n["id"]: {a for a, b in readers if b == n["id"]} for n in work}
    trunk, left = [], sorted([n for n in work if n.get("template") != "send"], key=lambda n: n["_order"])
    while left:
        ids_left = {x["id"] for x in left}
        nxt = next((n for n in left if not (pre[n["id"]] & ids_left)), left[0])      # a recorded cycle: run order
        trunk.append(nxt)
        left.remove(nxt)
    tids = [t["id"] for t in trunk]
    # steps: the team that made each deliverable. Its line in is the Charter (every workflow is given it) and, when it reads the box
    # just before it on the trunk (or a send's source), that box; its line out is the record that put its workflows on the box.
    steps, pairs = [], []
    for b in work:
        b["lane"] = "trunk" if b["id"] in tids else "branch"
        if b["id"] == "work:charter":
            continue
        src = [a for a, x in readers if x == b["id"]]
        k = tids.index(b["id"]) if b["id"] in tids else -1
        a = tids[k - 1] if k > 0 and tids[k - 1] in src else (src[0] if k < 0 and src else None)
        pairs.append((a, b))
    for a, b in pairs:
        ats = b.get("_atoms") or []
        ch = _checks(ats)
        wf = len(b["workflows"])
        bad = _unchecked(ats, done)
        detail = (f"{wf} workflow{'s' if wf != 1 else ''} · {ch['passed']} of {ch['run']} checks passed" if wf else "not recorded") \
            + (f" · {len(bad)} done, checks did not pass ({', '.join(bad)})" if bad else "")
        if b.get("template") == "style":
            detail = b["detail"]
        sid = f"step:{(a or 'work:charter').split(':')[1]}>{b['id'].split(':')[1]}"
        steps.append({"id": sid, "kind": "engine", "row": "work", "label": STEP_VERB.get(b.get("template"), "Make"), "status": b["status"],
                      "version": None, "detail": detail, "file": None, "workflows": b["workflows"], "tag": None, "color": None, "lane": b["lane"],
                      "team": b.get("_team"), "unchecked": bad})
        ins = sorted([x for x, y in readers if y == b["id"]], key=lambda x: min((_num(w) for w in readers[(x, b["id"])]["ids"]), default=0))
        for x in ins:       # every artifact one of this team's workflows read: A -> team, with the records that say so
            r = readers[(x, b["id"])]
            edges.append({"from": x, "to": sid, "kind": "step" if x == a else "handoff", "label": "read by " + ", ".join(sorted(r["ids"], key=_num)),
                          "n": len(r["ids"]), "basis": "recorded", "source": r["source"], "sources": r["sources"],
                          "readers": sorted(r["ids"], key=_num)})
        if not ins and "work:charter" in tids:      # every team reads the charter (a note on the Charter): a line only to a team that reads nothing else
            edges.append({"from": "work:charter", "to": sid, "kind": "step", "label": None, "n": wf, "basis": "recorded", "source": {"file": "goal.json", "field": "charter"}})
        made = b.get("_made")
        if made:
            edges.append({"from": sid, "to": b["id"], "kind": "step", "label": None, "n": wf, "basis": "recorded", "source": made})
        if not wf:
            nr.append(f"workflows of {b['label']}")
    # message board (board/1): an "asks" line from the asking deliverable to the answering one, an "uses" line from
    # each reuser's deliverable to it, labelled with the board id. Recorded data only; a question and its reuse inside
    # the same deliverable (the usual case for one website) have no line to draw, same as any self-referencing edge.
    # A question a function asked (asked_by_role "function") has no deliverable on the asking side, so no line
    # either; the Board tab lists every entry whoever asked it.
    board = ((live or {}).get("board") if live else _read(d, "board.json")) or {}
    board_edges = []
    for e in board.get("entries") or []:
        src, dst = owner.get(e.get("atom")), owner.get(e.get("to"))
        if src and dst and src != dst and e.get("status") == "answered":
            board_edges.append({"from": src, "to": dst, "kind": "asks", "label": e["id"], "n": None, "basis": "recorded",
                                "source": {"file": "live run" if live else "board.json", "field": "entries", "value": e["id"]}})
            for ra in e.get("used_by") or []:
                rsrc = owner.get(ra)
                if rsrc and rsrc != dst:
                    board_edges.append({"from": rsrc, "to": dst, "kind": "uses", "label": e["id"], "n": None, "basis": "recorded",
                                        "source": {"file": "live run" if live else "board.json", "field": "used_by", "value": e["id"]}})
    # the Requester
    chat = _jsonl(d, "chat.jsonl") if not live else (snap.get("chat") or [])
    mine = [m for m in chat if m.get("who") == "user"]
    last = next((m for m in reversed(chat) if m.get("who") != "system"), {})      # a system note after Identity's question is not an answer
    waiting = bool(snap.get("paused")) if live else bool(last.get("pause") and last.get("who") == "identity")
    person = {"id": "person:requester", "kind": "person", "row": "people", "label": "You",
              "status": "waiting_on_you" if waiting else "idle", "version": None, "tag": None, "color": "--user", "file": None,
              "detail": f"{len(mine)} message{'s' if len(mine) != 1 else ''} from you" if chat else "not recorded", "workflows": []}
    if not chat:
        nr.append("chat (messages from the Requester)")
    state, state_status = _state_line(d, live, atoms, waiting)
    calls = (snap.get("call_log") if live else _jsonl(d, "calls.jsonl")) or []
    if not calls and not live:
        nr.append("AI calls per function (calls.jsonl)")
    funcs = _functions(chat, calls, snap if live else None, waiting, nr)
    speaks = _speaks(chat, bool(chat))
    docs = _read(d, "documents.json", {}) or {}
    for st in steps:      # which functions made a step: only where documents.json recorded the call range
        rng = (docs.get(st["id"].split(">")[1]) or {}).get("calls")
        if rng and calls:
            per = {fn: sum(1 for c in calls if c.get("fn") == fn and rng["from"] <= c.get("id", 0) <= rng["to"]) for fn in FUNCS}
            st["made_by"] = {"calls": rng, "functions": {fn: n for fn, n in per.items() if n}, "basis": "recorded"}
        else:
            st["made_by"] = None
    lines = _work_lines(d, work, calls, docs, nr)
    if state == "not recorded":
        nr.append("how the run ended (summary.json)")
    def _after(st, b):      # where a side job is listed: after the box it reads; with no recorded source, after the box before it in the plan (order only, no line)
        src = "work:" + st["id"].split(">")[0][5:]
        if src != "work:charter":
            return src
        return next((t["id"] for t in reversed(trunk) if t["_order"] <= b["_order"]), "work:charter")
    # drawing order: each trunk box, then the side jobs that leave it (their step, then the deed), then the step to the next trunk box
    order, into = [], {st["id"].split(">")[1]: st for st in steps}
    for i, n in enumerate(trunk):
        if i:
            order.append(into[n["id"].split(":")[1]])
        order.append(n)
        for b in [x for x in work if x["lane"] == "branch"]:
            st = into.get(b["id"].split(":")[1])
            if st and _after(st, b) == n["id"]:
                order += [st, b]
    # presentation: each team's persona (its stage's role, else from what it does or makes; steps that share a workflow are one
    # team, named as the one with most workflows), a send's word, and each read's reader workflows. The page and the Artifacts tree
    # both read these, so they always agree.
    to = {e["from"]: e["to"] for e in edges if e["kind"] == "step" and e["from"].startswith("step:")}
    for st in steps:
        tag = (next((n for n in work if n["id"] == to.get(st["id"])), None) or {}).get("tag")
        p = PERSONA.get(PERSONA_VERB.get(st["label"]) or PERSONA_TAG.get(tag))
        st["persona"] = st.get("team") or (p if isinstance(p, str) else (p or {}).get(tag) or "Specialist")
    for st in sorted(steps, key=lambda x: -len(x["workflows"])):
        for o in steps:
            if o is not st and len(o["workflows"]) <= len(st["workflows"]) and set(o["workflows"]) & set(st["workflows"]):
                o["persona"] = st["persona"]
    # an artifact one of a team's workflows made and other workflows of the same team read (not the makers themselves): team_reads
    # names both, with the records that say so. The Tree draws it beside its team with a read-back line.
    team_of = {to[st["id"]]: st["persona"] for st in steps if to.get(st["id"])}
    crew = {}
    for st in steps:
        crew.setdefault(st["persona"], set()).update(st["workflows"])
    for n in work:
        mk = set(n.get("workflows") or [])
        got = {w: [s for x, s in reads.get(w, []) if x in mk] for w in crew.get(team_of.get(n["id"]), set()) - mk}
        got = {w: s for w, s in got.items() if s}
        if mk and got:
            n["team_reads"] = {"made_by": sorted(mk, key=_num), "read_by": sorted(got, key=_num), "sources": [s for w in sorted(got, key=_num) for s in got[w]]}
    for n in work:
        if n.get("tag") == "Send":
            n["send"] = send_word(n.get("detail"))
    out_nodes = [person] + funcs + order
    for n in out_nodes:
        for k in ("_atoms", "_order", "template", "_team", "_made"):
            n.pop(k, None)
    ch = _checks(atoms)
    # presentation only, for the Tree view's circle round a stage and a focused workflow: each workflow's name, status, the box it sits on,
    # the workflows it reads (dependencies, then recorded atom edges), what it made ("out": every deliverable that lists it) and its checks.
    # Nothing here changes a node or an edge.
    box_of = {wid: n["id"] for n in out_nodes if n["kind"] == "work" for wid in n.get("workflows") or []}
    made_of = {}
    for n in out_nodes:
        if n["kind"] == "work":
            for wid in n.get("workflows") or []:
                made_of.setdefault(wid, []).append(n["id"])
    flows = []
    for w in wfs:
        ats = by_wf.get(w["id"], [])
        reads = [named[x] for x in w.get("dependencies") or [] if named.get(x) and named[x] != w["id"]]
        reads += [str(e["atom"]).split(".")[0] for a in ats for e in a.get("depends_on") or []]
        st = {a.get("status") for a in ats}
        flows.append({"id": w["id"], "name": w.get("name") or w["id"], "status": w.get("status"), "box": box_of.get(w["id"]),
                      "atoms": next((x for x in ("verify_failed", "open", "abandoned", "closed") if x in st), None),
                      "checks": _checks(ats), "reads": sorted({x for x in reads if x != w["id"]}, key=_num), "out": made_of.get(w["id"], [])})
    return {"schema": SCHEMA, "run": os.path.basename(d), "live": bool(live),
            "status": {"state": state, "state_status": state_status, "checks": ch},
            "nodes": out_nodes, "workflows": flows, "edges": edges + speaks + lines + board_edges, "legend": LEGEND, "built_from": built_from,
            "not_recorded": list(dict.fromkeys(nr + ["messages to and from workflow agents (W-n) are not drawn",
                                                     "what the work draws on (Knows row, later version)"]))}


def write(d):
    """map.json beside atoms.json (additive)."""
    m = build(d)
    with open(os.path.join(d, "map.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
    return m

def plan_view(d):
    """What the Strategist (Adaptation) planned, from realization.json: the stages it chose with their reasons, and the replans. {"found": False} for a run with no plan record."""
    rz = _read(d, "realization.json") if d else None
    if not isinstance(rz, dict) or not isinstance(rz.get("plan"), dict):
        return {"found": False}
    p, conf = rz["plan"], rz.get("stages") or {}
    stages = []
    for s in p.get("stages") or []:
        sid = s.get("id")
        stages.append({"id": sid, "thinking": s.get("thinking") or "", "goal": s.get("goal") or "", "zone": (conf.get(sid) or {}).get("zone"),
                       "confidence": (conf.get(sid) or {}).get("confidence"),
                       "why": [{"name": f.get("name"), "why": f.get("why")} for f in p.get("factors") or [] if sid in (f.get("stages") or []) and f.get("why")],
                       "workflows": [w.get("name") for w in p.get("workflows") or [] if w.get("stage") == sid]})
    a = p.get("analysis") or {}
    replans = [{"round": r.get("round"), "faults": len(r.get("plan_faults") or []),
                "changes": [{"workflow": c.get("workflow"), "remedy": c.get("remedy")} for c in r.get("changes") or []]} for r in rz.get("rounds") or [] if (r.get("round") or 0) > 0]
    return {"found": True, "chosen": a.get("chosen") or "", "options": a.get("options") or [], "zone": (p.get("certainty_assessment") or {}).get("zone"),
            "confidence": rz.get("plan_confidence"), "stages": stages, "replans": replans}
