"""Manage-models dialog: provision the local AI runtime, pull models,
and assign engine roles.

Extracted verbatim from __init__.py (K-023, slice 1 of the K-006 file
split). Backs Tools > Klaus > Manage Models, the first-run one-click setup
path, and the Preferences panel's "Manage models" button.

This module is imported by __init__.py at package load time, so it must
never import __init__ (this package) at module load — only from inside a
function, after the package has finished loading. _pkg() below is that
lazy accessor (same pattern as curation.py's _pkg()); it reaches config
and model-selection helpers that live in __init__.py: get_config,
write_config, client, autocomplete_model, ask_model, klaus_engine,
open_config, _DEFAULT_CLAUDE_MODEL, _save_config_on_main.
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
    QStackedWidget,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import openLink, showInfo, showWarning, tooltip

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

# Suggested presets the user can pull with one click. Everything here runs
# on an 8 GB RAM machine (4-bit quantized weights ≤ ~5.5 GB on disk).
# Index 0 must stay the tiny starter model — the first-run flow pulls it.
_MODEL_PRESETS = [
    # Qwen3 — best quality-per-size family; great autocomplete at the
    # small end. The *-2507 refresh answers directly (no <think> phase),
    # which keeps Ask latency low.
    ("qwen3:0.6b", "fastest · ~0.8 GB"),
    ("qwen3:1.7b", "fast · ~1.4 GB"),
    ("qwen3:4b", "balanced · ~2.5 GB"),
    ("qwen3:4b-instruct-2507", "newest Qwen, no thinking delay · ~2.7 GB"),
    ("qwen3:8b", "best quality · ~5.2 GB"),
    # Google Gemma 3 / 3n — strong small models; 3n is engineered for a
    # low RAM footprint at runtime (bigger download than it "feels").
    ("gemma3:1b", "tiny · ~0.8 GB"),
    ("gemma3:4b", "great quality/size · ~3.3 GB"),
    ("gemma3n:e2b", "low-RAM runtime · ~5.6 GB download"),
    # Microsoft Phi-4 mini — punchy reasoning for its size.
    ("phi4-mini", "strong reasoning for size · ~2.5 GB"),
    # DeepSeek-R1 distill — thinks step-by-step before answering; better
    # for Ask than for autocomplete (the thinking phase adds latency).
    ("deepseek-r1:8b", "reasoning, thinks first · ~5.2 GB"),
    # Meta Llama — solid generalists.
    ("llama3.2:3b", "general · ~2 GB"),
    ("llama3.1:8b", "general · ~4.7 GB"),
    # Community medical fine-tune.
    ("cniongolo/biomistral", "medical-tuned · ~4.4 GB"),
]


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
    """Set up the local AI runtime, pull models, and assign roles.

    ``setup=True`` is the one-click first-run path: it auto-opens the
    provisioning confirm on the setup page, and after the server is up it
    chains straight into pulling the starter model when none exist.
    """
    dlg = _KlausManageDialog(mw)
    dlg.setWindowTitle("Klaus — Manage models")
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
    settings_btn = QPushButton("Settings…")
    install_btn_row.addWidget(check_conn_btn)
    install_btn_row.addStretch(1)
    install_btn_row.addWidget(settings_btn)
    install_layout.addLayout(install_btn_row)
    install_layout.addStretch(1)

    stack.addWidget(install_page)

    # ----- Page 1: jobs on top, model library below ------------------------
    # Organised by JOB (what Klaus does), not by backend: each row owns the
    # one control that decides who performs it. The Ollama list below is
    # pure inventory — it no longer assigns anything.
    models_page = QWidget()
    models_layout = QVBoxLayout(models_page)
    models_layout.setSpacing(8)

    _MUTED = "color: rgba(140,140,140,0.95); font-size: 11px;"
    _WARN = "color: #d9822b; font-size: 11px;"

    jobs_box = QGroupBox("What Klaus uses")
    jobs_layout = QVBoxLayout(jobs_box)
    jobs_layout.setSpacing(6)
    jobs_form = QFormLayout()
    jobs_form.setContentsMargins(0, 0, 0, 0)
    jobs_form.setSpacing(6)

    def _job_row(combo: QComboBox) -> tuple[QHBoxLayout, QLabel, QPushButton]:
        """combo + inline warning + a fix-it button, as one form field."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(combo, 1)
        warn = QLabel()
        warn.setStyleSheet(_WARN)
        warn.setVisible(False)
        row.addWidget(warn)
        fix = QPushButton("Pull it")
        fix.setVisible(False)
        row.addWidget(fix)
        return row, warn, fix

    # Autocomplete — always a local model; cloud per-keystroke is untenable.
    auto_combo = QComboBox()
    auto_row, auto_warn, auto_pull_btn = _job_row(auto_combo)
    jobs_form.addRow("Autocomplete:", auto_row)

    # Ask — engine and model merged into ONE choice. Previously the engine
    # lived here and the model was set by a button over the list, which is
    # what made "brain" vs "Ask model" vs "⌘K" read as three settings.
    ask_combo = QComboBox()
    ask_row, ask_warn, ask_pull_btn = _job_row(ask_combo)
    jobs_form.addRow("Ask (⌘K):", ask_row)

    claude_key_lbl = QLabel("    Claude key:")
    claude_key_edit = QLineEdit()
    claude_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    claude_key_edit.setPlaceholderText(
        "sk-ant-…  (platform.claude.com; stored in add-on config)"
    )
    jobs_form.addRow(claude_key_lbl, claude_key_edit)

    claude_model_lbl = QLabel("    Claude model:")
    claude_model_edit = QLineEdit()
    claude_model_edit.setPlaceholderText(_pkg()._DEFAULT_CLAUDE_MODEL)
    jobs_form.addRow(claude_model_lbl, claude_model_edit)

    # Semantic search — the only job that can use a cloud embedder.
    embed_provider_combo = QComboBox()
    embed_provider_combo.addItem("Voyage API (default)", "voyage")
    embed_provider_combo.addItem("OpenAI API", "openai")
    embed_provider_combo.addItem("Local Ollama (private, free)", "ollama")
    embed_row, embed_warn, embed_fix_btn = _job_row(embed_provider_combo)
    embed_fix_btn.setText("Pull it")
    jobs_form.addRow("Semantic search:", embed_row)

    embed_model_lbl = QLabel("    Search model:")
    embed_model_combo = QComboBox()
    embed_model_combo.setEditable(True)
    embed_model_combo.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    jobs_form.addRow(embed_model_lbl, embed_model_combo)

    embed_key_lbl = QLabel("    API key:")
    embed_key_edit = QLineEdit()
    embed_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    jobs_form.addRow(embed_key_lbl, embed_key_edit)
    jobs_layout.addLayout(jobs_form)

    index_row = QHBoxLayout()
    embed_status = QLabel()
    embed_status.setWordWrap(True)
    embed_status.setStyleSheet(_MUTED)
    index_row.addWidget(embed_status, 1)
    index_btn = QPushButton("Index cards now")
    index_row.addWidget(index_btn)
    jobs_layout.addLayout(index_row)
    models_layout.addWidget(jobs_box)

    # ----- Local model library (inventory only) ----------------------------
    lib_box = QGroupBox("Local model library (Ollama)")
    lib_layout = QVBoxLayout(lib_box)
    lib_layout.setSpacing(6)

    status_lbl = QLabel()
    status_lbl.setStyleSheet(_MUTED)
    lib_layout.addWidget(status_lbl)

    lst = QListWidget()
    lst.setMinimumHeight(96)
    lib_layout.addWidget(lst)

    pull_row = QHBoxLayout()
    pull_input = QComboBox()
    pull_input.setEditable(True)
    pull_input.setMinimumWidth(220)
    pull_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for name, desc in _MODEL_PRESETS:
        pull_input.addItem(f"{name}   ({desc})", name)
    pull_input.setCurrentIndex(-1)
    pull_input.lineEdit().setPlaceholderText("pick or type a model to download")
    pull_btn = QPushButton("Pull")
    delete_btn = QPushButton("Delete")
    refresh_btn = QPushButton("Refresh")
    pull_row.addWidget(pull_input, 1)
    pull_row.addWidget(pull_btn)
    pull_row.addWidget(delete_btn)
    pull_row.addWidget(refresh_btn)
    lib_layout.addLayout(pull_row)
    models_layout.addWidget(lib_box)

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
            auto_setup_btn, download_btn, check_conn_btn, settings_btn,
            auto_combo, auto_pull_btn, ask_combo, ask_pull_btn,
            claude_key_edit, claude_model_edit,
            embed_provider_combo, embed_model_combo, embed_key_edit,
            embed_fix_btn, index_btn,
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
        item = lst.currentItem()
        if not item:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or item.text()

    def refresh() -> None:
        cfg = _pkg().get_config()
        ep = endpoint_url()
        if not ollama_reachable(ep):
            show_install_page()
            return

        stack.setCurrentIndex(1)
        try:
            models = _pkg().client().list_models()
        except OllamaError:
            show_install_page()
            return

        ui_state["models"] = list(models)
        status_lbl.setText(f"Connected to {ep}")
        sync_jobs_widgets()
        sync_embed_widgets()
        rebuild_library_list()

    def rebuild_library_list() -> None:
        """Inventory with a 'used by' badge per model — the list answers
        'what do I have and what is it for', it no longer assigns."""
        from . import embeddings

        cfg = _pkg().get_config()
        models = ui_state["models"]
        selected = get_selected_model()
        lst.clear()
        if not models:
            placeholder = QListWidgetItem("(no models installed — pull one below)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            lst.addItem(placeholder)
            return
        auto_active = _pkg().autocomplete_model(cfg)
        ask_active = _pkg().ask_model(cfg) if _pkg().klaus_engine(cfg) != "claude" else None
        embed_active = (
            embeddings.embedding_model(cfg)
            if embeddings.provider_name(cfg) == "ollama"
            else None
        )
        for name in models:
            tags = [
                label
                for label, active in (
                    ("autocomplete", name == auto_active),
                    ("Ask", name == ask_active),
                    ("search", name == embed_active),
                )
                if active
            ]
            suffix = f"   ·  used by: {', '.join(tags)}" if tags else ""
            item = QListWidgetItem(name + suffix)
            item.setData(Qt.ItemDataRole.UserRole, name)
            lst.addItem(item)
            if name == selected:
                lst.setCurrentItem(item)

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
        the smallest preset when no models exist — one click end to end."""
        if not setup:
            return
        try:
            if _pkg().client().list_models():
                return
        except OllamaError:
            return
        pull_input.setCurrentIndex(0)  # smallest preset (qwen3:0.6b)
        start_pull()

    def start_auto_setup() -> None:
        if op_state["active"]:
            return
        starter_note = (
            "Afterwards, if no model is installed yet, Klaus will also "
            f"pull the starter model {_MODEL_PRESETS[0][0]} (~0.8 GB).\n\n"
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
            if getattr(res, "status", "") in ("reachable", "started"):
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

    # ----- Job assignment (the dropdowns) ----------------------------------

    def _fill_model_combo(combo: QComboBox, current: str, prefix: str = "") -> None:
        """Installed models as items; a missing configured model is kept as
        an item of its own so the dropdown never silently drops it."""
        models = ui_state["models"]
        combo.clear()
        for name in models:
            combo.addItem(f"{prefix}{name}" if prefix else name, name)
        if current and current not in models:
            combo.addItem(
                f"{prefix}{current}  (not installed)" if prefix else
                f"{current}  (not installed)",
                current,
            )
        if not combo.count():
            combo.addItem("(no models installed)", "")
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def sync_jobs_widgets() -> None:
        ui_state["syncing"] = True
        try:
            cfg = _pkg().get_config()
            auto_active = _pkg().autocomplete_model(cfg)
            ask_active = _pkg().ask_model(cfg)
            is_claude = _pkg().klaus_engine(cfg) == "claude"

            _fill_model_combo(auto_combo, auto_active)

            ask_combo.clear()
            for name in ui_state["models"]:
                ask_combo.addItem(f"Local — {name}", f"ollama:{name}")
            if ask_active and ask_active not in ui_state["models"]:
                ask_combo.addItem(
                    f"Local — {ask_active}  (not installed)", f"ollama:{ask_active}"
                )
            if not ask_combo.count():
                # Never let "Claude API…" be the only option — with an empty
                # library any edit to another row would silently switch the
                # engine to Claude.
                ask_combo.addItem("Local — (none installed)", "ollama:")
            ask_combo.addItem("Claude API…", "claude:")
            want = "claude:" if is_claude else f"ollama:{ask_active}"
            idx = ask_combo.findData(want)
            ask_combo.setCurrentIndex(idx if idx >= 0 else 0)

            claude_key_edit.setText(str(cfg.get("claude_api_key") or ""))
            claude_model_edit.setText(str(cfg.get("claude_model") or ""))
        finally:
            ui_state["syncing"] = False
        update_jobs_status()

    def ask_selection() -> tuple[str, str]:
        """The Ask row's merged choice as (engine, local model name)."""
        data = str(ask_combo.currentData() or "")
        if data.startswith("claude"):
            return "claude", ""
        return "ollama", data[len("ollama:"):] if data.startswith("ollama:") else ""

    def update_jobs_status() -> None:
        """Per-row warnings — this is what makes a config pointing at an
        uninstalled model visible instead of a silent contradiction."""
        models = ui_state["models"]
        engine, ask_name = ask_selection()
        is_claude = engine == "claude"
        for w in (claude_key_lbl, claude_key_edit, claude_model_lbl, claude_model_edit):
            w.setVisible(is_claude)

        auto_name = str(auto_combo.currentData() or "")
        auto_missing = bool(auto_name) and auto_name not in models
        auto_warn.setText("⚠ not installed")
        auto_warn.setVisible(auto_missing)
        auto_pull_btn.setVisible(auto_missing)

        ask_missing = bool(ask_name) and ask_name not in models
        if is_claude and not claude_key_edit.text().strip():
            ask_warn.setText("⚠ key needed")
            ask_warn.setVisible(True)
        else:
            ask_warn.setText("⚠ not installed")
            ask_warn.setVisible(ask_missing)
        ask_pull_btn.setVisible(ask_missing)

    def save_jobs() -> None:
        if ui_state["syncing"]:
            return
        cfg = _pkg().get_config()
        auto_name = str(auto_combo.currentData() or "")
        if auto_name:
            cfg["autocomplete_model"] = auto_name
            cfg["model"] = auto_name
        engine, ask_name = ask_selection()
        cfg["klaus_engine"] = engine
        if engine == "ollama" and ask_name:
            cfg["ask_model"] = ask_name
        cfg["claude_api_key"] = claude_key_edit.text().strip()
        cfg["claude_model"] = claude_model_edit.text().strip()
        _pkg().write_config(cfg)
        update_jobs_status()
        rebuild_library_list()

    def pull_missing(name: str) -> None:
        """Fix-it button on a job row: download the model it points at."""
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

        used_by = [
            label
            for label, active in (
                ("autocomplete", _pkg().autocomplete_model(cfg)),
                ("Ask", _pkg().ask_model(cfg) if _pkg().klaus_engine(cfg) != "claude" else None),
                (
                    "semantic search",
                    embeddings.embedding_model(cfg)
                    if embeddings.provider_name(cfg) == "ollama"
                    else None,
                ),
            )
            if active == name
        ]
        warn = (
            f"\n\n⚠ {name} is currently used by {', '.join(used_by)} — "
            "that job will stop working until you pick another model."
            if used_by
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
        from . import embeddings

        ui_state["syncing"] = True
        try:
            cfg = _pkg().get_config()
            provider = embeddings.provider_name(cfg)
            idx = max(0, embed_provider_combo.findData(provider))
            embed_provider_combo.setCurrentIndex(idx)
            # Local provider → offer the installed models; cloud → free text.
            embed_model_combo.clear()
            if provider == "ollama":
                for name in ui_state["models"]:
                    embed_model_combo.addItem(name, name)
            embed_model_combo.setEditText(str(cfg.get("embedding_model") or ""))
            edit = embed_model_combo.lineEdit()
            if edit is not None:
                edit.setPlaceholderText(
                    f"default: {embeddings.DEFAULT_MODELS[provider]}"
                )
            embed_key_edit.setText(str(cfg.get(_embed_cfg_key(provider)) or ""))
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

        # Row-level warning, matching the other two jobs.
        key_missing = is_cloud and not str(
            cfg.get(_embed_cfg_key(provider)) or ""
        ).strip()
        model_missing = (
            not is_cloud and sig[1] and sig[1] not in ui_state["models"]
        )
        if key_missing:
            site = "voyageai.com" if provider == "voyage" else "platform.openai.com"
            embed_warn.setText(f"⚠ key needed ({site})")
        elif model_missing:
            embed_warn.setText("⚠ not installed")
        embed_warn.setVisible(bool(key_missing or model_missing))
        embed_fix_btn.setVisible(bool(model_missing))

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
        note_count = mw.col.note_count() if mw.col else 0
        st = curation.index_stats()
        rebuild_note = (
            "\n\nThe embedding settings changed, so the existing index is "
            "rebuilt from scratch."
            if st["exists"] and (st["provider"], st["model"]) != sig
            else ""
        )
        where = (
            "locally via Ollama — free and private"
            if provider == "ollama"
            else f"via the {provider} API — billed to your key"
        )
        ok = QMessageBox.question(
            dlg,
            "Index cards?",
            f"Klaus will embed {note_count:,} notes with {model} ({where}). "
            "You can cancel any time — progress is saved and indexing "
            f"resumes where it stopped.{rebuild_note}\n\nContinue?",
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

    auto_setup_btn.clicked.connect(start_auto_setup)
    cancel_btn.clicked.connect(cancel_setup_download)
    dlg.confirm_close_cb = confirm_close  # Esc and title-bar ✕ too
    download_btn.clicked.connect(lambda: openLink(OLLAMA_DOWNLOAD_URL))
    check_conn_btn.clicked.connect(refresh)
    settings_btn.clicked.connect(_pkg().open_config)
    delete_btn.clicked.connect(delete_selected)
    refresh_btn.clicked.connect(refresh)
    pull_btn.clicked.connect(start_pull)
    close_btn.clicked.connect(confirm_close)
    auto_combo.currentIndexChanged.connect(lambda _i: save_jobs())
    ask_combo.currentIndexChanged.connect(lambda _i: save_jobs())
    claude_key_edit.editingFinished.connect(save_jobs)
    claude_model_edit.editingFinished.connect(save_jobs)
    auto_pull_btn.clicked.connect(
        lambda: pull_missing(str(auto_combo.currentData() or ""))
    )
    ask_pull_btn.clicked.connect(lambda: pull_missing(ask_selection()[1]))
    embed_fix_btn.clicked.connect(
        lambda: pull_missing(embed_model_combo.currentText().strip())
    )
    embed_provider_combo.currentIndexChanged.connect(lambda _i: save_embed())
    _embed_model_edit_widget = embed_model_combo.lineEdit()
    if _embed_model_edit_widget is not None:
        _embed_model_edit_widget.editingFinished.connect(save_embed)
    embed_model_combo.currentIndexChanged.connect(lambda _i: save_embed())
    embed_key_edit.editingFinished.connect(save_embed)
    index_btn.clicked.connect(start_index)

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

