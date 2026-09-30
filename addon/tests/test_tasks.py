"""The task tracker behind the status bar: one list of running processes.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_tasks.py
"""
from __future__ import annotations

import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
tasks = importlib.import_module("klausmate.tasks")
Task = tasks.Task
now = [100.0]
tasks.clock = lambda: now[0]

section("begin, update, end")
tasks.begin("a", "A")
tasks.update("a", done=3, total=10)
check("a running task carries its progress", tasks.snapshot()[0] == Task("a", "A", 3, 10, False, "", 100.0),
      str(tasks.snapshot()))
tasks.begin("a", "A2")
check("begin replaces by key", [t.label for t in tasks.snapshot()] == ["A2"], str(tasks.snapshot()))
now[0] = 101.0
tasks.begin("b", "B")
check("newest first", [t.key for t in tasks.snapshot()] == ["b", "a"], str(tasks.snapshot()))
tasks.end("b")
check("an end with no message removes the task", [t.key for t in tasks.snapshot()] == ["a"])
tasks.end("a", "Done")
check("an end message lingers", tasks.snapshot()[0].message == "Done")
now[0] += tasks.LINGER_S + 0.1
check("...then expires", tasks.snapshot() == [], str(tasks.snapshot()))
tasks.update("zz", done=1)
check("updating an unknown key changes nothing", tasks.snapshot() == [])

section("cancel")
hits = []
tasks.begin("c", "C", cancel=lambda: hits.append(1))
tasks.cancel("c")
check("cancel runs the task's callable", hits == [1] and tasks.snapshot()[0].cancellable is True)
tasks.begin("d", "D")
tasks.cancel("d")
check("cancel on a task without one is a no-op", not tasks.snapshot()[0].cancellable)

section("listeners run on the main thread, never inline")
queued, seen = [], []
tasks.run_on_main = queued.append
tasks.add_listener(lambda snap: seen.append(snap))
tasks.begin("e", "E")
check("nothing is delivered on the reporting thread", seen == [] and len(queued) == 1, f"{seen} {queued}")
queued[0]()
check("...only when the main thread runs it", len(seen) == 1 and seen[0][0].key == "e", str(seen))


def boom(_snap):
    raise RuntimeError("listener broke")


later = []
tasks.run_on_main = lambda fn: fn()
tasks.add_listener(boom)
tasks.add_listener(later.append)
try:
    tasks.begin("f", "F")
    ok = True
except Exception:
    ok = False
check("a raising listener neither breaks the reporter nor the next listener", ok and len(later) == 1)
tasks.remove_listener(boom)

section("clear on profile close")
del later[:]
tasks.clear()
check("clear empties the list", tasks.snapshot() == [])
check("...and tells the listeners once", later == [[]], str(later))

raise SystemExit(report())
