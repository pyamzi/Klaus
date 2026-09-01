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

### K-164: PdfJsViewer(QWidget) is the third QDockWidget=None-shaped import-time TypeError
owner: -
priority: P2
tags: bug,robustness
files: klausmate/pdfjs_viewer.py,tests/test_pdfjs_viewer.py
verify: bash -c 'python3 tests/test_pdfjs_viewer.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_lecture_view.py'
created: 2026-09-01

Found by the K-161 sweep, which the K-161 card asked for ("if there are two there are probably three" — there are exactly three).

klausmate/pdfjs_viewer.py:65 nulls the Qt names in its guarded-import fallback:

    except Exception:  # pragma: no cover — only in stripped test stubs
        QLabel = QSizePolicy = QTimer = QVBoxLayout = QWidget = Qt = None

and klausmate/pdfjs_viewer.py:829 then defines `class PdfJsViewer(QWidget)` at module level. `class X(None)` is TypeError: NoneType takes no arguments, raised at IMPORT time — so a partial Qt surface does not degrade the viewer, it takes the whole module down: renderer_from_config, chunk_b64, build_page_html, parse_bridge, decode_b64_json and records_from_rect_map are all aqt-free helpers that go with it, and PDFJS_AVAILABLE never gets to be False because the module never finishes importing. The comment on that except handler says "only in stripped test stubs", which is exactly the environment where the fallback is load-bearing and exactly where it does not work.

This is the same defect as index_queue._StatusDock (fixed under K-152) and lecture_view.LectureDock (fixed under K-161). Same fix, third time:

    _WidgetBase: Any = QWidget if QWidget is not None else object

with the real gate kept where the widget is actually constructed. PDFJS_AVAILABLE is already the right gate and already exists — the class definition just must not fire before anything can consult it.

NOT FIXED UNDER K-161 ON PURPOSE: pdfjs_viewer.py was in K-159 (worker-V, annotation tools) at the time, so the file was claimed and out of the sweeping lane. Check it is free before claiming.

