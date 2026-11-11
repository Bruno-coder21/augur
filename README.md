# 🧭 Augur

**Your agent knows your 3 priorities, notices when you drift, parks the detour, and on Friday clears what it can and shows where your attention actually went.**

[![CI](https://github.com/Bruno-coder21/augur/actions/workflows/ci.yml/badge.svg)](https://github.com/Bruno-coder21/augur/actions/workflows/ci.yml)
· Hermes Agent plugin · `requires_hermes >= 0.23.1` · MIT

<!-- GIF: the 🧭 question and the "Park it" button on Telegram (10 s) -->

## Why

An agent that can do anything makes it easy to do everything. One quick question turns into a website tweak, then a trip plan, and the week's real priorities get whatever is left. Augur keeps your agent pointed at the 3 goals you chose for the week, without getting in your way.

## What it does

| Moment | What happens |
|---|---|
| **Goals** | `/augur goals launching VDRI, hackathons, English`. One tap picks the planned split (50/30/20…). |
| **Nudge** | Augur silently labels each request. On the **2nd detour in a row** your agent asks one short question: *"🧭 2nd request off your goals (closest: VDRI launch). Do it now or park it?"* It never blocks you. |
| **Park** | "Park it" puts the detour in the **Queue** (`augur_park` or `/park <text>`). |
| **Friday run** | A cron job researches and drafts each parked item, marks what **needs you**, and sends the weekly report image. It is read-and-draft only, enforced by a guard. |
| **Hidden priority** | If 5 or more detours share a theme, Augur names the 4th priority you never declared and suggests swapping it in. |

<p align="center"><img src="docs/report-demo.png" width="420" alt="Weekly report: 24% of requests went to detours, planned vs actual per goal, hidden priority, items ready while you slept"></p>

`/augur` in the terminal:

```
🧭 Augur · Nov 5 – 11  (includes demo data)

  VDRI launch  ▇▇▇▇▇▇░░░░░░░░░░░░░░   31% of 50% planned
  Hackathons   ▇▇▇▇▇▇▇░░░░░░░░░░░░░   36% of 30% planned
  English      ▇▇░░░░░░░░░░░░░░░░░░    9% of 20% planned
  Detours      ▇▇▇▇▇░░░░░░░░░░░░░░░   24%

  45 requests counted · 240.8k tokens

  Queue: 5 parked · Friday run not scheduled → /blueprint augur:friday
  Hidden priority: "VDRI website" (6 requests) → /augur goals
  Augur itself used 1.2k tokens this week
```

Each goal keeps one color everywhere (terminal, PNG, Telegram, Desktop): blue, amber and violet, chosen to stay distinguishable for color-blind users.

## Quickstart (under 60 seconds)

```bash
hermes plugins install Bruno-coder21/augur --enable   # or `augur` once it is in the catalog
```

Then, in any Hermes chat (CLI, Telegram, Desktop):

```
/augur demo                                   # see a sample week right away (marked as demo)
/augur goals launching VDRI, hackathons, English
/blueprint augur:friday                       # schedule the Friday run (default Fri 17:30)
/augur demo clear                             # remove the sample data
```

Day to day you don't run anything: just work. `/augur` shows your week, `/augur report` sends the image now, `/park <text>` parks something by hand, `/augur fix` corrects the last label (Augur learns from it), and `/augur pause 2h` (or `off`) gives you quiet time.

## How well it works

The classifier is measured on a labeled set of 80 messages: 3 user profiles (founder, developer, student), 60% English and 40% Portuguese, with clear detours and hard cases (short follow-ups, mixed requests, small talk). 20 of the 80 are a **held-out set written blind** by a separate agent and run exactly once.

<!-- EVAL_TABLE -->

Precision comes before recall: a wrong nudge is annoying, while a missed detour costs little.

## Privacy and safety

- **Model calls:** one extra call per non-trivial message, through the `augur_classifier` auxiliary task. It defaults to your compression model, and you can pin or change it. Plus one call per weekly report, through `augur_insight`. Messages shorter than 15 characters and slash commands make no call.
- **Stored data:** date, goal, confidence and a redacted summary of at most 60 characters per message. Never the full text. Secrets are masked with Hermes's `redact_sensitive_text(force=True)` before anything is stored. Data lives in the Hermes plugin data directory (`~/.hermes/plugin-data/augur/`) and follows your profile.
- **Nudge text:** on the 2nd detour in a row, Augur adds a short instruction for the agent to that one message. Hermes keeps added context with the message in the conversation history.
- **Network and shell:** no network calls of its own, no shell commands, no reads outside its own data directory.
- **Friday run:** read-and-draft only, enforced by a `pre_tool_call` guard:
  - It allows Augur's tools, plus `read_file`, `search_files`, `web_search` and `web_extract`.
  - It allows `write_file` and `patch` only inside `drafts/`, with every V4A path checked.
  - Everything else is blocked, so anything that would need approval becomes "needs you" instead of waiting.
  - The guard is active only in Augur's own cron run.
- **No telemetry, no self-update, no binaries.**

## How it works

```mermaid
flowchart LR
  U[Your message] --> P[pre_llm_call]
  P -->|"label: ≤1.5 s budget,<br/>else silence"| C[(augur_classifier)]
  P -->|"2nd detour in a row"| N["+ 🧭 question context"]
  N --> A[Your agent]
  P --> A
  A -->|"Park it"| T[augur_park] --> Q[(Queue)]
  A --> R[post_api_request<br/>tokens per goal]
  F[Friday cron run] --> G{pre_tool_call guard}
  G -->|read / draft| D[drafts/]
  F --> B[augur_report] --> I[(augur_insight)]
  B --> M["PNG + MEDIA: line<br/>(transform_llm_output)"]
```

| Surface | Used for |
|---|---|
| 6 hooks | `pre_llm_call` (label and nudge), `post_llm_call` (park or do-now decision), `post_api_request` (tokens per goal), `post_auxiliary_call` (Augur's own cost), `pre_tool_call` (Friday guard), `transform_llm_output` (guaranteed report attachment) |
| 4 tools | `augur_park`, `augur_queue`, `augur_done`, `augur_report` |
| 2 auxiliary tasks | `augur_classifier`, `augur_insight` (each its own model slot) |
| 1 blueprint | `augur:friday` (time, day, deliver) |
| 2 commands | `/augur …`, `/park …` |
| Desktop | Status-bar chip "🧭 Hackathons · 62% on goals" with the week in a popover (`desktop/plugin.js`, RPC `plugin.augur.status`, live `status.changed` events) |

Reliability rules:
- Every hook returns `None` on any error.
- A slow model never delays you more than 1.5 s; a late answer is stored in the background without a nudge.
- Low confidence means silence.
- The plugin never returns `block` from `pre_llm_call`.

## Configuration

In Desktop → Settings → Plugins → Augur, or `plugins.entries.augur.settings` in `config.yaml`:

| Key | Default | Meaning |
|---|---|---|
| `language` | `en` | `en` or `pt`, for every message, panel and report |
| `max_nudges_per_day` | `3` | Augur stays quiet after this many nudges in a day |
| `nudge_cooldown_minutes` | `45` | No nudge in a session for this long after "Do it now" |
| `min_confidence` | `0.6` | Below this, a request is not counted and never nudged |

To pin a model for Augur's calls, pick it for **Augur classifier** and **Augur hidden priority** in the model screens (`hermes model`, or Desktop → Models), or set `auxiliary.augur_classifier.model` in `config.yaml`.

## Roadmap

- Weekly report to a partner or co-founder through the gateway.
- A nightly guard that flags cron jobs drifting outside your goals.
- Parked items that come back due on Monday.

## Developer

```bash
python -m pytest -q                     # unit tests with a fake Hermes context and a fake LLM
hermes plugins doctor . --ci            # load it through the real plugin manager
hermes plugins validate . --install-deps
```

`/augur eval` runs the 60-message dev set through your configured `augur_classifier` model and writes `RESULTS-dev-*.md` to the plugin data directory. `/augur eval final` runs the held-out set; run it once, at the end. `NOTES.md` lists every Hermes API detail checked against the source. Contributions welcome: open an issue first for anything that changes what Augur stores or sends.
