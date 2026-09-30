"""Per-PDF `!Library` tags — forward direction (PDF -> tag) AND, as of
K-054, the reverse (a tag renamed in Anki's own tag sidebar renames the
PDF in the Library).

Pouya: "add to index / re-index should automatically create the tags.
also, the tags should ALWAYS follow the name of the PDF and the PDF
should always follow the names of the tag, those two are always the
same." The forward half (events 1-4 below) is K-053. The reverse half
(`plan_library_sync`/`reconcile_from_tags`/`reconcile_on_profile_open`, at
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

import os
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
# Keep "doubtful" reserved so a PDF named "Doubtful.pdf" cannot collide
# with a tag already present in a collection.
RESERVED_LEAVES = frozenset({"curating", "curated", "matching", "doubtful"})

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
# vs. current tags, never a signal. `plan_library_sync` is the pure decision
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


def folder_tag(folder: str | None) -> str:
    """The tag a Library folder shows as: desired_tag's folder half."""
    segments = [s for s in (_sanitize_segment(p) for p in (folder or "").split("/")) if s]
    return "::".join(["!Library", *segments])


def _lib_segments(tag: str) -> list[str]:
    parts = tag.split("::")
    return parts[1:] if parts[:1] == ["!Library"] else parts


def _restore(segment: str) -> str:
    # Same lossy underscore -> space guess as _tag_to_folder_display.
    return segment.replace("_", " ").strip()


def _under(folder: str | None, root: str) -> bool:
    return bool(folder) and (folder == root or folder.startswith(root + "/"))


def _with_parents(paths) -> set[str]:
    out: set[str] = set()
    for path in paths:
        parts = [p for p in (path or "").split("/") if p]
        for i in range(1, len(parts) + 1):
            out.add("/".join(parts[:i]))
    return out


