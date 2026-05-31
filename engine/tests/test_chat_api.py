"""/chat endpoint — plain conversational text (no DSL operators), streamed."""

from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.providers.base import ChatChunk, Provider


class FakeProvider(Provider):
    def __init__(self, name: str = "ollama", kind: str = "local"):
        self.name = name
        self.kind = kind

    async def chat(self, model, messages, **params):
        # Echo the routed model + the user's text so the test can assert routing.
        user = messages[-1]["content"]
        yield ChatChunk(text=f"[{model}] reply to: {user}")
        yield ChatChunk(text="", done=True)


def test_chat_plain_text_streams(monkeypatch):
    monkeypatch.setattr(m, "build_provider", lambda name, config: FakeProvider(name))
    c = TestClient(m.app)

    r = c.post("/chat", json={"text": "hello there"})
    assert r.status_code == 200
    body = r.text
    assert "reply to: hello there" in body
    assert "qwen2.5-coder:14b" in body  # routed to the configured chat model
    assert "[DONE]" in body
