from __future__ import annotations
import asyncio
import io
import json
import struct
import httpx
import pytest
from fastapi.testclient import TestClient
from klausplus import keys
from klausplus.app import create_app
from klausplus.db import next_month_start


def _wav(seconds: float, rate: int = 16000) -> bytes:
    n = int(seconds * rate)
    data = b"\x00\x00" * n
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return hdr + b"data" + struct.pack("<I", len(data)) + data


class FakeUpstream:
    def __init__(self):
        self.calls = []

    async def openai_json(self, path, body):
        self.calls.append(("openai_json", path, body))
        n = len(body.get("input") or [])
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1, 0.2]} for i in range(n)],
                                         "usage": {"total_tokens": 7 * n}})

    async def openai_multipart(self, path, fields, filename, content, content_type):
        self.calls.append(("openai_multipart", path, fields, filename, len(content), content_type))
        return httpx.Response(200, json={"text": "hello lecture"})

    async def anthropic(self, body, stream):
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


@pytest.fixture
def world(settings, now):
    up = FakeUpstream()
    clock = {"t": now}
    app = create_app(settings, upstream=up, now=lambda: clock["t"])
    store = app.state.store
    cid = store.upsert_customer("cus_1", "a@b.c", now)
    key = keys.mint()
    store.set_key_hash(cid, keys.hash_key(key))
    store.set_subscription("cus_1", "active", int(now) + 20 * 86400, False, now)
    return {"app": app, "client": TestClient(app), "up": up, "store": store, "cid": cid, "key": key, "clock": clock}


def _h(world, purpose, version="0.2.0", key=None):
    return {"Authorization": f"Bearer {key or world['key']}", "X-Klaus-Purpose": purpose, "X-Klaus-Client": version}


def test_healthz_is_open(world):
    assert world["client"].get("/healthz").json() == {"ok": True}


def test_embeddings_forward_and_meter(world):
    r = world["client"].post("/v1/embeddings", json={"model": "text-embedding-3-large", "input": ["a", "b"], "dimensions": 1024},
                             headers=_h(world, "embed"))
    assert r.status_code == 200 and len(r.json()["data"]) == 2
    assert world["up"].calls[0][:2] == ("openai_json", "/embeddings")
    q = json.loads(r.headers["X-Klaus-Quota"])
    assert q["counters"]["embed"]["used"] == 14


def test_unknown_key_401_and_missing_purpose_400(world):
    assert world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed", key="kp_" + "0" * 32)).status_code == 401
    assert world["client"].post("/v1/embeddings", json={"input": ["a"]},
                                headers={"Authorization": f"Bearer {world['key']}", "X-Klaus-Client": "0.2.0"}).status_code == 400


def test_version_floor_426_and_pause_503(world, settings):
    assert world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed", version="0.1.9")).status_code == 426
    world["app"].state.settings = settings.__class__(**{**settings.__dict__, "paused": True})
    r = world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 503 and "maintenance" in r.json()["error"]["message"].lower()


def test_transcription_meters_audio_seconds_and_refuses_non_wav(world):
    wav = _wav(90.0)
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "gpt-4o-mini-transcribe", "response_format": "json", "language": "en"},
                             files={"file": ("chunk.wav", wav, "audio/wav")}, headers=_h(world, "transcribe"))
    assert r.status_code == 200 and r.json()["text"] == "hello lecture"
    assert json.loads(r.headers["X-Klaus-Quota"])["counters"]["transcribe"]["used"] == 90
    calls_before = len(world["up"].calls)
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", b"not a wav", "audio/wav")},
                             headers=_h(world, "transcribe"))
    assert r.status_code == 400
    assert len(world["up"].calls) == calls_before


def test_transcription_402_at_month_cap_and_daily_cap(world, settings):
    world["store"].add_usage(world["cid"], "2026-09", "audio_seconds", settings.quota_audio_seconds - 10)
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", _wav(30.0), "audio/wav")},
                             headers=_h(world, "transcribe"))
    assert r.status_code == 402 and "resets on 2026-10-01" in r.json()["error"]["message"]
    assert world["up"].calls == []
    world["clock"]["t"] = next_month_start(world["clock"]["t"]) + 1
    world["store"].add_daily_audio(world["cid"], "2026-10-01", settings.audio_day_seconds)
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", _wav(30.0), "audio/wav")},
                             headers=_h(world, "transcribe"))
    assert r.status_code == 402 and "today" in r.json()["error"]["message"]
    assert world["up"].calls == []


def test_messages_purpose_routing_and_non_stream_metering(world):
    body = {"model": "claude-sonnet-5", "max_tokens": 50, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "embed")).status_code == 400
    r = world["client"].post("/v1/messages", json=body, headers=_h(world, "judge"))
    assert r.status_code == 200 and json.loads(r.headers["X-Klaus-Quota"])["counters"]["judge"]["used"] == 120
    assert world["up"].calls[-1][2] is False


