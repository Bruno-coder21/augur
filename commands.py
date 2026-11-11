"""Slash commands: ``/bussola [goals|fix|pause|demo|report|eval|help]`` and ``/park``."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from . import demo, panel, privacy, strings
from .classifier import TASK as CLASSIFIER_TASK

log = logging.getLogger("bussola.commands")

SPLITS = ["50/30/20", "40/40/20", "34/33/33"]
_SPLIT_RE = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})\s*/\s*(\d{1,3})\s*%?\s*$")
_QUOTED_RE = re.compile(r"[\"“”]([^\"“”]+)[\"“”]")
_PAUSE_RE = re.compile(r"^(\d{1,4})\s*(m|min|h|d)?$", re.IGNORECASE)
LOCAL_SURFACES = {"", "cli", "tui", "local", "desktop", "acp"}

GOALS_SCHEMA = {
    "type": "object",
    "properties": {
        "goals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["goals"],
    "additionalProperties": False,
}
GOALS_INSTRUCTIONS = (
    "The user described their priorities for this week. Return exactly 3 goals in the order given. "
    "name: 1 to 3 words, Title Case, in the user's language. description: one sentence with what the goal covers. "
    "JSON only."
)


# ---------------------------------------------------------------------------- parsing


def parse_split(text: str) -> tuple[str, Optional[list[int]]]:
    """Strip a trailing ``50/30/20`` from ``text``; returns (rest, split or None)."""
    m = _SPLIT_RE.search(text)
    if not m:
        return text, None
    return text[: m.start()].strip(), [int(m.group(i)) for i in (1, 2, 3)]


def valid_split(split: Optional[list[int]]) -> bool:
    return bool(split) and len(split) == 3 and all(p > 0 for p in split) and sum(split) == 100


def _goal(part: str) -> dict[str, str]:
    part = part.strip().strip(".")
    if ":" in part:
        name, desc = part.split(":", 1)
        name, desc = name.strip(), part.strip()
    else:
        name, desc = part, part
    name = privacy.clip(name, 40)
    return {"name": name[:1].upper() + name[1:], "description": privacy.clip(desc, 160)}


def parse_goals(text: str) -> Optional[list[dict[str, str]]]:
    """Deterministic parse: quoted goals, or exactly 3 comma/semicolon/'and'-separated parts."""
    quoted = [q for q in _QUOTED_RE.findall(text) if q.strip()]
    if quoted:
        return [_goal(q) for q in quoted]
    parts = [p for p in re.split(r"[;,\n]", text) if p.strip()]
    if len(parts) == 2:
        tail = re.split(r"\s+(?:and|e)\s+", parts[1], maxsplit=1)
        parts = [parts[0], *tail]
    if len(parts) == 1:
        parts = re.split(r"\s+(?:and|e)\s+", parts[0])
    parts = [p for p in parts if p.strip()]
    if len(parts) == 3:
        return [_goal(re.sub(r"^\s*(?:and|e)\s+", "", p)) for p in parts]
    return None


# ---------------------------------------------------------------------------- commands


class Commands:
    def __init__(self, app: Any):
        self.app = app

    @property
    def ctx(self) -> Any:
        return self.app.ctx

    def _ask(self, question: str, choices: list) -> Optional[str]:
        ask = getattr(self.ctx, "ask_choice", None)
        if ask is None:
            return None
        try:
            return ask(question, choices)
        except Exception:
            return None

    # -- /bussola -----------------------------------------------------------------
    def bussola(self, raw_args: str = "", session_id: str = "", platform: str = "", **_: Any) -> str:
        lang = self.app.lang()
        try:
            args = (raw_args or "").strip()
            head, _, rest = args.partition(" ")
            head = head.lower()
            rest = rest.strip()
            if head in ("", "panel", "status"):
                return self.show_panel(platform, lang)
            if head in ("goals", "goal", "metas"):
                return self.goals(rest, lang)
            if head == "fix":
                return self.fix(rest, session_id, lang)
            if head == "pause":
                return self.pause(rest, lang)
            if head == "demo":
                return self.demo(rest, lang)
            if head == "report":
                return self.report(platform, lang)
            if head == "eval":
                return self.run_eval(rest, lang)
            return strings.t("help", lang)
        except Exception as exc:
            log.warning("bussola command failed: %s", exc, exc_info=True)
            return strings.t("error", lang)

    def park(self, raw_args: str = "", session_id: str = "", **_: Any) -> str:
        lang = self.app.lang()
        try:
            text = (raw_args or "").strip()
            if not text:
                return strings.t("park_usage", lang)
            out = self.app.park(text, session_id=session_id)
            item = self.app.store.queue_get(out["id"])
            return strings.t("park_saved", lang, id=out["id"], summary=item["summary60"], n=out["queue_size"])
        except Exception as exc:
            log.warning("bussola /park failed: %s", exc, exc_info=True)
            return strings.t("error", lang)

    # -- panel --------------------------------------------------------------------
    def show_panel(self, platform: str, lang: str) -> str:
        store = self.app.store
        if not store.has_goals():
            return strings.t("onboarding", lang)
        paused = self.app.paused_until()
        stats = self.app.week()
        return panel.render(
            stats,
            lang,
            color=(platform == "cli"),
            paused_until=_clock_label(paused) if paused else None,
            last_friday=panel.last_friday_label(store.meta_get("last_friday_run"), lang),
            health=self.app.health(),
        )

    # -- goals --------------------------------------------------------------------
    def goals(self, text: str, lang: str) -> str:
        if not text:
            return strings.t("onboarding", lang)
        rest, split = parse_split(text)
        if split is not None and not valid_split(split):
            return strings.t("goals_bad_split", lang)
        goals = parse_goals(rest)
        if goals is not None and len(goals) != 3:
            return strings.t("goals_need_three", lang, n=len(goals))
        if goals is None:
            goals = self._extract_goals(rest)
        if goals is None:
            return strings.t("goals_parse_failed", lang)
        names = [g["name"] for g in goals]
        if split is None:
            choice = self._ask(
                strings.t("goals_split_question", lang, g1=names[0], g2=names[1], g3=names[2]),
                [{"value": s, "label": s.replace("/", " / ")} for s in SPLITS]
                + [{"value": "cancel", "label": strings.t("cancel", lang)}],
            )
            if choice not in SPLITS:
                quoted = " ".join(f'"{n}"' for n in names)
                return strings.t("goals_not_saved", lang, names=quoted)
            split = [int(p) for p in choice.split("/")]
        for goal, pct in zip(goals, split):
            goal["planned_pct"] = pct
        store = self.app.store
        store.set_goals(goals, self.app.clock())
        message = strings.t(
            "goals_saved", lang, g1=names[0], g2=names[1], g3=names[2], p1=split[0], p2=split[1], p3=split[2]
        )
        if store.has_demo():
            demo.clear(store)  # real goals now: the sample week must not mix with real numbers
            message += "\n" + strings.t("goals_demo_cleared", lang)
        return message

    def _extract_goals(self, text: str) -> Optional[list[dict[str, str]]]:
        try:
            out = self.ctx.llm.complete_structured(
                instructions=GOALS_INSTRUCTIONS,
                input=[{"type": "text", "text": privacy.clip(privacy.redact(text), 600)}],
                json_schema=GOALS_SCHEMA,
                schema_name="bussola_goals",
                temperature=0,
                max_tokens=300,
                timeout=30,
                purpose="bussola: turn the user's description into 3 goals",
                task=CLASSIFIER_TASK,
            )
        except Exception as exc:
            log.info("bussola goal extraction failed: %s", type(exc).__name__)
            return None
        parsed = getattr(out, "parsed", None)
        items = parsed.get("goals") if isinstance(parsed, dict) else None
        if not isinstance(items, list) or len(items) != 3:
            return None
        goals = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                return None
            goals.append(
                {
                    "name": privacy.clip(item["name"], 40),
                    "description": privacy.clip(item.get("description") or item["name"], 160),
                }
            )
        return goals

    # -- fix ----------------------------------------------------------------------
    def fix(self, arg: str, session_id: str, lang: str) -> str:
        store = self.app.store
        turn = store.last_classified(session_id or None)  # never another session's request
        if turn is None or not store.has_goals():
            return strings.t("fix_nothing", lang)
        goals = store.goals()
        labels = {g["slot"]: g["name"] for g in goals}
        labels[0] = strings.t("detour", lang)
        target: Optional[int] = None
        arg = arg.strip().lower()
        if arg:
            if arg in ("0", "detour", "desvio"):
                target = 0
            elif arg in ("1", "2", "3"):
                target = int(arg)
            else:
                return strings.t("fix_usage", lang)
        else:
            current = labels.get(int(turn["goal"]), "?")
            choice = self._ask(
                strings.t("fix_question", lang, summary=turn["summary60"], label=current),
                [{"value": str(slot), "label": f"{slot} · {labels[slot]}"} for slot in (1, 2, 3)]
                + [{"value": "0", "label": labels[0]}],
            )
            if choice not in ("0", "1", "2", "3"):
                return strings.t("fix_unchanged", lang)
            target = int(choice)
        store.correction_add(turn["summary60"], target, self.app.clock())
        store.update_turn(turn["id"], goal=target)
        return strings.t("fix_saved", lang, summary=turn["summary60"], label=labels[target])

    # -- pause --------------------------------------------------------------------
    def pause(self, arg: str, lang: str) -> str:
        arg = arg.strip().lower()
        if arg in ("off", "stop", "resume", "0"):
            self.app.pause(None)
            return strings.t("pause_off", lang)
        m = _PAUSE_RE.match(arg or "2h")
        if not m:
            return strings.t("pause_usage", lang)
        amount, unit = int(m.group(1)), (m.group(2) or "m").lower()
        minutes = amount * {"m": 1, "min": 1, "h": 60, "d": 1440}[unit]
        if not 1 <= minutes <= 7 * 1440:
            return strings.t("pause_usage", lang)
        until = self.app.pause(minutes)
        return strings.t("pause_on", lang, until=_clock_label(until))

    # -- demo ---------------------------------------------------------------------
    def demo(self, arg: str, lang: str) -> str:
        store = self.app.store
        if arg.strip().lower() in ("clear", "off", "remove"):
            demo.clear(store)
            return strings.t("demo_cleared", lang)
        had_goals = store.has_goals() and store.meta_get("demo_goals") != "1"
        counts = demo.load(store, self.app.clock())
        msg = strings.t("demo_loaded", lang, n=counts["requests"], q=counts["parked"])
        if had_goals:
            msg += "\n" + strings.t("demo_kept_goals", lang)
        return msg

    # -- report -------------------------------------------------------------------
    def report(self, platform: str, lang: str) -> str:
        result = self.app.build_report()
        if not result.get("path"):
            return result["caption"] + "\n\n" + result["text"]
        if (platform or "").lower() in LOCAL_SURFACES:
            return result["caption"] + "\n" + result["path"]
        return result["caption"] + "\nMEDIA:" + result["path"]

    # -- eval (developer tool) -------------------------------------------------------
    def run_eval(self, arg: str, lang: str) -> str:
        from .evals import run as eval_run

        final = arg.strip().lower() == "final"
        path, table = eval_run.run_with_app(self.app, final=final)
        return strings.t("eval_done", lang, path=path, table=table)


def _clock_label(moment: Any) -> str:
    try:
        return moment.astimezone().strftime("%a %H:%M")
    except Exception:
        return str(moment)
