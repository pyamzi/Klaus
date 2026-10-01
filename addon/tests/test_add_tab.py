"""The Add tab (spec docs/superpowers/specs/2026-10-01-add-tab-design.md):
what the design REMOVED stays removed — the PDF dock, its title bar, its
placement memory, the editor-toolbar "Library…" button, the dock toggles
and the single window's dock plumbing — and a pdf_tabs.json from an older
build loses its placement keys quietly. The tab's own behaviour is pinned
in tests/test_single_window.py (host, routing, keys) and
tests/test_library_viewer.py / tests/test_reader_host.py (the reader).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_add_tab.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

UF = tempfile.mkdtemp(prefix="klaus-addtab-")

section("removed")
src_init = open("klausmate/__init__.py").read()
src_js = open("klausmate/web/copilot.js").read()
check("no PDF dock, panel bar or Library button in __init__",
      not any(n in src_init for n in ("class PdfDock", "class _PanelBar", "_on_library_button", "_ensure_sidebar_pdf",
                                      "def on_editor_did_init", 'action == "library"', "_klausmate_pdf_tabs",
                                      "_klausmate_pdf_container", "PANEL_AREAS", "editor_did_init.append")),
      str([n for n in ("class PdfDock", "class _PanelBar", "_on_library_button", "_ensure_sidebar_pdf",
                       "def on_editor_did_init", 'action == "library"', "_klausmate_pdf_tabs",
                       "_klausmate_pdf_container", "PANEL_AREAS", "editor_did_init.append") if n in src_init]))
check("no Library button in copilot.js", "klausmate-library-btn" not in src_js and "klausmate:library" not in src_js
      and "Library..." not in src_js)
ph = importlib.import_module("klausmate.pdf_handler")
check("no placement state in pdf_handler",
      not any(hasattr(ph, n) for n in ("migrate_placement", "load_panel_state", "save_panel_state", "PANEL_PLACEMENTS", "_LEGACY_PLACEMENTS")))
sw = importlib.import_module("klausmate.single_window")
check("no dock registration or PDF retarget in the single window",
      not any(hasattr(sw, n) for n in ("host_for", "register_dock", "_retarget_pdf", "toggle_dock", "make_add_dock")))
check("no reader attribute on editors anywhere in the package",
      not any("_klausmate_pdf_tabs" in open(os.path.join("klausmate", f)).read() or "_klausmate_sidebar" in open(os.path.join("klausmate", f)).read()
              for f in os.listdir("klausmate") if f.endswith(".py")))
check("the deleted test file is gone", not os.path.exists("tests/test_pdf_dock.py"))

section("legacy placement keys are dropped on read and on save")
json.dump({"placement": "float", "geom": [1, 2, 3, 4], "tabs": {"editor": ["A"]}},
          open(os.path.join(UF, "pdf_tabs.json"), "w"))
check("read ignores them", set(ph._load_tabs_file(UF)) == {"tabs"}, str(ph._load_tabs_file(UF)))
ph.save_open_tabs(UF, ["A"], "editor")
check("the next save drops them from disk", set(json.load(open(os.path.join(UF, "pdf_tabs.json")))) == {"tabs"},
      str(json.load(open(os.path.join(UF, "pdf_tabs.json")))))
check("an empty or corrupt file still reads as {}", ph._load_tabs_file(tempfile.mkdtemp()) == {})

raise SystemExit(report())
