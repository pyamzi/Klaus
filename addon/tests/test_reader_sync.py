"""PDF reader 1/5 (Task 6): open readers follow doc_sync.

A real offscreen ``PdfSidebar(None, host_key="lecture")`` built around a
stand-in pdf.js viewer (PdfJsViewer cannot be built headless: no
QtWebEngine), driven by doc_sync events: "changed" flushes, waits for an
open text box, reloads in place keeping page and zoom (the viewer re-reads
and mirrors the marks) and toasts "Updated from disk"; "moved" re-points
without a reload; "missing" closes the document with the exact copy and
leaves every mark and file alone (R33: a bulk Finder rename reports
"missing" and then "moved"). ``clear``/``cleanup`` flush before
``close_doc``. A load whose annotations JSON is newer than the PDF requests
one save. ``on_stale`` reloads silently. The old pollers are gone.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_reader_sync.py
"""
from __future__ import annotations

import base64
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
sys.modules["klaus_note"].USER_FILES = UF  # pre-settings layout
try:  # the settings seam, where it exists
    importlib.import_module("klaus_note.settings").user_files_dir = UF
except Exception:
    pass

ph = importlib.import_module("klaus_note.pdf_handler")
ph._live_library_root = lambda: ROOT
src = importlib.import_module("klaus_note.pdf_source")
src.user_files_dir = lambda: UF
store = importlib.import_module("klaus_note.drive_store")
ds = importlib.import_module("klaus_note.doc_sync")
ds._sync = lambda: None  # no real watcher: events are driven by hand
asv = importlib.import_module("klaus_note.annotation_save")
pj = importlib.import_module("klaus_note.pdfjs_viewer")
rp = importlib.import_module("klaus_note.reader_panel")
pdrive = importlib.import_module("klaus_note.pdf_drive")

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
rp.tooltip = lambda text, *a, **k: TIPS.append(text)


class FakeJs(QtWidgets.QWidget):
    """The pdf.js viewer's surface as PdfSidebar uses it. An open text box
    holds a reload until the page replies (``waiting``)."""

    def __init__(self, on_page_changed=None, parent=None):
        super().__init__(parent)
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

    def go_to_page(self, page):
        pass

    def clear_document(self):
        self.calls.append(("clear_document",))

    def cleanup(self):
        pass


REAL_JS = pj.PdfJsViewer
pj.PdfJsViewer, pj.PDFJS_AVAILABLE = FakeJs, True  # every reader builds the stand-in


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
plain = rp.PdfSidebar(None)
check("the default host is the editor dock", plain.host_key == "editor")
plain.cleanup()
sb = rp.PdfSidebar(None, host_key="lecture")
check("the Lecture dock's key is kept", sb.host_key == "lecture")
KEY = f"lecture:{id(sb)}"  # doc_sync registers each reader on its own (R36)
v = sb._viewer
check("the reader built the (stand-in) pdf.js viewer", isinstance(v, FakeJs))
lv_src = open(os.path.join(os.path.dirname(rp.__file__), "lecture_view.py"), encoding="utf-8").read()
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
check("...for this reader", ds._hosts.get("Doc") == {KEY}, str(ds._hosts))
check("the sidebar follows doc_sync events", sb._on_doc_event in ds._subs)
check("an up-to-date bake requests no save", PIPE.requests == [], str(PIPE.requests))

section('"changed": flush, wait for the open text box, reload in place, toast')
loads: list = []
_real_load = sb.load_pdf


def _counting_load(name):
    LOG.append(("load", name))
    loads.append(name)
    _real_load(name)


sb.load_pdf = _counting_load
LOG.clear()
v.calls.clear()
sb._on_doc_event("changed", "Doc", None)
check("flushes pending saves, then asks the page to commit its text box",
      LOG[:1] == [("flush", "Doc", False)] and v.calls == [("commit",)], f"{LOG} {v.calls}")
check("nothing reloads before the commit is done", TIPS == [] and v.waiting is not None)
v.waiting()
spin()
check("reloads the same file exactly once, in place, keeping page and zoom",
      [c for c in v.calls if c[0] == "load_path"] == [("load_path", DOC, "Doc", True)]
      and loads == [], f"{v.calls} {loads}")
