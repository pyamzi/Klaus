"""#19: Edit Cards and a closing Add never drop drawing changes not yet used.

A changed Draw tab (draw_tab.dirty) blocks Edit Cards and any Add that
closes the occlusion editor (Ctrl+Return / Ctrl+Shift+Return) with the
tooltip the Add button already shows before a first Use drawing:
"Press Use drawing first". Nothing is read from svg-edit, so no note is
written and the editor stays open. A clean drawing, no Draw tab, and an Add
that keeps the editor open are unchanged.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_io_unused_drawing_guard.py
"""
from __future__ import annotations

import importlib
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import _permissive_module, check, install, report, section  # noqa: E402

install()
for _name in ("aqt.addcards", "aqt.editcurrent", "aqt.reviewer", "anki.notes",
              "anki.errors", "anki.config"):
    _permissive_module(_name)

add = importlib.import_module("klaus_note.image_occlusion.add")
TIPS = []
add.tooltip = lambda msg, *a, **k: TIPS.append(msg)
HINT = "Press Use drawing first"


class SvgEdit:
    """svg-edit's webview: records the reads that would write notes."""

    def __init__(self):
        self.reads = []

    def evalWithCallback(self, js, cb):
        self.reads.append(js)


def session(draw_tab="clean", add_blocked=False):
    dialog = types.SimpleNamespace(
        add_blocked=add_blocked, svg_edit=SvgEdit(),
        draw_tab=None if draw_tab is None else types.SimpleNamespace(dirty=draw_tab == "dirty"))
    ia = add.ImgOccAdd.__new__(add.ImgOccAdd)
    ia.imgoccedit = dialog
    return ia, dialog


def run(label, action, draw_tab, blocked):
    ia, dialog = session(draw_tab)
    TIPS.clear()
    action(ia)
    if blocked:
        check(label + ": nothing read from svg-edit (no note written, editor open)",
              dialog.svg_edit.reads == [], str(dialog.svg_edit.reads))
        check(label + ": the tooltip says " + repr(HINT), TIPS == [HINT], str(TIPS))
    else:
        check(label + ": svg-edit's masks are read, as before",
              len(dialog.svg_edit.reads) == 1, str(dialog.svg_edit.reads))
        check(label + ": no tooltip", TIPS == [], str(TIPS))


EDIT = lambda ia: ia.onEditNotesButton("Don't Change")  # noqa: E731
ADD_CLOSE = lambda ia: ia.onAddNotesButton("ao", True)  # noqa: E731
ADD_OA_CLOSE = lambda ia: ia.onAddNotesButton("oa", True)  # noqa: E731
ADD_STAY = lambda ia: ia.onAddNotesButton("ao", False)  # noqa: E731

section("a changed, unused drawing blocks the actions that close the editor")
run("Edit Cards", EDIT, "dirty", True)
run("Ctrl+Return (Add ao, close)", ADD_CLOSE, "dirty", True)
run("Ctrl+Shift+Return (Add oa, close)", ADD_OA_CLOSE, "dirty", True)

section("an Add that keeps the editor open is unchanged with a dirty drawing")
run("Add without close", ADD_STAY, "dirty", False)

section("a clean drawing, or no Draw tab: unchanged")
for state in ("clean", None):
    run("Edit Cards (%s)" % state, EDIT, state, False)
    run("Add and close (%s)" % state, ADD_CLOSE, state, False)
    run("Add without close (%s)" % state, ADD_STAY, state, False)

section("before a first Use drawing Add is still blocked (add_blocked)")
ia, dialog = session("clean", add_blocked=True)
TIPS.clear()
ia.onAddNotesButton("ao", False)
check("no read and the same tooltip", dialog.svg_edit.reads == [] and TIPS == [HINT], str(TIPS))

section("Change Image after changing the drawing: the photo wins, nothing blocks")
ia, dialog = session("dirty")
dialog.svg_edit.eval = lambda js: None
dialog.set_add_enabled = lambda on: None
ia.getNewImage = lambda *a, **k: "/photos/photo.png"
_dims = add.get_image_dimensions
add.get_image_dimensions = lambda p: (400, 300)
try:
    ia.onChangeImage()
finally:
    add.get_image_dimensions = _dims
check("the picked photo is the image", ia.image_path == "/photos/photo.png")
check("...and the drawing no longer counts as unused (clean)", dialog.draw_tab.dirty is False)
for label, action in (("Edit Cards", EDIT), ("Add and close", ADD_CLOSE)):
    TIPS.clear()
    dialog.svg_edit.reads.clear()
    action(ia)
    check(label + " after Change Image: masks read, no tooltip",
          len(dialog.svg_edit.reads) == 1 and TIPS == [], str(TIPS))

raise SystemExit(report())
