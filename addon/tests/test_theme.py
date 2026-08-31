"""Headless tests for klausmate.theme — the design-token module.

theme.py must stay aqt-free at module top (only night_mode() touches aqt,
lazily, degrading to light mode) so every QSS builder is testable here.
"""
import importlib
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
theme = importlib.import_module("klausmate.theme")

section("palette structure")
check("LIGHT and DARK have identical key sets",
      set(theme.LIGHT.keys()) == set(theme.DARK.keys()))
check("light palette returns the light tokens",
      theme.palette(False)["bg"] == "#F5F5F7")
check("dark palette returns the dark tokens",
      theme.palette(True)["bg"] == "#191919")
p = theme.palette(False)
p["bg"] = "mutated"
check("palette() returns a copy — mutation does not leak",
      theme.palette(False)["bg"] == "#F5F5F7")
check("night_mode degrades to light headlessly (stub aqt has no theme)",
      theme.night_mode() in (False, True))  # must not raise

section("QSS builders substitute tokens for both modes")
builders = [
    ("dialog_qss", theme.dialog_qss),
    ("panel_header_qss", theme.panel_header_qss),
    ("find_bar_qss", theme.find_bar_qss),
    ("library_qss", theme.library_qss),
    ("thumb_strip_qss", theme.thumb_strip_qss),
    # The Anki-window builders (window_chrome consumers) join here so
    # every audit below — tokens substituted, background present, the
    # K-110 radius/font design scale — applies to them by construction.
    ("browse_qss", theme.browse_qss),
    ("sidebar_tree_qss", theme.sidebar_tree_qss),
    ("utility_window_qss", theme.utility_window_qss),
    ("editor_tags_qss", theme.editor_tags_qss),
]
for name, fn in builders:
    for night in (False, True):
        qss = fn(night)
        check(f"{name}(night={night}) is a non-empty string",
              isinstance(qss, str) and len(qss) > 50)
        check(f"{name}(night={night}) leaves no unsubstituted token",
              "{c[" not in qss and "{{" not in qss and "}}" not in qss)
        c = theme.palette(night)
        check(f"{name}(night={night}) carries a {['light','dark'][night]} "
              "background token", c["surface"] in qss or c["bg"] in qss)

section("dialog button roles")
d = theme.dialog_qss(False)
check("dialog has a primary (blue) default button",
      "#0071D3" in d and "QPushButton {" in d)
check("dialog defines SecondaryButton", "QPushButton#SecondaryButton" in d)
check("dialog defines DangerButton", "QPushButton#DangerButton" in d)
lib = theme.library_qss(False)
check("library inverts: grey default + PrimaryButton opt-in",
      "QPushButton#PrimaryButton" in lib)
for night in (False, True):
    lq = theme.library_qss(night)
    c = theme.palette(night)
    # The selection fill since K-130: the ACTIVE accent at the
    # SettingsNav alpha. Counting c["selection_bg"] was soft in dark
    # (it equals hover_subtle there, so hover fills padded the count);
    # this rgba string is emitted by the selection rules alone.
    # PRE-COMPOSITED OPAQUE since the offscreen-render pass: rgba
    # composited differently over each paint region's own base.
    _sel_fill = theme.accent_mix(night, 0.16)
    check(f"library_qss(night={night}): a selected row's branch "
          "(indentation/disclosure) cell is recoloured in step with "
          "the item — every row reserves that cell whether or not "
          "it's a folder, and unstyled it painted the raw palette "
          "Highlight colour (the stray blue block, live screenshot "
          "2026-08-30)",
          "QTreeWidget::branch:selected {" in lq
          and lq.count(_sel_fill) >= 2)
    check(f"library_qss(night={night}): the tree's own selection "
          "underlay is switched off, so nothing paints beneath the "
          "branch/item recolouring",
          "selection-background-color: transparent;" in lq)
    # ::item is a per-CELL subcontrol. The Library tree has three columns
    # (PDF / Retention / Cards), so ANY radius here rounds each column's
    # selection box separately and the adjacent corners notch the band at
    # every column boundary — the "bumps" along the highlight (live
    # screenshot, 2026-08-30). Comments are stripped first: the rule
    # carries prose explaining the trap, and the words would satisfy a
    # naive substring check on their own.
    _no_comments = re.sub(r"/\*.*?\*/", "", lq, flags=re.S)
    for sub in ("::item", "::item:hover", "::item:selected"):
        _blk = re.search(
            r"QTreeWidget" + re.escape(sub) + r" \{(.*?)\}", _no_comments, re.S
        )
        check(f"library_qss(night={night}): {sub} carries no border-radius "
              "— per-cell rounding is what notches a multi-column row",
              _blk is not None and "border-radius" not in _blk.group(1))
    check(f"library_qss(night={night}): the selection is still painted "
          "(straightening it must not mean losing it)",
          "QTreeWidget::item:selected {" in lq
          and _sel_fill in lq)

