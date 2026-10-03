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
``retention.ensure_matches`` → ``tag_sync.sync_after_matches``, with the
cancel token threaded through exactly as K-146 left it — and the Library
became one more CALLER. There is exactly one copy of that sequence in
the addon; a second one would drift (K-143's two-renderer lesson).

**Each indexing phase takes ``curation._busy`` in turn** rather than one
held token across the run. That is K-146's finding, not an oversight: the
cancellation branches return without releasing, so a caller-held token
would leak and brick indexing for the rest of the session.
Serialisation across jobs is the queue below, not the token. Phase
four writes the tags after matching.

**A queue, not a race.** Ten dropped PDFs are ten legitimate requests.
``curation._busy`` REFUSES a concurrent run — correct for a user
double-clicking a button, wrong for a batch — so jobs are serialised
here and the token is never contended by us. Duplicates collapse
(dropping the same PDF twice queues it once), and a PDF deleted before
its turn is dropped silently, checked at start time rather than trusting
a delete path to call us.

**Feedback is the shippable part.** Local embedding can take minutes, so a job must be visible
and stoppable from wherever it was started, and a toast is not a
progress display. So the runner publishes ONE ``RunnerState``, rendered
by ONE pure ``status_line()``, and ``_report_task`` turns it into the
``index`` task of the status bar (``tasks``/``status_bar``) at the
bottom of the main window and Browse: progress bar, text, and ✕ to
stop. Nothing starts on its own: the Library's ⟳ (``refresh``) is the
only trigger, and it tooltips what it queued (manual indexing, spec
docs/superpowers/specs/2026-10-01-manual-indexing-design.md).

**Gates.** No profile, no run (``mw.col`` is None until one opens).
A cancelled or failed job leaves nothing
that later reads as complete: the phases persist partial work as
explicitly partial (``card_index`` writes its manifest after its
vectors, ``pdf_index.is_fresh`` is False while ``embedded_rows`` trails
``chunks``, ``ensure_matches`` refuses to cache a cancelled pass), and
the tag write is on the completion path only.

Pure above the divider — what needs indexing, the ⟳ job plan, the queue
and every string the user reads — so ``tests/test_index_queue.py`` can drive
the whole policy without Qt.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable, NamedTuple

from . import embeddings
from . import settings

# A job is a plain ``(kind, name)`` tuple; name is "" for JOB_CARDS.
JOB_CARDS = "cards"  # refresh the card index alone (a sweep with no PDFs)
JOB_PDF = "pdf"  # the full chain for one PDF


# ── pure: manual indexing (⟳) ───────────────────────────────────────────


def needs_indexing(stats: dict, source_sig: Any, signature: Any) -> bool:
    """Does this PDF's page index need (re)building? ``stats`` is
    ``pdf_index.stats_from_disk``; ``source_sig`` the current
    ``pdf_index.source_signature`` (None when the text file is gone).
    Missing, partial, older-version, other-model and other-source
    indexes all need it."""
    from . import pdf_index

    try:
        return not (
            stats.get("exists")
            and stats.get("complete")
            and stats.get("version") == pdf_index.INDEX_VERSION
            and embeddings.signature_matches(
                stats.get("provider", ""), stats.get("model", ""), stats.get("dims", 0), signature
            )
            and source_sig is not None
            and tuple(stats.get("source_sig") or ()) == tuple(source_sig)
        )
    except Exception:
        return True


def refresh_jobs(
    names: list[str],
    excluded: set,
    pending: set,
    needs: Callable[[str], bool],
    stale_matches: set,
    cards_from_scratch: bool,
) -> list[tuple[str, str]]:
    """What one ⟳ press queues, in Library order: every PDF that needs
    indexing or re-matching, minus excluded and already-queued ones; the
    card index alone when no PDF job would rebuild it first."""
    jobs = [
        (JOB_PDF, n)
        for n in names
        if n not in excluded and n not in pending and (n in stale_matches or needs(n))
    ]
    if not jobs and cards_from_scratch:
        jobs.append((JOB_CARDS, ""))
    return jobs


def refresh_message(n_pdfs: int, cards: bool) -> str:
    if n_pdfs:
        return f"Indexing {n_pdfs} PDF" + ("" if n_pdfs == 1 else "s")
    return "Rebuilding the card index" if cards else "Everything is indexed"


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


# ── pure: everything the user reads ──────────────────────────────────────


class RunnerState(NamedTuple):
    """One snapshot, published to every listener and to the status
    bar's ``index`` task, which reads it through ``status_line`` below."""

    active: bool = False
    kind: str = ""
    name: str = ""  # display label of the running job
    label: str = ""  # phase label from the pipeline ("Embedding PDF…")
    phase: str = ""  # no separate phase value in the four-phase chain
    done: int = 0
    total: int = 0
    pending: int = 0  # jobs still waiting behind this one
    message: str = ""  # terminal text: finished / cancelled / refused
    finished: str = ""  # safe name of the PDF that just completed
    failed: bool = False  # the message is a failure: it stays in the bar


def status_line(state: RunnerState) -> str:
    """The ONE progress sentence. Idle states read as their message."""
    if not state.active:
        return state.message
    head = state.name or "Card index"
    if state.label:
        head = f"{head} — {state.label}"
    if state.total:
        progress = f"{round(state.done * 100 / state.total)}%"
        head = f"{head} {progress}"
    if state.pending:
        head = f"{head}  ·  {state.pending} more queued"
    return head


def card_index_confirm_message(pdf_label: str) -> str:
    """``pdf_label`` "" is ⟳'s card-index-only job."""
    if not pdf_label:
        return ("Indexing needs to rebuild your whole card index locally. "
                "This may take a while. Skip to leave it for later.")
    return (
        f"Indexing “{pdf_label}” needs to rebuild your whole card index locally first. "
        "This may take a while. Skip to add this PDF anyway: matching against your cards "
        "stays degraded until the card index is rebuilt (Preferences' Index Now, "
        "or the Library's ⟳, will finish it)."
    )


def queued_message(name: str, ahead: int) -> str:
    """The tooltip an add gets. ``ahead`` is how many jobs run BEFORE
    this one — the part of a ten-PDF drop the user cannot see, and the
    difference between "this is happening" and "this will happen"."""
    if ahead <= 0:
        return f"Klaus Note: indexing “{name}”"
    return f"Klaus Note: “{name}” queued for indexing — {ahead} ahead of it"


# ── aqt glue ─────────────────────────────────────────────────────────────

try:
    from aqt import gui_hooks, mw
    from aqt.qt import QMessageBox, QTimer
    from aqt.utils import tooltip
except Exception:  # headless tests / partial environments
    gui_hooks = mw = None  # type: ignore[assignment]
    QMessageBox = QTimer = None  # type: ignore[assignment]

    def tooltip(*_a: Any, **_k: Any) -> None:  # type: ignore[misc]
        pass


_queue = JobQueue()
_current: tuple[str, str] | None = None
_cancel: Any = None
_seq = 0
_state = RunnerState()
_listeners: list[Callable[[RunnerState], None]] = []
_waits = 0

BUSY_RETRY_MS = 1500
BUSY_WAIT_POLLS = 40  # ~60s of waiting for Index Now before giving up
BUSY_WAIT_TEXT = "Waiting for the current indexing run to finish…"




# ── listeners + published state ──────────────────────────────────────────


def pending_names() -> set[str]:
    """Safe names of the PDF being indexed now plus every queued one."""
    names = {name for kind, name in _queue.snapshot() if kind == JOB_PDF}
    if _current is not None and _current[0] == JOB_PDF:
        names.add(_current[1])
    return names


def add_listener(fn: Callable[[RunnerState], None]) -> None:
    """Subscribe a surface (the Library's warning icons read the
    runner through ``pending_names``; the status bar through ``tasks``)."""
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
    _report_task(new)
    for fn in list(_listeners):
        try:
            fn(new)
        except Exception as exc:
            print(f"[klaus_note] index listener failed: {exc}")


def _report_task(state: RunnerState) -> None:
    """The status bar's one ``index`` task: begun on the first active
    snapshot (✕ = ``cancel_all``), updated while it runs, ended with the
    runner's message. A message published with no run in progress (the
    busy-wait text) is shown the same way, as a lingering end."""
    try:
        from . import tasks

        running = any(t.key == "index" and not t.message for t in tasks.snapshot())
        if state.active:
            if running:
                tasks.update("index", done=state.done, total=state.total, label=status_line(state))
            else:
                tasks.begin("index", status_line(state), cancel=cancel_all)
                tasks.update("index", done=state.done, total=state.total)
        elif state.message:
            if not running:
                tasks.begin("index", state.message)
            tasks.end("index", state.message, error=state.failed)
        elif running:
            tasks.end("index")
    except Exception as exc:  # noqa: BLE001 - a report never breaks the run
        print(f"[klaus_note] index status report failed: {exc}")


# ── entry points ─────────────────────────────────────────────────────────


def request(jobs: list[tuple[str, str]], *, announce: bool = True) -> int:
    """Queue jobs and start pumping. Returns how many were newly queued.

    A profile must be open. Local provider failures are reported by the worker.
    """
    global _waits
    if mw is None or getattr(mw, "col", None) is None:
        return 0  # nothing runs before the profile is open
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


def _excluded_now(names) -> set:
    from . import drive_store

    return drive_store.excluded_safes(drive_store.load(settings.user_files()), names)


def _drop_if_excluded(name: str) -> bool:
    """Excluded while its job ran: the index it just wrote goes too.
    True when ``name`` is excluded (its index is gone)."""
    try:
        if _excluded_now([name]):
            from . import pdf_index

            pdf_index.delete(settings.user_files(), name)
            return True
    except Exception as exc:
        print(f"[klaus_note] dropping an excluded PDF's index failed: {exc}")
    return False


def refresh(parent: Any = None) -> int:
    """The Library's ⟳: queue every PDF that needs indexing and is not
    excluded, delete index data an excluded PDF still has, and say what
    happened. The only thing that starts indexing (manual indexing).
    Returns how many jobs were queued."""
    if mw is None or getattr(mw, "col", None) is None:
        tooltip("Open a profile first.", parent=parent)
        return 0
    try:
        from . import pdf_index

        uf = settings.user_files()
        names = [name for name, _manifest in _manifest_paths()]
        excluded = _excluded_now(names)
        for name in excluded:
            if os.path.isdir(pdf_index.index_dir(uf, name)):
                forget(name)
                pdf_index.delete(uf, name)
        sig = embeddings.index_signature(settings.read())

        def needs(name: str) -> bool:
            return needs_indexing(
                pdf_index.stats_from_disk(pdf_index.index_dir(uf, name)),
                pdf_index.source_signature(uf, name),
                sig,
            )

        try:
            stale = set(stale_match_names())
        except Exception as exc:
            print(f"[klaus_note] stale match scan failed: {exc}")
            stale = set()
        # #14: a PDF whose name clashes is shown flagged and waits for a
        # rename. Skipped only, never added to ``excluded``: that set's
        # index data is deleted above.
        try:
            from . import tag_sync

            clashing = set(tag_sync.library_clashes() or ())
        except Exception as exc:  # noqa: BLE001 - the tag gate still holds
            print(f"[klaus_note] clash check before refresh failed: {exc}")
            clashing = set()
        jobs = refresh_jobs(
            names, excluded | clashing, pending_names(), needs, stale, card_index_from_scratch(settings.read())
        )
    except Exception as exc:
        print(f"[klaus_note] refresh failed: {exc}")
        tooltip("Couldn't check the Library for new PDFs.", parent=parent)
        return 0
    added = request(jobs, announce=False) if jobs else 0
    n_pdfs = sum(1 for kind, _n in jobs if kind == JOB_PDF)
    tooltip(refresh_message(n_pdfs, bool(jobs) and not n_pdfs), parent=parent)
    return added


def cancel_all() -> None:
    """Stop the running job and forget the queue.

    Bumping ``_seq`` is what makes this safe rather than merely
    requested: every continuation below checks it first, so the phase
    already in flight finishes into a discarded callback. That matters
    most at the match callback — ``ensure_matches`` hands back a PARTIAL
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

        return pdf_index.source_signature(settings.user_files(), name) is not None
    except Exception as exc:
        print(f"[klaus_note] index queue presence check failed: {exc}")
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

        return drive_store.display_name(settings.user_files(), name) or name
    except Exception:
        return name


def _run(job: tuple[str, str]) -> None:
    """THE chain — the only copy in the addon.

    ``curation.ensure_index`` leads because it is the only thing that
    refreshes the CARD index, and everything that matches notes against
    a PDF reads it: skip it and every note written since the last pass
    is invisible to ``ensure_matches``, and the PDF's tag under-covers
    with no error at all (K-146's whole point). The four phases are
    ``ensure_index``, ``ensure_pdf_index``, ``ensure_matches``, and
    ``tag_sync.sync_after_matches``.
    """
    global _cancel, _seq
    from . import curation, retention, tag_sync

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
        if kind == JOB_PDF:
            _drop_if_excluded(name)  # phase two may already have saved it
        if not live():
            return
        _fail(exc)

    def after_matches(matches: Any) -> None:
        if not live():
            return
        try:
            tag_sync.sync_after_matches(mw, name, matches)
        except Exception as exc:
            print(f"[klaus_note] tag sync after index failed: {exc}")
        _drop_if_excluded(name)
        _job_done(f"Indexed “{label}”.", finished=name)

    def after_pdf_index(idx: Any) -> None:
        # Before live(): a cancelled run still saved its partial index.
        excluded = _drop_if_excluded(name)
        if not live():
            return
        if excluded:
            _job_done(f"“{label}” is excluded from the index.")
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
        if kind == JOB_CARDS:
            _job_done("Card index rebuild skipped.")
            return
        # K-237's decline behaviour: continue without the embed. The rest
        # of the chain still runs, against whatever card
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
    cfg = settings.read()
    # K-237: a from-scratch card re-embed is long, so it is asked first —
    # as a PDF job's phase one and as ⟳'s card-index-only job alike.
    if not card_index_from_scratch(cfg):
        start_card_index()
    else:
        ask_card_index_confirm(
            mw,
            card_index_confirm_message(label if kind == JOB_PDF else ""),
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
    repeating failed local work for the jobs behind it."""
    global _current
    _current = None
    dropped = _queue.clear()
    tail = f" {dropped} queued job(s) dropped." if dropped else ""
    _publish(
        RunnerState(message="Indexing stopped — it resumes where it left off." + tail, failed=True)
    )


def _fail(exc: Exception) -> None:
    """One failure ends the run. Ollama being down would fail all ten
    queued jobs identically; ten identical errors is not information,
    and each attempt repeats the same local failure.

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
    print(f"[klaus_note] indexing failed: {msg}")
    _publish(RunnerState(message=msg, failed=True))


# ── Library scans ────────────────────────────────────────────────────────


def _manifest_paths() -> list[tuple[str, str]]:
    """(PDF name, where its index manifest would live), for every PDF
    with stored text. One walk, two readers below."""
    from . import pdf_handler, pdf_index

    root = settings.user_files()
    out: list[tuple[str, str]] = []
    for fname in pdf_handler.list_contexts(root):
        name = fname[:-4] if fname.endswith(".txt") else fname
        out.append(
            (name, os.path.join(pdf_index.index_dir(root, name), pdf_index.MANIFEST_FILE))
        )
    return out


def stale_match_names() -> list[str]:
    """K-302: PDFs whose matches.json was written by an older
    MATCHES_VERSION (scores on the old raw-cosine scale). Re-matching them
    costs no embedding when their indexes are current, and it is what
    re-tags each PDF at the new threshold. A PDF never matched is not
    stale — there is nothing on disk to refresh."""
    from . import retention

    names: list[str] = []
    for name, manifest in _manifest_paths():
        path = os.path.join(os.path.dirname(manifest), retention.MATCHES_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                version = json.load(f).get("version")
        except (OSError, ValueError, AttributeError):
            continue
        if version != retention.MATCHES_VERSION:
            names.append(name)
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

    Read from ``curation.index_stats()`` (manifest-only, no vector load —
    cheap enough for every PDF job's phase one and every ⟳). Comparison is always
    ``signature_changed``/``embeddings.signature_matches``, never a
    hand-spelled tuple check, for the same reason spelled out there.
    """
    from . import curation

    try:
        stats = curation.index_stats()
    except Exception as exc:
        print(f"[klaus_note] card-index stats unavailable: {exc}")
        return False  # a bookkeeping hiccup must not manufacture a confirm
    if not stats.get("exists"):
        return True
    current = embeddings.index_signature(cfg)
    stored = (stats.get("provider", ""), stats.get("model", ""), stats.get("dims", 0))
    return signature_changed(stored, current)


def ask_card_index_confirm(parent: Any, text: str, answer: Callable[[bool], None]) -> None:
    """K-237's own local rebuild confirm: a from-scratch card-index embed
    about to run as phase one of an autonomous, silent PDF add. This fires
    deep inside the queue's async chain, never from an open Preferences
    window with a real parent to anchor on, so it is Embed/Skip,
    window-modal via ``open()`` (K-114), with Skip the default button — a
    stray Enter must never start a whole-collection re-embed.
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
        print(f"[klaus_note] card-index confirm dialog theme failed: {exc}")

    def finished(_result: int) -> None:
        clicked = box.clickedButton()
        box.deleteLater()
        answer(clicked is embed_btn)

    box.finished.connect(finished)
    box.open()


# ── lifecycle ────────────────────────────────────────────────────────────


def _on_profile_close(*_a: Any) -> None:
    """A job outlives its window but never its profile: the phases read
    the collection and write into ``user_files``, both of which are
    about to go away."""
    try:
        cancel_all()
    except Exception as exc:
        print(f"[klaus_note] index queue teardown failed: {exc}")


def setup() -> None:
    if gui_hooks is None:
        return
    gui_hooks.profile_will_close.append(_on_profile_close)
