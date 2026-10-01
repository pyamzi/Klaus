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

UF = tempfile.mkdtemp(prefix="klaus-k307-")  # never the real user_files
curation = importlib.import_module("klausmate.curation")
retention = importlib.import_module("klausmate.retention")
_settings.user_files_dir = UF
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
check("a Library tag in another casing still gets its label (Anki tags are case-insensitive)",
      ls.label_for("!library::2-BiB::Exam_1::Week_1") == "Week 1"
      and ls.label_for("!LIBRARY::2-BIB::EXAM_1::WEEK_1") == "Week 1")


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

section("retention: the mean recall of ALL of a tag's cards, never-studied ones at 0%")
means = ls.tag_means(
    {1: " Heme::Anemia ", 2: " Heme::Anemia Heme::Iron ", 3: " Onc ", 4: " Heme::Iron "},
    {1: [(0.9, False), (0.0, True)], 2: [(0.7, False)], 3: [(0.0, True)], 4: [(0.5, False)]},
)
check("a tag averages every card; a never-studied card counts as 0% (Pouya, 2026-09-30: "
      "recall times coverage, so a lecture with most of its cards untouched reads low, not high)",
      abs(means["heme::anemia"] - (0.9 + 0.0 + 0.7) / 3) < 1e-9, str(means))
check("a parent counts its children's cards, each card once",
      abs(means["heme"] - (0.9 + 0.0 + 0.7 + 0.5) / 4) < 1e-9, str(means))
check("a tag with only never-studied cards reads 0%, not a dash", means.get("onc") == 0.0, str(means))
check("row text", ls.percent_text(means, "Heme::Anemia") == "53%"
      and ls.percent_text(means, "Onc") == "0%" and ls.percent_text(means, "Nope") == "\u2014"
      and ls.percent_text(None, "Onc") is None)

retention = importlib.import_module("klausmate.retention")


class DB:
    """Card 11 is suspended (queue -1) and well remembered; card 10 is not."""

    def all(self, sql):
        if "revlog" in sql:
            return []
        if "from notes" in sql:
            return [(1, " Heme ")]
        return [(10, 1, 2, 5, '{"s": 1, "decay": 0.5, "lrt": 1700000000}'),
                (11, 1, 2, 5, '{"s": 100000, "decay": 0.5, "lrt": 1700000000}')]

    def list(self, sql):
        return [11] if "queue = -1" in sql else []


_col = types.SimpleNamespace(db=DB())
cr = retention.card_retrievability(_col, {1})
_both = sum(r for r, _n in cr[1]) / 2
check("suspended cards count toward a tag's %", len(cr[1]) == 2
      and abs(ls.compute_means(_col)["heme"] - _both) < 1e-9, str(cr))

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

section("a PDF that needs attention says why")
idx = ls.build_index(drive, prefs)
check("tag -> PDF and tag -> folder maps",
      idx["safes"]["!library::2-bib::exam_1::week_1::04-l-intro_to_cbc"] == "Intro_to_CBC"
      and idx["folders"]["!library::2-bib::exam_1"] == "2-BiB/Exam 1", str(idx))
st = ls.pdf_status(["a", "b", "c", "d"], {"d"},
                   {"a": (False, False), "b": (True, True), "c": (True, False), "d": (False, False)}.get)
check("not embedded, stale and indexing get reasons; a current one gets none",
      st == {"a": ls.NOT_EMBEDDED, "b": ls.STALE, "d": ls.INDEXING}, str(st))
ls._state["status"] = {"Intro_to_CBC": ls.STALE}
opt = QtWidgets.QStyleOptionViewItem()
opt.widget = tree
delegate.initStyleOption(opt, model.index(0, 0))
check("its row carries a warning icon", not opt.icon.isNull())
opt = QtWidgets.QStyleOptionViewItem()
opt.widget = tree
delegate.initStyleOption(opt, model.index(1, 0))
check("an ordinary tag row does not", opt.icon.isNull())
ls._state["status"] = {}

section("right-click menus")
act = importlib.import_module("klausmate.library_actions")
act.pdfs_under = lambda folder: ["Intro_to_CBC"] if folder == "2-BiB/Exam 1/Week 1" else []


