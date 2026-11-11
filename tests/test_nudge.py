"""The nudge: 2nd detour in a row, and every reason to stay quiet."""

from __future__ import annotations

from conftest import FakeCron, detour, on_goal, turn


def test_one_detour_only_records(make_app):
    app = make_app(lambda kw: detour())
    assert turn(app, "find a good recipe for a dinner party", turn_id="a") is None
    assert app.store.get_turn(1)["goal"] == 0


def test_second_detour_in_a_row_nudges_without_blocking(make_app):
    app = make_app(lambda kw: detour(closest=2))
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    out = turn(app, "and a playlist for that dinner party", turn_id="b")
    assert set(out) == {"context"}  # never {"action": "block"}
    assert "Do it now" in out["context"] and "Park it" in out["context"]
    assert "Hackathons" in out["context"]  # closest goal named
    assert "bussola_park" in out["context"]
    assert app.store.get_turn(2)["nudged"] == 1


def test_portuguese_nudge(make_app):
    app = make_app(lambda kw: detour(), config={"language": "pt"})
    turn(app, "acha uma receita boa para um jantar", turn_id="a")
    out = turn(app, "e uma playlist para esse jantar", turn_id="b")
    assert "Estacionar" in out["context"]


def test_detours_31_minutes_apart_are_silent(make_app, clock):
    app = make_app(lambda kw: detour())
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    clock.advance(minutes=31)
    assert turn(app, "and a playlist for that dinner party", turn_id="b") is None


def test_goal_between_detours_breaks_the_streak(make_app):
    answers = iter([detour(), on_goal(1), detour()])
    app = make_app(lambda kw: next(answers))
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    turn(app, "draft the pilot pricing tiers for VDRI", turn_id="b")
    assert turn(app, "and a playlist for that dinner party", turn_id="c") is None


def test_low_confidence_second_detour_is_silent(make_app):
    answers = iter([detour(), detour(conf=0.5)])
    app = make_app(lambda kw: next(answers))
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    assert turn(app, "and a playlist for that dinner party", turn_id="b") is None


def _nudge_then(app, ids=("a", "b")):
    turn(app, "find a good recipe for a dinner party", turn_id=ids[0])
    return turn(app, "and a playlist for that dinner party", turn_id=ids[1])


def test_text_answer_without_park_records_do_now_and_cooldown(make_app, clock):
    app = make_app(lambda kw: detour())
    assert _nudge_then(app)
    app.on_post_llm_call(session_id="s1", turn_id="b")  # model asked in text; no clarify
    clock.advance(minutes=1)
    assert turn(app, "do it now please, go ahead", turn_id="c") is None  # the answer turn never nudges
    app.on_post_llm_call(session_id="s1", turn_id="c")
    assert app.store.get_turn(2)["decision"] == "do_now"
    clock.advance(minutes=5)
    assert turn(app, "what wine goes with risotto tonight", turn_id="d") is None  # cooldown
    clock.advance(minutes=50)
    turn(app, "find me a dessert recipe with lemons", turn_id="e")
    assert turn(app, "and a cocktail that matches the dessert", turn_id="f") is not None


def test_clarify_in_same_turn_without_park_is_do_now(make_app):
    app = make_app(lambda kw: detour())
    assert _nudge_then(app)
    assert app.on_pre_tool_call(tool_name="clarify", args={}, session_id="s1", turn_id="b") is None
    app.on_post_llm_call(session_id="s1", turn_id="b")
    assert app.store.get_turn(2)["decision"] == "do_now"


def test_park_tool_records_park(make_app):
    app = make_app(lambda kw: detour())
    assert _nudge_then(app)
    app.on_pre_tool_call(tool_name="clarify", args={}, session_id="s1", turn_id="b")
    import json

    from bussola.tools import make_handlers

    out = json.loads(make_handlers(app)["bussola_park"]({"summary": "Dinner party playlist"}, session_id="s1"))
    assert out["ok"] and out["queue_size"] == 1
    app.on_post_llm_call(session_id="s1", turn_id="b")
    assert app.store.get_turn(2)["decision"] == "park"
    assert app.store.queue_list()[0]["summary60"] == "Dinner party playlist"


def test_daily_limit(make_app, clock):
    app = make_app(lambda kw: detour(), config={"max_nudges_per_day": 1, "nudge_cooldown_minutes": 0})
    assert _nudge_then(app, ("a", "b"))
    app.on_pre_tool_call(tool_name="clarify", args={}, session_id="s1", turn_id="b")
    app.on_post_llm_call(session_id="s1", turn_id="b")
    clock.advance(minutes=2)
    turn(app, "find me a dessert recipe with lemons", turn_id="c")
    assert turn(app, "and a cocktail that matches the dessert", turn_id="d") is None


def test_pause_and_cron_are_silent(make_app, clock):
    app = make_app(lambda kw: detour())
    app.pause(60)
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    assert turn(app, "and a playlist for that dinner party", turn_id="b") is None
    assert app.ctx.llm.calls == []
    app.pause(None)
    app.ctx.cron = FakeCron()
    assert turn(app, "and a playlist for that dinner party", turn_id="c") is None
    assert app.ctx.llm.calls == []


def test_sessions_do_not_mix(make_app):
    app = make_app(lambda kw: detour())
    turn(app, "find a good recipe for a dinner party", session="s1", turn_id="a")
    assert turn(app, "and a playlist for that dinner party", session="s2", turn_id="b") is None


def test_hook_errors_are_silent(make_app, monkeypatch):
    app = make_app(lambda kw: detour())
    monkeypatch.setattr(app.store, "insert_turn", lambda **kw: (_ for _ in ()).throw(RuntimeError("db locked")))
    assert turn(app, "find a good recipe for a dinner party") is None
