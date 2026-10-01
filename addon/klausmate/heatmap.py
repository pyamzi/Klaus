"""The Klaus review heatmap — a year of study activity on the deck list.

A GitHub-style contribution grid under Anki's deck table: one cell per
day, past days coloured by how many cards were answered, upcoming days
ghosted by how many fall due, and a stats line carrying the current and
longest streak, the daily average, and the share of days studied.

PROVENANCE. Pouya asked for Glutanimate's Review Heatmap
(``References/review-heatmap-main``, AGPLv3) restyled into Klaus's look.
That vendored 1.0.1 tree is where the *definitions* below come from —
what counts as a streak, that the forecast is queue 2/3 due dates, that
the daily average is over days STUDIED rather than days elapsed, and
that day bucketing has to happen in SQL with ``'localtime'`` so a DST
shift cannot smear one day into its neighbour. None of its code is
copied, and it is not vendored, because that release cannot be used as
it stands: it predates this Anki by four years (``anki.lang._``,
``anki.stats.CollectionStats``, ``addHook`` all belong to the 2.1.4x
era), it ships its web layer UNBUILT — TypeScript plus cal-heatmap plus
a 150KB d3, needing Glutanimate's ``aab`` builder and a Node toolchain
that is not installed here — and it carries ``libaddon`` and AGPL
Section 7 terms this addon has no other reason to take on. The grid it
needed d3 for is ~40 lines of CSS grid in 2026.

THE STYLING IS THE POINT, so none of it is invented here:

* the panel joins :func:`background.panel_css`'s frosted family by
  wearing the ``.klaus-hm`` hook listed in that selector, which is why
  it frosts, tints and rounds exactly like the deck table in every
  background mode, and why retuning the frost retunes it too;
* every cell colour is the ACTIVE accent at rising alpha, read from
  ``theme.palette``, so the heatmap re-colours with every colour theme
  — the six presets, the community palettes and a custom colour alike —
  without a line of per-theme code;
* both palettes ship keyed on Anki's own ``:root.night-mode`` class
  rather than baking whichever is current, for the same reason
  ``theme.toolbar_css`` takes no ``night`` argument: Anki flips that
  class with JS and never re-runs the hook that injected this.

Everything above the "aqt glue" divider is aqt-free and pure, for
``tests/test_heatmap.py``.
"""

from __future__ import annotations

import datetime
from typing import Any

from . import background, theme
from . import settings

SECS_PER_DAY = 86400
_EPOCH = datetime.date(1970, 1, 1)

# A year back, four weeks forward — the window the grid is drawn for.
# The STATS are deliberately not windowed (see stats_from_history).
DEFAULT_HISTORY_DAYS = 365
DEFAULT_FORECAST_DAYS = 28

# Cell geometry, in px. One week column is CELL + GAP wide, which is
# what lets the month labels ride the same grid as the cells.
CELL = 10  # Glutanimate's cal-heatmap cellSize
GAP = 3
# Extra air before the column that opens a new month, so a year reads as
# months instead of one undifferentiated ribbon. Applied to the cells
# and to the month strip from the SAME list, so they cannot drift apart.
MONTH_GAP = 5

# Windows the gear offers, in days, with the labels it shows them under.
# The reference addon calls these limhist/limfcst; ours are a short menu
# rather than a free number, so a stray value can never size the grid.
RANGE_CHOICES = (91, 182, 365)
RANGE_LABELS = ("3 months", "6 months", "1 year")

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
# The left rail: one letter per row, Sunday-first (see _row). GitHub
# labels alternate rows with three-letter names; Pouya asked for the
# whole S M T W T F S column, which only fits as initials. Derived from
# _WEEKDAYS so the rail and the tooltips can never name different days.
_WEEKDAY_INITIALS = tuple(name[0] for name in _WEEKDAYS)


# ─────────────────────────────────────────────────────────────────────
# Days
#
# Every day here is an INTEGER DAY NUMBER — days since 1970-01-01 — not
# a timestamp. The SQL below buckets each review into its local day and
# returns that day's midnight as a UTC-flavoured epoch; dividing by
# 86400 turns it into a number that is timezone-free, exactly one apart
# for consecutive days (which is the whole of the streak logic) and
# safe to turn back into a calendar date. Nothing downstream has to
# think about clocks again.
# ─────────────────────────────────────────────────────────────────────


def day_to_date(day: int) -> datetime.date:
    """The calendar date of day number *day*."""
    return _EPOCH + datetime.timedelta(days=int(day))


def _day_of(date: datetime.date) -> int:
    """Day number of *date* — :func:`day_to_date` backwards."""
    return (date - _EPOCH).days


def _row(day: int) -> int:
    """Grid row for *day*, Sunday-first (0 = Sunday ... 6 = Saturday)."""
    return (day_to_date(day).weekday() + 1) % 7


def enabled(cfg: Any) -> bool:
    """Whether to draw the heatmap. On unless explicitly switched off,
    and a corrupt value reads as on rather than silently hiding it."""
    if not isinstance(cfg, dict):
        return True
    value = cfg.get("heatmap_enabled", True)
    return value if isinstance(value, bool) else True


def history_window(cfg: Any) -> int:
    """How much past to draw. Only the menu's own choices are honoured —
    anything else (corrupt, hand-edited, from a future version) reads as
    the default rather than being allowed to size the grid."""
    if isinstance(cfg, dict):
        value = cfg.get("heatmap_history_days", DEFAULT_HISTORY_DAYS)
        if value in RANGE_CHOICES:
            return int(value)
    return DEFAULT_HISTORY_DAYS