section("library VS Code vernacular (K-117)")
import os as _os  # noqa: E402 — also imported later; harmless rebind

# Pouya: "make it look like the VSCode UI" — the deliberate values:
# compact 22px rows of 13px type, a FLAT borderless tree panel, chevron
# twisties per palette, an uppercase letter-spaced section caption, 11px
# muted column headers, quiet flat (transparent-at-rest) buttons, and
# full-width bands that span the indent column.
for night in (False, True):
    lq = theme.library_qss(night)
    c = theme.palette(night)
    _no_c = re.sub(r"/\*.*?\*/", "", lq, flags=re.S)
    check(f"library_qss(night={night}): the LIBRARY section caption id is "
          "styled as an 11px letter-spaced muted label",
          "QLabel#LibrarySectionHeader" in lq
          and "letter-spacing" in lq
          and "font-size: 11px" in lq.split("QLabel#LibrarySectionHeader", 1)[1][:160])
    _tree_blk = re.search(r"QTreeWidget \{(.*?)\}", _no_c, re.S)
    check(f"library_qss(night={night}): the tree is a FLAT panel — no "
          "border, no card radius (VS Code sidebar, not a rounded card)",
          _tree_blk is not None
          and "border: none" in _tree_blk.group(1)
          and "border-radius" not in _tree_blk.group(1))
    check(f"library_qss(night={night}): hover/selection bands span the "
          "indent column (show-decoration-selected)",
          "show-decoration-selected: 1;" in lq)
    _item_blk = re.search(r"QTreeWidget::item \{(.*?)\}", _no_c, re.S)
    check(f"library_qss(night={night}): compact 22px explorer rows",
          _item_blk is not None and "min-height: 22px" in _item_blk.group(1))
    _closed = "chevron-right-night.svg" if night else "chevron-right-day.svg"
    _crossed = "chevron-right-day.svg" if night else "chevron-right-night.svg"
    _open = "chevron-night.svg" if night else "chevron-day.svg"
    check(f"library_qss(night={night}): closed folder twisty is THIS "
          "palette's right chevron (and not the other palette's)",
          "QTreeWidget::branch:has-children:closed" in lq
          and _closed in lq and _crossed not in lq)
    check(f"library_qss(night={night}): open folder twisty reuses the "
          "existing down chevron for this palette",
          "QTreeWidget::branch:has-children:open" in lq and _open in lq)
    _hdr_blk = re.search(r"QHeaderView::section \{(.*?)\}", _no_c, re.S)
    check(f"library_qss(night={night}): column headers are 11px muted "
          "captions on the tree's own surface",
          _hdr_blk is not None
          and "font-size: 11px" in _hdr_blk.group(1)
          and c["text_muted"] in _hdr_blk.group(1)
          and c["surface"] in _hdr_blk.group(1))
    _btn_blk = re.search(r"QPushButton \{(.*?)\}", _no_c, re.S)
    check(f"library_qss(night={night}): toolbar buttons are quiet flat — "
          "transparent at rest, hover fill only",
          _btn_blk is not None
          and "background-color: transparent" in _btn_blk.group(1)
          and "QPushButton:hover" in lq)
