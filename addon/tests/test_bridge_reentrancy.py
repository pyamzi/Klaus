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


section("K-169: the note-table anchor obeys the deferral rule")
# The panel gained a SECOND anchor: notes-left/notes-right wrap Browse's
# note-table column instead of the editor pane, because in Browse the
# editor pane IS the right-hand column and can never reach the note list.
#
# It belongs in this file because docking is the OTHER half of the same
# crash class. _defer_placement's docstring names it: reparenting the
# live QPdfView between native windows inside event delivery leaves Qt
# delivering into freed widgets, and sip segfaults converting the
# receiver before any Python runs — SIGSEGV in sipSubClass_QPdfView,
# reproduced live 2026-08-24. A new drop zone is exactly the shape of
# change that tempts a direct self._embed(...) from inside eventFilter.
# _no_prose (comments AND strings out): every pin below matches
# code-shaped text, so a docstring naming form.widget or a caption
# spelling a placement can never satisfy one. The vocabulary itself
# comes from the AST above, not from a grep.
_INIT_CODE = _no_prose(_MODULES["__init__"])

# The vocabulary, read out of the AST rather than grepped, so a pin can
# never be satisfied by prose naming a placement.
_NOTES_PLACEMENTS: tuple = ()
_ZONE_KEYS: set = set()
for _node in ast.walk(_TREES["__init__"]):
    if isinstance(_node, ast.Assign):
        for _t in _node.targets:
            name = getattr(_t, "id", None) or getattr(_t, "attr", None)
            if name == "NOTES_PLACEMENTS":
                _NOTES_PLACEMENTS = tuple(ast.literal_eval(_node.value))
            elif name == "_ZONE_CAPTIONS":
                _ZONE_KEYS = set(ast.literal_eval(_node.value))

check("the notes placements exist and are named as their own family "
      "(a bare 'left'/'right' would collide with the editor anchor's)",
      _NOTES_PLACEMENTS == ("notes-left", "notes-right"),
      str(_NOTES_PLACEMENTS))
check("every notes placement is a previewable drop zone — a mode with "
      "no caption can be dropped into but never shown",
      set(_NOTES_PLACEMENTS) <= _ZONE_KEYS,
      str(sorted(_ZONE_KEYS)))
_EMBED = _no_prose(_func_src("__init__", "_embed"))
check("...and the captions are exactly the two anchors' modes, with "
      "_embed dispatching on the notes family — a caption with no "
      "branch would preview a dock that never happens",
      _ZONE_KEYS == {"above", "below", "left", "right"} | set(_NOTES_PLACEMENTS)
      and "NOTES_PLACEMENTS" in _EMBED
      and "_ensure_notes_split" in _EMBED,
      str(sorted(_ZONE_KEYS)))

# THE RULE. Both drop paths — the ghost-drop branch inside eventFilter
# and _finalize_drag — must reach _embed only through _defer_placement.
for _fn in ("eventFilter", "_finalize_drag"):
    _body = _no_prose(_func_src("__init__", _fn))
    check(f"{_fn} docks only through _defer_placement — no direct "
          "self._embed() inside event delivery, whichever zone won",
          "self._defer_placement(self._embed, zone)" in _body
          and "self._embed(" not in _body.replace(
              "self._defer_placement(self._embed, zone)", ""))
check("_defer_placement is still the singleShot(0) hand-back, not a "
      "direct call wearing the name",
      "QTimer.singleShot(0, run)"
      in _no_prose(_func_src("__init__", "_defer_placement")))

# ONE ENGINE, TWO ANCHORS. The insert-and-size tail and the wrap are
# each written once; a third anchor is a third _ensure_* in front of the
# same two helpers, never a third copy of this code.
check("_dock_into is the ONLY place the panel is inserted into an "
      "anchor — the second anchor did not fork the engine",
      _INIT_CODE.count("insertWidget(0 if first else") == 1
      and "def _dock_into(" in _INIT_CODE)
check("both anchors run it: the notes branch and the editor branch each "
      "end in self._dock_into(...)",
      _EMBED.count("self._dock_into(") == 2)
