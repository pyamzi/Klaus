"""One window: Decks, Add and Browse as tabs under Anki's toolbar — the
Add tab is Library tree | PDF reader | Add editor (spec
docs/superpowers/specs/2026-10-01-add-tab-design.md) — and Edit Current
in a right dock. Spec of the host:
docs/superpowers/specs/2026-09-30-single-window-design.md.

Anki's Browse, Add and Edit Current windows are built as CHILDREN of the
host from their first line (construction-time shims registered in Anki's
dialog registry) and never moved: the August attempt moved them and
every editor webview went black (K-090..K-094) — a QtWebEngine view
presents through the top-level window it was born under.

Pure builders above the divider; the aqt glue below it.
"""
from __future__ import annotations

import json
from typing import NamedTuple

# Attributes the touchpoints rely on; a missing one means "fall back to
# Anki's own window" before anything is touched.
PREFLIGHT: dict[str, tuple[str, ...]] = {
    "mw": ("web", "bottomWeb", "toolbarWeb", "form", "mainLayout", "stateShortcuts", "clearStateShortcuts",
           "setStateShortcuts", "addDockWidget", "tabifyDockWidget", "menuBar"),
    "browser": ("table", "sidebar", "form", "menuBar", "close", "editor"),
    "addcards": ("editor", "close", "form"),
    "editcurrent": ("editor", "close"),
}
# Browse's own menus, by their names on ``browser.form`` (browser.ui), in
# bar order. Help stays out: the host has its own.
BROWSE_MENUS = ("menuEdit", "menuqt_accel_view", "menu_Notes", "menu_Cards", "menuJump")

TOOLBAR_CSS = """
.hitem.klaus-active { text-decoration: underline; text-underline-offset: 3px; }
"""
TABS = ("decks", "add", "browse")


def preflight(kind: str, obj) -> list[str]:
    """The attributes of ``PREFLIGHT[kind]`` that ``obj`` lacks, in order."""
    return [n for n in PREFLIGHT[kind] if not hasattr(obj, n)]


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("single_window", True))


def active_link_js(tab: str) -> str:
    """Mark the active toolbar link: exactly one of Decks, Add, Browse."""
    return (
        "(function(){var t=%s;['decks','add','browse'].forEach(function(id){"
        "var e=document.getElementById(id);if(e)e.classList.toggle('klaus-active',id===t);});})();"
        % json.dumps(tab)
    )


# ── aqt glue ─────────────────────────────────────────────────────────────

BROWSE_PLACEHOLDER = "Browse is closed. Press B to open it."
ADD_PLACEHOLDER = "Press A to add a note."
SPLITTER_KEY = "klausmate_add_tab"


def placeholder(text: str):
    from aqt.qt import QLabel, Qt

    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setProperty("klaus_placeholder", True)
    return label


def _page():
    from aqt.qt import QVBoxLayout, QWidget

    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    return page


class Host:
    """The stacked Decks / Add / Browse pages under Anki's toolbar.
    ``previous`` is the tab shown before ``tab`` (Close and Escape on the
    Add tab go back there)."""

    def __init__(self, stack, pages: dict) -> None:
        self.stack = stack
        self.pages = pages
        self.tab = "decks"
        self.previous = "decks"
        self.listeners: list = []

    def switch(self, tab: str) -> None:
        if tab == self.tab or tab not in self.pages:
            return
        old, self.tab = self.tab, tab
        self.previous = old
        self.stack.setCurrentWidget(self.pages[tab])
        for fn in list(self.listeners):
            try:
                fn(tab, old)
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] single window tab listener failed: {exc}")

    def content(self, tab: str):
        lay = self.pages[tab].layout()
        item = lay.itemAt(0)
        return item.widget() if item is not None else None

    def set_content(self, tab: str, widget) -> None:
        """Replace the page's single child. ``None`` restores a placeholder.
        Only a placeholder is ever removed here: Anki owns its windows."""
        lay = self.pages[tab].layout()
        old = self.content(tab)
        if old is not None and old is not widget:
            try:
                is_placeholder = bool(old.property("klaus_placeholder"))
                lay.removeWidget(old)
                if is_placeholder:
                    old.setParent(None)
                    old.deleteLater()
                else:
                    old.hide()
            except RuntimeError:  # Anki already deleted the C++ object
                pass
        if widget is None:
            widget = placeholder(BROWSE_PLACEHOLDER)
        if widget.parent() is not self.pages[tab] or lay.indexOf(widget) < 0:
            lay.addWidget(widget)


