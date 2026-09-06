"""The Klaus toolkit strip along the bottom of Browse (K-170).

Pouya, 2026-09-01: *"At the bottom of this panel here, I want a toolkit
for Klaus where it does a few things."* Asked where, he chose a strip
across the bottom of the Browse window, under the note list. The first
tool is the semantic duplicate finder whose engine is ``duplicates.py``
(K-168); this module is the SURFACE and reimplements none of it.

Why Browse is the right home and not merely the chosen one: results are
only useful if you can act on them — select, suspend, tag, delete. Put
the strip here and the results land in the note TABLE directly above it,
where Anki's own machinery already does the acting. A toolkit in the
Library would have to bounce the user back here anyway.


THE GATE: this strip is NOT gated on ``klausbook_design``
---------------------------------------------------------
Every painter in ``window_chrome.py`` gates on it; this one does not,
and the difference is the whole distinction that gate encodes.
``background.design_enabled`` gates the LOOK — wallpapers, frosted
panels, restyled chrome. CLAUDE.md is explicit that functional
injections are never gated, and this Browse lane already has two
precedents that say so in their own words: ``browse_toggles.py`` ("NOT
gated ... they are a functional affordance, so they ship in native mode
too") and ``browse_retention.py`` ("no design gate — this is a
functional injection").

The asymmetry decides it. ``klausbook_design`` DEFAULTS TO FALSE —
"Klaus ships as tools in a stock Anki; the full look is the opt-in".
Gating a duplicate finder on it would ship the addon's flagship new
capability invisible to every default profile, and a feature nobody can
find is a feature that does not exist. Ungating it costs, at worst, a
row of buttons a design-averse user did not ask for. One failure is a
missing feature; the other is a cosmetic surprise.

But "ungated" is a bill, not a free pass, and browse_toggles paid it the
same way: *because* it ships against stock Anki chrome, it must LOOK
like stock Anki chrome. So this strip carries no Klaus surface fill, no
frost, no accent band, no wordmark. It is a hairline and a row of
borderless buttons in the same greys Anki uses, and every colour comes
from ``theme.palette`` so it follows the accent theme when there is one
and disappears into the window when there is not. Attribution rides in
the tooltips ("KlausMate: ..."), which is browse_retention's convention
for exactly this situation.

A visibility CONFIG KEY was considered and deliberately not added:
that would need a default in ``config.json`` and a line in
``config.md``, neither of which this card owns, and a key with no
default and no documentation is worse than no key. browse_toggles ships
its buttons unconditionally for the same reason.


THE SHAPE: a registry, so tool two is a tuple
---------------------------------------------
``TOOLS`` is the registry, in ``dashboard.WIDGETS``' shape — Python owns
it, and one tuple is one tool. The panel factory is named as a STRING
resolved with ``getattr`` at open time (``window_chrome._BUILDERS``'
shape), which is what keeps the registry itself aqt-free and testable
above the glue divider. Adding the second tool is one tuple plus one
``_build_*_panel`` function; nothing else in this file changes.


THE RESULTS: a native Anki search, never a private token
--------------------------------------------------------
Pairs reach the note table through
``col.build_search_string(SearchNode(nids=SearchNode.IdList(ids=...)))``
handed to ``Browser.search_for``. All three are verified against Anki
26.8.1's SHIPPED BYTECODE, not assumed:

* ``anki/search_pb2.pyc`` carries ``SearchNode.nids`` of type
  ``SearchNode.IdList`` — so a note-id list is a first-class search node
  and lowers to native ``nid:`` syntax;
* ``anki/collection.pyc`` carries ``Collection.build_search_string``,
  and its own docstrings point callers at it ("To programmatically
  construct a search string, see .build_search_string()");
* ``aqt/browser/browser.pyc`` carries ``Browser.search_for(search,
  prompt)`` — the same call Anki's own Find Duplicates report uses.

K-131 is the warning this follows. The heatmap's old private
``klausday:`` token was opaque AND inert: its ``browser_will_search``
resolver assigned ``search_context.card_ids``, and ``SearchContext`` has
no such field. Re-verified here from ``aqt/browser/table/__init__.pyc``
— the dataclass is exactly ``search``, ``browser``, ``order``,
``reverse``, ``addon_metadata``, ``ids``. So the resolver wrote an
attribute nothing reads, Anki parsed the token as a field search, and it
matched nothing, silently. This module never registers a search hook at
all: the string it builds is one the user can read, edit, and re-run.


THE FINDING THAT SHAPED THE RESULTS VIEW
----------------------------------------
``duplicates.py`` measured something that inverts the obvious design:
**cosine's top of the list is its worst part.** The single
highest-scoring pair in Pouya's collection, 0.9983, is a deliberate
CONTRAST pair — "increased plasma protein pi_GC -> Decreased FF" against
"decreased plasma protein pi_GC -> Increased FF" — and of the 64 pairs
above 0.99 that class dominates. Antonyms embed closer than paraphrases,
because the sentences are identical apart from the one word that
reverses them.

Four consequences, all load-bearing:

1. **This is not a delete queue.** Nothing is pre-selected, there is no
   bulk action, and no destructive action of any kind. The only thing a
   row can do is put its two notes in the table above, where Anki's own
   suspend / tag / delete apply with Anki's own undo.

2. **Both notes' text is on screen.** A row of two ids and a score is
   unusable here for exactly the reason above: the difference between a
   duplicate and a contrast pair is one word.

3. **The default order is by WORDING, not by score.** Sorting by cosine
   descending puts the least deletable pairs on top. So the default is
   ``lexical_overlap`` ASCENDING, score descending inside it — which
   surfaces the genuine finds (high cosine, low literal overlap; the
   ones Anki's exact matcher cannot make) and sinks both false-positive
   classes, because both are word-set-heavy: sibling notes share a
   verbatim Extra block, and a contrast pair's two sentences have
   *identical word sets*, the swap being an ordering, not a vocabulary.
   The raw cosine order stays available as the second choice. Overlap is
   a SORT and a BADGE and never a filter — three identical "ID
   Structure: Medial lemniscus" notes are real duplicates at ~0.9
   overlap, so suppressing the high end would hide the best answers.

4. **Pairs are the primitive.** ``duplicates.group_pairs`` exists and
   overreaches at these thresholds (2,067 pairs collapse to 1,405
   clusters whose largest is 14 notes and is an entire folate/B12 deck
   section), so this surface never leads with clusters.

The tier defaults to the tightest band (duplicate, >= 0.95 — 2,067
pairs on Pouya's collection against 13,389 near and 50,955 close). A
flat 66,411-row list is not a UI, and loosening is one combo away.


THREADING
---------
``scan_index`` is ~36 s on a 28,670-note index, so it runs on a
``QueryOp`` worker parented to ``mw`` (never to the strip: a QueryOp
whose parent dies takes its callback with it) with a ``seq`` token
discarding stale callbacks — pdf_drive's documented contract.

Progress crosses the thread boundary as ONE INTEGER and nothing else.
The engine's ``on_progress`` runs on the worker, so it only assigns to
``self._progress``; a main-thread ``QTimer`` polls that and updates the
label. No widget is touched from the worker, which is the only version
of this that is safe by construction rather than by luck.

Everything above the "aqt glue" divider is aqt-free and pure, for
``tests/test_browse_toolkit.py``.
"""

