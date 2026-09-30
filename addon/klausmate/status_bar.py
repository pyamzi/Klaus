"""The status bar along the bottom of the main window and Browse, like
VS Code's: one gear holding KlausMate Settings and Anki Settings on the
left, then a progress readout of every running process (``tasks``), and
Browse's layout toggles (◧ sidebar, ◨ card editor) at the far right.

Pure helpers above the divider; the widget and install glue below it.
"""
from __future__ import annotations

import sys

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


# ── aqt glue ─────────────────────────────────────────────────────────────

from aqt.qt import (  # noqa: E402
    QColor,
    QEvent,
    QFontMetrics,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
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
# The whole strip matches the macOS title bar (28pt since Big Sur).
# QStatusBar hard-codes 3px above its items and ~2px below, so the bar
# inside gets what's left, which also centres it in the strip.
STRIP_HEIGHT = 28
BAR_HEIGHT = STRIP_HEIGHT - 3 - 2
SHOW_DELAY_S = 0.5  # a task quicker than this never flashes the bar


def _open_klaus_settings() -> None:
    try:
        sys.modules[__package__].manage_models_dialog()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar: KlausMate settings failed: {exc}")


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
    """An 8-tooth gear outline centred in a ``size`` box, with its hub
    hole — drawn, because the ⚙ glyph renders at whatever the fallback
    font picks."""
    import math

    c, ro, ri, hub = size / 2.0, size * 0.44, size * 0.32, size * 0.14
    path = QPainterPath()
    pts = []
    for k in range(8):
        a = k * 45.0
        for r, da in ((ri, -15.0), (ro, -9.0), (ro, 9.0), (ri, 15.0)):
            t = math.radians(a + da)
            pts.append(QPointF(c + r * math.cos(t), c + r * math.sin(t)))
    path.moveTo(pts[0])
    for p in pts[1:]:
        path.lineTo(p)
    path.closeSubpath()
    path.addEllipse(QPointF(c, c), hub, hub)
    return path


class _GearButton(QToolButton):
    """The settings gear: painted like the pane toggles (nothing at rest,
    a grey wash on hover) so the bar's three icons read as one set, and
    with no menu arrow."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        from .browse_toggles import BUTTON_SIZE

        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.setAutoRaise(True)  # repaints on hover
        self._tab_focus = False
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Settings")
        self.setAccessibleName("Settings")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

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
            from .browse_toggles import CHIP_RADIUS, ICON_SIZE, stroke_width

            c = theme.palette(theme.night_mode())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w, h = float(self.width()), float(self.height())
            if self.isDown() or self.underMouse() or self.show_focus():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c["hover_subtle"]))
                painter.drawRoundedRect(QRectF(0.0, 0.0, w, h), CHIP_RADIUS, CHIP_RADIUS)
            painter.translate(round((w - ICON_SIZE) / 2.0), round((h - ICON_SIZE) / 2.0))
            pen = QPen(QColor(c["text_muted"]))
            pen.setWidthF(stroke_width(ICON_SIZE))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(gear_path(ICON_SIZE))
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
        self._tasks: list = []
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(6)
        self.gear = _GearButton(self)
        menu = QMenu(self.gear)
        menu.addAction("KlausMate Settings…").triggered.connect(lambda *_a: _open_klaus_settings())
        menu.addAction("Anki Settings…").triggered.connect(lambda *_a: _open_anki_settings())
        self.gear.setMenu(menu)
        row.addWidget(self.gear)
        self.progress = QProgressBar(self)
        self.progress.setFixedWidth(120)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.label = QLabel("", self)
        self.label.setMaximumWidth(LABEL_MAX_PX)
        clicks = _ClickFilter(self, self.open_task_list)
        self.progress.installEventFilter(clicks)
        self.label.installEventFilter(clicks)
        row.addWidget(self.progress)
        row.addSpacing(2)
        row.addWidget(self.label)
        row.addStretch(1)
        if browser is not None:
            row.setSpacing(2)  # the two toggles sit as a pair
            self._add_toggles(row, browser)
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

        dock = getattr(browser, "sidebarDockWidget", None)
        if dock is not None:
            btn = _PaneToggle("left", "sidebar", dock.isVisible())
            btn.clicked.connect(dock.setVisible)
            try:
                dock.visibilityChanged.connect(btn.setChecked)
            except Exception:  # noqa: BLE001
                pass
            row.addWidget(btn)
            self.sidebar_btn = btn
        col = _editor_column(browser)
        if col is not None:
            btn = _PaneToggle("right", "editor", col.isVisible())
            btn.clicked.connect(col.setVisible)
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
            host.setStyleSheet(theme.status_bar_qss(theme.night_mode()))
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] status bar theme failed: {exc}")

    def refresh(self, items: list) -> None:
        now = tasks.clock()
        young = [t for t in items if not t.message and now - t.started < SHOW_DELAY_S]
        if young:
            wait = min(SHOW_DELAY_S - (now - t.started) for t in young)
            self._wake.start(int(wait * 1000) + 20)
            items = [t for t in items if t not in young]
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
        if not self._tasks:
            return
        frame = QFrame(self, Qt.WindowType.Popup)
        frame.setObjectName("KlausStatusBar")
        frame.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        from . import theme

        frame.setStyleSheet(theme.status_bar_qss(theme.night_mode()))
        col = QVBoxLayout(frame)
        col.setContentsMargins(10, 8, 10, 8)
        for t in self._tasks:
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
        # Above the readout, kept on this bar's screen.
        pos = self.progress.mapToGlobal(self.progress.rect().topLeft())
        area = self.screen().availableGeometry()
        x = max(area.left(), min(pos.x(), area.right() + 1 - frame.width()))
        y = max(area.top(), pos.y() - frame.height() - 2)
        frame.move(x, y)
        self.popup = frame
        frame.show()


# ── install ──────────────────────────────────────────────────────────────

_bars: list = []  # live bars, for theme_did_change


def _track(bar: StatusBar) -> StatusBar:
    _bars.append(bar)
    bar.destroyed.connect(lambda *_a, b=bar: _bars.remove(b) if b in _bars else None)
    return bar


def install_main(mw) -> StatusBar | None:
    """Give the main window a status bar. Anki's main.ui has none, so
    QMainWindow.statusBar() creates it."""
    existing = getattr(mw, "_klausmate_status_bar", None)
    if existing is not None:
        return existing
    try:
        native = mw.statusBar()
        native.setVisible(True)
        native.setSizeGripEnabled(False)
        bar = StatusBar(mw)
        native.addPermanentWidget(bar, 1)
        native.setFixedHeight(STRIP_HEIGHT)
        bar.apply_theme()
        mw._klausmate_status_bar = bar
        return _track(bar)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar (main window) failed: {exc}")
        return None


def install_browser(browser) -> StatusBar | None:
    """Browse has no status bar of its own: give it one, with toggles."""
    existing = getattr(browser, "_klausmate_status_bar", None)
    if existing is not None:
        return existing
    try:
        from aqt.qt import QStatusBar

        native = QStatusBar(browser)
        native.setSizeGripEnabled(False)
        browser.setStatusBar(native)
        bar = StatusBar(browser, browser=browser)
        native.addPermanentWidget(bar, 1)
        native.setFixedHeight(STRIP_HEIGHT)
        bar.apply_theme()
        browser._klausmate_status_bar = bar
        return _track(bar)
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
    install_main(mw)


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
    for name, fn in (
        ("sync_will_start", on_sync_will_start),
        ("sync_did_finish", on_sync_did_finish),
        ("media_sync_did_start_or_stop", on_media_sync_did_start_or_stop),
        ("media_sync_did_progress", on_media_sync_did_progress),
    ):
        if hasattr(gui_hooks, name):
            getattr(gui_hooks, name).append(fn)
