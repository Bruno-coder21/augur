"""Redaction and the 60-character rule.

Nothing Bussola stores is longer than 60 characters of user text, and
everything passes through Hermes's public ``redact_sensitive_text(force=True)``
first. When Hermes is not importable (unit tests, CI), a conservative local
fallback masks the obvious secret shapes.
"""

from __future__ import annotations

import re
from typing import Any

SUMMARY_MAX = 60
RESULT_MAX = 140

_FALLBACK_PATTERNS = [
    re.compile(r"\b(sk|pk|rk|ghp|gho|ghs|xox[abprs]|AKIA|AIza)[-_A-Za-z0-9]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b\d{3,}[-\s]?\d{3,}[-\s]?\d{3,}\b"),
    re.compile(r"(?i)\b(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
]


def _fallback_redact(text: str) -> str:
    for pattern in _FALLBACK_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def redact(text: Any) -> str:
    """Mask secrets, even when Hermes's own redaction setting is off."""
    value = "" if text is None else str(text)
    if not value:
        return ""
    try:
        from agent.redact import redact_sensitive_text  # public Hermes API
    except Exception:
        return _fallback_redact(value)
    try:
        return redact_sensitive_text(value, force=True)
    except Exception:
        return _fallback_redact(value)


def clip(text: Any, limit: int) -> str:
    """Collapse whitespace and cut to ``limit`` characters (with an ellipsis)."""
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def summary60(text: Any) -> str:
    """Redact first, then clip: the only shape user text is ever stored in."""
    return clip(redact(text), SUMMARY_MAX)


def result_line(text: Any) -> str:
    return clip(redact(text), RESULT_MAX)


def message_text(user_message: Any) -> str:
    """``user_message`` can be a string or a list of content parts (image turns)."""
    if isinstance(user_message, str):
        return user_message
    if isinstance(user_message, list):
        parts = []
        for part in user_message:
            if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(p for p in parts if p)
    return "" if user_message is None else str(user_message)
