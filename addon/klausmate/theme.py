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


def palette(night: bool) -> dict:
    """The colour-token dict for *night* mode (a copy — mutate freely)."""
    return (DARK if night else LIGHT).copy()


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


def _toolbar_vars(c: dict) -> str:
    """One palette as Klaus custom properties for the toolbar."""
    return (
        f"--klaus-surface: {c['surface']};"
        f" --klaus-border: {c['grey_light']};"
        f" --klaus-text: {c['text']};"
        f" --klaus-text-muted: {c['text_muted']};"
        f" --klaus-hover: {c['hover_subtle']};"
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
    :root {{ {_toolbar_vars(palette(False))} }}
    :root.night-mode, body.night_mode, body.nightMode {{
        {_toolbar_vars(palette(True))}
    }}
    html, body {{
        background: var(--klaus-surface) !important;
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
        background: var(--klaus-surface);
        border-bottom: 1px solid var(--klaus-border) !important;
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
    #klaus-logo {{
        display: flex;
        align-items: center;
        padding: 0 8px 0 2px;
        cursor: pointer;
    }}
    #klaus-logo svg {{ display: block; }}
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
