"""The ``/augur`` panel: the week at a glance, in the same words as the PNG.

ANSI colors only on the classic CLI; every other surface gets plain text
(messaging apps and Desktop chat bubbles do not render escape codes).
"""

from __future__ import annotations

from typing import Optional

from . import privacy, strings
from .assets import palette
from .metering import human_tokens
from .report import WeekStats, date_label, week_label
from .store import parse_iso

BAR_WIDTH = 20
FULL, EMPTY = "▇", "░"


COMPACT_BAR = 10
COMPACT_NAME = 14


def _bar(pct: int, width: int = BAR_WIDTH) -> str:
    filled = round(width * max(0, min(100, pct)) / 100)
    return FULL * filled + EMPTY * (width - filled)


def render(
    stats: WeekStats,
    lang: str,
    *,
    color: bool,
    paused_until: Optional[str] = None,
    last_friday: Optional[str] = None,
    health: tuple[int, int] = (0, 0),
    compact: bool = False,
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
    elif compact:
        # Messaging apps use proportional fonts: a short monospace block that fits a phone.
        block = []
        for row in stats.rows:
            label = privacy.inert(row.name)
            name = label if len(label) <= COMPACT_NAME else label[: COMPACT_NAME - 1] + "…"
            tail = f"{row.pct:>3}%" if row.slot == 0 else f"{row.pct:>3}% / {row.planned}%"
            block.append(f"{name:<{COMPACT_NAME}} {_bar(row.pct, COMPACT_BAR)} {tail}")
        lines.append("```")
        lines.extend(block)
        lines.append("```")
        lines.append(strings.t("panel_legend", lang))
        lines.append(strings.t("panel_requests", lang, n=stats.counted, tokens=human_tokens(stats.tokens),
                                  requests_word=strings.t("requests_one" if stats.counted == 1 else "requests_many", lang)))
    else:
        width = max(len(r.name) for r in stats.rows)
        width = min(max(width, 8), 18)
        for row in stats.rows:
            label = privacy.inert(row.name)
            name = (label[: width - 1] + "…") if len(label) > width else label
            hex_color = palette.goal_color(row.slot)
            if row.slot == 0:
                tail = f"{row.pct:>3}%"
            else:
                tail = strings.t("panel_goal", lang, pct=row.pct, planned=row.planned)
            lines.append(f"  {name:<{width}}  {paint(_bar(row.pct), hex_color)}  {tail}")
        lines.append("")
        lines.append("  " + muted(strings.t("panel_requests", lang, n=stats.counted, tokens=human_tokens(stats.tokens),
                                  requests_word=strings.t("requests_one" if stats.counted == 1 else "requests_many", lang))))

    friday = (
        strings.t("panel_friday_on", lang, when=last_friday)
        if last_friday
        else strings.t("panel_friday_off", lang)
    )
    pad = "" if compact else "  "
    lines.append("")
    lines.append(pad + strings.t("panel_queue", lang, n=stats.parked, friday=friday,
                                   parked_word=strings.t("parked_one" if stats.parked == 1 else "parked_many", lang)))
    if stats.hidden:
        lines.append(pad + paint(
            strings.t("panel_hidden", lang, theme=privacy.inert(stats.hidden["theme"]), count=stats.hidden["count"]),
            palette.TEXT,
        ))
    lines.append(pad + muted(strings.t("panel_self_cost", lang, tokens=human_tokens(stats.self_tokens))))
    bad, total = health
    if total >= 10 and bad * 10 >= total * 3:  # 30% or more slow/failed
        lines.append("")
        lines.append(pad + strings.t("panel_health", lang, bad=bad, n=total))
    return "\n".join(lines)


def last_friday_label(iso_ts: Optional[str], lang: str) -> Optional[str]:
    if not iso_ts:
        return None
    try:
        return date_label(parse_iso(iso_ts), lang)
    except Exception:
        return None
