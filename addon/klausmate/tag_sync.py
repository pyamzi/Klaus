"""Per-PDF `!Library` tags — forward direction (PDF -> tag) AND, as of
K-054, the reverse (a tag renamed in Anki's own tag sidebar renames the
PDF in the Library).

Pouya: "add to index / re-index should automatically create the tags.
also, the tags should ALWAYS follow the name of the PDF and the PDF
should always follow the names of the tag, those two are always the
same." The forward half (events 1-4 below) is K-053. The reverse half
(`plan_reconcile`/`reconcile_from_tags`/`reconcile_on_profile_open`, at
the end of this file) is K-054 — see that section's own docstrings for
why it is INFERENCE from a before/after tag diff, never a real event.

THE INVARIANT: every indexed PDF owns exactly one collection tag,
``!Library::<folder path, / -> ::>::<leaf>``, where ``leaf`` is the PDF's
display name minus a trailing ``.pdf``/``.txt``, sanitized tag-legal. The
tag's members are exactly the notes whose cached match score is at or
above that PDF's sensitivity threshold. The four reserved leaves
(``Curating``, ``Curated``, ``Matching`` — the static tags already living
at the ``!Library`` root; see curation.CURATED_TAG. ``Matching``
was retention.py's own Browse-preview tag until K-055 retired it — kept
reserved anyway so a PDF literally named "Matching" can never collide
with that historical name — and ``Doubtful``, K-254's own root tag, whose
members are the pertinence-rejected nids each PDF still matches,
unioned across every PDF) get
a ``-pdf`` suffix if a display name would otherwise collide with one of
them at the root.

State: each PDF's prefs.json entry (the same file retention.py's
threshold overrides live in) gains a ``"tag"`` key — the last tag name
this module actually applied. Renames and deletes act on THAT STORED
VALUE, never on a value re-derived from the current display name/folder —
recomputing "what the old tag must have been" would be a guess, and a
wrong guess either orphans real note tags or silently no-ops a rename.
retention.forget_prefs/clear_threshold_overrides already preserve unknown
entry keys (K-049/K-052 groundwork; tested there), which is what lets
``tag`` ride along through both of those without this module touching
either function.

Four forward sync events, each exactly ONE undoable CollectionOp
(add_custom_undo_entry / merge_undo_entries — the pattern
curation.create_curated_deck uses; tag_migrate.run_migration's docstring
explains the OpChanges contract this must never violate: the op MUST
return ``col.merge_undo_entries(pos)``, never a plain dict/list/None, or
every caller of that op crashes before its success callback ever runs):

1. ``sync_after_matches`` — called from BOTH completion points that
   finish a PDF's match pipeline (pdf_drive._on_embed's after_matches,
   curation.run_curation's after_matches). This is "indexing creates the
   tag" itself.
2. ``sync_after_threshold`` (single PDF, pdf_drive._on_threshold's OK) and
   ``sync_after_clear_overrides`` (manage_models' "apply to all tuned
   PDFs" path, batched into one undo entry) — sensitivity changes re-diff
   membership at the new cut.
3. ``sync_after_rename`` (display rename / move to folder) and
   ``sync_after_folder_rename`` (batched across every PDF the folder move
   affects, in ONE undo entry) — renames the STORED tag to the newly
   computed desired one.
4. ``sync_after_delete`` — removes the stored tag entirely. Must run
   BEFORE pdf_handler.delete_context, which calls retention.forget_prefs
   and wipes the whole prefs entry (including "tag") — this module has no
   other way to learn what the tag was afterwards.

SAFETY: a cold or invalid matches cache (retention.load_matches -> None)
is a NO-OP with a printed status line, never a tag strip — only a real,
freshly-known score may shrink membership. The kill switch is the config
key ``library_tags_enabled`` (default True, read via ``cfg.get``).

Layout mirrors retention.py: pure logic up top (sanitizer, desired_tag,
membership diff, and the col-only apply_* helpers — all importable and
testable without aqt, taking a col-like double instead of touching
``aqt.mw``), aqt glue at the bottom. Only the two names tag_migrate.py
itself needs at module scope (``aqt.mw``, ``aqt.operations.CollectionOp``)
plus ``aqt.utils.tooltip`` are imported at the top of this file; every
klausmate sibling module (curation, retention, drive_store, pdf_handler,
card_index, embeddings, pdf_index) is imported lazily inside the function
that needs it, both to dodge the retention<->curation import order (same
reason curation.run_curation defers its own `from . import retention`)
and to keep this module importable under a minimal aqt stub for tests.
"""

from __future__ import annotations

import re
from typing import Callable

from aqt import mw
from aqt.operations import CollectionOp
from aqt.utils import tooltip

CONFIG_KEY = "library_tags_enabled"

