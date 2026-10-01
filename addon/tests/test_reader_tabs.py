"""PDF reader 3/5 (Task 11): the tab strip lives inside the reader.

``ReaderTabs`` (reader_tabs.py) is the strip: ＋, the tab bar with a ✕ on
every tab, and the page label. ``PdfSidebar.tabs`` is one per reader, so the
editor dock and the Lecture panel each have their own tab set, persisted
under ``pdf_tabs.json["tabs"][host_key]``; the legacy top-level ``"open"``
list belongs to the editor.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_reader_tabs.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _qt_getattr(name):
    for module in (QtWidgets, QtCore, QtGui):
        if hasattr(module, name):
            return getattr(module, name)
    if name == "qconnect":
        return lambda signal, callback: signal.connect(callback)
    raise AttributeError(name)


shim.__getattr__ = _qt_getattr
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["klaus-test"])

UF = tempfile.mkdtemp(prefix="klaus_reader_tabs_")
sys.modules["klausmate"].USER_FILES = UF  # pre-settings layout
try:  # the settings seam, where it exists
    importlib.import_module("klausmate.settings").user_files_dir = UF
except Exception:
    pass

ph = importlib.import_module("klausmate.pdf_handler")
src = importlib.import_module("klausmate.pdf_source")
src.user_files_dir = lambda: UF
pj = importlib.import_module("klausmate.pdfjs_viewer")
pj.renderer_from_config = lambda cfg: "native"
pv = importlib.import_module("klausmate.pdf_viewer")
rt = importlib.import_module("klausmate.reader_tabs")

# load_open_tabs keeps only names whose context exists in the store.
os.makedirs(os.path.join(UF, "contexts"), exist_ok=True)
for _n in ("a", "b", "c", "d"):
    with open(os.path.join(UF, "contexts", _n + ".txt"), "w", encoding="utf-8") as f:
        f.write("page one\n")


def spin(n=3):
    for _ in range(n):
        app.processEvents()


def raw():
    with open(os.path.join(UF, "pdf_tabs.json"), encoding="utf-8") as f:
        return json.load(f)


section("ReaderTabs: open, focus, close")
t = rt.ReaderTabs()
seen = {"activated": [], "closed": [], "add": 0}
t.activated.connect(lambda n: seen["activated"].append(n))
t.closed.connect(lambda n: seen["closed"].append(n))
t.add_requested.connect(lambda: seen.__setitem__("add", seen["add"] + 1))
for n in ("a", "b", "c"):
    t.open(n)
check("open adds tabs in order", t.names() == ["a", "b", "c"], str(t.names()))
check("the last opened tab is current", t.current() == "c", str(t.current()))
check("each open activates its name exactly once",
      seen["activated"] == ["a", "b", "c"], str(seen["activated"]))
t.open("a")
check("opening an open name focuses it, no duplicate",
      t.names() == ["a", "b", "c"] and t.current() == "a", f"{t.names()} {t.current()}")
check("...and activates it (Task 12 opens a lecture PDF through this)",
      seen["activated"][-1] == "a", str(seen["activated"]))
seen["activated"].clear()
t.close("b")
check("close removes that tab, order kept", t.names() == ["a", "c"], str(t.names()))
check("close reports the closed name", seen["closed"] == ["b"], str(seen["closed"]))
check("closing a tab that is not current activates nothing",
      seen["activated"] == [], str(seen["activated"]))
t.close("a")
check("closing the current tab activates the neighbour Qt selects",
      t.names() == ["c"] and seen["activated"] == ["c"], f"{t.names()} {seen['activated']}")
t.close("zzz")
check("closing an unknown name is a no-op", t.names() == ["c"] and seen["closed"] == ["b", "a"])
seen["activated"].clear()
t.set_tabs(["d", "a", "b"], "a")
check("set_tabs replaces the tab set and selects the active name",
      t.names() == ["d", "a", "b"] and t.current() == "a", f"{t.names()} {t.current()}")
check("...without activating anything (a restore must not load)",
      seen["activated"] == [], str(seen["activated"]))
t.set_tabs(["a"], None)
check("set_tabs with no active name keeps the tab set", t.names() == ["a"])

section("ReaderTabs: decoration, ＋, page label")
t.set_tabs(["a", "b"], "a")
btn = t.bar.tabButton(1, QtWidgets.QTabBar.ButtonPosition.RightSide)
check("every tab carries a ✕ button", isinstance(btn, QtWidgets.QToolButton) and btn.text() == "✕")
check("...and a tooltip with its full name", t.bar.tabToolTip(1) == "b")
btn.click()
spin()
check("its ✕ closes that tab and reports it", t.names() == ["a"] and seen["closed"][-1] == "b")
check("the tab bar can be reordered by drag", t.bar.isMovable())
t.add_btn.click()
spin()
check("＋ emits add_requested", seen["add"] == 1, str(seen["add"]))
t.set_page(3, 12)
check("set_page writes the page label", t.page_label.text() == "3 / 12", t.page_label.text())
t.set_page(0, 0)
check("set_page(0, 0) clears it", t.page_label.text() == "")

section("pdf_handler: one tab set per host")
ph.save_open_tabs(UF, ["a", "b"])
ph.save_open_tabs(UF, ["c"], host_key="lecture")
check("the editor's set round-trips (default host)", ph.load_open_tabs(UF) == ["a", "b"],
      str(ph.load_open_tabs(UF)))
check("the lecture set round-trips beside it",
      ph.load_open_tabs(UF, host_key="lecture") == ["c"])
check("stored as pdf_tabs.json['tabs'][host_key]",
      raw().get("tabs") == {"editor": ["a", "b"], "lecture": ["c"]}, str(raw()))
ph.save_open_tabs(UF, ["d"], host_key="lecture")
check("saving one host leaves the other's set alone",
      ph.load_open_tabs(UF) == ["a", "b"], str(ph.load_open_tabs(UF)))
check("names with no stored context are dropped on read",
      (ph.save_open_tabs(UF, ["a", "gone"], host_key="lecture")
       or ph.load_open_tabs(UF, host_key="lecture")) == ["a"])
check("an unknown host starts empty", ph.load_open_tabs(UF, host_key="other") == [])

section("pdf_handler: the legacy list migrates into 'editor'")
with open(os.path.join(UF, "pdf_tabs.json"), "w", encoding="utf-8") as f:
    json.dump({"open": ["b", "a"], "placement": "left"}, f)
check("a legacy file reads as the editor's tabs", ph.load_open_tabs(UF) == ["b", "a"],
      str(ph.load_open_tabs(UF)))
check("...and the Lecture panel starts empty", ph.load_open_tabs(UF, host_key="lecture") == [])
ph.save_open_tabs(UF, ["c"], host_key="lecture")
data = raw()
check("the first save moves the legacy list under 'editor' and drops 'open'",
      data.get("tabs") == {"editor": ["b", "a"], "lecture": ["c"]} and "open" not in data,
      str(data))
check("other keys in the file survive", data.get("placement") == "left")
with open(os.path.join(UF, "pdf_tabs.json"), "w", encoding="utf-8") as f:
    json.dump({"open": ["a"], "tabs": {"editor": ["c"]}}, f)
check("once 'editor' exists the legacy list is ignored", ph.load_open_tabs(UF) == ["c"])

section("PdfSidebar: every reader has its own strip")
with open(os.path.join(UF, "pdf_tabs.json"), "w", encoding="utf-8") as f:
    json.dump({"tabs": {"editor": ["a", "b"], "lecture": ["c"]}}, f)
import contextlib  # noqa: E402
import io  # noqa: E402

_out = io.StringIO()
with contextlib.redirect_stdout(_out):
    lec = pv.PdfSidebar(None, host_key="lecture")
check("building the reader logs no failure (the strip's restore must not "
      "shadow the module's settings and break the renderer read)",
      "failed" not in _out.getvalue(), _out.getvalue())
lec.resize(500, 400)
lec.show()
spin()
check("PdfSidebar(None, host_key='lecture') has a ReaderTabs strip at .tabs",
      isinstance(getattr(lec, "tabs", None), rt.ReaderTabs))
check("...shown at the top of the reader",
      lec.layout().itemAt(0).widget() is lec.tabs and lec.tabs.isVisible())
check("...restored from its own host's set, as labels only",
      lec.tabs.names() == ["c"] and lec._name is None, f"{lec.tabs.names()} {lec._name}")
ed = pv.PdfSidebar(None)
check("the editor reader restores the editor's set", ed.tabs.names() == ["a", "b"])
check("the native viewer's page label moved into the strip (click → Go to Page travels with it)",
      ed.tabs.page_label is ed._viewer._page_label
      and ed._viewer._page_label.parentWidget() is ed.tabs)


def fake_load(sb):
    """load_pdf without a document: what the tab wiring sees of a load."""
    loads = []

    def _load(name):
        loads.append(name)
        sb._name = name
        sb._page_count = 3
        sb._notify_loaded(name)

    sb.load_pdf = _load
    return loads


section("PdfSidebar: loads, tab switches and closes")
ph.clear_active_pdf(UF)
ed_loads = fake_load(ed)
ed.load_pdf("c")
check("a load from anywhere opens and selects its tab",
      ed.tabs.names() == ["a", "b", "c"] and ed.tabs.current() == "c", str(ed.tabs.names()))
check("...without loading it a second time", ed_loads == ["c"], str(ed_loads))
check("...persists the editor's set", ph.load_open_tabs(UF) == ["a", "b", "c"])
check("...and points the editor's active PDF at it", ph.get_active_pdf(UF) == "c")
check("...and records it as recently used", "c" in ph.load_last_used(UF))
jumps = []
ed.jump_to_page = lambda p: jumps.append(p)
ed._current_page = 2
ed.tabs.open("a")
spin()
check("selecting a restored label loads it", ed_loads == ["c", "a"], str(ed_loads))
ed._current_page = 0
ed.tabs.open("c")
spin()
check("switching back reloads c", ed_loads[-1] == "c")
check("...and returns to c's remembered page", jumps == [2], str(jumps))
n = len(ed_loads)
ed.tabs.open("c")
check("activating the shown document does not reload it", len(ed_loads) == n)

lec_loads = fake_load(lec)
lec.load_pdf("d")
check("the Lecture reader keeps its own set", lec.tabs.names() == ["c", "d"]
      and ph.load_open_tabs(UF, host_key="lecture") == ["c", "d"]
      and ph.load_open_tabs(UF) == ["a", "b", "c"])
check("...and never moves the editor's active PDF", ph.get_active_pdf(UF) == "c",
      str(ph.get_active_pdf(UF)))

cleared = []
ed.clear = lambda: cleared.append(True)
for name in ("a", "b", "c"):
    ed.tabs.close(name)
spin()
check("closing every tab clears the reader", ed.tabs.names() == [] and cleared,
      f"{ed.tabs.names()} {cleared}")
check("...persists the empty set", ph.load_open_tabs(UF) == [])
check("...and drops the editor's active PDF", ph.get_active_pdf(UF) is None,
      str(ph.get_active_pdf(UF)))

section("PdfSidebar: the ＋ menu")


class FakeAction:
    def __init__(self, text):
        self.text = text
        self.enabled = True
        self.slots = []
        self.triggered = types.SimpleNamespace(connect=self.slots.append)

    def setEnabled(self, on):
        self.enabled = on


class FakeMenu:
    shown = []

    def __init__(self, *_a):
        self.items = []

    def addAction(self, text):
        act = FakeAction(text)
        self.items.append(act)
        return act

    def exec(self, *_a):
        FakeMenu.shown.append(self.items)

    def deleteLater(self):
        pass


for _n in ("a", "b", "c", "d"):
    os.makedirs(os.path.join(UF, "pdfs"), exist_ok=True)
    with open(os.path.join(UF, "pdfs", _n + ".pdf"), "wb") as f:
        f.write(b"%PDF-1.4\n")
ph._live_library_root = lambda: None
importlib.import_module("klausmate.drive_store").record_import(UF, "b", "Bee Lecture")
real_menu, pv.QMenu = pv.QMenu, FakeMenu
real_hook = sys.excepthook
sys.excepthook = lambda *a: print("[test] slot raised:", a[1])
try:
    ed.tabs.set_tabs(["a"], "a")
    ed.tabs.add_btn.click()
    spin()
finally:
    sys.excepthook = real_hook
    pv.QMenu = real_menu
check("＋ opens the stored-PDF menu", len(FakeMenu.shown) == 1, str(FakeMenu.shown))
items = FakeMenu.shown[-1] if FakeMenu.shown else []
texts = [i.text for i in items]
check("it lists every stored PDF that is not open, by display name",
      sorted(texts) == ["Bee Lecture", "c", "d"], str(texts))
pick = next((i for i in items if i.text == "Bee Lecture"), None)
if pick is not None:
    pick.slots[0](False)
check("choosing one opens it in this reader", ed.tabs.names() == ["a", "b"]
      and ed.tabs.current() == "b" and ed_loads[-1] == "b", f"{ed.tabs.names()} {ed_loads}")

for sb in (lec, ed):
    sb.cleanup()
    sb.close()
spin()

raise SystemExit(report())
