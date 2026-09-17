"""Headless tests for tag_migrate — the !Library tag migration — and for
tag_sync, the bidirectional PDF<->!Library tag sync module built on top of
the same OpChanges contract: forward (PDF -> tag, K-053) and reverse (a
sidebar tag rename -> PDF, K-054).

Exists because of a real shipped crash (2026-08-23): run_migration
returned the renamed-pairs list, but CollectionOp's on_op_finished reads
``.changes`` off whatever the op returns, so every profile open died with
``AttributeError: 'list' object has no attribute 'changes'`` — and since
the crash preceded the success callback, the migrated flag never stuck
and the crash repeated forever. The contract check below is the test that
would have caught it: the op's return value must be the object
``col.merge_undo_entries`` produced, not a list, not None.

Style matches the other suites: check()/report, aqt stubbed via
sys.modules before import. The tag_sync sections below reuse this same
minimal stub (NOT the heavier anki_stubs.py permissive surface test_
imports.py uses) — tag_sync.py is deliberately written so its pure/
col-only layer, its reverse-direction decision core (``plan_reconcile``),
and its public event functions' cold-cache/kill-switch short-circuits
never need retention.py or curation.py to import successfully, which
means this file never has to grow the QAction/gui_hooks/AddNoteRequest
surface those modules need. Anything that DOES need that deferred import
chain (the actual membership-diff body once a real matches cache exists;
``reconcile_from_tags``'s own drive_store/prefs.json-writing glue) is
exactly the part Qt's absence means cannot be exercised here — see the
module docstring's own note on that boundary, restated in the tag_sync
sections below.
"""

import re
import sys
import types

PASS = 0
FAIL = 0


def check(label: str, ok: bool) -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok  {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


# ---- aqt stubs so tag_migrate imports without Anki --------------------


def stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class RecordingOp:
    """Stands in for aqt.operations.CollectionOp: records the (parent, op)
    it was built with instead of running anything. Tests drive `op_fn`
    and the success/failure callbacks manually, exactly the shape real
    Anki would call them in — this is what lets the tag_sync tests below
    verify the OpChanges contract end-to-end (op_fn(col) is col, success
    gets called with exactly what op_fn returned) without a live Anki.

    `instances` accumulates across the whole test run so a test can assert
    "no CollectionOp was even created" (the cold-cache/kill-switch no-op
    proof) by checking its length before/after a call.
    """

    instances: list["RecordingOp"] = []

    def __init__(self, parent=None, op=None):
        self.parent = parent
        self.op_fn = op
        self._success = None
        self._failure = None
        RecordingOp.instances.append(self)

    def success(self, fn):
        self._success = fn
        return self

    def failure(self, fn):
        self._failure = fn
        return self

    def run_in_background(self):
        pass  # tests call op_fn/_success/_failure directly instead


stub("aqt", mw=None)
stub("aqt.operations", CollectionOp=RecordingOp)
stub("aqt.utils", tooltip=lambda *a, **k: None)

pkg = types.ModuleType("klausmate")
pkg.__path__ = [__import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.dirname(
        __import__("os").path.abspath(__file__))), "klausmate")]
pkg.get_config = lambda: {}
sys.modules["klausmate"] = pkg

import importlib  # noqa: E402

tm = importlib.import_module("klausmate.tag_migrate")
ts = importlib.import_module("klausmate.tag_sync")


# ---- fake collection double ------------------------------------------


class _Changes:
    """Sentinel standing in for anki's OpChanges."""


class FakeTags:
    """Extended for tag_sync (K-053): bulk_add/bulk_remove/remove plus a
    `membership` map so FakeCol.find_notes can answer "who currently has
    this tag" the same way apply_membership's diff needs — the migration
    tests above only ever needed `.all()`/`.rename()`.
    """

    def __init__(self, tags=(), fail_on=(), membership=None):
        self._tags = set(tags)
        self.fail_on = set(fail_on)
        self.membership: dict[str, set[int]] = {
            k: set(v) for k, v in (membership or {}).items()
        }
        self.renames: list[tuple[str, str]] = []
        self.removed: list[str] = []
        self.bulk_add_calls: list[tuple[list[int], str]] = []
        self.bulk_remove_calls: list[tuple[list[int], str]] = []

    def all(self):
        return sorted(self._tags)

    def rename(self, old, new):
        if old in self.fail_on:
            raise RuntimeError(f"backend refused {old}")
        self._tags.discard(old)
        self._tags.add(new)
        self.renames.append((old, new))
        if old in self.membership:
            self.membership[new] = self.membership.pop(old)

    def remove(self, tags):
        for t in tags:
            self._tags.discard(t)
            self.membership.pop(t, None)
        self.removed.extend(tags)

    def bulk_add(self, nids, tag):
        self.bulk_add_calls.append((list(nids), tag))
        self.membership.setdefault(tag, set()).update(nids)
        self._tags.add(tag)

    def bulk_remove(self, nids, tag):
        self.bulk_remove_calls.append((list(nids), tag))
        if tag in self.membership:
            self.membership[tag].difference_update(nids)


