# Manual Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Indexing runs only on a ⟳ press; PDFs and folders can be excluded (their index data deleted); the Library header carries ⟳ and +PDF instead of the Import footer; the Duplicates strip goes.

**Architecture:** Exclusion is stored in `drive.json` (`drive_store`, pure). `index_queue` gains one pure predicate and one pure job planner behind `refresh(parent)`, and loses every automatic trigger. `library_sidebar` builds the menu items, the row dimming and the two header actions once; Browse's `SidebarToolbar` and the Add tab's `LibraryTree` both use them.

**Tech Stack:** Python 3.13, PyQt6 6.11 via `aqt.qt`, Anki 26.09.2; offscreen tests with `anki_stubs` (`check`/`section`/`report`).

**Spec:** `docs/superpowers/specs/2026-10-01-manual-indexing-design.md`

## Global Constraints

- No app-modal `exec()` / `askUser` / `QMessageBox.question` (K-114): confirms are a `QMessageBox` instance with `open()` and `finished`.
- Tests use temp dirs only; never touch `klausmate/user_files`. Never edit or stage `meta.json*` or `user_files/`.
- Never drive the running Anki. Edit the main checkout (Anki loads it via symlink).
- No commit per task. Pouya asks for commits; when asked, stage by name, check `git diff --cached --stat` and `git rev-parse HEAD` in the same command as the commit, and never `git reset -- <path>` a path another session staged.
- Copy, exact: menu "Exclude from Index" / "Include in Index"; header "Index New and Changed PDFs" (⟳) and "Import PDFs…" (+PDF); excluded row tooltip "Excluded from the index"; Q9 tooltip "Press ⟳ in the Library to re-index for the new model."; errors "Couldn't check the Library for new PDFs." and "Open a profile first."; refresh "Everything is indexed".
- Confirm copy, exact. PDF: "Exclude “{name}” from the index? Its search index is deleted. Its cards keep their Library tag." Folder: "Exclude “{name}” from the index? The search index of {n} PDF(s) in it is deleted. Their cards keep their Library tags." ("1 PDF", "4 PDFs"). Buttons: Exclude, Cancel; Cancel is the default.
- Run one file: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/<file>.py`. Whole suite: `failed=0; for t in tests/test_*.py; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 "$t" || failed=1; done; test "$failed" -eq 0`. Known failures at HEAD from other sessions (test_top_bar, two logo pins) are reported, not fixed.
- Peer session "Klausmate Frontend" is on Image Occlusion Task 4 (`reader_panel.py`, `pdfjs_viewer.py/.html`). This plan does not touch those files.

## Review Focus

1. A PDF excluded while its own job is RUNNING: the job finishes and writes an index. Expected: no index survives. Pinned in Task 2 (a finished job for an excluded PDF deletes its index).
2. A corrupt or unreadable `drive.json`: `load` returns the default, so nothing reads as excluded. Expected: ⟳ still works and indexes everything; no crash. Pinned in Task 1.
3. Exclude/Include from the Add tab's tree must repaint Browse's sidebar too, and the reverse. Pinned in Task 3 (both `refresh_status` and `refresh_trees` run).
4. ⟳ pressed with no profile, or while a run is going. Expected: "Open a profile first." / only unqueued PDFs added. Pinned in Task 2.
5. The Library root row and a PDF inside an excluded folder offer no Exclude/Include item. Pinned in Task 3.

---

### Task 1: Exclusion in drive.json

**Files:**
- Modify: `klausmate/drive_store.py` (`_default`, `load`, `rename_folder`, `remove_folder`, `remove_pdf`; schema docstring)
- Test: `tests/test_drive.py`

**Interfaces:**
- Produces: `drive_store.is_excluded(data: dict, safe: str) -> bool`; `drive_store.folder_excluded(data: dict, folder: str | None) -> bool`; `drive_store.excluded_safes(data: dict, safes) -> set[str]`; `drive_store.set_excluded(user_files_dir: str, kind: str, key: str, on: bool) -> bool` (`kind` is `"pdf"` or `"folder"`; returns False when the write failed). `load(...)["excluded"] == {"pdfs": [...], "folders": [...]}` always present.

- [ ] **Step 1: Write the failing tests** in a new `section("exclusion")` of `tests/test_drive.py`, temp user_files:

```python
uf = tempfile.mkdtemp()
ds.record_import(uf, "Hemo", "Hemo.pdf"); ds.add_folder(uf, "Exam 1/Week 1"); ds.set_folder(uf, "CBC", "Exam 1/Week 1")
check("a file without the key loads as nothing excluded", ds.load(uf)["excluded"] == {"pdfs": [], "folders": []})
check("set_excluded pdf round-trips", ds.set_excluded(uf, "pdf", "Hemo", True) and ds.is_excluded(ds.load(uf), "Hemo"))
ds.set_excluded(uf, "folder", "Exam 1", True)
check("a folder covers nested folders' PDFs", ds.is_excluded(ds.load(uf), "CBC") and ds.folder_excluded(ds.load(uf), "Exam 1/Week 1"))
ds.record_import(uf, "Later", "Later.pdf"); ds.set_folder(uf, "Later", "Exam 1")
check("...and PDFs added later", ds.is_excluded(ds.load(uf), "Later"))
check("a sibling folder is not covered", not ds.folder_excluded(ds.load(uf), "Exam 10"))
ds.rename_folder(uf, "Exam 1", "Exam A")
check("rename carries the exclusion", ds.load(uf)["excluded"]["folders"] == ["Exam A"] and ds.is_excluded(ds.load(uf), "CBC"))
ds.remove_folder(uf, "Exam A")
check("removing the folder drops it", ds.load(uf)["excluded"]["folders"] == [] and not ds.is_excluded(ds.load(uf), "CBC"))
ds.remove_pdf(uf, "Hemo")
check("removing the PDF drops it", ds.load(uf)["excluded"]["pdfs"] == [])
ds.set_excluded(uf, "pdf", "X", True); ds.set_excluded(uf, "pdf", "X", False)
check("include removes it", ds.load(uf)["excluded"]["pdfs"] == [])
open(ds._drive_path(uf), "w").write("{corrupt")
check("a corrupt file reads as nothing excluded", not ds.is_excluded(ds.load(uf), "CBC") and ds.excluded_safes(ds.load(uf), {"CBC"}) == set())
```

- [ ] **Step 2: Run, expect FAIL** (`KeyError: 'excluded'` / no attribute `set_excluded`).
- [ ] **Step 3: Implement.** `excluded` lists are sorted and de-duplicated on save; `load` keeps only strings (folders through `_valid_folder`). `folder_excluded` is true when `folder` equals an excluded folder or starts with it plus `"/"`. `is_excluded` checks the PDF list, then `folder_excluded` on the PDF's `folder`. `rename_folder` applies its `swap` to the excluded folders; `remove_folder` drops `path` and anything under it from them; `remove_pdf` drops the safe. `set_excluded` catches `OSError` from `_save` and returns False.
- [ ] **Step 4: Run, expect PASS**; also run `tests/test_library_sidebar.py` and `tests/test_library_tree.py` (they read drive.json).

---

### Task 2: What needs indexing, and ⟳

**Files:**
- Modify: `klausmate/pdf_index.py` (`stats_from_disk`, `_EMPTY_STATS`), `klausmate/index_queue.py`
- Test: `tests/test_index_queue.py` (new sections), `tests/test_klausmate.py` if it pins the stats key set

**Interfaces:**
- Consumes: `drive_store.excluded_safes`, `drive_store.load`.
- Produces: `pdf_index.stats_from_disk(...)` gains `"source_sig": tuple[int, int] | None` and `"version": int` (`_EMPTY_STATS`: `None`, `0`). `index_queue.needs_indexing(stats: dict, source_sig, signature) -> bool`; `index_queue.refresh_jobs(names: list[str], excluded: set, pending: set, needs: Callable[[str], bool], stale_matches: set, cards_from_scratch: bool) -> list[tuple[str, str]]`; `index_queue.refresh_message(n_pdfs: int, cards: bool) -> str`; `index_queue.refresh(parent=None) -> int`.

- [ ] **Step 1: Write the failing tests.** Pure first:

```python
sig = ("ollama", "nomic-embed-text", 0)
fresh = {"exists": True, "complete": True, "version": pdf_index.INDEX_VERSION, "provider": "ollama",
         "model": "nomic-embed-text", "dims": 768, "source_sig": (5, 10)}