def forecast_window(cfg: Any) -> int:
    """Days of scheduled-ahead ghosting, or 0 when switched off. Only an
    explicit False hides them: a corrupt value shows the forecast, the
    same way a corrupt value leaves the heatmap itself on."""
    if isinstance(cfg, dict) and cfg.get("heatmap_forecast", True) is False:
        return 0
    return DEFAULT_FORECAST_DAYS


# ─────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────


def stats_from_history(history: list, today: int) -> dict:
    """Streaks and averages from ``[(day, count), ...]``, ascending.

    Computed over the WHOLE history, not the drawn window: "you have
    studied on 62% of days" is only meaningful against every day since
    your first review, and a longest streak that silently forgot
    anything older than a year would be worse than not shown. The
    window only decides how much of the grid is painted.
    """
    empty = {
        "streak_cur": 0, "streak_max": 0, "days_learned": 0,
        "total": 0, "daily_avg": 0, "pct_days_active": 0,
    }
    if not history:
        return empty

    days = [int(d) for d, _ in history]
    total = sum(int(c) for _, c in history)

    run = 0
    streak_max = 0
    for i, day in enumerate(days):
        run = run + 1 if i and days[i - 1] == day - 1 else 1
        streak_max = max(streak_max, run)

    # `run` is now the length of the final run, which only counts as a
    # CURRENT streak if it reaches today or yesterday — today's studying
    # may simply not have happened yet, and breaking the streak at
    # midnight would be both wrong and discouraging.
    streak_cur = run if days[-1] in (today, today - 1) else 0

    days_learned = len(days)
    span = today - days[0] + 1
    return {
        "streak_cur": streak_cur,
        "streak_max": streak_max,
        "days_learned": days_learned,
        "total": total,
        "daily_avg": int(round(total / days_learned)),
        # A single day of history is 100% of the days there were.
        "pct_days_active": (
            100 if span <= 1 else int(round(days_learned / span * 100))
        ),
    }


# Glutanimate's own ramp (``renderer._dynamic_legend_factors``), taken
# as-is. Klaus used to run four factors ending at 1.0, which had two
# costs the reference does not pay: every day at or above the average
# collapsed into ONE colour — a 111-card day and a 500-card day drew
# identical ink — and with nothing below 0.25 a light day rounded away
# entirely. Five of these nine sit above the average, which is what lets
# a heavy day still read as heavy.
RAMP_FACTORS = (0.125, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0)

# Also the reference's: below ~20/day the fractions stop separating
# anything, so the ramp is computed against a floor rather than against
# a genuinely tiny average.
RAMP_MIN_BASE = 20


def ramp_levels(daily_avg: int) -> list:
    """The cut-offs that map a day's count onto a colour step.

    Derived from the user's own daily average rather than fixed counts,
    so the ramp means the same thing to somebody doing 20 cards a day
    and somebody doing 800. Forced strictly ascending, because rounding
    can otherwise collide two adjacent factors into one usable step.
    """
    base = max(RAMP_MIN_BASE, int(daily_avg))
    levels: list = []
    previous = 0
    for fraction in RAMP_FACTORS:
        value = max(previous + 1, int(round(base * fraction)))
        levels.append(value)
        previous = value
    return levels


# Below 1.0 this front-loads the ramp: alpha climbs fast over the early
# steps and eases off near the top.
#
# It has to. The reference can afford a linear scale because its steps
# are nine distinct HUES of a lime/ice/flame palette — its mid-steps are
# vividly coloured. Ours are one accent at rising alpha over a dark
# panel, where the middle of a linear 0.12→1.0 spread is muddy: spread
# evenly, an average day landed at 0.56 and the whole grid washed out
# (measured against the live collection, 2026-08-31). The curve restores
# a solid average day without giving up the extra steps above it.
RAMP_ALPHA_CURVE = 0.65


def ramp_alphas(low: float, high: float) -> tuple:
    """``len(RAMP_FACTORS)`` alphas from *low* to *high* along
    :data:`RAMP_ALPHA_CURVE`.

    Generated rather than written out so the ramp's length lives in ONE
    place: adding a factor can never leave a colour step undefined.
    """
    steps = len(RAMP_FACTORS)
    if steps == 1:
        return (high,)
    return tuple(
        round(low + (high - low) * (i / (steps - 1)) ** RAMP_ALPHA_CURVE, 3)
        for i in range(steps)
    )


def level_for(count: int, levels: list) -> int:
    """Colour step 0-N for *count* against :func:`ramp_levels` output."""
    if count <= 0:
        return 0
    for index, threshold in enumerate(levels):
        if count <= threshold:
            return index + 1
    return len(levels)


# ─────────────────────────────────────────────────────────────────────
# Grid
# ─────────────────────────────────────────────────────────────────────


