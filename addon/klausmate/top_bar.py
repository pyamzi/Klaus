"""The Klaus top bar — Anki's main-window toolbar, restyled in place.

What Pouya asked for after the Workspace detour: keep Anki's single
main window, but make the top toolbar a full-width Klaus bar with the
hand-drawn star at the left edge. The toolbar is a webview rendering
``<div class="header">`` (left-tray | links | right-tray), so this is
pure web-side work through two sanctioned hooks:

1. ``webview_will_set_content`` — when the context is
   ``aqt.toolbar.TopToolbar``, inject ``theme.toolbar_css`` into the
   head (the exact mechanism SynapsePro uses). Runs on every toolbar
   draw, so a night-mode flip restyles on the toolbar's own redraw.
2. ``top_toolbar_will_set_left_tray_content`` — prepend the star logo
   as the first left-tray item, i.e. the window's left edge.

RESTYLE ONLY: no element is hidden or replaced. Anki's own links,
Klaus's Library link (pdf_drive._on_toolbar_links), and other addons'
toolbar items — AnkiHub included — keep their handlers and inherit the
new look via the shared ``.hitem`` class.

``logo_html`` is aqt-free (pure string) for tests/test_top_bar.py.
"""

from __future__ import annotations

import json
from typing import Any

# Pouya's hand-drawn star, traced from his sketch (2026-08-25 revision):
# a POINT-DOWN pentagram — two peaks along the top, a point out each
# side, and one long point at the bottom — drawn as a single continuous
# stroke that crosses itself, with the sketch's slight tilt and uneven
# vertices preserved. Vertices were traced in the sketch's own pixel
# space and normalised into this 26x26 viewBox, so the proportions are
# the drawing's, not an idealised star's. Colour comes from the
# --klaus-accent CSS variable theme.toolbar_css defines — no hex here.
_STAR_PATH = (
    "M5.5 1.5 L23.6 13.7 L2.4 16.4 L17.8 1.8 L12.8 24.5 Z"
)

# The star's coordinate space (the SVG viewBox is 0 0 26 26).
STAR_VIEWBOX = 26.0


def star_points() -> list[tuple[float, float]]:
    """The star's vertices inside STAR_VIEWBOX, parsed from _STAR_PATH,
    so Qt surfaces (the Preferences sidebar logo) stroke the SAME
    hand-drawn mark the toolbar's SVG shows, from the same data."""
    pts: list[tuple[float, float]] = []
    for cmd in _STAR_PATH.replace("M", "").replace("Z", "").split("L"):
        parts = cmd.split()
        if len(parts) == 2:
            pts.append((float(parts[0]), float(parts[1])))
    return pts


def logo_html() -> str:
    """The left-edge logo: inline SVG star. Clicking it opens Klaus's
    own Preferences (``pycmd('klausmate:settings')``, intercepted in
    :func:`_on_js_message`) — Anki's Decks link sits right beside it,
    so the star is better spent on the settings Anki has no entry for."""
    return (
        '<a id="klaus-logo" href=# onclick="return pycmd(\'klausmate:settings\')" '
        'title="Klaus settings" aria-label="Klaus settings">'
        '<svg width="26" height="26" viewBox="0 0 26 26" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{_STAR_PATH}" fill="none" '
        'stroke="var(--klaus-accent)" stroke-width="2.3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg></a>"
    )


def native_chrome_color() -> str | None:
    """The window's ACTUAL background colour as Qt reports it, ``#rrggbb``.

    Pouya wants the bar to read as one surface with the OS title bar
    ("no lines, same exact color", macOS and Windows alike). Hardcoding
    a shade can't do that: the system chrome differs per OS, per
    version and per appearance. Qt's window-role colour follows all of
    that, so it is the closest thing to the title bar we can read
    without touching native window internals (NSWindow / DWM — the
    class of fiddling that killed single-window mode twice here).

    None whenever Qt is unavailable or the colour looks unusable, and
    the CSS token then stands as the fallback.
    """
    try:
        from aqt import mw
        from aqt.qt import QPalette

        colour = mw.palette().color(QPalette.ColorRole.Window)
        if not colour.isValid():
            return None
        return f"#{colour.red():02x}{colour.green():02x}{colour.blue():02x}"
    except Exception:
        return None


def chrome_override_js(colour: str | None) -> str:
    """JS that repaints the bar to ``colour`` (or clears the override).

    Sets the same custom property theme.toolbar_css defines, so the
    stylesheet stays the single source of the rules and this only
    overrides the one value. Clearing restores the token.
    """
    if not colour:
        return (
            "document.documentElement.style.removeProperty('--klaus-chrome');"
        )
    return (
        "document.documentElement.style.setProperty('--klaus-chrome', "
        + json.dumps(colour)
        + ");"
    )


def _push_chrome_colour() -> None:
    """Send the live window colour to the toolbar webview.

    Anki's theme switch never re-runs webview_will_set_content (it only
    toggles classes with JS), so the colour is pushed imperatively here
    instead — from our own theme_did_change hook, one tick later so
    Qt's palette has already been updated by Anki's own handler.
    """
    try:
        from aqt import mw
        from aqt.qt import QTimer

        def _send() -> None:
            try:
                web = getattr(getattr(mw, "toolbar", None), "web", None)
                if web is None:
                    return
                web.eval(chrome_override_js(native_chrome_color()))
            except Exception as exc:
                print(f"[klausmate] top bar chrome push failed: {exc}")

        QTimer.singleShot(0, _send)
    except Exception as exc:
        print(f"[klausmate] top bar chrome schedule failed: {exc}")


