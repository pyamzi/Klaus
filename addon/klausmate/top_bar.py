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

# The hand-drawn five-point star from Pouya's sketch: one open
# pentagram stroke with deliberately irregular vertices and a slight
# tilt so it keeps the sketched feel at 26px. Colour comes from the
# --klaus-accent CSS variable theme.toolbar_css defines — no hex here.
_STAR_PATH = (
    "M14.2 1.8 L19.6 23.4 L1.7 11.6 L24.3 10.1 L6.9 24.0 Z"
)


def logo_html() -> str:
    """The left-edge logo: inline SVG star, click goes to Decks (the
    same ``pycmd('decks')`` Anki's own Decks link uses)."""
    return (
        '<a id="klaus-logo" href=# onclick="return pycmd(\'decks\')" '
        'title="Klaus" aria-label="Klaus">'
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

        if not isinstance(context, TopToolbar):
            return
        from . import theme

        # No night_mode() snapshot on purpose: the sheet carries BOTH
        # palettes keyed on Anki's own night-mode classes, so the bar
        # follows a theme switch live (Anki toggles those classes with
        # JS and never re-runs this hook). See theme.toolbar_css.
        web_content.head += "<style>" + theme.toolbar_css() + "</style>"
        # First paint: apply the live window colour immediately so the
        # bar never flashes the token shade before the theme hook runs.
        colour = native_chrome_color()
        if colour:
            web_content.head += (
                "<style>:root, :root.night-mode, body.night_mode,"
                f" body.nightMode {{ --klaus-chrome: {colour}; }}</style>"
            )
    except Exception as exc:
        print(f"[klausmate] top bar css failed: {exc}")


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.top_toolbar_will_set_left_tray_content.append(_on_left_tray)
        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
        # Anki only toggles CSS classes on theme change; the native
        # window colour has to be re-read and pushed by us.
        gui_hooks.theme_did_change.append(_push_chrome_colour)
    except Exception as exc:
        print(f"[klausmate] top bar setup failed: {exc}")
