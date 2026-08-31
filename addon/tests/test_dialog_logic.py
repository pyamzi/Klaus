"""State-machine tests for the Manage-models dialog's semantic-search half
(embed_provider_combo / embed_model_combo / embed_key_edit).

PyQt6 cannot be imported here (its sip is 3.13-only), so this reimplements
the dialog's decision logic against faithful combo semantics and asserts the
behaviours that matter: the ui_state['syncing'] guard, the embed_fix_btn
dispatcher (_embed_fix_kind returning 'key' / 'model' / ''), assignment
round-trips, and the empty-library / uninstalled-model edge cases.

Kept in lockstep with manage_models_dialog by construction — the functions
below are transcribed from it; if that code changes these must too. The
K-039 section further down covers manage_models._resolve_ollama_model and
its config write-back guard in isolation and is maintained separately.
"""
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


class Combo:
    """QComboBox semantics: items carry (text, data); index changes signal."""

    def __init__(self, on_change=None):
        self.items = []
        self.index = -1
        self.on_change = on_change
        self._edit_text = ""

    def clear(self):
        self.items = []
        self.index = -1

    def addItem(self, text, data=None):
        self.items.append((text, data))
        if self.index == -1:
            self.index = 0

    def count(self):
        return len(self.items)

    def findData(self, data):
        for i, (_t, d) in enumerate(self.items):
            if d == data:
                return i
        return -1

    def setCurrentIndex(self, i):
        changed = i != self.index
        self.index = i
        if changed and self.on_change:
            self.on_change()

    def currentData(self):
        if 0 <= self.index < len(self.items):
            return self.items[self.index][1]
        return None

    def currentText(self):
        if self._edit_text:
            return self._edit_text
        return self.items[self.index][0] if 0 <= self.index < len(self.items) else ""

    def setEditText(self, t):
        self._edit_text = t

    def pick(self, data):
        """Simulate a user choosing the item with this data."""
        i = self.findData(data)
        assert i >= 0, f"no item with data {data!r}"
        self.setCurrentIndex(i)


class LineEdit:
    """QLineEdit semantics needed here: get/set text, and an editingFinished
    signal that fires when the simulated user finishes typing (embed_key_edit
    and embed_model_combo's line edit both connect editingFinished to
    save_embed in the real dialog)."""

    def __init__(self, on_finish=None):
        self._text = ""
        self.on_finish = on_finish

    def text(self):
        return self._text

    def setText(self, t):
        self._text = t

    def type_and_leave(self, t):
        """Simulate a user typing into the field and then leaving it."""
        self._text = t
        if self.on_finish:
            self.on_finish()


_EMBED_DEFAULTS = {
    "ollama": "nomic-embed-text",
    "openai": "text-embedding-3-small",
    "voyage": "voyage-3-lite",
}


def _resolve_ollama_model(configured, models, indexed_model, default):
    """Transcribed from manage_models._resolve_ollama_model, needed here so
    World.sync_embed_widgets can be transcribed faithfully too. The K-039
    section below transcribes its own copy independently for isolated
    resolver checks — both must be kept in lockstep with the real function."""
    configured = configured.strip()
    if configured:
        return configured
    if indexed_model and indexed_model in models:
        return indexed_model
    if len(models) == 1:
        return models[0]
    return default


