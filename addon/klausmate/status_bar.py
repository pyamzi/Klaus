"""Browse's bottom bar — and the Add tab's: a gear that opens Anki's
Preferences on the left, then a progress readout of every running process
(``tasks``), and the layout toggles at the far right (◧ sidebar, ◨ card
editor on Browse; ◧ Library tree, ◨ editor on the Add tab, bound to two
given widgets through ``panes``). The main window has no Qt bar: its row
is Anki's own, extended by ``bottom_row``, which shares this module's
readout rules, gear shape and task list. Klaus's own settings are the top
bar's star.

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
# The whole strip matches the macOS title bar (28pt since Big Sur).
# QStatusBar hard-codes 3px above its items and ~2px below, so the bar
# inside gets what's left, which also centres it in the strip.
STRIP_HEIGHT = 28
BAR_HEIGHT = STRIP_HEIGHT - 3 - 2


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

        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
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
    def __init__(self, window, browser=None, panes=None) -> None:
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
        elif panes is not None:
            row.setSpacing(2)
            self._add_pane_toggles(row, *panes)
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

    def _add_pane_toggles(self, row, left, right) -> None:
        """The Add tab: ◧ the Library tree, ◨ the editor slot."""
        from .browse_toggles import _PaneToggle, _VisibilityWatcher

        for side, pane, widget, attr in (("left", "tree", left, "sidebar_btn"), ("right", "editor", right, "editor_btn")):
            btn = _PaneToggle(side, pane, not widget.isHidden())
            btn.clicked.connect(widget.setVisible)
            _VisibilityWatcher(widget, btn.setChecked)
            row.addWidget(btn)
            setattr(self, attr, btn)

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
            anchor = self.progress.mapToGlobal(self.progress.rect().topLeft())
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
    screen = parent.screen() if hasattr(parent, "screen") else None
    area = screen.availableGeometry() if screen is not None else None
    x, y = anchor.x(), anchor.y() - frame.height() - 2
    if area is not None:
        x = max(area.left(), min(x, area.right() + 1 - frame.width()))
        y = max(area.top(), y)
    frame.move(x, y)
    frame.show()
    return frame


# ── install ──────────────────────────────────────────────────────────────

_bars: list = []  # live bars, for theme_did_change


def _track(bar: StatusBar) -> StatusBar:
    _bars.append(bar)
    bar.destroyed.connect(lambda *_a, b=bar: _bars.remove(b) if b in _bars else None)
    return bar


def install_add_tab(page, left, right) -> StatusBar | None:
    """The Add tab's bar: appended under the page's content, no close
    control (Close and Escape switch tabs)."""
    try:
        bar = StatusBar(page, panes=(left, right))
        bar.setFixedHeight(BAR_HEIGHT)
        page.layout().addWidget(bar)
        bar.apply_theme()
        return _track(bar)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] status bar (Add tab) failed: {exc}")
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
        try:
            from . import single_window

            if single_window.is_active():
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
