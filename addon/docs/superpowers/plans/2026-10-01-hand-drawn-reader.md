# Hand-drawn Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Klaus's PDF reader draws highlights as seeded rough.js marker bands, text boxes and notes in Excalifont, highlight notes as draggable hand-drawn cards, and free-standing sticky notes from a new Note tool; a "Hand-drawn style" switch restores today's look; the PDF file keeps standard marks in Helvetica, with notes as plain cards.

**Architecture:** A third record kind (`kind:"note"`) and an optional `card` offset on highlights flow through the existing validate → save → bake → push chain. The page renders from records as today, switching per `klausSetHandDrawn` between today's divs and an SVG/card renderer that uses a vendored rough.js and two pure helpers (`seedFor`, `cardSpot`). The bake learns notes only; nothing in it depends on the switch.

**Tech Stack:** Python 3.13 / PyQt6 6.11 via `aqt.qt`, Anki 26.09.2; pdf.js page (`pdfjs_viewer.html`); rough.js 4.6.x (MIT); vendored pypdf; offscreen tests with `anki_stubs`, node tests for `pdfjs_pure.js`.

**Spec:** `docs/superpowers/specs/2026-10-01-hand-drawn-reader-design.md`

## Global Constraints

- The PDF file never depends on the switch; nothing is embedded; `/FreeText` keeps `/DA /Helv`; no `/AP`, `/DR` or `/AcroForm` anywhere (existing pin `tests/test_klausmate.py:2732`).
- Record kinds: highlight `{id, page, rects, color, note[, card]}`; text `{id, kind:"text", page, rects, text, note, color, size}`; note `{id, kind:"note", page, rects:[[x,y,w,h]], text, color, size}`. Rects in page points, top-left origin. `card: [dx, dy]` in page points relative to the highlight's union top-right. Version stays 1; no migration.
- Seeds are `seedFor(id)`, never stored. Roughness 1 (Excalidraw "artist"), fixed. Highlight ink alpha 0.43, `mix-blend-mode: multiply`, band 2 pt taller than the rect.
- Default card spot: 8 pt right of the highlight union's right edge, top-aligned with it, clamped inside the page.
- Note size default 12 pt and the existing `TEXT_SIZES` stepper; note ink one of the five `theme.HIGHLIGHT_INKS` names, default yellow; note text ≤ `MAX_TEXT_CHARS` (4000); card box capped at `TEXT_BOX_MAX_W/H` (480×720).
- Hand-drawn font stack exactly `"Excalifont", sans-serif`; switch off is today's `Helvetica, Arial, sans-serif`.
- Copy, exact: switch "Hand-drawn style"; annobar button title "Add Note"; card menu "Edit Note", "Remove Note".
- No app-modal `exec()` (K-114); new `_bridge_*` handlers defer dialogs with `QTimer.singleShot(0)` (auto-found by `tests/test_bridge_reentrancy.py`).
- Keep the Image Occlusion hooks pinned by `tests/test_reader_occlude.py` working: the `/* occlusion-items:start */` block (`occlusionItems`, `renderRegionCanvas` at scale 2, `klausSetOcclusionEnabled`), `_bridge_occlude_image`, `_bridge_draw_diagram`, `_bridge_toast`, `_finite`, `excal_masks.png_size`, `PdfSidebar._editor` pushing occlusion state.
- Tests use temp dirs only; never touch `klausmate/user_files` or `meta.json`. Never drive the running Anki. No commit per task; Pouya asks for commits, and staging follows the shared-index rule (stage by name, verify on an exported staged tree, HEAD + tree guard in the commit command).
- One file: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/<file>.py`. Suite: `failed=0; for t in tests/test_*.py; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 "$t" || failed=1; done; test "$failed" -eq 0`.

## Review Focus

1. Removing a highlight that has a note card: the card and its line go with it, in the page and in the file (pinned in Task 4 and Task 6).
2. Zoom, soft relayout and reopen: the same wobble, cards and lines move with the page scale (pinned in Task 2 for the seed; Task 6 source pin that cards position in points × `state.scale`).
3. A note left empty or whitespace-only on blur is removed, never saved empty (pinned in Task 3 validation and Task 7 page pin).
4. Right-click on a card still offers the occlusion items and zoom items after the card items (pinned in Task 7).
5. An outside app's `/FreeText` is adopted as a text box, never as a note; Klaus's own `:note` cards are regenerated, not adopted (pinned in Task 4).

---

### Task 1: Excalifont served to the page, licence corrected, rough.js vendored

**Files:**
- Modify: `klausmate/__init__.py` (the `setWebExports` pattern), `klausmate/web/fonts/LICENSE-excalidraw.txt`, `klausmate/web/pdfjs_viewer.html` (head: `@font-face`, script tag)
- Create: `klausmate/web/rough.min.js`, `klausmate/web/LICENSE-roughjs.txt`, `scripts/build_roughjs.sh`
- Test: `tests/test_wordmark_font.py`, `tests/test_pdfjs_viewer.py`

**Interfaces:**
- Produces: the page has `@font-face { font-family: "Excalifont"; src: url("/_addons/__ADDON__/web/fonts/Excalifont-Regular.ttf"); }`; `window.rough` exists before the main script runs.

- [ ] **Step 1: Write the failing tests.**
  - `test_wordmark_font.py`: `LICENSE-excalidraw.txt` names "SIL Open Font License 1.1" for Excalifont and no longer says MIT for it (Excalidraw's own `image_occlusion/excalidraw/fonts/LICENSES.txt:18` is the source).
  - `test_pdfjs_viewer.py`: the first `setWebExports` pattern string matches `web/fonts/Excalifont-Regular.ttf` and `web/rough.min.js` (compile it with `re`); the template contains the `@font-face` above; `rough.min.js` is loaded by a `<script src>` before the main inline script and after `pdfjs_pure.js`; `LICENSE-roughjs.txt` exists and names MIT; `scripts/build_roughjs.sh` pins `roughjs@4.6.6`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Widen the web-exports `web/` group to `web/.*\.(css|js|ttf)` (one string literal, as the comment requires). `build_roughjs.sh` runs `npm pack roughjs@4.6.6` into a temp dir and copies `package/bundled/rough.js` to `klausmate/web/rough.min.js` and its licence; run it once and commit the output. Correct the Excalifont licence text (copyright line and OFL-1.1 text or URL as Excalidraw ships it).
- [ ] **Step 4: Run, expect PASS** (`test_wordmark_font.py`, `test_pdfjs_viewer.py`, `test_pdfjs_pure.py`).

---

### Task 2: `seedFor` and `cardSpot` (pure)

**Files:**
- Modify: `klausmate/web/pdfjs_pure.js`
- Test: `tests/pdfjs_pure_test.js` (run by `tests/test_pdfjs_pure.py`)

**Interfaces:**
- Produces: `seedFor(id: string) -> int` (32-bit unsigned, FNV-1a over the id's UTF-16 code units, never 0: 0 maps to 1, since rough.js treats seed 0 as "random"); `cardSpot(rec, pageW, pageH, cardW, cardH) -> {x, y}` in page points: `rec.card` applied to the union top-right when present, else the default spot; clamped so the card stays inside `[0, pageW-cardW] × [0, pageH-cardH]`.

- [ ] **Step 1: Write the failing node tests.**

```js
assert.strictEqual(seedFor("abc"), seedFor("abc"));
assert.notStrictEqual(seedFor("abc"), seedFor("abd"));
assert.ok(seedFor("") > 0 && seedFor("x") <= 0xffffffff);
const rec = {rects: [[100, 50, 80, 12], [100, 64, 40, 12]]};
assert.deepStrictEqual(cardSpot(rec, 600, 800, 120, 40), {x: 188, y: 50});   // 8 pt right of x+w=180
assert.deepStrictEqual(cardSpot({...rec, card: [10, 5]}, 600, 800, 120, 40), {x: 190, y: 55});
assert.deepStrictEqual(cardSpot({rects: [[550, 790, 40, 12]]}, 600, 800, 120, 40), {x: 480, y: 760}); // clamped
```

- [ ] **Step 2: Run `python3 tests/test_pdfjs_pure.py`, expect FAIL** (`seedFor is not defined`).
- [ ] **Step 3: Implement both in `pdfjs_pure.js`**, exported the way the file's other helpers are.
- [ ] **Step 4: Run, expect PASS.**

---

### Task 3: The note record and the `card` field

**Files:**
- Modify: `klausmate/pdf_handler.py` (`_validate_highlight`, `add_suppressed`, `_same_annotation`, `_record_signature`, `_tombstone_hits`), `klausmate/pdfjs_viewer.py` (`_is_plain_highlight`, new `make_note_record`, new bridges)
- Test: `tests/test_klausmate.py`, `tests/test_pdfjs_viewer.py`

**Interfaces:**
- Consumes: `make_text_record`'s validators (`sanitize_text`, `validate_hex_color`, `validate_text_size`, `validate_text_box`, `clamp_text_add`).
- Produces: `_validate_highlight` keeps `kind:"note"` records (`id, kind, page, rects, text, color, size`) and a highlight's `card` (two finite floats); `make_note_record(page, x, y, text, color, size, w, h) -> dict`; bridges `_bridge_note_add`, `_bridge_note_update`, `_bridge_note_remove`, `_bridge_card_move`, `_bridge_note_text` with payloads `note-add {page,x,y,text,color,size,w,h}`, `note-update {id,x,y,text,color,size,w,h}`, `note-remove {id}`, `card-move {id,dx,dy}`, `note-text {id,text}`.

- [ ] **Step 1: Write the failing tests.**
  - `_validate_highlight` round-trips a note record exactly; drops a note with empty or whitespace-only text; clamps `size` like text; drops an unknown `color` to yellow `#fadc50`; keeps `card: [12.5, -3]` on a highlight and drops `card: ["x", 1]` or a 3-element list; a text record keeps no `card`.
  - The three-way branches: a note and a highlight with the same rects are not `_same_annotation`; `_record_signature` differs by kind; a tombstone for a note matches only a note.
  - `_is_plain_highlight` is False for a note.
  - `make_note_record`'s key set is exactly `{id, kind, page, rects, text, color, size}`.
  - Bridges (with the existing fake viewer): `note-add` saves one note and pushes; `note-update` changes text/box/colour; `note-remove` deletes it; `card-move` sets `card` on a highlight with a note and ignores a highlight without one; `note-text` sets a highlight's `note` and an empty string clears it (the card goes). Each handler opens no dialog.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Notes reuse the text validators; `card` values clamp to ±page size. Every `kind == "text"` / else branch becomes explicit on `"text"`, `"note"`, highlight.
