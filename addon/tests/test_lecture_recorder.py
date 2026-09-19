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

  - the no-key gate and the PyQt6-blocked import check;
  - "Fix round 1" sections, one per item in task-4-review.md's Quality
    verdict (C1, I1, I2, I3, f1, f2) plus the minors folded in by the
    coordinator (m1-m5, FIFO order, a foreign leftover file, the 800-char
    prompt cap).
"""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import struct
import sys
import tempfile
import threading
import time
import types

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

section("I3: WAV header and duration honour the negotiated audio format")
neg_rate, neg_channels, neg_width = 48000, 2, 2
neg_frames = neg_rate // 2  # 0.5 s of audio
neg_pcm = b"\x00" * (neg_frames * neg_channels * neg_width)
w48 = lr.wav_bytes(neg_pcm, rate=neg_rate, channels=neg_channels, width=neg_width)
with wave.open(io.BytesIO(w48)) as wf:
    check("negotiated WAV header preserves rate, channels, width and frames",
          (wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes())
          == (48000, 2, 2, 24000))
    check("negotiated WAV contains half a second of the original PCM",
          wf.getnframes() / wf.getframerate() == 0.5
          and wf.readframes(wf.getnframes()) == neg_pcm)
w_default = lr.wav_bytes(b"\x00\x00" * 16000)
with wave.open(io.BytesIO(w_default)) as wf:
    check("default WAV remains one second of 16 kHz mono int16",
          (wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes())
          == (16000, 1, 2, 16000)
          and wf.getnframes() / wf.getframerate() == 1.0)

section("chunk_path and the uploader")
root = tempfile.mkdtemp()
p = lr.chunk_path(root, "lec", lr.Chunk(3, 100.0, 130.0))
check("recordings/<safe>/<t0>-<t1>-p<page:04d>.wav, both to the millisecond",
      p.endswith(os.path.join("recordings", "lec", "100.000-130.000-p0003.wav")), p)
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

section("no OpenAI key: logs once, never calls transcribe, keeps the WAV")
gate_calls = []
def transcribe_should_not_run(*a, **k):
    gate_calls.append((a, k))
    raise AssertionError("transcribe must not be called with no key")
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

section("C1: the stop() sentinel gets task_done() too, so a NEW uploader restarts cleanly")
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
# PR #4 FIFTH re-review: the restart is a NEW Uploader, never a reopened
# one. Production never reopens either -- _stop_lecture_uploader drops
# the singleton and uploader() builds a fresh instance -- so enqueue on a
# stopped uploader is refused outright (the WAV stays for the next
# uploader's requeue_leftovers) rather than reviving a worker whose
# predecessor may still be inside _one().
stop_up.enqueue("stoptest", os.path.join(root, "stoptest.pdf"), lr.Chunk(1, 30.0, 60.0), pS2)
check("an enqueue on the stopped uploader queues nothing and keeps the WAV",
      stop_up.queued() == 0 and stop_up._closed and os.path.exists(pS2))
fresh_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
fresh_up.enqueue("stoptest", os.path.join(root, "stoptest.pdf"), lr.Chunk(1, 30.0, 60.0), pS2)
check("a NEW Uploader processes that same chunk",
      _returns_within(fresh_up.drain, 2.0) and not os.path.exists(pS2))

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
# K-280 review: the match is anchored at BOTH ends (fullmatch), and nothing
# proved it. A name that merely CONTAINS a well-formed one — an editor
# backup, a copy, a spent marker — must not be requeued, or a stray file
# gets transcribed (a paid call) and its segment appended under a page it
# was never said over.
open(os.path.join(foreign_dir, "12.000-30.000-p0001.wav.bak"), "wb").write(b"trailing junk")
open(os.path.join(foreign_dir, "copy-of-12.000-30.000-p0001.wav"), "wb").write(b"leading junk")
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
check("exactly the 3 well-formed leftovers are requeued (the .txt, the 2-digit page name "
      "and the two names that merely CONTAIN a well-formed one are ignored)",
      n_foreign == 3, n_foreign)
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
        # The queue LENGTH, which the worker drops to 0 the moment it
        # picks a chunk up: the number the bar must NOT show (PR #4
        # second re-review). Deliberately different from pending() here,
        # so the status pins below can tell the two apart.
        return 0

    def pending(self) -> int:
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
          and os.path.basename(first[2]) == "5000.000-5005.000-p0001.wav",
          repr(tick_up.calls))
    check("...and that WAV carries the bytes this tick read off the "
          "device (44-byte header + the 16 PCM bytes), not just a header",
          first is not None and os.path.getsize(first[2]) == 44 + len(tick_pcm),
          repr(first))
    check("...and _tick reports elapsed seconds and the uploader's own "
          "PENDING count through on_status (the D6 status text's feed) — "
          "not queued(), which is already 0 for a chunk in flight",
          tick_status == [(5.0, 3)], repr(tick_status))
    tick_clock.t = 1005.0 + lr.CHUNK_S  # a full chunk later, same page
    tick_rec._tick()
    second = tick_up.calls[1] if len(tick_up.calls) > 1 else None
    check("a second tick a full CHUNK_S later closes the new page's chunk "
          "into the SAME recordings directory — _flush's makedirs is "
          "exist_ok, so the second write is not swallowed by its except",
          len(tick_up.calls) == 2 and first is not None
          and second[1] == lr.Chunk(2, 5005.0, 5035.0)
          and os.path.basename(second[2]) == "5005.000-5035.000-p0002.wav"
          and os.path.dirname(second[2]) == os.path.dirname(first[2])
          and os.path.getsize(second[2]) == 44 + len(tick_pcm),
          repr(tick_up.calls))
    check("...and status is reported on every tick, not just the first",
          tick_status == [(5.0, 3), (35.0, 3)], repr(tick_status))
finally:
    lr.time = _real_lr_time

# ---------------------------------------------------------------------
# PR #4 F2 (Copilot + Codex): chunk_path truncated t0 to whole seconds,
# so two chunks closed inside one second -- a page bounce, or Stop then
# Record on the same page -- shared ONE filename. The second _flush
# overwrote the first's audio, and the asynchronous upload then unlinked
# a WAV that no longer held the bytes it had transcribed.
# ---------------------------------------------------------------------
section("PR #4 F2: sub-second chunks get distinct filenames; legacy names still parse")
sub_a = lr.chunk_path(root, "subsec", lr.Chunk(1, 12.250, 42.250))
sub_b = lr.chunk_path(root, "subsec", lr.Chunk(1, 12.450, 42.450))
check("two chunks 0.2 s apart on the same page get DIFFERENT paths "
      "(whole-second names collided and the loser's audio was lost)",
      sub_a != sub_b, f"{os.path.basename(sub_a)} vs {os.path.basename(sub_b)}")
check("...and the millisecond is what distinguishes them",
      os.path.basename(sub_a) == "12.250-42.250-p0001.wav"
      and os.path.basename(sub_b) == "12.450-42.450-p0001.wav",
      f"{os.path.basename(sub_a)} / {os.path.basename(sub_b)}")

sub_dir = os.path.join(root, "recordings", "subsec")
os.makedirs(sub_dir, exist_ok=True)
open(os.path.join(sub_dir, "12.500-p0001.wav"), "wb").write(b"RIFF-later")
open(os.path.join(sub_dir, "12.250-p0001.wav"), "wb").write(b"RIFF-earlier")
open(os.path.join(sub_dir, "12-p0001.wav"), "wb").write(b"RIFF-legacy")
sub_order = []
def fake_transcribe_sub(key, wav, model, language="en", prompt="", timeout=None, **kw):
    sub_order.append(wav.decode())
    return ""
lr._transcribe = fake_transcribe_sub
sub_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
n_sub = sub_up.requeue_leftovers("subsec", os.path.join(root, "subsec.pdf"))
sub_up.drain()
check("requeue_leftovers still reads a legacy whole-second name alongside the new "
      "millisecond ones — old leftovers on disk must not become foreign files",
      n_sub == 3, n_sub)
check("...and orders them NUMERICALLY by t0: 12 < 12.250 < 12.500 (a decimal parsed "
      "as an int would raise, and a string sort puts 12.250 before 12)",
      sub_order == ["RIFF-legacy", "RIFF-earlier", "RIFF-later"], sub_order)

# ---------------------------------------------------------------------
# PR #4 F4: openai_client._request folds up to 300 bytes of the
# PROVIDER'S error body into the OpenAIError's message, and that body can
# echo request-derived text -- here, the continuity prompt, which is the
# previous segment's transcript. Log the class and status only.
# ---------------------------------------------------------------------
section("PR #4 F4: a failed transcription logs class and status, never the message")
import contextlib  # noqa: E402 -- local to this section

MARKER = "PATIENT-NAME-FROM-THE-TRANSCRIPT"
def fake_transcribe_leaky(key, wav, model, language="en", prompt="", timeout=None, **kw):
    raise lr.openai_client.OpenAIError(f"400 Bad Request: {{\"error\": \"{MARKER}\"}}", status=400)
lr._transcribe = fake_transcribe_leaky
leak_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
p_leak = lr.chunk_path(root, "leaktest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(p_leak), exist_ok=True); open(p_leak, "wb").write(b"RIFF OK")
leak_log = io.StringIO()
with contextlib.redirect_stdout(leak_log):
    leak_up.enqueue("leaktest", os.path.join(root, "leaktest.pdf"), lr.Chunk(1, 0.0, 30.0), p_leak)
    leak_up.drain()
leak_txt = leak_log.getvalue()
check("the provider's error body never reaches the log", MARKER not in leak_txt, leak_txt)
check("...but the failure is still reported, by class and status, and the WAV kept",
      "OpenAIError" in leak_txt and "400" in leak_txt and os.path.exists(p_leak), leak_txt)

def fake_transcribe_leaky_generic(key, wav, model, language="en", prompt="", timeout=None, **kw):
    raise RuntimeError(f"unexpected: {MARKER}")
lr._transcribe = fake_transcribe_leaky_generic
p_leak2 = lr.chunk_path(root, "leaktest", lr.Chunk(1, 30.0, 60.0))
open(p_leak2, "wb").write(b"RIFF OK")
leak_log2 = io.StringIO()
with contextlib.redirect_stdout(leak_log2):
    leak_up.enqueue("leaktest", os.path.join(root, "leaktest.pdf"), lr.Chunk(1, 30.0, 60.0), p_leak2)
    leak_up.drain()
leak_txt2 = leak_log2.getvalue()
check("the generic except is the same rule — class only, no message",
      MARKER not in leak_txt2 and "RuntimeError" in leak_txt2 and os.path.exists(p_leak2),
      leak_txt2)

# ---------------------------------------------------------------------
# PR #4 second re-review (Copilot), finding 1: `_stop_lecture_uploader`
# drops the uploader singleton the moment `stop()` has enqueued its
# sentinel — but the worker may be inside `_one()`, still transcribing.
# Appending then writes a page record behind a profile that is already
# closing, and unlinking the WAV destroys the only copy of that audio
# while the NEXT profile's requeue_leftovers is scanning the same
# directory: the same chunk can land twice, or race the new worker's own
# unlink. A stopped uploader must mutate nothing.
# ---------------------------------------------------------------------
section("PR #4 re-review: a stopped uploader appends nothing and keeps the WAV of the chunk in flight")
_close_gate = threading.Event()
_close_seen = threading.Event()


def fake_transcribe_gated(key, wav, model, language="en", prompt="", timeout=None):
    _close_seen.set()
    _close_gate.wait(5.0)
    return "text that only came back after the profile had closed"


lr._transcribe = fake_transcribe_gated
close_segs: list = []
close_up = lr.Uploader(root, lambda: {"api_key_openai": "k"},
                       on_segment=lambda safe, page: close_segs.append((safe, page)))
p_close = lr.chunk_path(root, "closetest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(p_close), exist_ok=True)
open(p_close, "wb").write(b"RIFF OK")
close_up.enqueue("closetest", os.path.join(root, "closetest.pdf"), lr.Chunk(1, 0.0, 30.0), p_close)
check("the worker really is inside the transcription when the teardown starts "
      "(the pins below are about a chunk in flight, not one still queued)",
      _close_seen.wait(2.0))
# The network call comes back AFTER stop() has run, which is the whole race.
threading.Timer(0.05, _close_gate.set).start()
_close_t0 = time.monotonic()
_close_returned = _returns_within(close_up.stop, 4.0)
_close_elapsed = time.monotonic() - _close_t0
check("stop() returns instead of leaving profile close hanging", _close_returned)
check("...and it WAITED for the in-flight chunk rather than racing it away",
      _close_elapsed >= 0.04, f"{_close_elapsed:.3f}s")
check("a transcription that lands after stop() appends nothing",
      close_segs == [], repr(close_segs))
check("...and its WAV is kept, so the next profile's requeue_leftovers re-uploads "
      "it exactly once — one re-upload is cheap, a duplicate segment is not",
      os.path.exists(p_close))

section("PR #4 re-review: stop()'s wait is bounded — a wedged upload cannot freeze profile close")
_hang_gate = threading.Event()
_hang_seen = threading.Event()


def fake_transcribe_wedged(key, wav, model, language="en", prompt="", timeout=None):
    _hang_seen.set()
    _hang_gate.wait(30.0)
    return ""


lr._transcribe = fake_transcribe_wedged
hang_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
p_hang = lr.chunk_path(root, "hangtest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(p_hang), exist_ok=True)
open(p_hang, "wb").write(b"RIFF")
hang_up.enqueue("hangtest", os.path.join(root, "hangtest.pdf"), lr.Chunk(1, 0.0, 30.0), p_hang)
check("the worker is wedged in the network call", _hang_seen.wait(2.0))
check("stop() gives up on it within STOP_JOIN_S rather than blocking the main "
      "thread for as long as the provider feels like taking",
      _returns_within(hang_up.stop, lr.STOP_JOIN_S + 1.5))
_hang_gate.set()  # let the leaked worker die instead of idling for 30 s

section("PR #4 re-review: a normal stop still drains — a chunk that finished is kept, not discarded")
lr._transcribe = lambda key, wav, model, language="en", prompt="", timeout=None: "landed"
norm_segs: list = []
norm_up = lr.Uploader(root, lambda: {"api_key_openai": "k"},
                      on_segment=lambda safe, page: norm_segs.append((safe, page)))
p_norm = lr.chunk_path(root, "normtest", lr.Chunk(2, 0.0, 30.0))
os.makedirs(os.path.dirname(p_norm), exist_ok=True)
open(p_norm, "wb").write(b"RIFF OK")
norm_up.enqueue("normtest", os.path.join(root, "normtest.pdf"), lr.Chunk(2, 0.0, 30.0), p_norm)
norm_up.drain()
check("stop() returns promptly when nothing is in flight", _returns_within(norm_up.stop, 2.0))
check("...and the chunk that completed BEFORE it is appended and its WAV removed",
      norm_segs == [("normtest", 1)] and not os.path.exists(p_norm), repr(norm_segs))

# ---------------------------------------------------------------------
# PR #4 second re-review, finding 3: the "· n to transcribe" number on
# both docks came from the uploader's queued() — the queue LENGTH — and
# the worker get()s a chunk BEFORE transcribing it. So through the whole
# of a slow upload the bar read "0 to transcribe" while the drain-aware
# re-index poll was still waiting on pending() == 1. One number, one
# meaning: what is still owed a transcript.
# ---------------------------------------------------------------------
section("PR #4 re-review: the '· n to transcribe' number counts pending(), not the queue length")
_bar_gate = threading.Event()
_bar_seen = threading.Event()


def fake_transcribe_bar(key, wav, model, language="en", prompt="", timeout=None):
    _bar_seen.set()
    _bar_gate.wait(5.0)
    return ""


lr._transcribe = fake_transcribe_bar
bar_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
p_bar = lr.chunk_path(root, "bartest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(p_bar), exist_ok=True)
open(p_bar, "wb").write(b"RIFF")
bar_up.enqueue("bartest", os.path.join(root, "bartest.pdf"), lr.Chunk(1, 0.0, 30.0), p_bar)
check("the chunk is off the queue and in flight (queued() already reads 0)",
      _bar_seen.wait(2.0) and bar_up.queued() == 0, f"queued={bar_up.queued()}")
bar_status: list = []
bar_rec = lr.Recorder(root, "bartest", os.path.join(root, "bartest.pdf"),
                      get_page=lambda: 1,
                      on_status=lambda s, q: bar_status.append(q),
                      uploader=bar_up)
bar_rec._io = _FakeIO(b"")
bar_rec._recording = True
bar_rec._epoch0 = 9000.0
bar_rec._start_mono = time.monotonic()
bar_rec._chunker.start(1, 9000.0)
bar_rec._tick()
check("the bar is told 1, not 0, while that chunk is mid-upload — the same "
      "number _request_index_when_idle waits on before re-indexing",
      bar_status == [1], f"{bar_status} (queued={bar_up.queued()})")
check("...and Recorder.queued is that one number's single source",
      bar_rec.queued == 1, repr(bar_rec.queued))
_bar_gate.set()
bar_up.drain()
check("...and it drops to 0 once the upload really finished", bar_rec.queued == 0)

# ---------------------------------------------------------------------
# PR #4 third re-review (Copilot), finding 2: `stop()` sets `_closed` and
# enqueues its sentinel, but every chunk already SITTING IN THE QUEUE
# ahead of that sentinel still reaches `_one()` — which read the config
# and transcribed (a paid call, per chunk) before the post-transcription
# `_closed` check threw the result away. The in-flight chunk above is
# unavoidable; the queued ones are pure waste, and on a long lecture
# there can be many of them. `_one()` must bail at the top.
# ---------------------------------------------------------------------
section("PR #4 third re-review: chunks queued behind the stop sentinel are never transcribed")
_q_gate = threading.Event()
_q_seen = threading.Event()
_q_calls: list = []


def fake_transcribe_counting(key, wav, model, language="en", prompt="", timeout=None):
    _q_calls.append(model)
    _q_seen.set()
    _q_gate.wait(5.0)
    return "barrier text"


lr._transcribe = fake_transcribe_counting
q_segs: list = []
q_up = lr.Uploader(root, lambda: {"api_key_openai": "k"},
                   on_segment=lambda safe, page: q_segs.append((safe, page)))
_q_paths = []
for _i, _ch in enumerate((lr.Chunk(1, 0.0, 30.0), lr.Chunk(1, 30.0, 60.0), lr.Chunk(1, 60.0, 90.0))):
    _p = lr.chunk_path(root, "queuedtest", _ch)
    os.makedirs(os.path.dirname(_p), exist_ok=True)
    open(_p, "wb").write(b"RIFF OK")
    _q_paths.append((_ch, _p))
# The first chunk holds the single worker inside the network call, so the
# other two are still QUEUED (never started) when stop() runs — exactly
# the shape the finding describes.
q_up.enqueue("queuedtest", os.path.join(root, "queuedtest.pdf"), *_q_paths[0])
check("the worker is parked inside the first chunk's transcription, so the "
      "next two really are queued rather than in flight", _q_seen.wait(2.0))
for _ch, _p in _q_paths[1:]:
    q_up.enqueue("queuedtest", os.path.join(root, "queuedtest.pdf"), _ch, _p)
check("...and both of them are on the queue when the teardown starts",
      q_up.queued() == 2, f"queued={q_up.queued()}")
threading.Timer(0.05, _q_gate.set).start()  # the barrier returns after stop()
check("stop() returns instead of hanging", _returns_within(q_up.stop, 4.0))
check("exactly ONE transcription happened — the barrier that was already in "
      "flight. The two chunks queued behind the sentinel cost nothing: no "
      "config read, no paid call, no result to throw away",
      _q_calls == ["gpt-4o-mini-transcribe"], repr(_q_calls))
check("...and both their WAVs are kept for the next Record's requeue_leftovers",
      all(os.path.exists(_p) for _ch, _p in _q_paths[1:]))
check("...with nothing appended behind the closing profile", q_segs == [], repr(q_segs))

# =======================================================================
# PR #4 FOURTH re-review (Copilot) -- K-272.
# =======================================================================

# ---------------------------------------------------------------------
# (2) enqueue() used to clear _closed, reopening an uploader whose OLD
# worker may still be inside _one() after stop()'s bounded join timed
# out. That worker then read _closed as False once its transcription
# returned and appended + unlinked the WAV -- while the very same WAV,
# re-queued, was processed a second time. _closed is a ONE-WAY LATCH now
# (PR #4 fifth re-review): a stopped uploader stays stopped, enqueue is
# refused with one log line, and the WAV waits for the NEXT uploader's
# requeue_leftovers -- which is what production does anyway, since
# _stop_lecture_uploader drops the singleton and uploader() rebuilds it.
# ---------------------------------------------------------------------
section("PR #4 fifth re-review: a stopped uploader stays stopped")
_ro_gate = threading.Event()
_ro_seen = threading.Event()
_ro_models: list = []


def fake_transcribe_held(key, wav, model, language="en", prompt="", timeout=None):
    _ro_models.append(model)
    _ro_seen.set()
    _ro_gate.wait(5.0)
    return "held text"


lr._transcribe = fake_transcribe_held
ro_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
_ro_pdf = os.path.join(root, "reopentest.pdf")
_ro_p1 = lr.chunk_path(root, "reopentest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(_ro_p1), exist_ok=True)
open(_ro_p1, "wb").write(b"RIFF 1")
ro_up.enqueue("reopentest", _ro_pdf, lr.Chunk(1, 0.0, 30.0), _ro_p1)
check("the worker is parked inside a transcription, so stop()'s sentinel "
      "queues BEHIND it rather than being consumed immediately",
      _ro_seen.wait(2.0))
# The worker is deliberately held, so don't pay stop()'s real join here.
_ro_join, lr.STOP_JOIN_S = lr.STOP_JOIN_S, 0.05
try:
    ro_up.stop()
finally:
    lr.STOP_JOIN_S = _ro_join
_ro_thread = ro_up._thread
check("stop() left the parked worker alive with its sentinel unconsumed",
      _ro_thread is not None and _ro_thread.is_alive() and ro_up._closed)
_ro_p2 = lr.chunk_path(root, "reopentest", lr.Chunk(2, 30.0, 60.0))
open(_ro_p2, "wb").write(b"RIFF 2")
# The parked worker has not reached stop()'s sentinel yet, so that
# sentinel is what is still on the queue — the pin is that the refused
# enqueue adds nothing to it.
_ro_qsize = ro_up.queued()
ro_up.enqueue("reopentest", _ro_pdf, lr.Chunk(2, 30.0, 60.0), _ro_p2)
check("an enqueue after stop() queues NOTHING and leaves the uploader "
      "closed (no reopening behind the parked worker)",
      ro_up.queued() == _ro_qsize and ro_up._closed,
      f"{ro_up.queued()} vs {_ro_qsize}")
check("...and starts no worker of its own",
      ro_up._thread is _ro_thread)
_ro_gate.set()
check("the parked worker finishes its own chunk and exits on the "
      "sentinel — drain() returns",
      _returns_within(ro_up.drain, 4.0))
check("the old worker never transcribed the refused chunk",
      _ro_models == ["gpt-4o-mini-transcribe"], repr(_ro_models))
check("both WAVs are kept: the parked one (closed mid-upload) and the "
      "refused one",
      os.path.exists(_ro_p1) and os.path.exists(_ro_p2))
# The restart production actually performs: a brand-new Uploader, which
# finds both leftovers on disk.
lr._transcribe = lambda key, wav, model, language="en", prompt="", timeout=None: ""
ro_fresh = lr.Uploader(root, lambda: {"api_key_openai": "k"})
check("a fresh Uploader's requeue_leftovers picks up both",
      ro_fresh.requeue_leftovers("reopentest", _ro_pdf) == 2)
check("...and processes them (each WAV handled exactly once)",
      _returns_within(ro_fresh.drain, 4.0)
      and not os.path.exists(_ro_p1) and not os.path.exists(_ro_p2))

# ---------------------------------------------------------------------
# (3) append_segment is DURABLE; on_segment is only a notification. With
# the notify inside the same try the exception reached _loop, which keeps
# the WAV for retry -- so the next requeue_leftovers transcribed (paid)
# and appended the very same segment a second time. Unlink first, then
# notify inside its own try.
# ---------------------------------------------------------------------
section("PR #4 fourth re-review: a raising on_segment never re-transcribes its chunk")
_ns_calls: list = []
_ns_notified: list = []


def fake_transcribe_counted(key, wav, model, language="en", prompt="", timeout=None):
    _ns_calls.append(model)
    return "spoken over the slide"


def on_segment_raises(safe, page):
    _ns_notified.append((safe, page))
    raise RuntimeError("boom from on_segment")


lr._transcribe = fake_transcribe_counted
ns_up = lr.Uploader(root, lambda: {"api_key_openai": "k"}, on_segment=on_segment_raises)
_ns_pdf = os.path.join(root, "notifytest.pdf")
_ns_p1 = lr.chunk_path(root, "notifytest", lr.Chunk(1, 0.0, 30.0))
os.makedirs(os.path.dirname(_ns_p1), exist_ok=True)
open(_ns_p1, "wb").write(b"RIFF N")
ns_up.enqueue("notifytest", _ns_pdf, lr.Chunk(1, 0.0, 30.0), _ns_p1)
check("drain() returns (the raise is swallowed, not propagated to _loop)",
      _returns_within(ns_up.drain, 3.0))
check("on_segment WAS reached — the notification still happens",
      _ns_notified == [("notifytest", 0)], repr(_ns_notified))
check("the WAV is unlinked despite the raise, so nothing re-queues it",
      not os.path.exists(_ns_p1))
check("requeue_leftovers finds nothing to transcribe a second time",
      ns_up.requeue_leftovers("notifytest", _ns_pdf) == 0)
ns_up.drain()
_ns_rec = page_store.load_record(root, "notifytest", _ns_pdf, 0)
check("the segment is in the page record exactly ONCE",
      len(_ns_rec.get("segments") or []) == 1, repr(_ns_rec.get("segments")))
check("...and it was transcribed exactly once (no paid re-run)",
      len(_ns_calls) == 1, repr(_ns_calls))
_ns_p2 = lr.chunk_path(root, "notifytest", lr.Chunk(2, 30.0, 60.0))
open(_ns_p2, "wb").write(b"RIFF N2")
ns_up.enqueue("notifytest", _ns_pdf, lr.Chunk(2, 30.0, 60.0), _ns_p2)
check("the worker survives and processes the next chunk",
      _returns_within(ns_up.drain, 3.0) and not os.path.exists(_ns_p2)
      and len(_ns_notified) == 2, repr(_ns_notified))

# ---------------------------------------------------------------------
# PR #4 sixth review (Copilot): a device whose ONLY sample format is
# Float32 must still record. The old fallback took device.preferredFormat()
# and forced Int16 onto it without ever asking isFormatSupported, so
# QAudioSource never started and Record was a dead button with no message.
# Negotiate honestly and convert the samples ourselves instead.
# ---------------------------------------------------------------------
section("PR #4 sixth review: pcm_to_int16 converts every negotiated sample format")


def _i16(*vals: int) -> bytes:
    return struct.pack("<%dh" % len(vals), *vals)


_f32 = struct.pack("<5f", -1.0, 0.0, 0.5, 1.0, 1.5)
check("Float32 -> clamped to [-1, 1] and scaled by 32767, little-endian",
      lr.pcm_to_int16(_f32, "Float") == _i16(-32767, 0, 16383, 32767, 32767),
      repr(lr.pcm_to_int16(_f32, "Float")))
check("...and Qt's own enum member is accepted, not just its name — the "
      "helper reads .name off whatever it is handed, so the Qt-free half "
      "of this module never imports QAudioFormat",
      lr.pcm_to_int16(_f32, types.SimpleNamespace(name="Float")) == _i16(-32767, 0, 16383, 32767, 32767))
check("Int32 -> shifted right 16 (a sign-preserving arithmetic shift, so "
      "the most negative sample stays the most negative)",
      lr.pcm_to_int16(struct.pack("<5i", 0, 65536, -65536, 2147483647, -2147483648), "Int32")
      == _i16(0, 1, -1, 32767, -32768))
check("UInt8 -> centred on 0 and shifted up 8",
      lr.pcm_to_int16(bytes([0, 128, 255, 64]), "UInt8") == _i16(-32768, 0, 32512, -16384))
_already = _i16(7, -7, 300)
check("Int16 passes through byte for byte — no round trip, no rescale",
      lr.pcm_to_int16(_already, "Int16") == _already)
_unknown_raised = False
try:
    lr.pcm_to_int16(b"\x00\x00", "Unknown")
except ValueError:
    _unknown_raised = True
check("an unknown sample format raises rather than guessing a width — "
      "start() turns that into a refusal with a log line, never silent "
      "noise in the WAV",
      _unknown_raised)

section("PR #4 sixth review: a Float32-ONLY device still records (start() "
        "picks the preferred format and converts)")


class _FakeSampleFormat:
    """Stands in for a QAudioFormat.SampleFormat enum member: the only
    thing the code under test reads off it is `.name`."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SampleFormat {self.name}>"


