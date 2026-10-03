"""Headless test bootstrap for the klaus_note Anki addon.

Why this exists: Anki 26.8.1 ships Python **3.13 bytecode only** (in
/Applications/Anki.app/Contents/Resources/app_packages) and this machine's
`python3` is 3.9, so `import aqt` raises "bad magic number". PyQt6 is no
help either — its `sip` is a 3.13-only extension, not abi3. Real Anki
modules therefore cannot be imported at all under the available
interpreter.

The workaround: register a synthetic `klaus_note` package plus stub
aqt/anki modules in sys.modules *before* importing the module under test.
Anything aqt-free (embeddings, card_index, pdf_index, drive_store) needs
only the package stub; anything importing aqt (retention, curation,
pdf_drive, pdf_drop, ...) needs install_aqt_stubs() as well.

Usage:
    from anki_stubs import install, check, report
    install()                      # package + aqt stubs
    import importlib
    retention = importlib.import_module("klaus_note.retention")
    check("weighted retention", abs(got - want) < 1e-9)
    raise SystemExit(report())

## The permissive Qt/aqt/anki surface

klaus_note imports a *lot* of names out of `aqt.qt` (every PyQt6 widget/
enum class it touches), plus a handful of names out of `aqt.editor`,
`aqt.webview`, `aqt.deckbrowser`, `aqt.preferences`, `anki.hooks` and
`anki.utils`. Hand-enumerating all of those (and keeping the list in sync
as the addon grows) is exactly the kind of stub drift that let
`klaus_note.pdf_drive` and `klaus_note.pdf_drop` go completely
import-untested — the old stub only defined QAction, QInputDialog,
QMessageBox, QTimer and qconnect.

Instead, every stubbed aqt/anki module here is *permissive*: an
undeclared attribute auto-vivifies into a `_Dummy` (see below) rather than
raising AttributeError/ImportError. `_Dummy` works as:
  - a base class (`class DriveWindow(QWidget): ...`),
  - a constructor (`QColor(58, 130, 247)`),
  - a chainable attribute/enum namespace (`Qt.ItemDataRole.UserRole`),
  - and something you can do enum-flag arithmetic on
    (`Qt.ItemDataRole.UserRole + 1`, which pdf_drive.py does at module
    level).

This is deliberately loose: it does not try to model real Qt behaviour.
But it never hides an error in OUR code — a name that doesn't exist in
klaus_note itself, a real syntax error, a bad relative import, a genuine
NameError in module-level code, etc. still raise normally, because those
happen independent of (or before) any attribute lookup on these
stand-ins. The catch-all only ever satisfies lookups *into aqt/anki*,
which is exactly the surface klaus_note does not own.
"""
from __future__ import annotations

import importlib
import os
import copy
import sys
import types

# Repo root derived from this file's own location (four levels up from
# .claude/skills/klaus-test/scripts/) so renaming the repo folder can
# never silently break the harness — a hardcoded path did exactly that
# when Addons/ became klaus-note-addon/ (2026-08-25).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)
ADDON = os.path.join(_REPO_ROOT, "klaus_note")

_PASS = 0
_FAIL = 0


def _purge_stale_bytecode(addon_dir: str) -> None:
    """Guarantee the tests execute the SOURCE they are asserting on.

    Python decides a cached .pyc is still valid from (mtime, size) alone.
    Editing a value to another of the SAME LENGTH within the same second
    — `0.85` -> `0.40`, exactly what a self-falsification check does —
    keeps both equal, so the stale bytecode is reused and the suite runs
    code that is no longer on disk. That really happened here: a pin was
    reported failing against a file that already held the correct value.

    Worse, `rm -rf klaus_note/__pycache__` does NOT fix it on this Mac:
    the system Python sets sys.pycache_prefix, so caches live in a MIRROR
    tree under ~/Library/Caches/com.apple.python/<abs source path>/. And
    `python3 -B` only stops bytecode being WRITTEN, not read.

    So: stop writing it, drop both cache locations, and re-scan.
    """
    import shutil

    sys.dont_write_bytecode = True
    roots = [os.path.join(addon_dir, "__pycache__")]
    prefix = getattr(sys, "pycache_prefix", None)
    if prefix:
        # The mirror tree mangles the absolute source path under prefix.
        roots.append(os.path.join(prefix, addon_dir.lstrip(os.sep),
                                  "__pycache__"))
    for root in roots:
        shutil.rmtree(root, ignore_errors=True)
    importlib.invalidate_caches()


_MIRROR: str | None = None