check("the right-chevron assets actually ship in klausmate/web (a QSS "
      "url() to a missing file is silently blank — twisties vanish)",
      _os.path.exists("klausmate/web/chevron-right-day.svg")
      and _os.path.exists("klausmate/web/chevron-right-night.svg"))

section("library chrome HIG pass (K-130)")
# Pouya (screenshot 2026-08-31): Qt painted its stock sort chevron OVER
# the header captions — "Note∧". The cure that SURVIVED offscreen
# probing: real image arrows (web/sort-{up,down}-{day,night}.svg) with
# explicit width/height and DEFAULT placement. Two rejected cures, both
# probed: a zero-size border-triangle subcontrol made Qt compute a
# bogus huge indicator reserve that elided "Notes" at ANY width; and a
# manual centre-right-in-padding position + 16px section reserve
# double-reserved on top of Qt's own metric. A truthfully-sized image
# gives Qt a truthful reserve, and the caption fits.
for night in (False, True):
    lq = theme.library_qss(night)
    c = theme.palette(night)
    _no_c = re.sub(r"/\*.*?\*/", "", lq, flags=re.S)
    for _arrow in ("down-arrow", "up-arrow"):
        _blk = re.search(
            r"QWidget#KlausLibraryWindow QHeaderView::" + _arrow
            + r" \{(.*?)\}", _no_c, re.S)
        check(f"library_qss(night={night}): ::{_arrow} is a real image "
              "with explicit metrics under the Library-window scope — "
              "the zero-size border-triangle made Qt reserve a bogus "
              "huge indicator area and elide every caption",
              _blk is not None
              and "sort-" + _arrow.split("-")[0] + "-" in _blk.group(1)
              and "width: 8px" in _blk.group(1)
              and "height: 5px" in _blk.group(1)
              and "border-top" not in _blk.group(1)
              and "subcontrol-position" not in _blk.group(1))
    _hdr_blk = re.search(r"QHeaderView::section \{(.*?)\}", _no_c, re.S)
    check(f"library_qss(night={night}): ::section padding is symmetric "
          "8px — Qt derives the glyph reserve from the image metrics, "
          "and a manual 16px reserve DOUBLE-reserved (probed: it elided "
          "captions it existed to protect)",
          _hdr_blk is not None
          and "padding: 4px 8px" in _hdr_blk.group(1)
          and "16px" not in _hdr_blk.group(1))
    check(f"library_qss(night={night}): headers are weight-500 "
          "secondary structure (HIG), no longer 600",
          _hdr_blk is not None
          and "font-weight: 500" in _hdr_blk.group(1)
          and "font-weight: 600" not in _hdr_blk.group(1))
    # Selection band (K-130): the ACTIVE accent at the SettingsNav
    # alpha in BOTH paint regions, same fill, full-strength text.
    # PRE-COMPOSITED OPAQUE since the offscreen-render pass: rgba
    # composited differently over each paint region's own base.
    _sel_fill = theme.accent_mix(night, 0.16)
    _item_sel = re.search(
        r"QTreeWidget::item:selected \{(.*?)\}", _no_c, re.S)
    _br_sel = re.search(
        r"QTreeWidget::branch:selected \{(.*?)\}", _no_c, re.S)
    _mix_fill = theme.accent_mix(night, 0.16)
    check(f"library_qss(night={night}): the selection band is the "
          "accent PRE-COMPOSITED OPAQUE (accent_mix), the same ink in "
          "BOTH paint regions, full-strength text on the item — an "
          "rgba fill composited over each region's own base to two "
          "different greys (offscreen renders, 2026-08-31); opaque is "
          "identical everywhere by construction",
          _item_sel is not None and _br_sel is not None
          and _mix_fill in _item_sel.group(1)
          and c["text"] in _item_sel.group(1)
          and _mix_fill in _br_sel.group(1)
          and "rgba" not in _br_sel.group(1))
    check(f"library_qss(night={night}): the two-paint-region trio is "
          "intact — branch recolour + transparent selection underlay "
          "+ show-decoration-selected (drop any one and palette-blue "
          "fragments return at the row edge, CLAUDE.md gotcha)",
          "QTreeWidget::branch:selected {" in lq
          and "selection-background-color: transparent;" in lq
          and "show-decoration-selected: 1;" in lq)
    # Caption buttons: quiet at rest stands (K-117), but with real
    # affordance — hover fill (pinned above), pressed a VISIBLE step
    # past hover in this palette (dark grey_mid == dark hover_subtle,
    # so dark must step to grey_dark), and a focus ring on a
    # pre-reserved transparent border (zero layout jitter).
    _press_blk = re.search(r"QPushButton:pressed \{(.*?)\}", _no_c, re.S)
    check(f"library_qss(night={night}): caption-button pressed fill "
          "is one visible step past the hover fill in this palette",
          _press_blk is not None
          and (c["grey_dark"] if night else c["grey_mid"])
          in _press_blk.group(1)
          and c["hover_subtle"] not in _press_blk.group(1))
    _btn_blk2 = re.search(r"QPushButton \{(.*?)\}", _no_c, re.S)
    check(f"library_qss(night={night}): caption buttons carry a "
          "visible focus ring on a pre-reserved transparent border",
          "QPushButton:focus" in lq
          and c["blue_bright"] in lq.split("QPushButton:focus", 1)[1][:120]
          and _btn_blk2 is not None
          and "border: 1px solid transparent" in _btn_blk2.group(1))

