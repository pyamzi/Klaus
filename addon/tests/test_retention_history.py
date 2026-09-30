"""Tests for klausmate.retention_history (K-118) + retention count keys.

Covers: snapshot recording (append / same-day replace / 730 cap /
atomicity / corrupt-file tolerance), the aqt-free chart math (point
mapping, nice ticks, date thinning, labels), the priority_rows count
contract the Library's Cards/Notes split reads (note_count / card_count /
suspended_count off ONE batched nid→queue query, chunked for SQLite's
host-parameter cap), and the source pins: the K-114 exec() ban, the K-115
paintEvent try/finally paint guard, and the open_history_dialog signature
the Library's "Retention History…" menu item calls.
"""

import ast
import importlib
import inspect
import json
import os
import shutil
import sys
import tempfile
from array import array
from datetime import date, timedelta

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()

rh = importlib.import_module("klausmate.retention_history")
retention = importlib.import_module("klausmate.retention")
pdf_handler = importlib.import_module("klausmate.pdf_handler")
card_index = importlib.import_module("klausmate.card_index")
pdf_index = importlib.import_module("klausmate.pdf_index")
embeddings = importlib.import_module("klausmate.embeddings")

tmp = tempfile.mkdtemp(prefix="klaus_rh_")
# NEVER the real user_files: every retention storage path below reads the
# module globals, so point them at the scratch tree for the whole file.
retention.USER_FILES = tmp
retention.INDEX_DIR = os.path.join(tmp, "card_index")

_RH_SRC = open("klausmate/retention_history.py").read()
_RH_CODE = code_only(_RH_SRC)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ------------------------------------------------------------------ recording

section("recording — append, same-day replace, cap, atomicity, corrupt")

hdir = os.path.join(tmp, "hist")
rh.record_rows(
    hdir,
    [
        {"name": "Lec_1", "retention": 0.8321},
        {"name": "Lec_2", "retention": None},
        {"name": "", "retention": 0.5},
    ],
    today="2026-08-30",
)
hist = rh.load_history(hdir)
check("a row with retention records one dated snapshot",
      hist.get("Lec_1") == [["2026-08-30", 0.8321]])
check("retention None (unindexed) records nothing", "Lec_2" not in hist)
check("a nameless row records nothing", list(hist) == ["Lec_1"])

rh.record_rows(hdir, [{"name": "Lec_1", "retention": 0.9}], today="2026-08-30")
hist = rh.load_history(hdir)
check("same-day refresh REPLACES the value — never stacks",
      hist["Lec_1"] == [["2026-08-30", 0.9]])

rh.record_rows(hdir, [{"name": "Lec_1", "retention": 0.7}], today="2026-08-31")
hist = rh.load_history(hdir)
check("the next day appends chronologically",
      hist["Lec_1"] == [["2026-08-30", 0.9], ["2026-08-31", 0.7]])

calls = []
_orig_write = rh._atomic_write_json
rh._atomic_write_json = lambda p, o: calls.append(p) or _orig_write(p, o)
rh.record_rows(hdir, [{"name": "Lec_1", "retention": 0.7}], today="2026-08-31")
rh._atomic_write_json = _orig_write
check("an identical same-day snapshot skips the write entirely", calls == [])

start = date(2020, 1, 1)
big = [[(start + timedelta(days=i)).isoformat(), 0.5]
       for i in range(rh.MAX_ENTRIES)]
rh._atomic_write_json(rh._history_path(hdir), {"Cap_PDF": big})
rh.record_rows(hdir, [{"name": "Cap_PDF", "retention": 0.6}],
               today="2026-08-31")
series = rh.load_history(hdir)["Cap_PDF"]
check("series cap holds at MAX_ENTRIES (730)",
      len(series) == rh.MAX_ENTRIES == 730)
check("the OLDEST entry is the one dropped; the new one is last",
      series[0][0] == (start + timedelta(days=1)).isoformat()
      and series[-1] == ["2026-08-31", 0.6])

