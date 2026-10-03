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


STATES = ("synced", "syncing", "never", "failed", "full")
RED_STATES = ("failed", "full")


def entry(now: float, last_sync: float | None, failures: int,
          full_pending: bool, running: bool) -> tuple[str, str]:
    """The sync icon's state and its tooltip, which says what the icon
    means and what a click does."""
    if running:
        return "syncing", "Syncing with AnkiWeb…"
    if full_pending:
        return "full", "AnkiWeb needs a full sync. Click to choose whether to upload or download."
    if failures >= FAIL_LIMIT:
        return "failed", "Couldn't sync with AnkiWeb. KlausNote keeps retrying; click to try now."
    if not last_sync:
        return "never", "Not synced with AnkiWeb yet. Click to sync now."
    return "synced", f"Synced with AnkiWeb {ago(now - last_sync)}. Click to sync now."


# 24-unit outline icons, drawn here (no icon font in Anki's webviews or Qt).
_CLOUD = "M7 18h10a4 4 0 0 0 .6-7.96A5.5 5.5 0 0 0 7 9.05A4.5 4.5 0 0 0 7 18z"
_ICON_PATHS = {
    "synced": (_CLOUD, "M9.5 14l2 2l3.5-3.5"),
    "never": (_CLOUD,),
    "failed": (_CLOUD, "M10 12l4 4M14 12l-4 4"),
    "syncing": ("M20 11A8.1 8.1 0 0 0 4.5 9M4 5v4h4", "M4 13a8.1 8.1 0 0 0 15.5 2M20 19v-4h-4"),
    "full": ("M7 3v18M4 6l3-3l3 3", "M17 21V3M14 18l3 3l3-3"),
}


def icon_svg(state: str, px: int, color: str = "currentColor") -> str:
    paths = "".join(f'<path d="{d}"/>' for d in _ICON_PATHS.get(state, _ICON_PATHS["never"]))
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>')


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
        print(f"[klaus_note] auto sync stand-down check failed: {exc}")
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
# Last sync, wall seconds. Cached: a sync holds the collection lock for its
# whole run, so a main-thread read (every tick, every entry) would freeze the
# UI. Read from the collection only when nothing syncs.
_last_sync: float | None = None
_listeners: list = []
_dialogs: list = []  # shown server-message dialogs, kept until closed
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


def _read_last_sync() -> None:
    """Refresh ``_last_sync`` from the collection (main thread, no sync running)."""
    global _last_sync
    if _quiet_running or _anki_running:
        return
    try:
        from aqt import mw

        ms = mw.col.db.scalar("select ls from col")
        if ms:
            _last_sync = max(_last_sync or 0, ms / 1000)
    except Exception:  # noqa: BLE001
        pass


def entry_state() -> dict:
    state, tip = entry(time.time(), _last_sync, _failures, _full_pending,
                       _quiet_running or _anki_running)
    return {"visible": _logged_in(), "state": state, "tip": tip, "red": state in RED_STATES}


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
        print(f"[klaus_note] auto sync state failed: {exc}")
        return
    for fn in list(_listeners):
        try:
            fn(state)
        except Exception as exc:  # noqa: BLE001
            print(f"[klaus_note] auto sync listener failed: {exc}")


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
        print(f"[klaus_note] auto sync toolbar draw failed: {exc}")


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)
    try:
        from aqt import mw

        mw.toolbar.draw()
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] auto sync toolbar draw failed: {exc}")
    _notify()


def sync_now() -> None:
    """Anki's own sync, a tick later (never inside a webchannel call)."""
    try:
        from aqt import mw
        from aqt.qt import QTimer

        QTimer.singleShot(0, lambda: mw.on_sync_button_clicked())
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] sync now failed: {exc}")


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
        print(f"[klaus_note] auto sync tick failed: {exc}")
    _notify()


def _run_quiet() -> None:
    global _last_attempt, _review_left_at, _quiet_running
    from aqt import gui_hooks, mw

    _last_attempt = clock()
    _review_left_at = None
    _quiet_running = True
    _notify()  # the icon spins
    try:
        gui_hooks.sync_will_start()
        auth = mw.pm.sync_auth()
        col, media = mw.col, mw.pm.media_syncing_enabled()

        def task():
            # ls moves only when something was transferred (finalize_sync);
            # read on the worker, which already holds the collection.
            before = col.db.scalar("select ls from col")
            result = col.sync_collection(auth, media)
            return result, before, col.db.scalar("select ls from col")

        mw.taskman.run_in_background(task, _on_done)
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] auto sync start failed: {exc}")
        _quiet_running = False


