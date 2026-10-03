# Preferences State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One aqt-free `PrefsState` holds every value the Preferences dialog edits; the dialog becomes adapters over it, Save writes only what changed, and dirty is a fact.

**Architecture:** `klausmate/prefs_state.py` (new) owns baseline + pending values, normalisation, `commit()` → one patch plus an ordered effect list. `manage_models.py` keeps its widgets, names and prompts; a small `_Binding` base replaces `mark_dirty`/`sync_*`/`save_*`, and `save_all` dispatches the effects. General and Local models move first, Appearance last.

**Tech Stack:** Python 3.9 (system python for tests), PyQt6 offscreen for the dialog tests, `klausmate.settings` for reads/writes, `klausmate.background.resolve` and `klausmate.embeddings.index_signature` (both aqt-free) inside the state module.

**Spec:** `docs/superpowers/specs/2026-09-30-prefs-state-design.md`

## Global Constraints

- Edit the main checkout only (`/Users/pyamzi/Documents/Github/Klaus/Klaus Addon/klausmate/`); Anki loads it through a symlink. Quote paths (spaces).
- No commits unless the user asks; every "commit" step below is a ledger line instead. Never stage `user_files/` or `meta.json*`.
- Test command for one file: `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/<file>.py`; whole suite: the CLAUDE.md loop, with `tests/test_top_bar.py` excepted (fails at HEAD on another session's logo deletion).
- No `exec()`/`exec_()` on any dialog (K-114); prompts stay window-modal `open()`.
- Keep stable for the offscreen tests: object names `SettingsNav`, `SettingsSearch`, `endpoint`, `embedding_model`, `pull_model`, `runtime_auto_setup`, `InstalledModels`, `OllamaStatus`, `OllamaProgress`, `AdvancedModelSettings`, `external_client_config`, `copy_external_client_config`, `test_external_client_connection`; button texts Save, Refresh, Install/start, Stop managed server, Update runtime, Download, Delete; `_OPEN_DLG`, `_close_for_profile(dlg, _preview_timer, op_state)`, `_on_profile_will_close`, `_preview_timer`, `dlg.show()` never `exec()`.
- Default endpoint `http://127.0.0.1:11434`; default threshold `retention.DEFAULT_THRESHOLD` (0.45); default accent `ocean`.
- Effects in this order and no other: `index_sweep`, `threshold_changed`, `anki_theme`, `renderer_restart`, `appearance`.
- Never write `heatmap_enabled` or `color2` from the dialog.

## Review Focus

1. A threshold set only with the keyboard (slider `valueChanged`, no `sliderReleased`) must light Save and be written — Task 2's offscreen check.
2. Save with nothing edited must call `settings.patch` zero times — Task 2's offscreen check.
3. Endpoint relocation landing while the endpoint field holds an unsaved edit: the edit survives, Save stays lit, the baseline moves — Task 1's `reseed` tests and Task 2's existing "unsaved endpoint" variant in `tests/test_local_model_settings.py`.
4. Discard after dragging a gradient sphere: the dot moves back on the deck screen and nothing is written — Task 4's revert test.
5. A `color_theme` stored as an unknown name must seed as `ocean` and NOT count as dirty — Task 3's seeding test.

---

### Task 1: `prefs_state.py` — General and Local-models keys

**Files:**
- Create: `klausmate/prefs_state.py`
- Test: `tests/test_prefs_state.py`

**Interfaces:**
- Produces: `class PrefsState` with `KEYS: tuple[str, ...]`, `from_config(cfg: dict) -> PrefsState`, `get(key) -> Any`, `set(key, value) -> None`, `reseed(key, value) -> None`, `view() -> dict`, `pending() -> dict`, `dirty: bool` (property), `discard() -> None`, `commit() -> Commit`; `Commit = NamedTuple("Commit", [("patch", dict), ("effects", list)])`; `DEFAULT_ENDPOINT = "http://127.0.0.1:11434"`. Keys in this task: `image_crop_enabled`, `pdf_renderer`, `endpoint`, `embedding_model`, `runtime_auto_setup`, `pdf_match_threshold`. Effects in this task: `("index_sweep", prev_signature)`, `("threshold_changed", old, new)`, `("renderer_restart",)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_prefs_state.py` (the repo's `check`/`section`/`report` style from `anki_stubs`; `install()` first so `klausmate` resolves):

```python
ps = importlib.import_module("klausmate.prefs_state")
st = ps.PrefsState.from_config({"endpoint": " http://x:1 ", "embedding_model": "m", "pdf_match_threshold": 0.456, "pdf_renderer": "weird"})
check("seed normalises endpoint", st.get("endpoint") == "http://x:1")
check("seed rounds the threshold", st.get("pdf_match_threshold") == 0.46)
check("seed coerces an unknown renderer", st.get("pdf_renderer") == "native")
check("missing keys take defaults", st.get("image_crop_enabled") is True and st.get("runtime_auto_setup") is True)
check("a fresh state is clean", st.dirty is False and st.pending() == {} and st.commit() == ps.Commit({}, []))
st.set("endpoint", "")
check("empty endpoint becomes the default and is an edit", st.get("endpoint") == ps.DEFAULT_ENDPOINT and st.dirty)
st.set("endpoint", "http://x:1")
check("setting back to baseline drops the pending value", st.dirty is False)
st.set("embedding_model", "n")
st.reseed("endpoint", "http://y:2")
check("reseed moves the baseline without an edit", st.get("endpoint") == "http://y:2" and st.pending() == {"embedding_model": "n"})
st.set("endpoint", "http://z:3"); st.reseed("endpoint", "http://z:3")
check("reseed to the pending value drops it", "endpoint" not in st.pending())
st.set("pdf_match_threshold", 0.6); st.set("pdf_renderer", "pdfjs")
c = st.commit()
check("commit writes changed keys only, threshold with its user-set mark",
      c.patch == {"embedding_model": "n", "pdf_match_threshold": 0.6, "_threshold_user_set": True, "pdf_renderer": "pdfjs"})
check("effects in the fixed order", c.effects == [("index_sweep", embeddings.index_signature({"embedding_model": "m"})),
                                                 ("threshold_changed", 0.46, 0.6), ("renderer_restart",)])
check("commit moves the baseline", st.dirty is False and st.get("embedding_model") == "n")
st.set("image_crop_enabled", False); st.discard()
check("discard drops pending", st.dirty is False and st.get("image_crop_enabled") is True)
check("view is a fresh dict", st.view() is not st.view() and st.view()["endpoint"] == "http://z:3")
check("set on an unknown key raises", raises(KeyError, lambda: st.set("nope", 1)))
```

- [ ] **Step 2: Run** `env PYTHONDONTWRITEBYTECODE=1 python3 tests/test_prefs_state.py` — Expected: ImportError `klausmate.prefs_state`.

- [ ] **Step 3: Implement** `klausmate/prefs_state.py`: `KEYS`, per-key `_NORMALISE[key](value)` and `_DEFAULTS`, `from_config` (normalise each key through the same table), `set` (KeyError on unknown, normalise, drop if equal to baseline), `reseed`, `view`/`pending`/`dirty`/`discard`, `commit` (patch from `pending()`, `_threshold_user_set` companion, effects by comparing `self._baseline` with `self.view()` in the fixed order; then baseline ← view, pending cleared). Signature via `embeddings.index_signature`. Module docstring states the interface and that effects are a pure function of (baseline, view).

- [ ] **Step 4: Run** the test — Expected: all checks pass.

- [ ] **Step 5: Ledger** `Task 1: complete` (no commit).

---

### Task 2: Shell — General and Local-models pages over the state

**Files:**
- Modify: `klausmate/manage_models.py` (`manage_models_dialog`; today: `ui_state` 1608, `set_busy` 1612-1627, `refresh` 1629-1632, `sync_embed_widgets` 1636-1648, `save_embed` 1676-1699, `sync_threshold_widget` 1704-1721, `save_threshold` 1723-1840, `confirm_close` 1974-2073, `save_general` 2075-2120 (its `image_crop_enabled`/`pdf_renderer`/`mw.set_theme` parts), `mark_dirty`/`clear_dirty` 2122-2141, `save_all` 2301-2326, `run_local.done` 2491-2494, `select_installed_model` 2527-2533, signal wiring 2594-2622, `refresh()` call 2780)
- Modify: `tests/test_dialog_logic.py` (delete the transcribed copies at 47-130 and 264-410 and the source pins on `save_embed`/`save_threshold` statement order 804-900ish, `ui_state`/`_bg_state` ordering 415-432 stays until Task 4), `tests/test_local_model_settings.py` (two new offscreen checks)

**Interfaces:**
- Consumes: Task 1's `PrefsState`, `Commit`.
- Produces: in the shell, `state: PrefsState`, `class _Binding` (`__init__(self, widget, key, read, paint, signal)`, `paint(self)`, `syncing` class attribute), `bindings: list[_Binding]`, `paint_all() -> None`, `refresh_dirty() -> None`, `_run_effect(effect: tuple) -> None`; `appearance_dirty: bool` interim flag that `mark_dirty` (Appearance only, until Task 4) sets and `refresh_dirty` ORs in.

- [ ] **Step 1: Write the failing offscreen checks** in `tests/test_local_model_settings.py` after the existing save checks (it drives the real dialog; `field('…')`, `button('Save')`, `writes` from the `_Store` already exist):

```python
mm.manage_models_dialog(); dlg = mm._OPEN_DLG
n = len(writes); button('Save').click(); drain()
check('save with no edit writes nothing', len(writes) == n)
slider = dlg.findChild(QtWidgets.QSlider); slider.setValue(slider.value() + 7)   # valueChanged only, no sliderReleased
check('a keyboard-only threshold edit lights Save', button('Save').isEnabled())
button('Save').click(); drain()
check('…and is written', writes[-1].get('pdf_match_threshold') == round(slider.value() / 100, 2) and writes[-1].get('_threshold_user_set') is True)
dlg.accept(); drain()
```

- [ ] **Step 2: Run** `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_local_model_settings.py` — Expected: "save with no edit writes nothing" FAILS (three writers patch unconditionally) and "keyboard-only threshold edit lights Save" FAILS.

- [ ] **Step 3: Implement in the shell.** `state = prefs_state.PrefsState.from_config(settings.read())` before the pages are built (seed `anki_theme` is Task 4). Add `_Binding` and bind: `image_crop_cb`/`pdfjs_cb` (`toggled`, renderer read `"pdfjs" if checked else "native"`), `endpoint_edit`/`embed_model_edit` (`textEdited`), `runtime_auto_cb` (`toggled`), `threshold_slider` (`valueChanged`, read `value()/100`, paint `setValue(round(x*100))` and the label). Replace `mark_dirty`/`clear_dirty` with `refresh_dirty()` (Appearance's handlers call a two-line `mark_dirty` that sets `appearance_dirty = True` and calls `refresh_dirty`, interim). Delete `sync_embed_widgets`, `sync_threshold_widget`, `refresh` (the open-time call becomes `paint_all()`), `save_embed`, `save_threshold`; move their non-value bodies into `_run_effect` (`index_sweep` → `update_embed_status()` + `index_queue.offer_model_sweep(dlg, prev)`; `threshold_changed` → the override prompt + `pdf_drive.refresh_open_library()`; `renderer_restart` → the restart `showInfo`). `save_general` keeps only its appearance part for now and no longer writes `image_crop_enabled`/`pdf_renderer`. `save_all`: `c = state.commit(); if c.patch: settings.patch(c.patch); for e in c.effects: _run_effect(e); save_general() if appearance_dirty; appearance_dirty = False; paint_all(); refresh_dirty()`; the "saved" tooltip unless a restart notice showed. `confirm_close`'s discard path: `state.discard(); appearance_dirty = False; paint_all()`. `run_local.done`: `state.reseed("endpoint", new); paint_all()`. `select_installed_model`: `state.set("embedding_model", name); paint_all(); refresh_dirty()`. `set_busy` ends with `refresh_dirty()`. `ui_state` loses `dirty` and `syncing` (keep the dict only if `op_state` code still reads it; otherwise delete).

- [ ] **Step 4: Run** `tests/test_local_model_settings.py`, `tests/test_external_client_settings.py`, `tests/test_anki_ops.py`, `tests/test_bridge_reentrancy.py`, `tests/test_md3_switch.py` — Expected: all pass (the relocation variants at 403-440 keep passing: "unsaved endpoint" relies on the field's unsaved text winning over the reseeded baseline).

- [ ] **Step 5: Delete the copies and moved-code pins** in `tests/test_dialog_logic.py`: the `World` class and the `mark_dirty`/`sync_embed_widgets`/`save_embed` copies (47-130), the `sync_threshold_widget`/`save_threshold` copies (264-410), and the AST pins on `save_embed`/`save_threshold` statement order. Run it — Expected: passes with fewer checks; print the before/after counts in the ledger.

- [ ] **Step 6: Whole suite** — Expected: green except `test_top_bar`. Ledger `Task 2: complete`.

---

### Task 3: `prefs_state.py` — Appearance keys and the flattener

**Files:**
- Modify: `klausmate/prefs_state.py`
- Test: `tests/test_prefs_state.py`

**Interfaces:**
- Consumes: Task 1's class.
- Produces: keys `klausbook_design`, `color_theme`, `color_theme_custom`, `background`, `reviewer_background`, `anki_theme`; `flatten_appearance(view: dict) -> dict` (module function; the `background_*`/`reviewer_background_*` keys `save_general` writes today, `int()` on grad_x/grad_y/grad_size for both, no reviewer blur, never `heatmap_enabled`/`color2`); `APPEARANCE_KEYS`; effects `("anki_theme", value)`, `("appearance",)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_prefs_state.py`):

```python
st = ps.PrefsState.from_config({"color_theme": "not-a-theme", "color_theme_custom": "zzz", "background_mode": "color", "reviewer_background_grad_x": "7"})
check("unknown accent seeds as ocean and is not dirty", st.get("color_theme") == "ocean" and st.get("color_theme_custom") == "" and st.dirty is False)
check("specs seed through background.resolve", st.get("background")["mode"] == "color" and st.get("reviewer_background")["grad_x"] == 7)
check("anki_theme defaults to 0", st.get("anki_theme") == 0)
spec = dict(st.get("background")); spec["grad_x"] = 12.0
st.set("background", spec)
check("a spec edit is dirty by equality", st.dirty and st.get("background") is not spec)
st.set("anki_theme", 2)
c = st.commit()
check("commit flattens the spec with int casts and drops the pseudo-key",
      c.patch["background_grad_x"] == 12 and isinstance(c.patch["background_grad_x"], int) and "anki_theme" not in c.patch and "background" not in c.patch)
check("appearance effects in order", c.effects == [("anki_theme", 2), ("appearance",)])
check("flatten_appearance never emits heatmap_enabled or color2", not {"heatmap_enabled", "color2"} & set(ps.flatten_appearance(st.view())))
check("flatten_appearance casts reviewer geometry too", isinstance(ps.flatten_appearance(st.view())["reviewer_background_grad_x"], int))
```

- [ ] **Step 2: Run** — Expected: FAIL on `color_theme` (KeyError / not a key).
- [ ] **Step 3: Implement**: the six keys in `KEYS`/`_NORMALISE`/`_DEFAULTS` (specs deep-copied on `set`, seeded via `background.resolve(cfg)` and `resolve(cfg, prefix="reviewer_background")`; accent validation = `theme.COLOR_THEMES` membership or `custom`, custom colour must match `#rrggbb` else `""`); `flatten_appearance`; `commit` uses it and emits the two effects; `anki_theme` stripped from the patch.
- [ ] **Step 4: Run** — Expected: pass. Ledger `Task 3: complete`.

---

### Task 4: Shell — Appearance page over the state

**Files:**
- Modify: `klausmate/manage_models.py` (`_bg_state` 1163-1169, `sync_background_widgets` 1243-1317, `on_*` handlers 1325-1426, accent 1430-1544 incl. `_accent_state` 1440 and `_pick_accent`/`_pick_custom_accent`, `_bg_preview_cfg` 2143-2212, `apply_appearance_live` 2214-2257, `revert_appearance_preview` 2259-2289, `appearance_changed` 2291-2299, `save_general` 2075-2120, gradient sink 2624-2723, `anki_theme_combo` seeding 1139-1145)
- Modify: `tests/test_dialog_logic.py` (delete 415-432, 617-630, 661, 667-677, 718-745, the `save_general`/`_bg_preview_cfg` slice pins; keep K-114, debounce, finished → revert, `_pkg()._apply_color_theme()`), `tests/test_anki_ops.py` (add the revert check)

**Interfaces:**
- Consumes: Task 3's keys, `flatten_appearance`, effects; Task 2's `_Binding`, `refresh_dirty`, `_run_effect`.
- Produces: `_bg_state`, `_accent_state`, `appearance_dirty`, `mark_dirty`, `save_general` deleted; `_run_effect` handles `anki_theme` (`mw.set_theme(Theme(value))`) and `appearance` (`apply_appearance_live()` then `_background.set_preview(None)`).

- [ ] **Step 1: Write the failing test** in `tests/test_anki_ops.py` next to the `_preview_timer.stop()` pin (it has a real `_KlausManageDialog`): open the dialog, drive `on_bg_mode_changed`-equivalent through `state.set("background", {...mode:"color", grad_x: 99})`, assert `background.preview_active()` after the timer fires, then `dlg.reject()` and assert `background.preview_active() is False`, `state.dirty is False`, and `writes` unchanged (name: "discard reverts the preview and writes nothing").
- [ ] **Step 2: Run** — Expected: FAIL (`state` has no `background` key / `_bg_state` still owns it).
- [ ] **Step 3: Implement**: seed `state.set`-free baseline for `anki_theme` via `state.reseed("anki_theme", mw.pm.theme().value)` right after `from_config`; bind `klausbook_cb`, `anki_theme_combo`; the `on_*` handlers and the gradient sink build a spec copy and `state.set("background"|"reviewer_background", spec)` then `appearance_changed()` (sink ops keep `_quiet_preview`); accent swatches `state.set("color_theme", name)` / `state.set("color_theme_custom", hex)`; `sync_background_widgets` and `sync_accent_swatches` read `state.get(...)` and run inside a `_Binding.syncing` scope; `_bg_preview_cfg` = `prefs_state.flatten_appearance(state.view())` + `klausbook_design` + the stored-config keys; `apply_appearance_live` reads the accent pair from `state.get`; delete `_bg_state`, `_accent_state`, `appearance_dirty`, `mark_dirty`, `save_general`; `_run_effect` gains the two cases; `refresh_dirty` is `state.dirty` alone.
- [ ] **Step 4: Run** `tests/test_anki_ops.py`, `tests/test_dialog_logic.py` — Expected: the new check passes; dialog_logic fails on the deleted-code pins.
- [ ] **Step 5: Delete the moved-code pins** listed above in `tests/test_dialog_logic.py`; run — Expected: pass; counts in the ledger.
- [ ] **Step 6: Whole suite** — Expected: green except `test_top_bar`. Ledger `Task 4: complete`.

---

### Task 5: Records

**Files:**
- Modify: `CLAUDE.md` (the `manage_models.py` bullet's "Preferences are deferred-save" paragraph → the state machine: `PrefsState`, bindings, `commit()` effects, "Adding a preference = one key in `prefs_state.KEYS` + one binding"), `AGENTS.md` (tree line for `prefs_state.py`), `CONTEXT.md` (Preferences state machine and page adapter from "planned" to built, one line each), `docs/superpowers/specs/2026-09-30-prefs-state-design.md` ("Rulings during implementation").

- [ ] **Step 1: Write** — Verify: `grep -n "prefs_state" CLAUDE.md AGENTS.md CONTEXT.md` hits in all three; `grep -c "mark_dirty" CLAUDE.md` is 0. Ledger `Task 5: complete`.
