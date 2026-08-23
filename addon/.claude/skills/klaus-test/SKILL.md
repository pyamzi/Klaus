---
name: klaus-test
description: Write and run headless tests for the klausmate Anki addon. Use when adding or changing klausmate Python modules, when verifying addon logic without launching Anki, or when the user asks to test klausmate. Provides the aqt-stub bootstrap that makes importing addon modules possible under this machine's Python.
---

# Testing klausmate headlessly

Anki's Python cannot be used to test this addon, and the addon cannot be
imported normally. This skill provides the workaround and the conventions.

## The constraint

- Anki 26.8.1 ships **3.13 bytecode only** at
  `/Applications/Anki.app/Contents/Resources/app_packages`; this machine's
  `python3` is **3.9**. `import aqt` fails with `bad magic number`.
- PyQt6 there is **not** loadable either — `sip` is a 3.13-only extension,
  not abi3. **Qt widgets cannot be instantiated or rendered in tests.**
  Layout and appearance can only be checked by restarting Anki and looking.
- Therefore: test *logic*, never *widgets*.

## Writing a test

Put tests in `tests/` at the repo root. Start with the bundled bootstrap:

```python
import sys, importlib
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import install, check, section, report

install()                     # synthetic klausmate package + aqt/anki stubs
retention = importlib.import_module("klausmate.retention")

section("retention math")
check("R at t=s is 0.90", abs(retention.fsrs_retrievability(10, 0.5, 10) - 0.9) < 1e-9)

raise SystemExit(report())
```

`install()` registers a synthetic `klausmate` package pointing at the
working tree, plus stub `aqt`, `aqt.operations`, `aqt.utils`, `aqt.qt`,
`aqt.gui_hooks`, `anki`, and `anki.collection`. Modules that are already
aqt-free (`embeddings`, `card_index`, `pdf_index`, `drive_store`) need only
`install_package_stub()`.

Run with `env QT_QPA_PLATFORM=offscreen python3 tests/<name>.py`.

## What to test, and how

**Provider HTTP** — spin a stdlib `http.server` and repoint the module
globals that exist for exactly this purpose:
`embeddings.VOYAGE_API_BASE` / `OPENAI_API_BASE`. Assert retry behaviour by
scripting status codes (429 + `Retry-After`, then 200).

**Collection access** — never touch the real collection. Fake it:

```python
class FakeDB:
    def __init__(self, rows): self.rows = rows
    def all(self, sql): return self.rows
class FakeCol:
    def __init__(self, rows): self.db = FakeDB(rows)
```

To validate against *real* scheduling data, open the collection read-only:
`sqlite3.connect("file:...collection.anki2?immutable=1", uri=True)`.

**Qt-shaped state machines** (dialog logic) — model the widget semantics in
a small fake class (a `Combo` with `items`/`index`/`currentData` and a
change signal) and transcribe the handler logic onto it. This caught a real
bug: with an empty model library, "Claude API…" being the only dropdown item
silently flipped the configured engine.

## Hard rules

- **Never point tests at `klausmate/user_files/`** — it holds real PDFs,
  annotations, and the card index. Use `tempfile.mkdtemp()` and pass that as
  `user_files_dir`; every storage function takes it as its first argument.
  (Project settings also deny writes there.)
- Every new module needs `from __future__ import annotations` so `str | None`
  annotations compile under 3.9.
- Syntax-check through the symlink, which also proves Anki is loading this
  tree: `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`
  (the PostToolUse hook does this automatically on every edit).

## Existing suites

`tests/test_klausmate.py` (embeddings, pdf_index, retention math),
`tests/test_drive.py` (drive_store, deck_curate helpers),
`tests/test_dialog_logic.py` (Manage-models dialog state machine).
Run all three after any change to the modules they cover.
