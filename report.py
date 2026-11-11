"""Weekly numbers, the PNG report (1080×1350) and its text fallback.

matplotlib is imported lazily inside :func:`render_png`; if it is missing the
report degrades to text and nothing breaks.
"""

from __future__ import annotations

import logging
import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from . import privacy, strings
from .assets import palette
from .metering import human_tokens
from .store import Store

log = logging.getLogger("augur.report")

WIDTH, HEIGHT, DPI = 1080, 1350, 100
MARGIN = 64
MIN_TEXT_PX = 28


@dataclass
class GoalRow:
    slot: int  # 0 = detours
    name: str
    count: int = 0
    tokens: int = 0
    pct: int = 0
    planned: Optional[int] = None


@dataclass
class WeekStats:
    start: datetime
    end: datetime
    rows: list[GoalRow]
    counted: int
    tokens: int
    detour_pct: int
    parked: int
    closed: list[dict[str, Any]]
    corrections: int
    self_tokens: int
    has_demo: bool
    detours: list[dict[str, Any]] = field(default_factory=list)
    hidden: Optional[dict[str, Any]] = None

    @property
    def ready(self) -> int:
        return sum(1 for q in self.closed if q["status"] == "done")

    @property
    def needs_you(self) -> int:
        return sum(1 for q in self.closed if q["status"] == "needs_you")


def _largest_remainder(counts: list[int]) -> list[int]:
    total = sum(counts)
    if total == 0:
        return [0] * len(counts)
    raw = [c * 100 / total for c in counts]
    floors = [int(r) for r in raw]
    short = 100 - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[:short]:
        floors[i] += 1
    return floors


def week_stats(store: Store, now: datetime, lang: str = "en") -> WeekStats:
    start = now - timedelta(days=7)
    end = now + timedelta(seconds=1)
    goals = store.goals()
    window = store.turns_between(start, end)
    turns = [t for t in window if t["goal"] is not None]
    rows = [GoalRow(slot=g["slot"], name=g["name"], planned=int(g["planned_pct"])) for g in goals]
    rows.append(GoalRow(slot=0, name=strings.t("panel_detours", lang)))
    by_slot = {r.slot: r for r in rows}
    for t in turns:
        row = by_slot.get(int(t["goal"]))
        if row is None:
            continue
        row.count += 1
        row.tokens += int(t["tokens"] or 0)
    for row, pct in zip(rows, _largest_remainder([r.count for r in rows])):
        row.pct = pct
    detours = [t for t in turns if int(t["goal"]) == 0]
    return WeekStats(
        start=start,
        end=end,
        rows=rows,
        counted=len(turns),
        tokens=sum(int(t["tokens"] or 0) for t in turns),
        detour_pct=by_slot[0].pct,
        parked=store.queue_size(),
        closed=store.queue_closed_between(start, end),
        corrections=store.corrections_between(start, end),
        self_tokens=store.self_tokens_between(start, end),
        has_demo=any(t["source"] == "demo" for t in window),
        detours=detours,
    )


_MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
}


def date_label(moment: datetime, lang: str = "en") -> str:
    local = moment.astimezone()
    months = _MONTHS.get(lang, _MONTHS["en"])
    if lang == "pt":
        return f"{local.day} {months[local.month - 1]}"
    return f"{months[local.month - 1]} {local.day}"


def week_label(stats: WeekStats, lang: str = "en") -> str:
    """The 7-day window as a range, e.g. "Nov 5 – 11" or "Oct 30 – Nov 5"."""
    first = stats.start + timedelta(days=1)
    last = stats.end - timedelta(seconds=1)
    a, b = first.astimezone(), last.astimezone()
    if a.month == b.month:
        return f"{date_label(first, lang)} – {b.day}" if lang != "pt" else f"{a.day} – {date_label(last, lang)}"
    return f"{date_label(first, lang)} – {date_label(last, lang)}"


