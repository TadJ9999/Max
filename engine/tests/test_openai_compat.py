"""OpenAI-compatible *local* adapter tests (mocked HTTP transport, no real server).

Covers the llama.cpp / vLLM / LM Studio provider routed via the ``^`` sigil.
"""

import asyncio

import httpx
import pytest

from max_engine.config import EngineConfig
from max_engine.providers import openai_compat
from max_engine.providers.factory import build_provider
from max_engine.providers.openai_compat import OpenAICompatProvider, list_local_models


def _sse(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_streams_text_deltas_without_api_key():
    body = _sse(
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        # Local provider must NOT send an Authorization header.
        assert "authorization" not in {k.lower() for k in request.headers}
        return httpx.Response(200, text=body)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OpenAICompatProvider(base_url="http://test", client=client)
        chunks = [c async for c in provider.chat("local-model", [{"role": "user", "content": "hi"}])]
        await client.aclose()
        return chunks

    chunks = asyncio.run(run())
    assert "".join(c.text for c in chunks) == "Hello"
    assert chunks[-1].done is True


def test_usage_block_fires_callback():
    body = _sse(
        'data: {"choices":[{"delta":{"content":"hi"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":11,"completion_tokens":7}}',
        "data: [DONE]",
    )
    recorded: list[tuple] = []
    openai_compat.set_usage_callback(lambda *a: recorded.append(a))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OpenAICompatProvider(name="local", base_url="http://test", client=client)
        async for _ in provider.chat("m", [{"role": "user", "content": "x"}], _feature="chat"):
            pass
        await client.aclose()

    try:
        asyncio.run(run())
    finally:
        openai_compat.clear_usage_callback()

    assert recorded == [("chat", "local", "m", 11, 7)]


def test_counts_tokens_when_no_usage_block():
    """Servers that don't emit a usage block fall back to counting deltas."""
    body = _sse(
        'data: {"choices":[{"delta":{"content":"a"}}]}',
        'data: {"choices":[{"delta":{"content":"b"}}]}',
        'data: {"choices":[{"delta":{"content":"c"}}]}',
        "data: [DONE]",
    )
    recorded: list[tuple] = []
    openai_compat.set_usage_callback(lambda *a: recorded.append(a))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OpenAICompatProvider(base_url="http://test", client=client)
        async for _ in provider.chat("m", [{"role": "user", "content": "x"}]):
            pass
        await client.aclose()

    try:
        asyncio.run(run())
    finally:
        openai_compat.clear_usage_callback()

    assert recorded and recorded[0][4] == 3  # out_tokens counted from 3 deltas


def test_surfaces_http_error_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "model not found"}})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        provider = OpenAICompatProvider(base_url="http://test", client=client)
        try:
            return [c async for c in provider.chat("m", [{"role": "user", "content": "x"}])]
        finally:
            await client.aclose()

    with pytest.raises(RuntimeError, match="model not found"):
        asyncio.run(run())


def test_list_local_models_parses_v1_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "qwen2.5-7b"}, {"id": "mistral"}]})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
        try:
            return await list_local_models(base_url="http://test", client=client)
        finally:
            await client.aclose()

    assert asyncio.run(run()) == ["qwen2.5-7b", "mistral"]


def test_factory_builds_local_provider_for_caret_sigil():
    cfg = EngineConfig()
    # The default config maps "^" -> "local" and includes a local provider.
    assert cfg.sigils.get("^") == "local"
    provider = build_provider("local", cfg)
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.kind == "local"
    assert provider.base_url == "http://127.0.0.1:8080"
