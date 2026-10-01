# Klaus add-on — domain glossary

One line per term; the narrative and the gotchas are in `CLAUDE.md`.
Use these names in code, cards, specs and reviews.

- **Settings store** — `klausmate/settings.py`: `read()`, `patch(updates, remove=())` (the one writer), `user_files()`, `register_migration`/`migrate()`. `__init__` installs the Anki adapter; tests install a `DictStore`. No whole-blob writer exists.
- **Preferences state machine** — `klausmate/prefs_state.py`: `PrefsState.from_config` / `set` / `reseed` / `view` / `dirty` / `discard` / `commit() -> Commit(patch, effects)`. Every value the Preferences dialog edits; dirty is a fact; Save writes one patch of changed keys and runs the effects in a fixed order.
- **Page adapter** — a `_Binding` in `manage_models.py`: one widget bound to one state key (signal = edit, `paint()` = state → widget under the syncing scope). The page keeps only its operations (Ollama install/pull, Index Now, library folder, image copies).
- **Library** — the `!Library` tag branch in Browse's sidebar; PDFs live in the user-chosen library root, `library_map.json` maps safe names to paths (`pdf_handler.pdf_path_for` is the one resolver).
- **Reader host** — `klausmate/reader_host.py`: the ONE PDF reader (`reader_panel.PdfSidebar`, `host_key="editor"`) and its two homes: `set_home()` (the Add tab's reader slot), `lend()`/`give_back()` (Browse's viewer mode borrows it), `release()` (cleanup + forget; a cleaned reader is never reused). Never re-parented across top-level windows.
- **Add tab** — the third host page (Library tree | PDF reader | Add editor) replacing the Add dock; `library_tree.py` is Klaus's own Library view, `reader_host.py` owns the one reader (`set_home()`, `reader()`, `lend()`, `give_back()`, `release()`) whose two homes are the Add tab's middle and Browse's viewer mode.
- **Manual indexing** — `index_queue.refresh(parent)`, the Library's ⟳ (beside the filter in Browse's sidebar toolbar and the Add tab's tree), is the only thing that starts indexing: it queues every PDF that `needs_indexing` or has a stale match cache, minus excluded and queued ones. Imports, profile open, rescans and model changes never index.
- **Excluded (from the index)** — a PDF or folder in `drive.json`'s `excluded` lists (`drive_store.set_excluded` / `is_excluded`); a folder covers its subfolders and later imports. Excluding deletes the covered PDFs' index dirs (confirm first when any exist); their cards keep their `!Library` tags.
- **Task readout** — `tasks.py`'s one list of running processes, drawn by Browse's status bar and the main window's bottom row.
- **Index runner** — `index_queue.py`: the four-phase chain every index request runs (card index → PDF index → matches → tag sync), queued behind `curation._busy`.
- **Tag sync invariant** — every indexed PDF owns exactly one `!Library::<folder>::<leaf>` tag whose members are exactly the notes at or above its threshold (`tag_sync.py`).
- **Single window** — `single_window.py` + `host_keys.py`: Decks, Add and Browse as tabs, Edit Current in a right dock; Anki's windows are built inside their containers, never moved.
- **Design gate** — `background.design_enabled(cfg)` (`klausbook_design`, default off): the full KlausBook look is opt-in and enforced at the painters, never in `resolve()`.
