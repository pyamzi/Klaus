"""Headless test bootstrap for the klausmate Anki addon.

Why this exists: Anki 26.8.1 ships Python **3.13 bytecode only** (in
/Applications/Anki.app/Contents/Resources/app_packages) and this machine's
`python3` is 3.9, so `import aqt` raises "bad magic number". PyQt6 is no
help either — its `sip` is a 3.13-only extension, not abi3. Real Anki
modules therefore cannot be imported at all under the available
interpreter.

The workaround: register a synthetic `klausmate` package plus stub
aqt/anki modules in sys.modules *before* importing the module under test.
Anything aqt-free (embeddings, card_index, pdf_index, drive_store) needs
only the package stub; anything importing aqt (retention, curation,
pdf_drive, deck_curate, ...) needs install_aqt_stubs() as well.

Usage:
    from anki_stubs import install, check, report
    install()                      # package + aqt stubs
    import importlib
    retention = importlib.import_module("klausmate.retention")
    check("weighted retention", abs(got - want) < 1e-9)
    raise SystemExit(report())

## The permissive Qt/aqt/anki surface

klausmate imports a *lot* of names out of `aqt.qt` (every PyQt6 widget/
enum class it touches), plus a handful of names out of `aqt.editor`,
`aqt.webview`, `aqt.deckbrowser`, `aqt.preferences`, `anki.hooks` and
`anki.utils`. Hand-enumerating all of those (and keeping the list in sync
as the addon grows) is exactly the kind of stub drift that let
`klausmate.pdf_drive` and `klausmate.deck_curate` go completely
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
klausmate itself, a real syntax error, a bad relative import, a genuine
NameError in module-level code, etc. still raise normally, because those
happen independent of (or before) any attribute lookup on these
stand-ins. The catch-all only ever satisfies lookups *into aqt/anki*,
which is exactly the surface klausmate does not own.
"""
from __future__ import annotations

import os
import sys
import types

# Repo root derived from this file's own location (four levels up from
# .claude/skills/klaus-test/scripts/) so renaming the repo folder can
# never silently break the harness — a hardcoded path did exactly that
# when Addons/ became KlausMate-Context/ (2026-08-25).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)
ADDON = os.path.join(_REPO_ROOT, "klausmate")

_PASS = 0
_FAIL = 0


def install_package_stub(addon_dir: str = ADDON) -> None:
    """Make `import klausmate.<mod>` resolve to the working tree."""
    pkg = types.ModuleType("klausmate")
    pkg.__path__ = [addon_dir]
    pkg.__package__ = "klausmate"
    sys.modules["klausmate"] = pkg


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
    klausmate uses some aqt.qt names directly as enum namespaces rather
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
    time. Covers every `aqt.*`/`anki.*` module klausmate imports from
    (grepped across klausmate/*.py — see module docstring), not just
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


def code_only(src: str) -> str:
    """Source with comments AND string literals removed, layout kept.

    Source-pin tests assert on the TEXT of klausmate modules, so any pin
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
