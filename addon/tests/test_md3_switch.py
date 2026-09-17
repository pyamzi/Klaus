"""Headless tests for the MD3 track-and-thumb switch (K-material3).

Painting/animation can't run headlessly (Qt widgets are never
constructed for real in this harness — see the klaus-test bootstrap's
own docstring), so this exercises the pure geometry/colour math at
module top plus source pins for the parts that only a running Qt event
loop could verify.
"""
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

sw = importlib.import_module("klausmate.md3_switch")
theme = importlib.import_module("klausmate.theme")

section("thumb geometry: grows and slides together")
check("unchecked thumb is the small MD3 dot",
      sw.thumb_diameter(0.0) == sw.THUMB_OFF_D)
check("checked thumb is the larger MD3 dot",
      sw.thumb_diameter(1.0) == sw.THUMB_ON_D)
check("diameter is monotonically non-decreasing across progress",
      all(sw.thumb_diameter(i / 10) <= sw.thumb_diameter((i + 1) / 10)
          for i in range(10)))
check("out-of-range progress is clamped, not extrapolated",
      sw.thumb_diameter(-5.0) == sw.THUMB_OFF_D
      and sw.thumb_diameter(5.0) == sw.THUMB_ON_D)

check("unchecked thumb sits left-of-centre, centred in its margin",
      sw.thumb_center_x(0.0) == sw.THUMB_MARGIN + sw.THUMB_OFF_D / 2.0)
check("checked thumb sits right-of-centre, centred in its margin",
      sw.thumb_center_x(1.0)
      == sw.TRACK_W - sw.THUMB_MARGIN - sw.THUMB_ON_D / 2.0)
check("the thumb travels strictly rightward as progress increases",
      all(sw.thumb_center_x(i / 10) < sw.thumb_center_x((i + 1) / 10)
          for i in range(10)))
check("checked position never overruns the track",
      sw.thumb_center_x(1.0) + sw.THUMB_ON_D / 2.0 <= sw.TRACK_W)

check("the three pill strokes (fill 0 / outline 0.5 / ring 1.0) come "
      "from ONE formula and stay concentric — same centre at every inset",
      all(
          (x + w / 2.0, y + h / 2.0)
          == (sw.TRACK_W / 2.0, 2.0 + sw.TRACK_H / 2.0)
          for x, y, w, h, _r in
          (sw.pill_rect(i) for i in (0.0, 0.5, 1.0))
      ))
check("pill radius is always the half-height (a true capsule end)",
      all(sw.pill_rect(i)[4] == sw.pill_rect(i)[3] / 2.0
          for i in (0.0, 0.5, 1.0)))

section("colour interpolation: the track crossfades, it doesn't snap")
check("progress 0 is exactly the off colour",
      sw._lerp_hex("#000000", "#FFFFFF", 0.0) == "#000000")
check("progress 1 is exactly the on colour",
      sw._lerp_hex("#000000", "#FFFFFF", 1.0) == "#FFFFFF")
check("progress 0.5 is the true midpoint",
      sw._lerp_hex("#000000", "#FFFFFF", 0.5) == "#808080")
check("out-of-range t is clamped",
      sw._lerp_hex("#000000", "#FFFFFF", -1.0) == "#000000"
      and sw._lerp_hex("#000000", "#FFFFFF", 2.0) == "#FFFFFF")

# The REAL light palette, not a hand-copied fixture — theme.py is the
# single source of truth for these tokens, and a copy here would keep
# passing against values production no longer uses.
_LIGHT = theme.LIGHT
check("track_color reaches the accent token, not a fixed blue — a "
      "theme switch must recolour this control too",
      sw.track_color(_LIGHT, 1.0) == _LIGHT["blue_accent"])
check("thumb_color reaches white ON, grey_dark OFF",
      sw.thumb_color(_LIGHT, 1.0) == "#FFFFFF"
      and sw.thumb_color(_LIGHT, 0.0) == _LIGHT["grey_dark"])
check("disabled track never claims a third colour — it's the current "
      "state, washed out, not a distinct disabled hue",
      sw.disabled_track_color(_LIGHT, True) == _LIGHT["blue_accent"]
      and sw.disabled_track_color(_LIGHT, False) == _LIGHT["grey_light"])
check("disabled thumb follows the same endpoint rule — surface off, "
      "white on — via its own tested function, not inline paint logic",
      sw.disabled_thumb_color(_LIGHT, True) == "#FFFFFF"
      and sw.disabled_thumb_color(_LIGHT, False) == _LIGHT["surface"])

section("module imports aqt-free logic without a live Qt session")
check("Md3Switch is defined and importable under the stub harness",
      hasattr(sw, "Md3Switch"))
_SRC = open("klausmate/md3_switch.py").read()
_CODE = code_only(_SRC)
check("no UI file hardcodes colour — every fill routes through "
      "theme.palette(), never a literal hex swatch for track/thumb",
      "theme.palette(" in _SRC
      and _SRC.count('QColor("#') == 0)
check("checked-state bookkeeping is 100% inherited from QCheckBox — "
      "isChecked/setChecked/toggled are never shadowed",
      "def isChecked" not in _SRC
      and "def setChecked" not in _SRC
      and "def toggled" not in _SRC)
check("clicking anywhere on the widget toggles it (no style-computed "
      "indicator rect to miss, since paintEvent draws no native one)",
      "def hitButton" in _SRC and "self.rect().contains(pos)" in _SRC)
check("animation uses MD3's standard 200ms duration",
      "setDuration(200)" in _SRC)