tests/test_lecture_view.py carries an AST sweep (section "no OTHER module regrows the shape") that walks klausmate/*.py for `class X(Base)` where Base is nulled in a module-level except handler. It has ONE allowlist entry: this file, pointing at this card. Fixing this card means DELETING that entry, and the sweep then holds the invariant repo-wide with an empty allowlist. Do not add a second entry instead.

### K-166: Pin the nine boolean edges the vacuity audit found in index_queue
owner: -
priority: P3
tags: test-integrity,indexing
files: tests/test_index_queue.py
verify: J=$(mktemp -t iqaudit) && python3 scripts/mutation_audit.py --modules index_queue --json "$J" >/dev/null 2>&1; python3 -c "

import json,sys
rows=json.load(open(\"$J\"))
bad=[r[\"lineno\"] for r in rows if r[\"kind\"]==\"boolflip\" and r[\"verdict\"]==\"survived\" and r[\"lineno\"] not in (298,766,787,824)]
print(bad); sys.exit(1 if bad else 0)"
created: 2026-09-01

K-162 pointed scripts/mutation_audit.py at index_queue.py and left the
findings standing. Under `gut` the module is clean — the only survivors
are the ten Qt-widget-only functions K-152 predicted. Under `boolflip`
nine sites flip with nothing noticing, and each one is an edge with a
documented intent. Full write-up: the "Second lane" section at the end
of scripts/AUDIT.md.

The nine, in four groups (line numbers are klausmate/index_queue.py at
sha 9012ecdb11db; the fix is in the TEST file, so they should hold):

1. `:358`, `:396` — the `announce: bool = True` defaults on `request`
   and `request_pdf`. Every test call passes `announce=False`, so both
   defaults flip undetected. `on_pdf_imported` (`:408`) — the funnel
   every import surface returns through — calls `request_pdf(name)`
   bare, so this is the production path. The module docstring (`:45`)
   states the invariant: nothing is ever started silently.
2. `:373` — `_key_warned = True` flips to `False`. Its own comment is
   the invariant: ten keyless drops must not stack ten tooltips. The
   flag's RESET is already pinned (test:552); its set is not.
3. `:471`, `:485`, `:733` — three `except` arms whose polarity is a
   documented decision: `_pdf_present`'s "never lose a job to a
   bookkeeping hiccup", `signature_changed`'s fail-closed gate on a
   whole-library re-embed (its docstring is entirely about not doing
   that silently on a paid API), and `_busy_elsewhere`'s
   run-rather-than-stall. Testable by making the deferred import or the
   callee raise.
4. `:497`, `:506`, `:513` — every `active=False` publish in `_pump`
   (drained, busy-wait, give-up). `status_line` (`:205`) and
   `dock_button_label` (`:221`) both branch on that flag, so a flip puts
   a live progress line and a Stop button on the bar while nothing runs.
   The tests already reach all three branches and pin their neighbouring
   fields (`finished` at test:368, `message` at test:611) — this is an
   oversight, not a harness limit. A probe confirmed the drained branch
   executes exactly once in the suite and nothing reads what it
   published.

ACCEPTANCE: all nine are behaviourally pinned — the check must fail when
the boolean is flipped and pass when it is not. Do NOT pin them by
reading the value back from the module (`iq.request.__defaults__`, or
comparing a message against the constant that produced it): that is the
self-referential shape AUDIT.md's "one source of truth, read twice"
section is about, and it would satisfy the letter of this card while
pinning nothing. Pin the OBSERVABLE — a tooltip stub that counts calls,
a raising callee, `status_line(state())`/`dock_button_label(state())`
output. The verify command runs the audit and fails while any of the
nine still survives; the four remaining boolflip survivors (`:298`
module default, `:766`/`:787`/`:824` Qt) are excluded by line number
and are correctly out of reach.

## Ready

## Doing

### K-158: The map is a vibe, not a census: sample the notes, make the connections the point
owner: worker-U
priority: P1
tags: ui,phase-d,vibe
files: klausmate/pdf_map.py,klausmate/pdf_graph.py,tests/test_pdf_map.py
verify: bash -c 'grep -q SAMPLE klausmate/pdf_map.py && python3 tests/test_pdf_map.py && python3 tests/test_imports.py'
created: 2026-09-01
claimed: 2026-09-01

Pouya, 2026-09-01, linking https://github.com/vasturiano/3d-force-graph:

"It doesn't have to show all of the nodes. It just has to say that there are this many PDFs. It doesn't have to show all the notes — just make it simple: have a simple graph, have it zoom in onto the node of the PDFs, and show some way of connecting how it's connected to all of its notes. Forget about cards, I don't care about cards. Just make it look really nice. Make it look like I'm accessing the matrix or some shit. It just has to show a good number to give the user an idea of what's going on. It gives an idea, a mental conception of what the embedding is. That's all I care about."

THIS REVERSES K-148's CENTRAL REQUIREMENT. K-137 asked for every note and K-148 delivered all 28,668 at 4.38ms/frame. He has now looked at it and wants the opposite: a SAMPLE, chosen to convey the idea. Do not treat the existing all-notes path as sacred — but do keep it reachable behind a constant, because "how many is legible" is a tuning question and the answer will move.

WHAT TO BUILD:
1. SAMPLE THE NOTES. A few hundred, not 28k. Chosen so the cloud still reads as the embedding's shape — an even stride over the projected points preserves structure better than a random draw, and projection.py already strides for its fit. Say the real total in the caption ("4 PDFs - 28,668 notes, showing 400") so the sample is honest rather than a silent lie about the data.
2. THE CONNECTIONS ARE THE POINT NOW, not the cloud. Selecting a PDF should show how it reaches its notes. Today edges only draw for the active PDF and are a flat alpha line; make that the centrepiece — the thing the camera flight is FOR.
3. MATRIX. Dark ground, glow, depth, motion that feels alive. K-148 already has the sway, the depth fog keyed on the real depth histogram, and the fly-to. Push the look: glow on nodes, edges that read as light rather than ink, brightness falling with depth.
4. FORGET CARDS. Nothing in this view should mention cards. Check the tooltip and caption.

THE ONE JUDGEMENT I HAVE ALREADY MADE, and it is arguable — say so on the card if you disagree:
KEEP PCA POSITIONING. 3d-force-graph is force-directed: node positions come from edge topology, not from the data. For "PDF connected to its notes" that produces a star/hairball that says nothing about the embedding — it would look like the link but mean nothing, and he explicitly said the point is "a mental conception of what the embedding IS". Our positions come from projection.py's PCA of the actual vectors, which is the real thing. So: take the LOOK from the reference, keep the MEANING we have.

RENDERER: STAY NATIVE. The K-148 research rejected a webview for reasons the smaller node count does not change — map_canvas has TWO hosts (window + Library dock) and K-143 exists to stop a second renderer growing; a webview also inherits Anki's software-video-driver path. What DOES change is that a few hundred nodes make glow affordable: radial-gradient sprites and layered strokes are now cheap where they were not at 28k. If after honest effort the native ceiling cannot deliver the vibe, say so with a render and we will revisit vendoring three.js — that is a real option (pdf.js is 1.3MB of vendored JS precedent), not a failure.

MEASURE AGAIN. K-148's numbers do not carry over: the worker found round dots cost 16x square and alpha fog 5x opaque AT 28k. At 400 nodes both may be affordable, and that changes what the look can be. Re-measure rather than inheriting the constraint.

RENDER IT AND LOOK, repeatedly, in both palettes and in the dock. This is a card where the render IS the acceptance test — there is no behavioural assertion for "looks like the matrix". Save PNGs and put the paths in your comment.

#### Comments
- [2026-09-01 orchestrator] CRITIQUE FROM POUYA'S OWN SCREENSHOT (zoomed into a PDF node). "This does not look aesthetic at all. It should look like something out of a movie." He is right. Six specific defects, all visible in that one frame — fix these, not a vague "make it nicer": 1. SQUARE DOTS. The notes are axis-aligned squares, so at any real zoom the cloud reads as JPEG noise or dead pixels, not as stars. K-148 chose square deliberately because round cost 16x at 28,668 notes — at a few hundred that constraint is GONE. Round, soft-edged sprites, and re-measure to prove the cost is affordable now. 2. NO GLOW ANYWHERE. Every dot is a flat opaque chip and the PDF node is a flat solid disc. Nothing emits light. A "matrix" look is fundamentally about emission — a bright core falling off into a halo. Radial-gradient sprites for notes, and the PDF node wants a core + halo + maybe a thin ring, not a filled circle. 3. THE CLOUD IS GREY ON GREY. White-ish dots on a grey ground with no hue at all. Give it colour and let depth drive both brightness AND saturation, so near points read hot and far points sink into the ground. 4. THE LABEL COLLIDES WITH THE NODE. "…easures of Disease Frequency ELO" begins INSIDE the blue disc and is clipped on the left by it. label_anchor offsets by the node radius, but at fly-to zoom the radius is huge and the label still lands on top — so either the offset is not tracking the drawn radius at that zoom, or the flight leaves the label anchored to a stale one. Find out which; it is a bug, not a taste issue. 5. NO EDGES IN THE ONE FRAME THAT SHOULD BE ALL EDGES. This is the zoomed-into-a-PDF view — the exact moment the card says the connections ARE the point — and not one connection is drawn. Whatever gates edge drawing is not firing on the fly-to. This is the single biggest gap between the screenshot and the ask. 6. THE BLOB HAS NO STRUCTURE. It is a featureless ball. Sampling to a few hundred will help by itself (28k points at this zoom is a solid mass), but consider whether the fly-to should also dim or drop notes that are NOT this PDF's, so the ones it connects to stand out instead of drowning in everything else. Reference for the FEEL, not the layout: https://github.com/vasturiano/3d-force-graph — glowing nodes, luminous links, depth, motion. Take the light; keep our PCA positions (see the card body). THE RENDER IS THE ACCEPTANCE TEST. There is no unit test for "looks like a movie". Iterate on the picture: render, look, adjust, repeat, and put the before/after PNGs in your comment. If you cannot get there in QPainter after honest effort, say so with a render and we will revisit vendoring three.js rather than shipping something that still looks like this.

### K-165: The Library's right-hand assistant panel: make six modules reachable
owner: assistant-lane
priority: P1
tags: assistant,ui
files: klausmate/assistant_panel.py,tests/test_assistant_panel.py,klausmate/pdf_drive.py
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_assistant_panel.py
created: 2026-09-01
claimed: 2026-09-01

Six modules (card_forge, llm_client, entitlement, anki_tools, assistant_session, podcast) are committed, tested and audit-clean, and NONE of them is reachable by a user. This is the card that changes that, and the first time any of it runs inside Anki.

Pouya's surface, decided 2026-09-01: a right-hand panel in the Library beside the folder tree. Tabs for ask / practice / podcast; ask first because assistant_session already drives it end to end.

Heed K-161 while building: a QDockWidget=None import fallback is a TypeError at CLASS DEFINITION time, not at use. Subclass something that always exists.

The tool loop must run OFF the Qt main thread — anki_tools.execute_tool marshals onto it and blocks the caller, so calling it FROM the main thread deadlocks (its own docstring says so). Stream back via signals.

## Review

### K-163: Podcast script: generate and cost a two-host script from a lecture, before any audio exists
owner: assistant-lane
priority: P1
tags: assistant,podcast
files: klausmate/podcast.py,tests/test_podcast.py,klausmate/card_forge.py,tests/test_card_forge.py
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_podcast.py
created: 2026-09-01
claimed: 2026-09-01

Pouya's headline feature. TTS cannot run in the addon (Anki ships bytecode-only 3.13, no pip, and every TTS lib is native), so audio must be produced outside and downloaded — hosted OR the user's own key, his call. Playback is fine: Anki bundles mpv and exposes AVPlayer.play_file with toggle_pause and seek_relative.

This card is the SCRIPT half only, deliberately: audio on a bad script is an expensive bad script, and the cost question he raised cannot be answered until a real script exists to measure. Ships a duration and cost estimate so the audio decision is made on numbers.

Grounding rules are card_forge's, because the failure mode is the same one he named about cards: a fluent invention the user cannot distinguish from the material. Cited slides must be within the selection; the fence-stripping and page-validation helpers are EXTRACTED from card_forge rather than copied, since duplicated comparison logic is what broke eight call sites earlier today.

### K-161: QDockWidget=None import fallback is a TypeError at class definition (lecture_view has the same shape)
owner: worker-W
priority: P2
tags: bug,robustness
files: klausmate/lecture_view.py,tests/test_lecture_view.py
verify: bash -c 'grep -q _DockBase klausmate/lecture_view.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_lecture_view.py'
created: 2026-09-01
claimed: 2026-09-01

Found by worker-T while building index_queue's status dock: 'class _StatusDock(QDockWidget)' with 'QDockWidget = None' in the import fallback is a hard TypeError AT IMPORT TIME, not a graceful degradation — it took the whole runner down under a partial aqt.qt stub. Fixed there.

klausmate/lecture_view.py has the identical shape: LectureDock subclasses QDockWidget, and the guarded-import fallback sets the name to None. Under any environment where that import fails, the module does not degrade — it raises on definition and takes the Lecture panel and everything importing it with it. The guarded-import-with-None-fallback pattern is a house convention (PDF_VIEWER_AVAILABLE and friends) and is CORRECT for names used as values; it is a trap for names used as BASE CLASSES.

Fix: build the class inside a factory, or fall back to , or guard the definition. Whichever — then sweep for other 'class X(SomeGuardedName)' shapes across klausmate/ and say what you found, because if there are two there are probably three.

#### Comments
- [2026-09-01 orchestrator] Body correction — one word was eaten by shell expansion when the card was filed. The sentence should read: "Fix: build the class inside a factory, or fall back to the builtin object as the base, or guard the definition." Everything else in the body stands.
- [2026-09-01 worker-W] Done, commit 094003c. Fix is index_queue._DockBase's shape: `_DockBase: Any = QDockWidget if QDockWidget is not None else object` as the base, with the real gate moved to where the dock is actually built — `_ensure_dock` returns None when mw or QDockWidget is None, and `open_lecture_view` (its one caller) now expects that None rather than reaching AttributeError inside its try. Reproduced first: TypeError: NoneType takes no arguments, exactly as filed. THE SWEEP — exactly three sites, so "if there are two there are probably three" was right on the number: klausmate/index_queue.py _StatusDock(QDockWidget) fixed under K-152 klausmate/lecture_view.py LectureDock(QDockWidget) fixed here klausmate/pdfjs_viewer.py PdfJsViewer(QWidget) NOT fixed -> K-164 pdfjs_viewer.py was in K-159 (worker-V) at the time, so it was out of this lane; filed as K-164 with the diagnosis and the same fix. Worth noting what it costs there: PDFJS_AVAILABLE never gets to be False, because the module never finishes importing to set it — and six aqt-free helpers (renderer_from_config, chunk_b64, build_page_html, parse_bridge, decode_b64_json, records_from_rect_map) go down with it. Its except handler is commented "only in stripped test stubs", which is precisely the environment where the fallback is load-bearing and precisely where it does not work. FOURTH SITE FOUND AND CLEARED: klausmate/md3_switch.py:151 `class Md3Switch(QCheckBox)` — its handler does `QCheckBox = object`. That is this card's fix already in the tree, predating the card. The sweep pin asserts md3_switch is NOT reported, so the good shape is pinned as well as the bad one. WHY THE SWEEP CATCHES MORE THAN THE CARD ASKED FOR: a base is equally unusable when the handler assigns it None (TypeError) and when it never rebinds it at all (NameError). The pin flags both. It is AST, not grep, because the fallback is a chained `a = b = c = None` whose LAST name is the assignment value rather than a target — a regex gets that wrong. TESTS 107 -> 110. The probe runs in a SUBPROCESS on purpose: it has to swap aqt.qt and re-import, and in-process that would leave a differently-configured lecture_view in sys.modules for every section after it — including the boot-state pins at the top of the file, which were captured from a different module object. It builds its own explicit stub rather than reusing anki_stubs, because anki_stubs' aqt.qt is PERMISSIVE (PEP 562 __getattr__ auto-vivifies every name) — which is the whole reason this defect class is invisible to the default bootstrap and stayed latent here. ALLOWLIST DISCIPLINE: one entry, klausmate/pdfjs_viewer.py -> K-164, plus a pin that the allowlisted file STILL HAS the defect. A stale entry therefore fails loudly instead of quietly hiding the next offender. Closing K-164 means deleting the entry, not adding a second beside it. FALSIFICATION — sandbox copy, PYTHONDONTWRITEBYTECODE=1, local __pycache__ and this Mac's sys.pycache_prefix mirror (~/Library/Caches/com.apple.python) purged per run, sandbox hashed before/after and restored byte-identical. 9 mutations, 8 caught: F1 base reverted to QDockWidget .................. 3 red F2 _DockBase drops the object fallback ........... 1 red F3 _ensure_dock gate removed ..................... 1 red F4 allowlisted file silently loses its defect .... 1 red (the stale-entry pin) F5 md3_switch `= object` -> `= None` ............. 2 red F6 sweep glob narrowed to nothing ................ 1 red (vacuity guard) F7 QDockWidget added back to the probe stub ...... 1 red F8 probe drops its `__bases__ == (object,)` assert SURVIVED F9 fallback base is a fabricated class, not object 1 red — and ONLY that assert catches it F8 and F9 are the same assert from both sides: deleting it alone changes nothing (F2/F3 already cover those), but it is the sole catcher for a fallback base that is neither None nor object. Reported rather than papered over — it earns its keep through F9, not F8. Full suite green: 31 files, 0 failures (test_lecture_view 110, test_drive 277, test_index_queue 122, test_pdfjs_viewer 297). py_compile clean through the addons21 symlink, which I checked resolves to the main checkout. NOT DONE, deliberately: no live-Anki check. The changed path only executes when aqt.qt is partial, which never happens inside Anki — in a real profile _DockBase IS QDockWidget and the behaviour is byte-for-byte what it was. The two new gate returns are unreachable there for the same reason.

### K-162: Point the vacuity audit at index_queue
owner: worker-W
priority: P3
tags: test-integrity
files: scripts/mutation_audit.py,scripts/AUDIT.md
verify: python3 scripts/mutation_audit.py --selftest && python3 scripts/mutation_audit.py --modules index_queue
created: 2026-09-01
claimed: 2026-09-01

index_queue.py landed with 122 checks and ~100 falsification mutations, so it is in good shape — but it is not in scripts/mutation_audit.py's AUDIT_MODULES, so nothing keeps it that way. One-tuple edit; ALLOWED_TESTS derives from it. Run --selftest after, and report survivors rather than fixing them (findings become cards). Note the module is aqt-light above its glue divider, which is the condition the audit needs.

#### Comments
- [2026-09-01 worker-W] Done. verify exits 0 (it exited 2 before the edit — the tool refused index_queue as out of scope). 101 mutations, 112 test-file runs, 25s, one correct pre-skip (tooltip@278, already vacuous). Run twice: identical apart from the timing line. --selftest green before and after; tree hash clean, one external edit correctly reported as another session's (pdf_map.py / test_pdf_map.py). The hand sweep's prediction held to the name: under gut the ONLY survivors are the ten Qt-widget-only functions K-152 listed — offer_model_sweep.answered, _StatusDock.__init__/.render, _on_dock_button, _ensure_dock, _render_dock, _hide_dock_later (+ its inner go), _hide_dock, and setup (the last two source-pinned-only). 47 of 57 applied gut mutations caught. No second K-135. Beyond that list: the two operators the hand sweep did not run. 9 constants survive both strengths — all judged trivial in the report, with reasons — and 9 boolflip sites are real gaps: the announce defaults (:358,:396, the on_pdf_imported path), _key_warned=True (:373), three except arms (:471,:485,:733) and all three active=False publishes in _pump (:497,:506,:513). Written up as the 'Second lane' section of scripts/AUDIT.md; filed as K-166, not fixed here per the brief. Two notes for the orchestrator: - The AUDIT_MODULES line itself landed in 026eb36, not in my commit: the K-163 lane ran git commit -a while my edit was uncommitted in the shared checkout and swept it in. Correct and present, just attributed elsewhere. That lane also appended "podcast" directly under my index_queue comment block, so the comment now sits above two entries. - scripts/AUDIT.md's H1 still says 'six modules (K-139)' while AUDIT_MODULES carries thirteen. The assistant lanes fixed their findings rather than recording them, so the body is still honestly six; my section says so explicitly. Worth a doc pass if a third lane records a run.

## Done

### K-160: Assistant session: the tool loop the Library's right panel will drive
owner: assistant-lane
priority: P1
tags: assistant,feature
files: klausmate/assistant_session.py,tests/test_assistant_session.py
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_assistant_session.py
created: 2026-09-01
claimed: 2026-09-01

Pouya has decided the surface: the Library grows a RIGHT-hand panel beside the folder tree, and that panel is the assistant. Three features against the open PDF — ask questions, practice MCQs, generate a podcast — in-app first, web/accounts later. This unblocks K-157.

This card is the aqt-free half: conversation state plus the tool loop (stream -> tool_use -> run tool -> echo tool_result -> repeat), with tool execution injected so it tests without Anki. The Qt panel goes on top of it and is deliberately thin.

Files are disjoint from K-152, which owns pdf_drive.py/__init__.py/manage_models.py/config.json/config.md. The panel's WIRING into DriveWindow needs pdf_drive.py and is NOT part of this card — it waits for K-152 to release, and is small when it comes.

### K-159: Annotation tools stay armed, and baked text keeps its size in Preview
owner: worker-V
priority: P1
tags: bug,ui,pdfjs
files: klausmate/web/pdfjs_viewer.html,klausmate/pdfjs_viewer.py,klausmate/pdf_handler.py,tests/test_pdfjs_viewer.py,tests/test_klausmate.py
verify: bash -c 'python3 tests/test_pdfjs_viewer.py && python3 tests/test_klausmate.py'
created: 2026-09-01
claimed: 2026-09-01

Three items from Pouya, 2026-09-01. The third is K-156, which he has now independently confirmed live — absorbed here so one lane owns the whole annotation surface.

1. ADD TEXT MUST STAY ARMED. "When you're adding text to a PDF, I don't want it to automatically toggle out of add-text mode. I want to stay in that mode." Today the text tool one-shots itself (setTool(null) after placing). Make it sticky: place a box, commit it, and the tool is still armed for the next one. Clicking the toolbar button again, or Escape, disarms.

2. HIGHLIGHT MUST STAY ARMED TOO. Same ask. NOTE THIS REVERSES PART OF K-149, WHICH LANDED HOURS AGO — that card made highlight one-shot as "cause 2" of the double-highlight bug. Read commit 73dbafd before touching this.

   IT IS SAFE TO REVERSE, AND HERE IS WHY: the load-bearing fix in K-149 was never the one-shot, it was merge-on-add. The real cause was that Range.getClientRects() returns an element's border box AND its text quads for a fully-covered span, so ONE drag produced two nested rects that composited to 67.5% at the 43% paint alpha. merge_rects and merge_highlight_records fixed that at mint time, and they also make deliberate re-highlighting idempotent — a same-ink overlap is absorbed rather than stacked. So sticky mode cannot resurrect the doubling. PROVE THAT rather than asserting it: with the tool sticky, highlight the same sentence three times and assert exactly one record with one set of rects, and that a DIFFERENT ink still cuts rather than composites (K-149's yellow/green/yellow behaviour).

3. THE BAKED FONT SIZE IS IGNORED BY PREVIEW — "the fonts don't render properly on the PDF viewer in Preview... they're always small. The highlights render great, but the fonts don't."

   DIAGNOSED, exactly. In vendored pypdf's FreeText builder (vendor/pypdf/annotations/_markup_annotations.py:165-169) the /DA default-appearance string is built ONLY `if border_color:` — and pdf_handler.py:1564 passes border_color=None deliberately (K-150 argued that correctly: Preview frames a text box only while selected, so a permanent border would be wrong). So /DA ships EMPTY. Font size and colour go only into /DS, the rich-text style string, which Preview and most readers ignore. Readers therefore fall back to a default appearance: small, black. That is precisely the reported symptom, and it is why highlights are fine — they carry /C, not /DA.

   FIX: emit /DA ourselves rather than relying on pypdf's border_color path, in the standard form `/Helv {size} Tf {r} {g} {b} rg`, carrying the record's own size and colour. Keep border_color=None — the border and the appearance string are separate concerns and conflating them is what caused this. Check whether the font resource needs to be present in the annotation or page /DR for Preview specifically; many readers accept /Helv implicitly but do not assume it.

   VERIFY IN A REAL READER, not just by byte inspection. Bake a 24pt red note and a 12pt black one, open the output, and confirm size AND colour survive. macOS `qlmanage -t` renders a PDF thumbnail headlessly and is the cheapest proxy for Preview; pdf.js with annotationMode ENABLE is the second check. A /DA that looks right in a hex dump and still renders small has not been fixed.

Do not port any of this to the native QPdfView renderer — it retires with K-101.

#### Comments
- [2026-09-01 worker-V] All three items done; verify green (test_pdfjs_viewer 278->297, test_klausmate 268->284). ONE FINDING that goes beyond the card, below. 1. STICKY TOOLS. Removed setTool(null) from the three highlight mint paths (mouseup after a selection release, arming abHl over a live selection, picking an ink over a live selection) and from the text placement click. WHAT DISARMS: the toolbar button (setTool toggles: state.tool = state.tool === tool ? null : tool) and Escape. With a text box open Escape is a two-step — the box's own keydown commits it and stopPropagation keeps the document handler off, so a second Escape disarms the tool. Verified live in Blink against the real page (build_page_html + a real one-page text PDF + a stubbed pycmd): one abHl click, three drags, three hl-add posts, state.tool === 'hl' after each; abText armed, place a box, tool still 'text', click elsewhere = one text-add + the next box opens; Escape #1 editing:false tool:'text', Escape #2 tool:null. Two things a sticky tool broke that had to be fixed with it: (a) the open box now swallows CLICK as well as mousedown — stopping mousedown does not stop the click that follows, and #scroll's placement handler would have read a caret click inside your own box as 'place another box here'. Falsified live: dispatching that same click straight at #scroll committed the box (text-add) and left a NEW EMPTY one in its place. (b) an armed click ON an existing box re-edits it instead of dropping an empty one over it — the dblclick editor is unreachable while armed, because this handler opens a box on the first of the two clicks and dblclick's state.textEdit gate then returns. 2. STICKY HIGHLIGHTING DOES NOT RE-STACK — but the merge WAS weaker than K-149 believed, in a way K-149 did not model. Read this bit. The card's premise holds: the one-shot was not load-bearing, and nothing in the mint path can see the tool state, so N drags produce the same records whether the tool was armed once or N times. Three drags of the same sentence fold to one record with one rect per line (raw 6-rect Blink geometry, the stricter unmerged payload), and passes two and three change nothing at all, so _bridge_hl_add's 'merged == self._highlights' returns before any save, bake or push. A different ink still cuts rather than composites. THE FINDING: a 400-session random property walk (asserting the paint invariant directly — no two SAME-INK rects overlap anywhere in the list) failed on its first run. merge_highlight_records folded a new mark into only the FIRST same-ink record it touched, so a drag BRIDGING two same-ink marks unioned into the left one and left the right one overlapping it. Two 43% layers on the sliver = the exact 'double-highlighted' look K-149 set out to kill, reached by a third route. Reproduced on real geometry from the live page (mark the left third of a line, then the right third, then drag across the gap): the old rule left two records overlapping by 26.02pt. NOT caused by stickiness — the same three drags did this before this card — but a sticky tool is how a user reaches three overlapping drags without noticing, so I fixed it here: step 3 now folds EVERY touching same-ink record into one. The first host keeps its id (K-149's pinned rule, unchanged) and a note on an absorbed record is carried onto the survivor rather than dropped with it. After the fix the same live sequence gives ONE record with the identical rect as marking the whole line once, the committed walk passes, and an offline sweep of 4,000 sessions x 10 drags (multi-line drags, two pages, five inks; 40,000 mints) found no same-ink overlap. 3. /DA. Emitted ourselves in pdf_handler.free_text_da: '/Helv <size> Tf <r> <g> <b> rg' — e.g. '/Helv 24 Tf 1 0 0 rg' and '/Helv 12 Tf 0 0 0 rg'. Numbers are PDF operands, not reprs (12 not 12.0; 0.9804 not 0.9803921568627451). Junk colour falls back through _bake_color, junk/zero/negative/non-finite size through the new text_point_size, which now also feeds pypdf's /DS so the two appearance strings can never disagree. border_color stays None (the /BS width-0 marker and the absent /C are pinned). NO /DR and NO /AcroForm — measured unnecessary, see below; inventing an empty form dictionary in a user's lecture PDF to restate a base-14 font would be a bigger change than the fix. Bonus: _freetext_style now parses Klaus's own baked style back, which it could not before (every box read as #000000/None). 4. WHAT THE REAL RENDERER SHOWED. Primary check is PDFKit — the framework Preview.app itself draws with — via a small swiftc tool, not qlmanage: 'qlmanage -t' rendered the page completely BLANK (it does not draw annotations at all), so it is not an honest proxy on this machine and I did not rely on it. BEFORE: FreeText contents='BIG RED 24pt' font=Helvetica size=12.0 color=white 0 FreeText contents='small black 12pt' font=Helvetica size=12.0 color=white 0 AFTER: FreeText contents='BIG RED 24pt' font=Helvetica size=24.0 color=RGB 1 0 0 FreeText contents='small black 12pt' font=Helvetica size=12.0 color=white 0 Second renderer, pdf.js with annotationMode ENABLE (vendored 3.11.174, in Chromium): defaultAppearanceData went from {fontSize:10, fontName:'', black} on BOTH notes to {fontSize:24, fontName:'Helv', red} and {fontSize:12, fontName:'Helv', black}, and the canvas shows it. /DR was tried and made no difference in either engine, which is why it is not shipped. Before/after image (PDFKit, 24pt red above 12pt black): /private/tmp/claude-501/-Users-pyamzi-Documents-Github-KlausMate-Context/349d2221-d585-4e2e-8198-698ba5945b6e/scratchpad/da/k159_da_pdfkit.png The PDFs themselves: /private/tmp/claude-501/-Users-pyamzi-Documents-Github-KlausMate-Context/349d2221-d585-4e2e-8198-698ba5945b6e/scratchpad/da/before.pdf and /private/tmp/claude-501/-Users-pyamzi-Documents-Github-KlausMate-Context/349d2221-d585-4e2e-8198-698ba5945b6e/scratchpad/da/after.pdf 5. FALSIFICATION. 26 mutations run against the new pins; every one caught, no survivors, and two pins were rewritten because the sweep showed they could not fail honestly: the old 'text tool disarms' pin asked for '"setTool(null);" in _HTML116' unscoped, which the Escape handler's own copy satisfied (every sticky pin is now scoped to its handler); and the colour-fallback pin only used strings that a length-only guard would also reject, so a six-character NON-hex case was added. Two more were changed to fail cleanly instead of raising a KeyError that aborts the file.
- [2026-09-01 orchestrator] Signed off, commit a97561e. Verified independently rather than on report: both new pins mutated and watched fail — folding into the first touching record only (drop = set()) gives 2 failures, a hardcoded /DA size gives 4 — and the PDFKit before/after render inspected directly: two identical small black notes before, real 24pt red after. Full sweep 31/31 green, 3,317 checks. Compile green through the addons21 symlink. The bridging-drag overlap the property walk caught is the finding of the card: K-149 fixed the same visual defect by two of its three routes and pinned the two it modelled, so the third survived a card that was specifically about it. Going past the brief to fix it was right.
