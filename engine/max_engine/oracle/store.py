"""Oracle store — the long-term, self-grading prediction track record.

Three plain-SQLite tables in the shared ``.apollo.db`` (the same file the vector
memory, prediction history, analytics, and user profile live in). Unlike the
30-day vector memory, the Oracle dataset is kept **indefinitely** — it is the
ground-truth training set the calibrator learns from, so it must not expire.

    oracle_reports  — one row per generated report (Apollo / Market / OSINT)
    oracle_claims   — atomic checkable claims extracted from each report
    oracle_grades   — one row per claim per checkpoint (24h/7d/30d): the verdict

Thread-safe via a lock with one shared connection (``check_same_thread=False``).
Callers run writes from a thread (``asyncio.to_thread``) so the event loop never
blocks. All reads return plain dicts.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import Lock

from .grading import brier as _brier

_DDL = """
CREATE TABLE IF NOT EXISTS oracle_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    feature     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    title       TEXT,
    body        TEXT NOT NULL,
    context_json TEXT,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS oracle_claims (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL,
    feature       TEXT NOT NULL,
    claim         TEXT NOT NULL,
    entity        TEXT,
    entity_kind   TEXT,
    direction     TEXT,
    magnitude     REAL,
    horizon_hours INTEGER,
    confidence    REAL,
    embedding_ref TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS oracle_grades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id      INTEGER NOT NULL,
    checkpoint    TEXT NOT NULL,
    score         INTEGER NOT NULL,
    outcome       TEXT NOT NULL,
    brier         REAL,
    failure_tag   TEXT,
    reason        TEXT,
    source        TEXT NOT NULL,
    evidence_json TEXT,
    user_verified INTEGER NOT NULL DEFAULT 0,
    graded_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oracle_claims_status ON oracle_claims(status, created_at);
CREATE INDEX IF NOT EXISTS idx_oracle_claims_entity ON oracle_claims(entity);
CREATE INDEX IF NOT EXISTS idx_oracle_grades_claim ON oracle_grades(claim_id, checkpoint);
"""


class OracleStore:
    """Persistent track-record store. One file, three tables, kept forever."""

    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_DDL)
            conn.commit()

    # ---- writes ---------------------------------------------------------

    def add_report(
        self, *, feature: str, kind: str, title: str, body: str, context: dict | None = None
    ) -> int:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO oracle_reports (feature, kind, title, body, context_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (feature, kind, title, body, json.dumps(context or {}), now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def add_claims(self, report_id: int, feature: str, claims: list[dict]) -> list[int]:
        """Insert extracted claims for a report. Returns the new claim ids."""
        now = int(time.time())
        ids: list[int] = []
        with self._lock, self._connect() as conn:
            for c in claims:
                cur = conn.execute(
                    "INSERT INTO oracle_claims "
                    "(report_id, feature, claim, entity, entity_kind, direction, magnitude, "
                    " horizon_hours, confidence, embedding_ref, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                    (
                        report_id,
                        feature,
                        c.get("claim", ""),
                        c.get("entity"),
                        c.get("entity_kind"),
                        c.get("direction"),
                        c.get("magnitude"),
                        int(c.get("horizon_hours") or 0) or None,
                        float(c.get("confidence") or 0.0),
                        c.get("embedding_ref"),
                        now,
                    ),
                )
                ids.append(int(cur.lastrowid))
            conn.commit()
        return ids

    def add_grade(
        self,
        *,
        claim_id: int,
        checkpoint: str,
        score: int,
        outcome: str,
        confidence: float,
        failure_tag: str | None = None,
        reason: str = "",
        source: str = "llm-local",
        evidence: dict | None = None,
        user_verified: bool = False,
    ) -> int:
        now = int(time.time())
        b = _brier(confidence, outcome, score)
        with self._lock, self._connect() as conn:
            # A manual override supersedes any prior grade at this checkpoint.
            if user_verified:
                conn.execute(
                    "DELETE FROM oracle_grades WHERE claim_id = ? AND checkpoint = ?",
                    (claim_id, checkpoint),
                )
            cur = conn.execute(
                "INSERT INTO oracle_grades "
                "(claim_id, checkpoint, score, outcome, brier, failure_tag, reason, source, "
                " evidence_json, user_verified, graded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim_id, checkpoint, int(score), outcome, b, failure_tag, reason, source,
                    json.dumps(evidence or {}), 1 if user_verified else 0, now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def set_claim_status(self, claim_id: int, status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE oracle_claims SET status = ? WHERE id = ?", (status, claim_id))
            conn.commit()

    def set_embedding_ref(self, claim_id: int, ref: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE oracle_claims SET embedding_ref = ? WHERE id = ?", (ref, claim_id)
            )
            conn.commit()

    # ---- reads ----------------------------------------------------------

    @staticmethod
    def _claim_row(r: sqlite3.Row) -> dict:
        return {
            "id": r["id"],
            "reportId": r["report_id"],
            "feature": r["feature"],
            "claim": r["claim"],
            "entity": r["entity"],
            "entityKind": r["entity_kind"],
            "direction": r["direction"],
            "magnitude": r["magnitude"],
            "horizonHours": r["horizon_hours"],
            "confidence": r["confidence"],
            "status": r["status"],
            "createdAt": r["created_at"],
        }

    @staticmethod
    def _grade_row(r: sqlite3.Row) -> dict:
        return {
            "id": r["id"],
            "claimId": r["claim_id"],
            "checkpoint": r["checkpoint"],
            "score": r["score"],
            "outcome": r["outcome"],
            "brier": r["brier"],
            "failureTag": r["failure_tag"],
            "reason": r["reason"],
            "source": r["source"],
            "evidence": json.loads(r["evidence_json"] or "{}"),
            "userVerified": bool(r["user_verified"]),
            "gradedAt": r["graded_at"],
        }

    def list_claims(
        self,
        *,
        status: str | None = None,
        feature: str | None = None,
        entity: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Claims (newest first) each with a compact grade summary for the table."""
        sql = "SELECT * FROM oracle_claims WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if feature:
            sql += " AND feature = ?"
            params.append(feature)
        if entity:
            sql += " AND entity = ?"
            params.append(entity.upper())
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            out: list[dict] = []
            for r in rows:
                grades = conn.execute(
                    "SELECT * FROM oracle_grades WHERE claim_id = ? ORDER BY graded_at",
                    (r["id"],),
                ).fetchall()
                d = self._claim_row(r)
                gl = [self._grade_row(g) for g in grades]
                d["grades"] = gl
                d["latestGrade"] = gl[-1] if gl else None
                out.append(d)
        return out

    def get_claim(self, claim_id: int) -> dict | None:
        """A claim with its source report and every checkpoint grade."""
        with self._lock, self._connect() as conn:
            r = conn.execute("SELECT * FROM oracle_claims WHERE id = ?", (claim_id,)).fetchone()
            if not r:
                return None
            d = self._claim_row(r)
            rep = conn.execute(
                "SELECT * FROM oracle_reports WHERE id = ?", (r["report_id"],)
            ).fetchone()
            d["report"] = (
                {
                    "id": rep["id"], "feature": rep["feature"], "kind": rep["kind"],
                    "title": rep["title"], "body": rep["body"],
                    "context": json.loads(rep["context_json"] or "{}"),
                    "createdAt": rep["created_at"],
                }
                if rep else None
            )
            grades = conn.execute(
                "SELECT * FROM oracle_grades WHERE claim_id = ? ORDER BY graded_at", (claim_id,)
            ).fetchall()
            d["grades"] = [self._grade_row(g) for g in grades]
        return d

    def claims_due(self, now: int, checkpoints: list[tuple[str, int]]) -> list[dict]:
        """Pending/active claims whose horizon for a checkpoint has elapsed and
        which have not yet been graded at that checkpoint. One entry per due
        (claim, checkpoint) pair, oldest claims first."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM oracle_claims WHERE status != 'unresolvable' ORDER BY created_at"
            ).fetchall()
            graded = {
                (g["claim_id"], g["checkpoint"])
                for g in conn.execute(
                    "SELECT claim_id, checkpoint FROM oracle_grades"
                ).fetchall()
            }
        due: list[dict] = []
        for r in rows:
            for label, hours in checkpoints:
                if now >= r["created_at"] + hours * 3600 and (r["id"], label) not in graded:
                    d = self._claim_row(r)
                    d["checkpoint"] = label
                    d["checkpointHours"] = hours
                    due.append(d)
        return due

    def claims_by_entity(self, entity: str, *, only_graded: bool = True, limit: int = 12) -> list[dict]:
        """Graded claims for one entity — the entity-tag arm of hindsight matching."""
        if not entity:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM oracle_claims WHERE entity = ? ORDER BY created_at DESC LIMIT ?",
                (entity.upper(), max(1, limit) * 2),
            ).fetchall()
            out: list[dict] = []
            for r in rows:
                grades = conn.execute(
                    "SELECT * FROM oracle_grades WHERE claim_id = ? ORDER BY graded_at",
                    (r["id"],),
                ).fetchall()
                if only_graded and not grades:
                    continue
                d = self._claim_row(r)
                d["grades"] = [self._grade_row(g) for g in grades]
                d["latestGrade"] = d["grades"][-1] if d["grades"] else None
                out.append(d)
                if len(out) >= limit:
                    break
        return out

    def grades_for_training(self) -> list[dict]:
        """Every (claim, grade) pair with a resolved outcome — the labelled set
        the calibrator trains on. ``too-early`` rows are excluded."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT c.feature, c.entity, c.entity_kind, c.direction, c.horizon_hours, "
                "       c.confidence, g.checkpoint, g.score, g.outcome, g.brier, g.source, "
                "       g.user_verified "
                "FROM oracle_grades g JOIN oracle_claims c ON c.id = g.claim_id "
                "WHERE g.outcome != 'too-early'"
            ).fetchall()
        return [
            {
                "feature": r["feature"],
                "entity": r["entity"],
                "entityKind": r["entity_kind"],
                "direction": r["direction"],
                "horizonHours": r["horizon_hours"],
                "confidence": r["confidence"],
                "checkpoint": r["checkpoint"],
                "score": r["score"],
                "outcome": r["outcome"],
                "brier": r["brier"],
                "source": r["source"],
                "userVerified": bool(r["user_verified"]),
            }
            for r in rows
        ]

    def stats(self) -> dict:
        """Aggregate dashboard numbers: counts, accuracy, Brier, failure modes,
        and a per-entity track record. Pure SQL — cheap to call per request."""
        with self._lock, self._connect() as conn:
            total_claims = conn.execute("SELECT count(*) FROM oracle_claims").fetchone()[0]
            pending = conn.execute(
                "SELECT count(*) FROM oracle_claims WHERE status = 'pending'"
            ).fetchone()[0]
            graded = conn.execute(
                "SELECT count(*) FROM oracle_claims WHERE status = 'graded'"
            ).fetchone()[0]
            resolved = conn.execute(
                "SELECT count(*) FROM oracle_grades WHERE outcome != 'too-early'"
            ).fetchone()[0]
            by_outcome = dict(
                conn.execute(
                    "SELECT outcome, count(*) FROM oracle_grades GROUP BY outcome"
                ).fetchall()
            )
            avg_score = conn.execute(
                "SELECT avg(score) FROM oracle_grades WHERE outcome != 'too-early'"
            ).fetchone()[0]
            avg_brier = conn.execute(
                "SELECT avg(brier) FROM oracle_grades WHERE outcome != 'too-early'"
            ).fetchone()[0]
            failures = dict(
                conn.execute(
                    "SELECT failure_tag, count(*) FROM oracle_grades "
                    "WHERE failure_tag IS NOT NULL GROUP BY failure_tag"
                ).fetchall()
            )
            # Calibration curve: bucket stated confidence into deciles, compare to
            # mean realised hit-fraction (score/100) in each bucket.
            curve_rows = conn.execute(
                "SELECT c.confidence AS conf, g.score AS score FROM oracle_grades g "
                "JOIN oracle_claims c ON c.id = g.claim_id WHERE g.outcome != 'too-early'"
            ).fetchall()
            ent_rows = conn.execute(
                "SELECT c.entity AS entity, count(*) AS n, avg(g.score) AS avg_score "
                "FROM oracle_grades g JOIN oracle_claims c ON c.id = g.claim_id "
                "WHERE g.outcome != 'too-early' AND c.entity IS NOT NULL "
                "GROUP BY c.entity ORDER BY n DESC LIMIT 25"
            ).fetchall()
        # Calibration buckets (Python side — small N).
        buckets: dict[int, list[float]] = {}
        for r in curve_rows:
            b = min(9, int((r["conf"] or 0.0) * 10))
            buckets.setdefault(b, []).append((r["score"] or 0) / 100.0)
        curve = [
            {
                "confidence": round((b + 0.5) / 10, 2),
                "actual": round(sum(v) / len(v), 3),
                "count": len(v),
            }
            for b, v in sorted(buckets.items())
        ]
        accuracy = (
            round((by_outcome.get("hit", 0) + 0.5 * by_outcome.get("partial", 0)) / resolved, 3)
            if resolved else None
        )
        return {
            "totalClaims": total_claims,
            "pending": pending,
            "gradedClaims": graded,
            "resolvedGrades": resolved,
            "byOutcome": by_outcome,
            "avgScore": round(avg_score, 1) if avg_score is not None else None,
            "avgBrier": round(avg_brier, 4) if avg_brier is not None else None,
            "accuracy": accuracy,
            "failureModes": failures,
            "calibrationCurve": curve,
            "perEntity": [
                {"entity": r["entity"], "count": r["n"], "avgScore": round(r["avg_score"], 1)}
                for r in ent_rows
            ],
        }
