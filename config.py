"""Plugin settings with defaults applied in code.

Hermes does not apply ``config_schema`` defaults from ``plugin.yaml`` when a key
was never saved (``PluginContext.get_config`` returns the ``default`` argument),
so every read goes through :func:`get` with the default from ``DEFAULTS``.
"""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "language": "en",
    "max_nudges_per_day": 3,
    "nudge_cooldown_minutes": 45,
    "min_confidence": 0.6,
}

_LANGUAGES = ("en", "pt")


def get(ctx: Any, key: str) -> Any:
    """Read one setting, falling back to the default on a missing or malformed value."""
    default = DEFAULTS[key]
    try:
        raw = ctx.get_config(key, default)
    except Exception:
        return default
    try:
        if key == "language":
            value = str(raw).strip().lower()
            return value if value in _LANGUAGES else default
        if isinstance(default, bool):
            return bool(raw)
        if isinstance(default, int):
            value = int(raw)
            return value if value >= 0 else default
        if isinstance(default, float):
            value = float(raw)
            return value if 0.0 <= value <= 1.0 else default
    except (TypeError, ValueError):
        return default
    return raw


def snapshot(ctx: Any) -> dict[str, Any]:
    """All settings at once (used by the panel and the eval runner)."""
    return {key: get(ctx, key) for key in DEFAULTS}
