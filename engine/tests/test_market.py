"""Market tests — Finnhub quote parsing, service caching, watchlist, endpoints.

Network is fully mocked via httpx.MockTransport; no real Finnhub calls.
"""

import asyncio
import json
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.market.finnhub import fetch_market_news, fetch_quote
from max_engine.market.models import MarketBoard, Quote
from max_engine.market.service import MarketService, board_digest
from max_engine.market.stream import TradeStream
from max_engine.providers.base import ChatChunk

API_KEY = "test-key"

# A general market-news payload; the second item has no headline and is skipped.
NEWS_JSON = [
    {"headline": "Stocks rally", "source": "Reuters", "summary": "x" * 400,
     "url": "http://e/1", "datetime": 1748600000},
    {"category": "general"},
]


class _FakeProvider:
    """Stand-in provider so endpoint tests don't hit a real model. Streams two
    chunks and records unload() calls."""

    def __init__(self):
        self.unloaded = None

    async def chat(self, model, messages, **params):
        yield ChatChunk(text="hello", done=False)
        yield ChatChunk(text="", done=True)

    async def unload(self, model):
        self.unloaded = model
        return True

# A normal /quote payload (c=current, d=change, dp=percent, pc=prev close, t=unix).
QUOTE_JSON = {
    "c": 191.5, "d": 2.5, "dp": 1.32, "h": 192.0,
    "l": 188.0, "o": 189.0, "pc": 189.0, "t": 1748600000,
}
PROFILE_JSON = {"name": "Apple Inc."}
# Finnhub returns c=0 for an unknown symbol.
EMPTY_QUOTE_JSON = {"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}


def _handler(req: httpx.Request) -> httpx.Response:
    if req.url.path.endswith("/profile2"):
        return httpx.Response(200, json=PROFILE_JSON)
    sym = req.url.params.get("symbol", "")
    if sym == "BADSYM":
        return httpx.Response(200, json=EMPTY_QUOTE_JSON)
    return httpx.Response(200, json=QUOTE_JSON)


def _mock_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


# ---- finnhub parsing ----------------------------------------------------


def test_fetch_quote_parses_payload():
    async def run():
        async with _mock_client() as client:
            return await fetch_quote(client, "AAPL", API_KEY)

    q = asyncio.run(run())
    assert q is not None
    assert q.symbol == "AAPL"
    assert q.name == "Apple Inc."
    assert q.price == 191.5
    assert q.change == 2.5
    assert q.change_pct == 1.32
    assert q.prev_close == 189.0
    assert q.ts is not None


def test_fetch_quote_skips_unknown_symbol():
    async def run():
        async with _mock_client() as client:
            return await fetch_quote(client, "BADSYM", API_KEY)

    assert asyncio.run(run()) is None  # c=0 -> no data, not an exception


def test_fetch_quote_swallows_http_error():
    def boom(_req):
        return httpx.Response(503)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
            return await fetch_quote(client, "AAPL", API_KEY)

    assert asyncio.run(run()) is None


# ---- service: board + caching ------------------------------------------


def test_get_board_aggregates_watchlist():
    async def run():
        async with _mock_client() as client:
            svc = MarketService(symbols=["AAPL", "MSFT", "BADSYM"], api_key=API_KEY, client=client)
            return await svc.get_board()

    board = asyncio.run(run())
    syms = {q.symbol for q in board.quotes}
    assert syms == {"AAPL", "MSFT"}  # BADSYM dropped, not fatal
    assert board.to_dict()["count"] == 2


def test_board_caches_within_ttl():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return _handler(req)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            svc = MarketService(symbols=["AAPL"], api_key=API_KEY, ttl_seconds=600, client=client)
            await svc.get_board()
            await svc.get_board()  # second call should hit cache, not the network

    asyncio.run(run())
    # one /quote call per symbol (profile2 skipped: with_name=False to stay within free-tier rate limit)
    assert calls["n"] == 1


def test_no_key_yields_empty_board():
    async def run():
        svc = MarketService(symbols=["AAPL"], api_key=None)
        return await svc.get_board()

    board = asyncio.run(run())
    assert board.quotes == []


def test_set_watchlist_roundtrip_and_dedup():
    svc = MarketService(symbols=["AAPL"], api_key=API_KEY)
    out = svc.set_watchlist(["msft", "MSFT", " nvda ", ""])
    assert out == ["MSFT", "NVDA"]
    assert svc.get_watchlist() == ["MSFT", "NVDA"]


# ---- endpoints ----------------------------------------------------------


def test_market_endpoints(monkeypatch):
    monkeypatch.setattr(
        m, "market", MarketService(symbols=["AAPL", "MSFT"], api_key=API_KEY, client=_mock_client())
    )
    c = TestClient(m.app)

    quotes = c.get("/market/quotes")
    assert quotes.status_code == 200
    body = quotes.json()
    assert "updated" in body and isinstance(body["quotes"], list)
    assert body["count"] == 2

    src = c.get("/market/sources")
    assert src.status_code == 200
    assert src.json()["key_set"] is True
    assert src.json()["provider"] == "finnhub"

    wl = c.get("/market/watchlist")
    assert wl.status_code == 200
    assert wl.json()["watchlist"] == ["AAPL", "MSFT"]


def test_market_watchlist_put(monkeypatch, tmp_path):
    # Avoid writing the real .maxconfig.json during the persist step.
    import max_engine.config as cfg

    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".maxconfig.json")
    monkeypatch.setattr(
        m, "market", MarketService(symbols=["AAPL"], api_key=API_KEY, client=_mock_client())
    )
    c = TestClient(m.app)

    r = c.put("/market/watchlist", json={"symbols": ["nvda", "amd"]})
    assert r.status_code == 200
    assert r.json()["watchlist"] == ["NVDA", "AMD"]
    # and it round-trips on a subsequent GET
    assert c.get("/market/watchlist").json()["watchlist"] == ["NVDA", "AMD"]


