from __future__ import annotations

import httpx

from .models import ISS

WTIA = "https://api.wheretheiss.at/v1/satellites/25544"
CREW = "http://api.open-notify.org/astros.json"


async def fetch_iss(*, timeout: float = 12.0) -> ISS:
    iss = ISS()
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.get(WTIA)
            r.raise_for_status()
            d = r.json()
            iss.lat = d.get("latitude")
            iss.lon = d.get("longitude")
            iss.altitude_km = d.get("altitude")
            iss.velocity_kms = round(float(d["velocity"]) / 3600.0, 2) if d.get("velocity") else None
            iss.timestamp = d.get("timestamp")
        except Exception:  # noqa: BLE001
            pass

        # Crew (open-notify is occasionally down — best effort).
        try:
            r = await client.get(CREW)
            r.raise_for_status()
            people = r.json().get("people", [])
            iss.crew = [p.get("name", "") for p in people if p.get("craft") == "ISS"]
        except Exception:  # noqa: BLE001
            pass

    return iss
