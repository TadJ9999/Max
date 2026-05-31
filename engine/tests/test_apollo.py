"""Apollo tests — payload aggregation + the report/predict streaming endpoints.

The OSINT and Market services are replaced with light duck-typed fakes, and the
provider is mocked, so nothing hits the network or a real model.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.apollo.service import ApolloService
from max_engine.market.models import MarketBoard, Quote
from max_engine.osint.models import Article, CountryStat, Heatmap
from max_engine.providers.base import ChatChunk

NOW = datetime(2026, 5, 30, tzinfo=timezone.utc)


class _FakeOsint:
    def __init__(self, articles, heatmap):
        self._articles = articles
        self._heatmap = heatmap

    async def get_articles(self, iso=None, limit=50):
        return self._articles[:limit]

    async def get_heatmap(self):
        return self._heatmap


class _FakeMarket:
    def __init__(self, board, news):
        self._board = board
        self._news = news

    async def get_board(self):
        return self._board

    async def get_news(self, count=8):
        return self._news[:count]


class _FakeProvider:
    async def chat(self, model, messages, **params):
        yield ChatChunk(text="hello", done=False)
        yield ChatChunk(text="", done=True)


def _svc():
    articles = [
        Article(title="Critical war", url="http://a/1", domain="reuters.com",
                origin="rss", country="Ukraine", iso="UKR", severity=3),
        Article(title="High tension", url="http://a/2", domain="bbc.com",
                origin="rss", country="Taiwan", iso="TWN", severity=2),
        Article(title="Minor note", url="http://a/3", domain="x.com",
                origin="rss", severity=0),
    ]
    heatmap = Heatmap(
        updated=NOW,
        countries=[
            CountryStat(iso="UKR", name="Ukraine", intensity=0.9,
                        article_count=12, sources=5, severity=3),
            CountryStat(iso="TWN", name="Taiwan", intensity=0.4,
                        article_count=4, sources=3, severity=2),
        ],
        total_articles=16,
    )
    board = MarketBoard(updated=NOW, quotes=[Quote(symbol="AAPL", price=191.0, change_pct=1.3)])
    news = [{"headline": "Stocks up", "source": "Reuters", "summary": "x", "url": "u"}]
    return ApolloService(osint=_FakeOsint(articles, heatmap), market=_FakeMarket(board, news))


# ---- payload aggregation ------------------------------------------------


def test_osint_payload_filters_criticals_and_ranks_hotspots():
    import asyncio

    p = asyncio.run(_svc().osint_payload())
    titles = [c["title"] for c in p["criticals"]]
    assert titles == ["Critical war", "High tension"]  # severity >= 2 only
    assert p["hotspots"][0]["iso"] == "UKR"  # highest intensity first
    assert p["totalArticles"] == 16


def test_market_payload_has_board_stats_news():
    import asyncio

    p = asyncio.run(_svc().market_payload())
    assert p["board"]["count"] == 1
    assert p["stats"]["up"] == 1
    assert p["news"][0]["headline"] == "Stocks up"


def test_combined_payload_merges_both():
    import asyncio

    p = asyncio.run(_svc().combined_payload())
    assert "osint" in p and "market" in p
    assert p["osint"]["criticals"][0]["title"] == "Critical war"


# ---- endpoints (provider mocked) ----------------------------------------


def test_apollo_endpoints_stream(monkeypatch):
    monkeypatch.setattr(m, "apollo", _svc())
    monkeypatch.setattr(m, "build_provider", lambda name, cfg: _FakeProvider())
    c = TestClient(m.app)
    for path in ("/apollo/osint-report", "/apollo/market-report", "/apollo/predict"):
        r = c.post(path)
        assert r.status_code == 200, path
        assert "hello" in r.text, path
