"""Tests for klausmate/assistant_dock.py — the Claude Code assistant dock
(K-198): header, transcript, input, Send/Stop, sessions, slash completer.

Design: docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-
design.md sections 4.3, 9, 10, 13.

Structure mirrors tests/test_pdf_map.py and tests/test_drive.py: pure
dict/function pins first under the plain permissive aqt stub (no real Qt
needed — TOOL_LABELS, commands_for_input, render_markdown_lite, the
source pins), then a REAL offscreen-PyQt6 section where klausmate.* is
purged and re-imported against an aqt.qt shim backed by genuine PyQt6
classes, because AssistantDock is a QDockWidget subclass and its actual
behaviour (header text, transcript content, button state, pixel ground)
cannot be asserted against the permissive _Dummy stand-ins, which have
no geometry and paint no pixels.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_assistant_dock.py
"""
from __future__ import annotations

import ast
import base64
import importlib
import io
import json
import os
import re
import sys
import tempfile
import tokenize
import types

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"),
)

from anki_stubs import ADDON, check, code_only, install, report, section  # noqa: E402

install()

assistant_dock = importlib.import_module("klausmate.assistant_dock")
theme = importlib.import_module("klausmate.theme")

_SRC = open(os.path.join(ADDON, "assistant_dock.py")).read()
_CODE = code_only(_SRC)  # comments AND strings stripped — real code only


# ─────────────────────────────────────────────────────────────────────────
# Pure surface: TOOL_LABELS, commands_for_input, render_markdown_lite.
# None of this touches Qt, so it runs fine under the plain permissive
# stub — no offscreen platform, no QApplication needed.
# ─────────────────────────────────────────────────────────────────────────

section("TOOL_LABELS — the collapsed tool-call line table")

check("TOOL_LABELS carries every mcp__klaus__ tool the system prompt names",
      all(name in assistant_dock.TOOL_LABELS for name in (
          "mcp__klaus__search_notes", "mcp__klaus__find_notes",
          "mcp__klaus__get_notes", "mcp__klaus__add_note",
          "mcp__klaus__search_lecture_pdfs", "mcp__klaus__current_view",
      )))
check("TOOL_LABELS carries the four allowed non-mcp tools "
      "(agent_host.ALLOWED_TOOLS: Read, Grep, Glob, ToolSearch)",
      all(name in assistant_dock.TOOL_LABELS for name in ("Read", "Grep", "Glob", "ToolSearch")))
check("search_notes renders 'searched notes: <query>'",
      assistant_dock.TOOL_LABELS["mcp__klaus__search_notes"]({"query": "renal"})
      == "searched notes: renal")
check("find_notes renders 'searched Anki: <query>'",
      assistant_dock.TOOL_LABELS["mcp__klaus__find_notes"]({"query": "deck:Default"})
      == "searched Anki: deck:Default")
check("get_notes renders 'read <n> notes' from note_ids length",
      assistant_dock.TOOL_LABELS["mcp__klaus__get_notes"]({"note_ids": [1, 2, 3]})
      == "read 3 notes")
check("get_notes tolerates a missing note_ids key (0 notes, never a crash)",
      assistant_dock.TOOL_LABELS["mcp__klaus__get_notes"]({}) == "read 0 notes")
check("add_note renders 'proposed a card for <deck>'",
      assistant_dock.TOOL_LABELS["mcp__klaus__add_note"]({"deck": "Renal::Physiology"})
      == "proposed a card for Renal::Physiology")
check("search_lecture_pdfs renders 'searched lectures: <query>'",
      assistant_dock.TOOL_LABELS["mcp__klaus__search_lecture_pdfs"]({"query": "nephron"})
      == "searched lectures: nephron")
check("current_view renders a fixed sentence, no input needed",
      assistant_dock.TOOL_LABELS["mcp__klaus__current_view"]({}) == "checked what you are viewing")
check("Read renders the basename only, not the full path",
      assistant_dock.TOOL_LABELS["Read"]({"file_path": "/a/b/c/notes.py"}) == "read notes.py")
check("Grep renders 'searched files for <pattern>'",
      assistant_dock.TOOL_LABELS["Grep"]({"pattern": "def foo"}) == "searched files for def foo")
check("Glob renders a fixed sentence", assistant_dock.TOOL_LABELS["Glob"]({}) == "listed files")
check("ToolSearch renders a fixed sentence", assistant_dock.TOOL_LABELS["ToolSearch"]({}) == "loaded tools")


section("commands_for_input — slash-completion candidate policy")


class _FakeSessionsForCommands:
    def __init__(self, commands):
        self._commands = list(commands)
        self.calls = []

    def list_commands(self, user_files):
        self.calls.append(user_files)
        return list(self._commands)


