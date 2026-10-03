"""#14: a Library PDF's tag must never equal a folder's tag or another
PDF's tag (maintainer decision 2026-10-02: refuse clashing names inside
Klaus, flag a clash made in Finder and leave it untagged until it is
renamed, and compare exact tags in the membership diff).

Anki's tag operations act on child tags too: ``tag:"X"`` finds notes
tagged ``X::Y``, and ``bulk_remove``/``rename``/``remove`` of ``X`` take
``X::Y`` with it. The fake collection below follows those semantics, so
a root PDF ``X`` beside a folder ``X`` shows the damage the real
backend did.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_tag_clash.py
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

import klaus_note.settings as _settings  # noqa: E402

ts = importlib.import_module("klaus_note.tag_sync")
plan = ts.plan_library_sync


def _under(tag: str, root: str) -> bool:
    return tag.casefold() == root.casefold() or tag.casefold().startswith(root.casefold() + "::")


class AnkiTags:
    """Anki's TagManager as it behaves: every operation on X also acts on X::*."""

    def __init__(self, col, registry=()):
        self.col, self.registry = col, set(registry)
        self.renames: list = []

    def all(self):
        out = set(self.registry)
        for tags in self.col.notes.values():
            out |= tags
        return sorted(out)

    def bulk_add(self, nids, tag):
        assert isinstance(tag, str)
        for n in nids:
            self.col.notes.setdefault(n, set()).add(tag)

    def bulk_remove(self, nids, tag):
        assert isinstance(tag, str)
        for n in nids:
            self.col.notes[n] = {t for t in self.col.notes.get(n, set()) if not _under(t, tag)}

    def rename(self, old, new):
        self.renames.append((old, new))

        def move(t):
            return new + t[len(old):] if _under(t, old) else t

        self.registry = {move(t) for t in self.registry}
        for n, tags in self.col.notes.items():
            self.col.notes[n] = {move(t) for t in tags}

    def remove(self, space_separated_tags):
        if not isinstance(space_separated_tags, str):
            raise TypeError("bad argument type for built-in operation")
        for tag in space_separated_tags.split():
            self.registry = {t for t in self.registry if not _under(t, tag)}
            for n, tags in self.col.notes.items():
                self.col.notes[n] = {t for t in tags if not _under(t, tag)}

    def set_collapsed(self, tag, collapsed):
        self.registry.add(tag)
        return "OpChanges"


class AnkiCol:
    def __init__(self, notes=None, registry=()):
        self.notes = {n: set(t) for n, t in (notes or {}).items()}
        self.tags = AnkiTags(self, registry)

    def find_notes(self, search):
        """``tag:"…"`` the way rslib reads it: ``\\_``/``\\*`` literal,
        ``_``/``*`` wildcards, and a match on the tag OR any child."""
        if not (search.startswith('tag:"') and search.endswith('"')):
            return []
        body, pat, i = search[5:-1], "", 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                pat += re.escape(body[i + 1])
                i += 2
                continue
            pat += ".*" if c == "*" else "." if c == "_" else re.escape(c)
            i += 1
        rx = re.compile(pat + r"(::.*)?\Z", re.IGNORECASE)
        return sorted(n for n, tags in self.notes.items() if any(rx.match(t) for t in tags))

    def add_custom_undo_entry(self, label):
        return 1

    def merge_undo_entries(self, pos):
        return "OpChanges"


# ------------------------------------------------------------ the fake itself

section("the fake follows Anki's child semantics (the bug's precondition)")
_c = AnkiCol({1: {"!Library::Week_1"}, 2: {"!Library::Week_1::Lecture"}})
check("tag:X finds the notes of X::Lecture too", _c.find_notes(ts.tag_query("!Library::Week_1")) == [1, 2])
_c.tags.bulk_remove([2], "!Library::Week_1")
check("bulk_remove of X strips X::Lecture", _c.notes[2] == set())


# ------------------------------------------------------------ pure predicates

