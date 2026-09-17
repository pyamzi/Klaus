"""Auth, limits and the three proxied routes. Bodies pass through; only counters stay."""
from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import email, entitlement, keys, meter

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


def authenticate(request: Request, purpose_required: bool = True, require_active: bool = True) -> Any:
    """`require_active=False` (fix1/K-243, C-1) skips only the entitlement 402 —
    identity (401), the paused 503, the version floor and the rate limit still apply.
    The Customer Portal needs this: a lapsed customer must still be able to reach
    Stripe to fix a card or resubscribe."""
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
    if require_active:
        state, reason = entitlement.verdict(row, now, settings.grace_days)
        if state != "active":
            raise _err(402, f"Klaus Plus is not active ({reason}) — manage your subscription under KlausMate Preferences.")
    if not st.limiter.allow(int(row["id"]), now):
        raise _err(429, f"Too many requests — Klaus Plus allows {settings.rate_per_minute} a minute; wait a moment.")
    purpose = request.headers.get("X-Klaus-Purpose", "")
    if purpose_required and purpose not in meter.PURPOSES:
        raise _err(400, "Missing or unknown X-Klaus-Purpose header.")
    request.state.customer = row
    request.state.purpose = purpose
    return row


def _quota_header_from(snap: dict) -> dict:
    return {"X-Klaus-Quota": json.dumps(snap)}


def _quota_header(request: Request, customer_id: int) -> dict:
    st = request.app.state
    return _quota_header_from(meter.snapshot(st.store, st.settings, customer_id, st.now()))


def _json_body(raw: bytes) -> dict:
    """M-1: a malformed or non-object JSON body must land as a klaus_plus 400,
    never a bare 500 (JSONDecodeError / AttributeError from `.get` on a list)."""
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise _err(400, "Malformed JSON body.")
    if not isinstance(body, dict):
        raise _err(400, "Malformed JSON body.")
    return body


def _declared_length(request: Request) -> int:
    """The client-declared Content-Length, or 0 if missing or not a plain integer."""
    try:
        return int(request.headers.get("content-length") or 0)
    except ValueError:
        return 0


async def _read_capped(request: Request, cap: int) -> bytes:
    """K-262: the declared length guards nothing on its own — a CHUNKED request declares
    no length at all, and `request.body()` buffers the whole thing before any check can
    fire (on the public webhook, that is memory exhaustion for the asking). Read through
    the stream and refuse the moment the running total passes `cap`, before the next
    chunk is pulled. The bytes are cached where Starlette's own `body()` keeps them, so a
    later `.body()`/`.form()` on this request reads them back instead of finding the
    stream consumed."""
    if hasattr(request, "_body"):
        # N1: whoever cached it did not necessarily answer to THIS cap (nothing in this app
        # reads a body before us today; a future middleware would).
        if len(request._body) > cap:
            raise _err(413, "Request too large.")
        return request._body
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise _err(413, "Request too large.")
        chunks.append(chunk)
    request._body = b"".join(chunks)
    return request._body


def _log(request: Request, status: int, metered: int, started: float) -> None:
    row = getattr(request.state, "customer", None)
    prefix = (row["key_hash"] or "")[:8] if row is not None else "-"
    request.app.state.log.info("%s %s %d key=%s ms=%d metered=%d", request.method, request.url.path, status, prefix,
                               int((time.time() - started) * 1000), metered)


async def _check_upstream_auth(request: Request, resp: Any) -> None:
    """I-2: never relay a provider's own 401/403 as the subscriber's -- the
    operator's key trouble is not the subscriber's fault, and the provider's
    error text (which can carry a redacted fragment of the OPERATOR's own key)
    must never be cached into a subscriber's meta.json. Status only, logged;
    never the upstream body."""
    if resp.status_code in (401, 403):
        request.app.state.log.info("upstream auth failure status=%d", resp.status_code)
        # A streamed response was never read: close it here or the pooled
        # connection leaks (httpx has no finalizer for it).
        try:
            await resp.aclose()
        except Exception:  # noqa: BLE001 - closing is best effort on the way out
            pass
        raise _err(502, "Klaus Plus could not reach the provider — try again later, or use your own API key.")


def _safe_send_quota_notice(st: Any, to: str, purpose: str, human_line: str) -> None:
    """round2: a quota notice must never fail the request (or background task, or
    stream teardown) it rides in on. One log line on failure, never the address."""
    try:
        email.send_quota_notice(st.settings, to, purpose, human_line)
    except Exception as exc:
        st.log.info("quota notice failed: %s", type(exc).__name__)


def _notify_quota(background_tasks: BackgroundTasks, st: Any, row: Any, snap: dict) -> None:
    """I-5/spec D3: schedule (never send inline) the 80%-of-quota email for each
    purpose this charge just crossed. `snap` is a meter.charge() result."""
    crossed = snap.get("crossed_80") or []
    if not crossed or not st.settings.email_enabled:
        return
    to = str(row["email"] or "") if row is not None else ""
    if not to:
        return
    for purpose in crossed:
        background_tasks.add_task(_safe_send_quota_notice, st, to, purpose, meter._HUMAN.get(purpose, purpose))


