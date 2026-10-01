"""State-machine tests for the Preferences dialog's "Local models"
page (endpoint_edit / embed_model_edit) and its default-sensitivity
slider.

PyQt6 cannot be imported here (its sip is 3.13-only), so this reimplements
the dialog's decision logic against faithful widget semantics and asserts
the behaviours that matter: the ui_state['syncing'] / ['dirty'] guards,
the deferred-save contract (Save is the one writer), and when saving
offers the whole-collection re-embed sweep.

Kept in lockstep with manage_models_dialog by construction — the functions
below are transcribed from it; if that code changes these must too. The
source-pin sections further down read manage_models.py directly.
"""
import os
import sys

PASS = FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


class LineEdit:
    """QLineEdit semantics needed here: get/set text."""

    def __init__(self):
        self._text = ""

    def text(self):
        return self._text

    def setText(self, t):
        self._text = t


_DEFAULT_EMBED_MODEL = "nomic-embed-text"


print("== default-sensitivity slider: migration-side bail (K-052) ==")

_SHIPPED_DEFAULTS = (0.35, 0.55, 0.75)
_DEFAULT_APPLIED_KEY = "_threshold_default_applied"
_THRESHOLD_USER_SET_KEY = "_threshold_user_set"


def _migrate_default_threshold(cfg, default_threshold):
    """Transcribed from retention._migrate_default_threshold — if that
    function changes this must too. Parameterized on ``default_threshold``
    (the real function reads the module constant DEFAULT_THRESHOLD) purely
    so a test can simulate "a later version bumps the default" without
    monkeypatching; behaviour is otherwise identical. The write-back side
    effect (mw.taskman.run_on_main -> write_config) is dropped since this
    file never imports aqt — only the returned dict matters here."""
    if cfg.get(_THRESHOLD_USER_SET_KEY):
        return cfg
    if cfg.get(_DEFAULT_APPLIED_KEY) == default_threshold:
        return cfg
    cfg = dict(cfg)
    try:
        current = float(cfg.get("pdf_match_threshold", default_threshold))
    except (TypeError, ValueError):
        current = None
    if current is not None and any(
        abs(current - shipped) < 1e-9 for shipped in _SHIPPED_DEFAULTS
    ):
        cfg["pdf_match_threshold"] = default_threshold
    cfg[_DEFAULT_APPLIED_KEY] = default_threshold
    cfg.pop("_threshold_default_migrated", None)
    return cfg


check(
    "untouched inherited value still migrates on a later bump (feature intact)",
    _migrate_default_threshold({"pdf_match_threshold": 0.55}, 0.85)[
        "pdf_match_threshold"
    ]
    == 0.85,
)
check(
    "a deliberately user-set 0.55 survives a later default bump",
    _migrate_default_threshold(
        {"pdf_match_threshold": 0.55, "_threshold_user_set": True}, 0.85
    )["pdf_match_threshold"]
    == 0.55,
)
check(
    "a user-set cfg is returned completely untouched, not just the threshold key",
    _migrate_default_threshold(
        {"pdf_match_threshold": 0.55, "_threshold_user_set": True}, 0.85
    )
    == {"pdf_match_threshold": 0.55, "_threshold_user_set": True},
)


print("== SynapsePro settings shell (K-106) ==")
# The CURRENT SynapsePro settings window (their 1.5.x, from Pouya's
# screenshot): sidebar of nav pills + a QStackedWidget of pages, each
# page a PageTitle/PageSubtitle over ONE rounded group of _row()s.
# Replaced the K-105 card grid outright.
_src2 = open("klausmate/manage_models.py").read()
check("no tabs and no card grid left — sidebar + stacked pages",
      "QTabWidget" not in _src2
      and "_install_grid_layout" not in _src2
      and "_cards.append" not in _src2)
check("sidebar carries the app identity",
      'setObjectName("SettingsSidebar")' in _src2
      and 'setObjectName("SidebarAppName")' in _src2
      and 'QLabel("KlausMate")' in _src2)
