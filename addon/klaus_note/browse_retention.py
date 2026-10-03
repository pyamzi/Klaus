"""A "Retention" column in Anki's Browse table (K-147).

Pouya's ask: "in the browse panel, add the retention % column as well." The
Library already ranks whole PDFs by retention; this puts the same number on
the individual rows of Browse, so a search can be read for study triage
without leaving the browser.

Two real Anki hooks carry the whole feature (contracts verified against
26.8.1's ``_aqt/hooks.pyc``, not guessed):

* ``browser_did_fetch_columns(columns: dict[str, Column])`` — "Allows you to
  add custom columns to the browser. ... Every column in the dictionary will
  be toggleable by the user." So the column ships INVISIBLE and the user
  turns it on from Browse's own right-click column menu; there is no Klaus
  config key for it, and no design gate — this is a functional injection
  (lecture_view's rule), not KlausBook chrome.
* ``browser_did_fetch_row(card_or_note_id, is_note, row: CellRow,
  columns: Sequence[str])`` — "Any columns the backend did not recognize
  will be returned as an empty string, and can be replaced with custom
  content." Our key is unknown to the Rust backend by construction, so the
  cell always arrives blank and we fill it in.

NOT SORTABLE, and the tooltips say so. ``sorting_cards``/``sorting_notes``
are ``SORTING_NONE`` because sorting happens in the backend's SQL, which has
never heard of this column; clicking its header does nothing. Claiming
otherwise (by declaring a sort order the backend cannot honour) would make
the header lie.

PER-ROW COST is the design constraint. ``browser_did_fetch_row`` fires once
per *rendered* row, on the UI thread, during scrolling — so this module
reads exactly the row's own card(s) through an index and nothing else:

* cards mode  → ``where id = ?``  on the primary key
* notes mode  → ``where nid = ?`` on ``ix_cards_nid``

Measured on Pouya's collection (35,095 cards / 28,670 notes, read-only):
**2.8 µs per cards-mode row, 3.1 µs per notes-mode row**, so a ~60-row
viewport costs well under a millisecond. The tempting shortcut —
``retention.card_retrievability(col, nids)`` — is a FULL collection scan
(11.5 ms) plus a ``revlog`` group-by (13.9 ms): ~25 ms *per row*, i.e. a
1.5-second freeze per viewport. It is never called here, and neither are
``priority_rows``, the embedding index, or the match caches: this column is
pure scheduling data and touches none of the semantic stack.

There is deliberately NO memo cache. Retrievability is a function of elapsed
time, so a cached cell goes stale by simply existing, and the query it would
save costs 3 µs.

NOTES MODE shows the note's LOWEST card retention — the card nearest to
being forgotten, which is the one that decides whether the note is worth
studying. That also matches Anki's own notes-mode idiom for per-card facts
(its Due column collapses a note's cards to the most urgent one). Cards that
have never been studied are skipped rather than counted as 0%, so a note
with one new card and one 90% card reads "90%", not "0%".

NEW CARDS render "—", not "0%". This is a deliberate divergence from
``retention.card_retrievability``, which scores new cards 0.0 because for
*PDF ranking* unlearned material is the strongest "study this" signal. In a
per-row cell that same 0.0 would read as "you are about to forget this",
which is the opposite of the truth: the card was never learned. "—" is also
what the Library prints for an absent score, so the two surfaces agree on
the glyph.

Suspended and buried cards are NOT special-cased: their memory decays like
any other, and Anki already tints those rows itself.

Everything above the "aqt glue" divider is aqt-free — the formatting, the
new-card/no-FSRS/None cases, the note aggregation, and the per-row queries
(which take ``col`` as an argument, retention.py's own convention) — for
tests/test_browse_retention.py. The glue below imports aqt only inside
functions, so ``import klaus_note.browse_retention`` never needs Qt.

The forgetting curve itself is NOT reimplemented here. ``retention.py`` owns
it (``fsrs_retrievability`` / ``sm2_retrievability``) and is imported lazily
inside ``_curve()`` — lazily because retention.py's own module top does
``from aqt import mw``, and this module's top must stay clean. A fork of
those four lines of arithmetic would be two curves that could drift apart;
tests/test_browse_retention.py pins that no such fork exists.
"""

from __future__ import annotations

import json
import time

# Stored in the collection's browser config once the user enables the
# column, so it must never change: a new key would silently drop everyone's
# enabled column back to hidden.
COLUMN_KEY = "klaus_retention"
COLUMN_LABEL = "Retention"

# Same glyph the Library prints for a missing score (pdf_drive), so the two
# surfaces read as one feature.
EMPTY_CELL = "—"

CARDS_TOOLTIP = (
    "KlausNote: estimated chance of recalling this card right now (FSRS "
    "retrievability). New cards show —. This column cannot be sorted."
)
NOTES_TOOLTIP = (
    "KlausNote: the lowest retention among this note's cards — the one "
    "nearest to being forgotten. Notes with no studied cards show —. This "
    "column cannot be sorted."
)

