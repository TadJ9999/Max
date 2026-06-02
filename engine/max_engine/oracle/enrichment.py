"""Enrichment analyzer — Oracle recommending *what data would make it sharper*.

Closes the learning loop: Oracle already grades its own predictions and learns a
calibrator from the track record. Here it turns that track record into concrete
data-source suggestions. Two layers:

  1. ``build_gap_report`` — deterministic signal extraction from the existing
     stats + calibrator metrics (top failure modes, hardest entities, weak signal
     reliability, which source *kinds* are active vs available). No LLM, no cost.
  2. Leo (the LLM) turns the gap report + a catalog of available sources into
     ranked, plain-English suggestions. If the model is unavailable or unparseable,
     ``heuristic_suggestions`` produces grounded fallbacks from the same gap report,
     so the tab is always useful — even fully offline.

Suggest-only: nothing here mutates config. Each suggestion tells the user what to
add (and where), and why it should help.
"""

from __future__ import annotations

import json
import re

from .grading import FAILURE_TAGS

# Source kinds Oracle can recommend. ``configKey`` tells the user where to wire it.
CANDIDATE_SOURCES: list[dict] = [
    {"type": "gnews", "label": "GNews.io query search",
     "configKey": "Settings → OSINT → GNews (set GNEWS_API_KEY + enable)",
     "good_for": "query-targeted, broad-outlet coverage that fills evidence gaps"},
    {"type": "feeds:world", "label": "More world-news RSS",
     "configKey": "Settings → OSINT → feeds",
     "good_for": "general geopolitical breadth and source diversity"},
    {"type": "feeds:finance", "label": "Finance & markets RSS",
     "configKey": "Settings → OSINT → feeds",
     "good_for": "ticker / market claims that lack supporting headlines"},
    {"type": "feeds:osint", "label": "Specialist OSINT feeds (ReliefWeb, Bellingcat, CISA)",
     "configKey": "Settings → OSINT → feeds",
     "good_for": "high-signal conflict, humanitarian, and cyber coverage"},
    {"type": "telegram", "label": "Telegram OSINT channels (planned)",
     "configKey": "not yet available",
     "good_for": "fast, on-the-ground breaking signals ahead of mainstream press"},
    {"type": "x", "label": "X.com / Twitter OSINT (planned)",
     "configKey": "not yet available",
     "good_for": "real-time reaction and primary-source amplification"},
]

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_PRIORITIES = ("high", "medium", "low")


# ---- layer 1: deterministic gap report --------------------------------------


def build_gap_report(
    stats: dict, model_metrics: dict, configured_sources: dict
) -> dict:
    """Extract the signals that argue for more data, from existing Oracle output."""
    failures = stats.get("failureModes") or {}
    top_failures = sorted(
        ({"tag": t, "count": int(n)} for t, n in failures.items() if t in FAILURE_TAGS),
        key=lambda d: -d["count"],
    )[:5]

    # Hardest entities: prefer the calibrator's shrunk per-entity skill; fall back
    # to the raw per-entity average score when the model hasn't trained yet.
    hardest = model_metrics.get("hardestEntities") or []
    if not hardest:
        per_entity = stats.get("perEntity") or []
        hardest = [
            {"entity": r["entity"], "skill": round((r.get("avgScore") or 0) / 100, 3)}
            for r in sorted(per_entity, key=lambda r: (r.get("avgScore") or 0))[:6]
        ]

    # Weakest signals: most negative logistic-regression reliability coefficients.
    reliability = model_metrics.get("reliability") or {}
    weak_signals = [
        {"signal": k, "coef": v}
        for k, v in sorted(reliability.items(), key=lambda kv: kv[1])
        if v < 0
    ][:6]

    osint = configured_sources.get("osint") or {}
    rss = osint.get("rss") or {}
    active_groups = rss.get("groups") or {}
    gnews = osint.get("gnews") or {}
    active_types = set()
    if osint.get("gdelt", {}).get("enabled"):
        active_types.add("gdelt")
    if rss.get("enabled"):
        for g in active_groups:
            active_types.add(f"feeds:{g}")
    if gnews.get("enabled") and gnews.get("hasKey"):
        active_types.add("gnews")

    missing = [c for c in CANDIDATE_SOURCES if c["type"] not in active_types]

    return {
        "resolvedGrades": stats.get("resolvedGrades", 0),
        "accuracy": stats.get("accuracy"),
        "avgScore": stats.get("avgScore"),
        "modelReady": bool(model_metrics.get("ready")),
        "topFailureModes": top_failures,
        "dataGapCount": int(failures.get("data-gap", 0)),
        "blackSwanCount": int(failures.get("black-swan", 0)),
        "wrongTimingCount": int(failures.get("wrong-timing", 0)),
        "hardestEntities": hardest[:6],
        "weakSignals": weak_signals,
        "activeSourceTypes": sorted(active_types),
        "activeFeedGroups": active_groups,
        "missingSourceTypes": [c["type"] for c in missing],
    }


# ---- layer 2a: heuristic fallback -------------------------------------------


