"""Friday run: identification, the read-and-draft guard, and the MEDIA guarantee."""

from __future__ import annotations

from pathlib import Path

from conftest import FakeCron, turn

from bussola import friday


def _start_friday(app, execution_id="exec-1"):
    app.ctx.cron = FakeCron(execution_id=execution_id)
    assert turn(app, friday.PROMPT, session="cron_s", turn_id="ft") is None
    assert app.fridays.active()


def test_marker_marks_only_bussola_runs(make_app):
    app = make_app()
    app.ctx.cron = FakeCron(execution_id="other-job", job_id="job-inbox", job_name="Inbox digest")
    turn(app, "Summarize my inbox every morning", session="cron_s", turn_id="x")
    assert not app.fridays.active()
    assert app.on_pre_tool_call(tool_name="terminal", args={"command": "ls"}) is None
    _start_friday(app)
    assert app.store.meta_get("last_friday_run")


def test_guard_policy(make_app, tmp_path):
    app = make_app()
    _start_friday(app)
    drafts = app.drafts_dir
    ok = lambda name, args: app.on_pre_tool_call(tool_name=name, args=args) is None  # noqa: E731
    assert ok("bussola_queue", {})
    assert ok("bussola_done", {"id": 1})
    assert ok("web_search", {"query": "standing desks"})
    assert ok("web_extract", {"urls": ["https://example.com"]})
    assert ok("read_file", {"path": "/etc/hostname"})
    assert ok("write_file", {"path": str(drafts / "desk.md"), "content": "x"})
    assert not ok("write_file", {"path": str(drafts / ".." / ".." / "x.md"), "content": "x"})
    assert not ok("write_file", {"path": str(tmp_path / "elsewhere.md"), "content": "x"})
    assert not ok("write_file", {"content": "no path"})
    assert not ok("terminal", {"command": "echo hi"})
    assert not ok("execute_code", {"code": "open('x','w')"})
    assert not ok("browser_exec", {"code": "..."})
    assert not ok("send_message", {"text": "hi Ana"})
    assert not ok("cronjob_manage", {})
    assert not ok("memory", {})
    blocked = app.on_pre_tool_call(tool_name="terminal", args={"command": "rm -rf /"})
    assert blocked == {"action": "block", "message": blocked["message"]} and "needs_you" in blocked["message"]


def test_patch_v4a_paths_are_checked(make_app):
    app = make_app()
    _start_friday(app)
    d = app.drafts_dir
    inside_patch = f"*** Begin Patch\n*** Add File: {d / 'a.md'}\n+hello\n*** End Patch"
    outside_patch = f"*** Begin Patch\n*** Update File: {d / 'a.md'}\n*** Add File: /tmp/evil.md\n+x\n*** End Patch"
    move_out = f"*** Begin Patch\n*** Move File: {d / 'a.md'} -> /tmp/b.md\n*** End Patch"
    assert app.on_pre_tool_call(tool_name="patch", args={"mode": "patch", "patch": inside_patch}) is None
    assert app.on_pre_tool_call(tool_name="patch", args={"mode": "patch", "patch": outside_patch}) is not None
    assert app.on_pre_tool_call(tool_name="patch", args={"mode": "patch", "patch": move_out}) is not None
    # replace mode with a smuggled V4A body is still checked
    assert app.on_pre_tool_call(
        tool_name="patch", args={"path": str(d / "a.md"), "patch": outside_patch}) is not None


def test_relative_paths_resolve_against_agent_cwd(tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    assert friday.allowed("write_file", {"path": "drafts/x.md"}, drafts, cwd=tmp_path)
    assert not friday.allowed("write_file", {"path": "drafts/../../x.md"}, drafts, cwd=tmp_path)
    link = drafts / "escape"
    link.symlink_to(tmp_path)
    assert not friday.allowed("write_file", {"path": str(link / "x.md")}, drafts, cwd=tmp_path)


def test_guard_fails_closed_inside_friday_and_open_outside(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(friday, "allowed", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    assert app.on_pre_tool_call(tool_name="read_file", args={"path": "x"}) is None  # not a Friday run
    _start_friday(app)
    assert app.on_pre_tool_call(tool_name="read_file", args={"path": "x"})["action"] == "block"


def test_media_line_added_only_in_friday_run_and_only_when_missing(make_app):
    app = make_app()
    png = Path(app.data_dir) / "report-x.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    app.store.meta_set("last_report_path", str(png))
    assert app.on_transform_llm_output(response_text="hello") is None  # not in a Friday run
    _start_friday(app)
    # a report built before this run (e.g. last week's) is never attached
    assert app.on_transform_llm_output(response_text="🧭 Your week: 24% went to detours.") is None
    app.store.meta_set("report_execution", "exec-1")
    out = app.on_transform_llm_output(response_text="🧭 Your week: 24% went to detours.")
    assert out.endswith(f"MEDIA:{png}")
    assert app.on_transform_llm_output(response_text=f"done\nMEDIA:{png}") is None


def test_ensure_media_requires_existing_absolute_file(tmp_path):
    assert friday.ensure_media("x", "relative.png") is None
    assert friday.ensure_media("x", str(tmp_path / "missing.png")) is None
    assert friday.ensure_media("x", None) is None


def test_guard_armed_without_the_hook_by_job_name_or_remembered_job(make_app):
    app = make_app()
    # pre_llm_call skipped (timeout, reload): the blueprint job name still arms the guard
    app.ctx.cron = FakeCron(execution_id="e9", job_id="j9", job_name="Bussola Friday run")
    assert app.on_pre_tool_call(tool_name="terminal", args={"command": "ls"})["action"] == "block"
    # a renamed job is recognised by the job id remembered from an earlier run
    app.ctx.cron = FakeCron(execution_id="e10", job_id="j10", job_name="My weekly cleanup")
    assert turn(app, friday.PROMPT, session="cron_s", turn_id="x") is None
    app.fridays._ids.clear()  # simulate a plugin reload
    app.ctx.cron = FakeCron(execution_id="e11", job_id="j10", job_name="My weekly cleanup")
    assert app.on_pre_tool_call(tool_name="terminal", args={"command": "ls"})["action"] == "block"


def test_report_built_in_the_run_is_attached(make_app, clock):
    import pytest

    pytest.importorskip("matplotlib")
    from bussola import demo

    app = make_app()
    demo.load(app.store, clock())
    _start_friday(app)
    out = app.build_report()
    assert app.store.meta_get("report_execution") == "exec-1"
    assert app.on_transform_llm_output(response_text="done").endswith(f"MEDIA:{out['path']}")
