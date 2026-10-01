"""Headless tests for klausmate.dashboard — the Control-Center-style
widget editing on the deck-browser screen.

The DOM half (wrapping, edit chrome, drag) is tested for real by
tests/dashboard_js_dom_test.js under node, invoked from here; this file
covers the pure Python layer — the registry, the config policy, the
boot state, the stylesheet — and pins the aqt glue's shape.
"""
import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section  # noqa: E402

install()
dash = importlib.import_module("klausmate.dashboard")
theme = importlib.import_module("klausmate.theme")


# ------------------------------------------------------------- registry
section("the widget registry")

check("decks is mandatory — no visibility key, so no delete badge and "
      "no way to remove Anki's own deck list",
      dict((w, k) for w, k, _l in dash.WIDGETS)["decks"] is None)
check("every removable widget's visibility key is a real config key, "
      "so ⊖/＋ writes land on something the defaults define",
      all(f'"{key}"' in open("klausmate/config.json").read()
          for _w, key, _l in dash.WIDGETS if key))
check("today's registry is exactly decks + heatmap",
      dash.widget_ids() == ["decks", "heatmap"]
      and dash.removable_ids() == ["heatmap"])
check("every widget carries a human label for the ＋ menu",
      all(label for _w, _k, label in dash.WIDGETS))

section("order normalisation")
check("a non-list degrades to registry order",
      dash.normalize_order(None) == ["decks", "heatmap"]
      and dash.normalize_order("garbage") == ["decks", "heatmap"])
check("unknown ids are dropped — a corrupt entry can never enter config",
      dash.normalize_order(["evil", "heatmap", "decks"])
      == ["heatmap", "decks"])
check("duplicates keep the first occurrence",
      dash.normalize_order(["heatmap", "decks", "heatmap"])
      == ["heatmap", "decks"])
check("missing known ids are appended, so a widget can never be LOST "
      "through the order key (visibility is the bools' job)",
      dash.normalize_order(["heatmap"]) == ["heatmap", "decks"])
check("a saved custom order round-trips untouched",
      dash.normalize_order(["heatmap", "decks"]) == ["heatmap", "decks"])
check("order_from_cfg survives a non-dict",
      dash.order_from_cfg(None) == ["decks", "heatmap"])

section("visibility")
check("mandatory widgets are always shown",
      dash.widget_shown({}, "decks")
      and dash.widget_shown({"heatmap_enabled": False}, "decks"))
check("a removable widget follows its own bool",
      dash.widget_shown({"heatmap_enabled": True}, "heatmap") is True
      and dash.widget_shown({"heatmap_enabled": False}, "heatmap") is False)
check("a corrupt value reads as SHOWN (heatmap.enabled's rule — bad "
      "config must not silently hide a feature)",
      dash.widget_shown({"heatmap_enabled": "no"}, "heatmap") is True)
# The corrupt-VALUE branch above was pinned; the corrupt-CONFIG branch
# beside it was not, and inverting it survived the K-139 mutation audit
# (finding 4). Same documented rule, one step earlier: config that is not
# a dict at all is still not permission to hide a feature.
check("a config that is not a dict at all reads as SHOWN too — the same "
      "rule one step earlier, and the branch a whole unreadable config "
      "falls into",
      dash.widget_shown(None, "heatmap") is True
      and dash.widget_shown("garbage", "heatmap") is True
      and dash.widget_shown([("heatmap_enabled", False)], "heatmap") is True)
check("an unknown id is not shown", dash.widget_shown({}, "evil") is False)


# ------------------------------------------------------- mutation policy
section("apply_action — the gate between the bridge and config")

check("order is re-normalised, never written raw",
      dash.apply_action({"action": "order",
                         "order": ["evil", "heatmap", "heatmap"]})
      == {"dashboard_order": ["heatmap", "decks"]})
