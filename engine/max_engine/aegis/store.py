"""Aegis event store — persists captured errors and security-posture data into
the shared .apollo.db.

Tables owned by this module:
  aegis_events   — runtime error events (existing)
  aegis_log      — diagnosis / apply / rollback history (existing)
  aegis_scans    — Phase 16: scan run records (new)
  aegis_findings — Phase 16: SAST + SCA findings (new)

No sqlite-vec extension needed — plain SQLite only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
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
            CREATE TABLE IF NOT EXISTS aegis_scans (
                id            TEXT PRIMARY KEY,
                ts            TEXT NOT NULL,
                finished_ts   TEXT,
                status        TEXT NOT NULL,
                trigger       TEXT,
                files_scanned INTEGER DEFAULT 0,
                score         INTEGER,
                critical      INTEGER DEFAULT 0,
                high          INTEGER DEFAULT 0,
                medium        INTEGER DEFAULT 0,
                low           INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS aegis_findings (
                id                TEXT PRIMARY KEY,
                fingerprint       TEXT NOT NULL,
                scan_id           TEXT,
                first_scan_id     TEXT,
                category          TEXT,
                rule_id           TEXT,
                cwe               TEXT,
                cve_id            TEXT,
                package           TEXT,
                installed_version TEXT,
                fixed_version     TEXT,
                severity          TEXT,
                title             TEXT,
                file              TEXT,
                line              INTEGER,
                snippet           TEXT,
                message           TEXT,
                recommendation    TEXT,
                ai_confidence     REAL,
                ai_summary        TEXT,
                status            TEXT DEFAULT 'open',
                first_ts          TEXT,
                last_ts           TEXT,
                log_id            TEXT
            );
            CREATE INDEX IF NOT EXISTS aegis_find_fp     ON aegis_findings(fingerprint);
            CREATE INDEX IF NOT EXISTS aegis_find_status ON aegis_findings(status);
            CREATE INDEX IF NOT EXISTS aegis_find_scan   ON aegis_findings(scan_id);
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

    # ================================================================
    # Phase 16 — Security Posture: scan lifecycle
    # ================================================================

    def start_scan(self, trigger: str = "manual") -> str:
        now = datetime.now(timezone.utc).isoformat()
        scan_id = str(uuid.uuid4())
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT INTO aegis_scans (id, ts, status, trigger) VALUES (?,?,?,?)",
                (scan_id, now, "running", trigger),
            )
            conn.commit()
        return scan_id

    def finish_scan(
        self,
        scan_id: str,
        counts: dict[str, int],
        score: int,
        files_scanned: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "UPDATE aegis_scans SET status=?, finished_ts=?, score=?, "
                "files_scanned=?, critical=?, high=?, medium=?, low=? WHERE id=?",
                (
                    "done", now, score, files_scanned,
                    counts.get("Critical", 0),
                    counts.get("High", 0),
                    counts.get("Medium", 0),
                    counts.get("Low", 0),
                    scan_id,
                ),
            )
            conn.commit()

    def fail_scan(self, scan_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "UPDATE aegis_scans SET status=?, finished_ts=? WHERE id=?",
                ("error", now, scan_id),
            )
            conn.commit()

    def update_scan_files(self, scan_id: str, count: int) -> None:
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "UPDATE aegis_scans SET files_scanned=? WHERE id=?", (count, scan_id)
            )
            conn.commit()

    # ---- findings -------------------------------------------------------

    @staticmethod
    def _finding_fingerprint(finding: dict) -> str:
        cat = finding.get("category", "")
        if cat == "sca":
            raw = f"sca:{finding.get('cve_id', '')}:{finding.get('package', '')}"
        else:
            raw = f"sast:{finding.get('rule_id', '')}:{finding.get('file', '')}:{finding.get('snippet', '')[:120]}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def upsert_finding(self, scan_id: str, finding: dict) -> str:
        """Insert or update a finding by fingerprint. Returns the finding id."""
        now = datetime.now(timezone.utc).isoformat()
        fp = self._finding_fingerprint(finding)
        with self._lock:
            conn = self._ensure()
            existing = conn.execute(
                "SELECT id, status FROM aegis_findings WHERE fingerprint=?", (fp,)
            ).fetchone()

            if existing:
                fid = existing["id"]
                # Refresh fields for existing finding; leave status=ignored alone
                conn.execute(
                    "UPDATE aegis_findings SET scan_id=?, last_ts=?, "
                    "severity=?, title=?, message=?, recommendation=?, "
                    "ai_confidence=?, ai_summary=?, fixed_version=? "
                    "WHERE fingerprint=?",
                    (
                        scan_id, now,
                        finding.get("severity"),
                        finding.get("title"),
                        finding.get("message"),
                        finding.get("recommendation"),
                        finding.get("ai_confidence"),
                        finding.get("ai_summary"),
                        finding.get("fixed_version"),
                        fp,
                    ),
                )
            else:
                fid = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO aegis_findings ("
                    " id, fingerprint, scan_id, first_scan_id, category, rule_id, cwe,"
                    " cve_id, package, installed_version, fixed_version,"
                    " severity, title, file, line, snippet, message, recommendation,"
                    " ai_confidence, ai_summary, status, first_ts, last_ts"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fid, fp, scan_id, scan_id,
                        finding.get("category"),
                        finding.get("rule_id"),
                        finding.get("cwe"),
                        finding.get("cve_id"),
                        finding.get("package"),
                        finding.get("installed_version"),
                        finding.get("fixed_version"),
                        finding.get("severity"),
                        finding.get("title"),
                        finding.get("file"),
                        finding.get("line", 0),
                        finding.get("snippet"),
                        finding.get("message"),
                        finding.get("recommendation"),
                        finding.get("ai_confidence"),
                        finding.get("ai_summary"),
                        "open",
                        now, now,
                    ),
                )
            conn.commit()
        return fid

    def reconcile_scan(self, scan_id: str) -> int:
        """Mark open findings not seen in scan_id as 'fixed'. Returns count."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._ensure()
            cur = conn.execute(
                "UPDATE aegis_findings SET status='fixed', last_ts=? "
                "WHERE status='open' AND scan_id != ?",
                (now, scan_id),
            )
            conn.commit()
        return cur.rowcount

    def get_finding(self, finding_id: str) -> dict | None:
        with self._lock:
            conn = self._ensure()
            row = conn.execute(
                "SELECT * FROM aegis_findings WHERE id=?", (finding_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_findings(
        self,
        category: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if category:
            clauses.append("category=?")
            params.append(category)
        if status:
            clauses.append("status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                f"SELECT * FROM aegis_findings {where} "
                "ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 "
                "WHEN 'Medium' THEN 2 ELSE 3 END, last_ts DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def set_finding_status(self, finding_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "UPDATE aegis_findings SET status=?, last_ts=? WHERE id=?",
                (status, now, finding_id),
            )
            conn.commit()

    def stamp_finding_log(self, finding_id: str, log_id: str) -> None:
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "UPDATE aegis_findings SET log_id=? WHERE id=?", (log_id, finding_id)
            )
            conn.commit()

    # ---- scan history / posture -----------------------------------------

    def list_scans(self, limit: int = 20) -> list[dict]:
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                "SELECT * FROM aegis_scans ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def posture(self, history_limit: int = 10) -> dict:
        """Return current posture: latest score, counts, at_risk, scan history."""
        with self._lock:
            conn = self._ensure()
            latest = conn.execute(
                "SELECT * FROM aegis_scans WHERE status='done' ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            history = conn.execute(
                "SELECT ts, score FROM aegis_scans WHERE status='done' "
                "ORDER BY ts DESC LIMIT ?",
                (history_limit,),
            ).fetchall()
            open_counts = conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM aegis_findings "
                "WHERE status='open' GROUP BY severity"
            ).fetchall()

        counts: dict[str, int] = {}
        for row in open_counts:
            counts[row["severity"]] = row["cnt"]

        score = latest["score"] if latest and latest["score"] is not None else 100
        return {
            "score": score,
            "critical": counts.get("Critical", 0),
            "high": counts.get("High", 0),
            "medium": counts.get("Medium", 0),
            "low": counts.get("Low", 0),
            "last_scan_ts": latest["ts"] if latest else None,
            "at_risk": score < 70,  # overridden by caller with config threshold
            "history": [{"ts": r["ts"], "score": r["score"]} for r in reversed(list(history))],
        }

    # ---- log helpers for findings ----------------------------------------

    def append_log_for_finding(self, finding_id: str, entry: dict) -> str:
        """Like append_log but stores finding_id in event_id column."""
        return self.append_log({**entry, "event_id": finding_id})
