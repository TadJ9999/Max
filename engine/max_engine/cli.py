"""Max command-line client.

A thin terminal client over the same engine the desktop app, VS Code extension,
and Neovim plugin use. Local by default; cloud only when you ask (``!`` / ``%``).

Installed as the ``max`` console script (see ``[project.scripts]`` in
``pyproject.toml``). Talks to the engine purely over HTTP, so it works against a
local engine or a remote one (set ``MAX_ENGINE_URL`` or pass ``--engine``).

Subcommands::

    max "!. write a fizzbuzz ."     # one-shot: DSL command or plain chat
    max run ". add a docstring ."   # explicit DSL command
    max chat                        # interactive REPL (multi-turn memory)
    max                             # no args → REPL
    max health                      # engine health + active model + cloud state
    max sessions                    # list delegate sessions
    max sessions cancel  <id>       # cancel a queued/running session
    max sessions promote <id>       # push a queued session to the cloud

Only httpx (already an engine dependency) and the stdlib are used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator

import httpx

DEFAULT_ENGINE_URL = "http://127.0.0.1:8001"

# ---- terminal styling (no deps; degrades to plain text when piped) ----------

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def dim(t: str) -> str:
    return _c("2", t)


def bold(t: str) -> str:
    return _c("1", t)


def cyan(t: str) -> str:
    return _c("36", t)


def green(t: str) -> str:
    return _c("32", t)


def red(t: str) -> str:
    return _c("31", t)


def yellow(t: str) -> str:
    return _c("33", t)


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


# ---- SSE streaming ----------------------------------------------------------


async def _stream_deltas(
    client: httpx.AsyncClient, path: str, payload: dict
) -> AsyncIterator[str]:
    """POST ``payload`` to an OpenAI-compatible SSE endpoint and yield text deltas.

    Raises ``httpx.HTTPStatusError`` for non-2xx (e.g. 400 on a non-command) and
    ``RuntimeError`` for an in-stream ``{"error": ...}`` payload.
    """
    async with client.stream("POST", path, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                if data == "[DONE]":
                    return
                continue
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if "error" in obj:
                err = obj["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise RuntimeError(msg)
            for choice in obj.get("choices", []):
                delta = choice.get("delta", {}).get("content")
                if delta:
                    yield delta


async def _print_stream(stream: AsyncIterator[str]) -> str:
    """Print deltas as they arrive; return the full assembled text."""
    parts: list[str] = []
    async for delta in stream:
        parts.append(delta)
        sys.stdout.write(delta)
        sys.stdout.flush()
    if parts and not parts[-1].endswith("\n"):
        sys.stdout.write("\n")
        sys.stdout.flush()
    return "".join(parts)


# ---- command / chat ---------------------------------------------------------


async def _run_dsl(client: httpx.AsyncClient, text: str) -> None:
    """Stream a DSL command from /command."""
    await _print_stream(_stream_deltas(client, "/command", {"text": text}))


async def _run_command_or_chat(client: httpx.AsyncClient, text: str) -> None:
    """Send ``text`` as a DSL command; if the engine rejects it as a non-command
    (400 ParseError), fall back to plain chat. The server's own parser is the
    source of truth, so the client never has to second-guess the grammar."""
    try:
        await _run_dsl(client, text)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            await _print_stream(_stream_deltas(client, "/chat", {"text": text}))
        elif e.response.status_code == 403:
            _eprint(red("✗ cloud is disabled (allow_cloud off or kill-switch on)."))
            raise SystemExit(3) from e
        else:
            raise


# ---- subcommand handlers ----------------------------------------------------


async def do_oneshot(client: httpx.AsyncClient, text: str) -> None:
    await _run_command_or_chat(client, text)


async def do_run(client: httpx.AsyncClient, text: str) -> None:
    await _run_dsl(client, text)


async def do_health(client: httpx.AsyncClient) -> int:
    try:
        h = (await client.get("/health")).json()
    except httpx.HTTPError as e:
        _eprint(red("⃠ engine offline"), dim(f"({client.base_url})"))
        _eprint(dim(f"  {e}"))
        return 1
    print(green("⚡ Max engine online"), dim(f"v{h.get('version', '?')}  {client.base_url}"))
    try:
        cfg = (await client.get("/config")).json()
    except httpx.HTTPError:
        return 0
    chat_model = (cfg.get("task_models") or {}).get("chat", "?")
    resident = (cfg.get("idle") or {}).get("resident_model", "?")
    cloud = cfg.get("allow_cloud")
    offline = cfg.get("force_offline")
    print(f"  chat model     {cyan(chat_model)}")
    print(f"  resident model {cyan(resident)}")
    cloud_str = green("on") if cloud else dim("off")
    if offline:
        cloud_str = red("kill-switch (offline)")
    print(f"  cloud          {cloud_str}")
    keys = []
    if cfg.get("cloud_key_set"):
        keys.append("Anthropic")
    if cfg.get("openai_key_set"):
        keys.append("OpenAI")
    print(f"  keys set       {cyan(', '.join(keys)) if keys else dim('none')}")
    return 0


_STATE_COLOR = {
    "done": green,
    "running": cyan,
    "queued": yellow,
    "error": red,
    "cancelled": dim,
}


async def do_sessions_list(client: httpx.AsyncClient) -> int:
    try:
        data = (await client.get("/sessions")).json()
    except httpx.HTTPError as e:
        _eprint(red("⃠ engine offline"), dim(f"({e})"))
        return 1
    sessions = data.get("sessions", [])
    if not sessions:
        print(dim("no sessions"))
        return 0
    for s in sessions:
        state = s.get("state", "?")
        color = _STATE_COLOR.get(state, str)
        cloud = " ☁" if s.get("is_cloud") else ""
        sid = s.get("id", "")[:8]
        line = (
            f"{dim(sid)}  {color(state.ljust(9))}  "
            f"{s.get('provider', '?')}/{s.get('model', '?')}{cloud}  "
            f"{bold(s.get('action', ''))}"
        )
        print(line)
        task = (s.get("task") or "").strip().replace("\n", " ")
        if task:
            print(dim(f"          {task[:100]}"))
    return 0


async def _session_action(client: httpx.AsyncClient, action: str, session_id: str) -> int:
    try:
        resp = await client.post(f"/sessions/{session_id}/{action}")
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except ValueError:
            pass
        _eprint(red(f"✗ {action} failed:"), detail or str(e))
        return 1
    except httpx.HTTPError as e:
        _eprint(red("⃠ engine offline"), dim(f"({e})"))
        return 1
    s = resp.json()
    print(green(f"✓ {action}"), dim(s.get("id", session_id)[:8]), "→", s.get("state", "?"))
    return 0


# ---- interactive REPL -------------------------------------------------------

REPL_BANNER = """\
⚡ Max — interactive chat. Local by default; cloud on ! / %.
   DSL commands run one-shot (e.g.  !. write a regex . ).
   Plain text is multi-turn chat with memory.
   /reset clears memory · /health · /sessions · /exit (or Ctrl-D) to quit.
