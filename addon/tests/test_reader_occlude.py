"""Image Occlusion 2/3: "Occlude this page" / "Occlude this region" in the reader.

The page renders the PNG at the same scale as the image copies and posts
``occlude-image`` (base64 JSON ``{png, page, region}``); ``PdfJsViewer``
validates it and calls ``on_occlude(png_bytes, page0, region)``;
``PdfSidebar`` writes ``<stem>.png`` under a fresh ``klaus-occlude-*`` temp
dir and hands it to ``image_occlusion.occlude``. ``PdfSidebar._editor`` is a
property whose setter pushes ``klausSetOcclusionEnabled(<editor present>)``
to the page (reader_host assigns it directly), and the page gets the value
again after every load. Review Focus 2: the same page occluded twice gives
a second distinct media name and the notes reference the name Anki returned.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_reader_occlude.py
"""
from __future__ import annotations

import base64
import copy
import importlib
import json
import os
import re
import shutil
import subprocess
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
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _qt_getattr(name):
    for module in (QtWidgets, QtCore, QtGui):
        if hasattr(module, name):
            return getattr(module, name)
    if name == "qconnect":
        return lambda signal, callback: signal.connect(callback)
    return _Dummy  # permissive, like the stubs (IOE's dialogs want sip)


shim.__getattr__ = _qt_getattr
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["klaus-test"])

TMP = tempfile.mkdtemp(prefix="klaus_reader_occlude_")
UF = os.path.join(TMP, "user_files")
os.makedirs(UF)
sys.modules["klausmate"].USER_FILES = UF
importlib.import_module("klausmate.settings").user_files_dir = UF

pj = importlib.import_module("klausmate.pdfjs_viewer")
rp = importlib.import_module("klausmate.reader_panel")
io = importlib.import_module("klausmate.image_occlusion")
HTML_PATH = os.path.join(ROOT, "klausmate", "web", "pdfjs_viewer.html")
html = open(HTML_PATH, encoding="utf-8").read()

NO_EDITOR_TIP = "Open the Add or Edit window to make an occlusion card"
PNG_HEAD = b"\x89PNG\r\n\x1a\n"
PNG = PNG_HEAD + b"fake-pixels"
TIPS: list = []
pj.tooltip = lambda text, *a, **k: TIPS.append(text)
rp.tooltip = lambda text, *a, **k: TIPS.append(text)


def b64json(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


def attempt(fn, *a):
    """(ok, result): a missing feature is a red check, not a crashed script."""
    try:
        return True, fn(*a)
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)


section("occlude_media_stem")
stem = getattr(rp, "occlude_media_stem", None)
check("occlude_media_stem exists", stem is not None)
if stem is not None:
    check("a page: <safe>-p<page+1>", stem("Heme", 4, False) == "Heme-p5")
    check("a region adds -region", stem("Heme", 4, True) == "Heme-p5-region")
    check("page 0 is p1", stem("Heme", 0, False) == "Heme-p1")

section("the page: menu items, the shared tip, the enabled flag")
check("the exact no-editor tip is in the page", NO_EDITOR_TIP in html)
check("...and in Python, the same string",
      getattr(pj, "NO_EDITOR_TIP", None) == NO_EDITOR_TIP)
check("the labels are verbatim",
      '"Occlude this page"' in html and '"Occlude this region"' in html)
check("the page exposes klausSetOcclusionEnabled",
      "window.klausSetOcclusionEnabled" in html)
check("the flag starts false (the page forgets it on every reload)",
      re.search(r"occlusionEnabled:\s*false", html) is not None)
check("occlude-image is posted as base64 JSON through postB64",
      'postB64("occlude-image"' in html)
check("no extra page.render: the occlusion PNG reuses renderRegionCanvas",
      html.count("page.render({") == 5)
check("both items are offered through occlusionItems in the context menu",
      "occlusionItems(" in html and html.count("occlusionItems(") >= 2)
