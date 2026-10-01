"""KlausMate Preferences for local models, general settings and appearance."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
from . import settings


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
    """The Klaus k for the Preferences sidebar, the same SVG as the toolbar
    (top_bar.logo_svg, evenodd and all), filled in the current accent on
    a transparent ground, never inside a tile.

    ``dpr`` comes from the label that will show it, so the mark is crisp
    on whatever screen the dialog opened on; 2.0 is only the fallback
    for a caller with no widget to ask. The k keeps its aspect ratio,
    centred vertically in the square."""
    try:
        from aqt.qt import QColor, QPainter, QPixmap, QRectF
        from PyQt6.QtSvg import QSvgRenderer
        from . import theme as _theme
        from . import top_bar as _top_bar

        px = QPixmap(int(size * dpr), int(size * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(QColor(0, 0, 0, 0))
        c = _theme.palette(_theme.night_mode())
        colour = QColor(c["blue_accent"]).name()
        renderer = QSvgRenderer(_top_bar.logo_svg(colour).encode("utf-8"))
        painter = QPainter(px)
        try:
            inset = max(1.3, size * 0.09) / 2.0
            width = size - inset * 2.0
            height = width * renderer.viewBoxF().height() / renderer.viewBoxF().width()
            renderer.render(painter, QRectF(inset, (size - height) / 2, width, height))
        finally:
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
    embedding invisibly after the dialog vanishes, and
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


def _close_for_profile(dlg: Any, preview_timer: Any, op_state: dict) -> None:
    """Close Preferences for a profile switch: no prompts, no late preview."""
    for step in (
        preview_timer.stop,  # a pending tick would re-arm the preview
        lambda: op_state.get("active") and op_state.get("cancel") and op_state["cancel"].set(),
        lambda: setattr(dlg, "confirm_close_cb", None),
        dlg.reject,
    ):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - never block a profile close
            print(f"[klausmate] preferences close for profile failed: {exc}")


class _Binding:
    """One value widget bound to a PrefsState key (spec: prefs-state).

    ``signal`` → ``state.set(key, read())`` then ``after()``; ``paint()``
    writes ``state.get(key)`` back into the widget under the class-wide
    ``syncing`` scope, during which incoming signals are ignored — so
    painting from state never counts as an edit (invariant 5).
    """

    syncing = False

    def __init__(self, state, key, read, paint, signal, after) -> None:
        self.state, self.key = state, key
        self._read, self._paint, self._after = read, paint, after
        signal.connect(self._on_signal)

    def _on_signal(self, *_args) -> None:
        if _Binding.syncing:
            return
        self.state.set(self.key, self._read())
        self._after()

    def paint(self) -> None:
        _Binding.syncing = True
        try:
            self._paint(self.state.get(self.key))
        finally:
            _Binding.syncing = False


PREFS_GEOM_KEY = "klausmate_prefs"


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

    from . import setup_flow
    profile_lifetime = setup_flow.runtime_lifetime()
    _generation, profile_cancel = profile_lifetime
    dlg = _KlausManageDialog(mw)
    dlg.setWindowTitle("KlausMate Preferences")
    dlg.setMinimumWidth(480)
    dlg.resize(960, 680)
    # The size the user last left it at, and no "?" on Windows.
    try:
        from aqt.utils import disable_help_button, restoreGeom, saveGeom

        disable_help_button(dlg)
        restoreGeom(dlg, PREFS_GEOM_KEY)
        dlg.finished.connect(lambda *_a: saveGeom(dlg, PREFS_GEOM_KEY))
    except Exception as exc:
        print(f"[klausmate] preferences geometry failed: {exc}")
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
    logo_px = [24]  # the pixmap's square; fit_logo sets it once laid out

    def fit_logo() -> None:
        """Make the k as tall as the wordmark and version together: their
        laid-out height (so any font or platform fits), over the share of
        its square the k fills (measured, so a new logo still fits)."""
        try:
            last = ver_lbl if _ver else app_name_lbl
            block = last.geometry().bottom() - app_name_lbl.geometry().top() + 1
            probe = _logo_pixmap(100, 1.0)
            if probe is None or block <= 0:
                return
            img = probe.toImage()
            rows = [y for y in range(img.height())
                    if any(img.pixelColor(x, y).alpha() > 0 for x in range(img.width()))]
            frac = (rows[-1] - rows[0] + 1) / img.height() if rows else 1.0
            logo_px[0] = max(24, round(block / frac))
            new = _logo_pixmap(logo_px[0], logo_lbl.devicePixelRatioF())
            if new is not None:
                # The label is the text block's height; the square pixmap
                # is centred in it, so only its empty margins are cropped.
                logo_lbl.setFixedSize(logo_px[0], block)
                logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                logo_lbl.setPixmap(new)
        except Exception as exc:
            print(f"[klausmate] preferences logo fit failed: {exc}")

    QTimer.singleShot(0, fit_logo)  # after the first layout pass
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
        text_col.setAlignment(Qt.AlignmentFlag.AlignTop)
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
        advanced_expanded = advanced_toggle.isChecked() or bool(q and any(
            q in row.klaus_search for row in _rows_by_page.get("Local models", ())
            if advanced_panel.isAncestorOf(row)))
        advanced_panel.setVisible(advanced_expanded)
        advanced_toggle.setText("▾ Advanced Settings" if advanced_expanded else "▸ Advanced Settings")
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
        "Local models", "Local models",
        "Choose the model for matching cards.",
    )
    advanced_panel = QWidget()
    advanced_panel.setObjectName("AdvancedModelPanel")
    advanced_layout = QVBoxLayout(advanced_panel)
    advanced_layout.setContentsMargins(0, 0, 0, 0)
    advanced_layout.klaus_page = "Local models"
    advanced_panel.hide()
    endpoint_edit = QLineEdit()
    endpoint_edit.setObjectName("endpoint")
    endpoint_edit.setMinimumWidth(220)
    endpoint_edit.setPlaceholderText("http://127.0.0.1:11434")
    _row(advanced_layout, "Ollama endpoint", "Local HTTP address for Ollama.", endpoint_edit)
    embed_model_edit = QLineEdit()
    embed_model_edit.setObjectName("embedding_model")
    embed_model_edit.setMinimumWidth(220)
    embed_model_edit.setPlaceholderText("nomic-embed-text")
    _row(
        advanced_layout,
        "Embedding model",
        "Changing it offers to re-index your cards and PDFs locally.",
        embed_model_edit,
    )

    from . import ollama_runtime

    runtime_auto_cb = Md3Switch()
    runtime_auto_cb.setObjectName("runtime_auto_setup")
    _row(advanced_layout, "Automatic management",
         "Start an installed Ollama runtime on profile open. Never downloads automatically.",
         runtime_auto_cb)
    runtime_status = QLabel("Not checked. Click Refresh to check Ollama and installed models.")
    runtime_status.setWordWrap(True)
    runtime_status.setTextFormat(Qt.TextFormat.PlainText)
    runtime_controls = QVBoxLayout()
    install_btn = QPushButton("Install/Start")
    stop_runtime_btn = QPushButton("Stop Managed Server")
    update_runtime_btn = QPushButton("Update Runtime")
    stop_runtime_btn.setEnabled(False)
    update_runtime_btn.setEnabled(False)
    for button in (install_btn, stop_runtime_btn, update_runtime_btn):
        button.setObjectName("SecondaryButton")
        if button is install_btn:
            runtime_controls.addWidget(button)
        else:
            _row(advanced_layout, button.text(), "Manage the Ollama runtime installed by Klaus.", button)
    runtime_hint = QLabel(
        "Runs your card-matching model on this computer. "
        f"First-time installation downloads {ollama_runtime.runtime_download_size_hint()}."
    )
    runtime_hint.setWordWrap(True)
    _row(keys_layout, "Ollama", runtime_hint, runtime_controls)
    _row(keys_layout, "Ollama status", runtime_status, None)
    runtime_status.setObjectName("OllamaStatus")
    installed_models = QListWidget()
    installed_models.setObjectName("InstalledModels")
    installed_models.setMinimumWidth(220)
    installed_models.setFixedHeight(108)
    inventory_controls = QVBoxLayout()
    inventory_controls.addWidget(installed_models)
    inventory_buttons = QHBoxLayout()
    refresh_models_btn = QPushButton("Refresh")
    delete_model_btn = QPushButton("Delete")
    for button in (refresh_models_btn, delete_model_btn):
        button.setObjectName("SecondaryButton")
        inventory_buttons.addWidget(button)
    inventory_controls.addLayout(inventory_buttons)
    inventory_row = _row(keys_layout, "Installed models",
         "Select a Card matching model, then Save. Model types appear below each name.",
         inventory_controls)
    inventory_row.layout().itemAt(0).layout().setAlignment(Qt.AlignmentFlag.AlignTop)
    pull_model_edit = QLineEdit()
    pull_model_edit.setObjectName("pull_model")
    pull_model_edit.setPlaceholderText("nomic-embed-text")
    pull_model_edit.setMinimumWidth(140)
    pull_model_edit.setText("nomic-embed-text")
    pull_btn = QPushButton("Download")
    pull_controls = QHBoxLayout()
    pull_controls.addWidget(pull_model_edit)
    pull_controls.addWidget(pull_btn)
    download_controls = QVBoxLayout()
    download_controls.addLayout(pull_controls)
    _row(keys_layout, "Download model", "For card matching, use nomic-embed-text. Download progress appears below.", download_controls)
    runtime_progress = QProgressBar()
    runtime_progress.setObjectName("OllamaProgress")
    runtime_progress.setRange(0, 100)
    runtime_progress.setValue(0)
    download_controls.addWidget(runtime_progress)

    model_usage = QLabel()
    model_usage.setWordWrap(True)
    inventory_controls.addWidget(model_usage)

    def update_model_usage() -> None:
        model_usage.setText("Card matching: " + (embed_model_edit.text().strip() or "Not selected"))

    embed_model_edit.textChanged.connect(update_model_usage)

    embed_status = QLabel()
    embed_status.setWordWrap(True)
    index_btn = QPushButton("Index Now")
    _row(keys_layout, "Index cards", embed_status, index_btn)

    from pathlib import Path
    from aqt.qt import QApplication, QPlainTextEdit
    from .scripts import mcp_stdio_bridge
    from .scripts.mcp_stdio_bridge import client_config, external_python

    external_interpreter = None
    external_script = str(Path(__file__).resolve().parent / "scripts" / "mcp_stdio_bridge.py")
    external_discovery = str(Path(settings.user_files()) / "mcp_connection.json")
    external_controls = QVBoxLayout()
    external_json = QPlainTextEdit()
    external_json.setObjectName("external_client_config")
    external_json.setReadOnly(True)
    external_json.setMinimumWidth(260)
    external_json.setMaximumHeight(180)
    external_copy = QPushButton("Copy Configuration")
    external_copy.setObjectName("copy_external_client_config")
    external_copy.setEnabled(False)
    external_test = QPushButton("Test Connection")
    external_test.setObjectName("test_external_client_connection")
    external_test.setEnabled(False)
    external_status = QLabel("Checking for external Python 3.9 or newer…")
    external_status.setProperty("mcp_status", True)
    external_status.setWordWrap(True)
    external_status.setTextFormat(Qt.TextFormat.PlainText)
    external_copy.clicked.connect(lambda: QApplication.clipboard().setText(external_json.toPlainText()))
    _row(advanced_layout, "MCP configuration", "Full configuration for an external assistant.", external_json)
    external_controls.addWidget(external_copy)
    external_controls.addWidget(external_test)
    _row(keys_layout, "MCP", external_status, external_controls)

    def connection_ready(result: dict) -> None:
        if _OPEN_DLG is not dlg or profile_cancel.is_set():
            return
        external_test.setEnabled(True)
        external_status.setText(result["message"])

    def check_external_connection(*_args) -> None:
        if not external_interpreter or _OPEN_DLG is not dlg or profile_cancel.is_set():
            return
        external_test.setEnabled(False)
        external_status.setText("Testing connection…")
        op = QueryOp(parent=dlg, op=lambda _col: mcp_stdio_bridge.test_connection(
            external_interpreter, external_script, external_discovery), success=connection_ready)
        op.failure(lambda _exc: connection_ready({"ok": False,
            "message": "Connection test failed. Restart Anki and try again."}))
        op.without_collection().run_in_background()

    external_test.clicked.connect(check_external_connection)

    def external_ready(interpreter: str | None) -> None:
        nonlocal external_interpreter
        if _OPEN_DLG is not dlg or profile_cancel.is_set():
            return
        external_interpreter = interpreter
        if interpreter:
            external_json.setPlainText(client_config(
                interpreter, external_script, external_discovery,
            ))
            external_copy.setEnabled(True)
            external_test.setEnabled(True)
            external_status.setText(
                "Connect an external assistant while Anki is open. Copy this configuration "
                "into your client. The client may send requested page text and images to its model provider."
            )
        else:
            external_status.setText("Install Python 3.9 or newer and reopen Preferences to copy the client configuration.")

    # ----- Default match sensitivity -----------------------------------
    # The global starting point for retention._migrate_default_threshold /
    # pdf_match_threshold. Same 20-80 range and live numeric readout as
    # the Library's per-PDF slider (pdf_drive._on_threshold) — same
    # control, different scope, so it should look and feel the same.
    threshold_slider = QSlider(Qt.Orientation.Horizontal)
    threshold_slider.setObjectName("pdf_match_threshold")
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

    advanced_toggle = QPushButton("▸ Advanced Settings")
    advanced_toggle.setObjectName("AdvancedModelSettings")
    advanced_toggle.setCheckable(True)
    advanced_toggle.toggled.connect(advanced_panel.setVisible)
    advanced_toggle.toggled.connect(lambda expanded: advanced_toggle.setText(
        "▾ Advanced Settings" if expanded else "▸ Advanced Settings"))
    advanced_toggle.setAccessibleName("Advanced Settings")
    keys_layout.addWidget(advanced_toggle)
    keys_layout.addWidget(advanced_panel)

    # ----- General ------------------------------------------------------
    general_layout = _page(
        "General",
        "General",
        "Feature toggles and the Library folder on disk.",
    )

    image_crop_cb = Md3Switch()  # MD3 switch (K-material3), not a checkbox
    _row(
        general_layout,
        "Image crop",
        "Right-click or double-click an image in a note field to crop a "
        "copy. The original file is untouched.",
        image_crop_cb,
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
    test_conn_btn = QPushButton("Check Connection")
    test_conn_btn.setObjectName("SecondaryButton")
    _row(
        advanced_layout,
        "Connection",
        "Check the local Ollama connection.",
        test_conn_btn,
    )

    # ---- Appearance: custom background + the deck-screen panels ----
    appearance_layout = _page(
        "Appearance",
        "Appearance",
        "The KlausBook design layer: backgrounds for Anki's deck, "
        "overview and study screens, and the deck-screen widgets. The "
        "accent color styles Klaus's own windows in either mode. To add "
        "or remove a widget such as the review heatmap, right-click the "
        "deck screen and choose Edit Widgets…",
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
        "Light or dark for all of Anki, the same switch as Anki's "
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
        "Restyle Anki toward the KlausBook look: toolbar, backgrounds, "
        "frosted panels, and widget editing on the deck screen. "
        "Off, Anki keeps its native design and Klaus adds only its "
        "tools.",
        klausbook_cb,
    )

    bg_mode_combo = QComboBox()

    bg_mode_combo.setObjectName("background_mode")
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
        "Mutes the whole picture behind a soft blurred veil: white "
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
        "Mutes the whole picture behind a soft blurred veil: white "
        "in light mode, dark at night.",
        study_wash_ctl,
    )

    # No Review-heatmap switch here (removed 2026-08-30, Pouya: "I can
    # add / remove widgets another way") — the deck screen's Edit
    # Widgets mode (⊖ / ＋) is the ONE writer of heatmap_enabled now.
    # _bg_preview_cfg still carries the key, read from stored config.

    _general_cfg = settings.read()
    try:
        _cur_theme = int(getattr(mw.pm.theme(), "value", 0))
    except Exception:
        _cur_theme = 0
    anki_theme_combo.setCurrentIndex(
        max(0, anki_theme_combo.findData(_cur_theme))
    )
    # The value state machine (prefs_state.py, spec prefs-state): EVERY
    # value this dialog edits lives there — General, Local models and
    # Appearance (the two background specs as values, the accent pair,
    # the design gate, and anki_theme as a pseudo-key seeded from
    # mw.pm.theme()). Widgets are _Binding adapters or paint from it;
    # Save commits it; dirty is its fact.
    from . import prefs_state as _prefs_state

    state = _prefs_state.PrefsState.from_config(_general_cfg)
    state.reseed("anki_theme", _cur_theme)
    dlg.prefs_state = state  # the offscreen tests drive the state directly
    dlg.paint_all = lambda: paint_all()  # …and repaint from it (invariant 5 pin)

    from . import dashboard as _dashboard
    from . import heatmap as _heatmap

    from . import background as _background

    klausbook_cb.setChecked(_background.design_enabled(_general_cfg))

    # Coalesces live appearance previews: top_bar.refresh() redraws the
    # toolbar and resets the main window, and the blur slider fires
    # continuously while dragged, so previewing per signal would repaint
    # per pixel. 140ms is under the ~200ms that reads as "instant" while
    # still collapsing a drag into a handful of repaints.
    _preview_timer = QTimer(dlg)
    _preview_timer.setSingleShot(True)
    _preview_timer.setInterval(140)
    _preview_timer.setObjectName("preview_timer")

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

                from . import settings as _settings

                pix = _image_thumb(
                    _os.path.join(_settings.user_files(), _background.IMAGE_DIR, name)
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
                f'{n} sphere{"s" if n != 1 else ""} {swatches}, edited '
                f"on the screen itself: drag a dot to move it, its ring "
                f"to resize, click a dot to recolor, right-click to "
                f"remove, ＋ to add another."
            )
        else:
            lbl.setText("")
        lbl.setEnabled(design_on)
        lbl.setVisible(bool(lbl.text()))

    def sync_background_widgets() -> None:
        """Repaint the Appearance controls from the state (never from
        config directly — the state holds the pending, unsaved value)."""
        spec = state.get("background")
        _Binding.syncing = True
        try:
            klausbook_cb.setChecked(bool(state.get("klausbook_design")))
            idx = max(0, bg_mode_combo.findData(spec["mode"]))
            bg_mode_combo.setCurrentIndex(idx)
            bg_fit_combo.setCurrentIndex(
                max(0, bg_fit_combo.findData(spec["fit"]))
            )
            bg_blur_slider.setValue(int(spec["blur"]))
            bg_wash_slider.setValue(int(spec["wash"]))
            r_spec = state.get("reviewer_background")
            study_mode_combo.setCurrentIndex(
                max(0, study_mode_combo.findData(r_spec["mode"]))
            )
            study_fit_combo.setCurrentIndex(
                max(0, study_fit_combo.findData(r_spec["fit"]))
            )
            study_wash_slider.setValue(int(r_spec["wash"]))
        finally:
            _Binding.syncing = False
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
        design_on = bool(state.get("klausbook_design"))
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

        r_spec = state.get("reviewer_background")
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

    def _edit_spec(key: str, **fields) -> None:
        """One or more fields of a background spec changed: copy, edit,
        set — the state owns the value, the handler never holds it."""
        spec = state.get(key)
        spec.update(fields)
        state.set(key, spec)

    def on_design_toggled(_checked: bool) -> None:
        # Live-preview like every appearance edit, then re-grey the
        # background rows the switch governs.
        if _Binding.syncing:
            return
        state.set("klausbook_design", klausbook_cb.isChecked())
        appearance_changed()
        sync_background_widgets()

    def on_bg_mode_changed(_i: int) -> None:
        if _Binding.syncing:
            return
        _edit_spec("background", mode=str(bg_mode_combo.currentData() or "theme"))
        appearance_changed()
        sync_background_widgets()

    def on_bg_fit_changed(_i: int) -> None:
        if _Binding.syncing:
            return
        _edit_spec("background", fit=str(bg_fit_combo.currentData() or "cover"))
        appearance_changed()

    def on_bg_blur_changed(value: int) -> None:
        bg_blur_lbl.setText(f"{value}px")
        if _Binding.syncing:
            return
        _edit_spec("background", blur=int(value))
        appearance_changed()

    def on_bg_wash_changed(value: int) -> None:
        bg_wash_lbl.setText(f"{value}%")
        if _Binding.syncing:
            return
        _edit_spec("background", wash=int(value))
        appearance_changed()

    def on_bg_image_removed(_href: str) -> None:
        _edit_spec("background", image="")
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
        from . import settings

        stored = _background.store_image(settings.user_files(), path)
        if not stored:
            showWarning("Could not use that image.", parent=dlg)
            return
        _edit_spec("background", image=stored, mode="image")
        appearance_changed()
        sync_background_widgets()

    def on_study_mode_changed(_i: int) -> None:
        if _Binding.syncing:
            return
        _edit_spec("reviewer_background", mode=str(study_mode_combo.currentData() or "theme"))
        appearance_changed()
        sync_background_widgets()

    def on_study_fit_changed(_i: int) -> None:
        if _Binding.syncing:
            return
        _edit_spec("reviewer_background", fit=str(study_fit_combo.currentData() or "cover"))
        appearance_changed()

    def on_study_wash_changed(value: int) -> None:
        study_wash_lbl.setText(f"{value}%")
        if _Binding.syncing:
            return
        _edit_spec("reviewer_background", wash=int(value))
        appearance_changed()

    def on_study_image_removed(_href: str) -> None:
        _edit_spec("reviewer_background", image="")
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
        from . import settings

        stored = _background.store_image(settings.user_files(), path)
        if not stored:
            showWarning("Could not use that image.", parent=dlg)
            return
        _edit_spec("reviewer_background", image=stored, mode="image")
        appearance_changed()
        sync_background_widgets()

    sync_background_widgets()

    # ----- Accent colour (SynapsePro's colour themes, K-107) ------------
    # Bare colour squares — no names, the swatch IS the label (the name
    # lives in the tooltip, since a colour square alone tells a
    # screen-reader user nothing). Preset colours come straight from
    # theme.COLOR_THEMES; the last square is the user's own colour and
    # opens a picker. Deferred-save like every other preference:
    # choosing is state.set("color_theme"); Save commits it and the
    # appearance effect applies it live.
    from . import theme as _theme_presets

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
            return str(state.get("color_theme_custom"))
        return _theme_presets.COLOR_THEMES[name][False]["blue"]

    def sync_accent_swatches() -> None:
        for name, btn in _accent_buttons.items():
            checked = name == state.get("color_theme")
            btn.setChecked(checked)
            btn.setStyleSheet(_accent_swatch_style(_accent_fill(name), checked))

    def _pick_accent(name: str) -> None:
        state.set("color_theme", name)
        appearance_changed()
        sync_accent_swatches()

    def _pick_custom_accent() -> None:
        """Open the colour picker for the custom swatch. Cancelling
        still selects custom (with whatever colour it already held) —
        the click was a choice of swatch, the dialog only refines it."""
        from aqt.qt import QColor, QColorDialog

        chosen = QColorDialog.getColor(
            QColor(str(state.get("color_theme_custom"))), dlg, "Accent Color"
        )
        if chosen.isValid():
            state.set("color_theme_custom", chosen.name())
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
            "Custom color: click to pick" if _is_custom
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

    sync_accent_swatches()
    _row(
        appearance_layout,
        "Accent color",
        "Recolors buttons, pills and highlights across every Klaus "
        "surface. Click the last square to pick your own color.",
        accent_ctl,
    )

    def _refresh_library_label() -> None:
        from . import pdf_handler

        root = pdf_handler.get_library_root(settings.read())
        library_path_lbl.setText(root or "Not set. PDFs stay inside the add-on.")

    _refresh_library_label()
    _finish_nav("General", "Appearance", "Local models")

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
    # Save is the primary action (theme default = blue) and the ONLY
    # writer of preference keys — see save_all() (state.commit()).
    save_btn = QPushButton("Save")
    save_btn.setEnabled(False)
    # The dialog's default button: Return saves once there is something
    # to save (Qt never fires a disabled default). HIG: a dialog names
    # its default action; crop_dialog and setup_flow already comply.
    save_btn.setDefault(True)
    # Cancel and Save in the platform's order (Save last on macOS, first
    # on Windows). Their clicks are wired directly below; the box only
    # places them, so its accepted/rejected signals stay unconnected.
    button_box = QDialogButtonBox()
    button_box.addButton(close_btn, QDialogButtonBox.ButtonRole.RejectRole)
    button_box.addButton(save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
    close_row.addWidget(button_box)
    foot.addLayout(close_row)

    # One background operation at a time in this dialog.
    op_state: dict[str, Any] = {"active": False, "kind": "", "cancel": None}
    bindings: list = []

    def refresh_dirty() -> None:
        """Save and the unsaved label follow the FACT: pending values exist."""
        save_btn.setEnabled(state.dirty and not op_state["active"])
        unsaved_lbl.setText("Unsaved changes" if state.dirty else "")

    def paint_all() -> None:
        """Every widget from the state — the bound ones, then the
        Appearance controls and the accent swatches."""
        for b in bindings:
            b.paint()
        sync_background_widgets()
        sync_accent_swatches()

    runtime_state = {"owned": False, "update": False}

    def set_busy(busy: bool) -> None:
        op_state["active"] = busy
        for w in (
            endpoint_edit, embed_model_edit, runtime_auto_cb,
            install_btn, refresh_models_btn, pull_btn, pull_model_edit, installed_models,
            index_btn, test_conn_btn,
            threshold_slider, library_change_btn,
        ):
            w.setEnabled(not busy)
        stop_runtime_btn.setEnabled(not busy and runtime_state["owned"])
        update_runtime_btn.setEnabled(not busy and runtime_state["update"])
        delete_model_btn.setEnabled(not busy and installed_models.currentItem() is not None
                                    and installed_models.currentItem().data(Qt.ItemDataRole.UserRole) is not None)
        progress.setVisible(busy and op_state["kind"] != "local")
        progress_lbl.setVisible(busy and op_state["kind"] != "local")
        refresh_dirty()

    # ----- Local models handlers --------------------------------------

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

        cfg = settings.read()
        sig = embeddings.index_signature(cfg)
        st = curation.index_stats()
        if not st["exists"]:
            txt = "No card index yet. Click Index Now to enable semantic search."
        else:
            txt = f"{st['count']:,} cards indexed · updated {_fmt_ago(st['updated_at'])}"
            if not embeddings.signature_matches(
                st["provider"], st["model"], st.get("dims", 0), sig
            ):
                txt += " · settings changed: next indexing rebuilds from scratch"
        embed_status.setText(txt)

    REINDEX_HINT = "Press ⟳ in the Library to re-index for the new model."

    def _run_index_sweep(_prev_sig) -> None:
        """The ``index_sweep`` effect: the stored signature moved under the
        index. Indexing is manual; Save's own tooltip says where to rebuild
        it (one tooltip: Anki's ``tooltip`` closes the previous one)."""
        update_embed_status()

    def _update_threshold_label(value: int) -> None:
        threshold_value_lbl.setText(f"{value / 100:.2f}")

    def _apply_threshold_to_tuned() -> None:
        """The ``threshold_changed`` effect, after the new default is
        written: refresh an open Library and offer to clear the per-PDF
        overrides that would otherwise hide the change (K-052 rework #2).
        """
        from . import retention

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
                else "Klaus: indexing cancelled. It resumes where it stopped."
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

        cfg = settings.read()
        sig = embeddings.index_signature(cfg)
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
            if op_state["active"] and op_state["kind"] == "index":
                # Indexing is the cancellable collection operation in this
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
                    "Stop it and close? Progress is saved, and indexing "
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

        if state.dirty:
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
                state.discard()
                paint_all()
                refresh_dirty()
                _after_dirty_check()

            msg1.finished.connect(_on_discard_answered)
            msg1.open()
        else:
            _after_dirty_check()

    def _bg_preview_cfg() -> dict:
        """The PENDING appearance keys in config shape, for background's
        preview override — the same keys Save writes (one flattener).

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
        out = _prefs_state.flatten_appearance(state.view())
        out.update({
            "heatmap_enabled": bool(_heatmap.enabled(settings.read())),
            # The heatmap's own corner menu writes these two, and it can
            # be used while this dialog is open — so they are carried
            # from STORED config and read live per tick, exactly like
            # heatmap_enabled above and dashboard_order below.
            "heatmap_history_days": _heatmap.history_window(settings.read()),
            "heatmap_forecast": _heatmap.forecast_window(settings.read()) > 0,
            # The dashboard reads its order through effective_cfg too;
            # Preferences has no order UI, so carry the stored value —
            # read live per tick, in case the dashboard writes mid-preview.
            "dashboard_order": _dashboard.order_from_cfg(settings.read()),
            "dashboard_hidden": _dashboard.hidden_foreign(settings.read()),
            "dashboard_sizes": _dashboard.sizes_from_cfg(settings.read()),
            "dashboard_uniform": _dashboard.uniform_from_cfg(settings.read()),
        })
        return out

    def apply_appearance_live() -> None:
        """Render the pending accent + background EVERYWHERE, saving
        nothing.

        Appearance is the one class of setting judged by eye, so it
        previews live while the dialog is open; Save remains the only
        writer of config (state.commit() in save_all). Cancelling runs
        revert_appearance_preview() to put the stored look back.
        """
        try:
            # Background first: top_bar.refresh() below repaints from it.
            _background.set_preview(_bg_preview_cfg())
            # Accent colour before name: set_active_theme("custom") is
            # only meaningful once the colour behind it is loaded.
            _theme_presets.set_custom_colour(str(state.get("color_theme_custom")))
            _theme_presets.set_active_theme(str(state.get("color_theme")))
            dlg.setStyleSheet(
                _theme_presets.dialog_qss(_theme_presets.night_mode())
            )
            # The swatches carry their own inline QSS, so the dialog
            # sheet swap above wipes them — repaint from the state.
            sync_accent_swatches()
            # The sidebar k is a baked pixmap filled in blue_accent;
            # re-render it or it keeps the old accent until reopen.
            _new_logo = _logo_pixmap(logo_px[0], logo_lbl.devicePixelRatioF())
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
        refresh_dirty()
        _preview_timer.start()

    def _run_effect(effect: tuple) -> None:
        """Dispatch one ``Commit.effect`` (prefs_state's fixed vocabulary)."""
        kind = effect[0]
        if kind == "index_sweep":
            _run_index_sweep(effect[1])
        elif kind == "threshold_changed":
            _apply_threshold_to_tuned()
        elif kind == "anki_theme":
            # Anki's own theme — the one non-Klaus preference this dialog
            # writes; only on an actual change (the effect IS the change):
            # mw.set_theme re-runs setupStyle, which repaints every webview.
            try:
                from aqt.theme import Theme as _Theme

                mw.set_theme(_Theme(int(effect[1])))
            except Exception as _exc:
                print(f"[klausmate] theme apply failed: {_exc}")
        elif kind == "appearance":
            # Paint through the same one path as every live edit, THEN
            # drop the override: stored config now holds identical
            # values, so leaving it armed would let a stale preview
            # shadow a later config change for the rest of the session.
            apply_appearance_live()
            _background.set_preview(None)

    def save_all() -> None:
        """The one writer of preference keys (the Save button): ONE patch
        of the keys that changed, then the effects that follow from them."""
        commit = state.commit()
        if commit.patch:
            settings.patch(commit.patch)
        for effect in commit.effects:
            _run_effect(effect)
        if _background.preview_active() and not any(e[0] == "appearance" for e in commit.effects):
            # A nudge-and-back armed the preview with baseline-equal values
            # and left nothing pending: stored config already matches, so
            # the override must not outlive this Save either.
            _background.set_preview(None)
        paint_all()
        refresh_dirty()
        saved = "Klaus: preferences saved."
        if any(e[0] == "index_sweep" for e in commit.effects):
            saved += " " + REINDEX_HINT
        tooltip(saved, parent=dlg)

    def change_library_folder() -> None:
        """Point the Library at a different on-disk folder, moving
        whatever's already there (K-070, part A of K-057) — same guarded,
        resumable move as setup_flow's first-time prompt, just old root
        -> new root instead of unset -> chosen.
        """
        from aqt.qt import QFileDialog

        from . import drive_store, pdf_handler, settings

        cfg = settings.read()
        old_root = pdf_handler.get_library_root(cfg)
        new_root = QFileDialog.getExistingDirectory(
            dlg, "Choose a folder for your Klaus Library", old_root or ""
        )
        if not new_root or new_root == old_root:
            return

        def do(_col: Any) -> Any:
            folders = drive_store.load(settings.user_files()).get("pdfs", {})
            return pdf_handler.migrate_to_root(
                settings.user_files(), new_root, folders, old_root=old_root
            )

        def on_done(result: Any) -> None:
            set_busy(False)
            settings.patch({"library_root": new_root})
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

    def local_alive() -> bool:
        return not profile_cancel.is_set() and _OPEN_DLG is dlg and _dlg_alive()

    def runtime_snapshot(endpoint: str) -> dict:
        from .ollama_client import OllamaClient

        client = OllamaClient(endpoint, timeout=5)
        reachable = client.health()
        owned = ollama_runtime.server_manager.spawned_or_adopted()
        managed = ollama_runtime.find_managed_runtime()
        update = bool(
            managed and managed[0] != ollama_runtime.OLLAMA_VERSION
            and owned and ollama_runtime.server_manager.active_binary() == managed[1]
        )
        models = []
        for name in client.list_models() if reachable else []:
            try:
                capabilities = client.model_capabilities(name)
            except Exception:
                capabilities = []
            models.append((name, capabilities))
        return {"reachable": reachable, "owned": owned, "update": update, "models": models}

    def _bar(report) -> None:
        """Report to the status bar; a report never breaks the op."""
        try:
            from . import tasks

            report(tasks)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] Ollama status report failed: {exc}")

    def local_progress(event: dict) -> None:
        # Runtime and HTTP callbacks run on workers. Every Qt access,
        # including the liveness check, belongs on the main thread.
        # The status bar's tracker is thread-safe, so it is fed here.
        event = dict(event)
        _bar(lambda t: t.update("ollama", done=int(event.get("completed") or 0),
                                total=int(event.get("total") or 0)))
        def apply() -> None:
            if not local_alive():
                return
            runtime_status.setText(str(event.get("status") or "Working…"))
            total = event.get("total") or 0
            if total:
                runtime_progress.setRange(0, 100)
                runtime_progress.setValue(int(100 * (event.get("completed") or 0) / total))
            else:
                runtime_progress.setRange(0, 0)
        mw.taskman.run_on_main(apply)

    def run_local(action: str, model: str = "") -> None:
        if op_state["active"] or not local_alive():
            return
        cfg = settings.read()
        starting_endpoint = cfg.get("endpoint")
        cfg["endpoint"] = endpoint_edit.text().strip() or "http://127.0.0.1:11434"
        endpoint = cfg["endpoint"]
        # Manual unsaved endpoints remain owned by Save, including relocation.
        save_endpoint = (
            setup_flow.runtime_endpoint_saver(profile_lifetime, starting_endpoint)
            if endpoint == (starting_endpoint or "http://127.0.0.1:11434") else None
        )
        op_state["kind"] = "local"
        set_busy(True)
        _bar(lambda t: t.begin("ollama", f"Ollama: {action}" + (f" {model}" if model else "")))
        runtime_status.setText(f"{action}… You can close Preferences; the operation continues.")
        runtime_progress.setRange(0, 0)

        def perform(cancel_flag: threading.Event | None = None) -> tuple:
            from .ollama_client import OllamaClient

            result = None
            if action == "Install/Start":
                result = ollama_runtime.full_setup(cfg, on_progress=local_progress, cancel_flag=cancel_flag, save_config=save_endpoint)
            elif action == "Update Runtime":
                result = ollama_runtime.update_runtime(cfg, on_progress=local_progress, cancel_flag=cancel_flag, save_config=save_endpoint)
            elif action == "Stop Managed Server":
                if not ollama_runtime.server_manager.spawned_or_adopted():
                    raise RuntimeError("This server is external. Stop it in the application that started it.")
                ollama_runtime.server_manager.stop()
            elif action == "Pull":
                OllamaClient(endpoint).pull(model, on_event=local_progress)
            elif action == "Delete":
                OllamaClient(endpoint).delete(model)
            if result is not None and not result.ok:
                raise RuntimeError(result.detail or "Ollama could not start. Check the endpoint and try Install/Start again.")
            actual_endpoint = result.endpoint if result is not None else endpoint
            return runtime_snapshot(actual_endpoint), actual_endpoint

        def work(_col: Any) -> Any:
            if profile_cancel.is_set():
                return None
            if action in ("Install/Start", "Update Runtime", "Stop Managed Server"):
                return setup_flow.run_profile_runtime(profile_lifetime, perform)
            return perform()

        def done(result: tuple | None) -> None:
            _bar(lambda t: t.end("ollama"))  # before the liveness check: the bar outlives Preferences
            if result is None or not local_alive():
                return
            snapshot, actual_endpoint = result
            runtime_state.update(owned=snapshot["owned"], update=snapshot["update"])
            # Inventory updates never select a different embedding model.
            installed_models.blockSignals(True)
            installed_models.clear()
            for name, capabilities in snapshot["models"]:
                purposes = [label for key, label in (
                    ("embedding", "Card matching"), ("vision", "Images"),
                    ("completion", "Text generation")) if key in capabilities]
                item = QListWidgetItem(name + "\n" + (" · ".join(purposes) or "Unknown type"))
                item.setData(Qt.ItemDataRole.UserRole, (name, capabilities))
                installed_models.addItem(item)
            installed_models.blockSignals(False)
            if actual_endpoint != endpoint:
                if settings.read().get("endpoint") == actual_endpoint:
                    # Stored moved under us: the baseline follows, whatever
                    # the field holds (a mid-operation edit stays pending).
                    state.reseed("endpoint", actual_endpoint)
                elif endpoint_edit.text().strip() == endpoint:
                    state.set("endpoint", actual_endpoint)  # "Save to use the new endpoint"
                paint_all()
                refresh_dirty()
            if snapshot["reachable"]:
                status = "Ollama is running (managed by Klaus)." if snapshot["owned"] else (
                    "Ollama is running (external). Stop it in the application that started it."
                )
            else:
                status = "Ollama is not reachable. Check the endpoint and click Install/Start."
            if actual_endpoint != endpoint:
                status += (
                    " The runtime chose another port; its endpoint was saved."
                    if settings.read().get("endpoint") == actual_endpoint else
                    " The runtime chose another port. Save to use the new endpoint."
                )
            runtime_status.setText(status)
            runtime_progress.setRange(0, 100)
            runtime_progress.setValue(100 if action in ("Pull", "Install/Start", "Update Runtime") else 0)
            op_state["kind"] = ""
            set_busy(False)

        def failed(exc: Exception) -> None:
            _bar(lambda t: t.end("ollama", f"{action} failed: {exc}", error=True))
            if not local_alive():
                return
            runtime_status.setText(f"{action} failed: {exc}")
            runtime_progress.setRange(0, 100)
            runtime_progress.setValue(0)
            op_state["kind"] = ""
            set_busy(False)

        op = QueryOp(parent=dlg, op=work, success=done)
        op.failure(failed)
        op.without_collection().run_in_background()

    def select_installed_model() -> None:
        item = installed_models.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        delete_model_btn.setEnabled(not op_state["active"] and data is not None)
        if data is not None and "embedding" in data[1]:
            state.set("embedding_model", data[0])
            paint_all()
            refresh_dirty()

    def pull_model() -> None:
        name = pull_model_edit.text().strip()
        if not name:
            runtime_status.setText("Enter a model name, such as nomic-embed-text, then click Download.")
            return
        run_local("Pull", name)

    def delete_model() -> None:
        item = installed_models.currentItem()
        if item is None or op_state["active"]:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data is None:
            return
        name = data[0]
        msg = QMessageBox(dlg)
        msg.setWindowTitle("Delete model?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(f"Delete {name} from Ollama? You will need to download it again to use it.")
        msg.setTextFormat(Qt.TextFormat.PlainText)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        def answered(_result: int) -> None:
            clicked = msg.clickedButton()
            confirmed = clicked is not None and msg.standardButton(clicked) == QMessageBox.StandardButton.Yes
            msg.deleteLater()
            if confirmed and local_alive():
                run_local("Delete", name)
        msg.finished.connect(answered)
        msg.open()

    install_btn.clicked.connect(lambda: run_local("Install/Start"))
    stop_runtime_btn.clicked.connect(lambda: run_local("Stop Managed Server"))
    update_runtime_btn.clicked.connect(lambda: run_local("Update Runtime"))
    refresh_models_btn.clicked.connect(lambda: run_local("Refresh"))
    pull_btn.clicked.connect(pull_model)
    delete_model_btn.clicked.connect(delete_model)
    delete_model_btn.setEnabled(False)
    installed_models.currentItemChanged.connect(lambda *_args: select_installed_model())

    def test_connection() -> None:
        if op_state["active"]:
            return
        from .ollama_client import OllamaClient
        endpoint = endpoint_edit.text().strip() or "http://127.0.0.1:11434"
        set_busy(True)
        def done(reachable: bool) -> None:
            if _OPEN_DLG is not dlg:
                return
            set_busy(False)
            if reachable:
                showInfo("Local Ollama is reachable.", parent=dlg)
            else:
                showWarning("Cannot connect to Ollama. Check the endpoint and start Ollama.", parent=dlg)
        op = QueryOp(parent=dlg, op=lambda _col: OllamaClient(endpoint, timeout=5).health(), success=done)
        op.failure(lambda _exc: done(False))
        op.without_collection().run_in_background()

    cancel_btn.clicked.connect(cancel_index)
    dlg.confirm_close_cb = confirm_close  # Esc and title-bar ✕ too
    test_conn_btn.clicked.connect(test_connection)
    close_btn.clicked.connect(confirm_close)
    # Value widgets are _Binding adapters over the state: a signal is an
    # edit, Save commits. textEdited rather than editingFinished so the
    # Save button lights up as you type; valueChanged on the slider so a
    # keyboard edit counts too (sliderReleased never fires for one).
    def _paint_threshold(value: float) -> None:
        threshold_slider.setValue(int(round(value * 100)))
        _update_threshold_label(threshold_slider.value())

    bindings[:] = [
        _Binding(state, "image_crop_enabled", image_crop_cb.isChecked, image_crop_cb.setChecked,
                 image_crop_cb.toggled, refresh_dirty),
        _Binding(state, "endpoint", endpoint_edit.text, endpoint_edit.setText, endpoint_edit.textEdited, refresh_dirty),
        _Binding(state, "embedding_model", embed_model_edit.text, embed_model_edit.setText,
                 embed_model_edit.textEdited, refresh_dirty),
        _Binding(state, "runtime_auto_setup", runtime_auto_cb.isChecked, runtime_auto_cb.setChecked,
                 runtime_auto_cb.toggled, refresh_dirty),
        _Binding(state, "pdf_match_threshold", lambda: threshold_slider.value() / 100, _paint_threshold,
                 threshold_slider.valueChanged, refresh_dirty),
        _Binding(state, "anki_theme", lambda: int(anki_theme_combo.currentData() or 0),
                 lambda v: anki_theme_combo.setCurrentIndex(max(0, anki_theme_combo.findData(int(v)))),
                 anki_theme_combo.currentIndexChanged, refresh_dirty),
    ]
    threshold_slider.valueChanged.connect(_update_threshold_label)
    index_btn.clicked.connect(start_index)
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

    def _on_grad_geom(spec_key: str, s: dict, i: int, data: dict) -> None:
        """A sphere moved/resized. QUIET on purpose — never
        top_bar.refresh(): the page already shows the dragged stack
        (the editor painted it inline), and a refresh would rebuild
        the page under the pointer."""
        g = s["gradients"][i]
        g["x"], g["y"], g["size"] = data["x"], data["y"], data["size"]
        if i == 0:
            # Legacy single-gradient mirror (what flatten_appearance also
            # writes), so a downgrade or hand-read config stays sane.
            s["grad_x"], s["grad_y"], s["grad_size"] = (
                data["x"], data["y"], data["size"],
            )
        state.set(spec_key, s)
        refresh_dirty()
        _quiet_preview()

    def _pick_sphere_colour(spec_key: str, i: int) -> None:
        """Recolor sphere i — the on-screen dot IS the colour chip, a
        click on it lands here (deferred one tick: modal work must
        never run inside a webchannel dispatch)."""
        from aqt.qt import QColor, QColorDialog

        s = state.get(spec_key)
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
        state.set(spec_key, s)
        refresh_dirty()
        _quiet_preview()
        sync_background_widgets()
        _replant_editor()

    def _on_grad_dragged(target: str, op: str, data: dict) -> None:
        """The on-screen editor's bridge sink (values already clamped
        in background.grad_edit_event). List bounds and the sphere cap
        are enforced HERE — JS indices are never trusted either."""
        spec_key = "reviewer_background" if target == "reviewer" else "background"
        s = state.get(spec_key)
        gradients = s["gradients"]
        i = int(data.get("i", 0))
        if op == "geom":
            if 0 <= i < len(gradients):
                _on_grad_geom(spec_key, s, i, data)
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
                state.set(spec_key, s)
                refresh_dirty()
                _quiet_preview()
                sync_background_widgets()
                _replant_editor()
        elif op == "remove":
            # The last sphere stays — colour mode IS a gradient; an
            # empty stack would be flat, which was removed outright.
            if len(gradients) > 1 and 0 <= i < len(gradients):
                gradients.pop(i)
                state.set(spec_key, s)
                refresh_dirty()
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
    # A control moved within 140 ms of closing left a tick pending that
    # re-armed the preview after the revert below (K-305): stop it first.
    dlg.finished.connect(lambda _result: _preview_timer.stop())
    # finished fires on EVERY close path (Save, Cancel, Esc, title-bar ✕),
    # so it is the one place an unsaved preview can be guaranteed not to
    # outlive the dialog. No-op unless a preview is actually armed.
    dlg.finished.connect(lambda _result: revert_appearance_preview())

    def _on_profile_will_close() -> None:
        # A NON-MODAL window can outlive its profile — close it before
        # the collection goes away. Forced, never through confirm_close:
        # its "Discard changes?" / "Stop indexing?" prompts return without
        # closing, which left the window and its armed appearance preview
        # open into the next profile. Unsaved edits are dropped with the
        # collection they were for; a running index stops (it resumes).
        # reject() then routes through finished → revert_appearance_preview.
        _close_for_profile(dlg, _preview_timer, op_state)

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

    paint_all()
    refresh_dirty()
    update_embed_status()
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
    external_op = QueryOp(parent=dlg, op=lambda _col: external_python(), success=external_ready)
    external_op.failure(lambda _exc: external_ready(None))
    external_op.without_collection().run_in_background()
    # Plant the gradient drag handles right away when a gradient is
    # already configured (arming an edge colour later plants them via
    # that edit's own live-preview refresh). After show(), so the one
    # deck-screen rebuild happens behind the appearing window.
    try:
        if (
            state.get("background")["mode"] == "color"
            or state.get("reviewer_background")["mode"] == "color"
        ):
            from . import top_bar as _top_bar

            _top_bar.refresh()
    except Exception as _exc:
        print(f"[klausmate] gradient handle plant failed: {_exc}")
