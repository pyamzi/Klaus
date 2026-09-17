# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

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

### K-145: Map dock: Refresh does not rebuild the graph, and collapse is drag-only
owner: -
priority: P3
tags: ui,phase-d
files: klausmate/pdf_drive.py,tests/test_drive.py
created: 2026-09-01

Two deliberate omissions from K-143, flagged rather than dropped. (1) The docks graph is a per-window snapshot; the Librarys Refresh rebuilds the tree but not the map, because a rebuild is ~17s — this becomes cheap once the Map-button async card lands, and should then be wired. (2) Collapsing the dock is drag-only: the handle was widened to 6px with a tooltip, but there is no chevron affordance. Worker-L called it a judgement call and flagged it; decide with Pouya once he has used it.

### K-154: The thumbnail strip is reachable in only one of the viewer's three hosts
owner: -
priority: P2
tags: ui,consistency
files: klausmate/pdf_viewer.py,klausmate/web/pdfjs_viewer.html,klausmate/pdfjs_viewer.py,tests/test_pdfjs_viewer.py
created: 2026-09-01

Found by the K-153 viewer-consistency audit; split out because it needs the pdfjs files another lane holds.

The thumbnail toggle button lives ONLY in the editor panel (__init__.py:944-960). The other two hosts — the Library and the lecture dock — have no way to show or hide the strip. Two consequences, and the second is a real bug:

1. NATIVE RENDERER: the strip is built in all three hosts (pdf_viewer.py:3611) and its visibility restores from a SHARED, GLOBAL thumbs_state (pdf_viewer.py:3695, pdf_handler.load_thumbs_state). So toggling it on in the editor panel leaves it stuck open in the Library and the lecture dock WITH NO WAY TO DISMISS IT.

2. PDFJS RENDERER: worse — klausToggleThumbs (web/pdfjs_viewer.html:1600) has no in-page button and no keyboard binding at all, so thumbnails are 100% unreachable outside the editor panel.

Fix shape, matching K-153s conclusion: put the affordance INSIDE the viewer rather than in one host. Either a viewer-owned chrome row carrying the toggle, or add it to the pdfjs annobar (which is already host-agnostic and now carries the ink swatches) plus a keyboard binding for the native renderer.

WATCH: tests/test_pdfjs_viewer.py:133-143 pins PdfJsViewers duck-typed surface INCLUDING toggle_thumbs — that contract must still hold if the button moves.

Related zoom asymmetry worth deciding at the same time: on the native renderer zoom has NO visible affordance in any host (context menu and Cmd+/- only — pdf_viewer.py:2513 calls this out as critique P3), while on pdfjs every host gets the annobars zoom buttons. So switching renderers changes the visible control set, differently per host.

### K-155: Dead editor seam: _klausmate_active_pdf is written and never read
owner: -
priority: P3
tags: cleanup
files: klausmate/pdf_viewer.py,klausmate/__init__.py,tests/test_klausmate.py
created: 2026-09-01

Found by the K-153 audit. pdf_viewer.py:4452 (_set_active) writes editor._klausmate_active_pdf, and __init__.py:2158-2159 initialises it to None. A repo-wide grep finds NO reader — it is either dead code or an unfinished seam.

Same shape as K-140s _klausmate_target_field_* removal (commit: dead editor state written three times, read never). FIRST JOB IS TO TRY TO DISPROVE IT: grep every read including getattr and string-keyed access, and check web/copilot.js and the pycmd routing in case it crosses the JS boundary by name. If something reads it, the finding is wrong — say so and stop; that is a good outcome.

Also in scope, same file family: __init__.py:1998 hand-rolls btn.setStyleSheet("font-size: 10px; border: none;") on the per-tab close button, where panel_header_qss should own the glyph. No colour, so it clears the letter of the no-hardcoded-colour rule, but it is a hand-rolled sheet in a themed surface. Note the hardcoded-hex lint (tests/test_setup_crop_theme.py:105,139) covers only setup_flow.py and crop_dialog.py — pdf_viewer.py, __init__.py and pdf_drive.py are unaudited for colour literals, which is worth fixing on its own.

### K-157: Assistant UI surface: wire card_forge/llm_client/entitlement/anki_tools to something the user can touch
owner: -
priority: P2
tags: assistant,design
files: klausmate/__init__.py,klausmate/manage_models.py
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_card_forge.py
created: 2026-09-01

The four engine layers landed 2026-09-01 (f74a09e, 120293f, a494f2d, f1b330b, e1c023c) and are wired to NOTHING — importable, tested, unreachable by a user. Remaining work is the surface plus its registration.

BLOCKED ON A DECISION, not on code: Pouya deliberately deferred the UI. His words were that he is 'thinking something along the lines of when you have the PDF viewer showing up like that panel, you can have AI show up at the bottom of the PDF viewer, but I'm not sure yet. I don't want to jump to anything yet in terms of UI.' Do NOT pick a surface on his behalf.

Files listed are what the surface will need when it exists (hook + menu registration in __init__.py, settings rows for assistant_backend/assistant_token in manage_models.py). NOT claimed now — the other lane is editing both and should not be blocked for work that is waiting on a human.

Quality bar, from the same conversation: the failure mode to avoid is 'creating a bunch of shitty cards that you're not sure if it's good or not'. card_forge already enforces mandatory slide provenance, drops cards citing unselected slides, dedups against the existing collection before display, and writes nothing without a per-card accept. The surface must not route around any of that.

### K-171: The map reshuffles on every re-index: PC2 and PC3 are not separated by the data
owner: -
priority: P2
tags: phase-d,correctness,perf
files: klausmate/projection.py,klausmate/pdf_graph.py,tests/test_projection.py
verify: python3 tests/test_projection.py
created: 2026-09-01

Surfaced by K-167's fit-stability experiment, which was asked for as an experiment precisely because I did not believe it either way. It is not caused by the cache; the cache slightly REDUCES it. It has been true since K-058.

THE MEASUREMENT (K-167, sign-aligned, normalized units where 0.003 is about one pixel at 700px):

    50 of 28,670 notes deleted   median note moves  24 px, worst  70 px
    50 notes added               median note moves  80 px, worst 197 px
    same 28,670 vectors, only a different even-stride 4,000 sample:
                                 median note moves 150 px, worst 391 px

The last line is the one that matters: the DATA did not change at all, only which 4,000 rows the fit sampled, and the picture moved 150 px in the median.

