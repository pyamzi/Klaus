"""Headless tests for the custom background + frosted top bar."""
import importlib
import os
import re
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
bg = importlib.import_module("klausmate.background")

section("resolve: defaults and validation")
d = bg.resolve({})
check("default mode paints nothing", d["mode"] == "theme")
check("non-dict degrades", bg.resolve(None)["mode"] == "theme")
check("unknown mode falls back", bg.resolve({"background_mode": "x"})["mode"] == "theme")
check("bad colour falls back to the default",
      bg.resolve({"background_color": "red"})["color"] == bg.DEFAULT_COLOR)
check("short hex accepted", bg.resolve({"background_color": "#abc"})["color"] == "#abc")
check("bad fit falls back", bg.resolve({"background_fit": "zoom"})["fit"] == "cover")
check("out-of-range blur falls back",
      bg.resolve({"background_blur": 999})["blur"] == bg.DEFAULT_BLUR
      and bg.resolve({"background_blur": "x"})["blur"] == bg.DEFAULT_BLUR)
check("image mode with no image is just the theme",
      bg.resolve({"background_mode": "image", "background_image": ""})["mode"]
      == "theme")

section("image names are contained")
check("path traversal stripped to a basename",
      bg.safe_image_name("../../../../etc/passwd.png") == "passwd.png")
check("non-image extensions refused",
      bg.safe_image_name("evil.py") == "" and bg.safe_image_name("x.exe") == "")
check("dotfiles refused", bg.safe_image_name(".hidden.png") == "")
check("url built under the addon's web export",
      bg.image_url("klausmate", "wall.jpg")
      == "/_addons/klausmate/user_files/backgrounds/wall.jpg")
check("no url without a valid image", bg.image_url("klausmate", "x.py") == "")

section("main_css: Anki's own screens")
check("theme mode paints nothing at all",
      bg.main_css(bg.resolve({})) == "")
colour = bg.resolve({"background_mode": "color", "background_color": "#123456"})
check("colour mode fills html/body", "#123456" in bg.main_css(colour))
img = bg.resolve({"background_mode": "image", "background_image": "w.jpg"})
url = bg.image_url("klausmate", "w.jpg")
css = bg.main_css(img, url)
check("image mode references the export url", url in css)
check("image mode is fixed + covering",
      "background-attachment: fixed" in css and "cover" in css)
check("image mode without a url degrades to nothing",
      bg.main_css(img, "") == "")

section("bar_css: the frost")
# The whole point: blurring a flat colour is a no-op, so the bar simply
# IS that colour and matches the window chrome with no measuring.
bar = bg.bar_css(colour)
check("colour mode needs no blur at all",
      "#123456" in bar and "blur(" not in bar)
check("theme mode leaves the bar to the theme tokens",
      bg.bar_css(bg.resolve({})) == "")
bar_img = bg.bar_css(img, url)
check("image mode blurs a copy of the background",
      "filter: blur(" in bar_img and url in bar_img)
check("the blurred layer sits behind the links", "z-index: -1" in bar_img)
check("content is lifted above the frost", ".header > *" in bar_img)
check("a tint keeps links readable over any photo",
      "--klaus-chrome" in bar_img and "opacity:" in bar_img)
# Blur samples outside the element; without bleed the edges go pale.
blur_px = img["blur"]
check("the frost layer bleeds past every edge",
      f"{-blur_px * 2}px" in bar_img)
check("no url means no frost", bg.bar_css(img, "") == "")

section("bar_css bottom variant (K-109): the bottom toolbar")
bot_col = bg.bar_css(colour, bottom=True)
check("colour mode paints html+body — the bottom bar has no .header "
      "class, only the #header table",
      "#123456" in bot_col and "html, body" in bot_col
      and ".header" not in bot_col)
bot_img = bg.bar_css(img, url, bottom=True)
check("image mode frosts off body and samples the image's BOTTOM edge "
      "(the slice of the window background the bar continues)",
      "body::before" in bot_img
      and "background-position: center bottom" in bot_img
      and "filter: blur(" in bot_img)
check("same tint + bleed discipline as the top bar",
      "--klaus-chrome" in bot_img and f"{-img['blur'] * 2}px" in bot_img)
check("buttons take full contrast + shadow over a photo, from a "
      "selector that outranks the chip base",
      "body #header button" in bot_img and "text-shadow" in bot_img)
check("bottom frost also degrades to nothing without a url",
      bg.bar_css(img, "", bottom=True) == "")
