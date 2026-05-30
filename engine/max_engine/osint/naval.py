"""US Navy carrier / big-deck amphib position estimates from public OSINT.

There is **no** real-time public GPS feed for USN warships. The open sources
(USNI Fleet Tracker, TWZ Carrier Tracker) publish *weekly, region-level*
positions in prose ("operating in the Arabian Sea"). We fetch the latest
report, anchor on hull tokens (``CVN-73`` / ``LHD-3``), and geocode the nearest
region phrase to a representative lat/lon. Positions are therefore approximate
and dated — flagged as such — and are the same "estimated via news analysis"
approach ShadowBroker uses. Groundwork for future track prediction.
"""

from __future__ import annotations

import asyncio
import html as _html
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import monotonic
from xml.etree import ElementTree as ET

import httpx

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# The default TWZ article (the user's seed source); newer ones supersede via config.
DEFAULT_TWZ_URL = "https://www.twz.com/sea/carrier-tracker-as-of-april-26-2026"

# ---- ship roster (active carriers + big-deck amphibs) -------------------
# hull -> (display name, type)
ROSTER: dict[str, tuple[str, str]] = {
    "CVN-68": ("USS Nimitz", "carrier"),
    "CVN-69": ("USS Dwight D. Eisenhower", "carrier"),
    "CVN-70": ("USS Carl Vinson", "carrier"),
    "CVN-71": ("USS Theodore Roosevelt", "carrier"),
    "CVN-72": ("USS Abraham Lincoln", "carrier"),
    "CVN-73": ("USS George Washington", "carrier"),
    "CVN-74": ("USS John C. Stennis", "carrier"),
    "CVN-75": ("USS Harry S. Truman", "carrier"),
    "CVN-76": ("USS Ronald Reagan", "carrier"),
    "CVN-77": ("USS George H.W. Bush", "carrier"),
    "CVN-78": ("USS Gerald R. Ford", "carrier"),
    "CVN-79": ("USS John F. Kennedy", "carrier"),
    "LHA-6": ("USS America", "amphib"),
    "LHA-7": ("USS Tripoli", "amphib"),
    "LHD-1": ("USS Wasp", "amphib"),
    "LHD-2": ("USS Essex", "amphib"),
    "LHD-3": ("USS Kearsarge", "amphib"),
    "LHD-4": ("USS Boxer", "amphib"),
    "LHD-5": ("USS Bataan", "amphib"),
    "LHD-7": ("USS Iwo Jima", "amphib"),
    "LHD-8": ("USS Makin Island", "amphib"),
}

# ---- region / port gazetteer -------------------------------------------
# alias (lowercase) -> (lat, lon, label, kind). kind weights which wins when a
# ship's window mentions several: open water (where it *is*) beats homeport.
_KIND_WEIGHT = {"sea": 4, "port": 3, "aor": 2, "country": 1}

