# Manual indexing, excluded PDFs, Library header icons — design

Date: 2026-10-01. Status: decided in conversation (Q1–Q9); awaiting written-spec review.

## Goal

Indexing happens only when Pouya asks for it. A refresh icon beside the Library filter indexes everything that needs it. PDFs and folders can be excluded from indexing. The Import PDFs… footer becomes a +PDF icon in the same header row. The Duplicates strip under Browse's card list goes.

Success means:
- Importing a PDF, opening a profile, rescanning the library folder or changing the embedding model never starts an indexing job.
- One click on ⟳ queues every PDF that needs indexing and is not excluded.
- An excluded PDF or folder is never indexed, and its index data is deleted when it is excluded.
- Browse's sidebar and the Add tab's Library tree both show the filter, ⟳ and +PDF on one row, with no footer under the tree.
- Browse shows no Duplicates button.

## Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | When indexing runs | Only on ⟳. No indexing on import, no catch-up on profile open. The `auto_index_on_add` preference is removed. |
| Q2 | What ⟳ indexes | PDFs never indexed, partly indexed, or changed since indexing (file, model, index version), minus excluded ones. |
| Q3 | How to exclude | Right-click "Exclude from Index" / "Include in Index" on a PDF or folder. A folder covers its subfolders and PDFs added later. Excluded rows are dimmed and show no warning icon. |
| Q4 | An excluded PDF's index data | Deleted. |
| Q5 | Where the icons go | Browse's sidebar and the Add tab's tree. The footer goes from both. The right-click Import items stay. |
| Q6 | Duplicates | The whole strip under Browse's card list goes. The engine (`duplicates.py`) and its tests stay for a later UI. |
| Q7 | Refresh feedback | A tooltip ("Indexing 5 PDFs" / "Everything is indexed"); progress in the status bar as today; pressing ⟳ while a run is going adds only PDFs not already queued. |
| Q8 | Confirm before deleting | A window-modal confirm when the exclusion deletes index data; none when there is nothing to delete. A folder's confirm counts the indexed PDFs it covers. |
| Q9 | Embedding model change | The re-index prompt goes. A tooltip says "Press ⟳ in the Library to re-index for the new model." |

## Current state

- `index_queue.on_pdf_imported` queues every import (`klausmate/__init__.py:562`, `pdf_drive.py:377`), gated on `auto_index_enabled` (config key `auto_index_on_add`, default on).
- At profile open, once Ollama answers, `setup_flow` runs `_offer_v2_index_sweep` (a priced prompt for pre-v2 indexes), `_rematch_stale_matches` (K-302) and `_resume_unindexed`.
- `pdf_drive`'s rescan re-queues PDFs whose text changed (`pdf_drive.py:474`).
- Preferences' Save runs `index_queue.offer_model_sweep` when the embedding signature moved (`manage_models.py:1729`).
- `library_sidebar.Footer` holds the "Import PDFs…" button. `_install_footer` adds it under Browse's sidebar, and `library_tree.LibraryTree` adds it under its view.
- Browse's sidebar header is Anki's grid row 0: `sidebar.searchBar` at (0,0), `sidebar.toolbar` (a `SidebarToolbar`, a `QToolBar` with the Search/Select tools) at (0,1). Read from the 25.09 source and confirmed in the 26.09 bytecode. `SidebarToolbar._update_icons` walks only its own action group, so extra actions added to the toolbar survive theme changes untouched.
- `browse_toolkit` installs a strip (`BrowseToolkit`) under the note list on `browser_will_show`. Its only tool is Duplicates.
- `pdf_index.delete(user_files, name)` removes one PDF's index directory: vectors, manifest and match cache.
- A PDF's retention % comes from its Library tag on notes (`library_sidebar.compute_means`), which tag sync keeps equal to the PDF's matches.

## Architecture

### What needs indexing (`index_queue`)

One pure predicate decides, and ⟳ is its only caller that queues:

- `needs_indexing(stats, current_source_sig, signature) -> bool` is True when the manifest is missing, incomplete, written by an older `INDEX_VERSION`, built with another embedding signature, or built from another source signature. It reads manifest stats only, never vectors.
- `pdf_index.stats_from_disk` gains `"source_sig"` and `"version"` keys so the predicate can read them.
- `refresh_jobs(names, excluded, pending, needs, stale_matches) -> list[job]` is pure: every name that needs indexing or has a stale match cache (K-302), minus excluded ones, minus ones already queued, in Library order.
- `refresh(parent) -> int` builds the jobs, calls `request(jobs, announce=False)`, shows the tooltip, and returns the count. It also deletes the index data of any excluded PDF that still has some (see "Folder moves" below).

