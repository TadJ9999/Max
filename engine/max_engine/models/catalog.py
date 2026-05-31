"""Static cloud model catalog + VRAM estimates for common local models.

Cloud models show cost (USD per 1M tokens input/output), context window, and a
cost multiplier relative to Claude Haiku at $0.80/1M input = 1×.
"""

from __future__ import annotations

# ── Cloud model catalog ────────────────────────────────────────────────────────

CLOUD_MODELS: list[dict] = [
    # ── Anthropic ────────────────────────────────────────────────────────────
    {
        "id": "claude-haiku-4-5-20251001",
        "display_name": "Claude Haiku 4.5",
        "provider": "anthropic",
        "provider_label": "Anthropic",
        "kind": "cloud",
        "context_k": 200,
        "input_cost_per_1m": 0.80,
        "output_cost_per_1m": 4.00,
        "cost_multiplier": 1.0,
        "strengths": ["fast", "cheap", "summarize", "classify"],
        "env_key": "ANTHROPIC_API_KEY",
        "status": "available",
    },
    {
        "id": "claude-sonnet-4-6",
        "display_name": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "provider_label": "Anthropic",
        "kind": "cloud",
        "context_k": 200,
        "input_cost_per_1m": 3.00,
        "output_cost_per_1m": 15.00,
        "cost_multiplier": 5.0,
        "strengths": ["coding", "reasoning", "analysis", "balanced"],
        "env_key": "ANTHROPIC_API_KEY",
        "status": "available",
    },
    {
        "id": "claude-opus-4-8",
        "display_name": "Claude Opus 4.8",
        "provider": "anthropic",
        "provider_label": "Anthropic",
        "kind": "cloud",
        "context_k": 200,
        "input_cost_per_1m": 15.00,
        "output_cost_per_1m": 75.00,
        "cost_multiplier": 25.0,
        "strengths": ["complex reasoning", "research", "long context", "best quality"],
        "env_key": "ANTHROPIC_API_KEY",
        "status": "available",
    },
    # ── OpenAI ───────────────────────────────────────────────────────────────
    {
        "id": "gpt-4o-mini",
        "display_name": "GPT-4o mini",
        "provider": "openai",
        "provider_label": "OpenAI",
        "kind": "cloud",
        "context_k": 128,
        "input_cost_per_1m": 0.15,
        "output_cost_per_1m": 0.60,
        "cost_multiplier": 0.3,
        "strengths": ["fast", "cheap", "simple tasks"],
        "env_key": "OPENAI_API_KEY",
        "status": "coming_soon",
    },
    {
        "id": "gpt-4o",
        "display_name": "GPT-4o",
        "provider": "openai",
        "provider_label": "OpenAI",
        "kind": "cloud",
        "context_k": 128,
        "input_cost_per_1m": 2.50,
        "output_cost_per_1m": 10.00,
        "cost_multiplier": 4.0,
        "strengths": ["coding", "vision", "reasoning", "multimodal"],
        "env_key": "OPENAI_API_KEY",
        "status": "coming_soon",
    },
    {
        "id": "o3-mini",
        "display_name": "o3-mini",
        "provider": "openai",
        "provider_label": "OpenAI",
        "kind": "cloud",
        "context_k": 200,
        "input_cost_per_1m": 1.10,
        "output_cost_per_1m": 4.40,
        "cost_multiplier": 2.0,
        "strengths": ["math", "coding", "STEM", "reasoning"],
        "env_key": "OPENAI_API_KEY",
        "status": "coming_soon",
    },
    # ── Google ───────────────────────────────────────────────────────────────
    {
        "id": "gemini-2.0-flash",
        "display_name": "Gemini 2.0 Flash",
        "provider": "google",
        "provider_label": "Google",
        "kind": "cloud",
        "context_k": 1000,
        "input_cost_per_1m": 0.10,
        "output_cost_per_1m": 0.40,
        "cost_multiplier": 0.4,
        "strengths": ["fast", "1M context", "multimodal", "cheap"],
        "env_key": "GOOGLE_API_KEY",
        "status": "coming_soon",
    },
    {
        "id": "gemini-1.5-pro",
        "display_name": "Gemini 1.5 Pro",
        "provider": "google",
        "provider_label": "Google",
        "kind": "cloud",
        "context_k": 1000,
        "input_cost_per_1m": 1.25,
        "output_cost_per_1m": 5.00,
        "cost_multiplier": 2.0,
        "strengths": ["1M context", "long documents", "multimodal", "research"],
        "env_key": "GOOGLE_API_KEY",
        "status": "coming_soon",
    },
]

# ── Local VRAM estimates ───────────────────────────────────────────────────────
# keyed by the beginning of the model tag (case-insensitive prefix match)

VRAM_ESTIMATES: list[tuple[str, int]] = [
    ("qwen2.5-coder:1.5b", 1_200),
    ("qwen2.5-coder:3b",   2_100),
    ("qwen2.5-coder:7b",   4_600),
    ("qwen2.5-coder:14b",  9_200),
    ("qwen2.5-coder:32b",  20_000),
    ("qwen2.5:3b",         2_100),
    ("qwen2.5:7b",         4_600),
    ("qwen2.5:14b",        9_200),
    ("qwen2.5:32b",        20_000),
    ("llama3.1:8b",        5_100),
    ("llama3.1:70b",       40_000),
    ("llama3.2:3b",        2_200),
    ("mistral:7b",         4_400),
    ("mistral-nemo",       7_800),
    ("deepseek-coder-v2:16b", 10_200),
    ("deepseek-coder-v2:236b", 130_000),
    ("nomic-embed-text",   600),
    ("bge-small",          300),
    ("starcoder2:3b",      2_000),
    ("starcoder2:7b",      4_500),
    ("phi4",               8_200),
    ("phi3.5",             4_200),
    ("gemma2:2b",          1_700),
    ("gemma2:9b",          6_000),
    ("gemma2:27b",         17_000),
]


def vram_mb(tag: str) -> int | None:
    """Best-effort VRAM estimate in MB for a local model tag."""
    tag_lower = tag.lower()
    for prefix, mb in VRAM_ESTIMATES:
        if tag_lower.startswith(prefix.lower()):
            return mb
    # Fallback: parse param count from tag (e.g. "mymodel:8b" → ~5 GB)
    import re
    m = re.search(r":(\d+)b", tag_lower)
    if m:
        params_b = int(m.group(1))
        return int(params_b * 650)  # rough estimate: ~650 MB per B params at Q4
    return None
