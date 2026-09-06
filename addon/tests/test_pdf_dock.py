"""Tests for klausmate.pdf_handler placement migration (K-216).

Covers: the placement-value migration from pre-dock panel placement names
to the four dock areas (left, right, bottom, float). Every legacy value
maps to a valid dock placement; unknown values default to "right".

A real-Qt section is appended by Task 2 (PdfDock construction), so report()
must stay the LAST line of the file — no code runs after it.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_pdf_dock.py
"""

import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

pdf_handler = importlib.import_module("klausmate.pdf_handler")


section("placement migration — one pure function, every old value lands")
for old, new in (
    ("above", "bottom"), ("below", "bottom"),
    ("left", "left"), ("notes-left", "left"),
    ("right", "right"), ("notes-right", "right"),
    ("float", "float"),
    ("bottom", "bottom"),
):
    check(f"{old!r} → {new!r}",
          pdf_handler.migrate_placement(old) == new,
          repr(pdf_handler.migrate_placement(old)))
check("an unknown or missing value lands on 'right' — the editor-side "
      "default, never an exception",
      pdf_handler.migrate_placement(None) == "right"
      and pdf_handler.migrate_placement("sideways") == "right"
      and pdf_handler.migrate_placement(42) == "right")
check("PANEL_PLACEMENTS is exactly the four values the dock persists",
      pdf_handler.PANEL_PLACEMENTS == ("left", "right", "bottom", "float"))
check("every migrated value is one of them",
      all(pdf_handler.migrate_placement(v) in pdf_handler.PANEL_PLACEMENTS
          for v in ("above", "below", "left", "notes-left", "right",
                    "notes-right", "float", None, "")))

# The migration has to happen at the READ, not only in the dock: a panel
# the user leaves docked at the bottom writes "bottom", and until
# 2026-09-05 load_panel_state's whitelist was the five PRE-dock values,
# so it silently dropped "bottom" (and every notes-* value) and the panel
# came back on the right next session.
import os as _os  # noqa: E402
import tempfile as _tempfile  # noqa: E402

_ps = _tempfile.mkdtemp(prefix="klaus-panel-state-")
for _stored, _want in (("bottom", "bottom"), ("notes-left", "left"),
                       ("above", "bottom"), ("float", "float"),
                       ("sideways", "right")):
    pdf_handler.save_panel_state(_ps, placement=_stored)
    check(f"load_panel_state({_stored!r}) reads back {_want!r} — the "
          "migration is at the choke point every caller goes through",
          pdf_handler.load_panel_state(_ps).get("placement") == _want,
          repr(pdf_handler.load_panel_state(_ps).get("placement")))
check("geom still round-trips beside it",
      (pdf_handler.save_panel_state(_ps, geom=[1, 2, 300, 400])
       or pdf_handler.load_panel_state(_ps).get("geom")) == [1, 2, 300, 400])


# ------------------------------------------------------------------
# 2. Real offscreen Qt: the dock as it lands in Browse and Add Cards
# ------------------------------------------------------------------
import types  # noqa: E402

_os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6 import QtCore as _QtC  # noqa: E402
from PyQt6 import QtGui as _QtG  # noqa: E402
from PyQt6 import QtWidgets as _QtW  # noqa: E402

from anki_stubs import exec_klausmate_under_qt  # noqa: E402

_app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])
_scratch = _tempfile.mkdtemp(prefix="klaus-dock-")
K = exec_klausmate_under_qt(_scratch)

# load_open_tabs filters the stored tab set against contexts/ — a name
# with no ingested text is not in the store and never comes back as a tab.
_os.makedirs(_os.path.join(_scratch, "contexts"), exist_ok=True)
for _name in ("stored.pdf", "lecture.pdf", "a.pdf", "b.pdf"):
    with open(_os.path.join(_scratch, "contexts", _name + ".txt"), "w",
              encoding="utf-8") as _fh:
        _fh.write("page one\n")


