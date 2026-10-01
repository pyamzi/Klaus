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

# K-234: every (win, dock) _dock() ever builds is recorded here so the
# cleanup pass at the end of the file (right before report()) can tear
# ALL of them down before the interpreter starts finalizing. Root cause:
# this file constructs ~20 real QMainWindow/PdfDock pairs and, without
# this, most stay live (never closed — a failed `check()` doesn't raise,
# so nothing here ever forced a teardown, and several sections bind
# throwaway docks to one-off names like _d0/d4/d5/d6/d7 that are never
# reassigned or released, which pins them for the rest of the file same
# as a leak would). PyQt6's own exit-time cleanup — QtCore's
# cleanup_on_exit, called from Py_FinalizeEx, walking every remaining
# live sip wrapper via sip_api_visit_wrappers — SIGBUS-es under a big
# enough pile of those. Caught via a macOS crash report
# (Python-2026-09-17-164442.ips) whose stack is exactly
# Py_FinalizeEx -> ... -> cleanup_on_exit -> sip_api_visit_wrappers,
# reproduced only under real concurrent load (several full test suites
# racing on one machine, as a busy multi-agent box does) — a lone
# standalone run is fast and light enough that sip's walk never trips,
# which is why this looked like a 1-in-3 ordering flake (and every
# check() genuinely still passes — report() prints 0 failed — right up
# until the interpreter crashes on the way out, after main() returns).
_all_docks: list = []
_rt = importlib.import_module("klausmate.reader_tabs")

# load_open_tabs filters the stored tab set against contexts/ — a name
# with no ingested text is not in the store and never comes back as a tab.
_os.makedirs(_os.path.join(_scratch, "contexts"), exist_ok=True)
for _name in ("stored.pdf", "lecture.pdf", "a.pdf", "b.pdf"):
    with open(_os.path.join(_scratch, "contexts", _name + ".txt"), "w",
              encoding="utf-8") as _fh:
        _fh.write("page one\n")


class _FakeSidebar(_QtW.QWidget):
    """What PdfDock reads off PdfSidebar, nothing else. Its ``tabs`` is a
    real ReaderTabs strip; a load opens a tab and closing the last one
    clears the reader, as PdfSidebar does (tests/test_reader_tabs.py pins
    that half)."""

    def __init__(self):
        super().__init__(None)
        self.tabs = _rt.ReaderTabs(self)
        self.tabs.closed.connect(
            lambda _n: None if self.tabs.names() else self.clear())
        self.picker_shown = 0
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
        self.tabs.open(name)
        if self.on_loaded:
            self.on_loaded(name)

    def _show_add_menu(self, *_a):
        self.picker_shown += 1

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
    K.pdf_handler.clear_active_pdf(_scratch)
    win, editor = _host()
    sb = _FakeSidebar()
    sb.tabs.set_tabs(list(tabs), None)  # what PdfSidebar restores
    d = K.PdfDock(editor, sb, win)
    editor._klausmate_pdf_tabs = d
    editor._klausmate_sidebar = sb
    win._klausmate_pdf_container = d  # F2 (review round 1): makes the
    # host-lifetime pin's "is None" clause real — _install_panel sets this
    # same attribute on the real host, _dock() is standing in for it.
    _all_docks.append((win, d))  # K-234: torn down at end-of-file, see above
    return win, editor, sb, d


section("construction: a QDockWidget of the host, hidden, bar as title")
win, editor, sb, d = _dock("right", tabs=["stored.pdf"])
check("building the dock loads nothing — a restored tab is a label "
      "until it is selected or the panel shown",
      sb.tabs.names() == ["stored.pdf"] and sb.loaded == [])
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
check("the tabs live in the reader, not the title bar (PDF reader 3/5): "
      "the bar keeps thumbnails, float and hide only",
      not hasattr(d._bar, "tabs") and not hasattr(d._bar, "add_btn")
      and sb.tabs.parent() is sb)
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

section("the title-bar contract: the empty bar ignores presses")
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
# F1 (review round 1) pinned a >= 60px drag strip beside a saturated tab
# bar. The tabs left the bar (PDF reader 3/5), so the strip is now the bar
# between ◫ and ⧉, however many PDFs are open.
for _name in ("Lecture 12 - Introduction to Quantum Field Theory.pdf",
              "Week 03 - Cardiovascular Physiology Overview.pdf",
              "CS 6820 Advanced Algorithms - Network Flow.pdf",
              "Organic Chemistry II - Reaction Mechanisms Review.pdf"):
    sb.load_pdf(_name)
_app.processEvents()
_strip = bar.float_btn.x() - (bar.thumbs_btn.x() + bar.thumbs_btn.width())
check("with four PDFs open the bar keeps a wide drag strip (>= 60px)",
      sb.tabs.names() and _strip >= 60, f"strip={_strip}")
_spy.hits = 0
_mid = _QtC.QPointF(bar.thumbs_btn.x() + bar.thumbs_btn.width() + _strip / 2,
                    bar.height() / 2)