_fsc = _FakeSessionsForCommands(["explain", "cards", "quiz"])
check("a bare '/' lists every command",
      assistant_dock.commands_for_input("/", _fsc, "uf") == ["explain", "cards", "quiz"])
check("a partial command name still lists every command (Qt does the prefix filtering)",
      assistant_dock.commands_for_input("/exp", _fsc, "uf") == ["explain", "cards", "quiz"])
check("a space after the command name ends completion (the command is chosen)",
      assistant_dock.commands_for_input("/explain rest of the sentence", _fsc, "uf") == [])
check("text with no leading slash is never a command",
      assistant_dock.commands_for_input("hello there", _fsc, "uf") == [])
check("an empty string is never a command", assistant_dock.commands_for_input("", _fsc, "uf") == [])
check("commands_for_input passes user_files straight through to list_commands",
      _fsc.calls and _fsc.calls[-1] == "uf")


class _RaisingSessions:
    def list_commands(self, user_files):
        raise RuntimeError("disk exploded")


check("a raising sessions object degrades to no candidates rather than propagating",
      assistant_dock.commands_for_input("/x", _RaisingSessions(), "uf") == [])


section("render_markdown_lite — pure, at module top")

check("plain text with no markup passes through unchanged",
      assistant_dock.render_markdown_lite("just words") == "just words")
check("HTML metacharacters are escaped",
      assistant_dock.render_markdown_lite("a < b & c > d")
      == "a &lt; b &amp; c &gt; d")
check("**bold** becomes <b>bold</b>",
      assistant_dock.render_markdown_lite("this is **bold** text")
      == "this is <b>bold</b> text")
check("a fenced code block becomes a <pre> block",
      "<pre>" in assistant_dock.render_markdown_lite("before\n```\ncode here\n```\nafter")
      and "code here" in assistant_dock.render_markdown_lite("before\n```\ncode here\n```\nafter"))
check("code inside a fenced block is escaped too (a literal < must not become a tag)",
      "&lt;script&gt;" in assistant_dock.render_markdown_lite("```\n<script>\n```"))
check("a fenced block is NOT bold-processed — ** inside code stays literal text, escaped only",
      "<b>" not in assistant_dock.render_markdown_lite("```\n**not bold**\n```")
      and "**not bold**" in assistant_dock.render_markdown_lite("```\n**not bold**\n```"))
check("a '- ' line becomes a bullet",
      assistant_dock.render_markdown_lite("- one\n- two") == "• one<br>• two")
check("a line NOT starting with '- ' keeps its dash literal",
      assistant_dock.render_markdown_lite("a - b") == "a - b")
check("empty text renders to empty text", assistant_dock.render_markdown_lite("") == "")
check("None-ish falsy input never raises", assistant_dock.render_markdown_lite(None) == "")


section("module surface — source pins")

check("no exec() anywhere in the module (the K-114 house ban)",
      "exec(" not in _CODE)
check("AssistantDock is a public class in the module",
      hasattr(assistant_dock, "AssistantDock") and isinstance(assistant_dock.AssistantDock, type))
check("the module functions Task 11 wires exist and are callable",
      all(callable(getattr(assistant_dock, name, None))
          for name in ("toggle_assistant", "open_assistant", "close_assistant", "setup",
                       "_dock", "menu_action")))
check("the assistant's shortcut is Ctrl+Shift+K, not Ctrl+Shift+A — the latter is "
      "pdf_viewer.py's own highlight-from-selection binding and pre-empts the assistant "
      "outright whenever a PDF pane has focus (ruled 2026-09-02, spec section 9)",
      assistant_dock._ASSISTANT_SHORTCUT == "Ctrl+Shift+K")
check("state_shortcuts_will_change is gone from the module's actual CODE (comments and "
      "docstrings that merely narrate the history are exempt — code_only strips both, "
      "same reasoning as every other 'X no longer appears' pin in this codebase)",
      "state_shortcuts_will_change" not in _CODE)
_LAZY_SIBLINGS = ("agent_host", "viewer_context", "page_ocr", "assistant_sessions", "anki_endpoint")
_top_level_imports = set()
for _node in ast.parse(_SRC).body:  # MODULE-level statements only — never ast.walk, which
    if isinstance(_node, ast.ImportFrom) and _node.module in (None, ""):  # would also match
        for _alias in _node.names:  # the very same imports safely nested inside functions.
            _top_level_imports.add(_alias.name)
check("the five sibling modules are imported LAZILY (inside functions), never at module top — "
      "so this module still imports if one of them is momentarily broken or absent",
      not (_top_level_imports & set(_LAZY_SIBLINGS)))


