"""The INDEX RUNNER — one queue, one chain, every surface (K-152).

Indexing IS the pipeline. It embeds the PDF, refreshes the CARD index,
scores every note against the PDF, writes the per-PDF ``!Library`` tag,
and thereby feeds retention, the lecture view and the map. K-146 removed
the Curate ceremony that used to wrap it; K-152 removes the last manual
step — adding a PDF starts it, and changing the embedding model restarts
it for everything.

**Why this module exists at all: the chain had no home.** It lived as
``DriveWindow._on_embed``, a METHOD, leaning on that window's ``busy``
flag, status label, ``_on_progress`` and Cancel button. A PDF dropped on
the deck screen has no Library window, so none of that is reachable from
where most PDFs now arrive. So the phase chain moved here whole —
``curation.ensure_index`` → ``retention.ensure_pdf_index`` →
``retention.ensure_matches`` → ``pertinence.ensure_judged`` →
``tag_sync.sync_after_matches``, with the
cancel token threaded through exactly as K-146 left it — and the Library
became one more CALLER. There is exactly one copy of that sequence in
the addon; a second one would drift (K-143's two-renderer lesson).

**Each phase still takes ``curation._busy`` in turn** rather than one
held token across the run — with ONE exception: phase four
(``pertinence.ensure_judged``) never touches it at all (K-255's review,
finding I1). That is K-146's finding, not an oversight: the
cancellation branches return without releasing, so a caller-held token
would leak and brick indexing for the rest of the session.
Serialisation across jobs is the queue below, not the token. Phase
four's own wait — the Judge/Skip dialog, then however long the
Anthropic batches take — runs at the user's own pace and can sit open
for minutes; holding the token across an interactive dialog is exactly
the shape of leak the previous sentence warns about, so it is left
free for that stretch instead. The one visible consequence: Preferences'
**Index Now** can start a concurrent card-index embed where every other
phase would have refused it — different files, different resources, no
data corruption, just a documented gap in the "each phase takes it in
turn" rule above.

**A queue, not a race.** Ten dropped PDFs are ten legitimate requests.
``curation._busy`` REFUSES a concurrent run — correct for a user
double-clicking a button, wrong for a batch — so jobs are serialised
here and the token is never contended by us. Duplicates collapse
(dropping the same PDF twice queues it once), and a PDF deleted before
its turn is dropped silently, checked at start time rather than trusting
a delete path to call us.

**Feedback is the shippable part.** Embedding is a paid cloud call by
default and a model sweep is minutes of work, so a job must be visible
and stoppable from wherever it was started. The Library has a status
line and a Cancel button; the deck screen has neither, and a toast is
not a progress display. So the runner publishes ONE ``RunnerState`` to
every listener, rendered by ONE pure ``status_line()``: the Library
paints it into its own status line, and ``_StatusDock`` — a thin
bottom-docked bar on the main window, the ``lecture_view`` dock's
pattern, visible on the deck screen, the overview and mid-review alike —
paints it with a Stop button for everyone else. Same text, same Stop,
two surfaces. Nothing is ever started silently: a single add tooltips
and shows the bar, and a whole-library sweep asks first, in notes and
PDFs, before spending anything.

**Gates.** No profile, no run (``mw.col`` is None until one opens). No
API key for a cloud provider, no run — an auto-index that fails silently
on every drop would be worse than the button it replaces, so the refusal
is a message, not a shrug. And a cancelled or failed job leaves nothing
that later reads as complete: the phases persist partial work as
explicitly partial (``card_index`` writes its manifest after its
vectors, ``pdf_index.is_fresh`` is False while ``embedded_rows`` trails
``chunks``, ``ensure_matches`` refuses to cache a cancelled pass), and
the tag write is on the completion path only.

Pure above the divider — the queue, the config gates, the sweep plan and
every string the user reads — so ``tests/test_index_queue.py`` can drive
the whole policy without Qt.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable, NamedTuple

from . import embeddings

# A job is a plain ``(kind, name)`` tuple; name is "" for JOB_CARDS.
JOB_CARDS = "cards"  # refresh the card index alone (a sweep with no PDFs)
JOB_PDF = "pdf"  # the full chain for one PDF

CONFIG_KEY = "auto_index_on_add"


# ── pure: config gates ───────────────────────────────────────────────────


def _truthy(value: Any) -> bool:
    """Config booleans, tolerant of the strings a hand-edited meta.json
    can hold. Only an explicitly false-ish value is False."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def auto_index_enabled(cfg: dict) -> bool:
    """Auto-index-on-add, default ON — and a corrupt value reads ON too.

    The opposite of ``background.design_enabled``'s rule, on purpose. A
    bad value there would restyle the whole app unasked; here the worst
    case is one job the user just asked for by adding a PDF, announced
    on the status bar and stoppable from it. Reading a corrupt value as
    OFF would instead delete the feature with no message at all, which
    is the failure this card exists to remove.
    """
    if not isinstance(cfg, dict) or CONFIG_KEY not in cfg:
        return True
    return _truthy(cfg.get(CONFIG_KEY))


def missing_key_provider(cfg: dict) -> str:
    """The cloud provider whose API key is missing, or "" when ready.

    The PURE half of ``setup_flow._embedding_ready`` — it checks only
    what is free to check, a key is a string in config, so ten dropped
    PDFs cost nothing on the main thread. Since 2026-09-15 (K-226) there
    is exactly one embedding provider, so the name it returns is a
    constant rather than a per-provider lookup.
    """
    if not isinstance(cfg, dict):
        return ""
    return "" if str(cfg.get("api_key_openai") or "").strip() else "OpenAI"


