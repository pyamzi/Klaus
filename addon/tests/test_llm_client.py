"""Tests for llm_client — the streaming transport behind both assistants.

Runs against a real local http.server, repointing API_BASE / HOSTED_API_BASE
the way the klaus-test bootstrap intends. That matters more than usual here:
the SSE parser's job is to survive a real byte stream arriving in arbitrary
chunks, and a hand-fed list of lines would not test that at all.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

lc = importlib.import_module("klausmate.llm_client")

SCRIPT: dict = {"events": [], "status": 200, "fail_first": 0}
SEEN: list = []


def _sse(events) -> bytes:
    return b"".join(
        b"event: x\n" + b"data: " + json.dumps(e).encode() + b"\n\n"
        for e in events
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the test output clean
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        SEEN.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(body or b"{}"),
        })
        if SCRIPT["fail_first"] > 0:
            SCRIPT["fail_first"] -= 1
            self.send_response(429)
            self.send_header("retry-after", "0")
            self.end_headers()
            self.wfile.write(b'{"error":{"type":"rate_limit","message":"slow down"}}')
            return
        if SCRIPT["status"] != 200:
            self.send_response(SCRIPT["status"])
            self.end_headers()
            self.wfile.write(
                b'{"error":{"type":"auth","message":"nope"}}'
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(_sse(SCRIPT["events"]))


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
lc.API_BASE = BASE
lc.HOSTED_API_BASE = BASE

DIRECT = {"assistant_api_key": "sk-test"}
HOSTED = {"assistant_backend": "hosted", "assistant_token": "tok-test"}


def _run(cfg, events, **kw):
    SCRIPT["events"] = events
    SCRIPT["status"] = 200
    SEEN.clear()
    return lc.backend_from_config(lambda: cfg).stream(
        {"model": "m", "messages": []}, **kw
    )


section("text streaming")
_text = [
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": "Incidence "}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": "is new cases."}},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
    {"type": "message_stop"},
]
_seen: list = []
_out = _run(DIRECT, _text, on_text=_seen.append)
check("deltas are assembled in order",
      lc.text_of(_out) == "Incidence is new cases.")
check("on_text fires per delta, so a surface can stream",
      _seen == ["Incidence ", "is new cases."])
check("stop_reason is carried out", _out["stop_reason"] == "end_turn")
check("stream:true is set for the caller — a non-streaming body would hang "
      "the SSE parser", SEEN[0]["body"]["stream"] is True)

section("tool_use blocks are finalized for the echo")
_tool = [
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "tool_use", "id": "t1", "name": "search_notes"}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "input_json_delta", "partial_json": '{"query":'}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "input_json_delta", "partial_json": '"incidence"}'}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_stop"},
]
_starts: list = []
_out = _run(DIRECT, _tool, on_block_start=_starts.append)
_block = _out["content"][0]
check("partial_json fragments are reassembled and parsed",
      _block["input"] == {"query": "incidence"})
check("the tool id and name survive for the echo",
      _block["id"] == "t1" and _block["name"] == "search_notes")
check("on_block_start fires, so a surface can say what is happening",
      len(_starts) == 1 and _starts[0]["type"] == "tool_use")
_bad = list(_tool)
_bad[1] = {"type": "content_block_delta", "index": 0,
           "delta": {"type": "input_json_delta", "partial_json": "{not json"}}
_bad[2] = {"type": "content_block_delta", "index": 0,
           "delta": {"type": "input_json_delta", "partial_json": ""}}
check("unparseable tool input degrades to {} rather than raising mid-stream",
      _run(DIRECT, _bad)["content"][0]["input"] == {})
# A cancelled or dropped stream never sends content_block_stop, which is
# where input is normally finalized.
_cut = _tool[:2]
check("a tool_use block from a TRUNCATED stream still carries an input "
      "dict — the tool-loop echo is malformed without one",
      _run(DIRECT, _cut)["content"][0].get("input") == {})

section("thinking blocks keep their signature")
_think = [
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "thinking", "thinking": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "thinking_delta", "thinking": "hmm"}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "signature_delta", "signature": "sig-abc"}},
    {"type": "message_stop"},
]
_blk = _run(DIRECT, _think)["content"][0]
check("the signature is preserved — the API REFUSES an echoed thinking "
      "block without it, so this is load-bearing, not decoration",
      _blk.get("signature") == "sig-abc")
check("thinking text accumulates", _blk["thinking"] == "hmm")
check("text_of ignores thinking and tool blocks",
      lc.text_of({"content": [_blk]}) == "")

section("cancellation")
_ev = threading.Event(); _ev.set()
_out = _run(DIRECT, _text, cancel=_ev)
check("a set cancel stops the stream", _out["stop_reason"] == "cancelled")

section("errors")
_err = [{"type": "error", "error": {"type": "overloaded", "message": "busy"}}]
try:
    _run(DIRECT, _err)
    check("an error event raises", False)
except lc.LLMError as e:
    check("an error event raises rather than returning half a message", True)
    check("...carrying the provider's own type", e.error_type == "overloaded")

SCRIPT["status"] = 401
SCRIPT["events"] = []
try:
    lc.backend_from_config(lambda: DIRECT).stream({"messages": []})
    check("a 401 raises", False)
except lc.LLMError as e:
    check("a direct 401 blames the KEY, which is what the user can fix",
          "key was rejected" in e.user_message())
try:
    lc.backend_from_config(lambda: HOSTED).stream({"messages": []})
    check("a hosted 401 raises", False)
except lc.LLMError as e:
    check("a hosted 401 blames the SUBSCRIPTION, not a key the user does "
          "not have", "subscription" in e.user_message())
# Retrying a 401 would burn a second request to be told "no" again, and on
# the hosted path would look like a brute-force attempt.
SEEN.clear()
try:
    lc.backend_from_config(lambda: DIRECT).stream({"messages": []})
except lc.LLMError:
    pass
check("a non-retryable status costs exactly ONE request — retrying an auth "
      "failure just asks to be refused twice", len(SEEN) == 1)
SCRIPT["status"] = 200

section("retry happens BEFORE any byte is streamed")
SCRIPT["fail_first"] = 1
_seen2: list = []
_out = _run(DIRECT, _text, on_text=_seen2.append)
SCRIPT["fail_first"] = 0
check("a 429 is retried and then succeeds",
      lc.text_of(_out) == "Incidence is new cases.")
check("the retry cost exactly one extra request", len(SEEN) == 2)
check("no text was replayed — retrying mid-stream would show the user the "
      "same words twice", _seen2 == ["Incidence ", "is new cases."])

section("backend selection")
check("no config at all is the free path", lc.backend_name({}) == "direct")
check("hosted is honoured when a token exists", lc.backend_name(HOSTED) == "hosted")
check("hosted WITHOUT a token falls back to direct — an empty token would "
      "401 every call on a machine with a working key beside it",
      lc.backend_name({"assistant_backend": "hosted"}) == "direct")
check("an unknown backend name is not trusted",
      lc.backend_name({"assistant_backend": "wat"}) == "direct")
check("the backend is chosen per call, so signing in needs no restart",
      lc.backend_from_config(lambda: HOSTED).name == "hosted"
      and lc.backend_from_config(lambda: DIRECT).name == "direct")

section("the hosted path never handles a provider key")
_run(HOSTED, _text)
_h = SEEN[0]["headers"]
check("hosted authenticates with a bearer token", _h.get("authorization") == "Bearer tok-test")
check("...and sends no x-api-key at all", "x-api-key" not in _h)
_mixed = dict(HOSTED); _mixed["assistant_api_key"] = "sk-should-never-be-sent"
_run(_mixed, _text)
check("a key sitting in config is NOT forwarded to the hosted service — a "
      "premium member has no provider key to leak",
      "sk-should-never-be-sent" not in json.dumps(SEEN[0]))
_run(DIRECT, _text)
check("the direct path does send the key, to the provider",
      SEEN[0]["headers"].get("x-api-key") == "sk-test")

section("missing credentials fail before the network")
try:
    lc.backend_from_config(lambda: {}).stream({"messages": []})
    check("no key raises", False)
except lc.LLMError as e:
    check("no key raises with something actionable", e.status == 401)
try:
    lc.HostedBackend(lambda: {}).stream({"messages": []})
    check("no token raises", False)
except lc.LLMError as e:
    check("no token says to sign in", "sign in" in e.user_message().lower()
          or "sign in" in str(e).lower())

section("shape")
_SRC = open("klausmate/llm_client.py").read()
_CODE = code_only(_SRC)
check("aqt-free — the surface is still undecided",
      "import aqt" not in _CODE and "from aqt" not in _CODE)
check("stdlib only: no SDK can be vendored into an AnkiWeb add-on",
      "anthropic" not in _CODE.replace("anthropic-version", "")
      and "import openai" not in _CODE)
check("HostedBackend never reads an api key, pinned in the source too",
      "assistant_api_key" not in _SRC.split("class HostedBackend", 1)[1])
check("one SSE parser serves both backends",
      _CODE.count("def consume_sse") == 1
      and _CODE.count("consume_sse(resp") == 2)

srv.shutdown()
raise SystemExit(report())
