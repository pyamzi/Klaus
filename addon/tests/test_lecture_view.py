"""K-119 lecture view: resolution core, targeted vector access, glue pins.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_lecture_view.py
"""

import ast
import glob
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from array import array

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import install, check, section, report  # noqa: E402

install()

card_index = importlib.import_module("klausmate.card_index")
pdf_index = importlib.import_module("klausmate.pdf_index")
pdf_handler = importlib.import_module("klausmate.pdf_handler")
lecture_view = importlib.import_module("klausmate.lecture_view")

LectureMatch = lecture_view.LectureMatch
NoLecture = lecture_view.NoLecture

# Boot state, captured before anything in this file can touch it. The
# setup-idempotency section far below asserts on this rather than on a
# live read, so reordering the file can never turn that pin vacuous.
_BOOT_SETUP_DONE = lecture_view._setup_done
_BOOT_DOCK = lecture_view._dock


def unit(vals):
    n = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / n for v in vals]


def flat(rows):
    a = array("f")
    for r in rows:
        a.extend(r)
    return a


def write_prefs(ufd, prefs):
    d = os.path.join(ufd, pdf_index.SUBDIR)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "prefs.json"), "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def write_ctx_json(ufd, safe, pages):
    d = os.path.join(ufd, "contexts")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, safe + ".json"), "w", encoding="utf-8") as f:
        json.dump({"pages": pages, "page_count": len(pages)}, f)


def write_ctx_txt(ufd, safe, text):
    d = os.path.join(ufd, "contexts")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, safe + ".txt"), "w", encoding="utf-8") as f:
        f.write(text)


def make_pdf_index(ufd, safe, chunks, rows, provider="p", model="m", dims=4):
    idx = pdf_index.PdfIndex(
        provider=provider,
        model=model,
        pdf_name=safe,
        dims=dims,
        source_sig=pdf_index.source_signature(ufd, safe) or (0, 0),
        chunks=list(chunks),
        embedded_rows=len(chunks),
        vectors=flat(rows),
    )
    pdf_index.save(idx, pdf_index.index_dir(ufd, safe))
    return idx


def make_card_index(ufd, nids, rows, skipped=None, provider="p", model="m", dims=4):
    ci = card_index.CardIndex(
        provider=provider,
        model=model,
        dims=dims,
        nids=list(nids),
        mods=[1] * len(nids),
        hashes=["h%d" % n for n in nids],
        skipped=dict(skipped or {}),
        vectors=flat(rows),
    )
    card_index.save(ci, os.path.join(ufd, lecture_view.CARD_INDEX_SUBDIR))
    return ci


# ---------------------------------------------------------------- fixtures

TMP = tempfile.mkdtemp(prefix="klaus_lecture_")


def fresh_ufd():
    d = tempfile.mkdtemp(dir=TMP)
    return d


# ------------------------------------------------------------ pure helpers

section("tag inversion + candidates")

prefs = {
    "PDF_A": {"tag": "!Library::Anatomy::A", "threshold": 0.7},
    "PDF_B": {"tag": "!Library::B"},
    "NoTag": {"threshold": 0.5},
    "Junk": "not-a-dict",
}
inv = lecture_view.tag_to_safe(prefs)
check("two tagged entries invert", len(inv) == 2)
check("keys are casefolded", "!library::anatomy::a" in inv)
check("threshold-only entry skipped", "NoTag" not in inv.values())
check(
    "exact tag resolves",
    lecture_view.candidates_for_tags(["!Library::B"], inv) == ["PDF_B"],
)
check(
    "case-insensitive hit",
    lecture_view.candidates_for_tags(["!LIBRARY::b"], inv) == ["PDF_B"],
)
check(
    "unrelated + marked tags ignored",
    lecture_view.candidates_for_tags(
        ["marked", "!Library::Other::Leaf"], inv
    )
    == [],
)
check(
    "order preserved, deduped",
    lecture_view.candidates_for_tags(
        ["!Library::B", "!Library::Anatomy::A", "!library::b"], inv
    )
    == ["PDF_B", "PDF_A"],
)

section("best_chunk argmax")

