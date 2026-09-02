"""The Claude Code assistant dock (K-198): header, transcript, input,
Send/Stop, sessions, slash completer.

Klaus is a HOST for Claude Code (agent_host.py), not a loop of its own —
this module is the Qt face of that host: one QDockWidget on Anki's main
window that follows whatever PDF viewer is in view (viewer_context.py),
attaches the page's OCR text/image (page_ocr.py) to every turn, and
persists one Claude Code session per PDF (assistant_sessions.py). Design:
docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md
sections 4.3, 9, 10, 13.

The five sibling modules this dock consumes (agent_host, viewer_context,
page_ocr, assistant_sessions, anki_endpoint) are imported LAZILY inside
functions, never at module top — the ``PDF_VIEWER_AVAILABLE`` pattern
used across this addon — so this module still imports cleanly if one of
them is momentarily missing or broken while the assistant lands in
pieces across a multi-session swarm. ``theme`` is imported at module top
like every other UI module here; it is aqt-free above its own divider
and safe unconditionally.

Constructor-injectable for tests (``host_factory``, ``context_provider``,
``sessions``, ``user_files``, ``endpoint_info``) — real Qt is still
required to construct one usefully (it is a QDockWidget subclass), but
nothing here ever launches the real ``claude`` binary or touches the
user's running Anki; see tests/test_assistant_dock.py.
"""

from __future__ import annotations

import html as _html
import os
import re
from typing import Any, Callable

from . import theme

try:
    from aqt import gui_hooks, mw
    from aqt.qt import (
        QAction,
        QColor,
        QCompleter,
        QDockWidget,
        QEvent,
        QHBoxLayout,
        QKeySequence,
        QLabel,
        QObject,
        QPlainTextEdit,
        QPushButton,
        Qt,
        QShortcut,
        QStringListModel,
        QTextBlockFormat,
        QTextCharFormat,
        QTextCursor,
        QTextEdit,
        QTimer,
        QVBoxLayout,
        QWidget,
        pyqtSignal,
    )
except Exception:  # headless tests / partial environments
    gui_hooks = mw = None  # type: ignore[assignment]
    QAction = QColor = QCompleter = QDockWidget = QEvent = QHBoxLayout = None  # type: ignore[assignment]
    QKeySequence = QLabel = QObject = QPlainTextEdit = QPushButton = Qt = None  # type: ignore[assignment]
    QShortcut = QStringListModel = None  # type: ignore[assignment]
    QTextBlockFormat = QTextCharFormat = QTextCursor = QTextEdit = None  # type: ignore[assignment]
    QTimer = QVBoxLayout = QWidget = pyqtSignal = None  # type: ignore[assignment]

# See lecture_view.py / index_queue.py / pdf_map.py for the same trick:
# the None-fallback convention is correct for names used as VALUES and a
# trap for names used as BASE CLASSES — a partial Qt surface must cost
# only the dock, never the pure helpers below this point.
_DockBase: Any = QDockWidget if QDockWidget is not None else object
_ObjBase: Any = QObject if QObject is not None else object
_signal: Any = pyqtSignal if pyqtSignal is not None else (lambda *a, **k: None)

_UNSET = object()

EMPTY_STATE_TEXT = (
    "Claude Code is not installed or not on the PATH. Install it and run "
    "`claude` once to log in."
)

# TOOL_LABELS — one collapsed transcript line per tool call. Every key
# here is either one of agent_host.ALLOWED_TOOLS' four non-mcp names
# (Read, Grep, Glob, ToolSearch) or one of the mcp__klaus__* tools named
# in assistant_sessions._SYSTEM_PROMPT_BODY. A tool NOT in this table
# still renders (`used <name>`, see _on_tool_use) rather than a blank
# line — a mutated/blanked lambda here is meant to be caught by a pin
# checking the EXACT text of a known tool, not by a missing-key crash.
TOOL_LABELS: dict[str, Callable[[dict], str]] = {
    "mcp__klaus__search_notes": lambda i: f"searched notes: {i.get('query', '')}",
    "mcp__klaus__find_notes": lambda i: f"searched Anki: {i.get('query', '')}",
    "mcp__klaus__get_notes": lambda i: f"read {len(i.get('note_ids') or [])} notes",
    "mcp__klaus__add_note": lambda i: f"proposed a card for {i.get('deck', '')}",
    "mcp__klaus__search_lecture_pdfs": lambda i: f"searched lectures: {i.get('query', '')}",
    "mcp__klaus__current_view": lambda i: "checked what you are viewing",
    "Read": lambda i: f"read {os.path.basename(str(i.get('file_path', '')))}",
    "Grep": lambda i: f"searched files for {i.get('pattern', '')}",
    "Glob": lambda i: "listed files",
    "ToolSearch": lambda i: "loaded tools",
}


def commands_for_input(text: str, sessions_mod: Any, user_files: str) -> list:
    """Slash-command completion candidates for the CURRENT input text.

    The full command list while the user is still typing the command
    token itself (``text`` starts with ``/`` and has no space or
    newline yet — Qt's own QCompleter does the prefix narrowing from
    there); nothing once a space ends that token (the command has been
    chosen and the rest is free text) or the input isn't a slash
    command at all. Kept Qt-free and pure so it is testable without
    constructing a dock.
    """
    if not text.startswith("/") or " " in text or "\n" in text:
        return []
    try:
        return sessions_mod.list_commands(user_files)
    except Exception as exc:
        print(f"[klausmate] assistant_dock: list_commands failed: {exc}")
        return []


_FENCE_RE = re.compile(r"```(?:[^\n`]*\n)?(.*?)\n?```", re.S)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def _render_inline(text: str) -> str:
    """Escape, then apply **bold** and '- ' bullets — line by line so a
    bullet only ever matches at the START of a line, never mid-sentence."""
    out_lines = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        indent, body = line[: len(line) - len(stripped)], stripped
        bullet = body.startswith("- ")
        if bullet:
            body = body[2:]
        escaped = _BOLD_RE.sub(r"<b>\1</b>", _html.escape(body))
        out_lines.append((_html.escape(indent) + "• " + escaped) if bullet else
                          (_html.escape(indent) + escaped))
    return "<br>".join(out_lines)


