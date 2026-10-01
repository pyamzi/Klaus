"""Image Occlusion 3/3: "Draw a diagram…" on the occlusion editor's Draw tab.

"Draw a diagram…" opens IOE's own editor (ImgOccEdit) on an 800×600 white
PNG and starts on a third tab, "&Draw": an Excalidraw webview with a Qt
"Use drawing" button. The page answers ``klausexcal:occlude:<b64 JSON>``;
excal_tab.prepare_occlusion writes the PNG and the label-mask SVG
(excal_masks), ImgOccAdd.use_drawing swaps svg-edit onto them and enables
Add, and after IOE adds the notes the scene is saved beside the image as
``<returned media name>.excalidraw``.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_excal_flow.py
"""
from __future__ import annotations

import base64
import copy
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import _Dummy, _permissive_module, check, install, report, section  # noqa: E402

install()
for _name in ("aqt.addcards", "aqt.editcurrent", "aqt.reviewer", "anki.notes",
              "anki.errors", "anki.config"):
    _permissive_module(_name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
from PyQt6 import QtCore, QtGui, QtWidgets, sip  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _qt_getattr(name):
    for module in (QtWidgets, QtCore, QtGui):
        if hasattr(module, name):
            return getattr(module, name)
    if name == "qconnect":
        return lambda signal, callback: signal.connect(callback)
    if name == "sip":
        return sip
    return _Dummy


shim.__getattr__ = _qt_getattr
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["klaus-test"])


# ------------------------------------------------------------ aqt stand-ins

class Hook(list):
    pass


gh = sys.modules["aqt.gui_hooks"]
for _h in ("profile_will_close", "card_will_show", "reviewer_did_show_answer",
           "browser_menus_did_init", "profile_did_open", "editor_did_init_buttons",
           "editor_will_show_context_menu", "editor_did_load_note",
           "state_shortcuts_will_change", "webview_will_set_content"):
    setattr(gh, _h, Hook())


class FakePage:
    """aqt.webview.AnkiWebPage: built with the view's bridge handler."""

    def __init__(self, on_bridge, *a, **k):
        self.on_bridge = on_bridge


class FakeWebView(QtWidgets.QWidget):
    """aqt.webview.AnkiWebView, as far as IOE and the Draw tab use it."""

    def __init__(self, parent=None, title="", kind=None):
        super().__init__(parent)
        self.evals, self.urls = [], []
        self._pendingActions = []
        self._domDone = True
        self._the_page = None
        self.onBridgeCmd = lambda cmd: None

    def setPage(self, page):
        self._the_page = page

    def page(self):
        return self._the_page

    def setUrl(self, url):
        self.urls.append(url)

    def eval(self, js):
        self.evals.append(js)

    def evalWithCallback(self, js, cb):
        self.evals.append(js)

    _evalWithCallback = evalWithCallback

    def _queueAction(self, name, *args):
        self._pendingActions.append((name, args))
        self._maybeRunActions()

    def _maybeRunActions(self):
        pass

    def set_bridge_command(self, func, context):
        self.onBridgeCmd = func

    def _onBridgeCmd(self, cmd):
        if cmd == "close":  # Anki: the injected Escape listener
            return self.onEsc()
        return self.onBridgeCmd(cmd)

    def onEsc(self):
        # Anki's default: Escape closes the nearest dialog.
        w = self.parent()
        while w is not None:
            if isinstance(w, QtWidgets.QDialog):
                w.close()
                break
            w = w.parent()

    def createWindow(self, window_type):
        return FakeWebView()  # Anki: a new AnkiWebView for target=_blank


class FakeDeckChooser:
    def __init__(self, mw, widget, label=True, **k):
        lay = QtWidgets.QHBoxLayout(widget)
        self.deckLabel, self.deck = QtWidgets.QLabel("Deck"), QtWidgets.QPushButton("Default")
        lay.addWidget(self.deckLabel)
        lay.addWidget(self.deck)
        self.selected_deck_id = 1

    def cleanup(self):
        pass


