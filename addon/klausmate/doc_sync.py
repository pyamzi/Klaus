"""Open-file watching for the PDF reader panels (PDF reader 1/5).

A registry of PDFs open in reader panels (``open_doc``/``close_doc``, one
entry per safe name, a set of hosts each). Every open path is watched; when
it changes outside Klaus, subscribers get ``("changed", safe, None)`` once
the file has settled (size and mtime equal across two checks ``STABLE_MS``
apart). Klaus's own saves are pinned (``pin_own_write``) and ignored. The
folder rescan reports moves and disappearances through ``repoint``,
``mark_missing`` and ``mark_back``; the watcher itself only emits "changed".

Events: ``("changed", safe, None)``, ``("moved", safe, new_path)``,
``("missing", safe, None)``, ``("back", safe, path)``. Everything runs on
the main thread. Everything above the "Qt glue" divider is aqt-free.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import pdf_handler

STABLE_MS = 150  # stable-file rule: two equal checks this far apart
MAX_MISSING_TICKS = 10  # a save-over's path is back within this many ticks

_hosts: dict = {}  # safe -> set of host keys that have it open
_paths: dict = {}  # safe -> path
_pins: dict = {}  # safe -> stat of Klaus's own last write
_last: dict = {}  # safe -> last stat classified (dedupes repeated fileChanged)
_subs: list = []


def open_doc(host: str, safe: str, path: str) -> None:
    _hosts.setdefault(safe, set()).add(host)
    if _paths.get(safe) != path:
        _paths[safe] = path
        _last[safe] = pdf_handler.file_stat(path)
        _sync()


def close_doc(host: str, safe: str) -> None:
    hosts = _hosts.get(safe)
    if hosts is None:
        return
    hosts.discard(host)
    if hosts:
        return  # another host still has it open
    for d in (_hosts, _paths, _pins, _last):
        d.pop(safe, None)
    _sync()


def open_paths() -> dict:
    return dict(_paths)


def pin_own_write(safe: str, stat: Optional[tuple]) -> None:
    """Klaus wrote ``safe``; a file with exactly this stat is ours. The pin
    lasts until a different stat is seen (a save-over fires more than once)."""
    if stat is None:
        _pins.pop(safe, None)
    else:
        _pins[safe] = tuple(stat)


def classify(safe: str, stat: Optional[tuple]) -> str:
    if stat is None:
        return "missing"
    if _pins.get(safe) == tuple(stat):
        return "own"
    _pins.pop(safe, None)
    return "changed"


def stable(prev: Optional[tuple], cur: Optional[tuple]) -> bool:
    """Size and mtime equal. A missing file is never stable."""
    return prev is not None and cur is not None and prev[1:] == cur[1:]


def subscribe(cb: Callable[[str, str, Optional[str]], None]) -> Callable[[], None]:
    _subs.append(cb)

    def _unsubscribe() -> None:
        try:
            _subs.remove(cb)
        except ValueError:
            pass

    return _unsubscribe


def repoint(safe: str, new_path: str) -> None:
    """The rescan found ``safe`` at ``new_path``: follow it, emit "moved"."""
    if safe in _hosts:
        _paths[safe] = new_path
        _last[safe] = pdf_handler.file_stat(new_path)  # a late fileChanged is not "changed"
        _sync()
    _emit("moved", safe, new_path)


def mark_missing(safe: str) -> None:
    _emit("missing", safe, None)


def mark_back(safe: str, path: str) -> None:
    if safe in _hosts:
        _paths[safe] = path
        _last[safe] = pdf_handler.file_stat(path)
        _sync()
    _emit("back", safe, path)


def resync() -> None:
    """Re-watch every open path that exists now (the rescan calls this
    each pass; idempotent)."""
    _sync()


def _settled(safe: str, stat: Optional[tuple]) -> None:
    """A settled stat for an open ``safe``: emit "changed" if it is new and
    not Klaus's own write. Missing is left to the rescan."""
    if stat is None or stat == _last.get(safe):
        return
    _last[safe] = stat
    if classify(safe, stat) == "changed":
        _emit("changed", safe, None)


def _emit(event: str, safe: str, path: Optional[str]) -> None:
    for cb in list(_subs):
        try:
            cb(event, safe, path)
        except Exception as exc:
            print(f"[klausmate] doc_sync subscriber failed on {event}: {exc}")


# ---- Qt glue ---------------------------------------------------------------

_WATCHER = None
_settling: dict = {}  # safe -> (previous sample, ticks while missing)


def watcher():
    """The one QFileSystemWatcher (created on first use, main thread)."""
    global _WATCHER
    if _WATCHER is None:
        from aqt.qt import QFileSystemWatcher

        _WATCHER = QFileSystemWatcher()
        _WATCHER.fileChanged.connect(_on_file_changed)
    return _WATCHER


def _sync() -> None:
    """Make the watched set match the open paths that exist right now
    (a save-over drops the path from the watcher; this re-adds it)."""
    if _WATCHER is None and not _paths:
        return
    try:
        w = watcher()
        want = {p for p in _paths.values() if pdf_handler.file_stat(p) is not None}
        have = set(w.files())
        if have - want:
            w.removePaths(sorted(have - want))
        if want - have:
            w.addPaths(sorted(want - have))
    except Exception as exc:
        print(f"[klausmate] doc_sync could not update the watcher: {exc}")


def _on_file_changed(path: str) -> None:
    for safe, p in list(_paths.items()):
        if p != path or safe in _settling:
            continue  # not ours, or its settle chain is already running
        _settling[safe] = (pdf_handler.file_stat(path), 0)
        _arm(safe)


def _arm(safe: str) -> None:
    from aqt.qt import QTimer

    QTimer.singleShot(STABLE_MS, lambda: _tick(safe))


def _tick(safe: str) -> None:
    prev, missing = _settling.get(safe, (None, 0))
    path = _paths.get(safe)
    if path is None:  # closed while settling
        _settling.pop(safe, None)
        return
    cur = pdf_handler.file_stat(path)
    if stable(prev, cur):
        _settling.pop(safe, None)
        _sync()
        _settled(safe, cur)
        return
    missing = missing + 1 if cur is None else 0
    if missing > MAX_MISSING_TICKS:  # gone for good: the rescan reports it
        _settling.pop(safe, None)  # no _sync(): FSEvents still watches it
        return
    _settling[safe] = (cur, missing)
    _arm(safe)
