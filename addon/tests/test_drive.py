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

pkg = types.ModuleType("klausmate")
pkg.__path__ = [ADDON]
pkg.__package__ = "klausmate"
sys.modules["klausmate"] = pkg

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
             "BROWSE_CMD", "_drop_square_html"):
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
check("the module holds exactly ONE module-level name, BROWSE_CMD — the "
      "armed PDF was session state, and with it gone there is nothing "
      "left for setup() to reset on profile_will_close",
      _DP_GLOBALS == ["BROWSE_CMD"], repr(_DP_GLOBALS))
check("and no function rebinds a module global (the `global` statement "
      "went with the state it wrote)",
      not [n for n in ast.walk(_DP_TREE) if isinstance(n, ast.Global)])

try:
    _SQUARE = sys.modules["klausmate.pdf_drop"]._drop_square_html()
    check("the square renders ONE state — the invitation and its "
          "Browse… anchor; no armed variant, no × dismiss link, and no "
          "copy naming an imported file",
          "Drop a lecture PDF" in _SQUARE
          and "Browse&hellip;" in _SQUARE
          and "&times;" not in _SQUARE
          and "Imported:" not in _SQUARE
          and "Armed:" not in _SQUARE, repr(_SQUARE[-260:]))
    check("with exactly one pycmd in it, the Browse command",
          _SQUARE.count("pycmd(") == 1
          and 'pycmd("klausmate_browse")' in _SQUARE)
except Exception as e:
    check("K-151 drop-square render", False, f"{type(e).__name__}: {e}")

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

print("== K-152: the Library DRIVES the shared runner, it is not the runner ==")
# K-146 pinned the phase ORDER here, because _on_embed *was* the chain:
# curation.ensure_index (one embedding per note) had to run first or
# every note written since the last card-index pass stayed invisible to
# ensure_matches and the per-PDF !Library tag quietly under-covered.
#
# K-152 lifted that chain into klausmate/index_queue.py so a PDF added
# from the deck screen — which has no Library window, and so could reach
# none of this window's busy flag, status label, progress callback or
# Cancel button — runs exactly the same four phases. The order pin moved
# with it, to tests/test_index_queue.py ("the chain"), where it is now
# checked against the ONE copy that exists. What belongs here is the
# other half of that split: that this window delegates rather than
# keeping a second copy, and that it renders the runner's own state.


class _EmbedStatus:
    def __init__(self):
        self.texts = []

    def setText(self, t):
        self.texts.append(t)


class _CancelBtn:
    def __init__(self):
        self.visible = None

    def setVisible(self, v):
        self.visible = v


class _EmbedHost:
    def __init__(self, alive=True):
        self.seq, self.status, self.refreshes = 7, _EmbedStatus(), 0
        self.cancel_btn = _CancelBtn()
        self._is_alive = alive

    def _alive(self):
        return self._is_alive

    def _refresh_rows(self):
        self.refreshes += 1


try:
    _iq = importlib.import_module("klausmate.index_queue")
    _seen = []
    _o = (_iq.request_pdf, _iq.cancel_all)
    _iq.request_pdf = lambda safe, **kw: _seen.append(("request", safe, kw))
    _iq.cancel_all = lambda: _seen.append(("cancel",))
    try:
        _host = _EmbedHost()
        pdf_drive.DriveWindow._on_embed(_host, "Renal_Phys")
        pdf_drive.DriveWindow._on_cancel(_host)
    finally:
        _iq.request_pdf, _iq.cancel_all = _o
    check("the button asks the shared runner to index THIS PDF, rather "
          "than starting a private copy of the chain",
          _seen[0][0] == "request" and _seen[0][1] == "Renal_Phys",
          repr(_seen))
    check("...silently: the runner's tooltip is for surfaces with "
          "nowhere to show state, and this window has a status line",
          _seen[0][2].get("announce") is False, repr(_seen[0]))
    check("Cancel stops the whole queue, not one window's private run — "
          "the job it stops may have been started from the deck screen",
          _seen[1] == ("cancel",), repr(_seen))

    # -- rendering the runner's snapshot -----------------------------
    _host = _EmbedHost()
    _busy = _iq.RunnerState(active=True, name="Renal_Phys",
                            label="Embedding PDF…", done=1, total=4,
                            pending=3)
    pdf_drive.DriveWindow._on_index_state(_host, _busy)
    check("the status line is the runner's OWN status_line, so this "
          "window and the bottom bar cannot describe one job differently",
          _host.status.texts[-1] == _iq.status_line(_busy),
          repr(_host.status.texts))
    check("...and it really says something (a pin against two empty "
          "strings agreeing)",
          "Renal_Phys" in _host.status.texts[-1] and "25%" in _host.status.texts[-1],
          repr(_host.status.texts))
    check("Cancel is offered exactly while a job is running",
          _host.cancel_btn.visible is True)
    check("a running job does not re-aggregate the tree on every "
          "progress tick", _host.refreshes == 0)

    pdf_drive.DriveWindow._on_index_state(
        _host, _iq.RunnerState(message="Indexed “Renal_Phys”.",
                               finished="Renal_Phys"))
    check("a FINISHED PDF re-aggregates the tree — its retention, card "
          "counts and freshness flag are all stale now",
          _host.refreshes == 1)
    check("...and Cancel goes away with the job", _host.cancel_btn.visible is False)

    pdf_drive.DriveWindow._on_index_state(
        _host, _iq.RunnerState(message="Indexing cancelled."))
    check("an idle snapshot with nothing finished refreshes nothing",
          _host.refreshes == 1)

    _dead = _EmbedHost(alive=False)
    pdf_drive.DriveWindow._on_index_state(_dead, _busy)
    check("a closed window's listener touches no deleted C++ widget",
          _dead.status.texts == [] and _dead.refreshes == 0)

    # One line, two writers. _refresh_rows' completion lands
    # asynchronously — on window open and after every finished job — and
    # must not blank the progress of the job running right now.
    _rr = _PD_CODE.split("def _refresh_rows", 1)[1].split("\n    def ", 1)[0]
    check("the retention refresh yields the status line to a running "
          "job instead of blanking it",
          "if not index_queue.state().active:" in _rr
          and _rr.index("if not index_queue.state().active:")
          < _rr.index(".join(notes)"))
except Exception as e:
    check("Library delegates to the runner", False, f"{type(e).__name__}: {e}")

print("== refresh_open_library glue (K-052 rework) ==")
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
# ALIVE means walked, for both shapes; HIDDEN means marked pending, not
# refreshed — one refresh on the next show coalesces every event that
# happened while nobody was looking. A properly closed standalone window
# leaves _instance through shutdown() and is never walked at all.
check("a hidden but still-registered Library is marked pending, not "
      "refreshed — the same policy as the embedded screen",
      w2.refreshes == 0 and getattr(w2, "_refresh_pending", False) is True,
      f"{w2.refreshes} refreshes, pending={getattr(w2, '_refresh_pending', None)!r}")

w3 = _FakeWin(alive=False, visible=True)
pdf_drive._instance = w3
pdf_drive.refresh_open_library()
check("dead C++ handle is not refreshed", w3.refreshes == 0)
pdf_drive._instance = None

# THE EMBEDDED LIBRARY IS THE ONE THE USER IS LOOKING AT. `_instance` is
# set by _create(), the standalone-window path only; the SCREEN is a
# DriveWindow(embedded=True) that library_tab constructs directly, so it
# never lands there. Since open_library() prefers the tab, walking only
# `_instance` meant the sensitivity save reached the shape almost nobody
# has open — K-052's exact complaint, regressed for the screen. The
# WeakSet K-173 added for viewer release is the roster of embedded
# screens; this hook has to walk it too.
@contextlib.contextmanager
def _scratch_rosters():
    """Both Library rosters emptied for the block, restored in finally —
    the file's try/finally idiom (cf. USER_FILES at K-136), so a raise
    inside cannot leave every later section with an emptied roster."""
    _prev_inst = pdf_drive._instance
    _prev_set = list(pdf_drive._embedded_windows)
    pdf_drive._instance = None
    pdf_drive._embedded_windows.clear()
    try:
        yield
    finally:
        pdf_drive._instance = _prev_inst
        pdf_drive._embedded_windows.clear()
        for _w in _prev_set:
            pdf_drive._embedded_windows.add(_w)


with _scratch_rosters():

    e1 = _FakeWin(alive=True, visible=True)
    pdf_drive._embedded_windows.add(e1)
    pdf_drive.refresh_open_library()
    check("the EMBEDDED Library screen gets refreshed too — the whole card",
          e1.refreshes == 1, f"{e1.refreshes} refreshes")

    e1.refreshes = 0
    e2 = _FakeWin(alive=True, visible=False)
    e3 = _FakeWin(alive=False, visible=True)
    pdf_drive._embedded_windows.add(e2)
    pdf_drive._embedded_windows.add(e3)
    pdf_drive.refresh_open_library()
    check("a HIDDEN embedded screen is NOT refreshed now but is MARKED pending "
          "— hidden is the tab's resting state, one refresh on its next show "
          "coalesces every save made while it was unseen (measured: ~130ms of "
          "collection-held worker per refresh, five slider releases were five)",
          e2.refreshes == 0 and getattr(e2, "_refresh_pending", False) is True,
          f"{e2.refreshes} refreshes, pending={getattr(e2, '_refresh_pending', None)!r}")
    check("a DEAD embedded screen is not refreshed — the WeakSet outlives "
          "the C++ object, so _alive() is load-bearing here, not hygiene",
          e3.refreshes == 0, f"{e3.refreshes} refreshes")
    check("...and the live one beside them still got its one refresh",
          e1.refreshes == 1, f"{e1.refreshes} refreshes")


    class _AngryWin(_FakeWin):
        def _refresh_rows(self):
            self.refreshes += 1
            raise RuntimeError("boom")


    # The RAISING window must be the one walked FIRST, or this pin is decided
    # by WeakSet iteration order: with bad and good both in the set, a broken
    # single-outer-try implementation passed 63% of 2000 replays — every run
    # where good happened to be iterated before bad. _instance is always the
    # first element of the walk, so it is the deterministic seat for bad.
    pdf_drive._embedded_windows.clear()
    bad = _AngryWin(alive=True, visible=True)
    good = _FakeWin(alive=True, visible=True)
    pdf_drive._instance = bad
    pdf_drive._embedded_windows.add(good)
    _raised = None
    try:
        pdf_drive.refresh_open_library()
    except Exception as _e:  # noqa: BLE001
        _raised = _e
    check("one screen that throws does not eat the refresh of the others — "
          "the guard is PER WINDOW, because this runs inside Preferences' "
          "config-save path where an escaping exception is far worse than a "
          "stale column (the raiser is walked first, so order cannot save a "
          "whole-loop try)",
          _raised is None and bad.refreshes == 1 and good.refreshes == 1,
          f"raised={_raised!r}, bad={bad.refreshes}, good={good.refreshes}")

    # No "reachable both ways" pin: the two rosters are DISJOINT by construction
    # (_instance is written only by _create(), which builds embedded=False;
    # _embedded_windows is joined only by an embedded __init__), so a window in
    # both is a state production cannot produce, and a dedupe would guard
    # nothing. Note for whoever cites a cost here: _refresh_rows never embeds
    # (retention.priority_rows reads cached artifacts only); a double refresh
    # costs a vector load, SQL and a main-thread rescan, not API money.

    # ONE walker for "every live Library", used by both consumers. The two
    # rosters are disjoint by construction, so it dedupes nothing; it skips
    # None and dead C++ handles and yields the rest, visible or not.
    pdf_drive._embedded_windows.clear()
    _lw_win = _FakeWin(alive=True, visible=True)
    _lw_hid = _FakeWin(alive=True, visible=False)
    _lw_dead = _FakeWin(alive=False, visible=True)
    pdf_drive._instance = _lw_win
    pdf_drive._embedded_windows.add(_lw_hid)
    pdf_drive._embedded_windows.add(_lw_dead)
    _lw_out = list(pdf_drive._live_libraries())
    check("_live_libraries yields the window and the hidden screen, and skips the "
          "dead handle — one roster walk both consumers share",
          len(_lw_out) == 2 and _lw_win in _lw_out and _lw_hid in _lw_out
          and _lw_dead not in _lw_out, f"{len(_lw_out)} yielded")
    pdf_drive._instance = None
    _lw_out2 = list(pdf_drive._live_libraries())
    check("...and with no standalone window it still yields the screens",
          _lw_out2 == [_lw_hid], repr(_lw_out2))

    # THE WATCHER TICK HAD THE SAME BLIND SPOT and no test at all. With only
    # the embedded screen open (_instance is None — only _create() writes
    # it), a disk change under the library root used to fall to the bare
    # rescan and never repaint the tree the user was looking at.
    _rescans = []
    _prev_rescan = pdf_drive.rescan_library_root
    pdf_drive.rescan_library_root = lambda *a, **k: _rescans.append(1)
    try:
        pdf_drive._embedded_windows.clear()
        _fs_scr = _FakeWin(alive=True, visible=True)
        pdf_drive._embedded_windows.add(_fs_scr)
        pdf_drive._instance = None
        pdf_drive._on_fs_tick()
        check("_on_fs_tick refreshes the EMBEDDED Library on a disk change — it "
              "walked _instance alone, so the visible tree never repainted "
              "(K-076 regressed for the tab)",
              _fs_scr.refreshes == 1, f"{_fs_scr.refreshes} refreshes")
        check("...and does not ALSO run the bare rescan when a Library took the "
              "refresh (_refresh_rows rescans itself)",
              not _rescans, f"{len(_rescans)} bare rescans")
        pdf_drive._embedded_windows.clear()
        del _rescans[:]
        pdf_drive._on_fs_tick()
        check("...and with no Library open at all it still runs the bare rescan, "
              "so folder->tag sync stays live while nothing is showing",
              len(_rescans) == 1, f"{len(_rescans)} bare rescans")
        _fs_hid = _FakeWin(alive=True, visible=False)
        pdf_drive._embedded_windows.add(_fs_hid)
        del _rescans[:]
        pdf_drive._on_fs_tick()
        check("...and a HIDDEN screen is marked pending while the bare rescan still "
              "keeps mapping/tags live — the watcher never refreshes an unseen tab",
              _fs_hid.refreshes == 0 and getattr(_fs_hid, "_refresh_pending", False)
              and len(_rescans) == 1,
              f"{_fs_hid.refreshes} refreshes, {len(_rescans)} rescans")
    finally:
        pdf_drive.rescan_library_root = _prev_rescan




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
# comment mentioning an old label must not satisfy a rename pin. It and
# _PD_SRC/_PD_CODE are hoisted to the K-146/K-151 block above, whose
# absence pins need the same tool.
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

