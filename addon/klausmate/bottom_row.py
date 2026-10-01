"""The main window's bottom row: Anki's own deck-list / overview row
(Get Shared, Create Deck, Import File, Add to Library; Options, Custom
Study…), left exactly as Anki draws it and extended with a gear that
opens Anki's Preferences at its left edge and, at its right edge, the
running-task readout (the newest task, then its progress bar, from
``tasks``; click → the task list with ✕), where the Add and Browse bars
show it too. Review's answer row is not touched. The row's height is
what those bars follow (``status_bar.set_row_height``).

It rides Anki's bottom webview rather than a Qt bar, so Anki's buttons
are never copied and the row is never hidden. The readout starts in the
state it was rendered with and follows ``tasks`` live through
``klausStatus`` evals while a deck screen shows.

Pure builders above the divider; the aqt glue below it.
"""
from __future__ import annotations

import json

from . import tasks

PREFS_CMD = "klausmate_row_prefs"
TASKS_CMD = "klausmate_row_tasks"
ROW_CONTEXTS = {"DeckBrowserBottomBar", "OverviewBottomBar"}
ROW_STATES = {"deckBrowser", "overview"}
GEAR_PX = 16


def row_state(items: list, now: float) -> dict:
    """What the readout shows, as plain JSON for the page."""
    from .status_bar import readout_text, visible_tasks

    shown, _wait = visible_tasks(items, now)
    running = [t for t in shown if not t.message]
    head = running[0] if running else None
    return {
        "text": readout_text(shown),
        "error": bool(shown) and not running and bool(shown[0].error),
        "running": head is not None,
        "busy": head is not None and head.total <= 0,
        "done": head.done if head else 0,
        "total": head.total if head else 0,
    }


def gear_svg() -> str:
    from .status_bar import gear_points

    pts = gear_points(GEAR_PX)
    d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    c = GEAR_PX / 2
    return (
        f'<svg width="{GEAR_PX}" height="{GEAR_PX}" viewBox="0 0 {GEAR_PX} {GEAR_PX}" '
        'fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" '
        f'aria-hidden="true"><path d="{d}"/><circle cx="{c}" cy="{c}" r="{GEAR_PX * 0.14:.2f}"/></svg>'
    )


_JS = """
function klausStatus(s) {
  var r = document.getElementById('klaus-status'); if (!r) return;
  var t = r.querySelector('.kr-text'), bar = r.querySelector('.kr-track'),
      fill = r.querySelector('.kr-fill');
  t.textContent = s.text; t.title = s.text;
  r.classList.toggle('kr-error', !!s.error);
  bar.style.display = s.running ? '' : 'none';
  bar.classList.toggle('kr-busy', !!s.busy);
  fill.style.width = s.busy ? '' : (s.total ? Math.min(100, 100 * s.done / s.total) + '%' : '0');
  klausFit();
}
function klausFit() {
  // Anki centres its buttons; the readout stops 24px short of the last.
  // Screen px over the body's zoom (bar_scale): getBoundingClientRect is
  // zoomed, a max-width inside the body is not.
  var r = document.getElementById('klaus-status'),
      bs = document.querySelectorAll('#outer button'), b = bs[bs.length - 1],
      z = parseFloat(getComputedStyle(document.body).zoom) || 1;
  if (r && b) r.style.maxWidth = Math.max(0, (window.innerWidth - b.getBoundingClientRect().right) / z - 8 - 24) + 'px';
}
window.addEventListener('resize', klausFit);
function klausKey(e, cmd) {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pycmd(cmd); }
}
// A click must not leave focus on a row button: the deck screens bind no
// Space shortcut, so the next Space reached klausKey and re-fired it (the
// Space re-fired the button). Tab still focuses them.
document.addEventListener('mousedown', function (e) {
  if (e.target.closest && e.target.closest('.klaus-edge [role=button]')) e.preventDefault();
});
"""