m = re.search(r"/\* occlusion-items:start \*/(.*?)/\* occlusion-items:end \*/", html, re.S)
check("occlusionItems is delimited for extraction", m is not None)
NODE = shutil.which("node")
if m is not None and NODE:
    prog = (
        'const NO_EDITOR_TIP = %s;\n'
        'const occludeImage = (p, pm) => ({p, pm});\n'
        + m.group(1) +
        '\nconst pm = {page0: 2, x: 1, y: 2, w: 3, h: 4};\n'
        'const out = {\n'
        '  offNoMarquee: occlusionItems(7, null, false),\n'
        '  offMarquee: occlusionItems(7, pm, false),\n'
        '  onMarquee: occlusionItems(7, pm, true),\n'
        '  onNoMarquee: occlusionItems(7, null, true),\n'
        '};\n'
        'const strip = (items) => items.map(i => [i[0], i[2], i[1]()]);\n'
        'console.log(JSON.stringify(Object.fromEntries('
        'Object.entries(out).map(([k, v]) => [k, strip(v)]))));\n'
    ) % json.dumps(NO_EDITOR_TIP)
    run = subprocess.run([NODE, "-e", prog], capture_output=True, text=True)
    ok = run.returncode == 0
    got = json.loads(run.stdout) if ok else {}
    check("occlusionItems runs under node", ok, run.stderr[-300:])
    if ok:
        check("no editor, no marquee: only the page item, disabled",
              got["offNoMarquee"] == [["Occlude this page", True, {"p": 7, "pm": None}]],
              str(got["offNoMarquee"]))
        check("no editor, marquee up: both items, both disabled",
              [(i[0], i[1]) for i in got["offMarquee"]]
              == [("Occlude this page", True), ("Occlude this region", True)])
        check("editor, marquee up: both enabled; the region item carries the marquee",
              [(i[0], i[1]) for i in got["onMarquee"]]
              == [("Occlude this page", False), ("Occlude this region", False)]
              and got["onMarquee"][1][2]["pm"]["page0"] == 2)
        check("editor, no marquee: only the page item",
              [i[0] for i in got["onNoMarquee"]] == ["Occlude this page"])
elif m is not None:
    print("SKIP  occlusionItems behaviour (no node)")
check("a disabled item shows the tip on hover and on click",
      "mi.title = NO_EDITOR_TIP" in html and 'post("toast:" + btoa(NO_EDITOR_TIP))' in html)


section("PdfJsViewer: the bridge action")


class Stand:
    """A PdfJsViewer stand-in: _bridge_occlude_image only reads these."""

    def __init__(self, page_count=10):
        self._page_count = page_count
        self.calls = []
        self.on_occlude = lambda png, page, region: self.calls.append((png, page, region))


def occ(stand, payload):
    TIPS.clear()
    stand.calls.clear()
    return attempt(pj.PdfJsViewer._bridge_occlude_image, stand, payload)