class FakeTagEdit(QtWidgets.QLineEdit):
    def setCol(self, col):
        pass


aqt = sys.modules["aqt"]
wv = sys.modules["aqt.webview"]
wv.AnkiWebView, wv.AnkiWebPage = FakeWebView, FakePage
aqt.webview = wv
aqt.deckchooser = types.SimpleNamespace(DeckChooser=FakeDeckChooser)
aqt.tagedit = types.SimpleNamespace(TagEdit=FakeTagEdit)
sys.modules["aqt.utils"].restoreGeom = lambda *a, **k: None
sys.modules["aqt.utils"].saveGeom = lambda *a, **k: None

TIPS: list = []


def tip(msg, *a, **k):
    TIPS.append(msg)


def attempt(fn, *a, **k):
    """(ok, result): a missing feature is a red check, not a crashed script."""
    try:
        return True, fn(*a, **k)
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)


def b64json(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


def png_bytes(w, h, colour="white") -> bytes:
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(colour))
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


io = importlib.import_module("klausmate.image_occlusion")
masks = importlib.import_module("klausmate.image_occlusion.excal_masks")
theme = importlib.import_module("klausmate.theme")
ok_import, et = attempt(importlib.import_module, "klausmate.image_occlusion.excal_tab")
check("excal_tab imports", ok_import, str(et))
et = et if ok_import else None
cfg = importlib.import_module("klausmate.image_occlusion.config")
ngen = importlib.import_module("klausmate.image_occlusion.ngen")
add = importlib.import_module("klausmate.image_occlusion.add")
ed_mod = importlib.import_module("klausmate.image_occlusion.editor")
main = importlib.import_module("klausmate.image_occlusion.main")
for mod in (add, ngen, main, io) + ((et,) if et else ()):
    mod.tooltip = tip

TMP = tempfile.mkdtemp(prefix="klaus_excal_flow_")
PAGE = "/_addons/klausmate/image_occlusion/excalidraw/"
SERVER = "http://127.0.0.1:40000/"

# A scene: a box with a bound label, a free label, a blank text (skipped).
SCENE = {
    "type": "excalidraw", "version": 2, "source": "local",
    "elements": [
        {"id": "box", "type": "rectangle", "x": 0, "y": 0, "width": 200, "height": 100,
         "angle": 0, "isDeleted": False},
        {"id": "t1", "type": "text", "x": 60, "y": 35, "width": 80, "height": 30,
         "angle": 0, "isDeleted": False, "text": "Heart", "containerId": "box"},
        {"id": "t2", "type": "text", "x": 230, "y": 120, "width": 70, "height": 25,
         "angle": 0, "isDeleted": False, "text": "Aorta Ñandú"},
        {"id": "t3", "type": "text", "x": 10, "y": 10, "width": 5, "height": 5,
         "angle": 0, "isDeleted": False, "text": "  "},
    ],
    "appState": {"viewBackgroundColor": "#ffffff"},
    "files": {},
}
# (300 + 2·20)·2 × (145 + 2·20)·2, as entry.jsx exports it
W, H = 680, 370
PNG = png_bytes(W, H)
RESULT = {"png": base64.b64encode(PNG).decode(), "scene": SCENE,
          "originX": 0, "originY": 0, "width": W, "height": H}
FILL, STROKE = "#FFEBA2", "#2D2D2D"


def listing(d):
    out = []
    for base, _dirs, files in os.walk(d):
        out += [os.path.relpath(os.path.join(base, f), d) for f in files]
    return sorted(out)


# ------------------------------------------------------------ pure-ish helpers

section("blank_png: an 800×600 white PNG")
if et is not None:
    d = tempfile.mkdtemp(dir=TMP)
    ok, p = attempt(et.blank_png, d)
    check("blank_png returns a path in the folder", ok and os.path.dirname(p) == d, str(p))
    if ok:
        img = QtGui.QImage(p)
        check("...a PNG", open(p, "rb").read(8) == b"\x89PNG\r\n\x1a\n")
        check("...800×600", (img.width(), img.height()) == (800, 600))
        check("...white", img.pixelColor(400, 300) == QtGui.QColor("white")
              and img.pixelColor(0, 0) == QtGui.QColor("white"))
        utils = importlib.import_module("klausmate.image_occlusion.utils")
        check("...IOE reads its size", utils.get_image_dimensions(p) == (800, 600))

