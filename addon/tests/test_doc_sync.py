"""PDF reader 1/5: doc_sync watches open PDFs with a stable-file rule.

Real QFileSystemWatcher under offscreen PyQt6; timers are driven with
processEvents plus short sleeps. Temp directories only.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_doc_sync.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")
for _mod in (QtCore, QtGui, QtWidgets):
    for _name in dir(_mod):
        if not _name.startswith("_"):
            setattr(shim, _name, getattr(_mod, _name))
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

ds = importlib.import_module("klaus_note.doc_sync")
ph = importlib.import_module("klaus_note.pdf_handler")
LOG = []
ds.print = lambda *a, **k: LOG.append(" ".join(map(str, a)))  # pristine output

EVENTS = []
ds.subscribe(lambda ev, safe, path: EVENTS.append((ev, safe, path)))
TMP = tempfile.mkdtemp()


def pump(secs=None, until=None):
    """Run the Qt loop until ``until()`` is true (max 3 s) or for ``secs``."""
    end = time.monotonic() + (secs if secs is not None else 3.0)
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until is None or until()


def write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def changed(safe):
    return [e for e in EVENTS if e == ("changed", safe, None)]


def watched(path):
    return path in ds.watcher().files()


def settle():
    """Let every pending fileChanged/settle chain finish, then forget it."""
    pump(0.8)
    EVENTS.clear()


section("constants and helpers")
check("STABLE_MS is 150", ds.STABLE_MS == 150)
check("stable: same size and mtime", ds.stable((1, 5, 9), (2, 5, 9)) is True)
check("stable: size moved", ds.stable((1, 5, 9), (1, 5, 10)) is False)
check("stable: mtime moved", ds.stable((1, 5, 9), (1, 6, 9)) is False)
check("stable: missing is never stable", ds.stable(None, None) is False
      and ds.stable((1, 5, 9), None) is False)
ds.pin_own_write("X", (1, 2, 3))
check("classify own", ds.classify("X", (1, 2, 3)) == "own")
check("pin kept after a match", ds.classify("X", (1, 2, 3)) == "own")
check("classify changed", ds.classify("X", (1, 2, 4)) == "changed")
check("classify missing", ds.classify("X", None) == "missing")
ds.pin_own_write("X", None)
check("pin cleared by None", ds.classify("X", (1, 2, 3)) == "changed")

section("outside rewrite of an open file: exactly one 'changed'")
a = os.path.join(TMP, "a.pdf")
write(a, b"one")
ds.open_doc("editor", "A", a)
check("open_paths", ds.open_paths() == {"A": a}, str(ds.open_paths()))
check("path watched", watched(a))
write(a, b"two, longer")
check("one 'changed'", pump(until=lambda: changed("A")), str(EVENTS))
pump(0.8)
check("still exactly one", EVENTS == [("changed", "A", None)], str(EVENTS))
EVENTS.clear()

section("Klaus's own write (pinned) emits nothing")
tmp = os.path.join(TMP, "a.tmp")
write(tmp, b"klaus save, different size")
ds.pin_own_write("A", ph.file_stat(tmp))
os.replace(tmp, a)  # rename keeps ino/mtime/size: the pinned stat
pump(1.0)
check("no event for the own write", EVENTS == [], str(EVENTS))
check("watched again after the replace", pump(until=lambda: watched(a)))
settle()

section("save-over (tmp + os.replace) by someone else")
tmp = os.path.join(TMP, "a.tmp")
write(tmp, b"outside save-over")
os.replace(tmp, a)
check("one 'changed'", pump(until=lambda: changed("A")), str(EVENTS))
pump(0.6)
check("exactly one", EVENTS == [("changed", "A", None)], str(EVENTS))
check("path watched again", watched(a))
EVENTS.clear()
write(a, b"second rewrite after the save-over")
check("a second rewrite also fires", pump(until=lambda: changed("A")), str(EVENTS))
settle()
# macOS's FSEvents engine keeps the path across a replace; inotify/kqueue
# drop it and emit fileChanged. Reproduce that so the re-add is exercised.
write(tmp, b"replace on a dropping engine")
os.replace(tmp, a)
ds.watcher().removePath(a)
ds._on_file_changed(a)
check("dropped path re-added after settling", pump(until=lambda: watched(a)))
check("and reported", pump(until=lambda: changed("A")), str(EVENTS))
settle()

section("five writes 50 ms apart: one 'changed' after they stop")
for i in range(5):
    write(a, b"burst" * (i + 2))
    pump(0.05)
check("nothing while the writes are still coming", EVENTS == [], str(EVENTS))
check("one 'changed' after the burst", pump(until=lambda: changed("A")), str(EVENTS))
pump(0.8)
check("exactly one", EVENTS == [("changed", "A", None)], str(EVENTS))
EVENTS.clear()

section("same safe open in two hosts")
ds.open_doc("lecture", "A", a)
check("one watch", ds.watcher().files().count(a) == 1)
write(a, b"seen by both hosts")
check("event", pump(until=lambda: changed("A")), str(EVENTS))
pump(0.6)
check("one event per change, not per host", EVENTS == [("changed", "A", None)],
      str(EVENTS))
EVENTS.clear()
ds.close_doc("editor", "A")
check("closing one host keeps the watch", watched(a) and ds.open_paths() == {"A": a})
write(a, b"lecture still watching")
check("still fires", pump(until=lambda: changed("A")), str(EVENTS))
settle()
ds.close_doc("lecture", "A")
check("last host closed: unwatched", not watched(a) and ds.open_paths() == {})
write(a, b"nobody is looking")
pump(0.8)
check("closed doc emits nothing", EVENTS == [], str(EVENTS))

section("repoint emits 'moved' and moves the watch")
b = os.path.join(TMP, "b.pdf")
write(b, b"bee")
ds.open_doc("editor", "B", b)
b2 = os.path.join(TMP, "sub_b.pdf")
os.rename(b, b2)
ds.repoint("B", b2)
check("'moved' emitted", EVENTS[:1] == [("moved", "B", b2)], str(EVENTS))
check("watch moved", pump(until=lambda: watched(b2) and not watched(b)))
check("open_paths follows", ds.open_paths() == {"B": b2})
pump(0.8)
check("the rename itself is not a 'changed'", EVENTS == [("moved", "B", b2)],
      str(EVENTS))
EVENTS.clear()
write(b2, b"edited at the new path")
check("changes at the new path fire", pump(until=lambda: changed("B")), str(EVENTS))
settle()

section("mark_missing / mark_back")
ds.mark_missing("B")
check("'missing' emitted", EVENTS == [("missing", "B", None)], str(EVENTS))
EVENTS.clear()
ds.mark_back("B", b2)
check("'back' emitted", EVENTS == [("back", "B", b2)], str(EVENTS))
check("still watched", watched(b2))
ds.close_doc("editor", "B")
EVENTS.clear()

section("moved / back refresh the settle baseline")
c = os.path.join(TMP, "c.pdf")
write(c, b"cee")
ds.open_doc("editor", "C", c)
c2 = os.path.join(TMP, "other volume c.pdf")
write(c2, b"cee copied to another volume")  # a cross-volume move: new inode and stat
os.remove(c)
ds.repoint("C", c2)
check("repoint: baseline is the new path's stat", ds._last.get("C") == ph.file_stat(c2))
EVENTS.clear()
ds._settled("C", ph.file_stat(c2))
check("a late settle of the moved file is not 'changed'", EVENTS == [], str(EVENTS))
c3 = os.path.join(TMP, "c back.pdf")
write(c3, b"cee came back, longer")
ds.mark_back("C", c3)
check("mark_back: baseline is the returned path's stat", ds._last.get("C") == ph.file_stat(c3))
EVENTS.clear()
ds._settled("C", ph.file_stat(c3))
check("a late settle of the returned file is not 'changed'", EVENTS == [], str(EVENTS))
pump(0.8)
ds.close_doc("editor", "C")
EVENTS.clear()

section("resync re-adds dropped watches")
d = os.path.join(TMP, "d.pdf")
write(d, b"dee")
ds.open_doc("editor", "D", d)
ds.watcher().removePath(d)  # what a save-over does to the watch
ds.resync()
check("resync re-adds the existing open path", watched(d))
ds.resync()
check("idempotent", ds.watcher().files().count(d) == 1)
os.remove(d)
ds.resync()  # a deleted path: nothing to re-add, nothing logged (checked below)
ds.close_doc("editor", "D")
pump(0.8)
EVENTS.clear()

section("unsubscribe")
seen = []
off = ds.subscribe(lambda *e: seen.append(e))
off()
ds.mark_missing("Z")
check("unsubscribed callback not called", seen == [])
check("log stayed quiet", LOG == [], str(LOG))

raise SystemExit(report())
