"""Tests for klausmate.anthropic_client — the Messages API transport.

The SSE sections read RECORDED fixtures (tests/fixtures/anthropic/*.sse)
rather than hand-built event lists: the wire facts this module has to keep
exact — the event names, the delta types, where ``stop_reason`` lives, the
``input:{}`` placeholder the API really does send in a tool_use
``content_block_start`` — are the whole point, and a synthetic event list
only ever pins what the test author already believed. That placeholder is
exactly what the revived code got wrong (see the dropped-stream pin).

The transport sections drive the module's ``_urlopen`` seam instead of a
local http.server: ``consume_sse`` iterates its response line by line, and
a BytesIO splits lines identically to a real HTTPResponse, so the parser
still sees a byte stream rather than a list of events. No network, paid or
otherwise, is touched by this file.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_anthropic_client.py
"""

import email.message
import importlib
import io
import json
import os
import sys
import threading
import urllib.error

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section  # noqa: E402

install()

ac = importlib.import_module("klausmate.anthropic_client")
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "anthropic")


def stream_of(name):
    return io.BytesIO(open(os.path.join(FIX, name), "rb").read())


def sse(*events) -> io.BytesIO:
    """An inline stream, for the shapes no fixture file needs to own."""
    return io.BytesIO(
        b"".join(
            b"event: "
            + str(e.get("type") or "x").encode()
            + b"\ndata: "
            + json.dumps(e).encode()
            + b"\n\n"
            for e in events
        )
    )


section("consume_sse: text")
got = []
r = ac.consume_sse(stream_of("text_turn.sse"), on_text=got.append)
check(
    "text deltas concatenate and stream out in order",
    r["content"] == [{"type": "text", "text": "Hello"}] and got == ["Hel", "lo"],
)
check("stop_reason from message_delta", r["stop_reason"] == "end_turn")
check("text_of joins text blocks only", ac.text_of(r) == "Hello")

section("consume_sse: tool_use")
starts = []
r = ac.consume_sse(stream_of("tool_use_turn.sse"), on_block_start=starts.append)
blk = r["content"][0]
check(
    "tool_use input assembled from partial_json at content_block_stop",
    blk["type"] == "tool_use"
    and blk["name"] == "record_verdicts"
    and blk["input"]
    == {"verdicts": [{"nid": 7, "pertinent": True, "reason": "same mechanism"}]},
)
check("on_block_start saw the tool_use block", starts and starts[0]["type"] == "tool_use")
check("stop_reason tool_use", r["stop_reason"] == "tool_use")
# Revived from a494f2d:tests/test_llm_client.py — the id is what the echoed
# assistant turn is matched against by tool_result.
check("the tool id survives for the echo", blk["id"] == "toolu_1")
check("text_of ignores a tool_use block", ac.text_of(r) == "")

section("consume_sse: dropped stream and cancel")
r = ac.consume_sse(stream_of("dropped_stream.sse"))
try:  # a regression here leaves the API's `"input":{}` placeholder behind,
    # which must read as one FAIL and not take the rest of the file with it
    _nid = r["content"][0]["input"]["verdicts"][0]["nid"]
except (KeyError, IndexError, TypeError):
    _nid = None