section("prepare_occlusion: PNG, mask SVG, sidecar")
if et is not None:
    d = tempfile.mkdtemp(dir=TMP)
    ok, out = attempt(et.prepare_occlusion, RESULT, d, FILL, STROKE)
    check("returns (png_path, svg_path, sidecar_json)", ok and len(out) == 3, str(out))
    if ok:
        png_path, svg_path, sidecar = out
        check("the PNG is named diagram-%Y%m%d-%H%M%S.png",
              re.fullmatch(r"diagram-\d{8}-\d{6}\.png", os.path.basename(png_path)) is not None,
              png_path)
        check("...under the folder it was given",
              os.path.realpath(png_path).startswith(os.path.realpath(d)))
        check("...with the page's bytes", open(png_path, "rb").read() == PNG)
        want = masks.masks_svg(W, H, masks.label_rects(SCENE, 0, 0, 20, 2, 4), FILL, STROKE)
        check("the SVG is masks_svg(label_rects(scene, origin, 20, 2, 4))",
              open(svg_path, encoding="utf-8").read() == want)
        check("...two masks (the blank label is skipped)", want.count("<rect") == 2)
        side = json.loads(sidecar)
        check("the sidecar is type excalidraw with the scene's elements",
              side.get("type") == "excalidraw" and side.get("elements") == SCENE["elements"])
        check("...and klaus {originX, originY, padding 20, scale 2}",
              side.get("klaus") == {"originX": 0, "originY": 0, "padding": 20, "scale": 2},
              str(side.get("klaus")))
    r2 = dict(RESULT, originX=-37.5, originY=12)
    ok, out = attempt(et.prepare_occlusion, r2, tempfile.mkdtemp(dir=TMP), FILL, STROKE)
    if ok:
        check("a shifted origin moves the masks and is kept in the sidecar",
              open(out[1], encoding="utf-8").read() == masks.masks_svg(
                  W, H, masks.label_rects(SCENE, -37.5, 12, 20, 2, 4), FILL, STROKE)
              and json.loads(out[2])["klaus"]["originX"] == -37.5)
    ok, out2 = attempt(et.prepare_occlusion, RESULT, d, FILL, STROKE)
    check("a second use in the same second never overwrites the first image",
          ok and out2[0] != out[0] and os.path.isfile(out[0]) if ok else False)

section("prepare_occlusion: errors write nothing")
big = dict(RESULT, png=base64.b64encode(png_bytes(8193, 10)).decode(), width=8193, height=10)
if et is not None:
    cases = {
        "an {error} result": {"error": "empty"},
        "an empty scene": dict(RESULT, scene=dict(SCENE, elements=[])),
        "a scene of deleted elements": dict(RESULT, scene=dict(SCENE, elements=[
            dict(SCENE["elements"][0], isDeleted=True)])),
        "no PNG": dict(RESULT, png=""),
        "not a PNG": dict(RESULT, png=base64.b64encode(b"GIF89a....").decode()),
        "an oversized PNG (side > 8192, R2)": big,
    }
    for label, res in cases.items():
        d = tempfile.mkdtemp(dir=TMP)
        ok, err = attempt(et.prepare_occlusion, res, d, FILL, STROKE)
        check(label + ": ValueError with a message", not ok and "ValueError" in err, str(err))
        check(label + ": no file written", listing(d) == [], str(listing(d)))
    ok, out = attempt(et.prepare_occlusion, dict(RESULT, png=base64.b64encode(
        png_bytes(8192, 4)).decode(), width=8192, height=4), tempfile.mkdtemp(dir=TMP), FILL, STROKE)
    check("exactly 8192 px is allowed", ok, str(out))
    ok, out = attempt(et.prepare_occlusion, dict(RESULT, scene=dict(SCENE, elements=SCENE[
        "elements"][:1])), tempfile.mkdtemp(dir=TMP), FILL, STROKE)
    check("a scene with no text is fine: no masks",
          ok and "<rect" not in open(out[1], encoding="utf-8").read(), str(out))


