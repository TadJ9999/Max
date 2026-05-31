"""Secret redaction for Aegis.

Scrubs known key patterns from strings before they are stored or sent to the
cloud. Applied to all error messages and tracebacks on ingest.
"""

from __future__ import annotations

import re

# Ordered from most-specific to most-generic so greedy patterns don't shadow others.
_RULES: list[tuple[re.Pattern, str]] = [
    # Anthropic sk-ant-* keys
    (re.compile(r"sk-ant-[a-zA-Z0-9\-_]{10,}", re.IGNORECASE), "[ANTHROPIC_KEY_REDACTED]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[a-zA-Z0-9\-_\.]{8,}", re.IGNORECASE), "Bearer [REDACTED]"),
    # KEY=value style (env vars / config dumps): KEY must be ≥8 uppercase chars
    (re.compile(r"\b([A-Z_]{8,})\s*[=:]\s*['\"]?(\S{6,})['\"]?"), r"\1=[REDACTED]"),
    # JSON-style "key": "value" where key contains API/KEY/SECRET/TOKEN
    (
        re.compile(r'"([\w]*(?:api[_\-]?key|secret|token|password|apikey)[\w]*)"\s*:\s*"([^"]{6,})"', re.IGNORECASE),
        r'"\1": "[REDACTED]"',
    ),
    # URL-embedded secrets (e.g. ?token=xxx or ?key=xxx in query strings)
    (re.compile(r"([?&](?:token|key|secret|api_key)=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    """Return a copy of *text* with secrets replaced by placeholder tokens."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(data: dict) -> dict:
    """Recursively redact string values in a dict (shallow copy)."""
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, str):
            out[k] = redact(v)
        elif isinstance(v, dict):
            out[k] = redact_dict(v)
        else:
            out[k] = v
    return out