# ── pure: the queue ──────────────────────────────────────────────────────


class JobQueue:
    """FIFO of ``(kind, name)`` jobs that collapses duplicates.

    Deliberately not a ``set``: order is the user's order, and the first
    PDF dropped should be the first one indexed.
    """

    def __init__(self) -> None:
        self._items: list[tuple[str, str]] = []

    def enqueue(self, job: tuple[str, str]) -> bool:
        """True when the job was added; False when already waiting."""
        if job in self._items:
            return False
        self._items.append(job)
        return True

    def pop(self) -> tuple[str, str] | None:
        return self._items.pop(0) if self._items else None

    def requeue(self, job: tuple[str, str]) -> None:
        """Put a popped job back at the FRONT — it lost its turn to a
        contended token, not to the jobs behind it."""
        if job not in self._items:
            self._items.insert(0, job)

    def drop(self, name: str) -> int:
        """Forget every queued job for one PDF; returns how many went."""
        before = len(self._items)
        self._items = [
            j for j in self._items if not (j[0] == JOB_PDF and j[1] == name)
        ]
        return before - len(self._items)

    def clear(self) -> int:
        count = len(self._items)
        self._items = []
        return count

    def pending(self) -> int:
        return len(self._items)

    def snapshot(self) -> list[tuple[str, str]]:
        return list(self._items)


def sweep_jobs(pdf_names: list[str]) -> list[tuple[str, str]]:
    """The model-change plan: the card index, then every indexed PDF.

    ``JOB_CARDS`` leads even though every PDF job re-runs
    ``curation.ensure_index`` as its own first phase — that phase is a
    no-op once the index is current, and leading with it means a
    collection with no PDFs at all still gets its cards re-embedded.
    """
    return [(JOB_CARDS, "")] + [(JOB_PDF, n) for n in pdf_names]


# ── pure: everything the user reads ──────────────────────────────────────


class RunnerState(NamedTuple):
    """One snapshot, published to every listener. The Library and the
    status dock render THIS, through ``status_line`` below, so the two
    surfaces cannot describe the same job differently."""

    active: bool = False
    kind: str = ""
    name: str = ""  # display label of the running job
    label: str = ""  # phase label from the pipeline ("Embedding PDF…")
    phase: str = ""  # "" for the K-146 chain phases; "judge" for pertinence
    done: int = 0
    total: int = 0
    pending: int = 0  # jobs still waiting behind this one
    message: str = ""  # terminal text: finished / cancelled / refused
    finished: str = ""  # safe name of the PDF that just completed


def status_line(state: RunnerState) -> str:
    """The ONE progress sentence. Idle states read as their message."""
    if not state.active:
        return state.message
    head = state.name or "Card index"
    if state.label:
        head = f"{head} — {state.label}"
    if state.total:
        # The judge phase counts cards, not percent complete — "judging
        # 12/40" says something a rounded percentage would flatten (how
        # much work, not just how far along).
        progress = f"{state.done}/{state.total}" if state.phase == "judge" else f"{round(state.done * 100 / state.total)}%"
        head = f"{head} {progress}"
    if state.pending:
        head = f"{head}  ·  {state.pending} more queued"
    return head


def dock_button_label(snapshot: RunnerState) -> str:
    """The status bar carries ONE button, because a bar with two is a
    toolbar: it stops the run while there is one, and clears the last
    result when there is not."""
    return "Stop" if snapshot.active else "Dismiss"


def sweep_message(n_pdfs: int, n_notes: int, model: str, estimate: str) -> str:
    """The confirm text for a model change. Never start a sweep without
    saying how much work it is AND what it costs: a changed model
    invalidates every stored vector, so this is a from-scratch re-embed
    of the whole collection, billed per token to the user's own OpenAI
    key. ``estimate`` is cost.format_estimate's own string, carried
    verbatim — this module never formats money itself."""
    pdfs = "1 PDF" if n_pdfs == 1 else f"{n_pdfs:,} PDFs"
    notes = "1 note" if n_notes == 1 else f"{n_notes:,} notes"
    price = f"{estimate}, billed to your OpenAI key.\n\n"
    return (
        f"Re-index everything with {model}?\n\n"
        f"{notes} and {pdfs} will be embedded again from scratch — "
        f"{price}"
        # Declining does NOT prevent the spend this priced: the next PDF
        # add runs curation.ensure_index as phase one and embeds every
        # note from scratch, unpriced and unconfirmed. Before the
        # API-first turn that path was free (a local engine); now it
        # bills the same key this dialog just asked about, so "No" has
        # to say what it really means. K-237 is the queue-side confirm
        # that would let it mean "and free".
        "If you decline, the card index is still rebuilt — unpriced — "
        "the first time a PDF is indexed.\n\n"
        "You can stop it at any time from the bar at the bottom of the "
        "main window."
    )


