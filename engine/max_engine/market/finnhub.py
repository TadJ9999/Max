"""Finnhub client — live US-stock quotes (free tier, API key required).

Finnhub's ``/quote`` endpoint returns the current price plus day open/high/low and
previous close; ``/stock/profile2`` carries the company name. Both require a
``token`` (free key in ``FINNHUB_API_KEY``). An ``httpx.AsyncClient`` may be
injected for testing. Per-symbol failures return ``None`` so one bad ticker
doesn't sink the whole board.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .models import Quote

FINNHUB_BASE = "https://finnhub.io/api/v1"

# A curated default board of liquid US megacaps. User-editable via config.
DEFAULT_WATCHLIST: list[str] = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AMD",
    "NFLX",
    "JPM",
    "V",
    "SPY",
]

# Company-name fallbacks so the board reads well even if profile lookups fail or
# are rate-limited (profile2 is a separate call from the quote).
_NAME_HINTS: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "NVDA": "NVIDIA Corp.",
    "AMZN": "Amazon.com Inc.",
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "AMD": "Advanced Micro Devices",
    "NFLX": "Netflix Inc.",
    "JPM": "JPMorgan Chase & Co.",
    "V": "Visa Inc.",
    "SPY": "SPDR S&P 500 ETF",
}


async def _fetch_name(client: httpx.AsyncClient, symbol: str, api_key: str) -> str | None:
    """Company display name from /stock/profile2. Falls back to a static hint."""
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/profile2",
            params={"symbol": symbol, "token": api_key},
        )
        if resp.status_code >= 400:
            return _NAME_HINTS.get(symbol)
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return _NAME_HINTS.get(symbol)
    if isinstance(data, dict) and data.get("name"):
        return str(data["name"])
    return _NAME_HINTS.get(symbol)


async def fetch_quote(
    client: httpx.AsyncClient,
    symbol: str,
    api_key: str,
    *,
    with_name: bool = True,
) -> Quote | None:
    """Fetch one symbol's live quote. Returns ``None`` on any failure or empty data.

    Finnhub /quote fields: c=current, d=change, dp=percent, h=high, l=low,
    o=open, pc=previous close, t=unix timestamp (seconds).
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return None
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/quote",
            params={"symbol": symbol, "token": api_key},
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    price = data.get("c")
    # Finnhub returns c=0 for an unknown/invalid symbol; treat that as no data.
    if not price:
        return None

    ts_raw = data.get("t")
    ts = (
        datetime.fromtimestamp(ts_raw, tz=timezone.utc)
        if isinstance(ts_raw, (int, float)) and ts_raw
        else None
    )
    name = await _fetch_name(client, symbol, api_key) if with_name else _NAME_HINTS.get(symbol)
    return Quote(
        symbol=symbol,
        name=name,
        price=float(data.get("c") or 0.0),
        change=float(data.get("d") or 0.0),
        change_pct=float(data.get("dp") or 0.0),
        high=float(data.get("h") or 0.0),
        low=float(data.get("l") or 0.0),
        open=float(data.get("o") or 0.0),
        prev_close=float(data.get("pc") or 0.0),
        ts=ts,
    )


async def fetch_market_news(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    count: int = 8,
) -> list[dict]:
    """Recent general market headlines from Finnhub ``/news?category=general``.

    Returns a trimmed list of ``{headline, source, summary, url, datetime}``.
    Returns ``[]`` on any failure so it never sinks an analysis request.
    """
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/news",
            params={"category": "general", "token": api_key},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data[: max(1, count)]:
        if not isinstance(item, dict) or not item.get("headline"):
            continue
        ts_raw = item.get("datetime")
        out.append(
            {
                "headline": str(item.get("headline")),
                "source": item.get("source"),
                "summary": (str(item.get("summary") or ""))[:280],
                "url": item.get("url"),
                "datetime": (
                    datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat()
                    if isinstance(ts_raw, (int, float)) and ts_raw
                    else None
                ),
            }
        )
    return out