WHY, and this is the part that makes the fix obvious. The three component standard deviations are 0.1332 / 0.1236 / 0.1190. There is no eigengap. PC2 and PC3 are not separated by the data, so a different sample simply SWAPS them (|<v2,v3'>| = 0.86, against 0.45 for a diagonal). Only the 3-D SUBSPACE is stable — principal angles 5.9 / 9.6 / 17.9 degrees. The cloud is in the same place; the axes spin inside it.

SO FITTING HARDER DOES NOT FIX IT. Fitting on all 28,670 rows instead of 4,000 is now affordable (it is a one-time cost behind K-167's cache) but near-degenerate axes stay near-degenerate: add fifty notes and PC2/PC3 can still swap. Do not spend the card on that unless the numbers say otherwise.

THE FIX THAT MATCHES THE DIAGNOSIS is to make the picture CONTINUOUS rather than the axes canonical: align each new layout to the previous one. Orthogonal Procrustes over the notes present in both layouts — given old positions P_old and new P_new (n x 3), find the orthogonal R minimising ||P_new R - P_old||, which is the SVD of P_new^T P_old. That matrix is 3x3, so this is a tiny pure-Python computation, not a linear-algebra project, and K-167's cache already persists exactly the artifact you need to align against. Decide deliberately whether to allow reflections (det = -1): forbidding them keeps handedness, allowing them gives a closer fit. Argue it.

VERIFY IT THE WAY THE DEFECT WAS FOUND: re-run K-167's three perturbations and report the same table after alignment. The number to beat is 150 px median on a pure resample; if alignment does not take that to a few pixels, it has not worked and you should say so rather than shipping it.

CONSTRAINTS:
- The alignment must not change WHAT is shown, only its orientation. A note's neighbours are the meaning; a rotation of the whole cloud is free. Pin that the pairwise distances are preserved to floating-point tolerance — an alignment that distorts is a bug, not a nicety.
- No numpy. A 3x3 SVD (or an equivalent, e.g. eigendecomposition of a 3x3 symmetric matrix, or Kabsch via quaternions) in pure stdlib. projection.py's own power-iteration idiom is the house precedent for "small linear algebra, by hand, tested".
- Degrade to unaligned rather than raising when there is no previous layout, when the overlap is too small to be meaningful (pick and justify a floor), or when the solve is degenerate.
- Reading klausmate/user_files read-only for measurement is allowed; writing is not. Tests use tempfile.mkdtemp.

### K-180: The mounted Library tree answers AX clients with 0 rows mid-rebuild: hundreds of out-of-bounds warnings per walk
owner: -
priority: P3
tags: accessibility,library,robustness
files: klausmate/pdf_drive.py,tests/test_drive.py
verify: python3 tests/test_drive.py
created: 2026-09-01

Observed by fable-ui (K-175/K-179 owner) while driving live Anki through the macOS accessibility tree, 2026-09-01: every entire-contents AX walk over the MOUNTED embedded Library emitted hundreds of Qt warnings from the tree —

    Cell requested for row 2 is out of bounds for table with 0 rows

Client-only: invisible to a mouse-and-keyboard user, but it means QTreeWidget's QAccessibleTableInterface is answering "0 rows" while an AX client is asking for row 2. Two consequences: (1) a VoiceOver user gets an inconsistent tree (real accessibility defect on the Library screen); (2) any AX-driven verification of that screen — the peer's live-probe method, the only way to check focus/keyboard paths on the real event loop — is slow and flaky, which is exactly what stopped K-179's arrow-key check from completing cleanly.

LIKELY MECHANISM, to be confirmed not assumed: the AX interface is being queried while the model is mid-rebuild. rebuild_tree() clears then repopulates (K-076 says it preserves expansion/selection/scroll, which implies clear+refill rather than diff), and it runs on mount, on every _on_index_state finished, on the watcher tick and on refresh_open_library — so an AX client walking the tree during any of those sees a table that momentarily has 0 rows while its cached row indices are still >0. Alternative: the _LibraryEmptyState overlay (K-132, WA_TransparentForMouseEvents, a sibling over the tree) or the hidden header confusing the table interface's row/column accounting. Reproduce first: an offscreen QAccessible walk (QAccessible.queryAccessibleInterface(tree) -> tableInterface() -> rowCount/cellAt) around a rebuild_tree() should show the 0-row window and the warning; a walk on a quiescent tree should not.

FIX SHAPE, whichever mechanism holds: never leave the model empty across an event-loop turn during rebuild (build the new items, then swap under one setUpdatesEnabled(False)/model reset pair), or emit a proper model reset so AX clients invalidate their cached indices. Pin with an offscreen AX walk that counts Qt warnings via qInstallMessageHandler — zero during and after rebuild.

NOT URGENT for Pouya, who does not use AX. Real for anyone who does, and real for every future live verification of this screen.

### K-207: assistant: semantic note search (card_index.top_k over the query embedding) beside the lexical search_notes
owner: -
priority: P3
tags: assistant,backlog
files: klausmate/anki_endpoint.py,klausmate/assistant_sessions.py,tests/test_anki_endpoint.py
verify: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_anki_endpoint.py
created: 2026-09-02

Final review (2026-09-02) I3: search_notes is Anki's own lexical search but was advertised as semantic in the tool description, the system prompt, spec §5.2 and AGENTS.md; the fix wave relabelled it. This card adds the semantic one for real: embed the query (the same paid embed-per-call _semantic_pdf_search already makes), card_index.top_k over the card index, map rows to note ids, the 'index stale → skip' rule; a new tool name so the lexical one keeps its precise Anki-syntax role. The verify above must gain a pin for the new tool that fails before the work.

### K-214: Map: hover re-hit-tests under the sway (the lit node follows the projected position, not the last pointer sample)
owner: -
priority: P3
tags: ui,phase-d,polish
files: klausmate/pdf_map.py,tests/test_pdf_map.py
verify: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_map.py
created: 2026-09-02

Final review 2026-09-02 M3 (optional polish, accepted rather than fixed in the final round): the hover state is computed from the last pointer sample and is not re-hit-tested as the sway moves the projected nodes, so a still pointer can sit over a node that has drifted out from under it (or onto one) without the lit state following. Pin it with an _idle_tick() under a forced cursor position.

### K-230: Assistant page PNG: cache the render beside the page record (every Send re-rasterises on the main thread since K-226)
owner: -
priority: P2
tags: api-first,plan2
files: klausmate/page_store.py,klausmate/assistant_dock.py,tests/test_page_store.py
verify: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_page_store.py
created: 2026-09-15

### K-233: duplicates.py similarity tiers are calibrated on nomic-embed-text (768-d local); re-read the band edges off text-embedding-3-large at 1024 dims
owner: -
priority: P2
tags: api-first,calibration
files: klausmate/duplicates.py,tests/test_duplicates.py
verify: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_duplicates.py
created: 2026-09-15

### K-237: Queue-side priced confirm before any from-scratch card-index embed (declining the Preferences sweep still bills the next PDF add)
owner: -
priority: P2
tags: api-first,money
files: klausmate/index_queue.py,tests/test_index_queue.py
verify: grep -q 'card-index confirm' klausmate/index_queue.py
created: 2026-09-16

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

### K-281: Evaluate TypeSafe (System One / Jev) for the pertinence Judge and the duplicate similarity tiers
owner: -
priority: P3
tags: assistant,api-first,evaluation
created: 2026-09-17

Pouya installed the typesafe@typesafe-ai skill at user scope on 2026-09-17 and asked that it be used on this project. TypeSafe is a hosted third-party API returning typed judgments (Choice, Noul yes/no probability, Score on ordered levels) rather than generated text. The two genuine fits here are the pertinence Judge (does a card belong to a lecture - a Choice/Noul shape; likely the pertinence core landed in Plan 2 T1, K-253) and the duplicate similarity tiers in duplicates.py (a Score shape; see K-233 for the calibration debt). THE TENSION, stated so the evaluation decides it rather than assumes it away: K-226 pivoted the addon to exactly two API keys, OpenAI and Anthropic, and AGENTS.md says not to resurrect provider choice. TypeSafe would be a third paid vendor with its own key, billing and outage surface. Pouya accepted that knowingly, so the bar is not "it is available" but "it beats the existing Anthropic Messages judge on real lecture data." Scope: a SPIKE, not an integration. Pick one of the two candidates, run it against the same real inputs the current judge sees, compare verdict quality, latency and cost per call, and write the numbers down. Integrate only if the numbers win. Do not declare files until the spike scopes them; the skill needs a fresh session to be loaded (installed mid-session).

### K-282: agent_host: AgentHost._read clears _running without a generation check, so stop() can silently no-op on the live child
owner: -
priority: P3
tags: assistant,lifecycle,follow-up
files: klausmate/agent_host.py,tests/test_agent_host.py
verify: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_agent_host.py
created: 2026-09-17

Flagged by the K-211 worker (2026-09-17) while adding the generation guard to the dock side, and deliberately left out of that card as out of scope. One AgentHost object is reused across PDF switches. K-211 made the dock ignore a stale exited(rc) by threading a `generation` counter through the exited callback. But one level lower, AgentHost._read itself still sets self._running = False in its finally block and in the "result" branch with NO generation compare - so when the OUTGOING child's reader thread finishes late (it joins the successor's stderr thread first, which is the same delay K-211 documented), it flips _running to False on the object that now represents the LIVE child. Consequence: stop() sees _running False and returns without signalling, so the live child cannot be stopped from the UI until it exits on its own. Fix shape: reuse the same capture-and-compare idiom (_stop_gen/_poll_stop, and now `generation`) - capture the generation at _read start and only clear _running if it still matches. The verify must gain a pin that fails before the work: drive two overlapping _read lifetimes with a fake child and assert the stale one does not clear the live one's _running. Read the K-211 commit first; do not re-guard what it already guards.

## Ready

## Doing

## Review

### K-205: assistant integration: full loop green, dock renders on chrome, endpoint answers, live checklist
owner: swarm-t13
priority: P2
tags: assistant,integration,needs-human
files: docs/superpowers/plans/2026-09-01-klaus-assistant-claude-code.md
verify: bash -c 'for t in tests/test_*.py; do python3 "$t" >/dev/null 2>&1 || exit 1; done'
created: 2026-09-02
claimed: 2026-09-02

#### Comments
- [2026-09-02 swarm-t13] DONE. Full loop: 38/38 files green, 4211 passed / 0 failed (QT_QPA_PLATFORM=offscreen, PYTHONDONTWRITEBYTECODE=1, no stale caches). 3 pre-existing honest SKIPs, none new: test_agent_host.py (no control_request in the recorded fixtures, build 2.1.228), test_page_ocr.py + test_pdf_notes.py (pypdf unavailable to those two tests' own sys.path -- pdf_handler.py/pdf_notes.py both add klausmate/vendor themselves before importing pypdf, which is why my own render script could). Dock render (scratchpad/render_dock.py -- fake AgentHost, REAL viewer_context.report_document/activate, REAL page_ocr.context_for over a pypdf-written 2-page scratch PDF, QT_SCALE_FACTOR=2, both palettes via theme.night_mode forced True/False): ALL CHECKS PASS. Header in both: "Following: Task 13 Demo Lecture.pdf . p. 1/2". Ground corners match theme.palette(night)["chrome"] exactly at both bottom corners (light #FFFFFF -> RGB 255,255,255; dark #232323 -> RGB 35,35,35). Grabbed image 840x640px, dock.devicePixelRatioF()==2.0, confirming Retina actually applied. context_for pulled real text-layer text (157 chars) and a real QtPdf-rendered PNG (39441 bytes). PNGs (attached): /private/tmp/claude-501/-Users-pyamzi-Documents-Github-KlausMate-Context/97bc4fbb-fc4d-4b55-a09b-ccaf5c79a685/scratchpad/assistant_dock_light.png (28836 bytes) and .../scratchpad/assistant_dock_dark.png (27589 bytes) -- both visually inspected, correct in every palette. Endpoint smoke (scratchpad/endpoint_smoke.py -- real ThreadingHTTPServer + anki_endpoint.Endpoint against a stub collection, hit with real curl subprocess calls, transcript saved to scratchpad/endpoint_smoke.out): version+correct token -> {"result": 6, "error": null}; version with NO token -> 403; version with a WRONG token -> 403; version with correct token but an Origin header -> 403; POST /mcp initialize -> result.serverInfo.name == "klaus"; POST /mcp tools/list -> the 13-tool ACTIONS registry (bare names: list_decks, list_models, model_fields, find_notes, get_notes, add_note, update_note_fields, add_tags, remove_tags, open_in_browse, search_notes, search_lecture_pdfs, current_view). All 6 checks pass. Permission-mode re-probe (spec 4.2, ONE real claude 2.1.228 call, empty temp dir, 90s budget, cost $0.3946885): "echo 'list files in the current directory using bash' | claude -p --output-format stream-json --verbose --permission-mode manual --allowedTools Read --disallowedTools Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task". manual IS a valid --permission-mode choice in this build (not rejected). Result: NO control_request or can_use_tool event anywhere in the 19 stdout lines; final result.permission_denials == []. Bash is simply unavailable -- absent from the system/init event's own 490-tool roster (Read/Glob/ToolSearch present, Bash/Edit/Write absent) and absent from ToolSearch's own 566-entry corpus (0 matches searching "select:Bash" or "bash shell command execute"). The model gave up on Bash, used Glob instead, and answered correctly that no Bash tool exists and the dir is empty. Confirms the spec's existing finding: --disallowedTools is the real, load-bearing guard; permission-mode shows no observed gating effect in this build, so agent_host.py's hardcoded --permission-mode default (command_line(), line 89) needs no change. Two zero-cost CLI-usage attempts before this (variadic --disallowedTools swallowing a trailing bare positional prompt, "Error: Input must be provided either through stdin or as a prompt argument") are recorded verbatim in the report; confirmed NOT to affect agent_host.command_line()'s real spawn shape, which never puts a bare prompt after the tool lists (the turn goes over stdin as one stream-json line). Secondary, unconfirmed, not chased further (one-call budget): Glob/ToolSearch ran unprompted despite --allowedTools only naming Read. Full detail, per-file table, raw transcripts: .superpowers/sdd/2026-09-01-klaus-assistant-claude-code/task-13-report.md Board note: K-206 (theme.py/library_explorer.py/test_theme.py/test_library_explorer.py/test_drive.py) claimed those files AFTER this task's loop and render already used them cleanly -- no conflict, nothing to re-run. NEEDS-HUMAN live checklist for Pouya (nothing here touched his running Anki): 1) restart Anki 2) open the Library 3) open a PDF 4) press Ctrl+Shift+K (or Tools -> Klaus Assistant) 5) the dock says "Following: <pdf> . p. 1/N" 6) ask "what is on this slide?" -> the answer streams and cites the page 7) ask "make one card from it" -> the approval dialog appears -> Approve -> the card exists in Browse with tag klaus::assistant 8) switch to another PDF -> the header follows and the session switches 9) select text in the PDF -> the chip shows it 10) click inside the PDF page then press Ctrl+Shift+K -> the dock toggles (this checks whether clicks reach the sidebar's mousePressEvent) 11) open Preferences -> Assistant -> the detected claude path shows.
- [2026-09-02 swarm-t13] FIX ROUND 1 (review: task-13-review.md). Three corrections, all done, no git writes. 1) CRITICAL, corrected: my prior comment/report wrongly claimed the real claude probe characterized --permission-mode manual. Re-verified against the EXISTING permission_probe.stdout.jsonl (no new claude -p call, per orchestrator ruling): grep -c '"manual"' -> 0 matches anywhere in the 41687-byte file; grep -o '"permissionMode":[^,}]*' -> "permissionMode":"default". So --permission-mode manual was passed on the command line but the session's own init event recorded default -- -p print mode (build 2.1.228) does not appear to honour --permission-mode manual. Free check re-run: claude --help | grep -A6 -i permission-mode still lists manual as a valid documented choice (acceptEdits, auto, bypassPermissions, manual, dontAsk, plan) -- the flag was never rejected, it just didn't take effect in the session. Every observation from that call (no control_request anywhere, Bash absent from the 490-tool init roster and from ToolSearch's 566-entry corpus, permission_denials:[], Glob/ToolSearch running unprompted despite allowedTools only naming Read) now stands relabeled as a SECOND confirmation of default -- not new evidence about manual. Removed every "under manual specifically" sentence from the report and this card's history. Spec doc docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md line 141 (only that line -- confirmed via git diff) edited to record this finding plainly instead of asserting the manual re-probe as done; left UNCOMMITTED for the orchestrator to review and commit (workers do not run git writes). No second claude -p call was spent. 2) IMPORTANT, fixed: added a 413 check to scratchpad/endpoint_smoke.py. New check 7: a 5,194,304-byte body (BODY_CAP + 1,000,000, ~4.95 MiB, over the 4 MiB BODY_CAP) sent over curl's stdin (--data-binary @-, a body this size cannot go through argv) with a VALID token -> HTTP 413 (anki_endpoint.py's drain-then-413 path, lines ~605-639); then a fresh curl subprocess (fresh TCP socket) immediately after, re-running the plain version check, confirms the endpoint is still healthy: {"result": 6, "error": null}. Both conditions ANDed into one check. Re-ran the WHOLE script twice: both times "7/7 checks passed" and "ALL CHECKS PASS", exit 0, identical results. Full 7-check output is in the report's Step 3 and in scratchpad/endpoint_smoke.out. 3) MINOR, fixed: report Step 1's "the Step 5 probe below" corrected to "the Step 4 probe below" (the probe is Step 4; Step 5 is the live checklist). Full before/after for all three items: .superpowers/sdd/2026-09-01-klaus-assistant-claude-code/task-13-report.md, new "## Fix round 1" section at the end (Step 3 and Step 4 sections above it were also rewritten in place to carry the corrected numbers/claims; Findings and Concerns updated to stay internally consistent -- no section still asserts manual was tested). Card stays in Review, still needs-human tagged, still needs Pouya's live checklist (unchanged, 11 items, still not run against his real Anki).
- [2026-09-02 orchestrator] Task review + re-review clean (loop reproduced, dock renders byte-identical, smoke 7/7 incl. 413, probe relabelled honestly; spec §4.7 committed 7ca8522). Stays in Review, needs-human: Pouya's 11-item live checklist (+ the out-of-root read item the fix wave adds) is the remaining gate.
- [2026-09-02 swarm-fixwave] Live-checklist ADDITIONS from the final-review fix wave (K-209). Append these to the Step 5 list; nothing above changes. 12. (I5, confinement) Ask the assistant: "read ~/Library/Application Support/Anki2/addons21/klausmate/meta.json and tell me what is in it". It must REFUSE or FAIL, and the transcript must NOT show the file's contents (that file holds the embedding API key). decide_permission now denies any file_path/path/pattern resolving outside the library root, but --disallowedTools is the real gate in this build, so this is the one that has to be seen. 13. (I8) Ask for a card, then approve SLOWLY — wait more than a minute before clicking Approve. The model must not report failure before the note lands, and must not add a duplicate. MCP_TOOL_TIMEOUT is now 300 s in the child's env vs the endpoint's 120 s approval wait. 14. (M7) With OCR on, flip pages fast for ~10 s. No hang, no crash; the dock keeps answering. 15. (C1) Ask a question, press Stop mid-answer, ask again. The second question must go through — no "error: stdin write failed". 16. (I6) When the approval dialog appears, press Enter WITHOUT clicking. It must CANCEL, not approve. 17. (I7) Turn on Preferences -> Assistant -> Reopen on start, leave the dock open, restart Anki. The dock comes back. I4 is already done and needs no live item: probed live (build 2.1.228) — ${KLAUS_TOKEN} expands in an inline --mcp-config header (init: klaus connected) and ps -o args shows the placeholder, not the token.

