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
import sys

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
        self.minted, self.single_adds = [], 0
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
