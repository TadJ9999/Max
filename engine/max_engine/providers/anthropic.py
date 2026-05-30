"""Anthropic / Claude (cloud) provider adapter.

Routed via the ``!`` sigil. Off-machine: requires an API key (from the
environment / secret store) and is gated upstream by ``EngineConfig.allow_cloud``.

Streams the Anthropic Messages API (SSE). System messages are lifted into the
top-level ``system`` field, as the API requires. An ``httpx.AsyncClient`` can be
injected for testing.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

from .base import ChatChunk, Provider

ANTHROPIC_VERSION = "2023-06-01"


def _split_system(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Separate system messages (top-level in the Anthropic API) from the turns."""
    system_parts: list[str] = []
    convo: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content", ""))
        else:
            convo.append({"role": m["role"], "content": m["content"]})
    return ("\n\n".join(system_parts) if system_parts else None), convo


class AnthropicProvider(Provider):
    kind = "cloud"

    def __init__(
        self,
        name: str = "claude",
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        client: httpx.AsyncClient | None = None,
        max_tokens: int = 4096,
    ):
        self.name = name
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url.rstrip("/")
        self._client = client
        self.max_tokens = max_tokens

    async def chat(
        self, model: str, messages: list[dict], **params
    ) -> AsyncIterator[ChatChunk]:
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; the cloud (!) provider is unavailable"
            )

        system, convo = _split_system(messages)
        payload: dict = {
            "model": model,
            "max_tokens": params.get("max_tokens", self.max_tokens),
            "messages": convo,
            "stream": True,
        }
        if system:
            payload["system"] = system
        for k in ("temperature", "top_p", "top_k", "stop_sequences"):
            if params.get(k) is not None:
                payload[k] = params[k]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        client = self._client or httpx.AsyncClient(timeout=None)
        owns_client = self._client is None
        try:
            async with client.stream(
                "POST", f"{self.base_url}/v1/messages", json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data:
                        continue
                    event = json.loads(data)
                    etype = event.get("type")
                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield ChatChunk(text=delta.get("text", ""))
                    elif etype == "message_stop":
                        yield ChatChunk(text="", done=True)
        finally:
            if owns_client:
                await client.aclose()
