"""One streaming LLM interface, two backends behind it.

Reshaped from the ``claude_api.py`` deleted in K-032 (`30847b9^`); the SSE
handling below is that module's, which had already been through a tool-loop
and is not worth rediscovering.

stdlib urllib only, as before: the official SDKs depend on compiled wheels
(pydantic-core) that cannot be vendored cross-platform into an AnkiWeb
add-on, so this speaks the wire format directly — the same reason
``ollama_client.py`` and ``embeddings.py`` do.

**Two backends, one wire format.**

* ``DirectBackend`` — the user's own key, straight to the provider. What a
  free member gets, and what works offline-ish and without an account.
* ``HostedBackend`` — a token to Klaus's own service, which holds the
  provider keys. What a premium member gets.

The hosted service passes the provider's SSE through UNCHANGED rather than
inventing a protocol of its own, so a single parser serves both and a
provider-side change is absorbed in one place instead of two. That is also
why the Anthropic message shape is the interface here: the hosted side is
free to translate to another vendor internally, but the addon should not
grow a second payload dialect to find out.

**Enforcement is not here.** This module routes; it does not decide who is
entitled to what. A local flag cannot gate a paid feature in an add-on
that ships as readable Python — the gate is the service refusing a token.
See ``entitlement.py``.

aqt-free and side-effect-free: testable against a local mock server by
monkeypatching ``API_BASE`` / ``HOSTED_API_BASE``.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

# Module globals so tests can point them at a local http.server, matching
# embeddings.OPENAI_API_BASE / VOYAGE_API_BASE.
API_BASE = "https://api.anthropic.com"
HOSTED_API_BASE = "https://api.klausmate.app"
API_VERSION = "2023-06-01"

_RETRYABLE_STATUSES = {429, 500, 502, 503, 529}
_MAX_RETRY_AFTER_S = 30.0
DEFAULT_TIMEOUT_S = 300.0


class LLMError(Exception):
    """API failure with a message already phrased for the user."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        error_type: str = "",
        retry_after: float | None = None,
        hosted: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.retry_after = retry_after
        self.hosted = hosted

    def user_message(self) -> str:
        """What to actually show. The service and the provider fail in
        different ways and the user can only act on one of them."""
        detail = str(self)
        if self.status in (401, 403):
            if self.hosted:
                return (
                    "Your KlausMate subscription could not be verified — "
                    "check it under KlausMate Preferences."
                )
            return (
                "That API key was rejected — check it under KlausMate "
                f"Preferences. ({detail})"
            )
        if self.status == 404:
            return f"Model not found — check the model setting. ({detail})"
        if self.status == 429:
            wait = (
                f" Try again in {int(self.retry_after)}s."
                if self.retry_after
                else ""
            )
            who = "KlausMate" if self.hosted else "the provider"
            return f"Rate limited by {who}.{wait}"
        if self.status is not None and self.status >= 500:
            return "The service is overloaded right now — try again shortly."
        if self.status is None and self.error_type == "network":
            return f"Could not reach the service: {detail}"
        return f"Assistant error: {detail}"


def _parse_error_body(raw: bytes) -> tuple[str, str]:
    """(error_type, message) from an error response body."""
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        err = data.get("error") or {}
        if isinstance(err, str):
            return "", err
        return str(err.get("type") or ""), str(err.get("message") or raw[:200])
    except (json.JSONDecodeError, AttributeError, TypeError):
        return "", raw.decode("utf-8", "replace")[:200]


def _open_stream(url: str, data: bytes, headers: dict, timeout: float, hosted: bool):
    """POST and return the open response, retrying once BEFORE any bytes
    stream.

    Retrying only pre-stream is deliberate: once deltas have reached the
    caller, a retry would replay text the user has already seen.
    """
    last_error: LLMError | None = None
    for attempt in range(2):
        req = urllib.request.Request(
            url, data=data, headers=headers, method="POST"
        )
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            error_type, message = _parse_error_body(e.read())
            retry_after = None
            try:
                retry_after = float(e.headers.get("retry-after") or 0) or None
            except (TypeError, ValueError, AttributeError):
                pass
            last_error = LLMError(
                message,
                status=e.code,
                error_type=error_type,
                retry_after=retry_after,
                hosted=hosted,
            )
            if attempt == 0 and e.code in _RETRYABLE_STATUSES:
                time.sleep(min(retry_after or 2.0, _MAX_RETRY_AFTER_S))
                continue
            raise last_error from e
        except urllib.error.URLError as e:
            last_error = LLMError(
                str(e.reason), error_type="network", hosted=hosted
            )
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise last_error from e
    raise last_error or LLMError("request failed", error_type="network", hosted=hosted)