check("sidebar identity: the k logo beside the Excalifont wordmark",
      "_logo_pixmap" in _src2
      and 'QLabel("KlausMate")' in _src2
      and "_top_bar.logo_svg(colour)" in _src2)
check("the logo fills blue_accent and repaints on an accent save",
      'QColor(c["blue_accent"])' in _src2
      and "logo_lbl.setPixmap(_new_logo)" in _src2)
check("settings search: a filter field sits in the sidebar",
      'setObjectName("SettingsSearch")' in _src2
      and "search_edit.textChanged.connect(_apply_search)" in _src2)
check("search rows carry haystacks and register per page",
      "roww.klaus_search" in _src2
      and "_rows_by_page.setdefault(" in _src2)
check("structural hiding beats a search hit (the image-only rows)",
      "hit and not roww.klaus_hidden" in _src2
      and "bg_fit_row.klaus_hidden = not (design_on and is_image)" in _src2)
check("pages without rows stay findable by their haystack",
      "_page_haystack[nav_label]" in _src2)
check("no-hit pages dim + lose clickability instead of vanishing",
      "Qt.ItemFlag.ItemIsEnabled" in _src2
      and "ForegroundRole" in _src2)
check("every section is a page with a sidebar pill and a big title",
      _src2.count("= _page(") == 3
      and 'setObjectName("SettingsNav")' in _src2
      and 'setObjectName("PageTitle")' in _src2
      and 'setObjectName("PageSubtitle")' in _src2)
check("display order is decoupled from build order via _finish_nav",
      '_finish_nav("General", "Appearance", "Local models")' in _src2)
check("settings are SynapsePro rows — name + desc left, control right, "
      "hairline separated",
      'setObjectName("SettingName")' in _src2
      and 'setObjectName("SettingDesc")' in _src2
      and 'setObjectName("RowSeparator")' in _src2)
check("the nav is ONE list — no per-page nav buttons remain",
      "QListWidgetItem(label)" in _src2
      and "nav.setCheckable" not in _src2)
check("blank-viewport clicks cannot clear the selection",
      "_select_page(_nav_state" in _src2)
check("a structurally hidden row takes its separator with it, so a "
      "hidden row never leaves a stray hairline behind",
      "roww.klaus_sep.setVisible(show and seen)" in _src2)
check("the Cancel/Save bar sits under a full-width hairline",
      'setObjectName("ButtonBarLine")' in _src2)


print("== SynapsePro UI/UX audit (K-107) ==")
# Accent colour themes + interaction polish, mimicking SynapsePro's UX.
check("accent swatches render from theme.COLOR_THEMES — the UI "
      "defines no colours of its own",
      "_theme_presets.COLOR_THEMES" in _src2
      and "_accent_swatch_style" in _src2)
_pick_accent_body = _src2.split("def _pick_accent", 1)[1].split("def ", 1)[0]
check("accent choice is deferred-save like every other preference — it "
      "previews live (appearance_changed marks dirty) but writes nothing",
      'state.set("color_theme", name)' in _pick_accent_body
      and "appearance_changed()" in _pick_accent_body
      and "write_config" not in _pick_accent_body)
# CODE only: this function's docstring names set_active_theme("custom")
# before the real calls, which silently inverted the ordering pin below
# until code_only() was introduced. Prose must not be able to fool a pin.
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import code_only  # noqa: E402

_apply_live = code_only(
    _src2.split("def apply_appearance_live", 1)[1].split("\n    def ", 1)[0]
)
check("the accent is applied BEFORE the toolbar re-bakes its palettes, "
      "and the colour before the name (custom is meaningless without it)",
      _apply_live.index("set_custom_colour(")
      < _apply_live.index("set_active_theme(")
      < _apply_live.index("_top_bar.refresh()"))
check("the dialog restyles itself on every live apply, not only on save",
      "dlg.setStyleSheet(" in _apply_live)
