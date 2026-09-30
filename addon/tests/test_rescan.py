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
      summary["moved"] == ["blood"] and ph.load_library_map(uf)["blood"] == "W1/02-ELO-Intro to Blood.pdf",
      str(summary))
check("the new lecture is imported", len(summary["ingested"]) == 1, str(summary))
again = ph.rescan_root(uf, root, {}, ph.prepare_rescan(uf, root))
check("settled: a second pass moves and imports nothing",
      again["moved"] == [] and again["ingested"] == [], str(again))

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
check("a running scan is a task", [t.key for t in tasks.snapshot()] == ["rescan"], str(tasks.snapshot()))
held[-1].success({})
check("...gone when it finishes", tasks.snapshot() == [], str(tasks.snapshot()))
pd5.start_library_rescan()
held[-1].fail(RuntimeError("disk"))
check("...and when it fails", tasks.snapshot() == [], str(tasks.snapshot()))

_init = open("klausmate/__init__.py", encoding="utf-8").read()
check("profile open starts the background rescan",
      "_pdf_drive.start_library_rescan()" in _init and "_pdf_drive.rescan_library_root()" not in _init)

raise SystemExit(report())
