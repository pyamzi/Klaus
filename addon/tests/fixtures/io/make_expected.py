"""Regenerate tests/fixtures/io/expected/{ao,oa}/*-{Q,A}.svg with the Task 1
VERBATIM ngen (31c3134, IOE v1.4.0 byte-for-byte), under stubs. From the repo root:
    d=$(mktemp -d); git archive 31c3134 klausmate/image_occlusion | tar -x -C "$d"
    PYTHONDONTWRITEBYTECODE=1 python3 tests/fixtures/io/make_expected.py "$d"
"""
import copy, os, shutil, sys, tempfile, types, importlib

REPO = os.getcwd()
VERB = sys.argv[1]
sys.path.insert(0, os.path.join(REPO, ".claude/skills/klaus-test/scripts"))
from anki_stubs import install, _permissive_module  # noqa: E402

install(os.path.join(VERB, "klausmate"))
for n in ("aqt.addcards", "aqt.editcurrent", "aqt.reviewer", "anki.notes", "anki.errors", "anki.config"):
    _permissive_module(n)

FIX = os.path.join(REPO, "tests", "fixtures", "io")


class Note(dict):
    def __init__(self, col, model):
        super().__init__()
        self.tags = []


sys.modules["anki.notes"].Note = Note
ngen = importlib.import_module("klausmate.image_occlusion.ngen")
cfg = importlib.import_module("klausmate.image_occlusion.config")
ngen.Note = Note


class Col:
    def __init__(self, media):
        self.conf = {"imgocc": copy.deepcopy(cfg.default_conf_syncd)}
        flds = [{"name": cfg.IO_FLDS[i], "sticky": False} for i in cfg.IO_FLDS_IDS]
        model = {"name": cfg.IO_MODEL_NAME, "flds": flds}
        self.models = types.SimpleNamespace(by_name=lambda n: model)
        self.media = types.SimpleNamespace(
            dir=lambda: media, add_file=lambda p: shutil.copy(p, media) and os.path.basename(p))
        self.added = []

    def addNote(self, note):
        self.added.append(note)


ngen.uuid.uuid4 = lambda: "abc"
for key, cls in (("ao", ngen.IoGenHideAllRevealOne), ("oa", ngen.IoGenHideOneRevealAll)):
    media = tempfile.mkdtemp()
    col = Col(media)
    mw = types.SimpleNamespace(col=col, pm=types.SimpleNamespace(profile={}), checkpoint=lambda *a: None)
    for mod in (ngen, cfg):
        mod.mw = mw
    svg = open(os.path.join(FIX, "abc-ao-O.svg"), encoding="utf-8").read()
    gen = cls(None, svg, os.path.join(FIX, "image.png"), {"tags": [], "did": 1}, [], {}, 1)
    assert gen.generateNotes() == "default"
    assert len(col.added) == 2
    out = os.path.join(FIX, "expected", key)
    os.makedirs(out, exist_ok=True)
    for n in (1, 2):
        for side in "QA":
            name = "abc-%s-%d-%s.svg" % (key, n, side)
            shutil.copy(os.path.join(media, name), out)
            print("wrote", os.path.join(out, name))
