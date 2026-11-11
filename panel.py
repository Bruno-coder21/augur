"""The ``/bussola`` panel: the week at a glance, in the same words as the PNG.

ANSI colors only on the classic CLI; every other surface gets plain text
(messaging apps and Desktop chat bubbles do not render escape codes).
"""

from __future__ import annotations

from typing import Optional

from . import strings
from .assets import palette
from .metering import human_tokens
from .report import WeekStats, date_label, week_label

BAR_WIDTH = 20
FULL, EMPTY = "▇", "░"


def _bar(pct: int) -> str:
    filled = round(BAR_WIDTH * max(0, min(100, pct)) / 100)
    return FULL * filled + EMPTY * (BAR_WIDTH - filled)


def render(
    stats: WeekStats,
    lang: str,
    *,
    color: bool,
    paused_until: Optional[str] = None,
    last_friday: Optional[str] = None,
    health: tuple[int, int] = (0, 0),
) -> str:
    def paint(text: str, hex_color: str) -> str:
        return f"{palette.ansi(hex_color)}{text}{palette.ANSI_RESET}" if color else text

    def muted(text: str) -> str:
        return paint(text, palette.TEXT_MUTED)

    title = strings.t("panel_title", lang, date=week_label(stats, lang))
    lines = [paint(title, palette.TEXT) + (muted(strings.t("panel_demo", lang)) if stats.has_demo else ""), ""]
    if paused_until:
        lines.insert(1, muted(strings.t("panel_paused", lang, until=paused_until)))

    if stats.counted == 0:
        lines.append("  " + strings.t("panel_empty", lang))
    else:
        width = max(len(r.name) for r in stats.rows)
        width = min(max(width, 8), 18)
        for row in stats.rows:
            name = (row.name[: width - 1] + "…") if len(row.name) > width else row.name
            hex_color = palette.goal_color(row.slot)
            if row.slot == 0:
                tail = f"{row.pct:>3}%"
            else:
                tail = strings.t("panel_goal", lang, pct=row.pct, planned=row.planned)
            lines.append(f"  {name:<{width}}  {paint(_bar(row.pct), hex_color)}  {tail}")
        lines.append("")
        lines.append("  " + muted(strings.t("panel_requests", lang, n=stats.counted, tokens=human_tokens(stats.tokens))))

    friday = (
        strings.t("panel_friday_on", lang, when=last_friday)
        if last_friday
        else strings.t("panel_friday_off", lang)
    )
    lines.append("")
    lines.append("  " + strings.t("panel_queue", lang, n=stats.parked, friday=friday))
    if stats.hidden:
        lines.append("  " + paint(
            strings.t("panel_hidden", lang, theme=stats.hidden["theme"], count=stats.hidden["count"]),
            palette.TEXT,
        ))
    lines.append("  " + muted(strings.t("panel_self_cost", lang, tokens=human_tokens(stats.self_tokens))))
    bad, total = health
    if total >= 10 and bad * 10 >= total * 3:  # 30% or more slow/failed
        lines.append("")
        lines.append("  " + strings.t("panel_health", lang, bad=bad, n=total))
    return "\n".join(lines)


def last_friday_label(iso_ts: Optional[str], lang: str) -> Optional[str]:
    if not iso_ts:
        return None
    try:
        from .store import parse_iso

        return date_label(parse_iso(iso_ts), lang)
    except Exception:
        return None
