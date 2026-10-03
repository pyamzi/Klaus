"""Headless tests for klaus_note.heatmap — the review heatmap.

Three kinds of check live here:

* pure logic (streaks, the colour ramp, the week grid) against
  hand-built inputs;
* the SQL glue against a fake collection, so the queries' SHAPE is
  pinned without touching Anki;
* and a read-only pass over the REAL collection, which is the only
  place the ease>0 filter can be shown to matter rather than asserted
  to. It skips loudly when the collection is not there.
"""
import datetime
import importlib
import os
import re
import sqlite3
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
heatmap = importlib.import_module("klaus_note.heatmap")
theme = importlib.import_module("klaus_note.theme")
background = importlib.import_module("klaus_note.background")

DAY = heatmap.SECS_PER_DAY


# ---------------------------------------------------------------- days
section("day numbers")

check("day 0 is 1970-01-01", heatmap.day_to_date(0) == datetime.date(1970, 1, 1))
check("consecutive day numbers are consecutive dates",
      heatmap.day_to_date(20000) + datetime.timedelta(days=1)
      == heatmap.day_to_date(20001))
# 1970-01-01 was a Thursday; rows run Sunday-first, so Thursday is row 4.
check("rows are Sunday-first, so the grid matches every other calendar",
      heatmap._row(0) == 4
      and [heatmap._row(d) for d in range(3, 10)] == [0, 1, 2, 3, 4, 5, 6])

section("the on/off switch")
check("on by default", heatmap.enabled({}) is True)
check("off when switched off", heatmap.enabled({"heatmap_enabled": False}) is False)
check("a corrupt value reads as ON — a bad config entry should not "
      "silently make a feature vanish",
      heatmap.enabled({"heatmap_enabled": "no"}) is True)
check("a non-dict config is survivable", heatmap.enabled(None) is True)


# --------------------------------------------------------------- stats
section("streaks and averages")

check("no history is all zeroes, not a crash",
      heatmap.stats_from_history([], 100)
      == {"streak_cur": 0, "streak_max": 0, "days_learned": 0,
          "total": 0, "daily_avg": 0, "pct_days_active": 0})

# Days 90,91,92 then a gap, then 98,99,100 (=today).
_hist = [(90, 10), (91, 10), (92, 10), (98, 4), (99, 4), (100, 4)]
_stats = heatmap.stats_from_history(_hist, 100)
check("the longest run is found across gaps", _stats["streak_max"] == 3)
check("a run reaching today is the current streak", _stats["streak_cur"] == 3)
check("a run reaching only YESTERDAY still counts — today's studying "
      "may just not have happened yet",
      heatmap.stats_from_history(_hist, 101)["streak_cur"] == 3)
check("a run that stopped before yesterday does not",
      heatmap.stats_from_history(_hist, 102)["streak_cur"] == 0)
check("...but the longest streak survives that",
      heatmap.stats_from_history(_hist, 102)["streak_max"] == 3)
check("the daily average is over days STUDIED, not days elapsed "
      "(42 cards over 6 study days = 7, not 42/11)",
      _stats["total"] == 42 and _stats["daily_avg"] == 7)
check("percentage active is measured from the FIRST review, not from "
      "the window (6 of the 11 days since day 90 = 55%)",
      _stats["pct_days_active"] == 55)
check("one day of history is 100% of the days there were",
      heatmap.stats_from_history([(100, 3)], 100)["pct_days_active"] == 100)
check("a single day is a streak of one",
      heatmap.stats_from_history([(100, 3)], 100)["streak_cur"] == 1)


# ---------------------------------------------------------------- ramp
section("the colour ramp")

# The factors are Glutanimate's (renderer._dynamic_legend_factors), and
# so is the floor: below ~20/day the steps stop separating anything.
_N = len(heatmap.RAMP_FACTORS)
check("the ramp uses the reference addon's nine factors",
      heatmap.RAMP_FACTORS
      == (0.125, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0))
for _avg in (0, 1, 2, 3, 7, 40, 800):
    _levels = heatmap.ramp_levels(_avg)
    if len(_levels) != _N or any(
        _levels[i] >= _levels[i + 1] for i in range(_N - 1)
    ):
        check(f"ramp for avg={_avg} is {_N} ascending steps", False,
              str(_levels))
        break
else:
    check(f"every average yields {_N} STRICTLY ascending steps — a tiny "
          "average must not collapse the ramp to one usable colour", True)

check("a low average is floored at the reference's 20, so the steps "
      "still separate something",
      heatmap.ramp_levels(3) == heatmap.ramp_levels(20)
      and heatmap.RAMP_MIN_BASE == 20)
check("above the floor the ramp scales with the user",
      heatmap.ramp_levels(40) != heatmap.ramp_levels(800))
check("a full day sits MID-ramp now, not at the top — that is the whole "
      "point of the reference's factors: days above the average stay "
      "distinguishable instead of flattening into one colour",
      heatmap.ramp_levels(40)[heatmap.RAMP_FACTORS.index(1.0)] == 40
      and heatmap.ramp_levels(40)[-1] == 160)

