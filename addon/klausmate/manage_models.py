"""KlausMate Preferences dialog: provision the local AI runtime, pull a
local embedding model, configure semantic search, and hold the two
maintenance action (Test connection).

Extracted verbatim from __init__.py (K-023, slice 1 of the K-006 file
split). Backs Tools > KlausMate Preferences — the single Tools-menu entry
point (K-045 folded the old 'Klaus' submenu's three items in here) — plus
the first-run one-click setup path.

Klaus is embeddings-only (K-027 dropped autocomplete and the Ask ⌘K
popover): the Semantic search and Local model library sections are one
job — where semantic search's embeddings come from (Voyage / OpenAI / a
local Ollama model). General holds the two toggles orphaned by
settings_ui.py's deletion, plus Test connection (K-045 moved it out
of the Tools menu so it stays reachable — a menu item that vanishes is
worse than one click deeper; the old Clear-library-tag action is gone
entirely, K-critique caught this docstring still advertising it).

This module is imported by __init__.py at package load time, so it must
never import __init__ (this package) at module load — only from inside a
function, after the package has finished loading. _pkg() below is that
lazy accessor (same pattern as curation.py's _pkg()); it reaches config
and helpers that live in __init__.py: get_config, write_config, client,
open_config, _save_config_on_main.
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
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import askUser, openLink, showInfo, showWarning, tooltip

from .md3_switch import Md3Switch
from .ollama_client import OllamaError
from .ollama_runtime import RuntimeProvisionError, full_setup, runtime_download_size_hint
from .ollama_setup import (
    OLLAMA_DOWNLOAD_URL,
    InstallMethod,
    install_methods,
    ollama_reachable,
    run_install_method,
)


def _pkg():
    import importlib

    return importlib.import_module(__package__)


# ----------------------------- model manager -----------------------------

# Embedding-model presets offered in the pull dropdown. Index 0 must stay
# nomic-embed-text — it is embeddings.DEFAULT_MODELS['ollama'] and the
# model the one-click setup flow auto-pulls when the library is empty.
_EMBED_PRESETS = [
    ("nomic-embed-text", "default, best all-round · ~274 MB"),
    ("all-minilm", "tiny, fastest · ~46 MB"),
    ("snowflake-arctic-embed", "strong retrieval · ~670 MB"),
    ("mxbai-embed-large", "best quality · ~670 MB"),
    ("bge-m3", "multilingual, long context · ~1.2 GB"),
    ("embeddinggemma", "Google, newest · ~620 MB"),
]

_EMBED_KEY_URLS = {
    "voyage": "https://dash.voyageai.com/api-keys",
    "openai": "https://platform.openai.com/api-keys",
}

_EMBED_KEY_PLACEHOLDERS = {
    "voyage": "pa-…  (free tier at voyageai.com; stored in add-on config)",
    "openai": "sk-…  (platform.openai.com; stored in add-on config)",
}


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


def _logo_pixmap(size: int) -> Any:
    """The Klaus star for the Preferences sidebar, drawn exactly like
    the top bar's: an open stroke in the accent colour on a transparent
    ground — no icon-square treatment — from the same
    top_bar.star_points() data the toolbar's SVG strokes."""
    try:
        from aqt.qt import QColor, QPainter, QPen, QPixmap, QPointF, QPolygonF

        from . import theme as _theme
        from . import top_bar as _top_bar

        dpr = 2.0
        px = QPixmap(int(size * dpr), int(size * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(QColor(0, 0, 0, 0))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = _theme.palette(_theme.night_mode())
        # Inset by the pen's radius so the stroke can't clip at the edges.
        width = max(1.3, size * 0.09)
        inset = width / 2.0
        scale = (size - width) / _top_bar.STAR_VIEWBOX
        poly = QPolygonF(
            [
                QPointF(x * scale + inset, y * scale + inset)
                for x, y in _top_bar.star_points()
            ]
        )
        pen = QPen(QColor(c["blue_accent"]))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(poly)
        painter.end()
        return px
    except Exception as exc:
        print(f"[klausmate] sidebar logo failed: {exc}")
        return None


def _format_pull_event(ev: dict) -> tuple[str, int]:
    """Return (human status, percent 0-100) for an Ollama pull progress event."""
    status = str(ev.get("status") or "")
    total = ev.get("total")
    completed = ev.get("completed")
    pct = 0
    if isinstance(total, (int, float)) and total > 0 and isinstance(completed, (int, float)):
        pct = int(min(100, max(0, completed * 100 / total)))
    if status == "success":
        pct = 100
    digest = str(ev.get("digest") or "")
    digest_short = digest[:12] + "…" if digest else ""
    label = status
    if digest_short:
        label = f"{status} ({digest_short})"
    if pct and total:
        mb = total / (1024 * 1024)
        label = f"{label} — {pct}% of {mb:.0f} MB"
    return label, pct


def _resolve_ollama_model(
    configured: str, models: list[str], indexed_model: str, default: str
) -> str:
    """What real model name the Ollama 'Search model' field should show when
    the config's embedding_model is empty, instead of silently falling
    through to embeddings.DEFAULT_MODELS['ollama'] — a stored index built
    with a different model would then look orphaned, and one click on
    'Index cards now' would discard it (K-039). Dialog-level resolution
    only; the embedding contract in embeddings.py is untouched.

    Precedence: (a) the model the existing index was actually built with,
    if it is currently installed; (b) the one model installed, if there is
    exactly one; (c) the hardcoded default.
    """
    configured = configured.strip()
    if configured:
        return configured
    if indexed_model and indexed_model in models:
        return indexed_model
    if len(models) == 1:
        return models[0]
    return default


class _KlausManageDialog(QDialog):
    """QDialog whose EVERY close path goes through the confirm callback.

    Esc triggers QDialog.reject() and the title-bar ✕ triggers closeEvent —
    neither hits a Close button's clicked signal. Without routing them
    through confirm_close, a runtime setup download would keep streaming
    invisibly after the dialog vanishes (and a retry would corrupt the
    shared .part file).
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
        _logo = _logo_pixmap(24)
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


def manage_models_dialog(setup: bool = False) -> None:
    """Set up the local AI runtime, pull an embedding model, and configure
    semantic search.

    ``setup=True`` is the one-click first-run path: it auto-opens the
    provisioning confirm on the setup page, and after the server is up it
    chains straight into pulling the starter model when none exist.
    """
    if _BARE_DIALOG_PROBE:
        try:
            _run_dialog_probe()
        except Exception as exc:
            print(f"[klausmate] dialog probe failed: {exc}")
        return

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

    stack = QStackedWidget()
    outer.addWidget(stack)

    # ----- Page 0: Install Ollama -----------------------------------------
    # Predates the K-106 sidebar shell; K-111 brought its title/subtitle
    # onto the same objectName language as _page() below (PageTitle +
    # PageSubtitle) even though this page keeps its own full-frame layout
    # with no sidebar/nav pill — a user with no Ollama shouldn't see
    # settings navigation offering pages that can't work yet.
    install_page = QWidget()
    install_layout = QVBoxLayout(install_page)
    install_layout.setContentsMargins(24, 18, 24, 8)
    install_layout.setSpacing(8)

    install_title = QLabel("Set up local AI")
    install_title.setObjectName("PageTitle")
    install_layout.addWidget(install_title)

    install_body = QLabel(
        "Klaus runs AI locally through Ollama — nothing ever leaves your "
        "computer. Klaus can download and manage its own copy "
        "automatically, or you can install Ollama yourself."
    )
    install_body.setObjectName("PageSubtitle")
    install_body.setWordWrap(True)
    install_layout.addWidget(install_body)
    install_layout.addSpacing(8)

    install_status = QLabel()
    install_status.setWordWrap(True)
    install_status.setStyleSheet(_MUTED)
    install_layout.addWidget(install_status)

    auto_setup_btn = QPushButton(
        f"Set up automatically ({runtime_download_size_hint()} download)"
    )
    auto_setup_btn.setDefault(True)
    install_layout.addWidget(auto_setup_btn)

    manual_lbl = QLabel("Manual options")
    manual_lbl.setObjectName("InstallSection")
    install_layout.addWidget(manual_lbl)

    download_btn = QPushButton("Open download page")
    download_btn.setObjectName("SecondaryButton")
    install_layout.addWidget(download_btn)

    install_methods_box = QWidget()
    install_methods_layout = QVBoxLayout(install_methods_box)
    install_methods_layout.setContentsMargins(0, 0, 0, 0)
    install_methods_layout.setSpacing(6)
    install_layout.addWidget(install_methods_box)

    install_steps = QLabel(
        "After installing manually:\n"
        "1. Finish the installer and grant permissions if prompted.\n"
        "2. Start Ollama (open the app or ensure the service is running).\n"
        "3. Click Check connection, then pull a model on the next screen."
    )
    install_steps.setWordWrap(True)
    install_steps.setStyleSheet(_MUTED)
    install_layout.addWidget(install_steps)

    install_btn_row = QHBoxLayout()
    check_conn_btn = QPushButton("Check connection")
    check_conn_btn.setObjectName("SecondaryButton")
    install_btn_row.addWidget(check_conn_btn)
    install_btn_row.addStretch(1)
    install_layout.addLayout(install_btn_row)
    install_layout.addStretch(1)

    stack.addWidget(install_page)

    # ----- Page 1: semantic search, then its model library -----------------
    # Klaus is embeddings-only: there is exactly one job here. This box asks
    # the three questions that job needs answered — where do embeddings come
    # from, what proves you can use it, which model — and the library below
    # is pure inventory (pull, delete, see what's installed).
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
    # right, hairline-separated. The install page (page 0 of the OUTER
    # stack) stays a full-frame page with no sidebar: a user with no
    # Ollama should not see navigation offering settings that cannot
    # work yet.
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
    _logo = _logo_pixmap(24)
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
        # klaus_hidden = structurally hidden (e.g. the API-key row under
        # Ollama) — it always beats a search hit in _apply_search.
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

    embed_layout = _page(
        "Semantic Search",
        "Semantic Search",
        "Finds cards and decks by meaning, not just keywords — powers "
        "Curate Deck and the Library's retention scores. Needs a Voyage "
        "or OpenAI key (both have free tiers) or a local Ollama model "
        "from the Local Models page.",
    )

    embed_provider_combo = QComboBox()
    embed_provider_combo.addItem("Voyage API (default)", "voyage")
    embed_provider_combo.addItem("OpenAI API", "openai")
    embed_provider_combo.addItem("Local Ollama (private, free)", "ollama")
    embed_provider_combo.setMinimumWidth(220)
    embed_fix_btn = QPushButton("Pull it")
    embed_fix_btn.setVisible(False)
    provider_ctl = QHBoxLayout()
    provider_ctl.setContentsMargins(0, 0, 0, 0)
    provider_ctl.addWidget(embed_provider_combo)
    provider_ctl.addWidget(embed_fix_btn)
    _row(
        embed_layout,
        "Embeddings from",
        "Voyage and OpenAI are cloud APIs; Ollama runs on your machine, "
        "private and free.",
        provider_ctl,
    )

    embed_model_combo = QComboBox()
    embed_model_combo.setEditable(True)
    embed_model_combo.setMinimumWidth(220)
    _row(
        embed_layout,
        "Search model",
        "Blank uses the provider's default. Changing provider or model "
        "rebuilds the card index.",
        embed_model_combo,
    )

    embed_key_edit = QLineEdit()
    embed_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    embed_key_edit.setMinimumWidth(220)
    # The whole row hides for Ollama (update_embed_status) — the local
    # provider has no key to ask for.
    key_row = _row(
        embed_layout,
        "API key",
        "For the selected cloud provider. Stored in this add-on's "
        "config on your machine.",
        embed_key_edit,
    )

    embed_status = QLabel()
    embed_status.setWordWrap(True)
    index_btn = QPushButton("Index cards now")
    _row(embed_layout, "Card index", embed_status, index_btn)

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
        embed_layout,
        "Default match sensitivity",
        "For every PDF that hasn't been tuned individually. Changing it "
        "offers to reset tuned PDFs too; any single PDF can still be "
        "adjusted in the Library (right-click → Match sensitivity).",
        threshold_ctl,
    )

    # ----- Local model library (inventory only) -------------------------
    lib_layout = _page(
        "Local Models",
        "Local Models",
        "Ollama embedding models installed on this machine — pull new "
        "ones, delete what you no longer use.",
    )
    lib_layout.setContentsMargins(16, 12, 16, 12)
    lib_layout.setSpacing(6)

    status_lbl = QLabel()
    status_lbl.setStyleSheet(_MUTED)
    lib_layout.addWidget(status_lbl)

    lib_lst = QListWidget()
    lib_lst.setMinimumHeight(96)
    lib_layout.addWidget(lib_lst)

    pull_row = QHBoxLayout()
    pull_input = QComboBox()
    pull_input.setEditable(True)
    pull_input.setMinimumWidth(220)
    pull_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _fill_pull_presets() -> None:
        pull_input.clear()
        for name, desc in _EMBED_PRESETS:
            pull_input.addItem(f"{name}   ({desc})", name)
        pull_input.setCurrentIndex(-1)
        edit = pull_input.lineEdit()
        if edit is not None:
            edit.setPlaceholderText("pick or type an embedding model to download")

    _fill_pull_presets()
    pull_btn = QPushButton("Pull")
    delete_btn = QPushButton("Delete")
    delete_btn.setObjectName("DangerButton")
    refresh_btn = QPushButton("Refresh")
    refresh_btn.setObjectName("SecondaryButton")
    pull_row.addWidget(pull_input, 1)
    pull_row.addWidget(pull_btn)
    pull_row.addWidget(delete_btn)
    pull_row.addWidget(refresh_btn)
    lib_layout.addLayout(pull_row)

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

    runtime_auto_cb = Md3Switch()  # MD3 switch (K-material3), not a checkbox
    _row(
        general_layout,
        "Manage Ollama automatically",
        "Start the local AI engine in the background and offer one-click "
        "setup when it's missing.",
        runtime_auto_cb,
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
    test_conn_btn = QPushButton("Test connection")
    test_conn_btn.setObjectName("SecondaryButton")
    _row(
        general_layout,
        "Connection",
        "Check that the embedding provider is reachable.",
        test_conn_btn,
    )

    # ---- Appearance: custom background + the frosted top bar ----
    # A blurred flat colour IS that colour, so "Solid colour" also makes
    # the top bar match the window chrome exactly (background.py).
    appearance_layout = _page(
        "Appearance",
        "Appearance",
        "Sets the background of Anki's deck, overview and congrats "
        "screens. The Klaus top bar shows the same background blurred, "
        "so it reads as frosted glass over it.",
    )

    bg_mode_combo = QComboBox()
    bg_mode_combo.addItem("Anki's own (default)", "theme")
    bg_mode_combo.addItem("Solid colour", "color")
    bg_mode_combo.addItem("Image", "image")
    bg_colour_btn = QPushButton("Colour…")
    bg_colour_btn.setObjectName("SecondaryButton")
    bg_image_btn = QPushButton("Choose image…")
    bg_image_btn.setObjectName("SecondaryButton")
    bg_ctl = QHBoxLayout()
    bg_ctl.setContentsMargins(0, 0, 0, 0)
    bg_ctl.addWidget(bg_mode_combo)
    bg_ctl.addWidget(bg_colour_btn)
    bg_ctl.addWidget(bg_image_btn)
    _row(
        appearance_layout,
        "Background",
        "Anki's own look, a solid colour, or an image of yours.",
        bg_ctl,
    )

    bg_image_lbl = QLabel()
    bg_image_lbl.setWordWrap(True)
    bg_image_lbl.setObjectName("SettingDesc")
    appearance_layout.addWidget(bg_image_lbl)

    bg_fit_combo = QComboBox()
    bg_fit_combo.addItem("Fill the window", "cover")
    bg_fit_combo.addItem("Fit inside", "contain")
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
        "Bar blur",
        "How strongly the top bar blurs an image behind it.",
        blur_ctl,
    )

    _general_cfg = _pkg().get_config()
    image_crop_cb.setChecked(bool(_general_cfg.get("image_crop_enabled", True)))
    runtime_auto_cb.setChecked(bool(_general_cfg.get("runtime_auto_setup", True)))
    from .pdfjs_viewer import renderer_from_config as _renderer_from_config

    pdfjs_cb.setChecked(_renderer_from_config(_general_cfg) == "pdfjs")

    from . import background as _background

    # Own syncing flag, NOT ui_state["syncing"]: this block builds and
    # runs sync_background_widgets() BEFORE ui_state is assigned further
    # down the function, and a closure's free variable is only looked up
    # at call time — referencing ui_state here crashed the dialog with
    # NameError the moment Preferences opened (live traceback).
    _bg_state = {"spec": _background.resolve(_general_cfg), "syncing": False}
    # Coalesces live appearance previews: top_bar.refresh() redraws the
    # toolbar and resets the main window, and the blur slider fires
    # continuously while dragged, so previewing per signal would repaint
    # per pixel. 140ms is under the ~200ms that reads as "instant" while
    # still collapsing a drag into a handful of repaints.
    _preview_timer = QTimer(dlg)
    _preview_timer.setSingleShot(True)
    _preview_timer.setInterval(140)

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
        finally:
            _bg_state["syncing"] = False
        bg_blur_lbl.setText(f"{spec['blur']}px")
        is_image = spec["mode"] == "image"
        is_colour = spec["mode"] == "color"
        bg_colour_btn.setEnabled(is_colour or is_image)
        bg_image_btn.setEnabled(is_image)
        # Whole rows, so the name and description grey out with the
        # control — a live-looking label over a dead slider was the
        # reason these read as broken rather than inactive.
        bg_fit_row.setEnabled(is_image)
        bg_blur_row.setEnabled(is_image)
        bg_image_lbl.setText(
            f"Image: {spec['image']}" if spec["image"]
            else ("No image chosen yet." if is_image else "")
        )
        bg_image_lbl.setVisible(bool(bg_image_lbl.text()))

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

    def pick_bg_colour() -> None:
        from aqt.qt import QColor, QColorDialog

        current = QColor(_bg_state["spec"]["color"])
        chosen = QColorDialog.getColor(current, dlg, "Background colour")
        if not chosen.isValid():
            return
        _bg_state["spec"]["color"] = chosen.name()
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
            QColor(str(_accent_state["custom"])), dlg, "Accent colour"
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
            "Custom colour — click to pick" if _is_custom
            else _name.capitalize()
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
        "Accent colour",
        "Recolours buttons, pills and highlights across every Klaus "
        "surface. The last square is your own colour — click it to pick.",
        accent_ctl,
    )

    def _refresh_library_label() -> None:
        from . import pdf_handler

        root = pdf_handler.get_library_root(_pkg().get_config())
        library_path_lbl.setText(root or "Not set — PDFs stay inside the add-on")

    _refresh_library_label()
    _finish_nav("General", "Appearance", "Semantic Search", "Local Models")

    stack.addWidget(models_page)

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
    cancel_btn = QPushButton("Cancel download")
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
    close_row.addWidget(save_btn)
    foot.addLayout(close_row)

    install_action_btns: list[QPushButton] = []
    op_state: dict[str, Any] = {"active": False, "kind": "", "cancel": None}
    # Written by refresh(); read by the index pipeline (missing-model check)
    # and the section-sync guards (avoid save-on-programmatic-set loops).
    # "dirty"/"shown_provider" back the deferred-save model: preference
    # widgets no longer write on every keystroke or toggle — Save does.
    # "shown_provider" is the provider the embed widgets are currently
    # DISPLAYING, which runs ahead of the stored config while unsaved.
    ui_state: dict[str, Any] = {
        "models": [],
        "syncing": False,
        "dirty": False,
        "shown_provider": "",
    }

    def set_busy(busy: bool) -> None:
        op_state["active"] = busy
        for w in (
            pull_btn, pull_input, delete_btn, refresh_btn,
            auto_setup_btn, download_btn, check_conn_btn,
            embed_provider_combo, embed_model_combo, embed_key_edit,
            embed_fix_btn, index_btn, test_conn_btn,
            threshold_slider, library_change_btn,
        ):
            w.setEnabled(not busy)
        for btn in install_action_btns:
            btn.setEnabled(not busy)
        progress.setVisible(busy)
        progress_lbl.setVisible(busy)

    def endpoint_url() -> str:
        return _pkg().get_config().get("endpoint", "http://localhost:11434")

    def rebuild_install_method_buttons() -> None:
        while install_methods_layout.count():
            item = install_methods_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        install_action_btns.clear()
        for method in install_methods():
            btn = QPushButton(method.label)
            btn.setToolTip(method.description)
            install_action_btns.append(btn)
            install_methods_layout.addWidget(btn)

            def _make_handler(m: InstallMethod = method) -> Callable[[], None]:
                return lambda: start_install(m)

            btn.clicked.connect(_make_handler())

    def show_install_page() -> None:
        stack.setCurrentIndex(0)
        install_status.setText(
            f"Could not reach Ollama at {endpoint_url()}.\n"
            "Use Set up automatically below — or install manually, start "
            "it, then click Check connection."
        )

    def get_selected_model() -> str:
        item = lib_lst.currentItem()
        if not item:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or item.text()

    def _needs_local_runtime(cfg: dict) -> bool:
        """True only when Ollama is the active embedding provider. A cloud
        (Voyage/OpenAI) user has no reason to land on a ~1GB local-runtime
        install page just because Ollama isn't running (K-036) — the
        install page stays reachable (switch the provider to Ollama, or
        click Pull), it just stops being the default landing."""
        from . import embeddings

        return embeddings.provider_name(cfg) == "ollama"

    def refresh() -> None:
        cfg = _pkg().get_config()
        ep = endpoint_url()
        models: list[str] = []
        reached = False
        if ollama_reachable(ep):
            try:
                models = list(_pkg().client().list_models())
                reached = True
            except OllamaError:
                reached = False

        if not reached and _needs_local_runtime(cfg):
            show_install_page()
            return

        stack.setCurrentIndex(1)
        ui_state["models"] = models
        status_lbl.setText(
            f"Connected to {ep}"
            if reached
            else "Local library needs Ollama — not required for your current provider."
        )
        sync_embed_widgets()
        sync_threshold_widget()
        rebuild_library_list()

    def rebuild_library_list() -> None:
        """Inventory with a 'used by' badge — pure inventory, doesn't
        assign anything (the embed row above does that)."""
        from . import embeddings

        cfg = _pkg().get_config()
        models = ui_state["models"]
        selected = get_selected_model()
        lib_lst.clear()

        embed_active = (
            embeddings.embedding_model(cfg)
            if embeddings.provider_name(cfg) == "ollama"
            else None
        )

        if not models:
            placeholder = QListWidgetItem("(no models installed — pull one below)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            lib_lst.addItem(placeholder)
            return
        for name in models:
            suffix = "   ·  used by: search" if name == embed_active else ""
            item = QListWidgetItem(name + suffix)
            item.setData(Qt.ItemDataRole.UserRole, name)
            lib_lst.addItem(item)
            if name == selected:
                lib_lst.setCurrentItem(item)

    def start_install(method: InstallMethod) -> None:
        ok = QMessageBox.question(
            dlg,
            "Install Ollama?",
            "Klaus will run this command on your computer:\n\n"
            f"  {method.command_display}\n\n"
            "You may be asked for your password in a system dialog. "
            "This can take several minutes.\n\n"
            "Continue?",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        op_state["kind"] = "install"
        set_busy(True)
        progress.setRange(0, 0)
        progress_lbl.setText(f"Installing via {method.id}…")

        def do() -> tuple[int, str]:
            return run_install_method(method)

        def on_done(result: tuple[int, str]) -> None:
            code, output = result
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            if code == 0:
                showInfo(
                    "Ollama install command finished.\n\n"
                    "Start the Ollama app if it is not already running, then "
                    "click Check connection."
                )
            else:
                showWarning(
                    f"Install command exited with code {code}.\n\n{output}"
                )
            refresh()

        def on_fail(exc: Exception) -> None:
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            showWarning(
                f"Could not run install command:\n\n{type(exc).__name__}: {exc}"
            )

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def maybe_auto_pull_starter() -> None:
        """setup mode: after the server is up, chain straight into pulling
        the default embedding model when none exist — one click end to
        end."""
        if not setup:
            return
        try:
            if _pkg().client().list_models():
                return
        except OllamaError:
            return
        pull_input.setCurrentIndex(0)  # default preset (nomic-embed-text)
        start_pull()

    def start_auto_setup() -> None:
        if op_state["active"]:
            return
        starter_note = (
            "Afterwards, if no model is installed yet, Klaus will also "
            f"pull the starter embedding model {_EMBED_PRESETS[0][0]} "
            "(~274 MB).\n\n"
            if setup
            else ""
        )
        ok = QMessageBox.question(
            dlg,
            "Set up local AI?",
            "Klaus will download the Ollama runtime from the official "
            f"GitHub release ({runtime_download_size_hint()}, verified "
            "against its published checksum) and run it in the background "
            "while Anki is open.\n\n"
            "It is stored in the add-on's user_files folder and can be "
            f"removed at any time.\n\n{starter_note}"
            "Continue?",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        cancel_event = threading.Event()
        op_state["kind"] = "setup"
        op_state["cancel"] = cancel_event
        set_busy(True)
        cancel_btn.setVisible(True)
        progress.setRange(0, 0)
        progress_lbl.setText("Preparing setup…")

        def on_event(ev: dict) -> None:
            label, pct = _format_pull_event(ev)

            def apply() -> None:
                progress_lbl.setText(label)
                if pct:
                    progress.setRange(0, 100)
                    progress.setValue(pct)
                else:
                    # Phases without byte totals (checksums, extract,
                    # winget) show as indeterminate.
                    progress.setRange(0, 0)

            mw.taskman.run_on_main(apply)

        def do() -> Any:
            return full_setup(
                _pkg().get_config(),
                on_progress=on_event,
                cancel_flag=cancel_event,
                save_config=_pkg()._save_config_on_main,
            )

        def finish() -> None:
            progress.setRange(0, 100)
            set_busy(False)
            cancel_btn.setVisible(False)
            op_state["kind"] = ""
            op_state["cancel"] = None

        def on_done(res: Any) -> None:
            finish()
            if getattr(res, "ok", False):
                cfg = _pkg().get_config()
                if cfg.get("_runtime_setup_declined"):
                    cfg["_runtime_setup_declined"] = False
                    _pkg().write_config(cfg)
                if getattr(res, "port_moved", False):
                    tooltip(f"Klaus: local AI running on {res.endpoint}")
                else:
                    tooltip("Klaus: local AI ready")
                refresh()
                maybe_auto_pull_starter()
            else:
                showWarning(
                    "Setup did not complete:\n\n"
                    + (getattr(res, "detail", "") or "Unknown error.")
                )
                refresh()

        def on_fail(exc: Exception) -> None:
            finish()
            if isinstance(exc, RuntimeProvisionError):
                if exc.kind == "cancelled":
                    tooltip("Klaus: setup cancelled")
                    return
                # unsupported_platform lands back on this page, where the
                # manual options are already visible.
                showWarning(str(exc))
            else:
                showWarning(f"Setup failed:\n\n{type(exc).__name__}: {exc}")

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def cancel_setup_download() -> None:
        ev = op_state.get("cancel")
        if ev is not None:
            ev.set()
            progress_lbl.setText("Cancelling…")

    def pull_missing(name: str) -> None:
        """Fix-it button on the embed row: download the model it points
        at."""
        if not name or op_state["active"]:
            return
        edit = pull_input.lineEdit()
        if edit is not None:
            edit.setText(name)
        start_pull()

    def delete_selected() -> None:
        name = get_selected_model()
        if not name:
            return
        cfg = _pkg().get_config()
        from . import embeddings

        used_by_search = (
            embeddings.provider_name(cfg) == "ollama"
            and embeddings.embedding_model(cfg) == name
        )
        warn = (
            f"\n\n⚠ {name} is currently used by semantic search — "
            "that will stop working until you pick another model."
            if used_by_search
            else ""
        )
        ok = QMessageBox.question(
            dlg,
            "Delete model",
            f"Delete '{name}' from Ollama?\n\nThis frees disk space but you'll "
            f"need to pull it again to use it.{warn}",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        op_state["kind"] = "delete"
        set_busy(True)
        progress.setRange(0, 0)
        progress_lbl.setText(f"Deleting {name}…")

        def do() -> None:
            _pkg().client().delete(name)

        def on_done(_: Any) -> None:
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            tooltip(f"Klaus: deleted {name}")
            refresh()

        def on_fail(exc: Exception) -> None:
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            showWarning(f"Could not delete {name}:\n\n{type(exc).__name__}: {exc}")

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def start_pull() -> None:
        edit = pull_input.lineEdit()
        typed = (edit.text() if edit else "").strip()
        idx = pull_input.currentIndex()
        # Only trust currentData while the visible text still matches the
        # selected preset — after the user edits the line, currentIndex
        # goes stale and would silently pull the wrong model.
        if idx >= 0 and typed == pull_input.itemText(idx).strip():
            name = str(pull_input.currentData() or typed)
        else:
            name = typed
        name = name.strip()
        if not name:
            return
        op_state["kind"] = "pull"
        set_busy(True)
        progress.setValue(0)
        progress_lbl.setText(f"Starting pull of {name}…")

        def on_event(ev: dict) -> None:
            label, pct = _format_pull_event(ev)

            def apply() -> None:
                progress_lbl.setText(label)
                if pct:
                    progress.setValue(pct)

            mw.taskman.run_on_main(apply)

        def do() -> None:
            _pkg().client().pull(name, on_event=on_event)

        def on_done(_: Any) -> None:
            progress.setValue(100)
            progress_lbl.setText(f"Pulled {name} ✓")
            set_busy(False)
            op_state["kind"] = ""
            tooltip(f"Klaus: {name} ready")
            refresh()

        def on_fail(exc: Exception) -> None:
            set_busy(False)
            op_state["kind"] = ""
            showWarning(f"Could not pull {name}:\n\n{type(exc).__name__}: {exc}")

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    # ----- Semantic search handlers ----------------------------------------

    def _embed_cfg_key(provider: str) -> str:
        return f"embedding_api_key_{provider}"

    def sync_embed_widgets(provider_override: str | None = None) -> None:
        from . import curation, embeddings

        # Refreshes (model pulls, connection checks) must never overwrite
        # unsaved edits with stored values. A provider switch passes
        # provider_override and is exempt — it IS the edit being applied,
        # and it needs the model/key fields reloaded for the new provider
        # without anything being written to disk.
        if provider_override is None and ui_state["dirty"]:
            return
        ui_state["syncing"] = True
        try:
            cfg = _pkg().get_config()
            provider = provider_override or embeddings.provider_name(cfg)
            ui_state["shown_provider"] = provider
            idx = max(0, embed_provider_combo.findData(provider))
            embed_provider_combo.setCurrentIndex(idx)
            # Local provider → offer every installed model (the library is
            # one flat list, nothing else pulls a non-embedding model into
            # it); cloud → free text.
            embed_model_combo.clear()
            if provider == "ollama":
                for name in ui_state["models"]:
                    embed_model_combo.addItem(name, name)
            configured_model = str(cfg.get("embedding_model") or "")
            if provider_override is not None:
                # Moving the widgets to a different provider than the one
                # stored: the stored model name belongs to the old one.
                configured_model = ""
            if provider == "ollama":
                st = curation.index_stats()
                indexed_model = st["model"] if st["exists"] else ""
                resolved = _resolve_ollama_model(
                    configured_model,
                    ui_state["models"],
                    indexed_model,
                    embeddings.DEFAULT_MODELS["ollama"],
                )
                if (
                    resolved != configured_model
                    and ui_state["models"]
                    and provider_override is None
                ):
                    # Heal the config now, not just the widget — an empty
                    # field must not silently mean DEFAULT_MODELS['ollama']
                    # everywhere else this config is read (index_signature,
                    # the real indexing pipeline in curation.py).
                    #
                    # Only persist when we actually enumerated the installed
                    # models. An empty list means we could not ask Ollama
                    # (server down, or the user just switched the provider
                    # combo back to ollama while it is down), and the
                    # resolver then falls through to the hardcoded default.
                    # Writing THAT to disk would permanently orphan an index
                    # built with another model — the exact failure this
                    # resolver exists to prevent, made durable. Display it,
                    # never store it.
                    cfg["embedding_model"] = resolved
                    _pkg().write_config(cfg)
                embed_model_combo.setEditText(resolved)
            else:
                embed_model_combo.setEditText(configured_model)
            edit = embed_model_combo.lineEdit()
            if edit is not None:
                edit.setPlaceholderText(
                    f"default: {embeddings.DEFAULT_MODELS[provider]}"
                )
            embed_key_edit.setText(str(cfg.get(_embed_cfg_key(provider)) or ""))
            embed_key_edit.setPlaceholderText(_EMBED_KEY_PLACEHOLDERS.get(provider, ""))
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

    def _embed_fix_kind() -> str:
        """What embed_fix_btn should do right now: 'key' when the selected
        cloud provider has no API key configured, 'model' when the local
        embed model named in config isn't installed, '' when neither. The
        single source of truth for both the row warning and the button
        dispatcher below — they must never compute this separately or the
        two could disagree about what the button is currently offering."""
        from . import embeddings

        cfg = _pkg().get_config()
        sig = embeddings.index_signature(cfg)
        provider = embed_provider_combo.currentData() or "ollama"
        is_cloud = provider != "ollama"
        if is_cloud and not str(cfg.get(_embed_cfg_key(provider)) or "").strip():
            return "key"
        if not is_cloud and sig[1] and sig[1] not in ui_state["models"]:
            return "model"
        return ""

    def update_embed_status() -> None:
        from . import curation, embeddings

        cfg = _pkg().get_config()
        sig = embeddings.index_signature(cfg)
        provider = embed_provider_combo.currentData() or "ollama"
        is_cloud = provider != "ollama"
        key_row.klaus_hidden = not is_cloud
        _apply_search(search_edit.text())
        st = curation.index_stats()
        if not st["exists"]:
            txt = "No card index yet — click “Index cards now” to enable semantic search."
        else:
            txt = f"{st['count']:,} cards indexed · updated {_fmt_ago(st['updated_at'])}"
            if (st["provider"], st["model"]) != sig:
                txt += " · settings changed: next indexing rebuilds from scratch"
        embed_status.setText(txt)

        # embed_fix_btn's role (open a key page vs. pull a model) switches
        # with `kind`. on_embed_fix_clicked() reads ui_state["embed_fix_kind"]
        # rather than being re-wired here, so there is exactly one .connect()
        # for this button for the life of the dialog (see the connect block).
        kind = _embed_fix_kind()
        ui_state["embed_fix_kind"] = kind
        if kind == "key":
            embed_fix_btn.setText("Get key")
        elif kind == "model":
            embed_fix_btn.setText("Pull it")
        embed_fix_btn.setVisible(bool(kind))

    def on_embed_fix_clicked() -> None:
        """Sole handler for embed_fix_btn.clicked (connected once, at the
        bottom). Dispatches on the state update_embed_status() last
        computed instead of the button being rewired per state change —
        Qt connects accumulate, so a naive second .connect() on a state
        change would leave both the old and new handler firing."""
        kind = ui_state.get("embed_fix_kind", "")
        if kind == "key":
            provider = str(embed_provider_combo.currentData() or "voyage")
            openLink(_EMBED_KEY_URLS.get(provider, _EMBED_KEY_URLS["voyage"]))
        elif kind == "model":
            pull_missing(embed_model_combo.currentText().strip())

    def save_embed() -> None:
        if ui_state["syncing"]:
            return
        from . import embeddings

        cfg = _pkg().get_config()
        provider = str(embed_provider_combo.currentData() or "ollama")
        prev = embeddings.provider_name(cfg)
        cfg["embedding_provider"] = provider
        # The widgets were repopulated for `provider` the moment it was
        # picked (on_provider_changed), so by Save time their contents
        # already belong to it — take them. Comparing against the STORED
        # provider here (as this did under auto-save, when the widgets
        # still held the old provider's model at signal time) would now
        # discard a model the user deliberately typed for the new one.
        if ui_state.get("shown_provider", provider) == provider:
            cfg["embedding_model"] = embed_model_combo.currentText().strip()
        else:
            cfg["embedding_model"] = ""
        if provider != "ollama":
            cfg[_embed_cfg_key(provider)] = embed_key_edit.text().strip()
        _pkg().write_config(cfg)
        if provider != prev:
            sync_embed_widgets()  # reload model/key fields for the new provider
        else:
            update_embed_status()
        rebuild_library_list()  # the "used by: search" badge may have moved

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
            if n and askUser(
                f"Apply this sensitivity to "
                f"{'the ' + str(n) + ' PDFs' if n > 1 else 'the one PDF'} "
                "with their own setting too?\n\n"
                "Their individual sensitivities will be cleared so they "
                "follow this default. You can still tune any single PDF "
                "afterwards in the Library.",
                parent=dlg,
            ):
                retention.clear_threshold_overrides()
                try:
                    from . import tag_sync

                    tag_sync.sync_after_clear_overrides(dlg, names)
                except Exception as e:
                    print(f"[klausmate] retagging cleared-override PDFs failed: {e}")
        except Exception as e:
            print(f"[klausmate] applying sensitivity to tuned PDFs failed: {e}")
        # An open Library window shows retention/cards computed at the
        # old numbers — push the change there immediately rather than
        # waiting for a reopen (K-052 rework: looked like it did nothing).
        try:
            from . import pdf_drive

            pdf_drive.refresh_open_library()
        except Exception as e:
            print(f"[klausmate] library refresh after sensitivity save failed: {e}")

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

    def _pull_embedder_then_index(model: str) -> None:
        op_state["kind"] = "pull"
        set_busy(True)
        progress.setRange(0, 100)
        progress.setValue(0)
        progress_lbl.setText(f"Downloading embedding model {model}…")

        def on_event(ev: dict) -> None:
            label, pct = _format_pull_event(ev)

            def apply() -> None:
                if not _dlg_alive():
                    return
                progress_lbl.setText(label)
                if pct:
                    progress.setValue(pct)

            mw.taskman.run_on_main(apply)

        def do() -> None:
            _pkg().client().pull(model, on_event=on_event)

        def on_done(_: Any) -> None:
            if not _dlg_alive():
                return
            set_busy(False)
            op_state["kind"] = ""
            refresh()
            _run_index()

        def on_fail(exc: Exception) -> None:
            if _dlg_alive():
                set_busy(False)
                op_state["kind"] = ""
            showWarning(
                f"Could not pull {model}:\n\n{type(exc).__name__}: {exc}"
            )

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def start_index() -> None:
        if op_state["active"]:
            return
        from . import curation, embeddings

        cfg = _pkg().get_config()
        sig = embeddings.index_signature(cfg)
        provider, model = sig
        if provider != "ollama" and not str(
            cfg.get(_embed_cfg_key(provider)) or ""
        ).strip():
            showWarning(
                f"Enter your {provider} API key above before indexing."
            )
            return
        st = curation.index_stats()
        if st["exists"] and (st["provider"], st["model"]) != sig:
            # Destructive: the stored vectors don't match the model about
            # to run, so a rebuild-from-scratch is one confirm away rather
            # than one click away. A matching signature (fresh build or
            # incremental update) skips this prompt entirely.
            note_count = mw.col.note_count() if mw.col else 0
            ok = QMessageBox.question(
                dlg,
                "Re-index from scratch?",
                f"Re-index all {note_count:,} cards from scratch? The "
                f"existing index was built with {st['model']} and the "
                f"current setting is {model}.",
            )
            if ok != QMessageBox.StandardButton.Yes:
                return
        if provider == "ollama" and model not in ui_state["models"]:
            _pull_embedder_then_index(model)
        else:
            _run_index()

    def confirm_close() -> None:
        # Checked BEFORE the running-operation branches: several of those
        # accept() straight away, and unsaved edits must not slip out
        # through one of them unmentioned.
        if ui_state["dirty"]:
            ok = QMessageBox.question(
                dlg,
                "Discard changes?",
                "You have unsaved preference changes.\n\n"
                "Close without saving them?",
            )
            if ok != QMessageBox.StandardButton.Yes:
                return
            clear_dirty()
        if op_state["active"]:
            if op_state["kind"] == "index":
                ok = QMessageBox.question(
                    dlg,
                    "Stop indexing?",
                    "Card indexing is still running.\n\n"
                    "Stop it and close? Progress is saved — indexing resumes "
                    "where it stopped next time.",
                )
                if ok != QMessageBox.StandardButton.Yes:
                    return
                ev = op_state.get("cancel")
                if ev is not None:
                    ev.set()
                dlg.accept()
                return
            if op_state["kind"] == "setup":
                # Unlike pulls, a runtime download must not keep streaming
                # invisibly after the dialog goes away — cancel it.
                ok = QMessageBox.question(
                    dlg,
                    "Cancel setup?",
                    "The local AI setup is still downloading.\n\n"
                    "Cancel it and close? (Nothing partial is kept.)",
                )
                if ok != QMessageBox.StandardButton.Yes:
                    return
                cancel_setup_download()
                dlg.accept()
                return
            label = "operation"
            if op_state["kind"] == "pull":
                label = "model pull"
            elif op_state["kind"] == "install":
                label = "Ollama install"
            ok = QMessageBox.question(
                dlg,
                "Operation in progress",
                f"A {label} is running in the background.\n\n"
                "Close anyway? (It will continue.)",
            )
            if ok != QMessageBox.StandardButton.Yes:
                return
        dlg.accept()

    def save_general() -> None:
        cfg = _pkg().get_config()
        cfg["image_crop_enabled"] = bool(image_crop_cb.isChecked())
        cfg["runtime_auto_setup"] = bool(runtime_auto_cb.isChecked())
        cfg["pdf_renderer"] = "pdfjs" if pdfjs_cb.isChecked() else "native"
        spec = _bg_state["spec"]
        cfg["background_mode"] = spec["mode"]
        cfg["background_color"] = spec["color"]
        cfg["background_image"] = spec["image"]
        cfg["background_fit"] = spec["fit"]
        cfg["background_blur"] = int(spec["blur"])
        cfg["color_theme"] = _accent_state["name"]
        cfg["color_theme_custom"] = _accent_state["custom"]
        _pkg().write_config(cfg)

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

    def on_provider_changed(_idx: int) -> None:
        """Reload the model list and key field for the newly picked
        provider WITHOUT writing config. The provider is passed through
        explicitly because config still holds the old one until Save."""
        if ui_state["syncing"]:
            return
        mark_dirty()
        sync_embed_widgets(
            provider_override=str(embed_provider_combo.currentData() or "ollama")
        )

    def _bg_preview_cfg() -> dict:
        """The PENDING background spec in config shape, for background's
        preview override — the same five keys save_general() writes."""
        spec = _bg_state["spec"]
        return {
            "background_mode": spec["mode"],
            "background_color": spec["color"],
            "background_image": spec["image"],
            "background_fit": spec["fit"],
            "background_blur": int(spec["blur"]),
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
            # The sidebar star is a baked pixmap stroked in blue_accent;
            # re-render it or it keeps the old accent until reopen.
            _new_logo = _logo_pixmap(24)
            if _new_logo is not None:
                logo_lbl.setPixmap(_new_logo)
        except Exception as _exc:
            print(f"[klausmate] accent apply failed: {_exc}")
        try:
            from . import top_bar as _top_bar

            _top_bar.refresh()
        except Exception as _exc:
            print(f"[klausmate] background refresh failed: {_exc}")

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

        Fixed on the move: it used to call client().health() with the
        client's default 30-second timeout, synchronously on this same
        main thread — a packet-dropping endpoint froze all of Anki for
        30s. ollama_reachable uses a short timeout for exactly this
        reason (see its docstring). It's also now provider-aware: a
        cloud-provider user gets a key-presence check, not an Ollama
        probe — Ollama is optional and shouldn't be implied otherwise.
        """
        from . import embeddings

        cfg = _pkg().get_config()
        provider = embeddings.provider_name(cfg)
        if provider != "ollama":
            provider_label = "Voyage" if provider == "voyage" else "OpenAI"
            key = str(cfg.get(_embed_cfg_key(provider)) or "").strip()
            if key:
                showInfo(f"{provider_label} API key is set.", parent=dlg)
            else:
                showWarning(
                    f"No {provider_label} API key is set. Add one above.",
                    parent=dlg,
                )
            return
        ep = endpoint_url()
        if ollama_reachable(ep):
            showInfo("Connected to Ollama.", parent=dlg)
        else:
            showWarning(
                f"Could not reach Ollama at {ep}.\n"
                "Install/start it from https://ollama.com/download",
                parent=dlg,
            )

    auto_setup_btn.clicked.connect(start_auto_setup)
    cancel_btn.clicked.connect(cancel_setup_download)
    dlg.confirm_close_cb = confirm_close  # Esc and title-bar ✕ too
    download_btn.clicked.connect(lambda: openLink(OLLAMA_DOWNLOAD_URL))
    check_conn_btn.clicked.connect(refresh)
    test_conn_btn.clicked.connect(test_connection)
    delete_btn.clicked.connect(delete_selected)
    refresh_btn.clicked.connect(refresh)
    pull_btn.clicked.connect(start_pull)
    close_btn.clicked.connect(confirm_close)
    embed_fix_btn.clicked.connect(on_embed_fix_clicked)
    # Preference widgets only MARK DIRTY; save_all() (Save button) is the
    # single writer. textEdited rather than editingFinished so the Save
    # button lights up as you type, not only on focus-out.
    embed_provider_combo.currentIndexChanged.connect(on_provider_changed)
    _embed_model_edit_widget = embed_model_combo.lineEdit()
    if _embed_model_edit_widget is not None:
        _embed_model_edit_widget.textEdited.connect(lambda _t: mark_dirty())
    embed_model_combo.currentIndexChanged.connect(lambda _i: mark_dirty())
    embed_key_edit.textEdited.connect(lambda _t: mark_dirty())
    threshold_slider.valueChanged.connect(_update_threshold_label)
    threshold_slider.sliderReleased.connect(mark_dirty)
    index_btn.clicked.connect(start_index)
    image_crop_cb.toggled.connect(lambda _checked: mark_dirty())
    runtime_auto_cb.toggled.connect(lambda _checked: mark_dirty())
    pdfjs_cb.toggled.connect(lambda _checked: mark_dirty())
    bg_mode_combo.currentIndexChanged.connect(on_bg_mode_changed)
    bg_fit_combo.currentIndexChanged.connect(on_bg_fit_changed)
    bg_blur_slider.valueChanged.connect(on_bg_blur_changed)
    bg_colour_btn.clicked.connect(pick_bg_colour)
    bg_image_btn.clicked.connect(pick_bg_image)
    save_btn.clicked.connect(save_all)
    library_change_btn.clicked.connect(change_library_folder)
    _preview_timer.timeout.connect(apply_appearance_live)
    # finished fires on EVERY close path (Save, Cancel, Esc, title-bar ✕),
    # so it is the one place an unsaved preview can be guaranteed not to
    # outlive the dialog. No-op unless a preview is actually armed.
    dlg.finished.connect(lambda _result: revert_appearance_preview())

    rebuild_install_method_buttons()
    refresh()
    if setup:
        if stack.currentIndex() == 0:
            # One-click path: go straight to the provisioning confirm.
            QTimer.singleShot(0, start_auto_setup)
        else:
            # Server already fine — jump to getting a first model.
            QTimer.singleShot(0, maybe_auto_pull_starter)
    # open(), NEVER exec() (live crash, 2026-08-26): on macOS 26.5 +
    # Qt 6.11, showing this dialog application-modal via exec()
    # segfaulted in its first backing-store flush
    # (QPaintDevice::devicePixelRatio on null inside QBackingStore::flush)
    # SEVEN times across THREE dispatch shapes — webchannel, a Tools-menu
    # QAction, and a clean QTimer slot — so the app-modal nested loop
    # (Qt runs it through AppKit's NSApp modal-session machinery, which
    # races Tahoe's window-appear animation) is the trigger, not how the
    # dialog was opened. Window-modal open() takes the normal window
    # path, like Anki's own dialogs and our QMenus, none of which crash.
    # Nothing here consumed exec()'s return value; every close path is
    # already callback-driven (confirm_close / save_all).
    dlg.open()

