"""Objective ticker grading + LLM-judge tests (stubbed candles / mocked model)."""

import asyncio

from max_engine.oracle.judge import judge_claim, parse_json_object
from max_engine.oracle.objective import grade_ticker


def _candles(entry, exit_px):
    # Oldest first; entry at t=1000, exit at t=2000.
    return [
        {"t": 1000, "o": entry, "h": entry, "l": entry, "c": entry, "v": 1},
        {"t": 2000, "o": exit_px, "h": exit_px, "l": exit_px, "c": exit_px, "v": 1},
    ]


def test_objective_up_call_that_rose_is_a_hit():
    claim = {"entity": "AAPL", "direction": "up", "magnitude": None}
    g = grade_ticker(claim, created_at=1000, candles=_candles(100, 108))
    assert g["outcome"] == "hit" and g["score"] >= 70
    assert g["evidence"]["changePct"] == 8.0


def test_objective_up_call_that_fell_is_a_miss():
    claim = {"entity": "AAPL", "direction": "up", "magnitude": None}
    g = grade_ticker(claim, created_at=1000, candles=_candles(100, 92))
    assert g["outcome"] == "miss"
    assert g["failure_tag"] == "wrong-direction"


def test_objective_magnitude_partial_credit():
    # Predicted +10% but only +3% materialised → right way, short of target.
    claim = {"entity": "MSFT", "direction": "up", "magnitude": 10.0}
    g = grade_ticker(claim, created_at=1000, candles=_candles(100, 103))
    assert g["outcome"] in {"partial", "hit"}
    assert g["evidence"]["changePct"] == 3.0


def test_objective_returns_none_for_non_ticker_or_no_candles():
    assert grade_ticker({"entity": "X", "direction": "event"}, created_at=1000,
                        candles=_candles(100, 110)) is None
    assert grade_ticker({"entity": "X", "direction": "up"}, created_at=1000, candles=[]) is None


def test_parse_json_object():
    assert parse_json_object('```json\n{"a":1}\n```') == {"a": 1}
    assert parse_json_object("nope") == {}


def _judge_llm(payload):
    async def llm(messages, *, provider, model):
        return payload
    return llm


def test_judge_normalizes_and_validates():
    payload = '{"outcome":"miss","score":15,"failure_tag":"wrong-direction",' \
              '"reason":"opposite happened","self_confidence":0.8}'
    claim = {"claim": "Ukraine ceasefire", "entity": "UA", "entityKind": "country"}
    v = asyncio.run(
        judge_claim(_judge_llm(payload), claim, evidence="...", checkpoint="7d",
                    provider="ollama", model="m")
    )
    assert v["outcome"] == "miss" and v["score"] == 15
    assert v["failure_tag"] == "wrong-direction" and v["self_confidence"] == 0.8


def test_judge_bad_output_defers():
    claim = {"claim": "x"}
    v = asyncio.run(
        judge_claim(_judge_llm("garbage"), claim, evidence="...", checkpoint="24h",
                    provider="ollama", model="m")
    )
    assert v["outcome"] == "too-early"


def test_judge_invalid_tag_dropped():
    payload = '{"outcome":"hit","score":90,"failure_tag":"made-up-tag","reason":"ok"}'
    v = asyncio.run(
        judge_claim(_judge_llm(payload), {"claim": "x"}, evidence="e", checkpoint="7d",
                    provider="ollama", model="m")
    )
    # hit → tag forced null regardless of model output
    assert v["outcome"] == "hit" and v["failure_tag"] is None