# Alphas. Nine steps spread LINEARLY put an average day at 0.56 and
# washed the whole grid out — visible immediately against the live
# collection, invisible to every pin above. The reference can spread its
# nine steps evenly because they are nine distinct HUES; ours are one
# accent at rising alpha over a dark panel, so the curve has to
# front-load.
_A = heatmap.ramp_alphas(0.15, 1.0)
check("one alpha per ramp step", len(_A) == _N)
check("alphas rise all the way to full accent",
      _A == tuple(sorted(_A)) and _A[-1] == 1.0 and _A[0] >= 0.1)
_avg_step = heatmap.RAMP_FACTORS.index(1.0)
check("an average day still reads as SOLID ink, not a wash — this is "
      "the whole reason the curve is not linear",
      _A[_avg_step] >= 0.6)
check("...and it is genuinely front-loaded, not linear in disguise",
      _A[_avg_step] > 0.15 + (1.0 - 0.15) * _avg_step / (_N - 1) + 0.05)
check("there is still headroom above an average day, so a 2x or 4x day "
      "is distinguishable from it",
      len([a for a in _A if a > _A[_avg_step]]) >= 3)

_levels = heatmap.ramp_levels(40)
check("nothing studied is step 0", heatmap.level_for(0, _levels) == 0)
check("a negative count cannot colour a cell",
      heatmap.level_for(-5, _levels) == 0)
check("one card is already step 1", heatmap.level_for(1, _levels) == 1)
check("a threshold belongs to its own step",
      [heatmap.level_for(v, _levels) for v in _levels]
      == list(range(1, _N + 1)))
check("a monster day tops out rather than overflowing",
      heatmap.level_for(10 ** 6, _levels) == _N)
check("an average day and a 4x day no longer draw the SAME ink "
      "(the bug the reference's factors fix)",
      heatmap.level_for(40, _levels) != heatmap.level_for(160, _levels))


# ---------------------------------------------------------------- grid
section("the week grid")

_today = 20000
_cols = heatmap.build_columns({19999: 3}, {20001: 5}, _today,
                              history_days=30, forecast_days=7)
check("every column is a full week", all(len(c["cells"]) == 7 for c in _cols))
check("columns start on a Sunday, so a cell's row IS its weekday",
      all(heatmap._row(c["start"]) == 0 for c in _cols))
_flat = [cell for c in _cols for cell in c["cells"]]
_real = [cell for cell in _flat if cell is not None]
check("the window covers exactly history_days + forecast_days",
      len(_real) == 30 + 7)
check("days outside the window are placeholders, so the grid keeps "
      "its seven rows instead of ragging at the ends",
      any(cell is None for cell in _flat))
_by_day = {cell[0]: cell for cell in _real}
check("a past day reads its count from history", _by_day[19999][1] == 3)
check("a past day is not marked future", _by_day[19999][2] is False)
check("a future day reads its count from the forecast",
      _by_day[20001][1] == 5 and _by_day[20001][2] is True)
check("a day with no activity is present but empty",
      _by_day[19998] == (19998, 0, False))
check("the window ends at today + forecast_days",
      max(_by_day) == _today + 7 and min(_by_day) == _today - 29)

_both = heatmap.build_columns({20000: 11}, {20000: 99}, _today,
                              history_days=5, forecast_days=5)
_today_cell = [c for col in _both for c in col["cells"]
               if c and c[0] == _today][0]
check("today is what you DID, not what is still scheduled — history "
      "wins even though today also has cards due",
      _today_cell == (_today, 11, False))

check("forecast_days=0 stops the grid at today",
      max(c[0] for col in heatmap.build_columns({}, {}, _today, 10, 0)
          for c in col["cells"] if c) == _today)

_labels = heatmap.month_labels(_cols)
check("one label slot per column", len(_labels) == len(_cols))
_year = heatmap.month_labels(
    heatmap.build_columns({}, {}, _today, 365, 28))
check("a year of columns names about twelve months",
      11 <= len([m for m in _year if m]) <= 14,
      str([m for m in _year if m]))
check("month names are the real ones, in order",
      all(m in heatmap._MONTHS for m in _year if m))


# K-141 (Pouya, 2026-09-01): "I just want the days to align with the
# months perfectly, like the day that fits August is under August, and
# if it's in September, it's under September." Columns are grouped by
# month now, so this is exact rather than a best effort — a week that
# straddles a boundary is SPLIT between the two runs. The cost he
# explicitly accepted ("You don't have to have perfect squares") is
# partial columns at each end of a month.
def _label_month_at(labels, index):
    """The month whose label governs column *index*."""
    for j in range(index, -1, -1):
        if labels[j]:
            return heatmap._MONTHS.index(labels[j]) + 1
    return None


def _misfiled(columns):
    """Every (date, governing label) pair that disagrees."""
    labels = heatmap.month_labels(columns)
    bad = []
    for index, column in enumerate(columns):
        governing = _label_month_at(labels, index)
        for cell in column["cells"]:
            if cell is None:
                continue
            if heatmap.day_to_date(cell[0]).month != governing:
                bad.append((heatmap.day_to_date(cell[0]), governing))
    return bad


_wins = [heatmap.build_columns({}, {}, _today + off, 365, 28)
         for off in range(0, 371, 37)]