check("no .tmp files left behind by the atomic writes",
      [f for f in os.listdir(hdir) if f.endswith(".tmp")] == [])
check("writes are atomic — tmp + os.replace (pin reads code, not prose)",
      "os.replace(" in _RH_CODE)

_write(rh._history_path(hdir), "{ not json")
check("a corrupt file reads as empty history", rh.load_history(hdir) == {})
rh.record_rows(hdir, [{"name": "Lec_1", "retention": 0.5}],
               today="2026-08-31")
check("recording over a corrupt file recovers it",
      rh.load_history(hdir)["Lec_1"] == [["2026-08-31", 0.5]])

rh._atomic_write_json(
    rh._history_path(hdir),
    {"X": [["2026-01-01", 0.5], "junk", ["a", "b"], [1, 2, 3]], "Y": "no"},
)
loaded = rh.load_history(hdir)
check("malformed entries drop individually — the good one survives",
      loaded.get("X") == [["2026-01-01", 0.5]] and "Y" not in loaded)
check("missing file reads as empty",
      rh.load_history(os.path.join(tmp, "nowhere")) == {})

# ----------------------------------------------------------------- chart math

section("chart math — points, ticks, thinning, labels")

pad = (10.0, 10.0, 10.0, 10.0)
ents = [("2026-01-01", 0.0), ("2026-01-06", 0.5), ("2026-01-11", 1.0)]
pts = rh.chart_points(ents, 100, 100, pad)
check("x spans pad..w-pad, time-proportional",
      pts[0][0] == 10.0 and abs(pts[1][0] - 50.0) < 1e-9
      and pts[2][0] == 90.0)
check("y maps retention 0→plot bottom, 1→plot top",
      pts[0][1] == 90.0 and abs(pts[1][1] - 50.0) < 1e-9
      and pts[2][1] == 10.0)
check("empty history → no points", rh.chart_points([], 100, 100, pad) == [])
check("a single snapshot centres on x",
      rh.chart_points([("2026-01-01", 0.25)], 100, 100, pad)
      == [(50.0, 70.0)])
clamped = rh.chart_points(
    [("2026-01-01", 1.5), ("2026-01-02", -2.0)], 100, 100, pad)
check("out-of-range retention clamps to the plot, never escapes it",
      clamped[0][1] == 10.0 and clamped[1][1] == 90.0)
gap = rh.chart_points(
    [("2026-01-01", 0.0), ("2026-01-02", 0.0), ("2026-01-11", 0.0)],
    100, 100, pad)
check("a recording gap keeps its width (time spacing, not index spacing)",
      abs(gap[1][0] - 18.0) < 1e-9)
check("a degenerate box yields no points",
      rh.chart_points(ents, 15, 15, pad) == [])
check("entries with unparseable dates are skipped, not fatal",
      len(rh.chart_points([("nope", 0.5), ("2026-01-01", 0.5)],
                          100, 100, pad)) == 1)

check("the fixed 0–100 axis gets clean 20% ticks",
      rh.nice_ticks(0.0, 100.0, 5) == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0])
check("a degenerate range collapses to one tick",
      rh.nice_ticks(5.0, 5.0) == [5.0])
check("ticks stay on the 1/2/5 family and cover the range",
      rh.nice_ticks(0.0, 0.73, 5) == [0.0, 0.2, 0.4, 0.6, 0.8])

check("no entries → no labels", rh.thin_dates(0) == [])
check("one entry labels itself", rh.thin_dates(1) == [0])
check("a short series labels every entry", rh.thin_dates(4, 5) == [0, 1, 2, 3])
td = rh.thin_dates(100, 5)
check("a dense series thins to max labels incl. first and last",
      len(td) == 5 and td[0] == 0 and td[-1] == 99 and td == sorted(set(td)))

check("short_date renders locale-free", rh.short_date("2026-08-31") == "Aug 31")
check("short_date carries the year when asked",
      rh.short_date("2026-08-31", True) == "Aug 31, 2026")
