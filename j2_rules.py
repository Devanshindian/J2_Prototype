"""artifact-rules/1: the template rules as data, one list per (kind, section), run by a small fixed set of checks.

The split this file completes: the Pydantic models in j2_artifact_models.py say what SHAPE an artifact's data has
(fields, types, required or optional, enums), and everything else - ids in order, references that point at an id that
exists, hex colours, plain CSS, page tags, anchors - is a rule here, written as a plain dict. Rules are data, so a
generic or generated template can carry its own list later without new code.

One function per rule type (RULE_TYPES), paths in a simple syntax:
    "statement"                 a field
    "components"                a list field
    "components[].covers"       a field of every item of a list
    "palette.*"                 every value of an object
run_rules() answers for every rule in the list, never raising: {"rule", "name", "from", "pass", "evidence"}, where
pass is True, False, or None when the run recorded nothing to check it against ("not recorded", never a pass).

Targets of ref_exists are "this.<path>" (the document this section belongs to, as the run has recorded it so far) or
"prd.<path>" / "hld.<path>" / "lld.<path>" (an earlier document). Python 3.9: Optional/List/Dict.
"""
import re
from typing import Any, Dict, List, Optional

SCHEMA = "artifact-rules/1"
HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}$")
CSS_SAFE = re.compile(r'^[^<>{}"\\]*$')          # the same values parse_style has always allowed
PAGE_TAGS = re.compile(r"<\s*(?:!doctype|html|body|head)\b", re.I)
ANCHOR = re.compile(r"#[A-Za-z][\w-]*$")
NOT_RECORDED = "not recorded"


# ---------------------------------------------------------------- paths
def walk(data, path):
    """[(value, owner)] for a path: owner is the object the value came from, so a rule can name the item it failed on
    (its "id", or the key for "palette.*"). A path that doesn't resolve gives []."""
    if not isinstance(path, str) or not path:
        return []
    node, owners = [(data, data)], None
    for part in path.split("."):
        out = []
        for value, owner in node:
            if part == "*":
                if isinstance(value, dict):
                    out += [(v, {"id": k}) for k, v in value.items()]
                continue
            star = part.endswith("[]")
            key = part[:-2] if star else part
            got = value.get(key) if isinstance(value, dict) else None
            if star:
                out += [(x, x if isinstance(x, dict) else owner) for x in got or []]
            elif got is not None:
                out.append((got, owner))
        node, owners = out, owners
    return node


def _id(owner, fallback=""):
    """The id of the item a value came from, for the evidence ("C1 covers R9, ...")."""
    if isinstance(owner, dict):
        for k in ("id", "group", "path", "name"):
            if owner.get(k):
                return str(owner[k])
    return fallback


def _flat(value):
    """Every leaf of a value (for css_safe over an object)."""
    if isinstance(value, dict):
        return [x for v in value.values() for x in _flat(v)]
    if isinstance(value, list):
        return [x for v in value for x in _flat(v)]
    return [value]


def _paths(spec):
    p = spec.get("path")
    return list(p) if isinstance(p, list) else ([p] if p else [])


def _ids(data, path):
    """The id strings a path holds, in order (a list of objects with ids, or a list of id strings)."""
    out = []
    for value, _ in walk(data, path):
        if isinstance(value, dict):
            out.append(str(value.get("id") or ""))
        elif isinstance(value, list):
            out += [str(x.get("id") if isinstance(x, dict) else x) for x in value]
        else:
            out.append(str(value))
    return out


# ---------------------------------------------------------------- the rule types
def ids_sequential(spec, data, docs):
    """ids run P1, P2, ... from 1, each once, in order (the rule P2 / H3 / L2 read on the rendered document)."""
    prefix, path = spec["prefix"], spec["path"]
    ids = [i for i in _ids(data, path) if i]
    if not ids:
        return None, f"no {prefix} ids recorded"
    bad = [i for i in ids if not re.fullmatch(rf"{prefix}\d+", i)]
    if bad:
        return False, f"{', '.join(bad)} is not {prefix}1, {prefix}2, ..."
    nums = [int(i[len(prefix):]) for i in ids]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        return False, f"duplicate id(s): {', '.join(dup)}"
    if nums != list(range(1, len(nums) + 1)):
        return False, f"ids are not in order from {prefix}1: {', '.join(ids)}"
    return True, f"{len(ids)} id(s) {ids[0]} to {ids[-1]}, unique and in order"


