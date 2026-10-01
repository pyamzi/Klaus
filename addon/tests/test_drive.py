"""Headless tests for drive_store + pdf_drop/pdf_drive importability.

Run: env QT_QPA_PLATFORM=offscreen python3 test_drive.py
"""
import ast
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import tokenize
import types

ADDON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "klausmate"
)

# The harness's package stub, so every USER_FILES lands in scratch, never
# the real Library.
sys.path.insert(0, os.path.join(os.path.dirname(ADDON), ".claude", "skills", "klaus-test", "scripts"))
from anki_stubs import install_package_stub  # noqa: E402

install_package_stub()
pkg = sys.modules["klausmate"]

import importlib

drive_store = importlib.import_module("klausmate.drive_store")
viewer_context = importlib.import_module("klausmate.viewer_context")

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

print("== K-127: retention_level — semantic buckets, not a hue ramp ==")
check("0.6999 is low (just under the boundary)",
      drive_store.retention_level(0.6999) == "low")
check("0.70 is mid (low < 0.70 <= mid)",
      drive_store.retention_level(0.70) == "mid")
check("0.8499 is still mid (just under the target boundary)",
      drive_store.retention_level(0.8499) == "mid")
check("0.85 is high (mid < 0.85 <= high — FSRS 'at target')",
      drive_store.retention_level(0.85) == "high")
check("the ends: 0.0 low, 1.0 high",
      drive_store.retention_level(0.0) == "low"
      and drive_store.retention_level(1.0) == "high")
check("out-of-range clamps into [0, 1] exactly like the old ramp did",
      drive_store.retention_level(-3) == "low"
      and drive_store.retention_level(1.7) == "high")
check("float()-compatible input coerces, like the old float() path",
      drive_store.retention_level("0.9") == "high")
_rl_raised = False
try:
    drive_store.retention_level(None)
except (TypeError, ValueError):
    _rl_raised = True
check("None raises into the caller's guard — pdf_drive None-guards "
      "before calling, and its try/except catches real garbage",
      _rl_raised)
check("the rainbow is dead: no retention_color left in drive_store",
      not hasattr(drive_store, "retention_color"))

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
    "QMenu", "QTimer", "QVBoxLayout", "QHBoxLayout", "QHeaderView",
    "QPushButton", "QSlider",
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

for mod in ("klausmate.pdf_drop", "klausmate.pdf_drive"):
    try:
        importlib.import_module(mod)
        check(f"{mod.split('.')[-1]} imports", True)
    except Exception as e:
        check(f"{mod.split('.')[-1]} imports", False, f"{type(e).__name__}: {e}")

# pdf_drop pure surface
try:
    dp = sys.modules["klausmate.pdf_drop"]
    check("the ONE surviving command is underscore-namespaced (a colon "
          "name is swallowed by the editor bridge's non-Editor guard)",
          dp.BROWSE_CMD == "klausmate_browse"
          and not dp.BROWSE_CMD.startswith("klausmate:"))
    # Every message check below passes a VALID deck context (DeckBrowser
    # is stubbed as _Any above, so an _Any() instance satisfies the
    # handler's own isinstance gate). That is load-bearing: with
    # context=None the CONTEXT gate turns everything away, and a handler
    # that had stopped filtering by message name at all would still look
    # correct — this pin passed that way until the K-151 falsification
    # pass caught it. QTimer is stubbed as the _Any CLASS, whose catch-all
    # __getattr__ is instance-level, so a real QTimer.singleShot lookup
    # raises: lend it a recorder for these calls and take it away again,
    # rather than leaving every other section's deferrals silently
    # succeeding where they used to raise.
    _fired = []
    _Any.singleShot = staticmethod(lambda ms, fn: _fired.append(fn))
    try:
        check("a Browse… click on a deck-screen context is claimed, and "
              "defers its file dialog instead of raising it inline",
              dp.on_deck_js_message((False, None), dp.BROWSE_CMD, _Any())
              == (True, None)
              and _fired == [dp._browse_for_pdfs], repr(_fired))
        check("js handler ignores a foreign message on that SAME "
              "context — the message gate is what turns it away, not "
              "the context gate",
              dp.on_deck_js_message((False, None), "something:else",
                                    _Any()) == (False, None))
        check("and the K-151-retired disarm command falls through it "
              "too; a handler that claimed-and-ignored the name would "
              "silently eat an identical message from anyone else",
              dp.on_deck_js_message((False, None), "klausmate_disarm",
                                    _Any()) == (False, None))
    finally:
        del _Any.singleShot
