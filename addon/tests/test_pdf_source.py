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

ps = importlib.import_module("klaus_note.pdf_source")
ph = importlib.import_module("klaus_note.pdf_handler")

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

section("R20: ranges come from a hard-link snapshot taken at load")
snap_dir = os.path.join(tmp, "reading")
orig = big
p6 = make("f.pdf", orig)
s6 = ps.DocSource(p6, snap_dir)
check("snapshot dir is created and holds one link",
      os.path.isdir(snap_dir) and len(os.listdir(snap_dir)) == 1)
check("reads go through the snapshot path",
      s6.read_path != p6 and os.path.dirname(s6.read_path) == snap_dir
      and s6.read_path.endswith(".pdf")
      and os.path.samefile(s6.read_path, p6))
check("length and fingerprint describe the file", s6.length == len(orig)
      and s6.stat == ph.file_stat(p6))
# Klaus's own bake: write a new file and os.replace it onto the path.
newer = make("f.new", b"%PDF-baked" + b"n" * 9000)
os.replace(newer, p6)
check("an os.replace of the original path does NOT make reads stale",
      ps.range_reply(s6, 1, 1, 0, 100) != {"stale": True})
check("...and reads still return the original bytes",
      s6.read(0, ps.FIRST_CHUNK) == orig[: ps.FIRST_CHUNK]
      and s6.read(1000, 5000) == orig[1000:5000])

p7 = make("g.pdf", orig)
s7 = ps.DocSource(p7, snap_dir)
with open(p7, "r+b") as f:
    f.seek(10)
    f.write(b"OUTSIDE-EDIT")
os.utime(p7, ns=(os.stat(p7).st_atime_ns, os.stat(p7).st_mtime_ns + 5_000_000))
check("an in-place rewrite of the original (shared inode) DOES make reads stale",
      ps.range_reply(s7, 1, 1, 0, 100) == {"stale": True})

_real_link = os.link


def _no_link(*a, **k):
    raise OSError(18, "Cross-device link")


os.link = _no_link
try:
    p8 = make("h.pdf", b"h" * 5000)
    s8 = ps.DocSource(p8, snap_dir)
finally:
    os.link = _real_link
check("link failure falls back to the live path", s8.read_path == p8
      and s8.read(0, 10) == b"h" * 10)
os.replace(make("h.new", b"i" * 5000), p8)
check("...and behaves as before: a replaced file reads stale",
      ps.range_reply(s8, 1, 1, 0, 10) == {"stale": True})
s8.close()
check("closing a source without a link touches nothing", os.path.exists(p8))

link6 = s6.read_path
s6.close()
check("close() removes the snapshot link", not os.path.exists(link6))
try:
    s6.close()
    closed_twice = True
except Exception:
    closed_twice = False
check("close() is idempotent", closed_twice)

before = set(os.listdir(snap_dir))
try:
    ps.DocSource(os.path.join(tmp, "nope.pdf"), snap_dir)
    missing_raised = False
except ps.StaleSource:
    missing_raised = True
check("...StaleSource for a missing file", missing_raised)
check("...and no link left behind", set(os.listdir(snap_dir)) == before)

keep_src = ps.DocSource(make("k.pdf", b"k" * 100), snap_dir)
open(os.path.join(snap_dir, "leftover.pdf"), "wb").close()
open(os.path.join(snap_dir, "notes.txt"), "wb").close()
ps.sweep_snapshots(snap_dir, keep={keep_src.read_path})
left = sorted(os.listdir(snap_dir))
check("sweep removes leftover links except keep (and non-PDFs)",
      left == sorted([os.path.basename(keep_src.read_path), "notes.txt"]))
try:
    ps.sweep_snapshots(os.path.join(tmp, "no-such-dir"))
    sweep_ok = True
except Exception:
    sweep_ok = False
check("sweep of a missing dir never raises", sweep_ok)

raise SystemExit(report())