def caption_lines(stats: WeekStats, lang: str) -> list[str]:
    lines = []
    total = len(stats.closed)
    if total:
        lines.append(
            strings.t(
                "report_caption", lang, pct=stats.detour_pct, ready=stats.ready, total=total, needs=stats.needs_you,
                needs_word=strings.t("needs_one" if stats.needs_you == 1 else "needs_many", lang),
            )
        )
    elif stats.parked:
        lines.append(strings.t(
            "report_caption_waiting", lang, pct=stats.detour_pct, n=stats.parked,
            items_word=strings.t("items_wait_one" if stats.parked == 1 else "items_wait_many", lang),
        ))
    else:
        lines.append(strings.t("report_caption_noqueue", lang, pct=stats.detour_pct))
    if stats.hidden:
        lines.append(strings.t("report_caption_hidden", lang, theme=stats.hidden["theme"]))
    return lines


def _empty_queue_line(stats: WeekStats, lang: str) -> str:
    if stats.parked:
        return strings.t("report_waiting", lang, n=stats.parked)
    return strings.t("report_nothing_parked", lang)


def prune_files(data_dir: Path, now: datetime, report_days: int = 56, draft_days: int = 30) -> int:
    """Retention for files: report PNGs after 8 weeks, drafts after 30 days.

    Never follows a symlinked folder out of the plugin data dir.
    """
    removed = 0
    root = os.path.realpath(data_dir)
    for folder, pattern, days in ((data_dir, "report-*.png", report_days), (data_dir / "drafts", "*", draft_days)):
        if not folder.is_dir() or folder.is_symlink():
            continue
        real = os.path.realpath(folder)
        if os.path.commonpath([real, root]) != root:
            continue
        cutoff = now.timestamp() - days * 86400
        for path in folder.glob(pattern):
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    return removed


def render_text(stats: WeekStats, lang: str) -> str:
    out = [strings.t("report_title", lang, date=week_label(stats, lang))]
    if stats.has_demo:
        out.append(f"({strings.t('report_demo', lang)})")
    out.append(strings.t("report_hero", lang, pct=stats.detour_pct))
    out.append(strings.t("report_hero_sub", lang, n=stats.counted, tokens=human_tokens(stats.tokens)))
    out.append("")
    for row in stats.rows:
        if row.slot == 0:
            out.append(f"  {row.name:<16} {row.pct:>3}%")
        else:
            out.append(f"  {row.name:<16} " + strings.t("report_planned_actual", lang, actual=row.pct, planned=row.planned))
    if stats.hidden:
        out.append("")
        out.append(strings.t("report_hidden", lang, theme=stats.hidden["theme"], count=stats.hidden["count"]))
    out.append("")
    out.append(strings.t("report_ready", lang))
    if not stats.closed:
        out.append("  " + _empty_queue_line(stats, lang))
    for item in stats.closed:
        mark = {"done": "✓", "needs_you": "●", "dropped": "✗"}.get(item["status"], "·")
        line = f"  {mark} {privacy.inert(item['summary60'])}"
        reason = item.get("result_line") or (strings.t("dropped_stale", lang) if item["status"] == "dropped" else "")
        if reason:
            line += f" — {privacy.inert(reason)}"
        out.append(line)
    out.append("")
    out.append(strings.t("report_footer", lang, tokens=human_tokens(stats.self_tokens), corrections=stats.corrections))
    return "\n".join(out)


# --------------------------------------------------------------------- PNG


def _pt(px: float) -> float:
    """Pixel size → matplotlib points at our DPI."""
    return px * 72.0 / DPI


def _wrap(text: str, px: int, width_px: int) -> list[str]:
    chars = max(10, int(width_px / (px * 0.56)))
    return textwrap.wrap(text, width=chars) or [""]


def _fit(text: str, px: int, width_px: int) -> str:
    """One line, cut with an ellipsis to fit ``width_px``."""
    from .privacy import clip

    return clip(text, max(10, int(width_px / (px * 0.56))))


