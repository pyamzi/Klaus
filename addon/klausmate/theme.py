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
    "selection_bg": "#E4F2FF",   # Tree/table row selection

    # ── Text ─────────────────────────────────────────────────────────────
    "text":         "#1D1D1F",   # Primary body text
    "text_muted":   "#86868B",   # Secondary labels, hints, status lines
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

    # ── Green (success) ──────────────────────────────────────────────────
    "green":        "#28CD41",
    "green_bg":     "#1E3A2E",
    "green_border": "#2D5A45",
}


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

def dialog_qss(night: bool) -> str:
    """Dialog foundation (Manage models, future dialogs).

    SynapsePro's settings-dialog language: window on ``bg``, every
    QGroupBox a white card (12px radius, 1px ``grey_light`` border),
    buttons blue-primary by default with rounded 8px corners; a button
    named ``SecondaryButton`` gets the grey treatment instead.
    """
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
        background-color: {c['blue']};
        color: white;
        border: {c['blue_border']};
        border-radius: 8px;
        padding: 6px 16px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: {c['blue_hover']}; }}
    QPushButton:pressed {{ background-color: {c['blue_pressed']}; }}
    QPushButton:disabled {{
        background-color: {c['grey_light']};
        color: {c['text_faint']};
    }}
    QPushButton#SecondaryButton {{
        background-color: {c['grey_light']};
        color: {c['text']};
        border: none;
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
    QComboBox, QLineEdit {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 4px 8px;
    }}
    QComboBox:focus, QLineEdit:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    QComboBox::drop-down {{ border: none; width: 25px; }}
    QComboBox QAbstractItemView {{
        background-color: {c['surface']};
        color: {c['text']};
        selection-background-color: {c['selection_bg']};
        selection-color: {c['text']};
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
       identity plus one checkable NavItem pill per page, a large
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
        font-family: "EB Garamond", Garamond, "Apple Garamond", Georgia, serif;
        font-size: 18px;
        font-weight: 300;
    }}
    QLabel#SidebarVersion {{ color: {c['text_muted']}; font-size: 11px; }}
    QLineEdit#SettingsSearch {{
        background-color: {c['surface']};
        border: 1px solid {c['grey_light']};
        border-radius: 8px;
        padding: 4px 10px;
        font-size: 12px;
    }}
    QPushButton#NavItem {{
        background-color: transparent;
        color: {c['text']};
        border: none;
        border-radius: 8px;
        padding: 6px 12px;
        font-weight: 600;
        text-align: left;
    }}
    QPushButton#NavItem:hover {{ background-color: {c['hover_subtle']}; }}
    QPushButton#NavItem:disabled {{
        background-color: transparent;
        color: {c['text_faint']};
    }}
    QPushButton#NavItem:checked {{
        background-color: {accent_rgba(night, 0.16)};
        color: {c['blue']};
    }}
    QLabel#PageTitle {{ font-size: 24px; font-weight: 800; }}
    QLabel#PageSubtitle {{ color: {c['text_muted']}; font-size: 12px; }}
    QLabel#SettingName {{ font-size: 13px; font-weight: 600; }}
    QLabel#SettingDesc {{ color: {c['text_muted']}; font-size: 11px; }}
    QFrame#RowSeparator {{
        background-color: {c['grey_light']};
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
        border-radius: 5px;
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
       Appearance page disables Fit/Bar blur/Choose image unless the
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
        border: none;
        border-radius: 6px;
        padding: 2px 6px;
    }}
    QWidget#KlausPanelHeader QToolButton:hover {{
        background: {c['hover_subtle']};
        color: {c['text']};
    }}
    QWidget#KlausPanelHeader QToolButton:pressed {{
        background: {c['grey_mid']};
    }}
    """


def find_bar_qss(night: bool) -> str:
    """The viewer's find bar, objectName ``KlausFindBar`` — surface strip,
    rounded input with an accent focus ring, borderless nav glyphs."""
    c = palette(night)
    return f"""
    QWidget#KlausFindBar {{
        background-color: {c['surface']};
        border-bottom: 1px solid {c['grey_light']};
    }}
    QWidget#KlausFindBar QLineEdit {{
        background-color: {c['bg']};
        color: {c['text']};
        border: 1px solid {c['grey_mid']};
        border-radius: 8px;
        padding: 3px 8px;
    }}
    QWidget#KlausFindBar QLineEdit:focus {{
        border: 1px solid {c['blue_bright']};
    }}
    QWidget#KlausFindBar QToolButton {{
        background: transparent;
        color: {c['text_muted']};
        border: none;
        border-radius: 6px;
        padding: 1px 6px;
        font-weight: 600;
    }}
    QWidget#KlausFindBar QToolButton:hover {{
        background: {c['hover_subtle']};
        color: {c['text']};
    }}
    """


def library_qss(night: bool) -> str:
    """The Library window (DriveWindow): window on ``bg``, the tree a
    white card with rounded corners and quiet selection, buttons
    secondary-grey by default (``PrimaryButton`` opts into blue —
    inverse of :func:`dialog_qss`, because the Library's row of utility
    buttons must not scream)."""
    c = palette(night)
    return f"""
    QWidget#KlausLibraryWindow {{
        background-color: {c['bg']};
        color: {c['text']};
    }}
    QWidget#KlausLibraryWindow QTreeWidget {{
        background-color: {c['surface']};
        alternate-background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['grey_light']};
        border-radius: 12px;
        padding: 4px;
    }}
    QWidget#KlausLibraryWindow QTreeWidget::item {{
        border-radius: 6px;
        padding: 2px 0px;
    }}
    QWidget#KlausLibraryWindow QTreeWidget::item:hover {{
        background: {c['hover_subtle']};
    }}
    QWidget#KlausLibraryWindow QTreeWidget::item:selected {{
        background: {c['selection_bg']};
        color: {c['text']};
    }}
    QWidget#KlausLibraryWindow QHeaderView::section {{
        background: transparent;
        color: {c['text_muted']};
        border: none;
        border-bottom: 1px solid {c['grey_light']};
        padding: 4px 6px;
        font-weight: 600;
    }}
    QWidget#KlausLibraryWindow QPushButton {{
        background-color: {c['grey_light']};
        color: {c['text']};
        border: none;
        border-radius: 8px;
        padding: 5px 14px;
        font-weight: 600;
    }}
    QWidget#KlausLibraryWindow QPushButton:hover {{
        background-color: {c['grey_mid']};
    }}
    QWidget#KlausLibraryWindow QPushButton:pressed {{
        background-color: {c['grey_dark']};
    }}
    QWidget#KlausLibraryWindow QPushButton#PrimaryButton {{
        background-color: {c['blue']};
        color: white;
        border: {c['blue_border']};
    }}
    QWidget#KlausLibraryWindow QPushButton#PrimaryButton:hover {{
        background-color: {c['blue_hover']};
    }}
    """


def thumb_strip_qss(night: bool) -> str:
    """The viewer's page-thumbnail strip, objectName ``KlausThumbStrip``:
    page-bg column, items as rounded cards, accent ring on the current
    page's selection."""
    c = palette(night)
    return f"""
    QListWidget#KlausThumbStrip {{
        background-color: {c['bg']};
        border: none;
        border-right: 1px solid {c['grey_light']};
        padding: 6px;
    }}
    QListWidget#KlausThumbStrip::item {{
        border: 2px solid transparent;
        border-radius: 8px;
        margin: 3px 2px;
        color: {c['text_muted']};
    }}
    QListWidget#KlausThumbStrip::item:hover {{
        background: {c['hover_subtle']};
    }}
    QListWidget#KlausThumbStrip::item:selected {{
        background: {c['selection_bg']};
        border: 2px solid {c['blue_bright']};
    }}
    """


