"""The index runner (K-152): gates, queue, chain order, cancellation.

Two halves, matching the module's own divider.

The PURE half — config gates, the FIFO, the sweep plan, every string the
user reads — is exercised directly.

The RUNNER half is exercised against a FAKE PIPELINE: `curation`,
`retention` and `tag_sync` are replaced in sys.modules with recorders
that hand back their `on_done` callbacks, so the test drives each phase
by hand and can assert what runs, in what order, and — the part that
actually matters — what does NOT run after a cancel. `QTimer.singleShot`
is replaced with a queue the test drains, which is what makes "one job
at a time" observable at all: real Qt would start the next job whenever
it felt like it.

PDFs are real files in a temp tree (never `klausmate/user_files/`), so
the deleted-before-its-turn path runs the real `pdf_index.source_signature`
rather than a mock of it.
"""
from __future__ import annotations

import ast
import importlib
import os
import sys
import tempfile

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import ADDON, check, code_only, install, report, section  # noqa: E402

install()
iq = importlib.import_module("klausmate.index_queue")


# --------------------------------------------------------------- pure gates

section("config gates")

check("auto-index defaults ON when the key is absent", iq.auto_index_enabled({}))
check("...and ON for the shipped default", iq.auto_index_enabled({"auto_index_on_add": True}))
check("explicit False turns it off", not iq.auto_index_enabled({"auto_index_on_add": False}))
check(
    'a hand-edited "false" string turns it off too',
    not iq.auto_index_enabled({"auto_index_on_add": "false"}),
)
check(
    'and "off"/"0"/"no"',
    not any(
        iq.auto_index_enabled({"auto_index_on_add": v}) for v in ("off", "0", "no", "")
    ),
)
check(
    "a corrupt value reads ON, not OFF — the opposite of background."
    "design_enabled's rule, because the failure here is a deleted "
    "feature with no message rather than an unasked-for restyle",
    iq.auto_index_enabled({"auto_index_on_add": {"bogus": 1}})
    and iq.auto_index_enabled(None),
)

check(
    "no OpenAI key is refused, by name (2026-09-15: OpenAI is the only "
    "embedding provider, so the name is a constant, not a lookup)",
    iq.missing_key_provider({"api_key_openai": ""}) == "OpenAI",
)
check(
    "an OpenAI key passes",
    iq.missing_key_provider({"api_key_openai": "sk-1"}) == "",
)
check(
    "a whitespace-only key is no key",
    iq.missing_key_provider({"api_key_openai": "   "}) == "OpenAI",
)
check(
    "an empty config is judged missing — the key is absent, not blank",
    iq.missing_key_provider({}) == "OpenAI",
)
check(
    "a non-dict is never key-gated (the callers' defensive shape)",
    iq.missing_key_provider(None) == "",
)

section("Klaus Plus: the key gate and the sweep wording")
check(
    "a Plus key satisfies the key gate",
    iq.missing_key_provider({"klaus_plus_key": "kp_" + "f" * 32}) == "",
)
check(
    "no key of either kind still names OpenAI",
    iq.missing_key_provider({}) == "OpenAI",
)
check(
    "the key message also points at Klaus Plus",
    "Klaus Plus" in iq.missing_key_message("OpenAI"),
)
_plus_msg = iq.sweep_message(2, 100, "text-embedding-3-large", "~1,000 tokens · under $0.01", plus=True)
check(
    "on Plus the sweep is 'included', not billed",
    "included in Klaus Plus" in _plus_msg and "billed to your OpenAI key" not in _plus_msg and "$" not in _plus_msg,
)
check(
    "off Plus the estimate is billed to the key",
    "billed to your OpenAI key" in iq.sweep_message(2, 100, "m", "~x", plus=False),
)


# -------------------------------------------------------------- the queue

section("JobQueue")

q = iq.JobQueue()
check("enqueue reports newly-added", q.enqueue((iq.JOB_PDF, "a")) is True)
check("a duplicate collapses", q.enqueue((iq.JOB_PDF, "a")) is False)
q.enqueue((iq.JOB_PDF, "b"))
q.enqueue((iq.JOB_PDF, "c"))
check("pending counts what is waiting", q.pending() == 3)
check("FIFO: the first PDF added is the first indexed", q.pop() == (iq.JOB_PDF, "a"))
check("drop removes a deleted PDF's jobs", q.drop("c") == 1 and q.pending() == 1)
check("drop of an absent name is a no-op", q.drop("zzz") == 0)
q.enqueue((iq.JOB_CARDS, ""))
check("a card job and a PDF job of the same name never collide", q.pending() == 2)
check("requeue puts a job back at the FRONT", (lambda: (q.requeue((iq.JOB_PDF, "z")), q.snapshot()[0] == (iq.JOB_PDF, "z"))[1])())
check("requeue never duplicates", (q.requeue((iq.JOB_PDF, "z")), q.pending())[1] == 3)
check("clear reports what it dropped", q.clear() == 3 and q.pending() == 0)

check(
    "a sweep leads with the card index, then every PDF in order",
    iq.sweep_jobs(["x", "y"])
    == [(iq.JOB_CARDS, ""), (iq.JOB_PDF, "x"), (iq.JOB_PDF, "y")],
)
check(
    "a collection with no PDFs still re-embeds its cards",
    iq.sweep_jobs([]) == [(iq.JOB_CARDS, "")],
)


# ------------------------------------------------------- what the user reads

section("status text")