def plan_library_sync(pdfs: dict, stored: dict, existing, nonempty=(), empty=(), folders=(), deleted=()) -> list[dict]:
    """K-306: what the Library must do so it and the ``!Library`` tag
    branch agree again. Pure — every input is plain data:

    - ``pdfs``: ``{safe: (folder or None, display)}``, every Library PDF.
    - ``stored``: ``{safe: tag}``, the tag each PDF was last given.
    - ``existing``: the collection's tags right now (``col.tags.all()``).
    - ``nonempty`` / ``empty``: PDFs whose cached matches put at least
      one / zero notes above threshold. A PDF in neither is unknown
      (cold cache).
    - ``folders``: every Library folder, empty ones included.
    - ``deleted``: PDFs whose tag the user just deleted in the sidebar
      (K-316: Anki's Delete is the Library's Delete PDF, even for a PDF
      with no matched cards).

    Returns actions, each a dict with a ``kind``:

    - ``register``: give ``safe`` (None for an empty folder) ``tag``,
      registering it as a zero-note tag if the collection lacks it.
    - ``rename``: the sidebar renamed or moved one PDF's tag; the PDF
      follows (``folder``, and ``display`` unless None = unchanged).
    - ``folder_rename``: the sidebar renamed or moved a folder tag; the
      folder follows with every PDF in it (``tags`` maps the ones whose
      tag Anki moved; empty ones vanished and are re-registered).
    - ``delete``: tags with matched cards, or ones in ``deleted``, are
      gone with no rename to explain them. Only a confirmation may act
      on this.

    Anki refuses to rename a zero-note tag, so a vanished tag known to
    be empty is never a rename source — that is the misrename fix: a
    zero-match PDF's tag never existed before K-306, and one stray
    ``!Library`` tag used to be "confidently" taken as its new name.
    A vanished tag that is empty or unknown is housekeeping (Check
    Database, Clear Unused Tags) and is silently re-registered.
    """
    # Anki compares tags ignoring case and rewrites a new tag's parents
    # to an existing row's case (register.rs adjusted_case_for_parents),
    # so every presence test here is casefolded — an exact compare read
    # Anki's respelling as "missing" and re-registered it forever.
    exact = set(existing)
    present = {t.casefold(): t for t in exact}
    nonempty, empty, deleted = set(nonempty), set(empty), set(deleted)
    actions: list[dict] = []

    owned: dict[str, str] = {}
    for safe in sorted(pdfs):
        folder, display = pdfs[safe]
        tag = stored.get(safe)
        if not tag:
            want = desired_tag(folder, display)
            tag = present.get(want.casefold(), want)
            actions.append({"kind": "register", "safe": safe, "tag": tag})
        elif tag not in exact and tag.casefold() in present:
            tag = present[tag.casefold()]  # adopt Anki's spelling, or this recurs
            actions.append({"kind": "register", "safe": safe, "tag": tag})
        owned[safe] = tag
    missing = {s: t for s, t in owned.items() if stored.get(s) and t.casefold() not in present}
    all_folders = _with_parents(list(folders) + [f for f, _ in pdfs.values()])

    library = [t for t in present.values() if t.startswith("!Library::")]
    taken = {t.casefold() for t in owned.values()} | {folder_tag(f).casefold() for f in all_folders}
    candidates = sorted(
        t for t in library
        if t.casefold() not in taken and not _is_reserved_tag(t)
        and not any(o.casefold().startswith(t.casefold() + "::") for o in library)
    )

    def leaf(tag: str) -> str:
        return _lib_segments(tag)[-1].lower()

    pairable = [s for s in sorted(missing) if s not in empty]
    pairs: dict[str, str] = {}
    for c in candidates:
        ms = [s for s in pairable if leaf(missing[s]) == leaf(c)]
        if len(ms) == 1 and sum(leaf(d) == leaf(c) for d in candidates) == 1:
            pairs[ms[0]] = c
    rest_m = [s for s in pairable if s not in pairs]
    rest_c = [c for c in candidates if c not in pairs.values()]
    if len(rest_m) == 1 and len(rest_c) == 1:
        pairs[rest_m[0]] = rest_c[0]

    consumed: set[str] = set()
    for s in sorted(pairs):
        if s in consumed:
            continue
        old = [x.casefold() for x in _lib_segments(missing[s])]
        new = [x.casefold() for x in _lib_segments(pairs[s])]
        if old[-1] != new[-1] or old[:-1] == new[:-1]:
            continue
        o, n = old[:-1], new[:-1]
        spelled = _lib_segments(pairs[s])[:-1]  # Anki's own spelling of the new folder
        shared = 0
        while shared < min(len(o), len(n)) and o[-1 - shared] == n[-1 - shared]:
            shared += 1
        raw = (pdfs[s][0] or "").split("/")
        for j in range(shared, -1, -1):  # the highest folder that moved as a whole
            a, b = o[: len(o) - j], n[: len(n) - j]
            if not a or not b:
                continue
            old_folder = "/".join(raw[: len(a)])
            new_folder = "/".join(_restore(x) for x in spelled[: len(b)])
            if new_folder in all_folders:
                continue  # an existing destination is a drag of PDFs, not a folder rename
            under = [t for t in sorted(pdfs) if _under(pdfs[t][0], old_folder)]
            tags = {}
            ok = bool(under)
            for t in under:
                if t in pairs:
                    ts = [x.casefold() for x in _lib_segments(missing[t])]
                    ok = ts[: len(a)] == a and pairs[t].casefold() == "::".join(["!library", *b, *ts[len(a):]])
                    tags[t] = pairs[t]
                elif t in missing:
                    ok = t not in nonempty
                else:
                    ok = not stored.get(t)  # a tag still in place: the folder did not move whole
                if not ok:
                    break
            if ok:
                actions.append({"kind": "folder_rename", "old": old_folder, "new": new_folder,
                                "safes": under, "tags": tags})
                consumed.update(under)
                break

    for s in sorted(pairs):
        if s in consumed:
            continue
        old, new = _lib_segments(missing[s]), _lib_segments(pairs[s])
        folder, display = pdfs[s]
        new_folder = folder if old[:-1] == new[:-1] else ("/".join(_restore(x) for x in new[:-1]) or None)
        new_display = None if old[-1] == new[-1] else _display_with_ext(_restore(new[-1]), display)
        actions.append({"kind": "rename", "safe": s, "old": missing[s], "new": pairs[s],
                        "folder": new_folder, "display": new_display})
        consumed.add(s)

    left = [s for s in sorted(missing) if s not in consumed]
    gone = set(left) | {s for s in pdfs if not stored.get(s)}
    grouped: set[str] = set()
    deleted_folders: list[str] = []
    for s in left:
        if s in grouped or (s not in nonempty and s not in deleted):
            continue
        parts = [p for p in (pdfs[s][0] or "").split("/") if p]
        group = None
        for i in range(1, len(parts) + 1):  # the highest folder emptied whole
            f = "/".join(parts[:i])
            under = [t for t in sorted(pdfs) if _under(pdfs[t][0], f)]
            if len(under) > 1 and all(t in gone for t in under):
                group = (f, under)
                break
        if group:
            actions.append({"kind": "delete", "folder": group[0], "safes": group[1]})
            grouped.update(group[1])
            deleted_folders.append(group[0])
        else:
            actions.append({"kind": "delete", "folder": None, "safes": [s]})
            grouped.add(s)
    for s in left:
        if s not in grouped:
            folder, display = pdfs[s]
            actions.append({"kind": "register", "safe": s, "tag": desired_tag(folder, display)})
    if grouped:
        actions = [a for a in actions if not (a["kind"] == "register" and a["safe"] in grouped)]

    known = _with_parents(folders)
    for f in sorted(known):
        if any(g.startswith(f + "/") for g in known):
            continue  # a parent shows through its child's tag
        if any(_under(pf, f) for pf, _ in pdfs.values()):
            continue
        if any(_under(f, d) for d in deleted_folders):
            continue
        ft = folder_tag(f)
        if ft.casefold() not in present and not any(t.casefold().startswith(ft.casefold() + "::") for t in library):
            actions.append({"kind": "register", "safe": None, "tag": ft})
    return actions