print("== K-125: the statics that exec() internally are gone too ==")
# K-100's audit: QInputDialog.getText and QMessageBox.question run an
# app-modal exec() under the hood — the same macOS 26 + Qt 6.11 crash
# class K-114 retired. All four pdf_drive sites converted to the
# instance + open() + signal patterns; bans on code_only text so a
# comment spelling a static can never trip them.
check("no QInputDialog static and no QMessageBox.question left in code",
      "QInputDialog.get" not in _PD_CODE
      and "QMessageBox.question" not in _PD_CODE)
check("the three text prompts (new folder, rename PDF, rename folder) "
      "are INSTANCES via open() + textValueSelected",
      _PD_CODE.count("textValueSelected.connect(") == 3
      and _PD_FLAT.count("QInputDialog(self)") == 3)
check("_new_folder is CPS — on_done(path) only on a real create, and "
      "_move_to_new_folder rides it",
      "on_done(path)" in _PD_FLAT
      and "self._new_folder(on_done=lambdapath:self._move_pdf(safe,path))"
      in _PD_FLAT)
check("delete confirm: window-modal Yes/No (No default) read via "
      "clickedButton() on finished; the destructive back half runs "
      "only from the Yes",
      "msg.open()" in _PD_FLAT
      and "msg.finished.connect(_on_answered)" in _PD_FLAT
      and "setDefaultButton(QMessageBox.StandardButton.No)" in _PD_FLAT
      and "self._delete_pdf_confirmed(safe,display)" in _PD_FLAT)
# Raw source here on purpose: code_only strips string literals, and an
# objectName IS a string literal (test_setup_crop_theme's precedent).
check("delete confirm wears the theme's destructive role (DangerButton "
      "on Yes, SecondaryButton on No)",
      'setObjectName("DangerButton")' in _PD_SRC
      and 'setObjectName("SecondaryButton")' in _PD_SRC)

print("== K-127: Library data presentation — source pins ==")
check("PDF column stretches — Stretch mode set, the fixed 240px "
      "gutter-maker gone",
      "setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)" in _PD_FLAT
      and "setColumnWidth(0,240)" not in _PD_FLAT)
check("numeric columns Fixed at 84 / 88 / 88 (widened for the K-130 16px sort-indicator reserve — 76/72 elided the captions, offscreen render), last-section stretch "
      "still off",
      "QHeaderView.ResizeMode.Fixed" in _PD_CODE
      and "setColumnWidth(1,84)" in _PD_FLAT
      and "setColumnWidth(2,88)" in _PD_FLAT
      and "setColumnWidth(3,88)" in _PD_FLAT
      and "setStretchLastSection(False)" in _PD_FLAT)
# Raw source on purpose: this pin is ON a comment (code_only strips
# comments), guarding the load-bearing 88px history note.
check("the 88px suspended-cell comment survives beside its width",
      "the Cards cell doubles as" in _PD_SRC
      and "elided those to" in _PD_SRC)
_APPLY_SRC = _PD_SRC.split("def _apply_row", 1)[1].split(
    "def _set_suspended_dim", 1)[0]
_tn = _APPLY_SRC.find("setFeature")
check("tnum lands in _apply_row through a guard — a try: before "
      "QFont.setFeature and an except after it, so Qt < 6.7 degrades "
      "to proportional digits instead of a broken row",
      'b"tnum"' in _APPLY_SRC
      and _tn > -1
      and "try:" in _APPLY_SRC[:_tn]
      and "except Exception" in _APPLY_SRC[_tn:])
# Raw source again: palette KEY names are string literals.
check("retention ink maps low -> red_text and high -> green off the "
      "live palette (the offscreen section proves the behaviour)",
      '"red_text" if level == "low" else "green_text"' in _PD_SRC
      and "drive_store.retention_level(fraction)" in _PD_SRC
      and "drive_store.retention_color" not in _PD_SRC)

print("== K-132: Library empty state — source pins ==")
_TITLE_M = re.search(r'LIBRARY_EMPTY_TEXT = "(.*)"', _PD_SRC)
_HINT_M = re.search(r'LIBRARY_EMPTY_HINT = "(.*)"', _PD_SRC)
check("the copy lives in module constants, not inline strings",
      "LIBRARY_EMPTY_TEXT" in _PD_CODE and "LIBRARY_EMPTY_HINT" in _PD_CODE
      and _TITLE_M is not None and _HINT_M is not None)
_TITLE = _TITLE_M.group(1) if _TITLE_M else ""
_HINT = _HINT_M.group(1) if _HINT_M else ""
check("the headline says NO PDFS — the wording that stays true when "
      "the tree holds folders and no PDFs (judgement (a): one copy "
      "for both empty shapes)",
      "PDF" in _TITLE and "empty" not in _TITLE.lower(), repr(_TITLE))
check("the hint names BOTH routes that exist — the tree drop and the "
      "drop square's Browse… (never the context menu, which has no "
      "import action to point at)",
      "Drag" in _HINT and "Browse…" in _HINT
      and "context menu" not in _HINT, repr(_HINT))
# THE show/hide condition. `not contexts` — the PDF list — and never a
# row count: a Library holding folders but no PDFs is still empty of the
# thing the pane is for (K-132 judgement (a)), and the offscreen section
# proves the block survives folder rows.
check("the condition is the PDF count, evaluated in rebuild_tree",
      "self.tree.set_empty_state(notcontexts)" in _PD_FLAT)
check("no second empty-state message left to contradict it — the old "
      "status line is gone (and it was overwritten by every "
      "_refresh_rows anyway)",
      "No PDFs yet" not in _PD_SRC)
check("the block reuses the shared drop-square language rather than "
      "inventing one, minus the idle dashed box",
      "idle_border=False" in _PD_FLAT
      and "theme.drop_zone_qss" in _PD_SRC.replace("_theme.", "theme."))
check("drop-through is structural: the block is transparent to the "
      "hit test Qt's drop-target search runs, so _LibraryTree keeps "
      "every drag itself",
      "WA_TransparentForMouseEvents" in _PD_CODE)

print("== K-132: pdf_drive carries no literal hex (tokens only) ==")
# theme.py is the single source of colour (CLAUDE.md: "UI files must
# not hardcode colours"), so a colour literal in a UI module is a bug
# by construction — it cannot follow a colour theme or a night flip.
#
# TOKENISED, not line-split. The line-split shape (test_setup_crop_theme's
# _hex_hits_outside_comments) drops everything after the first "#" on a
# line to skip comments — but a hex literal in Python ALWAYS lives
# inside a string, and the "#" that opens it is that same first "#", so
# the value being hunted is exactly what gets discarded. That helper can
# never report a hit. Dropping COMMENT tokens instead exempts comments
# (where these values are documented) while still seeing every string.
_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
_hex_hits = []
for _tok in tokenize.generate_tokens(io.StringIO(_PD_SRC).readline):
    if _tok.type != tokenize.COMMENT and _HEX_RE.search(_tok.string):
        _hex_hits.append((_tok.start[0], _tok.string.strip()[:60]))
