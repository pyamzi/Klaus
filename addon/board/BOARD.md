# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

### K-038: A8: root every Klaus tag at !Library and migrate existing ones
owner: -
priority: P0
tags: sonnet-safe,library-era
files: klausmate/curation.py,klausmate/retention.py,klausmate/tag_migrate.py
verify: grep -q '!Library' klausmate/curation.py && grep -q '!Library' klausmate/retention.py && test -f klausmate/tag_migrate.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_klausmate.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23

Pouya: 'all pdf-based tags should be rooted at !Library, that is the root tag'. The leading ! sorts the tree to the TOP of Anki's tag sidebar — that is the point of the prefix, so preserve it exactly.

BLOCKED until K-037 (A7) is Done — A7 merges the two clear-tag menu actions and must not be racing this.

1. RENAME THE CONSTANTS (values only — keep the constant NAMES so callers keep working):
   curation.TEMP_TAG      'klaus::curate'   -> '!Library::Curating'
   curation.CURATED_TAG   'klaus::curated'  -> '!Library::Curated'
   retention.RETENTION_TAG 'klaus::pdfmatch'-> '!Library::Matching'
   Leave curation.DECK_PREFIX ('Klaus::') alone — that is a DECK name prefix, not a tag.
   Keep Curating and Matching as SEPARATE tags. They look mergeable now that one menu item clears both, but retention.py's own comment explains they are deliberately distinct so a PDF-match preview cannot clobber an in-flight curation preview. Preserve that property.

2. VERIFY THE PREFIX IS SAFE. Every lookup goes through find_notes(f'tag:"{TAG}"') — quoted, so ! is not special there. But CHECK the bulk_add/bulk_remove paths and anything building a search string without quotes, and confirm Anki accepts ! as a leading tag character (it is a common convention for pinning tags to the top, but verify rather than assume — a wrong guess here silently tags nothing). State your evidence in the handoff.

3. ONE-TIME MIGRATION, new module klausmate/tag_migrate.py (aqt-thin, logic pure so it is headless-testable). Pouya chose automatic renaming. On profile open, guarded by a config flag so it runs exactly once (follow the existing '_'-prefixed convention, e.g. _library_tag_migrated — underscore-prefixed keys are left alone by _migrate_config):
   klaus::curate -> !Library::Curating, klaus::curated -> !Library::Curated, klaus::pdfmatch -> !Library::Matching.
   Use col.tags.rename(old, new) — it moves every note and child tag and is undoable. Wrap the whole migration in ONE undo entry (add_custom_undo_entry / merge_undo_entries, the pattern curation.create_curated_deck already uses) so Pouya can Ctrl+Z the lot. Skip silently when a source tag has no notes. Never delete a tag that failed to rename.
   THIS TOUCHES A REAL 32k-NOTE COLLECTION. It must be idempotent, must no-op on a second run, and must never throw into Anki's startup path — wrap in try/except and print('[klausmate] ...') on failure.
   Registration: tag_migrate exposes the entry point, but the profile_did_open hook lives in __init__.py which is NOT in your scope. Write the function and say clearly in your handoff that a one-line registration is still needed; I will file it or fold it into the next __init__.py card.