# ------------------------------------------------------------ the Draw tab

def fake_mw(col):
    return types.SimpleNamespace(
        col=col, pm=types.SimpleNamespace(profile={}), checkpoint=lambda *a: None,
        setupDialogGC=lambda d: None, reset=lambda: None, serverURL=lambda: SERVER,
        progress=types.SimpleNamespace(single_shot=lambda ms, fn, *a, **k: None))


section("DrawTab: page, navigation, new windows, Escape")
USED: list = []
if et is not None:
    et.mw = fake_mw(None)
    holder = QtWidgets.QDialog()
    ok, tab = attempt(et.DrawTab, holder, USED.append)
    check("DrawTab(parent, on_use) builds", ok, str(tab))
    if ok:
        QtWidgets.QVBoxLayout(holder).addWidget(tab)
        web = tab.web
        check("its webview loads the page from Anki's add-on server",
              [u.toString() for u in web.urls] == [SERVER.rstrip("/") + PAGE + "index.html"],
              str([u.toString() for u in web.urls]))
        page = web.page()
        check("the page is built with the view's bridge handler",
              page is not None and page.on_bridge == web._onBridgeCmd)
        nav = page.acceptNavigationRequest
        check("navigation to the page itself is accepted",
              nav(QtCore.QUrl(SERVER + PAGE[1:] + "index.html"), 0, True) is True)
        for url in ("https://github.com/excalidraw/excalidraw", "https://discord.gg/x",
                    "https://libraries.excalidraw.com/", SERVER + "_anki/pages/x.html",
                    "file:///etc/hosts"):
            check("navigation to %s is refused" % url,
                  nav(QtCore.QUrl(url), 0, True) is False
                  and nav(QtCore.QUrl(url), 0, False) is False)
        check("createWindow returns None (no window, no system browser)",
              web.createWindow(0) is None)
        holder.show()
        web._onBridgeCmd("close")  # Anki's Escape listener
        check("Escape in the drawing does not close the editor window", holder.isVisible())
        btns = tab.findChildren(QtWidgets.QPushButton)
        check("one Qt button, 'Use drawing'", [b.text() for b in btns] == ["Use drawing"],
              str([b.text() for b in btns]))

section("DrawTab: ready, theme, load, use, results")
if et is not None and ok:
    web.evals.clear()
    tab.load(SCENE)
    check("load() before the page's ready calls nothing", web.evals == [], str(web.evals))
    tab.use()
    check("use() before ready calls nothing", web.evals == [], str(web.evals))
    web._onBridgeCmd("klausexcal:ready:" + b64json({}))
    loads = [e for e in web.evals if "klausExcalidraw.load(" in e]
    check("ready flushes exactly one load", len(loads) == 1, str(web.evals))
    if loads:
        arg = loads[0].split("klausExcalidraw.load(", 1)[1].rsplit(")", 1)[0]
        check("...whose argument is a JSON *string* of the scene",
              json.loads(json.loads(arg)) == SCENE, arg[:80])
    c = theme.palette(False)
    css = [e for e in web.evals if "--color-primary" in e]
    check("ready injects Klaus's accent as .excalidraw CSS variables",
          len(css) == 1 and c["blue_accent"] in css[0] and ".excalidraw" in css[0], str(css)[:200])
    check("...and Klaus's UI font as --ui-font",
          css and "--ui-font" in css[0] and json.dumps(theme.FONT_FAMILY)[1:-1] in css[0])
    check("...before the scene is loaded",
          css and loads and web.evals.index(css[0]) < web.evals.index(loads[0]))
    web.evals.clear()
    tab.load(None)
    check("load(None) after ready loads an empty canvas at once",
          web.evals == ["klausExcalidraw.load(null);"], str(web.evals))
    web.evals.clear()
    tab.use_btn.click()
    check("'Use drawing' calls klausExcalidraw.occlude()",
          web.evals == ["klausExcalidraw.occlude();"], str(web.evals))
    TIPS.clear()
    web._onBridgeCmd("klausexcal:occlude:" + b64json({"error": "empty"}))
    check("an {error} result: a tooltip, on_use not called", len(TIPS) == 1 and USED == [],
          f"{TIPS} {USED}")
    web._onBridgeCmd("klausexcal:occlude:" + b64json(RESULT))
    check("a good result reaches on_use as a dict", USED == [RESULT])
    TIPS.clear()
    ok2, _ = attempt(web._onBridgeCmd, "klausexcal:occlude:@@@not-base64")
    check("a garbled message is logged, never raised", ok2 and len(USED) == 1)
    ok2, _ = attempt(web._onBridgeCmd, "klausmate:something:else")
    check("other messages are ignored", ok2 and len(USED) == 1)
    tab.shutdown()
    web.evals.clear()
    web._onBridgeCmd("klausexcal:occlude:" + b64json(RESULT))
    tab.use()
    check("after shutdown(): no on_use, no eval", len(USED) == 1 and web.evals == [])


