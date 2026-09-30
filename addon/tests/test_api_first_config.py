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


section("local defaults and one-time migration")
cfg = json.load(open(os.path.join(ROOT, "klausmate", "config.json"), encoding="utf-8"))
check("marker is never a default", "_local_embeddings_migrated" not in cfg)
for key, value in (("embedding_provider", "ollama"), ("embedding_model", "nomic-embed-text"),
                   ("embedding_dimensions", 0), ("runtime_auto_setup", True)):
    check(f"local default {key}", cfg.get(key) == value)
credentials = ("api_key_openai", "api_key_anthropic", "embedding_api_key_openai", "embedding_api_key_voyage", "klaus_plus_key")
check("no default credentials", not any(key in cfg for key in credentials))
store = dict(cfg, embedding_provider="openai", embedding_model="text-embedding-3-large",
             embedding_dimensions=1024, library_root="/fixture/library", color_theme="rose",
             transcription_binary="/custom cli", transcription_model_path="/saved model.bin",
             transcription_language="fa", transcription_model="old-cloud-model",
             _embed_key_setup_declined=True, assistant_model="old", ocr_model="old",
             **dict.fromkeys(credentials, "old-secret"))
writes = []
K.get_config = lambda: dict(store)
def save(value):
    store.clear()
    store.update(value)
    writes.append(dict(value))
K.write_config = save
K._migrate_config()
check("cloud profile changes to local native model", (store.get("embedding_provider"), store.get("embedding_model"), store.get("embedding_dimensions")) == ("ollama", "nomic-embed-text", 0))
_TRANSCRIPTION_KEYS = ("transcription_model_path", "transcription_binary", "transcription_language")
check("credentials and obsolete fields removed", not any(key in store for key in credentials + ("_embed_key_setup_declined", "assistant_model", "ocr_model", "transcription_model") + _TRANSCRIPTION_KEYS))
check("K-314: the retired lecture-recording keys are in _LEGACY_KEYS_DROPPED", set(_TRANSCRIPTION_KEYS) <= set(K._LEGACY_KEYS_DROPPED))
check("appearance and library choices survive", all(store[k] == v for k, v in (("library_root", "/fixture/library"), ("color_theme", "rose"))))
store["embedding_model"] = "custom-local"
store["endpoint"] = "http://localhost:12345"
K._migrate_config()
check("later migration preserves local choices and writes nothing", len(writes) == 1 and store["embedding_model"] == "custom-local" and store["endpoint"] == "http://localhost:12345")


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
    _fake_tm.queued.clear()
    K.mw.col = object()
    K.patch_config({"endpoint": "http://localhost:9999"})
    K.mw.col = object()
    _fake_tm.queued.pop()()
    check("queued patch cannot write to another profile", "endpoint" not in _fake_mgr._cfg)
finally:
    K.mw = _orig_mw
    K.get_config, K.write_config = _real_get_config, _real_write_config


raise SystemExit(report())
