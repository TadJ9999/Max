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
from typing import Any

from ..config import EngineConfig
from ..providers.factory import build_provider
from ..router import model_for
from .redact import redact
from .store import AegisStore


class AegisService:
    def __init__(self, store: AegisStore, config: EngineConfig, repo_root: str) -> None:
        self._store = store
        self._config = config
        self._root = Path(repo_root)

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

        # Verify
        ok, verify_out = _verify(self._root)
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


def _verify(root: Path) -> tuple[bool, str]:
    engine_dir = root / "engine"
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-q", "--tb=short", "-x"],
        cwd=engine_dir, capture_output=True, text=True, timeout=120,
    )
    out = (result.stdout + result.stderr).strip()[-2000:]
    return result.returncode == 0, out


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
