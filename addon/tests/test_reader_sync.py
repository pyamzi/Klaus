"""PDF reader 1/5 (Task 6): open readers follow doc_sync.

A real offscreen ``PdfSidebar(None, host_key="lecture")`` on the native
renderer, driven by doc_sync events: "changed" flushes, reloads in place
(keeping the scroll position), mirrors and toasts "Updated from disk";
"moved" re-points without a reload; "missing" closes the document with the
exact copy and leaves every mark and file alone (R33: a bulk Finder rename
reports "missing" and then "moved"). ``clear``/``cleanup`` flush before
``close_doc``. A load whose annotations JSON is newer than the PDF requests
one save. The old pollers are gone. The pdf.js-only paths (keep-view
reload, waiting for an open text box, ``on_stale``) run against a stand-in
viewer, since PdfJsViewer cannot be built headless.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_reader_sync.py
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import sys
import tempfile
import time
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")  # pristine output
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _qt_getattr(name):
    for module in (QtWidgets, QtCore, QtGui):
        if hasattr(module, name):
            return getattr(module, name)
    if name == "qconnect":
        return lambda signal, callback: signal.connect(callback)
    raise AttributeError(name)


shim.__getattr__ = _qt_getattr
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["klaus-test"])

TMP = tempfile.mkdtemp(prefix="klaus_reader_sync_")
UF = os.path.join(TMP, "user_files")
ROOT = os.path.join(TMP, "Library")
os.makedirs(UF)
os.makedirs(ROOT)
sys.modules["klausmate"].USER_FILES = UF  # pre-settings layout
try:  # the settings seam, where it exists
    importlib.import_module("klausmate.settings").user_files_dir = UF
except Exception:
    pass

ph = importlib.import_module("klausmate.pdf_handler")
ph._live_library_root = lambda: ROOT
src = importlib.import_module("klausmate.pdf_source")
src.user_files_dir = lambda: UF
store = importlib.import_module("klausmate.drive_store")
ds = importlib.import_module("klausmate.doc_sync")
ds._sync = lambda: None  # no real watcher: events are driven by hand
asv = importlib.import_module("klausmate.annotation_save")
pj = importlib.import_module("klausmate.pdfjs_viewer")
pj.renderer_from_config = lambda cfg: "native"
pv = importlib.import_module("klausmate.pdf_viewer")
pdrive = importlib.import_module("klausmate.pdf_drive")

LOG: list = []


class FakePipe:
    def __init__(self):
        self.requests = []
        self.pending = set()

    def request(self, name):
        self.requests.append(name)
        self.pending.add(name)

    def flush(self, name=None, timeout=10.0):
        LOG.append(("flush", name, name in self.pending))
        self.pending.discard(name)
        return True

    def subscribe(self, cb):
        return lambda: None


PIPE = FakePipe()
asv.pipeline = lambda: PIPE
_real_close = ds.close_doc


def _logged_close(host, safe):
    LOG.append(("close_doc", host, safe))
    _real_close(host, safe)


ds.close_doc = _logged_close
TIPS: list = []
pv.tooltip = lambda text, *a, **k: TIPS.append(text)
MIRRORS: list = []
pv.PdfViewer._start_foreign_mirror = lambda self, name: MIRRORS.append(name)


def spin(n=5):
    for _ in range(n):
        app.processEvents()


def make_pdf(path, pages=8):
    w = ph.pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def tree(top):
    """{relative path: sha1} of every file under ``top``."""
    out = {}
    for d, _dirs, files in os.walk(top):
        for fn in files:
            p = os.path.join(d, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, top)] = hashlib.sha1(f.read()).hexdigest()
    return out


# The Library: Doc.pdf mapped at the root, with marks, context and a name.
DOC = os.path.join(ROOT, "Doc.pdf")
make_pdf(DOC)
ph.save_library_map(UF, {"Doc": "Doc.pdf"})
store.record_import(UF, "Doc", "Doc Lecture")
MARK = {"id": "m1", "page": 1, "rects": [[72, 72, 100, 14]], "color": "#fadc50", "note": "keep me"}
ph.save_annotations(UF, "Doc", [MARK])
JSON = ph.annotations_path_for(UF, "Doc")
os.makedirs(os.path.join(UF, "contexts"), exist_ok=True)
with open(os.path.join(UF, "contexts", "Doc.json"), "w", encoding="utf-8") as f:
    json.dump({"pages": ["page %d" % i for i in range(8)]}, f)
with open(os.path.join(UF, "contexts", "Doc.txt"), "w", encoding="utf-8") as f:
    f.write("page text")
age(JSON, 100)  # an up-to-date bake: the PDF is newer than the JSON

section("host_key")
plain = pv.PdfSidebar(None)
check("the default host is the editor dock", plain.host_key == "editor")
plain.cleanup()
sb = pv.PdfSidebar(None, host_key="lecture")
check("the Lecture dock's key is kept", sb.host_key == "lecture")
check("native renderer under test", sb._renderer == "native" and sb._viewer is not None)
lv_src = open(os.path.join(os.path.dirname(pv.__file__), "lecture_view.py"), encoding="utf-8").read()
check("the Lecture dock passes host_key=\"lecture\"",
      'PdfSidebar(None, parent=body, host_key="lecture")' in lv_src)
sb.resize(520, 420)
sb.show()
spin()

section("load_pdf opens the document in doc_sync")
sb.load_pdf("Doc")
spin()
check("loaded", sb.is_loaded("Doc"))
check("doc_sync knows the path", ds.open_paths().get("Doc") == DOC, str(ds.open_paths()))
check("...for this host", ds._hosts.get("Doc") == {"lecture"}, str(ds._hosts))
check("the sidebar follows doc_sync events", sb._on_doc_event in ds._subs)
check("an up-to-date bake requests no save", PIPE.requests == [], str(PIPE.requests))

section('"changed": flush, reload in place, mirror, toast')
v = sb._viewer
v._pdf_view.verticalScrollBar().setValue(600)
spin()
pos = v.scroll_position()
check("scrolled down before the change", pos is not None and pos[0] > 0, str(pos))
loads: list = []
_real_load = sb.load_pdf


def _counting_load(name):
    LOG.append(("load", name))
    loads.append(name)
    _real_load(name)


sb.load_pdf = _counting_load
LOG.clear()
MIRRORS.clear()
sb._on_doc_event("changed", "Doc", None)
spin(10)
check("reloads exactly once", loads == ["Doc"], str(loads))
check("flushes pending saves before reloading", LOG[:2] == [("flush", "Doc", False), ("load", "Doc")], str(LOG))
check("keeps the reader's place", v.scroll_position() == pos, f"{v.scroll_position()} != {pos}")
check("runs the outside-mark mirror", MIRRORS == ["Doc"], str(MIRRORS))
check('toasts exactly "Updated from disk"', TIPS == ["Updated from disk"], str(TIPS))
check("no save is requested", PIPE.requests == [], str(PIPE.requests))
loads.clear()
del TIPS[:]
sb._on_doc_event("changed", "Other", None)
spin()
check("another document's change is ignored", loads == [] and TIPS == [])

section('"moved": re-point, no reload')
MOVED = os.path.join(ROOT, "Moved", "Doc.pdf")
os.makedirs(os.path.dirname(MOVED))
os.rename(DOC, MOVED)
ph.save_library_map(UF, {"Doc": "Moved/Doc.pdf"})
ds.repoint("Doc", MOVED)  # the rescan's call; reaches the sidebar as "moved"
spin()
check("doc_sync follows the move", ds.open_paths().get("Doc") == MOVED)
check("the sidebar's path follows it", sb._path == MOVED, str(sb._path))
check("no reload", loads == [], str(loads))
check("no toast", TIPS == [], str(TIPS))
check("still showing the document", sb.is_loaded("Doc"))

section('"missing" closes the document, keeps every mark (R33)')
before = tree(UF)
GONE = os.path.join(TMP, "Doc.pdf")  # mid bulk rename: not in the Library
os.rename(MOVED, GONE)
PIPE.request("Doc")  # a mark made just before the rename, still debouncing
PIPE.requests.clear()
LOG.clear()
ds.mark_missing("Doc")
spin()
check("the document is closed", sb._name is None and not sb.is_loaded())
check("with the exact copy, by display name",
      TIPS == ["Doc Lecture was removed from your Library folder."], str(TIPS))
check("doc_sync no longer holds it for this host", "Doc" not in ds.open_paths())
check("closed in doc_sync without a flush (a bake now would recreate the file at its old path)",
      LOG == [("close_doc", "lecture", "Doc")], str(LOG))
check("...so the pending save stays pending", "Doc" in PIPE.pending)
PIPE.pending.discard("Doc")
check("marks, annotations JSON, context and names untouched", tree(UF) == before)
FINAL = os.path.join(ROOT, "Renamed", "Doc.pdf")
os.makedirs(os.path.dirname(FINAL))
os.rename(GONE, FINAL)
ph.save_library_map(UF, {"Doc": "Renamed/Doc.pdf"})
ds.repoint("Doc", FINAL)  # the next scan: the same file, moved
spin()
check("a later \"moved\" for a closed document reloads nothing", loads == [], str(loads))
after = tree(UF)
after.pop("library_map.json", None)
before.pop("library_map.json", None)
check("...and still touches nothing but the map", after == before)
sb.load_pdf("Doc")
spin()
check("re-opening finds the document", sb.is_loaded("Doc") and sb._path == FINAL)
check("...with every mark intact", [h.get("id") for h in v._highlights] == ["m1"]
      and v._highlights[0].get("note") == "keep me", str(v._highlights))
check("...and doc_sync follows the new path", ds.open_paths().get("Doc") == FINAL)
DOC = FINAL

section("clear and cleanup flush a pending save before close_doc")
PIPE.request("Doc")
PIPE.requests.clear()
LOG.clear()
sb.load_pdf = _real_load
sb.clear()
check("clear: flush (with the save pending) then close_doc",
      LOG[:2] == [("flush", "Doc", True), ("close_doc", "lecture", "Doc")], str(LOG))
check("clear forgets the document", "Doc" not in ds.open_paths())
sb.load_pdf("Doc")
spin()
PIPE.request("Doc")
LOG.clear()
sb.cleanup()
check("cleanup: flush (with the save pending) then close_doc",
      LOG[:2] == [("flush", "Doc", True), ("close_doc", "lecture", "Doc")], str(LOG))
check("cleanup stops following doc_sync", sb._on_doc_event not in ds._subs)
LOG.clear()
sb.cleanup()
check("cleanup twice is safe and does nothing more", LOG == [], str(LOG))
sb.load_pdf("Doc")
check("a reused sidebar (profile switch) follows again, once",
      sum(1 for cb in ds._subs if cb == sb._on_doc_event) == 1)
check("...and re-opens in doc_sync", ds.open_paths().get("Doc") == DOC)

section("switching documents closes the previous one")
make_pdf(os.path.join(UF, "pdfs", "Two.pdf"), pages=2)
LOG.clear()
sb.load_pdf("Two")
spin()
check("the previous document is closed in doc_sync", ("close_doc", "lecture", "Doc") in LOG, str(LOG))
check("the new one is open", "Two" in ds.open_paths() and "Doc" not in ds.open_paths())
sb.load_pdf("Doc")
spin()

section("a JSON newer than the PDF requests one save on load")
age(DOC, 200)
os.utime(JSON, None)
PIPE.requests.clear()
sb.load_pdf("Doc")
spin()
check("native: one request", PIPE.requests == ["Doc"], str(PIPE.requests))


class FakeJs:
    """The pdf.js viewer's surface as PdfSidebar uses it."""

    def __init__(self):
        self.calls = []
        self.waiting = None
        self.on_count = None
        self.on_stale = None

    def set_page_texts(self, pages):
        pass

    def load_path(self, path, name, keep_view=False):
        self.calls.append(("load_path", path, name, keep_view))
        LOG.append(("load_path", keep_view))

    def load_annotations(self, name):
        self.calls.append(("load_annotations", name))

    def commit_open_edit(self, then):
        self.calls.append(("commit",))
        self.waiting = then

    def repoint(self, path):
        self.calls.append(("repoint", path))

    def scroll_position(self):
        return 0

    def clear_document(self):
        pass

    def cleanup(self):
        pass


