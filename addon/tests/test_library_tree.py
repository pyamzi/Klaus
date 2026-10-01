"""The Add tab's Library tree (klausmate/library_tree.py): Klaus's own view
over the index library_sidebar builds — same rows, icons, names, retention
%, right-click items, ⟳ and +PDF header and Finder drops as Browse's sidebar,
plus a filter box; a single click on a PDF opens it.
Spec: docs/superpowers/specs/2026-10-01-add-tab-design.md, "The Library tree".

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_library_tree.py
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

import klausmate.settings as _settings  # noqa: E402
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

UF = tempfile.mkdtemp(prefix="klaus-tree-")  # never the real user_files
retention = importlib.import_module("klausmate.retention")
_settings.user_files_dir = UF
ls = importlib.import_module("klausmate.library_sidebar")
lt = importlib.import_module("klausmate.library_tree")

drive = {"folders": ["2-BiB/Exam 1/Week 1", "Empty"],
         "pdfs": {"Intro_to_CBC": {"folder": "2-BiB/Exam 1/Week 1", "display": "04-L-Intro to CBC.pdf"},
                  "Hemolysis": {"folder": "2-BiB/Exam 1", "display": "05-L-Hemolysis.pdf"}}}
prefs = {"Intro_to_CBC": {"tag": "!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC"},
         "Hemolysis": {"tag": "!Library::2-BiB::Exam_1::05-L-Hemolysis"}}
os.makedirs(os.path.dirname(retention._prefs_path()), exist_ok=True)
json.dump(prefs, open(retention._prefs_path(), "w"))
drive_store = importlib.import_module("klausmate.drive_store")
json.dump(dict(drive, version=drive_store.DRIVE_VERSION), open(drive_store._drive_path(UF), "w"))
ls._cache["key"] = None

ROOT = "!library"
WEEK = "!library::2-bib::exam_1::week_1"
CBC = WEEK + "::04-l-intro_to_cbc"
HEMO = "!library::2-bib::exam_1::05-l-hemolysis"
EMPTY = "!library::empty"

section("pure: the tree from the index")
root = lt.tree_from_index(ls.library_index())
check("root, then folders in order", root["kind"] == "root" and root["key"] == ROOT and root["label"] == "Library"
      and [c["label"] for c in root["children"]] == ["2-BiB", "Empty"], str([c["label"] for c in root["children"]]))
exam = root["children"][0]["children"][0]
check("under Exam 1: the folder first, then the PDF",
      exam["label"] == "Exam 1" and [(c["kind"], c["label"]) for c in exam["children"]]
      == [("folder", "Week 1"), ("pdf", "05-L-Hemolysis")], str(exam["children"]))
check("a PDF node carries its safe name, a folder node its path",
      exam["children"][1]["safe"] == "Hemolysis" and exam["children"][0]["folder"] == "2-BiB/Exam 1/Week 1"
      and exam["children"][0]["children"][0]["safe"] == "Intro_to_CBC")
check("filter keeps matches and their ancestors", lt.visible_keys(root, "CBC") == {ROOT, "!library::2-bib", "!library::2-bib::exam_1", WEEK, CBC})
check("empty filter shows everything", len(lt.visible_keys(root, "")) == 7)
check("no match: only nothing", lt.visible_keys(root, "zzz") == set())

section("the widget")
tree = lt.LibraryTree()
tree.resize(300, 500)
tree.show()
app.processEvents()
m = tree.model
check("one top row, the Library root, carrying tag, kind and label",
      m.rowCount() == 1 and m.item(0).data(lt.TAG_ROLE) == ROOT and m.item(0).data(lt.KIND_ROLE) == "root"
      and m.item(0).text() == "Library")
check("the root is expanded on first build, folders are not", tree.view.isExpanded(tree.index_for(ROOT)) and not tree.view.isExpanded(tree.index_for(WEEK)))
check("PDF rows carry the safe name and the pdf kind",
      tree.index_for(CBC).data(lt.SAFE_ROLE) == "Intro_to_CBC" and tree.index_for(CBC).data(lt.KIND_ROLE) == "pdf")
check("rows have the Library icons", not m.item(0).icon().isNull() and not m.itemFromIndex(tree.index_for(CBC)).icon().isNull())
check("the delegate is the sidebar's, reading the tag from the row",
      isinstance(tree.view.itemDelegate(), ls.LibraryNameDelegate) and tree.view.itemDelegate().tag_of(tree.index_for(CBC)) == CBC)


def drawn(key):
    opt = QtWidgets.QStyleOptionViewItem()
    tree.view.itemDelegate().initStyleOption(opt, tree.index_for(key))
    return opt.text


check("a PDF row draws its real name", drawn(CBC) == "04-L-Intro to CBC", drawn(CBC))
clicked = []
tree.pdf_clicked.connect(clicked.append)
tree.view.clicked.emit(tree.index_for(CBC))
check("a single click on a PDF emits its safe name", clicked == ["Intro_to_CBC"])
tree.view.setExpanded(tree.index_for(WEEK), True)
tree.view.clicked.emit(tree.index_for(WEEK))
check("a click on a folder toggles it, emits nothing", not tree.view.isExpanded(tree.index_for(WEEK)) and clicked == ["Intro_to_CBC"])
tree.view.clicked.emit(tree.index_for(WEEK))
check("...and back", tree.view.isExpanded(tree.index_for(WEEK)))

section("filter")
tree.filter.setText("hemo")
app.processEvents()
hidden = lambda key: tree.view.isRowHidden(tree.index_for(key).row(), tree.index_for(key).parent())  # noqa: E731
check("the filter hides the other PDF and the empty folder, keeps the ancestors",
      hidden(CBC) and hidden(EMPTY) and not hidden(HEMO) and not hidden("!library::2-bib") and not hidden(ROOT))
check("the filter expands the ancestors of a match", tree.view.isExpanded(tree.index_for("!library::2-bib::exam_1")))
tree.filter.setText("")
app.processEvents()
check("clearing shows everything again", not hidden(CBC) and not hidden(EMPTY))

section("refresh keeps expansion and the filter")
tree.view.setExpanded(tree.index_for(WEEK), True)
tree.filter.setText("cbc")
app.processEvents()
tree.refresh()
app.processEvents()
check("after refresh: Week 1 still expanded, Hemolysis still hidden",
      tree.view.isExpanded(tree.index_for(WEEK)) and hidden(HEMO) and not hidden(CBC))
tree.filter.setText("")

section("right-click items match Browse's")
act = importlib.import_module("klausmate.library_actions")
act.pdfs_under = lambda folder: ["Intro_to_CBC"] if folder == "2-BiB/Exam 1/Week 1" else []
labels = lambda key: [e[0] for e in ls.menu_entries(tree, key) if e is not None]  # noqa: E731
check("root", labels(ROOT) == ["Import PDFs…", "New Folder…"])
check("a PDF", labels(CBC) == ["Match Sensitivity…", "Retention History…", "Show in Finder", "Exclude from Index"])
check("a folder with PDFs", labels(WEEK) == ["New Folder…", "Import PDFs Here…", "Exclude from Index"])
check("an empty folder", labels(EMPTY) == ["New Folder…", "Import PDFs Here…", "Rename Folder…", "Remove Folder", "Exclude from Index"])
check("separators are None entries, first", ls.menu_entries(tree, CBC)[0] is None)
check("the Browse hook still builds the same menu through menu_entries",
      "menu_entries(" in open("klausmate/library_sidebar.py").read().split("def on_context_menu")[1].split("\ndef ")[0])
shown = []
tree.popup_menu = lambda menu, pos: shown.append([a.text() for a in menu.actions() if not a.isSeparator()])
tree._on_context_menu(tree.view.visualRect(tree.index_for(CBC)).center())
check("the context menu is built from the entries and shown without exec", shown == [["Match Sensitivity…", "Retention History…", "Show in Finder", "Exclude from Index"]], str(shown))

section("drops and the header row")
check("drops are accepted on the view", tree.view.viewport().acceptDrops() and isinstance(getattr(tree, "_drops", None), ls.PdfDropFilter))
check("no footer", not hasattr(tree, "footer"))
check("the header row: the filter, then ⟳ and +PDF",
      [a.objectName() for a in tree.header.actions()] == ["klausmate_library_refresh", "klausmate_library_add_pdf"]
      and tree.layout().itemAt(0).layout() is not None
      and tree.layout().itemAt(0).layout().itemAt(0).widget() is tree.filter
      and tree.layout().itemAt(0).layout().itemAt(1).widget() is tree.header)

section("registry and refresh fan-out")
check("a tree is registered beside the sidebars", tree in ls._trees)
ls._state["means"] = {CBC: 0.5}
check("the % reaches the tree's rows", ls.percent_text(ls._state["means"], CBC) == "50%")
repainted = []
tree.view.viewport().update = lambda *_a: repainted.append(1)
ls._repaint()
check("_repaint repaints the tree", repainted == [1])
rebuilt = []
tree.refresh = lambda: rebuilt.append(1)
ls.refresh_trees()
check("refresh_trees rebuilds every tree", rebuilt == [1])
check("pdf_drive's library-changed fan-out reaches the trees",
      "refresh_trees()" in open("klausmate/pdf_drive.py").read().split("def _library_changed")[1].split("\ndef ")[0])
check("refresh_status no longer bails when only trees exist",
      "if not _sidebars and not _trees" in open("klausmate/library_sidebar.py").read())

section("row icons follow the theme (UI review #1)")
_themed = []
_fake_tm = types.SimpleNamespace(icon_from_resources=lambda path: (_themed.append(path), QtGui.QIcon(path))[1])
_real_theme = sys.modules.get("aqt.theme")
sys.modules["aqt.theme"] = types.SimpleNamespace(theme_manager=_fake_tm)
try:
    _ico = lt._icon("folder")
finally:
    if _real_theme is None:
        del sys.modules["aqt.theme"]
    else:
        sys.modules["aqt.theme"] = _real_theme
check("icons load through Anki's themed loader (white at night)", _themed == [lt._ICONS["folder"]] and not _ico.isNull(), str(_themed))

raise SystemExit(report())
