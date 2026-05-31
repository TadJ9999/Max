"""Geospatial event feeds — earthquake, disaster, and weather alerts.

All sources here are free and require no API key. Each source is fetched
independently (failures are swallowed) and returned as a unified GeoEvent list
that the client can layer over the map alongside the naval + news data.

Sources wired today:
  USGS  — M ≥ 4.5 earthquakes in the last 24 h (GeoJSON, true lat/lon)
  GDACS — Global disaster alerts (cyclones, floods, volcanoes, wildfires, …) via RSS

Architecture: add more sources by defining an ``async def fetch_*`` that returns
``list[GeoEvent]`` and calling it inside ``EventsService.refresh()``.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from xml.etree import ElementTree as ET

import httpx

# ---- shared model -------------------------------------------------------

CATEGORY_COLORS: dict[str, str] = {
    "earthquake": "#f97316",   # orange
    "cyclone":    "#c084fc",   # purple
    "flood":      "#38bdf8",   # sky-blue
    "volcano":    "#f43f5e",   # rose-red
    "wildfire":   "#fb923c",   # amber-orange
    "drought":    "#a16207",   # dark-amber
    "disaster":   "#f59e0b",   # amber (generic)
}

ALERT_SEVERITY: dict[str, int] = {"red": 3, "orange": 2, "green": 1}


@dataclass
class GeoEvent:
    id: str
    category: str          # "earthquake" | "cyclone" | "flood" | "volcano" | …
    title: str
    lat: float
    lon: float
    magnitude: float       # quake Mw, wind-speed km/h, etc.; 0 if not applicable
    severity: int          # 0–3 (mirrors news severity scale)
    url: str
    source: str
    published: str | None  # ISO datetime string

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "lat": self.lat,
            "lon": self.lon,
            "magnitude": self.magnitude,
            "severity": self.severity,
            "color": CATEGORY_COLORS.get(self.category, "#f59e0b"),
            "url": self.url,
            "source": self.source,
            "published": self.published,
        }


# ---- USGS earthquakes ---------------------------------------------------
# Completely free, no key, official GeoJSON, updated every 5 min.

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"


def _quake_severity(mag: float) -> int:
    if mag >= 7.0:
        return 3
    if mag >= 6.0:
        return 2
    if mag >= 5.0:
        return 1
    return 0


async def fetch_earthquakes(client: httpx.AsyncClient) -> list[GeoEvent]:
    try:
        r = await client.get(USGS_URL)
        if r.status_code >= 400:
            return []
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    out: list[GeoEvent] = []
    for feat in data.get("features", []):
        p = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        mag = float(p.get("mag") or 0)
        ts = p.get("time")
        pub = (
            datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
            if ts
            else None
        )
        out.append(
            GeoEvent(
                id=feat.get("id", f"usgs-{lat}-{lon}"),
                category="earthquake",
                title=p.get("place") or f"M{mag:.1f} earthquake",
                lat=lat,
                lon=lon,
                magnitude=mag,
                severity=_quake_severity(mag),
                url=p.get("url") or USGS_URL,
                source="USGS",
                published=pub,
            )
        )
    return out


# ---- GDACS disaster alerts ----------------------------------------------
# Global Disaster Alert and Coordination System — free RSS, no key.
# Covers cyclones, floods, earthquakes, volcanoes, droughts, wildfires.

GDACS_RSS = "https://www.gdacs.org/xml/rss.xml"

_GEO_NS   = "{http://www.w3.org/2003/01/geo/wgs84_pos#}"
_GDACS_NS = "{http://www.gdacs.org/}"

_CATEGORY_MAP: dict[str, str] = {
    "EQ": "earthquake", "TC": "cyclone", "FL": "flood",
    "VO": "volcano",    "DR": "drought", "WF": "wildfire",
}
_GDACS_DATE_RE = re.compile(
    r"(\w{3}),\s+(\d{1,2})\s+(\w{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})"
)


def _gdacs_date(raw: str) -> str | None:
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return None


def parse_gdacs_rss(xml: str) -> list[GeoEvent]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out: list[GeoEvent] = []
    for item in root.findall(".//item"):
        lat_el = item.find(f"{_GEO_NS}lat")
        lon_el = item.find(f"{_GEO_NS}long")
        if lat_el is None or lon_el is None:
            continue
        try:
            lat = float(lat_el.text or "")
            lon = float(lon_el.text or "")
        except ValueError:
            continue

        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        pub   = _gdacs_date(item.findtext("pubDate") or "")

        # GDACS event type
        etype = (item.findtext(f"{_GDACS_NS}eventtype") or "").upper()
        category = _CATEGORY_MAP.get(etype, "disaster")

        # Alert level → severity
        alert = (item.findtext(f"{_GDACS_NS}alertlevel") or "").lower()
        severity = ALERT_SEVERITY.get(alert, 1)

        # Magnitude / intensity value (severity number = e.g. wind speed or Mw)
        try:
            mag = float(item.findtext(f"{_GDACS_NS}severity") or 0)
        except ValueError:
            mag = 0.0

        # Skip green-alert quakes (USGS already covers these with real values)
        if category == "earthquake" and alert == "green":
            continue

        event_id = (
            item.findtext(f"{_GDACS_NS}eventid") or f"gdacs-{lat}-{lon}"
        )
        out.append(
            GeoEvent(
                id=f"gdacs-{event_id}",
                category=category,
                title=title,
                lat=lat,
                lon=lon,
                magnitude=mag,
                severity=severity,
                url=link,
                source="GDACS",
                published=pub,
            )
        )
    return out


async def fetch_gdacs(client: httpx.AsyncClient) -> list[GeoEvent]:
    try:
        r = await client.get(GDACS_RSS, follow_redirects=True)
        if r.status_code >= 400:
            return []
        return parse_gdacs_rss(r.text)
    except httpx.HTTPError:
        return []


# ---- service ------------------------------------------------------------

_UA = "MaxEngine-OSINT/0.1 (+local; event map)"


class EventsService:
    """Aggregates multi-source geospatial event feeds with a short TTL cache."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,  # USGS updates every 5 min
        client: httpx.AsyncClient | None = None,
    ):
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._lock = asyncio.Lock()
        self._events: list[GeoEvent] = []
        self._updated: datetime | None = None
        self._fetched_at: float | None = None

    def _fresh(self) -> bool:
        return (
            self._updated is not None
            and self._fetched_at is not None
            and (monotonic() - self._fetched_at) < self.ttl_seconds
        )

    async def refresh(self, *, force: bool = False) -> None:
        async with self._lock:
            if not force and self._fresh():
                return
            owns = self._client is None
            client = self._client or httpx.AsyncClient(
                timeout=15.0, headers={"user-agent": _UA}
            )
            try:
                results = await asyncio.gather(
                    fetch_earthquakes(client),
                    fetch_gdacs(client),
                    return_exceptions=True,
                )
            finally:
                if owns:
                    await client.aclose()

            events: list[GeoEvent] = []
            for r in results:
                if isinstance(r, list):
                    events.extend(r)
            self._events = events
            self._updated = datetime.now(timezone.utc)
            self._fetched_at = monotonic()

    async def get(self) -> dict:
        await self.refresh()
        return {
            "updated": self._updated.isoformat() if self._updated else None,
            "count": len(self._events),
            "events": [e.to_dict() for e in self._events],
            "sources": ["USGS (M≥4.5 earthquakes)", "GDACS (disaster alerts)"],
        }