busy = iq.RunnerState(active=True, name="Lecture 3", label="Embedding PDF…", done=1, total=4)
check("progress reads as name, phase, percent", iq.status_line(busy) == "Lecture 3 — Embedding PDF… 25%")
check(
    "no total means no percent (a scan has no denominator)",
    iq.status_line(busy._replace(done=0, total=0)) == "Lecture 3 — Embedding PDF…",
)
check(
    "queued work is named in the same line — the part of a ten-PDF "
    "drop the user cannot otherwise see",
    "3 more queued" in iq.status_line(busy._replace(pending=3)),
)
check(
    "an idle runner reads as its message, not as a stale percentage",
    iq.status_line(iq.RunnerState(message="Indexed “X”.")) == "Indexed “X”.",
)
check("an idle runner with nothing to say says nothing", iq.status_line(iq.RunnerState()) == "")
check(
    "a card-index job is still named",
    iq.status_line(iq.RunnerState(active=True, label="Embedding cards…"))
    == "Card index — Embedding cards…",
)
check(
    "the judge phase counts cards, not a rounded percent — 'judging "
    "12/40' says how much work is left in a way a percentage would flatten",
    "judging 12/40" in iq.status_line(
        iq.RunnerState(active=True, name="Lec", label="judging", phase="judge", done=12, total=40)
    ),
)

msg = iq.sweep_message(2, 30000, "text-embedding-3-large",
                       "~1,000 tokens · about $0.01")
check("the sweep names the model", "text-embedding-3-large" in msg)
check("...counts both kinds of work", "30,000 notes" in msg and "2 PDFs" in msg)
check(
    "...and carries the cost estimate VERBATIM, plus whose key pays it — "
    "a from-scratch re-embed of the whole collection is a paid API call, "
    "and a confirm that hides the price is not a confirm",
    "~1,000 tokens · about $0.01" in msg and "OpenAI" in msg,
)
check(
    "...and still says the run can be stopped from the bottom bar",
    "stop it" in msg.lower(),
)
check(
    "...and says what declining actually COSTS — the next PDF add runs "
    "the card index from scratch as phase one, unpriced and unconfirmed, "
    "so a bare No reads as 'not now, and free' when it means 'not now, "
    "and without being asked again'",
    "If you decline, the card index is still rebuilt — unpriced — the "
    "first time a PDF is indexed." in msg,
)
_one = iq.sweep_message(1, 1, "m", "~0 tokens · under $0.01")
# "1 PDF" is a SUBSTRING of "1 PDFs", so the obvious form of this check
# passes against a message that never learned the singular at all — it
# did, until the falsification pass made it fail and it didn't. The
# absence of the plural is the half with teeth.
check(
    "...singular when it is one, with the plural really gone",
    "1 PDF" in _one and "1 note" in _one
    and "1 PDFs" not in _one and "1 notes" not in _one,
)
check(
    "the add tooltip distinguishes running from queued",
    iq.queued_message("A", 0).startswith("KlausMate: indexing")
    and "3 ahead of it" in iq.queued_message("A", 3),
)
check("the key refusal names the provider and where to fix it", "OpenAI" in iq.missing_key_message("OpenAI") and "API keys & models" in iq.missing_key_message("OpenAI"))
check(
    "the bar's one button stops a run and clears a finished one",
    iq.dock_button_label(iq.RunnerState(active=True)) == "Stop"
    and iq.dock_button_label(iq.RunnerState(message="Indexed “X”.")) == "Dismiss",
)


# ------------------------------------------------ signature change detection

section("model-change detection")

sig_a = ("voyage", "voyage-3-lite", 0)
check("identical settings are not a change", not iq.signature_changed(sig_a, sig_a))
check("a changed model is a change", iq.signature_changed(sig_a, ("voyage", "voyage-3", 0)))
check("a changed provider is a change", iq.signature_changed(sig_a, ("openai", "voyage-3-lite", 0)))
check(
    "a width the new settings ASK for, that the old vectors don't have, "
    "is a change",
    iq.signature_changed(("openai", "text-embedding-3-large", 0), ("openai", "text-embedding-3-large", 1024)),
)
check(
    "...and a stored width under a new setting of 0 (the model's own "
    "default) is NOT — signature_matches' rule, inherited not re-spelled",
    not iq.signature_changed(("openai", "text-embedding-3-large", 1024), ("openai", "text-embedding-3-large", 0)),
)
check(
    "a legacy 2-tuple does not read as a change against an equal 3-tuple "
    "— the exact shape that silently re-embedded everything when the "
    "signature grew a third element",
    not iq.signature_changed(("voyage", "voyage-3-lite"), ("voyage", "voyage-3-lite", 0)),
)


# ------------------------------------------------------------ the fake world


class FakeDb:
    """Just enough of col.db for sweep_estimate's one scalar: the total
    length of every note's fields. 0 by default so the pins that don't
    care about cost are unaffected."""

    def __init__(self):
        self.total = 0

    def scalar(self, _sql, *_a):
        return self.total


class FakeCol:
    def __init__(self):
        self.db = FakeDb()

    def note_count(self):
        return 1234


class FakeAddonManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def getConfig(self, _pkg):
        return self.cfg


class FakeMw:
    def __init__(self, cfg):
        self.col = FakeCol()
        self.addonManager = FakeAddonManager(cfg)

    def addDockWidget(self, *_a):
        pass

    def removeDockWidget(self, *_a):
        pass


class FakeTimer:
    """QTimer.singleShot as an explicit queue the test drains. Real Qt
    would start the next job whenever it liked; here 'one job at a time'
    is something we can actually observe."""

    pending = []

    @staticmethod
    def singleShot(_ms, fn):
        FakeTimer.pending.append(fn)

    @staticmethod
    def drain(limit=50):
        n = 0
        while FakeTimer.pending and n < limit:
            FakeTimer.pending.pop(0)()
            n += 1


