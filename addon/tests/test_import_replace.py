"""#10: importing a PDF whose name is already in the Library never
destroys the existing file or its marks.

Default (and the prompt's Keep Both): a separate entry under a unique
file and safe name. Replace: the old file goes to the Trash (refused if
it cannot), the new one takes its place and starts with no marks. The
deck-screen drop asks per clashing file, in order.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_import_replace.py
"""
import importlib
import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

try:  # vendored pypdf needs typing_extensions (same shim as test_klaus_note)
    import typing_extensions  # noqa: F401
except ImportError:
    import typing as _typing

    class _TESub:
        def __getitem__(self, _i):
            return _typing.Any

        def __call__(self, *a, **k):
            return _typing.Any

    class _TEModule(types.ModuleType):
        def __getattr__(self, n):
            return getattr(_typing, n, _TESub())

    sys.modules["typing_extensions"] = _TEModule("typing_extensions")

ph = importlib.import_module("klaus_note.pdf_handler")
from pypdf import PdfWriter  # noqa: E402


def blank_pdf(path, pages=1):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        w.write(f)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def setup_marked():
    """Lecture_1 -> CourseA/Lecture 1.pdf with one baked native record."""
    uf = tempfile.mkdtemp(prefix="klaus_imp_uf_")
    root = tempfile.mkdtemp(prefix="klaus_imp_root_")
    src = tempfile.mkdtemp(prefix="klaus_imp_src_")
    os.makedirs(os.path.join(root, "CourseA"))
    ph._live_library_root = lambda: root  # what settings would answer
    first = os.path.join(src, "first", "Lecture 1.pdf")
    os.makedirs(os.path.dirname(first))
    blank_pdf(first)
    ph.extract_pages = lambda p: ["page text"]
    info = ph.save_pdf(uf, "Lecture 1", first, root=root)
    # Move it into CourseA the way the Library would.
    lib = os.path.join(root, "CourseA", "Lecture 1.pdf")
    shutil.move(os.path.join(root, "Lecture 1.pdf"), lib)
    ph.save_library_map(uf, {info["name"]: os.path.join("CourseA", "Lecture 1.pdf")})
    ph.save_annotations(uf, "Lecture_1", [{
        "id": "a" * 32, "page": 0, "rects": [[100.0, 100.0, 200.0, 12.0]],
        "color": "#fadc50", "note": "my note"}])
    rep = {}
    assert ph.bake_annotations(uf, "Lecture_1", rep), "bake failed"
    ph.mark_native_baked(uf, "Lecture_1", rep["native_ids"])
    if "stat" in rep:
        ph.record_stat(uf, "Lecture_1", rep["stat"])
    other = os.path.join(src, "other", "Lecture 1.pdf")
    os.makedirs(os.path.dirname(other))
    blank_pdf(other, pages=2)
    return uf, root, lib, other


def mirror(uf, name):
    return ph.mirror_foreign_annotations(
        uf, name, ph.scan_working_annotations(uf, name))


