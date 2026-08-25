"""Single-window mode (K-059..K-062): Browse, Add, Library and Stats open
as PANES inside the main window instead of separate windows.

Why: macOS/Windows/Linux window managers can't tab or tile Anki's Qt
windows (no native tabbing participation, geometry restored from Anki's
own store, dialogs as top-level peers). Rather than fight the OS, the
app becomes one window — the existing top toolbar (Decks Add Library
Browse Stats Sync) already reads as a tab bar, so pressing a link now
switches a QStackedWidget below the toolbar instead of spawning windows.

Mechanics (verified against 26.8.1 bytecode — see K-059 card):
- The shell re-slots ``mw.web`` + ``mw.bottomWeb`` into page 0 of a
  QStackedWidget added to ``mw.mainLayout`` under ``mw.toolbarWeb``.
  ``setCentralWidget`` is never called (it deletes the old central
  widget); the layout keeps its owner.
- Each pane is intercepted at the sanctioned point: the aqt.dialogs
  creator. The factory suppresses the class's ``show()`` during
  ``__init__`` (Browser/AddCards/DriveWindow all self-show there), so
  reparenting happens BEFORE any native window exists — no Cocoa
  mid-gesture teardown (K-072 lesson).
- Shortcut collisions (ambiguous QShortcuts are DEAD keys — CLAUDE.md):
  every embedded pane's menubar actions become
  WidgetWithChildrenShortcut scoped to the pane; main-window actions
  whose key sequences overlap a pane's are scoped to the Decks page.
  Non-colliding mw actions keep window scope so they work from every
  pane. Overlaps are logged.
- Panes never raise the main window's minimum size (K-089 tiling):
  size policy Ignored + minimum 1x1, so macOS tiling / Windows Snap /
  Linux tiling WMs can shrink the single window freely.

EVERY step is wrapped so a failure degrades to stock multi-window
behavior — this must never break the main window.
"""

from __future__ import annotations

from typing import Any, Callable

import aqt
from aqt import gui_hooks, mw
from aqt.qt import (
    QDialog,
    QEvent,
    QObject,
    QSizePolicy,
    QStackedWidget,
    Qt,
    QTimer,
    QVBoxLayout,
    QWidget,
)

# Dialog-manager name -> pane config. Class import is lazy (aqt modules
# load on demand); title is only used for logs.
PANES: dict[str, dict[str, Any]] = {
    "Browser": {"title": "Browse"},          # K-059
    "AddCards": {"title": "Add"},            # K-060
    "KlausDrive": {"title": "Library"},      # K-061
    "NewDeckStats": {"title": "Stats"},      # K-062
}

_state: dict[str, Any] = {
    "hooked": False,       # factories + hooks registered (once per run)
    "installed": False,    # shell built into mw
    "stack": None,
    "decks_page": None,
    "panes": {},           # name -> live pane widget
    "watchers": {},        # name -> _CloseWatcher (kept alive)
    "orig_creators": {},   # name -> original aqt.dialogs creator
    "orig_open": None,
    "scoped_mw_keys": set(),  # key sequences already arbitrated
}


def _cfg() -> dict:
    try:
        return mw.addonManager.getConfig(__package__) or {}
    except Exception:
        return {}


def enabled() -> bool:
    return bool(_cfg().get("single_window_mode", True))


def _alive(w: Any) -> bool:
    try:
        w.isVisible()
        return True
    except RuntimeError:
        return False
    except Exception:
        return False


# ------------------------------------------------------------- shell


def _install_shell() -> bool:
    """Build the stack under the top toolbar. Idempotent; False = leave
    everything stock."""
    if _state["installed"]:
        return True
    try:
        lay = getattr(mw, "mainLayout", None)
        web = getattr(mw, "web", None)
        bottom = getattr(mw, "bottomWeb", None)
        if lay is None or web is None or bottom is None:
            print("[klausmate] single-window: mw layout not found; stock mode")
            return False
        stack = QStackedWidget()
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        lay.removeWidget(web)
        lay.removeWidget(bottom)
        v.addWidget(web, 1)
        v.addWidget(bottom, 0)
        stack.addWidget(page)
        lay.addWidget(stack, 1)
        _state["stack"] = stack
        _state["decks_page"] = page
        _state["installed"] = True
        print("[klausmate] single-window shell installed")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window shell failed (stock mode): {e}")
        return False


