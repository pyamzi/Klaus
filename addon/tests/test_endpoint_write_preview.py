"""anki_endpoint write approval (#16): the preview shows the raw field HTML
that will be written, and an edit shows OLD and NEW for each changed field.

Drives Endpoint.handle() directly, never start(), so it runs where binding
a local port is not allowed (tests/test_anki_endpoint.py binds one).

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_endpoint_write_preview.py
"""
import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
ep = importlib.import_module("klaus_note.anki_endpoint")


class Note:
    def __init__(self, nid, fields):
        self.id, self._f, self.tags = nid, dict(fields), []

    def items(self):
        return list(self._f.items())

    def keys(self):
        return list(self._f)

    def __getitem__(self, k):
        return self._f[k]

    def __setitem__(self, k, v):
        self._f[k] = v

    def note_type(self):
        return {"name": "Basic", "flds": [{"name": k} for k in self._f]}

    def cards(self):
        return [object()]


class Col:
    def __init__(self):
        self.notes = {3: Note(3, {"Front": 'What is X?<img src="a.png">', "Back": "Y"})}
        self.updated, self.minted = [], []
        self.decks = type("D", (), {"by_name": lambda s, n: {"id": 1, "name": n}, "id": lambda s, n: 1})()
        self.models = type("M", (), {"by_name": lambda s, n: {"name": n, "flds": [{"name": "Front"}, {"name": "Back"}]}})()

    def get_note(self, nid):
        return self.notes[nid]

    def find_notes(self, q):
        return []

    def update_note(self, note):
        self.updated.append(note)

    def new_note(self, model):
        n = Note(0, {f["name"]: "" for f in model["flds"]})
        self.minted.append(n)
        return n

    def add_note(self, note, did):
        note.id = 99


col = Col()
asked = []


during_approval = []  # callables run while the dialog is "open"


def approver(title, sections):
    asked.append(sections)
    for fn in during_approval:
        fn()
    return True


end = ep.Endpoint(col_getter=lambda: col, run_on_main=lambda fn, t: fn(), approver=approver,
                  ctx_factory=lambda: {"strip": lambda s: s}, version="t")


def text(sections):
    return "\n".join(f"{k}: {v}" for k, v in sections)


section("updateNoteFields shows OLD and NEW raw HTML")
r = end.handle("updateNoteFields", {"note": {"id": 3, "fields": {"Front": "What is X?", "Back": "Y"}}}, agent=False)
shown = text(asked[-1]) if asked else ""
check("approved and written", r["error"] is None and col.updated, repr(r))
check("the old value, image included, is in the preview", 'What is X?<img src="a.png">' in shown, shown)
check("the new value is in the preview", "NEW: What is X?" in shown, shown)
check("an unchanged field is left out", "Back" not in shown, shown)
check("the write is exactly the previewed value", col.notes[3]["Front"] == "What is X?")

section("missing note: clean error, no dialog")
n = len(asked)
r = end.handle("updateNoteFields", {"note": {"id": 404, "fields": {"Front": "x"}}}, agent=False)
check("error returned", r["error"] and "404" in r["error"], repr(r))
check("approver never called", len(asked) == n)

section("addNote shows field markup")
r = end.handle("addNote", {"note": {"deckName": "D", "modelName": "Basic",
                                     "fields": {"Front": "x<img src=y onerror=z>", "Back": "b"}}}, agent=False)
shown = text(asked[-1])
check("markup visible, not stripped", "x<img src=y onerror=z>" in shown, shown)
check("written as previewed", col.minted[-1]["Front"] == "x<img src=y onerror=z>")

section("fix round 1: a field changed while the dialog was open is never overwritten")
col.notes[4] = Note(4, {"Front": "Q", "Back": "Y"})
during_approval.append(lambda: col.notes[4].__setitem__("Back", 'remote<img src="b.png">'))
n_upd = len(col.updated)
r = end.handle("updateNoteFields", {"note": {"id": 4, "fields": {"Front": "Q2", "Back": "Y"}}}, agent=False)
during_approval.clear()
check("the write is refused with a retry error", r["error"] and "changed since preview" in r["error"], repr(r))
check("...the remote change survives", col.notes[4]["Back"] == 'remote<img src="b.png">', col.notes[4]["Back"])
check("...and nothing was written", col.notes[4]["Front"] == "Q" and len(col.updated) == n_upd)

section("fix round 1: unknown field and no-op fail fast, no dialog")
n = len(asked)
r = end.handle("updateNoteFields", {"note": {"id": 4, "fields": {"Nope": "x"}}}, agent=False)
check("unknown field: error before any dialog", r["error"] and "Unknown field" in r["error"] and len(asked) == n, repr(r))
r = end.handle("updateNoteFields", {"note": {"id": 4, "fields": {"Front": "Q"}}}, agent=False)
check("nothing changes: no dialog, no write, no error",
      r == {"result": None, "error": None} and len(asked) == n and len(col.updated) == n_upd, repr(r))

section("fix round 1: a null field previews as it is written")
r = end.handle("addNote", {"note": {"deckName": "D", "modelName": "Basic", "fields": {"Front": "f", "Back": None}}}, agent=False)
shown = dict(asked[-1])
check("preview and write agree on a null field", shown.get("Back") == col.minted[-1]["Back"],
      repr((shown.get("Back"), col.minted[-1]["Back"])))

raise SystemExit(report())