- [ ] **Step 4: Run, expect PASS** (`test_klausmate.py`, `test_pdfjs_viewer.py`, `test_bridge_reentrancy.py`, `test_pdf_reader_final.py`).

---

### Task 4: The bake writes notes as Helvetica cards

**Files:**
- Modify: `klausmate/pdf_handler.py` (bake loop ~2171-2249, `scan_working_annotations` / `_mirror_core` only if a pin fails)
- Test: `tests/test_klausmate.py`, `tests/test_pdf_reader_final.py`

**Interfaces:**
- Consumes: Task 3's records; `free_text_da`, `text_point_size`, `_mark_klaus`, `FREETEXT_INSET_PT`.
- Produces: a note → `/FreeText` with `/DA /Helv`, `/Contents` its text, background colour its ink (pypdf `background_color`), a 0.75 pt border in the ink (`border_color`, `/BS W 0.75`), `/NM klausmate:<id>`; a highlight note → the highlight's `/Contents` is the note, plus a `/FreeText` card at `cardSpot`'s position (same arithmetic as Task 2, ported to Python as `card_box(rec, page_w, page_h, w, h)`) with `/NM klausmate:<id>:note`; no `/Text` icon.

- [ ] **Step 1: Write the failing tests.**
  - A baked note: one `/FreeText`, `/NM klausmate:<id>`, `/DA` names `/Helv`, a fill colour equal to the ink, `/Contents` the text.
  - A baked highlight with a note: its `/Highlight` has `/Contents` = note; a `/FreeText` with `/NM klausmate:<id>:note` exists at `card_box`'s rect (with `card` and without); no `/Text` subtype anywhere.
  - Removing that highlight and re-baking leaves no `:note` card (Review Focus 1).
  - No `/AP`, `/DR`, `/AcroForm` (existing pin still green); re-bake twice gives identical annotation dicts; pristine never doubles cards (`counts()` in `test_pdf_reader_final.py`).
  - An outside `/FreeText` without `klausmate:` `/NM` is adopted as `kind:"text"`; a `klausmate:<id>:note` card is not adopted (Review Focus 5).
  - `card_box` matches the Task 2 node cases.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** (`test_klausmate.py`, `test_pdf_reader_final.py`, `test_text_box_font.py`).

