"""Tests for the Aegis SAST scanner (Phase 16)."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from max_engine.aegis.scanner import RULES, scan_files, _fingerprint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_file(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Per-rule fire tests — each rule should fire on its known-bad snippet
# ---------------------------------------------------------------------------

class TestRuleFires:
    def test_R001_hardcoded_secret(self, tmp_path: Path):
        write_file(tmp_path, "cfg.py", 'api_key = "sk-ant-supersecret1234567890abcdef"\n')
        findings, _ = scan_files([str(tmp_path)])
        ids = [f["rule_id"] for f in findings]
        assert "R001" in ids

    def test_R002_eval_dynamic(self, tmp_path: Path):
        write_file(tmp_path, "app.py", "result = eval(user_input)\n")
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R002" for f in findings)

    def test_R003_shell_true(self, tmp_path: Path):
        write_file(tmp_path, "runner.py", 'subprocess.run(cmd, shell=True)\n')
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R003" for f in findings)

    def test_R003_os_system(self, tmp_path: Path):
        write_file(tmp_path, "runner.py", 'os.system("rm -rf /tmp/" + user_path)\n')
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R003" for f in findings)

    def test_R004_sql_concat(self, tmp_path: Path):
        write_file(tmp_path, "db.py", 'query = "SELECT * FROM users WHERE name = " + user_name\n')
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R004" for f in findings)

    def test_R005_pickle_load(self, tmp_path: Path):
        write_file(tmp_path, "ser.py", "data = pickle.load(f)\n")
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R005" for f in findings)

    def test_R005_yaml_unsafe(self, tmp_path: Path):
        write_file(tmp_path, "cfg.py", "cfg = yaml.load(stream)\n")
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R005" for f in findings)

    def test_R006_inner_html(self, tmp_path: Path):
        write_file(tmp_path, "app.tsx", "div.innerHTML = userContent;\n")
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R006" for f in findings)

    def test_R007_verify_false(self, tmp_path: Path):
        write_file(tmp_path, "http.py", "requests.get(url, verify=False)\n")
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R007" for f in findings)

    def test_R008_md5(self, tmp_path: Path):
        write_file(tmp_path, "auth.py", "h = hashlib.md5(password.encode()).hexdigest()\n")
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R008" for f in findings)

    def test_R009_debug_true(self, tmp_path: Path):
        write_file(tmp_path, "settings.py", "DEBUG = True\ndebug=True\n")
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R009" for f in findings)

    def test_R010_cors_star(self, tmp_path: Path):
        write_file(tmp_path, "main.py", 'allow_origins=["*"]\n')
        findings, _ = scan_files([str(tmp_path)])
        assert any(f["rule_id"] == "R010" for f in findings)


# ---------------------------------------------------------------------------
# No false positives on safe text
# ---------------------------------------------------------------------------

class TestNoFalsePositives:
    def test_safe_secret_env(self, tmp_path: Path):
        write_file(tmp_path, "cfg.py", 'api_key = os.environ.get("API_KEY")\n')
        findings, _ = scan_files([str(tmp_path)])
        assert not any(f["rule_id"] == "R001" for f in findings)

    def test_safe_yaml_loader(self, tmp_path: Path):
        write_file(tmp_path, "cfg.py", "cfg = yaml.load(stream, Loader=yaml.SafeLoader)\n")
        findings, _ = scan_files([str(tmp_path)])
        assert not any(f["rule_id"] == "R005" for f in findings)

    def test_safe_sha256(self, tmp_path: Path):
        write_file(tmp_path, "auth.py", "h = hashlib.sha256(data).hexdigest()\n")
        findings, _ = scan_files([str(tmp_path)])
        assert not any(f["rule_id"] == "R008" for f in findings)

    def test_completely_clean_file(self, tmp_path: Path):
        write_file(tmp_path, "util.py", "def add(a, b):\n    return a + b\n")
        findings, _ = scan_files([str(tmp_path)])
        assert findings == []


# ---------------------------------------------------------------------------
# Fingerprint stability
# ---------------------------------------------------------------------------

def test_fingerprint_is_deterministic():
    fp1 = _fingerprint("R001", "/path/to/file.py", "secret = 'abc123'")
    fp2 = _fingerprint("R001", "/path/to/file.py", "secret = 'abc123'")
    assert fp1 == fp2
    assert len(fp1) == 16


def test_fingerprint_differs_by_rule():
    fp1 = _fingerprint("R001", "/path/file.py", "same snippet")
    fp2 = _fingerprint("R002", "/path/file.py", "same snippet")
    assert fp1 != fp2


# ---------------------------------------------------------------------------
# Dedup — same pattern on same line yields one finding
# ---------------------------------------------------------------------------

def test_dedup_within_scan(tmp_path: Path):
    write_file(tmp_path, "a.py", "import pickle\ndata = pickle.load(f)\n")
    findings, files_count = scan_files([str(tmp_path)])
    r005 = [f for f in findings if f["rule_id"] == "R005"]
    assert len(r005) == 1
    assert files_count >= 1


# ---------------------------------------------------------------------------
# files_examined count
# ---------------------------------------------------------------------------

def test_files_examined(tmp_path: Path):
    write_file(tmp_path, "a.py", "x = 1\n")
    write_file(tmp_path, "b.py", "y = 2\n")
    _, count = scan_files([str(tmp_path)])
    assert count == 2


# ---------------------------------------------------------------------------
# Lang filtering — R002 should not fire on .py eval when lang excludes .txt
# ---------------------------------------------------------------------------

def test_lang_filter(tmp_path: Path):
    write_file(tmp_path, "notes.txt", "eval(bad_stuff)\n")
    findings, _ = scan_files([str(tmp_path)])
    # R002 is restricted to JS/TS/PY; .txt is not in CODE_EXTS for that rule
    # (actually .txt IS in CODE_EXTS but not in R002.langs — so it should NOT fire)
    assert not any(f["rule_id"] == "R002" for f in findings)


# ---------------------------------------------------------------------------
# Severity present and valid
# ---------------------------------------------------------------------------

def test_finding_has_required_fields(tmp_path: Path):
    write_file(tmp_path, "bad.py", "r = requests.get(url, verify=False)\n")
    findings, _ = scan_files([str(tmp_path)])
    assert findings
    f = findings[0]
    for key in ("category", "rule_id", "severity", "title", "file", "line", "snippet", "message"):
        assert key in f, f"missing key: {key}"
    assert f["severity"] in ("Critical", "High", "Medium", "Low")
    assert f["category"] == "sast"
