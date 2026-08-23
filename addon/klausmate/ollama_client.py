"""HTTP client for the local Ollama server.

Uses only the Python stdlib (urllib) so the add-on has no bundled C-extensions
and installs cleanly from AnkiWeb.
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable

_THINKING_BLOCK_RE = re.compile(
    r"<(?:redacted_)?think(?:ing)?>\s*.*?\s*</(?:redacted_)?think(?:ing)?>",
    re.DOTALL | re.IGNORECASE,
)
_QWEN_CONTROL_TOKEN_RE = re.compile(
    r"/(?:no_think|no_check|think)\b/?",
    re.IGNORECASE,
)


def _extract_model_text(text: str, thinking: str = "") -> str:
    """Strip thinking traces from Ollama message/response text."""
    if thinking and thinking in text:
        text = text.replace(thinking, "")
    text = _THINKING_BLOCK_RE.sub("", text)
    text = _QWEN_CONTROL_TOKEN_RE.sub("", text)
    return text.strip()


def _extract_generate_response(resp: dict[str, Any]) -> str:
    return _extract_model_text(
        str(resp.get("response") or ""),
        str(resp.get("thinking") or ""),
    )


def _extract_chat_message(msg: dict[str, Any]) -> str:
    return _extract_model_text(
        str(msg.get("content") or ""),
        str(msg.get("thinking") or ""),
    )

# #region agent log
# Writable from Anki regardless of repo path (USER_FILES lives in the add-on).
import os as _os

_DEBUG_LOG = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "user_files", "debug-16d0b4.log"
)


def _dbg(
    location: str,
    message: str,
    data: dict[str, Any],
    hypothesis_id: str,
) -> None:
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "16d0b4",
                        "timestamp": int(time.time() * 1000),
                        "location": location,
                        "message": message,
                        "data": data,
                        "hypothesisId": hypothesis_id,
                    }
                )
                + "\n"
            )
    except Exception:
        pass


# #endregion


class OllamaError(Exception):
    pass


class OllamaNotRunning(OllamaError):
    pass


def _url_error_message(endpoint: str, exc: urllib.error.URLError) -> str:
    """Map urllib failures to a clearer message (timeout vs refused)."""
    reason = exc.reason
    if isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout):
        return f"Timed out waiting for Ollama at {endpoint}"
    if isinstance(reason, ConnectionRefusedError):
        return f"Connection refused — is Ollama running at {endpoint}?"
    return f"Could not reach Ollama at {endpoint}: {exc}"


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "error" in data:
                    return str(data["error"])
            except json.JSONDecodeError:
                pass
            return raw[:300]
    except Exception:
        pass
    return exc.reason or f"HTTP {exc.code}"


class OllamaClient:
    def __init__(self, endpoint: str, timeout: float = 30.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    # ---------- low-level ----------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.endpoint}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # #region agent log
        t0 = time.monotonic()
        model_name = payload.get("model", "")
        num_predict = (payload.get("options") or {}).get("num_predict")
        _dbg(
            "ollama_client._post:start",
            "HTTP POST begin",
            {
                "path": path,
                "timeout_s": self.timeout,
                "model": model_name,
                "num_predict": num_predict,
                "prompt_chars": len(payload.get("prompt") or ""),
            },
            "A",
        )
        # #endregion
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise OllamaError(
                f"Ollama request failed ({e.code}): {_http_error_detail(e)}"
            ) from e
        except urllib.error.URLError as e:
            # #region agent log
            elapsed = round(time.monotonic() - t0, 2)
            reason = repr(getattr(e, "reason", e))
            is_timeout = isinstance(
                getattr(e, "reason", None), (TimeoutError, socket.timeout)
            )
            _dbg(
                "ollama_client._post:urlerror",
                "HTTP POST failed",
                {
                    "path": path,
                    "elapsed_s": elapsed,
                    "timeout_s": self.timeout,
                    "is_timeout": is_timeout,
                    "reason": reason[:200],
                    "model": model_name,
                },
                "A" if is_timeout else "D",
            )
            # #endregion
            raise OllamaNotRunning(_url_error_message(self.endpoint, e)) from e
        # #region agent log
        _dbg(
            "ollama_client._post:ok",
            "HTTP POST ok",
            {
                "path": path,
                "elapsed_s": round(time.monotonic() - t0, 2),
                "model": model_name,
            },
            "B",
        )
        # #endregion
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise OllamaError(f"Invalid JSON from Ollama: {body[:200]}") from e

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.endpoint}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise OllamaError(
                f"Ollama request failed ({e.code}): {_http_error_detail(e)}"
            ) from e
        except urllib.error.URLError as e:
            raise OllamaNotRunning(_url_error_message(self.endpoint, e)) from e
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise OllamaError(f"Invalid JSON from Ollama: {body[:200]}") from e

    # ---------- public ----------

    def health(self) -> bool:
        try:
            self._get("/api/tags")
            return True
        except OllamaError:
            return False

    def list_models(self) -> list[str]:
        data = self._get("/api/tags")
        return [m["name"] for m in data.get("models", [])]

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 40,
        temperature: float = 0.2,
        top_p: float | None = None,
        top_k: int | None = None,
        repeat_penalty: float | None = None,
        stop: list[str] | None = None,
    ) -> str:
        options: dict[str, Any] = {
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        if top_p is not None:
            options["top_p"] = top_p
        if top_k is not None:
            options["top_k"] = top_k
        if repeat_penalty is not None:
            options["repeat_penalty"] = repeat_penalty
        if stop:
            options["stop"] = stop
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if system:
            payload["system"] = system
        # Qwen3 thinking models may leak reasoning into `response` unless disabled.
        if "qwen3" in model.lower():
            payload["think"] = False
        resp = self._post("/api/generate", payload)
        return _extract_generate_response(resp)

    def chat(
        self,
        model: str,
        user_content: str,
        system: str | None = None,
        max_tokens: int = 40,
        temperature: float = 0.2,
        top_p: float | None = None,
        top_k: int | None = None,
        repeat_penalty: float | None = None,
        stop: list[str] | None = None,
    ) -> str:
        """Chat completion — preferred for Ask/autofill (better on Qwen3)."""
        options: dict[str, Any] = {
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        if top_p is not None:
            options["top_p"] = top_p
        if top_k is not None:
            options["top_k"] = top_k
        if repeat_penalty is not None:
            options["repeat_penalty"] = repeat_penalty
        if stop:
            options["stop"] = stop
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if "qwen3" in model.lower():
            payload["think"] = False
        resp = self._post("/api/chat", payload)
        return _extract_chat_message(resp.get("message") or {})

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via /api/embed.

        Returns one vector per input text, in input order. Ollama truncates
        over-long inputs server-side (``truncate: true``) instead of erroring.
        """
        if not texts:
            return []
        resp = self._post(
            "/api/embed",
            {"model": model, "input": texts, "truncate": True},
        )
        embeddings = resp.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            got = len(embeddings) if isinstance(embeddings, list) else "none"
            raise OllamaError(
                f"Embedding response mismatch: sent {len(texts)} texts, "
                f"got {got} vectors"
            )
        return embeddings

    # ---- model management ----

    def pull(
        self,
        model: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Pull a model, streaming progress events to ``on_event``.

        Each event is a dict like::

            {"status": "pulling manifest"}
            {"status": "downloading", "digest": "...", "total": 123, "completed": 45}
            {"status": "verifying sha256 digest"}
            {"status": "success"}

        Raises ``OllamaNotRunning`` if the server is unreachable and
        ``OllamaError`` if the server reports an error during the pull.
        """
        url = f"{self.endpoint}/api/pull"
        body = json.dumps({"name": model, "stream": True}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            # Pulls can take a long time — drop the read timeout for this call.
            resp = urllib.request.urlopen(req, timeout=None)
        except urllib.error.HTTPError as e:
            raise OllamaError(
                f"Pull failed ({e.code}): {_http_error_detail(e)}"
            ) from e
        except urllib.error.URLError as e:
            raise OllamaNotRunning(_url_error_message(self.endpoint, e)) from e
        try:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in ev:
                    raise OllamaError(str(ev["error"]))
                if on_event is not None:
                    on_event(ev)
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def delete(self, model: str) -> None:
        """Delete an installed model. Raises ``OllamaError`` on failure."""
        url = f"{self.endpoint}/api/delete"
        body = json.dumps({"name": model}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            raise OllamaError(
                f"Delete failed ({e.code}): {_http_error_detail(e)}"
            ) from e
        except urllib.error.URLError as e:
            raise OllamaNotRunning(_url_error_message(self.endpoint, e)) from e
