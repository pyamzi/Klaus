"""Tests for klausmate.page_store (K-221, Task 1 of the page-store-and-
api-clients plan).

One record per (PDF, page): slide text plus transcript segments, keyed by
a path+size+mtime digest so a replaced PDF gets a fresh directory. Covers
digest/path derivation, ensure_records' idempotent slide-text refresh that
never touches segments, append_segment's time-ordered merge, combined_text/
text_hash, page_texts for the index, corrupt-record tolerance, and the
subscribe/unsubscribe notification contract.

render_page_png (QtPdf, below the module's aqt-free divider) is not
exercised here: it is a verbatim copy of page_ocr.render_page_png (already
covered by tests/test_page_ocr.py), and none of this file's checks need a
real PDF renderer to exercise the JSON record store.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_page_store.py
"""
from __future__ import annotations

import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

import os, tempfile, json
ps = importlib.import_module("klausmate.page_store")
root = tempfile.mkdtemp(prefix="klaus-pages-")
pdf = os.path.join(root, "lec.pdf"); open(pdf, "wb").write(b"%PDF-1.4 fake")

section("digest and paths")
d = ps.digest12(pdf)
check("digest12 is 12 hex chars from path+size+mtime", len(d) == 12 and all(c in "0123456789abcdef" for c in d))
check("record_path lands under pages/<safe>/<digest>/<page:04d>.json",
      ps.record_path(root, "lec", pdf, 3).endswith(os.path.join("pages", "lec", d, "0003.json")))
os.utime(pdf, (1, 1))
check("a changed mtime is a new directory", ps.digest12(pdf) != d)

section("ensure_records fills slide text once, never touches segments")
n = ps.ensure_records(root, "lec", pdf, ["Slide one text", "", "Slide three"])
check("one record per page, three written", n == 3)
rec = ps.load_record(root, "lec", pdf, 0)
check("slide_text stored, no segments, version 1",
      rec["slide_text"] == "Slide one text" and rec["segments"] == [] and rec["version"] == 1)
ps.append_segment(root, "lec", pdf, 0, 0.0, 30.0, "the lecturer said this")
n2 = ps.ensure_records(root, "lec", pdf, ["Slide one text CHANGED", "", "Slide three"])
rec = ps.load_record(root, "lec", pdf, 0)
check("ensure_records is idempotent for segments and refreshes slide_text",
      rec["slide_text"] == "Slide one text CHANGED" and len(rec["segments"]) == 1)

section("combined_text and text_hash")
check("combined_text is slide text, blank line, segments in time order",
      ps.combined_text(rec) == "Slide one text CHANGED\n\nthe lecturer said this")
h1 = ps.text_hash(rec)
ps.append_segment(root, "lec", pdf, 0, 30.0, 60.0, "and then this")
rec2 = ps.load_record(root, "lec", pdf, 0)
check("a new segment changes the hash; 16 hex chars", ps.text_hash(rec2) != h1 and len(h1) == 16)
check("segments keep time order even when appended out of order",
      ps.combined_text(ps.append_segment(root, "lec", pdf, 0, 10.0, 20.0, "middle")).split("\n\n")[1]
      == "the lecturer said this\nmiddle\nand then this")
rec2 = ps.load_record(root, "lec", pdf, 0)  # refresh: the "middle" append above changed page 0 on disk

section("page_texts for the index")
rows = ps.page_texts(root, "lec", pdf, 3)
check("one row per page, 1-based, (page, hash, text); empty page has empty text",
      [r[0] for r in rows] == [1, 2, 3] and rows[1][2] == "" and rows[0][1] == ps.text_hash(rec2))

section("corrupt record reads as empty, subscribe notifies")
open(ps.record_path(root, "lec", pdf, 2), "w").write("{not json")
check("corrupt → empty record, no exception", ps.load_record(root, "lec", pdf, 2)["slide_text"] == "")
seen = []
unsub = ps.subscribe(lambda safe, page: seen.append((safe, page)))
ps.append_segment(root, "lec", pdf, 1, 0.0, 1.0, "x")
unsub()
ps.append_segment(root, "lec", pdf, 1, 1.0, 2.0, "y")
check("subscriber saw exactly the one append before unsubscribe", seen == [("lec", 1)])
def _boom(*a): raise RuntimeError("boom")
ps.subscribe(_boom)
ps.append_segment(root, "lec", pdf, 1, 2.0, 3.0, "z")
check("a raising subscriber is logged, never breaks the append",
      len(ps.load_record(root, "lec", pdf, 1)["segments"]) == 3)
raise SystemExit(report())
