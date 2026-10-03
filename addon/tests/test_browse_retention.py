"""Headless tests for klaus_note/browse_retention.py — the Browse "Retention"
column (K-147).

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_browse_retention.py

Four things this suite exists to hold down:

1. PER-ROW COST. ``browser_did_fetch_row`` fires per rendered row while the
   user scrolls, so a single row must cost ONE indexed statement. The fake
   collection counts every ``db.all`` / ``db.scalar`` call and the pins fail
   if a row spends more than one, or if either statement loses its WHERE
   clause and becomes a collection scan.
2. NOTES MODE. A note has many cards; the cell shows the LOWEST scoring one
   and skips cards that were never studied. Pinned in both directions
   (min wins; a new card does not drag the note to 0%).
3. NO FORK OF THE CURVE. retention.py owns ``fsrs_retrievability`` /
   ``sm2_retrievability``. A source pin (over ``code_only``, so prose can't
   satisfy it) fails if this module ever grows its own copy of the
   arithmetic, and the value pins compare against retention.py's functions
   rather than against hardcoded numbers.
4. AQT-FREE MODULE TOP. Parsed from the AST, not grepped: nothing at module
   level may import aqt/anki, so ``import klaus_note.browse_retention`` is
   clean under the stub harness and Browse never pays for Qt at import.

The glue is exercised too, with hand-built stand-ins for Anki's ``CellRow``
/ ``Cell`` / ``BrowserColumns`` (their shapes were read out of Anki 26.8.1's
own bytecode) and a fake ``gui_hooks``, so the hook wiring and the cell
write are covered without Qt.

A final section cross-checks the pure math against the REAL collection,
opened read-only/immutable, and SKIPs honestly when it isn't there.
"""
from __future__ import annotations

import ast
import importlib
import os
import sqlite3
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import ADDON, check, code_only, install, report, section  # noqa: E402

install()

br = importlib.import_module("klaus_note.browse_retention")
retention = importlib.import_module("klaus_note.retention")

SRC_PATH = os.path.join(ADDON, "browse_retention.py")
with open(SRC_PATH, encoding="utf-8") as fh:
    SRC = fh.read()
CODE = code_only(SRC)

NOW = 1_788_000_000.0  # fixed "now" so every expectation is deterministic
DAY = 86400.0


# ----------------------------------------------------------- fake collection


class FakeDB:
    """Counts and records every statement, so the per-row-cost pins are
    measurements rather than assertions of intent."""

    def __init__(self, cards=(), revlog=None):
        self.cards = list(cards)  # (id, nid, type, ivl, data)
        self.revlog = dict(revlog or {})  # cid -> last review id (ms)
        self.all_sql: list[tuple] = []
        self.scalar_sql: list[tuple] = []

    def all(self, sql, *args):
        self.all_sql.append((sql, args))
        if "where nid = ?" in sql:
            nid = args[0]
            return [
                (c[0], c[2], c[3], c[4]) for c in self.cards if c[1] == nid
            ]
        if "where id = ?" in sql:
            cid = args[0]
            return [(c[0], c[2], c[3], c[4]) for c in self.cards if c[0] == cid]
        raise AssertionError(f"unexpected unbounded query: {sql!r}")

    def scalar(self, sql, *args):
        self.scalar_sql.append((sql, args))
        return self.revlog.get(args[0])


class FakeCol:
    def __init__(self, cards=(), revlog=None):
        self.db = FakeDB(cards, revlog)


def close(got, want, tol=1e-9):
    """None-safe ``|got - want| < tol``.

    Every value pin runs through this so that a regression which turns a
    number into None FAILS its own check instead of raising a TypeError and
    taking the rest of the run — and every later pin — down with it. The
    F3 falsification (dropping the notes-mode WHERE clause) is exactly the
    case that proved this necessary.
    """
    return got is not None and want is not None and abs(got - want) < tol


def fsrs_data(s, decay=0.18, lrt=None):
    import json

    state = {"s": s, "d": 5.0, "dr": 0.9, "decay": decay}
    if lrt is not None:
        state["lrt"] = lrt
    return json.dumps(state)


# ------------------------------------------------------------------ formatting

section("formatting (aqt-free)")

