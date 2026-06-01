"""Google Calendar skill — OAuth2 PKCE flow + event CRUD."""

from __future__ import annotations

import base64
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from ..capabilities.interface import Capability
from ..config import GoogleCalendarConfig

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"

_SCOPES = " ".join([
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
])

_pending_verifier: str | None = None


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode()[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


class CalendarService:
    def __init__(self, cfg: GoogleCalendarConfig, client_id: str, client_secret: str) -> None:
        self._cfg = cfg
        self._client_id = client_id or cfg.client_id
        self._client_secret = client_secret

    @property
    def _is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

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
            "scope": _SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge_method": "S256",
            "code_challenge": challenge,
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
            "client_secret": self._client_secret,
            "code_verifier": verifier,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            return False
        tok = resp.json()
        self._cfg.access_token = tok.get("access_token", "")
        if "refresh_token" in tok:
            self._cfg.refresh_token = tok["refresh_token"]
        self._cfg.token_expiry = time.time() + tok.get("expires_in", 3600)
        save_fn()
        return True

    async def _ensure_token(self, save_fn) -> bool:
        if not self._cfg.refresh_token:
            return bool(self._cfg.access_token)
        if time.time() < self._cfg.token_expiry - 60:
            return True
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._cfg.refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
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

    def get_status(self) -> dict:
        return {
            "configured": self._is_configured,
            "authenticated": self._is_authenticated,
            "calendar_id": self._cfg.calendar_id,
        }

    async def list_events(
        self, save_fn, max_results: int = 15, days_ahead: int = 14
    ) -> list[dict]:
        await self._ensure_token(save_fn)
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()
        params = {
            "calendarId": self._cfg.calendar_id,
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": max_results,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                f"{_CALENDAR_BASE}/calendars/{self._cfg.calendar_id}/events",
                params=params,
                headers=self._auth_headers(),
            )
        if resp.status_code != 200:
            return []
        items = resp.json().get("items", [])
        events = []
        for item in items:
            start = item.get("start", {})
            end = item.get("end", {})
            events.append({
                "id": item.get("id", ""),
                "summary": item.get("summary", "(No title)"),
                "description": item.get("description", ""),
                "start": start.get("dateTime") or start.get("date", ""),
                "end": end.get("dateTime") or end.get("date", ""),
                "location": item.get("location", ""),
                "html_link": item.get("htmlLink", ""),
            })
        return events

    async def create_event(
        self,
        summary: str,
        start_dt: str,
        end_dt: str,
        description: str = "",
        location: str = "",
        save_fn=None,
    ) -> dict:
        if save_fn:
            await self._ensure_token(save_fn)
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_dt, "timeZone": "UTC"},
            "end": {"dateTime": end_dt, "timeZone": "UTC"},
        }
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(
                f"{_CALENDAR_BASE}/calendars/{self._cfg.calendar_id}/events",
                json=body,
                headers=self._auth_headers(),
            )
        if resp.status_code not in (200, 201):
            raise ValueError(f"Google Calendar API error {resp.status_code}: {resp.text[:200]}")
        item = resp.json()
        start = item.get("start", {})
        return {
            "id": item.get("id", ""),
            "summary": item.get("summary", ""),
            "start": start.get("dateTime") or start.get("date", ""),
            "html_link": item.get("htmlLink", ""),
        }

    async def delete_event(self, event_id: str, save_fn=None) -> bool:
        if save_fn:
            await self._ensure_token(save_fn)
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.delete(
                f"{_CALENDAR_BASE}/calendars/{self._cfg.calendar_id}/events/{event_id}",
                headers=self._auth_headers(),
            )
        return resp.status_code in (200, 204)


class CalendarCapability(Capability):
    name = "calendar"
    description = "View and manage Google Calendar events."
    domains = ["calendar"]

    def __init__(self, service: CalendarService) -> None:
        self._svc = service

    async def invoke(self, query: str, context: dict | None = None):
        import json
        try:
            events = await self._svc.list_events(save_fn=lambda: None)
            yield json.dumps(events, indent=2)
        except Exception as e:
            yield f"Calendar error: {e}"

    def status(self) -> dict:
        s = self._svc.get_status()
        return {"available": s["configured"], "connected": s["authenticated"]}
