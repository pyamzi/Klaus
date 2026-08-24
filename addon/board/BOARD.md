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

## Ready

## Doing

## Review

## Done

### K-053: Per-PDF tags: indexing creates them, names follow the PDF
owner: sonnet-as
priority: P0
tags: sonnet-safe,library-era
files: klausmate/tag_sync.py,klausmate/pdf_drive.py,klausmate/curation.py,klausmate/manage_models.py,tests/test_tag_migrate.py
verify: test -f klausmate/tag_sync.py && grep -q sync_after_matches klausmate/pdf_drive.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_tag_migrate.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-24
claimed: 2026-08-24

Pouya: 'add to index / re-index should automatically create the tags. also, the tags should ALWAYS follow the name of the PDF' (the reverse direction — tag renames flowing back to the PDF — is card 2, K-054; do NOT build it here).

THE INVARIANT. Every indexed PDF owns exactly one collection tag, derived from its Library location and display name: !Library::<folder path, / -> ::>::<leaf>. Leaf = display name minus a trailing .pdf/.txt, sanitized tag-legal: spaces -> _, strip any ::, collapse repeats. The three reserved leaves (Curating, Curated, Matching — the static tags at that root) get a -pdf suffix if a display name sanitizes into them. The tag's members are exactly the notes whose cached match score >= that PDF's sensitivity.

NEW MODULE klausmate/tag_sync.py — pure logic importable without aqt (desired_tag(folder, display), the sanitizer, membership diff) with aqt glue at the edges, same layout discipline as retention.py. State: the prefs.json entry for each safe gains 'tag' = the last-applied tag name. That is what makes renames exact and orphan-removal exact — never inferred. retention.forget_prefs and clear_threshold_overrides already preserve unknown entry keys (K-049/K-052 groundwork; tests prove it) so 'tag' survives both.

