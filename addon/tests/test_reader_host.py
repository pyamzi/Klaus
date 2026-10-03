"""The reader host (klaus_note/reader_host.py): the ONE PDF reader and its
two homes — the Add tab's reader slot and, on loan, Browse's viewer mode.
Spec: docs/superpowers/specs/2026-10-01-add-tab-design.md, "The reader".

Real PyQt6, offscreen; the reader itself is a fake (``make_reader`` seam).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_reader_host.py
"""
from __future__ import annotations

import importlib
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
from PyQt6 import QtCore, QtGui, QtWidgets, sip  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    if name == "sip":
        return sip
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

rh = importlib.import_module("klaus_note.reader_host")


def pump():
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    for _ in range(3):
        app.processEvents()


class FakeReader(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__("reader", parent)
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True


rh.make_reader = lambda parent: FakeReader(parent)


def slot_in(win):
    w = QtWidgets.QWidget()
    QtWidgets.QVBoxLayout(w).setContentsMargins(0, 0, 0, 0)
    win.setCentralWidget(w) if win.centralWidget() is None else win.centralWidget().layout().addWidget(w)
    return w


win1 = QtWidgets.QMainWindow(); win1.setCentralWidget(QtWidgets.QWidget()); QtWidgets.QVBoxLayout(win1.centralWidget())
win1.show()
slot, box = slot_in(win1), slot_in(win1)

section("home")
check("no home, no parent: nothing to build under", rh.reader() is None)
rh.set_home(slot)
r = rh.reader()
check("built once under the home", r is rh.reader() and r.parent() is slot and slot.layout().indexOf(r) >= 0)
check("has_home", rh.has_home() and not rh.borrowed())

section("lend and give back")
rh.lend(box)
check("lent: parent is the box, borrowed", r.parent() is box and rh.borrowed() and r.isVisibleTo(box)
      and box.layout().indexOf(r) >= 0 and slot.layout().indexOf(r) < 0)
rh.give_back()
check("home again", r.parent() is slot and not rh.borrowed() and slot.layout().indexOf(r) >= 0)
rh.give_back()
check("give_back is idempotent", r.parent() is slot and rh.reader() is r)

section("fallback: no home")
rh.set_home(None)
check("no home now", not rh.has_home())
rh.release()
check("released: cleaned up and forgotten", r.cleaned and rh.reader() is None)
win2 = QtWidgets.QMainWindow(); win2.setCentralWidget(QtWidgets.QWidget()); QtWidgets.QVBoxLayout(win2.centralWidget()); win2.show()
box2 = slot_in(win2)
rh.lend(box2)
r2 = rh.reader()
check("lend with no home builds under the box", r2 is not None and r2.parent() is box2)
rh.give_back()
check("...and give_back leaves it there", r2.parent() is box2 and rh.reader() is r2)
check("release twice is safe", (rh.release(), rh.release(), rh.reader() is None)[-1])

section("never across top-level windows")
rh.lend(box2)
r2 = rh.reader()
rh.set_home(slot)  # slot is in win1; r2 lives in win2
win3 = QtWidgets.QMainWindow(); win3.setCentralWidget(QtWidgets.QWidget()); QtWidgets.QVBoxLayout(win3.centralWidget()); win3.show()
box3 = slot_in(win3)
rh.lend(box3)
check("lend into another top-level rebuilds, never moves",
      r2.cleaned and rh.reader() is not r2 and rh.reader().parent() is box3)
rh.give_back()
check("give_back from a third window: the reader stays put, nothing crosses windows (the home is in win1)",
      rh.reader().parent() is box3 and rh.borrowed())
rh.release()

section("a dead reader is rebuilt")
r3 = rh.reader()
check("rebuilt under the home", r3 is not None and r3.parent() is slot)
r3.setParent(None); r3.deleteLater(); pump()
r4 = rh.reader()
check("reader() after C++ death returns a fresh live one", r4 is not r3 and r4.parent() is slot and not sip.isdeleted(r4))
slot.setParent(None); slot.deleteLater(); pump()
check("a dead home counts as no home", not rh.has_home())
check("reader() with a dead home and no parent is None (the old one died with the slot)", rh.reader() is None)

section("current() never builds; set_home twice keeps one note")
rh.set_home(None); rh.release()
slot2 = slot_in(win1)
rh.set_home(slot2)
check("current() is None before any reader() and builds nothing", rh.current() is None and rh._state["reader"] is None)
r5 = rh.reader()
check("current() is the live instance", rh.current() is r5)
r5.setParent(None); r5.deleteLater(); pump()
check("current() forgets a dead one and still builds nothing", rh.current() is None and rh._state["reader"] is None)
n1 = rh.borrowed_note()
rh.set_home(slot2)
check("set_home again drops the old note and keeps one", rh.borrowed_note() is not n1 and sip.isdeleted(n1) or n1.isHidden(),
      f"n1 deleted={sip.isdeleted(n1)}")
check("…exactly one note label in the slot", len([w for w in slot2.findChildren(QtWidgets.QLabel) if w.objectName() == "klaus_note_reader_borrowed" and not sip.isdeleted(w)]) == 1)

section("guarded: nothing raises on bad input")
raised = []
try:
    rh.lend(None); rh.give_back(); rh.release(); rh.set_home(None)
except Exception as exc:  # noqa: BLE001
    raised.append(exc)
check("lend(None), give_back, release, set_home(None) never raise", raised == [], repr(raised))

raise SystemExit(report())
