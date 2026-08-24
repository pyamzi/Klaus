"""Headless tests for tag_migrate — the !Library tag migration — and for
tag_sync, the forward PDF->tag sync module built on top of the same
OpChanges contract (K-053).

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
col-only layer and its public event functions' cold-cache short-circuit
never need retention.py or curation.py to import successfully, which
means this file never has to grow the QAction/gui_hooks/AddNoteRequest
surface those modules need. Anything that DOES need that deferred import
chain (the actual membership-diff body once a real matches cache exists)
is exactly the part Qt's absence means cannot be exercised here — see the
module docstring's own note on that boundary, restated in the tag_sync
sections below.
"""

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
        """Only needs to understand the exact `tag:"..."` shape
        apply_membership builds (see tag_sync._escape_tag)."""
        if search.startswith('tag:"') and search.endswith('"'):
            tag = search[5:-1].replace('\\"', '"').replace("\\\\", "\\")
            return sorted(self.tags.membership.get(tag, set()))
        return []


print("== plan_renames (pure) ==")
check(
    "proposes only present old tags",
    tm.plan_renames(["klaus::curate", "unrelated"]) == [("klaus::curate", "!Library::Curating")],
)
check("empty collection -> empty plan", tm.plan_renames([]) == [])
check(
    "already-migrated collection -> empty plan (idempotency)",
    tm.plan_renames(["!Library::Curating", "!Library::Curated"]) == [],
)

print("== run_migration: the CollectionOp contract ==")
col = FakeCol(["klaus::curate", "klaus::curated", "klaus::pdfmatch"])
out: list = []
result = tm.run_migration(col, renamed_out=out)
check("returns EXACTLY merge_undo_entries' object (OpChanges contract)", result is col.changes)
check("returns neither a list nor None", not isinstance(result, (list, type(None))))
check("all three pairs renamed", sorted(out) == sorted(tm.TAG_RENAME_MAP.items()))
check("one undo entry for the whole batch", col.undo_entries == 1 and col.merged == [42])

print("== run_migration: partial failure never aborts the batch ==")
col2 = FakeCol(["klaus::curate", "klaus::pdfmatch"], fail_on={"klaus::curate"})
out2: list = []
result2 = tm.run_migration(col2, renamed_out=out2)
check("still returns the OpChanges object after a failed pair", result2 is col2.changes)
check("surviving pair renamed", out2 == [("klaus::pdfmatch", "!Library::Matching")])
check("failed old tag NOT deleted", "klaus::curate" in col2.tags.all())

print("== second run is a structural no-op ==")
check("post-migration plan is empty", tm.plan_renames(col.tags.all()) == [])


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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
