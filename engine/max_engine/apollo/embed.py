"""Ollama embeddings client for Apollo (default ``nomic-embed-text``, 768-dim).

Best-effort: returns ``[]`` on any failure (model not pulled, Ollama down, bad
response) so ingestion/retrieval never crashes a request — Apollo just skips the
vector step and the report/prediction still streams.
"""

from __future__ import annotations

import httpx

DEFAULT_EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text output dimension


async def embed_texts(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    base_url: str = "http://127.0.0.1:11434",
    client: httpx.AsyncClient | None = None,
) -> list[list[float]]:
    """Embed a batch of texts via Ollama ``/api/embed``. Returns one vector per
    input (aligned by index), or ``[]`` on any failure."""
    cleaned = [t for t in texts if t and t.strip()]
    if not cleaned:
        return []
    owns = client is None
    client = client or httpx.AsyncClient(timeout=60.0)
    try:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/embed",
            json={"model": model, "input": cleaned},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if owns:
            await client.aclose()

    embs = data.get("embeddings")
    if not isinstance(embs, list) or len(embs) != len(cleaned):
        return []
    return embs
