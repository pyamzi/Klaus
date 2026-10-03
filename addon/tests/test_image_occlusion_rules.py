"""Image Occlusion 1/3: the vendored IOE port follows Klaus's rules.

K-114 (no exec, no exec-internally helpers), no attribute shadowing a Qt
method, gui_hooks instead of legacy hooks or monkey-patches, collection
config through get_config/set_config, and web assets served from
/_addons/<addon>/image_occlusion/web/. Every blocking ask is now a
callback: the code after the ask runs only when the answer arrives.

Run: env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_image_occlusion_rules.py
"""
import ast
import copy
import glob
import os
import shutil
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import _permissive_module, check, install, report, section  # noqa: E402

PKG = os.path.join(ROOT, "klaus_note", "image_occlusion")
FILES = sorted(glob.glob(os.path.join(PKG, "*.py")))

# The harness purges klaus_note/__pycache__ only; drop this subpackage's too.
sys.dont_write_bytecode = True
_prefix = getattr(sys, "pycache_prefix", None)
for _root in [os.path.join(PKG, "__pycache__")] + (
        [os.path.join(_prefix, PKG.lstrip(os.sep), "__pycache__")] if _prefix else []):
    shutil.rmtree(_root, ignore_errors=True)


# ------------------------------------------------------------ AST rules

def _trees():
    for p in FILES:
        with open(p, encoding="utf-8") as f:
            yield os.path.basename(p), ast.parse(f.read(), p)


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


BANNED_NAMES = {"askUser", "askUserDialog", "getText", "getOnlyText", "chooseList",
                "addHook", "remHook", "runHook", "wrap"}
BANNED_STATICS = {"QMessageBox.question", "QMessageBox.information",
                  "QMessageBox.critical", "QMessageBox.warning"}
SHADOWS = {"parent", "window", "close", "show", "hide", "font"}

violations = {k: [] for k in ("exec", "banned", "static", "shadow", "showAnswer",
                              "col.conf", "webexports")}
for fname, tree in _trees():
    for node in ast.walk(tree):
        where = "%s:%s" % (fname, getattr(node, "lineno", "?"))
        if isinstance(node, ast.Call):
            d = _dotted(node.func)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "exec" \
                    and "menu" not in d.lower():
                violations["exec"].append(where)
            if d in BANNED_STATICS or d.startswith("QInputDialog.get") \
                    or d.endswith(".getColor") or d == "QColorDialog.getColor":
                violations["static"].append(where + " " + d)
            if d.endswith("setWebExports"):
                violations["webexports"].append(where)
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in BANNED_NAMES:
                violations["banned"].append(where + " " + name)
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name in BANNED_NAMES:
                    violations["banned"].append(where + " import " + a.name)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Attribute) and sub.attr in SHADOWS \
                            and isinstance(sub.ctx, ast.Store):
                        violations["shadow"].append(where + " ." + sub.attr)
                    if isinstance(sub, ast.Attribute) and _dotted(sub) == "Reviewer._showAnswer":
                        violations["showAnswer"].append(where)
        if isinstance(node, ast.Attribute) and node.attr == "conf" \
                and isinstance(node.value, ast.Attribute) and node.value.attr == "col":
            violations["col.conf"].append(where)

section("AST rules over every image_occlusion/*.py")
check("the scan read the package (%d files)" % len(FILES), len(FILES) >= 15)
check("no .exec() on a dialog or message box", not violations["exec"], str(violations["exec"]))
check("no askUser/getText/getOnlyText/chooseList, no addHook/remHook/runHook, no anki.hooks.wrap",
      not violations["banned"], str(violations["banned"]))
check("no static QMessageBox.question/information/critical/warning, QInputDialog.getX or "
      "QColorDialog.getColor", not violations["static"], str(violations["static"]))
check("no instance attribute named parent/window/close/show/hide/font",
      not violations["shadow"], str(violations["shadow"]))
check("no assignment to Reviewer._showAnswer", not violations["showAnswer"],
      str(violations["showAnswer"]))
