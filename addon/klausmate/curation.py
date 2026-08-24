"""Semantic deck curation — the Klaus panel's one job.

Pipeline: keep the card index in sync (embeddings of every note), embed the
user's prompt and/or lecture PDF, rank every card against those query
vectors, tag the best matches for review in Browse, and copy the confirmed
set into a new deck (originals untouched).

aqt glue only — the vector math lives in card_index.py and the providers in
embeddings.py. Long work runs on QueryOp workers; the embedding phase runs
``without_collection()`` so a 20-minute first index never blocks reviewing.

Preview vehicle: the temp tag ``!Library::Curating`` (nid: search strings
break at thousands of ids). Tagging bumps note.mod, which is exactly why
the card index diffs by text hash — see card_index.py.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

import aqt
from anki.collection import AddNoteRequest
from aqt import gui_hooks, mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QAction, QInputDialog, qconnect
from aqt.utils import askUser, showWarning, tooltip

from . import card_index, embeddings, pdf_handler

ADDON_DIR = os.path.dirname(__file__)
USER_FILES = os.path.join(ADDON_DIR, "user_files")
INDEX_DIR = os.path.join(USER_FILES, "card_index")

TEMP_TAG = "!Library::Curating"
CURATED_TAG = "!Library::Curated"
DECK_PREFIX = "Klaus::"

PARTIAL_FLUSH_EVERY = 1024  # vectors between saves — cancel/crash resume point
MAX_QUERY_CHUNKS = 128
_FIELD_SEP = "\x1f"  # anki notes.flds separator

DEFAULT_TOP_K = 100
DEFAULT_MIN_SCORE = 0.35

# Result of the most recent search (ranked nids, scores, suggested name) —
# consumed by the Browser action and the panel's "Create deck now".
last_run: dict | None = None

_busy = False  # one index/search pipeline at a time (main-thread flag)

ProgressFn = Callable[[str, int, int], None]  # (label, done, total)


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _cfg() -> dict:
    return _pkg().get_config()


# ------------------------------------------------------------ pure helpers


def suggest_deck_name(prompt: str, pdf_name: str | None) -> str:
    """Deck-name suggestion: PDF basename, else a word-cut prompt prefix."""
    if pdf_name:
        base = os.path.basename(pdf_name)
        for ext in (".txt", ".pdf"):
            if base.lower().endswith(ext):
                base = base[: -len(ext)]
        base = base.strip()
        if base:
            return base[:60].strip()
    p = " ".join((prompt or "").split())
    if len(p) > 48:
        cut = p[:48].rsplit(" ", 1)[0]
        p = (cut if cut else p[:48]).rstrip() + "…"
    return p or "Curated"


def stride_sample(items: list, cap: int = MAX_QUERY_CHUNKS) -> list:
    """Evenly sample ``cap`` items, keeping document order."""
    if len(items) <= cap:
        return list(items)
    step = len(items) / cap
    return [items[int(i * step)] for i in range(cap)]


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
) -> None:
    """Bring the card index up to date. All callbacks fire on main thread.

    ``on_done(index, completed)`` — completed False means cancelled mid-way
    (the partial index is saved; the next run resumes).
    """
    global _busy
    if _busy:
        _fail(on_error, RuntimeError("Klaus is already indexing — try again in a moment."))
        return
    _busy = True

    def finish_err(exc: Exception) -> None:
        global _busy
        _busy = False
        _fail(on_error, exc)

    def phase_b(snap) -> None:
        global _busy
        index, plan, sig = snap
        if plan.is_noop() and index is not None:
            # Nothing changed at all — skip the worker round-trip.
            _busy = False
            if on_done:
                on_done(index, True)
            return
        if on_progress and plan.to_embed:
            on_progress("Embedding cards…", 0, len(plan.to_embed))

        def do_embed(_col=None):
            return _embed_plan(index, plan, sig, on_progress, cancel)

        def done(result) -> None:
            global _busy
            _busy = False
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


def _query_texts(prompt: str, pdf_name: str | None) -> tuple[list[str], str | None]:
    """Prompt and/or evenly-sampled PDF chunks → query strings."""
    texts: list[str] = []
    p = (prompt or "").strip()
    if p:
        texts.append(p)
    err = None
    if pdf_name:
        base = pdf_name if pdf_name.endswith(".txt") else pdf_name + ".txt"
        path = os.path.join(USER_FILES, "contexts", os.path.basename(base))
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            chunks = pdf_handler._chunk_text(raw, source=pdf_name)
            texts.extend(c["text"] for c in stride_sample(chunks))
        except OSError:
            err = f"Could not read the lecture PDF context “{pdf_name}”."
    return texts, err


def run_curation(
    parent,
    prompt: str = "",
    pdf_name: str | None = None,
    deck_scope: str | None = None,
    *,
    preview: bool = True,
    on_progress: ProgressFn | None = None,
    on_done: Callable[[dict], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Full search pipeline: sync index → embed query → rank → preview.

    ``on_done(result)`` with ``{"nids", "scores", "suggested_name",
    "previewed"}``; with ``preview`` the matches are tagged
    ``!Library::Curating`` and Browse opens on that tag (membership is
    ranked; row order in Browse follows the user's sort).
    """
    if not (prompt or "").strip() and not pdf_name:
        _fail(on_error, ValueError("Type a topic or pick a lecture PDF first."))
        return

    cfg = _cfg()
    top_n = int(cfg.get("curate_top_k") or DEFAULT_TOP_K)
    min_score = float(cfg.get("curate_min_score") or DEFAULT_MIN_SCORE)

    def after_index(index: card_index.CardIndex, completed: bool) -> None:
        if not completed:
            _fail(
                on_error,
                RuntimeError("Indexing was cancelled — run the search again to resume."),
            )
            return
        if not index.nids:
            _fail(
                on_error,
                RuntimeError(
                    "No cards are indexed yet — add some notes, then re-index "
                    "from Manage models."
                ),
            )
            return

        def scope(col) -> set[int] | None:
            if not deck_scope:
                return None
            return set(col.find_notes(f'deck:"{_escape_search(deck_scope)}"'))

        def rank(allowed: set[int] | None) -> None:
            if on_progress:
                on_progress("Searching…", 0, 0)

            def do_rank(_col=None) -> dict:
                texts, err = _query_texts(prompt, pdf_name)
                if err:
                    raise RuntimeError(err)
                if not texts:
                    raise RuntimeError("Nothing to search with — the PDF context is empty.")
                provider = embeddings.provider_from_config(_cfg)
                qvecs = []
                for _off, vecs in embeddings.embed_batches(
                    provider, texts, cancel=cancel, kind="query"
                ):
                    qvecs.extend(v for v in vecs if v is not None)
                if cancel is not None and cancel.is_set():
                    return {"cancelled": True}
                if not qvecs:
                    raise RuntimeError("Could not embed the search query.")
                ranked = card_index.top_k(
                    index, qvecs, top_n, allowed=allowed, min_score=min_score
                )
                return {"ranked": ranked, "cancelled": False}

            def ranked_done(out: dict) -> None:
                global last_run
                if out.get("cancelled"):
                    return
                ranked = out["ranked"]
                result = {
                    "nids": [nid for nid, _ in ranked],
                    "scores": [score for _, score in ranked],
                    "suggested_name": suggest_deck_name(prompt, pdf_name),
                    "previewed": False,
                }
                last_run = result
                if not ranked:
                    if on_done:
                        on_done(result)
                    return
                if preview:
                    result["previewed"] = True
                    _preview_in_browse(parent, result["nids"], lambda: on_done and on_done(result))
                else:
                    if on_done:
                        on_done(result)

            op = QueryOp(parent=parent, op=lambda col: do_rank(), success=ranked_done)
            op.failure(lambda exc: _fail(on_error, exc))
            op.without_collection().run_in_background()

        op = QueryOp(parent=parent, op=scope, success=rank)
        op.failure(lambda exc: _fail(on_error, exc))
        op.run_in_background()

    ensure_index(
        parent,
        on_progress=on_progress,
        on_done=after_index,
        on_error=on_error,
        cancel=cancel,
    )