class _FakeSampleFormats:
    Unknown = _FakeSampleFormat("Unknown")
    UInt8 = _FakeSampleFormat("UInt8")
    Int16 = _FakeSampleFormat("Int16")
    Int32 = _FakeSampleFormat("Int32")
    Float = _FakeSampleFormat("Float")


class _FakeAudioFormat:
    SampleFormat = _FakeSampleFormats

    def __init__(self, rate: int = 0, channels: int = 0, fmt=None) -> None:
        self._rate, self._channels, self._fmt = rate, channels, fmt

    def setSampleRate(self, r): self._rate = r
    def setChannelCount(self, c): self._channels = c
    def setSampleFormat(self, f): self._fmt = f
    def sampleRate(self): return self._rate
    def channelCount(self): return self._channels
    def sampleFormat(self): return self._fmt


class _FakeDevice:
    """A microphone that supports EXACTLY the formats it is told to."""

    def __init__(self, preferred: _FakeAudioFormat, supported_names) -> None:
        self._preferred, self._supported = preferred, set(supported_names)

    def isNull(self): return False
    def description(self): return "Fake Float32 Mic"
    def preferredFormat(self): return self._preferred

    def isFormatSupported(self, fmt):
        return getattr(fmt.sampleFormat(), "name", None) in self._supported


