"""Headless tests for the Klaus top bar (toolbar restyle + star logo)."""
import importlib
import json
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
top_bar = importlib.import_module("klausmate.top_bar")
theme = importlib.import_module("klausmate.theme")

section("logo")
html = top_bar.logo_html()
check("inline svg", "<svg" in html and "</svg>" in html)
check("hand-drawn star is a stroked open path",
      'fill="none"' in html and "stroke-linejoin" in html
      and 'd="M' in html)
check("colour comes from the CSS var, no hardcoded hex",
      "var(--klaus-accent)" in html and "#" not in html.split("href=#")[1])
check("clicking the star opens Klaus's own settings",
      "pycmd('klausmate:settings')" in html)
check("addressable for styling", 'id="klaus-logo"' in html)

section("toolbar css")
css = theme.toolbar_css()
check("no unsubstituted tokens", "{c[" not in css and "{{" not in css)
check("styles .header and .hitem", ".header" in css and ".hitem" in css)
check("RESTYLE ONLY — hides nothing",
      "display: none" not in css and "display:none" not in css)
check("logo slot styled", "#klaus-logo" in css)

section("theme-reactive (a baked palette went stale on toggle)")
# Anki's theme switch does NOT re-run webview_will_set_content — it only
# runs JS on the live document (documentElement.night-mode +
# body.night_mode/nightMode). A sheet built from a night_mode()
# snapshot therefore froze on the theme that was active when the
# toolbar last drew. Both palettes must ship in one sheet.
import inspect
check("toolbar_css takes no night argument (can't bake a snapshot)",
      list(inspect.signature(theme.toolbar_css).parameters) == [])
for key, tok in (("chrome", "chrome"), ("border", "grey_light"),
                 ("text", "text"), ("text-muted", "text_muted"),
                 ("accent", "blue_bright")):
    check(f"--klaus-{key}: both palettes present",
          f"--klaus-{key}: {theme.LIGHT[tok]};" in css
          and f"--klaus-{key}: {theme.DARK[tok]};" in css)
# Hover/press are TRANSLUCENT veils (Apple material states): black over
# light chrome, white over dark — so the highlight tints whatever is
# behind the button (flat chrome, custom colour, photo frost) instead
# of pasting an opaque grey chip over it.
check("hover veil: translucent black (light) / white (dark)",
      "--klaus-hover: rgba(0, 0, 0, 0.05);" in css
      and "--klaus-hover: rgba(255, 255, 255, 0.10);" in css)
check("press veil ships too, one step stronger",
      "--klaus-press: rgba(0, 0, 0, 0.09);" in css
      and "--klaus-press: rgba(255, 255, 255, 0.16);" in css)
check("no opaque hover fill remains in the bar sheet",
      theme.LIGHT["hover_subtle"] not in css)
check("links use the press veil on :active",
      ".header .hitem:active" in css)
_lum = lambda h: sum(int(h[i:i + 2], 16) for i in (1, 3, 5)) / 3
# Anki's own canvas: --canvas #f5f5f5 light, #2c2c2c dark (toolbar.css).
check("light chrome separates from Anki's light canvas (brighter)",
      _lum(theme.LIGHT["chrome"]) > _lum("#F5F5F5"))
check("dark chrome separates from Anki's dark canvas (darker)",
      _lum(theme.DARK["chrome"]) < _lum("#2C2C2C"))
check("dark chrome is not `surface` (that WAS Anki's canvas exactly)",
      theme.DARK["chrome"] != theme.DARK["surface"])
check("dark palette keyed on Anki's night-mode classes",
      ":root.night-mode" in css and "body.night_mode" in css
      and "body.nightMode" in css)
# The rules themselves must reference vars only — a single baked hex
# there is a colour that cannot follow the theme.
rules = css.split("}", 2)[2]
import re
check("rule bodies contain NO baked hex colours",
      re.search(r"#[0-9A-Fa-f]{6}", rules) is None)
check("rule bodies reference the klaus vars", "var(--klaus-" in rules)
check("the logo strokes a var, so it recolours too",
      "var(--klaus-accent)" in top_bar.logo_html())
check("top_bar injects without a snapshot",
      "toolbar_css()" in open("klausmate/top_bar.py").read())

section("seamless with the OS title bar")
check("no hairline under the bar (would break the seam)",
      "border-bottom: none !important" in css)
check("...and Anki's own header border is overridden too",
      css.count("border-bottom") == 1)
# The bar takes the window's real colour at runtime so it matches the
# system title bar on macOS AND Windows — no hardcoded shade can.
check("native_chrome_color degrades to None headlessly (no aqt)",
      top_bar.native_chrome_color() is None)
js = top_bar.chrome_override_js("#1e2225")
check("override sets the same var the stylesheet defines",
      "--klaus-chrome" in js and "#1e2225" in js and "setProperty" in js)
check("no colour clears the override, restoring the token",
      "removeProperty" in top_bar.chrome_override_js(None))
check("the colour is JSON-quoted, not string-glued",
      '"#1e2225"' in js)
