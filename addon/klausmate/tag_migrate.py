"""One-time migration of pre-``!Library`` Klaus tags.

Pouya rerooted every Klaus tag at ``!Library`` (the leading ``!`` sorts the
tag tree to the top of Anki's sidebar — see curation.py/retention.py) and
chose automatic renaming of any tags his existing 32k-note collection
already carries under the old names. This module is that one-time move.

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
# rather than imported from curation.TEMP_TAG/CURATED_TAG and
# retention.RETENTION_TAG: those constants already hold the NEW values by
# the time this migration runs, and the whole point of this table is the
# OLD side, which must never change again once notes may already carry it.
TAG_RENAME_MAP: dict[str, str] = {
    "klaus::curate": "!Library::Curating",
    "klaus::curated": "!Library::Curated",
    "klaus::pdfmatch": "!Library::Matching",
}

# Config flag guarding the one-time run, checked/set via the addon's own
# get_config()/write_config(). Underscore-prefixed keys are left alone by
# __init__._migrate_config's legacy-key scrub (see _LEGACY_KEYS_DROPPED).
MIGRATED_FLAG = "_library_tag_migrated"


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


# ------------------------------------------------------------- migration


def run_migration(col) -> list[tuple[str, str]]:
    """Rename every present legacy tag to its !Library home, in one undo
    entry. Must be called with the collection open.

    Returns the ``(old, new)`` pairs actually renamed — an empty list is a
    clean no-op (nothing to migrate: a fresh profile, or a second run
    after a completed first one).

    A rename that raises is caught per-pair and logged; it never deletes
    the old tag (see module docstring) and is simply retried whichever
    next time this runs. One bad pair never blocks the others.
    """
    existing = set(col.tags.all())
    plan = plan_renames(existing)
    if not plan:
        return []

    pos = col.add_custom_undo_entry("Klaus: migrate tags to !Library")
    done: list[tuple[str, str]] = []
    for old, new in plan:
        try:
            col.tags.rename(old, new)
            done.append((old, new))
        except Exception as exc:  # noqa: BLE001 - must not abort the batch
            print(f"[klausmate] tag_migrate: failed to rename {old!r} -> {new!r}: {exc}")
    if done:
        col.merge_undo_entries(pos)
    return done


def migrate_on_profile_open() -> None:
    """``profile_did_open`` entry point — runs the migration exactly once
    per profile, guarded by ``MIGRATED_FLAG`` in the addon config.

    Never raises: every failure is caught and printed so a bug here can
    never block Anki's startup. On any failure to complete the collection
    op itself, the flag is left unset so the next launch retries; thanks
    to ``run_migration``'s structural idempotency that retry is always
    safe even if some pairs already went through.
    """
    try:
        cfg = _cfg()
        if cfg.get(MIGRATED_FLAG):
            return

        def op(col):
            return run_migration(col)

        def done(renamed: list[tuple[str, str]]) -> None:
            try:
                cfg2 = _cfg()
                cfg2[MIGRATED_FLAG] = True
                _pkg().write_config(cfg2)
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] tag_migrate: failed to record migration flag: {exc}")
            if renamed:
                print(f"[klausmate] tag_migrate: renamed {len(renamed)} tag(s) to !Library: {renamed}")

        def fail(exc: Exception) -> None:
            print(f"[klausmate] tag_migrate: migration failed, will retry next launch: {exc}")

        CollectionOp(parent=mw, op=op).success(done).failure(fail).run_in_background()
    except Exception as exc:  # noqa: BLE001 - never block Anki startup
        print(f"[klausmate] tag_migrate: unexpected error: {exc}")