ufd = fresh_ufd()
write_ctx_json(ufd, "B", ["p1", "p2", "p3"])
idx_b = make_pdf_index(
    ufd,
    "B",
    chunks=[(1, 0, 2), (2, 0, 2), (7, 0, 2)],
    rows=[unit([0, 1, 0, 0]), unit([0.6, 0.8, 0, 0]), unit([1, 0, 0, 0])],
)
j, s = pdf_index.best_chunk(idx_b, unit([1, 0, 0, 0]))
check("argmax row found", j == 2)
check("argmax score is the dot", abs(s - 1.0) < 1e-6)
j2, s2 = pdf_index.best_chunk(idx_b, unit([0, 1, 0, 0]))
check("different query, different row", j2 == 0 and abs(s2 - 1.0) < 1e-6)
check(
    "empty index unusable",
    pdf_index.best_chunk(
        pdf_index.PdfIndex(provider="p", model="m", pdf_name="x", dims=4),
        unit([1, 0, 0, 0]),
    )
    == (-1, 0.0),
)
check(
    "dims mismatch unusable",
    pdf_index.best_chunk(idx_b, [1.0, 0.0]) == (-1, 0.0),
)

section("row map + targeted vector read")

ufd2 = fresh_ufd()
make_card_index(
    ufd2,
    nids=[10, 20, 30],
    rows=[unit([1, 0, 0, 0]), unit([0, 1, 0, 0]), unit([0, 0, 1, 0])],
    skipped={99: (1, "h99")},
)
cdir = os.path.join(ufd2, lecture_view.CARD_INDEX_SUBDIR)
rm = card_index.load_row_map(cdir)
check("row map loads", rm is not None)
check("every nid mapped", rm.rows == {10: 0, 20: 1, 30: 2})
check("skipped carried as set", rm.skipped == {99})
check("provider/model/dims carried", (rm.provider, rm.model, rm.dims) == ("p", "m", 4))
v2 = card_index.read_vector(cdir, 2, 4)
check("row 2 read exactly", v2 is not None and abs(v2[2] - 1.0) < 1e-6 and abs(v2[0]) < 1e-9)
check("past-end row is None", card_index.read_vector(cdir, 3, 4) is None)
check("negative row is None", card_index.read_vector(cdir, -1, 4) is None)
vec_path = os.path.join(cdir, card_index.VECTORS_FILE)
with open(vec_path, "r+b") as f:
    f.truncate(4 * 4 * 3 - 6)  # chop mid-row
check("truncated file is None", card_index.read_vector(cdir, 2, 4) is None)
bad = card_index.load_row_map(fresh_ufd())
check("missing manifest -> None", bad is None)
os.makedirs(os.path.join(TMP, "corrupt"), exist_ok=True)
with open(os.path.join(TMP, "corrupt", "manifest.json"), "w") as f:
    f.write("{nope")
check(
    "corrupt manifest -> None",
    card_index.load_row_map(os.path.join(TMP, "corrupt")) is None,
)

# ------------------------------------------------------- end-to-end resolve

section("resolve: end to end")

ufd3 = fresh_ufd()
write_prefs(
    ufd3,
    {
        "PDF_A": {"tag": "!Library::A"},
        "PDF_B": {"tag": "!Library::B"},
    },
)
write_ctx_json(ufd3, "PDF_A", ["a1", "a2"])
write_ctx_json(ufd3, "PDF_B", ["b"] * 8)
make_pdf_index(
    ufd3,
    "PDF_A",
    chunks=[(1, 0, 2)],
    rows=[unit([0.8, 0.6, 0, 0])],
)
make_pdf_index(
    ufd3,
    "PDF_B",
    chunks=[(1, 0, 2), (2, 0, 2), (7, 0, 2)],
    rows=[unit([0, 1, 0, 0]), unit([0.6, 0.8, 0, 0]), unit([1, 0, 0, 0])],
)
make_card_index(
    ufd3,
    nids=[100, 200, 300],
    rows=[unit([1, 0, 0, 0]), unit([0, 0, 0, 1]), unit([0, 1, 0, 0])],
    skipped={400: (1, "h")},
)
resolver = lecture_view.LectureResolver(ufd3)
both = ["!Library::A", "!Library::B"]
out = resolver.resolve(100, both)
check("match wins over both candidates", isinstance(out, LectureMatch))
check("winner is the closer PDF", out.safe == "PDF_B")
check("page is the argmax chunk's stored page", out.page == 7)
check("pages are known (json context)", out.pages_known is True)
check("fresh index is not stale", out.stale is False)
check("score carried", abs(out.score - 1.0) < 1e-6)

out_a = resolver.resolve(300, ["!Library::A"])
check(
    "single-candidate resolve hits it",
    isinstance(out_a, LectureMatch) and out_a.safe == "PDF_A" and out_a.page == 1,
)

section("resolve: every no-lecture reason")

