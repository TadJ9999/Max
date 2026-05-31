"""Prediction history store — saves one Apollo prediction per day, keeps 30 days.

Backed by a plain SQLite table in .apollo.db alongside the vector memory.
Used to give the Apollo chat endpoint recent prediction context.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


_DDL = """
CREATE TABLE IF NOT EXISTS prediction_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_date ON prediction_history(date);
"""

_TTL_SECONDS = 30 * 86_400  # 30 days


class PredictionHistory:
    """One prediction per day, 30-day rolling window."""

    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.executescript(_DDL)
                conn.commit()

    def save(self, text: str) -> None:
        """Upsert today's prediction and purge entries older than 30 days."""
        now = int(time.time())
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cutoff = now - _TTL_SECONDS
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM prediction_history WHERE created_at < ?", (cutoff,))
                conn.execute(
                    """INSERT INTO prediction_history (date, text, created_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(date) DO UPDATE SET
                           text       = excluded.text,
                           created_at = excluded.created_at""",
                    (date, text, now),
                )
                conn.commit()

    def get_recent(self, limit: int = 5) -> list[dict]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT date, text, created_at FROM prediction_history ORDER BY date DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def to_context_block(self) -> str:
        rows = self.get_recent(3)
        if not rows:
            return ""
        lines = ["Recent Apollo predictions (most recent first):"]
        for r in rows:
            preview = r["text"][:600] + ("…" if len(r["text"]) > 600 else "")
            lines.append(f"\n[{r['date']}]\n{preview}")
        return "\n".join(lines)
