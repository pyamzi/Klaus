"""Headless tests for tag_migrate — the !Library tag migration.

Exists because of a real shipped crash (2026-08-23): run_migration
returned the renamed-pairs list, but CollectionOp's on_op_finished reads
``.changes`` off whatever the op returns, so every profile open died with
``AttributeError: 'list' object has no attribute 'changes'`` — and since
the crash preceded the success callback, the migrated flag never stuck
and the crash repeated forever. The contract check below is the test that
would have caught it: the op's return value must be the object
``col.merge_undo_entries`` produced, not a list, not None.

Style matches the other suites: check()/report, aqt stubbed via
sys.modules before import.
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


stub("aqt", mw=None)
stub("aqt.operations", CollectionOp=object)

pkg = types.ModuleType("klausmate")
pkg.__path__ = [__import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.dirname(
        __import__("os").path.abspath(__file__))), "klausmate")]
sys.modules["klausmate"] = pkg

import importlib  # noqa: E402

tm = importlib.import_module("klausmate.tag_migrate")


# ---- fake collection double ------------------------------------------


class _Changes:
    """Sentinel standing in for anki's OpChanges."""


class FakeTags:
    def __init__(self, tags, fail_on=()):
        self._tags = set(tags)
        self.fail_on = set(fail_on)
        self.renames: list[tuple[str, str]] = []

    def all(self):
        return sorted(self._tags)

    def rename(self, old, new):
        if old in self.fail_on:
            raise RuntimeError(f"backend refused {old}")
        self._tags.discard(old)
        self._tags.add(new)
        self.renames.append((old, new))


class FakeCol:
    def __init__(self, tags, fail_on=()):
        self.tags = FakeTags(tags, fail_on)
        self.undo_entries = 0
        self.merged: list[int] = []
        self.changes = _Changes()

    def add_custom_undo_entry(self, name):
        self.undo_entries += 1
        return 42

    def merge_undo_entries(self, pos):
        self.merged.append(pos)
        return self.changes


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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