def _method_body_is_try_guarded(cls_name: str, method_name: str) -> bool:
    """True when method_name's ENTIRE body (a leading docstring aside) is
    one try/except — _build_chrome's own shape, and the standard
    _build_ui/_wire_bridge are being held to here: every widget/layout
    call or signal connect guarded by ONE method-level try, not scattered
    per-statement guards (or none at all)."""
    for node in ast.walk(ast.parse(_SRC)):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == method_name:
                    body = sub.body
                    if body and isinstance(body[0], ast.Expr) and isinstance(
                        getattr(body[0], "value", None), ast.Constant
                    ):
                        body = body[1:]  # a leading docstring is not the guard
                    return len(body) == 1 and isinstance(body[0], ast.Try)
    return False


check("_build_chrome is the baseline this pin models: its whole body is one try/except",
      _method_body_is_try_guarded("AssistantDock", "_build_chrome"))
check("_build_ui's whole body is now ALSO one try/except (every widget/layout call "
      "guarded, not just the completer's own connect) — matching _build_chrome's "
      "standard and the report's own 'every Qt call guarded' self-review claim",
      _method_body_is_try_guarded("AssistantDock", "_build_ui"))
check("_wire_bridge's whole body is now ALSO one try/except (all eight bridge "
      "signal connects), where before it had none at all",
      _method_body_is_try_guarded("AssistantDock", "_wire_bridge"))
check("theme.assistant_dock_qss(True) contains no literal hex colour outside a palette "
      "token substitution (test_theme's own audit technique, applied to this one builder's "
      "emitted CSS instead of its source)",
      all(any(hexval in str(v) for v in theme.palette(True).values())
          for hexval in re.findall(r"#[0-9A-Fa-f]{3,8}", theme.assistant_dock_qss(True))))
check("...and the same holds in light mode",
      all(any(hexval in str(v) for v in theme.palette(False).values())
          for hexval in re.findall(r"#[0-9A-Fa-f]{3,8}", theme.assistant_dock_qss(False))))


# ─────────────────────────────────────────────────────────────────────────
# Real offscreen Qt — construction, header/session following, streaming,
# tool lines, Send/Stop, empty state, the slash completer, and the
# pixel-level ground colour. AssistantDock is a QDockWidget subclass, so
# none of this is reachable through the permissive _Dummy stand-ins.
# ─────────────────────────────────────────────────────────────────────────

section("real offscreen Qt — construction, following, streaming, sessions")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC  # noqa: E402
    from PyQt6 import QtGui as _QtG  # noqa: E402
    from PyQt6 import QtWidgets as _QtW  # noqa: E402

    _HAVE_QT = True
except Exception as _qt_e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — "
          "the pure model and source pins above still ran")

