"""Minimal MCP (Model Context Protocol) client — JSON-RPC 2.0 over the stdio
transport.

The MCP stdio transport is newline-delimited JSON: each message is a single JSON
object on its own line (no embedded newlines). This module speaks just enough of
the protocol to be an MCP *host*: ``initialize`` → ``tools/list`` → ``tools/call``.

No third-party SDK — stdlib ``asyncio`` only, so it stays inside the project's
"stdlib + httpx" dependency budget. The protocol layer (:class:`MCPConnection`)
is split from process spawning (:class:`MCPStdioClient`) so it can be tested
against in-memory streams without launching a subprocess.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "max-engine", "version": "1.0.0"}


class MCPError(Exception):
    """An MCP server returned a JSON-RPC error, or the transport failed."""


class MCPConnection:
    """JSON-RPC 2.0 over a newline-delimited reader/writer pair.

    ``reader`` needs an awaitable ``readline() -> bytes``; ``writer`` needs
    ``write(bytes)`` and an awaitable ``drain()`` (the asyncio StreamReader/Writer
    contract, which tests can fake).
    """

    def __init__(self, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer
        self._id = 0

    async def _send(self, msg: dict) -> None:
        self._writer.write((json.dumps(msg) + "\n").encode("utf-8"))
        await self._writer.drain()

    async def request(self, method: str, params: dict | None = None, *, timeout: float = 30.0) -> dict:
        self._id += 1
        rid = self._id
        msg: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        await self._send(msg)
        # Read until we see the response carrying our id (skip notifications and
        # any interleaved messages with other ids).
        while True:
            line = await asyncio.wait_for(self._reader.readline(), timeout)
            if not line:
                raise MCPError(f"connection closed awaiting response to {method!r}")
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("id") == rid:
                if "error" in obj and obj["error"] is not None:
                    err = obj["error"]
                    raise MCPError(str(err.get("message", err)) if isinstance(err, dict) else str(err))
                return obj.get("result", {})

    async def notify(self, method: str, params: dict | None = None) -> None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._send(msg)

    async def initialize(self) -> dict:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        await self.notify("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict]:
        result = await self.request("tools/list")
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return await self.request("tools/call", {"name": name, "arguments": arguments or {}})


def tool_result_text(result: dict) -> str:
    """Flatten an MCP ``tools/call`` result into plain text for display.

    MCP returns ``{"content": [{"type": "text", "text": ...}, ...], "isError": …}``.
    """
    if not isinstance(result, dict):
        return str(result)
    parts: list[str] = []
    for block in result.get("content", []):
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif "text" in block:
                parts.append(str(block["text"]))
    return "\n".join(parts) if parts else json.dumps(result)


def _parse_rpc_response(text: str) -> dict | None:
    """Parse a JSON-RPC reply that may arrive as raw JSON or a single SSE event."""
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None
    last: dict | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            try:
                last = json.loads(data)
            except (ValueError, TypeError):
                continue
    return last


class MCPHttpClient:
    """Minimal MCP client over the Streamable HTTP transport (httpx).

    POSTs JSON-RPC and accepts either a JSON body or a single SSE event in reply.
    Tracks an ``mcp-session-id`` header across calls if the server issues one.
    Covers the common case; not a full streaming-HTTP implementation."""

    def __init__(self, url: str, *, headers: dict | None = None, client: Any = None) -> None:
        self._url = url
        self._headers = headers or {}
        self._client = client
        self._id = 0
        self._session_id: str | None = None
        self.server_info: dict = {}
        self.tools: list[dict] = []

    async def _rpc(self, method: str, params: dict | None = None, *, expect_reply: bool = True) -> dict:
        import httpx

        self._id += 1
        payload: dict = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            **self._headers,
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.post(self._url, json=payload, headers=headers)
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._session_id = sid
            if resp.status_code >= 400:
                raise MCPError(f"HTTP {resp.status_code} from MCP server")
            obj = _parse_rpc_response(resp.text)
        finally:
            if owns:
                await client.aclose()
        if not expect_reply:
            return {}
        if obj is None:
            raise MCPError(f"no JSON-RPC response for {method!r}")
        if obj.get("error"):
            err = obj["error"]
            raise MCPError(str(err.get("message", err)) if isinstance(err, dict) else str(err))
        return obj.get("result", {})

    async def connect(self) -> None:
        init = await self._rpc(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        self.server_info = init.get("serverInfo", {})
        try:
            await self._rpc("notifications/initialized", expect_reply=False)
        except MCPError:
            pass
        result = await self._rpc("tools/list")
        tools = result.get("tools", [])
        self.tools = tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    async def close(self) -> None:
        return None


class MCPStdioClient:
    """Spawns an MCP server as a subprocess and talks to it over stdio."""

    def __init__(self, command: list[str], *, cwd: str | None = None, env: dict | None = None) -> None:
        if not command:
            raise MCPError("stdio MCP server requires a command")
        self._command = command
        self._cwd = cwd
        self._env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._conn: MCPConnection | None = None
        self.server_info: dict = {}
        self.tools: list[dict] = []

    async def connect(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
        )
        assert self._proc.stdout is not None and self._proc.stdin is not None
        self._conn = MCPConnection(self._proc.stdout, self._proc.stdin)
        init = await self._conn.initialize()
        self.server_info = init.get("serverInfo", {})
        self.tools = await self._conn.list_tools()

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        if self._conn is None:
            raise MCPError("not connected")
        return await self._conn.call_tool(name, arguments)

    async def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
            self._proc = None
            self._conn = None
