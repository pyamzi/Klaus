"""Tests for klaus_note.pdf_notes (K-134, slice A of K-079).

Covers: the markdown sidecar (absent/corrupt tolerance, atomic write,
empty text DELETING the file), the Helvetica base-14 WinAnsi metrics, the
pure layout (greedy wrap, blank lines preserved, trailing whitespace
trimmed, hard-split unbreakable tokens, pagination with the first page's
heading reserve), the byte-exact content stream, and the source pins that
keep the module importable with neither aqt nor pypdf present.

The synthesis function is asserted on the BYTES it emits, not by round-
tripping through pypdf: pypdf cannot be imported by this machine's python3
without the typing_extensions shim, so a pypdf-only test would silently
stop running the moment that shim moved. The optional last section adds
the shim (test_klaus_note.py's precedent) and, when it takes, proves the
regenerative-bake contract end to end — appending once, never
accumulating across repeated bakes, and un-baking back to the pristine
page count. It reports an honest SKIP when pypdf is genuinely absent.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_notes.py
"""

import ast
import importlib
import io
import os
import shutil
import sys
import tempfile
import types
import typing as _typing

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section  # noqa: E402

install()

pn = importlib.import_module("klaus_note.pdf_notes")

_SRC = open("klaus_note/pdf_notes.py").read()
_CODE = code_only(_SRC)

# NEVER the real user_files — every storage call below is rooted here.
tmp = tempfile.mkdtemp(prefix="klaus_notes_")


# ------------------------------------------------------------------ sidecar

section("sidecar storage — path, tolerance, atomic write, empty deletes")

check("the sidecar is annotations/<safe>.notes.md, beside the highlights",
      pn.notes_path(tmp, "Lec_1")
      == os.path.join(tmp, "annotations", "Lec_1.notes.md"))
check("a PDF with no sidecar reads as empty string, not None",
      pn.load_notes(tmp, "Lec_1") == "")
check("has_notes is False when there is no sidecar",
      pn.has_notes(tmp, "Lec_1") is False)

check("save_notes reports success", pn.save_notes(tmp, "Lec_1", "hello\nworld"))
check("save creates the annotations dir it needs",
      os.path.isdir(os.path.join(tmp, "annotations")))
check("notes round-trip through the sidecar byte for byte",
      pn.load_notes(tmp, "Lec_1") == "hello\nworld")
check("has_notes is True once there is text", pn.has_notes(tmp, "Lec_1"))

pn.save_notes(tmp, "Lec_1", "note with an em dash — and é")
check("non-ASCII survives storage (utf-8 on disk; WinAnsi is a RENDER "
      "limit, never a storage one)",
      pn.load_notes(tmp, "Lec_1") == "note with an em dash — and é")

check("save_notes leaves no .tmp files behind",
      [f for f in os.listdir(os.path.join(tmp, "annotations"))
       if f.endswith(".tmp")] == [])

check("empty text DELETES the sidecar (the un-bake round-trip)",
      pn.save_notes(tmp, "Lec_1", "")
      and not os.path.exists(pn.notes_path(tmp, "Lec_1")))
pn.save_notes(tmp, "Lec_1", "back again")
check("whitespace-only text counts as empty and deletes too",
      pn.save_notes(tmp, "Lec_1", "  \n\t\n ")
      and not os.path.exists(pn.notes_path(tmp, "Lec_1")))
check("deleting an already-absent sidecar is a quiet success",
      pn.save_notes(tmp, "Lec_1", "") is True)

# A directory where the file should be: unreadable, must not raise.
bad = pn.notes_path(tmp, "Broken")
os.makedirs(bad, exist_ok=True)
check("an unreadable sidecar reads as empty rather than raising",
      pn.load_notes(tmp, "Broken") == "")

with open(pn.notes_path(tmp, "Mangled"), "wb") as f:
    f.write(b"good \xff\xfe bytes")
check("undecodable bytes cost characters, never the whole note",
      pn.load_notes(tmp, "Mangled").startswith("good "))


# ------------------------------------------------------ save_notes failure

section("save_notes reports FAILURE when the disk says no")
# Every success path returned True and was pinned; both error branches
# returned False and were pinned by nothing (K-139 mutation audit, finding
# 9 — flipping either `return False` to `return True` survived the whole
# suite). The return value is not decoration: the notes pane autosaves on a
# debounce and a lie here is a silently lost note, or — on the delete side —
# a stale notes page left baked into the PDF after the user cleared it.
#
# Exercised against a genuinely unwritable directory (0o500: stat and read
# still work, create and unlink do not). The mode is restored in a finally
# so this never leaves an unremovable scratch directory behind.
_ro_root = tempfile.mkdtemp(prefix="klaus_notes_ro_")
_ro_dir = os.path.dirname(pn.notes_path(_ro_root, "Locked"))
os.makedirs(_ro_dir, exist_ok=True)
check("fixture: a sidecar exists before the directory is locked",
      pn.save_notes(_ro_root, "Locked", "text that must not vanish") is True)
