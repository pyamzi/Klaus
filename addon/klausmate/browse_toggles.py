"""Browse toolbar toggles: sidebar / editor-column show-hide buttons and
the ``browser_will_show`` hook that installs them.

Extracted verbatim from __init__.py (K-024, slice 2 of the K-006 file
split). Backs the ◧ sidebar / ◨ editor column toggle buttons in the Browse
window's search-bar row.

This module is imported by __init__.py at package load time, so it must
never import __init__ (this package) at module load — only from inside a
function, after the package has finished loading. _pkg() below is that
lazy accessor (same pattern as curation.py's and manage_models.py's
_pkg()); it reaches a Browse helper that still lives in __init__.py:
_reset_browse_layout_to_defaults.
"""

from __future__ import annotations

from typing import Any, Callable

from aqt.qt import (
    QEvent,
    QHBoxLayout,
    QObject,
    QTimer,
    QToolButton,
    QWidget,
)


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _toggle_qss() -> str:
    """The ◧/◨ toggle chip, from theme tokens — accent-aware and
    night-aware (this predated the theme migration and was the last
    surface with its own hardcoded blue; found in the K-critique)."""
    try:
        from . import theme

        night = theme.night_mode()
        c = theme.palette(night)
        accent = theme.accent_rgba
        return (
            "QToolButton {"
            f" border: 1px solid {c['grey_mid']};"
            " border-radius: 6px;"
            " font-size: 14px;"
            f" color: {c['text_muted']};"
            f" background: {c['hover_subtle']};"
            "}"
            "QToolButton:hover {"
            f" color: {c['blue_accent']};"
            f" border-color: {accent(night, 0.45)};"
            f" background: {accent(night, 0.10)};"
            "}"
            "QToolButton:checked {"
            f" color: {c['blue_accent']};"
            f" border-color: {accent(night, 0.55)};"
            f" background: {accent(night, 0.14)};"
            "}"
        )
    except Exception as exc:
        print(f"[klausmate] browse toggle theme failed: {exc}")
        return ""


def _make_klaus_toggle(glyph: str, tip: str, checked: bool) -> QToolButton:
    btn = QToolButton()
    btn.setText(glyph)
    btn.setFixedSize(26, 26)
    btn.setToolTip(tip)
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setStyleSheet(_toggle_qss())
    return btn


class _VisibilityWatcher(QObject):
    """Calls ``on_change(visible)`` whenever ``target`` is shown or
    hidden — keeps a toggle button honest when other code (e.g. Anki's
    selection handling) flips the widget."""

    def __init__(
        self, target: QWidget, on_change: Callable[[bool], None]
    ) -> None:
        super().__init__(target)
        self._on_change = on_change
        target.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        t = ev.type()
        if t in (QEvent.Type.Show, QEvent.Type.Hide):
            try:
                self._on_change(t == QEvent.Type.Show)
            except Exception:
                pass
        return False


