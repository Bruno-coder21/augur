# NOTES: what was checked against the real Hermes

Everything Bussola relies on was read in the Hermes source before use.

- **Reference:** Hermes Agent **v0.23.1** (stable, `3b42157`, installed with the official `install.sh`), cross-checked with `main` at `b5f15a6` (2026-11-11).
- **Rule:** where the docs and the code disagreed, Bussola follows the code. Each divergence is recorded below.
- **Paths:** relative to the Hermes checkout.

## The 7 open questions from the brief

| Question | Answer | Where |
|---|---|---|
| Agent's "ask with options" tool | `clarify`, args `{questions: [{question, choices≤4, multi_select?}]}`. On Telegram the options appear in the message and the buttons are numbered `1..N` plus "Other". Not available in cron runs. | `tools/clarify_tool.py`, `plugins/platforms/telegram/adapter.py` |
| Desktop status-bar API | `ctx.register({id, area: STATUSBAR_AREAS.right, render})`. Plain ESM with `jsx()`; only `@hermes/plugin-sdk`, `react` and `react/jsx-runtime` resolve. Python side: `ctx.register_rpc(name, handler(params, *, session_id))` serves `plugin.<id>.<name>`, and `ctx.emit_to_session(sid, event, payload)` sends `plugin.<id>.<event>`. The desktop half is off until the user enables it. | `website/docs/developer-guide/desktop-plugin-sdk.md`, `hermes_cli/plugin_rpc.py`, `apps/desktop/src/plugins/radio/plugin.js` |
| `conversation_id` in hooks | **Not** passed to `pre_llm_call`, `post_llm_call`, `post_api_request` or `transform_llm_output`; only tool hooks and tool handlers get it. Bussola keys state by `session_id` (stable by default because `compression.in_place: true`) and by `turn_id`. | `agent/turn_context.py`, `hermes_cli/plugins.py` |
| Run a cron job now | `hermes cron run <job id or name>`: a synchronous run that prints "Ran now". | `hermes_cli/cron.py` |
| Real tool names for the guard | Read: `read_file`, `search_files`, `web_search`, `web_extract`. Write: `write_file(path)`, `patch(path \| V4A patch text)`. Also able to write: `terminal`, `execute_code`, `browser_exec`, `memory`, `cronjob_manage`, … | `toolsets.py`, `tools/file_tools.py` |
| matplotlib vs Hermes constraints | Not a Hermes dependency. `matplotlib>=3.8,<4` resolves next to Hermes's pins; pillow is forced to 13.0.0 by Hermes, which matplotlib accepts. `hermes plugins validate . --install-deps` passes. | `pyproject.toml` `[tool.uv]` |
| Installed version | `Hermes Agent v0.23.1 (2026.9.24)`, so `requires_hermes: ">=0.23.1"`. | `hermes --version` |

## Where the docs (or the brief) and the code disagree

1. **Auxiliary task keys** may contain only `[A-Za-z0-9_]`. The brief's `classifier` and `insight` became `bussola_classifier` and `bussola_insight`. The `aux_task` value in `post_auxiliary_call` is that key. (`hermes_cli/plugins_aux_tasks.py`)
2. **`ctx.llm.complete_structured(input=...)`** takes a list of blocks (`[{"type": "text", "text": ...}]`), not a string. A reply that does not match the schema raises `ValueError` when `jsonschema` is installed. (`agent/plugin_llm.py`)
3. **`usage.cost_usd` is always `None`** for plugin LLM calls, and `post_api_request`'s `usage` has no cost field. Bussola therefore reports tokens only, and the brief's `currency` setting was dropped.
4. **`ctx.get_config` does not apply the `config_schema` defaults** from `plugin.yaml`. The defaults live in `config.py`.
5. **Text returned by `pre_llm_call` is stored with the message and resent on every later turn** (`api_content` sidecar), even though the docs call it ephemeral. The nudge text is short and starts with "applies to this message only".
6. **`pre_tool_call` fails closed:** a callback that raises blocks the tool. Bussola's guard is wrapped so it can only block inside its own Friday run.
7. **`MEDIA:` tags in tool results are not delivered.** Only tags in the final reply are. `transform_llm_output` appends the line in the Friday run when the model forgot it.
8. **`ask_choice` cannot take free text:** typed text must match an option. Goal names come from the command line (`/bussola goals …`); `ask_choice` is used only for the split and for `/bussola fix`.
9. **`hermes plugins validate` has no `--ci` flag.** Only `doctor` has it.
10. **Command names with `_` never match on messaging platforms** (the gateway looks up `name.replace("_", "-")`). Bussola uses `/bussola` and `/park`.
11. **`plugin_db()` opens a new connection on every call.** `Store` keeps one connection per process behind an `RLock`.
12. **The V4A form of `patch` carries file paths inside the patch text**, not only in `path`. The Friday guard checks every `*** Add/Update/Delete/Move File:` header.

## Evidence log

- `hermes plugins doctor . --ci`: OK (4 tools, 6 hooks; runtime discovery, import and registration passed).
- `hermes plugins validate . --install-deps`: **Validation passed** (manifest, config schema, loadable `__init__.py` + `desktop/plugin.js`, declared tools/hooks match, no collisions, security scan safe, no core override, desktop stays inside the SDK surface).
- `pytest -q`: see CI.