def build_host(mw) -> Host:
    """Toolbar above a stack: the Decks page holds whatever Anki's main
    layout held below the toolbar (its own main and bottom webviews, or
    the splitter another add-on wrapped the main webview in: AMBOSS's
    sidepanel.py and AnkiHub's gui/reviewer.py both do that, and both
    find ``mw.web`` through ``mw.mainLayout``); the Add page is empty
    until ``build_add_page`` fills it; the Browse page a placeholder until
    Browse is built inside it. Nothing is detached or deleted: the central
    layout is reused, every item moved, and ``mw.mainLayout`` becomes the
    Decks layout so those add-ons keep finding the webview as a direct
    item."""
    from aqt.qt import QStackedWidget

    central = mw.form.centralwidget
    old = central.layout()
    items = []
    while old.count():
        items.append(old.takeAt(0))
    decks, add, browse = _page(), _page(), _page()
    for item in items:
        w = item.widget()
        if w is mw.toolbarWeb:
            continue
        if w is not None:
            decks.layout().addWidget(w)
        elif item.layout() is not None:
            decks.layout().addLayout(item.layout())
        else:
            decks.layout().addItem(item)
    browse.layout().addWidget(placeholder(BROWSE_PLACEHOLDER))
    stack = QStackedWidget()
    stack.addWidget(decks)
    stack.addWidget(add)
    stack.addWidget(browse)
    old.addWidget(mw.toolbarWeb)
    old.addWidget(stack)
    mw.mainLayout = decks.layout()
    return Host(stack, {"decks": decks, "add": add, "browse": browse})


class AddPage(NamedTuple):
    page: object
    splitter: object
    tree: object
    reader_slot: object
    editor_slot: object
    bar: object


def _slot(name: str):
    from aqt.qt import QVBoxLayout, QWidget

    w = QWidget()
    w.setObjectName(name)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    return w


def build_add_page(page, mw) -> AddPage:
    """Library tree | reader slot | editor slot in a splitter, Klaus's
    status bar (◧ tree, ◨ editor) under it. The editor slot holds the
    placeholder until Anki builds Add inside it; the reader slot is the
    reader's home (``reader_host.set_home`` is the caller's)."""
    from aqt.qt import QSplitter, Qt

    from . import library_tree, status_bar

    tree = library_tree.LibraryTree()
    reader_slot = _slot("klausmate_reader_slot")
    editor_slot = _slot("klausmate_add_editor_slot")
    editor_slot.layout().addWidget(placeholder(ADD_PLACEHOLDER))
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setObjectName("klausmate_add_splitter")
    splitter.setChildrenCollapsible(False)
    for i, w in enumerate((tree, reader_slot, editor_slot)):
        splitter.addWidget(w)
        splitter.setStretchFactor(i, (24, 46, 30)[i])
    page.layout().addWidget(splitter, 1)
    bar = status_bar.install_add_tab(page, tree, editor_slot)
    return AddPage(page, splitter, tree, reader_slot, editor_slot, bar)


# ── construction-time hosting ────────────────────────────────────────────
import contextlib  # noqa: E402
import importlib  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402

from . import settings  # noqa: E402

from aqt.qt import QDockWidget, QMainWindow, Qt  # noqa: E402

_state = types.SimpleNamespace(
    mw=None, active=False, disabled=None, host=None, browser=None, addcards=None,
    editcurrent=None, docks={}, add=None, moved_menus=[], menus_in=False,
    original_creators={}, recorder=None, parked=([], []),
)


class EmbedError(Exception):
    pass


def _mw():
    return _state.mw


def _config() -> dict:
    try:
        return settings.read()
    except Exception:  # noqa: BLE001
        return {}


class _Shim(QMainWindow):
    """Stands in for ``QMainWindow`` during ONE of Anki's constructors so
    the window is a child of ``target`` from its first line: its editor
    webview is then born under the main window (never moved, K-090..K-094).
    Reached two ways — after the Anki class in a subclass's method
    resolution order (``super().__init__`` in AddCards / EditCurrent), or
    as the module's ``QMainWindow`` name for Browse's explicit call."""

    target = None

    def __init__(self, parent=None, flags=None) -> None:
        target = _Shim.target
        if target is None:
            raise EmbedError("no host target")
        QMainWindow.__init__(self, target)
        self.setWindowFlags(Qt.WindowType.Widget)  # Qt's nested-main-window recipe
        target.layout().addWidget(self)


@contextlib.contextmanager
def hosted(target):
    _Shim.target = target
    try:
        yield
    finally:
        _Shim.target = None


