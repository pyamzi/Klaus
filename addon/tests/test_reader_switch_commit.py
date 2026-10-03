"""GitHub #15: leaving a document commits the page's open editor first.

A text box, note or card editor typed in place is committed only on blur,
Escape, Cmd/Ctrl+Enter, or when Python asks (``commit_open_edit``). A
reader tab click takes no focus, so loading another document went straight
to ``load_path`` and the page's ``teardown()`` dropped the typing.

Every path that replaces the shown document now takes the reload-from-disk
shape: ``commit_open_edit(then)`` with the load (or the clear) inside
``then``. The commit must reach Python BEFORE ``load_annotations`` switches
the viewer to the new document: bridge messages carry no document id, so a
``text-add`` arriving after the switch would be minted into the NEW PDF.

A real offscreen ``PdfSidebar`` around a stand-in pdf.js viewer whose
annotation half is the real ``PdfJsViewer``'s (built with ``__new__``, no
webview), so the simulated ``text-add`` lands where the real one would.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_reader_switch_commit.py
"""
from __future__ import annotations

import base64
import importlib
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
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

TMP = tempfile.mkdtemp(prefix="klaus_switch_commit_")
UF = os.path.join(TMP, "user_files")
ROOT = os.path.join(TMP, "Library")
os.makedirs(UF)
os.makedirs(ROOT)
sys.modules["klaus_note"].USER_FILES = UF
try:
    importlib.import_module("klaus_note.settings").user_files_dir = UF
except Exception:
    pass

ph = importlib.import_module("klaus_note.pdf_handler")
ph._live_library_root = lambda: ROOT
src = importlib.import_module("klaus_note.pdf_source")
src.user_files_dir = lambda: UF
ds = importlib.import_module("klaus_note.doc_sync")
ds._sync = lambda: None
asv = importlib.import_module("klaus_note.annotation_save")
pj = importlib.import_module("klaus_note.pdfjs_viewer")
rp = importlib.import_module("klaus_note.reader_panel")


class FakePipe:
    def __init__(self):
        self.requests = []

    def request(self, name):
        self.requests.append(name)

    def flush(self, name=None, timeout=10.0):
        return True

    def forget(self, name):
        pass

    def subscribe(self, cb):
        return lambda: None


asv.pipeline = lambda: FakePipe()
rp.tooltip = lambda *a, **k: None
pj.tooltip = lambda *a, **k: None


class Web:
    def eval(self, js):
        pass

    def cleanup(self):
        pass


REAL_JS = pj.PdfJsViewer


class FakeJs(QtWidgets.QWidget):
    """PdfSidebar's view of the pdf.js viewer. ``commit_open_edit`` holds
    its continuation (``waiting``) until the test answers for the page.
    Annotations go through a real PdfJsViewer's annotation half."""

    def __init__(self, on_page_changed=None, parent=None):
        super().__init__(parent)
        self.calls = []
        self.waiting = None
        self.on_count = None
        self.on_stale = None
        r = REAL_JS.__new__(REAL_JS)
        r._web, r._page_loaded, r._unsub_save = Web(), True, None
        r._annotations_name, r._highlights, r._page_count = None, [], 8
        r._start_foreign_mirror = lambda name: None
        self.real = r

    def set_page_texts(self, pages):
        pass

    def load_path(self, path, name, keep_view=False):
        self.calls.append(("load_path", name))

    def load_annotations(self, name):
        self.calls.append(("load_annotations", name))
        REAL_JS.load_annotations(self.real, name)

    def clear_document(self):
        self.calls.append(("clear_document",))
        self.real._annotations_name, self.real._highlights = None, []

    def commit_open_edit(self, then):
        self.calls.append(("commit",))
        self.waiting = then

    def answer(self):
        """The page's edit-done reply: run the held continuation."""
        then, self.waiting = self.waiting, None
        if then is not None:
            then()

    def go_to_page(self, page):
        pass

    def cleanup(self):
        pass

    def type_box(self, text):
        """The page commits its open box: the bridge's text-add."""
        data = {"page": 0, "x": 72, "y": 72, "text": text, "color": "#e5484d",
                "size": 14, "w": 120, "h": 20}
        self.real._bridge_text_add(base64.b64encode(json.dumps(data).encode()).decode())


pj.PdfJsViewer, pj.PDFJS_AVAILABLE = FakeJs, True


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


os.makedirs(os.path.join(UF, "contexts"), exist_ok=True)
for doc in ("A", "B", "C"):
    make_pdf(os.path.join(UF, "pdfs", doc + ".pdf"))
    ph.save_annotations(UF, doc, [])
    with open(os.path.join(UF, "contexts", doc + ".json"), "w", encoding="utf-8") as f:
        json.dump({"pages": ["page %d" % i for i in range(8)]}, f)


def texts(doc):
    return [h.get("text") or h.get("note") for h in ph.load_annotations(UF, doc)]


def loads(v):
    return [c for c in v.calls if c[0] in ("load_path", "clear_document")]


