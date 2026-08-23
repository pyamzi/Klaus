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
pdf_drive, deck_curate) needs install_aqt_stubs() as well.

Usage:
    from anki_stubs import install, check, report
    install()                      # package + aqt stubs
    import importlib
    retention = importlib.import_module("klausmate.retention")
    check("weighted retention", abs(got - want) < 1e-9)
    raise SystemExit(report())
"""
import sys
import types

ADDON = "/Users/pyamzi/Documents/Github/Addons/klausmate"

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


def install_aqt_stubs() -> None:
    """Minimal aqt/anki surface for modules that import them at load time."""
    aqt_mod = _stub("aqt", mw=None)
    aqt_mod.dialogs = types.SimpleNamespace(
        open=lambda *a, **k: None,
        register_dialog=lambda *a, **k: None,
        markClosed=lambda *a, **k: None,
    )
    _stub("aqt.operations", CollectionOp=_AnyOp, QueryOp=_AnyOp)
    _stub(
        "aqt.utils",
        tooltip=lambda *a, **k: None,
        askUser=lambda *a, **k: False,
        showWarning=lambda *a, **k: None,
        showInfo=lambda *a, **k: None,
        openLink=lambda *a, **k: None,
    )
    _stub(
        "aqt.qt",
        QAction=object,
        QInputDialog=object,
        QMessageBox=object,
        QTimer=types.SimpleNamespace(singleShot=lambda *a, **k: None),
        qconnect=lambda *a, **k: None,
    )
    gh = _stub("aqt.gui_hooks")
    aqt_mod.gui_hooks = gh
    _stub("anki")
    _stub("anki.collection", AddNoteRequest=object)


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
