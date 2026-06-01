"""Oracle store tests — the long-term track-record tables (real tiny SQLite)."""

import time

from max_engine.oracle.grading import checkpoints
from max_engine.oracle.store import OracleStore


def _store(tmp_path):
    return OracleStore(str(tmp_path / "t.apollo.db"))


def _claim(**kw):
    base = {
        "claim": "AAPL rises next week", "entity": "AAPL", "entity_kind": "ticker",
        "direction": "up", "magnitude": 5.0, "horizon_hours": 168, "confidence": 0.8,
    }
    base.update(kw)
    return base


def test_add_report_and_claims(tmp_path):
    s = _store(tmp_path)
    rid = s.add_report(feature="market", kind="market_report", title="Brief", body="text")
    ids = s.add_claims(rid, "market", [_claim(), _claim(entity="MSFT")])
    assert len(ids) == 2
    rows = s.list_claims()
    assert len(rows) == 2
    assert rows[0]["status"] == "pending"
    assert rows[0]["grades"] == []


def test_claims_due_respects_horizon_and_existing_grade(tmp_path):
    s = _store(tmp_path)
    rid = s.add_report(feature="market", kind="r", title="t", body="b")
    (cid,) = s.add_claims(rid, "market", [_claim()])
    cps = checkpoints([24, 168, 720])

    # Nothing due immediately.
    assert s.claims_due(int(time.time()), cps) == []

    # 8 days later → 24h and 7d checkpoints are due, 30d is not.
    later = int(time.time()) + 8 * 86_400
    due = s.claims_due(later, cps)
    labels = {d["checkpoint"] for d in due}
    assert labels == {"24h", "7d"}

    # Grade the 24h checkpoint → it drops out of "due".
    s.add_grade(claim_id=cid, checkpoint="24h", score=80, outcome="hit", confidence=0.8)
    due2 = {d["checkpoint"] for d in s.claims_due(later, cps)}
    assert due2 == {"7d"}


def test_grade_brier_and_training_rows(tmp_path):
    s = _store(tmp_path)
    rid = s.add_report(feature="apollo", kind="prediction", title="t", body="b")
    (cid,) = s.add_claims(rid, "apollo", [_claim(confidence=0.9)])
    s.add_grade(claim_id=cid, checkpoint="7d", score=0, outcome="miss",
                confidence=0.9, failure_tag="wrong-direction", reason="opposite")
    rows = s.grades_for_training()
    assert len(rows) == 1
    # Brier for a confident miss is high: (0.9 - 0)^2 = 0.81.
    g = s.get_claim(cid)["grades"][0]
    assert g["brier"] == 0.81
    assert g["failureTag"] == "wrong-direction"


def test_too_early_excluded_from_training(tmp_path):
    s = _store(tmp_path)
    rid = s.add_report(feature="osint", kind="osint_report", title="t", body="b")
    (cid,) = s.add_claims(rid, "osint", [_claim(entity="Ukraine", entity_kind="country")])
    s.add_grade(claim_id=cid, checkpoint="24h", score=0, outcome="too-early", confidence=0.5)
    assert s.grades_for_training() == []


def test_user_override_replaces_grade(tmp_path):
    s = _store(tmp_path)
    rid = s.add_report(feature="apollo", kind="prediction", title="t", body="b")
    (cid,) = s.add_claims(rid, "apollo", [_claim()])
    s.add_grade(claim_id=cid, checkpoint="30d", score=20, outcome="miss", confidence=0.8)
    s.add_grade(claim_id=cid, checkpoint="30d", score=90, outcome="hit",
                confidence=0.8, source="user", user_verified=True)
    grades = s.get_claim(cid)["grades"]
    assert len(grades) == 1 and grades[0]["score"] == 90 and grades[0]["userVerified"]


def test_stats_accuracy_and_failures(tmp_path):
    s = _store(tmp_path)
    rid = s.add_report(feature="market", kind="r", title="t", body="b")
    ids = s.add_claims(rid, "market", [_claim(), _claim(entity="MSFT"), _claim(entity="NVDA")])
    s.add_grade(claim_id=ids[0], checkpoint="7d", score=85, outcome="hit", confidence=0.7)
    s.add_grade(claim_id=ids[1], checkpoint="7d", score=50, outcome="partial",
                confidence=0.6, failure_tag="wrong-magnitude")
    s.add_grade(claim_id=ids[2], checkpoint="7d", score=10, outcome="miss",
                confidence=0.9, failure_tag="wrong-direction")
    st = s.stats()
    assert st["resolvedGrades"] == 3
    assert st["byOutcome"] == {"hit": 1, "partial": 1, "miss": 1}
    # accuracy = (1 hit + 0.5 partial) / 3 = 0.5
    assert st["accuracy"] == 0.5
    assert st["failureModes"]["wrong-direction"] == 1
    assert any(e["entity"] == "AAPL" for e in st["perEntity"])