from __future__ import annotations

from typing import Any

try:  # aqt-free, pure-stdlib engine; absent only if K-168 is unlanded
    from . import duplicates as _dupes
except Exception:  # pragma: no cover - the honest-refusal path
    _dupes = None  # type: ignore[assignment]


# ─────────────────────────────────────────────────────────────────────
# The registry
# ─────────────────────────────────────────────────────────────────────

# (tool id, button label, tooltip, panel-factory attribute name).
#
# The factory is a STRING resolved with getattr on this module at open
# time — window_chrome._BUILDERS' shape — so the registry stays pure and
# this whole section imports without Qt. Adding a tool is one tuple here
# plus one `_build_<id>_panel(host)` function below.
TOOLS: tuple = (
    (
        "duplicates",
        "Duplicates",
        "KlausMate: find notes that teach the same thing, by meaning "
        "rather than by identical text.",
        "_build_duplicates_panel",
    ),
)


def tool_ids() -> list:
    return [tid for tid, _label, _tip, _factory in TOOLS]


def tool_entry(tool_id: Any) -> tuple | None:
    for entry in TOOLS:
        if entry[0] == tool_id:
            return entry
    return None


def tool_factory_name(tool_id: Any) -> str:
    """The factory attribute for *tool_id*, or "" for an unknown id.

    Total by design: the strip resolves this through getattr, and an
    unknown id has to degrade to "no panel", never to an exception in a
    Browse window.
    """
    entry = tool_entry(tool_id)
    return entry[3] if entry else ""


# ─────────────────────────────────────────────────────────────────────
# Refusals — a message, not a shrug (index_queue's rule)
# ─────────────────────────────────────────────────────────────────────

NO_ENGINE_TEXT = (
    "The duplicate finder is not installed in this build of KlausMate."
)
NO_PROFILE_TEXT = "Open a collection first."
NO_INDEX_TEXT = (
    "No search index yet. Build one in KlausMate Preferences → Semantic "
    "Search, then come back."
)
STALE_INDEX_TEXT = (
    "The search index was built with a different embedding model. "
    "Re-index in KlausMate Preferences → Semantic Search."
)
THIN_INDEX_TEXT = "The search index holds too few notes to compare."

# Two notes is the smallest collection that can contain a pair at all;
# duplicates.scan_index returns an empty result below it.
MIN_NOTES = 2


