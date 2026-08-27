"""Headless tests for klausmate.heatmap — the review heatmap.

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
heatmap = importlib.import_module("klausmate.heatmap")
theme = importlib.import_module("klausmate.theme")
background = importlib.import_module("klausmate.background")

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

for _avg in (0, 1, 2, 3, 7, 40, 800):
    _levels = heatmap.ramp_levels(_avg)
    if len(_levels) != 4 or any(
        _levels[i] >= _levels[i + 1] for i in range(3)
    ):
        check(f"ramp for avg={_avg} is four ascending steps", False,
              str(_levels))
        break
else:
    check("every average yields four STRICTLY ascending steps — a tiny "
          "average must not collapse the ramp to one usable colour", True)

check("the top step is a full day's work for this user",
      heatmap.ramp_levels(40)[-1] == 40)
check("the ramp scales with the user: 20/day and 800/day get the same "
      "four meanings, not the same four numbers",
      heatmap.ramp_levels(20) != heatmap.ramp_levels(800))

_levels = heatmap.ramp_levels(40)  # [10, 20, 30, 40]
check("nothing studied is step 0", heatmap.level_for(0, _levels) == 0)
check("a negative count cannot colour a cell",
      heatmap.level_for(-5, _levels) == 0)
check("one card is already step 1", heatmap.level_for(1, _levels) == 1)
check("a threshold belongs to its own step",
      [heatmap.level_for(v, _levels) for v in _levels] == [1, 2, 3, 4])
check("a monster day tops out rather than overflowing",
      heatmap.level_for(10 ** 6, _levels) == 4)


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
check("the first column is never labelled — its month began off-screen",
      _labels[0] == "")
_year = heatmap.month_labels(
    heatmap.build_columns({}, {}, _today, 365, 28))
check("a year of columns names about twelve months",
      11 <= len([m for m in _year if m]) <= 14,
      str([m for m in _year if m]))
check("month names are the real ones, in order",
      all(m in heatmap._MONTHS for m in _year if m))


# ------------------------------------------------------------- markup
section("markup")

_stats = heatmap.stats_from_history(_hist, 100)
check("nothing to show renders nothing at all, rather than an empty grid",
      heatmap.heatmap_html({}, {}, 100, _stats) == "")

_html = heatmap.heatmap_html({99: 40, 98: 0}, {101: 6}, 100, _stats,
                             history_days=14, forecast_days=7)
check("the panel wears the .klaus-hm hook background.panel_css frosts",
      '<div class="klaus-hm">' in _html)
check("a day with reviews is clickable", "klausmate:heatmap:99" in _html)
check("a day with NOTHING on it is not — an empty Browse reads as a "
      "broken link", "klausmate:heatmap:98" not in _html)
check("a scheduled day is clickable too", "klausmate:heatmap:101" in _html)
check("future cells are drawn from the future ramp",
      "f1" in _html or "f2" in _html or "f3" in _html or "f4" in _html)
check("cells carry a plain-language tooltip",
      "40 reviews" in _html and "6 cards due" in _html
      and "No reviews" in _html)
check("one review is not '1 reviews'",
      "1 review ·" in heatmap.heatmap_html({100: 1}, {}, 100, _stats, 5, 0))
check("the stats line is in the panel",
      "day streak" in _html and "cards/day" in _html and "of days" in _html)
_cells = heatmap.build_columns({99: 40}, {101: 6}, 100, 14, 7)
# Anchored so `klaus-hm-cells` and `klaus-hm-corner` cannot be counted
# as cells: the class must end right after the `c`.
_cell_tags = len(re.findall(r'class="klaus-hm-c[ "]', _html))
check("exactly one cell element per grid slot, plus the five legend "
      "swatches",
      _cell_tags == sum(len(c["cells"]) for c in _cells) + 5,
      f"{_cell_tags} tags")
# NB: the 14-day window above happens to start on a Sunday and end on a
# Saturday, so it has no ragged ends at all. Ask for one that does.
_ragged = heatmap.heatmap_html({99: 40}, {}, 100, _stats,
                               history_days=10, forecast_days=3)
check("out-of-window slots render as padding, so a window that does "
      "not begin on a Sunday still keeps its seven rows",
      "klaus-hm-c pad" in _ragged)
check("weekday labels appear on alternate rows only",
      _html.count(">Mon<") == 1 and ">Tue<" not in _html)


# ----------------------------------------------------------------- css
section("stylesheet")

_css = heatmap.heatmap_css()
check("both palettes ship, keyed on Anki's own night-mode class — Anki "
      "flips that class with JS and never re-runs the hook that "
      "injected this, so baking one palette would freeze the heatmap "
      "on whichever theme was live at draw time",
      ":root {" in _css and ":root.night-mode {" in _css)
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
      and "min-width" not in _css
      and "max-width: 100%" in _css)
check("month labels ride the same column pitch as the cells, so they "
      "line up by construction rather than by measurement",
      f"grid-auto-columns: {heatmap.CELL + heatmap.GAP}px" in _css
      and f"grid-auto-columns: {heatmap.CELL}px" in _css)
check("weekday labels ride the same row pitch",
      _css.count(f"repeat(7, {heatmap.CELL}px)") == 2)
check("all four done-steps and all four due-steps are defined",
      all(f"--klaus-hm-l{i}:" in _css for i in range(1, 5))
      and all(f"--klaus-hm-f{i}:" in _css for i in range(1, 5)))
check("scheduled days are hollow, not just paler — 'done' and 'to "
      "come' must not read as the same weight of ink",
      "inset 0 0 0 1px var(--klaus-hm-ring)" in _css)

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

_db2 = FakeDB(ids=[1, 2, 3])
check("a day's cards are found by re-running the very expression that "
      "built the bucket, so no timezone question is reintroduced",
      heatmap.cards_reviewed_on(FakeCol(_db2, day_cutoff=_cutoff), 20000)
      == [1, 2, 3])
_sql2, _params2 = _db2.calls[0]
check("...matched against that day number in seconds",
      _params2 == (20000 * DAY,))
check("and selected through `cards`, so rows whose card was deleted "
      "drop out", "FROM cards WHERE id IN" in _sql2)

check("switched off, nothing is rendered and no query runs",
      heatmap.render_for_collection(
          FakeCol(FakeDB(), day_cutoff=_cutoff),
          {"heatmap_enabled": False}) == ""
      )

section("bridge")
check("a click is deferred, never run inside the webchannel handler",
      "QTimer.singleShot" in open("klausmate/heatmap.py", encoding="utf8").read())
check("a foreign message is passed straight through untouched",
      heatmap._on_js_message(("sentinel",), "klausmate:settings", None)
      == ("sentinel",))
check("a malformed day is swallowed rather than raising into Anki",
      heatmap._on_js_message((False, None), "klausmate:heatmap:xyz", None)
      == (True, None))


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
    check("a year of real data lays out as whole weeks",
          all(len(c["cells"]) == 7 for c in _grid) and 55 <= len(_grid) <= 58,
          f"{len(_grid)} columns")
    _real_html = heatmap.heatmap_html(
        dict(_real_rows), {}, _today_real, _stats_real)
    check("and renders", _real_html.startswith('<div class="klaus-hm">')
          and len(_real_html) > 10000)

raise SystemExit(report())