---

### Task 5: The "Hand-drawn style" switch and its push

**Files:**
- Modify: `klausmate/prefs_state.py` (`_SPEC`, `commit`), `klausmate/manage_models.py` (Appearance switch row, `_Binding`, `_run_effect`), `klausmate/pdfjs_viewer.py` (registry, push on `ready`), `klausmate/config.json`, `klausmate/config.md`
- Test: `tests/test_prefs_state.py`, `tests/test_local_model_settings.py` or `tests/test_dialog_logic.py`, `tests/test_pdfjs_viewer.py`

**Interfaces:**
- Produces: `prefs_state._SPEC["hand_drawn"] = (True, _bool(True))`; `commit` emits `("hand_drawn", bool)` when it changed; `pdfjs_viewer.set_hand_drawn_all(flag: bool) -> None` (pushes `window.klausSetHandDrawn && window.klausSetHandDrawn(<flag>)` to every live `PdfJsViewer`, tracked in a module `weakref.WeakSet`); each viewer pushes the stored value on `ready`, beside `klausSetOcclusionEnabled`.

- [ ] **Step 1: Write the failing tests.**
  - `PrefsState.from_config({})` reads `hand_drawn` True; `set("hand_drawn", False)` then `commit()` patches `{"hand_drawn": False}` and its effects contain `("hand_drawn", False)`; a corrupt value reads True.
  - The Preferences dialog has an `Md3Switch` whose row label is "Hand-drawn style", bound to `hand_drawn`; Save with it toggled calls a patched `pdfjs_viewer.set_hand_drawn_all` with False.
  - A viewer's `ready` handling evals `klausSetHandDrawn(false)` when the store says False, and still evals `klausSetOcclusionEnabled` (the occlusion push is not replaced).
  - `config.json` has `"hand_drawn": true`; `config.md` documents it under Feature toggles.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The row sits on the Appearance page after "KlausBook design".
