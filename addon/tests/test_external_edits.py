"""#11: a Klaus edit to an adopted outside mark makes it Klaus's.

An outside FreeText/Highlight is adopted as an ``origin: "external"``
record. Editing it in Klaus (text, move, a note) must survive the bake
and the next mirror: the record becomes native, the outside original is
tombstoned so the bake drops it, and the file ends with one Klaus-named
annotation carrying the edit.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_external_edits.py
"""
import importlib
import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install_package_stub, report, section  # noqa: E402

install_package_stub()

# Vendored pypdf needs typing_extensions; python3.9 here lacks it (same
# shim as test_klaus_note).
try:
    import typing_extensions  # noqa: F401
except ImportError:
    import typing as _typing

    class _TESub:
        def __getitem__(self, _i):
            return _typing.Any

        def __call__(self, *a, **k):
            return _typing.Any

    class _TEModule(types.ModuleType):
        def __getattr__(self, n):
            return getattr(_typing, n, _TESub())

    sys.modules["typing_extensions"] = _TEModule("typing_extensions")

ph = importlib.import_module("klaus_note.pdf_handler")
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.annotations import FreeText, Highlight  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, FloatObject, NameObject, TextStringObject,
)

NAME = "Ext_Edits"


def make_outside_pdf(uf):
    os.makedirs(os.path.join(uf, "pdfs"), exist_ok=True)
    path = os.path.join(uf, "pdfs", NAME + ".pdf")
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    with open(path + ".base", "wb") as f:
        w.write(f)
    w2 = PdfWriter(clone_from=PdfReader(path + ".base"))
    hl = Highlight(
        rect=(100, 600, 200, 620),
        quad_points=ArrayObject(
            FloatObject(v) for v in [100, 620, 200, 620, 100, 600, 200, 600]
        ),
    )
    hl[NameObject("/Contents")] = TextStringObject("margin note")
    w2.add_annotation(0, hl)
    w2.add_annotation(0, FreeText(
        text="added in Preview", rect=(300, 500, 450, 530),
        font_size="12pt", font_color="000000",
        border_color=None, background_color=None,
    ))
    with open(path, "wb") as f:
        w2.write(f)
    os.remove(path + ".base")
    return path


def mirror(uf):
    return ph.mirror_foreign_annotations(
        uf, NAME, ph.scan_working_annotations(uf, NAME))


def bake(uf):
    rep = {}
    ok = ph.bake_annotations(uf, NAME, rep)
    if ok and "native_ids" in rep:
        ph.mark_native_baked(uf, NAME, rep["native_ids"])
    return ok


def annots(path, sub):
    out = []
    for ref in PdfReader(path).pages[0].get("/Annots") or []:
        o = ref.get_object()
        if str(o.get("/Subtype")) == sub:
            out.append(o)
    return out


def ft_text(o):
    return str(o.get("/Contents") or "")


def edit(uf, kind, change):
    recs = ph.load_annotations(uf, NAME)
    for r in recs:
        if ph.record_kind(r) == kind:
            change(r)
    ph.save_annotations(uf, NAME, recs)


def rec_of(uf, kind):
    return next((r for r in ph.load_annotations(uf, NAME)
                 if ph.record_kind(r) == kind), None)


check("bake stack available", ph.BAKE_AVAILABLE)

section("edited outside text box survives bake + reopen")
uf = tempfile.mkdtemp(prefix="klaus_ext_")
try:
    working = make_outside_pdf(uf)
    check("adopts two outside marks", mirror(uf) == 2)
    check("text record is external",
          (rec_of(uf, "text") or {}).get("origin") == "external")
    edit(uf, "text", lambda r: r.__setitem__("text", "EDITED in Klaus"))
    check("bake ok", bake(uf))
    mirror(uf)
    t = rec_of(uf, "text") or {}
    check("record keeps the edited text after bake + mirror",
          t.get("text") == "EDITED in Klaus", repr(t))
    check("...and is Klaus's now (no origin)", "origin" not in t, repr(t))
    fts = annots(working, "/FreeText")
    check("file holds exactly one FreeText",
          len(fts) == 1, repr([ft_text(o) for o in fts]))
    check("...with the edited text and a klaus_note: /NM",
          len(fts) == 1 and "EDITED in Klaus" in ft_text(fts[0])
          and str(fts[0].get("/NM") or "").startswith("klaus_note:"),
          repr([(ft_text(o), o.get("/NM")) for o in fts]))
    check("a second mirror changes nothing", mirror(uf) == 0)
    check("one text record, no re-adopted original",
          sum(ph.record_kind(r) == "text"
              for r in ph.load_annotations(uf, NAME)) == 1)
