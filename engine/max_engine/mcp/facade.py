"""Inbound MCP façade — expose Max as an MCP server.

Lets an external MCP host (Claude Desktop, Cursor, …) call Max. The façade speaks
JSON-RPC 2.0 and proxies each tool call to the **running Max engine's HTTP API**,
so it reuses all of the engine's routing, providers, and skills — the façade is
just another thin client (consistent with "one engine, many clients").

:class:`MaxFacade` is transport-agnostic: it turns a parsed JSON-RPC message into
a response dict. ``max_engine.mcp_server`` wraps it in a stdio loop (what Claude
Desktop launches); the ``/mcp/facade`` endpoint serves its manifest + a
ready-to-paste Claude Desktop config snippet.
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "max", "version": "1.0.0"}

# Tools surfaced to the external host. Each maps to a Max engine HTTP endpoint.
FACADE_TOOLS: list[dict] = [
    {
        "name": "max_ask",
        "description": (
            "Ask Max anything. Routes through Max's intent router to the right skill "
            "(web search, reports, files, calendar, Spotify) or a general answer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "The request or question."}},
            "required": ["message"],
        },
    },
    {
        "name": "max_market_board",
        "description": "Get Max's live US-stock watchlist board (symbol, price, % change).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "max_osint_hotspots",
        "description": "Get the top countries on Max's global OSINT news-heat map right now.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text_result(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


class MaxFacade:
    def __init__(self, engine_base: str = "http://127.0.0.1:8001", *, client: Any = None) -> None:
        self._base = engine_base.rstrip("/")
        self._client = client

    # ---- JSON-RPC dispatch ---------------------------------------------

    async def handle(self, msg: dict) -> dict | None:
        """Map a JSON-RPC request to a response dict. Returns None for notifications."""
        method = msg.get("method")
        mid = msg.get("id")
        if method is None:
            return None
        if mid is None:  # a notification (e.g. notifications/initialized)
            return None
        try:
            result = await self._dispatch(method, msg.get("params") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": e.message}}
        except Exception as e:  # never crash the loop on a tool error
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}

    async def _dispatch(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        if method == "tools/list":
            return {"tools": FACADE_TOOLS}
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            return await self._call_tool(name, args)
        raise _RpcError(-32601, f"method not found: {method}")

    # ---- tools ----------------------------------------------------------

    async def _call_tool(self, name: str, args: dict) -> dict:
        try:
            if name == "max_ask":
                msg = str(args.get("message", "")).strip()
                if not msg:
                    return _text_result("max_ask requires a 'message'.", is_error=True)
                return _text_result(await self._ask(msg))
            if name == "max_market_board":
                return _text_result(await self._get_market_board())
            if name == "max_osint_hotspots":
                return _text_result(await self._get_osint_hotspots())
            return _text_result(f"unknown tool: {name}", is_error=True)
        except Exception as e:
            return _text_result(f"Max engine error: {e}", is_error=True)

    def _make_client(self):
        import httpx

        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=60.0), True

    async def _ask(self, message: str) -> str:
        client, owns = self._make_client()
        try:
            text_parts: list[str] = []
            async with client.stream(
                "POST", f"{self._base}/capabilities/route", json={"message": message}
            ) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except (ValueError, TypeError):
                        continue
                    delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content")
                    if delta:
                        text_parts.append(delta)
            return "".join(text_parts).strip() or "(no response)"
        finally:
            if owns:
                await client.aclose()

    async def _get_market_board(self) -> str:
        client, owns = self._make_client()
        try:
            r = await client.get(f"{self._base}/market/quotes")
            data = r.json()
            quotes = data.get("quotes", [])
            if not quotes:
                return "Market board is empty (no API key or market closed)."
            lines = [
                f"{q['symbol']}: ${q['price']} ({'+' if q['changePct'] >= 0 else ''}{q['changePct']}%)"
                for q in quotes
            ]
            return "Live market board:\n" + "\n".join(lines)
        finally:
            if owns:
                await client.aclose()

    async def _get_osint_hotspots(self) -> str:
        client, owns = self._make_client()
        try:
            r = await client.get(f"{self._base}/osint/heatmap")
            data = r.json()
            countries = (data.get("countries") or [])[:10]
            if not countries:
                return "No OSINT hotspots available."
            lines = [
                f"{c['name']} — {c['severityLabel']} ({c['articleCount']} articles)"
                for c in countries
            ]
            return "Top OSINT hotspots:\n" + "\n".join(lines)
        finally:
            if owns:
                await client.aclose()


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def claude_desktop_config(python_exe: str, engine_dir: str) -> dict:
    """A ready-to-paste ``claude_desktop_config.json`` entry that launches the
    façade as a stdio MCP server."""
    return {
        "mcpServers": {
            "max": {
                "command": python_exe,
                "args": ["-m", "max_engine.mcp_server"],
                "cwd": engine_dir,
            }
        }
    }
