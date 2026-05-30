"""Importance scoring — turn a pile of articles into per-country heat (0..1).

A country's raw pressure combines three signals:
  * **volume**     — how many articles mention it,
  * **recency**    — newer items count for more (exponential decay),
  * **diversity**  — more distinct sources => more corroborated => more important.

Raw scores are normalized against the busiest country, then gamma-lifted so the
mid-range stays visible on the map instead of being washed out by one hotspot.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .gazetteer import name_for
from .models import Article, CountryStat

HALF_LIFE_HOURS = 12.0
_GAMMA = 0.6  # < 1 lifts mid-range intensities for better visual spread

# Weighted-mean severity → tier. Bucketing the *average* (not the peak) stops a
# single "man killed" crime headline from flipping a whole country to Critical.
_SEV_CUTS = ((2.3, 3), (1.3, 2), (0.5, 1))  # (min mean, tier); else Low(0)


def _recency_weight(published: datetime | None, now: datetime) -> float:
    if published is None:
        return 0.5  # unknown age => middling weight
    age_h = max(0.0, (now - published).total_seconds() / 3600.0)
    return 0.5 ** (age_h / HALF_LIFE_HOURS)


def _severity_tier(mean: float) -> int:
    for cut, tier in _SEV_CUTS:
        if mean >= cut:
            return tier
    return 0


def score_countries(articles: list[Article], now: datetime | None = None) -> list[CountryStat]:
    """Aggregate geolocated articles into normalized per-country stats."""
    now = now or datetime.now(timezone.utc)

    weighted: dict[str, float] = {}
    sev_weighted: dict[str, float] = {}
    counts: dict[str, int] = {}
    domains: dict[str, set[str]] = {}

    for art in articles:
        if not art.iso:
            continue
        rw = _recency_weight(art.published, now)
        weighted[art.iso] = weighted.get(art.iso, 0.0) + rw
        sev_weighted[art.iso] = sev_weighted.get(art.iso, 0.0) + rw * art.severity
        counts[art.iso] = counts.get(art.iso, 0) + 1
        domains.setdefault(art.iso, set())
        if art.domain:
            domains[art.iso].add(art.domain)

    if not weighted:
        return []

    # diversity multiplier: 1 source -> 1.0, grows slowly (log2) with more sources.
    raw: dict[str, float] = {}
    for iso, w in weighted.items():
        diversity = 1.0 + 0.5 * math.log2(1 + len(domains.get(iso, ())))
        raw[iso] = w * diversity

    top = max(raw.values())
    stats: list[CountryStat] = []
    for iso, r in raw.items():
        intensity = (r / top) ** _GAMMA if top > 0 else 0.0
        stats.append(
            CountryStat(
                iso=iso,
                name=name_for(iso) or iso,
                intensity=intensity,
                article_count=counts[iso],
                sources=len(domains.get(iso, ())),
                severity=_severity_tier(sev_weighted[iso] / weighted[iso]),
            )
        )

    # Most-critical first, then by heat — so Critical zones top the list.
    stats.sort(key=lambda s: (s.severity, s.intensity), reverse=True)
    return stats