# The three tags already anchored at the !Library root before this module
# existed (curation's preview tag, curation's post-copy tag, and
# retention's Browse-preview tag — retired outright by K-055, but its name
# stays reserved below). Hardcoded as literal strings rather than imported from
# curation/retention: this file's pure section must stay import-free (see
# module docstring) so it can be unit-tested under the same minimal aqt
# stub tag_migrate.py already uses, and these three names are exactly as
# stable as tag_migrate.TAG_RENAME_MAP's old side — they name tags that
# already exist in shipped collections and must never quietly drift.
# "doubtful" joined them in K-254: DOUBTFUL_TAG below is Klaus's own new
# root tag (pertinence-rejected cards), reserved the same way so a PDF
# literally named "Doubtful.pdf" can never collide with it either.
RESERVED_LEAVES = frozenset({"curating", "curated", "matching", "doubtful"})

# The Doubtful tag (K-254, spec D5): membership is the UNION, across
# every PDF's judged.json, of the pertinence-rejected nids that PDF
# STILL matches at/above its threshold (`doubtful_members`, final review
# 2026-09-17) — global, not per-PDF, unlike every other tag this module
# manages. _do_sync_one
# recomputes it in full (apply_membership's own diff) whenever a caller
# hands it a `doubtful` set; passing None leaves it untouched entirely.
DOUBTFUL_TAG = "!Library::Doubtful"

_WHITESPACE_RE = re.compile(r"\s+")
_UNDERSCORE_RUN_RE = re.compile(r"_+")


# ------------------------------------------------------------ pure logic


def library_tags_enabled(cfg: dict) -> bool:
    """The kill switch: ``library_tags_enabled`` in the addon config,
    default True. Every public sync_* function checks this first."""
    return bool(cfg.get(CONFIG_KEY, True))


def strip_pdf_ext(display: str) -> str:
    """Display name minus a trailing ``.pdf`` or ``.txt`` (case-insensitive).

    Deliberately NOT pdf_handler._safe_basename: that helper sanitizes
    for the FILESYSTEM (a different, more aggressive alphabet) and is
    the wrong tool for deriving a tag's display-facing leaf. The two
    extensions come from curation.suggest_deck_name, which used the
    same pair for the deck names it minted — K-146 deleted that
    function with the curate button; this list outlived it.
    """
    name = display or ""
    lower = name.lower()
    if lower.endswith(".pdf") or lower.endswith(".txt"):
        return name[:-4]
    return name


def _sanitize_segment(text: str) -> str:
    """One tag-path segment, tag-legal: spaces -> underscore, any literal
    ``::`` stripped (it would otherwise smuggle in a phantom hierarchy
    level), repeated underscores collapsed to one, edge underscores
    trimmed. Applied to every segment — folder parts AND the leaf — since
    Anki tags are whitespace-delimited in a note's tags field: a raw space
    anywhere in a tag string would silently split it into two tags, not
    just look untidy.
    """
    text = (text or "").strip()
    text = text.replace("::", "")
    text = _WHITESPACE_RE.sub("_", text)
    text = _UNDERSCORE_RUN_RE.sub("_", text)
    return text.strip("_")


def desired_tag(folder: str | None, display: str) -> str:
    """The one tag this PDF should own right now, per THE INVARIANT.

    ``folder`` is a drive_store folder path ("Anatomy/Week 3") or None/""
    for root. ``display`` is the PDF's drive_store display name (still
    carrying its .pdf extension, spaces, whatever the user typed).

    Reserved-leaf collision (a display name that sanitizes to "Curating",
    "Curated", "Matching" — historical: retention.py's own Browse-preview
    tag until K-055 retired it — or "Doubtful", K-254's own root tag) only
    matters at the !Library ROOT — nested under any folder the full tag
    path already differs from the reserved one, so only the folder-less
    case gets the "-pdf" suffix.
    """
    leaf = _sanitize_segment(strip_pdf_ext(display)) or "PDF"
    segments = [s for s in (_sanitize_segment(p) for p in (folder or "").split("/")) if s]
    if not segments and leaf.lower() in RESERVED_LEAVES:
        leaf = f"{leaf}-pdf"
    segments.append(leaf)
    return "::".join(["!Library", *segments])


def diff_membership(desired: set[int], current: set[int]) -> tuple[list[int], list[int]]:
    """(to_add, to_remove) — sorted for deterministic tests/logging."""
    return sorted(desired - current), sorted(current - desired)


# ---------------------------------------------- reverse-direction (K-054)
#
# THE INVARIANT is bidirectional (Pouya): "the tags should ALWAYS follow
# the name of the PDF and the PDF should always follow the names of the
# tag." Everything above is the forward half. Below is the reverse: a tag
# renamed in Anki's OWN tag sidebar renames the PDF in the Library. Anki
# fires no "tag renamed" event for that — the sidebar's rename UI is just
# col.tags.rename() under the hood, indistinguishable from any other tag
# mutation — so this is RECONSTRUCTION from a before/after diff of stored
# vs. current tags, never a signal. `plan_reconcile` is the pure decision
# core, fully unit-tested; `reconcile_from_tags` (aqt glue, at the end of
# this file) is the only caller and the only thing that touches
# col/drive_store/prefs.json for real.


