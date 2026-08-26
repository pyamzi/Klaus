"""The webchannel-reentrancy rule, enforced across the whole addon.

THE RULE: never open a modal dialog (or any nested event loop — a
QMenu.exec counts) synchronously from a handler that Anki dispatches
over QWebChannel. Defer it with QTimer.singleShot(0, ...) so the bridge
call unwinds back to a clean top-level event-loop iteration first.

Why it is a rule and not a preference: breaking it segfaults Anki.
Twice now, live, same signature — EXC_BAD_ACCESS in
QPaintDevice::devicePixelRatio inside QBackingStore::flush, with
QMetaObjectPublisher::invokeMethod -> a Python slot -> QDialog::exec()
on the stack. A modal spins a nested loop inside the re-entrant
Chromium/Qt dispatch, and a paint posted for some widget lands against
a backing store that is not in a valid state.

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

check("exactly the three known js-message handlers are registered — a "
      "NEW one must be audited against the deferral rule and added here",
      _registered == {
          "__init__.on_js_message",
          "top_bar._on_js_message",
          "deck_curate.on_deck_js_message",
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

raise SystemExit(report())
