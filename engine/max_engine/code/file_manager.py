"""File manager for the Code tab.

All file operations are constrained to the workspace allowlist paths, which
prevents arbitrary filesystem access. Paths are normalised before comparison.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Extensions shown in the file tree (non-exhaustive; text-based files only).
_TEXT_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".toml", ".json", ".md",
    ".txt", ".yaml", ".yml", ".html", ".css", ".sh", ".cmd", ".ps1",
    ".env", ".gitignore", ".sql", ".csv", ".xml", ".ini", ".cfg",
}

# Directories always excluded from listing.
_SKIP_DIRS = {
    "node_modules", ".venv", "__pycache__", "target", ".git", ".pytest_cache",
    "dist", "build", ".next", ".nuxt", "coverage",
}

_MAX_FILE_BYTES = 500_000  # 500 KB ceiling to avoid huge binaries


@dataclass
class FileEntry:
    name: str
    path: str           # absolute path (forward slashes)
    is_dir: bool
    children: list["FileEntry"] = field(default_factory=list)


class FileManager:
    def __init__(self, allowlist: list[str]) -> None:
        self._roots: list[Path] = [Path(p).resolve() for p in allowlist]

    # ------------------------------------------------------------------
    # Access guard
    # ------------------------------------------------------------------

    def is_allowed(self, path: str) -> bool:
        """True when *path* is under at least one allowlisted root."""
        target = Path(path).resolve()
        return any(
            target == root or root in target.parents
            for root in self._roots
        )

    def _guard(self, path: str) -> Path:
        p = Path(path).resolve()
        if not self.is_allowed(str(p)):
            raise PermissionError(f"path not in workspace allowlist: {path!r}")
        return p

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    def list_root(self) -> list[FileEntry]:
        """Return the top-level entries for each allowlisted root."""
        entries: list[FileEntry] = []
        for root in self._roots:
            if root.exists() and root.is_dir():
                entries.append(FileEntry(
                    name=root.name or str(root),
                    path=root.as_posix(),
                    is_dir=True,
                ))
        return entries

    def list_dir(self, path: str) -> list[FileEntry]:
        """Return immediate children of *path* (files and dirs), filtered."""
        p = self._guard(path)
        if not p.is_dir():
            raise ValueError(f"not a directory: {path!r}")
        entries: list[FileEntry] = []
        try:
            children = sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
        except PermissionError:
            return entries
        for child in children:
            if child.name.startswith(".") and child.name not in {".env", ".gitignore"}:
                continue
            if child.is_dir() and child.name in _SKIP_DIRS:
                continue
            if child.is_file() and child.suffix.lower() not in _TEXT_EXTS:
                continue
            entries.append(FileEntry(
                name=child.name,
                path=child.as_posix(),
                is_dir=child.is_dir(),
            ))
        return entries

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> str:
        p = self._guard(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        size = p.stat().st_size
        if size > _MAX_FILE_BYTES:
            raise ValueError(f"file too large to edit ({size // 1024} KB)")
        return p.read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> None:
        p = self._guard(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Git helpers (best-effort; skip gracefully if git is unavailable)
    # ------------------------------------------------------------------

    def git_snapshot(self, paths: list[str]) -> str | None:
        """Create a git stash / snapshot of *paths* before applying edits.

        Returns the stash ref string on success, None if git is unavailable.
        """
        import subprocess
        repo = self._repo_root()
        if repo is None:
            return None
        try:
            # Stage the files and create a stash entry.
            subprocess.run(
                ["git", "stash", "push", "--include-untracked", "-m", "max-code-snapshot"],
                cwd=str(repo), capture_output=True, timeout=15, check=False,
            )
            result = subprocess.run(
                ["git", "stash", "list", "--format=%gd", "-n", "1"],
                cwd=str(repo), capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() or None
        except Exception:
            return None

    def git_rollback(self, stash_ref: str) -> bool:
        """Pop *stash_ref* to restore the pre-edit state."""
        import subprocess
        repo = self._repo_root()
        if repo is None:
            return False
        try:
            r = subprocess.run(
                ["git", "stash", "pop", stash_ref],
                cwd=str(repo), capture_output=True, timeout=30,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _repo_root(self) -> Path | None:
        import subprocess
        if not self._roots:
            return None
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(self._roots[0]), capture_output=True, text=True, timeout=5,
            )
            p = r.stdout.strip()
            return Path(p) if p else None
        except Exception:
            return None
