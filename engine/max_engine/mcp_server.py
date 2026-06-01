"""Stdio entrypoint for Max's inbound MCP façade.

Launched by an external MCP host (e.g. Claude Desktop) as a subprocess:

    python -m max_engine.mcp_server

Reads newline-delimited JSON-RPC requests on stdin, proxies each to the running
Max engine over HTTP via :class:`~max_engine.mcp.facade.MaxFacade`, and writes
responses to stdout. The engine itself must be running (Max desktop app or
``uvicorn``); this process is a thin bridge, not the engine.

``MAX_ENGINE_BASE`` overrides the engine URL (default ``http://127.0.0.1:8001``).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from .mcp.facade import MaxFacade


async def _serve() -> None:
    base = os.environ.get("MAX_ENGINE_BASE", "http://127.0.0.1:8001")
    facade = MaxFacade(base)
    loop = asyncio.get_event_loop()

    # Read stdin with a blocking readline on the default executor. This is the
    # portable approach: asyncio.connect_read_pipe(sys.stdin) is unsupported on
    # Windows (ProactorEventLoop), where MCP hosts like Claude Desktop also run.
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, TypeError):
            continue
        response = await facade.handle(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    try:
        asyncio.run(_serve())
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
