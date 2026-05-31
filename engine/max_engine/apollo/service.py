"""Apollo service — aggregate data, and read/write the vector memory.

Two responsibilities:
  * shape compact JSON payloads from the OSINT + Market services (no model calls);
  * Ingest = embed the high-signal items and write them to the sqlite-vec store
    (then purge >24h); Predict = embed a query and recall related memories.

All embedding/store work is best-effort: if Ollama or the store is unavailable
the report/prediction still streams, just without memory.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from ..market import MarketService, board_digest
from ..osint import OsintService
from .embed import DEFAULT_EMBED_MODEL, embed_texts
from .store import VectorStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApolloService:
    def __init__(
        self,
        *,
        osint: OsintService,
        market: MarketService,
        store: VectorStore | None = None,
        embed_model: str = DEFAULT_EMBED_MODEL,
        base_url: str = "http://127.0.0.1:11434",
        ttl_seconds: int = 86_400,
        retrieve_k: int = 6,
    ):
        self._osint = osint
        self._market = market
        self._store = store
        self._embed_model = embed_model
        self._base_url = base_url
        self._ttl = ttl_seconds
        self._k = retrieve_k

    # ---- data payloads (no I/O to the model) ---------------------------

    async def osint_payload(self, *, criticals: int = 18, hotspots: int = 8) -> dict:
        articles = await self._osint.get_articles(limit=250)
        crit = [a for a in articles if a.severity >= 2][:criticals]
        if not crit:
            crit = articles[:criticals]
        heatmap = await self._osint.get_heatmap()
        top = sorted(heatmap.countries, key=lambda c: c.intensity, reverse=True)[:hotspots]
        sev_counts: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        for a in articles:
            sev_counts[a.severity] = sev_counts.get(a.severity, 0) + 1
        return {
            "generatedAt": _now_iso(),
            "totalArticles": heatmap.total_articles,
            "severityCounts": sev_counts,
            "hotspots": [c.to_dict() for c in top],
            "criticals": [
                {
                    "title": a.title,
                    "country": a.country,
                    "iso": a.iso,
                    "severity": a.severity,
                    "severityLabel": a.to_dict()["severityLabel"],
                    "domain": a.domain,
                    "published": a.published.isoformat() if a.published else None,
                    "summary": a.summary,
                    "url": a.url,
                }
                for a in crit
            ],
        }

    async def market_payload(self) -> dict:
        board = await self._market.get_board()
        news = await self._market.get_news(count=8)
        return {
            "generatedAt": _now_iso(),
            "board": board.to_dict(),
            "stats": board_digest(board),
            "news": news,
        }

    async def combined_payload(self) -> dict:
        return {
            "generatedAt": _now_iso(),
            "osint": await self.osint_payload(),
            "market": await self.market_payload(),
        }

    # ---- vector memory: embed + write ----------------------------------

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return await embed_texts(texts, model=self._embed_model, base_url=self._base_url)

    async def _purge(self) -> None:
        if self._store:
            await asyncio.to_thread(self._store.purge_older_than, self._ttl)

    async def ingest_osint(self, payload: dict) -> int:
        """Embed the critical headlines and write them to memory (dedupe by URL)."""
        if not self._store:
            return 0
        crits = [a for a in payload.get("criticals", []) if a.get("url")]
        docs = [
            f"{a['title']} — {a.get('country') or 'global'}. {a.get('summary') or ''}".strip()
            for a in crits
        ]
        embs = await self._embed(docs)
        if not embs:
            await self._purge()
            return 0
        now = int(time.time())
        items = [
            {
                "kind": "osint",
                "ref": a["url"],
                "ts": now,
                "title": a["title"],
                "body": doc,
                "meta": {"country": a.get("country"), "severity": a.get("severity")},
                "embedding": emb,
            }
            for a, doc, emb in zip(crits, docs, embs, strict=False)
        ]
        written = await asyncio.to_thread(self._store.upsert, items)
        await self._purge()
        return written

    async def ingest_market(self, payload: dict) -> int:
        """Embed a market-snapshot summary + headlines and write them to memory."""
        if not self._store:
            return 0
        stats = payload.get("stats", {})
        gainers = ", ".join(
            f"{g['symbol']} {g['changePct']:+.2f}%" for g in stats.get("gainers", [])
        )
        losers = ", ".join(
            f"{x['symbol']} {x['changePct']:+.2f}%" for x in stats.get("losers", [])
        )
        snapshot = (
            f"Market breadth: {stats.get('up', 0)} up / {stats.get('down', 0)} down, "
            f"avg {stats.get('avgChangePct', 0)}%. Gainers: {gainers}. Losers: {losers}."
        )
        now = int(time.time())
        docs = [snapshot]
        refs = [f"market:snapshot:{now // 600}"]  # one per 10-min bucket
        titles = ["Market snapshot"]
        for h in payload.get("news", [])[:6]:
            if h.get("headline"):
                docs.append(h["headline"])
                refs.append("news:" + (h.get("url") or h["headline"][:80]))
                titles.append(h["headline"][:80])
        embs = await self._embed(docs)
        if not embs:
            await self._purge()
            return 0
        items = [
            {"kind": "market", "ref": ref, "ts": now, "title": title,
             "body": doc, "meta": {}, "embedding": emb}
            for ref, title, doc, emb in zip(refs, titles, docs, embs, strict=False)
        ]
        written = await asyncio.to_thread(self._store.upsert, items)
        await self._purge()
        return written

    # ---- vector memory: query + read -----------------------------------

    async def retrieve_for_prediction(self, payload: dict) -> list[dict]:
        """Recall memories most relevant to the current OSINT + market picture."""
        if not self._store:
            return []
        osint = payload.get("osint", {})
        market = payload.get("market", {})
        crit_titles = "; ".join(a["title"] for a in osint.get("criticals", [])[:5])
        mstats = market.get("stats", {})
        query = (
            f"Global conflict and market outlook. Active threats: {crit_titles}. "
            f"Market breadth {mstats.get('up', 0)} up / {mstats.get('down', 0)} down."
        )
        embs = await self._embed([query])
        if not embs:
            return []
        rows = await asyncio.to_thread(self._store.search, embs[0], k=self._k)
        # Trim bodies for the prompt; keep recency + similarity signal.
        return [
            {
                "kind": r["kind"],
                "title": r["title"],
                "body": (r["body"] or "")[:200],
                "ageHours": round((time.time() - r["ts"]) / 3600, 1) if r.get("ts") else None,
                "distance": r["distance"],
            }
            for r in rows
        ]

    def memory_stats(self) -> dict:
        if not self._store:
            return {"enabled": False, "total": 0, "byKind": {}, "oldest": None, "newest": None}
        s = self._store.stats()
        s["enabled"] = True
        return s
