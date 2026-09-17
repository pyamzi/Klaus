"""The only module that talks to a provider. Keys enter here from Settings and nowhere else."""
from __future__ import annotations

import httpx

from .config import Settings

ANTHROPIC_VERSION = "2023-06-01"


class Upstream:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0))

    async def openai_json(self, path: str, body: dict) -> httpx.Response:
        return await self._client.post(f"{self._s.openai_base}{path}", json=body,
                                       headers={"Authorization": f"Bearer {self._s.openai_api_key}"})

    async def openai_multipart(self, path: str, fields: dict, filename: str, content: bytes, content_type: str) -> httpx.Response:
        return await self._client.post(f"{self._s.openai_base}{path}", data=fields,
                                       files={"file": (filename, content, content_type)},
                                       headers={"Authorization": f"Bearer {self._s.openai_api_key}"})

    async def anthropic(self, body: dict, stream: bool) -> httpx.Response:
        req = self._client.build_request("POST", f"{self._s.anthropic_base}/v1/messages", json=body, headers={
            "x-api-key": self._s.anthropic_api_key, "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json"})
        return await self._client.send(req, stream=stream)

    async def aclose(self) -> None:
        await self._client.aclose()


class FakeUpstream:
    """Canned responses, no network, ever — promoted from
    ``service/tests/test_proxy.py`` (K-242's fixture) so ``create_app``
    can select it too (K-249, ``KLAUS_PLUS_FAKE_UPSTREAM=1``) and the
    service runs locally, or in the offline end-to-end, with no provider
    key at all. One fake, two users: the pytest fixture below imports
    this same class rather than keeping a second copy that could drift.

    Shapes match the real APIs just enough for the proxy's own parsing
    (embedding vectors, a transcript, a non-stream message, a four-event
    SSE stream); ``calls`` records every invocation for a test — or an
    e2e transcript — to assert on without a real upstream anywhere in
    the loop.
    """

    def __init__(self) -> None:
        self.calls: list = []

    async def openai_json(self, path: str, body: dict) -> httpx.Response:
        self.calls.append(("openai_json", path, body))
        n = len(body.get("input") or [])
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1, 0.2]} for i in range(n)],
                                         "usage": {"total_tokens": 7 * n}})

    async def openai_multipart(self, path: str, fields: dict, filename: str, content: bytes, content_type: str) -> httpx.Response:
        self.calls.append(("openai_multipart", path, fields, filename, len(content), content_type))
        return httpx.Response(200, json={"text": "hello lecture"})

    async def anthropic(self, body: dict, stream: bool) -> httpx.Response:
        self.calls.append(("anthropic", body, stream))
        if not stream:
            return httpx.Response(200, json={"id": "m", "content": [{"type": "text", "text": "ok"}],
                                             "usage": {"input_tokens": 100, "output_tokens": 20}})
        events = [
            'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":100,"output_tokens":1}}}\n\n',
            'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}\n\n',
            'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":25}}\n\n',
            'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b"".join(e.encode() for e in events))
