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
msg = iq.sweep_message(2, 30000, "nomic-embed-text")
check("local sweep names model and amount of work", "nomic-embed-text" in msg and "30,000 notes" in msg and "2 PDFs" in msg)
check("one note and PDF use singular labels", "1 note and 1 PDF will" in iq.sweep_message(1, 1, "m"))
check("local sweep describes time and cancellation", "locally" in msg and "stop it" in msg and "$" not in msg)
check("declining sweep explains later confirmation", "If you decline" in msg and "with confirmation" in msg)
check(
    "the add tooltip distinguishes running from queued",
    iq.queued_message("A", 0).startswith("KlausMate: indexing")
    and "3 ahead of it" in iq.queued_message("A", 3),
)
section("the status bar's index task (status bar 4/6)")
_tasks = importlib.import_module("klausmate.tasks")
_tasks.run_on_main = lambda fn: fn()
_tasks.clear()
iq._report_task(iq.RunnerState(active=True, name="Anemia", label="Embedding PDF…", done=3, total=10))
_t = [t for t in _tasks.snapshot() if t.key == "index"]
check("a running job is ONE cancellable index task with its progress",
      len(_t) == 1 and _t[0].done == 3 and _t[0].total == 10 and _t[0].cancellable
      and _t[0].label == iq.status_line(iq.RunnerState(active=True, name="Anemia", label="Embedding PDF…", done=3, total=10)),
      str(_t))
_stopped = []
_real_cancel_all = iq.cancel_all
iq.cancel_all = lambda: _stopped.append(1)
_tasks.clear()
iq._report_task(iq.RunnerState(active=True, name="Anemia", label="Embedding PDF…", done=4, total=10))
_tasks.cancel("index")
iq.cancel_all = _real_cancel_all
check("its ✕ stops the runner", _stopped == [1], str(_stopped))
iq._report_task(iq.RunnerState(message="Anemia indexed"))
_t = [t for t in _tasks.snapshot() if t.key == "index"]
check("a finished run leaves its message", len(_t) == 1 and _t[0].message == "Anemia indexed", str(_t))
_tasks.clear()
iq._report_task(iq.RunnerState(message=iq.BUSY_WAIT_TEXT))
check("a message with nothing running still reaches the bar",
      [t.message for t in _tasks.snapshot() if t.key == "index"] == [iq.BUSY_WAIT_TEXT], str(_tasks.snapshot()))
_tasks.clear()


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
        self._tag_raises = None
        self._busy = False  # curation's shared re-entrancy token
        # K-237: card_index_from_scratch's whole read. Defaults to a FRESH,
        # matching manifest (the current index_signature() for a bare
        # {"api_key_openai": "sk"} cfg) so every pre-existing test above —
        # none of which knows this gate exists — keeps calling ensure_index
        # straight through, with no confirm in the way.
        self._index_stats = {
            "exists": True,
            "provider": "ollama",
            "model": "nomic-embed-text",
            "dims": 0,
        }

    # -- curation ------------------------------------------------------
    def ensure_index(self, _parent, *, on_progress=None, on_done=None, on_error=None, cancel=None):
        self.calls.append(("ensure_index", ""))
        self.cancels.append(cancel)
        self.pending["cards"] = (on_done, on_error, on_progress)

    def index_stats(self):
        return dict(self._index_stats)

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
        if self._tag_raises is not None:
            raise self._tag_raises
    # -- drivers -------------------------------------------------------
    def finish_cards(self, completed=True):
        self.pending.pop("cards")[0](FakeIndex(), completed)

    def finish_pdf(self, complete=True):
        self.pending.pop("pdf")[0](FakeIndex(complete))

    def finish_matches(self, matches=((1, 0.9),)):
        self.pending.pop("matches")[0](list(matches))

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
    iq._dock = None
    return tmp, pipe


