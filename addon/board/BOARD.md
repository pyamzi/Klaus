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

## Ready

### K-061: Single-window mode: Library opens as a tab
owner: -
priority: P2
tags: single-window,needs-live-verify
files: klausmate/pdf_drive.py,klausmate/single_window.py,klausmate/__init__.py
verify: grep -q 'single_window' klausmate/pdf_drive.py
created: 2026-08-24

Depends on the shell card. The Library window is ours (pdf_drive), so this
is the easy one: when single_window_mode is on, the top-toolbar Library link
switches to a Library pane in the stack instead of opening a separate window.
Keep the existing separate-window path intact for single_window_mode=False.
refresh_open_library() must keep working for the embedded pane (its
alive+visible guard should treat 'pane is current' as visible).

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (0be02b4). KlausDrive rides the registry (open_drive already routes через aqt.dialogs.open); _switch_to runs the pane's catch-up _refresh_rows since refresh_open_library's isVisible guard skips hidden panes (contract documented in pdf_drive). Live: checklist item 3.

### K-062: Single-window mode: Stats as a tab (follow-up)
owner: -
priority: P2
tags: single-window,needs-live-verify
files: klausmate/single_window.py
verify: grep -q 'Stats' klausmate/single_window.py
created: 2026-08-24

Optional follow-up once Browse/Add/Library tabs are proven live. Stats
(NewDeckStats) is a QDialog, not a QMainWindow — embedding a QDialog as a pane
also works (clear window flags) but its close/accept semantics differ; verify
aqt.dialogs bookkeeping still balances. Deck Options, Preferences, Import and
other genuinely modal dialogs STAY dialogs — single-window apps keep modals.

#### Comments
- [2026-08-24 orchestrator] Signed off pending live verification (0be02b4). NewDeckStats (QDialog) rides the registry with a finished-signal hook — done() hides without a Close event, so the Close button retires the pane through the same drop path. Deck Options/Preferences/Import stay real dialogs. Live: checklist item 4.

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