handler = getattr(pj.PdfJsViewer, "_bridge_occlude_image", None)
check("PdfJsViewer has _bridge_occlude_image", handler is not None)
check("on_occlude is declared on the viewer", "on_occlude" in open(pj.__file__, encoding="utf-8").read())
if handler is not None:
    s = Stand()
    good = b64json({"png": base64.b64encode(PNG).decode(), "page": 4, "region": True})
    ok, _ = occ(s, good)
    check("a good payload calls on_occlude(png_bytes, 4, True)",
          ok and s.calls == [(PNG, 4, True)] and TIPS == [], f"{s.calls} {TIPS}")
    ok, _ = occ(s, b64json({"png": base64.b64encode(PNG).decode(), "page": 0, "region": False}))
    check("page 0, region False passes through", s.calls == [(PNG, 0, False)], str(s.calls))
    parse = pj.parse_bridge("klausmate_pdfjs:occlude-image:" + good)
    check("parse_bridge routes occlude-image", parse == ("occlude-image", good))
    png_b64 = base64.b64encode(PNG).decode()
    bad = {
        "not base64 json": "!!!not-base64!!!",
        "not a dict": b64json([1, 2]),
        "no png": b64json({"page": 1, "region": False}),
        "png not a string": b64json({"png": 5, "page": 1, "region": False}),
        "png not base64": b64json({"png": "@@@", "page": 1, "region": False}),
        "empty bytes": b64json({"png": "", "page": 1, "region": False}),
        "non-PNG bytes": b64json({"png": base64.b64encode(b"GIF89a....").decode(),
                                  "page": 1, "region": False}),
        "negative page": b64json({"png": png_b64, "page": -1, "region": False}),
        "page past the count": b64json({"png": png_b64, "page": 10, "region": False}),
        "huge int page": b64json({"png": png_b64, "page": 10 ** 400, "region": False}),
        "bool page": b64json({"png": png_b64, "page": True, "region": False}),
        "string page": b64json({"png": png_b64, "page": "3", "region": False}),
        "fractional page": b64json({"png": png_b64, "page": 1.5, "region": False}),
        "region not a bool": b64json({"png": png_b64, "page": 1, "region": "false"}),
        "region missing": b64json({"png": png_b64, "page": 1}),
    }
    for label, payload in bad.items():
        ok, res = occ(s, payload)
        check(f"{label}: tooltip, no call, no raise",
              ok and s.calls == [] and len(TIPS) == 1, f"{res} {s.calls} {TIPS}")
    s2 = Stand(page_count=0)  # count not reported yet: no upper bound to apply
    ok, _ = occ(s2, good)
    check("an unknown page count does not reject a good page", s2.calls == [(PNG, 4, True)])
    s3 = Stand()
    s3.on_occlude = None
    ok, _ = occ(s3, good)
    check("no hook wired: the no-editor tooltip, no raise",
          ok and TIPS == [NO_EDITOR_TIP], f"{ok} {TIPS}")
    # The real _on_bridge wraps handlers; one that raises must never abort Anki.
    s4 = Stand()

    def boom(*a):
        raise RuntimeError("hook failed")

    s4.on_occlude = boom
    s4._on_bridge = pj.PdfJsViewer._on_bridge.__get__(s4)
    s4._bridge_occlude_image = pj.PdfJsViewer._bridge_occlude_image.__get__(s4)
    ok, _ = attempt(s4._on_bridge, "klausmate_pdfjs:occlude-image:" + good)
    check("a hook that raises is caught by _on_bridge", ok)


section("PdfJsViewer: the enabled flag is pushed now and after each load")
EVALS: list = []


class Flag:
    def __init__(self):
        self._occlusion_enabled = False
        self._page_loaded = True
        self._hold_scroll = True
        self._scroll_pos = 0

    def _eval(self, js):
        EVALS.append(js)

    def _claim_shortcuts(self):
        pass

    def _push_annotations(self):
        pass


f = Flag()
setter = getattr(pj.PdfJsViewer, "set_occlusion_enabled", None)
check("PdfJsViewer has set_occlusion_enabled", setter is not None)
if setter is not None:
    f._push_occlusion_enabled = pj.PdfJsViewer._push_occlusion_enabled.__get__(f)
    f.set_occlusion_enabled = setter.__get__(f)
    EVALS.clear()
    f.set_occlusion_enabled(True)
    check("enabling evals klausSetOcclusionEnabled(true)",
          len(EVALS) == 1 and "klausSetOcclusionEnabled(true)" in EVALS[0], str(EVALS))
    EVALS.clear()
    f.set_occlusion_enabled(False)
    check("disabling evals klausSetOcclusionEnabled(false)",
          len(EVALS) == 1 and "klausSetOcclusionEnabled(false)" in EVALS[0], str(EVALS))
    f.set_occlusion_enabled(True)
    EVALS.clear()
    pj.PdfJsViewer._bridge_ready(f, "")  # the page just (re)loaded and forgot
    check("the page's ready pushes the stored value again",
          any("klausSetOcclusionEnabled(true)" in e for e in EVALS), str(EVALS))
    check("the eval is guarded: a page that lacks the function is a no-op",
          all("window.klausSetOcclusionEnabled &&" in e for e in EVALS if "Occlusion" in e))


section("PdfSidebar: _editor is a property that pushes")


class FakeJs(QtWidgets.QWidget):
    def __init__(self, on_page_changed=None, parent=None):
        super().__init__(parent)
        self.pushed = []
        self.on_count = self.on_stale = self.on_selection = self.on_occlude = None

    def set_occlusion_enabled(self, enabled):
        self.pushed.append(enabled)

    def clear_document(self):
        pass

    def cleanup(self):
        pass


