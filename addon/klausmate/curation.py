"""Semantic deck curation — rank every card against one imported PDF.

Pipeline: keep the card index in sync (embeddings of every note) → bring
the PDF's own persistent chunk index up to date (retention.ensure_pdf_index)
→ score every card against it (retention.ensure_matches, cached in
matches.json) → cut at the PDF's sensitivity threshold
(retention.get_threshold) → tag the survivors for review in Browse, and
copy the confirmed set into a new deck (originals untouched).

This used to be a SEPARATE pipeline that re-read contexts/<pdf>.txt,
re-chunked it, sampled up to 128 chunks and embedded them live on every
run, discarding the vectors — while retention persisted up to 1000 chunks
of that identical text. One embed per PDF now serves both: curation is
just retention's ranked-match list, cut at the same per-PDF sensitivity
number the library slider and the !Library tags use. Curating a PDF that
isn't indexed yet indexes it first (retention.ensure_pdf_index is
unconditional) rather than failing.

Free-text prompts (the other half of the old pipeline) are gone along with
the Klaus panel that offered them — the sole caller (deck_curate.py) always
passes a ``pdf_name``.

aqt glue only — the vector math lives in card_index.py and the providers in
embeddings.py. Long work runs on QueryOp workers; the embedding phases run
``without_collection()`` so a 20-minute first index never blocks reviewing.

Preview vehicle: the PDF's own durable !Library tag (tag_sync.py, K-053)
— K-064 retired the ``!Library::Curating`` temp tag it used to stamp per
run; the per-PDF tag holds the identical set, and nid: search strings
(the tagless alternative) break at thousands of ids. The preview is
sequenced through ``tag_sync.sync_after_matches``'s ``on_done`` so Browse
never opens before the tag is written.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

import aqt
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

# Result of the most recent search (ranked nids, scores, suggested name) —
# consumed by the Browser action and the panel's "Create deck now".
last_run: dict | None = None

# ONE re-entrancy token for the WHOLE composed pipeline: card-index sync,
# PDF chunk-index sync (retention.ensure_pdf_index) and card/PDF matching
# (retention.ensure_matches) all check and hold THIS SAME flag — those two
# retention functions take a ``_reentrant`` kwarg so a caller composing
# several phases (run_curation below) acquires it exactly once instead of
# nesting acquisitions. Previously curation._busy and retention._busy were
# separate globals, the guard was one-way (ensure_index never checked
# retention's), and ensure_matches checked neither.
_busy = False

ProgressFn = Callable[[str, int, int], None]  # (label, done, total)


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _cfg() -> dict:
    return _pkg().get_config()


# ------------------------------------------------------------ pure helpers


def suggest_deck_name(pdf_name: str | None) -> str:
    """Deck-name suggestion: the PDF's basename, minus its extension."""
    base = os.path.basename(pdf_name or "").strip()
    for ext in (".txt", ".pdf"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
    return base[:60].strip() or "Curated"


def _escape_search(term: str) -> str:
    return term.replace("\\", "\\\\").replace('"', '\\"')


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

    ``_reentrant``: set by a caller (namely run_curation) that already holds
    ``_busy`` for a larger composed pipeline this is one phase of — skips
    the guard/release here so the single token is acquired exactly once.
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


# ---------------------------------------------------------------- search


def run_curation(
    parent,
    pdf_name: str | None = None,
    deck_scope: str | None = None,
    *,
    on_progress: ProgressFn | None = None,
    on_done: Callable[[dict], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Full curation pipeline: sync the card index, sync the PDF's own
    chunk index (indexing it first if it isn't yet), score every card
    against it, cut at the PDF's sensitivity threshold, then tag and
    preview the survivors in Browse.

    ``on_done(result)`` with ``{"nids", "scores", "suggested_name",
    "previewed"}``; the sync gives the PDF's own !Library tag exactly the
    matching notes and Browse opens on that tag — deck-scoped runs add
    deck:"..." so the preview shows the same cut this run used.

    Holds ``_busy`` for the WHOLE composed pipeline (card index, PDF index,
    matching, preview) as one token: each phase below is called with
    ``_reentrant=True`` so none of them re-acquires it.
    """
    global _busy
    if not pdf_name:
        _fail(on_error, ValueError("Pick a lecture PDF first."))
        return
    if _busy:
        _fail(on_error, RuntimeError("Klaus is already indexing — try again in a moment."))
        return
    _busy = True

    def release() -> None:
        global _busy
        _busy = False

    def fail(exc: Exception) -> None:
        release()
        _fail(on_error, exc)

    from . import retention  # deferred: retention.py imports this module at its top

    def after_card_index(index: card_index.CardIndex, completed: bool) -> None:
        if not completed:
            fail(RuntimeError("Indexing was cancelled — run the search again to resume."))
            return
        if not index.nids:
            fail(
                RuntimeError(
                    "No cards are indexed yet — add some notes, then re-index "
                    "from Manage models."
                )
            )
            return

        def scope(col) -> set[int] | None:
            if not deck_scope:
                return None
            return set(col.find_notes(f'deck:"{_escape_search(deck_scope)}"'))

        def after_scope(allowed: set[int] | None) -> None:
            def after_pdf_index(idx) -> None:
                if not idx.is_complete():
                    fail(
                        RuntimeError(
                            "Indexing was cancelled — run the search again to resume."
                        )
                    )
                    return
                retention.ensure_matches(
                    parent,
                    pdf_name,
                    on_progress=on_progress,
                    on_done=after_matches,
                    on_error=fail,
                    cancel=cancel,
                    _reentrant=True,
                )

            def after_matches(matches: list[tuple[int, float]]) -> None:
                if cancel is not None and cancel.is_set():
                    # match_scores stops early on cancel but still returns
                    # its partial list — never treat that as a final answer.
                    fail(RuntimeError("Search was cancelled — run it again to resume."))
                    return
                from . import tag_sync  # deferred: see run_curation's retention import above

                global last_run
                threshold = retention.get_threshold(pdf_name, retention._cfg())
                ranked = sorted(
                    (
                        (nid, score)
                        for nid, score in matches
                        if score >= threshold and (allowed is None or nid in allowed)
                    ),
                    key=lambda pair: pair[1],
                    reverse=True,
                )
                result = {
                    "nids": [nid for nid, _ in ranked],
                    "scores": [score for _, score in ranked],
                    "suggested_name": suggest_deck_name(pdf_name),
                    "previewed": False,
                }
                last_run = result
                if not ranked:
                    # Still sync: an empty cut must empty the tag too.
                    tag_sync.sync_after_matches(parent, pdf_name, matches)
                    release()
                    if on_done:
                        on_done(result)
                    return
                result["previewed"] = True

                def after_preview() -> None:
                    release()
                    if on_done:
                        on_done(result)

                # The preview SEARCHES the tag the sync writes, so it must
                # not race the sync op — on_done fires once the sync
                # settles (success, failure, or tags-disabled early-out).
                tag_sync.sync_after_matches(
                    parent,
                    pdf_name,
                    matches,
                    on_done=lambda: _preview_in_browse(
                        parent, pdf_name, deck_scope, after_preview
                    ),
                )

            retention.ensure_pdf_index(
                parent,
                pdf_name,
                on_progress=on_progress,
                on_done=after_pdf_index,
                on_error=fail,
                cancel=cancel,
                _reentrant=True,
            )

        op = QueryOp(parent=parent, op=scope, success=after_scope)
        op.failure(fail)
        op.run_in_background()

    ensure_index(
        parent,
        on_progress=on_progress,
        on_done=after_card_index,
        on_error=fail,
        cancel=cancel,
        _reentrant=True,
    )


# ------------------------------------------------------- preview & create


def _preview_in_browse(
    parent,
    pdf_name: str,
    deck_scope: str | None,
    after: Callable[[], None] | None,
) -> None:
    """Open Browse on the PDF's own !Library tag (no note mutation).

    Callers sequence this AFTER tag_sync.sync_after_matches settles, so
    the stored tag exists and already holds this run's matches. When no
    tag is stored (Library tags disabled), the preview is skipped rather
    than falling back to the retired temp-tag stamping — ``after`` always
    runs either way, because it releases the pipeline's busy token.
    """
    try:
        from . import tag_sync

        tag = tag_sync.get_stored_tag(tag_sync._safe(pdf_name))
        if tag:
            query = f'tag:"{tag}"'
            if deck_scope:
                query += f' deck:"{deck_scope}"'
            browser = aqt.dialogs.open("Browser", mw)
            browser.search_for(query)
        else:
            print(
                "[klausmate] curation preview skipped: no !Library tag "
                f"stored for {pdf_name!r} (Library tags disabled?)"
            )
    except Exception as exc:  # noqa: BLE001 - preview is best-effort
        print(f"[klausmate] curation preview failed: {exc}")
    if after:
        after()


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

    CollectionOp(parent=parent, op=op).success(done).run_in_background()


def prompt_and_create(parent, nids: list[int], on_done: Callable[[int], None] | None = None) -> None:
    """Name dialog (prefilled from the last search) → create the deck.

    Window-modal all the way down (K-125, K-114's rule: app-modal exec —
    which the getText/askUser statics run internally — segfaults on
    Qt 6.11 + macOS 26). The old while-loop's edges keep their meaning
    as a callback chain: cancel ends the flow, an emptied name
    re-prompts, and declining the merge re-prompts with the same name
    so it can be edited.
    """
    suggested = DECK_PREFIX + (
        (last_run or {}).get("suggested_name") or "Curated"
    )

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
    nids = list(browser.selected_notes())
    if not nids:
        # No selection → act on the last run's whole result set (K-064:
        # there is no temp preview tag to read back anymore).
        nids = list((last_run or {}).get("nids") or [])
    if not nids:
        tooltip("Select notes first (or run a Klaus search).", parent=browser)
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