check('format_retention(None) == "—"', br.format_retention(None) == "—")
check('EMPTY_CELL is the em dash', br.EMPTY_CELL == "—")
check('format_retention(0.874) == "87%"', br.format_retention(0.874) == "87%")
check('format_retention(0.875) == "88%"', br.format_retention(0.875) == "88%")
check('format_retention(1.0) == "100%"', br.format_retention(1.0) == "100%")
check('format_retention(0.0) == "0%"', br.format_retention(0.0) == "0%")
check('format_retention("bogus") == "—"', br.format_retention("bogus") == "—")
check(
    "Library and Browse print a missing score identically",
    br.EMPTY_CELL in open(os.path.join(ADDON, "pdf_drive.py"), encoding="utf-8").read(),
)


# ------------------------------------------------------------- per-card math

section("per-card retention (aqt-free)")

check(
    "new card (type 0) is None, never 0%",
    br.card_retention(0, 0, '{"pos":1014982}', NOW) is None,
)
check(
    "new card with empty data is None",
    br.card_retention(0, 0, "", NOW) is None,
)
check(
    "new card is None even if a stale FSRS state lingers",
    br.card_retention(0, 10, fsrs_data(100.0, lrt=NOW - 5 * DAY), NOW) is None,
)

_s, _decay, _elapsed = 161.2696, 0.18, 30.0
_got = br.card_retention(2, 158, fsrs_data(_s, _decay, NOW - _elapsed * DAY), NOW)
_want = retention.fsrs_retrievability(_s, _decay, _elapsed)
check(
    "FSRS card delegates to retention.fsrs_retrievability",
    close(_got, _want, 1e-12),
    f"- got {_got!r} want {_want!r}",
)
check(
    "per-card decay is honoured (0.18 != the 0.5 default)",
    abs(retention.fsrs_retrievability(_s, 0.5, _elapsed) - _want) > 1e-6,
)
check(
    "R == 0.9 when elapsed equals stability (decay 0.5)",
    close(br.card_retention(2, 10, fsrs_data(10.0, 0.5, NOW - 10 * DAY), NOW), 0.9),
)
check(
    "R == 1.0 at zero elapsed",
    close(br.card_retention(2, 10, fsrs_data(10.0, 0.5, NOW), NOW), 1.0),
)
check(
    "R decays monotonically with elapsed time",
    (br.card_retention(2, 10, fsrs_data(10.0, 0.5, NOW - 1 * DAY), NOW) or 0)
    > (br.card_retention(2, 10, fsrs_data(10.0, 0.5, NOW - 60 * DAY), NOW) or 0),
)
check(
    "R stays inside [0, 1] at absurd elapsed",
    0.0
    <= (br.card_retention(2, 10, fsrs_data(0.0025, 0.18, NOW - 9999 * DAY), NOW) or -1)
    <= 1.0,
)

section("fallback paths (aqt-free)")

check(
    "FSRS state missing lrt falls back to the revlog callable",
    close(
        br.card_retention(2, 10, fsrs_data(10.0, 0.5), NOW, lambda: NOW - 10 * DAY),
        0.9,
    ),
)
check(
    "FSRS state missing lrt with no review history reads as fresh (elapsed 0)",
    close(br.card_retention(2, 10, fsrs_data(10.0, 0.5), NOW, lambda: None), 1.0),
)
_sm2 = br.card_retention(2, 20, "", NOW, lambda: NOW - 20 * DAY)
check(
    "reviewed card with no FSRS state uses retention.sm2_retrievability",
    close(_sm2, retention.sm2_retrievability(20, 20.0), 1e-12),
)
check(
    "reviewed card with no FSRS state and no revlog is None",
    br.card_retention(2, 20, "", NOW, lambda: None) is None,
)
check(
    "reviewed card with no FSRS state and no callable at all is None",
    br.card_retention(2, 20, "", NOW) is None,
)
check(
    "corrupt cards.data JSON degrades to the SM-2 path, never raises",
    br.card_retention(2, 20, "{not json", NOW, lambda: NOW - 20 * DAY) is not None,
)
check(
    "non-dict cards.data JSON degrades too",
    br.card_retention(2, 20, "[1,2,3]", NOW, lambda: NOW - 20 * DAY) is not None,
)
check(
    'stability of 0 is not treated as an FSRS state',
    br.card_retention(2, 20, '{"s":0,"decay":0.5}', NOW, lambda: None) is None,
)
check("parse_card_state('') is None", br.parse_card_state("") is None)
check("parse_card_state(None) is None", br.parse_card_state(None) is None)
check(
    "parse_card_state returns the dict",
    br.parse_card_state('{"s":1.5}') == {"s": 1.5},
)


