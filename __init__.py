"""Bussola: your agent knows your 3 priorities, notices drift, parks detours
and clears them on Friday.

``register(ctx)`` only wires the pieces; behavior lives in the modules:
classifier · nudge · metering · friday · report · insight · commands · tools.
"""

from __future__ import annotations

import logging

log = logging.getLogger("bussola")

TOOLS = ("bussola_park", "bussola_queue", "bussola_done", "bussola_report")
HOOKS = (
    "pre_llm_call",
    "post_llm_call",
    "post_api_request",
    "post_auxiliary_call",
    "pre_tool_call",
    "transform_llm_output",
)


def register(ctx):
    from . import friday, schemas
    from .commands import Commands
    from .core import Bussola
    from .tools import make_handlers

    app = Bussola(ctx)
    try:
        app.store.migrate()
    except Exception as exc:  # storage trouble must not take the agent down; hooks stay silent
        log.warning("bussola storage unavailable at load: %s", exc)

    # Two model slots, configurable in the model screens. They follow the compression
    # slot until the user pins a model; the panel warns when labels arrive too slowly.
    ctx.register_auxiliary_task(
        "bussola_classifier",
        display_name="Bussola classifier",
        description="Labels each request against your 3 weekly goals (one short call per message). Pin a fast model.",
        inherit_from="compression",
        defaults={"reasoning_effort": "none", "timeout": 20},
    )
    ctx.register_auxiliary_task(
        "bussola_insight",
        display_name="Bussola hidden priority",
        description="Finds a recurring theme in the week's detours (one call per weekly report).",
        inherit_from="compression",
        defaults={"reasoning_effort": "low", "timeout": 60},
    )

    ctx.register_hook("pre_llm_call", app.on_pre_llm_call)
    ctx.register_hook("post_llm_call", app.on_post_llm_call)
    ctx.register_hook("post_api_request", app.on_post_api_request)
    ctx.register_hook("post_auxiliary_call", app.on_post_auxiliary_call)
    ctx.register_hook("pre_tool_call", app.on_pre_tool_call)
    ctx.register_hook("transform_llm_output", app.on_transform_llm_output)

    handlers = make_handlers(app)
    for name, schema in (
        ("bussola_park", schemas.BUSSOLA_PARK),
        ("bussola_queue", schemas.BUSSOLA_QUEUE),
        ("bussola_done", schemas.BUSSOLA_DONE),
        ("bussola_report", schemas.BUSSOLA_REPORT),
    ):
        ctx.register_tool(name=name, toolset="bussola", schema=schema, handler=handlers[name], emoji="🧭")

    commands = Commands(app)
    ctx.register_command(
        "bussola",
        commands.bussola,
        description="Your week against your 3 goals: goals, fix, pause, report, demo",
        args_hint="[goals|fix|pause|report|demo]",
    )
    ctx.register_command("park", commands.park, description="Park a detour for the Friday run", args_hint="<text>")

    friday.register_blueprint(ctx)

    # Desktop status chip (desktop/plugin.js) reads this; other surfaces ignore it.
    try:
        ctx.register_rpc("status", app.rpc_status)
    except AttributeError:  # hosts without plugin RPC
        pass
    try:
        ctx.on_unload(app.close)
    except AttributeError:  # older hosts without unload callbacks
        pass
