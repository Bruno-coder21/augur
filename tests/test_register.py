"""register() wires exactly what plugin.yaml declares, and the static rules hold."""

from __future__ import annotations

import re

import pytest
from conftest import REPO, FakeCtx

import augur
from augur import strings


def _manifest_list(key: str) -> list[str]:
    text = (REPO / "plugin.yaml").read_text()
    m = re.search(rf"^{key}:\s*\[(.*?)\]", text, re.M)
    assert m, key
    return [x.strip() for x in m.group(1).split(",") if x.strip()]


@pytest.fixture
def registered(monkeypatch, tmp_path):
    from augur import store as store_mod

    monkeypatch.setattr(store_mod, "_default_connect", lambda: __import__("sqlite3").connect(
        str(tmp_path / "db.sqlite"), check_same_thread=False))
    monkeypatch.setattr(store_mod, "default_data_dir", lambda: tmp_path / "data")
    ctx = FakeCtx()
    augur.register(ctx)
    yield ctx
    for cb in ctx.unload:
        cb()


def test_register_matches_manifest(registered):
    assert sorted(registered.tools) == sorted(_manifest_list("provides_tools"))
    assert sorted(registered.hooks) == sorted(_manifest_list("provides_hooks"))
    assert set(augur.TOOLS) == set(registered.tools)
    assert set(augur.HOOKS) == set(registered.hooks)


def test_register_surfaces(registered):
    assert set(registered.commands) == {"augur", "park"}
    assert set(registered.aux_tasks) == {"augur_classifier", "augur_insight"}
    assert all(t["inherit_from"] == "compression" for t in registered.aux_tasks.values())
    assert set(registered.blueprints) == {"friday"}
    assert all(t["toolset"] == "augur" for t in registered.tools.values())


def test_blueprint_renders_friday_schedule(registered):
    bp = registered.blueprints["friday"]
    slots = {s["name"]: s for s in bp["slots"]}
    assert set(slots) == {"time", "day", "deliver"}
    hour, minute = slots["time"]["default"].split(":")
    days = {"friday": "5", "wednesday": "3"}
    schedule = bp["schedule_template"].format(minute=int(minute), hour=int(hour), dow=days[slots["day"]["default"]])
    assert schedule == "30 17 * * 5"
    assert "[augur:friday]" in bp["prompt_template"]
    bp["prompt_template"].format()  # Hermes formats the prompt with slot values: no stray braces


def test_strings_have_same_keys_in_every_language():
    assert set(strings.STRINGS["en"]) == set(strings.STRINGS["pt"])
    for lang, table in strings.STRINGS.items():
        for key, value in table.items():
            placeholders_en = set(re.findall(r"\{(\w+)", strings.STRINGS["en"][key]))
            assert set(re.findall(r"\{(\w+)", value)) == placeholders_en, (lang, key)


def test_t_never_raises():
    assert strings.t("park_saved", "pt", id=1).startswith("🧭")
    assert strings.t("help", "xx") == strings.STRINGS["en"]["help"]


def test_no_bytecode_or_binaries_tracked():
    bad = [p for p in REPO.rglob("*") if p.suffix in {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin"}
           and ".venv" not in p.parts and "__pycache__" not in p.parts]
    assert bad == []


def test_no_forbidden_calls_in_plugin_code():
    """No network, shell, eval, or reads of Hermes secrets from plugin code."""
    forbidden = [
        re.compile(r"^\s*(?:import|from)\s+(?:subprocess|socket|urllib|requests|httpx|aiohttp)\b", re.M),
        re.compile(r"\bos\.(?:system|popen|exec\w*)\b"),
        re.compile(r"(?<![\w.])(?:eval|exec)\("),
        re.compile(r"[\'\"][^\'\"]*(?:\.env|auth\.json)[\'\"]"),
    ]
    offenders = []
    for path in [*REPO.glob("*.py"), *REPO.glob("evals/*.py")]:
        text = path.read_text()
        for pattern in forbidden:
            offenders += [f"{path.name}: {m.group(0)}" for m in pattern.finditer(text)]
    assert offenders == []


def test_hook_callbacks_accept_kwargs(registered):
    import inspect

    for name, cb in registered.hooks.items():
        params = inspect.signature(cb).parameters.values()
        assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params), name


def test_register_survives_broken_storage(monkeypatch):
    from augur import store as store_mod

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(store_mod, "_default_connect", boom)
    ctx = FakeCtx()
    augur.register(ctx)  # must not raise
    assert ctx.hooks["pre_llm_call"](session_id="s", user_message="plan my trip to Rome please",
                                     conversation_history=[], turn_id="t") is None
    for cb in ctx.unload:
        cb()


def test_readme_mentions_every_command():
    readme = (REPO / "README.md")
    if not readme.exists():
        pytest.skip("README not written yet")
    text = readme.read_text()
    for cmd in ("/augur goals", "/augur fix", "/augur pause", "/augur demo", "/augur report", "/park"):
        assert cmd in text, cmd

