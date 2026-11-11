"""Tokens per goal, and what Bussola itself costs.

Hermes reports token counts on ``post_api_request`` (the user's own agent
calls) and ``post_auxiliary_call`` (Bussola's classifier and insight calls).
Neither carries a money amount in this Hermes version, so Bussola reports
tokens only and never guesses prices.
"""

from __future__ import annotations

from typing import Any

BUSSOLA_TASKS = frozenset({"bussola_classifier", "bussola_insight"})


def usage_tokens(usage: Any) -> int:
    """Total tokens from either naming convention; 0 when unknown."""
    if usage is None:
        return 0
    if isinstance(usage, dict):
        get = usage.get
    else:
        get = lambda key, default=None: getattr(usage, key, default)  # noqa: E731

    def num(*keys: str) -> int:
        for key in keys:
            value = get(key, None)
            if value is None:
                continue
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    total = num("total_tokens")
    if total:
        return total
    return num("input_tokens", "prompt_tokens") + num("output_tokens", "completion_tokens")


def human_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
