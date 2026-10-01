"""Toggling one side pane leaves the opposite one alone.

A pane hidden or shown in a QSplitter (the Add tab's tree | reader |
editor), or a dock beside one (Browse's sidebar beside its table |
editor splitter), makes Qt share the width change across every other
pane, so the opposite sidebar grew or shrank too (Pouya, 2026-10-01:
"can we not have the opposing sidebar resize itself?").
``set_visible_keeping`` flips one pane and then puts the opposite pane
back at its width, giving the difference to the widest other pane: the
middle content (the reader, the card table).
"""
from __future__ import annotations

from typing import Any, Optional


def splitter_slot(widget: Any) -> tuple:
    """``(splitter, index)`` of the splitter child holding ``widget``, else
    ``(None, -1)``. The climb stops at a window or main window, so a dock
    (whose width the main window keeps) never matches an unrelated outer
    splitter, AMBOSS's around mw.web for one."""
    from aqt.qt import QMainWindow, QSplitter

    w = widget
    while w is not None and not w.isWindow():
        parent = w.parentWidget()
        if isinstance(parent, QSplitter):
            return parent, parent.indexOf(w)
        if isinstance(parent, QMainWindow):
            break
        w = parent
    return None, -1


def keep_width(widget: Any, width: int) -> None:
    """Give ``widget``'s splitter slot ``width`` again, taking or giving
    the difference to the widest other visible pane."""
    splitter, i = splitter_slot(widget)
    if splitter is None or width <= 0 or widget.isHidden():
        return
    sizes = splitter.sizes()
    delta = sizes[i] - width
    if abs(delta) < 2:
        return
    others = [k for k, s in enumerate(sizes)
              if k != i and s > 0 and not splitter.widget(k).isHidden()]
    if not others:
        return
    j = max(others, key=lambda k: sizes[k])
    if sizes[j] + delta <= 0:  # no room: leave Qt's split
        return
    sizes[i] = width
    sizes[j] += delta
    splitter.setSizes(sizes)


def set_visible_keeping(widget: Any, on: bool, opposite: Optional[Any] = None) -> None:
    """``widget.setVisible(on)`` with ``opposite`` kept at its width. Its
    splitter re-splits now; a dock's main window only on its next layout
    pass, so the width is put back now and again one tick later."""
    width = opposite.width() if opposite is not None and not opposite.isHidden() else 0
    widget.setVisible(on)
    if not width:
        return
    keep_width(opposite, width)
    try:
        from aqt.qt import QTimer

        QTimer.singleShot(0, lambda: keep_width(opposite, width))
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] pane width keep failed: {exc}")
