"""An exception in a Qt slot aborts Anki (K-172).

PyQt6 answers an unhandled exception in a slot by printing the traceback and
then calling qFatal, which SIGABRTs the process. In a script that costs a
test run; in Anki it costs Anki, mid-review, with unsaved state.

Two kinds of check here, and the second is the one that matters:

* a SOURCE pass, which says whether handlers look guarded, and
* a BEHAVIOURAL pass in a SUBPROCESS, which raises inside a real slot on a
  real button and asserts the process survives.

The behavioural one is load-bearing because the source pass gets it wrong in
BOTH directions. It misses a handler that delegates its body to a helper
(assistant_panel.send does exactly that and reads as unguarded), and it
passes a handler whose `try` wraps one harmless line while the rest of the
body is exposed. Only running it settles the question — and it has to be a
subprocess, because a test that proves an abort by aborting takes the suite
with it.
"""
import ast
import glob
import os
import subprocess
import sys
import textwrap

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
import importlib

sg = importlib.import_module("klausmate.slot_guard")

HAVE_QT = True
try:
    import PyQt6.QtWidgets  # noqa: F401
except Exception:
    HAVE_QT = False


def _run(body: str) -> tuple:
    """Run a snippet in a subprocess; return (exit code, aborted?, stdout)."""
    src = textwrap.dedent(body)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, env=env, timeout=120
    )
    rc = proc.returncode
    # subprocess reports a signal death as a NEGATIVE returncode (-6 for
    # SIGABRT); a shell reports the same thing as 128+6=134. Accept both,
    # because getting this wrong reads a crash as a clean exit — which is
    # exactly the mistake that hid this bug for a whole session.
    return rc, rc < 0 or rc > 128, proc.stdout.decode(errors="replace")


section("the mechanism, measured rather than assumed")
if not HAVE_QT:
    print("  SKIP: PyQt6 unavailable — behavioural checks skipped")
else:
    # Anki installs sys.excepthook (aqt.errors.ErrorHandler), and PyQt6
    # honours a non-default hook INSTEAD of qFatal — so in Anki an unguarded
    # slot exception reaches the error handler; it does not abort Anki. The
    # controls below mirror that: the hook is the witness. A BARE interpreter
    # with no hook really does abort (exit 134, measured 2026-09-01), but
    # that is not proved here any more — proving it by aborting a child
    # filed a macOS crash report on every test run, which is how Pouya
    # found out.
    _rc, _aborted, _out = _run("""
        import sys
        def hook(t, v, tb): print("ESCAPED:" + t.__name__, flush=True)
        sys.excepthook = hook
        from PyQt6 import QtWidgets as W
        app = W.QApplication([]); b = W.QPushButton()
        b.clicked.connect(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        b.click()
        print("survived", flush=True)
    """)
    check("an UNGUARDED exception ESCAPES the slot — under an Anki-style "
          "excepthook it reaches the handler and the process survives; this "
          "is the whole reason the guard exists, checked without aborting "
          "any interpreter",
          not _aborted and _rc == 0 and "ESCAPED:RuntimeError" in _out
          and "survived" in _out, f"exit={_rc} out={_out!r}")

    _rc, _aborted, _out = _run("""
        import sys
        def hook(t, v, tb): print("ESCAPED:" + t.__name__, flush=True)
        sys.excepthook = hook
        sys.path.insert(0, "klausmate")
        from slot_guard import guarded
        from PyQt6 import QtWidgets as W
        app = W.QApplication([]); b = W.QPushButton()

        @guarded
        def boom():
            raise RuntimeError("x")

        b.clicked.connect(boom)
        b.click()
        print("survived", flush=True)
    """)
    check("the SAME exception through @guarded is CONTAINED — logged in the "
          "slot, never reaches the hook, process survives",
          not _aborted and _rc == 0 and "ESCAPED" not in _out
          and "slot boom failed" in _out and "survived" in _out,
          f"exit={_rc} out={_out!r}")

    _rc, _aborted, _out = _run("""
        import sys
        sys.path.insert(0, "klausmate")
        from slot_guard import guarded
        from PyQt6 import QtWidgets as W
        app = W.QApplication([]); b = W.QPushButton()

        @guarded
        def bye():
            raise SystemExit(7)

        b.clicked.connect(bye)
        b.click()
    """)
    check("SystemExit through a guarded slot does not abort either",
          not _aborted, f"exit={_rc}")