_EMBEDDED: dict = {}


def embedded_class(base) -> type:
    """``base`` with ``_Shim`` after it in the method resolution order, so
    its ``super().__init__(None, Window)`` lands in the shim. Cached.

    Browse's Cmd+W (``actionClose``) runs ``_handle_close``, which closes the
    ACTIVE window unless it is Browse; hosted, that is mw. The override sits
    ahead of the base, so ``setupUi`` connects it: mw counts as Browse (Close
    Browse), anything else (a dialog) keeps Anki's handling."""
    cls = _EMBEDDED.get(base)
    if cls is None:
        ns = {}
        if hasattr(base, "_handle_close"):
            def _handle_close(self) -> None:
                from aqt.qt import QApplication

                active = QApplication.activeWindow()
                if active is None or active is self.window():
                    self.close()
                else:
                    base._handle_close(self)

            ns["_handle_close"] = _handle_close
        cls = type(f"Embedded{base.__name__}", (base, _Shim), ns)
        _EMBEDDED[base] = cls
    return cls


# Anki's dialog-registry names Klaus hosts (26.09 registers both the legacy
# and the new Add / Edit Current screens), the preflight kind of each, and
# where it goes.
HOSTED = {
    "Browser": ("browser", "browse"),
    "AddCards": ("addcards", "add"),
    "NewAddCards": ("addcards", "add"),
    "EditCurrent": ("editcurrent", "edit"),
    "NewEditCurrent": ("editcurrent", "edit"),
}


def _dock(mw, name: str, title: str):
    from aqt.qt import QVBoxLayout, QWidget

    dock = QDockWidget(title, mw)
    dock.setObjectName(f"klausmate_{name}_dock")
    dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                     | QDockWidget.DockWidgetFeature.DockWidgetMovable)
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    dock.setWidget(content)
    lay.addWidget(placeholder(""))
    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.hide()
    try:
        dock.visibilityChanged.connect(lambda *_: _push_active_links())
    except Exception:  # noqa: BLE001
        pass
    _state.docks[name] = dock
    return dock


def _drop_placeholders(container) -> None:
    lay = container.layout()
    for i in reversed(range(lay.count())):
        w = lay.itemAt(i).widget()
        if w is not None and w.property("klaus_placeholder"):
            lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()


def _new_edit_dock(mw):
    return _dock(mw, "edit", "Edit")


def disable(reason: str) -> None:
    """Stop hosting for this session: Anki's own creators come back, the
    host bar and keys return to normal, and the notice shows once (a
    toolbar tooltip plus a sticky error line in the task readout).
    Windows already hosted stay hosted until Anki closes them."""
    first = _state.disabled is None
    _state.disabled = reason
    try:
        import aqt

        for name, creator in _state.original_creators.items():
            entry = aqt.dialogs._dialogs.get(name)
            live = entry[1] if entry is not None else None
            aqt.dialogs.register_dialog(name, creator, live)  # Anki's closeAll must still see a live one
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: restoring creators failed: {exc}")
    try:
        if _state.mw is not None:
            menus_out(_state.mw)
            _unpark_host_keys()
            if _state.recorder is not None:
                _state.recorder.resume(_state.mw)
        from . import reader_host

        reader_host.give_back()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: disable cleanup failed: {exc}")
    if first:
        text = f"Single window unavailable: {reason}"
        try:
            from . import tasks

            tasks.begin("single_window", "Single window")
            tasks.end("single_window", text, error=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] single window: notice failed: {exc}")
        try:
            web = getattr(_state.mw, "toolbarWeb", None)
            if web is not None:
                web.setToolTip(text)
        except Exception:  # noqa: BLE001
            pass
    print(f"[klausmate] single window disabled: {reason}")


def _target(where: str, mw):
    if where == "browse":
        return _state.host.pages["browse"]
    if where == "add":
        return _state.add.editor_slot
    return _new_edit_dock(mw).widget()


