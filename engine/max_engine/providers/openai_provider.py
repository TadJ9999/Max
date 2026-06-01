"""OpenAI (cloud) provider adapter.

Routed via the ``%`` sigil. Off-machine: requires an API key
(OPENAI_API_KEY in engine/.env) and is gated by ``EngineConfig.allow_cloud``.

Streams the OpenAI Chat Completions API (SSE). An ``httpx.AsyncClient`` can
be injected for testing.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from .base import ChatChunk, Provider

_EGRESS_LOG = Path(__file__).resolve().parent.parent.parent / ".egress.log"


def _log_egress(model: str, action: str, tokens: int = 0) -> None:
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        line = f"{ts} provider=openai model={model} action={action} tokens={tokens}\n"
        with _EGRESS_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


class OpenAIProvider(Provider):
    kind = "cloud"

    def __init__(
        self,
        name: str = "openai",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com",
        client: httpx.AsyncClient | None = None,
        max_tokens: int = 4096,
    ):
        self.name = name
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")
        self._client = client
        self.max_tokens = max_tokens

    async def chat(self, model: str, messages: list[dict], **params) -> AsyncIterator[ChatChunk]:
        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set; the OpenAI (%) provider is unavailable"
            )

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": params.get("max_tokens", self.max_tokens),
        }
        for k in ("temperature", "top_p", "stop"):
            if params.get(k) is not None:
                payload[k] = params[k]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        client = self._client or httpx.AsyncClient(timeout=None)
        owns_client = self._client is None
        output_tokens = 0
        _log_egress(model, "chat_start")
        try:
            async with client.stream(
                "POST", f"{self.base_url}/v1/chat/completions", json=payload, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    try:
                        msg = json.loads(body).get("error", {}).get("message", "")
                    except Exception:
                        msg = ""
                    raise RuntimeError(msg or f"OpenAI API returned HTTP {resp.status_code}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        yield ChatChunk(text="", done=True)
                        break
                    event = json.loads(data)
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        output_tokens += 1
                        yield ChatChunk(text=content)
                    finish = choices[0].get("finish_reason")
                    if finish == "stop":
                        yield ChatChunk(text="", done=True)
        finally:
            _log_egress(model, "chat_done", output_tokens)
            if owns_client:
                await client.aclose()
