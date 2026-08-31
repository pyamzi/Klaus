# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

### K-079: Per-PDF notes space: side pane + sidecar + baked appended Notes page
owner: -
priority: P2
tags: feature
files: klausmate/pdf_viewer.py,klausmate/pdf_handler.py,tests/test_klausmate.py
created: 2026-08-24

Pouya: each PDF should be "a space where you can take notes on the
side", "embedded into the PDFs in some way that's viewable in other
files but doesn't overwrite the PDF".

Recommended design (fits the regenerative bake exactly):
1. SOURCE OF TRUTH: sidecar annotations/<safe>.notes.md in user_files;
   plain-text/markdown.
2. UI: toggleable notes pane in the PDF viewer (per-tab toolbar button),
   QPlainTextEdit, autosave debounce ~800ms, feeding the same bake
   debounce highlights use.
3. EMBED: bake appends rendered "Notes — <display>" page(s) AFTER the
   last content page: Helvetica base-14 (no font embedding), wrapped
   text, multi-page as needed. Because every bake regenerates from the
   pristine original, the notes page never accumulates or duplicates;
   empty notes (+ no highlights) = un-bake back to pristine. Content
   pages are never touched -> "doesn't overwrite the PDF"; a real page
   -> visible in Preview/Acrobat/anything -> "viewable in other files".
   pypdf-only page synthesis (raw content stream, Tj ops, manual wrap):
   no new deps. Limitation v1: plain text only, WinAnsi charset
   (non-Latin chars degrade) — flagged.
Rejected alternative: embedded file attachment (EmbeddedFiles tree) —
macOS Preview ignores attachments, failing "viewable in other files".
Tests: notes page appended once across repeated bakes; page count =
pristine+N; un-bake restores pristine byte-identical; text extraction
of the notes page contains the note; wrap/pagination on a long note.

#### Comments
- [2026-08-31 orchestrator] Status 2026-08-31: deliberately NOT started in this swarm pass — the card's files include klausmate/pdf_handler.py, which a separate live session (the retention-history-prune task chip) holds uncommitted edits to right now; claiming would risk staging that session's half-finished work into our commit. Pick this up as the first card of the next pass once that session lands. The design in the card body (sidecar .notes.md + toggleable pane + bake-appended Notes page) is still the agreed shape.
- [2026-08-31 orchestrator] Foundation landed as K-134 (klausmate/pdf_notes.py, 93 checks): sidecar storage, Helvetica metrics, wrap/paginate, content-stream synthesis, and a lazy pypdf append_notes_pages. What remains HERE, once pdf_handler.py frees up: (1) the viewer's notes pane, (2) ONE call site in bake_annotations — after the highlight loop, immediately before the atomic write, so the n_pages bounds checks stay honest. LOAD-BEARING detail from worker-G's read: bake_annotations has TWO early returns that must learn about notes or a notes-only PDF never bakes — the 'never baked and nothing to bake' return (~L1377) and the un-bake branch 'if not native_to_bake and not carried' (~L1500), which would restore pristine and throw the notes away. Also: pdf_handler.delete_context (~L2351) unlinks an explicit path list that does NOT include the .notes.md sidecar — same blind spot retention_history.forget_history has — so a re-import under the same safe basename would inherit a stranger's notes. Deliberate non-decision carried forward: no page cap on a huge note, because a cap silently truncates the user's own writing.

### K-095: pdf.js migration umbrella: replace QPdfView rendering to kill flicker
owner: -
priority: P2
tags: pdfjs,orchestrator
created: 2026-08-25

Pouya: 'I want to do the real fix… PDFjs is the thing I will have to do eventually.' QPdfView flickers structurally (async pdfium page delivery, overlay repaint races); SynapsePro proves the pdf.js-in-webview architecture (scripts/SynapsePro-main/web_notebook/pdf_viewer.html): canvas layers GPU-composited by Chromium, base64 PDF feed, no repaint during scroll. Strategy: new PdfJsViewer behind config flag pdf_renderer ('native' default) satisfying PdfSidebar's six-method surface (set_document/set_page_texts/load_annotations/clear_document/go_to_page/scroll_position + toggle_thumbnails/_page_label); build parity feature-by-feature (K-096..K-099); flip default + retire native path only after live soak (K-100). The annotations JSON and bake pipeline are renderer-independent and MUST NOT change.