section("which PDFs clash (a clash made in Finder)")
ok = callable(getattr(ts, "tag_clashes", None))
check("tag_sync.tag_clashes exists", ok)
if ok:
    got = ts.tag_clashes({"ana": (None, "Anatomy.pdf"), "lec": ("Anatomy", "Lecture.pdf")}, {"Anatomy"})
    check("a root PDF next to a same-named folder clashes; the folder wins",
          set(got) == {"ana"} and "folder “Anatomy”" in got["ana"] and "Anatomy.pdf" in got["ana"], str(got))
    got = ts.tag_clashes({"ana": (None, "anatomy.pdf")}, {"Anatomy"})
    check("...compared ignoring case, as Anki compares tags", set(got) == {"ana"}, str(got))
    pdfs = {"w1": ("Heme", "Week 1.pdf"), "w2": ("Heme", "Week_1.pdf")}
    got = ts.tag_clashes(pdfs, {"Heme"})
    check("two PDFs whose names sanitize alike: exactly one is flagged (the later safe name)",
          set(got) == {"w2"}, str(got))
    check("...and its message names the other PDF", "Week 1.pdf" in got.get("w2", ""), str(got))
    got = ts.tag_clashes(pdfs, {"Heme"}, stored={"w2": "!Library::Heme::Week_1"})
    check("the PDF that already owns the tag keeps it; the newcomer is flagged",
          set(got) == {"w1"} and "Week_1.pdf" in got["w1"], str(got))
    check("an ordinary Library has no clash",
          ts.tag_clashes({"a": ("Heme", "A.pdf"), "b": (None, "B.pdf")}, {"Heme", "Onc"}) == {})
    check("a PDF named like a SUBFOLDER of its folder clashes too (ancestor tag)",
          set(ts.tag_clashes({"b": ("A", "B.pdf"), "c": ("A/B", "C.pdf")}, {"A/B"})) == {"b"})

section("refusing a clashing name inside Klaus")
ok = callable(getattr(ts, "name_clash", None))
check("tag_sync.name_clash exists", ok)
if ok:
    pdfs = {"w1": ("Heme", "Week 1.pdf"), "ana": (None, "Anatomy.pdf")}
    folders = {"Heme", "Week 1"}
    msg = ts.name_clash(pdfs, folders, "Heme", "Week_1.pdf")
    check("importing Week_1.pdf next to Week 1.pdf is refused, naming it", bool(msg) and "Week 1.pdf" in msg, str(msg))
    msg = ts.name_clash({}, {"Anatomy"}, None, "Anatomy.pdf")
    check("importing Anatomy.pdf next to folder Anatomy is refused, naming it",
          bool(msg) and "folder “Anatomy”" in msg, str(msg))
    msg = ts.name_clash(pdfs, folders, None, "Anatomy", is_folder=True)
    check("a new folder named like a PDF beside it is refused, naming the PDF",
          bool(msg) and "Anatomy.pdf" in msg, str(msg))
    msg = ts.name_clash(pdfs, folders, None, "Week_1", is_folder=True)
    check("a new folder that sanitizes like a sibling folder is refused",
          bool(msg) and "folder “Week 1”" in msg, str(msg))
    check("a free name passes", ts.name_clash(pdfs, folders, "Heme", "Week 2.pdf") is None)
    check("a folder is never its own clash (rename to the same tag)",
          ts.name_clash(pdfs, folders, None, "week 1", is_folder=True, skip="Week 1") is None)
    check("a PDF in another folder is no clash",
          ts.name_clash(pdfs, folders, "Onc", "Week_1.pdf") is None)


# ------------------------------------------------------------ the col layer

section("membership diffs touch only the exact tag (defence in depth)")
col = AnkiCol({1: {"!Library::X"}, 2: {"!Library::X::Lecture"}, 3: {"!Library::X", "!Library::X::Lecture"}})
added, removed = ts.apply_membership(col, "!Library::X", {1})
check("syncing root PDF X leaves the folder PDF's members untouched",
      "!Library::X::Lecture" in col.notes[2] and "!Library::X::Lecture" in col.notes[3], str(col.notes))
check("...and reports no removal from a child-tagged note", 2 not in removed and 3 not in removed, str(removed))

section("renaming a PDF never moves another PDF or a folder")
col = AnkiCol({1: {"!Library::Anatomy"}, 2: {"!Library::Anatomy::Lecture"}})
ts.apply_rename(col, "!Library::Anatomy", "!Library::Anatomy_overview")
check("a legacy PDF tag that is also a folder tag: the folder's PDF keeps its tag",
      col.notes[2] == {"!Library::Anatomy::Lecture"}, str(col.notes))
