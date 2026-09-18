"""Embedding provider for Klaus semantic search.

Turns note/PDF text into unit vectors via OpenAI's embeddings API. Two
ways to reach it: a Klaus Plus subscription (KLAUS_PLUS_KEY) — the same
metered, Stripe-billed proxy klausmate's plus.py talks to, so one
subscription unlocks AI features in both apps — or your own OpenAI key
(KLAUS_OPENAI_KEY) direct. A Plus key, when present, takes priority.

aqt-free and stdlib-only: neither key is ever required for the module to
import cleanly, and the HTTP call goes through urllib only. ``_urlopen``
is a module-level alias — the same seam klausmate's openai_client.py used
— that tests monkeypatch in place of hitting the network. Vectors are
unit-normalized at creation time so downstream similarity is a plain dot
product.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from array import array
from typing import Any, Callable, Iterator

from . import __version__

DEFAULT_MODEL = "text-embedding-3-large"
# klausmate/plus.py's DEFAULT_BASE and key() contract, verbatim: keys.mint()
# on the service is token_hex(16), so a well-formed key is always this shape.
DEFAULT_PLUS_BASE = "https://klausmate.com"
_PLUS_KEY_RE = re.compile(r"^kp_[0-9a-f]{32}$")

# OpenAI's v3 embedding models are trained with Matryoshka Representation
# Learning: the most significant components sit at the FRONT of the vector,
# so asking for fewer dimensions truncates the tail and degrades gracefully
# rather than catastrophically. Only these two models accept the `dimensions`
# parameter — _dimensions_for() gates on the model, not just the provider,
# so a future non-Matryoshka model can't silently get sent a value it will
# reject.
DIMENSION_CAPABLE_MODELS = ("text-embedding-3-small", "text-embedding-3-large")
DEFAULT_DIMENSIONS = 1024

BATCH_SIZE = 64

API_BASE = "https://api.openai.com/v1"
EMBED_TIMEOUT_S = 60.0

GetConfig = Callable[[], dict]

_urlopen = urllib.request.urlopen
_sleep = time.sleep


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
            env_var = "KLAUS_PLUS_KEY" if self.provider == "Klaus Plus" else "KLAUS_OPENAI_KEY"
            return f"{name} rejected the embedding API key — check {env_var}."
        if self.status == 402:
            return "Klaus Plus quota reached for this month — set KLAUS_OPENAI_KEY to use your own key instead."
        if self.status == 426:
            return "This klaus-core is too old for Klaus Plus — update it."
        if self.status == 429:
            wait = f" in {int(self.retry_after)}s" if self.retry_after else " shortly"
            return f"{name} rate-limited the embedding request — try again{wait}."
        if self.status is not None and self.status >= 500:
            return f"{name} is overloaded right now — try again in a minute."
        return str(self)


def default_config() -> dict:
    """The config `OpenAIEmbeddings` reads when no `get_config` is injected.

    Both keys come from env vars — unset is valid for either (the module
    still imports fine); it only becomes an error once `.embed()` is
    actually called and finds neither.
    """
    return {
        "api_key_openai": os.environ.get("KLAUS_OPENAI_KEY", ""),
        "plus_key": os.environ.get("KLAUS_PLUS_KEY", ""),
        "plus_base": os.environ.get("KLAUS_PLUS_BASE", "") or DEFAULT_PLUS_BASE,
        "embedding_model": DEFAULT_MODEL,
        "embedding_dimensions": DEFAULT_DIMENSIONS,
    }


def plus_key(cfg: dict) -> str:
    """A well-formed Klaus Plus key from `cfg`, or "" (klausmate/plus.py's
    key() contract, verbatim: 'kp_' + 32 lowercase hex — keys.mint() on the
    service is token_hex(16)). Anything else can only ever earn a 401, so
    it reads as no key at all rather than a doomed request."""
    k = str(cfg.get("plus_key") or "").strip()
    return k if _PLUS_KEY_RE.match(k) else ""


def plus_base(cfg: dict) -> str:
    return (str(cfg.get("plus_base") or "").strip() or DEFAULT_PLUS_BASE).rstrip("/")


def embedding_model(cfg: dict) -> str:
    model = str(cfg.get("embedding_model") or "").strip()
    return model or DEFAULT_MODEL


def embedding_dimensions(cfg: dict) -> int:
    """Requested output dimensions, or 0 for the model's own default."""
    try:
        value = int(cfg.get("embedding_dimensions") or 0)
    except (TypeError, ValueError):
        return DEFAULT_DIMENSIONS
    return value if value > 0 else 0


def _dimensions_for(cfg: dict) -> int:
    """The `dimensions` value to send, or 0 to omit the parameter entirely."""
    if embedding_model(cfg) not in DIMENSION_CAPABLE_MODELS:
        return 0
    return embedding_dimensions(cfg)


def index_signature(cfg: dict) -> tuple[str, str, int]:
    """(provider, model, dims) — a change in ANY of the three invalidates the
    card index."""
    return "openai", embedding_model(cfg), _dimensions_for(cfg)