SECS_PER_DAY = 86400.0

_curve_warned = False


# ------------------------------------------------------------ pure helpers


def _curve():
    """retention.py's forgetting curve, or None if it cannot be imported.

    Imported lazily and on purpose: retention.py is the single source of
    truth for both ``fsrs_retrievability`` and ``sm2_retrievability``, but
    its module top does ``from aqt import mw``. A top-level import here
    would drag aqt (and the whole curation/embeddings stack) into Browse's
    import path and break this module's headless testability; copying the
    arithmetic instead would fork the curve. So: lazy import, warn once,
    and degrade to an empty cell.
    """
    global _curve_warned
    try:
        from . import retention

        return retention
    except Exception as exc:  # noqa: BLE001 - a missing curve must not break Browse
        if not _curve_warned:
            _curve_warned = True
            print(f"[klaus_note] browse retention: FSRS curve unavailable: {exc}")
        return None


def parse_card_state(data) -> dict | None:
    """The FSRS state dict out of one card's ``cards.data`` JSON.

    Shape is ``{"s","d","dr","decay","lrt"}`` (plus "pos" on new cards).
    Anything unparseable, non-dict, or empty reads as None — ``cards.data``
    is NOT NULL but is routinely the empty string.
    """
    if not data:
        return None
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def card_retention(
    ctype, ivl, data, now: float, last_review_secs=None
) -> float | None:
    """One card's retrievability, or None when the card has no memory yet.

    Mirrors the per-card branch of ``retention.card_retrievability`` (FSRS
    state first, crude interval-based estimate for pre-FSRS reviewed cards)
    with one deliberate difference: this returns **None** where the
    aggregate returns ``0.0`` for new/never-reviewed cards. See the module
    docstring — 0% in a cell means "about to forget", which is the opposite
    of what an unstudied card deserves.

    ``last_review_secs`` is an optional zero-argument callable returning
    epoch seconds of the card's last review, used only on the two paths
    that need it (an FSRS state missing "lrt", or no FSRS state at all).
    Passing a callable rather than a value keeps the ``revlog`` query off
    the common path entirely: on Pouya's collection every card with FSRS
    stability also carries "lrt", so it never fires.
    """
    math_mod = _curve()
    if math_mod is None:
        return None

    try:
        ctype_i = int(ctype)
    except (TypeError, ValueError):
        return None
    if ctype_i == 0:
        return None  # new card: never studied, so there is nothing to recall

    state = parse_card_state(data)
    stability = _float_or_none(state.get("s")) if state is not None else None

    if stability is not None and stability > 0:
        decay = _float_or_none(state.get("decay")) or 0.5
        lrt = _float_or_none(state.get("lrt"))
        if not lrt and last_review_secs is not None:
            lrt = _float_or_none(last_review_secs())
        elapsed = ((now - lrt) / SECS_PER_DAY) if lrt else 0.0
        return math_mod.fsrs_retrievability(stability, decay, elapsed)

    # Reviewed (type != 0) but no usable FSRS state — SM-2 era, or an
    # import. Fall back to the interval-as-stability estimate.
    lrt = _float_or_none(last_review_secs()) if last_review_secs is not None else None
    if not lrt:
        return None  # non-new type with no review history: nothing to report
    try:
        ivl_i = int(ivl or 0)
    except (TypeError, ValueError):
        ivl_i = 0
    return math_mod.sm2_retrievability(ivl_i, (now - lrt) / SECS_PER_DAY)


def note_retention(values) -> float | None:
    """Collapse a note's per-card retentions to the cell's one number.

    The MINIMUM of the cards that have one — the weakest card is what makes
    the note worth restudying, and it is the same "most urgent card wins"
    collapse Anki uses for its own notes-mode columns. Cards with no
    retention (new / never reviewed) are skipped, not counted as zero; a
    note where every card is new returns None.
    """
    scored = [v for v in values if v is not None]
    return min(scored) if scored else None


def format_retention(value) -> str:
    """Cell text: ``"87%"``, or ``"—"`` for None.

    Integer percent and the em dash both copy pdf_drive's retention cell
    verbatim, so the Library and Browse never disagree about how the same
    number looks.
    """
    if value is None:
        return EMPTY_CELL
    try:
        pct = round(float(value) * 100)
    except (TypeError, ValueError):
        return EMPTY_CELL
    return f"{pct}%"


def cell_index(columns) -> int | None:
    """Position of our column in this row's active column list, or None.

    ``browser_did_fetch_row`` hands over every active column key; the
    column is off for most users most of the time, so "not present" is the
    normal case and must be cheap.
    """
    try:
        for idx, key in enumerate(columns):
            if key == COLUMN_KEY:
                return idx
    except TypeError:
        return None
    return None


# -------------------------------------------------- per-row collection reads