section("settings shell (K-106)")
# The SynapsePro 1.5.x settings language: sidebar + nav pills + row ids.
for night in (False, True):
    d2 = theme.dialog_qss(night)
    for oid in ("QFrame#SettingsSidebar", "QListWidget#SettingsNav",
                "QLabel#PageTitle", "QLabel#PageSubtitle",
                "QLabel#SettingName", "QLabel#SettingDesc",
                "QFrame#RowSeparator", "QFrame#ButtonBarLine",
                "QLabel#SidebarAppName", "QLabel#SidebarVersion"):
        check(f"dialog_qss(night={night}) styles {oid}", oid in d2)
d2 = theme.dialog_qss(False)
check("selected nav pill is the blue accent with white text",
      "QListWidget#SettingsNav::item:selected" in d2
      and d2.index("QListWidget#SettingsNav::item:hover")
      < d2.index("QListWidget#SettingsNav::item:selected"))
check("sidebar wordmark is set in Garamond, like Claude's",
      "Garamond" in theme.dialog_qss(False)
      and "QLabel#SidebarAppName" in theme.dialog_qss(False))
check("settings search field is styled in both palettes",
      all("QLineEdit#SettingsSearch" in theme.dialog_qss(n)
          for n in (False, True)))
check("no NavItem button styling survives — the nav is one list",
      "NavItem" not in theme.dialog_qss(False))
# Combos read as pickers, not dead line-edits (2026-08-30, Pouya:
# "make the dropdowns look better"): QSS draws NO arrow once
# ::drop-down is styled, so a real chevron must ship as a file.
check("dialog combos carry a real chevron per palette, a hover "
      "state, and a rounded padded popup with item selection",
      "chevron-day.svg" in theme.dialog_qss(False)
      and "chevron-night.svg" in theme.dialog_qss(True)
      and "chevron-night.svg" not in theme.dialog_qss(False)
      and "QComboBox:hover" in theme.dialog_qss(False)
      and "QComboBox::down-arrow" in theme.dialog_qss(False)
      and "QComboBox QAbstractItemView::item" in theme.dialog_qss(False))
import os as _os  # noqa: E402

check("both chevron assets actually ship in klausmate/web (a QSS "
      "url() to a missing file is silently blank — back to no arrow)",
      _os.path.exists("klausmate/web/chevron-day.svg")
      and _os.path.exists("klausmate/web/chevron-night.svg"))

section("colour themes (K-107 — SynapsePro's accent presets)")
BLUE_KEYS = {"blue", "blue_hover", "blue_pressed", "blue_border",
             "blue_bright", "blue_accent"}