section("page chrome: rebuilt bundle and CSS hides")
EXD = os.path.join(ROOT, "klausmate", "image_occlusion", "excalidraw")
js = open(os.path.join(EXD, "excalidraw.js"), encoding="utf-8").read()
html = open(os.path.join(EXD, "index.html"), encoding="utf-8").read()
src = open(os.path.join(EXD, "entry.jsx"), encoding="utf-8").read()
check("the bundle no longer has the in-page Occlude/Cancel (klaus-actions)",
      "klaus-actions" not in js and "klaus-actions" not in src)
check("entry.jsx renders an empty <MainMenu> and no renderTopRightUI",
      re.search(r"<MainMenu\s*/>|<MainMenu>\s*</MainMenu>", src) is not None
      and "renderTopRightUI" not in src)
check("entry.jsx exposes klausExcalidraw.occlude",
      re.search(r"window\.klausExcalidraw\s*=\s*\{[^}]*\bocclude\b", src) is not None)
check("the bundle exposes it too", "exportForOcclusion" in js and "klausexcal:" in js
      and re.search(r"klausExcalidraw=\{[^}]*occlude", js) is not None)
for cls in (".main-menu-trigger", ".sidebar-trigger", ".help-icon"):
    rules = re.findall(r"([^{}]+)\{([^}]*)\}", html[html.find("<style>"):html.find("</style>")])
    check("index.html hides " + cls, any(cls in sel and "display: none" in body.replace(
        "display:none", "display: none") for sel, body in rules))


# ------------------------------------------------------------ the editor

class Note(dict):
    flushed = []

    def __init__(self, col=None, model=None, nid=None):
        super().__init__()
        self.tags, self.nid = [], nid

    def model(self):
        return None


ngen.Note = Note


def io_model():
    return {"name": cfg.IO_MODEL_NAME, "tmpls": [{"name": cfg.IO_CARD_NAME}],
            "flds": [{"name": cfg.IO_FLDS[i], "sticky": False} for i in cfg.IO_FLDS_IDS]}


class Col:
    def __init__(self, media, returned=None):
        self._conf = {"imgocc": copy.deepcopy(cfg.default_conf_syncd)}
        model = io_model()
        self.models = types.SimpleNamespace(
            by_name=lambda n: model if n == model["name"] else None,
            fieldNames=lambda m: [f["name"] for f in m["flds"]])
        self.returned = returned
        self.adds = []
        self.media = types.SimpleNamespace(dir=lambda: media, add_file=self._add_file)
        self.added = []

    def _add_file(self, p):
        """Anki may rename on add; this one answers self.returned."""
        self.adds.append(p)
        name = self.returned or os.path.basename(p)
        shutil.copy(p, os.path.join(self.media.dir(), name))
        return name

    def get_config(self, key, default=None):
        return copy.deepcopy(self._conf[key]) if key in self._conf else default

    def set_config(self, key, val):
        self._conf[key] = copy.deepcopy(val)

    def addNote(self, note):
        self.added.append(note)


