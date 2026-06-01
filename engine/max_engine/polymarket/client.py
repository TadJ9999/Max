"""Polymarket API clients — Gamma (market listings) and CLOB (prices/order books).

Both APIs are free and require no authentication for read access.
Per-market failures are swallowed (returns None) so one bad market never sinks the board.
"""

from __future__ import annotations

import json

import httpx

from .models import Market, OrderBook, OrderBookLevel, Outcome, PricePoint

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_BASE = "https://data-api.polymarket.com"

_UA = "MaxEngine-Polymarket/0.1 (+local; prediction market board)"


def _parse_json_field(raw: str | list | None) -> list:
    """Gamma API returns outcomes/prices/tokenIds as JSON strings or actual lists."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []


def _parse_market(data: dict) -> Market | None:
    """Normalize one Gamma API market object. Returns None on parse failure."""
    try:
        cid = data.get("conditionId") or data.get("condition_id") or ""
        if not cid:
            return None
        outcomes_raw = _parse_json_field(data.get("outcomes"))
        prices_raw = _parse_json_field(data.get("outcomePrices"))
        tokens_raw = _parse_json_field(data.get("clobTokenIds"))

        outcomes: list[Outcome] = []
        for i, name in enumerate(outcomes_raw):
            price = float(prices_raw[i]) if i < len(prices_raw) else 0.0
            token_id = str(tokens_raw[i]) if i < len(tokens_raw) else None
            outcomes.append(Outcome(name=str(name), price=price, token_id=token_id))

        return Market(
            condition_id=cid,
            question=str(data.get("question", "")),
            slug=str(data.get("slug", "")),
            category=str(data.get("category", "")),
            description=str(data.get("description", "")),
            outcomes=outcomes,
            volume=float(data.get("volume", 0) or 0),
            volume_24hr=float(data.get("volume24hr", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            end_date=data.get("endDate"),
            active=bool(data.get("active", True)),
            closed=bool(data.get("closed", False)),
            image=data.get("image"),
        )
    except (KeyError, ValueError, TypeError):
        return None


async def fetch_markets(
    client: httpx.AsyncClient,
    *,
    category: str | None = None,
    active: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[Market]:
    """Fetch active markets from Gamma API sorted by 24h volume descending."""
    params: dict = {
        "active": str(active).lower(),
        "closed": "false",
        "archived": "false",
        "limit": limit,
        "offset": offset,
        "order": "volume24hr",
        "ascending": "false",
    }
    if category:
        params["category"] = category
    try:
        resp = await client.get(
            f"{GAMMA_BASE}/markets",
            params=params,
            headers={"user-agent": _UA},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    # Gamma may return a list or a wrapped object
    items = data if isinstance(data, list) else data.get("data", [])
    markets: list[Market] = []
    for item in items:
        m = _parse_market(item)
        if m is not None:
            markets.append(m)
    return markets


async def fetch_price_history(
    client: httpx.AsyncClient,
    condition_id: str,
    *,
    interval: str = "1w",
) -> list[PricePoint]:
    """Fetch YES-outcome price history from the CLOB API.

    ``interval`` is one of: 1d, 1w, 1m, max.
    Returns an empty list on any failure — never fatal.
    """
    try:
        resp = await client.get(
            f"{CLOB_BASE}/prices-history",
            params={"market": condition_id, "interval": interval, "fidelity": 60},
            headers={"user-agent": _UA},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    history = data.get("history", [])
    points: list[PricePoint] = []
    for h in history:
        try:
            points.append(PricePoint(t=int(h["t"]), p=float(h["p"])))
        except (KeyError, TypeError, ValueError):
            continue
    return points


async def fetch_order_book(
    client: httpx.AsyncClient,
    token_id: str,
) -> OrderBook | None:
    """Fetch the order book for one outcome token from the CLOB API."""
    try:
        resp = await client.get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
            headers={"user-agent": _UA},
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    def _levels(raw: list) -> list[OrderBookLevel]:
        out: list[OrderBookLevel] = []
        for entry in raw:
            try:
                out.append(OrderBookLevel(price=float(entry["price"]), size=float(entry["size"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    return OrderBook(
        bids=_levels(data.get("bids", [])),
        asks=_levels(data.get("asks", [])),
    )


def _parse_position(p: dict) -> dict | None:
    """Normalize one Data API position row. Returns None if it carries no size."""
    if not isinstance(p, dict):
        return None
    size = float(p.get("size", 0) or 0)
    if size == 0:
        return None
    cur_price = float(p.get("curPrice", 0) or 0)
    return {
        "conditionId": p.get("conditionId") or p.get("condition_id") or "",
        "title": str(p.get("title") or p.get("question") or ""),
        "slug": p.get("slug"),
        "outcome": str(p.get("outcome") or ""),
        "size": round(size, 4),
        "avgPrice": round(float(p.get("avgPrice", 0) or 0), 4),
        "curPrice": round(cur_price, 4),
        "initialValue": round(float(p.get("initialValue", 0) or 0), 2),
        "currentValue": round(float(p.get("currentValue", size * cur_price) or 0), 2),
        "cashPnl": round(float(p.get("cashPnl", 0) or 0), 2),
        "percentPnl": round(float(p.get("percentPnl", 0) or 0), 2),
        "redeemable": bool(p.get("redeemable", False)),
        "endDate": p.get("endDate") or p.get("end_date"),
    }


async def fetch_positions(client: httpx.AsyncClient, address: str) -> list[dict]:
    """Read-only open positions for a wallet from the public Data API.

    ``address`` is the user's proxy wallet (0x…). Returns ``[]`` on any failure or
    for an address with no positions. No auth required."""
    addr = (address or "").strip()
    if not addr:
        return []
    try:
        resp = await client.get(
            f"{DATA_BASE}/positions",
            params={"user": addr, "sizeThreshold": 1, "limit": 200, "sortBy": "CURRENT"},
            headers={"user-agent": _UA},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    items = data if isinstance(data, list) else data.get("data", [])
    out: list[dict] = []
    for item in items:
        pos = _parse_position(item)
        if pos is not None:
            out.append(pos)
    return out


async def fetch_market_events(
    client: httpx.AsyncClient,
    condition_id: str,
    *,
    limit: int = 10,
) -> list[dict]:
    """Fetch news/events for a market via the Gamma API ``/events`` field.

    Returns a list of ``{title, article_url, description, start_date}`` dicts,
    or ``[]`` on failure. The Gamma API's markets endpoint includes an ``events``
    array with related event metadata.
    """
    try:
        resp = await client.get(
            f"{GAMMA_BASE}/markets",
            params={"conditionId": condition_id},
            headers={"user-agent": _UA},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return []

    # The first market matching this condition_id may have an events field
    for item in items:
        if not isinstance(item, dict):
            continue
        events_raw = item.get("events") or []
        if not isinstance(events_raw, list):
            continue
        out: list[dict] = []
        for ev in events_raw[:limit]:
            if not isinstance(ev, dict):
                continue
            title = ev.get("title") or ev.get("question") or ""
            if not title:
                continue
            out.append({
                "title": str(title),
                "description": (str(ev.get("description") or ""))[:300],
                "article_url": ev.get("articleUrl") or ev.get("article_url"),
                "start_date": ev.get("startDate") or ev.get("start_date"),
                "end_date": ev.get("endDate") or ev.get("end_date"),
                "category": ev.get("category"),
            })
        if out:
            return out
    return []