sb = rp.PdfSidebar(None, host_key="lecture")
sb.tabs.set_tabs([], None)
v = sb._viewer
sb.resize(520, 420)
sb.show()
spin()

section("the first load (nothing on screen) needs no commit")
sb.load_pdf("A")
check("loads at once", sb.is_loaded("A") and v.calls[0] == ("load_path", "A"), str(v.calls))
check("...without asking the page to commit", ("commit",) not in v.calls, str(v.calls))

section("load_pdf to another document commits the open box first (#15)")
v.calls.clear()
sb.load_pdf("B")
check("asks the page to commit before anything else",
      v.calls[:1] == [("commit",)], str(v.calls))
check("...and loads nothing until the page answers",
      loads(v) == [] and sb._name == "A", f"{v.calls} {sb._name}")
v.type_box("typed on A")  # the commit's text-add, ahead of edit-done
check("the committed box is saved to A, the document it was typed on",
      texts("A") == ["typed on A"] and texts("B") == [], f"{texts('A')} {texts('B')}")
v.answer()
spin()
check("then B loads, with its own marks",
      loads(v) == [("load_path", "B")] and ("load_annotations", "B") in v.calls
      and sb._name == "B", str(v.calls))
check("A's box never reached B", texts("B") == [] and texts("A") == ["typed on A"])

section("a reader tab click: commit, then load, then the remembered page")
jumps: list = []
sb.jump_to_page = jumps.append
sb._last_page["A"] = 3
v.calls.clear()
sb.tabs.open("A")  # a click on A's tab is the same activated signal
spin()
check("asks for the commit, loads nothing yet",
      v.calls == [("commit",)] and sb._name == "B", str(v.calls))
check("...and does not jump on the document still shown", jumps == [], str(jumps))
v.answer()
spin()
check("A loads from the continuation", sb._name == "A" and loads(v) == [("load_path", "A")],
      str(v.calls))
check("...then returns to A's remembered page", jumps == [3], str(jumps))

section("re-selecting the shown tab neither commits nor reloads")
v.calls.clear()
sb.tabs.open("A")
spin()
check("no commit, no load", v.calls == [], str(v.calls))

section("going back to the shown tab before the page answers cancels the switch")
v.calls.clear()
sb.tabs.open("B")
spin()
held = v.waiting
check("B's switch is waiting on the commit", v.calls == [("commit",)] and held is not None)
sb.tabs.open("A")
spin()
v.answer()
spin()
check("A stays: B never loads", sb._name == "A" and loads(v) == [], f"{sb._name} {v.calls}")

section("a reload from disk while a switch is waiting does not swallow it")
v.calls.clear()
sb.tabs.open("B")
spin()
sb._on_viewer_stale()  # A changed on disk mid-switch: A is being left anyway
v.answer()
spin()
check("B loads", sb._name == "B" and loads(v) == [("load_path", "B")], str(v.calls))

section("closing the current tab: the neighbour loads after the commit")
sb.load_pdf("C")
v.answer()
spin()
check("C is shown among B and C", sb._name == "C" and sb.tabs.names()[-2:] == ["B", "C"],
      f"{sb._name} {sb.tabs.names()}")
v.calls.clear()
sb.tabs.close("C")
spin()
check("asks for the commit, nothing loads yet", v.calls == [("commit",)] and sb._name == "C",
      str(v.calls))
v.type_box("typed on C")
v.answer()
spin()
check("C's box is saved to C", texts("C") == ["typed on C"] and texts(sb._name) != ["typed on C"],
      f"{texts('C')} {sb._name}")
check("the neighbour loads", sb._name in sb.tabs.names() and loads(v) == [("load_path", sb._name)],
      str(v.calls))

section("closing the last tab: commit, then clear")
v.calls.clear()
for name in [n for n in sb.tabs.names() if n != sb._name]:
    sb.tabs.close(name)  # background tabs: no document change
spin()
last = sb._name
check("one tab left, still shown", sb.tabs.names() == [last] and ("commit",) not in v.calls,
      f"{sb.tabs.names()} {v.calls}")
before = texts(last)
v.calls.clear()
sb.tabs.close(last)
spin()
check("asks for the commit, clears nothing yet",
      v.calls == [("commit",)] and sb._name == last, str(v.calls))
v.type_box("typed on the last tab")
check("the box is saved to the closing document",
      texts(last) == before + ["typed on the last tab"], str(texts(last)))
v.answer()
spin()
check("then the reader clears", sb._name is None and loads(v) == [("clear_document",)],
      f"{sb._name} {v.calls}")

section("clear() itself stays immediate")
# clear() is the "document is going away" primitive: a Library delete
# (pdf_drive._close_in_panels, after the save pipeline forgot the PDF), the
# doc_sync "missing" handler (a bake would recreate the file at its old
# path) and the Lecture dock's shutdown. A commit there would write a box
# into a deleted or missing PDF's marks after its files are gone.
sb.load_pdf("A")
v.calls.clear()
sb.clear()
check("clears at once, no commit", v.calls == [("clear_document",)] and sb._name is None,
      str(v.calls))

sb.cleanup()
report()
