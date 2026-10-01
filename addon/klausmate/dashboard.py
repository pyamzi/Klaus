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
import re
from typing import Any

from . import background, theme
from . import settings

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


# Other add-ons' blocks on the deck screen (AMBOSS's Qbank card, …) are
# widgets too: the page names each ``x:<its id | .its-class | its tag>``.
# Python never sees the DOM, so it checks only that shape; the order
# keeps them in place and ``dashboard_hidden`` lists the removed ones.
FOREIGN_ID = re.compile(r"^x:[A-Za-z0-9_.:#-]{1,80}$")
MAX_FOREIGN = 40


def is_foreign(wid: Any) -> bool:
    return isinstance(wid, str) and FOREIGN_ID.match(wid) is not None


def hidden_foreign(cfg: Any) -> list:
    value = cfg.get("dashboard_hidden") if isinstance(cfg, dict) else None
    out: list = []
    if isinstance(value, list):
        for wid in value:
            if is_foreign(wid) and wid not in out and len(out) < MAX_FOREIGN:
                out.append(wid)
    return out


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}
_LEAVE = {"table", "br", "script", "style", "link", "meta", "noscript", "template"}


def _foreign_key(tag: str, attrs: dict, taken: set) -> str:
    cls = (attrs.get("class") or "").split()
    raw = attrs.get("id") or ("." + cls[0] if cls else tag)
    key = "x:" + re.sub(r"[^A-Za-z0-9_.:#-]", "-", raw)[:80]
    k, n = key, 2
    while k in taken:
        k, n = f"{key[:76]}-{n}", n + 1
    taken.add(k)
    return k