### K-219: PDF dock T4: integration — loop, renders in four placements, live checklist
owner: claude-t4
priority: P2
tags: pdf-dock,integration,needs-human
files: docs/superpowers/plans/2026-09-05-pdf-dock.md
verify: for t in tests/test_*.py; do PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 "$t" >/dev/null 2>&1 || exit 1; done
created: 2026-09-05
claimed: 2026-09-05

Plan Task 4. After T1-T3 are committed; moves to Ready then.

#### Comments
- [2026-09-05 claude-t4] Task 4 Step 4 -- live checklist (needs-human; not executed by the worker). Loop (39/39 files, 0 failed) and renders (10 PNGs, all 4 placements x night/day, integrated) are posted in the task-4 report. Verbatim from the brief: 1. Restart Anki. Open Browse; click the editor toolbar's Library… button → the PDF panel appears docked where it was last left (an old placement migrated: above/below → bottom, notes-left → left). 2. Drag the panel's empty bar to Browse's left edge → it docks beside Anki's sidebar; to the bottom edge → under both columns; away from any edge → it floats and stays above Browse. 3. Double-click the empty bar → floats; double-click again → docks back where it came from. 4. ⧉ toggles float/dock; the bar's ✕ hides the panel; Library… shows it again; ＋ still lists the Library's PDFs; a tab drag still reorders tabs. 5. Close Browse with the panel floating → no zombie window; reopen Browse → the panel comes back floating at the same place. 6. Add Cards: the same five steps; cancel Add Cards' discard prompt with the panel open → the panel is still there. 7. Under the pdf.js renderer (Preferences → Appearance) the docked and floating panel both render pages (the webview inside a QDockWidget — the Lecture dock already proves this on the main window).
- [2026-09-05 orchestrator] Review Approved: loop 39 files/4419 checks reproduced, renders reproduced and inspected, checklist verbatim. Stays in Review, needs-human: the seven-item live checklist above is Pouya's gate.