class _FakeSidebar(_QtW.QWidget):
    """What PdfDock reads off PdfSidebar, nothing else."""

    def __init__(self):
        super().__init__(None)
        self._viewer = None
        self._name = None
        self._current_page = 0
        self.on_loaded = None
        self.loaded = []
        self.cleanups = 0
        self.actives = []

    def is_loaded(self, name):
        return name in self.loaded

    def load_pdf(self, name):
        self.loaded.append(name)
        self._name = name
        if self.on_loaded:
            self.on_loaded(name)

    def clear(self):
        self._name = None

    def cleanup(self):
        self.cleanups += 1

    def jump_to_page(self, page):
        self._current_page = page

    def _set_active(self, name):
        self.actives.append(name)

    def _on_page_changed(self, page):
        pass


def _host():
    win = _QtW.QMainWindow()
    win.setCentralWidget(_QtW.QTextEdit())
    win.resize(1000, 700)
    win.show()
    _app.processEvents()
    return win, types.SimpleNamespace(widget=win.centralWidget())


def _dock(placement=None, geom=None, tabs=()):
    # Each dock is a FRESH session: the stored tab set and active PDF are
    # written here, so a PDF one section loads cannot leak into the next
    # (the panel really does restore both from disk).
    K.pdf_handler.save_panel_state(_scratch, placement=placement or "right",
                                   geom=geom)
    K.pdf_handler.save_open_tabs(_scratch, list(tabs))
    K.pdf_handler.clear_active_pdf(_scratch)
    win, editor = _host()
    sb = _FakeSidebar()
    d = K.PdfDock(editor, sb, win)
    editor._klausmate_pdf_tabs = d
    editor._klausmate_sidebar = sb
    win._klausmate_pdf_container = d  # F2 (review round 1): makes the
    # host-lifetime pin's "is None" clause real — _install_panel sets this
    # same attribute on the real host, _dock() is standing in for it.
    return win, editor, sb, d


section("construction: a QDockWidget of the host, hidden, bar as title")
win, editor, sb, d = _dock("right", tabs=["stored.pdf"])
check("last session's tab set comes back as LABELS — no document is "
      "loaded until a tab is selected or the panel shown",
      d._tabs.count() == 1 and d._tabs.tabText(0) == "stored.pdf"
      and sb.loaded == [])
win, editor, sb, d = _dock("right")
check("PdfDock is a QDockWidget whose parent is the host window",
      isinstance(d, _QtW.QDockWidget) and d.parent() is win)
check("objectName is stable for Qt state and QSS",
      d.objectName() == "KlausPdfDock")
A = _QtC.Qt.DockWidgetArea
check("allowed areas are exactly left, right and bottom",
      d.allowedAreas() == (A.LeftDockWidgetArea | A.RightDockWidgetArea
                           | A.BottomDockWidgetArea))
F = _QtW.QDockWidget.DockWidgetFeature
check("movable, floatable, closable — Qt's own drag, float and hide",
      d.features() == (F.DockWidgetMovable | F.DockWidgetFloatable
                       | F.DockWidgetClosable))
check("the bar is the title-bar widget and the sidebar is the dock's widget",
      d.titleBarWidget() is d._bar and d.widget() is sb)
check("hidden until panel_show — a hidden dock takes no space",
      not d.isVisible())
check("dock nesting is enabled on the host so the panel can sit beside "
      "Anki's own sidebar dock in Browse",
      win.isDockNestingEnabled())

section("placements: each stored value lands in its area, sized to 45%")
for name, area, vertical in (("left", A.LeftDockWidgetArea, False),
                             ("right", A.RightDockWidgetArea, False),
                             ("bottom", A.BottomDockWidgetArea, True)):
    win, editor, sb, d = _dock(name)
    d.panel_show()
    _app.processEvents()
    check(f"'{name}' → visible in the {name} area",
          d.isVisible() and not d.isFloating()
          and win.dockWidgetArea(d) == area,
          str(win.dockWidgetArea(d)))
    size = d.height() if vertical else d.width()
    check(f"'{name}' → the dock got a real share of the host (>= 200 px)",
          size >= 200, f"size={size}")