check("...and re-reads the marks", v.calls[-1] == ("load_annotations", "Doc"), str(v.calls))
# The last link, on the real viewer: its load_annotations is what starts
# the outside-mark mirror (K-082), on every load and reload from disk.
_mstand = REAL_JS.__new__(REAL_JS)
_mirrored: list = []
_mstand._push_annotations = lambda: None
_mstand._start_foreign_mirror = _mirrored.append
REAL_JS.load_annotations(_mstand, "Doc")
check("...which, on the real PdfJsViewer, reads the JSON and starts the outside-mark mirror",
      _mirrored == ["Doc"] and [h.get("id") for h in _mstand._highlights] == ["m1"],
      f"{_mirrored} {_mstand._highlights}")
check('toasts exactly "Updated from disk"', TIPS == ["Updated from disk"], str(TIPS))
check("no save is requested", PIPE.requests == [], str(PIPE.requests))
loads.clear()
v.calls.clear()
del TIPS[:]
sb._on_doc_event("changed", "Other", None)
spin()
check("another document's change is ignored", loads == [] and TIPS == [] and v.calls == [])

section('"moved": re-point, no reload')
MOVED = os.path.join(ROOT, "Moved", "Doc.pdf")
os.makedirs(os.path.dirname(MOVED))
os.rename(DOC, MOVED)
ph.save_library_map(UF, {"Doc": "Moved/Doc.pdf"})
ds.repoint("Doc", MOVED)  # the rescan's call; reaches the sidebar as "moved"
spin()
check("doc_sync follows the move", ds.open_paths().get("Doc") == MOVED)
check("the sidebar's path follows it", sb._path == MOVED, str(sb._path))
check("no reload", loads == [] and ("load_path", MOVED, "Doc", True) not in v.calls, str(v.calls))
check("the viewer is re-pointed instead", v.calls[-1:] == [("repoint", MOVED)], str(v.calls))
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
      LOG == [("close_doc", KEY, "Doc")], str(LOG))
check("...so the pending save stays pending", "Doc" in PIPE.pending)
check("...and its tab closes (R50)", "Doc" not in sb.tabs.names(), str(sb.tabs.names()))
PIPE.pending.discard("Doc")
_now = tree(UF)
for _t in (before, _now):  # the closed tab is session state, not data
    _t.pop("pdf_tabs.json", None)
check("marks, annotations JSON, context and names untouched", _now == before)
FINAL = os.path.join(ROOT, "Renamed", "Doc.pdf")
os.makedirs(os.path.dirname(FINAL))
os.rename(GONE, FINAL)
ph.save_library_map(UF, {"Doc": "Renamed/Doc.pdf"})
ds.repoint("Doc", FINAL)  # the next scan: the same file, moved
spin()
check("a later \"moved\" for a closed document reloads nothing", loads == [], str(loads))
after = tree(UF)
for _t in (before, after):
    _t.pop("library_map.json", None)
    _t.pop("pdf_tabs.json", None)
check("...and still touches nothing but the map", after == before)
v.calls.clear()
sb.load_pdf("Doc")
spin()
check("re-opening finds the document", sb.is_loaded("Doc") and sb._path == FINAL)
_marks = ph.load_annotations(UF, "Doc")
check("...with every mark intact, read back by the viewer",
      [h.get("id") for h in _marks] == ["m1"] and _marks[0].get("note") == "keep me"
      and ("load_annotations", "Doc") in v.calls, f"{_marks} {v.calls}")
check("...and doc_sync follows the new path", ds.open_paths().get("Doc") == FINAL)
DOC = FINAL

section("clear and cleanup flush a pending save before close_doc")
PIPE.request("Doc")
PIPE.requests.clear()
LOG.clear()
sb.load_pdf = _real_load
sb.clear()
check("clear: flush (with the save pending) then close_doc",
      LOG[:2] == [("flush", "Doc", True), ("close_doc", KEY, "Doc")], str(LOG))
check("clear forgets the document", "Doc" not in ds.open_paths())
sb.load_pdf("Doc")
spin()
PIPE.request("Doc")
LOG.clear()
sb.cleanup()
check("cleanup: flush (with the save pending) then close_doc",
      LOG[:2] == [("flush", "Doc", True), ("close_doc", KEY, "Doc")], str(LOG))
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
check("the previous document is closed in doc_sync", ("close_doc", KEY, "Doc") in LOG, str(LOG))
check("the new one is open", "Two" in ds.open_paths() and "Doc" not in ds.open_paths())
sb.load_pdf("Doc")
spin()