try:
    os.chmod(_ro_dir, 0o500)
    try:  # prove the lock actually locks — root ignores these bits
        _probe = os.path.join(_ro_dir, ".probe")
        with open(_probe, "w"):
            pass
        os.remove(_probe)
        _denied = False
    except OSError:
        _denied = True

    if not _denied:
        print("  SKIP  save_notes failure branches (this user/filesystem "
              "ignores 0o500) — NOT counted as a pass")
    else:
        check("a write that cannot happen reports False, never True — the "
              "atomic tmp+replace has nowhere to put its temp file",
              pn.save_notes(_ro_root, "Locked", "a replacement note")
              is False)
        check("the sidecar already on disk is untouched by the failed "
              "write (atomic means all or nothing, both ways)",
              pn.load_notes(_ro_root, "Locked")
              == "text that must not vanish")
        check("a DELETE that cannot happen reports False too — empty text "
              "is the un-bake half of the round trip, so a false success "
              "leaves a notes page baked into a PDF the user just cleared",
              pn.save_notes(_ro_root, "Locked", "") is False)
        check("...and the sidecar survives that failed delete",
              os.path.isfile(pn.notes_path(_ro_root, "Locked")))
        check("no half-written temp file is left in the locked directory",
              [f for f in os.listdir(_ro_dir) if f.endswith(".tmp")] == [])
finally:
    os.chmod(_ro_dir, 0o700)


# ------------------------------------------------------------------ metrics

section("Helvetica base-14 WinAnsi metrics")

check("the width table is total over all 256 WinAnsi codes",
      len(pn.HELVETICA_WIDTHS) == 256
      and all(isinstance(v, int) and v > 0 for v in pn.HELVETICA_WIDTHS))
check("AFM widths: space 278, W 944, i 222, @ 1015, M 833",
      [pn.HELVETICA_WIDTHS[ord(c)] for c in " Wi@M"]
      == [278, 944, 222, 1015, 833])
check("digits are tabular in Helvetica — all 556",
      {pn.HELVETICA_WIDTHS[ord(c)] for c in "0123456789"} == {556})
check("the WinAnsi upper half is populated: em dash 1000, bullet 350",
      pn.HELVETICA_WIDTHS[0x97] == 1000
      and pn.HELVETICA_WIDTHS[0x95] == 350)

check("encode_winansi maps the em dash to its single cp1252 byte",
      pn.encode_winansi("—") == b"\x97")
check("characters outside WinAnsi degrade to '?' (the flagged v1 limit)",
      pn.encode_winansi("ok 中文") == b"ok ??")
check("measurement follows the DEGRADED bytes, so width and emitted "
      "bytes can never disagree",
      pn.text_width("中", 11) == pn.text_width("?", 11))

check("text_width scales linearly with font size",
      abs(pn.text_width("Hello", 22) - 2 * pn.text_width("Hello", 11)) < 1e-9)
check("text_width sums the AFM table exactly (Hello @ 11pt)",
      abs(pn.text_width("Hello", 11)
          - (722 + 556 + 222 + 222 + 556) / 1000.0 * 11) < 1e-9)
check("empty text measures zero", pn.text_width("", 11) == 0.0)


# ------------------------------------------------------------------- wrap

section("wrap_lines — greedy wrap, blanks, trailing space, hard splits")

WIDTH = pn.PAGE_WIDTH - 2 * pn.MARGIN

check("empty text wraps to no lines at all", pn.wrap_lines("") == [])
check("a short line passes through untouched",
      pn.wrap_lines("short line", WIDTH) == ["short line"])

wrapped = pn.wrap_lines(
    "The quick brown fox jumps over the lazy dog and keeps on running "
    "well past the right margin for a while.", 200, 11)
check("a long line wraps to several lines", len(wrapped) > 1)
check("every wrapped line fits inside the column",
      all(pn.text_width(ln, 11) <= 200 for ln in wrapped))
check("wrapping loses no words",
      " ".join(wrapped).split()
      == ("The quick brown fox jumps over the lazy dog and keeps on "
          "running well past the right margin for a while.").split())

