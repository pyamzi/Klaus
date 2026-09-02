"""KlausMate Preferences dialog: provision the local AI runtime, pull a
local embedding model, configure semantic search, and hold the two
maintenance action (Check Connection).

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

# OCR-model presets offered in the Assistant page's Pull dropdown — the
# vision-capable counterpart to _EMBED_PRESETS above. Klaus's own OCR
# path (page_ocr.py) calls Ollama's /api/generate with images; these are
# just the two starter models worth surfacing, not an exhaustive list.
_OCR_PRESETS = [
    ("glm-ocr", "GLM-OCR — multimodal OCR for complex documents · ~2.5 GB"),
    ("deepseek-ocr", "DeepSeek-OCR — token-efficient OCR · ~3 GB"),
]

# Display labels for the Local Models list's Type column (rebuild_library_list).
_MODEL_TYPE_LABELS = {"embedding": "Embedding", "ocr": "OCR", "chat": "Chat"}


def classify_model(show: dict) -> str:
    """Pure: which of "embedding" / "ocr" / "chat" a /api/show payload
    describes, by Ollama's own reported capabilities list.

    "embedding" if "embedding" is among them; "ocr" if "vision" is
    (Klaus reads a scanned/no-text-layer PDF page through such a model);
    otherwise, or on anything malformed (missing key, non-dict input, a
    capabilities value that isn't even a list), "chat" — called once per
    installed model, so one odd response must never raise and blank the
    whole Local Models list.
    """
    caps = show.get("capabilities") if isinstance(show, dict) else None
    if not isinstance(caps, (list, tuple, set)):
        return "chat"
    if "embedding" in caps:
        return "embedding"
    if "vision" in caps:
        return "ocr"
    return "chat"


def embedding_candidates(models: list, model_types: dict) -> list:
    """Pure: the subset of `models` classified "embedding" by
    `model_types` (classify_model's cache shape, name -> "embedding" /
    "ocr" / "chat").

    Review K-194 Critical #1: sync_embed_widgets used to filter the
    DISPLAYED dropdown list this way inline, but still handed the
    UNFILTERED inventory to _resolve_ollama_model and to the
    write-to-disk guard right below it — so with exactly one installed
    model that happened to be OCR-typed, the resolver's "the one model
    installed" branch returned it, and it got silently persisted as
    embedding_model. Both call sites now build this list ONCE and use
    it in both places, so a non-embedding model can never reach either
    the dropdown OR the auto-heal / write path. A name absent from
    model_types (e.g. mid-classification, see _classify_models_async)
    is excluded, not assumed embedding — the same conservative default
    classify_model itself falls back to for a failed /api/show.
    """
    return [n for n in models if model_types.get(n) == "embedding"]


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
    'Index Now' would discard it (K-039). Dialog-level resolution
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

    download_btn = QPushButton("Open Download Page")
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
        "3. Click Check Connection, then download a model on the next screen."
    )
    install_steps.setWordWrap(True)
    install_steps.setStyleSheet(_MUTED)
    install_layout.addWidget(install_steps)

    install_btn_row = QHBoxLayout()
    check_conn_btn = QPushButton("Check Connection")
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
        "Finds cards by meaning, not just keywords — powers the "
        "Library's per-PDF card matching and retention scores. Needs a "
        "Voyage or OpenAI key (both have free tiers) or a local Ollama "
        "model from the Local Models page.",
    )

    embed_provider_combo = QComboBox()
    embed_provider_combo.addItem("Voyage API (Default)", "voyage")
    embed_provider_combo.addItem("OpenAI API", "openai")
    embed_provider_combo.addItem("Local Ollama (Private, Free)", "ollama")
    embed_provider_combo.setMinimumWidth(220)
    embed_fix_btn = QPushButton("Download")
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
    index_btn = QPushButton("Index Now")
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
        "Ollama embedding models installed on this machine — download new "
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
    pull_btn = QPushButton("Download")
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
    test_conn_btn = QPushButton("Check Connection")
    test_conn_btn.setObjectName("SecondaryButton")
    _row(
        general_layout,
        "Connection",
        "Check that the embedding provider is reachable.",
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
    runtime_auto_cb.setChecked(bool(_general_cfg.get("runtime_auto_setup", True)))
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
    # ---- Assistant --------------------------------------------------
    # Klaus is not itself the assistant: Claude Code is. This page
    # points at the local `claude` binary agent_host.py (Task 2)
    # discovers, and at the local OCR model that reads a lecture page's
    # slide text and images. The old Assistant panel — its promised
    # future features and its own provider-key / hosted-token picker —
    # is gone; see AGENTS.md's "What used to be here".
    assistant_layout = _page(
        "Assistant",
        "Assistant",
        "Claude Code is the engine: install it, run `claude` once to "
        "log in, and Klaus finds it. The page you are viewing reaches "
        "it as OCR text and image.",
    )

    ocr_enabled_cb = Md3Switch()  # MD3 switch (K-material3), not a checkbox
    _row(
        assistant_layout,
        "OCR",
        "Read every lecture page you view through a local vision model, "
        "so a scanned slide or a diagram reaches the Assistant as text. "
        "Off, it still gets the PDF's own text layer — which is empty "
        "for a scanned page.",
        ocr_enabled_cb,
    )

    ocr_model_combo = QComboBox()
    ocr_pull_btn = QPushButton("Pull")
    ocr_model_ctl = QHBoxLayout()
    ocr_model_ctl.setContentsMargins(0, 0, 0, 0)
    ocr_model_ctl.addWidget(ocr_model_combo, 1)
    ocr_model_ctl.addWidget(ocr_pull_btn)
    _row(
        assistant_layout,
        "OCR model",
        "Which local vision model reads the page. Pull downloads the "
        "selected one through Ollama, the same way the embedding "
        "models on the Semantic Search page do.",
        ocr_model_ctl,
    )

    def _fill_ocr_model_combo() -> None:
        """Installed OCR-typed models (from _classify_models_async's
        off-thread /api/show pass) plus the presets, so an unpulled one
        can still be picked and then downloaded with the Pull button
        beside it. Same never-clobber-an-unsaved-pick guard as
        sync_threshold_widget / sync_embed_widgets — a Refresh click
        elsewhere must not silently discard a pick made on this page
        before Save.

        Intersected against ui_state["models"] (the current inventory),
        not just filtered by cached type: model_types can briefly lag
        behind models (classification is async and/or a model was just
        deleted), and a stale "ocr" entry for a name no longer installed
        must not resurrect it in the picker."""
        if ui_state["dirty"]:
            return
        ui_state["syncing"] = True
        try:
            cfg = _pkg().get_config()
            want = str(cfg.get("ocr_model") or "glm-ocr")
            current = set(ui_state["models"])
            installed = sorted(
                name for name, kind in ui_state["model_types"].items()
                if kind == "ocr" and name in current
            )
            ocr_model_combo.clear()
            for name in installed:
                ocr_model_combo.addItem(name, name)
            installed_set = set(installed)
            for name, desc in _OCR_PRESETS:
                if name not in installed_set:
                    ocr_model_combo.addItem(f"{name}   ({desc})", name)
            idx = ocr_model_combo.findData(want)
            if idx < 0:
                # Stored choice is neither installed nor a known preset —
                # keep it rather than silently swapping in glm-ocr.
                ocr_model_combo.addItem(want, want)
                idx = ocr_model_combo.count() - 1
            ocr_model_combo.setCurrentIndex(idx)
        finally:
            ui_state["syncing"] = False

    def _pull_ocr_selected() -> None:
        """Reuses start_pull()'s existing progress bar / refresh() cycle
        instead of a second pull implementation — same technique as the
        embed row's own pull_missing(name) fix-it button."""
        if op_state["active"]:
            return
        idx = ocr_model_combo.currentIndex()
        name = str(ocr_model_combo.itemData(idx) or "") if idx >= 0 else ""
        if not name:
            return
        edit = pull_input.lineEdit()
        if edit is not None:
            edit.setText(name)
        start_pull()

    claude_binary_lbl = QLabel()
    claude_binary_lbl.setWordWrap(True)
    claude_override_btn = QPushButton("Override…")
    claude_override_btn.setObjectName("SecondaryButton")
    _row(
        assistant_layout, "Claude Code binary", claude_binary_lbl, claude_override_btn
    )

    # Pending (possibly unsaved) claude_binary value. Empty means
    # "auto-detect" — the same override-or-search contract
    # agent_host.find_claude itself takes.
    _assistant_state: dict[str, str] = {"claude_binary": ""}

    def _resolve_claude_binary(explicit: str) -> str:
        """Read-only detection via Task 2's agent_host — imported lazily
        because this dialog can open before that module exists (a fresh
        checkout mid-build) or on a machine missing it entirely.
        Degrades to "" (rendered as "not found"), never raises."""
        try:
            from . import agent_host
        except Exception as exc:
            print(f"[klausmate] agent_host unavailable: {exc}")
            return ""
        try:
            # Cached for the profile session (spec §4.1): step 3 of the
            # search spawns the user's login shell with a 3 s timeout,
            # and this runs on the main thread every time Preferences
            # opens or the label refreshes.
            return agent_host.find_claude_cached(explicit) or ""
        except Exception as exc:
            print(f"[klausmate] agent_host.find_claude failed: {exc}")
            return ""

    def _refresh_claude_binary_label() -> None:
        found = _resolve_claude_binary(_assistant_state["claude_binary"])
        claude_binary_lbl.setText(found or "not found")

    def _pick_claude_binary() -> None:
        from aqt.qt import QFileDialog

        # An INSTANCE + open() (K-125), never the static
        # getOpenFileName()/getExistingDirectory() convenience helpers —
        # those exec() their own nested loop.
        dialog = QFileDialog(dlg, "Locate the claude binary")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)

        def _on_selected(path: str) -> None:
            if not path:
                return
            _assistant_state["claude_binary"] = path
            try:
                from . import agent_host

                # The profile-session cache is keyed on the override, so
                # a new pick resolves fresh on the key alone. Clearing
                # it as well is what lets a user who INSTALLED claude
                # since the dialog opened get a real answer without
                # restarting Anki: a miss is cached now, so the empty
                # override's stored "not found" would otherwise stand.
                agent_host.clear_binary_cache()
            except Exception as exc:
                print(f"[klausmate] agent_host cache clear failed: {exc}")
            _refresh_claude_binary_label()
            mark_dirty()

        dialog.fileSelected.connect(_on_selected)
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    assistant_model_edit = QLineEdit()
    assistant_model_edit.setMinimumWidth(220)
    assistant_model_edit.setPlaceholderText("default")
    _row(
        assistant_layout,
        "Model",
        "Which Claude model the assistant runs. Leave blank for Claude "
        "Code's own default.",
        assistant_model_edit,
    )

    assistant_reopen_cb = Md3Switch()  # MD3 switch (K-material3), not a checkbox
    _row(
        assistant_layout,
        "Reopen on start",
        "Reopen the Assistant dock where you left it the next time Anki "
        "starts.",
        assistant_reopen_cb,
    )

    def _clear_sessions_confirmed() -> None:
        """The destructive back half, run only from the confirm's Yes.
        assistant_sessions is Task 7's module, imported lazily for the
        same reason agent_host is above."""
        try:
            from . import USER_FILES, assistant_sessions
        except Exception as exc:
            print(f"[klausmate] assistant_sessions unavailable: {exc}")
            return
        try:
            assistant_sessions.clear_all(USER_FILES)
        except Exception as exc:
            print(f"[klausmate] assistant_sessions.clear_all failed: {exc}")
            return
        tooltip("Klaus: assistant sessions cleared", parent=dlg)

    def clear_assistant_sessions() -> None:
        # Hand-built QMessageBox + open() + finished (K-125), same
        # pattern as pdf_drive._delete_pdf — never the blocking
        # QMessageBox.question() static (its internal exec() is the
        # K-114 segfault class).
        msg = QMessageBox(dlg)
        msg.setWindowTitle("Clear Sessions")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            "Clear every saved Assistant conversation?\n\n"
            "This removes the session history Claude Code keeps per "
            "PDF. Notes, PDFs, and highlights are never touched."
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
            print(f"[klausmate] clear-sessions dialog theme failed: {exc}")

        def _on_answered(_r: int) -> None:
            clicked = msg.clickedButton()
            confirmed = (
                clicked is not None
                and msg.standardButton(clicked) == QMessageBox.StandardButton.Yes
            )
            msg.deleteLater()
            if confirmed:
                _clear_sessions_confirmed()

        msg.finished.connect(_on_answered)
        msg.open()

    clear_sessions_btn = QPushButton("Clear Sessions")
    clear_sessions_btn.setObjectName("SecondaryButton")
    _row(
        assistant_layout,
        "Sessions",
        "Deletes the saved Assistant conversation history for every "
        "PDF. Notes, PDFs, and highlights are never touched.",
        clear_sessions_btn,
    )

    def load_assistant() -> None:
        cfg = _pkg().get_config()
        ocr_enabled_cb.setChecked(bool(cfg.get("ocr_enabled", True)))
        _assistant_state["claude_binary"] = str(cfg.get("claude_binary") or "")
        _refresh_claude_binary_label()
        assistant_model_edit.setText(str(cfg.get("assistant_model") or ""))
        assistant_reopen_cb.setChecked(bool(cfg.get("assistant_reopen", False)))
        # ocr_model_combo itself is (re)populated by refresh() /
        # _fill_ocr_model_combo — no models are known yet this early in
        # dialog construction, exactly like embed_model_combo/lib_lst.

    def save_assistant() -> None:
        cfg = _pkg().get_config()
        cfg["ocr_enabled"] = bool(ocr_enabled_cb.isChecked())
        idx = ocr_model_combo.currentIndex()
        picked = str(ocr_model_combo.itemData(idx) or "") if idx >= 0 else ""
        cfg["ocr_model"] = picked or "glm-ocr"
        cfg["claude_binary"] = _assistant_state["claude_binary"]
        cfg["assistant_model"] = assistant_model_edit.text().strip()
        cfg["assistant_reopen"] = bool(assistant_reopen_cb.isChecked())
        # No Preferences row for these two — they're dock state, set by
        # dragging the Assistant dock and by opening/closing it.
        # Round-tripped so this save never wipes them back to defaults.
        # int() is guarded because meta.json is hand-editable and a
        # non-numeric width must not break the Save button for every
        # other setting on the page (parked T8 finding).
        try:
            cfg["assistant_dock_width"] = int(cfg.get("assistant_dock_width", 420) or 420)
        except (TypeError, ValueError):
            cfg["assistant_dock_width"] = 420
        cfg["assistant_dock_open"] = bool(cfg.get("assistant_dock_open", False))
        _pkg().write_config(cfg)

    ocr_enabled_cb.toggled.connect(lambda _c: mark_dirty())
    ocr_model_combo.currentIndexChanged.connect(lambda _i: mark_dirty())
    ocr_pull_btn.clicked.connect(_pull_ocr_selected)
    claude_override_btn.clicked.connect(_pick_claude_binary)
    assistant_model_edit.textEdited.connect(lambda _t: mark_dirty())
    assistant_reopen_cb.toggled.connect(lambda _c: mark_dirty())
    clear_sessions_btn.clicked.connect(clear_assistant_sessions)
    load_assistant()

    _finish_nav("General", "Appearance", "Assistant", "Semantic Search",
                "Local Models")

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
    cancel_btn = QPushButton("Cancel Download")
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
        # name -> "embedding"/"ocr"/"chat", from _classify_models_async's
        # off-thread /api/show pass — classify_model over each installed
        # model, fetched once per refresh and cached here for the
        # dialog's life.
        "model_types": {},
        # Bumped by every refresh() call; a completed classification
        # whose generation no longer matches is a stale result from a
        # superseded refresh and is dropped rather than applied.
        "classify_gen": 0,
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
            ocr_model_combo, ocr_pull_btn,
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
        # model_types is intentionally left as-is here (not reset) — the
        # widgets below read whatever classification is already cached,
        # so a model this dialog already knows about doesn't flash to
        # "Chat" every refresh; _classify_models_async re-syncs them
        # again once it lands a fresh pass for the CURRENT models list.
        sync_embed_widgets()
        sync_threshold_widget()
        rebuild_library_list()
        _fill_ocr_model_combo()
        _classify_models_async(models)

    def _classify_models_async(models: list[str]) -> None:
        """Off-main-thread /api/show pass (K-194 review, Important #1).

        Classifying N installed models is 1..N sequential HTTP calls,
        each carrying OllamaClient's own 30s timeout if one hangs —
        running that inline in refresh() could freeze the whole
        Preferences window for minutes against a large local library.
        This runs in a QueryOp exactly like every other network op in
        this dialog (start_pull, delete_selected, start_install);
        model_types is written and the three widgets that read it are
        re-synced back on the MAIN thread in on_done, never from the
        worker. A failed /api/show for one model still tolerates to
        "chat" — same contract refresh() used to enforce inline, just no
        longer holding up the caller.

        ui_state["classify_gen"] guards against a stale result: if
        Refresh is clicked again (or a pull/delete completes) before
        this pass returns, that newer refresh() bumps the generation,
        and this pass's own on_done sees the mismatch and drops its
        result instead of overwriting fresher data with stale data.
        """
        if not models:
            # Nothing to classify (no models, or Ollama unreachable) —
            # and nothing stale should survive either, so a session that
            # goes from "some models" to "none" doesn't leave phantom
            # types behind for names that no longer exist.
            ui_state["model_types"] = {}
            return
        gen = ui_state["classify_gen"] = ui_state["classify_gen"] + 1

        def do() -> dict[str, str]:
            types: dict[str, str] = {}
            for name in models:
                try:
                    show = _pkg().client()._post("/api/show", {"model": name})
                except Exception:
                    show = {}
                types[name] = classify_model(show)
            return types

        def on_done(types: dict[str, str]) -> None:
            if gen != ui_state["classify_gen"]:
                return  # superseded by a later refresh() — drop it
            ui_state["model_types"] = types
            sync_embed_widgets()
            rebuild_library_list()
            _fill_ocr_model_combo()

        def on_fail(exc: Exception) -> None:
            print(f"[klausmate] model classification failed: {exc}")

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def rebuild_library_list() -> None:
        """Inventory with a 'used by' badge and a Type column (Embedding /
        OCR / Chat, from the cached classify_model pass) — pure
        inventory, doesn't assign anything (the embed row above does
        that)."""
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
            placeholder = QListWidgetItem("(no models installed — download one below)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            lib_lst.addItem(placeholder)
            return
        for name in models:
            kind = ui_state["model_types"].get(name, "chat")
            type_label = _MODEL_TYPE_LABELS.get(kind, "Chat")
            suffix = "   ·  used by: search" if name == embed_active else ""
            item = QListWidgetItem(f"{name}   ·  {type_label}{suffix}")
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
            f"download the starter embedding model {_EMBED_PRESETS[0][0]} "
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
            f"need to download it again to use it.{warn}",
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
            progress_lbl.setText(f"Downloaded {name} ✓")
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
            # Local provider → offer every installed EMBEDDING-typed model
            # (the library can now also hold OCR/chat models, classified
            # by the /api/show pass — those don't belong in this
            # dropdown); cloud → free text. Built ONCE and used at every
            # site below — review K-194 Critical #1 was exactly this list
            # being filtered here but NOT at the resolver call or the
            # write guard, so a lone installed OCR model could get
            # silently resolved and persisted as embedding_model.
            # Filtering never blocks a stored/healed choice from being
            # DISPLAYED: the combo stays editable, so _resolve_ollama_model
            # below can still surface a configured model classification
            # missed — it just can no longer get WRITTEN from a
            # non-embedding candidate list.
            embedding_models = embedding_candidates(
                ui_state["models"], ui_state["model_types"]
            )
            embed_model_combo.clear()
            if provider == "ollama":
                for name in embedding_models:
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
                    embedding_models,
                    indexed_model,
                    embeddings.DEFAULT_MODELS["ollama"],
                )
                if (
                    resolved != configured_model
                    and embedding_models
                    and provider_override is None
                ):
                    # Heal the config now, not just the widget — an empty
                    # field must not silently mean DEFAULT_MODELS['ollama']
                    # everywhere else this config is read (index_signature,
                    # the real indexing pipeline in curation.py).
                    #
                    # Only persist when embedding_models is non-empty. It
                    # reads empty for three reasons — Ollama unreachable
                    # (server down, or the provider combo was just
                    # switched back to ollama while it's down), Ollama
                    # reachable but nothing installed classifies as
                    # "embedding" yet, or classification simply hasn't
                    # finished (_classify_models_async runs off-thread and
                    # re-syncs this widget when it lands) — and in every
                    # case the resolver falls through to the hardcoded
                    # default. Writing THAT to disk would permanently
                    # orphan an index built with another model — the
                    # exact failure this resolver exists to prevent, made
                    # durable. Display it, never store it.
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
            txt = "No card index yet — click “Index Now” to enable semantic search."
        else:
            txt = f"{st['count']:,} cards indexed · updated {_fmt_ago(st['updated_at'])}"
            if not embeddings.signature_matches(
                st["provider"], st["model"], st.get("dims", 0), sig
            ):
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
            embed_fix_btn.setText("Download")
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
        # Captured BEFORE the mutations below, off STORED config: this is
        # what every vector on disk was made with, and comparing it with
        # what config holds after the write is the only honest way to ask
        # "did the model move under the index?" (K-152).
        prev_sig = embeddings.index_signature(cfg)
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
        # K-152: a changed provider/model/width invalidates EVERY stored
        # vector, and PDF indexes rebuild only lazily — one at a time,
        # whenever you next happen to touch that PDF — so without this
        # the whole Library goes quietly stale until each is opened by
        # hand. offer_model_sweep does the comparison (via
        # embeddings.signature_matches, never a tuple ==), counts the
        # work, and asks before spending anything.
        try:
            from . import index_queue

            index_queue.offer_model_sweep(dlg, prev_sig)
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
        provider, model = sig[0], sig[1]
        if provider != "ollama" and not str(
            cfg.get(_embed_cfg_key(provider)) or ""
        ).strip():
            showWarning(
                f"Enter your {provider} API key above before indexing."
            )
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
        save_assistant()
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

    rebuild_install_method_buttons()
    refresh()
    if setup:
        if stack.currentIndex() == 0:
            # One-click path: go straight to the provisioning confirm.
            QTimer.singleShot(0, start_auto_setup)
        else:
            # Server already fine — jump to getting a first model.
            QTimer.singleShot(0, maybe_auto_pull_starter)
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

