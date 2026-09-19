"""Local Ollama embedding adapter and normalized vector batching."""
from __future__ import annotations

import math
import threading
from array import array
from typing import Callable, Iterator

DEFAULT_MODELS = {"ollama": "nomic-embed-text"}
DEFAULT_PROVIDER = "ollama"
DEFAULT_DIMENSIONS = 0
BATCH_SIZE = 64
GetConfig = Callable[[], dict]


class EmbeddingError(Exception):
    def __init__(self, message: str, *, provider: str = "", status: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retry_after = retry_after

    def user_message(self) -> str:
        return str(self)


def provider_name(cfg: dict) -> str:
    return "ollama"


def embedding_model(cfg: dict) -> str:
    return str(cfg.get("embedding_model") or "").strip() or DEFAULT_MODELS["ollama"]


def embedding_dimensions(cfg: dict) -> int:
    return 0


def index_signature(cfg: dict) -> tuple[str, str, int]:
    return "ollama", embedding_model(cfg), 0


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


class OllamaEmbeddings:
    name = "ollama"

    def __init__(self, get_config: GetConfig) -> None:
        self._get_config = get_config

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        from .ollama_client import OllamaClient, OllamaError
        cfg = self._get_config() or {}
        try:
            return OllamaClient(str(cfg.get("endpoint") or "http://127.0.0.1:11434")).embed(
                embedding_model(cfg), texts
            )
        except OllamaError as exc:
            raise EmbeddingError(
                f"{exc}. Check Ollama and the selected model in KlausMate Preferences → Local models.",
                provider="Ollama",
            ) from exc


def provider_from_config(get_config: GetConfig):
    return OllamaEmbeddings(get_config)


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
