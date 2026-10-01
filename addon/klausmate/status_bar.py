"""Browse's bottom bar — and the Add tab's: a gear that opens Anki's
Preferences on the left, and the readout of every running process
(``tasks``: the newest task's name, then its progress bar) at the bottom
right. The pane toggles live in the top bar beside the Klaus logo
(``browse_toggles.setup_top_bar``); only a Browse window outside the
single window keeps them here, beside the gear. The main window has no Qt
bar: its row is Anki's own, extended by ``bottom_row``, which shares this
module's readout rules, gear shape and task list, and whose height every
bar here follows (``set_row_height``), so the bottom edge is one height on
every tab. Klaus's own settings are the top bar's logo.

Pure helpers above the divider; the widget and install glue below it.
"""
from __future__ import annotations

import math

from . import tasks


def readout_text(items: list) -> str:
    """The one line beside the progress bar: the newest running task,
    "+N more" when several run; with none running, the newest
    lingering end message; idle, nothing."""
    running = [t for t in items if not t.message]
    if running:
        head = running[0].label
        return f"{head}  +{len(running) - 1} more" if len(running) > 1 else head
    return items[0].message if items else ""


SHOW_DELAY_S = 0.5  # a task quicker than this never flashes the readout


def visible_tasks(items: list, now: float) -> tuple[list, float | None]:
    """The tasks the readout draws, and in how many seconds to look again:
    a running task younger than ``SHOW_DELAY_S`` is left out until then."""
    young = [t for t in items if not t.message and now - t.started < SHOW_DELAY_S]
    if not young:
        return list(items), None
    wait = min(SHOW_DELAY_S - (now - t.started) for t in young)
    return [t for t in items if t not in young], wait


def gear_points(size: float) -> list[tuple[float, float]]:
    """An 8-tooth gear outline centred in a ``size`` box — drawn, because
    the ⚙ glyph renders at whatever the fallback font picks. The hub is a
    circle of radius ``size * 0.14`` at the centre."""
    c, ro, ri = size / 2.0, size * 0.44, size * 0.32
    pts = []
    for k in range(8):
        for r, da in ((ri, -15.0), (ro, -9.0), (ro, 9.0), (ri, 15.0)):
            t = math.radians(k * 45.0 + da)
            pts.append((c + r * math.cos(t), c + r * math.sin(t)))
    return pts


# ── aqt glue ─────────────────────────────────────────────────────────────