check("remove/add write ONLY the widget's own bool",
      dash.apply_action({"action": "remove", "id": "heatmap"})
      == {"heatmap_enabled": False}
      and dash.apply_action({"action": "add", "id": "heatmap"})
      == {"heatmap_enabled": True})
check("removing the mandatory widget is refused",
      dash.apply_action({"action": "remove", "id": "decks"}) is None)
check("unknown ids and junk are refused",
      dash.apply_action({"action": "remove", "id": "evil"}) is None
      and dash.apply_action({"action": "explode"}) is None
      and dash.apply_action("not a dict") is None
      and dash.apply_action(None) is None)

section("other add-ons' blocks are widgets too (AMBOSS, AnkiHub, …)")
# Pouya: "Anytime there's a new thing on the screen, could you allow that
# to work within my widgets framework?" The page names each foreign block
# x:<its id, or .its-class, or its tag>; Python only ever checks the shape.
_AMB = "x:amboss-qbank-widget"
check("a foreign id keeps its place in the saved order",
      dash.normalize_order([_AMB, "heatmap", "decks", "x:.ankihub-thing"])
      == [_AMB, "heatmap", "decks", "x:.ankihub-thing"])
check("...but only in the page's own shape: markup, overlong ids and junk are dropped",
      dash.normalize_order(["x:<script>", "x:" + "a" * 200, "x:", 5, "amboss"]) == ["decks", "heatmap"])
check("removing one records it in dashboard_hidden",
      dash.apply_action({"action": "remove", "id": _AMB}, {}) == {"dashboard_hidden": [_AMB]})
check("...once, however often",
      dash.apply_action({"action": "remove", "id": _AMB}, {"dashboard_hidden": [_AMB]})
      == {"dashboard_hidden": [_AMB]})
check("adding it back takes it out again",
      dash.apply_action({"action": "add", "id": _AMB}, {"dashboard_hidden": [_AMB, "x:b"]})
      == {"dashboard_hidden": ["x:b"]})
check("a malformed foreign id is refused",
      dash.apply_action({"action": "remove", "id": "x:<b>"}, {}) is None)
check("the page learns which foreign blocks are hidden, junk dropped",
      dash.boot_state({"dashboard_hidden": [_AMB, "x:<b>", 3]}, False)["hiddenForeign"] == [_AMB]
      and dash.boot_state({"dashboard_hidden": "junk"}, False)["hiddenForeign"] == [])

section("wrap_foreign: add-on blocks are wrapped BEFORE the page parses")
# AMBOSS's <amboss-component-wrapper> builds a new React root on every
# connect, so moving it after parse drew the card three times. The
# wrapper is written into the HTML instead; the page never moves it.
_BODY = (
    "<center>\n<table cellspacing=0><tr class='deck'><td>A<td>B</tr></table>\n<br>\n"
    "<div id=studiedToday>Studied 7 cards</div>"
    '<div class="klaus-hm">grid</div>'
    '<script src="/_addons/x/w.js"></script>\n'
    '<amboss-component-wrapper data-widget-state="{&quot;a&quot;: 1}" id="amboss-qbank-widget">'
    "</amboss-component-wrapper>\n"
    '<div class="ankihub-thing"><p>unclosed<br></div>'
    '<div class="ankihub-thing">second</div>'
    "</center><script>after()</script>"
)
_W = dash.wrap_foreign(_BODY)
check("the AMBOSS element is wrapped, whole and byte-for-byte",
      '<div class="klaus-widget" data-w="x:amboss-qbank-widget"><div class="klaus-w-body">'
      '<amboss-component-wrapper data-widget-state="{&quot;a&quot;: 1}" id="amboss-qbank-widget">'
      "</amboss-component-wrapper></div></div>" in _W, _W)
check("a class-keyed block is wrapped, a second one gets its own key",
      '<div class="klaus-widget" data-w="x:.ankihub-thing"><div class="klaus-w-body">'
      '<div class="ankihub-thing"><p>unclosed<br></div></div></div>' in _W
      and 'data-w="x:.ankihub-thing-2"><div class="klaus-w-body"><div class="ankihub-thing">second</div></div></div>' in _W, _W)
