"""Klaus central theme module — design tokens + shared QSS builders.

Adapted from SynapsePro's theme.py (scripts/SynapsePro-main), whose whole
"framework" is discipline: one module of SEMANTIC colour tokens (the Apple
system palette), identical key sets for light and dark, and every UI file
building its stylesheet from ``palette(night)`` instead of hardcoding hex.
UI modules must NOT hardcode colours or font names; they import this module
and reference tokens by semantic key.

Pure stdlib at module top — importable with no Anki/Qt present (the
headless test harness). The one aqt touch, :func:`night_mode`, imports
lazily inside the function and degrades to light mode.

Usage in any UI file::

    from . import theme

    widget.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    label.setStyleSheet(theme.muted_label_qss(night))

Styles are computed at widget-creation time (SynapsePro does the same);
a night-mode flip mid-session catches up on the next open.
"""

from __future__ import annotations

import os


def _asset_url(name: str) -> str:
    """A Qt-stylesheet ``url(...)`` for a file shipped in klausmate/web.

    QSS images cannot be data: URIs or drawn with borders the way a
    web sheet would — they must be real files — so the few chrome
    glyphs QSS needs (the combo chevron) ship as tiny SVGs next to the
    web assets. Forward slashes on purpose: Qt's stylesheet parser
    wants them on every platform, Windows included."""
    path = os.path.join(os.path.dirname(__file__), "web", name)
    return 'url("%s")' % path.replace("\\", "/")


# ─────────────────────────────────────────────────────────────────────────────
# Typography
# ─────────────────────────────────────────────────────────────────────────────

FONT_FAMILY: str = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, '
    "Arial, sans-serif"
)

# ─────────────────────────────────────────────────────────────────────────────
# Palettes — the Apple system palette, light and dark, identical keys.
# ─────────────────────────────────────────────────────────────────────────────

LIGHT: dict = {
    # ── Backgrounds ──────────────────────────────────────────────────────
    "bg":           "#F5F5F7",   # Window / page background
    "surface":      "#FFFFFF",   # Cards, inputs, header bars, trees
    "chrome":       "#FFFFFF",   # Window chrome (the top bar). Chrome must
                                 # SEPARATE from the content canvas behind
                                 # it — brighter than canvas here, darker
                                 # in dark mode. Not `surface`: in dark that
                                 # is #2C2C2C, exactly Anki's --canvas, so
                                 # the bar dissolved into the page.
    "grey_light":   "#E5E5EA",   # Secondary-button fills, card borders
    "grey_mid":     "#D1D1D6",   # Hovers, input borders
    "grey_dark":    "#AEAEB2",   # Pressed states
    "hover_subtle": "#F0F0F0",   # Very subtle hover backgrounds
    "card_raised":  "#FFFFFF",   # A card one tone above the canvas
    "on_accent":    "#FFFFFF",   # Text on an accent (primary) fill
    "selection_bg": "#E4F2FF",   # Tree/table row selection

    # ── Text ─────────────────────────────────────────────────────────────
    "text":         "#1D1D1F",   # Primary body text
    "text_muted":   "#6A6A6F",   # Secondary labels, hints, status lines.
                                 # WCAG AA fix (K-critique/MD3 audit): the
                                 # original #86868B was 3.33:1 on `bg`
                                 # (Fog White) — fails 4.5:1 for the 11px
                                 # captions it backs everywhere. This
                                 # value clears 4.94:1 on `bg`, 5.38:1 on
                                 # `surface`, keeping the same cool lean.
    "text_faint":   "#AAAAAA",   # Placeholder / disabled

    # ── Blue (primary accent) ────────────────────────────────────────────
    "blue":         "#0071D3",   # Primary buttons, checked checkboxes
    "blue_hover":   "#0062C4",
    "blue_pressed": "#004990",
    "blue_border":  "none",      # Full CSS border value for primary buttons
    "blue_bright":  "#007AFF",   # Focus rings, active-tab underline, accents
    "blue_accent":  "#0071D3",   # Prominent accent (= blue in light,
                                 # brighter in dark — SynapsePro's token)

    # ── Red (danger / destructive) ───────────────────────────────────────
    "red":          "#FF3B30",
    "red_hover":    "#D7261E",
    "red_bg":       "#FFEBEB",
    "red_text":     "#D32F2F",
    # Text-weight green, red_text's sibling: "green" is the vivid
    # system green (#28CD41) — right for fills and dots, neon as INK,
    # especially on dark where red_text is a soft #FFCCCC. K-127's
    # retention column pairs these two as calm semantic text colours.
    "green_text":   "#1F7A3D",

    # ── Green (success) ──────────────────────────────────────────────────
    "green":        "#28CD41",
    "green_bg":     "#E8F8F5",
    "green_border": "#C1E1D9",
}

DARK: dict = {
    # ── Backgrounds ──────────────────────────────────────────────────────
    "bg":           "#191919",
    "surface":      "#2C2C2C",
    "chrome":       "#232323",   # See LIGHT["chrome"]: a step DARKER than
                                 # Anki's dark --canvas (#2c2c2c), so the
                                 # bar reads as recessed chrome.
    "grey_light":   "#303030",
    "grey_mid":     "#404040",
    "grey_dark":    "#505050",
    "hover_subtle": "#404040",
    "card_raised":  "#3A3A3C",   # dark `surface` IS Anki's canvas: step up
    "on_accent":    "#FFFFFF",
    "selection_bg": "#404040",

    # ── Text ─────────────────────────────────────────────────────────────
    "text":         "#E0E0E0",
    "text_muted":   "#AAAAAA",
    "text_faint":   "#888888",

    # ── Blue (primary accent) ────────────────────────────────────────────
    "blue":         "#0071D3",
    "blue_hover":   "#0062C4",
    "blue_pressed": "#004990",
    "blue_border":  "1px solid #0056A4",  # Dark mode: shadows don't read,
    "blue_bright":  "#4FACFE",            # borders + brighter accent do.
    "blue_accent":  "#4FACFE",

    # ── Red (danger / destructive) ───────────────────────────────────────
    "red":          "#FF3B30",
    "red_hover":    "#D7261E",
    "red_bg":       "#5A1E1E",
    "red_text":     "#FFCCCC",
    "green_text":   "#B9E8C9",

    # ── Green (success) ──────────────────────────────────────────────────
    "green":        "#28CD41",
    "green_bg":     "#1E3A2E",
    "green_border": "#2D5A45",
}


# ─────────────────────────────────────────────────────────────────────────────
# Highlight inks (K-149) — the marker colours the pdf.js annobar offers.
#
# These live OUTSIDE the light/dark palettes on purpose: a highlight is
# INK ON THE PAGE, not chrome. The value is written into the record, the
# record bakes into the PDF as the annotation's /C, and that file opens
# in Preview and Acrobat where Klaus's night mode does not exist — so a
# per-mode fork here would mean the same mark rendering two different
# colours depending on where you look at it. They do not follow the
# accent theme either, for the same reason (and because five marker
# inks derived from one accent would be five near-identical hues).
#
# Chosen to read at the viewer's 43% paint alpha over white paper AND
# to stay distinguishable from each other when two abut. YELLOW MUST
# STAY FIRST: it is pdfjs_viewer.HIGHLIGHT_COLOR, the native viewer's
# default, and every pre-K-149 record on disk already carries it.
# ─────────────────────────────────────────────────────────────────────────────

HIGHLIGHT_INKS: tuple[tuple[str, str], ...] = (
    ("yellow", "#FADC50"),
    ("green",  "#8AE08C"),
    ("blue",   "#7FC6F2"),
    ("pink",   "#F79AC8"),
    ("orange", "#F7B267"),
)

HIGHLIGHT_INK_DEFAULT: str = HIGHLIGHT_INKS[0][1]


# ─────────────────────────────────────────────────────────────────────────────
# Colour themes — SynapsePro's accent presets, verbatim. Only the six
# blue-family tokens differ per theme; backgrounds, text and greys always
# come from the base palettes so every theme works in light AND dark.
# Structure: COLOR_THEMES[name][night_bool] = {token overrides}.
# ─────────────────────────────────────────────────────────────────────────────

