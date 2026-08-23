# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

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

### K-035: B3: restyle the editor PDF bar to match the deck-browser square
owner: -
priority: P2
tags: sonnet-safe,library-era
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

### K-036: A6: don't route cloud-provider users to the Ollama install page
owner: -
priority: P1
tags: sonnet-safe,removal,library-era
files: klausmate/manage_models.py
verify: grep -q '_needs_local_runtime' klausmate/manage_models.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && python3 tests/test_dialog_logic.py
created: 2026-08-23

BLOCKED until K-030 (A3) is Done — same file. Re-confirm the bug still exists before starting; K-030 rewrites much of this dialog and may have changed the shape of the fix (but its card did not mention this issue, so it most likely persists).

Found by sonnet-ab while doing K-029, and independently confirmed by the orchestrator: manage_models.py's refresh() does 'if not ollama_reachable(ep): show_install_page()' with NO provider check (~:524 and ~:532 pre-K-030). So a user on the DEFAULT cloud provider (Voyage) who opens Manage models is dumped on a page reading 'Could not reach Ollama at http://localhost:11434' and offered a ~1GB runtime install they will never need.

This defeats the whole point of K-029, which made Ollama optional for the passive per-profile-open flow. The proactive path — the user actually clicking 'Manage models…' — still assumes Ollama is mandatory.

