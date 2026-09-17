"""The lecture recorder (K-256, Plan 2 Task 4): Chunker, wav_bytes,
chunk_path, and the Uploader daemon worker.

Only the PURE half (above lecture_recorder.py's own "Qt glue" divider) is
exercised here — the brief scopes the Recorder's real QAudioSource/QTimer
behaviour to a separate offscreen task (Task 5), so this file never opens
a real microphone. It DOES construct bare `Recorder` instances and drive
their internals directly (`_flush`, `stop`, `start`'s early-return guard)
where fix round 1 needs headless coverage of Qt-adjacent logic that
doesn't actually touch PyQt6.

Step 1's pinned block (Chunker/wav_bytes/chunk_path/Uploader) is kept
verbatim from task-4-brief.md, with ONE authorized insertion (fix round
1, f2: seeding real page text before the first enqueue). Everything else
before and after it is this task's own addition. Sections are grouped and
labelled by what they cover:

  - the original dispatch's own additions (Klaus Plus routing/quota/
    refusal, the no-key gate, the PyQt6-blocked import check);
  - "Fix round 1" sections, one per item in task-4-review.md's Quality
    verdict (C1, I1, I2, I3, f1, f2) plus the minors folded in by the
    coordinator (m1-m5, FIFO order, a foreign leftover file, the 800-char
    prompt cap).
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import struct
import sys
import tempfile
import threading
import time

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"),
)

from anki_stubs import install, check, report, section  # noqa: E402

install()

# ---------------------------------------------------------------------
# The core must import without PyQt6 at module load time. PyQt6 IS
# installed for this machine's system python3 (see the klaus-test
# skill), so a plain import would silently pass even if the module put a
# `from PyQt6...` at its top — block it in sys.modules first so this is a
# real negative test, not a no-op.
# ---------------------------------------------------------------------
section("the core imports with no PyQt6 available (Qt glue is deferred into Recorder.start())")
sys.modules["PyQt6"] = None  # type: ignore[assignment]
try:
    importlib.import_module("klausmate.lecture_recorder")
    check("klausmate.lecture_recorder imports cleanly with PyQt6 blocked", True)
except Exception as exc:
    check("klausmate.lecture_recorder imports cleanly with PyQt6 blocked", False, repr(exc))
finally:
    del sys.modules["PyQt6"]

lr = importlib.import_module("klausmate.lecture_recorder")
page_store = importlib.import_module("klausmate.page_store")


def _wait_idle(up, timeout: float = 2.0) -> bool:
    """Test helper standing in for `up.drain()` when the code under test
    might hang the whole suite (fix round 1, C1's pre-fix behaviour):
    polls the queue's own unfinished-task count instead of blocking on
    it, so a stuck worker shows up as 'False' instead of a hang."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if up._q.unfinished_tasks == 0:
            return True
        time.sleep(0.02)
    return up._q.unfinished_tasks == 0


def _returns_within(fn, timeout: float = 2.0) -> bool:
    """True iff the zero-arg callable `fn` returns within `timeout`
    seconds. Runs it on a daemon thread so a call that never returns
    (the exact C1 bug) cannot hang this test file — the stuck thread is
    simply leaked, harmlessly, until the process exits."""
    done = threading.Event()
    def _runner():
        try:
            fn()
        finally:
            done.set()
    threading.Thread(target=_runner, daemon=True).start()
    return done.wait(timeout)


class _FakeIO:
    """Stands in for the QIODevice `Recorder._io` holds, for tests that
    drive `_tick`/`stop` without a real QAudioSource."""
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readAll(self):
        return self._data


def _load_wav_seconds():
    """Lift `wav_seconds` verbatim (by AST, not retyped) from the Klaus
    Plus service so the I3 pin proves interop with the REAL metering
    code, not a reimplementation of its formula that could drift from
    it. service/ is never imported as a package (heavy FastAPI deps,
    and it must never ship in the add-on) — just this one pure function,
    executed in an isolated namespace."""
    proxy_path = os.path.join(os.path.dirname(__file__), "..", "service", "klausplus", "proxy.py")
    src = open(proxy_path, encoding="utf-8").read()
    tree = ast.parse(src)
    fn_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "wav_seconds")
    fn_src = ast.get_source_segment(src, fn_node)
    ns: dict = {"struct": struct}
    exec(compile(fn_src, "<wav_seconds>", "exec"), ns)  # noqa: S102 -- test-only, our own source file
    return ns["wav_seconds"]


