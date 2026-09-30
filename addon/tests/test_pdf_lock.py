"""PDF reader 1/5: a per-PDF lock, and a bake that resolves its path late.

A Library rename/move/delete that lands while a bake is running used to
leave the bake writing to the OLD path (recreating a deleted file, or
forking a second copy). The bake now resolves the working path under
`pdf_lock(name)` just before its `os.replace`.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_lock.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import threading

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
sys.modules["klausmate"].get_config = lambda: {}
ph = importlib.import_module("klausmate.pdf_handler")


def make_world(tmp: str):
    """A Library root with one mapped two-page PDF and one saved highlight."""
    uf = os.path.join(tmp, "user_files")
    root = os.path.join(tmp, "Library")
    os.makedirs(uf)
    os.makedirs(root)
    w = ph.pypdf.PdfWriter()
    w.add_blank_page(width=612, height=792)
    w.add_blank_page(width=612, height=792)
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
    capture, or just before it creates its temp file), run `action` on
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
        class _Uuid:  # the bake draws its tmp name after every read it makes
            @staticmethod
            def uuid4():
                if sys._getframe(1).f_code.co_name == "bake_annotations":
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
        uf, lambda: ph.rename_mapped_file(uf, root, "Lecture", "Renamed")
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

section("a delete during the bake")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    ok, rep = bake_paused(uf, lambda: ph.delete_context(uf, "Lecture"))
    leftovers = [f for d, _, fs in os.walk(root) for f in fs]
    check("delete during bake writes nothing",
          ok is False and not os.path.exists(old) and leftovers == [],
          f"ok={ok} exists={os.path.exists(old)} leftovers={leftovers}")

with tempfile.TemporaryDirectory() as tmp:
    uf, root, old = make_world(tmp)
    ok, rep = bake_paused(uf, lambda: ph.delete_context(uf, "Lecture"), at="write")
    leftovers = [f for d, _, fs in os.walk(root) for f in fs]
    check("delete just before the write drops the bake and its temp file",
          ok is False and not os.path.exists(old) and leftovers == [],
          f"ok={ok} exists={os.path.exists(old)} leftovers={leftovers}")

raise SystemExit(report())