def _on_done(fut) -> None:
    global _failures, _full_pending, _quiet_running, _last_sync
    from aqt import gui_hooks, mw

    if getattr(mw, "col", None) is None:
        # The profile closed under the sync: no collection for the finish
        # steps, and a listener that throws is dropped from the hook for good.
        _quiet_running = False
        return
    changed = False
    try:
        try:
            mw.col._load_scheduler()  # the scheduler version may have changed
        except Exception:  # noqa: BLE001
            pass
        from anki.errors import Interrupted, SyncError, SyncErrorKind

        try:
            out, before, after = fut.result()
        except Interrupted:
            pass
        except SyncError as err:
            if err.kind is SyncErrorKind.AUTH:
                mw.pm.clear_sync_auth()  # the button becomes Log In
            else:
                _failures += 1
        except Exception as err:  # noqa: BLE001
            print(f"[klaus_note] auto sync failed: {err}")
            _failures += 1
        else:
            _failures = 0
            _last_sync = time.time()
            changed = before != after
            mw.pm.set_host_number(out.host_number)
            if out.new_endpoint:
                mw.pm.set_current_sync_url(out.new_endpoint)
            if out.server_message:
                from aqt.utils import showText

                # run=False: showText's default exec()s (app-modal, K-114).
                diag, _box = showText(out.server_message, parent=mw, type="rich", run=False)
                _dialogs.append(diag)
                try:
                    diag.finished.connect(lambda *_a, d=diag: _dialogs.remove(d) if d in _dialogs else None)
                except Exception:  # noqa: BLE001
                    pass
                diag.show()
            if out.required == out.NO_CHANGES:
                mw.media_syncer.start_monitoring()
            else:
                _full_pending = True  # never started here: the entry asks
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] auto sync result failed: {exc}")
    finally:
        # Reset only when the sync changed the collection: mw.reset() reloads
        # Browse's table and editor, and Add's notetype, every time it runs.
        steps = [lambda: mw.col.models._clear_cache()] if changed else []
        steps.append(gui_hooks.sync_did_finish)  # while _quiet_running: our own fire
        if changed:
            steps.append(mw.reset)
        steps.append(mw.toolbar.update_sync_status)
        for step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001
                print(f"[klaus_note] auto sync finish step failed: {exc}")
        _quiet_running = False
        _redraw_if_login_changed()
        _notify()


def _on_anki_sync_start() -> None:
    global _anki_running
    if not _quiet_running:
        _anki_running = True
        _notify()  # the icon spins


def _on_anki_sync_finish() -> None:
    global _anki_running, _last_attempt, _failures, _full_pending
    if _quiet_running:
        return
    _anki_running = False
    _last_attempt = clock()
    _failures = 0  # Anki's own flow already showed any error
    _full_pending = False
    _read_last_sync()
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
    global _full_pending, _quiet_running, _anki_running, _drawn_logged_in, _last_sync
    try:
        from aqt import mw
        from aqt.qt import QTimer

        from . import settings

        _enabled = settings.read().get("auto_sync", True) is not False
        _last_input, _last_attempt, _review_left_at = clock(), float("-inf"), None
        _failures, _full_pending, _quiet_running, _anki_running = 0, False, False, False
        _drawn_logged_in = _logged_in()
        _last_sync = None  # another profile's time must not carry over
        _read_last_sync()
        _install_activity()
        if not _timer:
            t = QTimer(mw)
            t.timeout.connect(_tick)
            _timer.append(t)
        _timer[0].start(TICK_MS)
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] auto sync start failed: {exc}")


def _on_profile_close() -> None:
    if _quiet_running:
        try:
            from aqt import mw

            mw.col.abort_sync()  # takes no collection lock; the result is Interrupted
        except Exception as exc:  # noqa: BLE001
            print(f"[klaus_note] auto sync abort failed: {exc}")
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
