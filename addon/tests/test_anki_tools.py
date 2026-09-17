"""Tests for anki_tools — the tool layer both assistants call.

The module is built so every handler is ``handler(col, args, ctx)`` against a
duck-typed collection and a ctx of injected capabilities. That is what makes
this testable at all: the real ``col`` needs a running Anki, and a stub does
not.

What only a running Anki can prove is stated as such at the bottom rather
than faked here — the confirmation dialog and the main-thread marshalling
are Qt, and a stub that "passes" for them would be worse than no test.
"""
import json
import os
import shutil
import sys
import tempfile
from array import array

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

at = importlib.import_module("klausmate.anki_tools")


class Note:
    def __init__(self, nid=1, fields=None, tags=None, ntname="Basic"):
        self.id = nid
        self._f = dict(fields or {"Front": "What is incidence?", "Back": "New cases."})
        self.fields = list(self._f.values())
        self.tags = list(tags or [])
        self._nt = {"name": ntname, "flds": [{"name": k} for k in self._f]}

    def note_type(self):
        return self._nt

    def items(self):
        return list(self._f.items())

    def __getitem__(self, k):
        return self._f[k]

    def __setitem__(self, k, v):
        self._f[k] = v
        self.fields = list(self._f.values())

    def cards(self):
        return [type("C", (), {"did": 1})()]


class Decks:
    def __init__(self):
        self.created = []

    def by_name(self, n):
        return {"id": 1, "name": n} if n == "Epi" else None

    def name(self, did):
        return "Epi"

    def id(self, n):
        self.created.append(n)
        return 1

    def all_names_and_ids(self):
        return [type("D", (), {"name": "Epi"})()]


class Models:
    def by_name(self, n):
        if n != "Basic":
            return None
        return {"name": "Basic", "flds": [{"name": "Front"}, {"name": "Back"}]}

    def all_names(self):
        return ["Basic"]


class Col:
    def __init__(self):
        self.decks, self.models = Decks(), Models()
        self.added, self.undo = [], []
        # Tracked separately: the stub AddNoteRequest does not retain its
        # kwargs, so the notes are inspected where they were minted, and
        # the two add paths are counted apart so "used add_notes" is a real
        # assertion rather than a vacuous one.
        self.minted, self.single_adds, self.updated = [], 0, []
        self.notes = {1: Note()}

    def find_notes(self, q):
        if q == "boom":
            raise ValueError("bad query")
        return [1]

    def get_note(self, nid):
        if nid not in self.notes:
            raise KeyError(nid)
        return self.notes[nid]

    def new_note(self, model):
        note = Note(fields={f["name"]: "" for f in model["flds"]})
        self.minted.append(note)
        return note

    def add_note(self, note, did):
        self.single_adds += 1
        self.added.append((note, did))

    def add_notes(self, requests):
        self.added.extend(requests)

    def add_custom_undo_entry(self, label):
        self.undo.append(label)
        return len(self.undo)

    def merge_undo_entries(self, pos):
        return {"merged": pos}

    def update_note(self, note):
        self.updated.append(note)


def ctx(confirm=True, search=None):
    return {
        "strip": lambda s: s,
        "confirm": lambda *a: confirm,
        "user_files": "/tmp/nope",
        "search_pdfs": search or (lambda q, k, uf: []),
    }


section("reads")
_out = at._h_search_notes(Col(), {"query": "deck:Epi"}, ctx())
check("search_notes returns matches with previews and tags",
      _out["total_matches"] == 1 and _out["notes"][0]["note_id"] == 1)
check("a bad query is a ToolError, not a traceback",
      isinstance(
          json.loads(at.run_tool(Col(), "search_notes", {"query": "boom"},
                                 ctx())[0]).get("error"), str))
_out = at._h_get_note(Col(), {"note_id": 1}, ctx())
check("get_note returns every field", set(_out["fields"]) == {"Front", "Back"})
check("...and the decks its cards live in", _out["decks"] == ["Epi"])