class FakeCol:
    def __init__(self, tags=(), fail_on=(), membership=None):
        self.tags = FakeTags(tags, fail_on, membership)
        self.undo_entries = 0
        self.merged: list[int] = []
        self.changes = _Changes()

    def add_custom_undo_entry(self, name):
        self.undo_entries += 1
        return 42

    def merge_undo_entries(self, pos):
        self.merged.append(pos)
        return self.changes

    def find_notes(self, search: str) -> list[int]:
        """Understands the exact quoted ``tag:"…"`` operand
        ``tag_sync.tag_query`` builds — INCLUDING Anki's wildcards, which
        is the whole point of the K-274 pin below. In a ``tag:`` search an
        unescaped ``*`` matches any run and ``_`` any single character,
        while ``\\*`` and ``\\_`` are literal (rslib ``text.rs``
        ``to_custom_re``). A double that looked the operand up as a plain
        dict key could not tell the two escapings apart at all, so
        ``apply_membership``'s quote-only ``_escape_tag`` — which left both
        wildcards live and silently swept other tags' notes into the diff —
        read as correct here for as long as it shipped."""
        if not (search.startswith('tag:"') and search.endswith('"')):
            return []
        body, pat, i = search[5:-1], "", 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                pat += re.escape(body[i + 1])
                i += 2
                continue
            pat += ".*" if c == "*" else "." if c == "_" else re.escape(c)
            i += 1
        rx = re.compile(pat + r"\Z")
        out: set[int] = set()
        for tag, nids in self.tags.membership.items():
            if rx.match(tag):
                out |= set(nids)
        return sorted(out)


print("== plan_renames (pure) ==")
check(
    "proposes only present old tags",
    tm.plan_renames(["klaus::curated", "unrelated"])
    == [("klaus::curated", "!Library::Curated")],
)
check(
    "klaus::curate is retired now, not renamed (K-064)",
    tm.plan_renames(["klaus::curate"]) == [],
)
check("empty collection -> empty plan", tm.plan_renames([]) == [])
check(
    "already-migrated collection -> empty plan (idempotency)",
    tm.plan_renames(["!Library::Curating", "!Library::Curated"]) == [],
)

print("== run_migration: the CollectionOp contract ==")
col = FakeCol(["klaus::curate", "klaus::curated"])
out: list = []
gone: list = []
result = tm.run_migration(col, renamed_out=out, removed_out=gone)
check("returns EXACTLY merge_undo_entries' object (OpChanges contract)", result is col.changes)
check("returns neither a list nor None", not isinstance(result, (list, type(None))))
check("the rename pair renamed", sorted(out) == sorted(tm.TAG_RENAME_MAP.items()))
check("the retired name removed in the SAME batch (K-064)", gone == ["klaus::curate"])
check("one undo entry for the whole batch", col.undo_entries == 1 and col.merged == [42])

print("== run_migration: partial failure never aborts the batch ==")
col2 = FakeCol(["klaus::curate", "klaus::curated"], fail_on={"klaus::curated"})
out2: list = []
gone2: list = []
result2 = tm.run_migration(col2, renamed_out=out2, removed_out=gone2)
check("still returns the OpChanges object after a failed pair", result2 is col2.changes)
check("failed pair NOT reported renamed", out2 == [])
check("failed old tag NOT deleted", "klaus::curated" in col2.tags.all())
check("removal half still went through despite the rename failure", gone2 == ["klaus::curate"])

print("== second run is a structural no-op ==")
check("post-migration plan is empty", tm.plan_renames(col.tags.all()) == [])


# =========================================================================
# tag_migrate (K-055) — retiring the !Library::Matching preview tag
# =========================================================================
#
# K-053/K-054's durable per-PDF !Library tags made the temp Browse-preview
# tag (retention.RETENTION_TAG, formerly "klaus::pdfmatch" pre-!Library)
# redundant. Rather than renaming it into its !Library home like the two
# curation tags above, this removes both names outright — see the module
# docstring and RETIRED_TAGS/plan_retired_cleanup.

