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
