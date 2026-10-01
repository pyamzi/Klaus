"""K-313: double-click a PDF in Browse's Library -> the PDF viewer takes
the cards' place; a single click or Esc brings the cards back.

Real PyQt6, offscreen: a QMainWindow shaped like Browse (central widget =
card table + editor, the sidebar dock on the left, Klaus's PDF panel
dock on the right).

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
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
lv = importlib.import_module("klausmate.library_viewer")
ph = importlib.import_module("klausmate.pdf_handler")
ph.touch_last_used = lambda uf, safe: None

R, L = QtCore.Qt.DockWidgetArea.RightDockWidgetArea, QtCore.Qt.DockWidgetArea.LeftDockWidgetArea


class PdfDock(QtWidgets.QDockWidget):
    def __init__(self, win):
        super().__init__("PDF")
        self.setWidget(QtWidgets.QLabel("viewer"))
        self._loaded = []
        # The editor dock's active pointer: a load moves it, and showing the
        # panel loads it if it isn't loaded (PdfDock.showEvent ->
        # _ensure_sidebar_pdf in __init__.py).
        self.pointer = None
        self._sidebar = types.SimpleNamespace(is_loaded=lambda s: s in self._loaded, load_pdf=self._load)
        self.persisted = 0
        self.topLevelChanged.connect(lambda *_a: setattr(self, "persisted", self.persisted + 1))
        win.addDockWidget(R, self)

    def _load(self, name):
        self._loaded.append(name)
        self.pointer = name

    def panel_show(self):
        self.show()
        if self.pointer and self.pointer not in self._loaded:
            self._load(self.pointer)


def make_browser(panel_open=False, floating=False):
    b = QtWidgets.QMainWindow()
    b.resize(1100, 700)
    b.setCentralWidget(QtWidgets.QSplitter())
    side = QtWidgets.QDockWidget("sidebar")
    side.setWidget(QtWidgets.QTreeView())
    b.addDockWidget(L, side)
    b.sidebarDockWidget = side  # Browse's own attribute name
    dock = PdfDock(b)
    b.editor = types.SimpleNamespace(_klausmate_pdf_tabs=dock)
    b.show()
    if not panel_open:
        dock.hide()
    if floating:
        dock.setFloating(True)
        dock.show()
    app.processEvents()
    return b, dock, side


section("double-click: the viewer takes the cards' place, the Library stays")
b, dock, side = make_browser()
check("sanity: cards showing, panel closed", b.centralWidget().isVisible() and not dock.isVisible())
check("enter", lv.enter(b, "Intro_to_CBC"))
app.processEvents()
check("the cards and editor step aside", not b.centralWidget().isVisible())
check("the PDF panel is up with the PDF", dock.isVisible() and dock._loaded == ["Intro_to_CBC"])
check("...filling the space", dock.width() > 700, str(dock.width()))
check("the Library sidebar stays", side.isVisible())
lv.enter(b, "Hemolysis")
check("double-clicking another PDF switches the viewer to it", dock._loaded == ["Intro_to_CBC", "Hemolysis"])

section("single click brings the cards back")
lv.on_sidebar_click(b)
check("the click that ends the double-click itself does not leave", lv.active(b))
getattr(b, lv.ATTR)["entered"] = time.monotonic() - 5
lv.on_sidebar_click(b)
app.processEvents()
check("a later single click leaves viewer mode", not lv.active(b) and b.centralWidget().isVisible())
check("the panel goes back to closed, as it was", not dock.isVisible())

section("Esc brings the cards back, and never closes Browse")
lv.enter(b, "Intro_to_CBC")
app.processEvents()
esc = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)
handled = b._klausmate_viewer_filter.eventFilter(b, esc)
app.processEvents()
check("Esc is taken", handled and not lv.active(b) and b.centralWidget().isVisible() and b.isVisible())
check("outside viewer mode Esc is Browse's again", not b._klausmate_viewer_filter.eventFilter(b, esc))

section("closing the panel or Browse restores the layout")
lv.enter(b, "Intro_to_CBC")
app.processEvents()
dock.hide()
app.processEvents()
check("the panel's own ✕ brings the cards back", not lv.active(b) and b.centralWidget().isVisible())
lv.enter(b, "Intro_to_CBC")
app.processEvents()
b.close()
app.processEvents()
check("closing Browse in viewer mode leaves the table showing for next time",
      not lv.active(b) and not b.centralWidget().isHidden())

section("an open panel keeps its size; a floating one floats again, placement untouched")
b2, dock2, _ = make_browser(panel_open=True)
before = dock2.width()
lv.enter(b2, "A")
app.processEvents()
lv.leave(b2)
app.processEvents()
check("an open panel stays open at about its old width", dock2.isVisible() and abs(dock2.width() - before) < 40,
      f"{before} -> {dock2.width()}")
b3, dock3, _ = make_browser(floating=True)
persisted = dock3.persisted
lv.enter(b3, "A")
app.processEvents()
check("a floating panel docks for viewer mode", not dock3.isFloating() and not b3.centralWidget().isVisible())
lv.leave(b3)
app.processEvents()
check("...and floats again after", dock3.isFloating())
check("...without its placement memory seeing any of it", dock3.persisted == persisted, str(dock3.persisted))

section("the sidebar keeps its width through viewer mode and back")
for _open in (False, True):
    b5, dock5, side5 = make_browser(panel_open=_open)
    b5.resizeDocks([side5], [260], QtCore.Qt.Orientation.Horizontal)
    app.processEvents()
    w0 = side5.width()
    lv.enter(b5, "A")
    app.processEvents()
    w1 = side5.width()
    lv.leave(b5)
    app.processEvents()
    w2 = side5.width()
    check(f"panel {'open' if _open else 'closed'} before: sidebar {w0} -> {w1} (viewer) -> {w2} (cards)",
          abs(w1 - w0) <= 2 and abs(w2 - w0) <= 2)

section("a first open loads only the PDF that was double-clicked")
b6, dock6, _ = make_browser()
dock6.pointer = "Last_session"
lv.enter(b6, "Hemolysis")
app.processEvents()
check("the panel's remembered PDF is not loaded first and then replaced",
      dock6._loaded == ["Hemolysis"], str(dock6._loaded))
lv.leave(b6)


def spy_resize(win):
    calls = []
    real = win.resizeDocks

    def spy(docks, sizes, orientation):
        calls.append(list(docks))
        real(docks, sizes, orientation)

    win.resizeDocks = spy
    return calls


section("the panel sizes through the window that holds it, not through Browse")
# Single window: the PDF dock lives in the main window, not in Browse.
b7 = QtWidgets.QMainWindow()
b7.resize(1100, 700)
b7.setCentralWidget(QtWidgets.QSplitter())
side7 = QtWidgets.QDockWidget("sidebar")
side7.setWidget(QtWidgets.QTreeView())
b7.addDockWidget(L, side7)
b7.sidebarDockWidget = side7
mw7 = QtWidgets.QMainWindow()  # stands in for mw
mw7.resize(1200, 800)
mw7.setCentralWidget(QtWidgets.QWidget())
dock7 = PdfDock(mw7)
dock7.hide()
b7.editor = types.SimpleNamespace(_klausmate_pdf_tabs=dock7)
mw7.show()
b7.show()
app.processEvents()
check("_dock_host is the dock's own main window", lv._dock_host(dock7) is mw7)
check("...and Browse holds only its sidebar", lv._dock_host(side7) is b7)
mw_calls, b_calls = spy_resize(mw7), spy_resize(b7)
lv.enter(b7, "A")
app.processEvents()
check("enter sizes the panel through the main window",
      any(dock7 in c for c in mw_calls), str(mw_calls))
check("...and never asks Browse to size a dock it doesn't hold",
      not any(dock7 in c for c in b_calls), str(b_calls))
check("the panel fills its window", dock7.width() > 700, str(dock7.width()))
mw_calls.clear()
b_calls.clear()
lv.leave(b7)
app.processEvents()
check("leave restores through the main window as well",
      not any(dock7 in c for c in b_calls) and b7.centralWidget().isVisible(), str(b_calls))

section("an open panel in another window is restored through that window too")
dock7.show()
app.processEvents()
lv.enter(b7, "A")
app.processEvents()
mw_calls.clear()
b_calls.clear()
lv.leave(b7)
app.processEvents()
check("leave resizes the still-visible panel through the main window",
      any(dock7 in c for c in mw_calls) and not any(dock7 in c for c in b_calls),
      f"{mw_calls} {b_calls}")
dock7.hide()

section("a dock in no main window: no host, a clear log line, nothing raises")
b9, _, _ = make_browser()
_was9 = QtWidgets.QMainWindow()
loose = PdfDock(_was9)
_was9.removeDockWidget(loose)
loose.setParent(None)
b9.editor = types.SimpleNamespace(_klausmate_pdf_tabs=loose)
check("_dock_host is None when no QMainWindow holds the dock", lv._dock_host(loose) is None)
import contextlib as _cl  # noqa: E402
import io as _io  # noqa: E402

_log, _raised = _io.StringIO(), None
try:
    with _cl.redirect_stdout(_log):
        lv.enter(b9, "A")
        app.processEvents()
        lv.leave(b9)
except Exception as exc:  # noqa: BLE001
    _raised = exc
check("enter and leave don't raise", _raised is None, repr(_raised))
check("...and say why the panel wasn't sized, not a generic AttributeError",
      "no main window holds the PDF panel" in _log.getvalue()
      and "AttributeError" not in _log.getvalue() and "NoneType" not in _log.getvalue(),
      _log.getvalue())
_log, _raised = _io.StringIO(), None
loose.show()
app.processEvents()
try:
    with _cl.redirect_stdout(_log):
        lv.enter(b9, "A")
        app.processEvents()
        lv.leave(b9)
except Exception as exc:  # noqa: BLE001
    _raised = exc
# A parentless dock counts as floating, so leave floats it back without
# asking for a host; only enter's sizing hits the no-host line here.
check("an open host-less panel: no raise, the clear line, the cards come back",
      _raised is None and "no main window holds the PDF panel" in _log.getvalue()
      and "NoneType" not in _log.getvalue() and b9.centralWidget().isVisible(),
      f"{_raised!r} {_log.getvalue()!r}")
loose.close()

section("a main window nested inside another: the inner one holds the dock")
outer = QtWidgets.QMainWindow()
outer.resize(1200, 800)
inner = QtWidgets.QMainWindow(outer, QtCore.Qt.WindowType.Widget)
inner.setCentralWidget(QtWidgets.QWidget())
outer.setCentralWidget(inner)
dock8 = PdfDock(inner)
outer.show()
app.processEvents()
check("_dock_host walks to the nearest main window that holds the dock",
      lv._dock_host(dock8) is inner and dock8.parentWidget() is inner)
inner_calls, outer_calls = spy_resize(inner), spy_resize(outer)
b8, _, _ = make_browser()
b8.editor = types.SimpleNamespace(_klausmate_pdf_tabs=dock8)
lv.enter(b8, "A")
app.processEvents()
check("enter sizes through the inner window, never the outer one",
      any(dock8 in c for c in inner_calls) and not outer_calls, f"{inner_calls} {outer_calls}")
lv.leave(b8)

section("no panel yet: nothing happens")
b4 = QtWidgets.QMainWindow()
b4.setCentralWidget(QtWidgets.QWidget())
b4.editor = types.SimpleNamespace(_klausmate_pdf_tabs=None)
check("enter declines", lv.enter(b4, "A") is False and not lv.active(b4))

raise SystemExit(report())