class FakeIndex:
    def __init__(self, complete=True):
        self._complete = complete

    def is_complete(self):
        return self._complete


class Pipeline:
    """Stands in for curation + retention + tag_sync, recording the phase
    order and parking each on_done so the test completes phases by hand."""

    def __init__(self):
        self.calls = []
        self.pending = {}
        self.cancels = []
        self._busy = False  # curation's shared re-entrancy token
        self.rejected_global = set()  # what all_rejected() hands back
        self._judge_raises = None  # one-shot exception for ensure_judged (fix round 1, C1)

    # -- curation ------------------------------------------------------
    def ensure_index(self, _parent, *, on_progress=None, on_done=None, on_error=None, cancel=None):
        self.calls.append(("ensure_index", ""))
        self.cancels.append(cancel)
        self.pending["cards"] = (on_done, on_error, on_progress)

    # -- retention -----------------------------------------------------
    def ensure_pdf_index(self, _parent, name, *, on_progress=None, on_done=None, on_error=None, cancel=None):
        self.calls.append(("ensure_pdf_index", name))
        self.pending["pdf"] = (on_done, on_error, on_progress)

    def ensure_matches(self, _parent, name, *, on_progress=None, on_done=None, on_error=None, cancel=None):
        self.calls.append(("ensure_matches", name))
        self.pending["matches"] = (on_done, on_error, on_progress)

    # -- tag_sync ------------------------------------------------------
    def sync_after_matches(self, _mw, name, matches, **_k):
        self.calls.append(("tag_sync", name))

    # -- pertinence ------------------------------------------------------
    def ensure_judged(self, _parent, name, _matches, *, on_done=None, on_error=None, cancel=None, on_progress=None, ask=None):
        self.calls.append(("ensure_judged", name))
        if self._judge_raises is not None:
            exc, self._judge_raises = self._judge_raises, None
            raise exc
        self.pending["judge"] = (on_done, on_error, on_progress)

    def all_rejected(self, _user_files):
        return self.rejected_global

    # -- drivers -------------------------------------------------------
    def finish_cards(self, completed=True):
        self.pending.pop("cards")[0](FakeIndex(), completed)

    def finish_pdf(self, complete=True):
        self.pending.pop("pdf")[0](FakeIndex(complete))

    def finish_matches(self, matches=((1, 0.9),)):
        self.pending.pop("matches")[0](list(matches))

    def finish_judge(self, rejected=frozenset()):
        self.pending.pop("judge")[0](set(rejected))

    def raise_in(self, phase, exc):
        self.pending.pop(phase)[1](exc)

    def progress(self, phase, label, done, total):
        self.pending[phase][2](label, done, total)


def new_world(cfg=None, names=("a", "b", "c")):
    """Reset every module global and build a temp library on disk."""
    tmp = tempfile.mkdtemp(prefix="klaus-iq-")
    os.makedirs(os.path.join(tmp, "contexts"))
    for n in names:
        with open(os.path.join(tmp, "contexts", n + ".txt"), "w") as f:
            f.write("page text " + n)
    pkg = sys.modules["klausmate"]
    pkg.USER_FILES = tmp

    pipe = Pipeline()
    for dotted, obj in (
        ("klausmate.curation", pipe),
        ("klausmate.retention", pipe),
        ("klausmate.tag_sync", pipe),
        ("klausmate.pertinence", pipe),
    ):
        sys.modules[dotted] = obj
        setattr(pkg, dotted.split(".")[1], obj)

    iq.mw = FakeMw(cfg if cfg is not None else {"api_key_openai": "sk"})
    iq.QTimer = FakeTimer
    iq.QDockWidget = None  # headless: no dock, the pure status_line is the pin
    FakeTimer.pending = []
    iq._queue = iq.JobQueue()
    iq._current = None
    iq._cancel = None
    iq._seq = 0
    iq._waits = 0
    iq._state = iq.RunnerState()
    iq._listeners = []
    iq._key_warned = False
    iq._dock = None
    return tmp, pipe


def run_one(pipe, name):
    """Drive one PDF job to completion."""
    pipe.finish_cards()
    pipe.finish_pdf()
    pipe.finish_matches()
    pipe.finish_judge()


# ----------------------------------------------------------------- the chain

section("the chain")

tmp, pipe = new_world()
iq.request_pdf("a", announce=False)
check("nothing starts inside the caller's event — the add returns first", pipe.calls == [])
FakeTimer.drain()
check("phase 1 is the CARD index, always", pipe.calls == [("ensure_index", "")])
pipe.finish_cards()
check("phase 2 is the PDF's own index", pipe.calls[-1] == ("ensure_pdf_index", "a"))
pipe.finish_pdf()
check("phase 3 is matching", pipe.calls[-1] == ("ensure_matches", "a"))
pipe.finish_matches()
check("phase 4 judges pertinence", pipe.calls[-1] == ("ensure_judged", "a"))
pipe.finish_judge()
check("phase 5 writes the PDF's !Library tag", pipe.calls[-1] == ("tag_sync", "a"))
check(
    "the whole chain, in order, once",
    [c[0] for c in pipe.calls]
    == ["ensure_index", "ensure_pdf_index", "ensure_matches", "ensure_judged", "tag_sync"],
)
check("a completed job publishes its name so the Library can re-aggregate", iq.state().finished == "a")
check("...and reads as idle", not iq.state().active)