class _FakeAudioSource:
    def __init__(self, device, fmt):
        self.device, self.fmt, self.stopped = device, fmt, False
        self.io = _FakeIO(b"")

    def start(self): return self.io
    def stop(self): self.stopped = True


class _FakeTimer:
    def __init__(self):
        self.interval = None
        self.started = False
        self.timeout = types.SimpleNamespace(connect=lambda fn: None)

    def setInterval(self, ms): self.interval = ms
    def start(self): self.started = True
    def stop(self): self.started = False


def _with_fake_qt(fn):
    """Run fn() with PyQt6.QtCore/PyQt6.QtMultimedia replaced by the fakes
    above — never a real QAudioSource, so this suite still opens no
    microphone (the file's own standing constraint)."""
    qtc = types.ModuleType("PyQt6.QtCore")
    qtc.QTimer = _FakeTimer
    qtm = types.ModuleType("PyQt6.QtMultimedia")
    qtm.QAudioFormat = _FakeAudioFormat
    qtm.QAudioSource = _FakeAudioSource
    saved = {k: sys.modules.get(k) for k in ("PyQt6.QtCore", "PyQt6.QtMultimedia")}
    sys.modules["PyQt6.QtCore"] = qtc
    sys.modules["PyQt6.QtMultimedia"] = qtm
    try:
        return fn(qtm)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _start_against(device, recorder):
    def run(qtm):
        class _FakeMediaDevices:
            @staticmethod
            def defaultAudioInput():
                return device

        qtm.QMediaDevices = _FakeMediaDevices
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = recorder.start()
        return ok, out.getvalue()

    return _with_fake_qt(run)