def _show_decks() -> None:
    try:
        stack = _state["stack"]
        if stack is not None:
            stack.setCurrentIndex(0)
    except Exception:
        pass


def _switch_to(name: str) -> None:
    try:
        pane = _state["panes"].get(name)
        stack = _state["stack"]
        if pane is None or stack is None or not _alive(pane):
            return
        stack.setCurrentWidget(pane)
        # The Library pane skips refreshes while hidden
        # (refresh_open_library's isVisible guard) — catch up on entry.
        if hasattr(pane, "_refresh_rows"):
            try:
                pane._refresh_rows()
            except Exception:
                pass
    except Exception:
        pass


# ------------------------------------------------------------- panes


def _pane_class(name: str):
    try:
        if name == "Browser":
            from aqt.browser.browser import Browser

            return Browser
        if name == "AddCards":
            from aqt.addcards import AddCards

            return AddCards
        if name == "NewDeckStats":
            from aqt.stats import NewDeckStats

            return NewDeckStats
        if name == "KlausDrive":
            from .pdf_drive import DriveWindow

            return DriveWindow
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window: no class for {name}: {e}")
    return None


class _CloseWatcher(QObject):
    """Removes a pane from the stack after it closes.

    Deferred one tick (K-072: never reparent inside event delivery) and
    re-checked: a pane still visible after the tick VETOED its close
    (AddCards' unsaved-note guard) and must stay."""

    def __init__(self, name: str) -> None:
        super().__init__(mw)
        self._name = name

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        try:
            if ev.type() == QEvent.Type.Close:
                QTimer.singleShot(0, lambda n=self._name: _drop_pane(n))
        except Exception:
            pass
        return False


def _drop_pane(name: str) -> None:
    try:
        pane = _state["panes"].get(name)
        if pane is None:
            return
        if _alive(pane) and pane.isVisible():
            return  # close was vetoed (unsaved-note guard) — keep it
        _state["panes"].pop(name, None)
        _state["watchers"].pop(name, None)
        stack = _state["stack"]
        if stack is not None and _alive(pane):
            try:
                stack.removeWidget(pane)
            except Exception:
                pass
        _show_decks()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window: drop {name} failed: {e}")


def _menu_actions(menubar) -> list:
    """Every QAction reachable from a menubar, submenus included."""
    out: list = []

    def walk(menu) -> None:
        for act in menu.actions():
            sub = act.menu()
            if sub is not None:
                walk(sub)
            elif not act.isSeparator():
                out.append(act)

    try:
        walk(menubar)
    except Exception:
        pass
    return out


def _action_keys(act) -> set:
    try:
        return {
            ks.toString()
            for ks in act.shortcuts()
            if ks and not ks.isEmpty()
        }
    except Exception:
        return set()


def _scope_shortcuts(win: QWidget) -> None:
    """Widget-scope the pane's own actions, then arbitrate collisions:
    any mw menubar action sharing a key sequence gets scoped to the
    Decks page. Ambiguous shortcuts would otherwise go DEAD."""
    pane_keys: set = set()
    try:
        mb = win.menuBar() if hasattr(win, "menuBar") else None
    except Exception:
        mb = None
    if mb is not None:
        for act in _menu_actions(mb):
            try:
                keys = _action_keys(act)
                if not keys:
                    continue
                act.setShortcutContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                win.addAction(act)
                pane_keys |= keys
            except Exception:
                continue
    if not pane_keys:
        return
    try:
        page = _state["decks_page"]
        mw_bar = mw.form.menubar
        for act in _menu_actions(mw_bar):
            keys = _action_keys(act)
            hits = keys & pane_keys
            if not hits or keys & _state["scoped_mw_keys"]:
                continue
            act.setShortcutContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            page.addAction(act)
            _state["scoped_mw_keys"] |= keys
            print(
                f"[klausmate] single-window: arbitrated shortcut(s) "
                f"{sorted(hits)} between mw and pane"
            )
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window: shortcut arbitration failed: {e}")