# --------------------------------------------------- col-only apply layer
#
# These four take a col-like object (real Anki collection, or a test
# double exposing find_notes/tags.bulk_add/tags.bulk_remove/tags.rename/
# tags.remove) and nothing else klausmate-specific — no aqt.mw, no config,
# no drive_store/prefs lookups. That keeps them testable exactly like
# tag_migrate.run_migration is tested against FakeCol, independent of the
# "what tag should this be" resolution the aqt-glue layer below does.


def tag_query(tag: str) -> str:
    """One quoted ``tag:`` operand, escaped for Anki's search syntax.

    A tag is user-derived — ``desired_tag``'s sanitizer only strips
    whitespace and a literal ``::`` — yet it goes straight into Anki's
    QUERY LANGUAGE. Four characters matter there and the sanitizer keeps
    all four: ``"`` terminates the quoted operand, ``\\`` escapes
    whatever follows it, and in a ``tag:`` search ``*`` matches any run
    while ``_`` matches any single character. ``_`` is not exotic —
    ``_sanitize_segment`` mints one for every space, so "Week 3" becomes
    ``Week_3`` and an unescaped query for it also matches ``Week-3``.

    The escaping is Anki's own (anki-main): ``rslib/src/text.rs``'s
    ``escape_anki_wildcards`` (:512) backslash-escapes exactly
    ``[\\\\*_]``; ``rslib/src/search/writer.rs``'s ``maybe_quote``
    (:103) wraps in ``"…"`` after ``replace('"', '\\\\"')``; and
    ``rslib/src/search/parser.rs``'s ``unescape`` (:731) accepts
    ``\\\\ \\" \\: \\( \\) \\-`` while deliberately leaving ``\\*`` and
    ``\\_`` for the SQL writer (its own test at :881, "parser doesn't
    unescape ``\\*_``"). Backslash first, or the escapes we add would be
    escaped again.

    EVERY caller that puts a tag in front of ``find_notes``,
    ``find_cards`` or ``Browser.search_for`` uses this — the membership
    diff below included since K-274. It used to build its own operand
    with a quote-only escape, on the reasoning that widening that query
    is a membership change rather than a search fix. It is both: the
    notes the wildcards drag in come back as ``current``, and everything
    in ``current`` that is not desired is bulk-REMOVED from the tag. One
    helper, one escaping.
    """
    return 'tag:"{}"'.format(
        tag.replace("\\", "\\\\").replace('"', '\\"')
           .replace("*", "\\*").replace("_", "\\_")
    )


