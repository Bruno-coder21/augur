"""Hidden priority: a 4th goal the user keeps working on without declaring it.

Runs only while building the weekly report, as one call through the
``augur_insight`` auxiliary task, and only shows when 5 or more of the
week's detours share a theme. The result is cached per week so the report,
the panel and the Friday run never pay twice.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from . import privacy

log = logging.getLogger("augur.insight")

TASK = "augur_insight"
MIN_COUNT = 5

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "theme": {"type": "string", "description": "empty string when no theme covers 5 requests"},
        "count": {"type": "integer"},
        "examples": {"type": "array", "items": {"type": "string"}},
        "suggested_goal": {"type": "string"},
    },
    "required": ["theme", "count", "examples", "suggested_goal"],
    "additionalProperties": False,
}

INSTRUCTIONS = """These are one week of requests a user made to their AI agent that fell OUTSIDE their 3 declared goals.
Find the single largest group of requests that share one concrete theme (a project, a topic, an area of life), if any.

Answer with JSON only:
- theme: a short name for that theme (2 to 4 words), or an empty string if no theme covers at least 5 requests.
- count: how many of the listed requests belong to it. Count only clear members.
- examples: 2 short examples taken from the list (at most 40 characters each).
- suggested_goal: the theme phrased as a weekly goal (at most 40 characters).
Requests marked [did it] are ones the user chose to do anyway; they are the strongest signal."""


def cache_key(week_start: str, detours: list[dict[str, Any]]) -> str:
    last = max((int(d["id"]) for d in detours), default=0)
    return f"{week_start}:{len(detours)}:{last}"


def find(
    llm_getter: Callable[[], Any],
    detours: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """One model call; ``None`` when there is no hidden priority or anything fails."""
    if len(detours) < MIN_COUNT:
        return None
    lines = []
    for d in detours[-60:]:
        flag = " [did it]" if d.get("decision") == "do_now" else ""
        lines.append(f"- {d.get('summary60') or ''}{flag}")
    try:
        out = llm_getter().complete_structured(
            instructions=INSTRUCTIONS,
            input=[{"type": "text", "text": "\n".join(lines)}],
            json_schema=SCHEMA,
            schema_name="augur_hidden_priority",
            temperature=0,
            max_tokens=200,
            timeout=30,
            purpose="augur: find a recurring theme in the week's detours",
            task=TASK,
        )
    except Exception as exc:
        log.info("augur insight call failed: %s: %.300s", type(exc).__name__, exc)
        return None
    return validate(getattr(out, "parsed", None), len(detours))


def validate(parsed: Any, n_detours: int) -> Optional[dict[str, Any]]:
    if not isinstance(parsed, dict) or not parsed.get("theme"):
        return None
    try:
        count = int(parsed.get("count") or 0)
    except (TypeError, ValueError):
        return None
    count = min(count, n_detours)
    if count < MIN_COUNT:
        return None
    examples = [privacy.clip(privacy.redact(e), 40) for e in (parsed.get("examples") or []) if str(e).strip()][:2]
    return {
        "theme": privacy.clip(privacy.redact(parsed["theme"]), 40),
        "count": count,
        "examples": examples,
        "suggested_goal": privacy.clip(privacy.redact(parsed.get("suggested_goal") or parsed["theme"]), 40),
    }


def cached(store: Any, key: str, allow_pinned: bool = False) -> tuple[bool, Optional[dict[str, Any]]]:
    raw = store.meta_get("insight_cache")
    if not raw:
        return False, None
    try:
        data = json.loads(raw)
    except ValueError:
        return False, None
    if data.get("pinned"):
        return (True, data.get("result")) if allow_pinned else (False, None)  # demo value: only with demo data
    if data.get("key") != key:
        return False, None
    return True, data.get("result")


def remember(store: Any, key: str, result: Optional[dict[str, Any]], pinned: bool = False, at: str = "") -> None:
    store.meta_set("insight_cache", json.dumps({"key": key, "result": result, "pinned": pinned, "at": at}))


def latest(store: Any, now: Any, allow_pinned: bool = False) -> Optional[dict[str, Any]]:
    """The last computed hidden priority, if it is less than 7 days old (no model call)."""
    from datetime import timedelta

    from .store import parse_iso

    try:
        data = json.loads(store.meta_get("insight_cache") or "{}")
    except ValueError:
        return None
    if data.get("pinned"):
        return data.get("result") if allow_pinned else None
    try:
        if now - parse_iso(data.get("at") or "") > timedelta(days=7):
            return None
    except ValueError:
        return None
    return data.get("result")
