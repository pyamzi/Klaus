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

print("== folder rename collides with an existing folder ==")
tmp_r = tempfile.mkdtemp(prefix="klaus_drive_")
drive_store.add_folder(tmp_r, "Alpha")
drive_store.add_folder(tmp_r, "Beta")
drive_store.record_import(tmp_r, "Doc1", "Doc One.pdf")
drive_store.set_folder(tmp_r, "Doc1", "Alpha")
drive_store.record_import(tmp_r, "Doc2", "Doc Two.pdf")
drive_store.set_folder(tmp_r, "Doc2", "Beta")
rename_ok = drive_store.rename_folder(tmp_r, "Alpha", "Beta")
d = drive_store.load(tmp_r)
check("rename onto an existing folder still reports ok", rename_ok)
check("rename onto an existing folder merges, no duplicate",
      d["folders"].count("Beta") == 1 and d["folders"] == ["Beta"])
check("rename onto an existing folder migrates the old folder's pdf",
      d["pdfs"]["Doc1"]["folder"] == "Beta")
check("rename onto an existing folder leaves the target's own pdf alone",
      d["pdfs"]["Doc2"]["folder"] == "Beta")
shutil.rmtree(tmp_r, ignore_errors=True)

print("== two PDFs whose safe-names collide ==")
tmp_c = tempfile.mkdtemp(prefix="klaus_drive_")
drive_store.record_import(tmp_c, "Notes", "Notes (Week 1).pdf")
drive_store.set_folder(tmp_c, "Notes", "Anatomy")
# A second original file sanitizes to the same safe name (pdf_handler's
# _safe_basename collision) and re-imports over the same key.
drive_store.record_import(tmp_c, "Notes", "Notes (Week 2).pdf")
d = drive_store.load(tmp_c)
check("colliding safe-name keeps a single pdfs entry", len(d["pdfs"]) == 1)
check("colliding safe-name shows the latest import's display",
      d["pdfs"]["Notes"]["display"] == "Notes (Week 2).pdf")
check("colliding safe-name preserves the earlier folder assignment",
      d["pdfs"]["Notes"]["folder"] == "Anatomy")
shutil.rmtree(tmp_c, ignore_errors=True)

print("== drive.json holding a folder no pdf references ==")
tmp_o = tempfile.mkdtemp(prefix="klaus_drive_")
os.makedirs(tmp_o, exist_ok=True)
with open(os.path.join(tmp_o, "drive.json"), "w") as f:
    json.dump({"version": 1, "folders": ["Orphan/Nested"], "pdfs": {},
               "window": {}}, f)
d = drive_store.load(tmp_o)
check("load keeps a folder no pdf references", d["folders"] == ["Orphan/Nested"])
tree = drive_store.build_tree([], d)
check("build_tree lists the unreferenced folder, empty",
      "Orphan/Nested" in tree["folders"] and tree["folders"]["Orphan/Nested"] == [])
check("build_tree root stays empty", tree["root"] == [])
drive_store.remove_folder(tmp_o, "Orphan/Nested")
d2 = drive_store.load(tmp_o)
check("removing an unreferenced nested folder collapses it to its parent",
      d2["folders"] == ["Orphan"] and d2["pdfs"] == {})
shutil.rmtree(tmp_o, ignore_errors=True)

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
    "QMessageBox", "QAbstractItemView", "QFileSystemWatcher", "qconnect")}
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

print("== deck_curate recency ordering (last_used missing for some pdfs) ==")
try:
    tmp_dc = tempfile.mkdtemp(prefix="klaus_drive_")
    ctx_dir = os.path.join(tmp_dc, "contexts")
    os.makedirs(ctx_dir, exist_ok=True)
    for name in ("alpha", "beta", "gamma"):
        open(os.path.join(ctx_dir, name + ".txt"), "w").close()
    # beta has no last_used entry at all -- must fall back to file mtime,
    # interleaved correctly against alpha/gamma's explicit timestamps.
    os.utime(os.path.join(ctx_dir, "beta.txt"), (3000.0, 3000.0))
    with open(os.path.join(tmp_dc, "pdf_tabs.json"), "w") as f:
        json.dump({"last_used": {"alpha": 1000.0, "gamma": 5000.0}}, f)

    pkg.USER_FILES = tmp_dc  # deck_curate._user_files() reads this attr

    _created_menus = []

    class _FakeSignal:
        def connect(self, fn):
            pass

    class _FakeAction:
        def __init__(self, text, parent=None):
            self.text = text
            self.enabled = True

        def setEnabled(self, v):
            self.enabled = v

        @property
        def triggered(self):
            return _FakeSignal()

    class _FakeMenu:
        def __init__(self, parent=None):
            self.items = []
            _created_menus.append(self)

        def addAction(self, action):
            self.items.append(action)

        def addSeparator(self):
            self.items.append("sep")

        def exec(self, pos=None):
            pass

    class _FakeCursor:
        @staticmethod
        def pos():
            return None

    orig_menu, orig_action, orig_cursor = dc.QMenu, dc.QAction, dc.QCursor
    dc.QMenu, dc.QAction, dc.QCursor = _FakeMenu, _FakeAction, _FakeCursor
    try:
        dc._pick_pdf_menu()
    finally:
        dc.QMenu, dc.QAction, dc.QCursor = orig_menu, orig_action, orig_cursor

    menu = _created_menus[-1]
    order = [it.text for it in menu.items
             if isinstance(it, _FakeAction) and it.enabled]
    check("recency order interleaves explicit last_used and mtime fallback",
          order == ["gamma", "beta", "alpha"], order)
    shutil.rmtree(tmp_dc, ignore_errors=True)
