"""Curated news-feed catalog — the source-of-truth list of RSS/Atom feeds.

Feeds are grouped by theme so the intake is organized and the Oracle Enrichment
analyzer can reason about *which kind* of coverage is thin. ``DEFAULT_FEEDS`` is
the flat, de-duped composition the OSINT service actually fetches; it preserves
the original world feeds at the front so existing behaviour is unchanged.

Only feeds with a real, public RSS/Atom endpoint are listed (Reuters retired
theirs, so NYT/NPR/France24 stand in). Individual dead feeds are harmless — the
fetcher swallows per-feed failures (``osint/rss.py``).

This module is also the home for *future* source groups (Telegram/X). Those plug
in as a ``fetch_<src>`` coroutine returning ``Article`` objects with a new
``origin`` tag, folded into ``OsintService.refresh``'s gather — no new framework.
"""

from __future__ import annotations

# Human-readable labels for each group (used by the Enrichment analyzer + UI).
GROUP_LABELS: dict[str, str] = {
    "world": "World news",
    "finance": "Finance & markets",
    "osint": "Specialist OSINT",
}

FEED_CATALOG: dict[str, list[str]] = {
    # General world desks — the original six plus reliable additions.
    "world": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.dw.com/rdf/rss-en-world",
        "https://www.theguardian.com/world/rss",
        "https://apnews.com/index.rss",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://feeds.npr.org/1004/rss.xml",
        "https://www.france24.com/en/rss",
        "https://www.cbc.ca/webfeed/rss/rss-world",
        "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
    ],
    # Markets coverage — feeds Apollo/Market prediction context as well as OSINT.
    "finance": [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "http://feeds.marketwatch.com/marketwatch/topstories/",
        "https://finance.yahoo.com/news/rssindex",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        "https://www.theguardian.com/uk/business/rss",
    ],
    # Higher-signal OSINT / advisories / conflict & cyber.
    "osint": [
        "https://www.cisa.gov/cybersecurity-advisories/all.xml",
        "https://reliefweb.int/updates/rss.xml",
        "https://www.bellingcat.com/feed/",
        "https://krebsonsecurity.com/feed/",
        "https://www.state.gov/rss-feeds/press-releases/feed/",
    ],
}


def _dedupe_preserve_order(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# Flat composition fetched by the service (world first to preserve old behaviour).
DEFAULT_FEEDS: list[str] = _dedupe_preserve_order(
    [u for group in FEED_CATALOG.values() for u in group]
)

# Reverse map url -> group, for tagging / analysis.
FEED_GROUP: dict[str, str] = {
    url: group for group, urls in FEED_CATALOG.items() for url in urls
}
