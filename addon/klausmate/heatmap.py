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

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
# Row indices that get a weekday label. GitHub labels alternate rows so
# the strip reads without crowding; rows are Sunday-first (see _row).
_WEEKDAY_LABEL_ROWS = (1, 3, 5)


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

    Each column is ``{"start": <day of its Sunday>, "cells": [...]}``
    with exactly seven cells, Sunday-first. A cell is ``None`` where the
    week runs past either end of the window — the placeholder is what
    keeps every column a full seven rows tall, so the weekday a cell
    sits on is always readable off its row.

    Today belongs to history even though it also has cards due: what
    you have already done outranks what is still scheduled.
    """
    history_days = max(1, int(history_days))
    forecast_days = max(0, int(forecast_days))
    first = today - history_days + 1
    last = today + forecast_days

    columns: list = []
    start = first - _row(first)          # rewind to that week's Sunday
    while start <= last:
        cells: list = []
        for row in range(7):
            day = start + row
            if day < first or day > last:
                cells.append(None)
            elif day <= today:
                cells.append((day, int(history.get(day, 0)), False))
            else:
                cells.append((day, int(forecast.get(day, 0)), True))
        columns.append({"start": start, "cells": cells})
        start += 7
    return columns


def month_labels(columns: list) -> list:
    """One label per column: the month name where a new month starts,
    otherwise empty. The first column never gets one — its month began
    off-screen, so labelling it would point at a partial week."""
    labels: list = []
    previous = None
    for index, column in enumerate(columns):
        month = day_to_date(column["start"]).month
        labels.append(
            _MONTHS[month - 1] if index and month != previous else ""
        )
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


def _cells_html(columns: list, levels: list) -> str:
    parts: list = []
    for column in columns:
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

    months = "".join(
        f'<span class="klaus-hm-m">{label}</span>'
        for label in month_labels(columns)
    )
    weekdays = "".join(
        f'<span class="klaus-hm-w">'
        f'{_WEEKDAYS[row] if row in _WEEKDAY_LABEL_ROWS else ""}</span>'
        for row in range(7)
    )
    return (
        '<div class="klaus-hm">'
        '<div class="klaus-hm-top">'
        '<span class="klaus-hm-heading">Review activity</span>'
        f'<span class="klaus-hm-stats">{_stats_html(stats)}</span>'
        "</div>"
        # The grid is allowed to be wider than the window and scroll
        # inside its own box. It must never widen the panel: forcing a
        # width here is what pushed the deck panel off-screen before.
        '<div class="klaus-hm-scroll"><div class="klaus-hm-plot">'
        '<span class="klaus-hm-corner"></span>'
        f'<div class="klaus-hm-months">{months}</div>'
        f'<div class="klaus-hm-wd">{weekdays}</div>'
        f'<div class="klaus-hm-cells">{_cells_html(columns, levels)}</div>'
        "</div></div>"
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
    week = CELL + GAP
    return (
        f":root {{{_palette_vars(False)} }}"
        f":root.night-mode {{{_palette_vars(True)} }}"
        " .klaus-hm {"
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
        " justify-content: space-between; gap: 6px 18px;"
        " margin-bottom: 11px;"
        " }"
        " .klaus-hm-heading {"
        " font-size: 13px; font-weight: 600; letter-spacing: 0.01em;"
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
        # Two rows: month strip beside a spacer, then the weekday
        # column beside the cells. Both inner grids use the same column
        # and row sizes as the cells, so labels line up by construction
        # rather than by measurement.
        " .klaus-hm-plot {"
        " display: grid; grid-template-columns: auto auto;"
        f" gap: 4px {GAP + 3}px; width: max-content;"
        " }"
        " .klaus-hm-months {"
        f" display: grid; grid-auto-flow: column;"
        f" grid-auto-columns: {week}px; height: 11px;"
        " }"
        # Month and weekday labels are the smallest type in the app,
        # sitting on a frosted panel over an ARBITRARY user photo — so
        # they wear full text colour: muted's contrast was AA-checked
        # against bg/surface, never against a photo behind a 50% tint.
        # Only the stat labels stay muted; their bold accent numbers
        # anchor them.
        " .klaus-hm-m {"
        " font-size: 10px; color: var(--klaus-hm-text);"
        " white-space: nowrap; overflow: visible; line-height: 11px;"
        " }"
        " .klaus-hm-wd {"
        f" display: grid; grid-template-rows: repeat(7, {CELL}px);"
        f" row-gap: {GAP}px;"
        " }"
        " .klaus-hm-w {"
        " font-size: 10px; color: var(--klaus-hm-text);"
        f" line-height: {CELL}px; text-align: right; white-space: nowrap;"
        " }"
        " .klaus-hm-cells {"
        " display: grid; grid-auto-flow: column;"
        f" grid-template-rows: repeat(7, {CELL}px);"
        f" grid-auto-columns: {CELL}px; gap: {GAP}px;"
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
        " .klaus-hm-c.hit { cursor: pointer; }"
        " .klaus-hm-c.hit:hover {"
        " outline: 1px solid var(--klaus-hm-accent); outline-offset: 1px;"
        " }"
        # Anki's own webviews get a slim scrollbar; match it rather than
        # letting a chunky default cut into the panel's bottom padding.
        " .klaus-hm-scroll::-webkit-scrollbar { height: 6px; }"
        " .klaus-hm-scroll::-webkit-scrollbar-thumb {"
        " background: var(--klaus-hm-empty); border-radius: 3px;"
        " }"
    )


# ─────────────────────────────────────────────────────────────────────
# aqt glue — everything below here talks to Anki
# ─────────────────────────────────────────────────────────────────────

# Our own search token, resolved in _on_browser_will_search. Anki has no
# operator for "reviewed on this exact day": `rated:` counts backwards
# from today and is capped, so it cannot address the far end of a year
# of history. Resolving the ids ourselves is exact for any day and needs
# no guess about which cap this Anki enforces.
SEARCH_PREFIX = "klausday:"

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
    try:
        from aqt import mw

        stored = mw.addonManager.getConfig(__package__) or {}
    except Exception:
        return {}
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


def cards_reviewed_on(col: Any, day: int) -> list:
    """Card ids answered on day number *day*.

    Selected through `cards` so rows whose card has since been deleted
    drop out, and matched by re-running the very expression that built
    the bucket — inverting a local-midnight day number back into a
    timestamp range would reintroduce every timezone question
    :func:`_day_expr` exists to avoid.
    """
    offset = _rollover_hours(col) * 3600
    return col.db.list(
        "SELECT id FROM cards WHERE id IN ("
        f" SELECT cid FROM revlog WHERE {_REAL_REVIEWS}"
        f" AND {_day_expr('id', offset)} = ?)",
        int(day) * SECS_PER_DAY,
    )


def render_for_collection(col: Any, cfg: Any = None) -> str:
    """The heatmap panel's HTML for *col*, or "" when switched off."""
    cfg = cfg if isinstance(cfg, dict) else _config()
    if not enabled(cfg):
        return ""
    history, forecast, today = _collect(col, DEFAULT_FORECAST_DAYS)
    return heatmap_html(
        dict(history),
        forecast,
        today,
        stats_from_history(history, today),
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


def _open_day(day: int) -> None:
    """Show a day's cards in Browse: what was answered, or what is due."""
    try:
        import aqt
        from aqt import mw

        col = getattr(mw, "col", None)
        if col is None:
            return
        today = _today(col)
        query = (
            f"prop:due={day - today}" if day > today
            else f"{SEARCH_PREFIX}{day}"
        )
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(query)
    except Exception as exc:
        print(f"[klausmate] heatmap browse failed: {exc}")


def _on_js_message(handled: tuple, message: str, context: Any) -> tuple:
    """Handle a cell click from the deck browser webview."""
    if not message.startswith("klausmate:heatmap:"):
        return handled
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


def _on_browser_will_search(search_context: Any) -> None:
    """Resolve our own ``klausday:`` token into card ids.

    Setting ``card_ids`` replaces the whole query, so this token does
    not combine with other search terms — acceptable because the deck
    browser's heatmap is collection-wide and the token is only ever
    produced by a cell click.
    """
    try:
        search = getattr(search_context, "search", "") or ""
        if not search.startswith(SEARCH_PREFIX):
            return
        day = int(search[len(SEARCH_PREFIX):])
    except Exception:
        return
    try:
        from aqt import mw

        search_context.card_ids = cards_reviewed_on(mw.col, day)
    except Exception as exc:
        print(f"[klausmate] heatmap search failed: {exc}")


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.deck_browser_will_render_content.append(
            _on_deck_browser_content
        )
        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
        gui_hooks.webview_did_receive_js_message.append(_on_js_message)
        gui_hooks.browser_will_search.append(_on_browser_will_search)
    except Exception as exc:
        print(f"[klausmate] heatmap setup failed: {exc}")
