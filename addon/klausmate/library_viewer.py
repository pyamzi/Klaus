"""Viewer mode in Browse (K-313): double-click a PDF in the Library.

The card table and the note editor (Browse's central widget) step aside
and the PDF panel fills that space with the PDF loaded; the Library
sidebar stays on the left. A single click on any sidebar row, or Esc,
brings the cards back. Closing the panel or the Browse window restores
the normal layout too — Browse is reused all session, so leaving the
table hidden would outlive the window.

The panel is Klaus's own PdfDock (``editor._klausmate_pdf_tabs``).
Viewer mode never changes its remembered placement: a floating panel is
docked for the duration with its signals blocked, so its
placement-memory handlers never see it, and is floated back after.
"""
from __future__ import annotations

import time

from aqt.qt import QApplication, QEvent, QObject, Qt

ATTR = "_klausmate_viewer"


def _dock(browser):
    return getattr(getattr(browser, "editor", None), "_klausmate_pdf_tabs", None)


def active(browser) -> bool:
    return getattr(browser, ATTR, None) is not None


def _fill(browser, dock) -> None:
    try:
        vertical = browser.dockWidgetArea(dock) == Qt.DockWidgetArea.BottomDockWidgetArea
        total = browser.height() if vertical else browser.width()
        browser.resizeDocks(
            [dock], [max(400, total)],
            Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] viewer mode resize failed: {exc}")


def enter(browser, safe: str) -> bool:
    """Show ``safe`` in the PDF panel in place of the cards."""
    dock = _dock(browser)
    central = browser.centralWidget() if browser is not None else None
    if dock is None or central is None:
        return False  # the panel is installed one tick after Browse opens
    if not active(browser):
        state = {
            "visible": dock.isVisible(),
            "floating": dock.isFloating(),
            "geometry": dock.geometry(),
            "width": dock.width(),
            "height": dock.height(),
            "entered": 0.0,
        }
        if state["floating"]:
            dock.blockSignals(True)
            try:
                dock.setFloating(False)
            finally:
                dock.blockSignals(False)
        setattr(browser, ATTR, state)
        _install_filter(browser, dock)
        dock.panel_show()
        central.hide()
        _fill(browser, dock)
    getattr(browser, ATTR)["entered"] = time.monotonic()
    try:
        sidebar = dock._sidebar
        if not sidebar.is_loaded(safe):
            sidebar.load_pdf(safe)
        from . import library_actions, pdf_handler

        pdf_handler.touch_last_used(library_actions._uf(), safe)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] viewer mode could not load {safe!r}: {exc}")
    return True


def leave(browser) -> None:
    """The cards come back; the panel returns to how it was."""
    state = getattr(browser, ATTR, None)
    if state is None:
        return
    setattr(browser, ATTR, None)  # first: hiding the panel below re-enters via its signal
    central = browser.centralWidget()
    if central is not None:
        central.show()
    dock = _dock(browser)
    if dock is None:
        return
    try:
        if state["floating"]:
            dock.blockSignals(True)
            try:
                dock.setFloating(True)
                dock.setGeometry(state["geometry"])
            finally:
                dock.blockSignals(False)
        elif not state["visible"]:
            dock.hide()
        else:
            vertical = browser.dockWidgetArea(dock) == Qt.DockWidgetArea.BottomDockWidgetArea
            browser.resizeDocks(
                [dock], [state["height"] if vertical else state["width"]],
                Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] leaving viewer mode: panel restore failed: {exc}")


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
    took), and closing Browse restores the layout it will reopen with."""

    def __init__(self, browser) -> None:
        super().__init__(browser)
        self.browser = browser

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if not active(self.browser):
            return False
        kind = event.type()
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            leave(self.browser)
            return True
        if kind == QEvent.Type.Close:
            leave(self.browser)
        return False


def _install_filter(browser, dock) -> None:
    if getattr(browser, "_klausmate_viewer_filter", None) is not None:
        return
    viewer_filter = _ViewerFilter(browser)
    browser.installEventFilter(viewer_filter)
    browser._klausmate_viewer_filter = viewer_filter
    # The panel's own ✕ while the cards are hidden would leave an empty
    # window: closing the panel leaves viewer mode.
    dock.visibilityChanged.connect(lambda visible: None if visible else leave(browser))