check("EVERY day sits under its own month's label — not most of them, "
      "all of them; a week spanning a boundary is split between the "
      "two month runs instead of being assigned to one",
      all(not _misfiled(w) for w in _wins),
      "; ".join(f"{d} under {m}" for w in _wins for d, m in _misfiled(w)[:3]))
check("...and no day is lost or duplicated in the splitting — the "
      "window still holds exactly history + forecast days",
      all(len({c[0] for col in w for c in col["cells"] if c}) == 365 + 28
          for w in _wins))
check("a month's first column is where its label goes, including the "
      "very first — its days really are that month's days",
      heatmap.month_labels(
          heatmap.build_columns({}, {}, 20000, 365, 28))[0] != "")
check("every column belongs to exactly one month, so labelling can "
      "no longer be a guess",
      all("month" in col for w in _wins for col in w))

check("...including the months that begin ON a Sunday, which the old "
      "week-start rule got right by luck",
      not _misfiled(heatmap.build_columns({}, {}, _today, 365, 28)))


# ------------------------------------------------------------- markup
section("markup")

_stats = heatmap.stats_from_history(_hist, 100)
check("nothing to show renders nothing at all, rather than an empty grid",
      heatmap.heatmap_html({}, {}, 100, _stats) == "")

_html = heatmap.heatmap_html({99: 40, 98: 0}, {101: 6}, 100, _stats,
                             history_days=14, forecast_days=7)
check("the panel wears the .klaus-hm hook background.panel_css frosts",
      '<div class="klaus-hm">' in _html)
check("a day with reviews is clickable", "klaus_note:heatmap:99" in _html)
check("a day with NOTHING on it is not — an empty Browse reads as a "
      "broken link", "klaus_note:heatmap:98" not in _html)
check("a scheduled day is clickable too", "klaus_note:heatmap:101" in _html)
check("future cells are drawn from the future ramp",
      "f1" in _html or "f2" in _html or "f3" in _html or "f4" in _html)
check("tooltips use the reference's phrasing — cards reviewed / cards "
      "due / no reviews, joined with 'on'",
      "40 cards reviewed on" in _html and "6 cards due on" in _html
      and "No reviews on" in _html)
check("one card is not '1 cards'",
      "1 card reviewed on"
      in heatmap.heatmap_html({100: 1}, {}, 100, _stats, 5, 0))
check("an empty FUTURE day says nothing is due, not that nothing was "
      "reviewed — the reference splits those two",
      "No cards due on"
      in heatmap.heatmap_html({}, {101: 6}, 100, _stats, 5, 7))
check("the stats row carries the reference addon's four labels, in its "
      "order (daily average, days learned, longest, current)",
      [m for m in re.findall(
          r"Daily average|Days learned|Longest streak|Current streak",
          _html)]
      == ["Daily average", "Days learned", "Longest streak",
          "Current streak"])
check("labels lead, values follow — the reference's layout",
      re.search(r"Daily average:</span>\s*<b[^>]*>", _html) is not None)
check("each stat carries the reference's own explanatory tooltip",
      "Average reviews on active days" in _html
      and "Percentage of days with review activity" in _html
      and "All types of repetitions included." in _html)
_cells = heatmap.build_columns({99: 40}, {101: 6}, 100, 14, 7)
# Anchored so `klaus-hm-cells` and `klaus-hm-corner` cannot be counted
# as cells: the class must end right after the `c`.
_cell_tags = len(re.findall(r'class="klaus-hm-c[ "]', _html))
check("exactly one cell element per grid slot and NOTHING else — the "
      "reference ships displayLegend:false, so there are no legend "
      "swatches left to count",
      _cell_tags == sum(len(c["cells"]) for c in _cells),
      f"{_cell_tags} tags")
# NB: the 14-day window above happens to start on a Sunday and end on a
# Saturday, so it has no ragged ends at all. Ask for one that does.
_ragged = heatmap.heatmap_html({99: 40}, {}, 100, _stats,
                               history_days=10, forecast_days=3)
check("out-of-window slots render as padding, so a window that does "
      "not begin on a Sunday still keeps its seven rows",
      "klaus-hm-c pad" in _ragged)
check("the left rail names EVERY row, as initials — S M T W T F S "
      "(Pouya, 2026-08-31), not GitHub's alternating three-letter names",
      re.findall(r'<span class="klaus-hm-w">(.*?)</span>', _html)
      == ["S", "M", "T", "W", "T", "F", "S"])
check("the rail's letters are derived from the tooltip's day names, so "
      "the two can never name different days",
      heatmap._WEEKDAY_INITIALS
      == tuple(name[0] for name in heatmap._WEEKDAYS))
check("no heading survives above the grid — the grid says what it is",
      "Review activity" not in _html
      and "klaus-hm-heading" not in _html
      and "klaus-hm-heading" not in heatmap.heatmap_css())

# ---- months are given air --------------------------------------- K-121
_year_html = heatmap.heatmap_html({99: 40}, {}, 100, _stats,
                                  history_days=365, forecast_days=28)
