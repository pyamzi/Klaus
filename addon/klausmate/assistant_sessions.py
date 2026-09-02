"""Per-PDF/global assistant sessions, slash-command prompts, and the
versioned system prompt file — the small persistent bits the Claude Code
assistant dock (``assistant_dock.py``, not yet wired to a surface) needs
across restarts. Design: docs/superpowers/specs/2026-09-01-klaus-assistant-
claude-code-design.md §10.

Three independent stores live under ``user_files/assistant/``:

- ``sessions.json`` — ``{"by_pdf": {<pdf_safe>: {"session_id", "last_used"}},
  "global": {"session_id", "last_used"}}``. Claude Code's own session ids
  are opaque strings; this module only remembers WHICH one belongs to
  which PDF (or to no PDF at all) so the dock can resume the right
  conversation when the followed PDF changes. Atomic write (tmp +
  ``os.replace``); a MISSING file is the ordinary "nothing recorded yet"
  case and stays quiet, while a PRESENT-but-corrupt file is the
  exceptional case and is logged — both read back as the same empty
  shape, because a torn or hand-edited store must never take session
  resume down with it.
- ``prompts/<name>.md`` — the slash-command library. ``ensure_defaults``
  seeds ``explain.md``/``cards.md``/``quiz.md`` the FIRST time the folder
  is looked at (no directory yet, or an empty one) and never again: the
  gate is folder-level emptiness, not "does explain.md exist", so a user
  who has edited (or deleted) just one of the three never has it reappear
  or get clobbered on the next open because of that check. ``expand``
  turns a typed line into the text actually sent to Claude Code: a
  leading ``/name`` is swapped for that file's content with the rest of
  the line appended, then ``$SELECTION``/``$PAGE``/``$PDF`` are filled in
  from the caller's ctx dict (keys ``selection``/``page_text``/``pdf`` —
  deliberately not the same spelling as the placeholder names, so a lazy
  ``ctx.get("page")`` typo is its own bug rather than a silent no-op). An
  unrecognized command (no matching file) passes the line through
  untouched instead of erroring — the user may just be typing a sentence
  that happens to start with a slash.
- ``system_prompt.md`` — Klaus's fixed system prompt for the assistant
  session, versioned by a leading HTML-comment marker
  (``<!-- klaus-system-prompt vN -->``) so a later Klaus release can ship
  a revised prompt and have it actually reach an existing profile:
  ``ensure_system_prompt`` rewrites whenever the marker is missing or
  names a version below ``SYSTEM_PROMPT_VERSION``, and leaves the file
  alone otherwise. It is not user-editable content, but the version gate
  still exists so an already-current file is never needlessly rewritten.

Every path helper takes the SAME ``user_files`` root the rest of the addon
uses (``pdf_handler``'s, ``retention``'s) — never Anki's ``meta.json`` or
the live collection. aqt-free and stdlib-only by construction (no other
addon module is imported here), so tests/test_assistant_sessions.py needs
only a temp dir, never the aqt stub.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

ASSISTANT_DIRNAME = "assistant"
SESSIONS_FILE = "sessions.json"
PROMPTS_DIRNAME = "prompts"
SYSTEM_PROMPT_FILE = "system_prompt.md"

SYSTEM_PROMPT_VERSION = 1

DEFAULT_PROMPTS = {
    "explain": (
        "Explain this page to me as if for an exam, then list the three "
        "facts most likely to be tested."
    ),
    "cards": (
        "Propose Anki cards for this page: one fact per card, front/back, "
        "cite the page. Wait for my go-ahead before adding any."
    ),
    "quiz": (
        "Quiz me on this page, one question at a time; grade my answer "
        "before the next."
    ),
}

# ``\w[\w-]*`` — a command name starts with a word character and may
# continue with word characters or hyphens (matches slash-command file
# stems like "cards" and "aaa-mnemonic"). re.S so a multi-line "rest" (the
# text after the command name) is captured whole, embedded newlines and
# all, rather than truncated at the first line.
_COMMAND_RE = re.compile(r"^/(\w[\w-]*)\s*(.*)$", re.S)

# The version marker is always the file's first line, e.g.
# "<!-- klaus-system-prompt v1 -->". Anything else on that line (a stray
# hand edit, a different comment) reads as "no marker" -> version None.
_MARKER_RE = re.compile(r"^<!-- klaus-system-prompt v(\d+) -->\s*$")

_SYSTEM_PROMPT_BODY = (
    "You are Klaus, the study assistant inside Anki. The user is reading lecture PDFs.\n"
    "\n"
    "Every user message ends with a \"[Klaus context]\" block: the PDF and page in view, any selected text, and the page's text (OCR or text layer). An image of that page is attached when available. \"This page\", \"this slide\" and \"this\" mean that page.\n"
    "\n"
    "Answer from the page and the library first. Cite pages as (p. N). If the material does not contain the answer, say so.\n"
    "\n"
    "Your mcp__klaus__* tools reach the user's Anki collection: search_notes (semantic), find_notes/get_notes (Anki search), search_lecture_pdfs, list_decks, list_models, model_fields, add_note, update_note_fields, add_tags, remove_tags, open_in_browse, current_view.\n"
    "\n"
    "Making cards: propose them in prose first; on the user's go-ahead call add_note ONCE PER CARD with deck, model, fields and source_page (the slide it came from). The user approves each card in a dialog; a tool result that says declined or errored means the card was NOT added — never claim otherwise.\n"
)


def _system_prompt_text() -> str:
    return f"<!-- klaus-system-prompt v{SYSTEM_PROMPT_VERSION} -->\n" + _SYSTEM_PROMPT_BODY


# ------------------------------------------------------------------ paths


def _assistant_dir(user_files: str) -> str:
    return os.path.join(user_files, ASSISTANT_DIRNAME)


def sessions_path(user_files: str) -> str:
    return os.path.join(_assistant_dir(user_files), SESSIONS_FILE)


def prompts_dir(user_files: str) -> str:
    return os.path.join(_assistant_dir(user_files), PROMPTS_DIRNAME)


def system_prompt_path(user_files: str) -> str:
    return os.path.join(_assistant_dir(user_files), SYSTEM_PROMPT_FILE)


# ------------------------------------------------------------- atomic I/O


def _atomic_write(path: str, text: str) -> None:
    """Write ``text`` to ``path`` via tmp + ``os.replace`` so a reader can
    never observe a half-written file. Failures are logged, never raised —
    every writer in this module (sessions, prompt defaults, the system
    prompt) must survive a full disk or a locked-down user_files."""
    dest_dir = os.path.dirname(path) or "."
    tmp = os.path.join(dest_dir, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"[klausmate] assistant_sessions: write failed for {path}: {exc}")
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _atomic_write_json(path: str, obj: dict) -> None:
    try:
        text = json.dumps(obj, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        print(f"[klausmate] assistant_sessions: could not serialize {path}: {exc}")
        return
    _atomic_write(path, text)


def _empty_store() -> dict:
    return {"by_pdf": {}, "global": {}}


# --------------------------------------------------------------- sessions


def load(user_files: str) -> dict:
    """The whole sessions store as ``{"by_pdf": {...}, "global": {...}}``.

    A missing file is the routine "nothing recorded yet" case and reads
    back as empty without a peep. A present file that is not valid JSON,
    not an object, or missing/mis-shaped keys is the exceptional case: it
    is logged and STILL reads back as empty, because a corrupt store must
    never take session lookup (or resume) down with it — the next
    ``remember`` call simply starts the file over.
    """
    path = sessions_path(user_files)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _empty_store()
    except (OSError, ValueError) as exc:
        print(f"[klausmate] assistant_sessions: sessions store unreadable, "
              f"treating as empty: {exc}")
        return _empty_store()
    if not isinstance(data, dict):
        print("[klausmate] assistant_sessions: sessions store was not an "
              "object, treating as empty")
        return _empty_store()
    by_pdf = data.get("by_pdf")
    by_pdf = by_pdf if isinstance(by_pdf, dict) else {}
    glob = data.get("global")
    glob = glob if isinstance(glob, dict) else {}
    return {"by_pdf": by_pdf, "global": glob}


def session_for(user_files: str, pdf_safe: str | None) -> str | None:
    """The remembered Claude Code session id for ``pdf_safe`` (or, when
    ``pdf_safe`` is falsy, the global session) — ``None`` when nothing is
    on record for it."""
    data = load(user_files)
    entry = data["by_pdf"].get(pdf_safe) if pdf_safe else data["global"]
    if not isinstance(entry, dict):
        return None
    sid = entry.get("session_id")
    return sid if isinstance(sid, str) and sid else None


def remember(
    user_files: str,
    pdf_safe: str | None,
    session_id: str,
    now=time.time,
) -> None:
    """Record ``session_id`` as the current session for ``pdf_safe`` (or
    the global session when ``pdf_safe`` is falsy), timestamped via the
    injected clock ``now`` (a zero-arg callable returning epoch seconds —
    defaults to ``time.time`` itself, invoked here rather than at import
    time so tests can pin an exact moment)."""
    data = load(user_files)
    entry = {"session_id": session_id, "last_used": _iso(now())}
    if pdf_safe:
        data["by_pdf"][pdf_safe] = entry
    else:
        data["global"] = entry
    _atomic_write_json(sessions_path(user_files), data)


def forget(user_files: str, pdf_safe: str | None) -> None:
    """Drop the remembered session for ``pdf_safe`` (or the global session
    when ``pdf_safe`` is falsy). A no-op, not an error, when nothing was
    on record for it."""
    data = load(user_files)
    changed = False
    if pdf_safe:
        if pdf_safe in data["by_pdf"]:
            del data["by_pdf"][pdf_safe]
            changed = True
    elif data["global"]:
        data["global"] = {}
        changed = True
    if changed:
        _atomic_write_json(sessions_path(user_files), data)


def clear_all(user_files: str) -> None:
    """Wipe every remembered session — the Manage Models "Clear Sessions"
    button's one call (manage_models.save_assistant, Task 8)."""
    _atomic_write_json(sessions_path(user_files), _empty_store())


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


