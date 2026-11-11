"""Fakes that mirror the real Hermes plugin context closely enough to test without Hermes.

``FakeCtx`` follows ``hermes_cli.plugin_validate.RecordingContext`` and the real
``PluginContext`` signatures; anything the real context does not have raises
``AttributeError``. ``FakeLLM`` can be slow, raise, or answer badly on demand.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent))  # the repo folder *is* the ``bussola`` package

import bussola  # noqa: E402
from bussola.core import Bussola  # noqa: E402
from bussola.store import Store  # noqa: E402


@dataclass
class FakeOut:
    parsed: Any
    text: str = ""
    usage: dict = field(default_factory=lambda: {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150})
    content_type: str = "json"


class FakeLLM:
    """``responder(kwargs) -> dict | Exception | FakeOut``; ``delay`` seconds per call."""

    def __init__(self, responder: Optional[Callable[[dict], Any]] = None, delay: float = 0.0):
        self.responder = responder or (lambda kw: {"goal": 1, "confidence": 0.9, "continues_previous": False,
                                                   "closest_goal": 1, "summary60": "ok"})
        self.delay = delay
        self.calls: list[dict] = []

    def complete_structured(self, **kwargs: Any) -> FakeOut:
        assert isinstance(kwargs.get("input"), list), "Hermes needs input blocks, not a string"
        self.calls.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        answer = self.responder(kwargs)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, FakeOut):
            return answer
        return FakeOut(parsed=answer)


@dataclass
class FakeCron:
    job_id: str = "job1"
    job_name: str = "Bussola Friday run"
    execution_id: str = "exec-1"
    source: str = "scheduler"
    scheduled_instant: Optional[str] = None
    started_at: Optional[str] = None
    profile: str = "default"


class FakeCtx:
    plugin_id = "bussola"
    profile_name = "default"

    def __init__(self, llm: Optional[FakeLLM] = None, config: Optional[dict] = None):
        self.llm = llm or FakeLLM()
        self.config = dict(config or {})
        self.tools: dict[str, dict] = {}
        self.hooks: dict[str, Callable] = {}
        self.commands: dict[str, Callable] = {}
        self.aux_tasks: dict[str, dict] = {}
        self.blueprints: dict[str, dict] = {}
        self.unload: list[Callable] = []
        self.cron: Optional[FakeCron] = None
        self.choices: list[Optional[str]] = []
        self.asked: list[tuple[str, list]] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def current_cron_execution(self) -> Any:
        return self.cron

    def ask_choice(self, question: str, choices: list) -> Optional[str]:
        self.asked.append((question, choices))
        return self.choices.pop(0) if self.choices else None

    def register_tool(self, name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False,
                      description="", emoji="", override=False):
        assert schema["name"] == name
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_hook(self, hook_name, callback, *, hold_stream=False):
        self.hooks[hook_name] = callback

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        assert "_" not in name, "underscored command names never match on messaging platforms"
        self.commands[name] = handler

    def register_auxiliary_task(self, key, *, display_name, description, defaults=None, inherit_from=None):
        assert all(c.isalnum() or c == "_" for c in key), key
        self.aux_tasks[key] = {"inherit_from": inherit_from}

    def register_automation_blueprint(self, key, *, title, description, schedule_template, prompt_template,
                                      category="general", slots=(), deliver_default="origin", skills=(), tags=()):
        assert ":" not in key
        self.blueprints[key] = {"schedule_template": schedule_template, "prompt_template": prompt_template,
                                "slots": list(slots)}

    def on_unload(self, callback):
        self.unload.append(callback)


def detour(conf: float = 0.9, closest: int = 1, cont: bool = False, summary: str = "a detour") -> dict:
    return {"goal": 0, "confidence": conf, "continues_previous": cont, "closest_goal": closest, "summary60": summary}


def on_goal(goal: int, conf: float = 0.9, cont: bool = False, summary: str = "on goal") -> dict:
    return {"goal": goal, "confidence": conf, "continues_previous": cont, "closest_goal": goal, "summary60": summary}


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: Any) -> None:
        self.now = self.now + timedelta(**kw)


GOALS = [
    {"name": "VDRI launch", "description": "pilot customers, pricing and the investor deck", "planned_pct": 50},
    {"name": "Hackathons", "description": "build and submit the Hermes plugin", "planned_pct": 30},
    {"name": "English", "description": "speaking and writing practice", "planned_pct": 20},
]


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc))


@pytest.fixture
def make_app(tmp_path, clock):
    apps = []

    def factory(responder=None, delay=0.0, config=None, goals=True, budget=1.5):
        ctx = FakeCtx(FakeLLM(responder, delay), config)
        app = Bussola(ctx, store=Store(tmp_path / f"db{len(apps)}.sqlite"), data_dir=tmp_path / "data",
                      clock=clock, budget=budget)
        app.store.migrate()
        if goals:
            app.store.set_goals([dict(g) for g in GOALS], clock())
        apps.append(app)
        return app

    yield factory
    for app in apps:
        app.close()


def turn(app: Bussola, message: str, session: str = "s1", turn_id: str = "t1", history: Optional[list] = None):
    return app.on_pre_llm_call(
        session_id=session, user_message=message, conversation_history=history or [], is_first_turn=False,
        model="m", platform="cli", turn_id=turn_id, task_id="task", parent_session_id="", sender_id="",
    )


__all__ = ["bussola", "FakeCtx", "FakeLLM", "FakeOut", "FakeCron", "detour", "on_goal", "turn", "GOALS"]
