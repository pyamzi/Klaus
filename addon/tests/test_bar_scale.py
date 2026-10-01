"""Bar size (``bar_scale``): the top bar, the bottom row and the Qt status
strips scale by one factor, 85% by default, on top of Anki's own User
Interface Size; a slider in Preferences > Appearance sets it.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_bar_scale.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
sys.modules["aqt"].mw = types.SimpleNamespace(onPrefs=lambda: None)

settings = importlib.import_module("klausmate.settings")
dashboard = importlib.import_module("klausmate.dashboard")
theme = importlib.import_module("klausmate.theme")
ps = importlib.import_module("klausmate.prefs_state")
sb = importlib.import_module("klausmate.status_bar")

section("the value: 85 by default, 70-150 in 5s, anything else is the default")
check("the default is 85", dashboard.BAR_SCALE_DEFAULT == 85 and dashboard.bar_scale_from_cfg({}) == 85)
for good in (70, 100, 120, 150):
    check(f"{good} is kept", dashboard.bar_scale_from_cfg({"bar_scale": good}) == good)
for bad in (65, 155, 87, "90", 90.0, True, None, [90]):
    check(f"{bad!r} reads as the default", dashboard.bar_scale_from_cfg({"bar_scale": bad}) == 85)
check("a non-dict config reads as the default", dashboard.bar_scale_from_cfg(None) == 85)
cfg_file = json.load(open("klausmate/config.json"))
check("config.json ships 85", cfg_file.get("bar_scale") == 85)
check("config.md documents it", "**bar_scale**" in open("klausmate/config.md").read())

section("webviews: one CSS zoom on body, composed with Anki's own")
check("85% is body zoom 0.85", theme.bar_zoom_css(85) == "body { zoom: 0.85; }", theme.bar_zoom_css(85))
check("150% is 1.5", "zoom: 1.5;" in theme.bar_zoom_css(150))
check("Anki's Linux webview zoom is multiplied, not replaced", "zoom: 1.7;" in theme.bar_zoom_css(85, 2.0))

tb = importlib.import_module("klausmate.top_bar")
toolbar_mod = types.ModuleType("aqt.toolbar")


class TopToolbar:
    pass


toolbar_mod.TopToolbar = TopToolbar
sys.modules["aqt.toolbar"] = toolbar_mod


class DeckBrowserBottomBar:
    pass


class OverviewBottomBar:
    pass


class ReviewerBottomBar:
    pass


def injected(ctx, cfg=None):
    settings.store = settings.DictStore(cfg or {})
    wc = types.SimpleNamespace(head="", body="")
    tb._on_webview_will_set_content(wc, ctx)
    return wc.head


check("the top bar gets the zoom with the KlausBook design OFF", "zoom: 0.85;" in injected(TopToolbar()))
check("so do the deck and overview rows", "zoom: 0.85;" in injected(DeckBrowserBottomBar())
      and "zoom: 0.85;" in injected(OverviewBottomBar()))
check("the review answer row is left alone", "zoom" not in injected(ReviewerBottomBar()))
check("the stored value is what is drawn", "zoom: 1.2;" in injected(TopToolbar(), {"bar_scale": 120}))
check("with the design ON the zoom still comes once",
      injected(TopToolbar(), {"klausbook_design": True, "bar_scale": 110}).count("zoom: 1.1;") == 1)
settings.store = settings.DictStore({})

br_src = open("klausmate/bottom_row.py").read()
check("the row's readout width is divided by the body zoom (getBoundingClientRect is zoomed)",
      "getComputedStyle(document.body).zoom" in br_src)

section("Qt strips: height, gear and text follow the same factor")
page = QtWidgets.QWidget()
QtWidgets.QVBoxLayout(page).setContentsMargins(0, 0, 0, 0)
page.layout().addWidget(QtWidgets.QTextEdit())
page.resize(800, 400)
page.show()
bar = sb.install_add_tab(page)
app.processEvents()
strip = bar.parentWidget()
check("the default strip is 85% of the 28pt floor (24)", strip.height() == 24 and sb.strip_height() == 24,
      str(strip.height()))
check("the bar inside keeps Qt's insets", bar.height() == 24 - sb.STRIP_INSET)
check("the gear is 85% too", bar.gear.width() == bar.gear.height() == round(22 * 0.85), str(bar.gear.size()))
sb.set_scale(150)
app.processEvents()
check("150%: the strip is 42", strip.height() == 42 and bar.height() == 42 - sb.STRIP_INSET, str(strip.height()))
check("150%: the gear is 33", bar.gear.width() == 33, str(bar.gear.width()))
check("150%: the text is 16px", "font-size: 16px" in strip.styleSheet())
sb.set_row_height(30)
check("a shorter Decks row cannot pull the strip under the scaled floor", strip.height() == 42)
sb.set_row_height(60)
check("a taller Decks row still sets the height", strip.height() == 60)
sb.set_scale(70)
app.processEvents()
check("70%: the cap scales too (64 to 45)", strip.height() == 45, str(strip.height()))
sb.set_row_height(10)
check("70%: the floor is 20, nothing under it", strip.height() == 20 and bar.height() == 15)
check("70%: the gear still fits the bar", bar.gear.height() <= bar.height(), str(bar.gear.height()))
sb.set_scale(85)
check("back to 85: 24", strip.height() == 24)
check("an invalid scale reads as the default", (sb.set_scale(87), strip.height())[1] == 24)

section("Preferences: Appearance carries bar_scale through the one state machine")
st = ps.PrefsState.from_config({})
check("seeded at 85", st.get("bar_scale") == 85)
check("an invalid stored value seeds 85", ps.PrefsState.from_config({"bar_scale": 33}).get("bar_scale") == 85)
st.set("bar_scale", 85)
check("85 again is no edit", not st.dirty)
st.set("bar_scale", 110)
check("the preview config carries the pending size", ps.flatten_appearance(st.view())["bar_scale"] == 110)
c = st.commit()
check("Save writes bar_scale and repaints appearance",
      c.patch.get("bar_scale") == 110 and ("appearance",) in c.effects, str(c))
mm = open("klausmate/manage_models.py").read()
row = mm.split("bar_scale_slider = QSlider")[1].split('_row(appearance_layout, "Bar size"')[0]
check("a Bar size slider on the Appearance page, 70-150 in 5s, with a % readout",
      '_row(appearance_layout, "Bar size", bar_scale_desc, bar_scale_ctl)' in mm
      and "setRange(_dashboard.SCALE_MIN // _dashboard.SCALE_STEP" in row and "}%\")" in row)
check("the caption names Anki's size and links to Anki's Preferences",
      "anki_ui_scale()" in mm.split("bar_scale_slider = QSlider")[0][-400:]
      and "linkActivated.connect(lambda *_a: _status_bar._open_anki_settings())" in row + mm.split("bar_scale_desc.")[1][:200])
check("the readout is painted with the value (setValue(14) on a fresh slider emits nothing)",
      'bar_scale_value_lbl.setText(f"{int(v)}%")' in mm)
check("bound to the state and previewed live", '_Binding(state, "bar_scale"' in mm
      and "bar_scale_slider.valueChanged, appearance_changed" in mm)
check("the strips follow a preview and its revert",
      mm.split("def apply_appearance_live")[1].split("def revert_appearance_preview")[0].count("set_scale(") == 1
      and mm.split("def revert_appearance_preview")[1].split("def appearance_changed")[0].count("set_scale(") == 1)

report()