f32_up = lr.Uploader(root, lambda: {})
f32_enqueued = []
f32_up.enqueue = lambda *a, **k: f32_enqueued.append(a)
f32_rec = lr.Recorder(root, "f32test", os.path.join(root, "f32test.pdf"),
                      get_page=lambda: 1, uploader=f32_up)
f32_device = _FakeDevice(_FakeAudioFormat(48000, 2, _FakeSampleFormats.Float), {"Float"})
f32_ok, f32_log = _start_against(f32_device, f32_rec)
check("start() succeeds on a device that offers Float32 and nothing else",
      f32_ok is True, f32_log)
check("...because it took the device's preferred format AS IT IS rather "
      "than forcing Int16 onto a format the device never claimed",
      f32_rec._sample_format == "Float", repr(f32_rec._sample_format))
check("...keeping the negotiated rate and channel count in the header",
      (f32_rec._wav_rate, f32_rec._wav_channels) == (48000, 2),
      repr((f32_rec._wav_rate, f32_rec._wav_channels)))
check("...while the header width is 2 for the converted int16 samples",
      f32_rec._wav_width == 2)
# Drive one tick with real Float32 bytes from the fake device and read
# the flushed WAV back: the conversion has to happen on the way INTO the
# chunk buffer, or the 44-byte header describes 16-bit audio over 32-bit
# float samples (noise, at half the claimed duration).
f32_rec._io = _FakeIO(struct.pack("<4f", -1.0, 0.0, 0.5, 1.0))
f32_rec._start_mono -= (lr.CHUNK_S + 1.0)  # the next tick closes a chunk
f32_rec._tick()
check("a tick closed a chunk and flushed it", len(f32_enqueued) == 1, repr(f32_enqueued))
if f32_enqueued:
    with wave.open(f32_enqueued[0][3], "rb") as _wf:
        f32_frames = _wf.readframes(_wf.getnframes())
        check("the flushed WAV is 16-bit at the negotiated 48 kHz / 2ch",
              (_wf.getsampwidth(), _wf.getframerate(), _wf.getnchannels()) == (2, 48000, 2),
              repr((_wf.getsampwidth(), _wf.getframerate(), _wf.getnchannels())))
    check("...and its samples are the CONVERTED ones, not the raw float bytes",
          f32_frames == _i16(-32767, 0, 16383, 32767), repr(f32_frames))