check("no mw.col.conf access (config goes through get_config/set_config)",
      not violations["col.conf"], str(violations["col.conf"]))
check("no setWebExports call (KlausNote has one, in klaus_note/__init__.py)",
      not violations["webexports"], str(violations["webexports"]))


# ------------------------------------------------------------ imports

install()
for _name in ("aqt.addcards", "aqt.editcurrent", "aqt.reviewer", "anki.notes",
              "anki.errors", "anki.config"):
    _permissive_module(_name)

import importlib  # noqa: E402

M = {}
for _n in ("consts", "config", "dialogs", "editor", "options", "ngen", "nconvert",
           "add", "web", "main"):
    M[_n] = importlib.import_module("klaus_note.image_occlusion." + _n)


def set_mw(fake):
    """Every module that bound aqt.mw at import gets the fake."""
    for mod in M.values():
        if hasattr(mod, "mw"):
            mod.mw = fake


section("web assets are served from the subpackage")
web = M["web"]
check("MODULE_ADDON names the subpackage path",
      M["consts"].MODULE_ADDON == "klaus_note/image_occlusion", M["consts"].MODULE_ADDON)
check("editor css/js read /_addons/klaus_note/image_occlusion/web/",
      '/_addons/klaus_note/image_occlusion/web/editor.css' in web.editor_html
      and '/_addons/klaus_note/image_occlusion/web/editor.js' in web.editor_html)
check("reviewer js reads /_addons/klaus_note/image_occlusion/web/",
      '/_addons/klaus_note/image_occlusion/web/reviewer.js' in web.reviewer_html)


# ------------------------------------------------------------ config

class FakeCol:
    def __init__(self, conf=None, model=None):
        self._conf = copy.deepcopy(conf or {})
        self.set_calls = []
        self._model = model
        self.removed = []
        self.notes = {}
        self.models = types.SimpleNamespace(
            by_name=lambda name: self._model,
            fieldNames=lambda m: [f["name"] for f in m["flds"]])
        self.media = types.SimpleNamespace(dir=lambda: "/nonexistent", add_file=lambda p: p)

    def get_config(self, key, default=None):  # Anki's contract: default on a miss
        return copy.deepcopy(self._conf[key]) if key in self._conf else default

    def set_config(self, key, val):
        self.set_calls.append(key)
        self._conf[key] = copy.deepcopy(val)

    def remNotes(self, nids):
        self.removed.append(list(nids))


def fake_mw(col):
    return types.SimpleNamespace(col=col, pm=types.SimpleNamespace(profile={}),
                                 checkpoint=lambda *a: None)


cfg = M["config"]
section("config: collection config through get_config/set_config")
col = FakeCol()
set_mw(fake_mw(col))
got = cfg.getSyncedConfig()
check("a missing imgocc config is created with IOE's default dict",
      col._conf.get("imgocc") == cfg.default_conf_syncd and got == cfg.default_conf_syncd)
got["skip"].append("x")
check("...as a copy: editing what came back does not edit the module default",
      cfg.default_conf_syncd["skip"] == [cfg.IO_FLDS["e1"], cfg.IO_FLDS["e2"]])

col = FakeCol({"image_occlusion_conf": {"initFill[color]": "111111", "mask_fill_color": "222222"}})
set_mw(fake_mw(col))
cfg.getSyncedConfig()
check("the IO 2.0 upgrade still copies its two colours",
      col._conf["imgocc"]["ofill"] == "111111" and col._conf["imgocc"]["qfill"] == "222222")

old = {"version": 1.0, "ofill": "ABCDEF", "flds": dict(cfg.IO_FLDS)}
col = FakeCol({"imgocc": old})
set_mw(fake_mw(col))
got = cfg.getSyncedConfig()
check("an older version gains the missing keys, keeps its own, and is bumped",
      got["ofill"] == "ABCDEF" and got["fsize"] == 24
      and got["version"] == cfg.default_conf_syncd["version"]
      and col._conf["imgocc"] == got and col.set_calls == ["imgocc"])
