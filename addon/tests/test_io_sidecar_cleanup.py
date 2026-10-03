"""#30: a diagram's _<image>.excalidraw goes once no note names its image.

Every removal goes through add.drop_unused_sidecar(image_name): it moves the
sidecar to Anki's media trash (col.media.trash_files: syncs as a deletion,
Check Media can restore it) only when no note's fields contain the image's
name, and never touches anything else. A successful re-edit that moved the
notes to a new image name calls it for the old name.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_io_sidecar_cleanup.py
"""
from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import _permissive_module, check, install, report, section  # noqa: E402

install()
for _name in ("aqt.addcards", "aqt.editcurrent", "aqt.reviewer", "anki.notes",
              "anki.errors", "anki.config"):
    _permissive_module(_name)

add = importlib.import_module("klaus_note.image_occlusion.add")
excal_tab = importlib.import_module("klaus_note.image_occlusion.excal_tab")
add.tooltip = lambda *a, **k: None
SCENE = {"type": "excalidraw", "elements": [],
         "klaus": {"originX": 0, "originY": 0, "padding": 20, "scale": 2}}


class Col:
    """The collection as far as the cleanup reads it: notes(flds) in SQLite
    (the real LIKE runs), a media folder and its trash."""

    def __init__(self):
        self.media_dir = tempfile.mkdtemp(prefix="io-sidecar-media-")
        self.trashed, self.trash_error = [], None
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("create table notes (id integer primary key, flds text)")
        self.db = types.SimpleNamespace(scalar=self._scalar)
        self.media = types.SimpleNamespace(dir=lambda: self.media_dir, trash_files=self._trash)

    def _scalar(self, sql, *args):
        row = self.conn.execute(sql, args).fetchone()
        return row[0] if row else None

    def _trash(self, names):
        if self.trash_error:
            raise self.trash_error
        for n in names:
            self.trashed.append(n)
            os.remove(os.path.join(self.media_dir, n))

    def note(self, nid, image_name, escape=False):
        src = image_name.replace("&", "&amp;") if escape else image_name
        flds = '<img src="%s">\x1f<img src="abc-ao-O.svg">\x1fabc-ao-%d' % (src, nid)
        self.conn.execute("insert or replace into notes values (?, ?)", (nid, flds))

    def sidecar(self, image_name):
        path = os.path.join(self.media_dir, "_" + image_name + ".excalidraw")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(SCENE, f)
        return path


def use(col):
    add.mw = types.SimpleNamespace(col=col)
    return col


drop = getattr(add, "drop_unused_sidecar", None)
check("add.drop_unused_sidecar exists (the one removal path)", callable(drop))


def attempt(name):
    try:
        return drop(name) if drop else None
    except Exception as e:  # noqa: BLE001
        return e


section("drop_unused_sidecar: trashed only when no note names the image")
col = use(Col())
side = col.sidecar("diagram-1.png")
col.note(1, "diagram-2.png")
check("no note names it: returns True", attempt("diagram-1.png") is True)
check("...and the sidecar went through col.media.trash_files",
      col.trashed == ["_diagram-1.png.excalidraw"] and not os.path.exists(side), str(col.trashed))

col = use(Col())
side = col.sidecar("diagram-1.png")
col.note(1, "diagram-1.png")
check("a note still names it: kept (False)", attempt("diagram-1.png") is False
      and os.path.isfile(side) and col.trashed == [])

col = use(Col())
side = col.sidecar("50%_a.png")
col.note(1, "50%_a.png")
check("LIKE's % and _ in a referenced name: kept", attempt("50%_a.png") is False
      and os.path.isfile(side))
col.conn.execute("delete from notes")
col.note(1, "50%Xa.png")
check("...and they match only themselves (an unrelated name doesn't keep it)",
      attempt("50%_a.png") is True and not os.path.exists(side))

col = use(Col())
side = col.sidecar("a&b.png")
col.note(1, "a&b.png", escape=True)
check("a name stored HTML-escaped (a&amp;b.png) still counts: kept",
      attempt("a&b.png") is False and os.path.isfile(side))

