"""Headless tests for the Klaus top bar (toolbar restyle + k logo)."""
import importlib
import json
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
top_bar = importlib.import_module("klaus_note.top_bar")
theme = importlib.import_module("klaus_note.theme")

section("logo")
html = top_bar.logo_html()
check("inline svg", "<svg" in html and "</svg>" in html)
# 2026-10-01: the mark is Pouya's hand-drawn k — ONE evenodd path of
# M/L/Z subpaths, filled in the text colour, in a viewBox cropped to the k.
check("the hand-drawn k is ONE filled evenodd path in its cropped box",
      f'viewBox="{top_bar.LOGO_VIEWBOX}"' in html
      and top_bar.LOGO_VIEWBOX == "126 163 1010 918"
      and html.count("<path") == 1
      and 'fill-rule="evenodd"' in html
      and html.count('fill="var(--klaus-text, currentColor)"') == 1)
check("nothing is stroked — a filled mark, never an outlined one",
      "stroke" not in html and 'fill="none"' not in html)
check("the path in the svg is _LOGO_PATH, verbatim",
      f'd="{top_bar._LOGO_PATH}"' in html)
check("no tile inside Klaus: the brand file's #2393f4 square is the app "
      "icon only", "<rect" not in html and "2393f4" not in html)
check("colour comes from the CSS var with a currentColor fallback — "
      "the var only exists while the design layer injects toolbar_css; "
      "on a stock toolbar the k must inherit Anki's own link colour "
      "rather than vanish (an unresolvable var() makes the fill invalid)",
      "var(--klaus-text, currentColor)" in html
      and "#" not in html.split("href=#")[1])
check("clicking the k opens Klaus's own settings",
      "pycmd('klaus_note:settings')" in html)
check("addressable for styling", 'id="klaus-logo"' in html)
# The <a> is the accessible element: it carries the name a screen
# reader announces and the click target. klaus-logo.svg ships its own
# role/aria-label for standalone viewing; repeating them on the inline
# copy would announce the mark twice inside one link.
check("the <a> owns the accessible name — the inner svg repeats neither "
      "role nor aria-label",
      html.count("aria-label=") == 1
      and 'aria-label="Klaus settings"' in html
      and "role=" not in html
      and 'title="Klaus settings"' in html)
check("the 26x26 seat is unchanged — the box is the toolbar's, only the "
      "artwork inside it changed",
      'width="26" height="26"' in html)

section("toolbar css")
css = theme.toolbar_css()
check("no unsubstituted tokens", "{c[" not in css and "{{" not in css)
check("styles .header and .hitem", ".header" in css and ".hitem" in css)
check("RESTYLE ONLY — hides nothing",
      "display: none" not in css and "display:none" not in css)
# The logo's geometry used to live in this sheet, which the KlausBook
# design gate switches off — so the mark moved whenever the design
# layer did. It now travels inline on the element (logo_html), and this
# sheet must NOT re-declare it, or the two could drift apart again.
# Comments are stripped first: a CSS comment naming #klaus-logo would
# otherwise satisfy this pin with no rule present (prose has faked four
# pins in this repo already).
_css_code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
check("the logo's seat is NOT in this sheet — it rides inline so the "
      "design gate cannot move the mark",
      "#klaus-logo" not in _css_code)
check("...and logo_html carries the whole seat itself",
      all(prop in top_bar.logo_html()
          for prop in ("display: inline-flex", "align-items: center",
                       "vertical-align: middle", "padding: 0 8px 0 2px")))

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
# light chrome, white over dark — so the highlight tints the flat
# chrome colour instead of pasting an opaque grey chip over it.
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
check("the logo fills a var, so it recolours too",
      "var(--klaus-text," in top_bar.logo_html())
check("top_bar injects without a snapshot",
      "toolbar_css()" in open("klaus_note/top_bar.py").read())

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
      "theme_did_change" in open("klaus_note/top_bar.py").read())
# The old first-paint override set --klaus-chrome on BOTH the light and
# dark selectors at once, pinning both themes to one draw-time snapshot
# — that is why the bar came up light in dark mode. It is gone; the
# background CSS is what the injector adds now, and the live window
# colour is only ever pushed imperatively (theme_did_change).
_src = open("klaus_note/top_bar.py").read()
_inject = _src.split("def _on_webview_will_set_content")[1].split("def setup")[0]
check("first paint no longer pins both themes to one snapshot",
      ":root.night-mode" not in _inject)