def test_market_sources_reports_no_key(monkeypatch):
    monkeypatch.setattr(m, "market", MarketService(symbols=["AAPL"], api_key=None))
    c = TestClient(m.app)
    assert c.get("/market/sources").json()["key_set"] is False
    # /market/quotes still returns a valid (empty) board with no key
    body = c.get("/market/quotes").json()
    assert body["quotes"] == []


# ---- A3: board digest + market news ------------------------------------


def test_board_digest_breadth_and_movers():
    board = MarketBoard(
        updated=datetime.now(timezone.utc),
        quotes=[
            Quote(symbol="A", change_pct=5.0),
            Quote(symbol="B", change_pct=-3.0),
            Quote(symbol="C", change_pct=0.0),
            Quote(symbol="D", change_pct=2.0),
        ],
    )
    d = board_digest(board)
    assert d["count"] == 4
    assert (d["up"], d["down"], d["flat"]) == (2, 1, 1)
    assert d["gainers"][0]["symbol"] == "A"  # biggest gainer first
    assert d["losers"][0]["symbol"] == "B"  # biggest loser first


def test_board_digest_empty():
    d = board_digest(MarketBoard(updated=datetime.now(timezone.utc), quotes=[]))
    assert d["count"] == 0 and d["gainers"] == [] and d["losers"] == []


def test_fetch_market_news_parses_and_trims():
    def handler(req):
        return httpx.Response(200, json=NEWS_JSON)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_market_news(client, API_KEY, count=5)

    news = asyncio.run(run())
    assert len(news) == 1  # headline-less item skipped
    assert news[0]["headline"] == "Stocks rally"
    assert len(news[0]["summary"]) <= 280  # summary trimmed
    assert news[0]["datetime"] is not None


def test_get_news_caches_within_ttl():
    calls = {"n": 0}

    def handler(req):
        if req.url.path.endswith("/news"):
            calls["n"] += 1
            return httpx.Response(200, json=NEWS_JSON)
        return _handler(req)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            svc = MarketService(symbols=["AAPL"], api_key=API_KEY, client=client)
            await svc.get_news()
            await svc.get_news()  # second call hits the cache

    asyncio.run(run())
    assert calls["n"] == 1