def consume_sse(
    resp,
    on_text: Callable[[str], None] | None = None,
    on_block_start: Callable[[dict], None] | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """Drain one SSE stream into finalized content blocks.

    Returns ``{"content": [blocks], "stop_reason": str|None}``. Blocks are
    finalized so they can be echoed VERBATIM in the assistant turn of a tool
    loop: text {type,text}, tool_use {type,id,name,input}, thinking
    {type,thinking,signature}. The thinking ``signature`` must be preserved
    or the API refuses the echo — that is not decoration.

    Setting ``cancel`` closes the stream and returns what accumulated, with
    stop_reason "cancelled".
    """
    blocks: dict[int, dict[str, Any]] = {}
    partial_json: dict[int, list[str]] = {}
    stop_reason: str | None = None
    cancelled = False
    try:
        for raw_line in resp:
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue  # event:/ping framing; the type lives in the JSON
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "content_block_start":
                idx = int(event.get("index") or 0)
                block = dict(event.get("content_block") or {})
                blocks[idx] = block
                partial_json[idx] = []
                if on_block_start is not None:
                    on_block_start(block)
            elif etype == "content_block_delta":
                idx = int(event.get("index") or 0)
                delta = event.get("delta") or {}
                dtype = delta.get("type")
                block = blocks.setdefault(idx, {"type": "text", "text": ""})
                if dtype == "text_delta":
                    text = str(delta.get("text") or "")
                    block["text"] = block.get("text", "") + text
                    if text and on_text is not None:
                        on_text(text)
                elif dtype == "input_json_delta":
                    partial_json.setdefault(idx, []).append(
                        str(delta.get("partial_json") or "")
                    )
                elif dtype == "thinking_delta":
                    block["thinking"] = block.get("thinking", "") + str(
                        delta.get("thinking") or ""
                    )
                elif dtype == "signature_delta":
                    block["signature"] = str(delta.get("signature") or "")
            elif etype == "content_block_stop":
                idx = int(event.get("index") or 0)
                block = blocks.get(idx)
                if block is not None and block.get("type") == "tool_use":
                    raw = "".join(partial_json.get(idx) or [])
                    try:
                        block["input"] = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError:
                        block["input"] = {}
            elif etype == "message_delta":
                sr = (event.get("delta") or {}).get("stop_reason")
                if sr:
                    stop_reason = str(sr)
            elif etype == "message_stop":
                break
            elif etype == "error":
                err = event.get("error") or {}
                raise LLMError(
                    str(err.get("message") or "stream error"),
                    error_type=str(err.get("type") or ""),
                )
    finally:
        try:
            resp.close()
        except Exception:
            pass
    # A stream cut short — cancelled, or the connection dropped — never
    # delivers content_block_stop, which is where tool_use input is
    # finalized. Without this, such a block reaches the tool loop with no
    # `input` key at all and the echo is malformed. Found by a test that
    # dropped the stop event by accident.
    #
    # Keyed by the SSE index, NOT by position in the finalized list: the two
    # only coincide when block indices happen to run contiguously from zero.
    for idx in sorted(blocks):
        block = blocks[idx]
        if block.get("type") == "tool_use" and not isinstance(
            block.get("input"), dict
        ):
            raw = "".join(partial_json.get(idx) or [])
            try:
                block["input"] = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                block["input"] = {}
    return {
        "content": [blocks[i] for i in sorted(blocks)],
        "stop_reason": "cancelled" if cancelled else stop_reason,
    }


def text_of(result: dict) -> str:
    """The plain text of a result, ignoring tool_use and thinking blocks."""
    return "".join(
        str(b.get("text") or "")
        for b in (result.get("content") or [])
        if b.get("type") == "text"
    )


class DirectBackend:
    """The user's own key, straight to the provider. The free path."""

    name = "direct"
    hosted = False

    def __init__(self, get_config: Callable[[], dict]) -> None:
        self._get_config = get_config

    def stream(self, payload: dict, **kw) -> dict:
        key = str(
            (self._get_config() or {}).get("assistant_api_key") or ""
        ).strip()
        if not key:
            raise LLMError(
                "No API key set — add one under KlausMate Preferences, or "
                "sign in to use the hosted assistant.",
                status=401,
            )
        body = dict(payload)
        body["stream"] = True
        resp = _open_stream(
            f"{API_BASE}/v1/messages",
            json.dumps(body).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": API_VERSION,
            },
            float(kw.pop("timeout", DEFAULT_TIMEOUT_S)),
            hosted=False,
        )
        return consume_sse(resp, **kw)


class HostedBackend:
    """A token to Klaus's service, which holds the provider keys.

    Deliberately never reads an API key from config. A premium member has no
    provider key to leak, and the service is what enforces the subscription —
    which is the only place it CAN be enforced, since the add-on ships as
    readable Python.
    """

    name = "hosted"
    hosted = True

    def __init__(self, get_config: Callable[[], dict]) -> None:
        self._get_config = get_config

    def stream(self, payload: dict, **kw) -> dict:
        token = str(
            (self._get_config() or {}).get("assistant_token") or ""
        ).strip()
        if not token:
            raise LLMError(
                "Not signed in — sign in under KlausMate Preferences to use "
                "the hosted assistant.",
                status=401,
                hosted=True,
            )
        body = dict(payload)
        body["stream"] = True
        resp = _open_stream(
            f"{HOSTED_API_BASE}/v1/messages",
            json.dumps(body).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            float(kw.pop("timeout", DEFAULT_TIMEOUT_S)),
            hosted=True,
        )
        return consume_sse(resp, **kw)


_BACKENDS = {"direct": DirectBackend, "hosted": HostedBackend}


def backend_name(cfg: dict) -> str:
    """Which backend the config asks for. Hosted only when a token exists —
    an empty token would otherwise fail every call with a 401 on a machine
    that has a perfectly good key sitting next to it."""
    cfg = cfg or {}
    want = str(cfg.get("assistant_backend") or "").strip().lower()
    if want == "hosted" and str(cfg.get("assistant_token") or "").strip():
        return "hosted"
    if want in _BACKENDS and want != "hosted":
        return want
    return "direct"


def backend_from_config(get_config: Callable[[], dict]):
    """The backend for the current config, chosen fresh each call so a
    sign-in takes effect without a restart."""
    return _BACKENDS[backend_name(get_config() or {})](get_config)
