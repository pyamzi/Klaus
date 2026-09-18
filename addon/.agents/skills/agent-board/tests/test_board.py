"""Tests for the agent board (scripts/boardlib.py + scripts/board.py).

Every test runs against a scratch board via BOARD_DIR, so a real BOARD.md is
never touched.

Run: python3 tests/test_board.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
BOARD_PY = os.path.join(SCRIPTS, "board.py")
sys.path.insert(0, SCRIPTS)

# These tests assert on concrete ids, so pin the prefix rather than
# depending on the default. Subprocesses inherit it via os.environ.
os.environ["BOARD_PREFIX"] = "K"

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


def new_board_dir():
    d = tempfile.mkdtemp(prefix="agentboard_")
    os.environ["BOARD_DIR"] = d
    return d


def cli(*args, **kw):
    """Run board.py in the scratch board; returns (rc, stdout, stderr)."""
    env = dict(os.environ)
    env.update(kw.pop("env", {}))
    p = subprocess.run(
        [sys.executable, BOARD_PY] + list(args),
        capture_output=True, text=True, env=env,
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


import boardlib as B  # noqa: E402  (needs sys.path above)

tmpdirs = []

# --------------------------------------------------------------- parsing

section("parse / serialize round trip")
d = new_board_dir(); tmpdirs.append(d)

SAMPLE = B.BOARD_HEADER + """
## Backlog

### K-001: A card with tricky body
owner: -
priority: P1
files: src/parser.py
created: 2026-08-23

Prose with a fenced block that contains headings:

```markdown
### K-999: not a real card
## Doing
```

Trailing prose after the fence.

#### Comments
- [2026-08-23 orchestrator] groomed.

## Ready

## Doing

## Review

