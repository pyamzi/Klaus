"""K-309: the folder scan survives a bulk rename in Finder.

Renaming every lecture at once (adding "06-L-" prefixes) left no
basename to match, so plan_rescan called the whole batch ambiguous and
neither moved nor ingested anything for a week. Matching by text fixes
it; the reading and OCR moved to a background op so it cannot freeze
Anki at profile open.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_rescan.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
sys.modules["klausmate"].get_config = lambda: {}
ph = importlib.import_module("klausmate.pdf_handler")
plan = ph.plan_rescan
fp = ph.page_fingerprint

# ------------------------------------------------------------ pure plan

section("text pairs what a bulk rename left unmatched")
mapping = {"blood": "W1/01-Intro to Blood.pdf", "cbc": "W1/03-Intro to CBC.pdf",
           "anemic": "W1/Approach to Anemic Patient.pdf"}
disk = ["W1/02-ELO-Intro to Blood.pdf", "W1/04-L-Intro to CBC.pdf",
        "W1/06-L-Approach to Anemic Patient.pdf", "W1/11-ELO-Splenomegaly.pdf",
        "W1/Additional/02-Anemia Algorithms.pdf"]
text = {"blood": ["blood is a tissue", "plasma"], "cbc": ["the cbc", "indices", "smear"],
        "anemic": ["approach to anemia"]}
fps = {
    "missing": {s: fp(p) for s, p in text.items()},
    "new": {
        disk[0]: fp(["Blood  is a TISSUE", "plasma"]),
        disk[1]: fp(["the cbc", "indices", "smear"]),
        disk[2]: fp(["approach to anemia"]),
        disk[3]: fp(["a teenage girl"]),
        disk[4]: fp(["algorithms", "more"]),
    },
}
before = plan(mapping, disk)
check("sanity: by name alone the batch is ambiguous and nothing happens",
      before["ambiguous"] and before["moves"] == {} and before["ingestable"] == [])
p = plan(mapping, disk, fps)
check("the three renames are recognised by their text",
      p["moves"] == {"blood": disk[0], "cbc": disk[1], "anemic": disk[2]}, str(p))
check("the two genuinely new files are imported", p["ingestable"] == [disk[3], disk[4]], str(p))
check("nothing ambiguous, nothing missing", not p["ambiguous"] and p["missing"] == [], str(p))

section("never guessed")
p = plan({"a": "a.pdf", "b": "b.pdf"}, ["c.pdf", "d.pdf"],
         {"missing": {"a": fp(["same"]), "b": fp(["same"])}, "new": {"c.pdf": fp(["same"]), "d.pdf": fp(["x"])}})
check("two missing PDFs with the same text claim nothing", p["moves"] == {}, str(p))
p = plan({"a": "a.pdf"}, ["b.pdf"], {"missing": {"a": fp(["one"])}, "new": {"b.pdf": fp(["two"])}})
check("a lone missing/new pair whose texts differ is not a rename",
      p["moves"] == {} and p["missing"] == ["a"] and p["ingestable"] == ["b.pdf"], str(p))
p = plan({"a": "a.pdf"}, ["b.pdf"], {"missing": {"a": fp(["one"])}, "new": {"b.pdf": None}})
check("...but with no text to compare, the lone pair is still the rename", p["moves"] == {"a": "b.pdf"})
p = plan({"a": "a.pdf", "z": "z.pdf"}, ["b.pdf", "c.pdf"],
         {"missing": {"a": fp(["one"]), "z": fp(["zz"])}, "new": {"b.pdf": None, "c.pdf": fp(["new"])}})
check("an unreadable new file is held while PDFs are missing; readable ones import",
      p["ingestable"] == ["c.pdf"] and p["ambiguous"], str(p))
check("a page-count change is a different document",
      not ph._same_document(fp(["a", "b"]), fp(["a", "b", "c"])))
check("one OCR-repaired page does not break the match",
      ph._same_document(fp(["garbl3d", "page two", "page three"]), fp(["repaired", "page two", "page three"])))

# ------------------------------------------------------------ prepared apply

section("prepare off the main thread, apply on it")
uf = tempfile.mkdtemp(prefix="klaus-k309-uf-")
root = tempfile.mkdtemp(prefix="klaus-k309-root-")
os.makedirs(os.path.join(uf, "contexts"))
os.makedirs(os.path.join(root, "W1"))
files = {"W1/02-ELO-Intro to Blood.pdf": ["blood is a tissue", "plasma"],
         "W1/11-ELO-Splenomegaly.pdf": ["a teenage girl"]}
for rel in files:
    open(os.path.join(root, rel), "wb").write(b"%PDF")
json.dump({"pages": ["blood is a tissue", "plasma"], "page_count": 2},
          open(os.path.join(uf, "contexts", "blood.json"), "w"))
open(os.path.join(uf, "contexts", "blood.txt"), "w").write("blood")
ph.save_library_map(uf, {"blood": "W1/01-Intro to Blood.pdf"})
reads, repairs = [], []
ph.extract_pages = lambda path: (reads.append(os.path.relpath(path, root)), files[os.path.relpath(path, root)])[1]
ph.repair_garbled_pages = lambda path, pages, **k: (repairs.append(os.path.relpath(path, root)), pages)[1]

prepared = ph.prepare_rescan(uf, root)
check("each new file is read once", sorted(reads) == sorted(files), str(reads))
check("only the file to import is OCR-repaired", repairs == ["W1/11-ELO-Splenomegaly.pdf"], str(repairs))
del reads[:]
summary = ph.rescan_root(uf, root, {}, prepared)
check("applying reads no PDF again", reads == [], str(reads))
check("the renamed lecture keeps its identity",
      summary["moved"] == {"blood": os.path.join(root, "W1/02-ELO-Intro to Blood.pdf")}
      and ph.load_library_map(uf)["blood"] == "W1/02-ELO-Intro to Blood.pdf",
      str(summary))
check("the new lecture is imported", len(summary["ingested"]) == 1, str(summary))
again = ph.rescan_root(uf, root, {}, ph.prepare_rescan(uf, root))
check("settled: a second pass moves and imports nothing",
      again["moved"] == {} and again["ingested"] == [], str(again))

# ------------------------------------------------------------ Task 5a

section("rescan reports moved, missing, back and changed in one walk")
_stub_extract, _stub_repair = ph.extract_pages, ph.repair_garbled_pages
ph.extract_pages = lambda path: open(path, encoding="utf-8").read().split("|")
ph.repair_garbled_pages = lambda path, pages, **k: pages
ps5 = importlib.import_module("klausmate.page_store")
_real_ensure = ps5.ensure_records
ensured = []
ps5.ensure_records = lambda uf_, safe, path, pages: ensured.append((safe, path, list(pages)))
uf5 = tempfile.mkdtemp(prefix="klaus-t5-uf-")
root5 = tempfile.mkdtemp(prefix="klaus-t5-root-")
os.makedirs(os.path.join(uf5, "contexts"))
os.makedirs(os.path.join(root5, "Heme & Onc"))
seed = {"Lecture": ("Lecture.pdf", "lecture one|lecture two"),
        "Week": ("Heme & Onc/Week 2.pdf", "week two|anemia"),
        "Closed": ("Closed.pdf", "closed one|closed two"),
        "Gone": ("Gone.pdf", "gone one")}


def put(rel, text):
    with open(os.path.join(root5, rel), "w", encoding="utf-8") as fh:
        fh.write(text)


for _safe, (_rel, _text) in seed.items():
    put(_rel, _text)
    json.dump({"pages": _text.split("|"), "page_count": len(_text.split("|"))},
              open(os.path.join(uf5, "contexts", _safe + ".json"), "w"))
    open(os.path.join(uf5, "contexts", _safe + ".txt"), "w").write(_text)
ph.save_library_map(uf5, {s: rel for s, (rel, _t) in seed.items()})


def scan():
    return ph.rescan_root(uf5, root5, {}, ph.prepare_rescan(uf5, root5))


p5 = ph.prepare_rescan(uf5, root5)
check("prepare returns root_ok, the walk and an empty changed set when nothing is new",
      p5.get("root_ok") is True and p5.get("disk") == ph.walk_root(root5) and p5.get("changed") == {}, str(p5))
s5 = ph.rescan_root(uf5, root5, {}, p5)
check("a settled folder reports nothing",
      (s5["moved"], s5["missing"], s5["back"], s5["changed_text"]) == ({}, [], [], []), str(s5))

walks = []
_real_walk = ph.walk_root
ph.walk_root = lambda r: (walks.append(r), _real_walk(r))[1]
new_week = "Heme & Onc/Wk 2 – Anämie & Blut.pdf"
os.rename(os.path.join(root5, "Lecture.pdf"), os.path.join(root5, "lecture.pdf"))
os.rename(os.path.join(root5, seed["Week"][0]), os.path.join(root5, new_week))
s5 = scan()
ph.walk_root = _real_walk
check("a full prepare + apply walks the folder once", len(walks) == 1, str(walks))
check("case-only rename and a name with spaces, & and non-ASCII resolve to the new path",
      s5["moved"] == {"Lecture": os.path.join(root5, "lecture.pdf"),
                      "Week": os.path.join(root5, new_week)}, str(s5))
check("...and the next bake writes to the new name",
      ph._working_pdf_path(uf5, "Lecture", root5) == os.path.join(root5, "lecture.pdf")
      and ph._working_pdf_path(uf5, "Week", root5) == os.path.join(root5, new_week))
check("a rename is neither missing nor ingested", s5["missing"] == [] and s5["ingested"] == [], str(s5))

os.remove(os.path.join(root5, "Gone.pdf"))
s5 = scan()
check("a deleted file is missing and persisted",
      s5["missing"] == ["Gone"] and ph.load_missing(uf5) == {"Gone"}, str(s5))
check("the missing set lives under __missing__ beside the stats",
      json.load(open(os.path.join(uf5, "library_stats.json")))["__missing__"] == ["Gone"]
      and "__missing__" not in ph.load_library_stats(uf5))
ph.record_stat(uf5, "Closed", ph.file_stat(os.path.join(root5, "Closed.pdf")))
check("record_stat keeps the missing set", ph.load_missing(uf5) == {"Gone"})
s5 = scan()
check("still gone: missing again, not back", s5["missing"] == ["Gone"] and s5["back"] == [], str(s5))
put("Gone.pdf", "gone one")
s5 = scan()
check("the file reappears: back, and cleared",
      s5["back"] == ["Gone"] and s5["missing"] == [] and ph.load_missing(uf5) == set(), str(s5))

section("Library root unavailable")
os.remove(os.path.join(root5, "Gone.pdf"))
scan()
map_before = ph.load_library_map(uf5)
away = root5 + "-away"
os.rename(root5, away)
p5 = ph.prepare_rescan(uf5, root5)
check("prepare: root_ok False and nothing else computed", p5 == {"root_ok": False}, str(p5))
s5 = ph.rescan_root(uf5, root5, {}, p5)
check("apply: nothing missing, nothing moved", s5["missing"] == [] and s5["moved"] == {} and s5["back"] == [],
      str(s5))
s5 = ph.rescan_root(uf5, root5, {})
check("without prepared too", s5["missing"] == [] and s5["moved"] == {}, str(s5))
check("the persisted missing set and the mapping are untouched",
      ph.load_missing(uf5) == {"Gone"} and ph.load_library_map(uf5) == map_before)
os.rename(away, root5)
put("Gone.pdf", "gone one")
scan()

section("a file mapped between prepare and apply is not missing")
p5 = ph.prepare_rescan(uf5, root5)
put("Late.pdf", "late")
m5 = ph.load_library_map(uf5)
m5["Late"] = "Late.pdf"
ph.save_library_map(uf5, m5)
s5 = ph.rescan_root(uf5, root5, {}, p5)
check("present on disk though the walk predates it", "Late" not in s5["missing"], str(s5))

section("a closed file changed outside Klaus")
del ensured[:]
put("Closed.pdf", "edited elsewhere|closed two|page three")
p5 = ph.prepare_rescan(uf5, root5)
check("prepare re-extracts its pages",
      p5["changed"] == {"Closed": ["edited elsewhere", "closed two", "page three"]}, str(p5["changed"]))
s5 = ph.rescan_root(uf5, root5, {}, p5)
check("its text changed", s5["changed_text"] == ["Closed"], str(s5))
check("context json and txt rewritten as ingest writes them",
      ph.load_pages(uf5, "Closed") == ["edited elsewhere", "closed two", "page three"]
      and open(os.path.join(uf5, "contexts", "Closed.txt")).read()
      == "edited elsewhere\n\nclosed two\n\npage three")
check("page records refreshed once",
      ensured == [("Closed", os.path.join(root5, "Closed.pdf"), ["edited elsewhere", "closed two", "page three"])],
      str(ensured))
_st = ph.file_stat(os.path.join(root5, "Closed.pdf"))
check("its new stat is recorded", ph.load_library_stats(uf5)["Closed"] == [_st[2], _st[1]])
check("a second pass reports nothing", scan()["changed_text"] == [])
put("Closed.pdf", "edited   elsewhere |closed two|page three\n")
s5 = scan()
check("whitespace-only change: records refreshed, text not changed",
      s5["changed_text"] == [] and len(ensured) == 2, str(s5))
put("Closed.pdf", "baked by klaus|closed two|page three|x")
ph.record_stat(uf5, "Closed", ph.file_stat(os.path.join(root5, "Closed.pdf")))
check("Klaus's own write (stat recorded) is not reported", ph.prepare_rescan(uf5, root5)["changed"] == {})
ds5 = importlib.import_module("klausmate.doc_sync")
ds5._paths["Closed"] = os.path.join(root5, "Closed.pdf")
put("Closed.pdf", "open in a reader|y")
check("an open file is left to its reader", ph.prepare_rescan(uf5, root5)["changed"] == {})
del ds5._paths["Closed"]

ph.extract_pages, ph.repair_garbled_pages = _stub_extract, _stub_repair
ps5.ensure_records = _real_ensure

section("the background op never holds the collection")
pdf_drive = importlib.import_module("klausmate.pdf_drive")
ops = []


class FakeQueryOp:
    def __init__(self, parent=None, op=None, success=None):
        self.op, self.ok, self.no_col = op, success, False
        ops.append(self)

    def failure(self, fn):
        return self

    def without_collection(self):
        self.no_col = True
        return self

    def run_in_background(self):
        self.ok(self.op(None))


pdf_drive.QueryOp = FakeQueryOp
pdf_drive.mw = type("MW", (), {"col": None})()
ph._live_library_root = lambda: root
sys.modules["klausmate"].USER_FILES = uf
applied = []
pdf_drive.rescan_library_root = lambda prepared=None: (applied.append(prepared), {"moved": []})[1]
done = []
pdf_drive.start_library_rescan(done.append)
check("one op, without the collection", len(ops) == 1 and ops[0].no_col)
check("its result is applied back on the main thread", len(applied) == 1 and done == [{"moved": []}])
section("an imported PDF gets what every import gets")
calls = []
ps = importlib.import_module("klausmate.page_store")
iq = importlib.import_module("klausmate.index_queue")
tsync = importlib.import_module("klausmate.tag_sync")
ps.ensure_records = lambda uf_, safe, path, pages: calls.append(("pages", safe))
iq.on_pdf_imported = lambda safe: calls.append(("index", safe))
tsync._schedule_reconcile = lambda: calls.append(("tag", None))  # scheduled, not inline: our renames land first
pdf_drive.mw = type("MW", (), {"col": object()})()
pdf_drive._after_ingest(["splen"])
check("page records, auto-index and a tag for the new PDF",
      calls == [("pages", "splen"), ("index", "splen"), ("tag", None)], str(calls))
del calls[:]
pdf_drive.rescan_library_root = lambda prepared=None: {"moved": [], "ingested": ["x"], "tree_changed": []}
pdf_drive._library_changed = lambda: None
pdf_drive.start_library_rescan()
check("the background rescan hands what it ingested on", ("index", "x") in calls, str(calls))

section("deleting a folder never takes the user's own files with it")
import importlib as _il  # noqa: E402
pdf_drive = _il.reload(_il.import_module("klausmate.pdf_drive"))
ph._live_library_root = lambda: root
sys.modules["klausmate"].USER_FILES = uf
trashed = []
pdf_drive._move_to_trash = lambda path: trashed.append(os.path.relpath(path, root))
os.makedirs(os.path.join(root, "Notes only"))
open(os.path.join(root, "Notes only", "02-ELO-Intro to Blood.md"), "w").write("my notes")
pdf_drive.delete_folder("Notes only")
check("a folder holding notes (no PDFs) stays on disk",
      trashed == [] and os.path.isfile(os.path.join(root, "Notes only", "02-ELO-Intro to Blood.md")))
os.makedirs(os.path.join(root, "Empty"))
open(os.path.join(root, "Empty", ".DS_Store"), "w").write("")
pdf_drive.delete_folder("Empty")
check("an empty folder goes to the Trash", trashed == ["Empty"], str(trashed))
real_trash = _il.reload(_il.import_module("klausmate.pdf_drive"))._move_to_trash
os.makedirs(os.path.join(root, "Kept"))
open(os.path.join(root, "Kept", "a.md"), "w").write("x")
real_trash(os.path.join(root, "Kept"))  # the stub Qt has no Trash: the fallback runs
check("with no Trash, a non-empty directory is left alone (never rmtree)",
      os.path.isfile(os.path.join(root, "Kept", "a.md")))

section("which PDFs are being indexed")
iq._queue.clear()
iq._queue.enqueue((iq.JOB_PDF, "a"))
iq._queue.enqueue((iq.JOB_CARDS, ""))
iq._current = (iq.JOB_PDF, "b")
check("pending_names is the running PDF plus the queued ones",
      iq.pending_names() == {"a", "b"}, str(iq.pending_names()))
iq._queue.clear()
iq._current = None

section("the folder scan shows in the status bar (status bar 5/6)")
tasks = importlib.import_module("klausmate.tasks")
tasks.run_on_main = lambda fn: fn()
tasks.clear()
held = []


class HoldOp:
    """Keeps the op pending so the test can see the task while it runs."""

    def __init__(self, parent=None, op=None, success=None):
        self.success, self.fail = success, None
        held.append(self)

    def failure(self, fn):
        self.fail = fn
        return self

    def without_collection(self):
        return self

    def run_in_background(self):
        pass


pd5 = importlib.import_module("klausmate.pdf_drive")
pd5.QueryOp = HoldOp
pd5.mw = type("MW", (), {"col": object()})()
pd5._rescan.update(running=False, again=False)
ph._live_library_root = lambda: root
pd5.rescan_library_root = lambda prepared=None: {"moved": []}
pd5.start_library_rescan()
check("a running scan stays out of the status bar", tasks.snapshot() == [], str(tasks.snapshot()))
held[-1].success({})
check("...and so does a finished one", tasks.snapshot() == [], str(tasks.snapshot()))
pd5.start_library_rescan()
held[-1].fail(RuntimeError("disk"))
check("...and a failure stays in the bar with its reason",
      [(t.key, t.error, "disk" in t.message) for t in tasks.snapshot()] == [("rescan", True, True)], str(tasks.snapshot()))
tasks.clear()

_init = open("klausmate/__init__.py", encoding="utf-8").read()
check("profile open starts the background rescan",
      "_pdf_drive.start_library_rescan()" in _init and "_pdf_drive.rescan_library_root()" not in _init)

raise SystemExit(report())
