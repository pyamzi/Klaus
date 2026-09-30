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
    def __init__(self, full_name, kind="TAG"):
        self.full_name = full_name
        self.name = full_name.rsplit("::", 1)[-1]
        self.item_type = types.SimpleNamespace(name=kind)


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

section("retention: the mean recall of a tag's studied cards")
means = ls.tag_means(
    {1: " Heme::Anemia ", 2: " Heme::Anemia Heme::Iron ", 3: " Onc ", 4: " Heme::Iron "},
    {1: [(0.9, False), (0.0, True)], 2: [(0.7, False)], 3: [(0.0, True)], 4: [(0.5, False)]},
)
check("a tag averages its studied cards; new cards are left out",
      abs(means["heme::anemia"] - 0.8) < 1e-9, str(means))
check("a parent counts its children's cards, each card once",
      abs(means["heme"] - (0.9 + 0.7 + 0.5) / 3) < 1e-9, str(means))
check("a tag with only new cards has no mean", "onc" not in means)
check("row text", ls.percent_text(means, "Heme::Anemia") == "80%"
      and ls.percent_text(means, "Onc") == "\u2014" and ls.percent_text(None, "Onc") is None)

retention = importlib.import_module("klausmate.retention")


class DB:
    def all(self, sql):
        if "revlog" in sql:
            return []
        card = '{"s": 10, "decay": 0.5, "lrt": 1700000000}'
        return [(10, 1, 2, 5, card), (11, 1, 2, 5, card)]

    def list(self, sql):
        return [11] if "queue = -1" in sql else []


cr = retention.card_retrievability(types.SimpleNamespace(db=DB()), {1}, skip_suspended=True)
check("suspended cards are skipped when asked", len(cr[1]) == 1, str(cr))
check("...and kept by default", len(retention.card_retrievability(types.SimpleNamespace(db=DB()), {1})[1]) == 2)

section("the % is painted at the row's right edge")
tree.resize(320, 200)
tree.show()
app.processEvents()


def right_edge_ink(means):
    ls._state["means"] = means
    img = QtGui.QImage(300, 22, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(img)
    opt = QtWidgets.QStyleOptionViewItem()
    opt.rect = QtCore.QRect(0, 0, 300, 22)
    opt.widget = tree
    opt.fontMetrics = tree.fontMetrics()
    opt.palette = tree.palette()
    delegate.paint(painter, opt, model.index(1, 0))
    painter.end()
    return sum(1 for x in range(250, 300) for y in range(22) if img.pixel(x, y) != QtGui.QColor("white").rgb())


check("nothing at the right edge before retention is computed", right_edge_ink(None) == 0)
check("the % lands at the right edge once it is", right_edge_ink({"hematology::anemia": 0.82}) > 0)
check("a studied-nothing tag shows a dash there", right_edge_ink({}) > 0)
check("a non-tag row (a deck) never gets one",
      ls.percent_text({}, "x") and not ls._is_tag(Item("Default", kind="DECK")))

section("recomputed after changes, only while Browse is open")
fired = []
ls._schedule_refresh = lambda: fired.append(1)
ls._sidebars.clear()
ls.on_operation_did_execute(types.SimpleNamespace(card=True), None)
check("no Browse open: nothing scheduled", fired == [])
ls._sidebars.add(tree)
ls.on_operation_did_execute(types.SimpleNamespace(card=False, note=False, tag=False, study_queues=False), None)
ls.on_operation_did_execute(types.SimpleNamespace(card=True), None)
check("a card change with Browse open schedules one refresh", fired == [1])

section("wired")
_init = open("klausmate/__init__.py", encoding="utf-8").read()
check("__init__ sets it up", "library_sidebar" in _init and ".setup()" in _init.split("library_sidebar", 1)[1][:200])

raise SystemExit(report())