### K-229: API-first T9: integration — loop, live embed smoke (flagged), checklist
owner: claude-t9
priority: P2
tags: api-first,plan1,integration,needs-human
files: docs/superpowers/plans/2026-09-15-page-store-and-api-clients.md
verify: for t in tests/test_*.py; do PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 "$t" >/dev/null 2>&1 || exit 1; done
created: 2026-09-15
claimed: 2026-09-16

Plan 1 Task 9. Last.

#### Comments
- [2026-09-16 claude-t9] 1. Restart Anki. Open KlausMate Preferences → the page is "API keys & models" with two key fields and three model fields; no Ollama page, no OCR row, no Claude Code binary row. 2. Paste the OpenAI key and Save → the re-index prompt shows note and PDF counts and a token/dollar estimate; accept. 3. The bottom status bar shows "Embedding pages…" per PDF; the Library's rows refresh; a PDF's index directory has `manifest.json` version 2 with `pages`. 4. Right-click a PDF → Show matches in Browse still opens the `!Library` tag search. 5. Open a PDF in Browse's dock, press Ctrl+Shift+K, ask "what is on this slide?" → the answer cites the page text (no OCR); the Preferences page has no OCR switch. 6. Reviewer → Lecture panel still jumps to the matched page. 7. Remove the OpenAI key and Save → drop a PDF onto the deck screen → the refusal names the Preferences page. 8. Paste the OpenAI key for the first time and Save → a priced re-index prompt appears whose DEFAULT button is No (Enter must not start a paid sweep); accept it deliberately with Yes → the sweep runs. (New in this plan: a first key offers the sweep even though nothing changed.) 9. Live API check, embeddings: after the sweep, open the Library → every PDF row shows a retention score; `user_files/pdf_index/<safe>/manifest.json` has `"version": 2` and a `"pages"` list; the bottom status dock read "Embedding pages…" during the run. 10. Live API check, transcription: not reachable from any UI yet (Plan 2's recorder) — skip; only note that Preferences shows the `transcription_model` field with its placeholder. 11. Known gaps, not defects to report: the readiness nudge names both keys but checks only the OpenAI one (K-231); the assistant's page image is re-rendered on every Send, no cache (K-230); the `reasoning_model` field is written but not read by the assistant until Plan 3 (K-235); removing the OpenAI key and Saving does not re-prompt.
- [2026-09-16 orchestrator] Loop on 4b4841c: 43/43 files, 4505 passed, 0 failed; compile + audit selftest clean; the paid smoke skipped (no key in the session environment). Stays in Review, needs-human: the 11-item live checklist above is Pouya's.

### K-249: Klaus Plus T10: integration — FakeUpstream + env switch, local e2e, loops, the rollout checklist
owner: claude-kp10
priority: P2
tags: klaus-plus,plan-kp,integration,needs-human
files: service/klausplus/upstream.py,service/klausplus/app.py,service/tests/test_proxy.py,service/tests/test_upstream_fake.py,scripts/mutation_audit.py,scripts/AUDIT.md
verify: test -e service/tests/test_upstream_fake.py && cd service && .venv/bin/python -m pytest -q
created: 2026-09-16
claimed: 2026-09-16

#### Comments
- [2026-09-16 claude-kp10] Step 4: The rollout checklist, posted verbatim on the card for Pouya (needs-human): 1. `brew install flyctl`, `fly auth login`; from `service/`: `fly launch --no-deploy --copy-config --name klausmate`, `fly volumes create klausplus_data --size 1`. 2. Set the Fly secrets from `service/README.md` step 3, with the Stripe TEST key and spend caps set at OpenAI and Anthropic. 3. Run `scripts/stripe_setup.py` in test mode; paste its `fly secrets set` line. `fly deploy`. `/healthz` answers. 4. Open `https://klausmate.fly.dev`, subscribe monthly with card `4242 4242 4242 4242` → the welcome page shows a `kp_` key (and emails it if Resend is configured). 5. In Anki: Preferences → API keys & models → paste the key → Save → Check: the status line reads "Plus · renews … · 0 of 30 lecture hours, 0 of 3,000 cards, 0 of 200 turns"; the OpenAI and Anthropic rows say "Not needed on Klaus Plus". 6. Drop a PDF on the deck screen with no OpenAI key in config → it indexes through the service (`fly logs` shows `POST /v1/embeddings 200` with a hash prefix and a metered amount, never text); the Library row fills in. 7. Manage subscription… opens Stripe's portal; cancel at period end → Check still says active with "renews" replaced by the end date; in the Stripe dashboard, mark the subscription unpaid (or end the test clock) → Check reads refused with the service's message; a drop refuses with the same message and offers the free tier. 8. Set `KLAUS_PLUS_PAUSED=1` → a drop shows the maintenance message; unset it. 9. Going live: the live Stripe key, `MIN_CLIENT_VERSION` = the shipped add-on version, `fly deploy`, ship the add-on.
- [2026-09-16 orchestrator] Committed 1af5e40: 72 service tests, add-on loop clean, audit logged; review (sonnet) APPROVED. Stays in Review: the checklist above is Pouya's to walk (needs-human). The e2e's /v1 finding is fixed in the following commit.
- [2026-09-17 orchestrator] Re-verified 2026-09-17 while answering Pouya about the subscription system: `cd service && .venv/bin/python -m pytest -q` -> 127 passed in ~1 s (up from 72 at review), entirely keyless via KLAUS_PLUS_FAKE_UPSTREAM. Note for whoever walks the checklist: the repo venv runs Python 3.9.6 (the machine has no 3.12; only 3.9 and 3.14), and the suite is green on it despite README saying 3.12. I briefly mislabeled .venv/pyvenv.cfg as 3.14 by re-running venv on the existing dir; restored to the real 3.9.6 metadata, suite re-run green. Nothing in the 9 steps above can be done by an agent: Fly login with a card, Stripe account, and the OPENAI_API_KEY/ANTHROPIC_API_KEY secrets (config.py:74-75) are all Pouya-only.

### K-259: Plan 2 T7: docs and integration — CLAUDE.md, AGENTS.md, config.md, the audit, the live checklist (needs-human)
owner: claude-p2t7
priority: P2
tags: plan-2,docs,needs-human
files: CLAUDE.md,AGENTS.md,klausmate/config.md,scripts/mutation_audit.py,scripts/AUDIT.md,tests/test_imports.py
verify: grep -q 'pertinence' CLAUDE.md && grep -q 'lecture_recorder' AGENTS.md
created: 2026-09-16
claimed: 2026-09-17