# --------------------------------------------------------------- notes mode

section("notes mode aggregation (aqt-free)")

check("note_retention([]) is None", br.note_retention([]) is None)
check("note_retention([None, None]) is None", br.note_retention([None, None]) is None)
check(
    "note_retention takes the LOWEST card — the one nearest forgotten",
    br.note_retention([0.9, 0.2, 0.55]) == 0.2,
)
check(
    "a new card does not drag the note to 0%",
    br.note_retention([None, 0.9]) == 0.9,
)
check(
    "a genuine 0.0 still wins over a higher card",
    br.note_retention([0.0, 0.9]) == 0.0,
)


# ----------------------------------------------------------- column plumbing

section("cell_index (aqt-free)")

check(
    "finds our key at its position",
    br.cell_index(["noteFld", "template", br.COLUMN_KEY, "cardDue"]) == 2,
)
check("absent column reads as None", br.cell_index(["noteFld", "cardDue"]) is None)
check("empty column list reads as None", br.cell_index([]) is None)
check("non-iterable columns read as None", br.cell_index(None) is None)
check("COLUMN_KEY is the stable stored key", br.COLUMN_KEY == "klaus_retention")


# ------------------------------------------------------- per-row cost (fakes)

section("per-row cost: one indexed statement per row")

_cards = [
    (101, 11, 2, 158, fsrs_data(161.2696, 0.18, NOW - 30 * DAY)),
    (102, 11, 2, 4, fsrs_data(0.0025, 0.18, NOW - 1 * DAY)),
    (103, 12, 0, 0, '{"pos":9}'),
]

col = FakeCol(_cards)
val = br.retention_for_item(col, 101, False, now=NOW)
check(
    "cards mode: exactly ONE db.all for the row",
    len(col.db.all_sql) == 1,
    f"- {col.db.all_sql}",
)
check(
    "cards mode: zero revlog queries on a modern FSRS card",
    len(col.db.scalar_sql) == 0,
)
check(
    "cards mode SQL is a primary-key seek",
    "from cards where id = ?" in col.db.all_sql[0][0],
    f"- {col.db.all_sql[0][0]!r}",
)
check(
    "cards mode value matches the pure per-card math",
    close(val, retention.fsrs_retrievability(161.2696, 0.18, 30.0), 1e-12),
)

col = FakeCol(_cards)
val = br.retention_for_item(col, 11, True, now=NOW)
check(
    "notes mode: exactly ONE db.all for the whole note",
    len(col.db.all_sql) == 1,
    f"- {col.db.all_sql}",
)
check(
    "notes mode SQL rides ix_cards_nid",
    "from cards where nid = ?" in col.db.all_sql[0][0],
    f"- {col.db.all_sql[0][0]!r}",
)
check(
    "notes mode returns the note's LOWEST card",
    close(val, retention.fsrs_retrievability(0.0025, 0.18, 1.0), 1e-12),
    f"- {val!r}",
)

col = FakeCol(_cards)
check(
    "a note whose every card is new reads None",
    br.retention_for_item(col, 12, True, now=NOW) is None,
)

col = FakeCol(
    [(201, 21, 2, 20, "")], revlog={201: int((NOW - 20 * DAY) * 1000)}
)
val = br.retention_for_item(col, 201, False, now=NOW)
check(
    "the revlog fallback is ONE extra scalar, only when needed",
    len(col.db.all_sql) == 1 and len(col.db.scalar_sql) == 1,
    f"- all={col.db.all_sql} scalar={col.db.scalar_sql}",
)
check(
    "the revlog fallback is a cid seek, not a group-by",
    "where cid = ?" in col.db.scalar_sql[0][0]
    and "group by" not in col.db.scalar_sql[0][0].lower(),
)
check(
    "SM-2 fallback value matches retention.sm2_retrievability",
    close(val, retention.sm2_retrievability(20, 20.0), 1e-12),
)

check(
    "a missing row degrades to None, not an exception",
    br.retention_for_item(FakeCol(_cards), 99999, False, now=NOW) is None,
)


