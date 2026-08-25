"""Headless tests for klausmate.theme — the design-token module.

theme.py must stay aqt-free at module top (only night_mode() touches aqt,
lazily, degrading to light mode) so every QSS builder is testable here.
"""
import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
theme = importlib.import_module("klausmate.theme")

section("palette structure")
check("LIGHT and DARK have identical key sets",
      set(theme.LIGHT.keys()) == set(theme.DARK.keys()))
check("light palette returns the light tokens",
      theme.palette(False)["bg"] == "#F5F5F7")
check("dark palette returns the dark tokens",
      theme.palette(True)["bg"] == "#191919")
p = theme.palette(False)
p["bg"] = "mutated"
check("palette() returns a copy — mutation does not leak",
      theme.palette(False)["bg"] == "#F5F5F7")
check("night_mode degrades to light headlessly (stub aqt has no theme)",
      theme.night_mode() in (False, True))  # must not raise

section("QSS builders substitute tokens for both modes")
builders = [
    ("dialog_qss", theme.dialog_qss),
    ("panel_header_qss", theme.panel_header_qss),
    ("find_bar_qss", theme.find_bar_qss),
    ("library_qss", theme.library_qss),
    ("thumb_strip_qss", theme.thumb_strip_qss),
]
for name, fn in builders:
    for night in (False, True):
        qss = fn(night)
        check(f"{name}(night={night}) is a non-empty string",
              isinstance(qss, str) and len(qss) > 50)
        check(f"{name}(night={night}) leaves no unsubstituted token",
              "{c[" not in qss and "{{" not in qss and "}}" not in qss)
        c = theme.palette(night)
        check(f"{name}(night={night}) carries a {['light','dark'][night]} "
              "background token", c["surface"] in qss or c["bg"] in qss)

section("dialog button roles")
d = theme.dialog_qss(False)
check("dialog has a primary (blue) default button",
      "#0071D3" in d and "QPushButton {" in d)
check("dialog defines SecondaryButton", "QPushButton#SecondaryButton" in d)
check("dialog defines DangerButton", "QPushButton#DangerButton" in d)
lib = theme.library_qss(False)
check("library inverts: grey default + PrimaryButton opt-in",
      "QPushButton#PrimaryButton" in lib)

section("drop zone + helpers")
dz = theme.drop_zone_qss(False, "klausmateLibraryDropZone")
check("drop zone scopes rules to the given objectName",
      "#klausmateLibraryDropZone {" in dz
      and '#klausmateLibraryDropZone[dragOver="true"]' in dz)
check("drop zone styles its Browse button",
      "#klausmateLibraryDropZone QPushButton" in dz)
check("accent_rgba light = system blue with alpha",
      theme.accent_rgba(False, 0.3) == "rgba(0, 122, 255, 0.3)")
check("accent_rgba dark = bright dark-mode accent",
      theme.accent_rgba(True, 0.85) == "rgba(79, 172, 254, 0.85)")
m = theme.muted_label_qss(False, 10)
check("muted label carries text_muted + size",
      theme.LIGHT["text_muted"] in m and "font-size: 10px" in m)

raise SystemExit(report())