section("paint safety — the nine-crash regression (macOS 26 + Qt 6.11)")
# Bisected with a staged live probe: bare dialog fine, + our stylesheet
# fine, + ONE Md3Switch crashed. The dialog calls setChecked() while
# building, which fired toggled -> started the animation -> repainted
# the switch while the window was still being composited, and Qt's
# backing-store flush hit a paint device that did not exist yet.
check("an off-screen switch JUMPS to its state instead of animating — "
      "setChecked() during dialog build must not start a repaint loop "
      "(the jump goes through _set_progress, whose visible-only update "
      "the next pin holds; Reduce Motion shares the same jump branch)",
      "if not self.isVisible() or _reduce_motion():" in _CODE
      and "self._set_progress(target)" in _CODE
      and "self._anim.start()" in _CODE)
check("the animated property only repaints once on screen",
      "if self.isVisible():\n            self.update()" in _SRC)
check("paint bails out when the widget has no surface yet",
      "if self.width() <= 0 or self.height() <= 0:" in _SRC)
# Shared helper: prose must never be able to satisfy or break a pin.
check("the pin below reads real code, not prose — docstrings and "
      "comments are stripped, so a described call cannot fake a pass",
      "painter.end()" in _CODE and "nine-crash" not in _CODE)
check("painter.end() is guaranteed by finally, and is not also called "
      "inline (a double-end or a leaked painter both corrupt the "
      "backing store)",
      "finally:" in _CODE
      and _CODE.count("painter.end()") == 1)
check("a drawing bug cannot escape paintEvent — it is caught, so a "
      "future overload slip degrades to 'did not draw', not a segfault",
      "except Exception as exc:" in _CODE
      and "MD3 switch paint failed" in _SRC)

# PyQt6 overload reality (from the live TypeError, 2026-08-26): the only
# float-coordinate form of drawRoundedRect takes a QRectF, and the
# positional x,y,w,h form is int-ONLY. This widget passed floats
# positionally from the day it shipped, so it raised on EVERY paint and
# never once rendered — the escaping exception is what corrupted the
# backing store. Same trap on drawEllipse.
check("drawRoundedRect is handed a QRectF, never bare float coordinates",
      "drawRoundedRect(QRectF(" in _CODE
      and "drawRoundedRect(x," not in _CODE)
check("drawEllipse uses the QPointF-centre overload, not float x,y,w,h",
      "drawEllipse(QPointF(" in _CODE
      and "drawEllipse(float(" not in _CODE)
check("QRectF and QPointF are imported, or the draw calls above are "
      "NameErrors at paint time",
      "QRectF," in _SRC and "QPointF," in _SRC)
check("all three pill strokes go through the ONE _pill helper, so the "
      "QRectF rule is enforced in a single place",
      _CODE.count("self._pill(painter,") == 3
      and _CODE.count("drawRoundedRect") == 1)
check("keyboard focus gets its own ring — paintEvent bypasses QStyle "
      "entirely, so the shared QPushButton:focus rule can't reach here",
      "self.hasFocus()" in _SRC and 'c["blue_bright"]' in _SRC)

section("reduce motion")
check("the switch honours Anki's Reduce Motion preference — the jump "
      "branch covers it alongside the off-screen case, and BOTH go "
      "through _set_progress (which repaints only when visible)",
      "def _reduce_motion" in _SRC
      and "if not self.isVisible() or _reduce_motion():" in _CODE
      and "self._set_progress(target)" in _CODE)
check("...and reads it through aqt guarded, so headless tests and a "
      "missing preference read as motion-on, never a crash",
      "mw.pm.reduce_motion()" in _SRC
      and "except Exception:" in _SRC.split("def _reduce_motion")[1].split("class Md3Switch")[0])

section("manage_models.py wiring")
_MM = open("klausmate/manage_models.py").read()
check("from .md3_switch import Md3Switch",
      "from .md3_switch import Md3Switch" in _MM)
# Stated as a RULE, not a head count. This pin used to assert
# `== 3`, which meant every new preference toggle broke it and got
# "fixed" by bumping the number — a pin nobody reads is a pin that
# stops catching the thing it was written for. Read the toggles out of
# the source instead, so a QCheckBox slipping back in fails loudly and
# a fourth switch does not.
_MM_CODE = code_only(_MM)
_TOGGLES = dict(re.findall(r"(\w+_cb) = (\w+)\(", _MM_CODE))
check("every Preferences toggle is an Md3Switch, whatever their number",
      len(_TOGGLES) >= 4
      and set(_TOGGLES.values()) == {"Md3Switch"},
      str(sorted(_TOGGLES.items())))
check("the toggles that predate live appearance preview still only "
      "mark_dirty(), so Save stays the sole writer",
      all(f"{name}.toggled.connect(lambda _checked: mark_dirty())" in _MM_CODE
          for name in ("image_crop_cb", "pdfjs_cb")))
check("...and the appearance one (the design master switch — the "
      "heatmap switch left Preferences 2026-08-30) routes through "
      "on_design_toggled → appearance_changed(): marks dirty AND "
      "previews live, same deferred save",
      "klausbook_cb.toggled.connect(on_design_toggled)" in _MM_CODE
      and "heatmap_cb" not in _MM_CODE)

section("theme.py: caption contrast fix (MD3 audit accessibility finding)")
def _luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    chans = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        c = c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        chans.append(c)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


check("LIGHT text_muted clears WCAG AA (4.5:1) against the page ground",
      _contrast(theme.LIGHT["text_muted"], theme.LIGHT["bg"]) >= 4.5)
check("LIGHT text_muted clears WCAG AA against white cards too",
      _contrast(theme.LIGHT["text_muted"], theme.LIGHT["surface"]) >= 4.5)
check("DARK text_muted still clears WCAG AA (was already passing)",
      _contrast(theme.DARK["text_muted"], theme.DARK["bg"]) >= 4.5)
check("the old failing value is gone from the light palette",
      theme.LIGHT["text_muted"] != "#86868B")

raise SystemExit(report())