def signature_matches(provider: str, model: str, dims: int, signature: tuple) -> bool:
    """True when a PERSISTED (provider, model, dims) satisfies `signature`.

    dims is compared only when the signature asks for a specific width; 0
    means "the model's own default" and cannot disagree with a stored width.
    """
    if (provider, model) != (signature[0], signature[1]):
        return False
    want = int(signature[2]) if len(signature) > 2 else 0
    return not want or int(dims or 0) == want


# --------------------------------------------------------------- HTTP call


def _post_json(url: str, body: dict, headers: dict, timeout: float, what: str,
                provider: str = "OpenAI") -> dict:
    """POST `body` as JSON, one retry on 429/5xx or a network blip."""
    data = json.dumps(body).encode("utf-8")
    last: EmbeddingError | None = None
    for attempt in (0, 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with _urlopen(req, timeout=timeout) as resp:
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
                raw = e.read().decode("utf-8", errors="replace")
            except Exception:
                raw = ""
            service_message = ""
            try:
                parsed = json.loads(raw) if raw else {}
                service_message = str((parsed.get("error") or {}).get("message") or "")
            except (ValueError, AttributeError):
                service_message = ""
            message = service_message or f"{provider} {what} failed (HTTP {e.code}): {raw[:300] or e.reason}"
            last = EmbeddingError(message, provider=provider, status=e.code, retry_after=retry_after)
            if attempt == 0 and (e.code == 429 or e.code >= 500):
                _sleep(min(retry_after or 2.0, 10.0))
                continue
            raise last from e
        except urllib.error.URLError as e:
            last = EmbeddingError(f"Could not reach {provider} {what}: {e.reason}", provider=provider)
            if attempt == 0:
                _sleep(2.0)
                continue
            raise last from e
        except json.JSONDecodeError as e:
            raise EmbeddingError(f"Invalid JSON from {provider} {what}", provider=provider) from e
    raise last  # type: ignore[misc]


def _embeddings_body(model: str, texts: list[str], dims: int) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "input": list(texts)}
    if dims:
        body["dimensions"] = int(dims)
    return body


def _parse_embeddings_response(resp: dict, texts: list[str], provider: str) -> list[list[float]]:
    data = resp.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise EmbeddingError(
            f"{provider} returned {len(data) if isinstance(data, list) else 'no'} embeddings "
            f"for {len(texts)} inputs",
            provider=provider,
        )
    out: list[list[float] | None] = [None] * len(texts)
    for item in data:
        i, vec = item.get("index"), item.get("embedding")
        if not isinstance(i, int) or not (0 <= i < len(texts)) or not isinstance(vec, list):
            raise EmbeddingError(f"Malformed embedding item from {provider}", provider=provider)
        out[i] = vec
    if any(v is None for v in out):
        raise EmbeddingError(f"{provider} response is missing embedding indices", provider=provider)
    return out  # type: ignore[return-value]


def _embed_http(key: str, texts: list[str], model: str, dims: int,
                 timeout: float = EMBED_TIMEOUT_S) -> list[list[float]]:
    """Direct to OpenAI with the caller's own key."""
    body = _embeddings_body(model, texts, dims)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    resp = _post_json(API_BASE + "/embeddings", body, headers, timeout, "embeddings", provider="OpenAI")
    return _parse_embeddings_response(resp, texts, "OpenAI")


def _embed_via_plus(key: str, base: str, texts: list[str], model: str, dims: int,
                     timeout: float = EMBED_TIMEOUT_S) -> list[list[float]]:
    """Through klausmate's Klaus Plus proxy — same request/response shape as
    OpenAI's own API (klausplus/proxy.py's /v1/embeddings is a passthrough),
    plus the three headers that route, authorize and version-gate the call."""
    body = _embeddings_body(model, texts, dims)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "X-Klaus-Purpose": "embed",
        "X-Klaus-Client": __version__,
    }
    resp = _post_json(base + "/v1/embeddings", body, headers, timeout, "embeddings", provider="Klaus Plus")
    return _parse_embeddings_response(resp, texts, "Klaus Plus")


# --------------------------------------------------------------- providers


class OpenAIEmbeddings:
    name = "openai"

    def __init__(self, get_config: GetConfig = default_config) -> None:
        self._get_config = get_config

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        cfg = self._get_config() or {}
        model, dims = embedding_model(cfg), _dimensions_for(cfg)

        pkey = plus_key(cfg)
        if pkey:
            return _embed_via_plus(pkey, plus_base(cfg), texts, model, dims)

        key = str(cfg.get("api_key_openai") or "").strip()
        if not key:
            raise EmbeddingError(
                "No embedding key is set — set KLAUS_PLUS_KEY for a Klaus Plus "
                "subscription, or KLAUS_OPENAI_KEY for your own OpenAI key.",
                provider="OpenAI",
                status=401,
            )
        return _embed_http(key, texts, model, dims)


def provider_from_config(get_config: GetConfig = default_config) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(get_config)


# ------------------------------------------------------------ batch helper


try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (this repo runs 3.9)
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

    A generator so the caller owns progress reporting and partial flushes.
    Stops cleanly between batches when ``cancel`` is set.
    """
    for start in range(0, len(texts), batch_size):
        if cancel is not None and cancel.is_set():
            return
        batch = texts[start : start + batch_size]
        raw = provider.embed(batch, kind=kind)
        yield start, [normalize(v) for v in raw]
