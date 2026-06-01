"""Apollo vector-memory tests — sqlite-vec store + embed client + service ingest/
recall. The store is real (tiny, on a tmp file); the embedder is mocked so no
Ollama is needed.
"""

import asyncio

import httpx
import pytest

from max_engine.apollo.embed import embed_texts
from max_engine.apollo.service import ApolloService
from max_engine.apollo.store import VectorStore

DIM = 8


def _store(tmp_path):
    return VectorStore(str(tmp_path / "t.apollo.db"), dim=DIM)


def _vec(seed):
    return [float((seed + i) % 5) for i in range(DIM)]


def _item(kind, ref, ts, title, seed):
    return {
        "kind": kind, "ref": ref, "ts": ts, "title": title,
        "body": title, "embedding": _vec(seed),
    }


# ---- store --------------------------------------------------------------


def test_store_upsert_search_and_dedupe(tmp_path):
    s = _store(tmp_path)
    s.upsert([_item("osint", "u1", 1000, "A", 0), _item("market", "m1", 1000, "B", 3)])
    # re-upsert same ref → replace, not duplicate
    s.upsert([_item("osint", "u1", 2000, "A2", 0)])
    assert s.stats()["total"] == 2

    hits = s.search(_vec(0), k=5)
    assert hits[0]["ref"] == "u1" and hits[0]["title"] == "A2"  # nearest + updated

    osint_only = s.search(_vec(0), k=5, kind="osint")
    assert all(h["kind"] == "osint" for h in osint_only)


def test_store_purge_ttl(tmp_path):
    import time

    s = _store(tmp_path)
    now = int(time.time())
    s.upsert([
        _item("osint", "fresh", now, "f", 0),
        _item("osint", "stale", now - 90_000, "s", 1),
    ])
    removed = s.purge_older_than(86_400)
    assert removed == 1
    assert s.stats()["total"] == 1


# ---- embed client (mocked HTTP) ----------------------------------------


def test_embed_texts_parses(monkeypatch):
    def handler(req):
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await embed_texts(["a", "b"], client=c)

    assert asyncio.run(run()) == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_texts_best_effort_on_error():
    def boom(req):
        return httpx.Response(500)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as c:
            return await embed_texts(["a"], client=c)

    assert asyncio.run(run()) == []


# ---- service ingest + recall (mock embedder, real store) ---------------


class _FakeOsint:
    async def get_articles(self, iso=None, limit=50):
        from max_engine.osint.models import Article

        return [
            Article(title="War escalates", url="http://a/1", domain="r.com", origin="rss",
                    country="Ukraine", severity=3, summary="heavy fighting"),
        ]

    async def get_heatmap(self):
        from datetime import datetime, timezone

        from max_engine.osint.models import Heatmap

        return Heatmap(updated=datetime.now(timezone.utc), countries=[], total_articles=1)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    s = ApolloService(osint=_FakeOsint(), market=None, store=_store(tmp_path))
    # deterministic embedder: one DIM-vector per input text
    async def fake_embed(texts):
        return [_vec(i) for i, _ in enumerate(texts)]

    monkeypatch.setattr(s, "_embed", fake_embed)
    return s


def test_ingest_osint_writes_memory(svc):
    payload = asyncio.run(svc.osint_payload())
    n = asyncio.run(svc.ingest_osint(payload))
    assert n == 1
    assert svc.memory_stats()["total"] == 1


def test_retrieve_for_prediction_recalls(svc):
    payload = asyncio.run(svc.osint_payload())
    asyncio.run(svc.ingest_osint(payload))
    combined = {"osint": payload, "market": {"stats": {"up": 1, "down": 0}}}
    mem = asyncio.run(svc.retrieve_for_prediction(combined))
    assert len(mem) == 1
    assert "ageHours" in mem[0] and "distance" in mem[0]


def test_ingest_all_articles_indexes_every_article(svc):
    # ingest_all_articles embeds *all* articles (not just severity>=2 criticals).
    n = asyncio.run(svc.ingest_all_articles())
    assert n == 1
    assert svc.memory_stats()["byKind"].get("osint") == 1


def test_recall_is_question_driven(svc):
    asyncio.run(svc.ingest_all_articles())
    hits = asyncio.run(svc.recall("what is happening in Ukraine?"))
    assert hits and hits[0]["title"] == "War escalates"
    assert "ageHours" in hits[0] and "kind" in hits[0]


def test_recall_kind_filter(svc):
    asyncio.run(svc.ingest_all_articles())
    # No market memories yet → filtering to market returns nothing.
    assert asyncio.run(svc.recall("anything", kinds=["market"])) == []
    assert asyncio.run(svc.recall("anything", kinds=["osint"]))


def test_ingest_report_and_recall(svc):
    n = asyncio.run(svc.ingest_report("report", "apollo:predict:2026-06-01", "Daily brief", "Body text"))
    assert n == 1
    hits = asyncio.run(svc.recall("daily brief"))
    assert any(h["kind"] == "report" for h in hits)


def test_recall_block_formats_and_empty():
    from max_engine.apollo.service import format_memories

    assert format_memories([]) == ""
    block = format_memories([
        {"kind": "osint", "title": "Pence remarks", "body": "details", "ageHours": 3.0},
    ])
    assert "RELEVANT INDEXED KNOWLEDGE" in block
    assert "[NEWS" in block and "Pence remarks" in block