def _is_reserved_tag(tag: str) -> bool:
    """True only for the exact !Library-root reserved tags (curation's
    !Library::Curating/Curated, plus !Library::Matching — retention.py's
    own Browse-preview tag until K-055 retired it) — these
    can never be treated as an orphaned PDF tag up for claiming, even
    though nothing about their shape otherwise distinguishes them from a
    real PDF tag. Mirrors desired_tag's own root-only collision guard
    (RESERVED_LEAVES): a leaf that merely matches one of these names
    NESTED under a folder (``!Library::Foo::Curating``) is an ordinary
    PDF tag and stays claimable — the same root-vs-nested line
    desired_tag's own docstring draws.
    """
    parts = tag.split("::")
    return len(parts) == 2 and parts[0] == "!Library" and parts[1].lower() in RESERVED_LEAVES


def _tag_to_folder_display(tag: str) -> tuple[str | None, str]:
    """Reverse of desired_tag's shape: split a ``!Library::...::Leaf`` tag
    back into (folder path with '/' separators, or None at the root; the
    leaf as a display string).

    LOSSY ON PURPOSE, and this is the one place it matters: desired_tag's
    sanitizer (``_sanitize_segment``) turns every space into an
    underscore before a name ever reaches a tag, so once a name is inside
    a tag string there is no way to tell "this underscore used to be a
    space" from "this was a genuine underscore in the display name" —
    reversing it can only ever guess "space". A PDF named
    "cell_biology.pdf" whose tag gets renamed in the sidebar will
    therefore round-trip its RECOMPUTED leaf as "cell biology" (a space)
    — a rare, purely cosmetic surprise, accepted rather than building an
    escaping scheme for it (see the card notes on this — do not add one).
    """
    parts = [p for p in tag.split("::") if p]
    if parts and parts[0] == "!Library":
        parts = parts[1:]
    if not parts:
        return None, ""
    restored = [p.replace("_", " ").strip() for p in parts]
    leaf = restored[-1]
    folder = "/".join(restored[:-1]) if len(restored) > 1 else None
    return folder, leaf


def _display_with_ext(new_leaf: str, old_display: str) -> str:
    """The display name to actually store for a confident rename: the
    tag's reconstructed leaf, with whatever real filename extension the
    OLD display carried (drive_store's ``display`` always carries one —
    see drive_store.record_import) re-appended. Same extension list as
    strip_pdf_ext, kept in sync on purpose — losing the extension would
    make the Library stop recognizing the row's file type.
    """
    lower = (old_display or "").lower()
    if lower.endswith(".pdf") or lower.endswith(".txt"):
        return f"{new_leaf}{old_display[-4:]}"
    return new_leaf


def plan_reconcile(stored_by_safe: dict[str, str], existing_tags: set[str]) -> dict:
    """The reverse-direction decision core, pure and fully testable: no
    col, no prefs.json, no drive_store — just "what WAS stored" (every
    indexed PDF's ``get_stored_tag`` value) against "what tags exist
    right now" (``col.tags.all()``).

    Per-PDF: a stored tag still present means nothing happened to it.
    ``missing`` collects every PDF whose stored tag disappeared.

    If ``missing`` is empty, the plan is a structural no-op regardless of
    anything else — this is also Pouya's actual day-one state: an empty
    ``stored_by_safe`` (no PDF has a stored tag yet) always plans a
    no-op, without even needing ``existing_tags``.

    Otherwise, ``candidates`` is every ``!Library::``-prefixed tag that
    IS currently in the collection, is NOT any PDF's stored tag (missing
    OR still-present — a tag another PDF already owns is never up for
    claiming), and is not one of the three reserved root tags
    (``_is_reserved_tag``).

    Exactly one missing PDF and exactly one candidate -> a confident
    rename: that PDF became that tag in the sidebar. Anything else
    (several missing, several candidates, or zero candidates for a real
    miss) is ambiguous and NEVER guessed at — the action is "reapply",
    meaning every missing PDF gets its deterministically-computed tag
    restored instead (PDF wins ties: our side is deterministic, the
    sidebar's diff is not).
    """
    missing = {safe: tag for safe, tag in stored_by_safe.items() if tag not in existing_tags}
    if not missing:
        return {"missing": {}, "candidates": [], "action": "noop", "rename": None}

    all_stored = set(stored_by_safe.values())
    candidates = sorted(
        t
        for t in existing_tags
        if t.startswith("!Library::") and t not in all_stored and not _is_reserved_tag(t)
    )

    if len(missing) == 1 and len(candidates) == 1:
        safe, old_tag = next(iter(missing.items()))
        return {
            "missing": missing,
            "candidates": candidates,
            "action": "rename",
            "rename": {"safe": safe, "old": old_tag, "new": candidates[0]},
        }

    return {"missing": missing, "candidates": candidates, "action": "reapply", "rename": None}


# --------------------------------------------------- col-only apply layer
#
# These four take a col-like object (real Anki collection, or a test
# double exposing find_notes/tags.bulk_add/tags.bulk_remove/tags.rename/
# tags.remove) and nothing else klausmate-specific — no aqt.mw, no config,
# no drive_store/prefs lookups. That keeps them testable exactly like
# tag_migrate.run_migration is tested against FakeCol, independent of the
# "what tag should this be" resolution the aqt-glue layer below does.


def _escape_tag(tag: str) -> str:
    return tag.replace("\\", "\\\\").replace('"', '\\"')


