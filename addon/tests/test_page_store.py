"""Tests for klausmate.page_store (K-221, Task 1 of the page-store-and-
api-clients plan).

One record per (PDF, page): slide text plus transcript segments, keyed by
a path+size+mtime digest so a replaced PDF gets a fresh directory. Covers
digest/path derivation, ensure_records' idempotent slide-text refresh that
never touches segments, append_segment's time-ordered merge, combined_text/
text_hash, page_texts for the index, corrupt-record tolerance, and the
subscribe/unsubscribe notification contract.

render_page_png (QtPdf, below the module's aqt-free divider) is covered at
the bottom, against a real one-page PDF. That check moved here from
tests/test_page_ocr.py, which was deleted with page_ocr.py on 2026-09-15
and took the ONLY test of this function with it (K-228 — the mutation
audit found the hole by gutting the body and watching this file still
pass). It now pins the SCALE, read out of the PNG's own IHDR, since a
gutted render returning any PNG at all passed the old "starts with the
magic bytes" check. SKIPs, loudly, only where PyQt6.QtPdf is missing.

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

section("render (real QtPdf, offscreen)")


def _blank_pdf(dest: str, width: int = 300, height: int = 200) -> str:
    """One blank page, written by hand.

    The version of this check in tests/test_page_ocr.py built the page with
    the vendored pypdf — which THIS machine's python3 cannot import at all
    (vendor/pypdf wants typing_extensions from Anki's bundle), so restoring
    it verbatim would have restored a check that only ever prints SKIP: a
    vacuous pin by another name. A literal PDF has no such dependency and
    pdfium reads it fine.
    """
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R >>" % (width, height),
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(dest, "wb") as fh:
        fh.write(bytes(out))
    return dest


try:
    from PyQt6.QtPdf import QPdfDocument  # noqa: F401

    real = _blank_pdf(os.path.join(root, "blank.pdf"))
    png = ps.render_page_png(real, 0, long_edge=140)
    # PNG IHDR: width is bytes 16..20, height 20..24. 300x200 at long_edge
    # 140 is 140 wide — the pin is the SCALING, not just "some bytes came
    # back", or a gutted render that returned any PNG would pass.
    check("render_page_png returns a PNG with the long edge scaled to 140",
          png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100
          and int.from_bytes(png[16:20], "big") == 140)
    check("the DEFAULT long edge is LONG_EDGE (1400) — what the assistant sends",
          int.from_bytes(ps.render_page_png(real, 0)[16:20], "big") == ps.LONG_EDGE == 1400)
    try:
        ps.render_page_png(real, 5)
        check("a page past the end raises rather than returning junk", False)
    except RuntimeError as exc:
        check("a page past the end raises rather than returning junk", "6" in str(exc))
except ImportError as exc:
    print(f"  SKIP real render: {exc}")

raise SystemExit(report())
