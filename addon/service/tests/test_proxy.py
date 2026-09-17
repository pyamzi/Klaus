from __future__ import annotations
import asyncio
import io
import json
import logging
import struct
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from klausplus import email, keys
from klausplus.app import create_app
from klausplus.db import next_month_start
from klausplus.upstream import FakeUpstream


def _wav(seconds: float, rate: int = 16000) -> bytes:
    n = int(seconds * rate)
    data = b"\x00\x00" * n
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return hdr + b"data" + struct.pack("<I", len(data)) + data


def _wav_with_bits(bits: int, n_bytes: int = 100, rate: int = 16000) -> bytes:
    """M-2: a WAVE header naming a sub-byte bit depth (1-7) -- byte_rate/block_align
    are nominal, wav_seconds() never reads them."""
    data = b"\x00" * n_bytes
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, bits)
    return hdr + b"data" + struct.pack("<I", len(data)) + data


@pytest.fixture
def world(settings, now):
    up = FakeUpstream()
    clock = {"t": now}
    app = create_app(settings, upstream=up, now=lambda: clock["t"])
    store = app.state.store
    cid = store.upsert_customer("cus_1", "a@b.c", now)
    key = keys.mint()
    store.set_key_hash(cid, keys.hash_key(key), now)
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


def test_a_tiny_request_still_costs_a_token(world, settings):
    """K-278: `chars // 4` and `len(raw) // 4` are 0 for a short input, so the request was
    ADMITTED against a spent ceiling and — with K-275's fallback metering the reservation —
    billed nothing. Unlimited short requests walked past the cap."""
    world["store"].add_usage(world["cid"], "2026-09", "embed_tokens", settings.embed_ceiling_tokens)
    r = world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 402
    assert world["up"].calls == []
    world["store"].add_usage(world["cid"], "2026-09", "embed_tokens", -settings.embed_ceiling_tokens)
    r = world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 200 and world["store"].usage(world["cid"], "2026-09")["embed_tokens"] >= 1
    # fix1: the carve-out is a literally EMPTY input list, not "no characters" — a list of
    # empty strings was admitted against the spent ceiling and forwarded upstream.
    # The counter must sit EXACTLY on the ceiling: one token over and even a 0-token
    # reservation is refused, which would pass this pin with the carve-out still wrong.
    used = world["store"].usage(world["cid"], "2026-09")["embed_tokens"]
    world["store"].add_usage(world["cid"], "2026-09", "embed_tokens", settings.embed_ceiling_tokens - used)
    assert world["store"].usage(world["cid"], "2026-09")["embed_tokens"] == settings.embed_ceiling_tokens
    calls_before = len(world["up"].calls)  # the 200 above spent a legitimate call
    r = world["client"].post("/v1/embeddings", json={"input": ["", ""]}, headers=_h(world, "embed"))
    assert r.status_code == 402 and len(world["up"].calls) == calls_before
    world["store"].add_usage(world["cid"], "2026-09", "embed_tokens", -settings.embed_ceiling_tokens)
    # the same on /v1/messages: a two-byte body with no max_tokens reserved nothing at all
    world["store"].add_usage(world["cid"], "2026-09", "judge_tokens", settings.quota_judge_tokens)
    r = world["client"].post("/v1/messages", content=b"{}",
                             headers=dict(_h(world, "judge"), **{"content-type": "application/json"}))
    assert r.status_code == 402


def test_audio_shorter_than_a_second_costs_a_second(world):
    """K-278: `int(round(...))` billed a sub-half-second chunk as 0 seconds and forwarded it
    free. Audio rounds UP now — a zero-length WAV is still junk and refused before this."""
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"},
                             files={"file": ("c.wav", _wav(0.3), "audio/wav")}, headers=_h(world, "transcribe"))
    assert r.status_code == 200
    assert world["store"].usage(world["cid"], "2026-09")["audio_seconds"] == 1
    assert json.loads(r.headers["X-Klaus-Quota"])["counters"]["transcribe"]["used"] == 1
    assert world["store"].daily_audio(world["cid"], "2026-09-16") == 1


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