col.set_calls.clear()
cfg.getSyncedConfig()
check("a current config is read without a write", col.set_calls == [])

col = FakeCol()
m = fake_mw(col)
m.pm.profile["imgocc"] = {"version": 1.0, "hotkey": "Ctrl+K"}
set_mw(m)
loc = cfg.getLocalConfig()
check("profile settings stay in mw.pm.profile['imgocc']; an upgrade keeps the user's "
      "hotkey and adds the missing dir", loc is m.pm.profile["imgocc"]
      and loc["hotkey"] == "Ctrl+K" and loc["dir"] == cfg.IO_HOME
      and loc["version"] == cfg.default_conf_local["version"])


# ------------------------------------------------------------ main: reviewer hooks

main = M["main"]


class Point:
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class Card:
    def __init__(self, name):
        self._name = name

    def note_type(self):
        return {"name": self._name}


evals, reads = [], []


def _page():
    reads.append(1)
    return types.SimpleNamespace(scrollPosition=lambda: Point(3, 40))


main.mw = types.SimpleNamespace(reviewer=types.SimpleNamespace(
    web=types.SimpleNamespace(page=_page, eval=evals.append)))
io, plain = Card(cfg.IO_MODEL_NAME), Card("Basic")

section("main: reviewer scroll position kept across showing the answer, via hooks")
check("the two hooks exist", callable(getattr(main, "on_card_will_show", None))
      and callable(getattr(main, "on_reviewer_did_show_answer", None)))
if callable(getattr(main, "on_card_will_show", None)):
    check("card_will_show returns the text unchanged",
          main.on_card_will_show("A", io, "reviewAnswer") == "A")
    check("...and captured the scroll position before the answer rendered", reads == [1])
    main.on_reviewer_did_show_answer(io)
    check("reviewer_did_show_answer restores it", evals == ["window.scrollTo(3, 40);"], str(evals))
    main.on_reviewer_did_show_answer(io)
    check("...once: a second show-answer without a capture does nothing", len(evals) == 1)
    del evals[:], reads[:]
    check("a non-IO card is left alone: text unchanged, nothing read",
          main.on_card_will_show("B", plain, "reviewAnswer") == "B" and reads == [])
    main.on_reviewer_did_show_answer(plain)
    check("...and nothing restored", evals == [])
    main.on_card_will_show("Q", io, "reviewQuestion")
    main.on_card_will_show("P", io, "previewAnswer")
    main.on_reviewer_did_show_answer(io)
    check("only kind == 'reviewAnswer' captures (question, previewer ignored)",
          reads == [] and evals == [])
    main.on_card_will_show("A", io, "reviewAnswer")
    main.on_reviewer_did_show_answer(plain)
    check("a capture is dropped, not restored, if the shown answer is a non-IO card",
          evals == [])
    main.on_reviewer_did_show_answer(io)
    check("...and does not leak into the next answer", evals == [])


class Hook(list):
    pass


gh = sys.modules["aqt.gui_hooks"]
for _h in ("card_will_show", "reviewer_did_show_answer", "browser_menus_did_init",
           "profile_did_open", "editor_did_init_buttons", "editor_will_show_context_menu",
           "editor_did_load_note", "state_shortcuts_will_change", "main_window_did_init",
           "profile_will_close", "webview_will_set_content"):
    setattr(gh, _h, Hook())
main.setup_main(types.SimpleNamespace(addonManager=types.SimpleNamespace(
    setConfigAction=lambda *a: None), form=types.SimpleNamespace(
    menuTools=types.SimpleNamespace(addAction=lambda a: None),
    menuHelp=types.SimpleNamespace(addAction=lambda a: None))))
check("setup_main registers both reviewer hooks",
      getattr(main, "on_card_will_show", None) in gh.card_will_show
      and getattr(main, "on_reviewer_did_show_answer", None) in gh.reviewer_did_show_answer)
