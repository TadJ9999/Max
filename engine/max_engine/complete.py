"""Fill-in-the-middle (FIM) code completion via Ollama ``/api/generate``.

Ollama's generate endpoint takes ``prompt`` (code before the cursor) and
``suffix`` (code after); FIM-capable models (qwen2.5-coder, codellama, …) infill
the gap. This powers the VS Code extension's ghost-text inline completion.

Best-effort: returns ``""`` on any failure so the editor degrades to "no
suggestion" rather than erroring. An ``httpx.AsyncClient`` is injectable for
testing.
"""

from __future__ import annotations

import httpx


async def fim_complete(
    prefix: str,
    suffix: str = "",
    *,
    model: str,
    base_url: str = "http://127.0.0.1:11434",
    max_tokens: int = 96,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Infill the code between ``prefix`` and ``suffix``. Returns the middle text
    (may be empty). Low temperature + a token cap keep it snappy for ghost text."""
    if not prefix and not suffix:
        return ""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={
                "model": model,
                "prompt": prefix,
                "suffix": suffix,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.1},
            },
        )
        if resp.status_code >= 400:
            return ""
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return ""
    finally:
        if owns:
            await client.aclose()
    if not isinstance(data, dict):
        return ""
    return data.get("response", "") or ""