def disabled_reason(
    *,
    engine: Any,
    has_profile: bool,
    stats: Any,
    signature_ok: bool,
) -> str:
    """Why the duplicates tool cannot run right now, or "" when it can.

    Ordered most-fundamental first so the message names the thing the
    user has to fix, not the last check that happened to trip. Pure, and
    the ONE place the refusal is decided — the panel renders whatever
    this returns and never composes its own excuse.
    """
    if engine is None:
        return NO_ENGINE_TEXT
    if not has_profile:
        return NO_PROFILE_TEXT
    if not isinstance(stats, dict) or not stats.get("exists"):
        return NO_INDEX_TEXT
    # Signature BEFORE size: an index built by another model is wrong at
    # any size, and "too few notes" would be a misleading thing to say
    # about a full index that simply cannot be compared.
    if not signature_ok:
        return STALE_INDEX_TEXT
    try:
        count = int(stats.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count < MIN_NOTES:
        return THIN_INDEX_TEXT
    return ""


# ─────────────────────────────────────────────────────────────────────
# Tiers — read off the engine, never re-spelled
# ─────────────────────────────────────────────────────────────────────

DEFAULT_TIER = "duplicate"


def tier_choices() -> list:
    """[(tier id, label, threshold)], tightest first.

    The thresholds come from ``duplicates`` so this surface can never
    disagree with the engine about what "duplicate" means; the band
    edges were calibrated against a real collection and are explicitly
    NOT transferable between embedding models, which is another reason
    not to keep a second copy of them here. Empty when the engine is
    missing — the tool is disabled in that state anyway.
    """
    if _dupes is None:
        return []
    return [
        ("duplicate", "Duplicates", float(_dupes.DUPLICATE)),
        ("near", "Near duplicates", float(_dupes.NEAR)),
        ("close", "Close", float(_dupes.CLOSE)),
    ]


def threshold_for(tier_id: Any) -> float:
    for tid, _label, value in tier_choices():
        if tid == tier_id:
            return value
    for tid, _label, value in tier_choices():
        if tid == DEFAULT_TIER:
            return value
    return 0.0


def tier_label(tier_id: Any) -> str:
    for tid, label, _value in tier_choices():
        if tid == tier_id:
            return label
    return ""


# ─────────────────────────────────────────────────────────────────────
# Wording — a sort and a badge, never a filter
# ─────────────────────────────────────────────────────────────────────

# Read off duplicates.py's measurements, not chosen: every sampled pair
# above 0.85 word-set Jaccard was a sibling note carved out of one
# shared block, and every genuine semantic find sat below 0.40.
SAME_WORDING = 0.85
SIMILAR_WORDING = 0.40

WORDING_SAME = "same wording"
WORDING_SIMILAR = "similar wording"
WORDING_DIFFERENT = "different wording"

ORDER_DISTINCT = "distinct"
ORDER_SCORE = "score"
DEFAULT_ORDER = ORDER_DISTINCT

ORDER_CHOICES: tuple = (
    (ORDER_DISTINCT, "Different wording first"),
    (ORDER_SCORE, "Highest similarity first"),
)

ORDER_TOOLTIP = (
    "Different wording first puts the finds Anki's exact matcher cannot "
    "make at the top. Pairs whose two notes use the same words are "
    "usually sibling notes or deliberate contrast pairs — they sort "
    "last, and are never hidden."
)


def wording_label(overlap: Any) -> str:
    """One word for how literally alike a pair's two notes are."""
    try:
        value = float(overlap)
    except (TypeError, ValueError):
        return ""
    if value >= SAME_WORDING:
        return WORDING_SAME
    if value >= SIMILAR_WORDING:
        return WORDING_SIMILAR
    return WORDING_DIFFERENT


def sort_rows(rows: Any, order: Any) -> list:
    """Display order for result rows. Never drops one.

    ``distinct`` (the default) is lexical overlap ASCENDING then score
    descending; ``score`` is the raw cosine order. Both are total over
    the same list — the whole point of the finding is that the ordering
    is a judgement and the filtering is not ours to make.
    """
    items = list(rows or [])
    if order == ORDER_SCORE:
        return sorted(items, key=lambda r: -float(r.get("score", 0.0)))
    return sorted(
        items,
        key=lambda r: (float(r.get("overlap", 0.0)), -float(r.get("score", 0.0))),
    )


# ─────────────────────────────────────────────────────────────────────
# Result copy
# ─────────────────────────────────────────────────────────────────────

SCANNING_TEXT = "Scanning the collection for duplicates…"
LOADING_TEXT = "Loading the search index…"
SCAN_FAILED_TEXT = "The scan could not finish. See the console for details."
NO_SELECTION_TEXT = "Select a note in the table above first."
SELECTED_NOT_INDEXED_TEXT = (
    "That note is not in the search index yet — it may be new, or have no "
    "text to embed."
)

# Said once in the empty state, because it is the argument for the tool:
# exact_text_groups() returns ZERO on Pouya's collection, so Anki's own
# Find Duplicates has nothing at all to show him there.
EXACT_NOTE = (
    "This looks for notes that mean the same thing. Anki's own Find "
    "Duplicates only matches identical text in one field."
)


def preview_text(raw: Any, cap: int = 160) -> str:
    """One note's text, collapsed to a single line and capped.

    The cap is generous on purpose: the difference between a duplicate
    and a contrast pair is often a single word deep into the sentence,
    so a stingy preview would hide exactly what the row exists to show.
    """
    text = " ".join(str(raw or "").split())
    if cap > 0 and len(text) > cap:
        return text[: max(0, cap - 1)].rstrip() + "…"
    return text


def normalize_nids(values: Any) -> list:
    """Positive ints, deduplicated, first occurrence wins.

    Total: anything unparseable is dropped rather than raising, because
    the caller is building a search string out of whatever a result row
    happens to hold.
    """
    out: list = []
    seen: set = set()
    for value in list(values or []):
        try:
            nid = int(value)
        except (TypeError, ValueError):
            continue
        if nid <= 0 or nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out


def row_nids(rows: Any) -> list:
    """Every note id named by *rows*, in display order."""
    flat: list = []
    for row in list(rows or []):
        flat.append(row.get("a"))
        flat.append(row.get("b"))
    return normalize_nids(flat)


def result_summary(
    shown: int, counts: Any, tier: Any, cancelled: bool = False
) -> str:
    """The one status line under a finished scan.

    ``stats.counts`` carries the TRUE per-tier totals even when the
    returned list was truncated, so this can report both without lying
    about either.
    """
    label = (tier_label(tier) or "matching").lower()
    total = 0
    if isinstance(counts, dict):
        try:
            total = int(counts.get(tier) or 0)
        except (TypeError, ValueError):
            total = 0
    stopped = " Stopped early — this is a partial result." if cancelled else ""
    if not total and not shown:
        return f"No {label} pairs found.{stopped}"
    if total > shown:
        return f"Showing {shown:,} of {total:,} {label} pairs.{stopped}"
    return f"{shown:,} {label} pair{'' if shown == 1 else 's'}.{stopped}"


def progress_text(done: Any, total: Any) -> str:
    """Worker progress as a line, from two plain integers."""
    try:
        done_i, total_i = int(done), int(total)
    except (TypeError, ValueError):
        return SCANNING_TEXT
    if total_i <= 0:
        return SCANNING_TEXT
    pct = max(0, min(100, int(100 * done_i / total_i)))
    return f"Scanning… {pct}%"


def build_rows(pairs: Any, texts: Any) -> list:
    """Engine pairs + a {nid: text} map -> display rows.

    ``overlap`` is computed here, once, so sorting and badging never
    disagree and the engine is never asked for it twice. A pair whose
    notes have no text still renders — the ids and the score are real,
    and dropping the row would be a silent filter.
    """
    rows: list = []
    lookup = texts if isinstance(texts, dict) else {}
    overlap_fn = getattr(_dupes, "lexical_overlap", None)
    for pair in list(pairs or []):
        text_a = lookup.get(pair.nid_a, "")
        text_b = lookup.get(pair.nid_b, "")
        overlap = 0.0
        if overlap_fn is not None:
            try:
                overlap = float(overlap_fn(text_a, text_b))
            except Exception:
                overlap = 0.0
        rows.append(
            {
                "a": pair.nid_a,
                "b": pair.nid_b,
                "score": float(pair.score),
                "tier": pair.tier,
                "overlap": overlap,
                "text_a": preview_text(text_a),
                "text_b": preview_text(text_b),
            }
        )
    return rows


def score_text(score: Any) -> str:
    try:
        return f"{float(score):.3f}"
    except (TypeError, ValueError):
        return ""


# ─────────────────────────────────────────────────────────────────────
# aqt glue — everything below here talks to Anki
# ─────────────────────────────────────────────────────────────────────

from aqt.qt import (  # noqa: E402
    QAbstractItemView,
    QBoxLayout,
    QColor,
    QComboBox,
    QEvent,
    QFontMetrics,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QObject,
    QPainter,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    Qt,
    QTimer,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# How many result rows reach the tree. The engine's own limit bounds the
# scan; this bounds the WIDGET, and the summary line always reports the
# true total beside it so a cap never reads as an answer.
DISPLAY_CAP = 500

# The engine's heap size. Its default; named here so the pin can see it.
SCAN_LIMIT = 2000

STRIP_MARGIN = 6
STRIP_SPACING = 8
HAIRLINE = 1
RESULTS_MAX_H = 320
# The results tree is sized to its CONTENT between these two row counts.
# Measured: six results in a fixed 320px tree left half the panel an empty
# white rectangle, and an empty one was a void the size of the note table
# it had just stolen from.
TREE_MIN_ROWS = 3
TREE_MAX_ROWS = 12
FALLBACK_ROW_H = 22

COL_SCORE, COL_WORDING, COL_A, COL_B = 0, 1, 2, 3
COLUMN_HEADERS = ("Similarity", "Wording", "Note", "Other note")
SCORE_COL_W = 88
WORDING_COL_W = 132


def _theme():
    from . import theme

    return theme


def _strip_qss(night: bool) -> str:
    """The strip's own chrome, composed from theme tokens ONLY.

    No literal colour appears in this file (there is a pin). Quiet by
    construction: nothing at rest, a subtle wash on hover, the live
    accent at low alpha when a tool is open — browse_toggles' grammar,
    for browse_toggles' reason (an ungated surface has to read as
    Anki's, not as an advertisement).
    """
    theme = _theme()
    c = theme.palette(night)
    return f"""
    QToolButton#KlausToolButton {{
        border: none;
        border-radius: 6px;
        padding: 3px 10px;
        background: transparent;
        color: {c['text']};
    }}
    QToolButton#KlausToolButton:hover {{
        background: {c['hover_subtle']};
    }}
    QToolButton#KlausToolButton:checked {{
        background: {theme.accent_rgba(night, 0.14)};
        color: {c['blue_accent']};
    }}
    QToolButton#KlausToolButton:disabled {{
        color: {c['text_faint']};
    }}
    QLabel#KlausToolStatus, QLabel#KlausToolEmpty {{
        color: {c['text_muted']};
    }}
    QLabel#KlausToolEmpty {{
        padding: 10px 2px 12px 2px;
    }}
    QScrollArea#KlausToolControls {{
        background: transparent;
        border: none;
    }}
    QTreeWidget#KlausToolResults {{
        border: {HAIRLINE}px solid {c['grey_mid']};
        border-radius: 6px;
        background: {c['surface']};
        color: {c['text']};
    }}
    QTreeWidget#KlausToolResults::item:selected {{
        background: {c['selection_bg']};
        color: {c['text']};
    }}
    QHeaderView::section {{
        background: {c['bg']};
        color: {c['text_muted']};
        border: none;
        border-bottom: {HAIRLINE}px solid {c['grey_mid']};
        padding: 3px 6px;
    }}
    """


class _ElidedLabel(QLabel):  # type: ignore[misc]
    """A status label that elides instead of forcing the strip wider.

    Browse gets narrow, and a plain QLabel's sizeHint is its whole text —
    which would push the tool buttons off the row rather than shortening
    the sentence. Elision is done in setText/resizeEvent with
    QFontMetrics rather than in a paintEvent, so this widget adds no
    second painter to guard.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__("")
        self._full = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 — Qt override name
        try:
            self._full = text or ""
            self._reelide()
        except Exception as exc:
            print(f"[klausmate] browse toolkit label text failed: {exc}")

    def full_text(self) -> str:
        return self._full

    def _reelide(self) -> None:
        try:
            metrics = QFontMetrics(self.font())
            width = max(0, self.width())
            if width <= 0:
                super().setText(self._full)
            else:
                super().setText(
                    metrics.elidedText(
                        self._full, Qt.TextElideMode.ElideRight, width
                    )
                )
            self.setToolTip(self._full)
        except Exception:
            super().setText(self._full)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override name
        try:
            self._reelide()
            super().resizeEvent(event)
        except Exception as exc:
            print(f"[klausmate] browse toolkit label resize failed: {exc}")


class BrowseToolkit(QWidget):  # type: ignore[misc]
    """The strip: a hairline, a row of tool buttons, and at most one
    open tool panel above them.

    Vertically Maximum so it takes its size hint and never a pixel more
    — the note table above it keeps every surplus row of the column, which
    is what stops the table shrinking when nothing is open.
    """

    def __init__(self, browser: Any) -> None:
        super().__init__()
        self.browser = browser
        self._buttons: dict = {}
        self._panels: dict = {}
        self._open: str = ""

        self.setObjectName("KlausBrowseToolkit")
        # Horizontally IGNORED: the strip sits inside the note column since
        # 2026-09-05, and a Preferred width there would add the button
        # row's minimum to the window's floor (measured: 130 → 151 px).
        # The column is never narrower than its own table, so the row is
        # never actually clipped.
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, HAIRLINE, 0, 0)
        outer.setSpacing(0)

        self._panel_host = QWidget()
        host_box = QVBoxLayout(self._panel_host)
        host_box.setContentsMargins(
            STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN, 0
        )
        host_box.setSpacing(0)
        self._panel_host.setVisible(False)
        outer.addWidget(self._panel_host)

        row_host = QWidget()
        row = QHBoxLayout(row_host)
        row.setContentsMargins(
            STRIP_MARGIN, STRIP_MARGIN // 2, STRIP_MARGIN, STRIP_MARGIN // 2
        )
        row.setSpacing(STRIP_SPACING)
        for tool_id, label, tip, _factory in TOOLS:
            btn = QToolButton()
            btn.setObjectName("KlausToolButton")
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setAccessibleName(f"KlausMate {label}")
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, tid=tool_id: self.toggle_tool(tid)
            )
            row.addWidget(btn)
            self._buttons[tool_id] = btn
        row.addStretch(1)
        self.status = _ElidedLabel("")
        self.status.setObjectName("KlausToolStatus")
        row.addWidget(self.status, 1)
        outer.addWidget(row_host)

        self.apply_theme()

    # ---- chrome ----

    def apply_theme(self) -> None:
        try:
            theme = _theme()
            night = theme.night_mode()
            self.setStyleSheet(_strip_qss(night))
            self.status.setStyleSheet(theme.muted_label_qss(night))
        except Exception as exc:
            print(f"[klausmate] browse toolkit theme failed: {exc}")

    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt override name
        """One hairline along the top edge, so the strip reads as part of
        the window rather than as a floating box.

        K-115: a painter left open corrupts the backing store and
        segfaults Qt's next flush, so end() rides a finally and a drawing
        bug degrades to "the line did not draw".
        """
        try:
            if self.width() <= 0 or self.height() <= 0:
                return
            painter = QPainter(self)
            try:
                c = _theme().palette(_theme().night_mode())
                painter.fillRect(
                    0, 0, self.width(), HAIRLINE, QColor(c["grey_mid"])
                )
            finally:
                painter.end()
        except Exception as exc:
            print(f"[klausmate] browse toolkit hairline failed: {exc}")

    # ---- tools ----

    def toggle_tool(self, tool_id: str) -> None:
        try:
            if self._open == tool_id:
                self.close_tool()
                return
            self.open_tool(tool_id)
        except Exception as exc:
            print(f"[klausmate] browse toolkit toggle failed: {exc}")

    def open_tool(self, tool_id: str) -> None:
        try:
            panel = self._panels.get(tool_id)
            if panel is None:
                name = tool_factory_name(tool_id)
                factory = globals().get(name) if name else None
                if factory is None:
                    print(f"[klausmate] browse toolkit: no panel for {tool_id}")
                    return
                panel = factory(self)
                if panel is None:
                    return
                self._panels[tool_id] = panel
                self._panel_host.layout().addWidget(panel)
            for other, widget in self._panels.items():
                widget.setVisible(other == tool_id)
            self._panel_host.setVisible(True)
            self._open = tool_id
            for tid, btn in self._buttons.items():
                btn.setChecked(tid == tool_id)
            opened = getattr(panel, "on_opened", None)
            if callable(opened):
                opened()
        except Exception as exc:
            print(f"[klausmate] browse toolkit open failed: {exc}")

    def close_tool(self) -> None:
        try:
            panel = self._panels.get(self._open)
            self._open = ""
            self._panel_host.setVisible(False)
            for btn in self._buttons.values():
                btn.setChecked(False)
            closed = getattr(panel, "on_closed", None)
            if callable(closed):
                closed()
        except Exception as exc:
            print(f"[klausmate] browse toolkit close failed: {exc}")

    def open_tool_id(self) -> str:
        return self._open

    def set_status(self, text: str) -> None:
        self.status.setText(text or "")

    def cleanup(self) -> None:
        """Stop every tool's background work. Called when Browse closes —
        a QueryOp callback that lands on a dead window is exactly what
        the seq token and _alive() exist to swallow, but a scan nobody
        will ever read should not keep burning a core either."""
        for panel in self._panels.values():
            stop = getattr(panel, "shutdown", None)
            if callable(stop):
                try:
                    stop()
                except Exception as exc:
                    print(f"[klausmate] browse toolkit shutdown failed: {exc}")


# ─────────────────────────────────────────────────────────────────────
# Tool 1: the semantic duplicate finder
# ─────────────────────────────────────────────────────────────────────


def _index_dir() -> str:
    from . import curation

    return curation.INDEX_DIR


def _browser_col(browser: Any) -> Any:
    col = getattr(browser, "col", None)
    if col is not None:
        return col
    try:
        from aqt import mw

        return getattr(mw, "col", None)
    except Exception:
        return None


def note_search(col: Any, nids: Any) -> str:
    """The NATIVE search string selecting exactly *nids*.

    ``SearchNode(nids=SearchNode.IdList(ids=...))`` through
    ``build_search_string`` — Anki's own documented way to construct a
    search programmatically, lowering to ``nid:`` syntax the user can
    read and edit. Never a private token and never a hand-spelled
    string: the backend owns the grammar.
    """
    clean = normalize_nids(nids)
    if not clean or col is None:
        return ""
    from anki.collection import SearchNode

    return col.build_search_string(SearchNode(nids=SearchNode.IdList(ids=clean)))


def show_in_table(browser: Any, nids: Any) -> bool:
    """Put *nids* in the note table above. True when a search was run."""
    try:
        search = note_search(_browser_col(browser), nids)
        if not search:
            return False
        browser.search_for(search)
        return True
    except Exception as exc:
        print(f"[klausmate] browse toolkit search failed: {exc}")
        return False


def selected_nids(browser: Any) -> list:
    """The note ids selected in Browse's table, through Anki's own API."""
    try:
        getter = getattr(browser, "selected_notes", None)
        if callable(getter):
            return normalize_nids(getter())
        table = getattr(browser, "table", None)
        if table is not None:
            return normalize_nids(table.get_selected_note_ids())
    except Exception as exc:
        print(f"[klausmate] browse toolkit selection read failed: {exc}")
    return []


def _note_texts(col: Any, nids: Any) -> dict:
    """{nid: embeddable text} for the notes a result set names.

    Runs on the QueryOp worker with the col that op was handed. Uses
    ``card_index.note_text`` so the preview is the SAME string the
    vectors were built from — a preview assembled differently could show
    two rows that look unalike and were scored alike.
    """
    from anki.utils import strip_html

    from . import card_index

    out: dict = {}
    for nid in normalize_nids(nids):
        try:
            note = col.get_note(nid)
            out[nid] = card_index.note_text(note.fields, strip_html)
        except Exception:
            out[nid] = ""
    return out


class _DuplicatesPanel(QWidget):  # type: ignore[misc]
    """The duplicate finder's results view.

    Deliberately not a delete queue: nothing is pre-selected, and the
    only action a row offers is putting its two notes in the table
    above. See the module docstring for the measurement that forced
    that shape.
    """

    def __init__(self, host: BrowseToolkit) -> None:
        super().__init__()
        self.host = host
        self.browser = host.browser
        self._seq = 0
        self._running = False
        self._progress: tuple = (0, 0)
        self._cancel: Any = None
        self._rows: list = []
        self._counts: dict = {}
        self._cancelled = False
        self._scanned_tier = ""

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(STRIP_MARGIN)

        # The control row rides in a scroll area with NO frame and no
        # vertical bar. Measured: laid out directly, this row's seven
        # controls pushed the whole Browse WINDOW's minimum width from
        # 130px to 924px — a Klaus panel deciding how narrow Anki's
        # Browse is allowed to be. Inside the scroller the panel's
        # minimum is its viewport's, so Browse shrinks as far as Anki
        # lets it and a thin horizontal bar appears only when the row
        # genuinely does not fit.
        self.control_scroll = QScrollArea()
        self.control_scroll.setObjectName("KlausToolControls")
        self.control_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.control_scroll.setWidgetResizable(True)
        self.control_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.control_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        control_host = QWidget()
        controls = QHBoxLayout(control_host)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(STRIP_SPACING)

        self.tier_combo = QComboBox()
        for tid, label, value in tier_choices():
            self.tier_combo.addItem(f"{label} (≥ {value:g})", tid)
        self.tier_combo.setToolTip(
            "How alike two notes must be to appear. Loosening this needs a "
            "fresh scan."
        )
        self.tier_combo.currentIndexChanged.connect(self._on_tier_changed)
        controls.addWidget(self.tier_combo)

        self.order_combo = QComboBox()
        for oid, label in ORDER_CHOICES:
            self.order_combo.addItem(label, oid)
        self.order_combo.setToolTip(ORDER_TOOLTIP)
        self.order_combo.currentIndexChanged.connect(self._render_rows)
        controls.addWidget(self.order_combo)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setObjectName("SecondaryButton")
        self.scan_btn.setToolTip(
            "Compare every note in the search index against every other. "
            "Runs in the background — Browse stays usable."
        )
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        controls.addWidget(self.scan_btn)

        self.selected_btn = QPushButton("Selected note")
        self.selected_btn.setObjectName("SecondaryButton")
        self.selected_btn.setToolTip(
            "Find the notes closest to the one selected in the table above. "
            "Instant — it compares one note, not every pair."
        )
        self.selected_btn.clicked.connect(self._on_selected_clicked)
        controls.addWidget(self.selected_btn)

        controls.addStretch(1)

        self.show_btn = QPushButton("Show pair")
        self.show_btn.setObjectName("SecondaryButton")
        self.show_btn.setToolTip(
            "Search the table above for this pair, so Anki's own tools "
            "apply to it."
        )
        self.show_btn.setEnabled(False)
        self.show_btn.clicked.connect(self._on_show_selected)
        controls.addWidget(self.show_btn)

        self.show_all_btn = QPushButton("Show all")
        self.show_all_btn.setObjectName("SecondaryButton")
        self.show_all_btn.setToolTip(
            "Search the table above for every note listed here."
        )
        self.show_all_btn.setEnabled(False)
        self.show_all_btn.clicked.connect(self._on_show_all)
        controls.addWidget(self.show_all_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("SecondaryButton")
        self.close_btn.clicked.connect(host.close_tool)
        controls.addWidget(self.close_btn)

        self.control_scroll.setWidget(control_host)
        self.control_scroll.setFixedHeight(
            control_host.sizeHint().height()
            + self.control_scroll.horizontalScrollBar().sizeHint().height()
        )
        box.addWidget(self.control_scroll)

        self.tree = QTreeWidget()
        self.tree.setObjectName("KlausToolResults")
        self.tree.setColumnCount(len(COLUMN_HEADERS))
        self.tree.setHeaderLabels(list(COLUMN_HEADERS))
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tree.setMinimumWidth(0)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemDoubleClicked.connect(self._on_show_selected)
        try:
            header = self.tree.header()
            header.setSectionResizeMode(
                COL_SCORE, QHeaderView.ResizeMode.Fixed
            )
            header.setSectionResizeMode(
                COL_WORDING, QHeaderView.ResizeMode.Fixed
            )
            header.setSectionResizeMode(COL_A, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(COL_B, QHeaderView.ResizeMode.Stretch)
            self.tree.setColumnWidth(COL_SCORE, SCORE_COL_W)
            self.tree.setColumnWidth(COL_WORDING, WORDING_COL_W)
        except Exception as exc:
            print(f"[klausmate] browse toolkit header setup failed: {exc}")
        box.addWidget(self.tree)

        # An empty results tree is a void the size of the note table it
        # just took space from (pdf_drive's _LibraryEmptyState learned
        # this on the Library). With no rows the tree is hidden outright
        # and this line stands in its place, carrying the SAME text the
        # status line has — the reason, or the argument for the tool.
        self.empty = QLabel(EXACT_NOTE)
        self.empty.setObjectName("KlausToolEmpty")
        self.empty.setWordWrap(True)
        self.empty.setMinimumWidth(0)
        box.addWidget(self.empty)

        # Main-thread poll of the worker's progress counter. Started only
        # while a scan is live; see the module docstring on why the
        # worker never touches a widget.
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._on_tick)

        self._sync_enabled()

    # ---- lifecycle ----

    def on_opened(self) -> None:
        self._sync_enabled()

    def on_closed(self) -> None:
        self.host.set_status("")

    def shutdown(self) -> None:
        self._seq += 1
        self._stop_cancel()
        try:
            self._tick.stop()
        except Exception:
            pass
        self._running = False

    def _alive(self) -> bool:
        """False once the C++ side is gone — pdf_drive's exact probe.

        A RuntimeError from any Qt call is the house test for a deleted
        widget; it needs no ``sip`` import, which this package otherwise
        never takes and which is spelled differently across bindings.
        """
        try:
            self.isVisible()
            return True
        except RuntimeError:  # C++ side deleted
            return False

    # ---- gate ----

    def _stats(self) -> dict:
        from . import card_index

        return card_index.stats_from_disk(_index_dir())

    def _signature_ok(self, stats: dict) -> bool:
        """Whether the on-disk index was built by the configured model.

        Always through ``embeddings.signature_matches`` — a hand-spelled
        tuple ``==`` reads every cache as stale, which is exactly how
        widening the signature broke eight call sites at once.
        """
        try:
            from . import curation, embeddings

            return embeddings.signature_matches(
                str(stats.get("provider") or ""),
                str(stats.get("model") or ""),
                int(stats.get("dims") or 0),
                embeddings.index_signature(curation._cfg()),
            )
        except Exception as exc:
            print(f"[klausmate] browse toolkit signature check failed: {exc}")
            return False

    def refusal(self) -> str:
        """"" when the tool can run, else the honest reason."""
        try:
            has_profile = _browser_col(self.browser) is not None
            stats = self._stats() if has_profile else {}
            return disabled_reason(
                engine=_dupes,
                has_profile=has_profile,
                stats=stats,
                signature_ok=self._signature_ok(stats) if stats else False,
            )
        except Exception as exc:
            print(f"[klausmate] browse toolkit gate failed: {exc}")
            return NO_INDEX_TEXT

    def _sync_enabled(self) -> None:
        reason = self.refusal()
        runnable = not reason and not self._running
        self.scan_btn.setEnabled(runnable)
        self.selected_btn.setEnabled(runnable)
        self.tier_combo.setEnabled(not self._running)
        for btn in (self.scan_btn, self.selected_btn):
            if reason:
                btn.setToolTip(reason)
        self.show_all_btn.setEnabled(bool(self._rows))
        if not self._rows and not self._running:
            # The refusal — or, with nothing wrong, the argument for the
            # tool — goes where the results would have been.
            self._show_empty(reason or EXACT_NOTE)

    # ---- controls ----

    def _tier(self) -> str:
        data = self.tier_combo.currentData()
        return data if isinstance(data, str) else DEFAULT_TIER

    def _order(self) -> str:
        data = self.order_combo.currentData()
        return data if isinstance(data, str) else DEFAULT_ORDER

    def _on_tier_changed(self) -> None:
        # The tier IS the engine's threshold, so loosening it needs a new
        # scan rather than a client-side filter over a result set that was
        # never allowed to contain the looser pairs.
        try:
            if (
                self._rows
                and self._scanned_tier
                and self._tier() != self._scanned_tier
            ):
                self.host.set_status(
                    "Similarity changed — scan again to see those pairs."
                )
        except Exception as exc:
            print(f"[klausmate] browse toolkit tier change failed: {exc}")

    def _on_tree_selection(self) -> None:
        try:
            self.show_btn.setEnabled(self.tree.currentItem() is not None)
        except Exception as exc:
            print(f"[klausmate] browse toolkit selection failed: {exc}")

    def _row_for(self, item: Any) -> dict | None:
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _on_show_selected(self, *_args) -> None:
        try:
            row = self._row_for(self.tree.currentItem())
            if row is None:
                return
            show_in_table(self.browser, [row.get("a"), row.get("b")])
        except Exception as exc:
            print(f"[klausmate] browse toolkit show pair failed: {exc}")

    def _on_show_all(self) -> None:
        try:
            nids = row_nids(self._visible_rows())
            if nids:
                show_in_table(self.browser, nids)
        except Exception as exc:
            print(f"[klausmate] browse toolkit show all failed: {exc}")

    # ---- the two searches ----

    def _stop_cancel(self) -> None:
        try:
            if self._cancel is not None:
                self._cancel.set()
        except Exception:
            pass

    def _on_scan_clicked(self) -> None:
        try:
            if self._running:
                self._stop_cancel()
                self.host.set_status("Stopping…")
                return
            self._start_scan()
        except Exception as exc:
            print(f"[klausmate] browse toolkit scan click failed: {exc}")

    def _begin(self, label: str) -> int:
        self._seq += 1
        self._running = True
        self._cancelled = False
        self._progress = (0, 0)
        self.host.set_status(label)
        self.scan_btn.setText("Stop")
        self._sync_enabled()
        self.scan_btn.setEnabled(True)
        try:
            self._tick.start()
        except Exception:
            pass
        return self._seq

    def _finish(self) -> None:
        self._running = False
        self.scan_btn.setText("Scan collection")
        try:
            self._tick.stop()
        except Exception:
            pass
        self._sync_enabled()

    def _on_tick(self) -> None:
        try:
            if not self._running:
                return
            done, total = self._progress
            self.host.set_status(progress_text(done, total))
        except Exception as exc:
            print(f"[klausmate] browse toolkit progress tick failed: {exc}")

    def _start_scan(self) -> None:
        reason = self.refusal()
        if reason:
            self.host.set_status(reason)
            return
        try:
            import threading

            from aqt import mw
            from aqt.operations import QueryOp
        except Exception as exc:
            print(f"[klausmate] browse toolkit scan unavailable: {exc}")
            return

        tier = self._tier()
        threshold = threshold_for(tier)
        seq = self._begin(LOADING_TEXT)
        cancel = threading.Event()
        self._cancel = cancel

        def progress(done: int, total: int) -> None:
            # Worker thread. Assigns ONE tuple and touches nothing else;
            # the main-thread QTimer above is what reaches the label.
            self._progress = (done, total)

        def work(col: Any) -> dict:
            from . import card_index

            index = card_index.load(_index_dir())
            if index is None:
                return {"error": NO_INDEX_TEXT}
            result = _dupes.scan_index(
                index,
                threshold=threshold,
                limit=SCAN_LIMIT,
                cancel=cancel,
                on_progress=progress,
            )
            pairs = result.pairs[:DISPLAY_CAP]
            texts = _note_texts(col, row_nids(build_rows(pairs, {})))
            return {
                "rows": build_rows(pairs, texts),
                "counts": dict(result.stats.counts or {}),
                "cancelled": bool(result.stats.cancelled),
                "tier": tier,
            }

        def done(payload: dict) -> None:
            if seq != self._seq or not self._alive():
                return
            self._finish()
            if payload.get("error"):
                self.host.set_status(str(payload["error"]))
                return
            self._absorb(payload)

        def failed(exc: Exception) -> None:
            print(f"[klausmate] duplicate scan failed: {exc}")
            if seq != self._seq or not self._alive():
                return
            self._finish()
            self.host.set_status(SCAN_FAILED_TEXT)

        op = QueryOp(parent=mw, op=work, success=done)
        op.failure(failed)
        op.run_in_background()

    def _on_selected_clicked(self) -> None:
        try:
            self._start_selected()
        except Exception as exc:
            print(f"[klausmate] browse toolkit selected lookup failed: {exc}")

    def _start_selected(self) -> None:
        reason = self.refusal()
        if reason:
            self.host.set_status(reason)
            return
        nids = selected_nids(self.browser)
        if not nids:
            self.host.set_status(NO_SELECTION_TEXT)
            return
        try:
            from aqt import mw
            from aqt.operations import QueryOp
        except Exception as exc:
            print(f"[klausmate] browse toolkit lookup unavailable: {exc}")
            return

        nid = nids[0]
        tier = self._tier()
        threshold = threshold_for(tier)
        seq = self._begin(LOADING_TEXT)
        self._cancel = None

        def work(col: Any) -> dict:
            from . import card_index

            index = card_index.load(_index_dir())
            if index is None:
                return {"error": NO_INDEX_TEXT}
            if _dupes.row_of(index, nid) < 0:
                return {"error": SELECTED_NOT_INDEXED_TEXT}
            pairs = _dupes.duplicates_of(
                index, nid, limit=DISPLAY_CAP, threshold=threshold
            )
            counts: dict = {}
            for pair in pairs:
                counts[pair.tier] = counts.get(pair.tier, 0) + 1
            texts = _note_texts(col, row_nids(build_rows(pairs, {})))
            return {
                "rows": build_rows(pairs, texts),
                "counts": counts,
                "cancelled": False,
                "tier": tier,
            }

        def done(payload: dict) -> None:
            if seq != self._seq or not self._alive():
                return
            self._finish()
            if payload.get("error"):
                self.host.set_status(str(payload["error"]))
                return
            self._absorb(payload)

        def failed(exc: Exception) -> None:
            print(f"[klausmate] duplicate lookup failed: {exc}")
            if seq != self._seq or not self._alive():
                return
            self._finish()
            self.host.set_status(SCAN_FAILED_TEXT)

        op = QueryOp(parent=mw, op=work, success=done)
        op.failure(failed)
        op.run_in_background()

    # ---- rendering ----

    def _absorb(self, payload: dict) -> None:
        self._rows = list(payload.get("rows") or [])
        self._counts = dict(payload.get("counts") or {})
        self._cancelled = bool(payload.get("cancelled"))
        self._scanned_tier = str(payload.get("tier") or "")
        self._render_rows()

    def _visible_rows(self) -> list:
        return sort_rows(self._rows, self._order())[:DISPLAY_CAP]

    def _fit_tree(self, count: int) -> None:
        """Size the tree to its CONTENT, between three and twelve rows.

        A fixed height would show six results in a half-empty box and
        would take that space from the note table for nothing.
        """
        try:
            row_h = self.tree.sizeHintForRow(0) if count else 0
            if row_h <= 0:
                row_h = FALLBACK_ROW_H
            chrome = (
                self.tree.header().sizeHint().height()
                + 2 * self.tree.frameWidth()
                + 4
            )
            visible = max(TREE_MIN_ROWS, min(int(count), TREE_MAX_ROWS))
            self.tree.setFixedHeight(
                min(RESULTS_MAX_H, chrome + row_h * visible)
            )
        except Exception as exc:
            print(f"[klausmate] browse toolkit tree fit failed: {exc}")

    def _show_empty(self, text: str) -> None:
        """No rows: hide the tree, put *text* where the eye already is.

        The strip's corner status is CLEARED here on purpose. Rendered
        with both, the refusal appeared twice on one screen — once in the
        panel and once in the corner — which reads as a bug rather than
        as emphasis. One message, one place: the panel owns the standing
        reason, the corner owns progress and the result summary.
        """
        self.tree.setVisible(False)
        self.empty.setText(text or EXACT_NOTE)
        self.empty.setVisible(True)
        self.host.set_status("")

    def _render_rows(self) -> None:
        try:
            self.tree.clear()
            rows = self._visible_rows()
            for row in rows:
                item = QTreeWidgetItem(
                    [
                        score_text(row.get("score")),
                        wording_label(row.get("overlap")),
                        row.get("text_a", ""),
                        row.get("text_b", ""),
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                item.setToolTip(COL_A, row.get("text_a", ""))
                item.setToolTip(COL_B, row.get("text_b", ""))
                self.tree.addTopLevelItem(item)
            # NOTHING pre-selected: the top of a cosine ranking is where
            # the contrast pairs live, so a default selection would aim
            # the user's next action at the rows he must not touch.
            self.tree.setCurrentItem(None)
            self.tree.clearSelection()
            self.show_btn.setEnabled(False)
            self.show_all_btn.setEnabled(bool(rows))
            summary = result_summary(
                len(rows), self._counts, self._scanned_tier, self._cancelled
            )
            if rows:
                self.empty.setVisible(False)
                self.tree.setVisible(True)
                self._fit_tree(len(rows))
                self.host.set_status(summary)
            else:
                self._show_empty(summary)
        except Exception as exc:
            print(f"[klausmate] browse toolkit render failed: {exc}")


def _build_duplicates_panel(host: BrowseToolkit) -> Any:
    """Registry factory for the ``duplicates`` tool."""
    return _DuplicatesPanel(host)


# ─────────────────────────────────────────────────────────────────────
# Installation
# ─────────────────────────────────────────────────────────────────────


def browse_body_layout(browser: Any) -> Any:
    """The vertical layout that owns Browse's splitter, or None.

    Found by walking from ``form.splitter`` — a widget every Browse
    window has — rather than by naming the generated
    ``verticalLayout_3``. Generated form attributes show the setupUi
    state only, and Anki mutates this window after setupUi;
    browse_toggles walks for the same reason.

    Since 2026-09-05 this is only ``install``'s FALLBACK: the strip lives
    in the note column's own layout (``browse_note_column``), and lands
    here — below the splitter, across the whole window — only when that
    column has no vertical box layout to append to.
    """
    form = getattr(browser, "form", None)
    split = getattr(form, "splitter", None)
    if split is None:
        return None
    parent = split.parentWidget()
    layout = parent.layout() if parent is not None else None
    if not isinstance(layout, QBoxLayout):
        return None
    try:
        if layout.direction() != QBoxLayout.Direction.TopToBottom:
            return None
    except Exception:
        return None
    return layout


class _CloseWatcher(QObject):  # type: ignore[misc]
    """Runs the strip's cleanup when its Browse window closes.

    Anki 26.8.1 ships NO ``browser_will_close`` hook — checked against
    ``_aqt/hooks.pyc``, which carries ``browser_will_show`` and
    ``browser_did_fetch_columns`` but nothing for closing — so this
    watches the window's own Close event instead
    (browse_toggles._VisibilityWatcher's shape). The seq token already
    makes a late callback harmless; this is about not burning a core on
    a scan whose window is gone.
    """

    def __init__(self, window: Any, strip: Any) -> None:
        super().__init__(window)
        self._strip = strip
        window.installEventFilter(self)

    def eventFilter(self, _obj, event) -> bool:  # noqa: N802 — Qt override
        try:
            if event.type() == QEvent.Type.Close:
                self._strip.cleanup()
            return False
        except Exception as exc:
            print(f"[klausmate] browse toolkit close watch failed: {exc}")
            return False


def browse_note_column(browser: Any) -> Any:
    """Browse's note-table column — the direct child of ``form.splitter``
    that holds ``form.tableView`` — or None.

    Naming the generated ``form.widget`` would break silently on an Anki
    rename, and Anki mutates this layout after setupUi.
    """
    form = getattr(browser, "form", None)
    split = getattr(form, "splitter", None)
    w = getattr(form, "tableView", None)
    if split is None or w is None:
        return None
    while w is not None and w.parentWidget() is not split:
        w = w.parentWidget()
    return w


def install(browser: Any) -> Any:
    """Put the strip under the note list of one Browse window. Idempotent.

    The strip is the last row of the note column's own vertical layout,
    so it spans the list and nothing else (Pouya, 2026-09-05: "only under
    the list of cards, not under the editor"). A Browse whose note column
    has no vertical box layout falls back to the body layout under the
    whole splitter — the pre-2026-09-05 placement.
    """
    existing = getattr(browser, "_klausmate_toolkit", None)
    if existing is not None:
        return existing
    col = browse_note_column(browser)
    layout = col.layout() if col is not None else None
    if not (isinstance(layout, QBoxLayout)
            and layout.direction() == QBoxLayout.Direction.TopToBottom):
        layout = browse_body_layout(browser)
    if layout is None:
        print("[klausmate] browse toolkit: nowhere to put the strip in Browse")
        return None
    strip = BrowseToolkit(browser)
    layout.addWidget(strip)
    browser._klausmate_toolkit = strip  # type: ignore[attr-defined]
    try:
        browser._klausmate_toolkit_watch = _CloseWatcher(browser, strip)
    except Exception as exc:
        print(f"[klausmate] browse toolkit close watch install failed: {exc}")
    print("[klausmate] browse toolkit installed")
    return strip


def _on_browser_will_show(browser: Any) -> None:
    """Deferred one tick, browse_toggles' pattern: ``setupUi`` has to
    have finished wiring the form before we touch its layout."""

    def _deferred() -> None:
        try:
            install(browser)
        except Exception as exc:
            print(f"[klausmate] browse toolkit install failed: {exc}")

    try:
        QTimer.singleShot(0, _deferred)
    except Exception as exc:
        print(f"[klausmate] browse toolkit defer failed: {exc}")
        _deferred()


def _on_theme_change() -> None:
    """Re-style one tick after the whole theme_did_change chain —
    window_chrome's deferral, for window_chrome's reason (Anki's own
    Browse handlers run in that chain too)."""

    def _walk() -> None:
        try:
            from aqt import dialogs

            browser = dialogs._dialogs.get("Browser", [None, None])[1]
        except Exception:
            browser = None
        strip = getattr(browser, "_klausmate_toolkit", None)
        if strip is not None:
            strip.apply_theme()

    try:
        QTimer.singleShot(0, _walk)
    except Exception as exc:
        print(f"[klausmate] browse toolkit theme walk failed: {exc}")


def setup_hooks() -> None:
    """ONE line from __init__.py registers the whole surface —
    curation.setup_hooks' shape, because that file is enormous and every
    lane wants a piece of it."""
    try:
        from aqt import gui_hooks

        gui_hooks.browser_will_show.append(_on_browser_will_show)
        gui_hooks.theme_did_change.append(_on_theme_change)
    except Exception as exc:
        print(f"[klausmate] browse toolkit setup failed: {exc}")