finally:
    shutil.rmtree(uf, ignore_errors=True)

section("moving an outside text box clear of its spot")
uf = tempfile.mkdtemp(prefix="klaus_ext_")
try:
    working = make_outside_pdf(uf)
    mirror(uf)
    edit(uf, "text", lambda r: r.__setitem__("rects", [[20.0, 20.0, 150.0, 30.0]]))
    bake(uf)
    mirror(uf)
    texts = [r for r in ph.load_annotations(uf, NAME) if ph.record_kind(r) == "text"]
    check("exactly one text record, at the new spot",
          len(texts) == 1 and texts[0]["rects"][0][:2] == [20.0, 20.0],
          repr(texts))
    check("file holds exactly one FreeText", len(annots(working, "/FreeText")) == 1)
finally:
    shutil.rmtree(uf, ignore_errors=True)

section("a note added to an outside highlight reaches the file")
uf = tempfile.mkdtemp(prefix="klaus_ext_")
try:
    working = make_outside_pdf(uf)
    mirror(uf)
    edit(uf, "highlight", lambda r: r.__setitem__("note", "Klaus note"))
    bake(uf)
    mirror(uf)
    h = rec_of(uf, "highlight") or {}
    check("record keeps the Klaus note", h.get("note") == "Klaus note", repr(h))
    hls = annots(working, "/Highlight")
    check("file holds one highlight carrying the note in /Contents",
          len(hls) == 1 and "Klaus note" in str(hls[0].get("/Contents") or ""),
          repr([o.get("/Contents") for o in hls]))
finally:
    shutil.rmtree(uf, ignore_errors=True)

section("fix round 1: a claim outlives the tombstone TTL")
uf = tempfile.mkdtemp(prefix="klaus_ext_")
try:
    working = make_outside_pdf(uf)
    mirror(uf)
    edit(uf, "text", lambda r: r.__setitem__("text", "EDITED late"))
    doc = ph._load_annotation_doc(uf, NAME)
    for t in doc["suppressed_external"]:
        t["ts"] -= 3600  # the first bake lands an hour after the edit
    ph._atomic_write_json(ph.annotations_path_for(uf, NAME), doc)
    bake(uf)
    mirror(uf)
    fts = annots(working, "/FreeText")
    check("one FreeText, the edited one",
          [ft_text(o) for o in fts] == ["EDITED late"], repr([ft_text(o) for o in fts]))
    check("one text record, the edited one",
          [r.get("text") for r in ph.load_annotations(uf, NAME)
           if ph.record_kind(r) == "text"] == ["EDITED late"])
    check("the mirror swept the claim tombstone once the original left",
          ph.load_suppressed(uf, NAME) == [], repr(ph.load_suppressed(uf, NAME)))
finally:
    shutil.rmtree(uf, ignore_errors=True)

section("unedited outside marks are still carried verbatim")
uf = tempfile.mkdtemp(prefix="klaus_ext_")
try:
    working = make_outside_pdf(uf)
    mirror(uf)
    recs = ph.load_annotations(uf, NAME)
    ph.save_annotations(uf, NAME, recs)  # a save that edits nothing
    bake(uf)
    check("both still external",
          all(r.get("origin") == "external" for r in ph.load_annotations(uf, NAME)))
    fts = annots(working, "/FreeText")
    check("the outside FreeText is carried, not renamed",
          len(fts) == 1 and not str(fts[0].get("/NM") or "").startswith("klaus_note:"))
    check("no tombstone written", ph.load_suppressed(uf, NAME) == [])
finally:
    shutil.rmtree(uf, ignore_errors=True)

raise SystemExit(report())