tmp, pipe = new_world()
iq.request([(iq.JOB_CARDS, "")], announce=False)
FakeTimer.drain()
pipe.finish_cards()
check(
    "a card-index job stops after phase 1 — there is no PDF to index",
    [c[0] for c in pipe.calls] == ["ensure_index"],
)

section("fix round 1, C1 — a pertinence-phase exception never wedges the queue")

tmp, pipe = new_world()
pipe._judge_raises = KeyError("claude-sonnet-4-5")
iq.request_pdf("a", announce=False)
FakeTimer.drain()
pipe.finish_cards()
pipe.finish_pdf()
pipe.finish_matches()
check(
    "ensure_judged raising reaches after_matches' own try/except, not the "
    "caller's QueryOp — pipe.calls sees the attempt",
    pipe.calls[-2] == ("ensure_judged", "a"),
)
check(
    "...and the PDF is STILL tagged — an untagged pertinence phase beats a "
    "wedged queue, the next index pass can always re-judge. The tag write "
    "goes through the SAME after_judged the normal path uses (source/AST-"
    "pinned above), so it still passes doubtful=pertinence.all_rejected(...)",
    pipe.calls[-1] == ("tag_sync", "a"),
)
check(
    "...and _current actually clears — the next queued job is free to run "
    "(this is the wedge C1 found: a bare raise never reaches _job_done)",
    iq._current is None,
)
FakeTimer.drain()
check("...the run really did finish, idle, not stuck mid-job", not iq.state().active)


# ------------------------------------------------------------------ the queue

section("ten PDFs, one at a time")

tmp, pipe = new_world(names=[f"p{i}" for i in range(10)])
for i in range(10):
    iq.request_pdf(f"p{i}", announce=False)
check("ten adds queue ten jobs, none refused", iq._queue.pending() == 10)
FakeTimer.drain()
check("exactly ONE job is in flight", len([c for c in pipe.calls if c[0] == "ensure_index"]) == 1)
check("...on the FIRST PDF added", iq.state().name == "p0")
check("...and nine are still waiting", iq.state().pending == 9)
run_one(pipe, "p0")
FakeTimer.drain()
check("finishing one starts the next", iq.state().name == "p1")
check("...and only the next", [c for c in pipe.calls if c[0] == "ensure_pdf_index"] == [("ensure_pdf_index", "p0")])
pipe.finish_cards()
check("the second job runs the same chain", pipe.calls[-1] == ("ensure_pdf_index", "p1"))

tmp, pipe = new_world()
iq.request_pdf("a", announce=False)
iq.request_pdf("a", announce=False)
check("dropping the same PDF twice queues it once", iq._queue.pending() == 1)
FakeTimer.drain()
iq.request_pdf("a", announce=False)
check("re-requesting the RUNNING PDF does not queue a second pass", iq._queue.pending() == 0)

# The ten-drop above adds everything before the first job starts, so it
# cannot see a request arriving mid-run — which is the case the shared
# _busy token gets WRONG (it refuses) and the whole card exists to fix.
tmp, pipe = new_world(names=("a", "b"))
iq.request_pdf("a", announce=False)
FakeTimer.drain()
check("a job really is running", iq._current is not None)
check(
    "a PDF added WHILE one is indexing is QUEUED, not refused — the "
    "user did nothing wrong, and curation._busy's refusal is the answer "
    "to a double-clicked button, not to a legitimate batch",
    iq.request_pdf("b", announce=False) is True and iq._queue.pending() == 1,
)
check("...and the running job is undisturbed", iq.state().name == "a")
check("...with the newcomer counted in the line both surfaces read", iq.state().pending == 1)
run_one(pipe, "a")
FakeTimer.drain()
check("...then it runs", iq.state().name == "b")

tmp, pipe = new_world()
seen = []
iq.add_listener(seen.append)
iq.request_pdf("a", announce=False)
FakeTimer.drain()
check("a subscriber sees the run start", any(s.active for s in seen))
pipe.progress("cards", "Embedding cards…", 3, 10)
check(
    "...and every progress tick, with the phase's own label and counts",
    iq.state().label == "Embedding cards…" and iq.state().done == 3
    and iq.state().total == 10,
)
check("...published, not merely stored", seen[-1] == iq.state())
iq.remove_listener(seen.append)
before = len(seen)
pipe.progress("cards", "Embedding cards…", 4, 10)
check("an unsubscribed surface stops hearing about it", len(seen) == before)


# ------------------------------------------------------------- deleted PDFs

section("a PDF deleted mid-queue")

tmp, pipe = new_world(names=("a", "b"))
iq.request_pdf("a", announce=False)
iq.request_pdf("b", announce=False)
FakeTimer.drain()
os.remove(os.path.join(tmp, "contexts", "b.txt"))
run_one(pipe, "a")
FakeTimer.drain()
check(
    "a PDF deleted before its turn is skipped silently — no phase runs "
    "for it, and no error the user never caused",
    [c for c in pipe.calls if c[1] == "b"] == [],
)
check("...and the runner ends up idle, not stuck", iq._current is None)

tmp, pipe = new_world(names=("a", "b"))
iq.request_pdf("a", announce=False)
iq.request_pdf("b", announce=False)
FakeTimer.drain()
os.remove(os.path.join(tmp, "contexts", "a.txt"))
pipe.finish_cards()
pipe.raise_in("pdf", RuntimeError("No stored text for “a” — re-import the PDF."))
FakeTimer.drain()
pipe.finish_cards()
check(
    "deleting the RUNNING PDF does not take the rest of the batch down "
    "with it — that error says nothing about the jobs behind it",
    ("ensure_pdf_index", "b") in pipe.calls,
)
check(
    "...and it is not reported as a failure either",
    "not started" not in iq.state().message,
)


