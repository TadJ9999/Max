"""Polymarket CLOB market WebSocket → SSE relay.

Each SSE client opens its **own** short-lived upstream WebSocket to the public
CLOB *market* channel, subscribed to the outcome-token IDs of the market it is
viewing, and relays normalized price / order-book updates. No auth is required
for the public market channel.

Unlike the Market trade stream (one shared upstream for everyone's watchlist),
each Polymarket viewer watches a *different* market, so a per-connection upstream
socket is the simplest correct model — it is opened on subscribe and closed when
the SSE generator is cancelled (client disconnect).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import websockets

CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _levels(raw) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for e in raw:
        if not isinstance(e, dict):
            continue
        p, s = _f(e.get("price")), _f(e.get("size"))
        if p is not None and s is not None:
            out.append({"price": p, "size": s})
    return out


def normalize(raw: str | bytes) -> list[dict]:
    """Map a raw CLOB market-channel frame to a list of normalized events.

    Emits ``book`` (full depth), ``price_change`` (level deltas), and ``trade``
    (last trade price) events keyed by ``tokenId``."""
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return []
    events = msg if isinstance(msg, list) else [msg]
    out: list[dict] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        et = e.get("event_type") or e.get("type")
        token = e.get("asset_id") or e.get("token_id")
        if et == "book":
            out.append(
                {
                    "type": "book",
                    "tokenId": token,
                    "bids": _levels(e.get("bids") or e.get("buys")),
                    "asks": _levels(e.get("asks") or e.get("sells")),
                }
            )
        elif et == "price_change":
            changes = e.get("changes") or e.get("price_changes") or []
            norm = [
                {"price": _f(c.get("price")), "size": _f(c.get("size")), "side": c.get("side")}
                for c in changes
                if isinstance(c, dict)
            ]
            out.append({"type": "price_change", "tokenId": token, "changes": norm})
        elif et in ("last_trade_price", "tick_size_change"):
            price = _f(e.get("price"))
            if price is not None:
                out.append(
                    {
                        "type": "trade",
                        "tokenId": token,
                        "price": price,
                        "size": _f(e.get("size")),
                        "side": e.get("side"),
                    }
                )
    return out


async def stream_prices(
    token_ids: list[str],
    *,
    connect=None,  # injectable websockets.connect for tests
) -> AsyncIterator[dict]:
    """Open one upstream CLOB market socket for ``token_ids`` and yield normalized
    price/book events until the consumer stops iterating (which closes the WS)."""
    ids = [t for t in (token_ids or []) if t]
    if not ids:
        return
    connector = connect or websockets.connect
    async with connector(CLOB_WS) as ws:
        await ws.send(json.dumps({"assets_ids": ids, "type": "market"}))
        async for raw in ws:
            for ev in normalize(raw):
                yield ev
