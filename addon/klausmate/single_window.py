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
    QShortcut,
    QSize,
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


def _swdbg(msg: str) -> None:
    """K-090 diagnostics — stdout is invisible under live Anki."""
    try:
        import time as _t

        with open("/tmp/klausmate-debug.txt", "a", encoding="utf-8") as fh:
            fh.write(f"{_t.strftime('%H:%M:%S')} sw: {msg}\n")
    except Exception:
        pass


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
        try:
            stack.currentChanged.connect(_on_stack_changed)
        except Exception:
            pass
        # K-090 tiling: macOS refuses a tile smaller than the window's
        # minimum — Anki's stock 640x480 beats a MacBook's top/bottom
        # tile height (~478pt). An explicit minimum overrides layout
        # hints, so the single window tiles anywhere.
        try:
            hint = mw.minimumSizeHint()
            mw.setMinimumSize(QSize(400, 300))
            _swdbg(
                f"shell up; min hint was {hint.width()}x{hint.height()}"
                f", forced 400x300"
            )
        except Exception as e:
            print(f"[klausmate] single-window min-size relax failed: {e}")
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


def _nudge_webviews(win: Any) -> None:
    """QtWebEngine composites out-of-process, and Chromium tracks PAGE
    visibility separately from the Qt widget: a view whose window was
    never shown can stay render-suspended (occluded) after the widget
    appears — the dark Add pane. Round 2 (K-091: widget hide/show alone
    proved insufficient live): force the page itself visible, thaw its
    lifecycle, and wiggle the size so the compositor must produce a
    frame. Runs on every switch — cheap and idempotent."""
    try:
        from aqt.webview import AnkiWebView

        views = win.findChildren(AnkiWebView)
        for wv in views:
            try:
                page = wv.page()
                try:
                    page.setVisible(True)
                except Exception:
                    pass
                try:
                    page.setLifecycleState(page.LifecycleState.Active)
                except Exception:
                    pass
                try:
                    _swdbg(
                        f"  view state={page.lifecycleState()} "
                        f"vis={wv.isVisible()} "
                        f"size={wv.width()}x{wv.height()} "
                        f"url={page.url().toString()[:60]}"
                    )
                except Exception:
                    pass
                wv.hide()
                wv.show()
                try:
                    sz = wv.size()
                    if sz.height() > 2:
                        wv.resize(sz.width(), sz.height() - 1)
                        wv.resize(sz)
                except Exception:
                    pass
            except Exception:
                continue
        try:
            _swdbg(
                f"nudged {len(views)} webview(s) of {type(win).__name__} "
                f"pane={win.width()}x{win.height()}"
            )
        except Exception:
            _swdbg(f"nudged webviews of {type(win).__name__}")
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window webview nudge failed: {e}")


