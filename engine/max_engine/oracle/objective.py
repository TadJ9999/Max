"""Objective grading — score a ticker claim against real price history.

No model, no cost: for a ticker claim we already know the truth from the market.
Pull daily/hourly candles spanning the claim's life, compare the price at claim
time to the latest price, and score how well the call's direction (and magnitude,
if given) matched reality. Soft/geopolitical claims fall through to the LLM judge.
"""

from __future__ import annotations

from .grading import clamp_score, outcome_from_score

# A move smaller than this (percent) counts as "flat" for direction purposes.
_FLAT_BAND = 1.0


def _price_at(candles: list[dict], ts: int) -> float | None:
    """Close of the last candle at or before ``ts`` (entry price). Falls back to
    the earliest candle when the claim predates the window."""
    entry = None
    for c in candles:
        if c["t"] <= ts:
            entry = c["c"]
        else:
            break
    if entry is None and candles:
        entry = candles[0]["c"]
    return entry


def grade_ticker(
    claim: dict, *, created_at: int, candles: list[dict]
) -> dict | None:
    """Grade a ticker claim from OHLCV candles (oldest first). Returns a grade
    dict ``{score, outcome, reason, evidence, failure_tag}`` or ``None`` when the
    claim isn't objectively gradeable (no candles / non-ticker / no direction)."""
    if not candles or len(candles) < 2:
        return None
    direction = (claim.get("direction") or "").lower()
    if direction not in {"up", "down", "no-change"}:
        return None  # 'event'-style ticker claims aren't price-checkable here

    entry = _price_at(candles, created_at)
    exit_px = candles[-1]["c"]
    if not entry or entry <= 0:
        return None
    pct = (exit_px - entry) / entry * 100.0

    target = claim.get("magnitude")
    score: int
    failure_tag: str | None = None

    if direction == "no-change":
        score = clamp_score(100 - abs(pct) / _FLAT_BAND * 40)
        if abs(pct) >= _FLAT_BAND:
            failure_tag = "wrong-direction"
    else:
        want_up = direction == "up"
        moved_right_way = (pct > 0) if want_up else (pct < 0)
        if not moved_right_way:
            score = clamp_score(35 - min(abs(pct), 10) * 3)  # wrong way → low
            failure_tag = "wrong-direction" if abs(pct) >= _FLAT_BAND else "wrong-timing"
        elif target:
            # Right direction; reward proximity to the predicted magnitude.
            achieved = abs(pct) / abs(target) if target else 0.0
            score = clamp_score(60 + min(achieved, 1.5) * 26)
            if achieved < 0.5:
                failure_tag = "wrong-magnitude"
        else:
            # Right direction, no magnitude target → solid credit scaled by move.
            score = clamp_score(65 + min(abs(pct), 8) * 4)

    outcome = outcome_from_score(score)
    if outcome == "hit":
        failure_tag = None
    elif outcome == "partial" and not failure_tag:
        failure_tag = "partial-correct"
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "►")
    reason = (
        f"{claim.get('entity')} moved {arrow} {pct:+.2f}% from {entry:.2f} to {exit_px:.2f} "
        f"vs a '{direction}' call"
        + (f" targeting {target:+.1f}%" if target else "")
        + "."
    )
    return {
        "score": score,
        "outcome": outcome,
        "failure_tag": failure_tag,
        "reason": reason,
        "evidence": {
            "entry": round(entry, 4),
            "exit": round(exit_px, 4),
            "changePct": round(pct, 3),
            "candleCount": len(candles),
        },
    }
