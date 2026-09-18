"""klaus-core embeddings suite.

No real network calls: the OpenAI HTTP call is faked by swapping
embeddings._urlopen, the same seam openai_client.py used upstream.
Run: python3 tests/test_embeddings.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import urllib.error

os.environ.pop("KLAUS_OPENAI_KEY", None)
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from klaus_core import embeddings  # noqa: E402

failures = 0


def check(label, ok, detail=""):
    global failures
    if ok:
        print("  ok  " + label)
    else:
        failures += 1
        print(" FAIL " + label + ((" " + str(detail)) if detail else ""))


def raises(exc_type, fn):
    try:
        fn()
        return False
    except exc_type:
        return True


class FakeResponse:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status, message="boom"):
    body = json.dumps({"error": {"message": message}}).encode("utf-8")
    return urllib.error.HTTPError("https://api.openai.com/v1/embeddings", status,
                                   "err", {}, io.BytesIO(body))


print("== normalize ==")
n = embeddings.normalize([3.0, 4.0])
check("normalize([3,4]) is [0.6, 0.8]", n is not None and round(n[0], 3) == 0.6 and round(n[1], 3) == 0.8, n)
check("zero vector normalizes to None", embeddings.normalize([0.0, 0.0]) is None)
check("non-finite norm normalizes to None", embeddings.normalize([float("nan")]) is None)

print("== index_signature / signature_matches ==")
cfg = embeddings.default_config()
check("default signature", embeddings.index_signature(cfg) == ("openai", "text-embedding-3-large", 1024))
cfg_ada = {"embedding_model": "text-embedding-ada-002", "embedding_dimensions": 1024}
check("non-Matryoshka model gets dims stripped to 0",
      embeddings.index_signature(cfg_ada) == ("openai", "text-embedding-ada-002", 0))
sig = embeddings.index_signature(cfg)
check("identical signature matches", embeddings.signature_matches("openai", "text-embedding-3-large", 1024, sig))
check("different model does not match", not embeddings.signature_matches("openai", "other-model", 1024, sig))
check("different dims does not match", not embeddings.signature_matches("openai", "text-embedding-3-large", 256, sig))
loose_sig = ("openai", "text-embedding-3-large", 0)
check("dims=0 in signature accepts any stored width",
      embeddings.signature_matches("openai", "text-embedding-3-large", 4096, loose_sig))

print("== embed_batches ==")


class FakeProvider:
    def __init__(self):
        self.calls = []

    def embed(self, texts, kind="document"):
        self.calls.append(list(texts))
        return [[float(i + 1), 0.0] for i in range(len(texts))]


provider = FakeProvider()
batches = list(embeddings.embed_batches(provider, ["a", "b", "c", "d", "e"], batch_size=2))
check("batches split at batch_size", [offset for offset, _ in batches] == [0, 2, 4])
check("provider.embed called once per batch", provider.calls == [["a", "b"], ["c", "d"], ["e"]])
first_vec = batches[0][1][0]
check("vectors come back unit-normalized", first_vec is not None and round(first_vec[0], 3) == 1.0)

cancelled = threading.Event()
cancelled.set()
check("cancel stops before any batch is fetched",
      list(embeddings.embed_batches(FakeProvider(), ["a", "b"], cancel=cancelled)) == [])

print("== OpenAIEmbeddings.embed ==")
check("empty input short-circuits without calling get_config",
      embeddings.OpenAIEmbeddings(lambda: (_ for _ in ()).throw(AssertionError("called"))).embed([]) == [])

missing_key = embeddings.OpenAIEmbeddings(lambda: {"api_key_openai": ""})
err = None
try:
    missing_key.embed(["hi"])
except embeddings.EmbeddingError as e:
    err = e
check("missing API key raises EmbeddingError(401)", err is not None and err.status == 401)
check("missing-key message names KLAUS_OPENAI_KEY", "KLAUS_OPENAI_KEY" in str(err))

orig_urlopen = embeddings._urlopen
orig_sleep = embeddings._sleep
try:
    captured = {}

    def fake_urlopen_ok(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["auth"] = req.headers.get("Authorization")
        return FakeResponse({"data": [
            {"index": 0, "embedding": [1.0, 2.0, 3.0]},
            {"index": 1, "embedding": [4.0, 5.0, 6.0]},
        ]})

    embeddings._urlopen = fake_urlopen_ok
    provider2 = embeddings.OpenAIEmbeddings(lambda: {
        "api_key_openai": "sk-test",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 8,
    })
    vectors = provider2.embed(["a", "b"])
    check("embed() returns vectors in index order", vectors == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    check("request carries the bearer key", captured.get("auth") == "Bearer sk-test")
    check("dimension-capable model sends `dimensions`", captured.get("body", {}).get("dimensions") == 8)

    def fake_urlopen_401(req, timeout=None):
        raise http_error(401, "invalid key")

    embeddings._urlopen = fake_urlopen_401
    err2 = None
    try:
        provider2.embed(["a"])
    except embeddings.EmbeddingError as e:
        err2 = e
    check("HTTP 401 wraps into EmbeddingError", err2 is not None and err2.status == 401 and "invalid key" in str(err2))

    attempts = {"n": 0}

    def fake_urlopen_retry(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise http_error(429, "slow down")
        return FakeResponse({"data": [{"index": 0, "embedding": [1.0]}]})

    embeddings._urlopen = fake_urlopen_retry
    embeddings._sleep = lambda s: None
    result = provider2.embed(["a"])
    check("429 is retried once and then succeeds", attempts["n"] == 2 and result == [[1.0]])
finally:
    embeddings._urlopen = orig_urlopen
    embeddings._sleep = orig_sleep

print("== EmbeddingError.user_message ==")
check("401 mentions the API key",
      "KLAUS_OPENAI_KEY" in embeddings.EmbeddingError("x", provider="OpenAI", status=401).user_message())
check("429 mentions rate limiting",
      "rate-limited" in embeddings.EmbeddingError("x", provider="OpenAI", status=429, retry_after=5).user_message())
check("5xx mentions overloaded",
      "overloaded" in embeddings.EmbeddingError("x", provider="OpenAI", status=503).user_message())
check("no status falls back to the raw message",
      embeddings.EmbeddingError("just the message").user_message() == "just the message")
check("402 mentions quota and the OpenAI-key fallback",
      "quota" in embeddings.EmbeddingError("x", provider="Klaus Plus", status=402).user_message()
      and "KLAUS_OPENAI_KEY" in embeddings.EmbeddingError("x", provider="Klaus Plus", status=402).user_message())
check("426 mentions updating",
      "update" in embeddings.EmbeddingError("x", provider="Klaus Plus", status=426).user_message())
check("Klaus Plus 401 names KLAUS_PLUS_KEY, not the OpenAI var",
      "KLAUS_PLUS_KEY" in embeddings.EmbeddingError("x", provider="Klaus Plus", status=401).user_message())

print("== plus_key / plus_base ==")
GOOD_PLUS_KEY = "kp_" + "a" * 32
check("well-formed key accepted", embeddings.plus_key({"plus_key": GOOD_PLUS_KEY}) == GOOD_PLUS_KEY)
check("missing key reads as empty", embeddings.plus_key({}) == "")
check("wrong prefix rejected", embeddings.plus_key({"plus_key": "xx_" + "a" * 32}) == "")
check("wrong length rejected", embeddings.plus_key({"plus_key": "kp_" + "a" * 31}) == "")
check("uppercase hex rejected", embeddings.plus_key({"plus_key": "kp_" + "A" * 32}) == "")
check("default base is klausmate.com", embeddings.plus_base({}) == "https://klausmate.com")
check("configured base overrides, trailing slash stripped",
      embeddings.plus_base({"plus_base": "https://example.test/"}) == "https://example.test")

print("== config_from_header (KB-022: the klaus-pdf extension's per-request key) ==")
os.environ.pop("KLAUS_PLUS_KEY", None)
check("no header falls through to default_config() unchanged",
      embeddings.config_from_header(None) == embeddings.default_config())
check("a header overlays plus_key onto the env-var defaults, nothing else",
      embeddings.config_from_header(GOOD_PLUS_KEY) == {**embeddings.default_config(), "plus_key": GOOD_PLUS_KEY})
check("the overlaid config round-trips through plus_key() same as any other",
      embeddings.plus_key(embeddings.config_from_header(GOOD_PLUS_KEY)) == GOOD_PLUS_KEY)
check("an empty header string is treated as absent, not as an empty key",
      embeddings.config_from_header("") == embeddings.default_config())

print("== OpenAIEmbeddings.embed routes through Klaus Plus when a key is set ==")
orig_urlopen = embeddings._urlopen
try:
    captured = {}

    def fake_plus_ok(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        captured["purpose"] = req.headers.get("X-klaus-purpose")  # urllib lower-cases header keys
        captured["client"] = req.headers.get("X-klaus-client")
        return FakeResponse({"data": [{"index": 0, "embedding": [1.0]}]})

    embeddings._urlopen = fake_plus_ok
    plus_provider = embeddings.OpenAIEmbeddings(lambda: {
        "plus_key": GOOD_PLUS_KEY, "api_key_openai": "sk-should-not-be-used",
    })
    vectors = plus_provider.embed(["a"])
    check("Plus-routed embed() returns the vector", vectors == [[1.0]])
    check("posts to klausmate.com/v1/embeddings", captured.get("url") == "https://klausmate.com/v1/embeddings")
    check("carries the Plus bearer key", captured.get("auth") == f"Bearer {GOOD_PLUS_KEY}")
    check("X-Klaus-Purpose is embed", captured.get("purpose") == "embed")
    check("X-Klaus-Client is klaus_core's own version", captured.get("client") == embeddings.__version__)

    def fake_plus_401(req, timeout=None):
        raise http_error(401, "bad key")

    embeddings._urlopen = fake_plus_401
    err3 = None
    try:
        plus_provider.embed(["a"])
    except embeddings.EmbeddingError as e:
        err3 = e
    check("a rejected Plus key raises with provider=Klaus Plus",
          err3 is not None and err3.provider == "Klaus Plus" and err3.status == 401)

    check("a malformed Plus key falls through to the OpenAI path, not a doomed Plus request",
          embeddings.plus_key({"plus_key": "not-a-real-key", "api_key_openai": ""}) == "")
    fallback_provider = embeddings.OpenAIEmbeddings(lambda: {
        "plus_key": "not-a-real-key", "api_key_openai": "",
    })
    err4 = None
    try:
        fallback_provider.embed(["a"])
    except embeddings.EmbeddingError as e:
        err4 = e
    check("malformed Plus key + no OpenAI key -> the no-key error, not a network call",
          err4 is not None and err4.status == 401 and "KLAUS_PLUS_KEY" in str(err4))
finally:
    embeddings._urlopen = orig_urlopen

print("\n%d failures" % failures)
sys.exit(1 if failures else 0)