check("setup_main registers the Browse conversion menu through browser_menus_did_init "
      "(nconvert no longer registers itself on import)",
      gh.browser_menus_did_init == [M["nconvert"].setupMenu])


# ------------------------------------------------------------ asks become callbacks

class Asks(list):
    """Stands in for io_ask: records (parent, text, on_answer, kwargs)."""

    def __call__(self, parent, text, on_answer, title="", **kw):
        self.append(types.SimpleNamespace(parent=parent, text=text, on_answer=on_answer,
                                          title=title, kw=kw))


section("editor: closing with unsaved changes asks through io_ask, closes only on yes")
ed_mod = M["editor"]
rejected = []
_orig_reject = ed_mod.QDialog.__dict__.get("reject")
ed_mod.QDialog.reject = lambda self: rejected.append(self)
asks = Asks()
ed_mod.io_ask = asks
ed = object.__new__(ed_mod.ImgOccEdit)
ed.svg_edit, ed.draw_tab = object(), None  # open, no Draw tab
# Klaus (R20): a yes closes through close(), so closeEvent's cleanup runs.
ed.close = lambda: rejected.append(ed)
ed._input_modified = lambda: False
ed._on_reject_callback(True)
check("nothing changed: closes at once, asks nothing", rejected == [ed] and asks == [])
del rejected[:]
ed._input_modified = lambda: True
ed._on_reject_callback(True)
check("changed fields: asks first and does not close yet", len(asks) == 1 and rejected == [])
check("IOE's question text and title are unchanged",
      asks and asks[0].text == "Are you sure you want to close the window? This will "
      "discard any unsaved changes." and asks[0].title == "Exit Image Occlusion?"
      and asks[0].parent is ed)
asks[0].on_answer(False)
check("answer No: stays open", rejected == [])
ed._on_reject_callback(False)
asks[1].on_answer(True)
check("unsaved masks (undo stack not empty), answer Yes: closes", rejected == [ed])
if _orig_reject is None:
    del ed_mod.QDialog.reject
else:
    ed_mod.QDialog.reject = _orig_reject


section("ngen: the delete confirm (~397) continues only through the callback")
ngen = M["ngen"]
asks = Asks()
ngen.io_ask = asks
col = FakeCol()
set_mw(fake_mw(col))
from xml.dom import minidom  # noqa: E402

svg = ('<svg width="400" height="300"><g><title>Labels</title></g>'
       '<g><title>Masks</title><rect id="abc-ao-1" width="10" height="10"/></g></svg>')
gen = object.__new__(ngen.IoGenHideAllRevealOne)
gen.opref = {"uniq_id": "abc", "occl_tp": "ao"}
gen.occl_id = "abc-ao"
gen.new_svg = svg
gen.ed = types.SimpleNamespace(imgoccadd=types.SimpleNamespace(imgoccedit="EDIT-DIALOG"))
gen._getMnodesAndSetIds(True)
gen.nids = {"abc-ao-1": 11, "abc-ao-2": 22}  # abc-ao-2's mask was deleted
mlayer = minidom.parseString(svg).documentElement.childNodes[-1]
done = []
gen._deleteAndIdNotes(mlayer, lambda *counts: done.append(counts))
check("a deletion asks (parent = the IO editor) and nothing is deleted yet",
      len(asks) == 1 and asks[0].parent == "EDIT-DIALOG" and col.removed == [] and done == [])
check("IOE's confirm text and title are unchanged",
      asks and "This will <b>delete 1 card(s)</b> and <b>create 0 new one(s)</b>." in asks[0].text
      and "Would you still like to proceed?" in asks[0].text
      and asks[0].title == "Please confirm action" and asks[0].kw.get("help") == "edit")
asks[0].on_answer(False)
check("answer No: no delete, no continuation", col.removed == [] and done == [])
asks[0].on_answer(True)
check("answer Yes: the note is deleted and the update continues with (del, new) counts",
      col.removed == [[22]] and done == [(1, 0)], "%r %r" % (col.removed, done))