check("_wrap_pane is the ONLY place a pane is reparented into a new "
      "splitter, and both _ensure_* callers go through it",
      _INIT_CODE.count("split.addWidget(pane)") == 2  # splitter + layout arm
      and _no_prose(
          _func_src("__init__", "_ensure_vsplit")).count("_wrap_pane(") == 1
      and _no_prose(
          _func_src("__init__", "_ensure_notes_split")
      ).count("_wrap_pane(") == 1)

# QSplitter.setOrientation TRANSPOSES the size policy (the AddCards
# blank-space bug). The re-assert has to come AFTER it or it is inert.
_DOCK = _no_prose(_func_src("__init__", "_dock_into"))
check("_dock_into re-asserts the wrapped pane's size policy AFTER "
      "setOrientation, which transposes it",
      "setOrientation(" in _DOCK
      and "split.setSizePolicy(pane.sizePolicy())" in _DOCK
      and _DOCK.index("setOrientation(")
      < _DOCK.index("split.setSizePolicy(pane.sizePolicy())"))

# The anchor is DISCOVERED, not named: Anki mutates this layout after
# setupUi and the generated form is not the runtime truth.
_PANE = _no_prose(_func_src("__init__", "_browse_note_pane"))
check("the note column is walked up from form.tableView (browse_toggles' "
      "method), never taken from the generated form.widget attribute",
      "form.tableView" in _PANE
      and "parentWidget()" in _PANE
      and "form.widget" not in _PANE)

# Anki persists form.splitter with saveState()/restoreState(); restore
# applies the saved sizes POSITIONALLY. Docking into it directly would
# write a three-size state that hands the editor column the PDF's width
# in any later session where the panel is never opened.
check("the panel WRAPS Browse's splitter child rather than becoming a "
      "third child of form.splitter, so Anki's own saved Browse layout "
      "keeps round-tripping",
      "form.splitter.insertWidget" not in _INIT_CODE
      and "form.splitter.addWidget" not in _INIT_CODE
      and "splitter.insertWidget" not in _no_prose(
          _func_src("__init__", "_ensure_notes_split")))

section("K-169: a Browse-only position must not reach Add Cards")
# pdf_tabs.json is shared by every host window. There is exactly ONE
# stored "placement" and both windows read it, so a notes-* value there
# would follow the user into Add Cards, which has no note table.
_PERSIST = _no_prose(_func_src("__init__", "_persist_state"))
check("_persist_state keeps notes placements OUT of the shared key",
      "notes = self._placement in NOTES_PLACEMENTS" in _PERSIST
      and "placement=None if notes else self._placement" in _PERSIST)
check("...and writes Browse's own key on EVERY Browse placement change, "
      "None included, so moving back to the editor pane clears it",
      "_save_browse_placement(self._placement if notes else None)"
      in _PERSIST
      and "self._browse_form() is not None" in _PERSIST)

_PH_SRC = open("klausmate/pdf_handler.py").read()
_PH_WHITELIST: tuple = ()
for _node in ast.walk(ast.parse(_PH_SRC)):
    if (isinstance(_node, ast.Compare)
            and isinstance(_node.ops[0], ast.In)
            and getattr(_node.left, "id", "") == "placement"):
        _PH_WHITELIST = tuple(ast.literal_eval(_node.comparators[0]))
check("pdf_handler.load_panel_state's whitelist is disjoint from the "
      "notes placements — the shared key could not carry one home even "
      "if something wrote it (widen that whitelist and this pin fires, "
      "which is the audit)",
      bool(_PH_WHITELIST)
      and not (set(_PH_WHITELIST) & set(_NOTES_PLACEMENTS)),
      str(_PH_WHITELIST))

