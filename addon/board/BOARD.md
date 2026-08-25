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