wav_seconds = _load_wav_seconds()

section("Chunker: 30 s cap, page change closes early, no straddle")
c = lr.Chunker()
c.start(page=3, t=100.0)
check("no chunk before 30 s", c.tick(120.0) is None and c.active and c.page == 3)
ch = c.tick(130.0)
check("closes at exactly CHUNK_S with the page it opened on", ch == lr.Chunk(3, 100.0, 130.0) and c.t0 == 130.0)
ch = c.page_changed(4, 140.0)
check("a page change closes the open chunk on the OLD page and reopens on the new", ch == lr.Chunk(3, 130.0, 140.0) and c.page == 4 and c.t0 == 140.0)
check("page_changed to the same page is a no-op", c.page_changed(4, 141.0) is None and c.t0 == 140.0)
ch = c.stop(150.0)
check("stop closes the last chunk; a stopped chunker emits nothing", ch == lr.Chunk(4, 140.0, 150.0) and not c.active and c.tick(200.0) is None)
c2 = lr.Chunker(); c2.start(1, 0.0)
check("a zero-length chunk is never emitted", c2.page_changed(2, 0.0) is None and c2.page == 2)

# ---------------------------------------------------------------------
# Fix round 1, I2: tick must close at the ACTUAL tick time, not an
# idealized t0+CHUNK_S boundary, so the stored [t0,t1] always matches the
# audio the WAV actually holds (a late tick after a stall must not
# silently mislabel a long chunk as a clean 30s one).
# ---------------------------------------------------------------------
section("I2: tick closes at the actual tick time, not an idealized boundary")
c3 = lr.Chunker(); c3.start(3, 100.0)
ch3 = c3.tick(131.0)
check("a late tick (100.0 -> 131.0) closes at the ACTUAL time 131.0, not the ideal 130.0 boundary",
      ch3 == lr.Chunk(3, 100.0, 131.0) and c3.t0 == 131.0)

section("wav_bytes")
w = lr.wav_bytes(b"\x00\x00" * 160, 16000)
check("RIFF/WAVE 16 kHz mono int16", w[:4] == b"RIFF" and w[8:12] == b"WAVE" and len(w) == 44 + 320)
import wave, io
with wave.open(io.BytesIO(w)) as wf:
    check("header fields", wf.getframerate() == 16000 and wf.getnchannels() == 1 and wf.getsampwidth() == 2 and wf.getnframes() == 160)

# ---------------------------------------------------------------------
# Fix round 1, I3 (the headless-pinnable half): wav_bytes must accept and
# honour the NEGOTIATED rate/channels/width, and the header it writes
# must be exactly what the Klaus Plus service's OWN wav_seconds (lifted
# above) reads back — proving the two sides agree on what the bytes mean,
# not just that wav_bytes runs.
# ---------------------------------------------------------------------
section("I3: wav_bytes honours negotiated rate/channels/width (the service's own wav_seconds agrees)")
neg_rate, neg_channels, neg_width = 48000, 2, 2
neg_frames = neg_rate // 2  # 0.5 s of audio
neg_pcm = b"\x00" * (neg_frames * neg_channels * neg_width)
w48 = lr.wav_bytes(neg_pcm, rate=neg_rate, channels=neg_channels, width=neg_width)
check("a non-default rate/channels/width header round-trips through the service's wav_seconds as 0.5s",
      abs(wav_seconds(w48) - 0.5) < 1e-9)
w_default = lr.wav_bytes(b"\x00\x00" * 16000)  # unchanged callers still get the old 16kHz mono default
check("callers that pass only pcm/rate still get mono 16-bit (unchanged default)",
      abs(wav_seconds(w_default) - 1.0) < 1e-9)

section("chunk_path and the uploader")
root = tempfile.mkdtemp()
p = lr.chunk_path(root, "lec", lr.Chunk(3, 100.0, 130.0))
check("recordings/<safe>/<t0>-p<page:04d>.wav", p.endswith(os.path.join("recordings", "lec", "100-p0003.wav")))
segs = []
calls = []
def fake_transcribe(key, wav, model, language="en", prompt="", timeout=None):
    calls.append((key, model, prompt)); return "hello" if b"OK" in wav else ""
