"""Minimal Anthropic Messages API client (powers the Claude ⌘K brain).

stdlib urllib only — the official `anthropic` SDK depends on compiled
wheels (pydantic-core) that can't be vendored cross-platform into an
AnkiWeb add-on, so this speaks the wire format directly, mirroring the
approach of ollama_client.py.

aqt-free and side-effect-free: fully testable against a local mock server
by monkeypatching API_BASE.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

API_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"

_RETRYABLE_STATUSES = {429, 500, 529}
_MAX_RETRY_AFTER_S = 30.0


class ClaudeAPIError(Exception):
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
        detail = str(self)
        if self.status == 401:
            return (
                "Your Anthropic API key was rejected — check it in "
                "Tools → Klaus → Manage models…"
            )
        if self.status == 403:
            return (
                "Your Anthropic API key doesn't have permission for this "
                f"request (billing or access issue): {detail}"
            )
        if self.status == 404:
            return (
                "Model not found — check the Claude model in "
                f"Tools → Klaus → Manage models… ({detail})"
            )
        if self.status == 429:
            wait = f" Try again in {int(self.retry_after)}s." if self.retry_after else ""
            return f"Rate limited by the Anthropic API.{wait}"
        if self.status is not None and (self.status >= 500 or self.status == 529):
            return "Anthropic's API is overloaded right now — try again shortly."
        if self.status is None and self.error_type == "network":
            return f"Could not reach the Anthropic API: {detail}"
        return f"Anthropic API error: {detail}"


def _parse_error_body(raw: bytes) -> tuple[str, str]:
    """(error_type, message) from an error response body."""
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        err = data.get("error") or {}
        return str(err.get("type") or ""), str(err.get("message") or raw[:200])
    except (json.JSONDecodeError, AttributeError):
        return "", raw.decode("utf-8", "replace")[:200]


def stream_message(
    api_key: str,
    payload: dict[str, Any],
    on_text: Callable[[str], None] | None = None,
    on_block_start: Callable[[dict], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """One streamed /v1/messages call. Blocking; call from a worker thread.

    Returns ``{"content": [finalized blocks], "stop_reason": str|None}``.
    ``on_text`` fires per text delta; ``on_block_start`` per content block
    (so callers can surface tool-use/thinking status). Setting ``cancel``
    closes the stream and returns what accumulated with stop_reason
    ``"cancelled"``. Retries once (before any bytes stream) on 429/5xx.

    Content blocks are finalized so they can be echoed verbatim in the
    assistant turn of a tool loop: text {type,text}, tool_use
    {type,id,name,input}, thinking {type,thinking,signature} — the
    signature MUST be preserved for the API to accept the echo.
    """
    body = dict(payload)
    body["stream"] = True
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
    }

    resp = None
    last_error: ClaudeAPIError | None = None
    for attempt in range(2):
        req = urllib.request.Request(
            f"{API_BASE}/v1/messages", data=data, headers=headers, method="POST"
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            break
        except urllib.error.HTTPError as e:
            error_type, message = _parse_error_body(e.read())
            retry_after = None
            try:
                retry_after = float(e.headers.get("retry-after") or 0) or None
            except (TypeError, ValueError):
                pass
            last_error = ClaudeAPIError(
                message, status=e.code, error_type=error_type, retry_after=retry_after
            )
            if attempt == 0 and e.code in _RETRYABLE_STATUSES:
                time.sleep(min(retry_after or 2.0, _MAX_RETRY_AFTER_S))
                continue
            raise last_error from e
        except urllib.error.URLError as e:
            last_error = ClaudeAPIError(str(e.reason), error_type="network")
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise last_error from e
    if resp is None:  # both attempts failed with a retryable status
        raise last_error or ClaudeAPIError("request failed", error_type="network")

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
                continue  # event:/ping framing lines; type field is in the JSON
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
                raise ClaudeAPIError(
                    str(err.get("message") or "stream error"),
                    error_type=str(err.get("type") or ""),
                )
            # message_start / ping → ignore
    finally:
        try:
            resp.close()
        except Exception:
            pass

    content = [blocks[i] for i in sorted(blocks)]
    return {
        "content": content,
        "stop_reason": "cancelled" if cancelled else stop_reason,
    }
