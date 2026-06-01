"""MCP (Model Context Protocol) host + façade.

Two directions:
  * **Outbound host** — :class:`MCPManager` connects Max to external MCP servers
    (stdio or HTTP) and routes ``tools/call``.
  * **Inbound façade** — :class:`MaxFacade` exposes Max's own capabilities as an
    MCP server so Claude Desktop / Cursor can call Max.
"""

from __future__ import annotations

from .client import MCPConnection, MCPError, MCPHttpClient, MCPStdioClient, tool_result_text
from .facade import FACADE_TOOLS, MaxFacade, claude_desktop_config
from .manager import MCPManager

__all__ = [
    "MCPManager",
    "MCPConnection",
    "MCPStdioClient",
    "MCPHttpClient",
    "MCPError",
    "tool_result_text",
    "MaxFacade",
    "FACADE_TOOLS",
    "claude_desktop_config",
]