def row_html(state: dict, night: bool) -> str:
    """The gear, pinned to the row's left edge, and the readout, pinned to
    its right edge. Divs with ``role=button``, never ``<button>``: Anki's
    bottom-bar CSS frames every button, and this gear is a quiet icon."""
    from . import theme

    c = theme.palette(night)
    css = f"""
.klaus-edge {{ position: fixed; top: 0; bottom: 0; display: flex;
  align-items: center; gap: 8px; font-size: 12px; color: {c['text_muted']}; }}
#klaus-row {{ left: 8px; }}
#klaus-status {{ right: 8px; max-width: 30vw; }}
#klaus-row .kr-gear {{ display: flex; padding: 3px; border-radius: 5px; cursor: default; }}
#klaus-row .kr-gear:hover, #klaus-row .kr-gear:focus-visible {{ background: {c['hover_subtle']}; outline: none; }}
#klaus-status .kr-readout {{ display: flex; align-items: center; gap: 8px; min-width: 0; cursor: default; }}
#klaus-status .kr-track {{ position: relative; flex: none; width: 90px; height: 4px; overflow: hidden;
  border-radius: 2px; background: {c['grey_light']}; }}
#klaus-status .kr-fill {{ height: 100%; border-radius: 2px; background: {c['blue']}; }}
#klaus-status .kr-busy .kr-fill {{ position: absolute; width: 30%; animation: kr-slide 1.2s ease-in-out infinite; }}
@keyframes kr-slide {{ from {{ left: -30%; }} to {{ left: 100%; }} }}
#klaus-status .kr-text {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
#klaus-status.kr-error .kr-text {{ color: {c['red_text']}; }}
"""
    return (
        f"<style>{css}</style>"
        '<div id="klaus-row" class="klaus-edge">'
        f'<div class="kr-gear" role="button" tabindex="0" title="Anki Settings" aria-label="Anki Settings" '
        f'onclick=\'pycmd("{PREFS_CMD}")\' onkeydown=\'klausKey(event, "{PREFS_CMD}")\'>{gear_svg()}</div>'
        "</div>"
        '<div id="klaus-status" class="klaus-edge">'
        f'<div class="kr-readout" role="button" tabindex="0" onclick=\'pycmd("{TASKS_CMD}")\' '
        f'onkeydown=\'klausKey(event, "{TASKS_CMD}")\'>'
        '<span class="kr-text"></span><div class="kr-track"><div class="kr-fill"></div></div></div>'
        "</div>"
        f"<script>{_JS}klausStatus({json.dumps(state)});</script>"
    )


# ── aqt glue ─────────────────────────────────────────────────────────────


def _night() -> bool:
    try:
        from . import theme

        return theme.night_mode()
    except Exception:  # noqa: BLE001
        return False


def _on_webview_content(web_content, context) -> None:
    if type(context).__name__ not in ROW_CONTEXTS:
        return
    try:
        web_content.body += row_html(row_state(tasks.snapshot(), tasks.clock()), _night())
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] bottom row injection failed: {exc}")


def _on_js_message(handled, message: str, context):
    if message not in (PREFS_CMD, TASKS_CMD):
        return handled
    # Both open a tick later, never inside the webchannel call (the
    # deferral rule, tests/test_bridge_reentrancy.py).
    try:
        from aqt.qt import QTimer

        from . import status_bar

        if message == PREFS_CMD:
            QTimer.singleShot(0, status_bar._open_anki_settings)
        else:
            QTimer.singleShot(0, _open_task_list)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] bottom row click failed: {exc}")
    return (True, None)


def _open_task_list() -> None:
    try:
        from aqt import mw
        from aqt.qt import QCursor

        from . import status_bar

        items, _wait = status_bar.visible_tasks(tasks.snapshot(), tasks.clock())
        if items:
            status_bar.show_task_list(mw, items, QCursor.pos())
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] bottom row task list failed: {exc}")


def _push(snap: list) -> None:
    """Follow ``tasks`` live on the deck screens; look again when a young
    task comes of age or a message's linger runs out."""
    try:
        from aqt import mw

        if getattr(mw, "state", "") not in ROW_STATES:
            return
        from .status_bar import visible_tasks

        now = tasks.clock()
        state = row_state(snap, now)
        mw.bottomWeb.eval(f"window.klausStatus && klausStatus({json.dumps(state)});")
        _shown, wait = visible_tasks(snap, now)
        if wait is None and any(t.message and not t.error for t in snap):
            wait = tasks.LINGER_S + 0.05
        if wait is not None:
            from aqt.qt import QTimer

            QTimer.singleShot(int(wait * 1000) + 20, lambda: _push(tasks.snapshot()))
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] bottom row update failed: {exc}")


_height_filter: list = []


def _report_height(web) -> None:
    try:
        from aqt import mw

        if getattr(mw, "state", "") in ROW_STATES and web.height() > 0:
            from . import status_bar

            status_bar.set_row_height(web.height())
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] bottom row height failed: {exc}")


def _watch_height() -> None:
    try:
        from aqt import mw

        from aqt.qt import QEvent, QObject

        web = getattr(mw, "bottomWeb", None)
        if web is None or _height_filter:
            return

        class Resized(QObject):
            """Reports the row's height on every resize of Anki's bottom
            webview (``_report_height`` ignores the taller review row)."""

            def eventFilter(self, obj, ev) -> bool:  # noqa: N802 - Qt override
                if ev.type() == QEvent.Type.Resize:
                    _report_height(obj)
                return False

        _height_filter.append(Resized(web))
        web.installEventFilter(_height_filter[0])
        _report_height(web)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] bottom row height watch failed: {exc}")


def setup() -> None:
    from aqt import gui_hooks

    gui_hooks.main_window_did_init.append(_watch_height)
    gui_hooks.webview_will_set_content.append(_on_webview_content)
    gui_hooks.webview_did_receive_js_message.append(_on_js_message)
    tasks.add_listener(_push)
