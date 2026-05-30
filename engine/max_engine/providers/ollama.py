"""Ollama (local) provider adapter.

Streams chat completions from a local Ollama server via its ``/api/chat`` endpoint,
which emits newline-delimited JSON objects. Each line carries an incremental
``message.content`` and a ``done`` flag.

An ``httpx.AsyncClient`` can be injected for testing.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .base import ChatChunk, Provider


class OllamaProvider(Provider):
    kind = "local"

    def __init__(
        self,
        name: str = "ollama",
        base_url: str = "http://127.0.0.1:11434",
        client: httpx.AsyncClient | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._client = client  # injectable; if None we own a per-call client

    async def chat(
        self, model: str, messages: list[dict], **params
    ) -> AsyncIterator[ChatChunk]:
        payload: dict = {"model": model, "messages": messages, "stream": True}
        options = {k: v for k, v in params.items() if v is not None}
        if options:
            payload["options"] = options

        client = self._client or httpx.AsyncClient(timeout=None)
        owns_client = self._client is None
        try:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    text = data.get("message", {}).get("content", "")
                    done = bool(data.get("done"))
                    if text or done:
                        yield ChatChunk(text=text, done=done)
        finally:
            if owns_client:
                await client.aclose()
