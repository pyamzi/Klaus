"""Image Occlusion 1/3: built into Klaus, guarded against the separate add-on.

setup() registers IOE's hooks once (never when IOE, add-on 1374772155 or
its .ankiaddon folder image_occlusion_enhanced, is installed and enabled), the one setWebExports regex serves the subpackage's
web assets, the note type is created once, the note generators still write
the masks the verbatim IOE wrote (fixtures made by running 31c3134's ngen),
occlude() hands svg-edit an initial mask in add mode, and (#13) note IDs and
image src values from a synced deck never reach a path outside media.

Run: env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_image_occlusion_setup.py
"""
from __future__ import annotations

import ast
import copy
import os
import re
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import _Dummy, _permissive_module, check, install, report, section  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "io")
CONFLICT_TIP = ("Image Occlusion is now built into KlausNote. Disable the separate Image "
                "Occlusion Enhanced add-on and restart Anki.")

install()
for _name in ("aqt.addcards", "aqt.editcurrent", "aqt.reviewer", "anki.notes",
              "anki.errors", "anki.config"):
    _permissive_module(_name)


class Hook(list):
    pass


HOOKS = ("card_will_show", "reviewer_did_show_answer", "browser_menus_did_init",
         "profile_did_open", "editor_did_init_buttons", "editor_will_show_context_menu",
         "editor_did_load_note", "state_shortcuts_will_change", "main_window_did_init",
         "profile_will_close", "webview_will_set_content")
gh = sys.modules["aqt.gui_hooks"]


def fresh_hooks():
    for h in HOOKS:
        setattr(gh, h, Hook())


fresh_hooks()

import importlib  # noqa: E402

io = importlib.import_module("klaus_note.image_occlusion")


class Mgr:
    """mw.addonManager with Anki's semantics: allAddons() lists installed
    folders, isEnabled() is True for a folder with no meta.json at all."""

    def __init__(self, installed=(), disabled=()):
        self.installed, self.disabled = list(installed), set(disabled)
        self.config_actions = []

    def allAddons(self):
        return sorted(self.installed)

    def isEnabled(self, module):
        return module not in self.disabled

    def setConfigAction(self, *a):
        self.config_actions.append(a)


class Menu:
    def __init__(self):
        self.actions = []

    def addAction(self, a):
        self.actions.append(a)


class Action:
    def __init__(self, text, *a):
        self.text = text
        self.triggered = _Dummy()


def fake_main_window(mgr):
    return types.SimpleNamespace(
        addonManager=mgr,
        form=types.SimpleNamespace(menuTools=Menu(), menuHelp=Menu()),
        progress=types.SimpleNamespace(single_shot=lambda ms, fn, *a, **k: fn()))


tips = []
io.tooltip = lambda msg, *a, **k: tips.append(msg)

section("conflict guard: the separate add-on installed and enabled")
check("CONFLICT_ADDON is IOE's AnkiWeb id", io.CONFLICT_ADDON == "1374772155")
mgr = Mgr(installed=["1374772155", "klaus_note"])
mwin = fake_main_window(mgr)
io.mw = mwin
check("setup() returns False", io.setup() is False)
check("no gui_hooks callback is registered", all(getattr(gh, h) == [] for h in HOOKS),
      str({h: getattr(gh, h) for h in HOOKS if getattr(gh, h)}))
check("no menu action is added",
      mwin.form.menuTools.actions == [] and mwin.form.menuHelp.actions == [])
check("exactly the conflict tooltip is shown", tips == [CONFLICT_TIP], str(tips))
check("the guard runs before IOE's modules load",
      "klaus_note.image_occlusion.main" not in sys.modules)
check("setup() leaves the guard flag off", io._active is False)
check("occlude() does nothing while the guard is tripped",
      io.occlude(types.SimpleNamespace(addMode=True), "/nonexistent.png") is False
      and "klaus_note.image_occlusion.main" not in sys.modules
      and "klaus_note.image_occlusion.add" not in sys.modules)