check("...the PDF's own notes follow it", "!Library::Anatomy_overview" in col.notes[1], str(col.notes))
acts = plan({"ana": (None, "Anatomy overview.pdf"), "lec": ("Anatomy", "Lecture.pdf")},
            {"ana": "!Library::Anatomy_overview", "lec": "!Library::Anatomy::Lecture"},
            set(col.tags.all()), nonempty={"ana", "lec"}, folders={"Anatomy"})
check("...so the reconcile plans no folder_rename", not any(a["kind"] == "folder_rename" for a in acts), str(acts))
col = AnkiCol({1: {"!Library::A"}, 2: {"!Library::B"}})
ts.apply_rename(col, "!Library::A", "!Library::A2")
check("an ordinary rename is still Anki's own rename", col.tags.renames == [("!Library::A", "!Library::A2")])

section("planner: the issue's repro never moves a folder on disk")
acts = plan({"ana": (None, "Anatomy overview.pdf"), "lec": ("Anatomy", "Lecture.pdf")},
            {"ana": "!Library::Anatomy_overview", "lec": "!Library::Anatomy::Lecture"},
            {"!Library::Anatomy_overview", "!Library::Anatomy_overview::Lecture"}, folders={"Anatomy"})
check("a tag that landed under another PDF's tag is no folder rename",
      not any(a["kind"] == "folder_rename" for a in acts), str(acts))
check("...nor a move of the PDF into a folder named like that PDF",
      not any(a["kind"] == "rename" for a in acts), str(acts))

section("planner: a drag into an EXISTING folder still moves the PDF (round 1)")
acts = plan({"ana": (None, "Anatomy.pdf"), "lec": ("Heme", "Lec.pdf"), "x": ("Anatomy", "X.pdf")},
            {"lec": "!Library::Heme::Lec", "x": "!Library::Anatomy::X"},
            {"!Library::Anatomy::Lec", "!Library::Anatomy::X"}, nonempty={"lec", "x"},
            folders={"Heme", "Anatomy"}, clashing={"ana"})
check("dragging Lec into Anatomy/ moves it, even beside a flagged root Anatomy.pdf",
      [(a["kind"], a.get("safe"), a.get("folder")) for a in acts] == [("rename", "lec", "Anatomy")], str(acts))

section("planner: a clashing PDF is never registered")
try:
    acts = plan({"ana": (None, "Anatomy.pdf"), "lec": ("Anatomy", "Lecture.pdf")},
                {"lec": "!Library::Anatomy::Lecture"}, {"!Library::Anatomy::Lecture"},
                folders={"Anatomy"}, clashing={"ana"})
except TypeError as exc:
    acts = [{"kind": "error", "why": str(exc)}]
check("a root PDF next to its folder gets no tag (it would be the folder's)",
      not any(a.get("safe") == "ana" for a in acts) and not any(a["kind"] == "error" for a in acts), str(acts))
try:
    acts = plan({"w1": ("Heme", "Week 1.pdf"), "w2": ("Heme", "Week_1.pdf")}, {}, set(),
                folders={"Heme"}, clashing={"w2"})
except TypeError as exc:
    acts = [{"kind": "error", "why": str(exc)}]
check("of two PDFs that sanitize alike, only the one not flagged is registered",
      [a.get("safe") for a in acts if a["kind"] == "register"] == ["w1"], str(acts))


# ------------------------------------------------------------ aqt glue

curation = importlib.import_module("klaus_note.curation")
drive_store = importlib.import_module("klaus_note.drive_store")
pdf_handler = importlib.import_module("klaus_note.pdf_handler")
retention = importlib.import_module("klaus_note.retention")
UF = tempfile.mkdtemp(prefix="klaus-tag-clash-")  # never the real user_files
_settings.user_files_dir = UF
root = tempfile.mkdtemp(prefix="klaus-tag-clash-root-")
pdf_handler._live_library_root = lambda: root
os.makedirs(os.path.join(UF, "contexts"), exist_ok=True)