check("Anki's table, <br>, studied line, the heatmap and scripts are left for the page",
      _W.count('class="klaus-widget"') == 3 and "<script src=\"/_addons/x/w.js\"></script>" in _W
      and '<div id=studiedToday>Studied 7 cards</div><div class="klaus-hm">grid</div>' in _W)
check("nothing outside the <center> changes", _W.endswith("</center><script>after()</script>"))
check("a removed block is written hidden, so it never flashes",
      'data-w="x:amboss-qbank-widget" style="display:none">' in dash.wrap_foreign(_BODY, ["x:amboss-qbank-widget"]))
check("unparseable or center-less html is returned untouched",
      dash.wrap_foreign("<center><div class=a>never closed</center>") == "<center><div class=a>never closed</center>"
      and dash.wrap_foreign("<div>no center</div>") == "<div>no center</div>")

_DSRC = open("klausmate/dashboard.py", encoding="utf-8").read()
check("the deck screen's HTML goes through wrap_foreign before the boot script is added",
      "web_content.body = wrap_foreign(web_content.body, hidden_foreign(_config()))" in _DSRC
      and _DSRC.index("wrap_foreign(web_content.body") < _DSRC.index("web_content.body += boot_html("))
check("the page's reorder is CSS order only: no widget is ever re-inserted by drag or order",
      "insertBefore(w, neighbour" not in open("klausmate/web/dashboard.js").read()
      and "center.klaus-dash-col" in dash.dashboard_css())

section("bridge payload parsing")
import base64  # noqa: E402
_good = base64.b64encode(json.dumps({"action": "edit-on"}).encode()).decode()
check("a well-formed payload decodes", dash.parse_bridge(_good)
      == {"action": "edit-on"})
check("garbage decodes to None, never an exception into Anki",
      dash.parse_bridge("!!!") is None
      and dash.parse_bridge("") is None
      and dash.parse_bridge(base64.b64encode(b"[1,2]").decode()) is None)


# ------------------------------------------------------------ boot state
section("boot state and boot html")

# Read BEFORE the bridge section below flips it: this is the module's boot
# value, and the audit (finding 3) flipped `_EDIT: bool = False` to True
# with nothing noticing — every deck browser would boot into jiggle mode.
# The flag's RESET paths are source-pinned; its default was not pinned at
# all, and "never persisted, reopening Anki always starts calm" is only
# true if the module-level default is False.
check("edit mode boots OFF — a fresh session must never open jiggling",
      dash._EDIT is False)

_state = dash.boot_state({"heatmap_enabled": False,
                          "dashboard_order": ["heatmap", "decks"]}, True)
check("order, edit flag, removables and labels all ship",
      _state["order"] == ["heatmap", "decks"] and _state["edit"] is True
      and _state["removable"] == ["heatmap"]
      and _state["labels"] == {"heatmap": "Review Heatmap"})
check("hidden is CONFIG-driven — the disabled heatmap is offered "
      "under ＋ even though no DOM was consulted",
      _state["hidden"] == [{"id": "heatmap", "label": "Review Heatmap"}])
check("nothing hidden when everything is enabled",
      dash.boot_state({}, False)["hidden"] == [])

_html = dash.boot_html({"order": [], "note": "</script><b>"}, "/x/dashboard.js?v=5")
check("the state blob cannot terminate its own script element",
      "</script><b>" not in _html.split('<script src')[0]
      and "<\\/script>" in _html)
check("the script src lands verbatim, version and all",
      '<script src="/x/dashboard.js?v=5"></script>' in _html)


# ------------------------------------------------------------ stylesheet
section("stylesheet")

_css = dash.dashboard_css()
check("both palettes ship, keyed on Anki's own night-mode class",
      ":root {" in _css and ":root.night-mode {" in _css)