section("#20 conflict guard: IOE installed from its .ankiaddon (image_occlusion_enhanced)")
fresh_hooks()
tips.clear()
mgr = Mgr(installed=["image_occlusion_enhanced", "klaus_note"])
mwin = fake_main_window(mgr)
io.mw = mwin
check("setup() returns False", io.setup() is False)
check("no gui_hooks callback is registered", all(getattr(gh, h) == [] for h in HOOKS),
      str({h: getattr(gh, h) for h in HOOKS if getattr(gh, h)}))
check("no menu action is added",
      mwin.form.menuTools.actions == [] and mwin.form.menuHelp.actions == [])
check("exactly the conflict tooltip is shown", tips == [CONFLICT_TIP], str(tips))
check("IOE's modules still don't load", "klaus_note.image_occlusion.main" not in sys.modules)
check("the guard flag stays off", io._active is False)

main = importlib.import_module("klaus_note.image_occlusion.main")
main.QAction = Action

for label, mgr in (("disabled", Mgr(installed=["1374772155"], disabled=["1374772155"])),
                   ("absent", Mgr(installed=["klaus_note"])),
                   ("disabled (.ankiaddon folder)",
                    Mgr(installed=["image_occlusion_enhanced"],
                        disabled=["image_occlusion_enhanced"]))):
    section("setup with the separate add-on " + label)
    fresh_hooks()
    tips.clear()
    mwin = fake_main_window(mgr)
    io.mw = mwin
    check("setup() returns True", io.setup() is True)
    for h, fn in (("editor_did_init_buttons", main.on_setup_editor_buttons),
                  ("editor_will_show_context_menu", main.maybe_add_image_menu),
                  ("editor_did_load_note", main.on_editor_did_load_note),
                  ("profile_did_open", main.on_profile_loaded),
                  ("state_shortcuts_will_change", main.on_mw_state_shortcuts)):
        check("registers %s once" % h, getattr(gh, h) == [fn], str(getattr(gh, h)))
    check("no tooltip", tips == [])
    check("setup() sets the guard flag", io._active is True)
    check("R3: setConfigAction is never called (KlausNote keeps its own Config button)",
          mgr.config_actions == [], str(mgr.config_actions))
    check("Tools gets 'Image Occlusion Options…'",
          [a.text for a in mwin.form.menuTools.actions] == ["Image Occlusion Options…"],
          str([a.text for a in mwin.form.menuTools.actions]))
    check("Help keeps one Image Occlusion entry",
          [a.text for a in mwin.form.menuHelp.actions] == ["Image Occlusion Help…"],
          str([a.text for a in mwin.form.menuHelp.actions]))


section("the one setWebExports regex")
tree = ast.parse(open(os.path.join(ROOT, "klaus_note", "__init__.py"), encoding="utf-8").read())
calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
         and isinstance(n.func, ast.Attribute) and n.func.attr == "setWebExports"]
check("klaus_note/__init__.py has exactly one setWebExports call", len(calls) == 1)
pat = calls[0].args[1].value
for path in ("web/x.css", "user_files/backgrounds/A.JPG", "image_occlusion/web/editor.js",
             "image_occlusion/web/editor.css", "image_occlusion/excalidraw/index.html",
             "image_occlusion/excalidraw/assets/Excalifont.woff2"):
    check("serves " + path, re.fullmatch(pat, path) is not None)
for path in ("image_occlusion/svg-edit/editor/svg-editor.html", "image_occlusion/add.py",
             "user_files/annotations/x.json"):
    check("does not serve " + path, re.fullmatch(pat, path) is None)
src = open(os.path.join(ROOT, "klaus_note", "__init__.py"), encoding="utf-8").read()
check("klaus_note/__init__.py calls image_occlusion.setup() once",
      len(re.findall(r"\b_?image_occlusion\.setup\(\)", src)) == 1)


# ------------------------------------------------------------ collection fakes

