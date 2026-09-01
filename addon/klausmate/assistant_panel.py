"""The Library's right-hand assistant panel.

The surface Pouya chose: a third pane in the Library splitter, beside the
folder tree and the PDF viewer. It is the first thing that makes
``card_forge``, ``llm_client``, ``entitlement``, ``anki_tools``,
``assistant_session`` and ``podcast`` reachable by a person.

Deliberately thin. Everything that could be *wrong* lives in
``assistant_session``; this renders a transcript, forwards keystrokes, and
gets the threading right.

**The threading is the part with teeth.** ``anki_tools.execute_tool``
marshals its handler ONTO the Qt main thread and blocks the caller until it
finishes — so the tool loop must run on a worker, and calling it from the
main thread would deadlock against itself. The worker talks back through
signals, which Qt queues across threads for us; touching a widget directly
from the worker would be a crash rather than a glitch.

``QWidget`` is the base class on purpose. K-161 found that a
``QDockWidget = None`` import fallback raises TypeError at CLASS DEFINITION
time — the module fails to import at all, long before anybody uses the
widget — so the base has to be something that always exists.
"""

from __future__ import annotations

import threading

from aqt.qt import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QObject,
    QPlainTextEdit,
    QPushButton,
    Qt,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

# The three things the panel does, in the order Pouya asked for them. Only
# ASK is wired; the other two say so rather than presenting a dead control
# that looks finished.
ASK, PRACTICE, PODCAST = "Ask", "Practice", "Podcast"
TABS = (ASK, PRACTICE, PODCAST)

PLACEHOLDER = {
    PRACTICE: (
        "Multiple-choice practice from the open PDF.\n\n"
        "Not built yet. The generator will reuse the same grounding as the "
        "card drafter: every question cites the slide it came from, and a "
        "question citing a slide you did not select is dropped."
    ),
    PODCAST: (
        "A two-host podcast from the open PDF.\n\n"
        "The script half is built and can be costed; the audio half is not. "
        "Voicing an 8-minute episode is a few cents, so the expensive part "
        "is generating the script over a long lecture, not speaking it."
    ),
}

NO_PDF = "Select a PDF in the Library to ask about it."


def status_line(stop_reason: str, pdf_name: str = "") -> str:
    """The footer under the transcript.

    A loop that hit its turn ceiling looks exactly like a model giving up
    unless it is named, and a cancelled one looks like a crash.
    """
    if stop_reason == "max_turns":
        return "Stopped after too many tool calls — try a narrower question."
    if stop_reason == "cancelled":
        return "Stopped."
    if stop_reason == "answered":
        return f"Answered from {pdf_name}." if pdf_name else "Answered."
    return NO_PDF if not pdf_name else f"Ready — asking about {pdf_name}."


def transcript_entry(role: str, text: str) -> str:
    """One block in the running transcript."""
    who = "You" if role == "user" else "Klaus"
    return f"{who}: {text}".rstrip()


class _Worker(QObject):  # type: ignore[misc]
    """Carries the worker thread's news back to the widget.

    Signals rather than direct calls: Qt queues a cross-thread emission onto
    the receiving object's thread, and touching a widget from the worker
    would be a crash rather than a glitch.
    """

    delta = pyqtSignal(str)
    tool = pyqtSignal(str)
    done = pyqtSignal(str, str)
    failed = pyqtSignal(str)