def build_columns(
    history: dict,
    forecast: dict,
    today: int,
    history_days: int = DEFAULT_HISTORY_DAYS,
    forecast_days: int = DEFAULT_FORECAST_DAYS,
) -> list:
    """Week columns for the grid, oldest first.

    Columns are grouped BY MONTH: a month gets its own run of week
    columns, and a week that straddles a month boundary is split
    between the two runs rather than assigned to one of them. That is
    what makes every day sit under its own month's label — the whole
    point of the strip (Pouya, 2026-09-01: "the day that fits August is
    under August, and if it's in September, it's under September").

    The cost is deliberate and was explicitly accepted: the first and
    last column of each month are PARTIAL, so the grid is no longer an
    unbroken 7-row ribbon ("You don't have to have perfect squares").
    Two earlier attempts tried to keep the ribbon and move the label
    instead — the label on the first week that STARTS in the month, then
    on the week owning MOST of its days — and both leave real days
    under the wrong name, because a week simply does not belong to one
    month.

    Each column is ``{"start": <day of its Sunday>, "cells": [...],
    "month": <1-12>}`` with exactly seven cells, Sunday-first. A cell is
    ``None`` where the week runs outside this month or past either end
    of the window — the placeholder keeps every column seven rows tall,
    so the weekday a cell sits on is always readable off its row.

    Today belongs to history even though it also has cards due: what
    you have already done outranks what is still scheduled.
    """
    history_days = max(1, int(history_days))
    forecast_days = max(0, int(forecast_days))
    first = today - history_days + 1
    last = today + forecast_days

    columns: list = []
    cur = day_to_date(first).replace(day=1)
    stop = day_to_date(last).replace(day=1)
    while cur <= stop:
        nxt = (
            datetime.date(cur.year + 1, 1, 1) if cur.month == 12
            else datetime.date(cur.year, cur.month + 1, 1)
        )
        # This month, clipped to the drawn window.
        lo = max(first, _day_of(cur))
        hi = min(last, _day_of(nxt - datetime.timedelta(days=1)))
        if lo <= hi:
            start = lo - _row(lo)        # rewind to that week's Sunday
            while start <= hi:
                cells: list = []
                for row in range(7):
                    day = start + row
                    if day < lo or day > hi:
                        cells.append(None)
                    elif day <= today:
                        cells.append((day, int(history.get(day, 0)), False))
                    else:
                        cells.append((day, int(forecast.get(day, 0)), True))
                columns.append(
                    {"start": start, "cells": cells, "month": cur.month}
                )
                start += 7
        cur = nxt
    return columns


def month_labels(columns: list) -> list:
    """One label per column: the month's name on the first column of its
    run, empty elsewhere.

    No heuristic left. Columns are grouped by month
    (:func:`build_columns`), so a column belongs to exactly one month
    and the label is simply where a new run begins — including the very
    first column, whose days really are its month's days even when the
    window opens mid-month. The two rules this replaced (month of the
    week's Sunday; month owning most of the week's days) both had to
    guess, because they were labelling weeks that spanned two months.
    """
    labels: list = []
    previous = None
    for column in columns:
        month = column["month"]
        labels.append(_MONTHS[month - 1] if month != previous else "")
        previous = month
    return labels


# ─────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _tooltip(day: int, count: int, future: bool) -> str:
    date = day_to_date(day)
    when = f"{_WEEKDAYS[_row(day)]}, {date.day} {_MONTHS[date.month - 1]} {date.year}"
    # Glutanimate's wording, including its split between an empty past
    # day ("No reviews") and an empty future one ("No cards due").
    if future:
        if count:
            return f"{_plural(count, 'card')} due on {when}"
        return f"No cards due on {when}"
    if count:
        return f"{_plural(count, 'card')} reviewed on {when}"
    return f"No reviews on {when}"


def _cells_html(columns: list, levels: list, starts: list) -> str:
    """The grid, one element per WEEK column.

    Columns are their own boxes rather than one flat run of cells so the
    first column of a month can carry ``ms`` and open a gap. *starts*
    comes from :func:`month_labels`, so the gap and the label that names
    it are always decided by the same list.
    """
    parts: list = []
    for index, column in enumerate(columns):
        parts.append(
            '<div class="klaus-hm-col%s">' % (" ms" if starts[index] else "")
        )
        for cell in column["cells"]:
            if cell is None:
                parts.append('<span class="klaus-hm-c pad"></span>')
                continue
            day, count, future = cell
            step = level_for(count, levels)
            classes = ["klaus-hm-c"]
            if step:
                classes.append(("f" if future else "l") + str(step))
            attrs = ""
            if count:
                # Only days with something to show are clickable — an
                # empty day would open an empty Browse and read as a
                # broken link.
                classes.append("hit")
                attrs = f" onclick=\"pycmd('klausmate:heatmap:{day}')\""
            parts.append(
                f'<span class="{" ".join(classes)}"'
                f' title="{_tooltip(day, count, future)}"{attrs}></span>'
            )
        parts.append("</div>")
    return "".join(parts)


# Glutanimate's stats row verbatim: its four labels, in its order, with
# its own hover text (web_content.HTML_STREAK). Label leads, value
# follows — the reference's arrangement, not the accent-number-first one
# Klaus used to run.
_STAT_ROW = (
    ("daily_avg", "Daily average", "",
     "Average reviews on active days"),
    ("pct_days_active", "Days learned", "%",
     "Percentage of days with review activity over entire review history"),
    ("streak_max", "Longest streak", "",
     "Longest continuous streak of review activity. "
     "All types of repetitions included."),
    ("streak_cur", "Current streak", "",
     "Current card review activity streak. "
     "All types of repetitions included."),
)


def _stats_html(stats: dict) -> str:
    return "".join(
        f'<span class="klaus-hm-stat">'
        f'<span class="klaus-hm-stat-label">{label}:</span>'
        f'<b title="{tip}">{stats[key]}{suffix}</b>'
        f"</span>"
        for key, label, suffix, tip in _STAT_ROW
    )


# A settings glyph rather than a gear character: the emoji gear renders
# in colour on macOS and would be the one non-monochrome mark on the
# deck screen. Strokes are currentColor, so it follows the palette.
_GEAR_SVG = (
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">'
    '<g fill="none" stroke="currentColor" stroke-width="1.4"'
    ' stroke-linecap="round">'
    '<path d="M2 4.75h4.2M10.8 4.75H14M2 11.25h2.2M8.8 11.25H14"/>'
    '<circle cx="8.5" cy="4.75" r="1.9"/><circle cx="6.5" cy="11.25" r="1.9"/>'
    "</g></svg>"
)

