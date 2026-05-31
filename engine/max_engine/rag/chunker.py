"""Workspace walking + chunking for codebase RAG.

Pure, dependency-free helpers (easy to test): decide which files are in scope,
read them, and split them into overlapping line-based chunks for embedding.

Scope is privacy-first: indexing only ever happens inside the user's configured
workspace allowlist (enforced by the service), and we skip the usual noise
(`.git`, `node_modules`, build output, virtualenvs) and non-text/huge files.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass

# Directories never worth indexing.
DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "target",
        ".next", ".nuxt", ".svelte-kit", "out", "coverage", ".idea", ".vscode",
        ".cache", ".turbo", "vendor", "Pods", ".gradle", "bin", "obj",
    }
)

# Extensions we treat as indexable text/code.
CODE_EXTS: frozenset[str] = frozenset(
    {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rs", ".go",
        ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".rb",
        ".php", ".swift", ".m", ".mm", ".scala", ".sh", ".bash", ".zsh", ".ps1",
        ".sql", ".html", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
        ".md", ".mdx", ".rst", ".txt", ".json", ".jsonc", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".env", ".lua", ".r", ".jl", ".dart", ".ex",
        ".exs", ".clj", ".gradle", ".tf", ".proto", ".graphql", ".dockerfile",
    }
)

MAX_FILE_BYTES = 1_000_000  # skip files larger than ~1 MB (generated/minified/data)


@dataclass(frozen=True)
class Chunk:
    text: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive


def is_indexable(path: str, *, max_bytes: int = MAX_FILE_BYTES) -> bool:
    """A regular text/code file, small enough, with a known code/text suffix."""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if ext not in CODE_EXTS and name.lower() not in ("dockerfile", "makefile"):
        return False
    try:
        return 0 < os.path.getsize(path) <= max_bytes
    except OSError:
        return False


def gather_files(
    roots: list[str],
    *,
    ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
    max_bytes: int = MAX_FILE_BYTES,
) -> Iterator[str]:
    """Yield absolute paths of indexable files under ``roots`` (recursively),
    pruning ignored directories. A root may be a single file too."""
    seen: set[str] = set()
    for root in roots:
        root = os.path.abspath(root)
        if os.path.isfile(root):
            if is_indexable(root, max_bytes=max_bytes) and root not in seen:
                seen.add(root)
                yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".")]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if is_indexable(p, max_bytes=max_bytes) and p not in seen:
                    seen.add(p)
                    yield p


def read_text(path: str) -> str | None:
    """Read a file as UTF-8 text; return None if it's binary/unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def file_hash(text: str) -> str:
    """Stable content hash used for incremental re-indexing."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, *, max_chars: int = 1200, overlap_lines: int = 8) -> list[Chunk]:
    """Split text into overlapping, line-aligned chunks.

    Chunks stay under ``max_chars`` where possible (a single over-long line is
    emitted whole), and consecutive chunks share ``overlap_lines`` for context
    continuity. Always makes forward progress.
    """
    lines = text.splitlines()
    n = len(lines)
    if n == 0:
        return []
    chunks: list[Chunk] = []
    i = 0
    while i < n:
        start = i
        size = 0
        while i < n and (i == start or size + len(lines[i]) + 1 <= max_chars):
            size += len(lines[i]) + 1
            i += 1
        end = i  # exclusive
        body = "\n".join(lines[start:end])
        if body.strip():
            chunks.append(Chunk(text=body, start_line=start + 1, end_line=end))
        if i >= n:
            break
        if overlap_lines > 0:
            i = max(end - overlap_lines, start + 1)  # step back for overlap, but progress
    return chunks
