"""Sessions — one isolated task bound to a provider+model.

Sessions are isolated (each result viewed separately, per the design). The
manager spawns / tracks / cancels them; concurrency is governed by the
:class:`~max_engine.delegate.scheduler.Scheduler`.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import Enum


class SessionState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


TERMINAL_STATES = (SessionState.DONE, SessionState.CANCELLED, SessionState.ERROR)


@dataclass
class Session:
    task: str
    provider: str
    model: str
    action: str = "generate"
    is_cloud: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    state: SessionState = SessionState.QUEUED
    output: str = ""
    # Live streaming: each open stream registers a queue; emit() fans out to all.
    _subscribers: list[asyncio.Queue] = field(
        default_factory=list, repr=False, compare=False
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "action": self.action,
            "provider": self.provider,
            "model": self.model,
            "is_cloud": self.is_cloud,
            "state": self.state.value,
            "output": self.output,
        }

    # ---- live output stream --------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Register a live-output queue. Call before the session runs to catch
        every chunk; mid-run subscribers replay ``output`` first (see the API)."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def emit(self, text: str) -> None:
        """Append a chunk to ``output`` and fan it out to live subscribers."""
        if not text:
            return
        self.output += text
        for q in list(self._subscribers):
            q.put_nowait({"type": "chunk", "text": text})

    def finish(self) -> None:
        """Signal terminal state to all live subscribers (called once, by the engine)."""
        for q in list(self._subscribers):
            q.put_nowait({"type": "done", "state": self.state.value})


class SessionManager:
    """Tracks all sessions. Spawn / get / cancel / list."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def spawn(
        self,
        task: str,
        provider: str,
        model: str,
        action: str = "generate",
        is_cloud: bool = False,
    ) -> Session:
        s = Session(task=task, provider=provider, model=model, action=action, is_cloud=is_cloud)
        self._sessions[s.id] = s
        return s

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def cancel(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s and s.state in (SessionState.QUEUED, SessionState.RUNNING):
            s.state = SessionState.CANCELLED

    def list(self) -> list[Session]:
        return list(self._sessions.values())
