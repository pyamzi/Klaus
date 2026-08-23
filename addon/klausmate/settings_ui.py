"""Klaus settings widget — embeddable in Anki Preferences or a dialog."""

from __future__ import annotations

from typing import Any, Callable

from aqt import mw
from aqt.utils import askUser, tooltip
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .ollama_client import OllamaNotRunning

_DEFAULT_MODEL = "qwen3:0.6b"


class KlausSettingsPanel(QWidget):
    """All Klaus add-on settings in one scrollable panel."""

    def __init__(
        self,
        parent: QWidget | None = None,
        on_manage_models: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_manage_models = on_manage_models
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        legacy_note = QLabel(
            "Local AI autocomplete and Ask for Anki. Models run via Ollama on this machine."
        )
        legacy_note.setWordWrap(True)
        legacy_note.setStyleSheet("color: rgba(120,120,120,0.95); font-size: 11px;")
        outer.addWidget(legacy_note)

        model_label = QLabel("Models")
        model_label.setStyleSheet("font-weight: 600; margin-top: 4px;")
        outer.addWidget(model_label)

        model_form = QFormLayout()
        self.autocomplete_model_edit = QLineEdit()
        self.autocomplete_model_edit.setPlaceholderText("e.g. qwen3:0.6b")
        model_form.addRow("Autocomplete:", self.autocomplete_model_edit)

        self.ask_model_edit = QLineEdit()
        self.ask_model_edit.setPlaceholderText("e.g. qwen3:4b")
        model_form.addRow("Ask (Cmd+K):", self.ask_model_edit)
        outer.addLayout(model_form)

        model_row = QHBoxLayout()
        model_row.addStretch(1)
        self.manage_btn = QPushButton("Manage models…")
        if on_manage_models:
            self.manage_btn.clicked.connect(on_manage_models)
        model_row.addWidget(self.manage_btn)
        outer.addLayout(model_row)

        self.models_info = QLabel("")
        self.models_info.setWordWrap(True)
        self.models_info.setStyleSheet("color: rgba(120,120,120,0.9); font-size: 11px;")
        outer.addWidget(self.models_info)

        features_label = QLabel("Features")
        features_label.setStyleSheet("font-weight: 600; margin-top: 10px;")
        outer.addWidget(features_label)

        # Either feature can be turned off independently. Both default to on
        # — handled in load_from_config so old configs (pre-toggle) keep
        # working.
        self.autocomplete_enabled_cb = QCheckBox("Inline autocomplete (ghost text)")
        outer.addWidget(self.autocomplete_enabled_cb)
        self.ask_enabled_cb = QCheckBox("Ask popover (⌘K)")
        outer.addWidget(self.ask_enabled_cb)

        engine_label = QLabel("Local AI engine")
        engine_label.setStyleSheet("font-weight: 600; margin-top: 10px;")
        outer.addWidget(engine_label)

        self.runtime_auto_cb = QCheckBox(
            "Manage Ollama automatically (start it in the background; "
            "offer one-click setup)"
        )
        outer.addWidget(self.runtime_auto_cb)

        engine_row = QHBoxLayout()
        self.remove_runtime_btn = QPushButton("Remove Klaus-managed runtime")
        self.remove_runtime_btn.clicked.connect(self._remove_managed_runtime)
        engine_row.addWidget(self.remove_runtime_btn)
        engine_row.addStretch(1)
        outer.addLayout(engine_row)

        brain_pointer = QLabel(
            "The Klaus brain (Ask ⌘K engine, Claude API key) and the card "
            "embeddings for semantic deck curation are configured in "
            "<b>Tools → Klaus → Manage models…</b>"
        )
        brain_pointer.setWordWrap(True)
        brain_pointer.setStyleSheet(
            "color: rgba(140,140,140,0.95); font-size: 11px; margin-top: 8px;"
        )
        outer.addWidget(brain_pointer)

        params_label = QLabel("Generation parameters")
        params_label.setStyleSheet("font-weight: 600; margin-top: 10px;")
        outer.addWidget(params_label)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Word — single token", "word")
        self.mode_combo.addItem("Phrase — to first .!?", "phrase")
        self.mode_combo.addItem("Sentence — one full sentence", "sentence")
        self.mode_combo.addItem("Paragraph — 2–3 sentences", "paragraph")
        self.mode_combo.addItem("Long — multi-line lists", "long")
        form.addRow("Autocomplete length:", self.mode_combo)

        self.temp = QDoubleSpinBox()
        self.temp.setRange(0.0, 2.0)
        self.temp.setSingleStep(0.05)
        self.temp.setDecimals(2)
        form.addRow("Temperature:", self.temp)

        self.top_p = QDoubleSpinBox()
        self.top_p.setRange(0.0, 1.0)
        self.top_p.setSingleStep(0.05)
        self.top_p.setDecimals(2)
        form.addRow("Top P:", self.top_p)

        self.top_k = QSpinBox()
        self.top_k.setRange(0, 500)
        form.addRow("Top K:", self.top_k)

        self.rep = QDoubleSpinBox()
        self.rep.setRange(0.5, 2.0)
        self.rep.setSingleStep(0.05)
        self.rep.setDecimals(2)
        form.addRow("Repeat penalty:", self.rep)

        self.ask_key_edit = QLineEdit()
        form.addRow("Ask popover hotkey:", self.ask_key_edit)

        self.retrieval_top_k = QSpinBox()
        self.retrieval_top_k.setRange(1, 20)
        form.addRow("PDF chunks to inject:", self.retrieval_top_k)

        self.endpoint_edit = QLineEdit()
        form.addRow("Ollama endpoint:", self.endpoint_edit)

        self.min_chars = QSpinBox()
        self.min_chars.setRange(1, 200)
        form.addRow("Min chars before autocomplete:", self.min_chars)

        outer.addLayout(form)

        sp_label = QLabel("System prompt")
        sp_label.setStyleSheet("font-weight: 600; margin-top: 10px;")
        outer.addWidget(sp_label)
        self.sp_edit = QPlainTextEdit()
        self.sp_edit.setMinimumHeight(80)
        outer.addWidget(self.sp_edit)

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        legacy = str(cfg.get("model") or _DEFAULT_MODEL).strip()
        self.autocomplete_model_edit.setText(
            str(cfg.get("autocomplete_model") or legacy).strip()
        )
        self.ask_model_edit.setText(str(cfg.get("ask_model") or legacy).strip())
        mode = cfg.get("completion_mode", "sentence")
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemData(i) == mode:
                self.mode_combo.setCurrentIndex(i)
                break
        self.temp.setValue(float(cfg.get("temperature", 0.2)))
        self.top_p.setValue(float(cfg.get("top_p", 0.9)))
        self.top_k.setValue(int(cfg.get("top_k", 40)))
        self.rep.setValue(float(cfg.get("repeat_penalty", 1.1)))
        self.ask_key_edit.setText(str(cfg.get("ask_hotkey", "Cmd+K")))
        self.retrieval_top_k.setValue(int(cfg.get("retrieval_top_k", 4)))
        self.endpoint_edit.setText(str(cfg.get("endpoint", "http://localhost:11434")))
        self.min_chars.setValue(int(cfg.get("min_chars_before_trigger", 8)))
        self.sp_edit.setPlainText(str(cfg.get("system_prompt", "")))
        self.autocomplete_enabled_cb.setChecked(
            bool(cfg.get("autocomplete_enabled", True))
        )
        self.ask_enabled_cb.setChecked(bool(cfg.get("ask_enabled", True)))
        self.runtime_auto_cb.setChecked(bool(cfg.get("runtime_auto_setup", True)))
        self._refresh_runtime_button()
        self._refresh_models_hint()

    def _refresh_runtime_button(self) -> None:
        try:
            from . import ollama_runtime

            used = ollama_runtime.managed_runtime_disk_usage()
        except Exception:
            used = 0
        if used > 0:
            self.remove_runtime_btn.setText(
                f"Remove Klaus-managed runtime (frees {used / 1_000_000_000:.1f} GB)"
            )
            self.remove_runtime_btn.setEnabled(True)
        else:
            self.remove_runtime_btn.setText("Remove Klaus-managed runtime")
            self.remove_runtime_btn.setEnabled(False)

    def _remove_managed_runtime(self) -> None:
        from . import ollama_runtime

        used = ollama_runtime.managed_runtime_disk_usage()
        if used == 0:
            self._refresh_runtime_button()
            return
        if not askUser(
            "Remove the Ollama runtime that Klaus downloaded "
            f"({used / 1_000_000_000:.1f} GB)?\n\n"
            "Models in ~/.ollama are kept. If Klaus's server is currently "
            "running it will be stopped. You can set it up again any time."
        ):
            return
        active = ollama_runtime.server_manager.active_binary()
        if active and active.startswith(ollama_runtime.runtime_root()):
            ollama_runtime.server_manager.stop()
        ollama_runtime.cleanup_old_runtimes(keep=None)
        tooltip("Klaus: managed runtime removed")
        self._refresh_runtime_button()

    def _refresh_models_hint(self) -> None:
        try:
            from .ollama_client import OllamaClient

            ep = self.endpoint_edit.text().strip() or "http://localhost:11434"
            installed = OllamaClient(ep, timeout=8.0).list_models()
            if installed:
                self.models_info.setText(
                    "Installed: " + ", ".join(installed[:6])
                    + (" …" if len(installed) > 6 else "")
                )
                self.models_info.setStyleSheet(
                    "color: rgba(120,120,120,0.9); font-size: 11px;"
                )
            else:
                self.models_info.setText(
                    "No models reported — open Manage models to pull one."
                )
        except OllamaNotRunning:
            self.models_info.setText(
                "Ollama not reachable — start it or check the endpoint below."
            )
            self.models_info.setStyleSheet(
                "color: rgba(200,140,80,0.95); font-size: 11px;"
            )
        except Exception:
            self.models_info.setText("")

    def save_to_config(self, cfg: dict[str, Any]) -> dict[str, Any]:
        auto_m = self.autocomplete_model_edit.text().strip() or _DEFAULT_MODEL
        ask_m = self.ask_model_edit.text().strip() or auto_m
        cfg["autocomplete_model"] = auto_m
        cfg["ask_model"] = ask_m
        cfg["model"] = auto_m
        cfg["endpoint"] = self.endpoint_edit.text().strip() or "http://localhost:11434"
        cfg["completion_mode"] = self.mode_combo.currentData() or "sentence"
        cfg["temperature"] = float(self.temp.value())
        cfg["top_p"] = float(self.top_p.value())
        cfg["top_k"] = int(self.top_k.value())
        cfg["repeat_penalty"] = float(self.rep.value())
        cfg["ask_hotkey"] = self.ask_key_edit.text().strip() or "Cmd+K"
        cfg["retrieval_top_k"] = int(self.retrieval_top_k.value())
        cfg["min_chars_before_trigger"] = int(self.min_chars.value())
        cfg["system_prompt"] = self.sp_edit.toPlainText()
        cfg["autocomplete_enabled"] = bool(self.autocomplete_enabled_cb.isChecked())
        cfg["ask_enabled"] = bool(self.ask_enabled_cb.isChecked())
        cfg["runtime_auto_setup"] = bool(self.runtime_auto_cb.isChecked())
        return cfg


def open_settings_dialog(
    get_config: Callable[[], dict],
    write_config: Callable[[dict], None],
    manage_models_dialog: Callable[[], None],
    tooltip: Callable[[str], None],
) -> None:
    """Standalone settings dialog (Add-ons → Config)."""
    cfg = get_config()
    dlg = QDialog(mw)
    dlg.setWindowTitle("Klaus — Settings")
    dlg.setMinimumWidth(520)
    lay = QVBoxLayout(dlg)
    panel = KlausSettingsPanel(dlg, on_manage_models=manage_models_dialog)
    panel.load_from_config(cfg)
    lay.addWidget(panel)
    btns = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save
        | QDialogButtonBox.StandardButton.Cancel
    )
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    lay.addWidget(btns)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    write_config(panel.save_to_config(dict(cfg)))
    tooltip("Klaus: settings saved")
