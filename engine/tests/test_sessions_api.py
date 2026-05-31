"""/sessions endpoint tests (structure + routing; execution covered in test_delegate)."""

from fastapi.testclient import TestClient

import max_engine.main as m


def _client() -> TestClient:
    return TestClient(m.app)


def test_create_and_list_sessions():
    c = _client()
    r = c.post(
        "/sessions",
        json={
            "tasks": [
                {"task": "add a function", "provider": "ollama"},
                {"task": "write tests", "provider": "claude", "action": "generate"},
            ]
        },
    )
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert len(sessions) == 2
    by_provider = {s["provider"]: s for s in sessions}
    assert by_provider["ollama"]["is_cloud"] is False
    assert by_provider["claude"]["is_cloud"] is True
    assert by_provider["claude"]["model"].startswith("claude-")

    # each is retrievable individually
    one = c.get(f"/sessions/{sessions[0]['id']}")
    assert one.status_code == 200
    assert one.json()["id"] == sessions[0]["id"]

    listing = c.get("/sessions").json()["sessions"]
    ids = {s["id"] for s in listing}
    assert {s["id"] for s in sessions} <= ids


def test_get_unknown_session_404():
    assert _client().get("/sessions/nope").status_code == 404


def test_cloud_submission_blocked_when_disabled(monkeypatch):
    monkeypatch.setattr(m.config, "allow_cloud", False)
    r = _client().post("/sessions", json={"tasks": [{"task": "x", "provider": "claude"}]})
    assert r.status_code == 403
