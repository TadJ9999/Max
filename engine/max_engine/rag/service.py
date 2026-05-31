"""RagService — index a workspace and retrieve context for grounded answers.

Ties the chunker + embedder + store together:

* **index(roots)** — walk the allowlisted roots, hash each file, (re)chunk and
  embed only changed files (incremental), and drop chunks for deleted files.
* **search(query)** — embed the query and return the nearest code chunks.
* **context_for(query)** — format those chunks into a prompt-ready context block.

Embedding is injectable (``embed_fn``) so tests run without Ollama. All embedding
work is best-effort: if embeddings are unavailable the service degrades to a
no-op rather than failing a request.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from ..apollo.embed import DEFAULT_EMBED_MODEL, embed_texts
from .chunker import chunk_text as _chunk_text
from .chunker import file_hash, gather_files, read_text
from .store import RagStore

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


class RagService:
    def __init__(
        self,
        store: RagStore,
        *,
        embed_fn: EmbedFn | None = None,
        embed_model: str = DEFAULT_EMBED_MODEL,
        base_url: str = "http://127.0.0.1:11434",
        max_chars: int = 1200,
        overlap_lines: int = 8,
    ) -> None:
        self.store = store
        self._embed_model = embed_model
        self._base_url = base_url
        self.max_chars = max_chars
        self.overlap_lines = overlap_lines
        self._embed_fn: EmbedFn = embed_fn or self._default_embed

    async def _default_embed(self, texts: list[str]) -> list[list[float]]:
        return await embed_texts(texts, model=self._embed_model, base_url=self._base_url)

    # ---- indexing -------------------------------------------------------

    async def index(self, roots: list[str]) -> dict:
        """(Re)index the given roots incrementally. Returns a summary."""
        if not roots:
            return {"indexed": 0, "skipped": 0, "removed": 0, "chunks": 0, "files": 0}

        present = set(gather_files(roots))
        known = self.store.file_hashes()

        # Drop files that vanished from the workspace.
        removed = 0
        for path in list(known):
            if path not in present:
                self.store.delete_file(path)
                removed += 1

        indexed = skipped = chunks_written = 0
        for path in present:
            text = read_text(path)
            if text is None:
                continue
            h = file_hash(text)
            if known.get(path) == h:
                skipped += 1
                continue
            chunks = _chunk_text(
                text, max_chars=self.max_chars, overlap_lines=self.overlap_lines
            )
            if not chunks:
                self.store.replace_file(path, h, [])
                indexed += 1
                continue
            embeddings = await self._embed_fn([c.text for c in chunks])
            if len(embeddings) != len(chunks):
                continue  # embedding unavailable -> leave this file for next run
            rows = [
                {
                    "embedding": embeddings[i],
                    "idx": i,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "text": c.text,
                }
                for i, c in enumerate(chunks)
            ]
            chunks_written += self.store.replace_file(path, h, rows)
            indexed += 1

        return {
            "indexed": indexed,
            "skipped": skipped,
            "removed": removed,
            "chunks": chunks_written,
            "files": self.store.stats()["files"],
        }

    # ---- retrieval ------------------------------------------------------

    async def search(self, query: str, *, k: int = 6) -> list[dict]:
        if not query.strip():
            return []
        embs = await self._embed_fn([query])
        if not embs:
            return []
        return self.store.search(embs[0], k=k)

    async def context_for(self, query: str, *, k: int = 6) -> str:
        """A prompt-ready context block from the top matches (empty if none)."""
        hits = await self.search(query, k=k)
        return format_context(hits)

    def status(self) -> dict:
        return self.store.stats()


def format_context(hits: list[dict]) -> str:
    """Render retrieved chunks as a fenced, cited context block for a prompt."""
    if not hits:
        return ""
    blocks = []
    for h in hits:
        loc = f"{os.path.basename(h['path'])}:{h['start_line']}-{h['end_line']}"
        blocks.append(f"// {loc}\n{h['text']}")
    return "\n\n".join(blocks)
