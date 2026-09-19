"""The lecture recorder (spec D6, Plan 2): mic audio in, transcript segments out.

A ``Chunker`` cuts the recording into pieces that close at 30 s or on a
page change, whichever comes first — text must never straddle a page,
since ``page_store`` keys a segment on exactly one page. Above the divider
this is pure stdlib (``wave`` for the WAV header, ``queue``/``threading``
for the upload worker): no PyQt6 import at module load time, so the core
is importable and testable without a display. Below the divider,
``Recorder`` is the Qt glue that actually owns a microphone
(``QAudioSource``) and a 250 ms poll timer.

The ``Uploader`` is the other half: one daemon worker, FIFO, that
transcribes a closed chunk's WAV and appends the result to the PDF's page
record (``page_store.append_segment``) — never blocking the UI thread, and
never losing audio: a failed upload (network error, no key, a bad
response) simply keeps the WAV on disk for the next attempt
(``requeue_leftovers`` on the next Record). The worker loop itself must
survive anything a single chunk throws at it (K-256 fix round 1, C1) —
including ``on_segment``, a callback this module hands to Task 5's Qt-side
consumer across a thread boundary — or one bad chunk permanently stops
transcription for the rest of the session.

Transcription is direct-key only: the uploader calls
``openai_client.transcribe`` with the user's own ``api_key_openai`` and
nothing else — no metered routing, no refusal caching, no quota
bookkeeping. Missing a key is handled exactly like any other failure to
transcribe (a network error, a bad response): the WAV simply stays on
disk for the next attempt, and the failure is logged by exception class
and HTTP status only, never the message. Page records are seeded once per PDF
(``page_store.ensure_records``) before the first segment is ever
appended, so a transcript can land even on a PDF nobody has indexed yet.
"""
from __future__ import annotations

import array
import io
import os
import queue
import re
import sys
import threading
import time
import wave
from typing import Callable, NamedTuple

from . import openai_client, page_store

CHUNK_S = 30.0
# How long stop() waits for the worker to put down whatever chunk it is
# holding. Bounded because stop() runs on the MAIN thread at profile
# close: a wedged provider call must cost a two-second pause, never a
# frozen Anki (PR #4 second re-review).
STOP_JOIN_S = 2.0


class Chunk(NamedTuple):
    page: int
    t0: float
    t1: float


class Chunker:
    """A pure state machine: one open span at a time, closed by whichever
    of "30 seconds elapsed" or "the page changed" happens first. A span
    that never advances past its own start (a page change reported at
    the exact instant it opened) is zero-length and is dropped rather
    than emitted — the caller's bookkeeping (page/t0) still moves on."""

    def __init__(self) -> None:
        self.page: int | None = None
        self.t0: float = 0.0
        self.active: bool = False

    def _close(self, t: float) -> Chunk | None:
        return Chunk(self.page, self.t0, t) if t > self.t0 else None

    def start(self, page: int, t: float) -> None:
        self.page = page
        self.t0 = t
        self.active = True

    def tick(self, t: float) -> Chunk | None:
        """Called regularly (the Recorder's poll timer); closes the open
        span once at least CHUNK_S has elapsed, labelled with the ACTUAL
        time ``t`` of this tick — never an idealized ``t0 + CHUNK_S``
        boundary (fix round 1, I2). The WAV written for this chunk holds
        exactly the audio captured between the old t0 and now, so the
        label must say so; an idealized boundary would silently disagree
        with the bytes after any stall (a suspended machine, a GC pause),
        and worse, would then chase the idealized schedule with a burst
        of near-empty catch-up chunks instead of one correctly-labelled
        long one."""
        if not self.active or t - self.t0 < CHUNK_S:
            return None
        chunk = self._close(t)
        self.t0 = t
        return chunk

    def page_changed(self, page: int, t: float) -> Chunk | None:
        if not self.active or page == self.page:
            return None
        chunk = self._close(t)
        self.page = page
        self.t0 = t
        return chunk

    def stop(self, t: float) -> Chunk | None:
        if not self.active:
            return None
        chunk = self._close(t)
        self.active = False
        return chunk


