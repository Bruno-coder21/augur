"""The running plugin: state shared by hooks, tools and commands.

Contract for every entry point here: never raise into Hermes. Hooks return
``None`` on any error (silence), tools return a JSON string, commands return
text. The one deliberate exception is the Friday-run guard, which blocks when
it cannot decide (see ``on_pre_tool_call``).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from . import classifier as clf
from . import config, friday, insight, metering, nudge, privacy, report, strings
from .store import Store, iso, parse_iso, utcnow

log = logging.getLogger("bussola")

# Surfaces with nobody there to answer a question: never labeled, never nudged.
UNATTENDED_PLATFORMS = frozenset({"cron", "kanban", "webhook", "webhooks", "api", "api_server", "batch", "scheduler"})
# Short replies that carry no task of their own ("ok", "thanks"): not counted at all.
_ACK_RE = re.compile(
    r"^\s*(ok(ay)?|k|yes|yep|no|nope|thanks?( you)?|thx|ty|cool|great|nice|perfect|done|got it|sure|"
    r"obrigad[oa]|valeu|vlw|sim|não|nao|beleza|blz|show|massa|perfeito|certo|entendi|tá|ta|👍|🙏|❤️)[\s!.?]*$",
    re.IGNORECASE,
)
HEALTH_WINDOW = 20


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
        self.fridays = friday.FridayRuns(self._cron, self._friday_jobs)
        self.evaluating = False

    def close(self) -> None:
        self.classifier.shutdown()
        self.store.close()

    # ------------------------------------------------------------------ helpers
    def _cron(self) -> Any:
        return self.ctx.current_cron_execution()

    def _friday_jobs(self) -> set[str]:
        try:
            return set(json.loads(self.store.meta_get("friday_jobs") or "[]"))
        except Exception:
            return set()

    def _remember_friday_job(self, job_id: Any) -> None:
        if not job_id:
            return
        jobs = [j for j in json.loads(self.store.meta_get("friday_jobs") or "[]") if j != str(job_id)]
        self.store.meta_set("friday_jobs", json.dumps((jobs + [str(job_id)])[-10:]))

    def _health(self, outcome: str) -> None:
        """Rolling record of the last classifier outcomes (o=ok, l=late, f=fail)."""
        try:
            code = {"ok": "o", "late": "l"}.get(outcome, "f")
            history = (self.store.meta_get("clf_health") or "") + code
            self.store.meta_set("clf_health", history[-HEALTH_WINDOW:])
        except Exception:
            pass

    def health(self) -> tuple[int, int]:
        """(slow or failed, total) over the last classifier calls."""
        history = self.store.meta_get("clf_health") or ""
        return sum(1 for c in history if c != "o"), len(history)

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
        platform: str = "",
        **_: Any,
    ) -> Optional[dict[str, str]]:
        try:
            if str(platform or "").lower() in UNATTENDED_PLATFORMS or os.environ.get("HERMES_KANBAN_TASK"):
                if self._cron() is None:
                    return None
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
                self._remember_friday_job(getattr(run, "job_id", ""))
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

        if answering and len(message.strip()) < 60:
            # "Park it" / "do it now": the reply to a nudge is not a new request. Its tokens
            # (the detour work, when the answer is "do it now") go to the nudged request.
            if turn_id:
                state.turn_rows[turn_id] = state.pending_row
            return None

        if len(message.strip()) < clf.SHORT_MESSAGE_CHARS and _ACK_RE.match(message):
            return None  # "ok", "thanks": not a request, not counted, no row

        # The row stores no user text: summary60 is written only from the model's summary.
        row = self.store.insert_turn(ts=now, session_id=session_id, summary="", source="live")
        if turn_id:
            state.turn_rows[turn_id] = row

        previous = self.store.previous_user_turn(session_id, row)
        recent_prev = previous if previous and now - parse_iso(previous["ts"]) <= nudge.STREAK_WINDOW else None

        if len(message.strip()) < clf.SHORT_MESSAGE_CHARS:
            if recent_prev and recent_prev["goal"] is not None:
                self.store.update_turn(
                    row, goal=recent_prev["goal"], confidence=recent_prev["confidence"], source="inherited"
                )
            return None  # short follow-ups ("shorter") count for the same goal and never nudge

        goals = self.store.goals()
        # Only hold the turn when this request could trigger a nudge (the previous one was an
        # open detour). Otherwise label it in the background: zero added latency.
        wait = not answering and nudge.nudge_possible(
            self.store,
            session_id=session_id,
            turn_row=row,
            now=now,
            cooldown_minutes=config.get(self.ctx, "nudge_cooldown_minutes"),
            max_per_day=config.get(self.ctx, "max_nudges_per_day"),
        )

        def on_late(late: Optional[clf.Result]) -> None:
            if not wait:  # not held, but still measured: would it have made the 1.5 s budget?
                self._health("fail" if late is None else ("late" if late.latency > self.classifier.budget else "ok"))
            goal = self._record(row, late, recent_prev, source="background" if wait else "live", session_id=session_id)
            if wait and late is not None and goal == 0:
                self._late_nudge(state, row, turn_id, late, goals, session_id)

        result, outcome = self.classifier.classify(
            goals,
            self.store.corrections_recent(8),
            clf.previous_user_messages(conversation_history),
            message,
            on_late=on_late,
            wait=wait,
        )
        if outcome != "async":
            self._health(outcome)
        if result is None:
            return None
        goal = self._record(row, result, recent_prev, source="live", session_id=session_id)
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

    def _late_nudge(self, state, row: int, turn_id: str, result: clf.Result, goals, session_id: str) -> None:
        """The label came after the agent started: no question, but a 🧭 line under the reply."""
        try:
            if not turn_id or not nudge.should_nudge(
                self.store,
                session_id=session_id,
                turn_row=row,
                goal=0,
                confidence=result.confidence,
                now=self.clock(),
                min_confidence=config.get(self.ctx, "min_confidence"),
                cooldown_minutes=config.get(self.ctx, "nudge_cooldown_minutes"),
                max_per_day=config.get(self.ctx, "max_nudges_per_day"),
            ):
                return
            # the user did it anyway: count the nudge and start the quiet time, like "Do it now"
            self.store.update_turn(row, nudged=1, decision="do_now", decided_at=iso(self.clock()))
            state.notes[turn_id] = nudge.nudge_note(goals, result.closest_goal, self.lang())
        except Exception as exc:
            log.debug("bussola late nudge skipped: %s", exc)

    def _record(
        self, row: int, result: Optional[clf.Result], previous: Optional[dict], source: str, session_id: str = ""
    ) -> Optional[int]:
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
        self._emit_status(session_id)
        return goal

    # ------------------------------------------------------------------ desktop chip
    def status(self, session_id: str = "") -> dict[str, Any]:
        """Compact JSON for the Desktop status chip (RPC ``plugin.bussola.status``)."""
        lang = self.lang()
        if not self.store.has_goals():
            return {"has_goals": False, "language": lang}
        stats = self.week()
        names = {r.slot: r.name for r in stats.rows}
        last = self.store.last_classified(session_id or None)
        current = None
        if last is not None and last["goal"] is not None:
            current = names.get(int(last["goal"]))
        return {
            "has_goals": True,
            "language": lang,
            "current_goal": current,
            "on_goals_pct": (100 - stats.detour_pct) if stats.counted else 0,
            "counted": stats.counted,
            "rows": [{"slot": r.slot, "name": r.name, "pct": r.pct, "planned": r.planned} for r in stats.rows],
            "parked": stats.parked,
            "hidden": stats.hidden,
            "has_demo": stats.has_demo,
        }

    def rpc_status(self, params: Any = None, *, session_id: str = "", **_: Any) -> dict[str, Any]:
        sid = session_id or (params.get("session_id") if isinstance(params, dict) else "") or ""
        try:
            return self.status(str(sid))
        except Exception as exc:
            log.warning("bussola status RPC failed: %s", exc)
            return {"has_goals": False, "error": True}

    def _emit_status(self, session_id: str) -> None:
        emit = getattr(self.ctx, "emit_to_session", None)
        if not session_id or emit is None:
            return
        try:
            emit(session_id, "status.changed", self.status(session_id))
        except Exception as exc:  # no viewer, CLI session, cron: nothing to update
            log.debug("bussola status emit skipped: %s", exc)

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
            if aux_task in metering.BUSSOLA_TASKS and not self.evaluating:  # the dev eval is not runtime cost
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

    def on_transform_llm_output(
        self, response_text: str = "", session_id: str = "", turn_id: str = "", **_: Any
    ) -> Optional[str]:
        try:
            state = self.sessions.peek(session_id) if session_id else None
            note = state.notes.pop(turn_id, None) if state is not None and turn_id else None
            if note and isinstance(response_text, str) and response_text.strip():
                return response_text.rstrip() + "\n\n" + note
            execution = self.fridays.execution_id()
            if not execution or self.store.meta_get("report_execution") != execution:
                return None  # only a report built during *this* run is ever attached
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
        hit, value = insight.cached(self.store, key, allow_pinned=stats.has_demo)
        if hit or not compute:
            return value
        value = insight.find(lambda: self.ctx.llm, stats.detours)
        insight.remember(self.store, key, value)
        return value

    def _housekeeping(self, now: datetime) -> None:
        if self.store.demo_is_stale(now):
            self.store.clear_demo()  # a forgotten demo never leaks into real weeks
        self.store.prune(now)
        report.prune_files(self.data_dir, now)

    def build_report(self) -> dict[str, Any]:
        now = self.clock()
        lang = self.lang()
        self._housekeeping(now)
        stats = report.week_stats(self.store, now, lang)
        hidden = self.hidden_priority(stats, compute=True)
        out = report.build(self.store, self.data_dir, now, lang, hidden)
        execution = self.fridays.execution_id()
        if out.get("path") and execution:
            self.store.meta_set("report_execution", execution)
        return out

    def week(self) -> report.WeekStats:
        now = self.clock()
        if self.store.demo_is_stale(now):
            self.store.clear_demo()
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
