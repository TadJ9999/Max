"""LLM-as-judge — grade a soft claim against freshly gathered evidence.

For geopolitical / qualitative claims there is no price to check, so a model
compares the original claim to current evidence (recent OSINT headlines, market
news) and returns a structured verdict. Runs on the local model by default; the
caller may escalate low-confidence or high-stakes calls to a cloud model.

The judge must return strict JSON; we parse defensively and validate every field
against the fixed taxonomy so a hallucinated tag never reaches the store.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from .grading import FAILURE_TAGS, OUTCOMES, clamp_score, outcome_from_score

LLM = Callable[..., Awaitable[str]]

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """Extract the first JSON object from a model response. ``{}`` on failure."""
    if not text:
        return {}
    m = _FENCE_RE.search(text)
    candidate = m.group(1) if m else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(candidate[start : end + 1])
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize(data: dict) -> dict:
    score = clamp_score(data.get("score", 0))
    outcome = str(data.get("outcome", "")).strip().lower()
    if outcome not in OUTCOMES:
        outcome = outcome_from_score(score)
    tag = data.get("failure_tag")
    tag = str(tag).strip().lower() if tag else None
    if tag not in FAILURE_TAGS:
        tag = None
    if outcome == "hit":
        tag = None
    try:
        self_conf = float(data.get("self_confidence", 0.6))
    except (TypeError, ValueError):
        self_conf = 0.6
    return {
        "score": score,
        "outcome": outcome,
        "failure_tag": tag,
        "reason": str(data.get("reason", "")).strip()[:600],
        "self_confidence": max(0.0, min(1.0, self_conf)),
    }


async def judge_claim(
    llm: LLM,
    claim: dict,
    *,
    evidence: str,
    checkpoint: str,
    provider: str,
    model: str,
) -> dict:
    """Grade one claim with the given provider/model. Returns the normalized
    verdict dict (always valid against the taxonomy), or a ``too-early`` fallback
    when the model can't be parsed."""
    from ..prompts import oracle_judge_messages

    messages = oracle_judge_messages(claim=claim, evidence=evidence, checkpoint=checkpoint)
    try:
        raw = await llm(messages, provider=provider, model=model)
    except Exception:
        return {
            "score": 0, "outcome": "too-early", "failure_tag": None,
            "reason": "Judge unavailable; will retry at the next checkpoint.",
            "self_confidence": 0.0,
        }
    data = parse_json_object(raw)
    if not data:
        return {
            "score": 0, "outcome": "too-early", "failure_tag": None,
            "reason": "No parseable verdict; deferred.", "self_confidence": 0.0,
        }
    return _normalize(data)
