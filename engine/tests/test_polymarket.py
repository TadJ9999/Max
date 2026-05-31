"""Tests for the Polymarket prediction-market module.

All network calls are mocked via httpx.MockTransport / monkeypatch so
tests run offline. Covers: market parsing, price history, order book,
board aggregation + TTL caching, watchlist round-trip, embed call, endpoints.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from max_engine.polymarket.client import (
    _parse_market,
    fetch_markets,
    fetch_order_book,
    fetch_price_history,
)
from max_engine.polymarket.embedder import _market_text, embed_markets
from max_engine.polymarket.models import Market, OrderBook, Outcome, PricePoint, PolymarketBoard
from max_engine.polymarket.service import PolymarketService


def _run(coro):
    return asyncio.run(coro)

# ---- test fixtures -------------------------------------------------------

MARKET_RAW = {
    "conditionId": "0xabc123",
    "question": "Will the Fed cut rates in 2025?",
    "slug": "fed-rate-cut-2025",
    "category": "Economics",
    "description": "Resolves YES if the Federal Reserve cuts rates at least once.",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.72", "0.28"]',
    "clobTokenIds": '["token_yes", "token_no"]',
    "volume": 500000.0,
    "volume24hr": 12000.0,
    "liquidity": 80000.0,
    "endDate": "2025-12-31T23:59:59Z",
    "active": True,
    "closed": False,
    "image": "https://example.com/image.png",
}

PRICE_HISTORY_RAW = {
    "history": [
        {"t": 1700000000, "p": 0.60},
        {"t": 1700086400, "p": 0.65},
        {"t": 1700172800, "p": 0.72},
    ]
}

ORDER_BOOK_RAW = {
    "market": "0xabc123",
    "asset_id": "token_yes",
    "bids": [{"price": "0.71", "size": "500.0"}, {"price": "0.70", "size": "1000.0"}],
    "asks": [{"price": "0.72", "size": "300.0"}, {"price": "0.73", "size": "800.0"}],
}


# ---- market parsing -------------------------------------------------------


def test_parse_market_basic():
    m = _parse_market(MARKET_RAW)
    assert m is not None
    assert m.condition_id == "0xabc123"
    assert m.question == "Will the Fed cut rates in 2025?"
    assert m.category == "Economics"
    assert len(m.outcomes) == 2
    assert m.outcomes[0].name == "Yes"
    assert abs(m.outcomes[0].price - 0.72) < 1e-6
    assert m.outcomes[0].token_id == "token_yes"
    assert m.outcomes[1].name == "No"
    assert abs(m.outcomes[1].price - 0.28) < 1e-6
    assert m.volume == 500000.0
    assert m.volume_24hr == 12000.0
    assert m.liquidity == 80000.0
    assert m.active is True
    assert m.closed is False


def test_parse_market_with_list_fields():
    """Gamma API sometimes returns outcomes/prices as actual lists (not JSON strings)."""
    raw = {**MARKET_RAW, "outcomes": ["Yes", "No"], "outcomePrices": ["0.60", "0.40"], "clobTokenIds": ["t1", "t2"]}
    m = _parse_market(raw)
    assert m is not None
    assert len(m.outcomes) == 2
    assert abs(m.outcomes[0].price - 0.60) < 1e-6


def test_parse_market_missing_condition_id():
    raw = {**MARKET_RAW}
    del raw["conditionId"]
    m = _parse_market(raw)
    assert m is None


def test_parse_market_yes_price():
    m = _parse_market(MARKET_RAW)
    assert m is not None
    assert abs(m.yes_price - 0.72) < 1e-6


def test_market_to_dict():
    m = _parse_market(MARKET_RAW)
    assert m is not None
    d = m.to_dict()
    assert d["conditionId"] == "0xabc123"
    assert d["yesPrice"] == 0.72
    assert len(d["outcomes"]) == 2
    assert d["volume24hr"] == 12000.0


# ---- price history -------------------------------------------------------


def _make_transport(status: int, body: dict):
    content = json.dumps(body).encode()

    def handler(req):
        return httpx.Response(status, content=content)

    return httpx.MockTransport(handler)


def test_fetch_price_history_success():
    async def run():
        transport = _make_transport(200, PRICE_HISTORY_RAW)
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_price_history(client, "0xabc123", interval="1w")
    points = _run(run())
    assert len(points) == 3
    assert points[0].t == 1700000000
    assert abs(points[0].p - 0.60) < 1e-6
    assert abs(points[2].p - 0.72) < 1e-6


def test_fetch_price_history_http_error():
    async def run():
        transport = _make_transport(500, {})
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_price_history(client, "0xabc123")
    assert _run(run()) == []


# ---- order book ----------------------------------------------------------


def test_fetch_order_book_success():
    async def run():
        transport = _make_transport(200, ORDER_BOOK_RAW)
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_order_book(client, "token_yes")
    book = _run(run())
    assert book is not None
    assert len(book.bids) == 2
    assert len(book.asks) == 2
    assert abs(book.bids[0].price - 0.71) < 1e-6
    assert abs(book.asks[0].price - 0.72) < 1e-6


def test_fetch_order_book_failure():
    async def run():
        transport = _make_transport(404, {})
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_order_book(client, "bad_token")
    assert _run(run()) is None


def test_order_book_to_dict():
    from max_engine.polymarket.models import OrderBook, OrderBookLevel
    book = OrderBook(
        bids=[OrderBookLevel(price=0.71, size=500)],
        asks=[OrderBookLevel(price=0.72, size=300)],
    )
    d = book.to_dict()
    assert d["bids"][0]["price"] == 0.71
    assert d["asks"][0]["price"] == 0.72


# ---- board fetch / caching -----------------------------------------------


def _market_transport(markets: list[dict]):
    body = markets

    def handler(req):
        return httpx.Response(200, content=json.dumps(body).encode())

    return httpx.MockTransport(handler)


def test_service_get_board():
    async def run():
        transport = _market_transport([MARKET_RAW])
        client = httpx.AsyncClient(transport=transport)
        svc = PolymarketService(ttl_seconds=60, client=client)
        board = await svc.get_board()
        await client.aclose()
        return board
    board = _run(run())
    assert len(board.markets) == 1
    assert board.markets[0].condition_id == "0xabc123"


def test_service_ttl_cache():
    """Second get_board call within TTL must not trigger a second HTTP fetch."""
    call_count = 0

    def handler(req):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=json.dumps([MARKET_RAW]).encode())

    async def run():
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = PolymarketService(ttl_seconds=60, client=client)
        await svc.get_board()
        await svc.get_board()
        await client.aclose()

    _run(run())
    assert call_count == 1  # second call served from cache


def test_service_force_refresh():
    call_count = 0

    def handler(req):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=json.dumps([MARKET_RAW]).encode())

    async def run():
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = PolymarketService(ttl_seconds=60, client=client)
        await svc.refresh()
        await svc.refresh(force=True)
        await client.aclose()

    _run(run())
    assert call_count == 2


# ---- watchlist -----------------------------------------------------------


def test_watchlist_round_trip():
    svc = PolymarketService()
    ids = svc.set_watchlist(["0xaaa", "0xbbb", "0xaaa"])  # dedup
    assert ids == ["0xaaa", "0xbbb"]
    assert svc.get_watchlist() == ["0xaaa", "0xbbb"]


def test_watchlist_strip_blanks():
    svc = PolymarketService()
    ids = svc.set_watchlist(["  0xaaa  ", "", "0xbbb"])
    assert "0xaaa" in ids
    assert "" not in ids


# ---- embedder ------------------------------------------------------------


def test_market_text_format():
    m = _parse_market(MARKET_RAW)
    assert m is not None
    text = _market_text(m)
    assert "Will the Fed cut rates" in text
    assert "Yes probability" in text or "72.0%" in text
    assert "Economics" in text


def test_embed_markets_calls_store():
    m = _parse_market(MARKET_RAW)
    assert m is not None

    mock_store = MagicMock()
    mock_store.upsert = MagicMock(return_value=1)
    mock_store.purge_older_than = MagicMock(return_value=0)

    async def run():
        with patch("max_engine.polymarket.embedder.embed_texts", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [[0.1] * 768]
            return await embed_markets([m], mock_store)

    n = _run(run())
    assert n == 1
    mock_store.upsert.assert_called_once()
    items = mock_store.upsert.call_args[0][0]
    assert items[0]["kind"] == "polymarket"
    assert items[0]["ref"] == "polymarket:0xabc123"


def test_embed_markets_empty_embeddings():
    m = _parse_market(MARKET_RAW)
    assert m is not None
    mock_store = MagicMock()

    async def run():
        with patch("max_engine.polymarket.embedder.embed_texts", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = []  # Ollama unavailable
            return await embed_markets([m], mock_store)

    n = _run(run())
    assert n == 0
    mock_store.upsert.assert_not_called()


def test_embed_markets_no_store():
    m = _parse_market(MARKET_RAW)
    assert m is not None
    n = _run(embed_markets([m], None))  # type: ignore
    assert n == 0


# ---- endpoints (FastAPI TestClient) -------------------------------------


@pytest.fixture()
def test_app():
    """Minimal FastAPI app with the real endpoint wired in, but all I/O mocked."""
    from fastapi.testclient import TestClient
    from max_engine.main import app

    return TestClient(app)


def _mock_board():
    from datetime import datetime, timezone
    from max_engine.polymarket.models import PolymarketBoard
    m = _parse_market(MARKET_RAW)
    return PolymarketBoard(updated=datetime.now(timezone.utc), markets=[m])


def test_endpoint_board(test_app):
    with patch.object(
        __import__("max_engine.main", fromlist=["polymarket_svc"]).polymarket_svc,
        "get_board",
        new_callable=AsyncMock,
        return_value=_mock_board(),
    ):
        r = test_app.get("/polymarket/board")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["markets"][0]["conditionId"] == "0xabc123"


def test_endpoint_sources(test_app):
    r = test_app.get("/polymarket/sources")
    assert r.status_code == 200
    data = r.json()
    assert "gamma" in data
    assert data["keyRequired"] is False


def test_endpoint_watchlist_put(test_app):
    r = test_app.put(
        "/polymarket/watchlist",
        json={"condition_ids": ["0xaaa", "0xbbb"]},
    )
    assert r.status_code == 200
    assert "watchlist" in r.json()


def test_endpoint_prices(test_app):
    points = [PricePoint(t=1700000000, p=0.65), PricePoint(t=1700086400, p=0.70)]
    with patch.object(
        __import__("max_engine.main", fromlist=["polymarket_svc"]).polymarket_svc,
        "get_price_history",
        new_callable=AsyncMock,
        return_value=points,
    ):
        r = test_app.get("/polymarket/prices/0xabc123?interval=1w")
    assert r.status_code == 200
    data = r.json()
    assert data["conditionId"] == "0xabc123"
    assert len(data["history"]) == 2


def test_endpoint_order_book(test_app):
    from max_engine.polymarket.models import OrderBook, OrderBookLevel
    book = OrderBook(
        bids=[OrderBookLevel(price=0.71, size=500)],
        asks=[OrderBookLevel(price=0.72, size=300)],
    )
    with patch.object(
        __import__("max_engine.main", fromlist=["polymarket_svc"]).polymarket_svc,
        "get_order_book",
        new_callable=AsyncMock,
        return_value=book,
    ):
        r = test_app.get("/polymarket/order-book/token_yes")
    assert r.status_code == 200
    data = r.json()
    assert len(data["bids"]) == 1
    assert data["bids"][0]["price"] == 0.71