def add_pdf(safe, display, folder, tag=None):
    open(os.path.join(UF, "contexts", safe + ".txt"), "w").write("text")
    drive_store.record_import(UF, safe, display)
    drive_store.set_folder(UF, safe, folder)
    rel = os.path.join(*(folder.split("/") if folder else []), display)
    os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
    open(os.path.join(root, rel), "wb").write(b"%PDF")
    m = pdf_handler.load_library_map(UF)
    m[safe] = rel
    pdf_handler.save_library_map(UF, m)
    if tag:
        ts.set_stored_tag(safe, tag)


ops: list = []
live = {"col": None}


class Op:
    def __init__(self, parent=None, op=None):
        self.op = op
        ops.append(self)

    def success(self, fn):
        return self

    def failure(self, fn):
        return self

    def run_in_background(self, **_kw):
        self.op(live["col"])
        ts._own_ops["pending"] -= 1  # the fake never reports back


ts.CollectionOp = Op
ts._schedule_reconcile = lambda: None

# A legacy collision (tagged before #14): root Anatomy.pdf owns the folder's tag.
add_pdf("ana", "Anatomy.pdf", None, "!Library::Anatomy")
add_pdf("lec", "Lecture.pdf", "Anatomy", "!Library::Anatomy::Lecture")
live["col"] = AnkiCol({1: {"!Library::Anatomy"}, 2: {"!Library::Anatomy::Lecture"}})

section("glue: a clash on disk is flagged, never tagged")
clashes = ts.library_clashes() if hasattr(ts, "library_clashes") else {}
check("library_clashes reads the Library and flags the root PDF", set(clashes) == {"ana"}, str(clashes))
_n = len(ops)
ts.sync_after_matches(None, "ana", [(1, 0.99), (3, 0.99)])
check("indexing a flagged PDF writes no tag (no collection op)", len(ops) == _n, str(len(ops) - _n))
check("...the folder PDF's tag is untouched", live["col"].notes[2] == {"!Library::Anatomy::Lecture"})

section("glue: a delete never removes a tag another PDF or folder still uses")
ts.sync_after_delete(None, "ana", "Anatomy.pdf")
check("deleting the legacy root PDF keeps every tag under the folder",
      live["col"].notes[2] == {"!Library::Anatomy::Lecture"}, str(live["col"].notes))

check("...only the PDF's own notes lose it", live["col"].notes[1] == set(), str(live["col"].notes))

section("glue: renaming the legacy PDF in Finder moves nothing else")
live["col"] = AnkiCol({1: {"!Library::Anatomy"}, 2: {"!Library::Anatomy::Lecture"}})  # not deleted after all
drive_store.rename_display(UF, "ana", "Anatomy overview.pdf")
ts.sync_after_folder_rename(None, ["ana"])
check("the folder PDF keeps its tag", live["col"].notes[2] == {"!Library::Anatomy::Lecture"}, str(live["col"].notes))
check("...Anki's rename never dragged the folder's tags", live["col"].tags.renames == [], str(live["col"].tags.renames))
check("...and the renamed PDF's notes carry its new tag",
      "!Library::Anatomy_overview" in live["col"].notes[1], str(live["col"].notes))
check("...which is now its stored tag", ts.get_stored_tag("ana") == "!Library::Anatomy_overview")

section("library_actions: refused with a message naming the clash")
act = importlib.import_module("klaus_note.library_actions")
warned: list = []
act.show_warning = lambda text, **_k: warned.append(text)
act.showWarning = lambda text, **_k: warned.append("EXEC-BASED: " + text)
_deferred: list = []
act.QTimer = type("T", (), {"singleShot": staticmethod(lambda ms, fn: (_deferred.append(ms), fn()))})
act._ask_text = lambda parent, title, label, value, on_text: on_text(answer["text"])
answer = {"text": ""}
pdf_drive = importlib.import_module("klaus_note.pdf_drive")
pdf_drive.start_library_rescan = lambda *a, **k: None
add_pdf("w1", "Week 1.pdf", "Heme")

answer["text"] = "Anatomy overview"
act.new_folder(None)
check("a new folder named like a root PDF is refused, naming the PDF",
      "Anatomy overview" not in drive_store.load(UF)["folders"]
      and warned and "Anatomy overview.pdf" in warned[-1], str(warned))

