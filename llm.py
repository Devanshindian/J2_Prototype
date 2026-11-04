"""LLM wrapper: Claude or Gemini, with an offline mock mode (STUDIO_MOCK=1 or no API key).

Provider pick: STUDIO_PROVIDER=claude-cli uses the local `claude -p` on the Claude subscription (as the Sutra
repo does: ANTHROPIC_API_KEY is removed from its environment so it never bills the API). Otherwise
ANTHROPIC_API_KEY wins if set, else GEMINI_API_KEY, else mock.
Replies are streamed so the UI can show progress; pass on_progress(event) to receive:
  {"chars": int, "text": str}                      as text arrives
  {"note": str}                                    retries and model switches
"""
import base64
import json
import os
import re
import subprocess
import tempfile
import threading
import time



def _load_env_file():
    """Read KEY=value lines from .env next to this file. Variables already set in the shell win."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if value and not os.getenv(key):
                os.environ[key] = value


_load_env_file()

if os.getenv("STUDIO_PROVIDER") == "claude-cli":
    PROVIDER = "claude-cli"
    MODEL = os.getenv("CLAUDE_CLI_MODEL", "sonnet")   # alias; the CLI resolves it to the current Sonnet
elif os.getenv("ANTHROPIC_API_KEY"):
    PROVIDER = "anthropic"
    MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
elif os.getenv("GEMINI_API_KEY"):
    PROVIDER = "gemini"
    # Comma-separated fallback list: if one model is busy or out of quota, the next is tried.
    MODELS = [m.strip() for m in os.getenv("GEMINI_MODEL", "gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite").split(",")
              if m.strip()]
    MODEL = MODELS[0]
else:
    PROVIDER, MODEL = None, None
# Model tiers: the person picks one per run on the plan card (api-contract.md, the proposal's `models`). This is the one
# place for each tier's CLI alias, its plain label and a rough usage multiplier against Sonnet (stronger models think
# and write more). Env: J2_MODEL_<TIER> overrides an alias; J2_DEFAULT_MODEL names the suggested tier (else the tier
# CLAUDE_CLI_MODEL names, else sonnet). The chosen tier runs the builders, the design step, the polish pass and the
# quality / check judges; routine structured manager steps stay on MODEL (the cheap default).
MODEL_TIERS = [
    {"id": "fable", "alias": os.getenv("J2_MODEL_FABLE", "fable"), "label": "Fable · best quality", "multiplier": 1.5},
    {"id": "opus", "alias": os.getenv("J2_MODEL_OPUS", "opus"), "label": "Opus · great", "multiplier": 1.3},
    {"id": "sonnet", "alias": os.getenv("J2_MODEL_SONNET", "sonnet"), "label": "Sonnet · balanced", "multiplier": 1.0},
    {"id": "haiku", "alias": os.getenv("J2_MODEL_HAIKU", "haiku"), "label": "Haiku · fastest, cheapest", "multiplier": 0.8},
]
TIER_IDS = [t["id"] for t in MODEL_TIERS]
DEFAULT_TIER = (os.getenv("J2_DEFAULT_MODEL") or "").lower().strip() or \
    next((t for t in TIER_IDS if t == str(MODEL or "").lower()), "sonnet")
if DEFAULT_TIER not in TIER_IDS:
    DEFAULT_TIER = "sonnet"


def tier(tier_id):
    """The tier record for an id (None when the id is not a tier)."""
    return next((t for t in MODEL_TIERS if t["id"] == str(tier_id or "").lower()), None)


def tier_alias(tier_id):
    """The CLI model alias for a tier id; None (the default MODEL) when no tier is chosen."""
    t = tier(tier_id)
    return t["alias"] if t else None


def model_options(suggested=None):
    """The proposal card's model choice: [{id, label, suggested, multiplier}], one suggested."""
    sug = suggested if tier(suggested) else DEFAULT_TIER
    return [{"id": t["id"], "label": t["label"], "suggested": t["id"] == sug, "multiplier": t["multiplier"]}
            for t in MODEL_TIERS]