_year_cols = heatmap.build_columns({99: 40}, {}, 100, 365, 28)
_year_starts = [bool(m) for m in heatmap.month_labels(_year_cols)]
check("a month's first column opens a gap",
      _year_html.count('class="klaus-hm-col ms"') == sum(_year_starts))
check("...and the LABEL above it moves by the same rule, from the same "
      "list — a gap the month name did not follow would be worse than "
      "no gap at all",
      _year_html.count('class="klaus-hm-m ms"') == sum(_year_starts))
check("one stylesheet rule carries both, so they cannot drift apart",
      ".klaus-hm-col.ms, .klaus-hm-m.ms {" in heatmap.heatmap_css())
check("the gap is real air, not a whole extra column",
      0 < heatmap.MONTH_GAP < heatmap.CELL)

# ---- the corner menu --------------------------------------------- K-121
check("the panel carries a settings control in its corner",
      '<details class="klaus-hm-gear">' in _html)
check("...that needs no script of ours in Anki's deck-browser document",
      "<script" not in _html)
check("Range offers exactly the menu's own choices",
      all(f"{heatmap.SET_PREFIX}history:{days}" in _html
          for days in heatmap.RANGE_CHOICES)
      and len(heatmap.RANGE_CHOICES) == len(heatmap.RANGE_LABELS))
check("Upcoming can be turned on and off",
      f"{heatmap.SET_PREFIX}forecast:1" in _html
      and f"{heatmap.SET_PREFIX}forecast:0" in _html)
_menu = heatmap.heatmap_html({99: 40}, {}, 100, _stats,
                             history_days=182, forecast_days=0)
check("the live values are the ones shown as selected",
      "klaus-hm-opt on\" onclick=\"pycmd('%shistory:182')"
      % heatmap.SET_PREFIX in _menu
      and "klaus-hm-opt on\" onclick=\"pycmd('%sforecast:0')"
      % heatmap.SET_PREFIX in _menu)
check("exactly one Range choice and one Upcoming choice read as current",
      _menu.count('klaus-hm-opt on"') == 2)

# The legend is GONE. Glutanimate's addon ships displayLegend:false —
# it shows the grid and the stats row and nothing else — and matching it
# was Pouya's call (2026-08-31), knowingly retiring the personal
# "0 → a full day (N)" line the 2026-08-27 audit had built.
check("no legend element survives",
      'class="klaus-hm-legend"' not in _html)
check("...nor its wording, in either dialect",
      "a full day" not in _html
      and "Less" not in _html and "More" not in _html)
check("_legend_titles is gone with it, not left as dead code",
      not hasattr(heatmap, "_legend_titles"))


# ----------------------------------------------------------------- css
section("stylesheet")

_css = heatmap.heatmap_css()
check("the bar under the grid is gone in BOTH engines (Pouya, "
      "2026-08-31) while the box still scrolls — hidden, not disabled: "
      "trackpad and shift-wheel still reach a year that overflows",
      "scrollbar-width: none" in _css
      and "::-webkit-scrollbar { display: none; }" in _css
      and "overflow-x: auto" in _css
      and "scrollbar { height" not in _css)
check("a range wider than its box opens on the NEWEST weeks (the scroller runs "
      "opposite to the plot, so it starts at the plot's end), mirrored for RTL pages",
      " .klaus-hm-scroll { direction: rtl; }" in _css
      and " .klaus-hm-scroll > .klaus-hm-plot { direction: ltr; }" in _css
      and " [dir=rtl] .klaus-hm-scroll { direction: ltr; }" in _css
      and " [dir=rtl] .klaus-hm-scroll > .klaus-hm-plot { direction: rtl; }" in _css)
check("the weekday letters are pinned: their column sits BESIDE the scroller, not in it, "
      "and drops by the month strip plus the row gap so the letters meet their rows",
      re.search(r'<div class="klaus-hm-body"><div class="klaus-hm-wd">.*?</div>'
                r'<div class="klaus-hm-scroll"><div class="klaus-hm-plot">'
                r'<div class="klaus-hm-months">', _html) is not None
      and "klaus-hm-corner" not in _html
      and "padding-top: 15px; flex: none;" in _css.split(" .klaus-hm-wd {")[1].split("}")[0]
      and " .klaus-hm-body > .klaus-hm-scroll { flex: 0 1 auto; min-width: 0; }" in _css)
_late = heatmap.heatmap_html({99: 40}, {100 + d: 3 for d in range(1, 12)}, 100, _stats,
                             history_days=40, forecast_days=11)
_late_cols = heatmap.build_columns({99: 40}, {100 + d: 3 for d in range(1, 12)}, 100, 40, 11)
_late_labels = heatmap.month_labels(_late_cols)
_shown = re.findall(r'<span class="klaus-hm-m(?: ms)?">([^<]*)</span>', _late)
_n = len(_late_labels)
check("a month starting in the last column keeps its gap but not its name (it was cut "
      "to 'No' by the plot's edge); every other month keeps its name",
      _shown == [l if _n - i >= 2 else "" for i, l in enumerate(_late_labels)]
      and _late.count('klaus-hm-m ms') == sum(1 for l in _late_labels if l),
      f"{_shown} vs {_late_labels}")
