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
        self.ui_state = {"models": list(models), "syncing": False, "embed_fix_kind": ""}
        self.saves = 0
        self.opened_key_pages = []
        self.pulled_models = []

        self.embed_provider_combo = Combo(on_change=self.save_embed)
        self.embed_provider_combo.addItem("Voyage API (default)", "voyage")
        self.embed_provider_combo.addItem("OpenAI API", "openai")
        self.embed_provider_combo.addItem("Local Ollama (private, free)", "ollama")
        self.embed_model_combo = Combo(on_change=self.save_embed)
        self.embed_key_edit = LineEdit(on_finish=self.save_embed)

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

    def sync_embed_widgets(self):
        self.ui_state["syncing"] = True
        try:
            provider = self._provider_name()
            idx = max(0, self.embed_provider_combo.findData(provider))
            self.embed_provider_combo.setCurrentIndex(idx)
            # Local provider -> offer every installed model; cloud -> free
            # text (no items, just the line edit).
            self.embed_model_combo.clear()
            if provider == "ollama":
                for name in self.ui_state["models"]:
                    self.embed_model_combo.addItem(name, name)
            configured_model = str(self.cfg.get("embedding_model") or "")
            if provider == "ollama":
                resolved = _resolve_ollama_model(
                    configured_model, self.ui_state["models"], self.indexed_model,
                    _EMBED_DEFAULTS["ollama"],
                )
                if resolved != configured_model and self.ui_state["models"]:
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
        if provider == prev:
            self.cfg["embedding_model"] = self.embed_model_combo.currentText().strip()
        else:
            # Provider switched: the typed/selected model belonged to the
            # old provider.
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

print("== assignment round-trips ==")
w = World({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"},
          models=["nomic-embed-text", "all-minilm"])
w.pick_model("all-minilm")
check("picking a model writes config", w.cfg["embedding_model"] == "all-minilm")
check("one save for one pick", w.saves == 1)

w = World(BASE, models=[])
w.embed_key_edit.type_and_leave("pa-new-key")
check("typing a key writes config", w.cfg["embedding_api_key_voyage"] == "pa-new-key")
check("key entered clears the fix warning", w.ui_state["embed_fix_kind"] == "")

print("== switching provider drops the old model and resyncs without a double-save ==")
w = World({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"},
          models=["nomic-embed-text"])
w.embed_provider_combo.pick("openai")
check("provider switch writes the new provider", w.cfg["embedding_provider"] == "openai")
check("old provider's model is dropped, not carried over", w.cfg["embedding_model"] == "")
check("switching provider is exactly one save (inner resync must not re-save)",
      w.saves == 1)
check("cloud fields reset to empty (no openai key yet)", w.embed_key_edit.text() == "")

print("== empty embedding_model resolver (K-039, manage_models._resolve_ollama_model) ==")


def _resolve_ollama_model(configured, models, indexed_model, default):
    """Transcribed verbatim from manage_models._resolve_ollama_model — if
    that function changes this must too. Decides what real model name the
    ollama 'Search model' field should show/hold when embedding_model is
    empty, instead of silently falling through to
    embeddings.DEFAULT_MODELS['ollama'] (which can mismatch an existing
    index and make one click on 'Index cards now' discard it)."""
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
        self.ui_state = {"syncing": False}
        self.writes = 0
        self.slider = Slider(on_release=self.save_threshold)
        self.sync_threshold_widget()

    def sync_threshold_widget(self):
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
check("a click-release that changes nothing writes nothing", w.writes == 0)
check("no user-set flag from a no-op release", "_threshold_user_set" not in w.cfg)

w = ThresholdWorld({"pdf_match_threshold": 0.75})
w.slider.user_drag_and_release(55)
check("dragging and releasing persists the new value",
      w.cfg["pdf_match_threshold"] == 0.55)
check("dragging and releasing stamps the user-set flag",
      w.cfg.get("_threshold_user_set") is True)
check("exactly one write for one drag-and-release", w.writes == 1)

w = ThresholdWorld({"pdf_match_threshold": 0.55})
w.slider.user_drag_and_release(55)  # releases at the value already stored
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
bumped = _migrate_default_threshold(w.cfg, 0.85)
check(
    "the dialog's own output config is untouched by a later migration",
    bumped["pdf_match_threshold"] == 0.55,
)


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