check("first paint does NOT inject the chosen wallpaper — the bars "
      "used to paint a blurred copy of it and no longer do (removed "
      "2026-08-30); they show flat chrome regardless of background "
      "mode",
      "_background_css()" not in _inject
      and "background.bar_css" not in _src)
check("_background_css takes no bar/bottom distinction any more — its "
      "only remaining caller wants the deck/overview background",
      "def _background_css() -> str:" in _src)
check("the logo's settings command is intercepted",
      "klaus_note:settings" in _src and "webview_did_receive_js_message" in _src)

section("a SEPARATE background for the study screen")
# Pouya: "this needs to be separate from the background I set for the
# regular main section." One dispatch function, two independent paths.
_main_src = open("klaus_note/top_bar.py").read()
_dispatch = _main_src.split("def _on_main_webview_content")[1].split(
    "def _on_js_message")[0]
check("the reviewer's own webview is handled — context=self in "
      "Reviewer._initWeb, verified against Anki's own source",
      "isinstance(context, Reviewer)" in _dispatch)
check("it calls its OWN css helper, resolved from its OWN prefix — "
      "never the deck screen's _background_css",
      "_reviewer_background_css()" in _dispatch)
# .split(marker, 1) + a length check, never a blind [1] — a marker
# that has genuinely disappeared (the regression these two pins exist
# to catch) must FAIL the check, not IndexError and crash the rest of
# this file's checks along with it (this suite was bitten by exactly
# that shape of bug before: a crashing test file silently dropped
# every pin after it).
_reviewer_parts = _dispatch.split("isinstance(context, Reviewer)", 1)
check("NO panel_js weld on the reviewer branch — that DOM surgery "
      "targets the deck table, which does not exist on this screen, "
      "and the intent (a card is the user's content) rules it out "
      "even where it would happen to no-op",
      len(_reviewer_parts) > 1 and "panel_js" not in _reviewer_parts[1])
_deck_parts = _dispatch.split("isinstance(context, (DeckBrowser", 1)
_deck_branch = (
    _deck_parts[1].split("isinstance(context, Reviewer)", 1)[0]
    if len(_deck_parts) > 1 else ""
)
check("the deck screens keep doing exactly what they did before — "
      "panel_js weld still fires there, unaffected by the new branch",
      bool(_deck_branch) and "background.panel_js" in _deck_branch)
check("_reviewer_background_css shares the exact gate shape as "
      "_background_css — resolved from a DIFFERENT prefix, never "
      "reading the deck screen's own keys",
      'prefix="reviewer_background"' in _main_src
      and "design_enabled" in _main_src.split(
          "def _reviewer_background_css")[1].split(
          "def _on_main_webview_content")[0])

section("the KlausBook design gate")
# klausbook_design (default OFF) is the master switch between "stock
# Anki + Klaus tools" and the full KlausBook look. Every visual
# injection into an Anki-owned surface must consult it; the functional
# ones (the k, Library link, settings pycmd) must not.
check("the toolbar/bottombar restyle is gated — it was the one part of "
      "the design layer no config key reached",
      "design_enabled" in _inject)
_bgcss = _src.split("def _background_css")[1].split("def _on_main_webview_content")[0]
check("the background paint funnel is gated AT THE FUNNEL, not inside "
      "background.resolve() — Preferences seeds its widgets through "
      "resolve(stored) and writes the spec back on Save, so a "
      "resolve-level gate would wipe a stored image background",
      "design_enabled" in _bgcss and 'return ""' in _bgcss)
_push = _src.split("def _push_chrome_colour")[1].split("def _addon")[0]
check("the chrome-colour push is gated — an off state must not eval "
      "into Anki's toolbar on every theme flip",
      "design_enabled" in _push)
check("the k itself is NOT gated: it survives native mode as the "
      "one Klaus mark and the in-window Preferences entry",
      "design_enabled" not in _src.split("def _on_left_tray")[1].split("def _on_webview_will_set_content")[0])
check("the dead congrats import is gone for good — that class does not "
      "exist in this Anki and the congrats page never fires this hook",
      "CongratsPage" not in _src and "deckdescription" not in _src)

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
# Anki draws the toolbar in finish_ui_setup — BEFORE any profile opens —
# so the first sheet bakes the DEFAULT accent; without this profile-open
# redraw the k launched blue on every restart whatever theme was
# saved (live repro, 2026-08-30). code_only so prose can't fake the pin.
_wiring_code = code_only(open("klaus_note/top_bar.py").read())
check("setup registers a profile-open toolbar redraw (saved accent "
      "reaches the bar only through it)",
      "gui_hooks.profile_did_open.append(_on_profile_open_redraw)"
      in _wiring_code)