del asks[:], done[:]
gen.nids = {"abc-ao-1": 11}
gen._getMnodesAndSetIds(True)
gen._deleteAndIdNotes(mlayer, lambda *counts: done.append(counts))
check("nothing deleted or added: no ask, the update continues at once",
      asks == [] and done == [(0, 0)])

# updateNotes threads the continuation through to its caller.
gen2 = object.__new__(ngen.IoGenHideAllRevealOne)
gen2.opref = {"uniq_id": "abc", "occl_tp": "ao"}
gen2.new_svg = svg
gen2.ed = gen.ed
gen2._findAllNotes = lambda: setattr(gen2, "nids", {"abc-ao-1": 11, "abc-ao-2": 22})
finished = []
gen2._finishUpdate = lambda *a: finished.append(a) or "default"
del asks[:]
states = []
ret = gen2.updateNotes(states.append)
check("updateNotes waits on the ask: its caller's continuation has not run",
      len(asks) == 1 and states == [] and finished == [])
asks[0].on_answer(True)
check("...and runs the rest, then hands the state to the caller, after Yes",
      len(finished) == 1 and states == ["default"], "%r %r" % (finished, states))


section("add: the edit flow waits for updateNotes' callback")
add = M["add"]
calls = []


class FakeGen:
    def __init__(self, *a):
        pass

    def updateNotes(self, on_done=None):
        calls.append(on_done)


ia = object.__new__(add.ImgOccAdd)
ia.imgoccedit = types.SimpleNamespace(close=lambda: calls.append("close"))
ia.opref = {"did": 1, "occl_tp": "ao"}
ia.ed = None
ia.image_path = "x.png"
ia.getUserInputs = lambda dialog, edit=False: ({}, [])
_genByKey = add.genByKey
add.genByKey = lambda *a: FakeGen
ia._onEditNotesButton("Don't Change", svg)
add.genByKey = _genByKey
check("the editor stays open until updateNotes calls back",
      len(calls) == 1 and callable(calls[0]) and "close" not in calls)


section("nconvert: the conversion confirm (~253) continues only through the callback")
nconvert = M["nconvert"]
asks = Asks()
nconvert.io_ask = asks
converted = []


class FakeConverter:
    def __init__(self, browser):
        converted.append("init")

    def convertNotes(self, nids):
        converted.append(list(nids))


RealConverter = nconvert.ImgOccNoteConverter
nconvert.ImgOccNoteConverter = FakeConverter
prog = []
bmw = types.SimpleNamespace(
    progress=types.SimpleNamespace(start=lambda: prog.append("start"),
                                   finish=lambda: prog.append("finish")),
    checkpoint=lambda *a: None, reset=lambda: None, col=types.SimpleNamespace(reset=lambda: None))
browser = types.SimpleNamespace(
    mw=bmw, selectedNotes=lambda: [5, 6],
    model=types.SimpleNamespace(beginReset=lambda: None, endReset=lambda: None))
nconvert.onIoConvert(browser)
check("asks with IOE's text, default No, parent = Browse; converts nothing yet",
      len(asks) == 1 and asks[0].text == M["dialogs"].dialog_msg["question_nconvert"]
      and asks[0].kw.get("default_no") is True and asks[0].parent is browser
      and asks[0].title == "Please confirm action" and converted == [] and prog == [])
asks[0].on_answer(False)
check("answer No: nothing converted", converted == [] and prog == [])
asks[0].on_answer(True)
check("answer Yes: the selected notes are converted inside progress",
      converted == ["init", [5, 6]] and prog == ["start", "finish"], "%r %r" % (converted, prog))


section("nconvert: _saveMask writes the mask under the note id (IOE's node_id NameError, R5)")
import tempfile  # noqa: E402

media = tempfile.mkdtemp(prefix="io-media-")
conv = object.__new__(RealConverter)
conv._media_path = media
try:
    name = conv._saveMask("<svg>ü</svg>", "abc-ao", "O")
    err = None