except Exception as e:
    check("deck_curate recency ordering", False, f"{type(e).__name__}: {e}")

shutil.rmtree(tmp, ignore_errors=True)

print("== refresh_open_library glue (K-052 rework) ==")
pdf_drive = importlib.import_module("klausmate.pdf_drive")
# With no Library window open, the hook must be a silent no-op — it is
# called from a config-save path in Preferences, where an exception or a
# stray dialog would be a much worse bug than a stale column.
pdf_drive._instance = None
try:
    pdf_drive.refresh_open_library()
    check("no open Library -> silent no-op", True)
except Exception as e:
    check(f"no open Library -> silent no-op (raised {e!r})", False)


class _FakeWin:
    def __init__(self, alive, visible):
        self._is_alive, self._visible, self.refreshes = alive, visible, 0
    def _alive(self): return self._is_alive
    def isVisible(self): return self._visible
    def _refresh_rows(self): self.refreshes += 1


w = _FakeWin(alive=True, visible=True)
pdf_drive._instance = w
pdf_drive.refresh_open_library()
check("open+visible Library gets exactly one refresh", w.refreshes == 1)

w2 = _FakeWin(alive=True, visible=False)
pdf_drive._instance = w2
pdf_drive.refresh_open_library()
check("hidden Library is not refreshed", w2.refreshes == 0)

w3 = _FakeWin(alive=False, visible=True)
pdf_drive._instance = w3
pdf_drive.refresh_open_library()
check("dead C++ handle is not refreshed", w3.refreshes == 0)
pdf_drive._instance = None



print("== rescan_library_root glue runs end-to-end (K-075 regression trap) ==")
# The K-073 glue shipped WITHOUT `import os` in pdf_drive: every live call
# died on a NameError inside its own failure guard, the folder never
# synced, and stdout swallowed the evidence — while the pdf_handler
# engine tests stayed green, because nothing ever exercised the GLUE.
# This does, so a dangling name in it can never ship silently again.
_g_uf = tempfile.mkdtemp(prefix="drive_glue_uf_")
_g_root = tempfile.mkdtemp(prefix="drive_glue_root_")
os.makedirs(os.path.join(_g_uf, "contexts"))
pkg.USER_FILES = _g_uf
_ph = importlib.import_module("klausmate.pdf_handler")
_orig_llr = _ph._live_library_root
_ph._live_library_root = lambda: _g_root
try:
    _g_summary = pdf_drive.rescan_library_root()
finally:
    _ph._live_library_root = _orig_llr
check(
    "glue returns a summary dict (not the failure-path None)",
    isinstance(_g_summary, dict),
    repr(_g_summary),
)
check(
    "empty root -> quiet summary",
    bool(_g_summary) and _g_summary.get("moved") == [] and _g_summary.get("ingested") == [],
    repr(_g_summary),
)

print("== K-076: plan_folder_move (folder drag targets) ==")
try:
    pfm = pdf_drive.plan_folder_move
    check("top-level into folder", pfm("B", "A") == "A/B")
    check("nested source keeps its leaf", pfm("A/B", "C") == "C/B")
    check("nested to root", pfm("A/B", None) == "B")
    check("into itself is illegal", pfm("A", "A") is None)
    check("into own subtree is illegal", pfm("A", "A/B") is None)
    check("sibling name-prefix is NOT illegal", pfm("A", "AB") == "AB/A")
    check("same place is a no-op", pfm("A/B", "A") is None)
    check("root to root is a no-op", pfm("B", None) is None)