def menu_for(full_name):
    menu = QtWidgets.QMenu()
    menu.addAction("Anki's own item")
    ls.on_context_menu(types.SimpleNamespace(browser=None), menu, Item(full_name), None)
    return [a.text() for a in menu.actions() if not a.isSeparator()]


check("Anki's items stay first", menu_for("!Library")[0] == "Anki's own item")
check("root: import and new folder", menu_for("!Library")[1:] == ["Import PDFs…", "New Folder…"])
check("a PDF: only what Anki's own items and a double-click can't do (K-316)",
      menu_for("!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC")[1:]
      == ["Match Sensitivity…", "Retention History…", "Show in Finder", "Exclude from Index"],
      str(menu_for("!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC")))
check("a folder with PDFs",
      menu_for("!Library::2-BiB::Exam_1::Week_1")[1:] == ["New Folder…", "Import PDFs Here…", "Exclude from Index"])
check("an empty folder can be renamed and removed here (Anki's own items skip empty tags)",
      menu_for("!Library::2-BiB::Exam_1")[1:]
      == ["New Folder…", "Import PDFs Here…", "Rename Folder…", "Remove Folder", "Exclude from Index"])
check("any other tag gets nothing extra", menu_for("Hematology::Anemia") == ["Anki's own item"])

section("a PDF missing from the Library folder")
_ph5 = importlib.import_module("klausmate.pdf_handler")
_uf5 = importlib.import_module("klausmate.pdf_source").user_files_dir()  # what the sidebar reads, HEAD or seam
_cbc = "!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC"
st = ls.pdf_status(["a", "d"], {"d"}, {"a": (False, False), "d": (True, False)}.get, missing={"a", "d"})
check("missing wins over every other reason", st == {"a": ls.MISSING, "d": ls.MISSING}, str(st))
check("...and its words", ls.MISSING == "Missing from your Library folder")
_ph5.set_missing(_uf5, {"Intro_to_CBC"})
_real_status = (ls._sidebars, retention.index_status)
_idx_q = importlib.import_module("klausmate.index_queue")
_real_pending = _idx_q.pending_names
_idx_q.pending_names = lambda: set()
retention.index_status = lambda safe, sig: (True, False)
ls._sidebars = {tree}
ls.refresh_status()
check("the sidebar reads the rescan's missing set", ls._state["status"] == {"Intro_to_CBC": ls.MISSING},
      str(ls._state["status"]))
opt = QtWidgets.QStyleOptionViewItem()
opt.widget = tree
delegate.initStyleOption(opt, model.index(0, 0))
check("its row carries the warning icon", not opt.icon.isNull())
ls._sidebars, retention.index_status = _real_status
_idx_q.pending_names = _real_pending
_pd5 = importlib.import_module("klausmate.pdf_drive")
_removed = []
_real_delete = _pd5.delete_pdf
_pd5.delete_pdf = lambda safe: (_removed.append(safe), True)[1]
menu = QtWidgets.QMenu()
ls.on_context_menu(types.SimpleNamespace(browser=None), menu, Item(_cbc), None)
_acts = [a for a in menu.actions() if a.text() == "Remove from Library"]
check("its menu offers Remove from Library", len(_acts) == 1, str([a.text() for a in menu.actions()]))


def _prompt():
    boxes = [w for w in QtWidgets.QApplication.topLevelWidgets()
             if isinstance(w, QtWidgets.QMessageBox) and w.isVisible()]
    return boxes[-1] if boxes else None


# PyQt6 aborts the process (qFatal) on an exception in a slot unless
# sys.excepthook is replaced: record instead, and check it stayed empty.
_No, _Yes = QtWidgets.QMessageBox.StandardButton.No, QtWidgets.QMessageBox.StandardButton.Yes


def _ask_remove():
    """Pick Remove from Library; the prompt it opened, or None."""
    if _acts:
        _acts[0].trigger()
    return _prompt()


def _answer(box, button):
    """Click Yes or No on the prompt; False when there was no prompt."""
    if box is None:
        return False
    box.button(button).click()
    app.processEvents()
    return True