# -------------------------------------------------------------- cancellation

section("cancel")

tmp, pipe = new_world()
iq.request_pdf("a", announce=False)
iq.request_pdf("b", announce=False)
FakeTimer.drain()
pipe.finish_cards()
pipe.finish_pdf()
iq.cancel_all()
check("cancel sets the token the phases are watching", pipe.cancels[-1].is_set())
check("cancel forgets the rest of the queue", iq._queue.pending() == 0)
pipe.finish_matches()
check(
    "a cancelled run NEVER writes the tag: ensure_matches hands back a "
    "PARTIAL ranking and tagging on it would silently shrink the PDF's "
    "!Library membership",
    ("tag_sync", "a") not in pipe.calls,
)
check(
    "...and never reaches the judge phase either — a cancelled matches "
    "pass has nothing worth paying to judge",
    ("ensure_judged", "a") not in pipe.calls,
)
FakeTimer.drain()
check("...and nothing new starts", [c for c in pipe.calls if c[1] == "b"] == [])
check("the user is told, in the same status line both surfaces read", "cancelled" in iq.status_line(iq.state()).lower())

tmp, pipe = new_world(names=("a", "b"))
iq.request_pdf("a", announce=False)
iq.request_pdf("b", announce=False)
FakeTimer.drain()
pipe.finish_cards(completed=False)
check(
    "a phase reporting PARTIAL work stops the run instead of matching "
    "cards against half an index",
    [c[0] for c in pipe.calls] == ["ensure_index"],
)
check("...says so, in words that promise the work is not lost", "resumes" in iq.state().message)
FakeTimer.drain()
check(
    "...and stops the QUEUE too: whatever halted one job will halt the "
    "next, and each attempt is billable",
    iq._queue.pending() == 0 and [c[0] for c in pipe.calls] == ["ensure_index"],
)

tmp, pipe = new_world()
iq.request_pdf("a", announce=False)
FakeTimer.drain()
pipe.finish_cards()
pipe.finish_pdf(complete=False)
check(
    "...same for a half-embedded PDF, before it can be tagged",
    [c[0] for c in pipe.calls] == ["ensure_index", "ensure_pdf_index"],
)

tmp, pipe = new_world(names=("a", "b", "c"))
iq.request_pdf("a", announce=False)
iq.request_pdf("b", announce=False)
iq.request_pdf("c", announce=False)
check("deleting a PDF forgets its queued job by name", iq.forget("b") == 1)
check("...and only its own", iq._queue.pending() == 2)

tmp, pipe = new_world()
iq.request_pdf("a", announce=False)
iq._key_warned = True
iq._on_profile_close()
check(
    "a profile close stops everything — the phases read the collection "
    "and write into user_files, and both are about to go away",
    iq._queue.pending() == 0 and iq._current is None,
)
check("...and the once-per-session key warning re-arms for the next profile", iq._key_warned is False)


# -------------------------------------------------------------------- errors

section("failure")

tmp, pipe = new_world()
iq.request_pdf("a", announce=False)
iq.request_pdf("b", announce=False)
FakeTimer.drain()
pipe.raise_in("cards", RuntimeError("voyage is down"))
FakeTimer.drain()
check("one failure ends the run — ten identical billed retries are not information", [c for c in pipe.calls if c[1] == "b"] == [])
check("...and says how much work it dropped", "not started" in iq.state().message)
check("...naming the cause", "voyage is down" in iq.state().message)


# --------------------------------------------------------------------- gates

section("gates")

tmp, pipe = new_world()
iq.mw.col = None
check("no profile, no job", iq.request_pdf("a", announce=False) is False)
check("...and nothing queued to leak into the next profile", iq._queue.pending() == 0)

tmp, pipe = new_world(cfg={"api_key_openai": ""})
check("no API key, no job", iq.request_pdf("a", announce=False) is False)
check(
    "...and the refusal is a MESSAGE, not a shrug — a silent no-op on "
    "every drop would be worse than the button this replaces",
    "API key" in iq.state().message,
)
FakeTimer.drain()
check("...nothing ran", pipe.calls == [])

tmp, pipe = new_world(cfg={"api_key_openai": "sk", "auto_index_on_add": False})
check("auto-index off: an import does not queue", iq.on_pdf_imported("a") is False)
check("...but the Library's own button still works", iq.request_pdf("a", announce=False) is True)

tmp, pipe = new_world()
check("auto-index on: an import queues", iq.on_pdf_imported("a") is True)
check("an empty name never queues", iq.on_pdf_imported("") is False)


# ------------------------------------------------- contention with Index Now

section("Preferences' Index Now holds the same token")

tmp, pipe = new_world()
pipe._busy = True  # curation._busy, taken by the dialog's own run
iq.request_pdf("a", announce=False)
FakeTimer.drain(limit=1)
check(
    "a drop during Index Now WAITS for the shared token instead of "
    "being refused and taking the queue down as a failure",
    pipe.calls == [] and iq._queue.pending() == 1,
)
check("...and says so", iq.state().message == iq.BUSY_WAIT_TEXT)
pipe._busy = False
FakeTimer.drain(limit=1)
check("...then runs as soon as the token frees", pipe.calls == [("ensure_index", "")])