del warned[:]
src = tempfile.mkdtemp(prefix="klaus-tag-clash-src-")
open(os.path.join(src, "Week_1.pdf"), "wb").write(b"%PDF new")
n = act.import_files([os.path.join(src, "Week_1.pdf")], "Heme")
check("importing Week_1.pdf next to Week 1.pdf is refused, naming it",
      n == 0 and not os.path.exists(os.path.join(root, "Heme", "Week_1.pdf"))
      and warned and "Week 1.pdf" in warned[-1], str((n, warned, os.listdir(os.path.join(root, "Heme")))))

del warned[:]
drive_store.add_folder(UF, "Empty")
drive_store.add_folder(UF, "Week 1")
answer["text"] = "Week_1"
act.rename_folder(None, "Empty")
check("renaming an empty folder onto a sibling folder's tag is refused",
      "Empty" in drive_store.load(UF)["folders"] and warned, str(warned))

del warned[:]
src2 = tempfile.mkdtemp(prefix="klaus-tag-clash-src2-")
open(os.path.join(src2, "Lecture.pdf"), "wb").write(b"%PDF a")
src3 = tempfile.mkdtemp(prefix="klaus-tag-clash-src3-")
open(os.path.join(src3, "Lecture.pdf"), "wb").write(b"%PDF b")
n = act.import_files([os.path.join(src2, "Lecture.pdf"), os.path.join(src3, "Lecture.pdf")], "Heme")
check("two files with the SAME name in one batch are a re-import, not a clash: both land",
      n == 2 and not warned and len([f for f in os.listdir(os.path.join(root, "Heme")) if f.startswith("Lecture")]) == 2,
      str((n, warned, os.listdir(os.path.join(root, "Heme")))))

check("the drop-path warning is deferred a tick (never a dialog inside a Drop event)", 0 in _deferred, str(_deferred))

import inspect  # noqa: E402

_src = {n: inspect.getsource(getattr(act, n)) for n in ("new_folder", "rename_folder", "_refuse_clashes", "import_files")}
check("the refusals use no exec-based dialog (K-114: no showWarning/showInfo/QMessageBox/.exec)",
      not [n for n, src in _src.items() if any(t in src for t in ("showWarning(", "showInfo(", "QMessageBox(", ".exec("))],
      str([n for n, src in _src.items() if "showWarning(" in src]))
check("...and library_actions no longer imports aqt's exec-based showWarning",
      "showWarning" not in open("klaus_note/library_actions.py", encoding="utf-8").read())
check("...the drop-path warning has a parent", "parent=mw" in _src["_refuse_clashes"])

section("Remove Folder never removes a tag a PDF still stores (round 1)")
add_pdf("leg", "Legacy.pdf", None, "!Library::Legacy")
drive_store.add_folder(UF, "Legacy")
live["col"] = AnkiCol({9: {"!Library::Legacy"}}, registry={"!Library::Legacy"})
act.remove_empty_folder("Legacy")
check("an empty folder beside a legacy PDF that stores its tag: the PDF keeps it",
      live["col"].notes[9] == {"!Library::Legacy"}, str(live["col"].notes))

section("a PDF leaving a SHARED tag never takes the keeper's notes (round 1)")
add_pdf("s1", "Shared A.pdf", "Onc", "!Library::Onc::Shared_A")
add_pdf("s2", "Shared_A.pdf", "Onc", "!Library::Onc::Shared_A")  # legacy: both stored one tag
drive_store.rename_display(UF, "s2", "Shared B.pdf")  # renamed in Finder: no clash any more
live["col"] = AnkiCol({1: {"!Library::Onc::Shared_A"}, 2: {"!Library::Onc::Shared_A"}})
_real_cached = ts._cached_matches_many
ts._cached_matches_many = lambda safes, cfg: {s: [(2, 0.99)] for s in safes}
ts.sync_after_folder_rename(None, ["s2"])
check("the keeper's note does not get the renamed PDF's tag",
      "!Library::Onc::Shared_B" not in live["col"].notes[1], str(live["col"].notes))
check("...the renamed PDF's tag is built from ITS matches",
      "!Library::Onc::Shared_B" in live["col"].notes[2], str(live["col"].notes))