_slot_errors, _real_hook = [], sys.excepthook
_ts5 = importlib.import_module("klausmate.tag_sync")
_ts5_mw = _ts5.mw
sys.excepthook = lambda *exc: _slot_errors.append(exc[1])
try:
    _ts5.mw = QtWidgets.QWidget()  # Anki's main window parents the prompt
    _box = _ask_remove()
    check("Remove asks first, window-modal, never exec (K-114)",
          _box is not None and _box.windowModality() == QtCore.Qt.WindowModality.WindowModal and _removed == [])
    check("...in these words",
          _box is not None and _box.text() == "“04-L-Intro to CBC” is no longer in your Library folder. "
          "Remove it from Klaus too?\n\nThis also removes its marks and its card tag.", _box and _box.text())
    check("...with No the default", _box is not None and _box.defaultButton() is _box.button(_No))
    check("No leaves everything alone",
          _answer(_box, _No) and _removed == [] and _ph5.load_missing(_uf5) == {"Intro_to_CBC"}
          and _prompt() is None, str(_removed))
    check("Yes deletes it from the Library and clears its missing flag at once",
          _answer(_ask_remove(), _Yes) and _removed == ["Intro_to_CBC"] and _ph5.load_missing(_uf5) == set(),
          str((_removed, _ph5.load_missing(_uf5))))
finally:
    _ts5.mw = _ts5_mw
    sys.excepthook = _real_hook
check("no slot raised", _slot_errors == [], str(_slot_errors))
_ph5.set_missing(_uf5, {"Intro_to_CBC"})
_back = os.path.join(_uf5, "pdfs", "Intro_to_CBC.pdf")
os.makedirs(os.path.dirname(_back), exist_ok=True)
open(_back, "wb").close()
check("a flagged PDF whose file is back before the rescan is not offered (it would be trashed)",
      "Remove from Library" not in menu_for(_cbc))
os.remove(_back)
_ph5.set_missing(_uf5, ())
check("a PDF that is not missing has no such item",
      "Remove from Library" not in menu_for(_cbc))
_pd5.delete_pdf = _real_delete
ls._state["status"] = {}

section("a single click only shows the cards; a double-click opens the viewer")
viewer = importlib.import_module("klausmate.library_viewer")
calls = []
viewer.on_sidebar_click = lambda b: calls.append(("click", b))
viewer.enter = lambda b, safe: calls.append(("enter", safe))
ls._on_clicked("B", model.index(0, 0))
ls._on_double_clicked("B", model.index(0, 0))
ls._on_double_clicked("B", model.index(1, 0))
check("click: viewer mode steps aside (the search itself is Anki's)", calls[0] == ("click", "B"))
check("double-click on a PDF enters the viewer with that PDF", calls[1] == ("enter", "Intro_to_CBC"))
check("double-click on any other tag does nothing", len(calls) == 2, str(calls))
import klausmate.pdf_handler as _ph  # noqa: E402
_ph.touch_last_used = lambda uf, safe: None

section("drop PDFs on the sidebar")
imported = []
act.import_files = lambda paths, folder=None: imported.append(paths)
drops = ls.PdfDropFilter()


_keep = []  # a drag event holds a raw pointer to its mime data


def drag(kind, urls):
    mime = QtCore.QMimeData()
    _keep.append(mime)
    if urls:
        mime.setUrls([QtCore.QUrl.fromLocalFile(u) for u in urls])
    else:
        mime.setText("a tag")
    cls = QtGui.QDropEvent if kind == QtCore.QEvent.Type.Drop else QtGui.QDragEnterEvent
    return cls(QtCore.QPointF(5, 5) if cls is QtGui.QDropEvent else QtCore.QPoint(5, 5),
               QtCore.Qt.DropAction.CopyAction, mime, QtCore.Qt.MouseButton.LeftButton,
               QtCore.Qt.KeyboardModifier.NoModifier)


check("a PDF drag is taken", drops.eventFilter(tree, drag(QtCore.QEvent.Type.DragEnter, ["/tmp/a.pdf"])))
check("Anki's own tag drags pass through", not drops.eventFilter(tree, drag(QtCore.QEvent.Type.DragEnter, None)))
drops.eventFilter(tree, drag(QtCore.QEvent.Type.Drop, ["/tmp/a.pdf", "/tmp/notes.txt"]))
check("dropping imports just the PDFs", imported == [["/tmp/a.pdf"]], str(imported))

