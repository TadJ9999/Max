"""FIM completion helper + /complete endpoint."""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.complete import fim_complete


def test_fim_complete_sends_prefix_suffix_and_returns_middle():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "    return a + b"})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t")
        out = await fim_complete(
            "def add(a, b):\n", "\n\nprint(add(1, 2))", model="qwen2.5-coder:3b", client=client
        )
        await client.aclose()
        return out

    out = asyncio.run(run())
    assert out == "    return a + b"
    body = captured["body"]
    assert body["prompt"] == "def add(a, b):\n"
    assert body["suffix"] == "\n\nprint(add(1, 2))"
    assert body["stream"] is False


def test_fim_complete_best_effort_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t")
        out = await fim_complete("x", "y", model="m", client=client)
        await client.aclose()
        return out

    assert asyncio.run(run()) == ""


def test_fim_complete_empty_input_short_circuits():
    assert asyncio.run(fim_complete("", "", model="m")) == ""


def test_complete_endpoint(monkeypatch):
    async def fake_fim(prefix, suffix="", **kw):
        return f"<{prefix}|{suffix}>"

    monkeypatch.setattr(m, "fim_complete", fake_fim)
    r = TestClient(m.app).post("/complete", json={"prefix": "a", "suffix": "b"})
    assert r.status_code == 200
    body = r.json()
    assert body["completion"] == "<a|b>"
    assert body["model"]  # the configured completion model surfaced
