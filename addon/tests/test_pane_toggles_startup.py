"""Top-bar pane toggles follow tab switches from the first session (#25).

On a profile auto-load Anki fires ``profile_did_open`` BEFORE
``main_window_did_init``, so the single window's host does not exist yet
when the toggles' ``profile_did_open`` listener runs. The single window's
own init must attach the toggles' tab listener, exactly once.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pane_toggles_startup.py
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

import klaus_note.settings as _settings  # noqa: E402
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

_settings.user_files_dir = tempfile.mkdtemp(prefix="klaus-pts-")
_settings.store = _settings.DictStore({})

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
bt = importlib.import_module("klaus_note.browse_toggles")
rh = importlib.import_module("klaus_note.reader_host")
rh.make_reader = lambda parent: type("R0", (QtWidgets.QLabel,), {"cleanup": lambda self: None})("r", parent)


class Hooks:
    """Every gui_hooks name is a plain list."""

    def __getattr__(self, name):
        lst: list = []
        setattr(self, name, lst)
        return lst


hooks = Hooks()
sys.modules["aqt"].gui_hooks = hooks

mw = QtWidgets.QMainWindow()
central = QtWidgets.QWidget()
mw.setCentralWidget(central)
lay = QtWidgets.QVBoxLayout(central)
mw.toolbarWeb, mw.web, mw.bottomWeb = (QtWidgets.QWidget() for _ in range(3))
for w in (mw.toolbarWeb, mw.web, mw.bottomWeb):
    lay.addWidget(w)
mw.mainLayout = lay
mw.form = types.SimpleNamespace(centralwidget=central)
mw.form.menuHelp = mw.menuBar().addMenu("Help")
mw.stateShortcuts = []
mw.clearStateShortcuts = mw.setStateShortcuts = lambda *a: None
mw.pm = types.SimpleNamespace(profile={})
evals: list = []
mw.toolbarWeb.eval = evals.append
sys.modules["aqt"].mw = mw
sys.modules["aqt"].dialogs = types.SimpleNamespace(
    register_dialog=lambda name, creator, instance=None: None, _dialogs={})


def pump():
    for _ in range(3):
        app.processEvents()


def last_panes():
    for js in reversed(evals):
        m = re.search(r"klausPanes\((\{.*\})\);", js)
        if m:
            return json.loads(m.group(1))
    return None


section("startup order: profile_did_open, then main_window_did_init")
bt.setup_top_bar()
sw.setup()
for fn in list(hooks.profile_did_open):
    fn()
for fn in list(hooks.main_window_did_init):
    fn()
mw.show()
pump()
check("the single window is up", sw.is_active() and sw._state.host is not None)
host = sw._state.host
evals.clear()
host.switch("add")
pump()
check("Decks -> Add pushes the Add tab's toggles (show: true)",
      (last_panes() or {}).get("show") is True, str(last_panes()))

section("profile close and reopen")
for fn in list(hooks.profile_will_close):
    fn()
for fn in list(hooks.profile_did_open):
    fn()
pump()
check("the toggle listener is on the host exactly once", host.listeners.count(bt._on_tab) == 1,
      str(host.listeners))

section("every switch pushes the new tab's state")
host.switch("decks")
pump()
for tab, show in (("browse", False), ("decks", False), ("add", True)):
    evals.clear()
    host.switch(tab)
    pump()
    check(f"-> {tab}: a push with show={show}", (last_panes() or {}).get("show") is show and bool(evals),
          str(last_panes()))

raise SystemExit(report())
