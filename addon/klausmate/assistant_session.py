"""One assistant conversation, and the tool loop that drives it.

The half of the Library's right-hand panel worth testing. The Qt widget on
top of this is deliberately thin: it renders a transcript and forwards
keystrokes, and everything that could be *wrong* lives here.

The loop is the standard shape — stream a turn, and if the model asked for
tools, run them, echo the results, and go round again — with three rules
that are not optional:

1. **The assistant turn is echoed VERBATIM.** Every content block comes back
   exactly as ``llm_client`` finalized it, thinking ``signature`` included.
   The API refuses an echoed thinking block without its signature, so
   "tidying" the history breaks the next turn rather than the current one,
   which is a miserable thing to debug.
2. **The loop is bounded.** ``max_turns`` exists because a model that keeps
   calling a failing tool will keep calling it forever, and the user is
   paying per turn.
3. **A tool failure is a RESULT, not an exception.** The model is told the
   tool failed and gets to recover; raising would throw away a conversation
   over one bad search.

aqt-free, and everything crossing a boundary is injected — the backend, the
tool runner, the clock. The whole loop is exercised in tests with no Anki,
no network and no model.
"""

from __future__ import annotations

import json
from typing import Any, Callable

# Ceiling on round trips per ask. Eight is generous for "search, read, answer"
# and still bounded: a model looping on a broken tool stops costing money.
MAX_TURNS = 8

# Kept small on purpose. The panel answers about ONE open PDF, and a long
# scrollback of earlier questions crowds out the retrieved passages that
# actually ground the answer.
HISTORY_TURNS = 12


class SessionError(Exception):
    """The conversation could not continue."""


def ask_system_prompt(pdf_name: str = "") -> str:
    """The instructions for the question-answering mode.

    Says where answers come from and what to do when the material does not
    contain one, because a study tool that fluently invents an answer is
    worse than one that says it cannot find it — the user cannot tell the
    difference until an exam does.
    """
    lines = [
        "You answer questions about the user's lecture material inside Anki.",
        "",
        "- Answer from the retrieved passages, not from memory. Search first.",
        "- Cite the slide you used, as (p. N). An uncited claim reads as "
        "fact and cannot be checked.",
        "- If the material does not answer the question, say so plainly and "
        "stop. Do not fill the gap from general knowledge without labelling "
        "it as outside the material.",
        "- Be brief. This renders in a narrow side panel, not a document.",
    ]
    if pdf_name:
        lines.insert(1, f"The open document is: {pdf_name}. Prefer it.")
    return "\n".join(lines)


def tool_result_block(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    """One tool_result, shaped for the assistant's next turn."""
    block: dict = {
        "type": "tool_result",
        "tool_use_id": str(tool_use_id),
        "content": str(content),
    }
    if is_error:
        block["is_error"] = True
    return block


def tool_uses(result: dict) -> list:
    """The tool_use blocks of a finished turn, in order."""
    return [
        b for b in (result.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]


def wants_tools(result: dict) -> bool:
    """Whether the model stopped to ask for tools.

    Keys on the PRESENCE of tool_use blocks rather than on stop_reason
    alone: a stream that was cut short carries the blocks without ever
    delivering the stop_reason that announces them, and answering "no tools
    wanted" there would silently drop the model's request.
    """
    return bool(tool_uses(result))


def trim_history(history: list, keep: int = HISTORY_TURNS) -> list:
    """The last *keep* messages, never starting on a tool_result.

    A tool_result whose matching tool_use has been trimmed away is a
    protocol error, not merely confusing — so the window is widened rather
    than allowed to open on an orphan.
    """
    if keep <= 0 or len(history) <= keep:
        return list(history)
    start = len(history) - keep
    while start > 0 and _is_tool_result(history[start]):
        start -= 1
    return list(history[start:])


def _is_tool_result(message: dict) -> bool:
    content = (message or {}).get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


class Session:
    """One conversation against one document."""

    def __init__(
        self,
        backend,
        run_tool: Callable[[str, dict], tuple],
        tools: list | None = None,
        pdf_name: str = "",
        model: str = "",
        max_turns: int = MAX_TURNS,
    ) -> None:
        self._backend = backend
        self._run_tool = run_tool
        self._tools = list(tools or [])
        self._pdf_name = pdf_name
        self._model = model
        self._max_turns = int(max_turns)
        self.history: list = []
        # Why the last ask stopped: "answered", "max_turns" or "cancelled".
        # The panel shows this; a loop that quietly hit its ceiling and
        # returned a half-answer would look like the model giving up.
        self.last_stop = ""

    def _payload(self) -> dict:
        body: dict = {
            "messages": trim_history(self.history),
            "system": ask_system_prompt(self._pdf_name),
            "max_tokens": 2048,
        }
        if self._model:
            body["model"] = self._model
        if self._tools:
            body["tools"] = self._tools
        return body

    def ask(
        self,
        question: str,
        on_text: Callable[[str], None] | None = None,
        on_tool: Callable[[str, dict], None] | None = None,
        cancel=None,
    ) -> str:
        """Ask, running tools until the model answers. Returns the answer.

        ``on_text`` streams deltas to the panel; ``on_tool`` announces each
        tool call so the panel can say "searching the slides…" rather than
        going silent for four seconds.
        """
        question = str(question or "").strip()
        if not question:
            raise SessionError("nothing to ask")
        self.history.append({"role": "user", "content": question})
        self.last_stop = ""

        for _turn in range(self._max_turns):
            if cancel is not None and cancel.is_set():
                self.last_stop = "cancelled"
                return self._last_text()
            result = self._backend.stream(
                self._payload(), on_text=on_text, cancel=cancel
            )
            content = result.get("content") or []
            # Verbatim. Not a summary, not the text blocks only — the
            # thinking signature has to survive or the next turn is refused.
            self.history.append({"role": "assistant", "content": content})

            if result.get("stop_reason") == "cancelled":
                self.last_stop = "cancelled"
                return self._text_of(content)
            calls = tool_uses(result)
            if not calls:
                self.last_stop = "answered"
                return self._text_of(content)

            results = []
            for call in calls:
                name = str(call.get("name") or "")
                args = call.get("input")
                if not isinstance(args, dict):
                    args = {}
                if on_tool is not None:
                    try:
                        on_tool(name, args)
                    except Exception:
                        pass  # a panel that fails to draw must not kill the ask
                try:
                    payload, is_error = self._run_tool(name, args)
                except Exception as exc:
                    # The model is told and can recover. Raising here would
                    # discard the whole conversation over one bad search.
                    payload = json.dumps(
                        {"error": f"tool failed: {type(exc).__name__}"}
                    )
                    is_error = True
                results.append(
                    tool_result_block(call.get("id") or "", payload, is_error)
                )
            self.history.append({"role": "user", "content": results})

        self.last_stop = "max_turns"
        return self._last_text()

    def _text_of(self, content: list) -> str:
        return "".join(
            str(b.get("text") or "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )

    def _last_text(self) -> str:
        for message in reversed(self.history):
            if message.get("role") != "assistant":
                continue
            text = self._text_of(message.get("content") or [])
            if text:
                return text
        return ""

    def reset(self) -> None:
        self.history = []
        self.last_stop = ""
