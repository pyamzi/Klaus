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

raise SystemExit(report())