def run_one(pipe, name):
    """Drive one PDF job to completion."""
    pipe.finish_cards()
    pipe.finish_pdf()
    pipe.finish_matches()


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
check("phase 4 writes the PDF's !Library tag", pipe.calls[-1] == ("tag_sync", "a"))
check(
    "the whole chain, in order, once",
    [c[0] for c in pipe.calls]
    == ["ensure_index", "ensure_pdf_index", "ensure_matches", "tag_sync"],
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
iq._on_profile_close()
check(
    "a profile close stops everything — the phases read the collection "
    "and write into user_files, and both are about to go away",
    iq._queue.pending() == 0 and iq._current is None,
)


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

tmp, pipe = new_world(cfg={})
check("local indexing requires no API key", iq.request_pdf("a", announce=False) is True)
FakeTimer.drain()
check("keyless local job runs", bool(pipe.calls))

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
            '"provider": "ollama", "model": "nomic-embed-text", "dims": 1024}'
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
# --- :943 — the sweep confirm's Yes branch passes announce=False ------------
# K-166 review: this site is NOT Qt-widget-only, which is why it survived on
# a false premise. The user has just answered a PRICED dialog; announcing the
# same queue again talks over the answer they just gave. iq.QMessageBox is a
# constructible stub and offer_model_sweep already reaches
# `box.finished.connect(answered)`, so a fake box that reports a Yes click is
# the whole seam: pristine the accepted sweep tooltips nothing, flipped to
# announce=True it tooltips once.
class _FakeSignal:
    def __init__(self):
        self.cbs = []

    def connect(self, cb):
        self.cbs.append(cb)


_RealBox = iq.QMessageBox


class _YesBox:
    """Just enough QMessageBox for offer_model_sweep, answering Yes."""

    last = None
    Icon = _RealBox.Icon
    StandardButton = _RealBox.StandardButton

    def __init__(self, _parent=None):
        self.finished = _FakeSignal()
        _YesBox.last = self

    def clickedButton(self):
        return "the-yes-button"

    def standardButton(self, _b):
        return _YesBox.StandardButton.Yes

    def button(self, _b):
        return None

    def __getattr__(self, _name):          # setText/setIcon/open/deleteLater…
        return lambda *_a, **_k: None


iq.QMessageBox = _YesBox
_sweep_tips: list = []                      # self-contained: _tips() is defined further down
_sweep_orig_tooltip = iq.tooltip
iq.tooltip = lambda text="", **_k: _sweep_tips.append(text)
_sweep_asked = iq.offer_model_sweep(None, embeddings.index_signature({}))
_pending_before = iq._queue.pending()
for _cb in (_YesBox.last.finished.cbs if _YesBox.last else []):
    _cb(0)
_pending_after = iq._queue.pending()
iq.QMessageBox = _RealBox
iq.tooltip = _sweep_orig_tooltip
check(
    "accepting the priced sweep queues the jobs but tooltips NOTHING — the "
    "user just answered the dialog, so announce=False is the whole point of "
    "that call, and announcing over their answer is the regression",
    _sweep_asked is True and _pending_after > _pending_before and _sweep_tips == [],
    f"asked={_sweep_asked} pending {_pending_before}->{_pending_after} tips={_sweep_tips!r}",
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


section("local sweep avoids paid estimates")
tmp, pipe = new_world(names=("a",))
check("unchanged model offers no sweep", iq.offer_model_sweep(None, embeddings.index_signature(iq._cfg())) is False)
check("changed local model offers sweep", iq.offer_model_sweep(None, ("ollama", "previous", 0)) is True)

# ----------------------------------------------------- K-237: the card-index
# ------------------------------------------------------------ confirm gate
#
# offer_model_sweep's own confirm has no teeth: declining it leaves the card
# index stale, and the VERY NEXT PDF add runs curation.ensure_index as phase
# one of this same chain — which has no price gate of its own, so a stale
# or missing index makes that a from-scratch re-embed of the whole
# collection, silently. These pins drive that phase-one call site with a
# fake QMessageBox (the sweep tests' own pattern) so the confirm can be
# answered without real Qt.

section("K-237: the card-index confirm")

_RealBox2 = iq.QMessageBox


class _ConfirmBox:
    """Stands in for QMessageBox wherever ask_card_index_confirm builds
    one: records the two buttons `addButton` mints and lets the test fire
    `finished` as though a specific one were clicked — the shape
    `ask_card_index_confirm` uses (Embed/Skip),
    never a bare Yes/No."""

    Icon = _RealBox2.Icon
    ButtonRole = _RealBox2.ButtonRole
    last = None

    def __init__(self, _parent=None):
        self.finished = _FakeSignal()
        self.buttons = {}
        self.clicked = None
        _ConfirmBox.last = self

    def addButton(self, text, _role):
        btn = object()
        self.buttons[text] = btn
        return btn

    def clickedButton(self):
        return self.clicked

    def click(self, text):
        self.clicked = self.buttons[text]
        for cb in list(self.finished.cbs):
            cb(0)

    def __getattr__(self, _name):  # setWindowTitle/setIcon/setText/…
        return lambda *_a, **_k: None


def _install_confirm_box():
    iq.QMessageBox = _ConfirmBox
    _ConfirmBox.last = None


def _restore_confirm_box():
    iq.QMessageBox = _RealBox2


# -- the gate detection itself, in isolation --------------------------------

tmp, pipe = new_world()
check(
    "a fresh, signature-matching manifest is not a from-scratch embed",
    iq.card_index_from_scratch(iq._cfg()) is False,
)
pipe._index_stats = {"exists": False, "provider": "", "model": "", "dims": 0}
check(
    "no manifest on disk at all IS one",
    iq.card_index_from_scratch(iq._cfg()) is True,
)
pipe._index_stats = {"exists": True, "provider": "voyage", "model": "voyage-3-lite", "dims": 0}
check(
    "a manifest under the OLD provider/model is one too — the same "
    "signature comparison offer_model_sweep's own trigger uses, not a "
    "hand-spelled tuple check",
    iq.card_index_from_scratch(iq._cfg()) is True,
)

# -- wired into phase one: the RED case this card exists to fix -------------

tmp, pipe = new_world()
pipe._index_stats = {"exists": False, "provider": "", "model": "", "dims": 0}
_install_confirm_box()
iq.request_pdf("a", announce=False)
FakeTimer.drain()
check(
    "a from-scratch card index asks BEFORE curation.ensure_index ever "
    "runs — the confirm this card adds, where before there was none",
    pipe.calls == [] and _ConfirmBox.last is not None,
    f"calls={pipe.calls!r} box={_ConfirmBox.last!r}",
)
_ConfirmBox.last.click("Skip")
check(
    "declining never calls ensure_index — the whole point of the gate: a "
    "silent PDF add must not spend money nobody was asked about",
    ("ensure_index", "") not in pipe.calls,
    repr(pipe.calls),
)
check(
    "...but the rest of the chain still runs, degraded rather than "
    "aborted: a declined phase does not "
    "crash or hang the PDF add, the phases after it still see whatever "
    "data already exists",
    pipe.calls == [("ensure_pdf_index", "a")],
    repr(pipe.calls),
)
pipe.finish_pdf()
pipe.finish_matches()
check(
    "...through to completion, PDF tagged and all",
    pipe.calls[-1] == ("tag_sync", "a") and iq.state().finished == "a",
    repr(pipe.calls),
)
_restore_confirm_box()

# -- accepting the confirm really does embed --------------------------------

tmp, pipe = new_world()
pipe._index_stats = {"exists": False, "provider": "", "model": "", "dims": 0}
_install_confirm_box()
iq.request_pdf("a", announce=False)
FakeTimer.drain()
_ConfirmBox.last.click("Embed")
check(
    "accepting DOES call ensure_index, exactly as the old unconfirmed "
    "path used to",
    pipe.calls == [("ensure_index", "")],
    repr(pipe.calls),
)
run_one(pipe, "a")
check("...and the chain completes normally", pipe.calls[-1] == ("tag_sync", "a"))
_restore_confirm_box()

# -- a plain card-index sweep job never double-confirms ----------------------

tmp, pipe = new_world()
pipe._index_stats = {"exists": False, "provider": "", "model": "", "dims": 0}
_install_confirm_box()
iq.request([(iq.JOB_CARDS, "")], announce=False)
FakeTimer.drain()
check(
    "a bare JOB_CARDS entry (offer_model_sweep's OWN priced confirm "
    "already asked, in Preferences, before this ever reaches the queue) "
    "is never asked a SECOND time here — only a PDF's own silent phase "
    "one is gated",
    pipe.calls == [("ensure_index", "")] and _ConfirmBox.last is None,
    f"calls={pipe.calls!r} box={_ConfirmBox.last!r}",
)
_restore_confirm_box()

check(
    "the phrase this card's verify grep looks for actually names the "
    "confirm's own purpose in the source, not just satisfies the grep "
    "by accident",
    "card-index confirm" in open(os.path.join(ADDON, "index_queue.py")).read(),
)


# ------------------------------------------------- K-166: the boolean edges

section("K-166: the boolean edges the vacuity audit found")
# scripts/mutation_audit.py --modules index_queue flips one boolean literal at
# a time and re-runs this file. Eight sites flipped with nothing noticing,
# every one of them an edge with a documented intent. Each pin below is
# BEHAVIOURAL on purpose: never `iq.request.__defaults__`, never a message
# compared against the constant that produced it (AUDIT.md's "one source of
# truth, read twice"), always the thing a user would see — a tooltip that
# fired or did not, a chain that started or parked, status_line/
# dock_button_label off the published snapshot.


class _Tips:
    """Records what index_queue actually tooltipped. `tooltip` is a module
    global there (the aqt import, or its own headless fallback), so this is
    the one seam that makes "nothing is ever started silently" observable."""

    def __init__(self):
        self.seen = []

    def __call__(self, text="", **_k):
        self.seen.append(text)


def _tips():
    tips = _Tips()
    iq.tooltip = tips
    return tips


_orig_tooltip = iq.tooltip

# --- :386 / :424 — the `announce: bool = True` defaults ---------------------
# The module docstring's own invariant: nothing is ever started silently.
# Every OTHER call in this file passes announce=False, which is exactly why
# both defaults used to flip undetected; these three calls are bare.
tmp, pipe = new_world()
tips = _tips()
_added = iq.request([(iq.JOB_PDF, "a")])
check(
    "request(jobs) with no announce= tooltips the add — the default is True, "
    "and a queued job the user never hears about is the bug the docstring's "
    "'nothing is ever started silently' forbids",
    _added == 1 and len(tips.seen) == 1 and "a" in tips.seen[0],
    repr(tips.seen),
)

tmp, pipe = new_world()
tips = _tips()
check("request_pdf(name) bare queues it", iq.request_pdf("a") is True)
check(
    "...and tooltips too: the Library's Update/Add to Search Index announces "
    "by default, so request_pdf's own default must be True as well",
    len(tips.seen) == 1 and "a" in tips.seen[0],
    repr(tips.seen),
)

tmp, pipe = new_world()
tips = _tips()
check("on_pdf_imported — the funnel EVERY import surface returns through — "
      "calls request_pdf bare, so a silent import is a silent index",
      iq.on_pdf_imported("a") is True and len(tips.seen) == 1, repr(tips.seen))

tmp, pipe = new_world()
tips = _tips()
iq.request_pdf("a", announce=False)
check("...and announce=False is still silent, so the pins above are about the "
      "DEFAULT and not about announcing at all", tips.seen == [], repr(tips.seen))

tmp, pipe = new_world(cfg={})
tips = _tips()
for name in ("a", "b", "c"):
    iq.request_pdf(name, announce=False)
check("keyless local jobs do not show key warnings", tips.seen == [])

iq.tooltip = _orig_tooltip


# --- :499 — `_busy_elsewhere`'s except arm returns False --------------------
class _Proxy:
    """A stand-in module whose ONE named attribute raises; everything else
    is the real object behind it. The shape each except arm below exists
    for — a deferred import or a callee that blows up mid-bookkeeping."""

    def __init__(self, inner, boom, exc):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_boom", boom)
        object.__setattr__(self, "_exc", exc)

    def __getattr__(self, name):
        if name == object.__getattribute__(self, "_boom"):
            raise object.__getattribute__(self, "_exc")
        return getattr(object.__getattribute__(self, "_inner"), name)


def _swap(dotted, obj):
    pkg = sys.modules["klausmate"]
    short = dotted.split(".")[1]
    prev = sys.modules.get(dotted), getattr(pkg, short, None)
    sys.modules[dotted] = obj
    setattr(pkg, short, obj)
    return dotted, short, prev


def _unswap(saved):
    dotted, short, (mod, attr) = saved
    pkg = sys.modules["klausmate"]
    if mod is not None:
        sys.modules[dotted] = mod
    setattr(pkg, short, attr)


tmp, pipe = new_world()
_saved = _swap("klausmate.curation", _Proxy(pipe, "_busy", RuntimeError("token unreadable")))
iq.request_pdf("a", announce=False)
FakeTimer.drain(limit=1)
_unswap(_saved)
check(
    "a curation._busy read that RAISES reads as 'not busy' and the job "
    "RUNS — fail-closed here would park every future job behind a token "
    "nobody can prove is free, and the queue would look wedged for the "
    "session",
    pipe.calls == [("ensure_index", "")] and iq.state().message != iq.BUSY_WAIT_TEXT,
    f"{pipe.calls!r} / {iq.state().message!r}",
)

# --- :513 — `_pdf_present`'s except arm returns True ------------------------
tmp, pipe = new_world()
pdf_index_mod = importlib.import_module("klausmate.pdf_index")
_saved = _swap("klausmate.pdf_index",
               _Proxy(pdf_index_mod, "source_signature", OSError("disk hiccup")))
iq.request_pdf("a", announce=False)
FakeTimer.drain(limit=1)
_unswap(_saved)
check(
    "a presence check that RAISES still runs the job — never lose a job to "
    "a bookkeeping hiccup; the other polarity would silently DROP a PDF the "
    "user asked to index and say nothing at all",
    pipe.calls == [("ensure_index", "")],
    repr(pipe.calls),
)

# --- :842 — `signature_changed`'s except arm returns False ------------------
tmp, pipe = new_world()
_emb = iq.embeddings


class _RaisingEmbeddings:
    signature_matches = staticmethod(
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("signature unreadable")))


iq.embeddings = _RaisingEmbeddings()
_raised = iq.signature_changed(("openai", "m", 1024), ("openai", "m2", 1024))
iq.embeddings = _emb
check(
    "signature_matches raising reads as 'nothing moved' — this gate's whole "
    "docstring is about not re-embedding the collection on a paid API "
    "silently, so a bookkeeping error must never be allowed to answer 'yes, "
    "everything is stale'",
    _raised is False,
    repr(_raised),
)
check(
    "...and a malformed `previous` (None, or too short to index) is the same "
    "answer, not a TypeError escaping into Preferences' Save",
    iq.signature_changed(None, ("openai", "m", 1024)) is False
    and iq.signature_changed((), ("openai", "m", 1024)) is False,
)

# --- :534 / :541 — the two `active=False` publishes in _pump ----------------
# status_line and dock_button_label both branch on `active`, so a flip puts a
# live progress line and a Stop button on the bar while NOTHING is running.
tmp, pipe = new_world()
pipe._busy = True  # Preferences' Index Now holds the token
iq.request_pdf("a", announce=False)
FakeTimer.drain(limit=1)
check(
    "while WAITING for the token the bar reads the waiting message and "
    "offers Dismiss — published active=False, because nothing of ours is "
    "running; active=True would render a progress head ('Card index') and a "
    "Stop button for a job that has not started",
    iq.status_line(iq.state()) == iq.BUSY_WAIT_TEXT
    and not iq.state().active,
    f"{iq.status_line(iq.state())!r} / {iq.state().active!r}",
)

for _ in range(iq.BUSY_WAIT_POLLS + 2):
    FakeTimer.drain(limit=1)
_gave_up = iq.status_line(iq.state())
check(
    "and when it GIVES UP polling the bar still reads its own sentence with "
    "a Dismiss button — the work is kept, but there is no run to Stop",
    "Another indexing run is still going" in _gave_up
    and "still waiting" in _gave_up
    and not iq.state().active,
    f"{_gave_up!r} / {iq.state().active!r}",
)
pipe._busy = False


section("tag sync errors release the runner")
tmp, pipe = new_world()
pipe._tag_raises = RuntimeError("simulated tag write failure")
iq.request_pdf("a", announce=False)
FakeTimer.drain()
run_one(pipe, "a")
check("a failed tag write still clears the completed job",
      pipe.calls[-1] == ("tag_sync", "a")
      and iq._current is None and iq.state().finished == "a")
FakeTimer.drain()
check("the runner returns to idle after a tag failure", not iq.state().active)

# ------------------------------------------------------------- source pins

section("one chain, one copy")

_iq_raw = open(os.path.join(ADDON, "index_queue.py")).read()  # docstrings are STRING tokens — code_only strips them
_iq_src = code_only(_iq_raw)
_drive_src = code_only(open(os.path.join(ADDON, "pdf_drive.py")).read())
_sidebar_src = code_only(open(os.path.join(ADDON, "library_sidebar.py")).read())
_init_src = code_only(open(os.path.join(ADDON, "__init__.py")).read())

check(
    "the priced confirm defaults to No — Save's own button is already "
    "Enter-default, so Enter in the key field reaches this window-modal "
    "confirm next with keyboard focus; a stray Enter must not start a "
    "paid whole-collection re-embed, the same rule "
    "the Library confirmation follows",
    "box.setDefaultButton(QMessageBox.StandardButton.No)" in _iq_src,
)
check(
    "index_queue holds the ONLY copy of the chain",
    _iq_src.count("curation.ensure_index(") == 1
    and _iq_src.count("retention.ensure_pdf_index(") == 1
    and _iq_src.count("retention.ensure_matches(") == 1,
)
check(
    "the Library no longer spells the chain itself — a second copy is "
    "the K-143 two-renderer failure with a different subject",
    "ensure_pdf_index(" not in _drive_src
    and "ensure_matches(" not in _drive_src
    and "curation.ensure_index(" not in _drive_src,
)
check(
    "the sidebar no longer draws or stops indexing: the status bar does "
    "(closing Browse can never cancel a run)",
    "cancel_all" not in _sidebar_src and "status_line(" not in _sidebar_src,
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
    "the status bar's index task reads the runner's own status_line, and "
    "the old dock is gone",
    "status_line(state)" in _iq_src
    and "_StatusDock" not in _iq_src and "dock_button_label" not in _iq_src
    and "_render_dock" not in _iq_src,
)

_after_matches_fn = _fn(os.path.join(ADDON, "index_queue.py"), "after_matches")
_after_matches_calls = {
    ast.unparse(n.func) if hasattr(ast, "unparse") else ""
    for n in ast.walk(_after_matches_fn)
    if isinstance(n, ast.Call)
} if _after_matches_fn else set()
check("after_matches exists to pin", _after_matches_fn is not None)
check("matching completion writes the lecture tag",
      "tag_sync.sync_after_matches" in _after_matches_calls)

raise SystemExit(report())
