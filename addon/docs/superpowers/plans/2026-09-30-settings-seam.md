# Settings Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One aqt-free `settings` module owns the stored config, its migrations, the merge write and the user-files path; every reach-back into the package root goes.

**Architecture:** `klausmate/settings.py` with a store adapter at its seam (Anki's addon manager in production, a dict in tests) and module-attribute hooks for the main-thread hop and the profile token. The bootstrap installs the adapters and runs migrations on profile open. A mechanical sweep replaces every reach-back and every test injection.

**Tech Stack:** Python 3, `aqt` only in the bootstrap, the repo's offscreen harness (`anki_stubs`).

**Spec:** `docs/superpowers/specs/2026-09-30-settings-seam-design.md`

## Global Constraints

- `settings.py` never imports `aqt`; the only `aqt` touch is the bootstrap installing adapters.
- `patch` applies inline on the main thread (`threading.current_thread() is threading.main_thread()`), hops via `settings.run_on_main` otherwise, and is skipped when `settings.current_profile()` changed since the call.
- A migration is a pure `dict -> dict`; returning the same object (or an equal dict) means no write.
- No commits until the user asks; stage by name; never `user_files/` or `meta.json*`.
- Tests: `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/<file>.py`; the whole suite at the end; `tests/test_top_bar.py` fails at HEAD from another session's work.

## Review Focus

1. A background thread calling `patch` after the profile closed: must not write (Task 1 test "patch from a background thread after a profile switch is dropped").
2. Two migrations registered by retention where the scale one also clears per-PDF overrides: the side effect must fire exactly once and only when the flag was missing (Task 3 test).
3. `pdf_path_for` with no explicit root in production reads the library root from settings; in tests it must still work with no store installed (Task 3 test).
4. `dashboard.write_cfg` while a preview is armed: the preview re-patch survives the move (Task 3 test).
5. `exec_klausmate_under_qt` tests (`test_pdf_dock`, `test_bridge_reentrancy`, `test_local_model_settings`) that executed the old accessors: they must run with the scratch directory as `settings.user_files_dir` (Task 4).

---

### Task 1: `settings.py`

**Files:**
- Create: `klausmate/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `DictStore(cfg: dict)` with `read() -> dict` (deep-ish copy: `json.loads(json.dumps(...))`) and `write(cfg)`; `AnkiStore(addon_manager, package: str)` with the same two; module attributes `store` (default `DictStore({})`), `run_on_main = None`, `current_profile = None`, `user_files_dir` (module dir + `user_files`); `read()`, `patch(updates, *, remove=())`, `user_files()`, `register_migration(fn)`, `migrate() -> bool` (True if it wrote), `LEGACY_KEYS_DROPPED` (moved verbatim from `__init__`), `_scrub_legacy(cfg) -> dict` (the embeddings default + scrub, registered at import).

- [ ] **Step 1: Write the failing tests** — sections: DictStore copies on read; `read()` returns fresh dicts; `patch` merges and removes, inline on the main thread even with `run_on_main` set (a recording `run_on_main` is NOT called from the main thread); from a `threading.Thread`, `patch` goes through `run_on_main`; with `current_profile` returning a different token when the hop runs, the write is dropped; `user_files()` ends with `user_files` and follows an assignment to `user_files_dir`; migrations run in order, once, write back only on change, and `migrate()` returns False the second time; `_scrub_legacy` drops every key of `LEGACY_KEYS_DROPPED` and sets the embeddings default once (`_local_embeddings_migrated`).
- [ ] **Step 2: Run** → Expected: `ModuleNotFoundError: klausmate.settings`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → Expected: all checks pass.

---

### Task 2: Bootstrap installs the adapters; the package root loses the accessors; the harness follows

**Files:**
- Modify: `klausmate/__init__.py` (delete `get_config`, `write_config`, `patch_config`, `USER_FILES`, `_LEGACY_KEYS_DROPPED`, `_migrate_config`; install `settings.store = AnkiStore(mw.addonManager, __name__)`, `settings.run_on_main = mw.taskman.run_on_main`, `settings.current_profile = lambda: getattr(mw, "col", None)` right after the imports; `profile_did_open.append(settings.migrate)` replaces `_migrate_config`; its own `get_config()` uses become `settings.read()`)
- Modify: `.claude/skills/klaus-test/scripts/anki_stubs.py` (`install_package_stub` no longer sets `pkg.USER_FILES`; `exec_klausmate_under_qt` sets `settings.user_files_dir = scratch_user_files` before executing)
- Test: `tests/test_settings.py` gains a source pin: `klausmate/__init__.py` contains none of `def get_config`, `def write_config`, `def patch_config`, `USER_FILES =`, `_LEGACY_KEYS_DROPPED`.

- [ ] **Step 1: Write the pin** → Expected: FAIL (they still exist).
- [ ] **Step 2: Implement** (the other reach-backs still break at this point; that is Task 3).
- [ ] **Step 3: Run test_settings** → Expected: pass.

---

### Task 3: The module sweep

**Files:**
- Modify: `curation.py` (`USER_FILES`/`INDEX_DIR` → `index_dir()` and `settings.user_files()`; `_cfg` deleted; `_pkg` kept only for `_strip_html`), `retention.py` (`USER_FILES`/`INDEX_DIR` copies go; `_cfg` → `settings.read()`; the two migrations become pure and are registered at import; `curation._cfg()` plain-read call site → `settings.read()`), `index_queue.py` (`_cfg`, `_user_files` → settings), `pdf_handler.py` (`_live_library_root` → `settings.read()`), `pdf_drive.py` + `library_actions.py` (`_user_files`/`_uf` → `settings.user_files()`), `lecture_view.py`, `setup_flow.py` (four patches; `_pkg` deleted), `tag_migrate.py` (patch with `remove`; `_pkg` deleted), `tag_sync.py` (`_pkg` deleted), `manage_models.py` (three savers + library move → patch; `USER_FILES` reads → `settings.user_files()`; `_pkg` kept for `_apply_color_theme`), `dashboard.py` (`write_cfg` through settings), `anki_endpoint.py`, `pdf_viewer.py`, `pdfjs_viewer.py`, `browse_toolkit.py` (`curation.INDEX_DIR` → `curation.index_dir()`), `library_sidebar.py` (`curation.USER_FILES` → `settings.user_files()`).
- Test: `tests/test_settings.py` gains: a source pin that no file under `klausmate/` except `settings.py` and `__init__.py` contains `addonManager.getConfig`/`writeConfig`, and none contains `from . import USER_FILES` or `_pkg().get_config()` / `_pkg().write_config(`; retention's registered migrations: scale migration clears overrides exactly once and sets `_threshold_scale`; default-threshold migration respects `_threshold_user_set`; `pdf_handler.pdf_path_for(user_files, name)` with no root and a `DictStore({"library_root": tmp})` resolves under `tmp`; `dashboard.write_cfg` with an armed preview re-arms a patched preview (stub `background`).

- [ ] **Step 1: Write the pins and tests** → Expected: FAIL (reach-backs present).
- [ ] **Step 2: Sweep.** Mechanical replacements first (`from . import USER_FILES` → `from . import settings` + `settings.user_files()`), then the writers, then the migrations.
- [ ] **Step 3: Compile through the symlink; run test_settings** → Expected: pass.

---

### Task 4: The test sweep and the whole suite

**Files:**
- Modify: every test that assigns `sys.modules["klausmate"].get_config` / `.USER_FILES` / `.write_config` (`test_bottom_row`, `test_current_page_load_failure`, `test_library_viewer`, `test_library_sidebar`, `test_pdf_lock`, `test_library_sync`, `test_single_window`, `test_rescan`, `test_status_bar`, `test_user_files_guard`) and every test touching `curation.USER_FILES`, `retention.USER_FILES`, `curation._pkg`, `K.get_config`/`K.write_config`, `FakeAddonManager` (`test_klausmate`, `test_index_queue`, `test_api_first_config`, `test_local_model_settings`, `test_external_client_settings`, `test_anki_ops`, `test_dashboard`, `test_browse_toolkit`, `test_heatmap`, `test_match_precision`, `test_retention_history`, `test_projection`, `test_pdf_map`, `test_setup_crop_theme`, `test_dialog_logic`, `test_manage_models_assistant`).

- [ ] **Step 1: Run the whole suite** → Expected: the affected files fail on the removed names (a list to work from).
- [ ] **Step 2: Migrate each** to `settings.store = settings.DictStore({...})` / `settings.user_files_dir = tmp`; delete `FakeAddonManager` where the only use was config; replace `curation._pkg` swaps that captured writes with a `DictStore` and a read-back.
- [ ] **Step 3: Whole suite** → Expected: green except `tests/test_top_bar.py` (pre-existing). `node tests/dashboard_js_dom_test.js` is run by test_dashboard.

---

### Task 5: Records

**Files:**
- Create: `CONTEXT.md` (repo root): the glossary — settings store, preferences state machine (planned), page adapter (planned), Library, PDF dock, task readout, index runner, tag sync's invariant, single window, design gate; one line each, pointing at CLAUDE.md for the narrative.
- Modify: `CLAUDE.md` (the `__init__.py` bullet's config paragraph → `settings.py`; the "never `write_config` a partial dict" gotcha becomes "there is no whole-blob writer"), `AGENTS.md` (tree + config accessors), `docs/superpowers/specs/2026-09-30-settings-seam-design.md` ("Rulings during implementation").

- [ ] **Step 1: Write** — Verify: `grep -n "settings" CONTEXT.md CLAUDE.md AGENTS.md` hits in all three; `grep -c "write_config" CLAUDE.md` is 0 outside history notes.
