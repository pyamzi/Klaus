"""The status bar: layout toggles (Browse), a progress readout of the
task tracker, the task list popup, and one settings gear.

Real PyQt6, offscreen: a QMainWindow shaped like Browse (sidebar dock on
the left; a splitter holding the card table and the editor column).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_status_bar.py
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
sys.modules["klausmate"].get_config = lambda: {}
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

calls: list[str] = []
sys.modules["klausmate"].manage_models_dialog = lambda: calls.append("klaus")
sys.modules["aqt"].mw = types.SimpleNamespace(onPrefs=lambda: calls.append("anki"))

tasks = importlib.import_module("klausmate.tasks")
theme = importlib.import_module("klausmate.theme")
sb = importlib.import_module("klausmate.status_bar")
Task = tasks.Task


def make_browser():
    b = QtWidgets.QMainWindow()
    b.resize(1000, 600)
    splitter = QtWidgets.QSplitter()
    splitter.addWidget(QtWidgets.QTableView())
    editor_col = QtWidgets.QWidget()
    fields = QtWidgets.QWidget(editor_col)
    QtWidgets.QVBoxLayout(editor_col).addWidget(fields)
    splitter.addWidget(editor_col)
    b.setCentralWidget(splitter)
    side = QtWidgets.QDockWidget("sidebar")
    side.setWidget(QtWidgets.QTreeView())
    b.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, side)
    b.sidebarDockWidget = side
    b.form = types.SimpleNamespace(splitter=splitter, fieldsArea=fields)
    return b, side, editor_col


section("readout_text")
T = lambda key, label, done=0, total=0, msg="", t=1.0: Task(key, label, done, total, False, msg, t)  # noqa: E731
check("idle is empty", sb.readout_text([]) == "")
check("one task reads as its label", sb.readout_text([T("a", "Anemia — Embedding")]) == "Anemia — Embedding")
check("several read as the newest plus a count",
      sb.readout_text([T("c", "Newest", t=3), T("b", "B", t=2), T("a", "A", t=1)]) == "Newest  +2 more")
check("only a lingering end message: the message",
      sb.readout_text([T("a", "A", msg="Anemia indexed")]) == "Anemia indexed")

section("Browse: the two layout toggles")
b, side, col = make_browser()
bar = sb.StatusBar(b, browser=b)
b.statusBar().addPermanentWidget(bar, 1)
b.show()
app.processEvents()
bar.sidebar_btn.click()
app.processEvents()
check("◧ hides the sidebar", not side.isVisible())
bar.sidebar_btn.click()
app.processEvents()
check("...and shows it again", side.isVisible())
side.hide()
app.processEvents()
check("the toggle follows a hide from elsewhere (⌘⇧F, View menu)", not bar.sidebar_btn.isChecked())
side.show()
bar.editor_btn.click()
app.processEvents()
check("◨ hides the card editor", not col.isVisible())
bar.editor_btn.click()
app.processEvents()
check("...and shows it again", col.isVisible())

main = sb.StatusBar(QtWidgets.QMainWindow())
check("the main window's bar has no toggles", main.sidebar_btn is None and main.editor_btn is None)

section("one gear, two settings")
actions = bar.gear.menu().actions()
check("the menu holds both settings", [a.text() for a in actions] == ["KlausMate Settings…", "Anki Settings…"],
      str([a.text() for a in actions]))
for a in actions:
    a.trigger()
check("each opens its own settings", calls == ["klaus", "anki"], str(calls))

section("the progress readout")
bar.refresh([Task("i", "Anemia — Embedding", 3, 10, True, "", 1.0)])
check("a known total fills the bar", bar.progress.maximum() == 10 and bar.progress.value() == 3
      and not bar.progress.isHidden())
check("...beside the task's name", bar.label.text() == "Anemia — Embedding", bar.label.text())
bar.refresh([Task("s", "Syncing…", 0, 0, False, "", 1.0)])
check("an unknown total animates", bar.progress.maximum() == 0 and bar.progress.minimum() == 0)
bar.refresh([])
check("idle: no bar, no text", bar.progress.isHidden() and bar.label.text() == "")
bar.refresh([Task("l", "x" * 200, 0, 0, False, "", 1.0)])
app.processEvents()
check("a very long name is elided and never widens the bar",
      "…" in bar.label.text() and bar.sizeHint().width() <= 600, f"{bar.sizeHint().width()} {bar.label.text()[:20]}")

section("the task list")
cancelled = []
real_cancel = tasks.cancel
tasks.cancel = cancelled.append
bar.refresh([Task("i", "Indexing", 1, 4, True, "", 2.0), Task("s", "Syncing…", 0, 0, False, "", 1.0)])
bar.open_task_list()
app.processEvents()
xs = [w for w in bar.popup.findChildren(QtWidgets.QToolButton) if w.text() == "✕"]
check("the list is a popup, not a dialog", bool(bar.popup.windowFlags() & QtCore.Qt.WindowType.Popup))
check("only the cancellable task gets a ✕", len(xs) == 1, str(len(xs)))
xs[0].click()
check("✕ cancels that task", cancelled == ["i"], str(cancelled))
tasks.cancel = real_cancel
bar.popup.close()

section("a closed window's bar stops listening")
b2, _s, _c = make_browser()
doomed = sb.StatusBar(b2, browser=b2)
before = len(tasks._listeners)
doomed.deleteLater()
b2.deleteLater()
QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
app.processEvents()
check("its listener is gone", len(tasks._listeners) == before - 1, f"{before} -> {len(tasks._listeners)}")
try:
    tasks.begin("x", "X")
    tasks.end("x")
    ok = True
except Exception as exc:  # noqa: BLE001
    ok = False
    print(exc)
check("and a report after that raises nothing", ok)

section("theme: tokens only")
for night in (False, True):
    qss = theme.status_bar_qss(night)
    pal = {v.lower() for v in theme.palette(night).values() if isinstance(v, str) and v.startswith("#")}
    hexes = {h.lower() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", qss)}
    check(f"night={night}: names the bar and uses palette colours only",
          "QWidget#KlausStatusBar" in qss and hexes <= pal, str(hexes - pal))

raise SystemExit(report())
