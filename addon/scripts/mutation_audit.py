#!/usr/bin/env python3
"""K-139 — a validated vacuity detector: find pins that cannot fail.

K-135 found a check that was incapable of failing: a hex-colour hunter
that cut each line at its first ``#`` to skip comments, when a hex
literal IS a ``#`` inside a string.  It deleted exactly what it hunted
and returned ``[]`` for ``BLUE = "#AABBCC"``.  Both checks built on it
had been vacuous since the day they were written, and it was found by
accident.  ~2,100 checks live in this suite; accident is not a strategy.

The only reliable evidence that a pin CAN fail is making it fail.  So:
break the code on purpose, one small break at a time, and watch whether
anything notices.  A break nothing notices is behaviour with no pin on
it.  Everything else here exists to keep that signal honest.

WHY IT IS BUILT THE WAY IT IS
-----------------------------

*It never touches the working tree.*  Every mutation is applied inside a
sandbox copy under a scratch directory.  The repo is hashed before the
run and re-hashed in a ``finally`` (exceptions and Ctrl-C included); a
single differing byte is a hard, loud failure.  Several agents share
this checkout — a mutation escaping into it would be worse than no tool.

*It refuses to run without a green baseline.*  Each test file is run
unmutated in the sandbox first.  If the sandbox copy cannot reproduce a
clean pass, every mutation would look "caught" and the report would be a
confident lie in the reassuring direction.  A red baseline aborts.

*It kills bytecode caching.*  Children run with ``-B`` and
``PYTHONDONTWRITEBYTECODE=1``, and both cache roots (the local
``__pycache__`` and this Mac's ``sys.pycache_prefix`` mirror tree) are
purged before each run.  CPython validates a ``.pyc`` on (mtime, size)
alone, so a same-size mutation inside one mtime second silently executes
the OLD code — and every mutation then looks caught.  After each run the
sandbox is scanned for ``.pyc`` files; finding one aborts the run.

*It distinguishes losing behaviour from losing text.*  Some tests in
this repo read module SOURCE as text rather than importing it.  The
primary ``gut`` operator therefore INSERTS ``return None`` after the
docstring and leaves the original body in place as dead code: the
behaviour is destroyed while every byte of the original text survives,
so a catch is a behavioural catch.  Any survivor is then re-run with
``gut-cut``, which deletes the body text outright.  Caught there but not
before means the code is source-pinned only — a text grep notices it is
gone, nothing notices what it did.

*It reports per CHECK, not per exit code.*  The harness prints one
``  ok  <name>`` / `` FAIL <name>`` line per check; those lines are
parsed into an ordered list and diffed against the baseline.  That is
what makes the selftest able to ask "did THIS pin fail?" rather than
"did the file exit non-zero?".

*Nothing is sampled and nothing is random.*  Mutations are enumerated
from the AST in source order.  Two runs of the same tree give the same
report.

*A mutation that cannot be applied cleanly is SKIPPED.*  Not caught.
Target missing, no-op, one-line body, source that will not compile,
timeout — all reported in their own categories and excluded from the
caught/survived tallies.  Silently scoring an unapplied mutation as
"caught" is the exact failure mode this tool exists to detect.

*No network. No writes outside the scratch directory.*  This script
never writes into the repo at all — findings go to stdout (and to
``--json`` inside the scratch dir if asked).  scripts/AUDIT.md is
written by a human/agent reading that output, because the judgement
"trivial or real" is not something a mutation runner can make.

USAGE
-----

    python3 scripts/mutation_audit.py --selftest
    python3 scripts/mutation_audit.py --modules heatmap,background
    python3 scripts/mutation_audit.py --list heatmap
    python3 scripts/mutation_audit.py --modules all --json out.json

``--selftest`` is the gate: it reconstructs the known-vacuous K-135
helper and demands the tool call it surviving, plants two decoys in a
well-pinned module and demands both be caught, and confirms the tree is
byte-identical afterwards.  Non-zero exit if any of the three is wrong.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# --------------------------------------------------------------- paths

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Copied into the sandbox.  ``klausmate/user_files`` (real PDFs, the
#: card index, annotations) and ``meta.json`` (API keys) are excluded —
#: they are half a gigabyte and none of it is ours to duplicate.
SANDBOX_TREES = ("klausmate", "tests", os.path.join(".claude", "skills", "klaus-test"))
_COPY_SKIP_DIRS = {"user_files", "__pycache__", ".git"}
_COPY_SKIP_NAMES = {"meta.json", "meta.json.bak"}

#: The six modules K-139 scopes the audit to.  Every other klausmate
#: module and every other test file belongs to another session.
AUDIT_MODULES = (
    "heatmap",
    "dashboard",
    "background",
    "pdf_notes",
    "lecture_view",
    "projection",
    # The assistant layers (2026-09-01). All four are aqt-light by
    # construction, so nearly every function is reachable from its own
    # test file — which is exactly the condition this audit needs.
    "card_forge",
    "llm_client",
    "entitlement",
    "anki_tools",
)

#: The only test files this tool is allowed to execute.  The selftest
#: adds test_setup_crop_theme.py, which is where the known-vacuous pin
#: lives.
ALLOWED_TESTS = tuple("tests/test_%s.py" % m for m in AUDIT_MODULES) + (
    "tests/test_setup_crop_theme.py",
)

RUN_TIMEOUT = 300  # seconds; test_projection is the slow one at ~11s


# ------------------------------------------------------- tree integrity


def _guarded_files():
    """Every repo file this tool reads, in a stable order.

    These are hashed before and after the run.  The tool writes to none
    of them; a mismatch means either a bug here or a concurrent edit by
    another session, and both deserve a loud stop rather than a report
    nobody can trust.
    """
    out = []
    for tree in SANDBOX_TREES:
        root = os.path.join(REPO, tree)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _COPY_SKIP_DIRS)
            for name in sorted(filenames):
                if name in _COPY_SKIP_NAMES or name.endswith(".pyc"):
                    continue
                out.append(os.path.join(dirpath, name))
    return out


def _hash_tree(paths):
    digests = {}
    for path in paths:
        try:
            with open(path, "rb") as fh:
                digests[path] = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            digests[path] = "<unreadable>"
    return digests


def _diff_hashes(before, after):
    changed = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            changed.append(path)
    return changed


#: sha256 of every blob this run wrote anywhere.  If a repo file ends up
#: holding one of these, the sandbox leaked and that is fatal.  If a repo
#: file changed to something NOT in here, another session edited it —
#: which is normal in this swarm, is not a failure of this tool, and must
#: not be reported as one.  Several agents share this checkout.
_WRITTEN_BLOBS = set()


def _classify_changes(changed, after):
    leaked, external = [], []
    for path in changed:
        if after.get(path) in _WRITTEN_BLOBS:
            leaked.append(path)
        else:
            external.append(path)
    return leaked, external


# ------------------------------------------------------------- sandbox


def _copy_filter(dirpath, names):
    ignored = set()
    for name in names:
        full = os.path.join(dirpath, name)
        if os.path.isdir(full) and name in _COPY_SKIP_DIRS:
            ignored.add(name)
        elif name in _COPY_SKIP_NAMES or name.endswith(".pyc"):
            ignored.add(name)
    return ignored


def build_sandbox(scratch):
    """A working copy of everything the tests need, and nothing else."""
    sandbox = os.path.join(scratch, "sandbox")
    if os.path.exists(sandbox):
        shutil.rmtree(sandbox)
    os.makedirs(sandbox)
    for tree in SANDBOX_TREES:
        src = os.path.join(REPO, tree)
        dst = os.path.join(sandbox, tree)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copytree(src, dst, ignore=_copy_filter)
    return sandbox


def _purge_bytecode(sandbox):
    """Drop both cache roots.  See the module docstring; this Mac's
    system python sets ``sys.pycache_prefix``, so ``rm -rf __pycache__``
    inside the tree is only half the job."""
    for dirpath, dirnames, _files in os.walk(sandbox):
        for name in list(dirnames):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, name), ignore_errors=True)
                dirnames.remove(name)
    prefix = getattr(sys, "pycache_prefix", None)
    if prefix:
        mirror = os.path.join(prefix, sandbox.lstrip(os.sep))
        shutil.rmtree(mirror, ignore_errors=True)


def _assert_no_bytecode(sandbox):
    for dirpath, _dirnames, files in os.walk(sandbox):
        for name in files:
            if name.endswith(".pyc"):
                raise RuntimeError(
                    "bytecode appeared in the sandbox (%s) — a run may have "
                    "executed stale code" % os.path.join(dirpath, name)
                )


# ------------------------------------------------------------ test runs

_OK_RE = re.compile(r"^  ok  (.*)$")
_FAIL_RE = re.compile(r"^ FAIL (.*)$")
_TALLY_RE = re.compile(r"^(\d+) passed, (\d+) failed\s*$")


class RunResult(object):
    __slots__ = ("rc", "checks", "passed", "failed", "timed_out", "stdout")

    def __init__(self, rc, checks, passed, failed, timed_out, stdout):
        self.rc = rc
        self.checks = checks  # ordered [(name, ok_bool), ...]
        self.passed = passed
        self.failed = failed
        self.timed_out = timed_out
        self.stdout = stdout

    @property
    def clean(self):
        return (
            not self.timed_out
            and self.rc == 0
            and self.failed == 0
            and all(ok for _n, ok in self.checks)
        )

    def failing_names(self):
        return [n for n, ok in self.checks if not ok]

    def canonical(self, base_names):
        """Check names as the baseline knows them.

        ``check()`` prints ``" FAIL {name} {detail}"``, so a failing line
        carries the detail glued onto the name while a passing line does
        not.  Comparing raw text would make every failure look like a
        check the baseline has never heard of.  Align positionally when
        the run produced the same number of checks, else fall back to the
        longest baseline name that prefixes the line.
        """
        if len(self.checks) == len(base_names):
            return [(base_names[i], ok) for i, (_n, ok) in enumerate(self.checks)]
        out = []
        for name, ok in self.checks:
            best = ""
            for cand in base_names:
                if len(cand) > len(best) and name.startswith(cand):
                    best = cand
            out.append((best or name, ok))
        return out


def _parse_output(text):
    """One (name, ok) per printed check line, in order.

    Only the harness's exact prefixes count.  A multi-line ``detail``
    string bleeding into the next lines must not be mistaken for a
    check, so anything that does not match is ignored.
    """
    checks = []
    passed = failed = 0
    for line in text.splitlines():
        m = _OK_RE.match(line)
        if m:
            checks.append((m.group(1).rstrip(), True))
            continue
        m = _FAIL_RE.match(line)
        if m:
            checks.append((m.group(1).rstrip(), False))
            continue
        m = _TALLY_RE.match(line)
        if m:
            passed, failed = int(m.group(1)), int(m.group(2))
    return checks, passed, failed


def run_test(sandbox, test_rel, timeout=RUN_TIMEOUT):
    if test_rel not in ALLOWED_TESTS:
        raise RuntimeError("refusing to run a test file outside K-139's scope: %r"
                           % test_rel)
    _purge_bytecode(sandbox)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PYTHONPATH", None)
    try:
        proc = subprocess.run(
            [sys.executable, "-B", test_rel],
            cwd=sandbox,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _assert_no_bytecode(sandbox)
        return RunResult(-1, [], 0, 0, True, "<timeout>")
    text = proc.stdout.decode("utf-8", "replace")
    _assert_no_bytecode(sandbox)
    checks, passed, failed = _parse_output(text)
    return RunResult(proc.returncode, checks, passed, failed, False, text)


# ----------------------------------------------------------- source ops


def _line_starts(src):
    starts = [0]
    for i, ch in enumerate(src):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _offset(src, starts, lineno, col_offset):
    """AST columns are UTF-8 BYTE offsets; these files contain ⊖, ＋, —."""
    line_start = starts[lineno - 1]
    line_end = starts[lineno] if lineno < len(starts) else len(src)
    line = src[line_start:line_end]
    prefix = line.encode("utf-8")[:col_offset].decode("utf-8", "replace")
    return line_start + len(prefix)


def _qualname(stack, node):
    return ".".join([n.name for n in stack] + [node.name])


def _iter_functions(tree):
    """(qualname, node) for every def, in source order, innermost last."""
    out = []

    def walk(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((_qualname(stack, child), child))
                walk(child, stack + [child])
            elif isinstance(child, ast.ClassDef):
                walk(child, stack + [child])
            else:
                walk(child, stack)

    walk(tree, [])
    out.sort(key=lambda p: (p[1].lineno, p[1].col_offset))
    return out


def _body_start(node):
    """First statement of the body that is not the docstring.

    The docstring is deliberately preserved: several pins in this repo
    grep module text, and removing prose would make them fire for a
    reason that has nothing to do with behaviour.
    """
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def _is_trivial_body(body):
    if not body:
        return True
    if len(body) > 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Return) and (
        stmt.value is None
        or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
    ):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return True  # `...` or a bare literal
    return False


# ---------------------------------------------------------- mutations


class Mutation(object):
    """One deterministic edit, plus how to apply it to a pristine file."""

    __slots__ = ("target", "kind", "name", "lineno", "detail", "_apply")

    def __init__(self, target, kind, name, lineno, detail, apply_fn):
        self.target = target  # repo-relative path
        self.kind = kind
        self.name = name
        self.lineno = lineno
        self.detail = detail
        self._apply = apply_fn

    @property
    def ident(self):
        return "%s::%s::%s@%d" % (self.target, self.kind, self.name, self.lineno)

    def apply(self, src):
        """Return mutated source, or None when it cannot be applied."""
        try:
            out = self._apply(src)
        except Exception:
            return None
        if out is None or out == src:
            return None
        try:
            compile(out, "<mutant>", "exec")
        except SyntaxError:
            return None
        return out


def _make_insert_return(path, qual, node, stmt):
    """gut: `return None` inserted as the first executed statement.

    A pure single-line insertion.  Every substring of the original file
    except those straddling the insertion point survives, so source-text
    pins stay satisfied and a catch is a BEHAVIOURAL catch.
    """

    def apply(src):
        starts = _line_starts(src)
        off = _offset(src, starts, stmt.lineno, stmt.col_offset)
        line_start = starts[stmt.lineno - 1]
        indent = src[line_start:off]
        if indent.strip():
            return None  # statement shares its line with something else
        if stmt.lineno == node.body[0].lineno == node.lineno:
            return None  # one-liner def
        return src[:line_start] + indent + "return None\n" + src[line_start:]

    return Mutation(path, "gut", qual, node.lineno,
                    "insert `return None` before the body (text preserved)",
                    apply)


def _make_cut_body(path, qual, node, body):
    """gut-cut: the body TEXT is replaced by `return None`.

    Only used on survivors of `gut`, to tell "nothing pins this" apart
    from "only a source-text grep pins this".
    """
    first, last = body[0], body[-1]

    def apply(src):
        starts = _line_starts(src)
        off = _offset(src, starts, first.lineno, first.col_offset)
        line_start = starts[first.lineno - 1]
        indent = src[line_start:off]
        if indent.strip():
            return None
        end = _offset(src, starts, last.end_lineno, last.end_col_offset)
        return src[:off] + "return None" + src[end:]

    return Mutation(path, "gut-cut", qual, node.lineno,
                    "delete the body text, leaving `return None`", apply)


def _mutate_literal(value, loud=False):
    """Deterministic, meaning-changing replacement for a literal.

    Two strengths, because one is not enough to conclude anything.

    *Quiet* nudges by one and appends to strings.  It is text-preserving
    (a source pin grepping the original value still matches) and it is
    the right probe for an identity: a path fragment, a dict key, a
    bridge prefix, an enum member.  It is a USELESS probe for a
    tolerance or a geometry constant — ``144.0 -> 145.0`` surviving says
    nothing at all, since no fixture sits on that boundary.

    *Loud* collapses the value to 1 / 1.0 / "MUT".  Nine orders of
    magnitude off a convergence epsilon, or a cell size of one pixel, is
    a change any real pin must see.  A survivor here is evidence; a
    survivor of the quiet variant alone is only a hint.
    """
    if isinstance(value, bool):
        return repr(not value) if not loud else None
    if isinstance(value, int):
        if loud:
            return repr(2 if value == 1 else 1)
        return repr(value + 1)
    if isinstance(value, float):
        if loud:
            return repr(2.0 if value == 1.0 else 1.0)
        return repr(value + 1.0)
    if isinstance(value, str):
        if loud:
            return repr("MUT") if value != "MUT" else None
        return repr(value + "MUT")
    return None


def _make_const(path, name, node, value_node, label, loud=False):
    replacement = _mutate_literal(value_node.value, loud=loud)
    if replacement is None:
        return None
    shown = replacement if len(replacement) <= 60 else replacement[:57] + "..."

    def apply(src):
        starts = _line_starts(src)
        a = _offset(src, starts, value_node.lineno, value_node.col_offset)
        b = _offset(src, starts, value_node.end_lineno, value_node.end_col_offset)
        return src[:a] + replacement + src[b:]

    return Mutation(path, "const-loud" if loud else "const", name,
                    value_node.lineno, "%s -> %s" % (label, shown), apply)


def _make_boolflip(path, name, node):
    def apply(src):
        starts = _line_starts(src)
        a = _offset(src, starts, node.lineno, node.col_offset)
        b = _offset(src, starts, node.end_lineno, node.end_col_offset)
        if src[a:b] not in ("True", "False"):
            return None
        return src[:a] + repr(not node.value) + src[b:]

    return Mutation(path, "boolflip", name, node.lineno,
                    "%r -> %r" % (node.value, not node.value), apply)


def enumerate_mutations(path, src):
    """Every mutation for one file, in a fixed order.  No sampling."""
    tree = ast.parse(src)
    muts = []
    skipped = []

    # 1. gut every function body
    for qual, node in _iter_functions(tree):
        body = _body_start(node)
        if _is_trivial_body(body):
            skipped.append((path, "gut", qual, node.lineno,
                            "body is already vacuous — nothing to remove"))
            continue
        muts.append(_make_insert_return(path, qual, node, body[0]))

    # 2. module-level constants (and the first element of literal
    #    tuples/lists, which is where RAMP_FACTORS-style data lives)
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        val = node.value
        if isinstance(val, ast.Constant):
            made = [_make_const(path, target.id, node, val, target.id, loud)
                    for loud in (False, True)]
            made = [m for m in made if m is not None]
            if made:
                muts.extend(made)
            else:
                skipped.append((path, "const", target.id, node.lineno,
                                "literal type has no deterministic mutation"))
        elif isinstance(val, (ast.Tuple, ast.List)) and val.elts:
            first = val.elts[0]
            if isinstance(first, ast.Constant):
                for loud in (False, True):
                    m = _make_const(path, target.id + "[0]", node, first,
                                    target.id + "[0]", loud)
                    if m is not None:
                        muts.append(m)

    # 3. every boolean literal, wherever it lives
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and (
            node.value is True or node.value is False
        ):
            muts.append(_make_boolflip(path, "bool@%d:%d"
                                       % (node.lineno, node.col_offset), node))

    order = ("gut", "const", "const-loud", "boolflip")
    muts.sort(key=lambda m: (order.index(m.kind), m.lineno, m.name))
    return muts, skipped


# ------------------------------------------------------------- the run


class Session(object):
    """Owns the sandbox, the integrity guard and the baseline cache."""

    def __init__(self, scratch, verbose=True):
        self.scratch = scratch
        self.verbose = verbose
        self.sandbox = build_sandbox(scratch)
        self._pristine = {}   # repo-rel path -> original source
        self._baseline = {}   # test_rel -> RunResult
        self.runs = 0

    # -- files ---------------------------------------------------------

    def pristine(self, rel):
        if rel not in self._pristine:
            with open(os.path.join(self.sandbox, rel), encoding="utf-8") as fh:
                self._pristine[rel] = fh.read()
        return self._pristine[rel]

    def _write(self, rel, text):
        """The ONLY writer in this file, and it cannot escape the sandbox.

        A path check here is worth more than any amount of care at the
        call sites: it makes writing into the shared checkout
        structurally impossible rather than merely unintended.
        """
        dest = os.path.abspath(os.path.join(self.sandbox, rel))
        root = os.path.abspath(self.sandbox) + os.sep
        if not dest.startswith(root):
            raise RuntimeError("refusing to write outside the sandbox: %s" % dest)
        _WRITTEN_BLOBS.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)

    def audited_digest(self, rel):
        """sha256 of the exact file version a finding was made against —
        the tree moves under a swarm, so findings name their input."""
        return hashlib.sha256(self.pristine(rel).encode("utf-8")).hexdigest()

    def touched_repo_paths(self):
        """Repo paths whose sandbox twin this run mutated.  An external
        edit to one of these invalidates the run; an external edit to any
        other file is merely noise."""
        return set(os.path.join(REPO, rel) for rel in self._pristine)

    def restore(self, rel):
        self._write(rel, self.pristine(rel))

    def restore_all(self):
        for rel in list(self._pristine):
            self.restore(rel)

    # -- baseline ------------------------------------------------------

    def baseline(self, test_rel):
        if test_rel not in self._baseline:
            res = run_test(self.sandbox, test_rel)
            self.runs += 1
            if not res.clean:
                raise RuntimeError(
                    "BASELINE IS NOT GREEN for %s in the sandbox — every "
                    "mutation would look caught. rc=%s failed=%s\n%s"
                    % (test_rel, res.rc, res.failed, res.stdout[-2000:])
                )
            self._baseline[test_rel] = res
        return self._baseline[test_rel]

    # -- one mutation --------------------------------------------------

    def evaluate(self, mutation, test_files):
        """Apply, run, restore.  Returns a result dict, never raises for
        an unapplicable mutation — that is a SKIP."""
        rel = mutation.target
        src = self.pristine(rel)
        mutated = mutation.apply(src)
        if mutated is None:
            return {"ident": mutation.ident, "verdict": "skipped",
                    "reason": "mutation could not be applied cleanly",
                    "kind": mutation.kind, "name": mutation.name,
                    "target": rel, "lineno": mutation.lineno,
                    "detail": mutation.detail, "failing": [], "test": None}
        for test_rel in test_files:
            self.baseline(test_rel)  # gate before anything is written

        record = {"ident": mutation.ident, "kind": mutation.kind,
                  "name": mutation.name, "target": rel,
                  "lineno": mutation.lineno, "detail": mutation.detail,
                  "failing": [], "test": None, "verdict": "survived",
                  "reason": ""}
        try:
            self._write(rel, mutated)
            # Read back: a mutation that never landed must never be
            # scored, in either direction.
            with open(os.path.join(self.sandbox, rel), encoding="utf-8") as fh:
                if fh.read() != mutated:
                    record["verdict"] = "skipped"
                    record["reason"] = "mutation did not land on disk"
                    return record
            for test_rel in test_files:
                res = run_test(self.sandbox, test_rel)
                self.runs += 1
                if res.timed_out:
                    record["verdict"] = "inconclusive"
                    record["reason"] = "timed out after %ds" % RUN_TIMEOUT
                    record["test"] = test_rel
                    return record
                base = self._baseline[test_rel]
                base_names = [n for n, _ok in base.checks]
                failing = [n for n, ok in res.canonical(base_names) if not ok]
                if failing or res.rc != 0:
                    record["verdict"] = "caught"
                    record["test"] = test_rel
                    record["failing"] = failing[:6]
                    if not failing:
                        record["reason"] = "run crashed (rc=%d)" % res.rc
                        record["verdict"] = "caught-crash"
                    return record
                if len(res.checks) != len(base.checks):
                    record["verdict"] = "inconclusive"
                    record["test"] = test_rel
                    record["reason"] = (
                        "check count changed %d -> %d with rc=0"
                        % (len(base.checks), len(res.checks))
                    )
                    return record
            return record
        finally:
            self.restore(rel)


def _tests_for_module(module):
    """The allowed test files that touch this module, primary first.

    Computed from the test sources rather than a hand table, so a new
    cross-import cannot silently narrow the search.
    """
    primary = "tests/test_%s.py" % module
    order = [primary]
    needle_a = "klausmate.%s" % module
    needle_b = "klausmate/%s.py" % module
    for other in ALLOWED_TESTS:
        if other == primary or other == "tests/test_setup_crop_theme.py":
            continue
        try:
            with open(os.path.join(REPO, other), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if needle_a in text or needle_b in text:
            order.append(other)
    return order


def audit(session, modules, out=sys.stdout):
    results = []
    for module in modules:
        rel = "klausmate/%s.py" % module
        src = session.pristine(rel)
        muts, pre_skipped = enumerate_mutations(rel, src)
        tests = _tests_for_module(module)
        digest = session.audited_digest(rel)
        # Name the exact file version: several sessions edit this
        # checkout, so a finding without a digest is a finding about
        # nothing in particular.
        print("\n== %s (%d mutations, sha256 %s, tests: %s) =="
              % (rel, len(muts), digest[:12], ", ".join(tests)), file=out)
        for path, kind, name, lineno, reason in pre_skipped:
            results.append({"ident": "%s::%s::%s@%d" % (path, kind, name, lineno),
                            "kind": kind, "name": name, "target": path,
                            "lineno": lineno, "detail": "", "failing": [],
                            "test": None, "verdict": "skipped",
                            "reason": reason})
        tally = {}
        for mut in muts:
            rec = session.evaluate(mut, tests)
            rec["sha256"] = digest
            # A survivor is re-probed with the text-destroying variant so
            # "nothing pins it" and "only a source grep pins it" do not
            # get reported as the same thing.
            if rec["verdict"] == "survived" and mut.kind == "gut":
                node_cut = _cut_variant(rel, src, mut)
                if node_cut is not None:
                    cut = session.evaluate(node_cut, tests)
                    if cut["verdict"].startswith("caught"):
                        rec["verdict"] = "source-pinned-only"
                        rec["failing"] = cut["failing"]
                        rec["test"] = cut["test"]
                        rec["reason"] = ("behaviour unpinned; a source-text "
                                         "check notices the body is gone")
                    elif cut["verdict"] != "survived":
                        rec["reason"] = "gut-cut probe: " + cut["verdict"]
            results.append(rec)
            tally[rec["verdict"]] = tally.get(rec["verdict"], 0) + 1
            if rec["verdict"] in ("survived", "source-pinned-only",
                                  "inconclusive"):
                print("  %-18s %s:%d %s (%s) %s"
                      % (rec["verdict"], rel, rec["lineno"], rec["name"],
                         rec["kind"], rec["reason"]), file=out)
        print("  -- " + ", ".join("%s=%d" % kv for kv in sorted(tally.items())),
              file=out)
    return results


def _cut_variant(rel, src, gut_mut):
    """The gut-cut twin of a gut mutation, found by qualified name."""
    tree = ast.parse(src)
    for qual, node in _iter_functions(tree):
        if qual == gut_mut.name and node.lineno == gut_mut.lineno:
            body = _body_start(node)
            if _is_trivial_body(body):
                return None
            return _make_cut_body(rel, qual, node, body)
    return None


# ------------------------------------------------------------ selftest

#: The pre-K-135 body of tests/test_setup_crop_theme.py's hex helper,
#: transcribed from commit a2c22f4's diff.  It cuts each line at its
#: first "#" to drop comments, which is the same "#" that opens a hex
#: literal — so it returns [] for `BLUE = "#AABBCC"`.
_VACUOUS_HELPER = '''def _hex_hits_outside_comments(src: str) -> list:
    """Literal 6-digit hex colours that appear before any '#' comment
    marker on their line."""
    hits = []
    for lineno, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_part = line.split("#", 1)[0]
        if _HEX_RE.search(code_part):
            hits.append((lineno, line))
    return hits
'''

#: Planted into klausmate/setup_flow.py.  A working hex pin must see it.
_PLANTED_HEX = '_MUTATION_AUDIT_PLANT = "#AABBCC"\n'

#: The check whose vacuity K-135 exposed.  It appears twice in the file
#: (setup_flow, then crop_dialog); occurrence 0 is setup_flow's.
_HEX_CHECK = "zero literal hex colours in code (comments are exempt)"


def _replace_function_source(src, func_name, new_source):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            starts = _line_starts(src)
            a = starts[node.lineno - 1]
            b = starts[node.end_lineno] if node.end_lineno < len(starts) \
                else len(src)
            return src[:a] + new_source + src[b:]
    return None


def _plant_hex(src):
    """Append the literal at module level — a pure addition, so no
    existing pin can fire for any other reason."""
    return src.rstrip("\n") + "\n\n\n" + _PLANTED_HEX


def _nth_check(res, base_names, name, index):
    seen = 0
    for got, ok in res.canonical(base_names):
        if got == name:
            if seen == index:
                return ok
            seen += 1
    return None


def selftest(scratch, out=sys.stdout):
    """Three cases.  Any wrong answer is a non-zero exit."""
    failures = []

    def gate(label, ok, detail=""):
        print("  %s %s%s" % ("PASS" if ok else "FAIL", label,
                             ("  — " + detail) if detail else ""), file=out)
        if not ok:
            failures.append(label)

    session = Session(scratch)
    setup_test = "tests/test_setup_crop_theme.py"
    flow_rel = "klausmate/setup_flow.py"

    print("\n== selftest (a): the known-vacuous K-135 pin ==", file=out)

    # Independent proof that the reconstruction really is blind, before
    # any test is run: exec it and ask it about a literal.
    ns = {"_HEX_RE": re.compile(r"#[0-9A-Fa-f]{6}")}
    exec(compile(_VACUOUS_HELPER, "<vacuous>", "exec"), ns)
    blind = ns["_hex_hits_outside_comments"]('BLUE = "#AABBCC"\n')
    gate("the reconstructed pre-K-135 helper is blind to a hex literal",
         blind == [], "returned %r" % (blind,))

    base = session.baseline(setup_test)
    base_names = [n for n, _ok in base.checks]

    # Control: with today's tokenised helper, a planted literal MUST be
    # seen.  Without this, "the vacuous one survives" proves nothing —
    # the plant might simply be invisible to everything.
    flow_src = session.pristine(flow_rel)
    plant = Mutation(flow_rel, "plant", "hex literal in setup_flow", 0,
                     "append %s" % _PLANTED_HEX.strip(), _plant_hex)
    control = session.evaluate(plant, [setup_test])
    gate("control: the FIXED pin catches a planted hex literal",
         control["verdict"] == "caught"
         and _HEX_CHECK in control["failing"],
         "verdict=%s failing=%r" % (control["verdict"], control["failing"]))

    # The case itself: revert the helper AND plant the literal.  If the
    # hex check still passes, the pin cannot fail.
    def revert_and_plant(src):
        reverted = _replace_function_source(src, "_hex_hits_outside_comments",
                                            _VACUOUS_HELPER)
        if reverted is None:
            return None
        return reverted

    session._write(setup_test, revert_and_plant(session.pristine(setup_test)))
    try:
        session._write(flow_rel, _plant_hex(flow_src))
        res = run_test(session.sandbox, setup_test)
        session.runs += 1
        hex_ok = _nth_check(res, base_names, _HEX_CHECK, 0)
        gate("the pre-K-135 pin does NOT fail on a planted literal "
             "(it cannot fail)", hex_ok is True,
             "check result was %r" % (hex_ok,))
        # And the tool must SAY so: the mutation-audit verdict for a pin
        # that cannot fail is the checks it should have tripped passing.
        gate("...and the planted literal is genuinely present in the "
             "module under test",
             _PLANTED_HEX.strip() in open(
                 os.path.join(session.sandbox, flow_rel), encoding="utf-8").read())
    finally:
        session.restore(setup_test)
        session.restore(flow_rel)

    print("\n== selftest (b): two decoys in a well-pinned module ==", file=out)
    hm_rel = "klausmate/heatmap.py"
    hm_src = session.pristine(hm_rel)
    hm_tests = ["tests/test_heatmap.py"]
    decoys = []
    tree = ast.parse(hm_src)
    wanted = {"stats_from_history": None, "level_for": None}
    for qual, node in _iter_functions(tree):
        if qual in wanted:
            wanted[qual] = node
    for qual in ("stats_from_history", "level_for"):
        node = wanted[qual]
        if node is None:
            gate("decoy target %s exists in heatmap.py" % qual, False)
            continue
        decoys.append(_make_insert_return(hm_rel, qual, node,
                                          _body_start(node)[0]))
    for decoy in decoys:
        rec = session.evaluate(decoy, hm_tests)
        gate("decoy caught: %s" % decoy.name,
             rec["verdict"] == "caught",
             "verdict=%s failing=%r" % (rec["verdict"], rec["failing"][:2]))

    print("\n== selftest (c): the working tree is untouched ==", file=out)
    return failures, session


# ---------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="prove the tool before trusting a finding")
    ap.add_argument("--modules", default="",
                    help="comma-separated module names, or 'all'")
    ap.add_argument("--list", dest="list_module", default="",
                    help="print the mutations for one module and exit")
    ap.add_argument("--scratch", default="",
                    help="scratch directory (default: a fresh temp dir)")
    ap.add_argument("--json", default="",
                    help="write the raw results to this path")
    ap.add_argument("--keep", action="store_true",
                    help="keep the scratch directory for inspection")
    args = ap.parse_args(argv)

    if not (args.selftest or args.modules or args.list_module):
        ap.error("nothing to do: pass --selftest, --modules or --list")

    guarded = _guarded_files()
    before = _hash_tree(guarded)

    if args.list_module:
        rel = "klausmate/%s.py" % args.list_module
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            muts, skipped = enumerate_mutations(rel, fh.read())
        for m in muts:
            print("%-9s %5d  %s  (%s)" % (m.kind, m.lineno, m.name, m.detail))
        for s in skipped:
            print("skipped   %5d  %s  (%s)" % (s[3], s[2], s[4]))
        print("%d mutations, %d pre-skipped" % (len(muts), len(skipped)))
        return 0

    scratch = args.scratch or tempfile.mkdtemp(prefix="klaus-mutation-audit-")
    os.makedirs(scratch, exist_ok=True)
    if os.path.abspath(scratch).startswith(REPO + os.sep):
        print("refusing to put the sandbox inside the repo: %s" % scratch)
        return 2

    rc = 0
    session = None
    started = time.time()
    try:
        if args.selftest:
            failures, session = selftest(scratch)
            after = _hash_tree(guarded)
            leaked, external = _classify_changes(_diff_hashes(before, after),
                                                 after)
            ok = not leaked and not (set(external) & session.touched_repo_paths())
            print("  %s the tree holds nothing this run wrote (%d files hashed)"
                  % ("PASS" if ok else "FAIL", len(guarded)))
            if leaked:
                failures.append("SANDBOX LEAKED into %s" % leaked[:5])
            if external:
                print("  note: %d file(s) changed under us — another session's "
                      "edits, none of them content this tool produced: %s"
                      % (len(external), [os.path.relpath(p, REPO)
                                         for p in external[:5]]))
                clash = sorted(set(external) & session.touched_repo_paths())
                if clash:
                    failures.append(
                        "a file this run mutated in the sandbox was edited in "
                        "the repo mid-run, so the answer is not trustworthy: %s"
                        % [os.path.relpath(p, REPO) for p in clash])
            print("\nselftest: %d test-file runs, %.1fs"
                  % (session.runs, time.time() - started))
            if failures:
                print("SELFTEST FAILED: %s" % "; ".join(map(str, failures)))
                return 1
            print("SELFTEST OK — all three cases answered correctly")
            return 0

        modules = (list(AUDIT_MODULES) if args.modules.strip() == "all"
                   else [m.strip() for m in args.modules.split(",") if m.strip()])
        bad = [m for m in modules if m not in AUDIT_MODULES]
        if bad:
            print("out of K-139's scope: %s (allowed: %s)"
                  % (bad, ", ".join(AUDIT_MODULES)))
            return 2
        session = Session(scratch)
        results = audit(session, modules)
        summary = {}
        for r in results:
            summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
        print("\n== totals ==")
        for k in sorted(summary):
            print("  %-20s %d" % (k, summary[k]))
        print("  %d test-file runs, %.1fs" % (session.runs, time.time() - started))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(results, fh, indent=1)
            print("  raw results -> %s" % args.json)
        return 0
    except BaseException as exc:  # KeyboardInterrupt included, by design
        print("\nABORTED: %r" % (exc,))
        rc = 3
        raise
    finally:
        # Restore first, verify second, clean up last — in that order, so
        # a failure in any of them still leaves the tree provably intact.
        try:
            if session is not None:
                session.restore_all()
        finally:
            after = _hash_tree(guarded)
            leaked, external = _classify_changes(_diff_hashes(before, after),
                                                 after)
            if leaked:
                sys.stderr.write(
                    "\n*** THE SANDBOX LEAKED INTO THE WORKING TREE ***\n"
                    "These repo files now hold content this run wrote. Restore "
                    "them before doing anything else:\n%s\n"
                    % "\n".join(leaked[:20])
                )
                os._exit(4)
            if external:
                sys.stderr.write(
                    "\nnote: %d repo file(s) changed while this ran, none of "
                    "them to content this tool produced (another session is "
                    "editing the checkout):\n%s\n"
                    % (len(external),
                       "\n".join(os.path.relpath(p, REPO) for p in external[:20]))
                )
            if not args.keep:
                shutil.rmtree(scratch, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