FIX: add a single helper, _needs_local_runtime(cfg) -> bool, returning True only when embeddings.provider_name(cfg) == 'ollama'. Gate the install-page routing on it. A cloud-provider user must land on the normal models page regardless of whether an Ollama server is reachable; the local model library section can show a quiet inline note ('Local models need Ollama, which isn't running') instead of hijacking the whole dialog. A user who switches the provider combo TO ollama, or who clicks something that needs a local model (Pull), should still be able to reach the install page — do not make it unreachable, just stop making it the default landing.

Keep the K-009 one-click Get key / Pull it dispatcher and the single-.connect discipline intact.

Constraint: this file only. Full suite must be green INCLUDING tests/test_dialog_logic.py (K-032 will have rewritten it around the embedding rows by the time this runs — if it has not, say so and coordinate rather than editing tests here). py_compile through the Anki symlink.

Done when: verify passes and a Voyage-configured profile can open Manage models, see its key state, and never be shown the Ollama install page.

## Ready

## Doing

### K-030: A3: collapse Manage models to embeddings-only
owner: sonnet-ac
priority: P1
tags: sonnet-safe,removal,library-era
files: klausmate/manage_models.py
verify: ! grep -q 'ask_combo' klausmate/manage_models.py && ! grep -q '_MODEL_PRESETS' klausmate/manage_models.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Phase A3. BLOCKED until K-027 (A1) is Done — A1 deletes autocomplete_model/ask_model/klaus_engine/_DEFAULT_CLAUDE_MODEL, which this file calls via _pkg(). Read A1's handoff on K-027 first for the exact list.

The dialog currently has three job rows (Autocomplete / Ask / Semantic search). Only Semantic search survives — Klaus is embeddings-only.

DELETE: the Autocomplete row + caption, the Ask row + caption, claude_key_lbl/edit + claude_model_lbl/edit, ask_selection(), the ask/auto halves of sync_jobs_widgets and update_jobs_status and save_jobs, the auto/Ask used-by badges in rebuild_library_list, the auto/ask entries in set_busy's widget tuple, and their signal connects. Delete _MODEL_PRESETS (text models) entirely, plus the Text-models tab, _is_embedding_model, and _fill_pull_presets's tab-switching — with only embedding models left, the library is ONE list again (keep _EMBED_MODEL_PRESETS from K-026 as the pull dropdown's presets). Also fix the module docstring's _pkg() contract list and maybe_auto_pull_starter (must reference an embedding model or go away).

REWORK the framing (this is the point of the card, not just deletion): 'What Klaus uses' now describes one job. The K-009 explainer text currently says 'Autocomplete and Ask work without any of this' — that is now false and inverted; semantic search is the ONLY thing. Rewrite that caption and the Semantic-search caption to match a one-job product. Keep the K-009 one-click 'Get key' / 'Pull it' dispatcher and the self-documenting key placeholders exactly as they are — they still apply.

ADD a small 'General' group with the two toggles orphaned by settings_ui.py's deletion (A5): image_crop_enabled and runtime_auto_setup. Read settings_ui.py for their exact config keys, labels and defaults, but do NOT edit that file (A5 deletes it).

Constraint: this file only. tests/test_dialog_logic.py currently models the ask/auto rows and WILL fail — that is expected and A5 rewrites it; do not edit tests here, and note the expected failures in your handoff. Every other suite must stay green. py_compile through the symlink.

Done when: verify passes, the dialog is one job + one model library + General, and the handoff lists every removed widget and the new caption text.

## Review

## Done

### K-034: B2: add a Browse button inside the deck-browser drop square
owner: sonnet-z
priority: P2
tags: sonnet-safe,library-era
files: klausmate/deck_curate.py
verify: grep -q 'BROWSE_CMD' klausmate/deck_curate.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_drive.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Phase B2. Small, self-contained. The deck-browser drop square currently only accepts a drag-and-drop; there is no way to pick a PDF with a file dialog from that screen. Add a 'Browse…' button inside the square.

The bridge pattern already exists in this file and the square already uses it — the armed state's '×' disarm link is a pycmd() call inside this very injected div, which proves clicks round-trip. Mirror it:

1. Add BROWSE_CMD = 'klausmate_browse' next to CURATE_CMD/DISARM_CMD (~:48-49) and add it to the _CLAIMED set (~:50). The _CLAIMED addition is mandatory — on_deck_js_message early-bails on messages not in that set.
2. Add a branch in on_deck_js_message (~:293-310) alongside the DISARM_CMD branch. Return (True, None) like the others. Keep the existing isinstance(context, (DeckBrowser, DeckBrowserBottomBar)) gate — the square renders under DeckBrowser so it passes.
3. In the handler, do NOT open the file dialog synchronously inside the JS-message callback — wrap it in QTimer.singleShot(0, ...) exactly as the drop wrapper does (~:400-402). Then QFileDialog.getOpenFileNames (plural: multi-select, matching the drop path which imports every dropped PDF) with filter 'PDF files (*.pdf)', and feed the result to the existing _import_and_arm(paths) (~:100) so import + arm + refresh behave identically to a drop.
4. Emit the button in on_deck_browser_content's idle-state HTML (~:336-349) with onclick='pycmd("klausmate_browse"); return false;'. Style it inline (the div has no stylesheet) as a quiet secondary control — a bordered link-button, not a loud primary. It belongs in the IDLE state; the armed state keeps its current text + × affordance.

NAMESPACE TRAP: it must be the underscore form klausmate_browse, NOT the editor bridge's colon form klausmate:browse — the colon handler claims and drops messages from non-Editor contexts. The module docstring explains this.

Note for your handoff: B3 (a sibling card) restyles the editor's Qt PDF bar to look exactly like this square, so if you change the square's dashed border, radius, padding or copy, record the exact final values in your handoff comment — B3 has to match them.

Constraint: this file only. Full suite; py_compile through the symlink. Done when: verify passes and the square offers both drop and Browse.

#### Comments
- [2026-08-23 sonnet-z] Decisions: Reused _import_and_arm(paths) exactly as the drop path does — Browse and drop now converge on one import function. QFileDialog is imported LAZILY inside _browse_for_pdfs() (not at module top-level) because tests/test_drive.py stubs a reduced aqt.qt without QFileDialog; a top-level import broke deck_curate's and pdf_drive's import checks (pdf_drive imports deck_curate). This follows the file's existing local-import convention (_user_files, _import_and_arm, _install_drop_wrap all do the same). QTimer.singleShot(0, _browse_for_pdfs) defers the modal dialog off the JS-message callback, mirroring the drop wrapper at ~:400. Button uses getOpenFileNames (plural) with filter 'PDF files (*.pdf)', title 'Import lecture PDF'. Files: klausmate/deck_curate.py — added BROWSE_CMD='klausmate_browse' constant + _CLAIMED entry (~:48-51), _browse_for_pdfs()/_on_browse_clicked() (~:280-292), a BROWSE_CMD branch in on_deck_js_message (~:325-327), and the Browse button markup in on_deck_browser_content's idle body (~:368-376). Style values for B3 (editor Qt PDF bar restyle) to match exactly — SQUARE (unchanged): idle border '1px dashed rgba(128,128,128,0.55)', armed border '1px solid rgba(58,130,247,0.85)', border-radius 10px, padding 8px 14px, font-size 13px. NEW Browse button (idle state only): inline <a> styled 'display:inline-block;margin-top:6px;padding:3px 10px;border:1px solid rgba(128,128,128,0.55);border-radius:6px;font-size:12px;color:inherit;text-decoration:none;', copy string 'Browse&hellip;' (HTML entity, renders 'Browse…'), placed on its own line via <br> below 'Drop a lecture PDF here to curate a deck from it.', inheriting the parent div's text-align:center. Risks: Cannot click-test the button since Qt can't be instantiated headlessly here (per card) — correctness rests on the aqt-stub suite plus mirroring the proven drop-path pattern (_import_and_arm, QTimer.singleShot deferral) exactly. Reviewer should double check the lazy-import choice isn't seen as a workaround rather than a deliberate fit with house style — it matches 4 existing precedents in this same file. Next: none.
- [2026-08-23 orchestrator] Independently re-verified: BROWSE_CMD uses the correct underscore namespace and IS in _CLAIMED (both edits present — the silent-failure trap avoided); QTimer is a module-level import already, so the deferral has no import cost; the QFileDialog local-import deviation is legitimate and I confirmed the premise myself — tests/test_drive.py:257's aqt.qt stub list contains QTimer but not QFileDialog, and the same local-import pattern already exists at :300 and :318 for aqt.deckbrowser, so it is house style rather than a workaround; Browse button lands in the idle branch only, armed state untouched; style is quiet secondary as specced. Full suite 234 green, py_compile clean in-repo and through the Anki symlink. Signed off — rendered look needs Pouya's eyes in Anki. B3 (K-035) must match the values recorded in sonnet-z's handoff.

### K-033: B1: Library rename, retention colors, sorting, drag-and-drop
owner: sonnet-y
priority: P1
tags: sonnet-safe,library-era
files: klausmate/pdf_drive.py,klausmate/drive_store.py
verify: grep -q 'Library' klausmate/pdf_drive.py && grep -q 'def retention_color' klausmate/drive_store.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_drive.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Phase B1 of the Library-era plan. Four user-visible upgrades to the PDF drive window, all in pdf_drive.py plus one pure helper in drive_store.py. Independent of Phase A — safe to run in parallel with removal cards (different files).

1. RENAME to 'Library'. The toolbar link label 'PDFs' lives in _on_toolbar_links (~:736, the second arg to toolbar.create_link); the window title 'Klaus — PDFs' is at ~:67; the toolbar tip is 'Klaus PDF drive'. Rename the user-visible strings to Library ('Library', 'Klaus — Library', tip 'Klaus PDF library'). Do NOT change the link's cmd name 'klausDriveOpen', the id 'klaus-drive', the DIALOG_NAME 'KlausDrive', or any module/file name — those are identities, and DIALOG_NAME in particular is what aqt.dialogs registration and saved state key off.

2. RETENTION COLOR (red 0% -> green 100%). Add a PURE function to drive_store.py: retention_color(fraction, night_mode) -> (r, g, b) ints, interpolating hue 0->120 in HSV. It must be aqt-free and Qt-free (plain tuple out) so it is headless-testable — drive_store.py is already aqt-free, keep it that way. Tune saturation/value so both light and dark themes stay readable (dark mode needs lighter, less saturated colors). In pdf_drive._apply_row, call it and item.setForeground(1, QBrush(QColor(*rgb))). Only the retention cell is colored — no row backgrounds, no bold, nothing loud (the product aesthetic is 'Anki with a little extra you barely notice'). Non-numeric states (not embedded / re-embed needed / no matches / em-dash) get NO color, default foreground. Night mode: aqt.theme.theme_manager.night_mode, read defensively.

3. SORTING. Today the tree is alpha-only from build_tree and the retention values live as strings in column text. Add a QTreeWidgetItem subclass overriding __lt__ so sorting is numeric, not lexicographic: store the sort key via setData(col, Qt.ItemDataRole.UserRole+2, value) in _apply_row (retention as a float, cards as an int; use -1.0 for unknown/unembedded so they sink to the bottom in either direction). Folders must ALWAYS sort above PDFs regardless of column/direction — handle that first in __lt__ (compare the _ROLE_FOLDER-vs-_ROLE_SAFE nature of self and other). Enable header().setSectionsClickable(True) + setSortingEnabled, and make sure rebuild_tree does not fight the sort (disable sorting while repopulating, re-enable after — a classic QTreeWidget trap).

4. DRAG-AND-DROP folder moves. Subclass QTreeWidget; setDragDropMode(InternalMove), setDragEnabled/setAcceptDrops. Override dropEvent: resolve the drop target (a folder item -> its _ROLE_FOLDER path; a PDF item -> that PDF's parent folder; empty space -> root/None), then call drive_store.set_folder(safe, folder) and rebuild_tree(). CRITICAL: do NOT call super().dropEvent() and do NOT let Qt perform the visual move — drive.json is the single source of truth and rebuild_tree repaints from it. Dragging a PDF onto its current folder is a no-op. PDFs only: reject drags whose item is a folder (folder reparenting is out of scope for this card). Guard everything in try/except per house style.

5. Slider range: in _on_threshold, widen the QSlider from 20-60 to 20-80. (Phase C raises the default to 0.55; this is groundwork so the default is not pinned at the max.)

Constraints: do not touch retention.py, curation.py or any tag logic — Phase C owns those. Add tests to tests/test_drive.py? NO — test_drive.py is not in your files: scope. Instead the verify gate only requires the helper to exist and existing suites to stay green; a follow-up may add color tests. Actually: tests/test_drive.py IS out of scope, so do not edit it.

Full suite (234 assertions, 5 files) must stay green; py_compile through the Anki symlink. Done when: verify passes, and the handoff describes the color ramp endpoints (what RGB 0% and 100% produce in each theme) and confirms the sorting/rebuild interaction is handled.

#### Comments
- [2026-08-23 sonnet-y] Decisions: retention_color(fraction, night_mode) in drive_store.py interpolates HSV hue 0->120 with fixed sat/val per theme, returning a plain (r,g,b) tuple — light theme uses S=0.65/V=0.75 (0%=rgb(191,67,67), 50%=rgb(191,191,67), 100%=rgb(67,191,67)); night mode uses a lighter/less-saturated S=0.5/V=0.9 (0%=rgb(230,115,115), 50%=rgb(230,230,115), 100%=rgb(115,230,115)). Applied via item.setForeground(1, QBrush(QColor(*rgb))) in a new _apply_row-called helper _set_retention_color; non-numeric states (no row/not-embedded/stale) clear the role via setData(1, ForegroundRole, None) rather than leave a stale color on reused items (the _on_threshold in-place update path reuses items). QColor/QBrush are imported lazily inside that method, not at module top-level — test_drive.py's own embedded aqt.qt stub whitelists a fixed set of names that doesn't include them, so a top-level import would fail that test's 'pdf_drive imports' check even though real Anki has both. Sorting: added _LibraryItem(QTreeWidgetItem) overriding __lt__, sort keys stored in a new _ROLE_SORT (UserRole+2) role set by _apply_row (retention as float, cards as int, -1.0 sentinel for no-row/unembedded/stale — NOT for a real zero-match count, which is a known value and sorts normally). Two invariants had to be direction-compensated inside __lt__: folders-above-PDFs and known-above-unknown both flip to the wrong side under Qt's descending comparator (QTreeModel::itemGreaterThan calls right<left, i.e. swaps which item's __lt__ runs) — __lt__ reads header().sortIndicatorOrder() and inverts its own relation when descending to cancel that flip, verified by hand-deriving both call directions. rebuild_tree captures was_sorting = tree.isSortingEnabled(), disables it before tree.clear()+repopulate, restores in a finally block; setSectionsClickable(True)+setSortingEnabled(True) are set once at tree construction in __init__ so the very first rebuild_tree call already sees sorting enabled and the dance is symmetric from the start. Drag-and-drop: new _LibraryTree(QTreeWidget) with InternalMove/setDragEnabled/setAcceptDrops; dropEvent never calls super() or touches Qt's own move — it resolves safe (the dragged item, via currentItem(), since single-selection means the drag always starts from the current item) and folder (itemAt(event.position().toPoint()): None item -> root, a folder item -> its _ROLE_FOLDER path, a PDF item -> that PDF's parent's folder, i.e. parent.data(0,_ROLE_FOLDER) or None if parent is None), rejects when the dragged item is a folder or event.source() is not self, no-ops (accepts but skips the write) when current_folder == folder, and otherwise calls self._window._move_pdf(safe, folder) — the exact existing two-line drive_store.set_folder+rebuild_tree pattern, reused rather than duplicated. Files: klausmate/drive_store.py (+retention_color), klausmate/pdf_drive.py (rename strings, _LibraryItem, _LibraryTree, _apply_row/_set_retention_color, rebuild_tree sort guard, slider 20->80). Risks: I could not run the actual window (Qt can't be instantiated headlessly here) so the drag-and-drop and sort-direction logic are verified by careful reading + hand-derivation of Qt's descending-comparator mechanics, not by executing them — a reviewer should sanity-check the __lt__ direction inversion live in Anki, especially clicking the Retention header twice (asc then desc) with a mix of embedded/unembedded PDFs and at least one folder. Also note test_drive.py is explicitly out of scope for this card and was not touched, so there is no automated coverage yet for retention_color's exact values or for _LibraryItem's sort behavior — verified manually via a standalone script (light 0/50/100%: rgb(191,67,67)/(191,191,67)/(67,191,67); dark: rgb(230,115,115)/(230,230,115)/(115,230,115)). Next: a follow-up card could add retention_color + sort-order tests to test_drive.py now that it's out of my scope; folder drag-and-drop (reparenting one folder into another) is explicitly out of scope here and still unimplemented. Note: verify initially failed twice with 'NameError: strip_ghost_html' in klausmate/__init__.py — that file is entirely outside this card's scope and was mid-edit by K-027 (@sonnet-x, concurrent removal card touching __init__.py). Waited for K-027 to land rather than releasing correct, complete work; re-ran verify + the full 5-file/234-assertion suite immediately after, both clean, then committed right away to minimize the shared-checkout race window.
- [2026-08-23 orchestrator] Independently re-verified. Identities intact (DIALOG_NAME/klausDriveOpen/klaus-drive unchanged; only label+tip+title renamed). retention_color is stdlib-only (colorsys) and stays aqt-free; I ran the ramp myself — light 0%=(191,67,67) -> 100%=(67,191,67), dark lighter at (230,115,115)->(115,230,115), out-of-range clamps correctly, muted as specced. The _LibraryItem.__lt__ descending-order handling is the standout: Qt's QTreeModel::itemGreaterThan calls right<left rather than reversing, so a naive folders-first relation inverts on the second header click — the worker caught this and compensates in both the folder and unknown-sink branches. Sorting is correctly disabled around rebuild_tree repopulation with try/finally restoring the user's setting. dropEvent never calls super() and never lets Qt reparent visually — it routes through _move_pdf -> drive_store.set_folder -> rebuild_tree, so drive.json stays the source of truth; same-folder drop is a no-op; folder drags rejected as scoped. Sentinel design is right: an embedded PDF matching nothing is a real zero and sorts with the numbers, only unknowns sink. Both files compile in-repo and through the Anki symlink; full suite 234 green. Signed off — colors/sort/drag need Pouya's eyes in Anki.

### K-027: A1: remove autocomplete + Ask + Browse NL search from __init__.py and copilot.js
owner: sonnet-x
priority: P0
tags: sonnet-safe,removal,library-era
files: klausmate/__init__.py,klausmate/web/copilot.js,klausmate/web/copilot.css,klausmate/config.json,klausmate/config.md
verify: ! grep -q 'def build_prompt' klausmate/__init__.py && ! test -f klausmate/web/copilot.css && ! grep -q 'dbgLog' klausmate/web/copilot.js && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Phase A1 of the approved Library-era plan (plan file: ~/.claude/plans/ok-but-i-want-cozy-forest.md). Klaus is dropping ALL LLM-text features — autocomplete, editor ⌘K Ask, and Browse natural-language search — keeping only embeddings. Hard delete; git preserves history.

DELETE from klausmate/__init__.py (locate by NAME, line numbers are pre-K-023 approximations and have shifted):
- Debug instrumentation: _debug_log_path block near top (~:21-60) and the klausmate:dbg pycmd handler (~:2149-2160).
- from .claude_api import ClaudeAPIError (line ~109).
- _DEFAULT_MODEL, resolve_model, autocomplete_model, ask_model, klaus_engine, _DEFAULT_CLAUDE_MODEL, _DEFAULT_ASK_SYSTEM, _ask_via_claude.
- _MODE_ORDER/_MODE_PARAMS/_LIST_INCOMING_RE/_LONG_MIN_SCORE/choose_mode, build_prompt, _strip_html, extract_card_ctx, strip_markdown + its _MD_* regexes.
- The ENTIRE output-cleanup section (_ABBREV through clean_completion, incl. _strip_llm_artifacts — its last caller, Browse search, dies here too).
- request_completion + send_completion_to_js, build_ask_prompt + request_ask.
- Browse NL search: the search-conversion block, _KlausSearchAskPopover, _install_browser_search_klaus, AND _remap_browser_mark_hotkey (deleting it restores Anki's native ⌘K Mark hotkey — that is intentional).
- retrieve_chunks_for (its 3 callers all die). Leave pdf_handler.py alone (its BM25 fn goes dormant; out of scope).
- generating_client. In the error-helper cluster: KEEP _try_silent_autostart and _save_config_on_main (setup_flow.py reaches them via _pkg()); delete _show_ollama_setup_error/_classify_setup_error ONLY if grep shows no surviving callers.
- _GHOST_SPAN_RE + strip_ghost_html + the gui_hooks.editor_will_munge_html registration.
- on_js_message branches for 'complete' and 'ask'; runtime-config injection of ask/autocomplete keys (ask_hotkey, ask_enabled, autocomplete_enabled, cycle hotkeys, debounce, min-chars, cooldowns); copilot.css injection line.
- Test-connection dialog: trim the autocomplete/ask model lines; keep the endpoint/health part.
- Settings openers pointing at settings_ui (menu will be rebuilt in A3; settings_ui.py itself is deleted in A5, NOT here).
- _migrate_config: collapse _LEGACY_KEY_RENAMES into _LEGACY_KEYS_DROPPED (the rename targets are now dead), and append ALL newly-dead keys so old profiles get scrubbed: model, autocomplete_model, ask_model, generate_timeout_s, temperature, top_p, top_k, repeat_penalty, completion_mode, ask_hotkey, cycle_forward_hotkey, cycle_backward_hotkey, debounce_ms, min_chars_before_trigger, paste_cooldown_ms, dismissal_cooldown_ms, accept_cooldown_ms, retrieval_method, retrieval_top_k, system_prompt, ask_system_prompt, autocomplete_enabled, ask_enabled, chat_hotkey, klaus_engine, claude_api_key, claude_model, claude_timeout_s, chat_engine, chat_claude_api_key, chat_claude_model, chat_turn_timeout_s, autofill_system_prompt. DO NOT TOUCH the _embed_default_migrated guard block.

klausmate/web/copilot.js — reduce to a minimal file keeping ONLY: the IIFE + window.klausmate={__installed:true} stub, deepActiveElement/isEditableField, fieldNameForEditable, notifyFieldFocus + its mousedown and focusin listeners (strip the ghost-wiping lines inside focusin), and the dblclick crop handler. Everything else goes (ghost text, ask popover, dbgLog + its localhost POST, keydown handler, layout tick with its findFieldContainers ReferenceError).

DELETE klausmate/web/copilot.css entirely (git rm).

klausmate/config.json — remove every key listed in the drop list above that exists there (survivors: endpoint, runtime_auto_setup, image_crop_enabled, embedding_*, curate_*, pdf_match_*, pdf_index_max_chunks, and any _-prefixed state keys). klausmate/config.md — delete the sections documenting removed keys/features.

HARD CONSTRAINTS: grep EVERY name before deleting it — a name is deletable only when all its callers are also in this card's delete set. manage_models.py/setup_flow.py reference some deleted names via lazy _pkg() calls — those modules are FOLLOW-UP cards (A3/A2b); their _pkg() calls are lazy so imports and py_compile stay green — do NOT touch those files. tests/test_dialog_logic.py is a stub transcription that imports nothing from the addon — it must keep passing untouched. tests/test_imports.py must pass (claude_api.py still exists until A5; you only remove __init__'s import OF it).

Done when: verify passes, full suite (234 assertions) green, py_compile through the Anki symlink clean, ⌘K/autocomplete/Browse-search code is unreachable, and the handoff lists every deleted top-level name plus every name you KEPT that the plan flagged (with the grep evidence for keeping it).

#### Comments
- [2026-08-23 sonnet-x] Handoff for K-027. Commit f3d3594. __init__.py 4354->2589 lines, copilot.js 1179->142 lines, copilot.css deleted (git rm), config.json 43->14 lines, config.md 214->95 lines. Verify gate exit 0; full suite 234/234 (68+29+58+22+57), test_dialog_logic.py untouched at 29/29; py_compile clean through the Anki symlink. (a) Deleted, grouped by feature: - Debug instrumentation: _debug_log_path, _dbg_autofill (the #region block), on_js_message's "dbg" branch; copilot.js's dbgLog + its localhost POST. - Claude wiring for Ask: `from .claude_api import ClaudeAPIError` import, _DEFAULT_CLAUDE_MODEL, _ask_via_claude (claude_api.py itself untouched, dies in A5). - Autocomplete: _DEFAULT_MODEL, resolve_model, autocomplete_model; _MODE_ORDER/_MODE_PARAMS/_LIST_INCOMING_RE/_LONG_MIN_SCORE/choose_mode; _VISIBLE_PAGE_CHAR_CAP/retrieve_chunks_for; build_prompt; extract_card_ctx; strip_markdown + all _MD_*_RE/_BLANKLINES_RE; the entire output-cleanup cluster (_ABBREV through clean_completion, ~30 names incl. _strip_llm_artifacts); request_completion/send_completion_to_js; on_js_message's "complete" branch. copilot.js: all ghost-text machinery (CONFIG/hotkey parsing, GHOST_ATTR helpers, showGhost/hideGhost/acceptGhost/dismissGhost, shouldTrigger/scheduleCompletion/requestCompletion/cycleSuggestion, getFieldText/fieldMatchesSnapshot family, window.klausmate.onCompletion/stripAllGhosts, input/selectionchange/composition*/paste listeners, the layout-tick block — which also kills the latent findFieldContainers ReferenceError). - Ask (Cmd+K): ask_model, klaus_engine, _DEFAULT_ASK_SYSTEM, build_ask_prompt, request_ask, on_js_message's "ask" branch. copilot.js: ensureAskEl/openAsk/repositionAsk/closeAsk/submitAsk/cancelTyping/typeInto, window.klausmate.onAskResult, the ask-popover dismiss-on-outside-click listener, and the whole document keydown handler (Cmd+K open, cycle hotkeys, Tab-accept, Esc-dismiss — shared with autocomplete). - Browse NL search: _DEFAULT_SEARCH_SYSTEM/request_search_conversion, _remap_browser_mark_hotkey (restores Anki's native Mark hotkey), _KlausSearchAskPopover, _install_browser_search_klaus/_find_browser_search_line_edit. - Error surfacing (dead once their only callers died): _classify_setup_error, _show_ollama_setup_error, _ollama_setup_warning_shown. - Injection/menu trims: on_webview_will_set_content drops the copilot.css append + the ask/autocomplete runtime-config keys (keeps only image_crop_enabled); install_menu's Test-connection dialog drops the Autocomplete/Ask model lines (keeps endpoint/health check); _LEGACY_KEY_RENAMES collapsed into _LEGACY_KEYS_DROPPED, now scrubbing every dead key from old profiles (model, autocomplete_model, ask_model, generate_timeout_s, temperature, top_p, top_k, repeat_penalty, completion_mode, ask_hotkey, cycle_forward/backward_hotkey, debounce_ms, min_chars_before_trigger, paste/dismissal/accept_cooldown_ms, retrieval_method, retrieval_top_k, system_prompt, ask_system_prompt, autocomplete_enabled, ask_enabled, chat_hotkey, klaus_engine, claude_api_key, claude_model, claude_timeout_s, autofill_system_prompt, plus the old chat_* rename sources). (b) Kept, with grep evidence: - _try_silent_autostart, _save_config_on_main: setup_flow.py:155,195 and manage_models.py:704 call both via _pkg(). - _reset_browse_layout_to_defaults (+ its _KLAUS_BROWSE_LAYOUT_HEALED guard), comments verbatim: browse_toggles.py:220 `_pkg()._reset_browse_layout_to_defaults(browser)` still resolves. - open_settings_dialog/install_preferences/open_config + the Settings... menu action: untouched, still point at settings_ui.py (alive until A5). Confirmed settings_ui.py imports nothing from __init__.py (no _pkg()/circular import) so it's decoupled from everything else deleted here. - _set_target_field: still the target of on_js_message's surviving "focus" branch. - UNANTICIPATED FINDING - _strip_html: the card listed this for deletion, but grep found a surviving caller OUTSIDE this card's files and outside the two follow-up files the card names: klausmate/curation.py:116 does `strip = _pkg()._strip_html` (used when prepping note text for embedding). curation.py is permanent (not slated for deletion or a follow-up card), so deleting _strip_html would have silently broken curation at runtime with no card scheduled to fix it. Kept it rather than guessing; only extract_card_ctx (its one same-file caller) was removed. - _classify_setup_error/_show_ollama_setup_error were NOT kept (contrast with above): grep showed their only callers were request_completion.on_failure, request_ask.on_failure, and request_search_conversion.on_failure - all three deleted in this same card - so per the card's own conditional they were safe to delete. (c) Deleted names other files still reach via lazy _pkg() - follow-up work for their cards: - manage_models.py (A3/K-030): autocomplete_model, ask_model, klaus_engine, _DEFAULT_CLAUDE_MODEL (manage_models.py:335,556,557,780,781,782,846,849,851,877,878). - browse_toggles.py (A4/K-031): _remap_browser_mark_hotkey, _install_browser_search_klaus (browse_toggles.py:207,211). - setup_flow.py (A2b/K-029): checked directly - it reads its own config keys (cfg.get("autocomplete_model") etc.) rather than calling __init__ symbols, so none of the deleted names above are actually referenced from this file; only get_config/client/write_config/_save_config_on_main are called via _pkg(), and all four survive. K-029's "blocked on K-027" note appears to be precautionary, not an active break. Risks: settings_ui.py's autocomplete/Ask/temperature panel still round-trips those config keys in its own UI (untouched by this card) - since _migrate_config now scrubs them on every profile open, any edit a user makes there via that panel will be silently reset on next Anki restart until A3/A5 land. Expected transient inconsistency, not a regression in this card's scope.
- [2026-08-23 orchestrator] Independently re-verified and signed off. Scale: __init__.py 4354->2589 lines, copilot.js 1179->142, config.json 43->12 keys, copilot.css deleted (delete mode confirmed in the commit after the index mishap I caused and repaired). Swept for remnants myself: build_prompt/request_completion/request_ask/dbgLog/copilot.css/klausmate:ask/klausmate:complete all zero. Three residual hits, all accounted for: _remap_browser_mark_hotkey + _install_browser_search_klaus survive only in browse_toggles.py (K-031/A4's scoped job); ClaudeAPIError only in claude_api.py itself (K-032/A5 deletes the file); 'ghost' in __init__.py is the PDF drag tear-off fallback, an unrelated feature that stays. THE WORKER CAUGHT A REAL ERROR IN MY CARD: I listed _strip_html for deletion, but curation.py:116 binds it via _pkg()._strip_html for embedding text prep — deleting it would have broken semantic indexing at runtime with NO test catching it (lazy resolution). They kept it and removed only its dead in-file caller. That is exactly what the grep-before-delete rule is for. One thing they missed, which I fixed directly in d9c4fa9: the module docstring still read 'Klausmate — Local AI Autocomplete for Anki'. Full suite 234 green, py_compile clean through the Anki symlink.

### K-031: A4: drop dead browse-search calls from browse_toggles.py
owner: sonnet-ad
priority: P2
tags: sonnet-safe,removal,library-era
files: klausmate/browse_toggles.py
verify: ! grep -q '_install_browser_search_klaus' klausmate/browse_toggles.py && ! grep -q '_remap_browser_mark_hotkey' klausmate/browse_toggles.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Phase A4. BLOCKED until K-027 (A1) is Done — A1 deletes the two functions this file calls.

Small card. In on_browser_will_show's _deferred() (~:206-212), remove the two _pkg() calls to _remap_browser_mark_hotkey and _install_browser_search_klaus, which A1 deleted along with the Browse natural-language search feature. Keep the third call, _reset_browse_layout_to_defaults (still lives in __init__.py — verify with grep). Update the module docstring: its numbered list mentions the ⌘K search and the Mark-hotkey remap as items 1 and 2; those behaviors are gone, and Anki's native ⌘K Mark now works again.

Everything else in this file — the ◧/◨ sidebar and editor-column toggles, _VisibilityWatcher, the gridLayout cell-(0,0) repack note and the QTimer.singleShot(0) deferral note — MUST stay, comments verbatim.

Constraint: this file only. Full suite; py_compile through the symlink. Done when: verify passes and the handoff confirms _reset_browse_layout_to_defaults still resolves.

#### Comments
- [2026-08-23 sonnet-ad] Decisions: removed both dead _pkg() calls (_remap_browser_mark_hotkey, _install_browser_search_klaus) from on_browser_will_show's _deferred(); kept _reset_browse_layout_to_defaults call and its surrounding comment verbatim (confirmed it still resolves — grep finds def _reset_browse_layout_to_defaults at klausmate/__init__.py:258). Rewrote the module docstring's function list (now just names _reset_browse_layout_to_defaults) and on_browser_will_show's numbered-list docstring to describe only the ◧ sidebar / ◨ editor-column toggles and the layout repair, noting the ⌘K search + Mark-hotkey remap are gone and Anki's native ⌘K Mark works again. Left the ◧/◨ toggle machinery, _VisibilityWatcher, the gridLayout cell-(0,0) repack comment, and the QTimer.singleShot(0) deferral comment untouched. Files: klausmate/browse_toggles.py. Risks: none -- pure removal + docstring update, verify gate and full suite (234/234) both green, py_compile through the Anki symlink clean. Next: none.
- [2026-08-23 orchestrator] Independently re-verified and signed off. Both dead _pkg() calls gone; _reset_browse_layout_to_defaults confirmed still defined at __init__.py:258 and its call plus comment kept intact. Both protected gotcha comments survive verbatim (gridLayout cell (0,0) at :153, QTimer.singleShot(0) deferral at :199). Docstrings rewritten honestly — the history paragraph now records that the Browse NL search and Mark remap were removed and that Anki's native ⌘K Mark works again, which is the right thing for the next reader to know rather than silently dropping the mention. py_compile clean in-repo and through the Anki symlink; full suite 234 green.

### K-028: A2a: strip text-generation from ollama_client.py
owner: sonnet-aa
priority: P1
tags: sonnet-safe,removal,library-era
files: klausmate/ollama_client.py
verify: ! grep -q 'def chat' klausmate/ollama_client.py && ! grep -q 'def generate' klausmate/ollama_client.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_klausmate.py
created: 2026-08-23
claimed: 2026-08-23

Phase A2a. BLOCKED until K-027 (A1) is Done — A1 deletes generating_client() and the three call sites of chat()/generate(). Do not start before then.

Klaus is embeddings-only now. ollama_client.py keeps only what embeddings and model management need.

DELETE: generate() (~:228-264), chat() (~:266-304), and the three response extractors used only by them: _extract_model_text (~:27), _extract_generate_response (~:36), _extract_chat_message (~:43). Locate by name.

KEEP (all still used): _url_error_message, _http_error_detail, every error class (OllamaError/OllamaNotRunning/etc), _post, _get, health(), list_models(), embed(), pull(), delete(). embeddings.py's OllamaProvider.embed() calls client.embed() -> POST /api/embed, and manage_models.py drives pull/delete/list_models — verify each with grep before you touch anything.

Also update the module docstring if it advertises chat/generate.

Constraint: do not touch embeddings.py, manage_models.py, or any other file. Full suite before committing; py_compile through the Anki symlink.

Done when: verify passes, full suite green, handoff confirms via grep that no caller of the deleted methods remains anywhere in klausmate/ or tests/.

#### Comments
- [2026-08-23 sonnet-aa] Decisions: Deleted exactly the 5 named items (generate, chat, _extract_model_text, _extract_generate_response, _extract_chat_message), grep-verified zero surviving callers for each: 'grep -rn .generate(.' and '.chat(.' across all *.py in klausmate/ tests/ returned zero hits (word-boundary 'generate'/'chat' hits elsewhere are unrelated prose in setup_flow.py comments/strings and print-log lines in __init__.py/chat_dock.py, not calls to OllamaClient); the three extractors had zero callers outside the deleted generate()/chat() bodies. Went one step beyond the literal list: _THINKING_BLOCK_RE and _QWEN_CONTROL_TOKEN_RE were used only inside _extract_model_text (grep confirmed no other reference), so once that function was deleted they'd be orphaned module-level regexes; removed them too, which in turn made 'import re' unused (grep '\bre\.' showed no other use), so I dropped that import as well. Checked module docstring — it never named chat/generate, so left it untouched per the card's conditional. Files: klausmate/ollama_client.py only (111 lines removed: 228-304 generate/chat methods, 17-47 the three extractors + two regexes, plus the re import). Risks: the _THINKING_BLOCK_RE/_QWEN_CONTROL_TOKEN_RE/import-re removal wasn't explicitly listed in the card — reviewer may want to confirm that judgment call; grep evidence for it is above and re-checkable with: grep -rn '_THINKING_BLOCK_RE\|_QWEN_CONTROL_TOKEN_RE' klausmate/ tests/ (zero hits post-change). Next: none — manage_models.py and setup_flow.py were confirmed to only call list_models/pull/delete/health/embed via _pkg(), untouched by this card. Verify gate exit 0 (grep checks + test_imports.py 22/22 + test_klausmate.py 57/57). Full suite 234/234 (68+29+58+22+57), no regressions. py_compile clean through the Anki symlink. Commit 10a347d, only klausmate/ollama_client.py staged.
- [2026-08-23 orchestrator] Independently re-verified and signed off. Pure deletion, 111 lines, zero insertions. Surviving API is exactly the specced set (health, list_models, embed, pull, delete) plus the error classes and _post/_get. The two judgment-call deletions beyond the card's literal list check out: grep across klausmate/ and tests/ returns ZERO references to _THINKING_BLOCK_RE and _QWEN_CONTROL_TOKEN_RE, and 're' is genuinely unused afterwards (the only remaining 're.' substring is the word 'Raises' inside a docstring). Flagging them in the handoff rather than deleting silently was the right call. py_compile clean in-repo and through the Anki symlink; full suite 234 green.

### K-029: A2b: rewrite setup_flow.py for embeddings-only, make Ollama optional
owner: sonnet-ab
priority: P1
tags: sonnet-safe,removal,library-era
files: klausmate/setup_flow.py
verify: ! grep -q 'ask_model' klausmate/setup_flow.py && ! grep -q 'autocomplete' klausmate/setup_flow.py && env QT_QPA_PLATFORM=offscreen python3 tests/test_imports.py
created: 2026-08-23
claimed: 2026-08-23

Phase A2b. BLOCKED until K-027 (A1) is Done — A1 deletes autocomplete_model/ask_model/klaus_engine, which this file calls via _pkg(). Read A1's handoff comment on K-027 first: it lists exactly which names vanished.

Klaus is embeddings-only. The DEFAULT install (embedding_provider=voyage) now needs NO Ollama at all — today this file nags every user to download a ~1GB runtime regardless. That is the main bug to fix.

1. first_run_check welcome copy: drop the ghost-text and ⌘K bullets. Keep and lead with the PDF sidebar + semantic-search/curation bullets. Remove the claim that 'Autocomplete and Ask run on this computer' — replace with an honest line about semantic search using a cloud embedder by default (free tier) or a local model if the user prefers.

2. _readiness_check_body: today its 'missing' list checks only autocomplete_model and ask_model — there is NO embedding readiness check at all. Replace that block entirely: ready means (cloud provider AND its embedding_api_key_<provider> is non-empty) OR (ollama provider AND the configured/default embedding model is installed). Not ready -> one actionable warning pointing at Manage models. Use embeddings.provider_name(cfg)/embedding_model(cfg) and embeddings.DEFAULT_MODELS; the config key shape is embedding_api_key_voyage / embedding_api_key_openai (confirm against manage_models._embed_cfg_key).

3. Ollama reachability half of _readiness_check_body: make it conditional on embeddings.provider_name(cfg) == 'ollama'. A Voyage user must never see an Ollama warning. Same gate on _maybe_offer_runtime_update.

4. Starter pull: if a first-run auto-pull remains, it must pull nomic-embed-text (the embedding default), NOT a text model, and only when the user has chosen the local provider. If that makes the starter pull vacuous for cloud users, drop it for them entirely.

Keep: _first_run_dialog_shown_this_session and both its readers in this module (shared session state), the _pkg() lazy-access pattern, all defensive try/except. _try_silent_autostart and _save_config_on_main survive in __init__.py per A1 — keep calling them via _pkg().

Constraint: this file only. Full suite; py_compile through the symlink. Done when: verify passes and a Voyage-default profile would see zero Ollama prompts (state in the handoff exactly which code path a Voyage user now takes through this file).

#### Comments
- [2026-08-23 orchestrator] Unblocked: K-027 is Done. Its worker reported that setup_flow.py does NOT reference any of the deleted symbols directly (it reads its own config keys), so the 'blocked' note was precautionary — no broken _pkg() calls to repair here. Your job is the copy rewrite and the embedding-readiness logic, not damage control.
- [2026-08-23 sonnet-ab] Decisions: Added a shared _embedding_ready(cfg) helper (cloud: embedding_api_key_<provider> non-empty; ollama: reachable + embedding_model(cfg) installed) used by both first_run_check and _readiness_check_body, so the two dialogs never disagree. Split _readiness_check_body into the existing ollama branch plus a new _cloud_readiness_check(cfg, provider) for Voyage/OpenAI, gated on embeddings.provider_name(cfg) != 'ollama'. Added the same provider gate to setup_readiness_check (skips ensure_server/QueryOp entirely for cloud providers, not just the dialog) and to _maybe_offer_runtime_update, per the card. Added a new declined-flag `_embed_key_setup_declined` (mirrors `_runtime_setup_declined`) so a cloud user who clicks Skip isn't renagged every profile open. Part 4 (starter pull) required no change: setup_flow.py never calls a pull directly — both action buttons just open manage_models_dialog(setup=True/False) in manage_models.py, which owns the actual pull. Unified button label to 'Manage models…' everywhere (dropped the old 'Choose models…' variant) for consistency. Voyage-default path traced end to end: fresh profile, embedding_provider unset -> embeddings.provider_name(cfg) returns 'voyage' (DEFAULT_PROVIDER). first_run_check(): provider='voyage', is_ollama=False, _embedding_ready(cfg) reads cfg['embedding_api_key_voyage'] -> empty -> ready=False. Dialog shows the two feature bullets plus: 'Semantic search needs a Voyage API key to work (free tier available). Add it under Manage models, or switch to a local embedding model there.' Buttons are 'Manage models…' and 'Later' — no Ollama text, no setup_btn (setup=True branch is only reachable when is_ollama). Clicking 'Manage models…' calls manage_models_dialog() (setup=False); clicking 'Later' just falls through. Either way cfg['_first_run_done']=True is written and first_run_check returns. Because _first_run_dialog_shown_this_session is now True, setup_readiness_check() returns immediately on this same profile-open. On the *next* profile open, setup_readiness_check(): provider != 'ollama' -> calls _readiness_check_body() directly, skipping ensure_server/QueryOp/tooltip entirely (no background Ollama probe at all). _readiness_check_body() sees provider != 'ollama' -> delegates to _cloud_readiness_check, which re-checks the key: still empty -> shows the same warning (unless the user already hit Skip, which set _embed_key_setup_declined=True and short-circuits it silently). Once the user pastes a Voyage key via Manage models, _embedding_ready/_cloud_readiness_check both see a non-empty cfg['embedding_api_key_voyage'] and go silent. At no point in this file does a Voyage-default user's console, dialog text, or button label mention Ollama. Files: klausmate/setup_flow.py only. Risks: manage_models.py's refresh() (lines ~507-539, read-only reference, not touched) routes to show_install_page() (the 'Install Ollama' page) whenever Ollama is unreachable, with no check of the configured embedding provider. That means if a Voyage user proactively clicks 'Manage models…' from my dialog (as opposed to the passive per-profile-open flow, which is Ollama-clean), and Ollama isn't installed/running, manage_models_dialog() will still land them on the Ollama install page today. That's a manage_models.py bug outside this card's file scope (a sibling worker owns that file right now) — flagging for a follow-up card rather than fixing it here. Also: 'starter pull' logic (maybe_auto_pull_starter, _MODEL_PRESETS[0]) lives entirely in manage_models.py; card item 4 (make it pull nomic-embed-text, not a text model, only for local provider) needs to land there, not in this file. Next: follow-up card to make manage_models.py's page routing (refresh/show_install_page) and its first-run auto-pull provider-aware, matching the gating done here in setup_flow.py.
- [2026-08-23 orchestrator] Independently re-verified and signed off. The core goal is met: every Ollama path (reachability probe, silent ensure_server autostart, runtime-update offer) is now gated on provider == 'ollama', and I traced the Voyage-default path myself — fresh profile resolves to voyage, first_run_check takes the cloud branch, setup_readiness_check short-circuits to _cloud_readiness_check before any probe. No Ollama string reaches a cloud user. I specifically checked whether _embedding_ready's client(5.0).health() introduces a main-thread blocking call at startup: it does NOT regress anything — the pre-K-029 first_run_check made that exact same 5s call UNCONDITIONALLY for every user; this change narrows it to Ollama profiles only, which is a strict improvement. _first_run_dialog_shown_this_session and both readers stayed together. New state key _embed_key_setup_declined mirrors the existing _runtime_setup_declined convention (underscore-prefixed, so _migrate_config leaves it alone). Full suite 234 green; py_compile clean through the symlink. Worker's out-of-scope finding about manage_models.py's install-page routing is real and I am filing it as its own card.
