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
import time as _time  # noqa: E402

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
    _all_docks.append((win, d))  # K-234: torn down at end-of-file, see above
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

section("record button: disabled without a document, enabled once one loads")
win, editor, sb, d = _dock("right")
d.panel_show()
_app.processEvents()
bar = d._bar
check("record_btn is a QToolButton with the record glyph and a tooltip "
      "naming a lecture",
      isinstance(bar.record_btn, _QtW.QToolButton)
      and bar.record_btn.text() == "●"
      and "lecture" in bar.record_btn.toolTip().lower())
check("disabled with no document loaded", not bar.record_btn.isEnabled())
sb.load_pdf("lec.pdf")
_app.processEvents()
check("enabled once a PDF is loaded", bar.record_btn.isEnabled())

section("record button: click starts/stops a recorder (K-257)")
# Starting a recording needs a REAL file at pdf_path_for's resolved path
# (never just a tab/context entry) — "lec.pdf" has neither yet.
_os.makedirs(_os.path.join(_scratch, "pdfs"), exist_ok=True)
with open(_os.path.join(_scratch, "pdfs", "lec.pdf"), "wb") as _fh:
    _fh.write(b"%PDF-1.4 fake\n")

K.lecture_recorder = importlib.import_module("klausmate.lecture_recorder")
K.index_queue = importlib.import_module("klausmate.index_queue")
_call_order = []


class _FakeRecorder:
    instances = []

    def __init__(self, user_files, pdf_safe, pdf_path, get_page,
                 on_status=None, uploader=None):
        self.user_files = user_files
        self.pdf_safe = pdf_safe
        self.pdf_path = pdf_path
        self.get_page = get_page
        self.on_status = on_status
        self.uploader = uploader
        self.is_recording = True
        self.stopped = False
        _FakeRecorder.instances.append(self)

    def start(self):
        _call_order.append("start")
        return True

    def stop(self):
        _call_order.append("stop")
        self.stopped = True
        self.is_recording = False


class _FakeUploader:
    def __init__(self):
        self.requeued = []
        # I-2 (final review): the scripted answers the drain poll gets,
        # one per turn — busy first, idle second, so a correct
        # _request_index_when_idle needs TWO turns before it may request
        # and a synchronous request_pdf is impossible to miss. Once the
        # script runs out it stays BUSY forever on purpose: later
        # sections stop a recorder too, and a poll of theirs that ever
        # reached the REAL index_queue.request_pdf (restored by their own
        # finally) would index against the stub collection.
        self.pending_calls = 0
        self.pending_left = [1, 0]

    def requeue_leftovers(self, pdf_safe, pdf_path):
        _call_order.append("requeue")
        self.requeued.append((pdf_safe, pdf_path))
        return 0

    def pending(self):
        self.pending_calls += 1
        return self.pending_left.pop(0) if self.pending_left else 1


_real_recorder_cls = K.lecture_recorder.Recorder
_real_uploader_fn = K.uploader
_real_request_pdf = K.index_queue.request_pdf
_fake_uploader = _FakeUploader()
_requested = []
K.lecture_recorder.Recorder = _FakeRecorder
K.uploader = lambda: _fake_uploader


def _fake_request_pdf(name, **kw):
    _call_order.append("request_pdf")
    _requested.append(name)


