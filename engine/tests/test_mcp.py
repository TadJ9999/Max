"""Tests for the MCP host (outbound) + façade (inbound).

No real subprocesses or sockets: the stdio protocol is tested against in-memory
streams, the manager against an injected fake connector, the HTTP client against
httpx.MockTransport, and the façade against a fake engine client.
"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.mcp.client import (
    MCPConnection,
    MCPError,
    MCPHttpClient,
    _parse_rpc_response,
    tool_result_text,
)
from max_engine.mcp.facade import MaxFacade, claude_desktop_config
from max_engine.mcp.manager import MCPManager


def _run(coro):
    return asyncio.run(coro)


# ---- stdio JSON-RPC connection ------------------------------------------


class _FakeReader:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""


class _FakeWriter:
    def __init__(self):
        self.sent = []

    def write(self, b):
        self.sent.append(b)

    async def drain(self):
        pass


def test_connection_request_roundtrip():
    reader = _FakeReader([b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'])
    writer = _FakeWriter()
    conn = MCPConnection(reader, writer)
    res = _run(conn.request("ping", {"x": 1}))
    assert res == {"ok": True}
    sent = json.loads(writer.sent[0])
    assert sent["method"] == "ping" and sent["id"] == 1 and sent["params"] == {"x": 1}


def test_connection_skips_unrelated_ids():
    reader = _FakeReader([
        b'{"jsonrpc":"2.0","method":"notifications/log","params":{}}\n',  # notification
        b'{"jsonrpc":"2.0","id":99,"result":{"nope":1}}\n',              # other id
        b'{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"t1"}]}}\n',
    ])
    conn = MCPConnection(reader, _FakeWriter())
    assert _run(conn.list_tools()) == [{"name": "t1"}]


def test_connection_error_raises():
    reader = _FakeReader([b'{"jsonrpc":"2.0","id":1,"error":{"message":"boom"}}\n'])
    with pytest.raises(MCPError):
        _run(MCPConnection(reader, _FakeWriter()).request("x"))


def test_connection_initialize_sends_notification():
    reader = _FakeReader([b'{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"s"}}}\n'])
    writer = _FakeWriter()
    conn = MCPConnection(reader, writer)
    res = _run(conn.initialize())
    assert res["serverInfo"]["name"] == "s"
    assert json.loads(writer.sent[1])["method"] == "notifications/initialized"


# ---- helpers -------------------------------------------------------------


def test_tool_result_text_flattens_content():
    assert tool_result_text({"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}) == "a\nb"
    assert tool_result_text({"weird": 1}) == '{"weird": 1}'


def test_parse_rpc_response_json_and_sse():
    assert _parse_rpc_response('{"id":1,"result":{}}')["id"] == 1
    sse = "event: message\ndata: {\"id\":2,\"result\":{\"x\":1}}\n\n"
    assert _parse_rpc_response(sse)["id"] == 2
    assert _parse_rpc_response("") is None


# ---- manager (injected fake connector) ----------------------------------


class _FakeClient:
    def __init__(self, cfg):
        self._cfg = cfg
        self.tools = [{"name": "hello", "description": "say hi"}]
        self.server_info = {"name": "fake"}
        self.closed = False

    async def connect(self):
        pass

    async def call_tool(self, name, arguments=None):
        return {"content": [{"type": "text", "text": f"called {name} {arguments}"}]}

    async def close(self):
        self.closed = True


def test_manager_connect_call_and_remove():
    mgr = MCPManager(
        [{"name": "s1", "transport": "stdio", "command": ["x"]}],
        connector=lambda cfg: _FakeClient(cfg),
    )

    async def run():
        desc = await mgr.connect("s1")
        res = await mgr.call("s1", "hello", {"a": 1})
        all_tools = mgr.all_tools()
        await mgr.remove_server("s1")
        return desc, res, all_tools, mgr.list_servers()

    desc, res, all_tools, servers = _run(run())
    assert desc["connected"] is True and desc["tools"][0]["name"] == "hello"
    assert "called hello" in tool_result_text(res)
    assert all_tools[0]["server"] == "s1"
    assert servers == []  # removed


def test_manager_unknown_server_and_not_connected():
    mgr = MCPManager(connector=lambda cfg: _FakeClient(cfg))
    with pytest.raises(MCPError):
        _run(mgr.connect("nope"))
    mgr.add_server({"name": "s2", "command": ["y"]})
    with pytest.raises(MCPError):
        _run(mgr.call("s2", "tool"))  # added but not connected


def test_manager_connect_failure_records_error():
    class _Boom(_FakeClient):
        async def connect(self):
            raise RuntimeError("spawn failed")

    mgr = MCPManager([{"name": "b", "command": ["z"]}], connector=lambda cfg: _Boom(cfg))
    with pytest.raises(MCPError):
        _run(mgr.connect("b"))
    desc = next(s for s in mgr.list_servers() if s["name"] == "b")
    assert desc["connected"] is False and "spawn failed" in (desc["error"] or "")


# ---- HTTP transport client (mocked httpx) -------------------------------


def test_http_client_connect_and_call():
    def handler(req):
        body = json.loads(req.content)
        rid = body.get("id")
        method = body["method"]
        if method == "initialize":
            result = {"serverInfo": {"name": "h"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "ht"}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "ok"}]}
        else:
            result = {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": result})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            cli = MCPHttpClient("http://x/mcp", client=c)
            await cli.connect()
            res = await cli.call_tool("ht", {})
            return cli.tools, res

    tools, res = _run(run())
    assert tools == [{"name": "ht"}]
    assert tool_result_text(res) == "ok"


# ---- inbound façade ------------------------------------------------------


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeEngine:
    def __init__(self, getmap):
        self._getmap = getmap

    async def get(self, url):
        for k, v in self._getmap.items():
            if k in url:
                return _FakeResp(v)
        return _FakeResp({})


def test_facade_initialize_and_tools_list():
    f = MaxFacade(client=_FakeEngine({}))
    init = _run(f.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}))
    assert init["result"]["serverInfo"]["name"] == "max"
    tl = _run(f.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    names = [t["name"] for t in tl["result"]["tools"]]
    assert "max_ask" in names and "max_market_board" in names and "max_osint_hotspots" in names


def test_facade_notification_returns_none():
    f = MaxFacade(client=_FakeEngine({}))
    assert _run(f.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None


def test_facade_market_board_tool():
    fake = _FakeEngine({"/market/quotes": {"quotes": [{"symbol": "AAPL", "price": 191.5, "changePct": 1.3}]}})
    f = MaxFacade(client=fake)
    r = _run(f.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "max_market_board", "arguments": {}}}))
    assert "AAPL" in r["result"]["content"][0]["text"]


def test_facade_unknown_method_is_jsonrpc_error():
    f = MaxFacade(client=_FakeEngine({}))
    r = _run(f.handle({"jsonrpc": "2.0", "id": 9, "method": "bogus"}))
    assert r["error"]["code"] == -32601


def test_claude_desktop_config_shape():
    cfg = claude_desktop_config("C:/py.exe", "C:/dev/Max/engine")
    assert cfg["mcpServers"]["max"]["command"] == "C:/py.exe"
    assert cfg["mcpServers"]["max"]["args"] == ["-m", "max_engine.mcp_server"]


# ---- endpoints -----------------------------------------------------------


def test_mcp_endpoints(monkeypatch, tmp_path):
    import max_engine.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".maxconfig.json")
    monkeypatch.setattr(m, "mcp_manager", MCPManager(connector=lambda c: _FakeClient(c)))
    c = TestClient(m.app)

    # add a server (persists)
    r = c.post("/mcp/servers", json={"name": "fs", "transport": "stdio", "command": ["python", "-m", "server"]})
    assert r.status_code == 200
    assert any(s["name"] == "fs" for s in r.json()["servers"])

    # connect + tools surface
    r = c.post("/mcp/servers/fs/connect")
    assert r.status_code == 200 and r.json()["connected"] is True

    # call a tool
    r = c.post("/mcp/call", json={"server": "fs", "tool": "hello", "arguments": {}})
    assert r.status_code == 200 and "called hello" in r.json()["text"]

    # remove
    r = c.delete("/mcp/servers/fs")
    assert r.status_code == 200 and r.json()["servers"] == []


def test_mcp_facade_endpoint():
    c = TestClient(m.app)
    r = c.get("/mcp/facade")
    assert r.status_code == 200
    body = r.json()
    assert any(t["name"] == "max_ask" for t in body["tools"])
    assert body["claudeDesktopConfig"]["mcpServers"]["max"]["args"] == ["-m", "max_engine.mcp_server"]


def test_mcp_call_not_connected_502(monkeypatch):
    monkeypatch.setattr(m, "mcp_manager", MCPManager(connector=lambda c: _FakeClient(c)))
    c = TestClient(m.app)
    r = c.post("/mcp/call", json={"server": "ghost", "tool": "x", "arguments": {}})
    assert r.status_code == 502
