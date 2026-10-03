"""Headless tests for K-112: theming the last two unthemed Klaus dialogs —
setup_flow.py's first-run/readiness QMessageBoxes and crop_dialog.py's
ImageCropDialog.

Pins the acceptance criteria from board/board.py show K-112:
  1. every QDialog these modules build applies theme.dialog_qss(...)
  2. secondary/cancel buttons carry the SecondaryButton objectName
  3. no literal hardcoded hex colour outside comments
  4. window titles use "Klaus Note" casing where the addon name appears in
     a title, while short "Klaus" prose (e.g. "Welcome to Klaus") is left
     alone
"""
import importlib
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

import klaus_note.settings as _settings  # noqa: E402

# Importing under the headless stubs also proves neither module raises at
# import time (syntax errors, bad relative imports, etc.) after the edit.
setup_flow = importlib.import_module("klaus_note.setup_flow")
crop_dialog = importlib.import_module("klaus_note.crop_dialog")

_SETUP_SRC = open("klaus_note/setup_flow.py").read()
_CROP_SRC = open("klaus_note/crop_dialog.py").read()

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def _hex_hits_outside_comments(src: str) -> list:
    """Literal 6-digit hex colours in CODE, comments excluded.

    Tokenised, not split on "#": the previous version cut each line at
    its first "#" to drop comments — and a hex colour literal IS a "#"
    inside a string, so it deleted the very thing it was hunting. It
    returned [] for `BLUE = "#AABBCC"`, which made both checks below
    vacuous from the day they were written (found while building
    K-132, fixed as K-135). Python's own tokeniser knows which "#"
    opens a comment and which sits inside a string; nothing else does.
    """
    import io as _io
    import tokenize as _tokenize

    hits = []
    try:
        tokens = _tokenize.generate_tokens(_io.StringIO(src).readline)
        for tok in tokens:
            if tok.type == _tokenize.COMMENT:
                continue
            if _HEX_RE.search(tok.string):
                hits.append((tok.start[0], tok.line.rstrip()))
    except (_tokenize.TokenError, IndentationError, SyntaxError):
        # A file we cannot tokenise is a finding, not a pass.
        return [(0, "could not tokenise %d bytes" % len(src))]
    return hits


section("the hex pin can actually fail (K-135)")
# A pin that cannot fail is worse than no pin: it reads as coverage.
# This one could not — it stripped each line at its first "#" to drop
# comments, which is the same "#" that opens a hex literal, so it
# returned [] for BLUE = "#AABBCC" and both checks below passed
# unconditionally. Guard the guard: the helper must SEE a literal it is
# supposed to catch, and still ignore one inside a comment.
check("the helper finds a hex literal in code",
      len(_hex_hits_outside_comments('BLUE = "#AABBCC"\n')) == 1)
check("...and still ignores one inside a comment, trailing or whole-line",
      _hex_hits_outside_comments("x = 1  # not #AABBCC\n") == []
      and _hex_hits_outside_comments("# leading #AABBCC\n") == [])
check("a file it cannot tokenise reports a finding, never a pass",
      len(_hex_hits_outside_comments("def broken(:\n")) == 1)

section("setup_flow.py: dialogs are themed")
check("references theme.dialog_qss", "dialog_qss" in _SETUP_SRC)
check("references theme.night_mode", "night_mode" in _SETUP_SRC)
check("guarded with try/except + print('[klaus_note] ...') fallback pattern",
      "except Exception as exc:" in _SETUP_SRC
      and 'print(f"[klaus_note] setup dialog theme failed' in _SETUP_SRC)
check("a shared themed-message-box helper backs every QMessageBox",
      "_themed_message_box" in _SETUP_SRC)
check("no bare, unstyled QMessageBox(mw) construction left behind",
      "QMessageBox(mw)" not in _SETUP_SRC)

section("setup_flow.py: button roles")
check("SecondaryButton objectName appears (Skip/Later/secondary actions)",
      "SecondaryButton" in _SETUP_SRC)
check("no DangerButton needed here (no destructive action in this module)",
      True)
# Every "Skip"/"Later" dismissal button is chained straight into
# .setObjectName("SecondaryButton") rather than left default-styled.
skip_or_later = re.findall(r'msg\.addButton\(\s*"(?:Skip|Later)"', _SETUP_SRC)
secondary_chained = re.findall(
    r'msg\.addButton\(\s*"(?:Skip|Later)"[^)]*\)\s*\.setObjectName\("SecondaryButton"\)',
    _SETUP_SRC,
    re.S,
)
check("every Skip/Later button found is styled SecondaryButton",
      len(skip_or_later) > 0 and len(skip_or_later) == len(secondary_chained),
      f"found {len(skip_or_later)} Skip/Later buttons, "
      f"{len(secondary_chained)} styled SecondaryButton")

section("setup_flow.py: no hardcoded hex outside comments")
hits = _hex_hits_outside_comments(_SETUP_SRC)
check("zero literal hex colours in code (comments are exempt)",
      len(hits) == 0, str(hits))

section("setup_flow.py: window title casing")
check('"Welcome to Klaus" prose title is left untouched (explicitly exempt)',
      '"Welcome to Klaus"' in _SETUP_SRC)
check("addon-name window titles use Klaus Note casing",
      "Klaus Note: local models" in _SETUP_SRC)