check("short_date echoes junk instead of raising",
      rh.short_date("junk") == "junk")
check("subtitle: empty state", rh.subtitle_text([]) == "No snapshots yet")
check("subtitle: singular snapshot with latest %",
      rh.subtitle_text([("2026-08-31", 0.784)])
      == "Latest 78% · 1 snapshot since Aug 31, 2026")
check("sorted_entries sorts, clamps, and drops unparseable dates",
      rh.sorted_entries(
          [["2026-01-02", 0.5], ["2026-01-01", 1.7],
           ["bad", 0.1], ["2025-12-31", -3.0]])
      == [("2025-12-31", 0.0), ("2026-01-01", 1.0), ("2026-01-02", 0.5)])

# --------------------------------------------- priority_rows count contract

section("priority_rows — note/card/suspended counts (K-118 contract)")

cfg = {"embedding_provider": "voyage", "pdf_match_threshold": 0.75}
sig = embeddings.index_signature(cfg)

ctx = os.path.join(tmp, "contexts")
os.makedirs(ctx, exist_ok=True)
_write(os.path.join(ctx, "Lecture_1.txt"), "alpha beta gamma delta")
_write(os.path.join(ctx, "Lecture_2.txt"), "unindexed pdf")

cidx = card_index.CardIndex(
    provider=sig[0], model=sig[1], dims=2,
    nids=[1, 2, 3], mods=[10, 10, 10], hashes=["h1", "h2", "h3"],
    vectors=array("f", [1.0, 0.0, 0.0, 1.0, 1.0, 0.0]),
)
card_index.save(cidx, retention.INDEX_DIR)
digest = retention.card_index_digest(cidx)

src_sig = pdf_index.source_signature(tmp, "Lecture_1")
pidx = pdf_index.PdfIndex(
    provider=sig[0], model=sig[1], pdf_name="Lecture_1", dims=2,
    source_sig=src_sig, pages=[(1, "h1")], embedded_rows=1,
    vectors=array("f", [1.0, 0.0]),
)
pdf_index.save(pidx, pdf_index.index_dir(tmp, "Lecture_1"))
retention.save_matches("Lecture_1", sig, 2, src_sig, digest,
                       [(1, 0.9), (2, 0.8), (3, 0.5)], {1: 1, 2: 1, 3: 1})


class FakeDB:
    def __init__(self, card_rows, queue_rows):
        self.card_rows = card_rows
        self.queue_rows = queue_rows
        self.queue_queries = []

    def all(self, sql, *args):
        if sql.startswith("select id, nid, type, ivl, data"):
            return self.card_rows
        if sql.startswith("select nid, queue from cards where nid in ("):
            self.queue_queries.append((sql, args))
            want = set(args)
            return [(n, q) for n, q in self.queue_rows if n in want]
        if "revlog" in sql:
            return []
        raise AssertionError(f"unexpected SQL: {sql}")


class FakeCol:
    def __init__(self, card_rows, queue_rows):
        self.db = FakeDB(card_rows, queue_rows)


card_rows = [
    (11, 1, 0, 0, ""),  # nid 1, viewable new card
    (12, 1, 0, 0, ""),  # nid 1, suspended new card
    (13, 2, 0, 0, ""),  # nid 2, viewable
    (14, 3, 0, 0, ""),  # nid 3 — below threshold, must not count
]
queue_rows = [(1, 0), (1, -1), (2, 2), (3, -1)]
col = FakeCol(card_rows, queue_rows)
out = retention.priority_rows(col, cfg)
rows_by = {r["name"]: r for r in out["rows"]}
r1, r2 = rows_by["Lecture_1"], rows_by["Lecture_2"]

check("note_count = matched notes at/above the row's threshold",
      r1["note_count"] == 2)
check("card_count = those notes' cards with queue != -1 (viewable)",
      r1["card_count"] == 2)