# ------------------------------------------------------- preview & create


def _preview_in_browse(parent, nids: list[int], after: Callable[[], None] | None) -> None:
    """Swap the temp tag onto the new result set, then open Browse on it."""

    def op(col):
        pos = col.add_custom_undo_entry("Klaus: preview curation matches")
        stale = col.find_notes(f'tag:"{TEMP_TAG}"')
        if stale:
            col.tags.bulk_remove(list(stale), TEMP_TAG)
        col.tags.bulk_add(list(nids), TEMP_TAG)
        return col.merge_undo_entries(pos)

    def done(_changes) -> None:
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(f'tag:"{TEMP_TAG}"')
        if after:
            after()

    CollectionOp(parent=parent, op=op).success(done).run_in_background()


def clear_curation_tag(parent=None, *, quiet: bool = False) -> None:
    """Tools-menu escape hatch: drop the preview tag from every note.

    ``quiet`` suppresses this function's own tooltip (both the "nothing to
    clear" early-out and the success summary) — for a caller that reports
    its own combined result instead. Default False keeps every existing
    caller's behavior unchanged.
    """
    parent = parent or mw
    nids = mw.col.find_notes(f'tag:"{TEMP_TAG}"') if mw.col else []
    if not nids:
        if not quiet:
            tooltip("No notes carry the Klaus curation tag.", parent=parent)
        return

    def op(col):
        pos = col.add_custom_undo_entry("Klaus: clear curation tag")
        col.tags.bulk_remove(list(nids), TEMP_TAG)
        return col.merge_undo_entries(pos)

    op_result = CollectionOp(parent=parent, op=op)
    if not quiet:
        op_result = op_result.success(
            lambda _c: tooltip(f"Cleared the curation tag from {len(nids)} notes.", parent=parent)
        )
    op_result.run_in_background()


