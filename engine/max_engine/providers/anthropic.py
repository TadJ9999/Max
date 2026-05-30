"""Anthropic / Claude (cloud) provider adapter — STUB.

Routed via the ``!`` sigil. Off-machine: requires an API key (from the secret
store) and is gated by ``EngineConfig.allow_cloud``.

TODO(Phase 1): call the Anthropic Messages API and stream tokens.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import ChatChunk, Provider


class AnthropicProvider(Provider):
    kind = "cloud"

    def __init__(self, name: str = "claude", api_key: str | None = None):
        self.name = name
        self.api_key = api_key

    async def chat(
        self, model: str, messages: list[dict], **params
    ) -> AsyncIterator[ChatChunk]:
        raise NotImplementedError("Anthropic adapter: Phase 1")
