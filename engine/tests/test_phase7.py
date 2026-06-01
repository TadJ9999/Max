"""Phase 7 tests: force_offline kill-switch, two-model routing,
VRAM manager, and egress log endpoints."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max_engine.config import EngineConfig, IdleConfig
from max_engine.dsl import Command
from max_engine.providers.vram import LoadedModel, VramManager
from max_engine.router import resolve


def _run(coro):
    """Run a coroutine synchronously (no pytest-asyncio needed)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1. force_offline config round-trip
# ---------------------------------------------------------------------------

def test_force_offline_defaults_false():
    cfg = EngineConfig()
    assert cfg.force_offline is False


def test_force_offline_apply_overrides():
    from max_engine.config import _apply_overrides
    cfg = EngineConfig()
    _apply_overrides(cfg, {"force_offline": True})
    assert cfg.force_offline is True


def test_force_offline_save_load(tmp_path):
    from max_engine.config import CONFIG_FILE, _apply_overrides, save_overrides
    cfg = EngineConfig()
    cfg.force_offline = True
    orig = CONFIG_FILE
    import max_engine.config as _conf
    _conf.CONFIG_FILE = tmp_path / "test.json"
    try:
        save_overrides(cfg)
        data = json.loads((tmp_path / "test.json").read_text())
        assert data["force_offline"] is True
    finally:
        _conf.CONFIG_FILE = orig


# ---------------------------------------------------------------------------
# 2. force_offline HTTP gate
# ---------------------------------------------------------------------------

def test_force_offline_blocks_osint(monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    monkeypatch.setattr(main_mod, "config", EngineConfig(force_offline=True))
    client = TestClient(main_mod.app, raise_server_exceptions=False)
    r = client.get("/osint/heatmap")
    assert r.status_code == 503
    assert "force_offline" in r.json()["detail"]


def test_force_offline_blocks_market(monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    monkeypatch.setattr(main_mod, "config", EngineConfig(force_offline=True))
    client = TestClient(main_mod.app, raise_server_exceptions=False)
    r = client.get("/market/quotes")
    assert r.status_code == 503


def test_force_offline_blocks_sentinel(monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    monkeypatch.setattr(main_mod, "config", EngineConfig(force_offline=True))
    client = TestClient(main_mod.app, raise_server_exceptions=False)
    r = client.get("/sentinel/iss")
    assert r.status_code == 503


def test_force_offline_allows_health(monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    monkeypatch.setattr(main_mod, "config", EngineConfig(force_offline=True))
    client = TestClient(main_mod.app)
    r = client.get("/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 3. Resident model routing
# ---------------------------------------------------------------------------

def _cmd(action: str, provider: str = "default") -> Command:
    return Command(action=action, body="x", sigil=None, provider=provider, is_cloud=False)


def test_resident_model_routes_completion():
    cfg = EngineConfig()
    cfg.idle.resident_model = "qwen2.5-coder:3b"
    route = resolve(_cmd("completion"), cfg)
    assert route.model == "qwen2.5-coder:3b"
    assert route.provider == "ollama"
    assert not route.is_cloud


def test_no_resident_model_uses_task_default():
    cfg = EngineConfig()
    cfg.idle.resident_model = ""
    cfg.task_models["completion"] = "qwen2.5-coder:14b"
    route = resolve(_cmd("completion"), cfg)
    assert route.model == "qwen2.5-coder:14b"


def test_explicit_sigil_overrides_resident():
    cfg = EngineConfig()
    cfg.idle.resident_model = "qwen2.5-coder:3b"
    # @-sigil forces ollama but still picks per-task model
    route = resolve(_cmd("completion", provider="ollama"), cfg)
    assert route.model == cfg.task_models.get("completion", "qwen2.5-coder:14b")


# ---------------------------------------------------------------------------
# 4. IdleConfig fields
# ---------------------------------------------------------------------------

def test_idle_config_defaults():
    idle = IdleConfig()
    assert idle.resident_model == "qwen2.5-coder:3b"
    assert idle.resident_keep_alive == "-1"
    assert idle.vram_budget_mb == 11_000


def test_idle_apply_overrides():
    from max_engine.config import _apply_overrides
    cfg = EngineConfig()
    _apply_overrides(cfg, {
        "idle": {
            "resident_model": "phi3:mini",
            "resident_keep_alive": "30m",
            "vram_budget_mb": 8_000,
        }
    })
    assert cfg.idle.resident_model == "phi3:mini"
    assert cfg.idle.resident_keep_alive == "30m"
    assert cfg.idle.vram_budget_mb == 8_000


def test_idle_vram_budget_clamped():
    from max_engine.config import _apply_overrides
    cfg = EngineConfig()
    _apply_overrides(cfg, {"idle": {"vram_budget_mb": 0}})
    assert cfg.idle.vram_budget_mb == 1_000  # clamped to minimum


# ---------------------------------------------------------------------------
# 5. VramManager (mocked httpx)
# ---------------------------------------------------------------------------

def test_vram_get_loaded_parses_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "llama3:8b", "size_vram": 8 * 1024 * 1024 * 1024},
            {"name": "qwen2.5-coder:3b", "size_vram": 2 * 1024 * 1024 * 1024},
        ]
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    mgr = VramManager()
    loaded = _run(mgr.get_loaded(client=mock_client))
    assert len(loaded) == 2
    assert loaded[0].name == "llama3:8b"


def test_vram_get_loaded_handles_error():
    import httpx
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

    mgr = VramManager()
    loaded = _run(mgr.get_loaded(client=mock_client))
    assert loaded == []


def test_vram_evict_to_fit_skips_when_fits():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [
        {"name": "small:1b", "size_vram": 1 * 1024 * 1024 * 1024},
    ]}
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    mgr = VramManager()
    evicted = _run(mgr.evict_to_fit(
        new_model_size_mb=2_000,
        budget_mb=11_000,
        client=mock_client,
    ))
    assert evicted == []


def test_vram_evict_to_fit_evicts_largest_first():
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {"models": [
        {"name": "big:14b", "size_vram": 9 * 1024 * 1024 * 1024},
        {"name": "small:3b", "size_vram": 2 * 1024 * 1024 * 1024},
    ]}
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_get_resp)
    mock_client.post = AsyncMock(return_value=mock_post_resp)

    mgr = VramManager()
    evicted = _run(mgr.evict_to_fit(
        new_model_size_mb=5_000,
        budget_mb=11_000,
        client=mock_client,
    ))
    assert "big:14b" in evicted


def test_vram_evict_keeps_resident():
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {"models": [
        {"name": "big:14b", "size_vram": 9 * 1024 * 1024 * 1024},
        {"name": "resident:3b", "size_vram": 2 * 1024 * 1024 * 1024},
    ]}
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_get_resp)
    mock_client.post = AsyncMock(return_value=mock_post_resp)

    mgr = VramManager()
    evicted = _run(mgr.evict_to_fit(
        new_model_size_mb=5_000,
        budget_mb=11_000,
        keep="resident:3b",
        client=mock_client,
    ))
    assert "resident:3b" not in evicted
    assert "big:14b" in evicted