section("PDF search goes through the injected capability")
_hits = [{"source": "Lecture_1", "page": 4, "text": "Incidence…", "score": 0.81}]
_out = at._h_search_lecture_pdfs(
    Col(), {"query": "incidence"}, ctx(search=lambda q, k, uf: _hits))
check("results carry the source PDF and the page, so an answer can cite "
      "where it came from",
      _out["chunks"][0]["source"] == "Lecture_1"
      and _out["chunks"][0]["page"] == 4)
# Raw source, not code_only: the capability is looked up by a STRING key
# and code_only strips string literals along with comments. Third time that
# has caught me today.
_TOOL_SRC = open("klausmate/anki_tools.py").read()
_H_SRC = _TOOL_SRC.split("def _h_search_lecture_pdfs", 1)[1].split("\ndef ", 1)[0]
check("the handler pulls the searcher out of ctx rather than importing an "
      "embedding provider itself — that is what lets it run here with no "
      "network and no embedding config",
      'ctx.get("search_pdfs")' in _H_SRC and "embeddings" not in _H_SRC)


def _raises(q, k, uf):
    raise RuntimeError("index missing")


try:
    at._h_search_lecture_pdfs(Col(), {"query": "x"}, ctx(search=_raises))
    check("a broken index is a ToolError", False)
except at.ToolError:
    check("a broken index is a ToolError the model can read, not a crash", True)

section("the real PDF search: pdf_index v2 + page_store (K-225 fix)")
# The section above only proves _h_search_lecture_pdfs delegates to
# whatever ctx["search_pdfs"] gives it. _semantic_pdf_search — the real
# implementation default_ctx() wires in as that capability — was never
# itself exercised, which is exactly how it went on calling the deleted
# pdf_index.best_chunk/.chunks/chunk_text_at (Task 5 moved pdf_index to
# one row per page: best_page/.pages) without any test noticing. These
# pins drive the real function end to end, no injected fake, against a
# real v2 index and real page_store records in a scratch user_files.
page_store = importlib.import_module("klausmate.page_store")
pdf_index = importlib.import_module("klausmate.pdf_index")
pdf_handler = importlib.import_module("klausmate.pdf_handler")
embeddings = importlib.import_module("klausmate.embeddings")
# install() gives klausmate a synthetic __init__ (so importing submodules
# never has to run the real, aqt-heavy klausmate/__init__.py) — it has no
# get_config of its own, same gap test_tag_migrate.py's own hand-rolled
# stub package fills the same way.
importlib.import_module("klausmate").get_config = lambda: {}

_sp_dir = tempfile.mkdtemp(prefix="klaus_test_ap_")


