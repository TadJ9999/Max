"""Build a Provider instance from config by name."""

from __future__ import annotations

from ..config import EngineConfig
from .anthropic import AnthropicProvider
from .base import Provider
from .ollama import OllamaProvider


def build_provider(name: str, config: EngineConfig) -> Provider:
    pc = next((p for p in config.providers if p.name == name), None)
    if pc is None:
        raise KeyError(f"unknown provider: {name!r}")
    if pc.kind == "cloud":
        return AnthropicProvider(name=pc.name)
    return OllamaProvider(
        name=pc.name, base_url=pc.base_url or "http://127.0.0.1:11434"
    )
