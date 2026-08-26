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
split: per-site pins for the entry points that exist today, plus a
roster pin that FAILS when a new js-message handler is registered — a
new handler is exactly how this bug reached a user twice, so adding one
should force a human to confirm it defers.
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
}


def _func_src(module: str, name: str) -> str:
    """Source of one top-level or nested function, by name (AST, so a
    later same-named string in the file can't fake a pass)."""
    src = _MODULES[module]
    for node in ast.walk(ast.parse(src)):
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
for mod, src in _MODULES.items():
    for node in ast.walk(ast.parse(src)):
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
    """Source with comments removed — these handlers now *describe* the
    modals they defer, so a prose scan flags its own documentation."""
    try:
        flat = textwrap.dedent(src)
        out = []
        for tok in tokenize.generate_tokens(io.StringIO(flat).readline):
            if tok.type != tokenize.COMMENT:
                out.append(tok.string)
        return " ".join(out)
    except Exception:
        return "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())


section("no bridge handler opens a nested loop in its own body")
# Transitive calls can't be caught from source alone (the top_bar crash
# was one: the handler body held no modal token at all, just a call to
# something that did). This catches the blatant case only, and says so.
_MODAL = (".exec()", "QInputDialog.get", "QFileDialog.get",
          "QColorDialog.get", "QMessageBox(")
for qualified in sorted(_registered):
    mod, name = qualified.split(".", 1)
    body = _code_only(_func_src(mod, name))
    direct = [tok for tok in _MODAL if tok in body]
    check(f"{qualified} opens no modal directly in its own body",
          not direct, str(direct))

raise SystemExit(report())