def render_markdown_lite(text: str) -> str:
    """A deliberately tiny markdown-ish renderer for assistant text:
    escape everything, then recognise fenced code blocks (-> ``<pre>``,
    escaped, never bold-processed), ``**bold**`` and ``- `` bullet
    lines. No inline code, links, headings or nesting — the assistant's
    own prose rarely needs more, and a bigger parser is a bigger place
    for a partial (mid-stream) render to look broken. Pure; safe on
    ``None``/empty input.
    """
    text = text or ""
    parts = _FENCE_RE.split(text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(f"<pre>{_html.escape(part)}</pre>")
        else:
            out.append(_render_inline(part))
    return "".join(out)


def _default_sessions():
    from . import assistant_sessions

    return assistant_sessions


def _default_user_files() -> str:
    from . import USER_FILES

    return USER_FILES


class _Bridge(_ObjBase):  # type: ignore[misc]
    """Crosses the AgentHost reader thread -> the Qt main thread. The
    host's callbacks only ever call ``.emit()`` here (thread-safe by
    construction); every widget update happens in a connected SLOT,
    which Qt's auto-connection queues automatically when emit() and the
    slot's own thread affinity differ (a real AgentHost) and calls
    directly when they don't (a synchronous fake host in tests) — no
    widget is ever touched from the reader thread either way."""

    init = _signal(dict)
    delta = _signal(str)
    tool_use = _signal(str, str, dict)  # (tool_use id, name, input) — M4: one per BLOCK
    tool_result = _signal(str, bool)
    result = _signal(dict)
    denied = _signal(str)
    error = _signal(str)
    exited = _signal(object)


class AssistantDock(_DockBase):  # type: ignore[misc]
    """Right-docked assistant panel on mw. Frameless (empty title bar) —
    the custom header row inside is the only chrome it needs, same
    convention as lecture_view.LectureDock. Hides rather than deletes
    (QDockWidget's own default close behaviour without WA_DeleteOnClose
    already gives this for free)."""

    def __init__(
        self,
        parent=None,
        *,
        host_factory: Callable[[dict], Any] | None = None,
        context_provider: Callable[[Any], Any] | None = None,
        sessions: Any = None,
        user_files: str | None = None,
        endpoint_info: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("KlausAssistantDock")
        self._sessions = sessions if sessions is not None else _default_sessions()
        self._user_files = user_files if user_files is not None else _default_user_files()
        self._context_provider = context_provider or self._default_context_provider
        self._endpoint_info = endpoint_info or self._default_endpoint_info
        self._host_factory = host_factory or self._default_host_factory

        self._host: Any = None
        self._running = False
        self._current_pdf_safe: Any = _UNSET
        # The PDF the LIVE child belongs to. _UNSET whenever there is no
        # live child for the followed PDF — which is the whole of the
        # lazy-start rule (final review I1): a viewer switch records a
        # target and spawns nothing; _ensure_child() spawns on the next
        # Send. The two are separate because the followed PDF can change
        # many times between two sends.
        self._host_pdf_safe: Any = _UNSET
        # The PDF the IN-FLIGHT turn was sent for, captured at send time.
        # `init`/`result` arrive ~1 s later through _Bridge, by which
        # point _current_pdf_safe may already name a different PDF —
        # remembering the session id under THAT one made B resume A's
        # conversation forever (final review I2).
        self._sending_pdf_safe: Any = _UNSET
        # (pdf, session_id) of a --resume still unproven by a completed
        # turn; cleared on the first clean result, dropped from the
        # store when Claude Code says it has no such conversation.
        self._resume_attempt: Any = None
        # Has the child spawned for _resume_attempt ever reached `init`?
        # A resume Claude Code accepted emits one; a resume of a session
        # it does not have exits before that. Without this, ANY hard
        # kill during an unproven resume — stop()'s own kill after the
        # 2 s grace, say — was read as "the conversation is gone" and
        # silently dropped a perfectly good mapping (re-review NEW-2).
        self._init_seen = False
        self._stop_deadline: float = 0.0
        # Generation token for the _poll_stop QTimer chain. Every chain
        # captures the value current when it started and stops dead once
        # it no longer matches, so a chain left over from a viewer
        # switch can never reach its grace expiry and force-kill a child
        # spawned AFTER it (re-review NEW-1, reproduced). `_ensure_child`
        # bumps it on every successful start, which is what invalidates
        # the pending chain — zeroing `_stop_deadline` instead would
        # leave `expired` permanently false and poll forever.
        self._stop_gen = 0
        self._assistant_block_open = False
        self._assistant_raw_text = ""
        self._assistant_raw_start = 0
        self._tool_blocks: dict = {}
        self._mcp_tooltip = ""
        self._scheduler: Any = None

        self._build_chrome()
        self._build_ui()
        self._bridge = _Bridge()
        self._wire_bridge()

        self._start_host()
        if self._host is not None:
            self._switch_session(self._current_view())

        self._unsub_viewer: Callable[[], None] | None = None
        self._subscribe_viewer()
        self._setup_scheduler()

        try:
            self._width_save_timer = QTimer(self)
            self._width_save_timer.setSingleShot(True)
            self._width_save_timer.timeout.connect(self._write_width_config)
        except Exception as exc:
            print(f"[klausmate] assistant dock: width-save timer failed: {exc}")
            self._width_save_timer = None

    # -- chrome / layout -----------------------------------------------------

    def _build_chrome(self) -> None:
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            self.setTitleBarWidget(QWidget(self))
            self.setStyleSheet(theme.assistant_dock_qss(theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] assistant dock: chrome setup failed: {exc}")

    def _build_ui(self) -> None:
        try:
            body = QWidget(self)
            outer = QVBoxLayout(body)
            outer.setContentsMargins(8, 8, 8, 8)
            outer.setSpacing(6)

            head_row = QHBoxLayout()
            self.header = QLabel("No PDF in view", body)
            self.header.setObjectName("KlausAssistantHeader")
            self.status_dot = QLabel("●", body)
            self.status_dot.setObjectName("KlausAssistantStatusDot")
            head_row.addWidget(self.header, 1)
            head_row.addWidget(self.status_dot, 0)
            outer.addLayout(head_row)

            self.selection_chip = QLabel("", body)
            self.selection_chip.setObjectName("KlausAssistantChip")
            self.selection_chip.setVisible(False)
            outer.addWidget(self.selection_chip)

            self.transcript = QTextEdit(body)
            self.transcript.setObjectName("KlausAssistantTranscript")
            self.transcript.setReadOnly(True)
            outer.addWidget(self.transcript, 1)

            self.input = QPlainTextEdit(body)
            self.input.setObjectName("KlausAssistantInput")
            self.input.setFixedHeight(64)
            self.input.installEventFilter(self)
            self.input.textChanged.connect(self._on_input_text_changed)
            outer.addWidget(self.input)

            btn_row = QHBoxLayout()
            self.recheck_button = QPushButton("Re-check", body)
            self.recheck_button.setObjectName("SecondaryButton")
            self.recheck_button.setVisible(False)
            self.recheck_button.clicked.connect(self._on_recheck_clicked)
            self.new_session_button = QPushButton("New Session", body)
            self.new_session_button.setObjectName("SecondaryButton")
            self.new_session_button.clicked.connect(self._on_new_session_clicked)
            self.send_button = QPushButton("Send", body)
            self.send_button.clicked.connect(self._on_send_button)
            btn_row.addWidget(self.recheck_button)
            btn_row.addWidget(self.new_session_button)
            btn_row.addStretch(1)
            btn_row.addWidget(self.send_button)
            outer.addLayout(btn_row)

            self.setWidget(body)

            self._completer_model = QStringListModel([], self)
            self._completer = QCompleter(self)
            self._completer.setModel(self._completer_model)
            self._completer.setWidget(self.input)
            self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            self._completer.activated[str].connect(self._apply_completion)
        except Exception as exc:
            print(f"[klausmate] assistant dock: ui build failed: {exc}")

    def _wire_bridge(self) -> None:
        try:
            self._bridge.init.connect(self._on_init)
            self._bridge.delta.connect(self._on_delta)
            self._bridge.tool_use.connect(self._on_tool_use)
            self._bridge.tool_result.connect(self._on_tool_result)
            self._bridge.result.connect(self._on_result)
            self._bridge.denied.connect(self._on_denied)
            self._bridge.error.connect(self._on_error)
            self._bridge.exited.connect(self._on_exited)
        except Exception as exc:
            print(f"[klausmate] assistant dock: bridge wiring failed: {exc}")

    def _subscribe_viewer(self) -> None:
        try:
            from . import viewer_context

            self._unsub_viewer = viewer_context.subscribe(self._on_viewer_context_changed)
        except Exception as exc:
            print(f"[klausmate] assistant dock: viewer subscribe failed: {exc}")

    def _setup_scheduler(self) -> None:
        try:
            from . import page_ocr

            self._scheduler = page_ocr.OcrScheduler(
                self._user_files, self._config, self._default_ollama_client
            )
            self._scheduler._timer = lambda: QTimer.singleShot(
                page_ocr.DEBOUNCE_MS, self._scheduler.tick
            )
        except Exception as exc:
            print(f"[klausmate] assistant dock: OCR scheduler setup failed: {exc}")
            self._scheduler = None

    # -- defaults for the injectable seams -----------------------------------

    def _config(self) -> dict:
        try:
            cfg = mw.addonManager.getConfig(__package__)
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    def _default_context_provider(self, view: Any) -> Any:
        from . import page_ocr

        return page_ocr.context_for(view, self._user_files)

    def _default_endpoint_info(self):
        try:
            from . import anki_endpoint

            ep = anki_endpoint.current()
            if ep is None:
                return None
            return (ep.port, ep.token)
        except Exception as exc:
            print(f"[klausmate] assistant dock: endpoint_info failed: {exc}")
            return None

    def _default_ollama_client(self):
        from . import ollama_client

        endpoint = str(self._config().get("endpoint") or "http://localhost:11434")
        return ollama_client.OllamaClient(endpoint)

    def _default_host_factory(self, callbacks: dict):
        from . import agent_host

        cfg = self._config()
        # Cached for the profile session (spec §4.1): the lookup's third
        # step spawns the user's login shell with a 3 s timeout, and this
        # runs on the main thread. Re-check clears the cache first.
        binary = agent_host.find_claude_cached(str(cfg.get("claude_binary") or ""))
        if not binary:
            raise FileNotFoundError("claude binary not found on PATH or in config")
        port, token = 0, ""
        info = self._endpoint_info()
        if info:
            port, token = info
        sp_path = self._sessions.ensure_system_prompt(self._user_files)
        log_path = os.path.join(self._user_files, "assistant", "claude.log")
        return agent_host.AgentHost(
            binary,
            port=int(port or 0),
            token=str(token or ""),
            library_root=cfg.get("library_root") or None,
            system_prompt_path=sp_path,
            model=str(cfg.get("assistant_model") or ""),
            log_path=log_path,
            callbacks=callbacks,
        )

    # -- host lifecycle -------------------------------------------------------

    def _start_host(self) -> None:
        self._host = None
        callbacks = {
            "init": lambda payload: self._bridge.init.emit(payload if isinstance(payload, dict) else {}),
            "delta": lambda text: self._bridge.delta.emit(str(text or "")),
            "tool_use": lambda tid, name, inp: self._bridge.tool_use.emit(
                str(tid or ""), str(name or ""), inp if isinstance(inp, dict) else {}
            ),
            "tool_result": lambda tid, err: self._bridge.tool_result.emit(str(tid or ""), bool(err)),
            "result": lambda payload: self._bridge.result.emit(payload if isinstance(payload, dict) else {}),
            "permission_denied": lambda name: self._bridge.denied.emit(str(name or "")),
            "error": lambda msg: self._bridge.error.emit(str(msg or "")),
            "exited": lambda rc: self._bridge.exited.emit(rc),
        }
        try:
            self._host = self._host_factory(callbacks)
        except FileNotFoundError:
            self._show_empty_state()
            return
        except Exception as exc:
            print(f"[klausmate] assistant dock: host construction failed: {exc}")
            self._append_muted_line(f"could not start Claude Code: {exc}")
            return
        try:
            self._sessions.ensure_defaults(self._user_files)
        except Exception as exc:
            print(f"[klausmate] assistant dock: ensure_defaults failed: {exc}")

    def _show_empty_state(self) -> None:
        self._host = None
        try:
            self.transcript.setPlainText(EMPTY_STATE_TEXT)
            self.input.setEnabled(False)
            self.send_button.setEnabled(False)
            self.new_session_button.setEnabled(False)
            self.recheck_button.setVisible(True)
        except Exception as exc:
            print(f"[klausmate] assistant dock: empty state render failed: {exc}")

    def _on_recheck_clicked(self) -> None:
        try:
            self.input.setEnabled(True)
            self.send_button.setEnabled(True)
            self.new_session_button.setEnabled(True)
            self.recheck_button.setVisible(False)
            self.transcript.clear()
        except Exception:
            pass
        try:
            from . import agent_host

            # The whole point of Re-check is to look again, so the
            # profile-session cache (M12) must not answer for it.
            agent_host.clear_binary_cache()
        except Exception as exc:
            print(f"[klausmate] assistant dock: binary cache clear failed: {exc}")
        self._current_pdf_safe = _UNSET
        self._host_pdf_safe = _UNSET
        self._start_host()
        if self._host is not None:
            self._switch_session(self._current_view())

    # -- viewer following / sessions ------------------------------------------

    def _current_view(self) -> Any:
        try:
            from . import viewer_context

            return viewer_context.current()
        except Exception as exc:
            print(f"[klausmate] assistant dock: viewer_context read failed: {exc}")
            return None

    def _on_viewer_context_changed(self, view: Any) -> None:
        try:
            self._switch_session(view)
        except Exception as exc:
            print(f"[klausmate] assistant dock: session switch failed: {exc}")
        try:
            if self._scheduler is not None:
                self._scheduler.on_view(view)
        except Exception:
            pass

    def _pdf_key(self) -> Any:
        """The followed PDF as the sessions store spells it: ``None`` is
        the global (no-PDF) slot, and the ``_UNSET`` sentinel — "nothing
        looked at yet" — collapses to it."""
        return self._current_pdf_safe if self._current_pdf_safe is not _UNSET else None

    def _switch_session(self, view: Any) -> None:
        """Follow a new PDF: stop any running turn (without blocking),
        record the target, announce it. NO process is spawned here.

        Spawning eagerly on every switch cost a kill (a blocking
        ``proc.wait`` on the main thread) plus a fresh Node process for
        a PDF the user might never ask about — during review, once per
        card that changed lecture (final review I1). Claude Code emits
        nothing until the first message arrives, so an idle child does
        no work worth paying for; ``_ensure_child`` spawns on Send.
        """
        pdf_safe = getattr(view, "pdf_safe", "") or None
        if pdf_safe == self._current_pdf_safe:
            self._sync_header(view)
            return
        self._current_pdf_safe = pdf_safe
        if self._host is None:
            self._sync_header(view)
            return
        # Whatever child exists belongs to the OUTGOING PDF: end it and
        # forget it, so the next Send starts the incoming PDF's own.
        self._begin_async_stop()
        self._host_pdf_safe = _UNSET
        resumed = None
        try:
            resumed = self._sessions.session_for(self._user_files, pdf_safe)
        except Exception as exc:
            print(f"[klausmate] assistant dock: session_for failed: {exc}")
        try:
            self.transcript.clear()
        except Exception:
            pass
        display = getattr(view, "display", "") or pdf_safe or "your notes"
        self._append_muted_line(
            f"Resumed session for {display}" if resumed else f"New session for {display}"
        )
        self._set_running(False)
        self._sync_header(view)

    # -- child lifecycle: non-blocking stop, lazy start ------------------------

    def _host_alive(self) -> bool:
        try:
            return bool(getattr(self._host, "alive", False))
        except Exception:
            return False

    def _begin_async_stop(self) -> None:
        """SIGINT the child, then watch it die on a QTimer.

        ``AgentHost.stop()`` blocks up to STOP_GRACE_S on ``proc.wait``;
        this path runs inside viewer_context's notifier on the main
        thread, where that is a visible hitch (final review I1). Signal,
        return, and let ``_poll_stop`` do the reaping.
        """
        host = self._host
        if host is None:
            return
        try:
            if not getattr(host, "alive", False):
                return
        except Exception:
            return
        try:
            host.interrupt()
        except Exception as exc:
            print(f"[klausmate] assistant dock: interrupt failed: {exc}")
        self._set_running(False)
        self._stop_gen += 1
        gen = self._stop_gen
        try:
            import time as _time

            from . import agent_host

            self._stop_deadline = _time.monotonic() + agent_host.STOP_GRACE_S
        except Exception:
            self._stop_deadline = 0.0
        self._poll_stop(gen)

    def _poll_stop(self, gen: int) -> None:
        """One tick of the reap chain started by ``_begin_async_stop``.

        ``gen`` binds this chain to the child it was started for. A
        chain whose generation has been superseded — `_ensure_child`
        spawned a new child while the old one was still exiting, which
        happens whenever the user switches PDF and asks a question
        inside the outgoing child's ~0.6 s death window — stops here.
        Without the check, the stale chain reached its own grace expiry
        and called ``reap(force=True)`` on whatever `self._host._proc`
        had become by then, killing the NEW child about two seconds into
        its first turn (re-review NEW-1).
        """
        if gen != self._stop_gen:
            return
        host = self._host
        if host is None:
            return
        try:
            import time as _time

            expired = self._stop_deadline and _time.monotonic() >= self._stop_deadline
            if host.reap(force=bool(expired)):
                return
        except Exception as exc:
            print(f"[klausmate] assistant dock: reap failed: {exc}")
            return
        try:
            QTimer.singleShot(100, lambda: self._poll_stop(gen))
        except Exception as exc:
            print(f"[klausmate] assistant dock: stop poll timer failed: {exc}")

    def _ensure_child(self) -> bool:
        """A live child for the CURRENTLY followed PDF, spawning one if
        there isn't one — the whole of C1's fix.

        Called before every send. ``stop()``, a crash, a profile switch
        and a PDF switch all leave no usable child; each of them used to
        leave the dock permanently unable to send ("stdin write failed:
        Broken pipe") until New Session. Returns False when the spawn
        failed, with a line already in the transcript.
        """
        host = self._host
        if host is None:
            return False
        pdf = self._pdf_key()
        if self._host_alive() and self._host_pdf_safe == pdf:
            return True
        resumed = None
        try:
            resumed = self._sessions.session_for(self._user_files, pdf)
        except Exception as exc:
            print(f"[klausmate] assistant dock: session_for failed: {exc}")
        try:
            if resumed:
                host.start(resume=resumed)
            else:
                host.start()
        except Exception as exc:
            print(f"[klausmate] assistant dock: host start failed: {exc}")
            self._append_muted_line(f"could not start Claude Code: {exc}")
            self._set_running(False)  # M14: never strand the button on Stop
            self._host_pdf_safe = _UNSET
            return False
        # This child is NOT the one any pending reap chain was started
        # for. Bumping the generation is what stops that chain from
        # force-killing it at its own grace expiry (re-review NEW-1).
        self._stop_gen += 1
        self._stop_deadline = 0.0
        self._host_pdf_safe = pdf
        # Unproven until a turn completes: a session Claude Code no
        # longer has fails the moment it is resumed (probe: rc=1, "No
        # conversation found with session ID"), and a message-less
        # session is never persisted in the first place.
        self._resume_attempt = (pdf, resumed) if resumed else None
        self._init_seen = False
        return True

    def _forget_stale_resume(self) -> None:
        attempt, self._resume_attempt = self._resume_attempt, None
        if not attempt:
            return
        pdf, _sid = attempt
        try:
            self._sessions.forget(self._user_files, pdf)
        except Exception as exc:
            print(f"[klausmate] assistant dock: forget stale session failed: {exc}")
        self._host_pdf_safe = _UNSET
        self._append_muted_line(
            "That saved conversation is gone from Claude Code; "
            "the next message starts a new one."
        )

    def _sync_header(self, view: Any) -> None:
        try:
            if view is not None and getattr(view, "pdf_safe", ""):
                page = int(getattr(view, "page_index", 0)) + 1
                count = int(getattr(view, "page_count", 0))
                self.header.setText(f"Following: {view.display} · p. {page}/{count}")
            else:
                self.header.setText("No PDF in view")
            sel = (getattr(view, "selection", "") if view is not None else "") or ""
            sel = sel.strip()
            if sel:
                self.selection_chip.setText("selection: " + sel[:40])
                self.selection_chip.setVisible(True)
            else:
                self.selection_chip.setText("")
                self.selection_chip.setVisible(False)
        except Exception as exc:
            print(f"[klausmate] assistant dock: header sync failed: {exc}")

    # -- sending ---------------------------------------------------------------

    def _on_input_text_changed(self) -> None:
        try:
            text = self.input.toPlainText()
            cmds = commands_for_input(text, self._sessions, self._user_files)
            self._completer_model.setStringList(["/" + c for c in cmds])
            if cmds:
                self._completer.setCompletionPrefix(text)
                if self.input.hasFocus():
                    self._completer.complete()
            else:
                popup = self._completer.popup()
                if popup is not None:
                    popup.hide()
        except Exception as exc:
            print(f"[klausmate] assistant dock: completer update failed: {exc}")

    def _apply_completion(self, text: str) -> None:
        try:
            self.input.blockSignals(True)
            self.input.setPlainText(text + " ")
            self.input.blockSignals(False)
            cur = self.input.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            self.input.setTextCursor(cur)
        except Exception as exc:
            print(f"[klausmate] assistant dock: completion apply failed: {exc}")

    def eventFilter(self, obj: Any, event: Any) -> bool:
        try:
            if obj is self.input and event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        return False
                    self._do_send()
                    return True
        except Exception as exc:
            print(f"[klausmate] assistant dock: input event filter failed: {exc}")
        try:
            return super().eventFilter(obj, event)
        except Exception:
            return False

    def _on_send_button(self) -> None:
        if self._running:
            self._do_stop()
        else:
            self._do_send()

    def _do_send(self) -> None:
        if self._host is None or self._running:
            return
        raw = self.input.toPlainText()
        if not raw.strip():
            return
        view = self._current_view()
        try:
            page_ctx = self._context_provider(view)
        except Exception as exc:
            print(f"[klausmate] assistant dock: context provider failed: {exc}")
            page_ctx = None
        selection = (getattr(page_ctx, "selection", "") if page_ctx is not None else "") or \
            (getattr(view, "selection", "") or "")
        page_text = getattr(page_ctx, "text", "") if page_ctx is not None else ""
        text_source = getattr(page_ctx, "text_source", "none") if page_ctx is not None else "none"
        png = getattr(page_ctx, "png", None) if page_ctx is not None else None
        ctx_dict = {
            "selection": selection,
            "page_text": page_text,
            "pdf": getattr(view, "pdf_safe", "") or "",
        }
        try:
            text = self._sessions.expand(raw, self._user_files, ctx_dict)
        except Exception as exc:
            print(f"[klausmate] assistant dock: slash expand failed: {exc}")
            text = raw
        view_dict = None
        if view is not None and getattr(view, "pdf_safe", ""):
            view_dict = {
                "display": getattr(view, "display", ""),
                "pdf_safe": view.pdf_safe,
                "page_index": getattr(view, "page_index", 0),
                "page_count": getattr(view, "page_count", 0),
            }
        try:
            from . import agent_host

            block = agent_host.build_context_block(view_dict, page_text, text_source, selection)
            turn = agent_host.build_turn(text, block, png)
        except Exception as exc:
            print(f"[klausmate] assistant dock: build_turn failed: {exc}")
            self._append_muted_line(f"could not build the turn: {exc}")
            return
        # Spawn BEFORE the input is cleared: a failed start leaves the
        # user's words where they typed them (M18's other half).
        if not self._ensure_child():
            return
        self._append_user_line(raw)
        self.input.clear()
        self._sending_pdf_safe = self._pdf_key()  # I2: remembered under THIS pdf
        try:
            self._host.send(turn)
            self._set_running(True)
        except Exception as exc:
            print(f"[klausmate] assistant dock: send failed: {exc}")
            self._append_muted_line(f"send failed: {exc}")
            self._set_running(False)
            self._host_pdf_safe = _UNSET  # whatever went wrong, respawn next time
            try:
                self.input.setPlainText(raw)  # M18: never eat the question
            except Exception:
                pass

    def _do_stop(self) -> None:
        if self._host is None:
            return
        try:
            self._host.stop()
        except Exception as exc:
            print(f"[klausmate] assistant dock: stop failed: {exc}")
        # stop() leaves the child DEAD (SIGINT, 2 s grace, kill), so the
        # next Send must spawn a new one — that is C1, whose whole
        # user-visible symptom was "error: stdin write failed" forever
        # after the first Stop.
        self._host_pdf_safe = _UNSET
        self._set_running(False)

    def _on_new_session_clicked(self) -> None:
        if self._host is None:
            return
        pdf_safe = self._pdf_key()
        self._begin_async_stop()
        self._host_pdf_safe = _UNSET
        self._resume_attempt = None
        # Also forget the IN-FLIGHT turn (re-review NEW-3). New Session
        # mid-turn interrupts the child, but a `result` already on its
        # way would otherwise re-remember, under this very PDF, the
        # exact session id the user just asked to forget — and the next
        # Send would resume it. `_do_stop` deliberately does NOT do
        # this: remembering a stopped turn's session is the point there.
        self._sending_pdf_safe = _UNSET
        try:
            self._sessions.forget(self._user_files, pdf_safe)
        except Exception as exc:
            print(f"[klausmate] assistant dock: forget session failed: {exc}")
        try:
            self.transcript.clear()
        except Exception:
            pass
        view = self._current_view()
        display = getattr(view, "display", "") or pdf_safe or "your notes"
        self._append_muted_line(f"New session for {display}")
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self._running = running
        try:
            self.send_button.setText("Stop" if running else "Send")
        except Exception:
            pass
        self._set_status_dot("running" if running else "idle")

    def _set_status_dot(self, state: str, tooltip: str = "") -> None:
        colour_key = {"idle": "text_muted", "running": "blue", "error": "red"}.get(state, "text_muted")
        try:
            c = theme.palette(theme.night_mode())
            self.status_dot.setStyleSheet(f"color: {c.get(colour_key, c['text_muted'])};")
            self.status_dot.setToolTip(tooltip or self._mcp_tooltip)
        except Exception:
            pass

    # -- bridge slots (main thread only) ---------------------------------------

    def _on_init(self, payload: dict) -> None:
        # Deliberately does NOT remember the session id (final review
        # I2): `init` is delivered ~1 s after the send, through _Bridge,
        # so _current_pdf_safe may already name a different PDF by then
        # — and a session with no completed turn is never persisted by
        # Claude Code anyway, so an id remembered here is a stale id
        # waiting to fail. _on_result does it, keyed by the PDF the turn
        # was actually sent for. It IS the proof that a --resume was
        # accepted, though: a resume of a conversation Claude Code does
        # not have never gets this far, so _on_exited uses the flag to
        # tell a failed resume from an ordinary kill (NEW-2).
        self._init_seen = True
        mcp_ok = bool(payload.get("mcp_ok")) if isinstance(payload, dict) else False
        self._mcp_tooltip = "Anki tools: connected" if mcp_ok else "Anki tools unavailable"
        if not mcp_ok:
            self._append_muted_line("Anki tools are unavailable right now; chat still works.")
        self._set_status_dot("idle", self._mcp_tooltip)

    def _is_stale_turn(self) -> bool:
        """Does the in-flight turn belong to a PDF we no longer follow?

        The switch no longer blocks until the child is dead — that is
        the whole of I1 — so the reader thread keeps delivering the
        outgoing PDF's deltas and tool lines for the ~0.6 s after
        `transcript.clear()` and the "New session for <B>" line, and
        they rendered under B's header (re-review NEW-4). `_UNSET` means
        no turn is in flight, so a plain switch with nothing running is
        unaffected; a page change inside the same PDF does not move
        `_pdf_key()`, so an ordinary turn never trips this.

        Only the DISPLAY paths consult it. `result` must never be
        dropped: it carries the session bookkeeping, and I2 already
        keys that by `_sending_pdf_safe` rather than the current PDF.
        """
        return (self._sending_pdf_safe is not _UNSET
                and self._sending_pdf_safe != self._pdf_key())

    def _on_delta(self, text: str) -> None:
        if not text or self._is_stale_turn():
            return
        try:
            cur = self.transcript.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            if not self._assistant_block_open:
                if not self.transcript.document().isEmpty():
                    cur.insertBlock()
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(theme.palette(theme.night_mode())["text"]))
                cur.setCharFormat(fmt)
                self._assistant_block_open = True
                self._assistant_raw_start = cur.position()
                self._assistant_raw_text = ""
            cur.insertText(text)
            self._assistant_raw_text += text
            self.transcript.setTextCursor(cur)
        except Exception as exc:
            print(f"[klausmate] assistant dock: delta render failed: {exc}")

    def _close_assistant_block(self) -> None:
        if not self._assistant_block_open:
            return
        self._assistant_block_open = False
        raw, self._assistant_raw_text = self._assistant_raw_text, ""
        if not raw.strip():
            return
        try:
            cur = self.transcript.textCursor()
            cur.setPosition(self._assistant_raw_start)
            cur.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
            cur.insertHtml(render_markdown_lite(raw))
            self.transcript.setTextCursor(cur)
        except Exception as exc:
            print(f"[klausmate] assistant dock: markdown finalize failed: {exc}")

    def _on_tool_use(self, tool_use_id: str, name: str, tool_input: dict) -> None:
        if self._is_stale_turn():
            return
        try:
            fn = TOOL_LABELS.get(name)
            label = fn(tool_input or {}) if fn else f"used {name}"
        except Exception as exc:
            print(f"[klausmate] assistant dock: tool label failed: {exc}")
            label = name
        block = self._append_muted_line(f"▸ {label}")
        # Keyed by the tool_use id, never "the last line" (M4): Claude
        # Code batches parallel Read/Grep calls, and a batch's results
        # come back in whatever order they finish, so a positional
        # correlation decorates the wrong line.
        if tool_use_id:
            if len(self._tool_blocks) > 64:
                self._tool_blocks.clear()
            self._tool_blocks[tool_use_id] = block

    def _on_tool_result(self, tool_use_id: str, is_error: bool) -> None:
        # Popped either way, stale or not, so the id table cannot grow a
        # permanent entry for a line that was never rendered.
        block = self._tool_blocks.pop(tool_use_id, None) if tool_use_id else None
        if self._is_stale_turn():
            return
        if not is_error or block is None:
            return
        try:
            if not block.isValid():
                return
            cur = QTextCursor(block)
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cur.insertText(" — failed")
        except Exception as exc:
            print(f"[klausmate] assistant dock: tool result render failed: {exc}")

    def _on_result(self, payload: dict) -> None:
        try:
            self._close_assistant_block()
        except Exception:
            pass
        self._set_running(False)
        self._tool_blocks.clear()
        stale = False
        try:
            from . import agent_host

            stale = agent_host.resume_failed(payload if isinstance(payload, dict) else {})
        except Exception as exc:
            print(f"[klausmate] assistant dock: resume check failed: {exc}")
        if stale and self._resume_attempt:
            self._forget_stale_resume()
            self._sending_pdf_safe = _UNSET
            return
        # A COMPLETED turn is what makes a session id real (Claude Code
        # writes no transcript for a message-less session), and the PDF
        # it belongs to is the one the turn was SENT for — I2.
        try:
            sid = payload.get("session_id") if isinstance(payload, dict) else ""
            if sid and self._sending_pdf_safe is not _UNSET:
                self._sessions.remember(self._user_files, self._sending_pdf_safe, sid)
        except Exception as exc:
            print(f"[klausmate] assistant dock: remember session failed: {exc}")
        self._sending_pdf_safe = _UNSET
        try:
            if isinstance(payload, dict) and payload.get("is_error"):
                self._append_muted_line("The assistant turn ended with an error.")
            else:
                self._resume_attempt = None  # a clean turn proves the resume
        except Exception:
            pass

    def _on_denied(self, name: str) -> None:
        self._append_muted_line(f"Klaus declined to use {name}.")

    def _on_error(self, msg: str) -> None:
        self._append_muted_line(f"error: {msg}")
        self._set_running(False)
        self._set_status_dot("error", str(msg))

    def _on_exited(self, rc: Any) -> None:
        self._set_running(False)
        # There is no child any more, whatever the code: the next Send
        # spawns one (_ensure_child). Without this the dock stayed
        # wedged on "stdin write failed" until New Session — C1.
        self._host_pdf_safe = _UNSET
        self._sending_pdf_safe = _UNSET
        if rc not in (0, None):
            if self._resume_attempt and not self._init_seen:
                # A --resume that never got off the ground: it died
                # before Claude Code ever announced a session, which is
                # what a resume of a conversation it does not have does.
                # Drop the stale mapping so the next Send starts clean.
                self._forget_stale_resume()
            else:
                # `init` DID arrive, so Claude Code accepted the resume
                # and this is an ordinary death — a hard kill after
                # stop()'s grace, say. Forgetting here dropped a
                # perfectly good conversation and told the user it was
                # gone from Claude Code, which was simply untrue
                # (re-review NEW-2).
                self._append_muted_line(
                    f"Claude Code exited (code {rc}); the next message starts a fresh process."
                )
            self._set_status_dot("error")
        else:
            self._set_status_dot("idle")
        self._init_seen = False

    # -- transcript rendering helpers -------------------------------------------

    def _append_user_line(self, text: str) -> None:
        try:
            self._close_assistant_block()
            cur = self.transcript.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            if not self.transcript.document().isEmpty():
                cur.insertBlock()
            block_fmt = QTextBlockFormat()
            block_fmt.setAlignment(Qt.AlignmentFlag.AlignRight)
            cur.setBlockFormat(block_fmt)
            char_fmt = QTextCharFormat()
            char_fmt.setForeground(QColor(theme.palette(theme.night_mode())["text_muted"]))
            cur.setCharFormat(char_fmt)
            cur.insertText(text)
            self.transcript.setTextCursor(cur)
        except Exception as exc:
            print(f"[klausmate] assistant dock: user line render failed: {exc}")

    def _append_muted_line(self, text: str) -> Any:
        try:
            self._close_assistant_block()
            cur = self.transcript.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            if not self.transcript.document().isEmpty():
                cur.insertBlock()
            block_fmt = QTextBlockFormat()
            block_fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
            cur.setBlockFormat(block_fmt)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(theme.palette(theme.night_mode())["text_muted"]))
            cur.setCharFormat(fmt)
            cur.insertText(text)
            self.transcript.setTextCursor(cur)
            return cur.block()
        except Exception as exc:
            print(f"[klausmate] assistant dock: line render failed: {exc}")
            return None

    # -- width persistence -------------------------------------------------------

    def resizeEvent(self, event: Any) -> None:
        try:
            super().resizeEvent(event)
        except Exception:
            pass
        try:
            if self._width_save_timer is not None and self.isVisible() and self.width() > 80:
                self._width_save_timer.start(500)
        except Exception:
            pass

    def save_width(self) -> None:
        try:
            if self.width() > 80:
                self._write_width_config()
        except Exception:
            pass

    def _write_width_config(self) -> None:
        try:
            from aqt import mw as _mw

            cfg = _mw.addonManager.getConfig(__package__)
            if not isinstance(cfg, dict):
                return
            cfg["assistant_dock_width"] = int(self.width())
            _mw.addonManager.writeConfig(__package__, cfg)
        except Exception as exc:
            print(f"[klausmate] assistant dock: width save failed: {exc}")

    # -- lifecycle -----------------------------------------------------------------

    def shutdown(self) -> None:
        try:
            if self._unsub_viewer:
                self._unsub_viewer()
        except Exception:
            pass
        try:
            if self._host is not None:
                self._host.close()
        except Exception as exc:
            print(f"[klausmate] assistant dock: host close failed: {exc}")

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt naming
        try:
            self.save_width()
        except Exception:
            pass
        try:
            super().closeEvent(event)
        except Exception:
            pass


# ── aqt glue: module-level singleton + Tools/shortcut wiring ──────────────

_dock_instance: Any = None
_setup_done = False
_assistant_action: Any = None

# Ctrl+Shift+A — the assistant's original binding — collides with
# pdf_viewer.py's own Ctrl+Shift+A "highlight the current text selection"
# (a WidgetWithChildrenShortcut on the native QPdfView pane): an offscreen
# repro with real widgets confirmed that with a PDF pane focused (the
# Lecture-dock shape or the embedded-Library shape — the two places this
# assistant is actually meant to be used from), Ctrl+Shift+A never reaches
# the assistant at all (the viewer's ShortcutOverride claims it outright,
# ahead of Qt's shortcut map), while Ctrl+Shift+K fires cleanly and leaves
# the viewer untouched. Ruled 2026-09-02 (spec §9, commit ca2d30c).
_ASSISTANT_SHORTCUT = "Ctrl+Shift+K"


def _dock() -> Any:
    return _dock_instance


def _ensure_dock() -> Any:
    global _dock_instance
    if _dock_instance is not None:
        return _dock_instance
    if mw is None or QDockWidget is None:
        return None
    try:
        _dock_instance = AssistantDock(mw)
    except Exception as exc:
        print(f"[klausmate] assistant dock: construction failed: {exc}")
        return None
    try:
        mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _dock_instance)
        cfg = mw.addonManager.getConfig(__package__) or {}
        width = int(cfg.get("assistant_dock_width") or 420)
        QTimer.singleShot(
            0,
            lambda: mw.resizeDocks([_dock_instance], [max(280, width)], Qt.Orientation.Horizontal),
        )
    except Exception as exc:
        print(f"[klausmate] assistant dock install failed: {exc}")
    return _dock_instance


