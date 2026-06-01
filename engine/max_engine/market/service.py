"""Market service — fetch the live watchlist board, cache it for a short TTL.

Pulls a quote per watchlist symbol from Finnhub concurrently and caches the board
for a TTL (the UI polls ~every 10s; the cache keeps us inside the free-tier rate
limit even with the window open). One in-flight refresh at a time via an async
lock. An ``httpx.AsyncClient`` can be injected for tests; otherwise one is created
per refresh. With no API key the board is empty (graceful offline state).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic

import httpx

from .finnhub import DEFAULT_WATCHLIST, fetch_market_news, fetch_quote
from .models import MarketBoard, Quote

_UA = "MaxEngine-Market/0.1 (+local; live stock board)"


def board_digest(board: MarketBoard) -> dict:
    """Computed market breadth for the AI report: up/down counts, average move,
    and the top movers. Pure function over a board snapshot (no I/O)."""
    qs = board.quotes
    if not qs:
        return {"count": 0, "up": 0, "down": 0, "flat": 0, "avgChangePct": 0.0,
                "gainers": [], "losers": []}
    by_chg = sorted(qs, key=lambda q: q.change_pct, reverse=True)
    return {
        "count": len(qs),
        "up": sum(1 for q in qs if q.change_pct > 0),
        "down": sum(1 for q in qs if q.change_pct < 0),
        "flat": sum(1 for q in qs if q.change_pct == 0),
        "avgChangePct": round(sum(q.change_pct for q in qs) / len(qs), 3),
        "gainers": [q.to_dict() for q in by_chg[:3]],
        "losers": [q.to_dict() for q in reversed(by_chg[-3:])],
    }


class MarketService:
    def __init__(
        self,
        *,
        symbols: list[str] | None = None,
        api_key: str | None = None,
        ttl_seconds: int = 10,
        client: httpx.AsyncClient | None = None,
    ):
        self._symbols = [s.strip().upper() for s in (symbols or DEFAULT_WATCHLIST) if s.strip()]
        self.api_key = api_key
        self.ttl_seconds = ttl_seconds
        self._client = client

        self._lock = asyncio.Lock()
        self._board: MarketBoard | None = None
        self._fetched_at: float | None = None

        # Market news is a separate, slower-moving feed with its own cache window.
        self.news_ttl_seconds = 300
        self._news: list[dict] = []
        self._news_at: float | None = None

    # ---- fetch / cache --------------------------------------------------

    def _fresh(self) -> bool:
        return (
            self._board is not None
            and self._fetched_at is not None
            and (monotonic() - self._fetched_at) < self.ttl_seconds
        )

    async def refresh(self, *, force: bool = False) -> None:
        async with self._lock:
            if not force and self._fresh():
                return
            # No key -> empty board, but still "fresh" so we don't spin on every poll.
            if not self.api_key:
                self._board = MarketBoard(updated=datetime.now(timezone.utc), quotes=[])
                self._fetched_at = monotonic()
                return

            owns = self._client is None
            client = self._client or httpx.AsyncClient(timeout=15.0, headers={"user-agent": _UA})
            try:
                # with_name=False: skip /stock/profile2 calls to stay within
                # Finnhub's free-tier rate limit (60 req/min). Names fall back
                # to the static _NAME_HINTS dict; the budget freed up here lets
                # candle requests succeed when the user opens a ticker modal.
                results = await asyncio.gather(
                    *(fetch_quote(client, sym, self.api_key, with_name=False) for sym in self._symbols)
                )
            finally:
                if owns:
                    await client.aclose()

            quotes: list[Quote] = [q for q in results if q is not None]
            self._board = MarketBoard(updated=datetime.now(timezone.utc), quotes=quotes)
            self._fetched_at = monotonic()

    # ---- queries --------------------------------------------------------

    async def get_board(self) -> MarketBoard:
        await self.refresh()
        assert self._board is not None
        return self._board

    async def get_news(self, count: int = 8) -> list[dict]:
        """Recent general market headlines, cached for ``news_ttl_seconds``.
        Empty list when no API key or the fetch fails (never fatal)."""
        if not self.api_key:
            return []
        if (
            self._news_at is not None
            and (monotonic() - self._news_at) < self.news_ttl_seconds
        ):
            return self._news[:count]

        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0, headers={"user-agent": _UA})
        try:
            news = await fetch_market_news(client, self.api_key, count=max(count, 8))
        finally:
            if owns:
                await client.aclose()
        self._news = news
        self._news_at = monotonic()
        return self._news[:count]

    def get_watchlist(self) -> list[str]:
        return list(self._symbols)

    def set_watchlist(self, symbols: list[str]) -> list[str]:
        """Replace the watchlist (dedup, upper, drop blanks) and invalidate the cache."""
        seen: set[str] = set()
        cleaned: list[str] = []
        for s in symbols:
            sym = s.strip().upper()
            if sym and sym not in seen:
                seen.add(sym)
                cleaned.append(sym)
        self._symbols = cleaned
        # Force a re-fetch on the next get_board for the new set.
        self._board = None
        self._fetched_at = None
        return list(self._symbols)

    def sources(self) -> dict:
        """Static description of where the data comes from (for the UI)."""
        return {
            "provider": "finnhub",
            "key_set": bool(self.api_key),
            "watchlist": list(self._symbols),
            "ttlSeconds": self.ttl_seconds,
        }
