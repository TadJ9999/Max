"""Claim extraction tests — JSON parsing, entity canonicalization, validation.
The LLM is mocked; no network."""

import asyncio

from max_engine.oracle.extract import canonical_entity, extract_claims, parse_json_array


def test_parse_json_array_tolerates_fences_and_prose():
    raw = 'Sure! Here:\n```json\n[{"claim":"x"}]\n```\nHope that helps.'
    assert parse_json_array(raw) == [{"claim": "x"}]
    assert parse_json_array("no json here") == []


def test_canonical_entity():
    assert canonical_entity("aapl", "ticker") == ("AAPL", "ticker")
    assert canonical_entity("Ukraine", "country") == ("UA", "country")
    assert canonical_entity("United States", "country") == ("US", "country")
    # Unknown country → stable uppercase slug, still kind=country.
    e, k = canonical_entity("Freedonia", "country")
    assert k == "country" and e == "FREEDONIA"
    # Inference when kind missing: short letters → ticker.
    assert canonical_entity("TSLA", None) == ("TSLA", "ticker")


def _fake_llm(payload):
    async def llm(messages, *, provider, model):
        return payload
    return llm


def test_extract_cleans_and_limits():
    payload = (
        '[{"claim":"AAPL up 5%","entity":"aapl","entity_kind":"ticker","direction":"up",'
        '"magnitude":5,"horizon_hours":168,"confidence":0.8},'
        '{"claim":"","entity":null,"direction":"bogus"},'  # dropped: empty claim
        '{"claim":"War escalates","entity":"Ukraine","entity_kind":"country",'
        '"direction":"event","confidence":1.5}]'  # confidence clamped
    )
    out = asyncio.run(
        extract_claims(_fake_llm(payload), report_text="r", feature="apollo",
                       provider="ollama", model="m")
    )
    assert len(out) == 2
    assert out[0]["entity"] == "AAPL" and out[0]["entity_kind"] == "ticker"
    assert out[1]["entity"] == "UA" and out[1]["confidence"] == 1.0
    assert out[1]["direction"] == "event"


def test_extract_best_effort_on_bad_output():
    out = asyncio.run(
        extract_claims(_fake_llm("garbage"), report_text="r", feature="market",
                       provider="ollama", model="m")
    )
    assert out == []
