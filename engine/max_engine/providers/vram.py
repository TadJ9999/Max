"""VRAM-aware model lifecycle manager.

Polls Ollama /api/ps to see which models are currently loaded in VRAM.
Before loading a heavy model, evict non-resident loaded models if the
VRAM budget (config.idle.vram_budget_mb) would otherwise be exceeded.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class LoadedModel:
    name: str
    size_vram: int  # bytes reported by Ollama


class VramManager:
    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url.rstrip("/")

    async def get_loaded(self, client: httpx.AsyncClient | None = None) -> list[LoadedModel]:
        """Fetch currently loaded models from Ollama /api/ps."""
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=5.0)
        try:
            resp = await client.get(f"{self.base_url}/api/ps")
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [
                LoadedModel(name=m.get("name", ""), size_vram=m.get("size_vram", 0))
                for m in data.get("models", [])
            ]
        except (httpx.HTTPError, ValueError):
            return []
        finally:
            if owns_client:
                await client.aclose()

    async def evict_to_fit(
        self,
        new_model_size_mb: int,
        budget_mb: int,
        *,
        keep: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> list[str]:
        """Evict loaded models (largest first) until the new model fits.

        ``keep`` is the resident model name — never evicted.
        Returns names of models that were evicted.
        """
        loaded = await self.get_loaded(client)
        budget_bytes = budget_mb * 1024 * 1024
        needed_bytes = new_model_size_mb * 1024 * 1024
        used_bytes = sum(m.size_vram for m in loaded)

        if used_bytes + needed_bytes <= budget_bytes:
            return []

        evicted: list[str] = []
        candidates = sorted(
            (m for m in loaded if m.name != keep),
            key=lambda m: m.size_vram,
            reverse=True,
        )

        owns_client = client is None
        http_client = client or httpx.AsyncClient(timeout=10.0)
        try:
            for model in candidates:
                if used_bytes + needed_bytes <= budget_bytes:
                    break
                resp = await http_client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model.name, "keep_alive": 0},
                )
                if resp.status_code < 400:
                    evicted.append(model.name)
                    used_bytes -= model.size_vram
        except httpx.HTTPError:
            pass
        finally:
            if owns_client:
                await http_client.aclose()

        return evicted
