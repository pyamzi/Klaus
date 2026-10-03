# Preferences state machine — design

Date: 2026-09-30. Candidate 1 of the architecture review; follows the
[settings seam](2026-09-30-settings-seam-design.md), which it builds on.
Repo: Klaus add-on, `klausmate/manage_models.py` (2,816 lines) is the
Preferences dialog.

## Problem

The dialog's value state is spread over four dicts and a dozen closures:
`ui_state` (dirty, syncing), `_bg_state` (two background specs plus its
own syncing flag), `_accent_state`, three `save_*` writers that each
rewrite every key they own whether it changed or not, two `sync_*`
readers whose "bail while dirty" guards protect a path nothing calls
after open, and a `mark_dirty` that signals call by hand. Consequences a
user meets: a keyboard-edited threshold never lights Save; every Save
rewrites every appearance and embedding key; "Unsaved changes" is a flag,
not a fact. Two test files pin transcribed copies of this logic rather
than the code.

## The module

`klausmate/prefs_state.py`, aqt-free, stdlib plus `embeddings` (for the
index signature). One class.

```python
class PrefsState:
    KEYS: tuple[str, ...]                      # every key the dialog owns (below)

    @classmethod
    def from_config(cls, cfg: dict) -> "PrefsState"   # baseline = the owned keys of cfg, normalised
    def get(self, key) -> Any                  # pending value if set, else baseline
    def set(self, key, value) -> None          # the user's edit, normalised; equal to baseline → pending dropped
    def reseed(self, key, value) -> None       # a stored value changed underneath: baseline moves, pending for key dropped if now equal
    def view(self) -> dict                     # baseline overlaid with pending (a fresh dict)
    def pending(self) -> dict                  # changed keys only
    @property
    def dirty(self) -> bool                    # bool(pending())
    def discard(self) -> None                  # pending cleared
    def commit(self) -> Commit                 # see below; baseline ← view, pending cleared
```

`Commit` is a `NamedTuple(patch: dict, effects: list[tuple])`.

### Keys

| Page | Key | Value | Normalisation at `set` |
|---|---|---|---|
| General | `image_crop_enabled` | bool | — |
| General | `pdf_renderer` | `"native"` / `"pdfjs"` | anything else → `"native"` |
| Local models | `endpoint` | str | stripped; empty → `http://127.0.0.1:11434` |
| Local models | `embedding_model` | str | stripped |
| Local models | `runtime_auto_setup` | bool | — |
| Local models | `pdf_match_threshold` | float | `round(x, 2)`; the slider's int/100 |
| Appearance | `klausbook_design` | bool | — |
| Appearance | `color_theme` | str | must be in `theme.COLOR_THEMES` or `custom`, else `ocean` |
| Appearance | `color_theme_custom` | str | a hex colour or `""` |
| Appearance | `background` | spec dict (`background.resolve` shape) | deep-copied; compared by equality |
| Appearance | `reviewer_background` | spec dict | deep-copied |
| Appearance | `anki_theme` | int 0/1/2 | pseudo-key: seeded from `mw.pm.theme().value` by the shell, never written to config |

`from_config` seeds the two specs through `background.resolve(cfg)` and
`resolve(cfg, prefix="reviewer_background")` (both aqt-free), the accent
pair through the same validation `_accent_state` uses today, and the
rest through the defaults the current seeding uses.

### commit()

`patch` is `pending()` with:

- `background` flattened to the `background_*` keys `save_general` writes
  today (mode, color, image, fit, blur, wash, grad_x, grad_y, grad_size,
  gradients) and `reviewer_background` to `reviewer_background_*` (no
  blur), with the same `int()` casts for grad_x/grad_y/grad_size on both
  (today the preview dict skips them for the reviewer; the state does not).
  `heatmap_enabled` and `color2` are never written.
- `pdf_match_threshold` accompanied by `_threshold_user_set: True`.
- `anki_theme` removed (pseudo-key).

`effects`, in this fixed order, each present only when its condition
holds between `baseline` and `view()`:

1. `("index_sweep", prev_signature)` when `embeddings.index_signature`
   differs; `prev_signature` is the baseline's.