check("blank lines are PRESERVED — paragraph breaks are structure",
      pn.wrap_lines("a\n\nb", WIDTH) == ["a", "", "b"])
check("several blank lines all survive",
      pn.wrap_lines("a\n\n\nb", WIDTH) == ["a", "", "", "b"])
check("no output line ever carries trailing whitespace (invisible on the "
      "page, but it would move a wrap point)",
      pn.wrap_lines("a   \n   \n  b  ", WIDTH)
      == [ln.rstrip() for ln in pn.wrap_lines("a   \n   \n  b  ", WIDTH)])
check("a whitespace-only line becomes a blank line",
      pn.wrap_lines("a\n   \nb", WIDTH) == ["a", "", "b"])
check("CRLF input splits on lines, not on stray carriage returns",
      pn.wrap_lines("a\r\nb", WIDTH) == ["a", "b"])

url = "https://example.com/" + "a" * 300
split = pn.wrap_lines(url, 200, 11)
check("an unbreakable token HARD-SPLITS instead of overflowing",
      len(split) > 1 and all(pn.text_width(s, 11) <= 200 for s in split))
check("a hard split loses no characters", "".join(split) == url)
check("a hard split always makes progress (no zero-length pieces)",
      all(s for s in split))
check("a token wider than the WHOLE column still terminates",
      len(pn.wrap_lines("W" * 40, 8, 11)) == 40)

check("leading indent is preserved and re-applied to continuations",
      pn.wrap_lines("    alpha beta gamma delta", 90, 11)[0].startswith("    ")
      and all(ln.startswith("    ")
              for ln in pn.wrap_lines("    alpha beta gamma delta", 90, 11)))
check("an indent too deep for the column is dropped, not wrapped to death",
      not pn.wrap_lines(" " * 200 + "word", 100, 11)[0].startswith(" "))
check("a nonsense column width yields no lines rather than looping",
      pn.wrap_lines("text", 0, 11) == []
      and pn.wrap_lines("text", 100, 0) == [])


# --------------------------------------------------------------- paginate

section("paginate — page capacity, first-page heading reserve, empties")

check("no lines means NO pages — never one empty page "
      "(an empty appendix would break the un-bake)",
      pn.paginate([]) == [] and pn.paginate(None) == [])

full = pn.lines_per_page()
first = pn.lines_per_page(reserve=pn.TITLE_RESERVE)
check("a Letter page holds 48 body lines at 13.75pt leading", full == 48)
check("page one is shorter — it pays for the heading",
      first == 45 and first < full)

body = [f"line {i}" for i in range(full + first + 3)]
pages = pn.paginate(body)
check("pagination fills page one to its reserved capacity",
      len(pages[0]) == first)
check("later pages use the FULL column, not the reserved one",
      len(pages[1]) == full)
check("pagination is a partition — every line lands exactly once, in order",
      [ln for p in pages for ln in p] == body)
check("the overflow spills to a third page",
      len(pages) == 3 and len(pages[2]) == 3)

check("one line makes exactly one page",
      pn.paginate(["only"]) == [["only"]])
check("a degenerate geometry still emits at least one line per page "
      "(notes are never silently dropped)",
      pn.lines_per_page(page_height_pt=10.0) == 1
      and pn.lines_per_page(leading=0.0) == 1)
check("a non-numeric geometry degrades instead of raising",
      pn.lines_per_page(leading="wide") == 1)


section("notes_pages — the composed entry point the bake calls")

check("empty notes produce ZERO pages — the un-bake gate",
      pn.notes_pages("") == [])
check("whitespace-only notes produce ZERO pages",
      pn.notes_pages("  \n\n\t ") == [] and pn.notes_pages(None) == [])
check("trailing blank lines never buy a page of nothing",
      pn.notes_pages("one line\n\n\n\n") == [["one line"]])
check("interior blank lines still survive the composer",
      pn.notes_pages("a\n\nb") == [["a", "", "b"]])
long_pages = pn.notes_pages("lorem ipsum dolor sit amet " * 400)
check("a long note paginates across several pages", len(long_pages) > 2)
check("no page exceeds the full-column capacity",
      all(len(p) <= full for p in long_pages))
check("a slide-shaped page (16:9) gets its own smaller capacity",
      len(pn.notes_pages("word " * 400, 720.0, 405.0)[0])
      < len(pn.notes_pages("word " * 400)[0]))


# --------------------------------------------------------------- synthesis

section("notes_page_stream — byte-exact content stream (no pypdf needed)")

stream = pn.notes_page_stream(
    ["Hello (world)", "", "back\\slash"], title="Notes — Lecture 1")