check(
    "a dropped stream still finalises tool_use input from the partial JSON",
    _nid == 7 and r["stop_reason"] is None,
)
ev = threading.Event()
ev.set()
r = ac.consume_sse(stream_of("text_turn.sse"), cancel=ev)
check(
    "cancel set before the first line -> stop_reason cancelled, no content",
    r["stop_reason"] == "cancelled" and r["content"] == [],
)
# Revived: a stream cut off mid-argument has no valid JSON to finalise. It
# must still carry an `input` DICT, or the tool-loop echo is malformed.
_half = ac.consume_sse(
    sse(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_2",
                "name": "record_verdicts",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"verdicts":'},
        },
    )
)
check(
    "a TRUNCATED tool_use block degrades to an empty input dict, never a "
    "missing key",
    _half["content"][0].get("input") == {},
)
check(
    "unparseable tool input degrades to {} rather than raising mid-stream",
    ac.consume_sse(
        sse(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "t", "name": "n", "input": {}},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": "{not json"},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        )
    )["content"][0]["input"]
    == {},
)

section("consume_sse: a pre-filled tool_use input survives finalisation")
# A content_block_start whose input already arrived non-empty, with zero
# input_json_delta deltas ever following it: _finalise_tool_input must
# leave it alone instead of joining an empty partial_json list into "" and
# overwriting a real value with {}.
_prefilled_start = {
    "type": "content_block_start",
    "index": 0,
    "content_block": {
        "type": "tool_use",
        "id": "toolu_3",
        "name": "record_verdicts",
        "input": {"already": "complete"},
    },
}
check(
    "content_block_stop with no deltas leaves a pre-filled input untouched",
    ac.consume_sse(
        sse(_prefilled_start, {"type": "content_block_stop", "index": 0})
    )["content"][0]["input"]
    == {"already": "complete"},
)
check(
    "a stream that drops before content_block_stop leaves that same "
    "pre-filled input untouched too (the post-loop finalisation path)",
    ac.consume_sse(sse(_prefilled_start))["content"][0]["input"]
    == {"already": "complete"},
)

section("consume_sse: thinking blocks keep their signature")
_blk = ac.consume_sse(
    sse(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "hmm"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "sig-abc"},
        },
        {"type": "message_stop"},
    )
)["content"][0]
check(
    "the signature is preserved — the API REFUSES an echoed thinking block "
    "without it, so this is load-bearing, not decoration",
    _blk.get("signature") == "sig-abc",
)
check("thinking text accumulates", _blk["thinking"] == "hmm")
check("text_of ignores thinking blocks", ac.text_of({"content": [_blk]}) == "")

