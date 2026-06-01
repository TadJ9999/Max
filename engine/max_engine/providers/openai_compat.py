"""OpenAI-compatible *local* provider adapter.

Talks to any local server that exposes the OpenAI Chat Completions API:
llama.cpp's ``llama-server``, vLLM, LM Studio, text-generation-webui, etc.
Routed via the ``^`` sigil (provider name ``local``).

This is the on-machine sibling of :mod:`providers.openai_provider`: same SSE
wire format, but ``kind="local"`` — **no API key, no egress logging** (nothing
leaves the box), and usage is recorded at $0 cost like Ollama. Point it at a
server with the provider's ``base_url`` (default ``http://127.0.0.1:8080``,
llama-server's default port).

An ``httpx.AsyncClient`` can be injected for testing.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

import httpx

from .base import ChatChunk, Provider

# Callback set by main.py at startup to record usage into the analytics store.
# Signature: (feature, provider, model, in_tokens, out_tokens)
_usage_callback: Callable[[str, str, str, int, int], None] | None = None


def set_usage_callback(cb: Callable[[str, str, str, int, int], None]) -> None:
    global _usage_callback
    _usage_callback = cb


def clear_usage_callback() -> None:
    global _usage_callback
    _usage_callback = None


class OpenAICompatProvider(Provider):
    kind = "local"

    def __init__(
        self,
        name: str = "local",
        base_url: str = "http://127.0.0.1:8080",
        client: httpx.AsyncClient | None = None,
        max_tokens: int = 4096,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._client = client  # injectable; if None we own a per-call client
        self.max_tokens = max_tokens

    async def chat(self, model: str, messages: list[dict], **params) -> AsyncIterator[ChatChunk]:
        feature = params.pop("_feature", "system")

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": params.get("max_tokens", self.max_tokens),
            # vLLM / OpenAI emit a final usage block when asked; llama.cpp ignores it.
            "stream_options": {"include_usage": True},
        }
        for k in ("temperature", "top_p", "stop"):
            if params.get(k) is not None:
                payload[k] = params[k]

        client = self._client or httpx.AsyncClient(timeout=None)
        owns_client = self._client is None
        in_tokens = 0
        out_tokens = 0  # fallback: count streamed deltas if no usage block arrives
        try:
            async with client.stream(
                "POST", f"{self.base_url}/v1/chat/completions", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    try:
                        msg = json.loads(body).get("error", {}).get("message", "")
                    except Exception:
                        msg = ""
                    raise RuntimeError(
                        msg or f"local server returned HTTP {resp.status_code}"
                    )
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
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        in_tokens = usage.get("prompt_tokens", in_tokens) or in_tokens
                        out_tokens = usage.get("completion_tokens", out_tokens) or out_tokens
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        if not (isinstance(usage, dict) and usage.get("completion_tokens")):
                            out_tokens += 1
                        yield ChatChunk(text=content)
                    finish = choices[0].get("finish_reason")
                    if finish == "stop":
                        yield ChatChunk(text="", done=True)
        finally:
            if _usage_callback is not None and (in_tokens or out_tokens):
                try:
                    _usage_callback(feature, self.name, model, in_tokens, out_tokens)
                except Exception:
                    pass
            if owns_client:
                await client.aclose()


async def list_local_models(
    base_url: str = "http://127.0.0.1:8080",
    client: httpx.AsyncClient | None = None,
    timeout: float = 1.5,
) -> list[str]:
    """Return the model ids served by an OpenAI-compatible server (``GET /v1/models``).

    Used for the Model Manager reachability card. Raises on connection failure
    so the caller can mark the server unreachable.
    """
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await c.get(f"{base_url.rstrip('/')}/v1/models")
        resp.raise_for_status()
        data = resp.json().get("data") or []
        return [m.get("id", "") for m in data if m.get("id")]
    finally:
        if owns:
            await c.aclose()
