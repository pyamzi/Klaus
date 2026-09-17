# Orientation

**klausmate** is an Anki add-on: a lecture-PDF Library, semantic matching
of the collection against each PDF, a PDF viewer with highlights, and
per-PDF retention scoring. (Autocomplete, ⌘K Ask and the chat panel were
deleted in 2026-08 — see CLAUDE.md.) It runs inside Anki 26.8.1 on PyQt6, in stdlib Python
plus a vendored pypdf. Roughly 18k lines, mostly in `klausmate/`.

This file is orientation only. The real references are:

- **`CLAUDE.md`** — how Anki loads the add-on, the module map, and the
  hard-won gotchas. Read this before touching add-on code.
- **`AGENTS.md`** — architecture and conventions. (Parts are stale; see K-003.)
- **`context/ROLES.md`** — how the three agent tiers share the board.

## Where things are

| Path | What |
|---|---|
| `klausmate/` | the add-on; `__init__.py` is the bootstrap and most of the UI |
| `klausmate/user_files/` | the human's real PDFs and indexes — never write here |
| `tests/` | headless suites; run with `python3 tests/test_*.py` |
| `board/` | the kanban board, its CLI, and the dashboard |
| `context/` | this file, roles, and the tier prompts |

## Working here

```bash
python3 board/board.py list                       # the board
python3 board/serve.py                            # dashboard → 127.0.0.1:8765
for t in tests/test_*.py; do python3 "$t" || break; done   # all suites
```

Anki loads the add-on through a symlink to this checkout, so changes are
live after an Anki restart — but only from the main checkout, never from a
git worktree copy.

## Current focus

The PDF drive window and the deck-screen PDF drop square are newly built
and have not been exercised in a live Anki yet (K-001). Docs lag the code in
two places (K-003, K-005). `klausmate/__init__.py` is overgrown at ~6k lines
and needs slicing before it can be worked on in parallel (K-006).