section("floating: an attached tool window, geometry remembered")
win, editor, sb, d = _dock("float", geom=[120, 80, 520, 640])
d.panel_show()
_app.processEvents()
check("'float' → floating, at the remembered POSITION and size (C1: "
      "setFloating(True) clobbers _float_geom with the hidden dock's "
      "pre-layout rect before it is read; the fallback geometry is "
      "also 520x640, so a size-only pin never caught the regression)",
      d.isFloating() and d.pos() == _QtC.QPoint(120, 80)
      and d.size() == _QtC.QSize(520, 640),
      f"floating={d.isFloating()} pos={d.pos()} size={d.size()}")
check("...and the persisted geom after the show is still the stored "
      "rect, not the hidden dock's pre-layout (0, 0, 100, 30)",
      K.pdf_handler.load_panel_state(_scratch).get("geom")
      == [120, 80, 520, 640],
      K.pdf_handler.load_panel_state(_scratch).get("geom"))
check("a floating dock is still the host's child — it dies with the window, "
      "and Qt keeps it above it (the attached behaviour Pouya chose)",
      d.parent() is win and d.isWindow())
d.setFloating(False)
_app.processEvents()
check("docking it back records the area it landed in, not 'float'",
      d._placement in ("left", "right", "bottom"), d._placement)
d.setFloating(True)
_app.processEvents()
check("floating it again records 'float'", d._placement == "float")
state = K.pdf_handler.load_panel_state(_scratch)
check("...and persists it through pdf_handler.save_panel_state",
      state.get("placement") == "float")

section("migration on read: an old placement becomes a dock area")
for old, new in (("notes-left", "left"), ("above", "bottom"),
                 ("notes-right", "right"), ("below", "bottom")):
    win, editor, sb, d = _dock(old)
    check(f"stored {old!r} reads as {new!r}", d._placement == new, d._placement)

section("the title-bar contract: empty bar ignores, tabs accept")
win, editor, sb, d = _dock("right")
d.panel_show()
_app.processEvents()
bar = d._bar


def _press(widget, pos):
    return _QtG.QMouseEvent(_QtC.QEvent.Type.MouseButtonPress, _QtC.QPointF(pos),
                            _QtC.Qt.MouseButton.LeftButton,
                            _QtC.Qt.MouseButton.LeftButton,
                            _QtC.Qt.KeyboardModifier.NoModifier)


class _PressSpy(_QtC.QObject):
    """Records presses that actually REACH the dock. The accepted flag on
    the event object cannot say this: QApplication's own propagation
    walks an ignored press up to the parent, and the parent accepting it
    sets that same flag — so `not ev.isAccepted()` after sendEvent is
    False whether the bar declined it or nobody wanted it."""

    def __init__(self):
        super().__init__()
        self.hits = 0

    def eventFilter(self, obj, e):
        if e.type() == _QtC.QEvent.Type.MouseButtonPress:
            self.hits += 1
        return False


_empty = _QtC.QPointF(bar.width() - 2, bar.height() / 2)
ev = _press(bar, _empty)
bar.event(ev)
check("the bar itself DECLINES a press on its empty space (ev.ignore, "
      "never accept) — Qt's setTitleBarWidget contract",
      not ev.isAccepted())
_spy = _PressSpy()
d.installEventFilter(_spy)
_app.sendEvent(bar, _press(bar, _empty))
check("...so sent through the application that press REACHES the "
      "QDockWidget, which is what lets Qt move, dock and float from a "
      "custom title bar",
      _spy.hits == 1, f"hits={_spy.hits}")
_app.sendEvent(d, _QtG.QMouseEvent(  # end the move Qt just started
    _QtC.QEvent.Type.MouseButtonRelease, _empty,
    _QtC.Qt.MouseButton.LeftButton, _QtC.Qt.MouseButton.NoButton,
    _QtC.Qt.KeyboardModifier.NoModifier))
