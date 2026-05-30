"""Sessions — one isolated task bound to a provider+model.

Sessions are isolated (each result viewed separately, per the design). The
manager spawns / tracks / cancels them; concurrency is governed by the
:class:`~max_engine.delegate.scheduler.Scheduler`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class SessionState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class Session:
    task: str
    provider: str
    model: str
    is_cloud: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    state: SessionState = SessionState.QUEUED
    output: str = ""


class SessionManager:
    """Tracks all sessions. Spawn/cancel/list. (Execution wired in Phase 4.)"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def spawn(self, task: str, provider: str, model: str, is_cloud: bool = False) -> Session:
        s = Session(task=task, provider=provider, model=model, is_cloud=is_cloud)
        self._sessions[s.id] = s
        return s

    def cancel(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s and s.state in (SessionState.QUEUED, SessionState.RUNNING):
            s.state = SessionState.CANCELLED

    def list(self) -> list[Session]:
        return list(self._sessions.values())
