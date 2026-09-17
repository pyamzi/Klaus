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
never losing audio: a failed upload (network error, no key, a Klaus Plus
refusal) simply keeps the WAV on disk for the next attempt
(``requeue_leftovers`` on the next Record). The worker loop itself must
survive anything a single chunk throws at it (K-256 fix round 1, C1) —
including ``on_segment``, a callback this module hands to Task 5's Qt-side
consumer across a thread boundary — or one bad chunk permanently stops
transcription for the rest of the session.

Klaus Plus (2026-09-16, after this plan was written): when Plus is active
the uploader calls ``openai_client.transcribe`` exactly the way
``embeddings.py`` calls ``embed`` on the Plus path — no provider key,
routed through ``plus.endpoint(cfg, "transcribe")`` — and a 401/402/426
is remembered via ``plus.note_refusal`` through the package's
``patch_config`` (a PATCH writer; the plain ``write_config`` replaces the
whole stored config and must never be the sink for a one-key update). A
successful metered call's response headers are hashed through
``plus.note_quota`` the same way. Page records are seeded once per PDF
(``page_store.ensure_records``) before the first segment is ever
appended, so a transcript can land even on a PDF nobody has indexed yet.
"""
from __future__ import annotations

import io
import os
import queue
import re
import threading
import time
import wave
from typing import Callable, NamedTuple

from . import openai_client, page_store, plus

CHUNK_S = 30.0


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


def chunk_path(user_files: str, pdf_safe: str, chunk: Chunk) -> str:
    name = f"{int(chunk.t0)}-p{chunk.page:04d}.wav"
    return os.path.join(user_files, "recordings", pdf_safe, name)


_LEFTOVER_RE = re.compile(r"(\d+)-p(\d{4})\.wav$")

# Module-level indirection so tests can swap the network call for a fake
# without touching openai_client itself (the house pattern — see
# embeddings.py's own module-level provider hooks).
_transcribe = openai_client.transcribe


def _patch_config_sink() -> Callable[[dict], None] | None:
    """The package's ``patch_config``, reached lazily: this module is
    aqt-free and must not import ``klausmate/__init__.py`` (which imports
    aqt) at module top. Mirrors embeddings.py's own lazy lookup exactly —
    one MERGE writer every ``plus.*`` call must use, never the package's
    plain ``write_config``, which replaces the whole stored config."""
    pkg = __import__(__package__, fromlist=["patch_config"])
    return getattr(pkg, "patch_config", None)


class Uploader:
    """One daemon worker; FIFO; a failed chunk keeps its WAV."""

    def __init__(self, user_files: str, get_config: Callable[[], dict],
                on_segment: Callable[[str, int], None] | None = None) -> None:
        self._q: queue.Queue = queue.Queue()
        self._user_files, self._get_config, self._on_segment = user_files, get_config, on_segment
        self._last_text: dict[str, str] = {}
        self._seeded: set[str] = set()
        self._thread: threading.Thread | None = None

    def enqueue(self, pdf_safe: str, pdf_path: str, chunk: Chunk, wav_path: str) -> None:
        self._q.put((pdf_safe, pdf_path, chunk, wav_path))
        self._ensure_thread()

    def queued(self) -> int:
        return self._q.qsize()

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
        cfg = self._get_config() or {}
        model = str(cfg.get("transcription_model") or "gpt-4o-mini-transcribe")
        key = str(cfg.get("api_key_openai") or "").strip()
        on_plus = plus.active(cfg)
        if not key and not on_plus:
            print(f"[klausmate] lecture recorder: no OpenAI key and no Klaus Plus, keeping {os.path.basename(wav_path)}")
            return
        prompt = self._last_text.get(pdf_safe, "")[-800:]
        try:
            wav = open(wav_path, "rb").read()
            if on_plus:
                text = _transcribe("", wav, model, prompt=prompt, endpoint=plus.endpoint(cfg, "transcribe"),
                                   on_headers=lambda h: plus.note_quota(cfg, h, _patch_config_sink()))
            else:
                text = _transcribe(key, wav, model, prompt=prompt)
        except openai_client.OpenAIError as exc:
            if on_plus and exc.status in (401, 402, 426):
                sink = _patch_config_sink()
                if sink is None:
                    print("[klausmate] Klaus Plus refusal not cached: package has no patch_config")
                else:
                    plus.note_refusal(cfg, exc.status, sink, message=exc.user_message())
            print(f"[klausmate] transcription failed, keeping {os.path.basename(wav_path)}: {exc}")
            return
        except Exception as exc:
            print(f"[klausmate] transcription failed, keeping {os.path.basename(wav_path)}: {exc}")
            return
        if text.strip():
            self._ensure_page(pdf_safe, pdf_path)
            page_store.append_segment(self._user_files, pdf_safe, pdf_path, chunk.page - 1, chunk.t0, chunk.t1, text.strip())
            self._last_text[pdf_safe] = text.strip()
            if self._on_segment:
                self._on_segment(pdf_safe, chunk.page - 1)
        try:
            os.unlink(wav_path)
        except OSError:
            pass

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
            m = _LEFTOVER_RE.match(name)
            if m:
                matches.append((int(m.group(1)), int(m.group(2)), name))
        matches.sort(key=lambda row: row[0])
        for t0, page, name in matches:
            self.enqueue(pdf_safe, pdf_path, Chunk(page, float(t0), float(t0) + CHUNK_S), os.path.join(d, name))
        return len(matches)

    def stop(self) -> None:
        self._q.put(None)


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
        # something reads them before a successful start().
        self._wav_rate = 16000
        self._wav_channels = 1
        self._wav_width = 2

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed(self) -> float:
        return (time.monotonic() - self._start_mono) if self._recording else 0.0

    @property
    def queued(self) -> int:
        return self._uploader.queued()

    def _now(self) -> float:
        return self._epoch0 + (time.monotonic() - self._start_mono)

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
                fmt = device.preferredFormat()
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            self._wav_rate = int(fmt.sampleRate())
            self._wav_channels = max(1, int(fmt.channelCount()))
            self._wav_width = max(1, int(fmt.bytesPerSample()))
            print(f"[klausmate] lecture recorder: recording at {self._wav_rate} Hz, "
                  f"{self._wav_channels}ch, {self._wav_width * 8}-bit on {device.description()}")
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
        if data:
            self._buffer.extend(data)
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
                self._on_status(self.elapsed, self._uploader.queued())
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
                self._buffer.extend(bytes(self._io.readAll()))
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
