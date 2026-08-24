"""One-time migration of pre-``!Library`` Klaus tags.

Pouya rerooted every Klaus tag at ``!Library`` (the leading ``!`` sorts the
tag tree to the top of Anki's sidebar — see curation.py/retention.py) and
chose automatic renaming of any tags his existing 32k-note collection
already carries under the old names. This module is that one-time move.

K-055 added a second, related cleanup in the same profile-open pass: the
PDF-match preview tag (``klaus::pdfmatch``, and its short-lived !Library
home) was retired outright rather than renamed once every indexed PDF
started owning a durable per-PDF !Library tag instead (tag_sync.py,
K-053) — renaming a tag straight into abolition would be pointless.
``plan_matching_cleanup``/the cleanup loop in ``run_migration`` remove
both names from any collection that still carries them, structurally
idempotent exactly like the rename plan above.

Rework (same day, review-caught): the cleanup pass has its OWN flag,
``MATCHING_MIGRATED_FLAG``, independent of ``MIGRATED_FLAG``. The first
version gated ``migrate_on_profile_open`` entirely on ``MIGRATED_FLAG``,
which is already ``True`` on every profile that completed the original
rename — making the new cleanup permanently unreachable for exactly the
user who reported the lingering tag. See ``migrate_on_profile_open``'s
docstring for the two-flag short-circuit rule.

THIS TOUCHES A REAL COLLECTION — the design goals, in order, are: never
lose data, never throw into Anki's startup path, and only then, run once.

- ``col.tags.rename(old, new)`` is Anki's own tag-rename op: it moves every
  note (and any child tag) from ``old`` to ``new`` and is itself undoable.
  A single call either fully succeeds or raises — there is no partial
  state to clean up, so a failed rename never deletes the old tag.
- Idempotency is structural, not just flag-based: ``plan_renames`` only
  proposes a pair when the *old* tag is still present in the collection.
  After a pair renames successfully the old tag no longer exists, so a
  second run (whether the guard flag failed to persist, or somebody calls
  ``run_migration`` directly) recomputes an empty plan and does nothing.
  Missing source tags (nothing to rename) are the same empty-plan case —
  a silent no-op, not an error.
- The whole batch runs as ONE undo entry (``add_custom_undo_entry`` /
  ``merge_undo_entries`` — the pattern ``curation.create_curated_deck``
  already uses) so Pouya can Ctrl+Z the entire migration in one step.
- ``migrate_on_profile_open`` (the intended ``profile_did_open`` entry
  point) never lets an exception escape: every layer is wrapped in
  try/except that prints ``"[klausmate] ..."`` on failure rather than
  raising into Anki's startup sequence.

aqt glue only at the edges — ``plan_renames`` and ``TAG_RENAME_MAP`` are
pure and import cleanly without aqt, so they're headlessly testable.

Registration owed (NOT done by this module — profile_did_open lives in
__init__.py, out of this file's scope)::

    gui_hooks.profile_did_open.append(tag_migrate.migrate_on_profile_open)
"""

from __future__ import annotations

from aqt import mw
from aqt.operations import CollectionOp

# Old tag -> new !Library home. Deliberately hardcoded as string literals
# rather than imported from curation.TEMP_TAG/CURATED_TAG: those constants
# already hold the NEW values by the time this migration runs, and the
# whole point of this table is the OLD side, which must never change
# again once notes may already carry it.
TAG_RENAME_MAP: dict[str, str] = {
    "klaus::curate": "!Library::Curating",
    "klaus::curated": "!Library::Curated",
}

# The two names the retired PDF-match preview tag has ever carried: the
# original pre-!Library tag, and its short-lived !Library home (formerly
# TAG_RENAME_MAP's target for the pair above, until K-055 removed it —
# renaming a tag straight into abolition would be pointless). Both are
# hardcoded string literals for the same reason TAG_RENAME_MAP's old side
# is: they name tags that may already exist in shipped collections and
# must never quietly drift.
MATCHING_TAGS_TO_REMOVE: tuple[str, ...] = ("klaus::pdfmatch", "!Library::Matching")