_REGIONS_RAW: list[tuple[str, float, float, str, str]] = [
    # seas & oceans
    ("south china sea", 13.0, 114.0, "South China Sea", "sea"),
    ("east china sea", 29.0, 125.0, "East China Sea", "sea"),
    ("philippine sea", 18.0, 132.0, "Philippine Sea", "sea"),
    ("sea of japan", 40.0, 135.0, "Sea of Japan", "sea"),
    ("yellow sea", 35.0, 123.0, "Yellow Sea", "sea"),
    ("bay of bengal", 15.0, 88.0, "Bay of Bengal", "sea"),
    ("andaman sea", 10.0, 96.0, "Andaman Sea", "sea"),
    ("arabian sea", 15.0, 65.0, "Arabian Sea", "sea"),
    ("persian gulf", 26.5, 51.5, "Persian Gulf", "sea"),
    ("arabian gulf", 26.5, 51.5, "Persian Gulf", "sea"),
    ("gulf of oman", 24.5, 58.5, "Gulf of Oman", "sea"),
    ("northern red sea", 25.0, 36.0, "Northern Red Sea", "sea"),
    ("red sea", 20.0, 38.0, "Red Sea", "sea"),
    ("gulf of aden", 12.0, 47.0, "Gulf of Aden", "sea"),
    ("eastern mediterranean", 34.0, 28.0, "Eastern Mediterranean", "sea"),
    ("central mediterranean", 35.0, 15.0, "Central Mediterranean", "sea"),
    ("western mediterranean", 39.0, 5.0, "Western Mediterranean", "sea"),
    ("mediterranean", 35.0, 18.0, "Mediterranean Sea", "sea"),
    ("adriatic", 43.0, 15.0, "Adriatic Sea", "sea"),
    ("aegean", 38.0, 25.0, "Aegean Sea", "sea"),
    ("black sea", 43.0, 34.0, "Black Sea", "sea"),
    ("baltic sea", 58.0, 20.0, "Baltic Sea", "sea"),
    ("north sea", 56.0, 3.0, "North Sea", "sea"),
    ("norwegian sea", 68.0, 5.0, "Norwegian Sea", "sea"),
    ("barents sea", 74.0, 38.0, "Barents Sea", "sea"),
    ("western atlantic", 32.0, -65.0, "Western Atlantic", "sea"),
    ("north atlantic", 45.0, -40.0, "North Atlantic", "sea"),
    ("south atlantic", -20.0, -10.0, "South Atlantic", "sea"),
    ("atlantic ocean", 35.0, -45.0, "Atlantic Ocean", "sea"),
    ("caribbean sea", 15.0, -75.0, "Caribbean Sea", "sea"),
    ("caribbean", 15.0, -75.0, "Caribbean Sea", "sea"),
    ("gulf of mexico", 25.0, -90.0, "Gulf of Mexico", "sea"),
    ("eastern pacific", 10.0, -120.0, "Eastern Pacific", "sea"),
    ("western pacific", 15.0, 140.0, "Western Pacific", "sea"),
    ("central pacific", 10.0, -170.0, "Central Pacific", "sea"),
    ("south pacific", -20.0, -150.0, "South Pacific", "sea"),
    ("pacific ocean", 0.0, -160.0, "Pacific Ocean", "sea"),
    ("coral sea", -15.0, 152.0, "Coral Sea", "sea"),
    ("tasman sea", -40.0, 160.0, "Tasman Sea", "sea"),
    ("indian ocean", -10.0, 75.0, "Indian Ocean", "sea"),
    ("gulf of alaska", 57.0, -145.0, "Gulf of Alaska", "sea"),
    ("strait of hormuz", 26.6, 56.4, "Strait of Hormuz", "sea"),
    ("taiwan strait", 24.0, 119.0, "Taiwan Strait", "sea"),
    ("strait of malacca", 3.0, 100.0, "Strait of Malacca", "sea"),
    # fleet AORs / commands (used when no specific sea is named)
    ("centcom", 24.0, 56.0, "CENTCOM AOR", "aor"),
    ("5th fleet", 24.0, 56.0, "5th Fleet AOR", "aor"),
    ("fifth fleet", 24.0, 56.0, "5th Fleet AOR", "aor"),
    ("6th fleet", 38.0, 10.0, "6th Fleet AOR", "aor"),
    ("sixth fleet", 38.0, 10.0, "6th Fleet AOR", "aor"),
    ("7th fleet", 15.0, 135.0, "7th Fleet AOR", "aor"),
    ("seventh fleet", 15.0, 135.0, "7th Fleet AOR", "aor"),
    ("3rd fleet", 25.0, -135.0, "3rd Fleet AOR", "aor"),
    ("third fleet", 25.0, -135.0, "3rd Fleet AOR", "aor"),
    ("4th fleet", 0.0, -70.0, "4th Fleet AOR", "aor"),
    ("indo-pacific", 15.0, 135.0, "Indo-Pacific", "aor"),
    ("southern seas", -25.0, -60.0, "Southern Seas (exercise)", "aor"),
    # homeports / named ports
    ("yokosuka", 35.29, 139.67, "Yokosuka, Japan", "port"),
    ("sasebo", 33.16, 129.72, "Sasebo, Japan", "port"),
    ("naval station norfolk", 36.95, -76.33, "Norfolk, VA", "port"),
    ("norfolk", 36.95, -76.33, "Norfolk, VA", "port"),
    ("newport news", 36.99, -76.43, "Newport News, VA", "port"),
    ("north island", 32.70, -117.22, "San Diego (North Island), CA", "port"),
    ("san diego", 32.70, -117.18, "San Diego, CA", "port"),
    ("bremerton", 47.56, -122.65, "Bremerton, WA", "port"),
    ("puget sound", 47.70, -122.70, "Puget Sound, WA", "port"),
    ("everett", 47.98, -122.22, "Everett, WA", "port"),
    ("mayport", 30.39, -81.42, "Mayport, FL", "port"),
    ("pearl harbor", 21.35, -157.95, "Pearl Harbor, HI", "port"),
    ("manama", 26.20, 50.60, "Manama, Bahrain", "port"),
    ("rota", 36.62, -6.35, "Rota, Spain", "port"),
    ("souda bay", 35.50, 24.10, "Souda Bay, Greece", "port"),
    ("singapore", 1.29, 103.85, "Singapore", "port"),
    ("los angeles", 33.74, -118.27, "Los Angeles, CA", "port"),
    # country fallbacks
    ("japan", 35.0, 138.0, "Japan", "country"),
    ("chile", -33.0, -72.0, "off Chile", "country"),
    ("philippines", 13.0, 122.0, "Philippines", "country"),
]
# longest alias first so "south china sea" wins over "china", "north island" over "island".
_REGIONS = sorted(_REGIONS_RAW, key=lambda r: len(r[0]), reverse=True)