def ids_unique(spec, data, docs):
    """Each id once (order free)."""
    ids = [i for i in _ids(data, spec["path"]) if i]
    if not ids:
        return None, "no ids recorded"
    dup = sorted({i for i in ids if ids.count(i) > 1})
    return (not dup), (f"duplicate id(s): {', '.join(dup)}" if dup else f"{len(ids)} id(s), each once")


def ref_exists(spec, data, docs):
    """Every id named at path exists in the target: "this.<path>" (this document as recorded so far) or
    "<doc>.<path>" (an earlier document). With nothing recorded to check against, the answer is "not recorded":
    a rule marked required_target reports that as a failure, as the flow always has."""
    target, path = spec["target"], spec["path"]
    where, _, tpath = target.partition(".")
    doc = (docs or {}).get("this" if where == "this" else where) or {}
    known = {i for i in _ids(doc, tpath) if i}
    named = [(v, o) for v, o in walk(data, path)]
    flat = [(x, o) for v, o in named for x in (v if isinstance(v, list) else [v]) if x]
    if not known:
        text = spec.get("missing_text") or f"{target} is not recorded, so {path} can't be checked"
        if flat and spec.get("required_target"):
            return False, text.format(id=_id(flat[0][1]), bad="", target=target)
        return None, text.format(id=_id(flat[0][1]) if flat else "", bad="", target=target)
    bad = [(str(x), o) for x, o in flat if str(x) not in known]
    if bad:
        first = bad[0]
        text = spec.get("fail_text") or "{id} names {bad}, which is not in " + target
        return False, text.format(id=_id(first[1]), bad=", ".join(sorted({b for b, _ in bad})), target=target)
    return True, (f"{len(flat)} reference(s) point at {target}" if flat else f"no reference named ({target} has "
                  f"{len(known)})")


def enum(spec, data, docs):
    """The value is one of the allowed ones (read case-insensitively, as the models normalise it)."""
    values, path = [str(v) for v in spec["values"]], spec["path"]
    got = [(str(v), o) for v, o in walk(data, path) if v is not None]
    if not got:
        return None, f"no {path} recorded"
    low = {v.lower() for v in values}
    bad = [(v, o) for v, o in got if v.lower() not in low]
    if bad:
        return False, f"{_id(bad[0][1])} has {path.split('.')[-1]} {bad[0][0]!r}, not one of " + ", ".join(values)
    return True, f"all {len(got)} value(s) are one of " + ", ".join(values[:4]) + ("..." if len(values) > 4 else "")


def hex_colour(spec, data, docs):
    """Every value at the path is a hex colour (#1f5f8b or #abc)."""
    got = walk(data, spec["path"])
    if not got:
        return None, f"no {spec['path']} recorded"
    bad = [(_id(o), str(v)) for v, o in got if not HEX.match(str(v or ""))]
    if bad:
        return False, "not a hex colour: " + ", ".join(f"{k} {v!r}" for k, v in bad[:3])
    return True, f"all {len(got)} colour(s) are hex"


def css_safe(spec, data, docs):
    """Every value is a plain CSS value: nothing that can close a rule, a tag or an attribute."""
    got = [(x, o) for p in _paths(spec) for v, o in walk(data, p) for x in _flat(v)]
    if not got:
        return None, "no CSS values recorded"
    bad = [str(v) for v, _ in got if v is not None and not CSS_SAFE.match(str(v))]
    if bad:
        return False, f"not plain CSS (no <, >, {{, }}, \" or \\): {', '.join(repr(x) for x in bad[:3])}"
    return True, f"all {len(got)} value(s) are plain CSS"


def html_no_page_tags(spec, data, docs):
    """The markup is the builder's own: no <html>, <head>, <body> or doctype."""
    got = [(str(v or ""), p) for p in _paths(spec) for v, _ in walk(data, p)]
    if not got:
        return None, "no markup recorded"
    bad = [p for v, p in got if PAGE_TAGS.search(v)]
    if bad:
        return False, f"{', '.join(bad)} contains <html>, <head> or <body> tags"
    return True, "no <html>, <head> or <body> tags"


