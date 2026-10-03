"""A background image whose filename has ', #, ? or % still renders (#26):
image_url percent-encodes the name, so the single-quoted CSS url() stays
well formed and the rules after it survive.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_background_image_url.py
"""
import importlib
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
bg = importlib.import_module("klaus_note.background")

PREFIX = "/_addons/klaus_note/user_files/backgrounds/"
NAME = "Desk's view #2?.jpg"

section("image_url encodes the filename segment")
url = bg.image_url("klaus_note", NAME)
seg = url[len(PREFIX):]
check("prefix unchanged", url.startswith(PREFIX), url)
check("no ', #, ? or raw space in the filename segment",
      not any(c in seg for c in "'#? "), seg)
check("% itself is encoded, never a broken escape",
      bg.image_url("klaus_note", "100% wall.png") == PREFIX + "100%25%20wall.png",
      bg.image_url("klaus_note", "100% wall.png"))
check("plain names are unchanged",
      bg.image_url("klaus_note", "desk.jpg") == PREFIX + "desk.jpg"
      and bg.image_url("klaus_note", "IMG_1234.JPG") == PREFIX + "IMG_1234.JPG")


def well_formed(css: str, url: str) -> bool:
    return (len(re.findall(r"url\('", css)) == 1 and f"url('{url}') !important;" in css
            and css.count("'") % 2 == 0)


section("main_css and reviewer_css stay intact")
deck = bg.resolve({"background_mode": "image", "background_image": NAME})
css = bg.main_css(deck, url)
check("main_css: exactly one well-formed url('…')", well_formed(css, url), css[:300])
check("main_css: the rules after it are intact",
      "body { background: transparent !important; }" in css and "--klaus-panel:" in css)
study = bg.resolve({"reviewer_background_mode": "image", "reviewer_background_image": NAME},
                   prefix="reviewer_background")
rcss = bg.reviewer_css(study, url)
check("reviewer_css: exactly one well-formed url('…')", well_formed(rcss, url), rcss[:300])
check("reviewer_css: the rules after it are intact",
      rcss.index("url(") < rcss.index("background-position: center top"))

raise SystemExit(report())
