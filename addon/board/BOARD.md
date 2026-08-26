# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

### K-058: After all this, I want to start working on the next few stages, like D and E.
owner: -
created: 2026-08-24

#### Comments
- [2026-08-24 opus] Started: K-071 (Ready) is Phase D1 — the embedding-map projection + graph data, headless foundation. D2 (the window + canvas UI) follows once D1 lands. Phase E begins with the designer audit of the PDF viewer (E0) — that is orchestrator-tier work, queued after this swarm.
- [2026-08-25 orchestrator] Phase D note: the Klaus Workspace (K-102, shipped behind workspace_enabled) is the intended home for the embedding-map view — add it as a second stack view + sidebar entry rather than a new window.
- [2026-08-25 orchestrator] Correction: the Workspace was reverted same-day (see K-102). Phase D's map view home is TBD again — likely its own window, or a Library-window tab.

### K-057: I want to have some Obsidian-like features for the library panel. Specifically, I want all of the PDFs that we import into the library to be hosted in a directory that points to a specific directory, and then you should be able to choose that directory right away. The first time you open the Anki app, it forces you to choose a directory to host the library in, and then you can change what that directory is.  All the PDFs are in that directory. The way the directory is controlled, the way the folders are arranged, is the same as in the library as well. If something is in a certain folder type, then all the PDFs are also arranged in that folder type in the library and also in the tags. Does that make sense?
owner: -
created: 2026-08-24

#### Comments
- [2026-08-24 opus] Held for grooming: this changes the storage architecture (a user-chosen disk directory becomes the source of truth; drive.json tree and tags mirror it — today nothing on disk moves and folders are virtual). Needs a design pass covering migration of existing user_files/pdfs, bake_annotations paths, rename/move sync direction, and missing-directory behavior. Also file-overlaps K-055 (pdf_drive, tag_sync). Will groom and launch after this swarm lands.
- [2026-08-24 opus] Design pass done. Split: K-070 (Ready) is part A — storage root, path mapping, migration, setup step, Preferences row. Part B (disk<->tree mirroring, rename/move sync both directions, rescan on profile open, tag follow-through) gets filed once A lands, on pdf_drive/tag_sync/drive_store. This card stays as the umbrella.
- [2026-08-24 opus] Part B shipped as K-073 (two-way sync + single-copy). Umbrella is now functionally complete: root folder chosen at setup/Preferences, disk<->tree<->tags all mirror, one copy of every PDF living in the root. Remaining live verification rides Pouya's next restart.

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

### K-089: Add the highlight search results addon features to Klausmate
owner: -
created: 2026-08-24

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

### K-100: pdfjs parity: page-insert into editor field + crop integration
owner: -
priority: P3
tags: pdfjs
files: klausmate/web/pdfjs_viewer.html,klausmate/pdfjs_viewer.py,klausmate/__init__.py
created: 2026-08-25

Whatever the editor integration surface uses from the native viewer (page-as-image insert into the focused field, image-crop trigger) reproduced from the pdf.js canvases. Audit __init__.py call sites before scoping details.

#### Comments
- [2026-08-25 orchestrator] Scope addendum from the K-097..K-099 pass: (1) editor page-insert targeting (_set_target_field) still native-only; (2) PdfSidebar.reload_if_externally_changed full-reload branch does not re-feed the pdfjs webview (the common annotation-mirror branch DOES work via load_annotations); (3) persisted-marquee re-copy + drag-out; (4) exact-substring find highlighting. All small; none block daily pdfjs use.

### K-101: pdfjs cutover: flip default renderer after live soak, then retire QPdfView path
owner: -
priority: P3
tags: pdfjs,needs-human
files: klausmate/config.json,klausmate/pdf_viewer.py,klausmate/pdfjs_viewer.py
created: 2026-08-25

GATE: Pouya uses pdf_renderer:'pdfjs' daily until satisfied (no flicker, parity holds incl. bake round-trips). Then default flips to 'pdfjs'; native path stays one release as fallback; final card deletes the QPdfView machinery (KEEP: annotations JSON, bake, pdf_handler — renderer-independent).

## Ready

## Doing

## Review

## Done

### K-083: Text overlay clips/wraps: Helvetica + explicit lines + fit-to-width
owner: -
priority: P2
tags: bug,orchestrator
files: klausmate/pdf_viewer.py
verify: python3 -m py_compile klausmate/pdf_viewer.py
created: 2026-08-24

Live K-082 verification: mirror works (text positioned correctly, live),
but Klaus renders 'This is a test' as 'This is a' + a clipped second
line. Cause: overlay draws with Qt's default font at the record size,
word-wrapped and CLIPPED inside the annotation rect; Qt's default is
wider than Preview's Helvetica, so text that exactly fits Preview's box
wraps in Klaus and the overflow line is clipped away.

Fix in _paint_texts: Helvetica family (closer metrics); draw explicit
lines only (records preserve the user's Return presses as \n — Preview
never soft-wraps FreeText); fit-to-width: if the widest line exceeds the
box, shrink the pixel size proportionally (floor 6px); draw baselines
manually with no clip rect so nothing can vanish.

Paint-path only — no headless assertion possible; live check: the box
renders its full text on one line matching Preview.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). Paint-only: Helvetica family, explicit \n lines only (no soft re-wrap), fit-to-width shrink (floor 6px), manual baselines with no clip rect. Compile + 218/82 green (no paint assertions possible headless). Live check owed: 'This is a test' renders whole, one line, matching Preview.

### K-084: Highlight sync: native deletes propagate; tombstones stop over-blocking
owner: -
priority: P1
tags: bug,orchestrator
files: klausmate/pdf_handler.py,klausmate/pdf_viewer.py,tests/test_klausmate.py
verify: python3 tests/test_klausmate.py && python3 tests/test_drive.py
created: 2026-08-24

Pouya: text sync perfect; "sometimes when I highlight something on the
PDF or remove a highlight, it doesn't do the same thing in Anki."

Two design gaps found by audit:
1. NATIVE DELETES DON'T PROPAGATE: mirror never removes native records,
   so a Klaus-baked highlight deleted in Preview stays in Klaus and the
   next bake resurrects it in the file. Fix: bake reports exactly which
   native ids it wrote (baked_native_out param -> main-thread
   mark_native_baked -> baked_native_ids doc key, replaced wholesale per
   bake). Mirror removes a native record that IS in baked_native_ids
   but NOT among the file's marked ids — meaning the save that produced
   this file version knew Klaus marks and this one was deliberately
   deleted. CLOBBER GUARD: removal only when >=1 Klaus mark survived in
   the file — a stale Preview model (opened pre-bake) saves with ZERO
   Klaus marks and must read as clobber (re-bake restores), never as
   mass-deletion. Unbaked records (debounce window) are never touched.
2. TOMBSTONE OVER-SUPPRESSION: 30%-overlap matching blocks NEW
   highlights near a previously deleted one ("sometimes my highlight
   doesn't appear"). Fix: precision matching — a tombstone blocks only
   the RESURRECTION of the specific deleted mark (same kind/page, text
   equal for text, bbox within 3pt), never the location. Plus expiry:
   a successful mirror scan that no longer finds the stale copy prunes
   the tombstone.
Also: Preview sometimes defers writing to disk until focus loss — sync
can only fire when the file actually changes (document, not fix).

Verify (red-first): native-delete propagation (2 baked marks, file
rewritten without one -> record drops, other kept); zero-marks clobber
guard (both removed from file -> records KEPT); unbaked-record guard;
tombstone precision (4pt-shifted new highlight imports; identical copy
still blocked); tombstone expiry on clean scan.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). Native-delete propagation via baked_native_ids ledger (bake out-param, main-thread write) with three safety guards (unbaked window, zero-marks clobber, None scan); tombstone precision (3pt + text equality) + expiry on clean scan. Red-first x5; falsified removal branch (3 red). 225+82 green, AST clean. Live checks: delete a Klaus highlight in Preview (with >=2 Klaus marks in the file) -> disappears from Klaus ~1s; highlight new text near a previously deleted spot -> imports; rapid Klaus highlighting never loses records.

### K-085: Leftover highlights: satellite masking, bake resurrection race, sub-second sync
owner: -
priority: P1
tags: bug,orchestrator
files: klausmate/pdf_handler.py,klausmate/pdf_viewer.py,klausmate/pdf_drive.py,tests/test_klausmate.py
verify: python3 tests/test_klausmate.py && python3 tests/test_drive.py
created: 2026-08-24

Pouya: better, but "sometimes highlights left over when it's supposed to
be gone"; wants both directions effectively live.

Causes found:
1. SATELLITE MASKING (the likely "sometimes"): a native highlight WITH a
   note bakes as TWO annotations sharing the id — the /Highlight and a
   /Text sticky marked klausmate:<id>:note. Deleting the highlight in
   Preview leaves the sticky; scan's marked_ids stripped the suffix, so
   the id still read as present -> record kept -> next bake resurrects
   BOTH. Fix: marked_ids counts only PRIMARY marks (suffix-less /NM);
   orphaned satellites are dropped by the next bake automatically (not
   carried, not regenerated).
2. BAKE RESURRECTION RACE: a bake pending when Preview deletes a mark
   regenerates it from still-stale records; the post-bake fingerprint
   then masks the tick, so the mirror never sees the deletion. Fix: the
   bake itself applies the K-084 deletion rule (ledger + >=1-surviving-
   mark clobber guard) while scanning the working file for the carry:
   deleted-in-file natives are OMITTED from regeneration and reported;
   the viewer's post-bake main callback removes those records
   (remove_records), refreshes open overlays, THEN records the ledger.
3. FINGERPRINT RACE: _refresh_stats_for stat'ed the file at callback
   time — a Preview save landing between the bake's os.replace and the
   callback got recorded as "current" and never mirrored. The bake now
   reports the exact stat of the file it wrote; the callback stores
   that, so any later write mismatches and mirrors normally.
4. LATENCY: viewer bake debounce 1200 -> 500ms (Klaus->Preview),
   watcher debounce 700 -> 350ms (Preview->Klaus). Both directions land
   well under a second.