f32_rec.stop()

section("PR #4 sixth review: a device with nothing usable refuses to "
        "record, with one log line naming the format")
none_rec = lr.Recorder(root, "nonetest", os.path.join(root, "nonetest.pdf"),
                       get_page=lambda: 1, uploader=lr.Uploader(root, lambda: {}))
none_device = _FakeDevice(_FakeAudioFormat(44100, 1, _FakeSampleFormats.Float), set())
none_ok, none_log = _start_against(none_device, none_rec)
check("start() returns False when even the preferred format is refused",
      none_ok is False and not none_rec.is_recording)
check("...and says so once, naming the format it could not use",
      none_log.count("[klausmate]") == 1 and "Float" in none_log, repr(none_log))
unk_rec = lr.Recorder(root, "unktest", os.path.join(root, "unktest.pdf"),
                      get_page=lambda: 1, uploader=lr.Uploader(root, lambda: {}))
unk_device = _FakeDevice(_FakeAudioFormat(44100, 1, _FakeSampleFormats.Unknown), {"Unknown"})
unk_ok, unk_log = _start_against(unk_device, unk_rec)
check("a supported-but-unreadable sample format is refused too, rather "
      "than written into a WAV as if it were Int16",
      unk_ok is False and "Unknown" in unk_log, repr(unk_log))

