"""The stored config and the user-files path, owned in one aqt-free place
(spec docs/superpowers/specs/2026-09-30-settings-seam-design.md).

Interface: ``read()`` (a fresh dict of the stored config), ``patch(updates,
remove=…)`` (the ONE writer: merge, drop keys), ``user_files()``, and the
migration list (``register_migration`` at import, ``migrate()`` once on
profile open). There is no whole-blob writer for callers: replacing the
blob was the wipe hazard every partial-dict write used to carry.

Seam: ``store`` — an object with ``read() -> dict`` and ``write(cfg)``.
The bootstrap installs ``AnkiStore`` (Anki's addon manager); tests assign
a ``DictStore``. Two more module-attribute hooks follow ``tasks``'s style:
``run_on_main`` (a background thread's patch hops through it; on the main
thread the patch applies inline, so a compare-and-set caller never sees a
queued gap) and ``current_profile`` (a patch that hops is dropped if the
profile changed before it landed). ``user_files_dir`` derives from this
file's location — in the test harness's mirror that is the scratch
directory the harness creates.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterable

PACKAGE = __package__ or "klausmate"


class DictStore:
    """A store over a dict; hands out copies so a caller's edits never
    leak into the stored config."""

    def __init__(self, cfg: dict | None = None) -> None:
        self._cfg = json.loads(json.dumps(cfg or {}))

    def read(self) -> dict:
        return json.loads(json.dumps(self._cfg))

    def write(self, cfg: dict) -> None:
        self._cfg = json.loads(json.dumps(cfg))


class AnkiStore:
    """Anki's addon manager: ``meta.json``'s config, defaults from
    config.json when absent."""

    def __init__(self, addon_manager, package: str = PACKAGE) -> None:
        self._am = addon_manager
        self._package = package

    def read(self) -> dict:
        return self._am.getConfig(self._package) or {}

    def write(self, cfg: dict) -> None:
        self._am.writeConfig(self._package, cfg)


store = DictStore({})
run_on_main: Callable[[Callable[[], None]], None] | None = None
current_profile: Callable[[], object] | None = None
user_files_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_files")


def read() -> dict:
    return store.read() or {}


def user_files() -> str:
    return user_files_dir


def _profile():
    return current_profile() if current_profile is not None else None


def patch(updates: dict, *, remove: Iterable[str] = ()) -> None:
    """Merge ``updates`` into the stored config and drop ``remove``.
    Inline on the main thread; through ``run_on_main`` from any other,
    skipped if the profile changed before the hop ran."""
    updates = dict(updates)
    remove = tuple(remove)
    token = _profile()

    def apply() -> None:
        if _profile() is not token:
            return
        cfg = read()
        cfg.update(updates)
        for key in remove:
            cfg.pop(key, None)
        store.write(cfg)

    if run_on_main is None or threading.current_thread() is threading.main_thread():
        apply()
    else:
        run_on_main(apply)


# ── migrations ───────────────────────────────────────────────────────────

LEGACY_KEYS_DROPPED = (
    "chat_system_prompt", "chat_use_pdf_context", "chat_max_tokens",
    "chat_engine", "chat_claude_api_key", "chat_claude_model", "chat_turn_timeout_s",
    "model", "autocomplete_model", "ask_model", "generate_timeout_s",
    "temperature", "top_p", "top_k", "repeat_penalty", "completion_mode",
    "ask_hotkey", "cycle_forward_hotkey", "cycle_backward_hotkey",
    "debounce_ms", "min_chars_before_trigger", "paste_cooldown_ms",
    "dismissal_cooldown_ms", "accept_cooldown_ms", "retrieval_method",
    "retrieval_top_k", "system_prompt", "ask_system_prompt",
    "autocomplete_enabled", "ask_enabled", "chat_hotkey", "klaus_engine",
    "claude_api_key", "claude_model", "claude_timeout_s",
    "autofill_system_prompt",
    "curate_top_k", "curate_min_score",
    "single_window_mode",
    "workspace_enabled",
    "assistant_api_key", "assistant_backend", "assistant_token",
    "embedding_api_key_voyage", "embedding_api_key_openai",
    "api_key_openai", "api_key_anthropic", "_embed_key_setup_declined",
    "ocr_enabled", "ocr_model", "claude_binary",
    "pdf_index_max_chunks", "pdf_match_agg", "assistant_model",
    "_embed_default_migrated",
    "klaus_plus_key", "klaus_plus_cache", "klaus_plus_base", "klaus_plus_email",
    "assistant_reopen", "assistant_dock_width", "assistant_dock_open",
    "reasoning_model", "transcription_model",
    "transcription_model_path", "transcription_binary", "transcription_language",
    "pdf_renderer",  # K-321 Task 12 (2026-10-01): every reader runs on pdf.js
)


def _scrub_legacy(cfg: dict) -> dict:
    """Keys owned by removed features (chat, autocomplete, Ask, Plus, the
    August single window, recording) go; the local-embeddings default is
    applied once. Idempotent: on a clean profile it returns its input."""
    if not any(k in cfg for k in LEGACY_KEYS_DROPPED) and cfg.get("_local_embeddings_migrated"):
        return cfg
    cfg = dict(cfg)
    if not cfg.get("_local_embeddings_migrated"):
        cfg.update(embedding_provider="ollama", embedding_model="nomic-embed-text",
                   embedding_dimensions=0, _local_embeddings_migrated=True)
    for old in LEGACY_KEYS_DROPPED:
        cfg.pop(old, None)
    return cfg


DEFAULT_MIGRATIONS: tuple = (_scrub_legacy,)
_migrations: list = list(DEFAULT_MIGRATIONS)


def register_migration(fn: Callable[[dict], dict]) -> None:
    """A pure ``dict -> dict``; return the input unchanged to mean "nothing
    to do". Modules register theirs at import, so the registering module
    must be imported by ``__init__`` at bootstrap (a lazily imported one
    registers nothing by the time the profile-open run happens); the
    bootstrap runs the list once per profile open."""
    if fn not in _migrations:
        _migrations.append(fn)


def migrate() -> bool:
    """Run every registered migration in order, write back once if any
    changed the config. Returns whether it wrote."""
    before = read()
    cfg = before
    for fn in list(_migrations):
        try:
            cfg = fn(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] settings migration {getattr(fn, '__name__', fn)} failed: {exc}")
    if cfg == before:
        return False
    store.write(cfg)
    return True