except Exception as e:  # noqa: BLE001
    name, err = None, e
check("_saveMask does not raise", err is None, repr(err))
check("...and writes <note_id>-<type>.svg into the media folder, UTF-8",
      name == "abc-ao-O.svg" and os.path.isfile(os.path.join(media, "abc-ao-O.svg"))
      and open(os.path.join(media, "abc-ao-O.svg"), "rb").read() == "<svg>ü</svg>".encode("utf8"),
      repr(name))
shutil.rmtree(media, ignore_errors=True)


section("options: GrabKey's notices are non-blocking io_info boxes (R4)")
opts = M["options"]
check("options.py names no showInfo at all",
      "showInfo" not in open(os.path.join(PKG, "options.py"), encoding="utf-8").read())
infos = []
opts.io_info = lambda msgkey, **kw: infos.append((msgkey, kw))
gk = object.__new__(opts.GrabKey)
for mods, extra, want in (
        ((False, False, False), "K", "Please use at least one keyboard modifier (Ctrl, Alt, Shift)"),
        ((False, False, True), "K", "Shift needs to be combined with at least one other "
                                    "modifier (Ctrl, Alt)"),
        ((True, False, False), None, "Please press at least one key that is not a keyboard "
                                     "modifier (not Ctrl/Alt/Shift)")):
    del infos[:]
    gk.active, (gk.ctrl, gk.alt, gk.shift), gk.extra = 1, mods, extra
    gk.keyReleaseEvent(None)
    check("GrabKey notice via io_info, IOE's text, the grabber as parent: " + want[:30],
          infos == [("custom", {"text": want, "parent": gk})], repr(infos))


section("options: Save writes collection config through set_config")
opts = M["options"]
col = FakeCol({"imgocc": copy.deepcopy(cfg.default_conf_syncd)},
              model={"flds": [{"name": n} for n in cfg.IO_FLDS.values()]})
m = fake_mw(col)
m.pm.profile["imgocc"] = dict(cfg.default_conf_local)
set_mw(m)
o = object.__new__(opts.ImgOccOpts)
o.ofill, o.qfill, o.scol, o.hotkey = "010101", "020202", "030303", "Ctrl+J"
o.lnedit = {}
o.swidth_sel = types.SimpleNamespace(value=lambda: 7)
o.fsize_sel = types.SimpleNamespace(value=lambda: 30)
o.font_sel = types.SimpleNamespace(currentFont=lambda: types.SimpleNamespace(family=lambda: "Menlo"))
o.skipped = types.SimpleNamespace(text=lambda: "Extra 1")
o.close = lambda: None
o.onAccept()
saved = col._conf["imgocc"]
check("the edited values land in the stored imgocc dict",
      (saved["ofill"], saved["qfill"], saved["scol"], saved["swidth"], saved["fsize"],
       saved["font"], saved["skip"]) == ("010101", "020202", "030303", 7, 30, "Menlo", ["Extra 1"]))
check("...the rest of the dict is kept", saved["flds"] == cfg.IO_FLDS
      and saved["version"] == cfg.default_conf_syncd["version"])
check("the hotkey stays a profile setting", m.pm.profile["imgocc"]["hotkey"] == "Ctrl+J")

renamed = []
col.models.renameField = lambda model, fld, name: renamed.append((fld["name"], name))
o.lnedit = {"hd": types.SimpleNamespace(isModified=lambda: True, text=lambda: "Title")}
modified, _flds = o.renameFields()
check("renaming a field renames the note type field and stores the new name in imgocc.flds",
      modified and renamed == [("Header", "Title")]
      and col._conf["imgocc"]["flds"]["hd"] == "Title", "%r %r" % (renamed, col._conf["imgocc"]["flds"]))


# ------------------------------------------------------------ real Qt: io_ask

section("dialogs: io_ask / io_info / io_critical are window-modal open(), answers by signal")
from PyQt6 import QtCore, QtGui, QtWidgets, sip  # noqa: E402

