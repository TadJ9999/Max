"""Session memory + memory-aware /rag/ask."""

import math
import re

from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.providers.base import ChatChunk, Provider
from max_engine.rag.memory import SessionMemory
from max_engine.rag.service import RagService
from max_engine.rag.store import RagStore

DIM = 64


# ---- SessionMemory unit ------------------------------------------------


def test_memory_appends_and_caps():
    mem = SessionMemory(max_messages=4)
    for i in range(5):
        mem.append("s1", "user", f"q{i}")
        mem.append("s1", "assistant", f"a{i}")
    hist = mem.history("s1")
    assert len(hist) == 4  # capped to most recent
    assert hist[-1] == {"role": "assistant", "content": "a4"}
    assert hist[0]["content"] in ("q3", "a3")  # oldest kept is recent


def test_memory_recent_user_text_and_isolation():
    mem = SessionMemory()
    mem.append("a", "user", "about the parser")
    mem.append("a", "assistant", "...")
    mem.append("a", "user", "its errors?")
    mem.append("b", "user", "unrelated")
    assert mem.recent_user_text("a", n=2) == "about the parser\nits errors?"
    assert mem.recent_user_text("b") == "unrelated"  # sessions don't bleed
    mem.clear("a")
    assert mem.history("a") == []


def test_memory_ignores_empty():
    mem = SessionMemory()
    mem.append("s", "user", "")
    mem.append("", "user", "x")
    assert mem.stats() == {"sessions": 0, "messages": 0}


# ---- /rag/ask with memory ----------------------------------------------


class EchoProvider(Provider):
    """Returns the messages it received so the test can assert what was sent."""

    name = "ollama"
    kind = "local"

    def __init__(self, *_a, **_k):
        pass

    async def chat(self, model, messages, **params):
        # Surface how many prior turns came through, plus the final question.
        prior = sum(1 for msg in messages if msg["role"] in ("user", "assistant")) - 1
        yield ChatChunk(text=f"answer (prior_turns={prior})")
        yield ChatChunk(text="", done=True)


def _embed(texts):
    async def run():
        out = []
        for t in texts:
            v = [0.0] * DIM
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                v[sum(ord(c) for c in tok) % DIM] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    return run()


def _read_sse(resp) -> str:
    return resp.text


def test_ask_records_and_replays_session_memory(tmp_path, monkeypatch):
    # Empty index is fine — we're testing memory threading, not retrieval.
    svc = RagService(RagStore(str(tmp_path / "r.db"), dim=DIM), embed_fn=lambda ts: _embed(ts))
    monkeypatch.setattr(m, "rag", svc)
    monkeypatch.setattr(m, "rag_memory", SessionMemory())
    monkeypatch.setattr(m, "build_provider", lambda *_a, **_k: EchoProvider())
    client = TestClient(m.app)

    # First turn: no prior history.
    r1 = client.post("/rag/ask", json={"question": "what does login do?", "session_id": "sess1"})
    assert r1.status_code == 200
    assert "prior_turns=0" in _read_sse(r1)

    # Memory now holds the first Q&A.
    hist = client.get("/rag/memory/sess1").json()["history"]
    assert [h["role"] for h in hist] == ["user", "assistant"]
    assert hist[0]["content"] == "what does login do?"

    # Second turn: prior turns are replayed to the model (user+assistant = 2).
    r2 = client.post("/rag/ask", json={"question": "and its errors?", "session_id": "sess1"})
    assert "prior_turns=2" in _read_sse(r2)

    # Clearing wipes it.
    client.post("/rag/memory/sess1/clear")
    assert client.get("/rag/memory/sess1").json()["history"] == []


def test_ask_without_session_is_stateless(tmp_path, monkeypatch):
    svc = RagService(RagStore(str(tmp_path / "r.db"), dim=DIM), embed_fn=lambda ts: _embed(ts))
    monkeypatch.setattr(m, "rag", svc)
    monkeypatch.setattr(m, "rag_memory", SessionMemory())
    monkeypatch.setattr(m, "build_provider", lambda *_a, **_k: EchoProvider())
    client = TestClient(m.app)

    client.post("/rag/ask", json={"question": "q1"})
    client.post("/rag/ask", json={"question": "q2"})
    assert m.rag_memory.stats()["messages"] == 0  # nothing stored without a session_id