def _scratch_mirror(addon_dir: str) -> str:
    """A temp copy of the package made of symlinks, with an EMPTY user_files/.

    klaus_note/ is symlinked into Anki's addons21, and curation, retention
    and anki_tools derive USER_FILES from `os.path.dirname(__file__)` at
    import time — so a test that imports them and writes (drive_store,
    library_map.json, pdf_index/prefs.json, contexts/*.txt) writes the
    user's REAL Library. That happened on 2026-09-28 (test_library_sync).
    Importing the package from this mirror makes every `__file__`-derived
    path land in scratch by construction; no list of globals to patch.
    """
    import atexit
    import shutil
    import tempfile

    root = tempfile.mkdtemp(prefix="klaus-note-test-")
    # rmtree unlinks the symlinks, it never descends into the real addon.
    atexit.register(shutil.rmtree, root, True)
    mirror = os.path.join(root, "klaus_note")
    os.mkdir(mirror)
    for name in os.listdir(addon_dir):
        if name not in ("user_files", "__pycache__"):
            os.symlink(os.path.join(addon_dir, name), os.path.join(mirror, name))
    os.mkdir(os.path.join(mirror, "user_files"))
    return mirror


def install_package_stub(addon_dir: str = ADDON) -> None:
    """Make `import klaus_note.<mod>` resolve to the working tree, with
    USER_FILES in a fresh temp dir (see _scratch_mirror)."""
    global _MIRROR
    _purge_stale_bytecode(addon_dir)
    _MIRROR = _scratch_mirror(addon_dir)
    pkg = types.ModuleType("klaus_note")
    pkg.__path__ = [_MIRROR]
    pkg.__package__ = "klaus_note"
    sys.modules["klaus_note"] = pkg
    # klaus_note.settings derives user_files_dir from its own (mirrored)
    # location, so it lands in the mirror's fresh user_files on its own.