def wav_bytes(pcm: bytes, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    """PCM -> a standard RIFF/WAVE blob, headered with the ACTUAL negotiated
    rate/channel-count/sample-width (fix round 1, I3). The Klaus Plus
    service meters lecture minutes by reading this header back
    (``wav_seconds`` in ``service/klausplus/proxy.py``), so a header that
    doesn't match the real audio either bills the wrong number of minutes
    or hands a transcription model PCM at a rate it didn't ask for."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


# Every ``QAudioFormat.SampleFormat`` Qt can hand back, by the ``.name``
# the enum member carries, mapped to the ``array`` type code that reads
# one such sample. "Float32" is not a Qt spelling — Qt's is plain
# "Float" — but it is what the format is universally called, so it is
# kept as an alias rather than refused. A name that is NOT in here
# (Qt's own "Unknown", or whatever a future Qt adds) is refused at
# ``Recorder.start()``: silence is better than noise written into a WAV
# under a header claiming it is 16-bit.
SAMPLE_FORMAT_CODES = {
    "UInt8": "B", "Int16": "h", "Int32": "i", "Float": "f", "Float32": "f",
}


def sample_format_name(sample_format) -> str:
    """The plain name of a ``QAudioFormat.SampleFormat`` — read off the
    enum member rather than imported, so this half of the module stays
    Qt-free and a test can hand it the bare string instead."""
    return str(getattr(sample_format, "name", sample_format))


def pcm_to_int16(data: bytes, sample_format) -> bytes:
    """Whatever the device negotiated -> little-endian Int16 PCM.

    PR #4 sixth review: plenty of inputs expose Float as their ONLY
    sample format, so demanding Int16 of them means ``QAudioSource``
    never starts and Record is a dead button. Take the format the device
    actually offers and convert here instead, on the way into the chunk
    buffer — which is what keeps ``wav_bytes``' header width at 2
    whatever the microphone speaks, and the Klaus Plus service (which
    meters lecture minutes by reading that header back) honest.

    ``data`` must be a whole number of samples; the caller owns the
    torn-tail carry, since dropping a partial sample would leave every
    later read one byte out of phase.
    """
    name = sample_format_name(sample_format)
    code = SAMPLE_FORMAT_CODES.get(name)
    if code is None:
        raise ValueError(f"unsupported sample format {name!r}")
    if code == "h" and sys.byteorder == "little":
        return bytes(data)
    src = array.array(code)
    src.frombytes(bytes(data))
    if code == "f":
        # Clamp first: a float sample may legitimately overshoot ±1.0,
        # and an unclamped scale wraps it to the opposite rail — a click.
        out = array.array(
            "h", [int(min(1.0, max(-1.0, v)) * 32767.0) for v in src])
    elif code == "i":
        out = array.array("h", [v >> 16 for v in src])
    elif code == "B":
        out = array.array("h", [(v - 128) << 8 for v in src])
    else:
        out = array.array("h", src)
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()


def chunk_path(user_files: str, pdf_safe: str, chunk: Chunk) -> str:
    """Millisecond precision in the name, not whole seconds (PR #4,
    Copilot + Codex): two chunks can close inside one second — a page
    bounce, or Stop then Record on the same page — and a truncated t0
    gave them ONE filename, so the second _flush overwrote the first's
    audio and the asynchronous upload then unlinked a WAV holding bytes
    it had never transcribed.

    The END time is in the name too (K-280, Copilot on PR #4): the
    Chunker closes a chunk early on a page change and on Stop, so
    rebuilding a leftover's end as ``t0 + CHUNK_S`` — the only thing
    ``requeue_leftovers`` could do without it — filed a 7-second chunk
    as 30 seconds of speech running past the page it was actually said
    over. This is the ONE place a name is minted."""
    name = f"{chunk.t0:.3f}-{chunk.t1:.3f}-p{chunk.page:04d}.wav"
    return os.path.join(user_files, "recordings", pdf_safe, name)


# Three shapes, newest first: "<t0>-<t1>-p0001.wav", the two-field
# millisecond name that predates the end time, and an older Klaus's
# whole-second "12-p0001.wav" — both of the older two still parse and
# still upload, falling back to t0 + CHUNK_S for the end they do not
# carry. Matched with fullmatch: a name this regex misses is a foreign
# file (an orphaned lecture), and — the point of anchoring BOTH ends —
# so is a spent chunk's retired "....wav.spent" marker.
_LEFTOVER_RE = re.compile(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?-p(\d{4})\.wav")

# What _spend renames a WAV to when it cannot delete it. Anything
# _LEFTOVER_RE cannot match would do; a suffix keeps the original name
# readable for anyone looking at the directory.
_SPENT_SUFFIX = ".spent"


def _spend(wav_path: str) -> None:
    """Retire a chunk whose transcript is already durably stored.

    Unlinking is the normal end of a chunk's life. When it FAILS (a
    locked file, a permission blip, a vanished mount) the audio must
    become unrequeueable anyway (K-280, Copilot on PR #4): the append
    that just happened is durable, so a surviving WAV is transcribed
    again — a paid call — by the next Record's ``requeue_leftovers``,
    which then appends the SAME segment a second time. Renaming it out
    of the requeue namespace is the fallback, and ``requeue_leftovers``
    unlinks any marker it walks past so they cannot pile up. If even
    that fails, say so once: a duplicated segment is the worst outcome
    here and it should not be silent."""
    try:
        os.unlink(wav_path)
        return
    except OSError:
        pass
    try:
        os.replace(wav_path, wav_path + _SPENT_SUFFIX)
    except OSError as exc:
        print(f"[klausmate] lecture recorder: could not retire spent "
              f"{os.path.basename(wav_path)} ({exc.__class__.__name__}); "
              f"it may be transcribed and appended again")

# Module-level indirection so tests can swap the network call for a fake
# without touching openai_client itself (the house pattern — see
# embeddings.py's own module-level provider hooks).
_transcribe = openai_client.transcribe


class Uploader:
    """One daemon worker; FIFO; a failed chunk keeps its WAV."""

    def __init__(self, user_files: str, get_config: Callable[[], dict],
                on_segment: Callable[[str, int], None] | None = None) -> None:
        self._q: queue.Queue = queue.Queue()
        self._user_files, self._get_config, self._on_segment = user_files, get_config, on_segment
        self._last_text: dict[str, str] = {}
        self._seeded: set[str] = set()
        self._thread: threading.Thread | None = None
        # Set by stop() BEFORE the sentinel goes in, so a chunk already in
        # flight can tell that the profile it belongs to is gone. ONE-WAY:
        # nothing clears it again (see enqueue); K-276's verify greps
        # this file for the assignment that used to reopen it.
        self._closed: bool = False

    def enqueue(self, pdf_safe: str, pdf_path: str, chunk: Chunk, wav_path: str) -> None:
        """Queue a closed chunk — unless this uploader is stopped, in
        which case the WAV simply stays on disk for the NEXT uploader's
        ``requeue_leftovers``.

        ``_closed`` is a one-way latch (PR #4 fifth re-review). Clearing
        it here reopened an uploader whose old worker could still be
        inside ``_one()``, past ``stop()``'s bounded join: that worker
        then read ``_closed`` as False when its transcription returned
        and appended + unlinked — while the requeued copy of the same
        WAV was processed too. Production never reopens one anyway
        (``_stop_lecture_uploader`` drops the singleton; ``uploader()``
        builds a fresh instance), so refusing is both the safe answer
        and the real one.
        """
        if self._closed:
            print(f"[klausmate] lecture recorder: uploader stopped, "
                  f"keeping {os.path.basename(wav_path)} for the next one")
            return
        self._q.put((pdf_safe, pdf_path, chunk, wav_path))
        self._ensure_thread()

    def queued(self) -> int:
        return self._q.qsize()

    def pending(self) -> int:
        """Chunks still owed a ``task_done()`` — what ``drain()`` waits on,
        NOT ``queued()`` (final review, I-2). The worker ``get()``s an item
        BEFORE transcribing it, so ``qsize()`` is already 0 while the last
        chunk is still uploading. Stopping a recording schedules that PDF's
        re-index once this reaches 0 (``__init__._request_index_when_idle``);
        on ``qsize()`` the re-index would read the page records before the
        tail chunk's transcript had landed — the end of every lecture
        unembedded."""
        return self._q.unfinished_tasks

    def _ensure_thread(self) -> None:
        # `not is_alive()` (fix round 1, C1) catches a worker that has
        # already exited — after `stop()`'s sentinel, or after a defect
        # elsewhere let an exception through — so a later enqueue always
        # gets a live worker instead of silently queueing into a corpse.
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                # The stop sentinel is a queue item like any other — it
                # must get its own task_done() (fix round 1, C1), or the
                # unfinished-task count `drain()`/`join()` waits on never
                # reaches zero and every future drain() hangs forever.
                # Nothing can be queued BEHIND it: `_closed` is latched
                # before the sentinel goes in and `enqueue` refuses from
                # then on (PR #4 fifth re-review), so the sentinel is
                # always a real exit order.
                self._q.task_done()
                return
            try:
                self._one(*item)
            except Exception as exc:
                # A single chunk must never take the whole worker down —
                # on_segment is caller-supplied (Task 5's Qt-side
                # consumer) and page_store.append_segment can fail too
                # (a full or read-only disk). Name the exception CLASS
                # only: never its message (could echo transcript text)
                # and never a path outside user_files.
                _, _, _, wav_path = item
                print(f"[klausmate] lecture recorder: chunk failed ({exc.__class__.__name__}), "
                      f"keeping {os.path.basename(wav_path)}")
            finally:
                self._q.task_done()

    def drain(self) -> None:
        """Tests only: block until every enqueued chunk (so far) has been
        processed. Works whether or not a worker thread is running —
        ``Queue.join()`` blocks on the same unfinished-task count either
        way."""
        self._q.join()

    def _ensure_page(self, pdf_safe: str, pdf_path: str) -> None:
        """Seed this PDF's page records once, lazily, before its first
        segment ever lands — a transcript may be the FIRST thing a PDF
        ever grows (idempotent; never overwrites existing segments).

        Marked seeded only AFTER ensure_records actually succeeds (fix
        round 1, m5): marking it first would mean a transient failure
        (a momentary disk hiccup) is never retried for the life of this
        Uploader, silently leaving every later segment on this PDF
        without slide_text."""
        if pdf_safe in self._seeded:
            return
        try:
            from . import pdf_handler
            pages = pdf_handler.load_pages(self._user_files, pdf_safe) or []
            page_store.ensure_records(self._user_files, pdf_safe, pdf_path, pages)
        except Exception as exc:  # noqa: BLE001 -- seeding must never block the segment write
            print(f"[klausmate] lecture recorder: page seeding failed for {pdf_safe}: {exc}")
            return
        self._seeded.add(pdf_safe)

    def _one(self, pdf_safe: str, pdf_path: str, chunk: Chunk, wav_path: str) -> None:
        if self._closed:
            # Queued BEHIND stop()'s sentinel (PR #4 third re-review):
            # `_closed` is set before the sentinel goes in, but every
            # chunk already on the queue still reaches this worker
            # first. Transcribing them would be a paid call per chunk
            # whose result the post-transcription `_closed` check below
            # then throws away. Bail before the config is even read; the
            # WAV stays for the next Record's requeue_leftovers, and the
            # loop's own `finally` still task_done()s this item.
            print(f"[klausmate] lecture recorder: uploader closed, "
                  f"keeping queued {os.path.basename(wav_path)}")
            return
        cfg = self._get_config() or {}
        model = str(cfg.get("transcription_model") or "gpt-4o-mini-transcribe")
        key = str(cfg.get("api_key_openai") or "").strip()
        if not key:
            print(f"[klausmate] lecture recorder: no OpenAI key, keeping {os.path.basename(wav_path)}")
            return
        prompt = self._last_text.get(pdf_safe, "")[-800:]
        try:
            wav = open(wav_path, "rb").read()
            text = _transcribe(key, wav, model, prompt=prompt)
        except openai_client.OpenAIError as exc:
            # Class and status ONLY, never the message (PR #4, Codex):
            # openai_client._request folds up to 300 bytes of the provider's
            # error body into it, and that body can echo request-derived
            # text — here the continuity prompt, which IS the previous
            # segment's transcript. Same rule the judge follows.
            print(f"[klausmate] transcription failed, keeping {os.path.basename(wav_path)} "
                  f"(OpenAIError status={exc.status})")
            return
        except Exception as exc:
            print(f"[klausmate] transcription failed, keeping {os.path.basename(wav_path)} "
                  f"({exc.__class__.__name__})")
            return
        if self._closed:
            # Torn down while this chunk was in flight (PR #4 second
            # re-review). Appending now would write a page record behind a
            # profile that is already closing, and unlinking would destroy
            # the only copy of this audio just as the NEXT profile's
            # requeue_leftovers scans the same directory — the same chunk
            # landing twice, or racing that new worker's own unlink. Keep
            # the WAV instead: one re-upload is cheap, a duplicate segment
            # is not.
            print(f"[klausmate] lecture recorder: uploader closed mid-upload, "
                  f"keeping {os.path.basename(wav_path)}")
            return
        text = text.strip()
        if text:
            self._ensure_page(pdf_safe, pdf_path)
            page_store.append_segment(self._user_files, pdf_safe, pdf_path, chunk.page - 1, chunk.t0, chunk.t1, text)
            self._last_text[pdf_safe] = text
        _spend(wav_path)
        # AFTER the unlink, and never fatal (PR #4 fourth re-review). The
        # append above is the durable write; `on_segment` is only a
        # notification to Qt. With it inside the block above, a raising
        # consumer reached `_loop`, which keeps the WAV for retry — so
        # the next `requeue_leftovers` transcribed (a paid call) and
        # appended the SAME segment a second time. `_spend` closes the
        # other half of that hole: a failed unlink must not leave the
        # WAV requeueable either (K-280).
        if text and self._on_segment:
            try:
                self._on_segment(pdf_safe, chunk.page - 1)
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] lecture recorder: on_segment failed "
                      f"({exc.__class__.__name__}) after the segment was stored")

    def requeue_leftovers(self, pdf_safe: str, pdf_path: str) -> int:
        d = os.path.join(self._user_files, "recordings", pdf_safe)
        if not os.path.isdir(d):
            return 0
        # Numeric t0 (fix round 1, m3) — a plain filename sort put "1000"
        # before "90", which only ever mattered for the continuity prompt
        # (append_segment re-sorts stored segments by t0 regardless), but
        # is wrong the moment two leftovers span a reboot or a filename
        # isn't zero-padded.
        matches = []
        for name in os.listdir(d):
            if name.endswith(_SPENT_SUFFIX):
                # A chunk `_spend` could not delete. Its transcript is
                # already stored, so the file is pure garbage — take the
                # free chance to clear it, and never mind if that fails
                # too (the next walk tries again).
                try:
                    os.unlink(os.path.join(d, name))
                except OSError:
                    pass
                continue
            m = _LEFTOVER_RE.fullmatch(name)
            if m:
                t0 = float(m.group(1))
                # Only a name written before the end time was carried
                # (or by an older Klaus) has to be guessed at.
                t1 = float(m.group(2)) if m.group(2) else t0 + CHUNK_S
                matches.append((t0, t1, int(m.group(3)), name))
        matches.sort(key=lambda row: row[0])
        for t0, t1, page, name in matches:
            self.enqueue(pdf_safe, pdf_path, Chunk(page, t0, t1), os.path.join(d, name))
        return len(matches)

    def stop(self) -> None:
        """Close the uploader and wait, briefly, for the worker to let go.

        ``_closed`` is set BEFORE the sentinel so a chunk already inside
        ``_one()`` sees it the moment its transcription returns; the join
        then makes "the uploader is stopped" true for the caller as well,
        not merely scheduled — ``_stop_lecture_uploader`` drops the
        singleton the instant this returns. Bounded by ``STOP_JOIN_S``:
        this runs on the main thread at profile close.
        """
        self._closed = True
        self._q.put(None)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(STOP_JOIN_S)


# ---- Qt glue ----------------------------------------------------------

TICK_MS = 250


class Recorder:
    """Owns one microphone capture for one PDF. Never constructed with a
    real audio backend by this module's own tests (offscreen-Qt coverage
    of the actual QAudioSource is a separate task) — every Qt call is
    defensive, since a missing input device or a headless machine must
    degrade to "no recording", not a crash."""

    def __init__(self, user_files: str, pdf_safe: str, pdf_path: str,
                get_page: Callable[[], int], on_status: Callable[[float, int], None] | None = None,
                uploader: "Uploader | None" = None) -> None:
        self._user_files = user_files
        self._pdf_safe = pdf_safe
        self._pdf_path = pdf_path
        self._get_page = get_page
        self._on_status = on_status
        # A last-resort fallback: real callers (Task 5) always pass their
        # own shared Uploader, which is the one wired to a real get_config.
        self._uploader = uploader if uploader is not None else Uploader(user_files, lambda: {})
        self._chunker = Chunker()
        self._source = None
        self._io = None
        self._timer = None
        self._buffer = bytearray()
        self._start_mono = 0.0
        # Epoch-anchored (fix round 1, m4): `_epoch0` is time.time() at
        # Record, so every chunk's t0/t1 is a real wall-clock timestamp
        # that still sorts and compares across separate sessions and
        # reboots — raw time.monotonic() only means "seconds since some
        # unspecified reference point" (often boot), which two lectures
        # recorded a day apart cannot be told apart by. `_now()` still
        # advances by monotonic deltas, so a wall-clock adjustment
        # mid-recording (NTP, DST) can't make a chunk's own span run
        # backwards.
        self._epoch0 = 0.0
        self._recording = False
        # The format actually negotiated with the device (fix round 1,
        # I3) — defaults match the old hardcoded assumption, used only if
        # something reads them before a successful start(). `_wav_width`
        # is 2 for good now (PR #4 sixth review): `_ingest` converts every
        # captured buffer to Int16, so the header never describes the
        # device's own sample width.
        self._wav_rate = 16000
        self._wav_channels = 1
        self._wav_width = 2
        self._sample_format = "Int16"
        self._sample_width = 2
        # A device read can end mid-sample; its tail belongs to the next
        # one. Dropping it would put every later read one byte out of
        # phase on a 4-byte format — noise, not a lost millisecond.
        self._pcm_tail = b""

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed(self) -> float:
        return (time.monotonic() - self._start_mono) if self._recording else 0.0

    @property
    def queued(self) -> int:
        """How many chunks still owe a transcript — the uploader's
        ``pending()``, NOT its ``queued()`` (PR #4 second re-review). The
        worker ``get()``s a chunk before transcribing it, so the queue
        length is already 0 while an upload is running, and the bar read
        "0 to transcribe" for the whole of it while
        ``_request_index_when_idle`` was still waiting on that same chunk.
        One number, one meaning."""
        return self._uploader.pending()

    def _now(self) -> float:
        return self._epoch0 + (time.monotonic() - self._start_mono)

    def _ingest(self, data: bytes) -> None:
        """The ONE way captured audio enters the chunk buffer, so that
        buffer only ever holds little-endian Int16 PCM whatever the
        device negotiated (PR #4 sixth review) — both readers, the tick
        and stop()'s final pull, go through here or the two would
        disagree about what the bytes mean."""
        if not data:
            return
        data = self._pcm_tail + bytes(data)
        usable = len(data) - (len(data) % self._sample_width)
        self._pcm_tail, data = data[usable:], data[:usable]
        if not data:
            return
        try:
            self._buffer.extend(pcm_to_int16(data, self._sample_format))
        except Exception as exc:
            print(f"[klausmate] lecture recorder: sample conversion failed: {exc}")

    def start(self) -> bool:
        if self._recording:
            # m1: a second Record press must not open a second
            # QAudioSource and orphan the first (mic stays hot, the OS
            # recording indicator never turns off).
            return True
        try:
            from PyQt6.QtCore import QTimer
            from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        except Exception as exc:
            print(f"[klausmate] lecture recorder: PyQt6 multimedia unavailable: {exc}")
            return False
        try:
            device = QMediaDevices.defaultAudioInput()
            if device is None or device.isNull():
                print("[klausmate] lecture recorder: no audio input device")
                return False
            # The aqt.sound.QtAudioInputRecorder shape (I3): ask for the
            # ideal format first, and only fall back to whatever the
            # device actually prefers when the ideal one is refused —
            # never demand 16 kHz mono Int16 unconditionally, since a
            # device that can't deliver it then records silence (I1) or,
            # worse, real audio under a header that describes the wrong
            # rate (a 3x quota/duration mismatch on Klaus Plus).
            ideal = QAudioFormat()
            ideal.setSampleRate(16000)
            ideal.setChannelCount(1)
            ideal.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if device.isFormatSupported(ideal):
                fmt = ideal
            else:
                # PR #4 sixth review: forcing Int16 onto the preferred
                # format asks the device for something it never claimed
                # to have — plenty of inputs expose Float as their ONLY
                # sample format, and QAudioSource then simply fails to
                # start, so Record was silently unavailable with no
                # message anywhere. Negotiate honestly: take the
                # preferred format AS IT IS, and convert its samples
                # ourselves on the way into the chunk buffer
                # (`pcm_to_int16`), so the WAV header's width stays 2
                # whatever the microphone speaks.
                fmt = device.preferredFormat()
                if not device.isFormatSupported(fmt):
                    print("[klausmate] lecture recorder: device supports neither 16 kHz "
                          "mono Int16 nor its own preferred format "
                          f"({sample_format_name(fmt.sampleFormat())} @ "
                          f"{int(fmt.sampleRate())} Hz); recording unavailable")
                    return False
            name = sample_format_name(fmt.sampleFormat())
            if name not in SAMPLE_FORMAT_CODES:
                print(f"[klausmate] lecture recorder: unreadable sample format {name!r} @ "
                      f"{int(fmt.sampleRate())} Hz; recording unavailable")
                return False
            self._sample_format = name
            self._sample_width = array.array(SAMPLE_FORMAT_CODES[name]).itemsize
            self._wav_rate = int(fmt.sampleRate())
            self._wav_channels = max(1, int(fmt.channelCount()))
            # Always 2, never the device's own bytesPerSample: every
            # captured buffer is converted to Int16 before it reaches the
            # buffer, so the header can never disagree with the bytes.
            self._wav_width = 2
            print(f"[klausmate] lecture recorder: recording at {self._wav_rate} Hz, "
                  f"{self._wav_channels}ch, {name} -> 16-bit on {device.description()}")
            source = QAudioSource(device, fmt)
            io_dev = source.start()
            if io_dev is None:
                print("[klausmate] lecture recorder: failed to start audio input")
                return False
        except Exception as exc:
            print(f"[klausmate] lecture recorder: could not open audio input: {exc}")
            return False
        try:
            timer = QTimer()
            timer.setInterval(TICK_MS)
            timer.timeout.connect(self._tick)
        except Exception as exc:
            print(f"[klausmate] lecture recorder: could not create timer: {exc}")
            try:
                source.stop()
            except Exception:
                pass
            return False
        self._source, self._io, self._timer = source, io_dev, timer
        self._buffer = bytearray()
        self._pcm_tail = b""
        self._epoch0 = time.time()
        self._start_mono = time.monotonic()
        self._chunker.start(int(self._get_page() or 1), self._epoch0)
        self._recording = True
        timer.start()
        return True

    def _tick(self) -> None:
        try:
            data = bytes(self._io.readAll()) if self._io is not None else b""
        except Exception as exc:
            print(f"[klausmate] lecture recorder: audio read failed: {exc}")
            data = b""
        self._ingest(data)
        now = self._now()
        try:
            page = int(self._get_page() or self._chunker.page)
        except Exception as exc:
            print(f"[klausmate] lecture recorder: get_page failed: {exc}")
            page = self._chunker.page
        chunk = None
        try:
            chunk = (self._chunker.page_changed(page, now) if page != self._chunker.page
                    else self._chunker.tick(now))
        except Exception as exc:
            print(f"[klausmate] lecture recorder: chunker step failed: {exc}")
        if chunk is not None:
            self._flush(chunk)
        if self._on_status:
            try:
                self._on_status(self.elapsed, self.queued)
            except Exception as exc:
                print(f"[klausmate] lecture recorder: on_status failed: {exc}")

    def _flush(self, chunk: Chunk) -> None:
        try:
            data, self._buffer = bytes(self._buffer), bytearray()
            if not data:
                # I1: an empty buffer would still be a "valid" 44-byte
                # RIFF/WAVE with zero frames — the Plus proxy's own
                # wav_seconds rejects it as incomplete, so it can never
                # transcribe and would simply be re-uploaded by
                # requeue_leftovers on every subsequent Record, forever.
                return
            path = chunk_path(self._user_files, self._pdf_safe, chunk)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(wav_bytes(data, rate=self._wav_rate, channels=self._wav_channels, width=self._wav_width))
            self._uploader.enqueue(self._pdf_safe, self._pdf_path, chunk, path)
        except Exception as exc:
            print(f"[klausmate] lecture recorder: could not write chunk: {exc}")

    def stop(self) -> None:
        if not self._recording:
            return
        self._recording = False
        try:
            # m2: read the device ONE more time before closing the last
            # chunk, or up to TICK_MS of trailing audio is discarded —
            # which is exactly what made the final chunk of every
            # recording empty (feeding I1).
            if self._io is not None:
                self._ingest(bytes(self._io.readAll()))
        except Exception as exc:
            print(f"[klausmate] lecture recorder: final audio read failed: {exc}")
        try:
            chunk = self._chunker.stop(self._now())
            if chunk is not None:
                self._flush(chunk)
        except Exception as exc:
            print(f"[klausmate] lecture recorder: closing the last chunk failed: {exc}")
        try:
            if self._timer is not None:
                self._timer.stop()
        except Exception as exc:
            print(f"[klausmate] lecture recorder: timer stop failed: {exc}")
        try:
            if self._source is not None:
                self._source.stop()
        except Exception as exc:
            print(f"[klausmate] lecture recorder: audio source stop failed: {exc}")
        self._timer = self._source = self._io = None
