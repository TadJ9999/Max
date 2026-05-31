"""GDELT DOC 2.0 client — recent geocoded news, free and key-less.

The DOC API requires a non-empty query, so we pass a broad OSINT theme query
(configurable). Each article carries a ``sourcecountry`` *name* which we map to
ISO-A3 via the gazetteer. Tone is not in the artlist mode, so heat is driven by
volume + source diversity + recency downstream.

An ``httpx.AsyncClient`` may be injected for testing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .gazetteer import iso_for_name
from .models import Article

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# A broad net for "what's happening in the world right now". Tunable via config.
DEFAULT_QUERY = (
    "(crisis OR conflict OR war OR election OR protest OR attack OR "
    "disaster OR earthquake OR flood OR sanctions OR summit OR economy) "
    "sourcelang:english"
)


def _parse_seendate(raw: str | None) -> datetime | None:
    """GDELT seendate looks like ``20260530T141500Z``."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _to_article(row: dict) -> Article | None:
    url = row.get("url")
    title = (row.get("title") or "").strip()
    if not url or not title:
        return None
    country_name = row.get("sourcecountry")
    return Article(
        title=title,
        url=url,
        domain=(row.get("domain") or "").lower(),
        origin="gdelt",
        iso=iso_for_name(country_name),
        country=country_name or None,
        published=_parse_seendate(row.get("seendate")),
        image=row.get("socialimage") or None,
    )


async def fetch_gdelt(
    client: httpx.AsyncClient,
    *,
    query: str = DEFAULT_QUERY,
    timespan: str = "24h",
    max_records: int = 250,
) -> list[Article]:
    """Fetch recent articles from GDELT. Returns ``[]`` on any failure."""
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "timespan": timespan,
        "maxrecords": str(max_records),
        "sort": "datedesc",
    }
    try:
        resp = await client.get(GDELT_DOC_URL, params=params)
        if resp.status_code >= 400:
            return []
        # GDELT returns text/plain on errors; guard the JSON decode.
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    rows = data.get("articles") if isinstance(data, dict) else None
    if not rows:
        return []
    out: list[Article] = []
    for row in rows:
        art = _to_article(row)
        if art is not None:
            out.append(art)
    return out
