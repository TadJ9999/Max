"""Provider router — resolve a parsed command to a concrete (provider, model).

Combines the DSL sigil with the per-task default models from config. The actual
dispatch to a Provider lands in Phase 1/2.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import EngineConfig
from .dsl import Command


@dataclass
class Route:
    provider: str
    model: str
    is_cloud: bool


_LOCAL_DEFAULT_MODEL = "qwen2.5-coder:14b"


def _looks_like_cloud_model(model: str) -> bool:
    """A model id that belongs to a cloud provider (Claude / GPT / Gemini).
    Used to keep cloud ids off local providers (Ollama would 404 on them)."""
    m = (model or "").lower()
    return m.startswith(("claude", "gpt", "gemini", "o1", "o3", "o4"))


def model_for(provider: str, action: str, config: EngineConfig) -> str:
    """Pick the model for a provider+action: per-provider override, else per-task.

    Guard: a **local** provider must never be handed a **cloud** model id. This
    happens when ``task_models[action]`` is set to a cloud model in the Model
    Manager (task_models is the shared fallback for every provider) — Ollama then
    404s on e.g. ``claude-opus-4-8``. In that case we fall back to a sane local
    model so local routing keeps working regardless of the cloud task defaults.
    """
    model = config.provider_models.get(provider, {}).get(action) or config.task_models.get(
        action, _LOCAL_DEFAULT_MODEL
    )
    if _looks_like_cloud_model(model) and not is_cloud_provider(provider, config):
        for candidate in (config.task_models.get("chat"), config.idle.resident_model,
                          _LOCAL_DEFAULT_MODEL):
            if candidate and not _looks_like_cloud_model(candidate):
                return candidate
        return _LOCAL_DEFAULT_MODEL
    return model


def is_cloud_provider(provider: str, config: EngineConfig) -> bool:
    # "agent" (subscription claude-cli) egresses to Anthropic, so it's gated like cloud.
    return any(p.name == provider and p.kind in ("cloud", "agent") for p in config.providers)


def resolve(command: Command, config: EngineConfig) -> Route:
    """Pick the provider + model for a parsed command."""
    # Sigil wins for provider selection; otherwise the per-task default provider.
    provider = command.provider
    if provider == "default":
        provider = "ollama"

    # FIM/completion: use the resident tiny model when configured and no explicit sigil.
    if (
        command.action == "completion"
        and command.provider == "default"
        and config.idle.resident_model
    ):
        return Route(provider="ollama", model=config.idle.resident_model, is_cloud=False)

    # Per-provider model override wins; otherwise the per-task default.
    model = model_for(provider, command.action, config)
    is_cloud = is_cloud_provider(provider, config)

    if is_cloud and not config.allow_cloud:
        raise PermissionError(
            f"command routes to cloud provider {provider!r} but allow_cloud is off"
        )
    return Route(provider=provider, model=model, is_cloud=is_cloud)
