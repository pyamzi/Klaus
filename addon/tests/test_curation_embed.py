"""curation._embed_plan reads the embedding provider from settings.

Regression (2026-10-01): the settings seam (d8a7025) removed curation's
``_cfg`` helper but left ``provider_from_config(_cfg)`` in ``_embed_plan``,
so every card-index phase with anything to embed died with a NameError,
``index_queue._fail`` dropped the whole queue, and no PDF was embedded
after that commit. The index_queue tests fake curation entirely, so only
a test of the real function can see it.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_curation_embed.py
"""
from __future__ import annotations

import importlib
import sys
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
settings = importlib.import_module("klaus_note.settings")
curation = importlib.import_module("klaus_note.curation")

cfg = {"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"}
settings.store = settings.DictStore(dict(cfg))

seen = []


class Stop(Exception):
    pass


real_provider = curation.embeddings.provider_from_config


def fake_provider(get_config):
    # The real signature: a GETTER, called per request (OllamaEmbeddings
    # calls it inside embed). Passing the dict itself fails on the first
    # batch with "'dict' object is not callable" (the first fix did that).
    seen.append(dict(get_config()))
    raise Stop  # the config is all this test needs; stop before embedding


curation.embeddings.provider_from_config = fake_provider
plan = types.SimpleNamespace(to_embed=[(1, 0, "h", "a card")])

section("_embed_plan builds its provider from the stored config")
try:
    curation._embed_plan(None, plan, None, None, None)
    outcome = "returned"
except Stop:
    outcome = "provider built"
except Exception as exc:  # noqa: BLE001
    outcome = repr(exc)
check("no NameError: the provider is built", outcome == "provider built", outcome)
check("…from a getter that returns settings.read()", len(seen) == 1
      and all(seen[0].get(k) == v for k, v in cfg.items()), str(seen))

section("the real provider gets a callable, as OllamaEmbeddings needs")
got = []
curation.embeddings.provider_from_config = lambda g: (got.append(g), (_ for _ in ()).throw(Stop()))[1]
try:
    curation._embed_plan(None, plan, None, None, None)
except Stop:
    pass
check("the argument is callable", len(got) == 1 and callable(got[0]), repr(got))
curation.embeddings.provider_from_config = real_provider

raise SystemExit(report())