def _has_glyph(char: str) -> bool:
    try:
        from matplotlib import font_manager
        from matplotlib.ft2font import FT2Font

        font = FT2Font(font_manager.findfont("DejaVu Sans"))
        return font.get_char_index(ord(char)) != 0
    except Exception:
        return False


def render_png(stats: WeekStats, path: Path, lang: str = "en") -> Path:
    """Draw the report. Raises ImportError when matplotlib is unavailable."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle

    fig = Figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=palette.BACKGROUND)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(HEIGHT, 0)  # y grows downwards, in pixels
    ax.axis("off")
    ax.set_facecolor(palette.BACKGROUND)
    content_w = WIDTH - 2 * MARGIN

    def text(x, y, s, px, color=palette.TEXT, weight="normal", ha="left", va="top"):
        px = max(px, MIN_TEXT_PX)
        # parse_math=False: a "$" in a name or summary must not switch to math mode (or crash)
        return ax.text(
            x, y, privacy.inert(s), fontsize=_pt(px), color=color, fontweight=weight, ha=ha, va=va,
            family="DejaVu Sans", parse_math=False,
        )

    # --- header: vector compass + title -------------------------------------------
    cx, cy, r = MARGIN + 24, MARGIN + 24, 24
    ax.add_patch(Circle((cx, cy), r, fill=False, lw=3, ec=palette.TEXT_MUTED))
    ax.add_patch(Polygon([(cx, cy - r + 5), (cx + 7, cy), (cx - 7, cy)], closed=True, fc=palette.TEXT, ec="none"))
    ax.add_patch(Polygon([(cx, cy + r - 5), (cx + 7, cy), (cx - 7, cy)], closed=True, fc=palette.TEXT_MUTED, ec="none"))
    text(MARGIN + 64, MARGIN + 6, strings.t("report_title", lang, date=week_label(stats, lang)), 30, palette.TEXT_MUTED)
    y = MARGIN + 80
    if stats.has_demo:
        text(WIDTH - MARGIN, MARGIN + 6, strings.t("report_demo", lang), 28, palette.TEXT_MUTED, ha="right")

    # --- hero number -----------------------------------------------------------------
    text(MARGIN - 6, y - 8, f"{stats.detour_pct}%", 150, palette.TEXT, weight="bold")
    y += 162
    hero = strings.t("report_hero", lang, pct=stats.detour_pct)
    hero_tail = hero.split("%", 1)[1].strip() if "%" in hero else hero
    for line in _wrap(hero_tail, 44, content_w):
        text(MARGIN, y, line, 44, palette.TEXT)
        y += 54
    text(
        MARGIN, y + 4,
        strings.t("report_hero_sub", lang, n=stats.counted, tokens=human_tokens(stats.tokens)),
        30, palette.TEXT_MUTED,
    )
    y += 64

    # --- planned vs actual bars ----------------------------------------------------------
    bar_h = 26
    for row in stats.rows:
        color = palette.goal_color(row.slot)
        text(MARGIN, y, row.name, 32, palette.TEXT, weight="bold")
        value = (
            f"{row.pct}%"
            if row.slot == 0
            else strings.t("report_planned_actual", lang, actual=row.pct, planned=row.planned)
        )
        text(WIDTH - MARGIN, y + 2, value, 28, palette.TEXT_MUTED, ha="right")
        bar_y = y + 44
        ax.add_patch(Rectangle((MARGIN, bar_y), content_w, bar_h, fc=palette.TRACK, ec="none"))
        if row.planned:
            ax.add_patch(
                Rectangle((MARGIN, bar_y), content_w * row.planned / 100, bar_h, fc=color, alpha=0.28, ec="none")
            )
        if row.pct:
            ax.add_patch(Rectangle((MARGIN, bar_y + 5), content_w * row.pct / 100, bar_h - 10, fc=color, ec="none"))
        y += 94

    # --- hidden priority bubble ---------------------------------------------------------------
    if stats.hidden:
        examples = [str(e) for e in (stats.hidden.get("examples") or [])][:2]
        bubble_h = 70 + 38 * len(examples)
        ax.add_patch(
            FancyBboxPatch(
                (MARGIN, y), content_w, bubble_h, boxstyle="round,pad=0,rounding_size=18",
                fc=palette.TRACK, ec=palette.TEXT_MUTED, lw=2,
            )
        )
        title = strings.t("report_hidden", lang, theme=stats.hidden["theme"], count=stats.hidden["count"])
        text(MARGIN + 24, y + 18, _fit(title, 30, content_w - 48), 30, palette.TEXT, weight="bold")
        ey = y + 62
        for ex in examples:
            text(MARGIN + 24, ey, "“" + _wrap(ex, 28, content_w - 80)[0] + "”", 28, palette.TEXT_MUTED)
            ey += 38
        y += bubble_h + 24

    # --- ready while you slept ---------------------------------------------------------------
    footer_y = HEIGHT - MARGIN - 34
    text(MARGIN, y, strings.t("report_ready", lang), 30, palette.TEXT, weight="bold")
    y += 46
    marks = {"done": "✓" if _has_glyph("✓") else "+", "needs_you": "●" if _has_glyph("●") else "*", "dropped": "–"}
    if not stats.closed:
        text(MARGIN, y, _empty_queue_line(stats, lang), 28, palette.TEXT_MUTED)
    shown = 0
    renderer = canvas.get_renderer()
    # needs-you items first: they are the ones that ask for the user's attention
    ordered = sorted(stats.closed, key=lambda q: {"needs_you": 0, "done": 1}.get(q["status"], 2))
    for item in ordered:
        if y + 42 + (42 if shown + 1 < len(ordered) else 0) > footer_y - 8:
            break
        status = item["status"]
        mark_color = palette.DETOUR if status == "dropped" else palette.TEXT  # goal colors stay reserved for goals
        text(MARGIN, y, marks.get(status, "·"), 28, mark_color, weight="bold")
        label = item["summary60"]
        if status == "needs_you" and item.get("result_line"):
            label = f"{label} — {item['result_line']}"
        label = _fit(label, 28, content_w - 48)
        t = text(MARGIN + 40, y, label, 28, palette.DETOUR if status == "dropped" else palette.TEXT)
        if status == "dropped":
            bbox = t.get_window_extent(renderer)
            mid = y + 19
            ax.plot([MARGIN + 40, MARGIN + 40 + bbox.width], [mid, mid], color=palette.DETOUR, lw=2)
        y += 42
        shown += 1
    if shown < len(stats.closed):
        text(MARGIN + 40, y, f"+{len(stats.closed) - shown}", 28, palette.TEXT_MUTED)

    # --- footer ---------------------------------------------------------------------------------
    text(
        MARGIN, footer_y,
        strings.t("report_footer", lang, tokens=human_tokens(stats.self_tokens), corrections=stats.corrections),
        28, palette.TEXT_MUTED,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.png")
    canvas.print_png(str(tmp))
    os.replace(tmp, path)
    return path


def build(store: Store, data_dir: Path, now: datetime, lang: str, hidden: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Generate the report; returns ``{"path", "caption", "text"}`` (path is None on fallback)."""
    store.drop_stale(now)
    stats = week_stats(store, now, lang)
    stats.hidden = hidden
    caption = "\n".join(caption_lines(stats, lang))
    text_report = render_text(stats, lang)
    path = data_dir / f"report-{now.astimezone().strftime('%Y-%m-%d')}.png"
    try:
        render_png(stats, path, lang)
    except ImportError:
        return {"path": None, "caption": caption, "text": strings.t("report_text_fallback", lang) + "\n" + text_report}
    except Exception as exc:  # a drawing bug must never break the run
        log.warning("augur report rendering failed: %s", exc)
        return {"path": None, "caption": caption, "text": text_report}
    store.meta_set("last_report_path", str(path))
    return {"path": str(path), "caption": caption, "text": text_report}
