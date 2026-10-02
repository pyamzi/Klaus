"""Automatic sync: Klaus syncs with AnkiWeb in the background and hides
Anki's Sync button (spec docs/superpowers/specs/2026-10-02-auto-sync-design.md).

Above the "aqt glue" divider: the policy (``due``), the status copy, the
Sync-link rewrite and the Auto Sync add-on stand-down, all aqt-free.
"""
from __future__ import annotations

import re

IDLE_S = 120               # no input this long → sync
MIN_GAP_S = 300            # AnkiWeb is asked at most this often
AFTER_REVIEW_S = 30        # leaving a review → sync this much later
AFTER_REVIEW_QUIET_S = 5   # ...once there has been no input this long
FAIL_LIMIT = 3             # failures in a row before the entry turns red
TICK_MS = 10_000


def due(now: float, *, last_input: float, last_attempt: float,
        review_left_at: float | None, state: str, ready: bool) -> bool:
    """Whether a quiet sync should start now."""
    if not ready or state == "review" or now - last_attempt < MIN_GAP_S:
        return False
    if now - last_input >= IDLE_S:
        return True
    return (review_left_at is not None and now - review_left_at >= AFTER_REVIEW_S
            and now - last_input >= AFTER_REVIEW_QUIET_S)


def ago(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


def entry_text(now: float, last_sync: float | None, failures: int,
               full_pending: bool) -> tuple[str, bool]:
    """The sync entry's text and whether it is red."""
    if full_pending:
        return "Full sync needed — click to choose", True
    if failures >= FAIL_LIMIT:
        return "Sync failed — click to retry", True
    if not last_sync:
        return "Not synced yet", False
    return f"Synced {ago(now - last_sync)}", False


def is_sync_link(html: str) -> bool:
    """Anki's Sync link, found by its id (its text is translated)."""
    return 'id="sync"' in html


_LINK = re.compile(r"(<a\b)([^>]*)(>)\s*[^<]*(<img)", re.S)


def link_html(original: str, *, logged_in: bool, active: bool) -> str:
    """Anki's Sync link, hidden while logged in, "Log In" while logged out.
    Both ids stay: Anki's spinner and colour scripts look them up."""
    if not active:
        return original
    if logged_in:
        return original.replace("<a ", '<a style="display:none" ', 1)

    def login(m: re.Match) -> str:
        attrs = re.sub(r'aria-label="[^"]*"', 'aria-label="Log In"', m.group(2))
        attrs = re.sub(r'title="[^"]*"', 'title="Log in to AnkiWeb"', attrs)
        return f"{m.group(1)}{attrs}{m.group(3)}Log In{m.group(4)}"

    return _LINK.sub(login, original, count=1)


def standing_down(mgr) -> bool:
    """True when an installed, enabled add-on calls itself Auto Sync."""
    try:
        for folder in mgr.allAddons():  # first: isEnabled is True for a missing folder
            if not mgr.isEnabled(folder):
                continue
            name = re.sub(r"[-_]+", " ", str(mgr.addonName(folder) or folder)).casefold()
            if "auto sync" in name:
                return True
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync stand-down check failed: {exc}")
    return False


# ── aqt glue ─────────────────────────────────────────────────────────────
#
# The quiet sync is Klaus's own call of the backend method, never
# aqt.sync.sync_collection: that one opens Anki's progress window on every
# run, a warning dialog on every error, and goes straight into the
# upload/download question for a full sync. Syncs the user asks for (the
# entry, Y, Log In) are Anki's own, dialogs and all.
#
# Anki's toolbar.redraw() does NOT rebuild links (only draw() re-runs
# top_toolbar_did_init_links), so a login or logout redraws through
# _redraw_if_login_changed.

import time
from typing import Callable

clock = time.monotonic

_enabled = True
_standing_down = False
_last_input = 0.0
_last_attempt = float("-inf")
_review_left_at: float | None = None
_failures = 0
_full_pending = False
_quiet_running = False
_anki_running = False
_drawn_logged_in: bool | None = None
_listeners: list = []
_timer: list = []   # the tick QTimer, once a profile is open
_activity: list = []  # the app-wide input filter, installed once


def active() -> bool:
    return _enabled and not _standing_down


def standing_down_now() -> bool:
    return _standing_down


def _logged_in() -> bool:
    from aqt import mw

    try:
        return bool(mw.pm.sync_auth())
    except Exception:  # noqa: BLE001
        return False


def entry_state() -> dict:
    from aqt import mw

    last = None
    try:
        ms = mw.col.db.scalar("select ls from col")
        last = ms / 1000 if ms else None
    except Exception:  # noqa: BLE001
        pass
    text, red = entry_text(time.time(), last, _failures, _full_pending)
    return {"visible": _logged_in(), "text": text, "red": red}


def add_listener(fn: Callable[[dict], None]) -> None:
    if fn not in _listeners:
        _listeners.append(fn)


def remove_listener(fn) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def _notify() -> None:
    try:
        state = entry_state()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync state failed: {exc}")
        return
    for fn in list(_listeners):
        try:
            fn(state)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] auto sync listener failed: {exc}")


def _redraw_if_login_changed() -> None:
    global _drawn_logged_in
    now = _logged_in()
    if now == _drawn_logged_in:
        return
    _drawn_logged_in = now
    try:
        from aqt import mw

        mw.toolbar.draw()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync toolbar draw failed: {exc}")


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)
    try:
        from aqt import mw

        mw.toolbar.draw()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync toolbar draw failed: {exc}")
    _notify()