col = use(Col())
check("no sidecar: False, nothing trashed", attempt("diagram-9.png") is False
      and col.trashed == [])
outside = os.path.join(os.path.dirname(col.media_dir), "_x.png.excalidraw")
open(outside, "w").write("{}")
check("a name with a path: False, nothing outside media touched",
      attempt("../x.png") is False and os.path.isfile(outside) and col.trashed == [])
check("an empty name: False", attempt("") is False and col.trashed == [])

col = use(Col())
side = col.sidecar("diagram-1.png")
col.trash_error = RuntimeError("backend says no")
check("trash_files failing: False, no exception, file kept",
      attempt("diagram-1.png") is False and os.path.isfile(side))


section("a re-edit that moves the notes to a new image")


class Gen:
    """The note generator: updateNotes writes the notes, then calls on_done."""
    new_name = "diagram-2.png"
    col = None

    def __init__(self, ed, svg, image_path, opref, tags, fields, did):
        self.media_name = None

    def updateNotes(self, on_done=None):
        self.media_name = Gen.new_name
        for nid in (1, 2):
            Gen.col.note(nid, Gen.new_name)
        on_done("reset")


def re_edit(col, new_name, other_note_on_old=False, drawing=True):
    use(col)
    col.sidecar("diagram-1.png")
    for nid in (1, 2):
        col.note(nid, "diagram-1.png")
    if other_note_on_old:  # an "Add New Cards" batch on the same image
        col.note(3, "diagram-1.png")
    Gen.new_name, Gen.col = new_name, col
    ia = add.ImgOccAdd.__new__(add.ImgOccAdd)
    ia.imgoccedit, ia.ed, ia.image_path = types.SimpleNamespace(), None, None
    ia.opref = {"image": os.path.join(col.media_dir, "diagram-1.png"), "did": 1,
                "occl_tp": "ao"}
    ia.excal_sidecar = json.dumps(SCENE) if drawing else None
    ia.getUserInputs = lambda *a, **k: ({}, [])
    after = []
    ia._afterEditNotes = lambda dialog, r: after.append(r)
    add.genByKey = lambda *a: Gen
    try:
        ia._onEditNotesButton("Don't Change", "<svg/>")
    except Exception as e:  # noqa: BLE001
        return after, e
    return after, None


old_side = lambda col: os.path.join(col.media_dir, "_diagram-1.png.excalidraw")  # noqa: E731
new_side = lambda col: os.path.join(col.media_dir, "_diagram-2.png.excalidraw")  # noqa: E731

col = Col()
after, err = re_edit(col, "diagram-2.png")
check("the edit finishes as before", err is None and after == ["reset"], repr(err))
check("the new sidecar is written", os.path.isfile(new_side(col)))
check("no note names the old image any more: its sidecar is trashed",
      not os.path.exists(old_side(col)) and col.trashed == ["_diagram-1.png.excalidraw"],
      str(col.trashed))

col = Col()
after, err = re_edit(col, "diagram-2.png", other_note_on_old=True)
check("another note still on the old image: its sidecar is kept",
      err is None and os.path.isfile(old_side(col)) and col.trashed == [], str(col.trashed))
check("...and re-editing that note still finds its diagram (Draw tab)",
      excal_tab.read_diagram(col.media_dir, "diagram-1.png") is not None)

col = Col()
after, err = re_edit(col, "diagram-1.png")
check("the image name unchanged: the sidecar stays (rewritten in place)",
      err is None and os.path.isfile(old_side(col)) and col.trashed == [], str(col.trashed))

col = Col()
after, err = re_edit(col, "photo.png", drawing=False)
check("Change Image to a photo: the old diagram's sidecar is trashed, none written",
      err is None and col.trashed == ["_diagram-1.png.excalidraw"]
      and not [n for n in os.listdir(col.media_dir) if n.endswith(".excalidraw")],
      str(os.listdir(col.media_dir)))

raise SystemExit(report())
