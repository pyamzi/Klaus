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

raise SystemExit(report())