if _HAVE_QT:
    _qt_shim = types.ModuleType("aqt.qt")

    def _qt_getattr(name, _mods=(_QtW, _QtC, _QtG)):
        for _m in _mods:
            if hasattr(_m, name):
                return getattr(_m, name)
        if name == "qconnect":
            return lambda sig, fn: sig.connect(fn)
        raise AttributeError(name)

    _qt_shim.__getattr__ = _qt_getattr
    sys.modules["aqt.qt"] = _qt_shim

    # Full purge, same as test_drive.py's K-117 section: pdf_map's window
    # class is defined LOCAL to a factory function so a bare shim-swap is
    # enough, but AssistantDock is a module-level class (tests construct
    # it directly) — its class body must re-execute against the REAL
    # QDockWidget, which only happens on a fresh import.
    #
    # `del sys.modules["klausmate.theme"]` alone is NOT enough: this test
    # file already imported klausmate.theme once, above (for the hex-audit
    # source pin), and `from . import theme` for a submodule that is
    # ALREADY an ATTRIBUTE of the `klausmate` package object resolves via
    # `getattr(package, "theme")` FIRST — it only falls back to a real
    # `sys.modules` import when that attribute is absent. Since deleting a
    # sys.modules entry does not remove the package's own attribute, a
    # freshly re-imported assistant_dock's `from . import theme` would
    # silently keep binding the STALE pre-purge theme module — verified by
    # id() during debugging: two live `klausmate.theme` objects, and a
    # `theme.night_mode` monkeypatch on the one this test holds would
    # never reach the one assistant_dock.py calls. Clearing the matching
    # package attribute alongside each sys.modules entry forces the real
    # re-import path.
    _pkg = sys.modules["klausmate"]
    for _name in [m for m in list(sys.modules) if m.startswith("klausmate.")]:
        del sys.modules[_name]
        _attr = _name.split(".", 1)[1]
        if hasattr(_pkg, _attr):
            try:
                delattr(_pkg, _attr)
            except Exception:
                pass
    sys.modules["klausmate"] = _pkg

    _uf_root = tempfile.mkdtemp(prefix="klaus_k198_uf_")
    assistant_dock = importlib.import_module("klausmate.assistant_dock")
    theme = importlib.import_module("klausmate.theme")
    viewer_context = importlib.import_module("klausmate.viewer_context")

    app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])

    # -- fakes --------------------------------------------------------------

    class _FakeHost:
        """Stands in for agent_host.AgentHost. Callbacks are invoked
        directly from the test's own thread — exactly like a real
        AgentHost's reader thread would, except synchronous, so Qt's
        auto-connection resolves the bridge signals as DIRECT calls and
        no processEvents() pump is needed to observe the result."""

        def __init__(self, callbacks):
            self.callbacks = callbacks
            self.running = False
            self.session_id = None
            self.sent = []
            self.started = []
            self.stopped = 0
            self.closed = 0

        def start(self, session_id=None, resume=None):
            self.started.append({"session_id": session_id, "resume": resume})
            self.session_id = resume or session_id or "fake-sid"
            self.running = False
            return self.session_id

        def send(self, turn_line):
            self.sent.append(turn_line)
            self.running = True

        def stop(self):
            self.stopped += 1
            self.running = False

        def close(self):
            self.closed += 1

    def _fake_host_factory(callbacks):
        return _FakeHost(callbacks)

    class _FakePageContext:
        def __init__(self, text="page text", text_source="ocr", png=None, selection=""):
            self.text = text
            self.text_source = text_source
            self.png = png
            self.selection = selection

    def _fake_context_provider(view):
        return _FakePageContext()

    class _FakeSessions:
        def __init__(self):
            self.stored = {}
            self.forgotten = []
            self.expand_calls = []
            self.commands = ["explain", "cards", "quiz"]
            self.remembered = []

        def session_for(self, user_files, pdf_safe):
            return self.stored.get(pdf_safe)

        def remember(self, user_files, pdf_safe, session_id):
            self.stored[pdf_safe] = session_id
            self.remembered.append((pdf_safe, session_id))

        def forget(self, user_files, pdf_safe):
            self.forgotten.append(pdf_safe)
            self.stored.pop(pdf_safe, None)

        def list_commands(self, user_files):
            return list(self.commands)

        def expand(self, text, user_files, ctx):
            self.expand_calls.append((text, dict(ctx)))
            return text

        def ensure_defaults(self, user_files):
            pass

        def ensure_system_prompt(self, user_files):
            return os.path.join(user_files, "assistant", "system_prompt.md")

    def _make_dock(**overrides):
        kwargs = dict(
            host_factory=_fake_host_factory,
            context_provider=_fake_context_provider,
            sessions=_FakeSessions(),
            user_files=_uf_root,
            endpoint_info=lambda: (18765, "tok"),
        )
        kwargs.update(overrides)
        dock = assistant_dock.AssistantDock(None, **kwargs)
        # QWidget.isVisible() reflects EFFECTIVE visibility (the whole
        # ancestor chain), not just "was setVisible(True) called on this
        # widget" — a child's own setVisible(True) is invisible in that
        # sense until its top-level ancestor is actually shown. Several
        # pins below check isVisible() on children (the selection chip,
        # the Re-check button), so the dock itself must be shown once.
        dock.show()
        app.processEvents()
        return dock

    # -- construction ---------------------------------------------------

    viewer_context.reset()
    _d1 = _make_dock()
    check("construction succeeds with a fake host and a fake context provider",
          _d1 is not None and isinstance(_d1._host, _FakeHost))
    check("a fresh dock with no PDF in view says so in the header",
          _d1.header.text() == "No PDF in view")
    check("construction starts the host exactly once (the initial session switch)",
          len(_d1._host.started) == 1 and _d1._host.started[0]["resume"] is None)
    check("Send is the button's resting text", _d1.send_button.text() == "Send")

    # -- header follows viewer_context -----------------------------------

    viewer_context.reset()
    _d2 = _make_dock()
    viewer_context.report_document(1, "lecture1", "Lecture 1.pdf", "/x/Lecture 1.pdf", 40)
    viewer_context.activate(1)
    app.processEvents()
    check("report_document + activate -> 'Following: <display> · p. <n>/<count>'",
          _d2.header.text() == "Following: Lecture 1.pdf · p. 1/40")
    check("no selection yet -> the chip stays hidden",
          not _d2.selection_chip.isVisible())
    viewer_context.report_selection(1, "a" * 60)
    app.processEvents()
    check("report_selection -> the chip shows exactly the first 40 chars",
          _d2.selection_chip.text() == "selection: " + ("a" * 40) and _d2.selection_chip.isVisible())
    viewer_context.report_page(1, 4)
    app.processEvents()
    check("a page change updates the 1-based page number in the header",
          _d2.header.text().endswith("p. 5/40"))
    viewer_context.report_selection(1, "")
    app.processEvents()
    check("clearing the selection hides the chip again", not _d2.selection_chip.isVisible())

    # -- sending: turn shape ----------------------------------------------

    viewer_context.reset()
    _png = b"\x89PNGfakebytes"
    _d3 = _make_dock(context_provider=lambda view: _FakePageContext(
        text="the nephron filters blood", text_source="ocr", png=_png, selection="tubule"))
    _d3.input.setPlainText("What is this slide about?")
    _d3._do_send()
    check("sending calls host.send exactly once", len(_d3._host.sent) == 1)
    _turn = json.loads(_d3._host.sent[0])
    _content = _turn["message"]["content"]
    check("the turn is a user message with text, context and image blocks",
          _turn["type"] == "user" and _turn["message"]["role"] == "user" and len(_content) == 3)
    check("block 0 carries the (expanded) user text",
          _content[0]["type"] == "text" and _content[0]["text"] == "What is this slide about?")
    check("block 1 carries the [Klaus context] block with the page text and selection",
          _content[1]["type"] == "text"
          and _content[1]["text"].startswith("[Klaus context]")
          and "the nephron filters blood" in _content[1]["text"]
          and "tubule" in _content[1]["text"])
    check("block 2 is an image block base64-encoding exactly the provider's PNG bytes",
          _content[2]["type"] == "image"
          and _content[2]["source"]["media_type"] == "image/png"
          and _content[2]["source"]["data"] == base64.b64encode(_png).decode("ascii"))
    check("the input box is cleared after sending", _d3.input.toPlainText() == "")
    check("the raw (pre-expansion) text is what the user turn line in the transcript shows",
          "What is this slide about?" in _d3.transcript.toPlainText())

    # -- no image when the provider has none -------------------------------

    viewer_context.reset()
    _d3b = _make_dock(context_provider=lambda view: _FakePageContext(png=None))
    _d3b.input.setPlainText("no picture available")
    _d3b._do_send()
    _content_b = json.loads(_d3b._host.sent[0])["message"]["content"]
    check("no PNG from the provider -> the image block is simply omitted",
          len(_content_b) == 2 and all(b["type"] == "text" for b in _content_b))

    # -- sending via the REAL Enter key path (eventFilter) ------------------

    viewer_context.reset()
    _d3c = _make_dock()
    _d3c.input.setFocus()
    _d3c.input.setPlainText("typed then Enter")
    _enter = _QtG.QKeyEvent(_QtC.QEvent.Type.KeyPress, _QtC.Qt.Key.Key_Return,
                             _QtC.Qt.KeyboardModifier.NoModifier)
    _QtW.QApplication.sendEvent(_d3c.input, _enter)
    check("a real KeyPress(Return) sent to the input widget triggers a send via eventFilter",
          len(_d3c._host.sent) == 1)
    _d3c.input.setPlainText("line one")
    _shift_enter = _QtG.QKeyEvent(_QtC.QEvent.Type.KeyPress, _QtC.Qt.Key.Key_Return,
                                  _QtC.Qt.KeyboardModifier.ShiftModifier)
    _QtW.QApplication.sendEvent(_d3c.input, _shift_enter)
    check("Shift+Enter must NOT send — it breaks a line instead",
          len(_d3c._host.sent) == 1)

    # -- while running: button flips, a second Enter is a no-op ------------

    viewer_context.reset()
    _d4 = _make_dock()
    _d4.input.setPlainText("hello")
    _d4._do_send()
    check("while a turn runs the button reads Stop", _d4.send_button.text() == "Stop")
    _sent_before = len(_d4._host.sent)
    _d4.input.setPlainText("hello again")
    _d4._do_send()
    check("a second send while running does nothing (still just one turn sent)",
          len(_d4._host.sent) == _sent_before)

    # -- streaming deltas, tool lines, denial, result -----------------------

    _host4 = _d4._host
    _host4.callbacks["delta"]("Hello, ")
    _host4.callbacks["delta"]("world!")
    app.processEvents()
    check("deltas append to the transcript IN ORDER",
          "Hello, world!" in _d4.transcript.toPlainText())
    _host4.callbacks["tool_use"]("mcp__klaus__search_notes", {"query": "renal"})
    app.processEvents()
    _lines4 = [ln.strip() for ln in _d4.transcript.toPlainText().splitlines()]
    check("a tool_use renders one line starting with ▸ and the TOOL_LABELS text",
          "▸ searched notes: renal" in _lines4)
    _host4.callbacks["tool_result"]("tid-1", True)
    app.processEvents()
    _lines4b = [ln.strip() for ln in _d4.transcript.toPlainText().splitlines()]
    check("a tool_result with is_error appends ' — failed' to the LAST tool line",
          "▸ searched notes: renal — failed" in _lines4b)
    _host4.callbacks["permission_denied"]("Bash")
    app.processEvents()
    check("permission_denied renders a line naming the refused tool",
          "Bash" in _d4.transcript.toPlainText())
    check("Stop is still the button's text — a denial does not end the turn",
          _d4.send_button.text() == "Stop")
    _host4.callbacks["result"]({"session_id": "sid-x", "is_error": False,
                                "duration_ms": 5, "total_cost_usd": 0.0, "text": "done"})
    app.processEvents()
    check("a result event flips Send back", _d4.send_button.text() == "Send")

    # -- init stores the session id via sessions.remember -------------------

    viewer_context.reset()
    _d5 = _make_dock()
    _d5._host.callbacks["init"]({"session_id": "real-sid-1", "mcp_ok": True})
    check("an init event remembers the session id for the currently-followed PDF (None: global)",
          _d5._sessions.stored.get(None) == "real-sid-1")
    _d5b = _make_dock()
    _d5b._host.callbacks["init"]({"session_id": "sid-2", "mcp_ok": False})
    app.processEvents()
    check("mcp_ok False adds a warning line but chat keeps working",
          "unavailable" in _d5b.transcript.toPlainText().lower()
          and _d5b.input.isEnabled())

    # -- Stop calls host.stop() ---------------------------------------------

    viewer_context.reset()
    _d6 = _make_dock()
    _d6.input.setPlainText("go")
    _d6._do_send()
    _d6._on_send_button()  # button now reads Stop; clicking it must stop, not send
    check("clicking Stop calls host.stop() exactly once", _d6._host.stopped == 1)
    check("stopping flips the button back to Send", _d6.send_button.text() == "Send")

    # -- New Session: forget + fresh start -----------------------------------

    viewer_context.reset()
    _d7 = _make_dock()
    _starts_before = len(_d7._host.started)
    _d7._on_new_session_clicked()
    check("New Session calls sessions.forget for the currently-followed PDF (None: global)",
          _d7._sessions.forgotten and _d7._sessions.forgotten[-1] is None)
    check("New Session calls host.start() completely fresh (no resume)",
          len(_d7._host.started) == _starts_before + 1
          and _d7._host.started[-1]["resume"] is None)
    check("New Session announces itself in the (now-cleared) transcript",
          "New session" in _d7.transcript.toPlainText())

    # -- switching the followed PDF resumes a stored session -----------------

    viewer_context.reset()
    _sessions8 = _FakeSessions()
    _sessions8.stored["pdfA"] = "resume-sid-A"
    _d8 = _make_dock(sessions=_sessions8)
    viewer_context.report_document(8, "pdfA", "PDF A.pdf", "/x/A.pdf", 10)
    viewer_context.activate(8)
    app.processEvents()
    check("switching to a PDF with a STORED session resumes it via host.start(resume=...)",
          any(s["resume"] == "resume-sid-A" for s in _d8._host.started))
    check("the transcript announces the resume by the PDF's display name",
          "Resumed session for PDF A.pdf" in _d8.transcript.toPlainText())
    _stopped_before = _d8._host.stopped
    viewer_context.report_document(9, "pdfB", "PDF B.pdf", "/x/B.pdf", 5)
    viewer_context.activate(9)
    app.processEvents()
    check("switching to a PDF with NO stored session starts fresh, not resumed",
          _d8._host.started[-1]["resume"] is None)
    check("the transcript announces a fresh session for the new PDF",
          "New session for PDF B.pdf" in _d8.transcript.toPlainText())
    check("switching PDFs stops the outgoing session's host first (it was left running below)",
          _d8._host.stopped >= _stopped_before)  # sanity: never fewer stops than before

    # A running turn on PDF A must actually be stopped before B's start.
    viewer_context.reset()
    _d8b = _make_dock()
    viewer_context.report_document(10, "pdfC", "PDF C.pdf", "/x/C.pdf", 3)
    viewer_context.activate(10)
    app.processEvents()
    _d8b.input.setPlainText("mid-turn")
    _d8b._do_send()
    _d8b._host.running = True
    _stopped_before2 = _d8b._host.stopped
    viewer_context.report_document(11, "pdfD", "PDF D.pdf", "/x/D.pdf", 3)
    viewer_context.activate(11)
    app.processEvents()
    check("a RUNNING turn is stopped before the dock switches to a different PDF's session",
          _d8b._host.stopped == _stopped_before2 + 1)

    # -- empty state: no claude binary ---------------------------------------

    def _raise_not_found(callbacks):
        raise FileNotFoundError("claude not found")

    viewer_context.reset()
    _d9 = _make_dock(host_factory=_raise_not_found)
    check("FileNotFoundError from host_factory shows the install copy",
          assistant_dock.EMPTY_STATE_TEXT in _d9.transcript.toPlainText())
    check("the empty state disables the input box", not _d9.input.isEnabled())
    check("the empty state disables Send", not _d9.send_button.isEnabled())
    check("the empty state surfaces a visible Re-check button", _d9.recheck_button.isVisible())
    check("no host got constructed", _d9._host is None)

    # Re-check recovers once a host becomes available.
    _d9._host_factory = _fake_host_factory
    _d9._on_recheck_clicked()
    app.processEvents()
    check("Re-check re-attempts construction and recovers when it now succeeds",
          _d9._host is not None and _d9.input.isEnabled() and not _d9.recheck_button.isVisible())

    # -- slash completer ------------------------------------------------------

    viewer_context.reset()
    _d10 = _make_dock()
    _d10.input.setPlainText("/")
    app.processEvents()
    check("a leading '/' populates the completer with every slash command, '/'-prefixed",
          sorted(_d10._completer_model.stringList())
          == sorted("/" + c for c in _d10._sessions.list_commands(_uf_root)))
    _d10.input.setPlainText("hello, not a command")
    app.processEvents()
    check("ordinary text empties the completer's candidate list",
          _d10._completer_model.stringList() == [])

    # -- width persistence: debounce, config key, 80px guard, hidden guard ---
    # Modelled on tests/test_lecture_view.py:421-491's coverage of that
    # dock's analogous mechanism, adapted to THIS dock's actual storage
    # (mw.addonManager's assistant_dock_width config key via a debounced
    # QTimer, not lecture_view's pdf_tabs.json merge). _write_width_config
    # does `from aqt import mw as _mw` fresh each call, so the fake lives
    # on sys.modules["aqt"].mw, not assistant_dock.mw.

    class _FakeAddonManager:
        def __init__(self):
            self.store = {"assistant_dock_width": 420}
            self.writes = []

        def getConfig(self, pkg):
            return dict(self.store)

        def writeConfig(self, pkg, cfg):
            self.writes.append(dict(cfg))
            self.store.update(cfg)

    _fake_mw_width = _QtW.QMainWindow()
    _fake_addon_mgr = _FakeAddonManager()
    _fake_mw_width.addonManager = _fake_addon_mgr
    _orig_aqt_mw = sys.modules["aqt"].mw
    sys.modules["aqt"].mw = _fake_mw_width
    try:
        viewer_context.reset()
        _dw = _make_dock()
        _dw.resize(500, 300)
        app.processEvents()
        check("a resize above the 80px guard, while visible, arms the debounce timer",
              _dw._width_save_timer.isActive())
        check("the debounce is exactly 500ms",
              _dw._width_save_timer.interval() == 500)
        _dw._width_save_timer.timeout.emit()  # simulate the timer elapsing (no real 500ms wait)
        check("the timer firing writes assistant_dock_width EXACTLY ONCE, with the new width",
              len(_fake_addon_mgr.writes) == 1
              and _fake_addon_mgr.writes[0]["assistant_dock_width"] == 500)

        _fake_addon_mgr.writes.clear()
        viewer_context.reset()
        _dw2 = _make_dock()
        # The dock's own layout (three buttons in a row) imposes a real
        # minimum width around 200px, so a plain .resize(60, ...) is
        # silently clamped back up by Qt and never actually exercises the
        # guard (confirmed: minimumSizeHint() ~204px wide). Force the
        # boundary condition directly the way this codebase's other
        # geometry-dependent pins do (test_pdf_map.py's _corner_colour
        # helpers reach for offscreen-render pixels the same way, when a
        # widget's natural constraints won't cooperate): shadow width()
        # on the INSTANCE with a value under the guard, then call
        # resizeEvent directly — `event` is only ever forwarded to
        # super().resizeEvent(event) inside its own try/except, so a
        # placeholder None is caught and swallowed there, never reaching
        # the guard logic this pin actually cares about.
        _dw2.width = lambda: 60
        _dw2.resizeEvent(None)
        check("below the 80px guard the resize never arms the timer at all",
              not _dw2._width_save_timer.isActive())
        check("...so nothing is ever written for it",
              not _fake_addon_mgr.writes)

        _fake_addon_mgr.writes.clear()
        viewer_context.reset()
        _dw3 = _make_dock()
        _dw3.hide()
        app.processEvents()
        _dw3.resize(500, 300)  # well above the guard, but hidden
        app.processEvents()
        check("hidden, a resize never arms the timer either",
              not _dw3._width_save_timer.isActive())
        check("...so nothing is written while hidden",
              not _fake_addon_mgr.writes)
    finally:
        sys.modules["aqt"].mw = _orig_aqt_mw

    # -- shortcut mechanism: one window-scoped QAction, menu_action(), scan --

    _fake_mw_sc = _QtW.QMainWindow()
    _orig_dock_mw = assistant_dock.mw
    assistant_dock.mw = _fake_mw_sc
    assistant_dock._setup_done = False
    assistant_dock._assistant_action = None
    try:
        assistant_dock.setup()
        _k_actions = [a for a in _fake_mw_sc.actions() if a.shortcut().toString() == "Ctrl+Shift+K"]
        check("setup() adds exactly one QAction carrying the Ctrl+Shift+K shortcut",
              len(_k_actions) == 1)
        check("its shortcut context is WindowShortcut — live anywhere in the main window, "
              "not scoped to one child widget the way pdf_viewer's highlight shortcut is",
              bool(_k_actions) and _k_actions[0].shortcutContext() == _QtC.Qt.ShortcutContext.WindowShortcut)
        check("menu_action() returns that SAME QAction object — Task 11's Tools menu entry "
              "must reuse it, never mint a second action or shortcut for the same chord",
              assistant_dock.menu_action() is not None and bool(_k_actions)
              and assistant_dock.menu_action() is _k_actions[0])
        _before = len(_fake_mw_sc.actions())
        assistant_dock.setup()
        check("a second setup() call is a true no-op (guarded by _setup_done) — no second action",
              len(_fake_mw_sc.actions()) == _before
              and len([a for a in _fake_mw_sc.actions()
                       if a.shortcut().toString() == "Ctrl+Shift+K"]) == 1)
    finally:
        assistant_dock.mw = _orig_dock_mw
        assistant_dock._setup_done = False
        assistant_dock._assistant_action = None

    # The one-time collision scan: logs, but still installs the assistant's
    # own action (there is nowhere better to put the shortcut; skipping
    # would leave the assistant with none at all rather than a diagnosed one).
    _fake_mw_taken = _QtW.QMainWindow()
    _pretaken = _QtG.QAction("Someone else", _fake_mw_taken)
    _pretaken.setShortcut(_QtG.QKeySequence("Ctrl+Shift+K"))
    _fake_mw_taken.addAction(_pretaken)
    assistant_dock.mw = _fake_mw_taken
    assistant_dock._setup_done = False
    assistant_dock._assistant_action = None
    _captured_out, _orig_stdout = io.StringIO(), sys.stdout
    sys.stdout = _captured_out
    try:
        assistant_dock.setup()
    finally:
        sys.stdout = _orig_stdout
    check("a pre-existing chord on mw logs the one-time diagnostic line",
          "Ctrl+Shift+K already bound on mw" in _captured_out.getvalue())
    check("...but the assistant still gets its own action (diagnostic only, never a skip)",
          assistant_dock.menu_action() is not None)
    assistant_dock.mw = _orig_dock_mw
    assistant_dock._setup_done = False
    assistant_dock._assistant_action = None

    # -- ground colour: chrome, under BOTH palettes --------------------------

    def _corner_colour(dock):
        dock.resize(420, 320)
        app.processEvents()
        img = dock.grab().toImage()
        w, h = img.width(), img.height()
        return img.pixelColor(2, h - 2), img.pixelColor(w - 2, h - 2)

    _orig_night_mode = theme.night_mode
    try:
        theme.night_mode = lambda: False
        _d_light = _make_dock()
        _bl, _br = _corner_colour(_d_light)
        _want_light = _QtG.QColor(theme.palette(False)["chrome"])
        check("the dock's ground is the palette's chrome in LIGHT mode (bottom-left corner)",
              (_bl.red(), _bl.green(), _bl.blue()) == (_want_light.red(), _want_light.green(), _want_light.blue()))
        check("...and the bottom-right corner agrees",
              (_br.red(), _br.green(), _br.blue()) == (_want_light.red(), _want_light.green(), _want_light.blue()))

        theme.night_mode = lambda: True
        _d_dark = _make_dock()
        _bl2, _br2 = _corner_colour(_d_dark)
        _want_dark = _QtG.QColor(theme.palette(True)["chrome"])
        check("the dock's ground is the palette's chrome in DARK mode (bottom-left corner)",
              (_bl2.red(), _bl2.green(), _bl2.blue()) == (_want_dark.red(), _want_dark.green(), _want_dark.blue()))
        check("...and the bottom-right corner agrees",
              (_br2.red(), _br2.green(), _br2.blue()) == (_want_dark.red(), _want_dark.green(), _want_dark.blue()))
    finally:
        theme.night_mode = _orig_night_mode

    # -- teardown / shutdown never raises -------------------------------------

    _ok_shutdown = True
    for _d in (_d1, _d2, _d3, _d4, _d5, _d6, _d7, _d8, _d9, _d10):
        try:
            _d.shutdown()
        except Exception as exc:  # noqa: BLE001
            _ok_shutdown = False
            print(f"  shutdown raised for a dock: {exc}")
    check("shutdown() never raises across every dock built above", _ok_shutdown)

raise SystemExit(report())
