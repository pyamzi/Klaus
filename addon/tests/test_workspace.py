"""Headless tests for the Klaus Workspace (K-102).

Covers the aqt-free helpers and the contracts the shell depends on.
The window itself is Qt and can only be verified live — see the K-102
card's live checklist.
"""
import importlib
import json
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
ws = importlib.import_module("klausmate.workspace")
drive_store = importlib.import_module("klausmate.drive_store")

section("flag resolution (default OFF)")
check("empty config -> off", ws.workspace_from_config({}) is False)
check("explicit true -> on", ws.workspace_from_config({"workspace_enabled": True}) is True)
check("explicit false -> off", ws.workspace_from_config({"workspace_enabled": False}) is False)
check("truthy non-bool degrades to off (strict opt-in)",
      ws.workspace_from_config({"workspace_enabled": 1}) is False)
check("non-dict degrades to off", ws.workspace_from_config(None) is False)

section("nav registry")
check("six entries", len(ws.NAV_ITEMS) == 6)
check("Library is first and is the only view",
      ws.NAV_ITEMS[0] == ("library", "Library", "view")
      and [k for k, _l, kind in ws.NAV_ITEMS if kind == "view"] == ["library"])
check("the five Anki surfaces are launchers",
      [k for k, _l, kind in ws.NAV_ITEMS if kind == "launcher"]
      == ["decks", "add", "browse", "stats", "sync"])

section("launcher mapping")
for key, _label, kind in ws.NAV_ITEMS:
    if kind == "launcher":
        check(f"launcher_action('{key}') is callable",
              callable(ws.launcher_action(key)))
check("view keys have no launcher", ws.launcher_action("library") is None)
check("unknown keys have no launcher", ws.launcher_action("nope") is None)

section("hosted DriveWindow surface (duck-typed by shared code)")
pdf_drive = importlib.import_module("klausmate.pdf_drive")
for attr in ("shutdown", "_alive", "_refresh_rows", "_save_geometry",
             "_restore_geometry"):
    check(f"DriveWindow has {attr}", hasattr(pdf_drive.DriveWindow, attr))
check("WorkspaceWindow declares silentlyClose (aqt.dialogs contract)",
      getattr(ws.WorkspaceWindow, "silentlyClose", False) is True)

section("drive_store keyed window state")
tmp = tempfile.mkdtemp()
drive_store.save_window_state(tmp, {"x": 1, "y": 2, "w": 800, "h": 600})
drive_store.save_window_state(
    tmp, {"x": 9, "y": 8, "w": 1200, "h": 720}, key="workspace_window")
check("default key reads the standalone window state",
      drive_store.get_window_state(tmp)["w"] == 800)
check("workspace key reads its own state",
      drive_store.get_window_state(tmp, key="workspace_window")["w"] == 1200)
# The regression that matters: load() whitelists keys, so a later save
# through the normal path must not drop the workspace geometry.
drive_store.save_window_state(tmp, {"x": 3, "y": 4, "w": 900, "h": 650})
check("workspace geometry survives an unrelated save cycle",
      drive_store.get_window_state(tmp, key="workspace_window")["w"] == 1200)
check("standalone geometry updated independently",
      drive_store.get_window_state(tmp)["w"] == 900)

section("config default")
here = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(here, "..", "klausmate", "config.json")))
check("config.json defaults workspace_enabled to false",
      cfg.get("workspace_enabled") is False)

section("theme builder")
theme = importlib.import_module("klausmate.theme")
for night in (False, True):
    qss = theme.workspace_qss(night)
    c = theme.palette(night)
    check(f"workspace_qss(night={night}) carries surface + accent",
          c["surface"] in qss and c["blue"] in qss)
    check(f"workspace_qss(night={night}) leaves no unsubstituted token",
          "{c[" not in qss and "{{" not in qss)
check("sidebar rail is objectName-scoped",
      "KlausWorkspaceSidebar" in theme.workspace_qss(False))

raise SystemExit(report())
