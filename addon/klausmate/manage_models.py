"""KlausMate Preferences dialog: the two API keys and the three model
names, the Library folder, and the KlausBook appearance layer.

Extracted verbatim from __init__.py (K-023, slice 1 of the K-006 file
split). Backs Tools > KlausMate Preferences — the single Tools-menu entry
point (K-045 folded the old 'Klaus' submenu's three items in here).

Since the API-first reversal (2026-09-15, spec D1) Klaus talks to exactly
two services with the user's own keys — OpenAI for embeddings and lecture
transcription, and Anthropic, whose key is STORED for the spec's Plans 2
and 3 (card pertinence, the assistant on the Messages API) and read by
nothing today: the assistant still runs on the user's own Claude Code
login. So the
old Semantic Search page (a provider combo fanned out over three
per-provider key slots) and the whole "Local model library (Ollama)" page
with its install / pull / delete / classify machinery are gone, together
with the runtime they managed. One page, "API keys & models", holds what
is left, and it is also where a changed embedding model or a first OpenAI
key offers the whole-collection re-embed sweep, priced by cost.py before
anything is spent.

This module is imported by __init__.py at package load time, so it must
never import __init__ (this package) at module load — only from inside a
function, after the package has finished loading. _pkg() below is that
lazy accessor (same pattern as curation.py's _pkg()); it reaches config
and helpers that live in __init__.py: get_config, write_config,
open_config.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QStackedWidget,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import showInfo, showWarning, tooltip

from .md3_switch import Md3Switch


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _addon_version() -> str:
    """human_version from manifest.json, "" when unreadable."""
    try:
        import json
        import os

        path = os.path.join(os.path.dirname(__file__), "manifest.json")
        with open(path, encoding="utf-8") as fh:
            return str(json.load(fh).get("human_version") or "")
    except Exception:
        return ""


def _logo_pixmap(size: int, dpr: float = 2.0) -> Any:
    """The Klaus impossible star for the Preferences sidebar, drawn
    exactly like the top bar's: five FILLED shapes in the accent colour
    on a transparent ground — no icon-square treatment — from the same
    top_bar.star_polygons() data the toolbar's SVG fills.

    ``dpr`` comes from the label that will show it, so the mark is
    crisp on whatever screen the dialog opened on rather than on an
    assumed Retina one; 2.0 is only the fallback for a caller with no
    widget to ask.

    ONE QPainterPath with WindingFill, not five drawPolygon calls:
    winding is SVG's own default fill rule, so a self-crossing arm
    fills here the way it fills in klaus-logo.svg. Qt's polygon default
    is odd-even, which would punch holes the drawing does not have.
    """
    try:
        from aqt.qt import (
            QColor,
            QPainter,
            QPainterPath,
            QPixmap,
            QPointF,
            QPolygonF,
            Qt,
        )

        from . import theme as _theme
        from . import top_bar as _top_bar

        px = QPixmap(int(size * dpr), int(size * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(QColor(0, 0, 0, 0))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = _theme.palette(_theme.night_mode())
        # The same margin the stroked mark left: half the old pen width
        # on every side, so the star keeps its seat in the 24px row.
        inset = max(1.3, size * 0.09) / 2.0
        scale = (size - inset * 2.0) / _top_bar.STAR_VIEWBOX
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for poly in _top_bar.star_polygons():
            path.addPolygon(
                QPolygonF(
                    [
                        QPointF(x * scale + inset, y * scale + inset)
                        for x, y in poly
                    ]
                )
            )
            path.closeSubpath()
        painter.fillPath(path, QColor(c["blue_accent"]))
        painter.end()
        return px
    except Exception as exc:
        print(f"[klausmate] sidebar logo failed: {exc}")
        return None


def _elide_middle(name: str, max_len: int = 44) -> str:
    """Middle-elide a long filename for the image captions.

    Word wrap cannot break an unbroken token, so one long stored
    filename (they arrive as e.g. hf_20260827_161844_<uuid>.jpg) sets
    the page's minimum width and brings back the horizontal scrollbar
    the captions were cured of. The middle goes because the ends are
    the identifying parts: prefix and extension. Full name lives in
    the tooltip."""
    if len(name) <= max_len:
        return name
    keep = (max_len - 1) // 2
    return f"{name[:keep]}…{name[-keep:]}"


def _image_thumb(path: str, w: int = 88, h: int = 54) -> Any:
    """A small rounded preview of a stored background image, for the
    Appearance captions (Pouya: "I want to be able to see a thumbnail
    of the image as well in the settings panel"). Centre-cropped to
    w×h, clipped to the design scale's 6px chip radius, rendered at 2×
    for retina (harmless at 1×). None when the file is missing or
    unreadable — the caller hides the label, it never shows a broken
    frame."""
    try:
        from aqt.qt import QPainter, QPainterPath, QPixmap

        src = QPixmap(path)
        if src.isNull():
            return None
        dpr = 2
        pw, ph = w * dpr, h * dpr
        scaled = src.scaled(
            pw,
            ph,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cropped = scaled.copy(
            max(0, (scaled.width() - pw) // 2),
            max(0, (scaled.height() - ph) // 2),
            pw,
            ph,
        )
        out = QPixmap(pw, ph)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(0.0, 0.0, float(pw), float(ph), 6.0 * dpr, 6.0 * dpr)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        out.setDevicePixelRatio(dpr)
        return out
    except Exception as exc:
        print(f"[klausmate] background thumb failed: {exc}")
        return None


class _KlausManageDialog(QDialog):
    """QDialog whose EVERY close path goes through the confirm callback.

    Esc triggers QDialog.reject() and the title-bar ✕ triggers closeEvent —
    neither hits a Close button's clicked signal. Without routing them
    through confirm_close, a running card-index build would keep
    embedding — and billing — invisibly after the dialog vanishes, and
    unsaved preference edits would be discarded without a word.
    """

    confirm_close_cb: Callable[[], None] | None = None

    def reject(self) -> None:  # Esc key
        if self.confirm_close_cb is not None:
            self.confirm_close_cb()
        else:
            super().reject()

    def closeEvent(self, event: Any) -> None:  # title-bar ✕
        if self.confirm_close_cb is not None:
            event.ignore()
            self.confirm_close_cb()
        else:
            super().closeEvent(event)


# ── DIAGNOSTIC (2026-08-26) ──────────────────────────────────────────────
# The Preferences dialog segfaults on macOS 26.5 + Qt 6.11 the instant it
# first flushes its backing store to screen (QPaintDevice::devicePixelRatio
# on a null paint device inside QBackingStore::flush) — whether shown
# app-modal (exec) or window-modal (open), so modality is NOT the cause.
# CONFIRMED: a bare QDialog(mw) opens fine, so this is NOT a platform-wide
# Qt/Cocoa bug — the fault is in THIS dialog's styling or widgets. The
# probe now adds one variable per stage so a single restart localizes it:
#   1  bare dialog ............................. FINE
#   2  + our top-level dialog_qss stylesheet ... FINE
#   3  + one MD3 switch (newest custom paint) .. CRASHED  <- culprit
# Root cause and fix live in md3_switch._animate_to: setChecked() during
# dialog build started the switch's animation, which repainted it while
# the window was still being composited. FIXED — probe left in place
# (off) because it localized this in three restarts and would do so
# again; flip _BARE_DIALOG_PROBE True and pick a stage to re-bisect.
_BARE_DIALOG_PROBE = False
_PROBE_STAGE = 3
_PROBE_KEEPALIVE: list = []

# The one live Preferences window (None when closed). Non-modal since
# 2026-08-30, so the star can be clicked while it is already open —
# this is what lets that front the existing window instead of stacking
# a second one (two dialogs would fight over the preview seam and race
# each other's Save).
_OPEN_DLG: Any = None


def _run_dialog_probe() -> None:
    """Staged bisection of the Preferences backing-store crash. Each stage
    is the previous one plus exactly one new variable; whichever stage
    first fails to appear (Anki dies) is where the fault lives."""
    from . import theme

    probe = QDialog(mw)
    probe.setWindowTitle(f"KlausMate diagnostic — stage {_PROBE_STAGE}")
    lay = QVBoxLayout(probe)
    note = QLabel("Stage 1: bare dialog (already known good).")
    note.setWordWrap(True)
    lay.addWidget(note)

    if _PROBE_STAGE >= 2:
        # The stylesheet is applied to the top-level QDialog, so it acts on
        # the whole window's backing store — the exact thing that crashes.
        probe.setStyleSheet(theme.dialog_qss(theme.night_mode()))
        note.setText(
            "Stage 2: the Preferences stylesheet is applied to this "
            "window. If you can read this, our stylesheet is NOT the "
            "cause — tell me and I'll test the MD3 switches next."
        )
    if _PROBE_STAGE >= 3:
        from .md3_switch import Md3Switch

        # Parented construction on purpose: the bare-parens spelling is a
        # counted source pin in test_md3_switch (exactly three real ones).
        sw = Md3Switch(probe)
        sw.setChecked(True)
        lay.addWidget(sw)
        note.setText(
            "Stage 3: an MD3 switch (the newest custom-painted widget) is "
            "added. If you can read this, the switch paint is NOT the "
            "cause — tell me and I'll test the sidebar next."
        )
    if _PROBE_STAGE >= 4:
        # The sidebar shell: star PIXMAP (drawn with its own QPainter at
        # dpr 2.0 — a second paint device, the prime suspect if we get
        # this far), wordmark, search field, nav list, stacked pages.
        from aqt.qt import (
            QFrame,
            QHBoxLayout,
            QLineEdit,
            QListWidget,
            QStackedWidget,
        )

        row = QHBoxLayout()
        sidebar = QFrame()
        sidebar.setObjectName("SettingsSidebar")
        sidebar.setFixedWidth(192)
        side = QVBoxLayout(sidebar)
        logo_lbl = QLabel()
        _logo = _logo_pixmap(24, logo_lbl.devicePixelRatioF())
        if _logo is not None:
            logo_lbl.setPixmap(_logo)
        logo_lbl.setFixedSize(24, 24)
        side.addWidget(logo_lbl)
        wordmark = QLabel("KlausMate")
        wordmark.setObjectName("SidebarAppName")
        side.addWidget(wordmark)
        search = QLineEdit()
        search.setObjectName("SettingsSearch")
        search.setPlaceholderText("Search")
        search.setClearButtonEnabled(True)
        side.addWidget(search)
        nav = QListWidget()
        nav.setObjectName("SettingsNav")
        nav.addItem("General")
        side.addWidget(nav)
        row.addWidget(sidebar)
        row.addWidget(QStackedWidget(), 1)
        lay.addLayout(row)
        note.setText(
            "Stage 4: the sidebar shell (star pixmap, wordmark, search, "
            "nav list, stacked pages). If you can read this, the shell is "
            "NOT the cause — tell me and I'll bisect the pages next."
        )

    probe.resize(440, 200)
    _PROBE_KEEPALIVE.append(probe)  # non-modal: outlive this call
    probe.open()
    print(f"[klausmate] dialog probe stage {_PROBE_STAGE} shown — "
          "backing-store flush did NOT crash")


def manage_models_dialog(*_args: Any) -> None:
    """Open (or front) the one Preferences window.

    ``*_args`` because a QAction's ``triggered`` signal hands its slot a
    ``checked`` bool: the old ``setup`` parameter used to absorb it, and
    dropping it outright would have turned every Tools-menu click into a
    TypeError.
    """
    if _BARE_DIALOG_PROBE:
        try:
            _run_dialog_probe()
        except Exception as exc:
            print(f"[klausmate] dialog probe failed: {exc}")
        return

    global _OPEN_DLG
    if _OPEN_DLG is not None:
        try:
            if _OPEN_DLG.isVisible():
                _OPEN_DLG.raise_()
                _OPEN_DLG.activateWindow()
                return
        except Exception:
            pass  # a dead/half-torn-down window: fall through and rebuild
        _OPEN_DLG = None

    dlg = _KlausManageDialog(mw)
    dlg.setWindowTitle("KlausMate Preferences")
    dlg.setMinimumWidth(480)
    dlg.resize(960, 680)
    # SynapsePro dialog language (theme.dialog_qss): window on bg, group
    # boxes as white cards, blue-primary buttons (objectName
    # SecondaryButton/DangerButton opt out per button below).
    try:
        from . import theme as _theme

        _night = _theme.night_mode()
        dlg.setStyleSheet(_theme.dialog_qss(_night))
        _MUTED = _theme.muted_label_qss(_night, 11)
    except Exception as _exc:
        print(f"[klausmate] preferences theme failed: {_exc}")
        _MUTED = "color: rgba(140,140,140,0.95); font-size: 11px;"
    outer = QVBoxLayout(dlg)
    # Edge-to-edge: the sidebar must run into the window edges and
    # down to the button-bar hairline; the footer carries its own
    # margins instead.
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    # ----- The settings shell ---------------------------------------------
    # One page of pages: the sidebar's nav list on the left, the stack of
    # settings pages on the right. There is no outer stack any more — the
    # "Set up local AI" page that used to sit in front of this one went
    # with the local runtime it installed.
    models_page = QWidget()
    models_page_layout = QVBoxLayout(models_page)
    models_page_layout.setContentsMargins(0, 0, 0, 0)

    # SynapsePro's CURRENT settings shell (K-106, built from Pouya's
    # screenshot of their 1.5.x window — the vendored source only has
    # the older card grid this replaced): a fixed sidebar on the left
    # carrying the app identity and one checkable pill per page, and a
    # QStackedWidget of pages on the right. Each page is a large title
    # + muted subtitle over ONE rounded #CardFrame group inside a
    # transparent scroll area, and each simple setting is a _row():
    # bold name + muted description on the left, its control pinned
    # right, hairline-separated.
    from aqt.qt import QFrame, QScrollArea

    body = QHBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(0)
    models_page_layout.addLayout(body)

    sidebar = QFrame()
    sidebar.setObjectName("SettingsSidebar")
    sidebar.setFixedWidth(192)
    side_lay = QVBoxLayout(sidebar)
    side_lay.setContentsMargins(10, 14, 10, 12)
    side_lay.setSpacing(2)

    # Identity: the star logo beside the Garamond "KlausMate" wordmark,
    # version under it, then a search field that filters the setting
    # rows across every page (macOS System Settings pattern).
    head_row = QHBoxLayout()
    head_row.setContentsMargins(0, 0, 0, 0)
    head_row.setSpacing(7)
    logo_lbl = QLabel()
    _logo = _logo_pixmap(24, logo_lbl.devicePixelRatioF())
    if _logo is not None:
        logo_lbl.setPixmap(_logo)
    logo_lbl.setFixedSize(24, 24)
    head_row.addWidget(logo_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
    name_col = QVBoxLayout()
    name_col.setContentsMargins(0, 0, 0, 0)
    name_col.setSpacing(0)
    app_name_lbl = QLabel("KlausMate")
    app_name_lbl.setObjectName("SidebarAppName")
    name_col.addWidget(app_name_lbl)
    _ver = _addon_version()
    if _ver:
        ver_lbl = QLabel(f"Version {_ver}")
        ver_lbl.setObjectName("SidebarVersion")
        name_col.addWidget(ver_lbl)
    head_row.addLayout(name_col, 1)
    side_lay.addLayout(head_row)
    side_lay.addSpacing(10)

    search_edit = QLineEdit()
    search_edit.setObjectName("SettingsSearch")
    search_edit.setPlaceholderText("Search")
    search_edit.setClearButtonEnabled(True)
    side_lay.addWidget(search_edit)
    side_lay.addSpacing(8)

    pages = QStackedWidget()
    body.addWidget(sidebar)
    body.addWidget(pages, 1)

    # The nav is ONE QListWidget, not per-page buttons. Three rounds of
    # pill-mush fixes (QSS margins, layout spacing, fixed heights) all
    # fought the same disease: four separately-polished checkable
    # QPushButtons, each free to lay out/paint differently on first
    # show vs after a restyle. A single list view with delegate-drawn
    # rows and hard setSizeHint geometry has one style path and one
    # layout pass — the bug class has no surface left.
    nav_list = QListWidget()
    nav_list.setObjectName("SettingsNav")
    nav_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
    # Tab reaches the nav, arrows switch pages (currentRowChanged
    # already drives the stack) — NoFocus made the whole page-switcher
    # keyboard-unreachable (critique P1). The native focus rect is
    # suppressed in QSS; the selected row's tint is the focus story.
    nav_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    nav_list.setSpacing(3)
    nav_list.setCursor(Qt.CursorShape.PointingHandCursor)
    nav_list.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    nav_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    _nav_items: dict[str, QListWidgetItem] = {}
    _nav_state = {"label": ""}
    _page_index: dict[str, int] = {}
    _page_haystack: dict[str, str] = {}
    _rows_by_page: dict[str, list[QWidget]] = {}
    _nav_order: list[str] = []

    def _select_page(label: str) -> None:
        pages.setCurrentIndex(_page_index[label])
        _nav_state["label"] = label
        item = _nav_items.get(label)
        if item is not None and nav_list.currentItem() is not item:
            nav_list.setCurrentItem(item)

    def _on_nav_row(row: int) -> None:
        item = nav_list.item(row)
        if item is None:
            # Clicking blank viewport clears the selection — reassert
            # the current page so exactly one row is always selected.
            if _nav_state["label"]:
                _select_page(_nav_state["label"])
            return
        label = str(item.text())
        _nav_state["label"] = label
        pages.setCurrentIndex(_page_index[label])

    nav_list.currentRowChanged.connect(_on_nav_row)

    def _page(nav_label: str, title: str, subtitle: str) -> QVBoxLayout:
        """One settings page + its sidebar pill. Returns the layout of
        the page's rounded group — call sites append to it exactly like
        the old per-card layouts. Sidebar placement is deferred to
        _finish_nav so display order is decoupled from build order."""
        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(24, 18, 24, 8)
        page_lay.setSpacing(4)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("PageTitle")
        page_lay.addWidget(title_lbl)
        sub_lbl = QLabel(subtitle)
        sub_lbl.setObjectName("PageSubtitle")
        sub_lbl.setWordWrap(True)
        page_lay.addWidget(sub_lbl)
        page_lay.addSpacing(8)

        scroll = QScrollArea()
        scroll.setObjectName("ContentScrollArea")
        scroll.setWidgetResizable(True)
        # Never sideways (Pouya: "It's so annoying to have to scroll
        # horizontally") — pages scroll vertically only, like the nav.
        # Content must WRAP into the viewport instead: every caption
        # label word-wraps, and long unbroken filenames are elided
        # (_elide_middle), because one unwrappable line is all it
        # takes to push the page's minimum width past the window.
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        group = QFrame()
        group.setObjectName("CardFrame")
        group_lay = QVBoxLayout(group)
        group_lay.setContentsMargins(16, 6, 16, 6)
        group_lay.setSpacing(0)
        inner_lay.addWidget(group)
        inner_lay.addStretch(1)
        scroll.setWidget(inner)
        page_lay.addWidget(scroll, 1)

        _page_index[nav_label] = pages.count()
        pages.addWidget(page)
        # The sidebar row itself is created in _finish_nav, in display
        # order — _page only registers the page.
        # Search bookkeeping: rows register against this label, and the
        # page itself is findable by its title/subtitle (so pages with
        # no _row()s, like Local Models, still match).
        group_lay.klaus_page = nav_label
        _page_haystack[nav_label] = f"{nav_label} {title} {subtitle}".lower()
        _rows_by_page[nav_label] = []
        return group_lay

    def _finish_nav(*order: str) -> None:
        """Fill the nav list in display order and select the first
        page. Runs once, after every _page() call. Row height comes
        from setSizeHint — view geometry, never a QSS-derived hint —
        and the list's fixed height deliberately OVERSHOOTS (slack is
        an invisible transparent strip; undershoot would clip a row)."""
        from aqt.qt import QSize

        _nav_order[:] = order
        row_h = 32
        for label in order:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(0, row_h))
            _nav_items[label] = item
            nav_list.addItem(item)
        sp = nav_list.spacing()
        rows = nav_list.count()
        nav_list.setFixedHeight(
            rows * row_h + (rows + 1) * 2 * sp
            + 2 * nav_list.frameWidth() + 8
        )
        side_lay.addWidget(nav_list)
        side_lay.addStretch(1)
        _select_page(order[0])

    def _row(
        group: QVBoxLayout,
        name: str,
        desc: str | QLabel,
        control: Any = None,
    ) -> QWidget:
        """A SynapsePro settings row: bold name over a muted description
        on the left, the control pinned right. ``desc`` may be an
        existing QLabel for rows whose description repaints live;
        ``control`` a widget or a layout. Returns the row widget, with
        ``klaus_desc`` (the description label) and ``klaus_sep`` (the
        hairline above it, None on the first row) attached so callers
        can repaint or hide the whole row."""
        sep = None
        if group.count():
            sep = QFrame()
            sep.setObjectName("RowSeparator")
            sep.setFixedHeight(1)
            group.addWidget(sep)
        roww = QWidget()
        row = QHBoxLayout(roww)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(16)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("SettingName")
        text_col.addWidget(name_lbl)
        desc_lbl = desc if isinstance(desc, QLabel) else QLabel(desc)
        desc_lbl.setObjectName("SettingDesc")
        desc_lbl.setWordWrap(True)
        text_col.addWidget(desc_lbl)
        row.addLayout(text_col, 1)
        if isinstance(control, QWidget):
            row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        elif control is not None:
            row.addLayout(control)
        group.addWidget(roww)
        roww.klaus_desc = desc_lbl
        roww.klaus_sep = sep
        # klaus_hidden = structurally hidden (e.g. the image-only
        # background rows) — it always beats a search hit in
        # _apply_search.
        roww.klaus_hidden = False
        roww.klaus_search = f"{name} {desc_lbl.text()}".lower()
        _rows_by_page.setdefault(
            getattr(group, "klaus_page", ""), []
        ).append(roww)
        return roww

    def _apply_search(text: str) -> None:
        """Filter every page's setting rows by name + description, dim
        the pills of pages with no hits, and jump to the first page (in
        sidebar display order) that has one. Clearing the field
        restores everything except structurally hidden rows."""
        q = str(text).strip().lower()
        first_hit = ""
        for label in _nav_order or list(_page_index):
            any_visible = False
            seen = False
            for roww in _rows_by_page.get(label, ()):
                hit = (not q) or q in roww.klaus_search
                show = hit and not roww.klaus_hidden
                roww.setVisible(show)
                # The first visible row in a group carries no hairline
                # above it; every later visible one does.
                if roww.klaus_sep is not None:
                    roww.klaus_sep.setVisible(show and seen)
                if show:
                    seen = True
                    any_visible = True
            page_hit = (
                (not q) or any_visible
                or q in _page_haystack.get(label, "")
            )
            item = _nav_items.get(label)
            if item is not None:
                # Dim + unclickable, but never removed: flags for the
                # click, ForegroundRole for the colour (None resets to
                # the stylesheet default; the faint tone comes from the
                # theme palette, not a literal).
                flags = item.flags()
                if page_hit:
                    item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)
                else:
                    item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
                    try:
                        from aqt.qt import QColor

                        from . import theme as _theme_nav

                        item.setData(
                            Qt.ItemDataRole.ForegroundRole,
                            QColor(
                                _theme_nav.palette(
                                    _theme_nav.night_mode()
                                )["text_faint"]
                            ),
                        )
                    except Exception:
                        pass
            if q and page_hit and not first_hit:
                first_hit = label
        if q and first_hit:
            _select_page(first_hit)

    search_edit.textChanged.connect(_apply_search)

    keys_layout = _page(
        "API keys & models",
        "API keys & models",
        "Klaus talks to OpenAI (embeddings, lecture transcription) and "
        "Anthropic (the assistant, and judging which cards a lecture "
        "really covers) with your own keys. Both are stored in this "
        "add-on's config on your machine and never sent anywhere else.",
    )

    openai_key_edit = QLineEdit()
    openai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    openai_key_edit.setMinimumWidth(220)
    openai_key_edit.setPlaceholderText("sk-…  (platform.openai.com)")
    openai_row = _row(
        keys_layout,
        "OpenAI API key",
        "Embeddings and lecture transcription.",
        openai_key_edit,
    )

    anthropic_key_edit = QLineEdit()
    anthropic_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    anthropic_key_edit.setMinimumWidth(220)
    anthropic_key_edit.setPlaceholderText("sk-ant-…  (console.anthropic.com)")
    anthropic_row = _row(
        keys_layout,
        "Anthropic API key",
        "The assistant and card pertinence.",
        anthropic_key_edit,
    )
    embed_model_edit = QLineEdit()
    embed_model_edit.setMinimumWidth(220)
    embed_model_edit.setPlaceholderText("text-embedding-3-large")
    _row(
        keys_layout,
        "Embedding model",
        "Changing it re-embeds everything (Klaus asks first, with an "
        "estimate).",
        embed_model_edit,
    )

    transcription_model_edit = QLineEdit()
    transcription_model_edit.setMinimumWidth(220)
    transcription_model_edit.setPlaceholderText("gpt-4o-mini-transcribe")
    _row(
        keys_layout,
        "Transcription model",
        "Turns lecture audio into per-slide notes.",
        transcription_model_edit,
    )

    embed_status = QLabel()
    embed_status.setWordWrap(True)
    index_btn = QPushButton("Index Now")
    _row(keys_layout, "Card index", embed_status, index_btn)

    # ----- Default match sensitivity -----------------------------------
    # The global starting point for retention._migrate_default_threshold /
    # pdf_match_threshold. Same 20-80 range and live numeric readout as
    # the Library's per-PDF slider (pdf_drive._on_threshold) — same
    # control, different scope, so it should look and feel the same.
    threshold_slider = QSlider(Qt.Orientation.Horizontal)
    threshold_slider.setMinimum(20)
    threshold_slider.setMaximum(80)
    threshold_slider.setFixedWidth(160)
    threshold_value_lbl = QLabel()
    threshold_value_lbl.setMinimumWidth(36)
    threshold_ctl = QHBoxLayout()
    threshold_ctl.setContentsMargins(0, 0, 0, 0)
    threshold_ctl.addWidget(threshold_slider)
    threshold_ctl.addWidget(threshold_value_lbl)
    _row(
        keys_layout,
        "Default match sensitivity",
        "For every PDF that hasn't been tuned individually. Changing it "
        "offers to reset tuned PDFs too; any single PDF can still be "
        "adjusted in the Library (right-click → Match sensitivity).",
        threshold_ctl,
    )

    # ----- General ------------------------------------------------------
    general_layout = _page(
        "General",
        "General",
        "Feature toggles, the Library folder on disk, and the PDF "
        "renderer.",
    )

    image_crop_cb = Md3Switch()  # MD3 switch (K-material3), not a checkbox
    _row(
        general_layout,
        "Image crop",
        "Right-click or double-click an image in a note field to crop a "
        "copy — the original file is untouched.",
        image_crop_cb,
    )

    # Advanced: renderer flag for the K-095 pdf.js migration. Maps the
    # config's pdf_renderer ("native"/"pdfjs") onto one checkbox — the
    # only UI that touches the key.
    pdfjs_cb = Md3Switch()  # MD3 switch (K-material3), not a checkbox
    _row(
        general_layout,
        "Use the new pdf.js viewer",
        "Smoother, flicker-free scrolling. Beta — not yet in it: "
        "inserting a page image into the editor's focused field, and "
        "exact-phrase find highlighting. Takes effect after Anki "
        "restarts.",
        pdfjs_cb,
    )

    # Library folder (K-070, part A of K-057) — where Library PDFs live
    # on disk. "Change…" re-runs the same guarded migration the
    # per-profile-open setup prompt uses (setup_flow._library_root_check),
    # just from the old root to the new one. The row's description IS the
    # live path label (_refresh_library_label repaints it).
    library_path_lbl = QLabel()
    library_path_lbl.setWordWrap(True)
    library_change_btn = QPushButton("Change…")
    library_change_btn.setObjectName("SecondaryButton")
    _row(general_layout, "Library folder", library_path_lbl, library_change_btn)

    # Maintenance — the connection check that used to live in the
    # Tools > Klaus submenu (K-045).
    test_conn_btn = QPushButton("Check Keys")
    test_conn_btn.setObjectName("SecondaryButton")
    _row(
        general_layout,
        "Connection",
        "Check that both API keys are set.",
        test_conn_btn,
    )

    # ---- Appearance: custom background + the deck-screen panels ----
    appearance_layout = _page(
        "Appearance",
        "Appearance",
        "The KlausBook design layer and everything it draws — the "
        "background of Anki's deck and overview screens and its "
        "panels, a separate background for the study screen, and the "
        "deck-screen widgets — plus the accent color, which styles "
        "Klaus's own windows in either mode. Widgets like the review "
        "heatmap are added or removed on the deck screen itself: "
        "right-click it and choose Edit Widgets….",
    )

    # Anki's own Light/Dark switch, mirrored here (Pouya: "add the
    # light mode / dark mode in the main settings to the klausmate
    # settings") — the ONE row on this page that writes an Anki
    # preference (profile meta via mw.set_theme), not a Klaus config
    # key. Applied on Save, deferred like every non-background pref: a
    # live-previewed theme flip would flash the whole app twice on a
    # Cancel.
    anki_theme_combo = QComboBox()
    anki_theme_combo.addItem("Follow System", 0)
    anki_theme_combo.addItem("Light", 1)
    anki_theme_combo.addItem("Dark", 2)
    _row(
        appearance_layout,
        "Theme",
        "Light or dark for all of Anki — the same switch as Anki's "
        "own preferences. Applies when you press Save.",
        anki_theme_combo,
    )

    # The master switch, next — everything below it on this page is
    # either gated by it (backgrounds) or independent of it (accent),
    # and reading it first makes that hierarchy legible.
    klausbook_cb = Md3Switch()  # MD3 switch (K-material3), not a checkbox
    _row(
        appearance_layout,
        "KlausBook design",
        "Restyle Anki toward the KlausBook look — toolbar, backgrounds, "
        "frosted panels, and widget editing on the deck screen. "
        "Off, Anki keeps its native design and Klaus adds only its "
        "tools.",
        klausbook_cb,
    )

    bg_mode_combo = QComboBox()
    bg_mode_combo.addItem("Anki's Own (Default)", "theme")
    bg_mode_combo.addItem("Color Gradient", "color")
    bg_mode_combo.addItem("Image", "image")
    # ONE control in the row: the mode. Everything a gradient needs is
    # edited ON the screen itself (dots/rings/＋ — Pouya: "It ought to
    # be simple"), the backdrop is always the default white (the edge
    # "shouldn't be an option at all"), and the image button only
    # appears once Image is the selected mode.
    bg_image_btn = QPushButton("Choose Image…")
    bg_image_btn.setObjectName("SecondaryButton")
    bg_ctl = QHBoxLayout()
    bg_ctl.setContentsMargins(0, 0, 0, 0)
    bg_ctl.addWidget(bg_mode_combo)
    bg_ctl.addWidget(bg_image_btn)
    bg_mode_row = _row(
        appearance_layout,
        "Background",
        "Anki's own look, gradient spheres, or an image of yours.",
        bg_ctl,
    )

    # Caption line for the gradient state — word-wrapped: this is the
    # longest line on the page, and an unwrapped QLabel's one-line
    # width becomes the whole page's minimum width (the horizontal
    # scrollbar, live screenshot 2026-08-30).
    bg_grad_lbl = QLabel()
    bg_grad_lbl.setObjectName("SettingDesc")
    bg_grad_lbl.setWordWrap(True)
    appearance_layout.addWidget(bg_grad_lbl)

    # Caption line under the mode row: a rounded thumbnail of the
    # chosen picture beside its filename (thumbnail per Pouya,
    # 2026-08-30). One container so the pair shows/hides whole.
    bg_thumb_lbl = QLabel()
    bg_image_lbl = QLabel()
    bg_image_lbl.setWordWrap(True)
    bg_image_lbl.setObjectName("SettingDesc")
    bg_caption = QWidget()
    _bg_cap_lay = QHBoxLayout(bg_caption)
    _bg_cap_lay.setContentsMargins(0, 0, 0, 0)
    _bg_cap_lay.setSpacing(8)
    _bg_cap_lay.addWidget(bg_thumb_lbl)
    _bg_cap_lay.addWidget(bg_image_lbl, 1)
    appearance_layout.addWidget(bg_caption)

    bg_fit_combo = QComboBox()
    bg_fit_combo.addItem("Fill the Window", "cover")
    bg_fit_combo.addItem("Fit Inside", "contain")
    bg_fit_combo.addItem("Tile", "tile")
    bg_fit_row = _row(
        appearance_layout,
        "Fit",
        "How an image is scaled to the window.",
        bg_fit_combo,
    )

    bg_blur_slider = QSlider(Qt.Orientation.Horizontal)
    bg_blur_slider.setRange(0, 60)
    bg_blur_slider.setFixedWidth(140)
    bg_blur_lbl = QLabel()
    bg_blur_lbl.setObjectName("SettingDesc")
    blur_ctl = QHBoxLayout()
    blur_ctl.setContentsMargins(0, 0, 0, 0)
    blur_ctl.addWidget(bg_blur_slider)
    blur_ctl.addWidget(bg_blur_lbl)
    bg_blur_row = _row(
        appearance_layout,
        "Panel Frost",
        "How strongly the content panels frost the image behind them.",
        blur_ctl,
    )

    # The image WASH — a different layer from the panel frost above:
    # ONE theme-aware veil (white by day, dark at night) plus a blur
    # over the whole picture, between it and everything on it.
    bg_wash_slider = QSlider(Qt.Orientation.Horizontal)
    bg_wash_slider.setRange(0, 100)
    bg_wash_slider.setFixedWidth(140)
    bg_wash_lbl = QLabel()
    bg_wash_lbl.setObjectName("SettingDesc")
    wash_ctl = QHBoxLayout()
    wash_ctl.setContentsMargins(0, 0, 0, 0)
    wash_ctl.addWidget(bg_wash_slider)
    wash_ctl.addWidget(bg_wash_lbl)
    bg_wash_row = _row(
        appearance_layout,
        "Image Wash",
        "Mutes the whole picture behind a soft blurred veil — white "
        "in light mode, dark at night.",
        wash_ctl,
    )

    # A SEPARATE picture for the study screen — Pouya: "this needs to
    # be separate from the background I set for the regular main
    # section." Same mode/colour/image/fit shape as the deck screen's
    # own group above, its own independent state, no Blur row: a card
    # has no panels to frost, so there is nothing a blur control would
    # visibly do.
    study_mode_combo = QComboBox()
    study_mode_combo.addItem("Anki's Own (Default)", "theme")
    study_mode_combo.addItem("Color Gradient", "color")
    study_mode_combo.addItem("Image", "image")
    study_image_btn = QPushButton("Choose Image…")
    study_image_btn.setObjectName("SecondaryButton")
    study_ctl = QHBoxLayout()
    study_ctl.setContentsMargins(0, 0, 0, 0)
    study_ctl.addWidget(study_mode_combo)
    study_ctl.addWidget(study_image_btn)
    study_mode_row = _row(
        appearance_layout,
        "Study screen background",
        "A different picture than the deck screen's, shown behind "
        "your cards while you study.",
        study_ctl,
    )

    study_grad_lbl = QLabel()
    study_grad_lbl.setObjectName("SettingDesc")
    study_grad_lbl.setWordWrap(True)
    appearance_layout.addWidget(study_grad_lbl)

    study_thumb_lbl = QLabel()
    study_image_lbl = QLabel()
    study_image_lbl.setWordWrap(True)
    study_image_lbl.setObjectName("SettingDesc")
    study_caption = QWidget()
    _study_cap_lay = QHBoxLayout(study_caption)
    _study_cap_lay.setContentsMargins(0, 0, 0, 0)
    _study_cap_lay.setSpacing(8)
    _study_cap_lay.addWidget(study_thumb_lbl)
    _study_cap_lay.addWidget(study_image_lbl, 1)
    appearance_layout.addWidget(study_caption)

    study_fit_combo = QComboBox()
    study_fit_combo.addItem("Fill the Window", "cover")
    study_fit_combo.addItem("Fit Inside", "contain")
    study_fit_combo.addItem("Tile", "tile")
    study_fit_row = _row(
        appearance_layout,
        "Fit",
        "How an image is scaled to the window.",
        study_fit_combo,
    )

    # The study screen's own wash — same veil, its own key, so a busy
    # picture can be muted behind the cards without touching the deck
    # screen's. (No Panel-Frost sibling here: the study screen has no
    # panels to frost.)
    study_wash_slider = QSlider(Qt.Orientation.Horizontal)
    study_wash_slider.setRange(0, 100)
    study_wash_slider.setFixedWidth(140)
    study_wash_lbl = QLabel()
    study_wash_lbl.setObjectName("SettingDesc")
    study_wash_ctl = QHBoxLayout()
    study_wash_ctl.setContentsMargins(0, 0, 0, 0)
    study_wash_ctl.addWidget(study_wash_slider)
    study_wash_ctl.addWidget(study_wash_lbl)
    study_wash_row = _row(
        appearance_layout,
        "Image Wash",
        "Mutes the whole picture behind a soft blurred veil — white "
        "in light mode, dark at night.",
        study_wash_ctl,
    )

    # No Review-heatmap switch here (removed 2026-08-30, Pouya: "I can
    # add / remove widgets another way") — the deck screen's Edit
    # Widgets mode (⊖ / ＋) is the ONE writer of heatmap_enabled now.
    # _bg_preview_cfg still carries the key, read from stored config.

    _general_cfg = _pkg().get_config()
    try:
        _cur_theme = int(getattr(mw.pm.theme(), "value", 0))
    except Exception:
        _cur_theme = 0
    anki_theme_combo.setCurrentIndex(
        max(0, anki_theme_combo.findData(_cur_theme))
    )
    image_crop_cb.setChecked(bool(_general_cfg.get("image_crop_enabled", True)))
    from .pdfjs_viewer import renderer_from_config as _renderer_from_config

    pdfjs_cb.setChecked(_renderer_from_config(_general_cfg) == "pdfjs")

    from . import dashboard as _dashboard
    from . import heatmap as _heatmap

    from . import background as _background

    klausbook_cb.setChecked(_background.design_enabled(_general_cfg))

    # Own syncing flag, NOT ui_state["syncing"]: this block builds and
    # runs sync_background_widgets() BEFORE ui_state is assigned further
    # down the function, and a closure's free variable is only looked up
    # at call time — referencing ui_state here crashed the dialog with
    # NameError the moment Preferences opened (live traceback).
    _bg_state = {
        "spec": _background.resolve(_general_cfg),
        "reviewer_spec": _background.resolve(
            _general_cfg, prefix="reviewer_background"
        ),
        "syncing": False,
    }
    # Coalesces live appearance previews: top_bar.refresh() redraws the
    # toolbar and resets the main window, and the blur slider fires
    # continuously while dragged, so previewing per signal would repaint
    # per pixel. 140ms is under the ~200ms that reads as "instant" while
    # still collapsing a drag into a handful of repaints.
    _preview_timer = QTimer(dlg)
    _preview_timer.setSingleShot(True)
    _preview_timer.setInterval(140)

    def _sync_caption(
        thumb: Any,
        text_lbl: Any,
        container: Any,
        spec_x: dict,
        is_image: bool,
        design_on: bool,
    ) -> None:
        """One caption line = rounded thumbnail + filename, shown and
        hidden as a pair. The thumb is re-rendered from the stored copy
        under user_files/backgrounds, so it always previews what the
        wallpaper will actually load, not the original file."""
        name = spec_x["image"]
        text_lbl.setText(
            f'Image: {_elide_middle(name)} &nbsp;&middot;&nbsp; '
            f'<a href="rm">Remove</a>'
            if name
            else ("No image chosen yet." if is_image else "")
        )
        text_lbl.setToolTip(name)
        pix = None
        if name:
            try:
                import os as _os

                from . import USER_FILES as _UF

                pix = _image_thumb(
                    _os.path.join(_UF, _background.IMAGE_DIR, name)
                )
            except Exception:
                pix = None
        if pix is not None:
            thumb.setPixmap(pix)
        else:
            thumb.clear()
        thumb.setVisible(pix is not None)
        container.setEnabled(design_on)
        container.setVisible(bool(text_lbl.text()) or pix is not None)

    def _sync_grad_caption(
        lbl: Any, spec_x: dict, is_colour: bool, design_on: bool
    ) -> None:
        """The gradient caption: one swatch per sphere and the
        on-screen editing vocabulary — the whole model in a sentence,
        since the handles live on the screen and not in this dialog.
        Hidden outside colour mode."""
        if is_colour:
            swatches = " ".join(
                f'<span style="color:{g["color"]}">&#11044;</span>'
                for g in spec_x["gradients"]
            )
            n = len(spec_x["gradients"])
            lbl.setText(
                f'{n} sphere{"s" if n != 1 else ""} {swatches} — edited '
                f"on the screen itself: drag a dot to move it, its ring "
                f"to resize, click a dot to recolor, right-click to "
                f"remove, ＋ to add another."
            )
        else:
            lbl.setText("")
        lbl.setEnabled(design_on)
        lbl.setVisible(bool(lbl.text()))

    def sync_background_widgets() -> None:
        """Repaint the Appearance controls from _bg_state (never from
        config directly — the spec is the pending, unsaved value)."""
        spec = _bg_state["spec"]
        _bg_state["syncing"] = True
        try:
            idx = max(0, bg_mode_combo.findData(spec["mode"]))
            bg_mode_combo.setCurrentIndex(idx)
            bg_fit_combo.setCurrentIndex(
                max(0, bg_fit_combo.findData(spec["fit"]))
            )
            bg_blur_slider.setValue(int(spec["blur"]))
            bg_wash_slider.setValue(int(spec["wash"]))
            r_spec = _bg_state["reviewer_spec"]
            study_mode_combo.setCurrentIndex(
                max(0, study_mode_combo.findData(r_spec["mode"]))
            )
            study_fit_combo.setCurrentIndex(
                max(0, study_fit_combo.findData(r_spec["fit"]))
            )
            study_wash_slider.setValue(int(r_spec["wash"]))
        finally:
            _bg_state["syncing"] = False
        bg_blur_lbl.setText(f"{spec['blur']}px")
        bg_wash_lbl.setText(f"{spec['wash']}%")
        is_image = spec["mode"] == "image"
        is_colour = spec["mode"] == "color"
        # Progressive disclosure (Pouya: "I shouldn't see all the
        # settings like the color and the image unless that item is
        # selected"): rows HIDE outright — via klaus_hidden, the same
        # structural flag the API-key row uses, so a settings search
        # can never resurface them — instead of greying. Design off
        # hides the whole background block; a mode shows only its own
        # rows. The accent grid alone survives every state: it colours
        # Klaus's own windows, which keep their design in both modes.
        design_on = klausbook_cb.isChecked()
        bg_mode_row.klaus_hidden = not design_on
        bg_image_btn.setVisible(is_image)
        _sync_grad_caption(
            bg_grad_lbl, spec, design_on and is_colour, design_on
        )
        bg_fit_row.klaus_hidden = not (design_on and is_image)
        bg_blur_row.klaus_hidden = not (design_on and is_image)
        bg_wash_row.klaus_hidden = not (design_on and is_image)
        _sync_caption(
            bg_thumb_lbl, bg_image_lbl, bg_caption, spec,
            design_on and is_image, design_on,
        )

        r_spec = _bg_state["reviewer_spec"]
        r_is_image = r_spec["mode"] == "image"
        r_is_colour = r_spec["mode"] == "color"
        study_wash_lbl.setText(f"{r_spec['wash']}%")
        study_mode_row.klaus_hidden = not design_on
        study_image_btn.setVisible(r_is_image)
        _sync_grad_caption(
            study_grad_lbl, r_spec, design_on and r_is_colour, design_on
        )
        study_fit_row.klaus_hidden = not (design_on and r_is_image)
        study_wash_row.klaus_hidden = not (design_on and r_is_image)
        _sync_caption(
            study_thumb_lbl,
            study_image_lbl,
            study_caption,
            r_spec,
            design_on and r_is_image,
            design_on,
        )
        # klaus_hidden only takes effect through the search filter's
        # walk — the API-key row's exact pattern. Guarded: the first
        # sync runs while the settings shell is still being built.
        try:
            _apply_search(search_edit.text())
        except Exception:
            pass

    def on_design_toggled(_checked: bool) -> None:
        # Live-preview like every appearance edit, then re-grey the
        # background rows the switch governs.
        appearance_changed()
        sync_background_widgets()

    def on_bg_mode_changed(_i: int) -> None:
        if _bg_state["syncing"]:
            return
        _bg_state["spec"]["mode"] = str(
            bg_mode_combo.currentData() or "theme"
        )
        appearance_changed()
        sync_background_widgets()

    def on_bg_fit_changed(_i: int) -> None:
        if _bg_state["syncing"]:
            return
        _bg_state["spec"]["fit"] = str(bg_fit_combo.currentData() or "cover")
        appearance_changed()

    def on_bg_blur_changed(value: int) -> None:
        bg_blur_lbl.setText(f"{value}px")
        if _bg_state["syncing"]:
            return
        _bg_state["spec"]["blur"] = int(value)
        appearance_changed()

    def on_bg_wash_changed(value: int) -> None:
        bg_wash_lbl.setText(f"{value}%")
        if _bg_state["syncing"]:
            return
        _bg_state["spec"]["wash"] = int(value)
        appearance_changed()

    def on_bg_image_removed(_href: str) -> None:
        _bg_state["spec"]["image"] = ""
        appearance_changed()
        sync_background_widgets()

    def pick_bg_image() -> None:
        from aqt.qt import QFileDialog

        path, _f = QFileDialog.getOpenFileName(
            dlg, "Choose a background image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif)",
        )
        if not path:
            return
        from . import USER_FILES  # type: ignore

        stored = _background.store_image(USER_FILES, path)
        if not stored:
            showWarning("Could not use that image.", parent=dlg)
            return
        _bg_state["spec"]["image"] = stored
        _bg_state["spec"]["mode"] = "image"
        appearance_changed()
        sync_background_widgets()

    def on_study_mode_changed(_i: int) -> None:
        if _bg_state["syncing"]:
            return
        _bg_state["reviewer_spec"]["mode"] = str(
            study_mode_combo.currentData() or "theme"
        )
        appearance_changed()
        sync_background_widgets()

    def on_study_fit_changed(_i: int) -> None:
        if _bg_state["syncing"]:
            return
        _bg_state["reviewer_spec"]["fit"] = str(
            study_fit_combo.currentData() or "cover"
        )
        appearance_changed()

    def on_study_wash_changed(value: int) -> None:
        study_wash_lbl.setText(f"{value}%")
        if _bg_state["syncing"]:
            return
        _bg_state["reviewer_spec"]["wash"] = int(value)
        appearance_changed()

    def on_study_image_removed(_href: str) -> None:
        _bg_state["reviewer_spec"]["image"] = ""
        appearance_changed()
        sync_background_widgets()

    def pick_study_image() -> None:
        from aqt.qt import QFileDialog

        path, _f = QFileDialog.getOpenFileName(
            dlg, "Choose a study screen image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif)",
        )
        if not path:
            return
        from . import USER_FILES  # type: ignore

        stored = _background.store_image(USER_FILES, path)
        if not stored:
            showWarning("Could not use that image.", parent=dlg)
            return
        _bg_state["reviewer_spec"]["image"] = stored
        _bg_state["reviewer_spec"]["mode"] = "image"
        appearance_changed()
        sync_background_widgets()

    sync_background_widgets()

    # ----- Accent colour (SynapsePro's colour themes, K-107) ------------
    # Bare colour squares — no names, the swatch IS the label (the name
    # lives in the tooltip, since a colour square alone tells a
    # screen-reader user nothing). Preset colours come straight from
    # theme.COLOR_THEMES; the last square is the user's own colour and
    # opens a picker. Deferred-save like every other preference:
    # choosing only updates _accent_state + the dirty flag; save_general
    # writes color_theme/color_theme_custom and save_all applies live.
    from . import theme as _theme_presets

    _accent_state = {
        "name": "ocean",
        "custom": _theme_presets.DEFAULT_CUSTOM_COLOR,
    }
    _accent_buttons: dict[str, QPushButton] = {}

    def _accent_swatch_style(fill: str, checked: bool) -> str:
        """A colour square. Checked = a white inner ring (SynapsePro's
        selection mark) over a neutral outer border, so the selection
        reads on a pale swatch as well as a saturated one."""
        c = _theme_presets.palette(_theme_presets.night_mode())
        outer = c["text_muted"] if checked else c["grey_mid"]
        ring = "rgba(255,255,255,0.9)" if checked else "transparent"
        return (
            "QPushButton {"
            f" background-color: {fill};"
            f" border-radius: 6px;"
            f" border: 2px solid {ring};"
            f" outline: 1px solid {outer};"
            " }"
        )

    def _accent_fill(name: str) -> str:
        if name == _theme_presets.CUSTOM_THEME:
            return str(_accent_state["custom"])
        return _theme_presets.COLOR_THEMES[name][False]["blue"]

    def sync_accent_swatches() -> None:
        for name, btn in _accent_buttons.items():
            checked = name == _accent_state["name"]
            btn.setChecked(checked)
            btn.setStyleSheet(_accent_swatch_style(_accent_fill(name), checked))

    def _pick_accent(name: str) -> None:
        _accent_state["name"] = name
        appearance_changed()
        sync_accent_swatches()

    def _pick_custom_accent() -> None:
        """Open the colour picker for the custom swatch. Cancelling
        still selects custom (with whatever colour it already held) —
        the click was a choice of swatch, the dialog only refines it."""
        from aqt.qt import QColor, QColorDialog

        chosen = QColorDialog.getColor(
            QColor(str(_accent_state["custom"])), dlg, "Accent Color"
        )
        if chosen.isValid():
            _accent_state["custom"] = chosen.name()
        _pick_accent(_theme_presets.CUSTOM_THEME)

    # 14 swatches (13 presets + custom) — wrapped 7 per row so the
    # control side of the row stays narrow enough for a compact dialog.
    from aqt.qt import QGridLayout as _QGridLayout

    accent_ctl = _QGridLayout()
    accent_ctl.setContentsMargins(0, 0, 0, 0)
    accent_ctl.setHorizontalSpacing(6)
    accent_ctl.setVerticalSpacing(6)
    _SWATCHES_PER_ROW = 7
    for _idx, _name in enumerate(
        list(_theme_presets.COLOR_THEMES) + [_theme_presets.CUSTOM_THEME]
    ):
        _is_custom = _name == _theme_presets.CUSTOM_THEME
        sw = QPushButton()
        sw.setCheckable(True)
        sw.setFixedSize(22, 22)
        sw.setCursor(Qt.CursorShape.PointingHandCursor)
        sw.setToolTip(
            "Custom color — click to pick" if _is_custom
            else _name.capitalize()
        )
        # A bare colour square is silent in VoiceOver; the accessible
        # name carries the identity the tooltip shows sighted users.
        sw.setAccessibleName(
            "Custom accent color" if _is_custom
            else f"{_name.capitalize()} accent color"
        )
        sw.clicked.connect(
            (lambda _=False: _pick_custom_accent()) if _is_custom
            else (lambda _=False, n=_name: _pick_accent(n))
        )
        _accent_buttons[_name] = sw
        accent_ctl.addWidget(
            sw, _idx // _SWATCHES_PER_ROW, _idx % _SWATCHES_PER_ROW
        )

    _cfg_custom = str(_general_cfg.get("color_theme_custom") or "")
    if _theme_presets.is_hex_colour(_cfg_custom):
        _accent_state["custom"] = _cfg_custom
    _cfg_accent = str(_general_cfg.get("color_theme") or "ocean")
    _accent_state["name"] = (
        _cfg_accent
        if _cfg_accent in _theme_presets.COLOR_THEMES
        or _cfg_accent == _theme_presets.CUSTOM_THEME
        else "ocean"
    )
    sync_accent_swatches()
    _row(
        appearance_layout,
        "Accent color",
        "Recolors buttons, pills and highlights across every Klaus "
        "surface. The last square is your own color — click it to pick.",
        accent_ctl,
    )

    def _refresh_library_label() -> None:
        from . import pdf_handler

        root = pdf_handler.get_library_root(_pkg().get_config())
        library_path_lbl.setText(root or "Not set — PDFs stay inside the add-on")

    _refresh_library_label()
    def load_api_key_settings() -> None:
        cfg = _pkg().get_config()
        anthropic_key_edit.setText(str(cfg.get("api_key_anthropic") or ""))
        transcription_model_edit.setText(
            str(cfg.get("transcription_model") or "")
        )

    def save_api_key_settings() -> None:
        cfg = _pkg().get_config()
        cfg["api_key_anthropic"] = anthropic_key_edit.text().strip()
        cfg["transcription_model"] = transcription_model_edit.text().strip()
        _pkg().write_config(cfg)

    _finish_nav("General", "Appearance", "API keys & models")

    outer.addWidget(models_page, 1)

    # ----- Shared footer --------------------------------------------------
    bar_line = QFrame()
    bar_line.setObjectName("ButtonBarLine")
    bar_line.setFixedHeight(1)
    outer.addWidget(bar_line)

    foot = QVBoxLayout()
    foot.setContentsMargins(12, 8, 12, 10)
    foot.setSpacing(6)
    outer.addLayout(foot)

    progress = QProgressBar()
    progress.setRange(0, 100)
    progress.setValue(0)
    progress.setTextVisible(True)
    progress.setVisible(False)
    foot.addWidget(progress)

    progress_lbl = QLabel("")
    progress_lbl.setStyleSheet(_MUTED)
    progress_lbl.setVisible(False)
    foot.addWidget(progress_lbl)

    close_row = QHBoxLayout()
    unsaved_lbl = QLabel("")
    unsaved_lbl.setStyleSheet(_MUTED)
    close_row.addWidget(unsaved_lbl)
    close_row.addStretch(1)
    cancel_btn = QPushButton("Stop Indexing")
    cancel_btn.setObjectName("SecondaryButton")
    cancel_btn.setVisible(False)
    close_row.addWidget(cancel_btn)
    close_btn = QPushButton("Cancel")
    close_btn.setObjectName("SecondaryButton")
    close_row.addWidget(close_btn)
    # Save is the primary action (theme default = blue) and the ONLY
    # writer of preference keys — see mark_dirty()/save_all().
    save_btn = QPushButton("Save")
    save_btn.setEnabled(False)
    # The dialog's default button: Return saves once there is something
    # to save (Qt never fires a disabled default). HIG: a dialog names
    # its default action; crop_dialog and setup_flow already comply.
    save_btn.setDefault(True)
    close_row.addWidget(save_btn)
    foot.addLayout(close_row)

    # "kind" is only ever "index" now — the pull / install / runtime-setup
    # operations went with the local runtime — but it stays a named kind
    # so confirm_close keeps reading one thing.
    op_state: dict[str, Any] = {"active": False, "kind": "", "cancel": None}
    # "syncing"/"dirty" back the deferred-save model: preference widgets
    # never write on a keystroke or a toggle — Save does. "syncing" is
    # what stops a programmatic repopulation looking like a user edit.
    ui_state: dict[str, Any] = {"syncing": False, "dirty": False}

    def set_busy(busy: bool) -> None:
        op_state["active"] = busy
        for w in (
            openai_key_edit, anthropic_key_edit, embed_model_edit,
            transcription_model_edit,
            index_btn, test_conn_btn,
            threshold_slider, library_change_btn,
        ):
            w.setEnabled(not busy)
        progress.setVisible(busy)
        progress_lbl.setVisible(busy)

    def refresh() -> None:
        """Reload every deferred-save widget from stored config. The one
        entry point that used to probe a local server and rebuild a model
        inventory; with two cloud keys there is nothing to probe."""
        sync_embed_widgets()
        sync_threshold_widget()

    # ----- API keys & models handlers --------------------------------------

    def sync_embed_widgets() -> None:
        """Seed the five fields from stored config.

        Never while dirty: a refresh landing mid-edit must not overwrite
        unsaved values with the stored ones. The key fields are seeded
        here and read only by save_embed / save_api_key_settings — a key's value
        never reaches a print, a tooltip or a status label.
        """
        if ui_state["dirty"]:
            return
        ui_state["syncing"] = True
        try:
            cfg = _pkg().get_config()
            openai_key_edit.setText(str(cfg.get("api_key_openai") or ""))
            embed_model_edit.setText(str(cfg.get("embedding_model") or ""))
            load_api_key_settings()
        finally:
            ui_state["syncing"] = False
        update_embed_status()

    def _fmt_ago(ts: float) -> str:
        secs = max(0, int(time.time() - ts))
        if secs < 90:
            return "just now"
        if secs < 5400:
            return f"{secs // 60} min ago"
        if secs < 172800:
            return f"{secs // 3600} h ago"
        return f"{secs // 86400} days ago"

    def update_embed_status() -> None:
        from . import curation, embeddings

        cfg = _pkg().get_config()
        sig = embeddings.index_signature(cfg)
        st = curation.index_stats()
        if not str(cfg.get("api_key_openai") or "").strip():
            txt = "Add your OpenAI API key above to enable semantic search."
        elif not st["exists"]:
            txt = "No card index yet — click “Index Now” to enable semantic search."
        else:
            txt = f"{st['count']:,} cards indexed · updated {_fmt_ago(st['updated_at'])}"
            if not embeddings.signature_matches(
                st["provider"], st["model"], st.get("dims", 0), sig
            ):
                txt += " · settings changed: next indexing rebuilds from scratch"
        embed_status.setText(txt)

    def save_embed() -> None:
        if ui_state["syncing"]:
            return
        from . import embeddings

        cfg = _pkg().get_config()
        # Captured BEFORE the mutations below, off STORED config: this is
        # what every vector on disk was made with, and comparing it with
        # what config holds after the write is the only honest way to ask
        # "did the model move under the index?" (K-152).
        prev_sig = embeddings.index_signature(cfg)
        had_key = bool(str(cfg.get("api_key_openai") or "").strip())
        cfg["api_key_openai"] = openai_key_edit.text().strip()
        cfg["embedding_model"] = embed_model_edit.text().strip()
        _pkg().write_config(cfg)
        update_embed_status()
        # K-152: a changed model or width invalidates EVERY stored
        # vector, and PDF indexes rebuild only lazily — one at a time,
        # whenever you next happen to touch that PDF — so without this
        # the whole Library goes quietly stale until each is opened by
        # hand. A FIRST key is the other half: the signature never moves
        # (nothing was ever embedded), and that is exactly the moment
        # the offer is most useful. offer_model_sweep does the
        # comparison (via embeddings.signature_matches, never a tuple
        # ==), counts the work, prices it, and asks before spending.
        # (The Plus-key half of this same offer now lives in
        # on_plus_sign_in — the key isn't editable through this form
        # anymore.)
        try:
            from . import index_queue

            index_queue.offer_model_sweep(dlg, prev_sig, first_key=not had_key and bool(cfg["api_key_openai"]))
        except Exception as exc:
            print(f"[klausmate] model-change sweep offer failed: {exc}")

    def _update_threshold_label(value: int) -> None:
        threshold_value_lbl.setText(f"{value / 100:.2f}")

    def sync_threshold_widget() -> None:
        from . import retention

        if ui_state["dirty"]:
            return  # never clobber an unsaved slider position
        ui_state["syncing"] = True
        try:
            cfg = retention._cfg()  # applies the default-bump migration
            try:
                value = float(
                    cfg.get("pdf_match_threshold") or retention.DEFAULT_THRESHOLD
                )
            except (TypeError, ValueError):
                value = retention.DEFAULT_THRESHOLD
            threshold_slider.setValue(int(round(value * 100)))
        finally:
            ui_state["syncing"] = False
        _update_threshold_label(threshold_slider.value())

    def save_threshold() -> None:
        """Wired to sliderReleased, not valueChanged — valueChanged only
        drives the live label (_update_threshold_label), so dragging never
        writes config on every intermediate pixel, and a programmatic
        setValue() (sync_threshold_widget, on every refresh()) never emits
        sliderReleased at all, real Qt never fires it outside a genuine
        mouse/touch release.

        Still guarded by ui_state['syncing'] like every other save_* here,
        belt-and-braces, AND a no-op unless the value actually differs from
        what's stored: opening this dialog and closing it untouched must
        leave config byte-identical. Getting either guard wrong stamps
        _threshold_user_set on profiles that never touched the control,
        which permanently opts them out of every future
        retention._migrate_default_threshold bump with no visible symptom
        until that bump ships and silently reaches nobody.
        """
        if ui_state["syncing"]:
            return
        from . import retention

        value = round(threshold_slider.value() / 100.0, 3)
        cfg = _pkg().get_config()
        try:
            current = round(
                float(cfg.get("pdf_match_threshold") or retention.DEFAULT_THRESHOLD),
                3,
            )
        except (TypeError, ValueError):
            current = None
        if value == current:
            return
        cfg["pdf_match_threshold"] = value
        cfg["_threshold_user_set"] = True
        _pkg().write_config(cfg)

        def _refresh_library() -> None:
            # An open Library window shows retention/cards computed at
            # the old numbers — push the change there immediately
            # rather than waiting for a reopen (K-052 rework: looked
            # like it did nothing).
            try:
                from . import pdf_drive

                pdf_drive.refresh_open_library()
            except Exception as e:
                print(f"[klausmate] library refresh after sensitivity save failed: {e}")

        # A per-PDF override always beats the default, so a user whose
        # PDFs are all individually tuned sees NOTHING move when this
        # slider changes — which reads as the setting being broken
        # (K-052 rework #2; that was exactly Pouya's library). Offer to
        # clear the overrides so the new default actually reaches every
        # row; declining keeps them, and either way untuned PDFs follow
        # the default as before.
        try:
            from . import retention

            names = retention.threshold_override_names()
            n = len(names)
        except Exception as e:
            print(f"[klausmate] applying sensitivity to tuned PDFs failed: {e}")
            _refresh_library()
            return
        if not n:
            _refresh_library()
            return

        # K-114: hand-built QMessageBox + open() + finished, same shape
        # as clear_assistant_sessions above — never a blocking static
        # confirm (its internal exec() is the K-114 segfault class).
        # Confirm-dialog parity: default Yes (the replaced call carried
        # no "default no" flag), Esc/close land on No.
        msg = QMessageBox(dlg)
        msg.setWindowTitle("Apply to individually tuned PDFs?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            f"Apply this sensitivity to "
            f"{'the ' + str(n) + ' PDFs' if n > 1 else 'the one PDF'} "
            "with their own setting too?\n\n"
            "Their individual sensitivities will be cleared so they "
            "follow this default. You can still tune any single PDF "
            "afterwards in the Library."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        no_btn = msg.button(QMessageBox.StandardButton.No)
        if no_btn is not None:
            no_btn.setObjectName("SecondaryButton")
        try:
            from . import theme as _theme

            msg.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] sensitivity-override dialog theme failed: {exc}")

        def _on_answered(_r: int) -> None:
            clicked = msg.clickedButton()
            confirmed = (
                clicked is not None
                and msg.standardButton(clicked) == QMessageBox.StandardButton.Yes
            )
            msg.deleteLater()
            if confirmed:
                try:
                    retention.clear_threshold_overrides()
                    try:
                        from . import tag_sync

                        tag_sync.sync_after_clear_overrides(dlg, names)
                    except Exception as e:
                        print(f"[klausmate] retagging cleared-override PDFs failed: {e}")
                except Exception as e:
                    print(f"[klausmate] applying sensitivity to tuned PDFs failed: {e}")
            _refresh_library()

        msg.finished.connect(_on_answered)
        msg.open()

    def cancel_index() -> None:
        ev = op_state.get("cancel")
        if ev is not None:
            ev.set()
            progress_lbl.setText("Cancelling…")

    def finish_index() -> None:
        progress.setRange(0, 100)
        set_busy(False)
        cancel_btn.setVisible(False)
        op_state["kind"] = ""
        op_state["cancel"] = None

    def _dlg_alive() -> bool:
        try:
            dlg.isVisible()
            return True
        except RuntimeError:  # C++ side deleted (dialog closed)
            return False

    def _run_index() -> None:
        from . import curation, embeddings

        cancel_event = threading.Event()
        op_state["kind"] = "index"
        op_state["cancel"] = cancel_event
        set_busy(True)
        cancel_btn.setVisible(True)
        progress.setRange(0, 0)
        progress_lbl.setText("Scanning your notes…")

        def on_progress(label: str, done: int, total: int) -> None:
            if not _dlg_alive():
                return
            if total:
                progress.setRange(0, 100)
                progress.setValue(int(done * 100 / total))
                progress_lbl.setText(f"{label} {done:,} / {total:,}")
            else:
                progress.setRange(0, 0)
                progress_lbl.setText(label)

        def on_done(_index: Any, completed: bool) -> None:
            if _dlg_alive():
                finish_index()
                update_embed_status()
            tooltip(
                "Klaus: card index up to date"
                if completed
                else "Klaus: indexing cancelled — it resumes where it stopped"
            )

        def on_error(exc: Exception) -> None:
            if _dlg_alive():
                finish_index()
                update_embed_status()
            if isinstance(exc, embeddings.EmbeddingError):
                showWarning("Klaus indexing failed.\n\n" + exc.user_message())
            else:
                showWarning(
                    f"Klaus indexing failed.\n\n{type(exc).__name__}: {exc}"
                )

        curation.ensure_index(
            dlg,
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
            cancel=cancel_event,
        )

    def start_index() -> None:
        if op_state["active"]:
            return
        from . import curation, embeddings

        cfg = _pkg().get_config()
        sig = embeddings.index_signature(cfg)
        if not str(cfg.get("api_key_openai") or "").strip():
            showWarning("Enter your OpenAI API key above before indexing.")
            return
        st = curation.index_stats()
        if st["exists"] and not embeddings.signature_matches(
            st["provider"], st["model"], st.get("dims", 0), sig
        ):
            # Destructive: the stored vectors don't match the model about
            # to run, so a rebuild-from-scratch is one confirm away rather
            # than one click away. A matching signature (fresh build or
            # incremental update) skips this prompt entirely.
            note_count = mw.col.note_count() if mw.col else 0
            # K-114: hand-built QMessageBox + open() + finished, same
            # shape as clear_assistant_sessions above — never a
            # blocking question() static (its internal exec() is the
            # K-114 segfault class). Yes/No with No default, matching
            # that static's own fallback.
            msg = QMessageBox(dlg)
            msg.setWindowTitle("Re-index from scratch?")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setText(
                f"Re-index all {note_count:,} cards from scratch? The "
                f"existing index was built with {st['model']} and the "
                f"current setting is {sig[1]}."
            )
            msg.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg.setDefaultButton(QMessageBox.StandardButton.No)
            yes_btn = msg.button(QMessageBox.StandardButton.Yes)
            if yes_btn is not None:
                yes_btn.setObjectName("DangerButton")
            no_btn = msg.button(QMessageBox.StandardButton.No)
            if no_btn is not None:
                no_btn.setObjectName("SecondaryButton")
            try:
                from . import theme as _theme

                msg.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
            except Exception as exc:
                print(f"[klausmate] re-index dialog theme failed: {exc}")

            def _on_answered(_r: int) -> None:
                clicked = msg.clickedButton()
                confirmed = (
                    clicked is not None
                    and msg.standardButton(clicked) == QMessageBox.StandardButton.Yes
                )
                msg.deleteLater()
                if confirmed:
                    _run_index()

            msg.finished.connect(_on_answered)
            msg.open()
            return
        _run_index()

    def confirm_close() -> None:
        # Checked BEFORE the running-operation branches: several of those
        # accept() straight away, and unsaved edits must not slip out
        # through one of them unmentioned.
        def _after_dirty_check() -> None:
            if op_state["active"]:
                # Indexing is the one long operation left in this
                # window. K-114: hand-built QMessageBox + open() +
                # finished, same shape as clear_assistant_sessions
                # above — never a blocking question() static. Chained
                # off the discard confirm below (via a plain function
                # call, not a nested dialog) so the two can never stack.
                msg2 = QMessageBox(dlg)
                msg2.setWindowTitle("Stop indexing?")
                msg2.setIcon(QMessageBox.Icon.Question)
                msg2.setText(
                    "Card indexing is still running.\n\n"
                    "Stop it and close? Progress is saved — indexing "
                    "resumes where it stopped next time."
                )
                msg2.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                msg2.setDefaultButton(QMessageBox.StandardButton.No)
                no_btn2 = msg2.button(QMessageBox.StandardButton.No)
                if no_btn2 is not None:
                    no_btn2.setObjectName("SecondaryButton")
                try:
                    from . import theme as _theme

                    msg2.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
                except Exception as exc:
                    print(f"[klausmate] stop-indexing dialog theme failed: {exc}")

                def _on_stop_answered(_r: int) -> None:
                    clicked = msg2.clickedButton()
                    confirmed = (
                        clicked is not None
                        and msg2.standardButton(clicked)
                        == QMessageBox.StandardButton.Yes
                    )
                    msg2.deleteLater()
                    if not confirmed:
                        return
                    ev = op_state.get("cancel")
                    if ev is not None:
                        ev.set()
                    dlg.accept()

                msg2.finished.connect(_on_stop_answered)
                msg2.open()
            else:
                dlg.accept()

        if ui_state["dirty"]:
            # K-114: hand-built QMessageBox + open() + finished, same
            # shape as clear_assistant_sessions above — never a
            # blocking question() static (its internal exec() is the
            # K-114 segfault class).
            msg1 = QMessageBox(dlg)
            msg1.setWindowTitle("Discard changes?")
            msg1.setIcon(QMessageBox.Icon.Question)
            msg1.setText(
                "You have unsaved preference changes.\n\n"
                "Close without saving them?"
            )
            msg1.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg1.setDefaultButton(QMessageBox.StandardButton.No)
            yes_btn1 = msg1.button(QMessageBox.StandardButton.Yes)
            if yes_btn1 is not None:
                yes_btn1.setObjectName("DangerButton")
            no_btn1 = msg1.button(QMessageBox.StandardButton.No)
            if no_btn1 is not None:
                no_btn1.setObjectName("SecondaryButton")
            try:
                from . import theme as _theme

                msg1.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
            except Exception as exc:
                print(f"[klausmate] discard-changes dialog theme failed: {exc}")

            def _on_discard_answered(_r: int) -> None:
                clicked = msg1.clickedButton()
                confirmed = (
                    clicked is not None
                    and msg1.standardButton(clicked)
                    == QMessageBox.StandardButton.Yes
                )
                msg1.deleteLater()
                if not confirmed:
                    return
                clear_dirty()
                _after_dirty_check()

            msg1.finished.connect(_on_discard_answered)
            msg1.open()
        else:
            _after_dirty_check()

    def save_general() -> None:
        cfg = _pkg().get_config()
        cfg["image_crop_enabled"] = bool(image_crop_cb.isChecked())
        cfg["pdf_renderer"] = "pdfjs" if pdfjs_cb.isChecked() else "native"
        spec = _bg_state["spec"]
        cfg["background_mode"] = spec["mode"]
        cfg["background_color"] = spec["color"]
        cfg["background_image"] = spec["image"]
        cfg["background_fit"] = spec["fit"]
        cfg["background_blur"] = int(spec["blur"])
        cfg["background_wash"] = int(spec["wash"])
        cfg["background_grad_x"] = int(spec["grad_x"])
        cfg["background_grad_y"] = int(spec["grad_y"])
        cfg["background_grad_size"] = int(spec["grad_size"])
        cfg["background_gradients"] = [dict(g) for g in spec["gradients"]]
        r_spec = _bg_state["reviewer_spec"]
        cfg["reviewer_background_mode"] = r_spec["mode"]
        cfg["reviewer_background_color"] = r_spec["color"]
        cfg["reviewer_background_image"] = r_spec["image"]
        cfg["reviewer_background_fit"] = r_spec["fit"]
        cfg["reviewer_background_wash"] = int(r_spec["wash"])
        cfg["reviewer_background_grad_x"] = int(r_spec["grad_x"])
        cfg["reviewer_background_grad_y"] = int(r_spec["grad_y"])
        cfg["reviewer_background_grad_size"] = int(r_spec["grad_size"])
        cfg["reviewer_background_gradients"] = [
            dict(g) for g in r_spec["gradients"]
        ]
        cfg["color_theme"] = _accent_state["name"]
        cfg["color_theme_custom"] = _accent_state["custom"]
        # No heatmap_enabled write: since 2026-08-30 the deck screen's
        # Edit Widgets mode is the only UI that owns that key, and a
        # write here would clobber a mid-session ⊖/＋ edit with the
        # value this dialog happened to open with.
        cfg["klausbook_design"] = bool(klausbook_cb.isChecked())
        _pkg().write_config(cfg)
        # Anki's own theme — the one non-Klaus preference this dialog
        # writes. Only when actually changed: mw.set_theme re-runs
        # setupStyle, which repaints every webview in the app.
        try:
            from aqt.theme import Theme as _Theme

            _want = int(anki_theme_combo.currentData() or 0)
            if int(getattr(mw.pm.theme(), "value", 0)) != _want:
                mw.set_theme(_Theme(_want))
        except Exception as _exc:
            print(f"[klausmate] theme apply failed: {_exc}")

    def mark_dirty() -> None:
        """A preference widget changed — nothing is written until Save.

        Every preference used to write config on its own change signal.
        That made "I changed it and it didn't take" indistinguishable
        from "I never committed it", and it silently lost any setting
        whose signal was left unconnected (exactly what happened to the
        pdf_renderer checkbox). Save is now the single writer, so an
        unwired signal costs a missing dirty mark, never a lost setting.
        """
        if ui_state["syncing"]:
            return
        ui_state["dirty"] = True
        save_btn.setEnabled(True)
        unsaved_lbl.setText("Unsaved changes")

    def clear_dirty() -> None:
        ui_state["dirty"] = False
        save_btn.setEnabled(False)
        unsaved_lbl.setText("")

    def _bg_preview_cfg() -> dict:
        """The PENDING appearance keys in config shape, for background's
        preview override — the same keys save_general() writes.

        This dict REPLACES config for every reader of
        background.effective_cfg, so a key left out of it does not fall
        back to the stored value, it falls back to that reader's own
        default. heatmap_enabled is here for exactly that reason:
        without it, opening Preferences with the heatmap removed and
        nudging the blur would preview it back into existence. This
        dialog no longer edits that key (Edit Widgets on the deck
        screen does), so it is carried from STORED config, read live
        per tick like dashboard_order below — a ⊖/＋ edit made while
        Preferences is open must survive the next preview tick.
        """
        spec = _bg_state["spec"]
        return {
            "background_mode": spec["mode"],
            "background_color": spec["color"],
            "background_image": spec["image"],
            "background_fit": spec["fit"],
            "background_blur": int(spec["blur"]),
            "background_wash": int(spec["wash"]),
            "background_grad_x": int(spec["grad_x"]),
            "background_grad_y": int(spec["grad_y"]),
            "background_grad_size": int(spec["grad_size"]),
            "background_gradients": [dict(g) for g in spec["gradients"]],
            # The study screen's OWN spec — carried for the same reason
            # as every key here: the preview dict REPLACES config, so
            # omitting these would snap the study background back to
            # its stored value (or default) on the very next preview
            # tick, even though the main background's edit is what
            # triggered it.
            "reviewer_background_mode": _bg_state["reviewer_spec"]["mode"],
            "reviewer_background_color": _bg_state["reviewer_spec"]["color"],
            "reviewer_background_image": _bg_state["reviewer_spec"]["image"],
            "reviewer_background_fit": _bg_state["reviewer_spec"]["fit"],
            "reviewer_background_wash": int(
                _bg_state["reviewer_spec"]["wash"]
            ),
            "reviewer_background_grad_x": _bg_state["reviewer_spec"]["grad_x"],
            "reviewer_background_grad_y": _bg_state["reviewer_spec"]["grad_y"],
            "reviewer_background_grad_size": _bg_state["reviewer_spec"][
                "grad_size"
            ],
            "reviewer_background_gradients": [
                dict(g) for g in _bg_state["reviewer_spec"]["gradients"]
            ],
            "heatmap_enabled": bool(_heatmap.enabled(_pkg().get_config())),
            # The heatmap's own corner menu writes these two, and it can
            # be used while this dialog is open — so they are carried
            # from STORED config and read live per tick, exactly like
            # heatmap_enabled above and dashboard_order below.
            "heatmap_history_days": _heatmap.history_window(
                _pkg().get_config()
            ),
            "heatmap_forecast": _heatmap.forecast_window(
                _pkg().get_config()
            ) > 0,
            # Same expression save_general writes. The design gates all
            # read through effective_cfg and their default is OFF, so a
            # preview dict missing this key would strip the whole look
            # on the first blur nudge.
            "klausbook_design": bool(klausbook_cb.isChecked()),
            # The dashboard reads its order through effective_cfg too;
            # Preferences has no order UI, so carry the stored value —
            # read live per tick, in case the dashboard writes mid-preview.
            "dashboard_order": _dashboard.order_from_cfg(_pkg().get_config()),
        }

    def apply_appearance_live() -> None:
        """Render the pending accent + background EVERYWHERE, saving
        nothing.

        Appearance is the one class of setting judged by eye, so it
        previews live while the dialog is open; Save remains the only
        writer of config (see mark_dirty). Cancelling runs
        revert_appearance_preview() to put the stored look back.
        """
        try:
            # Background first: top_bar.refresh() below repaints from it.
            _background.set_preview(_bg_preview_cfg())
            # Accent colour before name: set_active_theme("custom") is
            # only meaningful once the colour behind it is loaded.
            _theme_presets.set_custom_colour(str(_accent_state["custom"]))
            _theme_presets.set_active_theme(str(_accent_state["name"]))
            dlg.setStyleSheet(
                _theme_presets.dialog_qss(_theme_presets.night_mode())
            )
            # The swatches carry their own inline QSS, so the dialog
            # sheet swap above wipes them — repaint from _accent_state.
            sync_accent_swatches()
            # The sidebar star is a baked pixmap filled in blue_accent;
            # re-render it or it keeps the old accent until reopen.
            _new_logo = _logo_pixmap(24, logo_lbl.devicePixelRatioF())
            if _new_logo is not None:
                logo_lbl.setPixmap(_new_logo)
        except Exception as _exc:
            print(f"[klausmate] accent apply failed: {_exc}")
        try:
            from . import top_bar as _top_bar

            _top_bar.refresh()
        except Exception as _exc:
            print(f"[klausmate] background refresh failed: {_exc}")
        try:
            # Already-open Anki windows (Browse, Add, Stats — cached by
            # aqt.dialogs) restyle through the tracked walk, so the
            # toggle and every accent edit preview there live too.
            from . import window_chrome as _window_chrome

            _window_chrome.refresh()
        except Exception as _exc:
            print(f"[klausmate] window chrome refresh failed: {_exc}")

    def revert_appearance_preview() -> None:
        """Put the STORED appearance back on screen.

        Wired to dlg.finished, so it runs on EVERY close — Save, Cancel,
        Esc, the title-bar ✕ — because "re-apply from config" is the
        right answer for all of them: after Save config already matches
        (visually a no-op), and after a discard it undoes the preview.
        Without it a previewed accent would linger for the rest of the
        session despite being discarded, snapping back only on restart.
        Re-runs the addon's own profile-open applier so "revert" and
        "load from config" can never drift apart.
        """
        if not _background.preview_active():
            return  # nothing previewed — stored config is already drawn
        _background.set_preview(None)
        try:
            _pkg()._apply_color_theme()
        except Exception as _exc:
            print(f"[klausmate] appearance revert failed: {_exc}")
        try:
            from . import top_bar as _top_bar

            _top_bar.refresh()
        except Exception as _exc:
            print(f"[klausmate] appearance revert refresh failed: {_exc}")
        try:
            from . import window_chrome as _window_chrome

            _window_chrome.refresh()
        except Exception as _exc:
            print(f"[klausmate] window chrome revert failed: {_exc}")

    def appearance_changed() -> None:
        """An appearance widget moved: mark unsaved AND preview it live.

        Debounced — top_bar.refresh() redraws the toolbar and resets the
        main window, and the blur slider emits continuously while it is
        dragged, so an undebounced preview would repaint per pixel.
        """
        mark_dirty()
        _preview_timer.start()

    def save_all() -> None:
        """The one writer of preference keys (the Save button).

        clear_dirty() runs FIRST because save_embed()/save_threshold()
        re-sync widgets afterwards and those syncs are skipped while the
        dirty guard is up.
        """
        prev_renderer = _renderer_from_config(_pkg().get_config())
        clear_dirty()
        save_embed()
        save_threshold()
        save_general()
        save_api_key_settings()
        # Paint through the same one path as every live edit, THEN drop
        # the override: stored config now holds identical values, so
        # leaving it armed would let a stale preview shadow a later
        # config change for the rest of the session.
        apply_appearance_live()
        _background.set_preview(None)
        if _renderer_from_config(_pkg().get_config()) != prev_renderer:
            showInfo(
                "Preferences saved.\n\nThe PDF viewer change takes effect "
                "the next time you start Anki.",
                parent=dlg,
            )
        else:
            tooltip("Klaus: preferences saved", parent=dlg)

    def change_library_folder() -> None:
        """Point the Library at a different on-disk folder, moving
        whatever's already there (K-070, part A of K-057) — same guarded,
        resumable move as setup_flow's first-time prompt, just old root
        -> new root instead of unset -> chosen.
        """
        from aqt.qt import QFileDialog

        from . import USER_FILES, drive_store, pdf_handler

        cfg = _pkg().get_config()
        old_root = pdf_handler.get_library_root(cfg)
        new_root = QFileDialog.getExistingDirectory(
            dlg, "Choose a folder for your Klaus Library", old_root or ""
        )
        if not new_root or new_root == old_root:
            return

        def do(_col: Any) -> Any:
            folders = drive_store.load(USER_FILES).get("pdfs", {})
            return pdf_handler.migrate_to_root(
                USER_FILES, new_root, folders, old_root=old_root
            )

        def on_done(result: Any) -> None:
            set_busy(False)
            cfg2 = _pkg().get_config()
            cfg2["library_root"] = new_root
            _pkg().write_config(cfg2)
            _refresh_library_label()
            failed = (result or {}).get("failed") or {}
            if failed:
                showWarning(
                    "Library folder updated, but "
                    f"{len(failed)} file(s) couldn't be moved and stay "
                    "in the old location:\n"
                    + "\n".join(f"{k}: {v}" for k, v in failed.items()),
                    parent=dlg,
                )
            else:
                tooltip("Klaus: Library folder updated")

        def on_fail(exc: Exception) -> None:
            set_busy(False)
            showWarning(f"Could not move the Library: {exc}", parent=dlg)

        set_busy(True)
        op = QueryOp(parent=dlg, op=do, success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def test_connection() -> None:
        """Moved from the old Tools > Klaus > Test connection (K-045).

        A key-PRESENCE check, not a network probe: a live call would
        cost money to answer a question the user did not ask, and the
        only failure it could report that this cannot is a wrong key —
        which the first real request reports anyway, with its own
        message.
        """
        cfg = _pkg().get_config()
        pairs = (("OpenAI", "api_key_openai"), ("Anthropic", "api_key_anthropic"))
        missing = [label for label, key in pairs if not str(cfg.get(key) or "").strip()]
        if missing:
            showWarning(
                "No API key is set for: "
                + ", ".join(missing)
                + ".\n\nAdd one in KlausMate Preferences → API keys & models.",
                parent=dlg,
            )
        else:
            showInfo("Both API keys are set.", parent=dlg)

    cancel_btn.clicked.connect(cancel_index)
    dlg.confirm_close_cb = confirm_close  # Esc and title-bar ✕ too
    test_conn_btn.clicked.connect(test_connection)
    close_btn.clicked.connect(confirm_close)
    # Preference widgets only MARK DIRTY; save_all() (Save button) is the
    # single writer. textEdited rather than editingFinished so the Save
    # button lights up as you type, not only on focus-out.
    openai_key_edit.textEdited.connect(lambda _t: mark_dirty())
    embed_model_edit.textEdited.connect(lambda _t: mark_dirty())
    anthropic_key_edit.textEdited.connect(lambda _t: mark_dirty())
    transcription_model_edit.textEdited.connect(lambda _t: mark_dirty())
    threshold_slider.valueChanged.connect(_update_threshold_label)
    threshold_slider.sliderReleased.connect(mark_dirty)
    index_btn.clicked.connect(start_index)
    image_crop_cb.toggled.connect(lambda _checked: mark_dirty())
    pdfjs_cb.toggled.connect(lambda _checked: mark_dirty())
    anki_theme_combo.currentIndexChanged.connect(lambda _i: mark_dirty())
    klausbook_cb.toggled.connect(on_design_toggled)
    bg_mode_combo.currentIndexChanged.connect(on_bg_mode_changed)
    bg_fit_combo.currentIndexChanged.connect(on_bg_fit_changed)
    bg_blur_slider.valueChanged.connect(on_bg_blur_changed)
    bg_wash_slider.valueChanged.connect(on_bg_wash_changed)
    bg_image_lbl.linkActivated.connect(on_bg_image_removed)
    bg_image_btn.clicked.connect(pick_bg_image)
    study_mode_combo.currentIndexChanged.connect(on_study_mode_changed)
    study_fit_combo.currentIndexChanged.connect(on_study_fit_changed)
    study_wash_slider.valueChanged.connect(on_study_wash_changed)
    study_image_lbl.linkActivated.connect(on_study_image_removed)
    study_image_btn.clicked.connect(pick_study_image)
    save_btn.clicked.connect(save_all)
    library_change_btn.clicked.connect(change_library_folder)
    _preview_timer.timeout.connect(apply_appearance_live)
    # ── On-screen gradient editing (Pouya picked drag-on-screen over
    # sliders) ── rides the OPEN dialog: while Preferences is up, a
    # gradient background grows a draggable centre dot + size ring on
    # its own screen. JS repaints the page live during the drag; the
    # release lands here through background.grad_edit_event (clamped)
    # and this sink.
    def _quiet_preview() -> None:
        try:
            _background.set_preview(_bg_preview_cfg())
        except Exception as _exc:
            print(f"[klausmate] gradient preview failed: {_exc}")

    def _replant_editor() -> None:
        """Rebuild the screen so the editor regrows with fresh sphere
        indices — for STRUCTURAL edits only (add/remove/recolor);
        geometry drags must never come through here."""
        try:
            from . import top_bar as _top_bar

            _top_bar.refresh()
        except Exception as _exc:
            print(f"[klausmate] gradient replant failed: {_exc}")

    def _on_grad_geom(s: dict, i: int, data: dict) -> None:
        """A sphere moved/resized. QUIET on purpose — never
        top_bar.refresh(): the page already shows the dragged stack
        (the editor painted it inline), and a refresh would rebuild
        the page under the pointer."""
        g = s["gradients"][i]
        g["x"], g["y"], g["size"] = data["x"], data["y"], data["size"]
        if i == 0:
            # Legacy single-gradient mirror (what save_general also
            # writes), so a downgrade or hand-read config stays sane.
            s["grad_x"], s["grad_y"], s["grad_size"] = (
                data["x"], data["y"], data["size"],
            )
        mark_dirty()
        _quiet_preview()

    def _pick_sphere_colour(spec_key: str, i: int) -> None:
        """Recolor sphere i — the on-screen dot IS the colour chip, a
        click on it lands here (deferred one tick: modal work must
        never run inside a webchannel dispatch)."""
        from aqt.qt import QColor, QColorDialog

        s = _bg_state[spec_key]
        if not 0 <= i < len(s["gradients"]):
            return
        chosen = QColorDialog.getColor(
            QColor(s["gradients"][i]["color"]), dlg, "Sphere Color"
        )
        if not chosen.isValid():
            return
        s["gradients"][i]["color"] = chosen.name()
        if i == 0:
            s["color"] = chosen.name()
        mark_dirty()
        _quiet_preview()
        sync_background_widgets()
        _replant_editor()

    def _on_grad_dragged(target: str, op: str, data: dict) -> None:
        """The on-screen editor's bridge sink (values already clamped
        in background.grad_edit_event). List bounds and the sphere cap
        are enforced HERE — JS indices are never trusted either."""
        spec_key = "reviewer_spec" if target == "reviewer" else "spec"
        s = _bg_state[spec_key]
        gradients = s["gradients"]
        i = int(data.get("i", 0))
        if op == "geom":
            if 0 <= i < len(gradients):
                _on_grad_geom(s, i, data)
        elif op == "add":
            if len(gradients) < _background.MAX_SPHERES:
                try:
                    new_colour = _theme_presets.palette(
                        _theme_presets.night_mode()
                    )["blue_bright"]
                except Exception:
                    new_colour = "#0a84ff"
                gradients.append(
                    {"color": new_colour, "x": 50, "y": 45, "size": 60}
                )
                mark_dirty()
                _quiet_preview()
                sync_background_widgets()
                _replant_editor()
        elif op == "remove":
            # The last sphere stays — colour mode IS a gradient; an
            # empty stack would be flat, which was removed outright.
            if len(gradients) > 1 and 0 <= i < len(gradients):
                gradients.pop(i)
                mark_dirty()
                _quiet_preview()
                sync_background_widgets()
                _replant_editor()
        elif op == "pick":
            QTimer.singleShot(
                0, lambda: _pick_sphere_colour(spec_key, i)
            )

    _background.set_grad_edit(True, _on_grad_dragged)

    def _disarm_grad_edit(_result: int) -> None:
        """Connected BEFORE the preview revert below, so between them
        exactly one refresh clears the handles on every close path:
        with a preview armed the revert's own refresh rebuilds without
        the flag; with nothing previewed the revert early-returns and
        this refresh does the clearing."""
        _background.set_grad_edit(False, None)
        if not _background.preview_active():
            try:
                from . import top_bar as _top_bar

                _top_bar.refresh()
            except Exception:
                pass

    dlg.finished.connect(_disarm_grad_edit)
    # finished fires on EVERY close path (Save, Cancel, Esc, title-bar ✕),
    # so it is the one place an unsaved preview can be guaranteed not to
    # outlive the dialog. No-op unless a preview is actually armed.
    dlg.finished.connect(lambda _result: revert_appearance_preview())

    def _on_profile_will_close() -> None:
        # A NON-MODAL window can outlive its profile — close it before
        # the collection goes away. reject() routes through finished →
        # revert_appearance_preview, so an armed preview cannot leak
        # into the next profile either.
        try:
            dlg.reject()
        except Exception:
            pass

    try:
        from aqt import gui_hooks as _gui_hooks

        _gui_hooks.profile_will_close.append(_on_profile_will_close)
    except Exception as _exc:
        print(f"[klausmate] preferences profile guard failed: {_exc}")

    def _forget_dialog(_result: int) -> None:
        global _OPEN_DLG
        _OPEN_DLG = None
        try:
            from aqt import gui_hooks as _gui_hooks2

            _gui_hooks2.profile_will_close.remove(_on_profile_will_close)
        except Exception:
            pass

    dlg.finished.connect(_forget_dialog)

    refresh()
    # show(), NEVER exec() (live crash, 2026-08-26): on macOS 26.5 +
    # Qt 6.11, showing this dialog application-modal via exec()
    # segfaulted in its first backing-store flush
    # (QPaintDevice::devicePixelRatio on null inside QBackingStore::flush)
    # SEVEN times across THREE dispatch shapes — webchannel, a Tools-menu
    # QAction, and a clean QTimer slot — so the app-modal nested loop
    # (Qt runs it through AppKit's NSApp modal-session machinery, which
    # races Tahoe's window-appear animation) is the trigger, not how the
    # dialog was opened. The window-modal open() that replaced exec()
    # takes the normal window path; show() is that same path minus the
    # modality — dropped on purpose (2026-08-30, Pouya): Preferences is
    # a live control panel now, used BESIDE the main window while
    # appearance edits preview on it (and the on-screen gradient
    # handles need the deck screen clickable at all). _OPEN_DLG above
    # keeps it a singleton; profile_will_close closes it in time.
    # Nothing here consumed exec()'s return value; every close path is
    # already callback-driven (confirm_close / save_all).
    _OPEN_DLG = dlg
    dlg.show()
    # Plant the gradient drag handles right away when a gradient is
    # already configured (arming an edge colour later plants them via
    # that edit's own live-preview refresh). After show(), so the one
    # deck-screen rebuild happens behind the appearing window.
    try:
        if (
            _bg_state["spec"]["mode"] == "color"
            or _bg_state["reviewer_spec"]["mode"] == "color"
        ):
            from . import top_bar as _top_bar

            _top_bar.refresh()
    except Exception as _exc:
        print(f"[klausmate] gradient handle plant failed: {_exc}")

