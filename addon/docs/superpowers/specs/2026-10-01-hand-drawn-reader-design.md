# Hand-drawn PDF reader — design

Date: 2026-10-01. Status: decided in conversation (Q1–Q12; Q2, Q7 and Q10 revised to the Klaus-only option the same day); awaiting written-spec review.

## Goal

Klaus's PDF reader gets Excalidraw's look and its imperfections: highlights drawn as wobbly marker swipes, text boxes in Excalifont, and sticky notes as hand-drawn cards, both attached to highlights and free-standing. A Preferences switch "Hand-drawn style" (on by default) brings back today's clean look. The look lives in Klaus only: the PDF file keeps standard marks in Helvetica, so it adds no fonts and no bytes.

Success means:
- With the switch on, every highlight, text box and note in the reader looks hand-drawn, and each one wobbles the same way every time you see it.
- Greek letters, arrows, maths symbols and sub/superscripts still show in every text box and note (in a plain system font where Excalifont has no glyph).
- The PDF file is written as today: standard highlights and Helvetica text boxes; notes become plain Helvetica cards.
- With the switch off, the reader looks exactly as it does today.

## Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Scope | Highlights, text-box font and sticky notes only. No pen, arrows or shapes. |
| Q2 | The PDF file | **Klaus only.** The file keeps today's standard highlights and Helvetica text boxes; nothing is embedded. (Revised from "text boxes match" to keep the work and file size down.) |
| Q3 | Highlight style | Marker swipe: a translucent, slightly wavy band across each line. |
| Q4 | Sticky notes | Free-standing notes placed anywhere, and highlight notes shown as cards. |
| Q5 | Stable quirks | Every mark's wobble is seeded from its id: the same at every zoom, reload and session. |
| Q6 | On or off | Preferences switch "Hand-drawn style", on by default; off is today's look. |
| Q7 | Missing characters | **Per-character fallback on screen** to the system's sans-serif font; no bundled fallback font. (Revised with Q2: nothing needs to match in the file.) |
| Q8 | Free-standing notes | A Note tool on the annotation bar; click to place, type; the card grows to fit; drag to move; five ink colours, yellow by default; right-click to delete. |
| Q9 | Highlight-note cards | Start just right of the highlight, draggable, position saved; a hand-drawn line joins card and highlight. |
| Q10 | Notes in the file | Both kinds become visible cards (`/FreeText`) **in Helvetica** with the ink as fill; a highlight's note also stays in the highlight's own popup text. |
| Q11 | Existing text boxes | The font is a drawing-time choice: every text box follows the switch in the reader, nothing is converted; the file is unchanged. |
| Q12 | Roughness | Excalidraw's default "artist" roughness (1), fixed. |

## Current state (2026-10-01, HEAD 502cb0c)

- Marks live in `user_files/annotations/<safe>.json` as `{"version": 1, "highlights": [...]}`. Two record kinds: a highlight `{id, page, rects, color, note}` and a text box `{id, kind:"text", page, rects, text, note, color, size}`. Rects are page points, top-left origin. A highlight's note is its `note` string; there is no free-standing note.
- `pdf_handler._validate_highlight` rebuilds every record from a fixed key list, so an unknown kind or field is dropped on load; every other branch is "`kind == "text"` or else highlight".
- `pdfjs_viewer.html` draws marks as DOM divs: `.hlLayer` (highlights as `div.hl`, text boxes as `div.hltext` in Helvetica) and `.noteLayer` (a ✎ anchor per highlight note, edited through a Python dialog). `renderAnnotLayers` rebuilds both per page on every pass. pdf.js draws no PDF annotations.
- Text boxes size from measurement (`#textMeasure`, commit c35343f); Python validates the box.
- The bake rebuilds the working PDF from the stripped pristine copy: `/FreeText` with `/DA /Helv`, no `/AP`, no `/DR`, no `/AcroForm` (pinned); `/Highlight` with quad points; a highlight's note as an 18 pt `/Text` icon, `/NM klausmate:<id>:note`.
- `klausmate/web/fonts/Excalifont-Regular.ttf` is the Latin subset (212 code points). The web-exports pattern does not serve `web/fonts/`. `LICENSE-excalidraw.txt` calls Excalifont MIT; Excalidraw's own `LICENSES.txt` says OFL-1.1.
- rough.js exists only inside the 3.2 MB Image Occlusion Excalidraw bundle.
- The reader page receives no settings; `klausSetOcclusionEnabled` is the live-push pattern.

## Architecture

### Font

- The reader page loads the existing `Excalifont-Regular.ttf` through `@font-face`; the web-exports pattern is widened to serve `web/fonts/*.ttf`.
- The hand-drawn font stack is `"Excalifont", sans-serif`: the browser draws each character Excalifont lacks (α, β, →, ≤, ₂…) in the system sans-serif, per character.
- `LICENSE-excalidraw.txt` is corrected to Excalifont's real licence, checked against the Excalidraw repository.

