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
_LAZY_SIBLINGS = ("agent_host", "viewer_context", "page_store", "assistant_sessions", "anki_endpoint")
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
        no processEvents() pump is needed to observe the result.

        It MODELS THE PROCESS DYING, which the pre-fix version did not:
        its stop() only flipped running=False, so "Stop calls
        host.stop()" passed while the real next-send wrote into a dead
        pipe and the dock was stuck on "error: stdin write failed" until
        New Session (final review C1). Here stop()/interrupt()/close()
        end the child (``alive`` False) and send() to a dead one raises,
        exactly as AgentHost does — so C1 cannot come back unnoticed.
        """

        def __init__(self, callbacks):
            self.callbacks = callbacks
            self.running = False
            self.alive = False
            self.session_id = None
            self.sent = []
            self.started = []
            self.stopped = 0
            self.interrupts = 0
            self.reaps = 0
            self.closed = 0

        def start(self, session_id=None, resume=None):
            self.started.append({"session_id": session_id, "resume": resume})
            self.session_id = resume or session_id or "fake-sid"
            self.running = False
            self.alive = True
            return self.session_id

        def send(self, turn_line):
            if not self.alive:
                raise RuntimeError("the Claude Code process has exited (code 0)")
            self.sent.append(turn_line)
            self.running = True

        def stop(self):
            self.stopped += 1
            self.running = False
            self.alive = False  # SIGINT -> 2 s grace -> kill: the child is GONE

        def interrupt(self):
            self.interrupts += 1
            self.running = False
            self.alive = False

        def reap(self, force=False):
            self.reaps += 1
            self.alive = False
            return True

        def close(self):
            self.closed += 1
            self.alive = False

    def _fake_host_factory(callbacks):
        return _FakeHost(callbacks)

    def _FakePageContext(text="page text", text_source="page-record", png=None,
                         selection=""):
        """The context provider's payload is a plain dict since 2026-09-15
        (K-226) — page_store-backed, not an OCR dataclass."""
        return {"text": text, "text_source": text_source, "png": png,
                "selection": selection}

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
    # LAZY START (final review I1): constructing the dock — and every
    # later viewer switch — spawns NO `claude` child. Eager spawning cost
    # a blocking kill on the main thread plus a fresh Node process for a
    # PDF the user may never ask about, once per card that changed
    # lecture during review; Claude Code emits nothing until the first
    # message arrives anyway.
    check("construction spawns NO child — the first Send does",
          _d1._host.started == [])
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
        text="the nephron filters blood", text_source="page-record", png=_png,
        selection="tubule"))
    _d3.input.setPlainText("What is this slide about?")
    _d3._do_send()
    check("sending calls host.send exactly once", len(_d3._host.sent) == 1)
    check("...and THAT is when the child is spawned (lazy start, I1)",
          len(_d3._host.started) == 1)
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

    # -- the REAL context provider reads the page record (K-226) ------------
    # Replaces the OCR-scheduler pins: there is no OCR path and no Ollama
    # client here any more — the page in view is whatever page_store holds
    # for it, slide text and transcript segments combined.

    page_store = importlib.import_module("klausmate.page_store")
    _pdf_path = os.path.join(_uf_root, "lecture.pdf")
    with open(_pdf_path, "wb") as _f:
        _f.write(b"%PDF-1.4 not a real pdf")  # stat'd for the digest, never parsed
    page_store.ensure_records(_uf_root, "pdfRec", _pdf_path, ["slide two text"])
    page_store.append_segment(_uf_root, "pdfRec", _pdf_path, 0, 0.0, 4.0, "and the lecturer said this")
    _rec = page_store.load_record(_uf_root, "pdfRec", _pdf_path, 0)

    class _RecView:
        pdf_safe = "pdfRec"
        path = _pdf_path
        page_index = 0
        display = "Lecture.pdf"
        page_count = 1
        selection = ""

    _ctx_rec = _d3b._page_context(_RecView())
    check("the page context is a plain dict, not an OCR dataclass",
          isinstance(_ctx_rec, dict))
    check("its text IS the record's combined_text — slide text plus the "
          "transcript segments, in page_store's own order",
          _ctx_rec.get("text") == page_store.combined_text(_rec)
          and "slide two text" in _ctx_rec["text"]
          and "and the lecturer said this" in _ctx_rec["text"])
    check("text_source is 'page-record' — the label the turn carries, and "
          "never 'ocr' again",
          _ctx_rec.get("text_source") == "page-record")
    check("an unrenderable page degrades to no image rather than raising — "
          "the turn still goes out on the text",
          _ctx_rec.get("png") is None)
    check("no view (nothing open) is an empty page-record context, not a crash",
          _d3b._page_context(None) == {"text": "", "text_source": "page-record", "png": None})
    check("the dock reads its INJECTED user_files, never the package's real "
          "USER_FILES — a test must never touch the user's own library",
          _d3b._user_files == _uf_root)

    # -- empty record falls back to contexts/<safe>.json (PR1 review fix) ---
    # Records are only SEEDED by an import or an index run — with auto-index
    # off, no key, or a failed run there may be none, although the plain
    # extracted text from save_pdf is sitting right there in contexts/.

    pdf_handler = importlib.import_module("klausmate.pdf_handler")
    _ctx_dir = os.path.join(_uf_root, "contexts")
    os.makedirs(_ctx_dir, exist_ok=True)
    with open(os.path.join(_ctx_dir, "pdfCtxOnly.json"), "w", encoding="utf-8") as _f:
        json.dump({"pages": ["plain extracted slide text"], "page_count": 1}, _f)

    class _CtxOnlyView:
        pdf_safe = "pdfCtxOnly"
        path = os.path.join(_uf_root, "never-indexed.pdf")  # no page record seeded
        page_index = 0
        display = "CtxOnly.pdf"
        page_count = 1
        selection = ""

    _ctx_fallback = _d3b._page_context(_CtxOnlyView())
    check("an empty page record (no index run yet) falls back to the plain "
          "extracted text in contexts/<safe>.json (pdf_handler.load_pages), "
          "mirroring anki_tools' own lecture-search fallback",
          _ctx_fallback.get("text") == "plain extracted slide text")
    check("...and text_source says so — 'contexts', not 'page-record'",
          _ctx_fallback.get("text_source") == "contexts")

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
    _host4.callbacks["tool_use"]("tid-1", "mcp__klaus__search_notes", {"query": "renal"})
    app.processEvents()
    _lines4 = [ln.strip() for ln in _d4.transcript.toPlainText().splitlines()]
    check("a tool_use renders one line starting with ▸ and the TOOL_LABELS text",
          "▸ searched notes: renal" in _lines4)
    _host4.callbacks["tool_result"]("tid-1", True)
    app.processEvents()
    _lines4b = [ln.strip() for ln in _d4.transcript.toPlainText().splitlines()]
    check("a tool_result with is_error appends ' — failed' to the line for ITS OWN tool_use id",
          "▸ searched notes: renal — failed" in _lines4b)

    # M4: a batch of parallel tool calls, whose results come back in the
    # OPPOSITE order. Correlating by "the last tool line" decorated the
    # wrong one; correlating by tool_use id cannot.
    _host4.callbacks["tool_use"]("bat-A", "Read", {"file_path": "/lib/a.md"})
    _host4.callbacks["tool_use"]("bat-B", "Grep", {"pattern": "sodium"})
    app.processEvents()
    _host4.callbacks["tool_result"]("bat-A", True)   # the FIRST one failed
    app.processEvents()
    _lines4c = [ln.strip() for ln in _d4.transcript.toPlainText().splitlines()]
    check("both calls in a batch render their own line",
          "▸ read a.md" in " ".join(_lines4c) and "▸ searched files for sodium" in _lines4c)
    check("the failure decorates the line for bat-A, not the last line rendered",
          "▸ read a.md — failed" in _lines4c and "▸ searched files for sodium — failed" not in _lines4c)
    _host4.callbacks["tool_result"]("bat-B", False)
    app.processEvents()
    check("a successful result decorates nothing",
          "▸ searched files for sodium" in [ln.strip() for ln in _d4.transcript.toPlainText().splitlines()])
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

    # -- the session id is remembered on RESULT, under the SENDING pdf ------
    # (final review I2). `init` arrives ~1 s after the send through
    # _Bridge; remembering there, keyed by whatever PDF happened to be
    # current at DELIVERY time, stored A's session id under B and made B
    # resume A's conversation forever. And an id remembered before a turn
    # completed is stale by construction: Claude Code writes no
    # transcript for a message-less session, so `--resume` of it fails.

    viewer_context.reset()
    _d5 = _make_dock()
    _d5.input.setPlainText("ask")
    _d5._do_send()
    _d5._host.callbacks["init"]({"session_id": "real-sid-1", "mcp_ok": True})
    check("an init event alone remembers NOTHING — a session with no completed turn is not real",
          _d5._sessions.stored == {})
    _d5._host.callbacks["result"]({"session_id": "real-sid-1", "is_error": False,
                                   "duration_ms": 1, "total_cost_usd": 0.0, "text": "ok", "errors": []})
    check("the completed turn is what stores the id (None: the global slot)",
          _d5._sessions.stored.get(None) == "real-sid-1")

    # The exact I2 race: send for A, switch to B, THEN the events land.
    viewer_context.reset()
    _sessions_i2 = _FakeSessions()
    _d5r = _make_dock(sessions=_sessions_i2)
    viewer_context.report_document(20, "pdfA", "PDF A.pdf", "/x/A.pdf", 10)
    viewer_context.activate(20)
    app.processEvents()
    _d5r.input.setPlainText("about A")
    _d5r._do_send()
    viewer_context.report_document(21, "pdfB", "PDF B.pdf", "/x/B.pdf", 10)
    viewer_context.activate(21)
    app.processEvents()
    check("the switch really did land (the dock now follows B)",
          _d5r._current_pdf_safe == "pdfB")
    _d5r._host.callbacks["init"]({"session_id": "sid-of-A", "mcp_ok": True})
    _d5r._host.callbacks["result"]({"session_id": "sid-of-A", "is_error": False,
                                    "duration_ms": 1, "total_cost_usd": 0.0, "text": "ok", "errors": []})
    app.processEvents()
    check("A's session id lands under A — the PDF the turn was SENT for, not the one now in view",
          _sessions_i2.stored.get("pdfA") == "sid-of-A")
    check("...and nothing at all is written under B",
          "pdfB" not in _sessions_i2.stored)

    _d5b = _make_dock()
    _d5b._host.callbacks["init"]({"session_id": "sid-2", "mcp_ok": False})
    app.processEvents()
    check("mcp_ok False adds a warning line but chat keeps working",
          "unavailable" in _d5b.transcript.toPlainText().lower()
          and _d5b.input.isEnabled())

    # -- Stop, then send again: the child RESPAWNS (final review C1) --------

    viewer_context.reset()
    _d6 = _make_dock()
    _d6.input.setPlainText("go")
    _d6._do_send()
    _d6._on_send_button()  # button now reads Stop; clicking it must stop, not send
    check("clicking Stop calls host.stop() exactly once", _d6._host.stopped == 1)
    check("stopping flips the button back to Send", _d6.send_button.text() == "Send")
    check("...and the child is really dead afterwards (SIGINT, grace, kill)",
          _d6._host.alive is False)
    _starts_after_stop = len(_d6._host.started)
    _d6.input.setPlainText("ask again after Stop")
    _d6._do_send()
    check("the NEXT send spawns a new child rather than writing into the dead pipe",
          len(_d6._host.started) == _starts_after_stop + 1)
    check("...and the question actually goes out", len(_d6._host.sent) == 2)
    check("no 'stdin write failed' line anywhere in the transcript",
          "stdin write failed" not in _d6.transcript.toPlainText())

    # A remembered session is what the respawn resumes.
    viewer_context.reset()
    _sessions_c1 = _FakeSessions()
    _sessions_c1.stored[None] = "sid-to-resume"
    _d6b = _make_dock(sessions=_sessions_c1)
    _d6b.input.setPlainText("first")
    _d6b._do_send()
    _d6b._do_stop()
    _d6b.input.setPlainText("second")
    _d6b._do_send()
    check("the respawn after Stop resumes the remembered session id",
          _d6b._host.started[-1]["resume"] == "sid-to-resume")

    # An exited child (a crash, not a Stop) is the same story.
    viewer_context.reset()
    _d6c = _make_dock()
    _d6c.input.setPlainText("first")
    _d6c._do_send()
    _d6c._host.alive = False
    _d6c._host.callbacks["exited"](1)
    app.processEvents()
    _starts_after_exit = len(_d6c._host.started)
    _d6c.input.setPlainText("after the crash")
    _d6c._do_send()
    check("after an unexpected exit the next send spawns too",
          len(_d6c._host.started) == _starts_after_exit + 1 and len(_d6c._host.sent) == 2)

    # A stale --resume self-heals rather than wedging that PDF forever.
    viewer_context.reset()
    _sessions_stale = _FakeSessions()
    _sessions_stale.stored[None] = "sid-claude-forgot"
    _d6d = _make_dock(sessions=_sessions_stale)
    _d6d.input.setPlainText("hello")
    _d6d._do_send()
    check("the send resumed the stored id", _d6d._host.started[-1]["resume"] == "sid-claude-forgot")
    _d6d._host.callbacks["result"]({"session_id": "", "is_error": True, "duration_ms": 1,
                                    "total_cost_usd": 0.0, "text": "",
                                    "errors": [{"message": "No conversation found with session ID sid-claude-forgot"}]})
    app.processEvents()
    check("a 'No conversation found' result drops the stale mapping",
          _sessions_stale.forgotten and _sessions_stale.forgotten[-1] is None
          and None not in _sessions_stale.stored)
    check("...and says so in the transcript rather than failing silently",
          "gone from Claude Code" in _d6d.transcript.toPlainText())
    _d6d._host.alive = False
    _d6d.input.setPlainText("try again")
    _d6d._do_send()
    check("the next send starts FRESH, with no resume at all",
          _d6d._host.started[-1]["resume"] is None and len(_d6d._host.sent) == 2)

    # A send that fails must not eat the user's words (M18).
    viewer_context.reset()
    _d6e = _make_dock()

    def _explode(_turn):
        raise RuntimeError("pipe went away mid-write")

    _d6e.input.setPlainText("a question worth keeping")
    _d6e._host.start()          # a live child…
    _d6e._host_pdf_safe = None  # …that _ensure_child will accept
    _d6e._host.send = _explode
    _d6e._do_send()
    check("a failed send restores the typed text instead of losing it",
          _d6e.input.toPlainText() == "a question worth keeping")
    check("...and the button is not left stranded on Stop",
          _d6e.send_button.text() == "Send")

    # -- New Session: forget, spawn nothing until the next Send --------------

    viewer_context.reset()
    _d7 = _make_dock()
    _starts_before = len(_d7._host.started)
    _d7._on_new_session_clicked()
    check("New Session calls sessions.forget for the currently-followed PDF (None: global)",
          _d7._sessions.forgotten and _d7._sessions.forgotten[-1] is None)
    check("New Session spawns nothing on its own (lazy start)",
          len(_d7._host.started) == _starts_before)
    check("New Session announces itself in the (now-cleared) transcript",
          "New session" in _d7.transcript.toPlainText())
    _d7.input.setPlainText("first question of the new session")
    _d7._do_send()
    check("the next Send starts fresh — the mapping was forgotten, so no resume",
          len(_d7._host.started) == _starts_before + 1
          and _d7._host.started[-1]["resume"] is None)

    # -- switching the followed PDF resumes that PDF's stored session --------

    viewer_context.reset()
    _sessions8 = _FakeSessions()
    _sessions8.stored["pdfA"] = "resume-sid-A"
    _d8 = _make_dock(sessions=_sessions8)
    viewer_context.report_document(8, "pdfA", "PDF A.pdf", "/x/A.pdf", 10)
    viewer_context.activate(8)
    app.processEvents()
    check("the switch itself spawns nothing (I1)", _d8._host.started == [])
    check("the transcript announces the resume by the PDF's display name",
          "Resumed session for PDF A.pdf" in _d8.transcript.toPlainText())
    _d8.input.setPlainText("about A")
    _d8._do_send()
    check("the first Send after the switch resumes THAT PDF's stored session",
          _d8._host.started[-1]["resume"] == "resume-sid-A")
    viewer_context.report_document(9, "pdfB", "PDF B.pdf", "/x/B.pdf", 5)
    viewer_context.activate(9)
    app.processEvents()
    check("the transcript announces a fresh session for the new PDF",
          "New session for PDF B.pdf" in _d8.transcript.toPlainText())
    _d8.input.setPlainText("about B")
    _d8._do_send()
    check("switching to a PDF with NO stored session starts fresh, not resumed",
          _d8._host.started[-1]["resume"] is None)

    # A running turn on PDF A must be ended before B's — WITHOUT a
    # blocking wait on the main thread (final review I1): stop() blocks
    # up to 2 s on proc.wait, and this path runs inside viewer_context's
    # own notifier.
    viewer_context.reset()
    _d8b = _make_dock()
    viewer_context.report_document(10, "pdfC", "PDF C.pdf", "/x/C.pdf", 3)
    viewer_context.activate(10)
    app.processEvents()
    _d8b.input.setPlainText("mid-turn")
    _d8b._do_send()
    _d8b._host.running = True
    _interrupts_before = _d8b._host.interrupts
    _stopped_before2 = _d8b._host.stopped
    viewer_context.report_document(11, "pdfD", "PDF D.pdf", "/x/D.pdf", 3)
    viewer_context.activate(11)
    app.processEvents()
    check("a RUNNING turn is INTERRUPTED (signal + poll) when the dock switches PDF",
          _d8b._host.interrupts == _interrupts_before + 1)
    check("...and never through the blocking stop() path",
          _d8b._host.stopped == _stopped_before2)
    check("the interrupted child is reaped without blocking", _d8b._host.reaps >= 1)
    check("the button is back to Send after the switch", _d8b.send_button.text() == "Send")

    # -- NEW-1: the reap chain is bound to the child it was started for --
    # `_begin_async_stop` starts a QTimer chain that force-kills at its
    # 2 s grace expiry. Nothing cancelled it when `_ensure_child` spawned
    # a NEW child in the meantime — so a Send inside the outgoing child's
    # death window (~0.6 s for a real claude on SIGINT, the full 2 s if
    # it is mid-tool-call) handed the stale chain a fresh child to kill,
    # and the new turn died about two seconds in with "exited (code -9)".
    # `_FakeHost.reap()` returns True on the first call, so no round-1
    # pin ever had two generations of child alive across one chain; this
    # host reports "still exiting" the way a real one does.

    class _SlowReapHost(_FakeHost):
        def __init__(self, callbacks):
            super().__init__(callbacks)
            self.gen = 0
            self.reap_log = []      # (generation reaped, force?)
            self.killed = []        # generations actually force-killed
            self._exiting = False

        def start(self, session_id=None, resume=None):
            self.gen += 1
            self._exiting = False
            return super().start(session_id, resume)

        def interrupt(self):
            self.interrupts += 1
            self.running = False
            self._exiting = True    # signalled, NOT yet dead — alive stays True

        def reap(self, force=False):
            self.reap_log.append((self.gen, bool(force)))
            if force:
                self.killed.append(self.gen)
                self.alive = False
                self._exiting = False
                return True
            return not self._exiting

    viewer_context.reset()
    _d_race = _make_dock(host_factory=_SlowReapHost)
    viewer_context.report_document(40, "pdfG", "PDF G.pdf", "/x/G.pdf", 3)
    viewer_context.activate(40)
    app.processEvents()
    _d_race.input.setPlainText("about G")
    _d_race._do_send()
    _host_race = _d_race._host
    check("the first send spawned generation 1", _host_race.gen == 1 and _host_race.alive)

    viewer_context.report_document(41, "pdfH", "PDF H.pdf", "/x/H.pdf", 3)
    viewer_context.activate(41)
    app.processEvents()
    _stale_gen = _d_race._stop_gen
    check("the switch interrupted gen 1 and its reap says 'still exiting'",
          _host_race.interrupts == 1 and _host_race.reap_log == [(1, False)])

    _d_race.input.setPlainText("about H")
    _d_race._do_send()
    check("the Send inside that death window spawned generation 2, and it is alive",
          _host_race.gen == 2 and _host_race.alive and len(_host_race.sent) == 2)

    # Now let the STALE chain fire with its own grace period already
    # expired — the exact moment that used to kill generation 2. A past
    # deadline is set deliberately so the pin cannot pass merely because
    # `_ensure_child` zeroed it: the generation guard has to be what
    # stops this.
    _d_race._stop_deadline = 1.0  # monotonic() is far past this
    _reaps_before = len(_host_race.reap_log)
    _d_race._poll_stop(_stale_gen)
    check("a stale poll chain is a no-op — it never even reaps",
          len(_host_race.reap_log) == _reaps_before)
    check("...so the newly spawned child is untouched: no force-kill, still alive",
          _host_race.killed == [] and _host_race.alive is True)
    check("...and its turn is intact (2 sent, nothing exited)",
          len(_host_race.sent) == 2 and _d_race._host_pdf_safe == "pdfH")
    # The CURRENT generation's chain must still work, or the guard would
    # just be a way of never reaping anything.
    _d_race._poll_stop(_d_race._stop_gen)
    check("the current generation's chain still reaps normally",
          len(_host_race.reap_log) == _reaps_before + 1)

    # The same race, through the RESCHEDULE path rather than a direct
    # call: a real chain only ever fires again via QTimer.singleShot, and
    # that closure must carry the generation it was CREATED with. Reading
    # `self._stop_gen` at fire time instead would make every rescheduled
    # tick match by construction and the guard would be worthless. The
    # timer is faked so the callback can be held and fired after a new
    # child exists, instead of racing a real 100 ms.

    class _CapturingTimer:
        pending = []

        @staticmethod
        def singleShot(_ms, fn):
            _CapturingTimer.pending.append(fn)

    viewer_context.reset()
    _d_resched = _make_dock(host_factory=_SlowReapHost)
    viewer_context.report_document(42, "pdfI", "PDF I.pdf", "/x/I.pdf", 3)
    viewer_context.activate(42)
    app.processEvents()
    _d_resched.input.setPlainText("about I")
    _d_resched._do_send()
    _host_resched = _d_resched._host
    _real_qtimer = assistant_dock.QTimer
    assistant_dock.QTimer = _CapturingTimer
    try:
        _CapturingTimer.pending.clear()
        viewer_context.report_document(43, "pdfJ", "PDF J.pdf", "/x/J.pdf", 3)
        viewer_context.activate(43)
        app.processEvents()
        check("the switch's chain scheduled itself once (reap said 'still exiting')",
              len(_CapturingTimer.pending) == 1)
        _d_resched.input.setPlainText("about J")
        _d_resched._do_send()
        check("that Send spawned generation 2", _host_resched.gen == 2 and _host_resched.alive)
        _d_resched._stop_deadline = 1.0  # the stale chain's grace has expired
        _reaps_before2 = len(_host_resched.reap_log)
        _CapturingTimer.pending.pop(0)()  # the rescheduled tick fires
        check("the rescheduled tick carries the generation it was CREATED with, so it is a no-op",
              len(_host_resched.reap_log) == _reaps_before2)
        check("...and generation 2 is neither force-killed nor rescheduled against",
              _host_resched.killed == [] and _host_resched.alive is True
              and not _CapturingTimer.pending)
    finally:
        assistant_dock.QTimer = _real_qtimer

    # -- NEW-2: a hard kill after a resume Claude Code ACCEPTED --------------
    # `_on_exited` treated any rc != 0 during an unproven resume as a
    # failed resume, dropped that PDF's mapping and printed "That saved
    # conversation is gone from Claude Code" — untrue for a kill after
    # stop()'s grace, or for NEW-1's own force-kill. `init` is the proof
    # the resume was accepted: a resume of a session Claude Code does not
    # have never reaches it.

    viewer_context.reset()
    _sessions_n2 = _FakeSessions()
    _sessions_n2.stored[None] = "good-sid"
    _d_n2 = _make_dock(sessions=_sessions_n2)
    _d_n2.input.setPlainText("q")
    _d_n2._do_send()
    check("the send resumed the stored id", _d_n2._host.started[-1]["resume"] == "good-sid")
    _d_n2._host.callbacks["init"]({"session_id": "good-sid", "mcp_ok": True})
    _d_n2._host.alive = False
    _d_n2._host.callbacks["exited"](-9)  # SIGKILL, not a rejected resume
    app.processEvents()
    check("a hard kill AFTER init keeps the session — the resume had been accepted",
          _sessions_n2.forgotten == [] and _sessions_n2.stored.get(None) == "good-sid")
    check("...and never claims the conversation is gone from Claude Code",
          "gone from Claude Code" not in _d_n2.transcript.toPlainText())
    check("...it reports the exit instead", "exited (code -9)" in _d_n2.transcript.toPlainText())

    # The genuine failure — an exit BEFORE init — must still self-heal.
    viewer_context.reset()
    _sessions_n2b = _FakeSessions()
    _sessions_n2b.stored[None] = "sid-claude-rejects"
    _d_n2b = _make_dock(sessions=_sessions_n2b)
    _d_n2b.input.setPlainText("q")
    _d_n2b._do_send()
    _d_n2b._host.alive = False
    _d_n2b._host.callbacks["exited"](1)  # died before any init
    app.processEvents()
    check("an exit BEFORE init during a resume still forgets — that IS the real failure",
          _sessions_n2b.forgotten and _sessions_n2b.forgotten[-1] is None
          and "gone from Claude Code" in _d_n2b.transcript.toPlainText())

    # -- NEW-3: New Session mid-turn is not undone by a late result ---------

    viewer_context.reset()
    _sessions_n3 = _FakeSessions()
    _d_n3 = _make_dock(sessions=_sessions_n3)
    _d_n3.input.setPlainText("q")
    _d_n3._do_send()
    _d_n3._on_new_session_clicked()
    check("New Session forgot the mapping", _d_n3._sessions.forgotten == [None])
    _d_n3._host.callbacks["result"]({"session_id": "sid-user-just-forgot", "is_error": False,
                                     "duration_ms": 1, "total_cost_usd": 0.0, "text": "", "errors": []})
    app.processEvents()
    check("a result still in flight from the interrupted child never re-remembers "
          "the id the user just asked to forget", _sessions_n3.stored == {})
    # _do_stop deliberately does NOT clear _sending_pdf_safe: remembering
    # a stopped turn's session is exactly what you want there.
    viewer_context.reset()
    _sessions_n3b = _FakeSessions()
    _d_n3b = _make_dock(sessions=_sessions_n3b)
    _d_n3b.input.setPlainText("q")
    _d_n3b._do_send()
    _d_n3b._do_stop()
    _d_n3b._host.callbacks["result"]({"session_id": "sid-after-stop", "is_error": False,
                                      "duration_ms": 1, "total_cost_usd": 0.0, "text": "", "errors": []})
    app.processEvents()
    check("a result after STOP still remembers — Stop keeps the conversation",
          _sessions_n3b.stored.get(None) == "sid-after-stop")

    # -- NEW-4: the outgoing PDF's trailing output stays out of the new one --

    viewer_context.reset()
    _d_n4 = _make_dock()
    viewer_context.report_document(50, "pdfE", "PDF E.pdf", "/x/E.pdf", 3)
    viewer_context.activate(50)
    app.processEvents()
    _d_n4.input.setPlainText("about E")
    _d_n4._do_send()
    viewer_context.report_document(51, "pdfF", "PDF F.pdf", "/x/F.pdf", 3)
    viewer_context.activate(51)
    app.processEvents()
    _d_n4._host.callbacks["delta"]("trailing words from E")
    _d_n4._host.callbacks["tool_use"]("late-1", "Read", {"file_path": "/x/lecture-e.md"})
    _d_n4._host.callbacks["tool_result"]("late-1", True)
    app.processEvents()
    _txt_n4 = _d_n4.transcript.toPlainText()
    check("the outgoing PDF's trailing deltas never render under the incoming PDF's header",
          "trailing words from E" not in _txt_n4)
    check("...nor its trailing tool line", "lecture-e.md" not in _txt_n4)
    check("the incoming PDF's own announcement is untouched",
          "New session for PDF F.pdf" in _txt_n4)
    # An ordinary turn must be completely unaffected by that guard.
    _d_n4.input.setPlainText("about F")
    _d_n4._do_send()
    _d_n4._host.callbacks["delta"]("F answer")
    _d_n4._host.callbacks["tool_use"]("ok-1", "Read", {"file_path": "/x/lecture-f.md"})
    app.processEvents()
    _txt_n4b = _d_n4.transcript.toPlainText()
    check("an ordinary turn's deltas still render",
          "F answer" in _txt_n4b and "lecture-f.md" in _txt_n4b)

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

    # -- assistant_reopen: a preference that is finally READ (I7) ------------
    # It was written by Preferences and consumed by nobody — a visible,
    # documented setting that did nothing. The dock now records whether
    # it was open (assistant_dock_open) and honours the pair on
    # profile_did_open.

    _fake_mw_reopen = _QtW.QMainWindow()
    _reopen_mgr = _FakeAddonManager()
    _fake_mw_reopen.addonManager = _reopen_mgr
    _orig_dock_mw_reopen = assistant_dock.mw
    _orig_open_assistant = assistant_dock.open_assistant
    _reopened = []
    assistant_dock.mw = _fake_mw_reopen
    assistant_dock.open_assistant = lambda: _reopened.append(True)
    try:
        _reopen_mgr.store = {"assistant_dock_open": False}
        assistant_dock._write_open_flag(True)
        check("opening the dock records assistant_dock_open True",
              _reopen_mgr.store.get("assistant_dock_open") is True and len(_reopen_mgr.writes) == 1)
        assistant_dock._write_open_flag(True)
        check("...and writing the same value again is a no-op, not a second config write",
              len(_reopen_mgr.writes) == 1)
        assistant_dock._write_open_flag(False)
        check("closing it records False", _reopen_mgr.store.get("assistant_dock_open") is False)

        _reopen_mgr.store = {"assistant_reopen": False, "assistant_dock_open": True}
        assistant_dock.reopen_if_configured()
        app.processEvents()
        check("reopen OFF: the dock is not reopened even though it was open last time",
              _reopened == [])
        _reopen_mgr.store = {"assistant_reopen": True, "assistant_dock_open": False}
        assistant_dock.reopen_if_configured()
        app.processEvents()
        check("reopen ON but it was CLOSED last time: still not reopened", _reopened == [])
        _reopen_mgr.store = {"assistant_reopen": True, "assistant_dock_open": True}
        assistant_dock.reopen_if_configured()
        app.processEvents()
        check("reopen ON and it was open last time: the dock reopens", _reopened == [True])
    finally:
        assistant_dock.mw = _orig_dock_mw_reopen
        assistant_dock.open_assistant = _orig_open_assistant

    check("setup() registers the reopen consumer on profile_did_open — without this the "
          "preference is unread (the shape of I7's defect)",
          "gui_hooks.profile_did_open.append(reopen_if_configured)" in _CODE)

    # -- the stderr log file is the name the spec gives it (M1) --------------
    check("the child's stderr log is user_files/assistant/claude.log, as spec section 4.2 says "
          "(the code shipped agent.log, so the two disagreed)",
          '"assistant", "claude.log"' in _SRC and '"agent.log"' not in _SRC)

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
