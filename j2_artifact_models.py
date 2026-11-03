"""artifact-schema/1: the SHAPE of every artifact J2 generates, as Pydantic 2 models (J2_ARTIFACT_SCHEMA=1).

These models say what fields an artifact's data has, their types, which are required and which enums they allow -
and nothing else. Every constraint (ids in order, references that point at an id that exists, hex colours, plain
CSS, page tags, anchors) is a rule in j2_rules.py, written as data and run as its own layer. The one presence rule
that stays here is a website section's "html or head": which fields must be there is shape.

One model per thing a workflow writes, so each builder's schema stays small: a PRD section, an HLD section, an LLD
section, the design style guide, one website section. The document models (PRD/1, HLD/1, LLD/1) are the same fields
assembled, used for the cross-document rules and for rendering.

Two schemas per template, as the structured-output docs require:
  * the TRANSPORT schema, transport_schema(): what goes to the model. Draft-07 (2020-12 is refused by
    `claude --json-schema`), Pydantic's $defs rewritten to definitions, additionalProperties false on every object,
    every field required unless the brief may lack it, no min/max, no length, no pattern, no format, no recursion.
  * the FULL rules, in the validators below: ids in order, cross-references inside the document, hex colours, the
    enum values the parsers read. Anything that needs another document (an HLD component covering a PRD
    requirement) is checked by cross_errors(), which is given the chain.

The renderers write the markdown the existing parsers and conditions already read (parse_hld, parse_lld, md_ids,
P1-P8 / H1-H6 / L1-L6), so nothing downstream changes: the agent sends data, code writes the document.

Python 3.9: Optional/List/Dict, never "X | None".
"""
import copy
import hashlib
import json
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

import j2_rules

SCHEMA = "artifact-schema/1"
VERSION = 1
# Field names that may be missing from a reply because the brief may not say anything about them. Everything else is
# required in the transport schema.
OPTIONAL_FIELDS = {"assumptions", "google_fonts_url", "notes", "window", "target", "validation", "page", "head",
                   "anchor", "html",
                   "selectors_used", "facts_used", "implements", "covers", "goals", "actions", "needs",
                   "responsive_rules", "accessibility_rules", "out_of_scope", "risks", "data_flows", "files"}
# The enums are shape: the model allows these values and no others, and the transport schema carries them.
FIELD_TYPES = tuple(j2_rules.FIELD_TYPES)
PRIORITIES = tuple(j2_rules.PRIORITIES)


