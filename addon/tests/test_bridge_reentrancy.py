"""The dialog crash rules, enforced across the whole addon.

TWO RULES, one crash saga (seven live segfaults, 2026-08-24..26, all
EXC_BAD_ACCESS in QPaintDevice::devicePixelRatio inside
QBackingStore::flush during a Python QDialog's exec()):

1. Never open a modal dialog (or any nested event loop) synchronously
   from a handler Anki dispatches over QWebChannel — defer with
   QTimer.singleShot(0, ...) so the bridge call unwinds first. This
   was the ORIGINAL diagnosis; it is kept as real hygiene (Qt's docs
   warn about it), but the crash reports later FALSIFIED it as the
   cause: the identical crash fired from a Tools-menu QAction and
   from a clean deferred timer slot too.

2. THE ACTUAL FIX — never show a dialog application-modal via exec()
   on this stack (Qt 6.11 + macOS 26 "Tahoe"): app-modal exec runs
   through AppKit's NSApp modal-session machinery, which races
   Tahoe's window-appear animation and flushes a backing store whose
   paint device is null. Window-modal dlg.open() (what Anki's own
   dialogs use) and popup QMenu.exec take different AppKit paths and
   never crashed. Preferences now opens NON-MODAL with dlg.show() —
   the same normal window path as open(), minus the modality (dropped
   2026-08-30 so it works as a live control panel beside the main
   window) — pinned below. K-114 then retired every remaining
   app-modal exec site (the deck square's scope dialog, __init__'s crop
   dialog, setup_flow's five message boxes, pdfjs_viewer's two input
   prompts; pdf_drive's threshold dialog went under K-117) — per-file
   bans pinned at the bottom of this file.

The crash is invisible to the rest of the suite (Qt widgets are never
constructed headlessly), so these are source pins. They are deliberately
split: per-site pins for the entry points that exist today, plus TWO
auto-discovered rosters that widen on their own — the registered
js-message handlers (a pin FAILS when a new one appears, forcing a
human to confirm it defers) and pdfjs_viewer's _bridge_* dispatch
table (crash #1's shape: any new _bridge_ method lands in the modal
scan automatically). A new handler is exactly how this bug reached a
user twice.
"""
import ast
import io
import sys
import textwrap
import tokenize
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

_MODULES = {
    "__init__": open("klausmate/__init__.py").read(),
    "top_bar": open("klausmate/top_bar.py").read(),
    "pdf_drop": open("klausmate/pdf_drop.py").read(),
    "pdfjs_viewer": open("klausmate/pdfjs_viewer.py").read(),
    "pdf_drive": open("klausmate/pdf_drive.py").read(),
    "heatmap": open("klausmate/heatmap.py").read(),
    "dashboard": open("klausmate/dashboard.py").read(),
    "setup_flow": open("klausmate/setup_flow.py").read(),
    "curation": open("klausmate/curation.py").read(),
    "bottom_row": open("klausmate/bottom_row.py").read(),
}
# Parsed once per module — _func_src and both roster scans below walk
# these shared trees instead of re-parsing per lookup.
_TREES = {mod: ast.parse(src) for mod, src in _MODULES.items()}