except Exception as e:
    check("pdf_drop surface", False, str(e))

print("== K-146: the curate-a-deck ceremony is gone, by absence ==")
# Pouya: "remove the fucking option to curate a fucking deck." The button
# never created a deck — it searched, tagged, and opened Browse on the
# per-PDF !Library tag that indexing already writes and the Library's
# "Show Matched Cards in Browse" already opens. These are ABSENCE pins
# (the reviewer-sheet idiom): the board card's verify grepped for the
# same strings, but a card's gate dies at sign-off and this does not.
# code_only (comments AND string literals stripped) is the house pin
# tool, hoisted here because the K-151 pins below are ABOUT prose: the
# module docstring names every symbol that card removed, to say why it
# is gone, so a raw-source absence grep could never pass.
_SKILL_SCRIPTS = os.path.join(
    os.path.dirname(ADDON), ".claude", "skills", "klaus-test", "scripts"
)
sys.path.insert(0, _SKILL_SCRIPTS)
from anki_stubs import code_only  # noqa: E402

_DP_SRC = open(os.path.join(ADDON, "pdf_drop.py"), encoding="utf-8").read()
_DP_CODE = code_only(_DP_SRC)
_CU_SRC = open(os.path.join(ADDON, "curation.py"), encoding="utf-8").read()
_PD_SRC = open(os.path.join(ADDON, "pdf_drive.py"), encoding="utf-8").read()
_PD_CODE = code_only(_PD_SRC)
for _sym in ("choose_deck_scope", "run_curation_flow", "_curate_with",
             "_on_curate_clicked", "_pick_pdf_menu", "CURATE_CMD",
             "on_overview_bottom", "_install_deck_browser_button"):
    check(f"pdf_drop no longer defines or names {_sym}",
          _sym not in _DP_SRC)
for _sym in ("def run_curation(", "def _preview_in_browse(",
             "def suggest_deck_name(", "def _escape_search("):
    check(f"curation no longer defines {_sym[4:-1]}", _sym not in _CU_SRC)
check("no bottom-bar button label survives on either deck screen",
      "Curate Deck" not in _DP_SRC and "Curate Deck" not in _PD_SRC)
check("nor the Library's context-menu entry",
      "Curate Deck from This PDF" not in _PD_SRC)

def _names_in(src, wanted):
    """Every ast.Name/global occurrence of `wanted` in real CODE.

    A substring grep cannot express this: both these pins are ABOUT
    prose that names the removed symbol (the module docstrings explain
    what K-146 took out and why), so a grep over the raw source can
    never fail, and a grep over a prose-stripped copy is one split()
    away from scanning almost nothing. The AST reads code only.
    """
    hits = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name) and node.id == wanted:
            hits.append(node.lineno)
        elif isinstance(node, ast.Global) and wanted in node.names:
            hits.append(node.lineno)
    return hits


check("last_run is gone with the search that wrote it — a module global "
      "nothing writes reads as an always-empty fallback (AST, so this "
      "file's own prose about it cannot satisfy or trip the pin)",
      _names_in(_CU_SRC, "last_run") == [],
      repr(_names_in(_CU_SRC, "last_run")))

# ...but the drop machinery it was tangled with SURVIVES: this wrapper is
# the only thing stopping Anki's own importer choking on a dropped PDF.
for _sym in ("_install_drop_wrap", "_import_pdfs", "_browse_for_pdfs",
             "BROWSE_CMD"):
    check(f"pdf_drop keeps {_sym} (the import surface, not the "
          f"ceremony)", _sym in _DP_SRC)

def _calls_in_func(src, func, callee):
    """Is `callee` actually CALLED by `func` itself?

    AST, not a grep: the string "_install_drop_wrap()" appears in its own
    def line, so a substring check passes even with the call deleted.
    Nested defs and lambdas are NOT descended into — a call parked inside
    a helper `func` never runs is not `func` calling it.
    """
    _NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

    def own_nodes(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _NESTED):
                continue
            yield child
            yield from own_nodes(child)

    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                       and c.func.id == callee for c in own_nodes(node))
    return False


check("the drop wrap is still INSTALLED by setup() — the one thing "
      "standing between a dropped PDF and Anki's own importer",
      _calls_in_func(_DP_SRC, "setup", "_install_drop_wrap"))
check("curation keeps the manual Browse deck copier (no PDF, no scope)",
      "def prompt_and_create(" in _CU_SRC
      and "def create_curated_deck(" in _CU_SRC
      and "def on_browser_menus_did_init(" in _CU_SRC)