SET_PREFIX = "klausmate:heatmap:set:"


def _gear_html(history: int, forecast: int) -> str:
    """The corner menu.

    A ``<details>`` element, so it opens and closes with no script of
    ours anywhere in Anki's own deck-browser document — one less
    listener to leak, and it cannot fall out of sync with the markup.
    Every option posts its choice; Python validates it (JS is never
    trusted with a config value) and the redraw closes the menu.
    """
    ranges = "".join(
        f'<button class="klaus-hm-opt{" on" if days == history else ""}"'
        f" onclick=\"pycmd('{SET_PREFIX}history:{days}')\">{label}</button>"
        for days, label in zip(RANGE_CHOICES, RANGE_LABELS)
    )
    upcoming = "".join(
        f'<button class="klaus-hm-opt{" on" if bool(forecast) == want else ""}"'
        f" onclick=\"pycmd('{SET_PREFIX}forecast:{int(want)}')\">{label}"
        "</button>"
        for want, label in ((True, "Show"), (False, "Hide"))
    )
    return (
        '<details class="klaus-hm-gear">'
        '<summary title="Heatmap settings">' + _GEAR_SVG + "</summary>"
        '<div class="klaus-hm-menu">'
        '<div class="klaus-hm-menu-t">Range</div>'
        f'<div class="klaus-hm-opts">{ranges}</div>'
        '<div class="klaus-hm-menu-t">Upcoming</div>'
        f'<div class="klaus-hm-opts">{upcoming}</div>'
        "</div></details>"
    )


def heatmap_html(
    history: dict,
    forecast: dict,
    today: int,
    stats: dict,
    history_days: int = DEFAULT_HISTORY_DAYS,
    forecast_days: int = DEFAULT_FORECAST_DAYS,
) -> str:
    """The whole panel. Empty string when there is nothing to show —
    a brand-new collection gets Anki's screen back, not a blank grid."""
    if not history and not forecast:
        return ""

    columns = build_columns(
        history, forecast, today, history_days, forecast_days
    )
    levels = ramp_levels(stats.get("daily_avg", 0))

    labels = month_labels(columns)
    # One list decides both the gap and the label above it.
    starts = [bool(label) for label in labels]
    # A month that starts in the last column has no room for its name
    # ("No" for Nov, cut by the plot's edge): keep its gap, drop the text.
    months = "".join(
        '<span class="klaus-hm-m%s">%s</span>'
        % (" ms" if starts[index] else "", label if len(labels) - index >= 2 else "")
        for index, label in enumerate(labels)
    )
    weekdays = "".join(
        f'<span class="klaus-hm-w">{_WEEKDAY_INITIALS[row]}</span>'
        for row in range(7)
    )
    return (
        '<div class="klaus-hm">'
        # No heading: the grid says what it is (Pouya, 2026-08-31), so
        # the stats row is the whole top line and centres in it.
        f'{_gear_html(history_days, forecast_days)}'
        '<div class="klaus-hm-top">'
        f'<span class="klaus-hm-stats">{_stats_html(stats)}</span>'
        "</div>"
        # The grid is allowed to be wider than the window and scroll
        # inside its own box. It must never widen the panel: forcing a
        # width here is what pushed the deck panel off-screen before.
        # The weekday letters sit OUTSIDE the scroller, beside it, so a
        # range that scrolls keeps them pinned (Pouya: "pin the weekday
        # letters too") with no background to match the card behind them.
        '<div class="klaus-hm-body">'
        f'<div class="klaus-hm-wd">{weekdays}</div>'
        '<div class="klaus-hm-scroll"><div class="klaus-hm-plot">'
        f'<div class="klaus-hm-months">{months}</div>'
        '<div class="klaus-hm-cells">'
        f'{_cells_html(columns, levels, starts)}</div>'
        "</div></div></div>"
        # No legend: Glutanimate's addon renders with displayLegend
        # false — the grid and the stats row carry the whole story. The
        # personal "0 → a full day (N)" line the 2026-08-27 audit built
        # was retired with it (Pouya's call, 2026-08-31).
        "</div>"
    )


def _palette_vars(night: bool) -> str:
    """One palette's worth of heatmap tokens.

    The steps are the live accent at rising alpha rather than fixed
    colours, which is what makes the grid follow every colour
    theme — and alpha over the frosted panel keeps the photo behind it
    readable instead of stamping opaque blocks on top of it.
    """
    colours = theme.palette(night)
    # Scheduled days share the accent's hue but stay hollow: a ring and
    # a faint wash, so "already done" and "still to come" never read as
    # the same weight of ink.
    future = "".join(
        f" --klaus-hm-f{step}: {theme.accent_rgba(night, alpha)};"
        for step, alpha in enumerate(ramp_alphas(0.05, 0.26), start=1)
    )
    done = "".join(
        f" --klaus-hm-l{step}: {theme.accent_rgba(night, alpha)};"
        for step, alpha in enumerate(ramp_alphas(0.15, 1.0), start=1)
    )
    # Neutral scrims, not palette colours: a plain wash of the surface
    # for a day with nothing on it, matching how panel_css spells its
    # own glass.
    empty = "rgba(255,255,255,0.08)" if night else "rgba(0,0,0,0.06)"
    return (
        f"{done}{future}"
        f" --klaus-hm-ring: {theme.accent_rgba(night, 0.38)};"
        f" --klaus-hm-empty: {empty};"
        f" --klaus-hm-accent: {colours['blue_bright']};"
        f" --klaus-hm-text: {colours['text']};"
        f" --klaus-hm-muted: {colours['text_muted']};"
        # The corner menu is a floating surface, so it is OPAQUE — a
        # popover you can read the grid through is a popover you cannot
        # read. Spelled in Klaus's own palette rather than borrowing
        # Anki's --canvas-overlay: the panel can fall back on a light
        # value harmlessly, but a menu that lands white at night is a
        # flashbang.
        f" --klaus-hm-menu: {colours['surface']};"
    )


