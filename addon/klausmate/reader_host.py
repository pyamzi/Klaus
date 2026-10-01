"""The ONE PDF reader and its two homes (spec
docs/superpowers/specs/2026-10-01-add-tab-design.md, "The reader").

The reader (``reader_panel.PdfSidebar``, ``host_key="editor"``) has a
permanent parent — the Add tab's reader slot, ``set_home`` — and one
borrower: Browse's viewer mode, which ``lend``s it into Browse's central
area and ``give_back``s it on leave. It is one instance for its whole
life: re-parenting never rebuilds it, so doc_sync and the tab set never
split. Only a dead C++ object is rebuilt, and the fallback transition —
a lend into ANOTHER top-level window — releases and builds afresh there,
because a webview is never re-parented across top-level windows
(K-090..K-094).

Fallback mode (no home: the single window is off or disabled): the reader
is built under Browse on the first viewer-mode entry, stays there, and is
``release``d when that Browse closes.

Every entry point is guarded: a failure prints ``[klausmate] reader
host: …`` and leaves the reader where it is.
"""
from __future__ import annotations

from typing import Callable

# Test seam: build the reader under ``parent``. None → the real class.
make_reader: Callable | None = None

_state: dict = {"home": None, "reader": None, "note": None, "home_editor": None}
BORROWED = "Open in Browse"


def _alive(widget) -> bool:
    if widget is None:
        return False
    try:
        from aqt.qt import sip

        return not sip.isdeleted(widget)
    except Exception:  # noqa: BLE001
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False


def _build(parent):
    if make_reader is not None:
        return make_reader(parent)
    from .reader_panel import PdfSidebar

    return PdfSidebar(None, parent=parent, host_key="editor")


def _place(widget, container) -> None:
    """Move ``widget`` into ``container``'s layout and show it."""
    old = widget.parentWidget()
    if old is not None and old.layout() is not None:
        old.layout().removeWidget(widget)
    widget.setParent(container)
    lay = container.layout()
    if lay is not None:
        lay.addWidget(widget)
    widget.show()


def set_home(slot) -> None:
    _state["home"] = slot
    old = borrowed_note()
    _state["note"] = None
    if old is not None:
        try:
            old.hide()
            old.setParent(None)
            old.deleteLater()
        except RuntimeError:
            pass
    if slot is not None:
        try:
            from aqt.qt import QLabel, Qt

            note = QLabel(BORROWED, slot)
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            note.setObjectName("klausmate_reader_borrowed")
            if slot.layout() is not None:
                slot.layout().addWidget(note)
            note.hide()
            _state["note"] = note
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] reader host: note failed: {exc}")


def set_home_editor(editor) -> None:
    """The editor the reader belongs to while at home (the live Add
    editor, or None): ``PdfSidebar._editor`` for the reader's own insert
    flows and add-ons built on it (Image Occlusion). Lending sets it to
    the borrower's editor; giving back restores this one."""
    _state["home_editor"] = editor
    r = current()
    if r is not None and not borrowed():
        r._editor = editor


def current():
    """The live instance or None; never builds."""
    return _current()


def borrowed_note():
    """The label the home slot shows while Browse holds the reader."""
    return _state["note"] if _alive(_state["note"]) else None


def _show_note(show: bool) -> None:
    note = borrowed_note()
    if note is None:
        return
    if show:
        name = getattr(_current(), "_name", None)
        note.setText(f"{BORROWED}: {name}" if name else BORROWED)
    note.setVisible(show)


def has_home() -> bool:
    return _alive(_state["home"])


def _current():
    r = _state["reader"]
    if r is not None and not _alive(r):
        _state["reader"] = None
        return None
    return r


def reader(parent=None):
    """The one instance; built on first call under ``parent`` or the
    home; ``None`` when there is nowhere to put it."""
    try:
        r = _current()
        if r is not None:
            return r
        target = parent if parent is not None else (_state["home"] if has_home() else None)
        if target is None:
            return None
        r = _build(target)
        if target.layout() is not None:
            target.layout().addWidget(r)
        if target is _state["home"]:
            r._editor = _state["home_editor"]
        _state["reader"] = r
        return r
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] reader host: building the reader failed: {exc}")
        return None


def borrowed() -> bool:
    r = _current()
    return r is not None and (not has_home() or r.parentWidget() is not _state["home"])


def lend(container, editor=None) -> None:
    """Re-parent the reader into ``container`` (whose ``editor`` it then
    belongs to); build it there when none exists; never across top-level
    windows (release and rebuild instead)."""
    try:
        if container is None:
            return
        r = _current()
        if r is not None and r.window() is not container.window():
            release()
            r = None
        if r is None:
            r = reader(container)
            if r is not None:
                r._editor = editor
            return
        r._editor = editor
        if r.parentWidget() is container:
            r.show()
            return
        _place(r, container)
        _show_note(True)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] reader host: lend failed: {exc}")


def give_back() -> None:
    """Back into the home slot; with no live home it stays where it is."""
    try:
        r = _current()
        home = _state["home"]
        if r is None or not has_home() or r.parentWidget() is home:
            return
        if r.window() is not home.window():
            return  # never across top-level windows
        _place(r, home)
        r._editor = _state["home_editor"]
        _show_note(False)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] reader host: give_back failed: {exc}")


def release() -> None:
    """cleanup() the reader if alive, and forget it."""
    r = _current()
    _state["reader"] = None
    _show_note(False)
    if r is None:
        return
    try:
        r.cleanup()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] reader host: cleanup failed: {exc}")
    try:
        old = r.parentWidget()
        if old is not None and old.layout() is not None:
            old.layout().removeWidget(r)
        r.setParent(None)
        r.deleteLater()
    except RuntimeError:
        pass
