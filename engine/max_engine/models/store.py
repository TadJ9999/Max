"""SQLite store for benchmark results.

Table: model_benchmarks
  model TEXT PK, ttft_ms REAL, tokens_per_sec REAL, ran_at REAL
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


class BenchmarkStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_benchmarks (
                    model        TEXT PRIMARY KEY,
                    ttft_ms      REAL,
                    tokens_per_sec REAL,
                    prompt_tokens  INTEGER,
                    total_tokens   INTEGER,
                    ran_at       REAL
                )
                """
            )
            # Latency-probe columns (added later) — migrate existing DBs in place.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(model_benchmarks)")}
            for col in ("lat_ttft_ms", "lat_total_ms", "lat_ran_at"):
                if col not in cols:
                    conn.execute(f"ALTER TABLE model_benchmarks ADD COLUMN {col} REAL")

    def upsert(
        self,
        model: str,
        ttft_ms: float,
        tokens_per_sec: float,
        prompt_tokens: int = 0,
        total_tokens: int = 0,
    ) -> dict:
        ran_at = time.time()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO model_benchmarks
                    (model, ttft_ms, tokens_per_sec, prompt_tokens, total_tokens, ran_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(model) DO UPDATE SET
                    ttft_ms        = excluded.ttft_ms,
                    tokens_per_sec = excluded.tokens_per_sec,
                    prompt_tokens  = excluded.prompt_tokens,
                    total_tokens   = excluded.total_tokens,
                    ran_at         = excluded.ran_at
                """,
                (model, ttft_ms, tokens_per_sec, prompt_tokens, total_tokens, ran_at),
            )
        return self.get(model) or {}

    def upsert_latency(self, model: str, ttft_ms: float, total_ms: float) -> dict:
        """Record a latency-probe result without clobbering benchmark throughput
        fields (and vice-versa: the two probes update disjoint columns)."""
        ran_at = time.time()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO model_benchmarks (model, lat_ttft_ms, lat_total_ms, lat_ran_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(model) DO UPDATE SET
                    lat_ttft_ms  = excluded.lat_ttft_ms,
                    lat_total_ms = excluded.lat_total_ms,
                    lat_ran_at   = excluded.lat_ran_at
                """,
                (model, ttft_ms, total_ms, ran_at),
            )
        return self.get(model) or {}

    def get(self, model: str) -> dict | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM model_benchmarks WHERE model = ?", (model,)
            ).fetchone()
        return dict(row) if row else None

    def all(self) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM model_benchmarks ORDER BY ran_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
