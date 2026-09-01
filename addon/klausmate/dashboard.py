"""The Klaus dashboard — Control-Center-style widget editing for the
deck-browser screen.

Pouya's ask, verbatim in spirit: right-click a widget and it says Edit;
everything starts to shake like iOS; each widget grows a little delete
button; a little plus button adds widgets back; and widgets can be
dragged around. So the deck list and the review heatmap become
*widgets* — wrapped, orderable, removable (the deck list excepted: it
is Anki), with the arrangement persisted per profile.

Division of labour: this module owns the REGISTRY, the CONFIG POLICY
and the CHROME'S STYLESHEET; ``web/dashboard.js`` owns the DOM — it
wraps the existing elements into ``.klaus-widget`` divs, applies the
saved order, and runs the whole edit-mode interaction, reporting every
mutation over the bridge (``pycmd("klausmate:dash:<b64 json>")``) for
this module to validate and write. JS payloads are never trusted:
``apply_action`` is the single gate between a bridge message and a
config write, and unknown widget ids can never enter config.

Two config keys, each with one meaning: visibility stays on the
per-widget booleans that already exist (``heatmap_enabled`` — so the
Preferences switch, its live preview and its tests keep working
untouched), and the new ``dashboard_order`` holds only the order.

State that must survive a rebuild: Anki repaints the deck browser with
a full ``stdHtml`` page per refresh, so in-page edit state dies with
every re-render. The module-level ``_EDIT`` flag is what keeps the
jiggle on across the rebuild that follows re-adding a widget — baked
into each render's boot state, cleared on profile switch.

Everything above the "aqt glue" divider is aqt-free and pure, for
``tests/test_dashboard.py``; the DOM work is tested for real by
``tests/dashboard_js_dom_test.js`` (node) since a source pin proves
nothing about DOM manipulation.
"""

from __future__ import annotations

import json
from typing import Any

from . import background, theme

# The registry: (widget id, visibility config key, human label).
# A key of None means MANDATORY — the widget cannot be removed and
# never grows a delete badge (the deck list IS Anki; a dashboard that
# can delete it is a dashboard that can brick the main screen).
# Adding a future widget = one tuple here plus its renderer's own
# visibility bool in config.json.
WIDGETS: tuple = (
    ("decks", None, "Decks"),
    ("heatmap", "heatmap_enabled", "Review Heatmap"),
)


def widget_ids() -> list:
    return [wid for wid, _key, _label in WIDGETS]


def removable_ids() -> list:
    return [wid for wid, key, _label in WIDGETS if key]


def normalize_order(value: Any) -> list:
    """*value* as a safe widget order: registry ids only, no
    duplicates (first occurrence wins), every known id present
    (missing ones appended in registry order). Total — a corrupt
    config value degrades to the default order, never to an error or
    a vanished widget."""
    known = widget_ids()
    order: list = []
    if isinstance(value, list):
        for item in value:
            if item in known and item not in order:
                order.append(item)
    order.extend(wid for wid in known if wid not in order)
    return order


def order_from_cfg(cfg: Any) -> list:
    if not isinstance(cfg, dict):
        return normalize_order(None)
    return normalize_order(cfg.get("dashboard_order"))


def widget_shown(cfg: Any, wid: str) -> bool:
    """Visibility per the widget's own config bool. Mandatory widgets
    are always shown; a corrupt value reads as shown (heatmap.enabled's
    rule — a bad config entry must not silently hide a feature)."""
    for known, key, _label in WIDGETS:
        if known != wid:
            continue
        if key is None:
            return True
        if not isinstance(cfg, dict):
            return True
        value = cfg.get(key, True)
        return value if isinstance(value, bool) else True
    return False