check(
    "no tags",
    resolver.resolve(100, ["marked"]) == NoLecture(lecture_view.R_NO_TAGS),
)
check(
    "skipped nid = no vector",
    resolver.resolve(400, both) == NoLecture(lecture_view.R_NO_VECTOR),
)
check(
    "unknown nid = no vector",
    resolver.resolve(555, both) == NoLecture(lecture_view.R_NO_VECTOR),
)
check(
    "orthogonal vector = below floor",
    resolver.resolve(200, both) == NoLecture(lecture_view.R_BELOW_FLOOR),
)

ufd4 = fresh_ufd()
write_prefs(ufd4, {"PDF_A": {"tag": "!Library::A"}})
r4 = lecture_view.LectureResolver(ufd4)
check(
    "card manifest missing = no card index",
    r4.resolve(1, ["!Library::A"]) == NoLecture(lecture_view.R_NO_CARD_INDEX),
)
make_card_index(ufd4, nids=[1], rows=[unit([1, 0, 0, 0])])
r4.invalidate()
check(
    "candidate index dir missing = index unavailable",
    r4.resolve(1, ["!Library::A"])
    == NoLecture(lecture_view.R_INDEX_UNAVAILABLE),
)
write_ctx_json(ufd4, "PDF_A", ["x"])
make_pdf_index(
    ufd4, "PDF_A", chunks=[(1, 0, 1)], rows=[unit([1, 0, 0, 0])],
    provider="OTHER",
)
r4.invalidate()
check(
    "provider mismatch = index unavailable",
    r4.resolve(1, ["!Library::A"])
    == NoLecture(lecture_view.R_INDEX_UNAVAILABLE),
)

section("resolve: legacy pages + stale")

ufd5 = fresh_ufd()
write_prefs(ufd5, {"PDF_L": {"tag": "!Library::L"}})
write_ctx_txt(ufd5, "PDF_L", "one big blob")  # legacy: .txt only, no .json
make_pdf_index(ufd5, "PDF_L", chunks=[(1, 0, 4)], rows=[unit([1, 0, 0, 0])])
make_card_index(ufd5, nids=[1], rows=[unit([1, 0, 0, 0])])
r5 = lecture_view.LectureResolver(ufd5)
out5 = r5.resolve(1, ["!Library::L"])
check("legacy still matches", isinstance(out5, LectureMatch))
check("legacy pages unknown", out5.pages_known is False and out5.page == 0)

ufd6 = fresh_ufd()
write_prefs(ufd6, {"PDF_S": {"tag": "!Library::S"}})
write_ctx_json(ufd6, "PDF_S", ["p"])
make_pdf_index(ufd6, "PDF_S", chunks=[(1, 0, 1)], rows=[unit([1, 0, 0, 0])])
make_card_index(ufd6, nids=[1], rows=[unit([1, 0, 0, 0])])
r6 = lecture_view.LectureResolver(ufd6)
first = r6.resolve(1, ["!Library::S"])
check("pre-rewrite not stale", isinstance(first, LectureMatch) and first.stale is False)
write_ctx_json(ufd6, "PDF_S", ["p", "q", "r", "s"])  # size changes -> new sig
out6 = r6.resolve(1, ["!Library::S"])
check("context rewrite flips stale", isinstance(out6, LectureMatch) and out6.stale is True)

section("resolve: stamp-validated caching")

calls = {"n": 0}
orig_load = pdf_index.load


def counting_load(d):
    calls["n"] += 1
    return orig_load(d)


pdf_index.load = counting_load
try:
    r7 = lecture_view.LectureResolver(ufd3)
    a = r7.resolve(100, both)
    loads_first = calls["n"]
    b = r7.resolve(100, both)
    check("cache hit returns equal outcome", a == b)
    check("cache hit re-loads nothing", calls["n"] == loads_first)
    # Rewrite PDF_B's index so a different chunk (page 3) wins, and
    # bump its manifest stamp — the cached result must be recomputed.
    make_pdf_index(
        ufd3,
        "PDF_B",
        chunks=[(3, 0, 2)],
        rows=[unit([1, 0, 0, 0])],
    )
    man = os.path.join(pdf_index.index_dir(ufd3, "PDF_B"), pdf_index.MANIFEST_FILE)
    os.utime(man, (os.path.getmtime(man) + 5, os.path.getmtime(man) + 5))
    c = r7.resolve(100, both)
    check(
        "manifest drift recomputes",
        isinstance(c, LectureMatch) and c.page == 3,
    )
    # prefs drift: dropping PDF_B's tag removes the candidate.
    write_prefs(ufd3, {"PDF_A": {"tag": "!Library::A"}})
    d = r7.resolve(100, both)
    check(
        "prefs drift re-picks candidates",
        isinstance(d, LectureMatch) and d.safe == "PDF_A",
    )
