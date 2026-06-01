"""Ollama adapter test using a mocked HTTP transport (no live server needed)."""

import asyncio
import json

import httpx

from max_engine.providers.ollama import OllamaProvider


def test_ollama_streams_and_joins_chunks():
    lines = [
        '{"message":{"content":"Hello"},"done":false}',
        '{"message":{"content":" world"},"done":false}',
        '{"message":{"content":""},"done":true}',
    ]
    body = "\n".join(lines) + "\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        assert request.method == "POST"
        return httpx.Response(200, text=body)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OllamaProvider(base_url="http://test", client=client)
        chunks = [
            c async for c in provider.chat("qwen2.5-coder:14b", [{"role": "user", "content": "hi"}])
        ]
        await client.aclose()
        return chunks

    chunks = asyncio.run(run())
    assert "".join(c.text for c in chunks) == "Hello world"
    assert chunks[-1].done is True


def test_ollama_passes_keep_alive():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text='{"message":{"content":"x"},"done":true}\n')

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OllamaProvider(base_url="http://test", client=client, keep_alive="5m")
        _ = [c async for c in provider.chat("m", [{"role": "user", "content": "hi"}])]
        await client.aclose()

    asyncio.run(run())
    assert captured["body"]["keep_alive"] == "5m"


def test_ollama_applies_default_options_with_param_override():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text='{"message":{"content":"x"},"done":true}\n')

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OllamaProvider(
            base_url="http://test",
            client=client,
            default_options={"num_ctx": 8192, "num_gpu": 33},
        )
        # A per-call param overrides the configured default for the same key.
        _ = [c async for c in provider.chat("m", [{"role": "user", "content": "hi"}], num_ctx=4096)]
        await client.aclose()

    asyncio.run(run())
    opts = captured["body"]["options"]
    assert opts["num_gpu"] == 33  # from defaults
    assert opts["num_ctx"] == 4096  # per-call override wins


def test_probe_latency_reports_median(monkeypatch):
    from max_engine.models import benchmark as bm

    # Three streamed runs; assert TTFT + total are positive and runs counted.
    body = (
        '{"message":{"content":"ready"},"done":false}\n'
        '{"message":{"content":""},"done":true}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        sent = json.loads(request.content)
        assert sent["options"]["num_predict"] == 16  # latency cap
        return httpx.Response(200, text=body)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        result = await bm.probe_latency("m", base_url="http://test", client=client, runs=3)
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result["runs"] == 3
    assert result["ttft_ms"] >= 0.0
    assert result["total_ms"] >= result["ttft_ms"]


def test_benchmark_store_latency_upsert_is_disjoint(tmp_path):
    from max_engine.models.store import BenchmarkStore

    store = BenchmarkStore(str(tmp_path / "b.db"))
    store.upsert("m", ttft_ms=120.0, tokens_per_sec=42.0, prompt_tokens=5, total_tokens=10)
    store.upsert_latency("m", ttft_ms=88.0, total_ms=300.0)

    row = store.get("m")
    # Throughput fields survive the latency upsert (and vice-versa).
    assert row["tokens_per_sec"] == 42.0
    assert row["ttft_ms"] == 120.0
    assert row["lat_ttft_ms"] == 88.0
    assert row["lat_total_ms"] == 300.0


def test_ollama_unload_posts_keep_alive_zero():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"done": True})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OllamaProvider(base_url="http://test", client=client)
        ok = await provider.unload("m")
        await client.aclose()
        return ok

    ok = asyncio.run(run())
    assert ok is True
    assert captured["path"] == "/api/generate"
    assert captured["body"]["keep_alive"] == 0
