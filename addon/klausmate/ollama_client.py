"""HTTP client for the local Ollama server.

Uses only the Python stdlib (urllib) so the add-on has no bundled C-extensions
and installs cleanly from AnkiWeb.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Callable


class OllamaError(Exception):
    pass


class OllamaNotRunning(OllamaError):
    pass


def local_endpoint(endpoint: str) -> str:
    """Validate and normalize the loopback HTTP URL before any request."""
    match = re.fullmatch(r"http://(localhost|127\.0\.0\.1|\[::1\])(?::([0-9]+))?/?", endpoint.strip(), re.IGNORECASE)
    if match is None:
        raise OllamaError("Use a local HTTP Ollama endpoint, such as http://127.0.0.1:11434.")
    port = int(match.group(2) or 11434)
    if not 1 <= port <= 65535:
        raise OllamaError("Ollama endpoint port must be between 1 and 65535.")
    return f"http://{match.group(1).lower()}:{port}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _url_error_message(endpoint: str, exc: urllib.error.URLError) -> str:
    """Map urllib failures to a clearer message (timeout vs refused)."""
    reason = exc.reason
    if isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout):
        return f"Timed out waiting for Ollama at {endpoint}"
    if isinstance(reason, ConnectionRefusedError):
        return f"Connection refused. Is Ollama running at {endpoint}?"
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
        self.endpoint = local_endpoint(endpoint)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
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
            with self._opener.open(req, timeout=self.timeout) as resp:
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
            with self._opener.open(url, timeout=self.timeout) as resp:
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

    def model_capabilities(self, model: str) -> list[str]:
        """Read capabilities reported by Ollama, without guessing from names."""
        data = self._post("/api/show", {"model": model})
        capabilities = data.get("capabilities", [])
        return [value for value in capabilities if isinstance(value, str)] if isinstance(capabilities, list) else []

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

    def generate(self, model: str, prompt: str, images: list[str]) -> str:
        """One non-streaming completion over base64 images (the OCR path)."""
        resp = self._post(
            "/api/generate",
            {"model": model, "prompt": prompt, "images": list(images), "stream": False},
        )
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
            # Pulls can take a long time; drop the read timeout for this call.
            resp = self._opener.open(req, timeout=None)
        except urllib.error.HTTPError as e:
            raise OllamaError(
                f"Pull failed ({e.code}): {_http_error_detail(e)}"
            ) from e
        except urllib.error.URLError as e:
            raise OllamaNotRunning(_url_error_message(self.endpoint, e)) from e
        try:
            succeeded = False
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError as e:
                    raise OllamaError("Invalid progress JSON from Ollama.") from e
                if not isinstance(ev, dict):
                    raise OllamaError("Invalid progress event from Ollama.")
                if "error" in ev:
                    raise OllamaError(str(ev["error"]))
                succeeded = ev.get("status") == "success"
                if on_event is not None:
                    on_event(ev)
            if not succeeded:
                raise OllamaError("Model download ended before Ollama reported success. Please retry.")
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
            with self._opener.open(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            raise OllamaError(
                f"Delete failed ({e.code}): {_http_error_detail(e)}"
            ) from e
        except urllib.error.URLError as e:
            raise OllamaNotRunning(_url_error_message(self.endpoint, e)) from e
