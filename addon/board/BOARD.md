# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

## Ready

### K-050: user_files/README.txt: ships to users but is untracked, and still describes autocomplete
owner: -
priority: P2
tags: needs-human,audit
verify: human confirms the file is tracked and its text matches the current product
created: 2026-08-23

Two problems with klausmate/user_files/README.txt, found while closing K-047.

1. CONTENT: it still says the folder holds 'Extracted PDF text (lecture slides) used as context for completions' and 'Per-deck context overrides'. Completions are deleted; per-deck context overrides never shipped. The real contents are pdfs/, pdf_originals/, annotations/, contexts/, card_index/, pdf_index/, drive.json, pdf_tabs.json — and it should warn that deleting anything there is permanent, since Klaus keeps no second copy.

2. THE ACTUAL BUG: the file SHIPS (scripts/package.sh copies it into every .ankiaddon) but is NOT TRACKED (git ls-files klausmate/user_files/ is empty — the .gitignore rule that protects Pouya's personal data also excludes this template). So a file every user receives drifts with no review and no history. That is the part worth fixing properly.

NEEDS-HUMAN because editing it requires either Pouya doing it, or an explicit exception to the user_files deny-rule in .claude/settings.json — a rule that is otherwise load-bearing (it holds ~459MB of personal PDFs, annotations, and the 28,668-note index, and it correctly blocked ME from editing this file while closing K-047).

SUGGESTED FIX, for Pouya's call: move the template OUT of user_files — keep it at klausmate/user_files_README.txt (tracked, reviewable) and have package.sh copy it to user_files/README.txt at build time, exactly as it already does mkdir + cp for that directory. Then the shipped text is version-controlled and the deny-rule stays absolute with no exception.

#### Comments
- [2026-08-23 Pouya] Do the suggested fix

### K-051: Finish the recency + drop-filter unification in __init__.py
owner: -
priority: P2
tags: sonnet-safe,library-era
files: klausmate/__init__.py
verify: grep -q list_by_recency klausmate/__init__.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_klausmate.py
created: 2026-08-23

Two small leftovers K-049 correctly reported as owed rather than reaching outside its file scope. Both are in klausmate/__init__.py.

1. The _PdfTabContainer ＋ menu still re-derives its own recency order with a private _recency helper that reads pdfs/<safe>.pdf's mtime. That mtime is PRESERVED from the source file by shutil.copy2, so a lecture authored in 2019 and imported today sorts last. K-049 built pdf_handler.list_by_recency() for exactly this — it ranks by last_used and falls back to contexts/<safe>.txt, which is written fresh at import and therefore means ingest time. Swap the call and delete the private helper. deck_curate.py already uses the shared one, so after this both menus agree.
   While you are there: the two menus also LABEL PDFs differently — deck_curate shows drive_store.display_name, this menu shows the raw safe basename, so the same PDF reads as 'Renal_Phys' in one place and 'Renal Physiology (Dr. K).pdf' in the other. Use the display name here too.

2. _PdfBar's drag-and-drop filter checks only the .pdf suffix; deck_curate checks the suffix AND os.path.isfile. A directory named foo.pdf dropped on the editor bar reaches import_pdf_file; dropped on the deck screen it does not. Align on the stricter form.

Neither is user-visible as a crash — they are consistency bugs — but the recency one produces a menu that is simply wrong about which PDF you used last.

Full suite green (257 across 6 files); py_compile through the Anki symlink; stage by path.

## Doing

### K-052: Preferences panel: tabs, and a control for the default sensitivity
owner: sonnet-aq
priority: P0
tags: sonnet-safe,library-era
files: klausmate/manage_models.py,klausmate/retention.py,tests/test_dialog_logic.py
verify: grep -q QTabWidget klausmate/manage_models.py && grep -q _threshold_user_set klausmate/retention.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && python3 tests/test_dialog_logic.py
created: 2026-08-23
claimed: 2026-08-23

Pouya: 'add default sensitivity to the Preferences Panel, also feel free to add tabs to the preferences panel'.

CONTEXT. The dialog (manage_models.manage_models_dialog, 1276 lines) is a QStackedWidget: page 0 is the Ollama install page, page 1 is one long scroll holding three QGroupBoxes — Semantic search (:265), Local model library (:331), General (:373, the two toggles plus the Test connection / Clear library tag maintenance buttons). It was renamed to Klausmate Preferences and is now the single Tools entry, so everything lives here and the page is getting long.

1. TABS. Turn page 1 into a QTabWidget. Suggested split — adjust if you see better, and say why: 'Semantic search' (provider, model, key, index status + Index cards now, default sensitivity), 'Models' (the local library list and pull row), 'General' (the two toggles + maintenance buttons). KEEP the QStackedWidget: the install page is a MODE, not a tab — a user with no Ollama should not see tabs offering settings that cannot work yet. Only page 1 becomes tabbed.

2. DEFAULT SENSITIVITY CONTROL — the actual ask. There is currently NO UI anywhere for the global default; pdf_match_threshold is config-file-only (grep confirms: only retention.py reads it). Add a control for it in the Semantic search tab. A QSlider matching the Library's per-PDF dialog is the consistent choice (that one is range 20-80 = 0.20-0.80, in pdf_drive._on_threshold) with the live value shown as text; a QDoubleSpinBox is acceptable if you justify it. Default is now 0.75.

   LABEL IT SO IT CANNOT BE CONFUSED WITH THE PER-PDF VALUE. This sets the starting point for PDFs that have no override of their own; each PDF can still be tuned individually in the Library, and that override always wins. Say that in a caption. Getting this wrong means a user thinks they changed one PDF when they changed the default, or vice versa.

3. THE CORRECTNESS WRINKLE, and the reason retention.py is in your files. retention._migrate_default_threshold carries a stored value forward when the shipped default changes, treating any value in _SHIPPED_DEFAULTS (0.35, 0.55, 0.75) as inherited rather than chosen. That was safe while the value was config-file-only. Once a UI exists, a user can DELIBERATELY pick 0.55 — and the next default bump would silently overwrite their choice because it looks like an old default.
   Fix: add a _threshold_user_set boolean, set it to True whenever the value is changed through this new control, and make _migrate_default_threshold return immediately when it is set. Add a test for exactly that: user-set 0.55 survives a later default bump. Do not remove the existing seven migration tests.

4. Saving: follow the dialog's established pattern — immediate save on change, guarded by ui_state['syncing'] so programmatic repopulation never writes. Do NOT introduce an OK/Apply button; nothing else here has one.

PRESERVE: the single-connect fix-button dispatcher (_embed_fix_kind / on_embed_fix_clicked — Qt connects accumulate, this is deliberate), the per-provider key placeholders, _needs_local_runtime's install-page gating, and the K-039 index-safety behaviour (empty-model resolution + confirm-before-rebuild).

tests/test_dialog_logic.py hand-transcribes this dialog and must keep passing; extend it for the new control. Qt cannot instantiate headlessly here, so you CANNOT see the tabs — do not claim you verified appearance. py_compile through the Anki symlink. Full suite green (264 across 6 files). Stage by path.

Done when: verify passes, the panel is tabbed with the install page still a separate mode, the default sensitivity is settable and clearly distinguished from per-PDF overrides, and a user-set value survives a future default bump.

#### Comments
- [2026-08-23 orchestrator] HARD REQUIREMENT added to part 3 (Pouya asked specifically that this bug be dealt with properly, and the fix has a failure mode worse than the bug). _threshold_user_set must be set ONLY by a human moving the control, never by the code populating it. sync_embed_widgets repopulates widgets programmatically (manage_models.py ~:833-884) — that is what ui_state['syncing'] is for, and why save_embed bails on it at ~:960. A flag wired to a naive valueChanged handler would be stamped True on every profile the first time the dialog opens. Nothing would look broken; the value stays correct and the tests still pass. But every one of those users is then permanently excluded from future default migrations, with no symptom until a new default ships and silently reaches nobody. That is worse than the original bug: this one overwrites a rare deliberate choice, that one disables the mechanism for everyone. So: write the flag on the save path behind the syncing guard; only when the value actually differs from what is stored; and prefer sliderReleased/editingFinished over live valueChanged so a drag does not write config per pixel. Required tests: (1) programmatic repopulation does NOT set the flag — the regression above, and the most important one; (2) open-and-close without touching anything writes nothing; (3) a user-set value survives a later default bump; (4) an untouched inherited value is STILL carried forward, proving the false-positive fix did not break the feature. test_dialog_logic.py already has a syncing-guard test modelling this concept for the other widgets — follow its shape.

## Review

## Done