# K-142 (found by scripts/mutation_audit.py, confirmed by hand): the
# check above only proves the two SELECTORS exist. Swapping the palette
# blocks — light mode painting the DARK palette — left the whole suite
# green, and so did making night identical to day. The invariant is
# that each block carries ITS OWN palette, so pin the values.
_day_blk = re.search(r":root \{(.*?)\}", _css, re.S)
_night_blk = re.search(r":root\.night-mode \{(.*?)\}", _css, re.S)
check("the two palette blocks are not identical — a night mode that "
      "merely repeats day mode is the bug this pin exists to prevent",
      _day_blk is not None and _night_blk is not None
      and _day_blk.group(1) != _night_blk.group(1))
check("...and each block carries its OWN palette's ink, so the two "
      "cannot be swapped and still pass",
      theme.palette(False)["text"].lower() in _day_blk.group(1).lower()
      and theme.palette(True)["text"].lower() in _night_blk.group(1).lower()
      and theme.palette(True)["text"].lower()
      not in _day_blk.group(1).lower())
check("dashboard_css takes no `night` argument (Anki flips the class "
      "with JS and never re-runs the injecting hook)",
      dash.dashboard_css.__code__.co_argcount == 0)
_ocean = dash.dashboard_css()
theme.set_active_theme("claude")
check("the chrome recolours with the accent theme",
      dash.dashboard_css() != _ocean)
theme.set_active_theme("ocean")
check("the jiggle exists and honours Anki's reduce-motion mechanism — "
      "Anki ships NO prefers-reduced-motion CSS; it live-toggles "
      "body.reduce-motion from Python, so keying on that class is the "
      "only off-switch that works",
      "@keyframes klaus-jiggle" in _css
      and "body.klaus-dash-editing .klaus-widget" in _css
      and "body.reduce-motion .klaus-widget { animation: none !important; }"
      in _css)
_wrapper_rule = _css.split(".klaus-widget {", 1)[1].split("}")[0]
_grid_rule = _css.split("center.klaus-dash-col {", 1)[1].split("}")[0]
check("the deck screen is ONE grid of square cells, one gap everywhere "
      "(between widgets and around them)",
      f"grid-template-columns: repeat(auto-fill, {dash.GRID_CELL}px)" in _grid_rule
      and f"grid-auto-rows: minmax({dash.GRID_CELL}px, auto)" in _grid_rule
      and f"gap: {dash.GRID_GAP}px" in _grid_rule and f"padding: {dash.GRID_GAP}px" in _grid_rule
      and "dense" not in _grid_rule, _grid_rule)
check("a widget fills a whole COLUMNS x ROWS box from the spans the page sets, "
      "and no width or height of its own",
      "grid-column: span var(--kw-cols" in _wrapper_rule and "grid-row: span var(--kw-rows" in _wrapper_rule
      and not re.search(r"(?<![-a-z])(width|height):", _wrapper_rule), _wrapper_rule)
_body_rule = _css.split(".klaus-w-body {", 1)[1].split("}")[0]
check("content scrolls inside its box, which is exactly the grid area "
      "(border-box: Anki's global content-box would push a padded card out)",
      "inset: 0" in _body_rule and "overflow: auto" in _body_rule and "box-sizing: border-box" in _body_rule)
check("Same Look: one card on every box, and each widget's own outer card off "
      "so cards never nest; colours inside are left alone",
      "body.klaus-dash-uniform .klaus-w-body {" in _css
      and "background: var(--klaus-dash-card)" in _css
      and "body.klaus-dash-uniform .klaus-w-body > * {" in _css
      and "color" not in _css.split("body.klaus-dash-uniform .klaus-w-body > * {")[1].split("}")[0])
_jig = _css.split("@keyframes klaus-jiggle {", 1)[1].split("} }", 1)[0]
check("the shake is iOS-strength: ±1.5° with a small bob",
      "rotate(-1.5deg)" in _jig and "rotate(1.5deg)" in _jig and "translateY(-1px)" in _jig, _jig)
