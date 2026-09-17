"""The Klaus top bar — Anki's main-window toolbar, restyled in place.

What Pouya asked for after the Workspace detour: keep Anki's single
main window, but make the top toolbar a full-width Klaus bar with the
impossible star at the left edge. The toolbar is a webview rendering
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

# Pouya's "impossible star" (K-270, 2026-09-17): five separate FILLED
# polygons — arms that read as one continuous star only because of
# where they stop, which is why none of them may be stroked and why the
# box's corners stay empty. The design source of record is
# klausmate/web/klaus-logo.svg, copied in unchanged; these are its five
# `d` strings verbatim, and tests/test_top_bar.py pins the two against
# each other so the drawing and the code cannot drift apart.
#
# THIS IS THE ONE COPY. The toolbar's inline SVG fills these strings;
# Qt surfaces (the Preferences sidebar logo) fill star_polygons(),
# parsed from the same strings. Colour never lives here — the web side
# takes --klaus-accent, the Qt side theme.palette()'s accent token.
_STAR_PATHS = (
    "M 724 578 L 719 582 L 718 588 L 728 619 L 744 651 L 769 731 L 791 780 L 794 797 L 835 893 L 859 963 L 853 970 L 846 968 L 754 897 L 747 896 L 638 972 L 634 979 L 637 984 L 659 996 L 698 1026 L 824 1098 L 896 1120 L 912 1119 L 944 1110 L 973 1094 L 1002 1057 L 1009 1032 L 1010 997 L 992 936 L 982 920 L 980 906 L 962 855 L 945 825 L 941 806 L 931 789 L 905 715 L 886 674 L 852 577 L 845 566 L 836 565 Z",
    "M 658 131 L 610 131 L 576 144 L 543 171 L 522 203 L 506 244 L 496 260 L 475 320 L 467 333 L 462 361 L 455 373 L 443 421 L 420 485 L 419 499 L 403 535 L 402 550 L 379 616 L 381 624 L 485 692 L 492 690 L 509 631 L 521 604 L 532 567 L 532 557 L 568 449 L 575 415 L 590 379 L 612 309 L 620 297 L 627 297 L 634 307 L 642 340 L 674 428 L 711 428 L 760 421 L 794 422 L 803 414 L 802 405 L 790 383 L 783 355 L 775 342 L 754 273 L 739 246 L 734 227 L 718 195 L 692 153 Z",
    "M 753 731 L 749 727 L 740 729 L 679 775 L 638 799 L 607 824 L 570 846 L 472 916 L 399 960 L 393 959 L 389 952 L 424 837 L 321 765 L 316 766 L 305 789 L 299 816 L 289 834 L 281 866 L 268 894 L 266 911 L 256 931 L 254 947 L 246 967 L 238 1005 L 238 1034 L 247 1064 L 273 1093 L 298 1109 L 314 1114 L 353 1111 L 380 1103 L 521 1030 L 547 1009 L 654 941 L 792 841 L 776 790 L 760 758 Z",
    "M 1159 507 L 1147 473 L 1127 449 L 1110 437 L 1072 421 L 1026 418 L 973 425 L 902 427 L 884 432 L 803 434 L 733 443 L 694 443 L 673 448 L 589 451 L 584 455 L 570 496 L 549 571 L 555 576 L 613 574 L 717 558 L 849 545 L 872 546 L 889 542 L 913 543 L 963 538 L 993 540 L 999 545 L 999 551 L 992 559 L 891 634 L 891 642 L 934 744 L 941 745 L 1022 684 L 1042 673 L 1067 648 L 1084 637 L 1138 590 L 1156 557 Z",
    "M 107 469 L 97 502 L 94 530 L 99 557 L 116 587 L 187 647 L 211 661 L 232 683 L 273 711 L 286 724 L 426 814 L 503 869 L 512 869 L 605 800 L 605 794 L 532 740 L 494 719 L 339 617 L 264 562 L 256 553 L 260 546 L 267 543 L 378 541 L 385 538 L 421 429 L 417 422 L 376 424 L 358 421 L 340 424 L 279 419 L 245 422 L 220 418 L 184 421 L 153 431 L 132 443 Z",
)

# The star's coordinate space (the SVG viewBox is 0 0 1254 1254).
STAR_VIEWBOX = 1254


def star_polygons() -> list[list[tuple[float, float]]]:
    """One point list per path in :data:`_STAR_PATHS`, inside
    STAR_VIEWBOX, so Qt surfaces (the Preferences sidebar logo) FILL
    the same five shapes the toolbar's SVG fills, from the same data.

    The paths are M/L/Z polygons — no curves — which is exactly what
    makes this two-line parse honest rather than a half-written SVG
    reader: anything else in the file would silently drop points, and
    test_top_bar.py pins the per-path vertex counts for that reason."""
    polys: list[list[tuple[float, float]]] = []
    for d in _STAR_PATHS:
        pts: list[tuple[float, float]] = []
        for cmd in d.replace("M", "").replace("Z", "").split("L"):
            parts = cmd.split()
            if len(parts) == 2:
                pts.append((float(parts[0]), float(parts[1])))
        polys.append(pts)
    return polys


def logo_html() -> str:
    """The left-edge logo: inline SVG star. Clicking it opens Klaus's
    own Preferences (``pycmd('klausmate:settings')``, intercepted in
    :func:`_on_js_message`) — Anki's Decks link sits right beside it,
    so the star is better spent on the settings Anki has no entry for."""
    # The SEAT IS INLINE, and that is the point: these declarations
    # used to live in theme.toolbar_css's #klaus-logo block, which the
    # KlausBook design gate switches off — so the star moved every time
    # the design layer did. Carrying its own geometry means one
    # definition serves both modes and the mark cannot shift.
    #
    # inline-flex, not flex: as a flex item (the KlausBook tray) it is
    # blockified to flex anyway, but on a stock toolbar's inline run it
    # must not claim its own line. vertical-align centres it against
    # the text links there, and is simply ignored once it IS a flex
    # item. display:block on the svg drops the inline descender gap.
    #
    # currentColor fallback: --klaus-accent only exists while the
    # design layer injects toolbar_css. On a stock toolbar the star
    # fills in the link's own computed colour — Anki's native
    # foreground — rather than vanishing, since an unresolvable var()
    # makes the fill invalid.
    #
    # FILLED, never stroked (K-270): the impossible star is five solid
    # shapes, and a stroke would outline each arm into a different
    # drawing. The <a> already carries the accessible name, so the svg
    # repeats neither role nor aria-label — the file's own copy of
    # those is for viewing klaus-logo.svg standalone.
    seat = (
        "display: inline-flex; align-items: center;"
        " vertical-align: middle; padding: 0 8px 0 2px; cursor: pointer"
    )
    paths = "".join(
        f'<path d="{d}" fill="var(--klaus-accent, currentColor)"/>'
        for d in _STAR_PATHS
    )
    return (
        f'<a id="klaus-logo" style="{seat}" '
        'href=# onclick="return pycmd(\'klausmate:settings\')" '
        'title="Klaus settings" aria-label="Klaus settings">'
        f'<svg width="26" height="26" viewBox="0 0 {STAR_VIEWBOX} '
        f'{STAR_VIEWBOX}" style="display: block" '
        'xmlns="http://www.w3.org/2000/svg">'
        f"{paths}</svg></a>"
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

        from . import background

        # With the design layer off there is nothing consuming the
        # variable, and an off state should not be evaling into Anki's
        # toolbar at all. A toggle rebuilds the toolbar page outright,
        # so no stale value survives being un-pushed.
        if not background.design_enabled(background.effective_cfg(_config())):
            return

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


def _background_css() -> str:
    """CSS for Anki's own screens (deck list, overview) — the chosen
    wallpaper plus the panel family. The top and bottom toolbars no
    longer call this: they used to paint a blurred copy of the same
    background under themselves, and Pouya asked for that removed
    (2026-08-30) — the bars now always show flat chrome, independent
    of whatever is chosen here."""
    try:
        from . import background

        # effective_cfg: an unsaved Preferences preview wins over stored
        # config, so appearance edits render live before Save.
        # The design gate lives HERE, at the paint funnel, and NOT in
        # background.resolve(): Preferences seeds its widgets through
        # resolve(stored config) and writes that spec back on Save, so
        # a resolve-level gate would show "theme" for a stored image
        # background and Save would silently wipe it.
        if not background.design_enabled(background.effective_cfg(_config())):
            return ""
        spec = background.resolve(background.effective_cfg(_config()))
        url = background.image_url(_addon(), spec["image"])
        return background.main_css(spec, url)
    except Exception as exc:
        print(f"[klausmate] background css failed: {exc}")
        return ""


def _reviewer_background_css() -> str:
    """CSS for the reviewer's card screen — its OWN spec, resolved
    from ``reviewer_background_*`` keys, never the deck screen's
    (Pouya: "this needs to be separate from the background I set for
    the regular main section"). Same gate, same preview seam, same
    shape as :func:`_background_css` — just a different prefix and a
    different builder (no panels: see background.reviewer_css)."""
    try:
        from . import background

        if not background.design_enabled(background.effective_cfg(_config())):
            return ""
        cfg = background.effective_cfg(_config())
        spec = background.resolve(cfg, prefix="reviewer_background")
        url = background.image_url(_addon(), spec["image"])
        return background.reviewer_css(spec, url)
    except Exception as exc:
        print(f"[klausmate] reviewer background css failed: {exc}")
        return ""


def _on_main_webview_content(web_content: Any, context: Any) -> None:
    """Paint custom backgrounds on Anki's own screens.

    The deck list and overview share ONE wallpaper, with the Klaus
    panel family and the studied-line weld on top of it. The reviewer
    gets a SEPARATE, independently configured wallpaper — no panels,
    since a card's background is the user's own notetype, never
    Klaus's to touch (see background.reviewer_css). Deliberately
    excluding the reviewer entirely was the original call here; Pouya
    asked for a study-screen picture of its own instead (2026-08-30).
    """
    try:
        from aqt.deckbrowser import DeckBrowser
        from aqt.overview import Overview
        from aqt.reviewer import Reviewer

        # No congrats screen here on purpose: aqt's deck-description
        # module still exists but the congrats-page class is gone from
        # it in this Anki, and the congrats page itself is a sveltekit
        # page loaded via load_url — it never goes through stdHtml, so
        # this hook never fires for it. An import of that dead symbol
        # lived here for a while, silently failing on every draw.
        if isinstance(context, (DeckBrowser, Overview)):
            css = _background_css()
            if css:
                web_content.head += "<style>" + css + "</style>"
                # Moves the studied-today line into the deck table so it
                # is really inside the panel. No-op on the other screen
                # (nothing there has that id) and in theme mode (empty).
                from . import background

                spec = background.resolve(background.effective_cfg(_config()))
                web_content.body += background.panel_js(spec)
                # Inside `if css` on purpose: css non-empty is the
                # design gate having passed — handles must never
                # appear on a stock screen.
                if background.grad_edit_active():
                    web_content.body += background.gradient_edit_js(
                        spec, "main"
                    )
            return

        # context=self in Reviewer._initWeb (verified against Anki's
        # own source) — the SAME webview showing #qa, not the bottom
        # answer bar (a different context class entirely, owned by
        # window_chrome's chrome-only reviewer sheet).
        if isinstance(context, Reviewer):
            css = _reviewer_background_css()
            if css:
                # The id matters: refresh() previews live edits into
                # this SAME tag by id (reviewer_style_push_js), so the
                # build-time sheet and every later push are one tag —
                # a push can restyle or even empty it, never stack a
                # second sheet under it.
                web_content.head += (
                    '<style id="klaus-reviewer-bg">' + css + "</style>"
                )
                from . import background

                if background.grad_edit_active():
                    web_content.body += background.gradient_edit_js(
                        background.resolve(
                            background.effective_cfg(_config()),
                            prefix="reviewer_background",
                        ),
                        "reviewer",
                    )
    except Exception as exc:
        print(f"[klausmate] background inject failed: {exc}")


def _on_js_message(handled: tuple, message: str, context: Any) -> tuple:
    """Intercept the star logo's pycmd — Anki's toolbar would otherwise
    treat the unknown command as a link and do nothing — and the
    on-screen gradient editor's drag-end messages."""
    if message.startswith("klausmate:bggrad:"):
        try:
            import base64

            from . import background

            payload = message.split(":", 2)[2]
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            # Clamping lives in grad_edit_event — JS is never trusted.
            background.grad_edit_event(data)
        except Exception as exc:
            print(f"[klausmate] gradient edit message failed: {exc}")
        return (True, None)
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


def reviewer_style_push_js(css: str) -> str:
    """JS that installs ``css`` as the reviewer's Klaus background
    sheet, replace-not-stack (window_chrome's Stats pattern): one
    ``<style id="klaus-reviewer-bg">`` — the same tag the
    will_set_content injection writes — is created on demand, has its
    text swapped on every push, and is removed outright when ``css``
    is empty (theme mode / design off), so a discarded preview leaves
    no sheet behind. Pure string builder, aqt-free for tests."""
    return (
        "(function(){"
        "var el=document.getElementById('klaus-reviewer-bg');"
        f"var css={json.dumps(css)};"
        "if(!css){if(el){el.remove();}return;}"
        "if(!el){el=document.createElement('style');"
        "el.id='klaus-reviewer-bg';document.head.appendChild(el);}"
        "el.textContent=css;})();"
    )


def refresh() -> None:
    """Redraw the toolbar and the current screen after a settings change,
    so a new background lands without restarting Anki."""
    try:
        from aqt import mw

        if getattr(mw, "toolbar", None) is not None:
            mw.toolbar.draw()
        # Mid-review, mw.reset() REBUILDS THE STUDY QUEUES (its own
        # comment in aqt/main.py says so) and re-renders the card —
        # and with Preferences non-modal (2026-08-30) a live-preview
        # tick can land while a card is up, so resetting per tick
        # would flip the answer side away under the user. Push the
        # style into the live page instead: same CSS the
        # will_set_content hook injects, same tag, no rebuild. The
        # deck and overview screens keep the reset — their rebuild is
        # what re-runs the injection hooks and the panel_js weld.
        if getattr(mw, "state", None) == "review":
            web = getattr(getattr(mw, "reviewer", None), "web", None)
            if web is not None:
                web.eval(reviewer_style_push_js(_reviewer_background_css()))
                # The reviewer page persists across this path, so the
                # gradient editor must be planted/removed imperatively
                # too: ALWAYS clean, then re-plant while armed — a
                # planted editor holds the colours in its closure, so
                # replacing it (never skipping on "already there") is
                # what keeps a mid-review colour edit from dragging
                # with stale paint. No drag can be in flight during a
                # refresh: refreshes come from dialog edits, and one
                # pointer can't do both.
                from . import background

                editor_js = ""
                if background.grad_edit_active():
                    editor_js = background.gradient_edit_eval_js(
                        background.resolve(
                            background.effective_cfg(_config()),
                            prefix="reviewer_background",
                        ),
                        "reviewer",
                    )
                web.eval(background.GRAD_EDIT_CLEANUP_JS + editor_js)
            return
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

        from . import background

        # The KlausBook design gate. Without it these two sheets were
        # injected UNCONDITIONALLY — the one part of the design layer
        # no config key reached. The _background_css calls below gate
        # themselves through the same check; this return also covers
        # the theme.*_css restyles.
        if not background.design_enabled(
            background.effective_cfg(_config())
        ):
            return

        # The bottom toolbar (deck-browser/overview buttons) gets the
        # SAME chrome as the top, so the window is bracketed by
        # matching bars. Matched by class NAME: these contexts live in
        # aqt.deckbrowser/aqt.overview and importing both here for an
        # isinstance would be needless coupling. The reviewer's answer
        # bar is deliberately excluded — its colours carry scheduling
        # meaning. No wallpaper copy here (removed 2026-08-30, Pouya's
        # call) — the bar is always flat chrome, whatever background
        # mode the deck screen is painted with.
        if type(context).__name__ in (
            "DeckBrowserBottomBar",
            "OverviewBottomBar",
        ):
            from . import theme

            web_content.head += (
                "<style>" + theme.bottombar_css() + "</style>"
            )
            return

        if not isinstance(context, TopToolbar):
            return
        from . import theme

        # No night_mode() snapshot on purpose: the sheet carries BOTH
        # palettes keyed on Anki's own night-mode classes, so the bar
        # follows a theme switch live (Anki toggles those classes with
        # JS and never re-runs this hook). See theme.toolbar_css.
        web_content.head += "<style>" + theme.toolbar_css() + "</style>"
    except Exception as exc:
        print(f"[klausmate] top bar css failed: {exc}")


def _on_profile_open_redraw() -> None:
    """Redraw the top toolbar once the profile's accent theme is loaded.

    Anki draws the toolbar in ``finish_ui_setup()`` — BEFORE any profile
    opens (verified in aqt/main.py: finish_ui_setup runs during app
    setup, profile_did_open fires later inside loadProfile) — so the
    bar's first sheet bakes the DEFAULT accent, and the star launched
    blue on every restart whatever theme was saved (live repro,
    2026-08-30). ``__init__._apply_color_theme`` loads the saved accent
    on profile_did_open; this handler shares that hook and redraws the
    bar so its baked palette catches up. Deferred one tick
    (window_chrome's pattern) so it runs after EVERY other profile-open
    handler regardless of registration order. Ungated on purpose: in
    native mode the redraw just repaints the stock bar once — cheaper
    than a gate that would go stale if a profile flips the design on.
    """
    try:
        from aqt import mw
        from aqt.qt import QTimer

        def _redraw() -> None:
            try:
                if getattr(mw, "toolbar", None) is not None:
                    mw.toolbar.draw()
            except Exception as exc:
                print(f"[klausmate] toolbar accent redraw failed: {exc}")

        QTimer.singleShot(0, _redraw)
    except Exception as exc:
        print(f"[klausmate] toolbar accent redraw schedule failed: {exc}")


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
        # The bar is drawn before any profile opens (finish_ui_setup),
        # so the saved accent has to be redrawn onto it per profile.
        gui_hooks.profile_did_open.append(_on_profile_open_redraw)
    except Exception as exc:
        print(f"[klausmate] top bar setup failed: {exc}")
