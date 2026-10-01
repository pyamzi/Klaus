"""K-304: Anki op discipline found by the anki-qt-dev audit.

1. Endpoint writes run as ONE undoable CollectionOp (operation_did_execute
   fires, so an open editor reloads instead of saving a stale copy over
   Klaus's change); a request abandoned before its op starts never writes.
2. Slow endpoint reads (Ollama embeds) run in a QueryOp, off the main thread.
3. The map's ~17 s layout build runs without holding the collection.
4. Preferences closes on a profile switch without its discard/stop
   prompts, which used to leave it (and its preview) open.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_anki_ops.py
"""
from __future__ import annotations

import importlib
import sys
import threading

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

ep = importlib.import_module("klausmate.anki_endpoint")
pdf_map = importlib.import_module("klausmate.pdf_map")
manage_models = importlib.import_module("klausmate.manage_models")
aqt = sys.modules["aqt"]
operations = sys.modules["aqt.operations"]


class FakeOp:
    """Records how an op was built and runs it synchronously."""

    made: list = []

    def __init__(self, parent=None, op=None, success=None):
        self.op, self._success, self._failure = op, success, None
        self.no_col = False
        FakeOp.made.append(self)

    def success(self, fn):
        self._success = fn
        return self

    def failure(self, fn):
        self._failure = fn
        return self

    def without_collection(self):
        self.no_col = True
        return self

    def run_in_background(self):
        try:
            result = self.op(FakeCol())
        except Exception as exc:  # noqa: BLE001
            if self._failure:
                self._failure(exc)
            return
        if self._success:
            self._success(result)


class CollectionOpFake(FakeOp):
    kind = "collection"


class QueryOpFake(FakeOp):
    kind = "query"


class FakeTags:
    def __init__(self, log):
        self.log = log

    def bulk_add(self, nids, tags):
        self.log.append(("bulk_add", list(nids), tags))


class FakeCol:
    log: list = []

    def __init__(self):
        self.tags = FakeTags(FakeCol.log)

    def add_custom_undo_entry(self, label):
        FakeCol.log.append(("undo_entry", label))
        return 7

    def merge_undo_entries(self, pos):
        FakeCol.log.append(("merge", pos))
        return "OpChanges"


operations.CollectionOp = CollectionOpFake
operations.QueryOp = QueryOpFake
pending: list = []
aqt.mw = type("MW", (), {"taskman": type("T", (), {"run_on_main": staticmethod(pending.append)})()})()


def run_pending():
    while pending:
        pending.pop(0)()


def call_op(fn, timeout, write, label="Klaus: x"):
    """_run_collection_op from a worker, with 'main' pumped here."""
    box = {}

    def worker():
        try:
            box["r"] = ep._run_collection_op(fn, timeout, write, label)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(200):
        run_pending()
        t.join(0.005)
        if not t.is_alive():
            break
    return box


section("writes: one CollectionOp, one undo entry")
FakeCol.log.clear()
FakeOp.made.clear()
box = call_op(lambda col: (col.tags.bulk_add([1, 2], "x"), "done")[1], 2.0, True, "Klaus: addTags")
op = FakeOp.made[-1]
check("runs as a CollectionOp", getattr(op, "kind", "") == "collection")
check("wrapped in one custom undo entry, merged after the write",
      FakeCol.log == [("undo_entry", "Klaus: addTags"), ("bulk_add", [1, 2], "x"), ("merge", 7)])
check("the handler's own result reaches the caller", box.get("r") == "done")

def boom(col):
    raise ValueError("unknown deck")

box = call_op(boom, 2.0, True)
check("a handler error reaches the caller", isinstance(box.get("e"), ValueError))

section("an abandoned request never writes")
FakeCol.log.clear()
wrote = []
box = {}
done = threading.Event()

def late_worker():
    try:
        ep._run_collection_op(lambda col: wrote.append(1), 0.05, True, "Klaus: addNote")
    except BaseException as e:  # noqa: BLE001
        box["e"] = e
    done.set()

threading.Thread(target=late_worker).start()
done.wait(2.0)  # main thread busy: the op has not started when the caller gives up
check("caller times out", isinstance(box.get("e"), TimeoutError))
run_pending()  # the op finally starts, after the caller left
check("the late op does not write", wrote == [] and ("undo_entry", "Klaus: addNote") not in FakeCol.log)

section("reads: QueryOp off the main thread")
FakeOp.made.clear()
box = call_op(lambda col: ["hit"], 2.0, False)
check("runs as a QueryOp", getattr(FakeOp.made[-1], "kind", "") == "query")
check("result returned", box.get("r") == ["hit"])

section("endpoint dispatch")
calls: list = []


def fake_run_op(fn, timeout, write, label):
    calls.append((write, label))
    return fn(FakeCol())


main_calls: list = []
end = ep.Endpoint(col_getter=FakeCol, run_on_main=lambda fn, timeout: (main_calls.append(1), fn())[1],
                  approver=lambda t, s: True,
                  ctx_factory=lambda: {"strip": lambda s: s, "confirm": lambda *a: True},
                  version="x", run_op=fake_run_op)
FakeCol.log.clear()
res = end.handle("addTags", {"notes": [5], "tags": "t"}, False)
check("addTags goes through run_op as a write", calls == [(True, "Klaus: addTags")], str(res))
check("and actually tags", ("bulk_add", [5], "t") in FakeCol.log)
check("both semantic searches are background reads",
      ep.ACTIONS["klausSearchNotesSemantic"].background and ep.ACTIONS["klausSearchLecturePdfs"].background)
