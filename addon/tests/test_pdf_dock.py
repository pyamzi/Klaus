"""Tests for klausmate.pdf_handler placement migration (K-216).

Covers: the placement-value migration from pre-dock panel placement names
to the four dock areas (left, right, bottom, float). Every legacy value
maps to a valid dock placement; unknown values default to "right".

A real-Qt section is appended by Task 2 (PdfDock construction), so report()
must stay the LAST line of the file — no code runs after it.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_pdf_dock.py
"""

import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

pdf_handler = importlib.import_module("klausmate.pdf_handler")


section("placement migration — one pure function, every old value lands")
for old, new in (
    ("above", "bottom"), ("below", "bottom"),
    ("left", "left"), ("notes-left", "left"),
    ("right", "right"), ("notes-right", "right"),
    ("float", "float"),
    ("bottom", "bottom"),
):
    check(f"{old!r} → {new!r}",
          pdf_handler.migrate_placement(old) == new,
          repr(pdf_handler.migrate_placement(old)))
check("an unknown or missing value lands on 'right' — the editor-side "
      "default, never an exception",
      pdf_handler.migrate_placement(None) == "right"
      and pdf_handler.migrate_placement("sideways") == "right"
      and pdf_handler.migrate_placement(42) == "right")
check("PANEL_PLACEMENTS is exactly the four values the dock persists",
      pdf_handler.PANEL_PLACEMENTS == ("left", "right", "bottom", "float"))
check("every migrated value is one of them",
      all(pdf_handler.migrate_placement(v) in pdf_handler.PANEL_PLACEMENTS
          for v in ("above", "below", "left", "notes-left", "right",
                    "notes-right", "float", None, "")))

report()
