"""The assistant's shortcut must survive a focused PDF pane — and why
Ctrl+Shift+A could not.

Two halves. The SOURCE PINS run on every interpreter: the chord is read from
``assistant_dock._ASSISTANT_SHORTCUT`` (importable under the aqt stubs
alone) and its key is checked against both viewers' ShortcutOverride claim
tables, so a rebind onto a pane-claimed chord, or ``Key_K`` joining a claim
table, fails here even where PyQt6 is missing. The BEHAVIOURAL half needs
genuine PyQt6 (the K-117 recipe: real widgets behind an aqt.qt shim) and
SKIPs loudly without it, the way test_drive/test_assistant_dock/test_pdf_map
do — never silently, and never as a no-op, since the pins above still gate.

What the behavioural half pins (the 2026-09-02 collision session; rulings
ca2d30c, f0543b4): a native PdfSidebar in a QDockWidget and one in the
central layout of a QMainWindow — the Lecture-dock and Library-screen
shapes — the real ``assistant_dock.setup()`` action installed on that
window, every chord sent through QTest so Qt's shortcut map runs BEFORE
delivery, the order a platform key takes.

- Two live bindings on one chord go AMBIGUOUS: neither ``activated`` fires
  (the CLAUDE.md "host-window shortcut ambiguity" gotcha, pinned as Qt
  behaviour so the next part reads correctly).
- With a PDF pane focused, a window-scoped Ctrl+Shift+A never reaches its
  binding — ``activated`` 0 AND ``activatedAmbiguously`` 0 — because
  ``PdfViewer.eventFilter`` accepts the ShortcutOverride for every chord in
  ``_match_shortcut_combo`` ahead of the map: the viewer's highlight handler
  runs instead. Not ambiguity, pre-emption; from the assistant's side the
  two look identical (silence).
- The assistant's real action fires once with the pane focused and leaves
  the viewer untouched. The press is DERIVED from the constant, so a rebind
  is tested as itself (``test_assistant_dock`` pins the key's value and the
  QAction's shape, not the behaviour).

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_shortcut_collision.py
"""
import importlib
import os
import re
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "klaus-test", "scripts"))
from anki_stubs import check, install, report, section  # noqa: E402

install()

# ---------------------------------------------------------------- source pins
section("S. source pins — every interpreter, PyQt6 or not")
assistant_dock = importlib.import_module("klausmate.assistant_dock")  # aqt stubs suffice
CHORD = assistant_dock._ASSISTANT_SHORTCUT
LETTER = CHORD.rsplit("+", 1)[-1]
print(f"    assistant chord = {CHORD}")


def _src(name):
    with open(os.path.join(ROOT, "klausmate", name), encoding="utf-8") as fh:
        return fh.read()


_native_src, _pdfjs_src = _src("pdf_viewer.py"), _src("pdfjs_viewer.py")
check("the native viewer claims Ctrl+Shift+A in _match_shortcut_combo — the collision this suite exists for",
      "Qt.Key.Key_A and shift" in _native_src)
check(f"...and never names Key_{LETTER}: the assistant's chord is not in the native claim table",
      re.search(rf"\bKey_{LETTER}\b", _native_src) is None)
check("pdfjs_viewer claims Ctrl+Shift+A through ShortcutOverride exactly like the native viewer",
      "(K.Key_A, ctrl | shift)" in _pdfjs_src)
check(f"...and never names Key_{LETTER}: live over the pdf.js pane too (PyQt6-WebEngine cannot run "
      "offscreen here, so the pdf.js side is source-pinned only)",
      re.search(rf"\bKey_{LETTER}\b", _pdfjs_src) is None)

# ---------------------------------------------------------------- real Qt
try:
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402
    from PyQt6.QtTest import QTest  # noqa: E402
except Exception as _qt_e:  # noqa: BLE001
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — sections A–C, the behavioural "
          "checks (ambiguity pin, both pane shapes, the control), did NOT run; only the source pins "
          "above gate this suite here. Install PyQt6 for python3 to run them.")
    raise SystemExit(report())

# aqt.qt shim backed by the REAL PyQt6 (tests/test_drive.py's K-117 recipe).
_shim = types.ModuleType("aqt.qt")


def _qt_getattr(name, _mods=(QtWidgets, QtCore, QtGui)):
    for m in _mods:
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


_shim.__getattr__ = _qt_getattr
sys.modules["aqt.qt"] = _shim
for _n in [m for m in list(sys.modules) if m.startswith("klausmate.")]:
    del sys.modules[_n]

