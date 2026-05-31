from __future__ import annotations

from pydantic import BaseModel, Field


class TLE(BaseModel):
    """A single Two-Line Element set (raw — propagated client-side)."""

    name: str
    norad_id: str = ""
    line1: str
    line2: str


class SatGroup(BaseModel):
    id: str
    label: str
    count: int = 0


class TLEResponse(BaseModel):
    group: str
    count: int = 0
    satellites: list[TLE] = Field(default_factory=list)
    fetched_at: float = 0.0
    cached: bool = False
    error: str = ""


class OrbitElements(BaseModel):
    """Heliocentric Keplerian elements for drawing an asteroid's orbit."""

    a: float | None = None        # semi-major axis (AU)
    e: float | None = None        # eccentricity
    i: float | None = None        # inclination (deg)
    om: float | None = None       # longitude of ascending node (deg)
    w: float | None = None        # argument of perihelion (deg)
    ma: float | None = None       # mean anomaly (deg)
    epoch: float | None = None    # epoch (JD)


class Neo(BaseModel):
    id: str
    name: str
    hazardous: bool = False
    diameter_min_m: int | None = None
    diameter_max_m: int | None = None
    approach_epoch_ms: int | None = None
    approach_date: str = ""
    miss_km: int | None = None
    miss_lunar: float | None = None
    velocity_kms: float | None = None
    jpl_url: str = ""
    orbit: OrbitElements | None = None


class NeoResponse(BaseModel):
    count: int = 0
    hazardous_count: int = 0
    neos: list[Neo] = Field(default_factory=list)
    fetched_at: float = 0.0
    cached: bool = False
    error: str = ""


class KpPoint(BaseModel):
    t: str
    kp: float


class SpaceWeather(BaseModel):
    kp: float | None = None
    kp_time: str = ""
    kp_series: list[KpPoint] = Field(default_factory=list)
    storm: str = "Unknown"
    wind_speed: float | None = None   # km/s
    density: float | None = None      # protons/cm^3
    wind_time: str = ""
    fetched_at: float = 0.0
    cached: bool = False
    error: str = ""


class Fireball(BaseModel):
    date: str
    energy_kt: float | None = None
    impact_e_kt: float | None = None
    lat: float | None = None
    lon: float | None = None
    altitude_km: float | None = None
    velocity_kms: float | None = None


class FireballResponse(BaseModel):
    count: int = 0
    fireballs: list[Fireball] = Field(default_factory=list)
    fetched_at: float = 0.0
    cached: bool = False
    error: str = ""


class Launch(BaseModel):
    id: str = ""
    name: str = ""
    provider: str = ""
    vehicle: str = ""
    pad: str = ""
    location: str = ""
    net: str = ""           # ISO launch time
    status: str = ""
    image: str = ""
    webcast: str = ""


class LaunchResponse(BaseModel):
    count: int = 0
    launches: list[Launch] = Field(default_factory=list)
    fetched_at: float = 0.0
    cached: bool = False
    error: str = ""


class ISS(BaseModel):
    lat: float | None = None
    lon: float | None = None
    altitude_km: float | None = None
    velocity_kms: float | None = None
    timestamp: int | None = None
    crew: list[str] = Field(default_factory=list)
    fetched_at: float = 0.0
    cached: bool = False
    error: str = ""