def card_index_confirm_message(pdf_label: str, estimate: str) -> str:
    """K-237: the card-index confirm's own text — the gate ``sweep_message``
    above says does not exist yet. Declining ``offer_model_sweep`` does not
    prevent the spend it warned about, only delays it: the very next PDF
    add still runs ``curation.ensure_index`` as phase one, and a stale or
    missing card index makes THAT a from-scratch re-embed of every note,
    unpriced. This is the confirm that closes that gap."""
    price = f"{estimate}, billed to your OpenAI key.\n\n"
    return (
        f"Indexing “{pdf_label}” needs to rebuild your whole card index "
        f"from scratch first — {price}"
        "Skip to add this PDF anyway: matching against your cards stays "
        "degraded until the card index is rebuilt (Preferences' Index Now, "
        "or the next model sweep, will finish it)."
    )


def queued_message(name: str, ahead: int) -> str:
    """The tooltip an add gets. ``ahead`` is how many jobs run BEFORE
    this one — the part of a ten-PDF drop the user cannot see, and the
    difference between "this is happening" and "this will happen"."""
    if ahead <= 0:
        return f"KlausMate: indexing “{name}”"
    return f"KlausMate: “{name}” queued for indexing — {ahead} ahead of it"


def missing_key_message(provider: str) -> str:
    return (
        f"KlausMate can't index yet — add your {provider} API key in "
        "KlausMate Preferences → API keys & models, or subscribe to "
        "Klaus Plus."
    )


# ── aqt glue ─────────────────────────────────────────────────────────────

try:
    from aqt import gui_hooks, mw
    from aqt.qt import (
        QDockWidget,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        Qt,
        QTimer,
        QWidget,
    )
    from aqt.utils import tooltip
except Exception:  # headless tests / partial environments
    gui_hooks = mw = None  # type: ignore[assignment]
    QDockWidget = QHBoxLayout = QLabel = QMessageBox = None  # type: ignore[assignment]
    QPushButton = Qt = QTimer = QWidget = None  # type: ignore[assignment]

    def tooltip(*_a: Any, **_k: Any) -> None:  # type: ignore[misc]
        pass


# ``class _StatusDock(None)`` is a hard TypeError at IMPORT time, which
# would take the whole runner down — queue, gates and all — on any
# environment whose Qt surface is partial. Only the dock needs Qt, so
# only the dock degrades: the base falls back to ``object`` and
# ``_ensure_dock`` gates on ``QDockWidget`` still being None.
_DockBase: Any = QDockWidget if QDockWidget is not None else object


_queue = JobQueue()
_current: tuple[str, str] | None = None
_cancel: Any = None
_seq = 0
_state = RunnerState()
_listeners: list[Callable[[RunnerState], None]] = []
_dock: Any = None
_hide_gen = 0
_key_warned = False
_waits = 0

IDLE_HIDE_MS = 8000
BUSY_RETRY_MS = 1500
BUSY_WAIT_POLLS = 40  # ~60s of waiting for Index Now before giving up
BUSY_WAIT_TEXT = "Waiting for the current indexing run to finish…"


def _user_files() -> str:
    from . import USER_FILES  # deferred: the package root imports aqt

    return USER_FILES


def _cfg() -> dict:
    try:
        return mw.addonManager.getConfig(__package__) or {}
    except Exception:
        return {}


# ── listeners + published state ──────────────────────────────────────────


def add_listener(fn: Callable[[RunnerState], None]) -> None:
    """Subscribe a surface. The Library subscribes for the life of its
    window; the dock is driven directly (it belongs to this module)."""
    if fn not in _listeners:
        _listeners.append(fn)


def remove_listener(fn: Callable[[RunnerState], None]) -> None:
    try:
        _listeners.remove(fn)
    except ValueError:
        pass


def state() -> RunnerState:
    return _state


def _publish(new: RunnerState) -> None:
    global _state
    _state = new
    try:
        _render_dock(new)
    except Exception as exc:
        print(f"[klausmate] index status dock failed: {exc}")
    for fn in list(_listeners):
        try:
            fn(new)
        except Exception as exc:
            print(f"[klausmate] index listener failed: {exc}")


# ── entry points ─────────────────────────────────────────────────────────


def request(jobs: list[tuple[str, str]], *, announce: bool = True) -> int:
    """Queue jobs and start pumping. Returns how many were newly queued.

    THE gate wall, in one place so no caller can skip half of it: no
    profile, no cloud key, nothing runs. Both refusals publish, so
    whichever surface is open says why instead of appearing to work.
    """
    global _key_warned, _waits
    if mw is None or getattr(mw, "col", None) is None:
        return 0  # nothing runs before the profile is open
    provider = missing_key_provider(_cfg())
    if provider:
        msg = missing_key_message(provider)
        _publish(RunnerState(message=msg))
        if not _key_warned:
            _key_warned = True  # ten drops must not stack ten tooltips
            tooltip(msg, period=6000)
        return 0
    added = 0
    for job in jobs:
        if job == _current:
            continue  # already running — re-queueing would re-embed it
        if _queue.enqueue(job):
            added += 1
    if not added:
        return 0
    _waits = 0  # a fresh request re-opens the wait-for-the-token window
    if _current is None:
        _pump_soon()
    else:
        _publish(_state._replace(pending=_queue.pending()))
    if announce:
        first = jobs[0][1] if jobs and jobs[0][0] == JOB_PDF else ""
        ahead = _queue.pending() - 1 + (1 if _current is not None else 0)
        tooltip(queued_message(display_name(first), ahead))
    return added


