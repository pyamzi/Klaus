"""First-run welcome dialog and per-profile-open readiness checks.

Extracted verbatim from __init__.py (K-025, slice 3 of the K-006 file
split). Backs the one-time "Welcome to Klaus" dialog and the silent
Ollama autostart + actionable-warning flow that runs on every profile
open thereafter.

This module is imported by __init__.py at package load time, so it must
never import __init__ (this package) at module load — only from inside a
function, after the package has finished loading. _pkg() below is that
lazy accessor (same pattern as manage_models.py's and browse_toggles.py's
_pkg()); it reaches config and dialog helpers that still live in
__init__.py: get_config, write_config, client, _save_config_on_main,
open_settings_dialog.
"""

from __future__ import annotations

from typing import Any

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import QMessageBox
from aqt.utils import askUser, openLink, tooltip

from . import ollama_runtime
from .manage_models import manage_models_dialog
from .ollama_runtime import ensure_server, runtime_download_size_hint
from .ollama_setup import OLLAMA_DOWNLOAD_URL


def _pkg():
    import importlib

    return importlib.import_module(__package__)


# Session-scoped flag set when the welcome dialog actually fires. Used by
# setup_readiness_check (registered as a sibling profile-open hook) to
# avoid stacking a second dialog on top of the welcome screen during a
# fresh install.
_first_run_dialog_shown_this_session: bool = False