_app.sendEvent(bar, _press(bar, _mid))
check("...and a press in the middle of that strip reaches the QDockWidget",
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
K._on_library_button(_ed0)
_app.processEvents()
check("no tabs → showing the panel pops the reader's stored-PDF picker, "
      "the only route into the library from the editor",
      _d0.isVisible() and _sb0.picker_shown == 1, f"{_sb0.picker_shown}")

d.panel_show()
sb.load_pdf("a.pdf")
sb.load_pdf("b.pdf")
_app.processEvents()
check("a loaded PDF gets a tab in the reader, selected",
      sb.tabs.names() == ["a.pdf", "b.pdf"] and sb.tabs.current() == "b.pdf",
      str(sb.tabs.names()))
sb.tabs.close("b.pdf")
_app.processEvents()
check("closing a tab while others remain keeps the panel up", d.isVisible())
sb.tabs.close("a.pdf")
_app.processEvents()
check("closing the last tab hides the panel",
      sb.tabs.names() == [] and not d.isVisible())

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

section("lazy load: a hidden editor dock loads nothing until it is shown")
K.pdf_handler.save_panel_state(_scratch, placement="right")
# The active pointer holds a bare basename with a stored context.
with open(_os.path.join(_scratch, "contexts", "lazy.txt"), "w",
          encoding="utf-8") as _fh:
    _fh.write("page one\n")
K.pdf_handler.set_active_pdf(_scratch, "lazy")
check("fixture: the active PDF resolves",
      K.pdf_handler.get_active_pdf(_scratch) == "lazy")
_lw = _QtW.QMainWindow()
_lw.setCentralWidget(_QtW.QWidget())
_QtW.QVBoxLayout(_lw.centralWidget()).addWidget(_QtW.QWidget())
_lw.resize(1000, 700)
_lw.show()
_app.processEvents()
_lazy_ed = types.SimpleNamespace(widget=_lw.centralWidget(), parentWindow=_lw)
_lazy_sb = _FakeSidebar()
_pv_mod = importlib.import_module("klausmate.pdf_viewer")
_real_sidebar_cls = _pv_mod.PdfSidebar
_pv_mod.PdfSidebar = lambda editor, parent=None: _lazy_sb
try:
    K.on_editor_did_init(_lazy_ed)
    _app.processEvents()  # the install is deferred one tick
finally:
    _pv_mod.PdfSidebar = _real_sidebar_cls
_lazy_dock = getattr(_lazy_ed, "_klausmate_pdf_tabs", None)
if isinstance(_lazy_dock, K.PdfDock):
    _all_docks.append((_lw, _lazy_dock))
check("the editor dock installs hidden and has not called load_pdf",
      isinstance(_lazy_dock, K.PdfDock) and not _lazy_dock.isVisible()
      and _lazy_sb.loaded == [], f"{_lazy_dock!r} {_lazy_sb.loaded}")
_lazy_ed2 = types.SimpleNamespace(widget=_lw.centralWidget(), parentWindow=_lw)
K.on_editor_did_init(_lazy_ed2)
_app.processEvents()
check("an editor re-init reusing the hidden dock loads nothing either",
      getattr(_lazy_ed2, "_klausmate_pdf_tabs", None) is _lazy_dock
      and _lazy_sb.loaded == [], str(_lazy_sb.loaded))
if isinstance(_lazy_dock, K.PdfDock):
    _lazy_dock.panel_show()
    _app.processEvents()
check("the first show loads the active tab",
      _lazy_sb.loaded == ["lazy"] and _lazy_sb.tabs.current() == "lazy",
      str(_lazy_sb.loaded))

section("the deleted machinery is gone")
_src = open(_os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "klausmate", "__init__.py"), encoding="utf-8").read()
for name in ("NOTES_PLACEMENTS", "_ZONE_CAPTIONS", "_defer_placement",
             "startSystemMove", "_tear_off", "_make_floating", "_ensure_vsplit",
             "_ensure_notes_split", "_wrap_pane", "_dock_into", "_drag_tick",
             "_load_browse_placement", "_PdfTabContainer",
             # PDF reader 3/5: the tabs moved into the reader.
             "_decorate_tab", "_on_tab_changed", "load_open_tabs"):
    check(f"{name} no longer appears in __init__.py", name not in _src)

section("cleanup: every dock/window this file opened is torn down before "
        "interpreter exit (K-234 — sip's own exit-time wrapper walk, "
        "QtCore's cleanup_on_exit called from Py_FinalizeEx, SIGBUS-es "
        "under a big enough pile of un-torn-down top-level Qt objects; "
        "confirmed by a macOS crash report pinning the fault to exactly "
        "that walk, reproduced only under real concurrent load)")
for _win, _d in _all_docks:
    try:
        _d._on_host_closing()  # idempotent — guarded by _d._closed
    except Exception:
        pass
    try:
        _win.close()
    except Exception:
        pass
    try:
        _win.deleteLater()
    except Exception:
        pass
for _ in range(4):
    _app.processEvents()
import gc as _gc  # noqa: E402
_gc.collect()
check(f"all {len(_all_docks)} docks this file created are torn down — "
      "none left live for sip's exit-time cleanup to walk",
      all(_d._closed for _, _d in _all_docks),
      f"{sum(1 for _, _d in _all_docks if not _d._closed)} still open")

raise SystemExit(report())
