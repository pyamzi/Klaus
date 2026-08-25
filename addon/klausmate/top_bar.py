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

        web_content.head += (
            "<style>" + theme.toolbar_css(theme.night_mode()) + "</style>"
        )
    except Exception as exc:
        print(f"[klausmate] top bar css failed: {exc}")


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.top_toolbar_will_set_left_tray_content.append(_on_left_tray)
        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
    except Exception as exc:
        print(f"[klausmate] top bar setup failed: {exc}")
