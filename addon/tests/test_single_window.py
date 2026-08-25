"""Headless tests for klausmate.single_window (K-059..K-062).

Covers the LOGIC only: registry, config gate, fallback-to-stock,
menu-action walking, shortcut arbitration, pane drop/veto. The real
embed is Qt-live and belongs to the restart checklist on the cards.
Run: python3 tests/test_single_window.py
"""
import sys
import types
from types import SimpleNamespace

ADDON = "/Users/pyamzi/Documents/Github/Addons/klausmate"

pkg = types.ModuleType("klausmate")
pkg.__path__ = [ADDON]
pkg.__package__ = "klausmate"
sys.modules["klausmate"] = pkg

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


# ---------------------------------------------------------------- stubs

class _QObject:
    def __init__(self, parent=None):
        self._parent = parent


class _QDialog:
    pass


class _QWidget:
    pass


class _QTimer:
    calls = []

    @staticmethod
    def singleShot(ms, cb):
        _QTimer.calls.append(cb)


QtNS = SimpleNamespace(
    ShortcutContext=SimpleNamespace(WidgetWithChildrenShortcut="WWCS"),
    WindowType=SimpleNamespace(Widget="W-FLAG", Window="TOP-FLAG"),
)

_config = {"single_window_mode": True}
mw_stub = SimpleNamespace(
    addonManager=SimpleNamespace(getConfig=lambda _pkg: dict(_config)),
    form=SimpleNamespace(menubar=None),
)

aqt_mod = types.ModuleType("aqt")
aqt_mod.mw = mw_stub
aqt_mod.gui_hooks = SimpleNamespace(
    profile_did_open=[], state_did_change=[]
)
aqt_mod.dialogs = SimpleNamespace(
    _dialogs={}, register_dialog=lambda *a, **k: None, open=lambda *a, **k: None
)
sys.modules["aqt"] = aqt_mod
sys.modules["aqt.gui_hooks"] = aqt_mod.gui_hooks  # not imported as module here

qt_mod = types.ModuleType("aqt.qt")
qt_mod.QDialog = _QDialog
qt_mod.QEvent = SimpleNamespace(Type=SimpleNamespace(Close="CLOSE"))
qt_mod.QObject = _QObject
qt_mod.QSizePolicy = SimpleNamespace(Policy=SimpleNamespace(Ignored="IGN"))
qt_mod.QStackedWidget = _QWidget
qt_mod.Qt = QtNS
qt_mod.QTimer = _QTimer
qt_mod.QVBoxLayout = _QWidget
qt_mod.QWidget = _QWidget
sys.modules["aqt.qt"] = qt_mod

import importlib

sw = importlib.import_module("klausmate.single_window")

print("== registry + config gate ==")
check("registry covers Browse/Add/Library/Stats",
      set(sw.PANES) == {"Browser", "AddCards", "KlausDrive", "NewDeckStats"})
check("enabled() honors the config default", sw.enabled())
_config["single_window_mode"] = False
check("enabled() honors an explicit off", not sw.enabled())
_config["single_window_mode"] = True

print("== stock fallback when the shell cannot install ==")
# mw_stub has no mainLayout -> _install_shell returns False -> the
# factory must hand straight through to the original creator.
made = []
orig_creator = lambda *a, **k: made.append(("orig", a)) or "WIN"
factory = sw._wrap_creator("Browser", orig_creator)
r = factory("mw-arg")
check("shell failure falls back to the stock creator",
      r == "WIN" and made == [("orig", ("mw-arg",))], repr(made))
check("shell failure leaves no pane state",
      sw._state["panes"] == {} and not sw._state["installed"])

print("== profile hook is a no-op when disabled or shell-less ==")
_config["single_window_mode"] = False
sw._on_profile_open()
check("disabled: nothing hooked", not sw._state["hooked"])
_config["single_window_mode"] = True
sw._on_profile_open()
check("no mw layout: nothing hooked", not sw._state["hooked"])

print("== menu walking + shortcut arbitration ==")


class _Key:
    def __init__(self, s):
        self._s = s
    def toString(self):
        return self._s
    def isEmpty(self):
        return not self._s


class _Action:
    def __init__(self, key=None, menu=None, sep=False):
        self._keys = [_Key(key)] if key else []
        self._menu = menu
        self._sep = sep
        self.context = None
    def menu(self):
        return self._menu
    def isSeparator(self):
        return self._sep
    def shortcuts(self):
        return list(self._keys)
    def setShortcutContext(self, ctx):
        self.context = ctx


class _Menu:
    def __init__(self, actions):
        self._actions = actions
    def actions(self):
        return list(self._actions)


class _Pane:
    def __init__(self, bar):
        self._bar = bar
        self.added = []
    def menuBar(self):
        return self._bar
    def addAction(self, a):
        self.added.append(a)


sub = _Menu([_Action("Ctrl+F"), _Action(sep=True)])
subact = _Action(menu=sub)
bar = _Menu([subact, _Action("Ctrl+Z"), _Action()])
acts = sw._menu_actions(bar)
check("menu walk flattens submenus, skips separators and menu headers",
      sorted(k.toString() for a in acts for k in a.shortcuts())
      == ["Ctrl+F", "Ctrl+Z"], repr(acts))

pane = _Pane(bar)


class _Page:
    def __init__(self):
        self.added = []
    def addAction(self, a):
        self.added.append(a)


page = _Page()
mw_undo = _Action("Ctrl+Z")
mw_prefs = _Action("Ctrl+,")
mw_stub.form.menubar = _Menu([mw_undo, mw_prefs])
sw._state["decks_page"] = page
sw._state["scoped_mw_keys"] = set()
sw._scope_shortcuts(pane)
check("pane actions widget-scoped onto the pane",
      len(pane.added) == 2
      and all(a.context == "WWCS" for a in pane.added), repr(pane.added))
check("colliding mw action scoped to the Decks page",
      page.added == [mw_undo] and mw_undo.context == "WWCS")
check("non-colliding mw action untouched (works from every pane)",
      mw_prefs.context is None and mw_prefs not in page.added)
sw._scope_shortcuts(pane)
check("arbitration is idempotent across panes",
      page.added.count(mw_undo) == 1)

print("== pane drop + veto ==")


class _FakePaneWidget:
    def __init__(self, visible):
        self._visible = visible
    def isVisible(self):
        return self._visible


class _FakeStack:
    def __init__(self):
        self.removed = []
        self.index = None
    def removeWidget(self, w):
        self.removed.append(w)
    def setCurrentIndex(self, i):
        self.index = i


stack = _FakeStack()
sw._state["stack"] = stack
vetoed = _FakePaneWidget(visible=True)
sw._state["panes"]["AddCards"] = vetoed
sw._drop_pane("AddCards")
check("visible pane after close = vetoed close, kept",
      sw._state["panes"].get("AddCards") is vetoed and stack.removed == [])
gone = _FakePaneWidget(visible=False)
sw._state["panes"]["Browser"] = gone
sw._drop_pane("Browser")
check("hidden pane dropped from the stack, Decks fronted",
      "Browser" not in sw._state["panes"]
      and stack.removed == [gone] and stack.index == 0)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