"""

# A line is treated as a one-shot DSL command (not chat) when it begins with a
# provider sigil or an operator delimiter. Mirrors the engine's grammar enough
# to route; the engine remains the authoritative parser.
_SIGILS = "@#!%^"
_OP_STARTS = (".", "~")


def _looks_like_dsl(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s[0] in _SIGILS:
        s = s[1:].lstrip()
    return s.startswith(_OP_STARTS)


async def _repl_chat_turn(
    client: httpx.AsyncClient, messages: list[dict], model: str
) -> None:
    """Multi-turn chat via the OpenAI-compatible endpoint so the conversation
    carries memory across turns (the plain /chat endpoint is single-shot)."""
    payload = {"model": model, "messages": messages, "provider": "ollama", "stream": True}
    reply = await _print_stream(_stream_deltas(client, "/v1/chat/completions", payload))
    if reply:
        messages.append({"role": "assistant", "content": reply})


async def do_repl(client: httpx.AsyncClient) -> int:
    # Confirm the engine is up and learn the default chat model.
    try:
        cfg = (await client.get("/config")).json()
    except httpx.HTTPError as e:
        _eprint(red("⃠ engine offline"), dim(f"({client.base_url})  {e}"))
        return 1
    chat_model = (cfg.get("task_models") or {}).get("chat", "qwen2.5-coder:14b")
    print(cyan(REPL_BANNER))
    messages: list[dict] = []
    loop = asyncio.get_event_loop()
    while True:
        try:
            # input() blocks; run it off the event loop so streaming stays async-clean.
            line = await loop.run_in_executor(None, lambda: input(bold("max› ")))
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        line = line.strip()
        if not line:
            continue
        if line in ("/exit", "/quit", ":q"):
            return 0
        if line == "/reset":
            messages.clear()
            print(dim("memory cleared"))
            continue
        if line == "/health":
            await do_health(client)
            continue
        if line == "/sessions":
            await do_sessions_list(client)
            continue
        try:
            if _looks_like_dsl(line):
                await _run_command_or_chat(client, line)
            else:
                messages.append({"role": "user", "content": line})
                await _repl_chat_turn(client, messages, chat_model)
        except RuntimeError as e:  # in-stream backend error
            _eprint(red(f"✗ {e}"))
        except httpx.HTTPError as e:
            _eprint(red("✗ request failed:"), dim(str(e)))
    return 0


# ---- argument parsing / entrypoint ------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="max",
        description="Max — local-first AI engine CLI client.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            '  max "!. write a fizzbuzz in python ."   one-shot DSL command (Claude)\n'
            '  max "what is a monad?"                   one-shot plain chat (local)\n'
            "  max chat                                 interactive REPL\n"
            "  max health                               engine status\n"
            "  max sessions                             list delegate sessions\n"
        ),
    )
    p.add_argument(
        "--engine",
        default=os.environ.get("MAX_ENGINE_URL", DEFAULT_ENGINE_URL),
        help=f"engine base URL (env MAX_ENGINE_URL; default {DEFAULT_ENGINE_URL})",
    )
    sub = p.add_subparsers(dest="cmd")

    sp_run = sub.add_parser("run", help="run an explicit DSL command and stream the result")
    sp_run.add_argument("text", nargs="+", help="the DSL command, e.g. '. add a docstring .'")

    sub.add_parser("chat", help="interactive multi-turn chat REPL")
    sub.add_parser("health", help="show engine health, active model, and cloud state")

    sp_sess = sub.add_parser("sessions", help="list/cancel/promote delegate sessions")
    sp_sess.add_argument(
        "action",
        nargs="?",
        choices=["list", "cancel", "promote"],
        default="list",
    )
    sp_sess.add_argument("id", nargs="?", help="session id (for cancel/promote)")

    return p


_SUBCOMMANDS = {"run", "chat", "health", "sessions"}


def _split_engine(argv: list[str]) -> tuple[str, list[str]]:
    """Pull a global ``--engine URL`` / ``--engine=URL`` out of ``argv`` wherever
    it appears, returning (engine_url, remaining_argv). Lets bare one-shot text
    (`max "what is a monad?"`) coexist with `--engine` without argparse treating
    the first word as a subcommand."""
    engine = os.environ.get("MAX_ENGINE_URL", DEFAULT_ENGINE_URL)
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--engine" and i + 1 < len(argv):
            engine = argv[i + 1]
            i += 2
            continue
        if a.startswith("--engine="):
            engine = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return engine, rest


async def _dispatch(engine: str, args: argparse.Namespace | None, oneshot: str | None) -> int:
    timeout = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
    async with httpx.AsyncClient(base_url=engine.rstrip("/"), timeout=timeout) as client:
        try:
            if oneshot is not None:
                await do_oneshot(client, oneshot)
                return 0
            if args is None or args.cmd is None or args.cmd == "chat":
                return await do_repl(client)
            if args.cmd == "health":
                return await do_health(client)
            if args.cmd == "run":
                await do_run(client, " ".join(args.text))
                return 0
            if args.cmd == "sessions":
                if args.action == "list":
                    return await do_sessions_list(client)
                if not args.id:
                    _eprint(red(f"✗ '{args.action}' needs a session id"))
                    return 2
                return await _session_action(client, args.action, args.id)
            return 0
        except RuntimeError as e:  # in-stream backend error
            _eprint(red(f"✗ {e}"))
            return 1
        except httpx.HTTPError as e:
            _eprint(red("⃠ engine request failed"), dim(f"({engine})"))
            _eprint(dim(f"  {e}"))
            return 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    engine, rest = _split_engine(argv)

    args: argparse.Namespace | None = None
    oneshot: str | None = None
    if not rest:
        pass  # → REPL
    elif rest[0] in _SUBCOMMANDS or rest[0] in ("-h", "--help"):
        args = _build_parser().parse_args(rest)
    else:
        # Bare text → one-shot DSL command or chat (the common case).
        oneshot = " ".join(rest)

    try:
        return asyncio.run(_dispatch(engine, args, oneshot))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
