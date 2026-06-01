"""Files skill — read, search, and write local files within the workspace allowlist."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from ..capabilities.interface import Capability

_MAX_READ_BYTES = 512_000  # 512 KB safety cap


def _is_text_file(path: Path) -> bool:
    text_exts = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt",
        ".yaml", ".yml", ".toml", ".css", ".html", ".sh", ".ps1",
        ".env", ".gitignore", ".sql", ".rs", ".go", ".java", ".cpp",
        ".c", ".h", ".csv", ".ini", ".cfg", ".conf",
    }
    return path.suffix.lower() in text_exts or not path.suffix


class FilesService:
    def __init__(self, workspace_allowlist: list[str]) -> None:
        self._allowlist = [Path(p).resolve() for p in workspace_allowlist if p]

    def _is_allowed(self, path: Path) -> bool:
        resolved = path.resolve()
        if not self._allowlist:
            return False
        return any(
            resolved == base or base in resolved.parents
            for base in self._allowlist
        )

    def list_dir(self, path: str) -> list[dict]:
        p = Path(path).resolve()
        if not self._is_allowed(p):
            raise PermissionError(f"Path not in workspace allowlist: {path}")
        if not p.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        entries = []
        try:
            for entry in sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
                entries.append({
                    "name": entry.name,
                    "type": "file" if entry.is_file() else "dir",
                    "size": entry.stat().st_size if entry.is_file() else None,
                    "ext": entry.suffix.lower() if entry.is_file() else None,
                })
        except PermissionError:
            pass
        return entries

    def read_file(self, path: str) -> str:
        p = Path(path).resolve()
        if not self._is_allowed(p):
            raise PermissionError(f"Path not in workspace allowlist: {path}")
        if not p.is_file():
            raise FileNotFoundError(f"Not a file: {path}")
        raw = p.read_bytes()[:_MAX_READ_BYTES]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")

    def search_content(
        self,
        query: str,
        path: str | None = None,
        max_results: int = 50,
        case_sensitive: bool = False,
    ) -> list[dict]:
        base = Path(path).resolve() if path else None
        if base is None and self._allowlist:
            base = self._allowlist[0]
        if base is None:
            return []
        if not self._is_allowed(base):
            raise PermissionError(f"Path not in workspace allowlist: {path}")

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error:
            pattern = re.compile(re.escape(query), flags)

        results: list[dict] = []
        root = base if base.is_dir() else base.parent

        for dirpath, _dirs, files in os.walk(root):
            dp = Path(dirpath)
            if not self._is_allowed(dp):
                continue
            # skip noisy dirs
            _dirs[:] = [d for d in _dirs if d not in {
                ".git", "node_modules", "__pycache__", ".venv", "dist", "build",
            }]
            for fname in files:
                fp = dp / fname
                if not _is_text_file(fp):
                    continue
                try:
                    text = fp.read_bytes()[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        results.append({
                            "file": str(fp),
                            "line": i,
                            "text": line.rstrip()[:200],
                        })
                        if len(results) >= max_results:
                            return results
        return results

    def write_preview(self, path: str, content: str) -> dict:
        """Return a preview dict without writing."""
        p = Path(path).resolve()
        if not self._is_allowed(p):
            raise PermissionError(f"Path not in workspace allowlist: {path}")
        existing = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
        return {
            "path": str(p),
            "exists": p.exists(),
            "old_size": len(existing) if existing else 0,
            "new_size": len(content),
            "preview": content[:2000],
        }

    def write_file(self, path: str, content: str) -> dict:
        p = Path(path).resolve()
        if not self._is_allowed(p):
            raise PermissionError(f"Path not in workspace allowlist: {path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": str(p), "bytes_written": len(content.encode("utf-8"))}


class FilesCapability(Capability):
    name = "files"
    description = "Read, search, and write files within the workspace allowlist."
    domains = ["files"]

    def __init__(self, service: FilesService, provider, model: str) -> None:
        self._svc = service
        self._provider = provider
        self._model = model

    async def invoke(self, query: str, context: dict | None = None) -> AsyncIterator[str]:
        from ..prompts import skill_messages

        ctx = context or {}
        op = ctx.get("op", "search")
        if op == "read":
            try:
                content = self._svc.read_file(ctx["path"])
                yield content
            except Exception as e:
                yield f"Error: {e}"
            return
        if op == "search":
            try:
                hits = self._svc.search_content(query, ctx.get("path"))
                import json
                yield json.dumps(hits, indent=2)
            except Exception as e:
                yield f"Error: {e}"
            return
        # default: chat about the query using AI
        messages = skill_messages("", query, [])
        async for chunk in self._provider.chat(self._model, messages, _feature="skills"):
            if not chunk.done:
                yield chunk.text

    def status(self) -> dict:
        return {
            "available": True,
            "connected": True,
            "roots": [str(r) for r in self._svc._allowlist],
        }
