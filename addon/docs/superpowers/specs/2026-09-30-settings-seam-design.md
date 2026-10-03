# The settings seam

Date: 2026-09-30. Status: design grilled and confirmed; implementation next.
Origin: architecture review candidate 2 ("Config and `USER_FILES` are a
hidden interface of the bootstrap module"), the first step of candidate 1
(the Preferences state machine).

## Problem

The stored config and the user-files path are read and written through
the package root (`__init__.py`), which imports `aqt` at module top. Every
module below it therefore reaches back: six identical `_pkg()` helpers,
`index_queue._cfg` and `pdf_handler._live_library_root` reading Anki's
addon manager directly, `retention._cfg` wrapping `curation._cfg` with two
lazy migrations that write back, `pdf_drive._user_files` →
`library_actions._uf` as a two-hop pass-through for one string, twenty-odd
`from . import USER_FILES` inside functions "deferred: the package root
imports aqt", and separate `curation.USER_FILES` / `retention.USER_FILES`
copies. Three write semantics exist: whole-blob replace (the documented
wipe hazard), main-thread merge, and the dashboard's merge-plus-preview.
Migrations apply only to readers of `retention._cfg`. Sixteen test files
inject config or the user-files path by assigning into
`sys.modules["klausmate"]`.

## Design

One aqt-free module, `klausmate/settings.py`, owns the stored config and
the user-files path. Its interface:

- `read() -> dict`: the stored config, a fresh dict each call.
- `patch(updates: dict, *, remove: Iterable[str] = ()) -> None`: merge
  `updates` into the stored config and drop `remove`. Applies inline when
  called on the main thread (a compare-and-set caller must not see a
  queued gap), hops through `run_on_main` from any other thread, and is
  skipped if the profile changed in between (today's guard).
- `user_files() -> str`: the add-on's user-files directory.
- `register_migration(fn)` and `migrate()`: a migration is a pure
  `dict -> dict` (return the input unchanged to mean "nothing to do").
  `migrate()` runs the list once, in registration order, and writes back
  only if something changed. The bootstrap calls it on profile open.

Its seam is the store adapter, `settings.store`, an object with `read()`
and `write(cfg)`. Production installs the Anki adapter (addon manager)
at bootstrap; tests assign a `DictStore`. Two adapters exist, so the seam
is real. Two more module attributes follow the repo's documented cheap-seam
style (`tasks.clock`, `tasks.run_on_main`): `settings.run_on_main` and
`settings.current_profile`, both installed by the bootstrap and `None`
in tests. `settings.user_files_dir` is derived from the module's own
location, which in the test harness's mirror is the scratch directory the
harness already creates; tests override the attribute instead of the
package root.

Migrations move to where they belong: the legacy-key scrub and the
embeddings default (today `__init__._migrate_config`) become the first
registered migration inside `settings.py`; retention's two threshold
migrations become pure functions registered by `retention` at import, so
their side effect (`clear_threshold_overrides`) stays in retention. After
`migrate()` every reader sees migrated config; the lazy write-back on
every read is gone.

Deleted in the same change: `get_config`, `write_config`, `patch_config`,
`USER_FILES`, `_migrate_config` and `_LEGACY_KEYS_DROPPED` on the package
root; the config-only reach-back helpers (`setup_flow._pkg`,
`tag_migrate._pkg`, `tag_sync._pkg`); the config use of the three helpers
that also serve a non-config private (`curation._pkg` for `_strip_html`,
`manage_models._pkg` for `_apply_color_theme`, `browse_toggles._pkg` for
the Browse layout reset stay for that use only); `curation._cfg`,
`retention._cfg`, `index_queue._cfg`, `index_queue._user_files`,
`pdf_drive._user_files`, `library_actions._uf`, `lecture_view._user_files`,
`pdf_handler._live_library_root` (its `pdf_path_for` fallback reads
`settings.read()`); `curation.USER_FILES` / `retention.USER_FILES` /
`INDEX_DIR` module copies become `curation.index_dir()` and
`settings.user_files()`. `dashboard.write_cfg` keeps its preview rule but
reads and writes through `settings`.

Every read-modify-write caller becomes a `patch` of the keys it sets
(setup flow ×4, Preferences' three savers and the library-folder move, the
tag migration's flags with its legacy key removed).

## Test harness

`install_package_stub` stops setting `USER_FILES` on the package root.
Tests that need config assign `settings.store = settings.DictStore({...})`;
tests that need a scratch user-files directory assign
`settings.user_files_dir`. `exec_klausmate_under_qt` points
`settings.user_files_dir` at its scratch directory.

## Rulings

- The merge applies inline on the main thread: the setup flow's endpoint
  compare-and-set documents why a queued write leaves a gap.
- `remove` on `patch` exists because two callers drop keys; a whole-blob
  writer stays private to the module.
- Migrations run once per profile open, not on every read; a bump of a
  default still re-runs because the migrations record what they applied.

## Rulings during implementation

- `pdf_handler._live_library_root` keeps its name (six callers) with an
  aqt-free body over `settings.read()`; renaming bought nothing.
- `curation._pkg`, `manage_models._pkg` and `browse_toggles._pkg` stay
  for the non-config private each also serves; no config passes through
  them.
- `pdf_graph`'s per-call redirection of retention's user-files copy is an
  assignment to `settings.user_files_dir`.
- Seven readers the module sweep missed (`browse_toolkit`,
  `library_actions` ×2, `manage_models.sync_threshold_widget`,
  `library_sidebar`, `setup_flow._rematch_stale_matches`, `anki_tools`,
  `retention.do_build`, `single_window._config`) were fixed in the test
  sweep; `setup_flow`'s bare `retention._cfg()` (a migration side effect)
  is deleted, since migrations run at profile open.
- `annotation_save.py` (K-321, committed while this landed) reached back
  for the package `USER_FILES`; two lines moved to `settings.user_files()`.
- `tests/test_api_first_config.py`'s `patch_config` section is deleted:
  `tests/test_settings.py` pins the merge and the profile fence.
- The harness gains `LiveStore` (a store over a live dict) for tests that
  mutate their config between calls.

## Out of scope

The Preferences state machine (candidate 1), the index runner's token
(candidate 4), the Library ingest funnel (candidate 5). `anki_tools`'s own
`_USER_FILES` constant (derived from its file, aqt-free) is left alone.
