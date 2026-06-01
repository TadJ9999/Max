"""Tests for web search skill — DDG scraping and search stream."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from max_engine.skills.web_search import SearchResult, ddg_search, _search_stream

# Minimal DDG lite HTML with two results
_DDG_HTML = """
<html><body>
<table>
<tr><td><a class="result-link" href="https://example.com/1">Example One</a></td></tr>
<tr><td class="result-snippet">First result snippet text here.</td></tr>
<tr><td><a class="result-link" href="https://example.com/2">Example Two</a></td></tr>
<tr><td class="result-snippet">Second result snippet text.</td></tr>
</table>
</body></html>
"""

_DDG_EMPTY_HTML = "<html><body><table></table></body></html>"


def _make_request():
    return httpx.Request("GET", "https://lite.duckduckgo.com/lite/?q=test")


@pytest.mark.asyncio
async def test_ddg_search_parses_results(monkeypatch):
    req = _make_request()
    fake_resp = httpx.Response(200, text=_DDG_HTML, request=req)

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return fake_resp

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    results = await ddg_search("test query")
    assert len(results) == 2
    assert results[0].title == "Example One"
    assert results[0].url == "https://example.com/1"
    assert "First result" in results[0].snippet
    assert results[1].title == "Example Two"


@pytest.mark.asyncio
async def test_ddg_search_empty(monkeypatch):
    req = _make_request()
    fake_resp = httpx.Response(200, text=_DDG_EMPTY_HTML, request=req)

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return fake_resp

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    results = await ddg_search("nothing")
    assert results == []


def test_search_result_to_dict():
    r = SearchResult(title="T", url="https://x.com", snippet="S")
    assert r.to_dict() == {"title": "T", "url": "https://x.com", "snippet": "S"}


@pytest.mark.asyncio
async def test_search_stream_no_results(monkeypatch):
    """When ddg_search returns nothing, stream should yield 'No results found.'"""
    async def fake_ddg(query, max_results=6):
        return []

    monkeypatch.setattr("max_engine.skills.web_search.ddg_search", fake_ddg)

    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "ok", "done": False})()
            yield type("C", (), {"text": "", "done": True})()

    chunks = []
    async for c in _search_stream("x", FakeProvider(), "model"):
        chunks.append(c)
    assert any("No results" in c for c in chunks)


@pytest.mark.asyncio
async def test_search_stream_with_results(monkeypatch):
    """When ddg_search returns results, stream should synthesize via provider."""
    fake_results = [
        SearchResult("Title A", "https://a.com", "Snippet A"),
        SearchResult("Title B", "https://b.com", "Snippet B"),
    ]

    async def fake_ddg(query, max_results=6):
        return fake_results

    monkeypatch.setattr("max_engine.skills.web_search.ddg_search", fake_ddg)

    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "Synthesized answer.", "done": False})()
            yield type("C", (), {"text": "", "done": True})()

    chunks = []
    async for c in _search_stream("what is X?", FakeProvider(), "model"):
        chunks.append(c)
    assert "Synthesized answer." in "".join(chunks)


@pytest.mark.asyncio
async def test_search_stream_http_error(monkeypatch):
    """If ddg_search raises, stream should yield an error message."""
    async def bad_ddg(query, max_results=6):
        raise ConnectionError("no internet")

    monkeypatch.setattr("max_engine.skills.web_search.ddg_search", bad_ddg)

    class FakeProvider:
        async def chat(self, model, messages, **kw):
            yield type("C", (), {"text": "ok", "done": False})()

    chunks = []
    async for c in _search_stream("x", FakeProvider(), "model"):
        chunks.append(c)
    assert any("Search error" in c or "error" in c.lower() for c in chunks)