print("== plan_retired_cleanup (pure) ==")
check(
    "both retired names present -> both listed",
    tm.plan_retired_cleanup(["klaus::pdfmatch", "!Library::Matching", "unrelated"])
    == ["klaus::pdfmatch", "!Library::Matching"],
)
check("neither present -> empty (skip silently)", tm.plan_retired_cleanup(["unrelated"]) == [])
check(
    "klaus::pdfmatch alone -> just that one",
    tm.plan_retired_cleanup(["klaus::pdfmatch"]) == ["klaus::pdfmatch"],
)

print("== run_migration: !Library::Matching removed from notes AND the registry ==")
col3 = FakeCol(["!Library::Matching"], membership={"!Library::Matching": {7, 8}})
removed3: list = []
result3 = tm.run_migration(col3, removed_out=removed3)
check("returns EXACTLY merge_undo_entries' object", result3 is col3.changes)
check(
    "bulk-removed the tag from every note that carried it",
    col3.tags.bulk_remove_calls == [([7, 8], "!Library::Matching")],
)
check("tag itself removed from the registry", col3.tags.removed == ["!Library::Matching"])
check("reported via removed_out", removed3 == ["!Library::Matching"])
check("gone from tags.all() afterwards", "!Library::Matching" not in col3.tags.all())
check("still one undo entry for the whole (rename+cleanup) batch", col3.undo_entries == 1)

print("== run_migration: klaus::pdfmatch alone is cleaned (no notes carrying it) ==")
col4 = FakeCol(["klaus::pdfmatch"])
removed4: list = []
result4 = tm.run_migration(col4, removed_out=removed4)
check("returns EXACTLY merge_undo_entries' object", result4 is col4.changes)
check("no bulk_remove call when nothing carries it", col4.tags.bulk_remove_calls == [])
check("tag removed from the registry", col4.tags.removed == ["klaus::pdfmatch"])
check("reported via removed_out", removed4 == ["klaus::pdfmatch"])

print("== run_migration: neither retired tag present -> cleanup half is a no-op ==")
col5 = FakeCol(["unrelated"])
removed5: list = []
tm.run_migration(col5, removed_out=removed5)
check("nothing removed, nothing reported", removed5 == [] and col5.tags.removed == [])

print("== second cleanup run is a structural no-op ==")
check("post-cleanup plan is empty", tm.plan_retired_cleanup(col3.tags.all()) == [])

print("== migrate_on_profile_open: nothing to rename or clean -> CollectionOp never launched ==")


class _FakeMw:
    def __init__(self, col):
        self.col = col


_orig_mw = tm.mw
_had_write_config = hasattr(pkg, "write_config")
_orig_write_config = getattr(pkg, "write_config", None)
pkg.write_config = lambda cfg: None
tm.mw = _FakeMw(FakeCol(["unrelated"]))
try:
    _before_profile_op = len(RecordingOp.instances)
    tm.migrate_on_profile_open()
    check(
        "no CollectionOp created when there is nothing to rename or clean up",
        len(RecordingOp.instances) == _before_profile_op,
    )
finally:
    tm.mw = _orig_mw
    if _had_write_config:
        pkg.write_config = _orig_write_config
    else:
        del pkg.write_config

print(
    "== migrate_on_profile_open (K-055 rework): MIGRATED_FLAG already True "
    "must NOT block the Matching cleanup =="
)
# Falsifies the exact review finding: MIGRATED_FLAG (_library_tag_migrated)
# is already True on every profile that completed the original
# klaus::->!Library rename — Pouya's included. A single-flag short-circuit
# at the top of migrate_on_profile_open would make the new
# plan_retired_cleanup pre-flight permanently unreachable for exactly the
# user who reported the lingering !Library::Matching tag. This must reach
# the pre-flight (because the cleaned-list is still incomplete), launch
# the CollectionOp, actually remove the tag, and record BOTH flags when
# it succeeds.
col6 = FakeCol(["!Library::Matching"], membership={"!Library::Matching": {9}})
_written_cfgs: list = []
_orig_get_config3 = pkg.get_config
_had_write_config3 = hasattr(pkg, "write_config")
_orig_write_config3 = getattr(pkg, "write_config", None)
# Only the rename flag is set — the exact state of an already-migrated
# profile that has never run the Matching cleanup.
pkg.get_config = lambda: {tm.MIGRATED_FLAG: True}
pkg.write_config = lambda cfg: _written_cfgs.append(dict(cfg))
tm.mw = _FakeMw(col6)
try:
    _before_bug_op = len(RecordingOp.instances)
    tm.migrate_on_profile_open()
    _op_launched = len(RecordingOp.instances) == _before_bug_op + 1
    check(
        "a CollectionOp IS launched even though MIGRATED_FLAG is already True",
        _op_launched,
    )
    if _op_launched:
        _bug_inst = RecordingOp.instances[-1]
        _bug_result = _bug_inst.op_fn(col6)
        check(
            "running the op bulk-removes !Library::Matching from its notes",
            col6.tags.bulk_remove_calls == [([9], "!Library::Matching")],
        )
        check(
            "...and drops it from the tag registry",
            "!Library::Matching" not in col6.tags.all(),
        )
        _bug_inst._success(_bug_result)
        check(
            "on completion, the rename flag and the cleaned-list both get recorded",
            bool(_written_cfgs)
            and _written_cfgs[-1].get(tm.MIGRATED_FLAG) is True
            and set(tm.RETIRED_TAGS)
            <= set(_written_cfgs[-1].get(tm.CLEANED_KEY) or []),
        )
    else:
        # Keep the check count identical whether this is RED or GREEN, so
        # the "op not launched" failure above doesn't silently swallow the
        # rest of this scenario's assertions.
        check("running the op bulk-removes !Library::Matching from its notes", False)
        check("...and drops it from the tag registry", False)
        check("on completion, the rename flag and the cleaned-list both get recorded", False)