pj.PdfJsViewer, pj.PDFJS_AVAILABLE = FakeJs, True
sb = rp.PdfSidebar(None)
check("PdfSidebar._editor is a property", isinstance(getattr(rp.PdfSidebar, "_editor", None), property))
v = sb._viewer
check("built without an editor: the viewer is told False (or never told, default False)",
      v.pushed in ([], [False]), str(v.pushed))
v.pushed.clear()
ed = types.SimpleNamespace(addMode=True)
sb._editor = ed
check("assigning _editor on an instance pushes True", v.pushed == [True], str(v.pushed))
check("...and reads back", sb._editor is ed)
sb._editor = None
check("clearing it pushes False", v.pushed == [True, False], str(v.pushed))
check("...and reads back None", sb._editor is None)
sb2 = rp.PdfSidebar(ed)
check("a sidebar built WITH an editor tells its viewer True",
      sb2._viewer.pushed[-1:] == [True], str(sb2._viewer.pushed))
sb2.cleanup()
check("the viewer's on_occlude is the sidebar's handler",
      getattr(sb._viewer, "on_occlude", None) == getattr(sb, "_on_occlude", "missing"))
rh_src = open(os.path.join(ROOT, "klausmate", "reader_host.py"), encoding="utf-8").read()
check("reader_host still assigns r._editor directly (the setter is the seam)",
      "r._editor = " in rh_src)


section("PdfSidebar: the occlude handler")


def occ_sb(*a):
    return attempt(lambda: sb._on_occlude(*a))


CALLS: list = []
io.occlude = lambda editor, path, svg=None: CALLS.append((editor, path, svg)) or True
sb._name = "Heme"
sb._editor = None
TIPS.clear()
occ_sb(PNG, 4, False)
check("no editor: the exact tooltip, and occlude is never called",
      TIPS == [NO_EDITOR_TIP] and CALLS == [], f"{TIPS} {CALLS}")

sb._editor = ed
TIPS.clear()
ok, res = occ_sb(PNG, 4, False)
check("with an editor, occlude(editor, path, None) is called once",
      ok and len(CALLS) == 1 and CALLS[0][0] is ed and CALLS[0][2] is None, f"{res} {CALLS}")
path = CALLS[0][1] if CALLS else ""
check("the PNG is <tmp>/<stem>.png, named by occlude_media_stem",
      os.path.basename(path) == "Heme-p5.png", path)
check("...in a fresh klaus-occlude- temp dir",
      os.path.basename(os.path.dirname(path)).startswith("klaus-occlude-")
      and os.path.dirname(os.path.dirname(path)) == os.path.realpath(tempfile.gettempdir())
      or os.path.dirname(os.path.dirname(path)) == tempfile.gettempdir(), path)
check("...with exactly the bytes the page sent", os.path.isfile(path) and open(path, "rb").read() == PNG)
check("...never under user_files", not os.path.realpath(path).startswith(os.path.realpath(UF)))
check("no tooltip on success", TIPS == [], str(TIPS))
CALLS.clear()
occ_sb(PNG, 2, True)
check("a region is <safe>-p<n>-region.png",
      CALLS and os.path.basename(CALLS[0][1]) == "Heme-p3-region.png", str(CALLS))
CALLS.clear()
occ_sb(PNG, 4, False)
check("each call gets its own temp dir",
      len(CALLS) == 1 and os.path.dirname(CALLS[0][1]) != os.path.dirname(path))

sb._name = None
CALLS.clear()
TIPS.clear()
ok, _ = occ_sb(PNG, 0, False)
check("no document: nothing is written and nothing is called (no raise)", ok and CALLS == [])
sb._name = "Heme"

io._active = False
io.occlude = lambda editor, path, svg=None: False  # the real one's answer while the guard is tripped
TIPS.clear()
occ_sb(PNG, 4, False)
check("occlude False with the conflict guard tripped: the conflict tooltip",
      TIPS == [io.CONFLICT_TOOLTIP], str(TIPS))
