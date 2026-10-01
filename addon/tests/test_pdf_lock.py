"""PDF reader 1/5: a per-PDF lock, and a bake that resolves its path late.

A Library rename/move/delete that lands while a bake is running used to
leave the bake writing to the OLD path (recreating a deleted file, or
forking a second copy). The bake now resolves the working path under
`pdf_lock(name)` just before its `os.replace`.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_lock.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
ph = importlib.import_module("klausmate.pdf_handler")


def make_world(tmp: str, outside: bool = False):
    """A Library root with one mapped two-page PDF and (by default) one
    saved highlight. `outside` puts a non-Klaus highlight (like one drawn
    in Preview) into the file."""
    uf = os.path.join(tmp, "user_files")
    root = os.path.join(tmp, "Library")
    os.makedirs(uf)
    os.makedirs(root)
    w = ph.pypdf.PdfWriter()
    w.add_blank_page(width=612, height=792)
    w.add_blank_page(width=612, height=792)
    if outside:
        w.add_annotation(w.pages[0], ph._BakeHighlight(
            rect=(50, 50, 150, 70),
            quad_points=ph._BakeArray(ph._BakeFloat(v) for v in
                                      (50, 70, 150, 70, 50, 50, 150, 50)),
            highlight_color="ff0000", printing=True,
        ))
    path = os.path.join(root, "Lecture.pdf")
    with open(path, "wb") as f:
        w.write(f)
    ph.save_library_map(uf, {"Lecture": "Lecture.pdf"})
    ph._live_library_root = lambda: root
    ph.save_annotations(uf, "Lecture", [{
        "id": "a1", "page": 0, "rects": [[100, 100, 200, 20]],
        "color": "#fadc50", "note": "",
    }])
    return uf, root, path


def annots_in(path: str) -> int:
    reader = ph.pypdf.PdfReader(path)
    return sum(len(p.get("/Annots") or []) for p in reader.pages)


def bake_paused(uf: str, action, at: str = "capture"):
    """Run a bake that pauses mid-way (`at`: right after the pristine
    capture, or just before it creates its temp file, which is after the
    carry scan), run `action` on
    the main thread while it is paused, then let it finish.
    Returns (bake result, report dict)."""
    paused, release = threading.Event(), threading.Event()

    def pause():
        paused.set()
        release.wait(10)

    real_capture, real_uuid = ph._capture_pristine_stripped, ph.uuid
    if at == "capture":
        def slow(*args, **kw):
            ok = real_capture(*args, **kw)
            pause()
            return ok

        ph._capture_pristine_stripped = slow
    else:
        class _Uuid:  # the commit draws its tmp name after every read the bake makes
            @staticmethod
            def uuid4():
                if sys._getframe(1).f_code.co_name == "_commit_bake":
                    pause()
                return real_uuid.uuid4()

        ph.uuid = _Uuid
    out, rep = {}, {}
    try:
        t = threading.Thread(
            target=lambda: out.update(ok=ph.bake_annotations(uf, "Lecture", rep))
        )
        t.start()
        check("the bake is paused mid-way", paused.wait(10))
        action()
        release.set()
        t.join(10)
    finally:
        ph._capture_pristine_stripped, ph.uuid = real_capture, real_uuid
    return out.get("ok"), rep


section("file_stat and pdf_lock")
with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "a.pdf")
    with open(p, "wb") as f:
        f.write(b"12345")
    st = os.stat(p)
    check("file_stat is (ino, mtime_ns, size)",
          ph.file_stat(p) == (st.st_ino, st.st_mtime_ns, 5), str(ph.file_stat(p)))
    check("file_stat of missing path is None",
          ph.file_stat(os.path.join(tmp, "nope.pdf")) is None)

lock = ph.pdf_lock("x")
with lock:
    with ph.pdf_lock("x"):  # would deadlock if it were not re-entrant
        reentered = True
check("pdf_lock is re-entrant", reentered)
check("one lock per name", ph.pdf_lock("x") is lock and ph.pdf_lock("y") is not lock)

section("a rename during the bake")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    new = os.path.join(root, "Renamed.pdf")
    ok, rep = bake_paused(
        uf, lambda: ph.rename_mapped_file(uf, root, "Lecture", "Renamed"), at="write"
    )
    check("rename during bake lands on new path",
          ok is True and not os.path.exists(old) and os.path.isfile(new)
          and annots_in(new) == 1 and rep.get("path") == new,
          f"ok={ok} old={os.path.exists(old)} new={os.path.isfile(new)} rep={rep}")
    check("the report carries the new file's stat",
          rep.get("stat") == ph.file_stat(new), str(rep.get("stat")))

section("a folder rename during the bake")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    os.makedirs(os.path.join(root, "W1"))
    ph.move_mapped_file(uf, root, "Lecture", "W1")
    ok, rep = bake_paused(
        uf, lambda: ph.rename_mapped_folder(uf, root, "W1", "Week 1"), at="write"
    )
    new = os.path.join(root, "Week 1", "Lecture.pdf")
    check("folder rename during bake lands inside the renamed folder",
          ok is True and not os.path.exists(os.path.join(root, "W1"))
          and annots_in(new) == 1 and rep.get("path") == new, f"ok={ok} rep={rep}")
    check("no temp file is left behind",
          not [f for d, _, fs in os.walk(root) for f in fs if f.endswith(".tmp")])

section("a rename during the un-bake")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    # Baked once, then every record is deleted: the next bake is an un-bake.
    check("setup: the file carries one mark",
          ph.bake_annotations(uf, "Lecture") and annots_in(old) == 1)
    ph.save_annotations(uf, "Lecture", [])
    new = os.path.join(root, "Renamed.pdf")
    ok, rep = bake_paused(
        uf, lambda: ph.rename_mapped_file(uf, root, "Lecture", "Renamed"), at="write"
    )
    check("rename during un-bake lands on new path",
          ok is True and not os.path.exists(old) and os.path.isfile(new)
          and annots_in(new) == 0 and rep.get("path") == new
          and rep.get("stat") == ph.file_stat(new), f"ok={ok} {rep}")

section("outside marks survive a rename during the bake")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp, outside=True)
    new = os.path.join(root, "Renamed.pdf")
    ok, rep = bake_paused(
        uf, lambda: ph.rename_mapped_file(uf, root, "Lecture", "Renamed"), at="write"
    )
    check("a rename after the carry scan keeps the outside mark and adds ours",
          ok is True and annots_in(new) == 2 and not os.path.exists(old), f"ok={ok}")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp, outside=True)
    new = os.path.join(root, "Renamed.pdf")
    ok, rep = bake_paused(
        uf, lambda: ph.rename_mapped_file(uf, root, "Lecture", "Renamed")
    )
    check("a rename before the carry scan drops the bake, the file keeps the outside mark",
          ok is False and os.path.isfile(new) and annots_in(new) == 1
          and not [f for d, _, fs in os.walk(root) for f in fs if f.endswith(".tmp")],
          f"ok={ok} n={annots_in(new) if os.path.isfile(new) else None}")

section("a root with a trailing separator")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    os.makedirs(os.path.join(root, "W1"))
    ph.move_mapped_file(uf, root, "Lecture", "W1")
    ph._live_library_root = lambda: root + os.sep
    ok, rep = bake_paused(
        uf, lambda: ph.rename_mapped_folder(uf, root, "W1", "Week 1"), at="write"
    )
    new = os.path.join(root, "Week 1", "Lecture.pdf")
    check("the bake temp file still sits in the root",
          ok is True and annots_in(new) == 1, f"ok={ok} rep={rep}")

section("a delete during the bake")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    ok, rep = bake_paused(uf, lambda: ph.delete_context(uf, "Lecture"), at="write")
    leftovers = [f for d, _, fs in os.walk(root) for f in fs]
    check("delete during bake writes nothing",
          ok is False and not os.path.exists(old) and leftovers == [],
          f"ok={ok} exists={os.path.exists(old)} leftovers={leftovers}")

section("the file vanishes between the carry check and the reader open")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp, outside=True)
    real_reader, fired = ph.PdfReader, []

    def flaky(path, *a, **kw):  # the carry scan's open of the working file loses a rename race
        if (path == old and not fired
                and sys._getframe(1).f_code.co_name == "bake_annotations"):
            fired.append(1)
            raise FileNotFoundError(path)
        return real_reader(path, *a, **kw)

    ph.PdfReader = flaky
    try:
        ok = ph.bake_annotations(uf, "Lecture", {})
    finally:
        ph.PdfReader = real_reader
    check("a reader-open failure drops the bake, the file keeps the outside mark",
          fired and ok is False and annots_in(old) == 1
          and [h["id"] for h in ph.load_annotations(uf, "Lecture")] == ["a1"],
          f"fired={fired} ok={ok} n={annots_in(old)}")

section("no bake into a mapped file that is missing (R35)")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    assert ph.bake_annotations(uf, "Lecture", {})  # a pristine original now exists
    away = os.path.join(tmp, "Lecture.pdf")  # mid Finder rename: out of the Library
    os.rename(old, away)
    jpath = ph.annotations_path_for(uf, "Lecture")
    with open(jpath, "rb") as f:
        marks = f.read()
    rep = {}
    ok = ph.bake_annotations(uf, "Lecture", rep)
    check("the bake refuses, though a pristine original exists",
          ok is False and os.path.isfile(os.path.join(uf, "pdf_originals", "Lecture.pdf")))
    check("...and creates no file at the old path", not os.path.exists(old))
    check("...nor a temp file anywhere in the Library",
          [f for d, _, fs in os.walk(root) for f in fs] == [])
    check("...and reports no stat", "stat" not in rep)
    with open(jpath, "rb") as f:
        check("the marks JSON is untouched", f.read() == marks)
    ph.save_annotations(uf, "Lecture", [])
    check("an un-bake refuses too", ph.bake_annotations(uf, "Lecture", {}) is False
          and not os.path.exists(old))
    ph.save_annotations(uf, "Lecture", json.loads(marks)["highlights"])

    section("...and the save lands when the file comes back (\"back\" retries it)")
    asv = importlib.import_module("klausmate.annotation_save")
    ds = importlib.import_module("klausmate.doc_sync")
    ds._sync = lambda: None
    timers, events = [], []
    pipe = asv.SavePipeline(uf, lambda cb: cb(), lambda n, ms, cb: timers.append(cb),
                            lambda n, st: None)
    pipe.subscribe(lambda ev, n: events.append((ev, n)))
    subs_before = list(ds._subs)
    asv._wire_doc_sync(pipe)
    real_record = ph.record_stat
    ph.record_stat = lambda *a: None  # bookkeeping is not under test here
    try:
        pipe.request("Lecture")
        pipe.flush("Lecture")
        check("a request for the missing file fails visibly",
              events == [("failed", "Lecture")] and "Lecture" in pipe.failed_names(), str(events))
        check("...writes nothing at the old path", not os.path.exists(old))
        os.rename(away, old)
        ds.mark_back("Lecture", old)
        pipe.flush("Lecture")
        check("'back' retries and the bake succeeds",
              events[-1] == ("saved", "Lecture") and "Lecture" not in pipe.failed_names(), str(events))
        check("...with the mark in the file", annots_in(old) == 1)
    finally:
        ph.record_stat = real_record
        ds._subs[:] = subs_before

section("a save refused during a plain rename lands at the new path on \"moved\" (R38)")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    new = os.path.join(root, "Renamed.pdf")
    os.rename(old, new)  # renamed in Finder; the rescan has not run yet
    asv = importlib.import_module("klausmate.annotation_save")
    ds = importlib.import_module("klausmate.doc_sync")
    ds._sync = lambda: None
    events = []
    pipe = asv.SavePipeline(uf, lambda cb: cb(), lambda n, ms, cb: None, lambda n, st: None)
    pipe.subscribe(lambda ev, n: events.append((ev, n)))
    subs_before = list(ds._subs)
    asv._wire_doc_sync(pipe)
    real_record = ph.record_stat
    ph.record_stat = lambda *a: None
    try:
        pipe.request("Lecture")
        pipe.flush("Lecture")
        check("the save is refused while the map names the old path",
              events == [("failed", "Lecture")] and not os.path.exists(old), str(events))
        ph.save_library_map(uf, {"Lecture": "Renamed.pdf"})  # the rescan applies the move
        ds.repoint("Lecture", new)  # ...and tells readers: "moved"
        pipe.flush("Lecture")
        check("\"moved\" retries it and the save lands at the new path",
              events[-1] == ("saved", "Lecture") and annots_in(new) == 1
              and not os.path.exists(old), str(events))
    finally:
        ph.record_stat = real_record
        ds._subs[:] = subs_before

section("a bake that starts mid-rename carries the outside marks of the file it replaces")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp, outside=True)
    assert ph.bake_annotations(uf, "Lecture", {}) and annots_in(old) == 2
    new = os.path.join(root, "Renamed.pdf")
    os.rename(old, new)  # renamed in Finder; the map still names the old path
    ok, rep = bake_paused(
        uf, lambda: ph.save_library_map(uf, {"Lecture": "Renamed.pdf"}), at="write"
    )
    check("the bake re-reads the file it would replace: outside mark kept, ours added",
          ok is True and annots_in(new) == 2 and not os.path.exists(old),
          f"ok={ok} n={annots_in(new)}")
    check("...and reports the new path", rep.get("path") == new, str(rep.get("path")))

raise SystemExit(report())
