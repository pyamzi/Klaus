"""K-307: Browse's sidebar shows the Library by its real names.

The tag stays ``Intro_to_CBC`` (tags cannot hold spaces); the ROW draws
"04-L-Intro to CBC". Real PyQt6, offscreen: the delegate is exercised
through Qt's own initStyleOption on a model shaped like Anki's
SidebarModel (the index's internalPointer is the SidebarItem).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_library_sidebar.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
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

UF = tempfile.mkdtemp(prefix="klaus-k307-")  # never the real user_files
curation = importlib.import_module("klausmate.curation")
retention = importlib.import_module("klausmate.retention")
curation.USER_FILES = retention.USER_FILES = UF
ls = importlib.import_module("klausmate.library_sidebar")

drive = {"folders": ["2-BiB/Exam 1/Week 1"],
         "pdfs": {"Intro_to_CBC": {"folder": "2-BiB/Exam 1/Week 1", "display": "04-L-Intro to CBC.pdf"}}}
prefs = {"Intro_to_CBC": {"tag": "!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC"}}
os.makedirs(os.path.dirname(retention._prefs_path()), exist_ok=True)
json.dump(prefs, open(retention._prefs_path(), "w"))
drive_store = importlib.import_module("klausmate.drive_store")
json.dump(dict(drive, version=drive_store.DRIVE_VERSION), open(drive_store._drive_path(UF), "w"))

section("labels")
labels = ls.build_labels(drive, prefs)
check("a PDF tag shows its real name, no extension",
      labels["!library::2-bib::exam_1::week_1::04-l-intro_to_cbc"] == "04-L-Intro to CBC", str(labels))
check("a folder tag shows its own name", labels["!library::2-bib::exam_1::week_1"] == "Week 1")
check("parents too", labels["!library::2-bib::exam_1"] == "Exam 1" and labels["!library::2-bib"] == "2-BiB")
check("the root reads Library", labels["!library"] == "Library")
check("a non-Library tag keeps its own name", ls.label_for("Hematology::Anemia") is None)


class Item:
    def __init__(self, full_name):
        self.full_name = full_name
        self.name = full_name.rsplit("::", 1)[-1]


class Model(QtCore.QAbstractItemModel):
    """Anki's SidebarModel shape: internalPointer IS the item."""

    def __init__(self, items):
        super().__init__()
        self.items = items

    def index(self, row, col, parent=QtCore.QModelIndex()):
        return self.createIndex(row, col, self.items[row])

    def parent(self, index):
        return QtCore.QModelIndex()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 1

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.EditRole):
            return index.internalPointer().name
        return None


section("the row draws the real name; the tag is untouched")
items = [Item("!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC"), Item("Hematology::Anemia")]
model = Model(items)
tree = QtWidgets.QTreeView()
tree.setModel(model)
ls.on_browser_will_show(types.SimpleNamespace(sidebar=tree))
delegate = tree.itemDelegate()
check("the Library delegate is installed on the sidebar", isinstance(delegate, ls.LibraryNameDelegate))
ls.on_browser_will_show(types.SimpleNamespace(sidebar=tree))
check("...once", tree.itemDelegate() is delegate)


def drawn(row):
    opt = QtWidgets.QStyleOptionViewItem()
    delegate.initStyleOption(opt, model.index(row, 0))
    return opt.text


check("a Library PDF row draws its real name", drawn(0) == "04-L-Intro to CBC", drawn(0))
check("any other tag draws as Anki drew it", drawn(1) == "Anemia", drawn(1))
check("editing still opens on the tag name",
      model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.EditRole) == "04-L-Intro_to_CBC")

section("wired")
_init = open("klausmate/__init__.py", encoding="utf-8").read()
check("__init__ sets it up", "library_sidebar" in _init and ".setup()" in _init.split("library_sidebar", 1)[1][:200])

raise SystemExit(report())
