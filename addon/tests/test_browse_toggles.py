"""Headless tests for the Browse pane toggles (sidebar / card editor).

Qt widgets are never constructed for real in this harness (see the
klaus-test bootstrap's own docstring), so this exercises the pure icon
geometry and copy at module top, plus source pins for the parts only a
running Qt event loop could show.

The pins matter more than usual here: this control is SELF-PAINTED, so it
bypasses QStyle and QSS entirely — the shared rules that keep every other
Klaus control honest (theme colours, focus rings, the Md3Switch crash
rules) cannot reach it, and have to be re-asserted by hand.
"""
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

bt = importlib.import_module("klausmate.browse_toggles")

_SRC = open("klausmate/browse_toggles.py").read()
_CODE = code_only(_SRC)

BOX = bt.ICON_BOX
X, Y, W, H, R = bt.frame_rect(BOX)
HALF = bt.stroke_width(BOX) / 2.0
EPS = 1e-9

section("the frame: a window outline that fits its own box")
check("stroke stays inside the box on the left", X - HALF > 0)
check("... and on the right", X + W + HALF < BOX)
check("... and at the top", Y - HALF > 0)
check("... and at the bottom", Y + H + HALF < BOX)
check("wider than it is tall, the way a window is", W > H)
check("corner radius never exceeds half the short side", R <= H / 2.0)

section("the divider: inside the frame, and a true mirror")
DL = bt.divider_x(BOX, "left")
DR = bt.divider_x(BOX, "right")
check("left variant's rule sits inside the frame", X < DL < X + W)
check("right variant's rule sits inside the frame", X < DR < X + W)
check("left rule is left of centre", DL < X + W / 2.0)
check("right rule is right of centre", DR > X + W / 2.0)
check(
    "the two are exact mirrors about the frame's centre",
    abs((DL - X) - ((X + W) - DR)) < EPS,
)

section("the pane fill: inside the outline, never straddling it")
for side, d in (("left", DL), ("right", DR)):
    px, py, pw, ph = bt.pane_rect(BOX, side)
    check(f"{side}: fill has real area", pw > 0 and ph > 0)
    check(f"{side}: clears the frame's top stroke", py >= Y + HALF - EPS)
    check(f"{side}: clears the bottom stroke", py + ph <= Y + H - HALF + EPS)
    if side == "left":
        check("left: starts at the frame's inner edge", abs(px - (X + HALF)) < EPS)
        check("left: stops at the divider", abs((px + pw) - (d - HALF)) < EPS)
    else:
        check("right: starts at the divider", abs(px - (d + HALF)) < EPS)
        check(
            "right: stops at the frame's inner edge",
            abs((px + pw) - (X + W - HALF)) < EPS,
        )

section("the inner region: a fill can't escape the rounded frame")
IX, IY, IW, IH, IR = bt.frame_inner_rect(BOX)
check("inner rect sits inside the frame centreline", IX > X and IY > Y)
check("... on both far edges too", IX + IW < X + W and IY + IH < Y + H)
check("inset is exactly half a stroke", abs(IX - (X + HALF)) < EPS)
check("inner radius shrinks with the inset, staying concentric",
      abs(IR - (R - HALF)) < EPS)
check("radius can never go negative on a thick stroke",
      bt.frame_inner_rect(2.0)[4] >= 0.0)
for side in ("left", "right"):
    px, py, pw, ph = bt.pane_rect(BOX, side)
    check(f"{side}: fill is inside the inner region horizontally",
          px >= IX - EPS and px + pw <= IX + IW + EPS)
    check(f"{side}: and vertically", py >= IY - EPS and py + ph <= IY + IH + EPS)

section("it reads as a sidebar, not a split view")
_, _, PW, PH = bt.pane_rect(BOX, "left")
check("the filled column is under half the frame's width", PW < W / 2.0)
check("and is taller than it is wide", PH > PW)

section("one 16-unit grid serves every size and device pixel ratio")
for s in (12.0, 16.0, 24.0, 32.0, 64.0):
    k = s / BOX
    check(
        f"frame at {s:g}px is the grid scaled",
        all(
            abs(a - b * k) < EPS
            for a, b in zip(bt.frame_rect(s), bt.frame_rect(BOX))
        ),
    )
    check(f"stroke at {s:g}px scales with it", abs(bt.stroke_width(s) - bt.STROKE * k) < EPS)
    for side in ("left", "right"):
        check(
            f"{side} fill at {s:g}px scales with it",
            all(
                abs(a - b * k) < EPS
                for a, b in zip(bt.pane_rect(s, side), bt.pane_rect(BOX, side))
            ),
        )

