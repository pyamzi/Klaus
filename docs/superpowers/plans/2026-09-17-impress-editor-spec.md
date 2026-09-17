# Spec: Impress-style PDF editor with per-slide notes

**Date:** 2026-09-17 · **Status:** agreed with Pouya in conversation

## Vision

KlausBook treats **PDFs as the primary filetype** (lecture slide decks);
Markdown is secondary. The PDF editor should feel like editing a deck in
LibreOffice Impress / PowerPoint — "but a bit simpler" — not like reading in
a scrolling viewer. SiYuan (`references/siyuan-master`, AGPLv3 — design
reference ONLY, never copy code) and Obsidian are the aesthetic north star
for the app overall; this spec covers the editor surface.

## Decisions (from the clarifying rounds)

- **Layout: PowerPoint layout.** Filmstrip of page thumbnails down the left,
  one big slide on a center stage (fit-to-stage, keyboard prev/next), and a
  **right sidebar where Markdown notes + images can be added per slide**.
- **Editing = notes, not PDF mutation (this phase).** The slide itself is
  fixed; what you author is the per-slide notes (Markdown text, pasted
  images). Canvas overlays (text boxes/highlights/ink) and bake-into-PDF
  are the next phase (board KB-002/KB-003), not this spec.
- **Storage:** notes are one JSON doc per PDF in KlausBook's own data dir
  (never the klausmate library, which stays read-only), served by
  klaus-core. Pasted images are content-addressed files next to them.
  Baking notes into the PDF happens in the overlay/bake phase.
- **Fork purity:** everything ships in `extensions/klaus-pdf` + klaus-core.
  Zero changes to the KlausBook-Code fork.

## UI in one paragraph

Opening a PDF from the Library shows: a 168px filmstrip (lazy-rendered
thumbnails, current slide highlighted, click to jump), a stage showing the
current slide fitted with a thin toolbar (name, "n / N", zoom −/%/+/Fit),
and a 320px notes sidebar titled "Slide n" with an Edit/Preview toggle, a
Markdown textarea (autosaves, "Saving…/Saved/Save failed" indicator), and
image support: paste or drop an image → uploaded to klaus-core → a
`![](…)` reference inserted at the cursor → rendered in Preview.
Arrow/PageUp/PageDown/Home/End navigate slides unless focus is in the
textarea.

## Data design

- `GET/PUT /notes/{pdf_id}` — doc: `{"version": 1, "pages": {"3": {"md": "…"}}}`
  (page keys are 1-based strings; last-write-wins; atomic tmp+rename write).
- `POST /assets/{pdf_id}` (raw image body, png/jpeg/gif/webp allowlist,
  8 MB cap) → `{"name": "<sha116>.<ext>"}`;
  `GET /assets/{pdf_id}/{name}` serves it. Asset GETs accept the token as a
  `?token=` query param because `<img>` tags cannot send headers.
- Data root: `KLAUS_DATA_DIR` env override (tests), default
  `~/Library/Application Support/Klausbook/` → `notes/<id>.json`,
  `assets/<id>/<name>`. `pdf_id` and asset names are regex-validated to
  block path traversal.

## Out of scope (later plans, in rough order)

1. Canvas overlays (highlight from text selection, text boxes, ink) and the
   pristine-original bake into the PDF — KB-002/KB-003.
2. Deck page ops (reorder/insert/delete via pypdf).
3. Standalone Markdown vault with [[wikilinks]]/backlinks — KB-008.
4. SiYuan/Obsidian-style app chrome and theming (notes-app look, doc-tree
   sidebar, `--vscode-*` theme migration — KB-011).

## Success criteria

Open a lecture PDF → navigate slides by filmstrip and keyboard → type notes
under three different slides → paste a screenshot into one → quit KlausBook
entirely → relaunch → all notes and the image are still there, on the right
slides. `python3 tests/test_notes.py` and the existing suites pass; the
klausmate library's mtimes are untouched.