check("clickable pills show the pointing-hand cursor",
      _src2.count("PointingHandCursor") >= 2)
check("footer says Cancel, like SynapsePro's",
      'QPushButton("Cancel")' in _src2)
_init_src = open("klausmate/__init__.py").read()
check("the accent preset is applied at profile open, before any "
      "Klaus surface draws",
      "profile_did_open.append(_apply_color_theme)" in _init_src
      and _init_src.index("append(_apply_color_theme)")
      < _init_src.index("append(settings.migrate)"))
_cfgj = open("klausmate/config.json").read()
check("color_theme ships in config.json with the ocean default",
      '"color_theme": "ocean"' in _cfgj
      and '"color_theme_custom": "#0071D3"' in _cfgj)


print("== accent swatches + disabled rows (K-108) ==")
check("swatches are bare colour squares — name in the tooltip only",
      "QPushButton()" in _src2
      and "sw.setToolTip(" in _src2
      and "_accent_swatch_style" in _src2)
check("swatches wrap 7 per row so 14 of them fit a compact dialog",
      "_SWATCHES_PER_ROW = 7" in _src2
      and "_idx // _SWATCHES_PER_ROW" in _src2)
check("the custom swatch opens a colour picker; cancelling still "
      "selects custom with its held colour",
      "QColorDialog.getColor(" in _src2.split("def _pick_custom_accent",
                                              1)[1].split("def ", 1)[0])
check("custom colour is saved, and applied before the theme name",
      'state.set("color_theme_custom", chosen.name())' in _src2
      and _apply_live.index("set_custom_colour(str(state.get(")
      < _apply_live.index("set_active_theme(str(state.get("))
check("profile open loads the custom colour before the theme name",
      _init_src.index("set_custom_colour(")
      < _init_src.index('set_active_theme(str(cfg.get("color_theme")'))
check("progressive disclosure: image-only rows HIDE outright unless "
      "image mode is selected, via klaus_hidden (the API-key row's "
      "structural flag, so a settings search can never resurface "
      "them) + an _apply_search re-walk — and design off hides the "
      "whole background block",
      "bg_fit_row.klaus_hidden = not (design_on and is_image)" in _src2
      and "bg_blur_row.klaus_hidden = not (design_on and is_image)"
      in _src2
      and "bg_wash_row.klaus_hidden = not (design_on and is_image)"
      in _src2
      and "bg_mode_row.klaus_hidden = not design_on" in _src2
      and "study_mode_row.klaus_hidden = not design_on" in _src2
      and "_apply_search(search_edit.text())"
      in _src2.split("def sync_background_widgets", 1)[1]
      .split("\n    def ", 1)[0])
check("the chosen image can be REMOVED from its caption link, per "
      "screen (Pouya: \"allow me to remove the image\")",
      '<a href="rm">Remove</a>' in _src2
      and "def on_bg_image_removed" in _src2
      and "def on_study_image_removed" in _src2
      and "bg_image_lbl.linkActivated.connect(on_bg_image_removed)"
      in _src2
      and "study_image_lbl.linkActivated.connect(on_study_image_removed)"
      in _src2)
# One unwrappable line is all it takes to force the page's minimum
# width past the window — the sphere captions and long stored
# filenames did exactly that (horizontal scrollbar, live screenshot
# 2026-08-30).
check("pages never scroll horizontally — the scroll area forbids it "
      "and the long captions WRAP instead",
      "scroll.setHorizontalScrollBarPolicy(" in _src2
      and "ScrollBarAlwaysOff"
      in _src2.split("scroll.setHorizontalScrollBarPolicy(", 1)[1][:120]
      and "bg_grad_lbl.setWordWrap(True)" in _src2
      and "study_grad_lbl.setWordWrap(True)" in _src2)
_el_parts = _src2.split("def _elide_middle", 1)
_el_ns: dict = {}
if len(_el_parts) > 1:
    exec("def _elide_middle" + _el_parts[1].split("\ndef ", 1)[0], _el_ns)