K.index_queue.request_pdf = _fake_request_pdf
try:
    bar.record_btn.click()
    _app.processEvents()
    _safe = K.pdf_handler._safe_basename("lec.pdf")
    check("clicking Record builds a Recorder scoped to the loaded PDF's "
          "safe name and real path, sharing the module uploader",
          len(_FakeRecorder.instances) == 1
          and _FakeRecorder.instances[0].pdf_safe == _safe
          and _FakeRecorder.instances[0].pdf_path
          == _os.path.join(_scratch, "pdfs", "lec.pdf")
          and _FakeRecorder.instances[0].uploader is _fake_uploader)
    check("...and requeues that PDF's leftover WAVs BEFORE starting it "
          "(Notes for Task 5, item 6)",
          _fake_uploader.requeued == [
              (_safe, _os.path.join(_scratch, "pdfs", "lec.pdf"))]
          and _call_order == ["requeue", "start"])
    sb._current_page = 4
    check("get_page is scoped to THIS sidebar and reads it live, "
          "1-based (Notes for Task 5, items 3/4 — on_segment's page is "
          "0-based, so get_page must not be)",
          _FakeRecorder.instances[0].get_page() == 5)
    check("the button flips to Stop", bar.record_btn.text() == "■")

    # C1 (fix round 1): the sidebar is REUSED across documents (a tab
    # switch here; LectureDock._show_match on every reviewed card there)
    # — get_page must stop reporting a page at all once the sidebar has
    # moved on to a DIFFERENT document, or the recorder keeps filing
    # segments under the wrong PDF's page numbers.
    sb._name = "other.pdf"
    check("C1: switching the sidebar to a different document mid-"
          "recording freezes get_page at 0 (Recorder._tick's own "
          "`int(get_page() or chunker.page)` then holds the chunker's "
          "last known page instead of mis-filing under the new document)",
          _FakeRecorder.instances[0].get_page() == 0)
    sb._name = "lec.pdf"
    check("...and switching back to THIS recording's own PDF resumes "
          "reporting the live page",
          _FakeRecorder.instances[0].get_page() == 5)

    # I3 (fix round 1): D6's "elapsed time / n to transcribe" text —
    # on_status is the Recorder's own main-thread QTimer callback
    # (Task 4 note 2), safe to drive directly here.
    _FakeRecorder.instances[0].on_status(65.0, 2)
    check("I3: on_status drives the bar's status label in D6's exact "
          "format",
          bar.status_label.text() == "1:05 · 2 to transcribe"
          and bar.status_label.isVisible())

    bar.record_btn.click()
    _app.processEvents()
    check("clicking again stops the recorder",
          _FakeRecorder.instances[0].stopped
          and not _FakeRecorder.instances[0].is_recording)
    # I-2 (final review): rec.stop() only FLUSHES the tail chunk into the
    # uploader — its HTTP transcription then takes seconds on the worker
    # thread. Requesting the re-index here read the page records before
    # that transcript ever landed, so the last <=30 s of every lecture
    # (more with a backlog) was never embedded, and nothing re-triggered.
    check("I-2: ...but does NOT request the re-index yet, while the "
          "uploader still owes a chunk",
          _requested == []
          and _call_order == ["requeue", "start", "stop"],
          repr(_call_order))
    _deadline = _time.time() + 5.0
    while not _requested and _time.time() < _deadline:
        _app.processEvents()
        _time.sleep(0.02)
    check("I-2: ...and once the uploader reports pending() == 0 the poll "
          "requests it — after at least TWO turns, so it is really "
          "waiting on the queue and not just deferring one tick",
          _requested == ["lec.pdf"] and _fake_uploader.pending_calls >= 2,
          f"requested={_requested} pending_calls={_fake_uploader.pending_calls}")
    check("m3: the FULL call order proves stop happens strictly before "
          "request_pdf, not just that both happened somewhere",
          _call_order == ["requeue", "start", "stop", "request_pdf"])
    check("the button flips back to Record", bar.record_btn.text() == "●")
    check("I3: the status label hides again once stopped",
          not bar.status_label.isVisible())

    # A second Stop for the same PDF while a poll is already armed must
    # re-use it — two chains would mean two re-index requests (and, on a
    # judged index, two Judge/Skip dialogs) for one lecture.
    _requested.clear()
    _idle_busy = [1]

    class _PendingUploader:
        def pending(self):
            return _idle_busy[0]

    _real_poll_ms = K.INDEX_IDLE_POLL_MS
    K.uploader = lambda: _PendingUploader()
    K.INDEX_IDLE_POLL_MS = 0  # same poll, no wall-clock wait
    try:
        K._request_index_when_idle("lec.pdf")
        K._request_index_when_idle("lec.pdf")
        check("I-2: a second Stop for the same PDF while a poll is armed "
              "arms no second chain",
              K._index_when_idle == {"lec.pdf"} and _requested == [],
              repr(K._index_when_idle))
        _idle_busy[0] = 0
        for _ in range(8):
            _app.processEvents()
        check("I-2: ...so exactly ONE re-index is requested when it "
              "drains, and the name is released for the next lecture",
              _requested == ["lec.pdf"]
              and "lec.pdf" not in K._index_when_idle,
              repr(_requested))
    finally:
        K.INDEX_IDLE_POLL_MS = _real_poll_ms
        K.uploader = lambda: _fake_uploader
