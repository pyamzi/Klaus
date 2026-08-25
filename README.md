# Klaus

The ultimate PDF reader / notetaker for spaced-repetition learners. Klaus
organizes lecture PDFs and notes, connects to Anki (which keeps doing the
flashcards), and will grow an AI chat assistant that follows your notes plus
retention-driven podcast episodes. Standalone successor to the klausmate
Anki addon, which becomes Klaus's Anki bridge.

## Architecture

Klaus is a **minimal-patch fork of VS Code** (Electron) so the whole VS Code
extension ecosystem keeps working (via Open VSX). Klaus features live in
bundled extensions and webviews, not core patches — core changes stay
limited to branding/product.json so upstream merges stay cheap.

```
klaus/        this repo — the product
  core/         klaus-core: local Python service (FastAPI). PDF library now;
                annotations, embeddings/semantic search, chat agent, and the
                podcast pipeline later. Stays free of GUI imports.
  extensions/   Klaus's own VS Code extensions
    klaus-pdf/    PDF library view + PDF.js custom-editor webview
                  (webview-src/ holds the React viewer, pending extension wiring)

klaus-code/   sibling repo — the VS Code fork (branch `klaus`, remote
              `upstream` = microsoft/vscode). Branding + product.json only.
```

The UI talks to klaus-core over localhost HTTP (`127.0.0.1:7863`) with a
shared secret in the `X-Klaus-Token` header (`KLAUS_CORE_TOKEN`, default
`dev`).

Milestone 1 (current): read-only library + viewer. Core lists PDFs from the
existing klausmate library (`…/Addons/klausmate/user_files/{pdfs,pdf_originals}`,
baked copies shadow pristine originals) and never writes there. Override the
library location with `KLAUS_LIBRARY_DIR`.

## Run (dev)

Core:

```bash
cd core && .venv/bin/uvicorn klaus_core.app:app --host 127.0.0.1 --port 7863
```

(First time: `python3 -m venv core/.venv && core/.venv/bin/pip install fastapi 'uvicorn[standard]'`.)

Fork (first build takes a while; Node version pinned by `.nvmrc`):

```bash
cd ../klaus-code && npm i && npm run compile && ./scripts/code.sh
```

## Constraints inherited by forking

- Extension gallery is Open VSX, not Microsoft's Marketplace (license).
- Microsoft-proprietary extensions (Pylance, Remote-SSH, Live Share, C/C++)
  license-check for genuine VS Code and do not run on forks.
- Upstream ships monthly; the minimal-patch rule exists to keep those merges
  near-trivial.

## Roadmap

1. Walking skeleton: vanilla fork builds and runs; klaus-pdf extension shows
   the library and renders PDFs from klaus-core
2. Branding (product.json, icons) — Klaus, not Code OSS
3. Annotations + per-slide notes (JSON source of truth, baked into the PDF
   from a pristine original — klausmate's bake model, ported)
4. Embedding index + semantic search across the library (Voyage default)
5. Anki bridge addon (slim klausmate) → retention scoring, deck curation
6. Chat assistant with tools; HTML pane as the AI's canvas
7. Retention-driven podcast episodes ("what you're about to forget")
8. Packaging/signing; web version via openvscode-server + hosted core
