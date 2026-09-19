"""Embedding provider for Klaus semantic search.

Turns card text / prompts / PDF chunks into unit vectors via OpenAI's
embeddings API — the sole provider now (Ollama and Voyage are gone; the
actual HTTP lives in openai_client.py).

aqt-free and stdlib-only: config is injected as a callable so the module is
drivable headlessly against mock HTTP servers, and works within AnkiWeb's
no-compiled-wheels constraint. Vectors are unit-normalized at creation time
so downstream similarity is a plain dot product (see card_index.top_k).
"""

from __future__ import annotations

import math
import threading
from array import array
from typing import Callable, Iterator

DEFAULT_MODELS = {"openai": "text-embedding-3-large"}

DEFAULT_PROVIDER = "openai"

# OpenAI's v3 embedding models are trained with Matryoshka Representation
# Learning: the most significant components sit at the FRONT of the vector,
# so asking for fewer dimensions truncates the tail and degrades gracefully
# rather than catastrophically. text-embedding-3-large shortened to 256 still
# beats the old ada-002 at 1536.
#
# That is why the large model can be the fast one here. Ranking cost is
# linear in dimensions — card_index.top_k is a sumprod over packed rows — so
# -large at 1024 is BETTER than -small at 1536 on retrieval quality while
# being cheaper to rank and smaller on disk. Full 3072 is available by
# setting the key to 0 (meaning "whatever the model gives").
#
# Only these two models accept the parameter — _dimensions_for() gates on
# the model, not just the provider, so a future non-Matryoshka model can't
# silently get sent a dimensions value it will reject.
DIMENSION_CAPABLE_MODELS = ("text-embedding-3-small", "text-embedding-3-large")
DEFAULT_DIMENSIONS = 1024

BATCH_SIZE = 64

GetConfig = Callable[[], dict]


class EmbeddingError(Exception):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retry_after = retry_after

    def user_message(self) -> str:
        name = self.provider or "the embedding provider"
        if self.provider == "Klaus Plus":
            # The service's own wording (quota/version/maintenance
            # refusals) — verbatim, never re-canned as OpenAI copy below.
            return str(self)
        if self.status in (401, 403):
            return (
                f"{name} rejected the embedding API key — check it in "
                "KlausMate Preferences → API keys & models."
            )
        if self.status == 429:
            wait = f" in {int(self.retry_after)}s" if self.retry_after else " shortly"
            return f"{name} rate-limited the embedding request — try again{wait}."
        if self.status is not None and self.status >= 500:
            return f"{name} is overloaded right now — try again in a minute."
        return str(self)


def provider_name(cfg: dict) -> str:
    """OpenAI is now the only embedding provider; kept for existing callers."""
    return "openai"


def embedding_model(cfg: dict) -> str:
    model = str(cfg.get("embedding_model") or "").strip()
    return model or DEFAULT_MODELS[provider_name(cfg)]


def embedding_dimensions(cfg: dict) -> int:
    """Requested output dimensions, or 0 for the model's own default."""
    try:
        value = int(cfg.get("embedding_dimensions") or 0)
    except (TypeError, ValueError):
        return DEFAULT_DIMENSIONS
    return value if value > 0 else 0


def _dimensions_for(cfg: dict) -> int:
    """The `dimensions` value to send, or 0 to omit the parameter entirely.

    Gated on the model, not just the provider: only OpenAI's v3 embedding
    models accept it, and sending it anywhere else is a 400.
    """
    if embedding_model(cfg) not in DIMENSION_CAPABLE_MODELS:
        return 0
    return embedding_dimensions(cfg)


def index_signature(cfg: dict) -> tuple[str, str, int]:
    """(provider, model, dims) — a change in ANY of the three invalidates the
    card index.

    Dims belongs here: the same model at 3072 and at 1024 produces vectors
    that cannot be compared with each other, and without it in the signature
    that switch would be caught only later, by card_index's file-size check.
    """
    return provider_name(cfg), embedding_model(cfg), _dimensions_for(cfg)


def signature_matches(
    provider: str, model: str, dims: int, signature: tuple
) -> bool:
    """True when a PERSISTED (provider, model, dims) satisfies `signature`.

    One helper for every store that caches embeddings — the card index, the
    per-PDF index, the matches cache. Each of them used to spell this
    comparison itself as a two-tuple equality, which is precisely why adding
    a third element to the signature broke three call sites at once.

    dims is compared only when the signature asks for a specific width; 0
    means "the model's own default" and cannot disagree with a stored width.
    """
    if (provider, model) != (signature[0], signature[1]):
        return False
    want = int(signature[2]) if len(signature) > 2 else 0
    return not want or int(dims or 0) == want


# --------------------------------------------------------------- providers


class OpenAIEmbeddings:
    name = "openai"

    def __init__(self, get_config: GetConfig) -> None:
        self._get_config = get_config

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        cfg = self._get_config() or {}
        from . import openai_client

        key = str(cfg.get("api_key_openai") or "").strip()
        if not key:
            raise EmbeddingError(
                "OpenAI API key is not set — add it in KlausMate Preferences "
                "→ API keys & models.",
                provider="OpenAI",
                status=401,
            )
        try:
            return openai_client.embed(
                key, texts, embedding_model(cfg), _dimensions_for(cfg)
            )
        except openai_client.OpenAIError as e:
            raise EmbeddingError(
                str(e), provider="OpenAI", status=e.status, retry_after=e.retry_after
            ) from e


_PROVIDER_CLASSES = {"openai": OpenAIEmbeddings}


def provider_from_config(get_config: GetConfig):
    return _PROVIDER_CLASSES[provider_name(get_config())](get_config)


# ------------------------------------------------------------ batch helper


try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (Anki bundles 3.13)
    def _sumprod(a, b):  # type: ignore[misc]
        return sum(x * y for x, y in zip(a, b))


def normalize(vec: list[float]) -> array | None:
    """Unit-normalize into a float32 array; None for zero vectors."""
    norm = math.sqrt(_sumprod(vec, vec))
    if norm == 0.0 or not math.isfinite(norm):
        return None
    return array("f", (x / norm for x in vec))


def embed_batches(
    provider,
    texts: list[str],
    batch_size: int = BATCH_SIZE,
    cancel: threading.Event | None = None,
    kind: str = "document",
) -> Iterator[tuple[int, list[array | None]]]:
    """Yield ``(offset, vectors)`` per batch; a slot is None for zero vectors.

    A generator so the caller owns progress reporting and partial flushes
    (curation saves the index every ~1k vectors for cancel/crash resume).
    Stops cleanly between batches when ``cancel`` is set.
    """
    for start in range(0, len(texts), batch_size):
        if cancel is not None and cancel.is_set():
            return
        batch = texts[start : start + batch_size]
        raw = provider.embed(batch, kind=kind)
        yield start, [normalize(v) for v in raw]
