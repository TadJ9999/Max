"""Per-session live output streaming (engine-level + /sessions/{id}/stream)."""

import asyncio

from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.config import DelegateConfig, EngineConfig
from max_engine.delegate.engine import DelegateEngine
from max_engine.delegate.session import SessionState
from max_engine.providers.base import ChatChunk, Provider


class ChunkyProvider(Provider):
    """Yields several text chunks so we can watch them stream."""

    name = "ollama"
    kind = "local"

    def __init__(self, *_a, **_k):
        pass

    async def chat(self, model, messages, **params):
        for piece in ("Hello", ", ", "world", "!"):
            await asyncio.sleep(0)
            yield ChatChunk(text=piece)
        yield ChatChunk(text="", done=True)


def _engine() -> DelegateEngine:
    cfg = EngineConfig(delegate=DelegateConfig(mode="manual"))
    return DelegateEngine(cfg, provider_builder=lambda *_a, **_k: ChunkyProvider())


def test_subscriber_receives_all_chunks_then_done():
    async def run():
        eng = _engine()
        s = eng.submit("task", provider="ollama")
        q = s.subscribe()  # before kick => no chunk missed, none replayed
        await eng.kick()
        events = []
        while True:
            ev = await q.get()
            events.append(ev)
            if ev["type"] == "done":
                break
        await eng.drain()
        return s, events

    s, events = asyncio.run(run())
    streamed = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert streamed == "Hello, world!" == s.output
    assert events[-1] == {"type": "done", "state": "done"}
    assert s.state is SessionState.DONE


def test_emit_without_subscribers_still_accumulates_output():
    async def run():
        eng = _engine()
        eng.submit("task", provider="ollama")  # nobody subscribes
        await eng.kick()
        await eng.drain()
        return eng.manager.list()[0]

    s = asyncio.run(run())
    assert s.output == "Hello, world!"  # polling path unaffected by streaming


def test_stream_unknown_session_404():
    assert TestClient(m.app).get("/sessions/nope/stream").status_code == 404


def test_stream_replays_finished_session():
    # Inject an already-finished session (deterministic; no background tasks).
    s = m.delegate.manager.spawn(task="done one", provider="ollama", model="x")
    s.output = "final answer"
    s.state = SessionState.DONE

    body = TestClient(m.app).get(f"/sessions/{s.id}/stream").text
    assert "final answer" in body
    assert '"type": "done"' in body
    assert '"state": "done"' in body
