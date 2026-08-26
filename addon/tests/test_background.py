"""Headless tests for the custom background + frosted top bar."""
import importlib
import os
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
check("the deck table and Anki's callout box both get it",
      "table, .callout {" in _panels)
check("panels sit on a tint so text stays legible on a busy photo",
      "--klaus-panel: rgba(255,255,255,0.62)" in _panels)
check("BOTH palettes ship, keyed on Anki's own night-mode class — the "
      "theme flips that class with JS and never re-runs our injector",
      ":root.night-mode {" in _panels
      and "--klaus-panel: rgba(38,38,38,0.62)" in _panels)
check("rules use !important, since Anki's own sheet also sets these",
      _panels.count("!important") >= 4)
check("panels round to Anki's own container radius, with a fallback",
      "var(--border-radius-medium, 12px)" in _panels)

check("the current/hovered deck row joins the glass instead of punching "
      "an opaque slab through it (Anki fills it with --border-subtle)",
      ".current td," in _panels
      and "tr:hover:not(.top-level-drag-row) td," in _panels
      and "background: var(--klaus-panel-strong) !important;" in _panels)
def _alphas(css, token):
    """Every alpha declared for a token, light palette then night."""
    import re
    return [float(m) for m in
            re.findall(rf"{token}: rgba\([\d, ]+,\s*([\d.]+)\)", css)]


_pa, _sa = _alphas(_panels, "--klaus-panel"), _alphas(_panels,
                                                      "--klaus-panel-strong")
check("...and is MORE opaque than the panel in BOTH palettes — computed "
      "from the emitted alphas, so tweaking the values cannot silently "
      "invert the relationship the user actually asked for",
      len(_pa) == 2 and len(_sa) == 2
      and all(s > p for s, p in zip(_sa, _pa)))
check("the row does NOT stack a second backdrop-filter — the table "
      "beneath it is already a backdrop root, so one blur is enough",
      _panels.count("backdrop-filter") == 2)  # the -webkit- pair, once
check("Anki's RTL rules are more specific than its plain ones, so the "
      "row selector spells the [dir=rtl] variants out to match them",
      "[dir=rtl] .current td," in _panels
      and "[dir=rtl] tr:hover:not(.top-level-drag-row) td {" in _panels)

check("NO frost in colour mode — blurring a flat colour yields that "
      "same colour, so it would cost a compositing layer for nothing",
      bg.panel_css(bg.resolve({"background_mode": "color"})) == "")
check("NO frost in theme mode — Klaus paints no background there at all",
      bg.panel_css(bg.resolve({"background_mode": "theme"})) == "")
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