section("import copies into the library root; the background scan does the rest")
act = importlib.reload(act)
root = tempfile.mkdtemp(prefix="klaus-k307-root-")
src = tempfile.mkdtemp(prefix="klaus-k307-src-")
open(os.path.join(src, "Lecture.pdf"), "wb").write(b"%PDF")
open(os.path.join(root, "Lecture.pdf"), "wb").write(b"%PDF old")
_ph._live_library_root = lambda: root
scans = []
pdf_drive = importlib.import_module("klausmate.pdf_drive")
pdf_drive.start_library_rescan = lambda *a, **k: scans.append(1)
n = act.import_files([os.path.join(src, "Lecture.pdf"), os.path.join(src, "missing.pdf")], "Heme")
check("the PDF is copied into its folder", n == 1 and os.path.isfile(os.path.join(root, "Heme", "Lecture.pdf")))
act.import_files([os.path.join(src, "Lecture.pdf")])
check("a name clash at the root gets a new name, never an overwrite",
      open(os.path.join(root, "Lecture.pdf"), "rb").read() == b"%PDF old"
      and any(f.startswith("Lecture (") for f in os.listdir(root)), str(os.listdir(root)))
check("each import starts the background scan", scans == [1, 1])

section("header: ⟳ and +PDF beside the filter, no footer")
ls.refresh_status = lambda: None
check("the footer is gone", not hasattr(ls, "Footer") and not hasattr(ls, "_install_footer"))
_iq = importlib.import_module("klausmate.index_queue")
_act = importlib.import_module("klausmate.library_actions")
_hits = []
_iq_refresh, _pick = _iq.refresh, _act.pick_and_import
_iq.refresh = lambda parent=None: _hits.append(("refresh", parent)) or 0
_act.pick_and_import = lambda parent, folder=None: _hits.append(("import", parent))
_owner = QtWidgets.QWidget()
_refresh_act, _add_act = ls.header_actions(_owner)
check("two actions: ⟳ then +PDF, named and iconed",
      (_refresh_act.toolTip(), _add_act.toolTip()) == ("Index New and Changed PDFs", "Import PDFs…")
      and _refresh_act.objectName() == "klausmate_library_refresh" and _add_act.objectName() == "klausmate_library_add_pdf"
      and not _refresh_act.icon().isNull() and not _add_act.icon().isNull())
_refresh_act.trigger(); _add_act.trigger()
check("⟳ runs index_queue.refresh, +PDF opens the picker, both on the owner",
      _hits == [("refresh", _owner), ("import", _owner)], str(_hits))
container = QtWidgets.QWidget()
grid = QtWidgets.QGridLayout(container)
grid.addWidget(QtWidgets.QLineEdit(), 0, 0)
_toolbar = QtWidgets.QToolBar()
_toolbar.addAction("Search"); _toolbar.addAction("Select")
grid.addWidget(_toolbar, 0, 1)
side = QtWidgets.QTreeView()
side.toolbar = _toolbar
grid.addWidget(side, 1, 0, 1, 2)
browser = types.SimpleNamespace(sidebar=side, sidebarDockWidget=types.SimpleNamespace(widget=lambda: container))
ls._install_header(browser)
ls._install_header(browser)
_names = [a.objectName() for a in _toolbar.actions()]
check("Browse's sidebar toolbar gets the two actions once, after a separator",
      _names.count("klausmate_library_refresh") == 1 and _names.count("klausmate_library_add_pdf") == 1
      and _toolbar.actions()[2].isSeparator() and grid.rowCount() == 2, str(_names))
check("Finder drops still land on the sidebar", isinstance(getattr(side, "_klausmate_drops", None), ls.PdfDropFilter))
_iq.refresh, _act.pick_and_import = _iq_refresh, _pick

section("the Library is its own section, with its own icons")


class SItem:
    def __init__(self, full_name, kind="TAG", children=()):
        self.full_name, self.item_type = full_name, types.SimpleNamespace(name=kind)
        self.icon, self.children, self._parent_item = "icons:tag-outline.svg", list(children), None
        for c in self.children:
            c._parent_item = self