section('"missing" closes its tab; a neighbour tab loads and stays (R50)')
m = rp.PdfSidebar(None, host_key="lecture")
mv = m._viewer
m.load_pdf("Two")
m.load_pdf("Doc")
spin()
check("two tabs, Doc showing", sorted(m.tabs.names()) == ["Doc", "Two"] and m._name == "Doc", str(m.tabs.names()))
mv.calls.clear()
del TIPS[:]
m._on_doc_event("missing", "Doc", None)
spin()
check("the missing PDF's tab is closed", m.tabs.names() == ["Two"], str(m.tabs.names()))
check("the neighbour is loaded, not cleared after",
      m._name == "Two" and mv.calls[-2:] == [("load_path", os.path.join(UF, "pdfs", "Two.pdf"), "Two", False),
                                             ("load_annotations", "Two")], str(mv.calls))
check("with the exact copy", TIPS == ["Doc Lecture was removed from your Library folder."], str(TIPS))
m.load_pdf("Doc")
spin()
mv.calls.clear()
m._on_doc_event("missing", "Two", None)
spin()
check("a background tab whose PDF went missing closes too", m.tabs.names() == ["Doc"], str(m.tabs.names()))
check("...and the PDF on screen stays", m._name == "Doc" and ("clear_document",) not in mv.calls, str(mv.calls))

section("a load with no stored file clears the viewer")
mv.calls.clear()
m.load_pdf("Nowhere")
check("the previous document is not left on screen",
      m._name is None and ("clear_document",) in mv.calls, str(mv.calls))
m.cleanup()

section("a JSON newer than the PDF requests one save on load")
age(DOC, 200)
os.utime(JSON, None)
PIPE.requests.clear()
sb.load_pdf("Doc")
spin()
check("one request", PIPE.requests == ["Doc"], str(PIPE.requests))
js = rp.PdfSidebar(None, host_key="lecture")
fake = js._viewer
PIPE.requests.clear()
js.load_pdf("Doc")
check("a second reader: one request", PIPE.requests == ["Doc"], str(PIPE.requests))
age(JSON, 400)
PIPE.requests.clear()
js.load_pdf("Doc")
sb.load_pdf("Doc")
spin()
check("JSON older than the PDF: no request", PIPE.requests == [], str(PIPE.requests))

section('a second reader: "changed" waits for its own text box, reloads keeping the view')
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

section("on_stale: the same reload, silently (R21)")
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
      fake.on_stale == js._on_viewer_stale
      and "on_stale = self._on_viewer_stale" in inspect.getsource(rp.PdfSidebar.__init__))

section('"moved" re-points the viewer')
fake.calls.clear()
js._on_doc_event("moved", "Doc", "/elsewhere/Doc.pdf")
check("viewer re-pointed, no reload", fake.calls == [("repoint", "/elsewhere/Doc.pdf")], str(fake.calls))
js._path = DOC

section("a commit reply after cleanup reloads nothing")
fake.calls.clear()
del TIPS[:]
js._on_doc_event("changed", "Doc", None)
late = fake.waiting
js.cleanup()
fake.calls.clear()
late()
check("no reload, no mirror, no toast for a closed panel", fake.calls == [] and TIPS == [],
      f"{fake.calls} {TIPS}")

section("a deleted sidebar lets go of doc_sync")
from PyQt6 import sip  # noqa: E402

dead = rp.PdfSidebar(None, host_key="lecture")
dead.load_pdf("Doc")
dead_key = dead._sync_key
check("subscribed while alive", dead._on_doc_event in ds._subs)
sip.delete(dead)
dead._on_doc_event("changed", "Doc", None)
check("the first event after deletion unsubscribes it", dead._on_doc_event not in ds._subs)
check("...and drops its registration", dead_key not in ds._hosts.get("Doc", set()), str(ds._hosts))

