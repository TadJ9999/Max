"""GNews.io client — query-based news search across many outlets.

Free tier is **100 requests/day**, so the caller (``OsintService``) throttles this
on its own slow TTL rather than the main OSINT refresh cadence. The API key is read
from the environment (``GNEWS_API_KEY``) and passed in — never stored in config.

Each result is mapped to the shared :class:`Article` shape with ``origin="gnews"``.
Country is inferred from the headline + description via the gazetteer (best-effort),
the same way RSS items are geocoded. Returns ``[]`` on any failure (no key, HTTP
error, bad JSON) so a dead/over-quota provider never breaks a refresh.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from .gazetteer import find_iso_in_text, name_for
from .models import Article

GNEWS_SEARCH_URL = "https://gnews.io/api/v4/search"


def _domain(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _parse_published(raw: str | None) -> datetime | None:
    """GNews publishedAt is ISO-8601, e.g. ``2026-05-30T14:15:00Z``."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_article(row: dict) -> Article | None:
    title = (row.get("title") or "").strip()
    url = row.get("url")
    if not title or not url:
        return None
    desc = (row.get("description") or "").strip()
    iso = find_iso_in_text(f"{title} {desc}")
    source = row.get("source") or {}
    image = row.get("image") or None
    return Article(
        title=title,
        url=url.strip(),
        domain=_domain(source.get("url") or url),
        origin="gnews",
        iso=iso,
        country=name_for(iso) if iso else None,
        published=_parse_published(row.get("publishedAt")),
        image=image,
        summary=desc[:280] or None,
    )


async def fetch_gnews(
    client: httpx.AsyncClient,
    *,
    query: str,
    api_key: str | None,
    max_records: int = 25,
    lang: str = "en",
) -> list[Article]:
    """Search GNews for ``query``. Returns ``[]`` on any failure or missing key."""
    if not api_key or not (query and query.strip()):
        return []
    params = {
        "q": query,
        "token": api_key,
        "lang": lang,
        "max": str(max(1, min(100, max_records))),
        "sortby": "publishedAt",
    }
    try:
        resp = await client.get(GNEWS_SEARCH_URL, params=params)
        if resp.status_code >= 400:
            return []
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
