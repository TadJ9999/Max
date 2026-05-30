"""Claude (cloud) adapter test using a mocked HTTP transport (no real API call)."""

import asyncio

import httpx
import pytest

from max_engine.providers.anthropic import AnthropicProvider, _split_system


def test_split_system_lifts_system_messages():
    system, convo = _split_system(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert system == "be terse"
    assert convo == [{"role": "user", "content": "hi"}]


def test_anthropic_streams_text_deltas():
    events = [
        'event: content_block_delta',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
        '',
        'event: content_block_delta',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}',
        '',
        'event: message_stop',
        'data: {"type":"message_stop"}',
        '',
    ]
    body = "\n".join(events) + "\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        sent = request.read()
        assert b'"stream": true' in sent or b'"stream":true' in sent
        return httpx.Response(200, text=body)

    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        provider = AnthropicProvider(
            api_key="test-key", base_url="http://test", client=client
        )
        chunks = [
            c
            async for c in provider.chat(
                "claude-opus-4-8", [{"role": "user", "content": "hi"}]
            )
        ]
        await client.aclose()
        return chunks

    chunks = asyncio.run(run())
    assert "".join(c.text for c in chunks) == "Hello world"
    assert chunks[-1].done is True


def test_anthropic_requires_api_key():
    provider = AnthropicProvider(api_key=None)
    provider.api_key = None  # ensure no env leak

    async def run():
        return [c async for c in provider.chat("m", [{"role": "user", "content": "x"}])]

    with pytest.raises(RuntimeError):
        asyncio.run(run())
