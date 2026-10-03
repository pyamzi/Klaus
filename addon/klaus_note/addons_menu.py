"""One "Add-ons" menu for every top-level menu that isn't Anki's own
(AMBOSS, AnKing, AnkiHub, …), placed just before Help, in the main window
and in Browse. A watcher on the menu bar moves menus add-ons add later
(AnkiHub builds its menu after the profile opens). The menus move whole,
so every add-on's items and shortcuts keep working.
"""
from __future__ import annotations

from aqt.qt import QEvent, QMenu, QObject, QTimer

# Anki's own menus, by their names on ``window.form`` (main.ui, browser.ui).
MAIN_MENUS = ("menuCol", "menuEdit", "menuqt_accel_view", "menuTools", "menuHelp")
BROWSE_MENUS = ("menuEdit", "menuqt_accel_view", "menu_Notes", "menu_Cards", "menuJump", "menu_Help")
TITLE = "Add-ons"


def place_before_help(bar, menu, help_menu) -> None:
    """Insert ``menu`` just before Help (or at the end without one)."""
    before = help_menu.menuAction() if help_menu is not None else None
    if before in bar.actions():
        bar.insertMenu(before, menu)
    else:
        bar.addMenu(menu)


def _consolidate(window, names) -> None:
    bar = window.menuBar()
    own = {getattr(window.form, n).menuAction() for n in names if getattr(window.form, n, None) is not None}
    # Menus another Klaus module put on the bar on purpose (the single
    # window's Browse menus) are never swept.
    own |= set(getattr(window, "_klaus_note_keep_on_bar", ()))
    addons = getattr(window, "_klaus_note_addons_menu", None)
    if addons is None:
        addons = QMenu(TITLE, window)
        window._klaus_note_addons_menu = addons
    stray = [a for a in bar.actions() if a not in own and a is not addons.menuAction()]
    for a in stray:
        bar.removeAction(a)
        addons.addAction(a)
    if addons.menuAction() not in bar.actions():
        place_before_help(bar, addons, getattr(window.form, names[-1], None))  # Help is last in both lists
    addons.menuAction().setVisible(bool(addons.actions()))


class _Watcher(QObject):
    """Re-runs the move a tick after anything lands on the menu bar."""

    def __init__(self, window, names) -> None:
        super().__init__(window)
        self._window, self._names, self._pending = window, names, False

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 - Qt override
        if ev.type() == QEvent.Type.ActionAdded and not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._run)
        return False

    def _run(self) -> None:
        self._pending = False
        try:
            _consolidate(self._window, self._names)
        except Exception as exc:  # noqa: BLE001
            print(f"[klaus_note] add-ons menu failed: {exc}")


def install(window, names) -> None:
    try:
        _consolidate(window, names)
        if getattr(window, "_klaus_note_addons_watcher", None) is None:
            w = _Watcher(window, names)
            window.menuBar().installEventFilter(w)
            window._klaus_note_addons_watcher = w
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] add-ons menu failed: {exc}")


def setup() -> None:
    from aqt import gui_hooks

    gui_hooks.main_window_did_init.append(lambda: _install_main())
    gui_hooks.browser_will_show.append(lambda browser: install(browser, BROWSE_MENUS))


def _install_main() -> None:
    from aqt import mw

    install(mw, MAIN_MENUS)
