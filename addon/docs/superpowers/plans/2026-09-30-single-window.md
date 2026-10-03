# Single Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anki's main window becomes the only daily window: Decks and Browse as tabs under Anki's toolbar, Add and Edit Current embedded in a right dock area shared with Klaus's PDF dock, with a guarded fallback to stock windows.

**Architecture:** One new module `klausmate/single_window.py` owns the host layout (a stacked widget under the toolbar), the construction-time shims registered in Anki's dialog registry so Browse, Add, and Edit Current are built as children of the host from their first line (never moved: the August attempt moved them and every webview went black, K-090..K-094), the menu swap, navigation, lifecycle, and fallback. A live gate after Task 3 stops the plan until the editor is seen rendering in Anki. A second module `klausmate/host_keys.py` scopes the keyboard. Existing modules get small hooks: the PDF dock's host, one toggle in each bottom bar, toolbar link classes.

**Tech Stack:** Python 3, PyQt6 through `aqt.qt`, Anki `gui_hooks`, the repo's offscreen test harness (`tests/*.py` with `anki_stubs`), node for DOM tests where needed.

**Spec:** `docs/superpowers/specs/2026-09-30-single-window-design.md`

## Global Constraints

- Never move a window that is not Browse, Add, or Edit Current; everything else stays a window (spec, Out of scope).
- Config flag `single_window`, default `true`; `false` means no code path in this plan runs (spec, Fallback).
- Every hook body is `try/except Exception` with a `[klausmate]` print; nothing raises into Anki.
- A failed embed leaves the instance a shown top-level window and disables embedding for the session, with one notice: toolbar tooltip plus sticky error task keyed `single_window` (spec, Fallback).
- No monkeypatching of Anki functions, with one ruled exception: the name `QMainWindow` in `aqt.browser.browser` is swapped for the duration of one `Browser(...)` construction and restored in a `finally` (spec, "The August attempt").
- Never re-parent a window Anki built as a top-level; a window Klaus hosts is a child from its first line, or it stays Anki's window.
- js-message handlers that open a window defer with `QTimer.singleShot(0, …)` (`tests/test_bridge_reentrancy.py` rule).
- Tests run as `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/<file>.py` and use `check/section/report` from `anki_stubs`.
- `user_files/` and `meta.json*` are never staged. Commit only when the user asks; the commit steps below are the staging list for that moment.
- macOS has no `timeout`; use `perl -e 'alarm 120; exec @ARGV' python3 …` for the suite loop.

## Review Focus

0. The editor webview inside an embedded window renders in the live app. Offscreen frames were perfect while the screen was black in August, so no test here can prove it: Task 3's live gate is the check, and the plan does not continue past it without Pouya's confirmation.
1. Sync while the Browse tab is showing: Anki's close-all deletes Browse mid-view; the page must show its placeholder, menus must leave the host bar, and state shortcuts must be restored (Task 8 tests "destroyed while active").
2. `dialogs.open("Browser", search=…)` from Add's History menu while focus is in the Add dock: tab must switch and Browse's `reopen` must still run (Task 6 test "open from add-on switches tab").
3. Right-to-left layout: Browse restores geometry under `editorRTL`; the embed must not raise on either key (Task 3 test "restoreGeometry on a child does not raise").
4. Space and Enter with focus in the Add editor during a review: must type, never answer (Task 5 test "space in dock is overridden").
5. A second add-on that calls `browser.addDockWidget` on the embedded Browse: nested main windows keep their own dock areas, so it must still work (Task 3 test "child main window still accepts a dock").

---

### Task 1: Config flag and the pure helpers