def _write_open_flag(is_open: bool) -> None:
    """Remember whether the dock was open, so ``assistant_reopen`` has
    something to reopen (final review I7: the preference was written by
    Preferences and read by nobody). Written on the user's own open/
    close only — never by profile teardown, which is not a decision the
    user made about next time."""
    try:
        cfg = mw.addonManager.getConfig(__package__)
        if not isinstance(cfg, dict):
            return
        if bool(cfg.get("assistant_dock_open")) == bool(is_open):
            return
        cfg["assistant_dock_open"] = bool(is_open)
        mw.addonManager.writeConfig(__package__, cfg)
    except Exception as exc:
        print(f"[klausmate] assistant open-state save failed: {exc}")


def open_assistant() -> None:
    dock = _ensure_dock()
    if dock is None:
        return
    try:
        dock.show()
        dock.raise_()  # never activateWindow(): the viewer keeps keyboard focus
    except Exception as exc:
        print(f"[klausmate] assistant open failed: {exc}")
    _write_open_flag(True)


def close_assistant() -> None:
    if _dock_instance is None:
        return
    try:
        _dock_instance.save_width()
        _dock_instance.hide()
    except Exception as exc:
        print(f"[klausmate] assistant close failed: {exc}")
    _write_open_flag(False)


def reopen_if_configured() -> None:
    """``assistant_reopen`` honoured on profile open (spec §8/§9).

    Deferred one tick: profile_did_open also starts the endpoint the
    dock's child talks to (``__init__._start_assistant_endpoint``), and
    a dock built before that bind would construct its host with port 0
    and report "Anki tools unavailable" for the whole session.
    """
    try:
        cfg = mw.addonManager.getConfig(__package__) or {}
    except Exception as exc:
        print(f"[klausmate] assistant reopen: config read failed: {exc}")
        return
    if not cfg.get("assistant_reopen") or not cfg.get("assistant_dock_open"):
        return
    try:
        QTimer.singleShot(0, open_assistant)
    except Exception as exc:
        print(f"[klausmate] assistant reopen failed: {exc}")