def request_pdf(name: str, *, announce: bool = True) -> bool:
    """Index one PDF. The Library's Update/Add to Search Index."""
    return request([(JOB_PDF, name)], announce=announce) > 0


def on_pdf_imported(name: str) -> bool:
    """``import_pdf_file``'s hook — the ONE funnel every import surface
    returns through, so this covers the Library tree drop, the Library's
    Browse…, the deck-screen square and the deck-screen file drop
    without any of them knowing about indexing."""
    if not name or not auto_index_enabled(_cfg()):
        return False
    return request_pdf(name)


def cancel_all() -> None:
    """Stop the running job and forget the queue.

    Bumping ``_seq`` is what makes this safe rather than merely
    requested: every continuation below checks it first, so the phase
    already in flight finishes into a discarded callback. That matters
    most at ``after_matches`` — ``ensure_matches`` hands back a PARTIAL
    ranking when cancelled (deliberately uncached), and tagging on it
    would silently shrink the PDF's ``!Library`` tag.
    """
    global _current, _seq, _waits
    if _cancel is not None:
        _cancel.set()
    _seq += 1
    _current = None
    _waits = 0
    dropped = _queue.clear()
    tail = f" {dropped} queued job(s) dropped." if dropped else ""
    _publish(
        RunnerState(
            message="Indexing cancelled — it resumes where it stopped." + tail
        )
    )


def forget(name: str) -> int:
    """Drop a deleted PDF's queued jobs. Belt to ``_pump``'s braces —
    that check is what actually guarantees a deleted PDF never runs."""
    return _queue.drop(name)


# ── the pump ─────────────────────────────────────────────────────────────


def _pump_soon(delay_ms: int = 0) -> None:
    """Always start the next job from a fresh event loop turn: an add
    arrives inside a drop event, and a chain of ten jobs must not run as
    ten nested callbacks."""
    try:
        QTimer.singleShot(delay_ms, _pump)
    except Exception:
        _pump()


def _busy_elsewhere() -> bool:
    """``curation._busy`` — the ONE re-entrancy token every embedding
    phase in the addon holds — taken by someone who is not this queue.

    There is exactly one other holder: Preferences' **Index Now**, which
    calls ``curation.ensure_index`` directly because it has its own
    progress bar and cancel button. Without this check, a PDF dropped
    while that button is running would start a job, be refused by the
    token, and take the whole queue down with it as a "failure" the user
    never caused. So we WAIT for the token instead of racing it.
    """
    try:
        from . import curation

        return bool(curation._busy)
    except Exception:
        return False


def _pdf_present(name: str) -> bool:
    """A PDF still has extractable text on disk. ``source_signature`` is
    the same reader ``ensure_pdf_index`` raises on, so agreeing with it
    here turns "deleted before its turn" into a silent skip instead of
    an error the user never caused."""
    try:
        from . import pdf_index

        return pdf_index.source_signature(_user_files(), name) is not None
    except Exception as exc:
        print(f"[klausmate] index queue presence check failed: {exc}")
        return True  # never lose a job to a bookkeeping hiccup


def _pump() -> None:
    global _current, _waits
    if _current is not None:
        return
    while True:
        job = _queue.pop()
        if job is None:
            # finished="" so a drained queue can't re-fire the Library's
            # "this PDF just landed, re-aggregate" branch a second time.
            _publish(_state._replace(active=False, pending=0, finished=""))
            return
        if job[0] == JOB_PDF and not _pdf_present(job[1]):
            continue  # deleted before its turn — dropped silently
        break
    if _busy_elsewhere():
        _queue.requeue(job)
        _waits += 1
        if _waits <= BUSY_WAIT_POLLS:
            _publish(_state._replace(active=False, label="", message=BUSY_WAIT_TEXT))
            _pump_soon(BUSY_RETRY_MS)
        else:
            # Give up POLLING, not the work: the queue is untouched, so
            # the next add — or the next job that finishes — picks it up.
            _publish(
                _state._replace(
                    active=False,
                    message=(
                        "Another indexing run is still going — "
                        f"{_queue.pending()} job(s) still waiting."
                    ),
                )
            )
        return
    _waits = 0
    _current = job
    try:
        _run(job)
    except Exception as exc:
        _fail(exc)


def display_name(name: str) -> str:
    if not name:
        return "Card index"
    try:
        from . import drive_store

        return drive_store.display_name(_user_files(), name) or name
    except Exception:
        return name


