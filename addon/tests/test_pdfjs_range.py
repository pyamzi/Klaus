"""PDF reader 2/5: the page's range feed against the vendored pdf.js.

tests/pdfjs_range_test.js runs the page's own feed code (cut out of
web/pdfjs_viewer.html) against web/pdfjs/ under node; this file builds
its PDF and reports. Without node it is SKIPPED, never counted as a pass.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdfjs_range.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, report, section  # noqa: E402


def build_pdf(path: str) -> None:
    """12 text pages; page 3 carries a ~1.6 MB content stream, so pdf.js
    asks for one range wider than a single 1 MB bridge call."""
    n = 12
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            ("<< /Type /Pages /Kids [%s] /Count %d >>" % (
                " ".join("%d 0 R" % (3 + 2 * i) for i in range(n)), n)).encode()]
    for i in range(n):
        body = b"BT /F1 24 Tf 20 100 Td (Page %d) Tj ET\n" % (i + 1)
        body += b"0 0 m 10 10 l S\n" * (100_000 if i == 2 else 200)
        objs.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
                     "/Contents %d 0 R /Resources << /Font << /F1 << /Type /Font "
                     "/Subtype /Type1 /BaseFont /Helvetica >> >> >> >>" % (4 + 2 * i)).encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % k + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "wb") as f:
        f.write(out)


section("range feed against the vendored pdf.js (node)")
if shutil.which("node"):
    here = os.path.dirname(os.path.abspath(__file__))
    web = os.path.join(here, "..", "klaus_note", "web")
    pdf = os.path.join(tempfile.mkdtemp(), "range.pdf")
    build_pdf(pdf)
    proc = subprocess.run(
        ["node", os.path.join(here, "pdfjs_range_test.js"),
         os.path.join(web, "pdfjs_viewer.html"), os.path.join(web, "pdfjs"), pdf],
        capture_output=True, text=True, timeout=60)
    print(proc.stdout.rstrip())
    check("the page's KlausRange loads a real PDF through pdf.js by range, "
          "slices wide requests to MAX_RANGE, aborts on destroy, and on a "
          "stale reply posts stale:<gen> and stops",
          proc.returncode == 0,
          (proc.stdout + proc.stderr).strip().replace("\n", " | "))
else:
    print("  SKIP  pdf.js range feed (node not installed) — NOT counted as a pass")

raise SystemExit(report())