MOCK = os.getenv("STUDIO_MOCK") == "1" or PROVIDER is None
MOCK_DELAY = float(os.getenv("STUDIO_MOCK_DELAY", "0"))  # seconds per mock reply, to try the progress UI
# Optional Gemini thinking cap for short JSON replies (routing, spec, review). Off by default: a 512 cap
# coincided with replies cut off mid-JSON on 2026-09-29. Set GEMINI_LOW_THINKING=512 to try it again.
LOW_THINKING_BUDGET = int(os.getenv("GEMINI_LOW_THINKING", "0")) or None
# Usage of the latest reply, per thread (so builders running in parallel never read each other's numbers):
# model, input_tokens (cache included), cache_read_tokens, cache_creation_tokens, output_tokens, thinking_tokens,
# cost_usd (a list-price estimate, not a bill), web_searches, web_fetches, duration_ms. Read it as llm.LAST_META.
_META = threading.local()
_client = None


def meta():
    """This thread's usage record for its latest reply (a plain dict)."""
    if not hasattr(_META, "d"):
        _META.d = {}
    return _META.d


def __getattr__(name):          # llm.LAST_META is this thread's record (module attribute lookup, PEP 562)
    if name == "LAST_META":
        return meta()
    raise AttributeError(name)


def mock_meter(system, user, reply):
    """Mock mode's fake usage meter, so budget logic can be tested offline: about 4 characters per token."""
    return {"model": "mock", "input_tokens": (len(system or "") + len(user or "")) // 4, "cache_read_tokens": 0,
            "cache_creation_tokens": 0, "output_tokens": len(reply or "") // 4, "thinking_tokens": 0,
            "cost_usd": None, "web_searches": 0, "web_fetches": 0, "mock": True}


def cli_meta(d, fallback_model, counted=None):
    """The usage record from one `claude -p` result (json or the stream's result event): every token count, the cost
    estimate, the web tool counts, and the model that did the work. The model is the one named by the --model alias
    when the CLI lists it (a helper model can have more output tokens), else the one with the most output tokens, else
    the alias. counted: {web_searches, web_fetches} tallied from the stream's tool_use blocks; the CLI's own
    server_tool_use counters read 0 for WebSearch / WebFetch (CLI 2.1.281), so the larger of the two is kept."""
    u = d.get("usage") or {}
    mu = d.get("modelUsage") or {}
    alias = str(fallback_model or "").lower()
    named = [k for k in mu if alias and alias in k.lower()]
    model = (max(named, key=lambda k: (mu[k] or {}).get("outputTokens") or 0) if named else
             max(mu, key=lambda k: (mu[k] or {}).get("outputTokens") or 0) if mu else None)
    counted = counted or {}
    stu = u.get("server_tool_use") or {}
    otd = u.get("output_tokens_details") or {}
    inp, cr, cc = (u.get("input_tokens") or 0), (u.get("cache_read_input_tokens") or 0), \
        (u.get("cache_creation_input_tokens") or 0)
    return {"model": model or fallback_model, "duration_ms": d.get("duration_ms"),
            "input_tokens": inp + cr + cc if u else None, "fresh_input_tokens": inp if u else None,
            "cache_read_tokens": cr, "cache_creation_tokens": cc, "output_tokens": u.get("output_tokens"),
            "thinking_tokens": otd.get("thinking_tokens") or 0, "cost_usd": d.get("total_cost_usd"),
            "web_searches": max(stu.get("web_search_requests") or 0, counted.get("web_searches") or 0),
            "web_fetches": max(stu.get("web_fetch_requests") or 0, counted.get("web_fetches") or 0)}


# Tools a call may use (step 7): read-only web and read-only GitHub, for planning and research only. The names are
# the groups a caller asks for; each maps to the CLI tools it needs and the exact allow-list entries (with
# --setting-sources "" no permission prompt can be answered, so every allowed command is listed exactly). Nothing that
# writes is ever allowed.
# No `gh api`: its allow pattern is a prefix match, so `gh api -X DELETE ...` would pass it (verified: a POST reached
# GitHub). `gh repo view` and `gh search` are read-only by nature; file contents come through WebFetch.
TOOL_GROUPS = {"web": {"tools": ["WebSearch", "WebFetch"], "allowed": ["WebSearch", "WebFetch"]},
               "github": {"tools": ["Bash"], "allowed": ["Bash(gh repo view:*)", "Bash(gh search:*)"]}}