tmp, pipe = new_world()
pipe._busy = True
iq.request_pdf("a", announce=False)
for _ in range(iq.BUSY_WAIT_POLLS + 2):
    FakeTimer.drain(limit=1)
check("waiting is bounded — it never spins forever", FakeTimer.pending == [])
check("...and the work is kept, not thrown away", iq._queue.pending() == 1)


# -------------------------------------------------------------- the sweep set

section("the sweep set")

tmp, pipe = new_world(names=("a", "b"))
pdf_index = importlib.import_module("klausmate.pdf_index")
embeddings = importlib.import_module("klausmate.embeddings")
os.makedirs(pdf_index.index_dir(tmp, "a"))
with open(os.path.join(pdf_index.index_dir(tmp, "a"), "manifest.json"), "w") as f:
    f.write('{"version": %d, "pages": [[0,"h0"]], "embedded_rows": 1, '
            '"provider": "openai", "model": "text-embedding-3-large", "dims": 1024}'
            % pdf_index.INDEX_VERSION)
names = iq.indexed_pdf_names()
check("a PDF with an index on disk is swept", "a" in names)
check(
    "a PDF that was never indexed is not — there is nothing stale to "
    "rebuild, and indexing it is a decision the user has not made",
    "b" not in names,
)
check(
    "an unchanged signature offers nothing — saving Preferences without "
    "touching the model must not propose a whole-collection re-embed",
    iq.offer_model_sweep(None, embeddings.index_signature({})) is False,
)
check(
    "...and with every manifest at the current version nothing is stale, "
    "so the upgrade trigger cannot fire on a profile with nothing to "
    "upgrade",
    iq.stale_index_names() == [],
    str(iq.stale_index_names()),
)

# A PRE-UPGRADE index: the shape an existing profile actually carries on
# the morning it installs this plan.
os.makedirs(pdf_index.index_dir(tmp, "b"))
with open(os.path.join(pdf_index.index_dir(tmp, "b"), "manifest.json"), "w") as f:
    f.write('{"version": 1, "chunks": [[0,"h0"]], "embedded_rows": 1, '
            '"provider": "voyage", "model": "voyage-3-lite", "dims": 1024}')
check(
    "a pre-upgrade (v1) manifest is swept too — membership is \"has a "
    "manifest file\", ANY version. stats_from_disk reads through "
    "card_index.read_manifest, which answers None for every version but "
    "the current one, so a version gate here silently excludes the exact "
    "population the sweep exists for: every index built before this plan",
    sorted(iq.indexed_pdf_names()) == ["a", "b"],
    str(iq.indexed_pdf_names()),
)
check(
    "...and stale_index_names names ONLY the out-of-date one",
    iq.stale_index_names() == ["b"],
    str(iq.stale_index_names()),
)
check(
    "a stale-version manifest is the THIRD sweep trigger: it offers the "
    "re-index even though the signature never moved and the key is not "
    "new — an upgrade moves no signature, so without this an upgrader is "
    "never asked, while every PDF reads as absent in the Library",
    iq.offer_model_sweep(None, embeddings.index_signature({})) is True,
)
check(
    "...and a closed profile offers nothing either",
    (setattr(iq.mw, "col", None), iq.offer_model_sweep(None, ("openai", "x", 0)))[1]
    is False,
)

# A null (non-dict) manifest, sorting BEFORE "b" in the walk
# (_manifest_paths follows list_contexts' sort order): a corrupt
# manifest must be skipped, not a scan-stopper — "b"'s real v1
# manifest, later in the walk, still has to be reported stale.
with open(os.path.join(tmp, "contexts", "aaa.txt"), "w") as f:
    f.write("page text aaa")
os.makedirs(pdf_index.index_dir(tmp, "aaa"))
with open(os.path.join(pdf_index.index_dir(tmp, "aaa"), "manifest.json"), "w") as f:
    f.write("null")
check(
    "a null manifest doesn't truncate the scan — the real v1 manifest "
    "past it is still reported stale",
    iq.stale_index_names() == ["b"],
    str(iq.stale_index_names()),
)


# ------------------------------------------------------- what the sweep costs

section("the sweep estimate")

tmp, pipe = new_world(names=("a",))
page_store = importlib.import_module("klausmate.page_store")
pdf_handler = importlib.import_module("klausmate.pdf_handler")

iq.mw.col.db.total = 40_000
_est = iq.sweep_estimate([])
check(
    "the estimate counts the whole collection's note text — one scalar "
    "over notes.flds, at cost.py's four-chars-a-token",
    _est.tokens == 10_000 and _est.dollars > 0,
    f"got {_est!r}",
)

import json as _json  # noqa: E402

with open(os.path.join(tmp, "contexts", "a.json"), "w") as f:
    _json.dump({"pages": ["x", "y"]}, f)
_path = pdf_handler.pdf_path_for(tmp, "a") or ""
page_store.ensure_records(tmp, "a", _path, ["a" * 4000, "b" * 4000])
_est2 = iq.sweep_estimate(["a"])
check(
    "...plus every PAGE of every swept PDF — the page store is what gets "
    "re-embedded now, not a chunking of the raw text file",
    _est2.tokens == _est.tokens + 2000,
    f"got {_est2!r} vs {_est!r}",
)

with open(os.path.join(tmp, "contexts", "d.json"), "w") as f:
    _json.dump({"pages": ["p" * 2000, "q" * 2000]}, f)
_est3 = iq.sweep_estimate(["d"])
check(
    "...and a PDF with stored slide text but NO page-store records yet "
    "(no ensure_records call at all) is counted at its slide-text "
    "length, not skipped as zero — every PDF on every existing profile "
    "is in exactly this state the first time this ships",
    _est3.tokens == _est.tokens + 1000,
    f"got {_est3!r} vs {_est!r}",
)