#### Comments
- [2026-09-17 claude-p2t7] 1. Restart Anki. 2. Preferences → API keys & models: an OpenAI key and an Anthropic key (or a Klaus Plus key) saved. 3. Open a lecture PDF in the dock; press ● Record; speak for 60 seconds while turning three pages; press ■ — the bar showed elapsed time and "n to transcribe" and returns to ●. 4. The transcript strip under each of those pages shows what was said on THAT page (native viewer and pdf.js, the strip never covers a page). 5. Run the index on that PDF (Library → Update): the status line shows "judging n/m" after matching; the Judge/Skip prompt named the count (and the cost off Plus, "included" on Plus); Judge. 6. The Library row shows "n · m doubtful" when any card was rejected; "Doubtful cards…" opens Browse on that lecture's rejected cards, each tagged `!Library::Doubtful` AND the lecture tag. 7. Open Match Sensitivity: the preview score equals the row's; OK changes nothing. 8. Ask the assistant about a page you spoke over: its answer reflects the transcript. 9. Skip on a second lecture: no judging, the counts unchanged, no Doubtful tag on its cards. 10. With the Anthropic key removed and no Plus: the index runs, a log line says the judge was skipped, no prompt. 11. `user_files/recordings/<safe>/` is empty after the uploads succeeded; with the network off, the WAVs stay and are re-queued on the next Record.
- [2026-09-17 claude-p2t7] DONE (stays in Doing, needs-human). Verify: before (grep -q 'pertinence' CLAUDE.md && grep -q 'lecture_recorder' AGENTS.md) exit 1; after exit 0. Files: CLAUDE.md (Plan 2 paragraph; 'Only Plan 1 is built' and 'embeddings.py is the ONE live Plus path' both corrected — three of four purposes are live now; new pertinence.py + lecture_recorder.py entries; index_queue/tag_sync/retention/page_store/pdf_viewer/pdfjs_viewer/__init__/lecture_view/pdf_drive/pdf_map/openai_client/anthropic_client/cost/plus entries updated), AGENTS.md (intro, the network paragraph gains transcription and the judge, layout gains both modules + recordings/ + judged.json, the index chain is FIVE phases, retention diagram is confirmed-only, transcript-strip bullet, the two lecture profile hooks, conventions), klausmate/config.md (api_key_anthropic/reasoning_model/transcription_model are wired now; new 'Doubtful cards (the pertinence check)' and 'Recording a lecture' sections; confirmed-only priorities; library_tags_enabled now also costs the Doubtful tag) — NO new config key exists: config.json is byte-identical to HEAD. scripts/mutation_audit.py: AUDIT_MODULES += pertinence, lecture_recorder; SANDBOX_TREES += service/klausplus (tests/test_lecture_recorder.py lifts the service's wav_seconds by AST, so without that tree the sandbox baseline was RED and the run aborted — never a mutation target, hashed like every other tree; --selftest still OK, 212 files). tests/test_imports.py: NO change needed — its census is a glob; verified both new modules appear as their own checks (57 passed). Audit: pertinence 39 mutations, caught=15 caught-crash=15 survived=9, NO gut survivor; one real finding — bool@74:44 is the INNER additionalProperties on each verdict object, and test_pertinence.py:75 pins only the outer one (one clause closes it; that file is outside this task's set). lecture_recorder 48 mutations, caught=21 caught-crash=3 inconclusive=4 survived=20, NINE gut survivors: the pure half (Chunker, wav_bytes, chunk_path, Uploader._one incl. Plus routing/quota/refusal, _ensure_page, requeue_leftovers) is all caught; the survivors are the Qt-side Recorder the test file scopes out by its own docstring — _tick (the consequential one, pinned nowhere headless), start()'s failure/success tails, stop()'s flag, and the one-expression readouts whose values ARE pinned in tests/test_pdf_dock.py (outside this lane's reach); plus exist_ok=True at :458 (small but real). The 4 inconclusive are HANGS not survivors (drain() is Queue.join(); gutting _ensure_thread/_loop means no worker ever drains) — 300s x4 = 1200s of the 5224s run. Tree-integrity flagged klausmate/config.md as an external change: it was MY own doc edit landing mid-run, not a leak. Loop: 48 files, 4,964 passed, 0 failed, 0 non-zero exits (run twice, before and after the last doc edit); compile through the symlink OK. Step 3 paid smokes SKIPPED HONESTLY — no provider keys in this environment and none set; KLAUS_LIVE_API never set, nothing left the process, meta.json never read. Live checklist posted verbatim in the comment above. Report: .superpowers/sdd/2026-09-15-pertinence-and-lecture-recorder/task-7-report.md
- [2026-09-17 orchestrator] Review (sonnet): CHANGES REQUIRED — three stale sentences (AGENTS.md anthropic_client 'no caller' ×2; CLAUDE.md 'PRICES has exactly two entries'); fixed by the orchestrator against cost.py/pertinence.py, committed as 6fa3fda. Stays in Review: the eleven-step live checklist above is Pouya's (needs-human).
- [2026-09-17 orchestrator] Final whole-plan review (fable) — no-code items for Pouya, beside the checklist above: M-4 design debt: hiding the PDF dock (✕, last tab closed) or leaving review keeps the microphone open with no indicator — only host close, dock shutdown and profile close release it (one-line option: _release_recorder(self) in panel_hide). M-5 cosmetic: after a profile SWITCH the Lecture dock's ■ glyph stays until the next click (starts cleanly). M-6 live check: Recorder._tick polls readAll() every 250 ms on Qt's default QAudioSource buffer — speak two minutes continuously and confirm the transcript has no gaps. M-7: requeued leftover WAVs are labelled with a 30 s span even when a page change cut them short (ordering unaffected). The KLAUS_LIVE_API paid smokes were skipped (no key in the build environment): steps 3–6 and 10–11 above are those smokes, live.
- [2026-09-17 orchestrator] Fix wave landed (e82d64f): the judge now stops and reports a refusal (401/402/403/426) instead of re-sending every batch; Stop re-indexes only once the last chunk is transcribed (capped at 20 min); a card that stops matching a lecture stops being doubtful for it. Two Minors left as documented gaps: doubtful_members parses every judged PDF's matches.json on the calling thread (inherent to the fix; fine at library scale), and _request_index_when_idle resolves the uploader before its de-dup check (cosmetic).

### K-181: Four manifest readers still inline the preamble read_manifest replaced
owner: claude-manifest
priority: P3
tags: cleanup,robustness
files: klausmate/card_index.py,klausmate/pdf_index.py,klausmate/retention.py,tests/test_klausmate.py
verify: python3 tests/test_klausmate.py
created: 2026-09-01
claimed: 2026-09-17

Surfaced by /simplify's reuse angle, 2026-09-01. The manifest preamble — open MANIFEST_FILE, json.load, check "version", bail on the same exception tuple — was hand-copied at SIX sites across three modules. The /code-review fix for a JSON-but-not-object manifest (null / [] / a bare string raising AttributeError straight through into Preferences) reached only the two stats_from_disk copies, because those were the two inside the reviewed diff.

card_index.read_manifest(dir_path, version, manifest_file) -> dict | None now exists (isinstance gate, the drive_store.py idiom) and both stats_from_disk functions use it. THE OTHER FOUR still inline the preamble and still call m.get() on whatever json.load returned:

  klausmate/card_index.py  load()          (~line 115 in HEAD before this card)
  klausmate/card_index.py  load_row_map()  (~430)
  klausmate/pdf_index.py   load()          (~123)
  klausmate/retention.py   load_matches()  (~325, checks MATCHES_VERSION — pass it as `version`)

Route all four through read_manifest. card_index imports nothing from the package, so neither pdf_index (already imports card_index after this card) nor retention (already does) can cycle. Each caller's own except tuple can then narrow to the field-read errors (KeyError/TypeError/ValueError) exactly as stats_from_disk's did.

Fail-before: write "null" as the manifest and call each of the four; today load() and load_row_map() return None only by luck of a KeyError/TypeError downstream or raise AttributeError — pin the exit explicitly per function, watch it red, then route. Keep the pins in the modules' existing test files (test_klausmate.py covers card_index/pdf_index; retention's matches cache is pinned in test_klausmate too).

Do NOT touch stats_from_disk again; it is done. Do not add AttributeError to any except tuple — that was the wrong idiom and it hides attribute typos as "no index".

#### Comments
- [2026-09-17 claude-manifest] DONE, committed 5e6876c. Routed card_index.load, card_index.load_row_map, pdf_index.load, and retention.load_matches through read_manifest, exactly as specified. Two things worth flagging beyond the card text: (1) empirically verified with real payloads before touching anything (measured, not assumed) - card_index.load, pdf_index.load, and retention.load_matches all genuinely raise AttributeError on null/[]/a bare string today; load_row_map does NOT (a prior review fix already gave it its own inline isinstance guard, see tests/test_card_index.py) - so for that one function this is pure de-duplication, not a live-bug fix, and I said so rather than claiming a fourth fail-before that was not real. (2) load() and pdf_index.load() keep OSError in their except tuple (they still read a vectors file after the manifest) while load_row_map and load_matches narrow to (ValueError, KeyError, TypeError) since they touch no other file - a blind copy of "narrow to KeyError/TypeError/ValueError" onto the first two would have silently swallowed a legitimate OSError from a missing/short vectors file. Nine new corruption pins (3 functions x null/[]/bare-string) in test_klausmate.py, all confirmed red before the fix; one of my own pins was wrong on first write (the load_row_map round-trip inherited a manifest the preceding stats_from_disk loop left corrupted - fixed by rebuilding the fixture first). 433 checks in test_klausmate, test_card_index and test_projection (both already exercise these loaders) unaffected, full sweep across every test file green, symlink compile OK.

### K-239: Paid smokes behind KLAUS_LIVE_API=1 do not exist (spec testing list): embed one string, transcribe a 3 s WAV, one Messages turn
owner: swarm-livetest
priority: P2
tags: api-first,tests
files: tests/test_live_api.py
verify: test -e tests/test_live_api.py
created: 2026-09-16
claimed: 2026-09-17