check("that redraw is deferred one tick, so it runs after every other "
      "profile-open handler including _apply_color_theme",
      "QTimer.singleShot(0, _redraw)"
      in code_only(inspect.getsource(top_bar._on_profile_open_redraw)))

section("bottom toolbar matches the top (K-109)")
bcss = theme.bottombar_css()
check("both palettes ship in one sheet, keyed on Anki's night classes",
      ":root.night-mode" in bcss and "body.night_mode" in bcss
      and f"--klaus-chrome: {theme.LIGHT['chrome']};" in bcss
      and f"--klaus-chrome: {theme.DARK['chrome']};" in bcss)
check("the bar IS the chrome colour, borderless",
      "background: var(--klaus-chrome) !important;" in bcss
      and "border: none !important;" in bcss)
# Pouya: "EXACTLY the same as the top buttons." Not a lookalike —
# both sheets must emit the SAME shared declaration blocks, byte for
# byte, so the two bars cannot drift apart.
tcss = theme.toolbar_css()
for blk_name, blk in (("base", theme._chip_base_rules()),
                      ("hover", theme._chip_hover_rules()),
                      ("active", theme._chip_active_rules())):
    check(f"chip {blk_name} block is byte-identical in BOTH bar sheets",
          blk in tcss and blk in bcss)
check("chip blocks are fully !important — webview.css ships plain "
      "`button` rules that load with stdHtml regardless of order",
      "background: transparent !important;" in theme._chip_base_rules()
      and "border-radius: 8px !important;" in theme._chip_base_rules())
check("only the <button>-specific native strip is extra on the bottom",
      "-webkit-appearance: none !important;" in bcss
      and "#header button" in bcss)
check("hook injects it for deck-browser and overview bottom bars only",
      '"DeckBrowserBottomBar"' in open("klaus_note/top_bar.py").read()
      and '"OverviewBottomBar"' in open("klaus_note/top_bar.py").read()
      and "ReviewerBottomBar" not in open("klaus_note/top_bar.py").read())

section("logo geometry: code == brand file, Qt == web")
# The code and the brand file cannot drift: docs/reference/brand/
# klaus-logo.svg is Pouya's file verbatim (blue tile + white k), and
# _LOGO_PATH is what actually paints. Redraw one and forget the other
# and this fails.
import xml.etree.ElementTree as _ET
_NS = "{http://www.w3.org/2000/svg}"
_svg_root = _ET.parse("docs/reference/brand/klaus-logo.svg").getroot()
_brand_paths = list(_svg_root.iter(_NS + "path"))
_brand_k = [p for p in _brand_paths if p.get("fill") == "#fff"]
check("the brand file is the 1254 tile with one white k path",
      _svg_root.get("viewBox") == "0 0 1254 1254"
      and len(_brand_paths) == 1 and len(_brand_k) == 1
      and [r.get("fill") for r in _svg_root.iter(_NS + "rect")] == ["#2393f4"])
check("_LOGO_PATH IS the brand file's white path, verbatim, same rule",
      _brand_k and _brand_k[0].get("d") == top_bar._LOGO_PATH
      and _brand_k[0].get("fill-rule") == "evenodd")
# M/L/Z only, so every number pair is a vertex: the crop must hold all
# of them, or the k is clipped in its seat.
_d = top_bar._LOGO_PATH
_nums = [int(n) for n in re.findall(r"-?\d+", _d)]
_vx, _vy = _nums[0::2], _nums[1::2]
_bx, _by, _bw, _bh = (int(v) for v in top_bar.LOGO_VIEWBOX.split())
check("the path is M/L/Z polygons only (no curves to hide a vertex)",
      set(re.findall(r"[A-Za-z]", _d)) == {"M", "L", "Z"})
check("every vertex lies inside the cropped viewBox, with a margin",
      _bx < min(_vx) and max(_vx) < _bx + _bw
      and _by < min(_vy) and max(_vy) < _by + _bh)
check("the crop is tight: the k spans over 90% of the box both ways",
      (max(_vx) - min(_vx)) / _bw > 0.9 and (max(_vy) - min(_vy)) / _bh > 0.9)
