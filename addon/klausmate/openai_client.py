"""Klaus's OpenAI client: embeddings and audio transcription, stdlib only.

The official SDK depends on compiled wheels that cannot be vendored into
an AnkiWeb add-on, so this is stdlib urllib only, the house pattern for every
Klaus HTTP client: one retry on 429/5xx, one on a network blip, errors that
carry a user_message(). The key is passed in by the caller and never logged.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

API_BASE = "https://api.openai.com/v1"
EMBED_TIMEOUT_S = 60.0
TRANSCRIBE_TIMEOUT_S = 120.0
_urlopen = urllib.request.urlopen
_SLEEP = time.sleep


class OpenAIError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    def user_message(self) -> str:
        if self.status in (402, 426, 503):
            # The service's own wording (Klaus Plus quota/version/
            # maintenance refusals) — verbatim, not buried under a canned
            # line that was written for the provider's own errors.
            return str(self)
        if self.status in (401, 403):
            return "OpenAI rejected the API key — check it in KlausMate Preferences → API keys & models."
        if self.status == 429:
            wait = f" in {int(self.retry_after)}s" if self.retry_after else " shortly"
            return f"OpenAI rate-limited the request — try again{wait}."
        if self.status is not None and self.status >= 500:
            return "OpenAI is overloaded right now — try again in a minute."
        return str(self)


def _request(url: str, data: bytes, headers: dict[str, str], timeout: float, what: str,
             *, on_headers: Callable[[Any], None] | None = None) -> dict:
    last: OpenAIError | None = None
    for attempt in (0, 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with _urlopen(req, timeout=timeout) as resp:
                if on_headers is not None:
                    try:
                        on_headers(resp.headers)
                    except Exception as exc:
                        # The caller's callback is not this module's problem to
                        # fail a successful call over — a quota readout that
                        # can't refresh must never take the embedding/
                        # transcription result down with it.
                        print(f"[klausmate] on_headers raised {exc.__class__.__name__}")
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
            body = raw[:300]
            message = service_message or f"OpenAI {what} failed (HTTP {e.code}): {body or e.reason}"
            last = OpenAIError(message, status=e.code, retry_after=retry_after)
            if attempt == 0 and (e.code == 429 or e.code >= 500):
                _SLEEP(min(retry_after or 2.0, 10.0))
                continue
            raise last from e
        except urllib.error.URLError as e:
            last = OpenAIError(f"Could not reach OpenAI {what}: {e.reason}")
            if attempt == 0:
                _SLEEP(2.0)
                continue
            raise last from e
        except json.JSONDecodeError as e:
            raise OpenAIError(f"Invalid JSON from OpenAI {what}") from e
    raise last  # type: ignore[misc]


def embed(key: str, texts: list[str], model: str, dims: int, timeout: float = EMBED_TIMEOUT_S, *,
         on_headers: Callable[[Any], None] | None = None) -> list[list[float]]:
    if not texts:
        return []
    body: dict[str, Any] = {"model": model, "input": list(texts)}
    if dims:
        body["dimensions"] = int(dims)
    url = API_BASE + "/embeddings"
    headers = {"Content-Type": "application/json",
              "Authorization": f"Bearer {key}"}
    resp = _request(url, json.dumps(body).encode("utf-8"), headers, timeout, "embeddings", on_headers=on_headers)
    data = resp.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise OpenAIError(f"OpenAI returned {len(data) if isinstance(data, list) else 'no'} embeddings for {len(texts)} inputs")
    out: list[list[float] | None] = [None] * len(texts)
    for item in data:
        i, vec = item.get("index"), item.get("embedding")
        if not isinstance(i, int) or not (0 <= i < len(texts)) or not isinstance(vec, list):
            raise OpenAIError("Malformed embedding item from OpenAI")
        out[i] = vec
    if any(v is None for v in out):
        raise OpenAIError("OpenAI response is missing embedding indices")
    return out  # type: ignore[return-value]


def _multipart(fields: list[tuple[str, str]], file_field: str, filename: str, content_type: str, blob: bytes) -> tuple[bytes, str]:
    boundary = "klaus" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode("utf-8"))
    parts.append(blob)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(key: str, wav_bytes: bytes, model: str, language: str = "en", prompt: str = "",
               timeout: float = TRANSCRIBE_TIMEOUT_S, *,
               on_headers: Callable[[Any], None] | None = None) -> str:
    fields = [("model", model), ("response_format", "json"), ("language", language)]
    if prompt:
        fields.append(("prompt", prompt[:800]))
    data, ct = _multipart(fields, "file", "chunk.wav", "audio/wav", wav_bytes)
    url = API_BASE + "/audio/transcriptions"
    headers = {"Content-Type": ct, "Authorization": f"Bearer {key}"}
    resp = _request(url, data, headers, timeout, "transcription", on_headers=on_headers)
    return str(resp.get("text") or "").strip()