def apply_membership(col, tag: str, desired: set[int]) -> tuple[list[int], list[int]]:
    """Diff `tag`'s current members against `desired` and bulk add/remove
    the difference. Returns (added, removed) — empty lists if already in
    sync (a real no-op: no bulk_add/bulk_remove call at all)."""
    current = set(col.find_notes(tag_query(tag)))
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

    with retention.PREFS_LOCK:
        prefs = retention._load_prefs()
        prefs.setdefault(safe, {})["tag"] = tag
        pdf_handler._atomic_write_json(retention._prefs_path(), prefs, separators=(",", ":"))


def _folder_and_display(safe: str) -> tuple[str | None, str]:
    from . import curation, drive_store

    data = drive_store.load(curation.USER_FILES)
    entry = data.get("pdfs", {}).get(safe) or {}
    return entry.get("folder"), (entry.get("display") or safe)


def _cached_matches_many(safes: list[str], cfg: dict) -> dict[str, list | None]:
    """Each PDF's current matches.json cache, loading the card index ONCE
    (the batch paths used to reload the whole vectors file per PDF, K-305).
    None for a PDF whose cache is cold, missing, or invalidated — exactly
    retention.load_matches' "don't know", which callers must treat as a
    no-op, never as "zero matches"."""
    from . import card_index, embeddings, pdf_index, retention

    cfg_sig = embeddings.index_signature(cfg)
    cidx = card_index.load(retention.INDEX_DIR)
    if cidx is None or not card_index.check_signature(cidx, cfg_sig):
        return {safe: None for safe in safes}
    digest = retention.card_index_digest(cidx)
    out: dict[str, list | None] = {}
    for safe in safes:
        src_sig = pdf_index.source_signature(retention.USER_FILES, safe)
        cached = retention.load_matches(safe, cfg_sig, cidx.dims, src_sig, digest)
        out[safe] = cached[0] if cached is not None else None
    return out


def _retag_others(col, skip_safe: str, cfg: dict) -> None:
    """K-302: with best-lecture assignment on, re-matching one PDF can move
    a card off (or onto) every OTHER PDF, so their tags are re-derived from
    cache in the same op. Loads the card index once, on the op's worker."""
    from . import retention

    if retention.best_delta(cfg) is None:
        return
    safes = [
        s for s, e in retention._load_prefs().items()
        if s != skip_safe and isinstance(e, dict) and e.get("tag")
    ]
    if not safes:
        return
    for other, matches in _cached_matches_many(safes, cfg).items():
        if matches is None:
            continue  # cold cache: never strip a tag on missing data
        threshold = retention.get_threshold(other, cfg)
        folder, display = _folder_and_display(other)
        _do_sync_one(
            col, other, desired_tag(folder, display),
            {nid for nid, score in matches if score >= threshold},
        )


def _do_sync_one(col, safe: str, tag: str, desired_nids: set[int]) -> dict:
    """The membership-diff body shared by sync_after_matches,
    sync_after_threshold, and sync_after_clear_overrides. Self-healing:
    if the stored tag exists but doesn't match the freshly computed
    desired one (should only happen if a rename event was somehow missed
    — see module docstring), carries the old tag's members across before
    diffing, rather than leaving them orphaned under a dead tag name.

    """
    stored = get_stored_tag(safe)
    renamed = apply_rename(col, stored, tag)
    added, removed = apply_membership(col, tag, desired_nids)
    if stored != tag:
        set_stored_tag(safe, tag)
    return {
        "tag": tag,
        "added": added,
        "removed": removed,
        "renamed": renamed,
    }


# ------------------------------------------------------------- aqt glue


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _cfg() -> dict:
    return _pkg().get_config()