_SAVE_BP = _no_prose(_func_src("__init__", "_save_browse_placement"))
_LOAD_BP = _no_prose(_func_src("__init__", "_load_browse_placement"))
check("Browse's key is written through pdf_handler._save_tabs_file — "
      "the MERGE every writer of pdf_tabs.json uses (CLAUDE.md); a "
      "private open()/json.dump would drop the other keys",
      "pdf_handler._save_tabs_file(USER_FILES" in _SAVE_BP
      and "open(" not in _SAVE_BP
      and "json.dump" not in _SAVE_BP
      and "pdf_handler._load_tabs_file(USER_FILES" in _LOAD_BP)
check("a stale or hand-edited value can only cost the preference: "
      "_load_browse_placement returns None for anything not live",
      "val if val in NOTES_PLACEMENTS else None" in _LOAD_BP)
_CTOR = _no_prose(_func_src("__init__", "__init__"))
check("the restore is guarded on the host actually having a note table, "
      "so an Add Cards panel can never adopt a Browse-only placement",
      "if self._browse_form() is not None:" in _CTOR
      and "_load_browse_placement()" in _CTOR)


section("K-169: real offscreen Qt — the anchor as it lands in Browse")
# Source pins cannot see geometry, and geometry in this area is exactly
# where this repo's offscreen renders have caught bugs review missed.
# PyQt6 IS importable under this python (unlike Anki's bundled one), so
# the placement engine runs on genuine widgets against a replica of
# Anki's real Browse tree — read out of _aqt/forms/browser_qt6.pyc
# (bytecode-only, so via `strings` in creation order):
#     splitter[0] = widget > verticalLayout_2 > (gridLayout > searchEdit)
#                                             > tableView
#     splitter[1] = verticalLayoutWidget > verticalLayout
#                                        > horizontalLayout2 > fieldsArea
# The sidebar is a QDockWidget, NOT a splitter child.
import importlib  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC  # noqa: E402
    from PyQt6 import QtGui as _QtG  # noqa: E402
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
        for _name in [m for m in list(sys.modules) if m.startswith("klausmate.")]:
            del sys.modules[_name]

        _ADDON = os.path.abspath("klausmate")
        _spec = importlib.util.spec_from_file_location(
            "klausmate", os.path.join(_ADDON, "__init__.py"),
            submodule_search_locations=[_ADDON])
        _pkg = importlib.util.module_from_spec(_spec)
        sys.modules["klausmate"] = _pkg
        _app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])
        _spec.loader.exec_module(_pkg)
        _UF = tempfile.mkdtemp(prefix="klaus_k169_uf_")
        os.makedirs(os.path.join(_UF, "contexts"), exist_ok=True)
        _pkg.USER_FILES = _UF
        _browse_toggles = importlib.import_module("klausmate.browse_toggles")
        _ph = importlib.import_module("klausmate.pdf_handler")

        class _FakeSidebar(_QtW.QWidget):
            """PdfSidebar reduced to what the container touches."""

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

        def _panel(win, ed):
            c = _pkg._PdfTabContainer(ed, _FakeSidebar(), win)
            ed._klausmate_pdf_tabs = c
            win._klausmate_pdf_container = c
            c.hide()
            return c

        def _gx(w):
            return w.mapToGlobal(_QtC.QPoint(0, 0)).x()

        _win, _ed = _build_browse()
        _win.resize(1280, 760)
        _win.show()
        _c = _panel(_win, _ed)
        _app.processEvents()

        _pane = _c._browse_note_pane()
        check("the note column is found in a real Browse tree",
              _pane is not None and _pane is _win.form.widget)

        _c._embed("notes-right")
        _app.processEvents()
        _wrap = getattr(_win, "_klausmate_notes_split", None)
        check("form.splitter still has exactly TWO children — Anki's saved "
              "Browse layout keeps the same shape",
              _win.form.splitter.count() == 2)
        check("...and its state still restores into a two-child splitter",
              _QtW.QSplitter().restoreState(_win.form.splitter.saveState()))
        check("the panel is a sibling of the note column inside the wrapper",
              _wrap is not None and _wrap.count() == 2
              and _wrap.indexOf(_pane) >= 0 and _wrap.indexOf(_c) >= 0)
        check("notes-right puts the PDF to the RIGHT of the note table, and "
              "both keep real width",
              _gx(_c) > _gx(_pane) and _pane.width() > 40 and _c.width() > 40,
              f"pane x={_gx(_pane)} w={_pane.width()} "
              f"pdf x={_gx(_c)} w={_c.width()}")

        _win.resize(900, 620)
        _app.processEvents()
        check("a narrow window collapses neither pane",
              _pane.width() > 40 and _c.width() > 40 and _pane.isVisible()
              and _c.isVisible(),
              f"pane w={_pane.width()} pdf w={_c.width()}")

        _win.resize(1280, 760)
        _c._embed("notes-left")
        _app.processEvents()
        check("notes-left mirrors it",
              _gx(_c) < _gx(_pane) and _pane.width() > 40 and _c.width() > 40)

        # browse_toggles' own editor-column button, with the PDF docked.
        _browse_toggles._install_browser_sidebar_toggle(_win)
        _btn = getattr(_win, "_klausmate_editor_toggle_btn", None)
        check("browse_toggles still finds the editor column with the panel "
              "docked beside the notes (it walks up from fieldsArea, and "
              "this anchor never touches that column)",
              _btn is not None)
        if _btn is not None:
            _c._embed("notes-right")
            _app.processEvents()
            _btn.click()
            _app.processEvents()
            check("hiding the editor column gives its width to the notes + "
                  "PDF, and neither collapses",
                  not _win.form.verticalLayoutWidget.isVisible()
                  and _pane.width() > 40 and _c.width() > 40,
                  f"pane w={_pane.width()} pdf w={_c.width()}")
            _btn.click()
            _app.processEvents()
            check("...and showing it again brings it back",
                  _win.form.verticalLayoutWidget.isVisible())

        # Drop zones over the note column: 40% bands, neutral middle.
        _c._embed("notes-right")
        _app.processEvents()
        _r = _QtC.QRect(_pane.mapToGlobal(_QtC.QPoint(0, 0)), _pane.size())
        _zones = []
        for _frac in (0.10, 0.50, 0.90):
            _c._active_zone = None
            _c._update_zone(_QtC.QPoint(int(_r.left() + _r.width() * _frac),
                                        _r.top() + _r.height() // 2))
            _zones.append(_c._active_zone)
        check("the note column carries the same band grammar as the editor "
              "pane: 40% left, neutral middle, 40% right",
              _zones == ["notes-left", None, "notes-right"], str(_zones))
        _c._hide_zone()

        # The float path is untouched.
        _c._make_floating(None)
        _app.processEvents()
        check("the float path still works, and leaves the note column alone "
              "in the wrapper",
              _c.isWindow() and _c._placement == "float"
              and _wrap.count() == 1 and _wrap.indexOf(_pane) == 0)

        _c._embed("above")
        _app.processEvents()
        check("the editor anchor still works after the notes anchor existed",
              getattr(_ed, "_klausmate_vsplit", None) is not None
              and _c._placement == "above" and not _c.isWindow())

        # Cross-window persistence.
        class _AddEd:
            pass

        def _build_add():
            """An Add Cards-shaped host: an editor pane in a plain
            layout, no form, no note table."""
            win = _QtW.QWidget()
            _QtW.QVBoxLayout(win)
            pane = _QtW.QWidget()
            _QtW.QVBoxLayout(pane)
            win.layout().addWidget(pane)
            win.resize(700, 500)
            win.show()
            ed = _AddEd()
            ed.parentWindow = win
            ed.widget = pane
            return win, ed

        _ph.save_panel_state(_UF, placement="above")
        _c._embed("notes-right")
        _app.processEvents()
        check("a Browse notes placement leaves the SHARED key untouched",
              _ph.load_panel_state(_UF).get("placement") == "above"
              and _pkg._load_browse_placement() == "notes-right")

        _add, _ae = _build_add()
        _ac = _pkg._PdfTabContainer(_ae, _FakeSidebar(), _add)
        check("an Add Cards panel has no notes anchor and never restores a "
              "notes placement",
              _ac._browse_form() is None
              and _ac._ensure_notes_split() is None
              and _ac._placement not in _pkg.NOTES_PLACEMENTS,
              f"placement={_ac._placement!r}")
        _ac._embed("notes-right")
        _app.processEvents()
        check("...and asked for one anyway it falls back to the editor "
              "anchor on the same side, never to a stranded float",
              _ac._placement == "right" and not _ac.isWindow()
              and getattr(_ae, "_klausmate_vsplit", None) is not None,
              f"placement={_ac._placement!r} isWindow={_ac.isWindow()}")

        # ---- THE READ SIDE ------------------------------------------
        # Everything above exercises the WRITE side or a NEGATIVE case.
        # Nothing yet asserted that a panel comes UP wearing what was
        # stored — so `if False:` on the restore itself passed this whole
        # gate green (caught at K-169 integration, not here). That is the
        # feature's headline behaviour and the first thing a user
        # notices: without it Browse forgets the PDF's side on every
        # reopen. Restores are pinned POSITIVELY from here down.
        check("there is a stored notes placement to restore FROM — "
              "without this the two pins below could pass vacuously",
              _pkg._load_browse_placement() == "notes-right")
        _win2, _ed2 = _build_browse()
        _win2.resize(1280, 760)
        _win2.show()
        _c2 = _panel(_win2, _ed2)
        check("a REOPENED Browse panel restores the stored notes "
              "placement — the PDF is still beside the notes",
              _c2._placement == "notes-right",
              f"placement={_c2._placement!r}")
        _c2.panel_show()
        _app.processEvents()
        _pane2 = _c2._browse_note_pane()
        check("...and panel_show() puts it there with no second drag",
              getattr(_win2, "_klausmate_notes_split", None) is not None
              and not _c2.isWindow() and _pane2 is not None
              and _gx(_c2) > _gx(_pane2),
              f"placement={_c2._placement!r}")

        # The SHARED key's restore had no positive pin either — not in
        # this file and nowhere in the suite: disabling
        # `state.get("placement", "above")` left all 32 test files green.
        # That gap PREDATES K-169; the panel's placement has simply never
        # been checked to survive a restart. One pin, here, for both keys
        # at once — the stored notes value stays set throughout, so this
        # also proves the two keys never cross.
        _ph.save_panel_state(_UF, placement="below")
        _add2, _ae2 = _build_add()
        _ac2 = _pkg._PdfTabContainer(_ae2, _FakeSidebar(), _add2)
        check("the SHARED placement key is restored too, in a window with "
              "no note table (this gap predates K-169)",
              _ac2._placement == "below", f"placement={_ac2._placement!r}")
        check("...and that window still ignores the notes value sitting "
              "beside it — the two keys never cross",
              _pkg._load_browse_placement() == "notes-right"
              and _ac2._placement not in _pkg.NOTES_PLACEMENTS)
        _win3, _ed3 = _build_browse()
        _win3.show()
        _c3 = _panel(_win3, _ed3)
        check("with BOTH keys set, Browse prefers its own",
              _c3._placement == "notes-right",
              f"placement={_c3._placement!r}")

        _c._embed("above")
        _app.processEvents()
        check("moving back to the editor pane in Browse CLEARS the notes "
              "memory — the next Browse open must not overrule the move",
              _pkg._load_browse_placement() is None)
        _ph.save_panel_state(_UF, placement="below")
        _win4, _ed4 = _build_browse()
        _win4.show()
        _c4 = _panel(_win4, _ed4)
        check("...and with its own key cleared, Browse falls back to the "
              "shared one rather than to the 'above' default",
              _c4._placement == "below", f"placement={_c4._placement!r}")

        _before = _c._sidebar.cleaned
        _c._on_host_closing()
        check("K-095: teardown still runs sidebar.cleanup()",
              _c._sidebar.cleaned == _before + 1)
    except Exception as _e169:  # noqa: BLE001
        check(f"K-169 offscreen Browse checks ran ({_e169!r})", False)

raise SystemExit(report())