lr._transcribe = fake_transcribe
up = lr.Uploader(root, lambda: {"api_key_openai": "k", "transcription_model": "gpt-4o-mini-transcribe"}, on_segment=lambda safe, page: segs.append((safe, page)))
# Fix round 1 (f2): seed real page text BEFORE the first enqueue, so the
# ensure_records section below can assert on ACTUAL slide_text and the
# TEXT digest, not merely "a pointer file exists" -- which page_store's
# own legacy-directory adoption can create on its own, with no seeding
# at all (the vacuous version the review's mutation M4 exposed).
lec_pages = ["Page 1 slide text.", "Page 2 slide text.",
            "Page 3 slide text -- the one this recording covers."]
os.makedirs(os.path.join(root, "contexts"), exist_ok=True)
with open(os.path.join(root, "contexts", "lec.json"), "w", encoding="utf-8") as f:
    json.dump({"pages": lec_pages}, f)
os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b"RIFF OK")
up.enqueue("lec", os.path.join(root, "lec.pdf"), lr.Chunk(3, 100.0, 130.0), p); up.drain()
check("a chunk transcribes, lands on page index 2 (page 3 is 1-based), and its WAV is deleted",
      segs == [("lec", 2)] and not os.path.exists(p) and calls[-1][1] == "gpt-4o-mini-transcribe")
p2 = lr.chunk_path(root, "lec", lr.Chunk(3, 130.0, 160.0)); open(p2, "wb").write(b"RIFF silence")
up.enqueue("lec", os.path.join(root, "lec.pdf"), lr.Chunk(3, 130.0, 160.0), p2); up.drain()
check("an empty transcript is dropped and the WAV still deleted", len(segs) == 1 and not os.path.exists(p2))
def boom(*a, **k): raise lr.openai_client.OpenAIError("down", status=500)
lr._transcribe = boom
p3 = lr.chunk_path(root, "lec", lr.Chunk(4, 160.0, 190.0)); open(p3, "wb").write(b"RIFF OK")
up.enqueue("lec", os.path.join(root, "lec.pdf"), lr.Chunk(4, 160.0, 190.0), p3); up.drain()
check("a failed upload keeps the WAV for the next Record", os.path.exists(p3))
lr._transcribe = fake_transcribe
n = up.requeue_leftovers("lec", os.path.join(root, "lec.pdf")); up.drain()
check("requeue_leftovers picks the leftover up by its filename (page and t0) and transcribes it", n == 1 and segs[-1] == ("lec", 3) and not os.path.exists(p3))
check("the prompt to the API is the previous segment's text (continuity), capped", calls[-1][2] == "hello")

# ---------------------------------------------------------------------
# Fix round 1, f2: the STRONG ensure_records pin (replaces the vacuous
# "a pointer file exists" check the review's mutation M4 survived).
# ---------------------------------------------------------------------
section("f2: ensure_records seeds real slide_text and keys the pointer on the TEXT digest")
seeded_rec = page_store.load_record(root, "lec", os.path.join(root, "lec.pdf"), 2)
check("page 3's slide_text was seeded from contexts/lec.json before the first segment ever landed",
      seeded_rec["slide_text"] == lec_pages[2])
lec_pointer_path = os.path.join(root, "pages", "lec", "current")
check("the pointer is keyed on the TEXT digest (page_store.text_digest), not a legacy path digest",
      os.path.isfile(lec_pointer_path)
      and open(lec_pointer_path, encoding="utf-8").read().strip() == page_store.text_digest(lec_pages))

# ---------------------------------------------------------------------
# Klaus Plus: no provider key, routed through plus.endpoint, quota noted.
# Fix round 1, f1: plus_cfg now carries a REAL api_key_openai, so
# "key == ''" actually proves the Plus branch never reads it (the
# review's mutation M3 -- pass key through -- survived the old version,
# which had no api_key_openai to read in the first place).
# ---------------------------------------------------------------------
section("Klaus Plus: no provider key, routed through plus.endpoint, quota noted")
pkg_mod = sys.modules["klausmate"]
patches = []
pkg_mod.patch_config = lambda updates: patches.append(updates)

plus_calls = []
def fake_transcribe_plus(key, wav, model, language="en", prompt="", timeout=None, endpoint=None, on_headers=None, **kw):
    plus_calls.append({"key": key, "prompt": prompt, "endpoint": endpoint})
    if on_headers:
        on_headers({"X-Klaus-Quota": json.dumps({"human": {"lecture_hours": [1, 30]}})})
    return "plus transcript"