finally:
    K.lecture_recorder.Recorder = _real_recorder_cls
    K.uploader = _real_uploader_fn
    K.index_queue.request_pdf = _real_request_pdf

section("record button: closing the host stops a live recording, "
        "before sidebar.cleanup() (I1, fix round 1)")
_FakeRecorder.instances.clear()
_call_order.clear()
win4, editor4, sb4, d4 = _dock("right")
sb4.load_pdf("lec.pdf")
d4.panel_show()
_app.processEvents()
K.lecture_recorder.Recorder = _FakeRecorder
K.uploader = lambda: _fake_uploader
try:
    d4._bar.record_btn.click()
    _app.processEvents()
    check("a recording is in flight before the host closes",
          d4._recorder is not None and d4._recorder.is_recording
          and d4._recorder in K._active_recorders)
    _call_order.clear()  # isolate the teardown order from requeue/start noise
    _orig_cleanup4 = sb4.cleanup

    def _tracked_cleanup4():
        _call_order.append("cleanup")
        return _orig_cleanup4()

    sb4.cleanup = _tracked_cleanup4
    # PR #4 F3 (Codex): host close flushes the tail chunk into the
    # uploader exactly as the Stop button does, so it owes the same
    # drain-aware re-index — without it the lecture you close Browse on
    # stays out of the page vectors until someone re-indexes by hand.
    _requested.clear()
    K._index_when_idle.clear()
    K.index_queue.request_pdf = _fake_request_pdf
    _fake_uploader.pending_left = [1, 0]  # busy, then drained
    _real_poll_ms_i1 = K.INDEX_IDLE_POLL_MS
    K.INDEX_IDLE_POLL_MS = 0  # same poll, no wall-clock wait
    d4._on_host_closing()
    check("I1: the microphone is released — stopped, dropped from the "
          "active set, and the dock forgets it — and that happened "
          "BEFORE sidebar.cleanup() (never after, which is what let a "
          "closed Browse window's capture outlive the button that could "
          "stop it)",
          _FakeRecorder.instances[0].stopped
          and not _FakeRecorder.instances[0].is_recording
          and d4._recorder is None
          and _FakeRecorder.instances[0] not in K._active_recorders
          and _call_order == ["stop", "cleanup"])
    check("PR #4 F3: closing the host ARMS the same drain-aware poll the "
          "Stop button arms — for the recorder's OWN pdf, and not before "
          "the uploader says it owes nothing",
          K._index_when_idle == {"lec.pdf"} and _requested == [],
          f"armed={K._index_when_idle} requested={_requested}")
    for _ in range(8):
        _app.processEvents()
    check("PR #4 F3: ...and once the uploader drains, the re-index really "
          "fires, so the transcript reaches the page vectors",
          _requested == ["lec.pdf"] and "lec.pdf" not in K._index_when_idle,
          f"requested={_requested} armed={K._index_when_idle}")
finally:
    K.INDEX_IDLE_POLL_MS = _real_poll_ms_i1
    K.lecture_recorder.Recorder = _real_recorder_cls
    K.uploader = _real_uploader_fn
    K.index_queue.request_pdf = _real_request_pdf

