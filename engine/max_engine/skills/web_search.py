"""Web search skill — DuckDuckGo lite scraper + AI synthesis."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from ..capabilities.interface import Capability

_DDG_URL = "https://lite.duckduckgo.com/lite/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


async def ddg_search(query: str, max_results: int = 6) -> list[SearchResult]:
    """Scrape DuckDuckGo lite and return structured results."""
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=12) as client:
        resp = await client.get(_DDG_URL, params={"q": query})
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[SearchResult] = []

    links = soup.find_all("a", class_="result-link")
    snippets = soup.find_all("td", class_="result-snippet")

    for link, snip in zip(links, snippets):
        title = link.get_text(strip=True)
        url = link.get("href", "")
        snippet = re.sub(r"\s+", " ", snip.get_text(strip=True))
        if title and url and url.startswith("http"):
            results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break

    return results


class WebSearchCapability(Capability):
    name = "web_search"
    description = "Search the web with DuckDuckGo and synthesise the results with AI."
    domains = ["web_search"]

    def __init__(self, provider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def invoke(self, query: str, context: dict | None = None) -> AsyncIterator[str]:
        return _search_stream(query, self._provider, self._model)

    def status(self) -> dict:
        return {"available": True, "connected": True, "provider": "DuckDuckGo"}


async def _search_stream(
    query: str,
    provider,
    model: str,
    history: list[dict] | None = None,
) -> AsyncIterator[str]:
    from ..prompts import web_search_messages

    try:
        results = await ddg_search(query)
    except Exception as exc:
        yield f"Search error: {exc}"
        return

    if not results:
        yield "No results found."
        return

    results_json = json.dumps([r.to_dict() for r in results], indent=2)
    messages = web_search_messages(query, results_json, history or [])

    async for chunk in provider.chat(model, messages, _feature="skills"):
        if not chunk.done:
            yield chunk.text