_elide = _el_ns.get("_elide_middle")
_long_name = "hf_20260827_161844_c5554d2e-3576-4139-b966-880ca0345684.jpg"
check("long unbroken filenames are middle-elided in the caption — "
      "word wrap can't break one token — with the full name in the "
      "tooltip (the REAL function, exec'd from source)",
      _elide is not None
      and _elide("short.jpg") == "short.jpg"
      and len(_elide(_long_name)) <= 44
      and _elide(_long_name).startswith("hf_2026")
      and _elide(_long_name).endswith(".jpg")
      and "…" in _elide(_long_name)
      and "_elide_middle(name)" in _src2
      and "text_lbl.setToolTip(name)" in _src2)
# The Review-heatmap switch left Preferences on 2026-08-30 (Pouya: "I
# can add / remove widgets another way") — the deck screen's Edit
# Widgets mode is the one writer of that key now. Three pins: the
# widget is gone as CODE (code_only, so this comment can't fake it),
# Save no longer writes the key, and the preview dict still CARRIES it
# — from stored config, read live per tick (the preview dict replaces
# config outright, so dropping the key would resurrect a removed
# heatmap on the first blur nudge).
check("the heatmap switch is gone from Preferences as code",
      "heatmap_cb" not in code_only(_src2)
      and "heatmap_row" not in code_only(_src2))
check("save_general no longer writes heatmap_enabled (Edit Widgets "
      "owns it; a save here would clobber a mid-session ⊖/＋ edit)",
      'cfg["heatmap_enabled"]' not in _src2)
check("the preview dict still carries heatmap_enabled, from STORED "
      "config read live per tick (dashboard_order's pattern)",
      "bool(_heatmap.enabled(settings.read()))" in code_only(_src2))
check("the preview dict carries the removed add-on widgets too — it "
      "replaces config, so without them a removed AMBOSS card returns on "
      "the first preview tick",
      "_dashboard.hidden_foreign(settings.read())" in code_only(_src2))
check("...and the heatmap's two DISPLAY keys with it — the corner "
      "menu can be used while Preferences is open, and a key missing "
      "from the preview dict falls back to its default, not to the "
      "value the user just chose",
      "_heatmap.history_window(" in code_only(_src2)
      and "_heatmap.forecast_window(" in code_only(_src2))
check("nav geometry is pure view geometry: setSizeHint rows + list "
      "setSpacing + an overshooting fixed height — nothing QSS-derived "
      "(three pill-era fixes fought polish timing; a single list view "
      "has no per-button hints to get wrong)",
      "item.setSizeHint(QSize(0, row_h))" in _src2
      and "nav_list.setSpacing(3)" in _src2
      and "nav_list.setFixedHeight(" in _src2)


# ── Appearance: live preview, deferred save ──────────────────────────────
# The user's ask: appearance changes show up live while configuring, but
# only persist on Save. That splits "apply" from "write", so the pins
# below guard the three ways that split can rot: an appearance widget
# that only marks dirty (no preview), a Save that leaves the override
# armed (a stale preview would shadow later config), and a close that
# forgets to revert (a discarded accent lingering all session).
_mm_src = open("klausmate/manage_models.py").read()
_init_src = open("klausmate/__init__.py").read()
_tb_src = open("klausmate/top_bar.py").read()

check("save and preview read the SAME flattening of the state's view — "
      "prefs_state.flatten_appearance — so a key can no longer ride one "
      "and not the other (the klausbook_design / reviewer / wash / "
      "gradient parity lessons, pinned once in tests/test_prefs_state.py)",
      "_prefs_state.flatten_appearance(state.view())"
      in _mm_src.split("def _bg_preview_cfg")[1].split("def apply_appearance_live")[0]
      and "flatten_appearance(after)" in open("klausmate/prefs_state.py").read()
      and "def save_general" not in _mm_src)