pdf_viewer = importlib.import_module("klausmate.pdf_viewer")
assistant_dock = importlib.import_module("klausmate.assistant_dock")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["klaus-test"])
Qt = QtCore.Qt
QShortcut = QtGui.QShortcut
QKeySequence = QtGui.QKeySequence
CTRL_SHIFT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
_combo = QKeySequence(CHORD)[0]
CHORD_KEY, CHORD_MODS = _combo.key(), _combo.keyboardModifiers()
print(f"    PyQt6 {QtCore.PYQT_VERSION_STR} / Qt {QtCore.QT_VERSION_STR}; "
      f"PDF_VIEWER_AVAILABLE={pdf_viewer.PDF_VIEWER_AVAILABLE}")


def pump(n=3):
    for _ in range(n):
        app.processEvents()


def inside(widget, ancestor):
    w = widget
    while w is not None:
        if w is ancestor:
            return True
        w = w.parentWidget()
    return False


class Rec:
    """Counts activated / activatedAmbiguously on one QShortcut."""

    def __init__(self, sc, label):
        self.label, self.fired, self.ambiguous = label, 0, 0
        sc.activated.connect(self._hit)
        sc.activatedAmbiguously.connect(self._amb)

    def _hit(self):
        self.fired += 1

    def _amb(self):
        self.ambiguous += 1

    def reset(self):
        self.fired = self.ambiguous = 0

    def __repr__(self):
        return f"{self.label}: activated={self.fired} ambiguous={self.ambiguous}"


def press(widget, key, mods=CTRL_SHIFT):
    # QTest.keyClick runs the shortcut map first (ShortcutOverride up the
    # focus chain, then QShortcutMap.tryShortcut) and delivers the KeyPress
    # to the widget only when nothing claimed it — a platform key's order.
    QTest.keyClick(widget, key, mods)
    pump()


# ---------------------------------------------------------------- Part A
section("A. pure Qt: two live bindings on one chord go ambiguous")
winA = QtWidgets.QMainWindow()
centralA = QtWidgets.QWidget()
layA = QtWidgets.QVBoxLayout(centralA)
outsideA = QtWidgets.QLineEdit()
paneA = QtWidgets.QFrame()
paneA.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
layA.addWidget(outsideA)
layA.addWidget(paneA)
winA.setCentralWidget(centralA)
window_scoped = QShortcut(QKeySequence("ctrl+shift+a"), winA)
pane_scoped = QShortcut(QKeySequence("Ctrl+Shift+A"), paneA)
pane_scoped.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
rA_win, rA_pane = Rec(window_scoped, "window-scoped"), Rec(pane_scoped, "pane-scoped")
winA.resize(600, 400)
winA.show()
winA.activateWindow()
pump()
check("offscreen window became the active window",
      QtWidgets.QApplication.activeWindow() is winA)
paneA.setFocus()
pump()
check("focus is on the pane", QtWidgets.QApplication.focusWidget() is paneA)
press(paneA, Qt.Key.Key_A)
print(f"    {rA_win}; {rA_pane}")
check("pane focused: NEITHER binding's activated fires", rA_win.fired == 0 and rA_pane.fired == 0)
check("pane focused: the chord is reported AMBIGUOUS instead",
      rA_win.ambiguous + rA_pane.ambiguous >= 1)
rA_win.reset(); rA_pane.reset()
outsideA.setFocus()
pump()
press(outsideA, Qt.Key.Key_A)
print(f"    {rA_win}; {rA_pane}")
check("focus outside the pane: the window-scoped binding fires alone",
      rA_win.fired == 1 and rA_win.ambiguous == 0 and rA_pane.fired == 0)
winA.close()
pump()

# ---------------------------------------------------------------- Part B
section("B. real PdfSidebar in an mw-shaped host; the real assistant action on that host")
if not pdf_viewer.PDF_VIEWER_AVAILABLE:
    print("  SKIP: QtPdf/QtPdfWidgets missing from this PyQt6 — PdfSidebar builds no native viewer, "
          "so sections B and C (the pane probes and the control) did NOT run.")
    raise SystemExit(report())

win = QtWidgets.QMainWindow()
central = QtWidgets.QWidget()
lay = QtWidgets.QVBoxLayout(central)
outside = QtWidgets.QLineEdit()          # stand-in for mw.web holding focus
lay.addWidget(outside)
lib_sidebar = pdf_viewer.PdfSidebar(None, parent=central)   # Library-screen shape (in mainLayout)
lay.addWidget(lib_sidebar, 1)
win.setCentralWidget(central)
dock = QtWidgets.QDockWidget("Lecture", win)                  # lecture_view shape (dock on mw)
body = QtWidgets.QWidget()
blay = QtWidgets.QVBoxLayout(body)
dock_sidebar = pdf_viewer.PdfSidebar(None, parent=body)
blay.addWidget(dock_sidebar)
dock.setWidget(body)
win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
win.resize(1100, 700)
win.show()
win.activateWindow()
pump()
check("host is the active window", QtWidgets.QApplication.activeWindow() is win)

