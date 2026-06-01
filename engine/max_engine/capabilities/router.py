"""Intent router — classifies a free-form message into a skill domain."""

from __future__ import annotations

from .registry import CapabilityRegistry
from ..prompts import SYSTEM_PROMPTS

_VALID_DOMAINS = {
    "web_search", "report", "spotify", "calendar", "files", "code", "chat",
}


async def classify_intent(message: str, provider, model: str) -> str:
    """Call the resident model to classify message → domain string."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS["intent_router"]},
        {"role": "user", "content": message},
    ]
    result = ""
    try:
        async for chunk in provider.chat(
            model,
            messages,
            num_predict=10,
            temperature=0,
            _feature="skills",
        ):
            if not chunk.done:
                result += chunk.text
    except Exception:
        return "chat"
    domain = result.strip().lower().split()[0] if result.strip() else "chat"
    # normalise exact or prefix match (e.g. "web" → "web_search")
    for valid in _VALID_DOMAINS:
        if domain == valid or valid.startswith(domain):
            return valid
    return "chat"


async def route_and_invoke(message: str, provider, model: str):
    """Classify message → find capability → stream the response."""
    domain = await classify_intent(message, provider, model)
    registry = CapabilityRegistry.get()
    cap = registry.find_for_domain(domain)

    if cap is None or domain in ("code", "chat"):
        # No skill handles code/chat — let the caller fall back to normal chat
        yield f"[route:{domain}]"
        return

    yield f"[route:{domain}]"
    async for chunk in cap.invoke(message):
        yield chunk
