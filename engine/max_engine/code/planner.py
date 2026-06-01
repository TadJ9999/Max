"""Multi-file AI edit planner.

Given a natural-language request and the contents of relevant files, asks the
model to produce a structured JSON edit plan. The plan is streamed as SSE
status messages followed by the JSON payload.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..providers.base import Provider

_PLANNER_SYSTEM = """You are Max Code, an expert software engineer helping the user
make targeted, correct changes across their codebase.

The user will describe a change they want. You will receive the relevant file
contents. Your job is to produce a JSON edit plan.

Return ONLY a valid JSON object with this exact structure (no prose, no fences):
{
  "summary": "one-sentence description of the change",
  "patches": [
    {
      "path": "relative/path/to/file.ts",
      "description": "what changes in this file",
      "new_content": "<full updated file content>"
    }
  ]
}

Rules:
- Include ONLY files that actually need to change.
- "new_content" must be the COMPLETE file content after the change (not a diff).
- Preserve existing indentation, style, and formatting conventions.
- Make the smallest changes that satisfy the request.
- Do not include any text outside the JSON object."""


@dataclass
class FilePatch:
    path: str
    description: str
    old_content: str
    new_content: str


@dataclass
class EditPlan:
    summary: str
    patches: list[FilePatch] = field(default_factory=list)


async def stream_plan(
    request: str,
    file_contexts: list[dict],  # [{"path": str, "content": str}]
    provider: Provider,
    model: str,
) -> AsyncIterator[str]:
    """Yield SSE-style strings: status lines then a final ``plan:`` JSON line."""
    context_block = "\n\n".join(
        f"=== {fc['path']} ===\n{fc['content']}" for fc in file_contexts
    )
    user_msg = (
        f"Request: {request}\n\n"
        f"Relevant files:\n{context_block}"
    )
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    yield 'data: {"status": "Analysing files…"}\n\n'

    accumulated = ""
    async for chunk in provider.chat(model, messages):
        if chunk.done:
            break
        accumulated += chunk.text

    # Strip markdown fences if the model wrapped the JSON anyway.
    text = accumulated.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        yield f'data: {json.dumps({"error": f"model returned invalid JSON: {e}"})}\n\n'
        return

    plan_data = {
        "summary": data.get("summary", ""),
        "patches": data.get("patches", []),
    }
    yield f"data: {json.dumps({'plan': plan_data})}\n\n"
    yield "data: [DONE]\n\n"