pdf_row = SItem("!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC")
week = SItem("!Library::2-BiB::Exam_1::Week_1", children=[pdf_row])
lib = SItem("!Library", children=[SItem("!Library::2-BiB", children=[SItem("!Library::2-BiB::Exam_1", children=[week])])])
heme = SItem("Hematology")
tags = SItem("", kind="TAG_ROOT", children=[SItem("", kind="TAG_NONE"), lib, heme])
root = SItem("", kind="ROOT", children=[SItem("", kind="DECK_ROOT"), tags])
moved = ls.split_library_section(root, idx["safes"])
check("the Library leaves Tags and becomes the first section",
      moved is lib and root.children[0] is lib and lib not in tags.children and lib._parent_item is root)
check("other tags stay where they were", tags.children[-1] is heme and heme.icon == "icons:tag-outline.svg")
check("icons: library for the section, folder for folders, PDF for PDFs",
      lib.icon == ls.ROOT_ICON and week.icon == ls.FOLDER_ICON and pdf_row.icon == ls.PDF_ICON)
check("the three icons ship", all(os.path.isfile(p) for p in (ls.ROOT_ICON, ls.FOLDER_ICON, ls.PDF_ICON)))
check("no Library yet: nothing moves", ls.split_library_section(SItem("", kind="ROOT", children=[SItem("", kind="TAG_ROOT")]), {}) is None)

orphan = SItem("!Library::2-BiB::Exam_1::Week_1::02-ELO-Intro_to_Blood")
empty_folder = SItem("!Library::2-BiB::Exam_1")
lib2 = SItem("!Library", children=[orphan, empty_folder])
root2 = SItem("", kind="ROOT", children=[SItem("", kind="TAG_ROOT", children=[lib2])])
ls.split_library_section(root2, {}, {"!library::2-bib::exam_1": "2-BiB/Exam 1"})
check("a PDF whose tag lost its owner record still shows the PDF icon", orphan.icon == ls.PDF_ICON)
check("an empty folder Klaus knows keeps the folder icon", empty_folder.icon == ls.FOLDER_ICON)

section("the section is split AFTER every stage, whoever built the tags")
tag_lists = []


class FakeSidebar:
    def __init__(self):
        self.selected = ["!Library::Onc::Leuk"]

    def _root_tree(self):
        # Anki's own build, with AnkiHub-style add-ons having built Tags
        lib_ = SItem("!Library", children=[SItem("!Library::A")])
        return SItem("", kind="ROOT", children=[SItem("", kind="TAG_ROOT", children=[lib_, SItem("Heme")])])

    def _selected_tags(self):
        return self.selected

    def remove_tags(self, item):
        tag_lists.append("anki removed")


fs = FakeSidebar()
ls.wrap_sidebar(fs)
ls.wrap_sidebar(fs)
built_root = fs._root_tree()
check("one Tags section, and the Library is its own section above it",
      [c.full_name for c in built_root.children] == ["!Library", ""]
      and sum(ls._kind(c) == "TAG_ROOT" for c in built_root.children) == 1)
noted = []
_ts = importlib.import_module("klausmate.tag_sync")
_ts.note_user_deleted = lambda tags: noted.append(list(tags))
fs.remove_tags(None)
check("a sidebar delete is noted for tag_sync, then Anki deletes as usual",
      noted == [["!Library::Onc::Leuk"]] and tag_lists == ["anki removed"])
check("wrapped once", fs._klausmate_wrapped is True)

section("the disclosure arrows are drawn")
theme = importlib.import_module("klausmate.theme")
for _night in (False, True):
    _qss = theme.sidebar_tree_qss(_night)
    check(f"night={_night}: closed and open folders get arrow images",
          "::branch:has-children:closed" in _qss and "::branch:has-children:open" in _qss
          and ("branch-closed-night.svg" if _night else "branch-closed-day.svg") in _qss
          and ("branch-open-night.svg" if _night else "branch-open-day.svg") in _qss)
check("the arrow images ship", all(os.path.isfile(os.path.join("klausmate", "web", f)) for f in
      ("branch-closed-day.svg", "branch-closed-night.svg", "branch-open-day.svg", "branch-open-night.svg")))

section("wired")
_init = open("klausmate/__init__.py", encoding="utf-8").read()
check("__init__ sets it up", "library_sidebar" in _init and ".setup()" in _init.split("library_sidebar", 1)[1][:200])
_ls_src = open("klausmate/library_sidebar.py", encoding="utf-8").read()
check("Klaus no longer builds the Tags section itself (AnkiHub does, and two appeared)",
      "browser_will_build_tree" not in _ls_src and "_tag_tree(" not in _ls_src)

