"""Stop an exception in a Qt slot from killing Anki.

PyQt6 answers an unhandled exception in a slot by printing the traceback and
then calling ``qFatal``, which SIGABRTs the process. Measured with the real
toolkit on 2026-09-01: a plain ``RuntimeError`` raised in a ``clicked``
handler exits **134**. ``SystemExit`` and ``sys.exit`` are clean; a plain
exception or ``MemoryError`` is not.

In a script that costs a test run. In Anki it costs **Anki** — mid-review,
with unsaved state — and the user sees a crash reporter, not a broken
button. That is why CLAUDE.md asks for defensive try/except around every Qt
call: the convention is load-bearing, not tidiness.

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
            print(f"[klausmate] slot {name} failed: {exc}")
            return None

    wrapper.__klaus_guarded__ = True
    return wrapper


def is_guarded(fn) -> bool:
    """Whether *fn* has been through :func:`guarded`."""
    return bool(getattr(fn, "__klaus_guarded__", False))