The card index (notes) is unchanged. A PDF job's phase one still brings it up to date, and the K-237 confirm still guards a from-scratch rebuild of the whole collection. When no PDF needs work but the card index needs a from-scratch rebuild, ⟳ queues one `JOB_CARDS`.

### Removing automatic indexing

- `on_pdf_imported`, `resume_unindexed`, `auto_index_enabled`, `CONFIG_KEY` and the `auto_index_on_add` entries in `config.json` and `config.md` are deleted. The import funnel no longer calls into `index_queue`.
- `setup_flow` stops calling `_offer_v2_index_sweep`, `_rematch_stale_matches` and `_resume_unindexed`. ⟳ covers all three: pre-v2 manifests, stale match caches and unindexed PDFs.
- `pdf_drive`'s rescan stops queueing changed PDFs. The changed PDF shows its warning icon, and ⟳ picks it up.
- `offer_model_sweep` and its message helpers (`sweep_message`, `sweep_jobs`) are deleted. Preferences' Save shows the Q9 tooltip instead, when the signature moved.
- The `_v2_index_sweep_offered` flag stays in existing configs and is no longer read. meta.json is never edited.

### Excluded PDFs and folders (`drive_store`)

- `drive.json` gains `"excluded": {"pdfs": [safe…], "folders": [path…]}`. A file without the key loads as nothing excluded, so `DRIVE_VERSION` stays 1.
- Pure helpers: `is_excluded(data, safe) -> bool` (the PDF is listed, or its folder is an excluded folder or under one), `set_excluded(user_files, kind, key, on)`, and `excluded_safes(data, safes) -> set`.
- `rename_folder` rewrites excluded folder paths with the same prefix swap it uses for folders. `remove_folder` drops the folder from the excluded list (its PDFs reparent and stop being excluded through it). `remove_pdf` drops the PDF from the list.

### Excluding from the menu (`library_sidebar.menu_entries`)

- PDF and folder rows get "Exclude from Index" or "Include in Index", whichever applies. A PDF inside an excluded folder shows neither: the folder decides.
- Exclude on a PDF with index data, or on a folder covering indexed PDFs, opens a window-modal confirm (`open()`, K-114). PDF text: "Exclude 'Hemolysis' from the index? Its search index is deleted. Its cards keep their Library tag." Folder text: "Exclude 'Exam 1' from the index? The search index of 4 PDFs in it is deleted. Their cards keep their Library tags." Buttons: Exclude, Cancel (default).
- On Exclude: record the exclusion, `index_queue.forget` each covered PDF's queued jobs, `pdf_index.delete` each covered PDF, then `refresh_status()` and `refresh_trees()`.
- Include removes the exclusion and refreshes the rows. It queues nothing. The rows show their warning icon until ⟳.

### Rows

- `pdf_status` takes the excluded set: an excluded PDF gets no reason, so no warning icon.
- `LibraryNameDelegate` draws excluded PDF and folder names in the disabled text colour, and the tooltip says "Excluded from the index".
- The retention % keeps drawing. It comes from card tags, which exclusion does not touch.

### Header icons

- One factory, `library_sidebar.header_actions(parent) -> (refresh_action, add_action)`, builds two `QAction`s: ⟳ "Index New and Changed PDFs" calls `index_queue.refresh(parent)`, and +PDF "Import PDFs…" calls `library_actions.pick_and_import(parent)`.
- Icons are two new SVGs beside the Library icons (`web/library-refresh.svg`, `web/library-add-pdf.svg`), drawn in the same style and re-tinted on `theme_did_change`.
- Browse: `on_browser_will_show` adds the two actions to `browser.sidebar.toolbar` after a separator, once per Browse (attribute guard). `_install_footer` and `Footer` are deleted. The Finder-drop filter stays on the sidebar viewport.
- Add tab: `LibraryTree` puts the filter and a small `QToolBar` with the same two actions on one row. Its footer goes, and its drop filter stays on the view's viewport.

### Duplicates strip

- `browse_toolkit.setup_hooks` is no longer called from `klausmate/__init__.py`. `browse_toolkit.py` and its tests are deleted, since the strip has no other tool. `duplicates.py` and `tests/test_duplicates.py` stay, with no importer until a new UI uses them. Nothing else imports `browse_toolkit`.