API: bake_annotations(report: dict) replaces baked_native_out (K-084
tests updated); report = {native_ids, omitted_native, stat}.

Verify (red-first): satellite exclusion (sticky present, highlight
stripped -> id NOT in marked_ids; mirror drops the record); bake
omission (report lists it, file regenerated without it, orphan sticky
gone); remove_records helper; report stat matches the written file.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). Bake-level resurrection guard (ledger + surviving-mark clobber rule, same as mirror), exact-stat fingerprint pinning, post-bake record removal + overlay refresh, primary-only marked_ids, debounces 500/350ms. Red-first; falsified guard -> bake writes the deleted highlight + sticky back (the exact live symptom). 234+82 green, AST clean. Live: delete a Klaus highlight in Preview right after making another edit in Klaus -> stays deleted; both directions land <1s.

### K-086: Ghost highlights on add: stale mirror applies discarded; tombstone TTL
owner: -
priority: P1
tags: bug,orchestrator
files: klausmate/pdf_handler.py,tests/test_klausmate.py
verify: python3 tests/test_klausmate.py && python3 tests/test_drive.py
created: 2026-08-24

Pouya: "Removal seems to do well, but sometimes when you add a
highlight, it's not removed" — strays appear around ADDS.

Causes:
1. OUT-OF-ORDER MIRROR APPLIES: every scan runs on its own thread
   (load path, tick path, multiple sidebars). Add a mark then change
   something quickly -> two scans in flight; if the OLDER scan's apply
   lands after the newer one, it re-imports a mark already gone from
   the file. Ghost record in Klaus, absent from the file, and no
   further tick corrects it (nothing changes on disk). Fix: scans are
   fingerprint-stamped (stat of the working file taken at scan time);
   mirror_foreign_annotations re-stats at apply time and DISCARDS a
   result whose fingerprint no longer matches — a fresher pass always
   follows via the tick machinery, which compares against fingerprints
   captured BEFORE scans start.
2. TOMBSTONE SWALLOWS RE-ADDS: re-highlighting the exact same text in
   Preview after deleting that mark in Klaus produces byte-identical
   quads — indistinguishable from stale-model resurrection, so the
   precision tombstone blocks it forever (and the next bake deletes it
   from the file behind the user's back). Resurrection risk is
   session-scoped; fix: tombstones carry ts and only match for 10
   minutes; aged/legacy entries expire on the next mirror prune.

Verify (red-first): scan result carries stat; stale apply discarded
(scan v1 with {A,B}, file moves to v2 {A}, apply v2 then v1 -> B NOT
re-imported); aged tombstone no longer blocks; fresh one still does.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). Fingerprint-stamped scans + apply-time discard (falsified: guard off resurrects the deleted mark); tombstone TTL 10min (identical re-adds import after the stale-model window; legacy entries age out). 239+82 green, AST clean. Live: rapid add/remove sequences in either app settle with no strays; re-highlighting the same text after a Klaus-side delete works once ~10min have passed (or immediately at a slightly different spot).

### K-087: Preview deletes of highlights must propagate: ledger self-seed, drop clobber guard, recovery bucket
owner: -
priority: P1
tags: bug,orchestrator
files: klausmate/pdf_handler.py,tests/test_klausmate.py
verify: python3 tests/test_klausmate.py && python3 tests/test_drive.py
created: 2026-08-24

Pouya: Preview->Klaus DELETE of highlights still doesn't propagate (the
other three directions work). Proven from live data: RCTs json has 2
native records, the PDF has ZERO annotations, ledger empty, json still
on the pre-K-084 schema.

Two blockers, both mine:
1. LEDGER NEVER SEEDED for marks baked before K-084 (it is written only
   by post-K-084 bakes) -> `rid in ledger` false -> removal impossible.
2. ZERO-MARKS CLOBBER GUARD (K-084): removal required >=1 surviving
   Klaus mark, to tell a deliberate delete-them-all from a stale-model
   Preview save. There is NO content discriminator between those two
   (verified by reasoning through the file states: both yield pristine
   + Preview's own marks), so the guard permanently blocked the
   single-highlight and delete-all cases — exactly what he keeps
   hitting.

Policy change (his explicit priority: deletes must propagate):
- Ledger self-seeds from OBSERVED primary marks on every mirror pass
  (heals legacy files going forward).
- Removal rule drops the surviving-mark requirement: ledger says baked
  + absent from a FRESH scan (K-086 fingerprint) -> remove. Same rule
  applied in the bake's omission branch.
- SAFETY NET replaces the guard: removed native records are kept in
  `removed_native` (record + ts, capped 50 / 24h) so a stale-model
  clobber is recoverable rather than silent data loss.
- LEGACY RECONCILIATION for files whose json predates the ledger (key
  absent): one-time, and ONLY when the working file's mtime is NEWER
  than the annotations json — i.e. the file reflects a later state than
  the records, so absent marks are real deletions and not a bake still
  pending. Fixes his current RCTs leftovers.

Verify (red-first): ledger self-seed; zero-marks delete propagates;
removed records land in the bucket; legacy reconciliation removes when
pdf newer; legacy KEEPS records when json newer (pending bake);
ledger drops removed ids; bake omits with zero marks present.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). Ledger self-seeds from observed marks + prunes to live records; clobber guard replaced by trust-the-delete plus removed_native recovery bucket (50 entries / 24h); one-time legacy reconciliation gated on pdf-newer-than-json; bake omission aligned. Falsified seed and legacy paths separately (seeding test strengthened after v1 passed via the legacy path). 253+82 green, AST clean. Live: his RCTs leftovers should clear on next tab load (pdf newer than json); delete-the-only-highlight in Preview now propagates.

### K-088: Toolbar order: Library sits between Add and Browse
owner: -
priority: P3
tags: ui,orchestrator
files: klausmate/pdf_drive.py,tests/test_drive.py
verify: python3 tests/test_drive.py
created: 2026-08-24

Pouya: top toolbar order must read Decks - Add - Library - Browse -
Stats - Sync. _on_toolbar_links currently does links.insert(0, ...),
putting Library leftmost.

Fix: insert BEFORE the Browse link, located by scanning the link list
rather than trusting a fixed index (Anki builds the list and addons can
add their own), with a fallback to third place = the same slot in the
stock layout.

Verify: red-first test in test_drive.py driving the real
_on_toolbar_links against a stock-shaped link list + a fake toolbar.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). Library inserted before the Browse link (located by scan, not a fixed index; falls back to third place). Red-first x3 including the shifted-list and no-Browse cases. 85+253 green.

### K-059: Single-window mode: tab shell + Browse as a tab
owner: orchestrator
priority: P2
tags: single-window,needs-live-verify
files: klausmate/single_window.py,klausmate/__init__.py,klausmate/manage_models.py,tests/test_single_window.py
verify: test -f klausmate/single_window.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_single_window.py
created: 2026-08-24
claimed: 2026-08-24

Pouya wants ONE window: pressing Browse switches to a Browse pane in the main
window instead of opening a separate window. This card builds the shell and the
Browse embed; AddCards/Library/Stats follow in later cards.

VERIFIED FACTS (26.8.1 app_packages bytecode, 2026-08-24 — do not re-derive):
- aqt.browser.browser.Browser is a QMainWindow with its own menubar
  (menuEdit, menu_Notes, menu_Cards, menuFlag, menuJump, menu_Help) including
  actionUndo / actionFind (Cmd-F) / actionSelectAll (Cmd-A) which COLLIDE with
  the main window's actionUndo/actionRedo once both live in one window.
- aqt.addcards.AddCards is also a QMainWindow (next card). Stats is a QDialog.
- Toolbar links are plain pycmds (decks/browse/stats); Browse routes to
  aqt.dialogs.open("Browser", mw). aqt.dialogs.register_dialog/open/markClosed
  are public and re-registering the creator is the sanctioned intercept point.

DESIGN (agreed):
1. Shell: hoist mw.toolbarWeb ABOVE a QStackedWidget so the existing top
   toolbar stays visible on every pane and acts as the tab bar (no new chrome —
   "feels like Anki"). Page 0 = the existing central content (web + bottomWeb).
   CRITICAL: detach the old central widget with setParent(None) BEFORE calling
   mw.setCentralWidget(container) — setCentralWidget DELETES the previous one.
   Fallback shell if Anki's fullscreen code fights the hoist: plain QTabWidget
   as central widget with toolbarWeb left inside the Decks tab.
2. Browse embed: re-register the "Browser" creator with a factory that
   (a) temporarily no-ops Browser.show during __init__ (Browser.__init__ calls
   self.show() — suppressing it avoids any window flash AND means we reparent
   before first show, sidestepping the Cocoa mid-gesture reparent trap),
   (b) setWindowFlags(Qt.WindowType.Widget), reparent into the stack,
   (c) menuBar().setNativeMenuBar(False) so Browser's menus render as an
   in-pane strip (native macOS menubar only serves top-level windows).
3. Shortcuts: preferred strategy — widget-scope BOTH action sets
   (setShortcutContext(WidgetWithChildrenShortcut) + pane_root.addAction(a) for
   every menubar action, mw's and Browser's) so Cmd-Z/Cmd-F/Cmd-A resolve by
   focus with zero ambiguity. Fallback: enable/disable arbiter on
   currentChanged — but it must survive Anki's update_undo_actions, which
   re-enables mw.form.actionUndo after every op. Ambiguous shortcuts are DEAD
   keys (see CLAUDE.md gotcha), so an unresolved collision is a shipped bug:
   enumerate both menubars' shortcuts at runtime and log any overlap.
4. Lifecycle: Browser stays alive across tab switches; pressing Browse again
   re-fronts the pane. Cmd-W / closeEvent still fires on a child widget —
   markClosed bookkeeping keeps working; on close, remove the pane and switch
   back to Decks. aqt.dialogs.closeAll (profile switch/quit) must still close it.