cfg = importlib.import_module("klaus_note.image_occlusion.config")
ngen = importlib.import_module("klaus_note.image_occlusion.ngen")
add = importlib.import_module("klaus_note.image_occlusion.add")
MODS = (main, cfg, ngen, add)


class Note(dict):
    flushed = []

    def __init__(self, col=None, model=None, nid=None):
        super().__init__()
        self.tags, self.nid = [], nid

    def flush(self):
        Note.flushed.append(self.nid)

    def model(self):
        return None


ngen.Note = Note


def io_model():
    return {"name": cfg.IO_MODEL_NAME, "tmpls": [{"name": cfg.IO_CARD_NAME}],
            "flds": [{"name": cfg.IO_FLDS[i], "sticky": False} for i in cfg.IO_FLDS_IDS]}


class Models:
    def __init__(self, model=None):
        self.model, self.added = model, []

    def by_name(self, name):
        return self.model if self.model and self.model["name"] == name else None

    def fieldNames(self, m):
        return [f["name"] for f in m["flds"]]

    def new(self, name):
        return {"name": name, "flds": [], "tmpls": []}

    def newField(self, name):
        return {"name": name, "sticky": False}

    def addField(self, m, f):
        m["flds"].append(f)

    def newTemplate(self, name):
        return {"name": name}

    def addTemplate(self, m, t):
        m["tmpls"].append(t)

    def add(self, m):
        self.added.append(m)
        self.model = m


class Col:
    def __init__(self, media, model=None, notes=None):
        self._conf = {"imgocc": copy.deepcopy(cfg.default_conf_syncd)}
        self.models = Models(model)
        self.media = types.SimpleNamespace(
            dir=lambda: media,
            add_file=lambda p: shutil.copy(p, media) and os.path.basename(p))
        self.notes = notes or {}
        self.added, self.removed = [], []

    def get_config(self, key, default=None):
        return copy.deepcopy(self._conf[key]) if key in self._conf else default

    def set_config(self, key, val):
        self._conf[key] = copy.deepcopy(val)

    def addNote(self, note):
        self.added.append(note)

    def remNotes(self, nids):
        self.removed.append(list(nids))

    def findNotes(self, query):
        return sorted(self.notes)

    def getNote(self, nid):
        return self.notes[nid]


def use_col(col):
    mw = types.SimpleNamespace(col=col, pm=types.SimpleNamespace(profile={}),
                               checkpoint=lambda *a: None)
    for mod in MODS:
        mod.mw = mw
    return mw


section("the note type is created once")
col = Col(tempfile.mkdtemp(prefix="io-media-"))
use_col(col)
first = cfg.getOrCreateModel()
second = cfg.getOrCreateModel()
check("a missing model is created", len(col.models.added) == 1 and first is col.models.added[0])
check("...once: the second call returns it without adding another",
      second is first and len(col.models.added) == 1)
check("...with IOE's fields in order",
      [f["name"] for f in first["flds"]] == [cfg.IO_FLDS[i] for i in cfg.IO_FLDS_IDS])

existing = io_model()
existing["flds"].append({"name": "My extra", "sticky": True})
existing["tmpls"][0]["qfmt"] = "{{Header}} my own front"
before = copy.deepcopy(existing)
col = Col(tempfile.mkdtemp(prefix="io-media-"), model=existing)
use_col(col)
got = cfg.getOrCreateModel()
check("an existing model of that name is returned untouched",
      got is existing and existing == before and col.models.added == [])