check("an empty Browse selection now says so instead of silently "
      "copying a stale result set",
      "browser.selected_notes()" in _CU_SRC
      and "Select the notes to copy first." in _CU_SRC)

print("== K-151: the armed square is gone WHOLE, not vestigially ==")
# The armed half existed to STAGE a PDF for the curate button. K-146
# deleted the button, so K-151 deleted the staging: a square naming a
# file with no action attached is a confirmation Anki already gives
# (import_pdf_file tooltips "Klaus: loaded '<name>'" on every import
# surface). Removing a concept means every limb — state, bridge
# command, handler branch, HTML, the deck/overview re-render it needed,
# and pdf_drive's disarm_if call on delete.
check("deck_curate.py is gone — the module curated nothing and the "
      "file name went on saying it did",
      not os.path.exists(os.path.join(ADDON, "deck_curate.py")))


def _code_idents(src):
    """Every identifier that exists in real CODE: defs, assignments,
    globals, attributes, args and plain references.

    AST, not a grep, and for a sharper reason than usual here: pdf_drop's
    module docstring NAMES every symbol this card removed, to record what
    went and why. A raw-source absence grep would read that prose as the
    symbol still being present and fail on a correct file; code_only
    would strip the docstring but also every string literal, so it
    cannot see identifiers either way. This sees code and only code.
    """
    out = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Global):
            out.update(node.names)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
    return out


_DP_IDENTS = _code_idents(_DP_SRC)
for _sym in ("_armed_pdf", "arm", "armed", "disarm_if", "DISARM_CMD",
             "_CLAIMED", "_refresh_current_screen", "_import_and_arm",
             "_on_profile_will_close", "profile_will_close",
             "_display_name", "_user_files"):
    check(f"pdf_drop carries no {_sym} in real code", _sym not in _DP_IDENTS)

_DP_TREE = ast.parse(_DP_SRC)
_DP_GLOBALS = sorted(
    t.id
    for node in _DP_TREE.body
    if isinstance(node, (ast.Assign, ast.AnnAssign))
    for t in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
    if isinstance(t, ast.Name)
)
check("the module holds only its two constants, BROWSE_CMD and ADD_LABEL — the "
      "armed PDF was session state, and with it gone there is nothing "
      "left for setup() to reset on profile_will_close",
      _DP_GLOBALS == ["ADD_LABEL", "BROWSE_CMD"], repr(_DP_GLOBALS))
check("and no function rebinds a module global (the `global` statement "
      "went with the state it wrote)",
      not [n for n in ast.walk(_DP_TREE) if isinstance(n, ast.Global)])

print("== the drop square is gone; Add to Library joins Anki's bottom row ==")
# Pouya: "remove the PDF drop thing and just add 'Add to Library' for that
# instead". The row's buttons live in the status bar (status_bar parses
# Anki's own bottom-bar HTML), so the button goes where Anki's are.
for _sym in ("_drop_square_html", "on_deck_browser_content", "on_overview_content"):
    check(f"pdf_drop carries no {_sym}", _sym not in _DP_IDENTS)
_dp = sys.modules["klausmate.pdf_drop"]
_links = [["", "shared", "Get Shared"]]
_dp.add_library_link(_links)
_dp.add_library_link(_links)
check("the deck list's row gains Add to Library, once however often setup runs",
      _links == [["", "shared", "Get Shared"], ["", "klausmate_browse", "Add to Library"]], repr(_links))
_handler = object()
_ov = [["O", "opts", "Options"]]
check("the overview's row gains it too, and the filter hands back Anki's link handler",
      _dp.on_overview_will_render_bottom(_handler, _ov) is _handler
      and _ov[-1] == ["", "klausmate_browse", "Add to Library"], repr(_ov))
check("setup installs both", _calls_in_func(_DP_SRC, "setup", "add_library_link")
      and "overview_will_render_bottom.append(on_overview_will_render_bottom)" in _DP_SRC)
check("a click from the overview's row is claimed too (OverviewBottomBar context)",
      "OverviewBottomBar" in _DP_CODE)

check("pdf_drive's delete path no longer reaches into the armed state — "
      "it held the last disarm_if caller, and the module import went "
      "with it (code_only: the comment recording the removal must not "
      "satisfy the pin)",
      "disarm_if" not in _PD_CODE and "deck_curate" not in _PD_CODE)