5. Config gate single_window_mode (default True) surfaced in Klausmate
   Preferences -> General. EVERY embed step wrapped in try/except that falls
   back to stock window behavior — a failure here must degrade to normal Anki,
   never a broken main window.

TESTING: headless can only cover the logic (factory registration, action
enumeration/scoping lists, config gate) via the aqt-stub pattern — the real
verification is live: restart Anki, press Browse, check Cmd-Z/Cmd-F/Cmd-A in
both panes, close with Cmd-W, switch profiles. Flag anything you cannot verify
headlessly on the card for Pouya's restart queue.

File overlap warning: K-056 (Add-panel PDF bar rework) also touches
__init__.py — serialize via the board, never run concurrently.

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (orchestrator, self-executed in 0be02b4). Shell = stack in mw.mainLayout (no setCentralWidget), Browse embedded via creator wrap + show-suppression + flag clear + in-pane menubar; collision arbitration widget-scopes both sides (falsified: disabling it reds the test); stock fallback proven headlessly. LIVE CHECKLIST (restart): 1) press Browse -> pane below the toolbar, no new window; Cmd-F/Cmd-A inside it, Cmd-Z both panes; Cmd-W closes back to Decks. 2) Add -> pane; type a note, Cmd-W -> unsaved-note prompt, Cancel keeps the pane. 3) Library link -> pane; retention rows refresh on entry. 4) Stats -> pane; its Close button retires it. 5) press Decks from any pane -> Decks fronts. 6) profile switch + quit clean. 7) tiling: half-screen tile the window with a pane open (the pane must not block small sizes). Toggle lives in Preferences -> General.

### K-060: Single-window mode: Add Cards as a tab
owner: orchestrator
priority: P2
tags: single-window,needs-live-verify
files: klausmate/single_window.py,tests/test_single_window.py
verify: grep -q 'AddCards' klausmate/single_window.py
created: 2026-08-24
claimed: 2026-08-24

Depends on the shell card (same file — serial). AddCards is a QMainWindow
(verified in 26.8.1 bytecode); embed it exactly like Browser: re-register the
"AddCards" creator, suppress show() during __init__, clear window flags,
reparent into the stack, setNativeMenuBar(False), widget-scope its actions.
AddCards' menubar is small so the collision audit is quick, but run it anyway.
Closing the Add pane must still run AddCards' unsaved-note guard
(closeWithCallback path) — do not bypass its closeEvent.

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (0be02b4). AddCards rides the pane registry; close-veto logic keeps the pane when the unsaved-note guard ignores the close (falsified red). Live: Add pane + veto check per K-059 checklist item 2.

### K-061: Single-window mode: Library opens as a tab
owner: orchestrator
priority: P2
tags: single-window,needs-live-verify
files: klausmate/pdf_drive.py,klausmate/single_window.py,klausmate/__init__.py
verify: grep -q 'single_window' klausmate/pdf_drive.py
created: 2026-08-24
claimed: 2026-08-24

Depends on the shell card. The Library window is ours (pdf_drive), so this
is the easy one: when single_window_mode is on, the top-toolbar Library link
switches to a Library pane in the stack instead of opening a separate window.
Keep the existing separate-window path intact for single_window_mode=False.
refresh_open_library() must keep working for the embedded pane (its
alive+visible guard should treat 'pane is current' as visible).

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (0be02b4). KlausDrive rides the registry (open_drive already routes через aqt.dialogs.open); _switch_to runs the pane's catch-up _refresh_rows since refresh_open_library's isVisible guard skips hidden panes (contract documented in pdf_drive). Live: checklist item 3.

### K-062: Single-window mode: Stats as a tab (follow-up)
owner: orchestrator
priority: P2
tags: single-window,needs-live-verify
files: klausmate/single_window.py
verify: grep -q 'Stats' klausmate/single_window.py
created: 2026-08-24
claimed: 2026-08-24

Optional follow-up once Browse/Add/Library tabs are proven live. Stats
(NewDeckStats) is a QDialog, not a QMainWindow — embedding a QDialog as a pane
also works (clear window flags) but its close/accept semantics differ; verify
aqt.dialogs bookkeeping still balances. Deck Options, Preferences, Import and
other genuinely modal dialogs STAY dialogs — single-window apps keep modals.

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (0be02b4). NewDeckStats (QDialog) rides the registry with a finished-signal hook — done() hides without a Close event, so the Close button retires the pane through the same drop path. Deck Options/Preferences/Import stay real dialogs. Live: checklist item 4.

### K-090: Single-window audit: dark webview panes, focus, bare-key leaks, macOS tiling minimum
owner: -
priority: P1
tags: bug,single-window,needs-live-verify
files: klausmate/single_window.py,tests/test_single_window.py
verify: python3 tests/test_single_window.py
created: 2026-08-24

Pouya post-restart: (1) Add pane shows a dark screen; (2) audit what
single-window mode broke; (3) macOS native tiling still not responding.

DIAGNOSES:
1. DARK PANE: QtWebEngine composites out-of-process; a view reparented
   BEFORE first show can miss its visibility transition and never
   attach a surface -> black rectangle. The editor webview is the
   largest in the app. Fix: one-time hide/show nudge of every
   AnkiWebView in a pane after it first becomes current (deferred one
   tick), flagged so it never re-runs.