finally:
    pdf_index.load = orig_load


section("invalidate(): the only way past a stamp-blind edit")
# CLAUDE.md: results are "revalidated by file stamps" — and a stamp is
# (int(mtime), size), so an edit that changes neither is invisible to
# every cache in the resolver. invalidate() is what the user-initiated
# open calls to be sure it is looking at the disk; gutting it changed
# nothing any check could see (K-139 mutation audit, finding 8).
#
# The scenario below is built so the pin CANNOT pass for the wrong
# reason: the rewrite is asserted to be the same size, its mtime is put
# back, and the pre-invalidate resolve is asserted to still return the
# stale answer. Only then does invalidate() have anything to prove.
_iv = fresh_ufd()
write_prefs(_iv, {"PDF_A": {"tag": "!Library::Z"}})
write_ctx_json(_iv, "PDF_A", ["a"])
write_ctx_json(_iv, "PDF_B", ["b"])
make_pdf_index(_iv, "PDF_A", chunks=[(1, 0, 1)], rows=[unit([1, 0, 0, 0])])
make_pdf_index(_iv, "PDF_B", chunks=[(9, 0, 1)], rows=[unit([1, 0, 0, 0])])
make_card_index(_iv, nids=[1], rows=[unit([1, 0, 0, 0])])
r_iv = lecture_view.LectureResolver(_iv)
_iv_first = r_iv.resolve(1, ["!Library::Z"])
check("fixture: the tag resolves to PDF_A page 1",
      isinstance(_iv_first, LectureMatch)
      and _iv_first.safe == "PDF_A" and _iv_first.page == 1)

_iv_prefs = lecture_view.prefs_path(_iv)
_iv_stat = os.stat(_iv_prefs)
write_prefs(_iv, {"PDF_B": {"tag": "!Library::Z"}})  # same key length
check("fixture: the rewrite is stamp-INVISIBLE (identical size, mtime "
      "restored) — without this the pin below would pass on the stamp "
      "check alone and prove nothing about invalidate()",
      os.stat(_iv_prefs).st_size == _iv_stat.st_size)
os.utime(_iv_prefs, (_iv_stat.st_atime, _iv_stat.st_mtime))
_iv_stale = r_iv.resolve(1, ["!Library::Z"])
check("a stamp-blind edit really does go unnoticed by the caches",
      isinstance(_iv_stale, LectureMatch) and _iv_stale.safe == "PDF_A")

r_iv.invalidate()
check("invalidate() drops EVERY sub-cache, not just the results one "
      "(prefs inverse, row map, index LRU and results all reset)",
      r_iv._idx_cache == {} and r_iv._results == {}
      and r_iv._rowmap is None and r_iv._prefs_stamp == ()
      and r_iv._rowmap_stamp == ())
_iv_fresh = r_iv.resolve(1, ["!Library::Z"])
check("so the next resolve reads disk again and follows the moved tag "
      "to PDF_B page 9 — this is the guarantee the user-initiated open "
      "relies on",
      isinstance(_iv_fresh, LectureMatch)
      and _iv_fresh.safe == "PDF_B" and _iv_fresh.page == 9)


