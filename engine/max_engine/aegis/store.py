"""Aegis event store — persists captured errors into the shared .apollo.db.

Adds a regular ``aegis_events`` table alongside Apollo's vec0 virtual table.
No sqlite-vec extension needed here — plain SQLite only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any
import uuid


class AegisStore:
    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # ---- connection / schema -------------------------------------------

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS aegis_events (
                id          TEXT PRIMARY KEY,
                ts          TEXT NOT NULL,
                source      TEXT NOT NULL,
                severity    TEXT NOT NULL,
                kind        TEXT NOT NULL,
                message     TEXT NOT NULL,
                traceback   TEXT,
                context     TEXT,
                fingerprint TEXT NOT NULL,
                count       INTEGER DEFAULT 1,
                first_ts    TEXT NOT NULL,
                last_ts     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS aegis_fp ON aegis_events(fingerprint);
            CREATE INDEX IF NOT EXISTS aegis_ts ON aegis_events(ts DESC);
            CREATE TABLE IF NOT EXISTS aegis_log (
                id          TEXT PRIMARY KEY,
                ts          TEXT NOT NULL,
                event_id    TEXT,
                status      TEXT NOT NULL,
                severity    TEXT,
                symptom     TEXT,
                root_cause  TEXT,
                diff        TEXT,
                provider    TEXT,
                verification TEXT,
                snapshot_ref TEXT
            );
        """)
        conn.commit()
        self._conn = conn
        return conn

    # ---- fingerprint ----------------------------------------------------

    @staticmethod
    def fingerprint(kind: str, source: str, message: str) -> str:
        raw = f"{kind}:{source}:{message[:120]}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    # ---- writes ---------------------------------------------------------

    def ingest(self, event: dict[str, Any]) -> str:
        """Dedup-upsert an event by fingerprint. Returns the event id."""
        now = datetime.now(timezone.utc).isoformat()
        fp = self.fingerprint(
            event.get("kind", ""),
            event.get("source", ""),
            event.get("message", ""),
        )
        with self._lock:
            conn = self._ensure()
            existing = conn.execute(
                "SELECT id, count FROM aegis_events WHERE fingerprint = ?", (fp,)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE aegis_events SET count = count + 1, last_ts = ?, "
                    "message = ?, traceback = ?, context = ? WHERE fingerprint = ?",
                    (
                        now,
                        event.get("message", ""),
                        event.get("traceback"),
                        json.dumps(event.get("context") or {}),
                        fp,
                    ),
                )
                eid = existing["id"]
            else:
                eid = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO aegis_events "
                    "(id, ts, source, severity, kind, message, traceback, context, "
                    " fingerprint, count, first_ts, last_ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
                    (
                        eid,
                        now,
                        event.get("source", "engine"),
                        event.get("severity", "Medium"),
                        event.get("kind", "Exception"),
                        event.get("message", ""),
                        event.get("traceback"),
                        json.dumps(event.get("context") or {}),
                        fp,
                        now,
                        now,
                    ),
                )
            conn.commit()
        return eid

    def append_log(self, entry: dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        lid = str(uuid.uuid4())
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT INTO aegis_log (id, ts, event_id, status, severity, symptom, "
                "root_cause, diff, provider, verification, snapshot_ref) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lid,
                    now,
                    entry.get("event_id"),
                    entry.get("status", "proposed"),
                    entry.get("severity"),
                    entry.get("symptom"),
                    entry.get("root_cause"),
                    entry.get("diff"),
                    entry.get("provider"),
                    entry.get("verification"),
                    entry.get("snapshot_ref"),
                ),
            )
            conn.commit()
        return lid

    def update_log_status(self, log_id: str, status: str, verification: str | None = None) -> None:
        with self._lock:
            conn = self._ensure()
            if verification is not None:
                conn.execute(
                    "UPDATE aegis_log SET status = ?, verification = ? WHERE id = ?",
                    (status, verification, log_id),
                )
            else:
                conn.execute("UPDATE aegis_log SET status = ? WHERE id = ?", (status, log_id))
            conn.commit()

    # ---- reads ----------------------------------------------------------

    def get_event(self, event_id: str) -> dict | None:
        with self._lock:
            conn = self._ensure()
            row = conn.execute(
                "SELECT * FROM aegis_events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                "SELECT * FROM aegis_events ORDER BY last_ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_log(self, limit: int = 100) -> list[dict]:
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                "SELECT * FROM aegis_log ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_event(self, event_id: str) -> None:
        with self._lock:
            conn = self._ensure()
            conn.execute("DELETE FROM aegis_events WHERE id = ?", (event_id,))
            conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["context"] = json.loads(d.get("context") or "{}")
        except (ValueError, TypeError):
            d["context"] = {}
        return d
