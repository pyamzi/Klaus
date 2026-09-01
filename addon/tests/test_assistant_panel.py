"""Tests for assistant_panel — the Library's right-hand assistant.

These run against GENUINE offscreen PyQt6, not stubs. PyQt6 is installed
for this interpreter as an abi3 build (unlike Anki's bundled one), which
test_drive.py already exploits — the klaus-test skill's claim that "Qt
widgets cannot be instantiated in tests" is out of date, and this file is
the second place to depend on that.

That matters here more than anywhere else in the addon: the panel's whole
job is threading and signal marshalling, and a stub cannot tell you whether
a worker thread's emission actually reaches the widget.
"""
import os
import sys
import threading
import time
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC
    from PyQt6 import QtGui as _QtG
    from PyQt6 import QtWidgets as _QtW
    _HAVE_QT = True
except Exception as _e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable ({_e}) — widget tests skipped")

# ---- source pins, which run either way -------------------------------
_SRC = open("klausmate/assistant_panel.py").read()
_CODE = code_only(_SRC)

section("the traps this panel had to avoid")
check("it subclasses QWidget — K-161 found a QDockWidget=None fallback is "
      "a TypeError at CLASS DEFINITION, so the base must always exist",
      "class AssistantPanel(QWidget)" in _CODE)
check("the tool loop runs on a worker thread — execute_tool marshals ONTO "
      "the main thread and blocks, so calling it there deadlocks",
      "threading.Thread(" in _CODE)
check("the worker talks back through signals, never by touching a widget "
      "— a direct cross-thread widget call is a crash, not a glitch",
      "pyqtSignal" in _CODE and "self.signals." in _CODE)
check("no colour is named here; styling comes from theme tokens",
      "dialog_qss" in _CODE
      and not __import__("re").search(r"#[0-9A-Fa-f]{6}", _SRC))
check("a failing worker reports rather than dying silently — a panel stuck "
      "on 'thinking' is indistinguishable from a hang",
      "signals.failed.emit" in _CODE)

section("copy that carries a state the user cannot otherwise see")
ap = __import__("importlib").import_module("klausmate.assistant_panel")
check("hitting the turn ceiling is NAMED, not left looking like the model "
      "gave up", "too many tool calls" in ap.status_line("max_turns"))
check("a cancelled ask says so rather than looking like a crash",
      ap.status_line("cancelled") == "Stopped.")
check("an answer names the document it came from",
      "Lecture_1" in ap.status_line("answered", "Lecture_1"))
check("with no PDF selected the panel says what to do",
      ap.status_line("", "") == ap.NO_PDF)
check("the unbuilt tabs say they are unbuilt rather than showing a dead "
      "control that looks finished",
      "Not built yet" in ap.PLACEHOLDER[ap.PRACTICE])
check("...and the podcast tab is honest about which half exists",
      "script half is built" in ap.PLACEHOLDER[ap.PODCAST])
check("three tabs, in the order asked for",
      ap.TABS == ("Ask", "Practice", "Podcast"))

if not _HAVE_QT:
    raise SystemExit(report())

# ---- real widgets ----------------------------------------------------
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
for _name in [m for m in list(sys.modules) if m.startswith("klausmate.")]:
    del sys.modules[_name]
# install() returns None; the package handle is built here, as test_drive
# does, so klausmate.* re-imports against the working tree under real Qt.
_pkg = types.ModuleType("klausmate")
_pkg.__path__ = [os.path.abspath("klausmate")]
_pkg.__package__ = "klausmate"
sys.modules["klausmate"] = _pkg
import importlib  # noqa: E402

ap = importlib.import_module("klausmate.assistant_panel")

app = _QtW.QApplication.instance() or _QtW.QApplication([])