section("copy names the RESULT, the way macOS's own View menu does")
check("a showing sidebar offers to hide it", bt.toggle_label("sidebar", True) == "Hide Sidebar")
check("a hidden sidebar offers to show it", bt.toggle_label("sidebar", False) == "Show Sidebar")
check("the editor pane is named 'Card Editor'", bt.toggle_label("editor", True) == "Hide Card Editor")
check("an unknown pane still yields a sentence", bt.toggle_label("nope", False) == "Show Pane")
check(
    "every label is title case, per the copy glossary",
    all(
        word[:1].isupper()
        for pane in ("sidebar", "editor")
        for vis in (True, False)
        for word in bt.toggle_label(pane, vis).split()
    ),
)

section("state never rides on colour alone")
check("the ON state fills the pane column", "pane_rect(" in _CODE)
check("... with a real fill call", "drawRect(" in _CODE)
check("the OFF state is outline-only (fill is guarded by `on`)", "if on:" in _CODE)
check("the fill is clipped to the frame's rounded inner edge",
      "setClipPath(" in _CODE and "frame_inner_rect(" in _CODE)
check("the clip is scoped, not left on the painter",
      re.search(r"painter\.save\(\)[\s\S]{0,300}?painter\.setClipPath\("
                r"[\s\S]{0,300}?painter\.restore\(\)", _CODE) is not None)

section("the bordered box is gone — that was the whole complaint")
check("no stylesheet is set on the toggle at all", "setStyleSheet" not in _CODE)
check("no border rule survives anywhere", "border" not in _CODE)
check("no ◧/◨ text glyphs remain", "◧" not in _CODE and "◨" not in _CODE)
check("nothing calls setText — it is an icon now, not a character", "setText(" not in _CODE)

section("no invented colours (the addon's standing rule)")
# Deliberately the RAW source, not _CODE: code_only() strips string
# literals along with comments, and a hex colour in Python is ALWAYS a
# string literal — so this pin read against _CODE could never see the one
# failure mode it exists to catch. (Caught by mutation-testing it.)
check("no literal hex colour anywhere", not re.search(r"#[0-9A-Fa-f]{6}", _SRC))
check("hues come from the palette", "theme.palette(" in _CODE)
check("tints come from the live accent", "accent_rgba(" in _CODE)
check("night mode is read, never baked", "night_mode()" in _CODE)

section("the crash rules Md3Switch already paid for")
check(
    "the painter is closed in a finally",
    re.search(r"finally:\s*\n\s*painter\.end\(\)", _CODE) is not None,
)
_DRAWS = re.findall(r"draw(?:RoundedRect|Rect|Line)\(\s*([A-Za-z_][A-Za-z0-9_]*)", _CODE)
check("there are draw calls to check at all", len(_DRAWS) >= 4)
check(
    "every float draw call passes a Q*F object, never positional floats",
    all(d in ("QRectF", "QPointF", "QLineF") for d in _DRAWS),
)
check(
    "a zero-sized widget is refused before painting",
    "self.width() <= 0" in _CODE,
)
check("paint failures degrade to a log line", "pane toggle paint failed" in _SRC)

section("HIG: targets, focus, names, direction")
check("the button meets HIG's 28pt pointer target", bt.BUTTON_SIZE >= 28)
check("the icon has breathing room inside it", bt.ICON_SIZE < bt.BUTTON_SIZE)
check(
    "the chip radius is on the documented 12/8/6 scale",
    bt.CHIP_RADIUS in (12.0, 8.0, 6.0),
)
check("an accessible name is set, not just a tooltip", "setAccessibleName(" in _CODE)
check(
    "labels re-sync on programmatic flips too, not only clicks",
    "toggled.connect(self._sync_copy)" in _CODE,
)
check("keyboard focus is reachable", "StrongFocus" in _CODE)
check(
    "and visible — a self-painted widget must draw its own ring",
    "hasFocus()" in _CODE,
)
check("the icon mirrors in RTL, following the grid", "isRightToLeft()" in _CODE)
check(
    "hover/focus repaints are asked for explicitly, since QStyle is bypassed",
    all(m in _CODE for m in ("enterEvent", "leaveEvent", "focusInEvent", "focusOutEvent")),
)

section("this surface is not gated — it must survive native mode")
check(
    "no klausbook_design gate reaches the toggles",
    "klausbook_design" not in _CODE,
)

raise SystemExit(report())