2. AUDIT (full walk of top-level-window assumptions):
   a. FOCUS: activateWindow/raise_ are no-ops on child widgets — after
      a switch, keyboard focus stays on the previous pane. Fix: focus
      the pane (editor webview when present) on switch; mw.web when
      Decks fronts.
   b. BARE-KEY SHORTCUTS: mw's QShortcuts (a/b/t/s/d...) are
      window-scoped — with panes in the same window they now fire from
      inside Browse's card table etc. Fix: disable mw-owned QShortcuts
      (pane-descendant shortcuts excluded via parent-chain walk) while
      a pane is current; re-enable on Decks.
   c. GEOMETRY: pane closeEvents save child geometry into Anki's
      geom store — harmless while single-window is on; re-established
      by one manual resize if the mode is turned off. Documented, not
      coded around.
   d. WINDOW TITLES (Browser's card-count title) invisible — cosmetic,
      accepted.
   e. Verified unaffected: dialog manager bookkeeping incl. closeAll,
      AddCards unsaved-note veto, reopen routing, pane-parented
      dialogs (FindReplace/Previewer stay top-level), fullscreen (we
      never touch toolbarWeb), Escape-to-close.
3. TILING: stock main-window minimum (640x480 from main.ui) exceeds a
   MacBook's top/bottom tile height (~478pt) — macOS refuses tiles
   smaller than a window's minimum. Fix: explicit
   mw.setMinimumSize(400x300) at shell install (explicit minimum
   overrides layout hints); breadcrumb before/after minimums + window
   flags to /tmp/klausmate-debug.txt for live confirmation.

Verify: extended tests/test_single_window.py (nudge once-flag, focus
routing, shortcut disable/enable with pane-descendant exclusion,
min-size override recorded).

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (orchestrator). Webview hide/show nudge (once per pane, deferred), focus routing on switch/front, mw QShortcut gating with pane-descendant exclusion (falsified red), explicit 400x300 minimum for macOS tiling + breadcrumbs. 253+85+20 green, AST clean. LIVE: restart -> Add pane must render; type immediately (focus in first field); press 'a' inside Browse's table (must NOT open Add); tile the window top/bottom on the MacBook screen; if tiling still refuses, /tmp/klausmate-debug.txt now records the minimum-size numbers.

### K-091: Dark Add pane round 2: force Chromium page visibility, instrument pane state
owner: -
priority: P1
tags: bug,single-window,needs-live-verify
files: klausmate/single_window.py,tests/test_single_window.py
verify: python3 tests/test_single_window.py
created: 2026-08-24

K-090 live result: tiling FIXED; Add pane still dark. Breadcrumbs prove
the hide/show nudge RAN on AddCards (23:39:46) — widget-level cycling is
insufficient. Chromium tracks page visibility/occlusion separately from
the Qt widget: a page whose view was born hidden can stay
render-suspended after the widget shows.

Round 2, layered and instrumented:
- page().setVisible(True) + guarded setLifecycleState(Active) — drives
  Chromium's own visibility, the state widget hide/show never touched;
- size wiggle (h-1 then back) so the compositor must produce a frame;
- nudge now runs on EVERY switch to a pane plus a second pass 400ms
  after (the 0ms pass may predate surface creation), once-flag dropped;
- breadcrumbs record per-view page lifecycle state and url plus the
  PANE's size — if the pane itself is 0x0 the bug is layout, not
  compositing, and the next round pivots accordingly.

Verify: python3 tests/test_single_window.py (nudge test updated to
every-call semantics with page/size-capable stubs).

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (orchestrator). Page-level visibility forcing + lifecycle thaw + size wiggle, every-switch + 400ms second pass, rich per-view breadcrumbs (lifecycle state, sizes, url, pane size). 253+85+21 green, AST clean. LIVE: restart, open Add; if still dark, /tmp/klausmate-debug.txt now tells us whether the page is Frozen/Discarded, the view is 0-sized, or the PANE itself is 0x0 — three different round-3 pivots.

### K-092: Dark panes round 3: rebind webview delegates, pixel-evidence driven
owner: -
priority: P1
tags: bug,single-window,needs-live-verify
files: klausmate/single_window.py,tests/test_single_window.py
verify: python3 tests/test_single_window.py
created: 2026-08-24

Round 3 of the dark panes. Live evidence: BOTH Add and Browse render
all native widgets; ONLY the webviews are black, correctly laid out.
K-091 breadcrumbs show LifecycleState.Active, vis=True, correct sizes,
url loaded — Chromium believes the page is fine while painting
nothing. That is the render-delegate-bound-to-dead-window class: the
pane was born as a hidden top-level, the webview delegate bound to
that never-realized QWindow, and reparenting the PANE did not rebind
the delegate. Page-level pokes (K-091) cannot fix a delegate binding.

Fix: rebind by reparenting the VIEW itself once — hide, detach to
None, reinsert at the same slot (layout path preserves index+stretch;
QSplitter path preserves index+sizes), show. Driven by evidence:
_looks_black samples 9 pixels of wv.grab() (pure-black surface vs
night-mode grays are ~40x apart); heal runs 300ms after a pane becomes
current, retries up to 3x at 700ms, adds a 1px mw resize wiggle from
attempt 1, refocuses after rebinds, and breadcrumbs every verdict with
the sampled color — if grab() lies (renders content offscreen while
the screen stays black), the log will show 0/1 black and round 4 makes
the rebind unconditional instead.

Verify: python3 tests/test_single_window.py (black detection both
ways, layout rebind preserving index+stretch, splitter fallback
preserving sizes, heal dispatch on black-only).

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (orchestrator). Pixel-evidence heal loop: grab-sample -> rebind only actually-black views (layout slot+stretch preserved, splitter slot+sizes preserved) -> retry x3 with mw wiggle -> refocus; every verdict breadcrumbed with sampled colors so a grab() false-negative is visible. 253+85+25 green, AST clean. LIVE: restart, open Add and Browse — webviews should self-heal within ~1s of first switch; if still black, the debug file now proves whether grab lied (0-black verdicts) and round 4 goes unconditional-rebind.

### K-093: Dark panes round 4: unconditional embed-time webview rebind (grab lies about the screen)
owner: -
priority: P1
tags: bug,single-window,needs-live-verify
files: klausmate/single_window.py,tests/test_single_window.py
verify: python3 tests/test_single_window.py
created: 2026-08-24

Round 4. K-092's breadcrumbs are decisive: heal verdicts read
black=False sum=6795 mid=(245,245,245) while the SCREEN shows black —
wv.grab() renders a perfect frame offscreen, so Chromium composites
the page correctly and the dead half is PRESENTATION: the delegate
still paints toward the backing store of the hidden window the pane
was born in. Pixel detection therefore can never trigger (grab lies
about the screen), and the K-092 rebind never fired.

Fix: rebind EVERY webview unconditionally at embed time — one tick
after the pane lands in the stack (its top-level is mw by then, and
first paint has not happened, so no flicker): hide, detach to None,
reinsert in the same slot (layout stretch / splitter sizes preserved
by the K-092 helper), show. Breadcrumb each rebind. The heal loop
stays as a harmless regression net.

Fallback recorded for round 5 if presentation still fails:
wv.setAttribute(WA_NativeWindow) to give the view its own backing
store (input/stacking quirks make it second choice).

Verify: python3 tests/test_single_window.py (_rebind_all_webviews
loops the K-092 rebind over findChildren).

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (orchestrator). Unconditional embed-time rebind (one tick after stack insert, pre-first-paint), per-view isolation, breadcrumb per rebind; K-092 loop kept as regression net; WA_NativeWindow recorded as round-5 fallback. 253+85+26 green, AST clean. LIVE: restart, open Add + Browse; debug file will show 'embed-rebind AddCards ... -> True' — if the screen is STILL black after a confirmed-True rebind, round 5 goes native-window.

### K-094: Dark panes round 5: WA_NativeWindow on embedded webviews
owner: -
priority: P1
tags: bug,single-window,needs-live-verify
files: klausmate/single_window.py,tests/test_single_window.py
verify: python3 tests/test_single_window.py
created: 2026-08-24

Round 5. K-093 breadcrumbs: embed-rebind AddCards -> True, offscreen
frame perfect (sum=6795), screen still black. Reparenting the view
does not rebuild the presentation path on Qt 6.9/macOS — the delegate
keeps presenting through the top-level backing store route that never
worked for these panes.

Fix: WA_NativeWindow on every embedded webview at embed time, plus
winId() to force immediate native-handle creation — the view gets its
OWN NSView/backing store and presents directly, bypassing the broken
path. This is the standard cure for webengine-in-reparented-container
black screens; it was held back until now because native child
widgets can have stacking/input quirks (the editor webview has no
overlapping Qt siblings, so exposure is minimal). Replaces the
embed-time rebind loop (K-092's per-view rebind helper stays for the
heal net); test updated to assert attr+winId per view.

If THIS fails, the remaining option is architectural (construct panes
inside mw from the start) — noted, not expected.

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (orchestrator). WA_NativeWindow + winId() per embedded webview at embed time, per-view isolation, breadcrumbs. 253+85+26 green, AST clean. LIVE: restart, open Add/Browse — expect 'nativeized AddCards view winId=0x...' in the debug file and a rendering editor. If STILL black with a nonzero winId, the remaining path is architectural (construct panes inside mw) — flagged on the card.

### K-096: pdfjs foundation: vendored pdf.js viewer behind pdf_renderer flag
owner: orchestrator
priority: P1
tags: pdfjs
files: klausmate/pdfjs_viewer.py,klausmate/web/pdfjs_viewer.html,klausmate/web/pdfjs/pdf.min.js,klausmate/web/pdfjs/pdf.worker.min.js,klausmate/pdf_viewer.py,klausmate/config.json,klausmate/config.md,tests/test_pdfjs_viewer.py
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_pdfjs_viewer.py
created: 2026-08-25
claimed: 2026-08-25

Vendor pdf.js 3.11.174 (copy SynapsePro's bundled pdf.min.js + pdf.worker.min.js — no CDN, offline-safe). New web/pdfjs_viewer.html: continuous-scroll canvas rendering with text layer (native browser selection), fit-width zoom + controls, theme.py tokens injected as CSS variables (__THEME_VARS__ substitution). New pdfjs_viewer.py: PdfJsViewer(QWidget) hosting AnkiWebView; load_path() reads via pdf_handler.pdf_path_for, base64-chunks into window globals (SynapsePro's feed, ~8MB eval chunks, size guard); bridge via set_bridge_command for page-changed → _page_label. Stubs satisfying PdfSidebar surface. config.json gains pdf_renderer:'native' (docs in config.md); PdfSidebar branches on the flag. ACCEPTANCE: flag off → zero behavior change (all existing tests green); flag on → PDF renders, scrolls, zooms, page indicator tracks; test_pdfjs_viewer.py covers flag resolution, chunking math, HTML placeholders present, theme var injection.

#### Comments
- [2026-08-25 orchestrator] Shipped. Vendored pdf.js 3.11.174 (copied from SynapsePro's bundle), web/pdfjs_viewer.html (sized-placeholder + IntersectionObserver lazy render + text layer; theme.css_vars injected), pdfjs_viewer.py host (AnkiWebView, chunked-base64 feed, bridge -> page label), PdfSidebar branches on pdf_renderer (default native — zero behavior change verified, full suite green). Browser-harness verified: chunk feed -> open -> fit-width -> canvas+text render -> page tracking -> bridge posts. HARNESS CAUGHT A REAL BUG: layout-before-width rendered everything at the 0.25 scale floor; fixed with availWidth() rAF wait + ResizeObserver refit (userZoomed suspends refit). NEEDS-LIVE-VERIFY: set pdf_renderer:'pdfjs' in meta.json config, restart Anki, open a PDF — scroll smoothness is the whole point; IO/scroll-event delivery could not be exercised in the hidden harness pane (background throttling).

### K-097: pdfjs parity: selection + clipboard (copy text, copy page/marquee as image)
owner: orchestrator
priority: P2
tags: pdfjs
files: klausmate/web/pdfjs_viewer.html,klausmate/pdfjs_viewer.py
created: 2026-08-25
claimed: 2026-08-25

Text-layer selection already native; add: right-click menu (Copy page text / Copy slide as image), Cmd/Ctrl-double-click page → image to clipboard (canvas.toDataURL → Python QImage), Option/Alt-drag marquee → region image. Match native viewer's silent Preview-style copy (tooltips only for capture actions).

#### Comments
- [2026-08-25 orchestrator] Shipped with K-098/K-099 in one pass (shared files). Text selection is the pdf.js text layer (native browser selection; dbl/triple-click word/paragraph free). Custom context menu (theme-styled): Copy / Copy selection as image / Highlight over a selection; Copy page text / Copy slide as image always. Cmd-C copy = webview default. Option/Alt-drag marquee copies the region on release (offscreen 2x-quality crop -> PNG -> bridge -> QImage clipboard, tooltip per capture convention; text copies silent). DEFERRED: persisted-marquee re-copy + drag-out of the marquee image. Browser-harness verified end-to-end incl. decoding a real payload through the Python pipeline.

### K-098: pdfjs parity: highlights, sticky notes, outside text
owner: orchestrator
priority: P2
tags: pdfjs
files: klausmate/web/pdfjs_viewer.html,klausmate/pdfjs_viewer.py
created: 2026-08-25
claimed: 2026-08-25

Render the EXISTING annotations JSON (page-point rects) as positioned divs over the text layer; create highlight from selection; delete; notes as anchored boxes; K-078 adopted outside text with zoom-scaled font. Bake pipeline (pdf_handler.bake_annotations) consumes the same JSON — zero changes there. Coordinate mapping: pdf.js viewport.convertToViewportRectangle vs our y-flip convention — write the round-trip test FIRST.

#### Comments
- [2026-08-25 orchestrator] Shipped. Highlights/notes/outside-text render from the SAME records (0-based page, top-left page-point rects; CSS px = pts x scale — no coordinate fork): hlLayer under the text layer, note anchors (click -> Python QInputDialog), text-kind boxes with zoom-scaled fonts. Mutations go over the bridge (hl-add/hl-remove/note-edit); Python is the single writer — pdf_handler.save_annotations + the native viewer's 500ms debounced bake (thread), K-081 external-delete tombstones preserved via add_suppressed. Cmd+Shift+H/A create from selection. Harness-verified: records render pixel-plausibly, hit-testing drives the menu (Edit Note/Remove over a highlight), real selection payload -> valid record.

### K-099: pdfjs parity: find bar, go-to-page, thumbnails
owner: orchestrator
priority: P2
tags: pdfjs
files: klausmate/web/pdfjs_viewer.html,klausmate/pdfjs_viewer.py
created: 2026-08-25
claimed: 2026-08-25

In-page find via pdf.js text content (match count, Enter/Shift+Enter cycling, Esc — same shortcuts the native bar claims via ShortcutOverride), Cmd+Option+G go-to-page, thumbnail strip (lazy page renders at ~140px, click to jump) behind the existing ◫ toggle.

#### Comments
- [2026-08-25 orchestrator] Shipped. Find bar in-page (Cmd-F, 250ms debounce, n/m count, Enter/Shift+Enter + Cmd-G/Cmd-Shift-G cycling, Esc): search runs over cached getTextContent of ALL pages (unrendered included), navigation renders the page then rings the owning text span — item-level highlight, not exact substring (noted gap vs QPdfSearchModel's all-match paint). Go to page: Cmd-Option-G or click the page label -> Python getInt dialog. Thumbnails: in-page strip behind the existing header toggle, lazy 140px renders via IntersectionObserver, click-jump, current-page ring. Zoom Cmd+/-/0 (0 = refit; manual zoom suspends the ResizeObserver refit). Scroll position reported over the bridge (300ms debounce) and restored on ready.

### K-102: Klaus Workspace shell: sidebar + stacked views hosting the Library, behind workspace_enabled
owner: orchestrator
priority: P1
tags: workspace
files: klausmate/workspace.py,klausmate/pdf_drive.py,klausmate/theme.py,klausmate/config.json,tests/test_workspace.py
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_workspace.py
created: 2026-08-25
claimed: 2026-08-25

Approved plan (~/.claude/plans/tell-me-your-opinion-majestic-tiger.md): one window for KLAUS-OWNED surfaces only — the K-059 embedding of Anki windows stays dead (K-090..K-094 evidence); Anki windows get LAUNCHER buttons (mw.moveToState('deckBrowser'), aqt.dialogs.open AddCards/Browser, mw.onStats, mw.on_sync_button_clicked — verified against 26.8.1 bytecode). WorkspaceWindow(QWidget): sidebar rail (theme.workspace_qss) + QStackedWidget; view 0 = DriveWindow(hosted=True) — hosted skips _restore_geometry/show/raise/title, keeps _instance invariant so refresh_open_library/rescan reach it. _create() branches on workspace_from_config(cfg) (default OFF; flag off = byte-identical to today). Same DIALOG_NAME so profile_will_close/aboutToQuit teardown is shared. ACCEPTANCE: verify fails before/passes after; whole suite green; flag-off path untouched (existing tests prove).

#### Comments
- [2026-08-25 orchestrator] Shipped per the approved plan. workspace.py: WorkspaceWindow (sidebar rail themed by new theme.workspace_qss, QStackedWidget), view 0 = DriveWindow(hosted=True); hosted mode skips window chrome/geometry/show but keeps splitter persistence (MERGED into drive.json, not clobbered) and the _instance invariant. Launchers verified against 26.8.1 bytecode (moveToState/AddCards/Browser/onStats/on_sync_button_clicked). pdf_drive._create branches on workspace_from_config (strict opt-in: only workspace_enabled=True); Workspace closeEvent runs library.shutdown() + markClosed; _close_drive closes whichever window exists. drive_store window state grew an optional key= (workspace_window whitelisted in load() — the silent-key-drop trap was caught and pinned by test). 31-check tests/test_workspace.py green; full suite + symlink compile green. NEEDS-LIVE-VERIFY: flag on -> toolbar Library opens Workspace; checklist on the card body.
- [2026-08-25 orchestrator] REVERTED (with K-103) per Pouya before any release: 'the unified klaus workspace thing is garbage' — the real ask was a full-width custom TOP BAR on Anki's main window, not another window. workspace.py + test deleted; pdf_drive/_create, drive_store key= API, Preferences checkbox, config key all reverted (workspace_enabled scrubbed via _LEGACY_KEYS_DROPPED). shutdown() extraction kept (better structure). Successor: K-104 top-bar restyle.

### K-103: Klaus Workspace: Preferences toggle + docs
owner: orchestrator
priority: P2
tags: workspace
files: klausmate/manage_models.py,klausmate/config.md,CLAUDE.md
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_dialog_logic.py
created: 2026-08-25
claimed: 2026-08-25

General-section checkbox 'Unified Klaus Workspace…' following the deferred-save recipe EXACTLY (widget + mark_dirty signal + save_general line — pdf_renderer shipped broken by skipping the signal). config.md entry (toggle + Save + restart). CLAUDE.md: workspace.py module-map entry; amend Deleted note — embedding stays deleted, Workspace is the sanctioned successor. Comment on K-058: Phase D map view targets the Workspace.

#### Comments
- [2026-08-25 orchestrator] Shipped with K-102. Preferences -> General checkbox with ALL FOUR recipe legs (widget, setChecked via workspace_from_config, save_general line, mark_dirty toggled signal — the pdf_renderer lesson). config.md + CLAUDE.md updated: workspace.py module-map entry; Deleted note amended — embedding Anki windows stays deleted, Workspace is the sanctioned successor.

### K-104: Klaus top bar: restyle Anki's top toolbar in place — full-width bar + star logo
owner: orchestrator
priority: P1
tags: workspace,ui
files: klausmate/top_bar.py,klausmate/theme.py,klausmate/__init__.py,tests/test_top_bar.py
verify: env QT_QPA_PLATFORM=offscreen python3 tests/test_top_bar.py
created: 2026-08-25
claimed: 2026-08-25

Approved plan: SynapsePro's mechanism (webview_will_set_content on TopToolbar context -> theme.toolbar_css into head) + top_toolbar_will_set_left_tray_content prepending the hand-drawn star SVG (inline, --klaus-accent var, pycmd('decks') on click — command verified in 26.8.1 bytecode). RESTYLE ONLY: no element hidden/replaced, so Anki's links, Klaus's Library link, and AnkiHub's items keep working and inherit the .hitem pill look. ACCEPTANCE: verify green (18 checks incl. logo-lands-first with other addons' tray items untouched); browser-preview screenshots confirm light+dark full-width bar, star hard left, AnkiHub styled to match. NEEDS-LIVE-VERIFY: restart, both themes, all links, sync spinner.

#### Comments
- [2026-08-25 orchestrator] Shipped. Preview screenshots (browser harness reproducing Anki's exact .header/left-tray/hitem structure): light = white edge-to-edge strip, hairline border, star hard left, centered muted pill links, AnkiHub matching; dark = surface #2C2C2C with bright-accent star. Full suite (10 files) green; symlink compile ok.
- [2026-08-25 orchestrator] Live-feedback fixes (Pouya screenshot): (1) TWO LAYERS — Anki's body.fancy paints .toolbar as an elevated card (canvas-elevated bg, rounded bottom corners, box-shadow, backdrop blur) and every .hitem as a glass button; that inner card was the second layer. Flattened with !important (Anki's body.fancy:not(.flat) .hitem = specificity 0,3,1 outranks any class-level rule an addon can write), plus body.fancy margin-bottom:0 so the bar sits flush. (2) LOGO NOT CENTRED — Anki's .header uses align-items:start and .left-tray/.right-tray align-self:start; overridden to center, .tray-item made flex-centred. Anki's 3-column grid layout is left intact — paint and alignment only. Verified in a harness loading Anki's REAL _aqt/data/web/css/toolbar.css with body.fancy: computed .toolbar background rgba(0,0,0,0), box-shadow none, radius 0px, backdrop none; logo centre Y - header centre Y = 0px exactly; 44px bar. Screenshots confirm one flat strip in light and dark. Tests 18 -> 27 checks pinning the flatteners and the centring.
- [2026-08-25 orchestrator] Dark-mode follow fixed. The bar froze on whatever theme was active when the toolbar last drew: toolbar_css baked a night_mode() snapshot, but Anki's theme switch never re-runs webview_will_set_content — aqt/webview.py's on_theme_did_change only runs JS on the live document (documentElement.classList.add('night-mode'); body.add('night_mode'/'nightMode')). Fix: toolbar_css() now takes NO night arg and ships both palettes as --klaus-* custom properties keyed :root (light) and :root.night-mode/body.night_mode/body.nightMode (dark) — the same pattern Anki's own toolbar.css uses; every rule references vars, so a stray baked hex is now a test failure. Verified in a harness running Anki's REAL toolbar.css plus its verbatim theme JS: light bar #FFFFFF/link #86868B/star #007AFF -> dark #2C2C2C/#AAAAAA/#4FACFE, and reversible; dark screenshot confirms. Tests 27 -> 32 checks.
- [2026-08-25 orchestrator] Dark bar now reads as chrome. Root cause: the bar used the token, which in DARK is #2C2C2C — byte-identical to Anki's own dark --canvas, so the bar dissolved into the page (light mode never showed it: #FFFFFF over #f5f5f5 separates). Added a semantic token to BOTH palettes (key-set invariant held): LIGHT #FFFFFF (brighter than canvas, unchanged look), DARK #232323 (a step darker than #2c2c2c). Direction differs per theme on purpose — chrome must SEPARATE from content, not match a fixed relationship. Tests pin the rule itself via luminance comparisons against Anki's real canvas values, plus 'dark chrome != surface'. Screenshot over a real Anki-dark canvas confirms. NOTE: found a concurrent edit to theme.py adding a second, conflicting pair of chrome keys (#EDEDED/#232323) — duplicate dict keys silently drop the earlier one; collapsed to one per palette.
- [2026-08-25 orchestrator] Correction to the previous comment (two words were lost to shell backtick expansion): it should read "the bar used the SURFACE token" and "Added a semantic CHROME token to both palettes".
- [2026-08-25 orchestrator] Seamless-with-title-bar pass (Pouya: "integrated into the top bar of macOS... no lines, same exact color, same for windows"). (1) LINES: header border-bottom is now none !important, which also suppresses Anki own body:not(.fancy) .header hairline in minimalist mode. (2) COLOUR: hardcoding cannot match system chrome across OS/version/appearance, so native_chrome_color() reads mw.palette() Window role at runtime and pushes it as --klaus-chrome. Pushed twice: baked into the first paint (no flash of the token shade) and re-pushed from our OWN theme_did_change hook via QTimer.singleShot(0) so Qt has already updated its palette. Falls back to the chrome token whenever Qt is unavailable. Deliberately NOT touching NSWindow/DWM native window internals (option offered and declined) - that is the class of fiddling that killed single-window mode twice. Tests 35 -> 45 checks incl. JSON-escaping of the injected colour. NEEDS-LIVE-VERIFY: seam gone in both themes, both platforms.
- [2026-08-25 orchestrator] Logo updated to Pouya second sketch (2026-08-25): the star is now a POINT-DOWN pentagram — two peaks along the top, a point out each side, one long point at the bottom — replacing the point-up shape. Vertices were traced in the sketch own pixel space and normalised into the 26x26 viewBox, so the proportions are the drawing rather than an idealised star; the tilt and uneven vertices are preserved. Still one continuous self-crossing stroke, still strokes var(--klaus-accent) so it recolours with the theme. Previewed side by side against the old mark at 220px and inside the real bar at 26px in both themes.
- [2026-08-25 orchestrator] Frosted bar + custom background shipped (supersedes the native-colour chase). ROOT CAUSE of the light-bar-in-dark-mode regression: the first-paint override set --klaus-chrome on BOTH the light and dark selectors at once, pinning both themes to one draw-time snapshot, and theme_did_change never fires at startup so it could not self-correct. Removed. New background.py: resolve/main_css/bar_css, all aqt-free. The bar paints a BLURRED COPY of the same background rather than backdrop-filter (the toolbar is its own webview; nothing behind it composites in) - over a photo that is frosted glass, over a flat colour the blur is a no-op so the bar IS that colour and the seam is gone by construction (verified: bar and content both rgb(30,34,37), 0px border). Tint raised to 0.55 + full-contrast link text after the first preview showed links washing out over a bright photo. Images copied into user_files/backgrounds and served by a widened setWebExports pattern (verified it still blocks meta.json and other user_files). Star logo now opens Klaus Preferences. Settings gained an Appearance card (mode/colour/image/fit/blur) on the deferred-save recipe, applying live via top_bar.refresh(). 47 + 31 checks. K-105 files the remaining SynapsePro CardFrame layout refactor.
- [2026-08-25 orchestrator] Live crash on opening Preferences fixed: NameError "cannot access free variable ui_state" from sync_background_widgets. The Appearance block runs its initial sync at dialog-BUILD time, before the ui_state assignment further down manage_models_dialog — a closure free variable binds at call time, so the reference blew up the moment the dialog opened. The block is now self-contained on its own _bg_state["syncing"] flag (handlers included); zero ui_state references in it, asserted. Why tests missed it: test_dialog_logic transcribes the embed/threshold state machines, and test_imports only imports the module — nothing EXECUTES manage_models_dialog headlessly (Qt widgets cannot be constructed under the stub). New pins: the dangerous ordering itself (sync call precedes ui_state assignment), the block never touching ui_state, and the own-flag guard. 68 checks green.

### K-105: Preferences: adopt SynapsePro CardFrame layout (responsive grid of cards)
owner: orchestrator
priority: P2
tags: ui
files: klausmate/manage_models.py,klausmate/theme.py
created: 2026-08-25
claimed: 2026-08-25

Pouya: 'The Klausmate settings should look like Synapse Pro settings. Try to just copy that whole framework.' PARTLY DONE: theme.dialog_qss already renders QGroupBox sections as SynapsePro-style cards (surface fill, 12px radius, hairline border, blue-primary buttons) and Preferences uses them. REMAINING, from scripts/SynapsePro-main/settings_dialog.py: (a) QFrame#CardFrame + QLabel#SubHeaderLabel instead of QGroupBox titles; (b) the responsive layout — _install_grid_layout for wide dialogs vs _install_stack_layout for narrow, swapped at COMPACT_BREAKPOINT/TINY_BREAKPOINT via _replace_container_layout (note its careful re-parenting so cards survive the swap); (c) the info/support cards. Deferred deliberately: it is a layout refactor of a ~1500-line dialog whose deferred-save state machine is test-pinned, so it deserves its own card rather than riding along with the background feature.

#### Comments
- [2026-08-25 orchestrator] Shipped, with the KlausMate rename riding along (user-facing strings only — the lowercase package name is load-bearing: symlink, __package__, /_addons/klausmate/ URLs; live meta.json untouched, its cached addon-list name refreshes on reinstall; Tools menu is now "KlausMate Preferences…" with the dialog ellipsis). Layout transcribed from scripts/SynapsePro-main/settings_dialog.py: QTabWidget deleted; four sections became QFrame#CardFrame + SubHeaderLabel via a _card() helper whose (frame, layout) return reads exactly like the old QGroupBox sites, so every inner widget and the deferred-save state machine are byte-untouched. One ContentScrollArea page; 2-column grid >=720px, single stack below, swapped in resizeEvent via on_resize_cb; _replace_container_layout re-parents cards BEFORE QWidget().setLayout(old_layout) kills the old one (SynapsePro lesson). theme.dialog_qss grew the CardFrame/SubHeaderLabel/transparent-scroll rules. FOUND AND FIXED A TEST-SUITE HOLE: test_dialog_logic sys.exit sat mid-file, so the appearance-scoping pins added earlier (and anything appended since) were DEAD CODE that never ran; exit moved to the true end, and one pin was matching the def line instead of the call (substring). 78 checks now genuinely execute. NEEDS-LIVE-VERIFY: open Preferences wide (grid) and narrow (stack), confirm every control still saves.

### K-106: Preferences: SynapsePro sidebar-nav settings shell (K-106)
owner: builder
priority: P2
files: klausmate/manage_models.py,klausmate/theme.py,klausmate/top_bar.py,tests/test_dialog_logic.py,tests/test_theme.py,tests/test_top_bar.py
verify: grep -q SettingsSidebar klausmate/manage_models.py && python3 tests/test_dialog_logic.py
created: 2026-08-25
claimed: 2026-08-25

Rebuild KlausMate Preferences as SynapsePro's CURRENT (1.5.x) settings window, from Pouya's screenshot: left SettingsSidebar (star logo via top_bar.star_points(), app name + version, checkable NavItem pills), QStackedWidget pages (General / Appearance / Semantic Search / Local Models) each with PageTitle + PageSubtitle over one rounded CardFrame group of _row()s (SettingName + SettingDesc left, control right, RowSeparator hairlines), Cancel/Save under a full-width ButtonBarLine. Replaces the K-105 card grid outright. Deferred-save machinery untouched.

#### Comments
- [2026-08-25 builder] Done and verified. Shell: manage_models.py lost the K-105 grid machinery entirely (grep confirms no _install_grid_layout/_cards left); _page() builds each page + its NavItem pill, _finish_nav() sets display order (General, Appearance, Semantic Search, Local Models) decoupled from build order, _row() gives every simple setting the name/desc/control-right shape with RowSeparator hairlines. The API-key row hides WHOLE for Ollama (key_row + its separator — old code only hid label+field). Sidebar logo is a QPainter pixmap from top_bar.star_points(), a new pure helper parsing _STAR_PATH so toolbar SVG and Qt sidebar share one source of truth. theme.dialog_qss grew the ten shell ids, both palettes. Dead on_resize_cb hook stripped from _KlausManageDialog. Suite: 885 checks green (test_dialog_logic 80, test_theme 65, test_top_bar 50); full addon compiles through the symlink. Live verify owed on restart: pill switching, key-row hide on Ollama, Save still writes every key.

### K-107: SynapsePro UI/UX audit: accent colour themes + widget polish (K-107)
owner: builder
priority: P2
files: klausmate/theme.py,klausmate/manage_models.py,klausmate/__init__.py,klausmate/config.json,klausmate/config.md,tests/test_theme.py,tests/test_dialog_logic.py
verify: grep -q COLOR_THEMES klausmate/theme.py && python3 tests/test_theme.py && python3 tests/test_dialog_logic.py
created: 2026-08-25
claimed: 2026-08-25

Full audit of Klaus UI against SynapsePro's UI/UX (their source + 1.5.x settings). Implemented: (1) SynapsePro's accent colour-theme system — theme.COLOR_THEMES with their six presets verbatim, set_active_theme/get_active_theme, blue_accent token, config key color_theme applied at profile open before any surface draws; every QSS builder routes through palette() so dialogs, Library, panels, top bar and pdf.js viewer all recolour for free. Appearance page gets a swatch-pill row (colours from COLOR_THEMES only), deferred-save, applied live on Save before the toolbar re-bake. (2) Widget polish: QProgressBar / QSlider / QListWidget were bare native Qt in the Preferences dialog — now themed (grey_light grooves, accent fills, rounded list rows). (3) Interaction polish: pointing-hand cursor on nav + accent pills, footer button renamed Close->Cancel per their wording. Skipped knowingly: their custom theme editor popup (presets suffice for now), info/support cards (not applicable).

#### Comments
- [2026-08-25 builder] Done and verified. Accent themes: theme.COLOR_THEMES ships SynapsePro's six presets verbatim (light+dark override sets, blue-family tokens ONLY — pinned so backgrounds/text can never fork per theme); palette() overlays the active theme, so all 12 builder call sites recolour with zero per-surface code. Applied at profile_did_open by __init__._apply_color_theme, registered BEFORE _migrate_config so the toolbar's first bake already carries it (ordering pinned). Appearance page: swatch pills render from COLOR_THEMES, deferred-save writes color_theme, save_all applies via set_active_theme BEFORE top_bar.refresh() and restyles the open dialog immediately. Widget polish: QProgressBar/QSlider/QListWidget themed in dialog_qss both palettes. Cursors on all pills; footer Close->Cancel. Suite green: test_theme 91, test_dialog_logic 93; test_theme resets to ocean after the overlay checks so later suites see the default. Live verify owed: pick Orchid, Save, watch dialog + top bar + Library recolour without restart.

### K-108: Accent swatches: squares + custom colour + community palettes; disabled-state fix; logo back (K-108)
owner: builder
priority: P2
files: klausmate/theme.py,klausmate/manage_models.py,klausmate/__init__.py,klausmate/top_bar.py,klausmate/config.json,klausmate/config.md,tests/test_theme.py,tests/test_dialog_logic.py,tests/test_top_bar.py
verify: grep -q color_theme_custom klausmate/config.json && python3 tests/test_theme.py && python3 tests/test_dialog_logic.py
created: 2026-08-25
claimed: 2026-08-25

Accent picker reworked per Pouya: names dropped — bare 22px colour squares (names in tooltips), wrapped 7 per row; last square is a custom colour that opens QColorDialog and derives the whole blue family from one hex (theme.custom_overrides, ratios read off SynapsePro's presets; bright lifts further in dark). Added community palettes as accent presets — nord, solarized, catppuccin, gruvbox, everforest, dracula (canonical published colours via _community_preset) — plus claude (#D97757 Anthropic terracotta). New config color_theme_custom; applied colour-before-name at profile open and in save_all. Fixed 'these three settings plainly don't work': disabled Appearance controls looked fully live because QPushButton#SecondaryButton (id) outranks QPushButton:disabled (pseudo-state) — dialog_qss now carries :disabled rules repeating every id, and Fit/Bar-blur rows disable whole so labels dim too. Star logo restored beside the wordmark (accent-stroked pixmap from top_bar.star_points(), repainted on accent save).

#### Comments
- [2026-08-25 builder] Done. Swatch grid: 14 squares (13 presets + custom) at 7/row; selection = white inner ring so it reads on pale swatches too. Custom: one hex derives hover (x0.90), pressed (x0.70), bright (lighten-toward-white, stronger in dark) — derived ocean tones land within a couple points of SynapsePro's hand-tuned ones (pinned). Cancelling the picker still selects the custom swatch with its held colour. Community presets carry canonical colours (nord frost #88C0D0, dracula #BD93F9, gruvbox #FE8019, catppuccin mocha #CBA6F7 as dark brights — pinned). Disabled-state root cause: id selector outranks pseudo-state, documented in theme.py + CLAUDE.md; rows now disable whole. Logo back as accent-stroked star, pen-width inset so the stroke can't clip, repainted after save_all's sheet swap. Suite: theme 124, dialog 100, top_bar 49, all green; full compile through symlink. Live verify owed: disabled Fit/Bar-blur grey out under 'Anki's own', custom picker round-trip, Claude preset on the top bar.

### K-109: Bottom toolbar = top bar chrome; translucent state veils; pill mush root fix (K-109)
owner: builder
priority: P2
files: klausmate/theme.py,klausmate/background.py,klausmate/top_bar.py,klausmate/manage_models.py,tests/test_top_bar.py,tests/test_background.py,tests/test_dialog_logic.py
verify: grep -q bottombar_css klausmate/theme.py && python3 tests/test_top_bar.py && python3 tests/test_background.py
created: 2026-08-25
claimed: 2026-08-25

Pouya: (1) sidebar pills still mushed on first open despite layout-spacing fix — root cause is broader: ANY QSS-derived sizeHint (fonts, padding) lands on re-polish, so pill heights are now fixed at 30px, macOS System Settings style. (2) Anki's bottom toolbar (deck browser Get Shared/Create Deck/Import, overview Study Now) now gets the SAME treatment as the top bar: theme.bottombar_css() ships both palettes keyed on Anki's night classes, chrome background, native <button>s flattened into the top bar's glass-chip language; injected in top_bar's webview_will_set_content for DeckBrowserBottomBar/OverviewBottomBar by class name (reviewer answer bar deliberately stock — colours carry scheduling meaning). background.bar_css(bottom=True) frosts the bottom bar off body (no .header class there) sampling the image's BOTTOM edge; colour mode paints html+body flat. (3) Hover/press highlights are now Apple-material translucent veils — rgba black over light chrome, rgba white over dark, with a stronger :active step — replacing the opaque hover_subtle fill, so highlights tint whatever background is behind the bar (flat colour, photo frost) instead of pasting a grey chip.

#### Comments
- [2026-08-25 builder] Done. Bottom bar verified against Anki's REAL assets (app bundle): buttons are native <button> in #header table, loading toolbar.css + toolbar-bottom.css; contexts DeckBrowserBottomBar/OverviewBottomBar confirmed via strings on the pycs, matched by class name to avoid importing aqt.deckbrowser/overview in the hook. bottombar_css flattens -webkit-appearance, transparent at rest, 8px radius chips, muted->full text on hover — the exact .hitem language. Veils: --klaus-hover rgba(0,0,0,.05)/rgba(255,255,255,.10), --klaus-press .09/.16, opaque hover_subtle banned from the sheet by pin. bar_css(bottom=True) hangs frost off body (bottom has no .header CLASS, only #header id) and samples center bottom; top output pinned byte-identical to pre-param. Pills: setFixedHeight(30) — the polish-timing class of bug can no longer touch geometry. Suites: top_bar 57, background 37, dialog 102, all green; full compile ok. Live verify owed: first-open sidebar spacing, bottom bar in all three modes (theme/colour/image), hover veil over a photo.

### K-110: theme.py design-scale audit: radii/font scale + install-page QSS ids
owner: worker-scale
priority: P2
files: klausmate/theme.py,tests/test_theme.py
verify: grep -q InstallHeading klausmate/theme.py && ! grep -q 'border-radius: 5px' klausmate/theme.py && python3 tests/test_theme.py && python3 tests/test_top_bar.py
created: 2026-08-25
claimed: 2026-08-25

UI-consistency audit finding: theme.py builders drifted off any shared scale (a 5px checkbox-indicator radius at ~line 518, a 10px radius at ~line 796, next to the sanctioned 6/8/12). ACCEPTANCE: (1) a 'Design scale' comment block above dialog_qss documents the sanctioned values — radii: 12 cards/containers, 8 buttons/inputs/chips/pills, 6 small controls (swatches, list items, checkbox indicators), 7 = slider-handle circle (height/2), 4/2 slim fills (progress, groove), 0 only as a deliberate flattener; font sizes: 10 micro, 11 captions, 12 subtitles, 13 body, 14 section headings, 18 wordmark, 24 page titles. (2) The 5px and 10px outliers move onto the scale — pick by the element's ROLE and say so in a comment. (3) dialog_qss gains QLabel#InstallHeading (14px/700, SubHeaderLabel-like) and QLabel#InstallSection (13px/600, margin-top 8px) — K-111 consumes these from manage_models. (4) tests/test_theme.py gains a section that SCANS every builder's emitted CSS and asserts every border-radius is in the sanctioned set and every font-size in the sanctioned set — it must fail if an off-scale value is ever added. (5) Chip/veil/chrome semantics are untouched: test_top_bar.py must stay green (its pins assert the shared chip blocks byte-identically).

#### Comments
- [2026-08-25 worker-scale] Design scale documented above dialog_qss (radii 12/8/6/7/4/2/0, font-sizes 10/11/12/13/14/18/24). Fixed 2 outliers: QCheckBox::indicator 5px->6px (small-control tier); drop_zone_qss square 10px->12px (container/card role, not a button). Added QLabel#InstallHeading (14px/700) + QLabel#InstallSection (13px/600, margin-top 8px) to dialog_qss for K-111. tests/test_theme.py gains a 'design scale' section that regex-scans emitted CSS of all 8 builders (dialog_qss, panel_header_qss, find_bar_qss, library_qss, thumb_strip_qss, drop_zone_qss, toolbar_css, bottombar_css) and asserts border-radius/font-size membership in the sanctioned sets -- verified it actually catches an off-scale value (5px) before landing the real fix. Chip/veil/chrome values in toolbar_css/bottombar_css untouched. Verify command: PASSED. Full suite: 11/11 files green (test_theme.py 158/158, test_top_bar.py 60/60).
- [2026-08-25 orchestrator] Reviewed: diff touches only theme.py + test_theme.py; gate re-run green by orchestrator (verify + test_top_bar chip pins intact); outliers fixed on-role (checkbox 6px small-control, drop-zone 12px container); scale doc + regex-scan enforcement in place. Signing off.

### K-111: Preferences install page onto the K-106 shell language
owner: worker-install
priority: P2
files: klausmate/manage_models.py,tests/test_dialog_logic.py
verify: sh -c '! grep -q "install_heading" klausmate/manage_models.py && grep -q "InstallSection" klausmate/manage_models.py && grep -q "install_title.setObjectName(\"PageTitle\")" klausmate/manage_models.py && python3 tests/test_dialog_logic.py'
created: 2026-08-25
claimed: 2026-08-25

Page 0 of the Preferences stack ('Set up local AI') predates the K-106 sidebar shell and hand-styles labels with literal setStyleSheet strings (install_heading 'font-weight: 600; font-size: 14px;', manual_lbl 'font-weight: 600; margin-top: 8px;'). ACCEPTANCE: (1) those literal setStyleSheet calls are GONE; the labels take objectNames InstallHeading / InstallSection (styled centrally by dialog_qss — K-110 adds the ids; if they are not in theme.py yet when you start, proceed anyway, the pairing lands when both cards do). (2) The page opens with a PageTitle + PageSubtitle pair matching every other page: title 'Set up local AI', muted subtitle = the current explanatory body copy, page margins (24, 18, 24, 8) like _page(). (3) Behaviour unchanged: buttons, install_status, stack switching (show_install_page / refresh) untouched; every existing test_dialog_logic pin stays green. (4) New pins in tests/test_dialog_logic.py: no literal font setStyleSheet on the install page; the install page carries PageTitle.

#### Comments
- [2026-08-25 worker-install] Restyled the install page (page 0) onto the K-106 shell language. Changes in klausmate/manage_models.py: page margins now (24, 18, 24, 8) like _page(); added a new title_lbl 'Set up local AI' (objectName PageTitle) as the first widget, and repurposed install_body (the existing explanatory copy) into the PageSubtitle right below it (still wordwrapped) -- this pair 'opens' the page per acceptance criteria. The pre-existing install_heading label ('Set up local AI', originally hand-styled) and manual_lbl ('Manual options') keep their text/position but lost their literal setStyleSheet calls in favor of objectNames InstallHeading / InstallSection, which K-110 already ships CSS for in theme.py (confirmed present: QLabel#InstallHeading and QLabel#InstallSection rules exist). No behaviour touched -- buttons, install_status, show_install_page()/refresh() stack switching all untouched. Added 3 checks to tests/test_dialog_logic.py under a new K-111 section (covers: no literal font-weight/font-size setStyleSheet left in the install-page source slice; PageTitle+PageSubtitle pair present with matching margins; InstallHeading/InstallSection objectNames applied). Verify command passed: sh -c '! grep -q "install_heading.setStyleSheet" ... && grep -q InstallHeading ... && python3 tests/test_dialog_logic.py' -> exit 0, 105 passed/0 failed. Full suite (11 test files) all green: background 37, board 68, dialog_logic 105, drive 85, imports 27, klausmate 253, pdfjs_viewer 76, projection 30, tag_migrate 121, theme 158, top_bar 60 -- all passed, 0 failed. Committed as 26ba9e9, touching only klausmate/manage_models.py and tests/test_dialog_logic.py.
- [2026-08-25 orchestrator] Reviewed: shell language adopted correctly, behaviour untouched, gate + full dialog suite green. One rework applied in review: the old 'Set up local AI' label had been KEPT as InstallHeading directly under the new PageTitle saying the same thing — title duplicated twice on the page. Removed the old label (its job passed to PageTitle), updated the pin, amended the card verify to match. Signing off.

### K-112: Theme the last unthemed dialogs: setup_flow + crop_dialog
owner: worker-dialogs
priority: P2
files: klausmate/setup_flow.py,klausmate/crop_dialog.py,tests/test_setup_crop_theme.py
verify: sh -c 'grep -q dialog_qss klausmate/setup_flow.py && grep -q dialog_qss klausmate/crop_dialog.py && python3 tests/test_setup_crop_theme.py'
created: 2026-08-25
claimed: 2026-08-25

UI-consistency audit finding: setup_flow.py (first-run Welcome + readiness prompts) and crop_dialog.py (image crop) are the last Klaus surfaces with NO theme styling — raw native Qt next to the themed Preferences/Library. ACCEPTANCE: (1) every QDialog these modules build applies theme.dialog_qss(theme.night_mode()) at construction, with the repo's guarded pattern (try/except, print('[klausmate] ...') on failure). (2) Button roles follow the dialog convention: primary action = default blue; secondary/cancel setObjectName('SecondaryButton'); destructive 'DangerButton'. (3) Muted/hint labels use theme.muted_label_qss, no literal style strings, no hardcoded hex. (4) User-visible window TITLES read 'KlausMate ...' casing where the addon name appears; do NOT rename the short product name 'Klaus' inside prose copy. (5) The crop dialog's rubber-band/crop behaviour is untouched — style only. (6) New tests/test_setup_crop_theme.py using the klaus-test bootstrap (sys.path.insert '.claude/skills/klaus-test/scripts'; anki_stubs install/check/section/report; install() BEFORE importing klausmate) pinning: both modules reference dialog_qss; SecondaryButton appears wherever a cancel exists; no literal hex colour in either module (regex '#[0-9A-Fa-f]{6}' outside comments).

#### Comments
- [2026-08-25 worker-dialogs] Themed the last two unstyled Klaus surfaces. setup_flow.py: added a _themed_message_box() helper applying theme.dialog_qss(theme.night_mode()) (guarded try/except + print('[klausmate] setup dialog theme failed: ...')) to all 5 QMessageBox sites (Welcome + the 4 readiness/warning prompts). Skip/Later/Install-manually buttons now setObjectName('SecondaryButton'); primary actions (Got it, Set up Klaus, KlausMate Preferences-as-default) keep default blue. Window titles that name the addon now read 'KlausMate: ...' (was 'Klaus: ...'); 'Welcome to Klaus' prose kept per the card's carve-out. crop_dialog.py: ImageCropDialog now applies dialog_qss at construction (same guarded pattern), Cancel button is SecondaryButton, the hint label ('Drag to select crop area' / size readout) uses theme.muted_label_qss. Rubber-band/resize/move state machine and encode_cropped save-as-new-file path untouched -- style only. No literal hex outside comments in either file (the one '#3a82f7' mention stays in its existing full-line comment). Added tests/test_setup_crop_theme.py (klaus-test bootstrap) with 22 checks: dialog_qss/night_mode references, guarded fallback pattern present, every Skip/Later button chained to SecondaryButton, zero hex-outside-comments, title-casing rule, and a crop-behaviour-untouched sanity check. Verify command passed: grep dialog_qss x2 + test file, exit 0. Full suite (13 files) run clean after my commit: 0 failures across background/board/browse_highlight/dialog_logic/drive/imports/klausmate/pdfjs_viewer/projection/setup_crop_theme/tag_migrate/theme/top_bar. Committed as f63c3c6, only klausmate/setup_flow.py, klausmate/crop_dialog.py, tests/test_setup_crop_theme.py staged.
- [2026-08-25 orchestrator] Reviewed: gate re-run green; diff touches only the three card files; dialog_qss applied via the house guarded pattern in both modules, SecondaryButton roles on all non-primary actions, muted_label_qss on hints, titles 'Klaus: ...' -> 'KlausMate: ...' with the 'Welcome to Klaus' prose carve-out respected; crop behaviour untouched. 22 new pins green. Signing off.

### K-113: Browse search-term highlighting (vendor Glutanimate addon as native feature)
owner: worker-highlight
priority: P2
files: klausmate/browse_highlight.py,klausmate/__init__.py,klausmate/config.json,klausmate/config.md,tests/test_browse_highlight.py
verify: python3 tests/test_browse_highlight.py
created: 2026-08-25
claimed: 2026-08-25

Integrate References/highlight-search-results-main (Glutanimate, AGPLv3) as a native Klaus feature: searching in Browse highlights the matched terms in the editor pane. NEW MODULE klausmate/browse_highlight.py. ACCEPTANCE: (1) SearchTokenizer + get_searchable_tokens adapted as PURE aqt-free code at module top (ANKI2124 dialect only — drop the 2100 branches and the enum); KEEP the AGPL attribution header from the source files with a line noting 'adapted for KlausMate' (the licence requires the header stay intact). (2) Highlighting = webview.findText(term) per term on browser.editor.web; clear with findText(''). (3) A setup() function registers hooks — gui_hooks.browser_did_change_row re-highlights the current row's editor; gui_hooks.browser_menus_did_init adds a checkable View-menu action 'Highlight Search Results' (create browser.menuView only if absent — copy their existence-check pattern); skip their select-next/select-all shortcuts entirely (out of scope). (4) Config: browse_highlight_default (bool, default true) added to klausmate/config.json and documented in config.md under Feature toggles; each Browser starts its toggle from it. (5) setup() wired in klausmate/__init__.py near the other gui_hooks registrations, guarded try/except like the rest of the bootstrap. Do NOT add a Preferences row — another card owns manage_models.py; config-only default this pass. (6) tests/test_browse_highlight.py with the klaus-test bootstrap: port the applicable tokenizer cases from References/highlight-search-results-main/tests/test_search.py, plus pins — module imports aqt-free at top; deck:/tag:/re:/nc: ignored; quoted phrases survive tokenizing; negated terms and AND/OR operators dropped; searchable extraction strips quotes/wildcards.

#### Comments
- [2026-08-25 worker-highlight] Implemented klausmate/browse_highlight.py: ported SearchTokenizer + get_searchable_tokens from References/highlight-search-results-main/src/highlight_search_results/search.py (ANKI2124 dialect only, enum and 2100 branches dropped), pure/aqt-free at module top. AGPL header kept intact from source (search.py/webview.py/browser.py share it) plus an 'Adapted for KlausMate' note. highlight_terms/clear_highlights ported from webview.py (webview.findText per term / findText('')). setup() registers gui_hooks.browser_did_change_row (re-highlight on row change) and gui_hooks.browser_menus_did_init (checkable View-menu 'Highlight Search Results', with the existence-check pattern for browser.menuView) — select-next/select-all shortcuts from upstream intentionally skipped. Per-Browser state stored as browser._klausmate_highlight_results (repo's attribute-guard convention). Added browse_highlight_default (true) to config.json + documented under config.md Feature toggles; each Browser toggle seeds from it via highlight_default(). Wired setup() into __init__.py as one guarded try/except block next to the other gui_hooks registrations (single Edit, matching deck_curate/pdf_drive/top_bar pattern exactly). No Preferences UI row added (out of scope, owned by another card). Created tests/test_browse_highlight.py (24 checks): ported upstream's _assert_common_tokenizations cases for 2124, plus pins for deck:/tag:/re:/nc: ignored, quoted phrases surviving tokenizing, AND/OR/'-'-marker operators dropped, and quote/wildcard stripping in get_searchable_tokens (also documents the upstream quirk that a negated word's text itself still passes through as searchable — only the '-' marker token is filtered, matching the real algorithm). Verify: python3 tests/test_browse_highlight.py -> 24 passed, 0 failed. Full suite (13 files): all green, including test_imports.py (browse_highlight imports cleanly, aqt-free) and test_klausmate.py (253 passed, __init__.py bootstrap intact). Files touched: klausmate/browse_highlight.py (new), klausmate/__init__.py, klausmate/config.json, klausmate/config.md, tests/test_browse_highlight.py (new). Committed as 1dbbeab.
- [2026-08-25 orchestrator] Reviewed: gate green (24/24), full suite + symlink compile green; AGPL header verbatim with adaptation note (licence honoured); pure tokenizer at module top per the background.py pattern; hooks guarded, wiring in __init__.py matches the neighbouring blocks exactly; toggle rides the _klausmate_* attribute convention; upstream shortcuts correctly skipped. Signing off.