def _construct(name: str, base, mw, *args, module=None, **kwargs):
    """Build Anki's ``base`` as a child of its target from line one. The
    subclass covers ``super().__init__``; swapping the class's module
    ``QMainWindow`` name during the call covers Browse's explicit
    ``QMainWindow.__init__(self, …)``; whichever the source uses runs the
    shim exactly once, the other is inert."""
    kind, where = HOSTED[name]
    if _state.disabled is not None or _state.host is None:
        return base(mw, *args, **kwargs)
    from aqt.qt import QApplication

    mod = module if module is not None else sys.modules.get(getattr(base, "__module__", ""))
    orig = getattr(mod, "QMainWindow", None) if mod is not None else None
    if orig is not None:
        mod.QMainWindow = _Shim
    # A nested main window's NATIVE menu bar would attach to mw's NSWindow
    # and replace Anki's whole menu bar (macOS); the bar is created inside
    # Anki's constructor, so native bars are off for exactly that call.
    attr = Qt.ApplicationAttribute.AA_DontUseNativeMenuBar
    prev_native = QApplication.testAttribute(attr)
    QApplication.setAttribute(attr, True)
    try:
        with hosted(_target(where, mw)):
            inst = embedded_class(base)(mw, *args, **kwargs)
    finally:
        QApplication.setAttribute(attr, prev_native)
        if orig is not None:
            mod.QMainWindow = orig
    _hide_menu_bar(inst)
    missing = preflight(kind, inst)
    if missing:
        # The window is built and hosted; keep it (never destroy a live Anki
        # window) and stop hosting NEW ones for the session.
        disable(f"{kind} preflight: missing {', '.join(missing)}")
    _drop_placeholders(_target(where, mw) if where != "edit" else _state.docks["edit"].widget())
    return inst


def _hide_menu_bar(win) -> None:
    """Hide a hosted window's own menu bar without ever creating one
    (``menuBar()`` creates; ``menuWidget()`` only reports)."""
    try:
        bar = win.menuWidget()
        if bar is not None:
            bar.setNativeMenuBar(False)
            bar.hide()
    except Exception:  # noqa: BLE001
        pass


def _creator(name: str, base):
    def create(mw, *args, **kwargs):
        return _construct(name, base, mw, *args, **kwargs)

    create.__name__ = f"klausmate_{name}"
    return create


def make_browser(mw, card=None, search=None):
    """Anki's Browse, built as a child of the Browse page (module import
    kept lazy so a test can substitute the module)."""
    mod = importlib.import_module("aqt.browser.browser")
    return _construct("Browser", mod.Browser, mw, card=card, search=search, module=mod)


def register(mw) -> None:
    """Replace every hosted name's creator in Anki's dialog registry (the
    public add-on seam, ``DialogManager.register_dialog``), reading the
    class each name maps to from the registry itself."""
    import aqt

    for name in HOSTED:
        entry = aqt.dialogs._dialogs.get(name)
        if entry is None:
            continue
        base = entry[0]
        _state.original_creators.setdefault(name, base)
        aqt.dialogs.register_dialog(name, _creator(name, base))


# ── Browse's menus in the host bar ───────────────────────────────────────
BROWSE_ADDONS_TITLE = "Browse Add-ons"


def browse_menus(browser) -> list:
    """Browse's own menus that exist, in bar order, plus its consolidated
    Add-ons menu (``addons_menu``) if it has one."""
    form = getattr(browser, "form", None)
    menus = [getattr(form, n) for n in BROWSE_MENUS if getattr(form, n, None) is not None]
    extra = getattr(browser, "_klausmate_addons_menu", None)
    if extra is not None:
        menus.append(extra)
    return menus


def menus_in(mw, browser) -> None:
    """Put Browse's menus before Help in the host bar, exempt from the
    Add-ons watcher. Their shortcuts become active with them: Qt only
    fires a menu action's shortcut while it reaches a visible bar."""
    if _state.menus_in:
        return
    from .addons_menu import TITLE, place_before_help

    bar = mw.menuBar()
    keep = getattr(mw, "_klausmate_keep_on_bar", None)
    if keep is None:
        keep = mw._klausmate_keep_on_bar = set()
    help_menu = getattr(getattr(mw, "form", None), "menuHelp", None)
    moved = []
    for menu in browse_menus(browser):
        if menu.title() == TITLE:
            menu.setTitle(BROWSE_ADDONS_TITLE)
        keep.add(menu.menuAction())
        place_before_help(bar, menu, help_menu)
        moved.append(menu)
    _state.moved_menus = moved
    _state.menus_in = True


def menus_out(mw) -> None:
    if not _state.menus_in:
        return
    from .addons_menu import TITLE

    bar = mw.menuBar()
    keep = getattr(mw, "_klausmate_keep_on_bar", set())
    for menu in _state.moved_menus:
        try:
            bar.removeAction(menu.menuAction())
            keep.discard(menu.menuAction())
            if menu.title() == BROWSE_ADDONS_TITLE:
                menu.setTitle(TITLE)
        except RuntimeError:  # Browse (and its menus) already deleted
            pass
    _state.moved_menus = []
    _state.menus_in = False


