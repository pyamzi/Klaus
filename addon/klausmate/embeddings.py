"""Embedding providers for Klaus semantic search.

Turns card text / prompts / PDF chunks into unit vectors via one of:

- ``ollama``  — local ``/api/embed`` (default; private, free)
- ``openai``  — ``POST {OPENAI_API_BASE}/embeddings`` with a user API key
- ``voyage``  — ``POST {VOYAGE_API_BASE}/embeddings`` with a user API key

(Anthropic has no embeddings API, so Claude users pick one of the above.)

aqt-free and stdlib-only: config is injected as a callable so the module is
drivable headlessly against mock HTTP servers, and works within AnkiWeb's
no-compiled-wheels constraint. Vectors are unit-normalized at creation time
so downstream similarity is a plain dot product (see card_index.top_k).
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from array import array
from typing import Any, Callable, Iterator

# Module globals (not constants) so tests can point them at mock servers.
OPENAI_API_BASE = "https://api.openai.com/v1"
VOYAGE_API_BASE = "https://api.voyageai.com/v1"

DEFAULT_MODELS = {
    "ollama": "nomic-embed-text",
    "openai": "text-embedding-3-small",
    "voyage": "voyage-3-lite",
}

DEFAULT_PROVIDER = "voyage"

BATCH_SIZE = 64
CLOUD_TIMEOUT_S = 60.0
# Local embed calls can block on a cold model load, same as generation.
OLLAMA_TIMEOUT_S = 180.0

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
        if self.status in (401, 403):
            return (
                f"{name} rejected the embedding API key — check it in "
                "Tools → Klaus → Manage models."
            )
        if self.status == 429:
            wait = f" in {int(self.retry_after)}s" if self.retry_after else " shortly"
            return f"{name} rate-limited the embedding request — try again{wait}."
        if self.status is not None and self.status >= 500:
            return f"{name} is overloaded right now — try again in a minute."
        return str(self)


def provider_name(cfg: dict) -> str:
    p = str(cfg.get("embedding_provider") or DEFAULT_PROVIDER).strip().lower()
    return p if p in DEFAULT_MODELS else DEFAULT_PROVIDER


def embedding_model(cfg: dict) -> str:
    model = str(cfg.get("embedding_model") or "").strip()
    return model or DEFAULT_MODELS[provider_name(cfg)]


def index_signature(cfg: dict) -> tuple[str, str]:
    """(provider, model) — a change in either invalidates the card index."""
    return provider_name(cfg), embedding_model(cfg)


# --------------------------------------------------------------- providers


def _post_json(
    url: str,
    payload: dict,
    headers: dict[str, str],
    provider: str,
    timeout: float = CLOUD_TIMEOUT_S,
) -> dict:
    """POST JSON with one retry on 429/5xx; errors become EmbeddingError."""
    last: EmbeddingError | None = None
    for attempt in (0, 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            retry_after: float | None = None
            try:
                ra = e.headers.get("retry-after") if e.headers else None
                if ra:
                    retry_after = float(ra)
            except (TypeError, ValueError):
                pass
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                body = ""
            last = EmbeddingError(
                f"{provider} embeddings failed (HTTP {e.code}): {body or e.reason}",
                provider=provider,
                status=e.code,
                retry_after=retry_after,
            )
            if attempt == 0 and (e.code == 429 or e.code >= 500):
                time.sleep(min(retry_after or 2.0, 10.0))
                continue
            raise last from e
        except urllib.error.URLError as e:
            last = EmbeddingError(
                f"Could not reach {provider} embeddings API: {e.reason}",
                provider=provider,
            )
            # Transient network blips are expensive mid-index; one retry,
            # same as claude_api.
            if attempt == 0:
                time.sleep(2.0)
                continue
            raise last from e
        except json.JSONDecodeError as e:
            raise EmbeddingError(
                f"Invalid JSON from {provider} embeddings API",
                provider=provider,
            ) from e
    raise last  # unreachable, satisfies the type checker


def _vectors_by_index(data: Any, count: int, provider: str) -> list[list[float]]:
    """Restore input order from an OpenAI-shaped ``data[*].index`` response."""
    if not isinstance(data, list) or len(data) != count:
        got = len(data) if isinstance(data, list) else "none"
        raise EmbeddingError(
            f"{provider} returned {got} embeddings for {count} inputs",
            provider=provider,
        )
    out: list[list[float] | None] = [None] * count
    for item in data:
        i = item.get("index")
        vec = item.get("embedding")
        if not isinstance(i, int) or not (0 <= i < count) or not isinstance(vec, list):
            raise EmbeddingError(
                f"Malformed embedding item from {provider}", provider=provider
            )
        out[i] = vec
    if any(v is None for v in out):
        raise EmbeddingError(
            f"{provider} response is missing embedding indices", provider=provider
        )
    return out  # type: ignore[return-value]


class OllamaEmbeddings:
    name = "ollama"

    def __init__(self, get_config: GetConfig) -> None:
        self._get_config = get_config

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        from .ollama_client import OllamaClient, OllamaError, OllamaNotRunning

        cfg = self._get_config()
        # Endpoint read per call: the managed runtime may rewrite the port.
        endpoint = str(cfg.get("endpoint") or "http://localhost:11434")
        client = OllamaClient(endpoint, timeout=OLLAMA_TIMEOUT_S)
        model = embedding_model(cfg)
        try:
            return client.embed(model, texts)
        except OllamaNotRunning as e:
            raise EmbeddingError(str(e), provider="Ollama") from e
        except OllamaError as e:
            raise EmbeddingError(str(e), provider="Ollama") from e


class OpenAIEmbeddings:
    name = "openai"

    def __init__(self, get_config: GetConfig) -> None:
        self._get_config = get_config

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        cfg = self._get_config()
        key = str(cfg.get("embedding_api_key_openai") or "").strip()
        if not key:
            raise EmbeddingError(
                "OpenAI embedding API key is not set — add it in "
                "Tools → Klaus → Manage models.",
                provider="OpenAI",
                status=401,
            )
        resp = _post_json(
            f"{OPENAI_API_BASE}/embeddings",
            {"model": embedding_model(cfg), "input": texts},
            {"Authorization": f"Bearer {key}"},
            provider="OpenAI",
        )
        return _vectors_by_index(resp.get("data"), len(texts), "OpenAI")


class VoyageEmbeddings:
    name = "voyage"

    def __init__(self, get_config: GetConfig) -> None:
        self._get_config = get_config

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        cfg = self._get_config()
        key = str(cfg.get("embedding_api_key_voyage") or "").strip()
        if not key:
            raise EmbeddingError(
                "Voyage embedding API key is not set — add it in "
                "Tools → Klaus → Manage models.",
                provider="Voyage",
                status=401,
            )
        resp = _post_json(
            f"{VOYAGE_API_BASE}/embeddings",
            {
                "model": embedding_model(cfg),
                "input": texts,
                # Voyage embeds queries and documents asymmetrically.
                "input_type": "query" if kind == "query" else "document",
            },
            {"Authorization": f"Bearer {key}"},
            provider="Voyage",
        )
        return _vectors_by_index(resp.get("data"), len(texts), "Voyage")


_PROVIDER_CLASSES = {
    "ollama": OllamaEmbeddings,
    "openai": OpenAIEmbeddings,
    "voyage": VoyageEmbeddings,
}


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
    # Voyage rejects requests with more than 128 inputs (OpenAI allows 2048,
    # Ollama has no cap) — clamp so a future BATCH_SIZE bump can't break it.
    if getattr(provider, "name", "") == "voyage":
        batch_size = min(batch_size, 128)
    for start in range(0, len(texts), batch_size):
        if cancel is not None and cancel.is_set():
            return
        batch = texts[start : start + batch_size]
        raw = provider.embed(batch, kind=kind)
        yield start, [normalize(v) for v in raw]
