"""Classifier: time budget, silence on every failure, inheritance, redaction."""

from __future__ import annotations

import time
from datetime import timedelta

from conftest import FakeOut, detour, on_goal, turn

from augur import classifier as clf


def test_slow_model_returns_none_fast_and_records_late_result(make_app):
    calls = {"n": 0}

    def responder(kw):
        calls["n"] += 1
        if calls["n"] == 2:
            time.sleep(0.6)  # the 2nd detour in a row: the only time Augur holds the turn
        return detour()

    app = make_app(responder, budget=0.2)
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    started = time.monotonic()
    out = turn(app, "help me plan a weekend trip to Rome in April", turn_id="b", drain=False)
    elapsed = time.monotonic() - started
    assert out is None
    assert elapsed < 0.5  # held for the budget, not for the model
    assert app.store.get_turn(2)["goal"] is None  # nothing yet
    app.classifier.wait_idle(10)
    row = app.store.get_turn(2)
    assert row["goal"] == 0
    assert row["source"] == "background"
    assert row["nudged"] == 0  # too late to ask first: a 🧭 note is queued for the reply...
    assert "🧭" in app.on_transform_llm_output(response_text="Rome plan.", session_id="s1", turn_id="b")
    assert app.store.get_turn(2)["nudged"] == 1  # ...and counts only once it is shown
    assert app.health() == (1, 2)


def test_first_request_never_holds_the_turn(make_app):
    app = make_app(lambda kw: detour(), delay=1.0)
    started = time.monotonic()
    assert turn(app, "find a good recipe for a dinner party", drain=False) is None
    assert time.monotonic() - started < 0.5  # labeled in the background, not held for the 1 s model call
    app.classifier.wait_idle(5)
    assert app.store.get_turn(1)["goal"] == 0 and app.store.get_turn(1)["source"] == "live"


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
    day = timedelta(days=1)
    assert all(t["goal"] is None for t in app.store.turns_between(app.clock() - day, app.clock() + day))


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
    fake_key = "sk-" + "abcdefghij" * 3  # built at runtime so secret scanners stay quiet
    turn(app, f"deploy with key {fake_key} to the pilot server",
         history=[{"role": "user", "content": "earlier message about pricing"},
                  {"role": "assistant", "content": "ok"},
                  {"role": "user", "content": f"deploy with key {fake_key} to the pilot"}])
    call = app.ctx.llm.calls[-1]
    assert call["task"] == "augur_classifier"
    assert call["temperature"] == 0
    text = call["input"][0]["text"]
    assert fake_key not in text
    assert "earlier message about pricing" in text
    assert "Product launch" in text


def test_skips_slash_commands_subagents_cron_and_missing_goals(make_app):
    app = make_app(lambda kw: detour())
    assert turn(app, "/augur fix") is None
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
        {"role": "user", "content": "/augur"},
        {"role": "user", "content": "second"},
        {"role": "user", "content": [{"type": "text", "text": "third"}]},
        {"role": "user", "content": "current"},
    ]
    assert clf.previous_user_messages(history) == ["second", "third"]


def test_schemas_are_strict_mode_compatible():
    """Anthropic structured outputs reject objects without additionalProperties: false."""
    from augur import commands, insight

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
            for key in ("minimum", "maximum", "minLength", "maxLength"):
                assert key not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for schema in (clf.SCHEMA, insight.SCHEMA, commands.GOALS_SCHEMA):
        walk(schema)