check("edit chrome floats ABOVE pdf_drop's PDF drop square "
      "(fixed, z-index 50): bar 60, menus 70",
      "z-index: 60" in _css and "z-index: 70" in _css)
check("the shield outranks page content but sits under the badge",
      "z-index: 5;" in _css and "z-index: 6;" in _css)
check("the ⊖ badge's hit target outgrows its 22px disc via an "
      "invisible halo (HIG asks ~28px+ for pointer targets) — a "
      "pseudo-element is part of the button's hit area",
      ".klaus-w-remove::after {" in _css
      and "inset: -6px" in _css.split(".klaus-w-remove::after {")[1])
check("the badge mirrors to the leading corner in RTL",
      "[dir=rtl] .klaus-w-remove { left: auto; right: -8px; }" in _css)
check("a box's one card fills it, so sizes show with Same Look off; never Anki's "
      "table (its rows would stretch) and never a second element (it overflowed the decks box)",
      ".klaus-w-body > :only-child:not(table) {" in _css
      and "min-height: 100%" in _css.split(".klaus-w-body > :only-child:not(table) {")[1].split("}")[0])
check("the grid is at most GRID_MAX (800px) wide, centred, and shrinks onto its "
      "columns so the cell tiles line up with the tracks",
      dash.GRID_MAX == 800 and "width: fit-content; max-width: min(800px, 100%);" in _css
      and "margin: 0 auto;" in _css.split("center.klaus-dash-col {")[1].split("}")[0])
check("…and 4 columns (720px with padding) fit under it, so every 4-wide box does",
      4 * (dash.GRID_CELL + dash.GRID_GAP) + dash.GRID_GAP <= dash.GRID_MAX
      < 5 * (dash.GRID_CELL + dash.GRID_GAP) + dash.GRID_GAP)
check("edit mode's cell slots are drawn by the page, out of flow, in both palettes",
      ".klaus-dash-cell {" in _css
      and "position: absolute;" in _css.split(".klaus-dash-cell {")[1].split("}")[0]
      and _css.count("--klaus-dash-cell-edge:") == 2)
check("grid rows are at least a cell and grow only for an in-flow (own-height) body",
      "grid-auto-rows: minmax(160px, auto);" in _css
      and "position: relative; inset: auto; min-height: 160px;"
      in _css.split(".klaus-widget.klaus-w-own > .klaus-w-body {")[1].split("}")[0])
check("the landing outline is out of flow (an in-flow node would take a grid cell)",
      "position: absolute;" in _css.split(".klaus-dash-slot {")[1].split("}")[0]
      and "pointer-events: none" in _css.split(".klaus-dash-slot {")[1].split("}")[0])
check("Anki's table spans its box with border-box sizing (its 1rem padding overflowed at 100%), "
      "deck names aligned to the start, not centred by the box",
      ".klaus-w-body > table { margin: 0 auto; width: 100%; box-sizing: border-box;"
      " text-align: start; }" in _css)
check("a shadow-root card's host is a growing column flexbox so its adopted CSS can fill "
      "the box, fixed or own-height (no percentage height to resolve)",
      ".klaus-w-body > amboss-component-wrapper { display: flex; flex-direction: column;"
      " flex: 1 0 auto; min-height: 100%; }" in _css
      and "flex: 1 0 auto" in dash.SHADOW_CSS["amboss-component-wrapper"])
check("AMBOSS's card loses its 2em margins and 440px width inside its root",
      "margin: 0 !important" in dash.SHADOW_CSS["amboss-component-wrapper"]
      and "width: auto !important" in dash.SHADOW_CSS["amboss-component-wrapper"]
      and dash.boot_state({}, False)["shadowCss"] == dash.SHADOW_CSS)
check("the deck list and AMBOSS have their own height (3 decks left a 2-row box a third "
      "empty; AMBOSS's text wraps taller in 3 columns)",
      dash.OWN_HEIGHT == ("decks", "heatmap", "x:amboss-qbank-widget")
      and dash.boot_state({}, False)["ownHeight"] == list(dash.OWN_HEIGHT))
