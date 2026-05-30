"""Ollama (local) provider adapter — STUB.

TODO(Phase 1): call the Ollama HTTP API (/api/chat) and stream tokens.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import ChatChunk, Provider


class OllamaProvider(Provider):
    kind = "local"

    def __init__(self, name: str = "ollama", base_url: str = "http://127.0.0.1:11434"):
        self.name = name
        self.base_url = base_url

    async def chat(
        self, model: str, messages: list[dict], **params
    ) -> AsyncIterator[ChatChunk]:
        raise NotImplementedError("Ollama adapter: Phase 1")