TOOL_TIMEOUT = int(os.getenv("J2_TOOL_TIMEOUT", "1800"))   # seconds: a call with tools takes several turns
PLAIN_TIMEOUT = 900


def tool_flags(tools=None, allowed=None):
    """(--tools value, --allowedTools list) for the CLI: tools are group names from TOOL_GROUPS ("web", "github") or
    CLI tool names; allowed, when given, replaces the groups' allow-list. No tools: ("", [])."""
    names, allow = [], []
    for t in tools or []:
        g = TOOL_GROUPS.get(t)
        names += g["tools"] if g else [t]
        allow += g["allowed"] if g else [t]
    allow = list(allowed) if allowed is not None else allow
    return ",".join(dict.fromkeys(names)), list(dict.fromkeys(allow))


def ask(system, user, mock, max_tokens=1500, effort="high", on_progress=None, json_mode=False, images=None,
        tools=None, allowed=None, max_budget_usd=None, tier=None):
    """effort="low" caps Gemini thinking; use it for short structured replies.
    tier: the run's chosen model tier (MODEL_TIERS id) for this call; None runs the default MODEL. Only the Claude CLI
    switches models by tier; the usage record carries `tier` ("default" when none) for every provider and mock.
    json_mode=True makes Gemini return a JSON object only (Claude follows the prompt's format).
    images: PNG paths sent with the prompt (Audit's screenshots); every provider takes them, mock ignores them.
    tools / allowed (claude-cli only): the tool groups the call may use (tool_flags); other providers and mock
    ignore them."""
    images = [p for p in images or [] if p and os.path.exists(p)]
    progress = on_progress or (lambda e: None)
    tier_id = tier if tier_alias(tier) else None
    try:
        return _ask(system, user, mock, max_tokens, effort, progress, json_mode, images, tools, allowed,
                    max_budget_usd, tier_id)
    finally:
        meta()["tier"] = tier_id or "default"


def _ask(system, user, mock, max_tokens, effort, progress, json_mode, images, tools, allowed, max_budget_usd, tier_id):
    meta().clear()   # each provider fills in what it reports (tokens included); mock reports the fake meter
    if MOCK:
        text = _stream_mock(mock(), progress)
        meta().update(mock_meter(system, user, text))
        return text
    if PROVIDER == "gemini":
        return _ask_gemini(system, user, max_tokens, effort, progress, json_mode, images)
    if PROVIDER == "claude-cli":
        return _ask_claude_cli(system, user, effort, progress, images, tools, allowed, max_budget_usd,
                               model=tier_alias(tier_id))
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    text = ""
    with _client.messages.stream(model=MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": _blocks(user, images)}]) as stream:
        for piece in stream.text_stream:
            text += piece
            progress({"chars": len(text), "text": text})
        usage = stream.get_final_message().usage
    meta().update(model=MODEL, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
    return text.strip()


def _blocks(user, images):
    """Anthropic message content: the images first, then the prompt text."""
    if not images:
        return user
    out = []
    for path in images:
        with open(path, "rb") as f:
            out.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                    "data": base64.b64encode(f.read()).decode()}})
    return out + [{"type": "text", "text": user}]


def cli_command(system_arg, io, effort, tools=None, allowed=None, max_budget_usd=None, model=None):
    """The `claude -p` command line. No tools: --tools "" (a plain completion). With tools: --tools with exactly the
    tools asked for and --allowedTools with the exact allow-list (read-only web and gh commands only).
    max_budget_usd: the CLI stops the call at that spend (a bounded research call).
    model: the alias of the run's chosen tier for this call; None runs the default MODEL."""
    names, allow = tool_flags(tools, allowed)
    return ["claude", "-p", *io, *system_arg, "--tools", names, *(["--allowedTools", *allow] if allow else []),
            *(["--max-budget-usd", f"{float(max_budget_usd):.2f}"] if max_budget_usd else []),
            "--model", model or MODEL, "--effort", "low" if effort == "low" else "high", "--no-session-persistence",
            "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", ""]