# ---------------------------------------------------------- slash commands


def ensure_defaults(user_files: str) -> None:
    """Seed the three default prompts the FIRST time the folder is looked
    at — no directory yet, or an existing but empty one. Any other content
    (even just one file, default or custom) means "already initialized" and
    this writes nothing, which is what keeps an edited (or deleted)
    default from ever being silently restored."""
    directory = prompts_dir(user_files)
    try:
        existing = os.listdir(directory)
    except FileNotFoundError:
        existing = []
    except OSError as exc:
        print(f"[klausmate] assistant_sessions: could not list prompts "
              f"dir {directory}: {exc}")
        return
    if existing:
        return
    for name, text in DEFAULT_PROMPTS.items():
        _atomic_write(os.path.join(directory, f"{name}.md"), text)


def list_commands(user_files: str) -> list[str]:
    """Sorted command names — the ``.md`` stem of every file in the
    prompts folder. An absent folder is just an empty list, not an error."""
    directory = prompts_dir(user_files)
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return []
    except OSError as exc:
        print(f"[klausmate] assistant_sessions: could not list prompts "
              f"dir {directory}: {exc}")
        return []
    out = []
    for name in names:
        base, ext = os.path.splitext(name)
        if ext.lower() == ".md" and base and not base.startswith("."):
            out.append(base)
    return sorted(out)