section("Keep Both (the default): a clash never touches the existing entry")
uf, root, lib, other = setup_marked()
try:
    before = read(lib)
    pristine = os.path.join(uf, "pdf_originals", "Lecture_1.pdf")
    check("pristine captured by the bake", os.path.isfile(pristine))
    check("name_in_library sees the clash",
          ph.name_in_library(uf, "Lecture 1") == "Lecture_1")
    check("...also for a name that sanitizes to it",
          ph.name_in_library(uf, "Lecture_1") == "Lecture_1")
    check("...and not for a new name", ph.name_in_library(uf, "Lecture 2") is None)
    info = ph.save_pdf(uf, "Lecture 1", other, root=root)
    mirror(uf, "Lecture_1")
    check("existing Library file's bytes are unchanged", read(lib) == before)
    check("its pristine original is still there", os.path.isfile(pristine))
    recs = ph.load_annotations(uf, "Lecture_1")
    check("its record survives the mirror",
          [r.get("note") for r in recs] == ["my note"], repr(recs))
    check("the import got its own safe name", info["name"] != "Lecture_1", repr(info))
    m = ph.load_library_map(uf)
    check("...and its own Library file",
          m.get("Lecture_1") == os.path.join("CourseA", "Lecture 1.pdf")
          and info["name"] in m and m[info["name"]] != m["Lecture_1"]
          and read(os.path.join(root, m[info["name"]])) == read(other), repr(m))
    check("...whose filename is reported for the display name",
          info.get("filename") == os.path.basename(m[info["name"]]), repr(info))
    info2 = ph.save_pdf(uf, "Lecture 1", other, root=root)
    m = ph.load_library_map(uf)
    check("a third copy at the root gets a suffixed file, distinct name",
          len({info["name"], info2["name"], "Lecture_1"}) == 3
          and info2["filename"] == "Lecture 1 (1).pdf", repr(info2))
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

section("Keep Both beside a sanitize-alike name never shares its tag (#14)")
uf = tempfile.mkdtemp(prefix="klaus_imp_uf_")
root = tempfile.mkdtemp(prefix="klaus_imp_root_")
src = tempfile.mkdtemp(prefix="klaus_imp_src_")
try:
    ph.extract_pages = lambda p: ["page text"]
    a, b = os.path.join(src, "Lecture 1.pdf"), os.path.join(src, "Lecture_1.pdf")
    blank_pdf(a)
    blank_pdf(b, pages=2)
    first = ph.save_pdf(uf, "Lecture 1", a, root=root)
    second = ph.save_pdf(uf, "Lecture_1", b, root=root)
    stems = [os.path.splitext(i["filename"])[0] for i in (first, second)]
    check("the two display names sanitize differently",
          ph._safe_basename(stems[0]) != ph._safe_basename(stems[1]), repr(stems))
    check("...and the first file is untouched", read(os.path.join(root, "Lecture 1.pdf")) == read(a))
finally:
    for d in (uf, root, src):
        shutil.rmtree(d, ignore_errors=True)

section("Replace: old file to the Trash, new file in place, no marks")
uf, root, lib, other = setup_marked()
try:
    trash = tempfile.mkdtemp(prefix="klaus_imp_trash_")
    trashed = []

    def to_trash(path):
        trashed.append(path)
        shutil.move(path, os.path.join(trash, os.path.basename(path)))
        return True

    old = read(lib)
    info = ph.save_pdf(uf, "Lecture 1", other, root=root, replace=to_trash)
    check("same safe name", info["name"] == "Lecture_1", repr(info))
    check("the old file went to the Trash",
          trashed == [lib] and read(os.path.join(trash, "Lecture 1.pdf")) == old)
    check("the new file sits at the same path", read(lib) == read(other))
    check("mapping unchanged",
          ph.load_library_map(uf) == {"Lecture_1": os.path.join("CourseA", "Lecture 1.pdf")})
    check("no stale pristine",
          not os.path.isfile(os.path.join(uf, "pdf_originals", "Lecture_1.pdf")))
    check("marks cleared", ph.load_annotations(uf, "Lecture_1") == [])
    check("baked-id ledger cleared", ph.load_baked_native(uf, "Lecture_1") == set())
    check("a mirror afterwards removes nothing and parks nothing",
          mirror(uf, "Lecture_1") == 0
          and ph.load_removed_native(uf, "Lecture_1") == [])
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

section("Replace refused when the Trash fails: nothing changes")
uf, root, lib, other = setup_marked()
try:
    old = read(lib)
    raised = False
    try:
        ph.save_pdf(uf, "Lecture 1", other, root=root, replace=lambda p: False)
    except OSError:
        raised = True
    check("save_pdf refuses", raised)
    check("old file intact", read(lib) == old)
    check("marks intact", len(ph.load_annotations(uf, "Lecture_1")) == 1)
    check("pristine intact",
          os.path.isfile(os.path.join(uf, "pdf_originals", "Lecture_1.pdf")))
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

