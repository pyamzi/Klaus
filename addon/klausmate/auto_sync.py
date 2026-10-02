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