def apply_membership(col, tag: str, desired: set[int]) -> tuple[list[int], list[int]]:
    """Diff `tag`'s current members against `desired` and bulk add/remove
    the difference. Returns (added, removed) — empty lists if already in
    sync (a real no-op: no bulk_add/bulk_remove call at all)."""
    current = set(col.find_notes(f'tag:"{_escape_tag(tag)}"'))
    to_add, to_remove = diff_membership(set(desired), current)
    if to_add:
        col.tags.bulk_add(to_add, tag)
    if to_remove:
        col.tags.bulk_remove(to_remove, tag)
    return to_add, to_remove


def apply_rename(col, old: str | None, new: str) -> bool:
    """Rename `old` -> `new` if `old` is a real, different stored tag.
    False (no-op, no col call at all) when there is nothing to rename —
    ``old`` falsy (never indexed yet) or already equal to ``new``."""
    if not old or old == new:
        return False
    col.tags.rename(old, new)
    return True


def apply_renames(col, pairs: list[tuple[str | None, str]]) -> list[tuple[str, str]]:
    """Batch form of apply_rename for one undo entry covering many PDFs
    (folder rename). Returns the pairs that actually renamed."""
    done: list[tuple[str, str]] = []
    for old, new in pairs:
        if apply_rename(col, old, new):
            done.append((old, new))
    return done


def apply_removal(col, tag: str | None) -> bool:
    """Drop `tag` from the collection entirely (PDF deletion). False, no
    col call, when there was never a stored tag to remove."""
    if not tag:
        return False
    col.tags.remove([tag])
    return True


# ------------------------------------------------------------- prefs glue


def _safe(name: str) -> str:
    from . import pdf_handler

    return pdf_handler._safe_basename(name)


def get_stored_tag(safe: str) -> str | None:
    """The tag this module last applied for `safe`, or None if it has
    never indexed/tagged this PDF. NEVER a derived guess — see module
    docstring on why renames/removals must use exactly this value."""
    from . import retention

    entry = retention._load_prefs().get(safe)
    if isinstance(entry, dict):
        tag = entry.get("tag")
        if tag:
            return str(tag)
    return None


def set_stored_tag(safe: str, tag: str) -> None:
    from . import pdf_handler, retention

    prefs = retention._load_prefs()
    prefs.setdefault(safe, {})["tag"] = tag
    pdf_handler._atomic_write_json(retention._prefs_path(), prefs, separators=(",", ":"))


def _folder_and_display(safe: str) -> tuple[str | None, str]:
    from . import curation, drive_store

    data = drive_store.load(curation.USER_FILES)
    entry = data.get("pdfs", {}).get(safe) or {}
    return entry.get("folder"), (entry.get("display") or safe)


def _cached_matches(safe: str, cfg: dict) -> list[tuple[int, float]] | None:
    """The current matches.json cache for `safe`, or None if it's cold,
    missing, or invalidated (card index not ready, signature mismatch,
    etc). None here is exactly retention.load_matches' "don't know" —
    callers must treat it as a no-op, never as "zero matches"."""
    from . import card_index, embeddings, pdf_index, retention

    cfg_sig = embeddings.index_signature(cfg)
    src_sig = pdf_index.source_signature(retention.USER_FILES, safe)
    cidx = card_index.load(retention.INDEX_DIR)
    if cidx is None or not card_index.check_signature(cidx, cfg_sig):
        return None
    digest = retention.card_index_digest(cidx)
    cached = retention.load_matches(safe, cfg_sig, cidx.dims, src_sig, digest)
    return cached[0] if cached is not None else None


def _do_sync_one(
    col, safe: str, tag: str, desired_nids: set[int], doubtful: set[int] | None = None
) -> dict:
    """The membership-diff body shared by sync_after_matches,
    sync_after_threshold, and sync_after_clear_overrides. Self-healing:
    if the stored tag exists but doesn't match the freshly computed
    desired one (should only happen if a rename event was somehow missed
    — see module docstring), carries the old tag's members across before
    diffing, rather than leaving them orphaned under a dead tag name.

    ``doubtful`` (K-254) is the GLOBAL set of pertinence-rejected nids —
    not scoped to `safe` — so this recomputes DOUBTFUL_TAG's membership
    in full via the same apply_membership diff, exactly like every other
    tag here. None (the default) leaves DOUBTFUL_TAG untouched entirely,
    which is what lets plain indexing/curating (sync_after_matches with
    no judge pass yet run) skip it rather than wiping real verdicts.
    """
    stored = get_stored_tag(safe)
    renamed = apply_rename(col, stored, tag)
    added, removed = apply_membership(col, tag, desired_nids)
    if stored != tag:
        set_stored_tag(safe, tag)
    doubtful_added: list[int] = []
    doubtful_removed: list[int] = []
    if doubtful is not None:
        doubtful_added, doubtful_removed = apply_membership(col, DOUBTFUL_TAG, doubtful)
    return {
        "tag": tag,
        "added": added,
        "removed": removed,
        "renamed": renamed,
        "doubtful_added": doubtful_added,
        "doubtful_removed": doubtful_removed,
    }


