# Klaus add-on — domain glossary

One line per term; the narrative and the gotchas are in `CLAUDE.md`.
Use these names in code, cards, specs and reviews.

- **Settings store** — `klausmate/settings.py`: `read()`, `patch(updates, remove=())` (the one writer), `user_files()`, `register_migration`/`migrate()`. `__init__` installs the Anki adapter; tests install a `DictStore`. No whole-blob writer exists.
- **Preferences state machine** — `klausmate/prefs_state.py`: `PrefsState.from_config` / `set` / `reseed` / `view` / `dirty` / `discard` / `commit() -> Commit(patch, effects)`. Every value the Preferences dialog edits; dirty is a fact; Save writes one patch of changed keys and runs the effects in a fixed order.
- **Page adapter** — a `_Binding` in `manage_models.py`: one widget bound to one state key (signal = edit, `paint()` = state → widget under the syncing scope). The page keeps only its operations (Ollama install/pull, Index Now, library folder, image copies).
- **Library** — the `!Library` tag branch in Browse's sidebar; PDFs live in the user-chosen library root, `library_map.json` maps safe names to paths (`pdf_handler.pdf_path_for` is the one resolver).
- **PDF dock** — the one `QDockWidget` PDF viewer panel (`PdfDock`), hosted by the main window under the single window; placement persists in `pdf_tabs.json`.
- **Task readout** — `tasks.py`'s one list of running processes, drawn by Browse's status bar and the main window's bottom row.
- **Index runner** — `index_queue.py`: the four-phase chain every index request runs (card index → PDF index → matches → tag sync), queued behind `curation._busy`.
- **Tag sync invariant** — every indexed PDF owns exactly one `!Library::<folder>::<leaf>` tag whose members are exactly the notes at or above its threshold (`tag_sync.py`).
- **Single window** — `single_window.py` + `host_keys.py`: Decks and Browse as tabs, Add and Edit Current in a right dock; Anki's windows are built inside their containers, never moved.
- **Design gate** — `background.design_enabled(cfg)` (`klausbook_design`, default off): the full KlausBook look is opt-in and enforced at the painters, never in `resolve()`.