io._active = True
TIPS.clear()
occ_sb(PNG, 4, False)
check("occlude False otherwise: still a tooltip, never silent", len(TIPS) == 1, str(TIPS))
io._active = False


section("Review Focus 2: the same page occluded twice")
cfg = importlib.import_module("klausmate.image_occlusion.config")
ngen = importlib.import_module("klausmate.image_occlusion.ngen")
FIX = os.path.join(ROOT, "tests", "fixtures", "io")
O_SVG = open(os.path.join(FIX, "abc-ao-O.svg"), encoding="utf-8").read()


class Note(dict):
    def __init__(self, col=None, model=None, nid=None):
        super().__init__()
        self.tags, self.nid = [], nid


ngen.Note = Note
MEDIA = tempfile.mkdtemp(prefix="io-media-")
ADDS: list = []


def add_file(p):
    """Anki's media.add_file: a name taken by different bytes comes back
    renamed. The second add of Heme-p5.png answers Heme-p5-1.png."""
    ADDS.append(p)
    name = os.path.basename(p) if len(ADDS) == 1 else "Heme-p5-1.png"
    shutil.copy(p, os.path.join(MEDIA, name))
    return name


class Col:
    def __init__(self):
        self._conf = {"imgocc": copy.deepcopy(cfg.default_conf_syncd)}
        self.media = types.SimpleNamespace(dir=lambda: MEDIA, add_file=add_file)
        self.added = []
        self.models = types.SimpleNamespace(by_name=lambda n: {
            "name": cfg.IO_MODEL_NAME, "tmpls": [{"name": cfg.IO_CARD_NAME}],
            "flds": [{"name": cfg.IO_FLDS[i], "sticky": False} for i in cfg.IO_FLDS_IDS]})

    def get_config(self, key, default=None):
        return copy.deepcopy(self._conf[key]) if key in self._conf else default

    def set_config(self, key, val):
        self._conf[key] = copy.deepcopy(val)

    def addNote(self, note):
        self.added.append(note)


col = Col()
mw = types.SimpleNamespace(col=col, pm=types.SimpleNamespace(profile={}),
                           checkpoint=lambda *a: None)
for mod in (cfg, ngen):
    mod.mw = mw
ngen.tooltip = lambda *a, **k: None

# Two renders of page 5, as the reader would hand them over (different pixels).
CALLS.clear()
io.occlude = lambda editor, path, svg=None: CALLS.append((editor, path, svg)) or True
sb._editor = ed
occ_sb(PNG + b"first", 4, False)
occ_sb(PNG + b"second", 4, False)
paths = [c[1] for c in CALLS]
check("both runs asked for the same media name", len(paths) == 2
      and {os.path.basename(p) for p in paths} == {"Heme-p5.png"}, str(paths))
check("...from two different files", len(paths) == 2 and paths[0] != paths[1])

uuids = iter(["u1", "u2"])
_uuid4 = ngen.uuid.uuid4
ngen.uuid.uuid4 = lambda: next(uuids)
try:
    for p in paths:
        gen = ngen.IoGenHideAllRevealOne(None, O_SVG, p, {"tags": [], "did": 1}, [], {}, 1)
        attempt(gen.generateNotes)
finally:
    ngen.uuid.uuid4 = _uuid4
im = cfg.IO_FLDS["im"]
imgs = [n.get(im) for n in col.added]
check("four notes: two masks, two runs", len(col.added) == 4, str(imgs))
check("first run's notes show the name Anki returned (Heme-p5.png)",
      imgs[:2] == ['<img src="Heme-p5.png" />'] * 2, str(imgs))
check("second run's notes show the returned Heme-p5-1.png, not the requested name",
      imgs[2:] == ['<img src="Heme-p5-1.png" />'] * 2, str(imgs))
check("both files exist in media under their returned names",
      sorted(os.listdir(MEDIA))[:2] == ["Heme-p5-1.png", "Heme-p5.png"]
      or {"Heme-p5-1.png", "Heme-p5.png"} <= set(os.listdir(MEDIA)), str(os.listdir(MEDIA)))

raise SystemExit(report())