# A forecast whose very last column opens a new month — the case that drew "No".
for _fd in range(1, 60):
    _cols = heatmap.build_columns({99: 40}, {}, 100, 40, _fd)
    if heatmap.month_labels(_cols)[-1]:
        break
_edge = heatmap.heatmap_html({99: 40}, {100 + _fd: 1}, 100, _stats, history_days=40, forecast_days=_fd)
_edge_shown = re.findall(r'<span class="klaus-hm-m(?: ms)?">([^<]*)</span>', _edge)
check("…pinned on a range whose LAST column opens a month: that name is dropped",
      heatmap.month_labels(_cols)[-1] != "" and _edge_shown[-1] == ""
      and _edge.rstrip().count("klaus-hm-m ms") == sum(1 for l in heatmap.month_labels(_cols) if l),
      str(_fd))
check("both palettes ship, keyed on Anki's own night-mode class — Anki "
      "flips that class with JS and never re-runs the hook that "
      "injected this, so baking one palette would freeze the heatmap "
      "on whichever theme was live at draw time",
      ":root {" in _css and ":root.night-mode {" in _css)
# K-142 (found by scripts/mutation_audit.py, confirmed by hand): the
# check above only proves the two SELECTORS exist. Swapping the palette
# blocks — light mode painting the DARK palette — left the whole suite
# green, and so did making night identical to day. The invariant is
# that each block carries ITS OWN palette, so pin the values.
_day_blk = re.search(r":root \{(.*?)\}", _css, re.S)
_night_blk = re.search(r":root\.night-mode \{(.*?)\}", _css, re.S)
check("the two palette blocks are not identical — a night mode that "
      "merely repeats day mode is the bug this pin exists to prevent",
      _day_blk is not None and _night_blk is not None
      and _day_blk.group(1) != _night_blk.group(1))
check("...and each block carries its OWN palette's ink, so the two "
      "cannot be swapped and still pass",
      theme.palette(False)["text"].lower() in _day_blk.group(1).lower()
      and theme.palette(True)["text"].lower() in _night_blk.group(1).lower()
      and theme.palette(True)["text"].lower()
      not in _day_blk.group(1).lower())
check("heatmap_css takes no `night` argument, for that same reason",
      heatmap.heatmap_css.__code__.co_argcount == 0)

_ocean = heatmap.heatmap_css()
theme.set_active_theme("claude")
_claude = heatmap.heatmap_css()
theme.set_active_theme("ocean")
check("the cells re-colour with the accent theme — the whole point of "
      "deriving the ramp from the palette instead of picking colours",
      _ocean != _claude and heatmap.heatmap_css() == _ocean)
theme.set_custom_colour("#8A2BE2")
theme.set_active_theme(theme.CUSTOM_THEME)
check("...a CUSTOM accent colour included",
      heatmap.heatmap_css() not in (_ocean, _claude))
theme.set_active_theme("ocean")

check("the panel's own surface is spelled in ANKI's tokens, so it "
      "looks native in theme mode where Klaus paints no background",
      "var(--canvas-glass" in _css and "var(--border-subtle" in _css)
check("the grid scrolls INSIDE its box on a narrow window",
      "overflow-x: auto" in _css)
check("and never FORCES a width — that is what pushed the deck panel "
      "off-screen before. `max-width: 100%` caps and is welcome; a "
      "bare `width: 100%` or a `min-width` is not",
      not re.search(r"(?<!max-)width: 100%", _css)
      # A POSITIVE minimum is the hazard; `min-width: 0` is its
      # opposite — it removes the automatic minimum flex would
      # otherwise impose (see .klaus-hm-m).
      and set(re.findall(r"min-width:\s*([^;]+);", _css)) <= {"0"}
      and "max-width: 100%" in _css)
check("weekday labels ride the same row pitch",
      _css.count(f"repeat(7, {heatmap.CELL}px)") == 2)
check("all four done-steps and all four due-steps are defined",
      all(f"--klaus-hm-l{i}:" in _css for i in range(1, 5))
      and all(f"--klaus-hm-f{i}:" in _css for i in range(1, 5)))
check("scheduled days are hollow, not just paler — 'done' and 'to "
      "come' must not read as the same weight of ink",
      "inset 0 0 0 1px var(--klaus-hm-ring)" in _css)


def _rule(selector):
    """The declaration block of *selector*'s own rule in _css."""
    _m = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", _css)
    return _m.group(1) if _m else ""


check("month labels ride the same column pitch as the cells, so they "
      "line up by construction rather than by measurement: both strips "
      "are flex rows of CELL-wide items sharing the cells' own gap",
      _css.count(f"display: flex; gap: {heatmap.GAP}px") == 2
      and f"flex: 0 0 {heatmap.CELL}px" in _rule(".klaus-hm-m"))
check("the month strip's boxes cannot be inflated by their own text — "
      "a flex item's automatic minimum is its min-content size, and a "
      "nowrap month name would floor each LABELLED box above the cell "
      "pitch and walk every later label off its column",
      "min-width: 0" in _rule(".klaus-hm-m"))
