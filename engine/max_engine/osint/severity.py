"""News criticality classification — Critical / High / Medium / Low.

Volume alone made every busy country look equally "hot". Severity grades the
*nature* of the news instead: a country with a missile strike outranks one with
an election, regardless of article count. Keyword-driven and intentionally
simple — tuned for headlines, where the strongest signal wins.

Matching is word-boundary aware so "war" doesn't fire inside "Star Wars",
"warn", or "swarm". A trailing ``*`` marks a stem (prefix match) so "insurgen*"
catches insurgent/insurgency while bare words stay whole.

Tiers (high → low): 3 critical, 2 high, 1 medium, 0 low.
"""

from __future__ import annotations

import re

CRITICAL = 3
HIGH = 2
MEDIUM = 1
LOW = 0

LABELS: dict[int, str] = {CRITICAL: "critical", HIGH: "high", MEDIUM: "medium", LOW: "low"}

# Checked strongest-first; the first tier that matches wins.
_CRITICAL = (
    "war", "invasion", "invad*", "missile*", "airstrike*", "air strike*", "drone strike*",
    "killed", "death toll", "massacre*", "genocide", "terror*", "bombing*", "bombard*",
    "explosion*", "shelling", "offensive", "coup", "nuclear", "hostage*", "casualt*",
    "militant*", "insurgen*", "assassinat*", "ethnic cleansing", "warplane*", "artillery",
    "ceasefire*",
)
_HIGH = (
    "attack*", "clash*", "conflict*", "violence", "violent", "riot*", "unrest",
    "crackdown*", "threat*", "crisis", "crises", "evacuat*", "wildfire*", "earthquake*",
    "flood*", "hurricane*", "cyclone*", "disaster*", "outbreak*", "epidemic*", "shooting*",
    "standoff", "blockade*", "sanction*", "protest*", "strike*", "raid*", "kidnap*", "famine",
)
_MEDIUM = (
    "election*", "vote*", "ballot*", "summit*", "talks", "negotiat*", "economy",
    "economic*", "inflation", "recession", "tariff*", "trade", "diplomat*", "policy",
    "parliament*", "court*", "trial*", "accord*", "resign*", "scandal*", "dispute*", "deal",
)


def _compile(words: tuple[str, ...]) -> re.Pattern[str]:
    alts = []
    for w in words:
        if w.endswith("*"):
            alts.append(re.escape(w[:-1]))  # stem: boundary before only
        else:
            alts.append(re.escape(w) + r"\b")  # whole word: boundary both ends
    return re.compile(r"\b(?:" + "|".join(alts) + ")", re.IGNORECASE)


_CRIT_RE = _compile(_CRITICAL)
_HIGH_RE = _compile(_HIGH)
_MED_RE = _compile(_MEDIUM)


def classify(title: str | None, extra: str | None = None) -> int:
    """Grade a headline's criticality. ``extra`` (summary) is also scanned."""
    text = f"{title or ''} {extra or ''}"
    if not text.strip():
        return LOW
    if _CRIT_RE.search(text):
        return CRITICAL
    if _HIGH_RE.search(text):
        return HIGH
    if _MED_RE.search(text):
        return MEDIUM
    return LOW