def card_last_review_secs(col, cid) -> float | None:
    """Epoch seconds of one card's most recent review, or None.

    ``revlog.id`` is the review timestamp in milliseconds, and
    ``ix_revlog_cid`` makes this an index seek (~1.9 µs measured). Only
    reached by cards whose FSRS state predates the "lrt" field, so on a
    modern collection it effectively never runs.
    """
    try:
        ms = col.db.scalar("select max(id) from revlog where cid = ?", int(cid))
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] browse retention: revlog lookup failed: {exc}")
        return None
    return (ms / 1000.0) if ms else None


def card_rows(col, item_id, is_notes_mode: bool):
    """The (id, type, ivl, data) tuples for THIS row's card(s). One
    statement, one index, nothing collection-wide.

    Notes mode hands us a NoteId and a note owns a handful of cards;
    cards mode hands us a CardId and returns exactly one tuple.
    """
    if is_notes_mode:
        sql = "select id, type, ivl, data from cards where nid = ?"
    else:
        sql = "select id, type, ivl, data from cards where id = ?"
    return col.db.all(sql, int(item_id))


def retention_for_item(
    col, item_id, is_notes_mode: bool, now: float | None = None
) -> float | None:
    """The number the cell shows for one Browse row, or None.

    One card in cards mode; the lowest-scoring card in notes mode (see
    ``note_retention``). Any failure reads as None so a broken row can
    never take the browser down with it.
    """
    if now is None:
        now = time.time()
    try:
        rows = card_rows(col, item_id, is_notes_mode)
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] browse retention: card lookup failed: {exc}")
        return None
    values = []
    for row in rows or []:
        try:
            cid, ctype, ivl, data = row
        except (TypeError, ValueError):
            continue
        values.append(
            card_retention(
                ctype, ivl, data, now, lambda c=cid: card_last_review_secs(col, c)
            )
        )
    return note_retention(values)


# ─────────────────────────────────────────────────────────────────────
# aqt glue — every aqt/anki import below lives inside a function
# ─────────────────────────────────────────────────────────────────────


def _collection():
    """``mw.col``, or None when no profile is open. The single aqt
    touchpoint of the row handler, so tests can replace it wholesale."""
    from aqt import mw

    return getattr(mw, "col", None)


def make_column():
    """The ``BrowserColumns.Column`` describing our column, or None.

    ``anki.collection.BrowserColumns`` is the protobuf that
    ``aqt.browser.Column`` re-exports; taking it from the source module
    means one import for both the message class and the ``SORTING_NONE`` /
    ``ALIGNMENT_CENTER`` enum values.

    ``uses_cell_font`` is False — that flag is for columns showing note
    content in the note's own font; this one shows a number.
    """
    try:
        from anki.collection import BrowserColumns

        return BrowserColumns.Column(
            key=COLUMN_KEY,
            cards_mode_label=COLUMN_LABEL,
            notes_mode_label=COLUMN_LABEL,
            sorting_cards=BrowserColumns.SORTING_NONE,
            sorting_notes=BrowserColumns.SORTING_NONE,
            uses_cell_font=False,
            alignment=BrowserColumns.ALIGNMENT_CENTER,
            cards_mode_tooltip=CARDS_TOOLTIP,
            notes_mode_tooltip=NOTES_TOOLTIP,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] browse retention column build failed: {exc}")
        return None


def on_browser_did_fetch_columns(columns) -> None:
    """gui_hooks.browser_did_fetch_columns: offer the column.

    Adding the entry only makes it *toggleable*; Anki shows it once the
    user ticks it in Browse's column context menu.
    """
    try:
        column = make_column()
        if column is not None:
            columns[COLUMN_KEY] = column
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] browse retention columns hook failed: {exc}")


def on_browser_did_fetch_row(item_id, is_notes_mode, row, columns) -> None:
    """gui_hooks.browser_did_fetch_row: fill our (blank) cell in.

    Anki's own signature names the second argument ``is_note``; it is True
    in notes mode. Returns immediately when the user has not enabled the
    column, which is the common case — ``cell_index`` is a list walk over
    the handful of active column keys and nothing more.
    """
    try:
        idx = cell_index(columns)
        if idx is None:
            return
        if getattr(row, "is_disabled", False):
            return  # placeholder row for a deleted/missing item
        cells = getattr(row, "cells", None)
        if not cells or idx >= len(cells):
            return
        col = _collection()
        if col is None:
            return
        value = retention_for_item(col, item_id, bool(is_notes_mode))
        cells[idx].text = format_retention(value)
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] browse retention row hook failed: {exc}")


def setup() -> None:
    """Register both hooks. Called once from ``klaus_note/__init__.py``."""
    try:
        from aqt import gui_hooks

        gui_hooks.browser_did_fetch_columns.append(on_browser_did_fetch_columns)
        gui_hooks.browser_did_fetch_row.append(on_browser_did_fetch_row)
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] browse retention setup failed: {exc}")
