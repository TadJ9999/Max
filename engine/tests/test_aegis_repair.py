"""Tests for Aegis repair (whole-file fix → review → apply).

Covers the propose → apply round-trip: a stub provider returns a planner JSON
plan, ``RepairService`` turns it into reviewable patches, and ``apply`` writes the
file, verifies (monkeypatched), and keeps or rolls back.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from max_engine.aegis import repair as repair_mod
from max_engine.aegis.repair import RepairService
from max_engine.aegis.store import AegisStore
from max_engine.config import EngineConfig
from max_engine.providers.base import ChatChunk


# ---------------------------------------------------------------------------
# Stubs / fixtures
# ---------------------------------------------------------------------------

class StubProvider:
    """Yields a canned model response as a single ChatChunk."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def chat(self, model, messages):  # noqa: ANN001
        yield ChatChunk(text=self._payload, done=False)
        yield ChatChunk(text="", done=True)


def _install_provider(monkeypatch, payload: str) -> None:
    monkeypatch.setattr(repair_mod, "build_provider", lambda name, cfg: StubProvider(payload))
    monkeypatch.setattr(repair_mod, "model_for", lambda name, task, cfg: "test-model")


@pytest.fixture
def repo(tmp_path):
    """A git repo with one source file and an AegisStore."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    src = tmp_path / "app.py"
    src.write_text("import requests\nrequests.get(url, verify=False)\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    store = AegisStore(str(tmp_path / "test.db"))
    return tmp_path, src, store


def _finding(src) -> dict:
    return {
        "category": "sast",
        "rule_id": "R007",
        "cwe": "CWE-295",
        "severity": "High",
        "title": "TLS verification disabled",
        "file": str(src),
        "line": 2,
        "snippet": "requests.get(url, verify=False)",
        "message": "TLS disabled",
        "recommendation": "Enable verify",
        "ai_confidence": None,
        "ai_summary": None,
    }


FIXED_SRC = "import requests\nrequests.get(url, verify=True)\n"


def _plan_payload(path: str, new_content: str = FIXED_SRC) -> str:
    return json.dumps({
        "summary": "Enable TLS verification",
        "patches": [
            {"path": path, "description": "set verify=True", "new_content": new_content}
        ],
    })


async def _collect_plan(gen):
    """Drain a propose SSE generator → return the parsed plan dict (or None)."""
    plan = None
    async for evt in gen:
        line = evt.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        obj = json.loads(data)
        if "plan" in obj:
            plan = obj["plan"]
    return plan


# ---------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------

class TestPropose:
    async def test_finding_plan_has_new_content_and_diff(self, repo, monkeypatch):
        root, src, store = repo
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, _finding(src))
        _install_provider(monkeypatch, _plan_payload(str(src)))

        svc = RepairService(store, EngineConfig(), str(root))
        plan = await _collect_plan(svc.propose_for_finding(fid))

        assert plan is not None
        assert plan["log_id"]
        assert len(plan["patches"]) == 1
        patch = plan["patches"][0]
        assert patch["new_content"] == FIXED_SRC
        assert patch["diff"].strip() != ""
        assert "verify=True" in patch["diff"]
        # A proposed log row was created and stamped on the finding.
        assert store.get_finding(fid)["log_id"] == plan["log_id"]

    async def test_no_change_yields_note(self, repo, monkeypatch):
        root, src, store = repo
        scan_id = store.start_scan("manual")
        fid = store.upsert_finding(scan_id, _finding(src))
        # Model returns the file unchanged → nothing to apply.
        unchanged = src.read_text(encoding="utf-8")
        _install_provider(monkeypatch, _plan_payload(str(src), unchanged))

        svc = RepairService(store, EngineConfig(), str(root))
        plan = await _collect_plan(svc.propose_for_finding(fid))
        assert plan is None


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

class TestApply:
    def test_apply_writes_file_when_verify_passes(self, repo, monkeypatch):
        root, src, store = repo
        monkeypatch.setattr(repair_mod, "_verify_for", lambda r, paths: (True, "ok"))

        svc = RepairService(store, EngineConfig(), str(root))
        log_id = store.append_log_for_finding("f1", {"status": "proposed"})
        result = svc.apply(
            "finding", "f1",
            [{"path": str(src), "new_content": FIXED_SRC}],
            log_id,
        )
        assert result["ok"] is True
        assert src.read_text(encoding="utf-8") == FIXED_SRC
        # Log moved to verified.
        log = next(r for r in store.list_log() if r["id"] == log_id)
        assert log["status"] == "verified"

    def test_apply_rolls_back_when_verify_fails(self, repo, monkeypatch):
        root, src, store = repo
        original = src.read_text(encoding="utf-8")
        monkeypatch.setattr(repair_mod, "_verify_for", lambda r, paths: (False, "pytest failed"))

        svc = RepairService(store, EngineConfig(), str(root))
        log_id = store.append_log_for_finding("f1", {"status": "proposed"})
        result = svc.apply(
            "finding", "f1",
            [{"path": str(src), "new_content": FIXED_SRC}],
            log_id,
        )
        assert result["ok"] is False
        # File restored to its committed content.
        assert src.read_text(encoding="utf-8") == original
        log = next(r for r in store.list_log() if r["id"] == log_id)
        assert log["status"] == "rolled-back"

    def test_apply_rejects_path_outside_allowlist(self, repo, monkeypatch):
        root, src, store = repo
        monkeypatch.setattr(repair_mod, "_verify_for", lambda r, paths: (True, "ok"))
        cfg = EngineConfig(workspace_allowlist=[str(root / "engine")])

        svc = RepairService(store, cfg, str(root))
        with pytest.raises(PermissionError):
            svc.apply("finding", "f1", [{"path": str(src), "new_content": FIXED_SRC}], None)
        # File untouched.
        assert "verify=False" in src.read_text(encoding="utf-8")

    def test_apply_rejects_path_outside_repo(self, repo, monkeypatch):
        root, src, store = repo
        monkeypatch.setattr(repair_mod, "_verify_for", lambda r, paths: (True, "ok"))
        svc = RepairService(store, EngineConfig(), str(root))
        with pytest.raises(PermissionError):
            svc.apply(
                "finding", "f1",
                [{"path": str(root.parent / "outside.py"), "new_content": "x=1\n"}],
                None,
            )
