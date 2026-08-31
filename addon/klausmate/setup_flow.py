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

from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import QMessageBox, QTimer
from aqt.utils import openLink, showWarning, tooltip

from . import embeddings, ollama_runtime
from .manage_models import manage_models_dialog
from .ollama_runtime import ensure_server, runtime_download_size_hint
from .ollama_setup import OLLAMA_DOWNLOAD_URL, ollama_reachable


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _themed_message_box(parent: Any, title: str, icon: Any) -> QMessageBox:
    """Build a QMessageBox styled with the shared dialog QSS.

    Every readiness/warning prompt in this module goes through here, so
    theming (and its guarded fallback) lives in one place — same pattern
    as manage_models.py's dialog_qss application.
    """
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setIcon(icon)
    try:
        from . import theme

        msg.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    except Exception as exc:
        print(f"[klausmate] setup dialog theme failed: {exc}")
    return msg


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
        if not ollama_reachable(cfg.get("endpoint", "http://localhost:11434")):
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
            "(free tier available). Add it under KlausMate Preferences, or "
            "switch to a local embedding model there."
        )

    msg = _themed_message_box(mw, "Welcome to Klaus", QMessageBox.Icon.Information)
    msg.setText("\n".join(body_lines))
    setup_btn = None
    if ready:
        # "OK" is the primary/dismissive action here — stays default blue.
        msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        manage_btn = msg.addButton(
            "KlausMate Preferences", QMessageBox.ButtonRole.ActionRole
        )
        manage_btn.setObjectName("SecondaryButton")
    elif is_ollama:
        setup_btn = msg.addButton(
            "Set up Klaus", QMessageBox.ButtonRole.ActionRole
        )
        manage_btn = msg.addButton(
            "KlausMate Preferences", QMessageBox.ButtonRole.ActionRole
        )
        manage_btn.setObjectName("SecondaryButton")
        msg.addButton(
            "Later", QMessageBox.ButtonRole.AcceptRole
        ).setObjectName("SecondaryButton")
        msg.setDefaultButton(setup_btn)
    else:
        manage_btn = msg.addButton(
            "KlausMate Preferences", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton(
            "Later", QMessageBox.ButtonRole.AcceptRole
        ).setObjectName("SecondaryButton")
        msg.setDefaultButton(manage_btn)
    def _on_welcome_finished(_r: int) -> None:
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
        # Re-read before writing: the setup dialog opened above (or
        # anything else that ran while the welcome dialog was up) may
        # have written config — writing the snapshot captured before
        # the dialog would silently revert all of it.
        cfg2 = _pkg().get_config()
        cfg2["_first_run_done"] = True
        _pkg().write_config(cfg2)
        msg.deleteLater()

    # K-114: window-modal open() + finished callback, never app-modal
    # exec() (the macOS 26 + Qt 6.11 segfault class pinned in
    # test_bridge_reentrancy). clickedButton() is still valid inside a
    # finished handler, and Esc/close land there too — the exact paths
    # exec()'s fall-through used to cover. The closure keeps ``msg``
    # referenced so the shown dialog can't be garbage-collected out
    # from under the user.
    msg.finished.connect(_on_welcome_finished)
    msg.open()


def _library_root_check(then: Callable[[], None]) -> None:
    """Offer to pick a real on-disk folder for the Library (K-070, part A
    of K-057) once ``library_root`` is unset. Runs as one step of the
    per-profile-open readiness check, before the embedding-provider
    checks below.

    Declining writes nothing to config — the next profile open re-asks,
    exactly once, since this only ever runs from ``setup_readiness_check``
    which itself fires once per profile-open. No "stop asking forever"
    flag exists on purpose: an unset Library folder is a state worth
    re-surfacing, unlike a one-time API-key nudge.

    ``then()`` continues the caller's readiness flow once this step has
    fully resolved (root already set, declined, folder pick cancelled,
    or the migration op kicked off in the background) — the blocking
    askUser this replaced (K-125: its internal exec() is the K-114
    app-modal segfault class) gave callers that ordering for free, and
    the chain keeps the readiness dialogs from stacking on this one.
    """
    from . import pdf_handler

    cfg = _pkg().get_config()
    if pdf_handler.get_library_root(cfg):
        then()
        return

    msg = _themed_message_box(
        mw, "KlausMate: Library folder", QMessageBox.Icon.Question
    )
    msg.setText(
        "Klaus can keep your Library PDFs in a real folder on disk "
        "(instead of tucked inside the add-on) so they show up in "
        "Finder/Explorer too, and any existing PDFs get moved there.\n\n"
        "Choose a folder now?"
    )
    msg.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    # askUser parity: default Yes (no defaultno was passed), Esc = No.
    msg.setDefaultButton(QMessageBox.StandardButton.Yes)
    no_btn = msg.button(QMessageBox.StandardButton.No)
    if no_btn is not None:
        no_btn.setObjectName("SecondaryButton")

    def _pick_folder() -> None:
        from aqt.qt import QFileDialog

        chosen = QFileDialog.getExistingDirectory(
            mw, "Choose a folder for your Klaus Library"
        )
        if not chosen:
            then()
            return

        def do(_col: Any) -> Any:
            from . import USER_FILES, drive_store

            folders = drive_store.load(USER_FILES).get("pdfs", {})
            return pdf_handler.migrate_to_root(USER_FILES, chosen, folders)

        def on_done(result: Any) -> None:
            cfg2 = _pkg().get_config()
            cfg2["library_root"] = chosen
            _pkg().write_config(cfg2)
            failed = (result or {}).get("failed") or {}
            if failed:
                tooltip(
                    f"Klaus: Library folder set — {len(failed)} file(s) "
                    "couldn't be moved and stay in the old location"
                )
            else:
                tooltip("Klaus: Library folder set")

        def on_fail(exc: Exception) -> None:
            print(f"[klausmate] library migration failed: {exc}")
            showWarning(
                f"Could not set up the Library folder: {exc}", parent=mw
            )

        op = QueryOp(parent=mw, op=do, success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()
        # The old blocking flow continued to the readiness checks as
        # soon as the op was launched, not when it finished — kept.
        then()

    def _on_answered(_r: int) -> None:
        clicked = msg.clickedButton()
        accepted = (
            clicked is not None
            and msg.standardButton(clicked) == QMessageBox.StandardButton.Yes
        )
        msg.deleteLater()
        if not accepted:
            then()  # ask again next profile open — nothing persisted
            return
        # The native folder sheet nests its own loop — run it a tick
        # after this finished handler unwinds, never from inside it.
        QTimer.singleShot(0, _pick_folder)

    # K-125: open() + finished, never a blocking askUser (see docstring).
    msg.finished.connect(_on_answered)
    msg.open()


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

    # K-125: the Library-folder offer is callback-driven now, so the
    # provider checks run through its continuation — the old blocking
    # askUser ordered the two prompt families for free.
    _library_root_check(_readiness_after_library_root)


def _readiness_after_library_root() -> None:
    """The provider-readiness half of setup_readiness_check, chained
    behind the Library-folder offer's continuation (K-125)."""
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
        # K-125: the readiness dialogs run through the update offer's
        # continuation so they can never stack on its question.
        _maybe_offer_runtime_update(res, _readiness_check_body)

    op = QueryOp(parent=mw, op=lambda col: do(), success=on_ensure_done)
    op.failure(lambda _e: _readiness_check_body())
    op.without_collection().run_in_background()


def _maybe_offer_runtime_update(res: Any, then: Callable[[], None]) -> None:
    """Non-blocking, once-per-version offer to move a managed server onto
    the add-on's newly pinned Ollama version. The old version keeps
    working regardless — never block startup on an upgrade.

    Irrelevant to a cloud embedding provider, which has no local runtime
    to update.

    ``then()`` continues the caller's flow once the offer has resolved —
    every early return and both dialog answers reach it exactly once,
    the ordering the blocking askUser (K-125: internal app-modal exec,
    the K-114 segfault class) used to provide by blocking.
    """
    cfg = _pkg().get_config()
    if embeddings.provider_name(cfg) != "ollama":
        then()
        return
    if getattr(res, "detail", "") != "update_available":
        then()
        return
    offered_key = f"_runtime_update_offered_{ollama_runtime.OLLAMA_VERSION}"
    if cfg.get(offered_key):
        then()
        return
    cfg[offered_key] = True
    _pkg().write_config(cfg)

    msg = _themed_message_box(
        mw, "KlausMate: local AI engine update", QMessageBox.Icon.Question
    )
    msg.setText(
        "Klaus can update its local AI engine to Ollama "
        f"v{ollama_runtime.OLLAMA_VERSION} "
        f"({runtime_download_size_hint()} download).\n\n"
        "Update in the background? The engine restarts briefly once the "
        "download finishes; you can keep studying meanwhile."
    )
    msg.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    # askUser parity: default Yes (no defaultno was passed), Esc = No.
    msg.setDefaultButton(QMessageBox.StandardButton.Yes)
    no_btn = msg.button(QMessageBox.StandardButton.No)
    if no_btn is not None:
        no_btn.setObjectName("SecondaryButton")

    def _on_answered(_r: int) -> None:
        clicked = msg.clickedButton()
        accepted = (
            clicked is not None
            and msg.standardButton(clicked) == QMessageBox.StandardButton.Yes
        )
        msg.deleteLater()
        if accepted:

            def do() -> Any:
                return ollama_runtime.update_runtime(
                    _pkg().get_config(),
                    save_config=_pkg()._save_config_on_main,
                )

            def on_update_done(res2: Any) -> None:
                if getattr(res2, "ok", False):
                    tooltip("Klaus: local AI engine updated")
                else:
                    print(
                        "[klausmate] runtime update failed: "
                        f"{getattr(res2, 'detail', '')}"
                    )

            op = QueryOp(parent=mw, op=lambda col: do(), success=on_update_done)
            op.failure(
                lambda e: print(f"[klausmate] runtime update failed: {e}")
            )
            op.without_collection().run_in_background()
        # Continue whether the update was taken or declined — the old
        # blocking flow did after its answer either way.
        then()

    # K-125: open() + finished, never a blocking askUser.
    msg.finished.connect(_on_answered)
    msg.open()


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
    # Short timeout — this runs synchronously on the main thread.
    ollama_ok = ollama_reachable(cfg.get("endpoint", "http://localhost:11434"))

    if not ollama_ok:
        if not auto:
            # runtime_auto_setup: false means fully manual behavior — no
            # unprompted setup offers, just the old-style warning.
            msg = _themed_message_box(
                mw, "KlausMate: Ollama isn't running", QMessageBox.Icon.Warning
            )
            msg.setText(
                "Semantic search is set to use a local Ollama model, but "
                "Ollama isn't running. Install it from https://ollama.com, "
                "start it, and restart Anki.\n\n"
                "(Automatic management is disabled in Klaus settings.)"
            )
            open_btn = msg.addButton(
                "Open Download Page", QMessageBox.ButtonRole.ActionRole
            )
            msg.addButton(
                "Later", QMessageBox.ButtonRole.AcceptRole
            ).setObjectName("SecondaryButton")

            def _on_no_ollama_finished(_r: int) -> None:
                if msg.clickedButton() is open_btn:
                    openLink(OLLAMA_DOWNLOAD_URL)
                msg.deleteLater()

            # K-114: open() + finished, never exec (see first_run_check).
            msg.finished.connect(_on_no_ollama_finished)
            msg.open()
            return
        if cfg.get("_runtime_setup_declined"):
            print("[klausmate] Ollama unreachable; auto-setup previously declined")
            return
        msg = _themed_message_box(
            mw,
            "KlausMate: local embedding model isn't set up yet",
            QMessageBox.Icon.Warning,
        )
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
        manual_btn.setObjectName("SecondaryButton")
        msg.addButton(
            "Later", QMessageBox.ButtonRole.AcceptRole
        ).setObjectName("SecondaryButton")
        msg.setDefaultButton(setup_btn)

        def _on_offer_finished(_r: int) -> None:
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
                # open. Re-read config first: something else may have
                # written it while this dialog was up.
                cfg2 = _pkg().get_config()
                cfg2["_runtime_setup_declined"] = True
                _pkg().write_config(cfg2)
            msg.deleteLater()

        # K-114: open() + finished, never exec (see first_run_check) —
        # Esc/close still land in the else branch, exactly as exec()'s
        # fall-through did.
        msg.finished.connect(_on_offer_finished)
        msg.open()
        return

    # ---- 2. Embedding model installed? -----------------------------------
    model = embeddings.embedding_model(cfg)
    try:
        installed = set(_pkg().client().list_models())
    except Exception:
        installed = set()

    if model in installed:
        return  # All set — silent

    msg = _themed_message_box(
        mw, "KlausMate: embedding model needed", QMessageBox.Icon.Warning
    )
    msg.setText(
        "Klaus is connected to Ollama, but the embedding model it's "
        f"configured to use isn't installed yet: {model}\n\n"
        "Open KlausMate Preferences to download it, or choose a different "
        "embedding model there."
    )
    msg.setInformativeText(
        "Until it's installed, semantic search and PDF study priorities "
        "won't produce results."
    )
    manage_btn = msg.addButton(
        "KlausMate Preferences", QMessageBox.ButtonRole.ActionRole
    )
    msg.addButton(
        "Later", QMessageBox.ButtonRole.AcceptRole
    ).setObjectName("SecondaryButton")

    def _on_model_needed_finished(_r: int) -> None:
        if msg.clickedButton() is manage_btn:
            try:
                manage_models_dialog()
            except Exception as exc:
                print(f"[klausmate] manage_models_dialog failed: {exc}")
        msg.deleteLater()

    # K-114: open() + finished, never exec (see first_run_check).
    msg.finished.connect(_on_model_needed_finished)
    msg.open()


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
    msg = _themed_message_box(
        mw, "KlausMate: semantic search needs an API key", QMessageBox.Icon.Warning
    )
    msg.setText(
        f"Semantic search uses {provider_label}, but no API key is set. "
        f"Add a free key from {site} under KlausMate Preferences, or switch "
        "to a local embedding model there."
    )
    msg.setInformativeText(
        "Until then, semantic search and PDF study priorities won't "
        "produce results."
    )
    manage_btn = msg.addButton(
        "KlausMate Preferences", QMessageBox.ButtonRole.ActionRole
    )
    msg.addButton(
        "Later", QMessageBox.ButtonRole.AcceptRole
    ).setObjectName("SecondaryButton")

    def _on_key_needed_finished(_r: int) -> None:
        if msg.clickedButton() is manage_btn:
            try:
                manage_models_dialog()
            except Exception as exc:
                print(f"[klausmate] manage_models_dialog failed: {exc}")
        else:
            # Respect the decision — don't re-prompt on every profile
            # open.
            cfg2 = _pkg().get_config()
            cfg2["_embed_key_setup_declined"] = True
            _pkg().write_config(cfg2)
        msg.deleteLater()

    # K-114: open() + finished, never exec (see first_run_check) —
    # Esc/close still count as declining, as exec()'s fall-through did.
    msg.finished.connect(_on_key_needed_finished)
    msg.open()
