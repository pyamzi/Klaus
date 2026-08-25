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

### K-059: Single-window mode: tab shell + Browse as a tab
owner: -
priority: P2
tags: single-window,needs-live-verify
files: klausmate/single_window.py,klausmate/__init__.py,klausmate/manage_models.py,tests/test_single_window.py
verify: test -f klausmate/single_window.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_single_window.py
created: 2026-08-24

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

### K-060: Single-window mode: Add Cards as a tab
owner: -
priority: P2
tags: single-window,needs-live-verify
files: klausmate/single_window.py,tests/test_single_window.py
verify: grep -q 'AddCards' klausmate/single_window.py
created: 2026-08-24

Depends on the shell card (same file — serial). AddCards is a QMainWindow
(verified in 26.8.1 bytecode); embed it exactly like Browser: re-register the
"AddCards" creator, suppress show() during __init__, clear window flags,
reparent into the stack, setNativeMenuBar(False), widget-scope its actions.
AddCards' menubar is small so the collision audit is quick, but run it anyway.
Closing the Add pane must still run AddCards' unsaved-note guard
(closeWithCallback path) — do not bypass its closeEvent.

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

## Ready

## Doing

## Review

## Done

### K-081: Adoption audit: typing-drift doubling, self-heal, delete tombstones
owner: -
priority: P1
tags: bug,orchestrator
files: klausmate/pdf_handler.py,klausmate/pdf_viewer.py,tests/test_klausmate.py
verify: python3 tests/test_klausmate.py && python3 tests/test_drive.py
created: 2026-08-24

Full audit of the outside-annotation adoption system after live doubling
(screenshot: 'This is more' rendered twice, offset). Confirmed in the live
records: TWO generations of ONE Preview text box adopted as separate
records ('This is more text' @42.5,211.6 and '...for the output'
@45.8,215.6, overlapping). Preview AUTOSAVES while typing; every save
ticks the watcher; each snapshot has different text + drifted rect, so
exact-signature dedup treats it as a new annotation.

Audit findings (this card fixes 1-3):
1. TYPING DRIFT DOUBLING (live, confirmed): adoption must recognize "same
   spot on same page, same kind, external" as the SAME annotation being
   edited -> UPDATE in place (rects/text/color/size), not append.
   Side benefit: Preview edits of adopted marks now propagate instead of
   duplicating - softens the one-way valve.
2. NO SELF-HEAL: existing duplicated records (Pouya's file has them NOW)
   are never collapsed - adoption only ran when scan found foreign marks.
   Fix: adopt always runs a collapse pass over external records
   (overlapping same-kind same-page externals -> keep newest), and the
   viewer calls apply even with an empty scan.
3. ZOMBIE DELETES: Remove Text/Highlight on an adopted record while the
   unmarked original is still in the file (bake pending, or Preview
   re-saving its stale model) -> next scan re-adopts it. Fix: tombstones
   (suppressed_external in the annotations json, bbox+kind+page match);
   save_annotations must preserve unknown top-level keys (today it DROPS
   them - found in audit).
Known hazards documented, not fixed here: (a) while Preview holds the
file open, its saves rewrite Klaus's bakes with its stale model - Klaus
re-bakes from json, self-healing but churny; (b) each Preview autosave
reloads the open tab (~1s flicker while typing externally).

Verify: red-first tests recreating live doubling (drift adopt -> 1 record
updated, not 2), heal pass (pre-seeded dupes collapse), tombstone
(delete + rescan -> stays deleted), save_annotations key preservation.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). All four audit findings fixed red-first: overlap-update adoption (drift = update, not append), collapse pass heals existing dupes even on empty scans, delete tombstones with bbox matching, save_annotations preserves unknown keys. Falsified the matcher -> 4 red. 204+82 green, AST sweep clean. Pouya's duplicated record self-heals on next load of the Biostatistics tab.

### K-082: Mirror, don't adopt: file owns outside marks; bake carries them verbatim
owner: -
priority: P1
tags: bug,redesign,orchestrator
files: klausmate/pdf_handler.py,klausmate/pdf_viewer.py,tests/test_klausmate.py
verify: python3 tests/test_klausmate.py && python3 tests/test_drive.py
created: 2026-08-24

Pouya: "the sync is still not working... this whole sync back and forth
is so, so buggy". Live state: records still hold his two texts, the FILE
holds ZERO annotations — Preview and Klaus each rewrite the whole file
from their own model, last writer wins. Adoption-and-rebake made Klaus a
second full-file writer of PREVIEW'S OWN marks: every bake replaced his
text boxes with pypdf-rendered copies, Preview's next autosave clobbered
them back, deletions in Preview resurrected on the next bake, and each
cycle reloaded the tab.

REDESIGN — mirror, don't adopt:
1. For OUTSIDE marks the FILE is the source of truth. Records mirror it:
   scan adds/updates (overlap logic from K-081) AND REMOVES external
   records whose original vanished (Preview deletes finally propagate).
2. Bake never writes external records. It regenerates ONLY native Klaus
   marks (marked) from pristine, and CARRIES the unmarked foreign
   /Highlight+/FreeText annots over VERBATIM (pypdf clone) — Preview's
   objects are never rewritten, so its appearance/behavior never changes
   under its feet. Tombstoned ones are dropped from the carry (Klaus
   deletes propagate to the file). Bake's own pristine capture switches
   to the stripped variant (plain copy2 would double carried marks).
   Un-bake keeps outside marks: empty records -> pristine + carry.
3. scan_working_annotations returns None on failure vs dict on success
   ({foreign, marked_ids, page_count}) — a failed scan must never
   mass-remove mirrored records. marked_ids protect legacy adopted
   copies (matched by /NM id) from removal; bake carries those verbatim
   too.
4. Viewer: external change with SAME page count = annotation-only edit
   -> mirror records, no document reload (kills the per-autosave
   flicker); page-count change -> full reload. Mirror pass schedules NO
   bake (the file is already right; baking here re-fed the watcher loop).

Remaining accepted churn: Preview's save can still drop Klaus's NATIVE
baked marks from the file (stale model) — records are truth, next bake
restores them; invisible in Klaus.

Verify: reworked invariants in test_klausmate (carry-verbatim incl.
Contents-less AP fingerprint, no marked external, foreign survive native
bake, un-bake keeps foreign, Preview-delete propagation, None-scan
mass-removal guard, tombstone-drop-from-carry, marked-by-id legacy,
page_count). Falsify carry and removal separately.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator). Redesign landed: file owns outside marks, records mirror (add/update/remove), bake carries foreign verbatim + drops tombstoned, stripped pristine capture in bake, None-vs-dict scan contract, page_count-gated reload (annotation edits no longer flicker the tab), mirror schedules no bake. Falsified carry (9 red) and removal (3 red) separately. 218+82 green, AST clean. Live: Pouya's stale records will mirror-remove on next tab load (file currently has no annots — converges to Preview truth); new Preview text mirrors in live; deletes propagate BOTH ways now.