class Artifact(BaseModel):
    """Base of every artifact model: strict (no extra keys), and it carries the template name the records show."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    TEMPLATE: ClassVar[str] = "artifact/1"
    SECTION: ClassVar[str] = ""

    @classmethod
    def template(cls):
        return cls.TEMPLATE + (f" · {cls.SECTION}" if cls.SECTION else "")


# ---------------------------------------------------------------- PRD/1
class UserGroup(Artifact):
    group: str = Field(description="the name of this user group, as the charter names it")
    needs: str = Field(default="", description="what this group needs from the product")
    actions: List[str] = Field(default_factory=list, description="what this group does on the page; empty when this "
                                                                "group has no actions in this version")


class Goal(Artifact):
    id: str = Field(description="G1, G2, ... in order")
    statement: str = Field(description="the goal in one line")


class Requirement(Artifact):
    id: str = Field(description="R1, R2, ... in order")
    statement: str = Field(description="what the product must do, naming the user group that does it")
    priority: Literal["must", "should", "could"] = Field(description="must, should or could")
    goals: List[str] = Field(default_factory=list, description="the goal ids this requirement serves, e.g. [\"G1\"]")


class SuccessMetric(Artifact):
    goal: str = Field(description="the goal id this metric measures, e.g. \"G1\"")
    metric: str = Field(description="what is measured")
    target: str = Field(default="", description="the number or state to reach")
    window: str = Field(default="", description="the measurement window, e.g. \"in the first 30 days\"; write "
                                                "\"measurement window not set\" when the brief doesn't say")


class PRDProblem(Artifact):
    TEMPLATE: ClassVar[str] = "PRD/1"
    SECTION: ClassVar[str] = "Problem"
    statement: str = Field(description="the problem the product solves, in the charter's own words")
    assumptions: List[str] = Field(default_factory=list, description="facts you had to assume, each one line")


class PRDUsers(Artifact):
    TEMPLATE: ClassVar[str] = "PRD/1"
    SECTION: ClassVar[str] = "Users"
    users: List[UserGroup] = Field(description="every user group the charter names")
    assumptions: List[str] = Field(default_factory=list)


class PRDGoals(Artifact):
    TEMPLATE: ClassVar[str] = "PRD/1"
    SECTION: ClassVar[str] = "Goals"
    goals: List[Goal] = Field(description="the goals, G1, G2, ... in order")
    assumptions: List[str] = Field(default_factory=list)


class PRDRequirements(Artifact):
    TEMPLATE: ClassVar[str] = "PRD/1"
    SECTION: ClassVar[str] = "Requirements"
    requirements: List[Requirement] = Field(description="the requirements, R1, R2, ... in order")
    assumptions: List[str] = Field(default_factory=list)


class PRDSuccessMetrics(Artifact):
    TEMPLATE: ClassVar[str] = "PRD/1"
    SECTION: ClassVar[str] = "Success metrics"
    success_metrics: List[SuccessMetric] = Field(description="one metric per goal")
    assumptions: List[str] = Field(default_factory=list)


class PRDOutOfScope(Artifact):
    TEMPLATE: ClassVar[str] = "PRD/1"
    SECTION: ClassVar[str] = "Out of scope"
    out_of_scope: List[str] = Field(description="what the product will not do, one line each")
    assumptions: List[str] = Field(default_factory=list)


class PRD(Artifact):
    TEMPLATE: ClassVar[str] = "PRD/1"
    problem: PRDProblem
    users: List[UserGroup] = Field(default_factory=list)
    goals: List[Goal] = Field(default_factory=list)
    requirements: List[Requirement] = Field(default_factory=list)
    success_metrics: List[SuccessMetric] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- HLD/1
class Page(Artifact):
    id: str = Field(description="P1, P2, ... in order")
    name: str = Field(description="the page name")
    purpose: str = Field(description="what the page is for")
    implements: List[str] = Field(default_factory=list, description="the PRD requirement ids this page carries")


class Component(Artifact):
    id: str = Field(description="C1, C2, ... in order")
    name: str = Field(description="the component name")
    responsibility: str = Field(description="its one responsibility, in one line")
    covers: List[str] = Field(default_factory=list, description="the PRD requirement ids it covers, e.g. [\"R1\"]")
    page: str = Field(default="", description="the page id it sits on, e.g. \"P1\"")


class DataFlow(Artifact):
    from_: str = Field(alias="from", description="where the data comes from")
    to: str = Field(description="where it goes")
    data: str = Field(description="what is sent")
    trigger: str = Field(description="what starts it")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class Hosting(Artifact):
    kind: str = Field(description="how it is hosted, e.g. \"one static file on a static host\"")
    notes: str = Field(default="", description="how it is deployed and replaced")


class Risk(Artifact):
    risk: str = Field(description="the risk, one line")
    mitigation: str = Field(description="what is done about it")


class HLDPurpose(Artifact):
    TEMPLATE: ClassVar[str] = "HLD/1"
    SECTION: ClassVar[str] = "Purpose and scope"
    purpose: str = Field(description="what this design covers and what it leaves out")
    assumptions: List[str] = Field(default_factory=list)


class HLDPages(Artifact):
    TEMPLATE: ClassVar[str] = "HLD/1"
    SECTION: ClassVar[str] = "Pages"
    pages: List[Page] = Field(description="the pages, P1, P2, ... in order")
    assumptions: List[str] = Field(default_factory=list)


class HLDComponents(Artifact):
    TEMPLATE: ClassVar[str] = "HLD/1"
    SECTION: ClassVar[str] = "Components"
    components: List[Component] = Field(description="the components, C1, C2, ... in order; each names the PRD "
                                                    "requirement ids it covers")
    assumptions: List[str] = Field(default_factory=list)


class HLDDataFlow(Artifact):
    TEMPLATE: ClassVar[str] = "HLD/1"
    SECTION: ClassVar[str] = "Data flow"
    data_flows: List[DataFlow] = Field(description="every flow the pages need, including each form")
    assumptions: List[str] = Field(default_factory=list)


class HLDHosting(Artifact):
    TEMPLATE: ClassVar[str] = "HLD/1"
    SECTION: ClassVar[str] = "Hosting and deployment"
    hosting: Hosting
    assumptions: List[str] = Field(default_factory=list)


class HLDRisks(Artifact):
    TEMPLATE: ClassVar[str] = "HLD/1"
    SECTION: ClassVar[str] = "Risks"
    risks: List[Risk] = Field(description="each risk with its mitigation")
    assumptions: List[str] = Field(default_factory=list)


class HLD(Artifact):
    TEMPLATE: ClassVar[str] = "HLD/1"
    purpose: str = ""
    pages: List[Page] = Field(default_factory=list)
    components: List[Component] = Field(default_factory=list)
    data_flows: List[DataFlow] = Field(default_factory=list)
    hosting: Optional[Hosting] = None
    risks: List[Risk] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- LLD/1
class LLDSection(Artifact):
    id: str = Field(description="S1, S2, ... in order")
    anchor: str = Field(description="the id attribute on the page, with the #, e.g. \"#classes\"")
    page: str = Field(default="", description="the page id, e.g. \"P1\"")
    implements: List[str] = Field(default_factory=list, description="the HLD component ids this section implements")


class Element(Artifact):
    id: str = Field(description="E1, E2, ... in order")
    section: str = Field(description="the section id it sits in, e.g. \"S1\"")
    selector: str = Field(description="its selector, e.g. \"#book-now\"")
    trigger: str = Field(description="what the visitor does, e.g. \"click\"")
    behaviour: str = Field(description="what happens then")


class FormField(Artifact):
    id: str = Field(description="F1, F2, ... in order")
    form: str = Field(description="the form's selector, e.g. \"#booking\"")
    name: str = Field(description="the field name attribute")
    type: Literal["text", "email", "tel", "url", "number", "date", "time", "select", "textarea", "checkbox",
                  "radio", "password", "file"] = Field(description="one of " + ", ".join(FIELD_TYPES))
    required: bool = Field(description="true when the visitor must fill it in")
    section: str = Field(default="", description="the section id the form sits in, e.g. \"S1\"")
    validation: str = Field(default="", description="the validation rule in one line")


class FileEntry(Artifact):
    path: str = Field(description="the file path, e.g. \"index.html\"")
    purpose: str = Field(description="what it holds")


class LLDSections(Artifact):
    TEMPLATE: ClassVar[str] = "LLD/1"
    SECTION: ClassVar[str] = "Pages and sections"
    sections: List[LLDSection] = Field(description="the page sections, S1, S2, ... in order, each with its anchor and "
                                                   "the HLD components it implements")
    assumptions: List[str] = Field(default_factory=list)


class LLDElements(Artifact):
    TEMPLATE: ClassVar[str] = "LLD/1"
    SECTION: ClassVar[str] = "Interactive elements"
    elements: List[Element] = Field(description="every interactive element, E1, E2, ... in order")
    assumptions: List[str] = Field(default_factory=list)


class LLDFormFields(Artifact):
    TEMPLATE: ClassVar[str] = "LLD/1"
    SECTION: ClassVar[str] = "Form fields"
    form_fields: List[FormField] = Field(description="every form field, F1, F2, ... in order")
    assumptions: List[str] = Field(default_factory=list)


class LLDFiles(Artifact):
    TEMPLATE: ClassVar[str] = "LLD/1"
    SECTION: ClassVar[str] = "File structure"
    files: List[FileEntry] = Field(description="every file of the build")
    assumptions: List[str] = Field(default_factory=list)


class LLDRules(Artifact):
    TEMPLATE: ClassVar[str] = "LLD/1"
    SECTION: ClassVar[str] = "Responsive and accessibility rules"
    responsive_rules: List[str] = Field(default_factory=list, description="one rule per line")
    accessibility_rules: List[str] = Field(default_factory=list, description="one rule per line")
    assumptions: List[str] = Field(default_factory=list)


class LLD(Artifact):
    TEMPLATE: ClassVar[str] = "LLD/1"
    sections: List[LLDSection] = Field(default_factory=list)
    elements: List[Element] = Field(default_factory=list)
    form_fields: List[FormField] = Field(default_factory=list)
    files: List[FileEntry] = Field(default_factory=list)
    responsive_rules: List[str] = Field(default_factory=list)
    accessibility_rules: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- Design/1 (the style guide, STYLE_FMT as a model)
class Palette(Artifact):
    primary: str
    secondary: str
    accent: str
    background: str
    surface: str
    text: str
    muted: str


class Fonts(Artifact):
    heading: str = Field(description="a css font-family")
    body: str = Field(description="a css font-family")
    google_fonts_url: Optional[str] = Field(default=None, description="a https://fonts.googleapis.com/ url, or null")


class Spacing(Artifact):
    unit: str = Field(description="the base spacing, e.g. \"8px\"")
    section: str = Field(description="the space between sections, e.g. \"64px\"")


class Buttons(Artifact):
    primary: str = Field(description="css declarations for the primary button")
    secondary: str = Field(description="css declarations for the secondary button")


class Design(Artifact):
    TEMPLATE: ClassVar[str] = "Design/1"
    SECTION: ClassVar[str] = "Style guide"
    palette: Palette
    fonts: Fonts
    spacing: Spacing
    radius: str = Field(description="the corner radius, e.g. \"12px\"")
    buttons: Buttons
    card: str = Field(description="css declarations for a card")
    notes: str = Field(default="", description="one line: why this suits the business")


# ---------------------------------------------------------------- WebsiteSection/1
class WebsiteSection(Artifact):
    TEMPLATE: ClassVar[str] = "WebsiteSection/1"
    SECTION: ClassVar[str] = "Section"
    id: str = Field(description="the section id of this workflow, as the task gives it")
    anchor: str = Field(default="", description="the id attribute of the section element, with the #; \"\" when this "
                                                 "workflow writes page-head tags only")
    implements: List[str] = Field(default_factory=list, description="the LLD section ids this builds; empty when the "
                                                                    "run has no LLD")
    html: str = Field(default="", description="the section's HTML only: no <html>, <head> or <body> tags; \"\" when "
                                               "this workflow writes page-head tags only")
    head: str = Field(default="", description="page-head tags this section needs (meta, link, style or script only); "
                                              "\"\" when it needs none")
    selectors_used: List[str] = Field(default_factory=list, description="the ids and classes you used")
    facts_used: List[str] = Field(default_factory=list, description="the charter facts this section shows, copied "
                                                                     "exactly")

    @model_validator(mode="after")
    def _something(self):
        """Shape, not a constraint: a section must carry one of the two fields. Everything else about the markup and
        the anchor is a rule in j2_rules (html_no_page_tags, anchor_selector, anchor_in_html)."""
        if not str(self.html).strip() and not str(self.head).strip():
            raise ValueError("a section must have html, or head tags when it writes only those")
        return self


# ---------------------------------------------------------------- the registry: section -> model
# One model per section a workflow writes, so a builder's schema is only its own part. The names are the section
# names of PRD_SECTIONS / HLD_SECTIONS / LLD_SECTIONS in j2.py, and the drift test fails if they ever disagree.
SECTION_MODELS = {
    "prd": {"Problem": PRDProblem, "Users": PRDUsers, "Goals": PRDGoals, "Requirements": PRDRequirements,
            "Success metrics": PRDSuccessMetrics, "Out of scope": PRDOutOfScope},
    "hld": {"Purpose and scope": HLDPurpose, "Pages": HLDPages, "Components": HLDComponents,
            "Data flow": HLDDataFlow, "Hosting and deployment": HLDHosting, "Risks": HLDRisks},
    "lld": {"Pages and sections": LLDSections, "Interactive elements": LLDElements, "Form fields": LLDFormFields,
            "File structure": LLDFiles, "Responsive and accessibility rules": LLDRules},
    "design": {"Style guide": Design},
    "website": {"Section": WebsiteSection},
}
DOC_MODELS = {"prd": PRD, "hld": HLD, "lld": LLD, "design": Design, "website": WebsiteSection}
# Which condition each section's rules come from, for the records (the conditions themselves stay in conditions/).
SECTION_CONDITIONS = {
    "prd": {"Problem": ["P1"], "Users": ["P1", "P7"], "Goals": ["P1", "P6"], "Requirements": ["P1", "P2"],
            "Success metrics": ["P1", "P6", "P8"], "Out of scope": ["P1"]},
    "hld": {"Purpose and scope": ["H1"], "Pages": ["H1"], "Components": ["H1", "H3", "H4"], "Data flow": ["H1"],
            "Hosting and deployment": ["H1"], "Risks": ["H1"]},
    "lld": {"Pages and sections": ["L1", "L2", "L5"], "Interactive elements": ["L1", "L2", "L3"],
            "Form fields": ["L1", "L2", "L4"], "File structure": ["L1"],
            "Responsive and accessibility rules": ["L1"]},
    "design": {"Style guide": []},
    "website": {"Section": ["N1", "N4", "N8"]},
}


def model_for(kind, section):
    """The model one workflow writes, by output kind and section name (None when there is none)."""
    by = SECTION_MODELS.get(str(kind or ""), {})
    if section in by:
        return by[section]
    want = re.sub(r"[^a-z0-9]+", " ", str(section or "").lower()).strip()
    for name, m in by.items():
        if re.sub(r"[^a-z0-9]+", " ", name.lower()).strip() == want:
            return m
    return next(iter(by.values())) if kind in ("design", "website") else None


# ---------------------------------------------------------------- the transport schema
_STRIP = ("minLength", "maxLength", "minItems", "maxItems", "pattern", "format", "exclusiveMinimum",
          "exclusiveMaximum", "minimum", "maximum", "multipleOf", "default", "title", "examples", "const")


def _clean(node):
    """One schema node as the transport allows it: no length, pattern, format or default, anyOf [X, null] folded into
    a type list, objects closed, and every property required."""
    if not isinstance(node, dict):
        return node
    out = {k: v for k, v in node.items() if k not in _STRIP}
    if "anyOf" in out:      # Optional[X] -> {"type": [x, "null"]}
        parts = [_clean(x) for x in out.pop("anyOf")]
        nullable = any(p.get("type") == "null" for p in parts)
        real = [p for p in parts if p.get("type") != "null"]
        if len(real) == 1 and isinstance(real[0].get("type"), str):
            out.update(real[0])
            out["type"] = [real[0]["type"], "null"] if nullable else real[0]["type"]
        elif real:
            out["anyOf"] = real
    for key in ("properties", "definitions", "$defs"):
        if isinstance(out.get(key), dict):
            out[key] = {k: _clean(v) for k, v in out[key].items()}
    if isinstance(out.get("items"), dict):
        out["items"] = _clean(out["items"])
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
        props = list((out.get("properties") or {}).keys())
        out["required"] = [p for p in props if p not in OPTIONAL_FIELDS] or props
    return out


def transport_schema(model):
    """The draft-07 schema sent to the model: generated from the model, so the two can never drift. Pydantic's $defs
    become definitions (2020-12 is refused by `claude --json-schema`), reason comes first, and nothing the transport
    forbids is left in."""
    raw = json.loads(json.dumps(model.model_json_schema(by_alias=True)).replace("#/$defs/", "#/definitions/"))
    raw.pop("$schema", None)
    if "$defs" in raw:
        raw["definitions"] = raw.pop("$defs")
    out = _clean(copy.deepcopy(raw))
    out = {"$schema": "http://json-schema.org/draft-07/schema#", **out}
    return out


def reply_schema(model, extra_fields, section_schema=None):
    """The whole reply as one object: the fields a builder already returns (reason first), plus "section", its own
    section model. extra_fields is {name: schema} for the optional board and spec fields, as today. section_schema:
    the section's transport schema when it comes from elsewhere (a library template's schema.json)."""
    sec = copy.deepcopy(section_schema) if section_schema is not None else transport_schema(model)
    defs = sec.pop("definitions", None)
    sec.pop("$schema", None)
    props = {"reason": {"type": "string", "description": "one short sentence: why you decided this"},
             "say": {"type": "string", "description": "one short line reporting to @Coordination: what you changed; "
                                                      "code runs your checks and reports them, so don't claim they "
                                                      "pass"},
             "human_output": {"type": "string", "description": "1 to 3 plain sentences telling a person what you "
                                                               "built"},
             "atom_human_output": {"type": "string", "description": "1 or 2 plain sentences telling the Requester "
                                                                    "what this part created, in everyday words"},
             "next": {"type": "string", "description": "Coordination"},
             "section": sec}
    props.update(extra_fields or {})
    out = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
           "properties": props,
           "required": ["reason", "say", "human_output", "atom_human_output", "next", "section"]}
    if defs:
        out["definitions"] = defs
    return out


def schema_sha(schema):
    return hashlib.sha256(json.dumps(schema, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def schema_name(model):
    return model.template()


def validate(model, data):
    """(object or None, [error lines]) for one section's data, with the full rules. The errors are Pydantic's own
    words, so a retry can quote them."""
    try:
        return model.model_validate(data), []
    except Exception as e:
        return None, errors_of(e)


def errors_of(e):
    out = []
    for err in getattr(e, "errors", lambda: [])() or []:
        where = ".".join(str(x) for x in err.get("loc") or ()) or "section"
        out.append(f"{where}: {err.get('msg')}")
    return out or [str(e).splitlines()[0]]


def normalise(model, data):
    """Enum values read case-insensitively and written back in the model's own casing, before validation."""
    if not isinstance(data, dict):
        return data
    d = copy.deepcopy(data)
    enums = {"priority": PRIORITIES, "type": FIELD_TYPES}

    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for k, v in list(node.items()):
                if k in enums and isinstance(v, str):
                    low = v.strip().lower()
                    node[k] = next((x for x in enums[k] if x.lower() == low), v)
                else:
                    walk(v)
    walk(d)
    return d