check("…and every own-height widget is 4 wide, so it is always full width and its row "
      "stretches nobody",
      all(dash.size_of(w).startswith("4x") for w in dash.OWN_HEIGHT))
check("Anki's 15em deck-name minimum is lifted, or the table scrolls sideways in 3 columns",
      ".klaus-w-body > table .decktd { min-width: 0; }" in _css)
check("Same Look's card steps up from the canvas, with a firmer hairline and no shadow "
      "(DESIGN.md: depth is tone plus a hairline, never a shadow)",
      "--klaus-dash-card: #3A3A3C;" in _css  # theme.palette(True)["card_raised"] and "--klaus-dash-card-edge: rgba(0,0,0,0.14);" in _css
      and "box-shadow: none; padding: 12px;" in _css and "--klaus-dash-lift" not in _css)
check("Same Look turns add-on blocks' buttons into DESIGN.md primary buttons in the accent "
      "theme's blue — light DOM and AMBOSS's shadow root alike",
      "body.klaus-dash-uniform .klaus-widget[data-w^='x:'] .klaus-w-body button {" in _css
      and "var(--klaus-dash-primary)" in dash._PRIMARY_BUTTON and "border-radius: 8px" in dash._PRIMARY_BUTTON
      and ":host-context(body.klaus-dash-uniform) button {" + dash._PRIMARY_BUTTON
      in dash.SHADOW_CSS["amboss-component-wrapper"]
      and _css.count("--klaus-dash-primary:") == 2)
check("the widget size zooms the grid, keeps it at most 800px ON SCREEN and 4 columns",
      "zoom: var(--klaus-dash-scale, 1);" in _css
      and "max-width: min(720px, calc(800px / var(--klaus-dash-scale, 1)), 100%);" in _css)
check("widget size: 70-150% in Anki's 5% steps; anything else reads as 100",
      [dash.scale_from_cfg({"dashboard_scale": v}) for v in (70, 115, 150, 65, 155, 112, True, "110", None)]
      == [70, 115, 150, 100, 100, 100, 100, 100, 100] and dash.scale_from_cfg(None) == 100)
check("…the slider's value is validated the same way before it is saved",
      dash.apply_action({"action": "scale", "value": 125}, {}) == {"dashboard_scale": 125}
      and dash.apply_action({"action": "scale", "value": 127}, {}) is None
      and dash.apply_action({"action": "scale", "value": True}, {}) is None
      and dash.apply_action({"action": "scale", "value": 500}, {}) is None)
_bs2 = dash.boot_state({"dashboard_scale": 110}, True, 125)
check("…and the page gets the size, its range and Anki's own interface size (the slider sits on top of it)",
      _bs2["scale"] == 110 and _bs2["scaleRange"] == [70, 150, 5] and _bs2["ankiScale"] == 125
      and dash.boot_state({}, False)["ankiScale"] == 100)
check("a popover inside a widget (the heatmap's settings menu) is let out of the scroll box "
      "while open and its widget rises above the next one",
      ".klaus-widget:has(details[open]) { z-index: 8; }" in _css
      and ".klaus-widget:has(details[open]) > .klaus-w-body { overflow: visible; }" in _css)
check("an own-height widget's one card grows to its box, never Anki's table",
      ".klaus-widget.klaus-w-own > .klaus-w-body > :only-child:not(table) { flex: 1 0 auto; }" in _css)
check("keyboard focus shows on a widget's shield and on menu items",
      ".klaus-w-shield:focus-visible {" in _css and ".klaus-dash-menu .mi:focus-visible {" in _css)
check("Same Look's colours come from the theme palette, not typed-in hex",
      "#3A3A3C" not in inspect.getsource(dash._palette_vars)
      and "#FFFFFF" not in dash._PRIMARY_BUTTON
      and "var(--klaus-dash-on-accent)" in dash._PRIMARY_BUTTON)