check("fresh is not needed", not iq.needs_indexing(fresh, (5, 10), sig))
for label, patch in (("missing", {"exists": False}), ("partial", {"complete": False}),
                     ("old version", {"version": 1}), ("other model", {"model": "bge-m3"}),
                     ("other source", {"source_sig": (6, 10)})):
    check(f"{label} is needed", iq.needs_indexing({**fresh, **patch}, (5, 10), sig))
check("a vanished source is needed", iq.needs_indexing(fresh, None, sig))
needs = lambda n: n in {"a", "b", "c"}  # noqa: E731
check("refresh_jobs drops excluded and pending, keeps stale matches, keeps order",
      iq.refresh_jobs(["a", "b", "c", "d", "e"], {"b"}, {"c"}, needs, {"d", "b"}, False)
      == [("pdf", "a"), ("pdf", "d")])
check("cards only when no PDF job", iq.refresh_jobs([], set(), set(), needs, set(), True) == [("cards", "")]
      and ("cards", "") not in iq.refresh_jobs(["a"], set(), set(), needs, set(), True))
check("messages", iq.refresh_message(0, False) == "Everything is indexed"
      and iq.refresh_message(1, False) == "Indexing 1 PDF" and iq.refresh_message(5, False) == "Indexing 5 PDFs"
      and iq.refresh_message(0, True) == "Rebuilding the card index")