section("PR #4 sixth review: a device read that ends mid-sample carries "
        "its tail into the next read")
# A 4-byte format read 6 bytes at a time would otherwise lose 2 bytes per
# tick AND start the next read one sample out of phase — permanent
# desync, i.e. noise, not a dropped millisecond.
tail_rec = lr.Recorder(root, "tailtest", os.path.join(root, "tailtest.pdf"),
                       get_page=lambda: 1, uploader=lr.Uploader(root, lambda: {}))
tail_rec._sample_format, tail_rec._sample_width = "Float", 4
_whole = struct.pack("<2f", 0.5, -0.5)
tail_rec._ingest(_whole[:6])
check("a torn read converts only its whole samples", bytes(tail_rec._buffer) == _i16(16383))
tail_rec._ingest(_whole[6:])
check("...and the carried tail completes the next one, in phase",
      bytes(tail_rec._buffer) == _i16(16383, -16383), repr(bytes(tail_rec._buffer)))

# ---------------------------------------------------------------------
# K-280 (1) (Copilot on PR #4): append_segment SUCCEEDED but os.unlink
# raised -- a locked file, a permission blip, a vanished mount. The
# exception was swallowed and the WAV stayed eligible for
# requeue_leftovers, so the next Record transcribed it again (a paid
# call) and appended the SAME segment a second time. Once the durable
# append has happened the chunk is SPENT and must be unappendable even
# when the file itself survives.
# ---------------------------------------------------------------------
section("K-280: a spent WAV is unappendable even when its unlink fails")