check("top output is byte-identical to before the bottom param",
      bg.bar_css(colour) == bg.bar_css(colour, bottom=False) == bar)

section("store_image")
tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "pic.png")
open(src, "wb").write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
stored = bg.store_image(tmp, src)
check("stored under user_files/backgrounds", stored == "pic.png")
check("the copy really exists",
      os.path.isfile(os.path.join(tmp, bg.IMAGE_DIR, "pic.png")))
other = os.path.join(tmp, "sub")
os.makedirs(other, exist_ok=True)
src2 = os.path.join(other, "pic.png")
open(src2, "wb").write(b"\x89PNG\r\n\x1a\n" + b"1" * 64)
stored2 = bg.store_image(tmp, src2)
check("a different picture with the same name is versioned, not clobbered",
      stored2 == "pic-2.png"
      and open(os.path.join(tmp, bg.IMAGE_DIR, "pic.png"), "rb").read()
      != open(os.path.join(tmp, bg.IMAGE_DIR, "pic-2.png"), "rb").read())
check("non-images refused",
      bg.store_image(tmp, os.path.join(tmp, "nope.py")) == "")
check("missing files refused", bg.store_image(tmp, "/no/such/file.png") == "")

section("frosted panels over an image (readability)")
# Anki paints .fancy table with --canvas-glass but never blurs behind
# it, so over a photo the "glass" was just a see-through wash. Panels
# are in the SAME document as the page background, so unlike the bars
# they can use a real backdrop-filter.
_img = bg.resolve({"background_mode": "image", "background_image": "p.png",
                   "background_blur": 18})
_panels = bg.panel_css(_img)


def _alphas(css, token):
    """Every alpha declared for a token, light palette then night."""
    import re
    return [float(m) for m in
            re.findall(rf"{token}: rgba\([\d, ]+,\s*([\d.]+)\)", css)]


check("panels frost with a REAL backdrop-filter (same document as the "
      "background, unlike the separate-webview toolbars)",
      "backdrop-filter: blur(18px)" in _panels
      and "-webkit-backdrop-filter: blur(18px)" in _panels)
check("the blur follows the user's own blur setting",
      "blur(18px)" in _panels
      and "blur(22px)" in bg.panel_css(
          bg.resolve({"background_mode": "image",
                      "background_image": "p.png",
                      "background_blur": 22})))
check("the deck table, Anki's callout box and the review heatmap all "
      "get it — the heatmap joins this ONE rule instead of frosting "
      "itself, so it cannot drift out of step with the deck table",
      "table, .callout, .klaus-hm {" in _panels)
check("panels sit on a tint so text stays legible on a busy photo — "
      "a RANGE, not an exact value, so the look can be retuned without "
      "churning this test: sheer enough that the picture still reads as "
      "a picture, opaque enough to lift small text off it",
      all(0.35 <= a <= 0.75
          for a in _alphas(_panels, "--klaus-panel")))
check("BOTH palettes ship, keyed on Anki's own night-mode class — the "
      "theme flips that class with JS and never re-runs our injector",
      ":root.night-mode {" in _panels
      and "--klaus-panel: rgba(38,38,38," in _panels
      and len(_alphas(_panels, "--klaus-panel")) == 2)
check("rules use !important, since Anki's own sheet also sets these",
      _panels.count("!important") >= 4)
check("panels round to Anki's own container radius, with a fallback",
      "var(--border-radius-medium, 12px)" in _panels)

check("the current/hovered deck row joins the glass instead of punching "
      "an opaque slab through it (Anki fills it with --border-subtle)",
      "tr.deck.current td," in _panels
      and "tr.deck:hover:not(.top-level-drag-row) td," in _panels
      and "background: var(--klaus-panel-strong) !important;" in _panels)
check("the row rule is scoped to tr.deck — unscoped, it also matched the "
      "OVERVIEW's layout table and turned its cells into opaque slabs on "
      "hover, inside the frosted panel (Anki's own copy of this rule is "
      "unscoped but ships only in deckbrowser.css; ours is injected into "
      "the overview and congrats screens too)",
      "tr:hover" not in _panels.replace("tr.deck:hover", "")
      and " .current td," not in _panels)
_pa, _sa = _alphas(_panels, "--klaus-panel"), _alphas(_panels,
                                                      "--klaus-panel-strong")