js = pv.PdfSidebar(None, host_key="lecture")
js._renderer = "pdfjs"
js._doc = None
js._viewer = fake = FakeJs()
PIPE.requests.clear()
js.load_pdf("Doc")
check("pdf.js: one request", PIPE.requests == ["Doc"], str(PIPE.requests))
age(JSON, 400)
PIPE.requests.clear()
js.load_pdf("Doc")
sb.load_pdf("Doc")
spin()
check("JSON older than the PDF: no request", PIPE.requests == [], str(PIPE.requests))

section('pdf.js "changed": wait for the open text box, reload keeping the view')
fake.calls.clear()
LOG.clear()
del TIPS[:]
js._on_doc_event("changed", "Doc", None)
check("flushes, then asks the page to commit its text box",
      LOG[0][:2] == ("flush", "Doc") and fake.calls == [("commit",)], f"{LOG} {fake.calls}")
check("nothing reloads before the commit is done", TIPS == [] and fake.waiting is not None)
fake.waiting()
check("then reloads the same file keeping page and zoom",
      fake.calls[1:] == [("load_path", DOC, "Doc", True), ("load_annotations", "Doc")], str(fake.calls))
check('...and toasts "Updated from disk"', TIPS == ["Updated from disk"], str(TIPS))

section("pdf.js on_stale: the same reload, silently (R21)")
fake.calls.clear()
LOG.clear()
del TIPS[:]
js._on_viewer_stale()
fake.waiting()
check("flush, commit, keep-view reload",
      LOG[0][0] == "flush" and fake.calls == [("commit",), ("load_path", DOC, "Doc", True),
                                              ("load_annotations", "Doc")], f"{LOG} {fake.calls}")