check("suspended_count = their queue == -1 cards",
      r1["suspended_count"] == 1)
check("viewable + suspended == matched_cards (one truth, split two ways)",
      r1["card_count"] + r1["suspended_count"] == r1["matched_cards"] == 3)
check("an unindexed row still carries all three keys, at 0",
      (r2["note_count"], r2["card_count"], r2["suspended_count"]) == (0, 0, 0)
      and r2["indexed"] is False and r2["retention"] is None)
check("existing return keys survive (additive contract)",
      all(k in out for k in
          ("rows", "approx", "card_r", "matches", "card_index_ok")))
check("ONE batched queue query for the whole pool, shape pinned",
      len(col.db.queue_queries) == 1
      and col.db.queue_queries[0][0].startswith(
          "select nid, queue from cards where nid in (?")
      and set(col.db.queue_queries[0][1]) == {1, 2, 3})
check("card_queues handed back for col-free re-aggregation",
      out["card_queues"] == {1: [0, -1], 2: [2], 3: [-1]})

today = date.today().isoformat()
check("priority_rows records a history snapshot on the way out",
      rh.load_history(tmp).get("Lecture_1") == [[today, 0.0]])
check("rows without retention don't pollute history",
      "Lecture_2" not in rh.load_history(tmp))


def _boom(*a, **k):
    raise RuntimeError("boom")


_orig_rec = rh.record_rows
rh.record_rows = _boom
out2 = retention.priority_rows(FakeCol(card_rows, queue_rows), cfg)
rh.record_rows = _orig_rec
check("a history failure never breaks the Library pass",
      len(out2["rows"]) == 2 and "card_queues" in out2)

big_pool = set(range(1, 2001))
qrows = [(n, -1 if n % 3 == 0 else 0) for n in sorted(big_pool)]
col2 = FakeCol([], qrows)
qmap = retention.card_queues(col2, big_pool)
sizes = [len(args) for _sql, args in col2.db.queue_queries]
check("IN-list chunks at CARD_QUEUE_CHUNK (900/900/200 for 2000 nids)",
      sizes == [900, 900, 200] and retention.CARD_QUEUE_CHUNK == 900)
check("chunked map merges completely and splits queues correctly",
      len(qmap) == 2000 and qmap[3] == [-1] and qmap[4] == [0])

check("note_card_counts skips notes with no cards (deleted since indexing)",
      retention.note_card_counts([(7, 0.9)], 0.75, {}) == (0, 0, 0))
check("buried queues (-2/-3) stay viewable; only -1 suspends",
      retention.note_card_counts([(1, 0.9)], 0.5, {1: [-2, -3, -1, 2]})
      == (1, 3, 1))

# ------------------------------------------------------ delete cleanup

section("forget_history — one key, no-ops, corrupt/missing tolerance")

ddir = os.path.join(tmp, "del")
rh.record_rows(
    ddir,
    [{"name": "Doomed", "retention": 0.6},
     {"name": "Keeper", "retention": 0.4}],
    today="2026-08-30",
)
rh.forget_history(ddir, "Doomed")
left = rh.load_history(ddir)
check("forget drops exactly the named PDF's series", "Doomed" not in left)
check("every other PDF's series survives untouched",
      left == {"Keeper": [["2026-08-30", 0.4]]})

calls = []
_orig_write = rh._atomic_write_json
rh._atomic_write_json = lambda p, o: calls.append(p) or _orig_write(p, o)
rh.forget_history(ddir, "Doomed")   # already gone
rh._atomic_write_json = _orig_write
check("forgetting a key that isn't there skips the write entirely", calls == [])
check("the surviving series is unchanged by that no-op",
      rh.load_history(ddir) == {"Keeper": [["2026-08-30", 0.4]]})

