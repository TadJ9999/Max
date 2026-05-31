from __future__ import annotations

import math

import httpx

from .models import SpaceWeather, KpPoint

KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
WIND_URL = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"


def _storm_scale(kp: float | None) -> str:
    if kp is None:
        return "Unknown"
    if kp < 5:
        return "Quiet"
    if kp < 6:
        return "G1 Minor"
    if kp < 7:
        return "G2 Moderate"
    if kp < 8:
        return "G3 Strong"
    if kp < 9:
        return "G4 Severe"
    return "G5 Extreme"


def _clean(v) -> float | None:
    """NOAA uses fill values (~ -9999.9) for missing samples."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > -9990 else None


async def fetch_space_weather(*, timeout: float = 15.0) -> SpaceWeather:
    sw = SpaceWeather()
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Planetary K-index: header row + [time_tag, Kp, ...]
        try:
            r = await client.get(KP_URL)
            r.raise_for_status()
            rows = r.json()
            if isinstance(rows, list) and len(rows) > 1:
                data = rows[1:]
                series = []
                for row in data[-24:]:
                    kp = _clean(row[1])
                    if kp is not None:
                        series.append(KpPoint(t=str(row[0]), kp=kp))
                sw.kp_series = series
                last = data[-1]
                sw.kp = _clean(last[1])
                sw.kp_time = str(last[0])
        except Exception:  # noqa: BLE001
            pass

        # Solar wind plasma: header + [time_tag, density, speed, temperature]
        try:
            r = await client.get(WIND_URL)
            r.raise_for_status()
            rows = r.json()
            if isinstance(rows, list) and len(rows) > 1:
                for row in reversed(rows[1:]):
                    speed = _clean(row[2])
                    if speed is not None:
                        sw.wind_speed = speed
                        sw.density = _clean(row[1])
                        sw.wind_time = str(row[0])
                        break
        except Exception:  # noqa: BLE001
            pass

    # Never emit non-finite numbers (NaN breaks browser JSON.parse).
    for attr in ("kp", "wind_speed", "density"):
        v = getattr(sw, attr)
        if v is not None and not math.isfinite(v):
            setattr(sw, attr, None)
    sw.storm = _storm_scale(sw.kp)
    return sw