section("the retention refresh shows in the status bar (status bar 5/6)")
tasks = importlib.import_module("klausmate.tasks")
tasks.run_on_main = lambda fn: fn()
tasks.clear()
held = []


class HoldOp:
    def __init__(self, parent=None, op=None, success=None):
        self.success, self.fail = success, None
        held.append(self)

    def failure(self, fn):
        self.fail = fn
        return self

    def run_in_background(self):
        pass


ls.QueryOp = HoldOp
ls.mw = types.SimpleNamespace(col=object())
ls._sidebars.add(tree)
ls._state.update(busy=False, again=False)
ls._repaint = lambda: None
ls.refresh_retention()
check("a running refresh is a task", [t.key for t in tasks.snapshot()] == ["retention"], str(tasks.snapshot()))
held[-1].success({})
check("...gone when it lands", tasks.snapshot() == [], str(tasks.snapshot()))
ls.refresh_retention()
held[-1].fail(RuntimeError("db"))
check("...and a failure stays in the bar with its reason",
      [(t.key, t.error, "db" in t.message) for t in tasks.snapshot()] == [("retention", True, True)], str(tasks.snapshot()))
tasks.clear()

section("manual indexing: exclude and include")
pdf_index = importlib.import_module("klausmate.pdf_index")
iq = importlib.import_module("klausmate.index_queue")
PDF_TAG = "!Library::2-BiB::Exam_1::Week_1::04-L-Intro_to_CBC"
WEEK_TAG = "!Library::2-BiB::Exam_1::Week_1"
EXAM_TAG = "!Library::2-BiB::Exam_1"
check("the root offers neither", not {"Exclude from Index", "Include in Index"} & set(menu_for("!Library")))
check("exclude_confirm_text, a PDF",
      act.exclude_confirm_text("Hemolysis", "pdf", 1)
      == "Exclude “Hemolysis” from the index? Its search index is deleted. Its cards keep their Library tag.")
check("exclude_confirm_text, a folder of four",
      act.exclude_confirm_text("Exam 1", "folder", 4)
      == "Exclude “Exam 1” from the index? The search index of 4 PDFs in it is deleted. Their cards keep their Library tags.")
check("exclude_confirm_text, a folder of one",
      act.exclude_confirm_text("Exam 1", "folder", 1)
      == "Exclude “Exam 1” from the index? The search index of 1 PDF in it is deleted. Their cards keep their Library tags.")

asked, forgot, repaints = [], [], []
act._ask_exclude = lambda parent, text, on_yes: asked.append((text, on_yes))
iq.forget = lambda name: forgot.append(name) or 0
_rs, _rt = ls.refresh_status, ls.refresh_trees
ls.refresh_status = lambda: repaints.append("status")
ls.refresh_trees = lambda: repaints.append("trees")


def _index(safe):
    os.makedirs(pdf_index.index_dir(UF, safe), exist_ok=True)
    return pdf_index.index_dir(UF, safe)


act.exclude(None, "pdf", "Intro_to_CBC", "04-L-Intro to CBC")
check("no index data: no question, recorded at once",
      asked == [] and drive_store.is_excluded(drive_store.load(UF), "Intro_to_CBC"))
check("exclude repaints Browse's sidebar and the Add tab's tree", repaints == ["status", "trees"], str(repaints))
check("an excluded PDF offers Include", menu_for(PDF_TAG)[-1] == "Include in Index", str(menu_for(PDF_TAG)))
repaints.clear()
_pending = iq.pending_names()
act.include("pdf", "Intro_to_CBC")
check("include clears it, repaints both, and queues nothing",
      not drive_store.is_excluded(drive_store.load(UF), "Intro_to_CBC") and repaints == ["status", "trees"]
      and iq.pending_names() == _pending)

forgot.clear()
d = _index("Intro_to_CBC")
act.exclude(None, "pdf", "Intro_to_CBC", "04-L-Intro to CBC")
check("with index data it asks first, deleting nothing yet",
      len(asked) == 1 and "04-L-Intro to CBC" in asked[0][0] and os.path.isdir(d)
      and not drive_store.is_excluded(drive_store.load(UF), "Intro_to_CBC"))
