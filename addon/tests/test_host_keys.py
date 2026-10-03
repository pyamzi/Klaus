"""Keyboard scoping for the single window: the main window's state
shortcuts (review keys) are suspended while the Browse tab shows, and
keys typed into the right dock's editors are never answered as review
keys.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_host_keys.py
"""
from __future__ import annotations

import importlib
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

hk = importlib.import_module("klaus_note.host_keys")

section("normalize")
check("space", hk.normalize(" ") == "Space")
check("letters and combos", hk.normalize("e") == "E" and hk.normalize("Ctrl+Alt+N") == "Ctrl+Alt+N")
check("Qt.Key members", hk.normalize(QtCore.Qt.Key.Key_Return) == "Return" and hk.normalize(QtCore.Qt.Key.Key_F5) == "F5")

section("recorder")
win = QtWidgets.QWidget()
mw = types.SimpleNamespace(stateShortcuts=[QtGui.QShortcut(QtGui.QKeySequence("e"), win),
                                           QtGui.QShortcut(QtGui.QKeySequence(" "), win)])
r = hk.Recorder()
r.record("review", [("e", lambda: None), (" ", lambda: None), (QtCore.Qt.Key.Key_Return, lambda: None)])
check("keys are normalized", r.keys == {"E", "Space", "Return"})
r.suspend(mw)
check("suspend disables every state shortcut", r.suspended and not any(s.isEnabled() for s in mw.stateShortcuts))
mw.stateShortcuts = [QtGui.QShortcut(QtGui.QKeySequence("o"), win)]  # a state change installed fresh ones
r.apply(mw)
check("apply re-disables fresh shortcuts while suspended", not mw.stateShortcuts[0].isEnabled())
r.resume(mw)
check("resume enables them", not r.suspended and mw.stateShortcuts[0].isEnabled())
r.record("overview", [("o", lambda: None)])
check("a new state replaces the record", r.keys == {"O"})

section("override filter")
in_dock = [True]
f = hk.OverrideFilter(r, lambda: in_dock[0])
r.record("review", [(" ", lambda: None)])
ev = QtGui.QKeyEvent(QtCore.QEvent.Type.ShortcutOverride, QtCore.Qt.Key.Key_Space,
                     QtCore.Qt.KeyboardModifier.NoModifier, " ")
check("space in dock is overridden", f.eventFilter(None, ev) is True and ev.isAccepted())
ev2 = QtGui.QKeyEvent(QtCore.QEvent.Type.ShortcutOverride, QtCore.Qt.Key.Key_X,
                      QtCore.Qt.KeyboardModifier.NoModifier, "x")
check("a key not in the state list passes", f.eventFilter(None, ev2) is False)
in_dock[0] = False
check("outside the dock nothing is overridden", f.eventFilter(None, ev) is False)
r.suspended = True
in_dock[0] = True
check("suspended recorder overrides nothing", f.eventFilter(None, ev) is False)
r.suspended = False

section("end to end: a window-scoped space shortcut versus a focused field in the dock")
top = QtWidgets.QMainWindow()
dock_area = QtWidgets.QWidget()
QtWidgets.QVBoxLayout(dock_area)
edit = QtWidgets.QLineEdit()
dock_area.layout().addWidget(edit)
top.setCentralWidget(dock_area)
fired = []
sc = QtGui.QShortcut(QtGui.QKeySequence(" "), top)
sc.activated.connect(lambda: fired.append(1))
top.show()
QtWidgets.QApplication.setActiveWindow(top)
edit.setFocus()
app.processEvents()
focus_in = [True]
flt = hk.OverrideFilter(r, lambda: focus_in[0])
app.installEventFilter(flt)
QtTest.QTest.keyClick(edit, QtCore.Qt.Key.Key_Space)
app.processEvents()
check("with focus in the dock, space types and the shortcut stays silent", edit.text() == " " and fired == [])
focus_in[0] = False
# A text widget claims typing keys itself (Qt's own ShortcutOverride), so
# "outside the dock" means focus on a non-text widget, as on the deck screen.
plain = QtWidgets.QWidget()
plain.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
dock_area.layout().addWidget(plain)
plain.show()
plain.setFocus()
app.processEvents()
QtTest.QTest.keyClick(plain, QtCore.Qt.Key.Key_Space)
app.processEvents()
check("outside the dock, the shortcut fires", fired == [1], str(fired))
app.removeEventFilter(flt)

section("setup")
hooks = types.SimpleNamespace(state_shortcuts_will_change=[], state_did_change=[])
sys.modules["aqt"].gui_hooks = hooks
rec = hk.setup(mw, lambda: False)
check("setup registers the recorder on both hooks and installs the filter",
      len(hooks.state_shortcuts_will_change) == 1 and len(hooks.state_did_change) == 1 and isinstance(rec, hk.Recorder))
hooks.state_shortcuts_will_change[0]("review", [("u", lambda: None)])
check("the hook feeds the recorder", rec.keys == {"U"})

raise SystemExit(report())
