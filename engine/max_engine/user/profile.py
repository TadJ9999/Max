"""Persistent user-profile store — what Max knows about the person it's talking to.

Backed by a plain SQLite table (no TTL) inside .apollo.db alongside the vector
memory. Facts survive restarts and are injected into every AI system prompt so
Max can personalise responses without the user having to repeat themselves.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from threading import Lock


_DDL = """
CREATE TABLE IF NOT EXISTS user_profile (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'fact',
    source     TEXT NOT NULL DEFAULT 'explicit',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
"""

_VALID_KINDS = {"fact", "preference", "interest", "style"}


class UserProfileStore:
    """Thread-safe key-value store for persistent user facts."""

    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._lock = Lock()
        self._init_db()

    # ── private ───────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(_DDL)
                conn.commit()

    # ── public API ────────────────────────────────────────────────────────

    def upsert(
        self,
        key: str,
        value: str,
        kind: str = "fact",
        source: str = "explicit",
    ) -> dict:
        if kind not in _VALID_KINDS:
            kind = "fact"
        now = int(time.time())
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO user_profile (key, value, kind, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                           value      = excluded.value,
                           kind       = excluded.kind,
                           source     = excluded.source,
                           updated_at = excluded.updated_at""",
                    (key, value, kind, source, now, now),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM user_profile WHERE key = ?", (key,)
                ).fetchone()
        return dict(row)

    def get_all(self) -> list[dict]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM user_profile ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, key: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM user_profile WHERE key = ?", (key,))
                conn.commit()
        return cur.rowcount > 0

    def to_context_block(self) -> str:
        """Format all profile entries as a system-prompt context block."""
        rows = self.get_all()
        if not rows:
            return ""
        lines = ["About the user:"]
        for r in rows:
            lines.append(f"- {r['key']}: {r['value']}")
        return "\n".join(lines)