# ---------------------------------------------------------------------------
# 6. Egress log endpoints
# ---------------------------------------------------------------------------

def test_egress_log_returns_empty_when_missing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    monkeypatch.setattr(main_mod, "_EGRESS_LOG_PATH", tmp_path / "missing.log")
    client = TestClient(main_mod.app)
    r = client.get("/egress/log")
    assert r.status_code == 200
    assert r.json()["entries"] == []


def test_egress_log_parses_entries(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    log_path = tmp_path / "test.log"
    log_path.write_text(
        "2026-06-01T00:00:00Z provider=anthropic model=claude-sonnet-4-6 action=chat_done in=100 out=50\n"
        "2026-06-01T00:01:00Z provider=anthropic model=claude-sonnet-4-6 action=chat_start in=0 out=0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_mod, "_EGRESS_LOG_PATH", log_path)
    client = TestClient(main_mod.app)
    r = client.get("/egress/log")
    assert r.status_code == 200
    data = r.json()
    assert data["total_lines"] == 2
    assert len(data["entries"]) == 2
    # newest-first (reversed)
    assert data["entries"][0]["action"] == "chat_start"
    assert data["entries"][1]["in_tokens"] == 100


def test_egress_log_clear(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    log_path = tmp_path / "test.log"
    log_path.write_text("2026-06-01T00:00:00Z provider=anthropic model=x action=chat_done in=1 out=1\n")
    monkeypatch.setattr(main_mod, "_EGRESS_LOG_PATH", log_path)
    client = TestClient(main_mod.app)
    r = client.delete("/egress/log")
    assert r.status_code == 200
    assert r.json()["cleared"] is True
    assert log_path.read_text() == ""


def test_config_patch_force_offline(monkeypatch):
    from fastapi.testclient import TestClient
    import max_engine.main as main_mod
    cfg = EngineConfig()
    monkeypatch.setattr(main_mod, "config", cfg)
    with patch("max_engine.main.save_overrides"):
        client = TestClient(main_mod.app)
        r = client.put("/config", json={"force_offline": True})
    assert r.status_code == 200
    assert cfg.force_offline is True