def _suggestion(
    title: str, rationale: str, source_type: str, config_hint: str,
    impact: str, priority: str,
) -> dict:
    return {
        "title": title[:120],
        "rationale": rationale[:400],
        "sourceType": source_type,
        "suggestedConfig": config_hint[:160],
        "expectedImpact": impact,
        "priority": priority if priority in _PRIORITIES else "medium",
    }


def heuristic_suggestions(gap: dict, catalog: dict | None = None) -> list[dict]:
    """Rule-based suggestions grounded in the gap report. Used when the LLM is
    unavailable or returns nothing parseable."""
    by_type = {c["type"]: c for c in CANDIDATE_SOURCES}
    out: list[dict] = []
    missing = set(gap.get("missingSourceTypes") or [])

    # Evidence gaps at grade time → broaden, query-targeted intake first.
    if gap.get("dataGapCount", 0) > 0 and "gnews" in missing:
        out.append(_suggestion(
            "Enable GNews query search",
            f"'data-gap' is among your failure modes ({gap['dataGapCount']}×): claims are "
            "being graded without enough fresh evidence. GNews adds query-targeted "
            "coverage across many outlets to fill those gaps.",
            "gnews", by_type["gnews"]["configKey"],
            "more grade-time evidence → fewer data-gap misses", "high",
        ))

    # Country/geo entities are hardest → specialist OSINT feeds.
    hardest_names = [str(h.get("entity") or "") for h in gap.get("hardestEntities") or []]
    geo_like = [e for e in hardest_names if e and (len(e) <= 3 or e.isupper())]
    if geo_like and "feeds:osint" in missing:
        out.append(_suggestion(
            "Add specialist OSINT feeds",
            f"Your hardest entities ({', '.join(geo_like[:4])}) are thinly covered. "
            "ReliefWeb, Bellingcat and gov advisories add higher-signal conflict, "
            "humanitarian and cyber reporting on exactly these.",
            "feeds:osint", by_type["feeds:osint"]["configKey"],
            "better evidence on low-skill entities → higher accuracy", "high",
        ))

    # Finance group absent but market work exists → finance feeds.
    if "feeds:finance" in missing:
        out.append(_suggestion(
            "Add finance & markets feeds",
            "No finance-specific feeds are active. CNBC/MarketWatch/Yahoo Finance give "
            "market and ticker claims supporting headlines to be judged against.",
            "feeds:finance", by_type["feeds:finance"]["configKey"],
            "stronger grading of market/ticker claims", "medium",
        ))

    # Surprises / timing errors → faster, real-time sources (future social).
    if gap.get("blackSwanCount", 0) > 0 or gap.get("wrongTimingCount", 0) > 0:
        for t in ("telegram", "x"):
            if t in missing:
                c = by_type[t]
                out.append(_suggestion(
                    f"Plan for {c['label']}",
                    "'black-swan' / 'wrong-timing' misses suggest you're seeing events "
                    f"late. {c['label']} would surface {c['good_for']}.",
                    t, c["configKey"],
                    "earlier signal on fast-moving events", "low",
                ))
                break

    if not out:
        out.append(_suggestion(
            "Coverage looks healthy",
            "No strong data-gap signal yet. Keep grading; suggestions sharpen as the "
            "track record grows.",
            "none", "—", "n/a", "low",
        ))
    return out


# ---- layer 2b: LLM path -----------------------------------------------------


def build_messages(gap: dict) -> list[dict]:
    """Prompt Leo to turn the gap report into ranked source suggestions (JSON)."""
    catalog_lines = "\n".join(
        f"- {c['type']}: {c['label']} — good for {c['good_for']} "
        f"(add via: {c['configKey']})"
        for c in CANDIDATE_SOURCES
    )
    system = (
        "You are Leo, Max's data strategist. You decide what NEW data sources would "
        "make the Oracle prediction engine's forecasts and self-grading more accurate. "
        "You are given a gap report derived from Oracle's own track record, and a "
        "catalog of available sources. Recommend the highest-leverage additions.\n\n"
        "Return ONLY a JSON array (no prose) of 2-5 objects, each:\n"
        '{"title": str, "rationale": str (tie it to a specific gap signal), '
        '"sourceType": one of the catalog types, "suggestedConfig": where/how to add it, '
        '"expectedImpact": short phrase, "priority": "high"|"medium"|"low"}.\n'
        "Only recommend sources from the catalog. Prefer ones not already active."
    )
    user = (
        "Available source catalog:\n" + catalog_lines + "\n\n"
        "Oracle gap report (JSON):\n" + json.dumps(gap, indent=2)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_suggestions(text: str) -> list[dict]:
    """Extract a JSON array of suggestions from a model response. ``[]`` on failure."""
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
    if not isinstance(data, list):
        return []
    valid_types = {c["type"] for c in CANDIDATE_SOURCES} | {"none"}
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        rationale = str(item.get("rationale", "")).strip()
        if not title or not rationale:
            continue
        stype = str(item.get("sourceType", "")).strip()
        if stype not in valid_types:
            stype = "feeds:world"
        out.append(_suggestion(
            title, rationale, stype,
            str(item.get("suggestedConfig", "")).strip() or "—",
            str(item.get("expectedImpact", "")).strip()[:80] or "—",
            str(item.get("priority", "medium")).strip().lower(),
        ))
        if len(out) >= 6:
            break
    return out