def _func_src(module: str, name: str) -> str:
    """Source of one top-level or nested function, by name (AST, so a
    later same-named string in the file can't fake a pass)."""
    src = _MODULES[module]
    for node in ast.walk(_TREES[module]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                seg = ast.get_source_segment(src, node)
                if seg:
                    return seg
    return ""


section("the roster of webchannel-dispatched handlers")
# Anki dispatches these over QWebChannel. Every one is a place the rule
# applies. If this set changes, the new handler needs the same audit.
_registered = set()
for mod in _MODULES:
    for node in ast.walk(_TREES[mod]):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "append"):
            continue
        inner = f.value
        if (
            isinstance(inner, ast.Attribute)
            and inner.attr == "webview_did_receive_js_message"
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            _registered.add(f"{mod}.{node.args[0].id}")

# STILL FIVE after K-151, with one member RENAMED. That card retired the
# armed drop square and its "klausmate_disarm" command, and its board
# text predicted the roster would fall to four — but what left was a
# COMMAND, not a handler: on_deck_js_message stays registered for the
# square's remaining Browse… click, which is the single most important
# entry on this list (a QFileDialog raised straight out of the
# webchannel call). The module around it moved deck_curate.py ->
# pdf_drop.py, so the qualified name changed and this pin failed until
# someone confirmed the new name is the same audited code.
#
# The set is exact in BOTH directions on purpose: a handler arriving
# needs the deferral audit, and a handler leaving or moving needs the
# same deliberate look. Never widen this to a count or a subset.
check("exactly the five known js-message handlers are registered — a "
      "NEW one must be audited against the deferral rule and added here",
      _registered == {
          "__init__.on_js_message",
          "top_bar._on_js_message",
          "pdf_drop.on_deck_js_message",
          "heatmap._on_js_message",
          "dashboard._on_js_message",
          "bottom_row._on_js_message",
      }, str(sorted(_registered)))

section("pdfjs_viewer: the _bridge_* dispatch table (crash #1's shape)")
# _on_bridge routes "klaus:<action>:<payload>" to methods named
# _bridge_<action> via getattr — every one is dispatched over
# QWebChannel exactly like the gui_hooks handlers above. Discovered
# from the AST so a NEW bridge action lands in the modal scan below
# automatically, instead of needing someone to remember this file.
_bridge_methods = {
    f"pdfjs_viewer.{node.name}"
    for node in ast.walk(_TREES["pdfjs_viewer"])
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name.startswith("_bridge_")
}
check("discovery is live — it finds both methods that crashed in the "
      "wild, so the scan below can never pass vacuously",
      {"pdfjs_viewer._bridge_note_edit",
       "pdfjs_viewer._bridge_goto_request"} <= _bridge_methods,
      str(sorted(_bridge_methods)))

section("top_bar: the Preferences star (live crash #2)")
_TB = _func_src("top_bar", "_on_js_message")
check("the settings handler was found in the source", bool(_TB))
check("manage_models_dialog is deferred, not called inline — it ends in "
      "a modal dlg.exec()",
      "QTimer.singleShot(0, manage_models_dialog)" in _TB
      and "\n            manage_models_dialog()" not in _TB)

section("pdf_drop: the drop square's file picker")
# K-146 removed this file's other two bridge branches with the curate
# button (_on_curate_clicked, which deferred _curate_with's scope dialog
# and _pick_pdf_menu's nested menu.exec()); K-151 removed the third with
# the armed square (the × that sent klausmate_disarm). The Browse…
# picker is the ONLY branch left — and it is the one that matters most:
# QFileDialog opened straight out of the webchannel call.
_BROWSE = _func_src("pdf_drop", "_on_browse_clicked")
check("the file-picker branch was found in the source", bool(_BROWSE))
check("the file-picker path still defers (it always did)",
      "QTimer.singleShot(0, _browse_for_pdfs)" in _BROWSE)
check("nothing raises a picker inline beside it",
      "        _browse_for_pdfs()" not in _BROWSE)

section("__init__: editor bridge actions (already correct)")
_INIT = _func_src("__init__", "on_js_message")
check("crop defers its modal", "_launch_crop_dialog(editor, fname)" in _INIT
      and "QTimer.singleShot(0, lambda: _launch_crop_dialog" in _INIT)
check("library defers its QMenu",
      "QTimer.singleShot(0, lambda: _on_library_button(editor))" in _INIT)

section("pdfjs_viewer: page bridge (live crash #1)")
_NOTE = _func_src("pdfjs_viewer", "_bridge_note_edit")
_GOTO = _func_src("pdfjs_viewer", "_bridge_goto_request")
check("note-edit defers its QInputDialog",
      "QTimer.singleShot(0, lambda: self._do_note_edit(hl_id))" in _NOTE
      and "getMultiLineText" not in _NOTE)
check("goto defers its QInputDialog",
      "QTimer.singleShot(0, self._goto_dialog)" in _GOTO
      and "getInt" not in _GOTO)

def _code_only(src: str) -> str:
    """Source with comments removed, LAYOUT PRESERVED — these handlers
    now *describe* the modals they defer, so a prose scan would flag
    its own documentation. untokenize (not a token join) because the
    scan below matches multi-char source spellings like ".exec()":
    space-joined tokens ("dlg . exec ( )") can never match any of
    them, which silently turns the whole scan vacuous."""
    flat = textwrap.dedent(src)
    try:
        toks = [
            t
            for t in tokenize.generate_tokens(io.StringIO(flat).readline)
            if t.type != tokenize.COMMENT
        ]
        return tokenize.untokenize(toks)
    except Exception:
        return "\n".join(ln.split("#", 1)[0] for ln in flat.splitlines())


section("no bridge handler opens a nested loop in its own body")
# Runs over BOTH rosters: the registered js-message handlers and the
# whole _bridge_* dispatch table. Transitive calls can't be caught from
# source alone (the top_bar crash was one: the handler body held no
# modal token at all, just a call to something that did). This catches
# the blatant case only, and says so.
_MODAL = (".exec()", "QInputDialog.get", "QFileDialog.get",
          "QColorDialog.get", "QMessageBox(",
          # aqt's own modal helpers are QMessageBox under the hood.
          "showWarning(", "showInfo(", "showCritical(", "askUser(")
check("the scan can actually match — a real dlg.exec() is found and a "
      "commented-out one is not (guards _code_only against regressing "
      "into a form no _MODAL spelling can ever appear in)",
      ".exec()" in _code_only("def f():\n    dlg.exec()\n")
      and ".exec()" not in _code_only("def f():\n    pass  # dlg.exec()\n"))
for qualified in sorted(_registered | _bridge_methods):
    mod, name = qualified.split(".", 1)
    body = _code_only(_func_src(mod, name))
    direct = [tok for tok in _MODAL if tok in body]
    check(f"{qualified} opens no modal directly in its own body",
          not direct, str(direct))

section("bottom_row: the main window row's gear and readout")
_BR = _func_src("bottom_row", "_on_js_message")
check("the row's handler was found in the source", bool(_BR))
check("Preferences and the task-list popup both open a tick later, never "
      "inside the webchannel call",
      _BR.count("QTimer.singleShot(0,") == 2
      and "\n            status_bar._open_anki_settings()" not in _BR, _BR[-400:])

section("heatmap: a clicked day opens Browse")
_HM = _func_src("heatmap", "_on_js_message")
check("the cell-click handler was found in the source", bool(_HM))
check("opening the Browser is deferred like every other window this "
      "addon raises from a bridge message",
      "QTimer.singleShot(0, lambda: _open_day(day))" in _HM
      and "        _open_day(day)" not in _HM)
check("the day is frozen into the deferred callback rather than "
      "re-parsed a tick later", "int(message.rsplit" in _HM)


section("dashboard: add-refresh tears the webview down under the bridge")
_DASH = _func_src("dashboard", "_on_js_message")
check("the dashboard handler was found in the source", bool(_DASH))
check("the refresh a widget-add triggers is deferred — it rebuilds the "
      "very webview the webchannel message arrived from",
      "QTimer.singleShot(0, _refresh)" in _DASH
      and "\n        _refresh()" not in _DASH)


section("manage_models: Preferences opens non-modal, never exec()")
# Seven identical segfaults (macOS 26.5 + Qt 6.11) killed this dialog's
# app-modal exec() from three different dispatch shapes; the normal
# window path (first window-modal open(), non-modal show() since
# 2026-08-30 — same path, no modality) is the fix. Nothing consumed
# exec()'s return value — every close path is callback-driven — so
# this pin has no behavioural cost to hold. anki_stubs.code_only (the
# strings-stripped variant, NOT this file's own comments-only
# _code_only — that one deliberately keeps strings for its ".exec()"
# spelling scan): the show/open story is told in comments and
# docstrings right next to the call.
from anki_stubs import code_only as _no_prose  # noqa: E402

_MM_SRC = open("klausmate/manage_models.py").read()
_MM_CODE2 = _no_prose(_MM_SRC)
check("the Preferences dialog is shown non-modal with dlg.show()",
      "dlg.show()" in _MM_CODE2 and "dlg.open()" not in _MM_CODE2)
check("no app-modal dlg.exec() remains in manage_models",
      "dlg.exec()" not in _MM_CODE2)
# Non-modal consequences, each load-bearing: a second star click must
# front the live window (not stack a second dialog over the same
# preview seam), and a profile switch must close it before the
# collection goes away.
check("a live Preferences window is a singleton (front, don't stack)",
      "_OPEN_DLG.raise_()" in _MM_CODE2
      and "_OPEN_DLG.activateWindow()" in _MM_CODE2
      and "_OPEN_DLG=dlg" in _MM_CODE2.replace(" ", ""))
check("profile_will_close closes the open dialog without its prompts "
      "(K-304; behaviour in tests/test_anki_ops.py) and the handler is "
      "removed again on finished",
      "profile_will_close.append(_on_profile_will_close)" in _MM_CODE2
      and "profile_will_close.remove(_on_profile_will_close)" in _MM_CODE2
      and "_close_for_profile(dlg, _preview_timer, op_state)" in _MM_CODE2)

section("K-308: no Library link on the toolbar")
check("the Library lives in Browse's sidebar; nothing adds a toolbar link",
      "top_toolbar_did_init_links" not in _code_only(_MODULES["pdf_drive"]))


section("K-114: app-modal exec() retired addon-wide (per-file bans)")
# manage_models was the first conversion (pinned above); K-114 finished
# the sweep. The board card's verify greps the raw sources for
# dlg.exec()/msg.exec(); these pins re-assert that on code_only text —
# so prose can neither satisfy nor trip them — and pin the SHAPE of
# each replacement. QMenu.exec(pos) is a popup, takes a different
# AppKit path, and never crashed: the bans are dialog-spelled on
# purpose and menus stay legal.
_K114 = {mod: _no_prose(src) for mod, src in _MODULES.items()}

# This file's own K-114 conversion was choose_deck_scope, the deck
# picker the curate button raised; K-146 deleted the button and the
# dialog with it, so the file (deck_curate.py until K-151 renamed it
# pdf_drop.py) now opens no Qt dialog at all — its one picker is a
# native QFileDialog sheet, deliberately legal here. The per-file ban
# STAYS as a standing ban: this is the file where a "quick" modal would
# land next, and the absence pin keeps the deleted dialog from being
# reintroduced under its old name.
check("pdf_drop: the file carries no dialog exec at all, and the "
      "K-146-deleted scope dialog has not crept back",
      "dlg.exec()" not in _K114["pdf_drop"]
      and "msg.exec()" not in _K114["pdf_drop"]
      and "choose_deck_scope" not in _MODULES["pdf_drop"]
      and "choose_deck_scope" not in _MODULES["pdf_drive"])

_K114_CROP = _no_prose(_func_src("__init__", "_launch_crop_dialog"))
check("__init__: the crop dialog opens window-modal — crop work rides "
      "accepted, the reentry guard rides finished (dialog lifetime)",
      "dlg.open()" in _K114_CROP
      and "dlg.accepted.connect(on_accepted)" in _K114_CROP
      and "dlg.finished.connect(on_finished)" in _K114_CROP
      and "dlg.exec()" not in _K114["__init__"]
      and "msg.exec()" not in _K114["__init__"])

check("setup_flow: all three welcome/readiness QMessageBoxes (K-226 cut "
      "the Ollama-era boxes; the welcome dialog, the K-125 "
      "library-root question and the missing-key nudge remain) open "
      "window-modal with finished callbacks reading clickedButton() "
      "(Esc/close keep their exec-era fall-through meaning); the file "
      "carries NO nested-loop .exec() at all. A fourth box must be "
      "added open()-shaped to keep these counts honest",
      _K114["setup_flow"].count("msg.open()") == 3
      and _K114["setup_flow"].count("msg.finished.connect(") == 3
      and ".exec()" not in _K114["setup_flow"])

check("pdfjs_viewer: note-edit and go-to-page are QInputDialog "
      "INSTANCES via open() + textValueSelected/intValueSelected — no "
      "app-modal static helpers, no .exec() anywhere in the module",
      "QInputDialog.get" not in _K114["pdfjs_viewer"]
      and ".exec()" not in _K114["pdfjs_viewer"]
      # THREE until K-150, which made Add Text an in-place .editLayer box
      # typed in the page: _bridge_text_add mints from a finished payload
      # and opens no dialog at all, so the third prompt is gone rather
      # than converted. Two is the honest number now — a dialog leaving
      # gets the same look as one arriving, and the count stays exact so
      # a FOURTH has to be audited here.
      and _K114["pdfjs_viewer"].count("dlg.open()") == 2
      and "textValueSelected.connect" in _K114["pdfjs_viewer"]
      and "intValueSelected.connect" in _K114["pdfjs_viewer"])

check("pdf_drive: no dialog exec either (converted under K-117, pinned "
      "in test_drive.py; K-114's board verify covers this file too)",
      "dlg.exec()" not in _K114["pdf_drive"]
      and "msg.exec()" not in _K114["pdf_drive"])


section("K-125: the statics/utilities that exec() internally are gone")
# K-100's audit found the K-114 crash class hiding inside statics and
# aqt helpers: QInputDialog.getText, QMessageBox.question, and
# aqt.utils.askUser all run an app-modal exec() under the hood. The
# pdf_drive sites are pinned in test_drive.py beside its K-117 block;
# here: curation's name-prompt flow and setup_flow's two ex-askUser
# questions. Bans on code_only text; file dialogs (native sheets, a
# different AppKit path) stay legal.
check("curation: no QInputDialog static, no askUser, no .exec() — the "
      "name prompt is an INSTANCE via open() + textValueSelected",
      "QInputDialog.get" not in _K114["curation"]
      and "askUser" not in _K114["curation"]
      and ".exec()" not in _K114["curation"]
      and "dlg.textValueSelected.connect(on_named)" in _K114["curation"]
      and "dlg.open()" in _K114["curation"])
check("curation: the old while-loop's edges survive as callbacks — "
      "empty name re-prompts, a declined merge re-prompts with the "
      "same name, the merge confirm reads clickedButton() on finished",
      _K114["curation"].count("ask_name(name)") == 2
      and "msg.finished.connect(_on_answered)" in _K114["curation"]
      and "msg.open()" in _K114["curation"])
check("setup_flow: askUser is gone entirely (identifier and import) — "
      "both questions are themed QMessageBoxes via open()",
      "askUser" not in _K114["setup_flow"])
check("setup_flow: the library-root offer threads a continuation so "
      "the readiness dialogs never stack on it — every early return "
      "and its answer reach then() (the ordering blocking gave for "
      "free); K-226 deleted the runtime-update offer this used to "
      "chain beside",
      "def _library_root_check(then" in _MODULES["setup_flow"]
      and "_library_root_check(after_library)"
      in _K114["setup_flow"]
      and _K114["setup_flow"].count("then()") >= 4)
check("setup_flow: the native folder sheet is deferred a tick past the "
      "finished handler, never nested inside it",
      "QTimer.singleShot(0, _pick_folder)" in _K114["setup_flow"])

# K-236: raw source, never code_only — every name this pin cares about
# lives in a string literal, and code_only strips those, so the whole
# check would pass against a file that lost the feature.
_V2_SWEEP_SRC = _func_src("setup_flow", "_offer_v2_index_sweep")
check("setup_flow: the key-is-present path carries the ONE-TIME v2 "
      "index-sweep offer — an upgrade to pdf_index v2 moves no "
      "embedding signature, so Preferences' Save can never ask, while "
      "every pre-v2 index reads as absent (blank Library, silent "
      "Lecture panel). Asked once per profile off the stale-manifest "
      "scan, and the flag is written whether the answer was yes or NO: "
      "a refused whole-collection re-embed is an answer, not a snooze",
      "_offer_v2_index_sweep(_pkg().get_config())"
      in _func_src("setup_flow", "_readiness_after_library_root")
      and '_v2_index_sweep_offered' in _V2_SWEEP_SRC
      and "index_queue.stale_index_names()" in _V2_SWEEP_SRC
      and "index_queue.offer_model_sweep(" in _V2_SWEEP_SRC
      and "write_config(cfg2)" in _V2_SWEEP_SRC)

# Klaus Plus / setup_flow readiness pins used to live here as source-only
# checks (an AST-extracted-source substring for _embedding_ready and a
# whole-file substring for KEYS_COPY) — both were vacuous, passing even
# with the Klaus Plus feature deleted (a comment could fake the first,
# and this task's own docstring wording could fake the second). Real,
# live coverage — importing setup_flow and calling _embedding_ready(),
# reading KEYS_COPY directly — now lives in test_setup_crop_theme.py,
# which already imports this module (fix1, K-246 review I4).


section("2026-09-05: the placement engine and the tear-off are gone — "
        "Qt docks the PDF panel")
# K-169's rule guarded a crash class: reparenting the live QPdfView
# between native windows inside event delivery left Qt delivering into
# freed widgets, and sip segfaulted converting the receiver before any
# Python ran (SIGSEGV in sipSubClass_QPdfView, reproduced live
# 2026-08-24). The rule is closed BY CONSTRUCTION now: the panel is a
# QDockWidget, so every reparent between the host and a floating window
# happens inside Qt's own docking code, and the addon's placement engine
# and drag state machine were deleted with it (spec:
# docs/superpowers/specs/2026-09-05-pdf-dock-design.md). These pins keep
# the vocabulary from creeping back.
_INIT_CODE = _no_prose(_MODULES["__init__"])
for _name in ("NOTES_PLACEMENTS", "_ZONE_CAPTIONS", "_defer_placement",
              "_embed(", "_tear_off", "startSystemMove", "_make_floating",
              "_PdfTabContainer", "_ensure_notes_split", "_wrap_pane",
              "_dock_into", "_load_browse_placement"):
    check(f"{_name} is gone from __init__.py's code", _name not in _INIT_CODE)


def _class_src(module: str, name: str) -> str:
    """Source of one class, by name. _func_src's AST walk only matches
    FunctionDef, so it returns "" for a class — which would make every
    pin below vacuously true."""
    src = _MODULES[module]
    for node in ast.walk(_TREES[module]):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


_DOCK = _no_prose(_class_src("__init__", "PdfDock"))
check("the dock class is in __init__.py and its source was found — "
      "without this every pin below passes vacuously",
      bool(_DOCK) and "class PdfDock" in _DOCK)
check("PdfDock never calls setParent — Qt owns every reparent, which is "
      "what closes K-169's crash class",
      "setParent(" not in _DOCK)
check("...and it never wraps a host pane in a splitter of its own",
      "QSplitter(" not in _DOCK and "insertWidget(" not in _DOCK)
check("PdfDock still releases the webview on host close (K-095: a "
      "webview destroyed without cleanup() crashes Anki's next theme "
      "change)",
      "self._sidebar.cleanup()"
      in _no_prose(_func_src("__init__", "_on_host_closing")))
check("the host's Close is still handled a TICK LATER, never inside the "
      "event — the host may ignore() it (AddCards' discard prompt)",
      "QTimer.singleShot(0, self._host_close_check)"
      in _no_prose(_func_src("__init__", "eventFilter")))
_BAR = _no_prose(_class_src("__init__", "_PanelBar"))
check("the title bar IGNORES the presses it does not handle, so the "
      "QDockWidget can move, dock and float from it (Qt's "
      "setTitleBarWidget contract) — an accept() here strands the panel",
      bool(_BAR) and _BAR.count("ev.ignore()") == 4
      and "ev.accept()" not in _BAR)


section("2026-09-05: real offscreen Qt — the dock in a Browse-shaped host")
# The dock's own behaviour is pinned in tests/test_pdf_dock.py. What
# belongs HERE is what the deleted engine used to put at risk: Anki's own
# Browse layout. The replica is read out of _aqt/forms/browser_qt6.pyc
# (bytecode-only, so via `strings` in creation order):
#     splitter[0] = widget > verticalLayout_2 > (gridLayout > searchEdit)
#                                             > tableView
#     splitter[1] = verticalLayoutWidget > verticalLayout
#                                        > horizontalLayout2 > fieldsArea
# The sidebar is a QDockWidget, NOT a splitter child — which is exactly
# why the PDF panel can now sit beside it.
import importlib  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC  # noqa: E402
    from PyQt6 import QtWidgets as _QtW  # noqa: E402
    _HAVE_QT = True
except Exception as _qt_e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — "
          "the source pins above still ran")

