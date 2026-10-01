"""PDF reader final review: a bake never duplicates Klaus marks (C1), an
outside content change to an open PDF survives the next bake (I2), and an
outside save landing mid-bake is re-read, not overwritten (I3).

Real vendored pypdf on temp PDFs; doc_sync's classification is driven by
hand (no watcher).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_reader_final.py
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

TMP = tempfile.mkdtemp(prefix="klaus_reader_final_")
UF = os.path.join(TMP, "user_files")
ROOT = os.path.join(TMP, "Library")
os.makedirs(UF)
os.makedirs(ROOT)
importlib.import_module("klausmate.settings").user_files_dir = UF
ph = importlib.import_module("klausmate.pdf_handler")
ph._live_library_root = lambda: ROOT
ds = importlib.import_module("klausmate.doc_sync")
ds._sync = lambda: None  # no real watcher: classification is driven by hand
pypdf = ph.pypdf
from pypdf.annotations import Highlight as _Hl  # noqa: E402  (vendored, after install)
from pypdf.generic import ArrayObject, FloatObject  # noqa: E402

KLAUS = ph._KLAUS_NM


def make_pdf(path, pages=3, outside=False):
    """A blank PDF; with ``outside``, one unmarked /Highlight on page 0 (a
    mark made in Preview)."""
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    if outside:
        w.add_annotation(0, _Hl(
            rect=(300, 300, 400, 320),
            quad_points=ArrayObject(FloatObject(v) for v in (300, 320, 400, 320, 300, 300, 400, 300)),
            highlight_color="00ff00",
        ))
    with open(path, "wb") as f:
        w.write(f)


def counts(path):
    """(Klaus annotations, outside annotations, page count) in the file."""
    r = pypdf.PdfReader(path)
    klaus = outside = 0
    for pg in r.pages:
        for ref in pg.get("/Annots") or []:
            nm = str(ref.get_object().get("/NM") or "")
            if nm.startswith(KLAUS):
                klaus += 1
            else:
                outside += 1
    return klaus, outside, len(r.pages)


def add_outside_mark(path):
    """Preview saves an outside highlight on page 1 (same pages)."""
    w = pypdf.PdfWriter(clone_from=pypdf.PdfReader(path))
    w.add_annotation(1, _Hl(
        rect=(50, 50, 150, 70),
        quad_points=ArrayObject(FloatObject(v) for v in (50, 70, 150, 70, 50, 50, 150, 50)),
        highlight_color="0000ff",
    ))
    with open(path, "wb") as f:
        w.write(f)


MARK = {"id": "a1", "page": 0, "rects": [[100, 100, 200, 20]], "color": "#fadc50", "note": "why"}

section("C1: a dropped pristine never doubles Klaus marks")
DOC = os.path.join(ROOT, "Lecture.pdf")
make_pdf(DOC, outside=True)
ph.save_library_map(UF, {"Lecture": "Lecture.pdf"})
ph.save_annotations(UF, "Lecture", [MARK])
check("first bake", ph.bake_annotations(UF, "Lecture"))
check("one highlight + its :note sticky, the outside mark kept", counts(DOC)[:2] == (2, 1), str(counts(DOC)))
ph._drop_stale_original(UF, "Lecture")  # R16: the file changed outside, the pristine is stale
check("bake after the pristine is dropped", ph.bake_annotations(UF, "Lecture"))
check("still one Klaus highlight + sticky (no duplicate)", counts(DOC)[:2] == (2, 1), str(counts(DOC)))
ph._drop_stale_original(UF, "Lecture")
ph.save_annotations(UF, "Lecture", [])
check("un-bake after another drop", ph.bake_annotations(UF, "Lecture"))
check("no Klaus annotation remains, the outside mark is kept", counts(DOC)[:2] == (0, 1), str(counts(DOC)))
pristine = os.path.join(UF, "pdf_originals", "Lecture.pdf")
check("the recaptured pristine holds no Klaus mark", os.path.isfile(pristine) and counts(pristine)[0] == 0)

section("I2: an outside page delete on an open PDF survives the next bake")
DOC2 = os.path.join(ROOT, "Open.pdf")
make_pdf(DOC2, pages=3)
ph.save_library_map(UF, {"Lecture": "Lecture.pdf", "Open": "Open.pdf"})
ph.save_annotations(UF, "Open", [dict(MARK, id="b1", note="")])
check("bake before the edit", ph.bake_annotations(UF, "Open") and counts(DOC2) == (1, 0, 3), str(counts(DOC2)))
ds.open_doc("test", "Open", DOC2)
ds.pin_own_write("Open", ph.file_stat(DOC2))
w = pypdf.PdfWriter(clone_from=pypdf.PdfReader(DOC2))  # Preview deletes the last page
w.remove_page(2)
with open(DOC2, "wb") as f:
    w.write(f)
heard = []
_unsub = ds.subscribe(lambda ev, safe, path: heard.append((ev, safe)))
ds._settled("Open", ph.file_stat(DOC2))
_unsub()
check("doc_sync classified it 'changed'", heard == [("changed", "Open")], str(heard))
check("bake after the outside edit", ph.bake_annotations(UF, "Open"))
check("the page stays deleted, the Klaus mark is still there once", counts(DOC2) == (1, 0, 2), str(counts(DOC2)))
ds.close_doc("test", "Open")

section("I3: an outside save landing between the carry scan and the commit is re-read")
DOC3 = os.path.join(ROOT, "Race.pdf")
make_pdf(DOC3, pages=2)
ph.save_library_map(UF, {"Lecture": "Lecture.pdf", "Open": "Open.pdf", "Race": "Race.pdf"})
ph.save_annotations(UF, "Race", [dict(MARK, id="c1", note="")])
check("first bake", ph.bake_annotations(UF, "Race"))
_real_lock = ph.pdf_lock
saves = {"left": 1}


def racing_lock(safe):
    """The commit's lock: Preview saves just before the bake takes it."""
    @contextlib.contextmanager
    def cm():
        if safe == "Race" and saves["left"] > 0:
            saves["left"] -= 1
            add_outside_mark(DOC3)
        with _real_lock(safe):
            yield
    return cm()


