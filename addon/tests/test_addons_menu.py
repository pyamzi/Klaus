"""Every top-level menu that isn't Anki's own moves under one "Add-ons"
menu, just before Help — in the main window and in Browse, including
menus other add-ons add later.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_addons_menu.py
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
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

am = importlib.import_module("klausmate.addons_menu")


def make_main():
    win = QtWidgets.QMainWindow()
    bar = win.menuBar()
    form = types.SimpleNamespace(menubar=bar)
    for attr, title in (("menuCol", "File"), ("menuEdit", "Edit"), ("menuqt_accel_view", "View"),
                        ("menuTools", "Tools"), ("menuHelp", "Help")):
        setattr(form, attr, bar.addMenu(title))
    win.form = form
    return win, bar


def titles(bar):
    return [a.text() for a in bar.actions() if a.isVisible()]


section("main window")
win, bar = make_main()
amboss = bar.addMenu("AMBOSS")
amboss.addAction("Open AMBOSS")
bar.addMenu("AnKing")
bar.addMenu("AnkiHub")
am.install(win, am.MAIN_MENUS)
check("Anki's own menus stay, the rest go under Add-ons before Help",
      titles(bar) == ["File", "Edit", "View", "Tools", "Add-ons", "Help"], str(titles(bar)))
addons = win._klausmate_addons_menu
check("...in the order they were on the bar",
      [a.text() for a in addons.actions()] == ["AMBOSS", "AnKing", "AnkiHub"], str([a.text() for a in addons.actions()]))
check("an add-on's own items still sit inside its menu",
      addons.actions()[0].menu() is amboss and amboss.actions()[0].text() == "Open AMBOSS")
am.install(win, am.MAIN_MENUS)
check("installing twice changes nothing", titles(bar) == ["File", "Edit", "View", "Tools", "Add-ons", "Help"])

section("a menu an add-on adds later")
bar.addMenu("Late Add-on")
app.processEvents()
app.processEvents()
check("moves too", titles(bar) == ["File", "Edit", "View", "Tools", "Add-ons", "Help"]
      and [a.text() for a in addons.actions()][-1] == "Late Add-on", str(titles(bar)))

section("no add-on menus")
w2, b2 = make_main()
am.install(w2, am.MAIN_MENUS)
check("no empty Add-ons menu", titles(b2) == ["File", "Edit", "View", "Tools", "Help"], str(titles(b2)))

section("Browse")
b = QtWidgets.QMainWindow()
bb = b.menuBar()
bf = types.SimpleNamespace()
for attr, title in (("menuEdit", "Edit"), ("menuqt_accel_view", "View"), ("menu_Notes", "Notes"),
                    ("menu_Cards", "Cards"), ("menuJump", "Go"), ("menu_Help", "Help")):
    setattr(bf, attr, bb.addMenu(title))
b.form = bf
bb.addMenu("AnkiHub")
am.install(b, am.BROWSE_MENUS)
check("Browse's own menus stay, AnkiHub goes under Add-ons",
      titles(bb) == ["Edit", "View", "Notes", "Cards", "Go", "Add-ons", "Help"], str(titles(bb)))

section("keep-on-bar exemption (the single window's Browse menus)")
w3, b3 = make_main()
am.install(w3, am.MAIN_MENUS)
keep = QtWidgets.QMenu("Notes", w3)
w3._klausmate_keep_on_bar = {keep.menuAction()}
am.place_before_help(b3, keep, w3.form.menuHelp)
app.processEvents()
app.processEvents()
check("an exempt menu stays on the bar before Help, the watcher leaves it",
      titles(b3) == ["File", "Edit", "View", "Tools", "Notes", "Help"], str(titles(b3)))
b3.addMenu("Stray")
app.processEvents()
app.processEvents()
check("…while a stray one still moves under Add-ons",
      titles(b3) == ["File", "Edit", "View", "Tools", "Add-ons", "Notes", "Help"], str(titles(b3)))

raise SystemExit(report())