def toggle_assistant() -> None:
    if _dock_instance is not None and _dock_instance.isVisible():
        close_assistant()
    else:
        open_assistant()


def _teardown() -> None:
    global _dock_instance
    dock, _dock_instance = _dock_instance, None
    if dock is None:
        return
    try:
        dock.save_width()
        dock.shutdown()
        try:
            mw.removeDockWidget(dock)
        except Exception:
            pass
        dock.deleteLater()
    except RuntimeError:
        pass  # C++ side already gone
    except Exception as exc:
        print(f"[klausmate] assistant teardown failed: {exc}")


def menu_action() -> Any:
    """The one QAction carrying the assistant's shortcut — Task 11's Tools
    menu entry IS this object (``menu.addAction(menu_action())``), never a
    second QAction/QShortcut on the same chord. ``None`` before ``setup()``
    has run (or when Qt is unavailable)."""
    return _assistant_action


def _shortcut_already_bound(host: Any, want: Any) -> bool:
    """One-time diagnostic scan of ``host`` (``mw``) for an existing
    QAction or QShortcut already carrying ``want``. This is NOT a
    collision-avoidance gate — unlike the retired
    ``state_shortcuts_will_change`` scan, there is no shared list to steer
    around here, only mw's own actions/shortcuts — so it can only ever
    LOG a finding, never skip registration (skipping would leave the
    assistant with no shortcut at all, strictly worse)."""
    try:
        for act in host.actions():
            if act.shortcut() == want:
                return True
        for sc in host.findChildren(QShortcut):
            if sc.key() == want:
                return True
    except Exception as exc:
        print(f"[klausmate] assistant: shortcut collision scan failed: {exc}")
    return False


