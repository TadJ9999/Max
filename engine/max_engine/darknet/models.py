from __future__ import annotations

from pydantic import BaseModel


class TorStatus(BaseModel):
    running: bool
    bootstrapped: int = 0        # 0–100 bootstrap progress
    circuit_established: bool = False
    exit_ip: str | None = None
    circuit_age_seconds: int = 0
    socks_port: int = 9050


class FetchResult(BaseModel):
    url: str
    title: str | None = None
    html: str
    status_code: int = 200
    is_onion: bool = False
    fetch_time_ms: int = 0


class SearchResult(BaseModel):
    title: str
    url: str
    description: str | None = None
    is_onion: bool = False