check("every preset ships light AND dark override sets — "
      "SynapsePro's six, the community palettes, and Claude",
      set(theme.COLOR_THEMES) == {
          "ocean", "orchid", "forest", "deluge", "horizon", "dusty",
          "nord", "solarized", "catppuccin", "gruvbox", "everforest",
          "dracula", "claude"}
      and all(set(t) == {False, True}
              and set(t[False]) == BLUE_KEYS == set(t[True])
              for t in theme.COLOR_THEMES.values()))
check("community presets carry their canonical colours",
      theme.COLOR_THEMES["nord"][False]["blue"] == "#5E81AC"
      and theme.COLOR_THEMES["nord"][True]["blue_bright"] == "#88C0D0"
      and theme.COLOR_THEMES["dracula"][True]["blue_bright"] == "#BD93F9"
      and theme.COLOR_THEMES["gruvbox"][True]["blue_bright"] == "#FE8019"
      and theme.COLOR_THEMES["catppuccin"][True]["blue_bright"] == "#CBA6F7"
      and theme.COLOR_THEMES["claude"][False]["blue"] == "#D97757")
check("a palette's canonical dark bright is also its dark accent",
      all(theme.COLOR_THEMES[n][True]["blue_accent"]
          == theme.COLOR_THEMES[n][True]["blue_bright"]
          for n in ("nord", "dracula", "claude", "solarized")))
check("only blue-family tokens are overridden — backgrounds and text "
      "always come from the base palettes",
      all(k.startswith("blue") for t in theme.COLOR_THEMES.values()
          for n in (False, True) for k in t[n]))
check("default theme is ocean and matches the base palette",
      theme.get_active_theme() == "ocean"
      and theme.palette(False)["blue"] == "#0071D3")
check("blue_accent = blue in light, blue_bright in dark (ocean)",
      theme.palette(False)["blue_accent"] == theme.palette(False)["blue"]
      and theme.palette(True)["blue_accent"]
      == theme.palette(True)["blue_bright"])
theme.set_active_theme("orchid")
check("set_active_theme overlays every later palette() call",
      theme.get_active_theme() == "orchid"
      and theme.palette(False)["blue"] == "#E95ACC"
      and theme.palette(True)["blue_accent"] == "#FCABEC")
check("the overlay reaches the QSS builders too",
      "#E95ACC" in theme.dialog_qss(False))
check("non-blue tokens are untouched by a theme switch",
      theme.palette(False)["bg"] == theme.LIGHT["bg"]
      and theme.palette(True)["surface"] == theme.DARK["surface"])
theme.set_active_theme("no-such-theme")
check("unknown names are ignored, not crashed on",
      theme.get_active_theme() == "orchid")
theme.set_active_theme("ocean")  # reset — later checks assume the default
check("reset back to ocean for the rest of the suite",
      theme.palette(False)["blue"] == "#0071D3")

section("custom accent colour (K-108)")
check("hex validation accepts #rgb and #rrggbb, rejects the rest",
      theme.is_hex_colour("#abc") and theme.is_hex_colour("#0071D3")
      and not theme.is_hex_colour("red")
      and not theme.is_hex_colour("#gg0011")
      and not theme.is_hex_colour("") and not theme.is_hex_colour(None))
_ov = theme.custom_overrides("#0071D3", False)
check("one colour derives the whole blue family",
      set(_ov) == BLUE_KEYS and _ov["blue"] == "#0071D3")
check("derived tones land near SynapsePro's hand-tuned ocean values",
      _ov["blue_hover"] == "#0066BE" and _ov["blue_pressed"] == "#004F94")
check("hover is darker than base, pressed darker than hover",
      _ov["blue_pressed"] < _ov["blue_hover"] < _ov["blue"])
_ovd = theme.custom_overrides("#0071D3", True)
check("dark mode lifts the bright tone further than light does",
      _ovd["blue_bright"] > _ov["blue_bright"])
check("border follows the preset rule: none in light, pressed in dark",
      _ov["blue_border"] == "none"
      and _ovd["blue_border"] == f"1px solid {_ovd['blue_pressed']}")
