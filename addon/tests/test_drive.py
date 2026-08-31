"""Headless tests for drive_store + deck_curate/pdf_drive importability.

Run: env QT_QPA_PLATFORM=offscreen python3 test_drive.py
"""
import json
import os
import shutil
import sys
import tempfile
import types

ADDON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "klausmate"
)

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

print("== K-088: toolbar order (Decks Add Library Browse Stats Sync) ==")
try:
    class _FakeToolbar:
        def create_link(self, cmd, label, func, tip=None, id=None):
            return f"<a id={id!r} cmd={cmd!r}>{label}</a>"

    # Stock 26.8.1 shape: each link is an HTML string carrying its name.
    stock = [
        "<a id='decks' cmd='decks'>Decks</a>",
        "<a id='add' cmd='add'>Add</a>",
        "<a id='browse' cmd='browse'>Browse</a>",
        "<a id='stats' cmd='stats'>Stats</a>",
        "<a id='sync' cmd='sync'>Sync</a>",
    ]
    links = list(stock)
    pdf_drive._on_toolbar_links(links, _FakeToolbar())
    labels = [l.split(">")[1].split("<")[0] for l in links]
    check("Library sits between Add and Browse",
          labels == ["Decks", "Add", "Library", "Browse", "Stats", "Sync"],
          repr(labels))

    # Another addon added its own link first: position still resolves
    # off Browse, not off a fixed index.
    links = ["<a id='other' cmd='other'>Other</a>"] + list(stock)
    pdf_drive._on_toolbar_links(links, _FakeToolbar())
    labels = [l.split(">")[1].split("<")[0] for l in links]
    check("still lands directly before Browse when the list shifts",
          labels.index("Library") == labels.index("Browse") - 1,
          repr(labels))

    # No Browse link at all (future rename): must not raise, must still
    # land in a sane spot.
    links = ["<a id='decks' cmd='decks'>Decks</a>",
             "<a id='add' cmd='add'>Add</a>"]
    pdf_drive._on_toolbar_links(links, _FakeToolbar())
    labels = [l.split(">")[1].split("<")[0] for l in links]
    check("degrades to third place with no Browse link",
          labels == ["Decks", "Add", "Library"], repr(labels))
except Exception as e:
    check("K-088 section", False, f"{type(e).__name__}: {e}")

print("== K-117 source pins: labels, guarded import, exec ban ==")
# code_only (comments AND strings stripped) is the house pin tool — a
# docstring merely *mentioning* dlg.exec() must not fail the ban, and a
# comment mentioning an old label must not satisfy a rename pin.
_SKILL_SCRIPTS = os.path.join(
    os.path.dirname(ADDON), ".claude", "skills", "klaus-test", "scripts"
)
sys.path.insert(0, _SKILL_SCRIPTS)
from anki_stubs import code_only  # noqa: E402

_PD_SRC = open(os.path.join(ADDON, "pdf_drive.py")).read()
_PD_CODE = code_only(_PD_SRC)
_PD_FLAT = _PD_CODE.replace(" ", "")

check("four headers: PDF / Retention / Cards / Notes",
      '["PDF", "Retention", "Cards", "Notes"]' in _PD_SRC
      and "setColumnCount(4)" in _PD_SRC)
check("worst-retention-first default sort survives the new columns",
      "sortByColumn(1, Qt.SortOrder.AscendingOrder)" in _PD_SRC)
check("the context menu opts into visible tooltips",
      "menu.setToolTipsVisible(True)" in _PD_CODE)
check("index actions renamed for clarity, old labels gone",
      '"Update Search Index"' in _PD_SRC
      and '"Add to Search Index"' in _PD_SRC
      and '"Re-index"' not in _PD_SRC
      and '"Add to index"' not in _PD_SRC)
check("retention_history import is guarded with a None fallback so the "
      "Library stands alone until/despite K-118",
      "from . import retention_history" in _PD_CODE
      and "retention_history=None" in _PD_FLAT
      and "if retention_history is not None" in _PD_CODE)
check("K-114 exec ban: no app-modal dlg.exec()/msg.exec() in pdf_drive",
      "dlg.exec()" not in _PD_FLAT and "msg.exec()" not in _PD_FLAT)
