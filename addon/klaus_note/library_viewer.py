"""Viewer mode in Browse (K-313): double-click a PDF in the Library.

The card table and the note editor (Browse's splitter) step aside and the
ONE PDF reader (``reader_host``) is lent into Browse's central area with
the PDF loaded; the Library sidebar stays on the left. A single click on
any sidebar row, or Esc, brings the cards back and gives the reader back
to its home, the Add tab's reader slot. Closing Browse gives it back too
(before Anki deletes the window) — and in fallback mode, where the reader
has no home and was built under Browse, closing Browse releases it.

Spec: docs/superpowers/specs/2026-10-01-add-tab-design.md, "The reader".

Nothing of Browse's is re-parented: its central widget's direct children
are hidden and Klaus's own box (``browser._klaus_note_viewer_box``) joins
the central layout once. Anki's sidebar keeps its width both ways: hiding
or showing the splitter makes Qt re-split the dock area, so the width is
pinned back after each switch.
"""
from __future__ import annotations

import time

from aqt.qt import QApplication, QEvent, QObject, Qt, QVBoxLayout, QWidget

from . import reader_host, settings

ATTR = "_klaus_note_viewer"
BOX_ATTR = "_klaus_note_viewer_box"


def active(browser) -> bool:
    return getattr(browser, ATTR, None) is not None


def cards_showing(browser) -> bool:
    """Browse's own splitter (table + editor) is not hidden by viewer mode
    (``isHidden``: explicitly hidden, whatever the window's own state)."""
    splitter = getattr(getattr(browser, "form", None), "splitter", None)
    try:
        return splitter is not None and not splitter.isHidden()
    except RuntimeError:
        return False


def _sidebar(browser):
    side = getattr(browser, "sidebarDockWidget", None)
    return side if side is not None and side.isVisible() and not side.isFloating() else None


def _pin_sidebar(browser, width) -> None:
    side = _sidebar(browser)
    if side is not None and width:
        browser.resizeDocks([side], [width], Qt.Orientation.Horizontal)


def _inside(widget, ancestor) -> bool:
    from aqt.qt import QObject

    try:
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = QObject.parent(w)
    except (RuntimeError, TypeError):
        pass
    return False


def _box(browser, central):
    """Klaus's own container in Browse's central layout, made once."""
    box = getattr(browser, BOX_ATTR, None)
    if box is not None:
        try:
            box.objectName()
            return box
        except RuntimeError:
            pass
    box = QWidget(central)
    box.setObjectName("klaus_note_viewer_box")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    central_lay = central.layout()
    if central_lay is not None:
        central_lay.addWidget(box)
    box.hide()
    setattr(browser, BOX_ATTR, box)
    return box


def enter(browser, safe: str) -> bool:
    """Show ``safe`` in the reader in place of the cards."""
    central = browser.centralWidget() if browser is not None else None
    if central is None:
        return False
    box = _box(browser, central)
    if not active(browser):
        side = _sidebar(browser)
        hidden = [w for w in central.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
                  if w is not box and w.isVisible()]
        state = {"side": side.width() if side is not None else 0, "hidden": hidden, "entered": 0.0}
        setattr(browser, ATTR, state)
        _install_filter(browser)
        for w in hidden:
            w.hide()
        box.show()
        reader_host.lend(box, getattr(browser, "editor", None))
        _pin_sidebar(browser, state["side"])
    else:
        reader_host.lend(box, getattr(browser, "editor", None))
    rd = reader_host.reader()
    try:
        if rd is not None and not rd.is_loaded(safe):
            rd.load_pdf(safe)
        from . import pdf_handler

        pdf_handler.touch_last_used(settings.user_files(), safe)
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] viewer mode could not load {safe!r}: {exc}")
    getattr(browser, ATTR)["entered"] = time.monotonic()
    return True


def leave(browser) -> None:
    """The cards come back; the reader goes home (or stays, hidden, in
    fallback mode)."""
    state = getattr(browser, ATTR, None)
    if state is None:
        return
    setattr(browser, ATTR, None)
    try:
        reader_host.give_back()
        box = getattr(browser, BOX_ATTR, None)
        if box is not None:
            box.hide()
        for w in state.get("hidden", ()):
            try:
                w.show()
            except RuntimeError:
                pass
        _pin_sidebar(browser, state["side"])
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] leaving viewer mode failed: {exc}")


def on_sidebar_click(browser) -> None:
    """A single click in the sidebar leaves viewer mode — except the
    click Qt reports for the release that ends the very double-click
    that entered it."""
    state = getattr(browser, ATTR, None)
    if state is None:
        return
    if time.monotonic() - state["entered"] < QApplication.doubleClickInterval() / 1000.0:
        return
    leave(browser)


class _ViewerFilter(QObject):
    """On the Browse window: Esc leaves viewer mode instead of closing
    Browse (Browse's own keyPressEvent closes on an Esc nothing else
    took); closing Browse gives the reader back before Anki deletes the
    window, and releases it when it has no home (fallback mode)."""

    def __init__(self, browser) -> None:
        super().__init__(browser)
        self.browser = browser

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        kind = event.type()
        if kind == QEvent.Type.Close:
            if active(self.browser):
                leave(self.browser)
            # Still inside this Browse after give_back (no home, or a home in
            # another top-level window after disable): it would be deleted
            # with the window, uncleaned. Release it instead.
            rd = reader_host.current()
            if rd is not None and _inside(rd, self.browser):
                reader_host.release()
            return False
        if not active(self.browser):
            return False
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            leave(self.browser)
            return True
        return False


def _install_filter(browser) -> None:
    if getattr(browser, "_klaus_note_viewer_filter", None) is not None:
        return
    viewer_filter = _ViewerFilter(browser)
    browser.installEventFilter(viewer_filter)
    browser._klaus_note_viewer_filter = viewer_filter