section("dock open/width persistence (pdf_tabs.json's lecture_view key)")
# lecture_view_reopen is a user-visible feature whose entire storage
# layer was unwatched: both _saved_state and _save_state survived being
# gutted (K-139 finding 6). It is pure JSON over pdf_handler's merging
# tabs file, so it is fully testable here — against a temp user_files,
# never the real one.
_st_ufd = fresh_ufd()
_st_file = os.path.join(_st_ufd, pdf_handler._OPEN_TABS_FILE)
_orig_user_files = lecture_view._user_files
lecture_view._user_files = lambda: _st_ufd
try:
    check("no saved state yet reads as an empty dict, never None — the "
          "callers do state.update() on whatever comes back",
          lecture_view._saved_state() == {})

    lecture_view._save_state(open=True)
    check("open=True round-trips", lecture_view._saved_state() == {"open": True})
    with open(_st_file, encoding="utf-8") as _f:
        _raw = json.load(_f)
    check("it lands on disk under pdf_tabs.json's own lecture_view key, "
          "not at the top level",
          _raw["lecture_view"] == {"open": True})

    lecture_view._save_state(width=420)
    check("a second write MERGES rather than replaces — width and open "
          "are saved by different code paths and must coexist",
          lecture_view._saved_state() == {"open": True, "width": 420})
    lecture_view._save_state(open=False)
    check("closing rewrites only its own field",
          lecture_view._saved_state() == {"open": False, "width": 420})

    pdf_handler._save_tabs_file(_st_ufd, {"open": ["Lecture 1"]})
    lecture_view._save_state(open=True)
    check("the shared tabs file's OTHER keys survive our writes (every "
          "writer merges), and the top-level 'open' tab list is not the "
          "same key as the dock's own 'open' flag",
          pdf_handler._load_tabs_file(_st_ufd)["open"] == ["Lecture 1"]
          and lecture_view._saved_state() == {"open": True, "width": 420})

    pdf_handler._save_tabs_file(_st_ufd, {"lecture_view": "not a dict"})
    check("a corrupt lecture_view entry reads as no state, never a crash "
          "on the reviewer's hot path",
          lecture_view._saved_state() == {})
    with open(_st_file, "w", encoding="utf-8") as _f:
        _f.write("{ not json")
    check("an unreadable tabs file reads as no state either",
          lecture_view._saved_state() == {})

    # The toggle's own call site: closing the panel must persist open=False,
    # or lecture_view_reopen brings it back next session.
    class _FakeDock:
        def __init__(self):
            self.hidden = False
            self.saved_widths = 0

        def isVisible(self):
            return not self.hidden

        def save_width(self):
            self.saved_widths += 1

        def hide(self):
            self.hidden = True

    lecture_view._save_state(open=True)
    _fd = _FakeDock()
    lecture_view._dock = _fd
    lecture_view.toggle_lecture_view()
    check("toggling a visible panel closed hides it, banks its width, and "
          "persists open=False (the reopen feature's whole contract)",
          _fd.hidden is True and _fd.saved_widths == 1
          and lecture_view._saved_state().get("open") is False)
finally:
    lecture_view._user_files = _orig_user_files
    lecture_view._dock = _BOOT_DOCK


section("bridge contract (klausmate:lecture)")


class _RecTimer:
    """Records QTimer.singleShot instead of running it."""

    calls: list = []

    @staticmethod
    def singleShot(ms, fn):  # noqa: N802 — Qt naming
        _RecTimer.calls.append((ms, getattr(fn, "__name__", str(fn))))


_orig_qtimer = lecture_view.QTimer
lecture_view.QTimer = _RecTimer
try:
    check("a foreign message travels on UNCHANGED — the hook is a chain "
          "and __init__'s handler (and AnkiHub's) still get their turn",
          lecture_view._on_js_message(("sentinel", 1), "klausmate:settings",
                                      None)
          == ("sentinel", 1))
    check("the exact message reports HANDLED — returning False re-opens "
          "the pycmd to the rest of Anki's hook chain, which has no idea "
          "what it is",
          lecture_view._on_js_message((False, None), "klausmate:lecture",
                                      None)
          == (True, None))
    check("...and the toggle is DEFERRED off the bridge, never run inside "
          "the webchannel dispatch",
          _RecTimer.calls == [(0, "toggle_lecture_view")])
finally:
    lecture_view.QTimer = _orig_qtimer


# ------------------------------------------------------------- glue pins

section("glue pins (source)")

SRC_PATH = "klausmate/lecture_view.py"
with open(SRC_PATH, encoding="utf-8") as f:
    SRC = f.read()


def code_only(text):
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0]
        out.append(stripped)
    return "\n".join(out)


CODE = code_only(SRC)

for hook in (
    "webview_will_set_content.append",
    "webview_did_receive_js_message.append",
    "reviewer_did_show_question.append",
    "state_did_change.append",
    "state_shortcuts_will_change.append",
    "reviewer_will_show_context_menu.append",
    "profile_will_close.append",
    "aboutToQuit.connect",
):
    check("registers %s" % hook, hook in CODE)

check("bottom bar name-matched", '"ReviewerBottomBar"' in SRC)
check("button posts klausmate:lecture", 'pycmd("klausmate:lecture")' in SRC)
check("button id present", "klaus-lecture-btn" in SRC)
check("button sits beside More", "insertBefore(b, more)" in SRC)