### Marks (`pdf_handler`, `pdfjs_viewer`)

- A third record kind, a free-standing note: `{id, kind:"note", page, rects:[[x,y,w,h]], text, color, size}`. `rects[0]` is the card; `size` is the text size (default 12 pt, same stepper as text boxes); `color` is one of the five highlight inks.
- A highlight with a note gains an optional `card: [dx, dy]`, the card's top-left in page points relative to the highlight's union top-right. Absent means the default spot (8 pt right of the highlight's end, top-aligned, clamped inside the page).
- `_validate_highlight` learns the new kind and field with their limits (note text ≤ `MAX_TEXT_CHARS`, card offsets clamped to the page). Every "`kind == "text"` or else" branch becomes an explicit three-way choice: suppression tombstones, `_same_annotation`, `_record_signature`, `_tombstone_hits`, `_is_plain_highlight`, the bake and the page renderer. No migration: version stays 1, and an old file reads unchanged.
- No stored seed: the seed is a 32-bit hash of the record id.

### The reader page (`pdfjs_viewer.html`, `pdfjs_pure.js`, vendored rough.js)

- rough.js 4.6.x (MIT) is vendored as `klausmate/web/rough.min.js` with its licence, built by a pinned script, and loaded before the main script.
- `pdfjs_pure.js` gains `seedFor(id)` (a stable 32-bit hash) and `cardSpot(rec, pageW, pageH)` (the default card position, clamped), both node-tested.
- With hand-drawn on, `renderAnnotLayers` draws:
  - highlight: per rect, a rough.js `polygon` in one SVG per page layer, `fillStyle: "solid"`, `roughness: 1`, `seed: seedFor(id)`, no stroke, the band 2 pt taller than the rect with jittered ends, the ink at today's 0.43 alpha, no blend mode (final review, 2026-10-01: a multiply blend made bands vanish on dark slides; the plain alpha is what the off path already shows readably).
  - text box: the existing `div.hltext`, in the hand-drawn font stack.
  - highlight note: a card (`div.noteCard`: rough.js rounded-rectangle outline and fill in the highlight's ink, text in the hand-drawn font) at `card` or `cardSpot`, and a rough.js line from the card's nearest corner to the highlight. The ✎ anchor goes.
  - free-standing note: the same card at `rects[0]`.
- Cards are edited in place with the text editor the text tool already uses (`openTextEdit` in a card variant), committing on blur, Escape or ⌘/Ctrl+Enter. Dragging a card moves it (a highlight card stores `card`; a note stores `rects[0]`); one update is sent on drop. Right-click on a card: "Edit Note", "Remove Note" (on a highlight card, "Remove Note" clears its note; the highlight stays).
- The annobar gains a Note tool (`state.tool = "note"`), armed like the text tool: click places an empty card and opens its editor; the ink row shows the five highlight inks; the size stepper applies. An empty card that loses focus is removed.
- Hit-testing (`highlightAt`) covers cards first, then highlights.
- `#textMeasure` measures in the active font stack, and the first measurement after the hand-drawn font is used waits for `document.fonts.ready`.
- With hand-drawn off, rendering is exactly today's divs, ✎ anchors and Helvetica; free-standing notes still exist and draw as plain rounded cards in Helvetica.

### Bridge (`pdfjs_viewer.py`)

- New messages: `note-add {page, x, y, text, color, size, w, h}`, `note-update {id, x, y, text, color, size, w, h}`, `note-remove {id}`, `card-move {id, dx, dy}`, `note-text {id, text}` (a highlight card edited in place). Each handler validates like `_bridge_text_add` and defers any dialog with `QTimer.singleShot(0)` (the bridge re-entrancy pin finds them automatically).
- The `note-edit` Python dialog stays only for hand-drawn off.
- Python pushes `klausSetHandDrawn(bool)` on `ready` and when the setting changes (the `klausSetOcclusionEnabled` pattern); the page re-renders every visible page's marks.

### The bake (`pdf_handler`)

- Text boxes and highlights: unchanged.
- Free-standing note: a `/FreeText` card in Helvetica (`/DA /Helv`, today's text-box path) with the note's ink as background colour and a thin border, `/NM klausmate:<id>`.
- Highlight note: the highlight's `/Contents` carries the note text (its standard popup), and a `/FreeText` card the same way at the card position, `/NM klausmate:<id>:note`. The `/Text` icon goes.
- The bake does not depend on the switch: the file is the same whether hand-drawn is on or off.
- The "no `/DR`, no `/AcroForm`" rule stands untouched.
- Carry, scan and mirror (`scan_working_annotations`, `_mirror_core`): Klaus's own cards are `/NM`-stamped and regenerated, never adopted; a `:note`-suffixed id is still not a primary mark (K-085). An outside `/FreeText` stays adoptable as a text box.

### The switch (`prefs_state`, `manage_models`, `config.json`, `config.md`)

- `hand_drawn` (bool, default true) in `prefs_state._SPEC`, an `Md3Switch` row "Hand-drawn style" on the Appearance page, a `_Binding`, and a `hand_drawn` effect in `commit` that pushes `klausSetHandDrawn` to the open reader. No re-bake: the file does not depend on it.

## Data flow

1. Place a note: Note tool → click → empty card + editor → type → commit → `note-add` with the measured box → validated record saved → bake (debounced) → page re-renders from the pushed records.
2. Drag a card: drop → `card-move` (highlight card) or `note-update` (note) → save → bake.
3. Switch off: Preferences Save → `hand_drawn` effect → reader re-renders clean.
4. Open in Preview: standard highlights with their note in the popup, Helvetica text boxes, Helvetica note cards.

## Error handling

- Excalifont fails to load: the page's font stack falls through to sans-serif; nothing else changes.
- rough.js fails to load: marks draw as today's divs (the switch's off path), and the console says why.
- Unknown record fields from a newer Klaus: dropped on load, as today.
- A card dragged off the page: clamped inside on drop.

## Testing

- `tests/pdfjs_pure_test.js`: `seedFor` is stable and spreads; `cardSpot` defaults and clamps.
- `tests/test_pdfjs_viewer.py`: the new bridge messages validate and save; the Note tool markup and ink row; the hand-drawn push on `ready`; the font stack and `@font-face` present; rough.js loaded before the main script; the layer-destroy pin updated for the SVG/card layers.
- `tests/test_klausmate.py` / `test_pdf_reader_final.py`: `_validate_highlight` keeps the new kind and `card`, drops bad ones; every three-way branch; a baked note is a Helvetica `/FreeText` with a fill, a highlight note puts its text in the highlight's `/Contents` and no `/Text` icon; still no `/DR`/`/AcroForm`; re-bake is stable; pristine never doubles cards.
- `tests/test_text_box_font.py`: the bake's `/Helv` stays; the page's text box font follows the switch.
- `tests/test_wordmark_font.py` (or a new pin): the corrected Excalifont licence ships beside the TTF; the web-exports pattern serves it.
- Live checklist (Pouya):
  1. Highlight a paragraph: wobbly marker bands; zoom and reopen: same wobble.
  2. Add a text box with "β-blocker ≤ 2 mg": handwriting, with β and ≤ in a plain font.
  3. Place a sticky note, type, drag it, change its colour, delete it.
  4. Add a note to a highlight: a card appears beside it with a line; drag it; reopen: it stays.
  5. Open the PDF in Preview: standard highlights (note in the popup), Helvetica text boxes and note cards.
  6. Turn Hand-drawn style off: today's look in Klaus.

## Rulings

- **Seeds are derived from ids**, not stored: old marks get a stable wobble with no migration.
- **The file never depends on the switch**, so toggling it never rewrites a PDF.
- **Notes use the text size stepper** rather than a fixed size, since the editor and measurement are shared with text boxes.
- **The ✎ note dialog survives only for hand-drawn off**; with it on, notes are edited in place.

## Ownership

The reader files (`pdfjs_viewer.html/.py`, `pdfjs_pure.js`, `pdf_handler.py`'s bake, `annotation_save.py`) belong to the Klaus Addon Frontend session. That session confirmed (2026-10-01) nothing of theirs is in flight there and offered to own either half; the split is agreed when the plan is written.

Image Occlusion hooks that must keep working (pinned by `tests/test_reader_occlude.py`):
- the `/* occlusion-items:start */` block in `pdfjs_viewer.html` (`occlusionItems`, `renderRegionCanvas` at scale 2, `klausSetOcclusionEnabled`), which the card hit-testing and context-menu changes must leave intact;
- `_bridge_occlude_image`, `_bridge_draw_diagram`, `_bridge_toast`;
- the `_finite` guard and `excal_masks.png_size`;
- `PdfSidebar._editor` as a property that pushes the occlusion state to the page (the new `klausSetHandDrawn` push follows the same pattern and must not replace it).

## Out of scope

- Pen, arrows, shapes or any other Excalidraw drawing tool.
- Any hand-drawn look or font inside the PDF file.
- A bundled fallback font; CJK in Excalifont style.

## Risks

- Preview and other apps show Helvetica text and plain cards, not the handwriting; a shared PDF looks plainer than Klaus.
- Whether every viewer paints a `/FreeText` background colour without an appearance stream is unconfirmed; if Preview draws the card unfilled, the note text still shows.
- Per-character fallback mixes handwriting with a plain font in one word (β-blocker); that is the accepted look.
- The Excalifont licence must be confirmed before shipping the corrected licence file.
