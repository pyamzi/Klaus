"""Automatic sync (spec docs/superpowers/specs/2026-10-02-auto-sync-design.md):
the policy, the status copy, the Sync-link rewrite and the Auto Sync
stand-down (aqt-free), then the glue on a fake mw.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_auto_sync.py
"""
from __future__ import annotations

import importlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
A = importlib.import_module("klausmate.auto_sync")

section("due")
base = dict(last_input=0.0, last_attempt=0.0, review_left_at=None, state="deckBrowser", ready=True)


def d(now, **kw):
    return A.due(now, **{**base, **kw})


check("idle 119 s: no", not d(1000, last_input=881))
check("idle 120 s: yes", d(1000, last_input=880))
check("gap 299 s: no", not d(1000, last_attempt=701))
check("gap 300 s: yes", d(1000, last_attempt=700))
check("review: never", not d(1000, state="review"))
check("not ready: never", not d(1000, ready=False))
# after review: a busy user (input a few seconds ago), gap satisfied
check("29 s after review: no", not d(1000, last_input=994, review_left_at=971))
check("30 s after review, quiet 5 s: yes", d(1000, last_input=995, review_left_at=970))
check("30 s after review, input 4 s ago: no", not d(1000, last_input=996, review_left_at=970))
check("after review still respects the gap", not d(1000, last_input=995, review_left_at=970, last_attempt=800))

section("copy")
check("ago", [A.ago(s) for s in (0, 59, 60, 240, 3599, 3600, 7200, 86400 * 3)] ==
      ["just now", "just now", "1 min ago", "4 min ago", "59 min ago", "1 h ago", "2 h ago", "3 d ago"])
check("synced", A.entry_text(1240, 1000, 0, False) == ("Synced 4 min ago", False))
check("never", A.entry_text(1000, None, 0, False) == ("Not synced yet", False))
check("never (0)", A.entry_text(1000, 0, 0, False) == ("Not synced yet", False))
check("2 failures stay quiet", A.entry_text(1240, 1000, 2, False) == ("Synced 4 min ago", False))
check("3 failures: red", A.entry_text(1240, 1000, 3, False) == ("Sync failed — click to retry", True))
check("full pending beats failures",
      A.entry_text(1240, 1000, 5, True) == ("Full sync needed — click to choose", True))

section("link")
ANKI = ('<a class=hitem tabindex="-1" aria-label="Synchroniser" title="Raccourci : Y" id="sync" '
        'href=# onclick="return pycmd(\'sync\')"\n>Synchroniser<img id=sync-spinner '
        'src=\'/_anki/imgs/refresh.svg\'>\n</a>')
OTHER = '<a class=hitem id="decks" href=#>Decks</a>'
check("finds the link by id, not text", A.is_sync_link(ANKI) and not A.is_sync_link(OTHER))
check("inactive: untouched", A.link_html(ANKI, logged_in=True, active=False) == ANKI)
hidden = A.link_html(ANKI, logged_in=True, active=True)
check("logged in: hidden, ids kept",
      "display:none" in hidden and 'id="sync"' in hidden and "id=sync-spinner" in hidden, hidden)
login = A.link_html(ANKI, logged_in=False, active=True)
check("logged out: Log In, same pycmd and ids",
      ">Log In<img" in login and 'title="Log in to AnkiWeb"' in login and 'aria-label="Log In"' in login
      and "pycmd('sync')" in login and 'id="sync"' in login and "Synchroniser" not in login
      and "display:none" not in login, login)


class Mgr:
    def __init__(self, addons):
        self.a = addons  # dir -> (name, enabled)

    def allAddons(self):  # noqa: N802 - Anki's name
        return list(self.a)

    def isEnabled(self, d):  # noqa: N802
        return self.a.get(d, ("", True))[1]

    def addonName(self, d):  # noqa: N802
        return self.a[d][0]


section("stand-down")
check("stands down for an enabled Auto Sync", A.standing_down(Mgr({"501542723": ("AnkiWeb Auto Sync", True)})))
check("matches a GitHub folder name", A.standing_down(Mgr({"Auto-Sync-Anki-Addon": ("Auto-Sync-Anki-Addon", True)})))
check("disabled: no", not A.standing_down(Mgr({"x": ("Auto Sync", False)})))
check("missing folder (isEnabled True, not in allAddons): no", not A.standing_down(Mgr({})))
check("other add-ons: no", not A.standing_down(Mgr({"y": ("AnkiHub", True)})))

# ── glue, on a fake mw ───────────────────────────────────────────────────
import concurrent.futures  # noqa: E402
import types  # noqa: E402
from enum import Enum  # noqa: E402

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])


class SyncErrorKind(Enum):
    AUTH = 1
    NETWORK = 2


class SyncError(Exception):
    def __init__(self, kind):
        super().__init__(str(kind))
        self.kind = kind


class Interrupted(Exception):
    pass


errors = types.ModuleType("anki.errors")
errors.SyncError, errors.SyncErrorKind, errors.Interrupted = SyncError, SyncErrorKind, Interrupted
sys.modules["anki.errors"] = errors
sys.modules["anki"].errors = errors

fired: list = []


class Hook(list):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def __call__(self, *args):
        fired.append({"sync_will_start": "will", "sync_did_finish": "did"}.get(self.name, self.name))
        for fn in list(self):
            fn(*args)


class Hooks:
    def __getattr__(self, name):
        h = Hook(name)
        setattr(self, name, h)
        return h


hooks = Hooks()
sys.modules["aqt"].gui_hooks = hooks
shown: list = []
utils = types.ModuleType("aqt.utils")
utils.showText = lambda *a, **k: shown.append(a)
utils.tooltip = lambda *a, **k: shown.append(a)
sys.modules["aqt.utils"] = utils