COLOR_THEMES: dict = {
    "ocean": {
        False: {"blue": "#0071D3", "blue_hover": "#0062C4",
                "blue_pressed": "#004990", "blue_border": "none",
                "blue_bright": "#007AFF", "blue_accent": "#0071D3"},
        True:  {"blue": "#0071D3", "blue_hover": "#0062C4",
                "blue_pressed": "#004990",
                "blue_border": "1px solid #0056A4",
                "blue_bright": "#4FACFE", "blue_accent": "#4FACFE"},
    },
    "orchid": {
        False: {"blue": "#E95ACC", "blue_hover": "#E159C6",
                "blue_pressed": "#CB51B3", "blue_border": "none",
                "blue_bright": "#FCABEC", "blue_accent": "#E95ACC"},
        True:  {"blue": "#E95ACC", "blue_hover": "#E159C6",
                "blue_pressed": "#CB51B3",
                "blue_border": "1px solid #B8459F",
                "blue_bright": "#FCABEC", "blue_accent": "#FCABEC"},
    },
    "forest": {
        False: {"blue": "#619971", "blue_hover": "#598C68",
                "blue_pressed": "#477154", "blue_border": "none",
                "blue_bright": "#84CC99", "blue_accent": "#619971"},
        True:  {"blue": "#619971", "blue_hover": "#598C68",
                "blue_pressed": "#477154",
                "blue_border": "1px solid #3C5E43",
                "blue_bright": "#84CC99", "blue_accent": "#84CC99"},
    },
    "deluge": {
        False: {"blue": "#7961A9", "blue_hover": "#6D5798",
                "blue_pressed": "#65508D", "blue_border": "none",
                "blue_bright": "#987AD2", "blue_accent": "#7961A9"},
        True:  {"blue": "#7961A9", "blue_hover": "#6D5798",
                "blue_pressed": "#65508D",
                "blue_border": "1px solid #573F7A",
                "blue_bright": "#987AD2", "blue_accent": "#987AD2"},
    },
    "horizon": {
        False: {"blue": "#6183A9", "blue_hover": "#59799D",
                "blue_pressed": "#4B6683", "blue_border": "none",
                "blue_bright": "#7FABDC", "blue_accent": "#6183A9"},
        True:  {"blue": "#6183A9", "blue_hover": "#59799D",
                "blue_pressed": "#4B6683",
                "blue_border": "1px solid #3D596F",
                "blue_bright": "#7FABDC", "blue_accent": "#7FABDC"},
    },
    "dusty": {
        False: {"blue": "#5A9491", "blue_hover": "#528885",
                "blue_pressed": "#4E8280", "blue_border": "none",
                "blue_bright": "#7CCDC9", "blue_accent": "#5A9491"},
        True:  {"blue": "#5A9491", "blue_hover": "#528885",
                "blue_pressed": "#4E8280",
                "blue_border": "1px solid #3E6B69",
                "blue_bright": "#7CCDC9", "blue_accent": "#7CCDC9"},
    },
}

CUSTOM_THEME = "custom"

# The user's chosen accent, set once at profile open (config key
# ``color_theme``); every later palette() call overlays it. UI files
# never need to know a preference exists — SynapsePro's mechanism.
_ACTIVE_THEME: str = "ocean"

# The single ``#rrggbb`` behind CUSTOM_THEME. SynapsePro asks the user
# for four colours; Klaus asks for one and derives the rest, because a
# picker that demands a matching hover AND pressed AND bright shade is a
# design task, not a preference.
_CUSTOM_COLOR: str = "#0071D3"

DEFAULT_CUSTOM_COLOR = "#0071D3"


def is_hex_colour(value: object) -> bool:
    """True for ``#rgb`` / ``#rrggbb`` strings — the only accepted form."""
    s = str(value or "").strip()
    if not s.startswith("#") or len(s) not in (4, 7):
        return False
    try:
        int(s[1:], 16)
    except ValueError:
        return False
    return True


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    if len(h) == 3:  # #abc -> #aabbcc
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _shade(hex_colour: str, factor: float) -> str:
    """Darken (``factor`` < 1) or lighten (> 1) a colour, clamped.

    Lightening mixes toward white rather than scaling channels, so a
    fully saturated colour still brightens instead of staying put.
    """
    r, g, b = _rgb(hex_colour)
    if factor <= 1.0:
        vals = [c * factor for c in (r, g, b)]
    else:
        t = min(1.0, factor - 1.0)
        vals = [c + (255 - c) * t for c in (r, g, b)]
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(v))) for v in vals)


def custom_overrides(base_colour: str, night: bool) -> dict:
    """The six blue-family tokens derived from ONE user colour.

    Ratios are read off SynapsePro's own presets (hover ≈ 10% darker,
    pressed ≈ 30% darker, bright a lift toward white — much stronger in
    dark mode, where their accents are visibly lighter than the base).
    """
    if not is_hex_colour(base_colour):
        base_colour = DEFAULT_CUSTOM_COLOR
    pressed = _shade(base_colour, 0.70)
    bright = _shade(base_colour, 1.35 if night else 1.08)
    return {
        "blue": base_colour,
        "blue_hover": _shade(base_colour, 0.90),
        "blue_pressed": pressed,
        "blue_border": f"1px solid {pressed}" if night else "none",
        "blue_bright": bright,
        # Same rule as every preset: the accent is the base in light and
        # the brightened tone in dark.
        "blue_accent": bright if night else base_colour,
    }


def _community_preset(
    base: str,
    bright_light: str | None = None,
    bright_dark: str | None = None,
) -> dict:
    """A COLOR_THEMES entry from a palette's canonical accent colour.

    The community palettes (Nord, Solarized, …) publish a signature
    accent but not our exact six-token family, so hover/pressed are
    derived with the same ratios as the custom theme; where a palette
    DOES publish a canonical bright tone (Nord's frost, Dracula's
    purple), it is passed in rather than derived. Backgrounds and text
    stay on the base palettes by design — these are accent presets, not
    full re-skins.
    """
    ov_l = custom_overrides(base, False)
    ov_d = custom_overrides(base, True)
    if bright_light:
        ov_l["blue_bright"] = bright_light
    if bright_dark:
        ov_d["blue_bright"] = bright_dark
        ov_d["blue_accent"] = bright_dark
    return {False: ov_l, True: ov_d}


# Community palettes + Claude, as accent presets. Base colours are each
# palette's published signature accent; bright tones are the palette's
# own lighter companion where one exists.
COLOR_THEMES.update({
    # nord10 base; nord9 / nord8 (frost) brights.
    "nord": _community_preset("#5E81AC", "#81A1C1", "#88C0D0"),
    # Solarized blue — its accents are already tuned for both modes.
    "solarized": _community_preset("#268BD2"),
    # Latte mauve base; Mocha mauve as the dark bright.
    "catppuccin": _community_preset("#8839EF", None, "#CBA6F7"),
    # Neutral gruvbox orange; dark-mode bright is the iconic #FE8019.
    "gruvbox": _community_preset("#D65D0E", None, "#FE8019"),
    # Everforest green (light palette); dark palette green as bright.
    "everforest": _community_preset("#8DA101", None, "#A7C080"),
    # Dracula's ANSI purple for light surfaces; the iconic #BD93F9 dark.
    "dracula": _community_preset("#7C53C3", None, "#BD93F9"),
    # Claude's terracotta ("Crail"), Anthropic's primary accent.
    "claude": _community_preset("#D97757"),
})


def set_active_theme(name: str) -> None:
    """Persist the accent-preset name for all later palette() calls.
    Accepts any COLOR_THEMES key or ``"custom"``; unknown names are
    ignored (stays on the current theme)."""
    global _ACTIVE_THEME
    if name in COLOR_THEMES or name == CUSTOM_THEME:
        _ACTIVE_THEME = name


def get_active_theme() -> str:
    """The active accent-preset name (default ``"ocean"``)."""
    return _ACTIVE_THEME


