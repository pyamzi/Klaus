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
    ("reasoning_model", "claude-sonnet-5"),
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

section("_migrate_config renames the two surviving keys and scrubs the rest")

_store = {
    "embedding_api_key_openai": "sk-old",
    "assistant_model": "claude-x",
    "embedding_provider": "voyage",
    "ocr_model": "glm-ocr",
    "_embed_default_migrated": True,
}
_written: dict = {}
K.get_config = lambda: dict(_store)
K.write_config = lambda c: _written.update(c)
K._migrate_config()

check(
    "api key and model renamed, old keys gone, nothing else invented",
    _written.get("api_key_openai") == "sk-old"
    and _written.get("reasoning_model") == "claude-x"
    and not any(
        k in _written
        for k in (
            "embedding_api_key_openai",
            "assistant_model",
            "embedding_provider",
            "ocr_model",
        )
    ),
)

check(
    "the one-time ollama->voyage default pin is gone with the provider it "
    "pinned to — _embed_default_migrated is scrubbed, never re-written",
    "_embed_default_migrated" not in _written,
)

# A profile that already holds the new names must not have them clobbered
# by a stale old one: the rename only fills an EMPTY destination.
_store2 = {"embedding_api_key_openai": "sk-old", "api_key_openai": "sk-new"}
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
_store3 = {"api_key_openai": "sk", "reasoning_model": "claude-sonnet-5"}
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


raise SystemExit(report())
