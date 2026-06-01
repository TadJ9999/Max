"""Hindsight matching — the "we called this right / this didn't pan out" panel.

When a new report is generated we surface previously graded claims related to it,
matched two ways and unioned:

  * **entity tag** — graded claims sharing the report's entity (ticker / ISO);
  * **vector similarity** — nearest graded *lessons* in the Apollo vector store
    (``kind="lesson"``), embedded at grade time.

Results are de-duplicated by claim, split into "called right" (hit/partial) and
"didn't pan out" (miss) buckets, and returned newest-first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


def _item_from_claim(claim: dict) -> dict | None:
    g = claim.get("latestGrade") or (claim.get("grades") or [None])[-1]
    if not g or g.get("outcome") == "too-early":
        return None
    return {
        "claimId": claim["id"],
        "claim": claim["claim"],
        "entity": claim.get("entity"),
        "feature": claim.get("feature"),
        "outcome": g["outcome"],
        "score": g["score"],
        "checkpoint": g["checkpoint"],
        "failureTag": g.get("failureTag"),
        "reason": g.get("reason"),
        "match": "entity",
    }


def _item_from_lesson(hit: dict) -> dict | None:
    meta = hit.get("meta") or {}
    if not meta.get("claimId"):
        return None
    return {
        "claimId": meta.get("claimId"),
        "claim": meta.get("claim") or hit.get("title"),
        "entity": meta.get("entity"),
        "feature": meta.get("feature"),
        "outcome": meta.get("outcome"),
        "score": meta.get("score"),
        "checkpoint": meta.get("checkpoint"),
        "failureTag": meta.get("failureTag"),
        "reason": meta.get("reason") or hit.get("body"),
        "match": "vector",
        "distance": hit.get("distance"),
    }


async def related(
    *,
    store,
    vector,
    embed_fn: EmbedFn,
    feature: str | None,
    entity: str | None,
    query: str | None,
    k: int = 6,
) -> dict:
    """Return ``{"right": [...], "missed": [...]}`` of graded claims related to a
    new report. Best-effort: vector arm is skipped if embedding/store unavailable."""
    items: dict[int, dict] = {}

    # 1) Entity-tag arm.
    if entity:
        for c in store.claims_by_entity(entity, only_graded=True, limit=k):
            it = _item_from_claim(c)
            if it:
                items.setdefault(it["claimId"], it)

    # 2) Vector arm over graded lessons.
    if vector is not None and query and query.strip():
        try:
            embs = await embed_fn([query[:1000]])
        except Exception:
            embs = []
        if embs:
            import asyncio
            hits = await asyncio.to_thread(vector.search, embs[0], k=k * 2, kind="lesson")
            for h in hits:
                it = _item_from_lesson(h)
                if it and it["claimId"] not in items:
                    items.setdefault(it["claimId"], it)

    right, missed = [], []
    for it in items.values():
        if it.get("outcome") in {"hit", "partial"}:
            right.append(it)
        elif it.get("outcome") == "miss":
            missed.append(it)
    right.sort(key=lambda d: (d.get("score") or 0), reverse=True)
    missed.sort(key=lambda d: (d.get("score") or 0))
    return {"right": right[:k], "missed": missed[:k]}