def create_curated_deck(
    parent,
    nids: list[int],
    deck_name: str,
    on_done: Callable[[int], None] | None = None,
) -> None:
    """Copy ``nids`` into ``deck_name`` as one undoable operation.

    True copies: fresh notes (new guid) with the source's notetype, fields,
    and tags (minus the temp tag, plus ``!Library::Curated``). Source notes
    lose the temp tag. Scheduling starts fresh — these are new cards.
    """

    def op(col):
        pos = col.add_custom_undo_entry(f"Klaus: create deck “{deck_name}”")
        did = col.decks.id(deck_name)
        requests = []
        for nid in nids:
            src = col.get_note(nid)
            new = col.new_note(src.note_type())
            new.fields = list(src.fields)
            tags = [t for t in src.tags if t.lower() != TEMP_TAG.lower()]
            if CURATED_TAG not in tags:
                tags.append(CURATED_TAG)
            new.tags = tags
            requests.append(AddNoteRequest(note=new, deck_id=did))
        col.add_notes(requests)
        col.tags.bulk_remove(list(nids), TEMP_TAG)
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
    """Name dialog (prefilled from the last search) → create the deck."""
    suggested = DECK_PREFIX + (
        (last_run or {}).get("suggested_name") or "Curated"
    )
    name = suggested
    while True:
        name, ok = QInputDialog.getText(
            parent,
            "Klaus: create curated deck",
            f"Copy {len(nids)} notes into deck:",
            text=name,
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            continue
        if mw.col.decks.by_name(name):
            if askUser(
                f'Deck "{name}" already exists. Add the {len(nids)} copied '
                "notes to it?",
                parent=parent,
                defaultno=True,
            ):
                break
            continue  # re-prompt for a different name
        break
    create_curated_deck(parent, nids, name, on_done=on_done)


# ------------------------------------------------------------ browser glue


def _create_from_browser(browser) -> None:
    nids = list(browser.selected_notes())
    if not nids:
        # No selection → act on the whole preview set.
        nids = list(mw.col.find_notes(f'tag:"{TEMP_TAG}"'))
    if not nids:
        tooltip("Select notes first (or run a Klaus search).", parent=browser)
        return
    prompt_and_create(browser, nids)


def on_browser_menus_did_init(browser) -> None:
    action = QAction("Klaus: Create curated deck from selection…", browser)
    qconnect(action.triggered, lambda: _create_from_browser(browser))
    menu = getattr(browser.form, "menu_Notes", None) or browser.form.menuEdit
    menu.addSeparator()
    menu.addAction(action)


def setup_hooks() -> None:
    gui_hooks.browser_menus_did_init.append(on_browser_menus_did_init)