def anchor_selector(spec, data, docs):
    """An anchor is an id selector: "#classes"."""
    got = [(str(v or ""), o) for v, o in walk(data, spec["path"])]
    real = [(v, o) for v, o in got if v]
    if not real:
        return None, "no anchor recorded"
    bad = [(v, o) for v, o in real if not ANCHOR.fullmatch(v)]
    if bad:
        return False, f"{_id(bad[0][1])} has anchor {bad[0][0]!r}, which is not an id selector like \"#classes\""
    return True, f"{len(real)} anchor(s) are id selectors"


def anchor_in_html(spec, data, docs):
    """The anchor points at an element the markup really has."""
    anchors = [(str(v or ""), o) for v, o in walk(data, spec["anchor_path"])]
    html = " ".join(str(v or "") for v, _ in walk(data, spec["html_path"]))
    real = [(a, o) for a, o in anchors if a]
    if not real or not html.strip():
        return None, "no anchor or no html recorded"
    bad = [(a, o) for a, o in real if f'id="{a[1:]}"' not in html]
    if bad:
        return False, (f"the html has no element with id=\"{bad[0][0][1:]}\", so the anchor {bad[0][0]} points at "
                       "nothing")
    return True, f"{len(real)} anchor(s) point at an element in the html"


def not_empty(spec, data, docs):
    """Every path has something in it (a bool false counts as given; "" and [] do not)."""
    out = []
    for p in _paths(spec):
        got = walk(data, p)
        if not got:
            out.append((p, None))
            continue
        for v, o in got:
            if v is None or (isinstance(v, (str, list, dict)) and not (v.strip() if isinstance(v, str) else v)):
                out.append((p, o))
    if not out:
        total = sum(len(walk(data, p)) for p in _paths(spec))
        return True, f"{total} value(s) given"
    missing = sorted({p for p, _ in out})
    first = next((o for _, o in out if o), None)
    return False, (f"{_id(first) + ': ' if _id(first) else ''}nothing given for " + ", ".join(missing))


def one_of_present(spec, data, docs):
    """At least one of the paths has something in it."""
    for p in _paths(spec):
        for v, _ in walk(data, p):
            if v is not None and (v.strip() if isinstance(v, str) else v):
                return True, f"{p} is given"
    return False, "none of " + ", ".join(_paths(spec)) + " is given"


def url_prefix(spec, data, docs):
    """A url starts with the prefix it must (or is null, when the template allows that)."""
    got = [str(v) for v, _ in walk(data, spec["path"]) if v not in (None, "")]
    if not got:
        return True, f"no {spec['path']} given (allowed)"
    bad = [v for v in got if not v.startswith(spec["prefix"]) or not CSS_SAFE.match(v)]
    if bad:
        return False, f"{bad[0]!r} is not a {spec['prefix']} url"
    return True, f"{len(got)} url(s) start with {spec['prefix']}"


RULE_TYPES = {"ids_sequential": ids_sequential, "ids_unique": ids_unique, "ref_exists": ref_exists, "enum": enum,
              "hex": hex_colour, "css_safe": css_safe, "html_no_page_tags": html_no_page_tags,
              "anchor_selector": anchor_selector, "anchor_in_html": anchor_in_html, "not_empty": not_empty,
              "one_of_present": one_of_present, "url_prefix": url_prefix}


# ---------------------------------------------------------------- the rules, as data
# One list per (kind, section). "name" is the rule as a reader sees it, "from" the condition or the code it comes
# from. Nothing here is code: a template that carries its own rules carries exactly this shape.
PRIORITIES = ["must", "should", "could"]
FIELD_TYPES = ["text", "email", "tel", "url", "number", "date", "time", "select", "textarea", "checkbox", "radio",
               "password", "file"]

