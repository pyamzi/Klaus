"""One save pipeline for annotation bakes (PDF reader 1/5).

Both viewers write the annotations JSON, then call ``pipeline().request(name)``.
This debounces (``DEBOUNCE_MS``, restarted on every request) and bakes the JSON
into the real PDF on a background worker: at most ONE worker per PDF at a time
(a request that lands mid-bake sets an "again" flag, so the next bake starts
only after the first returns and sees the newer JSON); different PDFs bake
concurrently. Each successful bake's bookkeeping runs on the main thread
through ``run_on_main``.

Everything above the "Qt glue" divider is aqt-free: timers, the main-thread
hop and the fingerprint pin are injected, so tests drive it with fakes.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

DEBOUNCE_MS = 500  # defined once; K-085 (Klaus edits reach the file in <1s)


class SavePipeline:
    def __init__(
        self,
        ufd: str,
        run_on_main: Callable[[Callable], None],
        start_timer: Callable[[str, int, Callable], None],
        pin: Callable[[str, Optional[tuple]], None],
    ) -> None:
        self._ufd = ufd
        self._run_on_main = run_on_main
        self._start_timer = start_timer
        self._pin = pin
        self._cond = threading.Condition()
        self._gen: dict = {}  # name -> debounce generation (last request wins)
        self._pending: set = set()  # requested, timer not yet fired
        self._running: set = set()  # names with a live worker
        self._again: set = set()  # requested again while running
        self._failed: set = set()
        self._subs: list = []

    # ---- public ---------------------------------------------------------

    def request(self, name: str) -> None:
        """(Re)start the debounce for ``name``. Safe to call often."""
        with self._cond:
            gen = self._gen.get(name, 0) + 1
            self._gen[name] = gen
            self._pending.add(name)
        try:
            self._start_timer(name, DEBOUNCE_MS, lambda: self._fire(name, gen))
        except Exception as exc:
            print(f"[klausmate] could not schedule bake for {name}: {exc}")
            self._fire(name, gen)

    def flush(self, name: Optional[str] = None, timeout: float = 10.0) -> bool:
        """Run pending bakes now and wait (up to ``timeout`` s) for the
        named PDF — or every PDF — to go idle. True when idle."""
        with self._cond:
            names = {name} if name is not None else self._pending | self._running
            due = [(n, self._gen.get(n, 0)) for n in names if n in self._pending]
        for n, gen in due:
            self._fire(n, gen)
        deadline = time.monotonic() + timeout
        with self._cond:
            while any(n in self._pending or n in self._running for n in names):
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True

    def subscribe(self, cb: Callable[[str, str], None]) -> Callable[[], None]:
        """``cb(event, name)`` for "saved", "failed" and "records" (marks the
        bake dropped were removed; reload them). Returns an unsubscriber."""
        self._subs.append(cb)

        def _unsubscribe() -> None:
            try:
                self._subs.remove(cb)
            except ValueError:
                pass

        return _unsubscribe

    def failed_names(self) -> set:
        with self._cond:
            return set(self._failed)

    def retry(self, name: str) -> None:
        self.request(name)

    # ---- internals ------------------------------------------------------

    def _fire(self, name: str, gen: int) -> None:
        with self._cond:
            if self._gen.get(name) != gen or name not in self._pending:
                return  # superseded by a newer request, or already run
            self._pending.discard(name)
            if name in self._running:
                self._again.add(name)  # the live worker loops once more
                return
            self._running.add(name)
        try:
            threading.Thread(
                target=self._work, args=(name,), name="klausmate-bake", daemon=True
            ).start()
        except Exception as exc:
            print(f"[klausmate] bake thread failed to start: {exc}")
            self._finish(name)

    def _finish(self, name: str) -> None:
        with self._cond:
            self._running.discard(name)
            self._cond.notify_all()

    def _work(self, name: str) -> None:
        try:
            while True:
                self._bake_once(name)
                with self._cond:
                    if name in self._again:
                        self._again.discard(name)
                        continue
                    self._running.discard(name)
                    self._cond.notify_all()
                    return
        except BaseException:
            self._finish(name)
            raise

    def _bake_once(self, name: str) -> None:
        from . import pdf_handler

        rep: dict = {}
        try:
            print(f"[klausmate] bake started: {name}")
            ok = pdf_handler.bake_annotations(self._ufd, name, report=rep)
            print(f"[klausmate] bake finished: {name} ({'ok' if ok else 'FAILED'})")
        except Exception as exc:
            print(f"[klausmate] bake worker error for {name}: {exc}")
            ok = False
        if ok:
            with self._cond:
                self._failed.discard(name)
            self._run_on_main(lambda r=dict(rep): self._post(name, r))
        else:
            # JSON is untouched; it stays the source of truth and the next
            # request() retries.
            with self._cond:
                self._failed.add(name)
            self._run_on_main(lambda: self._emit("failed", name))

    def _post(self, name: str, rep: dict) -> None:
        """Main thread, per successful bake: pin the fingerprint of the file
        WE wrote (so the watcher never reads it as external), record it,
        drop records for marks the bake omitted as externally deleted (K-085
        resurrection race), then the native-baked ledger."""
        from . import pdf_handler as ph

        stat = rep.get("stat")
        try:
            self._pin(name, stat)
        except Exception as exc:
            print(f"[klausmate] pin failed for {name}: {exc}")
        omitted = rep.get("omitted_native") or []
        removed = 0
        try:
            ph.record_stat(self._ufd, name, stat)
            if omitted:
                removed = ph.remove_records(self._ufd, name, omitted)
            ph.mark_native_baked(self._ufd, name, rep.get("native_ids") or [])
        except Exception as exc:
            print(f"[klausmate] post-bake sync failed for {name}: {exc}")
        if removed:
            self._emit("records", name)
        self._emit("saved", name)

    def _emit(self, event: str, name: str) -> None:
        for cb in list(self._subs):
            try:
                cb(event, name)
            except Exception as exc:
                print(f"[klausmate] save subscriber failed on {event}: {exc}")


# ---- Qt glue ---------------------------------------------------------------

_PIPELINE: Optional[SavePipeline] = None


def _run_on_main(cb: Callable[[], None]) -> None:
    try:
        from aqt import mw

        if mw is not None:
            mw.taskman.run_on_main(cb)
            return
    except Exception:
        pass
    try:
        cb()  # headless: no other thread to conflict with
    except Exception as exc:
        print(f"[klausmate] main-thread callback failed: {exc}")


def _start_timer(_name: str, ms: int, cb: Callable[[], None]) -> None:
    # Restarts are handled by SavePipeline's generation check, so a plain
    # singleShot per request is enough (stale ones return at once).
    from aqt.qt import QTimer

    QTimer.singleShot(ms, cb)


def _pin(name: str, stat: Optional[tuple]) -> None:
    try:
        from . import doc_sync
    except ImportError:  # Task 4 wires this for real
        return
    doc_sync.pin_own_write(name, stat)


def pipeline() -> SavePipeline:
    global _PIPELINE
    if _PIPELINE is None:
        from . import USER_FILES

        _PIPELINE = SavePipeline(USER_FILES, _run_on_main, _start_timer, _pin)
    return _PIPELINE


def flush_all() -> None:
    """profile_will_close: bake whatever is still debouncing."""
    if _PIPELINE is not None:
        _PIPELINE.flush()
