"""Coordinator — decompose one high-level request into parallel subtasks.

The delegator/coordinator is the "let AI delegate" path: a planner model breaks a
request into independent subtasks, each of which becomes an isolated delegate
session. The scheduler then runs them in parallel within the 12 GB VRAM ceiling
(local heavy models queue; cloud + light tasks fan out), exactly like manually
submitted sessions — the coordinator just produces the task list.

Parsing is defensive: planner models don't always return clean JSON, so we strip
fences, slice to the outermost array, validate each item, and fall back to a
single subtask (the original request) if nothing usable comes back.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ..providers.base import ChatChunk

VALID_ACTIONS = ("generate", "summarize", "fix", "chat")


@dataclass
class SubtaskSpec:
    task: str
    action: str = "generate"
    complexity: float = 0.5


async def collect(stream: AsyncIterator[ChatChunk]) -> str:
    """Drain a provider stream into a single string (planner output is short)."""
    parts: list[str] = []
    async for chunk in stream:
        parts.append(chunk.text)
    return "".join(parts)


def _coerce_item(raw: object) -> SubtaskSpec | None:
    """Validate one planner item into a SubtaskSpec, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    task = raw.get("task")
    if not isinstance(task, str) or not task.strip():
        return None
    action = raw.get("action")
    if action not in VALID_ACTIONS:
        action = "generate"
    try:
        complexity = float(raw.get("complexity", 0.5))
    except (TypeError, ValueError):
        complexity = 0.5
    complexity = min(1.0, max(0.0, complexity))
    return SubtaskSpec(task=task.strip(), action=action, complexity=complexity)


def parse_plan(text: str, fallback_task: str, max_subtasks: int = 6) -> list[SubtaskSpec]:
    """Parse a planner response into subtasks; never returns empty.

    Falls back to a single subtask running the original request when the model
    returns no usable JSON array.
    """
    specs: list[SubtaskSpec] = []
    candidate = _slice_json_array(text)
    if candidate is not None:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            for raw in data:
                spec = _coerce_item(raw)
                if spec is not None:
                    specs.append(spec)
                if len(specs) >= max_subtasks:
                    break
    if not specs:  # planner gave nothing usable -> run the request as one task
        specs = [SubtaskSpec(task=fallback_task.strip(), action="generate")]
    return specs


def _slice_json_array(text: str) -> str | None:
    """Extract the outermost ``[ ... ]`` from a planner response, ignoring any
    surrounding prose or ```` ```json ```` fences."""
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return None