# ---------------------------------------------------------------- rendering: code writes the document, not the agent
# Each renderer writes the markdown the existing readers already parse (parse_hld, parse_lld, md_ids) and the
# conditions already check (P1-P8 / H1-H6 / L1-L6). The agent sends data; no agent writes a heading.
NO_ACTIONS = "have no actions in this version"


def _lines(items, fmt):
    return "\n".join(fmt(i, x) for i, x in enumerate(items, 1))


def _assumptions(data):
    return "".join(f"\nAssumption: {a}" for a in (data.get("assumptions") or []))


def render_section(kind, section, data):
    """The markdown of one section, from its validated data: "## <Section>" and the body, in the shape the readers
    expect. Returns None when nothing here renders that section."""
    d = dict(data or {})
    body = None
    if kind == "prd":
        if section == "Problem":
            body = str(d.get("statement") or "")
        elif section == "Users":
            rows, idle = [], []
            for u in d.get("users") or []:
                acts = ", ".join(u.get("actions") or [])
                rows.append(f"- {u.get('group')}: {u.get('needs') or 'uses the page'}"
                            + (f"; they {acts}." if acts else "."))
                if not (u.get("actions") or []):
                    name = str(u.get("group") or "")
                    idle.append(f"{name[:1].upper() + name[1:]} {NO_ACTIONS}.")
            body = "\n".join(rows) + ("\n\n" + " ".join(idle) if idle else "")
        elif section == "Goals":
            body = _lines(d.get("goals") or [], lambda i, g: f"- **{g['id']}**: {g['statement']}")
        elif section == "Requirements":
            body = _lines(d.get("requirements") or [], lambda i, r: f"{i}. **{r['id']}**: "
                          + str(r["statement"]).rstrip(".") + f" ({r.get('priority', 'must')})."
                          + (f" Serves {', '.join(r.get('goals') or [])}." if r.get("goals") else ""))
        elif section == "Success metrics":
            rows = d.get("success_metrics") or []
            body = ("| Goal | Metric | Target | Window |\n|---|---|---|---|\n"
                    + "\n".join(f"| {m.get('goal')} | {m.get('metric')} | {m.get('target') or 'not set'} | "
                                f"{m.get('window') or 'measurement window not set'} |" for m in rows))
        elif section == "Out of scope":
            body = "\n".join(f"- {x}" for x in d.get("out_of_scope") or [])
    elif kind == "hld":
        if section == "Purpose and scope":
            body = str(d.get("purpose") or "")
        elif section == "Pages":
            body = _lines(d.get("pages") or [], lambda i, p: f"- **{p['id']}** {p['name']}: "
                          + str(p["purpose"]).rstrip(".") + "."
                          + (f" Implements {', '.join(p.get('implements') or [])}." if p.get("implements") else ""))
        elif section == "Components":
            body = _lines(d.get("components") or [], lambda i, c: f"- **{c['id']}** {c['name']}: "
                          + str(c["responsibility"]).rstrip(".") + "."
                          + (f" Covers {', '.join(c.get('covers') or [])}." if c.get("covers") else "")
                          + (f" On {c['page']}." if c.get("page") else ""))
        elif section == "Data flow":
            body = "\n".join(f"- {f.get('from') or f.get('from_')} to {f['to']}: {f['data']}, on {f['trigger']}."
                             for f in d.get("data_flows") or [])
        elif section == "Hosting and deployment":
            h = d.get("hosting") or {}
            body = f"{h.get('kind') or ''}" + (f" {h.get('notes')}" if h.get("notes") else "")
        elif section == "Risks":
            body = "\n".join(f"- {str(r['risk']).rstrip('.')}. Mitigation: {r['mitigation']}"
                             for r in d.get("risks") or [])
    elif kind == "lld":
        if section == "Pages and sections":
            body = _lines(d.get("sections") or [], lambda i, s: f"- **{s['id']}** `{s['anchor']}`"
                          + (f" (page `{s['page']}`)" if s.get("page") else "") + ": shows "
                          + (", ".join(s.get("implements") or []) or "this part of the page") + "."
                          + (f" Implements {', '.join(s.get('implements') or [])}." if s.get("implements") else ""))
        elif section == "Interactive elements":
            body = _lines(d.get("elements") or [], lambda i, e: f"- **{e['id']}** in {e['section']}: `{e['selector']}`"
                          f" trigger {e['trigger']}; behaviour {e['behaviour']}")
        elif section == "Form fields":
            body = _lines(d.get("form_fields") or [],
                          lambda i, f: f"- **{f['id']}** in {f.get('section') or 'S1'}, form `{f['form']}`: field "
                          f"`{f['name']}`, type {f['type']}, required {'yes' if f.get('required') else 'no'}"
                          + (f", validation {f['validation']}" if f.get("validation") else ""))
        elif section == "File structure":
            body = "\n".join(f"- `{x['path']}`: {x['purpose']}" for x in d.get("files") or [])
        elif section == "Responsive and accessibility rules":
            body = "\n".join([f"- {x}" for x in d.get("responsive_rules") or []]
                             + [f"- {x}" for x in d.get("accessibility_rules") or []])
    if body is None:
        return None
    return f"## {section}\n\n{body.strip()}{_assumptions(d)}\n"


def style_from_design(data):
    """The design data as the style guide the rest of the code already uses (style_css, style.json): the same keys
    STYLE_FMT has, so nothing downstream changes."""
    d = dict(data or {})
    fonts = dict(d.get("fonts") or {})
    return {"palette": dict(d.get("palette") or {}),
            "fonts": {"heading": fonts.get("heading"), "body": fonts.get("body"),
                      "google_fonts_url": fonts.get("google_fonts_url")},
            "spacing": dict(d.get("spacing") or {}), "radius": d.get("radius"),
            "buttons": dict(d.get("buttons") or {}), "card": d.get("card"), "notes": d.get("notes") or ""}


# ---------------------------------------------------------------- the rules layer (code, every attempt)
# The rules themselves are data in j2_rules; these are here so the callers keep one import.
RULE_NAMES = dict(j2_rules.RULE_NAMES)
rule_names = j2_rules.rule_names
rules_count = j2_rules.rules_count
run_rules = j2_rules.run_rules
