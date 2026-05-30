"""Engine configuration.

Mirrors the roadmap: per-task default models, sigil->provider map, providers,
cloud toggle, and the workspace folder allowlist. File-backed loading is a TODO
(Phase 1); for now these are the in-memory defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

# UI-editable settings persist here (gitignored), next to engine/.env.
CONFIG_FILE = Path(__file__).resolve().parent.parent / ".maxconfig.json"


class ProviderConfig(BaseModel):
    name: str
    kind: str  # "local" | "cloud"
    base_url: str | None = None  # e.g. Ollama endpoint
    # API keys are loaded from the environment / secret store, never hard-coded.


class DelegateConfig(BaseModel):
    mode: str = "smart-auto"  # "manual" | "smart-auto"
    max_parallel_local: int = 1  # heavy local models queue past this (12 GB VRAM)
    max_parallel_cloud: int = 8


class EngineConfig(BaseModel):
    # sigil -> provider name
    sigils: dict[str, str] = Field(
        default_factory=lambda: {"@": "ollama", "#": "qwen", "!": "claude"}
    )
    # task -> default model
    task_models: dict[str, str] = Field(
        default_factory=lambda: {
            "generate": "qwen2.5-coder:14b",
            "summarize": "qwen2.5-coder:14b",
            "fix": "qwen2.5-coder:14b",
            "chat": "qwen2.5-coder:14b",
            "completion": "qwen2.5-coder:3b",
        }
    )
    # Optional per-provider model overrides: provider -> {action: model}.
    # Falls back to task_models when a provider/action isn't listed here.
    provider_models: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "claude": {
                "generate": "claude-sonnet-4-6",
                "summarize": "claude-haiku-4-5-20251001",
                "fix": "claude-sonnet-4-6",
                "chat": "claude-sonnet-4-6",
            }
        }
    )
    providers: list[ProviderConfig] = Field(
        default_factory=lambda: [
            ProviderConfig(name="ollama", kind="local", base_url="http://127.0.0.1:11434"),
            ProviderConfig(name="qwen", kind="local", base_url="http://127.0.0.1:11434"),
            ProviderConfig(name="claude", kind="cloud"),
        ]
    )
    allow_cloud: bool = True
    workspace_allowlist: list[str] = Field(default_factory=list)
    delegate: DelegateConfig = Field(default_factory=DelegateConfig)


def _apply_overrides(cfg: EngineConfig, data: dict) -> None:
    """Apply the UI-editable subset of settings onto a config in place."""
    if "allow_cloud" in data:
        cfg.allow_cloud = bool(data["allow_cloud"])
    if "workspace_allowlist" in data:
        cfg.workspace_allowlist = list(data["workspace_allowlist"])
    d = data.get("delegate") or {}
    if "mode" in d:
        cfg.delegate.mode = d["mode"]
    if "max_parallel_local" in d:
        cfg.delegate.max_parallel_local = max(1, int(d["max_parallel_local"]))
    if "max_parallel_cloud" in d:
        cfg.delegate.max_parallel_cloud = max(1, int(d["max_parallel_cloud"]))


def load_config() -> EngineConfig:
    """Defaults, with any persisted UI overrides from CONFIG_FILE applied."""
    cfg = EngineConfig()
    if CONFIG_FILE.exists():
        try:
            _apply_overrides(cfg, json.loads(CONFIG_FILE.read_text()))
        except (ValueError, OSError):
            pass  # corrupt/unreadable file -> fall back to defaults
    return cfg


def save_overrides(cfg: EngineConfig) -> None:
    """Persist the UI-editable subset of settings to CONFIG_FILE."""
    data = {
        "allow_cloud": cfg.allow_cloud,
        "workspace_allowlist": cfg.workspace_allowlist,
        "delegate": {
            "mode": cfg.delegate.mode,
            "max_parallel_local": cfg.delegate.max_parallel_local,
            "max_parallel_cloud": cfg.delegate.max_parallel_cloud,
        },
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