check("...and is heavier than the panel in BOTH palettes, but only by a "
      "step — computed from the emitted alphas, so the row can neither "
      "dissolve into the panel nor go back to being a bright slab of its "
      "own. The RELATIONSHIP is the design; either number may be retuned",
      len(_pa) == 2 and len(_sa) == 2
      and all(0 < (s - p) <= 0.25 for s, p in zip(_sa, _pa)))
_row_rule = _panels.split("tr.deck.current td,", 1)[1].split("}", 1)[0]
check("the row does NOT stack a second backdrop-filter — it sits INSIDE "
      "the table, which is already a backdrop root, so one blur is "
      "enough (#studiedToday is a SIBLING of the table and does need "
      "its own, which is why this asks about the row rule specifically)",
      "backdrop-filter" not in _row_rule)
check("Anki's RTL rules are more specific than its plain ones, so the "
      "row selector spells the [dir=rtl] variants out to match them — "
      "scoped to tr.deck like their LTR twins",
      "[dir=rtl] tr.deck.current td," in _panels
      and "[dir=rtl] tr.deck:hover:not(.top-level-drag-row) td {"
      in _panels)

section("the studied-today line lives INSIDE the deck panel")
# Anki renders <center><table>..</table><br>%(stats)s</center>, so the
# line is a SIBLING of the panel. It was first styled as a second box
# made to look joined, which meant keeping two widths in agreement —
# and forcing width:100% overflowed the panel off-screen, because Anki
# gives the table padding:1rem with content-box sizing. panel_js now
# reparents it into the table instead: one box, the table's own width.
check("the row is styled for life inside the table, not as its own box",
      "tr.klaus-studied td," in _panels
      and "tr.klaus-studied #studiedToday { margin: 0 !important; }"
      in _panels)

# Anki's deckbrowser.css hover rule is UNSCOPED (`.current td,
# tr:hover:not(.top-level-drag-row) td`) so it reaches this injected
# row too, and its :first-child/:last-child radius rules both fire on
# the one colSpan cell — the row lit up as a solid grey PILL on hover.
_studied_rule = _panels.split(" tr.klaus-studied td,", 1)[1].split("}")[0]
check("hovering the studied line paints NOTHING — background forced "
      "transparent with !important, which beats Anki's rule at any "
      "specificity since Anki's carries none",
      "background: transparent !important" in _studied_rule
      and "tr.klaus-studied:hover td," in _panels)
check("...in RTL too: Anki's [dir=rtl] hover variant is its most "
      "specific rule (0,3,2), so the RTL twin is spelled out like the "
      "deck-row rule's",
      "[dir=rtl] tr.klaus-studied:hover td {" in _panels)
check("the pill radius is neutralised — first/last-child rounding both "
      "fire on a single colSpan cell",
      "border-radius: 0 !important" in _studied_rule)
_pad = re.search(
    r"padding: ([\d.]+)em 12px ([\d.]+)em", _studied_rule)
check("padding is a RELATIONSHIP, not two magic numbers: generous air "
      "above (>= 1.2em, so the line stands off the decks), snug below "
      "(<= 0.6em, hugging the panel's bottom edge), top more than "
      "double the bottom — retunable without churning this test",
      _pad is not None
      and float(_pad.group(1)) >= 1.2
      and float(_pad.group(2)) <= 0.6
      and float(_pad.group(1)) > 2 * float(_pad.group(2)),
      _pad.group(0) if _pad else "no padding rule")
check("no width is set anywhere — that overflow is exactly what the "
      "reparenting removed the need for",
      "width:" not in _panels.replace("min-width", ""))
check("the old two-box weld is fully gone (no flattened table corners, "
      "no <br> hiding, no second panel box)",
      "center > table:has(tr.deck)" not in _panels
      and "center:has(#studiedToday)" not in _panels)
check("the moved row is NOT a tr.deck, so the hover/current rule cannot "
      "highlight it as if it were a deck",
      "tr.klaus-studied" not in _row_rule)
check("the script ships exactly when the panel styling does, so the two "
      "can never disagree about whether Klaus styles this screen",
      bool(bg.panel_js(_img))
      and bool(bg.panel_js(bg.resolve(
          {"background_mode": "color", "background_color": "#123456"})))
      and bg.panel_js(bg.resolve({"background_mode": "theme"})) == "")
check("it is a self-contained, fully guarded <script>",
      bg.panel_js(_img).startswith("<script>")
      and bg.panel_js(_img).endswith("</script>")
      and "try{" in bg.panel_js(_img))

