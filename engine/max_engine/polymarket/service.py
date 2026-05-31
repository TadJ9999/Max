"""Polymarket service — fetch prediction markets, cache them, and embed into Apollo.

Mirrors the MarketService pattern: async lock, TTL cache, watchlist mutation.
The board caches top-volume active markets for ``ttl_seconds`` (default 120s).
Price history is cached per condition-id for 1 hour.
No API key is required — Polymarket's public APIs are open read access.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic

import httpx

from .client import (
    GAMMA_BASE,
    _UA,
    fetch_markets,
    fetch_order_book,
    fetch_price_history,
)
from .models import Market, OrderBook, PolymarketBoard, PricePoint

_BOARD_LIMIT = 50  # top markets to fetch for the main board


class PolymarketService:
    def __init__(
        self,
        *,
        watchlist: list[str] | None = None,
        ttl_seconds: int = 120,
        embed_enabled: bool = True,
        categories: list[str] | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._watchlist: list[str] = list(watchlist or [])
        self.ttl_seconds = ttl_seconds
        self.embed_enabled = embed_enabled
        self._categories = list(categories or [])
        self._client = client

        self._lock = asyncio.Lock()
        self._board: PolymarketBoard | None = None
        self._fetched_at: float | None = None

        # Per-condition price history cache: condition_id -> (points, fetched_at)
        self._history_cache: dict[str, tuple[list[PricePoint], float]] = {}
        self._history_ttl = 3600  # 1 hour

    # ---- internal helpers ------------------------------------------------

    def _fresh(self) -> bool:
        return (
            self._board is not None
            and self._fetched_at is not None
            and (monotonic() - self._fetched_at) < self.ttl_seconds
        )

    def _make_client(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=15.0, headers={"user-agent": _UA}), True

    # ---- board fetch / cache ---------------------------------------------

    async def refresh(self, *, force: bool = False) -> None:
        async with self._lock:
            if not force and self._fresh():
                return
            client, owns = self._make_client()
            try:
                markets = await fetch_markets(client, limit=_BOARD_LIMIT)
            finally:
                if owns:
                    await client.aclose()
            self._board = PolymarketBoard(
                updated=datetime.now(timezone.utc), markets=markets
            )
            self._fetched_at = monotonic()

    async def get_board(self) -> PolymarketBoard:
        await self.refresh()
        assert self._board is not None
        return self._board

    async def get_markets(
        self,
        *,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Market]:
        """Fetch markets (optionally filtered by category) directly from Gamma API."""
        client, owns = self._make_client()
        try:
            return await fetch_markets(client, category=category, limit=limit, offset=offset)
        finally:
            if owns:
                await client.aclose()

    async def get_watchlist_markets(self) -> list[Market]:
        """Fetch markets for condition IDs in the user watchlist."""
        if not self._watchlist:
            return []
        client, owns = self._make_client()
        try:
            all_markets: list[Market] = []
            for cid in self._watchlist:
                try:
                    resp = await client.get(
                        f"{GAMMA_BASE}/markets",
                        params={"conditionIds": cid},
                        headers={"user-agent": _UA},
                    )
                    if resp.status_code < 400:
                        data = resp.json()
                        items = data if isinstance(data, list) else data.get("data", [])
                        from .client import _parse_market
                        for item in items:
                            m = _parse_market(item)
                            if m is not None:
                                all_markets.append(m)
                except httpx.HTTPError:
                    continue
            return all_markets
        finally:
            if owns:
                await client.aclose()

    # ---- price history ---------------------------------------------------

    async def get_price_history(
        self, condition_id: str, *, interval: str = "1w"
    ) -> list[PricePoint]:
        cache_key = f"{condition_id}:{interval}"
        cached = self._history_cache.get(cache_key)
        if cached is not None and (monotonic() - cached[1]) < self._history_ttl:
            return cached[0]

        client, owns = self._make_client()
        try:
            points = await fetch_price_history(client, condition_id, interval=interval)
        finally:
            if owns:
                await client.aclose()

        self._history_cache[cache_key] = (points, monotonic())
        return points

    # ---- order book ------------------------------------------------------

    async def get_order_book(self, token_id: str) -> OrderBook | None:
        client, owns = self._make_client()
        try:
            return await fetch_order_book(client, token_id)
        finally:
            if owns:
                await client.aclose()

    # ---- watchlist -------------------------------------------------------

    def get_watchlist(self) -> list[str]:
        return list(self._watchlist)

    def set_watchlist(self, condition_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for cid in condition_ids:
            cid = cid.strip()
            if cid and cid not in seen:
                seen.add(cid)
                cleaned.append(cid)
        self._watchlist = cleaned
        return list(self._watchlist)

    # ---- source info -----------------------------------------------------

    def sources(self, *, embedded_count: int = 0) -> dict:
        return {
            "gamma": GAMMA_BASE,
            "clob": "https://clob.polymarket.com",
            "keyRequired": False,
            "watchlist": self._watchlist,
            "ttlSeconds": self.ttl_seconds,
            "embedEnabled": self.embed_enabled,
            "embeddedCount": embedded_count,
        }
