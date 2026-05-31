"""Output post-processing for DSL command responses.

For streaming responses the extension applies these transforms incrementally on
the accumulated text (see extension/src/extension.ts postProcess).  This module
provides the same logic for non-streaming callers (tests, CLI, future REST
clients that request a single buffered response).
"""

from __future__ import annotations

import re

_OPEN_FENCE = re.compile(r"^```[^\n]*\n?", re.MULTILINE)
_CLOSE_FENCE = re.compile(r"\n?```\s*$")


def strip_fences(text: str) -> str:
    """Remove the outermost opening and closing markdown code fences."""
    text = _OPEN_FENCE.sub("", text, count=1)
    text = _CLOSE_FENCE.sub("", text)
    return text


def reindent(text: str, base_indent: str) -> str:
    """Prepend *base_indent* to every line except the first.

    The first line is placed at the cursor which is already indented; subsequent
    lines need the base indent added so the whole block aligns correctly.
    Blank continuation lines are left blank (no trailing whitespace injected).
    """
    if not base_indent:
        return text
    lines = text.split("\n")
    result = [
        line if (i == 0 or line == "") else base_indent + line
        for i, line in enumerate(lines)
    ]
    return "\n".join(result)


def postprocess(text: str, base_indent: str = "") -> str:
    """Full pipeline: strip fences then reindent."""
    return reindent(strip_fences(text), base_indent)