_hostile = '"; alert(1); //'
_js_h = top_bar.chrome_override_js(_hostile)
check("a hostile value stays inside ONE escaped JS string literal",
      json.dumps(_hostile) in _js_h and '\\"' in json.dumps(_hostile))
check("...and the colour is the only interpolated part",
      _js_h.replace(json.dumps(_hostile), "") .count('"') == 0)
check("theme changes repaint the bar (Anki won't re-inject)",
      "theme_did_change" in open("klausmate/top_bar.py").read())
# The old first-paint override set --klaus-chrome on BOTH the light and
# dark selectors at once, pinning both themes to one draw-time snapshot
# — that is why the bar came up light in dark mode. It is gone; the
# background CSS is what the injector adds now, and the live window
# colour is only ever pushed imperatively (theme_did_change).
_src = open("klausmate/top_bar.py").read()
_inject = _src.split("def _on_webview_will_set_content")[1].split("def setup")[0]
check("first paint no longer pins both themes to one snapshot",
      ":root.night-mode" not in _inject)
check("first paint injects the chosen background instead",
      "_background_css(bar=True)" in _inject)
check("the star's settings command is intercepted",
      "klausmate:settings" in _src and "webview_did_receive_js_message" in _src)

section("one layer (Anki's fancy toolbar card must be flattened)")
# Anki's body.fancy paints .toolbar as an elevated card (background,
# rounded bottom corners, box-shadow, backdrop blur) and .hitem as a
# glass button — that inner card was the visible second layer. Its
# selectors (body.fancy:not(.flat) .hitem) outrank class-level rules,
# so the neutralisers MUST carry !important.
toolbar_block = css.split(".header .toolbar {", 1)[1].split("}", 1)[0]
for prop in ("background: transparent !important",
             "box-shadow: none !important",
             "border-radius: 0 !important",
             "backdrop-filter: none !important"):
    check(f"inner .toolbar neutralised: {prop.split(':')[0]}",
          prop in toolbar_block)
hitem_block = css.split(".header .hitem {", 1)[1].split("}", 1)[0]
check("hitem paints no button of its own",
      "background: transparent !important" in hitem_block
      and "box-shadow: none !important" in hitem_block)
check("fancy body margin removed (bar sits flush)",
      "body.fancy" in css and "margin-bottom: 0 !important" in css)

section("vertical centring (Anki pins trays to the top)")
header_block = css.split("\n    .header {", 1)[1].split("}", 1)[0]
check("header centres its children",
      "align-items: center !important" in header_block
      and "align-content: center !important" in header_block)
tray_block = css.split(".header .left-tray, .header .right-tray {", 1)[1] \
                .split("}", 1)[0]
check("trays override Anki's align-self: start",
      "align-self: center !important" in tray_block)
check("tray items are flex-centred (logo sits on the centre line)",
      "align-items: center !important"
      in css.split(".header .tray-item {", 1)[1].split("}", 1)[0])

section("hook wiring shape")
check("left-tray handler prepends (logo must be leftmost)",
      callable(top_bar._on_left_tray))
content: list = ["<div>ankihub-item</div>"]
top_bar._on_left_tray(content, None)
check("logo lands FIRST, other addons' items untouched after it",
      content[0] == top_bar.logo_html()
      and content[1] == "<div>ankihub-item</div>")

section("bottom toolbar matches the top (K-109)")
bcss = theme.bottombar_css()
check("both palettes ship in one sheet, keyed on Anki's night classes",
      ":root.night-mode" in bcss and "body.night_mode" in bcss
      and f"--klaus-chrome: {theme.LIGHT['chrome']};" in bcss
      and f"--klaus-chrome: {theme.DARK['chrome']};" in bcss)
check("the bar IS the chrome colour, borderless",
      "background: var(--klaus-chrome) !important;" in bcss
      and "border: none !important;" in bcss)
check("Anki's native buttons are flattened into the top bar's chip "
      "language (appearance off, transparent at rest, rounded)",
      "-webkit-appearance: none;" in bcss
      and "background: transparent;" in bcss
      and "border-radius: 8px;" in bcss)
check("hover/press use the same translucent veils as the top bar",
      "background: var(--klaus-hover);" in bcss
      and "background: var(--klaus-press);" in bcss)
check("hook injects it for deck-browser and overview bottom bars only",
      '"DeckBrowserBottomBar"' in open("klausmate/top_bar.py").read()
      and '"OverviewBottomBar"' in open("klausmate/top_bar.py").read()
      and "ReviewerBottomBar" not in open("klausmate/top_bar.py").read())

section("star geometry shared with Qt surfaces")
pts = top_bar.star_points()
check("star_points parses every vertex of the hand-drawn path",
      len(pts) == 5 and pts[0] == (5.5, 1.5) and pts[-1] == (12.8, 24.5))
check("all vertices live inside the declared viewBox",
      all(0 <= x <= top_bar.STAR_VIEWBOX and 0 <= y <= top_bar.STAR_VIEWBOX
          for x, y in pts))

raise SystemExit(report())