def _install_browser_sidebar_toggle(browser: Any) -> None:
    """Add always-visible, checkable toggle buttons to the Browse window:
    ◧ shows/hides the left sidebar, ◨ shows/hides the right card-editor
    column.

    Anki ships the sidebar as a left-pinned ``QDockWidget`` whose title
    bar is an empty ``QWidget`` — so its own close button is invisible;
    the editor column has no toggle at all (Anki only hides it when the
    selection isn't a single card). Both buttons stay in lockstep with
    the real visibility no matter what flips it (⌘⇧F, the View menu,
    selection changes).

    We do NOT touch the sidebar dock's areas / floating / features — the
    sidebar stays exactly where Anki pins it. Purely toggle affordances.
    """
    dock = getattr(browser, "sidebarDockWidget", None)
    grid = getattr(getattr(browser, "form", None), "gridLayout", None)
    if dock is None or grid is None:
        print("[klausmate] sidebar toggle: dock or gridLayout missing")
        return
    if getattr(browser, "_klausmate_sidebar_toggle_btn", None) is not None:
        return  # idempotent — the Browser instance may re-run setup

    btn = _make_klaus_toggle("◧", "Toggle sidebar", dock.isVisible())
    # A checkable button's clicked signal carries the new checked bool,
    # which is exactly the visibility we want — no need to re-read state.
    btn.clicked.connect(dock.setVisible)
    # Keep the button in lockstep with the dock — covers ⌘⇧F, the View
    # menu, and any other path that flips visibility. setChecked doesn't
    # re-emit clicked, so there's no feedback loop.
    try:
        dock.visibilityChanged.connect(btn.setChecked)
    except Exception:
        pass

    # The card-editor column: the direct child of the Browse splitter that
    # contains fieldsArea. Walking up (instead of naming a form attribute)
    # stays correct even after the PDF panel wraps the pane in its own
    # splitter.
    editor_col: QWidget | None = None
    try:
        splitter = browser.form.splitter
        w: QWidget | None = browser.form.fieldsArea
        while w is not None:
            p = w.parentWidget()
            if p is splitter:
                editor_col = w
                break
            w = p
    except Exception:
        editor_col = None

    editor_btn: QToolButton | None = None
    if editor_col is not None:
        col = editor_col
        editor_btn = _make_klaus_toggle(
            "◨", "Toggle card editor", col.isVisible()
        )
        editor_btn.clicked.connect(col.setVisible)
        # Anki shows/hides this pane itself on selection changes — the
        # watcher keeps the button truthful through those flips.
        _VisibilityWatcher(col, editor_btn.setChecked)

    # gridLayout cell (0, 0) is NOT free at runtime: Anki's Browser
    # constructor drops its Cards/Notes Switch there (setup_table ->
    # gridLayout.addWidget(switch, 0, 0)), while the search bar sits at
    # (0, 1). QGridLayout lets two widgets share a cell and just overlaps
    # them, so we pull the switch out and repack [◧ | switch] into a
    # single holder at the far left. The ◨ editor toggle mirrors it on
    # the right end of the row (cell (0, 2) is free), next to the pane
    # it controls.
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(btn)
    existing = grid.itemAtPosition(0, 0)
    if existing is not None:
        prev = existing.widget()
        if prev is not None:
            grid.removeWidget(prev)
            row.addWidget(prev)
    row.addStretch(1)
    grid.addWidget(holder, 0, 0)
    if editor_btn is not None:
        grid.addWidget(editor_btn, 0, 2)

    browser._klausmate_sidebar_toggle_btn = btn  # type: ignore[attr-defined]
    browser._klausmate_editor_toggle_btn = editor_btn  # type: ignore[attr-defined]
    print("[klausmate] sidebar + editor toggle buttons installed")


def on_browser_will_show(browser: Any) -> None:
    """``gui_hooks.browser_will_show`` callback — install Klaus's
    Browse-specific features:

    1. Repair leftover broken layout state from earlier add-on builds
       (``_reset_browse_layout_to_defaults``).
    2. Add the visible, one-click ◧ sidebar / ◨ editor-column toggle
       buttons.

    Earlier batches also wrapped the editor pane in a ``QDockWidget`` and
    added a View menu, plus a Browse natural-language ⌘K search that
    remapped Anki's native Mark hotkey out of the way. Those features were
    removed — the user preferred Anki's stock Browse layout, and Anki's
    native ⌘K Mark hotkey now works again. The sidebar toggle button
    re-added here does NOT touch the dock's areas/floating/features; it is
    purely a visible affordance for Anki's existing show/hide.

    Installs are deferred one event-loop tick (``QTimer.singleShot(0)``)
    so ``setupUi`` has finished wiring the form's actions and widgets
    before we touch them.
    """

    def _deferred() -> None:
        # Repair leftover broken layout state from earlier add-on builds:
        # re-anchor the sidebar to the left and undo any zero-width
        # splitter pane. No-op on a clean profile. Runs BEFORE the toggle
        # install so the button's initial checked state reads the final
        # (healed / profile-restored) sidebar visibility.
        try:
            _pkg()._reset_browse_layout_to_defaults(browser)
        except Exception as exc:
            print(f"[klausmate] browse layout reset failed: {exc}")
        try:
            _install_browser_sidebar_toggle(browser)
        except Exception as exc:
            print(f"[klausmate] sidebar toggle install failed: {exc}")

    try:
        QTimer.singleShot(0, _deferred)
    except Exception as exc:
        print(f"[klausmate] browser_will_show defer failed: {exc}")
        # Last-ditch synchronous attempt if the singleShot itself errored.
        _deferred()
