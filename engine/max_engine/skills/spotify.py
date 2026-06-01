"""Spotify skill — OAuth PKCE flow + playback control + search."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from ..capabilities.interface import Capability
from ..config import SpotifyConfig

_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API_BASE = "https://api.spotify.com/v1"

_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-library-read",
    "playlist-read-private",
])

# in-memory PKCE verifier (one at a time)
_pending_verifier: str | None = None


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode()[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


class SpotifyService:
    def __init__(self, cfg: SpotifyConfig, client_id: str, client_secret: str) -> None:
        self._cfg = cfg
        self._client_id = client_id or cfg.client_id
        self._client_secret = client_secret  # from env only

    @property
    def _is_configured(self) -> bool:
        return bool(self._client_id)

    @property
    def _is_authenticated(self) -> bool:
        return bool(self._cfg.access_token)

    def start_auth(self) -> str:
        global _pending_verifier
        verifier, challenge = _pkce_pair()
        _pending_verifier = verifier
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._cfg.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": _SCOPES,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def handle_callback(self, code: str, save_fn) -> bool:
        global _pending_verifier
        if not _pending_verifier:
            return False
        verifier = _pending_verifier
        _pending_verifier = None

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._cfg.redirect_uri,
            "client_id": self._client_id,
            "code_verifier": verifier,
        }
        headers: dict = {"Content-Type": "application/x-www-form-urlencoded"}
        if self._client_secret:
            creds = base64.b64encode(
                f"{self._client_id}:{self._client_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {creds}"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_TOKEN_URL, data=data, headers=headers)
        if resp.status_code != 200:
            return False
        tok = resp.json()
        self._cfg.access_token = tok.get("access_token", "")
        self._cfg.refresh_token = tok.get("refresh_token", "")
        self._cfg.token_expiry = time.time() + tok.get("expires_in", 3600)
        save_fn()
        return True

    async def _ensure_token(self, save_fn) -> bool:
        if not self._cfg.refresh_token:
            return False
        if time.time() < self._cfg.token_expiry - 60:
            return True
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._cfg.refresh_token,
            "client_id": self._client_id,
        }
        headers: dict = {"Content-Type": "application/x-www-form-urlencoded"}
        if self._client_secret:
            creds = base64.b64encode(
                f"{self._client_id}:{self._client_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {creds}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_TOKEN_URL, data=data, headers=headers)
        if resp.status_code != 200:
            return False
        tok = resp.json()
        self._cfg.access_token = tok.get("access_token", self._cfg.access_token)
        if "refresh_token" in tok:
            self._cfg.refresh_token = tok["refresh_token"]
        self._cfg.token_expiry = time.time() + tok.get("expires_in", 3600)
        save_fn()
        return True

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._cfg.access_token}"}

    async def get_status(self, save_fn) -> dict:
        base: dict = {
            "configured": self._is_configured,
            "authenticated": self._is_authenticated,
            "client_id": self._client_id[:8] + "..." if self._client_id else "",
        }
        if not self._is_authenticated:
            return base
        await self._ensure_token(save_fn)
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"{_API_BASE}/me/player",
                    headers=self._auth_headers(),
                )
            if resp.status_code == 200 and resp.text:
                player = resp.json()
                item = player.get("item") or {}
                base["is_playing"] = player.get("is_playing", False)
                base["track"] = {
                    "name": item.get("name", ""),
                    "artist": ", ".join(
                        a.get("name", "") for a in item.get("artists", [])
                    ),
                    "album": (item.get("album") or {}).get("name", ""),
                    "duration_ms": item.get("duration_ms", 0),
                    "progress_ms": player.get("progress_ms", 0),
                    "uri": item.get("uri", ""),
                    "image": (
                        (item.get("album") or {}).get("images", [{}])[0].get("url", "")
                        if (item.get("album") or {}).get("images") else ""
                    ),
                }
        except Exception:
            pass
        return base

    async def control(self, action: str, save_fn) -> dict:
        await self._ensure_token(save_fn)
        method, endpoint = {
            "play": ("PUT", "/me/player/play"),
            "pause": ("PUT", "/me/player/pause"),
            "next": ("POST", "/me/player/next"),
            "prev": ("POST", "/me/player/previous"),
        }.get(action, ("PUT", "/me/player/play"))
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.request(
                method,
                f"{_API_BASE}{endpoint}",
                headers=self._auth_headers(),
            )
        return {"action": action, "ok": resp.status_code in (200, 204)}

    async def play_uri(self, uri: str, save_fn) -> dict:
        await self._ensure_token(save_fn)
        body: dict = {}
        if uri.startswith("spotify:track:"):
            body = {"uris": [uri]}
        else:
            body = {"context_uri": uri}
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.put(
                f"{_API_BASE}/me/player/play",
                json=body,
                headers=self._auth_headers(),
            )
        return {"uri": uri, "ok": resp.status_code in (200, 204)}

    async def search(self, query: str, types: str = "track", limit: int = 10, save_fn=None) -> list[dict]:
        if save_fn:
            await self._ensure_token(save_fn)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_API_BASE}/search",
                params={"q": query, "type": types, "limit": limit},
                headers=self._auth_headers(),
            )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results: list[dict] = []
        for track in data.get("tracks", {}).get("items", []):
            results.append({
                "type": "track",
                "name": track.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in track.get("artists", [])),
                "album": (track.get("album") or {}).get("name", ""),
                "uri": track.get("uri", ""),
                "duration_ms": track.get("duration_ms", 0),
                "image": (
                    (track.get("album") or {}).get("images", [{}])[0].get("url", "")
                    if (track.get("album") or {}).get("images") else ""
                ),
            })
        return results


class SpotifyCapability(Capability):
    name = "spotify"
    description = "Control Spotify playback and search for music."
    domains = ["spotify"]

    def __init__(self, service: SpotifyService) -> None:
        self._svc = service

    async def invoke(self, query: str, context: dict | None = None):
        results = await self._svc.search(query, save_fn=None)
        import json
        yield json.dumps(results[:5], indent=2)

    def status(self) -> dict:
        return {
            "available": self._svc._is_configured,
            "connected": self._svc._is_authenticated,
        }