def test_messages_stream_relays_sse_and_meters_after(world):
    body = {"model": "claude-sonnet-5", "max_tokens": 50, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with world["client"].stream("POST", "/v1/messages", json=body, headers=_h(world, "assistant")) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        text = b"".join(r.iter_bytes()).decode()
    assert "message_stop" in text and '"text":"hi"' in text
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == 125


def test_messages_402_when_judge_quota_spent(world, settings):
    world["store"].add_usage(world["cid"], "2026-09", "judge_tokens", settings.quota_judge_tokens)
    body = {"model": "claude-sonnet-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 402


def test_refused_subscription_402_with_reason(world):
    world["store"].set_subscription("cus_1", "unpaid", 0, False, world["clock"]["t"])
    r = world["client"].get("/v1/me", headers=_h(world, "embed"))
    assert r.status_code == 402 and "unpaid" in r.json()["error"]["message"]


def test_me_snapshot(world):
    r = world["client"].get("/v1/me", headers=_h(world, "embed"))
    j = r.json()
    assert j["plan"] == "plus" and j["status"] == "active" and j["quota"]["human"]["cards"] == [0, 3000]
    assert j["min_client_version"] == "0.2.0" and j["period_end"] > 0


def test_rate_limit_429(world, settings):
    world["app"].state.limiter.per_minute = 3
    for _ in range(3):
        assert world["client"].get("/v1/me", headers=_h(world, "embed")).status_code == 200
    assert world["client"].get("/v1/me", headers=_h(world, "embed")).status_code == 429


def test_upstream_error_passes_through_unmetered(world, monkeypatch):
    async def boom(path, body):
        return httpx.Response(500, json={"error": {"message": "upstream"}})
    monkeypatch.setattr(world["app"].state.upstream, "openai_json", boom)
    r = world["client"].post("/v1/embeddings", json={"input": ["abcd"]}, headers=_h(world, "embed"))
    assert r.status_code == 500
    assert world["store"].usage(world["cid"], "2026-09")["embed_tokens"] == 0


def test_embeddings_usage_null_meters_the_guess(world, monkeypatch):
    async def null_usage(path, body):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}], "usage": None})
    monkeypatch.setattr(world["app"].state.upstream, "openai_json", null_usage)
    r = world["client"].post("/v1/embeddings", json={"input": ["abcd"]}, headers=_h(world, "embed"))
    assert r.status_code == 200
    assert world["store"].usage(world["cid"], "2026-09")["embed_tokens"] == 1  # chars // 4 guess


def test_model_allow_list_when_configured(world, settings):
    restricted = settings.__class__(**{**settings.__dict__, "allowed_models": ("text-embedding-3-large",)})
    world["app"].state.settings = restricted
    r = world["client"].post("/v1/embeddings", json={"model": "x", "input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 400
    assert world["up"].calls == []
    r = world["client"].post("/v1/embeddings", json={"model": "text-embedding-3-large", "input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 200
    world["app"].state.settings = settings
    r = world["client"].post("/v1/embeddings", json={"model": "anything-goes", "input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 200


def test_bad_content_length_header_never_500s(world):
    # httpx (and so TestClient) validates/recomputes Content-Length client-side, so a
    # malformed value can only reach the route through the ASGI transport directly.
    async def probe():
        transport = httpx.ASGITransport(app=world["app"], raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = dict(_h(world, "embed"))
            headers["content-length"] = "abc"
            req = ac.build_request("POST", "/v1/embeddings", content=b'{"input": ["a"]}', headers=headers)
            return await ac.send(req)

    r = asyncio.run(probe())
    assert r.status_code == 200
    assert "X-Klaus-Quota" in r.headers


def test_transcription_model_allow_list_when_configured(world, settings):
    restricted = settings.__class__(**{**settings.__dict__, "allowed_models": ("gpt-4o-mini-transcribe",)})
    world["app"].state.settings = restricted
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", _wav(2.0), "audio/wav")},
                             headers=_h(world, "transcribe"))
    assert r.status_code == 400
    assert world["up"].calls == []
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "gpt-4o-mini-transcribe"},
                             files={"file": ("c.wav", _wav(2.0), "audio/wav")}, headers=_h(world, "transcribe"))
    assert r.status_code == 200


def test_wav_seconds():
    from klausplus.proxy import wav_seconds
    assert abs(wav_seconds(_wav(12.5)) - 12.5) < 0.01
    with pytest.raises(ValueError):
        wav_seconds(b"RIFFxxxxWAVEjunk")
