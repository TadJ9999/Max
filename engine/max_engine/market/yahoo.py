"""Yahoo Finance candle client — keyless OHLCV for charts.

Finnhub's ``/stock/candle`` endpoint became premium-only, so free keys get a 403
and the chart renders empty. Yahoo Finance's public v8 chart API needs no key and
covers every interval the terminal offers (5m / 30m / 60m / 1d / 1wk / 1mo) with
full open/high/low/close/volume. We keep Finnhub for quotes and the live trade
socket (both still free) and use Yahoo only for the historical candles.

The endpoint is unofficial but widely used; a browser-like ``User-Agent`` avoids
the occasional bot block. Any failure returns ``[]`` so the chart degrades to its
"no data" state rather than erroring.
"""

from __future__ import annotations

import time

import httpx

YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

# Browser-like UA: Yahoo 403s some default client UAs.
_YAHOO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Finnhub-style resolution (sent by the frontend) → Yahoo interval string.
_RESOLUTION_TO_INTERVAL: dict[str, str] = {
    "1": "1m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "60m",
    "D": "1d",
    "W": "1wk",
    "M": "1mo",
}


async def fetch_candles(
    client: httpx.AsyncClient,
    symbol: str,
    *,
    resolution: str = "D",
    days: int = 30,
) -> list[dict]:
    """Fetch OHLCV candles from Yahoo Finance's v8 chart API (no API key).

    ``resolution`` uses the same vocabulary as the old Finnhub path
    (1|5|15|30|60|D|W|M). Returns ``[{t, o, h, l, c, v}, ...]`` sorted oldest
    first (``t`` in unix seconds), or ``[]`` on any failure.
    """
    interval = _RESOLUTION_TO_INTERVAL.get(resolution.upper() if resolution.isalpha() else resolution, "1d")
    now_ts = int(time.time())
    period1 = now_ts - max(1, days) * 86_400
    try:
        resp = await client.get(
            f"{YAHOO_CHART_BASE}/{symbol.upper()}",
            params={
                "interval": interval,
                "period1": period1,
                "period2": now_ts,
                "includePrePost": "false",
            },
            headers={"user-agent": _YAHOO_UA},
            timeout=15.0,
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    chart = data.get("chart") if isinstance(data, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    if not results or not isinstance(results, list):
        return []
    result = results[0]
    if not isinstance(result, dict):
        return []

    ts_list = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote") or []
    if not ts_list or not quotes or not isinstance(quotes[0], dict):
        return []
    q = quotes[0]
    o_list = q.get("open") or []
    h_list = q.get("high") or []
    l_list = q.get("low") or []
    c_list = q.get("close") or []
    v_list = q.get("volume") or []

    candles: list[dict] = []
    for i, ts in enumerate(ts_list):
        close = c_list[i] if i < len(c_list) else None
        # Yahoo returns null for gaps (holidays, halts); skip those rows.
        if close is None:
            continue
        candles.append(
            {
                "t": int(ts),
                "o": float(o_list[i]) if i < len(o_list) and o_list[i] is not None else float(close),
                "h": float(h_list[i]) if i < len(h_list) and h_list[i] is not None else float(close),
                "l": float(l_list[i]) if i < len(l_list) and l_list[i] is not None else float(close),
                "c": float(close),
                "v": int(v_list[i]) if i < len(v_list) and v_list[i] is not None else 0,
            }
        )
    return candles
