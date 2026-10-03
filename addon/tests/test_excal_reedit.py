"""Image Occlusion 3/3: re-edit a diagram; note ids and hand masks survive.

remap_masks carries the masks over when a drawing is used again: a mask
that covers an old text label (IoU >= 0.8) follows its label (keeping its
id, so the note updates in place); every other mask is the user's own and
moves with the scene origin (Review Focus 5), dropped once it lies wholly
outside the new image. In edit mode, an occlusion note whose image has a
readable _<image>.excalidraw gets the Draw tab (Masks Editor stays
current); "Use drawing" there, and a repeat use in add mode, goes through
remap_masks, and an update saves the scene beside the new image name.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_excal_reedit.py
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
from xml.dom import minidom

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


def attempt(fn, *a, **k):
    """(ok, result): a missing feature is a red check, not a crashed script."""
    try:
        return True, fn(*a, **k)
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)


em = importlib.import_module("klaus_note.image_occlusion.excal_masks")
remap = getattr(em, "remap_masks", None)
check("excal_masks.remap_masks exists", remap is not None)

# ------------------------------------------------------------ fixtures

# A box with a bound label and a free label; origin (0, 0); 680 × 370 px.
OLD = {
    "type": "excalidraw", "version": 2, "source": "local",
    "elements": [
        {"id": "box", "type": "rectangle", "x": 0, "y": 0, "width": 200, "height": 100,
         "angle": 0, "isDeleted": False},
        {"id": "t1", "type": "text", "x": 60, "y": 35, "width": 80, "height": 30,
         "angle": 0, "isDeleted": False, "text": "Heart", "containerId": "box"},
        {"id": "t2", "type": "text", "x": 230, "y": 120, "width": 70, "height": 25,
         "angle": 0, "isDeleted": False, "text": "Aorta"},
    ],
    "appState": {"viewBackgroundColor": "#ffffff"}, "files": {},
}
META = {"originX": 0, "originY": 0, "padding": 20, "scale": 2}
W, H = 680, 370
OLD_LABELS = {r[0]: r[1:] for r in em.label_rects(OLD, 0, 0, 20, 2, 4)}
# t1 -> (156, 106, 168, 68); t2 -> (496, 276, 148, 58)
STYLE = 'fill="#ABCDEF" stroke="#123456" stroke-width="1"'


def rect(rid, x, y, w, h, style=STYLE):
    return '<rect id="%s" %s x="%s" y="%s" width="%s" height="%s"/>' % (rid, style, x, y, w, h)


def svg_edit_svg(w, h, masks, labels=""):
    """As svgCanvasToString() hands it back: comment, whitespace, layers, ids."""
    return ('<svg width="%d" height="%d" xmlns="http://www.w3.org/2000/svg" '
            'xmlns:svg="http://www.w3.org/2000/svg">\n'
            ' <!-- Created with SVG-edit - http://svg-edit.googlecode.com/ -->\n'
            ' <g>\n  <title>Labels</title>%s\n </g>\n'
            ' <g>\n  <title>Masks</title>\n  %s\n </g>\n</svg>' % (w, h, labels, "\n  ".join(masks)))


L1 = rect("abc-ao-1", *OLD_LABELS["t1"])
L2 = rect("abc-ao-2", *OLD_LABELS["t2"])
HAND = rect("abc-ao-3", 10, 220, 50, 40)
OLD_SVG = svg_edit_svg(W, H, [L1, L2, HAND])

GEOM = {"rect": ("x", "y", "width", "height"), "ellipse": ("cx", "cy", "rx", "ry")}


def parse(svg):
    """(width, height, [(tag, attrs)] of the masks layer, [(tag, attrs)] of the others)."""
    root = minidom.parseString(svg).documentElement
    layers = [n for n in root.childNodes if n.nodeType == n.ELEMENT_NODE and n.nodeName == "g"]

    def kids(layer):
        return [(n.nodeName, dict(n.attributes.items())) for n in layer.childNodes
                if n.nodeType == n.ELEMENT_NODE and n.nodeName != "title"]

    others = [k for layer in layers[:-1] for k in kids(layer)]
    return root.getAttribute("width"), root.getAttribute("height"), kids(layers[-1]), others


def by_id(masks):
    return {a.get("id") or "<no id %d>" % i: (tag, a) for i, (tag, a) in enumerate(masks)}


def geom(attrs, tag="rect"):
    return tuple(float(attrs[k]) for k in GEOM[tag])


def close(a, b):
    return len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))


def scene(*changes, drop=(), extra=()):
    s = copy.deepcopy(OLD)
    for eid, fields in changes:
        next(e for e in s["elements"] if e["id"] == eid).update(fields)
    s["elements"] = [e for e in s["elements"] if e["id"] not in drop] + list(extra)
    return s


def run(old_svg, new, new_meta, w, h, old=OLD, old_meta=META):
    if remap is None:
        return False, "no remap_masks"
    return attempt(remap, old_svg, old, old_meta, new, new_meta, w, h)


# ------------------------------------------------------------ remap_masks (pure)

section("unchanged scene: the masks come back as they went in, ids kept")
ok, out = run(OLD_SVG, OLD, META, W, H)
check("remap_masks runs", ok, str(out))
if ok:
    w, h, got, _ = parse(out)
    _, _, want, _ = parse(OLD_SVG)
    check("the canvas is the new image's size", (w, h) == (str(W), str(H)), str((w, h)))
    g, wn = by_id(got), by_id(want)
    check("the same three masks, by id", sorted(g) == sorted(wn) == ["abc-ao-1", "abc-ao-2", "abc-ao-3"],
          str(sorted(g)))
    check("...each with the same geometry and attributes",
          all(close(geom(g[i][1]), geom(wn[i][1]))
              and {k: v for k, v in g[i][1].items() if k not in GEOM["rect"]}
              == {k: v for k, v in wn[i][1].items() if k not in GEOM["rect"]} for i in g if i in wn),
          str(got))
    check("it is IOE's omask format: a Labels layer, then the Masks layer",
          re.search(r"<title>Labels</title>.*<title>Masks</title>", out, re.S) is not None)

section("a label's text edited: its mask keeps its id, the box follows the text")
NEW1 = scene(("t1", {"text": "Heart muscle", "x": 20, "width": 160}))
want1 = {r[0]: r[1:] for r in em.label_rects(NEW1, 0, 0, 20, 2, 4)}
ok, out = run(OLD_SVG, NEW1, META, W, H)
if ok:
    g = by_id(parse(out)[2])
    check("abc-ao-1 is still there", "abc-ao-1" in g, str(sorted(g)))
    check("...on the new box", "abc-ao-1" in g and close(geom(g["abc-ao-1"][1]), want1["t1"]),
          str(g.get("abc-ao-1")))
    check("...keeping its own fill and stroke",
          "abc-ao-1" in g and g["abc-ao-1"][1].get("fill") == "#ABCDEF"
          and g["abc-ao-1"][1].get("stroke") == "#123456")
    check("abc-ao-2 and the hand mask are unchanged",
          close(geom(g["abc-ao-2"][1]), OLD_LABELS["t2"]) and close(geom(g["abc-ao-3"][1]),
                                                                    (10, 220, 50, 40)))
else:
    check("remap_masks runs", False, str(out))

section("a label deleted: its mask is gone")
NEW2 = scene(drop=("t2",))
W2, H2 = (200 + 40) * 2, (100 + 40) * 2  # the box alone
ok, out = run(OLD_SVG, NEW2, META, W2, H2)
if ok:
    g = by_id(parse(out)[2])
    check("abc-ao-2 is gone; abc-ao-1 and the hand mask stay",
          sorted(g) == ["abc-ao-1", "abc-ao-3"], str(sorted(g)))
else:
    check("remap_masks runs", False, str(out))
ok, out = run(OLD_SVG, scene(("t2", {"isDeleted": True})), META, W, H)
check("...also when the label is only marked isDeleted",
      ok and sorted(by_id(parse(out)[2])) == ["abc-ao-1", "abc-ao-3"], str(out)[:200])

section("Review Focus 5: an element added left and above; hand masks move with the scene")
LEFT = {"id": "new", "type": "rectangle", "x": -50, "y": -30, "width": 30, "height": 30,
        "angle": 0, "isDeleted": False}
NEW3 = scene(extra=(LEFT,))
META3 = dict(META, originX=-50, originY=-30)
W3, H3 = (350 + 40) * 2, (175 + 40) * 2
want3 = {r[0]: r[1:] for r in em.label_rects(NEW3, -50, -30, 20, 2, 4)}
ELL = ('<ellipse id="abc-ao-4" %s cx="400" cy="60" rx="20" ry="10"/>' % STYLE)
POLY = ('<polygon id="abc-ao-5" %s points="10,10 40,10 25,40"/>' % STYLE)
TEXT = '<text id="svg_9" x="300" y="30">note</text>'
OLD_SVG3 = svg_edit_svg(W, H, [L1, L2, HAND, ELL, POLY], labels=TEXT)
ok, out = run(OLD_SVG3, NEW3, META3, W3, H3)
if ok:
    _, _, masks3, others3 = parse(out)
    g = by_id(masks3)
    check("the hand rect moves +100 px in x and +60 px in y",
          "abc-ao-3" in g and close(geom(g["abc-ao-3"][1]), (110, 280, 50, 40)),
          str(g.get("abc-ao-3")))
    check("the hand ellipse moves its centre the same way",
          "abc-ao-4" in g and close(geom(g["abc-ao-4"][1], "ellipse"), (500, 120, 20, 10)),
          str(g.get("abc-ao-4")))
    check("a polygon gets a translate(100 60) transform",
          "abc-ao-5" in g and re.fullmatch(r"translate\(100,? 60\)",
                                           g["abc-ao-5"][1].get("transform", "")) is not None,
          str(g.get("abc-ao-5")))
    check("the label masks still sit on their labels, ids kept",
          close(geom(g["abc-ao-1"][1]), want3["t1"]) and close(geom(g["abc-ao-2"][1]), want3["t2"]),
          str(masks3))
    check("...which moved by the same +100/+60",
          close(geom(g["abc-ao-1"][1]), (OLD_LABELS["t1"][0] + 100, OLD_LABELS["t1"][1] + 60,
                                         *OLD_LABELS["t1"][2:])))
    check("svg-edit's Labels-layer text moves too",
          len(others3) == 1 and re.fullmatch(r"translate\(100,? 60\)",
                                             others3[0][1].get("transform", "")) is not None,
          str(others3))
else:
    check("remap_masks runs", False, str(out))

section("hand masks outside the new image are dropped")
OUT = rect("abc-ao-6", 600, 10, 40, 40)        # wholly right of 480 px
EDGE = rect("abc-ao-7", 460, 10, 40, 40)       # still partly inside
BELOW = rect("abc-ao-8", 10, 300, 40, 40)      # wholly below 280 px
ok, out = run(svg_edit_svg(W, H, [L1, L2, HAND, OUT, EDGE, BELOW]), NEW2, META, W2, H2)
if ok:
    g = by_id(parse(out)[2])
    check("a hand mask wholly outside is dropped (right, below)",
          "abc-ao-6" not in g and "abc-ao-8" not in g, str(sorted(g)))
    check("one still partly inside is kept, unmoved",
          "abc-ao-7" in g and close(geom(g["abc-ao-7"][1]), (460, 10, 40, 40)), str(sorted(g)))
else:
    check("remap_masks runs", False, str(out))

section("a truly new label gets exactly one new mask, id klaus-new-1, in the old style")
T4 = {"id": "t4", "type": "text", "x": 20, "y": 120, "width": 60, "height": 20,
      "angle": 0, "isDeleted": False, "text": "Vena"}
NEW4 = scene(extra=(T4,))
want4 = {r[0]: r[1:] for r in em.label_rects(NEW4, 0, 0, 20, 2, 4)}
ok, out = run(OLD_SVG, NEW4, META, W, H)
if ok:
    masks4 = parse(out)[2]
    g = by_id(masks4)
    check("four masks: the three old ones and one new", len(masks4) == 4
          and sorted(g) == ["abc-ao-1", "abc-ao-2", "abc-ao-3", "klaus-new-1"], str(sorted(g)))
    fresh = g.get("klaus-new-1", ("", {}))[1]
    check("...the new one on the new label", fresh and close(geom(fresh), want4["t4"]), str(fresh))
    check("...in the old masks' fill and stroke",
          fresh.get("fill") == "#ABCDEF" and fresh.get("stroke") == "#123456", str(fresh))
else:
    check("remap_masks runs", False, str(out))
ok, out = run(svg_edit_svg(W, H, [L1, L2, HAND, rect("klaus-new-1", 600, 10, 20, 20)]), NEW4, META, W, H)
g = by_id(parse(out)[2]) if ok else {}
check("a new mask's id never collides with one already there (klaus-new-2)",
      len(g) == 5 and "klaus-new-2" in g and close(geom(g["klaus-new-2"][1]), want4["t4"]), str(sorted(g)))

section("R22: a label the old scene had keeps what the user left of its mask")
x, y, w_, h_ = OLD_LABELS["t1"]
WIDE = rect("abc-ao-1", x, y, w_ * 1.65, h_)  # IoU 1/1.65 ~ 0.6: the user's now
ok, out = run(svg_edit_svg(W, H, [WIDE, L2, HAND]), OLD, META, W, H)
g = by_id(parse(out)[2]) if ok else {}
check("a widened mask, unchanged scene: still three masks, no second rect for t1",
      ok and len(parse(out)[2]) == 3, str(sorted(g)))
check("...the widened mask keeps its id and its own box",
      "abc-ao-1" in g and close(geom(g["abc-ao-1"][1]), (x, y, w_ * 1.65, h_)), str(g.get("abc-ao-1")))
ok, out = run(svg_edit_svg(W, H, [WIDE, L2, HAND]), NEW1, META, W, H)
check("...also when its label's text changed: three masks, abc-ao-1 unmoved",
      ok and len(parse(out)[2]) == 3
      and close(geom(by_id(parse(out)[2])["abc-ao-1"][1]), (x, y, w_ * 1.65, h_)), str(out)[:200])
ok, out = run(svg_edit_svg(W, H, [L1, HAND]), OLD, META, W, H)
g = by_id(parse(out)[2]) if ok else {}
check("a label whose mask the user deleted gets none back (two masks)",
      ok and len(parse(out)[2]) == 2 and sorted(g) == ["abc-ao-1", "abc-ao-3"], str(sorted(g)))
ok, out = run(svg_edit_svg(W, H, [L1, HAND]), NEW4, META, W, H)
g = by_id(parse(out)[2]) if ok else {}
check("...while a new label beside it still gets exactly one (three masks)",
      ok and len(parse(out)[2]) == 3 and sorted(g) == ["abc-ao-1", "abc-ao-3", "klaus-new-1"],
      str(sorted(g)))

section("two masks over one label: the best follows it, the other is the user's")
DUP = rect("abc-ao-9", x + 8, y + 4, w_, h_)  # IoU ~0.84, below L1's 1.0
ok, out = run(svg_edit_svg(W, H, [DUP, L1, L2, HAND]), NEW3, META3, W3, H3)
g = by_id(parse(out)[2]) if ok else {}
check("four masks, none removed", ok and len(parse(out)[2]) == 4
      and sorted(g) == ["abc-ao-1", "abc-ao-2", "abc-ao-3", "abc-ao-9"], str(sorted(g)))
check("the exact one (abc-ao-1) follows the label",
      "abc-ao-1" in g and close(geom(g["abc-ao-1"][1]), want3["t1"]), str(g.get("abc-ao-1")))
check("the other keeps its id and shifts like a hand mask (+100/+60)",
      "abc-ao-9" in g and close(geom(g["abc-ao-9"][1]), (x + 108, y + 64, w_, h_)), str(g.get("abc-ao-9")))

section("a label mask the user nudged still follows its label (IoU >= 0.8)")
x, y, w_, h_ = OLD_LABELS["t1"]
ok, out = run(svg_edit_svg(W, H, [rect("abc-ao-1", x + 6, y + 3, w_, h_), L2, HAND]), NEW1, META, W, H)
check("abc-ao-1 lands on the edited label's box",
      ok and close(geom(by_id(parse(out)[2])["abc-ao-1"][1]), want1["t1"]), str(out)[:200])
ok, out = run(svg_edit_svg(W, H, [rect("abc-ao-1", x + 120, y, w_, h_), L2, HAND]), NEW3, META3, W3, H3)
check("a label mask moved well off its label is the user's: it shifts like a hand mask",
      ok and close(geom(by_id(parse(out)[2])["abc-ao-1"][1]), (x + 220, y + 60, w_, h_)), str(out)[:200])


# ------------------------------------------------------------ the editor harness

class Hook(list):
    pass


gh = sys.modules["aqt.gui_hooks"]
for _h in ("profile_will_close", "card_will_show", "reviewer_did_show_answer",
           "browser_menus_did_init", "profile_did_open", "editor_did_init_buttons",
           "editor_will_show_context_menu", "editor_did_load_note",
           "state_shortcuts_will_change", "webview_will_set_content"):
    setattr(gh, _h, Hook())


class FakePage:
    def __init__(self, on_bridge, *a, **k):
        self.on_bridge = on_bridge


class FakeWebView(QtWidgets.QWidget):
    """aqt.webview.AnkiWebView; evalWithCallback keeps the callback to answer by hand."""

    def __init__(self, parent=None, title="", kind=None):
        super().__init__(parent)
        self.evals, self.urls, self.callbacks = [], [], []
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
        self.callbacks.append(cb)

    _evalWithCallback = evalWithCallback

    def _queueAction(self, name, *args):
        self._pendingActions.append((name, args))

    def _maybeRunActions(self):
        pass

    def set_bridge_command(self, func, context):
        self.onBridgeCmd = func

    def _onBridgeCmd(self, cmd):
        return self.onBridgeCmd(cmd)

    def onEsc(self):
        pass


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


io = importlib.import_module("klaus_note.image_occlusion")
cfg = importlib.import_module("klaus_note.image_occlusion.config")
ngen = importlib.import_module("klaus_note.image_occlusion.ngen")
add = importlib.import_module("klaus_note.image_occlusion.add")
ed_mod = importlib.import_module("klaus_note.image_occlusion.editor")
main = importlib.import_module("klaus_note.image_occlusion.main")
et = importlib.import_module("klaus_note.image_occlusion.excal_tab")
utils = importlib.import_module("klaus_note.image_occlusion.utils")
for mod in (add, ngen, main, io, et):
    mod.tooltip = tip
ASKS: list = []
# IOE's "delete N / create M cards?" confirm: recorded and answered Yes.
ngen.io_ask = lambda parent, text, on_answer, **k: (ASKS.append(text), on_answer(True))

TMP = tempfile.mkdtemp(prefix="klaus_excal_reedit_")


def png_bytes(w, h) -> bytes:
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor("white"))
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def result(sc, ox, oy, w, h):
    return {"png": base64.b64encode(png_bytes(w, h)).decode(), "scene": sc,
            "originX": ox, "originY": oy, "width": w, "height": h}


def sidecar(sc, meta):
    return dict(sc, type="excalidraw", klaus=dict(meta))


def listing(d):
    return sorted(os.listdir(d))


# ------------------------------------------------------------ read_diagram

section("read_diagram: only a readable _<image>.excalidraw with its klaus block")
HD = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
check("read_diagram is the one name (no unused has_diagram beside it)",
      not hasattr(et, "has_diagram") and callable(getattr(et, "read_diagram", None)))


def has(media_dir, name):
    return et.read_diagram(media_dir, name) is not None


cases = (
    ("missing", None, False),
    ("invalid JSON", "{not json", False),
    ("JSON that is not a scene", "[1, 2]", False),
    ("a scene without its klaus block", json.dumps(OLD), False),
    ("a klaus block without an origin", json.dumps(dict(OLD, klaus={"scale": 2})), False),
    ("a non-numeric origin", json.dumps(sidecar(OLD, dict(META, originX="left"))), False),
    ("a saved scene", json.dumps(sidecar(OLD, META)), True),
)
for i, (label, body, want) in enumerate(cases):
    name = "img%d.png" % i
    if body is not None:
        with open(os.path.join(HD, "_" + name + ".excalidraw"), "w", encoding="utf-8") as f:
            f.write(body)
    ok, r = attempt(has, HD, name)
    check("%s: %s" % (label, want), ok and r is want, str(r))
with open(os.path.join(HD, "img9.png.excalidraw"), "w", encoding="utf-8") as f:
    f.write(json.dumps(sidecar(OLD, META)))
check("the name without its leading _ does not count", has(HD, "img9.png") is False)
check("a saved scene comes back whole, klaus block included",
      et.read_diagram(HD, "img6.png") == sidecar(OLD, META))


# ------------------------------------------------------------ the editor

def fake_mw(col):
    return types.SimpleNamespace(
        col=col, pm=types.SimpleNamespace(profile={}), checkpoint=lambda *a: None,
        setupDialogGC=lambda d: None, reset=lambda: None, serverURL=lambda: "http://127.0.0.1:40000/",
        progress=types.SimpleNamespace(single_shot=lambda ms, fn, *a, **k: None),
        web=_Dummy(), state="deckBrowser", moveToState=lambda s: None)


class Note(dict):
    flushed: list = []
    MODEL = None

    def __init__(self, col=None, model=None, nid=None):
        super().__init__()
        self.tags, self.nid = [], nid

    def __missing__(self, key):
        return ""

    def model(self):
        return Note.MODEL

    def cards(self):
        return [types.SimpleNamespace(id=self.nid or 1)]

    def flush(self):
        Note.flushed.append(self.nid)


ngen.Note = Note


def io_model():
    return {"name": cfg.IO_MODEL_NAME, "tmpls": [{"name": cfg.IO_CARD_NAME}],
            "flds": [{"name": cfg.IO_FLDS[i], "sticky": False} for i in cfg.IO_FLDS_IDS]}


class Col:
    def __init__(self, media, returned=None, notes=None):
        self._conf = {"imgocc": copy.deepcopy(cfg.default_conf_syncd)}
        model = Note.MODEL = io_model()
        self.models = types.SimpleNamespace(
            by_name=lambda n: model if n == model["name"] else None,
            fieldNames=lambda m: [f["name"] for f in m["flds"]])
        self.returned = returned
        self.adds, self.added, self.removed = [], [], []
        self.notes = notes or {}
        self.media = types.SimpleNamespace(dir=lambda: media, add_file=self._add_file)
        self.db = types.SimpleNamespace(scalar=lambda *a: 1)

    def _add_file(self, p):
        self.adds.append(p)
        name = self.returned or os.path.basename(p)
        dest = os.path.join(self.media.dir(), name)
        if os.path.abspath(p) != os.path.abspath(dest):  # a file already in media keeps its name
            shutil.copy(p, dest)
        return name

    def get_config(self, key, default=None):
        return copy.deepcopy(self._conf[key]) if key in self._conf else default

    def set_config(self, key, val):
        self._conf[key] = copy.deepcopy(val)

    def addNote(self, note):
        self.added.append(note)

    def findNotes(self, query):
        return sorted(self.notes)

    def getNote(self, nid):
        return self.notes[nid]

    def remNotes(self, nids):
        self.removed += nids


class Window(QtWidgets.QWidget):
    deckChooser = types.SimpleNamespace(selectedId=lambda: 1)


def use_col(c):
    m = fake_mw(c)
    for mod in (cfg, ngen, add, ed_mod, main, io, et, utils):
        mod.mw = m
    return m


io._active = True
F = cfg.IO_FLDS


def edit_session(media, image="diagram-1.png", returned=None):
    """An occlusion note abc-ao-1..3 on media/image, opened in edit mode."""
    with open(os.path.join(media, image), "wb") as f:
        f.write(png_bytes(W, H))
    with open(os.path.join(media, "abc-ao-O.svg"), "w", encoding="utf-8") as f:
        f.write(OLD_SVG)
    notes = {}
    for nid in (101, 102, 103):
        n = Note(nid=nid)
        n[F["id"]] = "abc-ao-%d" % (nid - 100)
        n[F["im"]] = '<img src="%s">' % image
        n[F["om"]] = '<img src="abc-ao-O.svg">'
        notes[nid] = n
    c = Col(media, returned=returned, notes=notes)
    use_col(c)
    editor = types.SimpleNamespace(addMode=False, note=notes[101], parentWindow=Window(),
                                   loadNote=lambda: None, outerLayout=_Dummy(), web=_Dummy(),
                                   setupWeb=lambda: None)
    ok, r = attempt(io.occlude, editor)
    ia = getattr(editor, "imgoccadd", None)
    return c, editor, ia, getattr(ia, "imgoccedit", None), (ok, r)


def tab_texts(dialog):
    return [dialog.tab_widget.tabText(i) for i in range(dialog.tab_widget.count())]


section("edit mode without a diagram: IOE's two tabs (missing / unreadable sidecar)")
for label, body in (("no sidecar", None), ("invalid JSON", "{oops")):
    media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
    if body is not None:
        with open(os.path.join(media, "_diagram-1.png.excalidraw"), "w") as f:
            f.write(body)
    c, editor, ia, dlg, (ok, r) = edit_session(media)
    check(label + ": the editor opens in edit mode", ok and r is True and dlg is not None
          and ia.mode == "edit", str(r))
    if dlg is not None:
        check(label + ": no Draw tab", tab_texts(dlg) == ["&Masks Editor", "&Fields"]
              and dlg.draw_tab is None, str(tab_texts(dlg)))
        dlg.close()

section("edit mode with a diagram: the Draw tab, loaded with the saved scene")
media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
OLD_SIDE = sidecar(OLD, META)
with open(os.path.join(media, "_diagram-1.png.excalidraw"), "w", encoding="utf-8") as f:
    json.dump(OLD_SIDE, f)
c, editor, ia, dlg, (ok, r) = edit_session(media, returned="diagram-returned-2.png")
check("the editor opens in edit mode", ok and r is True and dlg is not None
      and getattr(ia, "mode", None) == "edit", str(r))
if dlg is not None:
    check("three tabs: Masks Editor, Fields, &Draw",
          tab_texts(dlg) == ["&Masks Editor", "&Fields", "&Draw"], str(tab_texts(dlg)))
    check("the Masks Editor stays current", dlg.tab_widget.currentIndex() == 0)
    check("Update and Add new stay enabled", dlg.edit_btn.isEnabled() and dlg.new_btn.isEnabled()
          and not dlg.add_blocked)
    tab = dlg.draw_tab
    check("the Draw tab is a DrawTab", isinstance(tab, et.DrawTab))
    if tab is None:  # red, but keep going: a bare tab so the checks below still run
        tab = et.DrawTab(dlg, ia.use_drawing)
    tab.web._onBridgeCmd("klausexcal:ready:" + base64.b64encode(b"{}").decode())
    loads = [js for js in tab.web.evals if js.startswith("klausExcalidraw.load(")]
    check("the page loads the saved scene once it is ready",
          len(loads) == 1 and json.loads(json.loads(loads[0][len("klausExcalidraw.load("):-2]))
          ["elements"] == OLD["elements"], str(loads)[:200])
    check("a freshly loaded scene is clean", tab.dirty is False)

    section("edit mode: Use drawing reads svg-edit's masks, then remaps them")
    LEFT1 = scene(("t1", {"text": "Heart muscle", "x": 20, "width": 160}), extra=(LEFT,))
    RES = result(LEFT1, -50, -30, W3, H3)
    sv = dlg.svg_edit
    sv.evals.clear()
    image0 = ia.image_path
    ok, r = attempt(ia.use_drawing, RES)
    check("use_drawing accepts the drawing", ok and r is True, str(r))
    check("...and asks svg-edit for its current masks",
          len(sv.callbacks) == 1 and "svgCanvasToString()" in sv.evals[-1], str(sv.evals))
    check("...changing nothing until they come back", ia.image_path == image0
          and not any("loadFromString" in js for js in sv.evals))
    # svg-edit answers: the note's masks, plus one drawn by hand this session.
    CUR = svg_edit_svg(W, H, [L1, L2, HAND, rect("svg_7", 300, 20, 30, 30)])
    new_side = None
    if sv.callbacks:
        ok, r = attempt(sv.callbacks[-1], CUR)
        check("the answer is taken without raising", ok, str(r))
        new_side = json.loads(ia.excal_sidecar) if ia.excal_sidecar else None
        ev = "\n".join(sv.evals)
        want = em.remap_masks(CUR, OLD_SIDE, OLD_SIDE["klaus"], new_side, new_side["klaus"],
                              W3, H3) if new_side and remap else None
        check("svg-edit loads remap_masks(current masks, saved scene, new scene)",
              want is not None and "svgEditor.loadFromString(%s)" % json.dumps(want) in ev, ev[:300])
        g = by_id(parse(want)[2]) if want else {}
        check("...keeping abc-ao-1..3 and the session's svg_7",
              sorted(g) == ["abc-ao-1", "abc-ao-2", "abc-ao-3", "svg_7"], str(sorted(g)))
        check("...the hand masks shifted by +100/+60",
              g and close(geom(g["abc-ao-3"][1]), (110, 280, 50, 40))
              and close(geom(g["svg_7"][1]), (400, 80, 30, 30)))
        check("then the new PNG as background, at its size",
              ev.find("loadFromString") < ev.find("setBackground") < ev.find("setResolution")
              and "svgCanvas.setResolution(%d, %d)" % (W3, H3) in ev)
        check("image_path is the new PNG (outside media)",
              ia.image_path != image0 and not ia.image_path.startswith(media))
        check("the Masks Editor is current", dlg.tab_widget.currentIndex() == 0)

    section("edit mode: Update keeps the note ids; the scene follows the new image name")
    side_files0 = [n for n in listing(media) if n.endswith(".excalidraw")]
    Note.flushed = []
    TIPS.clear()
    ASKS.clear()
    if new_side is not None:
        # svg-edit gives an id to every mask; here all of them have one already.
        ok, r = attempt(ia._onEditNotesButton, "Don't Change", want)
        check("Update runs", ok, str(r))
        check("IOE asks once: 0 deleted, 1 created (the session's svg_7)",
              len(ASKS) == 1 and "delete 0 card" in ASKS[0] and "create 1 new" in ASKS[0], str(ASKS))
        check("the three notes are updated in place, svg_7 added, none removed",
              sorted(Note.flushed) == [101, 102, 103] and len(c.added) == 1 and c.removed == [],
              "%s %s %s" % (Note.flushed, c.added, c.removed))
        check("...keeping their ids",
              [c.notes[n][F["id"]] for n in (101, 102, 103)] == ["abc-ao-1", "abc-ao-2", "abc-ao-3"])
        check("...and showing the new image under the name Anki returned",
              all(c.notes[n][F["im"]] == '<img src="diagram-returned-2.png" />'
                  or 'src="diagram-returned-2.png"' in c.notes[n][F["im"]] for n in (101, 102, 103)),
              str(c.notes[101][F["im"]]))
        new_file = os.path.join(media, "_diagram-returned-2.png.excalidraw")
        check("_diagram-returned-2.png.excalidraw is written",
              os.path.isfile(new_file), str(listing(media)))
        if os.path.isfile(new_file):
            data = json.load(open(new_file, encoding="utf-8"))
            check("...holding the new scene and origin",
                  data.get("elements") == LEFT1["elements"]
                  and data.get("klaus", {}).get("originX") == -50
                  and data.get("klaus", {}).get("originY") == -30)
        check("the old image's scene stays for the old image",
              "_diagram-1.png.excalidraw" in listing(media))
        check("the editor closed", not dlg.isVisible())
    dlg.close()

section("Review Focus 1: remap_masks' output straight into ngen's edit path")
media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
with open(os.path.join(media, "_diagram-1.png.excalidraw"), "w", encoding="utf-8") as f:
    json.dump(OLD_SIDE, f)
c, editor, ia, dlg, _r = edit_session(media)
if dlg is not None:
    Note.flushed = []
    ASKS.clear()
    out5 = em.remap_masks(OLD_SVG, OLD, META, NEW4, META, W, H)
    gen = ngen.IoGenHideAllRevealOne(editor, out5, os.path.join(media, "diagram-1.png"), ia.opref,
                                     [], {}, 1)
    done5 = []
    ok, r = attempt(gen.updateNotes, done5.append)
    check("updateNotes runs on it (every mask has an id)", ok and len(done5) == 1, str(r))
    check("IOE asks: 0 deleted, 1 created", len(ASKS) == 1 and "delete 0 card" in ASKS[0]
          and "create 1 new" in ASKS[0], str(ASKS))
    check("the three notes update in place, exactly one note added, none removed",
          sorted(Note.flushed) == [101, 102, 103] and len(c.added) == 1 and c.removed == [],
          "%s %s %s" % (Note.flushed, len(c.added), c.removed))
    check("...the old notes keep their ids, the new one is abc-ao-4",
          [c.notes[n][F["id"]] for n in (101, 102, 103)] == ["abc-ao-1", "abc-ao-2", "abc-ao-3"]
          and c.added and c.added[0][F["id"]] == "abc-ao-4",
          str([n[F["id"]] for n in c.added]))
    dlg.close()

section("edit mode: Update without using the drawing writes no scene")
media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
with open(os.path.join(media, "_diagram-1.png.excalidraw"), "w", encoding="utf-8") as f:
    json.dump(OLD_SIDE, f)
c, editor, ia, dlg, _r = edit_session(media)
if dlg is not None:
    Note.flushed = []
    ok, r = attempt(ia._onEditNotesButton, "Don't Change", OLD_SVG)
    check("the notes update", ok and sorted(Note.flushed) == [101, 102, 103], "%s %s" % (r, Note.flushed))
    check("...and the only scene is the old one",
          [n for n in listing(media) if n.endswith(".excalidraw")] == ["_diagram-1.png.excalidraw"],
          str(listing(media)))
    dlg.close()

section("a failed update (no masks left) writes no scene")
media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
with open(os.path.join(media, "_diagram-1.png.excalidraw"), "w", encoding="utf-8") as f:
    json.dump(OLD_SIDE, f)
c, editor, ia, dlg, _r = edit_session(media, returned="diagram-returned-3.png")
if dlg is not None:
    ia.excal_sidecar = json.dumps(sidecar(NEW3, META3))
    attempt(ia._onEditNotesButton, "Don't Change", svg_edit_svg(W, H, []))
    check("no new scene in media",
          [n for n in listing(media) if n.endswith(".excalidraw")] == ["_diagram-1.png.excalidraw"],
          str(listing(media)))
    dlg.close()


section("add mode: a repeat Use drawing remaps; the first one replaces")
media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
c = Col(media)
use_col(c)
editor = types.SimpleNamespace(addMode=True, note=Note(), parentWindow=Window(), loadNote=lambda: None)
attempt(io.occlude, editor, draw=True)
ia = getattr(editor, "imgoccadd", None)
dlg = getattr(ia, "imgoccedit", None)
if dlg is not None:
    sv = dlg.svg_edit
    ok, r = attempt(ia.use_drawing, result(OLD, 0, 0, W, H))
    check("the first use returns True", ok and r is True, str(r))
    check("...and loads the label masks at once, without reading svg-edit",
          sv.callbacks == [] and any("loadFromString" in js for js in sv.evals))
    first = ia.image_path
    sv.evals.clear()
    ok, r = attempt(ia.use_drawing, result(NEW3, -50, -30, W3, H3))
    check("the second use returns True and reads svg-edit's masks",
          ok and r is True and len(sv.callbacks) == 1, str(r))
    CUR2 = svg_edit_svg(W, H, [rect("svg_1", *OLD_LABELS["t1"]), rect("svg_2", *OLD_LABELS["t2"]),
                               rect("svg_3", 10, 220, 50, 40)])
    if sv.callbacks:
        attempt(sv.callbacks[-1], CUR2)
        ev = "\n".join(sv.evals)
        m = re.search(r"svgEditor\.loadFromString\((.*?)\);\n", ev, re.S)
        g = by_id(parse(json.loads(m.group(1)))[2]) if m else {}
        check("the hand mask drawn after the first use moves +100/+60",
              "svg_3" in g and close(geom(g["svg_3"][1]), (110, 280, 50, 40)), str(g)[:300])
        check("the label masks follow their labels",
              "svg_1" in g and close(geom(g["svg_1"][1]), want3["t1"]))
        check("the image is the second PNG", ia.image_path != first)

    section("add mode: a third use remaps against the second drawing")
    sv.evals.clear()
    sv.callbacks.clear()
    attempt(ia.use_drawing, result(NEW3, -50, -30, W3, H3))
    if sv.callbacks:
        CUR3 = svg_edit_svg(W3, H3, [rect("svg_1", *want3["t1"]), rect("svg_3", 110, 280, 50, 40)])
        attempt(sv.callbacks[-1], CUR3)
        m = re.search(r"svgEditor\.loadFromString\((.*?)\);\n", "\n".join(sv.evals), re.S)
        g = by_id(parse(json.loads(m.group(1)))[2]) if m else {}
        check("an unchanged scene leaves the masks where they are",
              "svg_3" in g and close(geom(g["svg_3"][1]), (110, 280, 50, 40))
              and close(geom(g["svg_1"][1]), want3["t1"]), str(g)[:300])

    section("dirty is cleared only when the carried-over masks land; one pending use at a time")
    sv.evals.clear()
    sv.callbacks.clear()
    TIPS.clear()
    tab = dlg.draw_tab
    tab.web._onBridgeCmd("klausexcal:dirty:" + base64.b64encode(b"{}").decode())
    tab.web._onBridgeCmd("klausexcal:occlude:" + base64.b64encode(
        json.dumps(result(NEW1, 0, 0, W, H)).encode()).decode())
    check("Use drawing pressed: svg-edit is asked once", len(sv.callbacks) == 1, str(len(sv.callbacks)))
    check("...and while that is pending the drawing is still dirty", tab.dirty is True)
    files_before = sorted(os.listdir(ia.draw_dir))
    ok, r = attempt(ia.use_drawing, result(NEW3, -50, -30, W3, H3))
    check("a second press while one is pending is refused (False)", ok and r is False, str(r))
    check("...with a tooltip, no second svg-edit read and no file written",
          len(TIPS) == 1 and len(sv.callbacks) == 1 and sorted(os.listdir(ia.draw_dir)) == files_before,
          str(TIPS))
    if sv.callbacks:
        attempt(sv.callbacks[-1], CUR2)
    check("once the masks land the drawing is clean", tab.dirty is False)
    ok, r = attempt(ia.use_drawing, result(NEW1, 0, 0, W, H))
    check("...and the next press is taken again", ok and r is True and len(sv.callbacks) == 2, str(r))
    tab.web._onBridgeCmd("klausexcal:dirty:" + base64.b64encode(b"{}").decode())
    if len(sv.callbacks) == 2:
        attempt(sv.callbacks[-1], CUR2)
    check("an edit reported while the masks were pending keeps the drawing dirty", tab.dirty is True)

    section("svg-edit answers nothing: a tooltip; the drawing stays unused and dirty")
    sv.evals.clear()
    sv.callbacks.clear()
    TIPS.clear()
    before = ia.image_path
    tab.web._onBridgeCmd("klausexcal:dirty:" + base64.b64encode(b"{}").decode())
    ok, r = attempt(ia.use_drawing, result(NEW1, 0, 0, W, H))
    if sv.callbacks:
        ok, r = attempt(sv.callbacks[-1], None)
        check("None is taken without raising", ok, str(r))
        check("a tooltip says so", len(TIPS) == 1, str(TIPS))
        check("nothing changed", ia.image_path == before
              and not any("loadFromString" in js for js in sv.evals))
        check("the Draw tab is still dirty (Use drawing still to do)", dlg.draw_tab.dirty is True)
        ok, r = attempt(ia.use_drawing, result(NEW1, 0, 0, W, H))
        check("...and Use drawing can be pressed again", ok and r is True and len(sv.callbacks) == 2, str(r))
        if len(sv.callbacks) == 2:
            attempt(sv.callbacks[-1], CUR2)
    else:
        check("the repeat use reads svg-edit", False)

    section("Change Image to a photo: the next drawing is not remapped against the old scene")
    photo = os.path.join(TMP, "photo.png")
    with open(photo, "wb") as f:
        f.write(png_bytes(400, 300))
    ia.getNewImage = lambda *a, **k: photo
    attempt(ia.onChangeImage)
    check("the old scene is forgotten", getattr(ia, "excal_scene", "x") is None)
    sv.evals.clear()
    sv.callbacks.clear()
    ok, r = attempt(ia.use_drawing, result(NEW3, -50, -30, W3, H3))
    check("the next Use drawing is the plain replace: no svg-edit read, masks loaded at once",
          ok and r is True and sv.callbacks == [] and any("loadFromString" in js for js in sv.evals),
          str(r))

    section("the editor closes before svg-edit answers: nothing happens")
    sv.evals.clear()
    sv.callbacks.clear()
    attempt(ia.use_drawing, result(NEW1, 0, 0, W, H))
    dlg.close()
    if sv.callbacks:
        TIPS.clear()
        ok, r = attempt(sv.callbacks[-1], CUR2)
        check("the late answer is dropped without raising", ok, str(r))
        check("...and loads nothing, with no tooltip",
              not any("loadFromString" in js for js in sv.evals) and TIPS == [], str(TIPS))
    else:
        check("the repeat use reads svg-edit", False)


section("io_ask: a continuation that raises becomes a tooltip, never escapes the slot")
dialogs = importlib.import_module("klaus_note.image_occlusion.dialogs")
dialogs.tooltip = tip
HOOKED: list = []
_hook = sys.excepthook
sys.excepthook = lambda *a: HOOKED.append(a[1])
try:
    def _boom(yes):
        raise KeyError("id")  # e.g. ngen proceed -> _finishUpdate on a mask without an id

    TIPS.clear()
    box = dialogs.io_ask(QtWidgets.QWidget(), "Proceed?", _boom)
    box.finished.emit(int(QtWidgets.QMessageBox.StandardButton.Yes.value))
    app.processEvents()
    check("nothing reaches the excepthook", HOOKED == [], str(HOOKED))
    check("...a tooltip says it failed", len(TIPS) == 1, str(TIPS))
finally:
    sys.excepthook = _hook

section("Update with no ask: an error in the continuation stays inside it")
media = tempfile.mkdtemp(prefix="io-media-", dir=TMP)
c, editor, ia, dlg, _r = edit_session(media)
if dlg is not None:
    HOOKED.clear()
    sys.excepthook = lambda *a: HOOKED.append(a[1])
    _after = ia._afterEditNotes
    ia._afterEditNotes = lambda *a: (_ for _ in ()).throw(RuntimeError("refresh failed"))
    try:
        TIPS.clear()
        dlg.svg_edit.callbacks.clear()
        ia.onEditNotesButton("Don't Change")
        ok, r = attempt(dlg.svg_edit.callbacks[-1], OLD_SVG) if dlg.svg_edit.callbacks else (False, "no read")
        check("svg-edit's answer runs the update without raising", ok, str(r))
        check("...the failure is a tooltip", any("error" in t.lower() for t in TIPS), str(TIPS))
    finally:
        ia._afterEditNotes = _after
        sys.excepthook = _hook
    dlg.close()

raise SystemExit(report())
