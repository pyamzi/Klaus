"""The PDF reader's tab strip: ``[＋] [tabs]  …  [page n/m]``.

One strip per ``PdfSidebar`` (its ``tabs`` attribute), so every host — the
editor dock, the Lecture panel — has its own tab set. Moved out of
the editor dock in PDF reader 3/5; the dock itself went with the Add tab
(2026-10-01), so every host shows the strip above the reader.

The strip only shows names and reports what the user did; the reader
(``PdfSidebar``) loads documents and persists the set:

- ``activated(name)``: a tab became current — a click, the neighbour Qt
  selects when the current tab closes, or ``open(name)``.
- ``closed(name)``: the tab's ✕, or ``close(name)``; emitted after removal.
- ``add_requested()``: ＋ was pressed.
"""

from __future__ import annotations

from typing import Optional

def tab_label(name: str) -> str:
    """What a tab shows for the stored PDF ``name``: the name the Library
    shows (drive.json's display name, no ``.pdf``), else ``name``."""
    try:
        from . import drive_store, settings

        display = drive_store.display_name(settings.user_files(), name)
    except Exception:  # noqa: BLE001
        display = name
    if display.lower().endswith(".pdf"):
        display = display[:-4]
    return display.strip() or name


from aqt.qt import (
    QHBoxLayout,
    QLabel,
    QTabBar,
    QToolButton,
    QWidget,
    Qt,
    pyqtSignal,
)


class ReaderTabs(QWidget):
    activated = pyqtSignal(str)
    closed = pyqtSignal(str)
    add_requested = pyqtSignal()

    def __init__(
        self, parent: Optional[QWidget] = None, page_label: Optional[QLabel] = None
    ) -> None:
        super().__init__(parent)
        # The dock header's objectName, so theme.panel_header_qss styles
        # these tabs exactly as it styled them in the header.
        self.setObjectName("KlausPanelHeader")
        self.setFixedHeight(30)
        # WA_StyledBackground because a plain QWidget won't paint a
        # stylesheet background.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            from . import theme as _theme

            self.setStyleSheet(_theme.panel_header_qss(_theme.night_mode()))
        except Exception as exc:
            print(f"[klaus_note] reader tabs theme failed: {exc}")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 6, 0)
        row.setSpacing(4)

        self.add_btn = QToolButton(self)
        self.add_btn.setText("＋")
        self.add_btn.setAutoRaise(True)
        self.add_btn.setToolTip("Open another PDF in a new tab")
        # `clicked` carries a `checked` bool; add_requested takes none.
        self.add_btn.clicked.connect(lambda *_: self.add_requested.emit())
        row.addWidget(self.add_btn)

        self.bar = QTabBar(self)
        self.bar.setDocumentMode(True)
        self.bar.setDrawBase(False)
        self.bar.setMovable(True)
        self.bar.setUsesScrollButtons(True)
        self.bar.setExpanding(False)
        self.bar.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.bar.currentChanged.connect(self._on_current_changed)
        # Stretch factor 0 plus the stretch below: the tab bar takes only
        # the width its tabs need, and the page label sits at the right end.
        row.addWidget(self.bar, 0)
        row.addStretch(1)

        # The viewer's page indicator (its click opens Go to Page; the
        # filter travels with the label), else a plain label of our own.
        self.page_label = page_label if page_label is not None else QLabel("", self)
        self.page_label.setVisible(True)
        row.addWidget(self.page_label)

    # ---- the interface ----

    def names(self) -> list[str]:
        return [self._name_at(i) for i in range(self.bar.count())]

    def current(self) -> Optional[str]:
        idx = self.bar.currentIndex()
        return self._name_at(idx) if idx >= 0 else None

    def set_tabs(self, names: list[str], active: Optional[str]) -> None:
        """Show exactly ``names`` (``active`` selected when given) without
        activating anything — a restored tab set is labels only."""
        self.bar.blockSignals(True)
        try:
            while self.bar.count():
                self.bar.removeTab(0)
            for name in names:
                if self._find_tab(name) < 0:
                    self._add_tab(name)
            idx = self._find_tab(active) if active else -1
            if idx >= 0:
                self.bar.setCurrentIndex(idx)
        finally:
            self.bar.blockSignals(False)

    def open(self, name: str) -> None:
        """Add ``name`` (or find it), select it and emit ``activated`` once."""
        if not name:
            return
        self.bar.blockSignals(True)
        try:
            idx = self._find_tab(name)
            if idx < 0:
                idx = self._add_tab(name)
            self.bar.setCurrentIndex(idx)
        finally:
            self.bar.blockSignals(False)
        self.activated.emit(name)

    def close(self, name: str) -> None:  # noqa: A003 — the interface's name
        idx = self._find_tab(name)
        if idx < 0:
            return
        # Removing the current tab makes QTabBar select a neighbour, which
        # fires currentChanged and so activates that PDF first.
        self.bar.removeTab(idx)
        self.closed.emit(name)

    def set_page(self, n: int, total: int) -> None:
        self.page_label.setText(f"{n} / {total}" if total > 0 else "")

    # ---- per-tab ✕ ----

    def _add_tab(self, name: str) -> int:
        """The tab shows the Library's name for ``name``; ``name`` itself
        rides in the tab data, which is what the interface reports."""
        label = tab_label(name)
        # "&&": a lone & is a mnemonic to QTabBar ("Hematology & Oncology"
        # lost its ampersand and underlined the O).
        idx = self.bar.addTab(label.replace("&", "&&"))
        self.bar.setTabData(idx, name)
        self._decorate_tab(idx)
        self.bar.setTabToolTip(idx, label)
        return idx

    def _name_at(self, idx: int) -> str:
        data = self.bar.tabData(idx)
        return data if isinstance(data, str) and data else self.bar.tabText(idx)

    def _decorate_tab(self, idx: int) -> None:
        # Every tab is added through here, so this is the one place a tab's
        # tooltip needs setting: the FULL name, since ElideMiddle can only
        # show part of it once tabs saturate the bar (final-review M9).
        self.bar.setTabToolTip(idx, self.bar.tabText(idx))
        btn = QToolButton(self.bar)
        btn.setText("✕")
        btn.setAutoRaise(True)
        btn.setFixedSize(16, 16)
        btn.setStyleSheet("font-size: 10px; border: none;")
        btn.setToolTip("Close this PDF (keeps the stored file)")
        btn.clicked.connect(lambda _=False, b=btn: self._close_tab_of(b))
        self.bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)

    def _close_tab_of(self, btn: QToolButton) -> None:
        for i in range(self.bar.count()):
            if self.bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self.close(self._name_at(i))
                return

    # ---- tab bookkeeping ----

    def _find_tab(self, name: str) -> int:
        for i in range(self.bar.count()):
            if self._name_at(i) == name:
                return i
        return -1

    def _on_current_changed(self, idx: int) -> None:
        if idx >= 0:
            self.activated.emit(self._name_at(idx))
