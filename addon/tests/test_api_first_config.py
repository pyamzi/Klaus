"""API-first (2026-09-15, K-226): the local runtime and OCR are gone, and
config migrates onto the two API keys.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_api_first_config.py

Why its own file: tests/test_klausmate.py is another card's during this
plan, so the Task 6 pins that would naturally live beside its config
section live here instead. The bootstrap is the same exec-of-__init__
pattern — _migrate_config is a module-level function of klausmate/
__init__.py and cannot be reached by importing a submodule.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import types

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import (  # noqa: E402
    check,
    exec_klausmate_under_qt,
    install,
    report,
    section,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

install()
from PyQt6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
_SCRATCH = tempfile.mkdtemp(prefix="klaus-t6-")
K = exec_klausmate_under_qt(_SCRATCH)
# The real get_config/write_config, captured before the _migrate_config
# section below monkeypatches K.get_config/K.write_config to fixture
# lambdas for the rest of the file's run.
_real_get_config, _real_write_config = K.get_config, K.write_config


# ------------------------------------------------- deletions

section("2026-09-15: the local runtime, OCR and their config are gone")

for name in ("ollama_client", "ollama_runtime", "ollama_setup", "page_ocr"):
    check(
        f"klausmate/{name}.py is deleted",
        not os.path.exists(os.path.join(ROOT, "klausmate", f"{name}.py")),
    )

_src = open(os.path.join(ROOT, "klausmate", "__init__.py"), encoding="utf-8").read()
check(
    "__init__ imports none of them",
    not re.search(r"ollama_(client|runtime|setup)|page_ocr", _src),
)


# ------------------------------------------------- config.json

section("config.json is the API-first key set")

cfg = json.load(open(os.path.join(ROOT, "klausmate", "config.json"), encoding="utf-8"))

for k in (
    "embedding_provider",
    "embedding_api_key_openai",
    "embedding_api_key_voyage",
    "ocr_enabled",
    "ocr_model",
    "runtime_auto_setup",
    "claude_binary",
    "endpoint",
    "pdf_index_max_chunks",
    "pdf_match_agg",
    "assistant_model",
):
    check(f"config.json no longer defines {k}", k not in cfg)

for k, v in (
    ("api_key_openai", ""),
    ("api_key_anthropic", ""),
    ("transcription_model", "gpt-4o-mini-transcribe"),
    ("embedding_model", "text-embedding-3-large"),
):
    check(f"config.json defines {k} = {v!r}", cfg.get(k) == v)

check(
    "embedding_dimensions survives at 1024 — the width is still part of "
    "the index signature, so dropping it would silently re-embed",
    cfg.get("embedding_dimensions") == 1024,
)


# ------------------------------------------------- _migrate_config

section("_migrate_config: one rename, and what an Ollama-era profile loses")

# Model Anki's merge of defaults under profile overrides.
def _profile(**user_keys) -> dict:
    merged = dict(cfg)
    merged.update(user_keys)
    return merged


_store = _profile(
    embedding_api_key_openai="sk-old",
    assistant_model="claude-x",
    embedding_provider="ollama",
    embedding_model="nomic-embed-text",
    ocr_model="glm-ocr",
    _embed_default_migrated=True,
    _embed_key_setup_declined=True,
)
_written: dict = {}
K.get_config = lambda: dict(_store)
K.write_config = lambda c: _written.update(c)
K._migrate_config()

check(
    "the API key is renamed — its destination default IS \"\", so this "
    "one really does migrate a value the user would otherwise re-enter",
    _written.get("api_key_openai") == "sk-old"
    and "embedding_api_key_openai" not in _written,
)
check(
    "retired model aliases are removed without replacement",
    "reasoning_model" not in _written
    and "assistant_model" not in _written,
)
check(
    "a dead provider takes its model with it — the pre-plan dialog wrote "
    "the resolved Ollama model into embedding_model, and carrying "
    '"nomic-embed-text" into an OpenAI-only world prices as a KeyError '
    'and embeds as an HTTP 404. "" resolves to the OpenAI default',
    _written.get("embedding_model") == "",
)
check(
    "the declined-key flag goes with them: it was a 'no thanks' to an "
    "OPTIONAL key (a local engine existed then) and would otherwise "
    "silence the only profile-open message saying Klaus now REQUIRES "
    "one — the API-first regime gets exactly one fresh nudge",
    "_embed_key_setup_declined" not in _written,
)
check(
    "...and the rest of the Ollama era is scrubbed, nothing invented",
    not any(
        k in _written
        for k in ("embedding_provider", "ocr_model", "_embed_default_migrated")
    ),
)

# Retired dock keys are removed from existing profiles in one write.
_retired = ("assistant_reopen", "assistant_dock_width", "assistant_dock_open", "reasoning_model")
_migration_store = _profile(**dict.fromkeys(_retired, "old-value"))
_migration_store["library_root"] = "/fixture/library"
_migration_store["_embed_key_setup_declined"] = True
_migration_writes = []
K.get_config = lambda: dict(_migration_store)
def _save_migration(value):
    _migration_store.clear()
    _migration_store.update(value)
    _migration_writes.append(dict(value))
K.write_config = _save_migration
K._migrate_config()
check("all retired dock keys are absent from defaults and migrated profiles",
      all(k not in cfg and k not in _migration_store for k in _retired))
check("migration preserves unrelated configuration",
      _migration_store == dict(cfg, library_root="/fixture/library",
                               _embed_key_setup_declined=True))
check("retired keys cause exactly one migration write", len(_migration_writes) == 1)
K._migrate_config()
check("a second migration performs no write", len(_migration_writes) == 1)

# An OpenAI-era profile keeps the model it actually chose.
_storeO = _profile(embedding_provider="openai", embedding_model="text-embedding-3-small")
_writtenO: dict = {}
K.get_config = lambda: dict(_storeO)
K.write_config = lambda c: _writtenO.update(c)
K._migrate_config()
check(
    "an OpenAI-era profile's embedding model SURVIVES — only a dead "
    "provider's model is cleared, never a valid choice the user made",
    _writtenO.get("embedding_model") == "text-embedding-3-small",
)

# A profile that carried no retired key at all is not touched: a decline
# recorded AFTER the migration is honoured forever.
_storeD = _profile(api_key_openai="", _embed_key_setup_declined=True)
_wroteD = []
K.get_config = lambda: dict(_storeD)
K.write_config = lambda c: _wroteD.append(c)
K._migrate_config()
check(
    "a decline made in the API-first regime is NOT re-cleared — the "
    "fresh nudge is one-time, tied to the retired keys actually present, "
    "not a prompt that returns every launch",
    _wroteD == [],
)

# Retiring Klaus Plus storage does not make an API-first embedding key newly
# required, so it must not re-open a prompt the user already declined.
_storeP = _profile(
    klaus_plus_key="kp-retired",
    klaus_plus_cache={"old": "value"},
    klaus_plus_base="https://retired.example",
    klaus_plus_email="former@example.invalid",
    _embed_key_setup_declined=True,
)
_writtenP: dict = {}
K.get_config = lambda: dict(_storeP)
K.write_config = lambda c: _writtenP.update(c)
K._migrate_config()
check(
    "Plus-only migration drops all retired keys but preserves an API-first setup decline",
    bool(_writtenP)
    and all(
        k not in _writtenP
        for k in ("klaus_plus_key", "klaus_plus_cache", "klaus_plus_base", "klaus_plus_email")
    )
    and _writtenP.get("_embed_key_setup_declined") is True,
)

# A profile that already holds the new names must not have them clobbered
# by a stale old one: the rename only fills an EMPTY destination.
_store2 = _profile(embedding_api_key_openai="sk-old", api_key_openai="sk-new")
_written2: dict = {}
K.get_config = lambda: dict(_store2)
K.write_config = lambda c: _written2.update(c)
K._migrate_config()
check(
    "a rename never overwrites a destination the user has already set",
    _written2.get("api_key_openai") == "sk-new"
    and "embedding_api_key_openai" not in _written2,
)

# Idempotence: a profile already migrated writes nothing at all.
_store3 = _profile(api_key_openai="sk")
_wrote_any = []
K.get_config = lambda: dict(_store3)
K.write_config = lambda c: _wrote_any.append(c)
K._migrate_config()
check("an already-migrated profile is a no-op (no write)", _wrote_any == [])

check(
    "the retired keys are all named in _LEGACY_KEYS_DROPPED, so an old "
    "profile's meta.json loses them on the next open",
    set(
        (
            "embedding_provider",
            "embedding_api_key_voyage",
            "ocr_enabled",
            "ocr_model",
            "runtime_auto_setup",
            "claude_binary",
            "endpoint",
            "pdf_index_max_chunks",
            "pdf_match_agg",
            "_embed_default_migrated",
            "embedding_api_key_openai",
            "assistant_model",
        )
    )
    <= set(K._LEGACY_KEYS_DROPPED),
)


# ------------------------------------------------- patch_config (K-247 fix 1)

section("patch_config: a merging, main-thread config writer")

# write_config REPLACES the whole stored blob (mw.addonManager.writeConfig
# semantics) -- that is the point of the fake below, mirroring production
# instead of a dict.update() double that would hide the exact bug this
# guards against. get_config/write_config are restored to the real
# functions first: the _migrate_config section above left them pointing
# at fixture lambdas that never touch mw at all.
K.get_config, K.write_config = _real_get_config, _real_write_config


class _FakeAddonManager:
    """mirrors mw.addonManager: writeConfig REPLACES, like production."""

    def __init__(self, cfg):
        self._cfg = dict(cfg)

    def getConfig(self, _name):
        return dict(self._cfg)

    def writeConfig(self, _name, cfg):
        self._cfg = dict(cfg)


class _FakeTaskman:
    """Records what would run on the main thread instead of running it,
    so the test can see whether patch_config queued or applied inline."""

    def __init__(self):
        self.queued = []

    def run_on_main(self, fn):
        self.queued.append(fn)


_orig_mw = K.mw
_fake_mgr = _FakeAddonManager(
    {"api_key_openai": "sk-real", "library_root": "/library",
     "embedding_model": "text-embedding-3-large", "image_crop_enabled": False}
)
_fake_tm = _FakeTaskman()
K.mw = types.SimpleNamespace(addonManager=_fake_mgr, taskman=_fake_tm)
try:
    K.patch_config({"image_crop_enabled": True})
    check(
        "patch_config queues the write through mw.taskman.run_on_main "
        "rather than applying it inline while taskman is there to ask",
        len(_fake_tm.queued) == 1
        and _fake_mgr._cfg.get("image_crop_enabled") is False,
    )
    _fake_tm.queued[0]()
    _after = K.get_config()
    check(
        "...and once that queued closure runs, every OTHER stored "
        "setting survives untouched — write_config REPLACES the whole "
        "blob, so patch_config must merge into a fresh read before "
        "calling it, or a patch wipes the API key and library_root",
        _after.get("api_key_openai") == "sk-real"
        and _after.get("library_root") == "/library"
        and _after.get("embedding_model") == "text-embedding-3-large",
    )
    check("...with the patched key itself applied",
          _after.get("image_crop_enabled") is True)
finally:
    K.mw = _orig_mw
    K.get_config, K.write_config = _real_get_config, _real_write_config


raise SystemExit(report())