check("every remaining .exec( is the sanctioned popup QMenu.exec — the "
      "path the crash saga cleared (test_bridge_reentrancy's rule 2)",
      _PD_FLAT.count(".exec(") == _PD_FLAT.count("menu.exec(")
      and _PD_FLAT.count(".exec(") >= 1)
check("Match Sensitivity opens window-modal with a callback (K-114: "
      "dlg.open() + accepted, never exec)",
      "dlg.open()" in _PD_FLAT and "dlg.accepted.connect(apply)" in _PD_FLAT)

print("== K-117: real offscreen Qt — drops, sort, rows, menus, suspend ==")
# PyQt6 is installed for this interpreter (unlike Anki's bundled one),
# so the drag/drop and row logic runs on GENUINE widgets offscreen. The
# _Any-stubbed sections above stay as-is; here klausmate.* is purged and
# re-imported against an aqt.qt shim backed by the real PyQt6 modules.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC  # noqa: E402
    from PyQt6 import QtGui as _QtG  # noqa: E402
    from PyQt6 import QtWidgets as _QtW  # noqa: E402
    _HAVE_QT = True
except Exception as _qt_e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — "
          "widget tests skipped; the source pins above still ran")

if _HAVE_QT:
    _qt_shim = types.ModuleType("aqt.qt")

    def _qt_getattr(name, _mods=(_QtW, _QtC, _QtG)):
        for _m in _mods:
            if hasattr(_m, name):
                return getattr(_m, name)
        if name == "qconnect":
            return lambda sig, fn: sig.connect(fn)
        raise AttributeError(name)

    _qt_shim.__getattr__ = _qt_getattr
    sys.modules["aqt.qt"] = _qt_shim

    # CollectionOp that runs synchronously against a registered fake col
    # — the suspend wiring below needs deterministic completion.
    _run_now_col = []

    class _RunNowCollectionOp:
        def __init__(self, parent=None, op=None):
            self._op, self._cb = op, None

        def success(self, cb):
            self._cb = cb
            return self

        def failure(self, cb):
            return self

        def run_in_background(self):
            res = self._op(_run_now_col[0])
            if self._cb:
                self._cb(res)

    sys.modules["aqt.operations"].CollectionOp = _RunNowCollectionOp

    for _name in [m for m in list(sys.modules) if m.startswith("klausmate.")]:
        del sys.modules[_name]
    sys.modules["klausmate"] = pkg
    _rq_uf = tempfile.mkdtemp(prefix="klaus_k117_uf_")
    os.makedirs(os.path.join(_rq_uf, "contexts"), exist_ok=True)
    pkg.USER_FILES = _rq_uf
    pdf_drive = importlib.import_module("klausmate.pdf_drive")
    app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])

    class _K117Win:
        """Recording stand-in on _LibraryTree's _window seam."""

        def __init__(self):
            self.moved = []
            self.folder_moves = []
            self.dropped = []
            self.rebuilds = 0

        def _move_pdf(self, safe, dest):
            self.moved.append((safe, dest))

        def _move_folder(self, old, new):
            self.folder_moves.append((old, new))

        def _on_dropped_paths(self, paths, folder=None):
            self.dropped.append((list(paths), folder))

        def rebuild_tree(self):
            self.rebuilds += 1

    _fw = _K117Win()
    tree = pdf_drive._LibraryTree(_fw)
    tree.setColumnCount(4)
    _folder = pdf_drive._LibraryItem(tree, ["Anatomy"])
    _folder.setData(0, pdf_drive._ROLE_FOLDER, "Anatomy")
    _nested = pdf_drive._LibraryItem(_folder, ["Nested.pdf"])
    _nested.setData(0, pdf_drive._ROLE_SAFE, "Nested")
    _zoo = pdf_drive._LibraryItem(tree, ["Zoo"])
    _zoo.setData(0, pdf_drive._ROLE_FOLDER, "Zoo")
    _loose = pdf_drive._LibraryItem(tree, ["Loose.pdf"])
    _loose.setData(0, pdf_drive._ROLE_SAFE, "Loose")
    _folder.setExpanded(True)
    tree.resize(420, 480)
    tree.show()
    app.processEvents()

    _BTN = _QtC.Qt.MouseButton.LeftButton
    _MOD = _QtC.Qt.KeyboardModifier.NoModifier
    _COPY = _QtC.Qt.DropAction.CopyAction

    _md_pdf = _QtC.QMimeData()
    _md_pdf.setUrls([_QtC.QUrl.fromLocalFile("/tmp/Lecture 3.pdf"),
                     _QtC.QUrl.fromLocalFile("/tmp/notes.txt")])
    _enter = _QtG.QDragEnterEvent(_QtC.QPoint(30, 30), _COPY, _md_pdf,
                                  _BTN, _MOD)
    tree.dragEnterEvent(_enter)
    check("external drag carrying a .pdf url is accepted", _enter.isAccepted())
    _md_txt = _QtC.QMimeData()
    _md_txt.setText("hello")
    _enter2 = _QtG.QDragEnterEvent(_QtC.QPoint(30, 30), _COPY, _md_txt,
                                   _BTN, _MOD)
    tree.dragEnterEvent(_enter2)
    check("a non-file drag is NOT accepted (internal-move policy intact)",
          not _enter2.isAccepted())
    _mv = _QtG.QDragMoveEvent(_QtC.QPoint(30, 30), _COPY, _md_pdf, _BTN, _MOD)
    tree.dragMoveEvent(_mv)
    check("dragMove keeps accepting an external .pdf over the rows",
          _mv.isAccepted())

    def _drop_at(point_f, md):
        ev = _QtG.QDropEvent(point_f, _COPY, md, _BTN, _MOD)
        tree.dropEvent(ev)
        return ev

    _drop_at(_QtC.QPointF(tree.visualItemRect(_folder).center()), _md_pdf)
    check("drop on a folder row imports into that folder, .pdf only "
          "(the .txt url is filtered out)",
          _fw.dropped == [(["/tmp/Lecture 3.pdf"], "Anatomy")],
          repr(_fw.dropped))
    _fw.dropped.clear()
    _drop_at(_QtC.QPointF(tree.visualItemRect(_nested).center()), _md_pdf)
    check("drop on a PDF row targets that row's folder",
          _fw.dropped == [(["/tmp/Lecture 3.pdf"], "Anatomy")],
          repr(_fw.dropped))
    _fw.dropped.clear()
    _drop_at(_QtC.QPointF(200.0, 400.0), _md_pdf)
    check("drop on empty space lands at the root",
          _fw.dropped == [(["/tmp/Lecture 3.pdf"], None)], repr(_fw.dropped))
    for _ in range(3):
        app.processEvents()
    check("external drops schedule the K-076 next-tick rebuild",
          _fw.rebuilds >= 1, repr(_fw.rebuilds))

    class _InternalDrop(_QtG.QDropEvent):
        """Synthetic events return source() None; the internal path needs
        source() is the tree, and a Python-level override reaches our
        dropEvent because the call never crosses back into C++."""

        def __init__(self, src, *a):
            super().__init__(*a)
            self._src = src

        def source(self):
            return self._src

    # Bound, not inline: QDropEvent does not own its QMimeData, so an
    # inline temporary is freed while the event still points at it.
    _md_int = _QtC.QMimeData()
    tree.setCurrentItem(_loose)
    _iev = _InternalDrop(
        tree, _QtC.QPointF(tree.visualItemRect(_folder).center()),
        _QtC.Qt.DropAction.MoveAction, _md_int, _BTN, _MOD)
    tree.dropEvent(_iev)
    check("internal row drag still lands in _move_pdf (regression pin)",
          _fw.moved == [("Loose", "Anatomy")], repr(_fw.moved))
    check("internal drop finishes accepted as IgnoreAction (K-076)",
          _iev.isAccepted()
          and _iev.dropAction() == _QtC.Qt.DropAction.IgnoreAction)
    tree.setCurrentItem(_folder)
    _iev2 = _InternalDrop(
        tree, _QtC.QPointF(tree.visualItemRect(_zoo).center()),
        _QtC.Qt.DropAction.MoveAction, _md_int, _BTN, _MOD)
    tree.dropEvent(_iev2)
    check("internal folder drag still routes through plan_folder_move",
          _fw.folder_moves == [("Anatomy", "Zoo/Anatomy")],
          repr(_fw.folder_moves))

    print("== K-117: numeric sort on the new columns ==")
    _sort_tree = pdf_drive._LibraryTree(_K117Win())
    _sort_tree.setColumnCount(4)
    _sa = pdf_drive._LibraryItem(_sort_tree, ["a", "", "5", "900"])
    _sa.setData(2, pdf_drive._ROLE_SORT, 5.0)
    _sa.setData(3, pdf_drive._ROLE_SORT, 900.0)
    _sb = pdf_drive._LibraryItem(_sort_tree, ["b", "", "0", "1,000"])
    _sb.setData(2, pdf_drive._ROLE_SORT, 0.0)
    _sb.setData(3, pdf_drive._ROLE_SORT, 1000.0)
    _sc = pdf_drive._LibraryItem(_sort_tree, ["c", "", "—", "—"])
    _sc.setData(2, pdf_drive._ROLE_SORT, pdf_drive._UNKNOWN_SORT)
    _sc.setData(3, pdf_drive._ROLE_SORT, pdf_drive._UNKNOWN_SORT)
    _sort_tree.setSortingEnabled(True)
    _sort_tree.sortByColumn(3, _QtC.Qt.SortOrder.AscendingOrder)
    _names = [_sort_tree.topLevelItem(i).text(0) for i in range(3)]
    check("Notes column sorts numerically (the '1,000' < '900' string "
          "trap) with unknowns sunk", _names == ["a", "b", "c"],
          repr(_names))
    _sort_tree.sortByColumn(3, _QtC.Qt.SortOrder.DescendingOrder)
    _names = [_sort_tree.topLevelItem(i).text(0) for i in range(3)]
    check("descending still keeps unknowns at the bottom",
          _names == ["b", "a", "c"], repr(_names))
    _sort_tree.sortByColumn(2, _QtC.Qt.SortOrder.AscendingOrder)
    _names = [_sort_tree.topLevelItem(i).text(0) for i in range(3)]
    check("Cards column: a real zero sorts with the numbers, not the "
          "unknowns", _names == ["b", "a", "c"], repr(_names))

    print("== K-117: _apply_row — counts, alignment, suspended dim ==")

    class _RowHost:
        _set_retention_color = pdf_drive.DriveWindow._set_retention_color
        _set_suspended_dim = pdf_drive.DriveWindow._set_suspended_dim

    _host = _RowHost()
    _apply = pdf_drive.DriveWindow._apply_row
    _item = pdf_drive._LibraryItem(_sort_tree, ["X.pdf"])
    _full = {"indexed": True, "stale": False, "retention": 0.42,
             "matched_cards": 7, "new_pct": 0.5,
             "card_count": 5, "note_count": 4, "suspended_count": 2}
    _apply(_host, _item, _full)
    check("fresh row renders retention / cards / notes cells",
          _item.text(1) == "42%" and _item.text(2) == "5"
          and _item.text(3) == "4",
          repr((_item.text(1), _item.text(2), _item.text(3))))
    check("numeric cells are right-aligned",
          all(int(_item.textAlignment(cc))
              & int(_QtC.Qt.AlignmentFlag.AlignRight) for cc in (1, 2, 3)))
    check("sort roles carry the counts",
          _item.data(2, pdf_drive._ROLE_SORT) == 5.0
          and _item.data(3, pdf_drive._ROLE_SORT) == 4.0)
    check("hover detail keeps matched/suspended/unseen",
          "7 matched cards" in _item.toolTip(2)
          and "2 suspended" in _item.toolTip(2)
          and "50% unseen" in _item.toolTip(3))
    _bare = {"indexed": True, "stale": False, "retention": 0.9,
             "matched_cards": 3, "new_pct": 0.0}
    _apply(_host, _item, _bare)
    check("counts absent (pre-K-118 rows) -> em-dashes + unknown sort, "
          "so this card stands alone",
          _item.text(2) == "—" and _item.text(3) == "—"
          and _item.data(2, pdf_drive._ROLE_SORT) == pdf_drive._UNKNOWN_SORT
          and _item.data(3, pdf_drive._ROLE_SORT) == pdf_drive._UNKNOWN_SORT)
    _susp = dict(_full, card_count=0, suspended_count=6)
    _apply(_host, _item, _susp)
    check("fully suspended row says so in the Cards cell",
          _item.text(2) == "suspended", repr(_item.text(2)))
    check("fully suspended row dims every column to the faint token "
          "(#AAAAAA in the light palette)",
          _item.foreground(0).color().name().lower() == "#aaaaaa"
          and _item.foreground(1).color().name().lower() == "#aaaaaa"
          and _item.foreground(3).color().name().lower() == "#aaaaaa")
    _apply(_host, _item, _full)
    check("a later unsuspend restores the default foreground",
          _item.data(0, _QtC.Qt.ItemDataRole.ForegroundRole) is None
          and _item.text(2) == "5")
    _apply(_host, _item, {"indexed": False})
    check("not-embedded keeps its status string in the Cards cell",
          _item.text(1) == "—" and _item.text(2) == "not embedded")

    print("== K-117: suspend/unsuspend wiring ==")

    class _FakeSched:
        def __init__(self):
            self.suspended, self.unsuspended = [], []

        def suspend_cards(self, cids):
            self.suspended.append(list(cids))
            return "op-changes"

        def unsuspend_cards(self, cids):
            self.unsuspended.append(list(cids))
            return "op-changes"

    class _FakeCol:
        def __init__(self, cids):
            self.queries, self._cids = [], list(cids)
            self.sched = _FakeSched()

        def find_cards(self, q):
            self.queries.append(q)
            return list(self._cids)

    class _StatusStub:
        def __init__(self):
            self.texts = []

        def setText(self, t):
            self.texts.append(t)

    class _SuspendHost:
        def __init__(self):
            self.status = _StatusStub()
            self.refreshes = 0

        def _alive(self):
            return True

        def _refresh_rows(self):
            self.refreshes += 1

    _real_ts = importlib.import_module("klausmate.tag_sync")
    _fake_ts = types.SimpleNamespace(
        get_stored_tag=lambda safe: None,
        _folder_and_display=lambda safe: ("Anatomy/Week 3",
                                          'Renal "Phys".pdf'),
        desired_tag=_real_ts.desired_tag,
        _escape_tag=_real_ts._escape_tag,
    )
    _orig_ts, _orig_mw = pdf_drive.tag_sync, pdf_drive.mw
    _sh = _SuspendHost()
    try:
        _col = _FakeCol([11, 22])
        _run_now_col[:] = [_col]
        pdf_drive.tag_sync = _fake_ts
        pdf_drive.mw = types.SimpleNamespace(col=_col)
        pdf_drive.DriveWindow._set_suspended_cards(_sh, "Renal_Phys", True)
        _want_q = 'tag:"!Library::Anatomy::Week_3::Renal_\\"Phys\\""'
        check("no stored tag -> the DERIVED desired_tag is queried, "
              "quotes escaped", _col.queries == [_want_q],
              repr(_col.queries))
        check("suspend reaches col.sched.suspend_cards with the found "
              "cids", _col.sched.suspended == [[11, 22]]
              and _col.sched.unsuspended == [])
        check("a finished suspend refreshes the rows", _sh.refreshes == 1)

        _col2 = _FakeCol([7])
        _run_now_col[:] = [_col2]
        pdf_drive.mw = types.SimpleNamespace(col=_col2)
        _fake_ts.get_stored_tag = lambda safe: "!Library::Stored_Tag"
        pdf_drive.DriveWindow._set_suspended_cards(_sh, "Renal_Phys", False)
        check("a stored tag wins over the derived one (tag_sync's "
              "never-a-derived-guess rule)",
              _col2.queries == ['tag:"!Library::Stored_Tag"'],
              repr(_col2.queries))
        check("unsuspend reaches col.sched.unsuspend_cards",
              _col2.sched.unsuspended == [[7]]
              and _col2.sched.suspended == [])

        _col3 = _FakeCol([])
        _run_now_col[:] = [_col3]
        pdf_drive.mw = types.SimpleNamespace(col=_col3)
        pdf_drive.DriveWindow._set_suspended_cards(_sh, "Renal_Phys", True)
        check("no tagged cards -> status line, no sched call",
              _col3.sched.suspended == [] and _col3.sched.unsuspended == []
              and _sh.status.texts
              and "index it first" in _sh.status.texts[-1],
              repr(_sh.status.texts))
    finally:
        pdf_drive.tag_sync, pdf_drive.mw = _orig_ts, _orig_mw
        _run_now_col[:] = []

    print("== K-117: the PDF context menu on real QMenus ==")
    _menu_row_full = {"indexed": True, "stale": False, "retention": 0.42,
                      "matched_cards": 7, "new_pct": 0.5,
                      "label": "Loose Lecture",
                      "card_count": 5, "note_count": 4,
                      "suspended_count": 2}

    def _build_menu(row):
        host = types.SimpleNamespace(rows={"Loose": row})
        m = _QtW.QMenu()
        m.setToolTipsVisible(True)  # _on_context_menu's choke point
        pdf_drive.DriveWindow._build_pdf_menu(host, m, _loose)
        return host, m

    _orig_rh = pdf_drive.retention_history
    pdf_drive.retention_history = None
    _h0, _m0 = _build_menu(_menu_row_full)
    check("no retention_history module -> no history action (the card "
          "stands alone)",
          "Retention History…" not in [a.text() for a in _m0.actions()])
    _calls = []
    pdf_drive.retention_history = types.SimpleNamespace(
        open_history_dialog=lambda parent, safe, label: _calls.append(
            (parent, safe, label)))
    _h1, _m1 = _build_menu(_menu_row_full)
    _labels = [a.text() for a in _m1.actions() if not a.isSeparator()]
    _tips = {a.text(): a.toolTip() for a in _m1.actions()}
    _hist = next(a for a in _m1.actions()
                 if a.text() == "Retention History…")
    _hist.trigger()
    check("history action calls open_history_dialog(parent, safe, label) "
          "— the exact K-118 contract",
          _calls == [(_h1, "Loose", "Loose Lecture")], repr(_calls))
    pdf_drive.retention_history = _orig_rh

    check("indexed row offers 'Update Search Index' with the deck-safety "
          "tooltip",
          "Update Search Index" in _labels
          and _tips.get("Update Search Index")
          == "Re-reads the PDF and recomputes which cards match it. "
             "Does not touch your decks.")
    check("curate carries the copies-into-a-new-deck tooltip",
          _tips.get("Curate Deck from This PDF…")
          == "Copies the matching cards into a new deck.")
    check("both suspend actions offered while both counts are positive",
          "Suspend Cards" in _labels and "Unsuspend Cards" in _labels)
    _, _m2 = _build_menu(dict(_menu_row_full, card_count=0,
                              suspended_count=6))
    _l2 = [a.text() for a in _m2.actions()]
    check("fully suspended row offers only Unsuspend",
          "Unsuspend Cards" in _l2 and "Suspend Cards" not in _l2,
          repr(_l2))
    _, _m3 = _build_menu({})
    _l3 = [a.text() for a in _m3.actions()]
    check("unindexed row says 'Add to Search Index' and offers both "
          "suspend actions (counts unknown until K-118 data exists)",
          "Add to Search Index" in _l3
          and "Suspend Cards" in _l3 and "Unsuspend Cards" in _l3,
          repr(_l3))

    shutil.rmtree(_rq_uf, ignore_errors=True)

print("== K-124: the Map button ==")

_MAP_SRC = open("klausmate/pdf_drive.py", encoding="utf-8").read()
check("caption row carries a Map button beside New Folder/Refresh",
      'QPushButton("Map", left)' in _MAP_SRC)
check("it opens K-123's public surface, nothing deeper",
      "pdf_map.open_map_window(self)" in _MAP_SRC)
check("the import is guarded — a broken map costs a log line, never "
      "the Library",
      "map open failed" in _MAP_SRC)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