# ── navigation, refresh, filters, docks ──────────────────────────────────
from aqt.qt import QEvent, QObject, QTimer  # noqa: E402

ADD_NAMES = ("AddCards", "NewAddCards")
EDIT_NAMES = ("EditCurrent", "NewEditCurrent")
MAIN_STATES = ("deckBrowser", "overview", "review")


def _parent(w):
    """``QObject.parent(w)``, never ``w.parent()``: Image Occlusion
    Enhanced's ``ImgOccEdit`` sets ``self.parent = <window>`` as an
    instance attribute, which shadows the method (a live TypeError in
    ``_on_focus_did_change``, 2026-10-01)."""
    from aqt.qt import QObject

    return QObject.parent(w)


def _hosted_in(widget, container) -> bool:
    try:
        return widget is not None and container is not None and _parent(widget) is container
    except (RuntimeError, TypeError):
        return False


def _inside(widget, ancestor) -> bool:
    try:
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = _parent(w)
    except (RuntimeError, TypeError):
        pass
    return False


def dock_shown() -> bool:
    return any(_alive_visible(d) for d in _state.docks.values())


def _alive_visible(widget) -> bool:
    try:
        return widget.isVisible()
    except RuntimeError:
        return False


def focus_in_editor() -> bool:
    """Focus is inside the Add page's editor slot or the Edit dock: the
    place where a state-shortcut key must type instead of answering."""
    from aqt.qt import QApplication

    fw = QApplication.focusWidget()
    if _state.add is not None and _inside(fw, _state.add.editor_slot):
        return True
    return any(_inside(fw, d) for d in _state.docks.values())


def _push_active_links() -> None:
    try:
        host, mw = _state.host, _state.mw
        web = getattr(mw, "toolbarWeb", None)
        if host is None or web is None:
            return
        web.eval(active_link_js(host.tab))
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window toolbar push failed: {exc}")


def show_dock(name: str) -> None:
    dock = _state.docks.get(name)
    if dock is None:
        return
    dock.show()
    dock.raise_()
    _push_active_links()


def _back() -> None:
    """Close or Escape on the Add tab: the tab shown before it."""
    host = _state.host
    if host is not None and host.tab == "add":
        host.switch(host.previous if host.previous != "add" else "decks")


def hide_dock() -> None:
    for dock in list(_state.docks.values()):
        try:
            dock.hide()
        except RuntimeError:
            pass
    _push_active_links()


class _EscapeFilter(QObject):
    """Anki's Browse closes on Escape; inside the tab that would tear down
    the table and the editor, so Escape does nothing there. On the Add
    tab Escape goes back to the previous tab (``on_escape``)."""

    def __init__(self, on_escape=None) -> None:
        super().__init__()
        self._on_escape = on_escape

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        try:
            if (event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
                    and not event.modifiers()):
                event.accept()
                if self._on_escape is not None:
                    self._on_escape()
                return True
        except Exception:  # noqa: BLE001
            pass
        return False