class ExplodingCol:
    class db:  # noqa: D106
        @staticmethod
        def all(*a, **k):
            raise RuntimeError("boom")

        @staticmethod
        def scalar(*a, **k):
            raise RuntimeError("boom")


check(
    "a database error degrades to None, never propagates into Browse",
    br.retention_for_item(ExplodingCol(), 1, False, now=NOW) is None,
)
check(
    "a revlog error degrades to None too",
    br.card_last_review_secs(ExplodingCol(), 1) is None,
)


# ------------------------------------------------------------ the aqt glue

section("aqt glue with stand-ins for Anki's own types")


class FakeColumn:
    """Stands in for BrowserColumns.Column (a protobuf message) — the field
    names come from anki/search_pb2's descriptor, read out of 26.8.1."""

    def __init__(self, **kw):
        self.kw = kw
        for k, v in kw.items():
            setattr(self, k, v)


class FakeBrowserColumns:
    Column = FakeColumn
    SORTING_NONE = 0
    SORTING_ASCENDING = 1
    SORTING_DESCENDING = 2
    ALIGNMENT_START = 0
    ALIGNMENT_CENTER = 1


# Set the attribute on the harness's permissive anki.collection rather than
# replacing the module: other klaus_note modules import AddNoteRequest from it.
sys.modules["anki.collection"].BrowserColumns = FakeBrowserColumns

columns: dict = {}
br.on_browser_did_fetch_columns(columns)
check("the column registers under COLUMN_KEY", br.COLUMN_KEY in columns)
_c = columns.get(br.COLUMN_KEY)
check("cards-mode label is 'Retention'", getattr(_c, "cards_mode_label", None) == "Retention")
check("notes-mode label is 'Retention'", getattr(_c, "notes_mode_label", None) == "Retention")
check("the Column carries its own key", getattr(_c, "key", None) == br.COLUMN_KEY)
check(
    "sorting_cards is SORTING_NONE — the backend cannot sort a custom column",
    getattr(_c, "sorting_cards", None) == FakeBrowserColumns.SORTING_NONE,
)
check(
    "sorting_notes is SORTING_NONE too",
    getattr(_c, "sorting_notes", None) == FakeBrowserColumns.SORTING_NONE,
)
check("uses_cell_font is False (this is a number, not note content)",
      getattr(_c, "uses_cell_font", None) is False)
check(
    "alignment is centred",
    getattr(_c, "alignment", None) == FakeBrowserColumns.ALIGNMENT_CENTER,
)
check(
    "both tooltips say the column cannot be sorted",
    "cannot be sorted" in br.CARDS_TOOLTIP and "cannot be sorted" in br.NOTES_TOOLTIP,
)
check(
    "the notes tooltip documents the lowest-card rule",
    "lowest" in br.NOTES_TOOLTIP.lower(),
)


class FakeCell:
    def __init__(self, text=""):
        self.text = text
        self.is_rtl = False


class FakeCellRow:
    def __init__(self, n, is_disabled=False):
        self.cells = tuple(FakeCell() for _ in range(n))
        self.is_disabled = is_disabled


_original_collection = br._collection
_fake_col = FakeCol(_cards)
br._collection = lambda: _fake_col