RULES = {
    ("prd", "Problem"): [
        {"rule": "not_empty", "path": "statement", "name": "the problem statement is given", "from": "P1"}],
    ("prd", "Users"): [
        {"rule": "not_empty", "path": "users[].group", "name": "every user group is named", "from": "P7"},
        {"rule": "one_of_present", "path": ["users[].actions", "users[].needs"],
         "name": "every group says what it does or what it needs", "from": "P7"}],
    ("prd", "Goals"): [
        {"rule": "ids_sequential", "path": "goals", "prefix": "G",
         "name": "ids G1, G2, ... unique and in order", "from": "P6"}],
    ("prd", "Requirements"): [
        {"rule": "ids_sequential", "path": "requirements", "prefix": "R",
         "name": "ids R1, R2, ... unique and in order", "from": "P2"},
        {"rule": "enum", "path": "requirements[].priority", "values": PRIORITIES,
         "name": "priority is must, should or could", "from": "P2"},
        {"rule": "ref_exists", "path": "requirements[].goals", "target": "this.goals[].id",
         "name": "goals point at a goal id of this document", "from": "P6"}],
    ("prd", "Success metrics"): [
        {"rule": "ref_exists", "path": "success_metrics[].goal", "target": "this.goals[].id",
         "name": "every metric names a goal id of this document", "from": "P6"}],
    ("prd", "Out of scope"): [
        {"rule": "not_empty", "path": "out_of_scope", "name": "the out-of-scope lines are given", "from": "P1"}],
    ("hld", "Purpose and scope"): [
        {"rule": "not_empty", "path": "purpose", "name": "the purpose is given", "from": "H1"}],
    ("hld", "Pages"): [
        {"rule": "ids_sequential", "path": "pages", "prefix": "P",
         "name": "ids P1, P2, ... unique and in order", "from": "H1"}],
    ("hld", "Components"): [
        {"rule": "ids_sequential", "path": "components", "prefix": "C",
         "name": "ids C1, C2, ... unique and in order", "from": "H3"},
        {"rule": "not_empty", "path": "components[].responsibility",
         "name": "every component states its responsibility", "from": "H3"},
        {"rule": "ref_exists", "path": "components[].page", "target": "this.pages[].id",
         "name": "page points at a page id of this document", "from": "H1"},
        {"rule": "ref_exists", "path": "components[].covers", "target": "prd.requirements[].id",
         "required_target": True, "fail_text": "{id} covers {bad}, which is not a requirement of the PRD",
         "missing_text": "{id}: the PRD's requirement ids are not recorded, so Covers can't be checked",
         "name": "covers points at a requirement id of the PRD", "from": "H4"}],
    ("hld", "Data flow"): [
        {"rule": "not_empty", "path": ["data_flows[].from", "data_flows[].to", "data_flows[].data",
                                       "data_flows[].trigger"],
         "name": "every flow has from, to, data and trigger", "from": "H1"}],
    ("hld", "Hosting and deployment"): [
        {"rule": "not_empty", "path": "hosting.kind", "name": "the hosting kind is given", "from": "H1"}],
    ("hld", "Risks"): [
        {"rule": "not_empty", "path": ["risks[].risk", "risks[].mitigation"],
         "name": "every risk has a mitigation", "from": "H1"}],
    ("lld", "Pages and sections"): [
        {"rule": "ids_sequential", "path": "sections", "prefix": "S",
         "name": "ids S1, S2, ... unique and in order", "from": "L2"},
        {"rule": "anchor_selector", "path": "sections[].anchor", "name": "every section has an anchor",
         "from": "L2"},
        {"rule": "ref_exists", "path": "sections[].implements", "target": "hld.components[].id",
         "required_target": True, "fail_text": "{id} implements {bad}, which is not a component of the HLD",
         "missing_text": "{id}: the HLD's component ids are not recorded, so Implements can't be checked",
         "name": "implements points at a component id of the HLD", "from": "L5"}],
    ("lld", "Interactive elements"): [
        {"rule": "ids_sequential", "path": "elements", "prefix": "E",
         "name": "ids E1, E2, ... unique and in order", "from": "L2"},
        {"rule": "not_empty", "path": ["elements[].selector", "elements[].trigger", "elements[].behaviour"],
         "name": "every element has a selector, a trigger and a behaviour", "from": "L3"},
        {"rule": "ref_exists", "path": "elements[].section", "target": "this.sections[].id",
         "name": "section points at a section id of this document", "from": "L2"}],
    ("lld", "Form fields"): [
        {"rule": "ids_sequential", "path": "form_fields", "prefix": "F",
         "name": "ids F1, F2, ... unique and in order", "from": "L2"},
        {"rule": "not_empty", "path": ["form_fields[].name", "form_fields[].type"],
         "name": "every field has a name, a type and a required flag", "from": "L4"},
        {"rule": "enum", "path": "form_fields[].type", "values": FIELD_TYPES,
         "name": "type is one of " + ", ".join(FIELD_TYPES[:4]) + ", ...", "from": "L4"},
        {"rule": "ref_exists", "path": "form_fields[].section", "target": "this.sections[].id",
         "name": "section points at a section id of this document", "from": "L2"}],
    ("lld", "File structure"): [
        {"rule": "not_empty", "path": ["files[].path", "files[].purpose"],
         "name": "every file has a path and a purpose", "from": "L1"}],
    ("lld", "Responsive and accessibility rules"): [
        {"rule": "one_of_present", "path": ["responsive_rules", "accessibility_rules"],
         "name": "the rules are given", "from": "L1"}],
    ("design", "Style guide"): [
        {"rule": "hex", "path": "palette.*", "name": "every palette colour is a hex colour",
         "from": "parse_style (j2.py)"},
        {"rule": "not_empty", "path": ["fonts.heading", "fonts.body"], "name": "heading and body fonts are given",
         "from": "parse_style (j2.py)"},
        {"rule": "css_safe", "path": ["palette", "fonts.heading", "fonts.body", "spacing", "radius", "buttons",
                                      "card"], "name": "every value is plain CSS", "from": "parse_style (j2.py)"},
        {"rule": "url_prefix", "path": "fonts.google_fonts_url", "prefix": "https://fonts.googleapis.com/",
         "name": "the fonts url is a fonts.googleapis.com url or null", "from": "parse_style (j2.py)"}],
    ("website", "Section"): [
        {"rule": "html_no_page_tags", "path": ["html", "head"],
         "name": "the html has no <html>, <head> or <body> tags", "from": "parse_section (j2.py)"},
        {"rule": "anchor_selector", "path": "anchor", "name": "the anchor is an id selector",
         "from": "parse_section (j2.py)"},
        {"rule": "anchor_in_html", "anchor_path": "anchor", "html_path": "html",
         "name": "the anchor points at an element in the html", "from": "N4"},
        {"rule": "ref_exists", "path": "implements", "target": "lld.sections[].id",
         "fail_text": "{id} implements {bad}, which is not a section of the LLD",
         "name": "implements points at a section id of the LLD", "from": "N8"}],
}
# The names a reader sees, derived from the rules themselves: there is no second list to keep in step.
RULE_NAMES = {k: [r["name"] for r in v] for k, v in RULES.items()}


