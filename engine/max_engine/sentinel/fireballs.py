from __future__ import annotations

import httpx

from .models import Fireball

FIREBALL_API = "https://ssd-api.jpl.nasa.gov/fireball.api"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coord(val, hemi) -> float | None:
    n = _num(val)
    if n is None:
        return None
    if hemi in ("S", "W"):
        n = -n
    return n


async def fetch_fireballs(*, limit: int = 30, timeout: float = 15.0) -> list[Fireball]:
    """NASA CNEOS fireball (atmospheric impact) events. No API key required."""
    out: list[Fireball] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(FIREBALL_API, params={"limit": limit})
        r.raise_for_status()
        data = r.json()
        fields = data.get("fields", [])
        idx = {name: i for i, name in enumerate(fields)}

        def get(row, key):
            i = idx.get(key)
            return row[i] if i is not None and i < len(row) else None

        for row in data.get("data", []):
            out.append(
                Fireball(
                    date=str(get(row, "date") or ""),
                    energy_kt=_num(get(row, "energy")),
                    impact_e_kt=_num(get(row, "impact-e")),
                    lat=_coord(get(row, "lat"), get(row, "lat-dir")),
                    lon=_coord(get(row, "lon"), get(row, "lon-dir")),
                    altitude_km=_num(get(row, "alt")),
                    velocity_kms=_num(get(row, "vel")),
                )
            )
    return out
