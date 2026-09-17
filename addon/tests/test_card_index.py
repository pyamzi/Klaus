"""Tests for klausmate.card_index (PR1 review fix): load_row_map must not
crash on a non-dict manifest.

json.load happily returns whatever valid JSON allows — null, a list, a
number — not just an object. The old code went straight to m.get(...),
so a null or [] manifest (a torn write, a hand-edited file) raised
AttributeError, which isn't in load_row_map's except tuple: the
lecture-view lookup (lecture_view.py calls load_row_map on every card
flip) crashed instead of degrading to "no index yet", same as load()'s
own not-an-object guard and read_manifest's isinstance check for the
identical reason.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_card_index.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

card_index = importlib.import_module("klausmate.card_index")

section("load_row_map on a non-dict manifest")

root = tempfile.mkdtemp(prefix="klaus-card-index-")


def _manifest_dir(value) -> str:
    d = tempfile.mkdtemp(dir=root)
    with open(os.path.join(d, card_index.MANIFEST_FILE), "w", encoding="utf-8") as f:
        json.dump(value, f)
    return d


check("a manifest that is JSON null returns None, not AttributeError",
      card_index.load_row_map(_manifest_dir(None)) is None)
check("a manifest that is a JSON array returns None too",
      card_index.load_row_map(_manifest_dir([])) is None)
check("a genuinely missing manifest still returns None (unchanged behaviour)",
      card_index.load_row_map(tempfile.mkdtemp(dir=root)) is None)

raise SystemExit(report())