check("both image captions render a rounded thumbnail from the STORED "
      "copy under user_files/backgrounds — what the wallpaper will "
      "actually load, never the original path",
      _mm_src.count("_sync_caption(") >= 3
      and "_background.IMAGE_DIR" in _mm_src
      and "_image_thumb(" in _mm_src)
# The on-screen editor rides the OPEN dialog. GEOMETRY drags must
# never refresh — the page already shows the dragged stack, and a
# rebuild would land under the pointer mid-drag. STRUCTURAL ops
# (add/remove/recolor) are the opposite: they replant the editor so
# the handles regrow with fresh indices.
_geom_parts = code_only(_mm_src).split("def _on_grad_geom", 1)
_geom_body = (
    _geom_parts[1].split("\n    def ", 1)[0] if len(_geom_parts) > 1 else ""
)
check("the geometry sink updates the sphere, marks dirty, arms the "
      "preview QUIETLY — and never refreshes mid-drag",
      len(_geom_parts) > 1
      and "state.set(spec_key, s)" in _geom_body
      and "refresh_dirty()" in _geom_body
      and "_quiet_preview()" in _geom_body
      and "_top_bar.refresh" not in _geom_body and "replant" not in _geom_body)
check("structural ops are bounded and replant: add is capped at "
      "MAX_SPHERES, the LAST sphere can never be removed (colour "
      "mode IS a gradient), and a recolor click opens the picker "
      "DEFERRED — modal work never runs inside a webchannel dispatch",
      "len(gradients) < _background.MAX_SPHERES" in _mm_src
      and "if len(gradients) > 1 and 0 <= i < len(gradients):" in _mm_src
      and "QTimer.singleShot(\n                0, "
          "lambda: _pick_sphere_colour(spec_key, i)\n            )"
      in _mm_src)
check("the sphere lists ride save AND preview for both screens as "
      "DEEP COPIES — config must never alias live dialog state",
      "v = [dict(g) for g in (v or [])]" in open("klausmate/prefs_state.py").read()
      and "copy.deepcopy" in open("klausmate/prefs_state.py").read())
check("editing arms on open with the dialog's sink and disarms on "
      "finished — connected BEFORE the preview revert, so exactly one "
      "refresh clears the handles on every close path",
      "set_grad_edit(True, _on_grad_dragged)" in _mm_src
      and "set_grad_edit(False, None)" in _mm_src
      and 0 < _mm_src.find("dlg.finished.connect(_disarm_grad_edit)")
      < _mm_src.find(
          "dlg.finished.connect(lambda _result: revert_appearance_preview())"
      ))
check("Save is the dialog's DEFAULT button — HIG: a dialog names its "
      "default action, and Return should save once there is something "
      "to save (Qt never fires a disabled default)",
      "save_btn.setDefault(True)" in _mm_src)
# Anki's own Light/Dark switch, mirrored into KlausMate Preferences
# (2026-08-30, Pouya) — the ONE row writing an Anki preference.
check("the Anki theme row seeds from mw.pm.theme(), marks dirty like "
      "every deferred pref, and Save applies via mw.set_theme ONLY on "
      "an actual change (setupStyle repaints every webview)",
      '_Binding(state, "anki_theme"' in _mm_src
      and 'state.reseed("anki_theme", _cur_theme)' in _mm_src
      and "mw.set_theme(_Theme(int(effect[1])))" in _mm_src
      and '("anki_theme", after["anki_theme"])' in open("klausmate/prefs_state.py").read())
check("accent swatches carry accessible names — a bare colour square "
      "is silent in VoiceOver; the name mirrors the tooltip identity",
      'sw.setAccessibleName(' in _mm_src
      and '"Custom accent color"' in _mm_src)
check("appearance_changed both marks unsaved AND schedules the preview",
      "def appearance_changed() -> None:" in _mm_src
      and "refresh_dirty()\n        _preview_timer.start()" in _mm_src)