MEDIA = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
col = Col(MEDIA, returned="diagram-returned-1.png")
MW = fake_mw(col)
for mod in (cfg, ngen, add, ed_mod, main, io) + ((et,) if et else ()):
    mod.mw = MW
io._active = True


class Window(QtWidgets.QWidget):
    deckChooser = types.SimpleNamespace(selectedId=lambda: 1)


def new_editor():
    return types.SimpleNamespace(addMode=True, note=Note(), parentWindow=Window(),
                                 loadNote=lambda: None)


def tab_texts(dialog):
    return [dialog.tab_widget.tabText(i) for i in range(dialog.tab_widget.count())]


section("occlude(editor, path): IOE's two tabs, unchanged")
photo = os.path.join(TMP, "photo.png")
open(photo, "wb").write(png_bytes(400, 300))
e1 = new_editor()
ok, r = attempt(io.occlude, e1, photo)
d1 = getattr(getattr(e1, "imgoccadd", None), "imgoccedit", None)
check("occlude(editor, path) opens ImgOccEdit", ok and r is True and d1 is not None, str(r))
if d1 is not None:
    check("...with the two original tabs",
          tab_texts(d1) == ["&Masks Editor", "&Fields"], str(tab_texts(d1)))
    check("...the Add buttons enabled", d1.ao_btn.isEnabled() and d1.oa_btn.isEnabled())
    check("...and no Draw tab object", getattr(d1, "draw_tab", None) is None)
    d1.close()

section("occlude(editor, draw=True): a third tab, Draw, current; Add disabled")
e2 = new_editor()
ok, r = attempt(io.occlude, e2, draw=True)
ia = getattr(e2, "imgoccadd", None)
dlg = getattr(ia, "imgoccedit", None)
check("occlude(editor, draw=True) returns True and opens ImgOccEdit",
      ok and r is True and dlg is not None, str(r))
