"""Embed Polymarket markets into Apollo's vector store.

Formats each market as a natural-language chunk and stores it with
kind="polymarket" so Apollo retrieval surfaces prediction-market context
alongside news and stock memories.
"""

from __future__ import annotations

import time

from ..apollo.embed import embed_texts
from ..apollo.store import VectorStore
from .models import Market


def _market_text(market: Market) -> str:
    """Format a market as a natural-language chunk for embedding."""
    lines = [f"Prediction Market: {market.question}"]
    if market.category:
        lines.append(f"Category: {market.category}")
    for o in market.outcomes:
        pct = round(o.price * 100, 1)
        lines.append(f"{o.name} probability: {pct}%")
    if market.volume_24hr > 0:
        lines.append(f"24h volume: ${market.volume_24hr:,.0f}")
    if market.volume > 0:
        lines.append(f"Total volume: ${market.volume:,.0f}")
    if market.liquidity > 0:
        lines.append(f"Liquidity: ${market.liquidity:,.0f}")
    if market.end_date:
        lines.append(f"Resolves: {market.end_date[:10]}")
    if market.description:
        desc = market.description[:300].replace("\n", " ")
        lines.append(f"Details: {desc}")
    return ". ".join(lines)


async def embed_markets(
    markets: list[Market],
    store: VectorStore,
    *,
    embed_model: str = "nomic-embed-text",
    base_url: str = "http://127.0.0.1:11434",
    ttl_seconds: int = 86_400,
) -> int:
    """Embed markets and upsert into the vector store. Returns count written."""
    if not markets or store is None:
        return 0

    texts = [_market_text(m) for m in markets]
    embeddings = await embed_texts(texts, model=embed_model, base_url=base_url)
    if not embeddings or len(embeddings) != len(markets):
        return 0

    now = int(time.time())
    items = []
    for market, emb in zip(markets, embeddings):
        items.append(
            {
                "kind": "polymarket",
                "ref": f"polymarket:{market.condition_id}",
                "ts": now,
                "title": market.question[:120],
                "body": _market_text(market),
                "meta": {
                    "conditionId": market.condition_id,
                    "category": market.category,
                    "yesPrice": market.yes_price,
                    "volume24hr": market.volume_24hr,
                    "endDate": market.end_date,
                },
                "embedding": emb,
            }
        )

    written = await __import__("asyncio").to_thread(store.upsert, items)
    # Purge expired entries of this kind
    await __import__("asyncio").to_thread(store.purge_older_than, ttl_seconds)
    return written