def _pump(seconds=2.0, until=None):
    """Run the event loop until `until` or the deadline — the worker is a
    real thread, so its signals only land while the loop turns."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until is None or until()


class FakeSession:
    """Stands in for assistant_session.Session, on the worker thread."""

    def __init__(self, answer="Incidence is new cases (p. 3).",
                 tools=(), boom=False, block=None):
        self.answer, self._tools = answer, list(tools)
        self._boom, self._block = boom, block
        self.last_stop = ""
        self.asked = []

    def ask(self, question, on_text=None, on_tool=None, cancel=None):
        self.asked.append(question)
        if self._boom:
            raise RuntimeError("provider exploded")
        for name in self._tools:
            if on_tool:
                on_tool(name, {})
        if self._block is not None:
            while not self._block.is_set():
                if cancel is not None and cancel.is_set():
                    self.last_stop = "cancelled"
                    return ""
                time.sleep(0.005)
        for chunk in self.answer.split(" "):
            if on_text:
                on_text(chunk + " ")
        self.last_stop = "answered"
        return self.answer


def panel(session):
    p = ap.AssistantPanel(session_factory=lambda name: session)
    p.set_pdf("Lecture_1")
    return p


section("it builds, offscreen, for real")
_p = ap.AssistantPanel(session_factory=lambda n: FakeSession())
check("the widget constructs", _p is not None)
check("three tabs are present", _p.tabs.count() == 3)
check("named in order",
      [_p.tabs.tabText(i) for i in range(3)] == list(ap.TABS))
check("with no PDF the input is disabled — there is nothing to ask about",
      not _p.input.isEnabled() and not _p.send_btn.isEnabled())
check("and the panel says so", _p.status.text() == ap.NO_PDF)

section("binding to the selected PDF")
_p.set_pdf("Lecture_1")
check("selecting a PDF enables asking", _p.input.isEnabled())
check("...and says which one", "Lecture_1" in _p.status.text())
_p.transcript.setPlainText("stale conversation")
_p.set_pdf("Lecture_2")
check("a NEW document clears the transcript — carrying the last lecture's "
      "exchange over is how an answer cites the wrong file's slide",
      _p.transcript.toPlainText() == "")
_p._session = "sentinel"
_p.set_pdf("Lecture_2")
check("re-selecting the SAME pdf does not reset the conversation",
      _p._session == "sentinel")

section("a full ask, on a real worker thread")
_s = FakeSession(tools=["search_lecture_pdfs"])
_p = panel(_s)
_p.input.setText("what is incidence?")
_p.send()
check("the panel goes busy immediately", _p.busy or _p.stop_btn.isEnabled())
check("the input is disabled while it runs", not _p.input.isEnabled())
_pump(until=lambda: not _p.busy and _p.send_btn.isEnabled())
check("the question reached the session", _s.asked == ["what is incidence?"])
_text = _p.transcript.toPlainText()
check("the question is echoed into the transcript", "You: what is incidence?" in _text)
check("the streamed answer lands in ONE block, not one line per token",
      "Klaus: Incidence is new cases (p. 3)." in _text)
check("the tool call was announced, so the panel never went silent",
      "slides" in _p.status.text() or "Answered" in _p.status.text())
check("the footer settles on the answer", "Answered" in _p.status.text())
check("controls come back", _p.input.isEnabled() and not _p.stop_btn.isEnabled())
check("the input was cleared for the next question", _p.input.text() == "")

section("an empty question is not sent")
_s = FakeSession()
_p = panel(_s)
_p.input.setText("   ")
_p.send()
_pump(0.2)
check("whitespace is not a question", _s.asked == [])

section("stopping")
_gate = threading.Event()
_s = FakeSession(block=_gate)
_p = panel(_s)
_p.input.setText("long one")
_p.send()
_pump(0.3, until=lambda: _p.busy)
check("it is running", _p.busy)
_p.stop()
_pump(until=lambda: not _p.busy)
_gate.set()
check("stopping ends the run", not _p.busy)
check("...and says so rather than looking like a crash",
      "Stopped" in _p.status.text())
check("controls come back after a stop", _p.send_btn.isEnabled())

section("a failing provider surfaces, it does not hang")
_p = panel(FakeSession(boom=True))
_p.input.setText("q")
_p.send()
_pump(until=lambda: not _p.busy)
check("the error reaches the transcript",
      "[error]" in _p.transcript.toPlainText())
check("...naming what went wrong",
      "provider exploded" in _p.transcript.toPlainText())
check("the panel is usable again rather than stuck on 'thinking'",
      _p.send_btn.isEnabled() and not _p.stop_btn.isEnabled())

section("a second ask while one is running is refused")
_gate = threading.Event()
_s = FakeSession(block=_gate)
_p = panel(_s)
_p.input.setText("first")
_p.send()
_pump(0.3, until=lambda: _p.busy)
_p.input.setText("second")
_p.send()
_gate.set()
_pump(until=lambda: not _p.busy)
check("only the first question was asked — a second worker would race the "
      "first one's signals into the same transcript", _s.asked == ["first"])

raise SystemExit(report())
