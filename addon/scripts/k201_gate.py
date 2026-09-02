"""K-201 gate: the idle-fit containment pins must catch a disabled sweep gate.

The pin in tests/test_pdf_map.py's real-offscreen-Qt section that says
"the idle fit holds" used to be vacuous on its own fixture: a canvas
whose sweep-aware fit was switched off (``_sweep() -> 0``, a
single-pose fit) still put every sampled note inside the card, because
FIT_MARGIN's 48px absorbed the whole swing of a gaussian cloud at
700x460. A regression that silently disabled sweep-aware fitting —
sweep_bounds degrading to one pose, frame_bounds dropping its ``sweep``
argument, set_idle_rotation no longer setting ``_idle_want`` — would
have shipped green.

This gate runs tests/test_pdf_map.py twice, each in its own process
with a purged __pycache__ and PYTHONDONTWRITEBYTECODE=1 (the K-117
lesson): once untouched, where the file must be green and the K-201
pins must actually RUN and pass (a gate that matches nothing must not
pass — the k143_gate lesson), and once with ``klausmate.pdf_map
.map_canvas`` wrapped so every canvas it returns answers ``_sweep()``
with 0 — the exact mutation the K-201 investigation used, applied
through sys.modules only, never to pdf_map.py on disk. It passes only
when every K-201 pin goes red under that mutation.

Run: python3 scripts/k201_gate.py
"""
from __future__ import annotations

import importlib
import os
import runpy
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST = os.path.join(ROOT, "tests", "test_pdf_map.py")
SKILL_SCRIPTS = os.path.join(ROOT, ".claude", "skills", "klaus-test", "scripts")
TAG = "(K-201)"
MUTATED_FLAG = "--mutated-run"


def _purge_bytecode() -> None:
    for sub in ("klausmate", "tests", os.path.join(".claude", "skills", "klaus-test", "scripts")):
        shutil.rmtree(os.path.join(ROOT, sub, "__pycache__"), ignore_errors=True)


def _run(mutated: bool) -> tuple[int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    cmd = (
        [sys.executable, os.path.abspath(__file__), MUTATED_FLAG]
        if mutated
        else [sys.executable, TEST]
    )
    _purge_bytecode()
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _mutated_main() -> None:
    """The child: import klausmate.pdf_map under the test harness's own
    stubs, wrap map_canvas so every canvas fits single-pose, then run
    the test file as __main__ — its own install() call re-stubs aqt but
    leaves the already-imported, wrapped module in sys.modules."""
    sys.path.insert(0, SKILL_SCRIPTS)
    from anki_stubs import install  # noqa: E402

    install()
    pdf_map = importlib.import_module("klausmate.pdf_map")
    real_map_canvas = pdf_map.map_canvas

    def gate_off(parent=None, graph=None):
        cv = real_map_canvas(parent, graph)
        if cv is not None:
            cv._sweep = lambda: 0
        return cv

    pdf_map.map_canvas = gate_off
    sys.argv = [TEST]
    runpy.run_path(TEST, run_name="__main__")


def _pins(out: str, prefix: str) -> list:
    return [line for line in out.splitlines() if line.startswith(prefix) and TAG in line]


def main() -> int:
    if MUTATED_FLAG in sys.argv:
        _mutated_main()
        return 0
    problems: list = []

    rc_clean, out_clean = _run(mutated=False)
    ok_clean = _pins(out_clean, "  ok ")
    fail_clean = _pins(out_clean, " FAIL ")
    if rc_clean != 0:
        problems.append(f"tests/test_pdf_map.py is not green unmutated (exit {rc_clean})")
    if "SKIP: PyQt6 unavailable" in out_clean:
        problems.append("the real-offscreen-Qt section did not run, so the pins never executed")
    if fail_clean:
        problems.append(f"{len(fail_clean)} {TAG} pin(s) fail on the unmutated tree")
    if len(ok_clean) < 2:
        problems.append(
            f"expected at least 2 passing {TAG} pins in the clean run, found "
            f"{len(ok_clean)} — missing or renamed, so this gate would be matching nothing"
        )

    rc_mut, out_mut = _run(mutated=True)
    fail_mut = _pins(out_mut, " FAIL ")
    ok_mut = _pins(out_mut, "  ok ")
    if ok_mut:
        problems.append(
            f"{len(ok_mut)} {TAG} pin(s) stayed GREEN with _sweep() forced to 0 — not load-bearing"
        )
    if len(fail_mut) < max(2, len(ok_clean)):
        problems.append(
            f"only {len(fail_mut)} of {len(ok_clean)} {TAG} pins went red under the mutation"
        )
    if rc_mut == 0:
        problems.append("the mutated run exited 0 — nothing in the file noticed the gate was off")

    print(f"clean run: exit {rc_clean}, {len(ok_clean)} {TAG} pins ok, {len(fail_clean)} failing")
    for line in ok_clean:
        print("   " + line.strip()[:110])
    print(f"mutated run (_sweep() -> 0): exit {rc_mut}, {len(fail_mut)} {TAG} pins red, "
          f"{len(ok_mut)} still green")
    for line in fail_mut:
        print("   " + line.strip()[:160])
    other = [line for line in out_mut.splitlines() if line.startswith(" FAIL ") and TAG not in line]
    if other:
        print(f"   (+{len(other)} other pin(s) also red under the mutation — expected collateral)")
        for line in other[:5]:
            print("      " + line.strip()[:110])
    if problems:
        print("\nGATE FAILED:")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nGATE PASSED: the containment pins are load-bearing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