def _looks_black(wv: Any) -> tuple:
    """Sample the widget's rendered frame (K-092): a never-attached
    Chromium surface grabs as pure black; even night-mode editor
    backgrounds (#2c2c2c) sum ~40x higher. Returns (is_black, detail
    string for the breadcrumbs)."""
    try:
        img = wv.grab().toImage()
        if img.isNull() or img.width() < 8 or img.height() < 8:
            return False, "no-image"
        w, h = img.width(), img.height()
        total = 0
        for fx in (0.15, 0.5, 0.85):
            for fy in (0.15, 0.5, 0.85):
                c = img.pixelColor(int(w * fx), int(h * fy))
                total += c.red() + c.green() + c.blue()
        mid = img.pixelColor(w // 2, h // 2)
        detail = f"sum={total} mid=({mid.red()},{mid.green()},{mid.blue()})"
        return total <= 27, detail
    except Exception as e:  # noqa: BLE001
        return False, f"grab-failed {e}"


def _rebind_webview(wv: Any) -> bool:
    """The cure for a delegate bound to a dead window (K-092): reparent
    the VIEW itself once — same slot, layout stretch / splitter sizes
    preserved — so QtWebEngine rebinds its render surface to the real
    native window."""
    try:
        parent = wv.parentWidget()
        if parent is None:
            return False
        lay = parent.layout() if hasattr(parent, "layout") else None
        if lay is not None and hasattr(lay, "indexOf"):
            idx = lay.indexOf(wv)
            if idx < 0:
                return False
            stretch = lay.stretch(idx) if hasattr(lay, "stretch") else 0
            wv.hide()
            lay.removeWidget(wv)
            wv.setParent(None)
            try:
                lay.insertWidget(idx, wv, stretch)
            except TypeError:
                lay.insertWidget(idx, wv)
            wv.show()
            return True
        if hasattr(parent, "indexOf") and hasattr(parent, "insertWidget"):
            # QSplitter child (Browser's editor area).
            idx = parent.indexOf(wv)
            if idx < 0:
                return False
            sizes = parent.sizes() if hasattr(parent, "sizes") else None
            wv.hide()
            wv.setParent(None)
            parent.insertWidget(idx, wv)
            if sizes is not None:
                try:
                    parent.setSizes(sizes)
                except Exception:
                    pass
            wv.show()
            return True
        return False
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window webview rebind failed: {e}")
        return False


def _nativeize_webviews(win: Any) -> None:
    """Round 5 (K-094): rebinding proved insufficient — the delegate
    kept presenting through the top-level backing-store route that
    never worked for these panes (offscreen frames perfect, screen
    black, rebind -> True). WA_NativeWindow gives each embedded webview
    its OWN native window and backing store, so it presents directly
    and the broken route stops mattering. winId() forces the native
    handle into existence before first paint."""
    try:
        from aqt.webview import AnkiWebView

        for wv in win.findChildren(AnkiWebView):
            try:
                wv.setAttribute(
                    Qt.WidgetAttribute.WA_NativeWindow, True
                )
                wid = wv.winId()
                _swdbg(
                    f"  nativeized {type(win).__name__} view "
                    f"winId={int(wid) if wid else 0:#x}"
                )
            except Exception as e:  # noqa: BLE001
                _swdbg(f"  nativeize failed: {e}")
                continue
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window nativeize failed: {e}")


def _heal_black_panes(win: Any, attempt: int = 0) -> None:
    """Detect-and-repair loop for black webview surfaces (K-092).
    Evidence-driven: only rebinds views whose grabbed frame is actually
    black, retries with a top-level resize wiggle, and breadcrumbs every
    verdict so a grab() false-negative is visible in the log."""
    try:
        if not _alive(win) or not win.isVisible():
            return
        from aqt.webview import AnkiWebView

        views = win.findChildren(AnkiWebView)
        black = []
        for wv in views:
            is_black, detail = _looks_black(wv)
            _swdbg(
                f"  heal a{attempt} {type(win).__name__} "
                f"{wv.width()}x{wv.height()} black={is_black} {detail}"
            )
            if is_black:
                black.append(wv)
        if not black:
            return
        for wv in black:
            ok = _rebind_webview(wv)
            _swdbg(f"  rebind -> {ok}")
        _focus_pane(win)
        if attempt >= 1:
            try:
                sz = mw.size()
                mw.resize(sz.width(), sz.height() + 1)
                mw.resize(sz)
                _swdbg("  wiggled mw")
            except Exception:
                pass
        if attempt < 3:
            QTimer.singleShot(
                700, lambda: _heal_black_panes(win, attempt + 1)
            )
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window heal failed: {e}")


def _focus_pane(win: Any) -> None:
    """activateWindow/raise_ are no-ops on child widgets — route focus
    by hand or typing keeps landing in the previous pane (K-090)."""
    try:
        ed = getattr(win, "editor", None)
        web = getattr(ed, "web", None) if ed is not None else None
        if web is not None:
            web.setFocus()
            return
        win.setFocus()
    except Exception:
        pass


def _set_mw_shortcuts_enabled(on: bool) -> None:
    """mw's QShortcuts (a/b/t/s/d, state keys...) are window-scoped and
    would fire from inside a pane's card table (K-090). Disable them
    while a pane is current; pane-descendant shortcuts are excluded via
    a parent-chain walk (panes are mw children, so findChildren sees
    their shortcuts too)."""
    try:
        panes = list(_state["panes"].values())
        for qs in mw.findChildren(QShortcut):
            try:
                inside = False
                p = qs.parent()
                while p is not None:
                    if any(p is pane for pane in panes):
                        inside = True
                        break
                    p = p.parent()
                if not inside:
                    qs.setEnabled(on)
            except Exception:
                continue
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window shortcut toggle failed: {e}")


def _on_stack_changed(index: int) -> None:
    try:
        if index == 0:
            _set_mw_shortcuts_enabled(True)
            try:
                mw.web.setFocus()
            except Exception:
                pass
            return
        _set_mw_shortcuts_enabled(False)
        stack = _state["stack"]
        pane = stack.currentWidget() if stack is not None else None
        if pane is not None:
            QTimer.singleShot(0, lambda w=pane: (_nudge_webviews(w), _focus_pane(w)))
            # The 0ms pass can predate the render surface — second pass
            # once Chromium has had a beat (K-091).
            QTimer.singleShot(400, lambda w=pane: _nudge_webviews(w))
            # Pixel-evidence repair loop for surfaces that stayed black
            # anyway (K-092).
            QTimer.singleShot(300, lambda w=pane: _heal_black_panes(w))
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] single-window stack-change failed: {e}")


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
    # K-094: give the render delegates their own native windows now
    # that the pane's top-level is the main window — deferred one tick
    # so the reparent has fully settled, still ahead of first paint.
    try:
        QTimer.singleShot(0, lambda w=win: _nativeize_webviews(w))
    except Exception:
        pass
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