section("PdfJsViewer.repoint and commit_open_edit")
stand = REAL_JS.__new__(REAL_JS)
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

    def cleanup(self):
        pass


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
stand._page_loaded = True
stand._unsub_save = None
stand.commit_open_edit(lambda: done.append(4))
seq = stand._edit_seq
stand.cleanup()
stand._bridge_edit_done(str(seq))
spin()
check("cleanup drops a pending continuation", stand._after_edit is None and done == [1, 2, 3], str(done))
html = open(os.path.join(os.path.dirname(pj.__file__), "web", "pdfjs_viewer.html"), encoding="utf-8").read()
check("the page commits an open box, then replies on the same channel",
      "window.klausCommitEdit = function (seq) {\n"
      "  if (state.textEdit) commitTextEdit();\n"
      '  post("edit-done:" + seq);\n'
      "};" in html)

section("a second reader of one PDF never erases the first reader's marks (I1)")
pj.tooltip = lambda *a, **k: None
ph.save_annotations(UF, "Shared", [])


def reader_of(name):
    """A real PdfJsViewer's annotation half, without its webview."""
    r = REAL_JS.__new__(REAL_JS)
    r._web, r._page_loaded, r._unsub_save = Web(), True, None
    r._annotations_name = name
    r._highlights = ph.load_annotations(UF, name)
    return r


def mark(r, page):
    """The page's hl-add bridge call: one new highlight on ``page``."""
    data = {"pages": {str(page): [[72, 72, 100, 14]]}, "color": "#fadc50"}
    r._bridge_hl_add(base64.b64encode(json.dumps(data).encode()).decode())


ra, rb = reader_of("Shared"), reader_of("Shared")
mark(ra, 0)
pushes = len(ra._web.js)
for r in (ra, rb):  # the pipeline's "saved" reaches every reader
    r._on_save_event("saved", "Shared")
check("the reader that saved pushes nothing more", len(ra._web.js) == pushes, str(ra._web.js[pushes:]))
check("the other reader takes the new mark and pushes it",
      [h.get("page") for h in rb._highlights] == [0] and any("klausSetAnnotations" in j for j in rb._web.js),
      f"{rb._highlights} {rb._web.js}")
mark(rb, 1)
check("its own mark then keeps the first reader's",
      sorted(h.get("page") for h in ph.load_annotations(UF, "Shared")) == [0, 1],
      str(ph.load_annotations(UF, "Shared")))
pushes = len(rb._web.js)
rb._on_save_event("saved", "Other")
check("another document's save changes nothing", len(rb._web.js) == pushes)

section("a second reader's mark made before any 'saved' keeps the first reader's (R53 b)")
ph.save_annotations(UF, "Shared2", [])
ra, rb = reader_of("Shared2"), reader_of("Shared2")
mark(ra, 0)
mark(rb, 1)  # no pipeline event has reached rb yet
check("the JSON keeps both marks",
      sorted(h.get("page") for h in ph.load_annotations(UF, "Shared2")) == [0, 1],
      str(ph.load_annotations(UF, "Shared2")))
_mut = ("_bridge_hl_add", "_bridge_hl_remove", "_bridge_text_add", "_bridge_text_update", "_on_note_edited")
check("every mutating handler re-reads the marks once, through one helper",
      all(inspect.getsource(getattr(REAL_JS, n)).count("self._sync_marks()") == 1 for n in _mut),
      str([n for n in _mut if inspect.getsource(getattr(REAL_JS, n)).count("self._sync_marks()") != 1]))

section("a failed marks write keeps the marks in memory (R53 #2)")
ph.save_annotations(UF, "Failing", [])
rc = reader_of("Failing")
_jp = ph.annotations_path_for(UF, "Failing")
os.remove(_jp)
os.makedirs(_jp)  # writing the JSON now raises an OSError
check("save_annotations reports the failure", ph.save_annotations(UF, "Failing", []) is False)
PIPE.requests.clear()
mark(rc, 0)
check("the new mark stays in memory", [h.get("page") for h in rc._highlights] == [0], str(rc._highlights))
check("...and no bake is requested for a JSON that was not written", PIPE.requests == [], str(PIPE.requests))
mark(rc, 1)
check("a second mark while writes fail keeps the first",
      sorted(h.get("page") for h in rc._highlights) == [0, 1], str(rc._highlights))
os.rmdir(_jp)
mark(rc, 2)
check("once writes work again, every kept mark reaches the JSON",
      sorted(h.get("page") for h in ph.load_annotations(UF, "Failing")) == [0, 1, 2],
      str(ph.load_annotations(UF, "Failing")))
check("...and the bake is requested", PIPE.requests == ["Failing"], str(PIPE.requests))

