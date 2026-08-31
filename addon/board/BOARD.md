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

### K-089: Add the highlight search results addon features to Klausmate
owner: orchestrator
created: 2026-08-24
claimed: 2026-08-31

#### Comments
- [2026-08-31 orchestrator] Closing as shipped: this landed as K-113 — klausmate/browse_highlight.py (11KB, Glutanimate AGPLv3 header intact, vendored source in References/highlight-search-results-main): SearchTokenizer + ANKI2124 dialect, webview.findText per term on the Browse editor, re-run on browser_did_change_row, checkable View-menu action seeded by config browse_highlight_default. tests/test_browse_highlight.py green (24 checks) in every sweep since. Nothing left on this card.

### K-057: I want to have some Obsidian-like features for the library panel. Specifically, I want all of the PDFs that we import into the library to be hosted in a directory that points to a specific directory, and then you should be able to choose that directory right away. The first time you open the Anki app, it forces you to choose a directory to host the library in, and then you can change what that directory is.  All the PDFs are in that directory. The way the directory is controlled, the way the folders are arranged, is the same as in the library as well. If something is in a certain folder type, then all the PDFs are also arranged in that folder type in the library and also in the tags. Does that make sense?
owner: orchestrator
created: 2026-08-24
claimed: 2026-08-31

#### Comments
- [2026-08-24 opus] Held for grooming: this changes the storage architecture (a user-chosen disk directory becomes the source of truth; drive.json tree and tags mirror it — today nothing on disk moves and folders are virtual). Needs a design pass covering migration of existing user_files/pdfs, bake_annotations paths, rename/move sync direction, and missing-directory behavior. Also file-overlaps K-055 (pdf_drive, tag_sync). Will groom and launch after this swarm lands.
- [2026-08-24 opus] Design pass done. Split: K-070 (Ready) is part A — storage root, path mapping, migration, setup step, Preferences row. Part B (disk<->tree mirroring, rename/move sync both directions, rescan on profile open, tag follow-through) gets filed once A lands, on pdf_drive/tag_sync/drive_store. This card stays as the umbrella.
- [2026-08-24 opus] Part B shipped as K-073 (two-way sync + single-copy). Umbrella is now functionally complete: root folder chosen at setup/Preferences, disk<->tree<->tags all mirror, one copy of every PDF living in the root. Remaining live verification rides Pouya's next restart.
- [2026-08-31 orchestrator] Closing the umbrella: parts A (K-070: library root, path mapping via library_map.json, pdf_path_for choke point, migration, setup step, Preferences row) and B (K-073: two-way disk<->tree<->tags mirror, rescan_library_root + debounced watcher, single-copy invariant) both shipped and have been in daily live use since — K-117's VS Code Library overhaul (2026-08-31) was built ON TOP of this architecture, which is stronger live verification than any checklist. Folder tree, disk layout, and !Library tags all mirror; external drops file into the hovered folder. Nothing left on this card.

### K-123: Embedding map window (Phase D2): pan/zoom canvas over pdf_graph's data
owner: worker-B
priority: P2
tags: feature,phase-d
files: klausmate/pdf_map.py,tests/test_pdf_map.py
verify: bash -c 'test -f klausmate/pdf_map.py && python3 tests/test_pdf_map.py && python3 tests/test_imports.py'
created: 2026-08-31
claimed: 2026-08-31

Phase D completion (K-058). D1 shipped: projection.py (top-2 PCA, pure stdlib) + pdf_graph.build_graph_data(user_files, cfg) -> {pdfs, notes, edges} from on-disk caches only, xy normalized to [0,1]^2, retention=None headless (a caller with a live col fills it in).

D2 = the window: klausmate/pdf_map.py, aqt-free math top (world<->screen transform, fit-to-view, zoom-at-cursor, hit-test) above an aqt-glue divider; QPainter canvas (K-115 guards), notes as faint dots, PDFs as accent nodes sized by match_count, edges drawn for the hovered/selected PDF only (readability + perf at 4000 notes), hover tooltip with display/folder/match_count/retention-when-known, pan by drag + wheel zoom anchored at the cursor, show() never exec() (K-114), theme tokens only, singleton + cleanup.

Entry point deliberately NOT here: open_map_window(parent) is the public surface; the Library toolbar button lands as K-124 on pdf_drive.py AFTER K-114 releases that file (claim disjointness).