lr._transcribe = fake_transcribe_plus

plus_cfg = {"klaus_plus_key": "kp_" + "z" * 32, "transcription_model": "gpt-4o-mini-transcribe",
           "api_key_openai": "sk-must-not-be-used"}
plus_segs = []
plus_up = lr.Uploader(root, lambda: plus_cfg, on_segment=lambda safe, page: plus_segs.append((safe, page)))
p4 = lr.chunk_path(root, "lec2", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(p4), exist_ok=True); open(p4, "wb").write(b"anything")
plus_up.enqueue("lec2", os.path.join(root, "lec2.pdf"), lr.Chunk(1, 0.0, 30.0), p4); plus_up.drain()
check("on Plus the call carries no provider key -- api_key_openai is present in cfg but never read",
      bool(plus_calls) and plus_calls[-1]["key"] == "" and plus_calls[-1]["endpoint"] == lr.plus.endpoint(plus_cfg, "transcribe"))
check("the segment still lands (page index 0) and the WAV is deleted", plus_segs == [("lec2", 0)] and not os.path.exists(p4))
check("a metered call's quota header is noted as an active verdict via patch_config (never write_config)",
      bool(patches) and patches[-1].get(lr.plus.CACHE, {}).get("status") == "active"
      and set(patches[-1].keys()) == {lr.plus.CACHE})

section("Klaus Plus: a 402 refusal is remembered and the WAV is kept")
def fake_transcribe_402(key, wav, model, language="en", prompt="", timeout=None, endpoint=None, on_headers=None, **kw):
    raise lr.openai_client.OpenAIError("Klaus Plus: quota used up for this period", status=402)
lr._transcribe = fake_transcribe_402
patches.clear()
p6 = lr.chunk_path(root, "lec4", lr.Chunk(2, 0.0, 30.0))
os.makedirs(os.path.dirname(p6), exist_ok=True); open(p6, "wb").write(b"x")
plus_up.enqueue("lec4", os.path.join(root, "lec4.pdf"), lr.Chunk(2, 0.0, 30.0), p6); plus_up.drain()
check("a 402 on Plus is remembered via patch_config with status refused:402",
      os.path.exists(p6) and bool(patches) and patches[-1].get(lr.plus.CACHE, {}).get("status") == "refused:402")

del pkg_mod.patch_config

section("no OpenAI key and no Klaus Plus: logs once, never calls transcribe, keeps the WAV")
gate_calls = []
def transcribe_should_not_run(*a, **k):
    gate_calls.append((a, k))
    raise AssertionError("transcribe must not be called with no key and no Plus")
lr._transcribe = transcribe_should_not_run
gate_up = lr.Uploader(root, lambda: {}, on_segment=lambda *a: gate_calls.append(("on_segment", a)))
p7 = lr.chunk_path(root, "lec5", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(p7), exist_ok=True); open(p7, "wb").write(b"x")
gate_up.enqueue("lec5", os.path.join(root, "lec5.pdf"), lr.Chunk(1, 0.0, 30.0), p7); gate_up.drain()
check("the WAV is kept and transcribe/on_segment are never reached", os.path.exists(p7) and gate_calls == [])

# =======================================================================
# Fix round 1 -- items from task-4-review.md's Quality verdict, folded in
# by the coordinator.
# =======================================================================

# ---------------------------------------------------------------------
# C1: the worker loop survives an on_segment that raises (the next chunk
# still transcribes), and both a normal item and the stop() sentinel
# always get task_done() -- so drain() (and a later enqueue) never hang.
# ---------------------------------------------------------------------
section("C1: the worker survives an on_segment that raises; the next chunk still transcribes")
c1_events = []
def on_segment_ok(safe, page):
    c1_events.append(("B", safe, page))
def on_segment_first_raises(safe, page):
    # Swaps itself out on the FIRST call so exactly one chunk raises,
    # with no race against the main thread enqueueing the second chunk.
    c1_events.append(("A", safe, page))
    c1_up._on_segment = on_segment_ok
    raise RuntimeError("boom from on_segment")