ph.pdf_lock = racing_lock
ok = ph.bake_annotations(UF, "Race")
check("the bake re-reads the file and succeeds", ok)
check("the outside mark saved mid-bake survives, the Klaus mark too", counts(DOC3)[:2] == (1, 1), str(counts(DOC3)))
saves["left"] = 99  # Preview saves before every commit
ok = ph.bake_annotations(UF, "Race")
ph.pdf_lock = _real_lock
check("a file that keeps changing: one retry, then the bake is dropped", ok is False and saves["left"] == 97,
      f"{ok} {saves}")
check("...without overwriting it (every outside mark is still there)", counts(DOC3)[1] == 3, str(counts(DOC3)))

section("Round 2 (R53): an outside content save the settle has not reported is kept")


def pipe_bake(name):
    """A bake plus the pipeline's post-step: record the stat Klaus wrote."""
    rep = {}
    ok = ph.bake_annotations(UF, name, report=rep)
    if ok and rep.get("stat"):
        ph.record_stat(UF, name, rep["stat"])
    return ok


def delete_last(path):
    w = pypdf.PdfWriter(clone_from=pypdf.PdfReader(path))
    w.remove_page(len(w.pages) - 1)
    with open(path, "wb") as f:
        w.write(f)


DOC4 = os.path.join(ROOT, "Unsettled.pdf")
make_pdf(DOC4, pages=3)
ph.save_library_map(UF, dict(ph.load_library_map(UF), Unsettled="Unsettled.pdf"))
ph.save_annotations(UF, "Unsettled", [dict(MARK, id="d1", note="")])
check("bake (stat recorded)", pipe_bake("Unsettled") and counts(DOC4) == (1, 0, 3), str(counts(DOC4)))
delete_last(DOC4)  # Preview deletes a page; doc_sync has not settled yet
check("the next bake keeps the outside page delete", pipe_bake("Unsettled") and counts(DOC4) == (1, 0, 2),
      str(counts(DOC4)))
_pr4 = os.path.join(UF, "pdf_originals", "Unsettled.pdf")
_ino = os.stat(_pr4).st_ino
check("a bake of Klaus's own last write keeps the pristine", pipe_bake("Unsettled") and os.stat(_pr4).st_ino == _ino)

DOC5 = os.path.join(ROOT, "Unrecorded.pdf")
make_pdf(DOC5, pages=2)
ph.save_library_map(UF, dict(ph.load_library_map(UF), Unrecorded="Unrecorded.pdf"))
ph.save_annotations(UF, "Unrecorded", [dict(MARK, id="e1", note="")])
check("bake without a recorded stat", ph.bake_annotations(UF, "Unrecorded"))
_pr5 = os.path.join(UF, "pdf_originals", "Unrecorded.pdf")
_ino5 = os.stat(_pr5).st_ino
check("nothing recorded: the pristine is trusted (not re-captured)",
      ph.bake_annotations(UF, "Unrecorded") and os.stat(_pr5).st_ino == _ino5)

section("Round 2 (R53): a page delete landing between the carry scan and the commit is kept")
make_pdf(DOC4, pages=3)
ph._drop_stale_original(UF, "Unsettled")
check("reset to 3 pages", pipe_bake("Unsettled") and counts(DOC4) == (1, 0, 3), str(counts(DOC4)))
deletes = {"left": 1}


def deleting_lock(safe):
    @contextlib.contextmanager
    def cm():
        if safe == "Unsettled" and deletes["left"] > 0:
            deletes["left"] -= 1
            delete_last(DOC4)
        with _real_lock(safe):
            yield
    return cm()


ph.pdf_lock = deleting_lock
ok = pipe_bake("Unsettled")
ph.pdf_lock = _real_lock
check("the re-bake succeeds and the page stays deleted, the Klaus mark once",
      ok and counts(DOC4) == (1, 0, 2), f"{ok} {counts(DOC4)}")

raise SystemExit(report())