except Exception as e:
    check("plan_folder_move exists", False, f"{type(e).__name__}: {e}")

print("== K-076: apply_folder_change moves the disk dir with the tree ==")
_k_uf = tempfile.mkdtemp(prefix="drive_k76_uf_")
_k_root = tempfile.mkdtemp(prefix="drive_k76_root_")
try:
    _ph = importlib.import_module("klausmate.pdf_handler")
    os.makedirs(os.path.join(_k_uf, "contexts"))
    os.makedirs(os.path.join(_k_root, "Bootcamp"))
    with open(os.path.join(_k_root, "Bootcamp", "Biostats.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4 k76")
    _ph.save_library_map(_k_uf, {"Biostats": os.path.join("Bootcamp", "Biostats.pdf")})
    drive_store.record_import(_k_uf, "Biostats", "Biostats.pdf")
    drive_store.set_folder(_k_uf, "Biostats", "Bootcamp")
    drive_store.add_folder(_k_uf, "Archive")
    os.makedirs(os.path.join(_k_root, "Archive"))

    ok, why = pdf_drive.apply_folder_change(_k_uf, _k_root, "Bootcamp", "Archive/Bootcamp")
    check("move reports ok", ok, why)
    check("directory moved on disk",
          os.path.isfile(os.path.join(_k_root, "Archive", "Bootcamp", "Biostats.pdf"))
          and not os.path.exists(os.path.join(_k_root, "Bootcamp")))
    check("mapping rel rewritten",
          _ph.load_library_map(_k_uf).get("Biostats")
          == os.path.join("Archive", "Bootcamp", "Biostats.pdf"))
    _k_d = drive_store.load(_k_uf)
    check("store folder follows",
          _k_d["pdfs"]["Biostats"]["folder"] == "Archive/Bootcamp"
          and "Archive/Bootcamp" in _k_d["folders"])

    # THE K-076 trap: with a store-only rename (what _rename_folder shipped
    # as), the disk-truth rescan reverts the folder assignment on the very
    # next pass — live, that read as "my folder move snapped back".
    _k_sum = _ph.rescan_root(_k_uf, _k_root, drive_store.load(_k_uf).get("pdfs", {}))
    check("rescan is quiet after the move",
          _k_sum.get("moved") == [] and _k_sum.get("tree_changed") == [],
          repr(_k_sum))
    check("folder assignment SURVIVES the rescan",
          drive_store.load(_k_uf)["pdfs"]["Biostats"]["folder"] == "Archive/Bootcamp",
          repr(drive_store.load(_k_uf)["pdfs"]["Biostats"]))

    # Occupied destination (store side) refuses and changes nothing.
    drive_store.add_folder(_k_uf, "Slides")
    drive_store.add_folder(_k_uf, "Archive/Slides")
    ok2, why2 = pdf_drive.apply_folder_change(_k_uf, _k_root, "Slides", "Archive/Slides")
    check("occupied store destination refused", not ok2 and why2 == "exists", (ok2, why2))
    check("refused move leaves the source folder",
          "Slides" in drive_store.load(_k_uf)["folders"])

    # Occupied destination (disk side only) refuses too.
    drive_store.add_folder(_k_uf, "X")
    os.makedirs(os.path.join(_k_root, "X"))
    os.makedirs(os.path.join(_k_root, "Y", "X"))
    ok3, why3 = pdf_drive.apply_folder_change(_k_uf, _k_root, "X", "Y/X")
    check("occupied disk destination refused", not ok3 and why3 == "exists", (ok3, why3))

    # A tree-only folder (nothing on disk yet) still renames store-side.
    drive_store.add_folder(_k_uf, "Notes")
    ok4, why4 = pdf_drive.apply_folder_change(_k_uf, _k_root, "Notes", "Archive/Notes")
    check("tree-only folder renames", ok4, why4)
    _k_d = drive_store.load(_k_uf)
    check("tree-only rename lands in store, creates no dir",
          "Archive/Notes" in _k_d["folders"] and "Notes" not in _k_d["folders"]
          and not os.path.exists(os.path.join(_k_root, "Archive", "Notes")))

    ok5, why5 = pdf_drive.apply_folder_change(_k_uf, _k_root, "Archive", "a//b")
    check("invalid destination name refused", not ok5 and why5 == "invalid", (ok5, why5))
except Exception as e:
    check("apply_folder_change section", False, f"{type(e).__name__}: {e}")
finally:
    shutil.rmtree(_k_uf, ignore_errors=True)
    shutil.rmtree(_k_root, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