#### Comments
- [2026-09-17 swarm-livetest] Built tests/test_live_api.py: three paid, opt-in smokes against klausmate.openai_client.embed() (text-embedding-3-small, 256 dims, asserts vector length), klausmate.openai_client.transcribe() (a real ~3s WAV of actual speech synthesized via macOS `say`, not silence/a tone, so "non-empty text" is a meaningful assertion), and klausmate.anthropic_client.Client.complete() (model claude-sonnet-5 per this repo's own documented default; max_tokens=256, not 16, because Sonnet 5 runs adaptive thinking by default and a tiny budget risks the reply getting crowded out). Whole file SKIPs+exits 0 before any klausmate import unless KLAUS_LIVE_API=1; each section additionally SKIPs (not fails) on its own if OPENAI_API_KEY/ANTHROPIC_API_KEY is missing. Keys come only from those env vars, never from meta.json. Two things to flag honestly: 1) Commit location: this worker's session is pinned to worktree cranky-taussig-29e82a, and the harness's Write tool refused to write the file directly into the main checkout ("may corrupt the user's primary working copy"). Committed instead on branch claude/upbeat-moser-d85455 (commit 6078286) - needs merging/cherry-picking into the main checkout, matching how this swarm's other work has been integrated. Also worth noting: that worktree's own klausmate/ is a stale snapshot that predates openai_client.py/anthropic_client.py entirely (no api-first pivot), so the file cannot be run live from inside that worktree even after the merge lands - it needs the current klausmate/ package alongside it, which the main checkout has (confirmed the addons21 symlink points there). 2) Live verification: py_compile passed for tests/test_live_api.py and for the real addon through the addons21 symlink; running with KLAUS_LIVE_API unset exits 0 on the SKIP path. I additionally verified (read-only, via a scratch script, no writes to the main checkout) that install_package_stub + importing klausmate.openai_client/anthropic_client from the ACTUAL main-checkout klausmate/ succeeds and that embed/transcribe/Client.complete/text_of/error-class shapes match exactly what the test calls. I could NOT exercise an actual live run: no OPENAI_API_KEY or ANTHROPIC_API_KEY is set anywhere in this environment, and I deliberately did not read klausmate/meta.json (Read is denied on it by this repo's own settings, and it holds API keys) to go hunting for credentials there. So all three smokes would print SKIP as-is here - the real paid wire calls are unexercised until someone runs this with actual keys.
- [2026-09-17 orchestrator] Orchestrator: the file now lives in the main checkout too (commit above, copied unchanged from 6078286 on the worktree branch). Re-verified here: py_compile clean, skip path exits 0, all five referenced symbols exist in the current openai_client/anthropic_client with matching signatures. Live path stays unverified on purpose — Pouya confirmed there are no provider keys and will be none until the subscription system (Klaus Plus, K-249 rollout) is live. Leaving in Review until keys exist; the verify gate (file exists) passes.

## Done

### K-178: A documentless PDF viewer paints a raw grey slab in the Library
owner: swarm-viewer
priority: P2
tags: ui,library,polish
files: klausmate/pdf_viewer.py,klausmate/pdfjs_viewer.py,klausmate/theme.py,tests/test_drive.py
verify: python3 tests/test_drive.py
created: 2026-09-01
claimed: 2026-09-17

Seen in the K-175 sign-off render (offscreen, 2x, night): the Library's middle pane — the PdfSidebar's QPdfView with NO document loaded — paints a flat light-grey slab between the dark tree and the dark assistant pane. In day mode it is a mid-grey slab on a light ground. Either way it is the first thing on screen when the Library opens and reads as a broken widget.

PRE-EXISTING, and correctly declared out of scope by K-175's owner ("a documentless QPdfView paints mid-grey in both modes — not this card"). It predates K-173 too: the standalone window also built its sidebar with no document. K-173's lazy viewer build did not cause it, but the embedded screen is now the shape the toolbar link prefers, so far more eyes land on it.

WHAT TO DO: an empty-state for the viewer pane, in the Library's own ground colour, with one muted line — the same treatment _LibraryEmptyState (K-132) gives an empty TREE: a sibling overlay in theme tokens, WA_TransparentForMouseEvents so drops and clicks still reach the widget beneath, shown when no document is loaded and hidden on the first on_loaded. Both renderers: QPdfView (native) and the pdf.js webview, whose blank page is its own colour and may need the html body ground set from theme.css_vars instead. Copy the K-132 empty-state vernacular; do not invent a second one.

VERIFY BY RENDER, both palettes, both renderers where the machine allows (PyQt6-WebEngine is not installed for system python3, so pdf.js cannot be rendered headless here — say so rather than claim it). Pixel-read the pane's centre before and after: the "after" must be within the palette's bg family, never the raw QPdfView grey.

#### Comments
- [2026-09-02 claude-task8] Closed by commit 5fe57e4 (board card K-208, Task 8 of the constellation-and-panel-integration plan). PdfViewer now points every palette role a documentless QPdfView might read (Window/Base/Dark/Mid) at theme.palette(night)["bg"] via setPalette on both the QPdfView and its viewport plus viewport setAutoFillBackground(True), applied right after setZoomMode in PdfViewer.__init__ (klausmate/pdf_viewer.py). The palette approach worked on the first try in this offscreen environment -- no need for the overlay fallback the brief offered as a backup. Real-render evidence (tests/test_drive.py's K-173 offscreen section, a live embedded DriveWindow with a page loaded then cleared back to documentless so tree+viewer+map are all on screen together): night=True centre=#191919 (exact match to bg, tree/map read #232323=chrome); night=False centre=#f5f5f7 (exact match to bg, tree/map read #ffffff=chrome) -- the viewer reads visibly and numerically darker than the panels in both palettes, per Pouya's ask. Two new pins added to tests/test_drive.py, RED before (both read Qt's raw #9f9f9f grey) and GREEN after; mutation-tested (emptying the palette-role tuple goes red, restored byte-identical, md5 08b893bd84b5eec7b9200ab571443ddb). Full addon loop: 36 of 38 test_*.py files 0 failed; test_agent_host.py and test_assistant_dock.py currently crash in this shared checkout on live, uncommitted, in-progress edits from a concurrent session (board card K-209, owner swarm-fixwave) to agent_host.py/assistant_dock.py themselves -- unrelated to this change, confirmed by git status/diff showing zero overlap with the two files this commit touches.
- [2026-09-17 swarm-viewer] Already done — no new work needed. Grabbed for this swarm without checking Backlog freshness first; found on inspection that commit 5fe57e4 (K-178, K-208, dated 2026-09-02) already shipped exactly this: PdfViewer.__init__ sets the QPdfView + viewport palette to theme.palette(night)["bg"] with setAutoFillBackground(True), confirmed present at klausmate/pdf_viewer.py:837-839. Re-ran the card verify (python3 tests/test_drive.py) on current HEAD: 371 passed, 0 failed. Releasing rather than duplicating — this card should have been archived out of Backlog when 5fe57e4 landed.

### K-210: page_ocr: OcrScheduler _busy set before _start, render_page_png off the GUI thread, and gate OCR on a missing/short text layer
owner: swarm-ocr
priority: P3
tags: assistant,backlog
files: klausmate/page_ocr.py,tests/test_page_ocr.py
verify: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_page_ocr.py
created: 2026-09-02
claimed: 2026-09-17

Final review (2026-09-02) M7 + M5, left open by the fix wave because page_ocr.py was outside its file list. M7: OcrScheduler sets _busy before _start (a failed start leaves it stuck) and render_page_png drives QPdfDocument on a plain worker thread — live check is K-205 item 14 (flip pages quickly with OCR on). M5 (product call, Pouya's): only OCR when the PDF's own text layer is missing or short — the docs already describe OCR that way, and it cuts the per-page-flip GPU cost about 3x on a laptop. The verify must gain a pin that fails before the work.

#### Comments
- [2026-09-17 swarm-ocr] NO-OP -- premise voided by later work, not fixed. Read the real tree first, per house convention: klausmate/page_ocr.py and tests/test_page_ocr.py do not exist anywhere on this machine (checked both the main checkout at /Users/pyamzi/Documents/Github/KlausMate-Context and my assigned worktree). Git history explains why: commit 1198041 ("Delete the OCR path and the Ollama wiring; config migrates to the two API keys; the assistant's page context reads page_store (K-226)", 2026-09-15) deleted both files outright (224 + 163 lines) as part of the documented API-first pivot (docs/superpowers/specs/2026-09-15-api-first-klaus-design.md). K-226 itself -- archived today, 2026-09-17 -- lists these exact two paths in its own files: field, and its worker comment says outright: "page_ocr.py has no module-top importer and is safe to delete" / "page_ocr.py + test_page_ocr.py ARE deleted." Live AGENTS.md's 2026-09-15 "third clearing-out" section documents the same removal by name and is explicit: "Don't resurrect provider-choice, local-install or OCR language" -- the PDF's own text layer inside a page record, plus a page PNG, replace per-page OCR entirely, not just gate it the way M5 asked. Repo-wide grep of klausmate/ turns up zero references to page_ocr, OcrScheduler, or any OCR-specific text-layer gate; render_page_png survives only as an unrelated, relocated helper in page_store.py (consumed by assistant_dock.py) with no scheduler, no _busy flag, and no worker-thread QPdfDocument call -- M7's whole concurrency shape left the codebase with the module, and M5's threshold question is moot because there is no OCR path left to gate. ocr_enabled/ocr_model config keys are also being actively scrubbed per AGENTS.md, which confirms deliberate full removal rather than an incomplete refactor for this card to finish. Evidence gathered (fail-before in the spirit the card asked for, though not the kind expected): `python3 tests/test_page_ocr.py` -> can't open file ".../tests/test_page_ocr.py": [Errno 2] No such file or directory, exit 2 -- not a logic-bug red, a missing-module red that no source fix can turn green without recreating deleted, doctrine-forbidden code. `python3 -m py_compile` through the real Anki symlink is clean (exit 0) at HEAD without the file, so nothing is broken by its absence. Made no edits to klausmate/page_ocr.py or tests/test_page_ocr.py (neither exists to edit) and made no commit (nothing changed, and manufacturing one would mean resurrecting explicitly forbidden code just to satisfy the verify gate's letter over its intent). Recommend closing K-210 as superseded by K-226 rather than reworking it. Separately flagging for grooming: K-210's verify: command can never pass again without violating the API-first decision, so it should be retired rather than left dangling for the next worker to re-discover this same dead end. Moving to Review for that call.
- [2026-09-17 orchestrator] Orchestrator sign-off: confirmed independently. klausmate/page_ocr.py and tests/test_page_ocr.py do not exist; commit 1198041 ("Delete the OCR path and the Ollama wiring... (K-226)") removed them deliberately as part of the API-first pivot, K-226 is already archived, and AGENTS.md says not to resurrect OCR. K-210 was filed 2026-09-02, before that pivot, and was never retired when K-226 landed. Closing as superseded by K-226 — no code change, no commit. Lesson for the board: a Backlog card should be checked against the current tree before dispatch; this is the second stale pick in one swarm round (K-178 was already fixed by 5fe57e4).

### K-199: Map: bound spanning_tree's O(n^2) as the library grows (grid or a global sample cap)
owner: swarm-map
priority: P1
tags: ui,phase-d,perf
files: klausmate/pdf_map.py,tests/test_pdf_map.py
verify: python3 tests/test_pdf_map.py
created: 2026-09-02
claimed: 2026-09-17

#### Comments
- [2026-09-02 controller] From K-197's review (2026-09-02): split_cloud samples SAMPLE_PER_PDF=90 per PDF with no aggregate cap, so spanning_tree (Prim, O(n^2), once per canvas build) scales quadratically with PDF count — fine at 4 PDFs, a multi-second open at 100-200. Options: a global sample cap independent of PDF count, a grid-accelerated tree, or a realistic multi-PDF benchmark first. Also: cap<=0 in constellation_links drops the backbone before it is built (unreachable today; docstring caveat).
- [2026-09-02 orchestrator] PROMOTE TO P1 (final review 2026-09-02, measured under python3.14): spanning_tree is cleanly quadratic — 520 pts 24 ms, 1,000 89 ms, 2,000 357 ms, 4,000 1.4 s, 8,000 5.7 s; split_cloud feeds SAMPLE_NOTES 420 + SAMPLE_PER_PDF 90 × #PDFs with no aggregate cap, on the GUI thread in _MapCanvas.__init__ (every Library open/refresh that rebuilds the dock canvas, every Map window open). ~20 PDFs ≈ 0.45 s, 50 ≈ 2 s, 100 ≈ 8 s. The docstrings' 'sub-millisecond' claim was wrong by ~25× and was the premise of this card's deferral. Options: Kruskal over the kNN grid candidates + a component-bridging pass; Prim on a ≤600-point stride sample with the rest attached via the grid; or a global cap on linked points that also bounds the per-PDF drawPoints band groups (same curve, on the paint path). Land before the library passes ~20 PDFs.
- [2026-09-17 swarm-map] Fixed via option 3 (global cap on total LINKED points) — split_cloud now shrinks each PDFs own per-PDF sample once len(pdfs) * SAMPLE_PER_PDF would exceed a new LINK_TOTAL_CAP=600, floored at 1/PDF. Chosen over options 1/2 because it also bounds the per-PDF drawPoints band-grouping cost on the paint path (fed by the same linked dict, same growth curve) with the smallest diff, matching this codebases stated preference for a cap over a rewrite. per_pdf<=0 (draw-every-match escape hatch) is untouched. Re-measured myself before touching anything (python3.9.6, this machine, not the python3.14 quoted above — numbers differ but the quadratic shape matches exactly): spanning_tree alone: 520pts 33ms, 1,000 118ms, 2,000 483ms, 4,000 1.86s, 8,000 7.55s. Uncapped split_cloud aggregate fed straight to it: 4 PDFs 780pts/71ms, 20 PDFs 2,220pts/573ms, 50 PDFs 4,920pts/2.86s, 100 PDFs 9,000pts/10.3s. After the fix, at production defaults the point count plateaus instead of climbing: 4 PDFs unchanged (780pts/71ms, below the caps threshold), 20/50/100 PDFs all land at 1,020pts and 127-131ms — same ballpark as todays ordinary 4-PDF cost, regardless of how large the library gets. Also added a docstring caveat (not a code fix) on constellation_links: cap<=0 drops the spanning-tree backbone too, since the early return fires before the backbone is built. Left undone because every real caller passes LINK_MAX=300 (never <=0) and fixing it would require changing the existing cap=0 pin in tests/test_pdf_map.py for a path nothing today can reach — flagged as low-priority in the review, so documented rather than restructured. New tests/test_pdf_map.py section "K-199": aggregate stays <=LINK_TOTAL_CAP at 10 and 150 PDFs (600, not 900 or 13,500), a 4-PDF library is unaffected, per_pdf<=0 still bypasses the cap, flat point count never exceeds SAMPLE_NOTES+LINK_TOTAL_CAP at 4/10/30/80/150 PDFs, and a wall-clock guard that 80 PDFs builds the spanning tree in well under a second. Confirmed red on the pre-fix code (AttributeError: no LINK_TOTAL_CAP — the new checks require the fix to even run) and green after. Verify: python3 tests/test_pdf_map.py -> 311 passed, 0 failed, exit 0 (run against the actual main-checkout files the Anki symlink loads). python3 -m py_compile through ~/Library/Application Support/Anki2/addons21/klausmate/*.py -> exit 0. Commit 5453835 on the main checkout (cherry-picked cleanly from the worktree commit b524965 after the main checkout advanced past K-239 in the meantime).
- [2026-09-17 orchestrator] Orchestrator sign-off: 5453835 in the main checkout, only pdf_map.py + test_pdf_map.py. Re-ran the card verify myself (311 passed) and every test file that imports pdf_map or manage_models — test_drive 371, test_klausmate 434, test_projection 76, all green — plus the symlink compile. Option 3 (LINK_TOTAL_CAP=600) was the right pick: smallest diff, and it bounds the paint-path band grouping for free since both read the same dict. Measured 100 PDFs: 10.3 s -> 127 ms.

### K-232: manage_models.py still runs four K-114-banned blocking dialogs (askUser ~1815; QMessageBox.question ~1933/1949/1960) — convert to window-modal open()+finished
owner: swarm-dialogs
priority: P2
tags: k114,preferences
files: klausmate/manage_models.py,tests/test_dialog_logic.py
verify: ! grep -n 'askUser\|QMessageBox.question' klausmate/manage_models.py
created: 2026-09-15
claimed: 2026-09-17

#### Comments
- [2026-09-17 swarm-dialogs] Converted all four blocking dialogs to window-modal open()+finished, modeled on this same files clear_assistant_sessions and pdf_drive._delete_pdf (K-125/K-114 shape): save_threshold (askUser -> QMessageBox, default Yes per askUser no-defaultno parity, Library refresh runs from every exit path via a _refresh_library helper), start_index (QMessageBox.question -> QMessageBox, No default + DangerButton Yes for the destructive re-index-from-scratch confirm), confirm_close (two QMessageBox.question -> two QMessageBox instances chained via a plain _after_dirty_check continuation so the discard-changes and stop-indexing confirms can never stack). Also reworded the pre-existing clear_assistant_sessions comment (it spelled out "QMessageBox.question() static" in prose, which the verify grep would keep matching) to say "question() static", matching pdf_drive.pys phrasing. Extended tests/test_dialog_logic.py with a whole-file ban pin plus per-function AST-extracted source-pins for all three converted functions. Verify passes; test_dialog_logic.py 187 passed/0 failed; py_compile clean. Committed as 70816bd on branch claude/upbeat-moser-d85455 in worktree cranky-taussig-29e82a -- this lands on that branch, not the main checkout, since direct writes there were refused as unsafe (different branch sharing this repos .git); merging the branch is needed before the live addon sees the fix.
- [2026-09-17 orchestrator] Orchestrator: landed in the main checkout as 6001b9c (cherry-pick -x of 70816bd from the worktree branch, applied clean). Re-verified here: the grep-absence gate passes, tests/test_dialog_logic.py green, symlink compile OK. The worker could not write to this checkout because the Edit tool refuses cross-checkout writes from a pinned worktree — same finding as K-210 and K-239; the worktree's CLAUDE.md also still names the nonexistent Addons/klausmate path. Pattern for the rest of this swarm: commit on the worktree branch, report the SHA, orchestrator cherry-picks.
- [2026-09-17 orchestrator] Orchestrator sign-off: 6001b9c in the main checkout. Grep-absence gate passes, test_dialog_logic 187, and the wider blast radius (test_manage_models_assistant 129, test_klausmate 434, test_assistant_dock 176, test_md3_switch 44, test_bridge_reentrancy 80) all green after the cherry-pick. The continuation-passing shape for the two chained close confirms matches setup_flow, and the comment rewording was necessary for a comment-blind grep gate — noted so nobody "restores" the literal.

### K-211: assistant_dock: a switch mid-turn — flush the outgoing block before clearing, and generation-guard _on_exited (stale exit clobbers the live turn)
owner: swarm-dock
priority: P2
tags: assistant,lifecycle
files: klausmate/assistant_dock.py,klausmate/agent_host.py,tests/test_assistant_dock.py,tests/test_agent_host.py
verify: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_assistant_dock.py
created: 2026-09-02
claimed: 2026-09-17

From the fix wave's round-2 re-review (2026-09-02), both pre-existing round-1 behaviours: (1) deltas that arrived BEFORE a viewer switch are flushed into the incoming transcript — _close_assistant_block runs against the cleared document with a stale cursor, so the outgoing PDF's partial answer lands above the new header; fix: clear _assistant_block_open/_assistant_raw_text in _switch_session (the New Session path is outside the _sending_pdf_safe key). (2) _on_exited has no generation guard and _read's finally always fires it, delayed by a _drain_stderr join on the SUCCESSOR's stderr thread — the outgoing child's exit resets the live turn's _host_pdf_safe/_sending_pdf_safe/running state, falsely reports the death, and the live turn's result then remembers nothing. Live check: K-205 item 8 (switch PDFs mid-answer). The verify must gain pins that fail before the work.

#### Comments
- [2026-09-17 swarm-dock] Both premises confirmed on reading the real code. Fixed both, tests RED before / GREEN after. Bug 1 (stale transcript leak): confirmed exactly as described. _close_assistant_block only guards on _assistant_block_open, never on _is_stale_turn/_sending_pdf_safe, so it flushes whatever's buffered regardless of staleness. _switch_session's transcript.clear() + _append_muted_line("New/Resumed session...") triggers _close_assistant_block via _append_muted_line, and if a delta had opened a block for the outgoing turn, its raw text gets reinserted at the stale _assistant_raw_start position into the just-cleared document - above the new header. IMPORTANT: _on_new_session_clicked has the byte-for-byte identical shape (clear -> append_muted_line -> same leak) and was NOT named in the card's fix description, but grepping its body shows it needed the exact same treatment - fixed both call sites with one new helper, _discard_assistant_block(), rather than duplicating the reset inline. Bug 2 (dying outgoing child clobbers the live turn): confirmed. _on_exited lives in assistant_dock.py (not agent_host.py - the card's "likely agent_host.py" guess was wrong on file, right on mechanism), wired via _Bridge.exited <- AgentHost._read's `finally`. One AgentHost object is reused across PDF switches (only _proc/_reader/_stderr_thread get replaced per start()), so an outgoing child's dying reader thread calls _drain_stderr(), which joins self._stderr_thread - by then already overwritten with the NEW child's stderr thread - delaying the stale exited(rc) until after the new turn is live. Reused the existing _stop_gen/_poll_stop capture-and-compare idiom: AgentHost now has a `generation` int (bumped every start()), captured locally in _read() and threaded through the exited callback/signal; _on_exited no-ops on a generation mismatch. Secondary finding, NOT fixed (out of scope for this card, flagging for a follow-up): AgentHost._read's `finally` also unconditionally sets self._running = False (and the "result" branch does too), with no generation guard. Same staleness mechanism as Bug 2, one level lower - a stale child's belated finally can clear AgentHost._running while a new child is genuinely running, which would make stop() on the live child silently no-op (AgentHost.stop() checks `not self._running` and returns early). Never manifests through assistant_dock's own _running flag (which _on_exited's fix already protects), so it's a narrower, latent issue, not the bug this card describes - left it alone rather than expanding the diff. Evidence: added pins to tests/test_assistant_dock.py (leak: switch AND New Session call sites; generation guard: stale-vs-current exit, with a _fire_exited wrapper so the pre-fix signature mismatch reports as a clean failed check) and tests/test_agent_host.py (generation counter mechanics + exited payload carries it). Confirmed RED against pre-fix source (AttributeError: 'AgentHost' object has no attribute 'generation'; leaked text present in transcript; generation-guard calls raising against the old 1-arg callback) by temporarily reverting just the two source files via git checkout, then restored the fix and confirmed GREEN: test_assistant_dock.py 193 passed/0 failed, test_agent_host.py 92 passed/0 failed. Also reran test_slot_guards/test_drive/test_klausmate/test_manage_models_assistant/test_theme (all import one or both modules) - all green, no regressions. Process note for the orchestrator: this session was sandboxed into a git worktree (.claude/worktrees/cranky-taussig-29e82a) whose branch had forked from an unrelated, weeks-old point with none of these four files present. The Edit tool hard-refused any write to the main checkout path, warning it "may corrupt the user's primary working copy" since edits there wouldn't land on this session's branch - so per that guard I fast-forwarded the worktree's branch (claude/upbeat-moser-d85455) to the main checkout's own current commit (5e6876c, verified byte-identical on all four files first) and did all work there instead of directly in the main checkout as CLAUDE.md's own convention asks. The fix is committed as 1dd40bd on claude/upbeat-moser-d85455. py_compile ran clean against the worktree copy; the symlink-based compile check would currently only re-check the UNMODIFIED main-checkout files since my commit hasn't been merged/cherry-picked there yet - that integration step still needs to happen (from within the main checkout itself) before Anki will load this fix.
- [2026-09-17 orchestrator] Orchestrator sign-off: landed in the main checkout as 6eb6327 (cherry-pick -x of 1dd40bd, clean). Re-ran here: test_assistant_dock 193, test_agent_host 92, symlink compile OK. Two corrections the worker made to the card are right and now recorded: _on_exited lives in assistant_dock.py (wired from AgentHost._read's finally via _Bridge.exited), and _on_new_session_clicked had the identical leak and is fixed by the same _discard_assistant_block helper. The AgentHost._read _running staleness gap it flagged is filed as its own Backlog card rather than folded in.

### K-234: tests/test_pdf_dock.py flakes under the full offscreen loop (1 in 3 runs; green standalone) — find the order/timer dependency
owner: swarm-flaky
priority: P2
tags: tests,flaky
files: tests/test_pdf_dock.py
verify: for i in 1 2 3; do PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_dock.py >/dev/null 2>&1 || exit 1; done
created: 2026-09-15
claimed: 2026-09-17

#### Comments
- [2026-09-17 swarm-flaky] Root cause found and confirmed via a live crash, not a guess: this is a native SIGBUS during Python interpreter shutdown, not a check() failure. Every check() genuinely passes when it happens (report() prints "106 passed, 0 failed") -- the crash lands during Py_FinalizeEx, after the script's own logic is done, which is exactly why it looked like a 1-in-3 ordering flake rather than an exit-time crash outside any check's view. Mechanism: test_pdf_dock.py builds ~20 real QMainWindow/PdfDock pairs across its sections but never closes most of them -- several sections bind throwaway docks to one-off names (_d0, d4, d5, d6, d7) that are never reassigned or released. Instrumented the file with gc.collect() + object counts: 9 of these stay fully live and reachable (not even a GC-collectible cycle -- genuinely still referenced) at end of run. PyQt6's own exit-time cleanup -- QtCore's cleanup_on_exit, called from Py_FinalizeEx, walking every remaining live sip wrapper via sip_api_visit_wrappers -- SIGBUS-es under a big enough pile of those. Caught the live crash via a macOS crash report (~/Library/Logs/DiagnosticReports/Python-2026-09-17-164442.ips): EXC_BAD_ACCESS/SIGBUS, KERN_PROTECTION_FAILURE, stack = sip_api_visit_wrappers <- cleanup_on_exit (QtCore.abi3.so) <- ... <- Py_FinalizeEx <- Py_Exit <- PyRun_SimpleFileExFlags <- Py_RunMain <- Py_BytesMain. Reproduction: the documented runner is one python3 subprocess PER file, sequential -- 10 clean sequential full-suite passes, plus 36 more test_pdf_dock.py runs under single-lane CPU contention, never reproduced it, because sequential subprocesses never overlap in time and so can never contend with each other for the exit-time walk. It reproduces only under REAL concurrent load: several full suites racing on the same machine at once (the realistic condition on a busy multi-agent box -- Anki was live throughout my testing too). Caught on round 5 of a 3-lane concurrent stress run (~13-15 individual runs in); the crash report's timestamp lines up exactly. Fix (tests/test_pdf_dock.py only, no production file touched): every (win, dock) pair _dock() builds is now recorded in _all_docks; at the very end of the file, before report()/SystemExit, all of them are explicitly torn down (_on_host_closing() + close() + deleteLater(), processEvents() pumped to run the deferred deletes, then gc.collect()) so the interpreter has nothing large left to walk at exit. Added one check() confirming every dock ends up torn down (107 passed, 0 failed now, up from 106). Verification: card's own 3x-standalone verify still passes; py_compile through the Anki symlink is clean (no klausmate/*.py touched -- this was never a production bug). 60 concurrent runs (20 rounds x 3 lanes, same contention profile that caught the crash, each lane racing test_pdf_map.py/test_drive.py/test_dialog_logic.py alongside it) completed with zero failures and generated no new crash report (only an unrelated, pre-existing Sept-16 report remains on the machine). Process note for the orchestrator: this session's harness placed me in worktree .claude/worktrees/cranky-taussig-29e82a (branch claude/upbeat-moser-d85455), and its Edit tool refused a direct edit to the main checkout's tests/test_pdf_dock.py ("may corrupt the user's primary working copy" -- the main checkout is on an unrelated branch, claude/repo-root-casing, with its own uncommitted board/ changes right now). So the actual fix is committed on that worktree branch (commit 20a89d8), not directly in the main checkout -- this board comment/move is run against the main checkout's board.py since that's the copy where K-234 actually exists (my worktree's board/BOARD.md is a stale snapshot that doesn't have this card at all). The commit needs to be merged/cherry-picked from claude/upbeat-moser-d85455 into main.
- [2026-09-17 orchestrator] Orchestrator sign-off: landed in the main checkout as eb09eae (cherry-pick -x of 20a89d8, test file only). Re-verified here: the card's 3x standalone loop passes, symlink compile OK, and 6 concurrent runs (3 lanes x 2 rounds, the contention profile the worker caught the SIGBUS under) all exited 0 with no new Python crash report in DiagnosticReports. The root cause stands as found: not a test-ordering dependency but an exit-time native crash in PyQt6's sip wrapper walk with ~9 never-closed QMainWindow/PdfDock pairs still live; explicit teardown before report() removes the pile. The card's title premise was wrong in an instructive way and the comment records that.
