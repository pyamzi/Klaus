"""Headless tests for K-112: theming the last two unthemed Klaus dialogs —
setup_flow.py's first-run/readiness QMessageBoxes and crop_dialog.py's
ImageCropDialog.

Pins the acceptance criteria from board/board.py show K-112:
  1. every QDialog these modules build applies theme.dialog_qss(...)
  2. secondary/cancel buttons carry the SecondaryButton objectName
  3. no literal hardcoded hex colour outside comments
  4. window titles use "KlausMate" casing where the addon name appears in
     a title, while short "Klaus" prose (e.g. "Welcome to Klaus") is left
     alone
"""
import importlib
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

# Importing under the headless stubs also proves neither module raises at
# import time (syntax errors, bad relative imports, etc.) after the edit.
setup_flow = importlib.import_module("klausmate.setup_flow")
crop_dialog = importlib.import_module("klausmate.crop_dialog")

_SETUP_SRC = open("klausmate/setup_flow.py").read()
_CROP_SRC = open("klausmate/crop_dialog.py").read()

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def _hex_hits_outside_comments(src: str) -> list:
    """Literal 6-digit hex colours that appear before any '#' comment
    marker on their line. A whole-line comment (line stripped starts with
    '#') never counts; only the code portion of a line — everything
    before the first '#' — is checked, since this codebase never embeds
    a literal '#' inside a string on these lines (confirmed by inspection
    of both files pre-edit)."""
    hits = []
    for lineno, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_part = line.split("#", 1)[0]
        if _HEX_RE.search(code_part):
            hits.append((lineno, line))
    return hits


section("setup_flow.py: dialogs are themed")
check("references theme.dialog_qss", "dialog_qss" in _SETUP_SRC)
check("references theme.night_mode", "night_mode" in _SETUP_SRC)
check("guarded with try/except + print('[klausmate] ...') fallback pattern",
      "except Exception as exc:" in _SETUP_SRC
      and 'print(f"[klausmate] setup dialog theme failed' in _SETUP_SRC)
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
check("addon-name window titles use KlausMate casing",
      "KlausMate: Ollama isn't running" in _SETUP_SRC
      and "KlausMate: local embedding model isn't set up yet" in _SETUP_SRC
      and "KlausMate: embedding model needed" in _SETUP_SRC
      and "KlausMate: semantic search needs an API key" in _SETUP_SRC)
check("bare 'Klaus:' titles were not left behind",
      "Klaus: Ollama isn't running" not in _SETUP_SRC
      and "Klaus: local embedding model isn't set up yet" not in _SETUP_SRC
      and "Klaus: embedding model needed" not in _SETUP_SRC
      and "Klaus: semantic search needs an API key" not in _SETUP_SRC)


section("crop_dialog.py: dialog is themed")
check("references theme.dialog_qss", "dialog_qss" in _CROP_SRC)
check("references theme.muted_label_qss for the hint label",
      "muted_label_qss" in _CROP_SRC)
check("guarded with try/except + print('[klausmate] ...') fallback pattern",
      "except Exception as exc:" in _CROP_SRC
      and 'print(f"[klausmate] crop dialog theme failed' in _CROP_SRC)

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

section("crop_dialog.py: crop behaviour untouched (style only)")
check("rubber-band selection state machine intact",
      'self._mode = "draw"' in _CROP_SRC
      and 'self._mode = "move"' in _CROP_SRC
      and 'self._mode = "resize"' in _CROP_SRC)
check("save-as-new-file encode path intact",
      "def encode_cropped" in _CROP_SRC and "_KEEP_FORMATS" in _CROP_SRC)
check("crop dialog title still names the file, not renamed to KlausMate",
      'f"Crop Image — {fname}"' in _CROP_SRC)

raise SystemExit(report())
