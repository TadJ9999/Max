"""Aegis repair — turn a finding or runtime event into an applied code fix.

Unlike ``ScanService.fix_finding`` / ``AegisService.diagnose`` (which only stream
a *text proposal* containing a fragile ``git apply`` diff), this module asks the
model for the **complete new content** of each affected file — the same robust
pattern as ``code/planner.py`` — and writes those files directly.

Flow:
  1. ``propose_for_finding`` / ``propose_for_event`` (SSE async generators) gather
     the relevant file(s), ask Leo for whole-file rewrites, and stream a *plan*:
     ``{summary, log_id, patches:[{path, diff, new_content}]}`` where ``diff`` is a
     unified diff computed with :mod:`difflib` purely for human review.
  2. ``apply`` snapshots (git stash), writes ``new_content`` to disk, runs the
     ecosystem-aware verifier, then keeps the change or rolls it back.

Because apply writes ``new_content`` (not a diff) it cannot fail on context/line
mismatch, which is what made the old ``git apply`` path unreliable with local
Ollama models.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from ..config import EngineConfig
from ..providers.factory import build_provider
from ..rag.chunker import read_text
from ..router import model_for
from .redact import redact
from .scan_service import _fix_messages  # security framing reused for context
from .service import (
    _verify_for,
    _write_logbook,
)
from .store import AegisStore

log = logging.getLogger(__name__)

MAX_FILE_CHARS = 24000  # cap context per file so we don't blow the model window

_PLAN_CONTRACT = """
Return ONLY a valid JSON object (no prose, no markdown fences) of the form:
{
  "summary": "one-sentence description of the fix",
  "patches": [
    {
      "path": "<exact path of a file shown above>",
      "description": "what changes in this file and why it fixes the issue",
      "new_content": "<the COMPLETE updated file content>"
    }
  ]
}