def heatmap_css() -> str:
    """The panel's stylesheet, both palettes.

    No ``night`` argument on purpose — see the module docstring. The
    panel's own surface is spelled in ANKI's tokens so it looks native
    in theme mode, where Klaus paints no background; in image and colour
    modes ``background.panel_css`` overrides all four of those
    properties with the frosted family's, so the heatmap always matches
    whatever the deck table is doing.
    """
    return (
        f":root {{{_palette_vars(False)} }}"
        f":root.night-mode {{{_palette_vars(True)} }}"
        " .klaus-hm {"
        # position: relative anchors the corner gear to the PANEL, which
        # is what keeps it out of the top row's flow — the stats row can
        # then centre on the panel rather than on whatever space a
        # sibling control left it.
        " position: relative;"
        " display: inline-block; text-align: left;"
        " box-sizing: border-box; max-width: 100%;"
        " margin: 1.4em auto 0.6em auto; padding: 14px 16px 11px 16px;"
        " background: var(--canvas-glass, rgba(255,255,255,0.5));"
        " border: 1px solid var(--border-subtle, rgba(0,0,0,0.09));"
        " border-radius: var(--border-radius-medium, 12px);"
        f" font-family: {theme.FONT_FAMILY};"
        " color: var(--klaus-hm-text);"
        " }"
        " .klaus-hm-top {"
        " display: flex; flex-wrap: wrap; align-items: baseline;"
        # Centred, and padded by the same amount on BOTH sides so the
        # row stays centred on the panel while still clearing the gear
        # sitting in the corner above its right end.
        " justify-content: center; gap: 6px 18px; padding: 0 22px;"
        " margin-bottom: 11px;"
        " }"
        " .klaus-hm-stats { display: flex; flex-wrap: wrap; gap: 14px; }"
        " .klaus-hm-stat {"
        " font-size: 11px; color: var(--klaus-hm-muted);"
        " white-space: nowrap;"
        " }"
        # Label first, value after — the reference's arrangement. The
        # value keeps Klaus's accent weight so the row still has an
        # anchor to scan by.
        " .klaus-hm-stat-label { margin-right: 4px; }"
        " .klaus-hm-stat b {"
        " color: var(--klaus-hm-accent); font-weight: 600;"
        " font-size: 12px;"
        " }"
        " .klaus-hm-scroll {"
        " overflow-x: auto; overflow-y: hidden; padding-bottom: 3px;"
        " }"
        # NEWEST WEEKS FIRST when the box is narrower than the range (a
        # 3-column dashboard grid, a large widget size): a scroller opens
        # at its inline START, which was the oldest week, so today and
        # the forecast were the part cut off. The scroller runs opposite
        # to the plot, so it opens at the plot's END; the plot itself
        # keeps the page's direction. Mirrored for RTL pages.
        " .klaus-hm-scroll { direction: rtl; }"
        " .klaus-hm-scroll > .klaus-hm-plot { direction: ltr; }"
        " [dir=rtl] .klaus-hm-scroll { direction: ltr; }"
        " [dir=rtl] .klaus-hm-scroll > .klaus-hm-plot { direction: rtl; }"
        # The weekday column, then the scroller, centred together while
        # the range fits; once it does not, the scroller shrinks (min-width
        # 0) and scrolls while the column stays put.
        " .klaus-hm-body {"
        f" display: flex; align-items: flex-start; justify-content: center; gap: {GAP + 3}px;"
        " }"
        " .klaus-hm-body > .klaus-hm-scroll { flex: 0 1 auto; min-width: 0; }"
        # Two rows: the month strip, then the cells. The weekday column
        # uses the cells' row sizes and drops by the month strip plus the
        # row gap, so the letters line up by construction.
        " .klaus-hm-plot {"
        " display: grid; grid-template-columns: auto;"
        " row-gap: 4px; width: max-content;"
        # Centre the grid when it is narrower than the stats row above
        # it (a 3-month range is), and go inert when it is not: auto
        # margins resolve to 0 the moment the content overflows, so
        # this can never fight the scroller.
        " margin: 0 auto;"
        " }"
        " .klaus-hm-months {"
        f" display: flex; gap: {GAP}px; height: 11px;"
        " }"
        # Month and weekday labels are the smallest type in the app,
        # sitting on a frosted panel over an ARBITRARY user photo — so
        # they wear full text colour: muted's contrast was AA-checked
        # against bg/surface, never against a photo behind a 50% tint.
        # Only the stat labels stay muted; their bold accent numbers
        # anchor them.
        " .klaus-hm-m {"
        # min-width: 0 is load-bearing, not tidiness. A flex item's
        # automatic minimum size is its MIN-CONTENT size, and
        # white-space: nowrap makes a month name unbreakable — so
        # "Sep" floors this box at ~20px and the 10px basis is
        # ignored. Only the LABELLED boxes inflate, so each one shoves
        # every later column right: ~8px a label, 103px of drift by the
        # far end of a year, which is the labels walking away from
        # their own months. (The pre-flex grid never had this: a fixed
        # grid-auto-columns track is not sized by its item.)
        " min-width: 0;"
        f" flex: 0 0 {CELL}px;"
        " font-size: 10px; color: var(--klaus-hm-text);"
        " white-space: nowrap; overflow: visible; line-height: 11px;"
        " }"
        # ONE rule for both strips: a month's gap and the label that
        # names it can never end up on different columns.
        " .klaus-hm-col.ms, .klaus-hm-m.ms {"
        f" margin-left: {MONTH_GAP}px;"
        " }"
        " .klaus-hm-wd {"
        f" display: grid; grid-template-rows: repeat(7, {CELL}px);"
        f" row-gap: {GAP}px; padding-top: {11 + 4}px; flex: none;"
        " }"
        " .klaus-hm-w {"
        " font-size: 10px; color: var(--klaus-hm-text);"
        f" line-height: {CELL}px; text-align: right; white-space: nowrap;"
        " }"
        " .klaus-hm-cells {"
        f" display: flex; gap: {GAP}px;"
        " }"
        " .klaus-hm-col {"
        f" display: grid; grid-template-rows: repeat(7, {CELL}px);"
        f" row-gap: {GAP}px;"
        " }"
        " .klaus-hm-c {"
        f" width: {CELL}px; height: {CELL}px; border-radius: 2px;"
        " background: var(--klaus-hm-empty); display: block;"
        " }"
        # Out-of-window placeholders hold their row open and nothing else.
        " .klaus-hm-c.pad { background: transparent; }"
        # Generated from the ramp's own length, so adding a factor can
        # never leave a step with a var but no rule to use it.
        + "".join(
            f" .klaus-hm-c.l{n} {{ background: var(--klaus-hm-l{n}); }}"
            for n in range(1, len(RAMP_FACTORS) + 1)
        )
        + ", ".join(
            f" .klaus-hm-c.f{n}" for n in range(1, len(RAMP_FACTORS) + 1)
        )
        + " {"
        " box-shadow: inset 0 0 0 1px var(--klaus-hm-ring);"
        " }"
        + "".join(
            f" .klaus-hm-c.f{n} {{ background: var(--klaus-hm-f{n}); }}"
            for n in range(1, len(RAMP_FACTORS) + 1)
        )
        +
        # The corner menu. <details> carries the open/closed state
        # itself, so nothing here needs a listener in Anki's document.
        " .klaus-hm-gear { position: absolute; top: 9px; right: 10px; }"
        " .klaus-hm-gear > summary {"
        " list-style: none; display: block; cursor: pointer;"
        " padding: 3px; border-radius: 5px; line-height: 0;"
        " color: var(--klaus-hm-muted);"
        " }"
        " .klaus-hm-gear > summary::-webkit-details-marker {"
        " display: none;"
        " }"
        " .klaus-hm-gear > summary:hover {"
        " color: var(--klaus-hm-text); background: var(--klaus-hm-empty);"
        " }"
        " .klaus-hm-gear[open] > summary {"
        " color: var(--klaus-hm-accent);"
        " }"
        " .klaus-hm-menu {"
        " position: absolute; top: 100%; right: 0; z-index: 5;"
        " margin-top: 5px; padding: 8px;"
        " background: var(--klaus-hm-menu);"
        " border: 1px solid var(--klaus-hm-empty);"
        " border-radius: 9px;"
        " box-shadow: 0 6px 18px rgba(0,0,0,0.18);"
        " }"
        " .klaus-hm-menu-t {"
        " font-size: 9px; letter-spacing: 0.05em; text-transform: uppercase;"
        " color: var(--klaus-hm-muted); margin: 0 0 5px 2px;"
        " }"
        # A column of full-width rows, stated rather than left to
        # shrink-to-fit: a popover that lays its options out one way on
        # one engine and another way on the next is not a menu.
        " .klaus-hm-opts {"
        " display: flex; flex-direction: column; align-items: stretch;"
        " gap: 3px; margin-bottom: 9px;"
        " }"
        " .klaus-hm-opts:last-child { margin-bottom: 0; }"
        # Anki styles every <button> on this page; reset to a chip.
        " .klaus-hm-opt {"
        " appearance: none; -webkit-appearance: none;"
        f" font-family: {theme.FONT_FAMILY};"
        " font-size: 11px; line-height: 1; white-space: nowrap;"
        " margin: 0; padding: 5px 9px; border-radius: 6px; cursor: pointer;"
        " text-align: left;"
        " border: 1px solid transparent;"
        " background: var(--klaus-hm-empty);"
        " color: var(--klaus-hm-text);"
        " }"
        " .klaus-hm-opt:hover { border-color: var(--klaus-hm-accent); }"
        " .klaus-hm-opt.on {"
        " background: var(--klaus-hm-l2);"
        " border-color: var(--klaus-hm-accent); font-weight: 600;"
        " }"
        " .klaus-hm-c.hit { cursor: pointer; }"
        " .klaus-hm-c.hit:hover {"
        " outline: 1px solid var(--klaus-hm-accent); outline-offset: 1px;"
        " }"
        # No visible scrollbar (Pouya, 2026-08-31: "remove the little
        # thing at the bottom"). The box still SCROLLS — trackpad and
        # shift-wheel work, overflow-x stays auto — it just does not
        # spend a row of the panel drawing a bar under the grid.
        " .klaus-hm-scroll { scrollbar-width: none; }"
        " .klaus-hm-scroll::-webkit-scrollbar { display: none; }"
        + theme.web_control_css(".klaus-hm-opt", "var(--klaus-hm-accent)")
        + theme.web_control_css(".klaus-hm-gear", "var(--klaus-hm-accent)")
    )