2. `("threshold_changed", old, new)` when `pdf_match_threshold` differs.
3. `("anki_theme", value)` when `anki_theme` differs.
4. `("renderer_restart",)` when `pdf_renderer` differs.
5. `("appearance",)` when any Appearance key other than `anki_theme` differs.

A clean state commits `Commit({}, [])`. `commit()` is the only method
that moves the baseline besides `reseed`.

## The shell (`manage_models.py`)

`prefs_state.py` is the only new file. The dialog keeps its object names,
button texts, `_OPEN_DLG`, `_close_for_profile`, `_on_profile_will_close`
and `_preview_timer`, which the offscreen tests and the reentrancy pins
rely on.

**Adapters.** One small base in the shell, `_Binding(widget, key, read,
paint, signal)`: `signal` → `state.set(key, read())` then
`refresh_dirty()`; `paint()` writes `state.get(key)` into the widget
inside the base's `syncing` scope, during which incoming signals are
ignored. One binding per value widget. The background sliders, combos,
image buttons and the gradient sink build a new spec dict and call
`state.set("background", spec)` (or `reviewer_background`), then
`appearance_changed()` as today. `paint_all()` runs after `from_config`,
`reseed`, `discard` and `commit`.

**Dirty.** `refresh_dirty()` sets `save_btn.setEnabled(state.dirty and
not busy)` and the `unsaved_lbl` text. `set_busy` calls it. There is no
`mark_dirty`, no `clear_dirty`, no `ui_state["dirty"]`, no
`ui_state["syncing"]`, no `_bg_state`, no `_accent_state`.

**Save.** `save_all()`:

```python
c = state.commit()
if c.patch:
    settings.patch(c.patch)
for effect in c.effects:
    _run_effect(effect)
paint_all(); refresh_dirty()
tooltip("Preferences saved") unless a renderer_restart notice was shown
```

`_run_effect` dispatches: `index_sweep` → `update_embed_status()` then
`index_queue.offer_model_sweep(dlg, prev)`; `threshold_changed` → the
existing per-PDF override prompt (window-modal, default Yes) and
`pdf_drive.refresh_open_library()`; `anki_theme` → `mw.set_theme(Theme(
value))`; `renderer_restart` → the existing restart `showInfo`;
`appearance` → `apply_appearance_live()` then `_background.set_preview(
None)`. `save_embed`, `save_threshold`, `save_general` are deleted.

**Cancel, Esc, ✕, profile close.** `confirm_close` keeps its prompts
(discard, default No; stop indexing, default No); on discard it calls
`state.discard()` and `paint_all()` before accepting. The `finished`
hooks stay in their order (disarm the gradient editor, stop the timer,
revert the preview, forget the dialog). `_close_for_profile` unchanged.

**Preview.** `_bg_preview_cfg()` reads `state.view()` for the pending
appearance values and flattens them the way `commit()` does (one shared
flattener in `prefs_state`, `flatten_appearance(view) -> dict`), then
adds the stored-config keys it carries today (`heatmap_enabled`, the two
heatmap display keys, `dashboard_order`, `dashboard_hidden`, re-read every
tick). The timer, `apply_appearance_live`, the quiet path for gradient
drags and `revert_appearance_preview` stay in the shell.

**Values that change underneath.** Endpoint relocation (`run_local.done`)
calls `state.reseed("endpoint", new)` and paints; it is not an edit.
`select_installed_model` calls `state.set("embedding_model", name)`; it
is one.

**Outside the state, unchanged.** Library folder (`change_library_folder`
patches `library_root` immediately after its migration op), image copies
(`store_image` at pick time), every Ollama operation, Index Now, test
connection, the MCP rows, the Advanced toggle, search and progressive
disclosure (`sync_background_widgets` reads `state.get("background")` and
`state.get("klausbook_design")` instead of `_bg_state`).

## Invariants

1. `dirty` is true exactly when `view() != baseline`.
2. Save writes exactly the changed keys, in one `settings.patch`, or nothing.
3. The preview never writes config.
4. Every close path reverts the preview and leaves no pending value.
5. Painting a widget from state never marks it dirty.
6. A stored value that changed underneath (`reseed`) is never counted as the user's edit.
7. A pseudo-key never reaches `settings.patch`.
8. Effects are a pure function of (baseline, view) and run only after the patch is written.
9. Save is disabled while busy or clean.
10. No `exec()` anywhere (K-114); every prompt stays window-modal `open()`.