# K-120. Anki centres the ease buttons inside the MIDDLE table cell, not the
# window — that cell is only window-centred while the two side cells are equal.
# Our button lives in the right cell, so without a matching pad on the left the
# whole answer row slides left, into AnkiHub's position:absolute "View on
# AnkiHub" button (which sits at its static position and cannot be pushed away).
# Geometry was verified in a Chromium harness against Anki 26.8.1's verbatim
# _bottomHTML + reviewer-bottom.css + AnkiHub's real injection; these pins hold
# the shape of the fix that harness measured.
check(
    "left cell is balanced with padding, not a spacer element",
    "paddingRight" in SRC or "padding-right" in SRC,
)
check(
    "balance is scoped to the OUTER table's first cell",
    "#innertable > tbody > tr > td.stat:first-child" in SRC,
)
check(
    "balance selector cannot reach the ease row's own cell",
    "#innertable td:first-child" not in SRC,
)
check("balance width is measured, never hardcoded", "offsetWidth" in SRC)
check(
    "balance is guarded by a computed min-width media query",
    "@media (min-width: " in SRC and "minw" in SRC,
)
check(
    "min-width threshold leaves room for the four ease buttons",
    "pad * 6" in SRC,
)
check("bridge matches the exact message", '"klausmate:lecture"' in CODE)
check("toggle deferred out of the bridge", "QTimer.singleShot(0, toggle_lecture_view)" in CODE)
check("no app-modal exec anywhere", ".exec()" not in CODE)
check("sidebar cleanup on the close path", "self.sidebar.cleanup()" in CODE)
check("jump defer idiom present", "QTimer.singleShot" in CODE)
check("shortcut only in review state", 'state != "review"' in CODE)
check("shortcut collision scan present", '"l" in taken' in CODE)
check("never activateWindow (focus stays on reviewer)", "activateWindow" not in CODE)
check(
    "no literal hex colours in code",
    re.search(r"#[0-9a-fA-F]{6}\b", CODE) is None,
)
check(
    "empty-state sentence is Pouya's, verbatim",
    lecture_view.NO_LECTURE_TEXT == "No lecture page available for this card.",
)
check("dock is right-area", "RightDockWidgetArea" in CODE)
check("state change hides outside review", "_dock.hide()" in CODE)

section("wiring pins")

with open("klausmate/__init__.py", encoding="utf-8") as f:
    INIT = f.read()
check(
    "setup wired in __init__ (guarded)",
    "from . import lecture_view as _lecture_view" in INIT
    and "_lecture_view.setup()" in INIT,
)
with open("klausmate/config.json", encoding="utf-8") as f:
    CONF = json.load(f)
check("config default present and true", CONF.get("lecture_view_reopen") is True)
with open("klausmate/config.md", encoding="utf-8") as f:
    check("config.md documents the key", "lecture_view_reopen" in f.read())

check("module has aqt-free/glue divider", "aqt glue" in SRC)
check("public toggle exists", callable(lecture_view.toggle_lecture_view))
check("public open exists", callable(lecture_view.open_lecture_view))
check("setup exists", callable(lecture_view.setup))


section("the card-index directory is spelled three times — they must agree")
# CARD_INDEX_SUBDIR is one of three INDEPENDENT copies of the same on-disk
# path (curation.INDEX_DIR, lecture_view.CARD_INDEX_SUBDIR,
# pdf_graph.CARD_INDEX_SUBDIR). Every fixture in this file builds its
# directory FROM the constant, so the constant defines both the code and
# the test and the two can never disagree — a self-referential pin, the
# K-135 shape (K-139 mutation audit, finding 7: even collapsing it to
# "MUT" survived). What is actually at risk is DRIFT between the copies:
# if one moves, the Lecture panel reads an empty directory and says "No
# lecture page available" forever, with a green suite. So compare the
# imported constant against the OTHER two modules' own literals.


