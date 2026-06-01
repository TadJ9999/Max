"""MCP host manager — Max as an MCP *client* of external servers.

Holds the configured server list, connects/disconnects on demand, aggregates the
discovered tools, and routes ``tools/call`` to the right server. Connections are
lazy (opened on ``connect``) and the manager keeps one live client per server.

The default connector builds an :class:`MCPStdioClient` or :class:`MCPHttpClient`
from each server's config; tests inject a fake connector so no real process or
socket is involved.
"""

from __future__ import annotations

from typing import Any

from .client import MCPError, MCPHttpClient, MCPStdioClient


def _default_connector(cfg: dict) -> Any:
    transport = (cfg.get("transport") or "stdio").lower()
    if transport == "stdio":
        return MCPStdioClient(cfg.get("command") or [], cwd=cfg.get("cwd") or None)
    if transport in ("http", "sse", "streamable-http"):
        url = cfg.get("url") or ""
        if not url:
            raise MCPError("http MCP server requires a url")
        return MCPHttpClient(url, headers=cfg.get("headers") or {})
    raise MCPError(f"unsupported MCP transport: {transport!r}")


class MCPManager:
    def __init__(self, servers: list[dict] | None = None, *, connector: Any = None) -> None:
        self._configs: dict[str, dict] = {}
        self._clients: dict[str, Any] = {}
        self._errors: dict[str, str] = {}
        self._connector = connector or _default_connector
        if servers:
            self.set_servers(servers)

    # ---- config ---------------------------------------------------------

    def set_servers(self, servers: list[dict]) -> None:
        """Replace the configured server list (does not touch live connections)."""
        self._configs = {s["name"]: dict(s) for s in servers if s.get("name")}

    def add_server(self, cfg: dict) -> list[dict]:
        if not cfg.get("name"):
            raise MCPError("server requires a name")
        self._configs[cfg["name"]] = dict(cfg)
        return self.server_configs()

    async def remove_server(self, name: str) -> list[dict]:
        await self.disconnect(name)
        self._configs.pop(name, None)
        return self.server_configs()

    def server_configs(self) -> list[dict]:
        return [dict(c) for c in self._configs.values()]

    # ---- connection lifecycle ------------------------------------------

    async def connect(self, name: str) -> dict:
        cfg = self._configs.get(name)
        if cfg is None:
            raise MCPError(f"unknown MCP server: {name!r}")
        await self.disconnect(name)
        client = self._connector(cfg)
        try:
            await client.connect()
        except Exception as e:
            self._errors[name] = str(e)
            raise MCPError(f"failed to connect to {name!r}: {e}") from e
        self._clients[name] = client
        self._errors.pop(name, None)
        return self._describe(name)

    async def disconnect(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass

    async def call(self, server: str, tool: str, arguments: dict | None = None) -> dict:
        client = self._clients.get(server)
        if client is None:
            raise MCPError(f"server {server!r} is not connected")
        return await client.call_tool(tool, arguments)

    async def shutdown(self) -> None:
        for name in list(self._clients):
            await self.disconnect(name)

    # ---- introspection --------------------------------------------------

    def _describe(self, name: str) -> dict:
        cfg = self._configs.get(name, {})
        client = self._clients.get(name)
        return {
            "name": name,
            "transport": cfg.get("transport", "stdio"),
            "command": cfg.get("command", []),
            "url": cfg.get("url", ""),
            "enabled": cfg.get("enabled", True),
            "connected": client is not None,
            "tools": getattr(client, "tools", []) if client else [],
            "serverInfo": getattr(client, "server_info", {}) if client else {},
            "error": self._errors.get(name),
        }

    def list_servers(self) -> list[dict]:
        return [self._describe(name) for name in self._configs]

    def all_tools(self) -> list[dict]:
        """Flat list of every connected server's tools, tagged with the server."""
        out: list[dict] = []
        for name, client in self._clients.items():
            for tool in getattr(client, "tools", []):
                out.append({"server": name, **tool})
        return out
