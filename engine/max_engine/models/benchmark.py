"""Live benchmark runner.

Fires a timed prompt at an Ollama model and measures:
  - TTFT (time-to-first-token) in ms
  - Tokens/second (generation throughput)

The prompt is short and deterministic so results are comparable across models.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

BENCHMARK_PROMPT = (
    "Write a Python function that takes a list of integers and returns the "
    "median value. Include a docstring. Be concise."
)

BENCHMARK_SYSTEM = "You are a helpful coding assistant. Respond immediately and concisely."


async def run_benchmark(
    model: str,
    base_url: str = "http://127.0.0.1:11434",
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Benchmark ``model`` on Ollama.  Returns a dict with timing fields."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": BENCHMARK_SYSTEM},
            {"role": "user", "content": BENCHMARK_PROMPT},
        ],
        "stream": True,
        "keep_alive": "5m",
    }

    owns = client is None
    client = client or httpx.AsyncClient(timeout=120.0)

    ttft_ms: float | None = None
    token_count = 0
    start = time.perf_counter()
    first_token_t: float | None = None

    try:
        async with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                import json
                data = json.loads(line)
                text: str = data.get("message", {}).get("content", "")
                if text:
                    token_count += 1
                    if first_token_t is None:
                        first_token_t = time.perf_counter()
                        ttft_ms = (first_token_t - start) * 1000
                if data.get("done"):
                    # Ollama reports eval_count (generated tokens) at the end
                    eval_count = data.get("eval_count", token_count)
                    eval_duration_ns = data.get("eval_duration", 0)
                    if eval_duration_ns > 0:
                        tps = eval_count / (eval_duration_ns / 1e9)
                    else:
                        elapsed = time.perf_counter() - (first_token_t or start)
                        tps = eval_count / elapsed if elapsed > 0 else 0.0
                    prompt_tokens = data.get("prompt_eval_count", 0)
                    total_tokens = data.get("eval_count", token_count)
                    break
            else:
                tps = 0.0
                prompt_tokens = 0
                total_tokens = token_count
    finally:
        if owns:
            await client.aclose()

    return {
        "model": model,
        "ttft_ms": round(ttft_ms or 0.0, 1),
        "tokens_per_sec": round(tps, 1),
        "prompt_tokens": prompt_tokens,
        "total_tokens": total_tokens,
    }


async def list_ollama_models(
    base_url: str = "http://127.0.0.1:11434",
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Return installed Ollama models from /api/tags."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.get(f"{base_url}/api/tags")
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("models", [])
    except httpx.HTTPError:
        return []
    finally:
        if owns:
            await client.aclose()


async def pull_ollama_model(
    model: str,
    base_url: str = "http://127.0.0.1:11434",
) -> AsyncIterator[str]:
    """Stream pull progress for ``model`` via Ollama /api/pull.
    Yields status strings (e.g. "pulling manifest", "downloading …")."""
    import json
    async with httpx.AsyncClient(timeout=600.0) as client:
        async with client.stream(
            "POST", f"{base_url}/api/pull", json={"name": model, "stream": True}
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                status = data.get("status", "")
                total = data.get("total", 0)
                completed = data.get("completed", 0)
                if total and completed:
                    pct = int(completed / total * 100)
                    yield f"{status} {pct}%"
                else:
                    yield status
                if data.get("status") == "success":
                    break