class AssistantPanel(QWidget):  # type: ignore[misc]
    """The panel itself."""

    def __init__(self, parent=None, session_factory=None) -> None:
        super().__init__(parent)
        self.setObjectName("KlausAssistantPanel")
        # Injected so tests can drive the panel without a network, a model
        # or a collection. Defaults to the real thing at first use.
        self._session_factory = session_factory or _default_session
        self._session = None
        self._pdf_name = ""
        self._cancel: threading.Event | None = None
        self._thread: threading.Thread | None = None

        self.signals = _Worker()
        self.signals.delta.connect(self._on_delta)
        self.signals.tool.connect(self._on_tool)
        self.signals.done.connect(self._on_done)
        self.signals.failed.connect(self._on_failed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_ask(), ASK)
        for name in (PRACTICE, PODCAST):
            self.tabs.addTab(self._placeholder(PLACEHOLDER[name]), name)
        outer.addWidget(self.tabs, 1)
        # Nothing is selected yet, and Qt's default is enabled. Without
        # this the panel opens with a live-looking input that silently
        # swallows the first question — send() returns early with no PDF,
        # so pressing Enter does nothing at all and says nothing either.
        # (Found by driving the real widget offscreen; a stub reports
        # whatever it was told to.)
        self._set_running(False)
        self._apply_theme()

    # ---------------------------------------------------------- building

    def _placeholder(self, text: str) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        label = QLabel(text, page)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(label, 1)
        return page

    def _build_ask(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.transcript = QPlainTextEdit(page)
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText(NO_PDF)
        lay.addWidget(self.transcript, 1)

        self.status = QLabel(NO_PDF, page)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.input = QLineEdit(page)
        self.input.setPlaceholderText("Ask about this PDF…")
        self.input.returnPressed.connect(self.send)
        row.addWidget(self.input, 1)
        self.send_btn = QPushButton("Ask", page)
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        self.stop_btn = QPushButton("Stop", page)
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)
        lay.addLayout(row)
        return page

    def _apply_theme(self) -> None:
        """Styles come from theme tokens; this file names no colour."""
        try:
            from . import theme

            self.setStyleSheet(theme.dialog_qss(theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] assistant panel theme failed: {exc}")

    # ----------------------------------------------------------- binding

    def set_pdf(self, name: str) -> None:
        """Bind to the PDF the Library has selected.

        A new document starts a new conversation: carrying the last
        lecture's exchange into this one is how an answer ends up citing a
        slide from a different file.
        """
        name = str(name or "")
        if name == self._pdf_name:
            return
        self._pdf_name = name
        self._session = None
        try:
            self.transcript.clear()
            self.input.setEnabled(bool(name))
            self.send_btn.setEnabled(bool(name))
            self.status.setText(status_line("", name))
        except Exception as exc:
            print(f"[klausmate] assistant panel rebind failed: {exc}")

    def _ensure_session(self):
        if self._session is None:
            self._session = self._session_factory(self._pdf_name)
        return self._session

    # ------------------------------------------------------------ asking

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _guard(self, what: str, fn) -> None:
        """Run a SLOT body, swallowing anything that escapes.

        Not defensive style — load-bearing. PyQt6 answers an unhandled
        exception in a slot by printing the traceback and then calling
        qFatal, which SIGABRTs the process. In Anki that is not a broken
        panel, it is Anki gone, mid-review, with unsaved state. Measured:
        a plain RuntimeError raised in a clicked handler exits 134.
        """
        try:
            fn()
        except Exception as exc:
            print(f"[klausmate] assistant panel {what} failed: {exc}")

    def send(self) -> None:
        self._guard("send", self._send)

    def _send(self) -> None:
        question = self.input.text().strip()
        if not question or self.busy or not self._pdf_name:
            return
        self.input.clear()
        self._append(transcript_entry("user", question))
        self._append("Klaus: ")
        self._set_running(True)
        self._cancel = threading.Event()

        def run() -> None:
            try:
                session = self._ensure_session()
                answer = session.ask(
                    question,
                    on_text=self.signals.delta.emit,
                    on_tool=lambda name, args: self.signals.tool.emit(name),
                    cancel=self._cancel,
                )
                self.signals.done.emit(answer, session.last_stop)
            except Exception as exc:
                # The worker must never die silently: a panel stuck on
                # "thinking" with no error is indistinguishable from a hang.
                self.signals.failed.emit(str(exc))

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        def go() -> None:
            if self._cancel is not None:
                self._cancel.set()

        self._guard("stop", go)

    def _set_running(self, running: bool) -> None:
        self.send_btn.setEnabled(not running and bool(self._pdf_name))
        self.stop_btn.setEnabled(running)
        self.input.setEnabled(not running and bool(self._pdf_name))

    # --------------------------------------------------- signal handlers

    def _append(self, text: str) -> None:
        self.transcript.appendPlainText(text)

    def _on_delta(self, text: str) -> None:
        """Stream into the open Klaus block rather than appending lines —
        appendPlainText would put every token on its own row.

        Guarded like every slot here: this one is QUEUED from a worker
        thread, so it can arrive after the widget it writes into is gone.
        """
        self._guard("delta", lambda: self._insert(text))

    def _insert(self, text: str) -> None:
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.transcript.setTextCursor(cursor)

    def _on_tool(self, name: str) -> None:
        self._guard("tool notice", lambda: self.status.setText(
            f"Looking through the slides ({name.replace('_', ' ')})…"))

    def _on_done(self, answer: str, stop_reason: str) -> None:
        def go() -> None:
            self.status.setText(status_line(stop_reason, self._pdf_name))
            self._set_running(False)

        self._guard("completion", go)

    def _on_failed(self, message: str) -> None:
        def go() -> None:
            self._append(f"\n[error] {message}")
            self.status.setText("That did not go through.")
            self._set_running(False)

        self._guard("error report", go)


def _default_session(pdf_name: str):
    """The real session: hosted or BYO-key backend, the collection tools.

    Imported lazily so the panel module stays importable — and testable —
    without a configured provider.
    """
    from . import anki_tools, assistant_session, llm_client

    pkg = __import__(__package__, fromlist=["get_config"])
    get_config = pkg.get_config
    return assistant_session.Session(
        backend=llm_client.backend_from_config(get_config),
        run_tool=anki_tools.execute_tool,
        tools=[
            spec for spec in anki_tools.TOOL_SPECS
            if spec.get("name") in (
                "search_lecture_pdfs", "search_notes", "get_note",
            )
        ],
        pdf_name=pdf_name,
    )