section("Review Focus 1: masks equal the verbatim IOE's (31c3134 ngen)")
O_SVG = open(os.path.join(FIX, "abc-ao-O.svg"), encoding="utf-8").read()
PNG = os.path.join(FIX, "image.png")
_uuid4 = ngen.uuid.uuid4
ngen.uuid.uuid4 = lambda: "abc"
try:
    for key, gen_cls in (("ao", ngen.IoGenHideAllRevealOne), ("oa", ngen.IoGenHideOneRevealAll)):
        media = tempfile.mkdtemp(prefix="io-media-")
        col = Col(media, model=io_model())
        use_col(col)
        gen = gen_cls(None, O_SVG, PNG, {"tags": [], "did": 1}, [], {}, 1)
        check(key + ": generateNotes adds two notes",
              gen.generateNotes() == "default" and len(col.added) == 2)
        exp_dir = os.path.join(FIX, "expected", key)
        for name in sorted(os.listdir(exp_dir)):
            with open(os.path.join(exp_dir, name), "rb") as f:
                want = f.read()
            got_path = os.path.join(media, name)
            got = open(got_path, "rb").read() if os.path.isfile(got_path) else None
            check("%s: %s equals the committed expected file" % (key, name), got == want)
        check(key + ": the expected set is complete (Q and A for both masks)",
              len(os.listdir(exp_dir)) == 4)
finally:
    ngen.uuid.uuid4 = _uuid4

section("updateNotes keeps abc-ao-1/abc-ao-2: two notes updated, none added")
media = tempfile.mkdtemp(prefix="io-media-")
omask = os.path.join(media, "abc-ao-O.svg")
shutil.copy(os.path.join(FIX, "abc-ao-O.svg"), omask)
notes = {}
for nid, note_id in ((101, "abc-ao-1"), (102, "abc-ao-2")):
    n = Note(nid=nid)
    n[cfg.IO_FLDS["id"]] = note_id
    notes[nid] = n
col = Col(media, model=io_model(), notes=notes)
use_col(col)
Note.flushed = []
done = []
opref = {"uniq_id": "abc", "occl_tp": "ao", "omask": omask, "note_id": "abc-ao-1",
         "did": 1, "tags": []}
gen = ngen.IoGenHideAllRevealOne(types.SimpleNamespace(parentWindow=None), O_SVG, PNG,
                                 opref, [], {}, 1)
gen.updateNotes(on_done=done.append)
check("on_done runs once with a state (no confirm needed)", len(done) == 1, str(done))
check("both existing notes are flushed", sorted(Note.flushed) == [101, 102], str(Note.flushed))
check("no note is added and none removed", col.added == [] and col.removed == [])
check("the notes keep their IDs",
      [notes[n][cfg.IO_FLDS["id"]] for n in (101, 102)] == ["abc-ao-1", "abc-ao-2"])


section("occlude(editor, png, initial_svg) in add mode")
from PyQt6.QtCore import QUrl, QUrlQuery  # noqa: E402

add.QUrl, add.QUrlQuery = QUrl, QUrlQuery
urls = []


class Dialog(_Dummy):
    def __init__(self, *a, **k):
        self.tedit = {}
        self.svg_edit = types.SimpleNamespace(setUrl=urls.append, runOnLoaded=lambda fn: None)


add.ImgOccEdit = Dialog
col = Col(tempfile.mkdtemp(prefix="io-media-"), model=io_model())
use_col(col)
editor = types.SimpleNamespace(
    addMode=True, note=Note(),
    parentWindow=types.SimpleNamespace(deckChooser=types.SimpleNamespace(selectedId=lambda: 1)))
init_svg = os.path.join(tempfile.mkdtemp(prefix="io-init-"), "start-O.svg")
shutil.copy(os.path.join(FIX, "abc-ao-O.svg"), init_svg)
ok = io.occlude(editor, PNG, init_svg)
check("occlude returns True", ok is True)
check("the editor keeps its ImgOccAdd (ngen's confirm reaches it through ed.imgoccadd)",
      isinstance(getattr(editor, "imgoccadd", None), add.ImgOccAdd)
      and editor.imgoccadd.origin == "addcards")
check("svg-edit got one URL", len(urls) == 1)
if urls:
    q = QUrlQuery(urls[0])
    full = QUrl.ComponentFormattingOption.FullyDecoded
    check("url= points at initial_svg", q.queryItemValue("url", full)
          == add.path_to_url(init_svg), q.queryItemValue("url", full))
    check("initTool=rect (add mode)", q.queryItemValue("initTool") == "rect")
    check("dimensions read from the png", q.queryItemValue("dimensions") == "400,300")