check("every write action is routed as a write",
      all(a.write for a in ep.ACTIONS.values() if a.name in ("addNote", "addNotes", "updateNoteFields", "addTags", "removeTags")))
calls.clear()
end.handle("version", {}, False)
check("ordinary reads stay on the main-thread path", calls == [] and main_calls)
check("no run_op (tests, old callers) keeps the old main-thread path",
      ep.Endpoint(col_getter=FakeCol, run_on_main=lambda fn, timeout: fn(), approver=lambda t, s: True,
                  ctx_factory=lambda: {}, version="x")._run_op is None)

section("map build: layout without the collection")
FakeOp.made.clear()
got = []
pdf_map._load_graph = lambda: {"pdfs": [], "edges": []}
filled = []
pdf_map._fill_retention = lambda g: filled.append(g)
pdf_map.start_graph_build(got.append, lambda e: got.append(("fail", e)))
check("two ops", len(FakeOp.made) == 2)
check("the layout op does not hold the collection", FakeOp.made[0].no_col)
check("the retention fill does (it reads FSRS data)", not FakeOp.made[1].no_col and filled)
check("the finished graph reaches done", got == [{"pdfs": [], "edges": []}])

section("Preferences closes on profile switch without prompting")
prompts, closed = [], []
dlg = manage_models._KlausManageDialog()
base = manage_models._KlausManageDialog.__mro__[1]
base.reject = lambda self: closed.append(True)
dlg.confirm_close_cb = lambda: prompts.append("Discard changes?")
dlg.reject()
check("sanity: a normal close still prompts", prompts and not closed)
prompts.clear()
timer = type("Timer", (), {"stopped": False, "stop": lambda self: setattr(self, "stopped", True)})()
cancel = threading.Event()
manage_models._close_for_profile(dlg, timer, {"active": True, "kind": "index", "cancel": cancel})
check("profile close skips the prompt and closes", not prompts and closed)
check("the pending preview tick is stopped", timer.stopped)
check("a running index is cancelled", cancel.is_set())

section("K-305: smaller audit findings")
import os  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

_init = open("klausmate/__init__.py", encoding="utf-8").read()
_pat = re.search(r'setWebExports\(\s*__name__,.*?\br"([^"]+)"', _init, re.S).group(1)
check("an upper-case background extension is served (IMG_1234.JPG was refused)",
      re.fullmatch(_pat, "user_files/backgrounds/IMG_1234.JPG") is not None
      and re.fullmatch(_pat, "user_files/backgrounds/x.png") is not None
      and re.fullmatch(_pat, "user_files/backgrounds/x.exe") is None)

retention = importlib.import_module("klausmate.retention")
tag_sync = importlib.import_module("klausmate.tag_sync")
pdf_handler = importlib.import_module("klausmate.pdf_handler")
retention.USER_FILES = tempfile.mkdtemp(prefix="klaus-k305-")
_real_write = pdf_handler._atomic_write_json


def _slow_write(path, data, **kw):
    time.sleep(0.02)  # widen the read-modify-write window
    _real_write(path, data, **kw)


pdf_handler._atomic_write_json = _slow_write
try:
    a = threading.Thread(target=lambda: retention.set_threshold("A", 0.6))
    b = threading.Thread(target=lambda: tag_sync.set_stored_tag("B", "!Library::B"))
    a.start(); time.sleep(0.005); b.start(); a.join(); b.join()
finally:
    pdf_handler._atomic_write_json = _real_write
_prefs = retention._load_prefs()
check("concurrent prefs writers both survive (the lock serializes them)",
      _prefs.get("A", {}).get("threshold") == 0.6 and _prefs.get("B", {}).get("tag") == "!Library::B",
      str(_prefs))

_ci = importlib.import_module("klausmate.card_index")
_loads = []
_real_load = _ci.load
_ci.load = lambda d: (_loads.append(d), None)[1]
try:
    out = tag_sync._cached_matches_many(["a", "b", "c"], {})
finally:
    _ci.load = _real_load
check("batch retags load the card index once, not once per PDF",
      len(_loads) == 1 and out == {"a": None, "b": None, "c": None})

_bt = open("klausmate/browse_toolkit.py", encoding="utf-8").read()
check("the duplicate scan runs without the collection; only the row "
      "texts are fetched with it",
      "op = QueryOp(parent=mw, op=work, success=with_texts)" in _bt
      and "op.without_collection().run_in_background()" in _bt
      and "op2 = QueryOp(parent=mw, op=texts, success=done)" in _bt)
_mm = open("klausmate/manage_models.py", encoding="utf-8").read()
check("Preferences stops its preview timer on every close",
      "dlg.finished.connect(lambda _result: _preview_timer.stop())" in _mm)
_pd = open("klausmate/pdf_drive.py", encoding="utf-8").read()
_la = open("klausmate/library_actions.py", encoding="utf-8").read()
check("the /tmp debug log is gone", "klausmate-debug" not in _pd and "_dbg(" not in _pd)
check("context menus and the threshold dialog are freed",
      "dlg.finished.connect(dlg.deleteLater)" in _la
      # The ＋ menu moved from __init__ into the reader (PDF reader 3/5).
      and "menu.deleteLater()" in open("klausmate/pdf_viewer.py", encoding="utf-8").read())

raise SystemExit(report())