check("zero literal hex colours in pdf_drive.py code (comments exempt)",
      not _hex_hits, str(_hex_hits))

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

    print("== K-132: the empty state on a REAL tree ==")
    # Behaviour, not source: the block is a child of the tree's
    # viewport, so everything here — visibility, where it parks, and
    # above all that a drop over it still reaches _dest_folder_at —
    # runs against genuine Qt geometry and hit-testing.
    _ew = _K117Win()
    _etree = pdf_drive._LibraryTree(_ew)
    _etree.setColumnCount(4)
    _etree.resize(420, 480)
    _etree.show()
    app.processEvents()
    _blk = _etree._empty
    check("a fresh tree ships the block built but hidden",
          _blk is not None and not _blk.isVisibleTo(_etree.viewport()))
    check("the block renders the two constants verbatim",
          _blk.title.text() == pdf_drive.LIBRARY_EMPTY_TEXT
          and _blk.hint.text() == pdf_drive.LIBRARY_EMPTY_HINT,
          repr((_blk.title.text(), _blk.hint.text())))
    _etree.set_empty_state(True)
    app.processEvents()
    check("set_empty_state(True) shows it",
          _blk.isVisibleTo(_etree.viewport()))
    _etree.set_empty_state(False)
    check("set_empty_state(False) hides it — the moment a PDF row "
          "exists the pane is a plain tree again",
          not _blk.isVisibleTo(_etree.viewport()))

    # Judgement (a): folders are not PDFs. The block stays up over a
    # folder-only tree, and the LAYOUT (not a second string) keeps it
    # clear of the rows.
    _etree.set_empty_state(True)
    _ef = pdf_drive._LibraryItem(_etree, ["Anatomy"])
    _ef.setData(0, pdf_drive._ROLE_FOLDER, "Anatomy")
    _etree.set_empty_state(True)
    app.processEvents()
    _rows_bottom = _etree.visualItemRect(_ef).bottom()
    check("with folders but no PDFs the block stays up and parks in "
          "the free area BELOW the last row (never over it)",
          _blk.isVisibleTo(_etree.viewport())
          and _blk.geometry().top() > _rows_bottom,
          f"block top {_blk.geometry().top()} vs rows bottom "
          f"{_rows_bottom}")

    # THE drop-through pin (judgement (b)). Two independent proofs:
    # the Qt hit test that QWidgetWindow::findDnDTarget runs skips the
    # block outright, and a drop delivered at a point the block covers
    # still resolves through _dest_folder_at exactly as on a bare tree.
    check("the block is transparent to mouse/drag hit-testing",
          _blk.testAttribute(
              _QtC.Qt.WidgetAttribute.WA_TransparentForMouseEvents))
    _inside = _blk.geometry().center()
    check("Qt's own childAt() — the lookup the DnD target search uses "
          "— cannot see the block, so the viewport keeps the drag",
          _etree.viewport().childAt(_inside) is None,
          repr(_etree.viewport().childAt(_inside)))
    _ew.dropped.clear()
    _drop_over = _QtG.QDropEvent(_QtC.QPointF(_inside), _COPY, _md_pdf,
                                 _BTN, _MOD)
    _etree.dropEvent(_drop_over)
    check("a .pdf dropped ON the empty state files at the root — the "
          "same (paths, folder) a drop on blank tree space produces",
          _ew.dropped == [(["/tmp/Lecture 3.pdf"], None)],
          repr(_ew.dropped))
    _ew.dropped.clear()
    _on_folder = _QtC.QPointF(_etree.visualItemRect(_ef).center())
    _etree.dropEvent(_QtG.QDropEvent(_on_folder, _COPY, _md_pdf, _BTN, _MOD))
    check("folder targeting survives the empty state — a drop on the "
          "folder row still files into that folder",
          _ew.dropped == [(["/tmp/Lecture 3.pdf"], "Anatomy")],
          repr(_ew.dropped))

    # The affordance: the TREE lights the block, off the same test that
    # accepts the drag, so it can never advertise a refused drop.
    _blk.set_drag_active(False)
    _e_enter = _QtG.QDragEnterEvent(_QtC.QPoint(30, 30), _COPY, _md_pdf,
                                    _BTN, _MOD)
    _etree.dragEnterEvent(_e_enter)
    check("a .pdf drag over the tree arms the block's drag-over look",
          _blk.property("dragOver") == "true" and _e_enter.isAccepted())
    _etree.dragLeaveEvent(_QtG.QDragLeaveEvent())
    check("dragging back out disarms it", _blk.property("dragOver") == "false")
    _etree.dragEnterEvent(
        _QtG.QDragEnterEvent(_QtC.QPoint(30, 30), _COPY, _md_pdf, _BTN, _MOD))
    _etree.dropEvent(
        _QtG.QDropEvent(_QtC.QPointF(_inside), _COPY, _md_pdf, _BTN, _MOD))
    check("the drop itself disarms it too (no lit block left behind)",
          _blk.property("dragOver") == "false")
    _e_txt = _QtG.QDragEnterEvent(_QtC.QPoint(30, 30), _COPY, _md_txt,
                                  _BTN, _MOD)
    _etree.dragEnterEvent(_e_txt)
    check("a non-.pdf drag neither is accepted nor lights the block",
          not _e_txt.isAccepted() and _blk.property("dragOver") == "false")

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

    print("== K-127: retention ink — semantic levels on real items ==")
    # Compared against the LIVE palette, not hex literals: the code and
    # this test read the same theme.palette(False) (night_mode() falls
    # back to light offscreen, same as the #AAAAAA dim check above), so
    # a token-value change can never split them.
    from klausmate import theme as _th_k127
    _pal_k127 = _th_k127.palette(False)
    _lvl_item = pdf_drive._LibraryItem(_sort_tree, ["Y.pdf"])
    _apply(_host, _lvl_item, dict(_full, retention=0.42))
    check("low (< 0.70) wears the palette's red_text",
          _lvl_item.foreground(1).color().name().lower()
          == _QtG.QColor(_pal_k127["red_text"]).name().lower(),
          _lvl_item.foreground(1).color().name())
    _apply(_host, _lvl_item, dict(_full, retention=0.92))
    check("high (>= 0.85) wears the palette's green",
          _lvl_item.foreground(1).color().name().lower()
          == _QtG.QColor(_pal_k127["green_text"]).name().lower(),
          _lvl_item.foreground(1).color().name())
    _apply(_host, _lvl_item, dict(_full, retention=0.75))
    check("mid RESETS the foreground — a refresh out of low sheds the "
          "stale red instead of skipping the cell",
          _lvl_item.data(1, _QtC.Qt.ItemDataRole.ForegroundRole) is None)
    check("regular weight — the retention cell never bolds",
          not _lvl_item.font(1).bold())
    if hasattr(_lvl_item.font(1), "isFeatureSet"):
        _tnum_tag = _QtG.QFont.Tag(b"tnum")
        check("tnum actually lands on all three numeric cells' fonts "
              "(this Qt has setFeature)",
              all(_lvl_item.font(cc).isFeatureSet(_tnum_tag)
                  and _lvl_item.font(cc).featureValue(_tnum_tag) == 1
                  for cc in (1, 2, 3)))
    else:
        print("  SKIP: QFont.setFeature not in this Qt — the guarded "
              "source pin above still holds")

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
        tag_query=_real_ts.tag_query,
    )
    _orig_ts, _orig_mw = pdf_drive.tag_sync, pdf_drive.mw
    _sh = _SuspendHost()
    try:
        _col = _FakeCol([11, 22])
        _run_now_col[:] = [_col]
        pdf_drive.tag_sync = _fake_ts
        pdf_drive.mw = types.SimpleNamespace(col=_col)
        pdf_drive.DriveWindow._set_suspended_cards(_sh, "Renal_Phys", True)
        # PR #4 fourth review (1): the suspend hop is the third `tag:`
        # site in this file and builds its operand from the same
        # tag_query — so the underscores desired_tag mints out of spaces
        # ("Week 3" -> "Week_3") are escaped too, instead of standing as
        # Anki's any-single-character wildcard and suspending a
        # neighbouring PDF's cards.
        _want_q = 'tag:"!Library::Anatomy::Week\\_3::Renal\\_\\"Phys\\""'
        check("no stored tag -> the DERIVED desired_tag is queried, "
              "quotes and wildcards escaped", _col.queries == [_want_q],
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
              _col2.queries == ['tag:"!Library::Stored\\_Tag"'],
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

    print("== PR #4 F5: Match Sensitivity OK recomputes the COUNTS too ==")
    _th_uf = tempfile.mkdtemp(prefix="klaus_thresh_uf_")
    _th_prev_uf = pkg.USER_FILES
    pkg.USER_FILES = _th_uf
    class _ThreshHost(_QtW.QWidget):
        _on_threshold = pdf_drive.DriveWindow._on_threshold
        _apply_row = pdf_drive.DriveWindow._apply_row
        _set_retention_color = pdf_drive.DriveWindow._set_retention_color
        _set_suspended_dim = pdf_drive.DriveWindow._set_suspended_dim

        def _iter_pdf_items(self):
            return iter(self.items)

    _th_host = _ThreshHost()
    _th_tree = pdf_drive._LibraryTree(_fw)
    _th_tree.setColumnCount(4)
    _th_item = pdf_drive._LibraryItem(_th_tree, ["Thr.pdf"])
    _th_item.setData(0, pdf_drive._ROLE_SAFE, "Thr")
    _th_host.items = [_th_item]
    # 101 and 102 have two cards each; 103 has one below the new threshold.
    _th_host.matches = {"Thr": [(101, 0.90), (102, 0.72), (103, 0.62)]}
    _th_host.card_r = {101: [(0.9, False), (0.8, False)],
                       102: [(0.7, False), (0.7, False)],
                       103: [(0.5, True)]}
    _th_host.card_queues = {101: [0, 0], 102: [0, 0], 103: [0]}
    _th_host.rows = {"Thr": {"indexed": True, "stale": False, "retention": 0.9,
                             "matched_cards": 3, "new_pct": 0.0, "priority": 0.0,
                             "note_count": 3, "card_count": 5,
                             "suspended_count": 0}}

    _th_stored = {}
    _th_synced = []
    _th_orig = (pdf_drive.retention._cfg, pdf_drive.retention.get_threshold,
                pdf_drive.retention.set_threshold,
                pdf_drive.tag_sync.sync_after_threshold, pdf_drive.mw)
    pdf_drive.retention._cfg = lambda: {}
    pdf_drive.retention.get_threshold = lambda name, cfg: _th_stored.get(name, 0.60)
    pdf_drive.retention.set_threshold = lambda name, v: _th_stored.__setitem__(name, v)
    pdf_drive.tag_sync.sync_after_threshold = lambda *a, **k: _th_synced.append(a)
    pdf_drive.mw = types.SimpleNamespace(col=None)
    try:
        _th_host._on_threshold("Thr")
        _th_dlg = _th_host.findChildren(_QtW.QDialog)[-1]
        _th_slider = _th_dlg.findChildren(_QtW.QSlider)[0]
        check("the dialog opens on the PDF's current threshold (0.60), "
              "with 101/102/103 all above it",
              _th_slider.value() == 60, _th_slider.value())
        _th_slider.setValue(70)  # past 103's 0.62 — it leaves the match set
        _th_dlg.accept()
        app.processEvents()
        _th_row = _th_host.rows["Thr"]
        check("PR #4 F5: OK recomputes the COUNTS against the new "
              "threshold, not just the score — 103 drops out, so one "
              "matching note and its card go with it",
              (_th_row["note_count"], _th_row["card_count"],
               _th_row["suspended_count"]) == (2, 4, 0),
              repr({k: _th_row[k] for k in
                    ("note_count", "card_count", "suspended_count")}))
        check("...the retention score agrees with them — it was already "
              "recomputed with both matching notes",
              _th_row["matched_cards"] == 4
              and abs(_th_row["retention"] - (0.90 * 1.7 + 0.72 * 1.4) / (2 * (0.90 + 0.72))) < 1e-9,
              repr((_th_row["matched_cards"], _th_row["retention"])))
        check("...and the row reaches the tree: the Cards cell now reads "
              "the new pair, not the pre-OK one",
              _th_item.text(2) == "4", repr(_th_item.text(2)))

        _th_slider2_dlg_before = len(_th_host.findChildren(_QtW.QDialog))
        _th_host._on_threshold("Thr")
        _th_dlg2 = _th_host.findChildren(_QtW.QDialog)[-1]
        check("a second dialog really opened on the SAVED threshold",
              len(_th_host.findChildren(_QtW.QDialog)) == _th_slider2_dlg_before + 1
              and _th_dlg2.findChildren(_QtW.QSlider)[0].value() == 70)
        # 80 is the slider's own maximum, and 102 scores 0.72 — past it.
        _th_dlg2.findChildren(_QtW.QSlider)[0].setValue(80)
        _th_dlg2.accept()
        app.processEvents()
        _th_row2 = _th_host.rows["Thr"]
        check("raising the threshold removes 102 from both counts and score",
              (_th_row2["note_count"], _th_row2["card_count"]) == (1, 2)
              and _th_row2["matched_cards"] == 2
              and abs(_th_row2["retention"] - 0.85) < 1e-9
              and _th_item.text(2) == "2")
    finally:
        (pdf_drive.retention._cfg, pdf_drive.retention.get_threshold,
         pdf_drive.retention.set_threshold,
         pdf_drive.tag_sync.sync_after_threshold, pdf_drive.mw) = _th_orig
        pkg.USER_FILES = _th_prev_uf
        shutil.rmtree(_th_uf, ignore_errors=True)

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
    check("K-146: no curate entry survives on the real menu (the source "
          "pin above says the string is gone; this says the built menu "
          "is)",
          not any("Curate" in t for t in _labels), repr(_labels))
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

    print("== PR #4 fourth review (1): Browse escapes the tag ==")
    # Copilot's fourth review: the stored lecture tag was interpolated
    # raw into Anki's query language by BOTH hops. A quote terminates
    # the operand, a backslash escapes what follows, and in a tag:
    # search * matches any run and _ any single character — so a PDF
    # named 'Renal "Phys" 1_2*.pdf' opened Browse on something else
    # entirely. One helper, tag_sync.tag_query, now mints the operand.
    class _FakeBrowser:
        def __init__(self):
            self.searches = []

        def search_for(self, q):
            self.searches.append(q)

    class _BrowseHost:
        def __init__(self, matches):
            self.matches = matches
            self.status = _StatusStub()

    _fb = _FakeBrowser()
    _hop_tag = '!Library::Renal_"Phys"_1_2*'
    _hop_ts = types.SimpleNamespace(
        get_stored_tag=lambda safe: _hop_tag,
        tag_query=_real_ts.tag_query,
    )
    _hop_ret = types.SimpleNamespace(get_threshold=lambda safe, cfg: 0.5,
                                     _cfg=lambda: {})
    _o_aqt = pdf_drive.aqt
    _o_ts_hop, _o_ret_hop = pdf_drive.tag_sync, pdf_drive.retention
    try:
        pdf_drive.aqt = types.SimpleNamespace(
            dialogs=types.SimpleNamespace(open=lambda name, parent: _fb))
        pdf_drive.tag_sync, pdf_drive.retention = _hop_ts, _hop_ret
        _bh = _BrowseHost({"renal": [(1, 0.9), (2, 0.2)]})
        pdf_drive.DriveWindow._on_browse(_bh, "renal")
        check("Show matches hops on the tag_query operand",
              _fb.searches == [_real_ts.tag_query(_hop_tag)],
              repr(_fb.searches))
        check("the quote and both wildcards really are escaped in what "
              "Browse receives",
              _fb.searches
              and 'Renal\\_\\"Phys\\"\\_1\\_2\\*' in _fb.searches[0],
              repr(_fb.searches))
    finally:
        pdf_drive.aqt = _o_aqt
        pdf_drive.tag_sync, pdf_drive.retention = _o_ts_hop, _o_ret_hop
    # No raw interpolation survives anywhere in the file (code_only would
    # strip these string literals, so this reads the raw source).
    check("no hop interpolates a bare tag into the query any more",
          'f\'tag:"{tag}"\'' not in _PD_SRC
          and "_escape_tag" not in _PD_SRC)

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

print("== K-135: the Library opens wide enough to show a name ==")
# K-127 made the numeric columns Fixed, which removed the give the name
# column used to have: at the old [300, 740] default it was left 24px
# and every row opened nameless (header truncated to "PL", offscreen
# render). Fixed widths do not yield, so the PANE has to fit them.
import re as _re135
_DRIVE = open("klausmate/pdf_drive.py", encoding="utf-8").read()
# The default lives in a variable (it was briefly conditional on pane
# count while the third, assistant pane existed; Task 11 removed that
# pane and the conditional with it) — the arithmetic this pin checks is
# unchanged.
_m135 = _re135.search(r"default = \[(\d+), (\d+)\]", _DRIVE)
_numeric135 = sum(
    int(w) for w in _re135.findall(r"setColumnWidth\([123], (\d+)\)", _DRIVE))
_INDENT135 = 16
check("the default splitter leaves a READABLE PDF-name column — the "
      "numeric columns are Fixed, so the pane must be wide enough for "
      "them plus a name, not the other way round",
      _m135 is not None
      and int(_m135.group(1)) - _numeric135 - _INDENT135 >= 200,
      f"name column = {int(_m135.group(1)) - _numeric135 - _INDENT135}px"
      if _m135 else "no default splitter sizes found")
check("...and the arithmetic is pinned against the REAL column widths, "
      "so widening a numeric column re-runs this check",
      _numeric135 == 84 + 88 + 88, f"numeric total {_numeric135}")

print("== Library retains two panes ==")
check("the third-pane AssistantPanel mount is gone — no import, no "
      "guard-log string for it, and self.assistant does not exist",
      "assistant_panel" not in _DRIVE
      and "assistant panel unavailable" not in _DRIVE
      and "self.assistant" not in _DRIVE)
check("_on_assistant_target is gone with the panel it targeted",
      "_on_assistant_target" not in _DRIVE)
check("the splitter default returns to a plain two-pane [560, 480] — no "
      "pane-count branch and no assistant-width constant survive",
      "default = [560, 480]" in _DRIVE
      and "_ASSISTANT_DEFAULT_W" not in _DRIVE
      and "self.splitter.count() == 3" not in _DRIVE)
check("the size guard still sizes itself off the splitter rather than a "
      "hardcoded two — that part of the K-198 guard survives the pane's "
      "removal", "self.splitter.count()" in _DRIVE)
print("== K-136: the name column has a FLOOR, not just a good default ==")
# K-135 widened the DEFAULT splitter (300 -> 560). That fixed first run,
# but it moved the cliff edge rather than removing it: the tree reports
# an 88px minimum while its own Fixed columns consume 260, so QSplitter
# will still hand it 288 the moment the user drags — and
# _sane_splitter_sizes accepts any pane >= _MIN_PANE (120), so ONE narrow
# drag PERSISTS and the Library opens nameless on every launch after.
# The fix is for the tree to declare the width it actually needs.
_D136 = open("klausmate/pdf_drive.py", encoding="utf-8").read()
check("a named floor for the PDF-name column exists",
      "_NAME_COL_FLOOR" in _D136)
check("the tree DECLARES its own minimum width — the lie that the "
      "splitter believed (88px reported vs 260px of Fixed columns) is "
      "what let the name column collapse",
      "setMinimumWidth" in _D136 and "_NAME_COL_FLOOR" in _D136)
check("...and that minimum is SUMMED from the real column widths, not a "
      "hardcoded total — K-127 and K-130 both widened these columns, and "
      "a literal 260 here would be a second number to keep in step",
      _re135.search(
          r"sum\(\s*self\.tree\.columnWidth\(c\)\s*for c in \(1, 2, 3\)\s*\)",
          _D136) is not None)
check("the stale K-132 arithmetic is gone — that comment still said the "
      "pane 'opens at 300px' after K-135 made it 560",
      "opens at 300px" not in _D136)

if _HAVE_QT:
    # BEHAVIOUR, on a real DriveWindow: the point of the floor is that
    # Qt CLAMPS a narrow setSizes back up. A source regex cannot show
    # that, so this drives the real splitter and measures the column.
    try:
        _w136 = pdf_drive.DriveWindow()
        app.processEvents()
        _floor = pdf_drive._NAME_COL_FLOOR
        _col0 = lambda: _w136.tree.columnWidth(0)

        check("the Library still OPENS wide (K-135 stands — the floor is "
              "a floor, not a new default)",
              _col0() >= 200, f"col0 = {_col0()}px")

        _w136.splitter.setSizes([300, 740])
        app.processEvents()
        check("dragging the pane to the old 300px no longer empties the "
              "name column — Qt clamps the splitter up to the tree's "
              "declared minimum",
              _col0() >= _floor, f"col0 = {_col0()}px, floor {_floor}")

        _w136.splitter.setSizes([150, 890])
        app.processEvents()
        check("...and a hostile/degenerate narrow value is clamped too, "
              "so a persisted bad splitter cannot reopen the bug",
              _col0() >= _floor, f"col0 = {_col0()}px, floor {_floor}")

        # The round trip is the ACTUAL failure mode the user reported:
        # the splitter is persisted on close, so before this floor ONE
        # narrow drag was saved and every later launch reopened
        # nameless. Drag, close, reopen, measure.
        _prev_uf = pkg.USER_FILES
        try:
            _uf136 = tempfile.mkdtemp(prefix="klaus_k136_uf_")
            os.makedirs(os.path.join(_uf136, "contexts"), exist_ok=True)
            pkg.USER_FILES = _uf136
            _rt = pdf_drive.DriveWindow()
            app.processEvents()
            _rt.splitter.setSizes([300, 740])
            app.processEvents()
            _rt.close()
            app.processEvents()
            _saved = pdf_drive.drive_store.get_window_state(
                _uf136).get("splitter")
            _rt2 = pdf_drive.DriveWindow()
            app.processEvents()
            check("a narrow drag SAVED and REOPENED still shows names — "
                  "the persisted-forever half of the bug, which a wider "
                  "default alone could not reach",
                  _rt2.tree.columnWidth(0) >= _floor,
                  f"saved {_saved}, reopened col0 = "
                  f"{_rt2.tree.columnWidth(0)}px")
            _rt2.close()
        finally:
            pkg.USER_FILES = _prev_uf

        # The floor has to be worth having: a real short PDF name must
        # fit at depth 1, where the text starts 32px in.
        _fm136 = _w136.tree.fontMetrics()
        _need = _fm136.horizontalAdvance("Renal Phys.pdf") + 32
        check("the floor actually fits a real nested PDF name, not just "
              "a nonzero number of pixels",
              _floor >= _need, f"floor {_floor}px, 'Renal Phys.pdf' at "
              f"depth 1 needs {_need}px")
        _w136.close()
    except Exception as _e136:  # noqa: BLE001
        check(f"K-136 offscreen DriveWindow checks ran ({_e136})", False)
else:
    print("  SKIP: PyQt6 unavailable — K-136 source pins above still ran")

print("== Task 11: a stale pre-removal three-pane splitter state is "
      "rejected, not partially applied ==")
# _sane_splitter_sizes requires the stored pane count to match the
# splitter's CURRENT one. Without that length check, a stored three-pane
# state (saved before Task 11 removed the assistant pane) would fall
# through to Qt's own setSizes() tolerance for a too-long list — its
# extra value silently dropped, the first two (the user's OLD tree/
# viewer split) applied as-is. That is "still works" by accident, not by
# design: this pins the documented behaviour instead — the mismatch is
# rejected as the wrong shape and the clean two-pane default takes over.
if _HAVE_QT:
    try:
        _uf_stale = tempfile.mkdtemp(prefix="klaus_t11_stale_")
        os.makedirs(os.path.join(_uf_stale, "contexts"), exist_ok=True)
        # All three values clear _MIN_PANE (120) deliberately — this
        # fixture isolates the PANE-COUNT mismatch specifically, so a
        # regression that drops just the length check (but keeps the
        # per-pane floor) cannot hide behind a coincidentally-narrow
        # third value tripping that other guard instead.
        pdf_drive.drive_store.save_window_state(
            _uf_stale, {"x": 0, "y": 0, "w": 1040, "h": 680,
                        "splitter": [850, 250, 150]})
        _prev_uf_stale = pkg.USER_FILES
        try:
            pkg.USER_FILES = _uf_stale
            _w_stale = pdf_drive.DriveWindow()
            app.processEvents()
            _sizes_stale = list(_w_stale.splitter.sizes())
            check("a legacy three-pane splitter state is REJECTED for "
                  "today's two-pane window — the default applies rather "
                  "than the stale 850/250 surviving by accident",
                  len(_sizes_stale) == 2 and abs(_sizes_stale[0] - 850) > 50,
                  f"splitter = {_sizes_stale}")
            _w_stale.close()
        finally:
            pkg.USER_FILES = _prev_uf_stale
        shutil.rmtree(_uf_stale, ignore_errors=True)
    except Exception as _e_stale:  # noqa: BLE001
        check(f"Task 11 stale-splitter checks ran ({_e_stale})", False)
else:
    print("  SKIP: PyQt6 unavailable — Task 11 stale-splitter check needs "
          "a real splitter")

print("== K-143: the Obsidian map box, bottom-left ==")
# Pouya (K-137): "I want the graph to be on the bottom left, sort of like
# how Obsidian does it, as a separate little box in the bottom left with
# a column of that sidebar thing", and "when I am viewing a PDF on the
# PDF viewer, it chooses that item".
_D143 = open("klausmate/pdf_drive.py", encoding="utf-8").read()
_D143_CODE = "".join(
    _t.string for _t in tokenize.generate_tokens(io.StringIO(_D143).readline)
    if _t.type != tokenize.COMMENT
)
check("the tree and the map share the pane through a VERTICAL splitter",
      "QSplitter(Qt.Orientation.Vertical" in _D143
      and "self.left_split" in _D143)
check("the box renders through pdf_map's factory — the ONE renderer the "
      "standalone Map window uses, never a second canvas class grown "
      "here to drift away from it (comments stripped: prose about the "
      "renderer is fine, a renderer is not)",
      "pdf_map.map_canvas(" in _D143
      and "QPainter" not in _D143_CODE
      and "paintEvent" not in _D143_CODE)
check("its height AND collapsed state persist, guarded like the main "
      "splitter's rather than trusted",
      '"map_split"' in _D143
      and "_sane_map_sizes" in _D143
      and _D143.count("def _sane_map_sizes") == 1)
check("the box's floor is a DELIBERATE named constant, not whatever the "
      "canvas's sizeHint happened to be",
      "_MAP_MIN_H" in _D143 and "_MAP_MIN_W" in _D143
      and "setMinimumHeight(_MAP_MIN_H)" in _D143
      and "setMinimumSize(_MAP_MIN_W, _MAP_MIN_H)" in _D143)
check("...and the box can never become the pane's binding WIDTH — that "
      "floor is K-136's, summed from the tree's own columns",
      pdf_drive._MAP_MIN_W
      < sum((84, 88, 88)) + pdf_drive._NAME_COL_FLOOR,
      f"map min width {pdf_drive._MAP_MIN_W}")
check("follow-the-viewer rides PdfSidebar's EXISTING on_loaded callback "
      "— the viewer already fires it on every load path, so no new "
      "signal was invented and no parameter threaded",
      # Was pinned as the literal "self.sidebar.on_loaded = ..."; K-173
      # forbids dereferencing self.sidebar at all (a None sidebar is a
      # real state), so the wiring now happens on the local the viewer
      # is built into. The CLAIM is unchanged and still falsifiable —
      # this fails the moment nothing assigns on_loaded.
      "on_loaded = self._on_viewer_loaded" in _D143
      and "def _on_viewer_loaded" in _D143)
check("both maps follow: the dock's canvas directly, the standalone "
      "window through K-138's select_pdf seam",
      "pdf_map.select_pdf(safe)" in _D143 and "cv.select(safe)" in _D143)
check("a shut box leaves ONLY the splitter handle behind, so the handle "
      "is widened to a real target and says what it does (offscreen "
      "render: at the stock width it is a hairline in the same token as "
      "the chrome around it, and a shut box looks gone, not closed)",
      "setHandleWidth" in _D143 and "handle.setToolTip(" in _D143)
check("the 17 s graph build NEVER runs inline — it is a QueryOp op, "
      "mw-parented like _refresh_rows', or the Library would freeze on "
      "every open. K-145 added a SECOND call site (Refresh's own "
      "rebuild) — both must still be inline as this exact QueryOp "
      "shape, never a third, bare kind of call to graph_data()",
      len(re.findall(r"QueryOp\(\s*parent=mw,\s*op=lambda _col: "
                      r"pdf_map\.graph_data\(\)", _D143)) == 2
      and _D143.count("graph_data()") == 2)

if _HAVE_QT:
    try:
        _uf143 = tempfile.mkdtemp(prefix="klaus_k143_uf_")
        os.makedirs(os.path.join(_uf143, "contexts"), exist_ok=True)
        _prev143 = pkg.USER_FILES
        pkg.USER_FILES = _uf143
        pdf_map = importlib.import_module("klausmate.pdf_map")
        _w = pdf_drive.DriveWindow()
        _w.resize(1040, 680)
        app.processEvents()

        check("the splitter holds the tree over the map box, in that "
              "order — bottom-left is the whole ask",
              _w.left_split.count() == 2
              and _w.left_split.widget(0) is _w.tree
              and _w.left_split.widget(1) is _w.map_box)
        check("the tree can never be collapsed away; the box can (that "
              "0 is the collapsed state _sane_map_sizes admits)",
              not _w.left_split.isCollapsible(0)
              and _w.left_split.isCollapsible(1))
        check("the box declares the deliberate floor, and it is a floor "
              "Qt enforces",
              _w.map_box.minimumHeight() == pdf_drive._MAP_MIN_H)
        _open_h = _w.left_split.sizes()[1]
        check("it OPENS at its default height, not at some leftover of "
              "the layout — and not merely at the floor, which Qt would "
              "clamp any bad default up to and hide",
              abs(_open_h - pdf_drive._MAP_DEFAULT_H) <= 30,
              f"opened at {_open_h}px, default "
              f"{pdf_drive._MAP_DEFAULT_H}")

        check("on_loaded is wired to the Library's own handler",
              _w.sidebar.on_loaded == _w._on_viewer_loaded)

        _G143 = {
            "pdfs": [{"safe": "lec1", "display": "Lecture One",
                      "folder": None, "threshold": .4, "retention": None,
                      "xy": [-0.5, -0.2], "match_count": 12},
                     {"safe": "lec2", "display": "Lecture Two",
                      "folder": "F", "threshold": .4, "retention": None,
                      "xy": [0.6, 0.4], "match_count": 4}],
            "notes": [{"nid": i, "xy": [i / 50.0 - 1.0, 0.1]}
                      for i in range(100)],
            "edges": [{"pdf": "lec1", "nid": i, "score": .9}
                      for i in range(12)],
        }
        _w._install_map(_G143)
        app.processEvents()
        check("the finished graph installs a real canvas in the box, "
              "swapping out the placeholder line",
              _w.map_canvas is not None
              and not _w.map_status.isVisible()
              and _w.map_fit_btn.isEnabled())
        check("the dock applies its own minimum to the shared canvas "
              "(the canvas brings none)",
              (_w.map_canvas.minimumWidth(),
               _w.map_canvas.minimumHeight())
              == (pdf_drive._MAP_MIN_W, pdf_drive._MAP_MIN_H))

        # The K-136 constraint this dock could most easily have broken,
        # and only once a canvas is IN the layout: pdf_map's canvas used
        # to declare a 480px minimum width of its own. The failure that
        # would cause is NOT a narrow name column (a wider pane widens
        # that too) — it is that the pane's minimum stops being the
        # tree's derived 420 and silently becomes the map's, so a
        # numeric-column change no longer moves the floor and the
        # Library refuses to narrow for a reason nothing on screen
        # explains. So measure exactly that.
        _floor143 = pdf_drive._NAME_COL_FLOOR
        _w.splitter.setSizes([150, 890])
        app.processEvents()
        check("the name column still clears K-136's floor with a canvas "
              "in the box",
              _w.tree.columnWidth(0) >= _floor143,
              f"col0 = {_w.tree.columnWidth(0)}px, floor {_floor143}")
        check("...and the TREE is still what sets the pane's minimum "
              "width — the map is never the widest thing in the pane, "
              "so K-136's derived floor keeps deriving",
              _w.map_box.minimumSizeHint().width()
              <= _w.tree.minimumWidth(),
              f"box needs {_w.map_box.minimumSizeHint().width()}px, "
              f"tree {_w.tree.minimumWidth()}px")
        _w._on_viewer_loaded("lec2")
        check("opening a PDF in the viewer SELECTS it on the map — "
              "K-137's other half",
              _w.map_canvas._selected == "lec2"
              and _w._map_last == "lec2")
        _w._on_viewer_loaded("gone-from-the-map")
        check("...and a PDF the map does not know CLEARS the ring "
              "rather than leaving a lie on screen",
              _w.map_canvas._selected is None)

        # A canvas that arrives AFTER the reader opened something: the
        # build takes seconds, so this is the common case, not the edge.
        _w2 = pdf_drive.DriveWindow()
        app.processEvents()
        _w2._on_viewer_loaded("lec1")
        check("a load during the build is not lost — the canvas opens on "
              "the node the viewer is already showing",
              _w2.map_canvas is None and _w2._map_last == "lec1")
        _w2._install_map(_G143)
        app.processEvents()
        check("(that is what _map_last is for)",
              _w2.map_canvas is not None
              and _w2.map_canvas._selected == "lec1")
        _w2.close()

        _w3 = pdf_drive.DriveWindow()
        app.processEvents()
        _w3._install_map({"pdfs": [], "notes": [], "edges": []})
        check("an empty graph gets pdf_map's own empty-state line, not a "
              "blank card — one wording, decided in one place",
              _w3.map_canvas is None
              and _w3.map_status.text() == pdf_map.EMPTY_TEXT)
        _w3.close()

        # ---- the guard, on the real window ----
        _sane = _w._sane_map_sizes
        check("_sane_map_sizes takes a healthy pair",
              _sane([400, 200]) == [400, 200])
        check("...admits an EXACT 0 for the map, because collapsed is a "
              "state the user chose",
              _sane([600, 0]) == [600, 0])
        check("...rejects the degenerate middle (a never-laid-out "
              "window's sizes), junk, and a crushed tree",
              _sane([600, 12]) is None
              and _sane([46, 46]) is None
              and _sane([400, "x"]) is None
              and _sane([400]) is None
              and _sane("nope") is None)

        # ---- the round trip the user actually performs ----
        _uf_rt = tempfile.mkdtemp(prefix="klaus_k143_rt_")
        os.makedirs(os.path.join(_uf_rt, "contexts"), exist_ok=True)
        pkg.USER_FILES = _uf_rt
        _rt = pdf_drive.DriveWindow()
        app.processEvents()
        _rt.left_split.setSizes([_rt.left_split.sizes()[0] - 60,
                                 _rt.left_split.sizes()[1] + 60])
        _want = _rt.left_split.sizes()[1]
        _rt.close()
        app.processEvents()
        _rt2 = pdf_drive.DriveWindow()
        app.processEvents()
        check("a resized box comes back the height it was left at",
              abs(_rt2.left_split.sizes()[1] - _want) <= 2,
              f"left {_want}, reopened {_rt2.left_split.sizes()[1]}")
        _rt2.left_split.setSizes([600, 0])
        app.processEvents()
        _rt2.close()
        app.processEvents()
        _rt3 = pdf_drive.DriveWindow()
        app.processEvents()
        check("a box dragged SHUT stays shut — collapsed persists "
              "through the same sizes the height does, no second key",
              _rt3.left_split.sizes()[1] == 0
              and _rt3._map_collapsed is True,
              repr(_rt3.left_split.sizes()))
        _rt3.close()
        pkg.USER_FILES = _uf143

        # ---- the build really is deferred, not just described as such
        _seen = []

        class _RecordQueryOp:
            def __init__(self, parent=None, op=None, success=None):
                _seen.append(op)

            def failure(self, cb):
                return self

            def run_in_background(self):
                pass

        _oldq, _oldmw = pdf_drive.QueryOp, pdf_drive.mw
        _boom = []
        _oldgd = pdf_map.graph_data
        pdf_map.graph_data = lambda: _boom.append(1)
        try:
            pdf_drive.QueryOp = _RecordQueryOp
            pdf_drive.mw = types.SimpleNamespace(col=object())
            _w4 = pdf_drive.DriveWindow()
            app.processEvents()
            _inline = list(_boom)  # must be empty: nothing ran on the GUI

            def _hits_graph_data(op):
                """_refresh_rows queues a QueryOp too — the map's op is
                the one that reaches graph_data when you run it."""
                n = len(_boom)
                try:
                    op(object())
                except Exception:
                    pass
                return len(_boom) > n

            def _map_ops():
                return sum(1 for o in _seen if _hits_graph_data(o))

            check("opening the Library hands graph_data to a QueryOp and "
                  "never calls it on the GUI thread — 16.9 s inline "
                  "would be 17 s of frozen Library per open",
                  _inline == [] and _map_ops() == 1,
                  f"ops={len(_seen)} map_ops={_map_ops()} "
                  f"inline={len(_inline)}")
            check("...and the box says so while it waits",
                  _w4.map_status.text() == pdf_map.BUILDING_TEXT)
            _n_before = _map_ops()
            _w4._ensure_map()
            _w4._on_map_split_moved()
            check("the build is once per window, whatever happens — a "
                  "retry per handle drag would burn 17 s of CPU a twitch",
                  _map_ops() == _n_before, f"{_map_ops()} vs {_n_before}")
            _w4.close()

            # A COLLAPSED box has to cost nothing, and this is the only
            # place that claim can be made: without a live mw there is
            # no build to skip, so asserting it anywhere else passes
            # vacuously (it did, until falsification caught it).
            pkg.USER_FILES = _uf_rt  # the profile left with a shut box
            _n_before = _map_ops()
            _w5 = pdf_drive.DriveWindow()
            app.processEvents()
            check("a collapsed box never starts the 17 s build — it pays "
                  "for itself only when it is open",
                  _w5._map_collapsed is True
                  and _w5._map_started is False
                  and _map_ops() == _n_before,
                  f"collapsed={_w5._map_collapsed} "
                  f"started={_w5._map_started} "
                  f"new map ops={_map_ops() - _n_before}")
            _w5.left_split.setSizes([400, 200])
            _w5._on_map_split_moved()
            check("...and dragging it open is what starts it",
                  _w5._map_started is True
                  and _map_ops() == _n_before + 1,
                  f"started={_w5._map_started} "
                  f"new map ops={_map_ops() - _n_before}")
            _w5.close()
            pkg.USER_FILES = _uf143
        finally:
            pdf_drive.QueryOp, pdf_drive.mw = _oldq, _oldmw
            pdf_map.graph_data = _oldgd

        _w.close()
        pkg.USER_FILES = _prev143
        shutil.rmtree(_uf143, ignore_errors=True)
        shutil.rmtree(_uf_rt, ignore_errors=True)
    except Exception as _e143:  # noqa: BLE001
        check(f"K-143 offscreen dock checks ran ({_e143})", False)
else:
    print("  SKIP: PyQt6 unavailable — K-143 source pins above still ran")


print("== K-145 (1): Refresh also rebuilds the dock's OWN map, once built ==")
# board/ARCHIVE.md, K-143's closing comment: "K-145 (Refresh does not
# rebuild the dock's graph; collapse is drag-only)". Only the first half
# is in scope here — the second (a chevron affordance for the drag-only
# collapse handle) is Pouya's own call to make once he has used it, not
# something to build. The dock's graph (self.map_canvas, built once by
# _ensure_map) was a PER-WINDOW SNAPSHOT: a re-index or a match-set edit
# left it showing a stale picture until the Library was closed and
# reopened. K-167's layout cache (pdf_graph.py's LAYOUT_SUBDIR/LAYOUT_FILE)
# already makes a warm graph_data() ~0.06s instead of ~17-25s cold, which
# is exactly the "becomes cheap" condition the card names — so Refresh
# now also queues a map rebuild, off the UI thread, the same QueryOp
# shape _ensure_map already uses, and only when a canvas is actually
# there to update (a collapsed-and-never-built box costs nothing, same
# as _ensure_map's own guard).
_D145 = open("klausmate/pdf_drive.py", encoding="utf-8").read()
check("_refresh_rows calls a dedicated map-refresh seam",
      "def _refresh_rows" in _D145 and "_refresh_map()" in _D145
      and "def _refresh_map" in _D145)
check("the map refresh is its own QueryOp — never inline on the caller "
      "of _refresh_rows, or a Refresh click would freeze the Library",
      re.search(r"def _refresh_map.*?QueryOp\(\s*parent=mw,\s*op=lambda "
                r"_col: pdf_map\.graph_data\(\)", _D145, re.S) is not None)

if _HAVE_QT:
    try:
        _uf145 = tempfile.mkdtemp(prefix="klaus_k145_uf_")
        os.makedirs(os.path.join(_uf145, "contexts"), exist_ok=True)
        _prev145 = pkg.USER_FILES
        pkg.USER_FILES = _uf145
        pdf_map = importlib.import_module("klausmate.pdf_map")

        def _g145(safe):
            return {
                "pdfs": [{"safe": safe, "display": safe, "folder": None,
                          "threshold": .4, "retention": None,
                          "xy": [-0.2, 0.1], "match_count": 3}],
                "notes": [{"nid": i, "xy": [i / 20.0 - 1.0, 0.0]}
                          for i in range(10)],
                "edges": [{"pdf": safe, "nid": i, "score": .9}
                          for i in range(3)],
            }

        _G145 = _g145("lec1")

        _seen145 = []

        class _RecordQueryOp145:
            def __init__(self, parent=None, op=None, success=None):
                self._op, self._success = op, success
                _seen145.append(self)

            def failure(self, cb):
                self._failure = cb
                return self

            def run_in_background(self):
                pass

        _oldq145, _oldmw145 = pdf_drive.QueryOp, pdf_drive.mw
        _oldgd145 = pdf_map.graph_data
        _graph_calls = []
        pdf_map.graph_data = lambda: (_graph_calls.append(1), _G145)[1]

        def _map_ops_since(mark):
            """How many QueryOps queued since ``mark`` reach
            pdf_map.graph_data when actually run — mirrors K-143's own
            _hits_graph_data/_map_ops helpers, since _refresh_rows queues
            a retention.priority_rows op too and only one of the two
            queued here is the map's."""
            found = 0
            for rec in _seen145[mark:]:
                before = len(_graph_calls)
                try:
                    result = rec._op(object())
                except Exception:
                    continue
                if len(_graph_calls) > before:
                    found += 1
                    if rec._success:
                        rec._success(result)
            return found

        try:
            pdf_drive.QueryOp = _RecordQueryOp145
            pdf_drive.mw = types.SimpleNamespace(col=object())

            # ---- positive: a window whose map dock is already built ----
            _w145 = pdf_drive.DriveWindow()
            app.processEvents()
            _w145._install_map(_G145)
            app.processEvents()
            check("setup: the dock's map is really built before Refresh runs",
                  _w145.map_canvas is not None
                  and "lec1" in _w145.map_canvas._pdf_by_safe)

            # The graph now on disk has changed (a re-index dropped lec1
            # and picked up lec2) — a real rebuild has to notice that,
            # not just repaint the same stale canvas.
            pdf_map.graph_data = lambda: (_graph_calls.append(1), _g145("lec2"))[1]

            _mark = len(_seen145)
            _w145._refresh_rows()
            app.processEvents()
            check("RED-then-GREEN: Refresh with an open map queues a "
                  "graph_data rebuild for the dock too, not just the "
                  "tree's own retention pass",
                  _map_ops_since(_mark) == 1,
                  f"map ops queued by _refresh_rows = {_map_ops_since(_mark)}")
            check("...and the rebuilt graph actually REPLACES the canvas "
                  "content (lec2, not last session's lec1) — a real "
                  "repaint, not just a queued no-op",
                  _w145.map_canvas is not None
                  and "lec2" in _w145.map_canvas._pdf_by_safe
                  and "lec1" not in _w145.map_canvas._pdf_by_safe,
                  f"pdfs on canvas = {list(_w145.map_canvas._pdf_by_safe)}")

            # ---- negative: no map open yet — Refresh must not crash on
            # a None canvas, and must not waste a rebuild nobody sees ----
            _w145b = pdf_drive.DriveWindow()
            app.processEvents()
            check("setup: a freshly opened window has no map canvas yet "
                  "(collapsed by default / not yet built)",
                  _w145b.map_canvas is None)
            _mark_b = len(_seen145)
            _w145b._refresh_rows()
            app.processEvents()
            check("Refresh with no map open never touches graph_data — "
                  "no crash, no wasted rebuild of a picture nobody sees",
                  _map_ops_since(_mark_b) == 0,
                  f"map ops queued = {_map_ops_since(_mark_b)}")

            _w145.close()
            _w145b.close()
        finally:
            pdf_drive.QueryOp, pdf_drive.mw = _oldq145, _oldmw145
            pdf_map.graph_data = _oldgd145
        pkg.USER_FILES = _prev145
        shutil.rmtree(_uf145, ignore_errors=True)
    except Exception as _e145:  # noqa: BLE001
        check(f"K-145 offscreen dock-refresh checks ran ({_e145})", False)
else:
    print("  SKIP: PyQt6 unavailable — K-145 source pins above still ran")


print("== K-173: the embedded Library opens a PDF — the viewer came back ==")
# fc8591c made the Library a screen inside Anki's main window and, in
# that mode, did not construct PdfSidebar AT ALL. Construction and
# teardown were guarded for that; the OPEN path was not —
# _on_item_activated still called self.sidebar.load_pdf(safe), so every
# double-click raised AttributeError on None and the handler's own
# except dressed it up as a modal "Could not open that PDF."
# (Pouya, 2026-09-01: "The library's PDF viewer doesn't work anymore for
# some reason.")
_D173 = open("klausmate/pdf_drive.py", encoding="utf-8").read()
_T173 = ast.parse(_D173)


def _self_sidebar(node):
    """True for the expression ``self.sidebar`` itself."""
    return (isinstance(node, ast.Attribute) and node.attr == "sidebar"
            and isinstance(node.value, ast.Name) and node.value.id == "self")


def _from_sidebar(node):
    """True for a value that IS the sidebar: ``self.sidebar`` or a
    ``self._ensure_sidebar()`` call."""
    if _self_sidebar(node):
        return True
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_ensure_sidebar")


# A SWEEP, not a hand-listed set: the whole point is that a seventh use
# added later is caught. Two ways to use the sidebar safely — never
# dereference the attribute directly, and None-test the local you bind
# it to in the same function.
_direct173, _unchecked173 = [], []
for _fn173 in ast.walk(_T173):
    if not isinstance(_fn173, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    _bound, _used, _checked = set(), set(), set()
    for _n in ast.walk(_fn173):
        if isinstance(_n, ast.Attribute) and _self_sidebar(_n.value):
            _direct173.append(f"{_fn173.name}: self.sidebar.{_n.attr}")
        if isinstance(_n, ast.Assign) and _from_sidebar(_n.value):
            for _t in _n.targets:
                if isinstance(_t, ast.Name):
                    _bound.add(_t.id)
        if (isinstance(_n, ast.Attribute) and isinstance(_n.value, ast.Name)):
            _used.add(_n.value.id)
        if (isinstance(_n, ast.Compare) and isinstance(_n.left, ast.Name)
                and len(_n.ops) == 1
                and isinstance(_n.ops[0], (ast.Is, ast.IsNot))
                and len(_n.comparators) == 1
                and isinstance(_n.comparators[0], ast.Constant)
                and _n.comparators[0].value is None):
            _checked.add(_n.left.id)
    for _name in sorted(_bound & _used):
        if _name not in _checked:
            _unchecked173.append(f"{_fn173.name}: {_name}")

check("self.sidebar is never dereferenced directly — a None sidebar is "
      "the state the embedded screen ships in, so every use binds it to "
      "a local first (AST sweep, so a seventh use is caught too)",
      not _direct173, repr(_direct173))
check("...and every local bound from it is None-tested in the same "
      "function", not _unchecked173, repr(_unchecked173))

_ctors173 = [n for n in ast.walk(_T173)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "PdfSidebar"]
_ensure_fn = next((f for f in ast.walk(_T173)
                   if isinstance(f, ast.FunctionDef)
                   and f.name == "_ensure_sidebar"), None)
check("there is a single choke point that builds the viewer",
      _ensure_fn is not None)
check("...and it is the ONLY place a PdfSidebar is constructed, so a "
      "viewer can never exist that the revive path does not know about",
      len(_ctors173) == 1
      and _ensure_fn is not None
      and any(c is n for n in ast.walk(_ensure_fn) for c in _ctors173),
      f"{len(_ctors173)} constructions")

_act173 = next((f for f in ast.walk(_T173) if isinstance(f, ast.FunctionDef)
                and f.name == "_on_item_activated"), None)
_body173 = list(_act173.body) if _act173 else []
if (_body173 and isinstance(_body173[0], ast.Expr)
        and isinstance(_body173[0].value, ast.Constant)):
    _body173 = _body173[1:]  # docstring
check("_on_item_activated is a SLOT and its body cannot raise — an "
      "unhandled exception in a Qt slot is qFatal in a bare interpreter and "
      "Anki's error dialog in Anki (K-183). item.data() included",
      len(_body173) == 1 and isinstance(_body173[0], ast.Try),
      f"{len(_body173)} top-level statements")
check("...and it no longer answers a failed double-click with a modal: "
      "showWarning execs internally (K-114/K-125) and a modal raised "
      "from inside a slot re-enters the event loop",
      _act173 is not None
      and not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "showWarning"
                  for n in ast.walk(_act173)))

if _HAVE_QT:
    try:
        # Task 10 (K-196): a clean slate for the viewer_context pins
        # further down this block — earlier sections above construct
        # plain DriveWindow()s that may have shown (and so activated) a
        # sidebar with no document loaded; reset() drops that residue
        # so "Renal" below is unambiguously the one report_document/
        # activate name.
        viewer_context.reset()

        def _proof_pdf(path):
            """One page, a fat black bar, real text. Ink you can count."""
            objs = [
                b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            ]
            stream = (b"0 0 0 rg 72 400 468 300 re f\n"
                      b"BT /F1 36 Tf 72 200 Td (KLAUS RENDER PROOF) Tj ET\n")
            objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream
                        + b"endstream")
            objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont "
                        b"/Helvetica >>")
            out, offs = bytearray(b"%PDF-1.4\n"), []
            for i, body in enumerate(objs, start=1):
                offs.append(len(out))
                out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
            xref = len(out)
            out += b"xref\n0 %d\n" % (len(objs) + 1)
            out += b"0000000000 65535 f \n"
            for off in offs:
                out += b"%010d 00000 n \n" % off
            out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n"
                    b"%%%%EOF\n" % (len(objs) + 1, xref))
            with open(path, "wb") as fh:
                fh.write(bytes(out))

        def _wait_ink(widget, want=200, tries=200):
            """Ink in a grab of ``widget``, waiting for it to arrive.

            pdfium renders pages on its own thread: a grab taken before
            the first page lands reads blank, and a fixed number of
            processEvents() turns that race into a flaky gate (measured:
            one run in six read 0 with the code correct). Bounded, so a
            pane that never renders still fails.
            """
            got = 0
            for _ in range(tries):
                got = _ink(widget)
                if got >= want:
                    return got
                app.processEvents()
                _QtC.QThread.msleep(10)
            return got

        def _ink(widget):
            """Count near-black pixels in a grab of ``widget`` — the
            page's own bar, which nothing in Klaus's chrome draws."""
            img = widget.grab().toImage()
            n = 0
            for y in range(0, img.height(), 3):
                for x in range(0, img.width(), 3):
                    px = img.pixel(x, y)
                    if (px & 0xFF) < 40 and ((px >> 8) & 0xFF) < 40 \
                            and ((px >> 16) & 0xFF) < 40:
                        n += 1
            return n

        _uf173 = tempfile.mkdtemp(prefix="klaus_k173_uf_")
        os.makedirs(os.path.join(_uf173, "contexts"), exist_ok=True)
        os.makedirs(os.path.join(_uf173, "pdfs"), exist_ok=True)
        _proof_pdf(os.path.join(_uf173, "pdfs", "Renal.pdf"))
        with open(os.path.join(_uf173, "contexts", "Renal.txt"), "w",
                  encoding="utf-8") as _fh:
            _fh.write("renal physiology page one\n")
        with open(os.path.join(_uf173, "contexts", "Renal.json"), "w",
                  encoding="utf-8") as _fh:
            json.dump({"pages": ["renal physiology page one"]}, _fh)
        pdf_drive.drive_store.record_import(_uf173, "Renal",
                                            "Renal Physiology.pdf")
        _prev173 = pkg.USER_FILES
        pkg.USER_FILES = _uf173

        def _mount(win):
            """What library_tab.mount() does: the screen is built
            PARENTLESS, added to mw.mainLayout, then shown."""
            host = _QtW.QWidget()
            host.resize(1600, 820)
            lay = _QtW.QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(win)
            host.show()
            win.show()
            for _ in range(12):
                app.processEvents()
            return host

        def _row(win, safe="Renal"):
            it = win.tree.topLevelItem(0)
            for i in range(win.tree.topLevelItemCount()):
                cand = win.tree.topLevelItem(i)
                if cand.data(0, pdf_drive._ROLE_SAFE) == safe:
                    return cand
            return it

        # A layout the user arranged, stored before this screen opens.
        # It is deliberately far from the [560, 480] default so the two
        # are distinguishable regardless of exactly how Qt's proportional
        # redistribution lands: the viewer pane should stay close to the
        # STORED 250 below, not drift toward the default's 480.
        pdf_drive.drive_store.save_window_state(
            _uf173, {"x": 0, "y": 0, "w": 1040, "h": 680,
                     "splitter": [850, 250]})

        # Capture the log while the screen opens: the host step is
        # wrapped whole, so a mistake in it (reading an attribute that
        # does not exist yet, say) is a LINE in the log and a green test
        # run. That is how the assistant-ordering bug got in.
        _logbuf = io.StringIO()
        _stdout = sys.stdout
        sys.stdout = _logbuf
        try:
            _emb = pdf_drive.DriveWindow(embedded=True)
            _host = _mount(_emb)
            # BOTH shapes: the standalone window builds its viewer
            # mid-__init__ and the screen builds it a tick after show,
            # so a step that reads something not constructed yet shows
            # up in only one of them.
            _standalone173 = pdf_drive.DriveWindow()
            app.processEvents()
            _standalone173.close()
        finally:
            sys.stdout = _stdout
        _log173 = _logbuf.getvalue()
        print(_log173, end="")
        check("opening the Library logs no viewer error — the build and "
              "host steps are wrapped, so a failure there is silent "
              "except for this line",
              "library viewer host failed" not in _log173
              and "library viewer unavailable" not in _log173,
              repr([l for l in _log173.splitlines() if "viewer" in l]))
        _item = _row(_emb)
        check("the embedded Library lists the PDF (the tree is intact — "
              "this card is about the viewer only)",
              _item is not None
              and _item.data(0, pdf_drive._ROLE_SAFE) == "Renal")

        # THE ACCEPTANCE TEST, driven through the real signal the tree
        # emits on a double-click — not by calling the handler.
        _emb.tree.itemDoubleClicked.emit(_item, 0)
        for _ in range(25):
            app.processEvents()
        _sb173 = _emb.sidebar
        check("double-clicking a PDF in the EMBEDDED Library builds a "
              "viewer and loads that PDF — the whole reported symptom",
              _sb173 is not None and _sb173.is_loaded("Renal"),
              f"sidebar={_sb173!r}")
        check("...and the status line was NOT turned into a failure "
              "message (fc8591c's AttributeError path)",
              "Could not open" not in _emb.status.text(),
              repr(_emb.status.text()))
        _pix173 = _wait_ink(_sb173) if _sb173 is not None else 0
        check("...and the page is actually ON SCREEN: the proof PDF's "
              "black bar is in a grab of the viewer pane, which no part "
              "of Klaus's own chrome draws (a render, not an assertion)",
              _pix173 > 200, f"{_pix173} near-black pixels")

        # Task 10 (K-196): this real, on-screen, just-loaded sidebar is
        # exactly the fixture viewer_context reporting needs — reused
        # rather than building a second one. Reset and reload DIRECTLY
        # (not via the double-click) first: _sb173 is already visible,
        # so this does not raise a fresh showEvent — isolating
        # load_pdf's own report_document/activate from the showEvent
        # that already fired once above (both are real call sites and
        # either alone would make this pass, which is exactly why this
        # step is needed to pin load_pdf's specifically).
        viewer_context.reset()
        _sb173.load_pdf("Renal")
        check("load_pdf reported the document into viewer_context and "
              "activated it as current()",
              viewer_context.current() is not None
              and viewer_context.current().pdf_safe == "Renal",
              repr(viewer_context.current()))
        # The proof PDF is one page; poke the count so page 3 is not
        # clamped back to 0 — _on_page_changed's own clamping is
        # pre-existing behaviour this pin has no interest in.
        _sb173._page_count = 10
        _sb173._on_page_changed(3)
        check("_on_page_changed reports the new page index into "
              "viewer_context",
              viewer_context.current() is not None
              and viewer_context.current().page_index == 3,
              repr(viewer_context.current()))
        _sb173._viewer.on_selection_changed("abc")
        check("the native viewer's selection-changed hook reports live "
              "selection text into viewer_context",
              viewer_context.current() is not None
              and viewer_context.current().selection == "abc",
              repr(viewer_context.current()))
        _sb173.cleanup()
        check("cleanup() forgets the viewer — current() is None once the "
              "sidebar is torn down",
              viewer_context.current() is None,
              repr(viewer_context.current()))

        # Task 10 (K-196) fix round 1 (review Important #2): _sb173 is
        # the NATIVE renderer (this whole block renders real QPdfView
        # pixels), so load_pdf above never touches _pending_count_name —
        # that only happens in the pdf.js branch. A source pin is the
        # proportionate way to cover that one line without standing up
        # a second, pdf.js-renderer fixture just for it.
        _PV_SRC_R1 = open("klausmate/pdf_viewer.py", encoding="utf-8").read()
        check("load_pdf's pdf.js branch captures the pending count's "
              "name at the same moment it sets self._name",
              "self._pending_count_name = name" in _PV_SRC_R1)

        # A late pdf.js count for a document this sidebar has since left
        # must not resurrect it as ACTIVITY — no activate(), no page/
        # selection reset. _pending_count_name is a single shared
        # attribute (the bridge carries no per-load token), so it
        # cannot by itself tell two DIFFERENT real documents' in-flight
        # counts apart — see the report's fix-round notes. What it
        # closes unconditionally, because report_page_count structurally
        # cannot do either, is exactly what the review called out: no
        # re-activation, no page/selection reset, no matter which
        # document the late count nominally lands on.
        viewer_context.reset()
        _sb173._name = "DocA"
        _sb173._pending_count_name = "DocA"
        _sb173._page_count = 5
        _sb173._report_document()
        _sb173._name = "DocB"
        _sb173._pending_count_name = "DocB"
        _sb173._page_count = 20
        _sb173._report_document()
        _sb173._on_page_changed(2)
        _sb173._viewer.on_selection_changed("bee")
        # A sentinel viewer activated after B is the only reliable way
        # to prove "no activate()": if the count catch-up called
        # activate(id(self)) it would steal current() back from this one.
        viewer_context.report_document(-1, "Sentinel", "Sentinel", "", 1)
        viewer_context.activate(-1)
        _sb173._on_pdfjs_count(999)  # A's late count, arriving after B loaded
        check("a late pdf.js count does not call activate() — a "
              "sentinel viewer activated after B stays current()",
              viewer_context.current() is not None
              and viewer_context.current().pdf_safe == "Sentinel",
              repr(viewer_context.current()))
        viewer_context.activate(id(_sb173))
        check("...and once B is current again, its page and selection "
              "are exactly as B left them — the late count reset "
              "neither (the pre-fix _report_document() re-call would "
              "have zeroed both)",
              viewer_context.current() is not None
              and viewer_context.current().pdf_safe == "DocB"
              and viewer_context.current().page_index == 2
              and viewer_context.current().selection == "bee",
              repr(viewer_context.current()))
        # The identity comparison's OWN logic, isolated: today's one
        # call site always sets _name and _pending_count_name together,
        # so a live sequence can never actually diverge them (a mutation
        # weakening the guard to bare "if self._name:" proved this —
        # neither pin above noticed, because report_page_count's own
        # contract already keeps them passing regardless). This pin
        # injects a synthetic mismatch directly to pin the comparison
        # itself, independent of whether a real call sequence reaches it
        # yet — a future second call site (or a reload of a DIFFERENT
        # document under the SAME renderer path) could.
        _sb173._name = "DocX"
        _sb173._pending_count_name = "DocY"
        _sb173._page_count = 1
        _sb173._on_pdfjs_count(555)
        check("_on_pdfjs_count is a strict no-op when the pending "
              "count's name does not match the CURRENT document name — "
              "the sidebar's own page_count is untouched",
              _sb173._page_count == 1, _sb173._page_count)

        check("the viewer pane sits right after the tree, the same "
              "two-pane shape the window has (Task 11 retired the "
              "third, assistant pane)",
              _emb.splitter.indexOf(_sb173) == 1,
              f"index {_emb.splitter.indexOf(_sb173)}")
        _sizes173 = list(_emb.splitter.sizes())
        check("a stored two-pane layout survives the viewer pane "
              "ARRIVING LATE: at restore time the splitter still had "
              "only the tree, so the saved pair was rejected as the "
              "wrong shape and the default applied — re-applying it "
              "once the pane lands is the only reason the user's own "
              "widths come back",
              len(_sizes173) == 2 and _sizes173[0] >= 800
              and _sizes173[1] >= 250,
              f"splitter = {_sizes173}")
        check("the tree still has a readable name column beside it "
              "(K-135's arithmetic survives the viewer pane arriving "
              "late)",
              _emb.tree.columnWidth(0) >= pdf_drive._NAME_COL_FLOOR,
              f"col0 = {_emb.tree.columnWidth(0)}px")

        # library_tab.unmount() HIDES the screen and keeps the tab for
        # the session; leaving and coming back must not cost the viewer.
        _emb.hide()
        app.processEvents()
        _emb.show()
        for _ in range(10):
            app.processEvents()
        _emb.tree.itemDoubleClicked.emit(_item, 0)
        for _ in range(20):
            app.processEvents()
        check("leaving the Library screen and coming back still opens a "
              "PDF — state_will_change only HIDES the tab, and a cleanup "
              "there would kill the viewer for every later visit",
              _emb.sidebar is not None and _emb.sidebar.is_loaded("Renal"))

        # A None sidebar must be survivable from every handler, not just
        # the ones someone remembered.
        _emb.sidebar = None
        _emb._delete_pdf_confirmed  # noqa: B018 — exists
        _survived = True
        try:
            _emb._on_viewer_loaded(None)
            _emb._save_geometry()
            _emb.shutdown()
        except Exception as _e_none:  # noqa: BLE001
            _survived = False
        check("every teardown/notify path survives self.sidebar is None",
              _survived)
        check("the viewer's window IS the host it was mounted into — it "
              "is never built in one top-level window and moved to "
              "another (K-090's black pane), which is the property that "
              "makes the splitter safe, not the widget it sits in",
              _sb173 is not None and _sb173.window() is _host,
              f"{_sb173.window()!r} vs {_host!r}")
        _host.close()

        # Task 8 (K-178): a documentless QPdfView must paint the
        # Library's own ground -- theme.palette(night)["bg"], one step
        # darker than the panels' "chrome" (K-206) -- never QPdfView's
        # raw mid-grey slab. The pane's ground does not depend on being
        # hosted inside a DriveWindow, so a fresh, unmounted PdfSidebar
        # per palette is enough on its own; this reuses the aqt.mw/QtPdf
        # state this section has already proven works for a real native
        # PdfSidebar (untouched by the pdf.js renderer switch below,
        # which purges and rebuilds klausmate.* fresh).
        print("== Task 8: the empty viewer pane is bg, not Qt's grey ==")
        pdf_viewer = importlib.import_module("klausmate.pdf_viewer")
        theme = importlib.import_module("klausmate.theme")
        _orig_night_mode8 = theme.night_mode
        try:
            for _night8 in (True, False):
                theme.night_mode = lambda n=_night8: n
                _sb8 = pdf_viewer.PdfSidebar(None, parent=None)
                _sb8.resize(600, 400)
                _sb8.show()
                for _ in range(3):
                    app.processEvents()
                # PdfSidebar wraps the native QPdfView inside its own
                # ._viewer (a PdfViewer), which is where ._pdf_view
                # actually lives -- not on the sidebar itself.
                _v8 = _sb8._viewer._pdf_view.viewport()
                _img8 = _v8.grab().toImage()
                _px8 = _QtG.QColor(_img8.pixel(_img8.width() // 2,
                                                _img8.height() // 2))
                _bg8 = _QtG.QColor(theme.palette(_night8)["bg"])
                check(f"night={_night8}: with no document the viewer's "
                      "centre is the bg token, not QPdfView's raw grey "
                      "(K-178)",
                      max(abs(_px8.red() - _bg8.red()),
                          abs(_px8.green() - _bg8.green()),
                          abs(_px8.blue() - _bg8.blue())) <= 8,
                      f"centre={_px8.name()} bg={_bg8.name()}")
                _sb8.cleanup()
                _sb8.close()
        finally:
            # Later sections (and later pins in this file) must see the
            # real theme.night_mode, not this loop's last lambda.
            theme.night_mode = _orig_night_mode8

        pkg.USER_FILES = _prev173
        shutil.rmtree(_uf173, ignore_errors=True)
    except Exception as _e173:  # noqa: BLE001
        check(f"K-173 offscreen render ran ({_e173})", False)
else:
    print("  SKIP: PyQt6 unavailable — K-173 source pins above still ran")


print("== K-173: ...on the pdf.js renderer, which is the one Pouya runs ==")
# config.json defaults pdf_renderer to "native", but the live value is in
# meta.json (unreadable by policy) and Pouya is on pdf.js — so the render
# above, real as it is, exercises a QPdfView he never sees. Under pdf.js
# PdfSidebar holds an AnkiWebView, which is the whole reason fc8591c gave
# for dropping the viewer.
#
# WHAT THIS CANNOT DO: PyQt6-WebEngine is not installed for this
# interpreter (verified: `from PyQt6 import QtWebEngineWidgets` raises
# ImportError), so no Chromium runs here and no pdf.js pixels exist to
# count. What IS checkable headlessly is everything Python owns — that
# the pdf.js renderer is the one selected, that the exact bytes of the
# PDF reach the page and the page is told to render them — plus the two
# properties the black-pane failure was actually about: the webview is
# never reparented across top-level windows, and it is unregistered from
# Anki's global hooks before it dies.
if _HAVE_QT:
    try:
        import base64 as _b64_173

        _theme_hook173: list = []

        class _FakeWeb173(_QtW.QWidget):
            """A real widget standing in for AnkiWebView.

            Mirrors the lifecycle that matters: AnkiWebView.__init__
            registers on_theme_did_change with Anki's global hook and
            ONLY cleanup() unregisters it, so a webview destroyed
            without cleanup leaves a dead bound method there and the
            user's next theme change crashes inside Anki's own iteration
            (live traceback 2026-08-25).
            """

            def __init__(self, parent=None):
                super().__init__(parent)
                self.evals, self.html = [], []
                self.alive = True
                self.birth_window = self.window()
                _theme_hook173.append(self.on_theme_did_change)
                _webs173.append(self)

            def on_theme_did_change(self):
                if not self.alive:
                    raise RuntimeError(
                        "wrapped C/C++ object of type AnkiWebView has "
                        "been deleted")

            def set_bridge_command(self, *_a, **_k):
                pass

            def stdHtml(self, html, **_k):  # noqa: N802 — Anki's name
                self.html.append(html)

            def eval(self, js):
                self.evals.append(js)

            def setZoomFactor(self, _f):  # noqa: N802 — Qt naming
                pass

            def cleanup(self):
                try:
                    _theme_hook173.remove(self.on_theme_did_change)
                except ValueError:
                    pass

            def destroy_cpp(self):
                self.alive = False

        _webs173: list = []
        _fired173 = []

        def _fire_theme173():
            """True when Anki's hook iteration survives intact."""
            try:
                for fn in list(_theme_hook173):
                    fn()
                return True
            except RuntimeError:
                return False

        _prev_web = sys.modules["aqt.webview"].AnkiWebView
        _prev_mwattr = aqt_mod.mw
        sys.modules["aqt.webview"].AnkiWebView = _FakeWeb173
        aqt_mod.mw = types.SimpleNamespace(
            addonManager=types.SimpleNamespace(
                getConfig=lambda *_a, **_k: {"pdf_renderer": "pdfjs"},
                addonFromModule=lambda *_a, **_k: "klausmate"),
            taskman=types.SimpleNamespace(
                run_in_background=lambda *_a, **_k: None),
            col=None)
        # Purging sys.modules is NOT enough to re-import a submodule:
        # `from . import pdfjs_viewer` reads the ATTRIBUTE off the
        # package first, so the stale module object comes back with the
        # old stubs still bound (that is exactly how this section first
        # ran against _Any instead of the fake webview, and read a None
        # mw). Drop both.
        for _name in [m for m in list(sys.modules)
                      if m.startswith("klausmate.")]:
            del sys.modules[_name]
            try:
                delattr(pkg, _name.split(".", 1)[1])
            except AttributeError:
                pass
        sys.modules["klausmate"] = pkg
        pdf_drive = importlib.import_module("klausmate.pdf_drive")
        pdf_viewer173 = importlib.import_module("klausmate.pdf_viewer")

        _ufjs = tempfile.mkdtemp(prefix="klaus_k173_js_")
        os.makedirs(os.path.join(_ufjs, "contexts"), exist_ok=True)
        os.makedirs(os.path.join(_ufjs, "pdfs"), exist_ok=True)
        _pdf_js_path = os.path.join(_ufjs, "pdfs", "Renal.pdf")
        _proof_pdf(_pdf_js_path)
        with open(os.path.join(_ufjs, "contexts", "Renal.txt"), "w",
                  encoding="utf-8") as _fh:
            _fh.write("renal physiology page one\n")
        # Under pdf.js the page count comes from the stored page text
        # until the webview's bridge reports the real one — which needs
        # a Chromium that does not exist here.
        with open(os.path.join(_ufjs, "contexts", "Renal.json"), "w",
                  encoding="utf-8") as _fh:
            json.dump({"pages": ["renal physiology page one"]}, _fh)
        pdf_drive.drive_store.record_import(_ufjs, "Renal",
                                            "Renal Physiology.pdf")
        pkg.USER_FILES = _ufjs

        _embjs = pdf_drive.DriveWindow(embedded=True)
        _hostjs = _mount(_embjs)
        _itemjs = _row(_embjs)
        _embjs.tree.itemDoubleClicked.emit(_itemjs, 0)
        for _ in range(25):
            app.processEvents()
        _sbjs = _embjs.sidebar

        check("the embedded Library is on the pdf.js renderer here — the "
              "one Pouya runs, and the one fc8591c dropped the viewer to "
              "avoid",
              _sbjs is not None and getattr(_sbjs, "_renderer", None)
              == "pdfjs", f"renderer={getattr(_sbjs, '_renderer', None)!r}")
        check("...and a double-click still opens the PDF there",
              _sbjs is not None and _sbjs.is_loaded("Renal"))

        _web173 = _webs173[-1] if _webs173 else None
        check("the pdf.js page itself was installed in the webview",
              _web173 is not None and len(_web173.html) == 1
              and "pdf" in _web173.html[0].lower())

        def _fed_bytes(web):
            """Reassemble what the page was handed: every klausPdfChunk
            payload, base64-decoded."""
            out = []
            for js in web.evals:
                if "klausPdfChunk(" not in js:
                    continue
                arg = js.split("klausPdfChunk(", 1)[1].rsplit(");", 1)[0]
                out.append(json.loads(arg))
            return _b64_173.b64decode("".join(out)) if out else b""

        with open(_pdf_js_path, "rb") as _fh:
            _want173 = _fh.read()
        check("the EXACT bytes of that PDF reached the page — chunked "
              "base64, reassembled and compared with the file on disk",
              _web173 is not None and _fed_bytes(_web173) == _want173,
              f"{len(_fed_bytes(_web173)) if _web173 else 0} of "
              f"{len(_want173)} bytes")
        check("...and the page was then told to render them (this is as "
              "far as headless can see: no Chromium, so no pixels)",
              _web173 is not None
              and any("klausPdfLoad" in js for js in _web173.evals))

        # THE property the 2026-08-25 black pane was about. K-090's
        # diagnosis: "a view reparented BEFORE first show can miss its
        # visibility transition and never attach a surface". An embedded
        # DriveWindow is built parentless and only then added to
        # mw.mainLayout, so a viewer built in its constructor WOULD cross
        # that boundary; built after the mount, it never does. This is
        # also lecture_view's property — its dock is parented to mw from
        # construction — so it is what makes the two shapes equivalent.
        check("the webview is BORN inside the main window and never "
              "moves: its window() at construction is the host, not the "
              "Library widget that was still parentless a tick earlier",
              _web173 is not None and _web173.birth_window is _hostjs,
              f"born in {_web173.birth_window!r}" if _web173 else "no web")
        check("...and it is still there after the mount",
              _sbjs is not None and _sbjs.window() is _hostjs)

        check("Anki's theme hook is intact while the Library is up",
              _fire_theme173())

        # K-095 for the screen, which has no close: library_tab.unmount
        # only HIDES the tab and keeps it for the session, so profile
        # switch and quit are where the webview must be handed back.
        _n_webs = len(_webs173)
        pdf_drive._release_embedded_viewers()
        for _ in range(5):
            app.processEvents()
        _web173.destroy_cpp()
        check("profile switch / quit unregisters the embedded Library's "
              "webview from Anki's global hooks BEFORE its C++ object "
              "dies — without it the next theme change crashes inside "
              "Anki's own iteration (K-095)",
              _fire_theme173())
        check("...and the husk is dropped, not kept as a dead pane",
              _embjs.sidebar is None
              and _embjs.splitter.indexOf(_sbjs) == -1)

        _embjs.tree.itemDoubleClicked.emit(_itemjs, 0)
        for _ in range(25):
            app.processEvents()
        check("a Library REUSED after that sweep builds a fresh viewer "
              "and opens the PDF again — library_tab keeps its tab for "
              "the session, so without the rebuild the screen would come "
              "back from a profile switch permanently unable to open "
              "anything",
              _embjs.sidebar is not None
              and _embjs.sidebar.is_loaded("Renal")
              and len(_webs173) == _n_webs + 1,
              f"{len(_webs173) - _n_webs} new webviews")
        check("...and the rebuilt pane goes back right after the tree, "
              "the splitter's whole shape now that the assistant pane "
              "is gone",
              _embjs.splitter.indexOf(_embjs.sidebar) == 1)

        # The BLANKET sweep is the harder case, and the one that
        # actually happens: pdf_viewer.cleanup_all_sidebars runs on
        # profile_will_close over every live sidebar (PdfSidebar
        # self-registers in _open_sidebars), and it leaves self.sidebar
        # SET — a viewer that is still a widget, still in the splitter,
        # and can never show a PDF again because its webview is gone.
        # Nothing else can notice that; _viewer_needs_rebuild is what
        # does.
        _n_webs2 = len(_webs173)
        pdf_viewer173.cleanup_all_sidebars()
        _husk = _embjs.sidebar
        _embjs.tree.itemDoubleClicked.emit(_itemjs, 0)
        for _ in range(25):
            app.processEvents()
        check("a sidebar the blanket sweep emptied is REPLACED, not "
              "reused — self.sidebar still points at a widget there, so "
              "'is it None' cannot tell you the viewer is dead",
              _embjs.sidebar is not None and _embjs.sidebar is not _husk
              and _embjs.sidebar.is_loaded("Renal")
              and len(_webs173) == _n_webs2 + 1,
              f"{len(_webs173) - _n_webs2} new webviews, "
              f"replaced={_embjs.sidebar is not _husk}")

        pdf_viewer173.cleanup_all_sidebars()
        for _w in _webs173:
            _w.destroy_cpp()
        check("...and with both teardown paths run over it, Anki's theme "
              "hook is still clean (cleanup is idempotent — belt and "
              "braces must not double-fault)",
              _fire_theme173())

        _hostjs.close()
        pkg.USER_FILES = _prev173
        shutil.rmtree(_ufjs, ignore_errors=True)
        sys.modules["aqt.webview"].AnkiWebView = _prev_web
        aqt_mod.mw = _prev_mwattr
    except Exception as _ejs:  # noqa: BLE001
        check(f"K-173 pdf.js checks ran ({_ejs})", False)
else:
    print("  SKIP: PyQt6 unavailable — the pdf.js checks need real widgets")


print("== the sensitivity save reaches a REAL embedded Library ==")
# The fake-window pins above stipulate the roster; this proves the two
# halves actually meet. A DriveWindow(embedded=True) built the way
# library_tab builds one must (a) put ITSELF in _embedded_windows and
# (b) be reached by refresh_open_library with _instance empty — which is
# exactly the state the Library SCREEN runs in, since _create() is the
# only writer of _instance and the tab never calls it.
if _HAVE_QT:
    _prev_ufe = pkg.USER_FILES
    _prev_set = list(pdf_drive._embedded_windows)
    _ufe = tempfile.mkdtemp(prefix="klaus_emb_refresh_uf_")
    _embw = None
    _hoste = None
    try:
        os.makedirs(os.path.join(_ufe, "contexts"), exist_ok=True)
        pkg.USER_FILES = _ufe
        pdf_drive._embedded_windows.clear()
        pdf_drive._instance = None

        _embw = pdf_drive.DriveWindow(embedded=True)
        # This block never opens a PDF: pre-mark the viewer arm as done so
        # the settle does not build a real PdfSidebar the block never uses.
        _embw._sidebar_arming = 1
        check("a real embedded Library enrols itself in the roster the "
              "hook walks — nothing else adds it, so a dropped add() "
              "silently un-wires the whole card",
              _embw in pdf_drive._embedded_windows)

        # library_tab mounts the parentless screen into mw's layout and
        # shows it there. isVisible() is synchronous after show(), so no
        # event turn is needed here.
        _hoste = _QtW.QWidget()
        _laye = _QtW.QVBoxLayout(_hoste)
        _laye.setContentsMargins(0, 0, 0, 0)
        _laye.addWidget(_embw)
        _hoste.resize(1200, 700)
        _hoste.show()
        _embw.show()

        _hits = []
        _embw._refresh_rows = lambda *a, **k: _hits.append(1)
        pdf_drive.refresh_open_library()
        # Honest title: _refresh_rows is stubbed and the harness has mw=None
        # (the real method would return on its first line), so this proves
        # the hook REACHES a real embedded window — roster + walk — and
        # nothing about what _refresh_rows then does.
        check("saving the default match sensitivity reaches a REAL embedded "
              "Library's refresh hook — the screen Pouya is looking at, "
              "which _instance has never pointed at (K-052, regressed by "
              "the move into a tab)",
              len(_hits) == 1, f"{len(_hits)} refreshes, "
              f"_instance={pdf_drive._instance!r}")

        # Hidden is the state library_tab leaves the screen in whenever
        # the user is anywhere else in Anki, and it is kept in the set.
        _embw.hide()
        del _hits[:]
        pdf_drive.refresh_open_library()
        check("...and a screen the user has navigated away from is marked "
              "pending, not refreshed, on the real widget as on the fakes",
              not _hits and _embw._refresh_pending is True,
              f"{len(_hits)} refreshes, pending={_embw._refresh_pending!r}")
        _embw.show()
        app.processEvents()
        check("...and its next show() runs exactly one refresh for however many "
              "saves happened while it was hidden",
              len(_hits) == 1 and _embw._refresh_pending is False,
              f"{len(_hits)} refreshes, pending={_embw._refresh_pending!r}")

        # PROFILE SWITCH: shutdown()'s only caller is closeEvent, which the
        # tab never gets; release_viewer strips only the sidebar. Without a
        # pending-refresh flag the next mount() showed the OLD collection's
        # rows. The release marks the window stale and the next show
        # schedules one refresh (deferred a tick, like the sidebar arm).
        _embw.hide()                        # unmounted, as at a real profile close
        del _hits[:]
        _embw._map_started = True          # as if a map had been built
        _seq_before = _embw.seq
        pdf_drive._release_embedded_viewers()
        check("collection close marks the screen stale: rows pending, seq bumped "
              "so an in-flight priority_rows cannot land on the new profile, and "
              "the MAP dropped so _ensure_map rebuilds it (the map was never "
              "reset before — the previous collection's constellation stayed)",
              _embw._refresh_pending is True and _embw.seq == _seq_before + 1
              and _embw._map_started is False and _embw.map_canvas is None,
              f"pending={_embw._refresh_pending!r} seq={_embw.seq}/{_seq_before} "
              f"map_started={_embw._map_started!r}")
        _embw.show()
        app.processEvents()
        check("...and the next show() schedules exactly one refresh, so a "
              "remounted Library never shows the previous profile's rows",
              len(_hits) == 1 and _embw._refresh_pending is False,
              f"{len(_hits)} refreshes, pending={_embw._refresh_pending!r}")
    except Exception as _e_emb:  # noqa: BLE001
        check(f"embedded-refresh offscreen checks ran ({_e_emb})", False)
    finally:
        # Restoration is unconditional (the file's own idiom, cf. the
        # try/finally around USER_FILES at K-136): a raise anywhere above
        # must not leave USER_FILES on a temp dir, the roster emptied, or
        # this widget alive — shutdown() is what detaches the
        # index_queue listener whose bound method would otherwise keep
        # the DriveWindow (and its sidebar) alive to process exit.
        try:
            if _embw is not None:
                _embw.shutdown()
        except Exception as _e_sd:  # noqa: BLE001
            print(f"  (embedded window shutdown raised: {_e_sd})")
        try:
            if _hoste is not None:
                _hoste.close()
        except Exception:
            pass
        pdf_drive._embedded_windows.clear()
        for _w in _prev_set:
            pdf_drive._embedded_windows.add(_w)
        pdf_drive._instance = None
        pkg.USER_FILES = _prev_ufe
        shutil.rmtree(_ufe, ignore_errors=True)
else:
    print("  SKIP: PyQt6 unavailable — the fake-window pins above still ran")


print("== a theme flip re-styles every live Library, hidden or not ==")
# Pouya, live screenshot: the embedded Library stayed dark after Anki
# switched to light — it is built ONCE per session (library_tab caches
# the tab) and its stylesheet was only ever applied at construction.
# gui_hooks.theme_did_change now walks the same roster refresh_open_
# library uses and re-paints each window's own chrome, its status/map
# labels, and the drop zone against theme.night_mode() as it is NOW.
if _HAVE_QT:
    # Fetched fresh, not the `theme` bound earlier in this file: pdf_drive
    # gets reloaded (del sys.modules + re-import) between here and there,
    # and mutating a stale module object would silently never reach the
    # `theme` THIS pdf_drive resolves internally via `from . import theme`.
    theme = importlib.import_module("klausmate.theme")
    _prev_uft = pkg.USER_FILES
    _prev_night = theme.night_mode
    _uft = tempfile.mkdtemp(prefix="klaus_theme_refresh_uf_")
    _wint = None
    try:
        os.makedirs(os.path.join(_uft, "contexts"), exist_ok=True)
        pkg.USER_FILES = _uft
        pdf_drive._embedded_windows.clear()
        pdf_drive._instance = None

        theme.night_mode = lambda: False
        _wint = pdf_drive.DriveWindow(embedded=True)
        _wint._sidebar_arming = 1
        _day_sheet = _wint.styleSheet()
        _day_drop = _wint.drop_zone.styleSheet()
        _wint.hide()  # library_tab's resting state — a flip must still land

        theme.night_mode = lambda: True
        pdf_drive._restyle_live_libraries()
        check("the window's own chrome repaints to the NEW theme, exactly "
              "what library_qss(True) builds — not just something "
              "different from before",
              _wint.styleSheet() == theme.library_qss(True))
        check("...the drop zone repaints too — it carries its own "
              "independent sheet, never covered by the window's",
              _wint.drop_zone.styleSheet() == theme.drop_zone_qss(
                  True, "klausmateLibraryDropZone"))
        check("...and it happened while HIDDEN — a flip must reach the "
              "tab whether or not the user is looking at it right now",
              not _wint.isVisible())
        check("...genuinely repainted, not coincidentally identical: the "
              "day and night sheets actually differ",
              _wint.styleSheet() != _day_sheet
              and _wint.drop_zone.styleSheet() != _day_drop)

        theme.night_mode = lambda: False
        pdf_drive._on_theme_change()
        app.processEvents()
        check("the module hook (what theme_did_change actually calls) "
              "reaches the same window one tick later",
              _wint.styleSheet() == theme.library_qss(False))
    except Exception as _e_theme:  # noqa: BLE001
        check(f"theme-refresh offscreen checks ran ({_e_theme})", False)
    finally:
        theme.night_mode = _prev_night
        try:
            if _wint is not None:
                _wint.shutdown()
        except Exception as _e_sd2:  # noqa: BLE001
            print(f"  (theme-test window shutdown raised: {_e_sd2})")
        pdf_drive._embedded_windows.clear()
        pdf_drive._instance = None
        pkg.USER_FILES = _prev_uft
        shutil.rmtree(_uft, ignore_errors=True)
else:
    print("  SKIP: PyQt6 unavailable — the theme-refresh checks above still ran")


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
