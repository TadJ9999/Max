"""/config — UI-editable settings (get, update, persist, validation)."""

from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine import config as config_module
from max_engine.config import EngineConfig


def _isolated(monkeypatch, tmp_path) -> TestClient:
    # Fresh config object + temp persistence file so tests don't bleed into
    # each other or write a real .maxconfig.json.
    monkeypatch.setattr(m, "config", EngineConfig())
    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / ".maxconfig.json")
    return TestClient(m.app)


def test_get_config_defaults(monkeypatch, tmp_path):
    g = _isolated(monkeypatch, tmp_path).get("/config").json()
    assert g["allow_cloud"] is True
    assert g["delegate"]["mode"] == "smart-auto"
    assert "cloud_key_set" in g  # boolean, never the key itself
    assert isinstance(g["workspace_allowlist"], list)


def test_update_persists_and_reflects(monkeypatch, tmp_path):
    c = _isolated(monkeypatch, tmp_path)
    r = c.put(
        "/config",
        json={
            "allow_cloud": False,
            "delegate": {"mode": "manual", "max_parallel_local": 3},
            "workspace_allowlist": ["C:/work", "D:/code"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["allow_cloud"] is False
    assert body["delegate"]["mode"] == "manual"
    assert body["delegate"]["max_parallel_local"] == 3
    assert body["workspace_allowlist"] == ["C:/work", "D:/code"]

    assert (tmp_path / ".maxconfig.json").exists()
    assert c.get("/config").json()["allow_cloud"] is False


def test_parallel_limits_floored_to_one(monkeypatch, tmp_path):
    c = _isolated(monkeypatch, tmp_path)
    body = c.put("/config", json={"delegate": {"max_parallel_local": 0}}).json()
    assert body["delegate"]["max_parallel_local"] == 1


def test_invalid_mode_rejected(monkeypatch, tmp_path):
    c = _isolated(monkeypatch, tmp_path)
    assert c.put("/config", json={"delegate": {"mode": "bogus"}}).status_code == 400


def test_idle_keep_alive_persists(monkeypatch, tmp_path):
    c = _isolated(monkeypatch, tmp_path)
    assert c.get("/config").json()["idle"]["keep_alive"] == "10m"  # default
    body = c.put("/config", json={"idle": {"keep_alive": "30m"}}).json()
    assert body["idle"]["keep_alive"] == "30m"
    assert c.get("/config").json()["idle"]["keep_alive"] == "30m"  # persisted
