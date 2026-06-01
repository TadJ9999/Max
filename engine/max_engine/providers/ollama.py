"""Ollama (local) provider adapter.

Streams chat completions from a local Ollama server via its ``/api/chat`` endpoint,
which emits newline-delimited JSON objects. Each line carries an incremental
``message.content`` and a ``done`` flag.

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


class OllamaProvider(Provider):
    kind = "local"

    def __init__(
        self,
        name: str = "ollama",
        base_url: str = "http://127.0.0.1:11434",
        client: httpx.AsyncClient | None = None,
        keep_alive: str | None = None,
        default_options: dict | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._client = client  # injectable; if None we own a per-call client
        # How long Ollama keeps the model resident after a request (e.g. "10m").
        # When set, idle models unload on their own to free RAM/VRAM.
        self.keep_alive = keep_alive
        # Tuning knobs (num_ctx / num_gpu / …) applied to every request as
        # Ollama `options`; per-call params still override these.
        self.default_options = default_options or {}

    async def chat(self, model: str, messages: list[dict], **params) -> AsyncIterator[ChatChunk]:
        feature = params.pop("_feature", "system")

        payload: dict = {"model": model, "messages": messages, "stream": True}
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        # Start from configured tuning defaults; per-call params take precedence.
        options = dict(self.default_options)
        options.update({k: v for k, v in params.items() if v is not None})
        if options:
            payload["options"] = options

        client = self._client or httpx.AsyncClient(timeout=None)
        owns_client = self._client is None
        try:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    text = data.get("message", {}).get("content", "")
                    done = bool(data.get("done"))
                    if done and _usage_callback is not None:
                        in_tok = data.get("prompt_eval_count", 0) or 0
                        out_tok = data.get("eval_count", 0) or 0
                        if in_tok or out_tok:
                            try:
                                _usage_callback(feature, "ollama", model, in_tok, out_tok)
                            except Exception:
                                pass
                    if text or done:
                        yield ChatChunk(text=text, done=done)
        finally:
            if owns_client:
                await client.aclose()

    async def unload(self, model: str) -> bool:
        """Evict ``model`` from RAM/VRAM now (Ollama ``keep_alive=0``). Returns
        True if the request succeeded. The model reloads on the next chat call."""
        client = self._client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._client is None
        try:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "keep_alive": 0},
            )
            return resp.status_code < 400
        except httpx.HTTPError:
            return False
        finally:
            if owns_client:
                await client.aclose()
