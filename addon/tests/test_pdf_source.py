"""PDF reader 2/5: pdf_source serves byte ranges without holding the file open.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_source.py
"""
from __future__ import annotations

import base64
import importlib
import io
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

ps = importlib.import_module("klausmate.pdf_source")
ph = importlib.import_module("klausmate.pdf_handler")

tmp = tempfile.mkdtemp()


def make(name: str, data: bytes) -> str:
    path = os.path.join(tmp, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def reply_bytes(r: dict) -> bytes:
    return base64.b64decode(r["b64"])


def real_pdf() -> bytes:
    w = ph.pypdf.PdfWriter()
    for _ in range(40):
        w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


section("constants")
check("first chunk 256 KB", ps.FIRST_CHUNK == 262144)
check("max range 1 MB", ps.MAX_RANGE == 1048576)

section("ranges match the file")
pdf = real_pdf()
big = pdf + bytes(range(256)) * 4096  # past one chunk, past nothing special
path = make("a.pdf", big)
src = ps.DocSource(path)
check("length", src.length == len(big))
check("stat is the shared fingerprint", src.stat == ph.file_stat(path))
check("first chunk", src.read(0, ps.FIRST_CHUNK) == big[: ps.FIRST_CHUNK])
check("first chunk of a real PDF starts with the header", src.read(0, 8)[:5] == b"%PDF-")
check("middle range", src.read(1000, 5000) == big[1000:5000])
check("end past length is clamped", src.read(len(big) - 10, len(big) + 999) == big[-10:])
check("wider than MAX_RANGE is clamped", len(src.read(0, len(big) * 10)) == min(len(big), ps.MAX_RANGE))
check("negative begin clamps to 0", src.read(-5, 4) == big[:4])
check("out-of-order range is empty", src.read(50, 10) == b"")
check("begin past length is empty", src.read(len(big) + 5, len(big) + 9) == b"")

section("range_reply")
r = ps.range_reply(src, 3, 3, 1000, 5000)
check("ok reply is b64", set(r) == {"b64"} and reply_bytes(r) == big[1000:5000])
check("empty range is empty b64", ps.range_reply(src, 3, 3, 50, 10) == {"b64": ""})
check("old gen refused", ps.range_reply(src, 2, 3, 0, 10) == {"refused": True})
check("no source is stale", ps.range_reply(None, 3, 3, 0, 10) == {"stale": True})

section("replaced, truncated or deleted files are stale")
path2 = make("b.pdf", b"x" * 5000)
s2 = ps.DocSource(path2)
other = make("b.new", b"y" * 5000)
os.replace(other, path2)
check("replaced file reads stale", ps.range_reply(s2, 1, 1, 0, 100) == {"stale": True})
try:
    s2.read(0, 10)
    raised = False
except ps.StaleSource:
    raised = True
check("read raises StaleSource", raised)

path3 = make("c.pdf", b"z" * 5000)
s3 = ps.DocSource(path3)
with open(path3, "wb") as f:
    f.write(b"z" * 100)
check("truncated file reads stale", ps.range_reply(s3, 1, 1, 0, 50) == {"stale": True})

path4 = make("d.pdf", b"q" * 5000)
s4 = ps.DocSource(path4)
os.remove(path4)
check("deleted file reads stale", ps.range_reply(s4, 1, 1, 0, 50) == {"stale": True})

section("no handle is kept")
path5 = make("e.pdf", b"k" * 5000)
s5 = ps.DocSource(path5)
s5.read(0, 100)
check("no open file attribute", not hasattr(s5, "_fh") and not any(
    hasattr(v, "read") and hasattr(v, "close") for v in vars(s5).values()))
repl = make("e.new", b"m" * 5000)
try:
    os.replace(repl, path5)
    replaced = True
except OSError:
    replaced = False
check("os.replace onto the path succeeds right after a read", replaced)

raise SystemExit(report())
