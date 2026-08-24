# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

### K-054: Tag renames flow back to the PDF (reverse direction of K-053)
owner: -
priority: P1
tags: sonnet-safe,library-era
files: klausmate/tag_sync.py,klausmate/pdf_drive.py,tests/test_tag_migrate.py
verify: grep -q reconcile_from_tags klausmate/tag_sync.py && env QT_QPA_PLATFORM=OFFSCREEN true; grep -q reconcile_from_tags klausmate/tag_sync.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_tag_migrate.py
created: 2026-08-24

BLOCKED until K-053 is Done — same files. Pouya's invariant is bidirectional: 'the PDF should always follow the names of the tag, those two are always the same.'

Add tag_sync.reconcile_from_tags(col): for each prefs entry with a stored 'tag', if that tag still exists -> nothing. If it is GONE and exactly one unrecognized !Library:: tag exists that is not any PDF's stored tag and not a reserved leaf -> treat as a rename made in Anki's tag sidebar: update the PDF's display name (leaf, _ -> space) and folder path (parents) via drive_store, store the new tag. AMBIGUOUS cases (multiple missing, multiple candidates) -> enforce the forward direction instead: reapply the PDF-derived tag, log why. PDF wins ties because our side is deterministic.

Run it on profile open (register next to tag_migrate's hook — __init__.py is NOT in your files; state the one-line registration as owed) and at the top of DriveWindow._refresh_rows so opening/refreshing the Library picks up sidebar renames.

CAVEAT to encode in copy+tests: the mapping is lossy — spaces become _ in tags, so a genuine underscore in a display name round-trips to a space. Accept and document; do not build an escaping scheme.

Same safety/verify regime as K-053. Full suite green; py_compile via symlink; stage by path.

## Ready

## Doing

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

## Review

## Done
