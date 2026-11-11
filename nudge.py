"""When to speak up: the rabbit-hole nudge.

A nudge fires only when ALL of these hold:
1. this turn is a detour with enough confidence;
2. the previous classified turn in the same session, within 30 minutes, was a detour too;
3. no "Do it now" in this session within ``nudge_cooldown_minutes``;
4. fewer than ``max_nudges_per_day`` nudges today;
5. not paused and not in a cron run (checked by the caller before classifying).
It never blocks anything: the result is extra context for the model, nothing more.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from . import strings
from .store import Store, parse_iso

STREAK_WINDOW = timedelta(minutes=30)
STATE_TTL_SECONDS = 2 * 60 * 60


def local_day_start(now: datetime) -> datetime:
    local = now.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class Limits:
    min_confidence: float
    cooldown_minutes: int
    max_per_day: int


def _streak_open(store: Store, session_id: str, turn_row: int, now: datetime, limits: Limits) -> bool:
    """Conditions 2-4: an unanswered detour just before, no quiet time, daily budget left."""
    previous = store.previous_classified(session_id, turn_row)
    if previous is None or previous["goal"] != 0:
        return False
    if previous.get("decision"):  # the last detour was already answered (parked or done): a new streak starts
        return False
    if now - parse_iso(previous["ts"]) > STREAK_WINDOW:
        return False
    last_do_now = store.last_do_now(session_id)
    if last_do_now and last_do_now.get("decided_at"):
        if now - parse_iso(last_do_now["decided_at"]) < timedelta(minutes=limits.cooldown_minutes):
            return False
    return store.nudges_since(local_day_start(now)) < limits.max_per_day


def should_nudge(
    store: Store, *, session_id: str, turn_row: int, goal: Optional[int], confidence: float, now: datetime,
    limits: Limits,
) -> bool:
    if goal != 0 or confidence < limits.min_confidence:  # condition 1
        return False
    return _streak_open(store, session_id, turn_row, now, limits)


def nudge_possible(store: Store, *, session_id: str, turn_row: int, now: datetime, limits: Limits) -> bool:
    """Could this turn nudge at all, whatever its label? Decides whether to hold the turn."""
    if store.previous_classified(session_id, turn_row) is None:
        # the previous request may still be labeling in the background: wait only if it is recent
        last = store.previous_user_turn(session_id, turn_row)
        if last is None or last["goal"] is not None or last.get("source") == "inherited":
            return False
        return now - parse_iso(last["ts"]) <= STREAK_WINDOW
    return _streak_open(store, session_id, turn_row, now, limits)


def nudge_context(goals: list[dict[str, Any]], closest_goal: int, lang: str) -> str:
    names = {g["slot"]: g["name"] for g in goals}
    return strings.t(
        "nudge_context",
        lang,
        g1=names.get(1, ""),
        g2=names.get(2, ""),
        g3=names.get(3, ""),
        closest=names.get(closest_goal, names.get(1, "")),
    )


def nudge_note(goals: list[dict[str, Any]], closest_goal: int, lang: str) -> str:
    """The after-the-fact version, appended to the reply when the label came too late to ask first."""
    names = {g["slot"]: g["name"] for g in goals}
    return strings.t("nudge_note", lang, closest=names.get(closest_goal, names.get(1, "")))


@dataclass
class SessionState:
    """Short-lived, per-session state; expires after 2 hours of silence."""

    touched: float = field(default_factory=time.monotonic)
    turn_rows: dict[str, int] = field(default_factory=dict)  # turn_id -> turns.id
    pending_row: Optional[int] = None  # nudged turn waiting for a decision
    pending_turn: Optional[str] = None  # turn_id that carried the nudge
    answer_turn: Optional[str] = None  # the next turn, which answers a text nudge
    clarify_turns: set[str] = field(default_factory=set)
    notes: dict[str, tuple[int, str]] = field(default_factory=dict)  # turn_id -> (row, 🧭 line) for a late label


class SessionStates:
    def __init__(self, ttl: float = STATE_TTL_SECONDS):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._states: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        now = time.monotonic()
        with self._lock:
            for key in [k for k, s in self._states.items() if now - s.touched > self._ttl]:
                del self._states[key]
            state = self._states.get(session_id)
            if state is None:
                state = self._states[session_id] = SessionState()
            state.touched = now
            # keep the per-turn map small
            if len(state.turn_rows) > 32:
                for key in list(state.turn_rows)[:-16]:
                    del state.turn_rows[key]
            return state

    def peek(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            return self._states.get(session_id)