print("== pdf_handler.list_by_recency (last_used missing for some pdfs) ==")
# This used to be driven THROUGH the deck square's _pick_pdf_menu with fake
# QMenu/QAction/QCursor objects, reading the ordering back off the fake
# menu's item texts. K-146 deleted that menu; the ordering rule it was
# really testing lives in pdf_handler and is still live (the editor PDF
# bar's ＋ menu reads it), so the coverage moved down to the function
# instead of leaving with the caller.
try:
    _ph_rec = importlib.import_module("klausmate.pdf_handler")
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

    _order = _ph_rec.list_by_recency(tmp_dc)
    check("recency order interleaves explicit last_used and mtime fallback",
          _order == ["gamma", "beta", "alpha"], repr(_order))
    check("names come back as safe basenames, .txt stripped",
          not any(n.endswith(".txt") for n in _order), repr(_order))
    check("limit truncates from the recent end, not the stale one",
          _ph_rec.list_by_recency(tmp_dc, 2) == ["gamma", "beta"],
          repr(_ph_rec.list_by_recency(tmp_dc, 2)))
    # An unreadable/absent contexts dir is the empty answer, not a raise:
    # every caller renders a menu straight off this.
    check("a user_files with no contexts dir yields []",
          _ph_rec.list_by_recency(os.path.join(tmp_dc, "nope")) == [])
    shutil.rmtree(tmp_dc, ignore_errors=True)
except Exception as e:
    check("list_by_recency ordering", False, f"{type(e).__name__}: {e}")

shutil.rmtree(tmp, ignore_errors=True)

pdf_drive = importlib.import_module("klausmate.pdf_drive")

print("== no Trash never means a permanent delete (Codex on PR #9) ==")
_qt = sys.modules["aqt.qt"]
_had_qfile, _old_qfile = hasattr(_qt, "QFile"), getattr(_qt, "QFile", None)
_qt.QFile = type("_NoTrash", (), {"moveToTrash": staticmethod(lambda p: False)})
_nt = tempfile.mkdtemp(prefix="klaus-notrash-")
_nt_pdf = os.path.join(_nt, "Only_copy.pdf")
open(_nt_pdf, "wb").write(b"%PDF-1.4")
check("a file that cannot go to the Trash is reported (False)...",
      pdf_drive._move_to_trash(_nt_pdf) is False)
check("...and left exactly where it was", os.path.isfile(_nt_pdf))
os.makedirs(os.path.join(_nt, "empty"))
check("an EMPTY directory may still go without a Trash (nothing to lose)",
      pdf_drive._move_to_trash(os.path.join(_nt, "empty")) is True
      and not os.path.exists(os.path.join(_nt, "empty")))
if _had_qfile:
    _qt.QFile = _old_qfile
else:
    del _qt.QFile
shutil.rmtree(_nt, ignore_errors=True)



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
    bool(_g_summary) and _g_summary.get("moved") == {} and _g_summary.get("ingested") == [],
    repr(_g_summary),
)


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
          _k_sum.get("moved") == {} and _k_sum.get("tree_changed") == [],
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


print("== K-308: the Library window is gone; its replacements keep the rules ==")
# The Library lives in Browse's sidebar now (library_sidebar,
# library_actions). The K-114/K-125 dialog rules and the K-132 colour
# rule move with it.
from anki_stubs import code_only as _code_only  # noqa: E402

_srcs = {n: open(os.path.join(ADDON, n)).read() for n in ("pdf_drive.py", "library_actions.py", "library_sidebar.py")}
for _name, _src in _srcs.items():
    _code = _code_only(_src)
    check(f"{_name}: no app-modal exec() and no exec-ing statics",
          ".exec(" not in _code.replace("menu.exec(", "") and "QInputDialog.get" not in _code
          and "QMessageBox.question" not in _code and "getOpenFileName" not in _code)
    _hits = [
        _tok.string for _tok in tokenize.generate_tokens(io.StringIO(_src).readline)
        if _tok.type != tokenize.COMMENT and re.search(r"#[0-9A-Fa-f]{6}\b", _tok.string)
    ]
    check(f"{_name}: zero literal hex colours (tokens only)", not _hits, str(_hits))
check("no toolbar Library link, no Library window, no Library screen",
      "top_toolbar_did_init_links" not in _code_only(_srcs["pdf_drive.py"])
      and "class DriveWindow" not in _srcs["pdf_drive.py"]
      and not os.path.exists(os.path.join(ADDON, "library_tab.py")))
check("every dialog in library_actions is an instance opened with open()",
      _code_only(_srcs["library_actions.py"]).count(".open()") == 3)  # text prompt, sensitivity, file picker
check("Preferences' refresh hook still exists (manage_models calls it)",
      hasattr(pdf_drive, "refresh_open_library"))


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