section("an unreadable marks file never wipes the marks (R54)")
_lj = ph.annotations_path_for(UF, "Lock")
ph.save_annotations(UF, "Lock", [])
_strict = getattr(ph, "load_annotations_strict", lambda *a: "missing")
with open(_lj, "w") as _f:
    _f.write("{not json")
check("load_annotations_strict: unreadable is None", _strict(UF, "Lock") is None)
check("...a missing file is empty", _strict(UF, "NoSuchDoc") == [])
os.remove(_lj)  # save_annotations never writes over an unreadable file (R56)
ph.save_annotations(UF, "Lock", [])
check("...a good file is its marks", _strict(UF, "Lock") == [])
rl = reader_of("Lock")
mark(rl, 0)
mark(rl, 1)
os.chmod(_lj, 0)  # unreadable for the next read (a sync client or antivirus holds it)
_real_save = ph.save_annotations


def _readable_again(*a, **k):
    os.chmod(_lj, 0o644)
    return _real_save(*a, **k)


ph.save_annotations = _readable_again
try:
    mark(rl, 2)
finally:
    ph.save_annotations = _real_save
    os.chmod(_lj, 0o644)
check("the file keeps all three marks",
      sorted(h.get("page") for h in ph.load_annotations(UF, "Lock")) == [0, 1, 2],
      str(ph.load_annotations(UF, "Lock")))
check("save_annotations writes through a tmp file and a rename (never a truncated file)",
      "_atomic_write_json(" in inspect.getsource(ph.save_annotations))

section("a failed marks write says so (R54)")
_tips4 = []
pj.tooltip = lambda text, *a, **k: _tips4.append(text)
ph.save_annotations(UF, "Failing2", [])
rf = reader_of("Failing2")
_fj = ph.annotations_path_for(UF, "Failing2")
os.remove(_fj)
os.makedirs(_fj)
mark(rf, 0)
os.rmdir(_fj)
pj.tooltip = lambda *a, **k: None
check("the failure toasts the kept-and-will-retry copy", asv.SAVE_FAILED_COPY in _tips4, str(_tips4))

section("a PDF whose marks file is unreadable at open never has it written over (R56)")
_tips5 = []
pj.tooltip = lambda text, *a, **k: _tips5.append(text)
_cj = ph.annotations_path_for(UF, "Corrupt")
os.makedirs(os.path.dirname(_cj), exist_ok=True)
with open(_cj, "w") as _f:
    _f.write('{"highlights": [half')
with open(_cj, "rb") as _f:
    _cbytes = _f.read()
ro = REAL_JS.__new__(REAL_JS)
ro._web, ro._page_loaded, ro._unsub_save = Web(), True, None
ro._start_foreign_mirror = lambda name: None
REAL_JS.load_annotations(ro, "Corrupt")
check("the reader opens with nothing to show", ro._highlights == [], str(ro._highlights))
_UNREADABLE = "Klaus can't read this PDF's saved marks, so new marks won't be saved until that file is fixed or removed."
check("the exact unreadable-marks copy, defined once beside the save-failed copy",
      getattr(asv, "UNREADABLE_MARKS_COPY", None) == _UNREADABLE)
check("...and says so once, in those words", _tips5 == [_UNREADABLE], str(_tips5))
PIPE.requests.clear()
mark(ro, 0)
mark(ro, 1)
with open(_cj, "rb") as _f:
    check("marks made meanwhile never overwrite the unreadable file", _f.read() == _cbytes)
check("...they stay in memory", sorted(h.get("page") for h in ro._highlights) == [0, 1], str(ro._highlights))
check("...no bake is requested and no further toast", PIPE.requests == []
      and _tips5 == [_UNREADABLE], f"{PIPE.requests} {_tips5}")
_old = dict(MARK, id="old1", page=5, note="")
with open(_cj, "w") as _f:  # the sync client finishes: the file is whole again
    json.dump({"version": 1, "highlights": [_old]}, _f)
mark(ro, 2)
check("once it reads again, its marks and the ones made meanwhile are all kept",
      sorted(h.get("page") for h in ph.load_annotations(UF, "Corrupt")) == [0, 1, 2, 5],
      str(ph.load_annotations(UF, "Corrupt")))