def boot_state(cfg: Any, edit: bool) -> dict:
    """Everything web/dashboard.js needs for one render.

    ``hidden`` is CONFIG-driven, never DOM-driven — a widget that is
    enabled but happened to render empty (a brand-new collection's
    heatmap) must not be offered for "adding". ``labels`` carries every
    removable widget's name so an in-page removal can list it under ＋
    without waiting for a rebuild.
    """
    return {
        "order": order_from_cfg(cfg),
        "edit": bool(edit),
        "removable": removable_ids(),
        "labels": {wid: label for wid, key, label in WIDGETS if key},
        "hidden": [
            {"id": wid, "label": label}
            for wid, key, label in WIDGETS
            if key and not widget_shown(cfg, wid)
        ],
    }


def boot_html(state: dict, script_url: str) -> str:
    """The two-tag boot block: the state blob, then the script that
    consumes it. ``</`` is escaped so no state value can ever terminate
    the script element (same blob discipline as the editor bridge)."""
    blob = json.dumps(state).replace("</", "<\\/")
    return (
        f"<script>window.klausDashState={blob};</script>"
        f'<script src="{script_url}"></script>'
    )


def parse_bridge(payload: str) -> dict | None:
    """b64(JSON) bridge payload -> dict, None on any malformation."""
    import base64

    try:
        data = json.loads(base64.b64decode(payload).decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def apply_action(action: Any) -> dict | None:
    """The whole config-mutation policy, as one pure transform.

    Bridge action -> the config updates it is allowed to make, or None
    for anything else — removing a mandatory widget, an unknown id, a
    malformed order. This is the gate that keeps untrusted JS payloads
    out of config; ``order`` is re-normalised here, never written raw.
    """
    if not isinstance(action, dict):
        return None
    act = action.get("action")
    if act == "order":
        return {"dashboard_order": normalize_order(action.get("order"))}
    if act in ("remove", "add"):
        wid = action.get("id")
        for known, key, _label in WIDGETS:
            if known == wid and key:
                return {key: act == "add"}
        return None
    return None


def _palette_vars(night: bool) -> str:
    """One palette's worth of edit-chrome tokens, from the live theme —
    so the chrome recolours with every accent theme like all other
    Klaus surfaces. The translucent scrims are literal rgba by the
    same precedent as panel_css's glass family."""
    colours = theme.palette(night)
    edge = "rgba(255,255,255,0.12)" if night else "rgba(0,0,0,0.10)"
    chip = "rgba(48,48,48,0.60)" if night else "rgba(255,255,255,0.60)"
    return (
        f" --klaus-dash-surface: {colours['surface']};"
        f" --klaus-dash-text: {colours['text']};"
        f" --klaus-dash-hover: {colours['hover_subtle']};"
        f" --klaus-dash-accent: {colours['blue_bright']};"
        f" --klaus-dash-badge: {colours['grey_light']};"
        f" --klaus-dash-edge: {edge};"
        f" --klaus-dash-chip: {chip};"
    )


def dashboard_css() -> str:
    """Wrapper + edit-mode chrome, both palettes keyed on Anki's own
    ``:root.night-mode`` class (Anki flips it with JS and never re-runs
    the injecting hook — same reason as theme.toolbar_css).

    No width rules anywhere: Anki's global ``*{box-sizing:content-box}``
    is what made a forced width overflow the deck panel before. The
    wrappers are plain blocks under ``<center>`` (Chromium's
    ``text-align:-webkit-center`` centres block children shrink-to-fit),
    so they hug their widget and the corner badge lands on the panel's
    actual corner.

    The jiggle honours Anki's OWN reduced-motion mechanism: Anki ships
    no ``prefers-reduced-motion`` CSS at all — it live-toggles a
    ``reduce-motion`` class on <body> from Python — so the off-switch
    keys on that class, and nothing else would work.
    """
    return (
        f":root {{{_palette_vars(False)} }}"
        f":root.night-mode {{{_palette_vars(True)} }}"
        # position:relative always (not just in edit mode) so the badge
        # and shield anchor without a layout jump when editing starts.
        #
        # width:fit-content + auto margins is the shrink-to-fit, and
        # the CHOICE of sizing function is load-bearing (both wrong
        # options were measured in Chromium):
        #   - a plain block stays full-width (589px around a 411px
        #     table), parking the ⊖ badge at the window edge and letting
        #     the edit shield swallow click-outside-exits beside the
        #     panel;
        #   - display:table shrinks but is sized purely to content, so
        #     the heatmap's max-width:100% stops resolving and the year
        #     grid blew out to 859px instead of engaging its own
        #     horizontal scroller.
        # fit-content + max-width:100% — BOTH are needed, measured:
        # fit-content alone still hit 859px, because it cannot go below
        # min-content and the heatmap's grid (width:max-content) IS its
        # min-content; the max-width cap is what re-engages the
        # heatmap's own horizontal scroller. This is exactly how the
        # .klaus-hm panel already sizes itself (inline-block +
        # max-width:100%), lifted onto the wrapper. Neither is a forced
        # width: the content-box overflow class of bug (width:100% on a
        # padded box) cannot happen with them.
        " .klaus-widget {"
        " position: relative; width: fit-content; max-width: 100%;"
        " margin: 0 auto 1.1em auto;"
        " }"
        # The wrapper must hug what the user can SEE: the edit badge
        # anchors to its corners, and a wrapped child's own margin sits
        # INSIDE the wrapper box — the heatmap's 1.4em margin-top
        # floated the ⊖ into empty page space above the panel (live
        # screenshot 2026-08-30). The child's rhythm is neutralised
        # here and the wrapper's bottom margin carries spacing instead;
        # native mode is untouched, since this sheet only exists with
        # the design on. Child selector outranks heatmap_css's own
        # .klaus-hm margin rule — no !important needed.
        " .klaus-widget > .klaus-hm { margin: 0; }"
        " @keyframes klaus-jiggle {"
        " 0% { transform: rotate(-0.4deg); }"
        " 50% { transform: rotate(0.4deg); }"
        " 100% { transform: rotate(-0.4deg); }"
        " }"
        # Small amplitude on purpose: these are large panels, not app
        # icons — ±0.4° reads as the iOS jiggle without smearing text.
        # Even children run slightly slower and phase-shifted so the
        # panels shake organically rather than in lockstep.
        " body.klaus-dash-editing .klaus-widget {"
        " animation: klaus-jiggle 0.32s ease-in-out infinite;"
        " }"
        " body.klaus-dash-editing .klaus-widget:nth-child(even) {"
        " animation-duration: 0.36s; animation-delay: -0.14s;"
        " }"
        " body.reduce-motion .klaus-widget { animation: none !important; }"
        # The shield is the iOS semantics enforcer: layered over the
        # widget in edit mode so deck clicks, gears, shift-select,
        # Anki's jQuery deck-row drag and the heatmap's day clicks all
        # become unreachable while jiggling. touch-action:none keeps
        # pointer capture honest.
        " .klaus-w-shield {"
        " position: absolute; inset: 0; z-index: 5;"
        " cursor: grab; touch-action: none;"
        " }"
        " .klaus-widget.klaus-w-drag {"
        " animation: none !important; z-index: 7;"
        " filter: drop-shadow(0 12px 24px rgba(0,0,0,0.28));"
        " }"
        " .klaus-w-remove {"
        " position: absolute; top: -8px; left: -8px;"
        " height: 22px; min-width: 22px; padding: 0;"
        " border-radius: 50%; z-index: 6; cursor: pointer;"
        " border: 1px solid var(--klaus-dash-edge);"
        " background: var(--klaus-dash-badge);"
        " color: var(--klaus-dash-text);"
        " font-size: 15px; font-weight: 600; line-height: 20px;"
        " text-align: center;"
        " box-shadow: 0 1px 4px rgba(0,0,0,0.25);"
        f" font-family: {theme.FONT_FAMILY};"
        " }"
        # An invisible halo grows the 22px disc to a ~34px hit target
        # (HIG asks ~28+ for pointer targets) with zero visual change —
        # a pseudo-element is part of its button's hit area.
        " .klaus-w-remove::after {"
        " content: \"\"; position: absolute; inset: -6px;"
        " }"
        # RTL mirrors the badge to the leading corner, like iOS does.
        " [dir=rtl] .klaus-w-remove { left: auto; right: -8px; }"
        # Top-right, the corner opposite pdf_drop's PDF drop square
        # (fixed, bottom-left family, z 50) — and above it.
        " .klaus-dash-bar {"
        " position: fixed; top: 12px; right: 14px; z-index: 60;"
        " display: flex; gap: 8px;"
        f" font-family: {theme.FONT_FAMILY};"
        " }"
        " .klaus-dash-chip {"
        " padding: 6px 14px;"
        " border-radius: var(--border-radius-medium, 12px);"
        " background: var(--klaus-dash-chip);"
        " -webkit-backdrop-filter: blur(10px);"
        " backdrop-filter: blur(10px);"
        " border: 1px solid var(--klaus-dash-edge);"
        " color: var(--klaus-dash-text);"
        " font-size: 12px; font-weight: 500; cursor: pointer;"
        " }"
        " .klaus-dash-chip:hover {"
        " border-color: var(--klaus-dash-accent);"
        " }"
        " #klaus-dash-done {"
        " color: var(--klaus-dash-accent); font-weight: 600;"
        " }"
        # One menu style serves both the right-click menu and the ＋
        # popover — pdfjs_viewer's #ctxmenu geometry, themed here.
        " .klaus-dash-menu {"
        " position: fixed; display: none; z-index: 70;"
        " min-width: 160px;"
        " background: var(--klaus-dash-surface);"
        " border: 1px solid var(--klaus-dash-edge);"
        " border-radius: 8px; padding: 4px;"
        " box-shadow: 0 4px 16px rgba(0,0,0,0.18);"
        " font-size: 13px; color: var(--klaus-dash-text);"
        f" font-family: {theme.FONT_FAMILY};"
        " }"
        " .klaus-dash-menu .mi {"
        " padding: 5px 10px; border-radius: 6px; cursor: pointer;"
        " white-space: nowrap;"
        " }"
        " .klaus-dash-menu .mi:hover {"
        " background: var(--klaus-dash-hover);"
        " }"
    )


# ─────────────────────────────────────────────────────────────────────
# aqt glue — everything below here talks to Anki
# ─────────────────────────────────────────────────────────────────────

# Edit mode, session-transient. Every rebuild of the deck browser (a
# full stdHtml page) boots from this flag, which is how the jiggle
# survives the refresh that follows re-adding a widget. Never
# persisted: reopening Anki always starts calm.
_EDIT: bool = False


def _addon() -> str:
    """The addon's web-export name (its folder under addons21)."""
    try:
        from aqt import mw

        return mw.addonManager.addonFromModule(__name__)
    except Exception:
        return "klausmate"


def _config() -> dict:
    """Stored config through the SAME preview seam as every other
    appearance reader, so an unsaved Preferences preview (heatmap
    switch included) renders on the dashboard before Save."""
    try:
        from aqt import mw

        stored = mw.addonManager.getConfig(__package__) or {}
    except Exception:
        return {}
    return background.effective_cfg(stored)


def write_cfg(updates: dict) -> None:
    """Apply *updates* to STORED config (never to a preview dict).

    Public because it is the package's ONE implementation of the preview
    rule below — heatmap's corner menu writes its settings through here
    rather than growing a second copy of it.

    If a Preferences preview is armed, the preview REPLACES config for
    every effective_cfg reader — so the same updates are patched into a
    re-armed copy of it, or the next preview tick would visually revert
    the dashboard edit the user just watched happen.
    """
    try:
        from aqt import mw

        cfg = mw.addonManager.getConfig(__package__) or {}
        cfg.update(updates)
        mw.addonManager.writeConfig(__package__, cfg)
        if background.preview_active():
            patched = dict(background.effective_cfg({}))
            patched.update(updates)
            background.set_preview(patched)
            print("[klausmate] dashboard: patched the live appearance preview")
    except Exception as exc:
        print(f"[klausmate] dashboard config write failed: {exc}")


def _script_url() -> str:
    """web/dashboard.js's export URL, mtime-versioned — QtWebEngine
    caches /_addons/ assets across restarts, so an unversioned URL can
    serve last week's script against today's Python."""
    import os

    version = 0
    try:
        path = os.path.join(os.path.dirname(__file__), "web", "dashboard.js")
        version = int(os.stat(path).st_mtime)
    except Exception:
        pass
    return f"/_addons/{_addon()}/web/dashboard.js?v={version}"


def _refresh() -> None:
    """Redraw the deck browser — only while the user is still ON it.
    This runs from a deferred singleShot; by then they may have moved
    to the overview or the reviewer, and yanking those screens back
    through a deck-browser repaint would be wrong."""
    try:
        from aqt import mw

        if getattr(mw, "state", "") == "deckBrowser":
            mw.deckBrowser.refresh()
    except Exception as exc:
        print(f"[klausmate] dashboard refresh failed: {exc}")


def _on_webview_will_set_content(web_content: Any, context: Any) -> None:
    global _EDIT
    try:
        from aqt.deckbrowser import DeckBrowser

        if not isinstance(context, DeckBrowser):
            return
        # Widget editing belongs to the KlausBook design layer: with it
        # off, no css and no boot script — no wrap, no jiggle, and the
        # heatmap renders in Anki's stock position. The flag reset
        # matters: toggling the layer off MID-JIGGLE renders a page
        # with no JS to ever send edit-off, so without this a later
        # re-enable would boot the dashboard jiggling unprompted.
        # (Toggled off and on again entirely from another screen, the
        # flag survives — acceptable; it self-heals on any off-render.)
        if not background.design_enabled(_config()):
            _EDIT = False
            return
        web_content.head += "<style>" + dashboard_css() + "</style>"
        # Body-appended, so it parses AFTER background.panel_js (hook
        # registration order: top_bar.setup() runs first) — the weld
        # must finish while `center > table` still matches, before the
        # table is wrapped. That ordering contract is also commented at
        # the __init__.py registration site.
        web_content.body += boot_html(
            boot_state(_config(), _EDIT), _script_url()
        )
    except Exception as exc:
        print(f"[klausmate] dashboard inject failed: {exc}")


def _on_js_message(handled: tuple, message: str, context: Any) -> tuple:
    """Bridge actions from web/dashboard.js. edit-on/off only flip the
    flag (the page already did the visual work); remove/order write
    config with no refresh (the page already hid/moved the widget —
    rebuilding would only jump the scroll); add writes AND refreshes,
    because the widget's HTML does not exist yet."""
    global _EDIT
    if not message.startswith("klausmate:dash:"):
        return handled
    try:
        payload = message.split(":", 2)[2]
    except Exception:
        return (True, None)
    action = parse_bridge(payload)
    if action is None:
        return (True, None)
    act = action.get("action")
    if act == "edit-on":
        _EDIT = True
        return (True, None)
    if act == "edit-off":
        _EDIT = False
        return (True, None)
    updates = apply_action(action)
    if updates is None:
        return (True, None)
    write_cfg(updates)
    if act == "add":
        try:
            from aqt.qt import QTimer

            # Deferred so the webchannel bridge call unwinds before the
            # webview is torn down and rebuilt under it (hygiene per
            # tests/test_bridge_reentrancy).
            QTimer.singleShot(0, _refresh)
        except Exception as exc:
            print(f"[klausmate] dashboard refresh schedule failed: {exc}")
    return (True, None)


def _on_profile_open() -> None:
    """Edit mode must not leak across profiles: profile B would boot
    its deck browser jiggling because profile A was left mid-edit."""
    global _EDIT
    _EDIT = False


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
        gui_hooks.webview_did_receive_js_message.append(_on_js_message)
        gui_hooks.profile_did_open.append(_on_profile_open)
    except Exception as exc:
        print(f"[klausmate] dashboard setup failed: {exc}")