check("accent = base in light, bright in dark (same as every preset)",
      _ov["blue_accent"] == "#0071D3"
      and _ovd["blue_accent"] == _ovd["blue_bright"])
check("a fully saturated colour still brightens (mix toward white, "
      "not a channel scale)",
      theme.custom_overrides("#FF0000", True)["blue_bright"] != "#FF0000")
check("garbage falls back to the default instead of blanking the accent",
      theme.custom_overrides("nonsense", False)["blue"]
      == theme.DEFAULT_CUSTOM_COLOR)
theme.set_custom_colour("#E95ACC")
theme.set_active_theme("custom")
check("custom is selectable and reaches palette() + the QSS builders",
      theme.get_active_theme() == "custom"
      and theme.palette(False)["blue"] == "#E95ACC"
      and "#E95ACC" in theme.dialog_qss(False))
theme.set_custom_colour("not-a-colour")
check("an invalid colour is ignored, keeping the last good one",
      theme.get_custom_colour() == "#E95ACC")
theme.set_active_theme("ocean")
theme.set_custom_colour(theme.DEFAULT_CUSTOM_COLOR)
check("reset to ocean/default for the rest of the suite",
      theme.palette(False)["blue"] == "#0071D3")

section("disabled states are visible (K-108)")
# An id selector outranks a pseudo-state one, so every :disabled rule
# must repeat the id it has to beat — that specificity loss is exactly
# why disabled Appearance controls looked fully live.
for night in (False, True):
    d4 = theme.dialog_qss(night)
    for sel in ("QPushButton#SecondaryButton:disabled",
                "QPushButton#DangerButton:disabled",
                "QComboBox:disabled", "QLineEdit:disabled",
                "QSlider::groove:horizontal:disabled",
                "QSlider::handle:horizontal:disabled",
                "QLabel#SettingName:disabled",
                "QLabel#SettingDesc:disabled",
                "QCheckBox::indicator:disabled"):
        check(f"dialog_qss(night={night}) has {sel}", sel in d4)
d4 = theme.dialog_qss(False)
check("disabled text uses the faint token, not the live one",
      theme.LIGHT["text_faint"] in d4.split("QLabel:disabled", 1)[1][:200])

section("widget polish (K-107): progress, slider, list")
for night in (False, True):
    d3 = theme.dialog_qss(night)
    for sel in ("QProgressBar", "QProgressBar::chunk",
                "QSlider::groove:horizontal", "QSlider::handle:horizontal",
                "QSlider::sub-page:horizontal",
                "QListWidget", "QListWidget::item:selected"):
        check(f"dialog_qss(night={night}) styles {sel}", sel in d3)

section("drop zone + helpers")
dz = theme.drop_zone_qss(False, "klausmateLibraryDropZone")
check("drop zone scopes rules to the given objectName",
      "#klausmateLibraryDropZone {" in dz
      and '#klausmateLibraryDropZone[dragOver="true"]' in dz)
check("drop zone styles its Browse button",
      "#klausmateLibraryDropZone QPushButton" in dz)
check("accent_rgba light = system blue with alpha",
      theme.accent_rgba(False, 0.3) == "rgba(0, 122, 255, 0.3)")
check("accent_rgba dark = bright dark-mode accent",
      theme.accent_rgba(True, 0.85) == "rgba(79, 172, 254, 0.85)")
m = theme.muted_label_qss(False, 10)
check("muted label carries text_muted + size",
      theme.LIGHT["text_muted"] in m and "font-size: 10px" in m)

section("webview vars (css_vars): the palette mirrored into :root")
# The one surface that reads theme tokens as CSS instead of QSS —
# web/pdfjs_viewer.html's __THEME_VARS__ substitution. Every var the
# page hands to var() must be emitted here or those declarations
# compute to nothing.
WEB_VARS = ("bg", "surface", "text", "text-muted", "grey-light",
            "grey-mid", "hover-subtle", "accent", "accent-selection",
            "font")