#### Comments
- [2026-08-25 orchestrator] Live-soak bugs from Pouya, fixed: (1) TEXT LAYER MISALIGNED + highlights broken — pdf.js 3.x sizes glyph spans via calc(var(--scale-factor)*...) and we never set the variable, so every span fell to ~13px default (measured: 36pt title span was 12.2pt tall). Fix: applyScaleFactor() on the pages container, tracked through build + rezoom; text layer attached to DOM BEFORE renderTextLayer so per-span scaleX measurement sees computed styles; official text-layer CSS props (text-size-adjust:none etc). Harness now measures span font 44.24px = 36pt x 1.23 scale, selection rect 538x41pt covering the full title — screenshot-verified pixel alignment under simulated hostile Anki stdHtml CSS. (2) Cmd+/- ZOOMED THE WHOLE FRAME — Anki's window-level zoom QActions fired before the page saw the key (the documented host-window shortcut ambiguity). Fix: ShortcutOverride claim on the webview + focusProxy for Cmd +/-/0/F/G/Shift-G/Alt-G/Shift-H/Shift-A, zoomFactor pinned to 1.0; the page's JS is the single zoom owner. (3) selectionRectMap containment relaxed to rect-center + clamp. Regression-pinned in tests/test_pdfjs_viewer.py (51 checks).
- [2026-08-25 orchestrator] Live crash fixed: poll_external_changes duck-types v._apply_mirror on the active renderer — AttributeError on PdfJsViewer (traceback from Pouya, taskman closure). PdfJsViewer now implements the full K-082 mirror surface: _apply_mirror (mirror_foreign_annotations + reload + push, NO bake — would re-feed the watcher), _start_foreign_mirror (daemon-thread pypdf scan + pristine capture, main-thread apply; also now runs on every pdfjs load_annotations so Preview marks made while Anki was closed appear on open), and _refresh_highlight_overlay as a push alias for _reload_records_for's post-bake refresh (that one was silently swallowed, not crashing — stale display). The entire duck-typed surface (12 attrs, from a grep of shared code) is now pinned in tests/test_pdfjs_viewer.py so shared-code additions can't crash one renderer silently. This closes K-100 gap item (2) early.
- [2026-08-25 orchestrator] Double-draw fixed (Pouya live report: highlights + outside text rendered twice). Root cause: the bake writes marks as REAL PDF annotations, and pdf.js paints annotations by default — canvas showed the baked copy under the overlay's record copy. The native viewer's documented rule transplanted: all four render sites (pages, thumbnails, page/region image copies) now pass annotationMode: AnnotationMode.DISABLE. Pixel-verified in the harness with a hand-written PDF carrying a real red /Square annotation: viewer canvas white at the annot rect, control render with annotations enabled red — the flag, not the PDF, is what suppresses it. Test pins all render sites carry the flag.
- [2026-08-25 orchestrator] Live crash fixed (theme change): RuntimeError 'wrapped C/C++ object of type AnkiWebView has been deleted' inside Anki's theme_did_change iteration. Cause: AnkiWebView.__init__ registers on_theme_did_change with the GLOBAL hook and only AnkiWebView.cleanup() unregisters it (Anki even logs 'destroyed without a cleanup() call'); PdfJsViewer created webviews but never called it, so closing the Library window / editor panel left a dead bound method that crashed the user's next theme switch. Fix: PdfJsViewer.cleanup() (idempotent, drops _web), PdfSidebar.cleanup() forwarding duck-typed (native QPdfView needs nothing), called from DriveWindow.shutdown and _PdfTabContainer._on_host_closing, plus pdf_viewer.cleanup_all_sidebars() swept on profile_will_close + aboutToQuit as a backstop for unenumerated paths. Regression test simulates Anki's hook lifecycle end to end AND falsifies itself (proves a webview destroyed without cleanup does crash the hook). 76 checks green.
- [2026-08-31 orchestrator] Umbrella status: every parity card is now Done (K-096 foundation, K-097 selection/clipboard, K-098 marks, K-099 find/thumbs/nav, K-116 zoom+annobar, K-100 editor integration). The ONLY remaining child is K-101 — the needs-human cutover soak. This umbrella closes with it.

### K-101: pdfjs cutover: flip default renderer after live soak, then retire QPdfView path
owner: -
priority: P3
tags: pdfjs,needs-human
files: klausmate/config.json,klausmate/pdf_viewer.py,klausmate/pdfjs_viewer.py
created: 2026-08-25

GATE: Pouya uses pdf_renderer:'pdfjs' daily until satisfied (no flicker, parity holds incl. bake round-trips). Then default flips to 'pdfjs'; native path stays one release as fallback; final card deletes the QPdfView machinery (KEEP: annotations JSON, bake, pdf_handler — renderer-independent).

#### Comments
- [2026-08-31 orchestrator] Status 2026-08-31: still gated on the needs-human soak, and the gate is now much easier to open — K-116 shipped the full zoom overhaul (instant pinch/keys/toolbar zoom, no blank pages, reachable left edge) and the wired annobar (highlight mode, add-text, zoom pill), and K-100 (the last parity card) is being executed right now. Once K-100 lands: Pouya flips KlausMate Preferences -> General -> 'Use the new pdf.js viewer' + restart, uses it daily, and reports. When satisfied, the default flips and the QPdfView machinery retires (annotations JSON/bake/pdf_handler stay — renderer-independent).