# A blank name is never a real PDF — record_rows refuses to create such a
# key, so forget refuses to consume one, even against a hand-edited file
# that does carry an empty key.
rh._atomic_write_json(
    rh._history_path(ddir),
    {"": [["2026-08-30", 0.1]], "Keeper": [["2026-08-30", 0.4]]},
)
rh.forget_history(ddir, "   ")
check("a blank/whitespace name is refused, never resolved to a real key",
      "" in rh.load_history(ddir))

missing = os.path.join(tmp, "nowhere")
check("forget on a dir with no history file is a silent no-op that "
      "creates nothing",
      rh.forget_history(missing, "Doomed") is None
      and not os.path.isdir(missing))

_write(rh._history_path(ddir), "{ not json")
rh.forget_history(ddir, "Doomed")  # must not raise
check("a corrupt history file is tolerated, and left for record_rows to "
      "recover rather than truncated here",
      open(rh._history_path(ddir), encoding="utf-8").read() == "{ not json")
check("no .tmp files left behind by forget's atomic write",
      [f for f in os.listdir(ddir) if f.endswith(".tmp")] == [])

section("delete wiring — pdf_handler.delete_context forgets the history")

wdir = os.path.join(tmp, "wired")
os.makedirs(os.path.join(wdir, "contexts"), exist_ok=True)
_write(os.path.join(wdir, "contexts", "Gone.txt"), "text")
rh.record_rows(
    wdir,
    [{"name": "Gone", "retention": 0.7}, {"name": "Stays", "retention": 0.3}],
    today="2026-08-30",
)
# The REAL lazy hop, not a stub: aqt is stubbed by this point, so this
# exercises the same import path production takes.
pdf_handler.delete_context(wdir, "Gone")
after = rh.load_history(wdir)
check("deleting a PDF drops its retention history — a same-named "
      "re-import can no longer inherit the old curve",
      "Gone" not in after)
check("the other PDFs' histories survive the delete",
      after == {"Stays": [["2026-08-30", 0.3]]})
check("the delete really ran (its context file is gone)",
      not os.path.isfile(os.path.join(wdir, "contexts", "Gone.txt")))

_orig_forget = rh.forget_history
rh.forget_history = _boom
_write(os.path.join(wdir, "contexts", "Stays.txt"), "text")
pdf_handler.delete_context(wdir, "Stays")
rh.forget_history = _orig_forget
check("a history-cleanup failure never blocks the delete itself",
      not os.path.isfile(os.path.join(wdir, "contexts", "Stays.txt")))
check("...the stale entry just stays behind instead of crashing",
      "Stays" in rh.load_history(wdir))

# ------------------------------------------------------ delete cleanup

section("forget_history — one key, no-ops, corrupt/missing tolerance")

ddir = os.path.join(tmp, "del")
rh.record_rows(
    ddir,
    [{"name": "Doomed", "retention": 0.6},
     {"name": "Keeper", "retention": 0.4}],
    today="2026-08-30",
)
rh.forget_history(ddir, "Doomed")
left = rh.load_history(ddir)
check("forget drops exactly the named PDF's series", "Doomed" not in left)
check("every other PDF's series survives untouched",
      left == {"Keeper": [["2026-08-30", 0.4]]})

calls = []
_orig_write = rh._atomic_write_json
rh._atomic_write_json = lambda p, o: calls.append(p) or _orig_write(p, o)
rh.forget_history(ddir, "Doomed")   # already gone
rh._atomic_write_json = _orig_write
check("forgetting a key that isn't there skips the write entirely", calls == [])
check("the surviving series is unchanged by that no-op",
      rh.load_history(ddir) == {"Keeper": [["2026-08-30", 0.4]]})

# A blank name is never a real PDF — record_rows refuses to create such a
# key, so forget refuses to consume one, even against a hand-edited file
# that does carry an empty key.
rh._atomic_write_json(
    rh._history_path(ddir),
    {"": [["2026-08-30", 0.1]], "Keeper": [["2026-08-30", 0.4]]},
)
rh.forget_history(ddir, "   ")
check("a blank/whitespace name is refused, never resolved to a real key",
      "" in rh.load_history(ddir))

