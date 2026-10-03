"""Cross-checks board/ against the packaged agent-board skill.

The board exists in three places on disk: board/ (live), .claude/skills/
agent-board/scripts/ and .agents/skills/agent-board/scripts/ (the same skill,
mirrored for two CLI conventions). 535bc56 forked all four scripts across
these trees without anyone noticing, because nothing checked. Byte equality
is the wrong test — board/boardlib.py's BOARD_HEADER, its context/ROLES.md
path, and its default BOARD_PREFIX are all supposed to differ from the
skill's generic versions; normalizing those away would just make the skill
less portable to chase a green diff.

What must not differ is BEHAVIOUR. So each tree's test_board.py is run in a
scratch copy of ITSELF with only boardlib.py swapped for the other tree's —
board.py, the CLI it actually exercises, stays put, since the swap is
testing "does board.py still work against a differently-sourced library",
not "are the two CLI entry points byte-identical" (module map does not aqt.

Never touches the real repo: everything runs in a tempdir with its own
KLAUS_BOARD_DIR-equivalent scoping, and the .agents/ mirror is checked for
byte-identity against .claude/ separately, since a THIRD hand-maintained
copy is exactly how this class of drift compounds (a two-way check misses a
fork that only shows up in the third file).

Run: python3 tests/test_board_skill_parity.py
"""
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, "board")
SKILL_CLAUDE = os.path.join(REPO, ".claude", "skills", "agent-board", "scripts")
SKILL_AGENTS = os.path.join(REPO, ".agents", "skills", "agent-board", "scripts")

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


def section(title):
    print(f"== {title} ==")


def run_test_suite_against(test_dir, sibling_name, foreign_boardlib_dir):
    """Copy test_dir's own (test_board.py, board.py) into a scratch tree,
    but swap in foreign_boardlib_dir's boardlib.py — the one file this
    check is actually about.

    sibling_name is the directory the test file expects its scripts in
    NEXT TO ITS OWN tests/ (board/ for the live tree, scripts/ for the
    skill — they chose different names for the same role), so mirroring
    it is what makes BOARD_PY / sys.path resolve inside the scratch tree.

    Returns (returncode, tail_of_stdout, stderr_tail)."""
    scratch = tempfile.mkdtemp(prefix="parity_")
    try:
        scripts_scratch = os.path.join(scratch, sibling_name)
        tests_scratch = os.path.join(scratch, "tests")
        os.makedirs(scripts_scratch)
        os.makedirs(tests_scratch)
        shutil.copy(os.path.join(test_dir, "board.py"), scripts_scratch)
        shutil.copy(os.path.join(foreign_boardlib_dir, "boardlib.py"),
                    scripts_scratch)
        test_src = os.path.join(os.path.dirname(test_dir), "tests",
                                 "test_board.py")
        shutil.copy(test_src, tests_scratch)
        result = subprocess.run(
            [sys.executable, "-B", os.path.join(tests_scratch, "test_board.py")],
            capture_output=True, text=True, cwd=scratch,
            env={**os.environ},
        )
        out = result.stdout.strip().splitlines()
        tail = out[-1] if out else "(no output)"
        return result.returncode, tail, result.stderr[-800:]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


section("behavioural parity: live tests against the skill's boardlib")
before_live = open(os.path.join(LIVE, "boardlib.py"), "rb").read()
rc, tail, err = run_test_suite_against(LIVE, "board", SKILL_CLAUDE)
check("live test_board.py passes against .claude skill's boardlib.py",
      rc == 0, f"{tail}\n{err}")
after_live = open(os.path.join(LIVE, "boardlib.py"), "rb").read()
check("board/boardlib.py itself untouched by the check", before_live == after_live)

section("behavioural parity: the skill's tests against live boardlib")
before_skill = open(os.path.join(SKILL_CLAUDE, "boardlib.py"), "rb").read()
rc, tail, err = run_test_suite_against(SKILL_CLAUDE, "scripts", LIVE)
check(".claude skill's test_board.py passes against live boardlib.py",
      rc == 0, f"{tail}\n{err}")
after_skill = open(os.path.join(SKILL_CLAUDE, "boardlib.py"), "rb").read()
check("skill's boardlib.py itself untouched by the check", before_skill == after_skill)

section("the .agents mirror tracks .claude byte-for-byte")
# Two trees drifting is what 535bc56 already did once; checking .agents
# against .claude directly (rather than running its suite too) is enough,
# since the .agents mirror only exists to serve a different CLI convention
# on the SAME script bodies -- it is not meant to have its own behaviour.
for fname in ("board.py", "boardlib.py", "serve.py", "dashboard.html"):
    a = os.path.join(SKILL_CLAUDE, fname)
    b = os.path.join(SKILL_AGENTS, fname)
    check(f".agents/{fname} matches .claude/{fname}",
          os.path.exists(b) and filecmp.cmp(a, b, shallow=False),
          f"{a} vs {b}")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