check("the corner menu is opaque and PALETTE-owned, in both palettes "
      "— borrowing Anki's --canvas-overlay would land a white popover "
      "on a dark deck screen wherever that token is not defined",
      _css.count("--klaus-hm-menu:") == 2
      and "background: var(--klaus-hm-menu)" in _rule(".klaus-hm-menu")
      and "rgba" not in _rule(".klaus-hm-menu").split("box-shadow")[0])

check("month and weekday labels wear FULL text colour at their 10px — "
      "muted's contrast was AA-checked against bg/surface, never "
      "against an arbitrary photo behind a 50% tint, and these are the "
      "smallest words in the app on exactly that glass",
      "color: var(--klaus-hm-text)" in _rule(".klaus-hm-m")
      and "color: var(--klaus-hm-text)" in _rule(".klaus-hm-w")
      and "font-size: 10px" in _rule(".klaus-hm-m")
      and "--klaus-hm-muted" not in _rule(".klaus-hm-m")
      and "--klaus-hm-muted" not in _rule(".klaus-hm-w"))
check("no legend rule is left in the sheet either",
      ".klaus-hm-legend" not in _css)
check("the stat labels alone STAY muted — their bold accent numbers "
      "anchor them — so the muted token must stay defined",
      "color: var(--klaus-hm-muted)" in _rule(".klaus-hm-stat")
      and "--klaus-hm-muted:" in _css)

section("the panel family")
_frosted = background.panel_css(background.resolve(
    {"background_mode": "image", "background_image": "p.png"}))
check("the heatmap is IN background.panel_css's one frosted rule, so "
      "retuning the tint or blur retunes it too and it can never "
      "drift out of step with the deck table",
      "table, .callout, .klaus-hm {" in _frosted)
check("the heatmap's own surface rule is overridable by it (panel_css "
      "wins with !important on all four properties)",
      _frosted.count("!important") >= 4)


# ------------------------------------------------------------ SQL glue
section("collection queries")


class FakeDB:
    def __init__(self, history=(), forecast=(), today_epoch=0, ids=()):
        self.history, self.forecast = list(history), list(forecast)
        self.today_epoch, self.ids = today_epoch, list(ids)
        self.calls = []

    def all(self, sql, *params):
        self.calls.append((sql, params))
        return self.history if "FROM revlog" in sql else self.forecast

    def scalar(self, sql, *params):
        self.calls.append((sql, params))
        return self.today_epoch

    def list(self, sql, *params):
        self.calls.append((sql, params))
        return self.ids


class FakeSched:
    def __init__(self, day_cutoff, today):
        self.day_cutoff, self.today = day_cutoff, today


class FakeCol:
    def __init__(self, db, day_cutoff=0, today=0):
        self.db, self.sched = db, FakeSched(day_cutoff, today)

    def get_config(self, key, default=None):
        return default


check("day bucketing goes through SQLite's 'localtime', not a fixed "
      "86400 grid — a DST change would otherwise shift every bucket by "
      "an hour and start filing late-evening reviews under tomorrow",
      "'localtime'" in heatmap._day_expr("id", 0)
      and "'start of day'" in heatmap._day_expr("id", 0))
check("the rollover offset is baked in as an int, never as user text",
      "14400" in heatmap._day_expr("id", 14400))

# 2026-08-27 04:00 local -> rollover hour 4.
_cutoff = int(datetime.datetime(2026, 8, 28, 4, 0).timestamp())
check("the rollover hour is read off the scheduler's own cut-off, so a "
      "profile that never wrote the config key still buckets days the "
      "way Anki counts them",
      heatmap._rollover_hours(FakeCol(FakeDB(), day_cutoff=_cutoff)) == 4)
check("an unusable scheduler falls back to Anki's default of 4am",
      heatmap._rollover_hours(FakeCol(FakeDB(), day_cutoff="nonsense")) == 4)

_db = FakeDB(
    history=[(19998 * DAY, 5), (20000 * DAY, 7)],
    forecast=[(1500, 3), (1502, 9)],
    today_epoch=20000 * DAY,
)
_history, _forecast, _today_n = heatmap._collect(
    FakeCol(_db, day_cutoff=_cutoff, today=1500), 28)
check("history comes back as (day number, count)",
      _history == [(19998, 5), (20000, 7)])
check("today is derived from the same clock the buckets use",
      _today_n == 20000)
check("due day numbers are rebased onto the same axis: a card due on "
      "the scheduler's own 'today' lands on today",
      _forecast == {20000: 3, 20002: 9})
_sql = " ".join(sql for sql, _p in _db.calls)
check("only real reviews are counted — revlog rows with ease 0 are "
      "manual entries (set due date, forget, bulk reschedules), not "
      "study",
      "ease > 0" in _sql)
check("the forecast is queues 2 and 3, whose `due` is a day number; "
      "queue 1 stores an epoch and suspended cards are not scheduled",
      "queue IN (2, 3)" in _sql)
check("history is NOT date-limited — the streak and the share of days "
      "studied are only honest over everything",
      "FROM revlog WHERE ease > 0 GROUP BY day" in _sql)

check("switched off, nothing is rendered and no query runs",
      heatmap.render_for_collection(
          FakeCol(FakeDB(), day_cutoff=_cutoff),
          {"heatmap_enabled": False}) == ""
      )