def _install_shortcut() -> None:
    """One window-scoped QAction on mw, added once. Replaces the retired
    ``state_shortcuts_will_change`` registration: per the collision
    session's static check of Anki's own shipped code, that hook fires
    only from ``Overview.show``/``Reviewer.show`` — never the deck browser,
    and never ``library_tab.mount()``'s embedded-screen path, which never
    touches ``mw.state`` at all. A plain ``QAction`` with
    ``WindowShortcut`` context is live in every one of those, including
    the two places this assistant is actually meant to be used from."""
    global _assistant_action
    if _assistant_action is not None or mw is None or QAction is None:
        return
    want = QKeySequence(_ASSISTANT_SHORTCUT)
    if _shortcut_already_bound(mw, want):
        print(f"[klausmate] assistant: {_ASSISTANT_SHORTCUT} already bound on mw")
    action = QAction("Klaus Assistant", mw)
    action.setShortcut(want)
    action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    action.triggered.connect(lambda checked=False: toggle_assistant())
    mw.addAction(action)
    _assistant_action = action


def setup() -> None:
    global _setup_done
    if _setup_done or gui_hooks is None or mw is None:
        return
    _setup_done = True
    try:
        _install_shortcut()
    except Exception as exc:
        print(f"[klausmate] assistant: shortcut registration failed: {exc}")
    try:
        gui_hooks.profile_will_close.append(_teardown)
    except Exception as exc:
        print(f"[klausmate] assistant hook failed: {type(exc).__name__}: {exc}")
    try:
        gui_hooks.profile_did_open.append(reopen_if_configured)
    except Exception as exc:
        print(f"[klausmate] assistant reopen hook failed: {type(exc).__name__}: {exc}")
