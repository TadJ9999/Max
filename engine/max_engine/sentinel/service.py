from __future__ import annotations

import asyncio
import time
from typing import Optional

from . import tle as tle_mod
from .asteroids import fetch_neos
from .fireballs import fetch_fireballs
from .iss import fetch_iss
from .launches import fetch_launches
from .models import (
    Fireball,
    FireballResponse,
    ISS,
    Launch,
    LaunchResponse,
    Neo,
    NeoResponse,
    SatGroup,
    SpaceWeather,
    TLE,
    TLEResponse,
)
from .space_weather import fetch_space_weather


class _Cache:
    """Tiny per-key TTL cache guarded by an async lock."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, object]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def get(self, key: str, ttl: float):
        hit = self._store.get(key)
        if hit and (time.monotonic() - hit[0]) < ttl:
            return hit[1]
        return None

    def put(self, key: str, value) -> None:
        self._store[key] = (time.monotonic(), value)


class SentinelService:
    """Aggregates space situational-awareness data. SGP4 propagation happens
    client-side (satellite.js Web Worker); this service serves raw TLEs plus
    NEO / space-weather / fireball / launch / ISS layers with TTL caching."""

    def __init__(
        self,
        *,
        nasa_key: str = "DEMO_KEY",
        tle_ttl: int = 7200,
        neo_ttl: int = 3600,
        sw_ttl: int = 600,
        fireball_ttl: int = 21600,
        launch_ttl: int = 3600,
        iss_ttl: int = 5,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._nasa_key = nasa_key or "DEMO_KEY"
        self._tle_ttl = tle_ttl
        self._neo_ttl = neo_ttl
        self._sw_ttl = sw_ttl
        self._fireball_ttl = fireball_ttl
        self._launch_ttl = launch_ttl
        self._iss_ttl = iss_ttl
        self._cache = _Cache()

    # ---- groups ----
    def groups(self) -> list[SatGroup]:
        return [SatGroup(id=gid, label=label) for gid, (label, _q) in tle_mod.GROUPS.items()]

    # ---- TLEs ----
    async def get_tle(self, group: str = "stations") -> TLEResponse:
        group = group if group in tle_mod.GROUPS else "stations"
        key = f"tle:{group}"
        async with self._cache._lock(key):
            cached = self._cache.get(key, self._tle_ttl)
            if cached is not None:
                return TLEResponse(group=group, count=len(cached), satellites=cached, cached=True, fetched_at=time.time())
            try:
                sats: list[TLE] = await tle_mod.fetch_group(group)
                self._cache.put(key, sats)
                return TLEResponse(group=group, count=len(sats), satellites=sats, fetched_at=time.time())
            except Exception as e:  # noqa: BLE001
                return TLEResponse(group=group, error=str(e))

    # ---- NEO ----
    async def get_neo(self) -> NeoResponse:
        key = "neo"
        async with self._cache._lock(key):
            cached = self._cache.get(key, self._neo_ttl)
            if cached is not None:
                return NeoResponse(
                    count=len(cached), hazardous_count=sum(n.hazardous for n in cached),
                    neos=cached, cached=True, fetched_at=time.time(),
                )
            try:
                neos: list[Neo] = await fetch_neos(self._nasa_key)
                self._cache.put(key, neos)
                return NeoResponse(
                    count=len(neos), hazardous_count=sum(n.hazardous for n in neos),
                    neos=neos, fetched_at=time.time(),
                )
            except Exception as e:  # noqa: BLE001
                return NeoResponse(error=str(e))

    # ---- space weather ----
    async def get_space_weather(self) -> SpaceWeather:
        key = "sw"
        async with self._cache._lock(key):
            cached = self._cache.get(key, self._sw_ttl)
            if cached is not None:
                sw: SpaceWeather = cached
                sw.cached = True
                return sw
            sw = await fetch_space_weather()
            sw.fetched_at = time.time()
            self._cache.put(key, sw)
            return sw

    # ---- fireballs ----
    async def get_fireballs(self) -> FireballResponse:
        key = "fireballs"
        async with self._cache._lock(key):
            cached = self._cache.get(key, self._fireball_ttl)
            if cached is not None:
                return FireballResponse(count=len(cached), fireballs=cached, cached=True, fetched_at=time.time())
            try:
                fbs: list[Fireball] = await fetch_fireballs()
                self._cache.put(key, fbs)
                return FireballResponse(count=len(fbs), fireballs=fbs, fetched_at=time.time())
            except Exception as e:  # noqa: BLE001
                return FireballResponse(error=str(e))

    # ---- launches ----
    async def get_launches(self) -> LaunchResponse:
        key = "launches"
        async with self._cache._lock(key):
            cached = self._cache.get(key, self._launch_ttl)
            if cached is not None:
                return LaunchResponse(count=len(cached), launches=cached, cached=True, fetched_at=time.time())
            try:
                lns: list[Launch] = await fetch_launches()
                self._cache.put(key, lns)
                return LaunchResponse(count=len(lns), launches=lns, fetched_at=time.time())
            except Exception as e:  # noqa: BLE001
                return LaunchResponse(error=str(e))

    # ---- ISS ----
    async def get_iss(self) -> ISS:
        key = "iss"
        async with self._cache._lock(key):
            cached = self._cache.get(key, self._iss_ttl)
            if cached is not None:
                iss: ISS = cached
                iss.cached = True
                return iss
            iss = await fetch_iss()
            iss.fetched_at = time.time()
            self._cache.put(key, iss)
            return iss

    # ---- AI payloads ----
    async def analyze_payload(self) -> dict:
        """Compact JSON snapshot for the AI analyst / chat context."""
        neo, sw, fb, ln, iss = await asyncio.gather(
            self.get_neo(), self.get_space_weather(), self.get_fireballs(),
            self.get_launches(), self.get_iss(),
        )
        hazardous = [n for n in neo.neos if n.hazardous][:8]
        return {
            "space_weather": {
                "kp": sw.kp, "storm": sw.storm,
                "solar_wind_kms": sw.wind_speed, "density": sw.density,
            },
            "near_earth_objects": {
                "today": neo.count, "hazardous": neo.hazardous_count,
                "notable": [
                    {
                        "name": n.name, "hazardous": n.hazardous,
                        "miss_lunar": n.miss_lunar, "diameter_max_m": n.diameter_max_m,
                        "velocity_kms": n.velocity_kms, "approach": n.approach_date,
                    }
                    for n in (hazardous or neo.neos[:8])
                ],
            },
            "fireballs_recent": [
                {"date": f.date, "energy_kt": f.energy_kt, "lat": f.lat, "lon": f.lon}
                for f in fb.fireballs[:5]
            ],
            "upcoming_launches": [
                {"name": l.name, "provider": l.provider, "net": l.net, "pad": l.pad}
                for l in ln.launches[:5]
            ],
            "iss": {"lat": iss.lat, "lon": iss.lon, "crew": iss.crew},
        }

    async def chat_payload(self, messages: Optional[list] = None) -> dict:
        return await self.analyze_payload()

    def sources(self) -> list[dict]:
        return [
            {"name": "CelesTrak", "kind": "TLE", "key": False},
            {"name": "NASA NeoWs", "kind": "NEO", "key": True},
            {"name": "JPL SBDB", "kind": "Orbital elements", "key": False},
            {"name": "NOAA SWPC", "kind": "Space weather", "key": False},
            {"name": "NASA CNEOS", "kind": "Fireballs", "key": False},
            {"name": "TheSpaceDevs LL2", "kind": "Launches", "key": False},
            {"name": "wheretheiss.at / open-notify", "kind": "ISS", "key": False},
        ]