check("the preview is debounced — top_bar.refresh() resets the main "
      "window and the blur slider fires continuously while dragged",
      "_preview_timer = QTimer(dlg)" in _mm_src
      and "_preview_timer.setSingleShot(True)" in _mm_src
      and "_preview_timer.timeout.connect(apply_appearance_live)" in _mm_src)
check("Save is still the ONLY writer of the appearance config keys",
      _mm_src.count("settings.patch(commit.patch)") == 1
      and 'cfg["color_theme"] = ' not in _mm_src
      and 'cfg["background_mode"] = ' not in _mm_src)
check("Save paints through the same one path, THEN drops the override so "
      "a stale preview cannot shadow later config changes",
      "            apply_appearance_live()\n            _background.set_preview(None)"
      in _mm_src.split("def _run_effect")[1].split("def save_all")[0])
check("every close path reverts — finished() covers Save, Cancel, Esc "
      "and the title-bar close alike",
      "dlg.finished.connect(lambda _result: revert_appearance_preview())"
      in _mm_src)
check("revert is a no-op when nothing was previewed (so an ordinary "
      "close does not needlessly reset the main window)",
      "if not _background.preview_active():" in _mm_src)
check("revert re-applies from config via the addon's OWN profile-open "
      "applier, so revert and load-from-config cannot drift apart",
      "_pkg()._apply_color_theme()" in _mm_src)
check("...and that applier really is a top-level name in __init__, or "
      "the revert above would fail silently into its except",
      "\ndef _apply_color_theme() -> None:" in _init_src)
check("the background paint seam honours the preview",
      "background.resolve(background.effective_cfg(_config()))" in _tb_src)

print("== the API-first page list and its two save_* writers (D1) ==")
check("Local models has endpoint and model fields", '"Local models", "Local models"' in _src2 and "endpoint_edit" in _src2 and "embed_model_edit" in _src2)
check("credential widgets and saves are removed", "api_key_" not in _src2 and "key_edit" not in _src2)
_ast_tree = __import__("ast").parse(_src2)
def _fn_src(name):
    import ast as _a
    for node in _a.walk(_ast_tree):
        if isinstance(node, _a.FunctionDef) and node.name == name:
            return _a.get_source_segment(_src2, node) or ""
    return ""
check("connection check runs without collection", "without_collection().run_in_background()" in _fn_src("test_connection"))

print("== changing the model re-indexes everything (K-152) ==")
# The signature comparison lives in prefs_state.commit() now (pinned
# behaviourally in tests/test_prefs_state.py: the index_sweep effect
# carries the BASELINE signature); the shell only dispatches it.
check("the shell dispatches the index_sweep effect to index_queue with the "
      "baseline signature the state captured",
      "index_queue.offer_model_sweep(dlg, prev_sig)" in _fn_src("_run_index_sweep")
      and "_run_index_sweep(effect[1])" in _fn_src("_run_effect"))

_iq_code = code_only(open("klausmate/index_queue.py").read())
check("the sweep offer is raised window-modal — open() and a finished "
      "callback, never exec() (K-114: exec's nested app-modal loop "
      "segfaults on Qt 6.11 + macOS 26, and the Preferences window this "
      "is raised from is itself non-modal)",
      "box.open()" in _iq_code and ".exec()" not in _iq_code)

_test_conn_src = _fn_src("test_connection")
check("test_connection probes the endpoint currently shown",
      bool(_test_conn_src) and "endpoint_edit.text()" in _test_conn_src)

check("Preferences' own Index Now still calls curation directly — it "
      "has its own progress bar and cancel, and the runner WAITS for "
      "the shared token rather than racing it",
      "curation.ensure_index(" in code_only(_mm_src))


print("== K-232: the four remaining blocking dialogs go window-modal ==")
# askUser (save_threshold's tuned-PDFs offer) and three QMessageBox.question
# statics (start_index's re-index confirm; confirm_close's discard-changes
# and stop-indexing confirms) each opened a nested app-modal event loop —
# the K-114 segfault class already fixed in pdf_drive._delete_pdf.
# Same shape here: a
# hand-built QMessageBox, themed, shown via open(), with the Yes/No
# decision read from clickedButton() inside a finished handler.
check("K-232: no blocking askUser or QMessageBox.question anywhere in "
      "this file — the board card's own verify condition, pinned so a "
      "regression fails a real test and not just the board gate",
      "askUser" not in _src2 and "QMessageBox.question" not in _src2)

