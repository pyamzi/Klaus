"""First-run welcome dialog and per-profile-open readiness checks.

Extracted verbatim from __init__.py (K-025, slice 3 of the K-006 file
split). Backs the one-time "Welcome to Klaus" dialog and the readiness
nudge that runs on every profile open thereafter.

Klaus is API-first since 2026-09-15 (K-226, spec D1): semantic search
runs on OpenAI and the assistant on Anthropic, both through the user's
own API keys. There is no local runtime to start, probe, download or
update any more, so readiness is one question — is the key there — and
the only other thing worth surfacing on profile open is the Library
folder.

This module is imported by __init__.py at package load time, so it must
never import __init__ (this package) at module load — only from inside a
function, after the package has finished loading. _pkg() below is that
lazy accessor (same pattern as manage_models.py's and browse_toggles.py's
_pkg()); it reaches config and dialog helpers that still live in
__init__.py: get_config, write_config, open_settings_dialog.
"""

from __future__ import annotations

from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import QMessageBox, QTimer
from aqt.utils import showWarning, tooltip

from .manage_models import manage_models_dialog

# The one place the two keys are named for the user. Both readiness
# surfaces below quote it, so the welcome dialog and the profile-open
# nudge can never describe setup two ways.
KEYS_COPY = (
    "Semantic search and the assistant use OpenAI and Anthropic through "
    "your own API keys. Add them in KlausMate Preferences → API keys & "
    "models."
)


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
    """True if semantic search can actually run right now — the OpenAI
    key is present. Nothing to probe: a key is a string in config."""
    return bool(str(cfg.get("api_key_openai") or "").strip())


def first_run_check() -> None:
    """Welcome dialog shown once per profile.

    Always shows the how-to bullets (PDF sidebar, semantic search) so the
    user knows the feature surface — not just when something needs setup.
    The readiness line and follow-up buttons say whether the API keys are
    in place yet.
    """
    global _first_run_dialog_shown_this_session
    # Reset each profile-open so profile switches re-evaluate cleanly.
    _first_run_dialog_shown_this_session = False
    cfg = _pkg().get_config()
    if cfg.get("_first_run_done"):
        return
    _first_run_dialog_shown_this_session = True

    ready = _embedding_ready(cfg)

    body_lines = [
        "Klaus adds a PDF workspace and semantic search to Anki.",
        "",
        "• The PDF sidebar lets you read a lecture PDF, highlight it, and "
        "keep it open next to your cards.",
        "• Semantic search finds the cards each lecture PDF covers, tags "
        "them, and scores how well you still recall them.",
        "",
    ]
    body_lines.append(
        "Semantic search runs on your OpenAI key — you're ready to go."
        if ready
        else KEYS_COPY
    )

    msg = _themed_message_box(mw, "Welcome to Klaus", QMessageBox.Icon.Information)
    msg.setText("\n".join(body_lines))
    if ready:
        # "OK" is the primary/dismissive action here — stays default blue.
        msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        manage_btn = msg.addButton(
            "KlausMate Preferences", QMessageBox.ButtonRole.ActionRole
        )
        manage_btn.setObjectName("SecondaryButton")
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
        if clicked is manage_btn:
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
    """Run on every profile open: offer the Library folder, then verify
    Klaus can actually embed — surfacing an actionable dialog only when
    it genuinely can't.

    Skipped on the very first profile open because ``first_run_check``
    already showed the welcome dialog (which itself includes setup
    guidance). The ``_first_run_dialog_shown_this_session`` module flag
    tracks that — both hooks share the ``profile_did_open`` signal in
    registration order: first_run_check runs first, this runs second.
    """
    if _first_run_dialog_shown_this_session:
        return

    # K-125: the Library-folder offer is callback-driven now, so the
    # provider checks run through its continuation — the old blocking
    # askUser ordered the two prompt families for free.
    _library_root_check(_readiness_after_library_root)


def _readiness_after_library_root() -> None:
    """The provider-readiness half of setup_readiness_check, chained
    behind the Library-folder offer's continuation (K-125).

    A pass-through since K-226 — the silent local-runtime start and the
    once-per-version runtime update offer that used to sit here went
    with the runtime. Kept as the named continuation so the chain reads
    the same and a future async step has a place to land.
    """
    _readiness_check_body()


def _offer_v2_index_sweep(cfg: dict) -> None:
    """One-time upgrade offer: rebuild the PDF indexes pdf_index v2 left
    unreadable (K-236).

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
        return
    try:
        from . import embeddings, index_queue

        if not index_queue.stale_index_names():
            return  # nothing to upgrade — ask later if that changes
        if not index_queue.offer_model_sweep(
            mw, embeddings.index_signature(cfg)
        ):
            return  # never asked (no profile, refused trigger) — no flag
    except Exception as exc:
        print(f"[klausmate] v2 index sweep offer failed: {exc}")
        return
    cfg2 = _pkg().get_config()
    cfg2["_v2_index_sweep_offered"] = True
    _pkg().write_config(cfg2)


def _readiness_check_body() -> None:
    """The readiness dialog: one nudge when the OpenAI key is missing.

    Silent when the key is set, and silent again once the user has said
    "Later" — an API key is a one-time errand, not something to re-ask
    on every profile open (unlike the Library folder above, which has no
    such flag on purpose).
    """
    cfg = _pkg().get_config()
    if _embedding_ready(cfg):
        # Set up, but possibly carrying pre-v2 indexes that now read as
        # absent — the one thing left worth asking about.
        _offer_v2_index_sweep(cfg)
        return
    if cfg.get("_embed_key_setup_declined"):
        return

    msg = _themed_message_box(
        mw, "KlausMate: semantic search needs an API key", QMessageBox.Icon.Warning
    )
    msg.setText(KEYS_COPY)
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