```

Then behaviour, with `new_world(names=("a", "b"))`, a `_Tips` recorder as `iq.tooltip`, and a fresh manifest written for `"a"` with `source_sig` equal to `pdf_index.source_signature(tmp, "a")`:
  - `iq.refresh()` returns 1, `pending_names() == {"b"}`, last tooltip "Indexing 1 PDF".
  - A second `iq.refresh()` returns 0 and queues nothing new (Review Focus 4).
  - With `drive_store.set_excluded(tmp, "pdf", "b", True)` after `cancel_all()`: `refresh()` returns 0 and tooltips "Everything is indexed".
  - With `iq.mw.col = None`: `refresh()` returns 0 and tooltips "Open a profile first."
  - A corrupt `drive.json`: `refresh()` still queues `"b"` (Review Focus 2).
  - With `_manifest_paths` patched to raise: returns 0 and tooltips "Couldn't check the Library for new PDFs."
  - Review Focus 1: run the chain for `"b"` (the file's existing chain helpers), excluding `"b"` before the job completes; after completion `os.path.isdir(pdf_index.index_dir(tmp, "b"))` is False.
  - An excluded PDF that still has an index dir loses it on `refresh()` (spec "Folder moves").

- [ ] **Step 2: Run, expect FAIL** (no `needs_indexing`).
- [ ] **Step 3: Implement.**
  - `stats_from_disk` reads `version` and `source_sig` from the manifest it already parsed. `read_manifest` returns None for other versions, so `needs_indexing` treats `exists=False` as needed and the version check covers a manifest that parsed.
  - `needs_indexing`: needed unless exists, complete, version == `INDEX_VERSION`, `embeddings.signature_matches(provider, model, dims, signature)`, and `source_sig` is not None and equals the stats' `source_sig`.
  - `refresh(parent=None)`: no `mw.col` → tooltip and 0. Inside one `try`: names from `_manifest_paths()`; `excluded = drive_store.excluded_safes(drive_store.load(settings.user_files()), names)`; purge `pdf_index.delete` for excluded names whose index dir exists, plus `forget(name)`; `needs` reads `pdf_index.stats_from_disk(index_dir)` and `pdf_index.source_signature`; `stale_matches = set(stale_match_names())`; `cards_from_scratch = card_index_from_scratch(settings.read())`; `request(jobs, announce=False)`; tooltip `refresh_message`. Any exception: print, tooltip the error copy, return 0.
  - Review Focus 1: where a PDF job completes (`_job_done` with `finished` set, or the end of `_run`), if `drive_store.is_excluded(load(...), name)` then `pdf_index.delete(user_files, name)`.
- [ ] **Step 4: Run, expect PASS.** Run `tests/test_index_queue.py`, `tests/test_klausmate.py`, `tests/test_rescan.py`.

---

### Task 3: Exclude and Include from the Library menu; dimmed rows

**Files:**
- Modify: `klausmate/library_sidebar.py` (`build_index`, `menu_entries`, `pdf_status` call in `refresh_status`, `LibraryNameDelegate.initStyleOption`/`helpEvent`), `klausmate/library_actions.py`
- Test: `tests/test_library_sidebar.py`, `tests/test_library_tree.py` (its menu-label pins)

**Interfaces:**
- Consumes: Task 1's `drive_store` helpers; `pdf_index.delete`, `pdf_index.stats_from_disk`, `index_queue.forget`.
- Produces: `library_index()["excluded"]: set[str]` (casefolded tags of excluded PDFs and folders, including those covered by an excluded ancestor folder); `library_sidebar.is_excluded_tag(tag) -> bool`; `library_actions.exclude(parent, kind: str, key: str, name: str) -> None`; `library_actions.include(kind: str, key: str) -> None`; `library_actions.exclude_confirm_text(name: str, kind: str, n_indexed: int) -> str`; test seam `library_actions._ask_exclude(parent, text: str, on_yes: Callable[[], None]) -> None`.

- [ ] **Step 1: Write the failing tests** (reuse the file's temp drive fixture):
  - `menu_entries` labels: an included PDF ends with `"Exclude from Index"`; after `set_excluded(pdf)` it shows `"Include in Index"`; a folder likewise; a PDF inside an excluded folder shows neither; the root shows neither (Review Focus 5).
  - `exclude_confirm_text("Hemolysis", "pdf", 1)` and `("Exam 1", "folder", 4)` and `("Exam 1", "folder", 1)` equal the Global Constraints copy exactly.
  - With `_ask_exclude` replaced by a recorder: excluding a PDF with an index dir asks once; calling the recorded `on_yes` writes the exclusion, deletes the index dir, and calls `index_queue.forget(safe)`. Excluding a PDF with no index dir asks nothing and records the exclusion. A folder covering two indexed PDFs asks with "2 PDFs" and deletes both dirs.
  - If `set_excluded` returns False, nothing is deleted (spec Error handling).
  - Exclude and include each call both `refresh_status` and `refresh_trees` (patch both, Review Focus 3).
  - Include queues nothing: `index_queue.pending_names()` is unchanged after `include`.
  - `pdf_status` gives an excluded safe no reason; the delegate's `initStyleOption` on an excluded row sets no warning icon and a disabled-role text colour; `helpEvent` tooltip text contains "Excluded from the index".
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
  - `build_index` computes `excluded` from the drive data it already receives, using `drive_store.is_excluded` / `folder_excluded`.
  - `menu_entries` appends the item after the row's existing entries: PDF → `act.exclude(parent, "pdf", safe, label)` or `act.include("pdf", safe)`; folder → same with `"folder"` and the folder path; skipped when the row is covered by an excluded ancestor.
  - `exclude` counts covered PDFs with `stats_from_disk(index_dir)["exists"]` or an existing index dir; zero → do it now; else `_ask_exclude`. Doing it: `set_excluded` first; only on True, `forget` + `pdf_index.delete` each covered safe; then `ls.refresh_status()` and `ls.refresh_trees()`.
  - `_ask_exclude`: `QMessageBox(parent)`, title "Exclude from Index", buttons Exclude (`DestructiveRole`) and Cancel (`RejectRole`, default), themed with `theme.dialog_qss`, `open()`, answer on `finished`.
  - Excluded rows: `refresh_status` passes `pending` and a status function that returns `(True, False)` for excluded safes, or `pdf_status` takes an `excluded` set; either way an excluded safe has no reason. The delegate sets `option.palette` text to the disabled colour when `is_excluded_tag(tag)`.
- [ ] **Step 4: Run, expect PASS** (`test_library_sidebar.py`, `test_library_tree.py`).

---

### Task 4: Remove automatic indexing

**Files:**
- Modify: `klausmate/index_queue.py`, `klausmate/__init__.py:555-565`, `klausmate/pdf_drive.py` (`_tell_readers`), `klausmate/setup_flow.py:340-412`, `klausmate/manage_models.py:1722-1731`, `klausmate/config.json`, `klausmate/config.md`
- Test: `tests/test_index_queue.py`, `tests/test_rescan.py`, `tests/test_bridge_reentrancy.py`, `tests/test_local_model_settings.py`, `tests/test_dialog_logic.py`, `tests/test_setup_crop_theme.py`, `tests/test_local_embeddings.py`

**Interfaces:**
- Consumes: Task 2's `refresh` (only for the Q9 tooltip text's meaning; no call).
- Produces: none. Deleted: `index_queue.on_pdf_imported`, `resume_unindexed`, `auto_index_enabled`, `_truthy` (if callerless), `CONFIG_KEY`, `offer_model_sweep`, `sweep_message`, `sweep_jobs`; `setup_flow._offer_v2_index_sweep`, `_rematch_stale_matches`, `_resume_unindexed`. Then delete `indexed_pdf_names`, `unindexed_pdf_names`, `stale_index_names` only if `grep -rn` finds no remaining caller.

- [ ] **Step 1: Write the failing removal pins** in a new `section("indexing is manual only")` of `tests/test_index_queue.py`:

```python
for gone in ("on_pdf_imported", "resume_unindexed", "auto_index_enabled", "offer_model_sweep", "sweep_message", "sweep_jobs", "CONFIG_KEY"):
    check(f"index_queue.{gone} is gone", not hasattr(iq, gone))
