"""OSINT — global news heat map.

Pulls recent geocoded news from GDELT (free, no key) and a curated set of RSS
feeds, aggregates it per country into a 0..1 "intensity" signal, and exposes it
to the desktop client. All outbound news fetching lives here in the engine
(clients stay thin), consistent with Max's privacy-marked egress model.
"""

from __future__ import annotations

from .events import EventsService, GeoEvent
from .models import Article, CountryStat, Heatmap
from .naval import NavalService, ShipPosition
from .service import OsintService

__all__ = [
    "Article", "CountryStat", "EventsService", "GeoEvent",
    "Heatmap", "NavalService", "OsintService", "ShipPosition",
]