check("no size chip: sizes are Klaus's, not the user's",
      ".klaus-w-size" not in _css)
check("Same Look's card padding replaces the child's, so the 4x1 heatmap "
      "(131px of content) still fits its 160px row",
      "padding: 12px;" in _css.split("body.klaus-dash-uniform .klaus-w-body {")[1].split("}")[0]
      and "padding: 0 !important" in _css.split("body.klaus-dash-uniform .klaus-w-body > * {")[1].split("}")[0])
check("a dragged widget stops jiggling — a CSS animation would "
      "otherwise override the inline drag transform outright",
      "animation: none !important; z-index: 7;" in _css)

section("the wiring (source pins)")
_SRC = open("klausmate/dashboard.py").read()
_CODE = code_only(_SRC)
_gate_slice = _SRC.split("def _on_webview_will_set_content")[1].split(
    "def _on_js_message")[0]
check("the whole dashboard is behind the KlausBook design gate — "
      "widget editing IS design layer, so native mode gets Anki's "
      "stock deck screen with the heatmap in its stock position",
      "design_enabled" in _gate_slice)
check("the off-branch clears the edit flag: toggling the layer off "
      "mid-jiggle leaves no JS to ever send edit-off, and a stale "
      "flag would boot a later re-enable jiggling unprompted",
      "_EDIT = False" in _gate_slice)
check("setup registers content, js-message and profile-open hooks",
      "webview_will_set_content.append(_on_webview_will_set_content)"
      in _CODE
      and "webview_did_receive_js_message.append(_on_js_message)" in _CODE
      and "profile_did_open.append(_on_profile_open)" in _CODE)
check("the add-refresh is deferred, never run inside the webchannel "
      "handler", "QTimer.singleShot(0, _refresh)" in _CODE)
check("_refresh only repaints while the user is still ON the deck "
      "browser — a deferred call may land after they moved on",
      'getattr(mw, "state", "") == "deckBrowser"' in _SRC)
check("the script URL is mtime-versioned (QtWebEngine caches /_addons/ "
      "assets across restarts)", "?v={version}" in _SRC)
check("edit mode is cleared on profile switch",
      "_EDIT = False" in _CODE.split("def _on_profile_open")[1])
check("config writes patch an armed Preferences preview, or the next "
      "preview tick would revert the edit the user just watched",
      "background.preview_active()" in _CODE
      and "background.set_preview(patched)" in _CODE)

section("bridge handler behaviour (stubbed)")
_calls = []
dash.write_cfg = lambda u: _calls.append(u)  # glue stubbed; policy real
check("a foreign message passes through untouched",
      dash._on_js_message(("sentinel",), "klausmate:settings", None)
      == ("sentinel",))
_b = lambda obj: "klausmate:dash:" + base64.b64encode(
    json.dumps(obj).encode()).decode()
_r_on = dash._on_js_message((False, None), _b({"action": "edit-on"}), None)
check("edit-on arms the session flag", dash._EDIT is True)
_r_off = dash._on_js_message((False, None), _b({"action": "edit-off"}), None)
check("edit-off clears it", dash._EDIT is False)
_r_rm = dash._on_js_message(
    (False, None), _b({"action": "remove", "id": "heatmap"}), None)
check("remove writes the widget's bool through the policy gate",
      _calls == [{"heatmap_enabled": False}])
_r_mand = dash._on_js_message(
    (False, None), _b({"action": "remove", "id": "decks"}), None)
check("removing the mandatory widget writes NOTHING",
      _calls == [{"heatmap_enabled": False}])
check("malformed payloads are swallowed",
      dash._on_js_message((False, None), "klausmate:dash:!!!", None)
      == (True, None))

