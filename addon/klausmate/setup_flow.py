"""Welcome, library-folder readiness and silent local Ollama startup."""

from __future__ import annotations

from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import QMessageBox, QTimer
from aqt.utils import showWarning, tooltip

from .manage_models import manage_models_dialog
from . import settings

LOCAL_MODELS_COPY = (
    "Semantic search uses local Ollama embeddings. Configure your Ollama endpoint "
    "and embedding model in KlausMate Preferences → Local models."
)


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


def first_run_check() -> None:
    """Welcome dialog shown once per profile.

    Always shows the how-to bullets (PDF sidebar, semantic search) so the
    user knows the feature surface — not just when something needs setup.
    The readiness line directs users to local model settings.
    """
    global _first_run_dialog_shown_this_session
    # Reset each profile-open so profile switches re-evaluate cleanly.
    _first_run_dialog_shown_this_session = False
    cfg = settings.read()
    generation = _profile_generation
    if cfg.get("_first_run_done"):
        return
    _first_run_dialog_shown_this_session = True

    body_lines = [
        "Klaus adds a PDF workspace and semantic search to Anki.",
        "",
        "• The PDF sidebar lets you read a lecture PDF, highlight it, and "
        "keep it open next to your cards.",
        "• Semantic search finds the cards each lecture PDF covers, tags "
        "them, and scores how well you still recall them.",
        "",
    ]
    body_lines.append(LOCAL_MODELS_COPY)

    msg = _themed_message_box(mw, "Welcome to Klaus", QMessageBox.Icon.Information)
    msg.setText("\n".join(body_lines))
    manage_btn = msg.addButton(
        "KlausMate Preferences", QMessageBox.ButtonRole.ActionRole
    )
    msg.addButton(
        "Later", QMessageBox.ButtonRole.AcceptRole
    ).setObjectName("SecondaryButton")
    msg.setDefaultButton(manage_btn)

    def _on_welcome_finished(_r: int) -> None:
        if generation != _profile_generation:
            msg.deleteLater()
            return
        clicked = msg.clickedButton()
        if clicked is manage_btn:
            try:
                manage_models_dialog()
            except Exception:
                pass
        # Re-read before writing: the setup dialog opened above (or
        # anything else that ran while the welcome dialog was up) may
        # have written config — writing the snapshot captured before
        # the dialog would silently revert all of it.
        settings.patch({"_first_run_done": True})
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

    cfg = settings.read()
    generation = _profile_generation
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
        if generation != _profile_generation:
            return
        from aqt.qt import QFileDialog

        chosen = QFileDialog.getExistingDirectory(
            mw, "Choose a folder for your Klaus Library"
        )
        if not chosen:
            then()
            return

        def do(_col: Any) -> Any:
            from . import drive_store, settings

            folders = drive_store.load(settings.user_files()).get("pdfs", {})
            return pdf_handler.migrate_to_root(settings.user_files(), chosen, folders)

        def on_done(result: Any) -> None:
            if generation != _profile_generation:
                return
            settings.patch({"library_root": chosen})
            failed = (result or {}).get("failed") or {}
            if failed:
                tooltip(
                    f"Klaus: Library folder set. {len(failed)} file(s) "
                    "couldn't be moved and stay in the old location"
                )
            else:
                tooltip("Klaus: Library folder set")

        def on_fail(exc: Exception) -> None:
            if generation != _profile_generation:
                return
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
        if generation != _profile_generation:
            msg.deleteLater()
            return
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
    """Run on every profile open: offer the Library folder, then verify
    Klaus can actually embed — surfacing an actionable dialog only when
    it genuinely can't.

    The first profile open starts the runtime behind the welcome dialog
    without stacking another setup prompt. The ``_first_run_dialog_shown_this_session`` module flag
    tracks that — both hooks share the ``profile_did_open`` signal in
    registration order: first_run_check runs first, this runs second.
    """
    if _first_run_dialog_shown_this_session:
        _readiness_after_library_root()
        return

    # K-125: the Library-folder offer is callback-driven now, so the
    # provider checks run through its continuation — the old blocking
    # askUser ordered the two prompt families for free.
    generation = _profile_generation
    def after_library() -> None:
        if generation == _profile_generation:
            _readiness_after_library_root()
    _library_root_check(after_library)


# A generation fences callbacks belonging to a closed profile. The worker lock
# also keeps cleanup of a late startup ahead of the next profile's startup.
import threading
_profile_generation = 0
_runtime_worker_lock = threading.Lock()
_profile_runtime_cancel = threading.Event()


def runtime_lifetime() -> tuple[int, threading.Event]:
    """Capture on the main thread before scheduling profile-owned work."""
    return _profile_generation, _profile_runtime_cancel


def run_profile_runtime(
    lifetime: tuple[int, threading.Event],
    operation: Callable[[threading.Event], Any],
) -> Any:
    """Serialize startup and stale-worker cleanup across profile switches."""
    generation, cancel = lifetime
    with _runtime_worker_lock:
        if cancel.is_set() or generation != _profile_generation:
            return None
        try:
            result = operation(cancel)
        finally:
            # A helper can finish spawning while profile close sets cancel.
            # Clean up before releasing the lock to the next profile, also
            # when the old operation raises after starting its process.
            if generation != _profile_generation:
                from . import ollama_runtime
                ollama_runtime.server_manager.stop()
        return result if generation == _profile_generation else None