Rules:
- Include ONLY files that must change to fix the issue.
- "path" MUST be one of the file paths shown above, copied verbatim.
- "new_content" MUST be the entire file after the change (not a diff, not a snippet).
- Preserve existing indentation, imports, and style. Make the minimal change.
- Do not output anything outside the JSON object.
"""


class RepairService:
    def __init__(
        self,
        store: AegisStore,
        config: EngineConfig,
        repo_root: str,
        apollo_store: Any | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._root = Path(repo_root)
        self._apollo_store = apollo_store

    # ---- propose: finding ----------------------------------------------

    async def propose_for_finding(self, finding_id: str) -> AsyncIterator[str]:
        finding = self._store.get_finding(finding_id)
        if finding is None:
            yield _sse({"error": {"message": "finding not found"}})
            return

        file_path = finding.get("file")
        if not file_path:
            yield _sse({"note": "This finding has no associated file to repair automatically."})
            yield "data: [DONE]\n\n"
            return

        content = read_text(file_path)
        if content is None:
            yield _sse({"note": f"Could not read {file_path} — repair manually."})
            yield "data: [DONE]\n\n"
            return

        # Reuse the SAST/SCA security framing from scan_service.
        framing = _fix_messages(finding, self._config.workspace_allowlist)[1]["content"]

        def make_log(root_cause: str, provider: str) -> str:
            log_id = self._store.append_log_for_finding(finding_id, {
                "status": "proposed",
                "severity": finding.get("severity"),
                "symptom": f"{finding.get('title', '')}: {finding.get('message', '')[:80]}",
                "root_cause": root_cause[:2000],
                "provider": provider,
            })
            self._store.stamp_finding_log(finding_id, log_id)
            return log_id

        async for evt in self._stream_plan(framing, [(file_path, content)], make_log):
            yield evt

    # ---- propose: runtime event ----------------------------------------

    async def propose_for_event(self, event_id: str) -> AsyncIterator[str]:
        event = self._store.get_event(event_id)
        if event is None:
            yield _sse({"error": {"message": "event not found"}})
            return

        files = self._event_target_files(event)
        if not files:
            yield _sse({"note": (
                "Could not locate an in-workspace source file from this error's "
                "traceback. Diagnose it manually, or add its directory to the "
                "workspace allowlist."
            )})
            yield "data: [DONE]\n\n"
            return

        context = json.dumps(
            {k: v for k, v in event.items() if k not in ("fingerprint", "context")},
            indent=2,
        )
        framing = (
            f"RUNTIME ERROR EVENT:\n```json\n{context}\n```\n\n"
            "Fix the root cause of this error in the file(s) shown below."
        )

        def make_log(root_cause: str, provider: str) -> str:
            return self._store.append_log({
                "event_id": event_id,
                "status": "proposed",
                "severity": event.get("severity"),
                "symptom": f"{event.get('kind')}: {event.get('message', '')[:80]}",
                "root_cause": root_cause[:2000],
                "provider": provider,
            })

        async for evt in self._stream_plan(framing, files, make_log):
            yield evt

    # ---- shared planner stream -----------------------------------------

    async def _stream_plan(
        self,
        framing: str,
        files: list[tuple[str, str]],
        make_log: Callable[[str, str], str],
    ) -> AsyncIterator[str]:
        provider_name = _pick_provider(self._config)
        try:
            provider = build_provider(provider_name, self._config)
        except Exception as exc:
            yield _sse({"error": {"message": redact(str(exc))}})
            return
        model = model_for(provider_name, "chat", self._config)

        yield _sse({"status": "Reading affected files…"})

        context_block = "\n\n".join(
            f"=== {path} ===\n{content[:MAX_FILE_CHARS]}" for path, content in files
        )
        messages = [
            {"role": "system", "content": (
                "You are Leo, Max's security engineer. You repair vulnerabilities and "
                "bugs by rewriting whole files correctly." + _PLAN_CONTRACT
            )},
            {"role": "user", "content": f"{framing}\n\nFILES:\n{context_block}"},
        ]

        yield _sse({"status": f"Asking Leo to repair {len(files)} file(s)…"})

        accumulated = ""
        try:
            async for chunk in provider.chat(model, messages):
                accumulated += chunk.text
        except Exception as exc:
            yield _sse({"error": {"message": redact(str(exc))}})
            return

        data = _parse_plan_json(accumulated)
        if data is None:
            yield _sse({"error": {"message": "Leo did not return a usable repair plan."}})
            return

        # Build reviewable patches: keep only files we actually provided, attach a diff.
        known = {path: content for path, content in files}
        patches: list[dict] = []
        for p in data.get("patches", []):
            path = p.get("path", "")
            new_content = p.get("new_content")
            if path not in known or not isinstance(new_content, str):
                continue
            old = known[path]
            if new_content == old:
                continue
            patches.append({
                "path": path,
                "description": p.get("description", ""),
                "diff": _unified_diff(old, new_content, path),
                "new_content": new_content,
            })

        if not patches:
            yield _sse({"note": "Leo found nothing to change in the affected file(s)."})
            yield "data: [DONE]\n\n"
            return

        log_id = make_log(data.get("summary", ""), f"{provider_name}/{model}")
        yield _sse({"plan": {
            "summary": data.get("summary", ""),
            "log_id": log_id,
            "patches": patches,
        }})
        yield "data: [DONE]\n\n"

    # ---- apply ----------------------------------------------------------

    def apply(
        self,
        kind: str,
        identifier: str,
        patches: list[dict],
        log_id: str | None = None,
    ) -> dict:
        """Write whole files → verify → keep, or restore originals on failure.

        Rollback during apply is done from in-memory originals (not git stash),
        so it is correct even when the working tree was clean. The post-apply
        Rollback button uses :meth:`revert` (``git checkout``).
        """
        if not patches:
            return {"ok": False, "error": "no patches to apply"}

        rel_paths: list[str] = []
        targets: list[tuple[Path, str]] = []
        for p in patches:
            full = _resolve_in_root(p.get("path", ""), self._root)
            rel_paths.append(full.relative_to(self._root).as_posix())
            targets.append((full, p.get("new_content", "")))

        _check_path_allowlist(rel_paths, self._config.workspace_allowlist, self._root)

        # Snapshot original contents so we can restore exactly on failure.
        originals: dict[Path, str | None] = {
            full: (full.read_text(encoding="utf-8") if full.exists() else None)
            for full, _ in targets
        }

        try:
            for full, new_content in targets:
                full.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            _restore(originals)
            return {"ok": False, "error": f"write failed: {exc}"}

        ok, verify_out = _verify_for(self._root, rel_paths)
        if not ok:
            _restore(originals)
            if log_id:
                self._store.update_log_status(log_id, "rolled-back", verify_out)
            return {
                "ok": False,
                "error": f"verification failed (changes reverted): {verify_out}",
            }

        if log_id:
            self._store.update_log_status(log_id, "verified", verify_out)
        _write_logbook(self._root, identifier, f"{kind} repair applied+verified", verify_out)
        self._embed(identifier, "", "\n".join(rel_paths), "applied+verified")
        # ``snapshot`` carries the changed paths so the UI's Rollback can revert them.
        return {"ok": True, "verification": verify_out, "files": rel_paths, "snapshot": rel_paths}

    # ---- revert (post-apply Rollback) ----------------------------------

    def revert(self, paths: list[str], log_id: str | None = None) -> dict:
        """Undo a kept repair by restoring the given files from git HEAD."""
        import subprocess

        rels = [_resolve_in_root(p, self._root).relative_to(self._root).as_posix() for p in paths]
        result = subprocess.run(
            ["git", "checkout", "--", *rels],
            cwd=self._root, capture_output=True, text=True,
        )
        ok = result.returncode == 0
        if ok and log_id:
            self._store.update_log_status(log_id, "rolled-back")
        return {"ok": ok, "output": (result.stdout + result.stderr).strip()}

    # ---- helpers --------------------------------------------------------

    def _event_target_files(self, event: dict) -> list[tuple[str, str]]:
        """Pull source file paths out of an event traceback, scoped to the repo."""
        tb = event.get("traceback") or ""
        seen: list[str] = []
        for m in re.finditer(r'File "([^"]+)", line \d+', tb):
            path = m.group(1)
            if path not in seen:
                seen.append(path)

        allow = self._config.workspace_allowlist
        files: list[tuple[str, str]] = []
        for path in seen:
            try:
                full = _resolve_in_root(path, self._root)
            except PermissionError:
                continue
            rel = full.relative_to(self._root).as_posix()
            if allow and not _in_allowlist(rel, allow, self._root):
                continue
            content = read_text(str(full))
            if content is not None:
                files.append((str(full), content))
            if len(files) >= 3:  # cap context
                break
        return files

    def _embed(self, identifier: str, diagnosis: str, files: str, status: str) -> None:
        if self._apollo_store is None:
            return
        try:
            self._apollo_store.upsert(
                text=(
                    f"Aegis repair [{status}] for {identifier}:\n"
                    f"Files: {files}\n{diagnosis[:800]}"
                ),
                source="aegis_repair",
                metadata={"id": identifier, "status": status},
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _restore(originals: dict[Path, str | None]) -> None:
    """Put files back to their captured pre-apply state (delete if they were new)."""
    for full, content in originals.items():
        try:
            if content is None:
                full.unlink(missing_ok=True)
            else:
                full.write_text(content, encoding="utf-8")
        except OSError:
            pass


def _pick_provider(config: EngineConfig) -> str:
    return (
        "claude"
        if config.allow_cloud and os.environ.get("ANTHROPIC_API_KEY")
        else "ollama"
    )


def _unified_diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))


def _parse_plan_json(text: str) -> dict | None:
    """Parse the planner JSON, tolerating markdown fences and surrounding prose."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        t = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # Fallback: grab the outermost {...} block.
    start, end = t.find("{"), t.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(t[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _resolve_in_root(path: str, root: Path) -> Path:
    """Resolve ``path`` (absolute or repo-relative) and ensure it stays inside root."""
    p = Path(path)
    full = (p if p.is_absolute() else root / p).resolve()
    root_resolved = root.resolve()
    if not str(full).startswith(str(root_resolved)):
        raise PermissionError(f"path escapes repo root: {path}")
    return full


def _in_allowlist(rel_path: str, allowlist: list[str], root: Path) -> bool:
    full = (root / rel_path).resolve()
    for a in allowlist:
        ap = Path(a)
        base = (ap if ap.is_absolute() else root / ap).resolve()
        if str(full).startswith(str(base)):
            return True
    return False


def _check_path_allowlist(paths: list[str], allowlist: list[str], root: Path) -> None:
    if not allowlist:
        return
    for rel in paths:
        if not _in_allowlist(rel, allowlist, root):
            raise PermissionError(f"path outside workspace allowlist: {rel}")
