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
MOCK = os.getenv("STUDIO_MOCK") == "1" or PROVIDER is None
MOCK_DELAY = float(os.getenv("STUDIO_MOCK_DELAY", "0"))  # seconds per mock reply, to try the progress UI
# Optional Gemini thinking cap for short JSON replies (routing, spec, review). Off by default: a 512 cap
# coincided with replies cut off mid-JSON on 2026-09-29. Set GEMINI_LOW_THINKING=512 to try it again.
LOW_THINKING_BUDGET = int(os.getenv("GEMINI_LOW_THINKING", "0")) or None
LAST_META = {}  # model, finish reason and token counts of the latest Gemini reply, saved with failed replies
_client = None


def ask(system, user, mock, max_tokens=1500, effort="high", on_progress=None, json_mode=False, images=None,
        schema=None):
    """effort="low" caps Gemini thinking; use it for short structured replies.
    json_mode=True makes Gemini return a JSON object only (Claude follows the prompt's format).
    images: PNG paths sent with the prompt (Audit's screenshots); every provider takes them, mock ignores them.
    schema: a JSON Schema the reply must follow (J2_ARTIFACT_SCHEMA=1). claude-cli sends it with --json-schema and
    reads structured_output; the Anthropic API uses output_config's json_format; Gemini gets response_schema when
    the schema is simple enough, else the schema in the prompt and code validates it. The reply is still returned as
    the JSON text, so nothing downstream changes. LAST_META["structured"] records what the provider did."""
    images = [p for p in images or [] if p and os.path.exists(p)]
    progress = on_progress or (lambda e: None)
    LAST_META.clear()   # each provider fills in what it reports (tokens included); mock reports nothing
    if MOCK:
        return _stream_mock(mock(), progress)
    if PROVIDER == "gemini":
        return _ask_gemini(system, user, max_tokens, effort, progress, json_mode, images, schema)
    if PROVIDER == "claude-cli":
        return _ask_claude_cli(system, user, effort, progress, images, schema)
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    text = ""
    extra = {"output_config": {"format": {"type": "json_schema", "schema": schema}}} if schema else {}
    with _client.messages.stream(model=MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": _blocks(user, images)}], **extra) as stream:
        for piece in stream.text_stream:
            text += piece
            progress({"chars": len(text), "text": text})
        usage = stream.get_final_message().usage
    LAST_META.update(model=MODEL, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
    if schema:
        LAST_META["structured"] = {"provider": "anthropic", "subtype": "success", "present": bool(text.strip())}
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


def _ask_claude_cli(system, user, effort, progress, images=None, schema=None):
    """One non-interactive `claude -p` call with no tools, MCP, skills or settings: a plain completion.
    The CLI has no max-tokens flag, so the reply format in the prompt is what keeps replies short.
    With images the prompt goes in as one stream-json user message (image blocks + text) and the result line is read
    from the stream-json output."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}
    io = (["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"] if images
          else ["--output-format", "json"])
    # A long system prompt goes in a temporary file: Windows refuses a command line over 32,767 characters (WinError 206)
    sysfile = None
    if len(system) > 20000:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(system)
            sysfile = f.name
    cmd = ["claude", "-p", *io, *(["--system-prompt-file", sysfile] if sysfile else ["--system-prompt", system]),
           "--tools", "", "--model", MODEL,
           "--effort", "low" if effort == "low" else "high", "--no-session-persistence", "--strict-mcp-config",
           "--disable-slash-commands", "--setting-sources", ""]
    if schema:      # structured output: Claude Code validates the schema, then returns the object in structured_output
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    try:
        return _run_claude_cli(cmd, images, user, env, progress, schema)
    finally:
        if sysfile:
            try:
                os.remove(sysfile)
            except OSError:
                pass


def _cli_meta(d):
    """What `claude -p` reports about one call, kept with it (the structured-output verdict is added by the caller)."""
    keep = LAST_META.get("structured")
    LAST_META.clear()
    u = d.get("usage") or {}
    LAST_META.update(model=next(iter(d.get("modelUsage") or {}), MODEL), duration_ms=d.get("duration_ms"),
                     input_tokens=(u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                     + (u.get("cache_creation_input_tokens") or 0) if u else None,
                     output_tokens=u.get("output_tokens"))
    if keep:
        LAST_META["structured"] = keep


def _run_claude_cli(cmd, images, user, env, progress, schema=None):
    stdin = (json.dumps({"type": "user", "message": {"role": "user", "content": _blocks(user, images)}}) + "\n"
             if images else user)
    last = None
    for attempt in range(2):
        try:
            p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env, timeout=900,
                               cwd=tempfile.gettempdir())
            if images:   # stream-json: one JSON event per line; the reply is the "result" event
                lines = [json.loads(x) for x in (p.stdout or "").splitlines() if x.strip().startswith("{")]
                d = next((x for x in reversed(lines) if x.get("type") == "result"), {})
            else:
                d = json.loads(p.stdout or "{}")
            sub = d.get("subtype")
            if schema:
                so = d.get("structured_output")
                ok = p.returncode == 0 and sub == "success" and not d.get("is_error") and so is not None
                LAST_META["structured"] = {"provider": "claude-cli", "subtype": sub, "present": so is not None}
                if not ok:
                    why = (f"subtype {sub!r}" if sub != "success" else "no structured_output in the reply")
                    last = RuntimeError(f"claude -p structured output failed: {why}")
                    progress({"note": f"{last}; retrying" if attempt == 0 else str(last)})
                    continue
                text = json.dumps(so, ensure_ascii=False)
                _cli_meta(d)
                progress({"chars": len(text), "text": text})
                return text
            if p.returncode == 0 and not d.get("is_error") and (d.get("result") or "").strip():
                text = d["result"].strip()
                _cli_meta(d)
                progress({"chars": len(text), "text": text})
                return text
            last = RuntimeError(f"claude -p failed (exit {p.returncode}): {(d.get('result') or p.stderr)[:300]}")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            last = RuntimeError(f"claude -p failed: {type(e).__name__}")
        progress({"note": f"{last}; retrying" if attempt == 0 else str(last)})
    raise last


def _stream_mock(text, progress):
    steps = 30 if MOCK_DELAY else 1
    for i in range(1, steps + 1):
        part = text[:len(text) * i // steps]
        progress({"chars": len(part), "text": part})
        if MOCK_DELAY:
            time.sleep(MOCK_DELAY / steps)
    return text


def _simple_schema(schema):
    """True when a schema has no $ref, no definitions and no type lists: Gemini's response_schema takes those only."""
    t = json.dumps(schema or {})
    return "$ref" not in t and "definitions" not in t and '"type": [' not in t


def _ask_gemini(system, user, max_tokens, effort, progress, json_mode=False, images=None, schema=None):
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
                LAST_META.clear()
                LAST_META.update(model=model, finish=finish, thinking_budget=LOW_THINKING_BUDGET if thinking else None,
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
