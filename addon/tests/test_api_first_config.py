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

import klausmate.settings as _settings  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
_SCRATCH = tempfile.mkdtemp(prefix="klaus-t6-")
K = exec_klausmate_under_qt(_SCRATCH)
from anki_stubs import LiveStore  # noqa: E402


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
_settings.store = LiveStore(store, writes)
_settings.migrate()
check("cloud profile changes to local native model", (store.get("embedding_provider"), store.get("embedding_model"), store.get("embedding_dimensions")) == ("ollama", "nomic-embed-text", 0))
_TRANSCRIPTION_KEYS = ("transcription_model_path", "transcription_binary", "transcription_language")
check("credentials and obsolete fields removed", not any(key in store for key in credentials + ("_embed_key_setup_declined", "assistant_model", "ocr_model", "transcription_model") + _TRANSCRIPTION_KEYS))
check("K-314: the retired lecture-recording keys are in _LEGACY_KEYS_DROPPED", set(_TRANSCRIPTION_KEYS) <= set(_settings.LEGACY_KEYS_DROPPED))
check("appearance and library choices survive", all(store[k] == v for k, v in (("library_root", "/fixture/library"), ("color_theme", "rose"))))
store["embedding_model"] = "custom-local"
store["endpoint"] = "http://localhost:12345"
_settings.migrate()
check("later migration preserves local choices and writes nothing", len(writes) == 1 and store["embedding_model"] == "custom-local" and store["endpoint"] == "http://localhost:12345")


# patch_config's merge + profile fence live in settings.patch now: tests/test_settings.py.


section("PDF reader 3/5: the retired pdf_renderer key is scrubbed")
# Whichever owner exists: settings (after the seam) or __init__ (before it).
try:
    import klausmate.settings as _st12
except ImportError:
    _st12 = None
_profile12 = {"pdf_renderer": "native", "color_theme": "rose",
              "_local_embeddings_migrated": True}
if _st12 is not None:
    _legacy12 = _st12.LEGACY_KEYS_DROPPED
    _store12 = _st12.store
    _st12.store = _st12.DictStore(_profile12)
    try:
        _st12.migrate()
        _after12 = _st12.store.read()
    finally:
        _st12.store = _store12
else:
    _legacy12 = K._LEGACY_KEYS_DROPPED
    _after12 = dict(_profile12)
    _io12 = K.get_config, K.write_config
    K.get_config = lambda: dict(_after12)
    K.write_config = lambda c: (_after12.clear(), _after12.update(c))
    try:
        K._migrate_config()
    finally:
        K.get_config, K.write_config = _io12
check("pdf_renderer is in the retired-keys list", "pdf_renderer" in _legacy12)
check("a stored pdf_renderer: 'native' is removed; other choices stay",
      "pdf_renderer" not in _after12 and _after12.get("color_theme") == "rose",
      str(_after12))

raise SystemExit(report())