shim = types.ModuleType("aqt.qt")
for _mod in (QtCore, QtGui, QtWidgets):
    for _n in dir(_mod):
        if not _n.startswith("_"):
            setattr(shim, _n, getattr(_mod, _n))
shim.sip = sip
shim.qconnect = lambda sig, fn: sig.connect(fn)
sys.modules["aqt.qt"] = shim
sys.modules["aqt"].qt = shim
del sys.modules["klaus_note.image_occlusion.dialogs"]
dq = importlib.import_module("klaus_note.image_occlusion.dialogs")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
QMB = QtWidgets.QMessageBox
win = QtWidgets.QWidget()
win.show()
dq.mw = types.SimpleNamespace(app=app)

slot_errors, real_hook = [], sys.excepthook
sys.excepthook = lambda *exc: slot_errors.append(exc[1])
try:
    answers = []
    box = dq.io_ask(win, "Proceed?", answers.append, title="T")
    check("io_ask returns an open, window-modal QMessageBox and has not answered yet",
          isinstance(box, QMB) and box.isVisible()
          and box.windowModality() == QtCore.Qt.WindowModality.WindowModal
          and box.text() == "Proceed?" and answers == [],
          # (no windowTitle check: QMessageBox drops the title on macOS)
          "%r %r %r %r" % (box.isVisible(), box.windowModality(), box.text(), answers))
    box.done(QMB.StandardButton.Yes.value)
    check("done(Yes) -> on_answer(True), from finished", answers == [True], str(answers))
    box = dq.io_ask(win, "Proceed?", answers.append)
    box.done(QMB.StandardButton.No.value)
    check("done(No) -> on_answer(False)", answers == [True, False], str(answers))
    box = dq.io_ask(win, "Proceed?", answers.append)
    box.button(QMB.StandardButton.Yes).click()
    check("a clicked Yes button -> on_answer(True)", answers == [True, False, True], str(answers))
    box = dq.io_ask(win, "Proceed?", answers.append)
    box.reject()
    check("Esc/close -> on_answer(False)", answers[-1] is False and len(answers) == 4)

    helps = []
    dq.ioHelp = lambda key, parent=None, **k: helps.append(key)
    box = dq.io_ask(win, "Delete?", answers.append, help="edit", default_no=True)
    check("help adds a Help button; default_no makes No the default",
          box.button(QMB.StandardButton.Help) is not None
          and box.defaultButton() is box.button(QMB.StandardButton.No))
    box.button(QMB.StandardButton.Help).click()
    check("Help opens IOE's help and answers False (IOE's behaviour)",
          helps == ["edit"] and answers[-1] is False and len(answers) == 5)

    box = dq.io_info("custom", text="Hello", parent=win)
    check("io_info is an open, window-modal box with IOE's arguments",
          isinstance(box, QMB) and box.isVisible() and box.text() == "Hello"
          and box.windowModality() == QtCore.Qt.WindowModality.WindowModal)
    box.done(QMB.StandardButton.Ok.value)
    box = dq.io_critical("model_error", help="notetype", parent=win)
    check("io_critical shows the predefined message, non-blocking",
          isinstance(box, QMB) and box.isVisible()
          and box.text() == dq.dialog_msg["model_error"]
          and box.icon() == QMB.Icon.Critical)
    box.button(QMB.StandardButton.Help).click()
    check("io_critical's Help opens IOE's help", helps[-1] == "notetype")
    app.processEvents()

    hook, cb = Hook(), (lambda: None)
    hook.append(cb)
    dq.remove_hook_later(hook, cb)
    check("a gui_hooks callback is not removed while the hook may be iterating it "
          "(profile_will_close -> close -> remove would skip the next add-on)", cb in hook)
    for _i in range(3):
        app.processEvents()
    check("...it is removed a tick later", cb not in hook)
finally:
    sys.excepthook = real_hook
check("no exception escaped a slot", not slot_errors, str(slot_errors))

raise SystemExit(report())
