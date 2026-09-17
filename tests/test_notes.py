"""klaus-core notes/assets storage suite.

Runs against a scratch data dir via KLAUS_DATA_DIR so the real one is
never touched. Run: python3 tests/test_notes.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ["KLAUS_DATA_DIR"] = tempfile.mkdtemp(prefix="klaus-notes-test-")
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from klaus_core import notes  # noqa: E402

PDF_ID = "0123456789abcdef"
failures = 0


def check(label, ok, detail=""):
    global failures
    if ok:
        print("  ok  " + label)
    else:
        failures += 1
        print(" FAIL " + label + ((" " + str(detail)) if detail else ""))


def raises_value_error(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


print("== notes round trip ==")
check("missing notes load as empty doc",
      notes.load_notes(PDF_ID) == {"version": 1, "pages": {}})
doc = {"version": 1, "pages": {"3": {"md": "renal **stuff**"}}}
notes.save_notes(PDF_ID, doc)
check("saved notes round-trip", notes.load_notes(PDF_ID) == doc)
notes.save_notes(PDF_ID, {"version": 1, "pages": {}})
check("overwrite works", notes.load_notes(PDF_ID) == {"version": 1, "pages": {}})

print("== validation ==")
for bad_id in ("../../etc", "0123456789ABCDEF", "0123", ""):
    check("bad pdf id rejected: %r" % bad_id,
          raises_value_error(lambda b=bad_id: notes.load_notes(b)))
check("bad doc shape rejected",
      raises_value_error(lambda: notes.save_notes(PDF_ID, {"pages": "nope"})))
check("non-dict doc rejected",
      raises_value_error(lambda: notes.save_notes(PDF_ID, ["x"])))

print("== assets ==")
name = notes.save_asset(PDF_ID, b"\x89PNGfake", "png")
check("asset name is content-addressed",
      name == notes.save_asset(PDF_ID, b"\x89PNGfake", "png"), name)
p = notes.asset_path(PDF_ID, name)
check("asset readable back", p is not None and p.read_bytes() == b"\x89PNGfake")
check("different bytes, different name",
      notes.save_asset(PDF_ID, b"other", "png") != name)
check("traversal name refused", notes.asset_path(PDF_ID, "../x.png") is None)
check("unknown asset 404s", notes.asset_path(PDF_ID, "f" * 16 + ".png") is None)
check("bad extension rejected",
      raises_value_error(lambda: notes.save_asset(PDF_ID, b"x", "svg")))

print("\n%d failures" % failures)
sys.exit(1 if failures else 0)
