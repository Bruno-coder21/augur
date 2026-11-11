"""Weekly report: PNG, text fallback, stale items, hidden priority threshold, metering."""

from __future__ import annotations

import builtins
import json
from datetime import timedelta

import pytest
from conftest import FakeOut, turn

from augur import demo, insight, metering, report
from augur.tools import make_handlers


def _week(app, clock):
    demo.load(app.store, clock())
    app.store.meta_set("insight_cache", None)  # make the insight path run for real


def test_png_is_valid_portrait_and_small(make_app, clock):
    pytest.importorskip("matplotlib")
    app = make_app()
    demo.load(app.store, clock())
    items = app.store.queue_list()
    app.store.queue_close(items[0]["id"], "done", "3 desks compared", None, clock())
    app.store.queue_close(items[3]["id"], "needs_you", "Needs you to send it", None, clock())
    app.store.queue_close(items[4]["id"], "dropped", "", None, clock())
    out = app.build_report()
    path = out["path"]
    assert path and path.endswith(".png")
    from PIL import Image

    with Image.open(path) as img:
        assert img.size == (1080, 1350)
    import os

    assert os.path.getsize(path) < 1_000_000
    assert "24%" in out["caption"] and "1 of 3" in out["caption"]
    assert "VDRI website" in out["caption"]


def test_text_fallback_without_matplotlib(make_app, clock, monkeypatch):
    app = make_app()
    demo.load(app.store, clock())
    real_import = builtins.__import__

    def no_mpl(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("no matplotlib")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mpl)
    out = json.loads(make_handlers(app)["augur_report"]({}))
    assert out["ok"] and "path" not in out
    assert "detours" in out["text"] and "VDRI launch" in out["text"]


def test_stale_parked_items_are_dropped(make_app, clock):
    app = make_app()
    app.store.queue_add("old idea", clock() - timedelta(days=15))
    app.store.queue_add("fresh idea", clock() - timedelta(days=2))
    app.build_report()
    statuses = {q["summary60"]: q["status"] for q in app.store.queue_list(None)}
    assert statuses == {"old idea": "dropped", "fresh idea": "parked"}


def _detours(app, clock, n):
    for i in range(n):
        app.store.insert_turn(ts=clock() - timedelta(hours=i + 1), session_id="s", summary=f"VDRI website task {i}",
                              goal=0, confidence=0.9)


def test_hidden_priority_needs_five(make_app, clock):
    answer = {"theme": "VDRI website", "count": 5, "examples": ["hero copy", "SEO"], "suggested_goal": "Ship it"}
    app = make_app(lambda kw: answer)
    _detours(app, clock, 4)
    assert app.build_report()["caption"].count("Hidden priority") == 0
    assert app.ctx.llm.calls == []  # fewer than 5 detours: no model call at all
    _detours(app, clock, 1)
    out = app.build_report()
    assert "Hidden priority spotted: \"VDRI website\"" in out["caption"]
    assert app.ctx.llm.calls[-1]["task"] == "augur_insight"
    calls = len(app.ctx.llm.calls)
    app.build_report()
    assert len(app.ctx.llm.calls) == calls  # cached for the same week and detours


def test_insight_validate_clamps():
    assert insight.validate({"theme": "x", "count": 4, "examples": []}, 10) is None
    assert insight.validate({"theme": "x", "count": 9, "examples": []}, 6)["count"] == 6
    assert insight.validate({"theme": None, "count": 9}, 9) is None
    assert insight.validate("nope", 9) is None


def test_metering_normalises_usage():
    assert metering.usage_tokens({"input_tokens": 10, "output_tokens": 5}) == 15
    assert metering.usage_tokens({"prompt_tokens": 10, "completion_tokens": 5}) == 15
    assert metering.usage_tokens({"total_tokens": 42, "input_tokens": 1}) == 42
    assert metering.usage_tokens(None) == 0
    assert metering.usage_tokens({"input_tokens": "x"}) == 0
    assert metering.human_tokens(1180) == "1.2k"


def test_tokens_land_on_the_turn_and_self_cost_is_recorded(make_app):
    app = make_app()
    turn(app, "draft the pilot pricing tiers for VDRI", turn_id="t9")
    app.on_post_api_request(session_id="s1", turn_id="t9", usage={"prompt_tokens": 1000, "completion_tokens": 200})
    app.on_post_api_request(session_id="s1", turn_id="t9", usage={"input_tokens": 300, "output_tokens": 50})
    assert app.store.get_turn(1)["tokens"] == 1550
    app.on_post_auxiliary_call(aux_task="augur_classifier", usage={"input_tokens": 100, "output_tokens": 20})
    app.on_post_auxiliary_call(aux_task="compression", usage={"input_tokens": 999, "output_tokens": 1})
    app.on_post_auxiliary_call(aux_task="augur_insight", usage=None, error="timeout")
    stats = app.week()
    assert stats.self_tokens == 120


def test_week_stats_percentages_add_to_100(make_app, clock):
    app = make_app()
    demo.load(app.store, clock())
    stats = report.week_stats(app.store, clock())
    assert sum(r.pct for r in stats.rows) == 100
    assert [r.pct for r in stats.rows] == [31, 36, 9, 24]
    assert stats.counted == 45 and stats.has_demo


def test_report_tool_returns_media_line(make_app, clock):
    pytest.importorskip("matplotlib")
    app = make_app(lambda kw: FakeOut(parsed=None))
    demo.load(app.store, clock())
    out = json.loads(make_handlers(app)["augur_report"]({}))
    assert out["media_line"] == f"MEDIA:{out['path']}"