finally:
    tm.mw = _orig_mw
    pkg.get_config = _orig_get_config3
    if _had_write_config3:
        pkg.write_config = _orig_write_config3
    else:
        del pkg.write_config


# =========================================================================
# tag_sync (K-053) — forward PDF -> !Library tag sync
# =========================================================================
#
# Qt cannot instantiate headlessly, so none of the four real event
# entry points (sync_after_matches, sync_after_threshold,
# sync_after_clear_overrides, sync_after_rename/_folder_rename,
# sync_after_delete) can be driven end-to-end here — each does a deferred
# `from . import retention` (which pulls in curation.py's own aqt.qt/
# gui_hooks/anki.collection surface) the moment it needs an actual PDF's
# cached matches, folder, or display name. That is a strictly bigger aqt
# footprint than tag_migrate.py needs, and pulling in anki_stubs.py's full
# permissive surface just for this file was avoided on purpose (see the
# module docstring) — tests/test_imports.py already proves tag_sync.py
# imports cleanly under that fuller stub.
#
# What IS fully testable here, and what each section below covers:
#   - the pure sanitizer/tag-name logic (no imports at all)
#   - the col-only apply_* layer (a FakeCol double, same style as
#     FakeCol/FakeTags above — no aqt needed beyond what's already stubbed)
#   - _run_sync_op, the shared helper EVERY event builds on, proving it
#     satisfies the exact OpChanges contract tag_migrate.run_migration
#     does
#   - the cold-cache and kill-switch short-circuits in a real public
#     event function (sync_after_threshold), which return before ever
#     reaching the retention/curation import — so they run under this
#     same minimal stub without falling into that gap

print("== tag_sync.strip_pdf_ext (pure) ==")
check("strips .pdf case-insensitively", ts.strip_pdf_ext("Renal Physiology.PDF") == "Renal Physiology")
check("strips .txt", ts.strip_pdf_ext("Notes.txt") == "Notes")
check("no matching extension -> unchanged", ts.strip_pdf_ext("Plain Name") == "Plain Name")
check("blank/None-safe", ts.strip_pdf_ext("") == "" and ts.strip_pdf_ext(None) == "")

print("== tag_sync._sanitize_segment: the sanitizer (pure) ==")
check("spaces become underscores", ts._sanitize_segment("Week 3") == "Week_3")
check("literal :: is stripped, never treated as a separator here", ts._sanitize_segment("A::B") == "AB")
check("repeated underscores collapse to one", ts._sanitize_segment("Foo__Bar") == "Foo_Bar")
check("mixed spaces+underscores collapse too", ts._sanitize_segment("A_ _B") == "A_B")
check("edge underscores are trimmed", ts._sanitize_segment("_Foo_") == "Foo")
check("blank/None-safe", ts._sanitize_segment("") == "" and ts._sanitize_segment(None) == "")

print("== tag_sync.desired_tag: root and nested folders ==")
check("root PDF", ts.desired_tag(None, "Biostatistics.pdf") == "!Library::Biostatistics")
check("empty-string folder treated as root", ts.desired_tag("", "Biostatistics.pdf") == "!Library::Biostatistics")
check(
    "single-level folder",
    ts.desired_tag("Anatomy", "Renal Physiology.pdf") == "!Library::Anatomy::Renal_Physiology",
)
check(
    "multi-level folder: / becomes ::, each segment sanitized",
    ts.desired_tag("Anatomy/Week 3", "Renal Physiology.pdf")
    == "!Library::Anatomy::Week_3::Renal_Physiology",
)

