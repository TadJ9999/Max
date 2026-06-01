"""Tests for Spotify skill — OAuth flow, token refresh, playback, search."""

import asyncio
import time

import httpx
import pytest

from max_engine.config import SpotifyConfig
from max_engine.skills.spotify import SpotifyService


def _make_svc(cfg=None):
    if cfg is None:
        cfg = SpotifyConfig(client_id="test-id")
    return SpotifyService(cfg, client_id="test-id", client_secret="test-secret")


# ---- is_configured / is_authenticated ----------------------------------------

def test_not_configured_no_client_id():
    svc = SpotifyService(SpotifyConfig(), client_id="", client_secret="")
    assert not svc._is_configured


def test_configured_with_client_id():
    svc = _make_svc()
    assert svc._is_configured


def test_not_authenticated_without_token():
    svc = _make_svc()
    assert not svc._is_authenticated


def test_authenticated_with_token():
    cfg = SpotifyConfig(access_token="tok")
    svc = SpotifyService(cfg, client_id="id", client_secret="sec")
    assert svc._is_authenticated


# ---- start_auth / PKCE -------------------------------------------------------

def test_start_auth_returns_spotify_url():
    svc = _make_svc()
    url = svc.start_auth()
    assert url.startswith("https://accounts.spotify.com/authorize")
    assert "code_challenge" in url
    assert "client_id=test-id" in url


def test_start_auth_sets_pending_verifier():
    import max_engine.skills.spotify as mod
    svc = _make_svc()
    svc.start_auth()
    assert mod._pending_verifier is not None


# ---- handle_callback ---------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_callback_no_pending_verifier():
    import max_engine.skills.spotify as mod
    mod._pending_verifier = None
    svc = _make_svc()
    ok = await svc.handle_callback("code123", lambda: None)
    assert not ok


@pytest.mark.asyncio
async def test_handle_callback_success(monkeypatch):
    import max_engine.skills.spotify as mod
    mod._pending_verifier = "test_verifier"

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, **kw):
            return httpx.Response(200, json={
                "access_token": "new_access",
                "refresh_token": "new_refresh",
                "expires_in": 3600,
            })

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    svc = _make_svc()
    saved = []
    ok = await svc.handle_callback("code123", lambda: saved.append(True))
    assert ok
    assert svc._cfg.access_token == "new_access"
    assert svc._cfg.refresh_token == "new_refresh"
    assert saved == [True]


# ---- control -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_control_play(monkeypatch):
    cfg = SpotifyConfig(access_token="tok", refresh_token="ref", token_expiry=time.time() + 9999)
    svc = SpotifyService(cfg, client_id="id", client_secret="sec")

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, **kw):
            return httpx.Response(204)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    result = await svc.control("play", lambda: None)
    assert result["ok"] is True


# ---- search ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_tracks(monkeypatch):
    cfg = SpotifyConfig(access_token="tok", refresh_token="ref", token_expiry=time.time() + 9999)
    svc = SpotifyService(cfg, client_id="id", client_secret="sec")

    track_json = {
        "tracks": {
            "items": [{
                "name": "Song",
                "artists": [{"name": "Artist"}],
                "album": {"name": "Album", "images": [{"url": "http://img"}]},
                "uri": "spotify:track:abc",
                "duration_ms": 210000,
            }]
        }
    }

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return httpx.Response(200, json=track_json)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    results = await svc.search("Song", save_fn=None)
    assert len(results) == 1
    assert results[0]["name"] == "Song"
    assert results[0]["artist"] == "Artist"


# ---- get_status unauthenticated ---------------------------------------------

@pytest.mark.asyncio
async def test_get_status_not_authenticated():
    svc = _make_svc()
    status = await svc.get_status(lambda: None)
    assert status["configured"] is True
    assert status["authenticated"] is False
    assert "track" not in status
