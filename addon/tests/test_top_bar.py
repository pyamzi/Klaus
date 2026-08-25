"""Headless tests for the Klaus top bar (toolbar restyle + star logo)."""
import importlib
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
check("click goes to Decks via Anki's own pycmd",
      "pycmd('decks')" in html)
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
for key, tok in (("surface", "surface"), ("border", "grey_light"),
                 ("text", "text"), ("text-muted", "text_muted"),
                 ("hover", "hover_subtle"), ("accent", "blue_bright")):
    check(f"--klaus-{key}: both palettes present",
          f"--klaus-{key}: {theme.LIGHT[tok]};" in css
          and f"--klaus-{key}: {theme.DARK[tok]};" in css)
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

raise SystemExit(report())
