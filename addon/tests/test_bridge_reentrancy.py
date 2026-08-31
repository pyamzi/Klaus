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
   app-modal exec site (deck_curate's scope dialog, __init__'s crop
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

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

_MODULES = {
    "__init__": open("klausmate/__init__.py").read(),
    "top_bar": open("klausmate/top_bar.py").read(),
    "deck_curate": open("klausmate/deck_curate.py").read(),
    "pdfjs_viewer": open("klausmate/pdfjs_viewer.py").read(),
    "pdf_drive": open("klausmate/pdf_drive.py").read(),
    "heatmap": open("klausmate/heatmap.py").read(),
    "dashboard": open("klausmate/dashboard.py").read(),
    "setup_flow": open("klausmate/setup_flow.py").read(),
    "curation": open("klausmate/curation.py").read(),
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

check("exactly the five known js-message handlers are registered — a "
      "NEW one must be audited against the deferral rule and added here",
      _registered == {
          "__init__.on_js_message",
          "top_bar._on_js_message",
          "deck_curate.on_deck_js_message",
          "heatmap._on_js_message",
          "dashboard._on_js_message",
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

section("deck_curate: Curate Deck on the deck surfaces")
_CURATE = _func_src("deck_curate", "_on_curate_clicked")
_BROWSE = _func_src("deck_curate", "_on_browse_clicked")
check("both curate branches defer — _curate_with reaches "
      "choose_deck_scope's dlg.exec(), _pick_pdf_menu ends in menu.exec()",
      _CURATE.count("QTimer.singleShot(0") == 2
      and "_curate_with(_armed_pdf)\n" not in _CURATE
      and "        _pick_pdf_menu()" not in _CURATE)
check("the armed PDF is frozen into the deferred callback, not re-read "
      "a tick later",
      "lambda safe=_armed_pdf" in _CURATE)
check("the file-picker path still defers (it already did)",
      "QTimer.singleShot(0, _browse_for_pdfs)" in _BROWSE)

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
check("profile_will_close rejects the open dialog (and the handler is "
      "removed again on finished)",
      "profile_will_close.append(_on_profile_will_close)" in _MM_CODE2
      and "profile_will_close.remove(_on_profile_will_close)" in _MM_CODE2
      and "dlg.reject()" in _MM_CODE2)

section("pdf_drive: the toolbar Library link (third dispatch shape)")
# open_drive is the Library link's callback — toolbar links are
# dispatched over the same webchannel. Its error branch used to call
# showWarning synchronously (recorded as a known landmine in the
# session handoff); now it defers, with the message frozen into the
# lambda because the except-variable is unbound by fire time.
_DRIVE = _code_only(_func_src("pdf_drive", "open_drive"))
check("open_drive's error branch defers its showWarning, message "
      "frozen into the lambda's default",
      "QTimer.singleShot" in _DRIVE
      and 'lambda msg=f"Could not open the PDF drive' in _DRIVE
      and "showWarning(msg)" in _DRIVE)
check("the deferred call is the ONLY modal left in open_drive's body",
      _DRIVE.count("showWarning(") == 1
      and not [tok for tok in _MODAL
               if tok != "showWarning(" and tok in _DRIVE])


section("K-114: app-modal exec() retired addon-wide (per-file bans)")
# manage_models was the first conversion (pinned above); K-114 finished
# the sweep. The board card's verify greps the raw sources for
# dlg.exec()/msg.exec(); these pins re-assert that on code_only text —
# so prose can neither satisfy nor trip them — and pin the SHAPE of
# each replacement. QMenu.exec(pos) is a popup, takes a different
# AppKit path, and never crashed: the bans are dialog-spelled on
# purpose and menus stay legal.
_K114 = {mod: _no_prose(src) for mod, src in _MODULES.items()}

check("deck_curate: choose_deck_scope opens window-modal; the result "
      "rides an accepted callback (CPS — cancel never calls on_done)",
      "dlg.open()" in _no_prose(_func_src("deck_curate",
                                          "choose_deck_scope"))
      and "def choose_deck_scope(parent, on_done)"
      in _MODULES["deck_curate"]
      and "dlg.exec()" not in _K114["deck_curate"]
      and "msg.exec()" not in _K114["deck_curate"])
check("both scope-dialog callers ride the callback — _curate_with here "
      "and pdf_drive._curate (the old tuple return is gone)",
      "choose_deck_scope(mw, lambda deck: run_curation_flow(safe, deck))"
      in _MODULES["deck_curate"]
      and "deck_curate.choose_deck_scope(" in _MODULES["pdf_drive"]
      and "accepted, deck = " not in _MODULES["pdf_drive"])

_K114_CROP = _no_prose(_func_src("__init__", "_launch_crop_dialog"))
check("__init__: the crop dialog opens window-modal — crop work rides "
      "accepted, the reentry guard rides finished (dialog lifetime)",
      "dlg.open()" in _K114_CROP
      and "dlg.accepted.connect(on_accepted)" in _K114_CROP
      and "dlg.finished.connect(on_finished)" in _K114_CROP
      and "dlg.exec()" not in _K114["__init__"]
      and "msg.exec()" not in _K114["__init__"])

check("setup_flow: all seven welcome/readiness QMessageBoxes (K-114's "
      "five + K-125's two ex-askUser questions) open window-modal with "
      "finished callbacks reading clickedButton() (Esc/close keep "
      "their exec-era fall-through meaning); the file carries NO "
      "nested-loop .exec() at all. An eighth box must be added "
      "open()-shaped to keep these counts honest",
      _K114["setup_flow"].count("msg.open()") == 7
      and _K114["setup_flow"].count("msg.finished.connect(") == 7
      and ".exec()" not in _K114["setup_flow"])

check("pdfjs_viewer: note-edit and go-to-page are QInputDialog "
      "INSTANCES via open() + textValueSelected/intValueSelected — no "
      "app-modal static helpers, no .exec() anywhere in the module",
      "QInputDialog.get" not in _K114["pdfjs_viewer"]
      and ".exec()" not in _K114["pdfjs_viewer"]
      and _K114["pdfjs_viewer"].count("dlg.open()") == 3
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
check("setup_flow: the two converted offers thread a continuation so "
      "the readiness dialogs never stack on them — every early return "
      "and both answers reach then() (the ordering blocking gave for "
      "free)",
      "def _library_root_check(then" in _MODULES["setup_flow"]
      and "def _maybe_offer_runtime_update(res: Any, then"
      in _MODULES["setup_flow"]
      and "_library_root_check(_readiness_after_library_root)"
      in _K114["setup_flow"]
      and "_maybe_offer_runtime_update(res, _readiness_check_body)"
      in _K114["setup_flow"]
      and _K114["setup_flow"].count("then()") >= 8)
check("setup_flow: the native folder sheet is deferred a tick past the "
      "finished handler, never nested inside it",
      "QTimer.singleShot(0, _pick_folder)" in _K114["setup_flow"])

raise SystemExit(report())
