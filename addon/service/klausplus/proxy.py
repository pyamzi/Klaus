"""Auth, limits and the three proxied routes. Bodies pass through; only counters stay."""
from __future__ import annotations

import json
import struct
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import entitlement, keys, meter

router = APIRouter()


def _err(status: int, message: str, kind: str = "klaus_plus") -> HTTPException:
    return HTTPException(status_code=status, detail={"type": kind, "message": message})


def _version_tuple(v: str) -> tuple:
    out = []
    for part in (v or "0").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


class RateLimiter:
    """Requests per minute per customer — a single-machine service, memory is fine."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[int, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, customer_id: int, now: float) -> bool:
        with self._lock:
            hits = [t for t in self._hits.get(customer_id, []) if now - t < 60.0]
            if len(hits) >= self.per_minute:
                self._hits[customer_id] = hits
                return False
            hits.append(now)
            self._hits[customer_id] = hits
            return True


def authenticate(request: Request, purpose_required: bool = True) -> Any:
    st = request.app.state
    settings, store, now = st.settings, st.store, st.now()
    if settings.paused:
        raise _err(503, "Klaus Plus is paused for maintenance — try again later, or use your own API key.")
    if _version_tuple(request.headers.get("X-Klaus-Client", "")) < _version_tuple(settings.min_client_version):
        raise _err(426, "This Klaus is too old for Klaus Plus — update it from Tools → Add-ons.")
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    row = store.customer_by_hash(keys.hash_key(token)) if keys.looks_like_key(token) else None
    if row is None:
        raise _err(401, "Klaus Plus key not recognised — check it under KlausMate Preferences.")
    state, reason = entitlement.verdict(row, now, settings.grace_days)
    if state != "active":
        raise _err(402, f"Klaus Plus is not active ({reason}) — manage your subscription under KlausMate Preferences.")
    if not st.limiter.allow(int(row["id"]), now):
        raise _err(429, "Too many requests — Klaus Plus allows 60 a minute; wait a moment.")
    purpose = request.headers.get("X-Klaus-Purpose", "")
    if purpose_required and purpose not in meter.PURPOSES:
        raise _err(400, "Missing or unknown X-Klaus-Purpose header.")
    request.state.customer = row
    request.state.purpose = purpose
    return row


def _quota_header(request: Request, customer_id: int) -> dict:
    st = request.app.state
    return {"X-Klaus-Quota": json.dumps(meter.snapshot(st.store, st.settings, customer_id, st.now()))}


def _declared_length(request: Request) -> int:
    """The client-declared Content-Length, or 0 if missing or not a plain integer."""
    try:
        return int(request.headers.get("content-length") or 0)
    except ValueError:
        return 0


def _log(request: Request, status: int, metered: int, started: float) -> None:
    row = getattr(request.state, "customer", None)
    prefix = (row["key_hash"] or "")[:8] if row is not None else "-"
    request.app.state.log.info("%s %s %d key=%s ms=%d metered=%d", request.method, request.url.path, status, prefix,
                               int((time.time() - started) * 1000), metered)


def wav_seconds(data: bytes) -> float:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, rate, channels, bits, data_len = 12, 0, 0, 0, 0
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt " and size >= 16:
            _fmt, channels, rate, _br, _ba, bits = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
        elif cid == b"data":
            data_len = min(size, len(data) - pos - 8)
            break
        pos += 8 + size + (size & 1)
    if not (rate and channels and bits and data_len):
        raise ValueError("WAVE header incomplete")
    return data_len / float(rate * channels * (bits // 8))


@router.get("/v1/me")
def me(request: Request) -> JSONResponse:
    started = time.time()
    row = authenticate(request, purpose_required=False)
    st = request.app.state
    body = {"plan": "plus", "status": row["status"], "period_end": int(row["period_end"] or 0),
            "cancel_at_period_end": bool(row["cancel_at_period_end"]),
            "quota": meter.snapshot(st.store, st.settings, int(row["id"]), st.now()),
            "min_client_version": st.settings.min_client_version}
    _log(request, 200, 0, started)
    return JSONResponse(body, headers=_quota_header(request, int(row["id"])))


@router.post("/v1/embeddings")
async def embeddings(request: Request) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    if request.state.purpose != "embed":
        raise _err(400, "X-Klaus-Purpose must be 'embed' for /v1/embeddings.")
    if _declared_length(request) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    raw = await request.body()
    if len(raw) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    body = json.loads(raw or b"{}")
    if st.settings.allowed_models and body.get("model") not in st.settings.allowed_models:
        raise _err(400, "That model is not available on Klaus Plus.")
    inputs = body.get("input") if isinstance(body.get("input"), list) else [body.get("input") or ""]
    guess = sum(len(str(t)) for t in inputs) // 4
    ok, _ = meter.check(st.store, st.settings, int(row["id"]), "embed", guess, st.now())
    if not ok:
        raise _err(402, meter.quota_message("embed", meter.snapshot(st.store, st.settings, int(row["id"]), st.now())["resets_at"]))
    resp = await st.upstream.openai_json("/embeddings", body)
    metered = 0
    if resp.status_code == 200:
        try:
            metered = int((resp.json().get("usage") or {}).get("total_tokens") or guess)
        except (ValueError, AttributeError, TypeError):
            metered = guess
        meter.charge(st.store, st.settings, int(row["id"]), "embed", metered, st.now())
    _log(request, resp.status_code, metered, started)
    return Response(resp.content, status_code=resp.status_code, media_type="application/json",
                    headers=_quota_header(request, int(row["id"])))


@router.post("/v1/audio/transcriptions")
async def transcriptions(request: Request) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    if request.state.purpose != "transcribe":
        raise _err(400, "X-Klaus-Purpose must be 'transcribe' for /v1/audio/transcriptions.")
    if _declared_length(request) > st.settings.max_audio_bytes + 65536:
        raise _err(413, "Audio chunk too large (25 MB max).")
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise _err(400, "Missing multipart field 'file'.")
    if st.settings.allowed_models and form.get("model") not in st.settings.allowed_models:
        raise _err(400, "That model is not available on Klaus Plus.")
    content = await upload.read()
    if len(content) > st.settings.max_audio_bytes:
        raise _err(413, "Audio chunk too large (25 MB max).")
    try:
        seconds = int(round(wav_seconds(content)))
    except ValueError:
        raise _err(400, "Only WAV audio is accepted.")
    cid = int(row["id"])
    if not meter.check_daily_audio(st.store, st.settings, cid, seconds, st.now()):
        raise _err(402, "Klaus Plus transcribes at most 240 minutes a day and you have reached today's limit; more tomorrow.")
    ok, _ = meter.check(st.store, st.settings, cid, "transcribe", seconds, st.now())
    if not ok:
        raise _err(402, meter.quota_message("transcribe", meter.snapshot(st.store, st.settings, cid, st.now())["resets_at"]))
    fields = {k: str(v) for k, v in form.items() if k != "file" and isinstance(v, str)}
    resp = await st.upstream.openai_multipart("/audio/transcriptions", fields, getattr(upload, "filename", "chunk.wav") or "chunk.wav",
                                              content, getattr(upload, "content_type", "audio/wav") or "audio/wav")
    metered = 0
    if resp.status_code == 200:
        metered = seconds
        meter.charge(st.store, st.settings, cid, "transcribe", seconds, st.now())
    _log(request, resp.status_code, metered, started)
    return Response(resp.content, status_code=resp.status_code, media_type="application/json", headers=_quota_header(request, cid))


def _usage_from_sse_line(line: bytes, acc: dict) -> None:
    if not line.startswith(b"data: "):
        return
    try:
        obj = json.loads(line[6:])
    except ValueError:
        return
    if obj.get("type") == "message_start":
        acc["in"] = int(((obj.get("message") or {}).get("usage") or {}).get("input_tokens") or 0)
    elif obj.get("type") == "message_delta":
        acc["out"] = int((obj.get("usage") or {}).get("output_tokens") or 0)


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    purpose = request.state.purpose
    if purpose not in ("judge", "assistant"):
        raise _err(400, "X-Klaus-Purpose must be 'judge' or 'assistant' for /v1/messages.")
    if _declared_length(request) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    raw = await request.body()
    if len(raw) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    body = json.loads(raw or b"{}")
    if st.settings.allowed_models and body.get("model") not in st.settings.allowed_models:
        raise _err(400, "That model is not available on Klaus Plus.")
    cid = int(row["id"])
    ok, _ = meter.check(st.store, st.settings, cid, purpose, 1, st.now())
    if not ok:
        raise _err(402, meter.quota_message(purpose, meter.snapshot(st.store, st.settings, cid, st.now())["resets_at"]))
    stream = bool(body.get("stream"))
    resp = await st.upstream.anthropic(body, stream)
    if not stream or resp.status_code != 200:
        content = await resp.aread() if hasattr(resp, "aread") else resp.content
        metered = 0
        if resp.status_code == 200:
            try:
                u = json.loads(content).get("usage") or {}
                metered = int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
            except (ValueError, AttributeError, TypeError):
                metered = 0
            meter.charge(st.store, st.settings, cid, purpose, metered, st.now())
        _log(request, resp.status_code, metered, started)
        return Response(content, status_code=resp.status_code, media_type="application/json", headers=_quota_header(request, cid))

    acc = {"in": 0, "out": 0}

    async def relay():
        buf = b""
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    _usage_from_sse_line(line.rstrip(b"\r"), acc)
        finally:
            try:
                metered = acc["in"] + acc["out"]
                meter.charge(st.store, st.settings, cid, purpose, metered, st.now())
                _log(request, 200, metered, started)
            finally:
                await resp.aclose()

    return StreamingResponse(relay(), media_type="text/event-stream", headers=_quota_header(request, cid))
