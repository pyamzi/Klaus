"""PDF reader 2/5: library_stats.json sidecar for closed-file change detection.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_library_stats.py
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
ph = importlib.import_module("klausmate.pdf_handler")


def world(tmp: str):
    uf = os.path.join(tmp, "uf")
    root = os.path.join(tmp, "Library")
    os.makedirs(uf)
    os.makedirs(root)
    p = os.path.join(root, "a.pdf")
    with open(p, "wb") as f:
        f.write(b"%PDF-1.4 one")
    return uf, root, p, {"a": "a.pdf"}


section("round trip and corrupt")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, p, m = world(tmp)
    check("absent reads empty", ph.load_library_stats(uf) == {})
    st = ph.file_stat(p)
    ph.record_stat(uf, "a", st)
    check("round trip is [size, mtime_ns]",
          ph.load_library_stats(uf) == {"a": [st[2], st[1]]})
    ph.record_stat(uf, "a", None)
    check("None removes the entry", ph.load_library_stats(uf) == {})
    with open(os.path.join(uf, "library_stats.json"), "w") as f:
        f.write("{not json")
    check("corrupt reads empty", ph.load_library_stats(uf) == {})
    ph.record_stat(uf, "a", st)
    check("record_stat heals a corrupt file",
          ph.load_library_stats(uf) == {"a": [st[2], st[1]]})

section("reserved keys")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, p, m = world(tmp)
    with open(os.path.join(uf, "library_stats.json"), "w") as f:
        json.dump({"__missing__": {"a": 1}, "b": [1, 2]}, f)
    check("readers skip __ keys", ph.load_library_stats(uf) == {"b": [1, 2]})
    ph.record_stat(uf, "a", ph.file_stat(p))
    with open(os.path.join(uf, "library_stats.json")) as f:
        raw = json.load(f)
    check("record_stat preserves __ keys", raw.get("__missing__") == {"a": 1})
    ph.record_stat(uf, "a", None)
    with open(os.path.join(uf, "library_stats.json")) as f:
        raw = json.load(f)
    check("removal preserves __ keys too", raw.get("__missing__") == {"a": 1})
    m2 = {"__missing__": "x.pdf", "a": "a.pdf"}
    check("a __ name in the mapping is never reported",
          ph.changed_since_recorded(uf, root, m2) == [])
    check("and never recorded", "__missing__" not in ph.load_library_stats(uf))

section("changed_since_recorded")
with tempfile.TemporaryDirectory() as tmp:
    uf, root, p, m = world(tmp)
    check("first call records without reporting",
          ph.changed_since_recorded(uf, root, m) == [])
    check("the first call recorded it", "a" in ph.load_library_stats(uf))
    check("unchanged reports nothing",
          ph.changed_since_recorded(uf, root, m) == [])
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    check("a touched file is reported", ph.changed_since_recorded(uf, root, m) == ["a"])
    check("and only once", ph.changed_since_recorded(uf, root, m) == [])
    with open(p, "ab") as f:
        f.write(b"more")
    ph.record_stat(uf, "a", ph.file_stat(p))
    check("record_stat after a Klaus write suppresses the report",
          ph.changed_since_recorded(uf, root, m) == [])
    os.remove(p)
    check("a missing file is not reported",
          ph.changed_since_recorded(uf, root, m) == [])
    check("and keeps its record", "a" in ph.load_library_stats(uf))

raise SystemExit(report())
