"""Aegis capture layer — hooks that funnel errors into the event store.

``AegisCapture`` provides:
- ``fastapi_handler`` — register as ``@app.exception_handler(Exception)``
- ``tap_delegate_error`` — call from the delegate's except-block
- ``ingest_report`` — called by ``POST /aegis/report`` (frontend / Rust errors)
"""

from __future__ import annotations

import traceback as tb
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse

from .redact import redact
from .store import AegisStore

if TYPE_CHECKING:
    from .service import AegisService


class AegisCapture:
    def __init__(self, store: AegisStore) -> None:
        self._store = store

    # ---- FastAPI exception handler --------------------------------------

    async def fastapi_handler(self, request: Request, exc: Exception) -> JSONResponse:
        """Register with: ``app.add_exception_handler(Exception, capture.fastapi_handler)``"""
        self._ingest_exc(exc, source="engine", context={"path": request.url.path})
        return JSONResponse(
            status_code=500,
            content={"error": {"type": type(exc).__name__, "message": redact(str(exc))}},
        )

    # ---- delegate tap --------------------------------------------------

    def tap_delegate_error(self, exc: Exception, session_id: str, provider: str, model: str) -> None:
        """Call from DelegateEngine._run() except block."""
        self._ingest_exc(
            exc,
            source="delegate",
            context={"session_id": session_id, "provider": provider, "model": model},
        )

    # ---- client / Rust push --------------------------------------------

    def ingest_report(self, payload: dict) -> str:
        """Accept an error event from the frontend or Rust layer."""
        message = redact(str(payload.get("message", "")))
        trace = payload.get("traceback")
        if trace:
            trace = redact(str(trace))
        return self._store.ingest({
            "source": payload.get("source", "frontend"),
            "severity": payload.get("severity", "Medium"),
            "kind": payload.get("kind", "ClientError"),
            "message": message,
            "traceback": trace,
            "context": payload.get("context") or {},
        })

    # ---- internal -------------------------------------------------------

    def _ingest_exc(self, exc: Exception, *, source: str, context: dict) -> str:
        raw_msg = str(exc)
        raw_tb = tb.format_exc()
        return self._store.ingest({
            "source": source,
            "severity": _severity(exc),
            "kind": type(exc).__name__,
            "message": redact(raw_msg),
            "traceback": redact(raw_tb) if raw_tb.strip() != "NoneType: None" else None,
            "context": context,
        })


def _severity(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if any(k in name for k in ("memory", "overflow", "fatal", "system")):
        return "Critical"
    if any(k in name for k in ("runtime", "os", "io", "connection", "timeout")):
        return "High"
    if any(k in name for k in ("value", "type", "key", "attribute", "index")):
        return "Medium"
    return "Low"
