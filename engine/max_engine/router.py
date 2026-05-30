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


def model_for(provider: str, action: str, config: EngineConfig) -> str:
    """Pick the model for a provider+action: per-provider override, else per-task."""
    return config.provider_models.get(provider, {}).get(action) or config.task_models.get(
        action, "qwen2.5-coder:14b"
    )


def is_cloud_provider(provider: str, config: EngineConfig) -> bool:
    return any(p.name == provider and p.kind == "cloud" for p in config.providers)


def resolve(command: Command, config: EngineConfig) -> Route:
    """Pick the provider + model for a parsed command."""
    # Sigil wins for provider selection; otherwise the per-task default provider.
    provider = command.provider
    if provider == "default":
        # TODO(Phase 2): allow a per-task default provider, not just default model.
        provider = "ollama"

    # Per-provider model override wins; otherwise the per-task default.
    model = model_for(provider, command.action, config)
    is_cloud = is_cloud_provider(provider, config)

    if is_cloud and not config.allow_cloud:
        raise PermissionError(
            f"command routes to cloud provider {provider!r} but allow_cloud is off"
        )
    return Route(provider=provider, model=model, is_cloud=is_cloud)