def _ask_claude_cli(system, user, effort, progress, images=None, tools=None, allowed=None, max_budget_usd=None,
                    model=None):
    """One non-interactive `claude -p` call with no MCP, skills or settings: a plain completion, or (tools) one that
    may use the read-only web and GitHub tools it is given.
    The CLI has no max-tokens flag, so the reply format in the prompt is what keeps replies short.
    With images the prompt goes in as one stream-json user message (image blocks + text) and the result line is read
    from the stream-json output."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}
    # Images need stream-json in and out. Tool calls take the stream out too: its tool_use blocks are how web searches
    # and fetches are counted (the CLI's own counters read 0 for them).
    io = (["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"] if images
          else ["--output-format", "stream-json", "--verbose"] if tools
          else ["--output-format", "json"])
    # A long system prompt goes in a temporary file: Windows refuses a command line over 32,767 characters (WinError 206)
    sysfile = None
    if len(system) > 20000:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(system)
            sysfile = f.name
    cmd = cli_command(["--system-prompt-file", sysfile] if sysfile else ["--system-prompt", system], io, effort,
                      tools, allowed, max_budget_usd, model)
    try:
        return _run_claude_cli(cmd, images, user, env, progress, TOOL_TIMEOUT if tools else PLAIN_TIMEOUT,
                               stream=bool(images or tools), model=model or MODEL)
    finally:
        if sysfile:
            try:
                os.remove(sysfile)
            except OSError:
                pass


def _run_claude_cli(cmd, images, user, env, progress, timeout=PLAIN_TIMEOUT, stream=None, model=None):
    stdin = (json.dumps({"type": "user", "message": {"role": "user", "content": _blocks(user, images)}}) + "\n"
             if images else user)
    stream = bool(images) if stream is None else stream
    last = None
    for attempt in range(2):
        try:
            p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env, timeout=timeout,
                               cwd=tempfile.gettempdir())
            counted = {}
            if stream:   # stream-json: one JSON event per line; the reply is the "result" event
                lines = [json.loads(x) for x in (p.stdout or "").splitlines() if x.strip().startswith("{")]
                d = next((x for x in reversed(lines) if x.get("type") == "result"), {})
                counted = tool_use_counts(lines)
            else:
                d = json.loads(p.stdout or "{}")
            if p.returncode == 0 and not d.get("is_error") and (d.get("result") or "").strip():
                text = d["result"].strip()
                meta().clear()
                meta().update(cli_meta(d, model or MODEL, counted))
                progress({"chars": len(text), "text": text})
                return text
            last = RuntimeError(f"claude -p failed (exit {p.returncode}): {(d.get('result') or p.stderr)[:300]}")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            last = RuntimeError(f"claude -p failed: {type(e).__name__}")
        progress({"note": f"{last}; retrying" if attempt == 0 else str(last)})
    raise last


def tool_use_counts(events):
    """{web_searches, web_fetches}: the WebSearch and WebFetch tool_use blocks in a stream-json transcript."""
    n = {"WebSearch": 0, "WebFetch": 0}
    for e in events:
        if e.get("type") != "assistant":
            continue
        for b in ((e.get("message") or {}).get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in n:
                n[b["name"]] += 1
    return {"web_searches": n["WebSearch"], "web_fetches": n["WebFetch"]}


def _stream_mock(text, progress):
    steps = 30 if MOCK_DELAY else 1
    for i in range(1, steps + 1):
        part = text[:len(text) * i // steps]
        progress({"chars": len(part), "text": part})
        if MOCK_DELAY:
            time.sleep(MOCK_DELAY / steps)
    return text


def _ask_gemini(system, user, max_tokens, effort, progress, json_mode=False, images=None):
    global _client
    from google import genai
    from google.genai import errors, types
    if _client is None:
        _client = genai.Client()  # reads GEMINI_API_KEY
    # Gemini's thinking tokens count against max_output_tokens, so the config adds headroom below.
    thinking = (types.ThinkingConfig(thinking_budget=LOW_THINKING_BUDGET)
                if effort == "low" and LOW_THINKING_BUDGET else None)
    last = None
    # Busy (503) or out of quota (429): switch to the next model at once instead of waiting on the same one.
    # One short pause between rounds; two rounds at most.
    for rnd in range(2):
        for model in MODELS:
            config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens + 8192,
                                                 thinking_config=thinking,
                                                 response_mime_type="application/json" if json_mode else None)
            try:
                text, finish, usage = "", None, None
                contents = user
                if images:
                    contents = [types.Part.from_bytes(data=open(p, "rb").read(), mime_type="image/png") for p in images] \
                        + [user]
                for chunk in _client.models.generate_content_stream(model=model, contents=contents, config=config):
                    text += chunk.text or ""
                    if chunk.candidates and chunk.candidates[0].finish_reason:
                        finish = chunk.candidates[0].finish_reason
                    usage = chunk.usage_metadata or usage
                    progress({"chars": len(text), "text": text})
                finish = getattr(finish, "name", finish)
                meta().clear()
                meta().update(model=model, finish=finish, thinking_budget=LOW_THINKING_BUDGET if thinking else None,
                                 json_mode=json_mode, max_output_tokens=config.max_output_tokens,
                                 input_tokens=getattr(usage, "prompt_token_count", None),
                                 output_tokens=getattr(usage, "candidates_token_count", None),
                                 thinking_tokens=getattr(usage, "thoughts_token_count", None))
                if finish not in (None, "STOP"):  # cut off (MAX_TOKENS), blocked (SAFETY), etc.
                    progress({"note": f"{model} stopped early: {finish}"})
                if not text.strip():
                    raise EmptyReply(f"{model} returned no text (finish reason: {finish})")
                return text.strip()
            except errors.APIError as e:
                if e.code == 400 and thinking is not None and "thinking" in str(e).lower():
                    # This model does not accept a thinking budget; retry without one.
                    progress({"note": f"{model} rejected the thinking budget, retrying without it"})
                    return _ask_gemini(system, user, max_tokens, "high", progress, json_mode, images)
                if e.code not in (404, 429, 500, 503):
                    raise
                last = e
                reason = {404: "not available", 429: "out of quota"}.get(e.code, "busy")
                progress({"note": f"{model} is {reason} ({e.code}), trying the next option"})
        if rnd == 0:
            progress({"note": "All models busy, retrying in 4s"})
            time.sleep(4)
    raise last


class EmptyReply(RuntimeError):
    pass


def extract_json(text):
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        return json.loads(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start == -1:
        raise ValueError("no JSON object in reply")
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        # A reply cut short or missing its last brace (runs/j2-20261013-185235: the whole proposal became a 400-char
        # "say"): close the open string and brackets and try once more; still bad -> the caller's fallback.
        return json.loads(close_json(text[start:]))


def close_json(s):
    """s with its unclosed string and brackets closed, in order."""
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            esc, in_str = (not esc and ch == "\\"), in_str and not (ch == '"' and not esc)
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return s.rstrip().rstrip(",") + ('"' if in_str else "") + "".join(reversed(stack))


def extract_html(text):
    m = re.search(r"```html\s*(.*?)```", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    i = text.lower().find("<!doctype")
    if i == -1:
        i = text.lower().find("<html")
    if i == -1:
        raise ValueError("no HTML in reply")
    return text[i:].strip()


def partial_html(text):
    """HTML written so far in a streaming reply (for the live preview), or '' if none yet."""
    low = text.lower()
    i = low.find("<!doctype")
    if i == -1:
        i = low.find("<html")
    if i == -1:
        return ""
    html = text[i:]
    end = html.find("```")
    return html[:end] if end != -1 else html
