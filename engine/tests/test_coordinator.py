"""Coordinator (auto-delegate): plan parsing + fan-out into parallel sessions."""

import asyncio

from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.config import DelegateConfig, EngineConfig
from max_engine.delegate.coordinator import VALID_ACTIONS, SubtaskSpec, parse_plan
from max_engine.delegate.engine import DelegateEngine
from max_engine.delegate.session import SessionState
from max_engine.providers.base import ChatChunk, Provider

PLAN_JSON = (
    '[{"task": "write the parser", "action": "generate", "complexity": 0.7},'
    ' {"task": "document it", "action": "summarize", "complexity": 0.2}]'
)


class PlannerProvider(Provider):
    """Yields a canned planner response, then behaves as a worker for subtasks."""

    name = "ollama"
    kind = "local"

    def __init__(self, plan_text: str = PLAN_JSON):
        self._plan_text = plan_text

    async def chat(self, model, messages, **params):
        system = messages[0]["content"] if messages else ""
        if "planning coordinator" in system:  # the planner prompt
            yield ChatChunk(text=self._plan_text)
        else:  # a worker subtask
            yield ChatChunk(text=f"done:{messages[-1]['content'][:12]}")
        yield ChatChunk(text="", done=True)


def _engine(plan_text: str = PLAN_JSON, mode: str = "manual") -> DelegateEngine:
    cfg = EngineConfig(delegate=DelegateConfig(mode=mode, max_parallel_local=4))
    return DelegateEngine(cfg, provider_builder=lambda *_a, **_k: PlannerProvider(plan_text))


# ---- plan parsing ------------------------------------------------------


def test_parse_plain_json_array():
    specs = parse_plan(PLAN_JSON, fallback_task="x")
    assert [s.task for s in specs] == ["write the parser", "document it"]
    assert specs[0].action == "generate" and specs[0].complexity == 0.7


def test_parse_strips_code_fences_and_prose():
    text = 'Sure! Here is the plan:\n```json\n[{"task": "do a thing"}]\n```\nHope that helps.'
    specs = parse_plan(text, fallback_task="x")
    assert len(specs) == 1
    assert specs[0].task == "do a thing"
    assert specs[0].action == "generate"  # defaulted


def test_parse_clamps_and_defaults_bad_fields():
    text = '[{"task": "a", "action": "bogus", "complexity": 5}, {"task": "  ", "action": "fix"}]'
    specs = parse_plan(text, fallback_task="x")
    assert len(specs) == 1  # blank-task item dropped
    assert specs[0].action == "generate"  # invalid action -> default
    assert specs[0].complexity == 1.0  # clamped from 5


def test_parse_falls_back_to_single_task_on_garbage():
    specs = parse_plan("the model rambled with no json at all", fallback_task="ORIGINAL")
    assert specs == [SubtaskSpec(task="ORIGINAL", action="generate", complexity=0.5)]


def test_parse_respects_max_subtasks():
    big = "[" + ",".join(f'{{"task": "t{i}"}}' for i in range(20)) + "]"
    specs = parse_plan(big, fallback_task="x", max_subtasks=3)
    assert len(specs) == 3


def test_valid_actions_match_prompt():
    assert VALID_ACTIONS == ("generate", "summarize", "fix", "chat")


# ---- end-to-end fan-out ------------------------------------------------


def test_coordinate_fans_out_and_runs_all_subtasks():
    async def run():
        eng = _engine()
        result = await eng.coordinate("build a date parser with docs")
        await eng.drain()
        return eng, result

    eng, result = asyncio.run(run())
    assert result["planner"]["provider"] == "ollama"
    assert len(result["sessions"]) == 2
    sessions = eng.manager.list()
    assert len(sessions) == 2
    assert all(s.state is SessionState.DONE for s in sessions)
    assert all(s.output.startswith("done:") for s in sessions)


def test_coordinate_planner_stays_local_when_cloud_off():
    cfg = EngineConfig(delegate=DelegateConfig(mode="smart-auto"), allow_cloud=False)
    eng = DelegateEngine(cfg, provider_builder=lambda *_a, **_k: PlannerProvider())
    # planner asked for cloud explicitly, but cloud is off -> falls back to local
    result = asyncio.run(eng.coordinate("x", planner="claude"))
    assert result["planner"]["provider"] == "ollama"


# ---- endpoint ----------------------------------------------------------


def test_coordinate_endpoint(monkeypatch):
    monkeypatch.setattr(
        m.delegate, "build_provider", lambda *_a, **_k: PlannerProvider(), raising=False
    )
    r = TestClient(m.app).post(
        "/sessions/coordinate", json={"request": "build a parser and document it"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["request"] == "build a parser and document it"
    assert len(body["sessions"]) == 2
    assert {s["action"] for s in body["sessions"]} == {"generate", "summarize"}
