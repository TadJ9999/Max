"""OSINT service — fetch, merge, cache, and serve the news heat map.

Pulls GDELT + RSS, dedupes, scores per-country heat, and caches the result for a
TTL (GDELT refreshes ~every 15 min, so hammering it buys nothing). One in-flight
refresh at a time via an async lock. An ``httpx.AsyncClient`` can be injected for
tests; otherwise one is created per refresh.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from time import monotonic

import httpx

from .gdelt import DEFAULT_QUERY, fetch_gdelt
from .models import Article, Heatmap
from .rss import DEFAULT_FEEDS, fetch_rss
from .score import score_countries
from .severity import classify

_UA = "MaxEngine-OSINT/0.1 (+local; news heat map)"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class OsintService:
    def __init__(
        self,
        *,
        feeds: list[str] | None = None,
        query: str = DEFAULT_QUERY,
        timespan: str = "24h",
        max_records: int = 250,
        ttl_seconds: int = 600,
        client: httpx.AsyncClient | None = None,
        gdelt_enabled: bool = True,
        rss_enabled: bool = True,
        tone_signal: bool = False,
    ):
        self.feeds = feeds or DEFAULT_FEEDS
        self.query = query
        self.timespan = timespan
        self.max_records = max_records
        self.ttl_seconds = ttl_seconds
        self._client = client
        self.gdelt_enabled = gdelt_enabled
        self.rss_enabled = rss_enabled
        self.tone_signal = tone_signal

        self._lock = asyncio.Lock()
        self._articles: list[Article] = []
        self._heatmap: Heatmap | None = None
        self._fetched_at: float | None = None

    # ---- fetch / cache --------------------------------------------------

    def _fresh(self) -> bool:
        return (
            self._heatmap is not None
            and self._fetched_at is not None
            and (monotonic() - self._fetched_at) < self.ttl_seconds
        )

    @staticmethod
    def _dedupe(articles: list[Article]) -> list[Article]:
        seen_urls: set[str] = set()
        seen_titles: set[tuple[str, str]] = set()
        out: list[Article] = []
        for art in articles:
            url_key = art.url.split("?", 1)[0].rstrip("/")
            title_key = (art.domain, art.title.strip().lower())
            if url_key in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url_key)
            seen_titles.add(title_key)
            out.append(art)
        return out

    async def refresh(self, *, force: bool = False) -> None:
        async with self._lock:
            if not force and self._fresh():
                return
            owns = self._client is None
            client = self._client or httpx.AsyncClient(timeout=20.0, headers={"user-agent": _UA})
            async def _empty() -> list:
                return []

            try:
                gdelt_coro = (
                    fetch_gdelt(
                        client,
                        query=self.query,
                        timespan=self.timespan,
                        max_records=self.max_records,
                    ) if self.gdelt_enabled else _empty()
                )
                rss_coro = fetch_rss(client, self.feeds) if self.rss_enabled else _empty()
                results = await asyncio.gather(gdelt_coro, rss_coro, return_exceptions=True)
                gdelt = results[0] if not isinstance(results[0], BaseException) else []
                rss = results[1] if not isinstance(results[1], BaseException) else []
            finally:
                if owns:
                    await client.aclose()

            articles = self._dedupe([*gdelt, *rss])
            for art in articles:
                art.severity = classify(art.title)
            self._articles = articles
            self._heatmap = Heatmap(
                updated=datetime.now(timezone.utc),
                countries=score_countries(articles, use_tone=self.tone_signal),
                total_articles=len(articles),
            )
            self._fetched_at = monotonic()

    # ---- queries --------------------------------------------------------

    async def get_heatmap(self, domains: set[str] | None = None) -> Heatmap:
        await self.refresh()
        assert self._heatmap is not None
        if not domains:
            return self._heatmap
        # Re-score from the cached article set, keeping only the allowed domains.
        # Cheap (in-memory) so per-source domain toggles stay snappy without a refetch.
        subset = [a for a in self._articles if a.domain in domains]
        return Heatmap(
            updated=self._heatmap.updated,
            countries=score_countries(subset, use_tone=self.tone_signal),
            total_articles=len(subset),
        )

    async def get_articles(
        self,
        iso: str | None = None,
        limit: int = 50,
        domains: set[str] | None = None,
    ) -> list[Article]:
        await self.refresh()
        items = self._articles
        if iso:
            iso = iso.upper()
            items = [a for a in items if a.iso == iso]
        if domains:
            items = [a for a in items if a.domain in domains]
        # Newest first; undated items sink to the bottom.
        items = sorted(items, key=lambda a: a.published or _EPOCH, reverse=True)
        return items[: max(1, limit)]

    async def get_domains(self) -> list[dict]:
        """Distinct source domains in the current article set, with article counts.

        Feeds the OSINT view's per-source toggle list. Newest data wins via the
        same TTL cache as everything else."""
        await self.refresh()
        counts: dict[str, dict] = {}
        for a in self._articles:
            if not a.domain:
                continue
            d = counts.setdefault(
                a.domain, {"domain": a.domain, "origin": a.origin, "count": 0}
            )
            d["count"] += 1
        return sorted(counts.values(), key=lambda d: (-d["count"], d["domain"]))

    async def get_timeline(self, frames: int = 24, window_hours: float = 24.0) -> dict:
        """Replay the last ``window_hours`` as ``frames`` heat snapshots.

        Frame *i* is scored over only the articles published at or before that
        frame's timestamp, with recency decay anchored at that moment — so
        dragging the scrubber replays how the heat actually built up. Reuses the
        same :func:`score_countries` model as the live map."""
        await self.refresh()
        frames = max(2, min(48, frames))
        window_hours = max(1.0, min(72.0, window_hours))
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=window_hours)
        step = (now - start) / (frames - 1)
        out: list[dict] = []
        for i in range(frames):
            at = start + step * i
            subset = [a for a in self._articles if (a.published or _EPOCH) <= at]
            countries = score_countries(subset, now=at, use_tone=self.tone_signal)
            out.append(
                {
                    "at": at.isoformat(),
                    "totalArticles": len(subset),
                    "countries": [c.to_dict() for c in countries],
                }
            )
        return {"frames": out, "windowHours": window_hours}

    def sources(self) -> dict:
        """Static description of where the data comes from (for the UI)."""
        return {
            "gdelt": {"query": self.query, "timespan": self.timespan},
            "feeds": self.feeds,
            "ttlSeconds": self.ttl_seconds,
        }