def set_custom_colour(hex_colour: str) -> None:
    """Store the colour behind ``"custom"``. Ignored unless it is a
    valid hex string, so a corrupt config can never blank the accent."""
    global _CUSTOM_COLOR
    if is_hex_colour(hex_colour):
        _CUSTOM_COLOR = str(hex_colour).strip()


def get_custom_colour() -> str:
    """The colour behind ``"custom"`` (``#rrggbb``)."""
    return _CUSTOM_COLOR


def palette(night: bool) -> dict:
    """The colour-token dict for *night* mode with the active accent
    theme's blue-family overrides applied (a copy — mutate freely)."""
    base = (DARK if night else LIGHT).copy()
    if _ACTIVE_THEME == CUSTOM_THEME:
        base.update(custom_overrides(_CUSTOM_COLOR, night))
    else:
        base.update(
            COLOR_THEMES.get(_ACTIVE_THEME, COLOR_THEMES["ocean"])[night]
        )
    return base


def night_mode() -> bool:
    """Anki's night-mode state; False (light) when aqt is unavailable."""
    try:
        from aqt.theme import theme_manager

        return bool(theme_manager.night_mode)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Shared QSS builders — one per UI surface family. All pure string
# functions of ``night`` so the headless tests can exercise every branch.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Design scale (K-110) — every QSS builder below draws its border-radius
# and font-size values from these two sanctioned sets. An off-scale value
# is drift, not a style choice — tests/test_theme.py scans the emitted
# CSS of every builder and fails the suite if either set gains a member
# it wasn't given here.
#
# border-radius (px):
#   12  cards / containers        — QGroupBox, CardFrame, TreeWidget,
#                                    drop-zone squares
#    8  buttons / inputs / chips / pills — QPushButton, QLineEdit,
#                                    QComboBox, nav rows, the toolbar
#                                    .hitem chip (pinned, see below)
#    6  small controls            — swatches, list items, checkbox
#                                    indicators, tab pills, tool-button
#                                    glyphs
#    7  slider-handle circle ONLY — height / 2 (a 14px handle is a
#                                    circle, not a rounded square)
#    4  slim fill                 — progress bar + its chunk
#    2  slim fill                 — slider groove + sub-page
#    0  a deliberate flattener (killing a corner Anki itself drew, e.g.
#       toolbar_css's `.header .toolbar`) — never a default
#
# font-size (px): 10 micro · 11 captions · 12 subtitles · 13 body ·
#   14 section headings · 18 wordmark · 24 page titles
#
# The toolbar/bottombar chip blocks (_chip_base_rules, _chip_hover_rules,
# _chip_active_rules, toolbar_css, bottombar_css) already sit on this
# scale (8px radius, 13px font) and are pinned byte-identical by
# tests/test_top_bar.py — this audit does not touch their values.
# ─────────────────────────────────────────────────────────────────────────────

_WORDMARK_FAMILY: str | None = None


def register_wordmark_font() -> str | None:
    """Register the wordmark's Excalifont once and return its family, or
    None without a QGuiApplication or when the font won't load.

    From bytes, not the path: Qt refused the same file by path in testing
    (an add-on folder can carry quarantine attributes)."""
    global _WORDMARK_FAMILY
    if _WORDMARK_FAMILY is not None:
        return _WORDMARK_FAMILY
    try:
        from aqt.qt import QByteArray, QFontDatabase, QGuiApplication

        if QGuiApplication.instance() is None:
            return None
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "fonts", "Excalifont-Regular.ttf")
        with open(path, "rb") as fh:
            fid = QFontDatabase.addApplicationFontFromData(QByteArray(fh.read()))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _WORDMARK_FAMILY = fams[0] if fams else None
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] wordmark font failed: {exc}")
    return _WORDMARK_FAMILY


