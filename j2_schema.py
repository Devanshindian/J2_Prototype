"""atom/1: one simple, standard shape for a work atom (docs/atom-schema.md, docs/atom-schema.json).

atom_view adapts a stored atom (no stored field is renamed or changed); validate_atom and validate_views give warnings
only: they never change an outcome, a prompt or a retry. Pure functions, no model call.
"""
SCHEMA = "atom/1"
STATUSES = ("open", "closed", "verify_failed", "abandoned")
# Each output item has a verb: MAKE gives an artifact, DO gives a deed (the noun follows from the verb). Forms are open
# lists: unknown forms are recorded, never rejected.
NOUN = {"make": "artifact", "do": "deed"}
MAKE_FORMS = ("doc", "code", "page", "test", "plan", "skill", "app")
DO_FORMS = ("behaviour", "fetch", "send")      # behaviour has scope self; send is external (test sends: dry-run or mock); fetch is not produced yet
FINAL_FORMS = ("page", "doc", "send")      # makes that are the deliverable itself; a send is a deed that ends a chain
MAX_ATTEMPTS = 3
MAKE_CHECKS = {"file-exists": "exists", "element-count": "exists", "grep-count": "exists", "heading-present": "exists",
               "section-not-empty": "exists", "facts-present": "meets the defined output",
               "lld-slice": "meets the defined output"}      # anything else: "valid"
DO_CHECKS = ("behavior-steps", "deed-send")      # a do item has one check, "receipt": a receipt exists and shows success


# Which recorded edge means "this atom's own content was built from that one". A change to an atom travels along
# these and no others: a manifest edge only listed another section's summary in the prompt, and a board edge records
# that an answer was on the prompt, not that the section was built from it. One name per reason, so a run can be
# read (and tested) by name.
import re as _re

CONTENT_EDGES = (("prd_requirements", _re.compile(r"^the PRD's requirements were in this builder's prompt")),
                 ("hld_components", _re.compile(r"^the HLD's components were in this builder's prompt")),
                 ("hld_summary", _re.compile(r"^the HLD component summary was in this builder's prompt")),
                 ("lld_slice", _re.compile(r"^LLD slice\b")),
                 ("declared_dependency", _re.compile(r"^its workflow depends on\b")))


def content_edge(why):
    """The name of the content edge this reason records, or None when it isn't one (a manifest listing, a board
    answer, or anything else a run records about a prompt)."""
    for name, pat in CONTENT_EDGES:
        if pat.match(str(why or "")):
            return name
    return None


def dedupe_edges(edges):
    """The edges with each (atom, reason) pair once, in the order they were recorded."""
    out, seen = [], set()
    for e in edges or []:
        key = (e.get("atom"), e.get("why"))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def atom_status(atom, wf=None, ended=False):
    """One of STATUSES from today's names. atom: passed, failed (after every attempt, and also after each one that will be
    retried), escalated, could not run, or none yet. wf: its workflow's status (registered, held, running, done, failed,
    unfunded). ended: the run is over, so what was never built is abandoned."""
    s, ws = atom.get("status"), (wf or {}).get("status")
    if s == "passed":
        return "closed"
    if s == "escalated" or (s == "failed" and (ws != "running" or (atom.get("attempts") or 0) >= MAX_ATTEMPTS)):
        return "verify_failed"
    if ws == "unfunded" or (ended and not s and ws not in (None, "done")):
        return "abandoned"
    return "open"      # none yet, retrying after a failed attempt, or a check that could not run


def atom_view(atom, wf=None, edges=None, ended=False):
    """The atom/1 view of a stored atom. wf: its workflow (for the name); edges: [{atom, why}] it depends on."""
    ag, a = atom.get("agent_output") or {}, atom
    wid = str(a["id"]).split(".")[0]
    name = (wf or {}).get("name") or ag.get("section_names", [None])[0] or a["id"]
    out, ver = _outputs(a, ag), []
    for r in a.get("results") or []:
        do = r.get("type") in DO_CHECKS
        ver.append({"check": "receipt" if do else MAKE_CHECKS.get(r.get("type"), "valid"),
                    "applies_to": _applies_to(do, r, out), "method": f"{r.get('type')}: {r.get('check')}",
                    "met": r.get("pass"), "evidence": f"{a['id']}:{r.get('attempt')}" if do else r.get("evidence")})
    details = {k: ag[k] for k in ("selectors", "ids", "section", "anchor") if ag.get(k)}
    els = [x for x in a.get("expected_output") or [] if isinstance(x, dict) and x.get("kind") == "element"]
    if els:
        details["elements"] = [x.get("target") for x in els]
    if any(o["verb"] == "do" for o in out):
        sends = any(o["form"] == "send" for o in out if o["verb"] == "do")
        details["scope"] = "external" if sends else "self"      # a send reaches outside; a behaviour step acts on the thing built
        if a.get("deed"):
            details.update(a["deed"])      # channel, mode, sent
    return {"schema": SCHEMA, "id": a["id"], "workflow": wid, "name": name, "owner": (a.get("how") or {}).get("agent"),
            "status": atom_status(a, wf, ended), "attempt": a.get("attempts") or ag.get("attempt"),
            "goal": a.get("goal"), "how": a.get("how"), "constraints": a.get("constraints") or [],
            "context": a.get("context") or [], "defined_output": a.get("expected_output") or [],
            "verification": ver, "output": out, "depends_on": dedupe_edges([dict(e) for e in edges or []]), "used_by": [],
            "notes": (a.get("human_output") or {}).get("text") or "", "details": details,
            # board/1: a board answer changed something this atom was built from (stale until its checks ran again)
            **({"stale": a["board_stale"]} if a.get("board_stale") else {}),
            **({"rechecked": a["board_rechecked"]} if a.get("board_rechecked") else {})}