section("no Library root: the legacy store is never overwritten either")
uf = tempfile.mkdtemp(prefix="klaus_imp_uf_")
src = tempfile.mkdtemp(prefix="klaus_imp_src_")
try:
    a = os.path.join(src, "Notes.pdf")
    blank_pdf(a)
    first = ph.save_pdf(uf, "Notes", a)
    legacy = os.path.join(uf, "pdfs", "Notes.pdf")
    before = read(legacy)
    blank_pdf(a, pages=3)
    second = ph.save_pdf(uf, "Notes", a)
    check("legacy file kept", read(legacy) == before)
    check("import kept beside it", second["name"] != first["name"]
          and os.path.isfile(os.path.join(uf, "pdfs", second["name"] + ".pdf")))
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(src, ignore_errors=True)

section("fix round 1: Replace refuses when the Library folder is unavailable")
uf, root, lib, other = setup_marked()
try:
    trashed = []
    msg = ""
    try:
        ph.save_pdf(uf, "Lecture 1", other, root=os.path.join(root, "unplugged"),
                    replace=lambda p: trashed.append(p))
    except ph.ReplaceRefused as e:
        msg = str(e)
    check("refused, saying the folder isn't available",
          "isn't available" in msg and "Lecture 1.pdf" in msg, repr(msg))
    check("nothing trashed, old file intact", trashed == [] and os.path.isfile(lib))
    check("marks and pristine intact",
          len(ph.load_annotations(uf, "Lecture_1")) == 1
          and os.path.isfile(os.path.join(uf, "pdf_originals", "Lecture_1.pdf")))
    check("nothing written to the legacy store",
          not os.path.isfile(os.path.join(uf, "pdfs", "Lecture_1.pdf")))
    check("mapping unchanged",
          ph.load_library_map(uf) == {"Lecture_1": os.path.join("CourseA", "Lecture 1.pdf")})
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

section("fix round 1: a failed copy leaves everything as it was")
uf, root, lib, other = setup_marked()
try:
    old = read(lib)
    trashed = []
    real_copy = ph.shutil.copy2

    def full_disk(s_, d, *a, **k):
        if os.path.abspath(d).startswith(os.path.abspath(root)):
            with open(d, "wb") as f:
                f.write(b"partial")
            raise OSError(28, "No space left on device")
        return real_copy(s_, d, *a, **k)

    ph.shutil.copy2 = full_disk
    raised = False
    try:
        ph.save_pdf(uf, "Lecture 1", other, root=root,
                    replace=lambda p: trashed.append(p))
    except OSError:
        raised = True
    finally:
        ph.shutil.copy2 = real_copy
    check("save_pdf raises", raised)
    check("nothing trashed, old bytes at the path", trashed == [] and read(lib) == old)
    check("marks and pristine intact",
          len(ph.load_annotations(uf, "Lecture_1")) == 1
          and os.path.isfile(os.path.join(uf, "pdf_originals", "Lecture_1.pdf")))
    leftovers = [n for _d, _s, fs in os.walk(root) for n in fs if n.endswith(".tmp")]
    check("no temp file left behind", leftovers == [], repr(leftovers))
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

section("fix round 1: Keep Both never maps two names to one file")
uf, root, lib, other = setup_marked()
try:
    # The clashing entry at the root top level, its file renamed in Finder.
    ph.save_library_map(uf, {"Lecture_1": "Lecture 1.pdf"})
    shutil.move(lib, os.path.join(root, "Renamed in Finder.pdf"))
    info = ph.save_pdf(uf, "Lecture 1", other, root=root)
    m = ph.load_library_map(uf)
    check("the new entry has its own relpath",
          m[info["name"]] != m["Lecture_1"], repr(m))
    mirror(uf, "Lecture_1")
    check("the old entry's records stay put",
          len(ph.load_annotations(uf, "Lecture_1")) == 1
          and ph.load_removed_native(uf, "Lecture_1") == [])
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

