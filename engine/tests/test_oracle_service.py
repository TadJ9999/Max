"""Service-level tests — capture → grade_due (objective path) → hindsight, with a
real store + vector, mocked LLM/embeds, and patched candle fetch (no network)."""

import asyncio

import pytest

from max_engine.apollo.store import VectorStore
from max_engine.oracle import service as service_mod
from max_engine.oracle.service import OracleService
from max_engine.oracle.store import OracleStore

DIM = 8


def _vec(seed):
    return [float((seed + i) % 5) for i in range(DIM)]


async def _embed(texts):
    return [_vec(i) for i, _ in enumerate(texts)]


def _extract_payload():
    return (
        '[{"claim":"AAPL up next week","entity":"AAPL","entity_kind":"ticker",'
        '"direction":"up","magnitude":3,"horizon_hours":24,"confidence":0.8}]'
    )


def _make_service(tmp_path, llm):
    store = OracleStore(str(tmp_path / "t.apollo.db"))
    vector = VectorStore(str(tmp_path / "t.apollo.db"), dim=DIM)
    return OracleService(
        store=store, vector=vector, llm=llm, embed_fn=_embed,
        market=None, osint=None, calibrator=None,
        extract_route=lambda: ("ollama", "m"),
        judge_local_route=lambda: ("ollama", "m"),
        judge_cloud_route=None,
        horizons_hours=[24, 168, 720],
    )


def test_capture_extracts_and_stores(tmp_path):
    async def llm(messages, *, provider, model):
        return _extract_payload()

    svc = _make_service(tmp_path, llm)
    n = asyncio.run(svc.capture(feature="market", kind="market_report",
                                title="Brief", body="AAPL looks strong"))
    assert n == 1
    claims = svc.list_claims()
    assert len(claims) == 1 and claims[0]["entity"] == "AAPL"


def test_grade_due_objective_path_and_hindsight(tmp_path, monkeypatch):
    async def llm(messages, *, provider, model):
        return _extract_payload()

    svc = _make_service(tmp_path, llm)
    asyncio.run(svc.capture(feature="market", kind="market_report",
                            title="Brief", body="AAPL strong"))
    created = svc.get_claim(svc.list_claims()[0]["id"])["createdAt"]

    # Patch candle fetch so the ticker objectively rose 5% → a hit, no network.
    # Candles must straddle the claim time: entry just before, exit after.
    async def fake_candles(client, symbol, *, resolution="D", days=30):
        return [
            {"t": created - 3600, "o": 100, "h": 100, "l": 100, "c": 100, "v": 1},
            {"t": created + 86_400, "o": 105, "h": 105, "l": 105, "c": 105, "v": 1},
        ]

    monkeypatch.setattr(service_mod, "fetch_candles", fake_candles)

    # Grade as if 8 days have passed → 24h + 7d checkpoints due.
    future = int(__import__("time").time()) + 8 * 86_400
    graded = asyncio.run(svc.grade_due(now=future))
    assert graded >= 1

    claim = svc.list_claims()[0]
    assert claim["latestGrade"]["outcome"] == "hit"
    assert claim["latestGrade"]["source"] == "objective"

    # Hindsight by entity surfaces the graded call in the "right" bucket.
    hs = asyncio.run(svc.hindsight(feature="market", entity="AAPL", query="AAPL outlook"))
    assert any(item["entity"] == "AAPL" for item in hs["right"])


def test_override_grade_marks_user_verified(tmp_path):
    async def llm(messages, *, provider, model):
        return _extract_payload()

    svc = _make_service(tmp_path, llm)
    asyncio.run(svc.capture(feature="apollo", kind="prediction", title="t", body="AAPL up"))
    cid = svc.list_claims()[0]["id"]
    svc.override_grade(cid, score=95, outcome="hit", reason="I checked")
    claim = svc.get_claim(cid)
    assert claim["status"] == "graded"
    assert claim["grades"][-1]["userVerified"] and claim["grades"][-1]["source"] == "user"


def test_disabled_service_is_noop(tmp_path):
    async def llm(messages, *, provider, model):
        return _extract_payload()

    svc = _make_service(tmp_path, llm)
    svc.enabled = False
    assert asyncio.run(svc.capture(feature="market", kind="r", title="t", body="b")) == 0
    assert asyncio.run(svc.grade_due()) == 0