def first_run_check() -> None:
    """Welcome dialog shown once per profile.

    Always shows the how-to bullets (autocomplete, ⌘K, PDF sidebar) so the
    user knows the feature surface — not just when Ollama is missing. If
    Ollama isn't running we add an install nudge to the same dialog.
    """
    global _first_run_dialog_shown_this_session
    # Reset each profile-open so profile switches re-evaluate cleanly.
    _first_run_dialog_shown_this_session = False
    cfg = _pkg().get_config()
    if cfg.get("_first_run_done"):
        return
    _first_run_dialog_shown_this_session = True
    try:
        # Short timeout — this runs synchronously on the main thread.
        ollama_ok = _pkg().client(5.0).health()
    except Exception:
        ollama_ok = False

    hotkey = cfg.get("ask_hotkey", "Cmd+K")
    body_lines = [
        "Klaus adds local AI to your Anki editor.",
        "",
        "• As you type, ghost-text suggestions appear — press Tab to accept, "
        "Esc to dismiss.",
        f"• Press {hotkey} on any field to open the Ask popover — type a "
        "free-form instruction and Klaus rewrites the field.",
        "• Drop a lecture PDF into the Klaus sidebar to ground suggestions "
        "in what you're reading.",
        "• Semantic search and PDF study priorities use the Voyage API by "
        "default (free key at voyageai.com — paste it under Manage models). "
        "Prefer fully local? Pick Ollama under Manage models → Card "
        "embeddings.",
        "",
    ]
    if ollama_ok:
        body_lines.append("Ollama is running — you're ready to go.")
    else:
        body_lines.append(
            "One click sets everything up: Klaus downloads its local AI "
            f"engine ({runtime_download_size_hint()}) and a starter model. "
            "Autocomplete and Ask run on this computer; semantic search "
            "uses the Voyage cloud API unless you switch it to local Ollama."
        )

    msg = QMessageBox(mw)
    msg.setWindowTitle("Welcome to Klaus")
    msg.setText("\n".join(body_lines))
    msg.setIcon(QMessageBox.Icon.Information)
    setup_btn = None
    if ollama_ok:
        msg.addButton("Got it", QMessageBox.ButtonRole.AcceptRole)
        manage_btn = msg.addButton(
            "Choose models…", QMessageBox.ButtonRole.ActionRole
        )
    else:
        setup_btn = msg.addButton(
            "Set up Klaus", QMessageBox.ButtonRole.ActionRole
        )
        manage_btn = msg.addButton(
            "Manage models…", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("Later", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(setup_btn)
    msg.exec()
    clicked = msg.clickedButton()
    if setup_btn is not None and clicked is setup_btn:
        try:
            manage_models_dialog(setup=True)
        except Exception as exc:
            print(f"[klausmate] setup dialog failed: {exc}")
    elif clicked is manage_btn:
        try:
            manage_models_dialog()
        except Exception:
            pass
    # Re-read before writing: the modal setup dialog above may have written
    # config (endpoint rewrite, model assignments) — writing the snapshot
    # captured before the dialog would silently revert all of it.
    cfg = _pkg().get_config()
    cfg["_first_run_done"] = True
    _pkg().write_config(cfg)


def setup_readiness_check() -> None:
    """Run on every profile open. Silently start a local Ollama when one
    is available (managed runtime or system install), then verify Klaus
    can actually generate — surfacing an actionable dialog only when it
    genuinely can't.

    Skipped on the very first profile open because ``first_run_check``
    already showed the welcome dialog (which itself includes setup
    guidance). The ``_first_run_dialog_shown_this_session`` module flag
    tracks that — both hooks share the ``profile_did_open`` signal in
    registration order: first_run_check runs first, this runs second.
    """
    if _first_run_dialog_shown_this_session:
        return

    cfg = _pkg().get_config()
    if not cfg.get("runtime_auto_setup", True):
        _readiness_check_body()
        return

    # ensure_server never downloads — it only reuses a reachable server or
    # starts an already-present binary, so it's safe to run unprompted.
    def do() -> Any:
        try:
            return ensure_server(
                _pkg().get_config(), save_config=_pkg()._save_config_on_main
            )
        except Exception as e:
            print(f"[klausmate] ensure_server failed: {type(e).__name__}: {e}")
            return None

    def on_ensure_done(res: Any) -> None:
        if getattr(res, "port_moved", False):
            tooltip(f"Klaus: local AI running on {res.endpoint}")
        _maybe_offer_runtime_update(res)
        _readiness_check_body()

    op = QueryOp(parent=mw, op=lambda col: do(), success=on_ensure_done)
    op.failure(lambda _e: _readiness_check_body())
    op.without_collection().run_in_background()


def _maybe_offer_runtime_update(res: Any) -> None:
    """Non-blocking, once-per-version offer to move a managed server onto
    the add-on's newly pinned Ollama version. The old version keeps
    working regardless — never block startup on an upgrade."""
    if getattr(res, "detail", "") != "update_available":
        return
    cfg = _pkg().get_config()
    offered_key = f"_runtime_update_offered_{ollama_runtime.OLLAMA_VERSION}"
    if cfg.get(offered_key):
        return
    cfg[offered_key] = True
    _pkg().write_config(cfg)
    if not askUser(
        "Klaus can update its local AI engine to Ollama "
        f"v{ollama_runtime.OLLAMA_VERSION} "
        f"({runtime_download_size_hint()} download).\n\n"
        "Update in the background? The engine restarts briefly once the "
        "download finishes; you can keep studying meanwhile."
    ):
        return

    def do() -> Any:
        return ollama_runtime.update_runtime(
            _pkg().get_config(), save_config=_pkg()._save_config_on_main
        )

    def on_done(res2: Any) -> None:
        if getattr(res2, "status", "") in ("reachable", "started"):
            tooltip("Klaus: local AI engine updated")
        else:
            print(
                "[klausmate] runtime update failed: "
                f"{getattr(res2, 'detail', '')}"
            )

    op = QueryOp(parent=mw, op=lambda col: do(), success=on_done)
    op.failure(lambda e: print(f"[klausmate] runtime update failed: {e}"))
    op.without_collection().run_in_background()


def _readiness_check_body() -> None:
    """The actual readiness dialogs; runs after the silent autostart."""
    # Re-read config — ensure_server may have rewritten the endpoint.
    cfg = _pkg().get_config()
    auto = bool(cfg.get("runtime_auto_setup", True))

    # ---- 1. Ollama reachable? -------------------------------------------
    try:
        # Short timeout — this runs synchronously on the main thread.
        ollama_ok = _pkg().client(5.0).health()
    except Exception:
        ollama_ok = False

    if not ollama_ok:
        if not auto:
            # runtime_auto_setup: false means fully manual behavior — no
            # unprompted setup offers, just the old-style warning.
            msg = QMessageBox(mw)
            msg.setWindowTitle("Klaus: Ollama isn't running")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                "Klaus needs Ollama to generate suggestions. Install it "
                "from https://ollama.com, start it, and restart Anki.\n\n"
                "(Automatic management is disabled in Klaus settings.)"
            )
            open_btn = msg.addButton(
                "Open download page", QMessageBox.ButtonRole.ActionRole
            )
            msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
            msg.exec()
            if msg.clickedButton() is open_btn:
                openLink(OLLAMA_DOWNLOAD_URL)
            return
        if cfg.get("_runtime_setup_declined"):
            print("[klausmate] Ollama unreachable; auto-setup previously declined")
            return
        msg = QMessageBox(mw)
        msg.setWindowTitle("Klaus: local AI isn't set up yet")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "Klaus needs a local AI engine (Ollama) to generate "
            "suggestions — and it can set one up for you automatically "
            f"(one-time {runtime_download_size_hint()} download).\n\n"
            "Everything runs on this computer. Nothing is sent anywhere."
        )
        msg.setInformativeText(
            "Until then, ⌘K, ghost-text autocomplete, and the Browse "
            "natural-language search will all be silent."
        )
        setup_btn = msg.addButton(
            "Set up automatically", QMessageBox.ButtonRole.ActionRole
        )
        manual_btn = msg.addButton(
            "Install manually…", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(setup_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is setup_btn:
            try:
                manage_models_dialog(setup=True)
            except Exception as exc:
                print(f"[klausmate] setup dialog failed: {exc}")
        elif clicked is manual_btn:
            openLink(OLLAMA_DOWNLOAD_URL)
        else:
            # Respect the decision — don't re-prompt on every profile
            # open. Re-read config first: a modal above us may have
            # written it while this snapshot was held.
            cfg = _pkg().get_config()
            cfg["_runtime_setup_declined"] = True
            _pkg().write_config(cfg)
        return

    # ---- 2. Models configured + installed? ------------------------------
    legacy = (cfg.get("model") or "").strip()
    auto = (cfg.get("autocomplete_model") or legacy).strip()
    ask_m = (cfg.get("ask_model") or legacy).strip()

    try:
        installed = set(_pkg().client().list_models())
    except Exception:
        installed = set()

    missing: list[tuple[str, str]] = []
    if not auto:
        missing.append(("Autocomplete", "<not selected>"))
    elif auto not in installed:
        missing.append(("Autocomplete", auto))
    if not ask_m:
        missing.append(("Ask (⌘K)", "<not selected>"))
    elif ask_m not in installed:
        missing.append(("Ask (⌘K)", ask_m))

    if not missing:
        return  # All set — silent

    bullets = "\n".join(f"  • {role}: {name}" for role, name in missing)
    msg = QMessageBox(mw)
    msg.setWindowTitle("Klaus: model setup needed")
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setText(
        "Klaus is connected to Ollama, but the model(s) it's configured "
        "to use aren't installed locally yet:\n\n"
        + bullets
        + "\n\nOpen Manage models… to pull a model (e.g. "
        "`qwen3:0.6b` for autocomplete, `qwen3:4b` for Ask), or pick a "
        "model you already have in Klaus settings."
    )
    msg.setInformativeText(
        "Until a model is available, ⌘K and ghost-text autocomplete "
        "won't produce output."
    )
    manage_btn = msg.addButton(
        "Manage models…", QMessageBox.ButtonRole.ActionRole
    )
    settings_btn = msg.addButton(
        "Open Klaus settings…", QMessageBox.ButtonRole.ActionRole
    )
    msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
    msg.exec()
    clicked = msg.clickedButton()
    if clicked is manage_btn:
        try:
            manage_models_dialog()
        except Exception as exc:
            print(f"[klausmate] manage_models_dialog failed: {exc}")
    elif clicked is settings_btn:
        try:
            _pkg().open_settings_dialog()
        except Exception as exc:
            print(f"[klausmate] open_settings_dialog failed: {exc}")