def _addon() -> str:
    """The addon's web-export name (its folder under addons21)."""
    try:
        from aqt import mw

        return mw.addonManager.addonFromModule(__name__)
    except Exception:
        return "klausmate"


def _config() -> dict:
    try:
        from aqt import mw

        return mw.addonManager.getConfig(__package__) or {}
    except Exception:
        return {}


def _background_css(bar: bool, bottom: bool = False) -> str:
    """CSS for the chosen background — the frosted variant for a bar
    (top by default, ``bottom=True`` for the bottom toolbar), the plain
    one for Anki's own screens. Empty in "theme" mode, so the default
    install paints nothing."""
    try:
        from . import background

        # effective_cfg: an unsaved Preferences preview wins over stored
        # config, so appearance edits render live before Save.
        spec = background.resolve(background.effective_cfg(_config()))
        url = background.image_url(_addon(), spec["image"])
        if bar:
            return background.bar_css(spec, url, bottom=bottom)
        return background.main_css(spec, url)
    except Exception as exc:
        print(f"[klausmate] background css failed: {exc}")
        return ""


def _on_main_webview_content(web_content: Any, context: Any) -> None:
    """Paint the custom background on Anki's own screens (deck list,
    overview, congrats). The reviewer is deliberately excluded — a
    wallpaper behind cards fights the card styling."""
    try:
        from aqt.deckbrowser import DeckBrowser
        from aqt.overview import Overview

        targets: tuple = (DeckBrowser, Overview)
        try:
            from aqt.deckdescription import CongratsPage  # type: ignore

            targets = targets + (CongratsPage,)
        except Exception:
            pass
        if not isinstance(context, targets):
            return
        css = _background_css(bar=False)
        if css:
            web_content.head += "<style>" + css + "</style>"
    except Exception as exc:
        print(f"[klausmate] background inject failed: {exc}")


def _on_js_message(handled: tuple, message: str, context: Any) -> tuple:
    """Intercept the star logo's pycmd. Anki's toolbar would otherwise
    treat the unknown command as a link and do nothing."""
    if message == "klausmate:settings":
        try:
            from aqt.qt import QTimer

            from .manage_models import manage_models_dialog

            # Deferred so the webchannel bridge call unwinds before any
            # dialog work runs (hygiene per tests/test_bridge_reentrancy).
            # NOTE the deferral alone did NOT stop the 2026-08-26 segfault
            # spree — crash reports showed the same devicePixelRatio/
            # flush crash from webchannel, QAction, AND timer dispatch
            # alike. The actual fix is manage_models_dialog opening
            # window-modal via dlg.open() instead of app-modal exec()
            # (see the comment there).
            QTimer.singleShot(0, manage_models_dialog)
        except Exception as exc:
            print(f"[klausmate] settings open failed: {exc}")
        return (True, None)
    return handled


def refresh() -> None:
    """Redraw the toolbar and the current screen after a settings change,
    so a new background lands without restarting Anki."""
    try:
        from aqt import mw

        if getattr(mw, "toolbar", None) is not None:
            mw.toolbar.draw()
        mw.reset()
    except Exception as exc:
        print(f"[klausmate] background refresh failed: {exc}")


def _on_left_tray(content: list, toolbar: Any) -> None:
    """First left-tray item = leftmost element of the bar. Other addons
    appending here (AnkiHub) land to the star's right, untouched."""
    try:
        content.insert(0, logo_html())
    except Exception as exc:
        print(f"[klausmate] top bar logo failed: {exc}")


def _on_webview_will_set_content(web_content: Any, context: Any) -> None:
    try:
        from aqt.toolbar import TopToolbar

        # The bottom toolbar (deck-browser/overview buttons) gets the
        # SAME chrome + frost as the top, so the window is bracketed by
        # matching bars. Matched by class NAME: these contexts live in
        # aqt.deckbrowser/aqt.overview and importing both here for an
        # isinstance would be needless coupling. The reviewer's answer
        # bar is deliberately excluded — its colours carry scheduling
        # meaning.
        if type(context).__name__ in (
            "DeckBrowserBottomBar",
            "OverviewBottomBar",
        ):
            from . import theme

            web_content.head += (
                "<style>" + theme.bottombar_css() + "</style>"
            )
            css = _background_css(bar=True, bottom=True)
            if css:
                web_content.head += "<style>" + css + "</style>"
            return

        if not isinstance(context, TopToolbar):
            return
        from . import theme

        # No night_mode() snapshot on purpose: the sheet carries BOTH
        # palettes keyed on Anki's own night-mode classes, so the bar
        # follows a theme switch live (Anki toggles those classes with
        # JS and never re-runs this hook). See theme.toolbar_css.
        web_content.head += "<style>" + theme.toolbar_css() + "</style>"
        # The custom background's frosted copy under the bar. A blurred
        # flat colour IS that colour, so "colour" mode makes the bar
        # match the window with no measuring at all.
        css = _background_css(bar=True)
        if css:
            web_content.head += "<style>" + css + "</style>"
    except Exception as exc:
        print(f"[klausmate] top bar css failed: {exc}")


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.top_toolbar_will_set_left_tray_content.append(_on_left_tray)
        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
        gui_hooks.webview_will_set_content.append(_on_main_webview_content)
        gui_hooks.webview_did_receive_js_message.append(_on_js_message)
        # Anki only toggles CSS classes on theme change; the native
        # window colour has to be re-read and pushed by us.
        gui_hooks.theme_did_change.append(_push_chrome_colour)
    except Exception as exc:
        print(f"[klausmate] top bar setup failed: {exc}")
