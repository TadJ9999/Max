"""Calibrator tests — cold-start gate always; training path only when sklearn is
installed (it's an optional dep, lazily imported)."""

import pytest

from max_engine.oracle.calibrator import OracleCalibrator, sklearn_available


def _rows(n, *, confidence, outcome):
    return [
        {
            "feature": "market", "entity": "AAPL", "entityKind": "ticker",
            "direction": "up", "horizonHours": 168, "confidence": confidence,
            "checkpoint": "7d", "score": 90 if outcome == "hit" else 5,
            "outcome": outcome, "brier": 0.1, "source": "objective", "userVerified": False,
        }
        for _ in range(n)
    ]


def test_cold_start_gate(tmp_path):
    cal = OracleCalibrator(str(tmp_path / "m.pkl"), min_samples=30)
    meta = cal.train(_rows(5, confidence=0.8, outcome="hit"))
    assert meta["ready"] is False
    assert meta["samples"] == 5
    assert cal.correct({"confidence": 0.9})["ready"] is False


@pytest.mark.skipif(not sklearn_available(), reason="scikit-learn not installed")
def test_trains_and_shrinks_overconfidence(tmp_path):
    cal = OracleCalibrator(str(tmp_path / "m.pkl"), min_samples=20)
    # 40 samples all stated 0.9 confidence but only ever miss → calibrator should
    # pull a fresh 0.9 call's confidence well below 0.9.
    rows = _rows(40, confidence=0.9, outcome="miss")
    meta = cal.train(rows)
    assert meta["ready"] is True
    out = cal.correct({"confidence": 0.9, "entity": "AAPL"})
    assert out["ready"] is True
    assert out["calibratedConfidence"] < 0.6  # overconfidence trimmed

    # A freshly constructed calibrator loads the persisted model.
    cal2 = OracleCalibrator(str(tmp_path / "m.pkl"), min_samples=20)
    assert cal2.ready is True