def _module_str_const(path, name):
    """The last string literal in module-level `name = ...` of `path`.

    Parsed, not grepped: curation spells it inside an os.path.join(), and
    a regex over source text would also match the word in a comment.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name
                   for t in node.targets):
            continue
        strings = [n.value for n in ast.walk(node.value)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        return strings[-1] if strings else None
    return None


_cur_dir = _module_str_const("klausmate/curation.py", "INDEX_DIR")
_graph_dir = _module_str_const("klausmate/pdf_graph.py", "CARD_INDEX_SUBDIR")
check("all three copies are still there to be compared — a copy that "
      "vanishes must fail loudly, not quietly compare nothing",
      isinstance(_cur_dir, str) and _cur_dir
      and isinstance(_graph_dir, str) and _graph_dir
      and isinstance(lecture_view.CARD_INDEX_SUBDIR, str))
check("curation.INDEX_DIR, lecture_view.CARD_INDEX_SUBDIR and "
      "pdf_graph.CARD_INDEX_SUBDIR name the SAME directory — the writer, "
      "the reviewer's reader and the map's reader must not drift apart",
      lecture_view.CARD_INDEX_SUBDIR == _cur_dir == _graph_dir)


section("setup(): registers every hook, exactly once")
# The idempotency guard was unpinned in BOTH directions (K-139 finding 5):
# True at the top means setup() returns immediately and the whole Lecture
# panel silently does not exist; False at the end means every call
# re-registers the hooks and a card fires them N times over.
check("the guard boots OFF — a module that boots 'already set up' "
      "registers nothing and the panel silently never exists",
      _BOOT_SETUP_DONE is False)


class _FakeHookList:
    def __init__(self, log, name):
        self._log = log
        self._name = name

    def append(self, fn):
        self._log.append(self._name)


class _FakeHooks:
    def __init__(self, log):
        self._log = log

    def __getattr__(self, name):
        return _FakeHookList(self.__dict__["_log"], name)


class _FakeSignal:
    def __init__(self, log):
        self._log = log

    def connect(self, fn):
        self._log.append("aboutToQuit")


class _FakeMw:
    def __init__(self, log):
        self.app = type("_App", (), {"aboutToQuit": _FakeSignal(log)})()


_hook_log: list = []
_saved_glue = (lecture_view.gui_hooks, lecture_view.mw,
               lecture_view._setup_done)
try:
    lecture_view.gui_hooks = _FakeHooks(_hook_log)
    lecture_view.mw = _FakeMw(_hook_log)
    # Deliberately NOT reset: if the module booted with the guard already
    # latched, this first call must be seen to register nothing.
    lecture_view.setup()
    _first = list(_hook_log)
    check("one setup() registers all eight hooks the panel needs, in "
          "order",
          _first == [
              "webview_will_set_content",
              "webview_did_receive_js_message",
              "reviewer_did_show_question",
              "state_did_change",
              "state_shortcuts_will_change",
              "reviewer_will_show_context_menu",
              "profile_will_close",
              "aboutToQuit",
          ])
    check("the guard latches on the way out", lecture_view._setup_done is True)
    lecture_view.setup()
    check("a second setup() registers NOTHING more — Anki calls addon "
          "setup once per load, but a re-entrant one would double every "
          "hook for the rest of the session",
          _hook_log == _first)
finally:
    (lecture_view.gui_hooks, lecture_view.mw,
     lecture_view._setup_done) = _saved_glue

section("a partial Qt surface degrades the DOCK, not the whole module (K-161)")
# ``class LectureDock(QDockWidget)`` with ``QDockWidget = None`` in the
# import fallback is a hard TypeError AT IMPORT TIME — "NoneType takes no
# arguments" — so an environment whose aqt.qt is partial loses the
# resolver, the config keys and the hooks too, not just the panel it could
# not have drawn anyway. The guarded-import-with-None-fallback convention
# (PDF_VIEWER_AVAILABLE and friends) is correct for names used as VALUES
# and a trap for names used as BASE CLASSES. Found in
# index_queue._StatusDock first (K-152, where tests/test_drive.py's
# explicit aqt.qt stub reported the whole K-152 block as one opaque
# failure); this is the twin.
#
# Run in a SUBPROCESS, deliberately. The pin must swap aqt.qt for a
# namespace WITHOUT QDockWidget and re-import lecture_view; doing that in
# process would leave a differently-configured module in sys.modules for
# every section after it, and the boot-state pins at the top of this file
# would be reading a different module than they were captured from. A
# fresh interpreter is also where the defect actually lives: it is an
# import-time failure, so importing is the test.

_PARTIAL_QT_PROBE = r'''
import importlib, sys, types
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
import anki_stubs
anki_stubs.install()


class _Any:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()


# tests/test_drive.py's shape exactly: an EXPLICIT aqt.qt whose hand-listed
# names do not include QDockWidget. anki_stubs' own aqt.qt is PERMISSIVE
# (PEP 562 __getattr__ auto-vivifies every name), which is why this whole
# class of defect is invisible to the default bootstrap and why the pin
# builds its own stub rather than reusing it.
shim = types.ModuleType("aqt.qt")
for _n in ("QLabel", "QStackedWidget", "QTimer", "QVBoxLayout", "QWidget"):
    setattr(shim, _n, _Any)
shim.Qt = _Any()
sys.modules["aqt.qt"] = shim
sys.modules.pop("klausmate.lecture_view", None)

lv = importlib.import_module("klausmate.lecture_view")

# Importing is most of the point, but on its own it would also pass if the
# probe simply failed to reproduce a partial surface. So prove the module
# really did take the fallback, really did degrade the base, and really is
# still usable above the divider.
assert lv.QDockWidget is None, "probe did not reproduce a partial aqt.qt"
assert lv.LectureDock.__bases__ == (object,), lv.LectureDock.__bases__
assert lv._ensure_dock() is None, "dock build must refuse, not raise"
assert lv._dock is None, "a refused build must not latch a half-made dock"
assert callable(lv.LectureResolver), "the resolver must survive"
assert lv.CARD_INDEX_SUBDIR and lv.NO_LECTURE_TEXT
print("PROBE-OK")
'''

_probe = subprocess.run(
    [sys.executable, "-c", _PARTIAL_QT_PROBE],
    capture_output=True, text=True, cwd=os.getcwd(),
    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
)
check(
    "lecture_view IMPORTS under an aqt.qt with no QDockWidget — a partial "
    "Qt surface must cost the dock, not the resolver, the config keys and "
    "the hooks as well%s" % (
        "" if _probe.returncode == 0
        else "\n      probe stderr: " + _probe.stderr.strip().splitlines()[-1]
        if _probe.stderr.strip() else ""),
    _probe.returncode == 0 and "PROBE-OK" in _probe.stdout,
)


section("no OTHER module regrows the shape (K-161 sweep)")
# K-161 asked for a sweep "because if there are two there are probably
# three" — there are exactly three, and this is what stops a fourth. A
# base class is unusable after a failed guarded import when the handler
# either assigns it None (TypeError at class definition) or never rebinds
# it at all (NameError). klausmate/md3_switch.py is the pattern done right
# and must stay clear of this: it falls back to ``QCheckBox = object``.


def _guarded_bases(path):
    """(lineno, class, base, why) for every module-level ``class X(Base)``
    in `path` whose Base a failed guarded import would leave unusable.

    AST, not grep: the fallback is a chained ``a = b = c = None`` whose
    last name is the assignment VALUE rather than a target, which no
    regex over source text gets right.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    nulled, imported, rebound = set(), set(), set()
    for node in tree.body:
        if not isinstance(node, ast.Try):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Import, ast.ImportFrom)):
                for alias in sub.names:
                    imported.add(alias.asname or alias.name.split(".")[0])
        for handler in node.handlers:
            for sub in ast.walk(handler):
                if not isinstance(sub, ast.Assign):
                    continue
                names = [t.id for t in sub.targets if isinstance(t, ast.Name)]
                if isinstance(sub.value, ast.Name):
                    names.append(sub.value.id)  # a = b = c = None
                rebound.update(names)
                if isinstance(sub.value, ast.Constant) and sub.value.value is None:
                    nulled.update(names)
    unusable = nulled | (imported - rebound)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            root = base
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in unusable:
                found.append((node.lineno, node.name, ast.unparse(base),
                              "None" if root.id in nulled else "unbound"))
    return found


