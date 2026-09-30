"""The one list of running processes the status bar draws.

Anything that does work reports three things: it started (``begin``,
with a cancel callable when it can be stopped), how far along it is
(``update``; ``total`` 0 means unknown) and that it finished (``end``,
optionally with a message that lingers ``LINGER_S`` seconds — or, with
``error=True``, stays until the next ``begin`` of any task).

Thread rule: ``begin``/``update``/``end`` may be called from any
thread. They only record the change under a lock and hand the listener
notification to ``run_on_main`` — the status bar glue sets it to
``mw.taskman.run_on_main`` — so a widget is never touched off the main
thread. A raising listener is logged and skipped; a report can never
break the work it describes. aqt-free.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, NamedTuple

LINGER_S = 4.0


class Task(NamedTuple):
    key: str
    label: str
    done: int
    total: int
    cancellable: bool
    message: str  # "" while running; the end message once finished
    started: float
    error: bool = False  # a failure: kept until the next task begins


clock: Callable[[], float] = time.monotonic
run_on_main: Callable[[Callable[[], None]], None] = lambda fn: fn()

_lock = threading.Lock()
_tasks: dict[str, Task] = {}
_ended: dict[str, float | None] = {}  # None: a failure, no expiry
_cancels: dict[str, Callable[[], None]] = {}
_order: dict[str, int] = {}  # begin order: breaks ties between equal clock readings
_seq = [0]
_listeners: list[Callable[[list[Task]], None]] = []


def _changed() -> None:
    # Snapshot at delivery, on the main thread: two threads can enqueue
    # in either order, and a snapshot taken here could land stale.
    run_on_main(lambda: _notify(snapshot()))


def _notify(snap: list[Task]) -> None:
    for fn in list(_listeners):
        try:
            fn(snap)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] task listener failed: {exc}")


def begin(key: str, label: str, cancel: Callable[[], None] | None = None) -> None:
    with _lock:
        for k, at in list(_ended.items()):
            if at is None:  # a new task clears the failures
                _ended.pop(k, None)
                _tasks.pop(k, None)
        _tasks[key] = Task(key, label, 0, 0, cancel is not None, "", clock())
        _seq[0] += 1
        _order[key] = _seq[0]
        _ended.pop(key, None)
        if cancel is None:
            _cancels.pop(key, None)
        else:
            _cancels[key] = cancel
    _changed()


def update(key: str, done: int | None = None, total: int | None = None, label: str | None = None) -> None:
    with _lock:
        task = _tasks.get(key)
        if task is None or key in _ended:
            return
        _tasks[key] = task._replace(
            done=task.done if done is None else int(done),
            total=task.total if total is None else int(total or 0),
            label=task.label if label is None else label,
        )
    _changed()


def end(key: str, message: str = "", error: bool = False) -> None:
    with _lock:
        task = _tasks.get(key)
        _cancels.pop(key, None)
        if task is None:
            return
        if message:
            _tasks[key] = task._replace(message=message, cancellable=False, error=error)
            _ended[key] = None if error else clock()
        else:
            _tasks.pop(key, None)
            _ended.pop(key, None)
    _changed()


def snapshot() -> list[Task]:
    with _lock:
        now = clock()
        for key, at in list(_ended.items()):
            if at is not None and now - at > LINGER_S:
                _ended.pop(key, None)
                _tasks.pop(key, None)
        return sorted(_tasks.values(), key=lambda t: (t.started, _order.get(t.key, 0)), reverse=True)


def cancel(key: str) -> None:
    fn = _cancels.get(key)
    if fn is None:
        return
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] cancelling {key!r} failed: {exc}")


def add_listener(fn: Callable[[list[Task]], None]) -> None:
    if fn not in _listeners:
        _listeners.append(fn)


def remove_listener(fn: Callable[[list[Task]], None]) -> None:
    try:
        _listeners.remove(fn)
    except ValueError:
        pass


def clear() -> None:
    with _lock:
        _tasks.clear()
        _ended.clear()
        _cancels.clear()
    _changed()
