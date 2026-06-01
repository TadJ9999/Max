"""Tests for Google Calendar skill — OAuth flow, token refresh, events."""

import asyncio
import time

import httpx
import pytest

from max_engine.config import GoogleCalendarConfig
from max_engine.skills.calendar_skill import CalendarService


def _make_svc(cfg=None):
    if cfg is None:
        cfg = GoogleCalendarConfig(client_id="test-id")
    return CalendarService(cfg, client_id="test-id", client_secret="test-secret")


# ---- is_configured / is_authenticated ----------------------------------------

def test_not_configured_missing_secret():
    svc = CalendarService(GoogleCalendarConfig(), client_id="id", client_secret="")
    assert not svc._is_configured


def test_configured():
    svc = _make_svc()
    assert svc._is_configured


def test_not_authenticated():
    svc = _make_svc()
    assert not svc._is_authenticated


def test_authenticated_with_token():
    cfg = GoogleCalendarConfig(access_token="tok")
    svc = CalendarService(cfg, client_id="id", client_secret="sec")
    assert svc._is_authenticated


# ---- start_auth --------------------------------------------------------------

def test_start_auth_returns_google_url():
    svc = _make_svc()
    url = svc.start_auth()
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "calendar" in url
    assert "code_challenge" in url


# ---- handle_callback ---------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_callback_no_verifier():
    import max_engine.skills.calendar_skill as mod
    mod._pending_verifier = None
    svc = _make_svc()
    ok = await svc.handle_callback("code", lambda: None)
    assert not ok


@pytest.mark.asyncio
async def test_handle_callback_success(monkeypatch):
    import max_engine.skills.calendar_skill as mod
    mod._pending_verifier = "test_verifier"

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, **kw):
            return httpx.Response(200, json={
                "access_token": "acc",
                "refresh_token": "ref",
                "expires_in": 3600,
            })

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    svc = _make_svc()
    saved = []
    ok = await svc.handle_callback("code123", lambda: saved.append(True))
    assert ok
    assert svc._cfg.access_token == "acc"
    assert svc._cfg.refresh_token == "ref"
    assert len(saved) == 1


# ---- get_status --------------------------------------------------------------

def test_get_status():
    svc = _make_svc()
    s = svc.get_status()
    assert s["configured"] is True
    assert s["authenticated"] is False
    assert s["calendar_id"] == "primary"


# ---- list_events -------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_events(monkeypatch):
    cfg = GoogleCalendarConfig(
        access_token="tok", refresh_token="ref",
        token_expiry=time.time() + 9999, calendar_id="primary",
    )
    svc = CalendarService(cfg, client_id="id", client_secret="sec")

    events_json = {
        "items": [
            {
                "id": "evt1",
                "summary": "Team Standup",
                "start": {"dateTime": "2026-06-01T09:00:00Z"},
                "end": {"dateTime": "2026-06-01T09:30:00Z"},
                "description": "",
                "location": "",
                "htmlLink": "https://calendar.google.com/evt1",
            }
        ]
    }

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return httpx.Response(200, json=events_json)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    events = await svc.list_events(lambda: None)
    assert len(events) == 1
    assert events[0]["summary"] == "Team Standup"
    assert events[0]["id"] == "evt1"


# ---- create_event ------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_event(monkeypatch):
    cfg = GoogleCalendarConfig(
        access_token="tok", refresh_token="ref",
        token_expiry=time.time() + 9999, calendar_id="primary",
    )
    svc = CalendarService(cfg, client_id="id", client_secret="sec")

    created = {
        "id": "new-evt",
        "summary": "Meeting",
        "start": {"dateTime": "2026-06-05T14:00:00Z"},
        "htmlLink": "https://calendar.google.com/new-evt",
    }

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, **kw):
            return httpx.Response(200, json=created)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    event = await svc.create_event(
        "Meeting",
        "2026-06-05T14:00:00Z",
        "2026-06-05T15:00:00Z",
    )
    assert event["id"] == "new-evt"
    assert event["summary"] == "Meeting"


# ---- delete_event -----------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_event_success(monkeypatch):
    cfg = GoogleCalendarConfig(
        access_token="tok", refresh_token="ref",
        token_expiry=time.time() + 9999,
    )
    svc = CalendarService(cfg, client_id="id", client_secret="sec")

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def delete(self, url, **kw):
            return httpx.Response(204)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    ok = await svc.delete_event("evt1")
    assert ok is True