check(
    "a PDF with no pages on disk contributes nothing and never raises",
    iq.sweep_estimate(["b"]).tokens == _est.tokens,
)

check(
    "a FIRST key offers the sweep even though the signature never moved "
    "— nothing was ever embedded, so there is nothing for the comparison "
    "to see, and that is exactly the moment the offer matters",
    iq.offer_model_sweep(None, embeddings.index_signature(iq._cfg()),
                         first_key=True) is True,
)
check(
    "...and without it that same unchanged signature still offers nothing",
    iq.offer_model_sweep(None, embeddings.index_signature(iq._cfg()))
    is False,
)

iq.mw.addonManager.cfg["embedding_model"] = "surprise-model-9"
_raised = False
try:
    iq.sweep_estimate([])
except Exception:
    _raised = True
iq.mw.addonManager.cfg.pop("embedding_model")
check(
    "a hand-typed model with no published price RAISES rather than "
    "silently pricing itself as some other model...",
    _raised,
)
check(
    "...and offer_model_sweep catches that and says the cost is unknown, "
    "so the confirm still appears (the re-embed is the user's to refuse)",
    "cost unknown" in open(os.path.join(ADDON, "index_queue.py")).read(),
)


class _RaisingDb:
    def scalar(self, _sql, *_a):
        raise RuntimeError("notes scalar boom")


_captured_estimate: dict = {}
_orig_sweep_message = iq.sweep_message


def _capture_sweep_message(n_pdfs, n_notes, model, estimate, plus=False):
    # Task 7 re-baseline: sweep_message grew a `plus` keyword, and
    # offer_model_sweep now always passes it — this stand-in must accept
    # (and forward) it too, or the call from offer_model_sweep raises a
    # TypeError that has nothing to do with what this test checks.
    _captured_estimate["estimate"] = estimate
    return _orig_sweep_message(n_pdfs, n_notes, model, estimate, plus=plus)


_orig_notes_db = iq.mw.col.db
iq.mw.col.db = _RaisingDb()
iq.sweep_message = _capture_sweep_message
try:
    iq.offer_model_sweep(
        None, embeddings.index_signature(iq._cfg()), first_key=True
    )
finally:
    iq.mw.col.db = _orig_notes_db
    iq.sweep_message = _orig_sweep_message
check(
    "a failed notes scalar does NOT degrade to a cheap estimate — the "
    "confirm must read cost unknown, never price a real re-embed at "
    "~0 tokens because one SQL call happened to fail",
    _captured_estimate.get("estimate") == "cost unknown for this model",
    f"got {_captured_estimate!r}",
)


# ------------------------------------------------------------- source pins

section("one chain, one copy")

_iq_raw = open(os.path.join(ADDON, "index_queue.py")).read()  # docstrings are STRING tokens — code_only strips them
_iq_src = code_only(_iq_raw)
_drive_src = code_only(open(os.path.join(ADDON, "pdf_drive.py")).read())
_init_src = code_only(open(os.path.join(ADDON, "__init__.py")).read())

check(
    "the priced confirm defaults to No — Save's own button is already "
    "Enter-default, so Enter in the key field reaches this window-modal "
    "confirm next with keyboard focus; a stray Enter must not start a "
    "paid whole-collection re-embed, the same rule "
    "clear_assistant_sessions' confirm already follows",
    "box.setDefaultButton(QMessageBox.StandardButton.No)" in _iq_src,
)
check(
    "index_queue holds the ONLY copy of the chain",
    _iq_src.count("curation.ensure_index(") == 1
    and _iq_src.count("retention.ensure_pdf_index(") == 1
    and _iq_src.count("retention.ensure_matches(") == 1,
)
check(
    "the Doubtful tag's membership is passed through as the GLOBAL "
    "rejected set — never a hand-picked subset of this one job's matches",
    "doubtful=pertinence.all_rejected(" in _iq_src,
)
check(
    "ask_judge is window-modal (.open(), never .exec()) with Skip as the "
    "default button — the same K-114 rule and Enter-safety "
    "offer_model_sweep's own confirm follows",
    "box.open()" in _iq_src
    and "box.setDefaultButton(skip_btn)" in _iq_src
    and ".exec(" not in _iq_src,
)
check(
    "...offering Judge and Skip as real buttons, not a Yes/No stand-in",
    'box.addButton("Judge", QMessageBox.ButtonRole.AcceptRole)' in _iq_raw
    and 'box.addButton("Skip", QMessageBox.ButtonRole.RejectRole)' in _iq_raw,
)
check(
    "fix round 1, I2 — the module docstring's chain names all five phases, "
    "pertinence.ensure_judged included, in order",
    "``curation.ensure_index`` → ``retention.ensure_pdf_index`` →\n"
    "``retention.ensure_matches`` → ``pertinence.ensure_judged`` →\n"
    "``tag_sync.sync_after_matches``" in _iq_raw,
)
check(
    "fix round 1, I1 — the docstring names phase four as the ONE exception "
    "to 'each phase takes curation._busy in turn', and says why (K-255 "
    "review): holding the token across the Judge/Skip dialog would "
    "re-create the exact K-146 leak the same paragraph warns about",
    "with ONE exception: phase four" in _iq_raw
    and "never touches it at all" in _iq_raw
    and "Judge/Skip dialog" in _iq_raw,
)
check(
    "offer_model_sweep routes the Plus flag from plus.active — a hand-"
    "computed bool here is how a stale cache or a just-added key would "
    "silently mis-price the sweep confirm",
    "plus=plus.active(" in _iq_src,
)
check(
    "the Library no longer spells the chain itself — a second copy is "
    "the K-143 two-renderer failure with a different subject",
    "ensure_pdf_index(" not in _drive_src
    and "ensure_matches(" not in _drive_src
    and "curation.ensure_index(" not in _drive_src,
)
check(
    "...and drives the shared runner instead",
    "index_queue.request_pdf(" in _drive_src
    and "index_queue.cancel_all()" in _drive_src,
)
check(
    "the Library renders the runner's own status_line, so the two "
    "surfaces cannot describe one job differently",
    "index_queue.status_line(" in _drive_src,
)