def stop_local_runtime() -> None:
    global _profile_generation, _profile_runtime_cancel
    _profile_runtime_cancel.set()
    _profile_generation += 1
    _profile_runtime_cancel = threading.Event()
    from . import ollama_runtime
    ollama_runtime.server_manager.stop()


def runtime_endpoint_saver(
    lifetime: tuple[int, threading.Event], starting_endpoint: Any,
) -> Callable[[dict], None]:
    """Persist automatic relocation only while its profile and endpoint match."""
    generation, cancel = lifetime

    def save_endpoint(updated: dict) -> None:
        endpoint = updated["endpoint"]

        def apply() -> None:
            if cancel.is_set() or generation != _profile_generation:
                return
            if settings.read().get("endpoint") != starting_endpoint:
                return
            # Read, compare and merge in this single main-thread callback:
            # settings.patch applies inline on the main thread, no gap.
            settings.patch({"endpoint": endpoint})

        mw.taskman.run_on_main(apply)

    return save_endpoint


def _readiness_after_library_root() -> None:
    from . import ollama_runtime
    cfg = settings.read()
    lifetime = runtime_lifetime()
    generation, _cancel = lifetime

    save_endpoint = runtime_endpoint_saver(lifetime, cfg.get("endpoint"))

    def start(_cancel: threading.Event) -> Any:
        if cfg.get("runtime_auto_setup", True):
            return ollama_runtime.ensure_server(dict(cfg), save_config=save_endpoint)
        from .ollama_setup import ollama_reachable
        return ollama_runtime.EnsureResult(
            "reachable" if ollama_reachable(str(cfg.get("endpoint") or "http://127.0.0.1:11434")) else "failed",
            str(cfg.get("endpoint") or "http://127.0.0.1:11434"),
        )

    def work(_col: Any) -> Any:
        return run_profile_runtime(lifetime, start)

    def done(result: Any) -> None:
        if generation != _profile_generation or result is None:
            return
        if _first_run_dialog_shown_this_session:
            return
        if result.status in ("reachable", "started"):
            _offer_v2_index_sweep(settings.read())
            _rematch_stale_matches()
            _resume_unindexed()
        else:
            _readiness_check_body()

    op = QueryOp(parent=mw, op=work, success=done)
    op.failure(lambda _exc: done(ollama_runtime.EnsureResult("failed", "")))
    op.without_collection().run_in_background()


def _resume_unindexed() -> None:
    """Queue every PDF that has text but no complete index (a batch the
    user never cancelled by hand, dropped by a failure or a restart)."""
    try:
        from . import index_queue

        index_queue.resume_unindexed()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] resume of unindexed PDFs failed: {exc}")


def _rematch_stale_matches() -> None:
    """K-302: re-match every PDF whose match cache predates the centered
    score scale, quietly (no embedding when its indexes are current). Runs
    the threshold-scale migration on the main thread first so the re-tag
    each job ends with uses the new thresholds. Self-healing, no flag: the
    re-match rewrites the cache at the current version."""
    try:
        from . import index_queue

        names = index_queue.stale_match_names()
        if names:
            index_queue.request([(index_queue.JOB_PDF, n) for n in names], announce=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] re-match after scoring change failed: {exc}")


def _offer_v2_index_sweep(cfg: dict) -> bool:
    """One-time upgrade offer: rebuild the PDF indexes pdf_index v2 left
    unreadable (K-236). True when it actually opened its confirm.

    A profile whose indexes predate v2 reads as having NO indexes at all
    — every Library row blank, the Lecture panel silent, every PDF
    invisible to the assistant — because an upgrade moves no embedding
    signature, so nothing else triggers a rebuild on its own.
    Preferences' Save shares this same trigger
    (``index_queue.offer_model_sweep``) and MAY re-offer while stale
    manifests remain; this profile-open call is the ONCE-per-profile
    one, gated on ``_v2_index_sweep_offered`` below — the flag is
    written whether the user said yes or no, because "no" to a priced
    whole-collection re-embed is an answer, not a snooze.

    Passing the CURRENT signature as ``previous`` is deliberate — it
    leaves the stale-manifest scan as the only trigger that can fire
    here, so this never doubles as a model-change prompt.
    """
    if cfg.get("_v2_index_sweep_offered"):
        return False
    try:
        from . import embeddings, index_queue

        if not index_queue.stale_index_names():
            return False  # nothing to upgrade — ask later if that changes
        if not index_queue.offer_model_sweep(
            mw, embeddings.index_signature(cfg)
        ):
            return False  # never asked (no profile, refused trigger) — no flag
    except Exception as exc:
        print(f"[klausmate] v2 index sweep offer failed: {exc}")
        return False
    settings.patch({"_v2_index_sweep_offered": True})
    return True


def _readiness_check_body() -> None:
    """Offer local setup after the background connection check fails."""
    generation = _profile_generation
    msg = _themed_message_box(mw, "KlausMate: local models", QMessageBox.Icon.Warning)
    msg.setText(LOCAL_MODELS_COPY)
    msg.setInformativeText("Start Ollama and make the selected embedding model available to enable semantic search.")
    manage_btn = msg.addButton("Local models", QMessageBox.ButtonRole.ActionRole)
    msg.addButton("Later", QMessageBox.ButtonRole.AcceptRole).setObjectName("SecondaryButton")

    def finished(_r: int) -> None:
        if generation == _profile_generation and msg.clickedButton() is manage_btn:
            manage_models_dialog()
        msg.deleteLater()

    msg.finished.connect(finished)
    msg.open()