def _notify_quota_fire_and_forget(st: Any, row: Any, snap: dict) -> None:
    """Same as _notify_quota, for the SSE relay's `finally`, which has no BackgroundTasks —
    runs the (synchronous, already-guarded) send on a worker thread so it can never block
    or break stream teardown."""
    crossed = snap.get("crossed_80") or []
    if not crossed or not st.settings.email_enabled:
        return
    to = str(row["email"] or "") if row is not None else ""
    if not to:
        return
    loop = asyncio.get_running_loop()
    for purpose in crossed:
        loop.run_in_executor(None, _safe_send_quota_notice, st, to, purpose, meter._HUMAN.get(purpose, purpose))


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
    if bits < 8:
        raise ValueError("unsupported WAVE bit depth")  # M-2: not a ZeroDivisionError from bits // 8
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
async def embeddings(request: Request, background_tasks: BackgroundTasks) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    if request.state.purpose != "embed":
        raise _err(400, "X-Klaus-Purpose must be 'embed' for /v1/embeddings.")
    if _declared_length(request) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    raw = await _read_capped(request, st.settings.max_json_bytes)
    body = _json_body(raw)
    if st.settings.allowed_models and body.get("model") not in st.settings.allowed_models:
        raise _err(400, "That model is not available on Klaus Plus.")
    inputs = body.get("input") if isinstance(body.get("input"), list) else [body.get("input") or ""]
    guess = sum(len(str(t)) for t in inputs) // 4
    res = meter.reserve(st.store, st.settings, int(row["id"]), "embed", guess, st.now())
    if not res.ok:
        raise _err(402, meter.quota_message("embed", res.before["resets_at"]))
    # The reservation is spent until settled, so every way out of here — the 502 below,
    # a network error, any non-200 — goes through the `finally` that hands it back.
    metered = 0
    try:
        resp = await st.upstream.openai_json("/embeddings", body)
        await _check_upstream_auth(request, resp)
        if resp.status_code == 200:
            try:
                metered = int((resp.json().get("usage") or {}).get("total_tokens") or guess)
            except (ValueError, AttributeError, TypeError):
                metered = guess
    finally:
        snap = meter.settle(st.store, st.settings, int(row["id"]), "embed", guess, metered, res.at)
    if resp.status_code == 200:
        _notify_quota(background_tasks, st, row, snap)
    _log(request, resp.status_code, metered, started)
    return Response(resp.content, status_code=resp.status_code, media_type="application/json",
                    headers=_quota_header(request, int(row["id"])))


@router.post("/v1/audio/transcriptions")
async def transcriptions(request: Request, background_tasks: BackgroundTasks) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    if request.state.purpose != "transcribe":
        raise _err(400, "X-Klaus-Purpose must be 'transcribe' for /v1/audio/transcriptions.")
    if _declared_length(request) > st.settings.max_audio_bytes + 65536:
        raise _err(413, "Audio chunk too large (25 MB max).")
    # The multipart wrapper costs a little over the audio itself; cap the whole body,
    # then let the parser read it back out of the cache _read_capped left behind.
    await _read_capped(request, st.settings.max_audio_bytes + 65536)
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
    # K-267: both ceilings are decided inside the one reservation lock now — a pre-check out
    # here was a read two concurrent uploads could pass together. `reason` says which refused.
    res = meter.reserve(st.store, st.settings, cid, "transcribe", seconds, st.now())
    if res.reason == "day":
        raise _err(402, "Klaus Plus transcribes at most 240 minutes a day and you have reached today's limit; more tomorrow.")
    if not res.ok:
        raise _err(402, meter.quota_message("transcribe", res.before["resets_at"]))
    fields = {k: str(v) for k, v in form.items() if k != "file" and isinstance(v, str)}
    metered = 0
    try:
        resp = await st.upstream.openai_multipart("/audio/transcriptions", fields, getattr(upload, "filename", "chunk.wav") or "chunk.wav",
                                                  content, getattr(upload, "content_type", "audio/wav") or "audio/wav")
        await _check_upstream_auth(request, resp)
        if resp.status_code == 200:
            metered = seconds
    finally:
        snap = meter.settle(st.store, st.settings, cid, "transcribe", seconds, metered, res.at)
    if resp.status_code == 200:
        _notify_quota(background_tasks, st, row, snap)
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
        usage = (obj.get("message") or {}).get("usage") or {}
        acc["in"] = int(usage.get("input_tokens") or 0)
        # I-1: a cached request is billed on these two fields too -- they ride
        # message_start's usage block alongside input_tokens.
        acc["cache_creation"] = int(usage.get("cache_creation_input_tokens") or 0)
        acc["cache_read"] = int(usage.get("cache_read_input_tokens") or 0)
    elif obj.get("type") == "message_delta":
        acc["out"] = int((obj.get("usage") or {}).get("output_tokens") or 0)