def dialog_qss(night: bool) -> str:
    """Dialog foundation (Manage models, future dialogs).

    SynapsePro's settings-dialog language: window on ``bg``, every
    QGroupBox a white card (12px radius, 1px ``grey_light`` border),
    quiet utility buttons with an explicit accented default action.
    """
    register_wordmark_font()
    c = palette(night)
    return f"""
    QDialog {{
        background-color: {c['bg']};
        color: {c['text']};
        font-size: 13px;
    }}
    QGroupBox {{
        background-color: {c['surface']};
        border: 1px solid {c['grey_light']};
        border-radius: 12px;
        font-weight: 600;
        margin-top: 10px;
        padding: 14px 12px 10px 12px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0px 4px;
        color: {c['text']};
    }}
    QLabel {{ color: {c['text']}; background: transparent; }}
    QPushButton {{
        background-color: {c['hover_subtle']};
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 6px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: {c['grey_light']}; }}
    QPushButton:pressed {{ background-color: {c['grey_mid']}; }}
    QPushButton:default, QPushButton#PrimaryButton {{
        background-color: {c['blue']}; color: white;
    }}
    QPushButton:default:hover, QPushButton#PrimaryButton:hover {{
        background-color: {c['blue_hover']};
    }}
    QPushButton:default:pressed, QPushButton#PrimaryButton:pressed {{
        background-color: {c['blue_pressed']};
    }}
    /* Reserve the border at rest so keyboard focus never shifts layout. */
    QPushButton:focus {{ border: 1px solid {c['blue_bright']}; }}
    QPushButton:disabled {{
        background-color: {c['grey_light']};
        color: {c['text_faint']};
    }}
    QPushButton#SecondaryButton {{
        background-color: {c['grey_light']};
        color: {c['text']};
        border: 1px solid transparent;
    }}
    QPushButton#SecondaryButton:hover {{ background-color: {c['grey_mid']}; }}
    QPushButton#SecondaryButton:pressed {{
        background-color: {c['grey_dark']};
    }}
    QPushButton#DangerButton {{
        background-color: {c['red_bg']};
        color: {c['red_text']};
        border: none;
    }}
    QPushButton#DangerButton:hover {{
        background-color: {c['red']};
        color: white;
    }}
    QPushButton#AdvancedModelSettings {{
        background: transparent; color: {c['text_muted']};
        border: 1px solid transparent; text-align: left;
        padding: 8px 0; font-weight: 500;
    }}
    QPushButton#AdvancedModelSettings:hover {{ color: {c['text']}; }}
    QPushButton#AdvancedModelSettings:pressed {{ background: {c['hover_subtle']}; }}
    QPushButton#SecondaryButton:focus,
    QPushButton#DangerButton:focus,
    QPushButton#AdvancedModelSettings:focus {{ border: 1px solid {c['blue_bright']}; }}
    QComboBox, QLineEdit {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 4px 8px;
    }}
    /* Combos read as pickers, not text fields (Pouya: "make the
       dropdowns look better"): room on the right for a real chevron
       — QSS draws NO arrow once ::drop-down is styled, which is
       exactly why these looked like dead line-edits — plus a hover
       state so they invite the click. The chevron is a shipped SVG
       (see _asset_url): QSS images must be files. */
    QComboBox {{
        padding: 4px 26px 4px 10px;
        min-height: 20px;
    }}
    QComboBox:hover {{
        border: 1px solid {c['grey_dark']};
        background-color: {c['bg']};
    }}
    QComboBox:focus, QLineEdit:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 24px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: {_asset_url('chevron-night.svg' if night else 'chevron-day.svg')};
        width: 10px;
        height: 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 4px;
        outline: 0;
        selection-background-color: {c['selection_bg']};
        selection-color: {c['text']};
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 22px;
        padding: 3px 8px;
        border-radius: 6px;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {c['blue_accent']};
        color: white;
    }}
    /* SynapsePro settings cards (K-105): QFrame#CardFrame is the
       section container, QLabel#SubHeaderLabel its heading, and the
       hosting scroll area is transparent so the dialog bg shows
       through — all three transcribed from SynapsePro's
       settings_dialog styles. */
    QFrame#CardFrame {{
        background-color: {c['surface']};
        border: 1px solid {c['grey_light']};
        border-radius: 12px;
    }}
    QLabel#SubHeaderLabel {{
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 5px;
    }}
    QScrollArea#ContentScrollArea {{ background: transparent; border: none; }}
    QScrollArea#ContentScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    /* K-106 — SynapsePro's CURRENT settings shell (their 1.5.x window,
       built from Pouya's screenshot; the vendored source only has the
       older card grid): a fixed SettingsSidebar carrying the app
       identity plus a SettingsNav list with one row per page, a large
       PageTitle + muted PageSubtitle heading each page, and settings as
       rows — bold SettingName over muted SettingDesc with the control
       pinned right — split by RowSeparator hairlines inside the same
       #CardFrame rounded group. ButtonBarLine is the hairline over the
       Cancel/Save bar. */
    QFrame#SettingsSidebar {{
        background-color: {c['bg']};
        border-right: 1px solid {c['grey_light']};
    }}
    QLabel#SidebarAppName {{
        font-family: "Excalifont", "EB Garamond", Garamond, Georgia, serif;
        font-size: 18px;
    }}
    QLabel#SidebarVersion {{ color: {c['text_muted']}; font-size: 11px; }}
    QLineEdit#SettingsSearch {{
        background-color: {c['surface']};
        border: 1px solid {c['grey_light']};
        border-radius: 8px;
        padding: 4px 10px;
        font-size: 12px;
    }}
    /* The Preferences nav — ONE QListWidget (see manage_models), so
       every row shares a single style/paint path. The id-scoped rules
       must beat the generic QListWidget polish below (id > type). */
    QListWidget#SettingsNav {{
        background: transparent;
        border: none;
        padding: 0px;
        font-weight: 600;
        font-size: 13px;
        outline: none; /* the selected row's tint carries focus */
    }}
    QListWidget#SettingsNav::item {{
        color: {c['text']};
        border-radius: 8px;
        padding-left: 12px;
    }}
    QListWidget#SettingsNav::item:hover {{
        background-color: {c['hover_subtle']};
    }}
    QListWidget#SettingsNav::item:selected {{
        background-color: {accent_rgba(night, 0.16)};
        color: {c['blue']};
    }}
    QLabel#PageTitle {{ font-size: 24px; font-weight: 600; }}
    QLabel#PageSubtitle {{ color: {c['text_muted']}; font-size: 12px; }}
    QLabel#SettingName {{ font-size: 13px; font-weight: 600; }}
    QLabel#SettingDesc {{ color: {c['text_muted']}; font-size: 12px; }}
    /* K-111 (manage_models's install/setup page): heading + subsection
       typography, sized like SubHeaderLabel/SettingName above so the
       install flow doesn't invent its own scale. */
    QLabel#InstallHeading {{ font-size: 14px; font-weight: 700; }}
    QLabel#InstallSection {{
        font-size: 13px;
        font-weight: 600;
        margin-top: 8px;
    }}
    QFrame#RowSeparator {{
        background-color: {c['grey_mid'] if night else c['grey_light']};
        border: none;
        max-height: 1px;
    }}
    QFrame#ButtonBarLine {{
        background-color: {c['grey_light']};
        border: none;
        max-height: 1px;
    }}
    QCheckBox {{ color: {c['text']}; spacing: 10px; padding: 4px 0px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        /* Small control (checkbox indicator) — 6px per the design
           scale above; this had drifted to a bespoke 5px. */
        border-radius: 6px;
        border: 1px solid {c['grey_mid']};
        background-color: {c['surface']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c['blue']};
        border: 1px solid {c['blue']};
    }}
    /* SynapsePro widget polish (K-107 audit): progress bars, sliders
       and lists were bare native Qt while every neighbouring control
       was themed — grey_light grooves, blue fills, rounded lists. */
    QProgressBar {{
        border: none;
        border-radius: 4px;
        background-color: {c['grey_light']};
        color: {c['text_muted']};
        font-size: 10px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {c['blue']};
        border-radius: 4px;
    }}
    QSlider::groove:horizontal {{
        border: none;
        height: 4px;
        border-radius: 2px;
        background: {c['grey_light']};
    }}
    QSlider::sub-page:horizontal {{
        background: {c['blue']};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {c['surface']};
        border: 1px solid {c['grey_mid']};
        width: 14px;
        height: 14px;
        margin: -6px 0;
        border-radius: 7px;
    }}
    QListWidget {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_light']};
        border-radius: 8px;
        padding: 4px;
    }}
    QListWidget::item {{
        border-radius: 6px;
        padding: 3px 6px;
    }}
    QListWidget::item:hover {{ background-color: {c['hover_subtle']}; }}
    QListWidget::item:selected {{
        background-color: {c['selection_bg']};
        color: {c['text']};
    }}
    /* Disabled states (K-108). An inert control MUST look inert: the
       Appearance page disables Fit/Blur/Choose Image unless the
       background is an image, and those controls read as fully live.
       Cause: an id selector (QPushButton#SecondaryButton) outranks a
       pseudo-state one (QPushButton:disabled), so the enabled style
       won — every :disabled rule below therefore repeats the id it
       has to beat, and rows are disabled WHOLE so their labels dim
       with the control. */
    QLabel:disabled,
    QLabel#SettingName:disabled,
    QLabel#SettingDesc:disabled,
    QCheckBox:disabled {{ color: {c['text_faint']}; }}
    QPushButton#SecondaryButton:disabled,
    QPushButton#DangerButton:disabled {{
        background-color: {c['grey_light']};
        color: {c['text_faint']};
        border: none;
    }}
    QComboBox:disabled, QLineEdit:disabled {{
        background-color: {c['bg']};
        color: {c['text_faint']};
        border: 1px solid {c['grey_light']};
    }}
    QSlider::groove:horizontal:disabled {{ background: {c['grey_light']}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {c['grey_mid']}; }}
    QSlider::handle:horizontal:disabled {{
        background: {c['bg']};
        border: 1px solid {c['grey_light']};
    }}
    QCheckBox::indicator:disabled {{
        background-color: {c['bg']};
        border: 1px solid {c['grey_light']};
    }}
    """


def panel_header_qss(night: bool) -> str:
    """The PDF panel's header bar (tabs + tool buttons), objectName
    ``KlausPanelHeader``. Surface-coloured bar with a hairline bottom
    border; document-mode tabs render as quiet pills, the active one on
    ``hover_subtle`` with the accent underline SynapsePro uses for
    active states; tool buttons are borderless glyphs that grow a
    rounded hover fill.
    """
    c = palette(night)
    return f"""
    QWidget#KlausPanelHeader {{
        background-color: {c['surface']};
        border-bottom: 1px solid {c['grey_light']};
    }}
    QWidget#KlausPanelHeader QTabBar {{
        background: transparent;
    }}
    QWidget#KlausPanelHeader QTabBar::tab {{
        background: transparent;
        color: {c['text_muted']};
        border: none;
        border-radius: 6px;
        padding: 3px 10px;
        margin: 2px 1px;
    }}
    QWidget#KlausPanelHeader QTabBar::tab:hover {{
        background: {c['hover_subtle']};
    }}
    QWidget#KlausPanelHeader QTabBar::tab:selected {{
        background: {c['hover_subtle']};
        color: {c['text']};
        font-weight: 600;
        border-bottom: 2px solid {c['blue_bright']};
    }}
    QWidget#KlausPanelHeader QToolButton {{
        background: transparent;
        color: {c['text_muted']};
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 3px 5px;
    }}
    QWidget#KlausPanelHeader QToolButton:hover {{
        background: {c['hover_subtle']};
        color: {c['text']};
    }}
    QWidget#KlausPanelHeader QToolButton:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    QWidget#KlausPanelHeader QToolButton:pressed {{
        background: {c['grey_mid']};
    }}
    """