class World:
    """The manage_models_dialog's semantic-search closure, transcribed:
    embed_provider_combo / embed_model_combo / embed_key_edit, the
    ui_state['syncing'] guard, and the embed_fix_btn dispatcher
    (_embed_fix_kind / on_embed_fix_clicked)."""

    def __init__(self, cfg, models, indexed_model=""):
        self.cfg = dict(cfg)
        # indexed_model mirrors curation.index_stats()["model"] when an
        # index already exists, else "".
        self.indexed_model = indexed_model
        self.ui_state = {
            "models": list(models), "syncing": False, "embed_fix_kind": "",
            "dirty": False, "shown_provider": "",
        }
        self.saves = 0
        self.opened_key_pages = []
        self.pulled_models = []

        # Deferred save: widgets mark dirty, save_all() writes.
        self.embed_provider_combo = Combo(on_change=self.on_provider_changed)
        self.embed_provider_combo.addItem("Voyage API (Default)", "voyage")
        self.embed_provider_combo.addItem("OpenAI API", "openai")
        self.embed_provider_combo.addItem("Local Ollama (private, free)", "ollama")
        self.embed_model_combo = Combo(on_change=lambda: self.mark_dirty())
        self.embed_key_edit = LineEdit(on_finish=lambda: self.mark_dirty())

        self.sync_embed_widgets()

    # --- transcribed from embeddings.py (provider_name/embedding_model/index_signature) ---

    def _provider_name(self):
        p = str(self.cfg.get("embedding_provider") or "voyage").strip().lower()
        return p if p in _EMBED_DEFAULTS else "voyage"

    def _embedding_model(self):
        model = str(self.cfg.get("embedding_model") or "").strip()
        return model or _EMBED_DEFAULTS[self._provider_name()]

    def _index_signature(self):
        return self._provider_name(), self._embedding_model()

    def _embed_cfg_key(self, provider):
        return f"embedding_api_key_{provider}"

    # --- transcribed from manage_models_dialog ---

    def pick_model(self, name):
        """Editable combo: choosing an item from the dropdown syncs the
        line edit's text to it (real QComboBox behaviour for an editable
        box) before the change signal fires. Combo's setCurrentIndex alone
        doesn't do that, so the harness does it explicitly."""
        combo = self.embed_model_combo
        i = combo.findData(name)
        assert i >= 0, f"no item with data {name!r}"
        combo.setEditText(name)
        combo.setCurrentIndex(i)

    def mark_dirty(self):
        if self.ui_state["syncing"]:
            return
        self.ui_state["dirty"] = True

    def clear_dirty(self):
        self.ui_state["dirty"] = False

    def on_provider_changed(self):
        if self.ui_state["syncing"]:
            return
        self.mark_dirty()
        self.sync_embed_widgets(
            provider_override=str(self.embed_provider_combo.currentData() or "ollama")
        )

    def save_all(self):
        self.clear_dirty()
        self.save_embed()

    def sync_embed_widgets(self, provider_override=None):
        if provider_override is None and self.ui_state["dirty"]:
            return  # never clobber unsaved edits
        self.ui_state["syncing"] = True
        try:
            provider = provider_override or self._provider_name()
            self.ui_state["shown_provider"] = provider
            idx = max(0, self.embed_provider_combo.findData(provider))
            self.embed_provider_combo.setCurrentIndex(idx)
            # Local provider -> offer every installed model; cloud -> free
            # text (no items, just the line edit).
            self.embed_model_combo.clear()
            if provider == "ollama":
                for name in self.ui_state["models"]:
                    self.embed_model_combo.addItem(name, name)
            configured_model = str(self.cfg.get("embedding_model") or "")
            if provider_override is not None:
                # Widgets moving to a provider other than the stored one:
                # the stored model name belongs to the old provider.
                configured_model = ""
            if provider == "ollama":
                resolved = _resolve_ollama_model(
                    configured_model, self.ui_state["models"], self.indexed_model,
                    _EMBED_DEFAULTS["ollama"],
                )
                if (
                    resolved != configured_model
                    and self.ui_state["models"]
                    and provider_override is None
                ):
                    # Heal the config now, not just the widget (K-039) —
                    # only when models were actually enumerated, so an
                    # unreachable Ollama can't durably orphan an index.
                    self.cfg["embedding_model"] = resolved
                self.embed_model_combo.setEditText(resolved)
            else:
                self.embed_model_combo.setEditText(configured_model)
            self.embed_key_edit.setText(
                str(self.cfg.get(self._embed_cfg_key(provider)) or ""))
        finally:
            self.ui_state["syncing"] = False
        self.update_embed_status()

    def update_embed_status(self):
        self.ui_state["embed_fix_kind"] = self._embed_fix_kind()

    def _embed_fix_kind(self):
        """'key' when the selected cloud provider has no API key configured,
        'model' when the local embed model named in config isn't installed,
        '' when neither."""
        sig = self._index_signature()
        provider = self.embed_provider_combo.currentData() or "ollama"
        is_cloud = provider != "ollama"
        if is_cloud and not str(self.cfg.get(self._embed_cfg_key(provider)) or "").strip():
            return "key"
        if not is_cloud and sig[1] and sig[1] not in self.ui_state["models"]:
            return "model"
        return ""

    def on_embed_fix_clicked(self):
        """Sole handler for embed_fix_btn.clicked — dispatches on the state
        update_embed_status() last computed, not recomputed here."""
        kind = self.ui_state.get("embed_fix_kind", "")
        if kind == "key":
            provider = str(self.embed_provider_combo.currentData() or "voyage")
            self.opened_key_pages.append(provider)
        elif kind == "model":
            self.pulled_models.append(self.embed_model_combo.currentText().strip())

    def save_embed(self):
        if self.ui_state["syncing"]:
            return
        self.saves += 1
        provider = str(self.embed_provider_combo.currentData() or "ollama")
        prev = self._provider_name()
        self.cfg["embedding_provider"] = provider
        # Widgets were repopulated for `provider` when it was picked, so
        # their contents already belong to it (comparing against the
        # STORED provider here would discard a model typed for the new
        # one — the auto-save-era bug).
        if self.ui_state.get("shown_provider", provider) == provider:
            self.cfg["embedding_model"] = self.embed_model_combo.currentText().strip()
        else:
            self.cfg["embedding_model"] = ""
        if provider != "ollama":
            self.cfg[self._embed_cfg_key(provider)] = self.embed_key_edit.text().strip()
        if provider != prev:
            self.sync_embed_widgets()  # reload model/key fields for the new provider
        else:
            self.update_embed_status()


