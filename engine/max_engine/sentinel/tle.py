from __future__ import annotations

import httpx

from .models import TLE

CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php"

# Curated groups exposed in the UI -> CelesTrak GROUP query value.
GROUPS: dict[str, tuple[str, str]] = {
    # id          (label,             celestrak group)
    "stations": ("Space Stations", "stations"),
    "visual": ("Brightest", "visual"),
    "starlink": ("Starlink", "starlink"),
    "oneweb": ("OneWeb", "oneweb"),
    "gps": ("GPS", "gps-ops"),
    "galileo": ("Galileo", "galileo"),
    "glonass": ("GLONASS", "glo-ops"),
    "beidou": ("BeiDou", "beidou"),
    "geo": ("Geostationary", "geo"),
    "weather": ("Weather", "weather"),
    "noaa": ("NOAA", "noaa"),
    "science": ("Science", "science"),
    "iridium": ("Iridium NEXT", "iridium-NEXT"),
    "planet": ("Planet", "planet"),
    "active": ("All Active", "active"),
    "last30": ("Last 30 Days", "last-30-days"),
}


def parse_tle(text: str) -> list[TLE]:
    """Parse CelesTrak 3-line (name / line1 / line2) records."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[TLE] = []
    i = 0
    n = len(lines)
    while i + 2 < n + 1 and i + 2 <= n:
        name = lines[i].strip()
        l1 = lines[i + 1] if i + 1 < n else ""
        l2 = lines[i + 2] if i + 2 < n else ""
        if l1.startswith("1 ") and l2.startswith("2 "):
            norad = l2[2:7].strip()
            out.append(TLE(name=name or f"NORAD {norad}", norad_id=norad, line1=l1, line2=l2))
            i += 3
        else:
            i += 1
    return out


async def fetch_group(group_id: str, *, timeout: float = 20.0) -> list[TLE]:
    """Fetch and parse a CelesTrak group's TLEs."""
    label_group = GROUPS.get(group_id)
    celes = label_group[1] if label_group else "stations"
    params = {"GROUP": celes, "FORMAT": "tle"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(CELESTRAK, params=params, headers={"User-Agent": "Max-Sentinel/1.0"})
        r.raise_for_status()
        return parse_tle(r.text)
