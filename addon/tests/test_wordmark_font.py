"""The Preferences wordmark is set in Excalifont (Pouya, 2026-10-01).

The font ships as klaus_note/web/fonts/Excalifont-Regular.ttf (built by
scripts/build_excalifont.sh) and theme registers it once, from bytes, the
first time the dialog stylesheet is built.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_wordmark_font.py
"""
import importlib
import os
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
theme = importlib.import_module("klaus_note.theme")

FONT = os.path.join("klaus_note", "web", "fonts", "Excalifont-Regular.ttf")

section("the font file")
check("Excalifont-Regular.ttf ships with the add-on", os.path.isfile(FONT))
check("its licence ships beside it",
      os.path.isfile(os.path.join("klaus_note", "web", "fonts", "LICENSE-excalidraw.txt")))
check("the build script that makes it is kept", os.path.isfile("scripts/build_excalifont.sh"))
_lic = open(os.path.join("klaus_note", "web", "fonts", "LICENSE-excalidraw.txt"), encoding="utf-8").read()
check("the licence is Excalifont's real one, the SIL Open Font License 1.1 (Excalidraw's own font notes say so)",
      "SIL OPEN FONT LICENSE Version 1.1" in _lic and "(license: MIT)" not in _lic
      and "Copyright (c) 2024 by Excalidraw" in _lic)

section("the wordmark rule")
qss = theme.dialog_qss(False)
m = re.search(r"QLabel#SidebarAppName\s*\{([^}]*)\}", qss)
rule = m.group(1) if m else ""
fam = re.search(r"font-family:\s*([^;]+);", rule)
check("the wordmark's first font is Excalifont",
      bool(fam) and fam.group(1).split(",")[0].strip().strip('"') == "Excalifont",
      rule)
check("the 18px wordmark size stays", "font-size: 18px" in rule)
check("no light weight (Excalifont has one weight)", "font-weight: 300" not in rule)

section("registration")
_aqt_qt = sys.modules["aqt.qt"]  # the harness stub; give it the real classes
from PyQt6.QtCore import QByteArray  # noqa: E402
from PyQt6.QtGui import QFontDatabase, QGuiApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

for _n, _v in (("QByteArray", QByteArray), ("QFontDatabase", QFontDatabase),
               ("QGuiApplication", QGuiApplication)):
    setattr(_aqt_qt, _n, _v)
app = QApplication.instance() or QApplication([])
check("registering returns the Excalifont family", theme.register_wordmark_font() == "Excalifont")
check("a second call is a no-op returning the same family",
      theme.register_wordmark_font() == "Excalifont")
check("Qt now knows the family", "Excalifont" in QFontDatabase.families())

raise SystemExit(report())