def pdf_panel_qss(night: bool) -> str:
    """The PDF reader's own panel, objectName ``KlausPdfPanel`` (K-153).

    Pouya: "I want it to be the same throughout the entire Anki app,
    because it should be consistent no matter what." The reader appears
    in more than one host, and when this was written (K-153) only the
    parts that SELF-STYLED looked identical everywhere: the native
    viewer's find bar and thumbnail strip (both deleted with it in PDF
    reader 5/5) and pdf.js's ``css_vars``, which still style the page.
    Everything that drifted, drifted because it relied on ancestry:
    ``PdfSidebar`` was a plain QWidget with no sheet and no
    ``WA_StyledBackground``, so it painted NOTHING and whatever was
    behind it showed through every gap around the reader — a different
    ambient in each host window (the since-deleted Library window's
    ``library_qss``, ``mw``'s stock palette under the lecture panel).
    With ``klausbook_design`` off by default, most hosts inherited
    nothing at all.

    So ``PdfSidebar`` applies this TO ITSELF: no host can forget it,
    and a new host gets the look for free. ONE id selector,
    deliberately. A child widget's own stylesheet still beats this
    inherited one irrespective of specificity (measured, K-153).

    Contents, and why each is here:

    * the panel background — one deterministic base instead of bleed.
    * ``QLabel`` — the panel's labels are secondary readouts (the page
      indicator, the viewer-unavailable fallback). A readout that
      carries ``muted_label_qss`` on itself was never at risk; the
      FALLBACK carries nothing, so it took its colour from whatever
      window it was in — ``utility_window_qss``'s bare
      ``QLabel { color: text }`` in Add Cards. This makes muted the
      panel's default for any label that does not ask otherwise,
      including ones added later.

    Scrollbars are deliberately NOT styled: nothing styles QScrollBar
    in any host today, which makes them the one part of the viewer
    that is already identical everywhere. Styling them here would
    create drift, not remove it.
    """
    c = palette(night)
    return f"""
    QWidget#KlausPdfPanel {{
        background-color: {c['bg']};
    }}
    QWidget#KlausPdfPanel QLabel {{
        color: {c['text_muted']};
        background: transparent;
    }}
    """


def assistant_dock_qss(night: bool) -> str:
    """The Claude Code assistant dock, objectName ``KlausAssistantDock``
    (K-198, replacing the retired ``KlausAssistantPanel`` third-pane —
    see ``library_qss``'s history). Joins the ``dialog_qss`` family:
    ground on ``chrome`` like the top/bottom bars and every other Klaus
    panel; header, selection chip and status dot in ``text_muted``; the
    transcript itself ALSO on ``chrome`` (its edges dissolve into the
    dock instead of reading as a separate white card sitting on it),
    with `text` body copy and `surface`-boxed ``<pre>`` blocks for the
    markdown-lite renderer's fenced code; the input on ``surface`` with
    a quiet ``grey_light`` hairline; and buttons following
    :func:`dialog_qss`'s own roles verbatim (blue-primary Send/Stop,
    grey ``SecondaryButton`` for New Session and Re-check).

    The focus ring is ``blue_bright``, not ``blue_border``: every other
    ``:focus`` rule in this module (QComboBox/QLineEdit, QPushButton,
    the LibraryGlyph action, SettingsSearch) uses ``blue_bright``
    specifically because it is visible in BOTH palettes — ``blue_border``
    is ``"none"`` in light mode (a button's resting-state chrome, not an
    accent ring), and a focus indicator that disappears in light mode
    fails the same P1 this module's own dialog_qss comment already
    fixed once for buttons. Kept consistent here rather than forked.
    """
    c = palette(night)
    return f"""
    QDockWidget#KlausAssistantDock {{
        background: {c['chrome']};
        color: {c['text']};
        font-size: 13px;
    }}
    QDockWidget#KlausAssistantDock QLabel#KlausAssistantHeader {{
        color: {c['text_muted']};
        font-size: 12px;
        font-weight: 600;
        background: transparent;
    }}
    QDockWidget#KlausAssistantDock QLabel#KlausAssistantChip {{
        color: {c['text_muted']};
        font-size: 11px;
        background: transparent;
    }}
    QDockWidget#KlausAssistantDock QLabel#KlausAssistantStatusDot {{
        color: {c['text_muted']};
        font-size: 11px;
        background: transparent;
    }}
    QDockWidget#KlausAssistantDock QTextEdit#KlausAssistantTranscript {{
        background-color: {c['chrome']};
        color: {c['text']};
        border: none;
        font-size: 13px;
    }}
    QDockWidget#KlausAssistantDock QTextEdit#KlausAssistantTranscript pre {{
        background-color: {c['surface']};
        border: 1px solid {c['grey_light']};
        border-radius: 8px;
        padding: 6px;
    }}
    QDockWidget#KlausAssistantDock QPlainTextEdit#KlausAssistantInput {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_light']};
        border-radius: 8px;
        padding: 6px 8px;
        font-size: 13px;
    }}
    QDockWidget#KlausAssistantDock QPlainTextEdit#KlausAssistantInput:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    QDockWidget#KlausAssistantDock QPushButton {{
        background-color: {c['blue']};
        color: white;
        border: {c['blue_border']};
        border-radius: 8px;
        padding: 6px 16px;
        font-weight: 600;
        font-size: 13px;
    }}
    QDockWidget#KlausAssistantDock QPushButton:hover {{ background-color: {c['blue_hover']}; }}
    QDockWidget#KlausAssistantDock QPushButton:pressed {{ background-color: {c['blue_pressed']}; }}
    QDockWidget#KlausAssistantDock QPushButton:focus {{ border: 1px solid {c['blue_bright']}; }}
    QDockWidget#KlausAssistantDock QPushButton:disabled {{
        background-color: {c['grey_light']};
        color: {c['text_faint']};
    }}
    QDockWidget#KlausAssistantDock QPushButton#SecondaryButton {{
        background-color: {c['grey_light']};
        color: {c['text']};
        border: none;
    }}
    QDockWidget#KlausAssistantDock QPushButton#SecondaryButton:hover {{
        background-color: {c['grey_mid']};
    }}
    QDockWidget#KlausAssistantDock QPushButton#SecondaryButton:pressed {{
        background-color: {c['grey_dark']};
    }}
    QDockWidget#KlausAssistantDock QPushButton#SecondaryButton:disabled {{
        background-color: {c['grey_light']};
        color: {c['text_faint']};
        border: none;
    }}
    """


def drop_zone_qss(
    night: bool, object_name: str, idle_border: bool = True
) -> str:
    """The shared drop-square language (Library drop zone; the deck-screen
    squares in deck_curate render the same values as HTML). Dashed grey
    idle border that turns solid accent on drag-over.

    ``idle_border=False`` keeps the drag-over half and drops the idle
    dashed box, for a surface that is a drop target but must not
    ADVERTISE as a box while idle — the Library's empty state (K-132),
    which is quiet muted guidance text until a .pdf drag arrives, in a
    pane that already carries one dashed square below the tree (two
    would read as two targets). The idle border is not removed but made
    TRANSPARENT: the box model stays identical, so the text cannot
    shift by a pixel when the accent border appears under the drag.
    """
    c = palette(night)
    idle_edge = (
        f"1px dashed {c['grey_mid']}" if idle_border else "1px solid transparent"
    )
    return f"""
    #{object_name} {{
        border: {idle_edge};
        /* Container role (a droppable card, not a button/chip) — 12px
           per the design scale above; this had drifted to a bespoke
           10px. */
        border-radius: 12px;
        background: transparent;
    }}
    #{object_name}[dragOver="true"] {{
        border: 1px solid {c['blue_bright']};
        background: {c['selection_bg']};
    }}
    #{object_name} QPushButton {{
        border: 1px solid {c['grey_mid']};
        border-radius: 6px;
        font-size: 12px;
        padding: 3px 10px;
        background: transparent;
        color: {c['text']};
    }}
    #{object_name} QPushButton:hover {{
        border-color: {c['blue_bright']};
        background: {c['hover_subtle']};
    }}
    """


def accent_rgba(night: bool, alpha: float) -> str:
    """``blue_bright`` as an ``rgba(...)`` string — for translucent
    overlays (the drop-zone drag preview) where hex can't carry alpha."""
    h = palette(night)["blue_bright"].lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:g})"