# EMPTY as of K-164, which fixed the one known survivor
# (klausmate/pdfjs_viewer.py, PdfJsViewer(QWidget)) — the entry was
# DELETED rather than joined by a second, because an allowlist that is
# allowed to grow is not a pin. The mechanism stays: an entry added here
# must name the card that owns it, and the stale-entry check below then
# makes that entry fail loudly the moment the defect is fixed.
_SWEEP_ALLOWED: dict = {}

_swept, _offenders = 0, []
for _path in sorted(glob.glob("klausmate/**/*.py", recursive=True)):
    _rel = _path.replace(os.sep, "/")
    if "/vendor/" in _rel:
        continue
    _swept += 1
    for _lineno, _cls, _base, _why in _guarded_bases(_path):
        if _rel in _SWEEP_ALLOWED:
            continue
        _offenders.append(f"{_rel}:{_lineno} class {_cls}({_base}) [{_why}]")

check("the sweep actually walked the package — an empty glob would make "
      "every finding below vacuously clean", _swept > 20)
check("md3_switch is the pattern done right and is swept: its fallback is "
      "``QCheckBox = object``, so it must NOT be reported",
      not any(f.startswith("klausmate/md3_switch.py") for f in _offenders))
check("lecture_view is no longer one of them",
      not any(f.startswith("klausmate/lecture_view.py") for f in _offenders))
check("pdfjs_viewer is no longer one of them either (K-164) — the third "
      "and last instance",
      not any(f.startswith("klausmate/pdfjs_viewer.py") for f in _offenders))
check("the allowlist is EMPTY, so the sweep below holds repo-wide with "
      "nothing excused from it (K-164 closed the last entry)",
      _SWEEP_ALLOWED == {})
check("no module outside the allowlist defines a class on a base a failed "
      "guarded import leaves unusable — found: %s" % (_offenders or "none"),
      _offenders == [])
for _bad, _card in sorted(_SWEEP_ALLOWED.items()):
    check("allowlisted %s still HAS the defect %s was filed for — a stale "
          "allowlist entry hides the next one" % (_bad, _card),
          bool(_guarded_bases(_bad)))


shutil.rmtree(TMP, ignore_errors=True)
raise SystemExit(report())
