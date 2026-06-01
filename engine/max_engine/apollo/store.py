"""Apollo vector memory — a local sqlite-vec store, the app-level knowledge base.

A single ``vec0`` virtual table holds embedded news, market snapshots, and prior
reports. Everything is local (one ``.apollo.db`` file); nothing leaves the
machine. The store is the engine's memory: ingest writes to it, every AI chat
recalls from it by question, and anything older than the TTL (default 30 days) is
purged each cycle.

Synchronous SQLite under a lock (the connection is shared with
``check_same_thread=False``); callers run these from a thread via
``asyncio.to_thread`` so the event loop never blocks.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

import sqlite_vec

from .embed import EMBED_DIM


class VectorStore:
    def __init__(self, path: str, *, dim: int = EMBED_DIM):
        self.path = str(path)
        self.dim = dim
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # ---- connection / schema -------------------------------------------

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            f"""CREATE VIRTUAL TABLE IF NOT EXISTS memories USING vec0(
                embedding float[{self.dim}],
                kind text,
                ref text,
                ts integer,
                +title text,
                +body text,
                +meta text
            )"""
        )
        self._conn = conn
        return conn

    # ---- writes ---------------------------------------------------------

    def upsert(self, items: list[dict]) -> int:
        """Insert embedded memories, replacing any existing row with the same
        ``ref`` (dedupe). ``items``: dicts with kind, ref, ts, title, body, meta,
        embedding. Returns how many rows were written."""
        written = 0
        with self._lock:
            c = self._ensure()
            for it in items:
                emb = it.get("embedding")
                ref = it.get("ref")
                if not emb or not ref:
                    continue
                c.execute("DELETE FROM memories WHERE ref = ?", (ref,))
                c.execute(
                    "INSERT INTO memories(embedding, kind, ref, ts, title, body, meta) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sqlite_vec.serialize_float32(emb),
                        it.get("kind", ""),
                        ref,
                        int(it.get("ts", time.time())),
                        it.get("title", ""),
                        it.get("body", ""),
                        json.dumps(it.get("meta", {})),
                    ),
                )
                written += 1
            c.commit()
        return written

    def purge_older_than(self, seconds: int = 86_400) -> int:
        """Delete memories older than ``seconds`` (the TTL). Returns rows removed."""
        cutoff = int(time.time()) - seconds
        with self._lock:
            c = self._ensure()
            cur = c.execute("DELETE FROM memories WHERE ts < ?", (cutoff,))
            c.commit()
            return cur.rowcount

    # ---- reads ----------------------------------------------------------

    def search(self, embedding: list[float], *, k: int = 6, kind: str | None = None) -> list[dict]:
        """K-nearest memories to ``embedding`` (optionally filtered to one kind),
        nearest first."""
        if not embedding:
            return []
        sql = (
            "SELECT kind, ref, ts, title, body, meta, distance FROM memories "
            "WHERE embedding MATCH ? AND k = ?"
        )
        params: list = [sqlite_vec.serialize_float32(embedding), k]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY distance"
        with self._lock:
            c = self._ensure()
            rows = c.execute(sql, params).fetchall()
        return [
            {
                "kind": r[0],
                "ref": r[1],
                "ts": r[2],
                "title": r[3],
                "body": r[4],
                "meta": json.loads(r[5] or "{}"),
                "distance": round(r[6], 4),
            }
            for r in rows
        ]

    def stats(self) -> dict:
        with self._lock:
            c = self._ensure()
            total = c.execute("SELECT count(*) FROM memories").fetchone()[0]
            by_kind = dict(
                c.execute("SELECT kind, count(*) FROM memories GROUP BY kind").fetchall()
            )
            oldest = c.execute("SELECT min(ts) FROM memories").fetchone()[0]
            newest = c.execute("SELECT max(ts) FROM memories").fetchone()[0]
        return {"total": total, "byKind": by_kind, "oldest": oldest, "newest": newest}