## Tests

- `tests/test_prefs_state.py` (new, no Qt): seeding and normalisation per
  key; `set` equal to baseline drops pending; `reseed` semantics; `view`,
  `pending`, `dirty`; `discard`; `commit` patch flattening (both specs,
  `int()` casts, `_threshold_user_set`, pseudo-key absent); each effect's
  condition and the fixed order; a clean commit is empty; `commit` moves
  the baseline. Invariants 1, 2, 6, 7, 8 pinned here.
- `tests/test_dialog_logic.py`: the transcribed copies (lines 47-130 and
  264-410, with the `World` fixture) and the source pins for code that
  moves (`ui_state`/`_bg_state` ordering, `save_*` statement order, the
  `appearance_changed()` count, the `save_general`/`_bg_preview_cfg`
  slices) are deleted with the page that moves them; pins on code that
  stays (K-114, the debounce timer, finished → revert, the shell strings)
  stay.
- `tests/test_local_model_settings.py`, `tests/test_external_client_settings.py`,
  `tests/test_anki_ops.py`, `tests/test_bridge_reentrancy.py`,
  `tests/test_md3_switch.py`: unchanged contracts (object names, button
  texts, `_OPEN_DLG`, the profile hook, `Md3Switch`), plus one new
  offscreen check per page that a keyboard-only threshold edit lights Save
  and that Save after no edit writes nothing.

## Order of work

1. `prefs_state.py` with the General and Local-models keys, plus the
   adapter base and the Save/Cancel/dirty rewiring in the shell; the
   `World` copies that cover `save_embed`/`sync_embed`/`mark_dirty` go.
2. The Appearance keys (both specs, accent pair, `klausbook_design`,
   `anki_theme`): `_bg_state` and `_accent_state` go, the preview reads
   `view()`, the remaining `World` copies and the appearance source pins go.

Between steps 1 and 2 the Appearance page still marks dirty by hand; the
shell's `refresh_dirty()` ORs `state.dirty` with that flag until step 2
removes it.

## Rulings during implementation

- `DEFAULT_THRESHOLD` is spelled in `prefs_state` (retention imports aqt);
  a test pins it equal to retention's.
- A bad `color_theme_custom` seeds as `theme.DEFAULT_CUSTOM_COLOR` (the
  shell's rule), not `""`.
- `klausbook_cb` keeps its direct `toggled → on_design_toggled` connection
  and edits the state inside that handler.
- The `appearance` effect runs the live apply and drops the preview; a
  Save without an appearance change no longer repaints the toolbar.
- `threshold_slider`, `bg_mode_combo` and `_preview_timer` carry object
  names for the offscreen tests; the dialog exposes `dlg.prefs_state`.
- The discard-reverts-preview check lives in `test_local_model_settings.py`.
- Specs are validated once at seed and deep-copied on `set`, never
  re-validated: re-validation rewrote "image with no image yet" to theme
  and hid Choose Image…. Consequence: Remove-image leaves the mode as
  the state holds it; the painters resolve an empty image to theme.
- A corrupt `klausbook_design` seeds OFF (`v is True`).
- A saved endpoint relocation always moves the baseline (`reseed`),
  whatever the field holds; only the "Save to use the new endpoint"
  case requires an untouched field.
- `dlg.prefs_state` and `dlg.paint_all` are exposed for the offscreen pins.

## Out of scope

The index runner's token (candidate 4), the Library ingest funnel
(candidate 5), moving the Ollama operations or the preview fan-out out of
the shell, a Preferences page for external clients.

## Rulings

- Effects are tuples, not classes: five names, a fixed set.
- Adapters live in `manage_models.py`, not a third module: they are thin
  and reference widgets the shell builds.
- The specs are values in the map (equality-compared dicts), not a side
  state: dirty has one source of truth.
- `anki_theme` is a pseudo-key so the Anki theme switch takes part in
  dirty and discard like every other row.
