"""K-313 + Add tab: double-click a PDF in Browse's Library -> the ONE reader
(reader_host) is lent into Browse's central area in place of the cards; a
single click or Esc gives it back to its home (the Add tab's reader slot).
Spec: docs/superpowers/specs/2026-10-01-add-tab-design.md, "The reader".

Real PyQt6, offscreen: a QMainWindow shaped like Browse (central widget =
a QVBoxLayout holding ``form.splitter``, the sidebar dock on the left); a
second main window plays the Add page and holds the reader's home slot.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_library_viewer.py
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
from PyQt6 import QtCore, QtGui, QtWidgets, sip  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    if name == "sip":
        return sip
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
rh = importlib.import_module("klaus_note.reader_host")
lv = importlib.import_module("klaus_note.library_viewer")
ph = importlib.import_module("klaus_note.pdf_handler")
ph.touch_last_used = lambda uf, safe: None

L = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea


def pump():
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    for _ in range(3):
        app.processEvents()


class FakeReader(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__("reader", parent)
        self.loaded: list[str] = []
        self.cleaned = False

    def is_loaded(self, name=None):
        return bool(self.loaded) and (name is None or self.loaded[-1] == name)

    def load_pdf(self, name):
        self.loaded.append(name)

    def cleanup(self):
        self.cleaned = True


rh.make_reader = lambda parent: FakeReader(parent)


HOST = QtWidgets.QMainWindow()  # stands in for mw: Browse and the Add page both live under it
HOST.resize(1400, 800)
HOST.setCentralWidget(QtWidgets.QWidget())
QtWidgets.QHBoxLayout(HOST.centralWidget()).setContentsMargins(0, 0, 0, 0)
HOST.show()


def make_browser(top_level=False):
    """A hosted Browse (a child main window of HOST, as single_window builds
    it); ``top_level`` gives the stock, separate window of fallback mode."""
    if top_level:
        b = QtWidgets.QMainWindow()
    else:
        b = QtWidgets.QMainWindow(HOST.centralWidget(), QtCore.Qt.WindowType.Widget)
        b.setWindowFlags(QtCore.Qt.WindowType.Widget)  # QMainWindow's ctor ORs Window in; the shim clears it the same way
        HOST.centralWidget().layout().addWidget(b, 3)
    b.resize(1100, 700)
    central = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(central)
    splitter = QtWidgets.QSplitter()
    splitter.addWidget(QtWidgets.QTableView())
    splitter.addWidget(QtWidgets.QTextEdit())
    lay.addWidget(splitter)
    b.setCentralWidget(central)
    b.form = types.SimpleNamespace(splitter=splitter)
    side = QtWidgets.QDockWidget("sidebar")
    side.setWidget(QtWidgets.QTreeView())
    b.addDockWidget(L, side)
    b.sidebarDockWidget = side  # Browse's own attribute name
    b.editor = None
    b.show()
    app.processEvents()
    return b, side


def make_home():
    """The Add page's reader slot, under the same host as Browse."""
    slot = QtWidgets.QWidget()
    QtWidgets.QVBoxLayout(slot).setContentsMargins(0, 0, 0, 0)
    HOST.centralWidget().layout().addWidget(slot, 1)
    return slot


home = make_home()
rh.set_home(home)
r = rh.reader()
check("fixture: the reader lives in its home", r is not None and r.parent() is home)

section("double-click: the reader takes the cards' place, the Library stays")
b, side = make_browser()
check("sanity: cards showing", lv.cards_showing(b))
check("enter", lv.enter(b, "Intro_to_CBC"))
app.processEvents()
check("the splitter steps aside, the central widget stays",
      not lv.cards_showing(b) and b.centralWidget().isVisible())
check("the reader is lent into Browse",
      rh.reader().parent() is b._klaus_note_viewer_box and rh.borrowed()
      and b._klaus_note_viewer_box.parent() is b.centralWidget())
check("...with the PDF loaded", rh.reader().loaded == ["Intro_to_CBC"])
check("...filling the space", rh.reader().width() > 700, str(rh.reader().width()))
check("the Library sidebar stays", side.isVisible())
lv.enter(b, "Hemolysis")
check("double-clicking another PDF switches the reader to it", rh.reader().loaded == ["Intro_to_CBC", "Hemolysis"])

section("lend while the home is showing")
check("the Add slot shows only the 'Open in Browse' note while Browse holds the reader",
      rh.reader() not in [home.layout().itemAt(i).widget() for i in range(home.layout().count())]
      and rh.borrowed_note().isVisible() and rh.borrowed_note().text().startswith("Open in Browse"))

section("single click brings the cards back")
lv.on_sidebar_click(b)
check("the click that ends the double-click itself does not leave", lv.active(b))
getattr(b, lv.ATTR)["entered"] = time.monotonic() - 5
lv.on_sidebar_click(b)
app.processEvents()
check("a later single click leaves, the reader goes home",
      not lv.active(b) and lv.cards_showing(b) and rh.reader().parent() is home and not rh.borrowed())
check("…and the note is hidden again", not rh.borrowed_note().isVisible())
check("the viewer box is hidden, the splitter back", not b._klaus_note_viewer_box.isVisible() and b.form.splitter.isVisible())