## Ready

## Doing

## Review

## Done

### K-132: Library empty state: teach the pane instead of showing a void
owner: worker-E
priority: P2
tags: ui,design,library
files: klausmate/pdf_drive.py,klausmate/theme.py,tests/test_drive.py,tests/test_theme.py
verify: bash -c "grep -q LIBRARY_EMPTY_TEXT klausmate/pdf_drive.py && python3 tests/test_drive.py && python3 tests/test_theme.py"
created: 2026-08-31
claimed: 2026-08-31

From the 2026-08-31 screenshot audit: below three rows the Library is a vast dead area, and a first-run Library is entirely blank — HIG says an empty pane should TEACH, not just be empty.

When the tree holds no PDFs at all, show a centered muted guidance block over the tree area (LIBRARY_EMPTY_TEXT + a second line naming the two import routes: drag PDFs from Finder onto the folder tree, or use the context menu). It must vanish the moment a row exists, and must NOT fight the existing external-drop handling (_LibraryTree drops + _dest_folder_at) — dropping onto the empty state must file the PDF exactly as dropping on the tree does; verify by reading that code first.

Also make the empty state a real drop affordance: while a Finder drag with .pdf urls is over it, it reads as an active target (theme has a drop_zone_qss builder already — reuse, do not invent). Keep the K-117 vernacular (quiet, muted, VS Code density); no illustration, no big buttons.

If the tree has folders but no PDFs, that is still "no PDFs" — decide and document which copy applies. Pins: the constant, the show/hide condition, the drop-through behaviour, and no-literal-hex; each falsified once.