# hull -> ship-name aliases (for sources that name a ship without its hull token).
NAME_ALIASES: dict[str, list[str]] = {
    hull: [name[len("USS ") :].lower()] for hull, (name, _) in ROSTER.items()
}

_HULL_RE = re.compile(r"\b(CVN|LHA|LHD)[\s-]?(\d{1,3})\b", re.IGNORECASE)
# "homeported" is deliberately excluded — a ship's home port is named even while
# it's deployed, so it isn't evidence of being in port right now.
_IN_PORT = re.compile(
    r"\b(in port|pierside|moored|maintenance|shipyard|drydock|dry dock|"
    r"RCOH|overhaul)\b",
    re.IGNORECASE,
)


@dataclass
class ShipPosition:
    name: str
    hull: str
    kind: str  # "carrier" | "amphib"
    lat: float
    lon: float
    region: str
    status: str  # "underway" | "in port"
    confidence: str  # "high" | "medium" | "low"
    source: str
    url: str
    as_of: str | None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "hull": self.hull,
            "kind": self.kind,
            "lat": self.lat,
            "lon": self.lon,
            "region": self.region,
            "status": self.status,
            "confidence": self.confidence,
            "source": self.source,
            "url": self.url,
            "asOf": self.as_of,
        }


def strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _best_region(window: str) -> tuple[float, float, str, str] | None:
    """Pick the strongest region in a text window: open water beats homeport."""
    low = window.lower()
    best: tuple[int, tuple[float, float, str, str]] | None = None
    for alias, lat, lon, label, kind in _REGIONS:
        if alias in low:
            w = _KIND_WEIGHT[kind]
            if best is None or w > best[0]:
                best = (w, (lat, lon, label, kind))
    return best[1] if best else None


def _ship_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    """Locate each rostered ship in the text: hull tokens first, then fall back
    to name aliases only for ships whose hull never appears (e.g. terse prose)."""
    spans: dict[str, list[tuple[int, int]]] = {}
    for m in _HULL_RE.finditer(text):
        hull = f"{m.group(1).upper()}-{int(m.group(2))}"
        if hull in ROSTER:
            spans.setdefault(hull, []).append(m.span())
    low = text.lower()
    for hull, aliases in NAME_ALIASES.items():
        if hull in spans:
            continue
        for alias in aliases:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                spans.setdefault(hull, []).append(m.span())
    return spans


def parse_positions(
    text: str, source: str, url: str, as_of: str | None
) -> list[ShipPosition]:
    """Extract one position per rostered ship from a tracker article's text.

    A ship's region is chosen by *accumulated* weight across all its mentions
    (status line + photo captions repeat the real sea), so a single neighbouring
    ship's location bleeding into one window can't win.
    """
    out: list[ShipPosition] = []
    for hull, occ in _ship_spans(text).items():
        name, kind = ROSTER[hull]
        # label -> [weight_sum, (lat, lon, rkind)]
        scores: dict[str, list] = {}
        in_port = False
        for start, end in occ:
            window = text[max(0, start - 80) : min(len(text), end + 220)]  # status follows the name
            if _IN_PORT.search(window):
                in_port = True
            region = _best_region(window)
            if region:
                lat, lon, label, rkind = region
                slot = scores.setdefault(label, [0, (lat, lon, rkind)])
                slot[0] += _KIND_WEIGHT[rkind]
        if not scores:
            continue  # location not recoverable — skip rather than guess
        label = max(scores, key=lambda k: (scores[k][0], _KIND_WEIGHT[scores[k][1][2]]))
        lat, lon, rkind = scores[label][1]
        status = "in port" if (in_port or rkind == "port") else "underway"
        confidence = {"port": "high", "sea": "medium", "aor": "low", "country": "low"}[rkind]
        out.append(
            ShipPosition(
                name=name,
                hull=hull,
                kind=kind,
                lat=lat,
                lon=lon,
                region=label,
                status=status,
                confidence=confidence,
                source=source,
                url=url,
                as_of=as_of,
            )
        )
    return out