sf = open("klausmate/setup_flow.py").read()
check("profile open runs no sweep", not any(n in sf for n in ("_offer_v2_index_sweep", "_rematch_stale_matches", "_resume_unindexed")))
check("imports do not index", "on_pdf_imported" not in open("klausmate/__init__.py").read())
check("the rescan queues nothing", "index_queue" not in open("klausmate/pdf_drive.py").read().split("def _tell_readers")[1].split("\ndef ")[0])
check("config has no auto_index_on_add", "auto_index_on_add" not in open("klausmate/config.json").read() and "auto_index_on_add" not in open("klausmate/config.md").read())
mm = open("klausmate/manage_models.py").read()
check("model change tooltips instead of prompting", "offer_model_sweep" not in mm and "Press ⟳ in the Library to re-index for the new model." in mm)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement the deletions.** `import_pdf_file`'s `try` block that calls `on_pdf_imported` goes. The rescan keeps its `changed_text` refresh of readers and drops the queueing loop. `setup_flow`'s readiness `done` keeps everything except the three calls. `_run_index_sweep` becomes `update_embed_status()` plus `tooltip("Press ⟳ in the Library to re-index for the new model.", parent=dlg)`. Remove the `auto_index_on_add` line from `config.json` and its entry from `config.md`.
- [ ] **Step 4: Repoint the old pins.** In `test_index_queue.py` delete the "config gates" section, the `offer_model_sweep` checks in "the sweep set", the resume-pass section's `resume_unindexed` checks and "local sweep avoids paid estimates" if it only covers `sweep_message`; keep any check whose subject survives. `test_rescan.py`: drop the `on_pdf_imported`/`auto_index_enabled` patches and assert the changed-text path queues nothing. `test_bridge_reentrancy.py:421-436`: replace the v2-sweep pin with a pin that the readiness path calls none of the three. `test_local_model_settings.py:57` and `test_dialog_logic.py:442`: pin the tooltip text instead of the sweep. `test_setup_crop_theme.py:240-256` and `test_local_embeddings.py:67`: drop the `_offer_v2_index_sweep` patch and any expectation of a `'sweep'` event.
- [ ] **Step 5: Run the suite, expect PASS** except the known HEAD failures.