EXPECTED = (
    b"q\n"
    b"BT\n"
    b"0 g\n"
    b"/F1 14 Tf\n"
    b"1 0 0 1 72 720 Tm\n"
    b"(Notes \\227 Lecture 1) Tj\n"
    b"ET\n"
    b"0.6 w\n"
    b"0.75 0.75 0.75 RG\n"
    b"72 712 m 540 712 l S\n"
    b"BT\n"
    b"0 g\n"
    b"/F1 11 Tf\n"
    b"13.75 TL\n"
    b"1 0 0 1 72 690 Tm\n"
    b"(Hello \\(world\\)) Tj\n"
    b"T*\n"
    b"T*\n"
    b"(back\\\\slash) Tj\n"
    b"ET\n"
    b"Q\n"
)
check("the emitted stream is byte-for-byte the expected PDF operators",
      stream == EXPECTED,
      f"\n--- got ---\n{stream.decode('latin-1')}"
      f"--- want ---\n{EXPECTED.decode('latin-1')}")
check("the stream is bytes, not str", isinstance(stream, bytes))
check("the whole stream stays 7-bit ASCII (octal escapes, not raw bytes)",
      all(b < 128 for b in stream))
check("a blank line emits a bare T* — the line advance IS the blank line",
      stream.count(b"T*") == 2 and b"() Tj" not in stream)
check("graphics state is saved and restored around the page",
      stream.startswith(b"q\n") and stream.endswith(b"\nQ\n"))

plain = pn.notes_page_stream(["only line"])
check("a continuation page draws no heading and no rule",
      b"Tj" in plain and b" l S" not in plain and b"/F1 14 Tf" not in plain)
check("a continuation page starts its text at the full top margin "
      "(no heading reserve to pay)",
      b"1 0 0 1 72 720 Tm" in plain)
check("no lines and no title emits a well-formed empty page stream",
      pn.notes_page_stream([]) == b"q\nQ\n")

check("pdf_literal escapes the three characters that would break a "
      "literal string",
      pn.pdf_literal("a(b)c\\d") == b"(a\\(b\\)c\\\\d)")
check("pdf_literal octal-escapes everything outside printable ASCII",
      pn.pdf_literal("é") == b"(\\351)")
check("pdf_literal degrades un-encodable text to '?' rather than raising",
      pn.pdf_literal("中") == b"(?)")
check("_num emits shortest stable reals",
      [pn._num(v) for v in (72.0, 13.75, 0.6, 0, -0.0)]
      == [b"72", b"13.75", b"0.6", b"0", b"0"])
check("notes_title is K-079's heading wording, em dash and all",
      pn.notes_title("Lecture 1") == "Notes — Lecture 1")

geom = pn.notes_page_stream(["x"], title="T", page_width_pt=720.0,
                            page_height_pt=405.0)
check("page geometry flows through to the emitted coordinates",
      b"1 0 0 1 72 333 Tm" in geom and b"72 325 m 648 325 l S" in geom)


# ------------------------------------------------------------- source pins

section("source pins — stdlib-only above the divider, guarded glue")

check("no aqt anywhere: a notes page has no Qt in it",
      "import aqt" not in _CODE and "from aqt" not in _CODE)

