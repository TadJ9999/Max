"""System prompts per DSL action. User-editable templates land in Phase 4."""

from __future__ import annotations

SYSTEM_PROMPTS: dict[str, str] = {
    "generate": (
        "You are a senior coding assistant. Generate code that fulfils the request. "
        "Output only the code (no prose, no fences) unless explicitly asked otherwise, "
        "matching the surrounding language and style."
    ),
    "summarize": (
        "You write concise documentation. Given code, produce a clear docstring or "
        "README section describing what it does, its parameters, and its return value."
    ),
    "fix": (
        "You fix and refactor code. Return the corrected code, preserving behavior "
        "unless a bug is being fixed. Output only the code unless asked to explain."
    ),
    "chat": "You are Max, a helpful, concise assistant.",
}


def messages_for(action: str, body: str) -> list[dict]:
    """Build chat messages for a parsed DSL command."""
    system = SYSTEM_PROMPTS.get(action, SYSTEM_PROMPTS["chat"])
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": body},
    ]
