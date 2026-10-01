"""K-310: anki_stubs.install() must never leave USER_FILES on the real Library.

klausmate/ is symlinked into Anki's addons21, so klausmate/user_files IS the
user's Library. On 2026-09-28 test_library_sync.py wrote drive.json,
library_map.json and contexts/ there through curation.USER_FILES (now
settings.user_files()). This pins that every user-files path the harness
exposes resolves into one temp dir.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_user_files_guard.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import ADDON, check, install, report, section  # noqa: E402

install()

import klausmate.settings as _settings  # noqa: E402

curation = importlib.import_module("klausmate.curation")
anki_tools = importlib.import_module("klausmate.anki_tools")

REAL = os.path.realpath(os.path.join(ADDON, "user_files"))
TMP = os.path.realpath(tempfile.gettempdir())
paths = {
    "settings.user_files()": _settings.user_files(),
    "curation.index_dir()": os.path.dirname(curation.index_dir()),
    "anki_tools._USER_FILES": anki_tools._USER_FILES,
}

section("no USER_FILES points at the real klausmate/user_files")
for name, p in paths.items():
    real = os.path.realpath(p)
    check(f"{name} is not the real Library", real != REAL, real)
    check(f"{name} is under the temp dir", real.startswith(TMP + os.sep), real)

section("they all agree on one scratch dir")
check("one scratch user_files", len({os.path.realpath(p) for p in paths.values()}) == 1,
      str(paths))
check("the scratch user_files exists", os.path.isdir(_settings.user_files()))

raise SystemExit(report())
