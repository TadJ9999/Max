"""Aegis service — diagnosis, apply, rollback, logbook.

Wires together the store, the provider router, and git-based apply/rollback.
``diagnose`` is an async generator that yields SSE-compatible JSON strings so
``main.py`` can wrap it in a plain ``StreamingResponse``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any  # noqa: F401 — used in type hint above

from ..config import EngineConfig
from ..providers.factory import build_provider
from ..router import model_for
from .redact import redact
from .store import AegisStore


class AegisService:
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
        self._apollo_store = apollo_store  # optional: embed fix records into Apollo memory

    @property
    def store(self) -> AegisStore:
        return self._store

    # ---- events ---------------------------------------------------------

    def get_events(self, limit: int = 50) -> list[dict]:
        return self._store.list_events(limit=limit)

    # ---- diagnose (SSE generator) ---------------------------------------

    async def diagnose(self, event_id: str) -> AsyncIterator[str]:
        event = self._store.get_event(event_id)
        if event is None:
            yield f"data: {json.dumps({'error': {'message': 'event not found'}})}\n\n"
            return

        provider_name = (
            "claude"
            if self._config.allow_cloud and os.environ.get("ANTHROPIC_API_KEY")
            else "ollama"
        )
        try:
            provider = build_provider(provider_name, self._config)
        except Exception as e:
            yield f"data: {json.dumps({'error': {'message': str(e)}})}\n\n"
            return

        model = model_for(provider_name, "chat", self._config)
        messages = _aegis_messages(event, self._config.workspace_allowlist)

        parts: list[str] = []
        try:
            async for chunk in provider.chat(model, messages):
                parts.append(chunk.text)
                delta = {"content": chunk.text} if chunk.text else {}
                payload = {
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": "stop" if chunk.done else None}],
                }
                yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"
            # Record a proposed log entry
            self._store.append_log({
                "event_id": event_id,
                "status": "proposed",
                "severity": event.get("severity"),
                "symptom": f"{event.get('kind')}: {event.get('message', '')[:80]}",
                "root_cause": "".join(parts)[:2000],
                "provider": f"{provider_name}/{model}",
            })
        except Exception as e:
            err = {"error": {"message": redact(str(e)), "type": type(e).__name__}}
            yield f"data: {json.dumps(err)}\n\n"

    # ---- auto diagnose-and-apply (autonomy=auto) -------------------------

    async def auto_diagnose_and_apply(self, event_id: str) -> AsyncIterator[str]:
        """Full pipeline: diagnose → extract diff → apply → verify.

        Only runs when ``config.aegis.autonomy == "auto"``. Yields SSE JSON
        status messages so the client can follow progress. Logged as "auto-applied"
        or "auto-rolled-back" in selfdiagnosefixes.md.
        """
        if self._config.aegis.autonomy != "auto":
            yield f"data: {json.dumps({'error': {'message': 'autonomy is not set to auto; cannot auto-apply'}})}\n\n"
            return

        # Step 1: diagnose
        diagnosis_parts: list[str] = []
        yield f"data: {json.dumps({'status': 'diagnosing'})}\n\n"
        async for chunk in self.diagnose(event_id):
            if chunk == "data: [DONE]\n\n":
                break
            diagnosis_parts.append(chunk)
            yield chunk

        diagnosis_text = "".join(
            part.split("content\":\"")[-1].split("\"")[0]
            for part in diagnosis_parts
            if "content" in part
        )

        # Step 2: extract unified diff
        diff = _extract_diff_from_diagnosis(diagnosis_text)
        if not diff:
            yield f"data: {json.dumps({'status': 'no_diff', 'detail': 'No patchable diff found in diagnosis — nothing applied.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Step 3: apply
        yield f"data: {json.dumps({'status': 'applying', 'diff_lines': diff.count(chr(10))})}\n\n"
        result = self.apply(event_id, diff)
        if result.get("ok"):
            yield f"data: {json.dumps({'status': 'applied', 'verification': result.get('verification', '')})}\n\n"
            self._embed_fix_into_apollo(event_id, diagnosis_text, diff, "auto-applied")
        else:
            yield f"data: {json.dumps({'status': 'failed', 'error': result.get('error', '')})}\n\n"
        yield "data: [DONE]\n\n"

    def _embed_fix_into_apollo(
        self, event_id: str, diagnosis: str, diff: str, status: str
    ) -> None:
        """Embed a fix record into Apollo memory so recurrences are recognized."""
        if self._apollo_store is None:
            return
        try:
            text = (
                f"Aegis fix [{status}] for event {event_id}:\n\n"
                f"Diagnosis:\n{diagnosis[:1000]}\n\n"
                f"Patch applied:\n{diff[:800]}"
            )
            self._apollo_store.upsert(
                text=text,
                source="aegis_fix",
                metadata={"event_id": event_id, "status": status},
            )
        except Exception:
            pass

    # ---- apply ----------------------------------------------------------

    def apply(self, event_id: str, diff: str, log_id: str | None = None) -> dict:
        """Snapshot → validate → apply diff → verify → keep or rollback."""
        # Guard: all paths in the diff must be inside workspace_allowlist
        _check_allowlist(diff, self._config.workspace_allowlist, self._root)

        # Snapshot (git stash)
        snapshot = _git_stash(self._root)

        # Write diff to temp file and apply
        with tempfile.NamedTemporaryFile(suffix=".patch", mode="w", delete=False) as f:
            f.write(diff)
            patch_path = f.name
        try:
            result = subprocess.run(
                ["git", "apply", "--check", patch_path],
                cwd=self._root, capture_output=True, text=True,
            )
            if result.returncode != 0:
                _git_unstash(self._root, snapshot)
                return {"ok": False, "error": f"patch check failed: {result.stderr.strip()}"}

            subprocess.run(["git", "apply", patch_path], cwd=self._root, check=True)
        except subprocess.CalledProcessError as e:
            _git_unstash(self._root, snapshot)
            return {"ok": False, "error": str(e)}
        finally:
            os.unlink(patch_path)

        # Verify — ecosystem-aware based on which files the patch touched
        changed_paths = _extract_diff_paths(diff)
        ok, verify_out = _verify_for(self._root, changed_paths)
        if not ok:
            _git_unstash(self._root, snapshot)
            if log_id:
                self._store.update_log_status(log_id, "rolled-back", verify_out)
            return {"ok": False, "error": f"verification failed: {verify_out}", "snapshot": snapshot}

        # Drop the stash (keep changes)
        if snapshot:
            subprocess.run(["git", "stash", "drop"], cwd=self._root, capture_output=True)

        if log_id:
            self._store.update_log_status(log_id, "verified", verify_out)
        _write_logbook(self._root, event_id, "applied+verified", verify_out)
        # Embed the fix into Apollo memory for future pattern recognition
        self._embed_fix_into_apollo(event_id, "", diff, "applied+verified")
        return {"ok": True, "verification": verify_out}

    # ---- rollback -------------------------------------------------------

    def rollback(self, snapshot_ref: str, log_id: str | None = None) -> dict:
        result = subprocess.run(
            ["git", "stash", "pop"],
            cwd=self._root, capture_output=True, text=True,
        )
        ok = result.returncode == 0
        if log_id:
            self._store.update_log_status(log_id, "rolled-back")
        if ok:
            _write_logbook(self._root, None, "rolled-back", snapshot_ref)
        return {"ok": ok, "output": result.stdout + result.stderr}

    # ---- log ------------------------------------------------------------

    def get_log(self, limit: int = 100) -> list[dict]:
        return self._store.list_log(limit=limit)

    # ---- sources --------------------------------------------------------

    def sources(self) -> dict:
        provider_name = (
            "claude"
            if self._config.allow_cloud and os.environ.get("ANTHROPIC_API_KEY")
            else "ollama"
        )
        return {
            "provider": provider_name,
            "autonomy": self._config.aegis.autonomy,
            "cooldown_seconds": self._config.aegis.cooldown_seconds,
            "db_path": self._store.path,
            "cloud_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "workspace_allowlist": self._config.workspace_allowlist,
        }


# ---- helpers ------------------------------------------------------------

def _aegis_messages(event: dict, allowlist: list[str]) -> list[dict]:
    from ..prompts import SYSTEM_PROMPTS
    context_str = json.dumps({k: v for k, v in event.items() if k != "fingerprint"}, indent=2)
    allowlist_str = "\n".join(allowlist) if allowlist else "(none configured)"
    user_content = (
        f"ERROR EVENT:\n```json\n{context_str}\n```\n\n"
        f"WORKSPACE ALLOWLIST (you may only suggest edits to files inside these paths):\n"
        f"{allowlist_str}\n\n"
        "Diagnose this error. Provide:\n"
        "1. **Root cause** — plain English\n"
        "2. **Severity** — Critical / High / Medium / Low\n"
        "3. **Affected files** — allowlist-scoped paths only\n"
        "4. **Fix** — a unified diff ready to apply\n"
        "5. **Verification** — the command to confirm the fix\n\n"
        "If the workspace allowlist is empty or the fix requires editing files outside it, "
        "explain what to do but skip the diff."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPTS.get("aegis", SYSTEM_PROMPTS["chat"])},
        {"role": "user", "content": user_content},
    ]


def _check_allowlist(diff: str, allowlist: list[str], root: Path) -> None:
    if not allowlist:
        return
    for line in diff.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            path_part = line[4:].strip()
            if path_part.startswith("b/"):
                path_part = path_part[2:]
            if path_part == "/dev/null":
                continue
            full = (root / path_part).resolve()
            if not any(str(full).startswith(str(Path(a).resolve())) for a in allowlist):
                raise PermissionError(f"diff touches path outside allowlist: {path_part}")


def _git_stash(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "stash", "push", "-m", "aegis-snapshot"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode == 0 and "No local changes" not in result.stdout:
        return "stash"
    return None


def _git_unstash(root: Path, snapshot: str | None) -> None:
    if snapshot:
        subprocess.run(["git", "stash", "pop"], cwd=root, capture_output=True)


def _extract_diff_paths(diff: str) -> list[str]:
    """Return the list of file paths touched by a unified diff."""
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            part = line[4:].strip()
            if part.startswith("b/"):
                part = part[2:]
            if part != "/dev/null":
                paths.append(part)
    return paths


def _verify(root: Path) -> tuple[bool, str]:
    engine_dir = root / "engine"
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-q", "--tb=short", "-x"],
        cwd=engine_dir, capture_output=True, text=True, timeout=120,
    )
    out = (result.stdout + result.stderr).strip()[-2000:]
    return result.returncode == 0, out


def _verify_for(root: Path, changed_paths: list[str]) -> tuple[bool, str]:
    """Dispatch verification based on which files the diff touched."""
    import shutil

    normalized = [p.replace("\\", "/") for p in changed_paths]
    has_py = any(
        p.endswith(".py") or p.startswith("engine/") for p in normalized
    )
    has_js_ts = any(
        any(p.endswith(ext) for ext in (".js", ".ts", ".jsx", ".tsx", ".mjs"))
        or "package" in p
        for p in normalized
    )
    has_rust = any(
        p.endswith(".rs") or "Cargo." in p for p in normalized
    )

    if has_py or not changed_paths:
        # Default: run pytest (existing behaviour)
        return _verify(root)

    if has_js_ts:
        if shutil.which("npx"):
            app_dir = root / "app"
            result = subprocess.run(
                ["npx", "tsc", "--noEmit"],
                cwd=app_dir, capture_output=True, text=True, timeout=120,
            )
            out = (result.stdout + result.stderr).strip()[-2000:]
            return result.returncode == 0, out
        return True, "applied — needs manual verify (npx not found)"

    if has_rust:
        if shutil.which("cargo"):
            tauri_dir = root / "app" / "src-tauri"
            result = subprocess.run(
                ["cargo", "check"],
                cwd=tauri_dir, capture_output=True, text=True, timeout=120,
            )
            out = (result.stdout + result.stderr).strip()[-2000:]
            return result.returncode == 0, out
        return True, "applied — needs manual verify (cargo not found)"

    # Fallback
    return _verify(root)


def _write_logbook(root: Path, event_id: str | None, status: str, detail: str) -> None:
    from datetime import datetime, timezone
    logbook = root / "selfdiagnosefixes.md"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    entry = f"\n## {ts} — {event_id or 'rollback'}\n- **Status:** {status}\n- **Detail:** {detail[:500]}\n"
    try:
        with open(logbook, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        pass


def _extract_diff_from_diagnosis(text: str) -> str:
    """Pull the first unified diff block (```diff ... ```) out of an AI response."""
    import re
    m = re.search(r"```diff\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: look for diff header lines
    lines = text.splitlines()
    diff_lines: list[str] = []
    in_diff = False
    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@ "):
            in_diff = True
        if in_diff:
            diff_lines.append(line)
            if line.startswith("```") and diff_lines:
                break
    return "\n".join(diff_lines) if len(diff_lines) > 3 else ""