BASE = {"embedding_provider": "voyage", "embedding_model": "",
        "embedding_api_key_voyage": ""}

print("== provider default and the syncing guard ==")
w = World(BASE, models=[])
check("defaults to voyage", w.embed_provider_combo.currentData() == "voyage")
check("opening the dialog saves nothing", w.saves == 0)
before = w.saves
w.sync_embed_widgets()
check("repopulating combos writes no config", w.saves == before)

print("== cloud provider with no key -> kind 'key' ==")
w = World(BASE, models=[])
check("voyage with empty key needs a key", w.ui_state["embed_fix_kind"] == "key")
check("cloud provider offers no model items, free text only",
      w.embed_model_combo.count() == 0)
w.on_embed_fix_clicked()
check("fix button opens the voyage key page", w.opened_key_pages == ["voyage"])

print("== cloud provider with a key -> kind '' (ready) ==")
w = World({**BASE, "embedding_api_key_voyage": "pa-xyz"}, models=[])
check("key present clears the warning", w.ui_state["embed_fix_kind"] == "")

print("== local provider with an uninstalled model -> kind 'model' ==")
w = World({"embedding_provider": "ollama", "embedding_model": "mxbai-embed-large"},
          models=["nomic-embed-text"])
check("configured model not in library needs a pull",
      w.ui_state["embed_fix_kind"] == "model")
check("model dropdown lists only what's installed, not the missing one",
      [n for n, _d in w.embed_model_combo.items] == ["nomic-embed-text"])
w.on_embed_fix_clicked()
check("fix button pulls the configured (missing) model, not an installed one",
      w.pulled_models == ["mxbai-embed-large"])