def _run(job: tuple[str, str]) -> None:
    """THE chain — the only copy in the addon.

    ``curation.ensure_index`` leads because it is the only thing that
    refreshes the CARD index, and everything that matches notes against
    a PDF reads it: skip it and every note written since the last pass
    is invisible to ``ensure_matches``, and the PDF's tag under-covers
    with no error at all (K-146's whole point). Five phases now, not
    four: ``pertinence.ensure_judged`` runs between ``ensure_matches``
    and the tag write (module docstring's chain; I1 in K-255's review
    is why it does not take ``curation._busy`` like the other three).
    """
    global _cancel, _seq
    from . import curation, pertinence, retention, tag_sync

    kind, name = job
    _seq += 1
    seq = _seq
    _cancel = threading.Event()
    cancel = _cancel
    label = display_name(name)

    def live() -> bool:
        return seq == _seq

    def prog(text: str, done: int, total: int) -> None:
        if not live():
            return
        _publish(
            _state._replace(
                label=text, done=done, total=total, pending=_queue.pending()
            )
        )

    def on_error(exc: Exception) -> None:
        if not live():
            return
        _fail(exc)

    def after_judged(rejected: set[int], matches: Any) -> None:
        if not live():
            return
        # The Doubtful read is guarded ON ITS OWN, the same shape
        # sync_after_threshold/sync_after_clear_overrides use: an auxiliary
        # failure there must never cost this PDF the lecture-tag write it
        # was indexed for. doubtful=None leaves the tag untouched.
        try:
            doubtful = tag_sync.doubtful_members(_cfg())
        except Exception as exc:
            print(f"[klausmate] doubtful set unavailable: {exc}")
            doubtful = None
        try:
            tag_sync.sync_after_matches(mw, name, matches, doubtful=doubtful)
        except Exception as exc:
            print(f"[klausmate] tag sync after index failed: {exc}")
        _job_done(f"Indexed “{label}”.", finished=name)

    def after_matches(matches: Any) -> None:
        if not live():
            return
        try:
            pertinence.ensure_judged(
                mw,
                name,
                matches,
                on_done=lambda rejected: after_judged(rejected, matches),
                on_error=on_error,
                cancel=cancel,
                on_progress=lambda text, d, t: _publish(_state._replace(phase="judge", label=text, done=d, total=t)) if live() else None,
                ask=ask_judge,
            )
        except Exception as exc:
            # Belt to pertinence's own defenses (fix round 1, C1): whatever
            # got past them must not skip the tag write or leave _current
            # set forever — every queued and future PDF would silently stop
            # indexing until Stop or a restart. Untagged pertinence beats a
            # wedged queue; the next index pass re-judges from scratch.
            print(f"[klausmate] pertinence phase failed, cards left unjudged: {type(exc).__name__}: {exc}")
            after_judged(set(), matches)

    def after_pdf_index(idx: Any) -> None:
        if not live():
            return
        if not idx.is_complete():
            # Reachable only if something set the shared cancel event
            # without going through cancel_all(). Kept because the
            # phases' contract is "partial, saved, resumable" and
            # continuing here would match cards against half a PDF and
            # then WRITE THAT as the PDF's tag.
            _job_stopped()
            return
        retention.ensure_matches(
            mw,
            name,
            on_progress=prog,
            on_done=after_matches,
            on_error=on_error,
            cancel=cancel,
        )

    def after_card_index(_index: Any, completed: bool) -> None:
        if not live():
            return
        if not completed:
            _job_stopped()
            return
        if kind == JOB_CARDS:
            _job_done("Card index up to date.")
            return
        retention.ensure_pdf_index(
            mw,
            name,
            on_progress=prog,
            on_done=after_pdf_index,
            on_error=on_error,
            cancel=cancel,
        )

    def start_card_index() -> None:
        curation.ensure_index(
            mw,
            on_progress=prog,
            on_done=after_card_index,
            on_error=on_error,
            cancel=cancel,
        )

    def card_index_answered(embed: bool) -> None:
        if not live():
            return
        if embed:
            start_card_index()
            return
        # K-237's decline behaviour: mirror pertinence's own Skip, not an
        # abort. The rest of the chain still runs, against whatever card
        # index already exists on disk (stale or empty) rather than the
        # fresh one the user just declined to pay for — matching this PDF
        # against recently added/edited cards is degraded until the index
        # is rebuilt, but the PDF still gets its own pages embedded,
        # matched and tagged. A raise or a silent hang here would be worse
        # than a documented degradation.
        _publish(
            _state._replace(
                label="Card index embed skipped — matching may miss recent cards."
            )
        )
        after_card_index(None, True)

    _publish(
        RunnerState(
            active=True,
            kind=kind,
            name=label,
            label="Starting…",
            pending=_queue.pending(),
        )
    )
    cfg = _cfg()
    # The confirm guards only the SILENT auto-index-on-add path (a single
    # PDF's own phase one) — never a JOB_CARDS entry, which only ever
    # reaches this queue via offer_model_sweep's OWN priced confirm
    # (Preferences Save); asking again here would double-prompt for a
    # spend the user already approved.
    if kind != JOB_PDF or not card_index_from_scratch(cfg):
        start_card_index()
    else:
        ask_card_index_confirm(
            mw,
            card_index_confirm_message(label, _card_index_estimate(cfg)),
            card_index_answered,
        )


def _job_done(message: str, finished: str = "") -> None:
    global _current
    _current = None
    _publish(
        RunnerState(message=message, pending=_queue.pending(), finished=finished)
    )
    _pump_soon()


def _job_stopped() -> None:
    """A phase reported partial work. Stop the whole run rather than
    burning a paid API on the jobs behind it."""
    global _current
    _current = None
    dropped = _queue.clear()
    tail = f" {dropped} queued job(s) dropped." if dropped else ""
    _publish(
        RunnerState(message="Indexing stopped — it resumes where it left off." + tail)
    )