def test_get_news_no_key_is_empty():
    assert asyncio.run(MarketService(api_key=None).get_news()) == []


# ---- A2: market chat + A4: model unload (provider mocked) ---------------


def test_market_analyze_streams(monkeypatch):
    monkeypatch.setattr(
        m, "market", MarketService(symbols=["AAPL"], api_key=API_KEY, client=_mock_client())
    )
    monkeypatch.setattr(m, "build_provider", lambda name, cfg: _FakeProvider())
    r = TestClient(m.app).post("/market/analyze")
    assert r.status_code == 200
    assert "hello" in r.text


def test_market_chat_streams(monkeypatch):
    monkeypatch.setattr(
        m, "market", MarketService(symbols=["AAPL"], api_key=API_KEY, client=_mock_client())
    )
    monkeypatch.setattr(m, "build_provider", lambda name, cfg: _FakeProvider())
    r = TestClient(m.app).post(
        "/market/chat", json={"messages": [{"role": "user", "content": "how's AAPL?"}]}
    )
    assert r.status_code == 200
    assert "hello" in r.text


def test_engine_unload(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr(m, "build_provider", lambda name, cfg: fake)
    r = TestClient(m.app).post("/engine/unload")
    assert r.status_code == 200
    assert r.json()["unloaded"] is True
    assert fake.unloaded is not None


# ---- trade WebSocket → SSE bridge ---------------------------------------


class _FakeWS:
    """Async-context-manager stand-in for websockets.connect(url)."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(3600)  # idle → caller's wait_for times out


def test_trade_stream_ingest_parses_and_filters():
    ts = TradeStream(api_key="k")  # no subscribers: _fanout just records _last
    ts._ingest(json.dumps({"type": "trade", "data": [{"s": "NVDA", "p": 5.0, "v": 1, "t": 9}]}))
    assert ts._last["NVDA"]["price"] == 5.0 and ts._last["NVDA"]["symbol"] == "NVDA"
    ts._ingest(json.dumps({"type": "ping"}))  # non-trade ignored
    ts._ingest("not json")                     # malformed ignored, no raise
    assert set(ts._last) == {"NVDA"}


def test_trade_stream_fanout_and_subscribe():
    msg = json.dumps({"type": "trade", "data": [{"s": "AAPL", "p": 200.5, "v": 10, "t": 123}]})
    created: list[_FakeWS] = []

    def fake_connect(url):
        ws = _FakeWS([msg])
        created.append(ws)
        return ws

    async def run():
        ts = TradeStream(api_key="k", symbols=["AAPL"], connect=fake_connect)
        q = await ts.subscribe()
        tick = await asyncio.wait_for(q.get(), timeout=2.0)
        await ts.unsubscribe(q)
        return tick

    tick = asyncio.run(run())
    assert tick["symbol"] == "AAPL" and tick["price"] == 200.5
    assert any('"subscribe"' in s and "AAPL" in s for s in created[0].sent)


def test_trade_stream_dormant_without_key():
    async def run():
        ts = TradeStream(api_key=None, symbols=["AAPL"])
        await ts.subscribe()
        await asyncio.sleep(0.05)  # _run should return immediately
        return ts.connected

    assert asyncio.run(run()) is False


def test_market_stream_endpoint_nokey(monkeypatch):
    monkeypatch.setattr(m, "trade_stream", TradeStream(api_key=None))
    r = TestClient(m.app).get("/market/stream")
    assert r.status_code == 200
    assert "nokey" in r.text


def test_set_watchlist_updates_trade_stream(monkeypatch, tmp_path):
    import max_engine.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / ".maxconfig.json")
    monkeypatch.setattr(m, "market", MarketService(symbols=["AAPL"], api_key=API_KEY, client=_mock_client()))
    ts = TradeStream(api_key=API_KEY, symbols=["AAPL"])
    monkeypatch.setattr(m, "trade_stream", ts)
    TestClient(m.app).put("/market/watchlist", json={"symbols": ["nvda", "amd"]})
    assert ts._symbols == {"NVDA", "AMD"}  # stream re-targeted live