section("Esc brings the cards back, and never closes Browse")
lv.enter(b, "Intro_to_CBC")
app.processEvents()
esc = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)
handled = b._klaus_note_viewer_filter.eventFilter(b, esc)
app.processEvents()
check("Esc is taken", handled and not lv.active(b) and lv.cards_showing(b) and b.isVisible() and rh.reader().parent() is home)
check("outside viewer mode Esc is Browse's again", not b._klaus_note_viewer_filter.eventFilter(b, esc))

section("closing Browse in viewer mode gives the reader back first")
lv.enter(b, "Intro_to_CBC")
app.processEvents()
b.close()
pump()
check("the reader is home and alive", rh.reader().parent() is home and not rh.reader().cleaned and not sip.isdeleted(rh.reader()))
check("Browse leaves viewer mode and shows the table for next time", not lv.active(b) and lv.cards_showing(b))

section("the sidebar keeps its width through viewer mode and back")
b5, side5 = make_browser()
b5.resizeDocks([side5], [260], QtCore.Qt.Orientation.Horizontal)
app.processEvents()
w0 = side5.width()
lv.enter(b5, "A")
app.processEvents()
w1 = side5.width()
lv.leave(b5)
app.processEvents()
w2 = side5.width()
check(f"sidebar {w0} -> {w1} (viewer) -> {w2} (cards)", abs(w1 - w0) <= 2 and abs(w2 - w0) <= 2)

section("a first open loads only the PDF that was double-clicked")
rh.reader().loaded.clear()
b6, _ = make_browser()
lv.enter(b6, "Hemolysis")
app.processEvents()
check("only the double-clicked PDF loads", rh.reader().loaded == ["Hemolysis"], str(rh.reader().loaded))
lv.enter(b6, "Hemolysis")
check("entering the same PDF again does not reload it", rh.reader().loaded == ["Hemolysis"])
lv.leave(b6)

section("fallback: no home — the reader is built under Browse and dies with it")
rh.set_home(None)
rh.release()
b2, _ = make_browser(top_level=True)
check("enter with no reader anywhere still works", lv.enter(b2, "Hemolysis"))
r2 = rh.reader()
check("built under Browse's box", r2 is not None and r2.parent() is b2._klaus_note_viewer_box and r2.loaded == ["Hemolysis"])
lv.leave(b2)
app.processEvents()
check("leave keeps it there, hidden with the box", r2.parent() is b2._klaus_note_viewer_box and not r2.isVisible() and lv.cards_showing(b2))
lv.enter(b2, "A")
app.processEvents()
check("re-enter shows it again", r2.isVisible() and lv.active(b2))
b2.close()
pump()
check("Browse's close releases it", r2.cleaned and rh.reader() is None)

section("post-disable (I-1): a home exists, a STOCK Browse borrows a fresh reader, closes — released, not deleted uncleaned")
rh.set_home(home)
r_home = rh.reader()
b8, _ = make_browser(top_level=True)
lv.enter(b8, "Hemolysis")
r8 = rh.reader()
check("a stock Browse gets its own fresh reader (never a cross-window move)", r8 is not r_home and r8.parent() is b8._klaus_note_viewer_box and r_home.cleaned)
lv.leave(b8)
check("leave keeps it in that Browse (the home is in another window)", r8.parent() is b8._klaus_note_viewer_box)
b8.close(); pump()
check("closing that Browse releases it even though a home exists", r8.cleaned and rh.reader() is None or rh.reader() is not r8)

section("closing Browse never builds a reader")
rh.set_home(home)
rh.release()
b9, _ = make_browser()
b9.close(); pump()
check("a Browse close with no reader builds nothing", rh._state["reader"] is None)
r9 = rh.reader()
r9.setParent(None); r9.deleteLater(); pump()  # died without release(), home alive
b10, _ = make_browser()
b10.close(); pump()
check("a Browse close with a DEAD reader builds nothing either (current() never builds)", rh.current() is None and rh._state["reader"] is None)
add_editor, browse_editor = object(), object()
rh.set_home_editor(add_editor)
r10 = rh.reader()
check("at home the reader belongs to the Add editor", r10._editor is add_editor)
b11, _ = make_browser()
b11.editor = browse_editor
lv.enter(b11, "A")
check("lent, it belongs to Browse's editor", r10._editor is browse_editor)
lv.leave(b11)
check("home again, the Add editor's", r10._editor is add_editor)

section("a hosted Browse closed while the reader is home: nothing to do, nothing released")
rh.set_home(home)
r5 = rh.reader()
b7, _ = make_browser()
b7.close(); pump()
check("the reader is untouched", rh.reader() is r5 and not r5.cleaned and r5.parent() is home)

section("no central widget: nothing happens")
b4 = QtWidgets.QMainWindow()
b4.form = types.SimpleNamespace(splitter=None)
check("enter declines", lv.enter(b4, "A") is False and not lv.active(b4))

section("the deleted machinery is gone")
check("no dock code left", not any(hasattr(lv, n) for n in ("_fill", "_dock_host", "_dock", "_NO_HOST")))
src = open("klaus_note/library_viewer.py").read()
check("no dock words in the module", "_klaus_note_pdf_tabs" not in src and "resizeDocks([dock" not in src and "setFloating" not in src)

raise SystemExit(report())
