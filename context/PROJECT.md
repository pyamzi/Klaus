# Orientation

**Klausbook** is a standalone PDF-first notetaker for spaced-repetition
learners: organize lecture PDFs and notes, annotate, and connect to Anki
(which keeps doing the flashcards). It is built as a **minimal-patch fork of
VS Code** plus a local Python service, and will grow an AI chat assistant
that follows your notes and retention-driven podcast episodes. It succeeds
the klausmate Anki addon, which shrinks into Klausbook's Anki bridge.

This file is orientation only. The real references are:

- **`README.md`** — architecture, how to run both processes, the roadmap.
- **`context/ROLES.md`** — how the three agent tiers share the board.

## Where things are

| Path | What |
|---|---|
| `core/` | klaus-core: FastAPI service on 127.0.0.1:7863 (PDF library now; annotations, embeddings, chat, podcast later). Venv at `core/.venv`. |
| `extensions/klaus-pdf/` | VS Code extension: Library tree view + PDF.js webview viewer. esbuild via `npm run build`. |
| `board/` | the kanban board, its CLI, and the dashboard |
| `context/` | this file, roles, and the tier prompts |
| `tests/` | headless suites; run with `python3 tests/test_*.py` |
| `../KlausBook-Code/` | the VS Code fork (branch `klaus`, remote `upstream`). Branding/product.json only — features live in extensions. |
| `../KlausMate-Context/klausmate/user_files/` | the human's real PDF library. klaus-core reads it **read-only**; never write there. |

## Working here

```bash
python3 board/board.py list                       # the board
python3 board/serve.py                            # dashboard → 127.0.0.1:8765
for t in tests/test_*.py; do python3 "$t" || break; done   # all suites
cd core && .venv/bin/uvicorn klaus_core.app:app --host 127.0.0.1 --port 7863
cd ../KlausBook-Code && fnm exec --using=v24.18.0 ./scripts/code.sh \
  --extensionDevelopmentPath="$PWD/../KlausBook-Context/extensions/klaus-pdf"
```

The fork's Node is pinned by its `.nvmrc` (24.18.0, via fnm); the system
Python is 3.9, so board/test code needs `from __future__ import annotations`.

## Current focus

Milestone 1 (walking skeleton) is done: the fork builds and runs, the
extension lists the library from klaus-core and renders PDFs with a
selectable text layer. Next up, in rough order: bundle the extension as a
built-in, port klausmate's annotation/bake model, then the embedding index
and the Anki bridge. The board's Backlog holds the sliced version of this.