# ─────────────────────────────────────────────────────────────────────
# aqt glue — everything below here talks to Anki
# ─────────────────────────────────────────────────────────────────────

# A private klausday: token used to live here, on the reasoning that
# `rated:` "is capped, so it cannot address the far end of a year of
# history". That was wrong twice over: rated:365 reaches back 364 days,
# which is the whole drawn window, and the token's resolver assigned a
# SearchContext field that does not exist, so it matched nothing at all.
# day_query() builds native searches instead — see its docstring.

# revlog rows with ease 0 are not reviews — they are manual entries:
# "set due date", "forget", and the bulk reschedules FSRS and add-ons
# perform. Counting them is not a rounding error but a wrecking ball.
# On Pouya's own collection they are 155,254 of 189,956 rows, landing as
# four ~35,000-entry spikes on days he did not study at all; unfiltered,
# those days alone would set the colour ramp and flatten every real
# study day to the same faint step. Filtering on ease rather than type
# also survives Anki adding new manual `type` codes, which it has.
_REAL_REVIEWS = "ease > 0"


def _config() -> dict:
    """Stored config, or the unsaved Preferences preview when one is
    armed — the same seam top_bar reads the background through, so
    flipping the heatmap switch shows up before Save like every other
    setting on the Appearance page."""
    from . import settings

    stored = settings.read()
    return background.effective_cfg(stored)