class _SettlingStream(StreamingResponse):
    """A stream that cannot lose its reservation. `stream_response` sends
    `http.response.start` BEFORE the first iteration, so a failure there — or a server that
    never drives the body at all — leaves the relay, which owns the settle, never entered:
    its `finally` does not run and the reservation stands until the month rolls over
    (K-267; measured at 4,124 tokens). Starlette's own `background` cannot close that
    window — it runs after `stream_response`, which is precisely what did not run. `entered`
    is the box the relay flips on its first iteration, so exactly one of the two releases."""

    def __init__(self, *args: Any, entered: dict, release: Any, aclose: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._entered, self._release, self._aclose = entered, release, aclose

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            if not self._entered["v"]:
                self._release()
                # The relay's own `finally` is also what closes the upstream response; on
                # this path it never ran, so the pooled connection would leak with the money.
                if self._aclose is not None:
                    try:
                        await self._aclose()
                    except Exception as exc:
                        print(f"[klausplus] upstream close after a never-entered relay failed: {type(exc).__name__}")


@router.post("/v1/messages")
async def messages(request: Request, background_tasks: BackgroundTasks) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    purpose = request.state.purpose
    if purpose not in ("judge", "assistant"):
        raise _err(400, "X-Klaus-Purpose must be 'judge' or 'assistant' for /v1/messages.")
    if _declared_length(request) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    raw = await _read_capped(request, st.settings.max_json_bytes)
    body = _json_body(raw)
    if st.settings.allowed_models and body.get("model") not in st.settings.allowed_models:
        raise _err(400, "That model is not available on Klaus Plus.")
    cid = int(row["id"])
    # K-262: pre-check on an ESTIMATE, the way /v1/embeddings guesses — a bare `1` let a
    # turn through on the last remaining token and charged the real usage afterwards.
    # A non-integer max_tokens counts as 0 (the provider will refuse it anyway; a bare
    # int() on it would be a 500). The concurrency overshoot — two requests passing the
    # check at once — stays bounded and accepted (Klaus Plus final review); no locking.
    try:
        want = max(0, int(body.get("max_tokens") or 0))
    except (TypeError, ValueError):
        want = 0
    reserved = len(raw) // 4 + want
    res = meter.reserve(st.store, st.settings, cid, purpose, reserved, st.now())
    if not res.ok:
        raise _err(402, meter.quota_message(purpose, res.before["resets_at"]))
    stream = bool(body.get("stream"))
    # R1: EVERY path from here to a settle hands the reservation back, not just the upstream
    # call — `resp.aread()` below is a real network read whenever a STREAMED response comes
    # back non-200, and a read timeout there charged the estimate forever with no recovery.
    settled = False
    try:
        resp = await st.upstream.anthropic(body, stream)
        await _check_upstream_auth(request, resp)
        if not stream or resp.status_code != 200:
            content = await resp.aread() if hasattr(resp, "aread") else resp.content
            metered = 0
            if resp.status_code == 200:
                try:
                    u = json.loads(content).get("usage") or {}
                    # I-1: cache fields are billed by the provider like any other token.
                    metered = (int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
                              + int(u.get("cache_creation_input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0))
                except (ValueError, AttributeError, TypeError):
                    metered = 0
            snap = meter.settle(st.store, st.settings, cid, purpose, reserved, metered, res.at)
            settled = True
            if resp.status_code == 200:
                _notify_quota(background_tasks, st, row, snap)
            _log(request, resp.status_code, metered, started)
            return Response(content, status_code=resp.status_code, media_type="application/json",
                            headers=_quota_header(request, cid))

        acc = {"in": 0, "out": 0, "cache_creation": 0, "cache_read": 0}
        entered = {"v": False}

        async def relay():
            entered["v"] = True  # a generator body runs on the FIRST iteration: this is the hand-over
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
                    metered = acc["in"] + acc["cache_creation"] + acc["cache_read"] + acc["out"]
                    snap = meter.settle(st.store, st.settings, cid, purpose, reserved, metered, res.at)
                    _log(request, 200, metered, started)
                    _notify_quota_fire_and_forget(st, row, snap)
                finally:
                    await resp.aclose()

        # R3: a StreamingResponse writes its headers before its body and neither Starlette nor
        # uvicorn does response trailers, so the settled figure cannot reach this one. Send the
        # reading the request was ADMITTED on instead — never the inflated reservation, which
        # `plus.note_quota` caches on the add-on as quota the subscriber never spent.
        response = _SettlingStream(
            relay(), media_type="text/event-stream", headers=_quota_header_from(res.before), entered=entered,
            release=lambda: meter.settle(st.store, st.settings, cid, purpose, reserved, 0, res.at),
            aclose=resp.aclose)
        settled = True  # K-267: the RESPONSE owns the settle from here — the relay's own `finally`
        # once it is entered, and `_SettlingStream.__call__` when it never is.
        return response
    finally:
        if not settled:
            meter.settle(st.store, st.settings, cid, purpose, reserved, 0, res.at)