def _toolbar_vars(c: dict, night: bool) -> str:
    """One palette as Klaus custom properties for the toolbars.

    Hover/press are TRANSLUCENT veils, not opaque fills — Apple's
    material treatment (NSToolbar button states): translucent black
    over light chrome, translucent white over dark. Over the custom
    backgrounds (a flat colour, a frosted photo) an opaque hover chip
    read as a grey sticker; a veil tints whatever is actually behind
    the button, so the highlight "reflects the background" by
    construction.
    """
    hover = "rgba(255, 255, 255, 0.10)" if night else "rgba(0, 0, 0, 0.05)"
    press = "rgba(255, 255, 255, 0.16)" if night else "rgba(0, 0, 0, 0.09)"
    return (
        f"--klaus-chrome: {c['chrome']};"
        f" --klaus-border: {c['grey_light']};"
        f" --klaus-text: {c['text']};"
        f" --klaus-text-muted: {c['text_muted']};"
        f" --klaus-hover: {hover};"
        f" --klaus-press: {press};"
        f" --klaus-accent: {c['blue_bright']};"
    )


def _chip_base_rules() -> str:
    """THE Klaus toolbar chip — the declarations behind the top bar's
    .hitem links, shared VERBATIM with the bottom bar's buttons so the
    two bars can never drift apart (Pouya: "EXACTLY the same").
    !important throughout: Anki's own sheets outrank plain injected
    rules — toolbar.css's body.fancy:not(.flat) .hitem is specificity
    0,3,1, and webview.css ships `button { background/border/... }`
    rules that load with stdHtml regardless of injection order."""
    return (
        "color: var(--klaus-text-muted) !important;"
        " background: transparent !important;"
        " border: 1px solid transparent !important;"
        " box-shadow: none !important;"
        " text-decoration: none !important;"
        f" font-family: {FONT_FAMILY};"
        " font-size: 13px !important;"
        " font-weight: 600;"
        " padding: 5px 12px !important;"
        " border-radius: 8px !important;"
    )


def _chip_hover_rules() -> str:
    """Chip hover: the translucent veil + text lifting to full."""
    return (
        "background: var(--klaus-hover) !important;"
        " color: var(--klaus-text) !important;"
        " border-color: transparent !important;"
        " text-decoration: none !important;"
    )


def _chip_active_rules() -> str:
    """Chip press: one veil step stronger."""
    return "background: var(--klaus-press) !important;"


def web_control_css(selector: str, accent: str = "var(--klaus-accent)") -> str:
    """Immediate press feedback and keyboard focus for a chrome control."""
    return f"""
    {selector} {{ font-optical-sizing: auto; touch-action: manipulation; }}
    {selector}:active {{ filter: brightness(0.92); transition: none; }}
    {selector}:focus-visible {{
        outline: 2px solid {accent} !important;
        outline-offset: 2px !important;
    }}
    @media (prefers-contrast: more) {{
        {selector} {{ outline: 1px solid currentColor; outline-offset: -1px; }}
    }}
    """


def toolbar_css() -> str:
    """Web CSS for Anki's top-toolbar webview (top_bar.py injects it via
    webview_will_set_content). RESTYLE ONLY — nothing is hidden or
    removed, so Anki's links, Klaus's Library link, and other addons'
    toolbar items (AnkiHub) keep working and inherit the look through
    the shared ``.hitem`` class. The bar reads as SynapsePro's nav rail
    turned horizontal: surface strip edge to edge, hairline bottom
    border, pill links, the star logo at the far left.

    THEME-REACTIVE BY CONSTRUCTION — takes no ``night`` argument on
    purpose. Anki's theme switch does NOT re-run
    ``webview_will_set_content``; it only runs JS on the live document
    (``documentElement.classList.add("night-mode")`` plus
    ``body.night_mode``/``nightMode``). A stylesheet baked from a
    ``night_mode()`` snapshot therefore goes stale the first time the
    user toggles the theme. So both palettes ship in one sheet, keyed
    on those classes — the same pattern Anki's own toolbar.css uses —
    and the bar (logo included, it fills ``var(--klaus-text)``)
    follows the theme instantly with no re-injection.
    """
    return f"""
    :root {{ {_toolbar_vars(palette(False), False)} }}
    :root.night-mode, body.night_mode, body.nightMode {{
        {_toolbar_vars(palette(True), True)}
    }}
    html, body {{
        background: var(--klaus-chrome) !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    /* ONE LAYER. Anki's "fancy" toolbar paints .toolbar as its own
       elevated card — canvas-elevated background, rounded bottom
       corners, box-shadow, backdrop blur — and gives every .hitem a
       glass button background. That inner card is the second layer.
       Flattened with !important because Anki's own selectors
       (body.fancy:not(.flat) .hitem = 0,3,1) outrank anything
       class-level an addon can write. Anki's layout grid is left
       alone; only paint and alignment change. */
    body.fancy {{ margin-bottom: 0 !important; }}
    .header .toolbar {{
        background: transparent !important;
        box-shadow: none !important;
        border-radius: 0 !important;
        backdrop-filter: none !important;
        overflow: visible !important;
    }}
    .header {{
        min-height: 44px;
        background: var(--klaus-chrome);
        /* No seam: the bar should read as one surface with the
           window's own title bar, so nothing is drawn between
           them and nothing under the bar either. */
        border-bottom: none !important;
        padding: 0 12px;
        box-sizing: border-box;
        /* Anki pins the trays to the TOP (align-items/align-self:
           start) — centre them so the logo and links sit on the bar's
           centre line. */
        align-items: center !important;
        align-content: center !important;
    }}
    .header .left-tray, .header .right-tray {{
        align-self: center !important;
        align-items: center !important;
    }}
    .header .tray-item {{
        display: flex !important;
        align-items: center !important;
    }}
    .header .hitem {{ {_chip_base_rules()} }}
    .header .hitem:hover {{ {_chip_hover_rules()} }}
    .header .hitem:active {{ {_chip_active_rules()} }}
    /* #klaus-logo carries its own geometry inline (top_bar.logo_html)
       so the star sits in the SAME spot whether or not this sheet is
       injected — the design gate must never move the mark. Nothing
       mode-specific is left to say about it here. */
    /* Other add-ons' toolbar items that draw their OWN chip artwork
       (rather than using .hitem) don't know about this bar's chrome.
       AMBOSS's `.amboss-indicator` is the case on hand: a baked-SVG
       toggle it absolutely-positions itself, with no class we can ask
       it to share. Two fixes, Klaus-side only — never touch the
       add-on itself: (1) its `top: 0.1em` was tuned for Anki's stock
       (shorter) toolbar; against this bar's 44px min-height that pins
       it too high, so re-centre it the same way every .hitem is
       centred, and give it the same 12px edge gutter as `.header`'s
       own padding. (2) its day-mode artwork bakes an opaque white
       pill — a white sticker on any chrome that isn't also white.
       `multiply` erases pure-white pixels against whatever is
       actually behind them while leaving the dark wordmark and the
       accent triangle alone, which is exactly the see-through effect
       a transparent chip would have had. The night variant ships its
       own deliberately-coloured badge with WHITE text on a navy fill
       instead — multiply there would blend that white text into the
       chrome too and erase the one thing that has to stay legible, so
       it ships untouched: a coloured badge, not a broken one. */
    .amboss-indicator {{
        top: 50% !important;
        right: 12px !important;
        transform: translateY(-50%) !important;
    }}
    .amboss-indicator.amboss-indicator-day {{
        mix-blend-mode: multiply;
    }}
    {web_control_css(".header .hitem")}
    """