from aqt.qt import (  # noqa: E402
    QColor,
    QEvent,
    QFontMetrics,
    QFrame,
    QHBoxLayout,
    QLabel,
    QObject,
    QPainter,
    QPainterPath,
    QPen,
    QPointF,
    QProgressBar,
    QRectF,
    Qt,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

LABEL_MAX_PX = 320
# The strip's floor is the macOS title bar (28pt since Big Sur); it grows
# to the Decks row's height when that is taller (set_row_height).
# QStatusBar hard-codes 3px above its items and ~2px below, so the bar
# inside gets what's left, which also centres it in the strip.
# These are the 100% sizes: the floor, the cap, the gear and the text all
# scale by bar_scale (85% by default, so the floor is 24), never under
# STRIP_MIN (70%'s floor, where a 15px gear still fits the bar).
STRIP_HEIGHT = 28
STRIP_MAX = 64  # a measurement past this is a transient layout, not a row
STRIP_MIN = 20
STRIP_INSET = 3 + 2
BAR_HEIGHT = STRIP_HEIGHT - STRIP_INSET
PROGRESS_PX = 120
_row_px = [0]  # the Decks row as last measured
_scale: list = [None]  # bar_scale, read from config on first use


def scale() -> int:
    """``bar_scale`` in percent: what ``set_scale`` last set, else config."""
    if _scale[0] is None:
        try:
            from . import dashboard, settings

            _scale[0] = dashboard.bar_scale_from_cfg(settings.read())
        except Exception:  # noqa: BLE001
            return 85
    return _scale[0]


def scaled(px: float) -> int:
    return round(px * scale() / 100)


def _open_anki_settings() -> None:
    try:
        from aqt import mw

        mw.onPrefs()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar: Anki settings failed: {exc}")


def _editor_column(browser):
    """The Browse splitter's direct child that holds the note editor."""
    try:
        splitter = browser.form.splitter
        w = browser.form.fieldsArea
        while w is not None:
            p = w.parentWidget()
            if p is splitter:
                return w
            w = p
    except Exception:  # noqa: BLE001
        pass
    return None


class _ClickFilter(QObject):
    def __init__(self, parent, on_click) -> None:
        super().__init__(parent)
        self._on_click = on_click

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 - Qt override
        if ev.type() == QEvent.Type.MouseButtonRelease:
            self._on_click()
            return True
        return False


def gear_path(size: float) -> "QPainterPath":
    """``gear_points`` as a QPainterPath, with its hub hole."""
    c, hub = size / 2.0, size * 0.14
    path = QPainterPath()
    pts = [QPointF(x, y) for x, y in gear_points(size)]
    path.moveTo(pts[0])
    for p in pts[1:]:
        path.lineTo(p)
    path.closeSubpath()
    path.addEllipse(QPointF(c, c), hub, hub)
    return path


class _GearButton(QToolButton):
    """The gear: opens Anki's Preferences in one click. Painted like the
    pane toggles (nothing at rest, a grey wash on hover) so the bar's
    three icons read as one set."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        from .browse_toggles import BUTTON_SIZE

        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)  # bar_scale: _size
        self.setAutoRaise(True)  # repaints on hover
        self._tab_focus = False
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Anki Settings")
        self.setAccessibleName("Anki Settings")

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt override
        from .browse_toggles import is_keyboard_focus

        self._tab_focus = is_keyboard_focus(event)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._tab_focus = False
        super().focusOutEvent(event)

    def show_focus(self) -> bool:
        return self.hasFocus() and self._tab_focus

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        if self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        try:
            from . import theme
            from .browse_toggles import CHIP_RADIUS, icon_size, stroke_width

            c = theme.palette(theme.night_mode())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w, h = float(self.width()), float(self.height())
            if self.isDown() or self.underMouse() or self.show_focus():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c["hover_subtle"]))
                painter.drawRoundedRect(QRectF(0.0, 0.0, w, h), CHIP_RADIUS, CHIP_RADIUS)
            size = icon_size(w, h)
            painter.translate(round((w - size) / 2.0), round((h - size) / 2.0))
            pen = QPen(QColor(c["text_muted"]))
            pen.setWidthF(stroke_width(size))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(gear_path(size))
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] status bar gear paint failed: {exc}")
        finally:
            painter.end()


class StatusBar(QWidget):
    def __init__(self, window, browser=None) -> None:
        super().__init__(window)
        self.setObjectName("KlausStatusBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(BAR_HEIGHT)
        self.popup = None
        self._wake = QTimer(self)  # re-check once young tasks come of age
        self._wake.setSingleShot(True)
        self._wake.timeout.connect(self._expire)
        self.sidebar_btn = None
        self.editor_btn = None
        self.dock_btn = None
        self.close_btn = None
        self._tasks: list = []
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(6)
        self.gear = _GearButton(self)
        self.gear.clicked.connect(lambda *_a: _open_anki_settings())
        row.addWidget(self.gear)
        if browser is not None:
            # Outside the single window Browse has no Klaus top bar, so
            # its toggles stay here, grouped with the gear.
            row.setSpacing(2)
            self._add_toggles(row, browser)
        row.addStretch(1)
        self.progress = QProgressBar(self)
        self.progress.setFixedWidth(PROGRESS_PX)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.label = QLabel("", self)
        self.label.setMaximumWidth(LABEL_MAX_PX)
        clicks = _ClickFilter(self, self.open_task_list)
        self.progress.installEventFilter(clicks)
        self.label.installEventFilter(clicks)
        # Bottom right: what is running, then how far along it is.
        row.addWidget(self.label)
        row.addSpacing(6)
        row.addWidget(self.progress)
        self.apply_theme()

        # The listener must not keep a deleted bar alive, nor touch one:
        # it holds a one-slot box that destroyed empties.
        box = [self]

        def listener(snap) -> None:
            if box[0] is not None:
                box[0].refresh(snap)

        def forget(*_a) -> None:
            box[0] = None
            tasks.remove_listener(listener)

        tasks.add_listener(listener)
        self.destroyed.connect(forget)
        self.refresh(tasks.snapshot())

    def _add_toggles(self, row, browser) -> None:
        from .browse_toggles import _PaneToggle, _VisibilityWatcher
        from . import pane_keep

        dock = getattr(browser, "sidebarDockWidget", None)
        if dock is not None:
            btn = _PaneToggle("left", "sidebar", dock.isVisible())
            btn.clicked.connect(lambda on, d=dock: pane_keep.set_visible_keeping(d, on, _editor_column(browser)))
            try:
                dock.visibilityChanged.connect(btn.setChecked)
            except Exception:  # noqa: BLE001
                pass
            row.addWidget(btn)
            self.sidebar_btn = btn
        col = _editor_column(browser)
        if col is not None:
            btn = _PaneToggle("right", "editor", col.isVisible())
            btn.clicked.connect(lambda on, c=col: pane_keep.set_visible_keeping(c, on, getattr(browser, "sidebarDockWidget", None)))
            _VisibilityWatcher(col, btn.setChecked)
            row.addWidget(btn)
            self.editor_btn = btn

    def apply_theme(self) -> None:
        try:
            from . import theme

            # On Qt's own status bar when inside one, so its QStatusBar
            # rules replace the macOS panel line and item frames.
            host = self.parentWidget()
            if host is None or not host.inherits("QStatusBar"):
                host = self
            host.setStyleSheet(theme.status_bar_qss(theme.night_mode(), scale()))
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] status bar theme failed: {exc}")

    def refresh(self, items: list) -> None:
        items, wait = visible_tasks(items, tasks.clock())
        if wait is not None:
            self._wake.start(int(wait * 1000) + 20)
        self._tasks = list(items)
        running = [t for t in items if not t.message]
        text = readout_text(items)
        self.label.setText(QFontMetrics(self.label.font()).elidedText(
            text, Qt.TextElideMode.ElideMiddle, LABEL_MAX_PX))
        self.label.setToolTip(text)
        failed = not running and bool(items) and items[0].error
        if self.label.property("error") is not failed:
            self.label.setProperty("error", failed)
            self.label.style().unpolish(self.label)
            self.label.style().polish(self.label)
        if running:
            head = running[0]
            if head.total > 0:
                self.progress.setRange(0, head.total)
                self.progress.setValue(min(head.done, head.total))
            else:
                self.progress.setRange(0, 0)
            self.progress.show()
        else:
            self.progress.hide()
            if items:  # a lingering end message: redraw once it expires
                QTimer.singleShot(int(tasks.LINGER_S * 1000) + 50, self._expire)

    def _expire(self) -> None:
        try:
            self.refresh(tasks.snapshot())
        except RuntimeError:
            pass  # the bar was deleted while the timer waited

    def open_task_list(self) -> None:
        if self._tasks:
            anchor = self.label.mapToGlobal(self.label.rect().topLeft())
            self.popup = show_task_list(self, self._tasks, anchor)


def show_task_list(parent, items: list, anchor) -> "QFrame":
    """Every task with its own bar and a ✕ where it can be stopped, in a
    ``Qt.Popup`` frame just above ``anchor`` (a global point), kept on
    that screen. Shared by Browse's bar and the main window's row."""
    from . import theme

    frame = QFrame(parent, Qt.WindowType.Popup)
    frame.setObjectName("KlausStatusBar")
    frame.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    frame.setStyleSheet(theme.status_bar_qss(theme.night_mode()))
    col = QVBoxLayout(frame)
    col.setContentsMargins(10, 8, 10, 8)
    for t in items:
        line = QHBoxLayout()
        text = t.message or t.label
        name = QLabel(QFontMetrics(frame.font()).elidedText(
            text, Qt.TextElideMode.ElideMiddle, LABEL_MAX_PX), frame)
        name.setToolTip(text)
        line.addWidget(name, 1)
        if not t.message:
            bar = QProgressBar(frame)
            bar.setFixedWidth(100)
            bar.setTextVisible(False)
            bar.setRange(0, t.total if t.total > 0 else 0)
            if t.total > 0:
                bar.setValue(min(t.done, t.total))
            line.addWidget(bar)
        if t.cancellable:
            x = QToolButton(frame)
            x.setText("✕")
            x.setToolTip("Stop")
            x.clicked.connect(lambda *_a, k=t.key: (tasks.cancel(k), frame.close()))
            line.addWidget(x)
        col.addLayout(line)
    frame.adjustSize()
    frame.show()
    # Clamped once shown: frameGeometry then includes the window frame,
    # and the readout sits at the bottom RIGHT, so the right edge matters.
    screen = parent.screen() if hasattr(parent, "screen") else None
    area = screen.availableGeometry() if screen is not None else None
    outer = frame.frameGeometry()
    x, y = anchor.x(), anchor.y() - outer.height() - 2
    if area is not None:
        x = max(area.left(), min(x, area.right() + 1 - outer.width()))
        y = max(area.top(), y)
    frame.move(x, y)
    return frame


# ── install ──────────────────────────────────────────────────────────────

_bars: list = []  # live bars, for theme_did_change


def _track(bar: StatusBar) -> StatusBar:
    _bars.append(bar)
    bar.destroyed.connect(lambda *_a, b=bar: _bars.remove(b) if b in _bars else None)
    return bar


def strip_height() -> int:
    """Every Klaus bar's strip height: the Decks row's, at least the
    scaled 28pt floor, at most the scaled cap."""
    floor = max(STRIP_MIN, scaled(STRIP_HEIGHT))
    return max(floor, min(_row_px[0], scaled(STRIP_MAX)))


def _size(bar: StatusBar) -> None:
    from .browse_toggles import BUTTON_SIZE

    native = bar.parentWidget()
    if native is not None and native.inherits("QStatusBar"):
        native.setFixedHeight(strip_height())
    bar.setFixedHeight(strip_height() - STRIP_INSET)
    n = scaled(BUTTON_SIZE)
    for btn in (bar.gear, bar.sidebar_btn, bar.editor_btn):
        if btn is not None:
            btn.setFixedSize(n, n)
    bar.progress.setFixedWidth(scaled(PROGRESS_PX))


def _resize_all(theme_too: bool = False) -> None:
    for bar in list(_bars):
        try:
            _size(bar)
            if theme_too:
                bar.apply_theme()
        except RuntimeError:
            pass


def set_row_height(px: int) -> None:
    """The Decks row measured ``px`` tall: size every bar to match."""
    before = strip_height()
    _row_px[0] = int(px)
    if strip_height() != before:
        _resize_all()


def set_scale(pct) -> None:
    """``bar_scale`` changed (a Preferences preview, its revert, a
    profile): re-size and re-style every bar. Invalid reads as 85."""
    from . import dashboard

    _scale[0] = dashboard.bar_scale_from_cfg({"bar_scale": pct})
    _resize_all(theme_too=True)


def _strip(parent):
    """Qt's own status bar, the frame both bars sit in (one hairline,
    the same insets, so the Add tab and Browse cannot differ)."""
    from aqt.qt import QStatusBar

    native = QStatusBar(parent)
    native.setSizeGripEnabled(False)
    return native


def install_add_tab(page, *_panes) -> StatusBar | None:
    """The Add tab's bar: appended under the page's content, no close
    control (Close and Escape switch tabs). Its panes' toggles are in the
    top bar (``browse_toggles``); ``_panes`` is the old call shape."""
    try:
        native = _strip(page)
        bar = StatusBar(native)
        native.addPermanentWidget(bar, 1)
        page.layout().addWidget(native)
        bar.apply_theme()
        _track(bar)
        _size(bar)
        return bar
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar (Add tab) failed: {exc}")
        return None


def install_browser(browser) -> StatusBar | None:
    """Browse has no status bar of its own: give it one (with the pane
    toggles only outside the single window)."""
    existing = getattr(browser, "_klausmate_status_bar", None)
    if existing is not None:
        return existing
    try:
        from . import single_window

        hosted = single_window.is_active()
        native = _strip(browser)
        browser.setStatusBar(native)
        # Hosted, the toggles are in the top bar beside the logo.
        bar = StatusBar(browser, browser=None if hosted else browser)
        native.addPermanentWidget(bar, 1)
        try:
            if hosted:
                # Browse is a tab: the one way to close it lives here.
                from aqt.qt import QToolButton

                close_btn = QToolButton(native)
                close_btn.setText("✕")
                close_btn.setAutoRaise(True)
                close_btn.setToolTip("Close Browse")
                close_btn.setAccessibleName("Close Browse")
                close_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                close_btn.clicked.connect(lambda *_a: browser.close())
                native.addPermanentWidget(close_btn)
                bar.close_btn = close_btn
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] status bar close control failed: {exc}")
        bar.apply_theme()
        browser._klausmate_status_bar = bar
        _track(bar)
        _size(bar)
        return bar
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar (Browse) failed: {exc}")
        return None


def _report(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar report failed: {exc}")


def on_sync_will_start() -> None:
    _report(lambda: tasks.begin("sync", "Syncing…"))


def on_sync_did_finish() -> None:
    _report(lambda: tasks.end("sync"))


def on_media_sync_did_start_or_stop(running: bool) -> None:
    _report(lambda: tasks.begin("media", "Syncing media…") if running else tasks.end("media"))


def on_media_sync_did_progress(entry: str) -> None:
    _report(lambda: tasks.update("media", label=f"Media: {entry}"))


def _on_profile_open() -> None:
    from aqt import mw

    try:
        tasks.run_on_main = mw.taskman.run_on_main
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar: no taskman: {exc}")
    _scale[0] = None  # this profile's bar_scale, read on next use


def _on_browser_will_show(browser) -> None:
    QTimer.singleShot(0, lambda: install_browser(browser))


def _on_theme_change() -> None:
    for bar in list(_bars):
        try:
            bar.apply_theme()
        except RuntimeError:
            pass


def setup() -> None:
    from aqt import gui_hooks

    gui_hooks.profile_did_open.append(_on_profile_open)
    gui_hooks.profile_will_close.append(tasks.clear)
    gui_hooks.browser_will_show.append(_on_browser_will_show)
    gui_hooks.theme_did_change.append(_on_theme_change)
    from . import browse_toggles

    browse_toggles.setup_top_bar()
    for name, fn in (
        ("sync_will_start", on_sync_will_start),
        ("sync_did_finish", on_sync_did_finish),
        ("media_sync_did_start_or_stop", on_media_sync_did_start_or_stop),
        ("media_sync_did_progress", on_media_sync_did_progress),
    ):
        if hasattr(gui_hooks, name):
            getattr(gui_hooks, name).append(fn)