def _at_threshold_nids(safe: str, cfg: dict) -> set[int] | None:
    """Every nid currently at or above `safe`'s sensitivity threshold, read
    RAW from its matches.json — or None when that file cannot be read.

    Raw on purpose, exactly as `pertinence._matched_pages` reads the same
    file: the validated `retention.load_matches` answers None for every PDF
    whose cached ranking is cold after ANY card-index change, so validating
    here would defeat the intersection below for every PDF except the one
    just indexed. None is "don't know", never "nobody" — a caller must
    never strip on it.
    """
    import json
    import os.path

    from . import retention

    try:
        with open(retention._matches_path(safe), encoding="utf-8") as f:
            rows = (json.load(f) or {}).get("matches") or []
        threshold = retention.get_threshold(safe, cfg)
        return {int(nid) for nid, score in rows if float(score) >= threshold}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"[klausmate] tag_sync: no readable matches for {safe!r} ({exc}) — its rejections all stand.")
        return None


def doubtful_members(cfg: dict) -> set[int]:
    """DOUBTFUL_TAG's membership: every pertinence-rejected nid that is
    STILL one of its PDF's at-threshold candidates (final review I-3).

    `pertinence.all_rejected` alone unions every verdict ever written, and
    judged.json is only ever added to — so raising a lecture's Match
    Sensitivity (or editing a note until it stops matching) left the old
    rejection in place and the card wearing `!Library::Doubtful` though no
    PDF doubted it any more, with no path back: it is only re-judged if it
    becomes that PDF's candidate again. Invisible inside Klaus (the counts
    and "Doubtful cards…" both re-intersect) but not to a user's own search
    or filtered deck on the bare tag. Intersecting HERE, at the one reader
    all the sinks share, self-heals on the next sync of any kind.

    The union across PDFs stays: a card rejected for A but confirmed for B
    is still Doubtful. That is the spec's rule (and a known design debt —
    per-card overrule is a board card), not something this narrowing
    touches.

    Never raises for one bad PDF, and never strips on missing data: a PDF
    whose matches.json is absent or unreadable keeps its whole rejected
    set.
    """
    import os

    from . import pertinence, retention

    user_files = retention.USER_FILES
    out: set[int] = set()
    try:
        names = os.listdir(os.path.join(user_files, "pdf_index"))
    except OSError:
        return out
    for safe in names:
        if not os.path.isfile(pertinence.judged_path(user_files, safe)):
            continue
        rejected = pertinence.rejected_nids(pertinence.load_judged(user_files, safe))
        if not rejected:
            continue
        at_threshold = _at_threshold_nids(safe, cfg)
        out |= rejected if at_threshold is None else (rejected & at_threshold)
    return out


# ------------------------------------------------------------- aqt glue


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _cfg() -> dict:
    return _pkg().get_config()


def _run_sync_op(
    parent,
    undo_label: str,
    work: Callable[[object], dict | None],
    *,
    on_done: Callable[[dict], None] | None = None,
    on_finished: Callable[[], None] | None = None,
) -> None:
    """Fire exactly one CollectionOp for one sync event. `work(col)` does
    the tag mutation(s) and returns a plain dict describing what happened
    — auxiliary data flows through that dict/closure, never through the
    op's return value, which MUST be exactly ``col.merge_undo_entries(pos)``
    (see module docstring; this is the one place that contract is
    satisfied, so every event above builds on it instead of re-risking the
    2026-08-23 crash per call site).
    """
    result: dict = {}

    def op(col):
        pos = col.add_custom_undo_entry(undo_label)
        result.update(work(col) or {})
        return col.merge_undo_entries(pos)

    def done(_changes) -> None:
        if on_done:
            on_done(result)
        if on_finished:
            on_finished()

    def fail(exc: Exception) -> None:
        # on_finished fires on BOTH outcomes — callers use it to sequence
        # follow-on work (curation's Browse preview) and to release the
        # pipeline busy token; skipping it on failure would deadlock that.
        print(f"[klausmate] tag_sync: {undo_label!r} failed: {exc}")
        if on_finished:
            on_finished()

    CollectionOp(parent=parent, op=op).success(done).failure(fail).run_in_background()


def _phrase_counts(added: int, removed: int) -> str:
    parts = []
    if added:
        parts.append(f"{added} added")
    if removed:
        parts.append(f"{removed} removed")
    return ", ".join(parts) or "no change"


def _tooltip_membership(parent, display: str, result: dict) -> None:
    added, removed = len(result.get("added") or []), len(result.get("removed") or [])
    if not added and not removed:
        return
    tooltip(f"“{display}” in !Library: {_phrase_counts(added, removed)}.", parent=parent)


