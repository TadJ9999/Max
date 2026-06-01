"""Capability interface — the abstract base every skill implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class Capability(ABC):
    """A named, domain-tagged skill that can be invoked with a text query."""

    name: str
    description: str
    domains: list[str]

    @abstractmethod
    async def invoke(
        self, query: str, context: dict | None = None
    ) -> AsyncIterator[str]:
        """Stream the response as text chunks."""
        ...

    def status(self) -> dict:
        """Return connection / availability status for the settings UI."""
        return {"available": True, "connected": True}