check("no toast", TIPS == [], str(TIPS))
check("PdfSidebar points the pdf.js viewer's on_stale at it",
      "on_stale = self._on_viewer_stale" in inspect.getsource(pv.PdfSidebar.__init__))

section('pdf.js "moved" re-points the viewer')
fake.calls.clear()
js._on_doc_event("moved", "Doc", "/elsewhere/Doc.pdf")
check("viewer re-pointed, no reload", fake.calls == [("repoint", "/elsewhere/Doc.pdf")], str(fake.calls))
js._path = DOC
js._viewer = FakeJs()
js.cleanup()

section("PdfJsViewer.repoint and commit_open_edit")
stand = pj.PdfJsViewer.__new__(pj.PdfJsViewer)
A = os.path.join(TMP, "a.pdf")
B = os.path.join(TMP, "b.pdf")
make_pdf(A, pages=1)
stand._path = A
stand._source = src.DocSource(A)  # read live: the fallback path
os.rename(A, B)
stand.repoint(B)
check("the viewer's path follows", stand._path == B)
check("a live-read source keeps reading at the new path", stand._source.read(0, 5) == b"%PDF-")


class Web:
    def __init__(self):
        self.js = []

    def eval(self, js):
        self.js.append(js)


stand._web = Web()
stand._page_loaded = True
done: list = []
stand.commit_open_edit(lambda: done.append(1))
check("asks the page to commit", any("klausCommitEdit(" in j for j in stand._web.js), str(stand._web.js))
check("waits for the page", done == [])
seq = stand._edit_seq
stand._bridge_edit_done(str(seq - 1))
spin()
check("an older reply is ignored", done == [])
stand._bridge_edit_done(str(seq))
spin()
check("the page's reply continues, once", done == [1])
stand._bridge_edit_done(str(seq))
spin()
check("a repeated reply does nothing", done == [1])
pj.EDIT_COMMIT_WAIT_MS, _wait = 20, pj.EDIT_COMMIT_WAIT_MS
stand.commit_open_edit(lambda: done.append(2))
deadline = time.monotonic() + 2
while done == [1] and time.monotonic() < deadline:
    spin(1)
    time.sleep(0.01)
check("no reply: the backstop continues", done == [1, 2], str(done))
pj.EDIT_COMMIT_WAIT_MS = _wait
stand._page_loaded = False
stand.commit_open_edit(lambda: done.append(3))
check("no page: continues at once", done == [1, 2, 3], str(done))
html = open(os.path.join(os.path.dirname(pj.__file__), "web", "pdfjs_viewer.html"), encoding="utf-8").read()
check("the page commits an open box, then replies on the same channel",
      "window.klausCommitEdit = function (seq) {\n"
      "  if (state.textEdit) commitTextEdit();\n"
      '  post("edit-done:" + seq);\n'
      "};" in html)

section("the old pollers are gone")
# The deleted names are pinned by the task's grep over klausmate and tests,
# which must come back empty, so they are not spelled out here.
check("the Library watcher tick no longer polls open readers",
      "pdf_viewer" not in inspect.getsource(pdrive._on_fs_tick))
check("the sidebar keeps no file fingerprint of its own",
      "os.stat" not in inspect.getsource(pv.PdfSidebar))

sb.cleanup()
raise SystemExit(report())
