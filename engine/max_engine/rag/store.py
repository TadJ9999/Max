"""Codebase RAG vector store — local sqlite-vec, one row per code chunk.

Separate from Apollo's memory store: this holds embedded *code/text chunks* for
retrieval-augmented answers about the user's workspace. Everything is local (one
``.maxrag.db`` file); nothing leaves the machine.

Incremental indexing keys on a per-file content hash: a file is re-chunked only
when its hash changes, and its old chunks are replaced atomically.
"""

from __future__ import annotations

import sqlite3
import threading

import sqlite_vec

from ..apollo.embed import EMBED_DIM


class RagStore:
    def __init__(self, path: str, *, dim: int = EMBED_DIM):
        self.path = str(path)
        self.dim = dim
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            f"""CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING vec0(
                embedding float[{self.dim}],
                path text,
                idx integer,
                start_line integer,
                end_line integer,
                +text text
            )"""
        )
        # Side table tracks the indexed hash per file (for incremental re-index).
        conn.execute(
            "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT NOT NULL)"
        )
        self._conn = conn
        return conn

    # ---- writes ---------------------------------------------------------

    def replace_file(self, path: str, file_hash: str, chunks: list[dict]) -> int:
        """Replace all chunks for ``path`` with ``chunks`` (each: embedding, idx,
        start_line, end_line, text) and record its hash. Returns chunks written."""
        with self._lock:
            c = self._ensure()
            c.execute("DELETE FROM chunks WHERE path = ?", (path,))
            written = 0
            for ch in chunks:
                emb = ch.get("embedding")
                if not emb:
                    continue
                c.execute(
                    "INSERT INTO chunks(embedding, path, idx, start_line, end_line, text) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        sqlite_vec.serialize_float32(emb),
                        path,
                        int(ch.get("idx", 0)),
                        int(ch.get("start_line", 0)),
                        int(ch.get("end_line", 0)),
                        ch.get("text", ""),
                    ),
                )
                written += 1
            c.execute(
                "INSERT INTO files(path, hash) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET hash = excluded.hash",
                (path, file_hash),
            )
            c.commit()
            return written

    def delete_file(self, path: str) -> None:
        with self._lock:
            c = self._ensure()
            c.execute("DELETE FROM chunks WHERE path = ?", (path,))
            c.execute("DELETE FROM files WHERE path = ?", (path,))
            c.commit()

    def clear(self) -> None:
        with self._lock:
            c = self._ensure()
            c.execute("DELETE FROM chunks")
            c.execute("DELETE FROM files")
            c.commit()

    # ---- reads ----------------------------------------------------------

    def file_hashes(self) -> dict[str, str]:
        """Currently indexed files -> their stored content hash."""
        with self._lock:
            c = self._ensure()
            return dict(c.execute("SELECT path, hash FROM files").fetchall())

    def search(self, embedding: list[float], *, k: int = 6) -> list[dict]:
        """K-nearest code chunks to ``embedding``, nearest first."""
        if not embedding:
            return []
        with self._lock:
            c = self._ensure()
            rows = c.execute(
                "SELECT path, idx, start_line, end_line, text, distance FROM chunks "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (sqlite_vec.serialize_float32(embedding), k),
            ).fetchall()
        return [
            {
                "path": r[0],
                "idx": r[1],
                "start_line": r[2],
                "end_line": r[3],
                "text": r[4],
                "distance": round(r[5], 4),
            }
            for r in rows
        ]

    def stats(self) -> dict:
        with self._lock:
            c = self._ensure()
            files = c.execute("SELECT count(*) FROM files").fetchone()[0]
            chunks = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
        return {"files": files, "chunks": chunks}
