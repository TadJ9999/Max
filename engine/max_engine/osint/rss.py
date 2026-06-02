"""RSS/Atom news fetcher (stdlib only — no feedparser dependency).

Handles RSS 2.0 (``channel/item``) and Atom (``feed/entry``). Extracts:
  - title, link, published
  - summary — plain-text excerpt from description/summary, HTML-stripped
  - image  — from media:thumbnail, media:content, or enclosure (in that order)
Items aren't geocoded; country is inferred from headline + summary via the
gazetteer (best-effort). Feeds are fetched concurrently; individual failures
are swallowed so one dead feed can't block the batch.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import httpx

from .gazetteer import find_iso_in_text, name_for
from .models import Article
from .sources import DEFAULT_FEEDS  # re-exported; the curated catalog lives there

_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_SUMMARY_MAX = 280  # chars


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _domain(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _rss_image(item: ET.Element) -> str | None:
    """Try media:thumbnail → media:content → enclosure for an item image."""
    # <media:thumbnail url="...">
    for tag in (f"{_MEDIA}thumbnail", f"{_MEDIA}content"):
        el = item.find(tag)
        if el is not None:
            url = el.get("url")
            if url:
                return url
    # <enclosure url="..." type="image/...">
    enc = item.find("enclosure")
    if enc is not None and "image" in (enc.get("type") or ""):
        url = enc.get("url")
        if url:
            return url
    return None


def _atom_image(entry: ET.Element) -> str | None:
    for tag in (f"{_MEDIA}thumbnail", f"{_MEDIA}content"):
        el = entry.find(tag)
        if el is not None:
            url = el.get("url")
            if url:
                return url
    return None


def _make_article(
    title: str,
    link: str,
    raw_summary: str | None,
    date_raw: str | None,
    image: str | None,
) -> Article | None:
    title = title.strip()
    if not title or not link:
        return None
    summary_text = _strip_html(raw_summary)
    summary = summary_text[:_SUMMARY_MAX] if summary_text else None
    iso = find_iso_in_text(f"{title} {summary_text}")
    return Article(
        title=title,
        url=link.strip(),
        domain=_domain(link),
        origin="rss",
        iso=iso,
        country=name_for(iso) if iso else None,
        published=_parse_date(date_raw),
        image=image,
        summary=summary,
    )


def parse_feed(xml: str) -> list[Article]:
    """Parse one RSS 2.0 or Atom document into normalized articles."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    out: list[Article] = []

    # RSS 2.0
    for item in root.iter("item"):
        art = _make_article(
            item.findtext("title", ""),
            item.findtext("link", ""),
            item.findtext("description"),
            item.findtext("pubDate"),
            _rss_image(item),
        )
        if art:
            out.append(art)

    # Atom
    for entry in root.iter(f"{_ATOM}entry"):
        link_el = entry.find(f"{_ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        raw_summary = (
            entry.findtext(f"{_ATOM}summary")
            or entry.findtext(f"{_ATOM}content")
            or ""
        )
        art = _make_article(
            entry.findtext(f"{_ATOM}title", ""),
            link,
            raw_summary,
            entry.findtext(f"{_ATOM}updated") or entry.findtext(f"{_ATOM}published"),
            _atom_image(entry),
        )
        if art:
            out.append(art)

    return out


async def _fetch_one(client: httpx.AsyncClient, url: str) -> list[Article]:
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code >= 400:
            return []
        return parse_feed(resp.text)
    except httpx.HTTPError:
        return []


async def fetch_rss(client: httpx.AsyncClient, feeds: list[str] | None = None) -> list[Article]:
    """Fetch all feeds concurrently and flatten results."""
    feeds = feeds or DEFAULT_FEEDS
    results = await asyncio.gather(*(_fetch_one(client, u) for u in feeds))
    return [art for batch in results for art in batch]