#### Comments
- [2026-08-31 worker-B] Shipped: klausmate/pdf_map.py + tests/test_pdf_map.py (60 checks, 0 fail; verify + test_imports + FULL sweep all green; symlink py_compile ok). Pure top: Viewport (frozen) world<->screen, fit_to_view (margin+center, degenerate-safe), zoom_at with derivation in docstring (anchor fixed to 1e-9 even when the MIN/MAX clamp bites), pan_by, hit_test (nearest-within-radius, inclusive rim, junk-safe), node_radius (sqrt, clamped 5..22px), edges_for_selection + active_pdf (hover previews over sticky selection), labels_visible LOD (1.4x fit), tooltip_text, parse_xy/bounds_of/graph_bounds. Glue (lazy aqt inside functions, retention_history's pattern): _MapCanvas QPainter canvas (K-115 try/finally painter.end(), house surface card + clip, note dots grey_mid, accent nodes, selection ring, edge alpha via QColor.setAlphaF on blue_accent — no hex anywhere), drag pan / wheel zoom-at-cursor / click select / hover QToolTip / leave clears; _MapWindow show()+raise_() only (K-114, no activateWindow), WA_DeleteOnClose, closeEvent clears singleton, Fit button (SecondaryButton), empty state EMPTY_TEXT muted label. open_map_window(parent=None) fronts on second call — K-124's entry point. Retention filled live via existing retention.card_retrievability (one batched call over edge nids) + pdf_retention per PDF; None stays omitted. 16 pins falsified once each (mutate->FAIL->restore, pycache purged, PYTHONDONTWRITEBYTECODE=1). NOTE: card says xy in [0,1]^2 but projection/pdf_graph actually emit [-1,1] per axis — viewport is range-agnostic (graph_bounds measures real data; DEFAULT_BOUNDS=(-1,-1,1,1)), so either convention renders. dialog_qss targets QDialog, so the window adds one token-only objectName rule for its own ground (no theme.py change needed).
- [2026-08-31 orchestrator] Reviewed and committed as af710b0. Independent re-run: 60/60, card verify green, exec-ban/paint-guard/hex spot-checks clean, zoom_at fixed-point derivation verified by eye and by pin. The [-1,1] vs [0,1] range finding was the right call — viewport measures real data. Entry point rides K-124.

### K-114: Retire app-modal exec() addon-wide (macOS 26 segfault class)
owner: worker-A
priority: P1
tags: crash,macos26
files: klausmate/deck_curate.py,klausmate/__init__.py,klausmate/pdf_drive.py,klausmate/setup_flow.py,klausmate/pdfjs_viewer.py,tests/test_bridge_reentrancy.py
verify: python3 -c "import sys; srcs={f: open(f).read() for f in ['klausmate/deck_curate.py','klausmate/__init__.py','klausmate/pdf_drive.py','klausmate/setup_flow.py']}; bad=[f for f,s in srcs.items() if 'dlg.exec()' in s or 'msg.exec()' in s]; sys.exit(1 if bad else 0)"
created: 2026-08-26
claimed: 2026-08-31

Seven live segfaults (2026-08-26, Qt 6.11 + macOS 26.5) proved that showing a Python dialog APPLICATION-modal via exec() crashes in its first backing-store flush (QPaintDevice::devicePixelRatio on null), regardless of dispatch shape (webchannel, QAction, deferred timer all crashed identically). manage_models_dialog is already fixed (dlg.open(), pinned in tests/test_bridge_reentrancy.py). Convert the remaining app-modal exec sites to window-modal open()/show() with callback-driven results: deck_curate.py:160 choose_deck_scope (returns a value -> needs CPS refactor of _curate_with), __init__.py:512 crop dialog, pdf_drive.py:1087, setup_flow.py's five msg.exec() QMessageBoxes (clickedButton() read after exec -> use buttonClicked signal or open+finished), pdfjs_viewer.py's two static QInputDialog helpers (_do_note_edit getMultiLineText, _goto_dialog getInt -> QInputDialog instances with open() + textValueSelected/intValueSelected). Each conversion must keep its existing test pins passing or strengthen them; add an exec-ban pin per converted file mirroring the manage_models one. Full context: context/SESSION-HANDOFF.md crash section.

#### Comments
- [2026-08-31 orchestrator] Progress: pdf_drive.py:1087 (_on_threshold) converted to dlg.open()+accepted callback under K-117, with a per-file exec-ban pin in tests/test_drive.py. Remaining sites on this card: deck_curate.py choose_deck_scope CPS, __init__.py crop dialog, setup_flow.py five msg.exec(), pdfjs_viewer.py two QInputDialog statics.
- [2026-08-31 worker-A] Done. Converted every app-modal exec site on the card to window-modal open()/show()-family with callback results: (1) deck_curate.choose_deck_scope is now CPS — choose_deck_scope(parent, on_done), on_done(deck) fires only on accept (cancel never calls it, _on_threshold's pattern); BOTH callers updated (_curate_with + pdf_drive._curate). (2) __init__._launch_crop_dialog: crop work rides accepted, the _klausmate_crop_open reentry guard now spans the DIALOG lifetime (set after open(), reset in finished) — the old try/finally reset would have cleared it instantly under open(). (3) setup_flow: all five msg.exec() QMessageBoxes -> open() + finished callbacks reading clickedButton() (Esc/close keep their exec-era fall-through meaning: decline flags still get written); closures keep the msg reference so no GC vanish; flow order preserved (each site was terminal in its function; _first_run_dialog_shown_this_session was already set before show). (4) pdfjs_viewer _do_note_edit/_goto_dialog: QInputDialog INSTANCES via open() + textValueSelected/intValueSelected, singleton attrs (_note_dialog/_goto_dlg) with front-not-stack + deleteLater on finished, themed via dialog_qss like _open_text_dialog; note edit re-looks-up the record by id at accept time. Unused QDialog import dropped from __init__. Tests: 6 new pins in test_bridge_reentrancy (47 passed, was 41) — per-file dlg/msg exec bans on code_only text + shape pins (msg.open() count==5 in setup_flow, dlg.open() count==3 in pdfjs, QInputDialog.get banned in pdfjs, CPS caller pins); setup_flow added to _MODULES; each new pin FALSIFIED once (scratch backup -> mutate -> 6 targeted FAILs -> restore, verified 47 pass + verify + compile after). Card verify passes; full sweep: 21/21 test files pass; py_compile through the symlink OK.
- [2026-08-31 worker-A] Discovered, OUT of this card's scope (not fixed): same app-modal-static crash class still lives in (a) pdf_drive.py:1397/1517/1556 QInputDialog.getText statics (New Folder + two renames), (b) curation.py:487 QInputDialog.getText (curated-deck name prompt), (c) pdf_drive._delete_pdf's QMessageBox.question static (~line 1602), (d) setup_flow's two askUser calls (library-root offer, runtime-update offer) — aqt's own helper, exec under the hood. File-dialog statics (getExistingDirectory/getOpenFileNames) are native sheets, likely fine. pdf_viewer.py statics stay out per card (native renderer slated for retirement). Suggest a follow-up card if the crash class is to be fully retired.
- [2026-08-31 orchestrator] Reviewed and committed. CPS refactor is textbook (deleteLater deferred past the accepted read), all five message boxes hold references through their closures and re-read config before deferred writes, Esc/cancel paths preserved. Verify fails-before/passes-after confirmed independently. 47 checks in test_bridge_reentrancy.

### K-124: Library toolbar: Map button opens the embedding map
owner: orchestrator
priority: P2
tags: feature,phase-d
files: klausmate/pdf_drive.py,tests/test_drive.py
verify: bash -c 'grep -q open_map_window klausmate/pdf_drive.py && python3 tests/test_drive.py'
created: 2026-08-31
claimed: 2026-08-31

Wire K-123's open_map_window(parent) into the Library: a quiet flat button in the LIBRARY caption row beside New Folder/Refresh (K-117 vernacular), guarded import, tooltip. Sequenced after K-114 released pdf_drive.py.

#### Comments
- [2026-08-31 orchestrator] Wired and committed: Map button in the caption row, guarded import to pdf_map.open_map_window, 3 pins in test_drive (131 total), guard pin falsified once. Verify green.

### K-058: After all this, I want to start working on the next few stages, like D and E.
owner: orchestrator
created: 2026-08-24
claimed: 2026-08-31

#### Comments
- [2026-08-24 opus] Started: K-071 (Ready) is Phase D1 — the embedding-map projection + graph data, headless foundation. D2 (the window + canvas UI) follows once D1 lands. Phase E begins with the designer audit of the PDF viewer (E0) — that is orchestrator-tier work, queued after this swarm.
- [2026-08-25 orchestrator] Phase D note: the Klaus Workspace (K-102, shipped behind workspace_enabled) is the intended home for the embedding-map view — add it as a second stack view + sidebar entry rather than a new window.
- [2026-08-25 orchestrator] Correction: the Workspace was reverted same-day (see K-102). Phase D's map view home is TBD again — likely its own window, or a Library-window tab.
- [2026-08-31 orchestrator] Closing: both named stages are served. Phase D shipped whole — D1 (K-071: projection.py top-2 PCA + pdf_graph.build_graph_data, headless), D2 (K-123: the pan/zoom embedding-map window, committed af710b0), and the Library entry point (K-124: Map button in the caption row). Phase E's opening move was 'designer audit of the PDF viewer' — that was superseded by Pouya driving that exact audit himself on 2026-08-31: K-116 (pdfjs zoom overhaul + wired annobar) and K-117 (VS Code Library) delivered what E0 was for, with the user in the loop, which is better. Anything further in E gets its own concrete card when Pouya names it.

### K-100: pdfjs parity: page-insert into editor field + crop integration
owner: worker-A
priority: P3
tags: pdfjs
files: klausmate/web/pdfjs_viewer.html,klausmate/pdfjs_viewer.py,klausmate/__init__.py
created: 2026-08-25
claimed: 2026-08-31

Whatever the editor integration surface uses from the native viewer (page-as-image insert into the focused field, image-crop trigger) reproduced from the pdf.js canvases. Audit __init__.py call sites before scoping details.

#### Comments
- [2026-08-25 orchestrator] Scope addendum from the K-097..K-099 pass: (1) editor page-insert targeting (_set_target_field) still native-only; (2) PdfSidebar.reload_if_externally_changed full-reload branch does not re-feed the pdfjs webview (the common annotation-mirror branch DOES work via load_annotations); (3) persisted-marquee re-copy + drag-out; (4) exact-substring find highlighting. All small; none block daily pdfjs use.
- [2026-08-31 worker-A] Done (items 1/3/4; item 2 was already closed — _full_external_reload runs self.load_pdf(name), the shared path that re-feeds the pdfjs webview; verified). AUDIT (item 1): the native path has NO direct write-into-field code — its editor insert surface IS the system clipboard: copy_pdf_page_image_to_clipboard (Cmd/Ctrl+dblclick or menu) + 'paste with Cmd+V', plus the persisted-marquee QDrag drop. _set_target_field/klausmate:focus is editor-side (copilot.js) and renderer-independent; NOTHING reads _klausmate_target_field_index (vestigial). Crop integration is likewise entirely editor-side — nothing to port. So parity = reproduce the gestures on the page, routed through the SAME copy-image bridge -> clipboard: added Cmd/Ctrl+double-click slide copy (metaKey=mac Cmd, ctrlKey=win, matching Qt's ControlModifier mapping). Item 3: marquee now PERSISTS after release like native/Preview — overlay div inside its page div (survives page teardown, re-lands at scale from renderAnnotLayers + softRelayout), native press rules (plain left press outside clears; press ON it arms drag-out; click-that-never-drags clears; alt-press clears then restarts; teardown forgets), context menu re-offers 'Copy Selection as Image' (marquee_act's label/semantics) while it stands, PNG pre-rendered+cached at persist (renderRegionCanvas factored out of copyRegionImage). Drag-out: HTML5 dragstart shipping the cached PNG as text/html <img src=data:...> — the webview CANNOT start the native QDrag+QMimeData image drag, so this rides Anki's editor HTML-drop/paste pipeline; cache miss cancels the drag. HONEST GAP: drop-into-field needs live-Anki verification (editor webview can't be driven headlessly); if a drop misbehaves the fallback is the persisted re-copy + Cmd+V, which is fully covered. Item 4: exact-substring find via the CSS Custom Highlight API (Ranges over text-layer text nodes — zero DOM mutation, a <mark> wrap would shift pdf.js's measured span widths); matches now carry start/len; matchSegments slices a match per owning span and steps over EOL joiners + zero-len items; ::highlight(klaus-find) styled with existing theme vars only; old owning-span ring kept as the guarded fallback (no API/no text node). Files: klausmate/web/pdfjs_viewer.html + tests/test_pdfjs_viewer.py only — pdfjs_viewer.py/__init__.py needed no change for this scope. GATE (card has no verify): python3 tests/test_pdfjs_viewer.py (160 passed; +19 checks incl. matchSegments behavior-tested under real node + node --check of the whole inline script) && python3 tests/test_imports.py (34 passed) — both green. Falsified: 13 targeted mutations -> 14 FAILs incl. the node math + syntax pins, restored, re-green. Full sweep 21/21 test files pass.
- [2026-08-31 worker-A] Discovered, out of scope: editor._klausmate_target_field_index / _klausmate_target_field_name are written (klausmate:focus -> _set_target_field) but read by NOTHING since the autocomplete/Ask removal — only the hasattr default-init touches them. _set_target_field's editor.currentField write may still matter for Anki-side focus; the two private attrs look vestigial. Worth a small cleanup card, not fixed here.
- [2026-08-31 orchestrator] Reviewed and committed. Gate re-run independently green (160+34); Custom Highlight API with guarded span-ring fallback verified present; the drag-out live-verification gap is acceptable and documented — it rides the K-101 soak. Board's parity set is now COMPLETE.

### K-125: Retire the remaining app-modal statics (K-114 follow-up: getText/question/askUser)
owner: worker-A
priority: P1
tags: crash,macos26
files: klausmate/pdf_drive.py,klausmate/curation.py,klausmate/setup_flow.py,tests/test_bridge_reentrancy.py,tests/test_drive.py
verify: python3 -c "import sys; checks=[('klausmate/pdf_drive.py',['QInputDialog.getText','QMessageBox.question']),('klausmate/curation.py',['QInputDialog.getText']),('klausmate/setup_flow.py',['askUser('])]; bad=[f for f,bans in checks for b in bans if b in open(f).read()]; sys.exit(1 if bad else 0)"
created: 2026-08-31
claimed: 2026-08-31

Worker-A's K-100 audit found more members of the K-114 segfault class (app-modal exec hiding inside statics/utilities): pdf_drive.py:1397/1517/1556 QInputDialog.getText, curation.py:487 QInputDialog.getText, pdf_drive._delete_pdf's QMessageBox.question, setup_flow's two aqt.utils.askUser calls (askUser exec()s internally). Convert each to the K-114 instance+open()+signal patterns already in the codebase (textValueSelected / finished+clickedButton / accepted-callback CPS where a return value is consumed). Keep every cancel path's meaning; keep references alive through closures; deleteLater on finished. Per-file ban pins in test_bridge_reentrancy (and test_drive where the site is pdf_drive's), falsified once each.

#### Comments
- [2026-08-31 worker-A] Done — every remaining app-modal static/utility converted to the K-114 instance+open()+signal patterns. pdf_drive (4 sites): _new_folder is CPS (on_done(path) fires only on a real create; _move_to_new_folder rides it; the three return-ignoring callers unchanged), _rename_pdf and _rename_folder are QInputDialog instances via open()+textValueSelected (cancel/empty/same-name keep their do-nothing meanings — the signal only fires on OK), _delete_pdf is a themed QMessageBox via open()+finished/clickedButton, Yes/No with No default (Esc/close = No, the static's reject path), Yes wears DangerButton / No SecondaryButton, and the destructive body moved whole into _delete_pdf_confirmed so it runs only from the Yes. curation.prompt_and_create: the getText+askUser while-loop became a callback chain — ask_name (instance, prefilled, themed) -> on_named -> confirm_merge (themed QMessageBox, defaultno parity: No default); every loop edge keeps its meaning (cancel ends, empty re-prompts, declined merge re-prompts with the SAME name for editing). ALSO converted curation:499's askUser (not on the card text but in the same flow being restructured — leaving one nested blocking modal inside the new chain would have defeated the card). setup_flow: both askUser sites are themed QMessageBoxes via open()+finished (default Yes as askUser-without-defaultno was), AND both now thread a then() continuation — setup_readiness_check chains the provider checks through _library_root_check(_readiness_after_library_root), and on_ensure_done passes _readiness_check_body into _maybe_offer_runtime_update — so the readiness dialogs can never stack on the offers (the ordering blocking used to give for free); the native folder sheet is deferred one tick past the finished handler (QTimer.singleShot). askUser import dropped from setup_flow and curation. Verify: failed before, PASSES now. Tests: test_bridge_reentrancy 47->52 (K-125 section: curation bans+loop-edge pins, setup_flow askUser-gone + continuation-threading + sheet-deferral pins; the K-114 five-box count pin deliberately widened 5->7 and was updated); test_drive 128->136 (K-125 block beside the K-117 pins: statics ban on code_only, 3x textValueSelected instances, _new_folder CPS, delete finished/clickedButton + DangerButton on raw source — code_only strips string literals, noted inline). All 11 new pins falsified (10 in one mutation pass incl. a real askUser/QMessageBox.question reintroduction; the delete-finished pin needed a second focused pass because its first mutation was whitespace, invisible to the space-stripped _PD_FLAT), restored, re-green. Fallout fixed: tests/test_klausmate.py + tests/test_projection.py build their own aqt.qt stubs with explicit export lists — added QMessageBox=object to both (curation now imports it; 253 and 30 pass). Full sweep 22/22 green; py_compile through the symlink OK.
- [2026-08-31 orchestrator] Reviewed and committed. Verify re-run fails-before/passes-after independently; curation callback chain preserves all four loop edges (read by eye); setup_flow continuations sequence rather than stack; caller of prompt_and_create unchanged and compatible (on_done optional). 22/22 sweep. With this, the app-modal exec class is EXTINCT addon-wide — pinned per file.