_tree = ast.parse(_SRC)
_toplevel = [n for n in _tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
_names = sorted(
    {a.name.split(".")[0] for n in _toplevel if isinstance(n, ast.Import)
     for a in n.names}
    | {(n.module or "").split(".")[0] for n in _toplevel
       if isinstance(n, ast.ImportFrom)}
)
check("module-level imports are stdlib only — os, uuid and __future__",
      _names == ["__future__", "os", "uuid"], f"- got {_names}")
check("pypdf is imported ONLY inside append_notes_pages, never at module "
      "top (this machine's python3 cannot import it at all)",
      "pypdf" not in _CODE.split("def append_notes_pages")[0])

_glue = [n for n in ast.walk(_tree)
         if isinstance(n, ast.FunctionDef) and n.name == "append_notes_pages"]
check("append_notes_pages exists exactly once", len(_glue) == 1)
check("its pypdf import sits inside a Try — a missing pypdf degrades to "
      "'appended nothing', it never breaks the bake",
      any(isinstance(node, ast.Try)
          and any(isinstance(s, (ast.Import, ast.ImportFrom))
                  for b in [node.body] for s in ast.walk(ast.Module(
                      body=b, type_ignores=[])))
          for node in ast.walk(_glue[0])))
check("every failure path logs with the house [klaus_note] prefix",
      _SRC.count('print(f"[klaus_note]') == _SRC.count("print("))

check("the glue only APPENDS — add_blank_page and nothing that inserts "
      "into or rewrites the content pages",
      _CODE.count("add_blank_page") == 1
      and "insert_page" not in _CODE and "insert_blank_page" not in _CODE)
check("save_notes writes atomically — tmp then os.replace, "
      "retention_history's primitive", "os.replace(tmp, path)" in _CODE)
check("the sidecar suffix is the markdown one K-079 specified",
      pn.NOTES_SUFFIX == ".notes.md")

check("load/save take the SAFE storage key, matching annotations_path_for "
      "and forget_history",
      list(pn.load_notes.__code__.co_varnames[:2]) == ["user_files_dir", "safe"]
      and list(pn.save_notes.__code__.co_varnames[:3])
      == ["user_files_dir", "safe", "text"])
check("append_notes_pages signature is the bake call site's contract",
      list(pn.append_notes_pages.__code__.co_varnames[:3])
      == ["writer", "text", "display_name"])
check("append_notes_pages appends nothing when there are no notes, "
      "without ever touching pypdf",
      pn.append_notes_pages(None, "", "Lecture 1") == 0
      and pn.append_notes_pages(None, "   ", "Lecture 1") == 0)


# ------------------------------------------------- optional pypdf round-trip

section("regenerative bake, end to end (pypdf — SKIPPED when unavailable)")

try:
    import typing_extensions  # noqa: F401
except ImportError:
    # test_klaus_note.py's shim: the vendored pypdf needs typing_extensions,
    # which this machine's python3.9 does not ship.
    class _TESub:
        def __getitem__(self, _i):
            return _typing.Any

        def __call__(self, *a, **k):
            return _typing.Any

    class _TEModule(types.ModuleType):
        def __getattr__(self, n):
            return getattr(_typing, n, _TESub())

    sys.modules["typing_extensions"] = _TEModule("typing_extensions")

sys.path.insert(0, os.path.join("klaus_note", "vendor"))
try:
    from pypdf import PdfReader, PdfWriter  # noqa: E402
except Exception as _pypdf_exc:  # noqa: BLE001
    print(f"  SKIP  pypdf unavailable ({type(_pypdf_exc).__name__}) — the "
          "byte-level stream pins and source pins above still ran")
else:
    _w0 = PdfWriter()
    _w0.add_blank_page(width=612, height=792)
    _w0.add_blank_page(width=612, height=792)
    _buf = io.BytesIO()
    _w0.write(_buf)
    PRISTINE = _buf.getvalue()

    def _bake(text):
        """One regenerative bake: clone the pristine original, append."""
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(PRISTINE)))
        added = pn.append_notes_pages(writer, text, "Lecture 1")
        out = io.BytesIO()
        writer.write(out)
        return added, PdfReader(io.BytesIO(out.getvalue()))

    NOTE = "Hello notes.\n\nA (paren), a \\ and an em dash —."
    n1, doc1 = _bake(NOTE)
    check("one notes page is appended after the content pages",
          n1 == 1 and len(doc1.pages) == 3)
    check("the appended page carries the heading and the note text",
          "Notes — Lecture 1" in doc1.pages[-1].extract_text()
          and "Hello notes." in doc1.pages[-1].extract_text())
    check("escaped characters survive as themselves, not as escapes",
          "(paren)" in doc1.pages[-1].extract_text()
          and "—" in doc1.pages[-1].extract_text())
    check("content pages are untouched — the notes ride on an appendix",
          doc1.pages[0].extract_text().strip() == "")

    n2, doc2 = _bake(NOTE)
    check("a REPEATED bake never accumulates a second notes page "
          "(regeneration from pristine is what guarantees it)",
          n2 == 1 and len(doc2.pages) == 3)

    n3, doc3 = _bake("")
    check("clearing the notes un-bakes back to the pristine page count",
          n3 == 0 and len(doc3.pages) == 2)

    n4, doc4 = _bake("lorem ipsum dolor sit amet " * 400)
    check("a long note appends as many pages as it needs",
          n4 > 1 and len(doc4.pages) == 2 + n4)
    check("continuation pages carry no second heading",
          doc4.pages[-1].extract_text().count("Notes — Lecture 1") == 0)

    _w5 = PdfWriter()
    _w5.add_blank_page(width=720, height=405)
    check("the appendix matches a 16:9 deck's page size",
          pn.append_notes_pages(_w5, "note", "Slides") == 1
          and abs(float(_w5.pages[-1].mediabox.width) - 720.0) < 0.5)


shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(_ro_root, ignore_errors=True)
raise SystemExit(report())
