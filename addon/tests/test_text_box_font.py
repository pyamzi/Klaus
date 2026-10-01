"""Text boxes draw in the font the PDF stores them in.

The bake writes every text box as a FreeText annotation in Helvetica
(``pdf_handler._DA_FONT = "Helv"``, a base-14 font), and Preview draws it
in Helvetica. The reader used to draw the same box in the system UI font
(San Francisco), which runs about 7% wider at the same size, so a box
looked bigger in Klaus than in Preview. Both the static box (``.hltext``)
and the in-place editor (``.editBody``) must use Helvetica.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_text_box_font.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(ROOT, "klausmate", "web", "pdfjs_viewer.html"), encoding="utf-8").read()
HANDLER = open(os.path.join(ROOT, "klausmate", "pdf_handler.py"), encoding="utf-8").read()

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok  {label}")
    else:
        failed += 1
        print(f"FAIL  {label}  {detail}")


def rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", HTML)
    return m.group(1) if m else ""


def family(body):
    m = re.search(r"font-family:\s*([^;]+);", body)
    return m.group(1).strip() if m else ""


check("the bake still writes text boxes in Helvetica (/Helv)",
      '_DA_FONT = "Helv"' in HANDLER)
for sel in (".hlLayer .hltext", ".editLayer .editBody"):
    fam = family(rule(sel))
    check(f"{sel} draws in Helvetica first, as the PDF does",
          fam.split(",")[0].strip().strip("'\"") == "Helvetica", f"font-family={fam!r}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