def drop_zone_qss(night: bool, object_name: str) -> str:
    """The shared drop-square language (Library drop zone; the deck-screen
    squares in deck_curate render the same values as HTML). Dashed grey
    idle border that turns solid accent on drag-over."""
    c = palette(night)
    return f"""
    #{object_name} {{
        border: 1px dashed {c['grey_mid']};
        border-radius: 10px;
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
    and the bar (logo included, it strokes ``var(--klaus-accent)``)
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
    .header .hitem {{
        color: var(--klaus-text-muted) !important;
        background: transparent !important;
        border: 1px solid transparent !important;
        box-shadow: none !important;
        text-decoration: none !important;
        font-family: {FONT_FAMILY};
        font-size: 13px;
        font-weight: 600;
        padding: 5px 12px !important;
        border-radius: 8px;
    }}
    .header .hitem:hover {{
        background: var(--klaus-hover) !important;
        color: var(--klaus-text) !important;
        border-color: transparent !important;
        text-decoration: none !important;
    }}
    .header .hitem:active {{
        background: var(--klaus-press) !important;
    }}
    #klaus-logo {{
        display: flex;
        align-items: center;
        padding: 0 8px 0 2px;
        cursor: pointer;
    }}
    #klaus-logo svg {{ display: block; }}
    """


def bottombar_css() -> str:
    """The bottom toolbar (deck-browser / overview buttons), matched to
    the top bar: same chrome colour, same both-palettes theme
    reactivity, and Anki's native ``<button>`` elements flattened into
    the top bar's glass-chip language — borderless and transparent at
    rest, the translucent hover/press veils on interaction, so the
    highlight tints whatever background is behind the bar. Injected by
    top_bar for ``DeckBrowserBottomBar``/``OverviewBottomBar`` contexts
    only; the reviewer's answer bar keeps Anki's own styling (its
    colours carry scheduling meaning).
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
    button {{
        -webkit-appearance: none;
        appearance: none;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        color: var(--klaus-text-muted);
        font-family: {FONT_FAMILY};
        font-size: 13px;
        font-weight: 600;
        padding: 5px 12px;
        margin: 0 2px;
        cursor: pointer;
        transition: background 120ms ease, color 120ms ease;
    }}
    button:hover {{
        background: var(--klaus-hover);
        color: var(--klaus-text);
    }}
    button:active {{ background: var(--klaus-press); }}
    button:focus {{ outline: 0; }}
    """


def css_vars(night: bool) -> str:
    """Theme tokens as CSS custom properties for webview surfaces
    (pdfjs_viewer.html's ``__THEME_VARS__`` substitution) — the same
    Qt-side tokens rendered for HTML, so webviews and widgets cannot
    drift (SynapsePro mirrors its palette into ``:root`` the same way)."""
    c = palette(night)
    return (
        f"--bg: {c['bg']};"
        f" --surface: {c['surface']};"
        f" --text: {c['text']};"
        f" --text-muted: {c['text_muted']};"
        f" --grey-light: {c['grey_light']};"
        f" --grey-mid: {c['grey_mid']};"
        f" --accent: {c['blue_bright']};"
        f" --accent-selection: {accent_rgba(night, 0.35)};"
        f" --font: {FONT_FAMILY};"
    )


def muted_label_qss(night: bool, size_px: int = 11) -> str:
    """Inline style for secondary/status labels (SynapsePro's text_muted)."""
    c = palette(night)
    return f"color: {c['text_muted']}; font-size: {size_px}px;"