print("== tag_sync.desired_tag: the three reserved leaves ==")
check("root collision with Curating gets a -pdf suffix", ts.desired_tag(None, "Curating.pdf") == "!Library::Curating-pdf")
check("root collision with Curated gets a -pdf suffix", ts.desired_tag(None, "Curated.txt") == "!Library::Curated-pdf")
check("root collision is case-insensitive", ts.desired_tag(None, "matching") == "!Library::matching-pdf")
check(
    "the SAME leaf nested under a folder does not collide (distinct tag path)",
    ts.desired_tag("Foo", "Curating.pdf") == "!Library::Foo::Curating",
)
check("an ordinary name is never suffixed", ts.desired_tag(None, "Normal Name.pdf") == "!Library::Normal_Name")

print("== tag_sync.diff_membership (pure) ==")
check("add only", ts.diff_membership({1, 2, 3}, {2, 3}) == ([1], []))
check("remove only", ts.diff_membership({2}, {1, 2, 3}) == ([], [1, 3]))
check("no-op: identical sets", ts.diff_membership({1, 2}, {1, 2}) == ([], []))
check("mixed add+remove", ts.diff_membership({1, 3}, {1, 2}) == ([3], [2]))

print("== tag_sync.apply_membership: diffs against a FakeCol ==")
col10 = FakeCol(membership={"!Library::Foo": {10, 20, 30}})
added10, removed10 = ts.apply_membership(col10, "!Library::Foo", {20, 30, 40})
check("returns the added nids", added10 == [40])
check("returns the removed nids", removed10 == [10])
check("bulk_add called exactly once, with only the new nid", col10.tags.bulk_add_calls == [([40], "!Library::Foo")])
check("bulk_remove called exactly once, with only the dropped nid", col10.tags.bulk_remove_calls == [([10], "!Library::Foo")])
check("membership reflects the diff afterwards", col10.tags.membership["!Library::Foo"] == {20, 30, 40})

print("== tag_sync.apply_membership: already-in-sync is a true no-op ==")
col11 = FakeCol(membership={"!Library::Bar": {1, 2}})
added11, removed11 = ts.apply_membership(col11, "!Library::Bar", {1, 2})
check("nothing to add", added11 == [])
check("nothing to remove", removed11 == [])
check("bulk_add never called", col11.tags.bulk_add_calls == [])
check("bulk_remove never called", col11.tags.bulk_remove_calls == [])

print("== tag_sync.apply_membership: searches through tag_query (K-274) ==")
# K-272 moved pdf_drive's three Browse hops onto tag_query; the membership
# diff itself still built its own operand with the quote-only _escape_tag,
# so a PDF whose name carries * or _ searched a WIDER set than it owns --
# and _sanitize_segment mints an _ for every space, so "Week 3" is not an
# exotic name. A widened search is not a cosmetic bug here: the extra notes
# come back as `current`, and everything in current that is not desired is
# BULK-REMOVED from the tag.
_wild = "!Library::Week_3*"
col20 = FakeCol(membership={
    _wild: {1},                  # the PDF's own members
    "!Library::Week-3x": {2},    # _ matches "-", * matches "x"
    "!Library::Week_3": {3},     # * matches the empty run
})
added20, removed20 = ts.apply_membership(col20, _wild, {1, 4})
check(
    "a tag holding * and _ no longer widens membership: the wildcard "
    "neighbours are not swept into the diff",
    (added20, removed20) == ([4], []),
)
check(
    "...so nothing is stripped off the tags that merely matched",
    col20.tags.bulk_remove_calls == []
    and col20.tags.membership["!Library::Week-3x"] == {2}
    and col20.tags.membership["!Library::Week_3"] == {3},
)
col21 = FakeCol(membership={"!Library::Plain": {1, 2}})
check(
    "a plain tag's membership is unchanged by the move onto tag_query",
    ts.apply_membership(col21, "!Library::Plain", {2, 3}) == ([3], [1]),
)
col22 = FakeCol(membership={'!Library::Lec "1"\\a': {7}})
check(
    "a tag carrying a quote and a backslash still finds its own members",
    ts.apply_membership(col22, '!Library::Lec "1"\\a', {7}) == ([], []),
)