urls.clear()
editor = types.SimpleNamespace(
    addMode=True, note=Note(),
    parentWindow=types.SimpleNamespace(deckChooser=types.SimpleNamespace(selectedId=lambda: 1)))
io.occlude(editor, PNG)
check("without initial_svg there is no url= item",
      len(urls) == 1 and not QUrlQuery(urls[0]).hasQueryItem("url"))


section("R7: Anki 26.09's NewAddCards (no deck chooser at all)")
import contextlib  # noqa: E402
import io as _stdio  # noqa: E402


class NewAddCards:
    """Like aqt.addcards.NewAddCards: no deckChooser, no deck_chooser, no AddCards base."""


urls.clear()
col = Col(tempfile.mkdtemp(prefix="io-media-"), model=io_model())
col.defaults_for_adding = lambda current_review_card=None: types.SimpleNamespace(deck_id=77)
col.decks = types.SimpleNamespace(get_current_id=lambda: 99)
use_col(col)
editor = types.SimpleNamespace(addMode=True, note=Note(), parentWindow=NewAddCards())
check("the editor-button origin comes from addMode, not isinstance(AddCards)",
      main.get_editor_parent_instance(editor) == "addcards")
check("a non-add editor is not addcards",
      main.get_editor_parent_instance(types.SimpleNamespace(
          addMode=False, parentWindow=NewAddCards())) != "addcards")
check("occlude works in a NewAddCards-like window", io.occlude(editor, PNG) is True
      and editor.imgoccadd.origin == "addcards")
check("...and takes the deck from col.defaults_for_adding",
      editor.imgoccadd.opref.get("did") == 77, str(editor.imgoccadd.opref.get("did")))
del col.defaults_for_adding
check("without defaults_for_adding the deck is the current deck",
      add._current_deck_id(editor) == 99)
legacy = types.SimpleNamespace(deckChooser=types.SimpleNamespace(selectedId=lambda: 5))
check("legacy AddCards: deckChooser.selectedId() first",
      add._current_deck_id(types.SimpleNamespace(parentWindow=legacy)) == 5)
newer = types.SimpleNamespace(deck_chooser=types.SimpleNamespace(selected_deck_id=6))
check("then deck_chooser.selected_deck_id",
      add._current_deck_id(types.SimpleNamespace(parentWindow=newer)) == 6)

section("on_profile_loaded logs a malformed imgocc config instead of raising")
col = Col(tempfile.mkdtemp(prefix="io-media-"), model=io_model())
col._conf["imgocc"] = {"ofill": "FFEBA2"}  # no "version"
use_col(col)
out = _stdio.StringIO()
try:
    with contextlib.redirect_stdout(out):
        main.on_profile_loaded()
    raised = None
except Exception as e:  # noqa: BLE001
    raised = e
check("it does not raise", raised is None, repr(raised))
check("it logs '[klaus_note] image occlusion profile setup failed: …'",
      "[klaus_note] image occlusion profile setup failed:" in out.getvalue(), out.getvalue())

section("#13 getIONoteData accepts only <hex uniq_id>-<ao|oa|aa>-<n> note IDs")
utils = importlib.import_module("klaus_note.image_occlusion.utils")
nconvert = importlib.import_module("klaus_note.image_occlusion.nconvert")
MODS = MODS + (utils,)
base = tempfile.mkdtemp(prefix="io-paths-")
media = os.path.join(base, "media")
os.makedirs(os.path.join(media, "sub"))
shutil.copy(PNG, os.path.join(media, "image.png"))
shutil.copy(os.path.join(FIX, "abc-ao-O.svg"), os.path.join(media, "abc-ao-O.svg"))
shutil.copy(PNG, os.path.join(media, "sub", "nested.png"))
shutil.copy(PNG, os.path.join(base, "outside.png"))
col = Col(media, model=io_model())
use_col(col)
ia = add.ImgOccAdd(types.SimpleNamespace(note=None), "editcurrent")
BAD_ID = "Editing unavailable: Invalid image occlusion Note ID"