if _HAVE_QT:
    # A missing anchor must read as a FAILING PIN, never as a
    # traceback that skips report() and takes the tally with it.
    try:
        _app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])
        _UF = tempfile.mkdtemp(prefix="klaus_dock_uf_")
        os.makedirs(os.path.join(_UF, "contexts"), exist_ok=True)
        from anki_stubs import exec_klausmate_under_qt  # noqa: E402

        _pkg = exec_klausmate_under_qt(_UF)
        _browse_toggles = importlib.import_module("klausmate.browse_toggles")

        class _FakeSidebar(_QtW.QWidget):
            """PdfSidebar reduced to what the dock touches."""

            def __init__(self):
                super().__init__()
                self._name = None
                self._current_page = 0
                self._viewer = None
                self.on_loaded = None
                self.cleaned = 0
                _QtW.QVBoxLayout(self).addWidget(_QtW.QLabel("pdf"))

            def is_loaded(self, name):
                return False

            def load_pdf(self, name):
                self._name = name

            def clear(self):
                pass

            def cleanup(self):
                self.cleaned += 1

            def _set_active(self, name):
                pass

            def _on_page_changed(self, page):
                pass

        def _build_browse():
            win = _QtW.QMainWindow()
            central = _QtW.QWidget()
            win.setCentralWidget(central)
            _QtW.QVBoxLayout(central)
            split = _QtW.QSplitter(_QtC.Qt.Orientation.Horizontal)
            split.setChildrenCollapsible(False)
            central.layout().addWidget(split)

            table_col = _QtW.QWidget(split)
            table_col.setObjectName("widget")
            _QtW.QVBoxLayout(table_col)
            grid = _QtW.QGridLayout()
            search = _QtW.QLineEdit()
            grid.addWidget(search, 0, 1)
            # Anki's Cards/Notes Switch occupies cell (0,0) at runtime.
            grid.addWidget(_QtW.QToolButton(), 0, 0)
            table_col.layout().addLayout(grid)
            table = _QtW.QTableWidget(12, 2)
            table_col.layout().addWidget(table)

            ed_col = _QtW.QWidget(split)
            ed_col.setObjectName("verticalLayoutWidget")
            _QtW.QVBoxLayout(ed_col)
            fields = _QtW.QWidget(ed_col)
            _QtW.QVBoxLayout(fields)
            ed_col.layout().addWidget(fields)
            split.setSizes([700, 300])

            dock = _QtW.QDockWidget()
            dock.setObjectName("AnkiSidebar")
            dock.setTitleBarWidget(_QtW.QWidget())
            dock.setWidget(_QtW.QTreeWidget())
            win.addDockWidget(_QtC.Qt.DockWidgetArea.LeftDockWidgetArea, dock)
            win.sidebarDockWidget = dock

            win.form = types.SimpleNamespace(
                splitter=split, widget=table_col, gridLayout=grid,
                searchEdit=search, tableView=table,
                verticalLayoutWidget=ed_col, fieldsArea=fields)

            class _Ed:
                pass

            ed = _Ed()
            ed.parentWindow = win
            ed.widget = _QtW.QWidget()
            _QtW.QVBoxLayout(ed.widget)
            fields.layout().addWidget(ed.widget)
            win.editor = ed
            return win, ed

        _ph = importlib.import_module("klausmate.pdf_handler")
        _ph.save_panel_state(_UF, placement="left")
        _win, _ed = _build_browse()
        _win.resize(1280, 760)
        _win.show()
        _sb = _FakeSidebar()
        _saved_split = _win.form.splitter.saveState()
        _d = _pkg.PdfDock(_ed, _sb, _win)
        _ed._klausmate_pdf_tabs = _d
        _win._klausmate_pdf_container = _d
        _d.panel_show()
        _app.processEvents()

        check("the panel opens on the side Browse last left it on",
              _d.isVisible()
              and _win.dockWidgetArea(_d)
              == _QtC.Qt.DockWidgetArea.LeftDockWidgetArea,
              str(_win.dockWidgetArea(_d)))
        check("form.splitter still has exactly TWO children, unmoved — the "
              "dock is not in it, so Anki's own saved Browse layout keeps "
              "round-tripping (the deleted engine wrapped a splitter child)",
              _win.form.splitter.count() == 2
              and _win.form.splitter.saveState() == _saved_split)
        check("...and its state still restores into a two-child splitter",
              _QtW.QSplitter().restoreState(_win.form.splitter.saveState()))
        check("Anki's own sidebar dock still sits in the left area beside "
              "ours — D5's setDockNestingEnabled, not a tab stack",
              _win.isDockNestingEnabled()
              and _win.dockWidgetArea(_win.sidebarDockWidget)
              == _QtC.Qt.DockWidgetArea.LeftDockWidgetArea
              and _win.sidebarDockWidget.isVisible()
              and _win.sidebarDockWidget.width() > 20
              and _d.width() > 20,
              f"sidebar w={_win.sidebarDockWidget.width()} pdf w={_d.width()}")

        # The status bar's editor-column toggle, with the PDF docked.
        _btn = importlib.import_module("klausmate.status_bar").StatusBar(_win, browser=_win).editor_btn
        check("the status bar still finds the editor column with the panel "
              "docked (it walks up from fieldsArea, and the dock never "
              "touches that column)",
              _btn is not None)
        if _btn is not None:
            _btn.click()
            _app.processEvents()
            check("hiding the editor column leaves the note table and the "
                  "PDF dock alive",
                  not _win.form.verticalLayoutWidget.isVisible()
                  and _win.form.widget.width() > 40 and _d.width() > 40,
                  f"notes w={_win.form.widget.width()} pdf w={_d.width()}")
            _btn.click()
            _app.processEvents()
            check("...and showing it again brings it back",
                  _win.form.verticalLayoutWidget.isVisible())

        _before = _sb.cleaned
        _d._on_host_closing()
        check("K-095: teardown still runs sidebar.cleanup()",
              _sb.cleaned == _before + 1)
    except Exception as _edock:  # noqa: BLE001
        check(f"offscreen Browse dock checks ran ({_edock!r})", False)

raise SystemExit(report())
