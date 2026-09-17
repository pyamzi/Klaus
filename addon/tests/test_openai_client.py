"""Tests for klausmate.openai_client (API-first plan, Task 2).

Covers: embeddings (bearer auth, model/input/dimensions body, dims=0 omits
the field, empty input short-circuits with no request, response vectors
reordered by index regardless of wire order), audio transcription
(multipart body: file/model/response_format/language/prompt, stripped
response text), and error handling (401 -> OpenAIError.user_message()
about the key, 429 retries once then succeeds). A fake `_urlopen` records
every request and returns canned bodies, so no network call is ever made.

Run: python3 tests/test_openai_client.py
"""

import contextlib
import importlib
import io
import json
import sys
import urllib.error

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

oc = importlib.import_module("klausmate.openai_client")


class _Resp(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers if headers is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


calls = []


def fake_urlopen(req, timeout=None):
    calls.append((req.full_url, dict(req.headers), req.data, timeout))
    if req.full_url.endswith("/embeddings"):
        body = json.loads(req.data)
        n = len(body["input"])
        return _Resp(json.dumps(
            {"data": [{"index": i, "embedding": [float(i), 0.0]} for i in reversed(range(n))]}
        ).encode())
    if req.full_url.endswith("/audio/transcriptions"):
        return _Resp(json.dumps({"text": "  hello lecture  "}).encode())
    raise AssertionError(req.full_url)


oc._urlopen = fake_urlopen

section("embed")
vecs = oc.embed("sk-test", ["a", "b"], "text-embedding-3-large", 1024)
url, headers, data, timeout = calls[-1]
body = json.loads(data)
check("POSTs to /v1/embeddings with bearer auth, model, dimensions",
      url == "https://api.openai.com/v1/embeddings" and headers.get("Authorization") == "Bearer sk-test"
      and body == {"model": "text-embedding-3-large", "input": ["a", "b"], "dimensions": 1024})
check("vectors come back in INPUT order regardless of response order",
      vecs == [[0.0, 0.0], [1.0, 0.0]] and len(vecs) == 2)
check("dims=0 omits the dimensions field",
      (oc.embed("k", ["a"], "m", 0), "dimensions" not in json.loads(calls[-1][2]))[1])
check("empty input → [] and no request",
      oc.embed("k", [], "m", 0) == [] and calls[-1][0].endswith("/embeddings"))

section("transcribe")
wav = b"RIFF....WAVEfmt fake"
text = oc.transcribe("sk-test", wav, "gpt-4o-mini-transcribe", language="en", prompt="previous words")
url, headers, data, timeout = calls[-1]
ct = headers.get("Content-type") or headers.get("Content-Type")
check("POSTs multipart to /v1/audio/transcriptions",
      url == "https://api.openai.com/v1/audio/transcriptions" and ct.startswith("multipart/form-data; boundary="))
boundary = ct.split("boundary=")[1].encode()
check("multipart carries file, model, response_format=json, language, prompt, and the wav bytes",
      data.count(b"--" + boundary) >= 6 and b'name="file"; filename="chunk.wav"' in data
      and b"Content-Type: audio/wav" in data
      and b'name="model"\r\n\r\ngpt-4o-mini-transcribe' in data
      and b'name="response_format"\r\n\r\njson' in data
      and b'name="language"\r\n\r\nen' in data
      and b'name="prompt"\r\n\r\nprevious words' in data
      and wav in data)
check("returns the stripped text", text == "hello lecture")

section("an Endpoint replaces the provider: base URL and headers")
calls.clear()
from klausmate import plus as _plus
ep = _plus.Endpoint("https://svc.test", {"Authorization": "Bearer kp_" + "d" * 32, "X-Klaus-Purpose": "embed", "X-Klaus-Client": "0.2.0"})
vecs = oc.embed("", ["a"], "text-embedding-3-large", 1024, endpoint=ep)
url, headers, data, _ = calls[-1]
check("the endpoint's base and headers are used, no provider key needed",
      url == "https://svc.test/v1/embeddings" and headers.get("Authorization") == "Bearer kp_" + "d" * 32
      and headers.get("X-klaus-purpose", headers.get("X-Klaus-Purpose")) == "embed" and len(vecs) == 1)
check("the default endpoint is still the provider", oc.API_BASE == "https://api.openai.com/v1")
ep_t = _plus.Endpoint("https://svc.test", {"Authorization": "Bearer kp_" + "d" * 32, "X-Klaus-Purpose": "transcribe", "X-Klaus-Client": "0.2.0"})
text = oc.transcribe("", b"RIFF", "gpt-4o-mini-transcribe", endpoint=ep_t)
url, headers, _, _ = calls[-1]
check("transcribe routes to the service's /v1/audio/transcriptions with the endpoint's headers",
      url == "https://svc.test/v1/audio/transcriptions" and headers.get("Authorization") == "Bearer kp_" + "d" * 32
      and text == "hello lecture")

section("the service's error message reaches the user")


def quota_urlopen(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 402, "quota", {}, io.BytesIO(json.dumps({"error": {"message": "used up; resets on 2026-10-01"}}).encode()))


oc._urlopen = quota_urlopen
try:
    oc.embed("", ["a"], "m", 0, endpoint=ep)
    check("402 raises OpenAIError", False)
except oc.OpenAIError as e:
    check("402 raises OpenAIError carrying the service's message verbatim", e.status == 402 and e.user_message() == "used up; resets on 2026-10-01")


def maintenance_urlopen(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 503, "maintenance", {}, io.BytesIO(json.dumps(
        {"error": {"message": "Klaus Plus is paused for maintenance — try again later, or use your own API key."}}).encode()))


oc._urlopen = maintenance_urlopen
try:
    oc.embed("", ["a"], "m", 0, endpoint=ep)
    check("503 raises OpenAIError", False)
except oc.OpenAIError as e:
    check("503 raises OpenAIError carrying the service's message verbatim too, not 'OpenAI is overloaded'",
          e.status == 503 and e.user_message() == "Klaus Plus is paused for maintenance — try again later, or use your own API key.")
oc._urlopen = fake_urlopen

section("errors")


def err_urlopen(req, timeout=None):
    raise urllib.error.HTTPError(
        req.full_url, 401, "Unauthorized", {"retry-after": "0"},
        io.BytesIO(b'{"error":{"message":"bad key"}}'))


oc._urlopen = err_urlopen
try:
    oc.embed("bad", ["a"], "m", 0)
    ok = False
except oc.OpenAIError as e:
    ok = e.status == 401 and "key" in e.user_message().lower()
check("401 → OpenAIError with a user_message about the key", ok)

attempts = []


def flaky(req, timeout=None):
    attempts.append(1)
    if len(attempts) == 1:
        raise urllib.error.HTTPError(req.full_url, 429, "rate", {"retry-after": "0"}, io.BytesIO(b"{}"))
    return _Resp(json.dumps({"data": [{"index": 0, "embedding": [1.0]}]}).encode())


oc._urlopen = flaky
oc._SLEEP = lambda s: None
check("429 retries once and succeeds",
      oc.embed("k", ["a"], "m", 0) == [[1.0]] and len(attempts) == 2)

section("on_headers: the response headers reach the callback on success, never on error")
seen = []


def headers_urlopen(req, timeout=None):
    if req.full_url.endswith("/embeddings"):
        return _Resp(json.dumps({"data": [{"index": 0, "embedding": [1.0]}]}).encode(),
                     headers={"X-Klaus-Quota": "embed-quota"})
    if req.full_url.endswith("/audio/transcriptions"):
        return _Resp(json.dumps({"text": "hi"}).encode(), headers={"X-Klaus-Quota": "transcribe-quota"})
    raise AssertionError(req.full_url)


oc._urlopen = headers_urlopen
oc.embed("k", ["a"], "m", 0, on_headers=seen.append)
check("embed hands the response headers to on_headers on a 2xx",
      len(seen) == 1 and seen[0].get("X-Klaus-Quota") == "embed-quota")
seen.clear()
oc.transcribe("k", b"wav", "m", on_headers=seen.append)
check("transcribe hands the response headers to on_headers on a 2xx",
      len(seen) == 1 and seen[0].get("X-Klaus-Quota") == "transcribe-quota")
seen.clear()


def error_urlopen(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":{"message":"bad key"}}'))


oc._urlopen = error_urlopen
try:
    oc.embed("bad", ["a"], "m", 0, on_headers=seen.append)
except oc.OpenAIError:
    pass
try:
    oc.transcribe("bad", b"wav", "m", on_headers=seen.append)
except oc.OpenAIError:
    pass
check("on_headers is never called on an error (embed or transcribe)", seen == [])

section("on_headers: a raising callback never breaks the call")


def boom_headers(_headers):
    raise ValueError("boom")


oc._urlopen = headers_urlopen
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    vecs = oc.embed("k", ["a"], "m", 0, on_headers=boom_headers)
check("a raising on_headers still yields the parsed embeddings", vecs == [[1.0]])
check("...and logs exactly one [klausmate] line naming only the exception class",
      buf.getvalue().count("[klausmate]") == 1 and "ValueError" in buf.getvalue()
      and "boom" not in buf.getvalue())

buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    text = oc.transcribe("k", b"wav", "m", on_headers=boom_headers)
check("a raising on_headers still yields the transcribed text", text == "hi")
check("...and logs exactly one [klausmate] line naming only the exception class",
      buf2.getvalue().count("[klausmate]") == 1 and "ValueError" in buf2.getvalue()
      and "boom" not in buf2.getvalue())

section("on_headers: called exactly once through a 429-then-200 retry")
retry_hits = []


def flaky_headers(req, timeout=None):
    retry_hits.append(1)
    if len(retry_hits) == 1:
        raise urllib.error.HTTPError(req.full_url, 429, "rate", {"retry-after": "0"}, io.BytesIO(b"{}"))
    return _Resp(json.dumps({"data": [{"index": 0, "embedding": [1.0]}]}).encode(),
                 headers={"X-Klaus-Quota": "retry-ok"})


oc._urlopen = flaky_headers
oc._SLEEP = lambda s: None
seen = []
result = oc.embed("k", ["a"], "m", 0, on_headers=seen.append)
check("a 429-then-200 retry calls on_headers exactly once, for the eventual 2xx only",
      result == [[1.0]] and len(seen) == 1 and seen[0].get("X-Klaus-Quota") == "retry-ok"
      and len(retry_hits) == 2)

raise SystemExit(report())
