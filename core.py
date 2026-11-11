"""The running plugin: state shared by hooks, tools and commands.

Contract for every entry point here: never raise into Hermes. Hooks return
``None`` on any error (silence), tools return a JSON string, commands return
text. The one deliberate exception is the Friday-run guard, which blocks when
it cannot decide (see ``on_pre_tool_call``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from . import classifier as clf
from . import config, friday, insight, metering, nudge, privacy, report, strings
from .store import Store, iso, parse_iso, utcnow

log = logging.getLogger("bussola")


class Bussola:
    def __init__(
        self,
        ctx: Any,
        store: Optional[Store] = None,
        data_dir: Optional[Path] = None,
        clock: Callable[[], datetime] = utcnow,
        budget: float = clf.BUDGET_SECONDS,
    ):
        self.ctx = ctx
        self.store = store or Store()
        self._data_dir = data_dir
        self.clock = clock
        self.sessions = nudge.SessionStates()
        self.classifier = clf.Classifier(lambda: self.ctx.llm, budget=budget)
        self.fridays = friday.FridayRuns(self._cron)

    def close(self) -> None:
        self.classifier.shutdown()
        self.store.close()

    # ------------------------------------------------------------------ helpers
    def _cron(self) -> Any:
        return self.ctx.current_cron_execution()

    @property
    def data_dir(self) -> Path:
        if self._data_dir is None:
            from .store import default_data_dir

            self._data_dir = default_data_dir()
        return self._data_dir

    @property
    def drafts_dir(self) -> Path:
        path = self.data_dir / "drafts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def lang(self) -> str:
        return config.get(self.ctx, "language")

    def paused_until(self) -> Optional[datetime]:
        raw = self.store.meta_get("paused_until")
        if not raw:
            return None
        try:
            until = parse_iso(raw)
        except ValueError:
            return None
        return until if until > self.clock() else None

    # ------------------------------------------------------------------ hooks
    def on_pre_llm_call(
        self,
        session_id: str = "",
        user_message: Any = None,
        conversation_history: Any = None,
        turn_id: str = "",
        parent_session_id: str = "",
        **_: Any,
    ) -> Optional[dict[str, str]]:
        try:
            return self._pre_llm_call(session_id, user_message, conversation_history, turn_id, parent_session_id)
        except Exception as exc:
            log.warning("bussola pre_llm_call skipped: %s", exc, exc_info=True)
            return None

    def _pre_llm_call(self, session_id, user_message, conversation_history, turn_id, parent_session_id):
        message = privacy.message_text(user_message)
        run = self._cron()
        if run is not None:
            if friday.MARKER in message:
                self.fridays.mark(getattr(run, "execution_id", ""))
                self.store.meta_set("last_friday_run", iso(self.clock()))
            return None
        if parent_session_id or not session_id:
            return None  # subagents and anonymous calls are not the user talking
        if not message.strip() or message.lstrip().startswith("/"):
            return None
        if self.paused_until() is not None or not self.store.has_goals():
            return None

        now = self.clock()
        state = self.sessions.get(session_id)
        # A text nudge is answered by the next turn; that turn never nudges again.
        answering = state.pending_row is not None and state.pending_turn != turn_id
        if answering and state.answer_turn and state.answer_turn != turn_id:
            self._decide(state, "do_now")  # the answer turn ended without post_llm_call
            answering = False
        if answering:
            state.answer_turn = turn_id

        row = self.store.insert_turn(ts=now, session_id=session_id, summary=message, source="live")
        if turn_id:
            state.turn_rows[turn_id] = row

        previous = self.store.previous_user_turn(session_id, row)
        recent_prev = previous if previous and now - parse_iso(previous["ts"]) <= nudge.STREAK_WINDOW else None

        if len(message.strip()) < clf.SHORT_MESSAGE_CHARS:
            if recent_prev and recent_prev["goal"] is not None:
                self.store.update_turn(row, goal=recent_prev["goal"], confidence=recent_prev["confidence"])
            return None  # continuations never nudge

        goals = self.store.goals()
        result = self.classifier.classify(
            goals,
            self.store.corrections_recent(8),
            clf.previous_user_messages(conversation_history),
            message,
            on_late=lambda late: self._record(row, late, recent_prev, source="background"),
        )
        if result is None:
            return None
        goal = self._record(row, result, recent_prev, source="live")
        if goal is None or answering:
            return None
        if not nudge.should_nudge(
            self.store,
            session_id=session_id,
            turn_row=row,
            goal=goal,
            confidence=result.confidence,
            now=now,
            min_confidence=config.get(self.ctx, "min_confidence"),
            cooldown_minutes=config.get(self.ctx, "nudge_cooldown_minutes"),
            max_per_day=config.get(self.ctx, "max_nudges_per_day"),
        ):
            return None
        self.store.update_turn(row, nudged=1)
        state.pending_row, state.pending_turn, state.answer_turn = row, turn_id, None
        return {"context": nudge.nudge_context(goals, result.closest_goal, self.lang())}

    def _record(self, row: int, result: Optional[clf.Result], previous: Optional[dict], source: str) -> Optional[int]:
        """Store a classification; returns the goal it counts toward (None = not counted)."""
        if result is None:
            return None
        if result.confidence < config.get(self.ctx, "min_confidence"):
            self.store.update_turn(row, confidence=result.confidence, source=source)
            return None
        goal = result.goal
        if result.continues_previous and previous and previous["goal"] is not None:
            goal = int(previous["goal"])
        fields: dict[str, Any] = {"goal": goal, "confidence": result.confidence, "source": source}
        if result.summary60:
            fields["summary60"] = result.summary60
        self.store.update_turn(row, **fields)
        return goal

    def on_post_llm_call(self, session_id: str = "", turn_id: str = "", **_: Any) -> None:
        try:
            state = self.sessions.peek(session_id) if session_id else None
            if state is None or state.pending_row is None:
                return None
            if turn_id == state.pending_turn:
                if turn_id in state.clarify_turns:
                    self._decide(state, "do_now")  # answered via buttons, and no park happened
            elif turn_id == state.answer_turn:
                self._decide(state, "do_now")
            state.clarify_turns.discard(turn_id)
        except Exception as exc:
            log.warning("bussola post_llm_call skipped: %s", exc)
        return None

    def _decide(self, state: nudge.SessionState, decision: str) -> None:
        if state.pending_row is not None:
            self.store.update_turn(state.pending_row, decision=decision, decided_at=iso(self.clock()))
        state.pending_row = state.pending_turn = state.answer_turn = None

    def on_post_api_request(self, session_id: str = "", turn_id: str = "", usage: Any = None, **_: Any) -> None:
        try:
            state = self.sessions.peek(session_id) if session_id else None
            row = state.turn_rows.get(turn_id) if state and turn_id else None
            if row is not None:
                self.store.add_tokens(row, metering.usage_tokens(usage))
        except Exception as exc:
            log.debug("bussola post_api_request skipped: %s", exc)
        return None

    def on_post_auxiliary_call(self, aux_task: str = "", usage: Any = None, **_: Any) -> None:
        try:
            if aux_task in metering.BUSSOLA_TASKS:
                tokens = metering.usage_tokens(usage)
                if tokens:
                    self.store.self_cost_add(aux_task, tokens, self.clock())
        except Exception as exc:
            log.debug("bussola post_auxiliary_call skipped: %s", exc)
        return None

    def on_pre_tool_call(self, tool_name: str = "", args: Any = None, session_id: str = "", turn_id: str = "", **_: Any):
        in_friday = False
        try:
            if tool_name == "clarify" and session_id and turn_id:
                state = self.sessions.peek(session_id)
                if state is not None and state.pending_turn == turn_id:
                    state.clarify_turns.add(turn_id)
            in_friday = self.fridays.active()
            if not in_friday:
                return None
            if friday.allowed(tool_name, args, self.drafts_dir):
                return None
            return {"action": "block", "message": strings.t("friday_blocked", self.lang())}
        except Exception as exc:
            log.warning("bussola guard error: %s", exc)
            if in_friday:  # unsure inside the Friday run: refuse rather than allow
                return {"action": "block", "message": strings.t("friday_blocked", "en")}
            return None

    def on_transform_llm_output(self, response_text: str = "", **_: Any) -> Optional[str]:
        try:
            if not self.fridays.active():
                return None
            return friday.ensure_media(response_text, self.store.meta_get("last_report_path"))
        except Exception as exc:
            log.warning("bussola transform skipped: %s", exc)
            return None

    # ------------------------------------------------------------------ shared actions
    def park(self, summary: str, session_id: str = "") -> dict[str, Any]:
        item = self.store.queue_add(summary, self.clock())
        if session_id:
            state = self.sessions.peek(session_id)
            if state is not None and state.pending_row is not None:
                self._decide(state, "park")
        return {"ok": True, "id": item, "queue_size": self.store.queue_size()}

    def hidden_priority(self, stats: report.WeekStats, compute: bool) -> Optional[dict[str, Any]]:
        key = insight.cache_key(iso(stats.start)[:10], stats.detours)
        hit, value = insight.cached(self.store, key)
        if hit or not compute:
            return value
        value = insight.find(lambda: self.ctx.llm, stats.detours)
        insight.remember(self.store, key, value)
        return value

    def build_report(self) -> dict[str, Any]:
        now = self.clock()
        lang = self.lang()
        stats = report.week_stats(self.store, now, lang)
        hidden = self.hidden_priority(stats, compute=True)
        return report.build(self.store, self.data_dir, now, lang, hidden)

    def week(self) -> report.WeekStats:
        now = self.clock()
        stats = report.week_stats(self.store, now, self.lang())
        stats.hidden = self.hidden_priority(stats, compute=False)
        return stats

    def pause(self, minutes: Optional[int]) -> Optional[datetime]:
        if not minutes:
            self.store.meta_set("paused_until", None)
            return None
        until = self.clock() + timedelta(minutes=minutes)
        self.store.meta_set("paused_until", iso(until))
        return until
