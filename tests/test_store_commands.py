"""Storage rules, commands and tools."""

from __future__ import annotations

import json
import sqlite3

from conftest import detour, on_goal, turn

from bussola import commands as cmd_mod
from bussola import demo
from bussola.commands import Commands
from bussola.store import Store
from bussola.tools import make_handlers


# ---------------------------------------------------------------- storage


def test_migrations_twice_keep_data(tmp_path):
    path = tmp_path / "db.sqlite"
    s1 = Store(path)
    assert s1.migrate() == 1
    s1.queue_add("keep me", __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    s1.close()
    s2 = Store(path)
    assert s2.migrate() == 1
    assert s2.migrate() == 1
    assert [q["summary60"] for q in s2.queue_list()] == ["keep me"]
    s2.close()


def test_nothing_longer_than_60_chars_of_user_text_is_stored(make_app, tmp_path):
    long_message = "please " + "research the history of every single espresso machine ever made " * 20
    app = make_app(lambda kw: detour(summary="x" * 300))
    turn(app, long_message, turn_id="a")
    turn(app, long_message, turn_id="b")
    make_handlers(app)["bussola_park"]({"summary": long_message}, session_id="s1")
    Commands(app).park(long_message)
    app.store.correction_add(long_message, 1, app.clock())
    conn = sqlite3.connect(tmp_path / "db0.sqlite")
    for table, col in (("turns", "summary60"), ("queue", "summary60"), ("corrections", "summary60")):
        for (value,) in conn.execute(f"SELECT {col} FROM {table}"):
            assert value is None or len(value) <= 60, (table, value)
    conn.close()


def test_secrets_are_redacted_before_storage(make_app):
    app = make_app(lambda kw: on_goal(1, summary="token ghp_abcdefghijklmnopqrstuvwxyz0123"))
    turn(app, "use ghp_abcdefghijklmnopqrstuvwxyz0123 to push the deck")
    row = app.store.get_turn(1)
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123" not in (row["summary60"] or "")


# ---------------------------------------------------------------- goals


def test_parse_goals_variants():
    assert [g["name"] for g in cmd_mod.parse_goals("launching VDRI, hackathons, English")] == [
        "Launching VDRI", "Hackathons", "English"]
    assert [g["name"] for g in cmd_mod.parse_goals("VDRI launch, hackathons and English")] == [
        "VDRI launch", "Hackathons", "English"]
    goals = cmd_mod.parse_goals('"VDRI launch: ship the beta" "Hackathons" "English"')
    assert goals[0]["name"] == "VDRI launch" and "ship the beta" in goals[0]["description"]
    assert cmd_mod.parse_goals("just one big thing") is None
    assert cmd_mod.parse_split("a, b, c 50/30/20") == ("a, b, c", [50, 30, 20])
    assert not cmd_mod.valid_split([50, 30, 30])


def test_goals_inline_with_split(make_app):
    app = make_app(goals=False)
    out = Commands(app).bussola('goals "VDRI launch" "Hackathons" "English" 50/30/20')
    assert "Goals saved" in out
    assert [g["planned_pct"] for g in app.store.goals()] == [50, 30, 20]
    assert app.ctx.asked == []


def test_goals_ask_split_with_buttons(make_app):
    app = make_app(goals=False)
    app.ctx.choices = ["40/40/20"]
    out = Commands(app).bussola("goals launching VDRI, hackathons, English")
    assert "Goals saved" in out
    question, choices = app.ctx.asked[0]
    assert "Launching VDRI" in question and len(choices) == 4
    assert [g["planned_pct"] for g in app.store.goals()] == [40, 40, 20]


def test_goals_cancel_or_no_buttons_saves_nothing(make_app):
    app = make_app(goals=False)
    out = Commands(app).bussola("goals launching VDRI, hackathons, English")
    assert "not saved" in out and not app.store.has_goals()


def test_goals_free_text_uses_model_extraction(make_app):
    extracted = {"goals": [{"name": "VDRI Launch", "description": "launch"},
                           {"name": "Hackathon", "description": "plugin"},
                           {"name": "English", "description": "practice"}]}
    app = make_app(lambda kw: extracted, goals=False)
    out = Commands(app).bussola("goals this week I mostly want to launch VDRI then the hackathon plus english 50/30/20")
    assert "Goals saved" in out
    assert app.ctx.llm.calls[-1]["task"] == "bussola_classifier"


def test_goals_bad_split(make_app):
    app = make_app(goals=False)
    assert "add up to 100" in Commands(app).bussola("goals a, b, c 50/30/30")


def test_panel_onboarding_then_panel(make_app):
    app = make_app(goals=False)
    assert "/bussola goals" in Commands(app).bussola("")
    demo.load(app.store, app.clock())
    text = Commands(app).bussola("", platform="telegram")
    assert "VDRI launch" in text and "24%" in text and "\x1b[" not in text
    assert "Hidden priority" in text
    colored = Commands(app).bussola("", platform="cli")
    assert "\x1b[38;2;59;130;246m" in colored  # goal 1 blue


# ---------------------------------------------------------------- fix and learning


def test_fix_records_correction_used_in_next_prompt(make_app):
    app = make_app(lambda kw: detour(summary="Tune Hermes plugin docs"))
    turn(app, "polish the docs page for my Hermes plugin", turn_id="a")
    app.ctx.choices = ["2"]
    out = Commands(app).bussola("fix", session_id="s1")
    assert "Hackathons" in out
    assert app.store.get_turn(1)["goal"] == 2
    turn(app, "polish the README for my Hermes plugin", turn_id="b")
    prompt = app.ctx.llm.calls[-1]["input"][0]["text"]
    assert '"Tune Hermes plugin docs" → 2 (Hackathons)' in prompt


def test_fix_inline_and_nothing_to_fix(make_app):
    app = make_app(lambda kw: on_goal(1))
    assert "Nothing to fix" in Commands(app).bussola("fix")
    turn(app, "draft the pilot pricing tiers for VDRI")
    assert "Detour" in Commands(app).bussola("fix detour")
    assert app.store.get_turn(1)["goal"] == 0


# ---------------------------------------------------------------- pause, demo, park, report


def test_pause_and_resume(make_app):
    app = make_app()
    assert "paused until" in Commands(app).bussola("pause 2h")
    assert app.paused_until() is not None
    assert "back on" in Commands(app).bussola("pause off")
    assert app.paused_until() is None
    assert "Usage" in Commands(app).bussola("pause forever")


def test_demo_load_and_clear_keeps_real_data(make_app):
    app = make_app(lambda kw: on_goal(1))
    turn(app, "draft the pilot pricing tiers for VDRI")
    out = Commands(app).bussola("demo")
    assert "45 requests" in out and "kept" in out
    assert app.ctx.llm.calls.__len__() == 1  # demo made no model call
    Commands(app).bussola("demo clear")
    assert not app.store.has_demo()
    assert app.store.has_goals() and app.store.get_turn(1)["goal"] == 1


def test_park_command(make_app):
    app = make_app()
    assert "Usage" in Commands(app).park("")
    assert "Parked #1" in Commands(app).park("compare standing desks under $400")
    assert app.store.queue_size() == 1


def test_report_command_media_only_on_messaging(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(app, "build_report", lambda: {"path": "/tmp/r.png", "caption": "cap", "text": "t"})
    assert "MEDIA:/tmp/r.png" in Commands(app).bussola("report", platform="telegram")
    assert "MEDIA:" not in Commands(app).bussola("report", platform="cli")


def test_commands_never_raise(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(app, "week", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert "went wrong" in Commands(app).bussola("")
    assert "commands" in Commands(app).bussola("nonsense").lower()


# ---------------------------------------------------------------- tools


def test_tools_queue_done_and_errors(make_app):
    app = make_app()
    h = make_handlers(app)
    assert json.loads(h["bussola_park"]({}))["ok"] is False
    pid = json.loads(h["bussola_park"]({"summary": "Research standing desks"}))["id"]
    q = json.loads(h["bussola_queue"]({}))
    assert q["items"][0]["summary"] == "Research standing desks" and q["drafts_dir"].endswith("drafts")
    draft = app.drafts_dir / "desks.md"
    draft.write_text("# desks")
    done = json.loads(h["bussola_done"]({"id": pid, "status": "done", "result_line": "3 desks compared",
                                         "draft_path": str(draft)}))
    assert done["ok"] and done["remaining"] == 0
    bad = json.loads(h["bussola_done"]({"id": pid, "status": "done", "result_line": "x",
                                        "draft_path": "/etc/passwd"}))
    assert bad["ok"] is False
    assert json.loads(h["bussola_done"]({"id": 999, "status": "done", "result_line": "x"}))["ok"] is False
    assert json.loads(h["bussola_done"]({"id": pid, "status": "parked", "result_line": "x"}))["ok"] is False
    assert json.loads(h["bussola_queue"]("not a dict"))["ok"] is True


# ---------------------------------------------------------------- desktop chip


def test_status_rpc_and_emit(make_app):
    app = make_app(lambda kw: on_goal(2))
    assert app.rpc_status({}, session_id="s1")["on_goals_pct"] == 0
    turn(app, "write the pytest tests for the classifier")
    status = app.rpc_status({"session_id": "s1"})
    assert status["current_goal"] == "Hackathons" and status["on_goals_pct"] == 100
    sid, event, payload = app.ctx.emitted[-1]
    assert (sid, event) == ("s1", "status.changed") and payload["current_goal"] == "Hackathons"
    import json

    json.dumps(status)  # JSON-safe for the RPC wire
    bare = make_app(goals=False)
    assert bare.rpc_status({}) == {"has_goals": False, "language": "en"}