def atom_kind(view):
    """make, do or mixed, derived from the output items (never stored)."""
    verbs = {o.get("verb") for o in view.get("output") or []}
    return "mixed" if verbs >= {"make", "do"} else "do" if "do" in verbs else "make"


def _outputs(a, ag):
    """MAKE items: the section (or document section) the atom wrote and the files it is in (form page or doc; a section's
    ref is its anchor, a document section's its file and heading). DO items: each behaviour step check run on the page
    (form "behaviour"), its ref the receipt id (atom:attempt) in receipts.jsonl."""
    out, files = [], ag.get("files") or []
    doc = ag.get("kind") == "doc"
    if ag:
        head = next((x.get("target") for x in a.get("expected_output") or [] if isinstance(x, dict) and x.get("kind") == "heading"), None)
        ref = f"{ag.get('file')}#{head or ag.get('section')}" if doc else f"{files[-1] if files else 'site/index.html'}#{ag['anchor']}" \
            if ag.get("anchor") else None
        if ref:
            out.append({"verb": "make", "name": (ag.get("section_names") or [a["id"]])[0], "form": "doc" if doc else "page", "ref": ref})
        out += [{"verb": "make", "name": f, "form": "doc" if f.endswith((".md", ".docx")) else "page" if f.endswith(".html")
                 else "file", "ref": f} for f in files]
    out += [{"verb": "do", "name": r.get("check"), "form": "send" if r.get("type") == "deed-send" else "behaviour", "ref": f"{a['id']}:{r.get('attempt')}"}
            for r in a.get("results") or [] if r.get("type") in DO_CHECKS]
    return out


def _applies_to(do, r, out):
    """The output item a check is about: a do check names its deed; a make check names the section or document the atom wrote."""
    if do:
        return r.get("check")
    t = r.get("target")
    return next((o["name"] for o in out if o["verb"] == "make" and o["form"] in FINAL_FORMS and "#" in o["ref"]), None) or \
        next((o["name"] for o in out if o["verb"] == "make"), None) or (", ".join(map(str, t)) if isinstance(t, list) else str(t))


def link_views(views):
    """used_by: the exact inverse of depends_on (built here, never by an agent). Mutates and returns the views."""
    by = {v["id"]: v for v in views}
    for v in views:
        v["used_by"] = []
    for v in views:
        for e in v["depends_on"]:
            if e["atom"] in by:
                by[e["atom"]]["used_by"].append({"atom": v["id"], "why": e["why"]})
    for v in views:
        v["used_by"] = dedupe_edges(v["used_by"])
    return views


def dependency_edges(wf, workflows):
    """Edges from a workflow's declared dependencies (proposal ids), for a builder that was given the whole page and
    nothing can be attributed. Dependencies that name no workflow produce nothing."""
    ids = {w.get("proposal_id"): w for w in workflows}
    return [{"atom": a["id"], "why": f"its workflow depends on {ids[d].get('name')}"}
            for d in wf.get("dependencies") or [] if d in ids and ids[d] is not wf for a in ids[d].get("atoms") or []]


def run_views(workflows, given=None, ended=False):
    """(views, warnings) for a run. given: {workflow id: {"edges": [{atom, why}], "whole": bool}}, what each builder's
    prompt actually held (recorded by the run). Without a record, or with the whole page given and no attributable
    edge, edges come from workflow dependencies, else stay empty."""
    given, views = given or {}, []
    for w in workflows:
        g = given.get(w["id"]) or {}
        edges = g.get("edges") or (dependency_edges(w, workflows) if g.get("whole", True) else [])
        for a in w.get("atoms") or []:
            views.append(atom_view(a, w, [e for e in edges if e["atom"] != a["id"]], ended))
    link_views(views)
    return views, validate_views(views)


def validate_atom(view, known=None):
    """Warnings for one view: an output item without a verb, an edge to a missing atom (when known ids are given)."""
    out = [f"{view['id']}: output item {o.get('name')!r} has no verb" for o in view.get("output") or [] if o.get("verb") not in NOUN]
    if known is not None:
        out += [f"{view['id']}: depends on {e['atom']}, which is not an atom of this run"
                for e in view.get("depends_on") or [] if e["atom"] not in known]
    return out


def validate_views(views):
    """Warnings for a run: dangling edges, missing verbs, cycles, outputs never used that are not final outputs, and an
    informational note for each mixed atom (valid; recorded in atoms.json only)."""
    known = {v["id"] for v in views}
    out = [w for v in views for w in validate_atom(v, known)]
    state, stack = {}, []

    def walk(i):
        state[i] = 1
        stack.append(i)
        for e in by[i]["depends_on"]:
            j = e["atom"]
            if j not in by:
                continue
            if state.get(j) == 1:
                out.append("cycle: " + " -> ".join(stack[stack.index(j):] + [j]))
            elif j not in state:
                walk(j)
        stack.pop()
        state[i] = 2
    by = {v["id"]: v for v in views}
    for i in by:
        if i not in state:
            walk(i)
    out += [f"{v['id']}: its output is never used and is not a final output" for v in views
            if v["output"] and not v["used_by"] and not any(o.get("form") in FINAL_FORMS for o in v["output"])]
    out += [f"info: {v['id']} is a mixed atom ({sum(o['verb'] == 'make' for o in v['output'])} make, "
            f"{sum(o['verb'] == 'do' for o in v['output'])} do)" for v in views if atom_kind(v) == "mixed"]
    return out