section("clicking a day (K-131)")

# Pouya, 2026-08-31: "when I click on an individual output, it doesn't
# show this klausday search query... the klausday thing does not help."
# It was opaque AND inert: the token was resolved by assigning
# search_context.card_ids, and Anki's SearchContext has no such field
# (its fields are search/browser/order/reverse/addon_metadata/ids —
# read out of aqt/browser/table/__init__.pyc), so the assignment did
# nothing and Anki parsed "klausday:20000" as a field search matching
# no cards. Native operators now, which are also editable by hand.
_T = 20000
check("a future day asks Anki what is due that many days out",
      heatmap.day_query(_T + 5, _T) == "prop:due=5"
      and heatmap.day_query(_T + 1, _T) == "prop:due=1")
check("today is simply rated:1",
      heatmap.day_query(_T, _T) == "rated:1")
check("a past day is a bounded pair — 'answered within n days' minus "
      "'answered within n-1', which leaves exactly that one day",
      heatmap.day_query(_T - 1, _T) == "rated:2 -rated:1"
      and heatmap.day_query(_T - 30, _T) == "rated:31 -rated:30")
check("the oldest drawable day still lands inside Anki's 365-day cap "
      "on rated: — which is WHY the range menu stops at a year",
      heatmap.day_query(_T - (max(heatmap.RANGE_CHOICES) - 1), _T)
      == "rated:365 -rated:364"
      and max(heatmap.RANGE_CHOICES) <= 365)
check("every query is built from NATIVE operators only — nothing "
      "private left for Anki to fail to understand",
      all(q.split(":")[0].lstrip("-") in ("prop", "rated")
          for day in (_T + 3, _T, _T - 1, _T - 200)
          for q in heatmap.day_query(day, _T).split()))
check("the klausday token, its resolver hook and its query helper are "
      "GONE, not left as dead code",
      not hasattr(heatmap, "SEARCH_PREFIX")
      and not hasattr(heatmap, "cards_reviewed_on")
      and not hasattr(heatmap, "_on_browser_will_search")
      and "browser_will_search"
      not in open("klaus_note/heatmap.py", encoding="utf8").read())

section("the KlausBook design gate")
_HM_SRC = open("klaus_note/heatmap.py", encoding="utf8").read()
_render_slice = _HM_SRC.split("def _on_deck_browser_content")[1].split(
    "def _on_webview_will_set_content")[0]
_css_slice = _HM_SRC.split("def _on_webview_will_set_content")[1].split(
    "def _open_day")[0]
check("the panel is a deck-screen WIDGET, so it renders only with the "
      "KlausNote design layer on — native mode leaves Anki's deck "
      "screen exactly as Anki draws it",
      "design_enabled" in _render_slice)
check("its stylesheet is gated the same way, so the css can never "
      "outlive the markup it styles",
      "design_enabled" in _css_slice)
check("the gate is NOT folded into enabled(): Preferences seeds its "
      "switch from enabled(stored) and saves that state back, so "
      "gating there would uncheck the switch and quietly persist "
      "heatmap_enabled False — losing an untouched preference",
      heatmap.enabled({"klausbook_design": False}) is True)

section("the corner menu's settings")

check("the range defaults to a year",
      heatmap.history_window({}) == heatmap.DEFAULT_HISTORY_DAYS
      and heatmap.DEFAULT_HISTORY_DAYS in heatmap.RANGE_CHOICES)
check("each of the menu's own choices is honoured",
      all(heatmap.history_window({"heatmap_history_days": d}) == d
          for d in heatmap.RANGE_CHOICES))
check("a value the menu cannot produce is NOT allowed to size the "
      "grid — a hand-edited 9000 would draw a 25-year ribbon",
      heatmap.history_window({"heatmap_history_days": 9000})
      == heatmap.DEFAULT_HISTORY_DAYS
      and heatmap.history_window({"heatmap_history_days": "365"})
      == heatmap.DEFAULT_HISTORY_DAYS
      and heatmap.history_window(None) == heatmap.DEFAULT_HISTORY_DAYS)
check("the forecast is on by default and off only when asked",
      heatmap.forecast_window({}) == heatmap.DEFAULT_FORECAST_DAYS
      and heatmap.forecast_window({"heatmap_forecast": False}) == 0)
check("a corrupt forecast value SHOWS the forecast — the same "
      "direction enabled() errs in, so bad config never silently "
      "subtracts from the panel",
      heatmap.forecast_window({"heatmap_forecast": "no"})
      == heatmap.DEFAULT_FORECAST_DAYS)