SYNC EVENTS, forward only, each ONE undoable op (add_custom_undo_entry/merge_undo_entries — copy curation.create_curated_deck's pattern; tag_migrate.py:run_migration is the other reference and its docstring explains the OpChanges return contract that CRASHED Anki once — the op MUST return col.merge_undo_entries(pos), never a list):
1. After matches land: one shared hop tag_sync.sync_after_matches(safe) called from BOTH completion points — pdf_drive._on_embed's after_matches (:728) and curation.run_curation's after_matches (curation.py:322). This is the 'indexing creates the tags' ask itself.
2. Sensitivity changes: the per-PDF dialog's OK (pdf_drive._on_threshold), and manage_models' apply-to-all path (clear_threshold_overrides callers) — membership re-diffs.
3. Rename display (_rename_pdf), move to folder (_move_pdf, incl. drag-drop), folder rename (_rename_folder — batch every affected PDF in ONE undo entry): col.tags.rename(stored, desired) then store the new name.
4. Delete PDF (_delete_pdf): col.tags.remove(stored tag).
Apply/diff mechanics: desired nids = cached matches >= threshold; current = col.find_notes on the quoted tag; bulk_add missing, bulk_remove extra. A COLD OR INVALID matches cache (load_matches None) is a NO-OP with a status note — never strip a tag because a cache went cold; only scores may shrink membership.

Kill switch: config key library_tags_enabled, default true, read via cfg.get — document in config.md? config.md is NOT in your files; note it owed.

SAFETY, non-negotiable: this bulk-tags a real 28,668-note collection. Never write klausmate/user_files/ or meta.json*. Never execute against a real collection — logic is validated through fakes (tests/test_tag_migrate.py is IN your scope and already fakes col.tags for the migration; extend that harness for desired_tag/sanitizer/diff/reserved-leaf cases). Wrap every aqt edge in try/except with print('[klausmate] ...'). Tooltips quiet: one summary per event, no stacking (the tooltip-overlay race is documented in __init__'s clear handler — do not reintroduce it).

Qt cannot instantiate headlessly; you cannot see any of this run. Full suite green (297 across 6 files; yours should raise it — account for the delta). py_compile through the Anki symlink for every touched file. Stage by path, plain git add + plain git commit. Commit prefix K-053.

Done when: verify passes; indexing or curating a PDF yields its !Library tag on exactly the matched notes; rename/move/delete keep tag and PDF in lockstep from the PDF side; a cold cache never strips tags; everything is one undo away.

#### Comments
- [2026-08-24 orchestrator] Worker sonnet-as was lost when the host process exited — no partial work on disk (tag_sync.py never written, no commits). Relaunching fresh with the same brief; claim stays.
- [2026-08-24 sonnet-as] Decisions: New klausmate/tag_sync.py, layout mirrors retention.py (pure logic on top, aqt glue at bottom). Sanitizer: _sanitize_segment() applies to EVERY tag-path segment (folder parts AND leaf, not just the leaf) — Anki tags are whitespace-delimited in a note's tags field, so a raw space anywhere (including in a folder name like "Week 3") would silently split into two tags, not just look untidy. Rule: strip(), drop literal "::", whitespace-run -> "_", underscore-run collapse, trim edge "_". strip_pdf_ext() removes one trailing .pdf/.txt (case-insensitive) before sanitizing. desired_tag(folder, display) = "!Library" + sanitized folder segments (split on "/") + sanitized leaf, joined "::"; the three reserved leaves (curating/curated/matching, compared case-insensitively) only get a "-pdf" suffix when the PDF sits at !Library ROOT (folder falsy) — nested under any folder the full path already differs, so no collision. prefs.json gains a "tag" key per PDF (get_stored_tag/set_stored_tag), and every rename/delete event acts on THAT STORED VALUE, never a re-derived guess (tested explicitly). Latitude used: _do_sync_one self-heals if a stored tag ever drifts from the freshly-computed desired one (renames old->new before diffing) — belt-and-braces, not a competing rename feature; event 3 (_rename_pdf/_move_pdf/_rename_folder) is still the only UI-triggered rename path. Tooltip wording is plain/quiet, one per event, none on delete (the existing "Deleted "X"" tooltip already covers it — avoids the K-038 stacking race). Four events wired: (1) sync_after_matches — called from pdf_drive.DriveWindow._on_embed's after_matches (was `after_matches(_matches)`, now uses the value) and curation.run_curation's after_matches (deferred `from . import tag_sync`, same reason run_curation already defers `from . import retention`). (2) sync_after_threshold — pdf_drive._on_threshold's OK handler, reuses the dialog's own already-loaded `matches` var so "cold" reads identically to what the live preview already shows; sync_after_clear_overrides — manage_models.py's apply-to-all path, now captures `names = retention.threshold_override_names()` BEFORE calling clear_threshold_overrides() (that function only returns a count) and re-diffs exactly those PDFs in ONE undo entry after the user confirms. (3) sync_after_rename — _rename_pdf/_move_pdf, called after drive_store already recorded the change; sync_after_folder_rename — _rename_folder collects every PDF whose folder now starts with the new path (direct + nested) via drive_store.load() AFTER drive_store.rename_folder(), batched into one undo entry. (4) sync_after_delete — _delete_pdf, called BEFORE pdf_handler.delete_context (which chains to retention.forget_prefs and wipes the whole prefs entry incl. "tag" — this is the only place the tag name can still be read). Busy-token: sync_after_matches fires from BOTH after_matches callbacks, which in retention.ensure_matches/ensure_pdf_index already call release() (curation._busy = False) before invoking on_done — so by the time tag_sync runs, the composed pipeline's token is already free. tag_sync deliberately does NOT touch curation._busy itself: it isn't part of that composed pipeline (doesn't read/write card_index, pdf_index, or matches.json), it only touches col.tags and its own prefs.json "tag" key, so guarding it with the same token would just be dead weight, not a race fix. Each of the 4 events is exactly ONE CollectionOp via a shared _run_sync_op() helper whose op(col) ALWAYS returns exactly col.merge_undo_entries(pos) (never the dict work() returns) — this is the one place that OpChanges contract is satisfied, so all four events build on it instead of re-risking the 2026-08-23 crash per call site. Cold/invalid cache (retention.load_matches -> None) is checked before any tag mutation in sync_after_matches/sync_after_threshold/sync_after_clear_overrides and is always a no-op with a printed status line, never a strip. Kill switch: config key library_tags_enabled, default True via cfg.get. Files: klausmate/tag_sync.py (new), klausmate/pdf_drive.py (import + 6 call sites: _on_embed's after_matches, _on_threshold, _rename_pdf, _move_pdf, _rename_folder, _delete_pdf), klausmate/curation.py (run_curation's after_matches), klausmate/manage_models.py (save_threshold's apply-to-all path), tests/test_tag_migrate.py (extended FakeTags/FakeCol with bulk_add/bulk_remove/remove/find_notes + membership map, added RecordingOp double, 55 new checks: sanitizer, desired_tag root/nested/reserved-leaf, diff_membership add/remove/no-op, apply_membership/apply_rename/apply_renames/apply_removal against FakeCol, _run_sync_op's OpChanges contract, cold-cache no-op, kill-switch no-op — 11 -> 66 in this file). Verify passes (exit 0); full suite 298 -> 353 (the card said baseline 297 — I measured 298 right before my change via git show HEAD:tests/test_tag_migrate.py + running the other 5 files, so the delta is +55 test_tag_migrate.py checks, all new). py_compile clean through the Anki symlink for all four touched klausmate/*.py. Risks: the only structurally-untestable part is exactly what Qt's absence always means here — the real membership-diff body once a genuine matches cache exists requires retention.py/curation.py's full aqt.qt/gui_hooks/anki.collection surface, so sync_after_matches/sync_after_threshold's "real matches, not None" branch is verified by code review + the col-only apply_membership tests, not by driving the public function end-to-end (documented in the test file's own new section header). A no-op undo entry can occasionally be registered (add_custom_undo_entry always runs before the diff is known) when a re-sync finds nothing changed — matches existing precedent in retention.py/curation.py's own preview/clear ops, not a new pattern, but worth a reviewer's eyes since this card runs far more often than those. Next (owed, not done — outside this card's files): klausmate/config.md needs a "Feature toggles" entry for library_tags_enabled (default true) — config.md is not in K-053's file scope. K-054 (reverse direction, tag rename -> PDF rename) is untouched as instructed.
- [2026-08-24 orchestrator] Independently re-verified and signed off. I checked the three failure modes the brief called out, since each has a scar in this codebase: 1. OpChanges contract — satisfied through a single choke point. _run_sync_op is the ONLY CollectionOp in the module (grepped) and its op returns col.merge_undo_entries(pos). All four events route through it, so the crash that took down profile open cannot recur per-event. 2. Cold cache — every path short-circuits. _cached_matches documents None as retention's 'don't know'; the apply-to-all loop logs and CONTINUES per PDF rather than treating it as zero matches; sync_after_matches and sync_after_threshold both guard and return. No path can strip a tag because a cache went cold. 3. Busy token — tag_sync deliberately does not take curation._busy, and that is correct, but for a reason worth recording: bulk-tagging bumps note mods, and the match cache is keyed on card_index_digest (hashes+nids), NOT updated_at, specifically so tag-only mod bumps cannot invalidate it (retention.py:12-17). So tagging thousands of notes mid-pipeline causes no cache thrash, and CollectionOps serialise in the backend so the tag op cannot interleave destructively with curation's own preview tagging. Baseline correction accepted: the worker measured the real pre-change count (298, not my card's 297) from git rather than trusting my number — right instinct. 353 now; test_imports 19->20 is tag_sync joining the module glob. py_compile clean in-repo and through the Anki symlink for all four Python files. Owed and correctly reported: config.md's library_tags_enabled entry (out of file scope). Nothing about this ran against a live collection — Qt cannot instantiate here — so first real tagging happens on Pouya's next index/curate.

### K-054: Tag renames flow back to the PDF (reverse direction of K-053)
owner: sonnet-at
priority: P1
tags: sonnet-safe,library-era
files: klausmate/tag_sync.py,klausmate/pdf_drive.py,tests/test_tag_migrate.py
verify: grep -q reconcile_from_tags klausmate/tag_sync.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_tag_migrate.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-24
claimed: 2026-08-24

BLOCKED until K-053 is Done — same files. Pouya's invariant is bidirectional: 'the PDF should always follow the names of the tag, those two are always the same.'

Add tag_sync.reconcile_from_tags(col): for each prefs entry with a stored 'tag', if that tag still exists -> nothing. If it is GONE and exactly one unrecognized !Library:: tag exists that is not any PDF's stored tag and not a reserved leaf -> treat as a rename made in Anki's tag sidebar: update the PDF's display name (leaf, _ -> space) and folder path (parents) via drive_store, store the new tag. AMBIGUOUS cases (multiple missing, multiple candidates) -> enforce the forward direction instead: reapply the PDF-derived tag, log why. PDF wins ties because our side is deterministic.

Run it on profile open (register next to tag_migrate's hook — __init__.py is NOT in your files; state the one-line registration as owed) and at the top of DriveWindow._refresh_rows so opening/refreshing the Library picks up sidebar renames.

CAVEAT to encode in copy+tests: the mapping is lossy — spaces become _ in tags, so a genuine underscore in a display name round-trips to a space. Accept and document; do not build an escaping scheme.

Same safety/verify regime as K-053. Full suite green; py_compile via symlink; stage by path.

#### Comments
- [2026-08-24 orchestrator] PREREQUISITES CONFIRMED against the landed K-053 module before launch, so build on these rather than re-deriving them: desired_tag(folder, display) :136 — the forward mapping you must re-apply when a reverse match is ambiguous. get_stored_tag(safe) :226 / set_stored_tag(safe, tag) :240 — prefs.json's 'tag' key, the exact record of what was last applied. This is what makes 'the stored tag is GONE' detectable at all; never infer it from the current display name. _folder_and_display(safe) :248, _safe(name) :220, RESERVED_LEAVES :90, library_tags_enabled(cfg) :99 — reuse all four, do not reimplement. drive_store.rename_display(user_files, safe, display) :115 and set_folder(user_files, safe, folder) :105 — the write side of the reverse direction. add_folder :126 exists if a renamed tag implies a folder that is not registered yet; set_folder auto-registers unknown paths, so check before adding a redundant call. Also note K-053's verified gate: I confirmed _run_sync_op is the ONLY CollectionOp in tag_sync and that every op returns col.merge_undo_entries(pos). If reconcile_from_tags mutates the collection at all, it goes through that same helper — do not add a second op path. One live-state fact worth knowing: Pouya's prefs.json is currently {} (he cleared every per-PDF override via the new apply-to-all prompt), so NO PDF has a stored 'tag' yet — reconcile must treat 'no stored tag' as simply nothing to reconcile, not as a missing tag to hunt for. That is the state your code will actually meet on his first run.
- [2026-08-24 sonnet-at] Decisions: layered plan_reconcile(stored_by_safe, existing_tags) as pure decision core, fully unit-tested; reconcile_from_tags(col) is thin deferred-import glue around it (mirrors K-053's own pure/col-only/prefs-glue/aqt-glue layering). Ambiguity rule as implemented: per-safe, stored tag still in col.tags.all() -> untouched. Else it's in 'missing'. candidates = every !Library::-prefixed tag in the collection that is NOT any PDF's stored tag (missing or still-present) and not a root reserved leaf (_is_reserved_tag: exact !Library::Curating/Curated/Matching only, case-insensitive on the leaf -- nested e.g. !Library::Foo::Curating stays claimable, matching desired_tag's own root-only collision guard). len(missing)==1 and len(candidates)==1 -> confident rename (pure drive_store.rename_display + drive_store.set_folder + set_stored_tag writes, NO CollectionOp -- Anki's sidebar already moved every note's tag, nothing here touches col.tags). Any other shape (multiple missing, multiple candidates, zero candidates) -> 'reapply': _reapply_missing rebuilds each missing PDF's deterministic tag from its own cached matches.json scores via apply_membership, batched into exactly ONE _run_sync_op CollectionOp (no second CollectionOp path -- confirmed only call site). Tag->folder/display reversal is _tag_to_folder_display (underscore -> space per segment); _display_with_ext re-appends the OLD display's real .pdf/.txt extension so the Library does not lose file-type recognition on a confident rename. Called from: DriveWindow._refresh_rows (klausmate/pdf_drive.py, top of the method, before the QueryOp fires) -- in this card's file scope, done. Registration OWED to __init__.py (not in this card's files): gui_hooks.profile_did_open.append(tag_sync.reconcile_on_profile_open) -- written and documented in tag_sync.py but not wired, per the card's own instruction not to reach into __init__.py. Files: klausmate/tag_sync.py (plan_reconcile + _is_reserved_tag + _tag_to_folder_display + _display_with_ext + reconcile_from_tags + reconcile_on_profile_open + _reapply_missing, plus a docstring update noting the reverse direction now lives here), klausmate/pdf_drive.py (one-line reconcile_from_tags(mw.col) call at the top of _refresh_rows), tests/test_tag_migrate.py (27 new checks: 93 passed in that file, full 6-file suite now 380 vs the confirmed 353 baseline -- exactly +27, no regressions elsewhere). Lossy mapping: documented in _tag_to_folder_display's docstring and covered by a direct test (!Library::Week_3_Notes -> (None, 'Week 3 Notes') -- a genuine underscore reads back as a space, no escaping scheme added, per the card's instruction. Risks: reconcile_from_tags's own deferred-import body (prefs.json load, drive_store writes, the ambiguous-case CollectionOp) could NOT be verified headlessly -- retention.py pulls in curation.py's aqt.qt/gui_hooks/anki.collection surface, which this suite's minimal stub deliberately does not cover (same documented boundary K-053's sync_after_matches etc. already live with). Only the pre-import kill-switch short-circuit on reconcile_from_tags itself is directly tested; every ambiguity-rule branch is proven at the plan_reconcile level instead, which is where that logic actually lives and is untangled from aqt entirely. Qt cannot instantiate headlessly on this machine at all, so nothing here was tested against a live Anki/real collection -- stating that plainly rather than implying otherwise. Next: none from me -- the __init__.py registration line is the one remaining wire-up, owed as stated above.
- [2026-08-24 orchestrator] Signed off, with three closures from me on top. THE INFERENCE LOGIC IS RIGHT, and I falsified it rather than reading it: replacing the strict `len(missing) == 1 and len(candidates) == 1` guard with a naive `len(candidates) >= 1` turns 3 checks red. So the tests genuinely pin the ambiguity rule — a greedy implementation cannot pass. plan_reconcile is pure (no col, no prefs, no drive_store), which is what made that falsification possible at all. Confirmed exactly ONE CollectionOp call site remains in the module (:457) — the confident-rename path deliberately mutates nothing in the collection, since Anki's own sidebar rename already moved every note, and only the ambiguous reapply routes through _run_sync_op. The OpChanges contract holds. MY THREE FIXES: 1. Registered reconcile_on_profile_open on profile_did_open (owed, __init__.py out of scope), ordered right after tag_migrate's hook so it cannot race a rename the migration is performing. Without this the reverse direction only fired on a Library refresh — sidebar renames would have looked ignored until you opened the Library. That is the difference between the feature working and appearing not to. 2. reconcile_from_tags' docstring puts the None-check on callers; pdf_drive called it bare. Safe TODAY only because it returns early while no PDF has a stored tag — once tags exist, a closing profile logs a spurious failure every refresh. Guarded at the call site. 3. Updated the docstring still claiming registration was owed. Suite 380, py_compile clean in-repo and through the symlink. Untestable here as the worker stated: the deferred-import body needs the full aqt surface, so the glue is verified by review and the decision core by the pure tests.

### K-056: Editor: replace the bottom PDF bar with a "Library..." button left of Fields...
owner: opus
tags: sonnet-safe,library-era
files: klausmate/__init__.py,klausmate/web/copilot.js
verify: grep -q "klausmate-library-btn" klausmate/web/copilot.js && ! grep -qE "_PdfBar|_KlausmatePanel|notetypeButtons|uiPromise" klausmate/__init__.py
created: 2026-08-24
claimed: 2026-08-24

Pouya (screenshots on card): remove the bottom PDF bar from the editor
("Measures_… [Browse…] Remove ◧") entirely. Add a button named EXACTLY
"Library..." at the TOP LEFT of the editor toolbar — to the LEFT of the
"Fields..." button, i.e. inside Anki's notetype button group, not the addon
group on the right. From it you choose PDFs already in the library; you can
NOT add new PDFs from the editor anymore (the Library window's drop zone is
the only add path).

VERIFIED API (extracted from 26.8.1 aqt/editor.pyc — Anki itself injects raw
HTML buttons into that exact group):
  uiPromise.then((noteEditor) => noteEditor.toolbar.notetypeButtons.appendButton(
      { component: editorToolbar.Raw, props: { html: ... } }, -1));
Both uiPromise and editorToolbar are globals in the editor webview. For
LEFTMOST placement use insertButton(button, 0) (inserts BEFORE index 0);
fall back to appendButton(button, 0) if insertButton is undefined, and log
which path ran — final left-of-Fields placement is a live check for Pouya.
Run the eval per-editor from gui_hooks.editor_did_init (each editor webview
has exactly one NoteEditor, so instances[0]/the uiPromise arg is safe).

BUTTON BEHAVIOR: html <button> with onclick pycmd('klausmate:library:<b64 {}>')
— the bridge in on_js_message already routes klausmate:<action>:<b64> (only
focus/crop/log/dbg remain; add 'library'). Handler = the old bar toggle role:
if the PDF panel is visible -> panel_hide(); if hidden -> panel_show(), and
when no tab is open, immediately pop the stored-PDF picker (_show_add_menu)
so the user lands in "choose from the library". Style the button to not look
alien next to Fields.../Cards... (a bare <button> gets browser-default
styling; borrow the neighboring buttons' classes or minimal inline style —
visual check is Pouya's).

REMOVALS: _PdfBar class (~:653-850) and its host wiring in _KlausmatePanel
(~:851+). _KlausmatePanel exists to host the bar below the Tags row — if
nothing else remains in it, delete the panel and its editor-layout insertion
too. PRESERVE the logic the bar delegated to (remove-current-pdf, toggle,
_ensure_sidebar_pdf) by moving what the new handler needs; per-tab close
buttons and the panel header's ◫/＋ controls already cover the rest (verified:
header has thumbs toggle, ＋ add menu, per-tab close, page indicator).
Also remove the filesystem "Browse…" entry from the container's ＋ menu
(~:2255) — the menu lists ONLY stored library PDFs now. Grep before every
delete; anything else that references a removed symbol must be resolved, not
commented out.

copilot.js is in the files list in case the eval approach needs a JS-side
assist (e.g. re-inserting after notetype switches rebuild the toolbar — test
switching Type in the Add window mentally: if the group re-renders, the
button must come back; a MutationObserver in copilot.js is the fallback).

Headless coverage is limited to py_compile + greps; the placement, styling,
toggle behavior, and notetype-switch survival all go on Pouya's restart queue
— list them explicitly in your handoff comment.

#### Comments
- [2026-08-24 Pouya] ![](attachments/d995a104801b8de0.png) This is what I am referring to
- [2026-08-24 Pouya] You can honsetly just place it at the top near all of the other buttons
- [2026-08-24 Pouya] ![](attachments/729bf33906c9089c.png)
- [2026-08-24 Pouya] This is what I mean by the top
- [2026-08-24 Pouya] Ensure that it is on the top Left side of you place it at the top, like to the left of Fields..., and name it "Library..."
- [2026-08-24 opus] Live crash report from Pouya mid-task (restarted Anki against the half-edited tree): NameError _KlausmatePanel at __init__.py:2135 in _install_klaus_bar. Expected transient state, but it pins the must-fix: _install_klaus_bar (~:2103-2161, QTimer.singleShot install path) must be rewritten or removed along with the class. Verify gate now also rejects any _KlausmatePanel reference — py_compile cannot catch dangling names, greps can.
- [2026-08-24 opus] Handoff: sonnet-av built the button machinery (HTML/JS injection with insertButton-then-appendButton, polling for page globals, script-escape guard, toggle handler, module-level _ensure_sidebar_pdf) then was stopped mid-task; the half-edited tree crashed live Anki (NameError _KlausmatePanel at :2135). Opus completed the rewiring: editor-init now evals the button JS (AnkiWebView.eval queues until page load; the JS polls for globals), bridge routes 'library' via singleShot (menu exec must not run in the webchannel handler), both dead panel refs deleted, + menu lost its filesystem Browse... and gained a disabled empty-state hint, QDialogButtonBox/QFileDialog/QFrame imports trimmed, copilot.js re-mounts the button after notetype switches. Verify gate PASS; py_compile through symlink ok; full suite 68/57/60/20/82/113 all green; leftover sweep clean (remaining QFileDialog/QDialogButtonBox hits are deck_curate/pdf_drive's own legitimate uses). LIVE CHECKS for Pouya: placement left of Fields..., styling, toggle, notetype-switch survival, empty-Library hint.
- [2026-08-24 opus] Signed off: headless criteria all met (gate, compile, suite, sweep). Live-only items stay on the restart queue and were listed in the handoff — if any fail on restart, reopen this card rather than filing fresh.
- [2026-08-24 opus] REOPENED (live failure, Pouya): button never appeared. Root cause found in the shipped web bundle, not the pyc: (1) our mount polled window.uiPromise/window.editorToolbar — both are page-lexical bindings, never window properties, so the poll timed out silently; (2) worse, editorToolbar.Raw does not exist in 26.8.1's editor.js bundle at all (editorToolbar exports only AddonButtons) — the pyc snippet naming Raw is dead legacy code, so the component path could never have worked. New approach: copilot.js (already injected in every editor page) mounts via plain DOM — find the native Fields... button, clone its className for native styling, insertBefore, pycmd on click; MutationObserver re-mounts after toolbar rebuilds. Gate updated to match.

### K-055: Retire the !Library::Matching preview tag (per-PDF tags replaced it)
owner: sonnet-au
tags: sonnet-safe,library-era
files: klausmate/retention.py,klausmate/pdf_drive.py,klausmate/manage_models.py,klausmate/tag_migrate.py,klausmate/tag_sync.py,tests/test_tag_migrate.py
verify: ! grep -qE "RETENTION_TAG|preview_matches|clear_pdfmatch_tag" klausmate/retention.py klausmate/pdf_drive.py klausmate/manage_models.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_tag_migrate.py
created: 2026-08-24
claimed: 2026-08-24

Pouya's screenshot: !Library::Matching lingers in the Browse tag sidebar.
Root cause: retention.preview_matches (called from pdf_drive._on_browse ~:842,
the Library right-click "Show matches in Browse") bulk-adds the temp tag
RETENTION_TAG onto every matched note per preview and it never fully leaves.
Since K-053 every indexed PDF has a DURABLE per-PDF tag holding exactly the
matches above the current sensitivity — the temp preview vehicle is redundant.

CHANGES (all call sites verified 2026-08-24; the only callers of the retiring
functions are the two listed below — still grep before you delete):

1. pdf_drive._on_browse (~:830-842): keep the existing guards ("Embed this PDF
   first", "No cards above the current sensitivity"), but replace the
   retention.preview_matches(mw, nids) tail with: tag = tag_sync.get_stored_tag(safe);
   if tag -> browser = aqt.dialogs.open("Browser", mw); browser.search_for of
   tag:"<tag>" (quote it — tag names contain no spaces by construction but
   quote anyway). If no stored tag -> self.status.setText telling the user to
   re-index this PDF to create its Library tag. No note mutation, no CollectionOp.

2. retention.py: delete preview_matches, clear_pdfmatch_tag, RETENTION_TAG.
   Do NOT touch the unrelated "Matching cards…" progress label (~:690).

3. manage_models.py (~:1370-1381): the Clear-library-tag maintenance flow
   counts RETENTION_TAG notes and calls clear_pdfmatch_tag(dlg, quiet=True) —
   remove both; adjust its combined summary message accordingly.

4. tag_migrate.py: (a) the legacy map entry "klaus::pdfmatch" ->
   "!Library::Matching" (~:52) — remove the pair; renaming into a tag we are
   abolishing is pointless. (b) Add a one-time idempotent cleanup that runs in
   the same profile-open pass: for each of "klaus::pdfmatch" and
   "!Library::Matching", if the tag exists, bulk_remove it from all carrying
   notes AND col.tags.remove it so the empty entry leaves the sidebar. Skip
   silently when neither exists (idempotency = structural, like plan_renames).
   HARD CONTRACT: any CollectionOp op MUST return col.merge_undo_entries(pos)
   — a plain return here crashed every profile open once (see run_migration's
   docstring). Reuse/extend the existing op rather than adding a second one.

5. tag_sync.py: COMMENTS ONLY — lines ~18, ~149, ~183 reference retention's
   !Library::Matching; update the prose. Leave RESERVED_LEAVES exactly as is
   ("matching" stays reserved so a PDF literally named Matching can never
   collide with historical tags).

TESTS: extend tests/test_tag_migrate.py with the cleanup (stub-col pattern
already in the file): tag exists -> removed from notes + registry; neither
tag exists -> no-op, op not launched; klaus::pdfmatch alone -> cleaned.
TRAP: the test file ends with print(summary) + sys.exit() — insert new tests
ABOVE that block or they silently never run (this bit us twice).

#### Comments
- [2026-08-24 Pouya] ![](attachments/cea1eabb6913859e.png) this is what keeps showing up
- [2026-08-24 sonnet-au] Decisions: pdf_drive._on_browse now looks up tag_sync.get_stored_tag(safe) and opens Browse on that stored !Library tag directly (no note mutation, no CollectionOp) instead of retention.preview_matches; falls back to a status message telling the user to re-index when there's no stored tag yet. retention.py: deleted preview_matches, clear_pdfmatch_tag, and the RETENTION_TAG constant, plus the now-unused aqt/CollectionOp/tooltip imports (only QueryOp and mw are still used). manage_models.py's clear_library_tag keeps only the curation-tag half (curation.TEMP_TAG / clear_curation_tag) and its summary message dropped the PDF-match count. tag_migrate.py: removed the 'klaus::pdfmatch' -> '!Library::Matching' pair from TAG_RENAME_MAP and added MATCHING_TAGS_TO_REMOVE + plan_matching_cleanup (pure, structurally idempotent like plan_renames) — run_migration now also bulk_removes each retired tag from its notes and calls col.tags.remove on it, in the SAME undo entry/op as the rename batch; migrate_on_profile_open's pre-flight check now short-circuits only when both plan_renames AND plan_matching_cleanup are empty. tag_sync.py: comments-only prose updates at the module docstring, the RESERVED_LEAVES block, desired_tag's docstring, and _is_reserved_tag's docstring — all now describe !Library::Matching as retention.py's retired preview tag rather than a live one; RESERVED_LEAVES itself is untouched. Files: klausmate/retention.py, klausmate/pdf_drive.py, klausmate/manage_models.py, klausmate/tag_migrate.py, klausmate/tag_sync.py, tests/test_tag_migrate.py. Risks: run_migration's cleanup loop calls col.find_notes(f'tag:"{tag}"') then col.tags.bulk_remove before col.tags.remove — real Anki's tags.remove may already strip membership on its own, so the bulk_remove call could be a harmless no-op in production even though the FakeCol test double tracks it as a distinct call; worth a sanity check against a live collection if anyone's touching this path again. Also note manage_models.py's askUser copy changed from 'Clear the Klaus curation and PDF-match tags' to 'Clear the Klaus curation tag' (singular) since there's only one tag left to clear. Next: none — all five call-site changes and the tag_sync comment updates from the card body are done.
- [2026-08-24 opus] REWORK (review finding, confirmed in code): migrate_on_profile_open early-returns on MIGRATED_FLAG (_library_tag_migrated) BEFORE the pre-flight — and that flag is already True on Pouya's profile from the original klaus::->!Library run. So the new Matching cleanup never executes for the exact user who reported the tag. Same failure class as the retired one-shot _threshold_default_migrated. Fix: add a second flag (e.g. _matching_tag_removed) guarding only the cleanup pass; proceed when EITHER flag is unset; empty pre-flight records both. Add the falsifying test first — 'rename flag already set, !Library::Matching present -> cleanup still runs' — confirm it is RED against the current commit, then green after.
- [2026-08-24 sonnet-au] REWORK addressed. Bug confirmed: migrate_on_profile_open's 'if cfg.get(MIGRATED_FLAG): return' short-circuited before the K-055 pre-flight ever ran plan_matching_cleanup — and MIGRATED_FLAG is already True on any profile that completed the original klaus::->!Library rename (Pouya's included), so the Matching cleanup was unreachable for exactly that user. Process: (1) wrote the falsifying test FIRST in tests/test_tag_migrate.py ('migrate_on_profile_open (K-055 rework): MIGRATED_FLAG already True must NOT block the Matching cleanup' — pkg.get_config returns only {MIGRATED_FLAG: True}, collection carries !Library::Matching with a note on it) and ran it against the unfixed commit: RED, 4 checks failed, exit 1, reported count 109 passed/4 failed. (2) Added MATCHING_MIGRATED_FLAG = '_matching_tag_removed' in tag_migrate.py, independent of MIGRATED_FLAG; migrate_on_profile_open's early-return now requires BOTH flags set ('if cfg.get(MIGRATED_FLAG) and cfg.get(MATCHING_MIGRATED_FLAG): return'); the pre-flight (and _record_flags, renamed from _record_flag) now runs whenever either is unset and always records both on completion — existing MIGRATED_FLAG semantics for a fresh profile (no legacy tags at all) are unchanged since both plans are empty and both flags get set together in the same step. (3) Reran: GREEN, 113 passed/0 failed, exit 0. (4) Reran the card's exact verify command end to end: exit 0, 113 passed/0 failed. Files: klausmate/tag_migrate.py (MATCHING_MIGRATED_FLAG constant + docstrings; migrate_on_profile_open's two-flag gate; _record_flag -> _record_flags), tests/test_tag_migrate.py (the new falsifying test, inserted above the print(summary)+sys.exit() trap — confirmed count increased 109 -> 113). No other card files touched in this rework; original K-055 commit was amended in place (same K-055-prefixed message, now with a Rework paragraph) rather than added as a second commit, per your instruction, so exactly one commit still carries this card. Risks: none new beyond what the original handoff already flagged (the bulk_remove-before-tags.remove redundancy in run_migration's cleanup loop). Next: none.
- [2026-08-24 opus] Signed off. Independent falsification: re-introduced the single-flag guard -> 4 red; restored -> 113 green. Gate grep-clause clean. The rework's amend pre-dated the K-056 commits, so history stacked cleanly (e6e47cf under a5111d0) — no rewrite occurred. Live check on next restart: !Library::Matching disappears from the Browse sidebar on profile open, and Library right-click 'Show matches in Browse' opens Browse filtered to the PDF's own tag.

### K-064: Retire the !Library::Curating preview tag (K-055's sibling)
owner: opus
priority: P2
tags: library-era
files: klausmate/curation.py,klausmate/manage_models.py,klausmate/tag_migrate.py,klausmate/tag_sync.py,klausmate/deck_curate.py,tests/test_tag_migrate.py,tests/test_klausmate.py
verify: ! grep -qE "TEMP_TAG" klausmate/curation.py klausmate/manage_models.py klausmate/deck_curate.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_tag_migrate.py
created: 2026-08-24
claimed: 2026-08-24

Pouya: Matching is gone from the Browse sidebar but !Library::Curating
still lingers — same disease, same cure as K-055. The curation preview
stamps curation.TEMP_TAG onto matched notes; post-K-044 the match set
equals the per-PDF tag's content, so preview should search that tag
(composable with a deck scope: tag:"<pdf-tag>" deck:"<scope>") and the
temp-tag machinery retires. KEEP !Library::Curated (permanent marker on
notes copied into a curated deck) and keep the Curate Deck button itself:
indexing computes matches and tags; curating CREATES A NEW DECK with
copies — indexing must never create decks as a side effect.

CRITICAL FLAG LESSON (bitten twice now): tag_migrate's cleanup is guarded
by MATCHING_MIGRATED_FLAG which is one-shot and has ALREADY FIRED on
Pouya's profile today. Simply appending Curating to
MATCHING_TAGS_TO_REMOVE would be unreachable — the third instance of the
stale-one-shot-flag bug. Replace the boolean with a config list of
cleaned tag names (e.g. _retired_tags_cleaned: [...]); pre-flight = set
difference against the current retirement list, so every future
retirement is automatically reachable. Migrate the existing booleans:
treat MATCHING_MIGRATED_FLAG=True as the two K-055 names already cleaned.
Falsifying test required: flags/list say Matching cleaned, collection
carries !Library::Curating -> op launches and removes it (RED before fix).
Also remove klaus::curate -> !Library::Curating from TAG_RENAME_MAP and
clean both names; RESERVED_LEAVES untouched.

#### Comments
- [2026-08-24 opus] Committed 50d8997. Red-first honored: falsifying test (both legacy booleans True + Curating present) was RED 5 failures against the pre-fix tree, GREEN after; full suite 408 assertions green; gate PASS; compile-all ok. Design notes: preview sequenced through sync_after_matches on_done (fires on success/failure/early-out — releases the busy token, skipping it would deadlock); copies keep source tags; Curate Deck button intentionally KEPT (it creates a deck; indexing must never create decks). Live checks: Curating vanishes from Browse sidebar on next profile open; curation preview opens Browse on the per-PDF tag; Preferences no longer shows Clear library tag.

### K-063: K-056 rework: DOM-mount the Library... button (component API was dead code)
owner: opus
priority: P2
tags: library-era
files: klausmate/__init__.py,klausmate/web/copilot.js
verify: grep -q "klausmate-library-btn" klausmate/web/copilot.js && ! grep -qE "notetypeButtons|uiPromise|_library_button_js" klausmate/__init__.py
created: 2026-08-24
claimed: 2026-08-24

Live failure: button never appeared. Bundle ground truth (26.8.1
_aqt/data/web/js/editor.js): editorToolbar exports ONLY AddonButtons — the
Raw component the pyc snippet references is dead legacy code; and
uiPromise/editorToolbar are page-lexical bindings, invisible as window.*
properties, so the old poll timed out silently. Fix: copilot.js (already
injected into every editor page) mounts by DOM — find the native button
whose trimmed text starts with "Fields", create <button
id=klausmate-library-btn> cloning its className for native styling,
insertBefore it, onclick pycmd('klausmate:library:e30='); initial timed
retries + MutationObserver re-mount after toolbar rebuilds. Python side:
delete _library_button_js/_LIBRARY_BTN_ID and the editor.web.eval; keep
_on_library_button and the bridge action unchanged. Label-match is
English-locale-bound — acceptable (personal addon), log when not found.

#### Comments
- [2026-08-24 opus] Committed. Gate PASS, py_compile ok, node --check ok on copilot.js. Live check remains: button appears left of Fields... in Add/Browse/EditCurrent, native styling via cloned className, survives notetype switch, click toggles PDF panel.
- [2026-08-24 opus] Signed off with K-064; both ship together on Pouya's next restart. If the button still fails to appear, the copilot.js console line '[klausmate] Library button: Fields... never appeared' is the tell — report what the editor console shows.

### K-065: Library... button: click must survive Svelte node cloning
owner: opus
priority: P2
tags: library-era
files: klausmate/web/copilot.js,klausmate/__init__.py
verify: grep -q "addEventListener(\"click\"" klausmate/web/copilot.js && ! grep -q "btn.addEventListener" klausmate/web/copilot.js
created: 2026-08-24
claimed: 2026-08-24

Live report: button renders but clicking does nothing. Python path verified intact (hooks registered, bridge block present, handler mirrors the old bar toggle exactly) — the likely killer is on the page: Svelte re-renders can clone DOM subtrees, and cloneNode keeps the button's markup but drops addEventListener handlers, leaving a dead shell that the remount observer skips (getElementById still finds it). Fix: no per-node listener at all — one document-level capture-phase click listener using closest('#klausmate-library-btn'), which fires regardless of how many times the node is recreated and beats Svelte's own delegation. Exactly ONE dispatch mechanism (an inline onclick attribute PLUS delegation would double-fire the toggle). Add console breadcrumbs on mount and click so a still-dead button becomes diagnosable.

#### Comments
- [2026-08-24 opus] Committed. node --check ok, py_compile ok, gate PASS. Breadcrumb design makes the next failure (if any) self-localizing: '[klausmate] Library button clicked' in the editor console but no '[klausmate] Library button: toggling PDF panel' on stdout = bridge; neither = page; both = panel logic.

### K-066: Cache-bust copilot.js + breadcrumb diagnostics for the dead click
owner: opus
priority: P2
tags: library-era
files: klausmate/__init__.py,klausmate/web/copilot.js
verify: grep -q "copilot.js?v=" klausmate/__init__.py
created: 2026-08-24
claimed: 2026-08-24

Button still dead after K-065 despite a verified restart (Anki up 16:39:01, commit 16:38:18). Prime suspect: QtWebEngine caches /_addons/ web assets across restarts, so the page may still run the K-063 copilot.js — mount works (button renders), per-node listener dies to Svelte node cloning (clicks dead), and K-065's delegated-listener fix never reached the page. Fix: append ?v=<file mtime> to the copilot.js URL in on_webview_will_set_content. Plus temp breadcrumbs to /tmp/klausmate-debug.txt: script-loaded and button-mounted pings from the page via pycmd dbg, bridge-level log of every klausmate:* message, and step logging in _on_library_button — so a still-dead click localizes to page/bridge/panel in one report.

#### Comments
- [2026-08-24 opus] Committed. /tmp/klausmate-debug.txt cleared pre-test. Expected healthy sequence after restart+click: script-loaded (+late), button-mounted, click-heard, bridge: klausmate:library, handler entered, isVisible/placed state, panel_show done. Diagnostics are temporary — file a removal card once the button is confirmed working.

### K-067: Restore _ensure_sidebar_pdf (K-063's block-cut swallowed it)
owner: opus
priority: P2
tags: library-era
files: klausmate/__init__.py
verify: grep -q "def _ensure_sidebar_pdf" klausmate/__init__.py && python3 -c "import ast,sys; tree=ast.parse(open(\"klausmate/__init__.py\").read()); names={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}; sys.exit(0 if \"_ensure_sidebar_pdf\" in names else 1)"
created: 2026-08-24
claimed: 2026-08-24

Breadcrumbs localized the dead Library... button to a NameError: K-063's range-delete of the dead JS-injection block also swallowed the module-level _ensure_sidebar_pdf that sat between the anchors. Two live call sites survived: _on_library_button (the button click — dead since K-063) and _PdfTabContainer.showEvent:968 (silently broken since K-063). py_compile cannot catch dangling names; the reviewer's own rule — grep every deleted symbol — was preached to the worker and then violated by the reviewer. Restore the function verbatim from commit a5111d0.

#### Comments
- [2026-08-24 opus] Committed. Gate PASS (def present + AST membership); full-file AST name-resolution sweep shows zero other unresolved symbols. Everything upstream of the NameError was already proven live by Pouya's own clicks in the breadcrumb log, so this restore is the last missing link. Diagnostics stay in until he confirms, then a removal card.

### K-068: Harden PDF panel teardown (SIGSEGV + dead-label RuntimeError)
owner: opus
priority: P2
tags: library-era
files: klausmate/pdf_viewer.py,klausmate/__init__.py
verify: grep -q "except RuntimeError" klausmate/pdf_viewer.py && grep -q "_hidden_for_close" klausmate/__init__.py
created: 2026-08-24
claimed: 2026-08-24

Live crash pair from Pouya: (1) hard SIGSEGV in sipSubClass_QPdfView while AnkiApp's app-level event filter converts a mouse-event receiver — a C++-deleted QPdfView still referenced by Qt's mouse pipeline, ~2.5s after a successful embed, consistent with the host Add window closing while the panel's viewer sat under the cursor; (2) RuntimeError: _page_label QLabel deleted while the viewer's nav signal still fires — the label is the viewer's child ADOPTED into the container header (cross-tree ownership), so partial teardown can kill either half first. Fixes: guard every _page_label touch with except RuntimeError (house convention, missing here); on the host's Close event, synchronously hide() the panel before the deferred teardown check so a dying viewer leaves the hover/tracking pipeline immediately (re-show if the close turns out cancelled — AddCards' discard prompt). Both mitigations are independent of the exact deletion order, which static reading could not fully pin. Breadcrumb diagnostics stay in until stable.

#### Comments
- [2026-08-24 opus] Committed. Gate PASS, compile ok, full suite 408 green. Confidence honest: the RuntimeError is FIXED (deterministic guard); the SIGSEGV is MITIGATED via close-time hide — a use-after-free in Qt's mouse pipeline can't be reproduced headlessly, so live confirmation is Pouya toggling the panel then closing the Add window several times, cursor over the PDF. If it segfaults again, next step is deterministic early teardown of the container on Close (deleteLater at a safe point) rather than riding the window's destructor cascade.

### K-069: Strip K-066 diagnostics; document library_tags_enabled in config.md
owner: sonnet-aw
priority: P2
tags: sonnet-safe,library-era
files: klausmate/__init__.py,klausmate/web/copilot.js,klausmate/config.md
verify: ! grep -rq "_dbg" klausmate/__init__.py klausmate/web/copilot.js && grep -q "library_tags_enabled" klausmate/config.md
created: 2026-08-24
claimed: 2026-08-24

Pouya confirmed the Library... button and panel are stable — the temporary
diagnostics come out. REMOVE: the _dbg helper and every _dbg(...) call in
__init__.py (bridge-level message log, all handler step logs — the marker
comment says 'K-066 TEMP DIAGNOSTICS'); in copilot.js the ping() function,
both script-loaded pings, the button-mounted ping, and the click-heard ping
(the console.log lines may stay — they are free and aid future debugging).
KEEP (permanent, do not touch): the ?v= cache-buster on the copilot.js URL,
the _hidden_for_close close-time hide, the RuntimeError guards, the
document-level click delegation, and the MutationObserver remount.
Grep '_dbg' across klausmate/ after removal — zero hits (the deleted-symbol
lesson from K-067 applies in reverse: no orphaned callers).

Second job, owed since K-053: klausmate/config.md documents every config
key — add library_tags_enabled (default true; when off, Klaus stops
creating/updating the per-PDF !Library tags and the curation Browse
preview is skipped). Match the file's existing entry style exactly.

#### Comments
- [2026-08-24 sonnet-aw] Decisions: removed the _dbg helper/comment block, the bridge-level _dbg call in on_js_message, and every step _dbg call inside _on_library_button (kept the print() in the except branch, and the try/except structure itself). In copilot.js removed the ping() function + its comment, both script-loaded pings, the button-mounted ping, and the click-heard ping; kept both console.log lines, the document-level click delegation, and the MutationObserver remount untouched. Added library_tags_enabled to config.md under Feature toggles, describing the tag_sync.py kill switch (default true) and that turning it off also skips curation's Browse-preview step since the per-PDF !Library tag is that preview's vehicle (curation.py's K-064 note). Files: klausmate/__init__.py, klausmate/web/copilot.js, klausmate/config.md. Verify: '! grep -rq "_dbg" klausmate/__init__.py klausmate/web/copilot.js && grep -q "library_tags_enabled" klausmate/config.md' exits 0. Risks: none identified -- grepped '_dbg' across klausmate/ (excluding user_files) after removal, zero hits; confirmed KEEP items (?v= cache-buster, _hidden_for_close, document-level click delegation, MutationObserver) all still present untouched. Next: none. Commit: b1ae797.
- [2026-08-24 opus] Signed off: diff reviewed, all KEEP items verified present (cache-buster, _hidden_for_close, RuntimeError guards, delegation+observer), gate PASS, py_compile + node --check green. config.md entry is accurate incl. the K-064 preview interaction. Board commit deferred until the swarm drains.

### K-071: Phase D1: embedding map foundation — 2D projection + graph data (no UI)
owner: sonnet-ay
priority: P2
tags: sonnet-safe,library-era
files: klausmate/projection.py,klausmate/pdf_graph.py,tests/test_projection.py
verify: test -f klausmate/projection.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_projection.py
created: 2026-08-24
claimed: 2026-08-24

First card of Phase D (Pouya's K-058: start the next stages): the
Obsidian-like map of all embeddings. This card is the HEADLESS foundation
only — the window/canvas UI is the next card, so everything here must be
fully testable offline. NEW FILES ONLY; touch nothing existing.

1. klausmate/projection.py (aqt-free, stdlib only — NO numpy, Anki's env
   has none): project unit vectors (array('f') rows, the card_index/
   pdf_index storage format) to 2D via PCA — top-2 principal components
   by power iteration with deflation on mean-centered data, using
   math.sumprod over memoryviews for the inner loops (same trick that
   makes card_index.top_k rank 30k x 768 in ~0.25s). Deterministic:
   seeded start vectors, fixed iteration count (~40) with an early-out on
   convergence. Cap the input at max_points (default 4000) by even-stride
   sampling so a 30k-note index stays interactive; the cap and stride are
   parameters. API: project(rows: Sequence[memoryview|sequence], *,
   max_points=4000, seed=0) -> list[tuple[float, float]] plus the chosen
   row indices, normalized into [-1, 1] on both axes.
2. klausmate/pdf_graph.py: build_graph_data(user_files, cfg) -> dict —
   assembles the JSON the future canvas will render: PDF nodes (safe
   name, display name, folder, threshold, retention if cached) placed at
   the centroid of their matched notes' 2D positions; note nodes (nid,
   xy); edges PDF->nid for matches at-or-above that PDF's threshold,
   read from the existing matches.json caches via retention.load_matches
   (import inside the function; treat None as 'unknown — skip that PDF,
   never invent empties'). Read vectors via card_index/pdf_index public
   loaders only — if a loader is missing, add nothing to those modules;
   read the packed files directly here instead and note it on the card.
   No Qt imports at module top; keep the module importable headless.
3. tests/test_projection.py (new, follow the aqt-stub pattern from
   tests/test_klausmate.py's header): projection determinism (same seed,
   same output); two well-separated clusters in 768-d land well-separated
   in 2D (inter-cluster 2D distance > intra-cluster); max_points
   sampling respected; degenerate inputs (0 rows, 1 row, identical rows)
   return without dividing by zero; build_graph_data on a synthetic
   scratch store produces consistent node/edge counts and skips a PDF
   whose match cache is absent. Standalone runner style: check()
   counters + print(summary) + sys.exit like the other test files.

Never point anything at the real user_files — scratch fixtures only.

#### Comments
- [2026-08-24 sonnet-ay] Decisions: projection.py does top-2 PCA via power iteration + deflation directly on the n x d centered data matrix (never forms the d x d covariance matrix). Both matrix-vector directions (X@v row-wise, X.T@s column-wise) reuse ONE packed array('d') buffer — column j is read via a strided memoryview slice mv[j:n*d:d] instead of building a separate transposed copy, so no extra O(n*d) transpose pass is needed. math.sumprod is used with the same pre-3.12 zip/sum fallback card_index.py already carries (this repo's plain python3 is 3.9.6, confirmed via 'python3 --version', no math.sumprod). pdf_graph.build_graph_data derives the embedding signature from the loaded card_index itself (cidx.provider, cidx.model) rather than recomputing embeddings.index_signature(cfg) — avoids a spurious 'stale index' false-skip if cfg drifts from what was actually indexed, and let pdf_graph.py skip importing embeddings.py entirely. It relies entirely on retention.load_matches' own invalidation checks (signature/dims/source_sig/digest/agg) to decide None='unknown, skip' rather than duplicating that staleness logic. retention.py is imported LAZILY inside build_graph_data (it pulls in aqt via curation.py at its own module top) so pdf_graph.py itself stays Qt-free at import time; card_index/pdf_index/pdf_handler/drive_store are the public loaders already documented in CLAUDE.md and needed no additions. One notable side effect: build_graph_data sets the module global retention.USER_FILES = user_files before calling retention.load_matches, because that function has no per-call user_files parameter — this mirrors the exact pattern tests/test_klausmate.py already uses (retention.USER_FILES = tmp) to redirect it in tests; in production user_files is always curation.USER_FILES already so it's a no-op there. PDF node 'retention' field is always None headlessly (FSRS scoring needs a live collection this module never has). A PDF whose cached matches don't overlap the projected/sampled note subset (when max_points caps a large collection) is skipped like an absent cache — documented as a tradeoff in pdf_graph.py's module docstring. Files: klausmate/projection.py (new), klausmate/pdf_graph.py (new), tests/test_projection.py (new). Risks: the retention.USER_FILES mutation above is the one thing worth a second look — it's an accepted pattern in this codebase but it is a cross-module global side effect. Also flagging for the reviewer: pdf_graph.py never validates that a PDF's own pdf_index/<safe>/ chunk index is complete/fresh before reading its matches.json — it doesn't need to, because retention.load_matches already re-validates (provider,model,dims,source_sig,digest,agg) against what's stored, so a stale/incomplete PDF index just yields no match cache -> skip, same as a totally absent one. Next: none — this card is headless data-layer only; the window/canvas UI is explicitly the next card per K-058 Phase D. Verify: 'test -f klausmate/projection.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_projection.py' -> exit 0, 28 passed, 0 failed. Rough timing line from the run: 'projected 4000x768 in 8.21s (no numpy, no C ext)' — that's under Python 3.9.6's math.sumprod-less fallback path (system python3 has no math.sumprod; confirmed the fallback is exercised, matching card_index.py's own compatibility story).
- [2026-08-24 opus] Signed off. Review: scope exact (3 new files), import-pure headless, gate green, and one falsification finding — the second PC was unpinned (all tests green with deflation disabled); added two pinning tests, red-verified (corr=1.0) then 30/30 green. Worker's flagged retention.USER_FILES mutation reviewed: same-value write in production, acceptable for D1, but D2 should thread user_files as a real parameter into retention.load_matches instead. D2 notes: 8.2s projection on 4000x768 under python3.9-without-sumprod means the graph build MUST run on a QueryOp worker, never the main thread (Anki's own 3.13 has math.sumprod, so live timing will be much better — still off-thread).

### K-072: Tear-off/re-dock SIGSEGV: reparent runs inside mouse-event delivery
owner: opus
priority: P2
tags: library-era
files: klausmate/__init__.py
verify: grep -q "_defer_placement" klausmate/__init__.py && ! grep -nE "^ +self\._embed\(zone\)$" klausmate/__init__.py
created: 2026-08-24
claimed: 2026-08-24

Pouya's reproduction (exact): float the PDF panel OUT of the window, then dock it back IN -> SIGSEGV in sipSubClass_QPdfView during QApplication event-filter delivery of a mouse event. Same signature as the K-068 crash but a DIFFERENT trigger, and K-068's close-time hide cannot help here.

Root cause (traced, not guessed): _finalize_drag -> self._embed(zone) is called SYNCHRONOUSLY from inside eventFilter (app-filter release/press/buttonless-move at ~:1260-1266, bar release at ~:1432), and the manual_ghost drop path calls _embed/_tear_off inline at ~:1424-1428. _embed reparents the panel — with the live QPdfView inside it — from a floating top-level window into the host splitter. Reparenting across native windows destroys and recreates the widget subtree's native handles WHILE Qt is mid-delivery of a mouse event through the application-level filter; the next event's receiver pointer is then dangling, and sip segfaults converting it to a Python object before any of our Python code runs (so no try/except can catch it). This is the CLAUDE.md 'never reparent mid-mouse-gesture' gotcha resurfacing at drop time rather than pickup time.

FIX: add a _defer_placement(fn) helper that schedules placement work via QTimer.singleShot(0, ...) with a liveness guard (skip if self._closed or the C++ object is gone — catch RuntimeError), and route EVERY placement call that can originate inside event delivery through it: both _embed and _tear_off in the manual_ghost drop, and _embed in _finalize_drag. The event returns to Qt first, the filter stack unwinds, the app filter is already removed by _reset_drag (which runs BEFORE the deferred work), and only then does the reparent happen with no event in flight.

Keep _reset_drag's ordering: filter removal must still precede the deferred placement. Do not defer _make_floating calls that happen outside event delivery (panel_show's initial placement at ~:945/:1036) — those are already safe and deferring them would flash an unplaced panel.

Headless verification is impossible for a native use-after-free; live check is Pouya repeating his exact reproduction several times, plus a re-dock on each of the four zones.

#### Comments
- [2026-08-24 opus] Committed fca2e41. Gate PASS, compile ok, full suite green. Honest confidence: the mechanism is traced end-to-end (synchronous reparent inside eventFilter -> dangling receiver -> sip conversion crash before any Python runs) and the fix removes it structurally, but like K-068 this is a native use-after-free no headless test can prove. Live check: float out, dock back in, repeated across above/below/left/right, plus a float-to-float move. Remaining known synchronous reparent is _start_panel_drag's tear-off, which startSystemMove requires — documented in the commit, not implicated in this crash.

### K-070: Library root directory, part A: storage root + migration (K-057)
owner: opus
priority: P2
tags: sonnet-safe,library-era
files: klausmate/pdf_handler.py,klausmate/setup_flow.py,klausmate/manage_models.py,tests/test_klausmate.py
verify: grep -q "library_root" klausmate/pdf_handler.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_klausmate.py
created: 2026-08-24
claimed: 2026-08-24

Part A of Pouya's K-057 (directory-backed library). DESIGN (agreed):
a real filesystem directory becomes where library PDFs LIVE; the Library
tree and tags mirror it. This card ships the storage half only — root
config, path resolution, migration, and the two UI touchpoints. Part B
(disk<->tree mirroring, rename/move sync, rescan) is a later card on
pdf_drive/tag_sync — do NOT touch those files.

1. Config key library_root (absolute path, addon config). New pdf_handler
   helpers: get_library_root(cfg) -> str|None, and a single resolution
   choke point — pdf_path_for must consult a persisted mapping
   safe_name -> path-relative-to-root (stored in user_files/
   library_map.json via _atomic_write_json) and fall back to the legacy
   pdfs/<safe>.pdf location when unmapped. EVERY consumer already routes
   through pdf_path_for — verify that claim with a grep before relying on
   it, and fix any caller that hardcodes pdfs/ paths.
2. Migration (pdf_handler.migrate_to_root(user_files, root, folders)):
   for each stored PDF, move pdfs/<safe>.pdf ->
   <root>/<drive.json folder path>/<display name>.pdf. Per-file guarded
   and RESUMABLE: never overwrite an existing destination (append a
   numeric suffix), write the mapping entry only after a verified move
   (size match), leave the source untouched on any failure, keep going on
   per-file errors. contexts/, pdf_originals/, annotations/ are Klaus-
   private and STAY under user_files keyed by safe name — only the baked
   pdfs/ copies relocate. bake_annotations regenerates into the MAPPED
   path — its tmp file must be created in the destination directory so
   os.replace stays same-filesystem (existing pattern, preserve it).
3. setup_flow: when library_root is unset, the per-profile-open readiness
   check adds a step prompting to choose the folder (QFileDialog
   directory picker) and then runs the migration with a progress-safe
   CollectionOp-free QueryOp (no collection involvement). Decline =
   ask-again-next-profile-open, never nag twice per session.
4. manage_models General tab: a 'Library folder' row showing the current
   path with a Change... button — changing re-runs migrate_to_root from
   the old root to the new one (same per-file rules).

SAFETY, absolute: never write to the REAL klausmate/user_files/ in tests
or verification — a deny rule enforces this. All tests use scratch
directories with synthetic files. The migration code itself must be pure
enough to test that way (pass user_files and root as parameters, no
module-global path reads inside the move loop).

TESTS (tests/test_klausmate.py, insert ABOVE the print(summary)/sys.exit
tail): mapping round-trip; unmapped fallback to legacy path; migration
moves+maps; collision suffixing; failure mid-list leaves earlier moves
mapped and later sources untouched; re-run resumes; pdf_path_for after
migration resolves to the root path.

#### Comments
- [2026-08-24 sonnet-ax] Decisions: pdf_path_for(user_files_dir, name, root=None) keeps its 2-arg call sites (pdf_viewer.py, __init__.py) working unchanged — a new optional root= param lets tests bypass aqt entirely, while production falls back to a guarded _live_library_root() (lazy `from aqt import mw`, try/except) reading cfg["library_root"] via mw.addonManager.getConfig(__package__). Extracted the shared resolution logic into _working_pdf_path() (returns the intended path even when it doesn't exist yet) so bake_annotations's `working` var uses the SAME choke point instead of hardcoding pdfs/ — its tmp-file/os.replace pattern was already derived from os.path.dirname(working) so no other change was needed there. migrate_to_root(user_files_dir, root, folders=None) takes folders shaped exactly like drive_store.load(...)["pdfs"] (safe -> {folder, display}) so it's a pure function a test can drive with a hand-built dict — no drive_store import inside pdf_handler.py. Resumability is achieved by checking "is safe already mapped AND does that mapped file exist" before touching anything for that PDF, rather than a separate journal. Extra fix beyond the card text, flagging per the card's own instruction #1 ("fix any caller that hardcodes pdfs/ paths"): delete_context in pdf_handler.py itself was hardcoding pdfs/<safe>.pdf as one of its removal candidates — after a migration that's not where the real file lives anymore, so a delete would silently orphan the actual PDF in the Library folder. Fixed it to also pop the safe's library_map.json entry and delete the mapped file when one exists. This is pdf_handler.py-internal, stayed in scope. setup_flow.py: added _library_root_check(), called from the top of setup_readiness_check() (right after the _first_run_dialog_shown_this_session early-return, so it's skipped on the very first profile-open alongside the welcome dialog, then runs on every one after). askUser() explains why, then QFileDialog.getExistingDirectory() picks the folder; migration runs via QueryOp(...).without_collection().run_in_background(), matching the file's existing ensure_server pattern. Decline persists nothing, so it re-asks next profile-open — no "stop nagging forever" flag, by design (an unset Library folder is a state worth re-surfacing). manage_models.py: smallest addition I could make — one QHBoxLayout row (label + path QLabel + 'Change…' button) inserted into the existing General QGroupBox right after runtime_auto_cb, one change_library_folder() handler placed next to save_general()/test_connection(), one line added to set_busy()'s widget tuple, one .clicked.connect() added to the existing end-of-function dispatcher block. No other line in that file touched. Files: klausmate/pdf_handler.py (load_library_map/save_library_map/get_library_root/_live_library_root/_working_pdf_path/pdf_path_for/_library_filename/_unique_path/migrate_to_root added; bake_annotations and delete_context updated to route through the mapping). klausmate/setup_flow.py (_library_root_check added; wired into setup_readiness_check; showWarning added to the aqt.utils import). klausmate/manage_models.py (Library folder row + change_library_folder() + set_busy/dispatcher wiring). tests/test_klausmate.py (31 new checks in a new "library root + migration (K-070)" section, inserted above the print(summary)/sys.exit tail; scratch tempfile.mkdtemp() dirs only, never touches klausmate/user_files/). Risks: _live_library_root()'s aqt lookup is exercised by NEITHER the automated suite nor a real Anki restart yet — every test that needs migrated-path resolution passes root= explicitly, so the live mw.addonManager.getConfig(__package__) path is currently unverified beyond code review. The mid-migration failure/resume tests simulate a disk error by monkeypatching pdf_handler.shutil.copy2 (restored in finally) rather than a real IO fault — worth a skeptical read since it's global-module patching, even though scoped narrowly. _library_filename()'s sanitizing (replace '/' and '\\', strip leading dots) is a defensive addition beyond literal card text — no test exercises a display name containing a slash specifically, only the collision-suffix path was tested end-to-end. Live-only checks for Pouya's restart queue (none of this is exercised by the headless suite): (1) first-time setup prompt — profile open with library_root unset should show the askUser() explanation, then a real QFileDialog folder picker, then a tooltip on completion; decline should re-prompt on the NEXT profile open, not nag again this session. (2) Preferences -> General -> Library folder row: initial label should read "Not set — PDFs stay inside the add-on" pre-migration, update to the real path after either the setup prompt or "Change…" completes. (3) Actual migration against a real user_files/pdfs/ store with a real drive.json — confirm PDFs land under <root>/<folder>/<display>.pdf, the sidebar/viewer (pdf_viewer.py's load_pdf, __init__.py's pdf_path_for call) still opens them post-migration, and bake/un-bake (highlighting a migrated PDF) still writes into the new location. (4) "Change…" from an already-migrated root to a second new root (root-to-root move, not just unset-to-root). Verify: `grep -q "library_root" klausmate/pdf_handler.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_klausmate.py` exits 0. 113 passed, 0 failed (baseline before this card: 82 passed). Real tail of the run: ok re-run completes the previously-failed file ok re-run skips already-migrated files instead of re-moving them ok resumed file is now mapped ok resumed file's legacy source is finally removed 113 passed, 0 failed Next: Part B (disk<->tree mirroring, rename/move sync both directions, rescan on profile open, tag follow-through) is filed separately per the card's own note, touching pdf_drive.py/tag_sync.py/drive_store.py — none of which this card touched.
- [2026-08-24 opus] REWORK (review finding, reproduced in scratch): change_library_folder promises old-root -> new-root but migrate_to_root only moves LEGACY pdfs/ sources. After a first migration to root A, changing to root B reports the PDF as 'skipped', the mapping rel resolves against B where nothing exists, pdf_path_for returns None, and the file sits stranded in A — every already-migrated PDF becomes unopenable on a folder change. Repro: migrate to A (moved), migrate same store to B (skipped), pdf_path_for(root=B) -> None, file present in A. Fix in migrate_to_root: accept old_root: str|None = None; when a mapping entry's file is absent under the NEW root but present under old_root/rel, move it old->new under the same collision/verify/map-then-delete discipline, updating the mapping rel. change_library_folder passes old_root; setup_flow's first-time call passes None. Falsifying test FIRST (mirror the repro above; must be RED on the current commit), then fix, then re-run the full gate.
- [2026-08-24 opus] Rework done by opus (worker stopped by host restarts 3x). Red-then-green honored: change-root test written first (failed on the missing parameter), six checks red with the fix disabled, 124/124 green with it; full suite 68/57/60/22/124/30/121. Verify gate PASS. NOTE FOR POUYA — a deliberate behavior now pinned by test: if the folder you point the Library at already contains a file at a PDF's mapped relative path, Klaus ADOPTS that file rather than overwriting or duplicating it, and the original stays in the old folder. That is required for resumable migrations (an interrupted run leaves files exactly there) and cannot be told apart from a stranger's same-named file without hashing. Say the word if you would rather it suffix instead.
- [2026-08-24 opus] Signed off. LIVE CHECKS still owed on next restart: first-run folder prompt appears and migrates; Klausmate Preferences > General shows the Library folder row; Change... moves an existing library between folders and every PDF still opens afterwards; baked annotations write to the new location. Part B (disk<->tree mirroring, rename/move sync, rescan) still to be filed against K-057.

### K-073: K-057 part B: two-way folder sync + single-copy invariant
owner: opus
priority: P2
tags: library-era
files: klausmate/pdf_handler.py,klausmate/pdf_drive.py,klausmate/__init__.py,klausmate/tag_sync.py,tests/test_klausmate.py
verify: grep -q "plan_rescan" klausmate/pdf_handler.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_klausmate.py
created: 2026-08-24
claimed: 2026-08-24

Pouya (live, after part A): Anki->folder works, folder->Anki does not — moving files in Finder must sync back. Plus the single-copy invariant: the PDF in the root folder IS the PDF Anki opens, never a second copy. Design: rescan on profile open + Library refresh (mirrors K-054 tag reconcile): walk the root, diff against library_map; a missing mapped file matches a new unmapped file by unique basename, else by the exactly-one-missing/exactly-one-new rule (same confidence philosophy as plan_reconcile — ambiguity reports and does nothing). Confirmed moves update mapping rel + drive_store folder/display + tag sync follows. Mapped-but-deleted files are reported, never data-deleted. New unmatched PDFs dropped into the folder are ingested in place (context extracted, drive entry, mapping — no copy). Single copy: with a root set, imports write directly into the root; rescan also re-runs migrate_to_root to sweep any legacy pdfs/ stragglers. pdf_originals stays internal (bake machinery, not a viewable duplicate — flag to Pouya). Opus-owned.

#### Comments
- [2026-08-24 opus] Committed f5797f7. 30 new checks, 151/151 in file, full suite green; falsification: ambiguity guard disabled = 2 red. Design notes pinned by test: (1) moving files in Finder syncs folder+name back into the tree and tags; (2) simultaneous multi-file rename+move batches are AMBIGUOUS and untouched — resolve one at a time; (3) deleting a file in Finder reports it missing but never deletes Klaus data (annotations/context/index survive; re-add the file and everything reconnects); (4) dropping a PDF into the folder ingests it in place, no copy; (5) imports with a root set write straight into the root, re-imports replace in place. pdf_originals/ deliberately stays as the internal pristine baseline for annotation baking — not a viewable duplicate.

### K-074: Rescan reconciles tree to mapping unconditionally (K-073 live fix)
owner: -
priority: P2
tags: library-era
files: klausmate/pdf_handler.py,klausmate/pdf_drive.py,tests/test_klausmate.py
verify: grep -q "tree_changed" klausmate/pdf_handler.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_klausmate.py
created: 2026-08-24

#### Comments
- [2026-08-24 opus] Committed 9b4a2a6, filed retrospectively (fix shipped in the same turn as the diagnosis). Diagnosed from real data: mapping synced at 17:42 by migration, tree rewritten at 18:08 by the stale-tag reconcile, moves-only loop permanently unable to repair. Fix: tree follows mapping for every mapped entry; tags follow tree_changed. Pouya's stale tree self-heals on next Library open/refresh — no manual cleanup needed. Falsified (3 red on the old loop); suite 156 in file, all green.

### K-075: Two-way sync DOA fix + Anki-side file moves + live watcher (K-075)
owner: -
priority: P2
tags: library-era
files: klausmate/pdf_handler.py,klausmate/pdf_drive.py,tests/test_klausmate.py,tests/test_drive.py
verify: grep -q "^import os" klausmate/pdf_drive.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_drive.py
created: 2026-08-24

#### Comments
- [2026-08-24 opus] Committed dec0195, filed retrospectively (diagnosed and fixed in one turn from Pouya's third live report). Root cause of ALL three no-sync rounds: pdf_drive missing 'import os' — the K-073 glue NameError'd inside its own failure guard on every call, invisible. Regression trap added at the glue layer (verified red on the recreated bug); fleet-wide AST name sweep clean. Also shipped: Anki-side moves/renames now move the real file (disappearing-move fix), live QFileSystemWatcher sync while the Library is open, PDFs no longer render as drop targets. Temp rescan breadcrumbs stay in until Pouya confirms.

### K-076: Library window: live repaint + folder drag/rename moves disk (view desync)
owner: -
priority: P1
tags: orchestrator
files: klausmate/pdf_drive.py,tests/test_drive.py
verify: python3 tests/test_drive.py && python3 tests/test_klausmate.py
created: 2026-08-24

Live report after K-075: data-side sync now WORKS (breadcrumbs show quiet
rescans), but the OPEN Library window never repaints — Pouya must close and
reopen the tab to see any change. Also folder drags vanish from the view
until reopen.

Root causes (verified by reading pdf_drive.py):
1. `_refresh_rows` (the watcher/refresh target) runs rescan + tag reconcile
   but NEVER calls `rebuild_tree()` — drive.json updates, the tree widget
   doesn't. Reopen rebuilds, hence "works after reopen".
2. `_LibraryTree.dropEvent` rejects folder drags outright ("out of scope"),
   and Qt InternalMove can still remove the dragged row on macOS even for
   ignored/accepted-noop drops -> folder disappears from the VIEW (data
   intact, back on reopen). Same latent hole: accepted same-folder PDF drop
   (line ~238) rebuildless -> row removed.
3. Context-menu folder RENAME (`_rename_folder`) never moves the directory
   on disk (`rename_mapped_folder` has ZERO callers) — with live repaint it
   would visibly snap back on the next rescan.
4. Watcher is per-window — "live all the time" needs it module-level so
   tags keep syncing while the Library is closed.

Work:
- `_refresh_rows` calls `rebuild_tree()`; rebuild preserves folder
  expansion + scroll + selection so frequent rebuilds are visually stable.
- Folder drag-and-drop implemented: pure `plan_folder_move(old, dest)`
  (illegal = into itself/own subtree/no-op), `apply_folder_change(uf, root,
  old, new)` module-level (disk dir move via rename_mapped_folder + store
  rename; refuses when destination occupied; tree-only folders rename
  store-only). `_rename_folder` routes through the same apply path.
- dropEvent: every path ends IgnoreAction-accepted + next-tick heal
  rebuild, so Qt can never eat a row.
- Module-level QFileSystemWatcher (parented to mw, armed/re-armed inside
  rescan_library_root); window open -> _refresh_rows, closed -> bare rescan.
  Per-window watcher removed.

Verify: python3 tests/test_drive.py (new plan_folder_move +
apply_folder_change + survives-rescan trap; RED against current tree) &&
python3 tests/test_klausmate.py. Falsify: disable the disk half of
apply_folder_change -> survives-rescan test must go red.
Live checks (Pouya): Finder move updates OPEN window ~1s; folder drag in
Library moves dir on disk and sticks; folder rename sticks; nothing
disappears without reopen.

#### Comments
- [2026-08-24 orchestrator] Signed off (orchestrator, self-executed). Root causes verified in code + live breadcrumbs: (1) _refresh_rows never rebuilt the tree — data synced, view stale until reopen; (2) folder drags rejected while Qt InternalMove still removed the row from the view; (3) context-menu folder rename was store-only (rename_mapped_folder had zero callers) so the disk-truth rescan reverted it. Fix: refresh rebuilds (expansion/selection/scroll preserved), folder drag+rename share apply_folder_change (disk dir + store + mapping, merge-refusing), every drop path ends IgnoreAction+heal-rebuild, watcher is module-level so sync is live with the window closed. Falsified: disk half disabled -> survives-rescan test red with the exact live revert. 82+165 green, AST sweep clean. Commit 20a5b5f. Live checks owed: Finder move updates open window ~1s; folder drag sticks; nothing disappears.