_save_threshold_src = _fn_src("_apply_threshold_to_tuned")
check("the threshold_changed effect handler was found", bool(_save_threshold_src))
check("the tuned-PDFs confirm is window-modal — hand-built QMessageBox, "
      "open() + finished, never a blocking call",
      "msg = QMessageBox(dlg)" in _save_threshold_src
      and "msg.finished.connect(_on_answered)" in _save_threshold_src
      and "msg.open()" in _save_threshold_src
      and ".exec()" not in _save_threshold_src)
check("...defaults Yes, matching the replaced call's own no-defaultno "
      "default (setup_flow's askUser conversions set the same precedent)",
      "setDefaultButton(QMessageBox.StandardButton.Yes)" in _save_threshold_src)
check("...and the Library refresh runs from every exit path (the error "
      "branch, the nothing-to-offer branch, and the finished handler) "
      "since it depends on the value already written to config, not on "
      "whether the user cleared the per-PDF overrides",
      _save_threshold_src.count("_refresh_library()") == 4)
_st_on_answered = _save_threshold_src.split("def _on_answered", 1)[1]
check("...clear_threshold_overrides only runs from the finished handler, "
      "gated on confirmed — never unconditionally once the dialog is up",
      "if confirmed:" in _st_on_answered
      and _st_on_answered.index("if confirmed:")
      < _st_on_answered.index("retention.clear_threshold_overrides()"))

_start_index_src = _fn_src("start_index")
check("start_index was found", bool(_start_index_src))
check("the re-index-from-scratch confirm is window-modal — hand-built "
      "QMessageBox, open() + finished, never a blocking call",
      "msg = QMessageBox(dlg)" in _start_index_src
      and "msg.finished.connect(_on_answered)" in _start_index_src
      and "msg.open()" in _start_index_src
      and ".exec()" not in _start_index_src)
check("...No default (matching the replaced static's own fallback), Yes "
      "wears DangerButton for a destructive rebuild-from-scratch",
      "setDefaultButton(QMessageBox.StandardButton.No)" in _start_index_src
      and 'yes_btn.setObjectName("DangerButton")' in _start_index_src)
check("...and _run_index runs unconditionally only when the signature "
      "already matches (no prompt needed); once the dialog is shown it "
      "runs ONLY from the finished handler's Yes",
      _start_index_src.count("_run_index()") == 2
      and "return\n        _run_index()" in _start_index_src)

_confirm_close_src = _fn_src("confirm_close")
check("confirm_close was found", bool(_confirm_close_src))
check("both confirms (discard changes, stop indexing) are window-modal "
      "— two hand-built QMessageBoxes, open() + finished, never a "
      "blocking call",
      _confirm_close_src.count("QMessageBox(dlg)") == 2
      and "msg1.finished.connect(_on_discard_answered)" in _confirm_close_src
      and "msg2.finished.connect(_on_stop_answered)" in _confirm_close_src
      and _confirm_close_src.count(".open()") == 2
      and ".exec()" not in _confirm_close_src)
check("...chained by a plain continuation call rather than a nested "
      "dialog, so the discard confirm and the stop-indexing confirm can "
      "never stack — the continuation is defined before it is used",
      "_after_dirty_check()" in _confirm_close_src
      and _confirm_close_src.index("def _after_dirty_check")
      < _confirm_close_src.index("if state.dirty:"))
check("...and dlg.accept() only fires from a Yes/skip path — the "
      "no-dialog-needed fallthrough and the stop-confirm's Yes — never "
      "unconditionally once a confirm is showing",
      _confirm_close_src.count("dlg.accept()") == 2)


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