check("bare 'Klaus:' titles were not left behind",
      "Klaus: Ollama isn't running" not in _SETUP_SRC
      and "Klaus: local embedding model isn't set up yet" not in _SETUP_SRC
      and "Klaus: embedding model needed" not in _SETUP_SRC
      and "Klaus: semantic search needs an API key" not in _SETUP_SRC)


section("crop_dialog.py: dialog is themed")
check("references theme.dialog_qss", "dialog_qss" in _CROP_SRC)
check("references theme.muted_label_qss for the hint label",
      "muted_label_qss" in _CROP_SRC)
check("guarded with try/except + print('[klaus_note] ...') fallback pattern",
      "except Exception as exc:" in _CROP_SRC
      and 'print(f"[klaus_note] crop dialog theme failed' in _CROP_SRC)

section("crop_dialog.py: button roles")
check("Cancel button carries SecondaryButton",
      'cancel_btn.setObjectName("SecondaryButton")' in _CROP_SRC)
check("Crop (primary) button keeps no override — default blue",
      'self._crop_btn.setObjectName' not in _CROP_SRC)

section("crop_dialog.py: no hardcoded hex outside comments")
hits2 = _hex_hits_outside_comments(_CROP_SRC)
check("zero literal hex colours in code (comments are exempt)",
      len(hits2) == 0, str(hits2))
check("the frozen brand blue is gone entirely — the crop selection "
      "draws in the USER'S accent from the palette (K-critique P2)",
      "#3a82f7" not in _CROP_SRC
      and "_KLAUS_BLUE" not in _CROP_SRC
      and 'palette(theme.night_mode())["blue_accent"]' in _CROP_SRC)

section("K-115: paintEvent guards its QPainter (md3_switch's rule)")
# A QPainter constructed and .end()ed with no try/finally between them
# is the proven-fatal md3_switch pattern: any exception in the body
# leaves a live painter on the widget, corrupts the backing store, and
# segfaults Qt on the next flush (nine crashes, 2026-08-26). Pin the
# custom-painted crop_dialog canvas (pdf_viewer's selection overlay, the
# other one, went with the native renderer in PDF reader 5/5).
import ast as _ast


def _paint_event_guarded(src: str) -> tuple:
    """(has_try_finally, finally_ends_painter, except_logs) for the
    file's paintEvent, via AST so comments can't fake a pass."""
    for node in _ast.walk(_ast.parse(src)):
        if isinstance(node, _ast.FunctionDef) and node.name == "paintEvent":
            for t in _ast.walk(node):
                if isinstance(t, _ast.Try) and t.finalbody:
                    fin = _ast.unparse(_ast.Module(t.finalbody, []))
                    exc = (
                        _ast.unparse(_ast.Module(t.handlers[0].body, []))
                        if t.handlers
                        else ""
                    )
                    return (
                        True,
                        "painter.end()" in fin,
                        "[klaus_note]" in exc,
                    )
    return (False, False, False)


_tf, _fe, _el = _paint_event_guarded(_CROP_SRC)
check("crop_dialog.paintEvent wraps its body in try/finally", _tf)
check("crop_dialog.paintEvent's finally closes the painter", _fe)
check("crop_dialog.paintEvent's except logs, never re-raises", _el)

section("crop_dialog.py: crop behaviour untouched (style only)")
check("rubber-band selection state machine intact",
      'self._mode = "draw"' in _CROP_SRC
      and 'self._mode = "move"' in _CROP_SRC
      and 'self._mode = "resize"' in _CROP_SRC)
check("save-as-new-file encode path intact",
      "def encode_cropped" in _CROP_SRC and "_KEEP_FORMATS" in _CROP_SRC)
check("crop dialog title still names the file, not renamed to Klaus Note",
      'f"Crop Image: {fname}"' in _CROP_SRC)

class _FakeBtn:
    def __init__(self):
        self.object_name = ""

    def setObjectName(self, name):
        self.object_name = name


class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)


class _FakeMsg:
    def __init__(self, title):
        self.title, self.text, self.info = title, "", ""
        self.opened = False
        self.finished = _FakeSignal()

    def setText(self, text):
        self.text = text

    def setInformativeText(self, text):
        self.info = text

    def addButton(self, *_a):
        return _FakeBtn()

    def clickedButton(self):
        return None

    def deleteLater(self):
        pass

    def open(self):
        self.opened = True


def _nudge_for(cfg):
    """(title, text, informative) the readiness nudge would show, or None
    when it shows nothing at all."""
    shown = []
    saved = (setup_flow._themed_message_box, _settings.store)

    def _fake_box(_parent, title, _icon):
        msg = _FakeMsg(title)
        shown.append(msg)
        return msg

    setup_flow._themed_message_box = _fake_box
    _settings.store = _settings.DictStore(cfg)
    try:
        setup_flow._readiness_check_body()
    finally:
        (setup_flow._themed_message_box, _settings.store) = saved
    if not shown:
        return None
    return (shown[0].title, shown[0].text, shown[0].info)


nudge = _nudge_for({})
check("readiness directs users to local models", nudge is not None and "Local models" in nudge[1] and "Ollama" in nudge[2])
check("legacy keys never suppress local readiness", _nudge_for({"api_key_openai": "old", "_embed_key_setup_declined": True}) == nudge)

raise SystemExit(report())
