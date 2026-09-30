"""PDF reader 1/5: SavePipeline core (debounced, one worker per PDF).

Fake run_on_main (inline), fake timer (fired by hand), fake bake injected
through pdf_handler.bake_annotations. No Qt, no real PDFs.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_annotation_save.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
sys.modules["klausmate"].get_config = lambda: {}
ph = importlib.import_module("klausmate.pdf_handler")
asv = importlib.import_module("klausmate.annotation_save")

STAT = (1, 2, 3)


class Timers:
    def __init__(self):
        self.calls = []  # (name, ms, cb)

    def __call__(self, name, ms, cb):
        self.calls.append((name, ms, cb))

    def fire_all(self):
        calls, self.calls = self.calls, []
        for _n, _ms, cb in calls:
            cb()


class Bake:
    """Stands in for pdf_handler.bake_annotations; counts calls/overlap."""

    def __init__(self, result=True, gate=None, omitted=None):
        self.result = result
        self.gate = gate  # threading.Event the bake blocks on
        self.omitted = omitted or []
        self.calls = []
        self.active = {}
        self.max_active = {}
        self.started = threading.Event()
        self.lock = threading.Lock()

    def __call__(self, ufd, name, report=None):
        with self.lock:
            self.calls.append(name)
            self.active[name] = self.active.get(name, 0) + 1
            self.max_active[name] = max(
                self.max_active.get(name, 0), self.active[name]
            )
        self.started.set()
        try:
            if self.gate is not None:
                self.gate.wait(5)
            if report is not None and self.result:
                report["stat"] = STAT
                report["omitted_native"] = list(self.omitted)
                report["native_ids"] = ["n1"]
            return self.result
        finally:
            with self.lock:
                self.active[name] -= 1


def make(bake):
    ph.bake_annotations = bake
    timers, pins, events = Timers(), [], []
    pipe = asv.SavePipeline(
        tempfile.mkdtemp(),
        lambda cb: cb(),
        timers,
        lambda name, stat: pins.append((name, stat)),
    )
    pipe.subscribe(lambda ev, name: events.append((ev, name)))
    return pipe, timers, pins, events


def wait_for(cond, secs=3.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


ph.record_stat = lambda *a: None
ph.remove_records = lambda *a: 0
ph.mark_native_baked = lambda *a: None

section("debounce: three requests, one bake")
bake = Bake()
pipe, timers, pins, events = make(bake)
for _ in range(3):
    pipe.request("A")
check("every request arms the %d ms timer" % asv.DEBOUNCE_MS,
      [(n, ms) for n, ms, _ in timers.calls] == [("A", 500)] * 3
      and asv.DEBOUNCE_MS == 500)
check("nothing bakes before the timer fires", bake.calls == [])
timers.fire_all()
check("flush reports idle", pipe.flush("A") is True)
check("one bake for three requests", bake.calls == ["A"], str(bake.calls))

section("never two bakes of one PDF at once")
gate = threading.Event()
bake = Bake(gate=gate)
pipe, timers, pins, events = make(bake)
pipe.request("A")
timers.fire_all()
check("first bake started", bake.started.wait(3))
pipe.request("A")
timers.fire_all()
time.sleep(0.15)
check("second waits while the first runs", bake.calls == ["A"], str(bake.calls))
gate.set()
check("flush waits for both", pipe.flush("A") is True)
check("second bake ran after the first", bake.calls == ["A", "A"])
check("never overlapped", bake.max_active["A"] == 1, str(bake.max_active))

section("different PDFs may overlap")
both = threading.Barrier(2, timeout=3)


class Rendezvous(Bake):
    def __call__(self, ufd, name, report=None):
        both.wait()  # only passes if A and B are inside at the same time
        return super().__call__(ufd, name, report)


bake = Rendezvous()
pipe, timers, pins, events = make(bake)
pipe.request("A")
pipe.request("B")
timers.fire_all()
check("both bakes ran concurrently", pipe.flush(timeout=5) is True
      and sorted(bake.calls) == ["A", "B"])

section("failed bake: event, failed_names, retry clears")
jpath = os.path.join(tempfile.mkdtemp(), "A.json")
with open(jpath, "w") as f:
    f.write('{"records": [1]}')
bake = Bake(result=False)
pipe, timers, pins, events = make(bake)
pipe.request("A")
timers.fire_all()
pipe.flush("A")
check("failed event emitted", events == [("failed", "A")], str(events))
check("failed_names", pipe.failed_names() == {"A"})
check("no pin on failure", pins == [])
with open(jpath) as f:
    check("json untouched", f.read() == '{"records": [1]}')
bake.result = True
pipe.request("A")
timers.fire_all()
pipe.flush("A")
check("next request retried", bake.calls == ["A", "A"])
check("failure cleared", pipe.failed_names() == set())
check("saved emitted", ("saved", "A") in events)
bake.result = False
pipe.request("A")
timers.fire_all()
pipe.flush("A")
bake.result = True
pipe.retry("A")
timers.fire_all()
pipe.flush("A")
check("retry() re-requests and clears", pipe.failed_names() == set())

section("flush runs a pending bake now")
bake = Bake()
pipe, timers, pins, events = make(bake)
pipe.request("A")
check("flush('A') returns True", pipe.flush("A") is True)
check("baked without the timer", bake.calls == ["A"])
timers.fire_all()  # the late timer must not bake again
pipe.flush("A")
check("late timer is a no-op", bake.calls == ["A"])
check("flush() with nothing pending is True", pipe.flush() is True)
pipe.request("B")
check("flush() with no name runs every pending", pipe.flush() is True
      and bake.calls == ["A", "B"])

section("a bake that never returns times flush out")
gate = threading.Event()
bake = Bake(gate=gate)
pipe, timers, pins, events = make(bake)
pipe.request("A")
check("flush times out False", pipe.flush("A", timeout=0.2) is False)
gate.set()
pipe.flush("A")

section("post-step on success")
ph.record_stat = lambda d, n, s: order.append(("record_stat", n, s))
ph.remove_records = lambda d, n, ids: order.append(("remove", n, list(ids))) or 2
ph.mark_native_baked = lambda d, n, ids: order.append(("mark", n, list(ids)))
order = []
bake = Bake(omitted=["x"])
pipe, timers, pins, events = make(bake)
pipe.subscribe(lambda ev, n: order.append((ev, n)))
pipe.request("A")
timers.fire_all()
pipe.flush("A")
check("pin gets the report's stat", pins == [("A", STAT)], str(pins))
check("order: stat, omitted removed, ledger, records, saved",
      order == [("record_stat", "A", STAT), ("remove", "A", ["x"]),
                ("mark", "A", ["n1"]), ("records", "A"), ("saved", "A")],
      str(order))
order.clear()
bake.omitted = []
pipe.request("A")
timers.fire_all()
pipe.flush("A")
check("no omitted: no remove, no records event",
      [o[0] for o in order] == ["record_stat", "mark", "saved"], str(order))

section("a raising bake counts as failed, worker survives")


def boom(*a, **k):
    raise RuntimeError("disk full")


ph.bake_annotations = boom
pipe, timers, pins, events = make(boom)
ph.bake_annotations = boom
pipe.request("A")
timers.fire_all()
check("flush idle", pipe.flush("A") is True)
check("reported failed", events == [("failed", "A")]
      and pipe.failed_names() == {"A"})

section("unsubscribe")
pipe, timers, pins, events = make(Bake())
seen = []
off = pipe.subscribe(lambda ev, n: seen.append(ev))
off()
pipe.request("A")
timers.fire_all()
pipe.flush("A")
check("unsubscribed callback not called", seen == [])

raise SystemExit(report())
