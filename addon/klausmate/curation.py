"""The CARD INDEX — one embedding per note — plus the manual deck copier.

**Two things live here, and K-146 cut the pipeline that joined them.**

1. ``ensure_index`` keeps ``user_files/card_index/`` in sync with the
   collection: diff notes against the index holding the collection
   (seconds), then embed and flush incrementally without it (possibly
   minutes). Everything that matches cards against a PDF reads this
   index, so whatever refreshes it decides how current matching is.
   ``index_queue._run`` (K-152) is the caller for every automatic and
   Library-driven index; Preferences' **Index Now** is the one other,
   with its own progress bar. See the note on ``ensure_index`` itself
   before adding a third.
2. ``prompt_and_create`` / ``create_curated_deck`` copy a set of notes
   into a new deck as one undoable step, driven by the Browse Notes-menu
   action ``setup_hooks`` registers. Deck-scope free, PDF-free: you
   select notes, you name a deck, they are copied.

What K-146 removed was ``run_curation``, which chained phase 1 into
retention's PDF index + matching and then opened Browse on the per-PDF
!Library tag. Every step of that survives elsewhere — indexing writes
the tag (``tag_sync.sync_after_matches``), the Library opens it ("Show
Matched Cards in Browse") — so the chain was ceremony. Its one
irreplaceable side effect was calling ``ensure_index``, which moved to
``pdf_drive._on_embed`` rather than disappearing with it — and moved
again in K-152, into ``index_queue``, when that chain had to serve a PDF
added from the deck screen with no Library window in sight.

The module is NOT dead weight even beyond those two: retention.py imports
it at module top for USER_FILES/INDEX_DIR/_cfg/_fail and, above all, for
``_busy`` — the ONE re-entrancy token every embedding phase in the addon
holds. manage_models, tag_sync and pdf_map read from it too.

aqt glue only — the vector math lives in card_index.py and the providers in
embeddings.py. Long work runs on QueryOp workers; the embedding phases run
``without_collection()`` so a 20-minute first index never blocks reviewing.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

from anki.collection import AddNoteRequest
from aqt import gui_hooks, mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QAction, QInputDialog, QMessageBox, qconnect
from aqt.utils import showWarning, tooltip

from . import card_index, embeddings

ADDON_DIR = os.path.dirname(__file__)
USER_FILES = os.path.join(ADDON_DIR, "user_files")
INDEX_DIR = os.path.join(USER_FILES, "card_index")

CURATED_TAG = "!Library::Curated"
DECK_PREFIX = "Klaus::"

PARTIAL_FLUSH_EVERY = 1024  # vectors between saves — cancel/crash resume point
_FIELD_SEP = "\x1f"  # anki notes.flds separator

# ONE re-entrancy token for every embedding phase in the addon: card-index
# sync (ensure_index below), PDF chunk-index sync
# (retention.ensure_pdf_index) and card/PDF matching
# (retention.ensure_matches) all check and hold THIS SAME flag. Previously
# curation._busy and retention._busy were separate globals, the guard was
# one-way (ensure_index never checked retention's), and ensure_matches
# checked neither.
#
# The ``_reentrant`` kwarg those functions carry let ONE caller hold the
# token across several phases; K-146 removed that caller (run_curation).
# index_queue._run composes the same phases but lets each take the token
# in turn, because its cancellation branches return without a release
# and a held token would leak, bricking indexing for the session — see
# that module's docstring. Serialisation across JOBS is the queue there,
# never this flag: this flag REFUSES, and refusing ten dropped PDFs is
# the wrong answer to a legitimate batch.
_busy = False

ProgressFn = Callable[[str, int, int], None]  # (label, done, total)


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _cfg() -> dict:
    return _pkg().get_config()


# ------------------------------------------------------------ pure helpers


def index_stats() -> dict:
    """Cheap status for the panel line — manifest only, no vector load."""
    return card_index.stats_from_disk(INDEX_DIR)


# ---------------------------------------------------------- index pipeline


def _snapshot_with_col(col, force_rebuild: bool):
    """Phase A (holds col, ~seconds): diff the collection against the index."""
    cfg = _cfg()
    sig = embeddings.index_signature(cfg)
    index = None if force_rebuild else card_index.load(INDEX_DIR)
    if index is not None and not card_index.check_signature(index, sig):
        index = None  # provider/model changed → full rebuild
    rows = col.db.all("select id, mod, flds from notes")
    mods = {int(r[0]): int(r[1]) for r in rows}
    flds = {int(r[0]): str(r[2]) for r in rows}
    strip = _pkg()._strip_html

    def text_fn(nid: int) -> str:
        return card_index.note_text(flds[nid].split(_FIELD_SEP), strip)

    plan = card_index.plan_sync(index, mods, text_fn)
    return index, plan, sig


def _embed_plan(index, plan, sig, on_progress, cancel):
    """Phase B (no col, possibly minutes): embed + flush incrementally.

    Returns (new_index, completed). Partial saves every ~1k vectors mean a
    cancel/crash resumes from the last flush on the next run.
    """
    todo = plan.to_embed
    texts = [t for (_, _, _, t) in todo]
    total = len(texts)
    embedded: dict[int, Any] = {}
    provider = embeddings.provider_from_config(_cfg)
    since_flush = 0
    for offset, vecs in embeddings.embed_batches(provider, texts, cancel=cancel):
        for j, vec in enumerate(vecs):
            embedded[todo[offset + j][0]] = vec
        since_flush += len(vecs)
        if on_progress:
            done = len(embedded)
            mw.taskman.run_on_main(
                lambda d=done: on_progress("Embedding cards…", d, total)
            )
        if since_flush >= PARTIAL_FLUSH_EVERY:
            card_index.save(card_index.apply_sync(index, plan, embedded, sig), INDEX_DIR)
            since_flush = 0
    new_index = card_index.apply_sync(index, plan, embedded, sig)
    card_index.save(new_index, INDEX_DIR)
    return new_index, len(embedded) == total


def ensure_index(
    parent,
    *,
    force_rebuild: bool = False,
    on_progress: ProgressFn | None = None,
    on_done: Callable[[card_index.CardIndex, bool], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    cancel: threading.Event | None = None,
    _reentrant: bool = False,
) -> None:
    """Bring the card index up to date. All callbacks fire on main thread.

    ``on_done(index, completed)`` — completed False means cancelled mid-way
    (the partial index is saved; the next run resumes).

    **This is how fresh matching stays fresh.** Every note added or edited
    since the last pass is invisible to ``retention.ensure_matches`` until
    this runs, and the failure is SILENT: no error, just a per-PDF
    !Library tag that under-covers. Until K-146 the only user-facing
    caller was ``run_curation`` behind the curate button; removing that
    button without moving this call was the one way to turn that card
    into a regression. Since K-152 it is phase one of ``index_queue``'s
    chain, which every index request — an added PDF, the Library's
    Update/Add to Search Index, a model-change sweep — runs through.
    Anything new that matches cards against a PDF belongs in that chain
    rather than calling this directly.

    Preferences' **Index Now** is the one deliberate exception: it wants
    the card index alone, with its own progress bar and cancel button.
    That is why ``index_queue`` WAITS on ``_busy`` (``_busy_elsewhere``)
    instead of racing it — a PDF dropped mid-Index-Now would otherwise
    be refused here and take a whole queued batch down as a "failure"
    the user never caused.

    ``_reentrant``: for a caller that already holds ``_busy`` across a
    larger composed pipeline this is one phase of — skips the
    guard/release here so the single token is acquired exactly once.
    No caller sets it today (see ``_busy``); the kwarg stays because
    retention's two phases carry the matching one.
    """
    global _busy
    if not _reentrant:
        if _busy:
            _fail(on_error, RuntimeError("Klaus is already indexing — try again in a moment."))
            return
        _busy = True

    def release() -> None:
        global _busy
        if not _reentrant:
            _busy = False

    def finish_err(exc: Exception) -> None:
        release()
        _fail(on_error, exc)

    def phase_b(snap) -> None:
        index, plan, sig = snap
        if plan.is_noop() and index is not None:
            # Nothing changed at all — skip the worker round-trip.
            release()
            if on_done:
                on_done(index, True)
            return
        if on_progress and plan.to_embed:
            on_progress("Embedding cards…", 0, len(plan.to_embed))

        def do_embed(_col=None):
            return _embed_plan(index, plan, sig, on_progress, cancel)

        def done(result) -> None:
            release()
            new_index, completed = result
            if on_done:
                on_done(new_index, completed)

        op = QueryOp(parent=parent, op=lambda col: do_embed(), success=done)
        op.failure(finish_err)
        op.without_collection().run_in_background()

    if on_progress:
        on_progress("Scanning your notes…", 0, 0)
    op = QueryOp(
        parent=parent,
        op=lambda col: _snapshot_with_col(col, force_rebuild),
        success=phase_b,
    )
    op.failure(finish_err)
    op.run_in_background()


def _fail(on_error, exc: Exception) -> None:
    if on_error:
        on_error(exc)
        return
    if isinstance(exc, embeddings.EmbeddingError):
        showWarning("Klaus semantic search failed.\n\n" + exc.user_message())
    elif isinstance(exc, (RuntimeError, ValueError)):
        showWarning(str(exc))
    else:
        showWarning(f"Klaus semantic search failed.\n\n{type(exc).__name__}: {exc}")


# --------------------------------------------------- the deck copier


def create_curated_deck(
    parent,
    nids: list[int],
    deck_name: str,
    on_done: Callable[[int], None] | None = None,
) -> None:
    """Copy ``nids`` into ``deck_name`` as one undoable operation.

    True copies: fresh notes (new guid) with the source's notetype, fields,
    and tags (plus ``!Library::Curated``; since K-064 there is no temp tag
    to strip — copies keep the per-PDF !Library tag, which is accurate:
    they match the PDF too). Scheduling starts fresh — these are new cards.
    """

    def op(col):
        pos = col.add_custom_undo_entry(f"Klaus: create deck “{deck_name}”")
        did = col.decks.id(deck_name)
        requests = []
        for nid in nids:
            src = col.get_note(nid)
            new = col.new_note(src.note_type())
            new.fields = list(src.fields)
            tags = list(src.tags)
            if CURATED_TAG not in tags:
                tags.append(CURATED_TAG)
            new.tags = tags
            requests.append(AddNoteRequest(note=new, deck_id=did))
        col.add_notes(requests)
        return col.merge_undo_entries(pos)

    def done(_changes) -> None:
        tooltip(
            f"Created “{deck_name}” with {len(nids)} notes (Ctrl+Z to undo)",
            parent=parent,
            period=5000,
        )
        if on_done:
            on_done(len(nids))

    # Progress on mw (K-319): closing Browse within Anki's 600 ms progress
    # delay would otherwise delete the progress window before it shows.
    CollectionOp(parent=mw, op=op).success(done).run_in_background()


def prompt_and_create(parent, nids: list[int], on_done: Callable[[int], None] | None = None) -> None:
    """Name dialog → create the deck.

    The prefill used to come from ``last_run``, the ranked result of the
    curate button's search; K-146 removed both. This flow is reached
    only from Browse with notes SELECTED, where there is no PDF and no
    search to name a deck after, so the prefill is the bare prefix.

    Window-modal all the way down (K-125, K-114's rule: app-modal exec —
    which the getText/askUser statics run internally — segfaults on
    Qt 6.11 + macOS 26). The old while-loop's edges keep their meaning
    as a callback chain: cancel ends the flow, an emptied name
    re-prompts, and declining the merge re-prompts with the same name
    so it can be edited.
    """
    suggested = DECK_PREFIX + "Curated"

    def ask_name(prefill: str) -> None:
        dlg = QInputDialog(parent)
        dlg.setWindowTitle("Klaus: create curated deck")
        dlg.setLabelText(f"Copy {len(nids)} notes into deck:")
        dlg.setTextValue(prefill)
        try:
            from . import theme

            dlg.setStyleSheet(theme.dialog_qss(theme.night_mode()))
        except Exception:
            pass
        dlg.textValueSelected.connect(on_named)
        dlg.finished.connect(lambda _r: dlg.deleteLater())
        dlg.open()

    def on_named(raw: Any) -> None:
        name = str(raw or "").strip()
        if not name:
            ask_name(name)  # the old loop's continue: empty re-prompts
            return
        if mw.col.decks.by_name(name):
            confirm_merge(name)
            return
        create_curated_deck(parent, nids, name, on_done=on_done)

    def confirm_merge(name: str) -> None:
        msg = QMessageBox(parent)
        msg.setWindowTitle("Klaus: create curated deck")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            f'Deck "{name}" already exists. Add the {len(nids)} copied '
            "notes to it?"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        # askUser(defaultno=True) parity; No is the quiet secondary.
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        no_btn = msg.button(QMessageBox.StandardButton.No)
        if no_btn is not None:
            no_btn.setObjectName("SecondaryButton")
        try:
            from . import theme

            msg.setStyleSheet(theme.dialog_qss(theme.night_mode()))
        except Exception:
            pass

        def _on_answered(_r: int) -> None:
            clicked = msg.clickedButton()
            merge = (
                clicked is not None
                and msg.standardButton(clicked)
                == QMessageBox.StandardButton.Yes
            )
            msg.deleteLater()
            if merge:
                create_curated_deck(parent, nids, name, on_done=on_done)
            else:
                ask_name(name)  # decline re-prompts, same name, editable

        msg.finished.connect(_on_answered)
        msg.open()

    ask_name(suggested)


# ------------------------------------------------------------ browser glue


def _create_from_browser(browser) -> None:
    """Copy the selected notes into a new deck.

    Selection is the whole input now. It used to fall back to
    ``last_run``'s result set when nothing was selected — the curate
    button's most recent search — and K-146 removed that search, so an
    empty selection has nothing to mean. Browse's own search IS how you
    pick the notes: tag:!Library::… for one PDF's matches, anything else
    for anything else.
    """
    nids = list(browser.selected_notes())
    if not nids:
        tooltip("Select the notes to copy first.", parent=browser)
        return
    prompt_and_create(browser, nids)


def on_browser_menus_did_init(browser) -> None:
    action = QAction("KlausMate: Create Curated Deck from Selection…", browser)
    qconnect(action.triggered, lambda: _create_from_browser(browser))
    menu = getattr(browser.form, "menu_Notes", None) or browser.form.menuEdit
    menu.addSeparator()
    menu.addAction(action)


def setup_hooks() -> None:
    gui_hooks.browser_menus_did_init.append(on_browser_menus_did_init)
