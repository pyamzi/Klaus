"""HTTP client for the local Ollama server.

Uses only the Python stdlib (urllib) so the add-on has no bundled C-extensions
and installs cleanly from AnkiWeb.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable


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
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
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

    def generate(self, model: str, prompt: str, images: list[str], timeout: float | None = None) -> str:
        """One non-streaming completion with images (the OCR path).

        ``images`` are base64 strings, as Ollama's /api/generate takes them.
        A per-call timeout because OCR of a dense slide takes longer than the
        client's default; the caller passes page_ocr.OCR_TIMEOUT_S.
        """
        old = self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            resp = self._post("/api/generate", {"model": model, "prompt": prompt, "images": list(images), "stream": False})
        finally:
            self.timeout = old
        text = resp.get("response")
        if not isinstance(text, str):
            raise OllamaError("generate response had no text")
        return text

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