#### Comments
- [2026-08-31 worker-E] Empty state shipped. LIBRARY_EMPTY_TEXT ("No PDFs in your library yet") + LIBRARY_EMPTY_HINT ("Drag PDFs here, or use Browse… below") render as a quiet muted block over the tree; it lights up in the shared drop-square accent while a .pdf drag is over the tree, and vanishes the moment a PDF row exists. JUDGEMENT (a) — folders but no PDFs gets the SAME copy, one pair of constants. The pane's content is PDFs; a folder is scaffolding the user just made and changes neither what to do next nor how, so a second variant would be a second string to keep true for an identical instruction. The condition is therefore `self.tree.set_empty_state(not contexts)` — the PDF list, never a row count. What the folders case gets instead of new copy is LAYOUT: _reposition_empty parks the block in the free area BELOW whatever rows exist (clamped at the half line, which is also why no scroll hook is needed — rows that fit can't scroll, rows that overflow are past the clamp at every scroll position). Documented at the constants and on the method. Rendered: folders-no-pdfs-day-420.png. JUDGEMENT (b) — sibling OVERLAY on the tree's viewport, never a replacement, and I read the drop path before choosing. _LibraryTree.dropEvent → _dest_folder_at(point) → DriveWindow._on_dropped_paths is the only import path, and _dest_folder_at resolves folder targeting off the ROWS — a QStackedWidget swap would have taken the tree, folder targeting and that whole K-117 path off screen and needed a second drop handler to drift from the first. WA_TransparentForMouseEvents is what makes the overlay safe: QWidget::childAt() (the lookup QWidgetWindow::findDnDTarget runs) skips children carrying it, so every drag is delivered to the viewport as if the block weren't there. Proven offscreen two ways — viewport().childAt(point inside the block) is None, and a drop at that point still yields the identical (paths, folder) tuple, root over blank space and "Anatomy" over the folder row. The block never handles an event: the TREE lights it, off the same _external_pdf_paths test that accepts the drag, so it can't advertise a drop the tree refuses. Copy note: the card's second line said "or use the context menu" — there is no import action in either Library context menu (_build_folder_menu and the blank-space menu offer folder actions only), so the hint names the two routes that exist, the tree drop and the drop square's Browse…. I did not invent a third one. Length is load-bearing: the left pane opens at 300px, leaving 224px of text width; the hint measures 214px at 11px so it sits on one line instead of orphaning "Browse… below". theme.drop_zone_qss gains ONE kwarg, idle_border=False (reuse, not invention): drag-over half untouched, idle dashed box replaced by a TRANSPARENT 1px border so the box model survives the drag and the text can't shift. The pane already carries one dashed square below the tree; two would read as two targets. CHECKS: test_drive 176 passed / 0 failed (was 156; +7 source pins, +13 on real offscreen Qt). test_theme 277 / 0 (was 266; +7 pins, +4 scale-audit lines for the new variant). Card verify exits 0. FALSIFIED (backup + mutate + restore, __pycache__ purged, PYTHONDONTWRITEBYTECODE=1): 1. constant — renamed LIBRARY_EMPTY_TEXT → the constants pin AND the card's own grep-verify both failed (exit 1). 2. show/hide condition, source — swapped `not contexts` for a topLevelItemCount()==0 row test → "the condition is the PDF count" failed. 2b. show/hide, behaviour — setter ignoring its argument → 3 offscreen checks failed. 3. drop-through — deleted the WA_TransparentForMouseEvents call → the attribute pin, the source pin and the childAt pin all failed, the last reporting a QLabel where the viewport should be (i.e. the drag would have been eaten). 4. no-literal-hex — added "#8E8E93" → failed with the line number; a hex in a COMMENT stays exempt (0 failures). 5. theme — kwarg ignored → 4 idle_border pins failed. The hex pin needed rewriting to be real: the house helper in test_setup_crop_theme.py (_hex_hits_outside_comments) drops everything after the first "#" on a line to skip comments, but a hex literal always lives in a string whose opening "#" IS that first "#", so it discards exactly what it searches for — it can never report a hit, and both its checks are vacuous. Mine tokenises and drops COMMENT tokens instead. That file is outside this claim; flagged as a separate task. Also spotted, NOT touched (outside the card): the Library opens with its PDF-name column at ~28px — the default splitter is [300, 740] and columns 1-3 are Fixed at 84+88+88=260, so Stretch gets what's left and first-run rows render nameless (see folders-no-pdfs-day-300.png vs -420.png). Flagged separately. RENDERS (real offscreen Qt, left pane built from the real _LibraryTree + library_qss + the real drop square), /private/tmp/claude-501/-Users-pyamzi-Documents-Github-KlausMate-Context/349d2221-d585-4e2e-8198-698ba5945b6e/scratchpad/empty/: empty-day.png, empty-night.png, empty-dragover-day.png, empty-dragover-night.png, folders-no-pdfs-day-420.png, folders-no-pdfs-night-420.png, folders-no-pdfs-day-300.png, folders-no-pdfs-night-300.png, populated-day.png (control: block gone). Harness one level up at scratchpad/render_empty.py.
- [2026-08-31 orchestrator] Reviewed and committed. Both judgement calls are right and, more to the point, were made by READING the drop path rather than assuming it — the WA_TransparentForMouseEvents proof is the kind of evidence this board is for. Your two out-of-scope findings are being acted on now as K-135: the vacuous hex helper (confirmed structurally incapable — it strips the # that opens the literal) and the 24px name column (confirmed by arithmetic AND visible as 'PL' in your own empty-night render; it is a regression from MY K-127 width change).

### K-135: Two integrity fixes from K-132's audit: nameless PDF column + a hex pin that cannot fail
owner: orchestrator
priority: P1
tags: bug,test-integrity
files: klausmate/pdf_drive.py,tests/test_drive.py,tests/test_setup_crop_theme.py,scripts/k135_gate.py
verify: bash -c 'python3 scripts/k135_gate.py && python3 tests/test_drive.py && python3 tests/test_setup_crop_theme.py'
created: 2026-08-31
claimed: 2026-08-31

Two findings worker-E surfaced while building K-132, both confirmed independently.

1. NAMELESS ROWS ON FIRST RUN. The Library opens with splitter [300, 740]; the numeric columns are Fixed at 84+88+88 = 260px and the tree indents 16px, leaving 24px for the PDF name. Every row renders nameless — visible as a header reading "PL" in K-132s own empty-night render. This is a REGRESSION FROM K-127: before it, all four columns were resizable and the name column kept its 240px while the numerics yielded; making the numerics Fixed removed that give. Pouyas live screenshot looked fine only because his SAVED splitter state is wide — this bites new profiles and anyone whose state is reset. Fix the default so the table fits the pane it opens in (name >= ~280px), and pin the arithmetic so a future width change cannot silently re-break it.

2. A HEX PIN THAT CANNOT FAIL. tests/test_setup_crop_theme.py::_hex_hits_outside_comments strips everything after the first "#" on a line to skip comments — but a hex colour literal IS a "#" inside a string, so the helper deletes the exact thing it is hunting. Proven: it returns [] for the line BLUE = "#AABBCC". Both checks that use it are vacuous and have been since they were written. Replace with tokenisation (drop COMMENT tokens, then scan) — worker-E already did exactly this in tests/test_drive.py; reuse that shape. Then confirm both files really are hex-free, and FIX anything the working pin now catches rather than weakening it.

scripts/k135_gate.py is the gate: it asserts the helper sees a literal AND that the default splitter leaves >= 200px for the name. It exits 1 today (verified).

#### Comments
- [2026-08-31 orchestrator] Fixed and committed. Splitter default 300 -> 560 (name column 24px -> 284px), hex helper tokenised. Both falsified by restoring the old behaviour and watching scripts/k135_gate.py fail. Both target files verified genuinely hex-free, so nothing was weakened to make the working pin pass.