for night in (False, True):
    cv = theme.css_vars(night)
    c = theme.palette(night)
    check(f"css_vars(night={night}) leaves no unsubstituted token",
          "{c[" not in cv and "{{" not in cv and "}}" not in cv)
    missing = [v for v in WEB_VARS if f"--{v}: " not in cv]
    check(f"css_vars(night={night}) emits every var the page reads "
          f"(missing: {missing})", not missing)
    # --hover-subtle went undefined here once: the findbar, annobar,
    # context menu and thumbnail strip all hover with it, and K-116
    # had to ship a neutral in-page fallback because an undefined
    # var() paints nothing. It is now the SAME palette token the
    # Qt-side builders hover with, so the webview half of that family
    # cannot drift from its widget half — and the page's fallback is
    # a safety net, never the definition.
    check(f"css_vars(night={night}) takes --hover-subtle from the "
          "palette token, not a hand-mixed neutral",
          f"--hover-subtle: {c['hover_subtle']};" in cv)
    check(f"css_vars(night={night}): that is the fill find_bar_qss "
          "and thumb_strip_qss hover their Qt siblings with",
          c["hover_subtle"] in theme.find_bar_qss(night)
          and c["hover_subtle"] in theme.thumb_strip_qss(night))
check("light and dark hover fills actually differ (a single baked "
      "neutral would pass every check above)",
      theme.LIGHT["hover_subtle"] != theme.DARK["hover_subtle"])

section("design scale (K-110): every builder stays on-scale")
# Sanctioned sets — must match the "Design scale" comment block above
# theme.dialog_qss. This scans the ACTUAL emitted CSS of every QSS/CSS
# builder in the module (not just dialog_qss's known ids) so an
# off-scale border-radius or font-size anywhere fails the suite the
# moment it lands, not just the two outliers this card fixed (the
# checkbox indicator's 5px and the drop-zone's 10px).
RADIUS_SCALE = {0, 2, 4, 6, 7, 8, 12}
FONT_SIZE_SCALE = {10, 11, 12, 13, 14, 18, 24}
# border-radius: 0 ships bare (no "px") as a flattener — see toolbar_css
# — so the unit is optional; font-size always ships with "px".
RADIUS_RE = re.compile(r"border-radius:\s*(\d+)(?:px)?")
FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")

scale_builders = builders + [
    ("drop_zone_qss",
     lambda night: theme.drop_zone_qss(night, "ScaleAuditDropZone")),
    ("toolbar_css", lambda night: theme.toolbar_css()),
    ("bottombar_css", lambda night: theme.bottombar_css()),
    ("reviewer_bar_css", lambda night: theme.reviewer_bar_css()),
    ("editor_css", lambda night: theme.editor_css()),
    ("stats_css", lambda night: theme.stats_css()),
]
for name, fn in scale_builders:
    for night in (False, True):
        css = fn(night)
        radii = {int(v) for v in RADIUS_RE.findall(css)}
        sizes = {int(v) for v in FONT_SIZE_RE.findall(css)}
        off_radii = sorted(radii - RADIUS_SCALE)
        off_sizes = sorted(sizes - FONT_SIZE_SCALE)
        check(f"{name}(night={night}) border-radius values are all in "
              f"the sanctioned set {sorted(RADIUS_SCALE)} "
              f"(off-scale: {off_radii})",
              not off_radii)
        check(f"{name}(night={night}) font-size values are all in the "
              f"sanctioned set {sorted(FONT_SIZE_SCALE)} "
              f"(off-scale: {off_sizes})",
              not off_sizes)
check("muted_label_qss's default size is on-scale",
      int(FONT_SIZE_RE.search(theme.muted_label_qss(False)).group(1))
      in FONT_SIZE_SCALE)
check("dialog_qss documents the K-111 install-page ids on-scale",
      "QLabel#InstallHeading {" in theme.dialog_qss(False)
      and "font-size: 14px" in theme.dialog_qss(False).split(
          "QLabel#InstallHeading", 1)[1][:40]
      and "QLabel#InstallSection {" in theme.dialog_qss(False)
      and "margin-top: 8px"
      in theme.dialog_qss(False).split("QLabel#InstallSection", 1)[1][:80])

raise SystemExit(report())
