"""RAG endpoints — index/search/status/clear with allowlist enforcement."""

import math
import re

from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.rag.service import RagService
from max_engine.rag.store import RagStore

DIM = 64


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


def _setup(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "auth.py").write_text("def login(user, password):\n    return verify(user, password)\n")
    (ws / "cache.py").write_text("def memoize(fn):\n    store = {}\n    return fn\n")
    svc = RagService(RagStore(str(tmp_path / "rag.db"), dim=DIM), embed_fn=lambda ts: _embed(ts))
    monkeypatch.setattr(m, "rag", svc)
    monkeypatch.setattr(m.config, "workspace_allowlist", [str(ws)])
    return TestClient(m.app), str(ws)


def test_index_search_status_clear(tmp_path, monkeypatch):
    client, ws = _setup(tmp_path, monkeypatch)

    idx = client.post("/rag/index", json={}).json()
    assert idx["indexed"] == 2 and idx["files"] == 2

    status = client.get("/rag/status").json()
    assert status["files"] == 2 and status["allowlist"] == [ws]

    hits = client.post("/rag/search", json={"query": "login password", "k": 2}).json()["hits"]
    assert hits and hits[0]["path"].endswith("auth.py")

    assert client.post("/rag/clear").json()["files"] == 0


def test_index_ignores_paths_outside_allowlist(tmp_path, monkeypatch):
    client, _ws = _setup(tmp_path, monkeypatch)
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "keys.py").write_text("SECRET = 'do-not-index'\n")

    # Asking to index a non-allowlisted path indexes nothing.
    idx = client.post("/rag/index", json={"roots": [str(outside)]}).json()
    assert idx["indexed"] == 0 and idx["files"] == 0