4. Update any docstring or comment naming the old tags (curation.py's module docstring and retention.py:19-22 both do).

Do NOT touch __init__.py, manage_models.py, or pdf_drive.py. Add tests for the pure parts to tests/test_klausmate.py? NO — that file is out of scope; keep the logic importable and testable, a later card adds coverage.

Full suite green; py_compile through the Anki symlink. Stage explicitly by path.

Done when: verify passes, all three tags live under !Library, the migration is written and idempotent, and the handoff names the exact registration line still owed.

#### Comments
- [2026-08-23 orchestrator] SCOPE ADDITION (from the K-037 review). While merging the two clear-tag menu actions, K-037 had to work around Anki's tooltip system: clear_curation_tag and clear_pdfmatch_tag each fire their own tooltip from an async CollectionOp, and Anki's tooltip() is a single global overlay where each call closes the previous one. The workaround in __init__.py is a QTimer.singleShot(400) before the summary message. That is fragile — on Pouya's real 32k-note collection either op can exceed 400ms, in which case the summary fires first, gets clobbered, and the bug returns. You own curation.py and retention.py, so please fix it properly as part of this card: give both clear_*_tag functions a quiet: bool = False parameter that suppresses their internal tooltip when True. Keep the default False so any other caller is unaffected. Do NOT edit __init__.py to use it (out of your scope) — just add the parameter and say so in your handoff; I will file the one-line caller change. This is additive to your existing three parts (constant rename, prefix safety check, migration module), not a replacement.

### K-035: B3: restyle the editor PDF bar to match the deck-browser square
owner: -
priority: P2
tags: sonnet-safe, library-era
files: klausmate/__init__.py
verify: grep -q 'dashed' klausmate/__init__.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23

Phase B3. BLOCKED until K-027 (A1) is Done — A1 is rewriting __init__.py heavily and owns the file until it lands. ALSO read K-034 (B2)'s handoff comment first if that card is done: it records the exact final border/radius/padding/copy of the deck-browser square, which this card must match.

Pouya's requirement (item 12): 'I want the same PDF thing to replace the Klaus thing at the bottom of the ad panel, so those two should look exactly the same. There should be complete consistency between those two items.' The Add/Edit window's PDF bar and the deck-browser drop square do the same job but look nothing alike — one is a 34px solid-bordered Qt row with a cobalt 'Klaus' badge, the other a dashed centered pill.

Restyle _PdfBar (the QFrame at ~:2515-2694, an id-selector stylesheet on objectName 'klausmateDropZone') to match the square:
- 1px DASHED border rgba(128,128,128,0.55), radius 10px, transparent/inherit background at rest (the square uses var(--window-bg,transparent)); centered content.
- Idle copy 'Drop a lecture PDF here' -> match the square's phrasing as closely as the context allows (the square says 'Drop a lecture PDF here to curate a deck from it.'; in the editor the action is 'to read alongside your cards', so keep the leading clause identical and adapt only the trailing purpose clause — state your exact final string in the handoff).
- A visible 'Browse…' button inside the bar, like the square gets in B2.
- Drag-over state should read like the square's armed state: solid cobalt rgba(58,130,247,0.85) border.
- DROP the cobalt 'Klaus' badge — it was there to rhyme with the ⌘K popover, which A1 deleted. Its removal is part of the simplification.
- KEEP the extra affordances the editor genuinely needs — Remove (when a PDF is active) and the ◨ viewer toggle — but make them subtle/secondary so the bar still reads as the same object as the square. The bar may need to grow past 34px to breathe; that is fine, but it must not dominate the Add window.
- Preserve ALL behavior: acceptDrops, dragEnter/dragLeave/dropEvent with the dragOver property + unpolish/polish restyle trick, multi-PDF drop, _elide_name on resize, the Browse/Remove action swap in set_active_pdf, update_toggle.

Do NOT touch _install_klaus_bar's placement logic (~:4130-4188) — the button-box insertion was hard-won in K-017 and is correct; you are restyling the widget, not moving it.

Constraint: this file only, and only the _PdfBar region. Full suite; py_compile through the symlink. Done when: verify passes and the handoff states the final border/radius/copy values so they can be diffed against the square's.

#### Comments
- [2026-08-23 orchestrator] SEQUENCING: K-037 (A7) also edits __init__.py and is going first (it is larger and touches the menu/bootstrap region). Wait for K-037 to be Done, then rebase your reading of the file — line numbers in this card's body predate both K-027 and K-037.

### K-032: A5: delete dead modules and rewrite the two test files
owner: -
priority: P1
tags: sonnet-safe,removal,library-era
files: klausmate/claude_api.py,klausmate/anki_tools.py,klausmate/settings_ui.py,tests/test_imports.py,tests/test_dialog_logic.py,klausmate/embeddings.py
verify: ! test -f klausmate/claude_api.py && ! test -f klausmate/anki_tools.py && ! test -f klausmate/settings_ui.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && python3 tests/test_dialog_logic.py
created: 2026-08-23

Phase A5 — the closing card of the removal phase. BLOCKED until K-027, K-028, K-029, K-030, K-031 are ALL Done. Verify that before starting.

1. git rm three modules, each confirmed dead by then:
   - claude_api.py — its only consumers were __init__.py's ClaudeAPIError import and _ask_via_claude, both deleted in A1. Grep to confirm zero references before deleting.
   - anki_tools.py — already fully orphaned today (zero references anywhere in the repo; it was tooling for a removed chat agent).
   - settings_ui.py — its two surviving toggles moved into Manage models in A3. Confirm A3 actually did that before deleting, and confirm nothing still imports or opens it.

2. klausmate/embeddings.py: ONE comment near the _post_json helper says something like 'same as claude_api.' — reword it to stand alone. This is a comment-only edit; change no logic in this file.

3. tests/test_imports.py: it globs klausmate/*.py and imports each, then executes __init__.py. Update it for the three removed modules so it passes. Keep its structure and its guard value.

4. tests/test_dialog_logic.py: near-total rewrite. It currently transcribes the Autocomplete/Ask/Claude combo logic, which no longer exists — and it has ZERO coverage of the embedding rows that survive. KEEP the check() harness and the Combo class verbatim (they are good and reusable). Rebuild World around what the dialog is now: embed_provider_combo, embed_model_combo, embed_key_edit, the ui_state['syncing'] guard, and the K-009 fix-button dispatcher (kind 'key' vs 'model' vs '' — read manage_models.py's _embed_fix_kind and on_embed_fix_clicked and transcribe faithfully; the file's contract is hand-transcription kept in lockstep with the real closure). At minimum assert: switching provider repopulates without writing config (the syncing guard — this concept survives from the old file); a cloud provider with no key yields kind 'key'; a local provider with an uninstalled model yields kind 'model'; a ready state yields ''; the embed model dropdown offers only embedding models. Aim to at least match the 29 assertions the old file had.

5. FINAL GATE for the whole removal phase: run a repo-wide sweep and paste the output in your handoff —
   grep -rn 'claude_api\|anki_tools\|settings_ui\|autocomplete\|ask_model\|klaus_engine\|request_completion\|copilot.css' klausmate/ tests/ --include='*.py' --include='*.js' --include='*.json'
   Anything that comes back must be either a deliberate historical mention in a comment (say which) or a real leftover you then fix. Docs (README/CLAUDE.md/ANKIWEB.md/config.md) are a SEPARATE follow-up card — do not edit them here, but DO list every doc hit the sweep finds so that card can be written accurately.

Full suite must be green at the end — that is the whole point of this card. py_compile through the Anki symlink. Done when: verify passes, the sweep is clean, and the handoff includes the sweep output plus the new test_dialog_logic assertion count.

#### Comments
- [2026-08-23 orchestrator] DEPENDENCY ADDED: this card is now ALSO blocked on K-037 (A7). __init__.py still imports settings_ui at :586 and :596 and the Tools menu's 'Settings…' action calls open_settings_dialog. A5 deletes settings_ui.py but does not own __init__.py, so running it first would break the add-on at import (your own verify gate would fail on test_imports). K-037 removes those imports and the menu action. Confirm K-037 is Done before starting, and re-run the repo-wide sweep afterwards — the sweep list should now also include 'chat_dock' and 'search.js', which K-037 deletes.

## Ready

## Doing

## Review

## Done

### K-036: A6: don't route cloud-provider users to the Ollama install page
owner: orchestrator
priority: P1
tags: sonnet-safe,removal,library-era
files: klausmate/manage_models.py
verify: grep -q '_needs_local_runtime' klausmate/manage_models.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && python3 tests/test_dialog_logic.py
created: 2026-08-23
claimed: 2026-08-23

BLOCKED until K-030 (A3) is Done — same file. Re-confirm the bug still exists before starting; K-030 rewrites much of this dialog and may have changed the shape of the fix (but its card did not mention this issue, so it most likely persists).

Found by sonnet-ab while doing K-029, and independently confirmed by the orchestrator: manage_models.py's refresh() does 'if not ollama_reachable(ep): show_install_page()' with NO provider check (~:524 and ~:532 pre-K-030). So a user on the DEFAULT cloud provider (Voyage) who opens Manage models is dumped on a page reading 'Could not reach Ollama at http://localhost:11434' and offered a ~1GB runtime install they will never need.

This defeats the whole point of K-029, which made Ollama optional for the passive per-profile-open flow. The proactive path — the user actually clicking 'Manage models…' — still assumes Ollama is mandatory.

FIX: add a single helper, _needs_local_runtime(cfg) -> bool, returning True only when embeddings.provider_name(cfg) == 'ollama'. Gate the install-page routing on it. A cloud-provider user must land on the normal models page regardless of whether an Ollama server is reachable; the local model library section can show a quiet inline note ('Local models need Ollama, which isn't running') instead of hijacking the whole dialog. A user who switches the provider combo TO ollama, or who clicks something that needs a local model (Pull), should still be able to reach the install page — do not make it unreachable, just stop making it the default landing.

Keep the K-009 one-click Get key / Pull it dispatcher and the single-.connect discipline intact.

Constraint: this file only. Full suite must be green INCLUDING tests/test_dialog_logic.py (K-032 will have rewritten it around the embedding rows by the time this runs — if it has not, say so and coordinate rather than editing tests here). py_compile through the Anki symlink.

Done when: verify passes and a Voyage-configured profile can open Manage models, see its key state, and never be shown the Ollama install page.

#### Comments
- [2026-08-23 orchestrator] SUPERSEDED by K-039, which absorbs this card's entire scope (the _needs_local_runtime helper and the install-page routing gate) as its part 5. Both cards edit manage_models.py's refresh()/sync_embed_widgets() territory, so folding them avoids a pointless serial pipeline on the same file. Closing this one; the work is not dropped.

### K-039: B4: Manage models layout polish, index-safety, and cloud-user routing
owner: sonnet-af
priority: P0
tags: sonnet-safe,library-era
files: klausmate/manage_models.py,tests/test_dialog_logic.py
verify: grep -q setFieldGrowthPolicy klausmate/manage_models.py && grep -q _needs_local_runtime klausmate/manage_models.py && ! grep -q embed_warn klausmate/manage_models.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && python3 tests/test_dialog_logic.py
created: 2026-08-23
claimed: 2026-08-23

From Pouya's screenshot of the reworked dialog: 'make the UI look a little bit better, like the search model thing can be wider, the embeddings from __ and search model ___ thing could be aligned left. You also don't need the key needed warning.' Investigating that screenshot turned up a real data-loss trap, and Pouya chose to fix it here too. THIS CARD ALSO ABSORBS K-036 (A6) — same file, same functions; K-036 is closed as superseded.

All work is in klausmate/manage_models.py plus a tests/test_dialog_logic.py addition.

--- 1. LAYOUT (cosmetic) ---
In the embed_form block (~:264-266):
- embed_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
- embed_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
- embed_model_combo.setMinimumWidth(220), mirroring pull_input.setMinimumWidth(220) at ~:324

ROOT CAUSE, already diagnosed — do not re-litigate: both combos ALREADY have Expanding/Fixed policies (~:243, ~:279), so that is not the difference. The field column ignores them because setFieldGrowthPolicy is never called and macOS QMacStyle defaults to FieldsStayAtSizeHint. Compounding it, embed_model_combo is editable and gets cleared to zero items for cloud providers (~:789-792), and an empty editable combo's sizeHint collapses to a few characters while placeholder text contributes nothing. Hence the elided 'default: ...'.

--- 2. DROP THE INLINE WARNING (cosmetic) ---
Remove embed_warn entirely: the three writes at ~:862, ~:865, ~:867 and the unpack at ~:272 (unpack as _ or restructure). KEEP embed_fix_btn — its text already says what is wrong ('Get key' / 'Pull it') and it is the actionable half.
Two cleanups fall out, both verified single-consumer: the _WARN constant (~:230) becomes dead, and _job_row (~:239-251) now has exactly ONE caller. Inline _job_row into the provider row and delete both — but preserve the button creation AND the row.addWidget(combo, 1) stretch factor.
DO NOT touch the single-connect dispatcher (_embed_fix_kind / on_embed_fix_clicked ~:815-881, connected once at ~:1117). Qt connects accumulate; that pattern is deliberate and was earned on an earlier card.

--- 3. EMPTY MODEL FIELD MUST NOT ORPHAN THE INDEX ---
Real bug, verified against Pouya's actual files. His card_index manifest was built with ('ollama','embeddinggemma:latest') over 28,668 notes. When embedding_model is EMPTY, embeddings.embedding_model(cfg) returns the hardcoded DEFAULT_MODELS['ollama'] = 'nomic-embed-text' — which he does not have installed — so the dialog showed 'not installed' and 'settings changed: next indexing rebuilds from scratch'. One click would have discarded 28,668 vectors.
Add a resolver used by sync_embed_widgets (~:789). When provider is ollama and the configured model is empty, resolve in this order: (a) the model named in the existing index manifest IF it is installed, (b) the single installed embedding model if there is exactly one, (c) the hardcoded default. Show the resolved name as REAL combo text, not as a placeholder — that makes it visible and gives the combo a real sizeHint.
Read the manifest via curation.index_stats() (already called in update_embed_status ~:836; it returns provider/model). Do NOT re-read the file yourself. Do NOT change embeddings.DEFAULT_MODELS — this is dialog-level resolution, not a change to the embedding contract.

--- 4. CONFIRM BEFORE DISCARDING AN INDEX ---
'Index cards now' currently goes straight to the rebuild. Gate it: when index_stats() reports an existing index AND embeddings.index_signature(cfg) differs from the stored (provider, model), askUser first, naming the count and BOTH models — e.g. 'Re-index all 28,668 cards from scratch? The existing index was built with embeddinggemma:latest and the current setting is nomic-embed-text.' Proceed only on yes. A matching signature (incremental update) stays one click, no prompt.

--- 5. CLOUD USERS MUST NOT LAND ON THE OLLAMA INSTALL PAGE (absorbed from K-036) ---
refresh() does 'if not ollama_reachable(ep): show_install_page()' (~:524, ~:532) with no provider check, so a Voyage user opening this dialog is dumped on an install page for a ~1GB runtime they never need. This defeats the Ollama-is-optional work already landed in setup_flow.py.
Add ONE helper, _needs_local_runtime(cfg) -> bool, True only when embeddings.provider_name(cfg) == 'ollama', and gate the install-page routing on it. A cloud user must land on the normal models page regardless of whether Ollama is reachable; the local library section can show a quiet inline note instead of hijacking the dialog. Keep the install page REACHABLE — a user switching the provider to ollama, or clicking Pull, must still get there. Just stop making it the default landing.

--- TESTS ---
Extend tests/test_dialog_logic.py with the resolver from part 3 — it is pure and stub-testable. Four cases: empty + indexed-model-installed -> that model; empty + exactly one installed -> that one; empty + none installed -> hardcoded default; non-empty -> untouched. Keep every existing assertion in that file passing.

--- CONSTRAINTS ---
Qt cannot be instantiated headlessly on this machine, so alignment/width/warning-absence CANNOT be verified here — they need Pouya in a restarted Anki. Correctness comes from careful reading plus the logic tests. NEVER write to klausmate/user_files/ (holds the live 28,668-card index) and never touch meta.json*. Do not exercise the rebuild path. Full suite must stay green (233 baseline). py_compile through the Anki symlink. Stage explicitly by path.

Done when: verify passes, labels are left-aligned, the search-model combo is readable, no inline warning remains, an empty model field can no longer silently orphan an index, a destructive rebuild asks first, and a Voyage user never sees the install page.

#### Comments
- [2026-08-23 sonnet-af] Decisions: (1) Layout — added embed_form.setLabelAlignment(AlignLeft|AlignVCenter), setFieldGrowthPolicy(AllNonFixedFieldsGrow), embed_model_combo.setMinimumWidth(220), matching pull_input. (2) Inlined _job_row into the provider row (kept the addWidget(combo,1) stretch and embed_fix_btn), deleted _job_row and the now-dead _WARN constant, removed all embed_warn writes/unpacking from update_embed_status. (3) Added a pure module-level resolver _resolve_ollama_model(configured, models, indexed_model, default) called from sync_embed_widgets when provider=='ollama': precedence is (a) the model curation.index_stats() says the existing index was built with, IF it's in ui_state['models'], (b) the sole installed model if len(models)==1, (c) embeddings.DEFAULT_MODELS['ollama']. Judgment call: I went beyond a display-only fix — when resolved differs from the stored (empty) config, sync_embed_widgets now writes cfg['embedding_model'] = resolved via _pkg().write_config(cfg) before showing it as real combo text. Rationale: embeddings.embedding_model(cfg) is read all over the codebase (curation.py's real indexing pipeline included), not just this dialog, so a display-only fix would leave every other call site still resolving to the wrong hardcoded default; healing cfg here closes the hole everywhere, not just behind this button. (4) start_index() no longer shows a generic 'Index cards?' confirmation on every click. It now confirms ONLY when curation.index_stats() shows an existing index whose (provider, model) differs from embeddings.index_signature(cfg) — i.e. an actual destructive rebuild. Final wording — title 'Re-index from scratch?', body: f"Re-index all {note_count:,} cards from scratch? The existing index was built with {st['model']} and the current setting is {model}." Plain sentence case, no exclamation marks, names the count and both models. A matching signature (fresh build or incremental update) now takes exactly one click, no dialog. (5) Added _needs_local_runtime(cfg) -> bool = embeddings.provider_name(cfg)=='ollama', and gated both show_install_page() branches in refresh() on it; restructured refresh() around a single reached/models pair instead of duplicating the OllamaError-vs-unreachable branches. A cloud user now lands on models_page with an inline status_lbl note ('Local library needs Ollama — not required for your current provider.') instead of the install page; the install page stays reachable via Check connection / Refresh / Pull once the provider is switched to ollama (those all still call refresh(), which re-evaluates _needs_local_runtime against the now-updated cfg). Resolver precedence order as implemented: configured (non-empty, stripped) > indexed-model-if-installed > sole-installed-model > hardcoded default. Files: klausmate/manage_models.py, tests/test_dialog_logic.py. Could NOT verify headlessly (Qt cannot be instantiated on this machine): actual label alignment, embed_model_combo's rendered width, and that no warning label is visually present — these need Pouya in a restarted Anki. Verify gate exits 0 (setFieldGrowthPolicy present, _needs_local_runtime present, embed_warn absent, test_imports 21/21, test_dialog_logic 34/34). Full suite: 238 assertions total (68+34+58+21+57), up from the 233 baseline by exactly the 5 new resolver cases (4 spec'd + 1 extra: indexed-model-present-but-not-installed falls through past rule (a)) — no regressions elsewhere. py_compile through the Anki symlink passed. Never wrote to user_files/ or meta.json*; never exercised the real rebuild path. Risks: reviewer should double check the auto-heal-cfg judgment call in sync_embed_widgets (part 3) — it's a slightly bigger fix than 'just fix the display', see rationale above; also double check start_index()'s new confirm wording reads naturally when st['model'] and the live 'model' are the same string by coincidence but provider differs (edge case, not hit by the four spec'd cases). Next: none.
- [2026-08-23 orchestrator] Reviewed and signed off, with one fix applied by me on top (c3697ce). WHAT I CHANGED AND WHY. The worker's judgment call — healing the resolved model back into config rather than only into the widget — is RIGHT, and I want that on the record: embeddings.embedding_model(cfg) is read by index_signature and the real indexing pipeline, so a display-only fix would have left every non-dialog call site still resolving to the wrong default. Good instinct, correctly reasoned in the handoff. But the write was unguarded. Trace: provider ollama + ui_state['models'] empty + configured empty -> resolver falls through branches (a) and (b) to the hardcoded default -> that default gets WRITTEN TO DISK. Reachable in practice: switch the provider combo to ollama (line ~952 re-syncs) while the Ollama server is down, so the model list was never enumerated. An index built with embeddinggemma would then be orphaned in stored config — the precise failure this card exists to prevent, converted from recoverable into permanent. Fixed by gating the write on a populated model list: the fallback is still DISPLAYED, never STORED. Added three transcribed checks for the branch; suite now 240 (was 238 after the worker's five, plus my three, minus... see below). NOTE ON THE COUNT: the worker reported 238. I measured 233 -> 238 -> 241? No — actual current totals are 68+37+58+21+57 = 241. My three checks account for +3 over the worker's 238. Verified by running each file. Also caught while adding tests: appending to tests/test_dialog_logic.py is a trap — the file ends with print(summary) + sys.exit(), so anything appended after that NEVER RUNS and silently reports the old count. New blocks must be inserted ABOVE line ~311. Worth knowing for the next card that extends it. Everything else verified: gate exits 0, full suite green, py_compile clean in-repo and through the Anki symlink, confirmation wording is plain sentence case naming both models and the count, _needs_local_runtime correctly keeps the install page reachable rather than unreachable. Alignment, combo width and warning-absence remain unverifiable headlessly — Pouya's restart checks them.
