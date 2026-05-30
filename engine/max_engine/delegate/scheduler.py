"""VRAM-aware scheduler.

The 12 GB VRAM ceiling means only a limited number of heavy *local* models can
run at once, while *cloud* and tiny-local tasks can fan out freely. Smart-Auto
mode routes by task complexity; users can also manually push a queued task to
cloud when local is backed up.

This is the policy skeleton; the async run-loop is wired in Phase 4.
"""

from __future__ import annotations

from .session import Session


class Scheduler:
    def __init__(self, max_parallel_local: int = 1, max_parallel_cloud: int = 8) -> None:
        self.max_parallel_local = max_parallel_local
        self.max_parallel_cloud = max_parallel_cloud

    def has_capacity(self, session: Session, running: list[Session]) -> bool:
        """Can ``session`` start now given what's already running?"""
        if session.is_cloud:
            running_cloud = sum(1 for s in running if s.is_cloud)
            return running_cloud < self.max_parallel_cloud
        running_local = sum(1 for s in running if not s.is_cloud)
        return running_local < self.max_parallel_local

    @staticmethod
    def prefer_cloud(complexity: float, local_queue_depth: int) -> bool:
        """Smart-Auto hint: send complex tasks (or deep local queues) to cloud.

        ``complexity`` is a 0..1 estimate. Tunable in Phase 4.
        """
        return complexity >= 0.7 or local_queue_depth >= 3