# Klaus's own tag ops still in flight. A reconcile that reads the
# collection mid-op sees tags renamed but prefs not yet updated (or the
# reverse) and would take its own rename for the user's delete — that
# asked Pouya to delete four freshly renamed lectures (2026-09-30).
_own_ops = {"pending": 0}


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
        _own_ops["pending"] -= 1
        if on_done:
            on_done(result)
        if on_finished:
            on_finished()

    def fail(exc: Exception) -> None:
        # on_finished fires on BOTH outcomes — callers use it to sequence
        # follow-on work (curation's Browse preview) and to release the
        # pipeline busy token; skipping it on failure would deadlock that.
        _own_ops["pending"] -= 1
        print(f"[klausmate] tag_sync: {undo_label!r} failed: {exc}")
        if on_finished:
            on_finished()

    _own_ops["pending"] += 1
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
    on_done: Callable[[], None] | None = None,
) -> None:
    """Event 1 — indexing/curating a PDF creates or refreshes its tag.

    Called from BOTH completion points that finish a PDF's match pipeline
    (pdf_drive._on_embed's after_matches, curation.run_curation's
    after_matches) with whatever ensure_matches just handed back. That
    value is never None in practice — ensure_matches raises on failure
    rather than returning None — the guard below is defense in depth only,
    matching every other event's "never strip on missing data" rule.

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

        def work(col):
            result = _do_sync_one(col, safe, tag, desired_nids)
            _retag_others(col, safe, cfg)
            return result

        _run_sync_op(
            parent,
            f"Klaus: tag “{display}” in !Library",
            work,
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

        _run_sync_op(
            parent,
            f"Klaus: retag “{display}” for new sensitivity",
            lambda col: _do_sync_one(col, safe, tag, desired_nids),
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
    tag) without blocking the rest of the batch.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg) or not cleared_safes:
            return
        from . import retention

        plans: list[tuple[str, str, set[int]]] = []
        cached = _cached_matches_many(list(cleared_safes), cfg)
        for safe in cleared_safes:
            matches = cached[safe]
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
                r = _do_sync_one(col, safe, tag, desired_nids)
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
    cached = _cached_matches_many(list(missing), cfg)
    for safe in missing:
        matches = cached[safe]
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


def _library_state(col):
    from . import curation, drive_store, pdf_handler, retention

    uf = curation.USER_FILES
    tree = drive_store.build_tree(pdf_handler.list_contexts(uf), drive_store.load(uf))
    pdfs = {
        p["safe"]: (p["folder"], p["display"])
        for items in (tree["root"], *tree["folders"].values())
        for p in items
    }
    stored = {
        safe: entry["tag"]
        for safe, entry in retention._load_prefs().items()
        if isinstance(entry, dict) and entry.get("tag")
    }
    return pdfs, stored, set(col.tags.all()), set(tree["folders"])


def _membership_known(safes, cfg: dict) -> tuple[set[str], set[str]]:
    """(nonempty, empty) from the matches cache; a cold PDF is in neither."""
    from . import retention

    nonempty: set[str] = set()
    empty: set[str] = set()
    for safe, matches in _cached_matches_many(list(safes), cfg).items():
        if matches is None:
            continue
        threshold = retention.get_threshold(safe, cfg)
        (nonempty if any(score >= threshold for _, score in matches) else empty).add(safe)
    return nonempty, empty


def _plan(col, cfg: dict) -> list[dict]:
    pdfs, stored, existing, folders = _library_state(col)
    missing = [s for s in pdfs if stored.get(s) and stored[s] not in existing]
    # ponytail: the card index loads on the main thread, and only when a
    # tag vanished; move it into a QueryOp if that ever shows as a hitch.
    nonempty, empty = _membership_known(missing, cfg) if missing else (set(), set())
    deleted = {s for s in missing if _deleted_by_user(stored[s])}
    return plan_library_sync(pdfs, stored, existing, nonempty, empty, folders, deleted)


def _library_root() -> str | None:
    from . import pdf_handler

    root = pdf_handler._live_library_root()
    return root if root and os.path.isdir(root) else None


def _move_pdf(safe: str, folder: str | None, display: str | None = None) -> None:
    """One PDF follows its tag: drive_store first, then the file on disk
    (K-075), or the next disk rescan would snap it back."""
    from . import curation, drive_store, pdf_handler

    uf = curation.USER_FILES
    root = _library_root()
    if display:
        drive_store.rename_display(uf, safe, display)
        if root:
            pdf_handler.rename_mapped_file(uf, root, safe, display)
    drive_store.set_folder(uf, safe, folder)
    if root:
        pdf_handler.move_mapped_file(uf, root, safe, folder)


def _apply_moves(actions: list[dict]) -> bool:
    from . import curation

    moved = False
    for a in actions:
        try:
            if a["kind"] == "rename":
                _move_pdf(a["safe"], a["folder"], a["display"])
                set_stored_tag(a["safe"], a["new"])
                moved = True
            elif a["kind"] == "folder_rename":
                from . import pdf_drive

                ok, why = pdf_drive.apply_folder_change(
                    curation.USER_FILES, _library_root(), a["old"], a["new"]
                )
                if not ok:  # the directory would not move: move the PDFs one by one
                    print(f"[klausmate] tag_sync: folder move {a['old']!r} -> {a['new']!r} failed ({why}); moving its PDFs")
                    for safe in a["safes"]:
                        folder, _ = _folder_and_display(safe)
                        _move_pdf(safe, a["new"] + (folder or "")[len(a["old"]):])
                for safe, tag in a["tags"].items():
                    set_stored_tag(safe, tag)
                moved = True
        except Exception as exc:  # noqa: BLE001 - one bad move never blocks the rest
            print(f"[klausmate] tag_sync: could not apply {a!r}: {exc}")
    return moved


def _register(regs: list[dict], existing: set[str]) -> None:
    """Give each PDF its tag and register the zero-note ones, so a PDF
    with no matched cards and an empty folder still show in the sidebar.
    ``set_collapsed`` is Anki's own way to register a tag with no notes;
    it is SkipUndo, so this op adds no undo entry."""
    for a in regs:
        if a["safe"]:
            set_stored_tag(a["safe"], a["tag"])
    have_now = {t.casefold() for t in existing}
    tags = sorted({a["tag"] for a in regs if a["tag"].casefold() not in have_now})
    if not tags:
        return

    def op(col):
        have = {t.casefold() for t in col.tags.all()}
        changes = None
        for tag in tags:
            if tag.casefold() not in have:
                changes = col.tags.set_collapsed(tag, False)
        if changes is None:
            from anki.collection import OpChanges

            changes = OpChanges()
        return changes

    def settle(*_a) -> None:
        _own_ops["pending"] -= 1

    def failed(exc: Exception) -> None:
        settle()
        print(f"[klausmate] tag_sync: registering Library tags failed: {exc}")

    _own_ops["pending"] += 1
    CollectionOp(parent=mw, op=op).success(settle).failure(failed).run_in_background()


_prompt = {"open": False}
_user_deleted: dict = {"tags": set(), "at": 0.0}
USER_DELETE_WINDOW_S = 120


def note_user_deleted(tags) -> None:
    """Called by the sidebar just before Anki removes these tags. A
    vanished tag is only ever a DELETE when the user did this; any other
    disappearance (a sync mid-flight, Check Database, another add-on) is
    restored instead."""
    import time

    _user_deleted["tags"] = {t.casefold() for t in tags if t}
    _user_deleted["at"] = time.monotonic()


def _deleted_by_user(tag: str | None) -> bool:
    import time

    if not tag or time.monotonic() - _user_deleted["at"] > USER_DELETE_WINDOW_S:
        return False
    key = tag.casefold()
    return any(key == d or key.startswith(d + "::") for d in _user_deleted["tags"])


def _ask(text: str, on_yes: Callable[[], None], on_no: Callable[[], None]) -> None:
    """K-125: an instance, open(), and the answer from finished — never
    an exec. No is the default: this deletes files."""
    from aqt.qt import QMessageBox

    box = QMessageBox(mw)
    box.setWindowTitle("Delete PDF")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    try:
        from . import theme

        box.button(QMessageBox.StandardButton.Yes).setObjectName("DangerButton")
        box.button(QMessageBox.StandardButton.No).setObjectName("SecondaryButton")
        box.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] delete prompt theme failed: {exc}")

    def answered(_result: int) -> None:
        yes = box.standardButton(box.clickedButton()) == QMessageBox.StandardButton.Yes
        box.deleteLater()
        (on_yes if yes else on_no)()

    box.finished.connect(answered)
    box.open()


def _confirm_deletes(col, deletes: list[dict], cfg: dict) -> None:
    """A tag with matched cards was deleted in the sidebar. Yes deletes
    the PDFs (files to the Trash); No puts the tags back."""
    safes = [s for a in deletes for s in a["safes"]]
    if len(deletes) == 1 and deletes[0]["folder"]:
        text = f"You deleted the “{deletes[0]['folder']}” tag. Delete the {len(safes)} PDFs in it too?"
    elif len(safes) == 1:
        text = f"You deleted the tag for “{strip_pdf_ext(_folder_and_display(safes[0])[1])}”. Delete the PDF too?"
    else:
        text = f"You deleted the tags for {len(safes)} PDFs. Delete the PDFs too?"
    text += "\n\nYes moves the files to the Trash. No puts the tags back."

    def settle() -> None:
        _prompt["open"] = False
        _schedule_reconcile()  # tag changes made while the prompt was up

    def yes() -> None:
        from . import pdf_drive

        for safe in safes:
            pdf_drive.delete_pdf(safe)
        for a in deletes:
            if a["folder"]:
                pdf_drive.delete_folder(a["folder"])
        settle()

    def no() -> None:
        stored = {s: t for s in safes if (t := get_stored_tag(s))}
        _reapply_missing(col, stored, cfg)
        settle()

    _prompt["open"] = True
    _ask(text, yes, no)


def reconcile_from_tags(col) -> dict:
    """The REVERSE direction of THE INVARIANT (K-054, rebuilt K-306): the
    ``!Library`` tag branch in Browse's sidebar IS the Library, so what
    happened to a tag there happens to the PDF. Runs on profile open,
    after every operation that changed tags (``on_operation_did_execute``)
    and at the top of a Library refresh. ``plan_library_sync`` decides;
    this applies: moves and renames first (drive_store, prefs, the file
    on disk), then a second plan for what the moves left — registering
    zero-note tags, and confirming deletes. Never raises. Returns
    ``{"actions": [...]}``, or ``{}`` when switched off or on failure.
    """
    try:
        cfg = _cfg()
        if not library_tags_enabled(cfg):
            return {}
        actions = _plan(col, cfg)
        if _apply_moves(actions):
            actions = _plan(col, cfg)
        regs = [a for a in actions if a["kind"] == "register"]
        if regs:
            _register(regs, set(col.tags.all()))
        deletes, restore = [], {}
        for a in actions:
            if a["kind"] != "delete":
                continue
            stored = {s: get_stored_tag(s) for s in a["safes"]}
            if all(_deleted_by_user(t) for t in stored.values() if t):
                deletes.append(a)
            else:
                restore.update({s: t for s, t in stored.items() if t})
        if restore:
            print(f"[klausmate] tag_sync: restoring {len(restore)} tag(s) that vanished without a sidebar delete")
            _reapply_missing(col, restore, cfg)
        if deletes and not _prompt["open"]:
            _user_deleted["tags"] = set()  # one delete, one question
            _confirm_deletes(col, deletes, cfg)
        return {"actions": actions}
    except Exception as exc:  # noqa: BLE001 - never block a profile open or a Library refresh
        print(f"[klausmate] tag_sync: reconcile_from_tags failed: {exc}")
        return {}


_debounce: dict = {"timer": None}


def _reconcile_now() -> None:
    if _prompt["open"] or mw is None or getattr(mw, "col", None) is None:
        return
    if _own_ops["pending"] > 0:
        _schedule_reconcile()  # read the collection only once our ops landed
        return
    reconcile_from_tags(mw.col)


def _schedule_reconcile() -> None:
    """Debounced, so a drag of twenty tags is one reconcile."""
    if mw is None:
        return
    try:
        if _debounce["timer"] is None:
            from aqt.qt import QTimer

            timer = QTimer(mw)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(_reconcile_now)
            _debounce["timer"] = timer
        _debounce["timer"].start()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tag_sync: could not schedule a reconcile: {exc}")


def on_operation_did_execute(changes, handler) -> None:
    """``operation_did_execute``: any op that touched tags (a sidebar
    rename, drag or delete, undo, Check Database's reset, or one of
    ours, which then plans nothing) is followed by a reconcile."""
    if getattr(changes, "tag", False):
        _schedule_reconcile()


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