try:
    cols = ["noteFld", br.COLUMN_KEY, "cardDue"]
    row = FakeCellRow(3)
    br.on_browser_did_fetch_row(101, False, row, cols)
    check(
        "the row hook writes a percentage into OUR cell",
        row.cells[1].text.endswith("%"),
        f"- {row.cells[1].text!r}",
    )
    check(
        "the row hook touches no other cell",
        row.cells[0].text == "" and row.cells[2].text == "",
    )

    _fake_col.db.all_sql.clear()
    row = FakeCellRow(2)
    br.on_browser_did_fetch_row(101, False, row, ["noteFld", "cardDue"])
    check(
        "column disabled: no cell written",
        row.cells[0].text == "" and row.cells[1].text == "",
    )
    check(
        "column disabled: NOT ONE query is issued",
        len(_fake_col.db.all_sql) == 0,
        f"- {_fake_col.db.all_sql}",
    )

    _fake_col.db.all_sql.clear()
    row = FakeCellRow(3, is_disabled=True)
    br.on_browser_did_fetch_row(101, False, row, cols)
    check(
        "a disabled placeholder row is skipped without querying",
        row.cells[1].text == "" and len(_fake_col.db.all_sql) == 0,
    )

    row = FakeCellRow(3)
    br.on_browser_did_fetch_row(103, False, row, cols)
    check(
        "a new card renders the em dash, not 0%",
        row.cells[1].text == br.EMPTY_CELL,
        f"- {row.cells[1].text!r}",
    )

    # The hook takes no `now`, so pin the RELATION rather than a wall-clock
    # value: the note's cell must equal its weakest card's cell and differ
    # from its strongest. Flipping min->max in note_retention fails this.
    row_note, row_low, row_high = FakeCellRow(3), FakeCellRow(3), FakeCellRow(3)
    br.on_browser_did_fetch_row(11, True, row_note, cols)
    br.on_browser_did_fetch_row(102, False, row_low, cols)
    br.on_browser_did_fetch_row(101, False, row_high, cols)
    check(
        "notes mode fills the cell from the note's LOWEST card",
        row_note.cells[1].text == row_low.cells[1].text,
        f"- note {row_note.cells[1].text!r} vs low {row_low.cells[1].text!r}",
    )
    check(
        "notes mode is not showing the note's highest card",
        row_note.cells[1].text != row_high.cells[1].text,
        f"- note {row_note.cells[1].text!r} vs high {row_high.cells[1].text!r}",
    )

    row = FakeCellRow(1)  # fewer cells than columns: must not IndexError
    br.on_browser_did_fetch_row(101, False, row, cols)
    check("a short cell tuple is survived, not indexed past", row.cells[0].text == "")

    br._collection = lambda: None
    row = FakeCellRow(3)
    br.on_browser_did_fetch_row(101, False, row, cols)
    check("no open collection: cell left blank, no crash", row.cells[1].text == "")
finally:
    br._collection = _original_collection


class FakeHook:
    def __init__(self):
        self.callbacks = []

    def append(self, cb):
        self.callbacks.append(cb)


gh = sys.modules["aqt.gui_hooks"]
_cols_hook, _row_hook = FakeHook(), FakeHook()
gh.browser_did_fetch_columns = _cols_hook
gh.browser_did_fetch_row = _row_hook
br.setup()
check(
    "setup() registers the columns hook",
    br.on_browser_did_fetch_columns in _cols_hook.callbacks,
)
check(
    "setup() registers the row hook",
    br.on_browser_did_fetch_row in _row_hook.callbacks,
)


# --------------------------------------------------------------- source pins

section("source pins")

_module_level_imports: list[str] = []
for _node in ast.parse(SRC).body:
    if isinstance(_node, ast.Import):
        _module_level_imports += [a.name for a in _node.names]
    elif isinstance(_node, ast.ImportFrom):
        _module_level_imports.append(_node.module or "")

check(
    "module top imports stdlib only — no aqt, no anki, no sibling modules",
    all(
        not (m.startswith("aqt") or m.startswith("anki") or m == "")
        for m in _module_level_imports
    ),
    f"- {_module_level_imports}",
)
check(
    "module top is __future__ + json + time and nothing else",
    sorted(_module_level_imports) == ["__future__", "json", "time"],
    f"- {_module_level_imports}",
)

_divider = SRC.find("# aqt glue")
check("the module carries an 'aqt glue' divider", _divider > 0)
for _name in (
    "def format_retention",
    "def card_retention",
    "def note_retention",
    "def cell_index",
    "def parse_card_state",
    "def retention_for_item",
):
    check(f"{_name[4:]} lives ABOVE the divider", 0 < SRC.find(_name) < _divider)
for _name in ("def make_column", "def on_browser_did_fetch_row", "def setup"):
    check(f"{_name[4:]} lives BELOW the divider", SRC.find(_name) > _divider)

check(
    "the FSRS curve is borrowed from retention.py, never forked here",
    "0.9 **" not in CODE and "0.9**" not in CODE,
    "- browse_retention grew its own copy of the forgetting curve",
)
check(
    "no exponent arithmetic at all above the glue",
    "**" not in CODE,
)
check(
    "it calls retention.fsrs_retrievability",
    "fsrs_retrievability" in CODE,
)
check(
    "it calls retention.sm2_retrievability",
    "sm2_retrievability" in CODE,
)

