"""Reports skill — AI-generated structured markdown reports, persisted to disk."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from ..capabilities.interface import Capability

_REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def _ensure_dir() -> Path:
    _REPORTS_DIR.mkdir(exist_ok=True)
    return _REPORTS_DIR


def _meta_path(report_id: str) -> Path:
    return _ensure_dir() / f"{report_id}.meta.json"


def _content_path(report_id: str) -> Path:
    return _ensure_dir() / f"{report_id}.md"


def _extract_title(markdown: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return m.group(1).strip() if m else fallback


class ReportService:
    def list_reports(self) -> list[dict]:
        out = []
        for path in sorted(_ensure_dir().glob("*.meta.json"), key=lambda p: -p.stat().st_mtime):
            try:
                meta = json.loads(path.read_text())
                out.append(meta)
            except Exception:
                pass
        return out

    def get_report(self, report_id: str) -> dict | None:
        meta_p = _meta_path(report_id)
        content_p = _content_path(report_id)
        if not meta_p.exists():
            return None
        meta = json.loads(meta_p.read_text())
        meta["content"] = content_p.read_text() if content_p.exists() else ""
        return meta

    def delete_report(self, report_id: str) -> bool:
        meta_p = _meta_path(report_id)
        content_p = _content_path(report_id)
        if not meta_p.exists():
            return False
        meta_p.unlink(missing_ok=True)
        content_p.unlink(missing_ok=True)
        return True

    async def generate_stream(
        self,
        title: str,
        instructions: str,
        provider,
        model: str,
    ) -> AsyncIterator[str]:
        from ..prompts import SYSTEM_PROMPTS, apply_persona
        from ..config import EngineConfig

        report_id = uuid.uuid4().hex
        system = SYSTEM_PROMPTS["report"]
        prompt = f"Write a report titled: **{title}**\n\nInstructions:\n{instructions}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        content_buf = ""
        async for chunk in provider.chat(model, messages, _feature="skills"):
            if not chunk.done:
                content_buf += chunk.text
                yield chunk.text

        # persist after generation completes
        if content_buf:
            derived_title = _extract_title(content_buf, title)
            _content_path(report_id).write_text(content_buf)
            meta = {
                "id": report_id,
                "title": derived_title,
                "created_at": int(time.time()),
                "word_count": len(content_buf.split()),
            }
            _meta_path(report_id).write_text(json.dumps(meta, indent=2))
            yield f"\n\n<!-- report_id:{report_id} -->"


class ReportCapability(Capability):
    name = "report"
    description = "Generate structured markdown reports on any topic."
    domains = ["report"]

    def __init__(self, service: ReportService, provider, model: str) -> None:
        self._svc = service
        self._provider = provider
        self._model = model

    async def invoke(self, query: str, context: dict | None = None) -> AsyncIterator[str]:
        title = (context or {}).get("title", query[:80])
        return self._svc.generate_stream(title, query, self._provider, self._model)

    def status(self) -> dict:
        reports = len(list(_ensure_dir().glob("*.meta.json"))) if _ensure_dir().exists() else 0
        return {"available": True, "connected": True, "reports_saved": reports}
