# Klausbook

The ultimate PDF reader / notetaker for spaced-repetition learners.
Klausbook organizes lecture PDFs and notes, connects to Anki (which keeps
doing the flashcards), and will grow an AI chat assistant that follows your
notes plus retention-driven podcast episodes. Klausbook is the standalone
successor to the klausmate Anki addon, which becomes Klausbook's Anki
bridge.

## Architecture

Klausbook is a **minimal-patch fork of VS Code** (Electron) so the whole
VS Code extension ecosystem keeps working (via Open VSX). Klausbook
features live in bundled extensions and webviews, not core patches — core
changes stay limited to branding/product.json so upstream merges stay
cheap.

```
klausbook/        this repo — the product
  core/             klaus-core: local Python service (FastAPI). PDF library now;
                    annotations, embeddings/semantic search, chat agent, and the
                    podcast pipeline later. Stays free of GUI imports.
  extensions/       Klausbook's own VS Code extensions
    klaus-pdf/        PDF library view + PDF.js webview viewer
  board/            the kanban board: BOARD.md + CLI + dashboard
  context/          agent-tier docs: ROLES.md, PROJECT.md, prompts/
  tests/            headless suites (python3 tests/test_*.py)

klausbook-code/   sibling repo — the VS Code fork (branch `klaus`, remote
                  `upstream` = microsoft/vscode). Branding + product.json only.
```

The UI talks to klaus-core over localhost HTTP (`127.0.0.1:7863`) with a
shared secret in the `X-Klaus-Token` header (`KLAUS_CORE_TOKEN`, default
`dev`).

Milestone 1 (done): read-only library + viewer. Core lists PDFs from the
existing klausmate library (`…/Addons/klausmate/user_files/{pdfs,pdf_originals}`,
baked copies shadow pristine originals) and never writes there. Override the
library location with `KLAUS_LIBRARY_DIR`.

## Run (dev)

Core:

```bash
cd core && .venv/bin/uvicorn klaus_core.app:app --host 127.0.0.1 --port 7863
```

(First time: `python3 -m venv core/.venv && core/.venv/bin/pip install fastapi 'uvicorn[standard]'`.)

Fork (Node pinned by its `.nvmrc` — 24.18.0 via fnm):

```bash
cd ../klausbook-code && fnm exec --using=v24.18.0 ./scripts/code.sh \
  --extensionDevelopmentPath="$PWD/../klausbook/extensions/klaus-pdf"
```

## The PDF editor

Opening a PDF from the Library shows an Impress-style editor: a filmstrip
of slide thumbnails (click or Arrow/PageUp/PageDown/Home/End to navigate),
the current slide on the stage (zoom −/+/Fit), and a notes sidebar on the
right. Notes are per-slide Markdown with an Edit/Preview toggle; paste or
drop an image to embed it. Everything autosaves to klaus-core under
`~/Library/Application Support/Klausbook/` (`KLAUS_DATA_DIR` overrides;
tests use a scratch dir). The klausmate library itself is never written.

## The board

All project work is tracked on a kanban board (same system as the klausmate
repo): `board/BOARD.md` is the source of truth, and every state change goes
through the CLI so parallel agents cannot collide. Card ids are `KB-###`.

```bash
python3 board/board.py list          # the board
python3 board/board.py show KB-001   # one card in full
python3 board/serve.py               # dashboard → 127.0.0.1:8765
python3 tests/test_board.py          # board engine suite
```

Roles, column gates, and grooming rules: `context/ROLES.md`. Tier briefs
for agents: `context/prompts/worker.md` and `context/prompts/designer.md`.

## Constraints inherited by forking

- Extension gallery is Open VSX, not Microsoft's Marketplace (license).
- Microsoft-proprietary extensions (Pylance, Remote-SSH, Live Share, C/C++)
  license-check for genuine VS Code and do not run on forks.
- Upstream ships monthly; the minimal-patch rule exists to keep those merges
  near-trivial.

## Roadmap

The live version is the board (`python3 board/board.py list`). In rough
order: bundle klaus-pdf as a built-in → port klausmate's annotation/bake
model → embedding index + semantic search → Anki bridge + retention →
chat assistant + Markdown notes → retention-driven podcast → packaging,
then a web version via openvscode-server + hosted core.