# ---- fetching -----------------------------------------------------------

# USNI sits behind Cloudflare (TLS fingerprinting 403s httpx), but the WordPress
# category *feed* is open and carries each post's full HTML in content:encoded —
# so we read the latest tracker straight from the feed, no scraping needed.
USNI_CATEGORY = "https://news.usni.org/category/fleet-tracker"
# The category feed is scoped but can lag; the site feed often carries the newest
# tracker first. We read both and keep whichever post is most recent.
USNI_FEEDS = (
    "https://news.usni.org/feed",
    "https://news.usni.org/category/fleet-tracker/feed/",
)
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
_USNI_POST_RE = re.compile(
    r"https://news\.usni\.org/(20\d{2})/(\d{2})/(\d{2})/[a-z0-9-]*fleet[a-z0-9-]*"
)
_TWZ_DATE_RE = re.compile(r"as-of-([a-z]+)-(\d{1,2})-(20\d{2})", re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


async def _latest_usni_from_feed(
    client: httpx.AsyncClient,
) -> tuple[str, str | None, str] | None:
    """Newest fleet-tracker post across the USNI feeds: (url, as-of, body text).

    Picks the most recent tracker by the date embedded in its own URL (feed
    ordering isn't reliable, and feeds can lag each other).
    """
    best: tuple[str, str, str] | None = None  # (as_of, link, body)
    for feed_url in USNI_FEEDS:
        try:
            r = await client.get(feed_url, follow_redirects=True)
            if r.status_code >= 400:
                continue
            root = ET.fromstring(r.text)
        except (httpx.HTTPError, ET.ParseError):
            continue
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            m = _USNI_POST_RE.search(link)
            if not m:
                continue
            as_of = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            body = item.findtext(_CONTENT_NS) or item.findtext("description") or ""
            if body and (best is None or as_of > best[0]):
                best = (as_of, link, body)
    if best is None:
        return None
    return best[1], best[0], strip_html(best[2])


def _twz_date(url: str) -> str | None:
    m = _TWZ_DATE_RE.search(url)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    try:
        return date(int(m.group(3)), mon, int(m.group(2))).isoformat()
    except ValueError:
        return None


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, follow_redirects=True)
        if r.status_code >= 400:
            return None
        return strip_html(r.text)
    except httpx.HTTPError:
        return None


async def fetch_naval(
    client: httpx.AsyncClient, twz_url: str | None = None
) -> list[ShipPosition]:
    """Fetch the latest USNI post (auto-discovered) + an optional TWZ article,
    parse both, and merge — one position per ship, preferring USNI (fresher)."""
    by_hull: dict[str, ShipPosition] = {}

    usni = await _latest_usni_from_feed(client)
    if usni:
        url, as_of, text = usni
        for p in parse_positions(text, "USNI Fleet Tracker", url, as_of):
            by_hull[p.hull] = p

    if twz_url:
        text = await _fetch_text(client, twz_url)
        if text:
            for p in parse_positions(text, "TWZ Carrier Tracker", twz_url, _twz_date(twz_url)):
                by_hull.setdefault(p.hull, p)  # USNI wins ties

    return sorted(by_hull.values(), key=lambda s: s.hull)


class NavalService:
    """Fetches + caches carrier/amphib positions. Weekly data → long TTL.

    A browser User-Agent is required (USNI 403s default clients). An
    ``httpx.AsyncClient`` may be injected for tests.
    """

    def __init__(
        self,
        *,
        twz_url: str | None = DEFAULT_TWZ_URL,
        ttl_seconds: int = 21_600,  # 6h; trackers update ~weekly
        client: httpx.AsyncClient | None = None,
    ):
        self.twz_url = twz_url
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._lock = asyncio.Lock()
        self._ships: list[ShipPosition] = []
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
            client = self._client or httpx.AsyncClient(timeout=25.0, headers={"user-agent": _UA})
            try:
                ships = await fetch_naval(client, self.twz_url)
            finally:
                if owns:
                    await client.aclose()
            self._ships = ships
            self._updated = datetime.now(timezone.utc)
            self._fetched_at = monotonic()

    async def get(self) -> dict:
        await self.refresh()
        return {
            "updated": self._updated.isoformat() if self._updated else None,
            "ships": [s.to_dict() for s in self._ships],
            "sources": [USNI_CATEGORY] + ([self.twz_url] if self.twz_url else []),
        }
