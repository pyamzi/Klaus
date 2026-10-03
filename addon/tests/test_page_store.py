"""Tests for klaus_note.page_store (K-221, Task 1 of the page-store-and-
api-clients plan).

One record per (PDF, page): its slide text, keyed by the document's
identity so a replaced PDF gets a fresh directory. Covers digest/path
derivation, ensure_records' idempotent slide-text refresh, combined_text/
text_hash, page_texts for the index, and corrupt-record tolerance.

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

import os, tempfile, json, shutil
ps = importlib.import_module("klaus_note.page_store")
root = tempfile.mkdtemp(prefix="klaus-pages-")
pdf = os.path.join(root, "lec.pdf"); open(pdf, "wb").write(b"%PDF-1.4 fake")

section("digest and paths")
d = ps.digest12(pdf)
check("digest12 is 12 hex chars from path+size+mtime", len(d) == 12 and all(c in "0123456789abcdef" for c in d))
check("record_path lands under pages/<safe>/<digest>/<page:04d>.json",
      ps.record_path(root, "lec", pdf, 3).endswith(os.path.join("pages", "lec", d, "0003.json")))
os.utime(pdf, (1, 1))
check("a changed mtime is a new directory", ps.digest12(pdf) != d)

section("ensure_records fills slide text once")
n = ps.ensure_records(root, "lec", pdf, ["Slide one text", "", "Slide three"])
check("one record per page, three written", n == 3)
rec = ps.load_record(root, "lec", pdf, 0)
check("slide_text stored, version 1",
      rec["slide_text"] == "Slide one text" and rec["version"] == 1)
n2 = ps.ensure_records(root, "lec", pdf, ["Slide one text", "", "Slide three"])
rec = ps.load_record(root, "lec", pdf, 0)
check("ensure_records is idempotent for unchanged text — no rewrite",
      n2 == 0 and rec["slide_text"] == "Slide one text")

section("combined_text and text_hash")
check("combined_text is the stripped slide text",
      ps.combined_text({"slide_text": "  Slide one text \n"}) == "Slide one text")
h1 = ps.text_hash(rec)
check("text_hash is 16 hex chars and follows the text",
      len(h1) == 16 and ps.text_hash({"slide_text": "other"}) != h1)

section("page_texts for the index")
rows = ps.page_texts(root, "lec", pdf, 3)
check("one row per page, 1-based, (page, hash, text); empty page has empty text",
      [r[0] for r in rows] == [1, 2, 3] and rows[1][2] == "" and rows[0][1] == ps.text_hash(rec))

section("corrupt record reads as empty")
open(ps.record_path(root, "lec", pdf, 2), "w").write("{not json")
check("corrupt → empty record, no exception", ps.load_record(root, "lec", pdf, 2)["slide_text"] == "")

section("text_digest: the document's own identity (PR1 review fix)")
check("12 hex chars, like digest12",
      len(ps.text_digest(["a", "b"])) == 12
      and all(c in "0123456789abcdef" for c in ps.text_digest(["a", "b"])))
check("whitespace differences collapse to the same digest",
      ps.text_digest(["a   b\nc"]) == ps.text_digest(["a b c"]))
check("different text is a different digest",
      ps.text_digest(["a"]) != ps.text_digest(["b"]))

section("identity survives a bake (size/mtime change) and a move")
id_root = tempfile.mkdtemp(prefix="klaus-pages-identity-")
id_pdf = os.path.join(id_root, "orig.pdf")
open(id_pdf, "wb").write(b"%PDF-1.4 original bytes")
ps.ensure_records(id_root, "idpdf", id_pdf, ["Only page text"])
dir_before = ps.record_dir(id_root, "idpdf", id_pdf)
digest_before = ps.digest12(id_pdf)

# Simulate bake_annotations' os.replace: same path, different bytes/size/mtime.
with open(id_pdf, "ab") as f:
    f.write(b"MORE-BYTES-FROM-A-BAKE")
os.utime(id_pdf, (1000, 1000))
check("a bake changes the legacy path-digest (so the pin actually exercises the fix)",
      ps.digest12(id_pdf) != digest_before)
check("...but record_dir still resolves to the SAME directory",
      ps.record_dir(id_root, "idpdf", id_pdf) == dir_before)
check("...and the record written before the bake is still there",
      ps.load_record(id_root, "idpdf", id_pdf, 0)["slide_text"] == "Only page text")

moved_pdf = os.path.join(id_root, "moved.pdf")
os.rename(id_pdf, moved_pdf)
check("a move (new path) resolves to the same directory too",
      ps.record_dir(id_root, "idpdf", moved_pdf) == dir_before)
check("...record still there under the new path",
      ps.load_record(id_root, "idpdf", moved_pdf, 0)["slide_text"] == "Only page text")

section("a different pages list is a replaced document, not a refresh")
n_replaced = ps.ensure_records(id_root, "idpdf", moved_pdf, ["Totally different content"])
check("ensure_records wrote the one page of the new document", n_replaced == 1)
new_dir = ps.record_dir(id_root, "idpdf", moved_pdf)
check("...resolves to a FRESH directory (not the bake/move survivor above)",
      new_dir != dir_before)
new_rec = ps.load_record(id_root, "idpdf", moved_pdf, 0)
check("...whose page 0 holds the new text — a different document, not a correction",
      new_rec["slide_text"] == "Totally different content")
check("...and the OLD directory is left on disk, not deleted (delete_context's job)",
      os.path.isdir(dir_before))

section("a legacy digest12(path) directory with no pointer is adopted")
leg_root = tempfile.mkdtemp(prefix="klaus-pages-legacy-")
leg_pdf = os.path.join(leg_root, "legacy.pdf")
open(leg_pdf, "wb").write(b"%PDF-1.4 legacy")
leg_digest = ps.digest12(leg_pdf)
leg_dir = os.path.join(leg_root, "pages", "legpdf", leg_digest)
os.makedirs(leg_dir, exist_ok=True)
with open(os.path.join(leg_dir, "0000.json"), "w", encoding="utf-8") as f:
    json.dump({"version": 1, "slide_text": "pre-existing Plan 1 text",
               "segments": [], "updated_at": 0.0}, f)
pointer_path = os.path.join(leg_root, "pages", "legpdf", "current")
check("no pointer exists yet", not os.path.isfile(pointer_path))
rec_legacy = ps.load_record(leg_root, "legpdf", leg_pdf, 0)
check("the legacy record is visible through the new resolution, its "
      "retired segments key dropped on read (K-314)",
      rec_legacy["slide_text"] == "pre-existing Plan 1 text" and "segments" not in rec_legacy)
check("...and reading it adopted the legacy dir: the pointer is now written",
      os.path.isfile(pointer_path)
      and open(pointer_path, encoding="utf-8").read().strip() == leg_digest)

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

section("__init__.import_pdf_file seeds page records at import (PR1 review fix)")
# The only production ensure_records call used to live inside
# retention.ensure_pdf_index (the paid index run) — with auto-index off,
# no OpenAI key, or a failed index, the assistant got no slide text even
# though contexts/<safe>.json already had it. import_pdf_file is
# __init__.py's own funnel (every import surface — editor drop bar,
# deck-screen drop, drive window — returns through it), so this needs
# the REAL __init__.py loaded under real (offscreen) Qt — anki_stubs'
# own exec_klaus_note_under_qt, the same recipe test_slot_guards.py and
# test_bridge_reentrancy.py hand-rolled before the helper existed. This
# runs last in this FILE (not shared with test_klaus_note.py's own much
# larger process, which by this point has already imported half the
# addon under its own bootstrap — exec_klaus_note_under_qt needs a clean
# sys.modules to bind curation/tag_sync/etc. to the fresh stubs it just
# installed, and only a small, single-purpose file like this one gives
# it that).
_ipf_uf = tempfile.mkdtemp(prefix="klaus_test_importpdf_")
_ipf_raw = os.path.join(_ipf_uf, "Lecture One.pdf")
with open(_ipf_raw, "wb") as _f:
    _f.write(b"%PDF-1.4\n%%EOF")
_ipf_module = None
try:
    from anki_stubs import exec_klaus_note_under_qt

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _ipf_module = exec_klaus_note_under_qt(_ipf_uf)
except Exception as exc:
    print(f"  SKIP import_pdf_file (needs real offscreen Qt): {exc}")
if _ipf_module is not None:
    _ipf_module.pdf_handler.extract_pages = lambda p: ["page one text", "page two text"]
    _ipf_name = _ipf_module.import_pdf_file(_ipf_raw)
    check("import_pdf_file returns the safe name", _ipf_name == "Lecture_One", str(_ipf_name))
    _ipf_rec0 = ps.load_record(_ipf_uf, _ipf_name, _ipf_raw, 0)
    _ipf_rec1 = ps.load_record(_ipf_uf, _ipf_name, _ipf_raw, 1)
    check("a page record exists for every page right after import — no "
          "index run needed for the assistant to have slide text",
          _ipf_rec0["slide_text"] == "page one text"
          and _ipf_rec1["slide_text"] == "page two text",
          f"{_ipf_rec0}, {_ipf_rec1}")


section("a legacy directory holding the SAME document migrates with its records; a different document does not")
_uf = tempfile.mkdtemp(prefix="klaus-pages-migrate-")
_pdf = os.path.join(_uf, "lec.pdf")
with open(_pdf, "wb") as _f:
    _f.write(b"%PDF-1.4 legacy")
_pages = ["Slide one", "Slide  two"]
_legacy_dir = os.path.join(_uf, ps.SUBDIR, "lec", ps.digest12(_pdf))
os.makedirs(_legacy_dir)
for _i, _text in enumerate(_pages):
    with open(os.path.join(_legacy_dir, f"{_i:04d}.json"), "w", encoding="utf-8") as _f:
        # updated_at 0.0 marks the file written under the legacy name:
        # page 0's text is unchanged, so ensure_records never rewrites it.
        json.dump({"slide_text": _text, "updated_at": 0.0}, _f)
ps.ensure_records(_uf, "lec", _pdf, ["Slide one", "Slide two"])  # same text, other whitespace
check("the pointer now names the text digest", ps._read_pointer(_uf, "lec") == ps.text_digest(_pages))
check("the legacy directory was renamed, not abandoned", not os.path.isdir(_legacy_dir))
check("the record written under the legacy name survives, not re-seeded fresh",
      ps.load_record(_uf, "lec", _pdf, 0) == {"slide_text": "Slide one", "updated_at": 0.0, "version": ps.VERSION})
ps.ensure_records(_uf, "lec", _pdf, ["A different deck", "Entirely"])
check("a different document repoints to a fresh directory",
      ps.load_record(_uf, "lec", _pdf, 0)["slide_text"] == "A different deck" and ps._read_pointer(_uf, "lec") == ps.text_digest(["A different deck", "Entirely"]))
check("the previous document's records are left on disk for delete_context",
      os.path.isdir(os.path.join(_uf, ps.SUBDIR, "lec", ps.text_digest(_pages))))
shutil.rmtree(_uf, ignore_errors=True)

section("an empty-slide_text legacy record migrates, not orphaned (M-15)")
_uf2 = tempfile.mkdtemp(prefix="klaus-pages-emptytext-")
_pdf2 = os.path.join(_uf2, "lec.pdf")
with open(_pdf2, "wb") as _f:
    _f.write(b"%PDF-1.4 emptytext")
_pages2 = ["Real slide one", "Real slide two"]
_legacy_dir2 = os.path.join(_uf2, ps.SUBDIR, "lec", ps.digest12(_pdf2))
os.makedirs(_legacy_dir2)
# Only page 1 has a record at all, and its slide_text is empty — written
# before ANY index run ever seeded slide_text. Page 0 has no record file
# yet. Both must be treated as "nothing to disagree with", not a
# mismatch, or the directory is orphaned.
with open(os.path.join(_legacy_dir2, "0001.json"), "w", encoding="utf-8") as _f:
    json.dump({"version": 1, "slide_text": "", "updated_at": 0.0}, _f)
ps.ensure_records(_uf2, "lec", _pdf2, _pages2)
check("the legacy directory migrated onto the text digest, not left orphaned",
      not os.path.isdir(_legacy_dir2) and ps._read_pointer(_uf2, "lec") == ps.text_digest(_pages2))
check("the real slide text from the index run is there too, on both pages",
      ps.load_record(_uf2, "lec", _pdf2, 0)["slide_text"] == "Real slide one"
      and ps.load_record(_uf2, "lec", _pdf2, 1)["slide_text"] == "Real slide two")
shutil.rmtree(_uf2, ignore_errors=True)

section("ensure_records leaves the pointer alone when the destination directory already exists (M-15)")
_uf3 = tempfile.mkdtemp(prefix="klaus-pages-collision-")
_pdf3 = os.path.join(_uf3, "lec.pdf")
with open(_pdf3, "wb") as _f:
    _f.write(b"%PDF-1.4 collision")
_pages3 = ["Collision slide one", "Collision slide two"]
_td3 = ps.text_digest(_pages3)
_base3 = os.path.join(_uf3, ps.SUBDIR, "lec3")
_old_dir3 = os.path.join(_base3, "oldhome0001")
os.makedirs(_old_dir3)
for _i, _text in enumerate(_pages3):
    with open(os.path.join(_old_dir3, f"{_i:04d}.json"), "w", encoding="utf-8") as _f:
        json.dump({"slide_text": _text}, _f)
ps._write_pointer(_uf3, "lec3", "oldhome0001")
# The migration target already has its OWN directory on disk (independent
# content) — os.replace onto it would raise, and the old bug repointed
# there anyway, orphaning old_dir's records behind an unreachable pointer.
_td_dir3 = os.path.join(_base3, _td3)
os.makedirs(_td_dir3)
_td_rec3 = {"slide_text": "already here", "updated_at": 0.0}
with open(os.path.join(_td_dir3, "0000.json"), "w", encoding="utf-8") as _f:
    json.dump(_td_rec3, _f)
ps.ensure_records(_uf3, "lec3", _pdf3, _pages3)
check("the pointer stays on the current directory, not moved onto the pre-existing target",
      ps._read_pointer(_uf3, "lec3") == "oldhome0001")
check("the current directory is untouched, not renamed away",
      os.path.isdir(_old_dir3))
check("the pre-existing target directory's own record is untouched (no merge, no overwrite)",
      json.load(open(os.path.join(_td_dir3, "0000.json"))) == _td_rec3)
check("reads still resolve through the (unmoved) pointer, seeing the old directory's own content",
      ps.load_record(_uf3, "lec3", _pdf3, 0)["slide_text"] == _pages3[0])
shutil.rmtree(_uf3, ignore_errors=True)


section("a text-less (scanned) document is identified by its pristine bytes, not its page count (K-268)")
# Copilot, stacked PR #3: text_digest hashes what the pages SAY, so a deck
# with no text layer hashes on its PAGE COUNT alone — two different scans
# of the same length, re-imported under one safe name, shared a directory
# and inherited each other's records. Identity for those is now the
# pristine original's bytes (pdf_originals/<base>.pdf), which a bake never
# writes and save_pdf drops on a re-ingest.
_tl = tempfile.mkdtemp(prefix="klaus-pages-textless-")
_scan_a = _blank_pdf(os.path.join(_tl, "scan_a.pdf"), 300, 200)
_scan_b = _blank_pdf(os.path.join(_tl, "scan_b.pdf"), 612, 792)
_blank = [""]  # one page, no text layer at all
check("text_digest alone cannot tell two one-page scans apart (the bug)",
      ps.text_digest([""]) == ps.text_digest([" \n "]))
ps.ensure_records(_tl, "scan", _scan_a, _blank)
_dir_a = ps.record_dir(_tl, "scan", _scan_a)
# A text-less page has no slide text to recognise it by, so mark scan A's
# record directly.
with open(os.path.join(_dir_a, "0000.json"), "w", encoding="utf-8") as _f:
    json.dump({"version": 1, "slide_text": "marker for scan A", "updated_at": 0.0}, _f)
_id_a = ps._read_pointer(_tl, "scan")
check("a text-less document is NOT keyed on its page-count text digest",
      _id_a != ps.text_digest(_blank) and len(_id_a) == 12
      and all(c in "0123456789abcdef" for c in _id_a), str(_id_a))
check("...it captured the pristine original the first bake would have captured",
      os.path.isfile(os.path.join(_tl, "pdf_originals", "scan.pdf")))

# A bake rewrites the working file with os.replace; the pristine copy is
# what it regenerates FROM, so it is untouched.
with open(_scan_a, "ab") as _f:
    _f.write(b"%% baked annotations\n")
os.utime(_scan_a, (1000, 1000))
check("a text-less document keeps its identity after a bake changes its bytes",
      ps.document_identity(_tl, "scan", _scan_a, _blank) == _id_a)
check("...so record_dir still resolves to the directory holding its records",
      ps.record_dir(_tl, "scan", _scan_a) == _dir_a
      and ps.load_record(_tl, "scan", _scan_a, 0)["slide_text"] == "marker for scan A")

# save_pdf drops the stale pristine when a PDF is re-ingested under the
# same safe name, so the replacing scan is captured fresh.
os.remove(os.path.join(_tl, "pdf_originals", "scan.pdf"))
ps.ensure_records(_tl, "scan", _scan_b, _blank)
_id_b = ps._read_pointer(_tl, "scan")
check("a DIFFERENT text-less scan of the same page count gets a different identity",
      _id_b != _id_a, f"{_id_a} vs {_id_b}")
check("...its records land in their own directory",
      ps.record_dir(_tl, "scan", _scan_b) != _dir_a)
check("...inheriting no record from the scan it replaced",
      ps.load_record(_tl, "scan", _scan_b, 0)["slide_text"] == "")
check("...and the replaced scan's record is left on disk for delete_context",
      json.load(open(os.path.join(_dir_a, "0000.json")))["slide_text"] == "marker for scan A")
shutil.rmtree(_tl, ignore_errors=True)

section("a legacy path-digest directory of the SAME text-less file is still adopted (K-268)")
_lg = tempfile.mkdtemp(prefix="klaus-pages-textless-legacy-")
_scan_c = _blank_pdf(os.path.join(_lg, "scan_c.pdf"), 400, 250)
_leg_dir = os.path.join(_lg, ps.SUBDIR, "scanc", ps.digest12(_scan_c))
os.makedirs(_leg_dir)
# Pre-pointer scheme, and the only record has all-empty text. Its
# updated_at 0.0 marks it: the text is unchanged, so ensure_records never
# rewrites it, and a freshly seeded record would carry the current time.
with open(os.path.join(_leg_dir, "0000.json"), "w", encoding="utf-8") as _f:
    json.dump({"version": 1, "slide_text": "", "updated_at": 0.0}, _f)
ps.ensure_records(_lg, "scanc", _scan_c, [""])
check("the legacy directory migrated onto the pristine-bytes identity, not orphaned",
      not os.path.isdir(_leg_dir)
      and ps._read_pointer(_lg, "scanc") == ps.document_identity(_lg, "scanc", _scan_c, [""]))
check("...carrying the record written before the first index run",
      ps.load_record(_lg, "scanc", _scan_c, 0)["updated_at"] == 0.0)
check("a text-bearing document's identity is still exactly text_digest",
      ps.document_identity(_lg, "scanc", _scan_c, ["Real slide text"])
      == ps.text_digest(["Real slide text"]))
shutil.rmtree(_lg, ignore_errors=True)

# K-268 review: the fallback is pinned, not just promised — no file at all
# (nothing to capture, nothing to hash) must still answer an identity, the
# page-count digest, rather than raise out of an import.
_missing = ps.document_identity(_tmp_ident if '_tmp_ident' in dir() else tempfile.mkdtemp(prefix='klaus-ident-'), 'ghost', '/nonexistent/klaus/ghost.pdf', ['', ''])
check('a text-less document whose file is missing falls back to the page-count digest',
      _missing == ps.text_digest(['', '']), _missing)

section("an empty path never names a directory (K-238)")
# digest12("") is a CONSTANT, so an empty path names ONE legacy directory
# shared by every caller that has lost track of its file — and the empty
# path is reachable: pdf_handler.pdf_path_for answers "" for a PDF that
# does not resolve yet, and the recorder seeds a page before the first
# index run. Whatever is written there vanishes from view the moment the
# real file resolves and the identity moves on, so the store refuses at
# its own boundary rather than trusting its callers.
_ep = tempfile.mkdtemp(prefix="klaus-pages-emptypath-")
_shared = os.path.join(_ep, ps.SUBDIR, "ghost", ps.digest12(""))


def _refuses(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    except Exception as exc:          # any other escape is not a refusal
        return f"raised {type(exc).__name__}: {exc}"
    return False


for _blank in ("", "   ", "\t\n"):
    _what = {"": "empty", "   ": "spaces-only"}.get(_blank, "whitespace")
    check(f"record_dir refuses a {_what} path — it has no directory to name",
          _refuses(ps.record_dir, _ep, "ghost", _blank))
    check(f"record_path refuses a {_what} path",
          _refuses(ps.record_path, _ep, "ghost", _blank, 0))
    check(f"...and no records directory was produced for a {_what} path — "
          "least of all the shared digest12(\"\") one",
          not os.path.isdir(_shared)
          and not os.path.isdir(os.path.join(_ep, ps.SUBDIR, "ghost")))
    check(f"load_record answers the EMPTY record for a {_what} path (the shape "
          "its contract already documents for missing data), never a raise",
          ps.load_record(_ep, "ghost", _blank, 0) == ps._empty())
    check(f"page_texts answers empty rows for a {_what} path",
          [t for _p, _h, t in ps.page_texts(_ep, "ghost", _blank, 2)] == ["", ""])

# The refusal is "an empty path may never NAME a directory", not "a caller
# without a path is turned away": identity here is the DOCUMENT (the
# pointer file / document_identity), so a call the store can still answer
# without consulting the path is answered using the stored document identity.
_np = tempfile.mkdtemp(prefix="klaus-pages-nopath-")
ps.ensure_records(_np, "lec", "", ["Slide one text"])
check("ensure_records with no path keys on the TEXT — never on digest12(\"\")",
      ps._read_pointer(_np, "lec") == ps.text_digest(["Slide one text"])
      and not os.path.isdir(os.path.join(_np, ps.SUBDIR, "lec", ps.digest12(""))))
check("...and once that pointer exists the path is not consulted at all: the "
      "record is read from the document's own directory",
      ps.load_record(_np, "lec", "", 0)["slide_text"] == "Slide one text"
      and ps.record_dir(_np, "lec", "")
      == os.path.join(_np, ps.SUBDIR, "lec", ps.text_digest(["Slide one text"])))

# K-238 review: the deviation left one hole open. ensure_records' own
# fallback identity for an empty page list is text_digest([]), which is
# byte-identical to digest12("") — the shared bucket every other entry
# point refuses — so an empty seed minted exactly what the card abolishes.
_empty_root = tempfile.mkdtemp(prefix="klaus-empty-pages-")
_before = sorted(os.listdir(_empty_root))
check("ensure_records writes nothing at all for a PDF with no extracted pages",
      ps.ensure_records(_empty_root, "ghost", "/nope/ghost.pdf", []) == 0)
check("...and mints no directory, least of all the one digest12('') names",
      sorted(os.listdir(_empty_root)) == _before, os.listdir(_empty_root))
check("text_digest([]) really is the collision this guards (proof, not assumption)",
      ps.text_digest([]) == ps.digest12(""), (ps.text_digest([]), ps.digest12("")))

section("cached_page_png / store_page_png: PNG cache beside the record (K-230)")
_pc_root = tempfile.mkdtemp(prefix="klaus-pages-pngcache-")
_pc_pdf = os.path.join(_pc_root, "lec.pdf")
open(_pc_pdf, "wb").write(b"%PDF-1.4 pngcache")
ps.ensure_records(_pc_root, "pc", _pc_pdf, ["Slide text"])
check("a cache miss answers None", ps.cached_page_png(_pc_root, "pc", _pc_pdf, 0) is None)
ps.store_page_png(_pc_root, "pc", _pc_pdf, 0, b"FAKEPNGBYTES")
check("a stored PNG reads back byte for byte",
      ps.cached_page_png(_pc_root, "pc", _pc_pdf, 0) == b"FAKEPNGBYTES")
_pc_expect = os.path.join(ps.record_dir(_pc_root, "pc", _pc_pdf),
                          "0000.%s.png" % ps.digest12(_pc_pdf))
check("the cache lives beside the JSON record, same stem, stamped by the source file",
      os.path.isfile(_pc_expect)
      and os.path.isfile(os.path.join(os.path.dirname(_pc_expect), "0000.json")))
check("the write is atomic — no leftover .tmp file", not os.path.isfile(_pc_expect + ".tmp"))
_pc_dir = os.path.dirname(_pc_expect)
open(_pc_pdf, "wb").write(b"%PDF-1.4 pngcache, same text, new graphics")
check("replacing the PDF keeps its record dir (same text) — the case the stamp exists for",
      ps.record_dir(_pc_root, "pc", _pc_pdf) == _pc_dir)
check("...but the old render no longer answers for the new file",
      ps.cached_page_png(_pc_root, "pc", _pc_pdf, 0) is None)
ps.store_page_png(_pc_root, "pc", _pc_pdf, 0, b"NEWPNG")
check("the new render reads back", ps.cached_page_png(_pc_root, "pc", _pc_pdf, 0) == b"NEWPNG")
check("storing it drops the stale render: one PNG for page 1",
      [n for n in os.listdir(_pc_dir) if n.endswith(".png")]
      == ["0000.%s.png" % ps.digest12(_pc_pdf)], os.listdir(_pc_dir))
check("cached_page_png never raises for an unresolvable path — answers None",
      ps.cached_page_png(_pc_root, "ghost", "", 5) is None)
_pc_blocked_base = os.path.join(_pc_root, ps.SUBDIR, "blocked")
os.makedirs(os.path.dirname(_pc_blocked_base), exist_ok=True)
open(_pc_blocked_base, "w").write("a file sitting where the record dir needs to be a directory")
_pc_store_raised = False
try:
    ps.store_page_png(_pc_root, "blocked", "/nonexistent/blocked.pdf", 0, b"x")
except Exception:
    _pc_store_raised = True
check("store_page_png never raises into the caller, even when the write fails",
      not _pc_store_raised)

raise SystemExit(report())
