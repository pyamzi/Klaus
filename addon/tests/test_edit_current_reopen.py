"""Single window: reopening Edit Current within ~5 s of closing it keeps
the new window (#24). The reaper started for the closed window must only
ever remove the dock it was made for, never a newer Edit dock.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_edit_current_reopen.py
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

import klaus_note.settings as _settings  # noqa: E402
from PyQt6 import QtCore, QtGui, QtWidgets, sip  # noqa: E402

_settings.user_files_dir = tempfile.mkdtemp(prefix="klaus-ecr-")

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

sw = importlib.import_module("klaus_note.single_window")


def fake_mw():
    win = QtWidgets.QMainWindow()
    central = QtWidgets.QWidget()
    win.setCentralWidget(central)
    lay = QtWidgets.QVBoxLayout(central)
    win.toolbarWeb, win.web, win.bottomWeb = (QtWidgets.QWidget() for _ in range(3))
    for w in (win.toolbarWeb, win.web, win.bottomWeb):
        lay.addWidget(w)
    win.mainLayout = lay
    win.form = types.SimpleNamespace(centralwidget=central)
    win.toolbarWeb.eval = lambda js: None
    return win


def pump(seconds: float = 0.0) -> None:
    end = time.monotonic() + seconds
    while True:
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.02)


class FakeEditCurrent(QtWidgets.QMainWindow):  # Anki hides it on close and never deletes it
    def __init__(self, mw):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.editor = object()
        self.show()


registry = {"EditCurrent": [object(), None], "NewEditCurrent": [object(), None]}
sys.modules["aqt"].dialogs = types.SimpleNamespace(
    register_dialog=lambda name, creator, instance=None: None, _dialogs=registry)

mw = fake_mw()
sw._state.mw = mw
sw._state.host = sw.build_host(mw)
sw._state.docks = {}
sw._state.browser = sw._state.addcards = sw._state.editcurrent = None
sw._state.active, sw._state.disabled = True, None
mw.show()


def open_edit():
    """What Anki's dialog manager does: the creator builds it in a new dock,
    the registry records it, editor_did_init and the open hook follow."""
    with sw.hosted(sw._new_edit_dock(mw).widget()):
        ec = sw.embedded_class(FakeEditCurrent)(None)
    registry["NewEditCurrent"][1] = ec
    sw._on_editor_did_init(types.SimpleNamespace(
        editorMode=types.SimpleNamespace(name="EDIT_CURRENT"), parentWindow=ec))
    sw._on_dialog_opened(None, "NewEditCurrent", ec)
    return ec


section("close, then reopen 0.3 s later")
ec1 = open_edit()
dock1 = sw._state.docks["edit"]
ec1.close()
pump(0.1)  # the note is still saving: the registry still shows it open
registry["NewEditCurrent"][1] = None  # Anki's markClosed
pump(0.3)
check("the first dock is reaped and its orphan deleted",
      sw._state.docks.get("edit") is not dock1 and sip.isdeleted(ec1))
ec2 = open_edit()
dock2 = sw._state.docks["edit"]
pump(5.5)
check("the reopened Edit dock is still the live one",
      sw._state.docks.get("edit") is dock2 and not sip.isdeleted(dock2))
check("…visible", not sip.isdeleted(dock2) and dock2.isVisible())
check("…and its Edit Current is alive and recorded",
      not sip.isdeleted(ec2) and sw._state.editcurrent is ec2)

section("closing the reopened one still reaps it")
ec2.close()
registry["NewEditCurrent"][1] = None
pump(0.5)
check("no Edit dock is left behind and the orphan is deleted",
      "edit" not in sw._state.docks and sw._state.editcurrent is None and sip.isdeleted(ec2))

section("profile close (closeWithCallback ends in close()) leaves no Edit dock")
ec3 = open_edit()
registry["NewEditCurrent"][1] = None  # closeAll marks it closed
ec3.close()
pump(0.5)
check("no Edit dock, no instance", "edit" not in sw._state.docks and sw._state.editcurrent is None
      and sip.isdeleted(ec3))

raise SystemExit(report())