**Files:**
- Create: `klausmate/single_window.py` (pure part only)
- Modify: `klausmate/config.json` (add `"single_window": true` after `"klausbook_design"`), `klausmate/config.md` (one entry)
- Test: `tests/test_single_window.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PREFLIGHT: dict[str, tuple[str, ...]]` with keys `"mw"`, `"browser"`, `"addcards"`, `"editcurrent"`.
  - `preflight(kind: str, obj) -> list[str]` — names in `PREFLIGHT[kind]` that `obj` lacks (`hasattr`), in order.
  - `BROWSE_MENUS = ("menuEdit", "menuqt_accel_view", "menu_Notes", "menu_Cards", "menuJump")`.
  - `active_link_js(tab: str, dock_shown: bool) -> str` — JS that sets class `klaus-active` on exactly one of `#decks`/`#browse` and toggles `klaus-pressed` on `#add`.
  - `TOOLBAR_CSS: str` — rules for `.hitem.klaus-active` and `.hitem.klaus-pressed` (underline and a subtle background from `theme.palette`; both palettes keyed on Anki's night-mode class, as `theme.toolbar_css` does).
  - `enabled(cfg: dict) -> bool` — `cfg.get("single_window", True)`.

- [ ] **Step 1: Write the failing tests**

```python
section("pure helpers")
sw = importlib.import_module("klausmate.single_window")
check("preflight lists what is missing, in order",
      sw.preflight("browser", types.SimpleNamespace(table=1)) ==
      [n for n in sw.PREFLIGHT["browser"] if n != "table"])
check("preflight is empty when everything exists",
      sw.preflight("mw", types.SimpleNamespace(**{n: 1 for n in sw.PREFLIGHT["mw"]})) == [])
js = sw.active_link_js("browse", True)
check("active link js marks browse, unmarks decks, presses add",
      "browse" in js and "klaus-active" in js and "klaus-pressed" in js and "'decks'" in js)
check("flag defaults on", sw.enabled({}) is True and sw.enabled({"single_window": False}) is False)
check("config ships the flag", json.load(open("klausmate/config.json"))["single_window"] is True)
```

`PREFLIGHT` values to pin in the test file as a source pin (exact tuples):
- `"mw"`: `("web", "bottomWeb", "toolbarWeb", "form", "stateShortcuts", "clearStateShortcuts", "setStateShortcuts", "addDockWidget", "tabifyDockWidget", "menuBar")`
- `"browser"`: `("table", "sidebar", "form", "menuBar", "close", "editor")`
- `"addcards"`: `("closeButton", "editor", "close")`
- `"editcurrent"`: `("editor", "close")`

- [ ] **Step 2: Run it to verify it fails**

Run: `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_single_window.py`
Expected: FAIL with `ModuleNotFoundError: klausmate.single_window`

- [ ] **Step 3: Implement the pure part**

Module docstring: what the module is (host, embed, navigation, lifecycle, fallback), pure builders above a `# ── aqt glue ──` divider as in `bottom_row.py`. Implement the five names above. `active_link_js` is a single string built from `json.dumps(tab)` and `json.dumps(dock_shown)`.

- [ ] **Step 4: Run it to verify it passes**

Run: same command. Expected: `all N checks passed` (the harness's report line).

- [ ] **Step 5: Commit (when asked)**

```bash
git add klausmate/single_window.py klausmate/config.json klausmate/config.md tests/test_single_window.py
git commit -m "Single window: config flag and pure helpers"
```

---

### Task 2: The host layout

**Files:**
- Modify: `klausmate/single_window.py` (aqt glue)
- Test: `tests/test_single_window.py`

**Interfaces:**
- Consumes: Task 1 names.
- Produces:
  - `class Host`: attributes `stack: QStackedWidget`, `pages: dict[str, QWidget]` (`"decks"`, `"browse"`), `tab: str`, `listeners: list[Callable[[str, str], None]]` (new, old). Methods `switch(tab: str) -> None` (no-op when same; calls listeners after the stack changes), `set_content(tab: str, widget) -> None` (replaces the page's single child; `None` restores the placeholder), `content(tab: str)`.
  - `build_host(mw) -> Host` — rebuilds `mw.form.centralwidget`'s layout as toolbar above a `QStackedWidget`; the Decks page holds `mw.web` and `mw.bottomWeb` in a zero-margin `QVBoxLayout`; the Browse page holds a placeholder `QLabel` ("Browse is closed. Press B to open it.").
  - `placeholder(text: str) -> QWidget`.

- [ ] **Step 1: Write the failing tests**

```python
section("host layout")
def fake_mw():
    win = QtWidgets.QMainWindow()
    central = QtWidgets.QWidget(); win.setCentralWidget(central)
    lay = QtWidgets.QVBoxLayout(central)
    win.toolbarWeb, win.web, win.bottomWeb = (QtWidgets.QWidget() for _ in range(3))
    for w in (win.toolbarWeb, win.web, win.bottomWeb): lay.addWidget(w)
    win.form = types.SimpleNamespace(centralwidget=central)
    return win
mw = fake_mw(); tw, web, bw = mw.toolbarWeb, mw.web, mw.bottomWeb
host = sw.build_host(mw)
check("Anki's three webviews are the same objects", (mw.toolbarWeb, mw.web, mw.bottomWeb) == (tw, web, bw))
check("web and bottomWeb live inside the Decks page",
      web.parent() is host.pages["decks"] and bw.parent() is host.pages["decks"])
check("toolbar is above the stack",
      mw.form.centralwidget.layout().indexOf(tw) == 0 and mw.form.centralwidget.layout().indexOf(host.stack) == 1)
check("starts on decks", host.tab == "decks" and host.stack.currentWidget() is host.pages["decks"])
seen = []; host.listeners.append(lambda new, old: seen.append((new, old)))
host.switch("browse")
check("switch changes the stack and tells listeners", host.stack.currentWidget() is host.pages["browse"] and seen == [("browse", "decks")])
host.switch("browse")
check("switching to the same tab is a no-op", seen == [("browse", "decks")])
w = QtWidgets.QWidget(); host.set_content("browse", w)
check("set_content replaces the placeholder", host.content("browse") is w and w.parent() is host.pages["browse"])
host.set_content("browse", None)
check("None restores a placeholder", isinstance(host.content("browse"), QtWidgets.QLabel))
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL with `AttributeError: module 'klausmate.single_window' has no attribute 'build_host'`

- [ ] **Step 3: Implement `Host` and `build_host(mw)`**

Take the three widgets out of the old layout with `removeWidget`, delete the old layout via `QWidget().setLayout(old)` (Qt's idiom to detach a layout), build the new one. Point `mw.mainLayout` at the Decks page's layout afterwards (a few add-ons reference it). Each page is a `QWidget` with a zero-margin `QVBoxLayout` holding exactly one child; `set_content` removes and re-parents the old child to `None` only when it is a placeholder (never delete a Browse instance here; Anki owns it).

- [ ] **Step 4: Run to verify it passes**

Expected: all checks pass, including Task 1's.

- [ ] **Step 5: Commit (when asked)**

```bash
git add klausmate/single_window.py tests/test_single_window.py
git commit -m "Single window: host layout with Decks and Browse pages"
```

---

### Task 3: Construction-time shims, registry creators, and the live gate

**Files:**
- Modify: `klausmate/single_window.py`, `klausmate/__init__.py` (a minimal setup block: build the host and register the creators when the flag is on; grown in Task 8)
- Test: `tests/test_single_window.py`

**Interfaces:**
- Consumes: `preflight`, `Host`.
- Produces:
  - `class _Shim(QMainWindow)` with class attribute `target: QWidget | None`; `__init__(self, parent=None, flags=None)` calls `QMainWindow.__init__(self, _Shim.target)`, then `self.setWindowFlags(Qt.WindowType.Widget)`, then `_Shim.target.layout().addWidget(self)`. Raises `EmbedError("no target")` when `target` is `None`.
  - `class EmbedError(Exception)`.
  - `hosted(target: QWidget)` — a context manager setting `_Shim.target` for the duration and clearing it after, also on exception.
  - `make_addcards_class(base) -> type` — returns `type("EmbeddedAddCards", (base, _Shim), {})`; `make_editcurrent_class(base)` likewise. Built at `register` time from the real `aqt.addcards.AddCards` / `aqt.editcurrent.EditCurrent`.
  - `make_browser(mw, card=None, search=None)` — preflight; then, inside `hosted(_state.host.pages["browse"])`, swap `aqt.browser.browser.QMainWindow = _Shim`, construct `Browser(mw, card=card, search=search)`, restore the name in `finally`. On `EmbedError` or any exception before construction returns: `disable(reason)` and construct Anki's own class with the original name in place (a stock window).
  - `make_addcards(mw)` / `make_editcurrent(mw)` — preflight; inside `hosted(<add dock content> / <fresh edit dock content>)` construct the embedded class; same fallback to the plain class.
  - `register(mw) -> None` — `aqt.dialogs.register_dialog("Browser", make_browser)`, `("AddCards", make_addcards)`, `("EditCurrent", make_editcurrent)`; records the originals in `_state.original_creators` so `disable` can restore them.
  - `_state` gains `mw`, `original_creators: dict`, `disabled: str | None`.
  - `disable(reason)` (full behaviour in Task 8; here: set `_state.disabled`, restore the original creators, print).

- [ ] **Step 1: Write the failing tests**

```python
section("shims")
mwq = QtWidgets.QMainWindow(); mwq.show()
page = QtWidgets.QWidget(); QtWidgets.QVBoxLayout(page); mwq.setCentralWidget(page); page.show()

class AddLike(QtWidgets.QMainWindow):                # super().__init__ style (AddCards, EditCurrent)
    def __init__(self, mw):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.child = QtWidgets.QWidget(self); self.setCentralWidget(self.child); self.show()
Emb = sw.make_addcards_class(AddLike)
with sw.hosted(page):
    a = Emb(None)
check("Add-style window is born a child of the page", a.parent() is page and not a.isWindow())
check("a widget created inside it has the main window as top-level", a.child.window() is mwq)
check("it is still an instance of the original class", isinstance(a, AddLike))
check("hosted() clears the target afterwards", sw._Shim.target is None)

fake = types.ModuleType("fake_browser"); fake.QMainWindow = QtWidgets.QMainWindow; fake.Qt = QtCore.Qt; fake.QWidget = QtWidgets.QWidget
exec("class Browser(QMainWindow):\n"
     "    def __init__(self, mw, card=None, search=None):\n"
     "        QMainWindow.__init__(self, None, Qt.WindowType.Window)\n"
     "        self.table = self.sidebar = self.editor = object(); self.form = None\n"
     "        self.child = QWidget(self); self.setCentralWidget(self.child); self.show()\n", fake.__dict__)
sys.modules["aqt.browser.browser"] = fake                     # what make_browser imports
sw._state.mw = mwq; sw._state.host = sw.build_host(fake_mw()); sw._state.host.pages["browse"].show()
b = sw.make_browser(mwq)
check("Browse is born a child of the Browse page", b.parent() is sw._state.host.pages["browse"] and not b.isWindow())
check("its child has the host's main window as top-level", b.child.window() is sw._state.host.pages["browse"].window())
check("the module's QMainWindow name is restored", fake.QMainWindow is QtWidgets.QMainWindow)
exec("class Browser(QMainWindow):\n"
     "    def __init__(self, mw, card=None, search=None): raise RuntimeError('boom')\n", fake.__dict__)
try: sw.make_browser(mwq); raised = False
except RuntimeError: raised = True
check("a raising constructor still restores the name", raised and fake.QMainWindow is QtWidgets.QMainWindow)

section("preflight fallback")
exec("class Browser(QMainWindow):\n"
     "    def __init__(self, mw, card=None, search=None):\n"
     "        QMainWindow.__init__(self, None, Qt.WindowType.Window); self.show()\n", fake.__dict__)   # no table/sidebar/editor
sw._state.disabled = None
b2 = sw.make_browser(mwq)
check("missing attributes: Anki's own top-level window comes back and the session is disabled",
      b2.isWindow() and sw._state.disabled is not None and "table" in sw._state.disabled)
d = QtWidgets.QDockWidget("x", b); b.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, d)
b.restoreGeometry(b.saveGeometry())
check("child main window accepts a dock and survives restoreGeometry", d.parent() is b and b.parent() is sw._state.host.pages["browse"])

section("registry")
opened = {}
sys.modules["aqt"].dialogs = types.SimpleNamespace(register_dialog=lambda name, creator, instance=None: opened.__setitem__(name, creator),
                                                  _dialogs={"Browser": [object(), None], "AddCards": [object(), None], "EditCurrent": [object(), None]})
sys.modules["aqt.addcards"] = types.SimpleNamespace(AddCards=AddLike); sys.modules["aqt.editcurrent"] = types.SimpleNamespace(EditCurrent=AddLike)
sw.register(mwq)
check("three creators registered", set(opened) == {"Browser", "AddCards", "EditCurrent"})
```

(Preflight on the fake `Browser` above checks the attributes after construction, since the fake has no class-level ones; `make_browser` therefore preflights the constructed instance and, on a miss, closes it, disables, and constructs the plain class.)

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL with `AttributeError: … no attribute 'make_addcards_class'`

- [ ] **Step 3: Implement**

`hosted` is `contextlib.contextmanager`. `make_browser` imports `aqt.browser.browser` lazily (so the test's fake module is what it sees), swaps `mod.QMainWindow`, constructs inside `try/finally`. The Add dock and Edit dock content widgets come from Task 6's `make_add_dock`; until Task 6 lands, `make_addcards` targets a placeholder dock created here (`_ensure_add_dock(mw)`), which Task 6 replaces.

- [ ] **Step 4: Run to verify it passes**

Expected: all checks pass.

- [ ] **Step 5: Wire the minimum into `__init__.py` and commit (when asked)**

Add, after the `_addons_menu.setup()` block, a guarded block that calls `_single_window.setup()`; for this task `setup()` only does: read the flag; on `main_window_did_init`, `build_host(mw)`, `_ensure_add_dock(mw)`, `register(mw)`. Nothing else yet.

```bash
git add klausmate/single_window.py klausmate/__init__.py tests/test_single_window.py
git commit -m "Single window: Browse, Add and Edit Current are built inside the main window"
```

- [ ] **Step 6: LIVE GATE (needs Pouya).** Restart Anki. Press `a`: the Add editor must render inside the right dock, with fields visible and typeable. Press `b`: Browse renders inside the main window (unstyled, no menus yet) with its editor pane showing a note's fields. Expected: both editors render. If either webview is black, STOP the plan here, set `single_window` to `false` in the report, and record the result on the spec; the remaining tasks are not built.

### Task 4: Menu swap and Browse shortcut scoping

**Files:**
- Modify: `klausmate/addons_menu.py` (extract `place_before_help(bar, menu, help_menu) -> None` from `_consolidate`, keep behaviour; `_consolidate` skips any action in `getattr(window, "_klausmate_keep_on_bar", set())` so the watcher never sweeps Browse's menus under Add-ons), `klausmate/single_window.py`
- Test: `tests/test_addons_menu.py` (one check that `place_before_help` exists; one that installs the watcher via `install`, adds a menu whose action is in `win._klausmate_keep_on_bar`, processes events twice, and checks it stayed on the bar), `tests/test_single_window.py`

**Interfaces:**
- Consumes: `BROWSE_MENUS`, `_state`.
- Produces:
  - `addons_menu.place_before_help(bar: QMenuBar, menu: QMenu, help_menu: QMenu | None) -> None`.
  - `browse_menus(browser) -> list[QMenu]` — the `BROWSE_MENUS` on `browser.form` that exist, plus `browser._klausmate_addons_menu` if present.
  - `menus_in(mw, browser) -> None` — adds each menu's `menuAction()` to `mw._klausmate_keep_on_bar` first, then inserts each before `mw.form.menuHelp`; retitles Browse's own Add-ons menu to "Browse Add-ons" while it is in the host bar (ruling: two menus titled Add-ons on one bar is confusing; restore the title in `menus_out`); sets `_state.menus_in = True`; no-op if already in.
  - `menus_out(mw) -> None` — removes those menu actions from `mw.menuBar()`; `_state.menus_in = False`.

- [ ] **Step 1: Write the failing tests**

```python
section("menu swap")
mw2 = QtWidgets.QMainWindow(); bar = mw2.menuBar()
mw2.form = types.SimpleNamespace(menuHelp=bar.addMenu("Help"))
bar.insertMenu(mw2.form.menuHelp.menuAction(), QtWidgets.QMenu("Tools", mw2))  # Tools before Help
br = QtWidgets.QMainWindow(); brf = types.SimpleNamespace()
for n, t in (("menuEdit", "Edit"), ("menu_Notes", "Notes"), ("menuJump", "Go")):
    setattr(brf, n, br.menuBar().addMenu(t))
br.form = brf
fired = []; act = brf.menu_Notes.addAction("Forget"); act.setShortcut("Ctrl+Alt+N"); act.triggered.connect(lambda: fired.append(1))
sw.menus_in(mw2, br)
titles = [a.text() for a in bar.actions()]
check("Browse's menus sit before Help in the host bar", titles == ["Tools", "Edit", "Notes", "Go", "Help"], str(titles))
sw.menus_in(mw2, br)
check("twice is a no-op", [a.text() for a in bar.actions()] == titles)
sw.menus_out(mw2)
check("out removes them", [a.text() for a in bar.actions()] == ["Tools", "Help"])
brf.menuJump = None; br._klausmate_addons_menu = QtWidgets.QMenu("Add-ons", br)
sw.menus_in(mw2, br)
check("Browse's Add-ons menu is retitled while in the host bar", "Browse Add-ons" in [a.text() for a in bar.actions()])
sw.menus_out(mw2)
check("…and gets its title back", br._klausmate_addons_menu.title() == "Add-ons")
```

For the shortcut scoping check, build a real embedded browser in a host (`fake_mw()` + `build_host` + `embed`), show `mw`, then:

```python
mw3 = fake_mw(); mw3.form.menuHelp = mw3.menuBar().addMenu("Help"); host3 = sw.build_host(mw3)
br3 = FakeBrowser(); hit = []
a = br3.menuBar().actions()[0].menu().addAction("Forget"); a.setShortcut("Ctrl+Alt+N"); a.triggered.connect(lambda: hit.append(1))
sw.embed("browser", br3, host3.pages["browse"], on_destroyed=lambda: None); br3.show(); mw3.show(); QtWidgets.QApplication.setActiveWindow(mw3); app.processEvents()
def press():
    QtTest.QTest.keyClick(mw3, QtCore.Qt.Key.Key_N, QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.AltModifier); app.processEvents()
host3.switch("decks"); sw.menus_out(mw3); press()
check("Browse action shortcut is silent on the Decks tab", hit == [])
host3.switch("browse"); sw.menus_in(mw3, br3); press()
check("…and fires on the Browse tab", hit == [1])
```

(`from PyQt6 import QtTest`.) If the offscreen platform does not deliver `keyClick` to shortcuts, replace `press()` with `QtWidgets.QApplication.sendEvent(mw3, QtGui.QKeyEvent(...))` for both `ShortcutOverride` and `KeyPress`; the assertions stay.

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL with `AttributeError: … no attribute 'menus_in'`

- [ ] **Step 3: Implement**

`menus_in` uses `place_before_help` per menu in `BROWSE_MENUS` order. `menus_out` calls `bar.removeAction(menu.menuAction())` for each recorded menu (keep the list on `_state.moved_menus`).

- [ ] **Step 4: Run to verify it passes**

Expected: all checks pass; `tests/test_addons_menu.py` still passes.

- [ ] **Step 5: Commit (when asked)**

```bash
git add klausmate/addons_menu.py klausmate/single_window.py tests/test_addons_menu.py tests/test_single_window.py
git commit -m "Single window: Browse menus swap into the host bar per tab"
```

---

### Task 5: `host_keys.py` — state shortcuts per tab and the dock override

**Files:**
- Create: `klausmate/host_keys.py`
- Test: `tests/test_host_keys.py`

**Interfaces:**
- Consumes: nothing from `single_window` (it receives callables).
- Produces:
  - `normalize(key: str | Qt.Key) -> str` — `" "` maps to `"Space"`; a `Qt.Key` member goes through `QKeySequence(int(key))`; a string through `QKeySequence(key)`; both `.toString(QKeySequence.SequenceFormat.PortableText)`.
  - `class Recorder`: `keys: set[str]` (normalized), `suspended: bool`; `record(state: str, shortcuts: list) -> None` (called from the hook; stores the keys); `suspend(mw) -> None` (`setEnabled(False)` on every item of `mw.stateShortcuts`, `suspended = True`); `resume(mw) -> None` (`setEnabled(True)` on every item, `suspended = False`); `apply(mw) -> None` (re-applies the current suspended flag to `mw.stateShortcuts`; called from `state_did_change`, because a state change while the Browse tab is active installs fresh, enabled shortcuts). Ruling, recorded in the spec: not `clearStateShortcuts`/`setStateShortcuts`, because `setStateShortcuts` re-fires `state_shortcuts_will_change` and any add-on appending there would append again on every resume, and duplicate keys make Qt fire neither.
  - `event_key(event: QKeyEvent) -> str` — normalized text of `event.key()` plus modifiers (`QKeySequence(event.keyCombination()).toString(PortableText)`).
  - `class OverrideFilter(QObject)`: `__init__(recorder, focus_in_dock: Callable[[], bool])`; `eventFilter` accepts `QEvent.Type.ShortcutOverride` and returns `True` when `not recorder.suspended and focus_in_dock() and event_key(ev) in recorder.keys`.
  - `setup(mw, focus_in_dock) -> Recorder` — appends `recorder.record` to `gui_hooks.state_shortcuts_will_change`, appends `lambda new, old: recorder.apply(mw)` to `gui_hooks.state_did_change`, installs the filter on `QApplication.instance()`.

- [ ] **Step 1: Write the failing tests**

```python
section("normalize")
check("space", hk.normalize(" ") == "Space")
check("letters and combos", hk.normalize("e") == "E" and hk.normalize("Ctrl+Alt+N") == "Ctrl+Alt+N")
check("Qt.Key members", hk.normalize(QtCore.Qt.Key.Key_Return) == "Return" and hk.normalize(QtCore.Qt.Key.Key_F5) == "F5")

section("recorder")
win = QtWidgets.QWidget()
mw = types.SimpleNamespace(stateShortcuts=[QtGui.QShortcut(QtGui.QKeySequence("e"), win), QtGui.QShortcut(QtGui.QKeySequence(" "), win)])
r = hk.Recorder(); r.record("review", [("e", lambda: None), (" ", lambda: None), (QtCore.Qt.Key.Key_Return, lambda: None)])
check("keys are normalized", r.keys == {"E", "Space", "Return"})
r.suspend(mw)
check("suspend disables every state shortcut", r.suspended and not any(s.isEnabled() for s in mw.stateShortcuts))
mw.stateShortcuts = [QtGui.QShortcut(QtGui.QKeySequence("o"), win)]   # a state change installed fresh ones
r.apply(mw)
check("apply re-disables fresh shortcuts while suspended", not mw.stateShortcuts[0].isEnabled())
r.resume(mw)
check("resume enables them", not r.suspended and mw.stateShortcuts[0].isEnabled())
r.record("overview", [("o", lambda: None)])
check("a new state replaces the record", r.keys == {"O"})

section("override filter")
in_dock = [True]
f = hk.OverrideFilter(r, lambda: in_dock[0]); r.record("review", [(" ", lambda: None)])
ev = QtGui.QKeyEvent(QtCore.QEvent.Type.ShortcutOverride, QtCore.Qt.Key.Key_Space, QtCore.Qt.KeyboardModifier.NoModifier, " ")
check("space in dock is overridden", f.eventFilter(None, ev) is True and ev.isAccepted())
ev2 = QtGui.QKeyEvent(QtCore.QEvent.Type.ShortcutOverride, QtCore.Qt.Key.Key_X, QtCore.Qt.KeyboardModifier.NoModifier, "x")
check("a key not in the state list passes", f.eventFilter(None, ev2) is False)
in_dock[0] = False
check("outside the dock nothing is overridden", f.eventFilter(None, ev) is False)
r.suspended = True; in_dock[0] = True
check("suspended recorder overrides nothing", f.eventFilter(None, ev) is False)
```

End-to-end: a `QShortcut(" ", win)` on a shown window with a `QLineEdit` inside a "dock" widget focused; with the filter installed on the app and `focus_in_dock` true, `QTest.keyClick(edit, Qt.Key_Space)` types a space into the edit and the shortcut does not fire; with `focus_in_dock` false, the shortcut fires.

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL with `ModuleNotFoundError: klausmate.host_keys`

- [ ] **Step 3: Implement `host_keys.py`**

Module docstring explains the two mechanisms (clear/restore on tab switch, override in the dock) and why (window-scoped shortcuts, Qt's ambiguity rule).

- [ ] **Step 4: Run to verify it passes**

Expected: all checks pass.

- [ ] **Step 5: Commit (when asked)**

```bash
git add klausmate/host_keys.py tests/test_host_keys.py
git commit -m "Single window: state shortcuts per tab, dock keys type instead of answering"
```

---

### Task 6: Navigation, refresh, Escape, Add's Close

**Files:**
- Modify: `klausmate/single_window.py`
- Test: `tests/test_single_window.py`

**Interfaces:**
- Consumes: `Host`, `embed`, `menus_in/out`, `host_keys.Recorder`.
- Produces (aqt glue, all guarded):
  - `_on_browser_will_show(browser)` — post-construction only (the window is already a child, Task 3): if `browser.parent()` is the Browse page, hide its menu bar, store `_state.browser`, install `_EscapeFilter`, connect `destroyed` → `_forget_browser()` (placeholder, `menus_out`, `_state.browser = None`, resume keys if on Decks). A Browse that is a top-level (fallback) is left alone.
  - `_on_add_cards_did_init(addcards)` — post-construction only: if hosted, hide its menu bar, reconnect `addcards.closeButton.clicked` to `hide_dock`, connect `destroyed` → dock placeholder.
  - `_on_editor_did_init(editor)` — when `editor.editorMode.name == "EDIT_CURRENT"` and the parent window is hosted in the Edit dock: `mw.tabifyDockWidget(add_dock, edit_dock)`, raise, install `_CloseFilter` on the instance. Anki's `EditCurrent.closeEvent` runs `cleanup()` (which marks it closed in the dialog registry) and lets Qt hide the widget; it never deletes it, so `destroyed` alone would leave a hidden orphan and the next `e` would create a second one. `_CloseFilter` sees `QEvent.Type.Close`, and a tick later (`singleShot(0)`) removes the Edit dock, raises Add, and `deleteLater()`s the orphan. `on_destroyed` does the same removal if Anki's close-all deletes it first.
  - `_on_dialog_opened(dm, name, instance)` — `"Browser"` → `host.switch("browse")`; `"AddCards"` → `show_dock("add")`; `"EditCurrent"` → `show_dock("edit")`.
  - `_on_state_did_change(new, old)` — `host.switch("decks")`.
  - `_on_tab_switch(new, old)` — the host listener: `menus_in/out`, `recorder.suspend/resume`, `_push_active_links()`.
  - `_on_op_executed(changes, handler)` — if `host.tab == "browse"` and `_state.browser`: `browser.table.redraw_cells()`, `browser.sidebar.refresh_if_needed()`.
  - `_on_focus_did_change(new, old)` — same when `new` is inside the Browse page.
  - `class _EscapeFilter(QObject)` — installed on the embedded Browse; swallows `KeyPress` Escape.
  - `focus_in_dock() -> bool` — `QApplication.focusWidget()` is a descendant of any dock in `_state.docks`.
  - `make_add_dock(mw) -> QDockWidget` — title "Add", a content widget with a zero-margin `QVBoxLayout` (the shim's target; a placeholder label sits in it until Add is built), features closable and movable, added to the right area hidden, stored as `_state.docks["add"]`. Closing it via its title bar just hides it. Replaces Task 3's `_ensure_add_dock`.
  - `_new_edit_dock(mw) -> QDockWidget` — title "Edit", same shape, stored as `_state.docks["edit"]`; the shim target for Edit Current.
  - `show_dock(name)`, `hide_dock()`, `toggle_dock()` — as described in Step 3.
  - `_push_active_links()` — `mw.toolbarWeb.eval(active_link_js(host.tab, dock_shown()))`.

- [ ] **Step 1: Write the failing tests**

Use fakes: `fake_mw()` extended with `toolbarWeb.eval = evals.append`, `stateShortcuts=[]`, `clearStateShortcuts`, `setStateShortcuts`, `addDockWidget`, `tabifyDockWidget` (real `QMainWindow` methods), `form.menuHelp`. Set `sw._state.mw = mw`, `sw._state.host = sw.build_host(mw)`, `sw.make_add_dock(mw)`, and `sw._state.active = True`. Then:

```python
section("navigation")
with sw.hosted(sw._state.host.pages["browse"]):
    b = sw.make_addcards_class(FakeBrowser)(None)      # any hosted main window will do here
sw._on_browser_will_show(b)
check("a hosted Browse is recorded and its menu bar hidden", sw._state.browser is b and b.menuBar().isHidden())
sw._on_dialog_opened(None, "Browser", b)
check("open switches the tab and moves menus in", sw._state.host.tab == "browse" and sw._state.menus_in)
sw._on_state_did_change("deckBrowser", "review")
check("a main-state change switches back and moves menus out", sw._state.host.tab == "decks" and not sw._state.menus_in)
sw._state.host.switch("browse")
esc = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)
closed = []; b.close = lambda: closed.append(1) or True
QtWidgets.QApplication.sendEvent(b, esc)
check("Escape in Browse is swallowed", closed == [] and esc.isAccepted())
redrawn = []; b.table = types.SimpleNamespace(redraw_cells=lambda: redrawn.append("t")); b.sidebar = types.SimpleNamespace(refresh_if_needed=lambda: redrawn.append("s"))
sw._on_op_executed(object(), None)
check("an op on the Browse tab redraws table and sidebar", redrawn == ["t", "s"])
sw._state.host.switch("decks"); redrawn.clear(); sw._on_op_executed(object(), None)
check("…not on the Decks tab", redrawn == [])
b.deleteLater(); app.processEvents(); app.processEvents()
check("destroyed Browse leaves a placeholder and no menus", isinstance(sw._state.host.content("browse"), QtWidgets.QLabel) and sw._state.browser is None and not sw._state.menus_in)

section("add dock")
class FakeAdd(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.closeButton = QtWidgets.QPushButton("Close", self); self.closeButton.clicked.connect(self.close); self.editor = object()
with sw.hosted(sw._state.docks["add"].widget()):
    a = sw.make_addcards_class(FakeAdd)(None)
sw._on_add_cards_did_init(a); sw._on_dialog_opened(None, "AddCards", a)
check("a hosted Add sits in the dock and the dock shows", not a.isWindow() and sw._state.docks["add"].isVisible())
a.closeButton.click(); app.processEvents()
check("Close hides the dock and keeps the instance", not sw._state.docks["add"].isVisible() and a.parent() is not None and not a.isWindow())
sw.show_dock("add")
check("focus_in_dock sees a focused child of the dock", (a.closeButton.setFocus(), app.processEvents(), sw.focus_in_dock())[-1] is True)

section("edit current")
class FakeEditCurrent(QtWidgets.QMainWindow):
    def __init__(self): super().__init__(None, QtCore.Qt.WindowType.Window); self.editor = object()
with sw.hosted(sw._new_edit_dock(mw).widget()):      # construct through the shim directly; the creator needs aqt
    ec = sw.make_editcurrent_class(FakeEditCurrent)(None)
ed = types.SimpleNamespace(editorMode=types.SimpleNamespace(name="EDIT_CURRENT"), parentWindow=ec)
sw._on_editor_did_init(ed); sw._on_dialog_opened(None, "EditCurrent", ec)
check("Edit embeds into its own dock, tabbed with Add and raised", "edit" in sw._state.docks and not ec.isWindow() and sw._state.docks["edit"].isVisible())
QtWidgets.QApplication.sendEvent(ec, QtCore.QEvent(QtCore.QEvent.Type.Close)); app.processEvents(); app.processEvents(); app.processEvents()
check("Anki-style close removes the Edit dock and deletes the orphan", "edit" not in sw._state.docks)
```

Also: "open from add-on switches tab": call `sw._on_dialog_opened(None, "Browser", b2)` while `a.closeButton` has focus; expect `host.tab == "browse"`.

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL with `AttributeError: … no attribute '_on_browser_will_show'`

- [ ] **Step 3: Implement**

`show_dock(name)`: `dock.show()`, `dock.raise_()`; for `"add"` with no instance, `aqt.dialogs.open("AddCards", mw)` (guarded import; in tests `aqt.dialogs` comes from the stubs and is not asserted). `hide_dock()` hides every dock in `_state.docks`. `toggle_dock()`: hide if any visible, else `show_dock(_state.last_dock or "add")`. Reconnect Add's Close: `addcards.closeButton.clicked.disconnect()` then `.connect(lambda *_: hide_dock())`.

- [ ] **Step 4: Run to verify it passes**

Expected: all checks pass.

- [ ] **Step 5: Commit (when asked)**

```bash
git add klausmate/single_window.py tests/test_single_window.py
git commit -m "Single window: navigation, Browse refresh, Escape, Add's Close hides the dock"
```

---

### Task 7: Right dock area, PDF dock host, dock state, and the bottom-bar toggles

**Files:**
- Modify: `klausmate/single_window.py`, `klausmate/__init__.py:1419` (the `parent_window` used for `PdfDock` and `_klausmate_pdf_container`), `klausmate/bottom_row.py`, `klausmate/status_bar.py` (`_add_toggles`, `install_browser`)
- Test: `tests/test_single_window.py`, `tests/test_bottom_row.py`, `tests/test_status_bar.py`, `tests/test_bridge_reentrancy.py` (no new handler; the audit covers the new branch in `bottom_row._on_js_message`)

**Interfaces:**
- Consumes: `_state`, `_mw`, `make_add_dock`, `show_dock/hide_dock/toggle_dock` (Task 6).
- Produces:
  - `host_for(window) -> QWidget` — `aqt.mw` when `_state.active` and `type(window).__name__ in ("Browser", "AddCards", "EditCurrent")`, else `window`.
  - `register_dock(dock: QDockWidget, name: str) -> None` — `mw.addDockWidget(Right, dock)`, `mw.tabifyDockWidget(_state.docks["add"], dock)` when the Add dock exists, records in `_state.docks`; hides it.
  - `save_dock_state(mw)` / `restore_dock_state(mw)` — `mw.saveState()` to profile key `"klausmate_host_state"` on `profile_will_close`; restore on `profile_did_open` (there is no profile yet at `main_window_did_init`), then `hide_dock()`.
  - `bottom_row.DOCK_CMD = "klausmate_row_dock"`; `row_html(state, night, dock_toggle: bool = False)` appends a `role=button` div titled "Right sidebar" that `pycmd`s `DOCK_CMD` when `dock_toggle`; `_on_js_message` handles `DOCK_CMD` by `QTimer.singleShot(0, single_window.toggle_dock)`.
  - `status_bar.StatusBar._add_toggles` adds a third `_PaneToggle("right", "dock", visible)` wired to `single_window.toggle_dock` when `single_window.is_active()`; `install_browser` adds a small close `QToolButton` ("Close Browse", `browser.close`) at the row's right end when active.
  - `is_active() -> bool` — `_state.active and _state.disabled is None`.

- [ ] **Step 1: Write the failing tests**

```python
section("docks")
check("host_for maps the three window kinds to mw and leaves others",
      sw.host_for(type("Browser", (), {})()) is sw._mw() and sw.host_for(w := QtWidgets.QWidget()) is w)
d = QtWidgets.QDockWidget("PDF"); sw.register_dock(d, "pdf")
check("registered dock is on mw's right area, tabbed with Add, hidden",
      mw.dockWidgetArea(d) == QtCore.Qt.DockWidgetArea.RightDockWidgetArea and d in mw.tabifiedDockWidgets(sw._state.docks["add"]) and d.isHidden())
sw.toggle_dock(); check("toggle shows", any(x.isVisible() for x in sw._state.docks.values()))
sw.toggle_dock(); check("toggle hides all", not any(x.isVisible() for x in sw._state.docks.values()))

section("bottom row dock toggle")   # in tests/test_bottom_row.py
html = br.row_html(state, False, dock_toggle=True)
check("row has the dock toggle", br.DOCK_CMD in html and "Right sidebar" in html)
check("…only when asked", br.DOCK_CMD not in br.row_html(state, False))
br._on_js_message(False, br.DOCK_CMD, None); app.processEvents(); app.processEvents()
check("dock cmd is deferred and reaches toggle_dock", toggled == [1])   # toggle_dock monkeypatched in the test
```

For `test_status_bar.py`: with `single_window.is_active` patched true, `StatusBar(browser, browser=browser)` has a third toggle whose click calls the patched `toggle_dock`, and `install_browser` adds a button titled "Close Browse" whose click calls `browser.close`.

- [ ] **Step 2: Run to verify they fail**

Expected: `test_single_window.py` FAIL on `host_for`; `test_bottom_row.py` FAIL with `TypeError: row_html() got an unexpected keyword argument 'dock_toggle'`; `test_status_bar.py` FAIL on the missing third toggle.

- [ ] **Step 3: Implement**

In `__init__.py:1419` replace the two uses of `parent_window` (the `_klausmate_pdf_container` lookup/store and `PdfDock(editor, sidebar, parent_window)`) with `host = _single_window.host_for(parent_window)`; after creating the container, `if host is mw: _single_window.register_dock(container, "pdf")`. `_single_window` is imported lazily inside the function, as the other modules do.

- [ ] **Step 4: Run to verify they pass**

Expected: the three test files pass; `tests/test_bridge_reentrancy.py` passes (the new branch defers).

- [ ] **Step 5: Commit (when asked)**

```bash
git add klausmate/single_window.py klausmate/__init__.py klausmate/bottom_row.py klausmate/status_bar.py tests/test_single_window.py tests/test_bottom_row.py tests/test_status_bar.py
git commit -m "Single window: right dock area shared by Add, Edit, and PDF; bottom-bar toggles"
```

---

### Task 8: Toolbar indicator, fallback notice, lifecycle across sync, and `setup()`

**Files:**
- Modify: `klausmate/single_window.py`, `klausmate/__init__.py` (setup block after `_addons_menu.setup()`)
- Test: `tests/test_single_window.py`, `tests/test_tasks.py` (no change expected; the sticky error path is already covered)

**Interfaces:**
- Consumes: everything above; `tasks.begin/end`; `host_keys.setup`.
- Produces:
  - `_on_toolbar_content(web_content, context)` — when `type(context).__name__ == "TopToolbar"` and `is_active()`: `web_content.head += "<style>" + TOOLBAR_CSS + "</style>"`.
  - `_on_toolbar_redraw(toolbar)` — `_push_active_links()`.
  - `disable(reason: str) -> None` — `_state.disabled = reason`; restores Anki's original creators in the dialog registry (Task 3's `_state.original_creators`); `tasks.begin("single_window", "Single window")` then `tasks.end("single_window", f"Single window unavailable: {reason}", error=True)`; `mw.toolbarWeb.setToolTip(...)` once; menus out; keys resumed. Windows already hosted stay hosted until Anki closes them; new ones are stock.
  - `setup() -> None` — reads `enabled(_config())`; if false, returns. Otherwise on `main_window_did_init`: `build_host`, `make_add_dock`, `register(mw)`, `hide_dock`, `host_keys.setup(mw, focus_in_dock)`, listeners, and the hook registrations: `browser_will_show`, `add_cards_did_init`, `editor_did_init`, `dialog_manager_did_open_dialog`, `state_did_change`, `operation_did_execute`, `focus_did_change`, `webview_will_set_content`, `top_toolbar_did_redraw`, `profile_did_open` (restore dock state, then hide), `profile_will_close` (save). Sets `_state.active = True`.

- [ ] **Step 1: Write the failing tests**

```python
section("toolbar indicator")
wc = types.SimpleNamespace(head="", body=""); sw._on_toolbar_content(wc, type("TopToolbar", (), {})())
check("toolbar gets the indicator css when active", "klaus-active" in wc.head)
evals.clear(); sw._on_toolbar_redraw(None)
check("redraw pushes the active-link js", evals and "klaus-active" in evals[-1])

section("fallback")
tasks.clear(); evals.clear()
sw.disable("preflight: table")
check("disabled records a sticky error task", any(t.error and "Single window unavailable" in t.message for t in tasks.snapshot()))
check("…and is_active is false", sw.is_active() is False)
b4 = FakeBrowser(); sw._on_browser_will_show(b4)
check("after disable, a top-level Browse is left alone", b4.isWindow() and sw._state.browser is not b4)

section("destroyed while active")   # Review Focus 1
```

The last section: reset `_state.disabled = None`; embed a Browse, switch to it (menus in, keys suspended via a recorder fake counting calls); `deleteLater` it; expect placeholder, `menus_in` false, recorder resumed exactly once.

`setup()` check: with `sys.modules["klausmate"].get_config = lambda: {"single_window": False}`, `sw.setup()` registers nothing on a stub `gui_hooks` (count hook lengths before and after).

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL with `AttributeError: … no attribute '_on_toolbar_content'`

- [ ] **Step 3: Implement, then wire in `__init__.py`**

Add after the `_addons_menu.setup()` block, same shape:

```python
try:
    from . import single_window as _single_window
    _single_window.setup()
except Exception as exc:  # noqa: BLE001
    print(f"[klausmate] single window setup failed: {exc}")
```

- [ ] **Step 4: Run to verify it passes, then the whole suite**

Run every `tests/test_*.py` in a loop with the `perl` alarm; also `node tests/dashboard_js_dom_test.js`.
Expected: everything passes except `tests/test_top_bar.py` and one `test_dialog_logic.py` check, both already failing at HEAD from the other session's logo work. Name any other failure in the report.

- [ ] **Step 5: Commit (when asked)**

```bash
git add klausmate/single_window.py klausmate/__init__.py tests/test_single_window.py
git commit -m "Single window: toolbar indicator, fallback notice, lifecycle, setup"
```

---

### Task 9: Docs

**Files:**
- Modify: `CLAUDE.md` (module bullets for `single_window` and `host_keys`, the touchpoint table's location, the fallback rule; rewrite the "Deleted" paragraph's `single_window.py` sentence and delete "Embedding Anki's windows stays deleted": the module is back on Pouya's 2026-09-30 request with construction-time hosting, and the August re-parenting route is the thing that stays banned, with K-090..K-094 as the reason), `AGENTS.md` (tree and setup lines), `README.md` (one paragraph: tabs, right panel, the `single_window` flag), `docs/superpowers/specs/2026-09-30-single-window-design.md` (a "Rulings during implementation" section listing any ledgered rulings, including: the third toggle in Browse's bar rather than reusing the editor-column toggle; state shortcuts suspended by disabling them rather than clearing and re-setting; Browse's Add-ons menu retitled "Browse Add-ons" while in the host bar; Edit Current's close handled by a close filter because Anki hides rather than deletes it).

- [ ] **Step 1: Write the doc changes**
- [ ] **Step 2: Verify** — `grep -n "single_window" CLAUDE.md AGENTS.md README.md` shows one hit each at least. Expected: three files match.
- [ ] **Step 3: Commit (when asked)**

```bash
git add CLAUDE.md AGENTS.md README.md docs/superpowers/specs/2026-09-30-single-window-design.md
git commit -m "Docs: single window"
```

---

## Manual check after the plan lands (not a task; the user runs it)

Task 3's live gate comes first and is separate: without it nothing past Task 3 is built.

Restart Anki with the flag on: press `b` (Browse tab appears, menus Edit/View/Notes/Cards/Go in the menu bar), `d` (back, menus gone), `a` (right panel with Add), type a space in a field during a review (types), start a sync with Browse showing (tab blanks, comes back on `b`), and check AMBOSS, AnKing, and AnkiHub items under Add-ons on the Browse tab.