lr._transcribe = lambda key, wav, model, language="en", prompt="", timeout=None: "seg text"
c1_up = lr.Uploader(root, lambda: {"api_key_openai": "k"}, on_segment=on_segment_first_raises)
pA = lr.chunk_path(root, "c1test", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(pA), exist_ok=True); open(pA, "wb").write(b"A")
c1_up.enqueue("c1test", os.path.join(root, "c1test.pdf"), lr.Chunk(1, 0.0, 30.0), pA)
pB = lr.chunk_path(root, "c1test", lr.Chunk(1, 30.0, 60.0))
open(pB, "wb").write(b"B")
c1_up.enqueue("c1test", os.path.join(root, "c1test.pdf"), lr.Chunk(1, 30.0, 60.0), pB)
idle = _wait_idle(c1_up, timeout=2.0)
check("the queue idles within 2s instead of hanging forever (task_done in a finally)", idle)
check("the SECOND chunk still transcribed after the first chunk's on_segment raised",
      ("B", "c1test", 0) in c1_events)
check("drain() itself returns promptly (not just the queue idling)", _returns_within(c1_up.drain, 2.0))

section("C1: the stop() sentinel gets task_done() too, so a later enqueue restarts cleanly")
lr._transcribe = lambda key, wav, model, language="en", prompt="", timeout=None: ""
stop_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
pS = lr.chunk_path(root, "stoptest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(pS), exist_ok=True); open(pS, "wb").write(b"x")
stop_up.enqueue("stoptest", os.path.join(root, "stoptest.pdf"), lr.Chunk(1, 0.0, 30.0), pS)
check("drain() returns before stop()", _returns_within(stop_up.drain, 2.0))
stop_up.stop()
check("the stop sentinel itself is drained (task_done for None too)", _returns_within(stop_up.drain, 2.0))
pS2 = lr.chunk_path(root, "stoptest", lr.Chunk(1, 30.0, 60.0))
open(pS2, "wb").write(b"y")
stop_up.enqueue("stoptest", os.path.join(root, "stoptest.pdf"), lr.Chunk(1, 30.0, 60.0), pS2)
check("a later enqueue restarts the (now-dead) worker thread and still processes it",
      _returns_within(stop_up.drain, 2.0) and not os.path.exists(pS2))

# ---------------------------------------------------------------------
# I1: Recorder._flush must write nothing for an empty buffer.
# ---------------------------------------------------------------------
section("I1: Recorder._flush writes nothing for an empty buffer")
flush_calls = []
flush_up = lr.Uploader(root, lambda: {})
flush_up.enqueue = lambda *a, **k: flush_calls.append(a)
flush_rec = lr.Recorder(root, "flushtest", os.path.join(root, "flushtest.pdf"), get_page=lambda: 1, uploader=flush_up)
empty_chunk = lr.Chunk(1, 0.0, 30.0)
flush_rec._buffer = bytearray()
flush_rec._flush(empty_chunk)
check("an empty buffer writes no file and never enqueues",
      flush_calls == [] and not os.path.exists(lr.chunk_path(root, "flushtest", empty_chunk)))
flush_rec._buffer = bytearray(b"\x01\x00" * 10)
flush_rec._flush(empty_chunk)
check("a non-empty buffer still writes and enqueues (the guard isn't a permanent no-op)",
      len(flush_calls) == 1 and os.path.exists(lr.chunk_path(root, "flushtest", empty_chunk)))

# ---------------------------------------------------------------------
# m1: a second start() while already recording is a no-op returning True.
# ---------------------------------------------------------------------
section("m1: a second start() while already recording returns True and touches nothing")
m1_up = lr.Uploader(root, lambda: {})
m1_rec = lr.Recorder(root, "m1test", os.path.join(root, "m1test.pdf"), get_page=lambda: 1, uploader=m1_up)
m1_rec._recording = True  # simulate an already-active recording, no real audio needed
sys.modules["PyQt6"] = None  # if start() tried to import PyQt6 despite the guard, this proves it
try:
    m1_result = m1_rec.start()
finally:
    del sys.modules["PyQt6"]
check("start() while already recording returns True without attempting to touch PyQt6", m1_result is True)

# ---------------------------------------------------------------------
# m2: stop() reads the device one last time before closing the final
# chunk, so up to one tick's worth of trailing audio is not discarded.
# ---------------------------------------------------------------------
section("m2: stop() pulls the last bytes from the device into the final chunk")
m2_flush_calls = []
m2_up = lr.Uploader(root, lambda: {})
m2_up.enqueue = lambda *a, **k: m2_flush_calls.append(a)
m2_rec = lr.Recorder(root, "m2test", os.path.join(root, "m2test.pdf"), get_page=lambda: 1, uploader=m2_up)
m2_rec._recording = True
m2_rec._epoch0 = 1000.0
m2_rec._start_mono = time.monotonic() - 5.0
m2_rec._chunker.start(1, 1000.0)
m2_rec._io = _FakeIO(b"\x01\x00" * 4)  # bytes still sitting in the device, never read by a tick
m2_rec._buffer = bytearray()
m2_rec.stop()
check("stop() reads the device once more, so the final chunk is non-empty and gets flushed",
      len(m2_flush_calls) == 1 and os.path.exists(m2_flush_calls[0][3]))

# ---------------------------------------------------------------------
# m3 + f3 (foreign files): requeue_leftovers orders by NUMERIC t0 and
# ignores anything that isn't a well-formed "<t0>-p<page:04d>.wav".
# ---------------------------------------------------------------------
section("m3/f3: requeue_leftovers orders by numeric t0 and ignores foreign files")
foreign_dir = os.path.join(root, "recordings", "foreign")
os.makedirs(foreign_dir, exist_ok=True)
open(os.path.join(foreign_dir, "notes.txt"), "w").write("not audio")
open(os.path.join(foreign_dir, "100-p03.wav"), "wb").write(b"only 2 page digits, not a match")
for t0 in (90, 1000, 100):  # deliberately NOT in lexicographic filename order
    open(os.path.join(foreign_dir, f"{t0}-p0001.wav"), "wb").write(f"RIFF-{t0}".encode())
seen_order = []
def fake_transcribe_order(key, wav, model, language="en", prompt="", timeout=None):
    seen_order.append(wav.decode())
    return ""
lr._transcribe = fake_transcribe_order
foreign_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
n_foreign = foreign_up.requeue_leftovers("foreign", os.path.join(root, "foreign.pdf"))
foreign_up.drain()
check("exactly the 3 well-formed leftovers are requeued (the .txt and the 2-digit page name are ignored)",
      n_foreign == 3)
check("they transcribe in NUMERIC t0 order (90, 100, 1000), not lexicographic (100, 1000, 90)",
      seen_order == ["RIFF-90", "RIFF-100", "RIFF-1000"])

# ---------------------------------------------------------------------
# m4: segment timestamps are epoch seconds (real wall-clock time), not
# raw time.monotonic() ("seconds since some unspecified point, often
# boot") -- so segments from different sessions/reboots still sort and
# compare.
# ---------------------------------------------------------------------
section("m4: chunk timestamps are epoch seconds, not seconds-since-boot")
m4_up = lr.Uploader(root, lambda: {})
m4_flush_calls = []
m4_up.enqueue = lambda *a, **k: m4_flush_calls.append(a)
m4_rec = lr.Recorder(root, "m4test", os.path.join(root, "m4test.pdf"), get_page=lambda: 1, uploader=m4_up)
before_epoch = time.time()
m4_rec._recording = True
m4_rec._epoch0 = time.time()
m4_rec._start_mono = time.monotonic()
m4_rec._chunker.start(1, m4_rec._epoch0)
m4_rec._io = _FakeIO(b"\x00\x00")
m4_rec.stop()
after_epoch = time.time()
check("the closed chunk's t0 is a real epoch timestamp (close to time.time()), not seconds-since-boot",
      bool(m4_flush_calls) and before_epoch - 1.0 <= m4_flush_calls[0][2].t0 <= after_epoch + 1.0)

# ---------------------------------------------------------------------
# m5: a page is marked "seeded" only after ensure_records actually
# succeeds, so a transient failure is retried on the next chunk instead
# of being silently permanent for the life of the Uploader.
# ---------------------------------------------------------------------
section("m5: a page is marked seeded only after ensure_records succeeds")
m5_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
seed_attempts = []
_real_ensure_records = page_store.ensure_records
def flaky_ensure_records(*a, **k):
    seed_attempts.append(1)
    if len(seed_attempts) == 1:
        raise RuntimeError("transient disk hiccup")
    return _real_ensure_records(*a, **k)
page_store.ensure_records = flaky_ensure_records
try:
    lr._transcribe = lambda key, wav, model, language="en", prompt="", timeout=None: "seg"
    pm5a = lr.chunk_path(root, "m5test", lr.Chunk(1, 0.0, 30.0))
    os.makedirs(os.path.dirname(pm5a), exist_ok=True); open(pm5a, "wb").write(b"a")
    m5_up.enqueue("m5test", os.path.join(root, "m5test.pdf"), lr.Chunk(1, 0.0, 30.0), pm5a); m5_up.drain()
    pm5b = lr.chunk_path(root, "m5test", lr.Chunk(1, 30.0, 60.0))
    open(pm5b, "wb").write(b"b")
    m5_up.enqueue("m5test", os.path.join(root, "m5test.pdf"), lr.Chunk(1, 30.0, 60.0), pm5b); m5_up.drain()
finally:
    page_store.ensure_records = _real_ensure_records
check("a failed seeding attempt is retried on the next chunk rather than marked seeded forever",
      len(seed_attempts) == 2)

# ---------------------------------------------------------------------
# f3 (remaining): strict FIFO order, and the continuity prompt capped at
# 800 chars (the existing pin only proved a prompt was passed, never
# that it was bounded).
# ---------------------------------------------------------------------
section("f3: the Uploader processes chunks strictly FIFO")
fifo_order = []
def fake_transcribe_fifo(key, wav, model, language="en", prompt="", timeout=None):
    fifo_order.append(wav)
    return ""
lr._transcribe = fake_transcribe_fifo
fifo_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
for i, tag in enumerate((b"AAA", b"BBB", b"CCC")):
    # Indexed by the loop counter, never by len(fifo_order) -- that list
    # only grows once the BACKGROUND thread transcribes, so using it here
    # would race the enqueue loop and could reuse (and delete out from
    # under) the same chunk_path for two different chunks.
    fifo_chunk = lr.Chunk(1, float(i) * 30.0, float(i) * 30.0 + 30.0)
    fifo_path = lr.chunk_path(root, "fifo", fifo_chunk)
    os.makedirs(os.path.dirname(fifo_path), exist_ok=True)
    open(fifo_path, "wb").write(tag)
    fifo_up.enqueue("fifo", os.path.join(root, "fifo.pdf"), fifo_chunk, fifo_path)
fifo_up.drain()
check("three enqueued chunks transcribe strictly in the order they were enqueued",
      fifo_order == [b"AAA", b"BBB", b"CCC"])

section("f3: the continuity prompt is capped at 800 chars")
long_text = "x" * 2000
cap_calls = []
def fake_transcribe_long(key, wav, model, language="en", prompt="", timeout=None):
    cap_calls.append(prompt)
    return long_text if wav == b"FIRST" else ""
lr._transcribe = fake_transcribe_long
cap_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
c1p = lr.chunk_path(root, "captest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(c1p), exist_ok=True); open(c1p, "wb").write(b"FIRST")
cap_up.enqueue("captest", os.path.join(root, "captest.pdf"), lr.Chunk(1, 0.0, 30.0), c1p); cap_up.drain()
c2p = lr.chunk_path(root, "captest", lr.Chunk(1, 30.0, 60.0))
open(c2p, "wb").write(b"SECOND")
cap_up.enqueue("captest", os.path.join(root, "captest.pdf"), lr.Chunk(1, 30.0, 60.0), c2p); cap_up.drain()
check("the prompt for the next chunk is capped to the previous segment's LAST 800 chars",
      cap_calls[-1] == long_text[-800:] and len(cap_calls[-1]) == 800)

# ---------------------------------------------------------------------
# Final review, I-2: pending() is what "has the uploader drained?" must
# ask. The worker get()s an item BEFORE transcribing it, so qsize() is
# already 0 while the last chunk of a lecture is still in flight —
# scheduling the re-index on qsize() reads the page records before the
# tail transcript has landed, and the end of every lecture is never
# embedded.
# ---------------------------------------------------------------------
section("I-2: pending() counts the chunk in flight, which queued() does not")
_pend_gate = threading.Event()
_pend_seen = threading.Event()


def fake_transcribe_blocking(key, wav, model, language="en", prompt="", timeout=None):
    _pend_seen.set()
    _pend_gate.wait(5.0)
    return ""


lr._transcribe = fake_transcribe_blocking
pend_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
pend_chunk = lr.Chunk(1, 0.0, 30.0)
pend_path = lr.chunk_path(root, "pendtest", pend_chunk)
os.makedirs(os.path.dirname(pend_path), exist_ok=True)
open(pend_path, "wb").write(b"RIFF")
pend_up.enqueue("pendtest", os.path.join(root, "pendtest.pdf"), pend_chunk, pend_path)
check("the worker really did pick the chunk up (the pin below is about a "
      "chunk mid-upload, not one still waiting in line)",
      _pend_seen.wait(2.0))
check("pending() is 1 while that chunk is mid-upload — and queued() is "
      "already 0, which is exactly why the drain poll cannot use it",
      pend_up.pending() == 1 and pend_up.queued() == 0,
      f"pending={pend_up.pending()} queued={pend_up.queued()}")
_pend_gate.set()
pend_up.drain()
check("...and pending() is back to 0 once the queue has actually drained",
      pend_up.pending() == 0)

# ---------------------------------------------------------------------
# M-9 (2)/(3): Recorder._tick, QTimer-free. The real tick is driven by a
# 250 ms QTimer against a live QAudioSource, neither of which this file
# opens — but the LOGIC between them (read the device, notice the page
# changed, close and write that page's chunk, report status) is plain
# Python and was unpinned. _flush's os.makedirs(..., exist_ok=True) rides
# along for free: the second chunk lands in the directory the first one
# created, which without exist_ok raises FileExistsError into _flush's
# own except and silently enqueues nothing.
# ---------------------------------------------------------------------
section("M-9: _tick closes the OLD page's chunk on a page change, reports "
        "status, and writes a second chunk into the same directory")


class _FakeClock:
    """Swapped in for lecture_recorder's own `time` module, so nothing
    outside this module sees a frozen clock."""

    def __init__(self, t: float) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t


class _TickUploader:
    def __init__(self) -> None:
        self.calls: list = []

    def enqueue(self, pdf_safe, pdf_path, chunk, wav_path):
        self.calls.append((pdf_safe, chunk, wav_path))

    def queued(self) -> int:
        return 3


tick_up = _TickUploader()
tick_status: list = []
tick_page = [1]
tick_rec = lr.Recorder(root, "ticktest", os.path.join(root, "ticktest.pdf"),
                       get_page=lambda: tick_page[0],
                       on_status=lambda s, q: tick_status.append((s, q)),
                       uploader=tick_up)
tick_pcm = b"\x01\x00" * 8  # 16 bytes = 8 frames at the negotiated width
tick_rec._io = _FakeIO(tick_pcm)
tick_rec._recording = True
tick_rec._epoch0 = 5000.0      # wall-clock at Record
tick_rec._start_mono = 1000.0  # monotonic at Record
tick_rec._chunker.start(1, 5000.0)
_real_lr_time = lr.time
tick_clock = _FakeClock(1005.0)  # 5 s into the recording
lr.time = tick_clock
try:
    tick_page[0] = 2  # the user turned the page between ticks
    tick_rec._tick()
    first = tick_up.calls[0] if tick_up.calls else None
    check("a page change closes the chunk on the OLD page, at the tick's "
          "own time, and hands its WAV to the uploader",
          len(tick_up.calls) == 1 and first[0] == "ticktest"
          and first[1] == lr.Chunk(1, 5000.0, 5005.0)
          and os.path.basename(first[2]) == "5000-p0001.wav",
          repr(tick_up.calls))
    check("...and that WAV carries the bytes this tick read off the "
          "device (44-byte header + the 16 PCM bytes), not just a header",
          first is not None and os.path.getsize(first[2]) == 44 + len(tick_pcm),
          repr(first))
    check("...and _tick reports elapsed seconds and the uploader's own "
          "queue depth through on_status (the D6 status text's feed)",
          tick_status == [(5.0, 3)], repr(tick_status))
    tick_clock.t = 1005.0 + lr.CHUNK_S  # a full chunk later, same page
    tick_rec._tick()
    second = tick_up.calls[1] if len(tick_up.calls) > 1 else None
    check("a second tick a full CHUNK_S later closes the new page's chunk "
          "into the SAME recordings directory — _flush's makedirs is "
          "exist_ok, so the second write is not swallowed by its except",
          len(tick_up.calls) == 2 and first is not None
          and second[1] == lr.Chunk(2, 5005.0, 5035.0)
          and os.path.basename(second[2]) == "5005-p0002.wav"
          and os.path.dirname(second[2]) == os.path.dirname(first[2])
          and os.path.getsize(second[2]) == 44 + len(tick_pcm),
          repr(tick_up.calls))
    check("...and status is reported on every tick, not just the first",
          tick_status == [(5.0, 3), (35.0, 3)], repr(tick_status))
finally:
    lr.time = _real_lr_time

raise SystemExit(report())