def expand(text: str, user_files: str, ctx: dict) -> str:
    """Turn a typed line into what actually gets sent to Claude Code.

    A leading ``/name`` whose prompt file exists is replaced by that
    file's content with the rest of the line appended (blank when there
    is no rest); a leading ``/name`` with no matching file — an unknown
    command, or just a sentence that starts with a slash — passes through
    completely unchanged. Either way, ``$SELECTION``/``$PAGE``/``$PDF``
    are then filled in from ``ctx`` (keys ``selection``/``page_text``/
    ``pdf``; a missing or falsy key fills in as an empty string, never a
    KeyError), so plain typed text carrying those placeholders resolves
    too, not just command bodies.
    """
    ctx = ctx or {}
    m = _COMMAND_RE.match(text)
    if m:
        name = m.group(1)
        path = os.path.join(prompts_dir(user_files), f"{name}.md")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    body = f.read().strip()
                rest = m.group(2).strip()
                text = body + (f"\n\n{rest}" if rest else "")
            except OSError as exc:
                print(f"[klausmate] assistant_sessions: could not read "
                      f"prompt {name!r}: {exc}")
    text = text.replace("$SELECTION", str(ctx.get("selection") or ""))
    text = text.replace("$PAGE", str(ctx.get("page_text") or ""))
    text = text.replace("$PDF", str(ctx.get("pdf") or ""))
    return text


# ----------------------------------------------------------- system prompt


def ensure_system_prompt(user_files: str) -> str:
    """Return the system prompt file's path, writing (or rewriting) it
    first when needed: no file yet, no version marker, or a marker naming
    a version below ``SYSTEM_PROMPT_VERSION``. A file already at (or
    above) the current version is left exactly alone."""
    path = system_prompt_path(user_files)
    try:
        with open(path, encoding="utf-8") as f:
            first_line = f.readline()
    except FileNotFoundError:
        first_line = ""
    except OSError as exc:
        print(f"[klausmate] assistant_sessions: could not read system "
              f"prompt marker: {exc}")
        first_line = ""
    version = None
    match = _MARKER_RE.match(first_line)
    if match:
        try:
            version = int(match.group(1))
        except ValueError:
            version = None
    if version is None or version < SYSTEM_PROMPT_VERSION:
        _atomic_write(path, _system_prompt_text())
    return path
