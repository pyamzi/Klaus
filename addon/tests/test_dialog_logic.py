"""State-machine tests for the Preferences dialog's "API keys & models"
page (openai_key_edit / embed_model_edit) and its default-sensitivity
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


_DEFAULT_EMBED_MODEL = "text-embedding-3-large"


class World:
    """manage_models_dialog's "API keys & models" closure, transcribed:
    openai_key_edit / embed_model_edit, the ui_state['syncing'] and
    ['dirty'] guards, sync_embed_widgets and save_embed. There is ONE
    embedding provider now (OpenAI), so the provider combo, the
    per-provider key fan-out and the Ollama resolver are gone — what is
    left to get wrong is the deferred-save contract, which is what these
    pins are for.

    """

    def __init__(self, cfg):
        self.cfg = dict(cfg)
        self.ui_state = {"syncing": False, "dirty": False}
        self.saves = 0
        self.sweeps = []
        self.openai_key_edit = LineEdit()
        self.embed_model_edit = LineEdit()
        self.sync_embed_widgets()

    # --- transcribed from embeddings.py (embedding_model/index_signature) ---

    def _embedding_model(self):
        return str(self.cfg.get("embedding_model") or "").strip() or _DEFAULT_EMBED_MODEL

    def _index_signature(self):
        return "openai", self._embedding_model(), 0

    # --- transcribed from manage_models_dialog ---

    def mark_dirty(self):
        if self.ui_state["syncing"]:
            return
        self.ui_state["dirty"] = True

    def sync_embed_widgets(self):
        if self.ui_state["dirty"]:
            return
        self.ui_state["syncing"] = True
        try:
            self.openai_key_edit.setText(str(self.cfg.get("api_key_openai") or ""))
            self.embed_model_edit.setText(str(self.cfg.get("embedding_model") or ""))
        finally:
            self.ui_state["syncing"] = False

    def type_key(self, text):
        self.openai_key_edit.setText(text)
        self.mark_dirty()

    def type_model(self, text):
        self.embed_model_edit.setText(text)
        self.mark_dirty()

    def save_embed(self):
        if self.ui_state["syncing"]:
            return
        prev_sig = self._index_signature()
        had_key = bool(str(self.cfg.get("api_key_openai") or "").strip())
        self.cfg["api_key_openai"] = self.openai_key_edit.text().strip()
        self.cfg["embedding_model"] = self.embed_model_edit.text().strip()
        self.saves += 1
        self.sweeps.append(
            (prev_sig, self._index_signature(), not had_key and bool(self.cfg["api_key_openai"]))
        )

    def save_all(self):
        self.ui_state["dirty"] = False
        self.save_embed()

BASE = {"api_key_openai": "", "embedding_model": ""}

print("== opening the page writes nothing ==")
w = World(BASE)
check("the key field seeds from config", w.openai_key_edit.text() == "")
check("opening the dialog saves nothing", w.saves == 0)
before = w.saves
w.sync_embed_widgets()
check("repopulating the fields writes no config", w.saves == before)

print("== deferred save: edits do not reach config until Save ==")
w = World(BASE)
w.type_key("sk-new-key")
check("typing a key marks dirty but writes nothing",
      w.ui_state["dirty"] is True and w.cfg["api_key_openai"] == "")
w.save_all()
check("Save persists the key", w.cfg["api_key_openai"] == "sk-new-key")
check("Save clears dirty", w.ui_state["dirty"] is False)

w = World({"api_key_openai": "sk", "embedding_model": ""})
w.type_model("text-embedding-3-small")
check("typing a model writes nothing yet", w.cfg["embedding_model"] == "")
w.save_all()
check("Save persists the model", w.cfg["embedding_model"] == "text-embedding-3-small")

print("== a refresh while dirty must not clobber unsaved edits ==")
w = World({"api_key_openai": "sk", "embedding_model": "text-embedding-3-large"})
w.type_model("text-embedding-3-small")
w.sync_embed_widgets()          # what refresh() does
check("unsaved edit survives a refresh",
      w.embed_model_edit.text() == "text-embedding-3-small")
w.save_all()
check("and still saves correctly afterwards",
      w.cfg["embedding_model"] == "text-embedding-3-small")

print("== the sweep offer: a model change, or a first key ==")
w = World({"api_key_openai": "sk", "embedding_model": "text-embedding-3-large"})
w.type_model("text-embedding-3-small")
w.save_all()
_prev, _cur, _first = w.sweeps[-1]
check("the PREVIOUS signature is the one the stored vectors were made "
      "with, captured before the widgets overwrite config",
      _prev == ("openai", "text-embedding-3-large", 0))
check("...and the current one is what was just saved",
      _cur == ("openai", "text-embedding-3-small", 0))
check("a model change is not a first key", _first is False)

w = World(BASE)
w.type_key("sk-first")
w.save_all()
_prev, _cur, _first = w.sweeps[-1]
check("an empty key filled in for the first time IS a first key — the "
      "signature never moved, but nothing has ever been embedded",
      _first is True and _prev == _cur)

w = World({"api_key_openai": "sk-old", "embedding_model": "text-embedding-3-large"})
w.type_key("sk-rotated")
w.save_all()
_prev, _cur, _first = w.sweeps[-1]
check("rotating an existing key is NOT a first key — the vectors on "
      "disk are still valid, and re-embedding the collection on a key "
      "change would be a bill for nothing",
      _first is False and _prev == _cur)


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


print("== default-sensitivity slider: dialog-side flag wiring (K-052) ==")


class Slider:
    """QSlider semantics needed here: setValue fires valueChanged only when
    the value actually changes (real Qt behaviour, mirrored by Combo
    above); sliderReleased is a distinct signal that ONLY a genuine user
    mouse/touch release ever triggers — a programmatic setValue() never
    emits it. That distinction is what makes sliderReleased (not
    valueChanged) the safe place to persist a change and set the
    user-set flag from."""

    def __init__(self, on_change=None, on_release=None):
        self._value = 0
        self.on_change = on_change
        self.on_release = on_release

    def value(self):
        return self._value

    def setValue(self, v):
        changed = v != self._value
        self._value = v
        if changed and self.on_change:
            self.on_change(v)

    def user_drag_and_release(self, v):
        """A real user dragging the handle to v and releasing the mouse —
        the only path that should ever persist a change."""
        self.setValue(v)
        if self.on_release:
            self.on_release()

    def user_click_release_no_move(self):
        """A plain click-and-release that changes nothing — must still not
        write anything."""
        if self.on_release:
            self.on_release()


class ThresholdWorld:
    """manage_models_dialog's default-sensitivity control, transcribed:
    sync_threshold_widget / save_threshold and the ui_state['syncing']
    guard shared with the rest of the dialog (see World above for the
    embed-widget half of the same guard)."""

    DEFAULT_THRESHOLD = 0.75

    def __init__(self, cfg):
        self.cfg = dict(cfg)
        self.ui_state = {"syncing": False, "dirty": False}
        self.writes = 0
        # Deferred save: a release marks dirty; save_all() (the Save
        # button) is what calls save_threshold.
        self.slider = Slider(on_release=self.mark_dirty)
        self.sync_threshold_widget()

    def mark_dirty(self):
        if self.ui_state["syncing"]:
            return
        self.ui_state["dirty"] = True

    def save_all(self):
        self.ui_state["dirty"] = False
        self.save_threshold()

    def sync_threshold_widget(self):
        if self.ui_state["dirty"]:
            return  # never clobber an unsaved slider position
        self.ui_state["syncing"] = True
        try:
            try:
                value = float(
                    self.cfg.get("pdf_match_threshold") or self.DEFAULT_THRESHOLD
                )
            except (TypeError, ValueError):
                value = self.DEFAULT_THRESHOLD
            self.slider.setValue(int(round(value * 100)))
        finally:
            self.ui_state["syncing"] = False

    def save_threshold(self):
        if self.ui_state["syncing"]:
            return
        value = round(self.slider.value() / 100.0, 3)
        try:
            current = round(
                float(self.cfg.get("pdf_match_threshold") or self.DEFAULT_THRESHOLD),
                3,
            )
        except (TypeError, ValueError):
            current = None
        if value == current:
            return
        self.cfg["pdf_match_threshold"] = value
        self.cfg["_threshold_user_set"] = True
        self.writes += 1


w = ThresholdWorld({"pdf_match_threshold": 0.55})
check("opens showing the stored value", w.slider.value() == 55)
check("populating the widget on open writes nothing", w.writes == 0)
check(
    "populating the widget on open does not stamp the user-set flag",
    "_threshold_user_set" not in w.cfg,
)

before = w.writes
w.sync_threshold_widget()  # e.g. Refresh / Check connection re-populating
check("re-syncing without touching the slider still writes nothing",
      w.writes == before)
check(
    "repeated programmatic repopulation still never stamps the flag",
    "_threshold_user_set" not in w.cfg,
)

w = ThresholdWorld({"pdf_match_threshold": 0.55})
w.slider.user_click_release_no_move()
w.save_all()
check("a click-release that changes nothing writes nothing", w.writes == 0)
check("no user-set flag from a no-op release", "_threshold_user_set" not in w.cfg)

w = ThresholdWorld({"pdf_match_threshold": 0.75})
w.slider.user_drag_and_release(55)
check("dragging alone writes nothing until Save",
      "pdf_match_threshold" in w.cfg and w.cfg["pdf_match_threshold"] == 0.75
      and w.writes == 0)
check("dragging marks dirty", w.ui_state["dirty"] is True)
w.sync_threshold_widget()   # a refresh landing mid-edit
check("an unsaved slider position survives a refresh", w.slider.value() == 55)
w.save_all()
check("dragging and releasing then saving persists the new value",
      w.cfg["pdf_match_threshold"] == 0.55)
check("dragging and releasing then saving stamps the user-set flag",
      w.cfg.get("_threshold_user_set") is True)
check("exactly one write for one drag-and-release-and-save", w.writes == 1)

w = ThresholdWorld({"pdf_match_threshold": 0.55})
w.slider.user_drag_and_release(55)  # releases at the value already stored
w.save_all()
check("releasing at the already-stored value writes nothing", w.writes == 0)
check(
    "no user-set flag when the value didn't actually change",
    "_threshold_user_set" not in w.cfg,
)

print("== the syncing guard is load-bearing on its own (orchestrator review) ==")

# Every check above is satisfied by the value-differs guard ALONE, because
# sync always sets the slider to the stored value, so the two agree and the
# save returns early either way. Deleting ui_state['syncing'] from
# save_threshold left the whole suite green — which means nothing pinned it,
# and a future refactor could drop it silently.
#
# It is not redundant. The slider is integer 1/100 steps, so a stored value
# it cannot represent (hand-edited config, or any future writer with more
# precision) makes widget and stored value genuinely DIFFER during a
# programmatic sync. Then only the syncing guard stands between opening the
# dialog and having your value rewritten and stamped user-set — which
# permanently opts that profile out of every later default bump.
w = ThresholdWorld({"pdf_match_threshold": 0.753})
check("a non-representable stored value shows as the nearest step", w.slider.value() == 75)
check("merely opening does not rewrite it", w.writes == 0)

w.ui_state["syncing"] = True
w.save_threshold()  # what a naive valueChanged wiring would do mid-sync
w.ui_state["syncing"] = False
check(
    "syncing guard blocks a save even when widget and stored value DIFFER",
    w.writes == 0,
)
check(
    "...and no user-set flag is stamped by that blocked save",
    "_threshold_user_set" not in w.cfg,
)
check("the stored value is left exactly as it was", w.cfg["pdf_match_threshold"] == 0.753)

# And the mirror: with syncing clear, that same difference SHOULD persist —
# proving the guard is what blocked it, not the value-diff check.
w.save_threshold()
check("with syncing clear, a real difference does persist", w.writes == 1)
check("which is the path that legitimately stamps the flag", w.cfg["_threshold_user_set"] is True)

print("== end to end: a slider-set value survives a later default bump ==")
w = ThresholdWorld({"pdf_match_threshold": 0.75})
w.slider.user_drag_and_release(55)  # user deliberately picks 0.55
w.save_all()                        # ...and commits it with Save
bumped = _migrate_default_threshold(w.cfg, 0.85)
check(
    "the dialog's own output config is untouched by a later migration",
    bumped["pdf_match_threshold"] == 0.55,
)


print("== appearance block scoping (live NameError regression) ==")
# sync_background_widgets() runs at dialog-build time, BEFORE the
# ui_state assignment further down manage_models_dialog. A closure's
# free variables bind at call time, so referencing ui_state there
# crashed Preferences on open with NameError. The appearance block must
# stay self-contained on _bg_state.
_src = open("klausmate/manage_models.py").read()
_dlg = _src.split("def manage_models_dialog", 1)[1]
_call_at = _dlg.index("\n    sync_background_widgets()\n")  # the CALL, not the def
_ui_state_at = _dlg.index('ui_state: dict')
check("the immediate sync call still precedes ui_state's assignment "
      "(the ordering that makes this dangerous)", _call_at < _ui_state_at)
_bg_block = _dlg[_dlg.index("_bg_state = {"):_call_at]
check("appearance block never touches ui_state", "ui_state" not in _bg_block)
check("appearance block guards with its own flag",
      '_bg_state["syncing"]' in _bg_block)


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
check("sidebar identity: star logo beside the Garamond wordmark",
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
      '_finish_nav("General", "Appearance", "API keys & models")' in _src2)
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
      'cfg["color_theme"] = _accent_state["name"]' in _src2
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
      < _init_src.index("append(_migrate_config)"))
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
      'cfg["color_theme_custom"] = _accent_state["custom"]' in _src2
      and _apply_live.index("set_custom_colour(str(_accent_state")
      < _apply_live.index("set_active_theme(str(_accent_state"))
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
      "bool(_heatmap.enabled(_pkg().get_config()))" in code_only(_src2))
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

check("every appearance widget previews live, not just marks dirty — "
      "thirteen handlers: design toggle, mode, fit, blur, wash, "
      "image chosen, image removed, accent swatch, and the study "
      "screen's own mode/fit/wash/image-chosen/image-removed (sphere "
      "colours live on the on-screen dots now — the four colour-"
      "picker buttons left with the edge-colour option, 2026-08-30)",
      _mm_src.count("        appearance_changed()") == 13)
check("save and preview carry the design key as the IDENTICAL "
      "expression — the preview dict replaces config and the gates "
      "default OFF, so a preview missing the key strips the whole "
      "look mid-drag, while a save missing it leaves a zombie screen "
      "that snaps back on the next redraw",
      _mm_src.split("def save_general")[1].split("def mark_dirty")[0]
      .count('cfg["klausbook_design"] = bool(klausbook_cb.isChecked())')
      == 1
      and '"klausbook_design": bool(klausbook_cb.isChecked()),'
      in _mm_src.split("def _bg_preview_cfg")[1].split(
          "def apply_appearance_live")[0])
_save_slice = _mm_src.split("def save_general")[1].split("def mark_dirty")[0]
_preview_slice = _mm_src.split("def _bg_preview_cfg")[1].split(
    "def apply_appearance_live")[0]
check("the study screen's four keys are written from r_spec in "
      "save_general AND read from the identical _bg_state expression "
      "in _bg_preview_cfg — same lesson as klausbook_design, applied "
      "to the background this session just added",
      all(f'cfg["reviewer_background_{field}"]' in _save_slice
          for field in ("mode", "color", "image", "fit"))
      and all(
          f'"reviewer_background_{field}": _bg_state["reviewer_spec"]'
          f'["{field}"],' in _preview_slice
          for field in ("mode", "color", "image", "fit",
                        "grad_x", "grad_y")))
check("the gradient keys ride save AND preview for both screens — "
      "and color2 rides NEITHER: the backdrop stopped being a "
      "setting (a write would resurrect the option in config)",
      all(f'cfg["background_{f}"]' in _save_slice
          and f'cfg["reviewer_background_{f}"]' in _save_slice
          for f in ("grad_x", "grad_y", "grad_size"))
      and "color2" not in _save_slice
      and "color2" not in _preview_slice
      and '"background_grad_size": int(spec["grad_size"]),'
      in _preview_slice
      and '"reviewer_background_grad_size": _bg_state["reviewer_spec"]['
      in _preview_slice)
check("the wash keys ride save AND preview for both screens — the "
      "same parity lesson, fifth field",
      'cfg["background_wash"] = int(spec["wash"])' in _save_slice
      and 'cfg["reviewer_background_wash"] = int(r_spec["wash"])'
      in _save_slice
      and '"background_wash": int(spec["wash"]),' in _preview_slice
      and '"reviewer_background_wash": int(' in _preview_slice)
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
      and "mark_dirty()" in _geom_body
      and "_quiet_preview()" in _geom_body
      and "refresh" not in _geom_body and "replant" not in _geom_body)
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
      _mm_src.count('[dict(g) for g in spec["gradients"]]') == 2
      and 'cfg["reviewer_background_gradients"] = [' in _save_slice
      and '"reviewer_background_gradients": [' in _preview_slice)
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
      "anki_theme_combo.currentIndexChanged.connect(lambda _i: mark_dirty())"
      in _mm_src
      and "mw.set_theme(_Theme(_want))" in _mm_src
      and 'int(getattr(mw.pm.theme(), "value", 0)) != _want' in _mm_src)
check("accent swatches carry accessible names — a bare colour square "
      "is silent in VoiceOver; the name mirrors the tooltip identity",
      'sw.setAccessibleName(' in _mm_src
      and '"Custom accent color"' in _mm_src)
check("appearance_changed both marks unsaved AND schedules the preview",
      "def appearance_changed() -> None:" in _mm_src
      and "mark_dirty()\n        _preview_timer.start()" in _mm_src)
check("the preview is debounced — top_bar.refresh() resets the main "
      "window and the blur slider fires continuously while dragged",
      "_preview_timer = QTimer(dlg)" in _mm_src
      and "_preview_timer.setSingleShot(True)" in _mm_src
      and "_preview_timer.timeout.connect(apply_appearance_live)" in _mm_src)
check("Save is still the ONLY writer of the appearance config keys",
      _mm_src.count('cfg["color_theme"] = ') == 1
      and _mm_src.count('cfg["background_mode"] = ') == 1
      and "def save_general() -> None:" in _mm_src)
check("Save paints through the same one path, THEN drops the override so "
      "a stale preview cannot shadow later config changes",
      "        apply_appearance_live()\n        _background.set_preview(None)"
      in _mm_src)
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
# One page replaces two: the provider combo, the per-provider key fan-out
# and the whole "Local model library (Ollama)" page are gone, and the two
# API keys plus the three model names live together where the money is
# spent. RAW source throughout — an absence pin against code_only() is
# vacuous, because code_only strips the string literals these keys ARE.
check("the page is called \"API keys & models\", as a nav label and a title",
      '"API keys & models",\n        "API keys & models",' in _src2)
check("...and neither page it replaces survives",
      '"Semantic Search"' not in _src2 and '"Local Models"' not in _src2)
check("the four fields the spec names are all constructed",
      all(n in _src2 for n in ("openai_key_edit", "anthropic_key_edit",
                               "embed_model_edit",
                               "transcription_model_edit")))
check("both provider key fields are password masked",
      _src2.count("EchoMode.Password") == 2
      and "openai_key_edit.setEchoMode" in _src2
      and "anthropic_key_edit.setEchoMode" in _src2)
_ast_tree = __import__("ast").parse(_src2)


def _key_edit_leaks(tree) -> bool:
    """True if a print/tooltip/setText/showWarning/showInfo call has a
    ``*_key_edit.text()`` call anywhere inside its arguments.

    An AST walk, not a same-line text scan: the old pin only rejected
    ``print(`` and ``_key_edit.text()`` sharing one physical line, so a
    leak split across two lines (a value assigned on one line, printed
    on the next) would have passed it clean.
    """
    import ast as _a

    sinks = {"print", "tooltip", "setText", "showWarning", "showInfo"}

    def _callee_name(call):
        f = call.func
        if isinstance(f, _a.Name):
            return f.id
        if isinstance(f, _a.Attribute):
            return f.attr
        return None

    def _owner_name(node):
        if isinstance(node, _a.Name):
            return node.id
        if isinstance(node, _a.Attribute):
            return node.attr
        return None

    def _is_key_edit_text_call(node):
        return (
            isinstance(node, _a.Call)
            and isinstance(node.func, _a.Attribute)
            and node.func.attr == "text"
            and (_owner_name(node.func.value) or "").endswith("_key_edit")
        )

    for node in _a.walk(tree):
        if isinstance(node, _a.Call) and _callee_name(node) in sinks:
            args_and_kwargs = list(node.args) + [kw.value for kw in node.keywords]
            for part in args_and_kwargs:
                if any(_is_key_edit_text_call(sub) for sub in _a.walk(part)):
                    return True
    return False


check("a key's VALUE is read only to be saved — never into a print, a "
      "tooltip or a status label — an AST walk over every sink call's "
      "arguments, so a leak split across two lines cannot slip past",
      "openai_key_edit.text()" in _src2 and not _key_edit_leaks(_ast_tree))


def _fn_src(name):
    import ast as _a
    for node in _a.walk(_ast_tree):
        if isinstance(node, _a.FunctionDef) and node.name == name:
            return _a.get_source_segment(_src2, node) or ""
    return ""


_save_embed_src = _fn_src("save_embed")
check("save_embed was found", bool(_save_embed_src))
check("save_embed writes the OpenAI key and the embedding model...",
      '"api_key_openai"' in _save_embed_src
      and '"embedding_model"' in _save_embed_src)
check("...and never the retired provider key — one provider now, so a "
      "stored embedding_provider would be a value nothing reads",
      "embedding_provider" not in _save_embed_src
      and "embedding_api_key_" not in _save_embed_src)

_save_api_key_settings_src = _fn_src("save_api_key_settings")
check("save_api_key_settings was found", bool(_save_api_key_settings_src))
for _k in ("api_key_anthropic", "transcription_model"):
    check(f'save_api_key_settings writes "{_k}"', f'"{_k}"' in _save_api_key_settings_src)
check("...and never the Ollama/Claude-Code era keys",
      "claude_binary" not in _save_api_key_settings_src
      and "ocr_model" not in _save_api_key_settings_src
      and "ocr_enabled" not in _save_api_key_settings_src
      and "assistant_model" not in _save_api_key_settings_src)
check("every one of the four fields is written by exactly one save_*",
      _src2.count('cfg["api_key_openai"] = ') == 1
      and _src2.count('cfg["api_key_anthropic"] = ') == 1
      and _src2.count('cfg["embedding_model"] = ') == 1
      and _src2.count('cfg["transcription_model"] = ') == 1)
_sync_embed_src = _fn_src("sync_embed_widgets")
check("load_api_key_settings runs INSIDE sync_embed_widgets' syncing guard — "
      "seeding a switch that is already true emits toggled, and outside "
      "the guard that marks a dialog nobody has touched as dirty",
      "load_api_key_settings()" in _sync_embed_src
      and _sync_embed_src.index("load_api_key_settings()")
      < _sync_embed_src.index('ui_state["syncing"] = False'))
check("all API fields connect to dirty tracking after mark_dirty is defined",
      all(_src2.index("def mark_dirty() -> None:")
          < _src2.index(f"{name}.textEdited.connect")
          for name in ("openai_key_edit", "anthropic_key_edit",
                       "embed_model_edit", "transcription_model_edit")))
check("Save applies the surviving API key and transcription settings",
      "save_api_key_settings()" in _fn_src("save_all"))
check("General no longer offers to manage a local runtime",
      "runtime_auto_cb" not in _src2 and "runtime_auto_setup" not in _src2)
check("and no module-top import of the deleted runtime modules survives",
      "ollama_client" not in _src2 and "ollama_runtime" not in _src2
      and "ollama_setup" not in _src2)


print("== changing the model re-indexes everything (K-152) ==")
# save_embed is the ONE writer of the embedding keys, so it is also the
# only place that can see the settings move under the stored vectors.
# AST, not text: what matters is the ORDER of statements inside that
# function — capturing the signature after the mutations would compare
# the new settings with themselves and never sweep, silently, forever.
import ast  # noqa: E402

_mm_tree = ast.parse(_mm_src)
_save_embed = next(
    (n for n in ast.walk(_mm_tree)
     if isinstance(n, ast.FunctionDef) and n.name == "save_embed"),
    None,
)
check("save_embed is still the function to pin", _save_embed is not None)


def _stmt_index(fn, needle):
    """Position of the first TOP-LEVEL statement of `fn` whose unparsed
    source contains `needle`. Body order, not ast.walk's breadth-first
    traversal — the whole point of these three pins is the order the
    statements run in."""
    if fn is None:
        return None
    for i, node in enumerate(fn.body):
        try:
            if needle in ast.unparse(node):
                return i
        except Exception:
            pass
    return None


_sig_line = _stmt_index(_save_embed, "index_signature(cfg)")
_mut_line = _stmt_index(_save_embed, "cfg['api_key_openai'] =")
_write_line = _stmt_index(_save_embed, "write_config(cfg)")
_offer_line = _stmt_index(_save_embed, "offer_model_sweep")
check("the previous signature is captured off STORED config",
      _sig_line is not None)
check("...BEFORE the widgets overwrite it — capturing it after would "
      "compare the new settings against themselves and never sweep",
      _sig_line is not None and _mut_line is not None and _sig_line < _mut_line)
check("...and the sweep is offered AFTER the write, so a decline still "
      "leaves the new settings saved",
      _offer_line is not None and _write_line is not None
      and _write_line < _offer_line)
_had_key_line = _stmt_index(_save_embed, "had_key =")
check("the had_key flag is captured off STORED config too, BEFORE the "
      "write — reading it afterwards would make every first key look "
      "like a key that was already there",
      _had_key_line is not None and _mut_line is not None
      and _had_key_line < _mut_line)
_first_key_arg = None
for _n in ast.walk(_save_embed):
    if isinstance(_n, ast.Call) and "offer_model_sweep" in ast.unparse(_n.func):
        for _kw in _n.keywords:
            if _kw.arg == "first_key":
                _first_key_arg = ast.unparse(_kw.value)
check("save_embed asks for the sweep on a FIRST key as well as a moved "
      "signature — a hard False here makes the offer unreachable for "
      "the one user who most needs it, and nothing else would notice",
      _first_key_arg is not None and "had_key" in _first_key_arg,
      f"got {_first_key_arg!r}")
check("save_embed delegates the sweep comparison to index_queue",
      "index_queue.offer_model_sweep(" in code_only(_mm_src)
      and code_only(_mm_src).count("prev_sig") == 2)

_iq_code = code_only(open("klausmate/index_queue.py").read())
check("the sweep offer is raised window-modal — open() and a finished "
      "callback, never exec() (K-114: exec's nested app-modal loop "
      "segfaults on Qt 6.11 + macOS 26, and the Preferences window this "
      "is raised from is itself non-modal)",
      "box.open()" in _iq_code and ".exec()" not in _iq_code)

_test_conn_src = _fn_src("test_connection")
check("test_connection reads the current saved configuration",
      bool(_test_conn_src) and "_pkg().get_config()" in _test_conn_src)

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

_save_threshold_src = _fn_src("save_threshold")
check("save_threshold was found", bool(_save_threshold_src))
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
      < _confirm_close_src.index('if ui_state["dirty"]:'))
check("...and dlg.accept() only fires from a Yes/skip path — the "
      "no-dialog-needed fallthrough and the stop-confirm's Yes — never "
      "unconditionally once a confirm is showing",
      _confirm_close_src.count("dlg.accept()") == 2)


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