auth = ["AUTH"]
starts: list = []
draws: list = []
clicked: list = []
resets_box = [0]
out = types.SimpleNamespace(required=0, NO_CHANGES=0, host_number=3, new_endpoint="", server_message="")
raise_with = None


def _sync_collection(a, media):
    if raise_with is not None:
        raise raise_with
    return out


def _run_in_background(task, on_done=None, **_kw):
    fut = concurrent.futures.Future()
    try:
        fut.set_result(task())
    except BaseException as exc:  # noqa: BLE001
        fut.set_exception(exc)
    if on_done:
        on_done(fut)
    return fut


def _clear_auth():
    auth[0] = None


mw = types.SimpleNamespace(
    pm=types.SimpleNamespace(
        sync_auth=lambda: auth[0], media_syncing_enabled=lambda: True,
        set_host_number=lambda n: None, set_current_sync_url=lambda u: None,
        clear_sync_auth=_clear_auth),
    col=types.SimpleNamespace(
        sync_collection=_sync_collection, _load_scheduler=lambda: None,
        models=types.SimpleNamespace(_clear_cache=lambda: None),
        db=types.SimpleNamespace(scalar=lambda q: 600_000)),
    taskman=types.SimpleNamespace(run_in_background=_run_in_background),
    toolbar=types.SimpleNamespace(draw=lambda: draws.append("draw"),
                                  update_sync_status=lambda: draws.append("update")),
    media_syncer=types.SimpleNamespace(is_syncing=lambda: False, start_monitoring=lambda: starts.append("media")),
    reset=lambda: resets_box.__setitem__(0, resets_box[0] + 1),
    state="deckBrowser",
    _can_sync_unattended=lambda: bool(auth[0]),
    safeMode=False,
    on_sync_button_clicked=lambda: clicked.append(1),
    addonManager=Mgr({}),
)
sys.modules["aqt"].mw = mw
A.setup()
A._enabled = True

section("quiet sync")
A._last_input = A.clock() - 999
A._last_attempt = -1e9
A._tick()
check("idle tick runs one quiet sync, no window",
      fired == ["will", "did"] and starts == ["media"] and resets_box[0] == 1, repr((fired, starts, resets_box)))
check("no dialog or tooltip", shown == [])
check("Anki's own sync_will_start handler ignores our run", not A._anki_running)
check("entry says Synced", A.entry_state()["text"].startswith("Synced") and not A.entry_state()["red"],
      repr(A.entry_state()))
A._tick()
check("the 5-minute gap holds", fired == ["will", "did"], repr(fired))

out.required = 2  # anything but NO_CHANGES
A._last_attempt = -1e9
A._tick()
check("full sync result: pending, red, no full sync started",
      A.entry_state()["text"] == "Full sync needed — click to choose" and A.entry_state()["red"])
A._last_attempt = -1e9
A._tick()
check("pending blocks further quiet syncs", fired.count("will") == 2, repr(fired))
A._on_anki_sync_start()
A._on_anki_sync_finish()  # the user pressed y / clicked the entry
check("Anki's own sync clears pending", not A._full_pending)
out.required = 0

raise_with = SyncError(SyncErrorKind.NETWORK)
for i in range(3):
    A._last_attempt = -1e9
    A._tick()
    if i == 1:
        check("2 failures: still quiet", not A.entry_state()["red"])
check("3 failures: red retry",
      A.entry_state() == {"visible": True, "text": "Sync failed — click to retry", "red": True}, repr(A.entry_state()))
check("still no dialog", shown == [])

raise_with = SyncError(SyncErrorKind.AUTH)
A._last_attempt = -1e9
d0 = len(draws)
A._tick()
check("auth error logs out silently and redraws as Log In",
      mw.pm.sync_auth() is None and "draw" in draws[d0:] and A.entry_state()["visible"] is False and shown == [],
      repr((auth, draws[d0:], A.entry_state())))
A._last_attempt = -1e9
n = fired.count("will")
A._tick()
check("logged out: nothing runs", fired.count("will") == n)

raise_with = Interrupted()
auth[0] = "AUTH"
A._failures = 0
A._last_attempt = -1e9
A._tick()
check("interrupted: no failure counted", A._failures == 0)
raise_with = None

section("toolbar follows login")
auth[0] = None
d0 = len(draws)
A._tick()
check("logout elsewhere → draw() within a tick", "draw" in draws[d0:])
auth[0] = "AUTH"
n = draws.count("draw")
A._on_anki_sync_start()
A._on_anki_sync_finish()
check("login via Log In → draw(), since redraw() keeps the link", draws.count("draw") == n + 1)
links = [ANKI, OTHER]
A._on_links(links, mw.toolbar)
check("logged in: link hidden in place", "display:none" in links[0] and links[1] == OTHER)
A.set_enabled(False)
links = [ANKI]
A._on_links(links, mw.toolbar)
check("switch off: Anki's button back", links == [ANKI])
A._last_attempt = -1e9
A._last_input = A.clock() - 999
n = fired.count("will")
A._tick()
check("switch off: tick does nothing", fired.count("will") == n)
A.set_enabled(True)

section("review")
mw.state = "review"
A._last_attempt = -1e9
n = fired.count("will")
A._tick()
check("never in review", fired.count("will") == n)
A._on_state("overview", "review")
mw.state = "overview"
check("leaving review records the time", A._review_left_at is not None)

section("listeners")
got: list = []
A.add_listener(got.append)
A._tick()
check("a tick notifies listeners with entry_state", got and got[-1] == A.entry_state())
A.remove_listener(got.append)

section("sync_now")
A.sync_now()
check("deferred: nothing inside the call", clicked == [])
app.processEvents()
check("...Anki's own sync a tick later", clicked == [1])

raise SystemExit(report())
