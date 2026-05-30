"""Provider adapter interface.

Every backend (local or cloud) implements :class:`Provider` so the router can
treat them identically. Implementations land in Phase 1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class ChatChunk:
    """A streamed piece of a model response."""

    text: str
    done: bool = False


class Provider(ABC):
    name: str
    kind: str  # "local" | "cloud"

    @abstractmethod
    async def chat(
        self, model: str, messages: list[dict], **params
    ) -> AsyncIterator[ChatChunk]:
        """Stream a chat completion as :class:`ChatChunk` objects."""
        raise NotImplementedError
