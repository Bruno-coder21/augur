"""Small units the end-to-end tests do not pin down."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone

from conftest import FakeCtx, on_goal

from augur import classifier as clf
from augur import commands, config, nudge, report
from augur.store import Store


def test_config_coerces_or_falls_back():
    ctx = FakeCtx(config={"language": "PT", "max_nudges_per_day": "5", "min_confidence": 7,
                          "nudge_cooldown_minutes": "soon"})
    assert config.get(ctx, "language") == "pt"
    assert config.get(ctx, "max_nudges_per_day") == 5
    assert config.get(ctx, "min_confidence") == 0.6  # out of range → default
    assert config.get(ctx, "nudge_cooldown_minutes") == 45  # not a number → default
    assert config.get(FakeCtx(config={"language": "fr"}), "language") == "en"


def test_retention_prunes_old_rows_and_files(tmp_path):
    now = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
    store = Store(tmp_path / "db.sqlite")
    store.insert_turn(ts=now - timedelta(days=91), session_id="s", summary="", goal=1, confidence=1)
    store.insert_turn(ts=now - timedelta(days=5), session_id="s", summary="", goal=1, confidence=1)
    assert store.prune(now) == 1
    assert len(store.turns_between(now - timedelta(days=400), now)) == 1
    data = tmp_path / "data"
    (data / "drafts").mkdir(parents=True)
    old_png, new_png, old_draft = data / "report-2026-01-01.png", data / "report-2026-11-10.png", data / "drafts" / "a.md"
    for path in (old_png, new_png, old_draft):
        path.write_text("x")
    stamp = (now - timedelta(days=60)).timestamp()
    os.utime(old_png, (stamp, stamp))
    os.utime(old_draft, (stamp, stamp))
    assert report.prune_files(data, now) == 2
    assert new_png.exists() and not old_png.exists() and not old_draft.exists()
    store.close()


def test_busy_classifier_stays_silent():
    gate = threading.Event()

    class Slow:
        def complete_structured(self, **kw):
            gate.wait(2)
            raise RuntimeError("released")

    c = clf.Classifier(lambda: Slow(), budget=0.01, workers=1)
    outcomes = [c.classify([], [], [], "x", wait=False)[1] for _ in range(3)]
    assert outcomes == ["async", "async", "busy"]  # 2 in flight max (workers * 2), then silence
    gate.set()
    assert c.wait_idle(5)
    c.shutdown()


def test_week_label_across_months_and_in_portuguese():
    stats = report.WeekStats(
        start=datetime(2026, 10, 29, 15, tzinfo=timezone.utc), end=datetime(2026, 11, 5, 15, tzinfo=timezone.utc),
        rows=[], counted=0, tokens=0, detour_pct=0, parked=0, closed=[], corrections=0, self_tokens=0, has_demo=False,
    )
    assert report.week_label(stats, "en").startswith("Oct 30") and report.week_label(stats, "en").endswith("Nov 5")
    assert "out" in report.week_label(stats, "pt") and "nov" in report.week_label(stats, "pt")


def test_parse_goals_in_portuguese():
    goals = commands.parse_goals("lançar o beta, hackathon e espanhol")
    assert [g["name"] for g in goals] == ["Lançar o beta", "Hackathon", "Espanhol"]


def test_clock_label_is_localized():
    moment = datetime(2026, 11, 11, 18, 30, tzinfo=timezone.utc)  # a Wednesday
    assert commands._clock_label(moment, "pt").split()[0] in {"qua", "qui", "ter"}  # depends on server TZ
    assert commands._clock_label(moment, "en").split()[0] in {"Wed", "Thu", "Tue"}


def test_session_states_expire():
    states = nudge.SessionStates(ttl=0.0)
    states.get("a").pending_row = 3
    states.get("b")  # touching another session sweeps expired ones
    assert states.peek("a") is None


def test_label_prompt_includes_corrections_and_goal_descriptions():
    blocks = clf.build_input(
        [{"slot": 1, "name": "Beta", "description": "Beta: first 10 users"}],
        [{"summary60": "Landing page copy", "goal": 1}],
        [],
        "rewrite the landing page hero",
    )
    text = blocks[0]["text"]
    assert "Beta — Beta: first 10 users" in text and '"Landing page copy" → 1 (Beta)' in text
    assert clf.parse(on_goal(2), 0.1).goal == 2
