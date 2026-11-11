"""Measure the classifier: detour precision/recall, goal accuracy, latency, tokens.

Run inside Hermes with ``/augur eval`` (dev set) or ``/augur eval final``
(the held-out set: run it once, at the end, never tune on it). Results are
written to ``<plugin-data>/augur/evals/`` and returned as a Markdown table.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .. import classifier as clf
from .. import config

HERE = Path(__file__).resolve().parent
TARGETS = {"detour_precision": 0.90, "detour_recall": 0.70, "goal_accuracy": 0.85, "p95_latency_s": 1.5}


def load_rows(final: bool = False) -> list[dict[str, Any]]:
    path = HERE / ("final.jsonl" if final else "dataset.jsonl")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_profiles() -> dict[str, list[dict[str, Any]]]:
    return json.loads((HERE / "profiles.json").read_text(encoding="utf-8"))


def predict(
    call: Callable[..., Optional[clf.Result]], row: dict[str, Any], goals: list[dict[str, Any]], min_conf: float
) -> tuple[Optional[int], Optional[clf.Result]]:
    """Same decision path as the live hook (continuation inheritance, confidence floor)."""
    result = call(goals, [], row.get("history") or [], row["message"])
    if result is None or result.confidence < min_conf:
        return None, result
    goal = result.goal
    if result.continues_previous and row.get("history_goal") is not None and row["history_goal"] >= 0:
        goal = int(row["history_goal"])
    return (-1 if goal is None else goal), result


def score(records: list[dict[str, Any]]) -> dict[str, Any]:
    pred_detour = [r for r in records if r["predicted"] == 0]
    true_detour = [r for r in records if r["expected"] == 0]
    in_goal = [r for r in records if r["expected"] in (1, 2, 3)]
    latencies = sorted(r["latency"] for r in records if r["latency"] is not None)
    tokens = [r["tokens"] for r in records if r["tokens"]]

    def ratio(num: int, den: int) -> Optional[float]:
        return num / den if den else None

    p95 = latencies[max(0, int(round(0.95 * len(latencies))) - 1)] if latencies else None
    return {
        "n": len(records),
        "detour_precision": ratio(sum(1 for r in pred_detour if r["expected"] == 0), len(pred_detour)),
        "detour_recall": ratio(sum(1 for r in true_detour if r["predicted"] == 0), len(true_detour)),
        "goal_accuracy": ratio(sum(1 for r in in_goal if r["predicted"] == r["expected"]), len(in_goal)),
        "neutral_ok": ratio(
            sum(1 for r in records if r["expected"] == -1 and r["predicted"] != 0),
            sum(1 for r in records if r["expected"] == -1),
        ),
        "silent": sum(1 for r in records if r["predicted"] is None),
        "p50_latency_s": statistics.median(latencies) if latencies else None,
        "p95_latency_s": p95,
        "avg_tokens": statistics.mean(tokens) if tokens else None,
    }


def table(metrics: dict[str, Any]) -> str:
    def pct(v):
        return "n/a" if v is None else f"{v * 100:.0f}%"

    def sec(v):
        return "n/a" if v is None else f"{v:.2f} s"

    def ok(key, v, lower_is_better=False):
        if v is None:
            return "–"
        target = TARGETS[key]
        return "✅" if (v <= target if lower_is_better else v >= target) else "❌"

    rows = [
        ("Detour precision (flagged detours that really were)", pct(metrics["detour_precision"]), "≥ 90%",
         ok("detour_precision", metrics["detour_precision"])),
        ("Detour recall (real detours caught)", pct(metrics["detour_recall"]), "≥ 70%",
         ok("detour_recall", metrics["detour_recall"])),
        ("Goal accuracy on in-goal requests", pct(metrics["goal_accuracy"]), "≥ 85%",
         ok("goal_accuracy", metrics["goal_accuracy"])),
        ("Latency p95", sec(metrics["p95_latency_s"]), "≤ 1.5 s",
         ok("p95_latency_s", metrics["p95_latency_s"], lower_is_better=True)),
        ("Latency p50", sec(metrics["p50_latency_s"]), "", ""),
        ("Neutral messages never flagged", pct(metrics["neutral_ok"]), "", ""),
        ("Average tokens per message", "n/a" if metrics["avg_tokens"] is None else f"{metrics['avg_tokens']:.0f}",
         "record", ""),
    ]
    out = ["| Metric | Result | Target | |", "|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
    return "\n".join(out)


def run(
    call: Callable[..., Optional[clf.Result]],
    *,
    final: bool = False,
    min_conf: float = 0.6,
    out_dir: Path,
    model_label: str = "",
) -> tuple[Path, str]:
    profiles = load_profiles()
    rows = load_rows(final)
    records = []
    for row in rows:
        predicted, result = predict(call, row, profiles[row["profile"]], min_conf)
        records.append(
            {
                "id": row["id"],
                "lang": row.get("lang"),
                "kind": row.get("kind"),
                "expected": row["expected_goal"],
                "predicted": predicted,
                "confidence": None if result is None else round(result.confidence, 2),
                "latency": None if result is None else result.latency,
                "tokens": None if result is None else result.tokens,
                "message": row["message"][:70],
            }
        )
    metrics = score(records)
    now = datetime.now().astimezone()
    md = [
        f"## {'Final (held-out)' if final else 'Dev'} set · {now:%Y-%m-%d %H:%M %Z}",
        "",
        f"Prompt `{clf.PROMPT_VERSION}` · min_confidence {min_conf} · {metrics['n']} messages"
        + (f" · model: {model_label}" if model_label else ""),
        "",
        table(metrics),
        "",
    ]
    misses = [r for r in records if r["predicted"] != r["expected"]]
    if misses:
        md += ["| id | kind | expected | got | conf | message |", "|---|---|---|---|---|---|"]
        for r in misses:
            got = "silent" if r["predicted"] is None else r["predicted"]
            md.append(f"| {r['id']} | {r['kind']} | {r['expected']} | {got} | {r['confidence']} | {r['message']} |")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"RESULTS-{'final' if final else 'dev'}-{now:%Y%m%d-%H%M%S}.md"
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    (out_dir / f"records-{'final' if final else 'dev'}-{now:%Y%m%d-%H%M%S}.json").write_text(
        json.dumps({"metrics": metrics, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return path, "\n".join(md)


def run_with_app(app: Any, final: bool = False) -> tuple[Path, str]:
    app.evaluating = True  # eval calls are not counted as Augur's own cost
    try:
        return run(
            app.classifier.call,
            final=final,
            min_conf=config.get(app.ctx, "min_confidence"),
            out_dir=app.data_dir / "evals",
        )
    finally:
        app.evaluating = False