print("== tag_sync.apply_rename: renames the STORED tag, never a derived guess ==")
col12 = FakeCol(membership={"!Library::OldName": {1, 2}})
renamed12 = ts.apply_rename(col12, "!Library::OldName", "!Library::NewName")
check("apply_rename reports it renamed", renamed12 is True)
check(
    "renamed EXACTLY the (old, new) pair it was given",
    col12.tags.renames == [("!Library::OldName", "!Library::NewName")],
)
check("membership carried across to the new name", col12.tags.membership.get("!Library::NewName") == {1, 2})
check("old tag's membership entry is gone", "!Library::OldName" not in col12.tags.membership)
unrelated_guess = ts.desired_tag(None, "Something Else.pdf")
check(
    "apply_rename never recomputes a tag name itself — it used the stored value, not this unrelated one",
    unrelated_guess != "!Library::NewName",
)
check("no-op when old is falsy (nothing ever indexed)", ts.apply_rename(FakeCol(), None, "!Library::X") is False)
check("no-op when old already equals new", ts.apply_rename(FakeCol(), "!Library::X", "!Library::X") is False)

print("== tag_sync.apply_renames: batched, skips no-ops ==")
col13 = FakeCol(membership={"!Library::A": {1}, "!Library::B": {2}})
done13 = ts.apply_renames(
    col13,
    [
        ("!Library::A", "!Library::A2"),
        (None, "!Library::ignored"),
        ("!Library::B", "!Library::B"),
    ],
)
check("only the real, changed pair is reported done", done13 == [("!Library::A", "!Library::A2")])
check("only that pair actually hit col.tags.rename", col13.tags.renames == [("!Library::A", "!Library::A2")])

print("== tag_sync.apply_removal ==")
col14 = FakeCol(tags=["!Library::Gone"], membership={"!Library::Gone": {1, 2, 3}})
check("reports removal", ts.apply_removal(col14, "!Library::Gone") is True)
check("calls tags.remove with a one-element list", col14.tags.removed == ["!Library::Gone"])
check("membership entry is gone", "!Library::Gone" not in col14.tags.membership)
col15 = FakeCol()
check("no-op on a falsy tag (nothing ever indexed)", ts.apply_removal(col15, None) is False)
check("no-op never touches tags.removed", col15.tags.removed == [])

print("== tag_sync._run_sync_op: reuses the SAME OpChanges contract ==")
_before_ops = len(RecordingOp.instances)
_captured: dict = {}


def _work(col):
    col.tags.bulk_add([1, 2], "!Library::Contract")
    return {"added": [1, 2], "removed": []}


ts._run_sync_op(None, "test undo label", _work, on_done=lambda r: _captured.update(r))
check("exactly one CollectionOp created for one event", len(RecordingOp.instances) == _before_ops + 1)
_inst = RecordingOp.instances[-1]
col16 = FakeCol()
_op_result = _inst.op_fn(col16)
check("op_fn adds exactly one undo entry", col16.undo_entries == 1)
check("op_fn's return is EXACTLY merge_undo_entries' object, not a dict", _op_result is col16.changes)
check("op_fn actually ran work() and applied the mutation", col16.tags.membership.get("!Library::Contract") == {1, 2})
_inst._success(_op_result)
check("on_done received work()'s dict (never the OpChanges object)", _captured == {"added": [1, 2], "removed": []})

print("== tag_sync.sync_after_threshold: a cold cache is a no-op, never a strip ==")
_before_cold = len(RecordingOp.instances)
ts.sync_after_threshold(None, "Some.pdf", None, 0.6)
check(
    "matches=None never creates a CollectionOp — nothing can be stripped from data we don't have",
    len(RecordingOp.instances) == _before_cold,
)

print("== tag_sync: library_tags_enabled kill switch ==")
check("default True when the key is absent", ts.library_tags_enabled({}) is True)
check("respects an explicit False", ts.library_tags_enabled({"library_tags_enabled": False}) is False)
_old_get_config = pkg.get_config
pkg.get_config = lambda: {"library_tags_enabled": False}
try:
    _before_kill = len(RecordingOp.instances)
    ts.sync_after_threshold(None, "Some.pdf", [(1, 0.9)], 0.5)
    check(
        "kill switch off -> no CollectionOp even with real, non-None matches",
        len(RecordingOp.instances) == _before_kill,
    )
finally:
    pkg.get_config = _old_get_config


# =========================================================================
# tag_sync (K-054) — reverse !Library tag -> PDF sync
# =========================================================================
#
# Same boundary as the K-053 section above: plan_reconcile and the three
# small pure helpers it leans on (_is_reserved_tag, _tag_to_folder_display,
# _display_with_ext) need nothing beyond string/set logic, so they are
# fully exercised here. reconcile_from_tags's own body (prefs.json load,
# drive_store writes, the ambiguous-case CollectionOp) does a deferred
# `from . import retention` the moment there is any real stored tag to
# look at, which pulls in curation.py's aqt.qt/gui_hooks/anki.collection
# surface — exactly the gap this file's minimal stub does not cover (see
# module docstring). Only its kill-switch short-circuit (checked BEFORE
# that import) is exercised directly against reconcile_from_tags below;
# everything else is proven at the plan_reconcile level, which is where
# the actual ambiguity-rule logic lives.