section("Replace clears the old document's index state, keeps its history")
uf, root, lib, other = setup_marked()
try:
    import json as _json

    pidx = importlib.import_module("klaus_note.pdf_index")
    idx = pidx.index_dir(uf, "Lecture_1")
    os.makedirs(idx)
    open(os.path.join(idx, "manifest.json"), "w").write("{}")
    pages_dir = os.path.join(uf, "pages", "Lecture_1", "abc")
    os.makedirs(pages_dir)
    with open(os.path.join(uf, "retention_history.json"), "w") as f:
        _json.dump({"Lecture_1": [["2026-10-01", 0.5]], "Other": [["2026-10-01", 0.7]]}, f)
    ph.save_pdf(uf, "Lecture 1", other, root=root, replace=lambda p: os.remove(p))
    check("page index gone", not os.path.exists(idx))
    check("page records gone", not os.path.exists(os.path.join(uf, "pages", "Lecture_1")))
    hist = _json.load(open(os.path.join(uf, "retention_history.json")))
    check("its retention history is KEPT (the tag's cards stay; it can't be rebuilt)",
          hist.get("Lecture_1") == [["2026-10-01", 0.5]] and "Other" in hist, repr(hist))
    ph.delete_context(uf, "Lecture_1", remove_file=lambda p: os.remove(p))
    hist = _json.load(open(os.path.join(uf, "retention_history.json")))
    check("a Library delete still clears it, others kept",
          "Lecture_1" not in hist and "Other" in hist, repr(hist))
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

section("replace_blocker answers before anything is touched")
uf, root, lib, other = setup_marked()
try:
    check("a reachable file: no blocker",
          ph.replace_blocker(uf, "Lecture 1", root) is None)
    check("an unavailable folder: the refusal message",
          "isn't available" in (ph.replace_blocker(uf, "Lecture 1", os.path.join(root, "gone")) or ""))
    os.remove(lib)
    check("a missing file: the refusal message",
          "isn't in your Library folder" in (ph.replace_blocker(uf, "Lecture 1", root) or ""))
finally:
    shutil.rmtree(uf, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

_init = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "klaus_note", "__init__.py"), encoding="utf-8").read()
_imp = _init.split("def import_pdf_file", 1)[1].split("\ndef ", 1)[0]
check("import_pdf_file forgets the pending bake only after save_pdf succeeds",
      _imp.index("save_pdf(") < _imp.index(".forget("))
_refused = _imp.split("except pdf_handler.ReplaceRefused", 1)[1].split("except Exception", 1)[0]
check("a refused Replace warns window-modally (show_warning, never the exec'ing showWarning)",
      "show_warning(" in _refused and "showWarning(" not in _refused, _refused)
check("...and closes open readers of the old file first (delete_pdf's rule)",
      "_close_in_panels(" in _imp and _imp.index("_close_in_panels(") < _imp.index("save_pdf("))
check("...but only once the old file is known reachable (a refusal keeps the reader tab)",
      "replace_blocker(" in _imp
      and _imp.index("replace_blocker(") < _imp.index("_close_in_panels("))

section("deck-screen drop: one answer per clashing file, in order")
pkg = sys.modules["klaus_note"]
dp = importlib.import_module("klaus_note.pdf_drop")
imported = []
pkg.import_pdf_file = lambda path, replace=False: imported.append((path, replace))
clashing = {"/x/A.pdf": "A.pdf", "/x/C.pdf": "C.pdf", "/x/D.pdf": "D.pdf"}
dp._clash_name = lambda path: clashing.get(path)
asked = []
pending = []


def ask(path, shown, answer):
    asked.append((path, shown))
    pending.append(answer)


