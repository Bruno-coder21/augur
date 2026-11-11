# Classifier eval results

Model for `augur_classifier`: Claude Haiku 5.5 (`claude-haiku-5-5`, Anthropic API), through `ctx.llm.complete_structured` inside Hermes v0.23.1. Every run is appended here with its date and prompt version.

## Dev set · 2026-11-11 18:22 -03

Prompt `v2` · min_confidence 0.6 · 60 messages

| Metric | Result | Target | |
|---|---|---|---|
| Detour precision (flagged detours that really were) | 100% | ≥ 90% | ✅ |
| Detour recall (real detours caught) | 100% | ≥ 70% | ✅ |
| Goal accuracy on in-goal requests | 97% | ≥ 85% | ✅ |
| Latency p95 | 2.07 s | ≤ 1.5 s | ❌ |
| Latency p50 | 1.18 s |  |  |
| Neutral messages never flagged | 100% |  |  |
| Average tokens per message | 1230 | record |  |

| id | kind | expected | got | conf | message |
|---|---|---|---|---|---|
| dev-07 | in_goal | 3 | 1 | 0.8 | Correct the grammar of this paragraph from my pitch: 'We was founded i |

## Final (held-out) set · 2026-11-11 18:23 -03

Prompt `v2` · min_confidence 0.6 · 20 messages

| Metric | Result | Target | |
|---|---|---|---|
| Detour precision (flagged detours that really were) | 100% | ≥ 90% | ✅ |
| Detour recall (real detours caught) | 100% | ≥ 70% | ✅ |
| Goal accuracy on in-goal requests | 100% | ≥ 85% | ✅ |
| Latency p95 | 2.15 s | ≤ 1.5 s | ❌ |
| Latency p50 | 1.07 s |  |  |
| Neutral messages never flagged | 100% |  |  |
| Average tokens per message | 1286 | record |  |