print("== tag_sync._is_reserved_tag: only the exact !Library-root leaves ==")
check("!Library::Curating is reserved", ts._is_reserved_tag("!Library::Curating") is True)
check("!Library::Curated is reserved", ts._is_reserved_tag("!Library::Curated") is True)
check("!Library::Matching is reserved", ts._is_reserved_tag("!Library::Matching") is True)
check("case-insensitive on the leaf", ts._is_reserved_tag("!Library::matching") is True)
check(
    "the SAME leaf nested under a folder is NOT reserved (ordinary PDF tag)",
    ts._is_reserved_tag("!Library::Foo::Curating") is False,
)
check("an ordinary root tag is not reserved", ts._is_reserved_tag("!Library::Biostatistics") is False)

print("== tag_sync._tag_to_folder_display: reverse of desired_tag's shape ==")
check(
    "root tag -> (None, leaf)",
    ts._tag_to_folder_display("!Library::Biostatistics") == (None, "Biostatistics"),
)
check(
    "nested folder segments reconstructed with / separators",
    ts._tag_to_folder_display("!Library::Anatomy::Week_3::Renal_Physiology")
    == ("Anatomy/Week 3", "Renal Physiology"),
)
check(
    "LOSSY CAVEAT: an underscore in the tag always reads back as a space "
    "(cannot distinguish a sanitized space from a genuine underscore)",
    ts._tag_to_folder_display("!Library::Week_3_Notes") == (None, "Week 3 Notes"),
)

print("== tag_sync._display_with_ext: preserves the OLD display's real extension ==")
check(
    "reconstructed leaf gets the old display's .pdf extension re-appended",
    ts._display_with_ext("Renal Physiology", "Renal Physio.pdf") == "Renal Physiology.pdf",
)
check(
    "extension case is preserved as-is",
    ts._display_with_ext("Notes", "Old.TXT") == "Notes.TXT",
)
check(
    "no recognized extension on the old display -> nothing appended",
    ts._display_with_ext("Foo", "Foo") == "Foo",
)

print("== tag_sync.plan_reconcile: stored tag present -> no-op ==")
check(
    "tag still exists -> nothing happened, empty plan",
    ts.plan_reconcile({"safeA": "!Library::A"}, {"!Library::A"})
    == {"missing": {}, "candidates": [], "action": "noop", "rename": None},
)

print("== tag_sync.plan_reconcile: no stored tag at all (Pouya's current state) ==")
check(
    "empty stored_by_safe -> nothing to reconcile, existing_tags never even matters",
    ts.plan_reconcile({}, {"!Library::Whatever", "!Library::Curating"})
    == {"missing": {}, "candidates": [], "action": "noop", "rename": None},
)

print("== tag_sync.plan_reconcile: clean single-candidate rename ==")
plan_rename = ts.plan_reconcile(
    {"safeA": "!Library::OldName"},
    {"!Library::Anatomy::Week_3::New_Name"},
)
check("action is a confident rename", plan_rename["action"] == "rename")
check(
    "identifies the right safe, old, and new tag",
    plan_rename["rename"] == {
        "safe": "safeA",
        "old": "!Library::OldName",
        "new": "!Library::Anatomy::Week_3::New_Name",
    },
)

print("== tag_sync.plan_reconcile: multiple stored tags missing -> forward re-apply, no guess ==")
plan_multi_missing = ts.plan_reconcile(
    {"safeA": "!Library::A", "safeB": "!Library::B"},
    {"!Library::NewOne"},
)
check("action is reapply, never a guessed rename", plan_multi_missing["action"] == "reapply")
check("rename is None", plan_multi_missing["rename"] is None)
check(
    "both missing PDFs are reported",
    plan_multi_missing["missing"] == {"safeA": "!Library::A", "safeB": "!Library::B"},
)

print("== tag_sync.plan_reconcile: multiple unclaimed candidates -> forward re-apply, no guess ==")
plan_multi_candidates = ts.plan_reconcile(
    {"safeA": "!Library::A"},
    {"!Library::NewOne", "!Library::NewTwo"},
)
check("action is reapply", plan_multi_candidates["action"] == "reapply")
check("both candidates are reported", plan_multi_candidates["candidates"] == ["!Library::NewOne", "!Library::NewTwo"])

