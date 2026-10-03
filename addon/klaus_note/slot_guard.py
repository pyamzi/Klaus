"""Keep an exception in a Qt slot to one log line — not a dialog, not an abort.

What an unhandled slot exception costs depends on the PROCESS. A bare
interpreter — a test, a probe, a script — has no ``sys.excepthook`` of its
own, and PyQt6 answers by printing the traceback and calling ``qFatal``:
SIGABRT, exit 134 (measured 2026-09-01). ``SystemExit`` and ``sys.exit`` are
clean; a plain exception or ``MemoryError`` is not.

Anki is NOT that process. ``aqt.errors.ErrorHandler`` installs a non-default
``sys.excepthook``, and PyQt6 honours a non-default hook INSTEAD of qFatal
(verified 2026-09-01: hook called, exit 0). So in Anki an unguarded slot
exception reaches Anki's error dialog — modal, mid-review, with the slot's
work half-applied — rather than aborting. This guard turns that into one
``[klaus_note]`` line and a slot that returns None, and it is also what keeps
the offscreen test processes alive. CLAUDE.md's "defensive try/except around
every Qt call" is this convention, as a decorator.

This module is the uniform way to satisfy it. A decorator rather than a
hand-written try/except in each body, for two reasons:

* It is *detectable*. A source pin looking for ``try:`` in a handler body
  gets both answers wrong — it misses a handler that delegates its work to
  a helper, and it passes a handler whose ``try`` covers only one harmless
  line. A decorator is unambiguous.
* It cannot be half-applied. A ``try`` that someone later adds a statement
  after is silently no longer covering the slot.

Deliberately aqt-free and dependency-free, because it is imported at module
load by files that must not reach back into the package (``browse_toggles``
is imported by ``__init__`` during package load and would deadlock on a
circular import).

``except Exception`` on purpose: ``SystemExit`` and ``KeyboardInterrupt``
are ``BaseException`` and must keep propagating — swallowing them would
stop Anki quitting.
"""

from __future__ import annotations

import functools


def guarded(fn):
    """Wrap a Qt slot so an exception is logged instead of fatal.

    Returns None on failure, which every Qt signal accepts — a slot's
    return value is discarded.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            name = getattr(fn, "__qualname__", getattr(fn, "__name__", "?"))
            print(f"[klaus_note] slot {name} failed: {exc}")
            return None

    wrapper.__klaus_guarded__ = True
    return wrapper


def is_guarded(fn) -> bool:
    """Whether *fn* has been through :func:`guarded`."""
    return bool(getattr(fn, "__klaus_guarded__", False))
