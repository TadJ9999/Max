"""Delegate engine tests — execution, concurrency limits, routing, promotion."""

import asyncio

import pytest

from max_engine.config import DelegateConfig, EngineConfig
from max_engine.delegate.engine import DelegateEngine
from max_engine.providers.base import ChatChunk, Provider


class FakeProvider(Provider):
    """Records concurrency so we can assert the VRAM-aware scheduler limits it."""

    def __init__(self, name: str, kind: str = "local", stats: dict | None = None):
        self.name = name
        self.kind = kind
        self.stats = stats

    async def chat(self, model, messages, **params):
        if self.stats is not None:
            self.stats["active"] += 1
            self.stats["max"] = max(self.stats["max"], self.stats["active"])
        await asyncio.sleep(0.01)
        yield ChatChunk(text=f"{self.name}:{model}")
        if self.stats is not None:
            self.stats["active"] -= 1
        yield ChatChunk(text="", done=True)


def _builder(stats=None):
    def build(name: str, config: EngineConfig) -> Provider:
        kind = "cloud" if name == "claude" else "local"
        return FakeProvider(name, kind=kind, stats=stats)

    return build


def test_local_concurrency_limited_to_one():
    cfg = EngineConfig(delegate=DelegateConfig(mode="manual", max_parallel_local=1))
    stats = {"active": 0, "max": 0}

    async def run():
        eng = DelegateEngine(cfg, provider_builder=_builder(stats))
        for i in range(3):
            eng.submit(f"task {i}", provider="ollama")
        await eng.kick()
        await eng.drain()
        return eng.manager.list()

    sessions = asyncio.run(run())
    assert len(sessions) == 3
    assert all(s.state.value == "done" for s in sessions)
    assert all(s.output for s in sessions)
    assert stats["max"] == 1  # heavy local models never overlapped


def test_cloud_tasks_fan_out():
    cfg = EngineConfig(delegate=DelegateConfig(max_parallel_local=1, max_parallel_cloud=8))
    stats = {"active": 0, "max": 0}

    async def run():
        eng = DelegateEngine(cfg, provider_builder=_builder(stats))
        for i in range(4):
            eng.submit(f"task {i}", provider="claude")
        await eng.kick()
        await eng.drain()
        return eng.manager.list()

    sessions = asyncio.run(run())
    assert all(s.is_cloud for s in sessions)
    assert stats["max"] > 1  # cloud sessions ran in parallel


def test_smart_auto_routes_by_complexity():
    cfg = EngineConfig(delegate=DelegateConfig(mode="smart-auto"))
    eng = DelegateEngine(cfg, provider_builder=_builder())
    simple = eng.submit("rename a variable", complexity=0.1)
    complex_ = eng.submit("design a distributed scheduler", complexity=0.9)
    assert simple.provider == "ollama" and simple.is_cloud is False
    assert complex_.provider == "claude" and complex_.is_cloud is True
    assert complex_.model.startswith("claude-")


def test_smart_auto_stays_local_when_cloud_disabled():
    cfg = EngineConfig(delegate=DelegateConfig(mode="smart-auto"), allow_cloud=False)
    eng = DelegateEngine(cfg, provider_builder=_builder())
    s = eng.submit("very complex task", complexity=0.95)
    assert s.provider == "ollama"
    assert s.is_cloud is False


def test_promote_queued_session_to_cloud():
    cfg = EngineConfig(delegate=DelegateConfig(mode="manual"))
    eng = DelegateEngine(cfg, provider_builder=_builder())
    s = eng.submit("refactor", provider="ollama")
    assert s.is_cloud is False
    eng.promote_to_cloud(s.id)
    assert s.provider == "claude"
    assert s.is_cloud is True
    assert s.model.startswith("claude-")


def test_submit_cloud_blocked_when_disabled():
    cfg = EngineConfig(allow_cloud=False)
    eng = DelegateEngine(cfg, provider_builder=_builder())
    with pytest.raises(PermissionError):
        eng.submit("do it", provider="claude")