section("consume_sse: an error event")
try:
    ac.consume_sse(
        sse({"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    )
    check("an error event raises rather than returning half a message", False)
except ac.LLMError as e:
    check("an error event raises rather than returning half a message", True)
    check("...carrying the provider's own type", e.error_type == "overloaded_error")

section("Client.stream and Client.complete: request shape and key")
calls = []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    calls.append((req.full_url, dict(req.headers), json.loads(req.data)))
    if json.loads(req.data).get("stream"):
        return stream_of("text_turn.sse")
    return _Resp(
        json.dumps(
            {
                "id": "msg_2",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
            }
        ).encode()
    )


ac._urlopen = fake_urlopen
c = ac.Client(lambda: {"api_key_anthropic": "sk-ant-test"})
r = c.stream(
    {
        "model": "claude-sonnet-5",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}],
    }
)
url, headers, body = calls[-1]
check(
    "stream POSTs /v1/messages with x-api-key, anthropic-version and stream:true",
    url == ac.API_BASE + "/v1/messages"
    and headers.get("X-api-key") == "sk-ant-test"
    and headers.get("Anthropic-version") == ac.API_VERSION
    and body["stream"] is True,
)
check("stream returns the consumed blocks", ac.text_of(r) == "Hello")
r2 = c.complete({"model": "claude-sonnet-5", "max_tokens": 64, "messages": []})
check(
    "complete never sets stream and returns the parsed body",
    "stream" not in calls[-1][2]
    and r2["stop_reason"] == "end_turn"
    and ac.text_of(r2) == "done",
)
_before = len(calls)
try:
    ac.Client(lambda: {}).complete({"model": "m", "max_tokens": 1, "messages": []})
    ok = False
except ac.LLMError as e:
    ok = e.status == 401 and "key" in e.user_message().lower()
check("no key → LLMError 401 with a user message, no request", ok and len(calls) == _before)
check(
    "a MISSING key says so, instead of claiming a key was rejected",
    "no anthropic api key" in ac.LLMError(
        "No Anthropic API key set — add it under KlausMate Preferences → "
        "API keys & models.",
        status=401,
        error_type="no_key",
    ).user_message().lower(),
)

section("http failures: statuses, retries, and what the user is told")
http = {"fail_first": 0, "status": 200, "calls": 0}


def _http_error(status, retry_after=None):
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["retry-after"] = retry_after
    return urllib.error.HTTPError(
        ac.API_BASE + "/v1/messages",
        status,
        "err",
        hdrs,
        io.BytesIO(b'{"error":{"type":"authentication_error","message":"nope"}}'),
    )


def flaky_urlopen(req, timeout=None):
    http["calls"] += 1
    if http["fail_first"] > 0:
        http["fail_first"] -= 1
        raise _http_error(429, "0.01")
    if http["status"] != 200:
        # retry-after keeps the retryable branch's sleep out of the suite's
        # wall clock; a non-retryable status never reads it.
        raise _http_error(http["status"], "0.01")
    return stream_of("text_turn.sse")


ac._urlopen = flaky_urlopen
http["status"] = 401
try:
    c.stream({"model": "m", "max_tokens": 1, "messages": []})
    check("a 401 raises", False)
except ac.LLMError as e:
    check(
        "a 401 blames the KEY, which is what the user can fix",
        "key was rejected" in e.user_message(),
    )
check(
    "a non-retryable status costs exactly ONE request — retrying an auth "
    "failure just asks to be refused twice",
    http["calls"] == 1,
)
http["status"] = 200
http["calls"] = 0
http["fail_first"] = 1
seen = []
out = c.stream({"model": "m", "max_tokens": 1, "messages": []}, on_text=seen.append)
check("a 429 is retried and then succeeds", ac.text_of(out) == "Hello")
check("the retry cost exactly one extra request", http["calls"] == 2)
check(
    "no text was replayed — retrying mid-stream would show the user the "
    "same words twice",
    seen == ["Hel", "lo"],
)
http["status"] = 503
http["calls"] = 0
try:
    c.complete({"model": "m", "max_tokens": 1, "messages": []})
    check("a 5xx raises", False)
except ac.LLMError as e:
    check(
        "a 5xx is retried once and then blames the service, not the user",
        http["calls"] == 2 and "overloaded" in e.user_message(),
    )
http["status"] = 200
ac._urlopen = lambda req, timeout=None: _Resp(b"<html>nope")
try:
    c.complete({"model": "m", "max_tokens": 1, "messages": []})
    _bad_json = False
except ac.LLMError as e:
    _bad_json = e.error_type == "protocol"
check("complete raises on a non-JSON body rather than returning junk", _bad_json)

section("wire facts and shape")
_SRC = open("klausmate/anthropic_client.py").read()
_CODE = code_only(_SRC)
check(
    "the Messages endpoint, version and auth header are exact",
    ac.API_BASE == "https://api.anthropic.com"
    and ac.API_VERSION == "2023-06-01"
    and '"x-api-key"' in _SRC
    and "/v1/messages" in _SRC,
)
check(
    "aqt-free — this module is transport, usable from any thread",
    "import aqt" not in _CODE and "from aqt" not in _CODE,
)
check(
    "stdlib only: no SDK can be vendored into an AnkiWeb add-on",
    "anthropic" not in _CODE.replace("anthropic-version", "")
    and "import openai" not in _CODE,
)
# The hosted half of llm_client.py died with the 2026-09-02 convergence and
# must not walk back in with the transport.
check(
    "no hosted backend, flag or chooser came back with the revival",
    "HostedBackend" not in _CODE
    and "HOSTED_API_BASE" not in _CODE
    and "hosted" not in _CODE
    and "backend_from_config" not in _CODE,
)
check(
    "...and no Klaus-run endpoint literal survives either",
    "klausmate.app" not in _SRC,
)
check(
    "the key comes from api_key_anthropic — the retired assistant_* keys "
    "are gone",
    "api_key_anthropic" in _SRC
    and "assistant_api_key" not in _SRC
    and "assistant_token" not in _SRC,
)
check(
    "_open_stream goes through the module-level _urlopen seam, which is "
    "what lets this file run without a network at all",
    "_urlopen(req" in _CODE and "urllib.request.urlopen(req" not in _CODE,
)
check(
    "one SSE parser, used by stream()",
    _CODE.count("def consume_sse") == 1 and _CODE.count("consume_sse(resp") == 1,
)

raise SystemExit(report())
