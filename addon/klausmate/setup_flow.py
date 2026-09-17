"""First-run welcome dialog and per-profile-open readiness checks.

Extracted verbatim from __init__.py (K-025, slice 3 of the K-006 file
split). Backs the one-time "Welcome to Klaus" dialog and the readiness
nudge that runs on every profile open thereafter.

Klaus is API-first since 2026-09-15 (K-226, spec D1): indexing runs on
OpenAI and the pertinence judge on Anthropic, both through the user's
own API keys (or one Klaus Plus key in place of both). The assistant is
the user's own Claude Code login and needs no key at all. There is no
local runtime to start, probe, download or update any more, so readiness
is one question — are those keys there — and the only other thing worth
surfacing on profile open is the Library folder.

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

from . import plus
from .manage_models import manage_models_dialog

# The two provider keys, each described to the user in exactly ONE
# place: what it buys, what stays dark without it, and the window title
# of the nudge that names it. KEYS_COPY and the per-case nudge are both
# built from this table, so the welcome dialog and the profile-open
# nudge can never describe setup two ways — and the nudge can never name
# a key it did not actually check (K-231: it listed both while readiness
# tested only the OpenAI one, so a user who pasted that key alone was
# told setup was done and met the first surprise at the judge).
KEY_COPY = {
    "api_key_openai": {
        "buys": "Indexing your cards and lecture pages uses OpenAI "
                "through your own API key.",
        "without": "semantic search and PDF study priorities won't "
                   "produce results",
        "title": "KlausMate: semantic search needs an API key",
    },
    "api_key_anthropic": {
        "buys": "Judging which of the matched cards a lecture page "
                "really covers uses Anthropic through your own API key.",
        "without": "Klaus indexes without the judging pass, so no card "
                   "is marked doubtful",
        "title": "KlausMate: judging lecture matches needs an API key",
    },
}

# One action sentence for every case — it never has to agree with how
# many keys are missing.
KEYS_ACTION = (
    "Add what's missing in KlausMate Preferences → API keys & models, or "
    "subscribe to Klaus Plus there and skip both keys. The assistant uses "
    "your own Claude Code login and needs no key."
)

# The fresh-install wording: both keys named. Every narrower case is
# this same copy with the keys that ARE set left out.
KEYS_COPY = " ".join([v["buys"] for v in KEY_COPY.values()] + [KEYS_ACTION])


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


def missing_keys(cfg: dict) -> list[str]:
    """Which provider keys are not set — ``[]`` when none is.

    A Klaus Plus key covers BOTH (K-246): the service holds the provider
    keys, so a subscriber has nothing to paste. Order follows KEY_COPY,
    which is the order the nudge names them in.

    This is a WORDING gate, never an entitlement check — nothing in
    Klaus is blocked on what it answers, and the service and the
    providers have the last word. It exists so the nudge says what it
    checked, nothing more.
    """
    if plus.key(cfg):
        return []
    return [k for k in KEY_COPY if not str((cfg or {}).get(k) or "").strip()]


def keys_missing_copy(cfg: dict) -> str:
    """KEYS_COPY narrowed to the keys actually missing; "" when none is.

    Derived from the same clauses KEYS_COPY is built from — never a
    second copy of the wording.
    """
    names = missing_keys(cfg)
    if not names:
        return ""
    return " ".join([KEY_COPY[n]["buys"] for n in names] + [KEYS_ACTION])


def _embedding_ready(cfg: dict) -> bool:
    """True if semantic search can actually run right now — the OpenAI
    key or a Klaus Plus subscription is present. Nothing to probe: a key
    is a string in config. The EMBEDDING half of readiness only; the
    judge's Anthropic key is reported by ``missing_keys`` and gates
    nothing here."""
    return "api_key_openai" not in missing_keys(cfg)


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

    # The same derived sentence the profile-open nudge shows, so the two
    # surfaces cannot describe setup two ways (K-231).
    missing_copy = keys_missing_copy(cfg)
    ready = not missing_copy

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
        "Everything Klaus needs is set up — you're ready to go."
        if ready
        else missing_copy
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
    cfg2 = _pkg().get_config()
    cfg2["_v2_index_sweep_offered"] = True
    _pkg().write_config(cfg2)
    return True


def _readiness_check_body() -> None:
    """The readiness dialog: one nudge, naming the keys that are missing.

    Silent when both are set (or one Klaus Plus key covers them), and
    silent again once the user has said "Later" — an API key is a
    one-time errand, not something to re-ask on every profile open
    (unlike the Library folder above, which has no such flag on
    purpose). One nudge and one flag for both keys, deliberately: a
    second dialog for the second key is a second thing to dismiss.

    It names WHAT IT CHECKED (K-231) and blocks nothing: readiness is a
    wording gate, and the service and the providers have the last word.
    """
    cfg = _pkg().get_config()
    if _embedding_ready(cfg) and _offer_v2_index_sweep(cfg):
        # Set up to embed, but carrying pre-v2 indexes that read as
        # absent — that confirm is now on screen, so the key nudge waits
        # for the next profile open rather than stacking on top of it.
        return
    missing = missing_keys(cfg)
    if not missing or cfg.get("_embed_key_setup_declined"):
        return

    msg = _themed_message_box(
        mw, KEY_COPY[missing[0]]["title"], QMessageBox.Icon.Warning
    )
    msg.setText(keys_missing_copy(cfg))
    msg.setInformativeText(
        "Until then, "
        + "; ".join(KEY_COPY[name]["without"] for name in missing)
        + "."
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
