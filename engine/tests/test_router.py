import pytest

from max_engine.config import EngineConfig
from max_engine.dsl import parse_command
from max_engine.router import resolve


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
