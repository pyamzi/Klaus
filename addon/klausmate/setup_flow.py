"""First-run welcome dialog and per-profile-open readiness checks.

Extracted verbatim from __init__.py (K-025, slice 3 of the K-006 file
split). Backs the one-time "Welcome to Klaus" dialog and the silent
Ollama autostart + actionable-warning flow that runs on every profile
open thereafter.

Klaus is embeddings-only (K-029): the only thing this module needs to
report readiness on is the embedding provider that powers semantic search
and PDF study priorities. The default provider is Voyage, a cloud API —
Ollama is an optional local alternative, not a requirement. Every check
below is gated on ``embeddings.provider_name(cfg)`` so a cloud-provider
profile never sees Ollama-flavored copy or probes.

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

from . import embeddings, ollama_runtime
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


def _embedding_ready(cfg: dict) -> bool:
    """True if semantic search can actually run right now.

    Cloud providers (Voyage, OpenAI) are ready once their API key is set —
    no local runtime involved. Ollama is ready once it's reachable AND the
    configured embedding model is pulled.
    """
    provider = embeddings.provider_name(cfg)
    if provider != "ollama":
        key = str(cfg.get(f"embedding_api_key_{provider}") or "").strip()
        return bool(key)
    try:
        if not _pkg().client(5.0).health():
            return False
        installed = set(_pkg().client().list_models())
    except Exception:
        return False
    return embeddings.embedding_model(cfg) in installed


def first_run_check() -> None:
    """Welcome dialog shown once per profile.

    Always shows the how-to bullets (PDF sidebar, semantic search) so the
    user knows the feature surface — not just when something needs setup.
    The readiness line and follow-up buttons adapt to whichever embedding
    provider is configured.
    """
    global _first_run_dialog_shown_this_session
    # Reset each profile-open so profile switches re-evaluate cleanly.
    _first_run_dialog_shown_this_session = False
    cfg = _pkg().get_config()
    if cfg.get("_first_run_done"):
        return
    _first_run_dialog_shown_this_session = True

    provider = embeddings.provider_name(cfg)
    is_ollama = provider == "ollama"
    ready = _embedding_ready(cfg)

    body_lines = [
        "Klaus adds a PDF workspace and semantic search to Anki.",
        "",
        "• The PDF sidebar lets you read a lecture PDF, highlight it, and "
        "keep it open next to your cards.",
        "• Semantic search finds cards by meaning, not just keywords, and "
        "can curate a deck for you — open it from the Browse screen.",
        "",
    ]
    if ready and not is_ollama:
        provider_label = "Voyage" if provider == "voyage" else "OpenAI"
        body_lines.append(f"Semantic search runs on {provider_label} — you're ready to go.")
    elif ready:
        body_lines.append(
            "Ollama is running with the embedding model installed — "
            "semantic search is ready."
        )
    elif is_ollama:
        body_lines.append(
            "Semantic search is set to use a local Ollama model. One "
            f"click sets it up: Klaus downloads Ollama "
            f"({runtime_download_size_hint()}) and the embedding model. "
            "Nothing leaves this computer."
        )
    else:
        provider_label = "Voyage" if provider == "voyage" else "OpenAI"
        body_lines.append(
            f"Semantic search needs a {provider_label} API key to work "
            "(free tier available). Add it under Manage models, or "
            "switch to a local embedding model there."
        )

    msg = QMessageBox(mw)
    msg.setWindowTitle("Welcome to Klaus")
    msg.setText("\n".join(body_lines))
    msg.setIcon(QMessageBox.Icon.Information)
    setup_btn = None
    if ready:
        msg.addButton("Got it", QMessageBox.ButtonRole.AcceptRole)
        manage_btn = msg.addButton(
            "Manage models…", QMessageBox.ButtonRole.ActionRole
        )
    elif is_ollama:
        setup_btn = msg.addButton(
            "Set up Klaus", QMessageBox.ButtonRole.ActionRole
        )
        manage_btn = msg.addButton(
            "Manage models…", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("Later", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(setup_btn)
    else:
        manage_btn = msg.addButton(
            "Manage models…", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("Later", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(manage_btn)
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
    can actually embed — surfacing an actionable dialog only when it
    genuinely can't.

    Skipped on the very first profile open because ``first_run_check``
    already showed the welcome dialog (which itself includes setup
    guidance). The ``_first_run_dialog_shown_this_session`` module flag
    tracks that — both hooks share the ``profile_did_open`` signal in
    registration order: first_run_check runs first, this runs second.

    The silent Ollama autostart only makes sense when the configured
    embedding provider actually is Ollama — a cloud-provider profile
    (the default) skips straight to the readiness dialog logic, which
    itself never touches Ollama for a cloud provider.
    """
    if _first_run_dialog_shown_this_session:
        return

    cfg = _pkg().get_config()
    if embeddings.provider_name(cfg) != "ollama":
        _readiness_check_body()
        return

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
    working regardless — never block startup on an upgrade.

    Irrelevant to a cloud embedding provider, which has no local runtime
    to update.
    """
    cfg = _pkg().get_config()
    if embeddings.provider_name(cfg) != "ollama":
        return
    if getattr(res, "detail", "") != "update_available":
        return
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
    provider = embeddings.provider_name(cfg)
    if provider != "ollama":
        _cloud_readiness_check(cfg, provider)
        return

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
                "Semantic search is set to use a local Ollama model, but "
                "Ollama isn't running. Install it from https://ollama.com, "
                "start it, and restart Anki.\n\n"
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
        msg.setWindowTitle("Klaus: local embedding model isn't set up yet")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "Semantic search is set to use a local Ollama model, and "
            "Klaus can set it up automatically (one-time "
            f"{runtime_download_size_hint()} download).\n\n"
            "Everything runs on this computer. Nothing is sent anywhere."
        )
        msg.setInformativeText(
            "Until then, semantic search and PDF study priorities won't "
            "produce results."
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

    # ---- 2. Embedding model installed? -----------------------------------
    model = embeddings.embedding_model(cfg)
    try:
        installed = set(_pkg().client().list_models())
    except Exception:
        installed = set()

    if model in installed:
        return  # All set — silent

    msg = QMessageBox(mw)
    msg.setWindowTitle("Klaus: embedding model needed")
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setText(
        "Klaus is connected to Ollama, but the embedding model it's "
        f"configured to use isn't installed yet: {model}\n\n"
        "Open Manage models… to pull it, or choose a different embedding "
        "model there."
    )
    msg.setInformativeText(
        "Until it's installed, semantic search and PDF study priorities "
        "won't produce results."
    )
    manage_btn = msg.addButton(
        "Manage models…", QMessageBox.ButtonRole.ActionRole
    )
    msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
    msg.exec()
    if msg.clickedButton() is manage_btn:
        try:
            manage_models_dialog()
        except Exception as exc:
            print(f"[klausmate] manage_models_dialog failed: {exc}")


def _cloud_readiness_check(cfg: dict, provider: str) -> None:
    """Readiness for Voyage/OpenAI: ready once an API key is set. No
    runtime to start, no Ollama to reach — just the key."""
    key = str(cfg.get(f"embedding_api_key_{provider}") or "").strip()
    if key:
        return  # All set — silent

    if cfg.get("_embed_key_setup_declined"):
        return

    provider_label = "Voyage" if provider == "voyage" else "OpenAI"
    site = "voyageai.com" if provider == "voyage" else "platform.openai.com"
    msg = QMessageBox(mw)
    msg.setWindowTitle("Klaus: semantic search needs an API key")
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setText(
        f"Semantic search uses {provider_label}, but no API key is set. "
        f"Add a free key from {site} under Manage models, or switch to a "
        "local embedding model there."
    )
    msg.setInformativeText(
        "Until then, semantic search and PDF study priorities won't "
        "produce results."
    )
    manage_btn = msg.addButton(
        "Manage models…", QMessageBox.ButtonRole.ActionRole
    )
    msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
    msg.exec()
    if msg.clickedButton() is manage_btn:
        try:
            manage_models_dialog()
        except Exception as exc:
            print(f"[klausmate] manage_models_dialog failed: {exc}")
    else:
        # Respect the decision — don't re-prompt on every profile open.
        cfg = _pkg().get_config()
        cfg["_embed_key_setup_declined"] = True
        _pkg().write_config(cfg)
