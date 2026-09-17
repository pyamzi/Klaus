"""Klaus's Anthropic Messages client — one streaming transport.

Revived 2026-09-15 from the ``llm_client.py`` deleted in the 2026-09-02
convergence (`a494f2d`), which was itself reshaped from the ``claude_api.py``
of `30847b9^`. The SSE handling below has been through a real tool loop
twice and is not worth rediscovering a third time.

What did NOT come back: the second backend, its token, the flag that chose
between them, and the copy about signing in to a Klaus-run service. There
is one path now — the user's own key, straight to the provider — and one
place to look when a call fails. Klaus stores no key of its own.

stdlib urllib only, as before: the official SDKs depend on compiled wheels
(pydantic-core) that cannot be vendored cross-platform into an AnkiWeb
add-on, so this speaks the wire format directly — the same reason
``embeddings.py`` does.

aqt-free and side-effect-free: no Qt, no collection, no profile, so a
caller may drive it from a worker thread. Tests point ``_urlopen`` at a
fake; ``API_BASE`` remains repointable at a local server.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from . import plus

# Module globals so tests can point them at a local http.server or a
# fake — the same pattern openai_client.py uses for its own tests.
API_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"

# The one place a request actually leaves the process. Tests replace it;
# nothing else in the module may call urlopen directly, or half the suite
# would need a network.
_urlopen = urllib.request.urlopen

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
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.retry_after = retry_after

    def user_message(self) -> str:
        """What to actually show."""
        detail = str(self)
        # A key that was never set and a key the provider refused are both
        # 401s, and only one of them is a "rejection" — telling a user with
        # no key that theirs was rejected sends them to check a field that
        # is empty.
        if self.error_type == "no_key":
            return detail
        if self.status in (402, 426, 503):
            # The service's own wording (Klaus Plus quota/version/
            # maintenance refusals) — verbatim, not buried under a canned
            # line written for the provider's own errors.
            return detail
        if self.status in (401, 403):
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
            return f"Rate limited by the provider.{wait}"
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


def _open_stream(url: str, data: bytes, headers: dict, timeout: float):
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
            return _urlopen(req, timeout=timeout)
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
            )
            if attempt == 0 and e.code in _RETRYABLE_STATUSES:
                time.sleep(min(retry_after or 2.0, _MAX_RETRY_AFTER_S))
                continue
            raise last_error from e
        except urllib.error.URLError as e:
            last_error = LLMError(str(e.reason), error_type="network")
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise last_error from e
    raise last_error or LLMError("request failed", error_type="network")


def _finalise_tool_input(block: dict, parts: list) -> None:
    """Parse a tool_use block's buffered partial_json into ``input``.

    Unparseable input degrades to ``{}`` rather than raising: a malformed
    argument is the model's problem to be told about, not a reason to lose
    the rest of a turn the user is watching.

    An empty ``parts`` list means no input_json_delta ever arrived for this
    block — leave whatever ``input`` it already carries untouched rather
    than joining "" and overwriting a pre-filled value with {}.
    """
    if not parts:
        return
    raw = "".join(parts or [])
    try:
        block["input"] = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        block["input"] = {}


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
    finalised: set[int] = set()
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
                    _finalise_tool_input(block, partial_json.get(idx) or [])
                    finalised.add(idx)
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
    # finalized. Without this, such a block reaches the tool loop carrying
    # the EMPTY PLACEHOLDER the API puts in content_block_start
    # (`"input":{}`) while the arguments sit unparsed in partial_json, and
    # the echo is a tool call with no arguments. Found by a test that
    # dropped the stop event by accident; the placeholder is why the test
    # for it has to be a recorded stream and not a hand-built one.
    #
    # Keyed by the SSE index, NOT by position in the finalized list: the two
    # only coincide when block indices happen to run contiguously from zero.
    for idx in sorted(blocks):
        block = blocks[idx]
        if block.get("type") == "tool_use" and idx not in finalised:
            _finalise_tool_input(block, partial_json.get(idx) or [])
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


class Client:
    """The user's own key, straight to the provider."""

    def __init__(self, get_config: Callable[[], dict]) -> None:
        self._get_config = get_config

    def _key(self) -> str:
        """Read fresh every call, so a key pasted into Preferences works
        without a restart."""
        key = str(
            (self._get_config() or {}).get("api_key_anthropic") or ""
        ).strip()
        if not key:
            raise LLMError(
                "No Anthropic API key set — add it under KlausMate "
                "Preferences → API keys & models.",
                status=401,
                error_type="no_key",
            )
        return key

    def _headers(self, key: str) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": API_VERSION,
        }

    def _target(self, purpose: str) -> tuple[str, dict]:
        """(url, headers) for one request: Klaus Plus when it is active,
        the user's own key straight to the provider otherwise.

        ``_key()``'s ``no_key`` error only fires off Plus — a Plus
        subscriber has no reason to ever see "add your Anthropic key".
        """
        cfg = self._get_config() or {}
        if plus.active(cfg):
            ep = plus.endpoint(cfg, purpose)
            return ep.base + "/v1/messages", {**ep.headers, "Content-Type": "application/json"}
        return API_BASE + "/v1/messages", self._headers(self._key())

    def stream(self, payload: dict, purpose: str = "assistant", *,
               on_headers: Callable[[Any], None] | None = None, **kw) -> dict:
        """One streaming request, drained into finalized content blocks."""
        url, headers = self._target(purpose)
        body = dict(payload)
        body["stream"] = True
        resp = _open_stream(
            url,
            json.dumps(body).encode("utf-8"),
            headers,
            float(kw.pop("timeout", DEFAULT_TIMEOUT_S)),
        )
        if on_headers is not None:
            try:
                on_headers(resp.headers)
            except Exception as exc:
                # Same rule as openai_client._request: a quota readout that
                # can't refresh must never take the assistant turn down with it.
                print(f"[klausmate] on_headers raised {exc.__class__.__name__}")
        return consume_sse(resp, **kw)

    def complete(self, payload: dict, timeout: float = DEFAULT_TIMEOUT_S, purpose: str = "assistant", *,
                 on_headers: Callable[[Any], None] | None = None) -> dict:
        """One non-streaming request; the parsed response body."""
        url, headers = self._target(purpose)
        body = dict(payload)
        body.pop("stream", None)
        req_data = json.dumps(body).encode("utf-8")
        resp = _open_stream(url, req_data, headers, float(timeout))
        if on_headers is not None:
            try:
                on_headers(resp.headers)
            except Exception as exc:
                print(f"[klausmate] on_headers raised {exc.__class__.__name__}")
        try:
            raw = resp.read().decode("utf-8")
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMError(
                "Invalid JSON from the Messages API", error_type="protocol"
            ) from e