# F1 (review round 1): a single short tab name left 96px of drag strip;
# two tabs already saturated the bar down to a measured 4px gap, and a
# real panel routinely carries several open lecture PDFs with long names.
# Pin the strip at a SATURATED bar, not the one-tab best case.
_LECTURE_NAMES = (
    "Lecture 12 - Introduction to Quantum Field Theory and Renormalization.pdf",
    "Week 03 - Cardiovascular Physiology and Pathophysiology Overview.pdf",
    "CS 6820 Advanced Algorithms - Network Flow and Linear Programming.pdf",
    "Organic Chemistry II - Reaction Mechanisms and Stereochemistry Review.pdf",
)
for _name in _LECTURE_NAMES:
    sb.load_pdf(_name)
_app.processEvents()
check("four open PDFs saturate the tab bar — the failure mode a real "
      "session hits, not a one-tab best case",
      bar.tabs.count() == 4, f"count={bar.tabs.count()}")
r = bar.tabs.tabRect(0)
_spy.hits = 0
ev2 = _press(bar.tabs, r.center())
_app.sendEvent(bar.tabs, ev2)
check("a press on a tab IS accepted by the tab bar — select and reorder "
      "stay the tab bar's",
      ev2.isAccepted())
check("...and never reaches the dock, so dragging a tab reorders tabs "
      "instead of moving the panel",
      _spy.hits == 0, f"hits={_spy.hits}")
_strip = bar.float_btn.x() - (bar.tabs.x() + bar.tabs.width())
check("a drag strip still survives between the saturated tab bar and the "
      "float button (>= 60px) — the resizeEvent cap on the tab bar, not "
      "just the trailing stretch, is what keeps this space alive",
      _strip >= 60, f"strip={_strip}")
_spy.hits = 0
_mid = _QtC.QPointF(bar.tabs.x() + bar.tabs.width() + _strip / 2,
                    bar.height() / 2)
_app.sendEvent(bar, _press(bar, _mid))
check("...and a press in the middle of that free strip still reaches the "
      "QDockWidget, same as the empty-bar case above",
      _spy.hits == 1, f"hits={_spy.hits}")
_app.sendEvent(d, _QtG.QMouseEvent(  # end the move Qt just started
    _QtC.QEvent.Type.MouseButtonRelease, _mid,
    _QtC.Qt.MouseButton.LeftButton, _QtC.Qt.MouseButton.NoButton,
    _QtC.Qt.KeyboardModifier.NoModifier))
d.removeEventFilter(_spy)
check("the bar carries the float/dock and hide buttons, since Qt draws "
      "none of its own on a custom title bar",
      isinstance(bar.float_btn, _QtW.QToolButton)
      and isinstance(bar.hide_btn, _QtW.QToolButton))
bar.hide_btn.click()
_app.processEvents()
check("hide button hides the dock", not d.isVisible())
d.panel_show()
bar.float_btn.click()
_app.processEvents()
check("float button toggles floating", d.isFloating())


class _FakeAction:
    def __init__(self, text):
        self.text = text
        self.triggered = types.SimpleNamespace(connect=lambda *_: None)

    def setEnabled(self, on):
        pass


class _FakeMenu:
    """QMenu with a recording exec(). The real one opens a nested loop
    with nobody to close it headlessly."""

    shown = []

    def __init__(self, *_a):
        self.items = []

    def addAction(self, text):
        act = _FakeAction(text)
        self.items.append(text)
        return act

    def exec(self, *_a):
        _FakeMenu.shown.append(self.items)


_real_menu, K.QMenu = K.QMenu, _FakeMenu
try:
    bar.add_btn.click()
    _app.processEvents()
finally:
    K.QMenu = _real_menu
check("＋ actually REACHES _show_add_menu — a @_guarded zero-arg slot on "
      "`clicked` raises into its own guard and silently never runs, which "
      "is what kept this button dead",
      len(_FakeMenu.shown) == 1, str(_FakeMenu.shown))

