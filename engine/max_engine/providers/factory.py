"""Build a Provider instance from config by name."""

from __future__ import annotations

from ..config import EngineConfig
from .anthropic import AnthropicProvider
from .base import Provider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .openai_provider import OpenAIProvider


def build_provider(name: str, config: EngineConfig, model: str = "") -> Provider:
    """Build a provider for the given name.

    When ``model`` matches the configured resident model, the provider gets
    ``keep_alive=resident_keep_alive`` so it is never evicted from VRAM.
    """
    pc = next((p for p in config.providers if p.name == name), None)
    if pc is None:
        raise KeyError(f"unknown provider: {name!r}")
    if pc.kind == "cloud":
        if pc.name == "openai":
            return OpenAIProvider(name=pc.name)
        return AnthropicProvider(name=pc.name)
    # Local OpenAI-compatible servers (llama.cpp / vLLM / LM Studio) — ^ sigil.
    if pc.name not in ("ollama", "qwen"):
        return OpenAICompatProvider(
            name=pc.name,
            base_url=pc.base_url or "http://127.0.0.1:8080",
        )
    is_resident = bool(model and model == config.idle.resident_model)
    ka = config.idle.resident_keep_alive if is_resident else config.idle.keep_alive
    return OllamaProvider(
        name=pc.name,
        base_url=pc.base_url or "http://127.0.0.1:11434",
        keep_alive=ka,
        default_options=config.tuning.to_options(),
    )