def rules_for(kind, section):
    """The rule specs of one section ([] when the template fixes none)."""
    return [dict(r) for r in RULES.get((str(kind or ""), str(section or "")), [])]


def rule_names(kind, section):
    return [r["name"] for r in rules_for(kind, section)]


def rules_count(kind, section, data=None):
    """How many rules this section is held to, so a receipt can say "n of m"."""
    return len(RULES.get((str(kind or ""), str(section or "")), []))


def run_rules(kind, section, data, docs=None):
    """Every rule of this section, answered: [{"rule", "name", "from", "pass", "evidence"}]. Nothing raises: a rule
    whose own check breaks is reported as not recorded with the reason. docs holds what the run recorded - {"this":
    this document's data so far, "prd": ..., "hld": ..., "lld": ...} - and a target it has nothing for is
    "not recorded", never a pass."""
    return run_specs(rules_for(kind, section), data, docs)


def run_specs(specs, data, docs=None):
    """run_rules for a given list of rule specs (a library template carries its own, in exactly this shape)."""
    out = []
    for spec in [dict(r) for r in specs or []]:
        fn = RULE_TYPES.get(spec.get("rule"))
        if fn is None:
            out.append({**_head(spec), "pass": None, "evidence": f"unknown rule type {spec.get('rule')!r}"})
            continue
        try:
            ok, ev = fn(spec, data or {}, docs or {})
        except Exception as e:      # a rule never breaks a run: it reports what happened
            ok, ev = None, f"the rule could not run: {type(e).__name__}: {e}"
        out.append({**_head(spec), "pass": ok, "evidence": ev})
    return out


def _head(spec):
    return {"rule": spec.get("rule"), "name": spec.get("name"), "from": spec.get("from")}


def failures(results):
    """The evidence of every rule that failed, in order (what the receipt and the retry quote)."""
    return [r["evidence"] for r in results if r["pass"] is False]