if dlg is not None:
    check("three tabs: Masks Editor, Fields, &Draw",
          tab_texts(dlg) == ["&Masks Editor", "&Fields", "&Draw"], str(tab_texts(dlg)))
    check("the Draw tab is current", dlg.tab_widget.currentIndex() == 2)
    check("...and it is the DrawTab", et is not None and isinstance(dlg.tab_widget.widget(2),
                                                                      et.DrawTab))
    check("both Add buttons are disabled", not dlg.ao_btn.isEnabled()
          and not dlg.oa_btn.isEnabled())
    blank = ia.image_path
    check("the image is the 800×600 blank PNG",
          blank and add.get_image_dimensions(blank) == (800, 600), str(blank))
    q = QtCore.QUrlQuery(dlg.svg_edit.urls[0]) if dlg.svg_edit.urls else None
    check("svg-edit opens on it (dimensions 800,600)",
          q is not None and q.queryItemValue("dimensions") == "800,600")
    check("the blank PNG is in a klaus-diagram- temp dir, not user_files or media",
          os.path.basename(os.path.dirname(blank)).startswith("klaus-diagram-")
          and not blank.startswith(MEDIA))

    section("Add before 'Use drawing' does nothing (buttons and shortcuts)")
    before = list(dlg.svg_edit.evals)
    TIPS.clear()
    for label, fn in (("Ctrl+Return (defaultAction)", lambda: dlg.defaultAction(True)),
                      ("Ctrl+Shift+Return (addOA)", lambda: dlg.addOA(True)),
                      ("addAO", dlg.addAO)):
        ok2, res = attempt(fn)
        check(label + ": no svg-edit read, no notes", ok2 and dlg.svg_edit.evals == before
              and col.added == [], f"{res} {dlg.svg_edit.evals[len(before):]}")
    check("...and a tooltip says why", len(TIPS) == 3, str(TIPS))

    section("an {error} from the page: tooltip, stays on Draw, nothing written")
    tab = dlg.draw_tab
    tab.web._onBridgeCmd("klausexcal:ready:" + b64json({}))
    draw_dir = os.path.dirname(blank)
    files0 = listing(draw_dir)
    TIPS.clear()
    tab.web._onBridgeCmd("klausexcal:occlude:" + b64json({"error": "empty"}))
    check("a tooltip", len(TIPS) == 1, str(TIPS))
    check("the Draw tab stays current", dlg.tab_widget.currentIndex() == 2)
    check("no file written", listing(draw_dir) == files0 and listing(MEDIA) == [])
    check("Add stays disabled", not dlg.ao_btn.isEnabled())

    section("Review Focus 3: an oversized drawing: tooltip, image unchanged")
    evals0 = list(dlg.svg_edit.evals)
    TIPS.clear()
    ok2, res = attempt(ia.use_drawing, big)
    check("use_drawing returns False", ok2 and res is False, str(res))
    check("a tooltip", len(TIPS) == 1, str(TIPS))
    check("the image is unchanged", ia.image_path == blank and dlg.svg_edit.evals == evals0)
    check("no file written, no media", listing(draw_dir) == files0 and listing(MEDIA) == [])
    check("still on Draw, Add still disabled",
          dlg.tab_widget.currentIndex() == 2 and not dlg.ao_btn.isEnabled())

    section("use_drawing: the change-image path, masks, Add, tab 0")
    TIPS.clear()
    dlg.svg_edit.evals.clear()
    tab.web._onBridgeCmd("klausexcal:occlude:" + b64json(RESULT))  # through the button path
    png_path = ia.image_path
    check("image_path is the new diagram PNG",
          png_path != blank and re.fullmatch(r"diagram-\d{8}-\d{6}\.png",
                                             os.path.basename(png_path or "")) is not None,
          str(png_path))
    ev = "\n".join(dlg.svg_edit.evals)
    check("svg-edit: setBackground('#FFF', <the PNG's URL>)",
          "svgCanvas.setBackground('#FFF', '%s')" % add.path_to_url(png_path) in ev, ev[:300])
    check("svg-edit: setResolution(<the PNG's size>)",
          "svgCanvas.setResolution(%d, %d)" % (W, H) in ev, ev[:300])
    want = masks.masks_svg(W, H, masks.label_rects(SCENE, 0, 0, 20, 2, 4),
                           "#" + ia.sconf["ofill"], "#" + ia.sconf["scol"])
    check("svg-edit loads masks equal to masks_svg(...)",
          "svgEditor.loadFromString(%s)" % json.dumps(want) in ev)
    check("...before the background/resolution (setSvgString resizes the canvas)",
          ev.find("loadFromString") < ev.find("setBackground") < ev.find("setResolution"))
    check("Add is enabled", dlg.ao_btn.isEnabled() and dlg.oa_btn.isEnabled())
    check("the Masks Editor tab is current", dlg.tab_widget.currentIndex() == 0)
    check("no tooltip", TIPS == [], str(TIPS))
    check("media untouched until Add", listing(MEDIA) == [])

    section("after IOE adds the notes: <returned name>.excalidraw in media")
    ok2, r = attempt(ia._onAddNotesButton, "ao", False, want)
    check("IOE added two notes", ok2 and len(col.added) == 2, f"{r} {len(col.added)}")
    side = os.path.join(MEDIA, "diagram-returned-1.png.excalidraw")
    check("the sidecar follows the name Anki returned, not the requested one",
          os.path.isfile(side) and not any(
              n.endswith(".excalidraw") and n != os.path.basename(side) for n in listing(MEDIA)),
          str(listing(MEDIA)))
    if os.path.isfile(side):
        data = json.loads(open(side, encoding="utf-8").read())
        check("...holding the scene and klaus.originX/originY",
              data.get("type") == "excalidraw" and data.get("elements") == SCENE["elements"]
              and data.get("klaus", {}).get("originX") == 0
              and data.get("klaus", {}).get("originY") == 0)

    section("Change Image to a photo: Add enabled, no sidecar")
    e5 = new_editor()
    io.occlude(e5, draw=True)
    ia5 = e5.imgoccadd
    ia5.use_drawing(RESULT)
    ia5.getNewImage = lambda *a, **k: photo
    ia5.onChangeImage()
    check("the photo replaces the drawing", ia5.image_path == photo)
    check("Add stays enabled", ia5.imgoccedit.ao_btn.isEnabled())
    col5 = Col(tempfile.mkdtemp(prefix="io-media-", dir=TMP))
    for mod in (cfg, ngen, add):
        mod.mw = fake_mw(col5)
    attempt(ia5._onAddNotesButton, "ao", False, want)
    check("...and adding writes no .excalidraw for the photo",
          not [n for n in listing(col5.media.dir()) if n.endswith(".excalidraw")],
          str(listing(col5.media.dir())))
    for mod in (cfg, ngen, add):
        mod.mw = MW
    ia5.imgoccedit.close()
    dlg.close()