def _fail(exc: Exception) -> None:
    """One failure ends the run. OpenAI being down would fail all ten
    queued jobs identically; ten identical errors is not information,
    and each attempt is a billable request.

    ONE exception to that: a PDF deleted while it was the running job
    fails with "no stored text", which says nothing about the nine
    behind it. Deleting one PDF must not cancel a batch, so that case
    skips like a deletion caught before its turn.
    """
    global _current
    job, _current = _current, None
    if job is not None and job[0] == JOB_PDF and not _pdf_present(job[1]):
        _pump_soon()
        return
    dropped = _queue.clear()
    try:
        msg = (
            exc.user_message()
            if isinstance(exc, embeddings.EmbeddingError)
            else f"{type(exc).__name__}: {exc}"
        )
    except Exception:
        msg = str(exc)
    if dropped:
        msg += f"  {dropped} queued job(s) were not started."
    print(f"[klausmate] indexing failed: {msg}")
    _publish(RunnerState(message=msg))


# ── the model-change sweep ───────────────────────────────────────────────


def _manifest_paths() -> list[tuple[str, str]]:
    """(PDF name, where its index manifest would live), for every PDF
    with stored text. One walk, two readers below."""
    from . import pdf_handler, pdf_index

    root = _user_files()
    out: list[tuple[str, str]] = []
    for fname in pdf_handler.list_contexts(root):
        name = fname[:-4] if fname.endswith(".txt") else fname
        out.append(
            (name, os.path.join(pdf_index.index_dir(root, name), pdf_index.MANIFEST_FILE))
        )
    return out


def indexed_pdf_names() -> list[str]:
    """Every PDF that has an index on disk, fresh or stale.

    Membership is "has a manifest FILE", NOT a signature comparison —
    after a model change every one of them is stale by definition, and
    hand-spelling that comparison is exactly how eight call sites
    silently broke when the signature grew a third element.

    Nor a PARSED, version-checked manifest (K-236): ``stats_from_disk``
    reads through ``card_index.read_manifest``, which answers None for
    any version but the current one, so asking it here excluded every
    index built before pdf_index v2 — the exact population D8's sweep
    exists for. The upgrader accepted a priced re-index and only the
    card index rebuilt.
    """
    names: list[str] = []
    try:
        for name, manifest in _manifest_paths():
            if os.path.isfile(manifest):
                names.append(name)
    except Exception as exc:
        print(f"[klausmate] index sweep scan failed: {exc}")
    return names


def stale_index_names() -> list[str]:
    """Every PDF whose manifest was written by an older INDEX_VERSION.

    These read as ABSENT everywhere (``pdf_index.load`` and
    ``stats_from_disk`` both gate on the version), so the Library shows
    them unembedded, the Lecture panel finds no page and the assistant
    skips them — and nothing would ever offer to rebuild them, because
    an UPGRADE moves no embedding signature. That is why this is the
    third sweep trigger (K-236). A corrupt manifest is not stale: it
    rebuilds on demand, and a whole-collection prompt is the wrong
    answer to one bad file.
    """
    names: list[str] = []
    try:
        from . import pdf_index

        for name, manifest in _manifest_paths():
            try:
                with open(manifest, encoding="utf-8") as f:
                    version = json.load(f).get("version")
            except (OSError, ValueError, AttributeError):
                continue
            if version != pdf_index.INDEX_VERSION:
                names.append(name)
    except Exception as exc:
        print(f"[klausmate] stale index scan failed: {exc}")
    return names


def signature_changed(previous: tuple, current: tuple) -> bool:
    """Did the embedding settings move under the stored vectors?

    ``embeddings.signature_matches`` and never a tuple comparison: the
    signature is (provider, model, dims) and dims is compared only when
    the new setting asks for a specific width. A hand-written ``!=``
    here would read every cache as stale forever and re-embed the whole
    collection on a paid API, silently — which is precisely what
    happened across the addon when the tuple grew from two to three.
    """
    try:
        return not embeddings.signature_matches(
            previous[0], previous[1], previous[2] if len(previous) > 2 else 0, current
        )
    except Exception:
        return False


def card_index_from_scratch(cfg: dict) -> bool:
    """K-237: is ``curation.ensure_index`` about to re-embed the WHOLE card
    index rather than diff it — no manifest on disk yet, or its stored
    signature no longer matches the configured provider/model/dims?

    The exact condition ``offer_model_sweep`` already gates its own priced
    confirm on, read here from ``curation.index_stats()`` (manifest-only,
    no vector load — cheap enough for the phase-one call site this backs,
    which runs on every silent auto-index-on-add). Comparison is always
    ``signature_changed``/``embeddings.signature_matches``, never a
    hand-spelled tuple check, for the same reason spelled out there.
    """
    from . import curation

    try:
        stats = curation.index_stats()
    except Exception as exc:
        print(f"[klausmate] card-index stats unavailable: {exc}")
        return False  # a bookkeeping hiccup must not manufacture a confirm
    if not stats.get("exists"):
        return True
    current = embeddings.index_signature(cfg)
    stored = (stats.get("provider", ""), stats.get("model", ""), stats.get("dims", 0))
    return signature_changed(stored, current)


def _card_index_estimate(cfg: dict) -> str:
    """What the from-scratch card-index embed the confirm is ASKING about
    would roughly cost — the note half of ``sweep_estimate``, called with
    no PDFs, since phase one only ever re-embeds notes (a PDF's own pages
    are phase two, priced nowhere and unaffected by this confirm)."""
    try:
        from . import cost

        return cost.format_estimate(sweep_estimate([]))
    except Exception as exc:
        print(f"[klausmate] card-index confirm estimate failed: {exc}")
        return "cost unknown for this model"


