"""RagService tests — incremental indexing + retrieval over a real sqlite-vec DB."""

import asyncio
import math
import re

from max_engine.rag.service import RagService
from max_engine.rag.store import RagStore

DIM = 64


def _bow_embed(dim: int = DIM):
    """Deterministic bag-of-words embedder: cosine-near for shared tokens.
    Splits identifiers on non-alphanumerics (so `parse_iso_date` -> parse/iso/date)
    so a natural-language query lands nearest the chunk that contains its words."""

    async def embed(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * dim
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                v[sum(ord(ch) for ch in tok) % dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out

    return embed


def _service(tmp_path) -> RagService:
    store = RagStore(str(tmp_path / "rag.db"), dim=DIM)
    return RagService(store, embed_fn=_bow_embed())


def _workspace(tmp_path):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "dates.py").write_text(
        "def parse_iso_date(s):\n    return datetime.fromisoformat(s)\n"
    )
    (tmp_path / "ws" / "math_utils.py").write_text(
        "def fibonacci(n):\n    return n if n < 2 else fibonacci(n-1)+fibonacci(n-2)\n"
    )
    return str(tmp_path / "ws")


def test_index_then_search_finds_relevant_file(tmp_path):
    svc = _service(tmp_path)
    ws = _workspace(tmp_path)

    summary = asyncio.run(svc.index([ws]))
    assert summary["indexed"] == 2
    assert summary["chunks"] >= 2
    assert summary["files"] == 2

    hits = asyncio.run(svc.search("parse iso date", k=3))
    assert hits
    assert hits[0]["path"].endswith("dates.py")  # nearest match is the right file


def test_incremental_skips_unchanged_reindexes_changed_and_drops_deleted(tmp_path):
    svc = _service(tmp_path)
    ws = _workspace(tmp_path)
    asyncio.run(svc.index([ws]))

    # 1) nothing changed -> all skipped, nothing re-indexed
    again = asyncio.run(svc.index([ws]))
    assert again["indexed"] == 0
    assert again["skipped"] == 2

    # 2) modify one file -> exactly one re-indexed
    (tmp_path / "ws" / "dates.py").write_text("def parse_iso_date(s):\n    return None\n")
    changed = asyncio.run(svc.index([ws]))
    assert changed["indexed"] == 1
    assert changed["skipped"] == 1

    # 3) delete one file -> removed from the index
    (tmp_path / "ws" / "math_utils.py").unlink()
    after = asyncio.run(svc.index([ws]))
    assert after["removed"] == 1
    assert svc.status()["files"] == 1


def test_index_empty_roots_is_noop(tmp_path):
    svc = _service(tmp_path)
    assert asyncio.run(svc.index([]))["indexed"] == 0


def test_context_for_formats_citations(tmp_path):
    svc = _service(tmp_path)
    ws = _workspace(tmp_path)
    asyncio.run(svc.index([ws]))
    ctx = asyncio.run(svc.context_for("fibonacci", k=2))
    assert "math_utils.py:" in ctx  # cited by file:line


def test_search_empty_query_returns_nothing(tmp_path):
    svc = _service(tmp_path)
    assert asyncio.run(svc.search("  ")) == []
