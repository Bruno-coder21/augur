"""Regressions found by the independent reviews (judge, quality and security passes)."""

from __future__ import annotations

from datetime import timedelta

from conftest import FakeOut, detour, on_goal, turn

from augur import demo
from augur.commands import Commands


def test_quickstart_order_keeps_real_goals(make_app):
    app = make_app(goals=False)
    c = Commands(app)
    c.augur("demo")
    out = c.augur("goals Ship beta, Write thesis, Learn Rust 50/30/20")
    assert "demo data was removed" in out
    c.augur("demo clear")
    assert [g["name"] for g in app.store.goals()] == ["Ship beta", "Write thesis", "Learn Rust"]
    assert not app.store.has_demo()


def test_no_user_text_is_stored_when_labeling_fails(make_app):
    answers = iter([RuntimeError("down"), FakeOut(parsed=None), detour(conf=0.2)])
    app = make_app(lambda kw: next(answers))
    secret = "My bank PIN is 4471 and my mother's maiden name is Oliveira"
    for i in range(3):
        turn(app, secret, turn_id=f"t{i}")
    turn(app, "PIN 4471 pls", turn_id="short")
    rows = app.store.turns_between(app.clock() - timedelta(days=1), app.clock() + timedelta(days=1))
    assert rows and all((r["summary60"] or "") == "" for r in rows)


def test_model_summary_is_what_gets_stored(make_app):
    app = make_app(lambda kw: on_goal(1, summary="Pilot pricing tiers"))
    turn(app, "Draft three pricing tiers for the product launch, with a discount for Acme Corp")
    assert app.store.get_turn(1)["summary60"] == "Pilot pricing tiers"


def test_forgotten_demo_expires_and_pinned_insight_only_with_demo(make_app, clock):
    app = make_app(lambda kw: on_goal(1))
    demo.load(app.store, clock())
    assert app.week().hidden["theme"] == "Personal website"
    clock.advance(days=8)
    stats = app.week()
    assert stats.hidden is None and not stats.has_demo
    assert not app.store.has_demo() and app.store.queue_size() == 0  # demo queue gone too
    assert app.store.has_goals()  # the user's own goals stay


def test_answer_to_a_nudge_is_not_a_request_and_park_breaks_the_streak(make_app):
    app = make_app(lambda kw: detour())
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    assert turn(app, "and a playlist for that dinner party", turn_id="b")
    app.on_post_llm_call(session_id="s1", turn_id="b")
    assert turn(app, "Park it", turn_id="c") is None
    from augur.tools import make_handlers

    make_handlers(app)["augur_park"]({"summary": "Dinner playlist"}, session_id="s1")
    app.on_post_llm_call(session_id="s1", turn_id="c")
    counted = [t for t in app.store.turns_between(app.clock() - timedelta(1), app.clock() + timedelta(1))]
    assert len(counted) == 2  # "Park it" did not become a 3rd request
    assert turn(app, "what wine goes with a mushroom risotto", turn_id="d") is None  # new streak starts


def test_acknowledgements_are_not_counted_and_inherited_rows_do_not_build_streaks(make_app):
    answers = iter([detour(), detour()])
    app = make_app(lambda kw: next(answers))
    turn(app, "find a good recipe for a dinner party", turn_id="a")
    turn(app, "thanks!", turn_id="b")
    turn(app, "even shorter", turn_id="c")
    rows = app.store.turns_between(app.clock() - timedelta(1), app.clock() + timedelta(1))
    assert [r["goal"] for r in rows] == [0, 0]  # "thanks!" left no row
    assert rows[1]["source"] == "inherited"
    # the next detour's previous *labeled* request is still the first one → nudge, but only once
    assert turn(app, "and a playlist for that dinner party", turn_id="d") is not None


def test_fix_never_shows_another_sessions_request(make_app):
    app = make_app(lambda kw: on_goal(1, summary="Session A secret plan"))
    turn(app, "draft the pilot pricing tiers for the launch", session="A")
    out = Commands(app).augur("fix", session_id="B")
    assert "Session A" not in out and "Nothing to fix" in out


def test_unattended_surfaces_are_not_labeled(make_app, monkeypatch):
    app = make_app(lambda kw: detour())
    assert app.on_pre_llm_call(session_id="s", user_message="plan a trip to Rome next spring", turn_id="t",
                               platform="kanban") is None
    monkeypatch.setenv("HERMES_KANBAN_TASK", "task-1")
    assert app.on_pre_llm_call(session_id="s", user_message="plan a trip to Rome next spring", turn_id="u",
                               platform="cli") is None
    assert app.ctx.llm.calls == []


def test_panel_warns_when_labels_are_slow(make_app):
    app = make_app(lambda kw: on_goal(1), delay=0.3, budget=0.05)
    for i in range(10):
        turn(app, f"draft the pilot pricing tiers for the launch v{i}", turn_id=f"t{i}")
    bad, total = app.health()
    assert (bad, total) == (10, 10)
    assert "Pin a fast model" in Commands(app).augur("", platform="telegram")


def test_caption_mentions_parked_items_waiting(make_app):
    app = make_app()
    app.store.queue_add("compare standing desks", app.clock())
    out = app.build_report()
    assert "1 parked item waits" in out["caption"]


def test_closed_store_never_reopens(make_app):
    app = make_app(lambda kw: on_goal(1))
    app.close()
    import pytest

    with pytest.raises(RuntimeError):
        app.store.goals()
    assert turn(app, "draft the pilot pricing tiers for the launch") is None  # silent, no crash


def test_caption_plural_and_eval_cost_not_counted(make_app, clock):
    from augur import report

    app = make_app()
    for summary in ("a", "b"):
        app.store.queue_add(summary, clock())
    items = app.store.queue_list()
    app.store.queue_close(items[0]["id"], "needs_you", "x", None, clock())
    app.store.queue_close(items[1]["id"], "done", "y", None, clock())
    stats = report.week_stats(app.store, clock())
    assert "1 needs you" in report.caption_lines(stats, "en")[0]
    from augur.core import EVALUATING

    token = EVALUATING.set(True)
    app.on_post_auxiliary_call(aux_task="augur_classifier", usage={"total_tokens": 999})
    EVALUATING.reset(token)
    assert app.week().self_tokens == 0