asked[0][1]()
check("Exclude records it, forgets queued jobs, deletes the index",
      drive_store.is_excluded(drive_store.load(UF), "Intro_to_CBC") and forgot == ["Intro_to_CBC"] and not os.path.isdir(d))
act.include("pdf", "Intro_to_CBC")
asked.clear(); forgot.clear()

act.pdfs_under = lambda folder: ["Intro_to_CBC", "Other"] if folder.startswith("2-BiB/Exam 1") else []
d1, d2 = _index("Intro_to_CBC"), _index("Other")
act.exclude(None, "folder", "2-BiB/Exam 1", "Exam 1")
check("a folder asks with its count", len(asked) == 1 and "2 PDFs" in asked[0][0], str(asked))
asked[0][1]()
check("...and deletes every covered index", not os.path.isdir(d1) and not os.path.isdir(d2)
      and sorted(forgot) == ["Intro_to_CBC", "Other"])
check("the excluded folder offers Include", menu_for(EXAM_TAG)[-1] == "Include in Index", str(menu_for(EXAM_TAG)))
check("a folder inside it offers neither", not {"Exclude from Index", "Include in Index"} & set(menu_for(WEEK_TAG)))
check("a PDF inside it offers neither", not {"Exclude from Index", "Include in Index"} & set(menu_for(PDF_TAG)))
check("library_index lists the excluded tags, covered ones included",
      {EXAM_TAG.casefold(), WEEK_TAG.casefold(), PDF_TAG.casefold()} <= ls.library_index()["excluded"])
check("is_excluded_tag", ls.is_excluded_tag(PDF_TAG) and not ls.is_excluded_tag("!Library"))
st = ls.pdf_status(["Intro_to_CBC", "x"], set(), lambda s: (False, False), excluded={"Intro_to_CBC"})
check("an excluded PDF gets no warning reason", st == {"x": ls.NOT_EMBEDDED}, str(st))
_model = QtGui.QStandardItemModel()
_item = QtGui.QStandardItem(PDF_TAG)
_model.appendRow(_item)


class _Del(ls.LibraryNameDelegate):
    def tag_of(self, index):
        return PDF_TAG


_view = QtWidgets.QTreeView()
_view.setModel(_model)
_d = _Del(_view)
_opt = QtWidgets.QStyleOptionViewItem()
_opt.widget = _view
_d.initStyleOption(_opt, _model.index(0, 0))
check("an excluded row draws in the disabled text colour",
      _opt.palette.color(QtGui.QPalette.ColorRole.Text)
      == _opt.palette.color(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text)
      and _opt.icon.isNull())
check("the delegate's tooltip names the exclusion", ls.tooltip_for(PDF_TAG).endswith("Excluded from the index"),
      str(ls.tooltip_for(PDF_TAG)))
act.include("folder", "2-BiB/Exam 1")
_failed_write = drive_store.set_excluded
drive_store.set_excluded = lambda *a: False
d1 = _index("Intro_to_CBC")
asked.clear()
act.exclude(None, "pdf", "Intro_to_CBC", "x")
asked[0][1]()
check("a failed write deletes nothing", os.path.isdir(d1))
drive_store.set_excluded = _failed_write
ls.refresh_status, ls.refresh_trees = _rs, _rt

section("manual indexing: a PDF whose text changed shows as stale")
embeddings = importlib.import_module("klausmate.embeddings")
_sig = embeddings.index_signature({})
os.makedirs(os.path.join(UF, "contexts"), exist_ok=True)
open(os.path.join(UF, "contexts", "Changed.txt"), "w").write("page text")
_d = pdf_index.index_dir(UF, "Changed")
os.makedirs(_d, exist_ok=True)


def _manifest(source_sig):
    json.dump({"version": pdf_index.INDEX_VERSION, "pages": [[0, "h"]], "embedded_rows": 1,
               "provider": _sig[0], "model": _sig[1], "dims": 0, "source_sig": list(source_sig)},
              open(os.path.join(_d, pdf_index.MANIFEST_FILE), "w"))


_manifest(pdf_index.source_signature(UF, "Changed"))
check("an index built from the current text is not stale", retention.index_status("Changed", _sig) == (True, False),
      str(retention.index_status("Changed", _sig)))
_manifest((1, 2))
check("an index built from other text is stale", retention.index_status("Changed", _sig) == (True, True))

raise SystemExit(report())