_qt_svg = _ET.fromstring(top_bar.logo_svg("#123456"))
_qt_paths = list(_qt_svg)
check("Qt renders the same path, evenodd, in its requested accent",
      len(_qt_paths) == 1
      and _qt_paths[0].get("d") == top_bar._LOGO_PATH
      and _qt_paths[0].get("fill-rule") == "evenodd"
      and _qt_paths[0].get("fill") == "#123456"
      and _qt_svg.get("viewBox") == top_bar.LOGO_VIEWBOX)
check("the fill is attribute-escaped",
      'fill="a&quot;b"' in top_bar.logo_svg('a"b'))
check("the star's leftovers are gone",
      not any(hasattr(top_bar, n) for n in
              ("star_polygons", "star_points", "_STAR_PATHS", "STAR_VIEWBOX")))

section("live preview mid-review (non-modal Preferences, 2026-08-30)")
# mw.reset() rebuilds the study queues (aqt/main.py says so in its own
# comment) — with Preferences non-modal a preview tick can land while
# a card is up, so refresh() must push CSS into the live page instead.
_push = top_bar.reviewer_style_push_js("html{background:red}")
check("push JS replaces ONE tag by id — created on demand, text "
      "swapped, never a second sheet stacked",
      "getElementById('klaus-reviewer-bg')" in _push
      and _push.count("appendChild") == 1
      and "el.textContent=css" in _push)
check("an empty push REMOVES the sheet, so a discarded preview leaves "
      "nothing behind",
      "el.remove()" in top_bar.reviewer_style_push_js(""))
check("the css rides as one JSON string literal (quotes survive)",
      json.dumps("html{background:red}") in _push)
_refresh_code = code_only(inspect.getsource(top_bar.refresh))
# Guarded split (never a blind [1] — a missing marker must FAIL the
# pin, not crash the file): the push call must come BEFORE mw.reset()
# and return without reaching it.
_after_push = _refresh_code.split(
    "reviewer_style_push_js(_reviewer_background_css())", 1
)
check("refresh() pushes the reviewer css and RETURNS before mw.reset() "
      "— the review state never takes the queue-rebuilding reset",
      len(_after_push) > 1
      and "return" in _after_push[1].split("mw.reset()", 1)[0]
      and "mw.reset()" in _after_push[1])
check("the will_set_content injection and the push share one tag id, "
      "so a push can restyle or empty the build-time sheet",
      "klaus-reviewer-bg"
      in inspect.getsource(top_bar._on_main_webview_content)
      and "klaus-reviewer-bg"
      in inspect.getsource(top_bar.reviewer_style_push_js))

section("gradient editor wiring (drag on the actual screen)")
_tb_raw = open("klaus_note/top_bar.py").read()
_tb_code = code_only(_tb_raw)
check("both screens plant the editor at page build while armed — two "
      "gradient_edit_js call sites, each inside its branch's `if css` "
      "(the design gate having passed: handles never land on a stock "
      "screen)",
      _tb_code.count("background.gradient_edit_js(") == 2
      and _tb_code.count("grad_edit_active()") >= 3)
check("refresh()'s review path cleans THEN re-plants (a planted "
      "editor holds its colours in a closure — replacing it is what "
      "keeps a mid-review colour edit from dragging stale paint)",
      "background.GRAD_EDIT_CLEANUP_JS+editor_js"
      in _tb_code.replace(" ", "")
      and "background.gradient_edit_eval_js(" in _tb_code)
# Behavioural: a real drag-end message through the real handler.
import base64 as _b64

_bg_mod = importlib.import_module("klaus_note.background")
_seen: list = []
_bg_mod.set_grad_edit(True, lambda t, op, d: _seen.append((t, op, d)))
_payload = _b64.b64encode(
    json.dumps({"target": "main", "op": "geom", "i": 1,
                "x": 30, "y": 40, "size": 120}).encode()
).decode()
_res = top_bar._on_js_message(
    (False, None), "klaus_note:bggrad:" + _payload, None
)
_bg_mod.set_grad_edit(False, None)
check("an editor pycmd decodes, clamps, reaches the sink with its op "
      "and sphere index, and is consumed by the handler",
      _res == (True, None)
      and _seen == [("main", "geom",
                     {"i": 1, "x": 30, "y": 40, "size": 120})])
check("a garbage payload is swallowed, never raises out of the hook",
      top_bar._on_js_message(
          (False, None), "klaus_note:bggrad:@@not-b64@@", None
      ) == (True, None))

raise SystemExit(report())