section("record button: two docks refuse a second concurrent recording "
        "(I4, fix round 1)")
_FakeRecorder.instances.clear()
_call_order.clear()
with open(_os.path.join(_scratch, "pdfs", "lec2.pdf"), "wb") as _fh:
    _fh.write(b"%PDF-1.4 fake two\n")
win5, editor5, sb5, d5 = _dock("right")
sb5.load_pdf("lec.pdf")
d5.panel_show()
_app.processEvents()
win6, editor6, sb6, d6 = _dock("right")
sb6.load_pdf("lec2.pdf")
d6.panel_show()
_app.processEvents()
_tooltips_i4 = []
_real_tooltip = K.tooltip
K.lecture_recorder.Recorder = _FakeRecorder
K.uploader = lambda: _fake_uploader
K.index_queue.request_pdf = _fake_request_pdf
K.tooltip = lambda msg, *a, **kw: _tooltips_i4.append(msg)
try:
    d5._bar.record_btn.click()
    _app.processEvents()
    check("dock A (Browse-shaped) starts recording",
          d5._recorder is not None and len(_FakeRecorder.instances) == 1)
    d6._bar.record_btn.click()
    _app.processEvents()
    check("I4: dock B (a second, differently-loaded dock — Add Cards, "
          "say) refuses to start a second recording while A's is still "
          "active, with no second Recorder ever constructed, its own "
          "button unchanged, and a tooltip naming what's already "
          "recording",
          d6._recorder is None
          and len(_FakeRecorder.instances) == 1
          and d6._bar.record_btn.text() == "●"
          and any("Already recording" in m and "lec.pdf" in m
                  for m in _tooltips_i4))
    d5._bar.record_btn.click()
    _app.processEvents()
    check("stopping A frees the slot for a later Record elsewhere",
          not K._active_recorders and d5._recorder is None)
finally:
    K.lecture_recorder.Recorder = _real_recorder_cls
    K.uploader = _real_uploader_fn
    K.index_queue.request_pdf = _real_request_pdf
    K.tooltip = _real_tooltip

section("record button: no microphone leaves the button unchanged "
        "(m2, fix round 1)")
_FakeRecorder.instances.clear()
_call_order.clear()


class _FakeRecorderNoMic(_FakeRecorder):
    def start(self):
        _call_order.append("start")
        return False


win7, editor7, sb7, d7 = _dock("right")
sb7.load_pdf("lec.pdf")
d7.panel_show()
_app.processEvents()
_tooltips_m2 = []
_real_tooltip = K.tooltip
K.lecture_recorder.Recorder = _FakeRecorderNoMic
K.uploader = lambda: _fake_uploader
K.tooltip = lambda msg, *a, **kw: _tooltips_m2.append(msg)
try:
    d7._bar.record_btn.click()
    _app.processEvents()
    check("m2: a Recorder whose start() returns False leaves _recorder "
          "None, the glyph unchanged, nothing added to the active set, "
          "and a tooltip explaining why",
          d7._recorder is None
          and d7._bar.record_btn.text() == "●"
          and len(K._active_recorders) == 0
          and _tooltips_m2 == ["No microphone available"])
finally:
    K.lecture_recorder.Recorder = _real_recorder_cls
    K.uploader = _real_uploader_fn
    K.tooltip = _real_tooltip

section("_stop_lecture_uploader: recorders released before the "
        "uploader; both profile hooks registered (I2, fix round 1)")
_teardown_calls: list = []


class _FakeTeardownRecorder:
    def __init__(self):
        self.is_recording = True
        self.pdf_name = "lec.pdf"  # a name a re-index COULD be requested for

    def stop(self):
        _teardown_calls.append("recorder")
        self.is_recording = False


class _FakeTeardownUploader:
    def stop(self):
        _teardown_calls.append("uploader")


