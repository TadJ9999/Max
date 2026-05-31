from __future__ import annotations

import asyncio
from datetime import date

import httpx

from .models import Neo, OrbitElements

NEOWS_FEED = "https://api.nasa.gov/neo/rest/v1/feed"
SBDB = "https://ssd-api.jpl.nasa.gov/sbdb.api"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _orbit_for(client: httpx.AsyncClient, des: str) -> OrbitElements | None:
    """Fetch heliocentric Keplerian elements from JPL SBDB for one object."""
    try:
        r = await client.get(SBDB, params={"sstr": des, "full-prec": "false"})
        r.raise_for_status()
        data = r.json()
        elems = {e.get("name"): e.get("value") for e in data.get("orbit", {}).get("elements", [])}
        epoch = data.get("orbit", {}).get("epoch")
        return OrbitElements(
            a=_num(elems.get("a")),
            e=_num(elems.get("e")),
            i=_num(elems.get("i")),
            om=_num(elems.get("om")),
            w=_num(elems.get("w")),
            ma=_num(elems.get("ma")),
            epoch=_num(epoch),
        )
    except Exception:  # noqa: BLE001
        return None


async def fetch_neos(api_key: str, *, with_orbits: int = 12, timeout: float = 20.0) -> list[Neo]:
    """NASA NeoWs feed for today, enriched with SBDB orbital elements for the
    closest `with_orbits` objects (used to draw orbit ellipses in SolarView)."""
    today = date.today().isoformat()
    out: list[Neo] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(
            NEOWS_FEED,
            params={"start_date": today, "end_date": today, "api_key": api_key or "DEMO_KEY"},
        )
        r.raise_for_status()
        by_day = r.json().get("near_earth_objects", {})
        for day in by_day.values():
            for o in day:
                ca = (o.get("close_approach_data") or [{}])[0]
                dia = (o.get("estimated_diameter") or {}).get("meters", {})
                miss = ca.get("miss_distance") or {}
                vel = ca.get("relative_velocity") or {}
                out.append(
                    Neo(
                        id=str(o.get("id", "")),
                        name=str(o.get("name", "")).replace("(", "").replace(")", "").strip(),
                        hazardous=bool(o.get("is_potentially_hazardous_asteroid")),
                        diameter_min_m=round(dia["estimated_diameter_min"]) if dia.get("estimated_diameter_min") else None,
                        diameter_max_m=round(dia["estimated_diameter_max"]) if dia.get("estimated_diameter_max") else None,
                        approach_epoch_ms=int(ca["epoch_date_close_approach"]) if ca.get("epoch_date_close_approach") else None,
                        approach_date=str(ca.get("close_approach_date_full") or ca.get("close_approach_date") or ""),
                        miss_km=round(float(miss["kilometers"])) if miss.get("kilometers") else None,
                        miss_lunar=round(float(miss["lunar"]), 1) if miss.get("lunar") else None,
                        velocity_kms=round(float(vel["kilometers_per_second"]), 2) if vel.get("kilometers_per_second") else None,
                        jpl_url=str(o.get("nasa_jpl_url", "")),
                    )
                )
        out.sort(key=lambda n: n.approach_epoch_ms or 0)

        # Enrich the closest N with orbital elements (bounded concurrency).
        targets = sorted(out, key=lambda n: n.miss_km if n.miss_km is not None else 1 << 62)[:with_orbits]
        results = await asyncio.gather(*[_orbit_for(client, n.name) for n in targets], return_exceptions=True)
        for n, orb in zip(targets, results):
            if isinstance(orb, OrbitElements):
                n.orbit = orb

    return out
