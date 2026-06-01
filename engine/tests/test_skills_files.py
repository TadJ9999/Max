"""Tests for files skill — list, read, search, write, allowlist enforcement."""

import os
from pathlib import Path

import pytest

from max_engine.skills.files import FilesService


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello():\n    print('hello world')\n")
    (tmp_path / "src" / "utils.py").write_text("import os\n\ndef get_env(key):\n    return os.environ.get(key)\n")
    (tmp_path / "README.md").write_text("# Project\n\nDescription here.\n")
    return tmp_path


@pytest.fixture
def svc(workspace):
    return FilesService([str(workspace)])


def test_list_dir_root(svc, workspace):
    entries = svc.list_dir(str(workspace))
    names = [e["name"] for e in entries]
    assert "src" in names
    assert "README.md" in names


def test_list_dir_subdir(svc, workspace):
    entries = svc.list_dir(str(workspace / "src"))
    names = [e["name"] for e in entries]
    assert "main.py" in names
    assert "utils.py" in names


def test_list_dir_outside_allowlist(svc, tmp_path):
    other = tmp_path.parent / "other_dir"
    other.mkdir(exist_ok=True)
    with pytest.raises(PermissionError):
        svc.list_dir(str(other))


def test_read_file(svc, workspace):
    content = svc.read_file(str(workspace / "src" / "main.py"))
    assert "def hello" in content
    assert "print" in content


def test_read_file_outside_allowlist(svc, tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret")
    with pytest.raises(PermissionError):
        svc.read_file(str(outside))


def test_read_missing_file(svc, workspace):
    with pytest.raises(FileNotFoundError):
        svc.read_file(str(workspace / "nonexistent.py"))


def test_search_content_finds_matches(svc, workspace):
    hits = svc.search_content("hello", str(workspace))
    assert any("hello" in h["text"].lower() for h in hits)
    assert all("file" in h for h in hits)
    assert all("line" in h for h in hits)


def test_search_content_case_insensitive(svc, workspace):
    hits = svc.search_content("HELLO", str(workspace))
    assert len(hits) > 0


def test_search_content_case_sensitive_no_match(svc, workspace):
    hits = svc.search_content("HELLO", str(workspace), case_sensitive=True)
    assert len(hits) == 0


def test_search_outside_allowlist(svc, tmp_path):
    with pytest.raises(PermissionError):
        svc.search_content("x", str(tmp_path.parent / "outside"))


def test_write_file(svc, workspace):
    target = str(workspace / "new_file.txt")
    result = svc.write_file(target, "hello content")
    assert result["bytes_written"] == len("hello content".encode())
    assert Path(target).read_text() == "hello content"


def test_write_file_outside_allowlist(svc, tmp_path):
    outside = str(tmp_path.parent / "evil.txt")
    with pytest.raises(PermissionError):
        svc.write_file(outside, "bad")


def test_write_preview(svc, workspace):
    target = str(workspace / "preview.txt")
    result = svc.write_preview(target, "preview content")
    assert result["exists"] is False
    assert "preview content" in result["preview"]
    assert not Path(target).exists()


def test_empty_allowlist_blocks_all():
    svc = FilesService([])
    with pytest.raises(PermissionError):
        svc.list_dir("/")
    with pytest.raises(PermissionError):
        svc.read_file("/etc/passwd")