def _sp_make(name, slide_pages, page_vecs, dims=2):
    """One indexed PDF on disk: contexts + a dummy PDF file + a fresh,
    matching v2 pdf_index (one unit vector per page)."""
    ctx_dir = os.path.join(_sp_dir, "contexts")
    os.makedirs(ctx_dir, exist_ok=True)
    with open(os.path.join(ctx_dir, name + ".json"), "w") as f:
        json.dump({"pages": slide_pages, "page_count": len(slide_pages)}, f)
    with open(os.path.join(ctx_dir, name + ".txt"), "w") as f:
        f.write("\n\n".join(slide_pages))
    pdf_dir = os.path.join(_sp_dir, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    with open(os.path.join(pdf_dir, name + ".pdf"), "wb") as f:
        f.write(b"%PDF-fake")
    idx = pdf_index.PdfIndex(
        provider="openai", model="m", pdf_name=name, dims=dims,
        source_sig=pdf_index.source_signature(_sp_dir, name),
        pages=[(i + 1, "h%d" % (i + 1)) for i in range(len(page_vecs))],
        embedded_rows=len(page_vecs),
    )
    for v in page_vecs:
        idx.vectors.extend(v)
    pdf_index.save(idx, pdf_index.index_dir(_sp_dir, name))
    return pdf_handler.pdf_path_for(_sp_dir, name)


def _sp_make_dotpdf(raw_stem, safe, slide_pages, page_vecs, dims=2):
    """Like _sp_make, but the context stem list_contexts will discover
    (``raw_stem``) differs from its ``_safe_basename`` (``safe``) — the
    double-extension import (e.g. an original display name of
    "X.pdf.pdf") that made Minor 5's reader/writer key mismatch possible.
    Only the discovery .txt is written under the raw stem; every real
    store (context .json, pdf file, pdf_index, and — by the caller —
    page_store) is keyed under ``safe``, mirroring what do_build itself
    writes under ``pdf_handler._safe_basename(pdf_name)``.
    """
    ctx_dir = os.path.join(_sp_dir, "contexts")
    os.makedirs(ctx_dir, exist_ok=True)
    with open(os.path.join(ctx_dir, raw_stem + ".txt"), "w") as f:
        f.write("\n\n".join(slide_pages))
    with open(os.path.join(ctx_dir, safe + ".json"), "w") as f:
        json.dump({"pages": slide_pages, "page_count": len(slide_pages)}, f)
    pdf_dir = os.path.join(_sp_dir, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    with open(os.path.join(pdf_dir, safe + ".pdf"), "wb") as f:
        f.write(b"%PDF-fake")
    idx = pdf_index.PdfIndex(
        provider="openai", model="m", pdf_name=safe, dims=dims,
        source_sig=pdf_index.source_signature(_sp_dir, safe),
        pages=[(i + 1, "h%d" % (i + 1)) for i in range(len(page_vecs))],
        embedded_rows=len(page_vecs),
    )
    for v in page_vecs:
        idx.vectors.extend(v)
    pdf_index.save(idx, pdf_index.index_dir(_sp_dir, safe))
    return pdf_handler.pdf_path_for(_sp_dir, safe)


# Lecture_A: page 2 (index 1) gets a page_store record with a transcript
# segment, so its combined text differs from the raw slide text — proof
# the hit's text came from page_store, not just pdf_handler.load_pages.
_pathA = _sp_make("Lecture_A", ["Slide A1", "Slide A2"], [[1.0, 0.0], [0.0, 1.0]])
page_store.ensure_records(_sp_dir, "Lecture_A", _pathA, ["Slide A1", "Slide A2"])
page_store.append_segment(_sp_dir, "Lecture_A", _pathA, 1, 0.0, 1.0, "Said on page two")
# Lecture_B: no page_store record anywhere -> must fall back to slide text.
_sp_make("Lecture_B", ["Slide B1"], [[0.0, 1.0]])
# Extra.pdf: neither Lecture_A nor Lecture_B exercises _safe_basename doing
# anything (both names are already fixed points), which is exactly how the
# anki_tools/do_build key mismatch stayed latent (Minor 5). This name's
# discovered stem ("Extra.pdf") differs from its safe basename ("Extra") —
# a page_store record keyed under the wrong one is silently invisible.
_pathExtra = _sp_make_dotpdf("Extra.pdf", "Extra", ["Slide E1"], [[0.0, 1.0]])
page_store.ensure_records(_sp_dir, "Extra", _pathExtra, ["Slide E1"])
page_store.append_segment(_sp_dir, "Extra", _pathExtra, 0, 0.0, 1.0, "Said on page one")

# Stub the embedding call itself (no network, no API key, no paid call):
# the query vector [0, 1] is engineered to win row 2 of Lecture_A (its
# [0, 1] page vector), the only row of Lecture_B, and the only row of Extra.
_orig_provider_from_config = embeddings.provider_from_config
_orig_index_signature = embeddings.index_signature


class _FakeQueryProvider:
    def embed(self, texts, kind="query"):
        return [[0.0, 1.0]]


embeddings.provider_from_config = lambda get_config: _FakeQueryProvider()
embeddings.index_signature = lambda cfg: ("openai", "m", 2)
try:
    _sp_hits = {h.get("source"): h
                for h in at._semantic_pdf_search("photosynthesis", 5, _sp_dir)}
finally:
    embeddings.provider_from_config = _orig_provider_from_config
    embeddings.index_signature = _orig_index_signature
    shutil.rmtree(_sp_dir, ignore_errors=True)

check("every fresh per-PDF index is scored and returned",
      set(_sp_hits) == {"Lecture_A", "Lecture_B", "Extra.pdf"})
_hitA, _hitB = _sp_hits.get("Lecture_A") or {}, _sp_hits.get("Lecture_B") or {}
check("the hit's page is the argmax row's 1-based page (best_page, not "
      "the deleted best_chunk)", _hitA.get("page") == 2 and _hitB.get("page") == 1)
check("a page WITH a page_store record returns its COMBINED text (slide + "
      "transcript) — proves the fix reads page_store, not just slide text",
      _hitA.get("text") == "Slide A2\n\nSaid on page two")
check("a page with NO page_store record falls back to the raw slide text",
      _hitB.get("text") == "Slide B1")

_hitExtra = _sp_hits.get("Extra.pdf") or {}
check("Minor 5 fix-round-2 pin: pdf_path_for and page_store.load_record "
      "key off the SAME _safe_basename(name) do_build uses, even when the "
      "discovered stem itself still has a trailing .pdf — the hit's text "
      "includes the transcript segment, proving load_record found the "
      "record under \"Extra\", not the raw \"Extra.pdf\"",
      _hitExtra.get("text") == "Slide E1\n\nSaid on page one",
      _hitExtra)

section("writes need the human, every time")
_c = Col()
_args = {"deck": "Epi", "note_type": "Basic", "fields": {"Front": "F", "Back": "B"}}
try:
    at._h_create_note(_c, _args, ctx(confirm=False))
    check("a declined confirmation blocks the write", False)
except at.ToolError as e:
    check("a declined confirmation blocks the write", "declined" in str(e))
check("...and nothing was added", _c.added == [])
_c = Col()
_out = at._h_create_note(_c, _args, ctx(confirm=True))
check("an approved create writes exactly one note", len(_c.added) == 1)
check("create_note is in WRITE_TOOLS, so it gets the long timeout and the "
      "dialog", "create_note" in at.WRITE_TOOLS)
check("search_notes is NOT a write tool", "search_notes" not in at.WRITE_TOOLS)
for _bad, _why in (
    ({"deck": "Nope", "note_type": "Basic", "fields": {"Front": "F"}}, "deck"),
    ({"deck": "Epi", "note_type": "Nope", "fields": {"Front": "F"}}, "note type"),
    ({"deck": "Epi", "note_type": "Basic", "fields": {"Bogus": "x"}}, "field"),
    ({"deck": "Epi", "note_type": "Basic", "fields": {}}, "empty fields"),
):
    try:
        at._h_create_note(Col(), _bad, ctx())
        check(f"an unknown {_why} is refused", False)
    except at.ToolError:
        check(f"an unknown {_why} is refused BEFORE the dialog", True)

# update_note is a WRITE tool and had no test at all until the mutation
# audit made that obvious. Its confirmation gate is the only thing between
# a model and somebody's existing cards.
section("update_note is gated too, not just create")
_c = Col()
_upd = {"note_id": 1, "fields": {"Front": "rewritten"}}
try:
    at._h_update_note(_c, _upd, ctx(confirm=False))
    check("a declined update changes nothing", False)
except at.ToolError as e:
    check("a declined update is refused", "declined" in str(e))
check("...and the note is untouched",
      _c.updated == [] and _c.notes[1]["Front"] == "What is incidence?")
_c = Col()
_out = at._h_update_note(_c, _upd, ctx(confirm=True))
check("an approved update writes", len(_c.updated) == 1)
check("...only the changed field", _c.notes[1]["Front"] == "rewritten"
      and _c.notes[1]["Back"] == "New cases.")
check("the tool reports what it changed", "Front" in _out["updated_fields"])
_c = Col()
_out = at._h_update_note(
    _c, {"note_id": 1, "fields": {"Front": "What is incidence?"}},
    ctx(confirm=False))
check("a no-op update never even asks — nothing changed, so there is "
      "nothing to approve", _out["updated_fields"] == [] and _c.updated == [])
try:
    at._h_update_note(Col(), {"note_id": 1, "fields": {"Nope": "x"}}, ctx())
    check("an unknown field is refused", False)
except at.ToolError:
    check("an unknown field is refused before the dialog", True)
try:
    at._h_update_note(Col(), {"note_id": 999, "fields": {"Front": "x"}}, ctx())
    check("a missing note is refused", False)
except at.ToolError:
    check("a missing note is a ToolError, not a crash", True)
check("update_note is a write tool", "update_note" in at.WRITE_TOOLS)

section("the reviewed batch is one undo entry")


class _P:
    def __init__(self, front, back, pages):
        self.front, self.back, self.pages = front, back, pages


_c = Col()
_props = [_P("F1", "B1", (2,)), _P("F2", "B2", (2, 5))]
_res = at.add_reviewed_cards(_c, _props, "Epi", "Basic")
check("every accepted card is written", len(_c.added) == 2)
check("as ONE undo entry — accepting twelve cards and pressing Ctrl+Z "
      "eleven times is not an undo", len(_c.undo) == 1)
check("the entry names the count", "2 cards" in _c.undo[0])
check("the undo entry is merged, so it is a single step",
      _res == {"merged": 1})
check("add_notes was used, not a loop of add_note — a loop leaves one undo "
      "entry per card", _c.single_adds == 0 and len(_c.added) == 2)
_tags = _c.minted[1].tags
check("provenance travels with the card as a page tag, because a source "
      "that lives only in a closed review window cannot be audited later",
      "page::3" in _tags and "page::6" in _tags)
check("...1-based, as a human reads it against the PDF", "page::2" not in _tags)
check("a drafted tag marks the batch", "!Library::Drafted" in _tags)
check("an empty batch writes nothing and creates no undo entry",
      at.add_reviewed_cards(Col(), [], "Epi", "Basic") is None)
for _nt, _dk, _why in (("Nope", "Epi", "note type"), ("Basic", "Nope", "deck")):
    try:
        at.add_reviewed_cards(Col(), _props, _dk, _nt)
        check(f"an unknown {_why} is refused", False)
    except at.ToolError:
        check(f"an unknown {_why} is refused", True)
try:
    at.add_reviewed_cards(Col(), _props, "Epi", "Basic", front_field="Nope")
    check("an unknown field is refused", False)
except at.ToolError:
    check("an unknown field is refused", True)

section("run_tool never raises and never leaks a traceback")
_txt, _err = at.run_tool(Col(), "no_such_tool", {}, ctx())
check("an unknown tool is an error result, not an exception", _err)
check("...naming the tool", "no_such_tool" in _txt)


def _explode(col, args, c):
    raise RuntimeError("secret internal detail")


at._HANDLERS["_boom"] = _explode
_txt, _err = at.run_tool(Col(), "_boom", {}, ctx())
del at._HANDLERS["_boom"]
check("an unexpected exception becomes a generic error", _err)
check("...with no traceback or internals leaked to the model",
      "secret internal detail" not in _txt and "RuntimeError" in _txt)
check("results are capped so one query cannot flood the context",
      at.MAX_RESULT_BYTES <= 50_000)

section("what only a running Anki can prove")
_SRC = open("klausmate/anki_tools.py").read()
_CODE = code_only(_SRC)
check("the approval dialog is PLAIN text, so note-field HTML cannot dress a "
      "destructive change up as something harmless",
      "QPlainTextEdit" in _CODE and "setPlainText" in _CODE)
check("Deny is the default button", "deny.setDefault(True)" in _CODE)
check("writes get a human-scale timeout and reads do not",
      at.WRITE_TIMEOUT_S >= 60 and at.READ_TIMEOUT_S <= 60)
check("execute_tool marshals onto the main thread",
      "_run_on_main_sync" in _CODE)
check("add_notes takes AddNoteRequest, not bare notes",
      "AddNoteRequest(note=" in _CODE)

raise SystemExit(report())
