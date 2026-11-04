"""Usage estimates from history (step 1 of j2-logic-fixes-plan.md): how many tokens similar work used before.

A run's budget is measured Claude usage in tokens (input, cache included, plus output). This module reads the past
runs' calls.jsonl and workflows.json and keeps a small table: the median tokens per kind of work (the "parts" the
planner names for each workflow: page_section, form, doc_section, fix, ...), and how much the managers used for each
token the builders used. Until there is enough history the plain defaults below apply. Nothing here is a keyword
guess: the kind of a workflow is what the planner declared.
"""
import json
import os
import statistics
import threading

# Plain defaults, used until history has at least MIN_SAMPLES workflows of a kind. One place, so they are easy to tune.
DEFAULT_TOKENS = {"page_section": 60_000, "form": 80_000, "interactive_feature": 70_000, "styling": 30_000,
                  "profiles": 60_000, "blog_post": 50_000, "extra_language": 70_000, "fix": 40_000,
                  "doc_section": 40_000, "requirements_section": 80_000, "artifact": 30_000,
                  "design": 150_000}     # step 11: the design research call (bounded) plus the three style directions
DEFAULT_KIND = "page_section"          # a workflow that names no kind of work
MANAGER_RATIO = 2.0                    # manager tokens per builder token, until history says otherwise
PLANNING_TOKENS = 150_000              # intake and the first plan, before any workflow runs
MIN_SAMPLES = 3                        # workflows of one kind before history replaces the default
SITE_ESSENTIALS = ("styling", "page_section", "page_section", "page_section", "form")   # a website's least work
STAGE_SECTIONS = {"prd": 6, "hld": 6, "lld": 6}      # sections per document (one requirements-like section each)


def tokens(meta):
    """Usage of one call in tokens: input (cache reads and writes included) plus output."""
    m = meta or {}
    return int(m.get("input_tokens") or 0) + int(m.get("output_tokens") or 0)


def call_tokens(row):
    """Usage of one calls.jsonl row, new shape ("usage") or old ("tokens": {input, output})."""
    u = row.get("usage") or {}
    if u.get("total") is not None:
        return int(u["total"])
    t = row.get("tokens") or {}
    return int(t.get("input") or 0) + int(t.get("output") or 0)


_CACHE, _LOCK = {}, threading.Lock()


def _jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def history(runs_dir):
    """{"kinds": {kind: [tokens per part]}, "ratios": [manager/builder tokens per run], "runs": n} from every past run
    folder with measured tokens. Mock runs are skipped (their numbers are a fake meter). Cached per folder listing."""
    try:
        names = sorted(n for n in os.listdir(runs_dir) if n.startswith("j2-"))
    except OSError:
        names = []
    key = (runs_dir, len(names), names[-1] if names else None)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    kinds, ratios, n = {}, [], 0
    for name in names:
        d = os.path.join(runs_dir, name)
        calls = _jsonl(os.path.join(d, "calls.jsonl"))
        head = (_jsonl(os.path.join(d, "chat.jsonl"))[:1] or [{}])[0]
        if not calls or head.get("mock"):
            continue
        by_fn = {}
        for c in calls:
            by_fn[c.get("fn")] = by_fn.get(c.get("fn"), 0) + call_tokens(c)
        if not any(by_fn.values()):
            continue
        n += 1
        try:
            with open(os.path.join(d, "workflows.json"), encoding="utf-8") as f:
                wfs = json.load(f)
        except (OSError, ValueError):
            wfs = []
        built = 0
        for w in wfs if isinstance(wfs, list) else []:
            used = by_fn.get(w.get("id"), 0)
            parts = [str(p) for p in w.get("parts") or []] or [DEFAULT_KIND]
            if used <= 0 or w.get("status") != "done":
                continue
            built += used
            for p in parts:
                kinds.setdefault(p, []).append(used / len(parts))
        managers = sum(v for k, v in by_fn.items() if not str(k).startswith("W-"))
        if built > 0:
            ratios.append(managers / built)
    out = {"kinds": kinds, "ratios": ratios, "runs": n}
    with _LOCK:
        _CACHE[key] = out
    return out


def table(runs_dir):
    """{kind: median tokens per part} (history where it has MIN_SAMPLES, else the default), and the manager ratio."""
    h = history(runs_dir)
    t = dict(DEFAULT_TOKENS)
    for k, xs in h["kinds"].items():
        if len(xs) >= MIN_SAMPLES:
            t[k] = int(statistics.median(xs))
    ratio = statistics.median(h["ratios"]) if len(h["ratios"]) >= MIN_SAMPLES else MANAGER_RATIO
    return t, ratio


def part_tokens(kind, runs_dir):
    t, _ = table(runs_dir)
    return t.get(str(kind), t[DEFAULT_KIND])


def workflow_tokens(w, runs_dir):
    """What similar work usually used: the median for each kind of work the workflow names (parts), summed."""
    parts = [str(p) for p in (w or {}).get("parts") or []] or [DEFAULT_KIND]
    t, _ = table(runs_dir)
    return sum(t.get(p, t[DEFAULT_KIND]) for p in parts)


def run_tokens(builder_tokens, runs_dir, planning=True):
    """A whole run: the builders' tokens, the managers' share on top (history's ratio), plus intake and planning."""
    _, ratio = table(runs_dir)
    return int(builder_tokens * (1 + ratio) + (PLANNING_TOKENS if planning else 0))


def stage_tokens(kind, runs_dir, sections=None):
    """The least a stage (a document or the website) usually uses, managers included. sections: the document's
    section count (one of them requirements-like)."""
    t, _ = table(runs_dir)
    if kind == "website":
        b = sum(t[p] for p in SITE_ESSENTIALS)
    elif kind in STAGE_SECTIONS:
        n = sections or STAGE_SECTIONS[kind]
        b = t["doc_section"] * (n - 1) + t["requirements_section"]
    else:
        return 0          # a send deed: code only, no model call
    return run_tokens(b, runs_dir, planning=False)


def short(n):
    """A token count in plain words: 2.1M, 340k, 900."""
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{round(n / 1000)}k"
    return str(n)
