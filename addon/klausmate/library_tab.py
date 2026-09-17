"""The Library as a screen inside Anki's main window, not its own window.

Pouya's ask: "just make it a tab". Anki has no tab API — its main window
shows one state at a time (deck browser, overview, reviewer) rendered into
webviews held in ``mw.mainLayout``. So a screen is made by adding a widget
to that layout and hiding the webviews while it is up.

**Library-only, deliberately.** The tree and the assistant mount here; the
PDF viewer does not. Under the pdf.js renderer ``PdfSidebar`` is a webview,
and a webview pane inside the main window is precisely what defeated
``single_window.py`` across five rework rounds before it was deleted
(2026-08-25, "Embedding Anki's windows stays deleted"). ``DriveWindow`` is
constructed with ``embedded=True``, which does not build the viewer at all
rather than building and hiding one — the difference between reusing that
machinery and re-fighting that bug.

**That left the tab with no way to open a PDF at all, which was a
regression** (K-173). The original note here claimed activation "routes to
the docked PDF panel" — it does not and cannot: that panel hangs off an
EDITOR (``editor._klausmate_pdf_tabs``, a ``PdfDock`` on Add and Browse
windows), and
the main window has no editor. There was no destination. The claim was
written before it was checked.

**If the viewer has to come back, prefer the DOCK shape over this one.**
``lecture_view.py`` already hosts a standalone ``PdfSidebar`` inside Anki's
main window under either renderer — but as a ``QDockWidget`` added with
``mw.addDockWidget(RightDockWidgetArea, ...)`` (lecture_view.py:591), NOT as
a widget in ``mw.mainLayout``. That distinction is the whole precedent:
single_window.py's failure was webview PANES in one window, so the working
example licenses the dock and says nothing in favour of the splitter. If a
viewer added to this splitter comes up black under pdf.js, that is the
2026-08-25 bug rather than a new one, and the dock is the other door rather
than something to fight toward. (Verified 2026-09-01; the distinction is
worker-AC's, via the other session.)

Everything here is guarded and reversible: if the mount fails, the webviews
come back and the standalone window still works.
"""

from __future__ import annotations

_state = {"tab": None, "mounted": False, "hidden": []}


def _mw():
    from aqt import mw

    return mw


def is_mounted() -> bool:
    return bool(_state["mounted"])


def _webviews(mw) -> list:
    """The main window's own panes, in the order Anki laid them out.

    toolbarWeb is deliberately NOT hidden: the top bar is how the user
    leaves this screen, and hiding it would strand them here.
    """
    out = []
    for name in ("web", "bottomWeb"):
        widget = getattr(mw, name, None)
        if widget is not None:
            out.append(widget)
    return out


def mount() -> bool:
    """Show the Library as the main window's current screen."""
    mw = _mw()
    if mw is None or getattr(mw, "mainLayout", None) is None:
        print("[klausmate] library tab: no main layout to mount into")
        return False
    if _state["mounted"]:
        return True
    try:
        tab = _state["tab"]
        if tab is None:
            from .pdf_drive import DriveWindow

            tab = DriveWindow(embedded=True)
            _state["tab"] = tab
            mw.mainLayout.addWidget(tab)
        hidden = []
        for widget in _webviews(mw):
            if widget.isVisible():
                widget.hide()
                hidden.append(widget)
        _state["hidden"] = hidden
        tab.show()
        _state["mounted"] = True
        return True
    except Exception as exc:
        print(f"[klausmate] library tab mount failed: {exc}")
        unmount()
        return False


def unmount() -> None:
    """Put the main window back the way Anki had it.

    Restores only what THIS module hid: a pane Anki had already hidden for
    its own reasons must stay hidden, or leaving the Library would resurrect
    the reviewer's bottom bar onto the deck screen.
    """
    try:
        tab = _state["tab"]
        if tab is not None:
            tab.hide()
        for widget in _state["hidden"]:
            try:
                widget.show()
            except Exception:
                pass
        _state["hidden"] = []
        _state["mounted"] = False
    except Exception as exc:
        print(f"[klausmate] library tab unmount failed: {exc}")


def toggle() -> None:
    """What the toolbar's Library link does."""
    if _state["mounted"]:
        unmount()
        try:
            _mw().moveToState("deckBrowser")
        except Exception as exc:
            print(f"[klausmate] library tab: state restore failed: {exc}")
        return
    mount()


def on_state_will_change(new_state: str, old_state: str) -> None:
    """Step aside whenever Anki moves to one of its own screens.

    Without this the Library would sit on top of the deck list forever: Anki
    changes state without knowing another widget is covering its webviews.
    """
    if _state["mounted"]:
        unmount()


def install_hooks() -> None:
    from aqt import gui_hooks

    try:
        gui_hooks.state_will_change.append(on_state_will_change)
    except Exception as exc:
        print(f"[klausmate] library tab hooks failed: {exc}")
