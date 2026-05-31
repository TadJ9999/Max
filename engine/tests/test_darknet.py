"""Tests for the Shadow Net / Tor dark-web module (Phase 15).

All network calls are mocked so tests run fully offline.
Covers: TorStatus model, FetchResult model, link rewriting in fetcher,
service port-check logic, search result parsing, and HTTP endpoints.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from max_engine.darknet.models import FetchResult, SearchResult, TorStatus
from max_engine.darknet.fetcher import fetch_url
from max_engine.darknet.service import TorService, _parse_ahmia, _port_open


def _run(coro):
    return asyncio.run(coro)


# ---- model tests ---------------------------------------------------------


def test_tor_status_defaults():
    s = TorStatus(running=False)
    assert s.bootstrapped == 0
    assert s.circuit_established is False
    assert s.exit_ip is None
    assert s.circuit_age_seconds == 0
    assert s.socks_port == 9050


def test_tor_status_connected():
    s = TorStatus(
        running=True,
        bootstrapped=100,
        circuit_established=True,
        exit_ip="1.2.3.4",
        circuit_age_seconds=120,
    )
    assert s.circuit_established is True
    assert s.exit_ip == "1.2.3.4"


def test_fetch_result_defaults():
    r = FetchResult(url="http://example.onion", html="<h1>hi</h1>")
    assert r.status_code == 200
    assert r.is_onion is False
    assert r.fetch_time_ms == 0


def test_search_result():
    r = SearchResult(title="Dark Wiki", url="http://abc.onion", is_onion=True)
    assert r.is_onion is True
    assert r.description is None


# ---- port-open helper ----------------------------------------------------


def test_port_open_closed():
    # Port 19999 is almost certainly not open on any test machine
    assert _port_open(19999) is False


# ---- fetcher link rewriting ----------------------------------------------


_SAMPLE_HTML = """
<html><head><title>Test Page</title></head>
<body>
  <a href="/page2">Relative</a>
  <a href="http://other.onion/deep">Absolute onion</a>
  <a href="#anchor">Anchor</a>
  <script>alert('xss')</script>
</body></html>
"""


def test_fetch_url_rewrites_links():
    """Links should be rewritten to ?url=<absolute>, scripts removed."""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = _SAMPLE_HTML.encode()
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}

    async def fake_fetch(*args, **kwargs):
        return mock_resp

    with patch("max_engine.darknet.fetcher.make_tor_client") as mk:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mk.return_value = mock_client

        result = _run(fetch_url("http://test.onion/page1"))

    assert result.title == "Test Page"
    assert result.is_onion is True
    # Relative link should be absolutised and wrapped
    assert "?url=http://test.onion/page2" in result.html
    # Absolute onion link should be wrapped
    assert "?url=http://other.onion/deep" in result.html
    # Anchor links should NOT be rewritten
    assert 'href="#anchor"' in result.html
    # Script tags should be removed
    assert "<script>" not in result.html
    assert "alert" not in result.html


def test_fetch_url_non_html_content():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"binary data here"
    mock_resp.headers = {"content-type": "application/octet-stream"}

    with patch("max_engine.darknet.fetcher.make_tor_client") as mk:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mk.return_value = mock_client

        result = _run(fetch_url("http://example.com/file.bin"))

    assert "<pre" in result.html
    assert result.title is None


# ---- service: bootstrap_info fallback -----------------------------------


def test_service_bootstrap_fallback_when_control_unreachable():
    """When the control port is not available, bootstrap_info should return 100,True
    (meaning we infer success from the SOCKS port being open)."""
    svc = TorService()
    with patch("max_engine.darknet.service._port_open", return_value=True):
        # stem is expected to raise (control port unavailable)
        with patch.dict("sys.modules", {"stem": None, "stem.control": None}):
            pct, circuit = svc._bootstrap_info()
    # Falls back to assuming 100 % / established when control port unavailable
    assert pct == 100
    assert circuit is True


def test_service_status_not_running():
    svc = TorService()
    with patch("max_engine.darknet.service._port_open", return_value=False):
        status = _run(svc.status())
    assert status.running is False
    assert status.circuit_established is False


# ---- search result parser ------------------------------------------------


_AHMIA_HTML = """
<html><body>
  <li class="result">
    <a href="/search/redirect?redirect_url=http://abc123.onion/page">Dark Wiki</a>
    <p>A collection of onion links.</p>
  </li>
  <li class="result">
    <a href="http://clearnet.example.com">Clearnet site</a>
  </li>
</body></html>
"""


def test_parse_ahmia_extracts_results():
    results = _parse_ahmia(_AHMIA_HTML)
    assert len(results) == 2
    assert results[0].title == "Dark Wiki"
    assert results[0].url == "http://abc123.onion/page"
    assert results[0].is_onion is True
    assert results[1].is_onion is False


def test_parse_ahmia_empty():
    assert _parse_ahmia("<html><body></body></html>") == []


# ---- endpoint smoke tests ------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from max_engine.main import app
    return TestClient(app)


def test_dark_status_endpoint(client):
    # With Tor not running, endpoint should return running=False
    with patch("max_engine.main.dark_svc") as mock_svc:
        mock_svc.status = AsyncMock(return_value=TorStatus(running=False))
        resp = client.get("/dark/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False


def test_dark_new_circuit_endpoint(client):
    with patch("max_engine.main.dark_svc") as mock_svc:
        mock_svc.new_circuit = AsyncMock()
        resp = client.post("/dark/new-circuit")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_dark_search_endpoint(client):
    results = [SearchResult(title="Hidden Wiki", url="http://abc.onion", is_onion=True)]
    with patch("max_engine.main.dark_svc") as mock_svc:
        mock_svc.search = AsyncMock(return_value=results)
        resp = client.get("/dark/search?q=wiki")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["title"] == "Hidden Wiki"
