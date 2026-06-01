"""Claim extraction — turn a free-text report into atomic, checkable claims.

One LLM call per report (local model by default). The model returns a strict
JSON array; we parse it defensively (models love to wrap JSON in prose or code
fences), validate every field, and canonicalize the entity so the same ticker or
country always tags the same way — which is what makes grading and the hindsight
entity-match work.

Best-effort: any failure (bad JSON, model down) yields ``[]`` so capture never
breaks report generation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

_DIRECTIONS = {"up", "down", "event", "no-change"}
_ENTITY_KINDS = {"ticker", "country", "topic"}

# Minimal country → ISO-2 map for the entities Apollo/OSINT actually surface.
# Falls back to a lowercase slug for anything not listed (still a stable tag).
_COUNTRY_ISO = {
    "united states": "US", "usa": "US", "us": "US", "america": "US",
    "russia": "RU", "ukraine": "UA", "china": "CN", "taiwan": "TW",
    "israel": "IL", "iran": "IR", "north korea": "KP", "south korea": "KR",
    "india": "IN", "pakistan": "PK", "japan": "JP", "germany": "DE",
    "france": "FR", "united kingdom": "GB", "uk": "GB", "britain": "GB",
    "saudi arabia": "SA", "syria": "SY", "lebanon": "LB", "yemen": "YE",
    "venezuela": "VE", "turkey": "TR", "egypt": "EG", "gaza": "PS",
    "palestine": "PS", "afghanistan": "AF", "iraq": "IQ", "poland": "PL",
}

# LLM caller: (messages, *, provider, model) -> assembled text.
LLM = Callable[..., Awaitable[str]]

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_array(text: str) -> list:
    """Pull the first JSON array out of a model response, tolerating code fences
    and leading/trailing prose. Returns ``[]`` if none parses."""
    if not text:
        return []
    m = _FENCE_RE.search(text)
    candidate = m.group(1) if m else text
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(candidate[start : end + 1])
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def canonical_entity(entity: str | None, entity_kind: str | None) -> tuple[str | None, str | None]:
    """Normalize an entity so the same thing always tags identically.
    Tickers → upper; countries → ISO-2 (or slug); topics → lowercase slug."""
    if not entity or not entity.strip():
        return None, None
    raw = entity.strip()
    kind = (entity_kind or "").strip().lower()
    if kind not in _ENTITY_KINDS:
        # Infer: 1–5 all-letters uppercase-ish → ticker; else topic.
        kind = "ticker" if re.fullmatch(r"[A-Za-z]{1,5}", raw) else "topic"
    if kind == "ticker":
        return raw.upper(), "ticker"
    if kind == "country":
        iso = _COUNTRY_ISO.get(raw.lower())
        return (iso or re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-").upper(), "country")
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return (slug.upper() if slug else None), "topic"


def _clean_claim(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    text = str(item.get("claim", "")).strip()
    if not text:
        return None
    direction = str(item.get("direction", "")).strip().lower()
    if direction not in _DIRECTIONS:
        direction = "event"
    entity, entity_kind = canonical_entity(item.get("entity"), item.get("entity_kind"))
    try:
        horizon = int(item.get("horizon_hours") or 0)
    except (TypeError, ValueError):
        horizon = 0
    try:
        conf = float(item.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.5
    mag = item.get("magnitude")
    try:
        mag = float(mag) if mag is not None else None
    except (TypeError, ValueError):
        mag = None
    return {
        "claim": text[:400],
        "entity": entity,
        "entity_kind": entity_kind,
        "direction": direction,
        "magnitude": mag,
        "horizon_hours": horizon if horizon > 0 else None,
        "confidence": max(0.0, min(1.0, conf)),
    }


async def extract_claims(
    llm: LLM,
    *,
    report_text: str,
    feature: str,
    provider: str,
    model: str,
    max_claims: int = 8,
) -> list[dict]:
    """Extract up to ``max_claims`` atomic claims from a report. Returns a list of
    cleaned claim dicts ready for :meth:`OracleStore.add_claims`."""
    from ..prompts import oracle_extract_messages

    if not report_text or not report_text.strip():
        return []
    messages = oracle_extract_messages(feature=feature, report=report_text[:6000])
    try:
        raw = await llm(messages, provider=provider, model=model)
    except Exception:
        return []
    items = parse_json_array(raw)
    out: list[dict] = []
    for it in items[: max_claims * 2]:
        cleaned = _clean_claim(it)
        if cleaned:
            out.append(cleaned)
        if len(out) >= max_claims:
            break
    return out