# Config flag guarding the one-time run, checked/set via the addon's own
# get_config()/write_config(). Underscore-prefixed keys are left alone by
# __init__._migrate_config's legacy-key scrub (see _LEGACY_KEYS_DROPPED).
MIGRATED_FLAG = "_library_tag_migrated"

# K-055 rework: a SECOND one-shot flag guarding only the Matching-tag
# cleanup pass, independent of MIGRATED_FLAG above. Required because
# MIGRATED_FLAG was already True on every profile that completed the
# original klaus::->!Library rename (Pouya's included) — short-circuiting
# migrate_on_profile_open on that single flag alone made the new cleanup
# pass permanently unreachable for exactly the user who reported the
# lingering !Library::Matching tag. migrate_on_profile_open only skips its
# pre-flight when BOTH flags are set; either one being unset lets it run
# again. A fresh profile's empty combined plan records both flags together
# in one step, so MIGRATED_FLAG's existing behavior for a brand-new
# profile is unchanged.
MATCHING_MIGRATED_FLAG = "_matching_tag_removed"


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _cfg() -> dict:
    return _pkg().get_config()


# ------------------------------------------------------------ pure logic


def plan_renames(
    existing_tags,
    mapping: dict[str, str] = TAG_RENAME_MAP,
) -> list[tuple[str, str]]:
    """Which ``(old, new)`` pairs actually need renaming, given every tag
    name currently in the collection (e.g. ``col.tags.all()``).

    A pair is only proposed when its *old* tag is present. This is both
    the "skip silently when a source tag has no notes" rule (an absent
    tag needs no rename) and the idempotency mechanism (a successfully
    renamed tag is gone from ``existing_tags`` on the next call, so it is
    never proposed again).
    """
    present = set(existing_tags)
    return [(old, new) for old, new in mapping.items() if old in present]


def plan_matching_cleanup(
    existing_tags, names: tuple[str, ...] = MATCHING_TAGS_TO_REMOVE
) -> list[str]:
    """Which of the retired PDF-match preview tag names are still present
    and need removing, given every tag name currently in the collection.

    Same structural idempotency as ``plan_renames``: a tag actually
    removed from the collection is gone from ``existing_tags`` on the
    next call, so a second run always resolves to an empty list. Skips
    silently (returns ``[]``) when neither name exists.
    """
    present = set(existing_tags)
    return [t for t in names if t in present]


# ------------------------------------------------------------- migration


def run_migration(
    col,
    renamed_out: list[tuple[str, str]] | None = None,
    removed_out: list[str] | None = None,
):
    """Rename every present legacy tag to its !Library home, AND (K-055)
    remove every present retired PDF-match preview tag outright, in ONE
    undo entry. Must be called with the collection open, and with a
    non-empty combined plan — callers pre-check ``plan_renames``/
    ``plan_matching_cleanup`` and skip the whole op when there is nothing
    to do in either half.

    RETURNS ``col.merge_undo_entries(pos)`` — an ``OpChanges`` object.
    This is a hard contract, not a convenience: when run under
    ``CollectionOp``, Anki's ``on_op_finished`` reads ``.changes`` off
    whatever the op returns, so returning anything else (this function
    originally returned the renamed-pairs list) crashes every profile
    open with ``AttributeError: 'list' object has no attribute
    'changes'`` — and because the crash lands before the success
    callback, the migrated flag never persists and the crash repeats
    forever. Shipped on 2026-08-23; caught by Pouya's live Anki.

    The renamed pairs / removed tag names are reported via
    ``renamed_out``/``removed_out`` (each extended in place) instead of
    the return value.

    A rename or removal that raises is caught per-item and logged; a
    failed rename never deletes the old tag (see module docstring) and a
    failed removal leaves the tag exactly as it was — either way it is
    simply retried whichever next time this runs. One bad item never
    blocks the others.
    """
    existing = set(col.tags.all())
    plan = plan_renames(existing)
    cleanup = plan_matching_cleanup(existing)

    pos = col.add_custom_undo_entry("Klaus: migrate tags to !Library")
    for old, new in plan:
        try:
            col.tags.rename(old, new)
            if renamed_out is not None:
                renamed_out.append((old, new))
        except Exception as exc:  # noqa: BLE001 - must not abort the batch
            print(f"[klausmate] tag_migrate: failed to rename {old!r} -> {new!r}: {exc}")
    for tag in cleanup:
        try:
            carrying = col.find_notes(f'tag:"{tag}"')
            if carrying:
                col.tags.bulk_remove(list(carrying), tag)
            col.tags.remove([tag])
            if removed_out is not None:
                removed_out.append(tag)
        except Exception as exc:  # noqa: BLE001 - must not abort the batch
            print(f"[klausmate] tag_migrate: failed to remove retired tag {tag!r}: {exc}")
    return col.merge_undo_entries(pos)


