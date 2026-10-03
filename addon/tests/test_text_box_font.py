"""Text boxes draw in the font the PDF stores them in.

The bake writes every text box as a FreeText annotation in Helvetica
(``pdf_handler._DA_FONT = "Helv"``, a base-14 font), and Preview draws it
in Helvetica. The reader used to draw the same box in the system UI font
(San Francisco), which runs about 7% wider at the same size, so a box
looked bigger in Klaus than in Preview. Both the static box (``.hltext``)
and the in-place editor (``.editBody``) must use Helvetica.

The hand-drawn reader (2026-10-01) draws them, the note cards and the
measuring twin in Excalifont instead, but only under ``body.handDrawn``:
with the switch off every one of them is Helvetica again.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_text_box_font.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(ROOT, "klaus_note", "web", "pdfjs_viewer.html"), encoding="utf-8").read()
HANDLER = open(os.path.join(ROOT, "klaus_note", "pdf_handler.py"), encoding="utf-8").read()

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
    # The selector must open its line: a grouped body.handDrawn rule that
    # merely ENDS in the same selector is not the base rule.
    m = base_match(selector)
    return m.group(1) if m else ""


def base_match(selector):
    return re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", HTML)


def family(body):
    m = re.search(r"font-family:\s*([^;]+);", body)
    return m.group(1).strip() if m else ""


check("the bake still writes text boxes in Helvetica (/Helv)",
      '_DA_FONT = "Helv"' in HANDLER)
BASE = (".hlLayer .hltext", ".noteCard", "#textMeasure", ".editLayer .editBody")
for sel in BASE:
    fam = family(rule(sel))
    check(f"{sel} draws in Helvetica first, as the PDF does (hand-drawn off)",
          fam.split(",")[0].strip().strip("'\"") == "Helvetica", f"font-family={fam!r}")

# One grouped rule switches all four to the hand-drawn stack together, so
# the measuring twin can never measure in a font the box does not draw in.
grp = re.search(r"((?:body\.handDrawn [^,{}]+,\s*)+body\.handDrawn [^,{}]+)\{([^}]*)\}", HTML)
sels = {x.strip() for x in grp.group(1).split(",")} if grp else set()
check("body.handDrawn switches exactly the box, the card, the twin and the editor",
      sels == {"body.handDrawn " + s for s in BASE}, repr(sels))
check('...to "Excalifont", sans-serif, exactly',
      bool(grp) and family(grp.group(2)) == '"Excalifont", sans-serif',
      repr(grp and family(grp.group(2))))
check("...and it comes after every base rule, so it wins the cascade",
      bool(grp) and all(base_match(s) and grp.start() > base_match(s).start() for s in BASE))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
