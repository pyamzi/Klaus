# klausmate PDF viewer — parity spec for the KlausBook editor

Source: agent inventory of `KlausMate-Context/klausmate/pdf_viewer.py` (native
QPdfView path), `theme.py`, `__init__.py` `_PanelBar`, 2026-09-17. This is the
interaction contract "the editor should feel EXACTLY like klausmate" refers
to. Visual skin is the Obsidian direction (see KB-011/KB-012); everything
below is behavior, wording, and the few colors that are content, not chrome.

## What klausmate's viewer actually is

- Continuous scroll, FitToWidth default, **chrome-free viewer** — the only
  toolbar is the host header (30px `_PanelBar`: thumbs toggle ◫, add ＋,
  record ●, per-PDF tabs with ✕, page label, float ⧉, hide ✕).
- Thumbnail strip: **hidden by default**, toggleable, 120–280px (default
  170px), lazy renders 140px wide (max 3 per 80ms tick, LRU 200), click →
  go to page, selected = 2px accent border + selection tint.
- No zoom buttons anywhere — zoom is ⌘+/−/0, pinch, and the context menu.

## Highlights (the core flow)

- Create: select text → **⌘⇧H or ⌘⇧A**, or right-click → "Highlight".
  No selection → toast "Klaus: select text first, then highlight".
  Multi-page selection mints one record per page. Selection clears after
  (the highlight replaces it, Preview-style). Toast: "Klaus: highlight added".
- Record: `{id, page, rects: [[x,y,w,h]…], color: "#fadc50"}`; painted at
  alpha 110/255 (43%), square corners.
- Inks (`theme.HIGHLIGHT_INKS`, never theme-forked — they bake into the
  PDF): yellow **#FADC50** (default), green #8AE08C, blue #7FC6F2,
  pink #F79AC8, orange #F7B267. Picker exists only in the pdf.js annobar
  (`pdfjs_viewer.py` ~179–290) — reference for ours.
- Delete: right-click a highlight → "Remove Highlight" (±3pt hit test,
  topmost first). Removing an externally-adopted record writes a tombstone
  so a stale bake can't resurrect it.
- Persistence: JSON store synchronously + debounced background bake of real
  PDF annotations from the pristine original (pypdf).

## Sticky notes (per-highlight, not per-page)

- Right-click highlight → "Add note…" / "Edit note…" → multi-line dialog
  titled "Highlight Note", label "Note:". Empty note removes the box.
- Box: anchored top-right of the highlight's first rect (+2,−2), width
  ≤180 (text+10), height ≤4 lines +6, radius 3, fill rgba(255,245,170,235),
  border 1px rgb(190,170,80), text rgb(70,60,20) at 10px, word-wrapped.

## Context menu (exact order)

Copy · Copy Selection as Image · Highlight · [Edit note…|Add note…] ·
[Remove Highlight|Remove Text] · Copy Page Text · Copy Slide as Image ·
─── · Zoom In ⌘+ · Zoom Out ⌘− · Actual Size ⌘0. Items disable rather
than hide. Floats on a 16px shadow (a sanctioned exception).

## Find bar (⌘F)

Top strip: input (placeholder "Find in PDF…", clear button) · count label
("" / "0 matches" / "{i+1} of {count}" / "{count} matches") · ‹ (Shift+Enter)
· › (Enter) · ✕ (Esc). Live search debounced 250ms. ⌘G/⌘⇧G cycle; silent
no-op while the bar is hidden. Hides + clears on document change.

## Keyboard / mouse

- ⌘C copy · ⌘A select page · ⌘=/⌘+ zoom ×1.25 · ⌘− ÷1.25 · ⌘0 actual size
  → FitToWidth · zoom clamp 0.25–5.0 · ⌘⌥G Go to Page (getInt dialog,
  "Page (1–{n}):" with en-dash) · PageUp/Down page nav · Home/End first/last
  · arrows scroll natively.
- Drag = text selection with char-snapped anchor (margin drags resolve);
  click in the gutter deselects; double-click word; triple-click paragraph
  (blank-line delimited); ⌘+double-click copies the slide as image;
  ⌥+drag marquee → auto-copies as image and persists (drag OUT of it to
  drag the image; any plain click clears it); pinch zooms.
- Live selection tint: OS Highlight color with alpha forced to 100
  (fallback #3A82F7@55%); marquee = same at alpha 30 + 1px dashed #808080.

## Voice

- Every feedback is a transient toast prefixed "Klaus: " — never a modal,
  never inline text.
- Page indicator: "Page {n} / {total}" (native) vs "{n} / {total}" (pdf.js)
  — KlausBook uses "{n} / {total}"; keep it.
- Degraded states have exact copy (see inventory); features degrade to None
  guards, never break the viewer.

## Known divergences to keep (deliberate)

- KlausBook's Impress stage (filmstrip + single slide + notes sidebar) vs
  klausmate's continuous scroll — chosen in the 2026-09-17 plan Q&A; see
  the open layout question on the board.
- KlausBook has per-slide notes (its own feature); klausmate has none —
  klausmate's transcript strip is lecture transcript, not notes.