def migrate_on_profile_open() -> None:
    """``profile_did_open`` entry point — runs the migration (both the
    legacy-tag rename AND, as of K-055, the retired PDF-match tag
    cleanup) exactly once per profile, guarded by TWO independent flags:
    ``MIGRATED_FLAG`` (the original rename) and ``MATCHING_MIGRATED_FLAG``
    (the K-055 cleanup). The short-circuit below only fires when BOTH are
    set — a profile that already has ``MIGRATED_FLAG`` True from the
    original klaus::->!Library run but has never run the Matching cleanup
    (``MATCHING_MIGRATED_FLAG`` unset) must still reach the pre-flight, or
    the cleanup can never run for exactly the users who need it (K-055
    rework — the single-flag version shipped originally never reached the
    pre-flight for anyone who had already migrated).

    Never raises: every failure is caught and printed so a bug here can
    never block Anki's startup. On any failure to complete the collection
    op itself, both flags are left unset so the next launch retries;
    thanks to ``run_migration``'s structural idempotency that retry is
    always safe even if some pairs/tags already went through.
    """
    try:
        cfg = _cfg()
        if cfg.get(MIGRATED_FLAG) and cfg.get(MATCHING_MIGRATED_FLAG):
            return

        def _record_flags() -> None:
            try:
                cfg2 = _cfg()
                cfg2[MIGRATED_FLAG] = True
                cfg2[MATCHING_MIGRATED_FLAG] = True
                _pkg().write_config(cfg2)
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] tag_migrate: failed to record migration flag(s): {exc}")

        # Pre-flight on the main thread: profile_did_open guarantees the
        # collection is loaded, and tags.all() is cheap. When there is
        # nothing to migrate OR clean up (fresh profile, or the flag write
        # failed after a completed run) we record BOTH flags and never
        # launch a CollectionOp at all — an empty batch has no OpChanges
        # to return and no undo entry worth creating.
        col = mw.col
        if col is None:
            return  # not loaded yet; retry next profile open
        existing_tags = col.tags.all()
        if not plan_renames(existing_tags) and not plan_matching_cleanup(existing_tags):
            _record_flags()
            return

        renamed: list[tuple[str, str]] = []
        removed: list[str] = []

        def op(col):
            # Contract: must return OpChanges (see run_migration).
            return run_migration(col, renamed_out=renamed, removed_out=removed)

        def done(_changes) -> None:
            _record_flags()
            if renamed:
                print(f"[klausmate] tag_migrate: renamed {len(renamed)} tag(s) to !Library: {renamed}")
            if removed:
                print(f"[klausmate] tag_migrate: removed {len(removed)} retired tag(s): {removed}")

        def fail(exc: Exception) -> None:
            print(f"[klausmate] tag_migrate: migration failed, will retry next launch: {exc}")

        CollectionOp(parent=mw, op=op).success(done).failure(fail).run_in_background()
    except Exception as exc:  # noqa: BLE001 - never block Anki startup
        print(f"[klausmate] tag_migrate: unexpected error: {exc}")
