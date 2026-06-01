"""Build a Provider instance from config by name."""

from __future__ import annotations

from ..config import EngineConfig
from .anthropic import AnthropicProvider
from .base import Provider
from .ollama import OllamaProvider


def build_provider(name: str, config: EngineConfig, model: str = "") -> Provider:
    """Build a provider for the given name.

    When ``model`` matches the configured resident model, the provider gets
    ``keep_alive=resident_keep_alive`` so it is never evicted from VRAM.
    """
    pc = next((p for p in config.providers if p.name == name), None)
    if pc is None:
        raise KeyError(f"unknown provider: {name!r}")
    if pc.kind == "cloud":
        return AnthropicProvider(name=pc.name)
    is_resident = bool(model and model == config.idle.resident_model)
    ka = config.idle.resident_keep_alive if is_resident else config.idle.keep_alive
    return OllamaProvider(
        name=pc.name,
        base_url=pc.base_url or "http://127.0.0.1:11434",
        keep_alive=ka,
    )
