"""Claude Code (subscription) provider — spawns the logged-in ``claude`` CLI.

Routed via the ``#`` sigil. Unlike :class:`AnthropicProvider` (the Messages API,
billed per-token against ``ANTHROPIC_API_KEY``), this runs the user's **Claude
subscription** by spawning ``claude --print`` as a subprocess. The CLI authenticates
with the account's stored OAuth credentials in ``~/.claude``.

**Linchpin:** the child env has the Anthropic API-key variables *stripped*, so Claude
Code uses the subscription, not a key (``engine/.env`` sets ``ANTHROPIC_API_KEY``,
which the engine process would otherwise pass through — and Claude Code prefers a key
when present, billing the API instead of the subscription).

Phase 19a (this module): **single-shot text** — one turn, mutating tools disallowed,
the default agent system prompt *replaced* with our concise assistant prompt (leaner
quota, plain-assistant behaviour). Streams Claude Code's ``stream-json`` events,
mapped to :class:`ChatChunk` text deltas, so it drops straight into ``_sse_stream``.

The process spawn is injectable (``spawn=``) so tests feed canned ``stream-json``
without launching a real ``claude`` — mirroring how :class:`AnthropicProvider` accepts
an injected ``httpx`` client.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from .base import ChatChunk, Provider

_EGRESS_LOG = Path(__file__).resolve().parent.parent.parent / ".egress.log"

# Callback set by main.py to record usage into the analytics store.
# Signature: (feature, provider, model, in_tokens, out_tokens)
_usage_callback: Callable[[str, str, str, int, int], None] | None = None


def set_usage_callback(cb: Callable[[str, str, str, int, int], None]) -> None:
    global _usage_callback
    _usage_callback = cb


def clear_usage_callback() -> None:
    global _usage_callback
    _usage_callback = None


def _log_egress(
    model: str,
    action: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    feature: str = "system",
) -> None:
    """Append one line to the egress audit log; fire usage callback on chat_done."""
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        line = (
            f"{ts} provider=claude-cli model={model} action={action} "
            f"in={input_tokens} out={output_tokens}\n"
        )
        with _EGRESS_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    if action == "chat_done" and _usage_callback is not None:
        try:
            _usage_callback(feature, "claude-cli", model, input_tokens, output_tokens)
        except Exception:
            pass


# Env vars that would make Claude Code bill the API key instead of the subscription.
_API_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")

# Catalog model IDs → Claude Code `--model` aliases (resilient to ID churn).
_MODEL_ALIASES = {
    "claude-opus-4-8": "opus",
    "claude-sonnet-4-6": "sonnet",
    "claude-haiku-4-5-20251001": "haiku",
}

# Mutating tools blocked in single-shot text mode (Phase 19a). Read-only tools are
# harmless and won't fire anyway with --max-turns 1 + the replaced system prompt.
_DISALLOWED_TOOLS_TEXT = ("Edit", "Write", "Bash", "NotebookEdit")


def subscription_env() -> dict[str, str]:
    """Parent env minus the Anthropic API-key vars → forces subscription auth."""
    return {k: v for k, v in os.environ.items() if k not in _API_ENV_VARS}


def find_claude(explicit: str | None = None) -> list[str]:
    """Resolve the argv prefix to launch ``claude``.

    Precedence: explicit config path → ``PATH`` → the standalone native install
    (``~/.local/bin``) → npm-global shim. Returns a list so a ``.cmd`` shim can be
    wrapped in ``cmd /c`` (``create_subprocess_exec`` can't run ``.cmd`` directly).
    Falls back to the bare name (hope it's on PATH at spawn time).
    """
    home = Path.home()
    appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    which = shutil.which("claude")
    if which:
        candidates.append(which)
    candidates += [
        str(home / ".local" / "bin" / "claude.exe"),   # native installer (Windows)
        str(home / ".local" / "bin" / "claude"),        # native installer (Unix)
        str(Path(appdata) / "npm" / "claude.cmd"),      # npm global (Windows)
    ]
    for c in candidates:
        if c and Path(c).exists():
            return ["cmd", "/c", c] if c.lower().endswith(".cmd") else [c]
    return ["claude"]


def _split_messages(messages: list[dict]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt). System turns are joined for
    ``--system-prompt``; remaining turns are flattened (role-prefixed when more
    than one) into the single prompt written to the CLI's stdin."""
    system_parts: list[str] = []
    convo: list[tuple[str, str]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if not isinstance(content, str):
            # Vision/array content isn't supported by the single-shot text path.
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        if role == "system":
            system_parts.append(content)
        else:
            convo.append((role, content))
    system = "\n\n".join(p for p in system_parts if p)
    if len(convo) == 1:
        user = convo[0][1]
    else:
        user = "\n\n".join(f"{r.upper()}: {c}" for r, c in convo)
    return system, user


# A spawned process needs: async-iterable .stdout (bytes lines), awaitable
# .stderr.read(), awaitable .wait() -> int, .returncode, .kill().
SpawnFn = Callable[[list[str], dict[str, str], bytes], Awaitable["asyncio.subprocess.Process"]]


async def _default_spawn(argv: list[str], env: dict[str, str], stdin_data: bytes):
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    if proc.stdin is not None:
        try:
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
    return proc


class ClaudeAgentProvider(Provider):
    """Spawns the subscription ``claude`` CLI; streams its reply as ChatChunks."""

    kind = "agent"  # off-machine but NOT the API-key path; gated like cloud (see router)

    def __init__(
        self,
        name: str = "claude-cli",
        claude_path: str | None = None,
        spawn: SpawnFn | None = None,
        max_turns: int = 1,
    ):
        self.name = name
        self._argv = find_claude(claude_path)
        self._spawn = spawn or _default_spawn
        self.max_turns = max_turns

    def _build_args(self, model: str, system: str) -> list[str]:
        alias = _MODEL_ALIASES.get(model, model)
        args = [
            *self._argv,
            "--print",
            "--input-format", "text",            # prompt arrives on stdin
            "--output-format", "stream-json",
            "--include-partial-messages",        # incremental text_delta events
            "--verbose",                         # required for stream-json + --print
            "--model", alias,
            "--max-turns", str(self.max_turns),
        ]
        if system:
            # Replace (not append) the default agent prompt → lean quota, plain assistant.
            args += ["--system-prompt", system]
        # Block mutating tools, then a flag follows so the variadic list terminates.
        args += ["--disallowed-tools", *_DISALLOWED_TOOLS_TEXT]
        return args

    async def chat(self, model: str, messages: list[dict], **params) -> AsyncIterator[ChatChunk]:
        feature = params.pop("_feature", "system")
        system, user = _split_messages(messages)
        args = self._build_args(model, system)
        env = subscription_env()

        _log_egress(model, "chat_start", feature=feature)
        proc = await self._spawn(args, env, user.encode("utf-8"))

        emitted = False
        fallback_text = ""
        in_tokens = 0
        out_tokens = 0
        error_msg: str | None = None
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, TypeError):
                    continue
                etype = ev.get("type")
                if etype == "stream_event":
                    inner = ev.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                emitted = True
                                yield ChatChunk(text=text)
                elif etype == "assistant" and not emitted:
                    # No partial deltas seen — capture the whole assistant message.
                    for block in ev.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            fallback_text += block.get("text", "")
                elif etype == "result":
                    usage = ev.get("usage", {})
                    in_tokens = usage.get("input_tokens", 0) or 0
                    out_tokens = usage.get("output_tokens", out_tokens) or out_tokens
                    if ev.get("is_error"):
                        error_msg = ev.get("result") or "claude returned an error"
                    elif not emitted and not fallback_text:
                        fallback_text = ev.get("result", "") or ""

            rc = await proc.wait()
            if error_msg:
                raise RuntimeError(_friendly(error_msg))
            if not emitted:
                if fallback_text:
                    yield ChatChunk(text=fallback_text)
                elif rc != 0:
                    stderr = b""
                    if proc.stderr is not None:
                        try:
                            stderr = await proc.stderr.read()
                        except Exception:
                            stderr = b""
                    msg = stderr.decode("utf-8", "replace").strip() or f"claude exited with code {rc}"
                    raise RuntimeError(_friendly(msg))
            yield ChatChunk(text="", done=True)
        finally:
            _log_egress(model, "chat_done", in_tokens, out_tokens, feature=feature)
            if proc.returncode is None:
                try:
                    proc.kill()
                except (ProcessLookupError, Exception):
                    pass


def _friendly(msg: str) -> str:
    """Turn the most common failure into an actionable hint."""
    if "Not logged in" in msg or "authentication_failed" in msg or "/login" in msg:
        return (
            "Claude CLI is not logged in. Run `claude` in a terminal, `/login` with "
            "your subscription, then retry the # command."
        )
    return f"claude: {msg}"