class _CloseFilter(QObject):
    """Add: a user Close (page button, Cmd+W) goes back to the previous tab
    and keeps the instance; Anki's own teardown (``_close_event_has_cleaned_up``
    already set) passes. Edit Current: Anki hides it on close and never
    deletes it, so a tick later the dock is removed and the orphan reaped
    once the registry shows it closed."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self._kind = kind

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        try:
            if event.type() != QEvent.Type.Close:
                return False
            if self._kind == "add":
                if getattr(obj, "_close_event_has_cleaned_up", False):
                    return False
                event.ignore()
                _back()
                return True
            QTimer.singleShot(0, lambda: _reap_edit(obj))
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] single window close filter failed: {exc}")
        return False


def _registry_instance(names) -> object | None:
    try:
        import aqt

        for n in names:
            entry = aqt.dialogs._dialogs.get(n)
            if entry is not None and entry[1] is not None:
                return entry[1]
    except Exception:  # noqa: BLE001
        pass
    return None


def _reap_edit(inst, attempt: int = 0) -> None:
    """Remove the Edit dock once Anki's async close has marked the dialog
    closed; retry briefly while its note is still saving."""
    if _registry_instance(EDIT_NAMES) is inst and attempt < 25:
        QTimer.singleShot(200, lambda: _reap_edit(inst, attempt + 1))
        return
    dock = _state.docks.pop("edit", None)
    _state.editcurrent = None
    if dock is not None:
        try:
            _state.mw.removeDockWidget(dock)
            dock.deleteLater()  # takes the orphan with it
        except RuntimeError:
            pass
    _push_active_links()


def _forget_browser() -> None:
    """A tick after ``destroyed``: Qt has removed the dead layout item by then."""
    _state.browser = None
    QTimer.singleShot(0, _forget_browser_now)


def _forget_browser_now() -> None:
    try:
        if _state.mw is not None:
            menus_out(_state.mw)
            _unpark_host_keys()
        if _state.host is not None:
            _state.host.set_content("browse", None)
        from . import reader_host

        reader_host.give_back()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: forgetting Browse failed: {exc}")
    _push_active_links()


def _on_add_destroyed() -> None:
    _state.addcards = None
    try:
        from . import reader_host

        reader_host.set_home_editor(None)
    except Exception:  # noqa: BLE001
        pass
    QTimer.singleShot(0, _replace_add_placeholder)


def _replace_add_placeholder() -> None:
    slot = _state.add.editor_slot if _state.add is not None else None
    try:
        if slot is not None and slot.layout().count() == 0:
            slot.layout().addWidget(placeholder(ADD_PLACEHOLDER))
    except RuntimeError:
        pass


def _on_browser_will_show(browser) -> None:
    try:
        if _state.host is None or not _hosted_in(browser, _state.host.pages["browse"]):
            return  # a stock top-level Browse (fallback) is left alone
        _hide_menu_bar(browser)
        _drop_placeholders(_state.host.pages["browse"])
        _state.browser = browser
        # Klaus's refresh must run AFTER Browse's own handler (registered per
        # instance in Browser.setupHooks, so later than Klaus's at init).
        try:
            from aqt import gui_hooks

            for hook, fn in ((gui_hooks.operation_did_execute, _on_op_executed),
                             (gui_hooks.focus_did_change, _on_focus_did_change)):
                try:
                    hook.remove(fn)
                except ValueError:
                    pass
                hook.append(fn)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] single window: hook order failed: {exc}")
        if _state.host.tab == "browse":
            # Rebuilt while its tab already shows (Close Browse, then b):
            # switch() is a no-op then, so the tab work runs here.
            _on_tab_switch("browse", "browse")
        flt = _EscapeFilter()
        browser._klausmate_escape_filter = flt
        browser.installEventFilter(flt)
        browser.destroyed.connect(lambda *_: _forget_browser())
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: Browse hook failed: {exc}")


def _on_add_cards_did_init(addcards) -> None:
    try:
        slot = _state.add.editor_slot if _state.add is not None else None
        if slot is None or not _hosted_in(addcards, slot):
            return
        _hide_menu_bar(addcards)
        _drop_placeholders(slot)
        _state.addcards = addcards
        from . import reader_host

        reader_host.set_home_editor(getattr(addcards, "editor", None))
        flt = _CloseFilter("add")
        addcards._klausmate_close_filter = flt
        addcards.installEventFilter(flt)
        esc = _EscapeFilter(_back)
        addcards._klausmate_escape_filter = esc
        addcards.installEventFilter(esc)
        addcards.destroyed.connect(lambda *_: _on_add_destroyed())
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: Add hook failed: {exc}")


def _on_editor_did_init(editor) -> None:
    try:
        mode = getattr(getattr(editor, "editorMode", None), "name", "")
        win = getattr(editor, "parentWindow", None)
        dock = _state.docks.get("edit")
        if mode != "EDIT_CURRENT" or dock is None or not _hosted_in(win, dock.widget()):
            return
        _hide_menu_bar(win)
        _drop_placeholders(dock.widget())
        _state.editcurrent = win
        flt = _CloseFilter("edit")
        win._klausmate_close_filter = flt
        win.installEventFilter(flt)
        win.destroyed.connect(lambda *_: _reap_edit(None))
        dock.show()
        dock.raise_()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: Edit hook failed: {exc}")


def _on_dialog_opened(dm, name: str, instance) -> None:
    try:
        if _state.host is None:
            return
        if name == "Browser" and instance is _state.browser:
            _state.host.switch("browse")
        elif name in ADD_NAMES and instance is _state.addcards:
            _state.host.switch("add")
        elif name in EDIT_NAMES and instance is _state.editcurrent:
            show_dock("edit")
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: open hook failed: {exc}")


def _on_state_did_change(new_state: str, old_state: str) -> None:
    try:
        if _state.host is not None and new_state in MAIN_STATES:
            _state.host.switch("decks")
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: state hook failed: {exc}")


_MODIFIERS = ("Ctrl+", "Meta+", "Alt+")
TAB_KEYS = {"D", "B", "A"}  # the three tabs: never parked (spec Q21)


def _bare(text: str) -> bool:
    """A key without Ctrl/Cmd/Alt (Shift allowed): fires from a table or
    tree, so it must not reach the main window from the Browse tab."""
    return bool(text) and not any(m in text for m in _MODIFIERS)


def _walk_actions(actions):
    for act in actions:
        menu = act.menu()
        if menu is not None:
            yield from _walk_actions(menu.actions())
        elif not act.isSeparator():
            yield act


def _browse_keys(browser) -> set:
    from aqt.qt import QKeySequence, QShortcut

    fmt = QKeySequence.SequenceFormat.PortableText
    keys = set()
    try:
        for act in _walk_actions([m.menuAction() for m in browse_menus(browser)]):
            for seq in act.shortcuts():
                keys.add(seq.toString(fmt))
        for scut in browser.findChildren(QShortcut):
            keys.add(scut.key().toString(fmt))
    except Exception:  # noqa: BLE001
        pass
    keys.discard("")
    return keys


def _park_host_keys(mw, browser=None) -> None:
    """While the Browse or the Add tab shows: host-bar actions whose key
    Browse also uses (Cmd+Shift+P would switch profiles from inside Browse
    on macOS) or whose key is bare (F, /) lose their shortcut; mw's
    permanent bare-key QShortcuts (d s a b t y…) are disabled — the
    Library tree and Browse's table would fire them. State keys are the
    recorder's. ``browser`` is None on the Add tab."""
    from aqt.qt import QKeySequence, QShortcut

    _unpark_host_keys()  # idempotent: never lose the originals
    fmt = QKeySequence.SequenceFormat.PortableText
    keys = _browse_keys(browser) if browser is not None else set()
    own = [w for w in (browser, _state.add.page if _state.add is not None else None) if w is not None]
    moved = {m.menuAction() for m in _state.moved_menus}
    parked_actions, parked_shortcuts = [], []
    try:
        top = [a for a in mw.menuBar().actions() if a not in moved]
        for act in _walk_actions(top):
            seqs = act.shortcuts()
            texts = [q.toString(fmt) for q in seqs]
            if any((t in keys or _bare(t)) and t.upper() not in TAB_KEYS for t in texts):
                parked_actions.append((act, seqs))
                act.setShortcut(QKeySequence())
        state = set(getattr(mw, "stateShortcuts", None) or [])
        for scut in mw.findChildren(QShortcut):
            if scut in state or any(_inside(scut.parent(), w) for w in own) or any(_inside(scut.parent(), d) for d in _state.docks.values()):
                continue
            text = scut.key().toString(fmt)
            if _bare(text) and text.upper() not in TAB_KEYS and scut.isEnabled():
                parked_shortcuts.append(scut)
                scut.setEnabled(False)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: parking host keys failed: {exc}")
    _state.parked = (parked_actions, parked_shortcuts)


