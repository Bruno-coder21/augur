"""The Friday run: an ordinary cron job that clears the Queue, read-and-draft only.

* ``register_blueprint`` adds ``/blueprint augur:friday`` (time, day, deliver).
* ``FridayRuns`` remembers which cron executions are Augur's (by the marker in the prompt).
* ``guard`` is the ``pre_tool_call`` policy for those executions only: Augur's own
  tools, a short list of read/search tools, and file writes inside ``drafts/``.
  Everything else is blocked, so anything needing approval becomes "needs you".
* ``ensure_media`` makes sure the final reply carries the report's ``MEDIA:`` line.
"""

from __future__ import annotations

import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

MARKER = "[augur:friday]"
BLUEPRINT_KEY = "friday"

READ_TOOLS = frozenset({"read_file", "search_files", "web_search", "web_extract"})
WRITE_TOOLS = frozenset({"write_file", "patch"})
OWN_PREFIX = "augur_"

_V4A_SINGLE = re.compile(r"^\*\*\*\s*(?:Update|Add|Delete)\s+File:\s*(.+)$", re.MULTILINE)
_V4A_MOVE = re.compile(r"^\*\*\*\s*Move\s+File:\s*(.+?)\s*->\s*(.+)$", re.MULTILINE)

PROMPT = (
    MARKER + " Augur Friday run. You are clearing the user's Queue of parked detours. "
    "This run is read-and-draft only: never send, post, buy, delete, schedule or change anything.\n"
    "1. Call augur_queue to list the parked items. It also returns drafts_dir.\n"
    "2. For each item, do only research, reading or drafting. Save any draft as a file inside drafts_dir "
    "(write_file with an absolute path in drafts_dir).\n"
    "3. Close each item with augur_done: status \"done\" when the research or draft is ready "
    "(result_line says what is ready, draft_path when you wrote one), or \"needs_you\" when it needs "
    "the user's approval, a decision, a login, sending a message or any action outside reading and drafting "
    "(result_line says why in one line). If a tool is blocked, mark the item needs_you and move on.\n"
    "4. Call augur_report. Your final answer is exactly the caption lines it returns, then its MEDIA line."
)

SLOTS = [
    {"name": "time", "type": "time", "label": "What time?", "default": "17:30", "help": "24h local time"},
    {
        "name": "day",
        "type": "enum",
        "label": "Which day?",
        "default": "friday",
        "options": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
    },
    {
        "name": "deliver",
        "type": "enum",
        "label": "Where to deliver?",
        "default": "origin",
        "options": ["origin", "local", "telegram", "discord", "slack"],
        "strict": False,
    },
]


def register_blueprint(ctx: Any) -> None:
    ctx.register_automation_blueprint(
        BLUEPRINT_KEY,
        title=TITLE,
        description=(
            "Every week, research and draft the detours you parked, mark what needs you, "
            "and send the weekly attention report."
        ),
        category="productivity",
        schedule_template="{minute} {hour} * * {dow}",
        prompt_template=PROMPT,
        slots=SLOTS,
        deliver_default="origin",
        tags=["focus", "weekly", "report"],
    )


TITLE = "Augur Friday run"


class FridayRuns:
    """Which cron executions are Augur's Friday run.

    A run is recognised by any of: its execution id was seen with the marker in
    ``pre_llm_call``; its job id was seen with the marker before (persisted, so a
    reload or a skipped hook does not disarm the guard); or its job name is the
    blueprint's title. Cron identity itself is a ContextVar read per call.
    """

    def __init__(
        self,
        cron_lookup: Callable[[], Any],
        known_jobs: Callable[[], set[str]] = lambda: set(),
        maxlen: int = 32,
    ):
        self._cron_lookup = cron_lookup
        self._known_jobs = known_jobs
        self._ids: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def current(self) -> Any:
        try:
            return self._cron_lookup()
        except Exception:
            return None

    def mark(self, execution_id: str) -> None:
        with self._lock:
            if execution_id and execution_id not in self._ids:
                self._ids.append(execution_id)

    def is_friday(self, run: Any) -> bool:
        if run is None:
            return False
        execution_id = getattr(run, "execution_id", None)
        with self._lock:
            if execution_id and execution_id in self._ids:
                return True
        if str(getattr(run, "job_name", "") or "").strip() == TITLE:
            return True
        job_id = getattr(run, "job_id", None)
        return bool(job_id) and str(job_id) in self._known_jobs()

    def active(self) -> bool:
        return self.is_friday(self.current())

    def execution_id(self) -> Optional[str]:
        run = self.current()
        return getattr(run, "execution_id", None) if self.is_friday(run) else None


def _agent_cwd() -> Path:
    try:
        from agent.runtime_cwd import resolve_agent_cwd  # public Hermes API

        return Path(resolve_agent_cwd())
    except Exception:
        return Path(os.getcwd())


def resolve_path(raw: Any, cwd: Optional[Path] = None) -> Optional[Path]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(os.path.expanduser(raw.strip()))
    if not path.is_absolute():
        path = (cwd or _agent_cwd()) / path
    return Path(os.path.realpath(path))


def inside(path: Optional[Path], root: Path) -> bool:
    if path is None:
        return False
    root_real = Path(os.path.realpath(root))
    try:
        return os.path.commonpath([str(path), str(root_real)]) == str(root_real)
    except ValueError:
        return False


def write_targets(tool_name: str, args: dict[str, Any]) -> list[Any]:
    """Every file path a write tool would touch (V4A headers included, in any mode)."""
    targets: list[Any] = []
    if args.get("path"):
        targets.append(args.get("path"))
    if tool_name == "patch":
        text = args.get("patch")
        if isinstance(text, str) and text:
            targets.extend(m.group(1).strip() for m in _V4A_SINGLE.finditer(text))
            for m in _V4A_MOVE.finditer(text):
                targets.extend([m.group(1).strip(), m.group(2).strip()])
    return targets


def allowed(tool_name: str, args: Any, drafts_dir: Path, cwd: Optional[Path] = None) -> bool:
    """The Friday-run tool policy. Pure function, easy to test."""
    if not isinstance(tool_name, str):
        return False
    if tool_name.startswith(OWN_PREFIX) or tool_name in READ_TOOLS:
        return True
    if tool_name in WRITE_TOOLS:
        targets = write_targets(tool_name, args if isinstance(args, dict) else {})
        return bool(targets) and all(inside(resolve_path(t, cwd), drafts_dir) for t in targets)
    return False


def ensure_media(response_text: str, png_path: Optional[str]) -> Optional[str]:
    """The reply with a MEDIA line appended when it has none; ``None`` = leave unchanged."""
    if not png_path or not isinstance(response_text, str):
        return None
    if "MEDIA:" in response_text:
        return None
    if not os.path.isabs(png_path) or not os.path.isfile(png_path):
        return None
    return response_text.rstrip() + "\n" + f"MEDIA:{png_path}"