def io_note(note_id, im='<img src="image.png">', om='<img src="abc-ao-O.svg">'):
    n = Note()
    n[cfg.IO_FLDS["id"]], n[cfg.IO_FLDS["im"]], n[cfg.IO_FLDS["om"]] = note_id, im, om
    return n


for good in ("abc-ao-1", "0123456789abcdef0123456789abcdef-oa-12", "abc-aa-3"):
    ia.opref = {}
    msg, path = ia.getIONoteData(io_note(good))
    check("accepts %s" % good, msg is None and path == os.path.join(media, "image.png")
          and ia.opref.get("uniq_id") == good.split("-")[0], str((msg, path)))
for bad in ("../../evil-ao-1", "a/b-ao-1", "a\\b-ao-1", "..-ao-1", "abc-../x-1",
            "abc-ao-1/..", "abc-xx-1", "ABC-ao-1", "abc-ao-", "-ao-1", "abc-ao-1x",
            " abc-ao-1", "abc-ao-1\n", ""):
    ia.opref = {}
    msg, path = ia.getIONoteData(io_note(bad))
    check("refuses %r with the invalid-ID message, opening nothing" % bad,
          msg == BAD_ID and path is None and "uniq_id" not in ia.opref, str((msg, path)))

section("#13 img_element_to_path resolves only to files directly in the media folder")
check("a plain media name resolves",
      utils.img_element_to_path('<img src="image.png">') == os.path.join(media, "image.png"))
check("nameonly still returns the name",
      utils.img_element_to_path('<img src="image.png">', True) == "image.png")
for src in ("../outside.png", os.path.join(base, "outside.png"), "sub/../../outside.png",
            "sub/nested.png"):
    got = utils.img_element_to_path('<img src="%s">' % src)
    check("refuses src=%r (None)" % src, got is None, str(got))
check("nameonly refuses a src with a path too (None)",
      utils.img_element_to_path('<img src="../outside.png">', True) is None)
check("a URL src never resolves to a local file of the same base name",
      utils.img_element_to_path('<img src="https://example.org/x/image.png">') is None
      and utils.img_element_to_path('<img src="https://example.org/x/image.png">', True)
      is None)
os.symlink(os.path.join(base, "outside.png"), os.path.join(media, "link.png"))
check("a media entry that resolves outside the folder is refused",
      utils.img_element_to_path('<img src="link.png">') is None)
msg, path = ia.getIONoteData(io_note("abc-ao-1", im='<img src="../outside.png">'))
check("getIONoteData: an image outside media is a missing image",
      path is None and msg == "Editing unavailable: Missing image or original mask", str(msg))

section("#13 the note generators never write a mask outside the media folder")
before = sorted(os.listdir(base))
# A synced deck whose ID fields and mask ids all carry the same bad uniq_id:
# no card is added or deleted, so updateNotes goes straight to the writes.
notes = {}
for nid, note_id in ((201, "../evil-ao-1"), (202, "../evil-ao-2")):
    n = Note(nid=nid)
    n[cfg.IO_FLDS["id"]] = note_id
    notes[nid] = n
col = Col(media, model=io_model(), notes=notes)
use_col(col)
evil = {"uniq_id": "../evil", "occl_tp": "ao", "omask": os.path.join(media, "abc-ao-O.svg"),
        "note_id": "../evil-ao-1", "did": 1, "tags": []}
gen = ngen.IoGenHideAllRevealOne(types.SimpleNamespace(parentWindow=None),
                                 O_SVG.replace("abc-ao-", "../evil-ao-"), PNG, evil, [], {}, 1)
ngen.tooltip = lambda *a, **k: None
try:
    r = gen.updateNotes(on_done=lambda s: None)
except Exception as e:  # noqa: BLE001
    r = e