def wrap_foreign(body: str, hidden: Any = ()) -> str:
    """Wrap every other add-on's block among the deck screen's
    ``<center>`` children in ``<div class="klaus-widget" data-w="x:…">``,
    in the HTML, before the page parses. Never in the page: a custom
    element re-runs its ``connectedCallback`` on every move (AMBOSS's
    Qbank card builds a new React root each time, and drew three cards).
    Anki's table, ``<br>``, the studied line, Klaus's own blocks and
    scripts are left for ``web/dashboard.js``. Tolerant parse (implicit
    closes); anything it can't account for returns *body* unchanged."""
    from html.parser import HTMLParser

    starts = [0]
    for line in body.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))

    class P(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.stack: list = []
            self.level = None  # stack depth of the first <center>
            self.done = False
            self.kids: list = []  # [tag, attrs, start, end]
            self.bad = False

        def _at(self) -> int:
            line, col = self.getpos()
            return starts[line - 1] + col

        def handle_starttag(self, tag, attrs) -> None:
            if self.done:
                return
            start = self._at()
            end = start + len(self.get_starttag_text() or "")
            if self.level is None:
                if tag == "center":
                    self.stack.append(tag)
                    self.level = len(self.stack)
                elif tag not in _VOID:
                    self.stack.append(tag)
                return
            if len(self.stack) == self.level:
                self.kids.append([tag, dict(attrs), start, end if tag in _VOID else None])
            if tag not in _VOID:
                self.stack.append(tag)

        def handle_startendtag(self, tag, attrs) -> None:
            if not self.done and self.level is not None and len(self.stack) == self.level:
                start = self._at()
                self.kids.append([tag, dict(attrs), start, start + len(self.get_starttag_text() or "")])

        def handle_endtag(self, tag) -> None:
            if self.done or tag not in self.stack:
                return
            at = self._at()
            end = body.find(">", at) + 1
            while self.stack:
                top = self.stack.pop()
                if self.level is not None and len(self.stack) == self.level and self.kids \
                        and self.kids[-1][3] is None:
                    if top != tag:
                        self.bad = True  # a direct child closed only implicitly
                    self.kids[-1][3] = end
                if top == tag:
                    break
            if self.level is not None and len(self.stack) < self.level:
                self.done = True

    try:
        p = P()
        p.feed(body)
        p.close()
    except Exception:
        return body
    if not p.done or p.bad or any(k[3] is None for k in p.kids):
        return body
    hide = set(hidden or ())
    taken: set = set()
    out = body
    wraps = []
    for tag, attrs, start, end in p.kids:
        cls = (attrs.get("class") or "").split()
        if tag in _LEAVE or attrs.get("id") == "studiedToday" or any(c.startswith("klaus-") for c in cls):
            continue
        wraps.append((start, end, _foreign_key(tag, attrs, taken)))
    for start, end, key in reversed(wraps):
        style = ' style="display:none"' if key in hide else ""
        out = (out[:start] + f'<div class="klaus-widget" data-w="{key}"{style}>'
               + '<div class="klaus-w-body">' + out[start:end] + "</div></div>" + out[end:])
    return out


# The grid (Pouya, 2026-10-01: "they should fit within square boxes").
# The deck screen is one grid of square cells, GRID_GAP apart and around;
# every widget fills a whole COLUMNS x ROWS box of them and scrolls inside
# it when its content is bigger. Klaus decides each box (Pouya, same day:
# "set up predecided 2x1, 1x2, and whatnot for it, and then I will just
# move it around"), measured once from each widget's rendered content:
# the heatmap is a 159px strip that wants width (4x1); AMBOSS's Qbank card,
# its margins stripped by SHADOW_CSS, is 142px tall at full width and
# taller once its text wraps (own height, at most 4x2);
# Anki's deck table is ~546px wide with its 1rem padding and holds ~12
# decks before it scrolls (4x3). An add-on block not listed here gets
# FOREIGN_SIZE. Nothing is saved: sizes are not a setting.
GRID_CELL = 160
GRID_GAP = 16
# Pouya, 2026-10-01: "I don't want the widget grid to get wider than
# 800 px, keep it aligned center" — 4 columns (4*176+16 = 720px).
GRID_MAX = 800
SIZES = {"decks": "4x3", "heatmap": "4x1", "x:amboss-qbank-widget": "4x2"}
FOREIGN_SIZE = "2x2"
# Widgets with their OWN height (Pouya, 2026-10-01: "let the deck list
# have its own height", after 3 decks still left ~120px of a 2-row box
# empty): the box is as tall as the content, at least one cell, at most
# the rows in SIZES, then it scrolls. Its row of the grid follows it
# (grid rows are minmax(GRID_CELL, auto)); every other widget's body is
# out of flow, so all other rows stay exactly GRID_CELL. Only a
# full-width widget may be listed: a row it set would stretch neighbours.
OWN_HEIGHT = ("decks", "x:amboss-qbank-widget")


# DESIGN.md's primary button, as declarations (8px, 6px 14px, 600, the
# accent theme's blue with white text), forced over an add-on's own.
_PRIMARY_BUTTON = (
    " background: var(--klaus-dash-primary) !important; color: #FFFFFF !important;"
    " border: 1px solid var(--klaus-dash-primary) !important; border-radius: 8px !important;"
    " box-shadow: none !important; font-weight: 600 !important;"
)

# Add-on blocks that draw their card inside an open shadow root, where the
# page's CSS cannot reach: these rules are adopted INTO that root (keyed
# by the host's tag) so the card fills its box like every other widget.
# AMBOSS's Qbank card is a 440px React div with 2em margins around it
# (amboss-anki-qbank-widget.js); that margin is what sat it ~30px lower
# than the heatmap. :host-context() follows Same Look from inside.
SHADOW_CSS = {
    "amboss-component-wrapper": (
        'div:has(> [data-e2e-test-id="qbank-container"])'
        " { width: auto !important; margin: 0 !important;"
        " flex: 1 0 auto; display: flex; flex-direction: column; }"
        ' [data-e2e-test-id="qbank-container"] { flex: 1 0 auto; box-sizing: border-box; }'
        ' :host-context(body.klaus-dash-uniform) [data-e2e-test-id="qbank-container"]'
        " { background: transparent !important; box-shadow: none !important; }"
        ' :host-context(body.klaus-dash-uniform) [data-e2e-test-id="qbank-box"]'
        " { padding: 0 !important; }"
        " :host-context(body.klaus-dash-uniform) button {" + _PRIMARY_BUTTON + " }"
        # Its count field, as a DESIGN.md input: 8px corners, a hairline.
        " :host-context(body.klaus-dash-uniform) input"
        " { border-radius: 8px !important; }"
    ),
}


def size_of(wid: str) -> str:
    return SIZES.get(wid, FOREIGN_SIZE)


def uniform_from_cfg(cfg: Any) -> bool:
    """``dashboard_uniform``: only an explicit True forces the one card
    look (a corrupt value must not restyle other add-ons' blocks)."""
    return isinstance(cfg, dict) and cfg.get("dashboard_uniform") is True


# Pouya, 2026-10-01: "an option to increase and decrease the UI item size",
# then "allow me to choose whatever % I want, and have a nice slider" —
# the dashboard widgets only, a slider in the Edit Widgets bar, 70-150% in
# 5% steps. CSS zoom on the grid, so other add-ons' blocks (AMBOSS's
# shadow-root card) scale too. It ALIGNS WITH Anki's own Preferences >
# User Interface Size (Pouya: "there is a proper setting for this"):
# Anki applies that at startup as QT_SCALE_FACTOR, which scales this
# webview's CSS pixels too, so the dashboard already follows it; this
# percentage is a fine-tune ON TOP (100% = Anki's size), in Anki's 5%
# steps, and the bar names Anki's size (anki_ui_scale) beside it.
SCALE_MIN, SCALE_MAX, SCALE_STEP = 70, 150, 5


def valid_scale(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and SCALE_MIN <= value <= SCALE_MAX and value % SCALE_STEP == 0)


def scale_from_cfg(cfg: Any) -> int:
    """``dashboard_scale`` in percent; anything not valid_scale is 100."""
    value = cfg.get("dashboard_scale") if isinstance(cfg, dict) else None
    return value if valid_scale(value) else 100


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
        foreign = 0
        for item in value:
            if item in order:
                continue
            if item in known:
                order.append(item)
            elif is_foreign(item) and foreign < MAX_FOREIGN:
                order.append(item)
                foreign += 1
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


def anki_ui_scale() -> int:
    """Anki's User Interface Size in percent (100 when unreadable)."""
    try:
        from aqt import mw

        return int(round(float(mw.pm.uiScale()) * 100))
    except Exception:  # noqa: BLE001
        return 100


def boot_state(cfg: Any, edit: bool, ui_scale: int = 100) -> dict:
    """Everything web/dashboard.js needs for one render.

    ``hidden`` is CONFIG-driven, never DOM-driven — a widget that is
    enabled but happened to render empty (a brand-new collection's
    heatmap) must not be offered for "adding". ``labels`` carries every
    removable widget's name so an in-page removal can list it under ＋
    without waiting for a rebuild.
    """
    return {
        "order": order_from_cfg(cfg),
        "hiddenForeign": hidden_foreign(cfg),
        "sizes": dict(SIZES),
        "foreignSize": FOREIGN_SIZE,
        "shadowCss": dict(SHADOW_CSS),
        "ownHeight": list(OWN_HEIGHT),
        "grid": {"cell": GRID_CELL, "gap": GRID_GAP},
        "uniform": uniform_from_cfg(cfg),
        "scale": scale_from_cfg(cfg),
        "scaleRange": [SCALE_MIN, SCALE_MAX, SCALE_STEP],
        "ankiScale": ui_scale if isinstance(ui_scale, int) else 100,
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


def apply_action(action: Any, cfg: Any = None) -> dict | None:
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
    if act == "scale":
        value = action.get("value")
        return {"dashboard_scale": value} if valid_scale(value) else None
    if act == "uniform":
        on = action.get("on")
        return {"dashboard_uniform": on} if isinstance(on, bool) else None
    if act in ("remove", "add"):
        wid = action.get("id")
        if is_foreign(wid):
            hidden = [h for h in hidden_foreign(cfg) if h != wid]
            if act == "remove":
                hidden.append(wid)
            return {"dashboard_hidden": hidden[-MAX_FOREIGN:]}
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
    # Same Look's card (Pouya: "it could have more contrast to the
    # background"). DESIGN.md: depth is tonal layering plus a hairline,
    # never a shadow. Dark `surface` IS Anki's canvas (#2C2C2C), so the
    # card steps a tone up; both modes get a firmer hairline.
    card = "#3A3A3C" if night else colours["surface"]
    card_edge = "rgba(255,255,255,0.16)" if night else "rgba(0,0,0,0.14)"
    return (
        f" --klaus-dash-card: {card};"
        f" --klaus-dash-card-edge: {card_edge};"
        f" --klaus-dash-primary: {colours['blue']};"
        f" --klaus-dash-surface: {colours['surface']};"
        f" --klaus-dash-text: {colours['text']};"
        f" --klaus-dash-hover: {colours['hover_subtle']};"
        f" --klaus-dash-accent: {colours['blue_bright']};"
        f" --klaus-dash-badge: {colours['grey_light']};"
        f" --klaus-dash-edge: {edge};"
        f" --klaus-dash-chip: {chip};"
        f" --klaus-dash-cell: {'rgba(255,255,255,0.04)' if night else 'rgba(0,0,0,0.03)'};"
        f" --klaus-dash-cell-edge: {'rgba(255,255,255,0.22)' if night else 'rgba(0,0,0,0.18)'};"
    )


def dashboard_css() -> str:
    """The widget grid + edit-mode chrome, both palettes keyed on Anki's
    own ``:root.night-mode`` class (Anki flips it with JS and never re-runs
    the injecting hook — same reason as theme.toolbar_css).

    Every widget fills a whole box of square grid cells and scrolls
    inside it (``.klaus-w-body``), so sizes and spacing are the grid's,
    never the content's. ``body.klaus-dash-uniform`` (Same Look) gives
    every box one card and switches each widget's own outer card off.

    The jiggle honours Anki's OWN reduced-motion mechanism: Anki ships
    no ``prefers-reduced-motion`` CSS at all — it live-toggles a
    ``reduce-motion`` class on <body> from Python — so the off-switch
    supports that class as well as the operating system media query.
    """
    return (
        f":root {{{_palette_vars(False)} }}"
        f":root.night-mode {{{_palette_vars(True)} }}"
        # THE GRID (2026-10-01). The deck screen's <center> is one grid
        # of GRID_CELL squares, GRID_GAP apart and padded by GRID_GAP, so
        # spacing is one number everywhere. Widgets still reorder by CSS
        # `order` only, never by moving nodes (an add-on's custom element
        # re-renders on every move); a stray <br> there would take a cell.
        # No `dense` flow: a widget's place on screen must follow its
        # order, or a drag lands somewhere other than where it was aimed.
        " center.klaus-dash-col {"
        f" display: grid; grid-template-columns: repeat(auto-fill, {GRID_CELL}px);"
        f" grid-auto-rows: minmax({GRID_CELL}px, auto); gap: {GRID_GAP}px; padding: {GRID_GAP}px;"
        " justify-content: center;"
        # At most GRID_MAX wide and centred: auto-fill counts columns
        # against the max width (definite), and fit-content then shrinks
        # the box onto exactly those columns.
        f" width: fit-content; max-width: min({GRID_MAX}px, 100%);"
        # The widget size (dashboard_scale, set by the page as
        # --klaus-dash-scale): zoom scales cells, text and add-on blocks
        # alike; the cap stays GRID_MAX on screen and 4 columns at most.
        " zoom: var(--klaus-dash-scale, 1);"
        f" max-width: min({4 * (GRID_CELL + GRID_GAP) + GRID_GAP}px,"
        f" calc({GRID_MAX}px / var(--klaus-dash-scale, 1)), 100%);"
        " box-sizing: border-box; margin: 0 auto; position: relative;"
        " }"
        " center.klaus-dash-col > br { display: none; }"
        # EDIT MODE SHOWS THE GRID (Pouya: "I can't tell where I can latch
        # widgets to"): the page draws every cell of the grid's real tracks
        # (an own-height row is taller than a cell, so a repeating tile
        # would drift) as a faint dashed slot behind the widgets, and
        # while dragging, the box the widget will land in. Both are
        # absolutely positioned: an in-flow node would take a grid cell.
        " .klaus-dash-cell {"
        " position: absolute; pointer-events: none; box-sizing: border-box;"
        " border: 1px dashed var(--klaus-dash-cell-edge); border-radius: 12px;"
        " background: var(--klaus-dash-cell);"
        " }"
        " .klaus-dash-slot {"
        " position: absolute; z-index: 1; pointer-events: none; box-sizing: border-box;"
        " border: 2px solid var(--klaus-dash-accent); border-radius: 12px;"
        " background: color-mix(in srgb, var(--klaus-dash-accent) 12%, transparent);"
        " }"
        # Each widget fills a whole COLUMNS x ROWS box: the page sets the
        # two spans (--kw-cols/--kw-rows) from SIZES, clamped to
        # the columns the window has. position:relative always, so the
        # badge and shield anchor without a jump.
        " .klaus-widget {"
        " position: relative; min-width: 0; min-height: 0;"
        " grid-column: span var(--kw-cols, 2); grid-row: span var(--kw-rows, 1);"
        " }"
        # The box itself: exactly the grid area, content scrolling inside
        # it. Its own element so the ⊖ badge (a child of the widget,
        # outside it) is never clipped by the scroll.
        # border-box explicitly: Anki's global *{box-sizing:content-box}
        # would push the padded uniform card past its cell.
        " .klaus-w-body {"
        " position: absolute; inset: 0; overflow: auto; box-sizing: border-box;"
        " border-radius: 12px; text-align: center;"
        " }"
        # A widget's own card fills its box, so the grid's sizes show even
        # with Same Look off. Only a box's ONE card (the decks box holds
        # the table AND the studied line, and a full-height studied line
        # overflowed it), and never Anki's deck table: a table stretched
        # to a height spreads the extra into its rows.
        " .klaus-w-body > :only-child:not(table) {"
        " box-sizing: border-box; width: 100%; min-height: 100%; margin: 0;"
        " }"
        # Anki's table spans its box's width so its card's edges line up
        # with every other widget's (border-box: Anki pads it 1rem with
        # content-box sizing, and 100% of that overflowed the box).
        # text-align: start, or the body's centring reaches Anki's deck
        # names (their cells set no alignment; a shrink-to-fit table hid
        # that, a full-width one centred "– AnKing" in its column). The
        # count cells keep their own align=end.
        " .klaus-w-body > table { margin: 0 auto; width: 100%; box-sizing: border-box;"
        " text-align: start; }"
        # An OWN_HEIGHT widget's body is in flow, so its row sizes to it:
        # at least a cell, at most its SIZES rows (max-height, set by the
        # page), scrolling past that.
        " .klaus-widget.klaus-w-own > .klaus-w-body {"
        f" position: relative; inset: auto; min-height: {GRID_CELL}px;"
        " display: flex; flex-direction: column;"
        " }"
        # Anki's deck-name column has min-width:15em, which made the table
        # ~546px and scrolled it sideways in a 3-column grid (120% size, a
        # narrow window); the name column already takes the spare width.
        " .klaus-w-body > table .decktd { min-width: 0; }"
        # A shadow-root card's host is inline by default; as a column
        # flexbox that grows to its box, the adopted SHADOW_CSS flexes the
        # card down to fill it (flex, not height:100%: an own-height box
        # has no definite height for a percentage to resolve against).
        + "".join(f" .klaus-w-body > {tag} {{ display: flex; flex-direction: column;"
                  " flex: 1 0 auto; min-height: 100%; }" for tag in SHADOW_CSS)
        + ""
        # SAME LOOK (dashboard_uniform): one card from DESIGN.md on every
        # widget, other add-ons' blocks included, and each widget's own
        # OUTER card switched off so cards never nest. Only the direct
        # child's chrome goes; the colours inside it stay. The card's
        # padding replaces the child's own, so a box that fits its content
        # without Same Look still fits it with (the 4x1 heatmap: 131px of
        # content + 12px + 12px + borders = 157px of a 160px cell).
        " body.klaus-dash-uniform .klaus-w-body {"
        " background: var(--klaus-dash-card);"
        " border: 1px solid var(--klaus-dash-card-edge);"
        " box-shadow: none; padding: 12px;"
        " }"
        " body.klaus-dash-uniform .klaus-w-body > * {"
        " background: transparent !important; border: 0 !important; padding: 0 !important;"
        " box-shadow: none !important; border-radius: 0 !important;"
        " -webkit-backdrop-filter: none !important; backdrop-filter: none !important;"
        " }"
        # SAME LOOK BUTTONS (Pouya: "ensure the buttons also follow the
        # same style ... that they follow the color theme"): an add-on
        # block's buttons become DESIGN.md primary buttons in the accent
        # theme's blue. Klaus's own widgets are themed already; buttons in
        # a shadow root get the same rules from SHADOW_CSS.
        f" body.klaus-dash-uniform .klaus-widget[data-w^='x:'] .klaus-w-body button {{{_PRIMARY_BUTTON} }}"
        # THE SHAKE: iOS's home-screen jiggle, ~±1.5° with a 1px bob on a
        # quarter-second cycle. The page gives each widget its own phase
        # and a slightly different period (animation-delay/-duration
        # inline), so they never move in lockstep.
        " @keyframes klaus-jiggle {"
        " 0% { transform: rotate(-1.5deg); }"
        " 50% { transform: rotate(1.5deg) translateY(-1px); }"
        " 100% { transform: rotate(-1.5deg); }"
        " }"
        " body.klaus-dash-editing .klaus-widget {"
        " animation: klaus-jiggle 0.26s ease-in-out infinite;"
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
        # The widget-size slider: a chip holding a range and its % readout.
        " #klaus-dash-scale { display: inline-flex; align-items: center; gap: 8px; cursor: default; }"
        " #klaus-dash-scale input[type=range] {"
        " width: 110px; margin: 0; accent-color: var(--klaus-dash-accent); cursor: pointer;"
        " }"
        " .klaus-dash-pct { min-width: 3em; text-align: end; font-variant-numeric: tabular-nums; }"
        " #klaus-dash-uniform[aria-pressed=true] {"
        " color: var(--klaus-dash-accent); border-color: var(--klaus-dash-accent);"
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
        # Top-right, above page content (z 60; the menus take 70).
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
        + theme.web_control_css(".klaus-dash-chip", "var(--klaus-dash-accent)")
        + theme.web_control_css(".klaus-w-remove", "var(--klaus-dash-accent)")
        + " @media (prefers-reduced-motion: reduce) {"
          " .klaus-widget { animation: none !important; } }"
        + " @media (prefers-reduced-transparency: reduce), (prefers-contrast: more) {"
          " .klaus-dash-chip { background: var(--klaus-dash-surface);"
          " backdrop-filter: none; -webkit-backdrop-filter: none; } }"
        + " @media (prefers-contrast: more) {"
          " .klaus-dash-menu { border-color: var(--klaus-dash-text); } }"
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
    from . import settings

    stored = settings.read()
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
        from . import settings

        settings.patch(updates)
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
        # Other add-ons' blocks are wrapped HERE, in the HTML, so the page
        # never moves them (see wrap_foreign).
        web_content.body = wrap_foreign(web_content.body, hidden_foreign(_config()))
        # Body-appended, so it parses AFTER background.panel_js (hook
        # registration order: top_bar.setup() runs first) — the weld
        # must finish while `center > table` still matches, before the
        # table is wrapped. That ordering contract is also commented at
        # the __init__.py registration site.
        web_content.body += boot_html(
            boot_state(_config(), _EDIT, anki_ui_scale()), _script_url()
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
    updates = apply_action(action, _config())
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