---

### Task 5: Header icons; the footer goes

**Files:**
- Create: `klausmate/web/library-refresh.svg`, `klausmate/web/library-add-pdf.svg`
- Modify: `klausmate/library_sidebar.py` (delete `Footer`, `_install_footer`; add `header_actions`, `_install_header`; `on_browser_will_show`), `klausmate/library_tree.py` (header row, no footer)
- Test: `tests/test_library_sidebar.py`, `tests/test_library_tree.py`, `tests/test_add_tab.py` if it pins the footer

**Interfaces:**
- Consumes: Task 2's `index_queue.refresh(parent)`; `library_actions.pick_and_import(parent)`.
- Produces: `library_sidebar.header_actions(parent) -> tuple[QAction, QAction]` (refresh first, +PDF second; `objectName`s `klausmate_library_refresh` and `klausmate_library_add_pdf`); `library_sidebar.REFRESH_ICON`, `ADD_PDF_ICON` paths; `LibraryTree.header` (a `QToolBar` holding the two actions) beside `LibraryTree.filter`.

- [ ] **Step 1: Write the failing tests.**
  - `header_actions(w)` texts/tooltips are "Index New and Changed PDFs" and "Import PDFs…", icons non-null; triggering the first calls a patched `index_queue.refresh` with `w`, the second a patched `library_actions.pick_and_import` with `w`.
  - Browse: a fake browser whose `sidebar.toolbar` is a real `QToolBar`; `on_browser_will_show` twice → the toolbar holds the two actions once (by objectName), after a separator; `browser.sidebarDockWidget` grid gets no new row; the drop filter is still on `sidebar.viewport()`.
  - `ls.Footer` and `ls._install_footer` no longer exist.
  - `LibraryTree`: the filter and `tree.header` share one `QHBoxLayout` row at the top; `tree.header` holds the two actions; no `tree.footer`; `tree.view.viewport().acceptDrops()` still True. Remove the tree's old footer pins.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** SVGs follow `library-pdf.svg`'s size and stroke style (a circular arrow; a page with a plus). `header_actions` sets `QIcon(path)`; on `theme_did_change` re-tint is not needed if the SVGs use the same fixed colour as the existing Library icons. `_install_header(browser)` guards with `browser._klausmate_library_header`, calls `toolbar.addSeparator()` and `addAction` twice. The Browse drop filter install that lived in `_install_footer` moves into `_install_header` (viewport only). `LibraryTree` replaces `self.footer` with `self.header = QToolBar(self)`, icon size 16, in an `QHBoxLayout` with the filter; the footer drop filter line goes.