# The script is the ONE piece of Klaus that manipulates Anki's DOM, and
# no string pin can tell whether it actually works. tests/
# panel_js_dom_test.js runs it against a fake DOM shaped like Anki's
# real markup. node is not required to develop this addon, so when it is
# missing this is reported as SKIPPED rather than counted as a pass —
# an unverified behaviour must never look like a verified one.
import shutil
import subprocess

if shutil.which("node"):
    _js_body = bg.panel_js(_img).replace("<script>", "").replace(
        "</script>", "")
    _js_path = os.path.join(tempfile.mkdtemp(), "panel.js")
    open(_js_path, "w").write(_js_body)
    _here = os.path.dirname(os.path.abspath(__file__))
    _proc = subprocess.run(
        ["node", os.path.join(_here, "panel_js_dom_test.js"), _js_path],
        capture_output=True, text=True)
    check("the generated script is valid JS and behaves correctly against "
          "a DOM shaped like Anki's — moves the line into the deck table, "
          "removes the gap, is idempotent across re-renders, leaves the "
          "overview alone, and no-ops when there is nothing to move",
          _proc.returncode == 0,
          (_proc.stdout + _proc.stderr).strip().replace("\n", " | "))
else:
    print("  SKIP  panel_js DOM behaviour (node not installed) — NOT "
          "counted as a pass")

_colour_panels = bg.panel_css(bg.resolve(
    {"background_mode": "color", "background_color": "#123456"}))
check("panels look the SAME whichever background is painted — colour "
      "mode gets the tint, borders, corners and welded stats line too",
      "table, .callout, .klaus-hm {" in _colour_panels
      and "#studiedToday {" in _colour_panels
      and "--klaus-panel:" in _colour_panels)
check("...but NOT the blur: a Gaussian blur of a flat colour is that "
      "colour, so backdrop-filter there would cost a compositing layer "
      "per panel to change nothing",
      "backdrop-filter" not in _colour_panels)
check("theme mode stays untouched — Klaus paints no background there, "
      "and Anki's stock look already glasses these surfaces itself",
      bg.panel_css(bg.resolve({"background_mode": "theme"})) == "")
check("main_css carries the panels in BOTH painted modes",
      "--klaus-panel:" in bg.main_css(bg.resolve(
          {"background_mode": "color", "background_color": "#123456"}))
      and "--klaus-panel:" in bg.main_css(_img, "pic.png"))
check("an out-of-range blur falls back rather than emitting junk CSS",
      f"blur({bg.DEFAULT_BLUR}px)" in bg.panel_css(
          {"mode": "image", "blur": 9999}))
check("main_css ships the panel rules with the image background, so one "
      "injection covers deck list, overview and congrats alike",
      "backdrop-filter" in bg.main_css(_img, "pic.png")
      and "backdrop-filter" not in bg.main_css(
          bg.resolve({"background_mode": "color"})))

section("unsaved live preview (Appearance previews before Save)")
# Appearance is judged by eye, so Preferences renders accent+background
# live while you configure them — but Save stays the ONLY writer of
# config. The pending background lives here as an override that every
# painting surface consults through effective_cfg().
_STORED = {"background_mode": "color", "background_color": "#112233"}
_PENDING = {"background_mode": "image", "background_image": "pic.png",
            "background_fit": "tile", "background_blur": 5}

bg.set_preview(None)
check("nothing armed by default — a fresh session paints stored config",
      bg.preview_active() is False
      and bg.effective_cfg(_STORED) is _STORED)

bg.set_preview(_PENDING)
check("an armed preview shadows stored config at the paint seam",
      bg.preview_active() is True
      and bg.effective_cfg(_STORED) is _PENDING)
check("the preview really changes what gets painted, end to end",
      bg.resolve(bg.effective_cfg(_STORED))["mode"] == "image"
      and bg.resolve(bg.effective_cfg(_STORED))["fit"] == "tile")
check("resolve() stays a PURE function of its argument — the override "
      "lives at the seam, so every existing resolve(cfg) test still "
      "tests exactly what it says",
      bg.resolve(_STORED)["mode"] == "color"
      and bg.resolve(_STORED)["color"] == "#112233")

bg.set_preview(None)
check("clearing restores stored config (Save and Cancel both land here)",
      bg.preview_active() is False
      and bg.resolve(bg.effective_cfg(_STORED))["mode"] == "color")
bg.set_preview("not a dict")
check("a non-dict clears rather than half-arming the preview",
      bg.preview_active() is False)
bg.set_preview(None)

raise SystemExit(report())