check("...and the keeper's tag is untouched", "!Library::Onc::Shared_A" in live["col"].notes[1])
ts.set_stored_tag("s2", "!Library::Onc::Shared_A")
live["col"] = AnkiCol({1: {"!Library::Onc::Shared_A"}, 2: {"!Library::Onc::Shared_A"}})
ts._cached_matches_many = lambda safes, cfg: {s: None for s in safes}
ts.sync_after_rename(None, "s2")
check("cold cache: nothing is copied, the new tag is registered empty",
      "!Library::Onc::Shared_B" not in live["col"].notes[1] | live["col"].notes[2]
      and "!Library::Onc::Shared_B" in live["col"].tags.all(), str((live["col"].notes, live["col"].tags.all())))
ts._cached_matches_many = _real_cached

section("the clash check fails CLOSED (round 1)")
_real_layout = ts.library_layout


def _broken():
    raise OSError("drive.json unreadable")


ts.library_layout = _broken
_n = len(ops)
ts.sync_after_matches(None, "lec", [(2, 0.99)])
check("a clash check that cannot read the Library writes no tag", len(ops) == _n, str(len(ops) - _n))
ts.library_layout = _real_layout

section("index_queue: ⟳ never queues a flagged PDF (round 1)")
iq = importlib.import_module("klaus_note.index_queue")
import types as _types  # noqa: E402

_saved_iq = {k: getattr(iq, k) for k in ("mw", "_manifest_paths", "_excluded_now", "stale_match_names",
                                         "card_index_from_scratch", "request", "needs_indexing")}
_queued: list = []
iq.mw = _types.SimpleNamespace(col=object())
iq._manifest_paths = lambda: [("ok", None), ("flagged", None)]
iq._excluded_now = lambda names: set()
iq.stale_match_names = lambda: []
iq.card_index_from_scratch = lambda cfg: False
iq.needs_indexing = lambda *a: True
iq.request = lambda jobs, announce=False: _queued.extend(jobs) or len(jobs)
_real_clashes = ts.library_clashes
ts.library_clashes = lambda: {"flagged": "“flagged.pdf” clashes."}
iq.refresh(None)
check("the flagged PDF is skipped, the other queued", [n for _k, n in _queued] == ["ok"], str(_queued))
ts.library_clashes = _real_clashes
for k, v in _saved_iq.items():
    setattr(iq, k, v)

section("sidebar: the row the PDF collides with carries the warning")
ls = importlib.import_module("klaus_note.library_sidebar")
add_pdf("w2", "Week_1.pdf", "Heme")  # a clash made in Finder, beside Week 1.pdf
ts.set_stored_tag("w1", "!Library::Heme::Week_1")
row = "!Library::Heme::Week_1"
check("the live index flags the row Week_1.pdf collides with",
      "Week_1.pdf" in (ls.library_index().get("clashes") or {}).get(row.casefold(), ""),
      str(ls.library_index().get("clashes")))
check("...the row keeps its owner, Week 1.pdf", ls.library_index()["safes"].get(row.casefold()) == "w1")
check("...its status is the clash (the warning icon)", "Week_1.pdf" in (ls.status_for(row) or ""), str(ls.status_for(row)))
check("...and its tooltip asks for a rename", "Rename" in (ls.tooltip_for(row) or ""), str(ls.tooltip_for(row)))
drive = {"folders": ["Anatomy"], "pdfs": {"ana": {"folder": None, "display": "Anatomy.pdf"},
                                          "lec": {"folder": "Anatomy", "display": "Lecture.pdf"}}}
prefs = {"ana": {"tag": "!Library::Anatomy"}, "lec": {"tag": "!Library::Anatomy::Lecture"}}
try:
    idx = ls.build_index(drive, prefs, clashes={"ana": "“Anatomy.pdf” clashes."})
except TypeError as exc:
    idx = {"error": str(exc)}
check("the folder row stays a folder (the legacy PDF tag is not the PDF's row)",
      idx.get("safes", {}).get("!library::anatomy") is None
      and idx.get("labels", {}).get("!library::anatomy") == "Anatomy", str(idx))
check("...and carries the clash message", "“Anatomy.pdf” clashes." in (idx.get("clashes") or {}).get("!library::anatomy", ""),
      str(idx))

raise SystemExit(report())
