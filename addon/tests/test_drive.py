"""Headless tests for drive_store + pdf_drop/pdf_drive importability.

Run: env QT_QPA_PLATFORM=offscreen python3 test_drive.py
"""
import ast
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

print("== K-146: _on_embed refreshes the CARD index first ==")
# THE regression this card could have shipped. curation.ensure_index —
# one embedding per note — was reachable only through run_curation,
# behind the curate button. Indexing a PDF never touched it. Delete the
# button without moving that call and every note written since the last
# card-index pass is invisible to ensure_matches: no error, no warning,
# the per-PDF !Library tag just quietly under-covers. So the order here
# is load-bearing, and ensure_index must come FIRST — matching against a
# stale card index is exactly the silent failure.


class _EmbedStatus:
    def __init__(self):
        self.texts = []

    def setText(self, t):
        self.texts.append(t)


class _EmbedHost:
    def __init__(self):
        self.seq, self.status, self.refreshes = 7, _EmbedStatus(), 0

    def _begin(self):
        return self.seq, "cancel-token"

    def _finish(self, seq):
        return seq == self.seq

    def _refresh_rows(self):
        self.refreshes += 1

    def _on_progress(self, seq, label, done, total):
        pass


def _run_embed(*, card_index_completed=True, pdf_index_complete=True):
    """Drive _on_embed with every phase answering synchronously."""
    calls = []

    class _Idx:
        def is_complete(self):
            return pdf_index_complete

    def _ensure_index(parent, *, on_progress=None, on_done=None,
                      on_error=None, cancel=None):
        calls.append(("ensure_index", cancel))
        on_done(_Idx(), card_index_completed)

    def _ensure_pdf_index(parent, safe, *, on_progress=None, on_done=None,
                          on_error=None, cancel=None):
        calls.append(("ensure_pdf_index", safe))
        on_done(_Idx())

    def _ensure_matches(parent, safe, *, on_progress=None, on_done=None,
                        on_error=None, cancel=None):
        calls.append(("ensure_matches", safe))
        on_done([(1, 0.9)])

    host = _EmbedHost()
    _o = (pdf_drive.curation, pdf_drive.retention, pdf_drive.tag_sync,
          pdf_drive.mw)
    pdf_drive.curation = types.SimpleNamespace(ensure_index=_ensure_index)
    pdf_drive.retention = types.SimpleNamespace(
        ensure_pdf_index=_ensure_pdf_index, ensure_matches=_ensure_matches)
    pdf_drive.tag_sync = types.SimpleNamespace(
        sync_after_matches=lambda *a: calls.append(("sync_after_matches",)))
    pdf_drive.mw = types.SimpleNamespace(col=object())
    try:
        pdf_drive.DriveWindow._on_embed(host, "Renal_Phys")
    finally:
        (pdf_drive.curation, pdf_drive.retention, pdf_drive.tag_sync,
         pdf_drive.mw) = _o
    return host, calls


try:
    _h, _calls = _run_embed()
    _names = [c[0] for c in _calls]
    check("the card index is refreshed BEFORE the PDF is matched — "
          "run_curation was the only path that used to do this",
          _names == ["ensure_index", "ensure_pdf_index", "ensure_matches",
                     "sync_after_matches"], repr(_names))
    check("the run's cancel token reaches ensure_index too (Cancel must "
          "stop the longest phase, not just the two after it)",
          _calls[0][1] == "cancel-token", repr(_calls[0]))
    check("a completed run still ends in the tag sync and a row refresh",
          _h.refreshes == 1 and _h.status.texts
          and "refreshing retention" in _h.status.texts[-1],
          repr(_h.status.texts))

    _h2, _calls2 = _run_embed(card_index_completed=False)
    check("a CANCELLED card-index pass stops the chain there — matching "
          "on a half-built index is the silent under-cover this whole "
          "pin exists for",
          [c[0] for c in _calls2] == ["ensure_index"], repr(_calls2))
    check("...and says so, rather than reporting success",
          _h2.status.texts and "cancelled" in _h2.status.texts[-1].lower()
          and _h2.refreshes == 0, repr(_h2.status.texts))

    _h3, _calls3 = _run_embed(pdf_index_complete=False)
    check("the pre-existing cancelled-PDF-index branch still short-"
          "circuits (the new phase did not swallow it)",
          [c[0] for c in _calls3] == ["ensure_index", "ensure_pdf_index"],
          repr(_calls3))
except Exception as e:
    check("_on_embed phase order", False, f"{type(e).__name__}: {e}")

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
_m135 = _re135.search(
    r"setSizes\(sane if sane is not None else \[(\d+), (\d+)\]\)", _DRIVE)
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
      "self.sidebar.on_loaded = self._on_viewer_loaded" in _D143
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
      "every open",
      re.search(r"QueryOp\(\s*parent=mw,\s*op=lambda _col: "
                r"pdf_map\.graph_data\(\)", _D143) is not None
      and _D143.count("graph_data()") == 1)

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


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