class _OsProxy:
    """`lecture_recorder`'s own `os`, with ONE call replaced. Patching
    the real `os.unlink` would reach page_store, tempfile and this test
    file too; this confines the failure to the module under test."""

    def __init__(self, real, unlink):
        self._real, self.unlink = real, unlink

    def __getattr__(self, name):
        return getattr(self._real, name)


_sp_wavs: list = []


def fake_transcribe_spend(key, wav, model, language="en", prompt="", timeout=None):
    _sp_wavs.append(wav)
    return "said over the slide"


def _unlink_denied(path):
    raise OSError(13, "Permission denied")


lr._transcribe = fake_transcribe_spend
_sp_pdf = os.path.join(root, "spendtest.pdf")
_sp_chunk = lr.Chunk(1, 0.0, 30.0)
_sp_p = lr.chunk_path(root, "spendtest", _sp_chunk)
_sp_dir = os.path.dirname(_sp_p)
os.makedirs(_sp_dir, exist_ok=True)
open(_sp_p, "wb").write(b"RIFF S")
sp_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
lr.os = _OsProxy(os, _unlink_denied)
try:
    sp_up.enqueue("spendtest", _sp_pdf, _sp_chunk, _sp_p)
    check("drain() returns — a failed unlink is not fatal to the worker",
          _returns_within(sp_up.drain, 3.0))