_written = []
_orig_write = heatmap._write_cfg
heatmap._write_cfg = lambda updates: _written.append(updates)
try:
    for _payload in ("history:182", "forecast:0", "forecast:1"):
        heatmap._apply_setting(_payload)
    check("a valid choice writes exactly its own key",
          _written == [{"heatmap_history_days": 182},
                       {"heatmap_forecast": False},
                       {"heatmap_forecast": True}])
    _written.clear()
    for _junk in ("history:9000", "history:abc", "forecast:2", "colors:lime",
                  "", "history:", ":", "history:365:extra"):
        heatmap._apply_setting(_junk)
    check("and nothing the page could invent writes ANYTHING — the "
          "webview is never trusted with a config value",
          _written == [], str(_written))
    _written.clear()
    check("a settings message is answered as handled",
          heatmap._on_js_message(
              (False, None), heatmap.SET_PREFIX + "history:91", None)
          == (True, None))
    check("...and routed as a SETTING, not as a day — 'set:history:91' "
          "ends in a number the day parser would happily swallow",
          _written == [{"heatmap_history_days": 91}], str(_written))
finally:
    heatmap._write_cfg = _orig_write

section("bridge")
check("a click is deferred, never run inside the webchannel handler",
      "QTimer.singleShot" in open("klaus_note/heatmap.py", encoding="utf8").read())
check("a foreign message is passed straight through untouched",
      heatmap._on_js_message(("sentinel",), "klaus_note:settings", None)
      == ("sentinel",))
check("a malformed day is swallowed rather than raising into Anki",
      heatmap._on_js_message((False, None), "klaus_note:heatmap:xyz", None)
      == (True, None))
# The two bridge sites worker-K could not reach from its own claim
# (K-142). Returning (False, None) re-opens the message to the rest of
# Anki's hook chain; both flips survived the mutation audit.
check("a rejected setting is still ANSWERED — a False here hands the "
      "payload back to Anki's hook chain instead of ending it",
      heatmap._apply_setting("history:9999") == (True, None)
      and heatmap._apply_setting("nonsense") == (True, None))
_timer_calls = []


class _RecordingTimer:
    @staticmethod
    def singleShot(ms, fn):
        _timer_calls.append((ms, fn))


import types as _types  # noqa: E402
_fake_qt = _types.ModuleType("aqt.qt")
_fake_qt.QTimer = _RecordingTimer
sys.modules["aqt.qt"] = _fake_qt
check("a day click is answered as handled AND deferred off the bridge "
      "— running Browse inside the webchannel call is the reentrancy "
      "hazard tests/test_bridge_reentrancy.py exists for",
      heatmap._on_js_message((False, None), "klaus_note:heatmap:20000", None)
      == (True, None)
      and len(_timer_calls) == 1 and _timer_calls[0][0] == 0)


# --------------------------------------------------- the real collection
section("against the real collection (read-only)")

_COL = os.path.expanduser(
    "~/Library/Application Support/Anki2/Pouya/collection.anki2")
if not os.path.exists(_COL):
    print("  SKIP no collection at %s — the ease>0 filter is only "
          "asserted, not demonstrated" % _COL)
else:
    _con = sqlite3.connect(f"file:{_COL}?immutable=1", uri=True)
    _expr = heatmap._day_expr("id", 4 * 3600)

    def _rows(where):
        return [
            (int(d) // DAY, int(c))
            for d, c in _con.execute(
                f"SELECT {_expr} AS day, COUNT() FROM revlog {where}"
                " GROUP BY day ORDER BY day"
            )
        ]

    _all_rows = _rows("")
    _real_rows = _rows("WHERE ease > 0")
    _today_real = int(_con.execute(
        "SELECT CAST(STRFTIME('%s','now','-14400 seconds','localtime',"
        "'start of day') AS int)").fetchone()[0]) // DAY
    _con.close()

    check("the query runs against a real 190k-row revlog and returns "
          "one row per day studied", 0 < len(_real_rows) < 20000,
          f"{len(_real_rows)} days")
    _all_avg = heatmap.stats_from_history(_all_rows, _today_real)["daily_avg"]
    _real_avg = heatmap.stats_from_history(_real_rows, _today_real)["daily_avg"]
    check("the ease>0 filter is not cosmetic: unfiltered, manual "
          "reschedules inflate this collection's daily average several "
          "times over, and since the average IS the top of the ramp "
          "that would flatten nearly every real study day to the same "
          "faint step",
          _all_avg > _real_avg * 3, f"avg {_all_avg} vs {_real_avg}")
    _stats_real = heatmap.stats_from_history(_real_rows, _today_real)
    check("real stats are all in range",
          0 <= _stats_real["pct_days_active"] <= 100
          and _stats_real["streak_cur"] <= _stats_real["streak_max"]
          and _stats_real["days_learned"] == len(_real_rows))
    _grid = heatmap.build_columns(dict(_real_rows), {}, _today_real, 365, 28)
    # Every column is still seven ROWS tall (that is what keeps a
    # cell's weekday readable off its row), but a year is no longer
    # ~56 columns: grouping by month splits each boundary week, which
    # costs 10-13 extra columns across a 13-month window. Measured
    # across 400 window positions: 66-69.
    check("a year of real data lays out as full-height month runs",
          all(len(c["cells"]) == 7 for c in _grid) and 64 <= len(_grid) <= 71,
          f"{len(_grid)} columns")
    _real_html = heatmap.heatmap_html(
        dict(_real_rows), {}, _today_real, _stats_real)
    check("and renders", _real_html.startswith('<div class="klaus-hm">')
          and len(_real_html) > 10000)

raise SystemExit(report())