def _rollover_hours(col: Any) -> int:
    """Anki's daily cut-off, in hours past local midnight.

    Read off the scheduler's own next cut-off rather than the config
    key, so a profile that never wrote ``rollover`` still buckets days
    exactly the way Anki counts them.
    """
    try:
        hour = datetime.datetime.fromtimestamp(int(col.sched.day_cutoff)).hour
        if 0 <= hour <= 23:
            return hour
    except Exception:
        pass
    try:
        value = int(col.get_config("rollover", 4))
        return value if 0 <= value <= 23 else 4
    except Exception:
        return 4


def _day_expr(column: str, offset: int) -> str:
    """SQL mapping a millisecond timestamp *column* to a day number.

    ``'localtime'`` is what makes this correct rather than merely close:
    bucketing on fixed 86400-second boundaries drifts by an hour at
    every DST change and starts assigning late-evening reviews to the
    next day. Letting SQLite do the calendar keeps our days identical to
    the ones Anki itself counts. *offset* is always an int computed
    here, never user text.
    """
    return (
        f"CAST(STRFTIME('%s', {column} / 1000 - {int(offset)}, 'unixepoch',"
        " 'localtime', 'start of day') AS int)"
    )


def _today(col: Any) -> int:
    """Today's day number, from the same clock the buckets use."""
    offset = _rollover_hours(col) * 3600
    epoch = col.db.scalar(
        "SELECT CAST(STRFTIME('%s', 'now', "
        f"'-{int(offset)} seconds', 'localtime', 'start of day') AS int)"
    )
    return int(epoch) // SECS_PER_DAY


