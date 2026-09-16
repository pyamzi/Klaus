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
