"""The PDF library store under a Library move (#29, #28, #43).

#29  annotation/map JSON is fsynced before it is renamed into place.
#28  a bake that commits while the legacy->root migration copies its file
     keeps its marks (the migration holds pdf_lock per file).
#43  while a Library move runs, no other library_map.json writer runs:
     a rescan or import is refused with a tooltip, and no entry from
     either side is lost.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_library_move_guard.py
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

import klaus_note.settings as settings  # noqa: E402
ph = importlib.import_module("klaus_note.pdf_handler")
pdf_drive = importlib.import_module("klaus_note.pdf_drive")

NAMES = [f"lecture{i}" for i in range(4)]
MOVING = "KlausNote: the Library is moving; try again in a moment."
real_live_root = ph._live_library_root
real_save_map = ph.save_library_map


def world():
    """user_files with NAMES in the legacy pdfs/ store, and an empty root."""
    uf = tempfile.mkdtemp(prefix="klaus-g4-uf-")
    root = tempfile.mkdtemp(prefix="klaus-g4-root-")
    for sub in ("contexts", "pdfs"):
        os.makedirs(os.path.join(uf, sub))
    for n in NAMES:
        open(os.path.join(uf, "contexts", n + ".txt"), "w").write("ctx")
        open(os.path.join(uf, "pdfs", n + ".pdf"), "wb").write(b"%PDF-" + n.encode())
    settings.user_files_dir = uf
    settings.store = settings.DictStore({"library_root": root})
    return uf, root


def read(path):
    with open(path, "rb") as f:
        return f.read()


# ------------------------------------------------------------------ #29

section("#29: an annotations save fsyncs the tmp file before the rename")
uf, root = world()
events = []
real_fsync, real_replace = ph.os.fsync, ph.os.replace


def fake_fsync(fd):
    events.append(("fsync", os.fstat(fd).st_ino))
    return real_fsync(fd)


def fake_replace(src, dst):
    events.append(("replace", os.stat(src).st_ino))
    return real_replace(src, dst)


ph.os.fsync, ph.os.replace = fake_fsync, fake_replace
try:
    ph.save_annotations(uf, "lecture0", [{"id": "a1", "page": 0, "rects": [[1, 1, 2, 2]],
                                          "color": "#fadc50", "note": ""}])
finally:
    ph.os.fsync, ph.os.replace = real_fsync, real_replace
kinds = [k for k, _ in events]
check("fsync ran before the replace", "fsync" in kinds and "replace" in kinds
      and kinds.index("fsync") < kinds.index("replace"), str(events))
check("...on the very file that was renamed into place",
      "fsync" in kinds and "replace" in kinds
      and events[kinds.index("fsync")][1] == events[kinds.index("replace")][1], str(events))


def failing_fsync(_fd):
    raise OSError("disk gone")


target = os.path.join(uf, "library_map.json")
ph.save_library_map(uf, {"keep": "keep.pdf"})
ph.os.fsync = failing_fsync
try:
    raised = False
    try:
        ph.save_library_map(uf, {"new": "new.pdf"})
    except OSError:
        raised = True
finally:
    ph.os.fsync = real_fsync
check("a failed fsync raises like a failed write", raised)
check("...the target is untouched", ph.load_library_map(uf) == {"keep": "keep.pdf"})
check("...and no tmp file is left", [n for n in os.listdir(uf) if n.endswith(".tmp")] == [])

# ------------------------------------------------------------------ #28

section("#28: a bake committing mid-migration keeps its marks")
uf, root = world()
ph._live_library_root = lambda: root
safe = NAMES[0]
bake_done = threading.Event()


def bake():
    # What _commit_bake does: resolve the working path under pdf_lock,
    # then write the new bytes there.
    with ph.pdf_lock(safe):
        dest = ph._working_pdf_path(uf, safe, root)
        with open(dest, "wb") as f:
            f.write(b"%PDF-BAKED")
    bake_done.set()


baker = threading.Thread(target=bake)


def save_map_with_bake(uf_, mapping):
    if safe in mapping and not baker.is_alive() and not bake_done.is_set():
        baker.start()  # the bake lands between the copy and the map write
        baker.join(0.5)
    return real_save_map(uf_, mapping)


ph.save_library_map = save_map_with_bake
try:
    res = ph.migrate_to_root(uf, root, {})
finally:
    ph.save_library_map = real_save_map
baker.join(5)
mapped = ph.pdf_path_for(uf, safe, root)
check("the PDF moved", safe in res["moved"], str(res))
check("the mapped file holds the bake", mapped is not None and read(mapped) == b"%PDF-BAKED",
      repr(mapped and read(mapped)))
check("the legacy copy is gone", not os.path.exists(os.path.join(uf, "pdfs", safe + ".pdf")))

# ------------------------------------------------------------------ #43


class PausedMove:
    """A Library move running on its own thread, held just before its
    first map write until release()."""

    def __init__(self, uf, root, old_root=None):
        self.uf, self.root, self.old_root = uf, root, old_root
        self.paused, self.go = threading.Event(), threading.Event()
        self.result = None
        self.thread = threading.Thread(target=self._run)

    def _save(self, uf_, mapping):
        if threading.current_thread() is self.thread and not self.go.is_set():
            self.paused.set()
            self.go.wait(10)
        return real_save_map(uf_, mapping)

    def _run(self):
        self.result = ph.migrate_to_root(self.uf, self.root, {}, old_root=self.old_root)

    def __enter__(self):
        ph.save_library_map = self._save
        self.thread.start()
        check("(the move reached its first map write)", self.paused.wait(5))
        return self

    def release(self):
        self.go.set()
        self.thread.join(10)

    def __exit__(self, *_a):
        self.release()
        ph.save_library_map = real_save_map


tips = []
pdf_drive.tooltip = lambda msg, *a, **k: tips.append(msg)
pdf_drive.mw = None

section("#43: a rescan during a move is refused and loses nothing")
uf, root = world()
ph._live_library_root = lambda: root
with PausedMove(uf, root) as move:
    out = {}
    t = threading.Thread(target=lambda: out.update(summary=pdf_drive.rescan_library_root()))
    t.start()
    t.join(10)
    move.release()
check("the rescan was refused with the moving tooltip", MOVING in tips and out.get("summary") is None,
      f"tips={tips} out={out}")
mapping = ph.load_library_map(uf)
check("every PDF is mapped exactly once", sorted(mapping) == NAMES, str(mapping))
check("no duplicate copies in the root", sorted(os.listdir(root)) == sorted(n + ".pdf" for n in NAMES),
      str(os.listdir(root)))
paths = {n: ph.pdf_path_for(uf, n, root) for n in NAMES}
check("every PDF resolves under the root", all(p and p.startswith(root) for p in paths.values()), str(paths))
tips.clear()
check("after the move, a rescan runs again", isinstance(pdf_drive.rescan_library_root(), dict) and not tips)

section("#43: an import during a move is refused, nothing written")
uf, root = world()
ph._live_library_root = lambda: root
src = os.path.join(tempfile.mkdtemp(prefix="klaus-g4-src-"), "Fresh.pdf")
w = ph.pypdf.PdfWriter()
w.add_blank_page(width=612, height=792)
with open(src, "wb") as f:
    w.write(f)
with PausedMove(uf, root):
    err = None
    try:
        ph.save_pdf(uf, "Fresh", src, root=root)
    except Exception as exc:  # noqa: BLE001
        err = exc
check("save_pdf refuses with the moving message", err is not None and str(err) == MOVING, repr(err))
check("...as a ReplaceRefused, which import_pdf_file shows as is",
      isinstance(err, ph.ReplaceRefused), repr(err))
check("...and wrote nothing", "Fresh" not in ph.load_library_map(uf)
      and not os.path.exists(os.path.join(uf, "contexts", "Fresh.txt"))
      and "Fresh.pdf" not in os.listdir(root), str(os.listdir(root)))
check("the move's own entries all landed", sorted(ph.load_library_map(uf)) == NAMES)

section("#43: Library actions during a move write no map entry")
uf, root = world()
ph._live_library_root = lambda: root
ph.migrate_to_root(uf, root, {})  # all four live in the root now
os.makedirs(os.path.join(root, "Week 1"))
os.rename(os.path.join(root, "lecture1.pdf"), os.path.join(root, "Week 1", "lecture1.pdf"))
m = ph.load_library_map(uf)
m["lecture1"] = os.path.join("Week 1", "lecture1.pdf")
real_save_map(uf, m)
# A fresh legacy straggler for the paused move to work on.
open(os.path.join(uf, "contexts", "late.txt"), "w").write("ctx")
open(os.path.join(uf, "pdfs", "late.pdf"), "wb").write(b"%PDF-late")
with PausedMove(uf, root):
    renamed = ph.rename_mapped_file(uf, root, "lecture0", "Renamed")
    moved = ph.move_mapped_file(uf, root, "lecture2", "Week 1")
    folder = ph.rename_mapped_folder(uf, root, "Week 1", "Week 2")
check("rename/move/folder rename are no-ops while moving",
      renamed is None and moved is None and folder is False, f"{renamed} {moved} {folder}")
mapping = ph.load_library_map(uf)
check("the move's entry and every earlier one survive",
      sorted(mapping) == sorted(NAMES + ["late"]), str(mapping))
check("every PDF still resolves", all(ph.pdf_path_for(uf, n, root) for n in NAMES + ["late"]),
      str({n: ph.pdf_path_for(uf, n, root) for n in NAMES + ["late"]}))

section("#43: delete, folder rename and import surfaces refuse while moving")
uf, root = world()
ph._live_library_root = lambda: root
la = importlib.import_module("klaus_note.library_actions")
la_tips = []
la.tooltip = lambda msg, *a, **k: la_tips.append(msg)
called = []
real_delete_context = ph.delete_context
ph.delete_context = lambda *a, **k: called.append(a)
tips.clear()
os.makedirs(os.path.join(root, "A"))
with PausedMove(uf, root):
    deleted = pdf_drive.delete_pdf(NAMES[0])
    folder_ok, why = pdf_drive.apply_folder_change(uf, root, "A", "B")
    imported = la.import_files([src])
ph.delete_context = real_delete_context
check("delete_pdf is refused with the tooltip, nothing deleted",
      deleted is False and not called and MOVING in tips, f"{deleted} {called} {tips}")
check("a folder rename on disk is refused as 'moving'", (folder_ok, why) == (False, "moving"), f"{folder_ok} {why}")
check("import_files copies nothing and tells the user", imported == 0 and MOVING in la_tips
      and "Fresh.pdf" not in os.listdir(root), f"{imported} {la_tips} {os.listdir(root)}")

section("#43: a Replace is refused before any reader closes")
uf, root = world()
ph._live_library_root = lambda: root
ph.migrate_to_root(uf, root, {})
open(os.path.join(uf, "contexts", "late.txt"), "w").write("ctx")  # a straggler to move
open(os.path.join(uf, "pdfs", "late.pdf"), "wb").write(b"%PDF-late")
with PausedMove(uf, root):
    blocked = ph.replace_blocker(uf, NAMES[0], root)
check("replace_blocker says the Library is moving", blocked == MOVING, repr(blocked))
check("...and nothing blocks it once the move is done", ph.replace_blocker(uf, NAMES[0], root) is None)

section("a crash mid-copy never leaves a truncated file under the real name")
uf, root = world()
ph._live_library_root = lambda: root
real_copy = ph.shutil.copy2


class Crash(BaseException):
    pass


def crashing_copy(src, dst, *a, **k):
    with open(dst, "wb") as f:
        f.write(read(src)[:3])  # half written, then the process dies
    raise Crash()


ph.shutil.copy2 = crashing_copy
try:
    try:
        ph.migrate_to_root(uf, root, {})
    except Crash:
        pass
finally:
    ph.shutil.copy2 = real_copy
check("no visible file was left in the root", [n for n in os.listdir(root) if not n.startswith(".")] == [],
      str(os.listdir(root)))
ph.migrate_to_root(uf, root, {})
check("the next sweep moves every PDF whole, under its own name",
      sorted(n for n in os.listdir(root) if not n.startswith(".")) == sorted(n + ".pdf" for n in NAMES)
      and all(read(ph.pdf_path_for(uf, n, root)) == b"%PDF-" + n.encode() for n in NAMES),
      str(os.listdir(root)))

ph._live_library_root = real_live_root
raise SystemExit(report())
