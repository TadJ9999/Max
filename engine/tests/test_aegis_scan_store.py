"""Tests for Aegis Security Posture store (Phase 16) — scan lifecycle,
finding upsert/dedup, status transitions, reconcile, posture score."""
from __future__ import annotations

import pytest

from max_engine.aegis.store import AegisStore
from max_engine.aegis.scan_service import posture_score


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return AegisStore(str(tmp_path / "test.db"))


# ---------------------------------------------------------------------------
# Posture score math
# ---------------------------------------------------------------------------

class TestPostureScore:
    def test_perfect(self):
        assert posture_score({}) == 100

    def test_one_critical(self):
        assert posture_score({"Critical": 1}) == 85

    def test_one_high(self):
        assert posture_score({"High": 1}) == 93

    def test_mixed(self):
        score = posture_score({"Critical": 1, "High": 2, "Medium": 3, "Low": 4})
        # 100 - 15 - 14 - 9 - 4 = 58
        assert score == 58

    def test_clamp_zero(self):
        assert posture_score({"Critical": 100}) == 0

    def test_clamp_max(self):
        assert posture_score({"Low": 0}) == 100


# ---------------------------------------------------------------------------
# Scan lifecycle
# ---------------------------------------------------------------------------

class TestScanLifecycle:
    def test_start_returns_id(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        assert scan_id

    def test_scan_shows_running(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        scans = store.list_scans()
        assert any(s["id"] == scan_id and s["status"] == "running" for s in scans)

    def test_finish_scan(self, store: AegisStore):
        scan_id = store.start_scan("scheduled")
        store.finish_scan(scan_id, {"Critical": 1, "High": 0, "Medium": 2, "Low": 0}, 85, 42)
        scans = store.list_scans()
        s = next(s for s in scans if s["id"] == scan_id)
        assert s["status"] == "done"
        assert s["score"] == 85
        assert s["files_scanned"] == 42
        assert s["critical"] == 1

    def test_fail_scan(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        store.fail_scan(scan_id)
        scans = store.list_scans()
        s = next(s for s in scans if s["id"] == scan_id)
        assert s["status"] == "error"


# ---------------------------------------------------------------------------
# Finding upsert + dedup
# ---------------------------------------------------------------------------

SAST_FINDING = {
    "category": "sast",
    "rule_id": "R007",
    "cwe": "CWE-295",
    "severity": "High",
    "title": "TLS verification disabled",
    "file": "/engine/client.py",
    "line": 42,
    "snippet": "requests.get(url, verify=False)",
    "message": "TLS disabled",
    "recommendation": "Enable verify",
    "ai_confidence": None,
    "ai_summary": None,
}

SCA_FINDING = {
    "category": "sca",
    "rule_id": "",
    "cwe": "",
    "cve_id": "CVE-2024-0001",
    "package": "requests",
    "installed_version": "2.28.0",
    "fixed_version": "2.32.0",
    "ecosystem": "PyPI",
    "severity": "High",
    "title": "Test vuln in requests",
    "file": "/engine/pyproject.toml",
    "line": 0,
    "snippet": "",
    "message": "Remote code execution",
    "recommendation": "Upgrade to 2.32.0",
    "ai_confidence": None,
    "ai_summary": None,
}


class TestFindingUpsert:
    def test_insert_sast(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, SAST_FINDING)
        assert fid
        f = store.get_finding(fid)
        assert f is not None
        assert f["rule_id"] == "R007"
        assert f["status"] == "open"

    def test_insert_sca(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, SCA_FINDING)
        f = store.get_finding(fid)
        assert f["cve_id"] == "CVE-2024-0001"
        assert f["package"] == "requests"

    def test_dedup_same_finding(self, store: AegisStore):
        scan_id1 = store.start_scan("manual")
        fid1 = store.upsert_finding(scan_id1, SAST_FINDING)

        scan_id2 = store.start_scan("manual")
        fid2 = store.upsert_finding(scan_id2, SAST_FINDING)

        # Same fingerprint → same id
        assert fid1 == fid2

    def test_dedup_updates_scan_id(self, store: AegisStore):
        scan_id1 = store.start_scan("manual")
        fid = store.upsert_finding(scan_id1, SAST_FINDING)

        scan_id2 = store.start_scan("manual")
        store.upsert_finding(scan_id2, SAST_FINDING)

        f = store.get_finding(fid)
        assert f["scan_id"] == scan_id2  # updated to latest scan
        assert f["first_scan_id"] == scan_id1  # origin preserved

    def test_ignored_finding_not_overwritten(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, SAST_FINDING)
        store.set_finding_status(fid, "ignored")

        # Re-upsert on next scan — status stays ignored
        scan_id2 = store.start_scan("manual")
        store.upsert_finding(scan_id2, SAST_FINDING)
        f = store.get_finding(fid)
        # upsert refreshes fields but our schema preserves 'ignored' by not touching status
        # (the upsert UPDATE doesn't change status)
        assert f["status"] == "ignored"


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

class TestStatusTransitions:
    def test_open_to_ignored(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, SAST_FINDING)
        store.set_finding_status(fid, "ignored")
        assert store.get_finding(fid)["status"] == "ignored"

    def test_ignored_to_open(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, SAST_FINDING)
        store.set_finding_status(fid, "ignored")
        store.set_finding_status(fid, "open")
        assert store.get_finding(fid)["status"] == "open"

    def test_open_to_fixed(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, SAST_FINDING)
        store.set_finding_status(fid, "fixed")
        assert store.get_finding(fid)["status"] == "fixed"


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_reconcile_marks_vanished_findings_fixed(self, store: AegisStore):
        scan_id1 = store.start_scan("manual")
        fid = store.upsert_finding(scan_id1, SAST_FINDING)
        assert store.get_finding(fid)["status"] == "open"

        # Second scan — R007 no longer seen (vuln fixed)
        scan_id2 = store.start_scan("manual")
        # Only insert a different finding
        store.upsert_finding(scan_id2, SCA_FINDING)
        store.reconcile_scan(scan_id2)

        # R007 should now be "fixed"
        assert store.get_finding(fid)["status"] == "fixed"

    def test_reconcile_leaves_ignored_alone(self, store: AegisStore):
        scan_id1 = store.start_scan("manual")
        fid = store.upsert_finding(scan_id1, SAST_FINDING)
        store.set_finding_status(fid, "ignored")

        scan_id2 = store.start_scan("manual")
        store.reconcile_scan(scan_id2)

        # Ignored findings are not touched by reconcile (status column isn't 'open')
        assert store.get_finding(fid)["status"] == "ignored"


# ---------------------------------------------------------------------------
# list_findings filtering
# ---------------------------------------------------------------------------

class TestListFindings:
    def test_filter_by_category(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        store.upsert_finding(scan_id, SAST_FINDING)
        store.upsert_finding(scan_id, SCA_FINDING)

        sast = store.list_findings(category="sast")
        sca = store.list_findings(category="sca")
        assert all(f["category"] == "sast" for f in sast)
        assert all(f["category"] == "sca" for f in sca)

    def test_filter_by_status_default(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, SAST_FINDING)
        store.set_finding_status(fid, "ignored")

        open_findings = store.list_findings(status="open")
        assert not any(f["id"] == fid for f in open_findings)

    def test_sorted_by_severity(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        store.upsert_finding(scan_id, {**SAST_FINDING, "severity": "Low", "snippet": "x=1", "rule_id": "R009"})
        store.upsert_finding(scan_id, {**SAST_FINDING, "severity": "Critical", "snippet": "x=2", "rule_id": "R001"})
        store.upsert_finding(scan_id, {**SAST_FINDING, "severity": "High", "snippet": "x=3"})

        findings = store.list_findings(status="open")
        sevs = [f["severity"] for f in findings]
        assert sevs[0] == "Critical"


# ---------------------------------------------------------------------------
# Posture
# ---------------------------------------------------------------------------

class TestPosture:
    def test_posture_no_scans(self, store: AegisStore):
        p = store.posture()
        assert p["score"] == 100
        assert p["last_scan_ts"] is None

    def test_posture_after_scan(self, store: AegisStore):
        scan_id = store.start_scan("manual")
        store.upsert_finding(scan_id, SAST_FINDING)  # 1 High
        store.finish_scan(scan_id, {"High": 1}, 93, 10)
        p = store.posture()
        assert p["score"] == 93

    def test_posture_history(self, store: AegisStore):
        for i in range(3):
            sid = store.start_scan("scheduled")
            store.finish_scan(sid, {}, 100 - i * 10, 5)
        p = store.posture(history_limit=5)
        assert len(p["history"]) == 3
