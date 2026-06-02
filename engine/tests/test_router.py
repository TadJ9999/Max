import pytest

from max_engine.config import EngineConfig
from max_engine.dsl import parse_command
from max_engine.router import model_for, resolve


def _route(text: str, **overrides):
    cfg = EngineConfig(**overrides)
    return resolve(parse_command(text, sigils=cfg.sigils), cfg)


def test_cloud_sigil_uses_claude_model():
    r = _route("!. write tests .")
    assert r.provider == "claude"
    assert r.is_cloud is True
    assert r.model.startswith("claude-")  # provider override applied


def test_local_sigil_uses_task_model():
    r = _route("@. add a function .")
    assert r.provider == "ollama"
    assert r.is_cloud is False
    assert r.model == "qwen2.5-coder:14b"


def test_cloud_blocked_when_disabled():
    with pytest.raises(PermissionError):
        _route("!. do it .", allow_cloud=False)


def test_local_provider_never_gets_cloud_model():
    """Regression: a cloud model set as a task default (via Model Manager) must not
    be handed to a local provider — Ollama 404s on e.g. claude-opus-4-8."""
    cfg = EngineConfig()
    cfg.task_models["generate"] = "claude-opus-4-8"
    cfg.task_models["fix"] = "claude-opus-4-8"
    # Local provider falls back to a local model instead of the cloud id.
    assert model_for("ollama", "generate", cfg) == "qwen2.5-coder:14b"
    assert not model_for("ollama", "fix", cfg).startswith("claude")
    # Cloud provider still gets its proper cloud model.
    assert model_for("claude", "generate", cfg).startswith("claude-")


def test_local_route_with_cloud_task_default_resolves_local():
    cfg_kwargs = {"task_models": {
        "generate": "claude-opus-4-8", "summarize": "qwen2.5-coder:14b",
        "fix": "gpt-4o", "chat": "qwen2.5-coder:14b", "completion": "qwen2.5-coder:3b",
    }}
    r = _route("@. add a function .", **cfg_kwargs)  # ollama, generate action
    assert r.provider == "ollama" and r.is_cloud is False
    assert not r.model.startswith(("claude", "gpt"))