finally:
    lr.os = os
_sp_rec = page_store.load_record(root, "spendtest", _sp_pdf, 0)
check("the segment was appended (the durable write happens before the unlink)",
      len(_sp_rec.get("segments") or []) == 1, repr(_sp_rec.get("segments")))
check("the file survived the failed unlink — but no longer under its own, requeueable name",
      not os.path.exists(_sp_p) and len(os.listdir(_sp_dir)) == 1, repr(os.listdir(_sp_dir)))
sp_fresh = lr.Uploader(root, lambda: {"api_key_openai": "k"})
check("a SECOND uploader over the same directory requeues nothing",
      sp_fresh.requeue_leftovers("spendtest", _sp_pdf) == 0, repr(os.listdir(_sp_dir)))
sp_fresh.drain()
_sp_rec2 = page_store.load_record(root, "spendtest", _sp_pdf, 0)
check("...so the segment is in the page record exactly ONCE, with no second paid transcription",
      len(_sp_rec2.get("segments") or []) == 1 and len(_sp_wavs) == 1,
      repr((_sp_rec2.get("segments"), len(_sp_wavs))))
check("...and that same walk unlinked the spent marker, so markers cannot pile up",
      os.listdir(_sp_dir) == [], repr(os.listdir(_sp_dir)))
_sp_chunk2 = lr.Chunk(1, 30.0, 60.0)
_sp_p2 = lr.chunk_path(root, "spendtest", _sp_chunk2)
open(_sp_p2, "wb").write(b"RIFF S2")
sp_up.enqueue("spendtest", _sp_pdf, _sp_chunk2, _sp_p2)
sp_up.drain()
check("the ORDINARY path still plain-unlinks — no marker is left behind at all",
      not os.path.exists(_sp_p2) and os.listdir(_sp_dir) == [], repr(os.listdir(_sp_dir)))

# ---------------------------------------------------------------------
# K-280 (2) (Copilot on PR #4): requeue_leftovers rebuilt every chunk's
# end as t0 + CHUNK_S, but the Chunker closes a chunk EARLY on a page
# change and on Stop -- so a leftover from such a chunk was stored with
# a fabricated t1 running up to 30 s past the real page boundary, unlike
# the Chunk.t1 the first attempt used. The filename carries the real end
# now; the two older shapes still parse, and only THEY fall back.
# ---------------------------------------------------------------------
section("K-280: a requeued leftover keeps its real end time")
_e_pdf = os.path.join(root, "earlytest.pdf")
_e_chunk = lr.Chunk(2, 500.0, 507.0)  # closed after 7 s by a page change
_e_p = lr.chunk_path(root, "earlytest", _e_chunk)
check("chunk_path mints <t0>-<t1>-p<page>.wav, so the real end survives on disk",
      os.path.basename(_e_p) == "500.000-507.000-p0002.wav", os.path.basename(_e_p))
os.makedirs(os.path.dirname(_e_p), exist_ok=True)
open(_e_p, "wb").write(b"RIFF E")
lr._transcribe = (lambda key, wav, model, language="en", prompt="", timeout=None:
                  "seven seconds of it")
e_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
check("the leftover is requeued", e_up.requeue_leftovers("earlytest", _e_pdf) == 1)
e_up.drain()
_e_seg = (page_store.load_record(root, "earlytest", _e_pdf, 1).get("segments") or [None])[0]
check("...and lands with the chunk's REAL end (507.0), not a fabricated t0 + CHUNK_S (530.0) "
      "running 23 s past the page boundary",
      _e_seg is not None and _e_seg.get("t0") == 500.0 and _e_seg.get("t1") == 507.0,
      repr(_e_seg))

_m_dir = os.path.join(root, "recordings", "mixtest")
os.makedirs(_m_dir, exist_ok=True)
open(os.path.join(_m_dir, "20.000-27.000-p0001.wav"), "wb").write(b"RIFF new")
open(os.path.join(_m_dir, "12.250-p0001.wav"), "wb").write(b"RIFF ms")
open(os.path.join(_m_dir, "5-p0001.wav"), "wb").write(b"RIFF legacy")
m_up = lr.Uploader(root, lambda: {"api_key_openai": "k"})
m_seen: list = []
m_up.enqueue = lambda safe, path, chunk, wav: m_seen.append(chunk)
n_mix = m_up.requeue_leftovers("mixtest", os.path.join(root, "mixtest.pdf"))
check("all three name shapes parse — neither older one may become a foreign file",
      n_mix == 3, n_mix)
check("...ordering is by t0 ALONE across mixed shapes, and only the names carrying no end "
      "time fall back to t0 + CHUNK_S",
      m_seen == [lr.Chunk(1, 5.0, 35.0), lr.Chunk(1, 12.25, 42.25), lr.Chunk(1, 20.0, 27.0)],
      repr(m_seen))

raise SystemExit(report())