def _fn(src_path, name, cls=None):
    tree = ast.parse(open(src_path).read())
    nodes = [tree]
    if cls:
        nodes = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == cls
        ]
    for root in nodes:
        for n in ast.walk(root):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
                return n
    return None


_shutdown = _fn(os.path.join(ADDON, "pdf_drive.py"), "shutdown", cls="DriveWindow")
_shutdown_calls = {
    ast.unparse(n.func) if hasattr(ast, "unparse") else ""
    for n in ast.walk(_shutdown)
    if isinstance(n, ast.Call)
} if _shutdown else set()
check("DriveWindow.shutdown exists to pin", _shutdown is not None)
check(
    "closing the Library does NOT cancel indexing — a job may have been "
    "started from the deck screen, and minutes of paid embedding must "
    "not die because a window was tidied away",
    "self._on_cancel" not in _shutdown_calls,
)
check(
    "...it unsubscribes instead",
    "index_queue.remove_listener" in _shutdown_calls,
)

_sig_fn = _fn(os.path.join(ADDON, "index_queue.py"), "signature_changed")
check("signature_changed exists to pin", _sig_fn is not None)
check(
    "signature detection never spells an == or != itself — a hand-"
    "written tuple comparison is what read every cache as stale and "
    "silently re-embedded everything on a paid API when the signature "
    "grew a third element (a length check is fine; equality is not)",
    _sig_fn is not None
    and not [
        n
        for n in ast.walk(_sig_fn)
        if isinstance(n, ast.Compare)
        and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in n.ops)
    ],
)
check(
    "...it delegates to embeddings.signature_matches",
    _sig_fn is not None
    and any(
        isinstance(n, ast.Attribute) and n.attr == "signature_matches"
        for n in ast.walk(_sig_fn)
    ),
)

_import_fn = _fn(os.path.join(ADDON, "__init__.py"), "import_pdf_file")
_import_calls = {
    ast.unparse(n.func) if hasattr(ast, "unparse") else ""
    for n in ast.walk(_import_fn)
    if isinstance(n, ast.Call)
} if _import_fn else set()
check("import_pdf_file exists to pin", _import_fn is not None)
check(
    "the ONE import funnel starts the index — hooking here is what "
    "makes every import surface behave the same",
    "index_queue.on_pdf_imported" in _import_calls,
)

_setup_fn = _fn(os.path.join(ADDON, "index_queue.py"), "setup")
_setup_code = (
    "\n".join(ast.unparse(n) for n in _setup_fn.body) if _setup_fn else ""
)
check(
    "the runner's ONE hook is profile teardown — everything else about "
    "it is demand-driven, so there is nothing else to register",
    "profile_will_close.append(_on_profile_close)" in _setup_code,
)
check(
    "...and the package actually calls setup(), or the teardown would "
    "never run and a job would outlive its collection",
    "_index_queue.setup()" in _init_src,
)
check(
    "the status bar and the Library render the SAME text through the "
    "same function — the dock has no wording of its own",
    _iq_src.count("status_line(snapshot)") >= 1
    and "dock_button_label(snapshot)" in _iq_src,
)

_after_matches_fn = _fn(os.path.join(ADDON, "index_queue.py"), "after_matches")
_after_matches_calls = {
    ast.unparse(n.func) if hasattr(ast, "unparse") else ""
    for n in ast.walk(_after_matches_fn)
    if isinstance(n, ast.Call)
} if _after_matches_fn else set()
check("after_matches exists to pin", _after_matches_fn is not None)
check(
    "phase four (pertinence) runs from INSIDE phase three's own "
    "completion handler — the judge pass must see the freshly matched set",
    "pertinence.ensure_judged" in _after_matches_calls,
)

_after_judged_fn = _fn(os.path.join(ADDON, "index_queue.py"), "after_judged")
_after_judged_calls = {
    ast.unparse(n.func) if hasattr(ast, "unparse") else ""
    for n in ast.walk(_after_judged_fn)
    if isinstance(n, ast.Call)
} if _after_judged_fn else set()
check("after_judged exists to pin", _after_judged_fn is not None)

_run_fn = _fn(os.path.join(ADDON, "index_queue.py"), "_run")
check(
    "fix round 1, I2 — _run's OWN docstring names the new phase too, not "
    "just the module docstring's chain",
    _run_fn is not None and "pertinence.ensure_judged" in (ast.get_docstring(_run_fn) or ""),
)
check(
    "...and the tag write happens from inside the JUDGE phase's own "
    "completion handler, never straight from after_matches — the tag "
    "write must see whatever the judge pass actually rejected, not run "
    "concurrently with it",
    "tag_sync.sync_after_matches" in _after_judged_calls
    and "tag_sync.sync_after_matches" not in _after_matches_calls,
)

raise SystemExit(report())