## Data flow

1. ⟳ → `index_queue.refresh` → `refresh_jobs(...)` over the Library's PDFs → `request(jobs)` → the queue runs as today → the status bar shows progress → `_on_index_state` refreshes the warning icons.
2. Exclude → confirm → `drive_store.set_excluded` → `forget` + `pdf_index.delete` → rows repaint dimmed.
3. Import (any surface) → `import_pdf_file` → the PDF appears with a "not indexed" warning icon → ⟳.

## Error handling

- `refresh` never raises into Qt. A failed manifest read counts as "needs indexing", the scan's existing rule. Any other failure prints and shows "Couldn't check the Library for new PDFs."
- No profile open: ⟳ shows "Open a profile first." and queues nothing.
- `pdf_index.delete` already ignores a missing directory. A failed `drive.json` write leaves the exclusion unrecorded and deletes nothing: the exclusion is recorded first, and deletion runs only after the write succeeded.

## Folder moves

Moving a PDF into an excluded folder (a tag operation in Browse) makes it excluded but leaves its index data on disk. The next ⟳ deletes that data with no prompt, since the folder exclusion was already confirmed. Until then the PDF still matches and searches as before.

## Testing

Offscreen tests with `anki_stubs`, temp user_files only:
- `tests/test_index_queue.py`: `needs_indexing` for missing, partial, old version, other signature, other source signature and fresh manifests; `refresh_jobs` drops excluded, pending and fresh PDFs and keeps stale-match ones; refresh with nothing to do tooltips "Everything is indexed"; the deleted names (`on_pdf_imported`, `resume_unindexed`, `auto_index_enabled`, `offer_model_sweep`) are gone.
- `tests/test_drive.py`: exclusion round-trips, a folder covers nested folders and later PDFs, rename carries it, folder and PDF removal drop it, a file without the key loads as nothing excluded.
- `tests/test_library_sidebar.py`: menu entries for excluded / included / inside-excluded-folder rows; the confirm appears only when index data exists; Exclude deletes the index dir and forgets queued jobs; `pdf_status` gives an excluded PDF no reason; no `Footer` and no footer in Browse; the toolbar gets the two actions once.
- `tests/test_library_tree.py`: the header row has the filter and both actions; no footer; drops still accepted on the view.
- Removal pins: no `browse_toolkit.setup_hooks` call in `__init__`; `setup_flow` no longer calls the three profile-open sweeps; the rescan queues nothing; `import_pdf_file` no longer calls `index_queue`; `config.json` has no `auto_index_on_add`.

Live checklist (Pouya):
1. Import a PDF: no indexing starts; the row shows its warning icon.
2. Press ⟳ in Browse: the tooltip counts the PDFs and the status bar shows progress. Press it again mid-run: nothing doubles.
3. Exclude an indexed PDF: confirm, the row dims, the warning icon goes, ⟳ skips it. Include it: the warning icon comes back.
4. Exclude a folder, import a PDF into it: the new PDF is dimmed and ⟳ skips it.
5. The Add tab tree shows the same row; +PDF opens the file picker in both places.
6. Browse shows no Duplicates strip.
7. Restart Anki: nothing indexes on profile open.

## Rulings

- **Exclusion keeps card tags.** A PDF's Library tag membership is its match result, and the retention % is computed from it. Removing those tags would be a collection change that also drops links Pouya may rely on in Browse. So excluding deletes only the index directory, and the % stays. This corrects the Q8 wording in conversation, which said the % goes away.
- **Stale matches and pre-v2 indexes join ⟳.** Both used to run at profile open. Manual-only means they wait for ⟳ like everything else.
- **The K-237 card-index confirm stays.** ⟳ is one click and a from-scratch card re-embed takes a long time, so the existing Embed/Skip prompt keeps guarding it.
- **Exclusion lives in `drive.json`**, the Library's own local store beside folders and display names. It is not synced, like the index it governs.
- **The header actions go on Anki's `SidebarToolbar`**, not a new widget in its grid: the toolbar already sits beside the search box and needs no layout change.

## Out of scope

- A new Duplicates UI.
- Indexing on a schedule or in the background.
- Excluding PDFs from search without deleting their data.

## Risks

- Another add-on that also adds actions to `sidebar.toolbar` would sit beside Klaus's. Low risk; actions do not conflict.
- Deleting `browse_toolkit.py` drops its tests. If a later Duplicates UI wants pieces of the strip, they are in git history.
