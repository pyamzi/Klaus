"""Headless tests for drive_store + deck_curate/pdf_drive importability.

Run: env QT_QPA_PLATFORM=offscreen python3 test_drive.py
"""
import json
import os
import shutil
import sys
import tempfile
import types

ADDON = "/Users/pyamzi/Documents/Github/Addons/klausmate"

pkg = types.ModuleType("klausmate")
pkg.__path__ = [ADDON]
pkg.__package__ = "klausmate"
sys.modules["klausmate"] = pkg

import importlib

drive_store = importlib.import_module("klausmate.drive_store")

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


tmp = tempfile.mkdtemp(prefix="klaus_drive_")

print("== drive_store basics ==")
check("empty load is default-shaped",
      drive_store.load(tmp) == {"version": 1, "folders": [], "pdfs": {}, "window": {}})

drive_store.record_import(tmp, "Renal_Phys", "Renal Physiology (Dr. K).pdf")
d = drive_store.load(tmp)
check("record_import stores display",
      d["pdfs"]["Renal_Phys"]["display"] == "Renal Physiology (Dr. K).pdf")
check("record_import folder defaults None", d["pdfs"]["Renal_Phys"]["folder"] is None)
check("display_name helper", drive_store.display_name(tmp, "Renal_Phys")
      == "Renal Physiology (Dr. K).pdf")
check("display_name falls back to safe", drive_store.display_name(tmp, "Unknown") == "Unknown")

check("atomic save leaves no tmp",
      not os.path.exists(os.path.join(tmp, "drive.json.tmp")))

print("== folders ==")
check("add_folder ok", drive_store.add_folder(tmp, "Anatomy"))
check("add_folder nested", drive_store.add_folder(tmp, "Anatomy/Week 3"))
check("add_folder rejects empty", not drive_store.add_folder(tmp, "   "))
check("add_folder rejects double slash", not drive_store.add_folder(tmp, "a//b"))
check("add_folder strips outer slashes",
      drive_store.add_folder(tmp, "/Physio/") and "Physio" in drive_store.load(tmp)["folders"])
check("add_folder idempotent",
      drive_store.add_folder(tmp, "Anatomy")
      and drive_store.load(tmp)["folders"].count("Anatomy") == 1)

drive_store.set_folder(tmp, "Renal_Phys", "Anatomy/Week 3")
check("set_folder assigns",
      drive_store.load(tmp)["pdfs"]["Renal_Phys"]["folder"] == "Anatomy/Week 3")
drive_store.set_folder(tmp, "Renal_Phys", None)
check("set_folder to root", drive_store.load(tmp)["pdfs"]["Renal_Phys"]["folder"] is None)
drive_store.set_folder(tmp, "Renal_Phys", "Anatomy/Week 3")

drive_store.set_folder(tmp, "Ghost_Pdf", "Brand/New")
check("set_folder auto-creates folder",
      "Brand/New" in drive_store.load(tmp)["folders"])

print("== rename / remove folder ==")
drive_store.rename_folder(tmp, "Anatomy", "Anatomy 2")
d = drive_store.load(tmp)
check("rename_folder rewrites subfolders", "Anatomy 2/Week 3" in d["folders"])
check("rename_folder rewrites pdf refs",
      d["pdfs"]["Renal_Phys"]["folder"] == "Anatomy 2/Week 3")
check("rename_folder rejects bad name",
      not drive_store.rename_folder(tmp, "Anatomy 2", "  "))

drive_store.remove_folder(tmp, "Anatomy 2/Week 3")
d = drive_store.load(tmp)
check("remove_folder reparents pdf", d["pdfs"]["Renal_Phys"]["folder"] == "Anatomy 2")
check("remove_folder drops path", "Anatomy 2/Week 3" not in d["folders"])

drive_store.add_folder(tmp, "Top/Mid")
drive_store.set_folder(tmp, "Renal_Phys", "Top/Mid")
drive_store.remove_folder(tmp, "Top")
d = drive_store.load(tmp)
check("remove_folder reparents subfolder to root", "Mid" in d["folders"])
check("remove_folder reparents nested pdf", d["pdfs"]["Renal_Phys"]["folder"] == "Mid")

print("== rename display / remove pdf ==")
drive_store.rename_display(tmp, "Renal_Phys", "Kidneys wk3")
check("rename_display", drive_store.display_name(tmp, "Renal_Phys") == "Kidneys wk3")
drive_store.rename_display(tmp, "Renal_Phys", "   ")
check("rename_display ignores blank", drive_store.display_name(tmp, "Renal_Phys") == "Kidneys wk3")
drive_store.remove_pdf(tmp, "Ghost_Pdf")
check("remove_pdf", "Ghost_Pdf" not in drive_store.load(tmp)["pdfs"])
drive_store.remove_pdf(tmp, "Never_Existed")  # must not raise
check("remove_pdf on missing is a no-op", True)

print("== window state ==")
drive_store.save_window_state(tmp, {"x": 10, "y": 20, "w": 900, "h": 600,
                                    "splitter": [280, 620]})
w = drive_store.get_window_state(tmp)
check("window roundtrip", w["w"] == 900 and w["splitter"] == [280, 620])
check("window survives other writes",
      (drive_store.add_folder(tmp, "Zed")
       and drive_store.get_window_state(tmp)["h"] == 600))