# The "we handled this" half of the bridge contract. Every RETURN out of a
# dash: message must be (True, None): returning False re-opens the message
# to the rest of Anki's hook chain, which then sees an unknown pycmd. The
# K-139 audit flipped five of this handler's six such returns to False with
# nothing noticing (only the malformed-payload one above was pinned). Four
# of those five are reachable and are pinned here; the fifth guards an
# IndexError on message.split(":", 2)[2], which the startswith() check
# above it makes impossible — that one is dead defensive code, and stays a
# survivor by construction rather than by omission.
check("EVERY dash: outcome reports the message handled — armed, cleared, "
      "refused by the policy gate, and written — so a klausmate: pycmd "
      "never falls through to the rest of Anki's hook chain",
      _r_on == (True, None) and _r_off == (True, None)
      and _r_mand == (True, None) and _r_rm == (True, None))
check("a foreign message is the ONE case that keeps travelling, and it "
      "travels unchanged",
      dash._on_js_message(("passing", "through"), "klausmate:lecture", None)
      == ("passing", "through"))


# ----------------------------------------------- the DOM half, for real
section("web/dashboard.js against a fake Anki DOM (node)")
# The dashboard's DOM work — wrapping, ordering, the whole edit mode —
# cannot be proven by source pins. node is not required to develop this
# addon, so when missing this is reported as SKIPPED rather than
# counted as a pass — an unverified behaviour must never look verified.
if shutil.which("node"):
    _here = os.path.dirname(os.path.abspath(__file__))
    _proc = subprocess.run(
        ["node", os.path.join(_here, "dashboard_js_dom_test.js"),
         os.path.join(_here, "..", "klausmate", "web", "dashboard.js")],
        capture_output=True, text=True)
    check("wraps both widgets, applies the saved order, survives theme "
          "mode and foreign addon content, is idempotent, and the whole "
          "edit mode (menu, shields, badge, ＋, Done, Esc) behaves",
          _proc.returncode == 0,
          (_proc.stdout + _proc.stderr).strip().replace("\n", " | "))
else:
    print("  SKIP  dashboard.js DOM behaviour (node not installed) — NOT "
          "counted as a pass")

section("sizes and Same Look: config policy")
check("Klaus fixes each widget's box from its measured content; unknown add-on blocks share one",
      dash.size_of("decks") == "4x3" and dash.size_of("heatmap") == "4x2"
      and dash.size_of("x:amboss-qbank-widget") == "4x2"
      and dash.size_of("x:.ankihub-thing") == dash.FOREIGN_SIZE == "2x2")
check("every size is a real COLUMNS x ROWS box no wider than 4 columns",
      all(re.fullmatch(r"[1-4]x[1-4]", v) for v in list(dash.SIZES.values()) + [dash.FOREIGN_SIZE]))
check("a size pick from an old page writes nothing (sizes are not a setting)",
      dash.apply_action({"action": "size", "id": "heatmap", "size": "3x2"}, {}) is None)
check("Same Look writes a strict bool, and only for a strict bool",
      dash.apply_action({"action": "uniform", "on": True}, {}) == {"dashboard_uniform": True}
      and dash.apply_action({"action": "uniform", "on": False}, {}) == {"dashboard_uniform": False}
      and dash.apply_action({"action": "uniform", "on": "yes"}, {}) is None)
check("only an explicit True turns Same Look on (a corrupt value must not restyle add-ons)",
      dash.uniform_from_cfg({"dashboard_uniform": True}) is True
      and dash.uniform_from_cfg({"dashboard_uniform": 1}) is False and dash.uniform_from_cfg({}) is False)
_bs = dash.boot_state({"dashboard_sizes": {"heatmap": "1x2"}, "dashboard_uniform": True}, False)
check("the page gets Klaus's sizes (a stale saved dashboard_sizes is ignored), the grid and Same Look",
      _bs["sizes"] == dash.SIZES and _bs["foreignSize"] == "2x2"
      and "sizeChoices" not in _bs and "defaultSizes" not in _bs
      and _bs["grid"] == {"cell": dash.GRID_CELL, "gap": dash.GRID_GAP} and _bs["uniform"] is True)

raise SystemExit(report())
