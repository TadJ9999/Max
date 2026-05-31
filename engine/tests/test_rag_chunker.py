"""Chunker / file-walk tests (pure, no embeddings)."""

import os

from max_engine.rag.chunker import (
    chunk_text,
    file_hash,
    gather_files,
    is_indexable,
)


def test_is_indexable_by_extension_and_size(tmp_path):
    py = tmp_path / "a.py"
    py.write_text("print(1)\n")
    png = tmp_path / "img.png"
    png.write_bytes(b"\x89PNG\r\n")
    assert is_indexable(str(py))
    assert not is_indexable(str(png))  # binary extension
    assert not is_indexable(str(tmp_path / "missing.py"))  # doesn't exist
    big = tmp_path / "big.py"
    big.write_text("x" * 50)
    assert not is_indexable(str(big), max_bytes=10)  # too large


def test_gather_files_prunes_noise_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("a = 1\n")
    (tmp_path / "src" / "ui.ts").write_text("export const x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("module.exports = 1\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")

    found = {os.path.basename(p) for p in gather_files([str(tmp_path)])}
    assert found == {"main.py", "ui.ts"}  # noise dirs + binary pruned


def test_gather_files_accepts_single_file(tmp_path):
    f = tmp_path / "solo.py"
    f.write_text("x = 1\n")
    assert [os.path.basename(p) for p in gather_files([str(f)])] == ["solo.py"]


def test_chunk_text_splits_with_overlap_and_line_numbers():
    text = "\n".join(f"line {i}" for i in range(1, 41))  # 40 short lines
    chunks = chunk_text(text, max_chars=60, overlap_lines=2)
    assert len(chunks) > 1
    assert chunks[0].start_line == 1
    # consecutive chunks overlap (next starts before previous ends)
    assert chunks[1].start_line <= chunks[0].end_line
    # coverage reaches the last line
    assert chunks[-1].end_line == 40


def test_chunk_text_handles_overlong_single_line_and_empty():
    one = chunk_text("x" * 5000, max_chars=100)
    assert len(one) == 1 and one[0].start_line == 1
    assert chunk_text("") == []
    assert chunk_text("\n\n   \n") == []  # whitespace-only -> no chunks


def test_file_hash_is_stable_and_content_sensitive():
    assert file_hash("abc") == file_hash("abc")
    assert file_hash("abc") != file_hash("abd")