deferred = []
dp.QTimer = types.SimpleNamespace(singleShot=lambda ms, fn: deferred.append(fn))
dp.mw = types.SimpleNamespace(col=object())


def tick():
    while deferred:
        deferred.pop(0)()


dp._import_pdfs(["/x/A.pdf", "/x/B.pdf", "/x/C.pdf", "/x/D.pdf"], ask=ask)
check("stops at the first clash and asks about it",
      asked == [("/x/A.pdf", "A.pdf")] and imported == [], repr((asked, imported)))
pending.pop(0)(dp.REPLACE)
check("the answer runs a tick later, after the box has closed",
      imported == [] and len(deferred) == 1, repr((imported, deferred)))
tick()
check("Replace imports it with replace, runs on to the next clash",
      imported == [("/x/A.pdf", True), ("/x/B.pdf", False)]
      and asked[-1] == ("/x/C.pdf", "C.pdf"), repr((asked, imported)))
pending.pop(0)(None)
tick()
check("Cancel imports nothing for that file, then asks the next",
      imported == [("/x/A.pdf", True), ("/x/B.pdf", False)]
      and asked[-1] == ("/x/D.pdf", "D.pdf"), repr((asked, imported)))
pending.pop(0)(dp.KEEP_BOTH)
tick()
check("Keep Both imports it beside the old one",
      imported[-1] == ("/x/D.pdf", False) and len(asked) == 3 and not pending)

asked.clear()
imported.clear()
dp._import_pdfs(["/x/A.pdf", "/x/C.pdf"], ask=ask)
dp.mw.col = None  # profile closed while the prompt was up
pending.pop(0)(dp.REPLACE)
tick()
check("a closed profile stops the chain: no import, no next prompt",
      imported == [] and len(asked) == 1 and not pending, repr((asked, imported)))

section("the prompt: window-modal open(), never exec()")
from PyQt6 import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
qt = types.ModuleType("aqt.qt")
for _m in (QtCore, QtWidgets):
    for _n in dir(_m):
        if not _n.startswith("_"):
            setattr(qt, _n, getattr(_m, _n))
sys.modules["aqt.qt"] = qt
answers = []
box = dp._ask_clash("/x/Lecture 1.pdf", "Lecture 1.pdf", answers.append, parent=None)
check("asks in plain words",
      box.text() == "“Lecture 1.pdf” is already in your Library.", box.text())
labels = [b.text() for b in box.buttons()]
check("Replace / Keep Both / Cancel",
      sorted(labels) == ["Cancel", "Keep Both", "Replace"], repr(labels))
check("Keep Both is the default", box.defaultButton().text() == "Keep Both")
check("shown, window-modal",
      box.isVisible() and box.windowModality() == QtCore.Qt.WindowModality.WindowModal)
next(b for b in box.buttons() if b.text() == "Replace").click()
app.processEvents()
check("a click answers through the signal", answers == [dp.REPLACE], repr(answers))
box2 = dp._ask_clash("/x/L.pdf", "L.pdf", answers.append, parent=None)
box2.reject()
app.processEvents()
check("Escape / close answers Cancel (None)", answers[-1] is None, repr(answers))
from PyQt6 import sip  # noqa: E402

_hooked = []
_prev_hook = sys.excepthook
sys.excepthook = lambda *a: _hooked.append(a)  # PyQt aborts on the default hook


def _boom(_choice):
    raise RuntimeError("answer failed")


box3 = dp._ask_clash("/x/M.pdf", "M.pdf", _boom, parent=None)
box3.reject()
app.processEvents()
QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
sys.excepthook = _prev_hook
check("the box is deleted even when the answer raises",
      _hooked and sip.isdeleted(box3), repr(_hooked))
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "klaus_note", "pdf_drop.py"), encoding="utf-8").read()
check("pdf_drop never execs a dialog", ".exec(" not in _src and "exec_(" not in _src)

raise SystemExit(report())