missing = os.path.join(tmp, "nowhere")
check("forget on a dir with no history file is a silent no-op that "
      "creates nothing",
      rh.forget_history(missing, "Doomed") is None
      and not os.path.isdir(missing))

_write(rh._history_path(ddir), "{ not json")
rh.forget_history(ddir, "Doomed")  # must not raise
check("a corrupt history file is tolerated, and left for record_rows to "
      "recover rather than truncated here",
      open(rh._history_path(ddir), encoding="utf-8").read() == "{ not json")
check("no .tmp files left behind by forget's atomic write",
      [f for f in os.listdir(ddir) if f.endswith(".tmp")] == [])

section("delete wiring — pdf_handler.delete_context forgets the history")

wdir = os.path.join(tmp, "wired")
os.makedirs(os.path.join(wdir, "contexts"), exist_ok=True)
_write(os.path.join(wdir, "contexts", "Gone.txt"), "text")
rh.record_rows(
    wdir,
    [{"name": "Gone", "retention": 0.7}, {"name": "Stays", "retention": 0.3}],
    today="2026-08-30",
)
# The REAL lazy hop, not a stub: aqt is stubbed by this point, so this
# exercises the same import path production takes.
pdf_handler.delete_context(wdir, "Gone")
after = rh.load_history(wdir)
check("deleting a PDF drops its retention history — a same-named "
      "re-import can no longer inherit the old curve",
      "Gone" not in after)
check("the other PDFs' histories survive the delete",
      after == {"Stays": [["2026-08-30", 0.3]]})
check("the delete really ran (its context file is gone)",
      not os.path.isfile(os.path.join(wdir, "contexts", "Gone.txt")))

_orig_forget = rh.forget_history
rh.forget_history = _boom
_write(os.path.join(wdir, "contexts", "Stays.txt"), "text")
pdf_handler.delete_context(wdir, "Stays")
rh.forget_history = _orig_forget
check("a history-cleanup failure never blocks the delete itself",
      not os.path.isfile(os.path.join(wdir, "contexts", "Stays.txt")))
check("...the stale entry just stays behind instead of crashing",
      "Stays" in rh.load_history(wdir))

# ------------------------------------------------- dialog pins + smoke test

section("history dialog — exec ban, paint guard, signature (pins)")

check("K-114: no .exec( anywhere — the dialog is show()-only "
      "(pin reads code, not prose)",
      ".exec(" not in _RH_CODE and "dlg.show()" in _RH_CODE)

_tree = ast.parse(_RH_SRC)
_paints = [n for n in ast.walk(_tree)
           if isinstance(n, ast.FunctionDef) and n.name == "paintEvent"]


def _guarded(fn):
    """True when the paintEvent holds a Try whose FINALLY ends the
    painter — the K-115 guarantee (a live QPainter on an exception
    corrupts the backing store and segfaults the next flush)."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Try) and node.finalbody:
            for stmt in node.finalbody:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Attribute) and sub.attr == "end":
                        return True
    return False


check("K-115: exactly one paintEvent, guarded by try/finally painter.end()",
      len(_paints) == 1 and _guarded(_paints[0]))
check("open_history_dialog signature is the Library-agent contract",
      list(inspect.signature(rh.open_history_dialog).parameters)
      == ["parent", "safe_name", "display_name"])
check("chart colours come from theme.palette tokens, never invented hex",
      'QColor("#' not in _RH_SRC and "theme.palette(" in _RH_SRC)
check("dialog is parent-owned and deletes on close",
      "QDialog(parent)" in _RH_CODE and "WA_DeleteOnClose" in _RH_CODE)
check("the empty/single state carries the friendly first-run message",
      "History starts today" in _RH_SRC)

dlg = rh.open_history_dialog(None, "Lecture_1", "Lecture 1")
check("dialog builds under the stub harness (no exception path taken)",
      dlg is not None)

shutil.rmtree(tmp, ignore_errors=True)
raise SystemExit(report())
