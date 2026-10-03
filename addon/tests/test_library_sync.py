"""K-306: the !Library tag branch as the Library (spec
docs/superpowers/specs/2026-09-28-library-in-browse-design.md, Part 1).

1. plan_library_sync, the pure planner: registration of tagless and
   emptied tags, leaf renames and moves, folder renames (empty PDFs move
   with the folder), deletes that must be confirmed, the misrename fix,
   and loop safety (a settled state plans nothing).
2. The apply layer against a scratch user_files and a fake collection:
   drive_store, the stored tag and the file on disk follow the sidebar.
3. Delete: Yes sends the file to the Trash, No restores the tag.
4. The live hook only reacts to tag changes.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_library_sync.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

import klaus_note.settings as _settings  # noqa: E402

ts = importlib.import_module("klaus_note.tag_sync")
plan = ts.plan_library_sync


def kinds(actions):
    return sorted(a["kind"] for a in actions)


# ------------------------------------------------------------ planner

section("tagless and emptied tags are registered, never renamed")
acts = plan({"a": (None, "Anemia.pdf")}, {}, set())
check("a never-tagged PDF gets its tag registered",
      acts == [{"kind": "register", "safe": "a", "tag": "!Library::Anemia"}], str(acts))

acts = plan({"z": (None, "Zero.pdf")}, {"z": "!Library::Zero"}, {"!Library::Stray"}, empty={"z"})
check("misrename fix: a zero-match PDF whose tag never existed is not "
      "renamed to the one stray !Library tag",
      acts == [{"kind": "register", "safe": "z", "tag": "!Library::Zero"}], str(acts))

acts = plan({"z": (None, "Zero.pdf")}, {"z": "!Library::Zero"}, set(), empty={"z"})
check("Check Database dropped an empty PDF tag: silently re-registered",
      acts == [{"kind": "register", "safe": "z", "tag": "!Library::Zero"}], str(acts))

acts = plan({}, {}, set(), folders={"Heme"})
check("an empty folder gets a folder tag",
      acts == [{"kind": "register", "safe": None, "tag": "!Library::Heme"}], str(acts))
acts = plan({"a": ("Heme", "A.pdf")}, {"a": "!Library::Heme::A"}, {"!Library::Heme::A"}, folders={"Heme"})
check("a folder with a tagged PDF needs no row of its own", acts == [], str(acts))

section("sidebar renames and moves of one PDF")
acts = plan({"a": ("Heme", "Anemia.pdf")}, {"a": "!Library::Heme::Anemia"},
            {"!Library::Heme::Anemias"}, nonempty={"a"}, folders={"Heme"})
check("a leaf rename renames the display, keeps the folder",
      acts == [{"kind": "rename", "safe": "a", "old": "!Library::Heme::Anemia",
                "new": "!Library::Heme::Anemias", "folder": "Heme", "display": "Anemias.pdf"}], str(acts))

state = ({"a": ("Heme", "Anemia.pdf"), "b": ("Onc", "Leuk.pdf")},
         {"a": "!Library::Heme::Anemia", "b": "!Library::Onc::Leuk"})
acts = plan(*state, {"!Library::Onc::Anemia", "!Library::Onc::Leuk"}, nonempty={"a", "b"},
            folders={"Heme", "Onc"})
check("dragging a PDF tag into an existing folder moves it, display untouched",
      acts == [{"kind": "rename", "safe": "a", "old": "!Library::Heme::Anemia",
                "new": "!Library::Onc::Anemia", "folder": "Onc", "display": None}], str(acts))

section("folder renames move every PDF in them, empty ones too")
pdfs = {"a": ("Heme", "A.pdf"), "b": ("Heme", "B.pdf"), "e": ("Heme", "Empty.pdf"), "o": ("Onc", "O.pdf")}
stored = {"a": "!Library::Heme::A", "b": "!Library::Heme::B", "e": "!Library::Heme::Empty",
          "o": "!Library::Onc::O"}
acts = plan(pdfs, stored, {"!Library::Hema::A", "!Library::Hema::B", "!Library::Onc::O"},
            nonempty={"a", "b", "o"}, empty={"e"}, folders={"Heme", "Onc"})
check("Heme -> Hema is one folder rename carrying the empty PDF",
      acts == [{"kind": "folder_rename", "old": "Heme", "new": "Hema", "safes": ["a", "b", "e"],
                "tags": {"a": "!Library::Hema::A", "b": "!Library::Hema::B"}}], str(acts))

pdfs = {"a": ("Y1/Heme", "A.pdf"), "b": ("Y1/Heme", "B.pdf"), "k": ("Y1/Kidney", "K.pdf")}
stored = {"a": "!Library::Y1::Heme::A", "b": "!Library::Y1::Heme::B", "k": "!Library::Y1::Kidney::K"}
acts = plan(pdfs, stored, {"!Library::Y2::Heme::A", "!Library::Y2::Heme::B", "!Library::Y1::Kidney::K"},
            nonempty={"a", "b", "k"}, folders={"Y1", "Y1/Heme", "Y1/Kidney", "Y2"})
check("dragging folder Heme from Y1 into Y2 moves just that folder",
      kinds(acts) == ["folder_rename"] and acts[0]["old"] == "Y1/Heme" and acts[0]["new"] == "Y2/Heme",
      str(acts))

pdfs = {"a": ("Heme", "A.pdf"), "b": ("Heme", "B.pdf"), "g": ("Onc", "G.pdf")}
stored = {"a": "!Library::Heme::A", "b": "!Library::Heme::B", "g": "!Library::Onc::G"}
acts = plan(pdfs, stored, {"!Library::Onc::A", "!Library::Onc::B", "!Library::Onc::G"},
            nonempty={"a", "b", "g"}, folders={"Heme", "Onc"})
check("dragging both PDFs into an EXISTING folder is two moves, not a folder merge",
      kinds(acts) == ["rename", "rename"] and {a["folder"] for a in acts} == {"Onc"}, str(acts))

section("deletes are confirmed, never silent")
acts = plan({"a": (None, "A.pdf")}, {"a": "!Library::A"}, set(), nonempty={"a"})
check("deleting a PDF tag with cards asks to delete that PDF",
      acts == [{"kind": "delete", "folder": None, "safes": ["a"]}], str(acts))

acts = plan({"a": ("Heme", "A.pdf"), "b": ("Heme", "B.pdf"), "e": ("Heme", "E.pdf")},
            {"a": "!Library::Heme::A", "b": "!Library::Heme::B", "e": "!Library::Heme::E"},
            set(), nonempty={"a", "b"}, empty={"e"}, folders={"Heme"})
check("deleting the folder tag asks once for every PDF in it",
      acts == [{"kind": "delete", "folder": "Heme", "safes": ["a", "b", "e"]}], str(acts))

acts = plan({"a": (None, "A.pdf")}, {"a": "!Library::A"}, set())
check("an unknown (cold cache) vanished tag is re-registered, not a prompt",
      kinds(acts) == ["register"], str(acts))

acts = plan({"z": (None, "Zero.pdf")}, {"z": "!Library::Zero"}, set(), empty={"z"}, deleted={"z"})
check("Delete on a card-less PDF's tag in the sidebar asks to delete that PDF (K-316)",
      acts == [{"kind": "delete", "folder": None, "safes": ["z"]}], str(acts))
acts = plan({"z": (None, "Zero.pdf")}, {"z": "!Library::Zero"}, set(), deleted={"z"})
check("...a cold-cache one too: the user's Delete is what counts",
      kinds(acts) == ["delete"], str(acts))

section("never claimed")
acts = plan({"a": (None, "A.pdf"), "b": (None, "B.pdf")}, {"a": "!Library::A", "b": "!Library::B"},
            {"!Library::B", "!Library::Curated"}, nonempty={"a"})
check("reserved root tags are never a rename target", kinds(acts) == ["delete"], str(acts))

section("Anki's case is Anki's: tags compare ignoring case")
acts = plan({"z": (None, "Zero.pdf")}, {"z": "!Library::Zero"}, {"!Library::zero"}, empty={"z"})
check("a respelled tag is present: adopt Anki's spelling once, register nothing new",
      acts == [{"kind": "register", "safe": "z", "tag": "!Library::zero"}], str(acts))
check("...and then it is settled",
      plan({"z": (None, "Zero.pdf")}, {"z": "!Library::zero"}, {"!Library::zero"}, empty={"z"}) == [])
acts = plan({"a": ("Heme", "A.pdf")}, {}, {"!Library::heme::A"}, folders={"Heme"})
check("a new PDF under a respelled folder takes the existing spelling",
      acts == [{"kind": "register", "safe": "a", "tag": "!Library::heme::A"}], str(acts))

section("loop safety: a settled library plans nothing")
check("everything tagged and present -> []",
      plan({"a": ("Heme", "A.pdf"), "e": (None, "E.pdf")}, {"a": "!Library::Heme::A", "e": "!Library::E"},
           {"!Library::Heme::A", "!Library::E", "!Library::Curated"}, folders={"Heme"}) == [])


# ------------------------------------------------------------ apply layer

curation = importlib.import_module("klaus_note.curation")
drive_store = importlib.import_module("klaus_note.drive_store")
pdf_handler = importlib.import_module("klaus_note.pdf_handler")
retention = importlib.import_module("klaus_note.retention")
UF = tempfile.mkdtemp(prefix="klaus-k306-")  # fresh: the stub's scratch dir persists between runs
_settings.user_files_dir = UF
root = tempfile.mkdtemp(prefix="klaus-root-")
pdf_handler._live_library_root = lambda: root
os.makedirs(os.path.join(UF, "contexts"), exist_ok=True)


def add_pdf(safe, display, folder, tag):
    open(os.path.join(UF, "contexts", safe + ".txt"), "w").write("text")
    drive_store.record_import(UF, safe, display)
    drive_store.set_folder(UF, safe, folder)
    rel = os.path.join(*(folder.split("/") if folder else []), safe + ".pdf")
    os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
    open(os.path.join(root, rel), "wb").write(b"%PDF")
    m = pdf_handler.load_library_map(UF)
    m[safe] = rel
    pdf_handler.save_library_map(UF, m)
    if tag:
        ts.set_stored_tag(safe, tag)


class Tags:
    def __init__(self, tags):
        self.tags, self.collapsed = set(tags), []

    def all(self):
        return sorted(self.tags)

    def set_collapsed(self, tag, collapsed):
        self.collapsed.append(tag)
        self.tags.add(tag)
        return "OpChanges"

    def remove(self, space_separated_tags):
        # Anki's TagManager.remove takes ONE space-separated string (#21).
        if not isinstance(space_separated_tags, str):
            raise TypeError("bad argument type for built-in operation")
        self.tags -= set(space_separated_tags.split())


class Col:
    def __init__(self, tags):
        self.tags = Tags(tags)

    def add_custom_undo_entry(self, label):
        return 1

    def merge_undo_entries(self, pos):
        return "OpChanges"


ops = []


class Op:
    def __init__(self, parent=None, op=None):
        self.op = op
        self.parent = parent
        ops.append(self)

    def success(self, fn):
        return self

    def failure(self, fn):
        return self

    def run_in_background(self, **_kw):
        self.result = self.op(col)


ts.CollectionOp = Op
ts._membership_known = lambda safes, cfg: (known_nonempty & set(safes), set(safes) - known_nonempty)
known_nonempty: set = set()

section("apply: a sidebar move moves the file and the record")
add_pdf("anemia", "Anemia.pdf", "Heme", "!Library::Heme::Anemia")
add_pdf("leuk", "Leuk.pdf", "Onc", "!Library::Onc::Leuk")
known_nonempty = {"anemia", "leuk"}
col = Col({"!Library::Onc::Anemia", "!Library::Onc::Leuk"})
ts.reconcile_from_tags(col)
check("drive_store follows the drag", drive_store.load(UF)["pdfs"]["anemia"]["folder"] == "Onc")
check("the file moved on disk", os.path.isfile(os.path.join(root, "Onc", "anemia.pdf"))
      and not os.path.exists(os.path.join(root, "Heme", "anemia.pdf")))
check("the stored tag is the sidebar's tag", ts.get_stored_tag("anemia") == "!Library::Onc::Anemia")
col.tags.tags |= {"!Library::Heme"}  # the now-empty folder registered
check("settled after one pass", ts._plan(col, {}) == [], str(ts._plan(col, {})))

section("apply: a folder rename moves the directory and the empty PDF")
add_pdf("a1", "A1.pdf", "Kidney", "!Library::Kidney::A1")
add_pdf("e1", "E1.pdf", "Kidney", "!Library::Kidney::E1")
known_nonempty = {"anemia", "leuk", "a1"}
col.tags.tags = {"!Library::Onc::Anemia", "!Library::Onc::Leuk", "!Library::Heme", "!Library::Renal::A1"}
ts.reconcile_from_tags(col)
pdfs = drive_store.load(UF)["pdfs"]
check("both PDFs now in Renal", pdfs["a1"]["folder"] == "Renal" and pdfs["e1"]["folder"] == "Renal", str(pdfs))
check("the directory was renamed on disk", os.path.isfile(os.path.join(root, "Renal", "e1.pdf")))
check("the empty PDF's tag was registered at its new place",
      "!Library::Renal::E1" in col.tags.tags and ts.get_stored_tag("e1") == "!Library::Renal::E1")
check("settled", ts._plan(col, {}) == [], str(ts._plan(col, {})))

section("a tag that vanished WITHOUT a sidebar delete is restored, never a prompt")
asked, restored, trashed = [], [], []
ts._ask = lambda text, on_yes, on_no: (asked.append(text), on_no())
ts._reapply_missing = lambda col_, missing, cfg: restored.append(sorted(missing))
col.tags.tags.discard("!Library::Onc::Leuk")
ts.reconcile_from_tags(col)
check("no delete prompt when the user deleted nothing (a sync caught mid-way, "
      "Check Database, another add-on)", asked == [], str(asked))
check("...the tag is put back instead", restored == [["leuk"]], str(restored))

section("apply: deleting a tag in the sidebar asks; No restores, Yes trashes")
del restored[:]
ts.note_user_deleted(["!Library::Onc::Leuk"])
ts.reconcile_from_tags(col)
check("one prompt naming the PDF", len(asked) == 1 and "Leuk" in asked[0], str(asked))
check("No restores the tag", restored == [["leuk"]], str(restored))
ts.reconcile_from_tags(col)
check("a delete is asked about once, not again on the next pass", len(asked) == 1, str(asked))
ts.note_user_deleted(["!Library::Onc"])  # the folder tag: covers the PDFs under it

pdf_drive = importlib.import_module("klaus_note.pdf_drive")
pdf_drive._move_to_trash = lambda path: trashed.append(path)
ts._ask = lambda text, on_yes, on_no: on_yes()
ts.reconcile_from_tags(col)
check("Yes sends the source PDF to the Trash", trashed == [os.path.join(root, "Onc", "leuk.pdf")], str(trashed))
check("and the PDF is gone from the Library", not os.path.exists(os.path.join(UF, "contexts", "leuk.txt")))

section("K-316: Delete on a card-less PDF's tag asks too")
asked2 = []
ts._ask = lambda text, on_yes, on_no: (asked2.append(text), on_no())
col.tags.tags.discard("!Library::Renal::E1")  # e1 has no matched cards
ts.note_user_deleted(["!Library::Renal::E1"])
ts.reconcile_from_tags(col)
check("one prompt naming the card-less PDF", len(asked2) == 1 and "E1" in asked2[0], str(asked2))

section("K-319: a sync op's progress window never hangs off a closable dialog")
_dialog = object()
ts._run_sync_op(_dialog, "Klaus: test", lambda col: {})
check("progress is parented to mw, not the caller's dialog",
      ops[-1].parent is ts.mw and ops[-1].parent is not _dialog, repr(ops[-1].parent))
ts._own_ops["pending"] -= 1  # the fake op never reports back

section("a reconcile waits for Klaus's own tag ops to land")
ran = []
_real_reconcile = ts.reconcile_from_tags
ts.reconcile_from_tags = lambda c: ran.append(1)
rescheduled = []
_real_schedule = ts._schedule_reconcile
ts._schedule_reconcile = lambda: rescheduled.append(1)
ts.mw = types.SimpleNamespace(col=col)
ts._own_ops["pending"] = 1
ts._reconcile_now()
check("while one of our ops is in flight it is put off, not run", ran == [] and rescheduled == [1])
ts._own_ops["pending"] = 0
ts._reconcile_now()
check("...and runs once they have landed", ran == [1])
ts.reconcile_from_tags, ts._schedule_reconcile = _real_reconcile, _real_schedule

section("the live hook reacts to tag changes only")
fired = []
ts._schedule_reconcile = lambda: fired.append(1)
ts.on_operation_did_execute(types.SimpleNamespace(tag=False), None)
ts.on_operation_did_execute(types.SimpleNamespace(tag=True), None)
check("one schedule, for the tag change", fired == [1])
_init = open("klaus_note/__init__.py", encoding="utf-8").read()
check("registered on operation_did_execute",
      "gui_hooks.operation_did_execute.append(_tag_sync.on_operation_did_execute)" in _init)

section("#21: a delete removes the PDF's tag, Remove Folder the folder's")
add_pdf("gone", "Gone.pdf", "Renal", "!Library::Renal::Gone")
col.tags.tags.add("!Library::Renal::Gone")
pdf_drive.delete_pdf("gone")
check("deleting an indexed PDF leaves no !Library tag behind for it",
      "!Library::Renal::Gone" not in col.tags.tags, str(sorted(col.tags.tags)))
_act = importlib.import_module("klaus_note.library_actions")
drive_store.add_folder(UF, "Empty")
col.tags.tags.add("!Library::Empty")
_act.remove_empty_folder("Empty")
check("Remove Folder on an empty folder removes its tag from the sidebar",
      "!Library::Empty" not in col.tags.tags, str(sorted(col.tags.tags)))

raise SystemExit(report())
