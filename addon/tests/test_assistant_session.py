"""Tests for assistant_session — the tool loop behind the Library panel.

Everything crossing a boundary is injected, so the whole loop runs here with
no Anki, no network and no model: a scripted backend replays turns, and a
fake tool runner records what it was asked for.

The loop's failure modes are all quiet ones — a history the API will reject
next turn, a loop that never ends, a tool error that eats the conversation —
so these pin the shape of what gets sent, not just what comes back.
"""
import json
import sys
import threading

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

asess = importlib.import_module("klausmate.assistant_session")

TOOLS = [{"name": "search_lecture_pdfs"}]


def text_turn(text, stop="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop}


def tool_turn(name="search_lecture_pdfs", tid="t1", args=None):
    return {
        "content": [{"type": "tool_use", "id": tid, "name": name,
                     "input": args or {"query": "incidence"}}],
        "stop_reason": "tool_use",
    }


class Backend:
    """Replays scripted turns and records every payload it was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.payloads = []

    def stream(self, payload, **kw):
        self.payloads.append(payload)
        if not self.turns:
            return text_turn("(out of script)")
        return self.turns.pop(0)


class Runner:
    def __init__(self, reply='{"chunks":[]}', is_error=False, boom=False):
        self.calls, self._reply = [], reply
        self._is_error, self._boom = is_error, boom

    def __call__(self, name, args):
        self.calls.append((name, args))
        if self._boom:
            raise RuntimeError("index exploded")
        return self._reply, self._is_error


def session(turns, runner=None, **kw):
    return asess.Session(Backend(turns), runner or Runner(), tools=TOOLS, **kw)


section("a plain answer is one round trip")
_s = session([text_turn("Incidence is new cases (p. 3).")])
_seen = []
_out = _s.ask("what is incidence?", on_text=_seen.append)
check("the answer comes back", _out == "Incidence is new cases (p. 3).")
check("and it says why it stopped", _s.last_stop == "answered")
check("one round trip, not two", len(_s._backend.payloads) == 1)
check("the question is in the history as a user turn",
      _s.history[0] == {"role": "user", "content": "what is incidence?"})
try:
    _s.ask("   ")
    check("an empty question is refused", False)
except asess.SessionError:
    check("an empty question is refused rather than billed", True)

section("the tool loop")
_r = Runner(reply='{"chunks":[{"source":"L1","page":3}]}')
_s = session([tool_turn(), text_turn("From slide 3 (p. 3).")], runner=_r)
_tools_seen = []
_out = _s.ask("what is incidence?", on_tool=lambda n, a: _tools_seen.append(n))
check("the tool was run", _r.calls and _r.calls[0][0] == "search_lecture_pdfs")
check("its arguments were passed through",
      _r.calls[0][1] == {"query": "incidence"})
check("the panel is told a tool is running, so it need not go silent",
      _tools_seen == ["search_lecture_pdfs"])
check("the final answer is returned, not the tool turn",
      _out == "From slide 3 (p. 3).")
check("two round trips", len(_s._backend.payloads) == 2)
_echo = _s.history[1]
check("the assistant turn is echoed VERBATIM — a summarised history is "
      "refused by the API on the NEXT turn, which is a miserable bug to "
      "trace back to here",
      _echo["role"] == "assistant"
      and _echo["content"][0]["type"] == "tool_use"
      and _echo["content"][0]["id"] == "t1")
_res = _s.history[2]
check("the result is attached to the id that asked for it",
      _res["role"] == "user"
      and _res["content"][0]["tool_use_id"] == "t1"
      and _res["content"][0]["type"] == "tool_result")
check("the second payload carries the whole exchange",
      len(_s._backend.payloads[1]["messages"]) == 3)

section("thinking blocks survive the echo")
_think = {
    "content": [
        {"type": "thinking", "thinking": "hmm", "signature": "sig-xyz"},
        {"type": "tool_use", "id": "t9", "name": "search_lecture_pdfs",
         "input": {}},
    ],
    "stop_reason": "tool_use",
}
_s = session([_think, text_turn("done")])
_s.ask("q")
_blocks = _s.history[1]["content"]
check("the thinking block is echoed with its signature intact — the API "
      "REFUSES the turn without it",
      _blocks[0].get("signature") == "sig-xyz")
check("...and is not stripped out of the history",
      any(b.get("type") == "thinking" for b in _blocks))

section("several tools in one turn")
_multi = {
    "content": [
        {"type": "tool_use", "id": "a", "name": "search_notes", "input": {}},
        {"type": "tool_use", "id": "b", "name": "get_note", "input": {}},
    ],
    "stop_reason": "tool_use",
}
_r = Runner()
_s = session([_multi, text_turn("both done")], runner=_r)
_s.ask("q")
check("every tool in the turn is run", len(_r.calls) == 2)
check("their results come back in ONE user turn, in order",
      len(_s.history[2]["content"]) == 2
      and [b["tool_use_id"] for b in _s.history[2]["content"]] == ["a", "b"])

section("a failing tool is a result, not the end of the conversation")
_s = session([tool_turn(), text_turn("recovered")], runner=Runner(boom=True))
_out = _s.ask("q")
check("the exception does not escape", _out == "recovered")
_block = _s.history[2]["content"][0]
check("the model is told the tool failed", _block.get("is_error") is True)
check("...without a traceback or internals",
      "tool failed" in _block["content"]
      and "index exploded" not in _block["content"])
_s = session([tool_turn(), text_turn("ok")],
             runner=Runner(reply='{"error":"nope"}', is_error=True))
_s.ask("q")
check("a tool that reports its own error is marked too",
      _s.history[2]["content"][0].get("is_error") is True)

section("the loop is bounded")
_r = Runner()
_s = session([tool_turn(tid=str(i)) for i in range(20)], runner=_r, max_turns=3)
_s.ask("q")
check("a model that only ever asks for tools is stopped",
      len(_s._backend.payloads) == 3)
check("...and says so, rather than looking like the model gave up",
      _s.last_stop == "max_turns")
check("the ceiling is what bounds it, not the script", len(_r.calls) == 3)
check("the default ceiling is small enough to matter", asess.MAX_TURNS <= 10)
# The audit caught these: hitting the ceiling still has to hand the user
# whatever the model DID say, and the defaults were never exercised because
# every test passed them explicitly.
_r = Runner()
_s = session([tool_turn(tid="a"),
              {"content": [{"type": "text", "text": "partial finding"},
                           {"type": "tool_use", "id": "b", "name": "x",
                            "input": {}}],
               "stop_reason": "tool_use"}] + [tool_turn(tid="c")] * 20,
             runner=_r, max_turns=3)
_out = _s.ask("q")
check("hitting the ceiling still returns the last thing the model said, "
      "rather than silence", _out == "partial finding")
_s = session([tool_turn()] * 20, runner=Runner())
_s.ask("q")
# Concrete, not `== asess.MAX_TURNS`: a pin that reads the constant it is
# checking moves with it and can never fail. Fourth time today.
check("the DEFAULT ceiling bounds a loop nobody capped explicitly, at 8",
      len(_s._backend.payloads) == 8 and asess.MAX_TURNS == 8)

section("reset clears the conversation")
_s = session([text_turn("a"), text_turn("b")])
_s.ask("first")
check("history accumulates", len(_s.history) == 2)
_s.reset()
check("reset empties it", _s.history == [])
check("...and clears why it stopped", _s.last_stop == "")
_s.ask("second")
check("the next ask starts from nothing, so a new PDF does not inherit the "
      "last one's context",
      len(_s._backend.payloads[-1]["messages"]) == 1)

section("cancellation")
_ev = threading.Event(); _ev.set()
_s = session([text_turn("never sent")])
_s.ask("q", cancel=_ev)
check("a cancel set before the first turn sends nothing at all",
      _s._backend.payloads == [] and _s.last_stop == "cancelled")
_s = session([{"content": [{"type": "text", "text": "half"}],
               "stop_reason": "cancelled"}, text_turn("more")])
_out = _s.ask("q")
check("a stream cancelled mid-turn keeps what arrived and stops",
      _out == "half" and _s.last_stop == "cancelled")
check("...and does not go round again", len(_s._backend.payloads) == 1)

section("wants_tools keys on the blocks, not the stop_reason")
check("a truncated turn carrying tool_use is still a tool turn — the "
      "stop_reason announcing them never arrived",
      asess.wants_tools({"content": [{"type": "tool_use", "id": "x"}],
                         "stop_reason": None}))
check("a plain answer wants nothing", not asess.wants_tools(text_turn("hi")))
check("an empty result wants nothing", not asess.wants_tools({}))

section("history trimming cannot orphan a tool_result")
_hist = (
    [{"role": "user", "content": "q0"}]
    + [{"role": "assistant", "content": [{"type": "tool_use", "id": "z"}]}]
    + [{"role": "user", "content": [{"type": "tool_result",
                                     "tool_use_id": "z", "content": "{}"}]}]
)
check("a window that would start ON a tool_result widens instead — an "
      "orphaned result is a protocol error, not just confusing",
      asess.trim_history(_hist, keep=1)[0]["role"] == "assistant")
check("a short history is untouched", asess.trim_history(_hist, 99) == _hist)
check("the window is bounded", asess.HISTORY_TURNS <= 20)
_long = [{"role": "user", "content": f"q{i}"} for i in range(40)]
check("the DEFAULT window trims a long conversation to 12",
      len(asess.trim_history(_long)) == 12 and asess.HISTORY_TURNS == 12)

section("what the model is told")
_p = asess.ask_system_prompt("Lecture_1.pdf")
check("the open document is named", "Lecture_1.pdf" in _p)
check("answers must be grounded in the retrieved passages",
      "not from memory" in _p)
check("citations are required, because an uncited claim cannot be checked",
      "(p. N)" in _p)
check("saying 'not in the material' is an ALLOWED answer — a study tool "
      "that fluently invents one is worse than useless",
      "does not answer" in _p and "say so" in _p)
check("no document name still yields a usable prompt",
      "lecture material" in asess.ask_system_prompt())

section("shape")
_SRC = open("klausmate/assistant_session.py").read()
_CODE = code_only(_SRC)
check("aqt-free", "import aqt" not in _CODE and "from aqt" not in _CODE)
check("no network of its own — the backend is injected",
      "urllib" not in _CODE)
check("tool execution is injected too, so this tests without a collection",
      "self._run_tool" in _CODE and "anki_tools" not in _CODE)

raise SystemExit(report())