def sync_after_matches(
    parent,
    pdf_name: str,
    matches: list[tuple[int, float]] | None,
    *,
    doubtful: set[int] | None = None,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Event 1 — indexing/curating a PDF creates or refreshes its tag.

    Called from BOTH completion points that finish a PDF's match pipeline
    (pdf_drive._on_embed's after_matches, curation.run_curation's
    after_matches) with whatever ensure_matches just handed back. That
    value is never None in practice — ensure_matches raises on failure
    rather than returning None — the guard below is defense in depth only,
    matching every other event's "never strip on missing data" rule.

    ``doubtful`` (K-254) is passed straight through to `_do_sync_one`;
    None (the default — every call site above except the judge phase)
    leaves DOUBTFUL_TAG untouched, so plain indexing never re-derives it
    from a stale or absent judged.json. The judge phase (index_queue's
    phase four, Task 3) is the one caller that passes
    `doubtful_members(cfg)` here.

    ``on_done`` (K-064) fires exactly once when the event is SETTLED —
    after the sync op succeeds or fails, and immediately on every early
    return (tags disabled, no matches, exception). Curation sequences its
    Browse preview through it, since the preview searches the tag this
    event writes; a path that skipped it would strand curation's busy
    token forever.
    """
    _settled = {"done": False}

    def settled() -> None:
        if _settled["done"] or on_done is None:
            _settled["done"] = True
            return
        _settled["done"] = True
        try:
            on_done()
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] tag_sync: on_done callback failed: {exc}")

    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg):
            settled()
            return
        safe = _safe(pdf_name)
        if matches is None:
            print(f"[klausmate] tag_sync: no matches for {safe!r} — skipping tag sync.")
            settled()
            return
        from . import retention

        threshold = retention.get_threshold(safe, cfg)
        folder, display = _folder_and_display(safe)
        tag = desired_tag(folder, display)
        desired_nids = {nid for nid, score in matches if score >= threshold}

        _run_sync_op(
            parent,
            f"Klaus: tag “{display}” in !Library",
            lambda col: _do_sync_one(col, safe, tag, desired_nids, doubtful),
            on_done=lambda result: _tooltip_membership(parent, display, result),
            on_finished=settled,
        )
    except Exception as exc:  # noqa: BLE001 - never break the indexing pipeline
        print(f"[klausmate] tag_sync: sync_after_matches failed for {pdf_name!r}: {exc}")
        settled()


def sync_after_threshold(
    parent, pdf_name: str, matches: list[tuple[int, float]] | None, threshold: float
) -> None:
    """Event 2 (single PDF) — pdf_drive._on_threshold's OK.

    `matches` should be the caller's already-loaded cache for this PDF
    (DriveWindow.matches[safe]) — the same value the dialog's own live
    preview already uses, so "no cached matches yet" reads identically in
    both places instead of the tag sync silently disagreeing with what
    the dialog just showed.

    Doubtful (K-254) is recomputed from `doubtful_members(cfg)` here —
    never re-judged — so dragging the sensitivity slider can never spend
    a paid pass; it only reflects whatever verdicts already exist. That
    read is its own try/except (K-254 review Important 2): a failure
    there falls back to `doubtful=None` rather than aborting the retag
    the user just confirmed — only the primary tag sync's own failure
    (below) does that.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg):
            return
        if matches is None:
            print(f"[klausmate] tag_sync: no cached matches for {pdf_name!r} — sensitivity change not synced to tags.")
            return
        safe = _safe(pdf_name)
        folder, display = _folder_and_display(safe)
        tag = desired_tag(folder, display)
        desired_nids = {nid for nid, score in matches if score >= threshold}

        # K-254 review Important 2: guarded on its own, same shape as
        # priority_rows — a failure in the AUXILIARY Doubtful read must
        # never take down the PRIMARY retag the user just confirmed by
        # moving the slider.
        try:
            doubtful = doubtful_members(cfg)
        except Exception as exc:
            print(f"[klausmate] tag_sync: doubtful set unavailable: {exc}")
            doubtful = None

        _run_sync_op(
            parent,
            f"Klaus: retag “{display}” for new sensitivity",
            lambda col: _do_sync_one(col, safe, tag, desired_nids, doubtful),
            on_done=lambda result: _tooltip_membership(parent, display, result),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tag_sync: sync_after_threshold failed for {pdf_name!r}: {exc}")


def sync_after_clear_overrides(parent, cleared_safes: list[str]) -> None:
    """Event 2 (batch) — manage_models' "apply new default to already-
    tuned PDFs" path, i.e. every caller of retention.clear_threshold_overrides.
    `cleared_safes` must be the exact list of safe basenames whose
    override was just cleared (retention.threshold_override_names(),
    captured BEFORE calling clear_threshold_overrides — that function
    itself only returns a count). One undo entry for the whole batch,
    matching the folder-rename batching rule below. A PDF whose matches
    cache is cold is skipped individually (never strips that one PDF's
    tag) without blocking the rest of the batch. Doubtful (K-254) is
    computed ONCE from `doubtful_members(cfg)` for the whole batch —
    never re-judged, and never per-PDF, since it is one global tag. That
    computation is its own try/except (K-254 review Important 2,
    mirroring sync_after_threshold above): a failure there is
    `doubtful=None` for the whole batch, never a reason to skip the
    retag every cleared PDF is here for.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg) or not cleared_safes:
            return
        from . import retention

        # K-254 review Important 2: same guard as sync_after_threshold —
        # an auxiliary Doubtful-read failure must not cancel the whole
        # batch's retag.
        try:
            doubtful = doubtful_members(cfg)
        except Exception as exc:
            print(f"[klausmate] tag_sync: doubtful set unavailable: {exc}")
            doubtful = None
        plans: list[tuple[str, str, set[int]]] = []
        for safe in cleared_safes:
            matches = _cached_matches(safe, cfg)
            if matches is None:
                print(f"[klausmate] tag_sync: no cached matches for {safe!r} — skipped in apply-to-all retag.")
                continue
            threshold = retention.get_threshold(safe, cfg)
            folder, display = _folder_and_display(safe)
            tag = desired_tag(folder, display)
            plans.append((safe, tag, {nid for nid, score in matches if score >= threshold}))
        if not plans:
            return

        def work(col):
            added = removed = 0
            for safe, tag, desired_nids in plans:
                r = _do_sync_one(col, safe, tag, desired_nids, doubtful)
                added += len(r["added"])
                removed += len(r["removed"])
            return {"added": added, "removed": removed, "count": len(plans)}

        def done(result: dict) -> None:
            if not result.get("added") and not result.get("removed"):
                return
            tooltip(
                f"!Library tags updated for {result.get('count', 0)} PDF(s): "
                f"{_phrase_counts(result.get('added', 0), result.get('removed', 0))}.",
                parent=parent,
            )

        _run_sync_op(parent, "Klaus: retag PDFs for new default sensitivity", work, on_done=done)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tag_sync: sync_after_clear_overrides failed: {exc}")


def sync_after_rename(parent, pdf_name: str) -> None:
    """Event 3 (single PDF) — pdf_drive._rename_pdf / _move_pdf. Call
    AFTER drive_store has already recorded the new display name/folder.
    A no-op (no CollectionOp fired at all) when the PDF has never been
    indexed — there is no stored tag to rename, and event 1 will create
    the right one the first time it is.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg):
            return
        safe = _safe(pdf_name)
        stored = get_stored_tag(safe)
        if not stored:
            return
        folder, display = _folder_and_display(safe)
        desired = desired_tag(folder, display)
        if desired == stored:
            return

        def work(col):
            apply_rename(col, stored, desired)
            set_stored_tag(safe, desired)
            return {"renamed": True}

        _run_sync_op(
            parent,
            f"Klaus: rename !Library tag for “{display}”",
            work,
            on_done=lambda _r: tooltip(f"“{display}”: !Library tag renamed.", parent=parent),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tag_sync: sync_after_rename failed for {pdf_name!r}: {exc}")


def sync_after_folder_rename(parent, safes: list[str]) -> None:
    """Event 3 (batch) — pdf_drive._rename_folder. `safes` is every PDF
    drive_store just reparented under the renamed folder (direct children
    and nested descendants alike) — collect them from drive_store AFTER
    calling drive_store.rename_folder, before calling this. Batched into
    ONE undo entry regardless of how many PDFs are affected.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg) or not safes:
            return
        pairs: list[tuple[str, str]] = []
        updates: list[tuple[str, str]] = []
        for safe in safes:
            stored = get_stored_tag(safe)
            if not stored:
                continue
            folder, display = _folder_and_display(safe)
            desired = desired_tag(folder, display)
            if desired != stored:
                pairs.append((stored, desired))
                updates.append((safe, desired))
        if not pairs:
            return

        def work(col):
            apply_renames(col, pairs)
            for safe, desired in updates:
                set_stored_tag(safe, desired)
            return {"count": len(pairs)}

        _run_sync_op(
            parent,
            "Klaus: rename !Library tags for moved folder",
            work,
            on_done=lambda result: tooltip(
                f"!Library tags updated for {result.get('count', 0)} PDF(s).", parent=parent
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tag_sync: sync_after_folder_rename failed: {exc}")


def sync_after_delete(parent, pdf_name: str, display: str | None = None) -> None:
    """Event 4 — pdf_drive._delete_pdf. Call BEFORE
    pdf_handler.delete_context: that function calls retention.forget_prefs,
    which drops the WHOLE prefs.json entry for this PDF (including "tag")
    — this module has no other record of what the tag was. The stored tag
    is read synchronously, before the async CollectionOp is even queued,
    so the later forget_prefs call (which runs synchronously, right after
    this returns) can never race the read.

    No tooltip on success — _delete_pdf already shows its own "Deleted
    ..." tooltip immediately after this call, and two tooltips racing for
    the same action is exactly the K-038 stacking bug the house style
    guards against.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg):
            return
        safe = _safe(pdf_name)
        stored = get_stored_tag(safe)
        if not stored:
            return
        label = display or safe

        _run_sync_op(
            parent,
            f"Klaus: remove !Library tag for “{label}”",
            lambda col: {"removed": apply_removal(col, stored)},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tag_sync: sync_after_delete failed for {pdf_name!r}: {exc}")


def _reapply_missing(col, missing: dict[str, str], cfg: dict) -> None:
    """The ambiguous-case fallback for reconcile_from_tags: recreate each
    vanished tag from ITS OWN last cached match scores — never from
    ``missing``'s old tag strings, which named something that no longer
    exists and (in every multi-missing/multi-candidate case this is
    reached for) may have been reused for a wholly unrelated tag by
    whatever happened in the sidebar. A PDF with no usable matches cache
    is skipped individually (never fabricates membership out of nothing
    — the same "cold cache is a no-op, not a strip" rule every forward
    event already follows) without blocking the rest of the batch. One
    CollectionOp/undo entry for the whole batch, same shape as
    sync_after_clear_overrides/sync_after_folder_rename.
    """
    from . import retention

    plans: list[tuple[str, str, set[int]]] = []
    for safe in missing:
        matches = _cached_matches(safe, cfg)
        if matches is None:
            print(f"[klausmate] tag_sync: no cached matches for {safe!r} — cannot restore its !Library tag yet.")
            continue
        threshold = retention.get_threshold(safe, cfg)
        folder, display = _folder_and_display(safe)
        tag = desired_tag(folder, display)
        plans.append((safe, tag, {nid for nid, score in matches if score >= threshold}))
    if not plans:
        return

    def work(col):
        for safe, tag, desired_nids in plans:
            apply_membership(col, tag, desired_nids)
            set_stored_tag(safe, tag)
        return {"count": len(plans)}

    _run_sync_op(mw, "Klaus: restore !Library tags after sidebar rename", work)


def reconcile_from_tags(col) -> dict:
    """Event 5 — the REVERSE direction of THE INVARIANT (K-054): a tag
    renamed in Anki's own tag sidebar renames the PDF in the Library.
    Call with ``mw.col`` — callers own the None-check, exactly like every
    ``_do_sync_one`` caller above owns handing this a real collection.

    Registration owed:
      - ``gui_hooks.profile_did_open.append(tag_sync.reconcile_on_profile_open)``
        next to tag_migrate's own hook (__init__.py, out of this card's
        file scope — see ``reconcile_on_profile_open`` below).
      - ``pdf_drive.DriveWindow._refresh_rows`` calls this directly at
        the top (in this card's scope), so opening or refreshing the
        Library also picks up sidebar renames.

    See ``plan_reconcile`` for the ambiguity rules this enforces (the
    actual decision logic, pure and fully unit-tested). This function is
    the thin, deferred-import glue around it: load every PDF's stored tag
    from prefs.json, diff against ``col.tags.all()``, then either

    (a) a confident single-candidate rename — pure drive_store/prefs.json
        writes, no CollectionOp at all, since Anki's own sidebar rename
        already moved every note's tag; nothing here touches col.tags —
        or
    (b) an ambiguous reapply — routed through ``_run_sync_op`` exactly
        like every forward event, because that path DOES mutate
        col.tags (recreating membership from cached scores). Never a
        second CollectionOp path (see module docstring's OpChanges
        contract note).

    Never raises: wrapped the same way every other public event in this
    module is, so a bug here can never block a profile open or a Library
    refresh. Returns a plain dict describing what happened ({} when
    there was nothing to reconcile, including the kill-switch/no-stored-
    tag/failure cases) — never anything from CollectionOp.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg):
            return {}
        from . import retention

        prefs = retention._load_prefs()
        stored_by_safe = {
            safe: entry.get("tag")
            for safe, entry in prefs.items()
            if isinstance(entry, dict) and entry.get("tag")
        }
        if not stored_by_safe:
            return {}  # e.g. Pouya's current state: no PDF has a stored tag yet

        plan = plan_reconcile(stored_by_safe, set(col.tags.all()))
        if plan["action"] == "noop":
            return plan

        if plan["action"] == "rename":
            from . import curation, drive_store

            r = plan["rename"]
            safe, old_tag, new_tag = r["safe"], r["old"], r["new"]
            folder, leaf = _tag_to_folder_display(new_tag)
            _, old_display = _folder_and_display(safe)
            drive_store.rename_display(curation.USER_FILES, safe, _display_with_ext(leaf, old_display))
            drive_store.set_folder(curation.USER_FILES, safe, folder)
            set_stored_tag(safe, new_tag)
            print(f"[klausmate] tag_sync: reconciled sidebar rename — {safe!r}: {old_tag!r} -> {new_tag!r}")
            return plan

        print(
            f"[klausmate] tag_sync: ambiguous tag reconciliation "
            f"({len(plan['missing'])} missing, {len(plan['candidates'])} candidate(s)) "
            "— reapplying the forward direction instead of guessing."
        )
        _reapply_missing(col, plan["missing"], cfg)
        return plan
    except Exception as exc:  # noqa: BLE001 - never block a profile open or a Library refresh
        print(f"[klausmate] tag_sync: reconcile_from_tags failed: {exc}")
        return {}


def reconcile_on_profile_open() -> None:
    """``profile_did_open`` entry point for the reverse direction.

    Registered in __init__.py immediately after tag_migrate's own hook —
    ordered so it never races a rename that migration is performing::

        gui_hooks.profile_did_open.append(tag_sync.reconcile_on_profile_open)

    Order relative to tag_migrate's hook does not matter — that migration
    only ever touches legacy ``klaus::*`` tags, never a ``!Library::``
    candidate this module would consider.
    """
    try:
        if mw is None or mw.col is None:
            return
        reconcile_from_tags(mw.col)
    except Exception as exc:  # noqa: BLE001 - never block Anki startup
        print(f"[klausmate] tag_sync: reconcile_on_profile_open failed: {exc}")
