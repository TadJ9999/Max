"""Ollama adapter test using a mocked HTTP transport (no live server needed)."""

import asyncio

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
