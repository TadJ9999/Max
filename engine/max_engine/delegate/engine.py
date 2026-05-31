"""Delegate engine — orchestrates parallel, isolated sessions.

Responsibilities:
* **Submit** tasks (one or many) — Manual (explicit provider) or Smart-Auto
  (decide local vs cloud by task complexity / local queue depth).
* **Schedule** respecting the 12 GB VRAM ceiling: heavy local models queue
  (``max_parallel_local``), while cloud + tiny tasks fan out (``max_parallel_cloud``).
* **Execute** each session against its provider, accumulating isolated output.
* **Cancel** a session; **promote** a queued session to cloud (manual override).

The provider builder is injectable for testing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..config import EngineConfig
from ..prompts import messages_for
from ..providers.base import Provider
from ..providers.factory import build_provider
from ..router import is_cloud_provider, model_for
from .coordinator import collect, parse_plan
from .scheduler import Scheduler
from .session import Session, SessionManager, SessionState

ProviderBuilder = Callable[[str, EngineConfig], Provider]


class DelegateEngine:
    def __init__(
        self,
        config: EngineConfig,
        provider_builder: ProviderBuilder = build_provider,
        manager: SessionManager | None = None,
        scheduler: Scheduler | None = None,
    ) -> None:
        self.config = config
        self.build_provider = provider_builder
        self.manager = manager or SessionManager()
        self.scheduler = scheduler or Scheduler(
            max_parallel_local=config.delegate.max_parallel_local,
            max_parallel_cloud=config.delegate.max_parallel_cloud,
        )
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # ---- submission -----------------------------------------------------

    def submit(
        self,
        task: str,
        action: str = "generate",
        provider: str | None = None,
        complexity: float = 0.5,
    ) -> Session:
        """Create a QUEUED session. ``provider=None`` => decide by delegate mode."""
        if provider is None:
            provider = self._choose_provider(complexity)

        is_cloud = is_cloud_provider(provider, self.config)
        if is_cloud and not self.config.allow_cloud:
            raise PermissionError("cloud routing requested but allow_cloud is off")

        model = model_for(provider, action, self.config)
        return self.manager.spawn(
            task=task, provider=provider, model=model, action=action, is_cloud=is_cloud
        )

    def _choose_provider(self, complexity: float) -> str:
        """Manual mode -> local default; Smart-Auto -> local vs cloud by complexity."""
        if self.config.delegate.mode != "smart-auto":
            return "ollama"
        local_queue = sum(
            1 for s in self.manager.list() if s.state == SessionState.QUEUED and not s.is_cloud
        )
        want_cloud = self.config.allow_cloud and Scheduler.prefer_cloud(complexity, local_queue)
        return "claude" if want_cloud else "ollama"

    def promote_to_cloud(self, session_id: str, provider: str = "claude") -> Session:
        """Manual override: move a still-queued session to a cloud provider."""
        s = self.manager.get(session_id)
        if s is None:
            raise KeyError(session_id)
        if s.state != SessionState.QUEUED:
            raise ValueError(f"session {session_id} is not queued (state={s.state.value})")
        if not self.config.allow_cloud:
            raise PermissionError("allow_cloud is off")
        s.provider = provider
        s.is_cloud = True
        s.model = model_for(provider, s.action, self.config)
        return s

    # ---- coordinator (auto-delegate) -----------------------------------

    def _planner_provider(self) -> str:
        """Pick the model that plans the breakdown. Prefer a strong cloud planner
        when cloud is enabled and we're in Smart-Auto; otherwise stay local."""
        if (
            self.config.delegate.mode == "smart-auto"
            and self.config.allow_cloud
            and is_cloud_provider("claude", self.config)
        ):
            return "claude"
        return "ollama"

    async def coordinate(
        self,
        request: str,
        planner: str | None = None,
        max_subtasks: int = 6,
    ) -> dict:
        """Decompose ``request`` into subtasks via a planner model, then submit
        each as a parallel session. Returns the plan + the created sessions."""
        provider = planner or self._planner_provider()
        # Never silently route the planner to the cloud when it's disabled.
        if is_cloud_provider(provider, self.config) and not self.config.allow_cloud:
            provider = "ollama"

        model = model_for(provider, "chat", self.config)
        planner_client = self.build_provider(provider, self.config)
        raw = await collect(planner_client.chat(model, messages_for("plan", request)))
        specs = parse_plan(raw, fallback_task=request, max_subtasks=max_subtasks)

        sessions = [
            self.submit(spec.task, action=spec.action, complexity=spec.complexity)
            for spec in specs
        ]
        await self.kick()
        return {
            "request": request,
            "planner": {"provider": provider, "model": model},
            "sessions": [s.to_dict() for s in sessions],
        }

    def cancel(self, session_id: str) -> None:
        self.manager.cancel(session_id)
        t = self._tasks.get(session_id)
        if t is not None:
            t.cancel()

    # ---- scheduling / execution ----------------------------------------

    async def kick(self) -> None:
        """Start as many queued sessions as capacity allows."""
        async with self._lock:
            running = [s for s in self.manager.list() if s.state == SessionState.RUNNING]
            for s in [x for x in self.manager.list() if x.state == SessionState.QUEUED]:
                if self.scheduler.has_capacity(s, running):
                    s.state = SessionState.RUNNING
                    self._tasks[s.id] = asyncio.create_task(self._run(s))
                    running.append(s)

    async def _run(self, s: Session) -> None:
        try:
            provider = self.build_provider(s.provider, self.config)
            messages = messages_for(s.action, s.task)
            async for chunk in provider.chat(s.model, messages):
                if s.state == SessionState.CANCELLED:
                    break
                s.emit(chunk.text)  # accumulates into output + streams live
            if s.state != SessionState.CANCELLED:
                s.state = SessionState.DONE
        except asyncio.CancelledError:
            s.state = SessionState.CANCELLED
            raise
        except Exception as e:  # isolate failures to the session
            s.state = SessionState.ERROR
            s.emit(f"[error] {type(e).__name__}: {e}")
            # Feed the error into Aegis capture (best-effort; import lazily to
            # avoid a circular-import at module load time).
            try:
                from max_engine.main import _aegis_capture  # type: ignore[import]
                _aegis_capture.tap_delegate_error(e, s.id, s.provider, s.model)
            except Exception:
                pass
        finally:
            self._tasks.pop(s.id, None)
            s.finish()  # notify live subscribers of the terminal state
            await self.kick()  # free capacity -> start the next queued session

    async def drain(self) -> None:
        """Await until no sessions are queued or running (mainly for tests)."""
        while True:
            tasks = list(self._tasks.values())
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                continue
            if any(s.state == SessionState.QUEUED for s in self.manager.list()):
                await self.kick()
                continue
            return