- [ ] **Step 4: Run, expect PASS** (`test_prefs_state.py`, the dialog test, `test_pdfjs_viewer.py`, `test_reader_occlude.py`).

---

### Task 6: The page draws hand-drawn marks and cards

**Files:**
- Modify: `klausmate/web/pdfjs_viewer.html` (CSS, `state`, `renderAnnotLayers`, `klausSetHandDrawn`, `#textMeasure`)
- Test: `tests/test_pdfjs_viewer.py`, `tests/test_text_box_font.py`, `tests/pdfjs_textbox_test.js` if the measure helpers change

**Interfaces:**
- Consumes: `seedFor`, `cardSpot` (Task 2); `window.rough`, the `@font-face` (Task 1); records from Task 3.
- Produces: `state.handDrawn` (default true until the first push); `window.klausSetHandDrawn(flag)` re-renders every rendered page's layers; with it on, `renderAnnotLayers` adds one `svg.roughLayer` per page inside `.hlLayer` (highlight bands) and a `.cardLayer` (z between `.noteLayer` and `#marqueeKeep`) holding `div.noteCard` elements and their connector `svg`; `.hltext`, `.noteCard`, `#textMeasure` and `.editBody` use the hand-drawn stack via a `body.handDrawn` class.

- [ ] **Step 1: Write the failing tests** (source pins in the file's existing style, plus the node textbox test where layout helpers are touched).
  - `renderAnnotLayers` destroys exactly `[".hlLayer", ".noteLayer", ".cardLayer"]` (update the existing pin at `test_pdfjs_viewer.py:1492-1500`).
  - With `state.handDrawn`, highlight bands come from `rough.svg(...).polygon(..., {fillStyle: "solid", roughness: 1, seed: seedFor(rec.id), stroke: "none"})`; no `Math.random` in the renderer.
  - Card positions use `cardSpot(...)` and multiply by `state.scale` (Review Focus 2); the connector is a rough `line` seeded with `seedFor(rec.id)`.
  - `body.handDrawn .hltext`, `.noteCard`, `#textMeasure`, `.editBody` share `font-family: "Excalifont", sans-serif`; without the class they keep Helvetica (update `test_text_box_font.py` to check both).
  - The first measure after `klausSetHandDrawn(true)` awaits `document.fonts.ready`.
  - The ✎ `noteAnchor` renders only when `!state.handDrawn`; `kind:"note"` records render as cards in both modes (plain Helvetica card when off).
  - Card fill uses the record's ink at 0.85 alpha through the `--ink-*` variables (no hex in the page, existing pin).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** (`test_pdfjs_viewer.py`, `test_text_box_font.py`, `test_pdfjs_pure.py`, `test_reader_occlude.py`).

---

### Task 7: Note tool, in-place editing, dragging, card menu

**Files:**
- Modify: `klausmate/web/pdfjs_viewer.html` (annobar markup, `setTool`, click handler, `openTextEdit` card variant, drag, `highlightAt`, `#ctxmenu` items)
- Test: `tests/test_pdfjs_viewer.py`, `tests/test_reader_occlude.py`

**Interfaces:**
- Consumes: Task 3 bridge messages; Task 6 card layer.
- Produces: `#abNote` button (title "Add Note") between `#abText` and the size stepper; `state.tool` accepts `"note"`; with the Note tool the ink row shows the five highlight inks and the size stepper shows; `cardAt(x, y)` hit-test checked before `highlightAt`.

- [ ] **Step 1: Write the failing tests** (source pins).
  - The annobar has `#abNote` titled "Add Note"; `setTool("note")` exists and Escape disarms it like the text tool.
  - A Note-tool click opens the card editor and commits through `postB64("note-add", …)` with the measured box; a highlight card commits through `note-text`; a free-standing card through `note-update`.
  - An editor closed with empty or whitespace-only text posts `note-remove` for a new free-standing note and `note-text` with `""` for a highlight card, never `note-add` with empty text (Review Focus 3).
  - Dragging a card posts exactly one message on mouseup: `card-move {id,dx,dy}` for a highlight card, `note-update` for a note; positions are clamped with `cardSpot`'s bounds.
  - The context menu on a card lists "Edit Note", "Remove Note" first and still contains the occlusion items block and zoom items (Review Focus 4); the `/* occlusion-items:start */` block is unchanged byte for byte.
  - `_bridge_note_edit` is only posted when `!state.handDrawn`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** (`test_pdfjs_viewer.py`, `test_reader_occlude.py`, `test_bridge_reentrancy.py`), then the whole suite.

---

### Task 8: Docs

**Files:**
- Modify: `CLAUDE.md` (the PDF reader section), `CONTEXT.md` (a "Note" and "Hand-drawn style" entry), `klausmate/config.md` (done in Task 5), `AGENTS.md` if it lists reader files.

- [ ] **Step 1:** Update the reader docs: record kinds incl. `note` and `card`, the hand-drawn renderer and switch, the bake's note cards (Helvetica, no `/Text` icon), Excalifont served via web exports, rough.js vendored and its build script.
- [ ] **Step 2:** Run the whole suite and record the result.

## Ownership split (agree with Klaus Addon Frontend before Task 1)

Proposed: Tasks 1–5 and 8 (fonts/licence/vendoring, pure helpers, data model and bridges, bake, switch, docs) here; Tasks 6–7 (the page renderer and interactions) by Klaus Addon Frontend, who owns `pdfjs_viewer.html`. Task 6 starts after Tasks 1–3 land, since it consumes their interfaces. If Frontend prefers the other half, swap.