check("updateNotes with a uniq_id of '../evil' writes nothing above media",
      sorted(os.listdir(base)) == before, str(sorted(os.listdir(base))))
check("...and refuses (False) before touching any note",
      r is False and col.removed == [], repr(r))

section("#13 a sibling ID with junk after -<n>: refused before any note is deleted")
media_before = sorted(os.listdir(media))
notes = {}
for nid, note_id in ((301, "abc-ao-1"), (302, "abc-ao-2"), (303, "abc-ao-../x")):
    n = Note(nid=nid)
    n[cfg.IO_FLDS["id"]] = note_id
    notes[nid] = n
col = Col(media, model=io_model(), notes=notes)
use_col(col)
Note.flushed = []
asks = []
ngen.io_ask = lambda parent, q, on_answer, **k: (asks.append(q), on_answer(True))
ok_opref = {"uniq_id": "abc", "occl_tp": "ao", "omask": os.path.join(media, "abc-ao-O.svg"),
            "note_id": "abc-ao-1", "did": 1, "tags": []}
ed = types.SimpleNamespace(parentWindow=None,
                           imgoccadd=types.SimpleNamespace(imgoccedit=None))
gen = ngen.IoGenHideAllRevealOne(ed, O_SVG, PNG, ok_opref, [], {}, 1)
try:
    r = gen.updateNotes(on_done=lambda s: None)
except Exception as e:  # noqa: BLE001
    r = e
check("updateNotes refuses (False)", r is False, repr(r))
check("...no note deleted, none flushed, nothing asked",
      col.removed == [] and Note.flushed == [] and asks == [],
      "%s %s %s" % (col.removed, Note.flushed, asks))
check("...and no mask written", sorted(os.listdir(media)) == media_before
      and sorted(os.listdir(base)) == before)

section("#13 nconvert reads the masks through their confined media paths")
nconvert.mw = add.mw
conv = nconvert.ImgOccNoteConverter(None)
cn = Note()
cn[cfg.IO_FLDS["qm"]] = cn[cfg.IO_FLDS["om"]] = '<img src="abc-ao-O.svg">'
cwd = os.getcwd()
os.chdir(base)  # a bare relative name would have resolved here, not in media
try:
    try:
        tp = conv.getOcclTypeAndNodes(cn)
    except Exception as e:  # noqa: BLE001
        tp = e
    check("masks in media are read from media (not the working directory)", tp == "ao", repr(tp))
    shutil.copy(os.path.join(FIX, "abc-ao-O.svg"), os.path.join(base, "esc-O.svg"))
    cn[cfg.IO_FLDS["qm"]] = cn[cfg.IO_FLDS["om"]] = '<img src="../esc-O.svg">'
    try:
        tp = conv.getOcclTypeAndNodes(cn)
    except Exception as e:  # noqa: BLE001
        tp = e
    check("a mask src outside media: None (the note is skipped), nothing read", tp is None,
          repr(tp))
finally:
    os.chdir(cwd)
    if os.path.exists(os.path.join(base, "esc-O.svg")):
        os.remove(os.path.join(base, "esc-O.svg"))
for mod, label in ((ngen.ImgOccNoteGenerator, "ngen"), (nconvert.ImgOccNoteConverter, "nconvert")):
    fake = types.SimpleNamespace(_media_path=media)
    for name in ("../x", os.path.join(base, "x"), "sub/x"):
        try:
            mod._saveMask(fake, "<svg/>", name, "Q")
            r = None
        except ValueError as e:
            r = e
        check("%s._saveMask refuses note id %r" % (label, name), isinstance(r, ValueError)
              and sorted(os.listdir(base)) == before
              and not os.path.exists(os.path.join(media, "sub", "x-Q.svg")), repr(r))
    check("%s._saveMask still writes a plain name into media" % label,
          mod._saveMask(fake, "<svg/>", "abc-ao-9", "Q") == "abc-ao-9-Q.svg"
          and os.path.isfile(os.path.join(media, "abc-ao-9-Q.svg")))

raise SystemExit(report())
