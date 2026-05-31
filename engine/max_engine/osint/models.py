"""Shared OSINT data shapes (normalized across GDELT + RSS)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .severity import LABELS


@dataclass
class Article:
    """One news item, normalized from whichever source produced it."""

    title: str
    url: str
    domain: str  # source domain, e.g. "reuters.com"
    origin: str  # "gdelt" | "rss"
    iso: str | None = None  # ISO-A3 of the country the item is about, if known
    country: str | None = None  # human country name
    published: datetime | None = None
    image: str | None = None
    severity: int = 0  # 0 low .. 3 critical (see osint.severity)
    summary: str | None = None  # plain-text excerpt (from RSS description or GDELT)
    tone: float | None = None   # GDELT tone: negative = negative sentiment (-100..100)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "origin": self.origin,
            "iso": self.iso,
            "country": self.country,
            "published": self.published.isoformat() if self.published else None,
            "image": self.image,
            "severity": self.severity,
            "severityLabel": LABELS[self.severity],
            "summary": self.summary,
        }


@dataclass
class CountryStat:
    """Aggregated news pressure for a single country."""

    iso: str  # ISO-A3 (joins to the map atlas on the client)
    name: str
    intensity: float  # 0..1 normalized heat (sizes the bar; coloring is by severity)
    article_count: int
    sources: int  # distinct source domains
    severity: int = 0  # peak criticality among the country's articles (0..3)

    def to_dict(self) -> dict:
        return {
            "iso": self.iso,
            "name": self.name,
            "intensity": round(self.intensity, 4),
            "articleCount": self.article_count,
            "sources": self.sources,
            "severity": self.severity,
            "severityLabel": LABELS[self.severity],
        }


@dataclass
class Heatmap:
    """The full payload served to the client."""

    updated: datetime
    countries: list[CountryStat] = field(default_factory=list)
    total_articles: int = 0

    def to_dict(self) -> dict:
        return {
            "updated": self.updated.isoformat(),
            "totalArticles": self.total_articles,
            "countries": [c.to_dict() for c in self.countries],
        }
