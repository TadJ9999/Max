"""Oracle grading primitives — shared constants and pure scoring helpers.

Kept dependency-free (stdlib only) so every other oracle module and the tests can
import these without pulling in numpy/sklearn or the network layer.
"""

from __future__ import annotations

# Fixed failure taxonomy. The LLM judge must pick one of these when a claim
# misses; aggregating the tags is what turns individual misses into "your top
# failure modes" on the dashboard. ``partial-correct`` doubles as the tag for a
# partial outcome.
FAILURE_TAGS: tuple[str, ...] = (
    "wrong-direction",
    "wrong-timing",
    "wrong-magnitude",
    "black-swan",
    "data-gap",
    "overconfidence",
    "partial-correct",
)

# Outcome buckets for a single checkpoint grade.
OUTCOMES: tuple[str, ...] = ("hit", "partial", "miss", "too-early")

# Default multi-horizon checkpoints (hours). A claim is graded at each.
DEFAULT_HORIZONS_HOURS: tuple[int, ...] = (24, 168, 720)

_LABELS = {24: "24h", 168: "7d", 720: "30d"}


def label_for_hours(hours: int) -> str:
    """Stable checkpoint label for a horizon in hours (e.g. 168 → '7d')."""
    if hours in _LABELS:
        return _LABELS[hours]
    if hours % 24 == 0:
        return f"{hours // 24}d"
    return f"{hours}h"


def checkpoints(horizons_hours: list[int] | tuple[int, ...] | None) -> list[tuple[str, int]]:
    """(label, hours) pairs for the configured horizons, ascending."""
    hrs = sorted({int(h) for h in (horizons_hours or DEFAULT_HORIZONS_HOURS) if int(h) > 0})
    return [(label_for_hours(h), h) for h in hrs]


def outcome_from_score(score: int) -> str:
    """Map a 0–100 score to a coarse outcome bucket."""
    if score >= 70:
        return "hit"
    if score >= 40:
        return "partial"
    return "miss"


def hit_fraction(outcome: str, score: int) -> float:
    """The empirical 'did it happen' signal in [0,1] used for Brier + training.
    Prefers the numeric score; falls back to the outcome bucket."""
    if outcome == "too-early":
        return 0.0
    return max(0.0, min(1.0, score / 100.0))


def brier(confidence: float, outcome: str, score: int) -> float:
    """Brier component for one prediction: (stated_confidence − actual)²."""
    actual = hit_fraction(outcome, score)
    c = max(0.0, min(1.0, float(confidence or 0.0)))
    return round((c - actual) ** 2, 4)


def clamp_score(value: object) -> int:
    """Coerce an arbitrary model/JSON value to an int score in [0,100]."""
    try:
        return max(0, min(100, int(round(float(value)))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