section("tabs and the library button keep their behaviour")
win, editor, sb, d = _dock("right", tabs=["a.pdf"])
K._on_library_button(editor)
_app.processEvents()
check("hidden → the library button shows the panel", d.isVisible())
K._on_library_button(editor)
_app.processEvents()
check("visible → the library button hides it", not d.isVisible())

# With no tab open the button pops the stored-PDF picker. _show_add_menu
# ends in QMenu.exec — a nested loop with no one to close it headlessly —
# so the call is observed, not run. (QMenu.exec is the one exec() the
# conventions allow; it is not a dialog.)
_win0, _ed0, _sb0, _d0 = _dock("right")
_popped = []
_d0._show_add_menu = lambda: _popped.append(True)
K._on_library_button(_ed0)
_app.processEvents()
check("no tabs → showing the panel pops the stored-PDF picker, the only "
      "route into the library from the editor",
      _d0.isVisible() and _popped == [True])

d.panel_show()
sb.load_pdf("a.pdf")
sb.load_pdf("b.pdf")
_app.processEvents()
check("a loaded PDF gets a tab, selected, persisted",
      d._tabs.count() == 2 and d._tabs.tabText(d._tabs.currentIndex()) == "b.pdf"
      and K.pdf_handler.load_open_tabs(_scratch) == ["a.pdf", "b.pdf"],
      f"{[d._tabs.tabText(i) for i in range(d._tabs.count())]} "
      f"{K.pdf_handler.load_open_tabs(_scratch)}")
d.close_tab("b.pdf")
d.close_tab("a.pdf")
_app.processEvents()
check("closing the last tab hides the panel",
      d._tabs.count() == 0 and not d.isVisible())

section("a host that takes no docks gets no panel, not a broken one")
# Edit Current is a QDialog: addDockWidget does not exist on it, and a
# QDockWidget parented to a non-QMainWindow has nowhere to live. The old
# pane-wrapping panel did work there; the dock declines instead.
import io as _io  # noqa: E402
import contextlib as _contextlib  # noqa: E402

_plain = _QtW.QWidget()
_QtW.QVBoxLayout(_plain).addWidget(_QtW.QWidget())
_plain_ed = types.SimpleNamespace(widget=_plain,
                                  parentWindow=_plain.window())
_buf = _io.StringIO()
with _contextlib.redirect_stdout(_buf):
    K.on_editor_did_init(_plain_ed)
    _app.processEvents()
check("no dock is installed on a QWidget host, and the reason is the "
      "host check itself — not some later failure",
      getattr(_plain_ed, "_klausmate_pdf_tabs", None) is None
      and "needs a QMainWindow host" in _buf.getvalue(),
      repr(_buf.getvalue()))

section("host lifetime: closing the window releases the viewer once")
win, editor, sb, d = _dock("right")
d.panel_show()
_app.processEvents()
win.close()
_app.processEvents()
_app.processEvents()
check("sidebar.cleanup() ran exactly once and the back-references are gone",
      sb.cleanups == 1 and editor._klausmate_pdf_tabs is None
      and getattr(win, "_klausmate_pdf_container", None) is None,
      f"cleanups={sb.cleanups}")
d._on_host_closing()
d._on_host_closing()
check("...and calling _on_host_closing again (the destroyed backstop can "
      "still fire after a Close already tore down) is a no-op — the "
      "`if self._closed: return` guard, not just luck, is why "
      "cleanup() never runs twice (F3, review round 1)",
      sb.cleanups == 1, f"cleanups={sb.cleanups}")

section("the deleted machinery is gone")
_src = open(_os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "klausmate", "__init__.py"), encoding="utf-8").read()
for name in ("NOTES_PLACEMENTS", "_ZONE_CAPTIONS", "_defer_placement",
             "startSystemMove", "_tear_off", "_make_floating", "_ensure_vsplit",
             "_ensure_notes_split", "_wrap_pane", "_dock_into", "_drag_tick",
             "_load_browse_placement", "_PdfTabContainer"):
    check(f"{name} no longer appears in __init__.py", name not in _src)

raise SystemExit(report())