## Done
"""

b = B.parse(SAMPLE)
check("card parsed", b.find("K-001")[1] is not None)
check("fenced '###' not parsed as a card", b.find("K-999")[1] is None)
_col, c1 = b.find("K-001")
check("fenced '## Doing' did not switch column", _col == "Backlog", _col)
check("fields parsed", c1.fields.get("priority") == "P1")
check("files parsed", c1.file_list() == ["src/parser.py"])
check("comment parsed", len(c1.comments) == 1)
check("fence content preserved in body", "### K-999: not a real card" in c1.body)
check("post-fence prose preserved", "Trailing prose after the fence." in c1.body)

once = B.serialize(b)
twice = B.serialize(B.parse(once))
check("round trip is stable (idempotent)", once == twice)

section("id allocation")
b2 = B.Board(columns={c: [] for c in B.COLUMNS})
B.add(b2, "Backlog", "one")
B.add(b2, "Backlog", "two")
check("sequential ids", [c.id for _c, c in b2.all_cards()] == ["K-001", "K-002"])
b2.columns["Backlog"].pop(0)
n = B.add(b2, "Backlog", "three")
check("ids do not reuse gaps", n.id == "K-003", n.id)
check("ids zero-padded", B.Board().next_id() == "K-001")

# ------------------------------------------------------------ transitions

section("transition rules")
b3 = B.Board(columns={c: [] for c in B.COLUMNS})
card = B.add(b3, "Backlog", "t", {"files": "x.py"})
B.move(b3, card.id, "Ready")
check("Backlog->Ready allowed", b3.find(card.id)[0] == "Ready")

for frm, to in [("Ready", "Doing"), ("Ready", "Review"), ("Backlog", "Done")]:
    bb = B.Board(columns={c: [] for c in B.COLUMNS})
    cc = B.add(bb, frm, "x")
    try:
        B.move(bb, cc.id, to)
        check(f"{frm}->{to} rejected", False, "was allowed")
    except B.BoardError:
        check(f"{frm}->{to} rejected", True)

bb = B.Board(columns={c: [] for c in B.COLUMNS})
cc = B.add(bb, "Ready", "x")
B.move(bb, cc.id, "Doing", force=True)
check("--force overrides", bb.find(cc.id)[0] == "Doing")

# ------------------------------------------------------------- claiming

section("claim / release")
b4 = B.Board(columns={c: [] for c in B.COLUMNS})
c4 = B.add(b4, "Ready", "claimable", {"files": "one.py"})
B.claim(b4, c4.id, "sonnet-1")
check("claim moves to Doing", b4.find(c4.id)[0] == "Doing")
check("claim sets owner", c4.fields["owner"] == "sonnet-1")
check("claim stamps date", "claimed" in c4.fields)
try:
    B.claim(b4, c4.id, "sonnet-2")
    check("second claim rejected", False, "was allowed")
except B.BoardError:
    check("second claim rejected", True)

B.release(b4, c4.id)
check("release returns to Ready", b4.find(c4.id)[0] == "Ready")
check("release clears owner", c4.fields["owner"] == "-")
check("release clears claimed stamp", "claimed" not in c4.fields)

section("file disjointness")
b5 = B.Board(columns={c: [] for c in B.COLUMNS})
a5 = B.add(b5, "Ready", "a", {"files": "src/renderer.py"})
B.claim(b5, a5.id, "w1")
b5b = B.add(b5, "Ready", "b", {"files": "src/renderer.py"})
try:
    B.claim(b5, b5b.id, "w2")
    check("claim rejected on exact file overlap", False, "was allowed")
except B.BoardError as e:
    check("claim rejected on exact file overlap", "in flight" in str(e))

b6 = B.Board(columns={c: [] for c in B.COLUMNS})
a6 = B.add(b6, "Ready", "dir", {"files": "src"})
B.claim(b6, a6.id, "w1")
b6b = B.add(b6, "Ready", "file", {"files": "src/parser.py"})
try:
    B.claim(b6, b6b.id, "w2")
    check("dir-prefix overlap detected", False, "was allowed")
except B.BoardError:
    check("dir-prefix overlap detected", True)

b7 = B.Board(columns={c: [] for c in B.COLUMNS})
x7 = B.add(b7, "Ready", "x", {"files": "tests/test_drive.py"})
B.claim(b7, x7.id, "w1")
y7 = B.add(b7, "Ready", "y", {"files": "README.md"})
B.claim(b7, y7.id, "w2")
check("disjoint files claim fine", b7.find(y7.id)[0] == "Doing")
check("check_disjoint reports overlap", len(B.check_disjoint(b6)) > 0)
check("check_disjoint clean when disjoint", B.check_disjoint(b7) == [])

section("comments and edit preserve body")
b8 = B.Board(columns={c: [] for c in B.COLUMNS})
c8 = B.add(b8, "Ready", "c", body="Original body.")
B.comment(b8, c8.id, "worker", "did   the\nthing")
check("comment normalises whitespace", c8.comments[0].endswith("did the thing"))
check("comment keeps body", c8.body == "Original body.")
B.edit(b8, c8.id, fields={"priority": "P0"})
check("edit updates field", c8.fields["priority"] == "P0")
check("edit keeps body", c8.body == "Original body.")

# ------------------------------------------------------------------- archive

section("archive")
d = new_board_dir(); tmpdirs.append(d)
archive_file = os.path.join(d, "ARCHIVE.md")

b9 = B.Board(columns={c: [] for c in B.COLUMNS})
c9 = B.add(b9, "Done", "finished work", {"files": "x.py"})
B.comment(b9, c9.id, "worker", "wrapped up nicely")
archived = B.archive(b9, c9.id)
check("archive removes card from Done", b9.find(c9.id)[1] is None)
check("archive returns the archived card", archived.id == c9.id)
check("archive stamps an archived-on date", "archived" in archived.fields)

with open(archive_file, encoding="utf-8") as f:
    archive_text = f.read()
check("archived card heading present in ARCHIVE.md",
      "### %s: finished work" % c9.id in archive_text)
check("archived comment preserved in ARCHIVE.md",
      "wrapped up nicely" in archive_text)
check("archived-on date field present in ARCHIVE.md",
      "archived: %s" % archived.fields["archived"] in archive_text)

section("archive refuses non-Done cards")
b10 = B.Board(columns={c: [] for c in B.COLUMNS})
c10 = B.add(b10, "Doing", "still in progress", {"files": "y.py"})
try:
    B.archive(b10, c10.id)
    check("archive refuses a Doing card", False, "was allowed")
except B.BoardError:
    check("archive refuses a Doing card", True)
try:
    B.archive(b10, "K-999")
    check("archive rejects an unknown id", False, "was allowed")
except B.BoardError:
    check("archive rejects an unknown id", True)

section("archive --all-done sweep")
d = new_board_dir(); tmpdirs.append(d)
cli("add", "--col", "Done", "--title", "done one")
cli("add", "--col", "Done", "--title", "done two")
cli("add", "--col", "Ready", "--title", "still ready", "--files", "keep.py")
rc, out, err = cli("archive", "--all-done")
check("archive --all-done exits 0", rc == 0, err)
check("archive --all-done reports both cards",
      "K-001" in out and "K-002" in out, out)

rc, out, _e = cli("list", "--json")
data = json.loads(out)
by_name = {col["name"]: col["cards"] for col in data["columns"]}
check("all Done cards archived off the board", by_name["Done"] == [], by_name["Done"])
check("Ready cards untouched by --all-done", len(by_name["Ready"]) == 1)

rc, out, err = cli("archive", "--all-done")
check("archive --all-done is a no-op when nothing is Done", rc == 0, err)
check("no-op sweep says so", "no Done cards" in out, out)

section("archive id-reuse regression")
# Grooming note on K-019: next_id() is max+1 over *live* cards, so removing
# the highest-numbered card (by delete, or now by archive) frees its number
# for reuse — except an archived card's id is still permanently recorded in
# ARCHIVE.md, so reusing it would collide with real history.
d = new_board_dir(); tmpdirs.append(d)
rc, highest_id, _e = cli("add", "--col", "Done", "--title", "will be archived")
check("seed card created", rc == 0, highest_id)
rc, _o, err = cli("archive", highest_id)
check("archive of the highest card exits 0", rc == 0, err)
rc, new_id, _e = cli("add", "--col", "Backlog", "--title", "created after archive")
check("add after archiving the max card exits 0", rc == 0, new_id)
check("new id is not the archived id", new_id != highest_id, new_id)
expect_num = int(highest_id[2:]) + 1
check("new id advances past the archived id",
      new_id == "K-%03d" % expect_num, "%s vs expected K-%03d" % (new_id, expect_num))

# ------------------------------------------------------------------ CLI

section("CLI end to end")
d = new_board_dir(); tmpdirs.append(d)
rc, out, _ = cli("add", "--col", "Ready", "--title", "cli card",
                 "--files", "z.py", "--verify", "true")
check("add exits 0", rc == 0)
check("add prints the new id", out == "K-001", out)
rc, _o, _e = cli("claim", "K-001", "--owner", "w1")
check("claim exits 0", rc == 0)
rc, _o, err = cli("claim", "K-001", "--owner", "w2")
check("re-claim exits 1", rc == 1, f"rc={rc}")
check("rejection reason on stderr", "not Ready" in err, err)
rc, _o, _e = cli("move", "K-001", "Done")
check("illegal move exits 1", rc == 1)
rc, out, _e = cli("list", "--json")
check("list --json is valid JSON", json.loads(out)["columns"][2]["name"] == "Doing")
rc, _o, _e = cli("show", "K-999")
check("show on missing card exits 1", rc == 1)
rc, _o, _e = cli("check-disjoint")
check("check-disjoint exits 0 when clean", rc == 0)

section("concurrent claims: exactly one winner")
d = new_board_dir(); tmpdirs.append(d)
cli("add", "--col", "Ready", "--title", "contested", "--files", "hot.py")
procs = [
    subprocess.Popen([sys.executable, BOARD_PY, "claim", "K-001",
                      "--owner", f"w{i}"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, env=dict(os.environ))
    for i in range(2)
]
codes = [p.wait() for p in procs]
check("exactly one claim succeeded", codes.count(0) == 1, f"codes={codes}")
check("the other was rejected, not crashed", codes.count(1) == 1, f"codes={codes}")
rc, out, _e = cli("list", "--json")
doing = [c for col in json.loads(out)["columns"] if col["name"] == "Doing"
         for c in col["cards"]]
check("card appears exactly once in Doing", len(doing) == 1)

section("lock behaviour")
d = new_board_dir(); tmpdirs.append(d)
cli("add", "--title", "x")

# A lock owned by a dead pid, old enough to be stale, must be broken.
lock = os.path.join(d, ".lock")
with open(lock, "w") as f:
    json.dump({"pid": 999999, "host": os.uname().nodename,
               "ts": time.time() - 9999}, f)
os.utime(lock, (time.time() - 9999, time.time() - 9999))
rc, _o, err = cli("comment", "K-001", "--author", "a", "--text", "t")
check("stale lock with dead pid is broken", rc == 0, err)

# A lock owned by a live pid must NOT be broken; caller times out at 2.
with open(lock, "w") as f:
    json.dump({"pid": os.getpid(), "host": os.uname().nodename,
               "ts": time.time() - 9999}, f)
os.utime(lock, (time.time() - 9999, time.time() - 9999))
t0 = time.time()
env = {"BOARD_DIR": d}
p = subprocess.run([sys.executable, "-c",
                    f"import sys;sys.path.insert(0,{SCRIPTS!r});"
                    "import boardlib as B;B.LOCK_TIMEOUT_S=0.5;"
                    "import board as BD;sys.exit(BD.main(['comment','K-001','--author','a','--text','t']))"],
                   capture_output=True, text=True, env={**os.environ, **env})
check("live lock is respected (exit 2)", p.returncode == 2, f"rc={p.returncode} {p.stderr[:120]}")
check("timed out rather than hanging", time.time() - t0 < 8)
os.unlink(lock)

section("real board file is untouched")
real = os.path.join(SCRIPTS, "BOARD.md")
check("tests never created the real BOARD.md unexpectedly",
      not os.path.exists(real) or os.path.getsize(real) > 0)

for d in tmpdirs:
    shutil.rmtree(d, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