print("== local provider, model installed -> kind '' (ready) ==")
w = World({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"},
          models=["nomic-embed-text", "all-minilm"])
check("installed model needs no fix", w.ui_state["embed_fix_kind"] == "")
check("model dropdown offers only the installed models",
      sorted(n for n, _d in w.embed_model_combo.items) == ["all-minilm", "nomic-embed-text"])

print("== local provider, empty library -> still 'model' (edge case) ==")
w = World({"embedding_provider": "ollama", "embedding_model": ""}, models=[])
check("empty config falls back to the hardcoded default for display",
      w.embed_model_combo.currentText() == "nomic-embed-text")
check("but an empty library still can't run it -> kind 'model'",
      w.ui_state["embed_fix_kind"] == "model")
check("empty library is not healed into config (nothing installed to confirm)",
      w.cfg["embedding_model"] == "")

print("== empty configured model heals from an installed library on open ==")
w = World({"embedding_provider": "ollama", "embedding_model": ""},
          models=["embeddinggemma"])
check("resolver picks the one installed model",
      w.embed_model_combo.currentText() == "embeddinggemma")
check("and writes it back to config (the sync_embed_widgets heal branch)",
      w.cfg["embedding_model"] == "embeddinggemma")
check("healing on open does not count as a user save", w.saves == 0)

print("== deferred save: edits do not reach config until Save ==")
w = World({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"},
          models=["nomic-embed-text", "all-minilm"])
w.pick_model("all-minilm")
check("picking a model marks dirty", w.ui_state["dirty"] is True)
check("picking a model writes NOTHING yet",
      w.cfg["embedding_model"] == "nomic-embed-text")
check("no save happened", w.saves == 0)
w.save_all()
check("Save persists the pick", w.cfg["embedding_model"] == "all-minilm")
check("Save clears dirty", w.ui_state["dirty"] is False)

w = World(BASE, models=[])
w.embed_key_edit.type_and_leave("pa-new-key")
check("typing a key marks dirty but writes nothing",
      w.ui_state["dirty"] is True
      and w.cfg.get("embedding_api_key_voyage") == "")
w.save_all()
check("Save persists the key", w.cfg["embedding_api_key_voyage"] == "pa-new-key")

print("== a refresh while dirty must not clobber unsaved edits ==")
w = World({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"},
          models=["nomic-embed-text", "all-minilm"])
w.pick_model("all-minilm")
w.sync_embed_widgets()          # what refresh() does after a pull/check
check("unsaved pick survives a refresh",
      w.embed_model_combo.currentText() == "all-minilm")
w.save_all()
check("and still saves correctly afterwards",
      w.cfg["embedding_model"] == "all-minilm")

print("== switching provider reloads the fields without writing ==")
w = World({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"},
          models=["nomic-embed-text"])
w.embed_provider_combo.pick("openai")
check("provider switch writes nothing yet",
      w.cfg["embedding_provider"] == "ollama")
check("but the widgets already show the new provider",
      w.ui_state["shown_provider"] == "openai")
check("cloud fields reset to empty (no openai key yet)", w.embed_key_edit.text() == "")
w.save_all()
check("Save writes the new provider", w.cfg["embedding_provider"] == "openai")
check("old provider's model is dropped, not carried over", w.cfg["embedding_model"] == "")

print("== provider switch THEN a typed model keeps the typed model (regression) ==")
# Under the auto-save-era logic (compare against the STORED provider) this
# silently saved "" and the typed model vanished.
w = World({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"},
          models=["nomic-embed-text"])
w.embed_provider_combo.pick("openai")
w.embed_model_combo.setEditText("text-embedding-3-large")
w.save_all()
check("the model typed for the NEW provider survives Save",
      w.cfg["embedding_model"] == "text-embedding-3-large")
check("provider saved alongside it", w.cfg["embedding_provider"] == "openai")

print("== empty embedding_model resolver (K-039, manage_models._resolve_ollama_model) ==")


def _resolve_ollama_model(configured, models, indexed_model, default):
    """Transcribed verbatim from manage_models._resolve_ollama_model — if
    that function changes this must too. Decides what real model name the
    ollama 'Search model' field should show/hold when embedding_model is
    empty, instead of silently falling through to
    embeddings.DEFAULT_MODELS['ollama'] (which can mismatch an existing
    index and make one click on 'Index Now' discard it)."""
    configured = configured.strip()
    if configured:
        return configured
    if indexed_model and indexed_model in models:
        return indexed_model
    if len(models) == 1:
        return models[0]
    return default


check(
    "empty + indexed model installed -> the indexed model",
    _resolve_ollama_model("", ["nomic-embed-text", "embeddinggemma:latest"],
                          "embeddinggemma:latest", "nomic-embed-text")
    == "embeddinggemma:latest",
)
check(
    "empty + exactly one installed -> that one",
    _resolve_ollama_model("", ["embeddinggemma:latest"], "", "nomic-embed-text")
    == "embeddinggemma:latest",
)
check(
    "empty + none installed -> hardcoded default",
    _resolve_ollama_model("", [], "", "nomic-embed-text") == "nomic-embed-text",
)
check(
    "non-empty -> untouched, indexed/installed state ignored",
    _resolve_ollama_model("qwen3:4b", ["embeddinggemma:latest"],
                          "embeddinggemma:latest", "nomic-embed-text")
    == "qwen3:4b",
)
check(
    "indexed model present but NOT installed -> falls through, not (a)",
    _resolve_ollama_model("", ["all-minilm", "bge-m3"], "embeddinggemma:latest",
                          "nomic-embed-text") == "nomic-embed-text",
)



print("== resolver write-back must not persist an uninformed fallback (K-039 review) ==")


def _should_persist(resolved, configured, models):
    """Transcribed from manage_models.sync_embed_widgets' heal branch.

    The resolver always returns SOMETHING to display, but the config may
    only be rewritten when we actually enumerated the installed models.
    With an empty list (Ollama unreachable) the resolver falls through to
    the hardcoded default; persisting that would durably orphan an index
    built with a different model.
    """
    return resolved != configured and bool(models)


check(
    "informed resolution persists",
    _should_persist("embeddinggemma:latest", "", ["embeddinggemma:latest"]) is True,
)
check(
    "uninformed fallback (no model list) does NOT persist",
    _should_persist("nomic-embed-text", "", []) is False,
)
check(
    "no change means no write even with a populated list",
    _should_persist("qwen3:4b", "qwen3:4b", ["qwen3:4b"]) is False,
)


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
      and "_top_bar.star_points()" in _src2)
check("the logo strokes blue_accent and repaints on an accent save",
      'QColor(c["blue_accent"])' in _src2
      and "logo_lbl.setPixmap(_new_logo)" in _src2)
check("settings search: a filter field sits in the sidebar",
      'setObjectName("SettingsSearch")' in _src2
      and "search_edit.textChanged.connect(_apply_search)" in _src2)
check("search rows carry haystacks and register per page",
      "roww.klaus_search" in _src2
      and "_rows_by_page.setdefault(" in _src2)
check("structural hiding beats a search hit (Ollama key row)",
      "hit and not roww.klaus_hidden" in _src2
      and "key_row.klaus_hidden = not is_cloud" in _src2)
check("pages without rows stay findable by their haystack",
      "_page_haystack[nav_label]" in _src2)
check("no-hit pages dim + lose clickability instead of vanishing",
      "Qt.ItemFlag.ItemIsEnabled" in _src2
      and "ForegroundRole" in _src2)
check("every section is a page with a sidebar pill and a big title",
      _src2.count("= _page(") == 4
      and 'setObjectName("SettingsNav")' in _src2
      and 'setObjectName("PageTitle")' in _src2
      and 'setObjectName("PageSubtitle")' in _src2)
check("display order is decoupled from build order via _finish_nav",
      '_finish_nav("General", "Appearance", "Semantic Search", '
      '"Local Models")' in _src2)
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
check("the API-key ROW hides whole for Ollama — via the search "
      "filter's structural-hide channel, separator handling included",
      "key_row.klaus_hidden = not is_cloud" in _src2
      and "roww.klaus_sep.setVisible(show and seen)" in _src2)
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
check("nav geometry is pure view geometry: setSizeHint rows + list "
      "setSpacing + an overshooting fixed height — nothing QSS-derived "
      "(three pill-era fixes fought polish timing; a single list view "
      "has no per-button hints to get wrong)",
      "item.setSizeHint(QSize(0, row_h))" in _src2
      and "nav_list.setSpacing(3)" in _src2
      and "nav_list.setFixedHeight(" in _src2)


print("== install page onto the K-106 shell language (K-111) ==")
# Page 0 (the pre-K-106 "Set up local AI" page) predated the sidebar shell
# and hand-styled its two headings with literal setStyleSheet font strings.
# K-111 gives it the same PageTitle/PageSubtitle opening as every other
# page (built by hand here, not via _page(), since this page keeps its own
# full-frame layout with no sidebar pill) and moves InstallHeading /
# InstallSection onto objectNames K-110 styles centrally.
_install_src = _src2.split("# ----- Page 0: Install Ollama", 1)[1].split(
    "# ----- Page 1:", 1)[0]
check("no literal font setStyleSheet remains on the install page",
      "font-weight" not in _install_src
      and "font-size" not in _install_src)
check("the install page opens with a PageTitle + PageSubtitle pair, "
      "margins matching _page()",
      'install_title.setObjectName("PageTitle")' in _install_src
      and 'install_body.setObjectName("PageSubtitle")' in _install_src
      and "install_body.setWordWrap(True)" in _install_src
      and "setContentsMargins(24, 18, 24, 8)" in _install_src)
check("the two hand-styled labels moved to InstallHeading / InstallSection",
      # The old "Set up local AI" heading label is GONE — with a real
      # PageTitle above it, keeping it duplicated the title (caught in
      # orchestrator review of K-111).
      "install_heading" not in _install_src
      and 'manual_lbl.setObjectName("InstallSection")' in _install_src)

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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