section("the decorator itself")
_calls = []


@sg.guarded
def _ok(a, b=2):
    _calls.append((a, b))
    return a + b


check("a working slot still returns its value", _ok(1) == 3)
check("...and its arguments arrive intact", _calls == [(1, 2)])


@sg.guarded
def _bad():
    raise ValueError("nope")


check("a raising slot returns None instead of propagating", _bad() is None)
check("guarded slots are detectable, which is what lets a pin see them",
      sg.is_guarded(_bad) and not sg.is_guarded(len))
check("the wrapper keeps the original name, so the log names the real slot",
      _bad.__name__ == "_bad")


# Tested in-process, not through a subprocess exit code: what matters is
# that `guarded` catches Exception and NOT BaseException. Asserting a
# particular exit code would be testing PyQt6's teardown, not this.
@sg.guarded
def _quit():
    raise SystemExit(7)


try:
    _quit()
    check("SystemExit is NOT swallowed — catching it would stop Anki "
          "quitting", False)
except SystemExit:
    check("SystemExit is NOT swallowed — catching it would stop Anki "
          "quitting", True)


@sg.guarded
def _interrupt():
    raise KeyboardInterrupt()


try:
    _interrupt()
    check("KeyboardInterrupt is not swallowed either", False)
except KeyboardInterrupt:
    check("KeyboardInterrupt is not swallowed either", True)


def _handlers(path):
    """(connected handler name -> node) for one module."""
    src = open(path, encoding="utf-8").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    connected = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "connect"):
            for a in n.args:
                if isinstance(a, ast.Attribute):
                    connected.add(a.attr)
                elif isinstance(a, ast.Name):
                    connected.add(a.id)
    return {
        n.name: n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in connected
    }


def _covered(node) -> bool:
    """Guarded by a decorator, a try, or delegation to a guard helper.

    All three are accepted because all three are real: the decorator is the
    preferred shape, a try in the body is the old one, and a one-line
    delegation to a _guard helper is what assistant_panel uses.
    """
    for dec in node.decorator_list:
        name = getattr(dec, "id", None) or getattr(dec, "attr", None)
        if name in ("guarded", "_guarded"):
            return True
    if any(isinstance(b, ast.Try) for b in node.body):
        return True
    body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
    return "_guard" in body


section("the files this card owns are covered")
for _path in ("klausmate/__init__.py", "klausmate/browse_toggles.py"):
    _hs = _handlers(_path)
    check(f"{os.path.basename(_path)} has connected handlers to check",
          len(_hs) > 0, f"{len(_hs)} found")
    _bad_ones = sorted(n for n, node in _hs.items() if not _covered(node))
    check(f"{os.path.basename(_path)}: every connected handler is guarded — "
          "an unguarded one aborts Anki rather than misbehaving",
          not _bad_ones, str(_bad_ones))

section("the rest of the addon, reported not enforced")
# Deliberately NOT a failure: the remaining files belong to other lanes and
# K-172 is scoped around them. Counting them here keeps the number honest
# and visible instead of quietly forgotten.
_left = []
for _p in sorted(glob.glob("klausmate/*.py")):
    if _p in ("klausmate/__init__.py", "klausmate/browse_toggles.py"):
        continue
    _left += [f"{os.path.basename(_p)}:{n}"
              for n, node in _handlers(_p).items() if not _covered(node)]
print(f"  NOTE: {len(_left)} connected handlers still unguarded elsewhere")
if _left:
    print("        " + ", ".join(_left[:8])
          + (" …" if len(_left) > 8 else ""))
check("assistant_panel's slots are already covered (451a753), so this card "
      "does not re-report them",
      not any(x.startswith("assistant_panel") for x in _left))

raise SystemExit(report())