def sync_now() -> None:
    """Anki's own sync, a tick later (never inside a webchannel call)."""
    try:
        from aqt import mw
        from aqt.qt import QTimer

        QTimer.singleShot(0, lambda: mw.on_sync_button_clicked())
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] sync now failed: {exc}")


def _ready() -> bool:
    from aqt import mw

    try:
        return (active() and bool(mw._can_sync_unattended())
                and not (_quiet_running or _anki_running or _full_pending
                         or mw.media_syncer.is_syncing()))
    except Exception:  # noqa: BLE001
        return False


def _tick() -> None:
    try:
        from aqt import mw

        _redraw_if_login_changed()
        if due(clock(), last_input=_last_input, last_attempt=_last_attempt,
               review_left_at=_review_left_at, state=getattr(mw, "state", ""), ready=_ready()):
            _run_quiet()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync tick failed: {exc}")
    _notify()


def _run_quiet() -> None:
    global _last_attempt, _review_left_at, _quiet_running
    from aqt import gui_hooks, mw

    _last_attempt = clock()
    _review_left_at = None
    _quiet_running = True
    try:
        gui_hooks.sync_will_start()
        auth = mw.pm.sync_auth()
        mw.taskman.run_in_background(
            lambda: mw.col.sync_collection(auth, mw.pm.media_syncing_enabled()), _on_done)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync start failed: {exc}")
        _quiet_running = False


def _on_done(fut) -> None:
    global _failures, _full_pending, _quiet_running
    from aqt import gui_hooks, mw

    try:
        try:
            mw.col._load_scheduler()  # the scheduler version may have changed
        except Exception:  # noqa: BLE001
            pass
        from anki.errors import Interrupted, SyncError, SyncErrorKind

        try:
            out = fut.result()
        except Interrupted:
            pass
        except SyncError as err:
            if err.kind is SyncErrorKind.AUTH:
                mw.pm.clear_sync_auth()  # the button becomes Log In
            else:
                _failures += 1
        except Exception as err:  # noqa: BLE001
            print(f"[klausmate] auto sync failed: {err}")
            _failures += 1
        else:
            _failures = 0
            mw.pm.set_host_number(out.host_number)
            if out.new_endpoint:
                mw.pm.set_current_sync_url(out.new_endpoint)
            if out.server_message:
                from aqt.utils import showText

                showText(out.server_message, parent=mw, type="rich")
            if out.required == out.NO_CHANGES:
                mw.media_syncer.start_monitoring()
            else:
                _full_pending = True  # never started here: the entry asks
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync result failed: {exc}")
    finally:
        for step in (lambda: mw.col.models._clear_cache(),
                     gui_hooks.sync_did_finish,  # while _quiet_running: our own fire
                     mw.reset,
                     mw.toolbar.update_sync_status):
            try:
                step()
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] auto sync finish step failed: {exc}")
        _quiet_running = False
        _redraw_if_login_changed()
        _notify()


def _on_anki_sync_start() -> None:
    global _anki_running
    if not _quiet_running:
        _anki_running = True


def _on_anki_sync_finish() -> None:
    global _anki_running, _last_attempt, _failures, _full_pending
    if _quiet_running:
        return
    _anki_running = False
    _last_attempt = clock()
    _failures = 0  # Anki's own flow already showed any error
    _full_pending = False
    _redraw_if_login_changed()
    _notify()


def _on_links(links: list, _toolbar) -> None:
    global _drawn_logged_in
    _drawn_logged_in = _logged_in()
    for i, item in enumerate(links):
        if isinstance(item, str) and is_sync_link(item):
            links[i] = link_html(item, logged_in=_drawn_logged_in, active=active())


def _on_state(new_state: str, old_state: str) -> None:
    global _review_left_at
    if old_state == "review" and new_state != "review":
        _review_left_at = clock()


def _install_activity() -> None:
    if _activity:
        return
    from aqt.qt import QApplication, QEvent, QObject

    kinds = {QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel}

    class Activity(QObject):
        """Records the time of the last key, click or scroll; consumes nothing."""

        def eventFilter(self, obj, ev) -> bool:  # noqa: N802 - Qt override
            global _last_input
            if ev.type() in kinds:
                _last_input = clock()
            return False

    app = QApplication.instance()
    _activity.append(Activity(app))
    app.installEventFilter(_activity[0])


def _on_profile_open() -> None:
    global _enabled, _last_input, _last_attempt, _review_left_at, _failures
    global _full_pending, _quiet_running, _anki_running, _drawn_logged_in
    try:
        from aqt import mw
        from aqt.qt import QTimer

        from . import settings

        _enabled = settings.read().get("auto_sync", True) is not False
        _last_input, _last_attempt, _review_left_at = clock(), float("-inf"), None
        _failures, _full_pending, _quiet_running, _anki_running = 0, False, False, False
        _drawn_logged_in = _logged_in()
        _install_activity()
        if not _timer:
            t = QTimer(mw)
            t.timeout.connect(_tick)
            _timer.append(t)
        _timer[0].start(TICK_MS)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] auto sync start failed: {exc}")


def _on_profile_close() -> None:
    if _timer:
        try:
            _timer[0].stop()
        except Exception:  # noqa: BLE001
            pass


def setup() -> None:
    global _standing_down
    from aqt import gui_hooks, mw

    _standing_down = standing_down(mw.addonManager)
    gui_hooks.profile_did_open.append(_on_profile_open)
    gui_hooks.profile_will_close.append(_on_profile_close)
    gui_hooks.state_did_change.append(_on_state)
    gui_hooks.sync_will_start.append(_on_anki_sync_start)
    gui_hooks.sync_did_finish.append(_on_anki_sync_finish)
    gui_hooks.top_toolbar_did_init_links.append(_on_links)