def _unpark_host_keys() -> None:
    actions, shortcuts = getattr(_state, "parked", ([], []))
    for act, seqs in actions:
        try:
            act.setShortcuts(seqs)
        except RuntimeError:
            pass
    for scut in shortcuts:
        try:
            scut.setEnabled(True)
        except RuntimeError:
            pass
    _state.parked = ([], [])


def _on_tab_switch(new: str, old: str) -> None:
    mw, rec = _state.mw, _state.recorder
    try:
        if new == "browse":
            if _state.browser is not None:
                _park_host_keys(mw, _state.browser)
                menus_in(mw, _state.browser)
            if rec is not None:
                rec.suspend(mw)
        elif new == "add":
            menus_out(mw)
            _park_host_keys(mw, None)
            if rec is not None:
                rec.suspend(mw)
            from . import reader_host

            reader_host.reader()  # built on the first show: last session's tabs are visible before any click
        else:
            menus_out(mw)
            _unpark_host_keys()
            if rec is not None:
                rec.resume(mw)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: tab switch failed: {exc}")
    _push_active_links()


def _redraw_browse() -> None:
    b = _state.browser
    if b is None:
        return
    try:
        b.table.redraw_cells()
        b.sidebar.refresh_if_needed()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: Browse redraw failed: {exc}")


def _on_op_executed(changes, handler) -> None:
    if _state.host is not None and _state.host.tab == "browse":
        _redraw_browse()


