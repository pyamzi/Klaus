"""Single window: Decks, Add and Browse as tabs in the main window (Add =
Library tree | PDF reader | Add editor), Edit Current in a right dock —
Anki's windows built as children of the host from their first line
(never moved: K-090..K-094).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_single_window.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

import klaus_note.settings as _settings  # noqa: E402
from PyQt6 import QtCore, QtGui, QtWidgets, sip  # noqa: E402

_settings.user_files_dir = tempfile.mkdtemp(prefix="klaus-sw-")  # the Add page's Library tree reads the index

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

section("pure helpers")
check("preflight lists what is missing, in order",
      sw.preflight("browser", types.SimpleNamespace(table=1)) ==
      [n for n in sw.PREFLIGHT["browser"] if n != "table"])
check("preflight is empty when everything exists",
      sw.preflight("mw", types.SimpleNamespace(**{n: 1 for n in sw.PREFLIGHT["mw"]})) == [])
check("PREFLIGHT pins the attributes the touchpoints rely on",
      sw.PREFLIGHT == {
          "mw": ("web", "bottomWeb", "toolbarWeb", "form", "mainLayout", "stateShortcuts", "clearStateShortcuts",
                 "setStateShortcuts", "addDockWidget", "tabifyDockWidget", "menuBar"),
          "browser": ("table", "sidebar", "form", "menuBar", "close", "editor"),
          "addcards": ("editor", "close", "form"),
          "editcurrent": ("editor", "close"),
      }, str(sw.PREFLIGHT))
js = sw.active_link_js("add")
check("active link js marks exactly one of three and never presses",
      "\"add\"" in js and "'decks'" in js and "'add'" in js and "'browse'" in js and "klaus-active" in js and "klaus-pressed" not in js, js)
check("toolbar css styles the active tab only", ".klaus-active" in sw.TOOLBAR_CSS and "klaus-pressed" not in sw.TOOLBAR_CSS)
check("browse menus are Anki's five, in bar order",
      sw.BROWSE_MENUS == ("menuEdit", "menuqt_accel_view", "menu_Notes", "menu_Cards", "menuJump"))
check("flag defaults on", sw.enabled({}) is True and sw.enabled({"single_window": False}) is False)
check("config ships the flag", json.load(open("klaus_note/config.json"))["single_window"] is True)

section("host layout")


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
    return win


mw = fake_mw()
tw, web, bw = mw.toolbarWeb, mw.web, mw.bottomWeb
host = sw.build_host(mw)
check("Anki's three webviews are the same objects", (mw.toolbarWeb, mw.web, mw.bottomWeb) == (tw, web, bw))
check("web and bottomWeb live inside the Decks page",
      web.parent() is host.pages["decks"] and bw.parent() is host.pages["decks"])
check("toolbar is above the stack",
      mw.form.centralwidget.layout().indexOf(tw) == 0 and mw.form.centralwidget.layout().indexOf(host.stack) == 1)
check("mw.mainLayout now points at the Decks page's layout", mw.mainLayout is host.pages["decks"].layout())
check("starts on decks", host.tab == "decks" and host.stack.currentWidget() is host.pages["decks"])
check("three pages, add in the middle", list(host.pages) == ["decks", "add", "browse"] and host.stack.count() == 3
      and host.stack.indexOf(host.pages["add"]) == 1)
seen = []
host.listeners.append(lambda new, old: seen.append((new, old)))
host.switch("browse")
check("switch changes the stack and tells listeners",
      host.stack.currentWidget() is host.pages["browse"] and seen == [("browse", "decks")])
host.switch("browse")
check("switching to the same tab is a no-op", seen == [("browse", "decks")])
host.switch("add")
host.switch("browse")
check("previous follows the switches", host.previous == "add" and host.tab == "browse")

section("host layout with the main webview wrapped by another add-on")
# AMBOSS (sidepanel.py:205) and AnkiHub (gui/reviewer.py:160) take mw.web
# out of mw.mainLayout and insert a QSplitter holding it in its place.
mw2 = fake_mw()
idx = mw2.mainLayout.indexOf(mw2.web)
mw2.mainLayout.removeWidget(mw2.web)
split = QtWidgets.QSplitter()
split.addWidget(mw2.web)
mw2.mainLayout.insertWidget(idx, split)
web2, split2 = mw2.web, split
host2 = sw.build_host(mw2)
for _ in range(3):
    app.processEvents()
check("the splitter and the webview survive, inside the Decks page",
      not sip.isdeleted(web2) and not sip.isdeleted(split2) and split2.parent() is host2.pages["decks"]
      and web2.parent() is split2)
check("Decks page keeps the row order: splitter then bottomWeb",
      host2.pages["decks"].layout().indexOf(split2) == 0 and host2.pages["decks"].layout().indexOf(mw2.bottomWeb) == 1)
check("mw.mainLayout is the Decks layout and the splitter is a direct item of it",
      mw2.mainLayout is host2.pages["decks"].layout() and mw2.mainLayout.indexOf(split2) == 0)
check("the central layout was reused, not replaced",
      mw2.form.centralwidget.layout().indexOf(mw2.toolbarWeb) == 0 and mw2.form.centralwidget.layout().indexOf(host2.stack) == 1)

w = QtWidgets.QWidget()
host.set_content("browse", w)
check("set_content replaces the placeholder", host.content("browse") is w and w.parent() is host.pages["browse"])
host.set_content("browse", None)
check("None restores a placeholder", isinstance(host.content("browse"), QtWidgets.QLabel))

section("shims")
mwq = QtWidgets.QMainWindow()
mwq.show()
page = QtWidgets.QWidget()
QtWidgets.QVBoxLayout(page)
mwq.setCentralWidget(page)
page.show()


class AddLike(QtWidgets.QMainWindow):  # super().__init__ style (AddCards, EditCurrent)
    def __init__(self, mw):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.child = QtWidgets.QWidget(self)
        self.setCentralWidget(self.child)
        self.editor = object()
        self.form = None
        self.show()


Emb = sw.embedded_class(AddLike)
with sw.hosted(page):
    a = Emb(None)
check("Add-style window is born a child of the page", a.parent() is page and not a.isWindow())
check("a widget created inside it has the main window as top-level", a.child.window() is mwq)
check("it is still an instance of the original class", isinstance(a, AddLike))
check("hosted() clears the target afterwards", sw._Shim.target is None)

fake = types.ModuleType("aqt.browser.browser")  # the name the real class carries in __module__
fake.QMainWindow, fake.Qt, fake.QWidget = QtWidgets.QMainWindow, QtCore.Qt, QtWidgets.QWidget
BROWSER_SRC = (
    "class Browser(QMainWindow):\n"
    "    def __init__(self, mw, card=None, search=None):\n"
    "        QMainWindow.__init__(self, None, Qt.WindowType.Window)\n"
    "        self.table = self.sidebar = self.editor = object(); self.form = None\n"
    "        self.child = QWidget(self); self.setCentralWidget(self.child); self.show()\n"
)
exec(BROWSER_SRC, fake.__dict__)
sys.modules["aqt.browser.browser"] = fake  # what make_browser imports
sw._state.mw = mwq
hmw = fake_mw()  # kept alive: Qt deletes an unreferenced window
sw._state.host = sw.build_host(hmw)
hmw.show()
b = sw.make_browser(mwq)
bpage = sw._state.host.pages["browse"]
check("Browse is born a child of the Browse page", b.parent() is bpage and not b.isWindow())
check("the placeholder is gone and Browse is the page's only child",
      bpage.layout().count() == 1 and sw._state.host.content("browse") is b)
check("its child has the host's main window as top-level", b.child.window() is bpage.window())
check("the module's QMainWindow name is restored", fake.QMainWindow is QtWidgets.QMainWindow)
exec("class Browser(QMainWindow):\n"
     "    def __init__(self, mw, card=None, search=None): raise RuntimeError('boom')\n", fake.__dict__)
try:
    sw.make_browser(mwq)
    raised = False
except RuntimeError:
    raised = True
check("a raising constructor still restores the name", raised and fake.QMainWindow is QtWidgets.QMainWindow)

section("preflight fallback")
exec("class Browser(QMainWindow):\n"
     "    def __init__(self, mw, card=None, search=None):\n"
     "        QMainWindow.__init__(self, None, Qt.WindowType.Window); self.show()\n", fake.__dict__)
sw._state.disabled = None
b2 = sw.make_browser(mwq)
check("missing attributes: the built (hosted) instance is kept, never destroyed, and the session is disabled (I5)",
      not b2.isWindow() and not sip.isdeleted(b2) and sw._state.disabled is not None and "table" in sw._state.disabled)
d = QtWidgets.QDockWidget("x", b)
b.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, d)
b.restoreGeometry(b.saveGeometry())
check("child main window accepts a dock and survives restoreGeometry", d.parent() is b and b.parent() is bpage)

section("registry")
# Anki 26.09 registers five hosted names: the legacy and the new Add /
# Edit Current screens, and Browse. Classes come from the registry itself.
exec(BROWSER_SRC, fake.__dict__)
opened = {}
originals = {"Browser": [fake.Browser, None], "AddCards": [AddLike, None], "NewAddCards": [AddLike, None],
             "EditCurrent": [AddLike, None], "NewEditCurrent": [AddLike, None], "Preferences": [AddLike, None]}
orig_classes = {k: v[0] for k, v in originals.items()}
sys.modules["aqt"].dialogs = types.SimpleNamespace(
    register_dialog=lambda name, creator, instance=None: (opened.__setitem__(name, creator),
                                                          originals.__setitem__(name, [creator, instance])),
    _dialogs=originals)
sw._state.disabled = None
sw.register(mwq)
check("the five hosted names get creators, Preferences is left alone",
      set(opened) == {"Browser", "AddCards", "NewAddCards", "EditCurrent", "NewEditCurrent"})
check("originals remembered for the fallback",
      sw._state.original_creators == {k: orig_classes[k] for k in opened})
sw._state.add = sw.build_add_page(sw._state.host.pages["add"], mwq)
with_slot = opened["NewAddCards"](mwq)
check("the registered Add creator builds inside the Add page's editor slot",
      not with_slot.isWindow() and with_slot.parent() is sw._state.add.editor_slot
      and isinstance(with_slot, AddLike))
edit = opened["NewEditCurrent"](mwq)
sw._state.docks["edit"].show()
app.processEvents()
check("the registered Edit creator builds inside a fresh Edit dock on the right",
      not edit.isWindow() and edit.parent() is sw._state.docks["edit"].widget()
      and mwq.dockWidgetArea(sw._state.docks["edit"]) == QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
sw._state.docks["edit"].hide()
b3 = opened["Browser"](mwq, card=None)
check("the registered Browse creator hosts through the module swap and restores the name",
      b3.parent() is bpage and fake.QMainWindow is QtWidgets.QMainWindow)
originals["Browser"][1] = b3  # a live instance Anki's closeAll must still see
sw.disable("test")
check("disable restores Anki's creators and keeps the live instances in the registry (I4)",
      all(opened[k] is sw._state.original_creators[k] for k in opened) and originals["Browser"][1] is b3)

section("menu swap")
mw2 = QtWidgets.QMainWindow()
bar = mw2.menuBar()
mw2.form = types.SimpleNamespace(menuHelp=bar.addMenu("Help"))
bar.insertMenu(mw2.form.menuHelp.menuAction(), QtWidgets.QMenu("Tools", mw2))  # Tools before Help
br = QtWidgets.QMainWindow()
brf = types.SimpleNamespace()
for n, t in (("menuEdit", "Edit"), ("menu_Notes", "Notes"), ("menuJump", "Go")):
    setattr(brf, n, br.menuBar().addMenu(t))
br.form = brf
sw.menus_in(mw2, br)
titles = [a.text() for a in bar.actions()]
check("Browse's menus sit before Help in the host bar", titles == ["Tools", "Edit", "Notes", "Go", "Help"], str(titles))
check("their actions are exempt from the Add-ons watcher",
      {m.menuAction() for m in (brf.menuEdit, brf.menu_Notes, brf.menuJump)} <= mw2._klaus_note_keep_on_bar)
sw.menus_in(mw2, br)
check("twice is a no-op", [a.text() for a in bar.actions()] == titles and sw._state.menus_in)
sw.menus_out(mw2)
check("out removes them", [a.text() for a in bar.actions()] == ["Tools", "Help"] and not sw._state.menus_in)
brf.menuJump = None
br._klaus_note_addons_menu = QtWidgets.QMenu("Add-ons", br)
sw.menus_in(mw2, br)
check("Browse's Add-ons menu is retitled while in the host bar",
      "Browse Add-ons" in [a.text() for a in bar.actions()] and "Add-ons" not in [a.text() for a in bar.actions()])
sw.menus_out(mw2)
check("…and gets its title back", br._klaus_note_addons_menu.title() == "Add-ons")

section("Browse shortcuts fire only on the Browse tab")
from PyQt6 import QtTest  # noqa: E402


class FakeBrowser(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.table = self.sidebar = self.editor = object()
        self.form = types.SimpleNamespace(menu_Notes=self.menuBar().addMenu("Notes"))
        self.form.actionClose = QtGui.QAction("Close", self)  # setupUi binds it to _handle_close
        self.form.actionClose.triggered.connect(self._handle_close)

    def _handle_close(self):  # mirrors Anki's Browse: Cmd+W closes the ACTIVE window
        active = QtWidgets.QApplication.activeWindow()
        if active and active is not self:
            (active.reject if isinstance(active, QtWidgets.QDialog) else active.close)()
        else:
            self.close()

    def keyPressEvent(self, ev):  # mirrors Anki's Browse: Escape closes
        if ev.key() == QtCore.Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)

mw3 = fake_mw()
mw3.form.menuHelp = mw3.menuBar().addMenu("Help")
host3 = sw.build_host(mw3)
br3 = FakeBrowser()
hit = []
act = br3.menuBar().actions()[0].menu().addAction("Forget")
act.setShortcut("Ctrl+Alt+N")
act.triggered.connect(lambda: hit.append(1))
with sw.hosted(host3.pages["browse"]):
    pass
br3.setParent(host3.pages["browse"], QtCore.Qt.WindowType.Widget)  # a plain widget stands in; construction is Task 3's
host3.pages["browse"].layout().addWidget(br3)
br3.menuBar().hide()
br3.show()
mw3.show()
QtWidgets.QApplication.setActiveWindow(mw3)
app.processEvents()


def press():
    ev = QtGui.QKeyEvent(QtCore.QEvent.Type.ShortcutOverride, QtCore.Qt.Key.Key_N,
                         QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.AltModifier)
    QtWidgets.QApplication.sendEvent(mw3, ev)
    QtTest.QTest.keyClick(mw3, QtCore.Qt.Key.Key_N,
                          QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.AltModifier)
    app.processEvents()


host3.switch("decks")
sw.menus_out(mw3)
press()
check("Browse action shortcut is silent on the Decks tab", hit == [])
host3.switch("browse")
sw.menus_in(mw3, br3)
press()
check("…and fires on the Browse tab", hit == [1], str(hit))

section("navigation")
hk = importlib.import_module("klaus_note.host_keys")


def pump():
    """deleteLater() called at the test's top loop level is only honoured
    after an explicit DeferredDelete flush; then the singleShot(0) follow-ups."""
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    for _ in range(3):
        app.processEvents()

mw6 = fake_mw()
evals = []
mw6.toolbarWeb.eval = evals.append
mw6.form.menuHelp = mw6.menuBar().addMenu("Help")
mw6.stateShortcuts = []
sys.modules["aqt"].dialogs = types.SimpleNamespace(
    register_dialog=lambda name, creator, instance=None: None,
    _dialogs={"Browser": [object(), None], "AddCards": [object(), None], "NewAddCards": [object(), None],
              "EditCurrent": [object(), None], "NewEditCurrent": [object(), None]})
sw._state.mw = mw6
sw._state.host = sw.build_host(mw6)
sw._state.docks = {}
sw._state.browser = sw._state.addcards = sw._state.editcurrent = None
sw._state.menus_in, sw._state.moved_menus = False, []
sw._state.active, sw._state.disabled = True, None
sw._state.recorder = hk.Recorder()
sw._state.host.listeners.append(sw._on_tab_switch)
sw._state.add = sw.build_add_page(sw._state.host.pages["add"], mw6)
mw6.show()
host6 = sw._state.host
rh = importlib.import_module("klaus_note.reader_host")
rh.make_reader = lambda parent: type("R0", (QtWidgets.QLabel,), {"cleanup": lambda self: setattr(self, "cleaned", True)})("r", parent)  # never the real PdfSidebar under stubs
check("the editor slot starts with the placeholder, the splitter holds tree | reader | editor",
      sw._state.add.editor_slot.layout().count() == 1
      and isinstance(sw._state.add.editor_slot.layout().itemAt(0).widget(), QtWidgets.QLabel)
      and sw._state.add.splitter.count() == 3 and sw._state.add.splitter.widget(0) is sw._state.add.tree
      and sw._state.add.splitter.widget(1) is sw._state.add.reader_slot and sw._state.add.splitter.widget(2) is sw._state.add.editor_slot
      and sw._state.add.splitter.objectName() == "klaus_note_add_splitter")
check("the status bar sits under the splitter; its pane toggles are in the top bar",
      sw._state.add.bar is not None and sw._state.add.bar.sidebar_btn is None and sw._state.add.bar.editor_btn is None
      and sw._state.add.bar.dock_btn is None)

with sw.hosted(host6.pages["browse"]):
    b = sw.embedded_class(FakeBrowser)()
host6.set_content("browse", b)
closed = []
b.close = lambda: closed.append(1) or True
sw._on_browser_will_show(b)
check("a hosted Browse is recorded and its menu bar hidden", sw._state.browser is b and b.menuBar().isHidden())
sw._on_dialog_opened(None, "Browser", b)
check("open switches the tab, moves menus in, suspends the state keys",
      host6.tab == "browse" and sw._state.menus_in and sw._state.recorder.suspended)
check("…and pushes the active link", bool(evals) and "\"browse\"" in evals[-1])
sw._on_state_did_change("deckBrowser", "review")
check("a main-state change switches back, moves menus out, resumes the keys",
      host6.tab == "decks" and not sw._state.menus_in and not sw._state.recorder.suspended)
host6.switch("browse")
esc = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)
QtWidgets.QApplication.sendEvent(b, esc)
check("Escape in Browse is swallowed", closed == [] and esc.isAccepted())
mw_closed = []
mw6.close = lambda: mw_closed.append(1) or True
QtWidgets.QApplication.setActiveWindow(mw6)
b.form.actionClose.trigger()
check("Cmd+W in hosted Browse closes Browse, never the main window",
      QtWidgets.QApplication.activeWindow() is mw6 and closed == [1] and mw_closed == [],
      f"active={QtWidgets.QApplication.activeWindow()} closed={closed} mw_closed={mw_closed}")
dlg = QtWidgets.QDialog(mw6)
rejected = []
dlg.rejected.connect(lambda: rejected.append(1))
dlg.show()
QtWidgets.QApplication.setActiveWindow(dlg)
b.form.actionClose.trigger()
check("…while a dialog is active, Cmd+W rejects the dialog and keeps Browse",
      rejected == [1] and closed == [1] and mw_closed == [], f"rejected={rejected} closed={closed}")
dlg.deleteLater()
del mw6.close
app.processEvents()  # the dialog's hide settles first, or mw6 is left inactive
QtWidgets.QApplication.setActiveWindow(mw6)
closed.clear()
redrawn = []
b.table = types.SimpleNamespace(redraw_cells=lambda: redrawn.append("t"))
b.sidebar = types.SimpleNamespace(refresh_if_needed=lambda: redrawn.append("s"))
sw._on_op_executed(object(), None)
check("an op on the Browse tab redraws table and sidebar", redrawn == ["t", "s"])
host6.switch("decks")
redrawn.clear()
sw._on_op_executed(object(), None)
check("…not on the Decks tab", redrawn == [])
host6.switch("browse")
b.deleteLater()
pump()
check("destroyed Browse leaves a placeholder and no menus",
      isinstance(host6.content("browse"), QtWidgets.QLabel) and sw._state.browser is None and not sw._state.menus_in,
      f"content={type(host6.content('browse')).__name__} count={host6.pages['browse'].layout().count()} browser={sw._state.browser} menus_in={sw._state.menus_in}")
host6.switch("decks")

section("add tab")
add_closed = []


class FakeAdd(QtWidgets.QMainWindow):  # mirrors 26.09's NewAddCards close flow
    def __init__(self, mw):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.editor = object()
        self.form = None
        self._close_event_has_cleaned_up = False
        self.field = QtWidgets.QLineEdit(self)
        self.setCentralWidget(self.field)
        self.show()

    def closeEvent(self, evt):
        if self._close_event_has_cleaned_up:
            evt.accept()
            return
        evt.ignore()
        self._close()

    def _close(self):
        self._close_event_has_cleaned_up = True
        add_closed.append(1)
        self.close()


slot6 = sw._state.add.editor_slot
host6.switch("browse")
with sw.hosted(sw._target("add", mw6)):
    a = sw.embedded_class(FakeAdd)(None)
sw._on_add_cards_did_init(a)
sw._on_dialog_opened(None, "NewAddCards", a)
check("open lands Add in the editor slot alone and switches the tab, previous = browse",
      not a.isWindow() and sw._hosted_in(a, slot6) and slot6.layout().count() == 1 and host6.tab == "add"
      and host6.previous == "browse" and sw._state.addcards is a and "\"add\"" in evals[-1])
check("the Add tab suspends the state keys", sw._state.recorder.suspended)
a.close()
app.processEvents()
check("a user Close returns to the previous tab and keeps the instance",
      host6.tab == "browse" and add_closed == [] and a.parent() is slot6 and sw._state.addcards is a)
host6.switch("add")
esc = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)
QtWidgets.QApplication.sendEvent(a, esc)
check("Escape does the same", host6.tab == "browse" and sw._state.addcards is a and esc.isAccepted())
host6.switch("add")
a.field.setFocus()
app.processEvents()
check("focus_in_editor sees a focused child of the editor slot", sw.focus_in_editor() is True)
sw._state.add.tree.filter.setFocus()
app.processEvents()
check("…not the Library tree", sw.focus_in_editor() is False)
mw6.web.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
mw6.web.setFocus()
app.processEvents()
check("…and not focus on the deck screen", sw.focus_in_editor() is False)
a._close_event_has_cleaned_up = True  # Anki's own teardown
a.close()
a.deleteLater()
pump()
check("Anki's teardown passes and the editor slot gets its placeholder back",
      sw._state.addcards is None and slot6.layout().count() == 1
      and isinstance(slot6.layout().itemAt(0).widget(), QtWidgets.QLabel),
      f"addcards={sw._state.addcards} count={slot6.layout().count()} closed={add_closed}")

section("close-all on the Add tab")
with sw.hosted(sw._target("add", mw6)):
    a2 = sw.embedded_class(FakeAdd)(None)
sw._on_add_cards_did_init(a2)
sw._on_dialog_opened(None, "NewAddCards", a2)
rh.set_home(sw._state.add.reader_slot)
r6 = rh.reader()
a2._close_event_has_cleaned_up = True
a2.close()
a2.deleteLater()
pump()
check("the tab stays, the slot shows its placeholder, the reader slot is untouched",
      host6.tab == "add" and sw._state.addcards is None and isinstance(slot6.layout().itemAt(0).widget(), QtWidgets.QLabel)
      and rh.reader() is r6 and r6.parent() is sw._state.add.reader_slot)
rh.release()
rh.make_reader = lambda parent: type("R0", (QtWidgets.QLabel,), {"cleanup": lambda self: setattr(self, "cleaned", True)})("r", parent)
host6.switch("decks")
host6.switch("add")
check("showing the Add tab builds the reader in its slot (I-2: last session's tabs are visible before any click)",
      rh._state["reader"] is not None and rh._state["reader"].parent() is sw._state.add.reader_slot)
host6.switch("decks")
check("the deleted machinery is gone (open_add too: Anki's dialogs.open is the one route in)",
      not any(hasattr(sw, n) for n in ("make_add_dock", "_ensure_add_dock", "toggle_dock", "DOCK_PLACEHOLDERS", "open_add"))
      and not hasattr(sw._state, "last_dock") and "add" not in sw._state.docks)

section("edit current")


class FakeEditCurrent(QtWidgets.QMainWindow):  # Anki hides it on close and never deletes it
    def __init__(self, mw):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.editor = object()
        self.show()


with sw.hosted(sw._new_edit_dock(mw6).widget()):
    ec = sw.embedded_class(FakeEditCurrent)(None)
ed = types.SimpleNamespace(editorMode=types.SimpleNamespace(name="EDIT_CURRENT"), parentWindow=ec)
sw._on_editor_did_init(ed)
sw._on_dialog_opened(None, "NewEditCurrent", ec)
check("Edit sits in its own dock, shown and raised",
      "edit" in sw._state.docks and not ec.isWindow() and sw._state.docks["edit"].isVisible()
      and sw._state.editcurrent is ec)
ec.close()
for _ in range(3):
    app.processEvents()
check("closing it removes the Edit dock and reaps the orphan once the registry shows it closed",
      "edit" not in sw._state.docks and sw._state.editcurrent is None and sip.isdeleted(ec))

section("dock state")
mw6.pm = types.SimpleNamespace(profile={})
sw._new_edit_dock(mw6).show()
sw.save_dock_state(mw6)
check("dock state is saved under Klaus's own profile key", isinstance(mw6.pm.profile.get("klaus_note_host_state"), bytes))
sw.restore_dock_state(mw6)
check("restore leaves every dock hidden (startup: dock closed)", not sw.dock_shown())
sw._state.docks.pop("edit").deleteLater()
pump()

section("toolbar indicator")
tasks = importlib.import_module("klaus_note.tasks")
tasks.clock = lambda: 1000.0
wc = types.SimpleNamespace(head="", body="")
sw._on_toolbar_content(wc, type("TopToolbar", (), {})())
check("toolbar gets the indicator css when active", "klaus-active" in wc.head)
wc2 = types.SimpleNamespace(head="", body="")
sw._on_toolbar_content(wc2, type("Other", (), {})())
check("…only for the top toolbar", wc2.head == "")
evals.clear()
sw._on_toolbar_redraw(None)
check("redraw pushes the active-link js", bool(evals) and "klaus-active" in evals[-1])

section("destroyed while active, then back to Decks")
with sw.hosted(host6.pages["browse"]):
    b7 = sw.embedded_class(FakeBrowser)()
sw._on_browser_will_show(b7)
sw._on_dialog_opened(None, "Browser", b7)
check("on the Browse tab the keys are suspended", host6.tab == "browse" and sw._state.recorder.suspended)
b7.deleteLater()
pump()
sw._on_state_did_change("deckBrowser", "deckBrowser")
check("after Anki deletes Browse mid-view and the deck screen returns, keys are back and menus gone",
      host6.tab == "decks" and not sw._state.recorder.suspended and not sw._state.menus_in
      and isinstance(host6.content("browse"), QtWidgets.QLabel))

section("fallback")
tasks.clear()
evals.clear()
host6.switch("browse")
sw._state.recorder.suspend(mw6)
sw.disable("preflight: table")
check("disabled records a sticky error task",
      any(t.error and "Single window unavailable" in t.message for t in tasks.snapshot()))
check("…is_active is false, the toolbar carries the reason, keys resumed",
      sw.is_active() is False and "table" in mw6.toolbarWeb.toolTip() and not sw._state.recorder.suspended)
b4 = FakeBrowser()
sw._on_browser_will_show(b4)
check("after disable, a top-level Browse is left alone", b4.isWindow() and sw._state.browser is not b4)
check("…and keeps Anki's own Cmd+W wiring", b4.form.actionClose.receivers(b4.form.actionClose.triggered) == 1)
wc3 = types.SimpleNamespace(head="", body="")
sw._on_toolbar_content(wc3, type("TopToolbar", (), {})())
check("…and the toolbar gets no indicator css", wc3.head == "")
host6.switch("decks")

section("setup")
HOOKS = ("main_window_did_init", "browser_will_show", "add_cards_did_init", "editor_did_init",
         "dialog_manager_did_open_dialog", "state_did_change", "operation_did_execute", "focus_did_change",
         "webview_will_set_content", "top_toolbar_did_redraw", "profile_did_open", "profile_will_close",
         "state_shortcuts_will_change")
hooks = types.SimpleNamespace(**{h: [] for h in HOOKS})
sys.modules["aqt"].gui_hooks = hooks
_settings.store = _settings.DictStore({"single_window": False})
sw.setup()
check("flag off: nothing is registered", all(len(getattr(hooks, h)) == 0 for h in HOOKS))
_settings.store = _settings.DictStore({})
sw.setup()
check("flag on: only main_window_did_init is registered at load", len(hooks.main_window_did_init) == 1
      and all(len(getattr(hooks, h)) == 0 for h in HOOKS if h != "main_window_did_init"))
mw8 = fake_mw()
mw8.form.menuHelp = mw8.menuBar().addMenu("Help")
mw8.stateShortcuts = []
mw8.clearStateShortcuts = mw8.setStateShortcuts = lambda *a: None
mw8.toolbarWeb.eval = evals.append
mw8.pm = types.SimpleNamespace(profile={})
sys.modules["aqt"].mw = mw8
registered = {}
sys.modules["aqt"].dialogs = types.SimpleNamespace(
    register_dialog=lambda name, creator, instance=None: registered.__setitem__(name, creator),
    _dialogs={"Browser": [FakeBrowser, None], "NewAddCards": [AddLike, None]})
sw._state.disabled = None
sw._state.docks = {}
hooks.main_window_did_init[0]()
check("init builds the host, the Add page (the reader's home), registers creators and every hook, and is active",
      sw._state.mw is mw8 and sw._state.host is not None and sw._state.add is not None
      and rh.has_home() and sw._state.add.reader_slot is rh._state["home"]
      and set(registered) == {"Browser", "NewAddCards"} and sw.is_active()
      and all(len(getattr(hooks, h)) == (2 if h == "state_did_change" else 1) for h in HOOKS)  # keys + tab switch
      and isinstance(sw._state.recorder, hk.Recorder)
      and sw._on_tab_switch in sw._state.host.listeners,
      str({h: len(getattr(hooks, h)) for h in HOOKS}))
saved, restored = [], []
for fake_utils in {id(m): m for m in (sys.modules.get("aqt.utils"), getattr(sys.modules["aqt"], "utils", None)) if m is not None}.values():
    fake_utils.saveSplitter = lambda w, key: saved.append((w, key))
    fake_utils.restoreSplitter = lambda w, key: restored.append((w, key))
hooks.profile_will_close[0]()
check("profile close saves the dock state and the Add splitter under one key",
      "klaus_note_host_state" in mw8.pm.profile and saved == [(sw._state.add.splitter, "klaus_note_add_tab")])
hooks.profile_did_open[0]()
check("profile open restores both and hides every dock", not sw.dock_shown() and restored[-1] == (sw._state.add.splitter, "klaus_note_add_tab"))
rh.make_reader = lambda parent: type("R0", (QtWidgets.QLabel,), {"cleanup": lambda self: setattr(self, "cleaned", True)})("r", parent)
r_before = rh.reader()
hooks.profile_will_close[0]()
check("profile close releases the reader (C-1: a cleaned PdfSidebar can never be reused)",
      getattr(r_before, "cleaned", False) and rh._state["reader"] is None)
check("…and the next reader() is a fresh one in the home", rh.reader() is not r_before and rh.reader().parent() is sw._state.add.reader_slot)
loaded8 = []
rh.make_reader = lambda parent: type("R", (QtWidgets.QLabel,), {"is_loaded": lambda self, n=None: False,
                                                                 "load_pdf": lambda self, n: loaded8.append(n),
                                                                 "cleanup": lambda self: None})("r", parent)
rh.release()
sw._state.add.tree.pdf_clicked.emit("Intro_to_CBC")
check("a tree click loads the PDF into the reader, built in its home", loaded8 == ["Intro_to_CBC"] and rh.reader().parent() is sw._state.add.reader_slot)

section("an add-on that shadows QObject.parent (Image Occlusion Enhanced sets self.parent = window)")
shadowed = QtWidgets.QWidget(host6.pages["add"])
shadowed.parent = a2 if not sip.isdeleted(a2) else object()  # the instance attribute IOE's ImgOccEdit sets
check("_inside walks past the shadowed attribute and still answers",
      sw._inside(shadowed, host6.pages["add"]) is True and sw._inside(shadowed, host6.pages["browse"]) is False)
check("_hosted_in too", sw._hosted_in(shadowed, host6.pages["add"]) is True)
raised = []
try:
    sw._on_focus_did_change(shadowed, None)
except Exception as exc:  # noqa: BLE001
    raised.append(exc)
check("focus landing in such a widget never raises", raised == [], repr(raised))

section("final review fixes")
# C1: a nested main window's NATIVE menu bar replaces the host's on macOS.
seen_attr = []
fake.QApplication, fake.seen_attr = QtWidgets.QApplication, seen_attr
exec("class Browser(QMainWindow):\n"
     "    def __init__(self, mw, card=None, search=None):\n"
     "        QMainWindow.__init__(self, None, Qt.WindowType.Window)\n"
     "        seen_attr.append(QApplication.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar))\n"
     "        self.menuBar().addMenu('Notes')  # created INSIDE the constructor, as Anki's setupUi does\n"
     "        self.table = self.sidebar = self.editor = object(); self.form = None\n"
     "        self.child = QWidget(self); self.setCentralWidget(self.child); self.show()\n", fake.__dict__)
sw._state.disabled = None
before = QtWidgets.QApplication.testAttribute(QtCore.Qt.ApplicationAttribute.AA_DontUseNativeMenuBar)
c1 = sw._construct("Browser", fake.Browser, mw8, module=fake)
check("C1: the menu bar is created while native bars are off, the bar is non-native afterwards, "
      "and the app attribute is restored",
      seen_attr == [True] and c1.menuBar().isNativeMenuBar() is False
      and QtWidgets.QApplication.testAttribute(QtCore.Qt.ApplicationAttribute.AA_DontUseNativeMenuBar) is before)


class BareAdd(QtWidgets.QMainWindow):  # Anki set no menu bar (non-mac): hiding must not create one
    def __init__(self, mw):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.editor = object()
        self.form = None
        self.show()


with sw.hosted(sw._target("add", mw8)):
    bare = sw.embedded_class(BareAdd)(None)
sw._on_add_cards_did_init(bare)
check("C1: the hide sites create no menu bar", bare.menuWidget() is None)

# I1: Klaus's refresh runs AFTER Browse's own handler.
hooks.operation_did_execute.clear()
hooks.focus_did_change.clear()
hooks.operation_did_execute.append(sw._on_op_executed)
hooks.focus_did_change.append(sw._on_focus_did_change)
own = lambda *a: None  # noqa: E731 - stands for Browser.on_operation_did_execute
hooks.operation_did_execute.append(own)
hooks.focus_did_change.append(own)
sw._on_browser_will_show(c1)
check("I1: Klaus's op and focus handlers are re-appended after Browse's",
      hooks.operation_did_execute.index(own) < hooks.operation_did_execute.index(sw._on_op_executed)
      and hooks.focus_did_change.index(own) < hooks.focus_did_change.index(sw._on_focus_did_change))

# I2 + I3: on the Browse tab, host-bar actions that collide with Browse keys or are bare keys
# are parked, and mw's permanent bare-key QShortcuts are disabled; all restored on leaving.
tools = mw8.menuBar().addMenu("Tools")
switch_profile = tools.addAction("Switch Profile"); switch_profile.setShortcut("Ctrl+Shift+P")
filtered = tools.addAction("Create Filtered Deck"); filtered.setShortcut("F")
export = tools.addAction("Export"); export.setShortcut("Ctrl+E")
mw8.menuBar().removeAction(mw8.form.menuHelp.menuAction()); mw8.menuBar().addMenu(mw8.form.menuHelp)
notes = c1.menuBar().actions()[0].menu()
c1.form = types.SimpleNamespace(menu_Notes=notes)
preview = notes.addAction("Preview"); preview.setShortcut("Ctrl+Shift+P")
sync_key = QtGui.QShortcut(QtGui.QKeySequence("y"), mw8)
decks_key = QtGui.QShortcut(QtGui.QKeySequence("d"), mw8)
browse_key = QtGui.QShortcut(QtGui.QKeySequence("b"), mw8)
add_key = QtGui.QShortcut(QtGui.QKeySequence("a"), mw8)
state_key = QtGui.QShortcut(QtGui.QKeySequence("e"), mw8)
mw8.stateShortcuts = [state_key]
sw._state.browser = c1
sw._state.host.switch("browse")
check("the tab keys d, b and a stay live on the Browse tab",
      decks_key.isEnabled() and browse_key.isEnabled() and add_key.isEnabled())
sw._park_host_keys(mw8, c1)  # a second park while still on the tab must not lose the originals
check("I2: a host action colliding with a Browse key is parked, a bare-key one too, others stay",
      switch_profile.shortcut().isEmpty() and filtered.shortcut().isEmpty() and export.shortcut().toString() == "Ctrl+E")
check("I3: mw's permanent bare-key shortcut is disabled on the Browse tab", not sync_key.isEnabled() and not state_key.isEnabled())
sw._state.host.switch("decks")
check("…and everything comes back on Decks",
      switch_profile.shortcut().toString() == "Ctrl+Shift+P" and filtered.shortcut().toString() == "F"
      and sync_key.isEnabled() and state_key.isEnabled())

# Browse rebuilt while its tab already shows (Close Browse, then b): menus must still come in.
sw._state.host.switch("browse")
c1.deleteLater()
pump()
check("after Close Browse the tab stays with a placeholder, menus out, host keys unparked",
      sw._state.host.tab == "browse" and not sw._state.menus_in and sync_key.isEnabled()
      and switch_profile.shortcut().toString() == "Ctrl+Shift+P")
c2 = sw._construct("Browser", fake.Browser, mw8, module=fake)
notes2 = c2.menuBar().actions()[0].menu()
c2.form = types.SimpleNamespace(menu_Notes=notes2)
sw._on_browser_will_show(c2)
check("a Browse rebuilt on the showing tab gets its menus into the host bar and keys parked",
      sw._state.browser is c2 and sw._state.menus_in and not sync_key.isEnabled())
sw._state.host.switch("decks")
check("…and Decks restores them", not sw._state.menus_in and sync_key.isEnabled())
sw._state.host.switch("browse")
sw.disable("mid-session")
check("disable unparks the host keys", sync_key.isEnabled() and switch_profile.shortcut().toString() == "Ctrl+Shift+P")
sw._state.disabled = None
sw._state.host.switch("decks")

# The Add tab parks bare host keys exactly as the Browse tab does.
sw._state.host.switch("add")
check("the Add tab parks bare host keys and mw's bare-key shortcuts; d, b, a stay live",
      filtered.shortcut().isEmpty() and not sync_key.isEnabled() and export.shortcut().toString() == "Ctrl+E"
      and decks_key.isEnabled() and browse_key.isEnabled() and add_key.isEnabled() and sw._state.recorder.suspended)
sw._state.host.switch("decks")
check("…and Decks restores them", filtered.shortcut().toString() == "F" and sync_key.isEnabled() and not sw._state.recorder.suspended)
with sw.hosted(sw._target("add", mw8)):
    a8 = sw.embedded_class(FakeAdd)(None)
sw._on_add_cards_did_init(a8)
sw._state.host.switch("browse")
sw._forget_browser_now()
sw.disable("mid-session")
check("forgetting Browse and disable both give the reader back (no-ops here: it is home)", rh.reader().parent() is sw._state.add.reader_slot)
sw._state.disabled = None

raise SystemExit(report())
