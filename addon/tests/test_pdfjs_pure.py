"""PDF reader 2/5: render cache, per-page mark redraw, incremental find.

tests/pdfjs_pure_test.js tests web/pdfjs_pure.js under node; without node
it is SKIPPED, never counted as a pass. Also checks that the page loads
the helpers before its main script.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdfjs_pure.py
"""
import importlib
import os
import shutil
import subprocess
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
pv = importlib.import_module("klausmate.pdfjs_viewer")

section("the page loads pdfjs_pure.js before its main script")
html = pv.build_page_html("x", night=False)
tag = '<script src="/_addons/x/web/pdfjs_pure.js"></script>'
check("the page template loads the helpers once, by add-on URL",
      html.count(tag) == 1)
check("...before the main page script",
      tag in html and html.index(tag) < html.index('<script>\n"use strict";'))

section("evictable / changedPages / findOrder (node)")
if shutil.which("node"):
    here = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.run(["node", os.path.join(here, "pdfjs_pure_test.js")],
                          capture_output=True, text=True, timeout=60)
    print(proc.stdout.rstrip())
    check("pdfjs_pure.js helpers behave", proc.returncode == 0,
          (proc.stdout + proc.stderr).strip().replace("\n", " | "))
else:
    print("  SKIP  pdfjs_pure.js helpers (node not installed) — NOT counted as a pass")

section("the in-place text box editor, run for real (node)")
if shutil.which("node"):
    here = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.run(["node", os.path.join(here, "pdfjs_textbox_test.js")],
                          capture_output=True, text=True, timeout=60)
    print(proc.stdout.rstrip())
    check("openTextEdit/sizeTextEdit/positionTextEdit/commitTextEdit behave: "
          "measured w/h in the payload, kept boxes kept, --k = 1/scale",
          proc.returncode == 0,
          (proc.stdout + proc.stderr).strip().replace("\n", " | "))
else:
    print("  SKIP  text box editor (node not installed) — NOT counted as a pass")

raise SystemExit(report())
