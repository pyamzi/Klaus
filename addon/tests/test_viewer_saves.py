"""PDF reader 1/5: the viewer saves through SavePipeline.

The pdf.js viewer keeps its synchronous JSON write, then hands the bake to
``annotation_save.pipeline().request(name)`` — no private timer. It reacts
to the pipeline's "records" (reload its marks) and "failed" (toast) for its
own document; the profile-close hook flushes pending saves. (The native
viewer this file also covered was deleted in PDF reader 5/5.)

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_viewer_saves.py
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")  # pristine output
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _qt_getattr(name):
    for module in (QtWidgets, QtCore, QtGui):
        if hasattr(module, name):
            return getattr(module, name)
    if name == "qconnect":
        return lambda signal, callback: signal.connect(callback)
    raise AttributeError(name)


shim.__getattr__ = _qt_getattr
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["klaus-test"])

TMP = tempfile.mkdtemp(prefix="klaus_viewer_saves_")
sys.modules["klausmate"].USER_FILES = TMP  # pre-settings layout
try:  # the settings seam, where it exists
    importlib.import_module("klausmate.settings").user_files_dir = TMP
except Exception:
    pass

ph = importlib.import_module("klausmate.pdf_handler")
asv = importlib.import_module("klausmate.annotation_save")
src = importlib.import_module("klausmate.pdf_source")
rp = importlib.import_module("klausmate.reader_panel")
pj = importlib.import_module("klausmate.pdfjs_viewer")
COPY = "Marks couldn't be saved into the file yet; they're kept and will retry."

section("user_files_dir(): settings seam when present, USER_FILES otherwise")
pkg = sys.modules["klausmate"]
_MISSING = object()
saved_mod = sys.modules.get("klausmate.settings", _MISSING)
saved_attr = getattr(pkg, "settings", _MISSING)
fake_settings = types.ModuleType("klausmate.settings")
fake_settings.user_files = lambda: os.path.join(TMP, "from-settings")
try:
    sys.modules["klausmate.settings"] = fake_settings
    pkg.settings = fake_settings
    check("with a settings module: settings.user_files()",
          src.user_files_dir() == os.path.join(TMP, "from-settings"))
    sys.modules["klausmate.settings"] = None  # import raises ImportError
    if hasattr(pkg, "settings"):
        del pkg.settings
    check("without one: the package's USER_FILES", src.user_files_dir() == TMP)
finally:
    if saved_mod is _MISSING:
        sys.modules.pop("klausmate.settings", None)
    else:
        sys.modules["klausmate.settings"] = saved_mod
    if saved_attr is not _MISSING:
        pkg.settings = saved_attr
    elif hasattr(pkg, "settings"):
        del pkg.settings

UFD = os.path.join(TMP, "ufd")  # every viewer path below resolves here
src.user_files_dir = lambda: UFD
check("pdf.js snapshots under <user_files_dir()>/reading",
      pj._reading_dir() == os.path.join(UFD, "reading"))


class FakePipe:
    def __init__(self):
        self.requests = []
        self.subs = []

    def request(self, name):
        self.requests.append(name)

    def subscribe(self, cb):
        self.subs.append(cb)

        def off():
            if cb in self.subs:
                self.subs.remove(cb)

        return off


PIPE = FakePipe()
asv.pipeline = lambda: PIPE
saved_json = []
ph.save_annotations = lambda ufd, name, hl: saved_json.append((name, list(hl))) or True  # written
loaded = []
ph.load_annotations = lambda ufd, name: loaded.append((ufd, name)) or [{"id": "r"}]
ph.load_annotations_strict = ph.load_annotations  # the viewer's re-reads use the strict form

section("copy constant")
check("exact failure copy, defined once", asv.SAVE_FAILED_COPY == COPY)

label, cls = "pdf.js", pj.PdfJsViewer
section(f"{label}: no private bake timer")
body = inspect.getsource(cls)
for gone in ("_on_bake_timer", "_bake_timer", "_bake_pending",
             "_bake_running", "_bake_lock"):
    check(f"{gone} is gone", gone not in body and not hasattr(cls, gone))
check("never bakes by itself", "bake_annotations" not in body)
# _schedule_bake survives only as a forwarder: its call sites are lines
# another session has uncommitted edits on (R26).
shim_src = inspect.getsource(cls._schedule_bake)
check("_schedule_bake only forwards to the pipeline",
      "pipeline().request(name)" in shim_src and "QTimer" not in shim_src)

section(f"{label}: a save is one JSON write + one pipeline request")


class Fake:
    _save_annotations = cls._save_annotations
    _schedule_bake = cls._schedule_bake


f = Fake()
f._annotations_name, f._highlights = "A", [{"id": "h1"}]
PIPE.requests.clear()
saved_json.clear()
f._save_annotations()
check("JSON written synchronously", saved_json == [("A", [{"id": "h1"}])])
check("pipeline().request(name) called once", PIPE.requests == ["A"])
f._annotations_name = None
f._save_annotations()
check("no document: no request", PIPE.requests == ["A"])

section(f"{label}: pipeline events for its own document")
tips = []
pj.tooltip = lambda text, *a, **k: tips.append(text)
g = types.SimpleNamespace(_annotations_name="A", _highlights=[], redraws=0, _save_failed=False)
g._refresh_highlight_overlay = lambda: setattr(g, "redraws", g.redraws + 1)
loaded.clear()
cls._on_save_event(g, "failed", "A")
check("'failed' shows the exact copy", tips == [COPY])
cls._on_save_event(g, "failed", "B")
cls._on_save_event(g, "records", "B")
check("another document's events are ignored",
      tips == [COPY] and loaded == [] and g.redraws == 0)
cls._on_save_event(g, "records", "A")
check("'records' reloads this viewer's marks",
      loaded == [(UFD, "A")] and g._highlights == [{"id": "r"}]
      and g.redraws == 1)
cls._on_save_event(g, "saved", "A")
check("'saved' with the marks already shown redraws nothing", tips == [COPY] and g.redraws == 1)

section("pdf.js: subscribes in __init__, unsubscribes in cleanup")
init_src = inspect.getsource(pj.PdfJsViewer.__init__)
check("__init__ subscribes",
      "subscribe(self._on_save_event)" in "".join(init_src.split()))
check("cleanup unsubscribes", "_unsub_save" in inspect.getsource(pj.PdfJsViewer.cleanup))

section("no module-wide 'saved' hook: doc_sync's exact pin replaced it (R28)")
check("PdfSidebar.__init__ subscribes nothing to the pipeline",
      "pipeline()" not in inspect.getsource(rp.PdfSidebar.__init__))

section("profile close flushes pending saves first")
init_path = os.path.join(os.path.dirname(rp.__file__), "__init__.py")
with open(init_path, encoding="utf-8") as fh:
    init_text = fh.read()
fn = next(n for n in ast.parse(init_text).body
          if isinstance(n, ast.FunctionDef) and n.name == "_flush_annotation_saves")
ns = {"__package__": "klausmate", "__name__": "klausmate._flush_test"}
exec(compile(ast.Module(body=[fn], type_ignores=[]), init_path, "exec"), ns)
flushed = []
asv.flush_all = lambda: flushed.append(True)
ns["_flush_annotation_saves"]()
check("hook calls annotation_save.flush_all()", flushed == [True])


def _boom():
    raise RuntimeError("disk gone")


asv.flush_all = _boom
logs = []
ns["print"] = lambda *a, **k: logs.append(" ".join(map(str, a)))
ns["_flush_annotation_saves"]()
check("a failing flush is logged, not raised",
      len(logs) == 1 and logs[0].startswith("[klausmate]"))
reg = init_text.find("profile_will_close.append(_flush_annotation_saves)")
sweep = init_text.find("profile_will_close.append(\n        _reader_panel_cleanup.cleanup_all_sidebars")
check("registered before the sidebar sweep", 0 <= reg < sweep)

raise SystemExit(report())