print("== tag_sync.plan_reconcile: zero candidates (tag just vanished) -> forward re-apply ==")
plan_zero_candidates = ts.plan_reconcile({"safeA": "!Library::A"}, set())
check("action is reapply", plan_zero_candidates["action"] == "reapply")
check("no candidates found", plan_zero_candidates["candidates"] == [])

print("== tag_sync.plan_reconcile: another PDF's stored tag is never claimable ==")
plan_other_owned = ts.plan_reconcile(
    {"safeA": "!Library::A", "safeB": "!Library::StillHere"},
    {"!Library::StillHere"},
)
check(
    "safeB's own still-present tag is excluded from candidates, leaving none -> reapply, not a false rename",
    plan_other_owned["action"] == "reapply" and plan_other_owned["candidates"] == [],
)

print("== tag_sync.plan_reconcile: reserved leaves are never claimable ==")
plan_reserved = ts.plan_reconcile(
    {"safeA": "!Library::A"},
    {"!Library::Curating", "!Library::Curated", "!Library::Matching"},
)
check(
    "all three reserved root tags excluded -> zero real candidates -> reapply",
    plan_reserved["action"] == "reapply" and plan_reserved["candidates"] == [],
)
plan_reserved_and_real = ts.plan_reconcile(
    {"safeA": "!Library::A"},
    {"!Library::Curating", "!Library::RealCandidate"},
)
check(
    "reserved tag ignored, the one real candidate still wins a confident rename",
    plan_reserved_and_real["action"] == "rename"
    and plan_reserved_and_real["rename"]["new"] == "!Library::RealCandidate",
)

print("== tag_sync.reconcile_from_tags: kill switch short-circuits before any deferred import ==")
_old_get_config2 = pkg.get_config
pkg.get_config = lambda: {"library_tags_enabled": False}
try:
    check(
        "kill switch off -> {} without ever needing retention/curation to import",
        ts.reconcile_from_tags(FakeCol()) == {},
    )
finally:
    pkg.get_config = _old_get_config2


print(
    "== migrate_on_profile_open (K-064): the legacy one-shot booleans must "
    "NOT strand the Curating cleanup =="
)
# Third instance of the stale-one-shot-flag disease, prevented this time:
# after K-055's rework, BOTH _library_tag_migrated and _matching_tag_removed
# are True on Pouya's profile. Retiring !Library::Curating afterwards must
# still reach the cleanup — the guard has to reopen whenever the retirement
# list grows, and the legacy boolean must migrate into the cleaned-list
# config entry (_retired_tags_cleaned) so this never recurs for the NEXT
# retirement either.
col8 = FakeCol(["!Library::Curating"], membership={"!Library::Curating": {11}})
_written8: list = []
_orig_get8 = pkg.get_config
_had_write8 = hasattr(pkg, "write_config")
_orig_write8 = getattr(pkg, "write_config", None)
pkg.get_config = lambda: {tm.MIGRATED_FLAG: True, "_matching_tag_removed": True}
pkg.write_config = lambda cfg: _written8.append(dict(cfg))
tm.mw = _FakeMw(col8)
try:
    _b8 = len(RecordingOp.instances)
    tm.migrate_on_profile_open()
    _launched8 = len(RecordingOp.instances) == _b8 + 1
    check("op launches although both legacy booleans are True", _launched8)
    if _launched8:
        _inst8 = RecordingOp.instances[-1]
        _r8 = _inst8.op_fn(col8)
        check(
            "!Library::Curating bulk-removed from its notes",
            col8.tags.bulk_remove_calls == [([11], "!Library::Curating")],
        )
        check(
            "...and dropped from the registry",
            "!Library::Curating" not in col8.tags.all(),
        )
        _inst8._success(_r8)
        _cfg8 = _written8[-1] if _written8 else {}
        _cleaned8 = set(_cfg8.get("_retired_tags_cleaned") or [])
        check(
            "cleaned-list records every retired name (old and new)",
            {"klaus::pdfmatch", "!Library::Matching", "klaus::curate",
             "!Library::Curating"} <= _cleaned8,
        )
        check(
            "legacy boolean dropped from config",
            "_matching_tag_removed" not in _cfg8,
        )
    else:
        for _lbl in ("tag removal", "registry drop", "cleaned-list",
                     "legacy key drop"):
            check(f"(unreached: op never launched) {_lbl}", False)
finally:
    pkg.get_config = _orig_get8
    tm.mw = _orig_mw
    if _had_write8:
        pkg.write_config = _orig_write8
    else:
        del pkg.write_config

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
