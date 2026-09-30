"""The status bar along the bottom of the main window and Browse, like
VS Code's: Browse's layout toggles on the left (◧ sidebar, ◨ card
editor), then a progress readout of every running process (``tasks``)
and one gear holding KlausMate Settings and Anki Settings.

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
    QEvent,
    QFontMetrics,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QObject,
    QProgressBar,
    Qt,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

LABEL_MAX_PX = 320


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


class StatusBar(QWidget):
    def __init__(self, window, browser=None) -> None:
        super().__init__(window)
        self.setObjectName("KlausStatusBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(22)
        self.popup = None
        self.sidebar_btn = None
        self.editor_btn = None
        self._tasks: list = []
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 4, 0)
        row.setSpacing(6)
        if browser is not None:
            self._add_toggles(row, browser)
        row.addStretch(1)
        self.progress = QProgressBar(self)
        self.progress.setFixedWidth(120)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.label = QLabel("", self)
        self.label.setMaximumWidth(LABEL_MAX_PX)
        clicks = _ClickFilter(self, self.open_task_list)
        self.progress.installEventFilter(clicks)
        self.label.installEventFilter(clicks)
        self.gear = QToolButton(self)
        self.gear.setText("⚙")
        self.gear.setToolTip("Settings")
        self.gear.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.gear)
        menu.addAction("KlausMate Settings…").triggered.connect(lambda *_a: _open_klaus_settings())
        menu.addAction("Anki Settings…").triggered.connect(lambda *_a: _open_anki_settings())
        self.gear.setMenu(menu)
        row.addWidget(self.progress)
        row.addWidget(self.label)
        row.addWidget(self.gear)
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

            self.setStyleSheet(theme.status_bar_qss(theme.night_mode()))
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] status bar theme failed: {exc}")

    def refresh(self, items: list) -> None:
        self._tasks = list(items)
        running = [t for t in items if not t.message]
        text = readout_text(items)
        self.label.setText(QFontMetrics(self.label.font()).elidedText(
            text, Qt.TextElideMode.ElideMiddle, LABEL_MAX_PX))
        self.label.setToolTip(text)
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
        frame.setStyleSheet(self.styleSheet())
        col = QVBoxLayout(frame)
        col.setContentsMargins(10, 8, 10, 8)
        for t in self._tasks:
            line = QHBoxLayout()
            name = QLabel(t.message or t.label, frame)
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
        pos = self.mapToGlobal(self.rect().topRight())
        frame.move(pos.x() - frame.width(), pos.y() - frame.height() - 2)
        self.popup = frame
        frame.show()
