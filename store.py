"""SQLite storage: numbered migrations, short idempotent writes, one lock.

The database lives in ``plugin_data_dir("augur")/data.db`` (via Hermes's
``plugin_db``) and follows the active profile. All user text stored here is
already redacted, inert and length-limited (see ``privacy.py`` for the exact limits).
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import privacy

PLUGIN_NAME = "augur"

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS goals (
          slot INTEGER PRIMARY KEY CHECK (slot IN (1,2,3)),
          name TEXT NOT NULL, description TEXT, planned_pct INTEGER NOT NULL,
          color TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS turns (
          id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT,
          goal INTEGER, confidence REAL, summary60 TEXT, source TEXT,
          tokens INTEGER DEFAULT 0, nudged INTEGER DEFAULT 0,
          decision TEXT, decided_at TEXT);
        CREATE INDEX IF NOT EXISTS turns_ts ON turns(ts);
        CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id, id);
        CREATE TABLE IF NOT EXISTS queue (
          id INTEGER PRIMARY KEY, ts TEXT NOT NULL, summary60 TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'parked',
          result_line TEXT, draft_path TEXT, closed_at TEXT, source TEXT DEFAULT 'live');
        CREATE TABLE IF NOT EXISTS corrections (
          id INTEGER PRIMARY KEY, ts TEXT NOT NULL, summary60 TEXT NOT NULL,
          goal INTEGER NOT NULL, source TEXT DEFAULT 'live');
        CREATE TABLE IF NOT EXISTS self_cost (
          id INTEGER PRIMARY KEY, ts TEXT NOT NULL, task TEXT, tokens INTEGER,
          source TEXT DEFAULT 'live');
        """,
    ),
]

QUEUE_STATUSES = ("parked", "done", "needs_you", "dropped")
CLOSE_STATUSES = ("done", "needs_you", "dropped")
QUEUE_MAX_PARKED = 100
BUSY_TIMEOUT_MS = 1000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _default_connect() -> sqlite3.Connection:
    from plugins.plugin_storage import plugin_db  # public Hermes API

    return plugin_db(PLUGIN_NAME)


def default_data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir  # public Hermes API

    return Path(plugin_data_dir(PLUGIN_NAME))