# The ORIGINAL registration shape (AnkiQt.setStateShortcuts: a bare
# window-scoped QShortcut on mw) on the chord the viewer claims.
sc_state_a = QShortcut(QKeySequence("ctrl+shift+a"), win)
r_state_a = Rec(sc_state_a, "window-scoped Ctrl+Shift+A")

# The REAL assistant action, installed the way __init__ does it: setup()
# with mw pointed at this host. toggle_assistant is resolved by name at
# trigger time, so the counter stands in for the dock.
toggled = []
_orig = (assistant_dock.mw, assistant_dock._setup_done,
         assistant_dock._assistant_action, assistant_dock.toggle_assistant)
assistant_dock.mw = win
assistant_dock._setup_done = False
assistant_dock._assistant_action = None
assistant_dock.toggle_assistant = lambda: toggled.append(1)
try:
    assistant_dock.setup()
    action = assistant_dock.menu_action()
    check("setup() installed the assistant's QAction on the host window",
          action is not None and action in win.actions())
    check("that action carries the module's own chord",
          action is not None and action.shortcut() == QKeySequence(CHORD))

    def probe(sidebar, label):
        viewer = getattr(sidebar, "_viewer", None)
        view = getattr(viewer, "_pdf_view", None)
        check(f"{label}: native QPdfView present", view is not None)
        if view is None:
            return
        hl = [s for s in view.findChildren(QShortcut) if s.key() == QKeySequence("Ctrl+Shift+A")]
        check(f"{label}: the viewer owns one WidgetWithChildren Ctrl+Shift+A QShortcut",
              len(hl) == 1 and hl[0].context() == Qt.ShortcutContext.WidgetWithChildrenShortcut)
        r_hl = Rec(hl[0], f"{label} highlight QShortcut")
        calls = []
        viewer._add_highlight_from_selection = lambda *a, **k: calls.append("override-path")
        view.setFocus()
        pump()
        fw = QtWidgets.QApplication.focusWidget()
        check(f"{label}: focus landed inside the PDF pane",
              fw is not None and inside(fw, view), f"focusWidget={fw!r}")
        r_state_a.reset(); r_hl.reset(); calls.clear(); toggled.clear()
        press(fw, Qt.Key.Key_A)
        print(f"    Ctrl+Shift+A -> {r_state_a}; {r_hl}; viewer dispatch={calls}")
        check(f"{label}: Ctrl+Shift+A never reaches a window-scoped binding "
              "(activated=0 AND ambiguous=0 — pre-empted, not ambiguous)",
              r_state_a.fired == 0 and r_state_a.ambiguous == 0)
        check(f"{label}: the viewer's highlight handler ran instead", calls == ["override-path"])
        check(f"{label}: neither QShortcut fired — the ShortcutOverride claim beat the map",
              r_hl.fired == 0 and r_hl.ambiguous == 0)
        r_state_a.reset(); r_hl.reset(); calls.clear(); toggled.clear()
        press(fw, CHORD_KEY, CHORD_MODS)
        print(f"    {CHORD} -> assistant toggled={len(toggled)}; {r_hl}; viewer dispatch={calls}")
        check(f"{label}: {CHORD} toggles the assistant exactly once with the pane focused",
              toggled == [1])
        check(f"{label}: {CHORD} leaves the viewer untouched", calls == [] and r_hl.fired == 0)

    probe(dock_sidebar, "lecture-dock shape")
    probe(lib_sidebar, "library-screen shape")

    section("C. control: focus outside every PDF pane")
    outside.setFocus()
    pump()
    check("focus is on the stand-in webview", QtWidgets.QApplication.focusWidget() is outside)
    r_state_a.reset(); toggled.clear()
    press(outside, Qt.Key.Key_A)
    check("outside the panes, Ctrl+Shift+A DOES reach the window-scoped binding "
          "(the registration was sound; the failure is focus-dependent)",
          r_state_a.fired == 1 and r_state_a.ambiguous == 0)
    toggled.clear()
    press(outside, CHORD_KEY, CHORD_MODS)
    check(f"outside the panes, {CHORD} toggles the assistant once", toggled == [1])
finally:
    (assistant_dock.mw, assistant_dock._setup_done,
     assistant_dock._assistant_action, assistant_dock.toggle_assistant) = _orig
    for sb in (dock_sidebar, lib_sidebar):
        try:
            sb.cleanup()
        except Exception as exc:  # noqa: BLE001
            print(f"    cleanup: {exc}")
    win.close()
    pump()

raise SystemExit(report())
