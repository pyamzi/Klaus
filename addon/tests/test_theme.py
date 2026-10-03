"""Headless tests for klaus_note.theme — the design-token module.

theme.py must stay aqt-free at module top (only night_mode() touches aqt,
lazily, degrading to light mode) so every QSS builder is testable here.
"""
import importlib
import json
import re
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
theme = importlib.import_module("klaus_note.theme")

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
    ("pdf_panel_qss", theme.pdf_panel_qss),
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
              "background token",
              c["surface"] in qss or c["bg"] in qss or c["chrome"] in qss)

section("dialog button roles")
d = theme.dialog_qss(False)
check("dialog has a primary (blue) default button",
      "#0071D3" in d and "QPushButton {" in d)
check("dialog defines SecondaryButton", "QPushButton#SecondaryButton" in d)
check("dialog defines DangerButton", "QPushButton#DangerButton" in d)

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
check("sidebar wordmark is set in Excalifont (Pouya, 2026-10-01)",
      '"Excalifont"' in theme.dialog_qss(False)
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

check("both chevron assets actually ship in klaus_note/web (a QSS "
      "url() to a missing file is silently blank — back to no arrow)",
      _os.path.exists("klaus_note/web/chevron-day.svg")
      and _os.path.exists("klaus_note/web/chevron-night.svg"))

section("colour themes (K-107 — SynapsePro's accent presets)")
BLUE_KEYS = {"blue", "blue_hover", "blue_pressed", "blue_border",
             "blue_bright", "blue_accent"}
check("every preset ships light AND dark override sets — "
      "SynapsePro's six, the community palettes, Claude, and the app's zinc",
      set(theme.COLOR_THEMES) == {
          "ocean", "orchid", "forest", "deluge", "horizon", "dusty",
          "nord", "solarized", "catppuccin", "gruvbox", "everforest",
          "dracula", "claude", "zinc"}
      and all(set(t) == {False, True}
              and set(t[False]) - {"on_accent"} == BLUE_KEYS
              == set(t[True]) - {"on_accent"}
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
      "always come from the base palettes (zinc alone adds on_accent: "
      "its dark fill is light, so the text on it must be dark)",
      all(k.startswith("blue") or (name == "zinc" and k == "on_accent")
          for name, t in theme.COLOR_THEMES.items()
          for n in (False, True) for k in t[n]))
check("zinc is the app's preset: near-black light, zinc-200 dark, dark text on it",
      theme.COLOR_THEMES["zinc"][False]["blue"] == "#18181B"
      and theme.COLOR_THEMES["zinc"][True]["blue"] == "#E4E4E7"
      and theme.COLOR_THEMES["zinc"][True]["on_accent"] == "#18181B"
      and theme.COLOR_THEMES["zinc"][False]["on_accent"] == "#FAFAFA")
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
dz = theme.drop_zone_qss(False, "klausNoteLibraryDropZone")
check("drop zone scopes rules to the given objectName",
      "#klausNoteLibraryDropZone {" in dz
      and '#klausNoteLibraryDropZone[dragOver="true"]' in dz)
check("drop zone styles its Browse button",
      "#klausNoteLibraryDropZone QPushButton" in dz)
# K-132: the Library's empty state is a drop target that must not
# ADVERTISE as a box while idle — the pane already carries one dashed
# square below the tree. Same builder, idle half muted.
for _n in (False, True):
    _dzq = theme.drop_zone_qss(_n, "klausNoteLibraryEmpty",
                               idle_border=False)
    _c = theme.palette(_n)
    check(f"idle_border=False (night={_n}) drops the idle dashed box",
          "dashed" not in _dzq)
    check(f"idle_border=False (night={_n}) keeps the SHARED drag-over "
          "half — the empty state lights up exactly like the square",
          '#klausNoteLibraryEmpty[dragOver="true"]' in _dzq
          and _c["blue_bright"] in _dzq and _c["selection_bg"] in _dzq)
    check(f"idle_border=False (night={_n}) makes that border "
          "TRANSPARENT rather than removing it — the box model has to "
          "survive the drag or the guidance text shifts a pixel",
          "border: 1px solid transparent" in _dzq)
check("the default is untouched: the deck/Library squares keep their "
      "dashed idle box", "dashed" in dz)
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
            "font") + tuple(f"ink-{n}" for n, _v in theme.HIGHLIGHT_INKS)
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
    check(f"css_vars(night={night}): that is the fill panel_header_qss "
          "(the reader's tab strip) hovers its Qt sibling with",
          c["hover_subtle"] in theme.panel_header_qss(night))
check("light and dark hover fills actually differ (a single baked "
      "neutral would pass every check above)",
      theme.LIGHT["hover_subtle"] != theme.DARK["hover_subtle"])

# Highlight inks (K-149). The pdf.js annobar's swatch row paints itself
# from these vars and reads the chosen value back out of them, so the
# page carries no hex of its own. They are the ONE part of css_vars that
# must NOT follow the mode or the accent: the value is written into the
# annotation record, bakes into the PDF as the mark's /C, and that file
# gets opened in Preview and Acrobat where Klaus's night mode does not
# exist. A per-mode fork here would mean one mark rendering two colours
# depending on where you looked at it.
_INK_VARS = [f"--ink-{n}: {v};" for n, v in theme.HIGHLIGHT_INKS]
check("every ink var is emitted, identically in light and dark",
      all(v in theme.css_vars(False) and v in theme.css_vars(True)
          for v in _INK_VARS), repr(_INK_VARS))
check("inks are five distinct #rrggbb values",
      len({v.lower() for _n, v in theme.HIGHLIGHT_INKS}) == 5
      and all(re.fullmatch(r"#[0-9A-Fa-f]{6}", v)
              for _n, v in theme.HIGHLIGHT_INKS))
check("yellow leads the row — it is pdfjs_viewer.HIGHLIGHT_COLOR, the "
      "colour every pre-K-149 record on disk already carries",
      theme.HIGHLIGHT_INKS[0][0] == "yellow"
      and theme.HIGHLIGHT_INK_DEFAULT.lower() == "#fadc50")
_ink_accent_probe = []
for _name in ("ocean", "claude"):
    theme.set_active_theme(_name)
    _ink_accent_probe.append(theme.css_vars(False))
theme.set_active_theme("ocean")
check("inks do NOT follow the accent theme (a highlight is content, "
      "not chrome — five inks derived from one accent would be five "
      "near-identical hues)",
      all(v in _ink_accent_probe[0] and v in _ink_accent_probe[1]
          for v in _INK_VARS)
      and _ink_accent_probe[0] != _ink_accent_probe[1])

section("one PDF viewer everywhere (K-153): pdf_panel_qss, self-applied")
# Pouya: "I want it to be the same throughout the entire Anki app,
# because it should be consistent no matter what." The viewer has three
# hosts — the editor panel, the Library window, the review-time lecture
# dock — and before this card the only parts of it that looked identical
# in all three were the ones that SELF-STYLE (the native find bar and
# thumb strip, deleted in PDF reader 5/5, and pdf.js's css_vars).
# Everything else drifted because it relied on ancestry: PdfSidebar
# carried no sheet and no styled background, so it painted nothing and
# the host showed through every gap.
_pdf_panel_src = open("klaus_note/reader_panel.py").read()

for night in (False, True):
    c = theme.palette(night)
    pq = theme.pdf_panel_qss(night)
    _no_c = re.sub(r"/\*.*?\*/", "", pq, flags=re.S)
    _selectors = [s.strip() for s in re.findall(r"([^{}]+)\{", _no_c)]
    # Scope is the whole safety argument. An unscoped rule in a sheet
    # that is set on a widget INSIDE someone else's window still only
    # reaches that widget's subtree — but the reverse matters: this
    # sheet must never be the thing that styles a host's own widgets,
    # and every rule reading as a descendant of the one id is what
    # makes that inspectable rather than argued.
    check(f"pdf_panel_qss(night={night}) scopes EVERY rule under the one "
          f"#KlausPdfPanel id (got: {_selectors})",
          bool(_selectors)
          and all(s.startswith("QWidget#KlausPdfPanel") for s in _selectors))
    _panel_blk = re.search(
        r"QWidget#KlausPdfPanel \{(.*?)\}", _no_c, re.S
    )
    check(f"pdf_panel_qss(night={night}): the panel paints ONE "
          "deterministic ground instead of letting the host bleed through",
          _panel_blk is not None
          and f"background-color: {c['bg']}" in _panel_blk.group(1))
    _label_blk = re.search(
        r"QWidget#KlausPdfPanel QLabel \{(.*?)\}", _no_c, re.S
    )
    check(f"pdf_panel_qss(night={night}): labels default to text_muted — "
          "the panel's labels are secondary readouts, and the "
          "fallback label carries no sheet of its own, so without this "
          "it took utility_window_qss's bare QLabel colour in Add Cards",
          _label_blk is not None
          and f"color: {c['text_muted']}" in _label_blk.group(1))
    # The hover family is keyed on the hover_subtle token that css_vars
    # mirrors for the pdf.js half (pinned above). A hover rule here
    # would be another definition of the same interaction, on a surface
    # that has no hover state.
    check(f"pdf_panel_qss(night={night}) declares no hover state — the "
          "hover_subtle family stays with the sheets that own it",
          ":hover" not in pq)
    # Scrollbars are the one part of the viewer already identical in
    # every host, precisely because NOTHING styles them. Styling them
    # here would create drift rather than remove it.
    check(f"pdf_panel_qss(night={night}) leaves QScrollBar alone",
          "QScrollBar" not in pq)

# The consumer half of the contract. A design token nobody applies is
# not a design; these pin that PdfSidebar — the ONE widget every host
# wraps, and the parent of the viewer — wears the sheet itself, the
# way the find bar and the strip already do.
check("PdfSidebar names itself KlausPdfPanel",
      'self.setObjectName("KlausPdfPanel")' in _pdf_panel_src)
check("PdfSidebar applies pdf_panel_qss to ITSELF, so no host can "
      "forget it and a fourth host gets it free",
      "self.setStyleSheet(_theme.pdf_panel_qss(" in _pdf_panel_src)
check("PdfSidebar sets WA_StyledBackground — a plain QWidget paints "
      "NOTHING however styled, which is what let the host bleed through",
      "self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)"
      in _pdf_panel_src)

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
    ("drop_zone_qss(idle_border=False)",
     lambda night: theme.drop_zone_qss(night, "ScaleAuditEmptyState",
                                       idle_border=False)),
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

section("design-tokens.json sync (shared cross-repo with KlausBook)")
# The highlight inks are meant to match KlausBook's copy byte-for-byte today
# (see docs/reference/design-tokens.json's "source_of_truth" note) — unlike
# the rest of the palette, they deliberately never theme-fork, because they
# bake into the PDF's own annotation color. The paint alpha is the
# renderer's (pdf.js CSS), not a theme.py constant, so it isn't asserted
# here.
try:
    with open("docs/reference/design-tokens.json", encoding="utf-8") as _f:
        _tokens = json.load(_f)
    _want_inks = [ink["hex"] for ink in _tokens["highlightInks"]]
    _want_default = next(
        ink["hex"] for ink in _tokens["highlightInks"] if ink.get("default"))
    check("HIGHLIGHT_INKS matches docs/reference/design-tokens.json",
          [hexv for _name, hexv in theme.HIGHLIGHT_INKS] == _want_inks,
          [hexv for _name, hexv in theme.HIGHLIGHT_INKS])
    check("HIGHLIGHT_INK_DEFAULT matches design-tokens.json's default ink",
          theme.HIGHLIGHT_INK_DEFAULT == _want_default)
except FileNotFoundError:
    check("docs/reference/design-tokens.json exists", False)

section("Preferences row dividers stay visible at night (UI review #3)")
for _night in (False, True):
    _m = re.search(r"QFrame#RowSeparator\s*\{[^}]*background-color:\s*(#[0-9A-Fa-f]{6})", theme.dialog_qss(_night))
    _line = _m.group(1) if _m else "#000000"
    _surf = theme.palette(_night)["surface"]
    _gap = max(abs(int(_line[i:i + 2], 16) - int(_surf[i:i + 2], 16)) for i in (1, 3, 5))
    check(f"{'night' if _night else 'day'} divider differs from the card surface by at least 0x10",
          _gap >= 0x10, f"{_line} on {_surf}")

raise SystemExit(report())
