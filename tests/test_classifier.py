"""Classifier: time budget, silence on every failure, inheritance, redaction."""

from __future__ import annotations

import time

from conftest import FakeOut, detour, on_goal, turn

from bussola import classifier as clf


def test_slow_model_returns_none_fast_and_records_late_result(make_app):
    app = make_app(lambda kw: detour(), delay=5.0, budget=1.5)
    started = time.monotonic()
    out = turn(app, "help me plan a weekend trip to Rome in April")
    elapsed = time.monotonic() - started
    assert out is None
    assert elapsed < 1.6
    row = app.store.last_classified()
    assert row is None  # nothing classified yet
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        row = app.store.get_turn(1)
        if row and row["goal"] is not None:
            break
        time.sleep(0.05)
    assert row["goal"] == 0
    assert row["source"] == "background"
    assert row["nudged"] == 0


def test_invalid_json_exception_and_parsed_none_are_silent(make_app):
    answers = iter([
        FakeOut(parsed=None, text="not json"),
        RuntimeError("provider down"),
        ValueError("schema mismatch"),
        {"goal": 7, "confidence": 0.9},
        {"goal": "x"},
    ])
    app = make_app(lambda kw: next(answers))
    for i in range(5):
        assert turn(app, f"compare the best espresso machines, round {i}", turn_id=f"t{i}") is None
    assert all(t["goal"] is None for t in app.store.turns_between(app.clock() - __import__("datetime").timedelta(1),
                                                                   app.clock() + __import__("datetime").timedelta(1)))


def test_low_confidence_is_silent_and_not_counted(make_app):
    app = make_app(lambda kw: detour(conf=0.4))
    assert turn(app, "what is the best espresso machine", turn_id="a") is None
    assert turn(app, "and the best grinder for espresso", turn_id="b") is None
    assert app.store.last_classified() is None


def test_short_message_inherits_previous_goal_without_model_call(make_app):
    app = make_app(lambda kw: on_goal(2))
    turn(app, "write the pytest tests for the classifier", turn_id="a")
    calls = len(app.ctx.llm.calls)
    assert turn(app, "shorter", turn_id="b") is None
    assert len(app.ctx.llm.calls) == calls
    assert app.store.get_turn(2)["goal"] == 2


def test_continues_previous_inherits_goal(make_app):
    answers = iter([on_goal(3), detour(cont=True)])
    app = make_app(lambda kw: next(answers))
    turn(app, "fix the grammar in my pitch paragraph please", turn_id="a")
    turn(app, "now do the same with the second paragraph", turn_id="b")
    assert app.store.get_turn(2)["goal"] == 3


def test_neutral_is_not_counted(make_app):
    app = make_app(lambda kw: {"goal": -1, "confidence": 0.95, "continues_previous": False, "closest_goal": 1,
                               "summary60": "small talk"})
    assert turn(app, "good morning! how are you doing today?") is None
    assert app.store.get_turn(1)["goal"] is None


def test_prompt_uses_blocks_task_and_redacts(make_app):
    app = make_app(lambda kw: on_goal(1))
    turn(app, "deploy with key sk-abcdefghijklmnopqrstuvwxyz123456 to the pilot server",
         history=[{"role": "user", "content": "earlier message about pricing"},
                  {"role": "assistant", "content": "ok"},
                  {"role": "user", "content": "deploy with key sk-abcdefghijklmnopqrstuvwxyz123456 to the pilot"}])
    call = app.ctx.llm.calls[-1]
    assert call["task"] == "bussola_classifier"
    assert call["temperature"] == 0
    text = call["input"][0]["text"]
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in text
    assert "earlier message about pricing" in text
    assert "VDRI launch" in text


def test_skips_slash_commands_subagents_cron_and_missing_goals(make_app):
    app = make_app(lambda kw: detour())
    assert turn(app, "/bussola fix") is None
    assert app.ctx.llm.calls == []
    assert app.on_pre_llm_call(session_id="s", user_message="plan a trip to Rome next spring",
                               turn_id="t", parent_session_id="parent") is None
    assert app.ctx.llm.calls == []
    from conftest import FakeCron

    app.ctx.cron = FakeCron()
    assert turn(app, "plan a trip to Rome next spring") is None
    assert app.ctx.llm.calls == []
    app.ctx.cron = None
    bare = make_app(lambda kw: detour(), goals=False)
    assert turn(bare, "plan a trip to Rome next spring") is None
    assert bare.ctx.llm.calls == []


def test_parse_clamps_and_summarises():
    r = clf.parse({"goal": 1, "confidence": 0.8, "continues_previous": False, "closest_goal": 9,
                   "summary60": "x" * 200}, 0.1)
    assert r.closest_goal == 1 and len(r.summary60) <= 60
    assert clf.parse({"goal": 1}, 0.1) is None
    assert clf.parse([], 0.1) is None


def test_previous_user_messages_excludes_current_and_commands():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "/bussola"},
        {"role": "user", "content": "second"},
        {"role": "user", "content": [{"type": "text", "text": "third"}]},
        {"role": "user", "content": "current"},
    ]
    assert clf.previous_user_messages(history) == ["second", "third"]