_fake_td_rec = _FakeTeardownRecorder()
K._active_recorders.add(_fake_td_rec)
K._index_when_idle.clear()
_orig_internal_uploader = K._uploader
K._uploader = _FakeTeardownUploader()
K._stop_lecture_uploader()
check("I2: every _active_recorders member is stopped BEFORE the "
      "uploader, the set is cleared, and the module singleton is reset",
      _teardown_calls == ["recorder", "uploader"]
      and K._active_recorders == set()
      and K._uploader is None)
check("PR #4 F3: profile close arms NO drain poll, even for a live "
      "recording — the uploader it would wait on dies with the profile, "
      "and _stop_lecture_uploader keeps its own path for exactly that "
      "reason (the generation counter is the second net, not the first)",
      K._index_when_idle == set(), repr(K._index_when_idle))
K._uploader = _orig_internal_uploader

# I-2 fix round 1: the queue a drain poll is watching dies with the
# profile, but its daemon worker can still finish the chunk it holds —
# pending() then drops to 0 and, without a generation check, the poll
# requests a re-index by display name in whatever profile opened next.
section("I-2: a drain poll armed before a profile switch never fires "
        "into the next profile (fix round 1)")
_requested.clear()
_gen_pending = [1]


class _GenUploader:
    def pending(self):
        return _gen_pending[0]


_gen_uploader = _GenUploader()
_real_poll_ms_gen = K.INDEX_IDLE_POLL_MS
_orig_internal_uploader_gen = K._uploader
K.uploader = lambda: _gen_uploader
K.index_queue.request_pdf = _fake_request_pdf
K.INDEX_IDLE_POLL_MS = 0  # same poll, no wall-clock wait
try:
    K._request_index_when_idle("lec.pdf")
    check("a poll is armed while that profile's uploader is still busy",
          K._index_when_idle == {"lec.pdf"} and _requested == [],
          repr(K._index_when_idle))
    K._stop_lecture_uploader()
    check("profile_will_close clears the armed set outright",
          K._index_when_idle == set(), repr(K._index_when_idle))
    # The old uploader's worker finishes its last chunk after the profile
    # is gone — the exact moment the stale poll would have fired.
    _gen_pending[0] = 0
    for _ in range(8):
        _app.processEvents()
    check("...and the stale poll neither re-arms nor requests a re-index, "
          "even once the dead profile's queue reports itself drained",
          _requested == [] and K._index_when_idle == set(),
          f"requested={_requested} armed={K._index_when_idle}")
finally:
    K.INDEX_IDLE_POLL_MS = _real_poll_ms_gen
    K.uploader = _real_uploader_fn
    K.index_queue.request_pdf = _real_request_pdf
    K._uploader = _orig_internal_uploader_gen

_init_src = open(_os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "klausmate", "__init__.py"), encoding="utf-8").read()
# The newline anchors on both sides (not just a substring test) so a
# mutation that just COMMENTS the line out ("# ...gui_hooks...") cannot
# satisfy this pin by leaving the text present but inert.
check("I2: the uploader is created for real at profile_did_open "
      "(ruling 4) — a standalone, uncommented registration line",
      "\ngui_hooks.profile_did_open.append(_start_lecture_uploader)\n"
      in _init_src)
check("I2: ...and stopped for real at profile_will_close — likewise "
      "uncommented",
      "\ngui_hooks.profile_will_close.append(_stop_lecture_uploader)\n"
      in _init_src)

section("the deleted machinery is gone")
_src = open(_os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "klausmate", "__init__.py"), encoding="utf-8").read()
for name in ("NOTES_PLACEMENTS", "_ZONE_CAPTIONS", "_defer_placement",
             "startSystemMove", "_tear_off", "_make_floating", "_ensure_vsplit",
             "_ensure_notes_split", "_wrap_pane", "_dock_into", "_drag_tick",
             "_load_browse_placement", "_PdfTabContainer"):
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