- [ ] **Step 4: Run, expect PASS.**

---

### Task 6: The Duplicates strip goes

**Files:**
- Modify: `klausmate/__init__.py:815-820`
- Delete: `klausmate/browse_toolkit.py`, `tests/test_browse_toolkit.py`
- Test: `tests/test_anki_ops.py:274` (its `browse_toolkit` read), `tests/test_add_tab.py` (removal pin)

**Interfaces:** none.

- [ ] **Step 1: Write the failing pin** in `tests/test_add_tab.py`'s "removed" section: `not os.path.exists("klausmate/browse_toolkit.py")` and `"browse_toolkit" not in open("klausmate/__init__.py").read()` and `os.path.exists("klausmate/duplicates.py")`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Delete** the import and `setup_hooks()` call in `__init__`, `browse_toolkit.py`, `tests/test_browse_toolkit.py`; in `test_anki_ops.py` drop the checks that read `browse_toolkit.py`. `grep -rn browse_toolkit klausmate tests` must come back empty (docs are Task 7).
- [ ] **Step 4: Run the suite, expect PASS** except the known HEAD failures.

---

### Task 7: Docs

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`, `README.md`, `CONTEXT.md`, `klausmate/config.md` (already trimmed in Task 4), any `docs/` page that `grep -rln -e auto_index_on_add -e "Import PDFs…" -e browse_toolkit -e "Duplicates" -e resume_unindexed -e offer_model_sweep` finds outside `docs/superpowers/` and `docs/reference/`.

- [ ] **Step 1:** Run the grep above and list each hit.
- [ ] **Step 2:** Update each: indexing is manual (⟳ beside the Library filter, both trees); exclusion lives in `drive.json` and deletes index data, keeping card tags; the Library header holds ⟳ and +PDF; Browse has no Duplicates strip, the engine stays in `duplicates.py`. CONTEXT.md gets an "Excluded (from the index)" entry.
- [ ] **Step 3:** Re-run the grep; every remaining hit is historical (a dated decision log) or a spec/plan.
- [ ] **Step 4:** Run the whole suite one last time and record the result.
