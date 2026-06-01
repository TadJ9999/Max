"""Analytics store — persists per-call token usage into the shared .apollo.db.

Table owned by this module:
  token_usage — one row per completed AI call (chat_done / Ollama done)

Cost is calculated at write-time from the static cloud catalog so historical
rows remain valid even if catalog prices change later.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

from ..models.catalog import CLOUD_MODELS

# ── Cost lookup ────────────────────────────────────────────────────────────────

_COST_MAP: dict[tuple[str, str], tuple[float, float]] = {
    (m["provider"], m["id"]): (m["input_cost_per_1m"], m["output_cost_per_1m"])
    for m in CLOUD_MODELS
}


def calc_cost(provider: str, model: str, in_tokens: int, out_tokens: int) -> float:
    """Return estimated USD cost for a single call. Returns 0.0 for local models
    or unknown model IDs."""
    rates = _COST_MAP.get((provider, model))
    if not rates:
        return 0.0
    return (in_tokens * rates[0] + out_tokens * rates[1]) / 1_000_000


# ── Store ──────────────────────────────────────────────────────────────────────

class UsageStore:
    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # ── connection / schema ──────────────────────────────────────────────────

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         INTEGER NOT NULL,
                day        TEXT NOT NULL,
                feature    TEXT NOT NULL,
                provider   TEXT NOT NULL,
                model      TEXT NOT NULL,
                in_tokens  INTEGER NOT NULL DEFAULT 0,
                out_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd   REAL NOT NULL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS tu_day     ON token_usage(day);
            CREATE INDEX IF NOT EXISTS tu_feature ON token_usage(feature);
        """)
        conn.commit()
        self._conn = conn
        return conn

    # ── writes ────────────────────────────────────────────────────────────────

    def record(
        self,
        ts: int,
        day: str,
        feature: str,
        provider: str,
        model: str,
        in_tokens: int,
        out_tokens: int,
        cost_usd: float,
    ) -> None:
        with self._lock:
            conn = self._ensure()
            conn.execute(
                """INSERT INTO token_usage
                   (ts, day, feature, provider, model, in_tokens, out_tokens, cost_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, day, feature, provider, model, in_tokens, out_tokens, cost_usd),
            )
            conn.commit()

    # ── reads ─────────────────────────────────────────────────────────────────

    def summary(self, days: int) -> dict[str, Any]:
        with self._lock:
            conn = self._ensure()
            row = conn.execute(
                """SELECT
                       COALESCE(SUM(in_tokens), 0)  AS total_in,
                       COALESCE(SUM(out_tokens), 0) AS total_out,
                       COALESCE(SUM(cost_usd), 0.0) AS total_cost,
                       COUNT(*)                     AS requests
                   FROM token_usage
                   WHERE day >= date('now', ? || ' days')""",
                (f"-{days}",),
            ).fetchone()

            top_feature_row = conn.execute(
                """SELECT feature, COUNT(*) AS cnt
                   FROM token_usage
                   WHERE day >= date('now', ? || ' days')
                   GROUP BY feature ORDER BY cnt DESC LIMIT 1""",
                (f"-{days}",),
            ).fetchone()

            top_model_row = conn.execute(
                """SELECT model, COUNT(*) AS cnt
                   FROM token_usage
                   WHERE day >= date('now', ? || ' days')
                   GROUP BY model ORDER BY cnt DESC LIMIT 1""",
                (f"-{days}",),
            ).fetchone()

        total_in = int(row["total_in"])
        total_out = int(row["total_out"])
        return {
            "days": days,
            "total_in_tokens": total_in,
            "total_out_tokens": total_out,
            "total_tokens": total_in + total_out,
            "total_cost_usd": round(float(row["total_cost"]), 6),
            "requests": int(row["requests"]),
            "top_feature": top_feature_row["feature"] if top_feature_row else "",
            "top_model": top_model_row["model"] if top_model_row else "",
        }

    def daily(self, days: int) -> list[dict[str, Any]]:
        """Return one row per (day, feature) within the window, for the stacked
        bar chart. The frontend pivots feature rows into a by_feature dict."""
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                """SELECT day, feature,
                          SUM(in_tokens + out_tokens) AS total_tokens,
                          SUM(cost_usd)               AS total_cost
                   FROM token_usage
                   WHERE day >= date('now', ? || ' days')
                   GROUP BY day, feature
                   ORDER BY day ASC""",
                (f"-{days}",),
            ).fetchall()

        # Pivot: day → {feature: tokens, cost: ...}
        pivot: dict[str, dict[str, Any]] = {}
        for r in rows:
            d = r["day"]
            if d not in pivot:
                pivot[d] = {"day": d, "total_tokens": 0, "total_cost_usd": 0.0, "by_feature": {}}
            pivot[d]["by_feature"][r["feature"]] = int(r["total_tokens"])
            pivot[d]["total_tokens"] += int(r["total_tokens"])
            pivot[d]["total_cost_usd"] += float(r["total_cost"] or 0)

        for entry in pivot.values():
            entry["total_cost_usd"] = round(entry["total_cost_usd"], 6)

        return list(pivot.values())

    def breakdown(self, days: int) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                """SELECT feature, model, provider,
                          SUM(in_tokens)             AS in_tokens,
                          SUM(out_tokens)            AS out_tokens,
                          SUM(in_tokens + out_tokens) AS total_tokens,
                          SUM(cost_usd)              AS cost_usd,
                          COUNT(*)                   AS requests
                   FROM token_usage
                   WHERE day >= date('now', ? || ' days')
                   GROUP BY feature, model, provider
                   ORDER BY cost_usd DESC""",
                (f"-{days}",),
            ).fetchall()

        return [
            {
                "feature":      r["feature"],
                "model":        r["model"],
                "provider":     r["provider"],
                "in_tokens":    int(r["in_tokens"]),
                "out_tokens":   int(r["out_tokens"]),
                "total_tokens": int(r["total_tokens"]),
                "cost_usd":     round(float(r["cost_usd"] or 0), 6),
                "requests":     int(r["requests"]),
            }
            for r in rows
        ]

    def reset(self) -> int:
        with self._lock:
            conn = self._ensure()
            cur = conn.execute("DELETE FROM token_usage")
            conn.commit()
            return cur.rowcount
