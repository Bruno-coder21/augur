"""Classify one user request against the week's 3 goals.

One structured call through the ``bussola_classifier`` auxiliary task, at
temperature 0, behind a hard 1.5 s budget. Anything unexpected (timeout,
exception, invalid JSON, low confidence) means silence: the caller gets
``None`` and the turn goes on untouched.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import privacy

log = logging.getLogger("bussola.classifier")

TASK = "bussola_classifier"
PROMPT_VERSION = "v1"
BUDGET_SECONDS = 1.5
CALL_TIMEOUT_SECONDS = 20
MAX_TOKENS = 160
SHORT_MESSAGE_CHARS = 15
HISTORY_CHARS = 400
MESSAGE_CHARS = 1200
NEUTRAL = -1  # small talk, questions about the assistant itself: never counted, never nudged

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "integer", "minimum": -1, "maximum": 3},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "continues_previous": {"type": "boolean"},
        "closest_goal": {"type": "integer", "minimum": 1, "maximum": 3},
        "summary60": {"type": "string"},
    },
    "required": ["goal", "confidence", "continues_previous", "closest_goal", "summary60"],
}

INSTRUCTIONS = """You label ONE request a user sent to their AI agent, against the user's 3 goals for this week.

Answer with JSON only:
- goal: 1, 2 or 3 when the request moves that goal forward, directly or as a sub-task (research, tooling, writing, fixing, learning something the goal needs).
- goal: 0 (detour) when it serves none of the 3 goals: other projects, personal errands, shopping, entertainment, idle curiosity, side ideas.
- goal: -1 (neutral) for greetings, thanks, small talk, and questions about the agent or its settings. Neutral is never a detour.
- continues_previous: true when the message only continues the previous request (a follow-up, "shorter", "now in Portuguese", "try again").
- closest_goal: the goal (1-3) the request is nearest to, even when it is a detour.
- confidence: 0 to 1. Use below 0.6 when you are unsure. A wrong "detour" annoys the user more than a missed one, so only call something a detour when it clearly fits none of the goals.
- summary60: a neutral summary of the request in at most 60 characters, in the request's language, without names, numbers or secrets.

When a request mixes a goal and a detour, label the main intent."""


@dataclass
class Result:
    goal: Optional[int]  # 0..3, or None for neutral
    confidence: float
    continues_previous: bool
    closest_goal: int
    summary60: str
    latency: float
    tokens: int = 0

    @property
    def is_detour(self) -> bool:
        return self.goal == 0


def build_input(
    goals: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    history: list[str],
    message: str,
) -> list[dict[str, str]]:
    """Input blocks for ``ctx.llm.complete_structured`` (it takes blocks, not a string)."""
    lines = ["Goals this week:"]
    for g in goals:
        desc = g.get("description") or ""
        lines.append(f"{g['slot']}. {g['name']}" + (f" — {desc}" if desc and desc != g["name"] else ""))
    if corrections:
        names = {g["slot"]: g["name"] for g in goals}
        lines.append("")
        lines.append("Corrections this user made to past labels (follow them for similar requests):")
        for c in corrections:
            label = "0 (detour)" if int(c["goal"]) == 0 else f"{c['goal']} ({names.get(int(c['goal']), '')})"
            lines.append(f'- "{c["summary60"]}" → {label}')
    if history:
        lines.append("")
        lines.append("Previous requests in this conversation (oldest first):")
        for h in history:
            lines.append(f"- {privacy.clip(privacy.redact(h), HISTORY_CHARS)}")
    lines.append("")
    lines.append("Request to label:")
    lines.append(privacy.clip(privacy.redact(message), MESSAGE_CHARS))
    return [{"type": "text", "text": "\n".join(lines)}]


def parse(parsed: Any, latency: float, tokens: int = 0) -> Optional[Result]:
    """Validate the model's JSON; ``None`` for anything malformed."""
    if not isinstance(parsed, dict):
        return None
    try:
        goal = int(parsed["goal"])
        confidence = float(parsed["confidence"])
        closest = int(parsed.get("closest_goal") or 1)
        continues = bool(parsed.get("continues_previous", False))
        summary = str(parsed.get("summary60") or "")
    except (KeyError, TypeError, ValueError):
        return None
    if goal not in (-1, 0, 1, 2, 3) or not (0.0 <= confidence <= 1.0):
        return None
    if closest not in (1, 2, 3):
        closest = 1
    return Result(
        goal=None if goal == NEUTRAL else goal,
        confidence=confidence,
        continues_previous=continues,
        closest_goal=closest,
        summary60=privacy.summary60(summary),
        latency=latency,
        tokens=tokens,
    )


def previous_user_messages(conversation_history: Any, limit: int = 2) -> list[str]:
    """The user's messages before the current one (history already ends with it)."""
    if not isinstance(conversation_history, list):
        return []
    users = [
        privacy.message_text(m.get("content"))
        for m in conversation_history
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    users = [u for u in users if u and not u.lstrip().startswith("/")]
    return users[-(limit + 1) : -1] if len(users) > 1 else []


def _usage_tokens(usage: Any) -> int:
    if usage is None:
        return 0
    get = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
    total = get("total_tokens", None)
    if total:
        return int(total)
    return int(get("input_tokens", 0) or 0) + int(get("output_tokens", 0) or 0)


class Classifier:
    """Runs model calls on a dedicated executor and enforces the time budget."""

    def __init__(self, llm_getter: Callable[[], Any], budget: float = BUDGET_SECONDS, workers: int = 4):
        self._llm_getter = llm_getter
        self.budget = budget
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bussola-clf")
        self._inflight = threading.BoundedSemaphore(workers * 2)

    def call(self, goals, corrections, history, message) -> Optional[Result]:
        """Blocking model call; never raises."""
        started = time.monotonic()
        try:
            llm = self._llm_getter()
            out = llm.complete_structured(
                instructions=INSTRUCTIONS,
                input=build_input(goals, corrections, history, message),
                json_schema=SCHEMA,
                schema_name="bussola_label",
                temperature=0,
                max_tokens=MAX_TOKENS,
                timeout=CALL_TIMEOUT_SECONDS,
                purpose="bussola: label a request against the weekly goals",
                task=TASK,
            )
        except Exception as exc:  # provider error, schema mismatch, trust error...
            log.info("bussola classifier call failed: %s", type(exc).__name__)
            return None
        latency = time.monotonic() - started
        return parse(getattr(out, "parsed", None), latency, _usage_tokens(getattr(out, "usage", None)))

    def classify(
        self,
        goals,
        corrections,
        history,
        message,
        on_late: Optional[Callable[[Optional[Result]], None]] = None,
    ) -> Optional[Result]:
        """Wait at most ``budget`` seconds. A late answer goes to ``on_late`` instead."""
        if not self._inflight.acquire(blocking=False):
            return None  # too many calls in flight: stay silent rather than queue up
        ctx = contextvars.copy_context()  # keep profile/secret scope for ctx.llm
        try:
            future: Future = self._executor.submit(ctx.run, self.call, goals, corrections, history, message)
        except Exception:
            self._inflight.release()
            return None
        future.add_done_callback(lambda _f: self._inflight.release())
        try:
            return future.result(timeout=self.budget)
        except FutureTimeout:
            if on_late is not None:
                future.add_done_callback(lambda f: _deliver_late(f, on_late))
            return None
        except Exception:
            return None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _deliver_late(future: Future, on_late: Callable[[Optional[Result]], None]) -> None:
    try:
        on_late(future.result())
    except Exception as exc:
        log.info("bussola late classification dropped: %s", type(exc).__name__)
