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

raise SystemExit(report())