def _embed(name: str, win: QWidget) -> None:
    stack = _state["stack"]
    try:
        win.setWindowFlags(Qt.WindowType.Widget)
    except Exception:
        pass
    try:
        mb = win.menuBar() if hasattr(win, "menuBar") else None
        if mb is not None:
            # The native macOS menubar only serves top-level windows —
            # render the pane's menus as an in-pane strip instead.
            mb.setNativeMenuBar(False)
    except Exception:
        pass
    try:
        # K-089 tiling: a pane must never raise the single window's
        # minimum size (QStackedWidget minimums are the max over pages,
        # and Browser's table/splitter minimums would block half-screen
        # tiles on small displays).
        win.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        win.setMinimumSize(1, 1)
    except Exception:
        pass
    stack.addWidget(win)
    _state["panes"][name] = win
    watcher = _CloseWatcher(name)
    win.installEventFilter(watcher)
    _state["watchers"][name] = watcher
    _scope_shortcuts(win)
    try:
        if isinstance(win, QDialog):
            # QDialog.done() hides without a Close event — hook finished
            # so Stats' Close button still retires the pane.
            win.finished.connect(
                lambda _r, n=name: QTimer.singleShot(
                    0, lambda: _drop_pane(n)
                )
            )
    except Exception:
        pass
    stack.setCurrentWidget(win)


def _wrap_creator(name: str, creator: Callable) -> Callable:
    def factory(*args, **kwargs):
        if not enabled() or not _install_shell():
            return creator(*args, **kwargs)
        cls = _pane_class(name)
        had_own_show = cls is not None and "show" in cls.__dict__
        orig_show = getattr(cls, "show", None) if cls is not None else None
        if cls is not None:
            try:
                # __init__ self-shows; suppressing it means the pane is
                # reparented before any native window exists (K-072).
                cls.show = lambda self: None  # type: ignore[method-assign]
            except Exception:
                orig_show = None
        try:
            win = creator(*args, **kwargs)
        finally:
            if cls is not None and orig_show is not None:
                try:
                    if had_own_show:
                        cls.show = orig_show  # type: ignore[method-assign]
                    else:
                        del cls.show  # restore inheritance
                except Exception:
                    try:
                        cls.show = orig_show  # type: ignore[method-assign]
                    except Exception:
                        pass
        try:
            _embed(name, win)
        except Exception as e:  # noqa: BLE001
            print(
                f"[klausmate] single-window: embed {name} failed, "
                f"falling back to a window: {e}"
            )
            try:
                win.setWindowFlags(Qt.WindowType.Window)
                win.show()
            except Exception:
                pass
        return win

    return factory


# ------------------------------------------------------------- wiring


def _wrap_dialogs_open() -> None:
    if _state["orig_open"] is not None:
        return
    orig = aqt.dialogs.open

    def wrapped(name, *args, **kwargs):
        r = orig(name, *args, **kwargs)
        try:
            _switch_to(name)
        except Exception:
            pass
        return r

    _state["orig_open"] = orig
    aqt.dialogs.open = wrapped


def _on_state_change(new_state: str, old_state: str) -> None:
    # Decks/review navigation happens on page 0 — pressing Decks (or
    # answering into review) while a pane is up must bring page 0 back.
    _show_decks()


def _on_profile_open() -> None:
    if not enabled():
        return
    if not _install_shell():
        return
    if _state["hooked"]:
        return
    try:
        for name in PANES:
            try:
                entry = aqt.dialogs._dialogs.get(name)
                if not entry:
                    continue
                _state["orig_creators"][name] = entry[0]
                aqt.dialogs.register_dialog(
                    name, _wrap_creator(name, entry[0])
                )
            except Exception as e:  # noqa: BLE001
                print(
                    f"[klausmate] single-window: hook {name} failed: {e}"
                )
        _wrap_dialogs_open()
        gui_hooks.state_did_change.append(_on_state_change)
        _state["hooked"] = True
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window wiring failed: {e}")


def setup() -> None:
    try:
        gui_hooks.profile_did_open.append(_on_profile_open)
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window setup failed: {e}")
