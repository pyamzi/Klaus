"""Klaus Workspace (K-102) — one window for Klaus-OWNED surfaces.

The sanctioned successor to the removed single-window mode: a sidebar +
QStackedWidget shell whose views are widgets Klaus builds itself (today:
the Library, i.e. ``DriveWindow(hosted=True)``; later: Phase D's
embedding map and a curation view). Anki's own windows are NEVER
embedded — the K-059..K-062 attempt died on exactly that (dark webview
panes, five failed rework rounds, K-090..K-094) — so the sidebar's
Decks/Add/Browse/Stats/Sync entries are LAUNCHERS that open the stock
windows. AnkiHub and every other addon that decorates Anki's windows is
untouched by design.

Selected by config key ``workspace_enabled`` (default False). When on,
``pdf_drive._create`` builds this window under the Library's existing
aqt.dialogs name, so the toolbar "Library" link, profile-close teardown,
and background refresh hooks all work unchanged; when off, behaviour is
byte-identical to the standalone Library window.

Pure helpers (:func:`workspace_from_config`, :data:`NAV_ITEMS`,
:func:`launcher_action`) are aqt-free for tests/test_workspace.py.
Launcher API names were verified against the 26.8.1 bytecode:
``mw.moveToState("deckBrowser")``, dialogs ``AddCards``/``Browser``,
``mw.onStats``, ``mw.on_sync_button_clicked``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# Guarded Qt imports — headless tests import this module with stub aqt.
try:
    import aqt
    from aqt import mw
    from aqt.qt import (
        QButtonGroup,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
        Qt,
    )

    WORKSPACE_AVAILABLE = True
except Exception:  # pragma: no cover — stripped test stubs only
    aqt = mw = None  # type: ignore[assignment]
    QButtonGroup = QHBoxLayout = QLabel = QPushButton = None  # type: ignore
    QStackedWidget = QVBoxLayout = QWidget = Qt = None  # type: ignore
    WORKSPACE_AVAILABLE = False


def workspace_from_config(cfg: Any) -> bool:
    """True only when the config explicitly opts in (default off —
    mirrors pdfjs_viewer.renderer_from_config's degradation rules)."""
    if not isinstance(cfg, dict):
        return False
    return cfg.get("workspace_enabled") is True


# The sidebar, in order. kind "view" = a page in the stack (only the
# Library today); kind "launcher" = opens the stock Anki surface.
NAV_ITEMS: list[tuple[str, str, str]] = [
    ("library", "Library", "view"),
    ("decks", "Decks", "launcher"),
    ("add", "Add", "launcher"),
    ("browse", "Browse", "launcher"),
    ("stats", "Statistics", "launcher"),
    ("sync", "Sync", "launcher"),
]


def launcher_action(key: str) -> Callable[[], None] | None:
    """The stock-Anki opener for a launcher key (None for unknown keys
    and for view keys). Late-bound so tests can inspect the mapping
    headlessly; every call is guarded per the addon convention."""

    def _decks() -> None:
        mw.moveToState("deckBrowser")
        mw.raise_()
        mw.activateWindow()

    def _add() -> None:
        aqt.dialogs.open("AddCards", mw)

    def _browse() -> None:
        aqt.dialogs.open("Browser", mw)

    def _stats() -> None:
        mw.onStats()

    def _sync() -> None:
        mw.on_sync_button_clicked()

    return {
        "decks": _decks,
        "add": _add,
        "browse": _browse,
        "stats": _stats,
        "sync": _sync,
    }.get(key)


class WorkspaceWindow(QWidget):  # type: ignore[misc]
    """Sidebar + stacked views. Owns window chrome for the hosted
    Library (title, geometry via the Library's own drive_store state,
    close teardown); the hosted DriveWindow owns everything inside its
    splitter, including its splitter-size persistence."""

    silentlyClose = True  # aqt.dialogs profile-switch teardown contract

    def __init__(
        self,
        library: Any,
        on_closed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self._library = library
        self._on_closed = on_closed
        self.setWindowTitle("Klaus")
        self.setMinimumSize(860, 480)
        self.setObjectName("KlausWorkspace")
        try:
            from . import theme

            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setStyleSheet(theme.workspace_qss(theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] workspace theme failed: {exc}")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- sidebar rail ----
        rail = QWidget(self)
        rail.setObjectName("KlausWorkspaceSidebar")
        try:
            rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        rail.setFixedWidth(170)
        rail_lay = QVBoxLayout(rail)
        rail_lay.setContentsMargins(12, 16, 12, 12)
        rail_lay.setSpacing(4)

        logo = QLabel("Klaus", rail)
        logo.setObjectName("WorkspaceLogo")
        logo.setFixedHeight(56)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rail_lay.addWidget(logo)
        rail_lay.addSpacing(10)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, Any] = {}
        for key, label, kind in NAV_ITEMS:
            btn = QPushButton(label, rail)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if kind == "view":
                btn.setCheckable(True)
                self._group.addButton(btn)
                btn.clicked.connect(
                    lambda _c=False, k=key: self._show_view(k)
                )
            else:
                btn.clicked.connect(
                    lambda _c=False, k=key: self._launch(k)
                )
            self._buttons[key] = btn
            rail_lay.addWidget(btn)
        rail_lay.addStretch(1)
        outer.addWidget(rail)

        # ---- stacked views ----
        self._stack = QStackedWidget(self)
        self._view_index: dict[str, int] = {}
        self._view_index["library"] = self._stack.addWidget(library)
        outer.addWidget(self._stack, 1)

        self._show_view("library")
        self._restore_geometry()
        try:
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception as exc:
            print(f"[klausmate] workspace show failed: {exc}")

    # ---- navigation ------------------------------------------------------

    def _show_view(self, key: str) -> None:
        idx = self._view_index.get(key)
        if idx is None:
            return
        self._stack.setCurrentIndex(idx)
        btn = self._buttons.get(key)
        if btn is not None:
            try:
                btn.setChecked(True)
            except Exception:
                pass

    def _launch(self, key: str) -> None:
        action = launcher_action(key)
        if action is None:
            return
        try:
            action()
        except Exception as exc:
            print(f"[klausmate] workspace launcher {key} failed: {exc}")

    # ---- geometry (own key in drive.json, separate from the standalone
    # Library window's so the two modes never fight) ----------------------

    _GEOMETRY_KEY = "workspace_window"

    def _user_files(self) -> str | None:
        try:
            from . import USER_FILES  # type: ignore

            return USER_FILES
        except Exception:
            return None

    def _restore_geometry(self) -> None:
        try:
            from . import drive_store

            uf = self._user_files()
            state = (
                drive_store.get_window_state(uf, key=self._GEOMETRY_KEY)
                if uf
                else {}
            )
            if state.get("w") and state.get("h"):
                self.resize(int(state["w"]), int(state["h"]))
                if state.get("x") is not None and state.get("y") is not None:
                    self.move(int(state["x"]), int(state["y"]))
            else:
                self.resize(1200, 720)
        except Exception as exc:
            print(f"[klausmate] workspace geometry restore failed: {exc}")
            try:
                self.resize(1200, 720)
            except Exception:
                pass

    def _save_geometry(self) -> None:
        try:
            from . import drive_store

            uf = self._user_files()
            if not uf or not self.isVisible():
                return
            geo = self.geometry()
            drive_store.save_window_state(
                uf,
                {
                    "x": geo.x(),
                    "y": geo.y(),
                    "w": geo.width(),
                    "h": geo.height(),
                },
                key=self._GEOMETRY_KEY,
            )
        except Exception as exc:
            print(f"[klausmate] workspace geometry save failed: {exc}")

    # ---- teardown --------------------------------------------------------

    def closeEvent(self, evt) -> None:  # noqa: N802 — Qt naming
        self._save_geometry()
        try:
            # The hosted Library never gets a window closeEvent of its
            # own — run its teardown (cancel jobs, splitter persistence,
            # sidebar clear, _instance reset) here.
            if self._library is not None:
                self._library.shutdown()
        except Exception as exc:
            print(f"[klausmate] workspace library shutdown failed: {exc}")
        if self._on_closed is not None:
            try:
                self._on_closed()
            except Exception:
                pass
        try:
            from . import pdf_drive

            aqt.dialogs.markClosed(pdf_drive.DIALOG_NAME)
        except Exception:
            pass
        super().closeEvent(evt)