def _collect(col: Any, forecast_days: int) -> tuple:
    """``(history, forecast, today)`` straight out of the collection.

    History is deliberately unbounded — the drawn window is a display
    choice, but the streak and "share of days studied" figures are only
    honest over everything. It costs one grouped scan of revlog (~18ms
    over 190k rows here), which is cheaper than being wrong.
    """
    offset = _rollover_hours(col) * 3600
    history = [
        (int(day) // SECS_PER_DAY, int(count))
        for day, count in col.db.all(
            f"SELECT {_day_expr('id', offset)} AS day, COUNT()"
            f" FROM revlog WHERE {_REAL_REVIEWS}"
            " GROUP BY day ORDER BY day"
        )
    ]

    today = _today(col)
    forecast: dict = {}
    try:
        # Queues 2 (review) and 3 (day learn) both carry `due` as a day
        # number relative to collection creation, which is what makes
        # them addable to today. Queue 1 stores an epoch instead, and
        # suspended/buried cards are not scheduled at all.
        scheduled_today = int(col.sched.today)
        for due, count in col.db.all(
            "SELECT due, COUNT() FROM cards WHERE queue IN (2, 3)"
            " AND due >= ? AND due <= ? GROUP BY due",
            scheduled_today,
            scheduled_today + max(0, int(forecast_days)),
        ):
            forecast[today + (int(due) - scheduled_today)] = int(count)
    except Exception as exc:
        # A missing forecast is a smaller loss than no heatmap at all.
        print(f"[klausmate] heatmap forecast unavailable: {exc}")

    return history, forecast, today


def render_for_collection(col: Any, cfg: Any = None) -> str:
    """The heatmap panel's HTML for *col*, or "" when switched off."""
    cfg = cfg if isinstance(cfg, dict) else _config()
    if not enabled(cfg):
        return ""
    ahead = forecast_window(cfg)
    history, forecast, today = _collect(col, ahead)
    # Stats stay computed over the FULL history whatever window is
    # drawn: a streak is a fact about the collection, not about how
    # much of it happens to be on screen.
    return heatmap_html(
        dict(history),
        forecast,
        today,
        stats_from_history(history, today),
        history_days=history_window(cfg),
        forecast_days=ahead,
    )


def _on_deck_browser_content(deck_browser: Any, content: Any) -> None:
    """Append the heatmap under the deck table.

    ``content.stats`` is the block Anki renders after the deck table
    inside its ``<center>`` — the same block holding the studied-today
    line that background.panel_js lifts INTO the table, so the heatmap
    is left as the panel below it rather than fighting for that row.
    """
    try:
        from aqt import mw

        # Deck-screen widgets belong to the KlausBook design layer: with
        # it off, Anki's deck screen is left exactly as Anki draws it.
        #
        # Gated HERE and not inside enabled(), for the same reason the
        # background gate is not inside resolve(): Preferences seeds
        # heatmap_cb from enabled(stored config) and save_general writes
        # that state back, so folding the design gate into enabled()
        # would uncheck the switch and quietly persist heatmap_enabled
        # False — losing a preference the user never touched.
        if not background.design_enabled(_config()):
            return
        col = getattr(mw, "col", None)
        if col is None:
            return
        html = render_for_collection(col)
        if html:
            content.stats += html
    except Exception as exc:
        print(f"[klausmate] heatmap render failed: {exc}")


def _on_webview_will_set_content(web_content: Any, context: Any) -> None:
    try:
        from aqt.deckbrowser import DeckBrowser

        if not isinstance(context, DeckBrowser):
            return
        cfg = _config()
        if not background.design_enabled(cfg) or not enabled(cfg):
            return
        web_content.head += "<style>" + heatmap_css() + "</style>"
    except Exception as exc:
        print(f"[klausmate] heatmap css failed: {exc}")


def day_query(day: int, today: int) -> str:
    """Anki's OWN search for the cards on day number *day*.

    Ahead of today, that is ``prop:due=N``. Behind it, a bounded pair of
    ``rated:`` terms: ``rated:n`` means "answered in the last n days", so
    subtracting the shorter window leaves exactly one day. Both are
    native operators — the query that lands in the search bar is one the
    user can read, edit, widen, or combine with a deck.

    This replaces a private ``klausday:<n>`` token (2026-08-31, Pouya:
    "that doesn't show me anything"), which was opaque AND broken: it
    was resolved by assigning ``search_context.card_ids``, and Anki's
    SearchContext has no such field — the real one is ``ids`` — so the
    assignment did nothing and Anki went on to parse the token as a
    field search, matching no cards at all.

    ``rated:`` counts revlog rows with ``ease > 0``, the same filter the
    grid itself uses (verified in the backend's SQL), so the Browse
    result agrees with the number in the tooltip. Anki caps ``rated:``
    at 365 days, which is why RANGE_CHOICES tops out there.
    """
    delta = today - int(day)
    if delta < 0:
        return f"prop:due={-delta}"
    if delta == 0:
        return "rated:1"
    return f"rated:{delta + 1} -rated:{delta}"


def _open_day(day: int) -> None:
    """Show a day's cards in Browse: what was answered, or what is due."""
    try:
        import aqt
        from aqt import mw

        col = getattr(mw, "col", None)
        if col is None:
            return
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(day_query(day, _today(col)))
    except Exception as exc:
        print(f"[klausmate] heatmap browse failed: {exc}")


def _refresh() -> None:
    """Redraw the deck browser — only while the user is still ON it.
    This runs deferred; by then they may have moved to the overview or
    the reviewer, and yanking those back through a deck-browser repaint
    would be wrong. (dashboard._refresh's rule, for the same screen.)"""
    try:
        from aqt import mw

        if getattr(mw, "state", "") == "deckBrowser":
            mw.deckBrowser.refresh()
    except Exception as exc:
        print(f"[klausmate] heatmap refresh failed: {exc}")


def _write_cfg(updates: dict) -> None:
    """Write settings through dashboard's writer.

    The deck screen's OTHER widget editor already owns the rule that an
    armed appearance preview must be patched alongside stored config —
    a preview dict REPLACES config for every effective_cfg reader, so a
    key only written to storage would be reverted on the next tick.
    One implementation of that rule, not two.
    """
    try:
        from . import dashboard

        dashboard.write_cfg(updates)
    except Exception as exc:
        print(f"[klausmate] heatmap config write failed: {exc}")


def _apply_setting(payload: str) -> tuple:
    """One choice from the corner menu.

    Validated HERE, never in the page: the webview may post anything, so
    only a known key carrying a value from that key's own menu is ever
    written. Anything else is swallowed, leaving config untouched.
    """
    updates: dict = {}
    key, _, raw = payload.partition(":")
    try:
        if key == "history" and int(raw) in RANGE_CHOICES:
            updates = {"heatmap_history_days": int(raw)}
        elif key == "forecast" and raw in ("0", "1"):
            updates = {"heatmap_forecast": raw == "1"}
    except Exception:
        updates = {}
    if not updates:
        return (True, None)
    _write_cfg(updates)
    try:
        from aqt.qt import QTimer

        # Deferred so the webchannel call unwinds before the deck
        # browser is rebuilt under the webview that sent it (hygiene
        # per tests/test_bridge_reentrancy).
        QTimer.singleShot(0, _refresh)
    except Exception as exc:
        print(f"[klausmate] heatmap refresh schedule failed: {exc}")
    return (True, None)


def _on_js_message(handled: tuple, message: str, context: Any) -> tuple:
    """Handle a cell click, or a choice from the corner menu."""
    if not message.startswith("klausmate:heatmap:"):
        return handled
    # Before the day parse: a settings payload also starts with the
    # heatmap prefix, and its trailing number would read as a day.
    if message.startswith(SET_PREFIX):
        return _apply_setting(message[len(SET_PREFIX):])
    try:
        day = int(message.rsplit(":", 1)[1])
    except Exception:
        return (True, None)
    try:
        from aqt.qt import QTimer

        # Deferred so the webchannel bridge call unwinds before the
        # Browser window is built (hygiene per tests/test_bridge_reentrancy).
        QTimer.singleShot(0, lambda: _open_day(day))
    except Exception as exc:
        print(f"[klausmate] heatmap click failed: {exc}")
    return (True, None)


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.deck_browser_will_render_content.append(
            _on_deck_browser_content
        )
        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
        gui_hooks.webview_did_receive_js_message.append(_on_js_message)
    except Exception as exc:
        print(f"[klausmate] heatmap setup failed: {exc}")