print("== build_tree ==")
data = drive_store.load(tmp)
contexts = ["Renal_Phys.txt", "Loose_One.txt", "Zebra.txt"]
tree = drive_store.build_tree(contexts, data)
check("known pdf in its folder",
      any(p["safe"] == "Renal_Phys" for p in tree["folders"].get("Mid", [])))
check("orphan context lands at root",
      {p["safe"] for p in tree["root"]} == {"Loose_One", "Zebra"})
check("orphan display falls back to safe",
      all(p["display"] == p["safe"] for p in tree["root"]))
check("empty folders still present", "Zed" in tree["folders"])
check("folders sorted", list(tree["folders"]) == sorted(tree["folders"]))
check("root sorted by display",
      [p["display"] for p in tree["root"]] == ["Loose_One", "Zebra"])
tree2 = drive_store.build_tree([], data)
check("pdf entry with no file is omitted",
      all(not v for v in tree2["folders"].values()) and tree2["root"] == [])

print("== prune ==")
drive_store.prune(tmp, ["Renal_Phys.txt"])
check("prune keeps live entry", "Renal_Phys" in drive_store.load(tmp)["pdfs"])
drive_store.prune(tmp, [])
check("prune drops dead entries", drive_store.load(tmp)["pdfs"] == {})

print("== corruption resilience ==")
with open(os.path.join(tmp, "drive.json"), "w") as f:
    f.write("{not json")
check("corrupt json -> default", drive_store.load(tmp)["pdfs"] == {})
with open(os.path.join(tmp, "drive.json"), "w") as f:
    json.dump({"version": 99, "pdfs": {"x": {}}}, f)
check("version mismatch -> default", drive_store.load(tmp)["pdfs"] == {})
with open(os.path.join(tmp, "drive.json"), "w") as f:
    json.dump({"version": 1, "folders": "nope", "pdfs": [1, 2]}, f)
check("wrong types -> default-shaped",
      drive_store.load(tmp) == {"version": 1, "folders": [], "pdfs": {}, "window": {}})
check("write after corruption recovers",
      (drive_store.record_import(tmp, "A", "a.pdf") or True)
      and drive_store.display_name(tmp, "A") == "a.pdf")

print("== aqt-dependent modules import cleanly (stubbed) ==")


def stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Hook(list):
    def append(self, fn):
        list.append(self, fn)


class _Op:
    def __init__(self, *a, **k): pass
    def success(self, *a, **k): return self
    def failure(self, *a, **k): return self
    def without_collection(self): return self
    def run_in_background(self): pass


hooks = stub("aqt.gui_hooks")
for h in ("webview_did_receive_js_message", "overview_will_render_bottom",
          "deck_browser_will_render_content", "profile_will_close",
          "top_toolbar_did_init_links"):
    setattr(hooks, h, _Hook())

aqt_mod = stub("aqt", mw=None, gui_hooks=hooks)
aqt_mod.dialogs = types.SimpleNamespace(
    open=lambda *a, **k: None, register_dialog=lambda *a, **k: None,
    markClosed=lambda *a, **k: None)
stub("aqt.operations", CollectionOp=_Op, QueryOp=_Op)
stub("aqt.utils", tooltip=lambda *a, **k: None, askUser=lambda *a, **k: False,
     showWarning=lambda *a, **k: None, showInfo=lambda *a, **k: None)


class _Any:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()
    # Qt enum members are ints (UserRole + 1 is read at import time).
    def __add__(self, other): return _Any()
    def __radd__(self, other): return _Any()


qt_names = {n: _Any for n in (
    "QAction", "QComboBox", "QCursor", "QDialog", "QDialogButtonBox", "QLabel",
    "QMenu", "QTimer", "QVBoxLayout", "QHBoxLayout", "QPushButton", "QSlider",
    "QSplitter", "QTreeWidget", "QTreeWidgetItem", "QWidget", "QInputDialog",
    "QMessageBox", "QAbstractItemView", "qconnect")}
# Qt is an enum namespace, not a base class — an instance chains attributes
# (Qt.ItemDataRole.UserRole is read at import time in pdf_drive).
qt_names["Qt"] = _Any()
stub("aqt.qt", **qt_names)
stub("aqt.webview", AnkiWebView=_Any)
stub("aqt.deckbrowser", DeckBrowser=_Any, DeckBrowserBottomBar=_Any)
stub("aqt.main", MainWebView=_Any)
stub("aqt.editor", Editor=_Any)
stub("anki")
stub("anki.collection", AddNoteRequest=_Any)

for mod in ("klausmate.deck_curate", "klausmate.pdf_drive"):
    try:
        importlib.import_module(mod)
        check(f"{mod.split('.')[-1]} imports", True)
    except Exception as e:
        check(f"{mod.split('.')[-1]} imports", False, f"{type(e).__name__}: {e}")

# deck_curate pure surface
try:
    dc = sys.modules["klausmate.deck_curate"]
    check("armed starts empty", dc.armed() is None)
    check("CURATE_CMD is underscore-namespaced (not swallowed by editor bridge)",
          dc.CURATE_CMD == "klausmate_curate"
          and not dc.CURATE_CMD.startswith("klausmate:"))
    check("js handler ignores foreign messages",
          dc.on_deck_js_message((False, None), "something:else", None) == (False, None))
except Exception as e:
    check("deck_curate surface", False, str(e))

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