def _on_focus_did_change(new, old) -> None:
    if _state.host is not None and _inside(new, _state.host.pages["browse"]):
        _redraw_browse()


# ── the right dock area shared with Klaus's own docks ────────────────────


STATE_KEY = "klausmate_host_state"


def save_dock_state(mw) -> None:
    try:
        profile = getattr(getattr(mw, "pm", None), "profile", None)
        if profile is not None:
            profile[STATE_KEY] = bytes(mw.saveState())
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: saving dock state failed: {exc}")


def restore_dock_state(mw) -> None:
    """Dock widths and tab order come back; every dock then hides
    (startup is always Decks with the dock closed)."""
    try:
        from aqt.qt import QByteArray

        profile = getattr(getattr(mw, "pm", None), "profile", None)
        data = profile.get(STATE_KEY) if profile is not None else None
        if data:
            mw.restoreState(QByteArray(data))
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: restoring dock state failed: {exc}")
    hide_dock()


def is_active() -> bool:
    return bool(_state.active) and _state.disabled is None


def _on_toolbar_content(web_content, context) -> None:
    try:
        if type(context).__name__ == "TopToolbar" and is_active():
            web_content.head += "<style>" + TOOLBAR_CSS + "</style>"
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window toolbar css failed: {exc}")


def _on_toolbar_redraw(toolbar) -> None:
    _push_active_links()


def _restore_splitter() -> None:
    try:
        from aqt.utils import restoreSplitter

        if _state.add is not None:
            restoreSplitter(_state.add.splitter, SPLITTER_KEY)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: restoring the Add splitter failed: {exc}")


def _on_profile_open() -> None:
    if _state.mw is not None:
        restore_dock_state(_state.mw)
    _restore_splitter()


def _on_profile_close() -> None:
    try:
        from aqt.utils import saveSplitter

        if _state.add is not None:
            saveSplitter(_state.add.splitter, SPLITTER_KEY)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: saving the Add splitter failed: {exc}")
    if _state.mw is not None:
        save_dock_state(_state.mw)
    try:
        from . import reader_host

        reader_host.release()  # the profile's readers are cleaned up; a cleaned one is never reused
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: releasing the reader failed: {exc}")


def _open_pdf(safe: str) -> None:
    """A click on a PDF row of the Add tab's tree: into the reader (its own
    load path adds the tab and touches last-used)."""
    try:
        from . import reader_host

        rd = reader_host.reader()
        if rd is not None and not rd.is_loaded(safe):
            rd.load_pdf(safe)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] single window: opening {safe!r} failed: {exc}")


def _init_main() -> None:
    """Runs once, after the profile has opened (that is when Anki fires
    ``main_window_did_init``)."""
    try:
        from aqt import gui_hooks, mw

        from . import host_keys

        missing = preflight("mw", mw)
        if missing:
            _state.mw = mw
            disable(f"mw preflight: missing {', '.join(missing)}")
            return
        from . import reader_host

        _state.mw = mw
        _state.host = build_host(mw)
        _state.add = build_add_page(_state.host.pages["add"], mw)
        reader_host.set_home(_state.add.reader_slot)
        _state.add.tree.pdf_clicked.connect(_open_pdf)
        register(mw)
        _state.recorder = host_keys.setup(mw, focus_in_editor)
        _state.host.listeners.append(_on_tab_switch)
        gui_hooks.browser_will_show.append(_on_browser_will_show)
        gui_hooks.add_cards_did_init.append(_on_add_cards_did_init)
        gui_hooks.editor_did_init.append(_on_editor_did_init)
        gui_hooks.dialog_manager_did_open_dialog.append(_on_dialog_opened)
        gui_hooks.state_did_change.append(_on_state_did_change)
        gui_hooks.operation_did_execute.append(_on_op_executed)
        gui_hooks.focus_did_change.append(_on_focus_did_change)
        gui_hooks.webview_will_set_content.append(_on_toolbar_content)
        gui_hooks.top_toolbar_did_redraw.append(_on_toolbar_redraw)
        gui_hooks.profile_did_open.append(_on_profile_open)
        gui_hooks.profile_will_close.append(_on_profile_close)
        _state.active = True
        restore_dock_state(mw)  # the profile is already open here
        _restore_splitter()
        _push_active_links()
    except Exception as exc:  # noqa: BLE001
        disable(f"init: {type(exc).__name__}: {exc}")


def setup() -> None:
    if not enabled(_config()):
        return
    from aqt import gui_hooks

    gui_hooks.main_window_did_init.append(_init_main)
