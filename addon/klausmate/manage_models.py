"""Klausmate Preferences dialog: provision the local AI runtime, pull a
local embedding model, configure semantic search, and hold the two
maintenance actions (Test connection, Clear library tag).

Extracted verbatim from __init__.py (K-023, slice 1 of the K-006 file
split). Backs Tools > Klausmate Preferences — the single Tools-menu entry
point (K-045 folded the old 'Klaus' submenu's three items in here) — plus
the first-run one-click setup path.

Klaus is embeddings-only (K-027 dropped autocomplete and the Ask ⌘K
popover): the Semantic search and Local model library sections are one
job — where semantic search's embeddings come from (Voyage / OpenAI / a
local Ollama model). General holds the two toggles orphaned by
settings_ui.py's deletion, plus Test connection and Clear library tag
(K-045 moved both out of the Tools menu so they stay reachable — a menu
item that vanishes is worse than one click deeper).

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
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
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
    QTabWidget,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import askUser, openLink, showInfo, showWarning, tooltip

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


def manage_models_dialog(setup: bool = False) -> None:
    """Set up the local AI runtime, pull an embedding model, and configure
    semantic search.

    ``setup=True`` is the one-click first-run path: it auto-opens the
    provisioning confirm on the setup page, and after the server is up it
    chains straight into pulling the starter model when none exist.
    """
    dlg = _KlausManageDialog(mw)
    dlg.setWindowTitle("Klausmate Preferences")
    dlg.setMinimumWidth(560)
    outer = QVBoxLayout(dlg)
    outer.setSpacing(10)

    stack = QStackedWidget()
    outer.addWidget(stack)

    # ----- Page 0: Install Ollama -----------------------------------------
    install_page = QWidget()
    install_layout = QVBoxLayout(install_page)
    install_layout.setSpacing(8)

    install_heading = QLabel("Set up local AI")
    install_heading.setStyleSheet("font-weight: 600; font-size: 14px;")
    install_layout.addWidget(install_heading)

    install_body = QLabel(
        "Klaus runs AI locally through Ollama — nothing ever leaves your "
        "computer. Klaus can download and manage its own copy "
        "automatically, or you can install Ollama yourself."
    )
    install_body.setWordWrap(True)
    install_layout.addWidget(install_body)

    install_status = QLabel()
    install_status.setWordWrap(True)
    install_status.setStyleSheet("color: rgba(140,140,140,0.95); font-size: 11px;")
    install_layout.addWidget(install_status)

    auto_setup_btn = QPushButton(
        f"Set up automatically ({runtime_download_size_hint()} download)"
    )
    auto_setup_btn.setDefault(True)
    install_layout.addWidget(auto_setup_btn)

    manual_lbl = QLabel("Manual options")
    manual_lbl.setStyleSheet("font-weight: 600; margin-top: 8px;")
    install_layout.addWidget(manual_lbl)

    download_btn = QPushButton("Open download page")
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
    install_steps.setStyleSheet("color: rgba(120,120,120,0.95); font-size: 11px;")
    install_layout.addWidget(install_steps)

    install_btn_row = QHBoxLayout()
    check_conn_btn = QPushButton("Check connection")
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

    # Page 1 used to be one long scroll of three group boxes and kept
    # growing (K-052). The install page (page 0) stays a separate
    # QStackedWidget page rather than a tab: a user with no Ollama should
    # not see tabs offering settings that cannot work yet (Local model
    # library) until they've set up local AI or picked a cloud provider.
    # Split follows the existing group boxes 1:1 — Semantic search /
    # Models / General — since that's already the natural job boundary and
    # needed no rethinking to tab cleanly.
    tabs = QTabWidget()
    models_page_layout.addWidget(tabs)

    def _tab(*widgets: QWidget) -> QWidget:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(8)
        for w in widgets:
            tab_layout.addWidget(w)
        tab_layout.addStretch(1)
        return tab

    _MUTED = "color: rgba(140,140,140,0.95); font-size: 11px;"
    _BOLD_TITLE = "QGroupBox { font-weight: 600; }"

    def _caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_MUTED)
        lbl.setWordWrap(True)
        return lbl

    embed_box = QGroupBox("Semantic search")
    embed_box.setStyleSheet(_BOLD_TITLE)
    embed_layout = QVBoxLayout(embed_box)
    embed_layout.setSpacing(8)
    embed_layout.addWidget(
        _caption(
            "Finds cards and decks by meaning, not just keywords — powers "
            "Curate Deck and the Library's retention scores."
        )
    )
    embed_form = QFormLayout()
    embed_form.setContentsMargins(0, 0, 0, 0)
    embed_form.setSpacing(6)
    embed_form.setLabelAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    embed_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    embed_provider_combo = QComboBox()
    embed_provider_combo.addItem("Voyage API (default)", "voyage")
    embed_provider_combo.addItem("OpenAI API", "openai")
    embed_provider_combo.addItem("Local Ollama (private, free)", "ollama")
    embed_provider_combo.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    embed_row = QHBoxLayout()
    embed_row.setContentsMargins(0, 0, 0, 0)
    embed_row.addWidget(embed_provider_combo, 1)
    embed_fix_btn = QPushButton("Pull it")
    embed_fix_btn.setVisible(False)
    embed_row.addWidget(embed_fix_btn)
    embed_form.addRow("Embeddings from:", embed_row)

    embed_model_lbl = QLabel("Search model:")
    embed_model_combo = QComboBox()
    embed_model_combo.setEditable(True)
    embed_model_combo.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    embed_model_combo.setMinimumWidth(220)
    embed_form.addRow(embed_model_lbl, embed_model_combo)

    embed_key_lbl = QLabel("API key:")
    embed_key_edit = QLineEdit()
    embed_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    embed_form.addRow(embed_key_lbl, embed_key_edit)
    embed_layout.addLayout(embed_form)

    index_row = QHBoxLayout()
    embed_status = QLabel()
    embed_status.setWordWrap(True)
    embed_status.setStyleSheet(_MUTED)
    index_row.addWidget(embed_status, 1)
    index_btn = QPushButton("Index cards now")
    index_row.addWidget(index_btn)
    embed_layout.addLayout(index_row)
    embed_layout.addWidget(
        _caption(
            "Needs a Voyage or OpenAI key (both have free tiers) or a local "
            "Ollama model from the library below — that's the only setup "
            "Klaus asks for."
        )
    )

    # ----- Default match sensitivity ---------------------------------------
    # The global starting point for retention._migrate_default_threshold /
    # pdf_match_threshold. Same 20-80 range and live numeric readout as the
    # Library's per-PDF slider (pdf_drive._on_threshold) — same control,
    # different scope, so it should look and feel like the same control.
    threshold_row = QHBoxLayout()
    threshold_row.setContentsMargins(0, 0, 0, 0)
    threshold_row.addWidget(QLabel("Default match sensitivity:"))
    threshold_slider = QSlider(Qt.Orientation.Horizontal)
    threshold_slider.setMinimum(20)
    threshold_slider.setMaximum(80)
    threshold_slider.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    threshold_row.addWidget(threshold_slider, 1)
    threshold_value_lbl = QLabel()
    threshold_value_lbl.setMinimumWidth(36)
    threshold_row.addWidget(threshold_value_lbl)
    embed_layout.addLayout(threshold_row)
    embed_layout.addWidget(
        _caption(
            "Starting point for PDFs that haven't been tuned individually — "
            "the Library's per-PDF sensitivity (right-click a PDF → Match "
            "sensitivity) always wins over this."
        )
    )

    tabs.addTab(_tab(embed_box), "Semantic search")

    # ----- Local model library (inventory only) ----------------------------
    lib_box = QGroupBox("Local model library (Ollama)")
    lib_box.setStyleSheet(_BOLD_TITLE)
    lib_layout = QVBoxLayout(lib_box)
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
    refresh_btn = QPushButton("Refresh")
    pull_row.addWidget(pull_input, 1)
    pull_row.addWidget(pull_btn)
    pull_row.addWidget(delete_btn)
    pull_row.addWidget(refresh_btn)
    lib_layout.addLayout(pull_row)
    tabs.addTab(_tab(lib_box), "Models")

    # ----- General ----------------------------------------------------------
    # The two toggles orphaned by settings_ui.py's deletion (A5) — labels,
    # keys and defaults read from that file, which this card does not edit.
    general_box = QGroupBox("General")
    general_box.setStyleSheet(_BOLD_TITLE)
    general_layout = QVBoxLayout(general_box)
    general_layout.setSpacing(6)

    image_crop_cb = QCheckBox(
        "Image crop (right-click or double-click an image in a note field)"
    )
    general_layout.addWidget(image_crop_cb)

    runtime_auto_cb = QCheckBox(
        "Manage Ollama automatically (start it in the background; offer "
        "one-click setup)"
    )
    general_layout.addWidget(runtime_auto_cb)

    # Maintenance — the two actions that used to live in the Tools > Klaus
    # submenu (K-045). Moved here rather than dropped: a menu item that
    # vanishes is worse than one that's a click deeper.
    maintenance_row = QHBoxLayout()
    maintenance_row.setContentsMargins(0, 0, 0, 0)
    test_conn_btn = QPushButton("Test connection")
    clear_library_btn = QPushButton("Clear library tag")
    maintenance_row.addWidget(test_conn_btn)
    maintenance_row.addWidget(clear_library_btn)
    maintenance_row.addStretch(1)
    general_layout.addLayout(maintenance_row)

    _general_cfg = _pkg().get_config()
    image_crop_cb.setChecked(bool(_general_cfg.get("image_crop_enabled", True)))
    runtime_auto_cb.setChecked(bool(_general_cfg.get("runtime_auto_setup", True)))
    tabs.addTab(_tab(general_box), "General")

    stack.addWidget(models_page)

    # ----- Shared footer --------------------------------------------------
    progress = QProgressBar()
    progress.setRange(0, 100)
    progress.setValue(0)
    progress.setTextVisible(True)
    progress.setVisible(False)
    outer.addWidget(progress)

    progress_lbl = QLabel("")
    progress_lbl.setStyleSheet("color: rgba(140,140,140,0.85); font-size: 11px;")
    progress_lbl.setVisible(False)
    outer.addWidget(progress_lbl)

    close_row = QHBoxLayout()
    close_row.addStretch(1)
    cancel_btn = QPushButton("Cancel download")
    cancel_btn.setVisible(False)
    close_row.addWidget(cancel_btn)
    close_btn = QPushButton("Close")
    close_row.addWidget(close_btn)
    outer.addLayout(close_row)

    install_action_btns: list[QPushButton] = []
    op_state: dict[str, Any] = {"active": False, "kind": "", "cancel": None}
    # Written by refresh(); read by the index pipeline (missing-model check)
    # and the section-sync guards (avoid save-on-programmatic-set loops).
    ui_state: dict[str, Any] = {"models": [], "syncing": False}

    def set_busy(busy: bool) -> None:
        op_state["active"] = busy
        for w in (
            pull_btn, pull_input, delete_btn, refresh_btn,
            auto_setup_btn, download_btn, check_conn_btn,
            embed_provider_combo, embed_model_combo, embed_key_edit,
            embed_fix_btn, index_btn, test_conn_btn, clear_library_btn,
            threshold_slider,
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

    def sync_embed_widgets() -> None:
        from . import curation, embeddings

        ui_state["syncing"] = True
        try:
            cfg = _pkg().get_config()
            provider = embeddings.provider_name(cfg)
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
            if provider == "ollama":
                st = curation.index_stats()
                indexed_model = st["model"] if st["exists"] else ""
                resolved = _resolve_ollama_model(
                    configured_model,
                    ui_state["models"],
                    indexed_model,
                    embeddings.DEFAULT_MODELS["ollama"],
                )
                if resolved != configured_model and ui_state["models"]:
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
        for w in (embed_key_lbl, embed_key_edit):
            w.setVisible(is_cloud)
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
        if provider == prev:
            cfg["embedding_model"] = embed_model_combo.currentText().strip()
        else:
            # Provider switched: the typed model belongs to the old provider.
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
        # An open Library window shows retention/cards computed at the
        # old default for every PDF without its own override — push the
        # new value there immediately rather than waiting for a reopen
        # (K-052 rework: the setting looked like it did nothing).
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
        _pkg().write_config(cfg)

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

    def clear_library_tag() -> None:
        """Moved from the old Tools > Klaus > Clear library tag (K-045),
        logic unchanged. quiet=True on both calls suppresses each
        function's own tooltip so the one summary below is the only
        message (K-038 — two independent async tooltips used to race)."""
        from . import curation, retention

        curation_nids = mw.col.find_notes(f'tag:"{curation.TEMP_TAG}"') if mw.col else []
        pdfmatch_nids = mw.col.find_notes(f'tag:"{retention.RETENTION_TAG}"') if mw.col else []
        if not curation_nids and not pdfmatch_nids:
            tooltip("No notes carry a Klaus library tag.", parent=dlg)
            return
        if not askUser(
            "Clear the Klaus curation and PDF-match tags from all notes?",
            parent=dlg,
        ):
            return

        curation.clear_curation_tag(dlg, quiet=True)
        retention.clear_pdfmatch_tag(dlg, quiet=True)

        parts = []
        if curation_nids:
            parts.append(f"{len(curation_nids)} curation")
        if pdfmatch_nids:
            parts.append(f"{len(pdfmatch_nids)} PDF-match")
        tooltip(
            f"Cleared the library tag from {' and '.join(parts)} notes.",
            parent=dlg,
        )

    auto_setup_btn.clicked.connect(start_auto_setup)
    cancel_btn.clicked.connect(cancel_setup_download)
    dlg.confirm_close_cb = confirm_close  # Esc and title-bar ✕ too
    download_btn.clicked.connect(lambda: openLink(OLLAMA_DOWNLOAD_URL))
    check_conn_btn.clicked.connect(refresh)
    test_conn_btn.clicked.connect(test_connection)
    clear_library_btn.clicked.connect(clear_library_tag)
    delete_btn.clicked.connect(delete_selected)
    refresh_btn.clicked.connect(refresh)
    pull_btn.clicked.connect(start_pull)
    close_btn.clicked.connect(confirm_close)
    embed_fix_btn.clicked.connect(on_embed_fix_clicked)
    embed_provider_combo.currentIndexChanged.connect(lambda _i: save_embed())
    _embed_model_edit_widget = embed_model_combo.lineEdit()
    if _embed_model_edit_widget is not None:
        _embed_model_edit_widget.editingFinished.connect(save_embed)
    embed_model_combo.currentIndexChanged.connect(lambda _i: save_embed())
    embed_key_edit.editingFinished.connect(save_embed)
    threshold_slider.valueChanged.connect(_update_threshold_label)
    threshold_slider.sliderReleased.connect(save_threshold)
    index_btn.clicked.connect(start_index)
    image_crop_cb.toggled.connect(lambda _checked: save_general())
    runtime_auto_cb.toggled.connect(lambda _checked: save_general())

    rebuild_install_method_buttons()
    refresh()
    if setup:
        if stack.currentIndex() == 0:
            # One-click path: go straight to the provisioning confirm.
            QTimer.singleShot(0, start_auto_setup)
        else:
            # Server already fine — jump to getting a first model.
            QTimer.singleShot(0, maybe_auto_pull_starter)
    dlg.exec()

