"""Redaction, length limits and output safety for every piece of user or model text.

What Augur stores, at most: a model-written request summary (60 chars), goal names
(40) and descriptions (160), parked-item text as the user or agent wrote it (60), and
Friday-run result lines (140). Everything passes through Hermes's public
``redact_sensitive_text(force=True)`` first (secret-shaped tokens only: names or
health details typed into ``/park`` are stored as typed). When Hermes is not
importable (unit tests, CI), a conservative local fallback masks the obvious shapes.

``inert`` makes stored text safe to repeat in replies: no terminal control or
bidi-override characters, no ``MEDIA:`` attachment tags, and no bare absolute paths
the gateway would turn into attachments.
"""

from __future__ import annotations

import re
from typing import Any

SUMMARY_MAX = 60
RESULT_MAX = 140

_FALLBACK_PATTERNS = [
    re.compile(r"\b(sk|pk|rk|ghp|gho|ghs|xox[abprs]|AKIA|AIza)[-_A-Za-z0-9]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b\d{3,12}[-\s]?\d{3,12}[-\s]?\d{3,12}\b"),
    re.compile(r"(?i)\b(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
]
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_MEDIA_TAG = re.compile(r"media\s*:", re.IGNORECASE)
# the gateway attaches bare absolute paths (/x/y.png, ~/y.pdf) found in a reply; a division
# slash (U+2215) at the start of a path looks the same to people and to no one else
_PATH_START = re.compile(r"(?<![/:\w.∕])(~?)/(?=[\w.\-])")


_DRIVE = re.compile(r"(?<![\w])([A-Za-z]):(?=[\\/])")  # C:\Users\... or C:/Users/... (Windows gateways)


def inert(text: Any) -> str:
    """Safe to show in any reply: no control chars, no MEDIA tags, no attachable paths."""
    value = _CONTROL.sub("", "" if text is None else str(text))
    value = _MEDIA_TAG.sub("MEDIA ·", value)
    value = _DRIVE.sub(lambda m: m.group(1) + "꞉", value)  # modifier-letter colon: looks the same
    return _PATH_START.sub(lambda m: m.group(1) + "∕", value)


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
    """Make inert, collapse whitespace and cut to ``limit`` characters (with an ellipsis)."""
    value = " ".join(inert(text).split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def summary60(text: Any) -> str:
    """Redact first, then clip: the only shape user text is ever stored in."""
    return clip(redact(str(text or "")[: SUMMARY_MAX * 4]), SUMMARY_MAX)


def result_line(text: Any) -> str:
    return clip(redact(str(text or "")[: RESULT_MAX * 4]), RESULT_MAX)


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