check("...and the bake is requested", PIPE.requests == ["Corrupt"], str(PIPE.requests))
pj.tooltip = lambda *a, **k: None

section("opening an unreadable marks file shows only the unreadable notice, even when a bake fails (R58)")
_tips6 = []
pj.tooltip = lambda text, *a, **k: _tips6.append(text)
_c2 = os.path.join(ROOT, "Corrupt2.pdf")
make_pdf(_c2, pages=2)
age(_c2, 300)  # the marks JSON is newer than the PDF: opening it requests a bake
ph.save_library_map(UF, dict(ph.load_library_map(UF), Corrupt2="Corrupt2.pdf"))
_c2j = ph.annotations_path_for(UF, "Corrupt2")
with open(_c2j, "w") as _f:
    _f.write('{"highlights": [half')
_timers, _mainq = [], []
real_pipe = asv.SavePipeline(UF, _mainq.append, lambda n, ms, cb: _timers.append(cb), lambda n, st: None)
asv.pipeline = lambda: real_pipe
sx = rp.PdfSidebar(None, host_key="lecture")
rv = REAL_JS.__new__(REAL_JS)  # the real viewer's save half, on the real pipeline
rv._web, rv._page_loaded, rv._page_count = Web(), True, 0
rv._start_foreign_mirror = lambda name: None
rv.load_path = lambda *a, **k: None
rv._unsub_save = real_pipe.subscribe(rv._on_save_event)
sx._viewer = rv
sx.load_pdf("Corrupt2")
for _cb in list(_timers):
    _cb()
real_pipe.flush("Corrupt2", timeout=30)
check("the open-time bake request ran and failed", "Corrupt2" in real_pipe.failed_names())
check("only the unreadable-marks notice is shown", _tips6 == [asv.UNREADABLE_MARKS_COPY], str(_tips6))
del _timers[:]
real_pipe.retry("Corrupt2")  # what a doc_sync "back" or "moved" does
for _cb in list(_timers):
    _cb()
real_pipe.flush("Corrupt2", timeout=30)
check("...and a retry that fails again adds nothing", _tips6 == [asv.UNREADABLE_MARKS_COPY], str(_tips6))
rv._unsub_save()
sx._viewer = None
sx.cleanup()
asv.pipeline = lambda: PIPE
pj.tooltip = lambda *a, **k: None
check("doc_sync pops a pin in one step (a pin landing mid-check survives)",
      "_pins.get(" not in inspect.getsource(ds.classify) and "_pins.pop(" in inspect.getsource(ds.classify))

section("two readers in one host keep their own registration (R36)")
e1, e2 = rp.PdfSidebar(None), rp.PdfSidebar(None)
e1.load_pdf("Doc")
e2.load_pdf("Doc")
spin()
check("both editor readers are registered apart",
      {f"editor:{id(e1)}", f"editor:{id(e2)}"} <= ds._hosts.get("Doc", set()), str(ds._hosts))
e1.cleanup()
check("closing one keeps the other registered",
      "Doc" in ds.open_paths() and f"editor:{id(e2)}" in ds._hosts["Doc"]
      and f"editor:{id(e1)}" not in ds._hosts["Doc"], str(ds._hosts))
followed: list = []
_real_reload = e2._reload_from_disk
e2._reload_from_disk = lambda name, toast: (followed.append(name), _real_reload(name, toast))
e1_followed: list = []
e1._reload_from_disk = lambda name, toast: e1_followed.append(name)
t = time.time() + 5
os.utime(DOC, (t, t))  # an outside save: the fingerprint changes
ds._on_file_changed(DOC)  # what the watcher would deliver
deadline = time.monotonic() + 2
while not followed and time.monotonic() < deadline:
    spin(1)
    time.sleep(0.01)
spin()
check("the other still follows \"changed\"", followed == ["Doc"], str(followed))
check("the closed one does not", e1_followed == [], str(e1_followed))
e2.cleanup()

section("the old pollers are gone")
# The deleted names are pinned by the task's grep over klaus_note and tests,
# which must come back empty, so they are not spelled out here.
check("the Library watcher tick no longer polls open readers",
      "reader_panel" not in inspect.getsource(pdrive._on_fs_tick))
check("the sidebar keeps no file fingerprint of its own",
      "os.stat" not in inspect.getsource(rp.PdfSidebar))

sb.cleanup()
raise SystemExit(report())
