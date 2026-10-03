"""GitHub #18: the first-run "Choose a folder now?" Library move must
never leave moved PDFs without a recorded ``library_root``.

The move runs in a background QueryOp whose success callback is fenced
by ``_profile_generation`` (dropped on profile switch) and is never
delivered at all on quit. The root therefore has to be persisted before
the move starts; unmapped PDFs still resolve from the legacy store.

Every resolution below goes through ``pdf_path_for(uf, name)`` WITHOUT
``root=``, so it reads the root from config exactly as production does.
"""
import importlib
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

import klaus_note.settings as settings  # noqa: E402
pdf_handler = importlib.import_module("klaus_note.pdf_handler")
setup_flow = importlib.import_module("klaus_note.setup_flow")

NAMES = [f"lecture{i}" for i in range(4)]


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in self.slots:
            fn(*a)


class _FakeMsg:
    """The folder prompt; ``answer`` picks Yes or No."""

    def __init__(self, answer):
        self.answer = answer
        self.finished = _Signal()

    def __getattr__(self, _name):
        return lambda *a, **k: None

    def clickedButton(self):
        return self.answer

    def standardButton(self, clicked):
        return setup_flow.QMessageBox.StandardButton.Yes if clicked == "yes" else None

    def button(self, *_a):
        return None

    def open(self):
        self.finished.emit(0)


class _FakeOp:
    """Captures do/success; the test decides when (and whether) they run."""

    last = None

    def __init__(self, parent=None, op=None, success=None):
        self.op, self.on_success = op, success
        _FakeOp.last = self

    def failure(self, fn):
        self.on_failure = fn
        return self

    def without_collection(self):
        return self

    def run_in_background(self):
        pass


class _ImmediateTimer:
    @staticmethod
    def singleShot(_ms, fn):
        fn()


def _fresh_library():
    uf = tempfile.mkdtemp(prefix="klaus-uf-")
    chosen = tempfile.mkdtemp(prefix="klaus-lib-")
    for sub in ("contexts", "pdfs"):
        os.makedirs(os.path.join(uf, sub))
    for name in NAMES:
        open(os.path.join(uf, "contexts", name + ".txt"), "w").write("ctx")
        open(os.path.join(uf, "pdfs", name + ".pdf"), "wb").write(b"%PDF-" + name.encode())
    settings.user_files_dir = uf
    settings.store = settings.DictStore({})
    return uf, chosen


def _run_prompt(answer, chosen):
    """Drive _library_root_check: answer the prompt, pick ``chosen``."""
    _FakeOp.last = None
    setup_flow._themed_message_box = lambda *_a: _FakeMsg(answer)
    setup_flow.QueryOp = _FakeOp
    setup_flow.QTimer = _ImmediateTimer
    sys.modules["aqt.qt"].QFileDialog = type(
        "QFileDialog", (), {"getExistingDirectory": staticmethod(lambda *a: chosen)}
    )
    continued = []
    setup_flow._library_root_check(lambda: continued.append(True))
    return continued


def _resolves_everywhere(uf):
    return {n: pdf_handler.pdf_path_for(uf, n) for n in NAMES}


section("dropped success callback (profile switched mid-move)")
uf, chosen = _fresh_library()
continued = _run_prompt("yes", chosen)
op = _FakeOp.last
check("the move was started in the background", op is not None and continued == [True])
result = op.op(None)  # the worker finishes the whole move...
setup_flow._profile_generation += 1  # ...but the profile closed first
op.on_success(result)
check("every PDF moved", sorted(result["moved"]) == NAMES, str(result))
check("library_root is recorded", settings.read().get("library_root") == chosen, str(settings.read()))
paths = _resolves_everywhere(uf)
check("every moved PDF still resolves", all(paths.values()), str(paths))
check("they resolve under the chosen folder",
      all(p and p.startswith(chosen) for p in paths.values()), str(paths))

section("callback never delivered (quit mid-move)")
uf, chosen = _fresh_library()
_run_prompt("yes", chosen)
_FakeOp.last.op(None)  # worker runs during shutdown; no callback at all
check("library_root is recorded without the callback",
      settings.read().get("library_root") == chosen, str(settings.read()))
check("every moved PDF still resolves", all(_resolves_everywhere(uf).values()))

section("move interrupted after N of M files")
uf, chosen = _fresh_library()
_run_prompt("yes", chosen)
n = 2
real_list = pdf_handler.list_contexts
pdf_handler.list_contexts = lambda d: real_list(d)[:n]
try:
    partial = _FakeOp.last.op(None)
finally:
    pdf_handler.list_contexts = real_list
check("only the first N moved", sorted(partial["moved"]) == NAMES[:n], str(partial))
paths = _resolves_everywhere(uf)
check("every PDF resolves", all(paths.values()), str(paths))
check("moved ones resolve under the new root",
      all((paths[x] or "").startswith(chosen) for x in NAMES[:n]), str(paths))
legacy = os.path.join(uf, "pdfs")
check("the rest resolve from the legacy store",
      all((paths[x] or "").startswith(legacy) for x in NAMES[n:]), str(paths))

section("a failed file stays resolvable from the legacy store")
uf, chosen = _fresh_library()
_run_prompt("yes", chosen)
real_copy = pdf_handler.shutil.copy2


def _flaky_copy(src, dst, *a, **k):
    if os.path.basename(src) == NAMES[1] + ".pdf":
        raise OSError("disk full")
    return real_copy(src, dst, *a, **k)


pdf_handler.shutil.copy2 = _flaky_copy
try:
    res = _FakeOp.last.op(None)
finally:
    pdf_handler.shutil.copy2 = real_copy
check("one file failed", list(res["failed"]) == [NAMES[1]], str(res))
check("every PDF resolves", all(_resolves_everywhere(uf).values()))

section("declining writes nothing")
uf, chosen = _fresh_library()
continued = _run_prompt("no", chosen)
check("no move started", _FakeOp.last is None)
check("flow continues", continued == [True])
check("config untouched", "library_root" not in settings.read(), str(settings.read()))

section("cancelling the folder picker writes nothing")
uf, _ = _fresh_library()
continued = _run_prompt("yes", "")
check("no move started", _FakeOp.last is None)
check("config untouched", "library_root" not in settings.read(), str(settings.read()))

raise SystemExit(report())