def bottombar_css() -> str:
    """The bottom toolbar (deck-browser / overview buttons), matched to
    the top bar: same chrome colour, same both-palettes theme
    reactivity, and Anki's native ``<button>`` elements flattened into
    the top bar's glass-chip language — borderless and transparent at
    rest, the translucent hover/press veils on interaction, so the
    highlight tints whatever background is behind the bar. Injected by
    top_bar for ``DeckBrowserBottomBar``/``OverviewBottomBar`` contexts
    only; the reviewer's answer bar has its own sheet
    (:func:`reviewer_bar_css`, injected by window_chrome) built from
    the SAME chip blocks — its scheduling colours live in the count
    and interval spans, which that sheet deliberately never styles.
    """
    return f"""
    :root {{ {_toolbar_vars(palette(False), False)} }}
    :root.night-mode,
    body.night_mode,
    body.nightMode {{ {_toolbar_vars(palette(True), True)} }}
    html, body {{
        background: var(--klaus-chrome) !important;
        border: none !important;
    }}
    #header {{
        border: none !important;
        margin: 0 !important;
        padding: 5px 9px !important;
        background: transparent !important;
    }}
    /* The chips are the top bar's .hitem, verbatim — same shared
       declaration blocks, so "exactly the same" holds by construction.
       Only the <button>-specific native chrome strip is extra. */
    #header button {{
        -webkit-appearance: none !important;
        appearance: none !important;
        margin: 0 !important;
        {_chip_base_rules()}
    }}
    #header button:hover {{ {_chip_hover_rules()} }}
    #header button:active {{ {_chip_active_rules()} }}
    #header button:focus {{ outline: 0 !important; }}
    {web_control_css("#header button")}
    """


def css_vars(night: bool) -> str:
    """Theme tokens as CSS custom properties for webview surfaces
    (pdfjs_viewer.html's ``__THEME_VARS__`` substitution) — the same
    Qt-side tokens rendered for HTML, so webviews and widgets cannot
    drift (SynapsePro mirrors its palette into ``:root`` the same way).

    ``--hover-subtle`` is the webview half of the SAME hover fill every
    QSS builder reaches for (``panel_header_qss`` among them — all
    ``c['hover_subtle']``): the pdf.js findbar,
    annobar, context menu and thumbnail strip hover over ``--surface``
    exactly as their Qt siblings do, so the token, not a hand-mixed
    neutral, is what keeps the two halves of that family in step.
    pdfjs_viewer.html keeps a fallback for it, ordered so this
    definition wins — a safety net, not a second source of truth.

    ``--ink-*`` (K-149) is the highlight swatch palette: one var per
    :data:`HIGHLIGHT_INKS` entry, so the annobar's colour buttons carry
    no hex of their own (CLAUDE.md: UI files must not hardcode colours)
    and the page reads the chosen value straight back out of the
    custom property. Emitted IDENTICALLY in both modes — see the
    HIGHLIGHT_INKS comment: this is ink on the page, not chrome."""
    c = palette(night)
    inks = "".join(
        f" --ink-{name}: {value};" for name, value in HIGHLIGHT_INKS
    )
    return (
        f"--bg: {c['bg']};"
        f" --surface: {c['surface']};"
        f" --text: {c['text']};"
        f" --text-muted: {c['text_muted']};"
        f" --grey-light: {c['grey_light']};"
        f" --grey-mid: {c['grey_mid']};"
        f" --hover-subtle: {c['hover_subtle']};"
        f" --accent: {c['blue_bright']};"
        f" --accent-selection: {accent_rgba(night, 0.35)};"
        f" --font: {FONT_FAMILY};"
        + inks
    )


def muted_label_qss(night: bool, size_px: int = 11) -> str:
    """Inline style for secondary/status labels (SynapsePro's text_muted)."""
    c = palette(night)
    return f"color: {c['text_muted']}; font-size: {size_px}px;"


def status_bar_qss(night: bool) -> str:
    """The status bar along the bottom of the main window and Browse
    (VS Code's): chrome ground, ONE grey_light hairline on top (on Qt's
    QStatusBar, replacing the macOS panel line; the bar inside draws
    none), muted 11px text, the progress chunk in the accent."""
    c = palette(night)
    return f"""
    QStatusBar {{
        background-color: {c['chrome']};
        border: none;
        border-top: 1px solid {c['grey_light']};
    }}
    QStatusBar::item {{
        border: none;
    }}
    QWidget#KlausStatusBar {{
        background-color: {c['chrome']};
    }}
    QWidget#KlausStatusBar QLabel {{
        color: {c['text_muted']};
        font-size: 11px;
        background: transparent;
    }}
    QWidget#KlausStatusBar QLabel[error="true"] {{
        color: {c['red_text']};
    }}
    QWidget#KlausStatusBar QToolButton {{
        background: transparent;
        border: none;
        color: {c['text_muted']};
        padding: 0px 4px;
    }}
    QWidget#KlausStatusBar QToolButton#KlausBarAction {{
        color: {c['text']};
        font-size: 12px;
        padding: 1px 8px;
        border-radius: 5px;
    }}
    QWidget#KlausStatusBar QToolButton#KlausBarAction:hover {{
        background: {c['hover_subtle']};
    }}
    QWidget#KlausStatusBar QToolButton#KlausBarAction:pressed {{
        background: {c['grey_light']};
    }}
    QWidget#KlausStatusBar QProgressBar {{
        background-color: {c['grey_light']};
        border: none;
        border-radius: 2px;
        max-height: 4px;
    }}
    QWidget#KlausStatusBar QProgressBar::chunk {{
        background-color: {c['blue']};
        border-radius: 2px;
    }}
    """


# ─────────────────────────────────────────────────────────────────────────────
# Anki-window builders (the KlausBook layer beyond the deck screen).
# Consumed by window_chrome.py, gated on klausbook_design at the
# painters — these are pure strings and know nothing about the gate.
# ─────────────────────────────────────────────────────────────────────────────


def browse_qss(night: bool) -> str:
    """The Browse window, HARMONIZED — tokens, never transformation.

    Browse is Anki's densest work surface, so this sheet recolours and
    nothing else: table selection/hairlines, header typography, the
    search combo in the find bar's language. Layout, density and row
    heights stay Anki's. Deliberately unreachable and left semantic:
    the flag/marked/suspended row tints (delegate-painted from
    aqt.colors at paint time) and the Cards/Notes switch (custom
    paintEvent). The window background is EXPLICIT because Anki's
    optional "Anki" widget style ships an app-scope
    ``QWidget{background:none}`` — a widget-scope sheet with a real
    background survives it.

    Applied to the Browser instance by window_chrome (the sidebar tree
    needs its own instance sheet — see :func:`sidebar_tree_qss`).
    """
    c = palette(night)
    return f"""
    QMainWindow {{
        background-color: {c['bg']};
    }}
    QTableView {{
        background-color: {c['surface']};
        alternate-background-color: {c['surface']};
        color: {c['text']};
        border: none;
        gridline-color: {c['grey_light']};
        selection-background-color: {c['selection_bg']};
        selection-color: {c['text']};
    }}
    QHeaderView::section {{
        background: {c['surface']};
        color: {c['text_muted']};
        border: none;
        border-bottom: 1px solid {c['grey_light']};
        padding: 4px 6px;
        font-weight: 600;
    }}
    QComboBox#searchEdit {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 3px 8px;
    }}
    QComboBox#searchEdit:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    QComboBox#searchEdit::drop-down {{
        border: none;
        width: 18px;
    }}
    QComboBox#searchEdit QAbstractItemView {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_light']};
        selection-background-color: {c['selection_bg']};
        selection-color: {c['text']};
    }}
    QLineEdit {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 6px;
        padding: 2px 6px;
    }}
    QLineEdit:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    QSplitter::handle {{
        background: {c['grey_light']};
    }}
    QDockWidget {{
        background-color: {c['bg']};
    }}
    """


