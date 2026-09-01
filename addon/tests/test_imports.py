"""Import-smoke test: every klausmate/*.py module, one pass/fail line each.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py

Why this exists (K-008): the human reported the PDF drive window does not
open at all in live Anki. `klausmate/__init__.py` wraps both
`from . import pdf_drive as _pdf_drive; _pdf_drive.setup()` and the
equivalent for `pdf_drop` in a `try/except Exception` that only prints —
so an ImportError or NameError anywhere in pdf_drive.py's own module-level
code would be swallowed silently and the window would just never register,
with no trace beyond a buried `print()` in Anki's console.

Nothing caught this before now: the old `aqt.qt` stub in
`.claude/skills/klaus-test/scripts/anki_stubs.py` only defined QAction,
QInputDialog, QMessageBox, QTimer and qconnect, so `from aqt.qt import
QWidget` (or any of the ~55 other Qt names klausmate actually imports)
raised before either pdf_drive.py's or pdf_drop.py's own code ever ran —
meaning those modules had literally never been import-tested. anki_stubs.py
now stubs aqt/anki permissively (see its module docstring); this test uses
that to import every klausmate module directly, bypassing __init__.py's
swallowing try/except, so a genuine import-time bug shows up as a hard FAIL
here instead of a buried print.
"""
from __future__ import annotations

import glob
import importlib
import importlib.util
import os
import sys
import traceback

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import ADDON, check, install, report, section  # noqa: E402


def _submodule_names() -> list[str]:
    """Every klausmate/*.py file directly under the package (no vendor/,
    no __pycache__ — the glob is non-recursive so subdirectories are never
    matched), as bare module stems, sorted for stable output. `__init__`
    is handled separately below.
    """
    paths = sorted(glob.glob(os.path.join(ADDON, "*.py")))
    names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    names.remove("__init__")
    return names


def _check_import(dotted: str) -> None:
    try:
        importlib.import_module(dotted)
    except Exception as e:  # noqa: BLE001 - a bad module should FAIL, not crash the run
        traceback.print_exc()
        check(f"import {dotted}", False, f"- {type(e).__name__}: {e}")
    else:
        check(f"import {dotted}", True)


def main() -> int:
    install()

    section("klausmate submodule imports")
    for name in _submodule_names():
        _check_import(f"klausmate.{name}")

    # install() (via install_package_stub) deliberately registers a
    # *lightweight* stand-in for the "klausmate" package itself — an empty
    # module whose __path__ points at the working tree — so that the
    # relative imports (`from . import curation`, etc.) inside every
    # submodule above resolve without ever running the real __init__.py.
    # That's the right call for every OTHER test in this suite (nobody
    # wants __init__.py's ~6k-line bootstrap running just to test
    # retention math), but it means a plain
    # `importlib.import_module("klausmate")` here would just return that
    # already-cached stand-in and vacuously "pass" without importing
    # anything — for exactly the file where the human's bug report points.
    # Load the real __init__.py from disk and execute it under the
    # "klausmate" name instead, so its own module-level code (including
    # the try/except around pdf_drive/pdf_drop setup()) actually runs.
    section("klausmate package bootstrap (__init__.py)")
    init_path = os.path.join(ADDON, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "klausmate", init_path, submodule_search_locations=[ADDON]
    )
    real_init = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("klausmate")
    sys.modules["klausmate"] = real_init
    try:
        spec.loader.exec_module(real_init)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        check("import klausmate (__init__.py)", False, f"- {type(e).__name__}: {e}")
        sys.modules["klausmate"] = previous  # restore the lightweight stand-in
    else:
        check("import klausmate (__init__.py)", True)

    return report()


if __name__ == "__main__":
    raise SystemExit(main())