def _stub(name: str, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class _AnyOp:
    """Stands in for QueryOp / CollectionOp: chainable, never runs."""

    def __init__(self, *a, **k):
        pass

    def success(self, *a, **k):
        return self

    def failure(self, *a, **k):
        return self

    def without_collection(self):
        return self

    def run_in_background(self):
        pass


class _DummyMeta(type):
    """Metaclass for `_Dummy` subclasses so that attribute/arithmetic
    access works even on the *class object itself* — needed because
    klaus_note uses some aqt.qt names directly as enum namespaces rather
    than instances (``Qt.ItemDataRole.UserRole``, at module level in
    pdf_drive.py), not just as base classes.
    """

    def __getattr__(cls, name):  # class.attr fallback (e.g. Qt.ItemDataRole)
        return cls

    def __add__(cls, other):
        return cls

    __radd__ = __sub__ = __rsub__ = __and__ = __rand__ = __or__ = __ror__ = __add__

    def __repr__(cls):
        return f"<Dummy {cls.__name__}>"


class _Dummy(metaclass=_DummyMeta):
    """Generic permissive stand-in. See module docstring."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):  # instance.attr fallback
        return _Dummy()

    def __call__(self, *a, **k):
        return _Dummy()

    def __add__(self, other):
        return _Dummy()

    __radd__ = __sub__ = __rsub__ = __and__ = __rand__ = __or__ = __ror__ = __add__

    def __bool__(self):
        return True

    def __repr__(self):
        return "<Dummy instance>"


_dummy_class_cache: dict[str, type] = {}


def _dummy_class(name: str) -> type:
    """A distinct `_Dummy` subclass per requested name, cached. Distinct
    types (rather than one shared object) avoid a hypothetical "duplicate
    base class" TypeError if some future class ever multiply-inherits
    from two different stubbed Qt names.
    """
    cls = _dummy_class_cache.get(name)
    if cls is None:
        cls = _DummyMeta(name, (_Dummy,), {})
        _dummy_class_cache[name] = cls
    return cls


def _permissive_module(name: str, **explicit) -> types.ModuleType:
    """A stub module whose undeclared attributes auto-vivify to a
    per-name `_Dummy` subclass, via PEP 562 module `__getattr__`.
    `explicit` overrides specific names with real (usually no-op)
    behaviour instead of a dummy class — e.g. `qconnect` needs to be a
    plain callable, not something you'd subclass.
    """
    mod = types.ModuleType(name)
    for k, v in explicit.items():
        setattr(mod, k, v)

    def __getattr__(item, _explicit=frozenset(explicit)):
        return _dummy_class(item)

    mod.__getattr__ = __getattr__
    sys.modules[name] = mod
    return mod


def _permissive_namespace() -> _Dummy:
    """A single reusable auto-vivifying instance for aqt.mw and similar
    "one object with lots of chained attributes" spots (mw.addonManager.
    setWebExports(...), mw.app.aboutToQuit.connect(...), ...).
    """
    return _Dummy()


def install_aqt_stubs() -> None:
    """Permissive aqt/anki surface for modules that import them at load
    time. Covers every `aqt.*`/`anki.*` module klaus_note imports from
    (grepped across klaus_note/*.py — see module docstring), not just
    aqt.qt.
    """
    aqt_mod = _permissive_module("aqt", mw=_permissive_namespace())
    aqt_mod.dialogs = types.SimpleNamespace(
        open=lambda *a, **k: None,
        register_dialog=lambda *a, **k: None,
        markClosed=lambda *a, **k: None,
    )
    _permissive_module("aqt.operations", CollectionOp=_AnyOp, QueryOp=_AnyOp)
    _permissive_module(
        "aqt.utils",
        tooltip=lambda *a, **k: None,
        askUser=lambda *a, **k: False,
        showWarning=lambda *a, **k: None,
        showInfo=lambda *a, **k: None,
        openLink=lambda *a, **k: None,
    )
    _permissive_module("aqt.qt", qconnect=lambda *a, **k: None)
    gh = _permissive_module("aqt.gui_hooks")
    aqt_mod.gui_hooks = gh
    _permissive_module("aqt.editor")          # Editor, EditorWebView
    _permissive_module("aqt.webview")         # WebContent, AnkiWebView
    _permissive_module("aqt.deckbrowser")     # DeckBrowser, DeckBrowserBottomBar
    _permissive_module("aqt.preferences")     # Preferences
    _permissive_module("aqt.main")            # AnkiQt (type-hint only)
    _stub("anki")
    _permissive_module("anki.collection", AddNoteRequest=_dummy_class("AddNoteRequest"))
    _permissive_module("anki.hooks")          # wrap
    _permissive_module("anki.utils")          # strip_html


def install(addon_dir: str = ADDON) -> None:
    install_package_stub(addon_dir)
    install_aqt_stubs()


def exec_klaus_note_under_qt(scratch_user_files: str, addon_dir: str | None = None):
    """Execute klaus_note/__init__.py as a module under REAL PyQt6 with the
    aqt/anki stubs in place, and point its USER_FILES at ``scratch``.

    Returns the module namespace. Needs QT_QPA_PLATFORM=offscreen, a
    QApplication already constructed, and install() already run — the
    permissive aqt stubs (mw, gui_hooks, aqt.editor, ...) are what let
    __init__.py's module-level bootstrap run at all; only `aqt.qt` is
    swapped for the real Qt here. The two hand-rolled copies in
    test_slot_guards.py and test_bridge_reentrancy.py predate this.
    """
    import importlib.util

    from PyQt6 import QtCore, QtGui, QtWidgets

    # The mirror, not ADDON: submodules __init__.py imports resolve through
    # this path, and from the real dir curation.USER_FILES is the Library.
    assert _MIRROR, "call install() first"
    addon_dir = addon_dir or _MIRROR

    shim = types.ModuleType("aqt.qt")
    for mod in (QtCore, QtGui, QtWidgets):
        for name in dir(mod):
            if not name.startswith("_"):
                setattr(shim, name, getattr(mod, name))
    shim.qconnect = lambda sig, fn: sig.connect(fn)
    sys.modules["aqt.qt"] = shim
    sys.modules["aqt"].qt = shim
    spec = importlib.util.spec_from_file_location(
        "klaus_note", os.path.join(addon_dir, "__init__.py"),
        submodule_search_locations=[addon_dir])
    module = importlib.util.module_from_spec(spec)
    settings = importlib.import_module("klaus_note.settings")  # resolves through the stub's path
    settings.user_files_dir = scratch_user_files
    sys.modules["klaus_note"] = module
    spec.loader.exec_module(module)
    # __init__ installed the stub mw as settings' profile token and main-thread
    # hop; the stub answers every attribute with a NEW _Dummy, so the fence
    # would drop every patch and the hop would swallow it. Tests that want
    # the fence install their own (tests/test_settings.py).
    settings.run_on_main = None
    settings.current_profile = None
    return module


# ----------------------------------------------------------- assertions


def check(name: str, cond, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ok  {name}")
    else:
        _FAIL += 1
        print(f" FAIL {name} {detail}")


def section(title: str) -> None:
    print(f"== {title} ==")


def report() -> int:
    """Print the tally; return an exit code for `raise SystemExit(report())`."""
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


class LiveStore:
    """``settings.store`` over a LIVE dict: reads copy it, so a test may
    mutate ``cfg`` between calls; each write replaces it and is recorded
    in ``writes``."""

    def __init__(self, cfg: dict, writes: list | None = None) -> None:
        self.cfg = cfg
        self.writes = writes if writes is not None else []

    def read(self) -> dict:
        return copy.deepcopy(self.cfg)

    def write(self, cfg: dict) -> None:
        self.cfg.clear()
        self.cfg.update(copy.deepcopy(cfg))
        self.writes.append(copy.deepcopy(cfg))


def code_only(src: str) -> str:
    """Source with comments AND string literals removed, layout kept.

    Source-pin tests assert on the TEXT of klaus_note modules, so any pin
    can be silently satisfied — or silently broken — by prose that merely
    *mentions* the thing it looks for. That has now bitten four separate
    checks in this repo (a commented-out `dlg.exec()`, a `painter.end()`
    named in a docstring, an ordering pin fooled by a docstring naming
    the calls in the opposite order). Pins that care about real code
    should read this instead of the raw source.

    Falls back to crude line-wise comment stripping if the source will
    not tokenize, so a syntax error surfaces as a failing pin rather
    than a crashing test file.
    """
    import io
    import tokenize

    try:
        kept = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        ]
        return tokenize.untokenize(kept)
    except Exception:
        return "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