def sweep_estimate(names: list[str]) -> Any:
    """What re-embedding everything would cost, as a ``cost.Estimate``.

    Every note's field text plus every PAGE of every swept PDF — the
    page store is what gets embedded now, so a chunking of the raw text
    file would be counting the wrong thing. The note half is ONE SQL
    scalar rather than a walk of the collection: this runs on the main
    thread, inside Save, with the user waiting.

    Raises (KeyError) for a model with no published price in cost.PRICES
    — deliberately, rather than quietly pricing a hand-typed model as
    some other one. ``offer_model_sweep`` catches it and says so.
    """
    from . import cost, page_store, pdf_handler

    chars = 0
    # A failed scalar here must NOT degrade to a cheap $0 estimate — it
    # propagates (like the price-lookup KeyError above it) so
    # offer_model_sweep's own catch reads it as "cost unknown", never
    # as a priced re-embed that costs real money for the wrong reason.
    chars += int(
        mw.col.db.scalar("select coalesce(sum(length(flds)),0) from notes") or 0
    )
    for name in names:
        try:
            safe = pdf_handler._safe_basename(name)
            pages = pdf_handler.load_pages(_user_files(), name) or []
            path = pdf_handler.pdf_path_for(_user_files(), safe) or ""
            # ponytail: one JSON read per page on the main thread inside
            # Save; a QueryOp if libraries reach ~10k pages.
            rows = page_store.page_texts(_user_files(), safe, path, len(pages))
            stored = sum(len(t) for _p, _h, t in rows)
            chars += stored or sum(len(p) for p in pages)
        except Exception as exc:
            print(f"[klausmate] page-text size unavailable for {name}: {exc}")
    return cost.estimate_embed(chars, embeddings.embedding_model(_cfg()))