for _banned in (
    "priority_rows",
    "card_retrievability",
    "load_matches",
    "ensure_matches",
    "card_index",
    "pdf_index",
    "tag_sync",
):
    check(f"never reaches for {_banned}", _banned not in CODE)

_cards_sql = SRC.split("from cards")[1:]
check(
    "no unbounded read: every 'from cards' is immediately followed by WHERE",
    bool(_cards_sql) and all(seg.lstrip().startswith("where ") for seg in _cards_sql),
    f"- {[s[:24] for s in _cards_sql]}",
)
check(
    "exactly two statements read the cards table (cards mode + notes mode)",
    len(_cards_sql) == 2,
    f"- {len(_cards_sql)}",
)
check(
    "both per-row statements are parameterised (no f-string SQL)",
    'f"select' not in SRC and "f'select" not in SRC,
)
check(
    "SQL text: cards mode seeks the primary key",
    "select id, type, ivl, data from cards where id = ?" in SRC,
)
check(
    "SQL text: notes mode seeks ix_cards_nid",
    "select id, type, ivl, data from cards where nid = ?" in SRC,
)
check(
    "SQL text: the revlog fallback is a single-cid seek",
    "select max(id) from revlog where cid = ?" in SRC,
)
check(
    "every `except Exception` logs with the house prefix",
    SRC.count("[klaus_note]") == CODE.count("except Exception") == 7,
    f"- {SRC.count('[klaus_note]')} prints vs {CODE.count('except Exception')} handlers",
)
check(
    "no exec() anywhere (K-114 exec-ban applies to every new surface)",
    ".exec()" not in CODE,
)


# ------------------------------------------------- real collection (read-only)

section("real collection cross-check (read-only, immutable)")

_DB = os.path.expanduser(
    "~/Library/Application Support/Anki2/Pouya/collection.anki2"
)
if not os.path.exists(_DB):
    print("  SKIP real collection not present at " + _DB)
else:
    con = sqlite3.connect(f"file:{_DB}?immutable=1", uri=True)
    cur = con.cursor()
    import time as _time

    now = _time.time()

    fsrs_rows = cur.execute(
        "select id, type, ivl, data from cards "
        "where data like '%\"s\"%' and data like '%\"lrt\"%' limit 200"
    ).fetchall()
    check(
        "the collection actually has FSRS states to check against",
        len(fsrs_rows) > 0,
        f"- {len(fsrs_rows)} rows",
    )

    import json as _json

    ok_range = True
    ok_curve = True
    for cid, ctype, ivl, data in fsrs_rows:
        got = br.card_retention(ctype, ivl, data, now)
        if int(ctype) == 0:
            if got is not None:
                ok_curve = False
            continue
        st = _json.loads(data)
        want = retention.fsrs_retrievability(
            float(st["s"]),
            float(st.get("decay") or 0.5),
            (now - float(st["lrt"])) / DAY,
        )
        if not close(got, want, 1e-12):
            ok_curve = False
        if got is not None and not (0.0 <= got <= 1.0):
            ok_range = False
    check("every real FSRS card matches retention.py's curve exactly", ok_curve)
    check("every real value lands inside [0, 1]", ok_range)

    new_rows = cur.execute(
        "select id, type, ivl, data from cards where type = 0 limit 50"
    ).fetchall()
    check(
        "every real new card reads as None (renders —)",
        new_rows
        and all(br.card_retention(t, i, d, now) is None for _, t, i, d in new_rows),
        f"- {len(new_rows)} rows",
    )

    # The per-row queries, run against the real schema, hit an index and
    # return the shape retention_for_item expects.
    plan = cur.execute(
        "explain query plan select id, type, ivl, data from cards where nid = ?",
        (1,),
    ).fetchall()
    check(
        "notes-mode query uses ix_cards_nid (verified by EXPLAIN QUERY PLAN)",
        any("ix_cards_nid" in str(r) for r in plan),
        f"- {plan}",
    )
    plan = cur.execute(
        "explain query plan select max(id) from revlog where cid = ?", (1,)
    ).fetchall()
    check(
        "revlog fallback uses ix_revlog_cid",
        any("ix_revlog_cid" in str(r) for r in plan),
        f"- {plan}",
    )
    con.close()


raise SystemExit(report())