class Store:
    """Thread-safe wrapper around one SQLite connection."""

    def __init__(self, connect: Callable[[], sqlite3.Connection] | str | Path | None = None):
        if connect is None:
            self._connect = _default_connect
        elif isinstance(connect, (str, Path)):
            path = str(connect)
            self._connect = lambda: sqlite3.connect(path, check_same_thread=False, timeout=5)
        else:
            self._connect = connect
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False

    # -- plumbing ---------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise RuntimeError("augur store is closed (plugin unloaded)")
            if self._conn is None:
                conn = self._connect()
                conn.row_factory = sqlite3.Row
                # hooks run on the user's turn: never wait seconds for another process's write lock
                conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
                self._conn = conn
                self._migrate(conn)
            return self._conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        current = int(row[0]) if row else 0
        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            with conn:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(version),),
                )

    def migrate(self) -> int:
        """Apply pending migrations (idempotent); returns the schema version."""
        with self._lock:
            self._migrate(self.conn)
            return int(self.meta_get("schema_version", "0"))

    def _write(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._lock:
            conn = self.conn
            with conn:
                cur = conn.execute(sql, tuple(params))
            return int(cur.lastrowid or 0)

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def _one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict[str, Any]]:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- meta -------------------------------------------------------------
    def meta_get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def meta_set(self, key: str, value: Optional[str]) -> None:
        if value is None:
            self._write("DELETE FROM meta WHERE key=?", (key,))
        else:
            self._write(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def meta_update(self, key: str, fn: Callable[[Optional[str]], Optional[str]]) -> None:
        """Atomic read-modify-write of one meta value."""
        with self._lock:
            self.meta_set(key, fn(self.meta_get(key)))

    # -- goals ------------------------------------------------------------
    def goals(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM goals ORDER BY slot")

    def has_goals(self) -> bool:
        return len(self.goals()) == 3

    def set_goals(self, goals: list[dict[str, Any]], now: datetime) -> None:
        from .assets.palette import goal_color

        if len(goals) != 3:
            raise ValueError("exactly 3 goals")
        if sum(int(g["planned_pct"]) for g in goals) != 100:
            raise ValueError("planned split must add up to 100")
        with self._lock:
            conn = self.conn
            with conn:
                conn.execute("DELETE FROM goals")
                conn.execute("DELETE FROM meta WHERE key='demo_goals'")  # these are the user's own goals now
                for slot, goal in enumerate(goals, start=1):
                    conn.execute(
                        "INSERT INTO goals(slot, name, description, planned_pct, color, created_at) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            slot,
                            privacy.clip(privacy.redact(goal["name"]), 40),
                            privacy.clip(privacy.redact(goal.get("description") or goal["name"]), 160),
                            int(goal["planned_pct"]),
                            goal_color(slot),
                            iso(now),
                        ),
                    )

    # -- turns ------------------------------------------------------------
    def insert_turn(
        self,
        *,
        ts: datetime,
        session_id: str,
        summary: str,
        source: str = "live",
        goal: Optional[int] = None,
        confidence: Optional[float] = None,
        tokens: int = 0,
        nudged: int = 0,
        decision: Optional[str] = None,
    ) -> int:
        return self._write(
            "INSERT INTO turns(ts, session_id, goal, confidence, summary60, source, tokens, nudged, decision) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (iso(ts), session_id, goal, confidence, privacy.summary60(summary), source, tokens, nudged, decision),
        )

    def update_turn(self, turn_id: int, **fields: Any) -> None:
        allowed = {"goal", "confidence", "summary60", "source", "nudged", "decision", "decided_at"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        if "summary60" in sets:
            sets["summary60"] = privacy.summary60(sets["summary60"])
        cols = ", ".join(f"{k}=?" for k in sets)
        self._write(f"UPDATE turns SET {cols} WHERE id=?", (*sets.values(), turn_id))

    def add_tokens(self, turn_id: int, tokens: int) -> None:
        if tokens > 0:
            self._write("UPDATE turns SET tokens = COALESCE(tokens, 0) + ? WHERE id=?", (int(tokens), turn_id))

    def get_turn(self, turn_id: int) -> Optional[dict[str, Any]]:
        return self._one("SELECT * FROM turns WHERE id=?", (turn_id,))

    def previous_classified(self, session_id: str, before_id: int) -> Optional[dict[str, Any]]:
        """The last request the model labeled in this session (inherited short replies are skipped)."""
        return self._one(
            "SELECT * FROM turns WHERE session_id=? AND id<? AND goal IS NOT NULL "
            "AND source!='inherited' ORDER BY id DESC LIMIT 1",
            (session_id, before_id),
        )

    def previous_user_turn(self, session_id: str, before_id: int) -> Optional[dict[str, Any]]:
        return self._one(
            "SELECT * FROM turns WHERE session_id=? AND id<? ORDER BY id DESC LIMIT 1",
            (session_id, before_id),
        )

    def last_classified(self, session_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """The last labeled request with a summary; scoped to the session when one is given."""
        where = "goal IS NOT NULL AND source NOT IN ('demo', 'inherited') AND COALESCE(summary60,'')!=''"
        if session_id:
            return self._one(f"SELECT * FROM turns WHERE session_id=? AND {where} ORDER BY id DESC LIMIT 1", (session_id,))
        return self._one(f"SELECT * FROM turns WHERE {where} ORDER BY id DESC LIMIT 1")

    def nudges_since(self, since: datetime) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM turns WHERE nudged=1 AND source!='demo' AND ts>=?", (iso(since),)
        )
        return int(row["n"]) if row else 0

    def last_do_now(self, session_id: str) -> Optional[dict[str, Any]]:
        return self._one(
            "SELECT * FROM turns WHERE session_id=? AND decision='do_now' ORDER BY decided_at DESC LIMIT 1",
            (session_id,),
        )

    def turns_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM turns WHERE ts>=? AND ts<? ORDER BY id", (iso(start), iso(end)))

    # -- queue ------------------------------------------------------------
    def queue_add(self, summary: str, now: datetime, source: str = "live") -> int:
        text = privacy.summary60(summary)
        if not text:
            raise ValueError("empty summary")
        if self.queue_size() >= QUEUE_MAX_PARKED:
            raise ValueError(f"the Queue is full ({QUEUE_MAX_PARKED} parked items)")
        return self._write(
            "INSERT INTO queue(ts, summary60, status, source) VALUES(?,?, 'parked', ?)", (iso(now), text, source)
        )

    def queue_get(self, item_id: int) -> Optional[dict[str, Any]]:
        return self._one("SELECT * FROM queue WHERE id=?", (item_id,))

    def prune(self, now: datetime, days: int = 90) -> int:
        """Retention: labeled requests older than ``days`` are deleted."""
        with self._lock:
            conn = self.conn
            with conn:
                cur = conn.execute("DELETE FROM turns WHERE ts<?", (iso(now - timedelta(days=days)),))
            return int(cur.rowcount or 0)

    def demo_is_stale(self, now: datetime) -> bool:
        """True when demo rows exist but the newest one has left the 7-day window."""
        row = self._one("SELECT MAX(ts) AS ts FROM turns WHERE source='demo'")
        return bool(row and row["ts"]) and parse_iso(row["ts"]) < now - timedelta(days=7)

    def queue_list(self, status: Optional[str] = "parked", limit: int = 1000) -> list[dict[str, Any]]:
        if status:
            return self._rows("SELECT * FROM queue WHERE status=? ORDER BY id LIMIT ?", (status, int(limit)))
        return self._rows("SELECT * FROM queue ORDER BY id LIMIT ?", (int(limit),))

    def queue_size(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM queue WHERE status='parked'")
        return int(row["n"]) if row else 0

    def queue_close(
        self, item_id: int, status: str, result: str, draft_path: Optional[str], now: datetime
    ) -> bool:
        if status not in CLOSE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(CLOSE_STATUSES)} (got {status!r})")
        self._write(
            "UPDATE queue SET status=?, result_line=?, draft_path=?, closed_at=? WHERE id=?",
            (status, privacy.result_line(result), draft_path, iso(now), item_id),
        )
        return self.queue_get(item_id) is not None

    def drop_stale(self, now: datetime, days: int = 14) -> int:
        cutoff = iso(now - timedelta(days=days))
        with self._lock:
            conn = self.conn
            with conn:
                cur = conn.execute(
                    "UPDATE queue SET status='dropped', closed_at=? WHERE status='parked' AND ts<?",
                    (iso(now), cutoff),
                )
            return int(cur.rowcount or 0)

    def queue_closed_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM queue WHERE status!='parked' AND closed_at>=? AND closed_at<? ORDER BY id",
            (iso(start), iso(end)),
        )

    # -- corrections ------------------------------------------------------
    def correction_add(self, summary: str, goal: int, now: datetime, source: str = "live") -> int:
        return self._write(
            "INSERT INTO corrections(ts, summary60, goal, source) VALUES(?,?,?,?)",
            (iso(now), privacy.summary60(summary), int(goal), source),
        )

    def corrections_recent(self, limit: int = 8) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM corrections WHERE source!='demo' ORDER BY id DESC LIMIT ?", (int(limit),)
        )

    def corrections_between(self, start: datetime, end: datetime) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM corrections WHERE ts>=? AND ts<?", (iso(start), iso(end))
        )
        return int(row["n"]) if row else 0

    # -- self cost --------------------------------------------------------
    def self_cost_add(self, task: str, tokens: int, now: datetime, source: str = "live") -> int:
        return self._write(
            "INSERT INTO self_cost(ts, task, tokens, source) VALUES(?,?,?,?)",
            (iso(now), task, int(tokens), source),
        )

    def self_tokens_between(self, start: datetime, end: datetime) -> int:
        row = self._one(
            "SELECT COALESCE(SUM(tokens),0) AS n FROM self_cost WHERE ts>=? AND ts<?", (iso(start), iso(end))
        )
        return int(row["n"]) if row else 0

    # -- demo -------------------------------------------------------------
    def has_demo(self) -> bool:
        row = self._one("SELECT COUNT(*) AS n FROM turns WHERE source='demo'")
        return bool(row and row["n"])

    def clear_demo(self) -> None:
        with self._lock:
            conn = self.conn
            with conn:
                conn.execute("DELETE FROM turns WHERE source='demo'")
                conn.execute("DELETE FROM queue WHERE source='demo'")
                conn.execute("DELETE FROM corrections WHERE source='demo'")
                conn.execute("DELETE FROM self_cost WHERE source='demo'")
                if self.meta_get("demo_goals") == "1":
                    conn.execute("DELETE FROM goals")
                conn.execute("DELETE FROM meta WHERE key IN ('demo_goals', 'insight_cache')")