def test_messages_meters_prompt_cache_tokens_non_stream(world, monkeypatch):
    # I-1: a cached request must be metered on all four usage fields, not just
    # input/output -- Anthropic bills the cache fields, so an unmetered cache
    # write/read is free spend on the operator's own key.
    async def cached(body, stream):
        return httpx.Response(200, json={"id": "m", "content": [{"type": "text", "text": "ok"}],
                                         "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100000,
                                                   "cache_read_input_tokens": 90000, "output_tokens": 20}})
    monkeypatch.setattr(world["app"].state.upstream, "anthropic", cached)
    body = {"model": "claude-sonnet-5", "max_tokens": 50, "messages": [{"role": "user", "content": "hi"}]}
    r = world["client"].post("/v1/messages", json=body, headers=_h(world, "judge"))
    assert r.status_code == 200
    assert world["store"].usage(world["cid"], "2026-09")["judge_tokens"] == 190030


def test_messages_meters_prompt_cache_tokens_stream(world, monkeypatch):
    # I-1: same, through the SSE relay -- the cache fields ride message_start's usage.
    async def cached(body, stream):
        events = [
            'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":10,'
            '"cache_creation_input_tokens":100000,"cache_read_input_tokens":90000,"output_tokens":1}}}\n\n',
            'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":20}}\n\n',
            'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b"".join(e.encode() for e in events))
    monkeypatch.setattr(world["app"].state.upstream, "anthropic", cached)
    body = {"model": "claude-sonnet-5", "max_tokens": 50, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with world["client"].stream("POST", "/v1/messages", json=body, headers=_h(world, "assistant")) as r:
        assert r.status_code == 200
        b"".join(r.iter_bytes())
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == 190030


def test_messages_402_when_judge_quota_spent(world, settings):
    world["store"].add_usage(world["cid"], "2026-09", "judge_tokens", settings.quota_judge_tokens)
    body = {"model": "claude-sonnet-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 402


def test_a_raising_body_read_on_a_streamed_non_200_leaves_usage_unchanged(world, monkeypatch):
    """R1 (fix round 1): `await resp.aread()` is a REAL network read for a streamed non-200 —
    it sat between the reservation and the settle with nothing releasing it, so a read
    timeout there charged the whole estimate forever, with no recovery path."""
    class Boom(httpx.Response):
        async def aread(self):
            raise httpx.ReadTimeout("upstream went away mid-body")

    async def half_dead(body, stream):
        return Boom(500, json={"error": {"message": "upstream"}})

    monkeypatch.setattr(world["app"].state.upstream, "anthropic", half_dead)
    body = {"model": "claude-sonnet-5", "max_tokens": 4096, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(httpx.ReadTimeout):
        world["client"].post("/v1/messages", json=body, headers=_h(world, "judge"))
    assert world["store"].usage(world["cid"], "2026-09")["judge_tokens"] == 0


def test_a_month_straddle_bills_the_month_that_admitted_the_request(world, monkeypatch):
    """R2 (fix round 1): reserve and settle are up to one upstream timeout apart. Settling on
    its own clock charged September and released out of October — a negative counter there,
    which `meter.check` reads as spendable quota."""
    async def slow(body, stream):
        world["clock"]["t"] = next_month_start(world["clock"]["t"]) + 1  # crossed UTC midnight mid-call
        return httpx.Response(200, json={"id": "m", "content": [{"type": "text", "text": "ok"}],
                                         "usage": {"input_tokens": 100, "output_tokens": 25}})

    monkeypatch.setattr(world["app"].state.upstream, "anthropic", slow)
    body = {"model": "claude-sonnet-5", "max_tokens": 4096, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 200
    assert world["store"].usage(world["cid"], "2026-09")["judge_tokens"] == 125
    assert world["store"].usage(world["cid"], "2026-10")["judge_tokens"] == 0


def test_a_stream_whose_response_start_fails_releases_its_reservation(world):
    """K-267: `stream_response` sends `http.response.start` BEFORE the first iteration, so a
    failure there means the relay — which owns the settle — is never entered at all, and the
    reservation stands until the month rolls over. Starlette's own `background` cannot cover
    it: that runs after `stream_response`, which is exactly what did not run. Driven as raw
    ASGI because no HTTP client can make the send callable fail."""
    raw = json.dumps({"model": "claude-sonnet-5", "max_tokens": 4096, "stream": True,
                      "messages": [{"role": "user", "content": "hi"}]}).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        raise RuntimeError("the client vanished before the headers went out")

    headers = dict(_h(world, "assistant"), host="test", **{"content-type": "application/json"})
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
             "method": "POST", "path": "/v1/messages", "raw_path": b"/v1/messages", "query_string": b"",
             "root_path": "", "scheme": "http", "server": ("test", 80), "client": ("1.2.3.4", 5000),
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    up = world["app"].state.upstream
    captured: list = []
    orig_anthropic = up.anthropic

    async def spy(body, stream):
        r = await orig_anthropic(body, stream)
        captured.append(r)
        return r

    up.anthropic = spy
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(world["app"](scope, receive, send))
    finally:
        up.anthropic = orig_anthropic
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == 0
    # ...and the upstream response is closed too: the relay's `finally` normally does that,
    # and on this path the relay never ran (reviewer's note on K-267)
    assert captured and captured[0].is_closed
    # and a stream that does run settles exactly once — not twice, not not at all
    body = {"model": "claude-sonnet-5", "max_tokens": 4096, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with world["client"].stream("POST", "/v1/messages", json=body, headers=_h(world, "assistant")) as r:
        b"".join(r.iter_bytes())
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == 125


def test_the_streamed_quota_header_never_advertises_the_reservation(world):
    """R3 (fix round 1): a StreamingResponse's headers go out before its body, and neither
    Starlette nor uvicorn does response trailers — so the settled figure CANNOT reach the
    streamed header. It must then read the usage the request was admitted on, never the
    inflated reservation (`plus.note_quota` caches whatever it says). The non-stream branch,
    where a post-settle header is possible, does report the settled figure."""
    body = {"model": "claude-sonnet-5", "max_tokens": 40_000, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with world["client"].stream("POST", "/v1/messages", json=body, headers=_h(world, "assistant")) as r:
        streamed = json.loads(r.headers["X-Klaus-Quota"])
        b"".join(r.iter_bytes())
    assert streamed["counters"]["assistant"]["used"] == 0
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == 125
    r = world["client"].post("/v1/messages", json={**body, "stream": False}, headers=_h(world, "assistant"))
    assert json.loads(r.headers["X-Klaus-Quota"])["counters"]["assistant"]["used"] == 245


_NO_USAGE_SSE = (b'event: message_start\ndata: {"type":"message_start","message":{}}\n\n'
                 b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}\n\n'
                 b'event: message_stop\ndata: {"type":"message_stop"}\n\n')


def _judge_body(max_tokens=4096):
    """The exact bytes, so the test knows the reservation the route will compute."""
    raw = json.dumps({"model": "claude-sonnet-5", "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": "hi"}]}).encode()
    return raw, len(raw) // 4 + max_tokens


def test_a_2xx_without_usage_meters_the_reservation_not_nothing(world, monkeypatch):
    """K-275: `usage` absent or unparseable metered 0, which settled the reservation back to
    nothing — a provider (or a proxy in front of one) that omits usage made every judged card
    free. A 2xx now settles the estimate the request was ADMITTED on."""
    raw, reserved = _judge_body()
    hdrs = dict(_h(world, "judge"), **{"content-type": "application/json"})

    async def no_usage(body, stream):
        return httpx.Response(200, json={"id": "m", "content": [{"type": "text", "text": "ok"}]})

    monkeypatch.setattr(world["app"].state.upstream, "anthropic", no_usage)
    assert world["client"].post("/v1/messages", content=raw, headers=hdrs).status_code == 200
    assert world["store"].usage(world["cid"], "2026-09")["judge_tokens"] == reserved

    async def junk_usage(body, stream):
        return httpx.Response(200, json={"id": "m", "content": [], "usage": "lots and lots"})

    monkeypatch.setattr(world["app"].state.upstream, "anthropic", junk_usage)
    assert world["client"].post("/v1/messages", content=raw, headers=hdrs).status_code == 200
    assert world["store"].usage(world["cid"], "2026-09")["judge_tokens"] == 2 * reserved


def test_a_stream_that_reports_no_usage_meters_the_reservation(world, monkeypatch):
    """K-275, the same gap on the SSE path: no usage event leaves all four accumulators at 0."""
    raw, reserved = _judge_body()
    hdrs = dict(_h(world, "assistant"), **{"content-type": "application/json"})
    body = json.loads(raw)
    body["stream"] = True
    streamed = json.dumps(body).encode()
    reserved_stream = len(streamed) // 4 + 4096

    async def silent(body, stream):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_NO_USAGE_SSE)

    monkeypatch.setattr(world["app"].state.upstream, "anthropic", silent)
    with world["client"].stream("POST", "/v1/messages", content=streamed, headers=hdrs) as r:
        assert r.status_code == 200
        assert b"message_stop" in b"".join(r.iter_bytes())
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == reserved_stream
    # and a stream that DOES report usage still meters the real figure, not the estimate
    monkeypatch.undo()
    with world["client"].stream("POST", "/v1/messages", content=streamed, headers=hdrs) as r:
        b"".join(r.iter_bytes())
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == reserved_stream + 125


def test_embeddings_without_usage_meters_the_guess_however_it_is_malformed(world, monkeypatch):
    """K-275: /v1/embeddings already fell back to the guess — pinned here so it stays that
    way for a malformed usage block, not only a missing one."""
    for payload in ({"data": []}, {"data": [], "usage": "nope"}, {"data": [], "usage": {"total_tokens": "abc"}}):
        async def canned(path, body, _p=payload):
            return httpx.Response(200, json=_p)
        monkeypatch.setattr(world["app"].state.upstream, "openai_json", canned)
        before = world["store"].usage(world["cid"], "2026-09")["embed_tokens"]
        r = world["client"].post("/v1/embeddings", json={"input": ["abcdefgh", "ijklmnop"]}, headers=_h(world, "embed"))
        assert r.status_code == 200
        assert world["store"].usage(world["cid"], "2026-09")["embed_tokens"] == before + 4, payload


def test_messages_402_when_max_tokens_cannot_fit_the_remaining_quota(world, settings):
    """K-262: the pre-check is an estimate (body chars/4 + max_tokens), not a bare 1 --
    a turn that cannot possibly fit in what is left is refused before the provider call."""
    world["store"].add_usage(world["cid"], "2026-09", "judge_tokens", settings.quota_judge_tokens - 1000)
    big = {"model": "claude-sonnet-5", "max_tokens": 50_000, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=big, headers=_h(world, "judge")).status_code == 402
    assert world["up"].calls == []
    small = {"model": "claude-sonnet-5", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=small, headers=_h(world, "judge")).status_code == 200


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


def test_rate_limit_429_names_the_configured_limit(world, settings):
    # C-1: the message must read the SETTING, not a literal, so raising the
    # default doesn't leave a stale number in the error text.
    world["app"].state.settings = settings.__class__(**{**settings.__dict__, "rate_per_minute": 3})
    world["app"].state.limiter.per_minute = 3
    for _ in range(3):
        assert world["client"].get("/v1/me", headers=_h(world, "embed")).status_code == 200
    r = world["client"].get("/v1/me", headers=_h(world, "embed"))
    assert r.status_code == 429 and "allows 3 a minute" in r.json()["error"]["message"]


def test_rate_limit_default_clears_a_100_call_index_batch_and_names_600(world, settings):
    # C-1: the add-on indexes 64 notes per request back to back -- 100 calls in one
    # window must all clear at the shipped default (the old 60/min refused this on
    # any collection above ~3,800 notes, on the FIRST index).
    assert settings.rate_per_minute == 600
    for _ in range(100):
        assert world["client"].get("/v1/me", headers=_h(world, "embed")).status_code == 200
    # exhaust the rest of the same window directly (no need for 500 more round trips)
    # to prove the boundary -- and its message -- follow the real setting.
    limiter, cid, now = world["app"].state.limiter, world["cid"], world["clock"]["t"]
    for _ in range(settings.rate_per_minute - 100):
        assert limiter.allow(cid, now) is True
    r = world["client"].get("/v1/me", headers=_h(world, "embed"))
    assert r.status_code == 429 and "allows 600 a minute" in r.json()["error"]["message"]


def test_upstream_error_passes_through_unmetered(world, monkeypatch):
    async def boom(path, body):
        return httpx.Response(500, json={"error": {"message": "upstream"}})
    monkeypatch.setattr(world["app"].state.upstream, "openai_json", boom)
    r = world["client"].post("/v1/embeddings", json={"input": ["abcd"]}, headers=_h(world, "embed"))
    assert r.status_code == 500
    # K-262: the pre-flight reservation is released again — a failed call bills nothing.
    assert world["store"].usage(world["cid"], "2026-09")["embed_tokens"] == 0


def test_upstream_500_on_messages_and_transcription_leaves_usage_unchanged(world, monkeypatch):
    """K-262: every route now reserves its estimate before calling the provider, so every
    route has to hand it back when the provider answers anything but a 200."""
    async def boom_msg(body, stream):
        return httpx.Response(500, json={"error": {"message": "upstream"}})

    async def boom_audio(path, fields, filename, content, content_type):
        return httpx.Response(500, json={"error": {"message": "upstream"}})

    monkeypatch.setattr(world["app"].state.upstream, "anthropic", boom_msg)
    monkeypatch.setattr(world["app"].state.upstream, "openai_multipart", boom_audio)
    body = {"model": "claude-sonnet-5", "max_tokens": 4096, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 500
    assert world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", _wav(30.0), "audio/wav")},
                                headers=_h(world, "transcribe")).status_code == 500
    usage = world["store"].usage(world["cid"], "2026-09")
    assert usage["judge_tokens"] == 0 and usage["audio_seconds"] == 0
    assert world["store"].daily_audio(world["cid"], "2026-09-16") == 0


# --- I-2: an upstream 401/403 must never become the subscriber's own 401 ----


_LEAKED_KEY_FRAGMENT = "sk-proj-****abcd"


def test_upstream_401_on_embeddings_becomes_502_and_never_leaks(world, monkeypatch, caplog):
    async def revoked(path, body):
        return httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {_LEAKED_KEY_FRAGMENT}"}})
    monkeypatch.setattr(world["app"].state.upstream, "openai_json", revoked)
    with caplog.at_level(logging.INFO, logger="klausplus"):
        r = world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 502 and r.json()["error"]["type"] == "klaus_plus"
    assert _LEAKED_KEY_FRAGMENT not in r.text
    assert _LEAKED_KEY_FRAGMENT not in "\n".join(rec.getMessage() for rec in caplog.records)
    assert world["store"].usage(world["cid"], "2026-09")["embed_tokens"] == 0


def test_upstream_403_on_transcription_becomes_502_and_never_leaks(world, monkeypatch, caplog):
    async def revoked(path, fields, filename, content, content_type):
        return httpx.Response(403, json={"error": {"message": f"Incorrect API key provided: {_LEAKED_KEY_FRAGMENT}"}})
    monkeypatch.setattr(world["app"].state.upstream, "openai_multipart", revoked)
    with caplog.at_level(logging.INFO, logger="klausplus"):
        r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", _wav(5.0), "audio/wav")},
                                 headers=_h(world, "transcribe"))
    assert r.status_code == 502 and r.json()["error"]["type"] == "klaus_plus"
    assert _LEAKED_KEY_FRAGMENT not in r.text
    assert _LEAKED_KEY_FRAGMENT not in "\n".join(rec.getMessage() for rec in caplog.records)
    assert world["store"].usage(world["cid"], "2026-09")["audio_seconds"] == 0


def test_upstream_401_on_messages_becomes_502_and_never_leaks(world, monkeypatch, caplog):
    async def revoked(body, stream):
        return httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {_LEAKED_KEY_FRAGMENT}"}})
    monkeypatch.setattr(world["app"].state.upstream, "anthropic", revoked)
    body = {"model": "claude-sonnet-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
    with caplog.at_level(logging.INFO, logger="klausplus"):
        r = world["client"].post("/v1/messages", json=body, headers=_h(world, "judge"))
    assert r.status_code == 502 and r.json()["error"]["type"] == "klaus_plus"
    assert _LEAKED_KEY_FRAGMENT not in r.text
    assert _LEAKED_KEY_FRAGMENT not in "\n".join(rec.getMessage() for rec in caplog.records)
    assert world["store"].usage(world["cid"], "2026-09")["judge_tokens"] == 0


def test_upstream_401_on_messages_stream_becomes_502(world, monkeypatch):
    # I-2: the check must land BEFORE the SSE relay is built -- a stream request
    # whose upstream call itself 401s must never start relaying.
    held = {}

    async def revoked(body, stream):
        # A STREAMED body, never read by the route: the 502 must close it or
        # the pooled connection leaks (httpx has no finalizer for it).
        held["resp"] = httpx.Response(401, stream=httpx.ByteStream(
            json.dumps({"error": {"message": _LEAKED_KEY_FRAGMENT}}).encode()))
        return held["resp"]
    monkeypatch.setattr(world["app"].state.upstream, "anthropic", revoked)
    body = {"model": "claude-sonnet-5", "max_tokens": 5, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    r = world["client"].post("/v1/messages", json=body, headers=_h(world, "assistant"))
    assert r.status_code == 502 and r.json()["error"]["type"] == "klaus_plus"
    assert held["resp"].is_closed, "the unread streamed 401 must be closed before the 502"
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == 0
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


def test_chunked_oversized_body_is_413_without_ever_buffering_it(world, settings):
    """K-262: a chunked body carries no Content-Length, so the declared-length check
    cannot fire. The read must refuse the moment the running total passes the cap --
    never pull the whole 16MB in first. Driven as raw ASGI because every HTTP client
    here (TestClient, ASGITransport) coalesces the chunks before the app sees them."""
    chunk = b"x" * (256 * 1024)
    fed = {"n": 0}
    sent = []

    async def receive():
        if fed["n"] >= 16 * 1024 * 1024:
            return {"type": "http.request", "body": b"", "more_body": False}
        fed["n"] += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        sent.append(message)

    headers = dict(_h(world, "embed"), host="test", **{"content-type": "application/json", "transfer-encoding": "chunked"})
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "path": "/v1/embeddings", "raw_path": b"/v1/embeddings", "query_string": b"", "root_path": "",
             "scheme": "http", "server": ("test", 80), "client": ("1.2.3.4", 5000),
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(world["app"](scope, receive, send))
    assert next(m["status"] for m in sent if m["type"] == "http.response.start") == 413
    assert fed["n"] <= settings.max_json_bytes + len(chunk)
    assert world["up"].calls == []


def test_read_capped_answers_the_cap_on_a_body_someone_else_cached():
    """N1: the cached fast path has to answer the cap too. Nothing in this app reads a body
    before `_read_capped` today — there is no middleware and both `request.form()` calls come
    after it — so only a future middleware can reach this, which is exactly the point: the
    helper's contract is 'this answers the cap', with no condition attached."""
    import types
    from fastapi import HTTPException
    from klausplus.proxy import _read_capped
    req = types.SimpleNamespace(_body=b"x" * 100)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_read_capped(req, 10))
    assert exc.value.status_code == 413
    assert asyncio.run(_read_capped(req, 1000)) == b"x" * 100


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


def test_malformed_json_body_is_400_in_the_envelope_not_a_bare_500(world):
    # M-1: `{not json` and `[]` must both land as a klaus_plus 400 on both JSON
    # routes -- not a JSONDecodeError/AttributeError bare 500 with a traceback.
    for path, hdrs in (("/v1/embeddings", _h(world, "embed")), ("/v1/messages", _h(world, "judge"))):
        for raw in (b"{not json", b"[]"):
            r = world["client"].post(path, content=raw, headers=hdrs)
            assert r.status_code == 400 and r.json()["error"]["type"] == "klaus_plus", (path, raw)


def test_wav_bit_depth_under_8_is_400_not_a_bare_500(world):
    # M-2: bits 1-7 must raise ValueError (the route's existing 400 path), never
    # ZeroDivisionError from `bits // 8` landing in the denominator.
    from klausplus.proxy import wav_seconds
    with pytest.raises(ValueError):
        wav_seconds(_wav_with_bits(4))
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"},
                             files={"file": ("c.wav", _wav_with_bits(4), "audio/wav")}, headers=_h(world, "transcribe"))
    assert r.status_code == 400


# --- fix round 1 (K-243), I-5: the 80%-of-quota notice ----------------------


def test_quota_notice_sent_once_on_crossing_80_percent(world, settings, monkeypatch):
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    sent = []
    monkeypatch.setattr(email, "send_quota_notice", lambda s, to, purpose, human_line: sent.append((to, purpose)) or True)
    cap = settings.quota_judge_tokens
    world["store"].add_usage(world["cid"], "2026-09", "judge_tokens", int(cap * 0.8) - 10)
    body = {"model": "claude-sonnet-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 200
    assert sent == [("a@b.c", "judge")]
    # the next charge is still above the line, not crossing it again: no second notice
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 200
    assert sent == [("a@b.c", "judge")]


def test_quota_notice_not_sent_when_email_disabled(world, settings, monkeypatch):
    assert not settings.email_enabled
    sent = []
    monkeypatch.setattr(email, "send_quota_notice", lambda *a, **k: sent.append(a) or True)
    cap = settings.quota_judge_tokens
    world["store"].add_usage(world["cid"], "2026-09", "judge_tokens", int(cap * 0.8) - 10)
    body = {"model": "claude-sonnet-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 200
    assert sent == []


def test_quota_notice_sent_once_on_crossing_80_percent_via_stream(world, settings, monkeypatch):
    """Same as above, through the SSE relay's fire-and-forget path (run_in_executor,
    no BackgroundTasks available there) — polls briefly since the send runs on a
    worker thread after the streamed response has already closed."""
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    sent = []
    monkeypatch.setattr(email, "send_quota_notice", lambda s, to, purpose, human_line: sent.append((to, purpose)) or True)
    cap = settings.quota_assistant_tokens
    world["store"].add_usage(world["cid"], "2026-09", "assistant_tokens", int(cap * 0.8) - 100)
    body = {"model": "claude-sonnet-5", "max_tokens": 50, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with world["client"].stream("POST", "/v1/messages", json=body, headers=_h(world, "assistant")) as r:
        assert r.status_code == 200
        b"".join(r.iter_bytes())
    deadline = time.time() + 1.0
    while not sent and time.time() < deadline:
        time.sleep(0.01)
    assert sent == [("a@b.c", "assistant")]