section("Review Focus 4: closing mid-draw writes nothing and never calls on_use")
for label, closer in (("closing the window", lambda d: d.close()),
                      ("profile_will_close", lambda d: [fn() for fn in list(gh.profile_will_close)])):
    media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
    c = Col(media)
    for mod in (cfg, ngen, add, ed_mod, main):
        mod.mw = fake_mw(c)
    e = new_editor()
    attempt(io.occlude, e, draw=True)
    ia4 = getattr(e, "imgoccadd", None)
    d4 = getattr(ia4, "imgoccedit", None)
    if d4 is None:
        check(label + ": a draw session opened", False)
        continue
    calls = []
    real_use = ia4.use_drawing
    ia4.use_drawing = lambda r: calls.append(r) or real_use(r)
    t4 = d4.draw_tab
    t4._on_use = ia4.use_drawing
    t4.web._onBridgeCmd("klausexcal:ready:" + b64json({}))
    blank4 = ia4.image_path
    files4 = listing(os.path.dirname(blank4))
    closer(d4)
    app.processEvents()
    check(label + ": the editor is closed", not d4.isVisible())
    ok4, _ = attempt(t4.web._onBridgeCmd, "klausexcal:occlude:" + b64json(RESULT))
    check(label + ": a late result is dropped without raising", ok4)
    check(label + ": on_use is never called", calls == [], str(calls))
    check(label + ": no media touched", listing(media) == [] and c.adds == [])
    check(label + ": no diagram written", listing(os.path.dirname(blank4)) == files4)
    ok4, r4 = attempt(real_use, RESULT)
    check(label + ": use_drawing itself refuses after close", ok4 and r4 is False, str(r4))
for mod in (cfg, ngen, add, ed_mod, main):
    mod.mw = MW


section("the editor button: a menu of two sources")
builder = getattr(main, "source_menu", None)
check("main.source_menu exists", builder is not None)
if builder is not None:
    ok, menu = attempt(builder, new_editor())
    check("it builds a QMenu offscreen", ok and isinstance(menu, QtWidgets.QMenu), str(menu))
    if ok:
        check("exactly 'Choose image…' and 'Draw a diagram…'",
              [a.text() for a in menu.actions()] == ["Choose image…", "Draw a diagram…"],
              str([a.text() for a in menu.actions()]))
io_btn = getattr(main, "on_io_button", None)
if io_btn is not None:
    em = new_editor()
    ok, _ = attempt(io_btn, em)
    shown = em.parentWindow.findChildren(QtWidgets.QMenu)
    check("in Add, the I/O button pops the menu up and returns (no exec)",
          ok and len(shown) == 1 and shown[0].isVisible(), str(shown))
    if shown:
        shown[0].hide()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
        check("...and the hidden menu is deleted",
              not em.parentWindow.findChildren(QtWidgets.QMenu))
btn_src = open(main.__file__, encoding="utf-8").read()
check("the I/O button goes through the menu (on_io_button)",
      "on_io_button(editor)" in btn_src)
check("io.occlude takes draw=False by default (reader's positional call still works)",
      __import__("inspect").signature(io.occlude).parameters.get("draw") is not None
      and __import__("inspect").signature(io.occlude).parameters["draw"].default is False)

raise SystemExit(report())
