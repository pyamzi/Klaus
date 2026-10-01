"""Toggling one side pane leaves the opposite one at its width
(klausmate/pane_keep.py), on real Qt widgets shaped like the Add tab
(tree | reader | editor in one splitter) and Browse (a sidebar dock
beside a table | editor splitter).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pane_keep.py
"""
from __future__ import annotations

import os
import sys
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
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim

sys.path.insert(0, ".")
from klausmate import pane_keep  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
Qt = QtCore.Qt


def settle():
    for _ in range(4):
        app.processEvents()


def pane(name):
    w = QtWidgets.QWidget()
    w.setObjectName(name)
    w.setMinimumWidth(40)
    return w


section("Add tab: tree | reader | editor in one splitter")
win = QtWidgets.QWidget()
lay = QtWidgets.QHBoxLayout(win)
lay.setContentsMargins(0, 0, 0, 0)
sp = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
tree, reader, editor = pane("tree"), pane("reader"), pane("editor")
for i, w in enumerate((tree, reader, editor)):
    sp.addWidget(w)
    sp.setStretchFactor(i, (24, 46, 30)[i])
lay.addWidget(sp)
win.resize(1000, 600)
win.show()
settle()
sp.setSizes([240, 460, 300])
settle()
before = editor.width()

# Control: a plain setVisible is what moved the editor.
tree.setVisible(False)
settle()
check("(control) a plain hide hands the tree's width to the editor too",
      editor.width() > before + 20, f"{before} -> {editor.width()}")
tree.setVisible(True)
settle()
sp.setSizes([240, 460, 300])
settle()

pane_keep.set_visible_keeping(tree, False, editor)
settle()
check("hiding the tree keeps the editor at its width; the reader takes the room",
      abs(editor.width() - before) <= 1 and reader.width() > 600,
      f"editor {before} -> {editor.width()}, reader {reader.width()}")
pane_keep.set_visible_keeping(tree, True, editor)
settle()
check("showing it again keeps the editor too", abs(editor.width() - before) <= 1,
      f"{before} -> {editor.width()}")
pane_keep.set_visible_keeping(editor, False, tree)
settle()
tree_w = tree.width()
pane_keep.set_visible_keeping(editor, True, tree)
settle()
check("toggling the editor keeps the tree", abs(tree.width() - tree_w) <= 1,
      f"{tree_w} -> {tree.width()}")

section("Browse: a sidebar dock beside a table | editor splitter")
mw = QtWidgets.QMainWindow()
central = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
table, col = pane("table"), pane("editor col")
central.addWidget(table)
central.addWidget(col)
mw.setCentralWidget(central)
dock = QtWidgets.QDockWidget("Sidebar")
dock.setWidget(pane("sidebar"))
mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
mw.resize(1200, 700)
mw.show()
settle()
central.setSizes([600, 340])
settle()
col_w = col.width()

dock.setVisible(False)
settle()
check("(control) a plain dock hide widens the editor column too",
      col.width() > col_w + 20, f"{col_w} -> {col.width()}")
dock.setVisible(True)
settle()
central.setSizes([600, 340])
settle()
col_w = col.width()

pane_keep.set_visible_keeping(dock, False, col)
settle()
check("hiding the sidebar dock keeps the editor column; the table takes the room",
      abs(col.width() - col_w) <= 1, f"{col_w} -> {col.width()}")
pane_keep.set_visible_keeping(dock, True, col)
settle()
check("showing it again keeps the editor column", abs(col.width() - col_w) <= 1,
      f"{col_w} -> {col.width()}")
dock_w = dock.width()
pane_keep.set_visible_keeping(col, False, dock)
settle()
pane_keep.set_visible_keeping(col, True, dock)
settle()
check("toggling the editor leaves the dock alone (a dock is no splitter slot)",
      abs(dock.width() - dock_w) <= 1 and pane_keep.splitter_slot(dock) == (None, -1),
      f"{dock_w} -> {dock.width()}")

section("edges")
check("no opposite pane: a plain toggle", (pane_keep.set_visible_keeping(tree, False), tree.isHidden())[1])
tree.setVisible(True)
check("a widget outside any splitter has no slot",
      pane_keep.splitter_slot(QtWidgets.QWidget()) == (None, -1))

raise SystemExit(report())