def sidebar_tree_qss(night: bool) -> str:
    """The Browse sidebar tree — an INSTANCE sheet, and that is the
    point: Anki's SidebarTreeView sets its own widget-level stylesheet
    and re-applies it on every theme flip, and a widget-level sheet
    beats any ancestor's. So this replaces Anki's wholesale, which
    means it must RE-DECLARE what Anki's carried (the padding and the
    zero border) or replacing it would visibly shift the tree.

    A selected tree ROW is two paint regions, not one: the BRANCH cell
    (the disclosure-arrow column) and the item. Styling only
    ``::item:selected`` left Qt painting the branch cell and the
    selection underlay with the palette highlight — system dark blue —
    which surfaced as dark fragments at the row's left edge, and
    peeked through the corner cutouts of a rounded item (live
    screenshot, 2026-08-29). Hence three rules here, not one:
    ``selection-background-color: transparent`` stops the style's own
    underlay painting entirely, the ``::branch`` states recolour the
    arrow column in step with the item, and the selection stays a
    FULL-WIDTH RECTANGLE — Anki's stock geometry, recoloured, which is
    what "harmonize" means, and square corners have nothing to leak
    through. ``outline: 0`` drops the style's dotted focus rect for
    the same reason; the selection colour itself carries focus, as it
    does in every macOS sidebar.
    """
    c = palette(night)
    return f"""
    QTreeView {{
        padding: 3px;
        padding-right: 0px;
        border: 0;
        background: {c['bg']};
        color: {c['text']};
        selection-background-color: transparent;
        show-decoration-selected: 1;
        outline: 0;
    }}
    QTreeView::item {{
        padding: 1px 0px;
    }}
    QTreeView::item:hover {{
        background: {c['hover_subtle']};
    }}
    QTreeView::item:selected {{
        background: {c['selection_bg']};
        color: {c['text']};
    }}
    QTreeView::branch {{
        background: transparent;
    }}
    QTreeView::branch:hover {{
        background: {c['hover_subtle']};
    }}
    QTreeView::branch:selected {{
        background: {c['selection_bg']};
    }}
    /* Styling ::branch at all hands the whole arrow column to the
       stylesheet, and Qt then draws NO disclosure arrow unless an image
       is given — the sidebar's folders showed no arrows at all. */
    /* Square SVGs with the chevron drawn small in the middle: Qt
       stretches a branch image over the whole indent cell. */
    QTreeView::branch:has-children:closed {{
        image: {_asset_url('branch-closed-night.svg' if night else 'branch-closed-day.svg')};
    }}
    QTreeView::branch:has-children:open {{
        image: {_asset_url('branch-open-night.svg' if night else 'branch-open-day.svg')};
    }}
    """


def utility_window_qss(night: bool) -> str:
    """Shared Qt chrome for Add Cards and the Stats dialog.

    Library polarity on purpose: these windows are rows of utility
    buttons (Add, Close, Help, History, the deck/notetype choosers,
    Save PDF) and a wall of blue would shout — grey secondary by
    default, with ONLY the dialog-default action (:default) taking the
    accent. Explicit window background for the same "Anki" widget
    style reason as :func:`browse_qss`.
    """
    c = palette(night)
    return f"""
    QMainWindow, QDialog {{
        background-color: {c['bg']};
    }}
    QLabel {{
        color: {c['text']};
        background: transparent;
    }}
    QPushButton {{
        background-color: {c['grey_light']};
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 5px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {c['grey_mid']};
    }}
    QPushButton:pressed {{
        background-color: {c['grey_dark']};
    }}
    QPushButton:focus, QPushButton:default:focus {{ border: 1px solid {c['blue_bright']}; }}
    QPushButton:default:pressed {{ background-color: {c['blue_pressed']}; }}
    QPushButton:disabled {{
        color: {c['text_faint']};
    }}
    QPushButton:default {{
        background-color: {c['blue']};
        color: white;
        border: 1px solid transparent;
    }}
    QPushButton:default:hover {{
        background-color: {c['blue_hover']};
    }}
    QComboBox {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 3px 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_light']};
        selection-background-color: {c['selection_bg']};
        selection-color: {c['text']};
    }}
    QLineEdit {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 3px 8px;
    }}
    QLineEdit:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    """


def editor_tags_qss(night: bool) -> str:
    """The legacy editor's Qt tag bar — another INSTANCE sheet, for
    the same reason as the sidebar tree: Anki gives the group box and
    the TagEdit widget-level sheets, so only a sheet on the widgets
    themselves can restyle them. TagEdit extends QLineEdit, so the
    input rule reaches it by class.
    """
    c = palette(night)
    return f"""
    QGroupBox {{
        border: none;
        background: transparent;
    }}
    QLabel {{
        color: {c['text_muted']};
        background: transparent;
    }}
    QLineEdit {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 3px 8px;
    }}
    QLineEdit:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    """


def reviewer_bar_css() -> str:
    """The reviewer's bottom bar — CHROME ONLY, and the scheduling
    semantics survive BY OMISSION: this sheet contains no rule for the
    count spans or the interval labels above the buttons, so their
    colours pass through untouched. The buttons themselves were never
    coloured by Anki (verified: they are generic <button>s inheriting
    the platform sheet) — reshaping them into the Klaus chip language
    changes shape, not meaning.

    Same both-palettes/no-argument contract as :func:`toolbar_css`,
    and the chips are the SAME shared declaration blocks the top and
    deck bottom bars use, so all three bars agree by construction.
    Flat chrome on purpose — no frosted background copy here: the
    reviewer's main webview is deliberately wallpaper-free, and a
    frosted photo strip under a flat card screen would read detached.
    """
    return f"""
    :root {{ {_toolbar_vars(palette(False), False)} }}
    :root.night-mode,
    body.night_mode,
    body.nightMode {{ {_toolbar_vars(palette(True), True)} }}
    html, body {{
        background: var(--klaus-chrome) !important;
        border: none !important;
    }}
    #outer {{
        border-top: none !important;
        background: transparent !important;
    }}
    button {{
        -webkit-appearance: none !important;
        appearance: none !important;
        {_chip_base_rules()}
    }}
    button:hover {{ {_chip_hover_rules()} }}
    button:active {{ {_chip_active_rules()} }}
    button:focus {{ outline: 0 !important; border: none !important; }}
    button:focus-visible {{
        outline: 2px solid var(--klaus-accent) !important;
        outline-offset: 1px !important;
    }}
    {web_control_css("button")}
    """


def editor_css() -> str:
    """The editor webview (Add Cards, Browse, Edit Current) —
    harmonization for the chrome AROUND the fields: toolbar strip on
    the window ground, field containers as quiet hairline cards with
    an accent focus, muted field labels. The fields' CONTENT is the
    user's card text and is never styled. Both palettes keyed on the
    night classes AnkiWebView flips live; injected via
    ``web_content.head``, which lands after css/editor.css and wins
    ties without needing !important.
    """
    light = palette(False)
    dark = palette(True)
    def vars_for(c: dict) -> str:
        return (
            f"--klaus-bg: {c['bg']};"
            f" --klaus-surface: {c['surface']};"
            f" --klaus-border: {c['grey_light']};"
            f" --klaus-border-mid: {c['grey_mid']};"
            f" --klaus-text-muted: {c['text_muted']};"
            f" --klaus-accent: {c['blue_bright']};"
        )
    return f"""
    :root {{ {vars_for(light)} }}
    :root.night-mode,
    body.night_mode,
    body.nightMode {{ {vars_for(dark)} }}
    .editor-toolbar,
    .button-toolbar {{
        background: var(--klaus-bg);
    }}
    .field-container {{
        border: 1px solid var(--klaus-border);
        border-radius: 8px;
    }}
    .field-container:focus-within {{
        border-color: var(--klaus-accent);
    }}
    .label-container {{
        color: var(--klaus-text-muted);
        font-size: 11px;
    }}
    {web_control_css(".editor-toolbar button")}
    {web_control_css(".button-toolbar button")}
    """


def stats_css() -> str:
    """The Stats (graphs) page — variables only, and ONLY the
    structural ones: page ground, graph-card surface, hairlines. The
    page's components consume Anki's own custom properties, so
    harmonizing means overriding four vars, not fighting sveltekit
    markup. Never touched: every ``--fg`` variable and every
    graph-semantic colour (young/mature/ease series carry meaning).
    Injected post-load by window_chrome through
    ``webview_did_inject_style_into_page``.
    """
    light = palette(False)
    dark = palette(True)
    def vars_for(c: dict) -> str:
        return (
            f"--canvas: {c['bg']};"
            f" --canvas-elevated: {c['surface']};"
            f" --border: {c['grey_light']};"
            f" --border-subtle: {c['grey_light']};"
        )
    return f"""
    :root {{ {vars_for(light)} }}
    :root.night-mode {{ {vars_for(dark)} }}
    """
