from __future__ import annotations

import httpx

from .models import Launch

# TheSpaceDevs Launch Library 2 — free, no key. Use the dev mirror (lighter
# rate limits) and fall back to the main host.
LL2_HOSTS = [
    "https://lldev.thespacedevs.com/2.2.0/launch/upcoming/",
    "https://ll.thespacedevs.com/2.2.0/launch/upcoming/",
]


async def fetch_launches(*, limit: int = 6, timeout: float = 20.0) -> list[Launch]:
    out: list[Launch] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        last_err: Exception | None = None
        for host in LL2_HOSTS:
            try:
                r = await client.get(host, params={"limit": limit, "mode": "list"})
                r.raise_for_status()
                results = r.json().get("results", [])
                for o in results:
                    prov = o.get("launch_service_provider") or {}
                    pad = o.get("pad") or {}
                    loc = pad.get("location") or {}
                    status = o.get("status") or {}
                    image = o.get("image")
                    out.append(
                        Launch(
                            id=str(o.get("id", "")),
                            name=str(o.get("name", "")),
                            provider=str(prov.get("name", "")),
                            vehicle=str((o.get("rocket") or {}).get("configuration", {}).get("name", "")) if o.get("rocket") else "",
                            pad=str(pad.get("name", "")),
                            location=str(loc.get("name", "")),
                            net=str(o.get("net", "")),
                            status=str(status.get("abbrev") or status.get("name") or ""),
                            image=str(image) if image else "",
                            webcast="",
                        )
                    )
                return out
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        if last_err:
            raise last_err
    return out