def offer_model_sweep(parent: Any, previous: tuple, first_key: bool = False) -> bool:
    """Preferences → Save changed the model, or set the API key for the
    first time: offer to re-index.

    ``first_key`` exists because the signature does NOT move when a user
    finally pastes their key — nothing was ever embedded, so there is
    nothing to compare — and that is precisely the moment the offer is
    most useful. Rotating an existing key is not a first key: those
    vectors are still valid, and re-embedding them would be a bill for
    nothing.

    A stale-version manifest on disk is the third trigger, for the same
    reason (K-236): an upgrade to pdf_index v2 moves no signature either,
    yet every one of those indexes now reads as absent.
    ``setup_flow`` calls this once per profile on that ground alone.

    Returns True when the question was actually asked. Window-modal via
    ``open()`` and a ``finished`` callback — K-114: ``exec()`` on a
    static (question/askUser) runs a nested app-modal loop that segfaults
    on Qt 6.11 + macOS 26, and this dialog is raised from a NON-modal
    Preferences window that stays usable behind it.
    """
    if mw is None or getattr(mw, "col", None) is None:
        return False
    current = embeddings.index_signature(_cfg())
    if not (
        first_key or signature_changed(previous, current) or stale_index_names()
    ):
        return False
    names = indexed_pdf_names()
    try:
        note_count = mw.col.note_count()
    except Exception:
        note_count = 0
    try:
        from . import cost

        estimate = cost.format_estimate(sweep_estimate(names))
    except Exception as exc:
        print(f"[klausmate] sweep estimate failed: {exc}")
        estimate = "cost unknown for this model"
    text = sweep_message(
        len(names), note_count, current[1] or current[0], estimate,
    )
    jobs = sweep_jobs(names)

    def answered(_result: int) -> None:
        clicked = box.clickedButton()
        yes = (
            clicked is not None
            and box.standardButton(clicked) == QMessageBox.StandardButton.Yes
        )
        box.deleteLater()
        if yes:
            request(jobs, announce=False)

    box = QMessageBox(parent)
    box.setWindowTitle("Re-index with the new model?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    box.setDefaultButton(QMessageBox.StandardButton.No)
    no_btn = box.button(QMessageBox.StandardButton.No)
    if no_btn is not None:
        no_btn.setObjectName("SecondaryButton")
    try:
        from . import theme

        box.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    except Exception as exc:
        print(f"[klausmate] sweep dialog theme failed: {exc}")
    box.finished.connect(answered)
    box.open()
    return True


def ask_judge(parent: Any, text: str, answer: Callable[[bool], None]) -> None:
    """The pertinence phase's own paid-pass confirm (spec D4): Judge or
    Skip, Skip the default — a stray Enter reaching this window-modal
    dialog must not start a paid batch, the same rule ``offer_model_sweep``
    follows for its own confirm. Window-modal via ``open()`` (K-114);
    ``answer`` fires from ``finished`` rather than a return value.
    """
    box = QMessageBox(parent)
    box.setWindowTitle("Judge matched cards?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    judge_btn = box.addButton("Judge", QMessageBox.ButtonRole.AcceptRole)
    skip_btn = box.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(skip_btn)
    try:
        from . import theme

        box.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    except Exception as exc:
        print(f"[klausmate] judge dialog theme failed: {exc}")

    def finished(_result: int) -> None:
        clicked = box.clickedButton()
        box.deleteLater()
        answer(clicked is judge_btn)

    box.finished.connect(finished)
    box.open()


def ask_card_index_confirm(parent: Any, text: str, answer: Callable[[bool], None]) -> None:
    """K-237's own paid-pass confirm: a from-scratch card-index embed
    about to run as phase one of an autonomous, silent PDF add. Same
    shape as ``ask_judge`` above, not ``offer_model_sweep``'s: this fires
    deep inside the queue's async chain, never from an open Preferences
    window with a real parent to anchor on, so it is Embed/Skip,
    window-modal via ``open()`` (K-114), with Skip the default button — a
    stray Enter must never start a paid whole-collection re-embed.
    """
    box = QMessageBox(parent)
    box.setWindowTitle("Rebuild the card index?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    embed_btn = box.addButton("Embed", QMessageBox.ButtonRole.AcceptRole)
    skip_btn = box.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(skip_btn)
    try:
        from . import theme

        box.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    except Exception as exc:
        print(f"[klausmate] card-index confirm dialog theme failed: {exc}")

    def finished(_result: int) -> None:
        clicked = box.clickedButton()
        box.deleteLater()
        answer(clicked is embed_btn)

    box.finished.connect(finished)
    box.open()


# ── the status dock ──────────────────────────────────────────────────────


class _StatusDock(_DockBase):  # type: ignore[misc]
    """A thin bar across the bottom of the main window: what is being
    indexed, how far along, and Stop.

    A QDockWidget rather than an overlay child of ``mw`` because the
    main window's centre is a webview and a plain child stacked over
    QtWebEngine is a z-order gamble; the dock area is Qt's own managed
    space, it survives every state change (deck browser, overview,
    mid-review), and ``lecture_view`` already proves the pattern here.
    Frameless and featureless — the user never docks, floats or closes
    it; it appears when work starts and leaves when it is done.
    """

    def __init__(self) -> None:
        super().__init__(mw)
        from . import theme

        night = theme.night_mode()
        c = theme.palette(night)
        self.setObjectName("KlausIndexDock")
        try:
            self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
            self.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            self.setTitleBarWidget(QWidget(self))
            self.setStyleSheet(theme.dialog_qss(night))
        except Exception as exc:
            print(f"[klausmate] index dock chrome failed: {exc}")

        body = QWidget(self)
        try:
            body.setObjectName("KlausIndexBar")
            body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            body.setStyleSheet(
                f"QWidget#KlausIndexBar {{ background-color: {c['bg']};"
                f" border-top: 1px solid {c['grey_light']}; }}"
            )
        except Exception as exc:
            print(f"[klausmate] index dock style failed: {exc}")
        lay = QHBoxLayout(body)
        lay.setContentsMargins(12, 5, 10, 5)
        lay.setSpacing(10)
        self.label = QLabel("", body)
        try:
            self.label.setStyleSheet(theme.muted_label_qss(night, 12))
        except Exception:
            pass
        lay.addWidget(self.label, 1)
        self.button = QPushButton("Stop", body)
        self.button.setObjectName("SecondaryButton")
        self.button.clicked.connect(_on_dock_button)
        lay.addWidget(self.button, 0)
        self.setWidget(body)

    def render(self, snapshot: RunnerState) -> None:
        self.label.setText(status_line(snapshot))
        self.button.setText(dock_button_label(snapshot))


def _on_dock_button() -> None:
    """One button, two jobs: Stop while running, Dismiss when the bar is
    only carrying the last result."""
    if _current is not None:
        cancel_all()
    else:
        _hide_dock()


def _ensure_dock() -> Any:
    global _dock
    if _dock is not None:
        return _dock
    if mw is None or QDockWidget is None:
        return None
    _dock = _StatusDock()
    try:
        mw.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, _dock)
    except Exception as exc:
        print(f"[klausmate] index dock attach failed: {exc}")
    return _dock


def _render_dock(snapshot: RunnerState) -> None:
    global _hide_gen
    if not snapshot.active and not snapshot.message:
        _hide_dock()
        return
    dock = _ensure_dock()
    if dock is None:
        return
    dock.render(snapshot)
    dock.show()
    _hide_gen += 1
    if not snapshot.active:
        _hide_dock_later()


def _hide_dock_later() -> None:
    """A finished run leaves its result on screen briefly, then clears
    itself — a failure does not (it stays until dismissed or superseded,
    because it is the only place the reason is written)."""
    if _state.active or not _state.message:
        return
    gen = _hide_gen

    def go() -> None:
        if gen == _hide_gen and _current is None:
            _hide_dock()

    try:
        QTimer.singleShot(IDLE_HIDE_MS, go)
    except Exception:
        pass


def _hide_dock() -> None:
    global _hide_gen
    _hide_gen += 1
    if _dock is not None:
        try:
            _dock.hide()
        except Exception:
            pass


# ── lifecycle ────────────────────────────────────────────────────────────


def _on_profile_close(*_a: Any) -> None:
    """A job outlives its window but never its profile: the phases read
    the collection and write into ``user_files``, both of which are
    about to go away."""
    global _dock, _key_warned
    try:
        cancel_all()
    except Exception as exc:
        print(f"[klausmate] index queue teardown failed: {exc}")
    _key_warned = False
    dock, _dock = _dock, None
    if dock is not None:
        try:
            mw.removeDockWidget(dock)
            dock.deleteLater()
        except Exception as exc:
            print(f"[klausmate] index dock teardown failed: {exc}")


def setup() -> None:
    if gui_hooks is None:
        return
    gui_hooks.profile_will_close.append(_on_profile_close)
