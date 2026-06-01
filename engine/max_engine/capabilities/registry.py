"""Capability registry — singleton that holds all registered skills."""

from __future__ import annotations

from .interface import Capability


class CapabilityRegistry:
    _instance: CapabilityRegistry | None = None

    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    @classmethod
    def get(cls) -> CapabilityRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, cap: Capability) -> None:
        self._caps[cap.name] = cap

    def get_capability(self, name: str) -> Capability | None:
        return self._caps.get(name)

    def find_for_domain(self, domain: str) -> Capability | None:
        for cap in self._caps.values():
            if domain in cap.domains:
                return cap
        return None

    def list_capabilities(self) -> list[dict]:
        out = []
        for cap in self._caps.values():
            entry = {
                "name": cap.name,
                "description": cap.description,
                "domains": cap.domains,
            }
            entry.update(cap.status())
            out.append(entry)
        return out
