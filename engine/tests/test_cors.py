"""CORS is enabled so local clients (the Tauri webview, browser previews) can
call the engine from a different origin."""

from fastapi.testclient import TestClient

from max_engine.main import app

client = TestClient(app)


def test_simple_request_gets_cors_header():
    r = client.get("/health", headers={"Origin": "http://localhost:1420"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"


def test_preflight_allows_post_to_sessions():
    r = client.options(
        "/sessions",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
    assert "POST" in r.headers.get("access-control-allow-methods", "")
