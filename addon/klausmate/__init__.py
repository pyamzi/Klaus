"""Klausmate — Local AI Autocomplete for Anki.

Provides Copilot-style inline ghost-text completions in the editor (Add /
Edit / Browser) powered by a local Ollama server. Press Tab to accept.
"""

from __future__ import annotations

import atexit
import base64
import html as html_mod
import json
import os
import re
import threading
import time
import traceback
import urllib.parse
from typing import Any, Callable

# #region agent log
def _debug_log_path() -> str:
    repo_cursor = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            ".cursor",
            "debug-16d0b4.log",
        )
    )
    if os.path.isdir(os.path.dirname(repo_cursor)):
        return repo_cursor
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "user_files",
        "debug-16d0b4.log",
    )


def _dbg_autofill(
    location: str,
    message: str,
    data: dict[str, Any],
    hypothesis_id: str,
) -> None:
    try:
        with open(_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "16d0b4",
                        "timestamp": int(time.time() * 1000),
                        "location": location,
                        "message": message,
                        "data": data,
                        "hypothesisId": hypothesis_id,
                    }
                )
                + "\n"
            )
    except Exception:
        pass


# #endregion

from aqt import gui_hooks, mw
from aqt.editor import Editor, EditorWebView
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QComboBox,
    QCursor,
    QDialog,
    QDockWidget,
    QDragEnterEvent,
    QDropEvent,
    QEvent,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QImage,
    QKeySequence,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QApplication,
    QMenu,
    QMessageBox,
    QMouseEvent,
    QObject,
    QPoint,
    QPointF,
    QProgressBar,
    QPushButton,
    QRect,
    QSize,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import askUser, openLink, showInfo, showWarning, tooltip
from aqt.webview import WebContent

from . import pdf_handler
from .claude_api import ClaudeAPIError
from .ollama_client import OllamaClient, OllamaError, OllamaNotRunning
from .ollama_setup import (
    OLLAMA_DOWNLOAD_URL,
    InstallMethod,
    install_methods,
    ollama_reachable,
    run_install_method,
)
from . import ollama_runtime
from .ollama_runtime import (
    RuntimeProvisionError,
    ensure_server,
    full_setup,
    runtime_download_size_hint,
    server_manager,
)

ADDON_DIR = os.path.dirname(__file__)
USER_FILES = os.path.join(ADDON_DIR, "user_files")


# ----------------------------- config helpers -----------------------------


def get_config() -> dict[str, Any]:
    cfg = mw.addonManager.getConfig(__name__) or {}
    return cfg


def write_config(cfg: dict[str, Any]) -> None:
    mw.addonManager.writeConfig(__name__, cfg)


# Old chat_* key → its klaus-brain successor. The retired chat keys with no
# successor are simply dropped.
_LEGACY_KEY_RENAMES = {
    "chat_engine": "klaus_engine",
    "chat_claude_api_key": "claude_api_key",
    "chat_claude_model": "claude_model",
    "chat_turn_timeout_s": "claude_timeout_s",
}
_LEGACY_KEYS_DROPPED = ("chat_system_prompt", "chat_use_pdf_context", "chat_max_tokens")


def _migrate_config() -> None:
    """One-time migration of retired chat_* keys (idempotent).

    The chat panel became the curation page; its engine/key config moved to
    the klaus_* brain keys. Runs at profile open: once meta.json holds no
    chat_* keys this is a no-op (the defaults no longer define them).
    """
    cfg = get_config()
    changed = False
    for old, new in _LEGACY_KEY_RENAMES.items():
        if old not in cfg:
            continue
        val = cfg.pop(old)
        changed = True
        # Never clobber a value already set on the new key.
        has_new = str(cfg.get(new) or "").strip()
        if not has_new and val not in (None, ""):
            cfg[new] = val
    for old in _LEGACY_KEYS_DROPPED:
        if old in cfg:
            cfg.pop(old)
            changed = True
    # One-time guard for the ollama→voyage embedding default flip: an install
    # from before `embedding_provider` existed in config.json would silently
    # inherit the new cloud default while owning an ollama-built index (and no
    # API key). Pin such installs back to ollama; leave fresh installs and
    # deliberate cloud configs alone.
    if not cfg.get("_embed_default_migrated"):
        cfg["_embed_default_migrated"] = True
        changed = True
        from . import curation, embeddings

        if embeddings.provider_name(cfg) != "ollama":
            has_cloud_key = any(
                str(cfg.get(f"embedding_api_key_{p}") or "").strip()
                for p in ("voyage", "openai")
            )
            try:
                index_exists = bool(curation.index_stats().get("exists"))
            except Exception:
                index_exists = False
            is_existing = bool(cfg.get("_first_run_done")) or index_exists
            if is_existing and not has_cloud_key:
                cfg["embedding_provider"] = "ollama"
    if changed:
        write_config(cfg)


_DEFAULT_MODEL = "qwen3:0.6b"

# Autocomplete uses config `system_prompt`. Ask needs its own — the
# sentence-completion system prompt causes garbled output for free-form edits.
_DEFAULT_ASK_SYSTEM = (
    "You help a medical student edit Anki flashcards from lecture material. "
    "Follow the user's instruction. Output plain text only — no markdown, "
    "no quotes, no preamble, no restating the prompt."
)


def resolve_model(cfg: dict[str, Any], key: str) -> str:
    """Return the Ollama tag for ``key`` (e.g. ``autocomplete_model``).

    Falls back to legacy ``model``, then ``_DEFAULT_MODEL``.
    """
    specific = str(cfg.get(key) or "").strip()
    if specific:
        return specific
    legacy = str(cfg.get("model") or "").strip()
    if legacy:
        return legacy
    return _DEFAULT_MODEL


def autocomplete_model(cfg: dict[str, Any] | None = None) -> str:
    return resolve_model(cfg or get_config(), "autocomplete_model")


def ask_model(cfg: dict[str, Any] | None = None) -> str:
    return resolve_model(cfg or get_config(), "ask_model")


_DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"


def klaus_engine(cfg: dict[str, Any] | None = None) -> str:
    """The configured Klaus brain for ⌘K Ask: "ollama" or "claude".

    "claude" only counts when an API key is actually set — otherwise the
    local path is used so a half-configured brain never breaks ⌘K.
    Ghost-text autocomplete always stays on the local Ollama model.
    """
    if cfg is None:
        cfg = get_config()
    engine = str(cfg.get("klaus_engine") or "ollama").strip().lower()
    if engine == "claude" and str(cfg.get("claude_api_key") or "").strip():
        return "claude"
    return "ollama"


def _ask_via_claude(prompt: str, system: str | None, cfg: dict[str, Any]) -> str:
    """Single-shot ⌘K Ask through the Anthropic API (no tools, no history).

    Blocking — call from a QueryOp worker. Raises ClaudeAPIError with a
    user-actionable message on API failures.
    """
    from . import claude_api

    key = str(cfg.get("claude_api_key") or "").strip()
    model = str(cfg.get("claude_model") or "").strip() or _DEFAULT_CLAUDE_MODEL
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 1024,
        "thinking": {"type": "adaptive"},
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    result = claude_api.stream_message(
        key, payload, timeout=float(cfg.get("claude_timeout_s") or 300)
    )
    parts = [
        str(b.get("text") or "")
        for b in (result.get("content") or [])
        if b.get("type") == "text"
    ]
    return "".join(parts).strip()


def client(timeout: float | None = None) -> OllamaClient:
    """Short-timeout client for health checks and model list/delete."""
    cfg = get_config()
    t = float(timeout) if timeout is not None else 30.0
    return OllamaClient(cfg.get("endpoint", "http://localhost:11434"), timeout=t)


def generating_client() -> OllamaClient:
    """Client for /api/generate — Ask can exceed 30s on larger models."""
    cfg = get_config()
    return OllamaClient(
        cfg.get("endpoint", "http://localhost:11434"),
        timeout=float(cfg.get("generate_timeout_s", 180)),
    )


# ----------------------------- completion mode ----------------------------

# Each mode controls how aggressively we generate and how we post-truncate.
_MODE_ORDER = ("word", "phrase", "sentence", "paragraph", "long")
_MODE_PARAMS = {
    "word": {"max_tokens": 8, "stop": [" ", ".", ",", ";", "\n"], "human": "one word"},
    # Phrase mode runs until a real sentence boundary or max-tokens — the
    # Python-side truncator (`_truncate_to_first_clause`) only honours .!? so
    # we don't strand the user mid-clause on a trailing comma.
    "phrase": {"max_tokens": 40, "stop": ["\n"], "human": "one short phrase"},
    "sentence": {
        "max_tokens": 60,
        "stop": ["\n\n", "---"],
        "human": "one complete sentence ending in ., !, or ?",
    },
    "paragraph": {
        "max_tokens": 100,
        "stop": ["\n\n", "---"],
        "human": "two or three complete sentences",
    },
    # `long` is for enumerations / multi-line dumps when the PDF has the answer.
    "long": {
        "max_tokens": 120,
        "stop": ["\n\n", "---"],
        "human": "a complete multi-clause answer",
    },
}

# Phrases that signal "a list or definition is about to come" — when these
# are at the very end of the field, the user is asking the model to fill in
# the substance of an enumeration. Combined with a strong PDF retrieval hit,
# they're our trigger to promote into `long` mode.
_LIST_INCOMING_RE = re.compile(
    r"(?:^|\s)(?:are|is|includes?|consists? of|defined as|the following|"
    r"such as|namely)\s*:?\s*$|:\s*$",
    re.IGNORECASE,
)

# BM25 score threshold above which we trust the PDF enough to enter `long`
# mode. Tuned conservatively — most cards stay in their configured mode.
_LONG_MIN_SCORE = 6.0


def choose_mode(
    field_text: str,
    configured: str,
    top_chunk_score: float = 0.0,
) -> str:
    """Pick an effective mode for this autocomplete request.

    Returns the user's ``completion_mode`` unless the field ends with a
    list/definition cue and PDF retrieval is strong (>= ``_LONG_MIN_SCORE``),
    in which case we promote to ``long`` when the configured mode is at least
    ``phrase`` (word mode is never auto-promoted).
    """
    if configured not in _MODE_ORDER:
        configured = "sentence"
    tail = field_text.rstrip()
    if (
        _LIST_INCOMING_RE.search(tail)
        and top_chunk_score >= _LONG_MIN_SCORE
        and _MODE_ORDER.index(configured) >= _MODE_ORDER.index("phrase")
    ):
        return "long"
    return configured


# ----------------------------- prompt building ----------------------------


# Maximum characters per visible-page chunk fed to the LLM. With ±1 page,
# 3 × 2000 = ~6000 chars, still 3× richer than BM25's ~1600 but keeps the
# prompt small enough that smaller models stay snappy and big models don't
# spend extra seconds on prompt-processing.
_VISIBLE_PAGE_CHAR_CAP = 2000


def retrieve_chunks_for(field_text: str, editor: Editor | None = None) -> list[dict]:
    """Run PDF retrieval once. Callers (request_completion) pass the result
    into both ``choose_mode`` and ``build_prompt`` so we don't fetch twice.

    If ``editor`` has an active sidebar PDF (set by ``PdfSidebar``), the
    visible pages (±1) of that PDF are returned as synthetic chunks with a
    sentinel score of 999.0 — bypassing BM25 entirely. This is the
    "what I'm looking at is what Klaus sees" path. Otherwise the function
    falls back to BM25 across all loaded PDFs.
    """
    if editor is not None:
        active = getattr(editor, "_klausmate_active_pdf", None)
        if active is not None:
            try:
                name, (start, end) = active
                pages = pdf_handler.load_pages(USER_FILES, name)
                if pages:
                    last = len(pages) - 1
                    s = max(0, min(int(start), last))
                    e = max(s, min(int(end), last))
                    sidebar_chunks = [
                        {
                            "source": f"{name}.pdf p.{s + i + 1}",
                            "text": pages[s + i][:_VISIBLE_PAGE_CHAR_CAP],
                            "score": 999.0,
                        }
                        for i in range(e - s + 1)
                        if pages[s + i].strip()
                    ]
                    if sidebar_chunks:
                        return sidebar_chunks
            except Exception:
                # Fall through to BM25 — never let a sidebar error break completion.
                pass

    cfg = get_config()
    top_k = int(cfg.get("retrieval_top_k", 4))
    method = cfg.get("retrieval_method", "keyword")
    if method == "semantic":
        print(
            "[klausmate] retrieval_method=semantic is not yet implemented; "
            "falling back to keyword BM25."
        )
    return pdf_handler.retrieve_relevant_chunks(USER_FILES, field_text, top_k=top_k)


def build_prompt(
    field_text: str,
    mode: str,
    card_ctx: dict | None = None,
    chunks: list[dict] | None = None,
    avoid: list[str] | None = None,
) -> tuple[str, str | None, str | None]:
    """Return (prompt, system_prompt, top_source) for the Ollama call.

    If ``chunks`` is None, retrieve them here. When called from
    ``request_completion`` the chunks have already been fetched and are
    passed through to avoid a second BM25 pass.

    ``avoid`` is an optional list of previously-shown completions for the
    same input. When present, an extra instruction block is appended telling
    the model to produce a MEANINGFULLY DIFFERENT continuation. This is the
    "Cmd+Shift+] cycle past the end" path.
    """
    cfg = get_config()
    system = cfg.get("system_prompt")
    if chunks is None:
        chunks = retrieve_chunks_for(field_text)

    parts: list[str] = []
    if chunks:
        parts.append(
            "AUTHORITATIVE REFERENCE — these excerpts are the ground truth for "
            "this card. Prefer them over your prior knowledge. Quoting or "
            "closely paraphrasing the reference is preferred when relevant."
        )
        parts.append("---")
        for ch in chunks:
            parts.append(f"[source: {ch['source']}]\n{ch['text']}")
        parts.append("---")

    grounding = (
        "When the reference covers the topic, ground the continuation in it — "
        "quoting short phrases verbatim is fine. "
        if chunks
        else ""
    )
    style_rule = (
        f"{grounding}Mirror the user's writing style — capitalization, "
        "abbreviation usage, terseness, and any bullet/prose pattern visible "
        "in the text above. "
    )
    if mode == "long":
        human_mode = _MODE_PARAMS["long"]["human"]
        parts.append(
            "TASK: Complete the following text INLINE. Output ONLY the next "
            f"{human_mode} that should appear immediately after the user's last "
            f"character. Do not repeat the user's text. {style_rule}"
            "Do not add quotes or preamble. Plain text only — no markdown."
        )
    elif mode == "sentence":
        tail_punct = field_text.rstrip()
        cap_rule = (
            "Begin with a capital letter."
            if (not tail_punct) or tail_punct[-1] in ".!?"
            else "Match the user's casing at the start of the continuation."
        )
        parts.append(
            "TASK: Complete the following text INLINE. Output ONLY one complete "
            "sentence that should appear immediately after the user's last "
            "character. The sentence MUST end with ., !, or ?. "
            "Do NOT output a dependent clause or sentence fragment — never start "
            "with Although, Because, Which, That, When, While, If, Unless, Since, "
            "Whereas, As (subordinating), Who, Whom, Whose, Where, After, Before, "
            "Until, Once, Or, And, or But when they only introduce a subordinate "
            f"clause. {cap_rule} Output ONLY new words that continue after the "
            "quoted text — never repeat or rephrase what the user already wrote. "
            f"Do not repeat the user's text. {style_rule}"
            "Do not add quotes or preamble. Plain text only — no markdown."
        )
    elif mode == "paragraph":
        tail_punct = field_text.rstrip()
        cap_rule = (
            "Begin with a capital letter."
            if (not tail_punct) or tail_punct[-1] in ".!?"
            else "Match the user's casing at the start of the continuation."
        )
        parts.append(
            "TASK: Complete the following text INLINE. Output ONLY two or three "
            "complete sentences that should appear immediately after the user's "
            "last character. Every sentence MUST end with ., !, or ?. "
            "Do NOT output dependent-clause fragments. "
            f"{cap_rule} Do not repeat the user's text. {style_rule}"
            "Do not add quotes or preamble. Plain text only — no markdown."
        )
    else:
        human_mode = _MODE_PARAMS.get(mode, _MODE_PARAMS["phrase"])["human"]
        tail_punct = field_text.rstrip()
        starts_new_sentence = (not tail_punct) or tail_punct[-1] in ".!?"
        case_rule = (
            "Begin with a capital letter."
            if starts_new_sentence
            else "Begin in lowercase — do NOT start a new sentence."
        )
        parts.append(
            "TASK: Complete the following text INLINE. Output ONLY the next "
            f"{human_mode} that should appear immediately after the user's last "
            f"character. {case_rule} Do not repeat the user's text. {style_rule}"
            "Do not add quotes or preamble. Plain text only — no markdown."
        )

    # Variant request: tell the model to produce a meaningfully different
    # continuation from the ones already shown. This is the "Cmd+Shift+]
    # cycle past the end" path; the temperature bump in request_completion
    # gives it additional sampling diversity.
    if avoid:
        clean_avoid = [a.strip() for a in avoid if a and a.strip()]
        if clean_avoid:
            parts.append(
                "IMPORTANT: The user has already seen the following "
                "continuation"
                + ("s" if len(clean_avoid) > 1 else "")
                + " and wants something DIFFERENT. Do not repeat or closely "
                "paraphrase any of these — pick a distinct angle, phrasing, "
                "or fact:"
            )
            for i, a in enumerate(clean_avoid, 1):
                parts.append(f"{i}. {a}")

    # NOTE: previously we appended a "This is the '<field>' field of a <kind>
    # note; keep the continuation appropriate (atomic, short, plain text)."
    # hint here. Small autocomplete models (qwen3:0.6b, etc.) were echoing
    # that sentence back verbatim as the completion because it looked too
    # much like natural content. Card-kind / atomicity guidance now lives
    # solely in the system prompt and the TASK directive above.

    parts.append('Text to continue (inside triple quotes):')
    parts.append(f'"""{field_text}"""')

    top_source = chunks[0]["source"] if chunks else None
    return "\n\n".join(parts), system, top_source


# ----------------------------- card context ------------------------------


def _strip_html(s: str) -> str:
    """Strip HTML tags so sibling-field content goes into prompts as plain text."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</?(div|p|span|li|ul|ol|h[1-6])\b[^>]*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    # Common HTML entities (don't pull in html.parser just for this).
    s = (s.replace("&nbsp;", " ")
           .replace("&amp;", "&")
           .replace("&lt;", "<")
           .replace("&gt;", ">")
           .replace("&quot;", '"'))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _set_target_field(editor: Editor, field_name: str) -> None:
    """Remember the last field the user clicked for PDF page insert."""
    if not field_name:
        return
    idx: int | None = None
    try:
        note = getattr(editor, "note", None)
        if note is not None:
            nt = note.note_type() if hasattr(note, "note_type") else note.model()
            if nt:
                names = [f.get("name", "") for f in nt.get("flds", [])]
                if field_name in names:
                    idx = names.index(field_name)
    except Exception:
        pass
    if idx is not None:
        try:
            editor._klausmate_target_field_index = idx  # type: ignore[attr-defined]
            editor._klausmate_target_field_name = field_name  # type: ignore[attr-defined]
            editor.currentField = idx
        except Exception:
            pass


def extract_card_ctx(editor: Editor) -> dict:
    """Best-effort lookup of the focused note's kind, field name, and siblings.

    Returns ``{"kind": "cloze"|"basic"|"", "field": <name>, "siblings": {name: value}}``.
    All values default to empty when anything is unavailable so callers can
    branch safely.
    """
    ctx: dict = {"kind": "", "field": "", "siblings": {}}
    try:
        note = getattr(editor, "note", None)
        if note is None:
            return ctx
        nt = None
        if hasattr(note, "note_type"):
            try:
                nt = note.note_type()
            except Exception:
                nt = None
        if nt is None and hasattr(note, "model"):
            try:
                nt = note.model()
            except Exception:
                nt = None
        if not nt:
            return ctx
        ntype = int(nt.get("type", 0))
        ctx["kind"] = "cloze" if ntype == 1 else "basic"
        flds = nt.get("flds", []) or []
        names = [f.get("name", "") for f in flds]
        values = list(getattr(note, "fields", []) or [])
        idx = getattr(editor, "currentField", None)
        if isinstance(idx, int) and 0 <= idx < len(names):
            ctx["field"] = names[idx]
        for i, name in enumerate(names):
            if i == idx:
                continue
            val = _strip_html(values[i]) if i < len(values) else ""
            if val:
                ctx["siblings"][name] = val
    except Exception:
        pass
    return ctx


# ----------------------------- markdown stripping ------------------------

_MD_FENCE_RE = re.compile(r"^\s*```.*?$", re.MULTILINE)
_MD_DIVIDER_RE = re.compile(r"^\s*[-=*_]{3,}\s*$", re.MULTILINE)
_MD_LIST_RE = re.compile(r"^\s*[*\-+]\s+", re.MULTILINE)
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
_MD_QUOTE_RE = re.compile(r"^\s*>\s+", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_MD_ITAL_RE = re.compile(
    r"(?<![\*\w])\*([^*\n]+?)\*(?![\*\w])|(?<![_\w])_([^_\n]+?)_(?![_\w])"
)
_MD_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BLANKLINES_RE = re.compile(r"\n{3,}")


def strip_markdown(text: str) -> str:
    """Strip common markdown so the output looks like prose."""
    if not text:
        return ""
    text = _MD_FENCE_RE.sub("", text)
    text = _MD_DIVIDER_RE.sub("", text)
    text = _MD_LIST_RE.sub("", text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_QUOTE_RE.sub("", text)
    text = _MD_BOLD_RE.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _MD_ITAL_RE.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _MD_CODE_RE.sub(lambda m: m.group(1), text)
    text = _BLANKLINES_RE.sub("\n\n", text)
    return text.strip()


# ----------------------------- output cleanup ----------------------------

_ABBREV = {
    "dr.", "mr.", "mrs.", "ms.", "st.", "jr.", "sr.",
    "e.g.", "i.e.", "etc.", "vs.", "approx.", "pt.", "pts.",
    "fig.", "no.", "prof.", "cf.", "ca.",
}


def _sentence_end_iter(text: str):
    """Yield end offsets for real sentence boundaries (skips abbreviations)."""
    for m in re.finditer(r"[.!?]+[\s\u201d\u2019\"')\]]*", text):
        snippet = text[: m.start() + 1]
        last_token = re.split(r"\s+", snippet)[-1].lower()
        if last_token in _ABBREV:
            continue
        yield m.end()


def _truncate_to_one_sentence(text: str) -> str:
    """Return text up to and including the first real sentence terminator."""
    if not text:
        return text
    for end in _sentence_end_iter(text):
        return text[:end].rstrip()
    return text


def _truncate_to_n_sentences(text: str, n: int = 3) -> str:
    """Return text through the nth sentence boundary (default up to 3)."""
    if not text or n < 1:
        return text
    last_end = 0
    for i, end in enumerate(_sentence_end_iter(text), start=1):
        last_end = end
        if i >= n:
            break
    if last_end:
        return text[:last_end].rstrip()
    return text


def _truncate_to_first_word(text: str) -> str:
    m = re.match(r"^\s*\S+", text)
    return m.group(0) if m else text


def _truncate_to_paragraph(text: str) -> str:
    """For `long` mode: cut at the first blank-line boundary if any, else
    return the whole text. Ollama already stops on ``\\n\\n``, so this is
    mostly a safety net for cases where the model emits a single multi-line
    paragraph and then a stray empty line.
    """
    if not text:
        return text
    parts = text.split("\n\n", 1)
    return parts[0].rstrip()


def _truncate_to_first_clause(text: str) -> str:
    # User preference (iteration 7): phrase mode ends only at a real sentence
    # boundary or at max-tokens — never at a comma/semicolon/colon, which used
    # to strand the user mid-clause. Abbreviation handling is preserved.
    for m in re.finditer(r"[.!?]", text):
        end = m.end()
        snippet = text[:end]
        last_token = re.split(r"\s+", snippet)[-1].lower()
        if last_token in _ABBREV:
            continue
        return text[:end]
    return text


_WORD_RE = re.compile(r"\w+", re.UNICODE)

_TRAILING_CONNECTOR_RE = re.compile(
    r"\s+(and|or|but|because|which|that|when|where|while|with|by|of|in|on|at|to|from)$",
    re.IGNORECASE,
)

_DEPENDENT_OPENER_RE = re.compile(
    r"^\s*(although|because|which|that|when|while|if|unless|since|whereas|"
    r"as|who|whom|whose|where|after|before|until|once|or|and|but)\b",
    re.IGNORECASE,
)

_TERMINAL_SENTENCE_RE = re.compile(r"[.!?][\s\u201d\u2019\"')\]]*\s*$")


def _strip_overlap_with_tail(text: str, tail: str) -> tuple[str, bool]:
    r"""Strip a leading run of ``text`` that the user already typed at the end
    of ``tail``. Returns ``(stripped_text, user_finished_word)``.

    Two cases:

    * Case A — partial-word echo. ``tail`` ends with ``\w+`` and ``text``
      starts with some suffix of that partial word. Progressively shrink the
      suffix until we find a match; accept it only if either the whole partial
      matched (``cut == len(partial)``) or the next char in ``text`` is a
      non-word char (clean boundary). The bool result is True only in the
      "whole partial matched" case — caller uses it to decide whether to put
      a leading space back.
    * Case B — multi-word echo. Walk back up to 6 words from the end of
      ``tail`` and check if they prefix ``text`` (case-insensitive). Strip the
      matched prefix from ``text``.
    """
    if not text or not tail:
        return text, False
    user_finished = False
    # Case A
    m = re.search(r"(\w+)$", tail)
    if m:
        partial = m.group(1)
        for cut in range(len(partial), 0, -1):
            if text[:cut].lower() == partial[-cut:].lower():
                whole = cut == len(partial)
                rest = text[cut:]
                clean_boundary = (not rest) or (not rest[0].isalnum())
                if whole or clean_boundary:
                    # "finished" is only true when the user wrote the whole
                    # partial AND the model isn't continuing it as one word.
                    user_finished = whole and clean_boundary
                    text = rest.lstrip() if user_finished else rest
                    break
    # Case B (run on whatever Case A left us with).
    tail_words = _WORD_RE.findall(tail)
    text_words = _WORD_RE.findall(text)
    max_k = min(len(tail_words), len(text_words), 6)
    for k in range(max_k, 0, -1):
        if [w.lower() for w in tail_words[-k:]] == [w.lower() for w in text_words[:k]]:
            idx = 0
            for _ in range(k):
                wm = _WORD_RE.search(text, idx)
                if not wm:
                    break
                idx = wm.end()
            text = text[idx:].lstrip()
            user_finished = True  # multi-word match implies finished words
            break
    return text, user_finished


def _longest_suffix_prefix_overlap(tail: str, text: str) -> int:
    """Length of longest k where tail[-k:] == text[:k] (case-insensitive)."""
    tl = tail.rstrip().lower()
    sl = text.lstrip().lower()
    if not tl or not sl:
        return 0
    best = 0
    for k in range(min(len(tl), len(sl)), 0, -1):
        if tl[-k:] == sl[:k]:
            best = k
            break
    return best


def _strip_rephrased_echo(text: str, tail: str, min_overlap: int = 12) -> str:
    """Drop a leading span that repeats the end of ``tail`` (rephrase-tolerant)."""
    k = _longest_suffix_prefix_overlap(tail, text)
    if k >= min_overlap:
        return text[k:].lstrip()
    return text


def _ends_mid_word(text: str) -> bool:
    """True when the caret is after a partial word (no trailing whitespace)."""
    if not text:
        return False
    if text[-1].isspace():
        return False
    if text[-1] in ".!?,;:\"'”’)]}":
        return False
    return True


def _is_mostly_already_in_tail(tail: str, text: str, min_overlap: int = 12) -> bool:
    """True when the suggestion largely repeats text already in the field."""
    if not tail or not text:
        return False
    tl = tail.rstrip().lower()
    sl = text.lstrip().lower()
    if len(sl) >= min_overlap and sl in tl:
        return True
    if _longest_suffix_prefix_overlap(tail, text) >= min_overlap:
        return True
    return False


_THINKING_BLOCK_RE = re.compile(
    r"<(?:redacted_)?think(?:ing)?>\s*.*?\s*</(?:redacted_)?think(?:ing)?>",
    re.DOTALL | re.IGNORECASE,
)
_PROMPT_LABEL_PREFIX_RE = re.compile(
    r"^(?:continuation|task|answer|response|output|text|field|content|input|note)\s*:\s*",
    re.IGNORECASE,
)
_FIELD_LABEL_LINE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9 _-]{0,48}\s*:\s*",
)
_QWEN_CONTROL_TOKEN_RE = re.compile(
    r"/(?:no_think|no_check|think)\b/?",
    re.IGNORECASE,
)
# Catch any sentence shaped like "This is the 'X' field of a Y note..." that
# small models sometimes regurgitate from prompt context. Greedy up to the
# nearest sentence terminator, case-insensitive.
_META_FIELD_ECHO_RE = re.compile(
    r"this is the\s+['\"]?[A-Za-z0-9 _-]{0,40}['\"]?\s+field of (?:a|an|the)\s+[A-Za-z0-9 _-]{0,20}\s+(?:note|card)[^.!?]*[.!?]?",
    re.IGNORECASE,
)


def _strip_llm_artifacts(text: str) -> str:
    """Remove prompt labels and Qwen/Ollama control tokens from model output."""
    if not text:
        return ""
    text = _QWEN_CONTROL_TOKEN_RE.sub("", text)
    text = _THINKING_BLOCK_RE.sub("", text)
    # Strip any "This is the 'Text' field of a cloze note..." regurgitation —
    # see prompt-build site where the original instruction was removed.
    text = _META_FIELD_ECHO_RE.sub("", text)
    text = text.strip()
    while True:
        m = _PROMPT_LABEL_PREFIX_RE.match(text)
        if not m:
            break
        text = text[m.end() :].lstrip()
    return text.strip()


def _strip_field_label_prefix(text: str, tail: str) -> str:
    """Drop ``FieldName: `` when the model echoes the field label + user text."""
    if not text:
        return text
    m = _FIELD_LABEL_LINE_RE.match(text)
    if not m:
        return text
    rest = text[m.end() :].lstrip()
    if not rest:
        return rest
    if _is_mostly_already_in_tail(tail, rest, min_overlap=8):
        return rest
    label = text[: m.end()].strip().rstrip(":").strip().lower()
    if label in ("text", "field", "content", "input", "note", "answer", "response"):
        return rest
    return text


def _is_meaningful_completion(text: str) -> bool:
    """Reject punctuation-only, control-token, or near-empty ghosts."""
    stripped = _strip_llm_artifacts(text)
    if not stripped:
        return False
    if re.fullmatch(r"[\s.!?;:,]+", stripped):
        return False
    if re.search(r"^/[\w]+/", stripped) or re.fullmatch(
        r"/[\w]+/?\.?", stripped
    ):
        return False
    letters = re.sub(r"[^A-Za-z0-9]", "", stripped)
    if len(letters) < 2:
        return False
    real_words = [w for w in re.findall(r"[A-Za-z]{2,}", stripped)]
    return len(real_words) >= 1


def _starts_with_dependent_opener(text: str) -> bool:
    return bool(_DEPENDENT_OPENER_RE.match(text.strip()))


def _ensure_complete_sentence(text: str) -> str:
    """Keep one sentence with terminal punctuation; reject clause fragments."""
    if not text:
        return ""
    text = _truncate_to_one_sentence(text)
    if not text or not _TERMINAL_SENTENCE_RE.search(text):
        return ""
    if _starts_with_dependent_opener(text):
        return ""
    return text


def _strip_trailing_dangle(text: str) -> str:
    """Strip trailing comma/semicolon/colon and any dangling connector word so
    the visible ghost doesn't look like it stopped mid-thought."""
    text = text.rstrip()
    while text and text[-1] in ",;:":
        text = text[:-1].rstrip()
    m = _TRAILING_CONNECTOR_RE.search(text)
    if m:
        text = text[: m.start()].rstrip()
    return text


def clean_completion(text: str, original_tail: str, mode: str = "sentence") -> str:
    """Trim model output to fit ``mode`` and strip common LLM artifacts."""
    if not text:
        return ""
    text = _strip_llm_artifacts(text)
    text = _strip_field_label_prefix(text, original_tail)
    if not text:
        return ""
    if original_tail.endswith((" ", "\n", "\t")):
        text = text.lstrip()
    # Strip wrapping quotes some models add.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1]
    # Strip any leading triple-quote leakage from the prompt framing.
    text = text.lstrip('"').lstrip("'").lstrip()
    # Autocomplete is inline \u2014 cut at first newline EXCEPT in long mode,
    # which is the one place multi-line output is desirable (enumerations
    # and definitions pulled from a PDF chunk).
    if mode != "long" and "\n" in text:
        text = text.split("\n", 1)[0]

    if mode == "word":
        text = _truncate_to_first_word(text)
    elif mode == "phrase":
        text = _truncate_to_first_clause(text)
    elif mode == "long":
        text = _truncate_to_paragraph(text)
    elif mode == "sentence":
        text = _ensure_complete_sentence(text)
    elif mode == "paragraph":
        text = _truncate_to_n_sentences(text, 3)
        if text and not _TERMINAL_SENTENCE_RE.search(text):
            text = ""
    else:
        text = _truncate_to_one_sentence(text)

    text = text.rstrip()
    if not text:
        return ""

    # Strip echoed words/partials the user has already typed at the end of
    # the field (covers the "publicpublic health" bug). When the user had
    # just finished the word (full-partial overlap), restore the leading
    # space so Tab-accept produces "public health" not "publichealth".
    text, user_finished_word = _strip_overlap_with_tail(text, original_tail)
    text = _strip_rephrased_echo(text, original_tail)
    if not text:
        return ""
    if _is_mostly_already_in_tail(original_tail, text):
        return ""
    # Mid-word: reject any multi-token rewrite (stale or slipped-through request).
    if _ends_mid_word(original_tail):
        if len(text.split()) > 1 or _is_mostly_already_in_tail(
            original_tail, text, min_overlap=4
        ):
            return ""
    if user_finished_word and not original_tail.endswith((" ", "\n", "\t")):
        text = " " + text.lstrip()
    # Anti-merge guard: when the user typed a finished word right up to the
    # caret (no trailing space) and the model returns a continuation that
    # would visually fuse (e.g. tail "potential" + text "E = E°"), insert a
    # separator space. Only fires when overlap wasn't detected (otherwise
    # the user_finished_word branch above has already handled it).
    elif (
        text
        and not text[:1].isspace()
        and original_tail
        and original_tail[-1].isalnum()
        and text[0].isalnum()
    ):
        m = re.search(r"\b(\w+)$", original_tail)
        if m and len(m.group(1)) >= 3 and m.group(1).isalpha():
            text = " " + text

    # Clean up a trailing comma/semicolon/colon or dangling connector word
    # so phrase-mode output never looks mid-thought.
    text = _strip_trailing_dangle(text)
    if not text or text in (" ",):
        return ""

    # Sentence / paragraph: final guard (models sometimes ignore the prompt).
    if mode == "sentence":
        text = _ensure_complete_sentence(text)
        if not text:
            return ""
    elif mode == "paragraph":
        text = _truncate_to_n_sentences(text, 3)
        if not text or not _TERMINAL_SENTENCE_RE.search(text):
            return ""

    if original_tail.endswith(text):
        return ""
    if not _is_meaningful_completion(text):
        return ""
    return text


# ----------------------------- error surfacing ----------------------------


# Per-session guard so silent autocomplete failures don't spam dialogs on
# every keystroke. Reset when the user successfully completes any request.
_ollama_setup_warning_shown = False

# Once per session: when a request fails only because the server isn't
# running, try to start a managed/system Ollama silently before dialoging.
_ollama_autostart_attempted = False


def _save_config_on_main(cfg: dict[str, Any]) -> None:
    """write_config marshalled to the main thread — ensure_server may need
    to persist a new endpoint from inside a QueryOp worker thread."""
    mw.taskman.run_on_main(lambda: write_config(cfg))


def _try_silent_autostart(exc: Exception) -> bool:
    """Start a local server in the background instead of showing a dialog.

    Returns True when an attempt was kicked off (caller suppresses its
    dialog — if the start fails, the next error surfaces normally).
    """
    global _ollama_autostart_attempted
    if _ollama_autostart_attempted:
        return False
    if not isinstance(exc, OllamaNotRunning):
        return False
    if "timed out" in (str(exc) or "").lower():
        return False  # server is up, model is just slow — nothing to start
    if not get_config().get("runtime_auto_setup", True):
        return False
    if not (ollama_runtime.find_managed_runtime() or ollama_runtime.find_system_ollama()):
        return False  # nothing to start — needs the one-click setup instead
    _ollama_autostart_attempted = True
    tooltip("Klaus: starting local AI engine…")

    def do() -> Any:
        return ensure_server(get_config(), save_config=_save_config_on_main)

    def on_done(res: Any) -> None:
        if getattr(res, "status", "") in ("reachable", "started"):
            tooltip("Klaus: local AI ready — try again")
        else:
            print(f"[klausmate] silent autostart failed: {getattr(res, 'detail', '')}")

    op = QueryOp(parent=mw, op=lambda col: do(), success=on_done)
    op.failure(lambda e: print(f"[klausmate] silent autostart error: {e}"))
    op.without_collection().run_in_background()
    return True


def _classify_setup_error(exc: Exception, *, model: str) -> tuple[str, str] | None:
    """Return ``(title, body)`` for actionable Ollama-setup failures, or None.

    Handles three structural cases the user can act on:
      - Ollama isn't installed / not running
      - The configured model isn't pulled locally
      - Timeout — likely Ollama is up but the model is huge / cold-loading
    Any other exception returns None (caller falls back to its generic path).
    """
    text = (str(exc) or "").lower()
    if isinstance(exc, OllamaNotRunning):
        if "timed out" in text:
            return (
                "Klaus: Ollama timed out",
                "Klaus reached Ollama but the model didn't respond in time.\n\n"
                "If this is the first request after starting Ollama, the model "
                "may still be loading — try again in a few seconds. Otherwise "
                "switch to a smaller model in Klaus → Settings, or raise "
                "generate_timeout_s in the add-on config.",
            )
        return (
            "Klaus: Ollama isn't running",
            "Klaus needs the Ollama background service to generate text "
            "locally — and it can set that up for you automatically.\n\n"
            "Click Set up automatically below, or install Ollama yourself "
            "from https://ollama.com.",
        )
    if "model" in text and ("not found" in text or "pull" in text or "404" in text):
        return (
            f"Klaus: model '{model}' isn't installed",
            f"The model '{model}' isn't available on this machine yet. "
            "You have two options:\n\n"
            f"• Run `ollama pull {model}` in a terminal.\n"
            "• Or open Klaus → Manage models… and pull it from there.",
        )
    return None


def _show_ollama_setup_error(
    exc: Exception, *, model: str, parent: Any = None, once_per_session: bool = False
) -> bool:
    """Show an actionable dialog when ``exc`` is a known setup problem.

    Returns True if the helper handled the error (caller can skip its
    fallback message). When ``once_per_session`` is True the dialog is
    suppressed after the first call this session — used by autocomplete
    so a single Ollama outage doesn't spam dialogs on every keystroke.
    """
    classified = _classify_setup_error(exc, model=model)
    if classified is None:
        return False
    if _try_silent_autostart(exc):
        return True  # background start kicked off; suppress this dialog
    global _ollama_setup_warning_shown
    if once_per_session and _ollama_setup_warning_shown:
        return True
    _ollama_setup_warning_shown = True
    title, body = classified
    msg = QMessageBox(parent or mw)
    msg.setWindowTitle(title)
    msg.setText(body)
    msg.setIcon(QMessageBox.Icon.Warning)
    setup_btn = msg.addButton(
        "Set up automatically", QMessageBox.ButtonRole.ActionRole
    )
    manage_btn = msg.addButton("Manage models…", QMessageBox.ButtonRole.ActionRole)
    msg.addButton("Dismiss", QMessageBox.ButtonRole.AcceptRole)
    msg.exec()
    clicked = msg.clickedButton()
    if clicked is setup_btn:
        try:
            manage_models_dialog(setup=True)
        except Exception:
            pass
    elif clicked is manage_btn:
        try:
            manage_models_dialog()
        except Exception:
            pass
    return True


# ----------------------------- completion flow ----------------------------


def request_completion(
    editor: Editor,
    request_id: int,
    field_text: str,
    card_ctx: dict | None = None,
    avoid: list[str] | None = None,
    variant: bool = False,
) -> None:
    """Run an Ollama request in the background and push the result back to JS.

    ``avoid`` is an optional list of previously-shown completions for this
    same field text — used when the user cycles past the end of the candidate
    list via Cmd+Shift+]. The prompt instructs the model to produce a
    DIFFERENT continuation. A small temperature bump improves diversity.
    ``variant`` flags the response so the JS side knows whether to append to
    the candidate list (variant=true) or replace it (variant=false).
    """
    if not field_text.strip():
        return
    if _ends_mid_word(field_text):
        send_completion_to_js(
            editor, request_id, "", None,
            variant=variant, field_text=field_text,
        )
        return
    cfg = get_config()
    model = autocomplete_model(cfg)
    base_temp = float(cfg.get("temperature", 0.2))
    # Variant requests get more diversity. We bump temperature by 0.4 (capped
    # at 1.2) per variant request — using len(avoid) as the variant index so
    # later variants get progressively more diverse.
    extra = 0.4 * len(avoid) if variant and avoid else 0.0
    temperature = min(1.2, base_temp + extra)
    top_p = float(cfg.get("top_p", 0.9))
    top_k = int(cfg.get("top_k", 40))
    repeat_penalty = float(cfg.get("repeat_penalty", 1.1))
    configured_mode = cfg.get("completion_mode", "sentence")
    # Retrieve once; pass to both choose_mode (needs top score for the
    # `long`-mode auto-promote) and build_prompt (needs chunk text).
    # `editor` is threaded through so an active PDF sidebar can override
    # BM25 with the visible-pages content.
    chunks = retrieve_chunks_for(field_text, editor=editor)
    top_score = float(chunks[0].get("score", 0.0)) if chunks else 0.0
    mode = choose_mode(field_text, configured_mode, top_chunk_score=top_score)
    params = _MODE_PARAMS[mode]
    def do() -> tuple[str, str | None]:
        prompt, system, source = build_prompt(
            field_text, mode, card_ctx,
            chunks=chunks, avoid=avoid,
        )
        raw = generating_client().generate(
            model=model,
            prompt=prompt,
            system=system,
            max_tokens=params["max_tokens"],
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            stop=params["stop"],
        )
        return raw, source

    def on_success(result: tuple[str, str | None]) -> None:
        raw, source = result
        completion = clean_completion(raw, field_text, mode=mode)
        # #region agent log
        _dbg_autofill(
            "request_completion.on_success",
            "autocomplete cleaned",
            {
                "raw_preview": (raw or "")[:100],
                "cleaned": (completion or "")[:100],
                "rejected_empty": not bool(completion),
                "tail_preview": field_text[-60:],
                "mid_word": _ends_mid_word(field_text),
                "mode": mode,
                "runId": "midword-fix",
            },
            "H",
        )
        # #endregion
        # A successful round-trip means Ollama is reachable and the model
        # is loaded — re-arm the setup-error dialog so a future Ollama
        # restart will surface a fresh warning.
        global _ollama_setup_warning_shown
        _ollama_setup_warning_shown = False
        send_completion_to_js(
            editor, request_id, completion, source,
            variant=variant, field_text=field_text,
        )

    def on_failure(exc: Exception) -> None:
        # Format the actual exception we were handed — never call
        # traceback.print_exc() here, because it pulls from sys.exc_info()
        # and prints "NoneType: None" when no exception is currently active
        # (which is the case in async QueryOp callbacks). That bogus output
        # ends up in Anki's error dialog.
        if not isinstance(exc, OllamaNotRunning):
            tb = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            print("[klausmate] completion failed:\n" + tb)
        send_completion_to_js(
            editor, request_id, "", None,
            variant=variant, field_text=field_text,
        )
        # Show a clear setup dialog at most once per session for structural
        # failures (Ollama down, missing model). Fall back to the silent
        # tooltip for everything else so autocomplete stays unobtrusive.
        handled = _show_ollama_setup_error(
            exc,
            model=resolve_model(get_config(), "autocomplete_model"),
            parent=editor.widget,
            once_per_session=True,
        )
        if handled:
            return
        if isinstance(exc, OllamaError):
            tooltip(f"Klaus: {exc}", parent=editor.widget)

    op = QueryOp(parent=editor.widget, op=lambda col: do(), success=on_success)
    op.failure(on_failure)
    op.without_collection().run_in_background()


def send_completion_to_js(
    editor: Editor,
    request_id: int,
    completion: str,
    source: str | None = None,
    variant: bool = False,
    field_text: str = "",
) -> None:
    payload = json.dumps(
        {
            "id": request_id,
            "completion": completion,
            "source": source,
            "variant": bool(variant),
            "field_text": field_text,
        }
    )
    js = f"window.klausmate && window.klausmate.onCompletion({payload});"
    try:
        editor.web.eval(js)
    except Exception:
        pass


# ----------------------------- inline Ask (Cmd+K) -------------------------


def build_ask_prompt(
    user_instruction: str,
    field_text: str,
    card_ctx: dict | None = None,
    editor: Editor | None = None,
) -> tuple[str, str | None]:
    """Build a prompt for the Cmd+K inline ask flow.

    Outputs are plain-text and atomic by default. The model is told how to
    behave per card kind / field (cloze vs basic; Front vs Back; etc.).
    When an editor with an active sidebar PDF is provided, the visible
    pages (±1) are used as reference instead of BM25.
    """
    cfg = get_config()
    system = cfg.get("ask_system_prompt") or _DEFAULT_ASK_SYSTEM
    query = (user_instruction + " " + field_text).strip()
    chunks = retrieve_chunks_for(query, editor=editor)

    cc = card_ctx or {}
    kind = cc.get("kind", "")
    field = cc.get("field", "")
    siblings = cc.get("siblings", {}) or {}
    field_lower = field.lower()

    parts: list[str] = []
    if chunks:
        parts.append("REFERENCE (context only — do not summarize, do not output):")
        parts.append("---")
        for ch in chunks:
            parts.append(f"[source: {ch['source']}]\n{ch['text']}")
        parts.append("---")

    parts.append(
        "TASK: The user is writing an Anki flashcard. Follow their instruction "
        "and produce the text they want.\n"
        "RULES:\n"
        "- Plain text ONLY. No markdown of any kind: no **bold**, no *italics*, "
        "no `code`, no bullets (* - +), no headings (#), no dividers (---), "
        "no code fences.\n"
        "- Anki cards are ATOMIC. Default to ONE short factual statement "
        "(one fact per card). Only produce multiple lines if the user's "
        "instruction explicitly asks for a list.\n"
        "- No preamble (\"Sure!\", \"Here's…\"), no quotes around the answer, "
        "no restating the instruction, no closing remarks."
    )

    if kind == "cloze":
        parts.append(
            "This is a Cloze note. Output a single short factual statement in "
            "plain text. Do NOT add {{c1::…}} markup — the user marks cloze "
            "deletions manually."
        )
    elif kind == "basic" and field_lower == "front":
        parts.append(
            "This is the Front field of a Basic note. Output ONLY a short cue "
            "or question (one sentence max)."
        )
    elif kind == "basic" and field_lower == "back":
        # Pull the Front content (case-insensitive lookup) so the model
        # answers the actual question the user wrote.
        front_val = ""
        for k, v in siblings.items():
            if k.lower() == "front":
                front_val = v
                break
        if front_val:
            parts.append(
                f'Front field (already written by the user):\n"""{front_val}"""'
            )
            parts.append(
                "This is the Back field. Output a concise answer that fits the "
                "Front above. Plain text, no preamble."
            )
        else:
            parts.append(
                "This is the Back field of a Basic note. Output a concise "
                "answer (plain text, no preamble)."
            )
    elif kind:
        parts.append(
            f"This is the '{field or 'unnamed'}' field of a {kind} note. "
            "Output a concise, plain-text, atomic statement appropriate for it."
        )

    parts.append(f"User instruction: {user_instruction.strip()}")
    if field_text.strip():
        parts.append("Current field text (for context):")
        parts.append(f'"""{field_text}"""')
    parts.append("Output:")
    return "\n\n".join(parts), system


def request_ask(
    editor: Editor,
    request_id: int,
    user_prompt: str,
    field_text: str,
    card_ctx: dict | None = None,
) -> None:
    """Run an inline-ask request in the background and stream the result back."""
    if not user_prompt.strip():
        return
    cfg = get_config()
    engine = klaus_engine(cfg)
    model = ask_model(cfg)
    temperature = float(cfg.get("temperature", 0.2))
    top_p = float(cfg.get("top_p", 0.9))
    top_k = int(cfg.get("top_k", 40))
    repeat_penalty = float(cfg.get("repeat_penalty", 1.1))

    def do() -> str:
        prompt, system = build_ask_prompt(user_prompt, field_text, card_ctx, editor=editor)
        if engine == "claude":
            return _ask_via_claude(prompt, system, cfg)
        return generating_client().chat(
            model=model,
            user_content=prompt,
            system=system,
            # Cmd+K ASK can produce richer, multi-fact outputs when the user
            # explicitly asks for them — 600 tokens fits a multi-sentence
            # explanation or short bulleted list. Atomic-by-default behavior
            # is still enforced by the prompt; this just removes the ceiling
            # for explicit asks like "expand on this" or "give me 3 facts".
            max_tokens=600,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            stop=["</output>", "User instruction:"],
        )

    def _send(text: str) -> None:
        payload = json.dumps({"id": request_id, "text": text})
        try:
            editor.web.eval(
                f"window.klausmate && window.klausmate.onAskResult({payload});"
            )
        except Exception:
            pass

    def on_success(raw: str) -> None:
        out = (raw or "").strip()
        if out.startswith('"""'):
            out = out[3:]
        if out.endswith('"""'):
            out = out[:-3]
        out = strip_markdown(out.strip())
        _send(out)

    def on_failure(exc: Exception) -> None:
        # See note in request_completion: never use traceback.print_exc() in
        # async callbacks — it prints "NoneType: None" outside `except:`
        # blocks and trips Anki's error dialog.
        tb = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        print("[klausmate] ask failed:\n" + tb)
        _send("")
        # Cmd+K is user-initiated, so always surface the real reason in
        # an actionable dialog. Claude-brain failures carry their own
        # user-facing message (bad key, rate limit, overload). The Ollama
        # helper covers Ollama-down, missing model, and timeout cases.
        # Anything else falls through to the generic warning.
        if isinstance(exc, ClaudeAPIError):
            showWarning("Klaus ask failed.\n\n" + exc.user_message())
            return
        handled = _show_ollama_setup_error(
            exc, model=ask_model(), parent=editor.widget
        )
        if not handled:
            showWarning(
                "Klaus ask failed.\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "If the message mentions a missing model, run "
                f"`ollama pull {ask_model()}` in a terminal."
            )

    op = QueryOp(parent=editor.widget, op=lambda col: do(), success=on_success)
    op.failure(on_failure)
    op.without_collection().run_in_background()



# ----------------------------- browser: search & hotkeys -----------------


# System prompt for the Browse search converter. Kept tight — the user's
# query is short, and we want most of the context budget spent on the
# syntax cheatsheet and example transformations.
_DEFAULT_SEARCH_SYSTEM = (
    "You convert natural-language requests into Anki Browse search syntax. "
    "Output ONLY the search query: no preamble, no explanation, no markdown, "
    "no surrounding quotes.\n\n"
    "ANKI SEARCH SYNTAX CHEATSHEET:\n"
    "- Plain text searches all fields. Multiple words = AND. 'or' between "
    "terms = OR. Prefix '-' = NOT. Group with parentheses.\n"
    "- Exact phrase: \"a dog\" (in double quotes). Word boundary: w:dog "
    "(matches 'dog' but not 'doggy'). Wildcards: _ (one char), * (any chars).\n"
    "- Field-specific: front:dog (exact), front:*dog* (contains), front: "
    "(empty), front:_* (non-empty).\n"
    "- Tags: tag:animal (includes subtags), tag:none, tag:ani*.\n"
    "- Decks: deck:french, deck:\"french words\", deck:filtered, "
    "-deck:filtered.\n"
    "- Card types / note types: card:1 (by position), card:forward "
    "(by name). note:basic.\n"
    "- States: is:due, is:new, is:learn, is:review, is:suspended, "
    "is:buried.\n"
    "- Flags: flag:0 (none), flag:1 (red), 2 (orange), 3 (green), "
    "4 (blue), 5 (pink), 6 (turquoise), 7 (purple).\n"
    "- Properties: prop:ivl>=10, prop:due=1 (due tomorrow), prop:due=-1 "
    "(due yesterday), prop:reps<10, prop:lapses>3, prop:ease!=2.5, "
    "prop:pos<=100.\n"
    "- Added: added:7 (last 7 days). Edited: edited:7. Introduced: "
    "introduced:365 (first-answered in last N days).\n"
    "- Rated: rated:N (any rating in last N days), rated:N:R "
    "(R = 1 Again, 2 Hard, 3 Good, 4 Easy). Use prop:rated=-N for exact "
    "N-days-ago.\n"
    "- Regex: re:pattern (anywhere) or field:re:pattern.\n"
    "- Case/accent-insensitive: nc:text.\n"
    "- IDs: nid:123, cid:123,456.\n\n"
    "EXAMPLES:\n"
    "- 'cards I marked easy in the last week' → rated:7:4\n"
    "- 'new cards in deck Pharmacology' → deck:Pharmacology is:new\n"
    "- 'cards I added today' → added:1\n"
    "- 'lapsed cards with ease below 2' → is:learn is:review prop:ease<2\n"
    "- 'red flagged cards due tomorrow' → flag:1 prop:due=1\n"
    "- 'notes tagged Pharm with front field empty' → tag:Pharm front:\n"
    "- 'cards I rated again 7 days ago' → prop:rated=-7\n\n"
    "Now convert the user's request to a valid Anki search query. Output "
    "ONLY the query."
)


def request_search_conversion(
    browser: Any,
    query: str,
    on_result: Callable[[str], None],
) -> None:
    """Send a natural-language query through the Ask model; deliver the
    Anki-syntax result to ``on_result`` on the main thread. Errors surface
    via the shared ``_show_ollama_setup_error`` helper (so missing-Ollama /
    missing-model dialogs are consistent with the editor flows).
    """
    cfg = get_config()
    model = ask_model(cfg)
    temperature = float(cfg.get("temperature", 0.2))
    top_p = float(cfg.get("top_p", 0.9))
    top_k = int(cfg.get("top_k", 40))
    repeat_penalty = float(cfg.get("repeat_penalty", 1.1))

    def do() -> str:
        ollama = generating_client()
        return ollama.chat(
            model=model,
            user_content=query,
            system=_DEFAULT_SEARCH_SYSTEM,
            max_tokens=200,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
        )

    def on_success(raw: str) -> None:
        out = _strip_llm_artifacts((raw or "").strip())
        # Strip leading code-fence backticks / surrounding quotes the
        # model may add despite the system prompt.
        out = out.strip()
        if out.startswith("```"):
            out = out.lstrip("`").strip()
            if out.endswith("```"):
                out = out[:-3].strip()
        if out.startswith("`") and out.endswith("`") and len(out) > 2:
            out = out[1:-1].strip()
        if (
            (out.startswith('"') and out.endswith('"'))
            or (out.startswith("'") and out.endswith("'"))
        ) and len(out) > 2:
            out = out[1:-1].strip()
        on_result(out)

    def on_failure(exc: Exception) -> None:
        handled = _show_ollama_setup_error(exc, model=model, parent=browser)
        if not handled:
            showWarning(
                f"Klaus search conversion failed.\n\n"
                f"{type(exc).__name__}: {exc}"
            )

    op = QueryOp(parent=browser, op=lambda col: do(), success=on_success)
    op.failure(on_failure)
    op.without_collection().run_in_background()


def _remap_browser_mark_hotkey(browser: Any) -> None:
    """Re-bind Anki's Browser mark hotkey to Ctrl+Alt+K so Klaus can own
    Ctrl/Cmd+K consistently across the editor and the Browse search bar.

    Targets ``browser.form.actionToggle_Mark`` directly (Anki 25.x and
    earlier expose it under that name) and falls back to a generic scan
    for forks that rename the action. The original Ctrl+Shift+M was a
    bad choice — it collides with Anki's existing ``actionChangeModel``
    (Change Note Type), which silently breaks both shortcuts via Qt's
    ambiguity resolution. Ctrl+Alt+K is unbound in stock Anki and keeps
    the "K for mark" mnemonic.
    """
    try:
        target = QKeySequence("Ctrl+K")
        new_seq = QKeySequence("Ctrl+Alt+K")
    except Exception:
        return

    def _apply(action: Any) -> bool:
        try:
            action.setShortcuts([new_seq])
            return True
        except Exception:
            return False

    # Direct path: Anki exposes the mark action on the form.
    form = getattr(browser, "form", None)
    direct = getattr(form, "actionToggle_Mark", None) if form is not None else None
    if direct is not None and _apply(direct):
        print("[klausmate] mark hotkey: actionToggle_Mark → Ctrl+Alt+K")
        return

    # Fallback for forks that rename the action: scan every QAction for
    # an existing Ctrl+K binding and reassign whichever one we find.
    try:
        actions = browser.findChildren(QAction)
    except Exception:
        return
    for action in actions:
        try:
            seqs = list(action.shortcuts() or [])
            primary = action.shortcut()
            if primary is not None and not primary.isEmpty():
                seqs.append(primary)
        except Exception:
            continue
        for sc in seqs:
            try:
                if (
                    sc.matches(target)
                    == QKeySequence.SequenceMatch.ExactMatch
                ):
                    if _apply(action):
                        name = (
                            getattr(action, "objectName", lambda: "?")()
                            or "?"
                        )
                        print(
                            f"[klausmate] mark hotkey (fallback): {name}"
                            " → Ctrl+Alt+K"
                        )
                    return
            except Exception:
                continue


class _KlausSearchAskPopover(QFrame):
    """Cmd+K popover for the Browse search bar.

    Visually mirrors the editor's JS ``klausmate-ask`` popover (Ask label
    left, free-form input middle, ↵/Esc hint right) so the two ⌘K
    surfaces feel identical. User types their natural-language request,
    presses Enter, and Klaus converts it to Anki search syntax — the
    result replaces the search bar text and the search runs.
    """

    def __init__(self, browser: Any, line_edit: QLineEdit) -> None:
        # Qt.Popup auto-closes when the user clicks outside — exactly the
        # dismiss behavior the JS popover gets for free in the webview.
        super().__init__(
            browser,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self._browser = browser
        self._line_edit = line_edit
        # Card background + thin Klaus-blue border with soft shadow,
        # rounded bottom corners to anchor visually to the search bar
        # above. Matches the JS popover's chrome as closely as Qt allows.
        self.setStyleSheet(
            "_KlausSearchAskPopover {"
            " background: rgba(252, 252, 253, 0.98);"
            " border: 1px solid rgba(58, 130, 247, 0.45);"
            " border-radius: 6px;"
            "}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        label = QLabel("Ask", self)
        label.setStyleSheet(
            "color: rgba(58, 130, 247, 0.95);"
            " font-weight: 500;"
            " font-size: 12px;"
            " background: transparent;"
        )
        lay.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText(
            "Ask Klaus to convert this to an Anki search"
        )
        self._input.setFrame(False)
        self._input.setStyleSheet(
            "background: transparent;"
            " border: 0;"
            " font-size: 13px;"
            " padding: 2px 0;"
        )
        lay.addWidget(self._input, 1, Qt.AlignmentFlag.AlignVCenter)

        hint = QLabel("↵ run · Esc cancel", self)
        hint.setStyleSheet(
            "color: rgba(120, 120, 120, 0.85);"
            " font-size: 12px;"
            " font-weight: 500;"
            " background: transparent;"
        )
        lay.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)

        self._input.returnPressed.connect(self._on_submit)

    def _on_submit(self) -> None:
        query = self._input.text().strip()
        if not query:
            self.hide()
            return
        self.hide()
        tooltip("Klaus: converting query…", parent=self._browser)

        def on_result(converted: str) -> None:
            if not converted:
                tooltip(
                    "Klaus: empty response (search bar unchanged)",
                    parent=self._browser,
                )
                return
            self._line_edit.setText(converted)
            # Trigger Anki's search using whichever entry point this
            # build exposes; fall back to firing returnPressed.
            for attr in ("onSearchActivated", "search", "onSearch"):
                fn = getattr(self._browser, attr, None)
                if callable(fn):
                    try:
                        fn()
                        return
                    except Exception:
                        continue
            try:
                self._line_edit.returnPressed.emit()
            except Exception:
                pass

        request_search_conversion(self._browser, query, on_result)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)

    def show_anchored_to(self, anchor: QWidget) -> None:
        rect = anchor.rect()
        anchor_bottom_left = anchor.mapToGlobal(rect.bottomLeft())
        self.setFixedWidth(max(360, rect.width()))
        # Slight vertical gap so the popover doesn't sit flush against
        # the search bar's bottom border.
        self.move(anchor_bottom_left.x(), anchor_bottom_left.y() + 2)
        # Always start empty — matches the editor's JS Ask popover, which
        # treats the popover input as a fresh free-form instruction.
        self._input.clear()
        self.show()
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)


def _install_browser_search_klaus(browser: Any) -> None:
    """Bind Ctrl/Cmd+K inside the Browse search edit to open the Klaus
    Ask popover — mirroring the editor's ⌘K behavior. User types their
    natural-language query into the popover; on Enter Klaus converts it
    to Anki search syntax and runs the search.

    Anki's search widget is a ``QComboBox`` (``browser.form.searchEdit``)
    with an internal ``QLineEdit``. Depending on whether the user clicks
    the line itself or the dropdown arrow / combobox chrome, Qt focus
    may land on EITHER widget. We bind the same shortcut on both with
    ``WidgetWithChildrenShortcut`` so either focus state triggers it.
    """
    line_edit = _find_browser_search_line_edit(browser)
    if line_edit is None:
        print("[klausmate] search ⌘K: could not locate searchEdit line edit")
        return

    # The QComboBox parent of the line edit — Anki's standard search bar.
    search_box = getattr(getattr(browser, "form", None), "searchEdit", None)

    try:
        popover = _KlausSearchAskPopover(browser, line_edit)
    except Exception as exc:
        print(f"[klausmate] search popover construction failed: {exc}")
        return

    # Strong reference on the browser so the popover survives GC.
    browser._klausmate_search_popover = popover  # type: ignore[attr-defined]

    def on_invoke() -> None:
        try:
            popover.show_anchored_to(search_box or line_edit)
        except Exception as exc:
            print(f"[klausmate] search popover show failed: {exc}")

    # Existing shortcut list on the browser (carries the install across
    # the hook lifetime so QShortcut objects don't get GC'd).
    existing = getattr(browser, "_klausmate_shortcuts", None)
    if existing is None:
        existing = []
        browser._klausmate_shortcuts = existing  # type: ignore[attr-defined]

    def _bind(widget: Any, label: str) -> None:
        if widget is None:
            return
        try:
            sc = QShortcut(QKeySequence("Ctrl+K"), widget)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(on_invoke)
            existing.append(sc)
            print(
                f"[klausmate] search ⌘K bound to {label}: "
                f"{type(widget).__name__}"
            )
        except Exception as exc:
            print(f"[klausmate] search ⌘K bind to {label} failed: {exc}")

    _bind(line_edit, "lineEdit")
    if search_box is not None and search_box is not line_edit:
        _bind(search_box, "searchEdit (QComboBox)")


def _find_browser_search_line_edit(browser: Any) -> Any:
    """Locate the QLineEdit backing the Browser's search box.

    Anki's Browser typically exposes ``browser.form.searchEdit`` as a
    ``QComboBox``; the editable line is ``.lineEdit()``. Older / newer
    versions may expose a bare ``QLineEdit`` directly, or rename the
    attribute, so we try a few paths.
    """
    candidates: list[Any] = []
    form = getattr(browser, "form", None)
    if form is not None:
        for attr in ("searchEdit", "search_edit", "searchBox", "search"):
            obj = getattr(form, attr, None)
            if obj is not None:
                candidates.append(obj)
    for obj in candidates:
        # If the object exposes lineEdit() (QComboBox), prefer that.
        line_edit = getattr(obj, "lineEdit", None)
        if callable(line_edit):
            try:
                le = line_edit()
                if le is not None:
                    return le
            except Exception:
                pass
        # Otherwise hope it already IS a QLineEdit.
        if isinstance(obj, QLineEdit):
            return obj
    # Last-ditch: any QLineEdit child of the browser whose objectName
    # contains "search".
    try:
        for le in browser.findChildren(QLineEdit):
            if "search" in (le.objectName() or "").lower():
                return le
    except Exception:
        pass
    return None


# One-time-per-session guard for the sidebar self-heal. A prior broken
# build of this add-on could persist a zero-width / detached sidebar into
# the profile; we force it back open the first time Browse opens in a
# session, then respect the user's toggle on every subsequent open so the
# sidebar toggle button's state actually sticks.
_KLAUS_BROWSE_LAYOUT_HEALED = False


def _reset_browse_layout_to_defaults(browser: Any) -> None:
    """Force the Browse window's sidebar + splitter back to Anki's stock
    layout, undoing any leftover state from the now-removed dock-
    wrapping helpers.

    Anki persists ``QMainWindow.saveState()`` + ``QSplitter.saveState()``
    to the user's profile on browser close (see
    ``aqt/browser/browser.py:433-434``). If a previous build of this
    add-on moved the sidebar around or collapsed the editor splitter,
    that broken layout is restored on every subsequent open even after
    the offending code is gone. This helper re-anchors the sidebar to
    the side Anki originally docked it on and reinstates a sane
    splitter ratio if one pane is collapsed.

    On browser close, Anki re-saves the corrected state — so after one
    open this normally only no-ops on subsequent runs.
    """
    # ---- sidebar ----
    global _KLAUS_BROWSE_LAYOUT_HEALED
    dock = getattr(browser, "sidebarDockWidget", None)
    if dock is not None:
        try:
            # Snapshot the visibility Anki restored from the profile (or
            # the user last chose) BEFORE we touch the dock — addDockWidget
            # can implicitly re-show a hidden dock.
            was_visible = dock.isVisible()
            rtl = (
                browser.layoutDirection()
                == Qt.LayoutDirection.RightToLeft
            )
            area = (
                Qt.DockWidgetArea.RightDockWidgetArea
                if rtl
                else Qt.DockWidgetArea.LeftDockWidgetArea
            )
            # Restore Anki's original constraints (in case a prior
            # build of this add-on unlocked them).
            dock.setAllowedAreas(area)
            dock.setFloating(False)
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetClosable
            )
            # Re-anchor to the correct side regardless of the layout
            # restoreState() pulled out of the profile.
            browser.addDockWidget(area, dock)
            # Anki uses an empty title-bar widget to suppress the
            # drag-handle. Re-establish that.
            dock.setTitleBarWidget(QWidget())
            if not _KLAUS_BROWSE_LAYOUT_HEALED:
                # First Browse open this session: force the sidebar open
                # once to self-heal any zero-width/hidden state left by an
                # earlier build.
                dock.setVisible(True)
                _KLAUS_BROWSE_LAYOUT_HEALED = True
            else:
                # Subsequent opens: preserve the user's last choice so the
                # sidebar toggle button's state persists across reopens.
                dock.setVisible(was_visible)
            print("[klausmate] sidebar re-anchored to default position")
        except Exception as exc:
            print(f"[klausmate] sidebar reset failed: {exc}")

    # ---- editor splitter ----
    form = getattr(browser, "form", None)
    splitter = getattr(form, "splitter", None) if form is not None else None
    if splitter is not None and splitter.count() >= 2:
        try:
            sizes = list(splitter.sizes())
            # A pane of < 4 px is a degenerate state — likely a leftover
            # from when the editor was extracted into a dock and the
            # splitter was forced to [width, 0]. Restore the form's
            # ~3:1 default ratio.
            if any(s < 4 for s in sizes):
                total = max(1, sum(sizes)) or 800
                splitter.setSizes(
                    [int(total * 0.75), int(total * 0.25)]
                )
                print(
                    f"[klausmate] editor splitter reset from {sizes} "
                    "to 3:1 default"
                )
        except Exception as exc:
            print(f"[klausmate] editor splitter reset failed: {exc}")


_KLAUS_TOGGLE_QSS = (
    "QToolButton {"
    " border: 1px solid rgba(120, 120, 120, 0.35);"
    " border-radius: 5px;"
    " font-size: 14px;"
    " color: rgba(80, 80, 80, 0.95);"
    " background: rgba(120, 120, 120, 0.06);"
    "}"
    "QToolButton:hover {"
    " color: rgba(58, 130, 247, 0.95);"
    " border-color: rgba(58, 130, 247, 0.45);"
    " background: rgba(58, 130, 247, 0.10);"
    "}"
    "QToolButton:checked {"
    " color: rgba(58, 130, 247, 0.95);"
    " border-color: rgba(58, 130, 247, 0.55);"
    " background: rgba(58, 130, 247, 0.14);"
    "}"
)


def _make_klaus_toggle(glyph: str, tip: str, checked: bool) -> QToolButton:
    btn = QToolButton()
    btn.setText(glyph)
    btn.setFixedSize(26, 26)
    btn.setToolTip(tip)
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setStyleSheet(_KLAUS_TOGGLE_QSS)
    return btn


class _VisibilityWatcher(QObject):
    """Calls ``on_change(visible)`` whenever ``target`` is shown or
    hidden — keeps a toggle button honest when other code (e.g. Anki's
    selection handling) flips the widget."""

    def __init__(
        self, target: QWidget, on_change: Callable[[bool], None]
    ) -> None:
        super().__init__(target)
        self._on_change = on_change
        target.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        t = ev.type()
        if t in (QEvent.Type.Show, QEvent.Type.Hide):
            try:
                self._on_change(t == QEvent.Type.Show)
            except Exception:
                pass
        return False


def _install_browser_sidebar_toggle(browser: Any) -> None:
    """Add always-visible, checkable toggle buttons to the Browse window:
    ◧ shows/hides the left sidebar, ◨ shows/hides the right card-editor
    column.

    Anki ships the sidebar as a left-pinned ``QDockWidget`` whose title
    bar is an empty ``QWidget`` — so its own close button is invisible;
    the editor column has no toggle at all (Anki only hides it when the
    selection isn't a single card). Both buttons stay in lockstep with
    the real visibility no matter what flips it (⌘⇧F, the View menu,
    selection changes).

    We do NOT touch the sidebar dock's areas / floating / features — the
    sidebar stays exactly where Anki pins it. Purely toggle affordances.
    """
    dock = getattr(browser, "sidebarDockWidget", None)
    grid = getattr(getattr(browser, "form", None), "gridLayout", None)
    if dock is None or grid is None:
        print("[klausmate] sidebar toggle: dock or gridLayout missing")
        return
    if getattr(browser, "_klausmate_sidebar_toggle_btn", None) is not None:
        return  # idempotent — the Browser instance may re-run setup

    btn = _make_klaus_toggle("◧", "Toggle sidebar", dock.isVisible())
    # A checkable button's clicked signal carries the new checked bool,
    # which is exactly the visibility we want — no need to re-read state.
    btn.clicked.connect(dock.setVisible)
    # Keep the button in lockstep with the dock — covers ⌘⇧F, the View
    # menu, and any other path that flips visibility. setChecked doesn't
    # re-emit clicked, so there's no feedback loop.
    try:
        dock.visibilityChanged.connect(btn.setChecked)
    except Exception:
        pass

    # The card-editor column: the direct child of the Browse splitter that
    # contains fieldsArea. Walking up (instead of naming a form attribute)
    # stays correct even after the PDF panel wraps the pane in its own
    # splitter.
    editor_col: QWidget | None = None
    try:
        splitter = browser.form.splitter
        w: QWidget | None = browser.form.fieldsArea
        while w is not None:
            p = w.parentWidget()
            if p is splitter:
                editor_col = w
                break
            w = p
    except Exception:
        editor_col = None

    editor_btn: QToolButton | None = None
    if editor_col is not None:
        col = editor_col
        editor_btn = _make_klaus_toggle(
            "◨", "Toggle card editor", col.isVisible()
        )
        editor_btn.clicked.connect(col.setVisible)
        # Anki shows/hides this pane itself on selection changes — the
        # watcher keeps the button truthful through those flips.
        _VisibilityWatcher(col, editor_btn.setChecked)

    # gridLayout cell (0, 0) is NOT free at runtime: Anki's Browser
    # constructor drops its Cards/Notes Switch there (setup_table ->
    # gridLayout.addWidget(switch, 0, 0)), while the search bar sits at
    # (0, 1). QGridLayout lets two widgets share a cell and just overlaps
    # them, so we pull the switch out and repack [◧ | switch] into a
    # single holder at the far left. The ◨ editor toggle mirrors it on
    # the right end of the row (cell (0, 2) is free), next to the pane
    # it controls.
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(btn)
    existing = grid.itemAtPosition(0, 0)
    if existing is not None:
        prev = existing.widget()
        if prev is not None:
            grid.removeWidget(prev)
            row.addWidget(prev)
    row.addStretch(1)
    grid.addWidget(holder, 0, 0)
    if editor_btn is not None:
        grid.addWidget(editor_btn, 0, 2)

    browser._klausmate_sidebar_toggle_btn = btn  # type: ignore[attr-defined]
    browser._klausmate_editor_toggle_btn = editor_btn  # type: ignore[attr-defined]
    print("[klausmate] sidebar + editor toggle buttons installed")


def on_browser_will_show(browser: Any) -> None:
    """``gui_hooks.browser_will_show`` callback — install Klaus's two
    Browse-specific features:

    1. Remap Anki's Mark hotkey (``Ctrl/Cmd+K``) to ``Ctrl/Cmd+Alt+K``
       so Klaus can own ``⌘K`` consistently across all surfaces.
    2. Bind ``⌘K`` inside the Browse search bar to the Klaus Ask
       popover, which converts natural-language queries to Anki search
       syntax.
    3. Add a visible, one-click sidebar toggle button.

    Earlier batches also wrapped the editor pane in a ``QDockWidget`` and
    added a View menu. Those layout-mutating features were removed — the
    user preferred Anki's stock Browse layout. The sidebar toggle button
    re-added here does NOT touch the dock's areas/floating/features; it is
    purely a visible affordance for Anki's existing show/hide.

    Installs are deferred one event-loop tick (``QTimer.singleShot(0)``)
    so ``setupUi`` has finished wiring the form's actions and widgets
    before we touch them.
    """

    def _deferred() -> None:
        try:
            _remap_browser_mark_hotkey(browser)
        except Exception as exc:
            print(f"[klausmate] mark remap failed: {exc}")
        try:
            _install_browser_search_klaus(browser)
        except Exception as exc:
            print(f"[klausmate] search ⌘K install failed: {exc}")
        # Repair leftover broken layout state from earlier add-on builds:
        # re-anchor the sidebar to the left and undo any zero-width
        # splitter pane. No-op on a clean profile. Runs BEFORE the toggle
        # install so the button's initial checked state reads the final
        # (healed / profile-restored) sidebar visibility.
        try:
            _reset_browse_layout_to_defaults(browser)
        except Exception as exc:
            print(f"[klausmate] browse layout reset failed: {exc}")
        try:
            _install_browser_sidebar_toggle(browser)
        except Exception as exc:
            print(f"[klausmate] sidebar toggle install failed: {exc}")

    try:
        QTimer.singleShot(0, _deferred)
    except Exception as exc:
        print(f"[klausmate] browser_will_show defer failed: {exc}")
        # Last-ditch synchronous attempt if the singleShot itself errored.
        _deferred()


# ----------------------------- strip ghost HTML on save -------------------


_GHOST_SPAN_RE = re.compile(
    r'<span\b[^>]*\bdata-klausmate-ghost\b[^>]*>.*?</span>',
    re.IGNORECASE | re.DOTALL,
)


def strip_ghost_html(txt: str, editor: Editor) -> str:
    """Remove inline ghost spans before Anki persists field HTML."""
    if not txt or "data-klausmate-ghost" not in txt:
        return txt
    return _GHOST_SPAN_RE.sub("", txt)


# ----------------------------- web injection ------------------------------


def on_webview_will_set_content(web_content: WebContent, context: Any) -> None:
    if not isinstance(context, Editor):
        return
    pkg = mw.addonManager.addonFromModule(__name__)
    web_content.css.append(f"/_addons/{pkg}/web/copilot.css")
    web_content.js.append(f"/_addons/{pkg}/web/copilot.js")
    # Inject runtime config so JS can read debounce, min chars, etc.
    cfg = get_config()
    runtime = {
        "ask_hotkey": cfg.get("ask_hotkey", "Cmd+K"),
        "cycle_forward_hotkey": cfg.get("cycle_forward_hotkey", "Cmd+Shift+]"),
        "cycle_backward_hotkey": cfg.get("cycle_backward_hotkey", "Cmd+Shift+["),
        "debounce_ms": int(cfg.get("debounce_ms", 400)),
        "min_chars_before_trigger": int(cfg.get("min_chars_before_trigger", 8)),
        "paste_cooldown_ms": int(cfg.get("paste_cooldown_ms", 800)),
        "dismissal_cooldown_ms": int(cfg.get("dismissal_cooldown_ms", 1500)),
        "accept_cooldown_ms": int(cfg.get("accept_cooldown_ms", 400)),
        # Feature toggles. Default true so users upgrading from a version
        # before these existed don't silently lose functionality.
        "autocomplete_enabled": bool(cfg.get("autocomplete_enabled", True)),
        "ask_enabled": bool(cfg.get("ask_enabled", True)),
        "image_crop_enabled": bool(cfg.get("image_crop_enabled", True)),
    }
    # "</" → "<\/" so a pathological config string (e.g. a hotkey
    # containing "</script>") can't terminate the script block and dump
    # the rest of the config as page text.
    blob = json.dumps(runtime).replace("</", "<\\/")
    web_content.head += f"<script>window.klausmateConfig = {blob};</script>"


# ----------------------------- pycmd routing ------------------------------


def on_js_message(
    handled: tuple[bool, Any], message: str, context: Any
) -> tuple[bool, Any]:
    if not message.startswith("klausmate:"):
        return handled
    if not isinstance(context, Editor):
        return (True, None)

    try:
        _, action, payload = message.split(":", 2)
    except ValueError:
        return (True, None)

    if action == "complete":
        try:
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            request_id = int(data["id"])
            field_text = str(data["text"])
        except Exception:
            return (True, None)
        avoid_raw = data.get("avoid") if isinstance(data, dict) else None
        avoid = (
            [str(a) for a in avoid_raw if isinstance(a, str)]
            if isinstance(avoid_raw, list)
            else None
        )
        is_variant = bool(data.get("variant")) if isinstance(data, dict) else False
        card_ctx = extract_card_ctx(context)
        request_completion(
            context, request_id, field_text, card_ctx,
            avoid=avoid, variant=is_variant,
        )
        return (True, None)

    if action == "ask":
        try:
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            request_id = int(data["id"])
            user_prompt = str(data["prompt"])
            field_text = str(data.get("text", ""))
        except Exception:
            return (True, None)
        card_ctx = extract_card_ctx(context)
        request_ask(context, request_id, user_prompt, field_text, card_ctx)
        return (True, None)

    if action == "focus":
        try:
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            field_name = str(data.get("field", "")).strip()
        except Exception:
            return (True, None)
        _set_target_field(context, field_name)
        return (True, None)

    if action == "crop":
        try:
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            fname = str(data.get("fname", "")).strip()
        except Exception:
            return (True, None)
        if fname and bool(get_config().get("image_crop_enabled", True)):
            editor = context
            # Defer so the modal exec() doesn't run inside the webchannel
            # message handler (mirrors the singleShot pattern at editor init).
            QTimer.singleShot(0, lambda: _launch_crop_dialog(editor, fname))
        return (True, None)

    if action == "log":
        print("[klausmate js]", payload)
        return (True, None)

    if action == "dbg":
        try:
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            _dbg_autofill(
                str(data.get("location", "js")),
                str(data.get("message", "")),
                data.get("data") if isinstance(data.get("data"), dict) else {},
                str(data.get("hypothesisId", "?")),
            )
        except Exception:
            pass
        return (True, None)

    return (True, None)


# ----------------------------- image crop ---------------------------------


_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(
    r"""(\bsrc\s*=\s*)("([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE
)


def _replace_img_src(
    html_text: str, old_fname: str, new_fname: str
) -> tuple[str, bool]:
    """Point every ``<img src>`` matching ``old_fname`` at ``new_fname``.

    Anki stores DECODED filenames in note fields (``reverse_url_quoting``
    unescapes on save), so we compare both the raw src and its
    percent-decoded form against ``old_fname`` — and additionally the
    HTML-entity-unescaped forms, because field HTML entity-escapes
    attribute values (a file named ``foo&bar.png`` is stored as
    ``src="foo&amp;bar.png"``). Returns ``(html, changed)``.
    """
    changed = False

    def fix_src(m: re.Match[str]) -> str:
        nonlocal changed
        raw = m.group(3) or m.group(4) or m.group(5) or ""
        try:
            decoded = urllib.parse.unquote(raw)
        except Exception:
            decoded = raw
        candidates = {raw, decoded}
        try:
            candidates.add(html_mod.unescape(raw))
            candidates.add(html_mod.unescape(decoded))
        except Exception:
            pass
        if old_fname not in candidates:
            return m.group(0)
        changed = True
        # Emit the canonical stored form: double-quoted, decoded,
        # entity-escaped so special chars round-trip through Anki's
        # field serialization (write_data-sanitized names contain no
        # quotes, but may contain e.g. '&').
        return f'{m.group(1)}"{html_mod.escape(new_fname, quote=True)}"'

    def fix_tag(m: re.Match[str]) -> str:
        return _SRC_ATTR_RE.sub(fix_src, m.group(0))

    return _IMG_TAG_RE.sub(fix_tag, html_text), changed


def _launch_crop_dialog(editor: Editor, fname: str) -> None:
    """Open the crop dialog for ``fname`` and apply the crop to the note.

    Shared by the context-menu and double-click triggers. The crop is
    always saved as a NEW media file; the original is never touched.
    """
    try:
        if editor.note is None:
            tooltip("Klaus: no note loaded", parent=editor.widget)
            return
        if getattr(editor, "_klausmate_crop_open", False):
            return
        editor._klausmate_crop_open = True  # type: ignore[attr-defined]
        try:
            # fname crosses the JS trust boundary — allow bare filenames
            # only (the media folder is flat, so that is always correct).
            if (
                not fname
                or "/" in fname
                or "\\" in fname
                or ".." in fname
            ):
                tooltip("Klaus: invalid image filename", parent=editor.widget)
                return
            path = os.path.join(editor.mw.col.media.dir(), fname)
            if not os.path.isfile(path):
                tooltip(
                    f"Klaus: image not found: {fname}", parent=editor.widget
                )
                return
            image = QImage(path)
            if image.isNull():
                tooltip(
                    "Klaus: could not load image (unsupported format)",
                    parent=editor.widget,
                )
                return
            from .crop_dialog import ImageCropDialog, encode_cropped

            dlg = ImageCropDialog(image, fname, parent=editor.parentWindow)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            cropped = dlg.cropped_image()
            if cropped is None or cropped.isNull():
                return
            stem, _, ext = fname.rpartition(".")
            if not stem:
                stem, ext = fname, ""
            data, out_ext = encode_cropped(cropped, ext)
            new_fname = editor.mw.col.media.write_data(
                f"{stem}_crop.{out_ext}", data
            )

            def apply_to_note() -> None:
                try:
                    note = editor.note
                    if note is None:
                        return  # editor closed while the dialog was up
                    any_change = False
                    for i, field_html in enumerate(note.fields):
                        new_html, field_changed = _replace_img_src(
                            field_html, fname, new_fname
                        )
                        if field_changed:
                            note.fields[i] = new_html
                            any_change = True
                    if not any_change:
                        tooltip(
                            f"Klaus: saved {new_fname}, but the note's HTML "
                            "doesn't reference the original image",
                            parent=editor.widget,
                        )
                        return
                    if not editor.addMode:
                        # Persist; initiator=editor so no auto-reload.
                        editor._save_current_note()
                    editor.loadNoteKeepingFocus()
                    tooltip(
                        f"Klaus: cropped image saved as {new_fname}",
                        parent=editor.widget,
                    )
                except Exception as e:
                    print(
                        "[klausmate] crop apply failed: "
                        f"{type(e).__name__}: {e}"
                    )
                    traceback.print_exc()

            # Flush pending in-webview edits into note.fields FIRST
            # (call_after_note_saved evals JS saveNow(); key:/blur: bridge
            # cmds land in note.fields via onBridgeCmd before the callback
            # fires), THEN mutate the fields.
            editor.call_after_note_saved(apply_to_note, keepFocus=True)
        finally:
            editor._klausmate_crop_open = False  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[klausmate] crop failed: {type(e).__name__}: {e}")
        traceback.print_exc()


def on_editor_context_menu(webview: EditorWebView, menu: QMenu) -> None:
    """Add "Crop image" when the editor context menu opened on an <img>."""
    try:
        if not bool(get_config().get("image_crop_enabled", True)):
            return
        editor = getattr(webview, "editor", None)
        if editor is None or editor.note is None:
            return
        if not hasattr(webview, "lastContextMenuRequest"):
            return  # older Anki without QWebEngineContextMenuRequest
        req = webview.lastContextMenuRequest()
        if req is None or req.mediaType() != req.MediaType.MediaTypeImage:
            return
        fname = req.mediaUrl().fileName()  # QUrl.fileName() -> decoded
        if not fname:
            return  # data: URIs / mathjax have no filename
        action = menu.addAction("Crop image")
        action.triggered.connect(
            lambda _=False, e=editor, f=fname: _launch_crop_dialog(e, f)
        )
    except Exception as e:
        print(f"[klausmate] crop context menu failed: {type(e).__name__}: {e}")


# ----------------------------- menu / setup -------------------------------


# Session-scoped flag set when the welcome dialog actually fires. Used by
# setup_readiness_check (registered as a sibling profile-open hook) to
# avoid stacking a second dialog on top of the welcome screen during a
# fresh install.
_first_run_dialog_shown_this_session: bool = False


def first_run_check() -> None:
    """Welcome dialog shown once per profile.

    Always shows the how-to bullets (autocomplete, ⌘K, PDF sidebar) so the
    user knows the feature surface — not just when Ollama is missing. If
    Ollama isn't running we add an install nudge to the same dialog.
    """
    global _first_run_dialog_shown_this_session
    # Reset each profile-open so profile switches re-evaluate cleanly.
    _first_run_dialog_shown_this_session = False
    cfg = get_config()
    if cfg.get("_first_run_done"):
        return
    _first_run_dialog_shown_this_session = True
    try:
        # Short timeout — this runs synchronously on the main thread.
        ollama_ok = client(5.0).health()
    except Exception:
        ollama_ok = False

    hotkey = cfg.get("ask_hotkey", "Cmd+K")
    body_lines = [
        "Klaus adds local AI to your Anki editor.",
        "",
        "• As you type, ghost-text suggestions appear — press Tab to accept, "
        "Esc to dismiss.",
        f"• Press {hotkey} on any field to open the Ask popover — type a "
        "free-form instruction and Klaus rewrites the field.",
        "• Drop a lecture PDF into the Klaus sidebar to ground suggestions "
        "in what you're reading.",
        "• Semantic search and PDF study priorities use the Voyage API by "
        "default (free key at voyageai.com — paste it under Manage models). "
        "Prefer fully local? Pick Ollama under Manage models → Card "
        "embeddings.",
        "",
    ]
    if ollama_ok:
        body_lines.append("Ollama is running — you're ready to go.")
    else:
        body_lines.append(
            "One click sets everything up: Klaus downloads its local AI "
            f"engine ({runtime_download_size_hint()}) and a starter model. "
            "Autocomplete and Ask run on this computer; semantic search "
            "uses the Voyage cloud API unless you switch it to local Ollama."
        )

    msg = QMessageBox(mw)
    msg.setWindowTitle("Welcome to Klaus")
    msg.setText("\n".join(body_lines))
    msg.setIcon(QMessageBox.Icon.Information)
    setup_btn = None
    if ollama_ok:
        msg.addButton("Got it", QMessageBox.ButtonRole.AcceptRole)
        manage_btn = msg.addButton(
            "Choose models…", QMessageBox.ButtonRole.ActionRole
        )
    else:
        setup_btn = msg.addButton(
            "Set up Klaus", QMessageBox.ButtonRole.ActionRole
        )
        manage_btn = msg.addButton(
            "Manage models…", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("Later", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(setup_btn)
    msg.exec()
    clicked = msg.clickedButton()
    if setup_btn is not None and clicked is setup_btn:
        try:
            manage_models_dialog(setup=True)
        except Exception as exc:
            print(f"[klausmate] setup dialog failed: {exc}")
    elif clicked is manage_btn:
        try:
            manage_models_dialog()
        except Exception:
            pass
    # Re-read before writing: the modal setup dialog above may have written
    # config (endpoint rewrite, model assignments) — writing the snapshot
    # captured before the dialog would silently revert all of it.
    cfg = get_config()
    cfg["_first_run_done"] = True
    write_config(cfg)


def setup_readiness_check() -> None:
    """Run on every profile open. Silently start a local Ollama when one
    is available (managed runtime or system install), then verify Klaus
    can actually generate — surfacing an actionable dialog only when it
    genuinely can't.

    Skipped on the very first profile open because ``first_run_check``
    already showed the welcome dialog (which itself includes setup
    guidance). The ``_first_run_dialog_shown_this_session`` module flag
    tracks that — both hooks share the ``profile_did_open`` signal in
    registration order: first_run_check runs first, this runs second.
    """
    if _first_run_dialog_shown_this_session:
        return

    cfg = get_config()
    if not cfg.get("runtime_auto_setup", True):
        _readiness_check_body()
        return

    # ensure_server never downloads — it only reuses a reachable server or
    # starts an already-present binary, so it's safe to run unprompted.
    def do() -> Any:
        try:
            return ensure_server(get_config(), save_config=_save_config_on_main)
        except Exception as e:
            print(f"[klausmate] ensure_server failed: {type(e).__name__}: {e}")
            return None

    def on_ensure_done(res: Any) -> None:
        if getattr(res, "port_moved", False):
            tooltip(f"Klaus: local AI running on {res.endpoint}")
        _maybe_offer_runtime_update(res)
        _readiness_check_body()

    op = QueryOp(parent=mw, op=lambda col: do(), success=on_ensure_done)
    op.failure(lambda _e: _readiness_check_body())
    op.without_collection().run_in_background()


def _maybe_offer_runtime_update(res: Any) -> None:
    """Non-blocking, once-per-version offer to move a managed server onto
    the add-on's newly pinned Ollama version. The old version keeps
    working regardless — never block startup on an upgrade."""
    if getattr(res, "detail", "") != "update_available":
        return
    cfg = get_config()
    offered_key = f"_runtime_update_offered_{ollama_runtime.OLLAMA_VERSION}"
    if cfg.get(offered_key):
        return
    cfg[offered_key] = True
    write_config(cfg)
    if not askUser(
        "Klaus can update its local AI engine to Ollama "
        f"v{ollama_runtime.OLLAMA_VERSION} "
        f"({runtime_download_size_hint()} download).\n\n"
        "Update in the background? The engine restarts briefly once the "
        "download finishes; you can keep studying meanwhile."
    ):
        return

    def do() -> Any:
        return ollama_runtime.update_runtime(
            get_config(), save_config=_save_config_on_main
        )

    def on_done(res2: Any) -> None:
        if getattr(res2, "status", "") in ("reachable", "started"):
            tooltip("Klaus: local AI engine updated")
        else:
            print(
                "[klausmate] runtime update failed: "
                f"{getattr(res2, 'detail', '')}"
            )

    op = QueryOp(parent=mw, op=lambda col: do(), success=on_done)
    op.failure(lambda e: print(f"[klausmate] runtime update failed: {e}"))
    op.without_collection().run_in_background()


def _readiness_check_body() -> None:
    """The actual readiness dialogs; runs after the silent autostart."""
    # Re-read config — ensure_server may have rewritten the endpoint.
    cfg = get_config()
    auto = bool(cfg.get("runtime_auto_setup", True))

    # ---- 1. Ollama reachable? -------------------------------------------
    try:
        # Short timeout — this runs synchronously on the main thread.
        ollama_ok = client(5.0).health()
    except Exception:
        ollama_ok = False

    if not ollama_ok:
        if not auto:
            # runtime_auto_setup: false means fully manual behavior — no
            # unprompted setup offers, just the old-style warning.
            msg = QMessageBox(mw)
            msg.setWindowTitle("Klaus: Ollama isn't running")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                "Klaus needs Ollama to generate suggestions. Install it "
                "from https://ollama.com, start it, and restart Anki.\n\n"
                "(Automatic management is disabled in Klaus settings.)"
            )
            open_btn = msg.addButton(
                "Open download page", QMessageBox.ButtonRole.ActionRole
            )
            msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
            msg.exec()
            if msg.clickedButton() is open_btn:
                openLink(OLLAMA_DOWNLOAD_URL)
            return
        if cfg.get("_runtime_setup_declined"):
            print("[klausmate] Ollama unreachable; auto-setup previously declined")
            return
        msg = QMessageBox(mw)
        msg.setWindowTitle("Klaus: local AI isn't set up yet")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "Klaus needs a local AI engine (Ollama) to generate "
            "suggestions — and it can set one up for you automatically "
            f"(one-time {runtime_download_size_hint()} download).\n\n"
            "Everything runs on this computer. Nothing is sent anywhere."
        )
        msg.setInformativeText(
            "Until then, ⌘K, ghost-text autocomplete, and the Browse "
            "natural-language search will all be silent."
        )
        setup_btn = msg.addButton(
            "Set up automatically", QMessageBox.ButtonRole.ActionRole
        )
        manual_btn = msg.addButton(
            "Install manually…", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(setup_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is setup_btn:
            try:
                manage_models_dialog(setup=True)
            except Exception as exc:
                print(f"[klausmate] setup dialog failed: {exc}")
        elif clicked is manual_btn:
            openLink(OLLAMA_DOWNLOAD_URL)
        else:
            # Respect the decision — don't re-prompt on every profile
            # open. Re-read config first: a modal above us may have
            # written it while this snapshot was held.
            cfg = get_config()
            cfg["_runtime_setup_declined"] = True
            write_config(cfg)
        return

    # ---- 2. Models configured + installed? ------------------------------
    legacy = (cfg.get("model") or "").strip()
    auto = (cfg.get("autocomplete_model") or legacy).strip()
    ask_m = (cfg.get("ask_model") or legacy).strip()

    try:
        installed = set(client().list_models())
    except Exception:
        installed = set()

    missing: list[tuple[str, str]] = []
    if not auto:
        missing.append(("Autocomplete", "<not selected>"))
    elif auto not in installed:
        missing.append(("Autocomplete", auto))
    if not ask_m:
        missing.append(("Ask (⌘K)", "<not selected>"))
    elif ask_m not in installed:
        missing.append(("Ask (⌘K)", ask_m))

    if not missing:
        return  # All set — silent

    bullets = "\n".join(f"  • {role}: {name}" for role, name in missing)
    msg = QMessageBox(mw)
    msg.setWindowTitle("Klaus: model setup needed")
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setText(
        "Klaus is connected to Ollama, but the model(s) it's configured "
        "to use aren't installed locally yet:\n\n"
        + bullets
        + "\n\nOpen Manage models… to pull a model (e.g. "
        "`qwen3:0.6b` for autocomplete, `qwen3:4b` for Ask), or pick a "
        "model you already have in Klaus settings."
    )
    msg.setInformativeText(
        "Until a model is available, ⌘K and ghost-text autocomplete "
        "won't produce output."
    )
    manage_btn = msg.addButton(
        "Manage models…", QMessageBox.ButtonRole.ActionRole
    )
    settings_btn = msg.addButton(
        "Open Klaus settings…", QMessageBox.ButtonRole.ActionRole
    )
    msg.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
    msg.exec()
    clicked = msg.clickedButton()
    if clicked is manage_btn:
        try:
            manage_models_dialog()
        except Exception as exc:
            print(f"[klausmate] manage_models_dialog failed: {exc}")
    elif clicked is settings_btn:
        try:
            open_settings_dialog()
        except Exception as exc:
            print(f"[klausmate] open_settings_dialog failed: {exc}")


def open_settings_dialog() -> None:
    from .settings_ui import open_settings_dialog as _open

    _open(get_config, write_config, manage_models_dialog, tooltip)


def install_preferences() -> None:
    """Embed Klaus settings in Anki Edit → Preferences (Editing tab)."""
    from anki.hooks import wrap
    from aqt.preferences import Preferences

    from .settings_ui import KlausSettingsPanel

    def _klaus_setup_options(prefs: Preferences) -> None:
        try:
            box = QGroupBox("Klaus")
            box_lay = QVBoxLayout(box)
            panel = KlausSettingsPanel(
                box, on_manage_models=manage_models_dialog
            )
            panel.load_from_config(get_config())
            box_lay.addWidget(panel)
            prefs._klausmate_settings = panel  # type: ignore[attr-defined]
            form = prefs.form
            target = getattr(form, "pastePNG", None)
            if target is not None:
                parent = target.parentWidget()
                lay = parent.layout() if parent else None
                if lay is not None:
                    lay.addWidget(box)
                    return
            lay_main = prefs.form.centralwidget.layout() if hasattr(
                prefs.form, "centralwidget"
            ) else None
            if lay_main is not None:
                lay_main.addWidget(box)
        except Exception as e:
            print(f"[klausmate] preferences setup failed: {e}")

    def _klaus_update_options(prefs: Preferences) -> None:
        panel = getattr(prefs, "_klausmate_settings", None)
        if panel is None:
            return
        try:
            cfg = get_config()
            write_config(panel.save_to_config(cfg))
        except Exception as e:
            print(f"[klausmate] preferences save failed: {e}")

    wrap(Preferences.setupOptions, _klaus_setup_options, "after")
    wrap(Preferences.updateOptions, _klaus_update_options, "after")


# ----------------------------- model manager -----------------------------

# Suggested presets the user can pull with one click. Everything here runs
# on an 8 GB RAM machine (4-bit quantized weights ≤ ~5.5 GB on disk).
# Index 0 must stay the tiny starter model — the first-run flow pulls it.
_MODEL_PRESETS = [
    # Qwen3 — best quality-per-size family; great autocomplete at the
    # small end. The *-2507 refresh answers directly (no <think> phase),
    # which keeps Ask latency low.
    ("qwen3:0.6b", "fastest · ~0.8 GB"),
    ("qwen3:1.7b", "fast · ~1.4 GB"),
    ("qwen3:4b", "balanced · ~2.5 GB"),
    ("qwen3:4b-instruct-2507", "newest Qwen, no thinking delay · ~2.7 GB"),
    ("qwen3:8b", "best quality · ~5.2 GB"),
    # Google Gemma 3 / 3n — strong small models; 3n is engineered for a
    # low RAM footprint at runtime (bigger download than it "feels").
    ("gemma3:1b", "tiny · ~0.8 GB"),
    ("gemma3:4b", "great quality/size · ~3.3 GB"),
    ("gemma3n:e2b", "low-RAM runtime · ~5.6 GB download"),
    # Microsoft Phi-4 mini — punchy reasoning for its size.
    ("phi4-mini", "strong reasoning for size · ~2.5 GB"),
    # DeepSeek-R1 distill — thinks step-by-step before answering; better
    # for Ask than for autocomplete (the thinking phase adds latency).
    ("deepseek-r1:8b", "reasoning, thinks first · ~5.2 GB"),
    # Meta Llama — solid generalists.
    ("llama3.2:3b", "general · ~2 GB"),
    ("llama3.1:8b", "general · ~4.7 GB"),
    # Community medical fine-tune.
    ("cniongolo/biomistral", "medical-tuned · ~4.4 GB"),
]


def _format_pull_event(ev: dict) -> tuple[str, int]:
    """Return (human status, percent 0-100) for an Ollama pull progress event."""
    status = str(ev.get("status") or "")
    total = ev.get("total")
    completed = ev.get("completed")
    pct = 0
    if isinstance(total, (int, float)) and total > 0 and isinstance(completed, (int, float)):
        pct = int(min(100, max(0, completed * 100 / total)))
    if status == "success":
        pct = 100
    digest = str(ev.get("digest") or "")
    digest_short = digest[:12] + "…" if digest else ""
    label = status
    if digest_short:
        label = f"{status} ({digest_short})"
    if pct and total:
        mb = total / (1024 * 1024)
        label = f"{label} — {pct}% of {mb:.0f} MB"
    return label, pct


class _KlausManageDialog(QDialog):
    """QDialog whose EVERY close path goes through the confirm callback.

    Esc triggers QDialog.reject() and the title-bar ✕ triggers closeEvent —
    neither hits a Close button's clicked signal. Without routing them
    through confirm_close, a runtime setup download would keep streaming
    invisibly after the dialog vanishes (and a retry would corrupt the
    shared .part file).
    """

    confirm_close_cb: Callable[[], None] | None = None

    def reject(self) -> None:  # Esc key
        if self.confirm_close_cb is not None:
            self.confirm_close_cb()
        else:
            super().reject()

    def closeEvent(self, event: Any) -> None:  # title-bar ✕
        if self.confirm_close_cb is not None:
            event.ignore()
            self.confirm_close_cb()
        else:
            super().closeEvent(event)


def manage_models_dialog(setup: bool = False) -> None:
    """Set up the local AI runtime, pull models, and assign roles.

    ``setup=True`` is the one-click first-run path: it auto-opens the
    provisioning confirm on the setup page, and after the server is up it
    chains straight into pulling the starter model when none exist.
    """
    dlg = _KlausManageDialog(mw)
    dlg.setWindowTitle("Klaus — Manage models")
    dlg.setMinimumWidth(560)
    outer = QVBoxLayout(dlg)
    outer.setSpacing(10)

    stack = QStackedWidget()
    outer.addWidget(stack)

    # ----- Page 0: Install Ollama -----------------------------------------
    install_page = QWidget()
    install_layout = QVBoxLayout(install_page)
    install_layout.setSpacing(8)

    install_heading = QLabel("Set up local AI")
    install_heading.setStyleSheet("font-weight: 600; font-size: 14px;")
    install_layout.addWidget(install_heading)

    install_body = QLabel(
        "Klaus runs AI locally through Ollama — nothing ever leaves your "
        "computer. Klaus can download and manage its own copy "
        "automatically, or you can install Ollama yourself."
    )
    install_body.setWordWrap(True)
    install_layout.addWidget(install_body)

    install_status = QLabel()
    install_status.setWordWrap(True)
    install_status.setStyleSheet("color: rgba(140,140,140,0.95); font-size: 11px;")
    install_layout.addWidget(install_status)

    auto_setup_btn = QPushButton(
        f"Set up automatically ({runtime_download_size_hint()} download)"
    )
    auto_setup_btn.setDefault(True)
    install_layout.addWidget(auto_setup_btn)

    manual_lbl = QLabel("Manual options")
    manual_lbl.setStyleSheet("font-weight: 600; margin-top: 8px;")
    install_layout.addWidget(manual_lbl)

    download_btn = QPushButton("Open download page")
    install_layout.addWidget(download_btn)

    install_methods_box = QWidget()
    install_methods_layout = QVBoxLayout(install_methods_box)
    install_methods_layout.setContentsMargins(0, 0, 0, 0)
    install_methods_layout.setSpacing(6)
    install_layout.addWidget(install_methods_box)

    install_steps = QLabel(
        "After installing manually:\n"
        "1. Finish the installer and grant permissions if prompted.\n"
        "2. Start Ollama (open the app or ensure the service is running).\n"
        "3. Click Check connection, then pull a model on the next screen."
    )
    install_steps.setWordWrap(True)
    install_steps.setStyleSheet("color: rgba(120,120,120,0.95); font-size: 11px;")
    install_layout.addWidget(install_steps)

    install_btn_row = QHBoxLayout()
    check_conn_btn = QPushButton("Check connection")
    settings_btn = QPushButton("Settings…")
    install_btn_row.addWidget(check_conn_btn)
    install_btn_row.addStretch(1)
    install_btn_row.addWidget(settings_btn)
    install_layout.addLayout(install_btn_row)
    install_layout.addStretch(1)

    stack.addWidget(install_page)

    # ----- Page 1: jobs on top, model library below ------------------------
    # Organised by JOB (what Klaus does), not by backend: each row owns the
    # one control that decides who performs it. The Ollama list below is
    # pure inventory — it no longer assigns anything.
    models_page = QWidget()
    models_layout = QVBoxLayout(models_page)
    models_layout.setSpacing(8)

    _MUTED = "color: rgba(140,140,140,0.95); font-size: 11px;"
    _WARN = "color: #d9822b; font-size: 11px;"

    jobs_box = QGroupBox("What Klaus uses")
    jobs_layout = QVBoxLayout(jobs_box)
    jobs_layout.setSpacing(6)
    jobs_form = QFormLayout()
    jobs_form.setContentsMargins(0, 0, 0, 0)
    jobs_form.setSpacing(6)

    def _job_row(combo: QComboBox) -> tuple[QHBoxLayout, QLabel, QPushButton]:
        """combo + inline warning + a fix-it button, as one form field."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(combo, 1)
        warn = QLabel()
        warn.setStyleSheet(_WARN)
        warn.setVisible(False)
        row.addWidget(warn)
        fix = QPushButton("Pull it")
        fix.setVisible(False)
        row.addWidget(fix)
        return row, warn, fix

    # Autocomplete — always a local model; cloud per-keystroke is untenable.
    auto_combo = QComboBox()
    auto_row, auto_warn, auto_pull_btn = _job_row(auto_combo)
    jobs_form.addRow("Autocomplete:", auto_row)

    # Ask — engine and model merged into ONE choice. Previously the engine
    # lived here and the model was set by a button over the list, which is
    # what made "brain" vs "Ask model" vs "⌘K" read as three settings.
    ask_combo = QComboBox()
    ask_row, ask_warn, ask_pull_btn = _job_row(ask_combo)
    jobs_form.addRow("Ask (⌘K):", ask_row)

    claude_key_lbl = QLabel("    Claude key:")
    claude_key_edit = QLineEdit()
    claude_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    claude_key_edit.setPlaceholderText(
        "sk-ant-…  (platform.claude.com; stored in add-on config)"
    )
    jobs_form.addRow(claude_key_lbl, claude_key_edit)

    claude_model_lbl = QLabel("    Claude model:")
    claude_model_edit = QLineEdit()
    claude_model_edit.setPlaceholderText(_DEFAULT_CLAUDE_MODEL)
    jobs_form.addRow(claude_model_lbl, claude_model_edit)

    # Semantic search — the only job that can use a cloud embedder.
    embed_provider_combo = QComboBox()
    embed_provider_combo.addItem("Voyage API (default)", "voyage")
    embed_provider_combo.addItem("OpenAI API", "openai")
    embed_provider_combo.addItem("Local Ollama (private, free)", "ollama")
    embed_row, embed_warn, embed_fix_btn = _job_row(embed_provider_combo)
    embed_fix_btn.setText("Pull it")
    jobs_form.addRow("Semantic search:", embed_row)

    embed_model_lbl = QLabel("    Search model:")
    embed_model_combo = QComboBox()
    embed_model_combo.setEditable(True)
    embed_model_combo.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    jobs_form.addRow(embed_model_lbl, embed_model_combo)

    embed_key_lbl = QLabel("    API key:")
    embed_key_edit = QLineEdit()
    embed_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    jobs_form.addRow(embed_key_lbl, embed_key_edit)
    jobs_layout.addLayout(jobs_form)

    index_row = QHBoxLayout()
    embed_status = QLabel()
    embed_status.setWordWrap(True)
    embed_status.setStyleSheet(_MUTED)
    index_row.addWidget(embed_status, 1)
    index_btn = QPushButton("Index cards now")
    index_row.addWidget(index_btn)
    jobs_layout.addLayout(index_row)
    models_layout.addWidget(jobs_box)

    # ----- Local model library (inventory only) ----------------------------
    lib_box = QGroupBox("Local model library (Ollama)")
    lib_layout = QVBoxLayout(lib_box)
    lib_layout.setSpacing(6)

    status_lbl = QLabel()
    status_lbl.setStyleSheet(_MUTED)
    lib_layout.addWidget(status_lbl)

    lst = QListWidget()
    lst.setMinimumHeight(96)
    lib_layout.addWidget(lst)

    pull_row = QHBoxLayout()
    pull_input = QComboBox()
    pull_input.setEditable(True)
    pull_input.setMinimumWidth(220)
    pull_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for name, desc in _MODEL_PRESETS:
        pull_input.addItem(f"{name}   ({desc})", name)
    pull_input.setCurrentIndex(-1)
    pull_input.lineEdit().setPlaceholderText("pick or type a model to download")
    pull_btn = QPushButton("Pull")
    delete_btn = QPushButton("Delete")
    refresh_btn = QPushButton("Refresh")
    pull_row.addWidget(pull_input, 1)
    pull_row.addWidget(pull_btn)
    pull_row.addWidget(delete_btn)
    pull_row.addWidget(refresh_btn)
    lib_layout.addLayout(pull_row)
    models_layout.addWidget(lib_box)

    stack.addWidget(models_page)

    # ----- Shared footer --------------------------------------------------
    progress = QProgressBar()
    progress.setRange(0, 100)
    progress.setValue(0)
    progress.setTextVisible(True)
    progress.setVisible(False)
    outer.addWidget(progress)

    progress_lbl = QLabel("")
    progress_lbl.setStyleSheet("color: rgba(140,140,140,0.85); font-size: 11px;")
    progress_lbl.setVisible(False)
    outer.addWidget(progress_lbl)

    close_row = QHBoxLayout()
    close_row.addStretch(1)
    cancel_btn = QPushButton("Cancel download")
    cancel_btn.setVisible(False)
    close_row.addWidget(cancel_btn)
    close_btn = QPushButton("Close")
    close_row.addWidget(close_btn)
    outer.addLayout(close_row)

    install_action_btns: list[QPushButton] = []
    op_state: dict[str, Any] = {"active": False, "kind": "", "cancel": None}
    # Written by refresh(); read by the index pipeline (missing-model check)
    # and the section-sync guards (avoid save-on-programmatic-set loops).
    ui_state: dict[str, Any] = {"models": [], "syncing": False}

    def set_busy(busy: bool) -> None:
        op_state["active"] = busy
        for w in (
            pull_btn, pull_input, delete_btn, refresh_btn,
            auto_setup_btn, download_btn, check_conn_btn, settings_btn,
            auto_combo, auto_pull_btn, ask_combo, ask_pull_btn,
            claude_key_edit, claude_model_edit,
            embed_provider_combo, embed_model_combo, embed_key_edit,
            embed_fix_btn, index_btn,
        ):
            w.setEnabled(not busy)
        for btn in install_action_btns:
            btn.setEnabled(not busy)
        progress.setVisible(busy)
        progress_lbl.setVisible(busy)

    def endpoint_url() -> str:
        return get_config().get("endpoint", "http://localhost:11434")

    def rebuild_install_method_buttons() -> None:
        while install_methods_layout.count():
            item = install_methods_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        install_action_btns.clear()
        for method in install_methods():
            btn = QPushButton(method.label)
            btn.setToolTip(method.description)
            install_action_btns.append(btn)
            install_methods_layout.addWidget(btn)

            def _make_handler(m: InstallMethod = method) -> Callable[[], None]:
                return lambda: start_install(m)

            btn.clicked.connect(_make_handler())

    def show_install_page() -> None:
        stack.setCurrentIndex(0)
        install_status.setText(
            f"Could not reach Ollama at {endpoint_url()}.\n"
            "Use Set up automatically below — or install manually, start "
            "it, then click Check connection."
        )

    def get_selected_model() -> str:
        item = lst.currentItem()
        if not item:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or item.text()

    def refresh() -> None:
        cfg = get_config()
        ep = endpoint_url()
        if not ollama_reachable(ep):
            show_install_page()
            return

        stack.setCurrentIndex(1)
        try:
            models = client().list_models()
        except OllamaError:
            show_install_page()
            return

        ui_state["models"] = list(models)
        status_lbl.setText(f"Connected to {ep}")
        sync_jobs_widgets()
        sync_embed_widgets()
        rebuild_library_list()

    def rebuild_library_list() -> None:
        """Inventory with a 'used by' badge per model — the list answers
        'what do I have and what is it for', it no longer assigns."""
        from . import embeddings

        cfg = get_config()
        models = ui_state["models"]
        selected = get_selected_model()
        lst.clear()
        if not models:
            placeholder = QListWidgetItem("(no models installed — pull one below)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            lst.addItem(placeholder)
            return
        auto_active = autocomplete_model(cfg)
        ask_active = ask_model(cfg) if klaus_engine(cfg) != "claude" else None
        embed_active = (
            embeddings.embedding_model(cfg)
            if embeddings.provider_name(cfg) == "ollama"
            else None
        )
        for name in models:
            tags = [
                label
                for label, active in (
                    ("autocomplete", name == auto_active),
                    ("Ask", name == ask_active),
                    ("search", name == embed_active),
                )
                if active
            ]
            suffix = f"   ·  used by: {', '.join(tags)}" if tags else ""
            item = QListWidgetItem(name + suffix)
            item.setData(Qt.ItemDataRole.UserRole, name)
            lst.addItem(item)
            if name == selected:
                lst.setCurrentItem(item)

    def start_install(method: InstallMethod) -> None:
        ok = QMessageBox.question(
            dlg,
            "Install Ollama?",
            "Klaus will run this command on your computer:\n\n"
            f"  {method.command_display}\n\n"
            "You may be asked for your password in a system dialog. "
            "This can take several minutes.\n\n"
            "Continue?",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        op_state["kind"] = "install"
        set_busy(True)
        progress.setRange(0, 0)
        progress_lbl.setText(f"Installing via {method.id}…")

        def do() -> tuple[int, str]:
            return run_install_method(method)

        def on_done(result: tuple[int, str]) -> None:
            code, output = result
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            if code == 0:
                showInfo(
                    "Ollama install command finished.\n\n"
                    "Start the Ollama app if it is not already running, then "
                    "click Check connection."
                )
            else:
                showWarning(
                    f"Install command exited with code {code}.\n\n{output}"
                )
            refresh()

        def on_fail(exc: Exception) -> None:
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            showWarning(
                f"Could not run install command:\n\n{type(exc).__name__}: {exc}"
            )

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def maybe_auto_pull_starter() -> None:
        """setup mode: after the server is up, chain straight into pulling
        the smallest preset when no models exist — one click end to end."""
        if not setup:
            return
        try:
            if client().list_models():
                return
        except OllamaError:
            return
        pull_input.setCurrentIndex(0)  # smallest preset (qwen3:0.6b)
        start_pull()

    def start_auto_setup() -> None:
        if op_state["active"]:
            return
        starter_note = (
            "Afterwards, if no model is installed yet, Klaus will also "
            f"pull the starter model {_MODEL_PRESETS[0][0]} (~0.8 GB).\n\n"
            if setup
            else ""
        )
        ok = QMessageBox.question(
            dlg,
            "Set up local AI?",
            "Klaus will download the Ollama runtime from the official "
            f"GitHub release ({runtime_download_size_hint()}, verified "
            "against its published checksum) and run it in the background "
            "while Anki is open.\n\n"
            "It is stored in the add-on's user_files folder and can be "
            f"removed at any time.\n\n{starter_note}"
            "Continue?",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        cancel_event = threading.Event()
        op_state["kind"] = "setup"
        op_state["cancel"] = cancel_event
        set_busy(True)
        cancel_btn.setVisible(True)
        progress.setRange(0, 0)
        progress_lbl.setText("Preparing setup…")

        def on_event(ev: dict) -> None:
            label, pct = _format_pull_event(ev)

            def apply() -> None:
                progress_lbl.setText(label)
                if pct:
                    progress.setRange(0, 100)
                    progress.setValue(pct)
                else:
                    # Phases without byte totals (checksums, extract,
                    # winget) show as indeterminate.
                    progress.setRange(0, 0)

            mw.taskman.run_on_main(apply)

        def do() -> Any:
            return full_setup(
                get_config(),
                on_progress=on_event,
                cancel_flag=cancel_event,
                save_config=_save_config_on_main,
            )

        def finish() -> None:
            progress.setRange(0, 100)
            set_busy(False)
            cancel_btn.setVisible(False)
            op_state["kind"] = ""
            op_state["cancel"] = None

        def on_done(res: Any) -> None:
            finish()
            if getattr(res, "status", "") in ("reachable", "started"):
                cfg = get_config()
                if cfg.get("_runtime_setup_declined"):
                    cfg["_runtime_setup_declined"] = False
                    write_config(cfg)
                if getattr(res, "port_moved", False):
                    tooltip(f"Klaus: local AI running on {res.endpoint}")
                else:
                    tooltip("Klaus: local AI ready")
                refresh()
                maybe_auto_pull_starter()
            else:
                showWarning(
                    "Setup did not complete:\n\n"
                    + (getattr(res, "detail", "") or "Unknown error.")
                )
                refresh()

        def on_fail(exc: Exception) -> None:
            finish()
            if isinstance(exc, RuntimeProvisionError):
                if exc.kind == "cancelled":
                    tooltip("Klaus: setup cancelled")
                    return
                # unsupported_platform lands back on this page, where the
                # manual options are already visible.
                showWarning(str(exc))
            else:
                showWarning(f"Setup failed:\n\n{type(exc).__name__}: {exc}")

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def cancel_setup_download() -> None:
        ev = op_state.get("cancel")
        if ev is not None:
            ev.set()
            progress_lbl.setText("Cancelling…")

    # ----- Job assignment (the dropdowns) ----------------------------------

    def _fill_model_combo(combo: QComboBox, current: str, prefix: str = "") -> None:
        """Installed models as items; a missing configured model is kept as
        an item of its own so the dropdown never silently drops it."""
        models = ui_state["models"]
        combo.clear()
        for name in models:
            combo.addItem(f"{prefix}{name}" if prefix else name, name)
        if current and current not in models:
            combo.addItem(
                f"{prefix}{current}  (not installed)" if prefix else
                f"{current}  (not installed)",
                current,
            )
        if not combo.count():
            combo.addItem("(no models installed)", "")
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def sync_jobs_widgets() -> None:
        ui_state["syncing"] = True
        try:
            cfg = get_config()
            auto_active = autocomplete_model(cfg)
            ask_active = ask_model(cfg)
            is_claude = klaus_engine(cfg) == "claude"

            _fill_model_combo(auto_combo, auto_active)

            ask_combo.clear()
            for name in ui_state["models"]:
                ask_combo.addItem(f"Local — {name}", f"ollama:{name}")
            if ask_active and ask_active not in ui_state["models"]:
                ask_combo.addItem(
                    f"Local — {ask_active}  (not installed)", f"ollama:{ask_active}"
                )
            if not ask_combo.count():
                # Never let "Claude API…" be the only option — with an empty
                # library any edit to another row would silently switch the
                # engine to Claude.
                ask_combo.addItem("Local — (none installed)", "ollama:")
            ask_combo.addItem("Claude API…", "claude:")
            want = "claude:" if is_claude else f"ollama:{ask_active}"
            idx = ask_combo.findData(want)
            ask_combo.setCurrentIndex(idx if idx >= 0 else 0)

            claude_key_edit.setText(str(cfg.get("claude_api_key") or ""))
            claude_model_edit.setText(str(cfg.get("claude_model") or ""))
        finally:
            ui_state["syncing"] = False
        update_jobs_status()

    def ask_selection() -> tuple[str, str]:
        """The Ask row's merged choice as (engine, local model name)."""
        data = str(ask_combo.currentData() or "")
        if data.startswith("claude"):
            return "claude", ""
        return "ollama", data[len("ollama:"):] if data.startswith("ollama:") else ""

    def update_jobs_status() -> None:
        """Per-row warnings — this is what makes a config pointing at an
        uninstalled model visible instead of a silent contradiction."""
        models = ui_state["models"]
        engine, ask_name = ask_selection()
        is_claude = engine == "claude"
        for w in (claude_key_lbl, claude_key_edit, claude_model_lbl, claude_model_edit):
            w.setVisible(is_claude)

        auto_name = str(auto_combo.currentData() or "")
        auto_missing = bool(auto_name) and auto_name not in models
        auto_warn.setText("⚠ not installed")
        auto_warn.setVisible(auto_missing)
        auto_pull_btn.setVisible(auto_missing)

        ask_missing = bool(ask_name) and ask_name not in models
        if is_claude and not claude_key_edit.text().strip():
            ask_warn.setText("⚠ key needed")
            ask_warn.setVisible(True)
        else:
            ask_warn.setText("⚠ not installed")
            ask_warn.setVisible(ask_missing)
        ask_pull_btn.setVisible(ask_missing)

    def save_jobs() -> None:
        if ui_state["syncing"]:
            return
        cfg = get_config()
        auto_name = str(auto_combo.currentData() or "")
        if auto_name:
            cfg["autocomplete_model"] = auto_name
            cfg["model"] = auto_name
        engine, ask_name = ask_selection()
        cfg["klaus_engine"] = engine
        if engine == "ollama" and ask_name:
            cfg["ask_model"] = ask_name
        cfg["claude_api_key"] = claude_key_edit.text().strip()
        cfg["claude_model"] = claude_model_edit.text().strip()
        write_config(cfg)
        update_jobs_status()
        rebuild_library_list()

    def pull_missing(name: str) -> None:
        """Fix-it button on a job row: download the model it points at."""
        if not name or op_state["active"]:
            return
        edit = pull_input.lineEdit()
        if edit is not None:
            edit.setText(name)
        start_pull()

    def delete_selected() -> None:
        name = get_selected_model()
        if not name:
            return
        cfg = get_config()
        from . import embeddings

        used_by = [
            label
            for label, active in (
                ("autocomplete", autocomplete_model(cfg)),
                ("Ask", ask_model(cfg) if klaus_engine(cfg) != "claude" else None),
                (
                    "semantic search",
                    embeddings.embedding_model(cfg)
                    if embeddings.provider_name(cfg) == "ollama"
                    else None,
                ),
            )
            if active == name
        ]
        warn = (
            f"\n\n⚠ {name} is currently used by {', '.join(used_by)} — "
            "that job will stop working until you pick another model."
            if used_by
            else ""
        )
        ok = QMessageBox.question(
            dlg,
            "Delete model",
            f"Delete '{name}' from Ollama?\n\nThis frees disk space but you'll "
            f"need to pull it again to use it.{warn}",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        op_state["kind"] = "delete"
        set_busy(True)
        progress.setRange(0, 0)
        progress_lbl.setText(f"Deleting {name}…")

        def do() -> None:
            client().delete(name)

        def on_done(_: Any) -> None:
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            tooltip(f"Klaus: deleted {name}")
            refresh()

        def on_fail(exc: Exception) -> None:
            progress.setRange(0, 100)
            set_busy(False)
            op_state["kind"] = ""
            showWarning(f"Could not delete {name}:\n\n{type(exc).__name__}: {exc}")

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def start_pull() -> None:
        edit = pull_input.lineEdit()
        typed = (edit.text() if edit else "").strip()
        idx = pull_input.currentIndex()
        # Only trust currentData while the visible text still matches the
        # selected preset — after the user edits the line, currentIndex
        # goes stale and would silently pull the wrong model.
        if idx >= 0 and typed == pull_input.itemText(idx).strip():
            name = str(pull_input.currentData() or typed)
        else:
            name = typed
        name = name.strip()
        if not name:
            return
        op_state["kind"] = "pull"
        set_busy(True)
        progress.setValue(0)
        progress_lbl.setText(f"Starting pull of {name}…")

        def on_event(ev: dict) -> None:
            label, pct = _format_pull_event(ev)

            def apply() -> None:
                progress_lbl.setText(label)
                if pct:
                    progress.setValue(pct)

            mw.taskman.run_on_main(apply)

        def do() -> None:
            client().pull(name, on_event=on_event)

        def on_done(_: Any) -> None:
            progress.setValue(100)
            progress_lbl.setText(f"Pulled {name} ✓")
            set_busy(False)
            op_state["kind"] = ""
            tooltip(f"Klaus: {name} ready")
            refresh()

        def on_fail(exc: Exception) -> None:
            set_busy(False)
            op_state["kind"] = ""
            showWarning(f"Could not pull {name}:\n\n{type(exc).__name__}: {exc}")

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    # ----- Semantic search handlers ----------------------------------------

    def _embed_cfg_key(provider: str) -> str:
        return f"embedding_api_key_{provider}"

    def sync_embed_widgets() -> None:
        from . import embeddings

        ui_state["syncing"] = True
        try:
            cfg = get_config()
            provider = embeddings.provider_name(cfg)
            idx = max(0, embed_provider_combo.findData(provider))
            embed_provider_combo.setCurrentIndex(idx)
            # Local provider → offer the installed models; cloud → free text.
            embed_model_combo.clear()
            if provider == "ollama":
                for name in ui_state["models"]:
                    embed_model_combo.addItem(name, name)
            embed_model_combo.setEditText(str(cfg.get("embedding_model") or ""))
            edit = embed_model_combo.lineEdit()
            if edit is not None:
                edit.setPlaceholderText(
                    f"default: {embeddings.DEFAULT_MODELS[provider]}"
                )
            embed_key_edit.setText(str(cfg.get(_embed_cfg_key(provider)) or ""))
        finally:
            ui_state["syncing"] = False
        update_embed_status()

    def _fmt_ago(ts: float) -> str:
        secs = max(0, int(time.time() - ts))
        if secs < 90:
            return "just now"
        if secs < 5400:
            return f"{secs // 60} min ago"
        if secs < 172800:
            return f"{secs // 3600} h ago"
        return f"{secs // 86400} days ago"

    def update_embed_status() -> None:
        from . import curation, embeddings

        cfg = get_config()
        sig = embeddings.index_signature(cfg)
        provider = embed_provider_combo.currentData() or "ollama"
        is_cloud = provider != "ollama"
        for w in (embed_key_lbl, embed_key_edit):
            w.setVisible(is_cloud)
        st = curation.index_stats()
        if not st["exists"]:
            txt = "No card index yet — click “Index cards now” to enable semantic search."
        else:
            txt = f"{st['count']:,} cards indexed · updated {_fmt_ago(st['updated_at'])}"
            if (st["provider"], st["model"]) != sig:
                txt += " · settings changed: next indexing rebuilds from scratch"
        embed_status.setText(txt)

        # Row-level warning, matching the other two jobs.
        key_missing = is_cloud and not str(
            cfg.get(_embed_cfg_key(provider)) or ""
        ).strip()
        model_missing = (
            not is_cloud and sig[1] and sig[1] not in ui_state["models"]
        )
        if key_missing:
            site = "voyageai.com" if provider == "voyage" else "platform.openai.com"
            embed_warn.setText(f"⚠ key needed ({site})")
        elif model_missing:
            embed_warn.setText("⚠ not installed")
        embed_warn.setVisible(bool(key_missing or model_missing))
        embed_fix_btn.setVisible(bool(model_missing))

    def save_embed() -> None:
        if ui_state["syncing"]:
            return
        from . import embeddings

        cfg = get_config()
        provider = str(embed_provider_combo.currentData() or "ollama")
        prev = embeddings.provider_name(cfg)
        cfg["embedding_provider"] = provider
        if provider == prev:
            cfg["embedding_model"] = embed_model_combo.currentText().strip()
        else:
            # Provider switched: the typed model belongs to the old provider.
            cfg["embedding_model"] = ""
        if provider != "ollama":
            cfg[_embed_cfg_key(provider)] = embed_key_edit.text().strip()
        write_config(cfg)
        if provider != prev:
            sync_embed_widgets()  # reload model/key fields for the new provider
        else:
            update_embed_status()
        rebuild_library_list()  # the "used by: search" badge may have moved

    def finish_index() -> None:
        progress.setRange(0, 100)
        set_busy(False)
        cancel_btn.setVisible(False)
        op_state["kind"] = ""
        op_state["cancel"] = None

    def _dlg_alive() -> bool:
        try:
            dlg.isVisible()
            return True
        except RuntimeError:  # C++ side deleted (dialog closed)
            return False

    def _run_index() -> None:
        from . import curation, embeddings

        cancel_event = threading.Event()
        op_state["kind"] = "index"
        op_state["cancel"] = cancel_event
        set_busy(True)
        cancel_btn.setVisible(True)
        progress.setRange(0, 0)
        progress_lbl.setText("Scanning your notes…")

        def on_progress(label: str, done: int, total: int) -> None:
            if not _dlg_alive():
                return
            if total:
                progress.setRange(0, 100)
                progress.setValue(int(done * 100 / total))
                progress_lbl.setText(f"{label} {done:,} / {total:,}")
            else:
                progress.setRange(0, 0)
                progress_lbl.setText(label)

        def on_done(_index: Any, completed: bool) -> None:
            if _dlg_alive():
                finish_index()
                update_embed_status()
            tooltip(
                "Klaus: card index up to date"
                if completed
                else "Klaus: indexing cancelled — it resumes where it stopped"
            )

        def on_error(exc: Exception) -> None:
            if _dlg_alive():
                finish_index()
                update_embed_status()
            if isinstance(exc, embeddings.EmbeddingError):
                showWarning("Klaus indexing failed.\n\n" + exc.user_message())
            else:
                showWarning(
                    f"Klaus indexing failed.\n\n{type(exc).__name__}: {exc}"
                )

        curation.ensure_index(
            dlg,
            on_progress=on_progress,
            on_done=on_done,
            on_error=on_error,
            cancel=cancel_event,
        )

    def _pull_embedder_then_index(model: str) -> None:
        op_state["kind"] = "pull"
        set_busy(True)
        progress.setRange(0, 100)
        progress.setValue(0)
        progress_lbl.setText(f"Downloading embedding model {model}…")

        def on_event(ev: dict) -> None:
            label, pct = _format_pull_event(ev)

            def apply() -> None:
                if not _dlg_alive():
                    return
                progress_lbl.setText(label)
                if pct:
                    progress.setValue(pct)

            mw.taskman.run_on_main(apply)

        def do() -> None:
            client().pull(model, on_event=on_event)

        def on_done(_: Any) -> None:
            if not _dlg_alive():
                return
            set_busy(False)
            op_state["kind"] = ""
            refresh()
            _run_index()

        def on_fail(exc: Exception) -> None:
            if _dlg_alive():
                set_busy(False)
                op_state["kind"] = ""
            showWarning(
                f"Could not pull {model}:\n\n{type(exc).__name__}: {exc}"
            )

        op = QueryOp(parent=dlg, op=lambda col: do(), success=on_done)
        op.failure(on_fail)
        op.without_collection().run_in_background()

    def start_index() -> None:
        if op_state["active"]:
            return
        from . import curation, embeddings

        cfg = get_config()
        sig = embeddings.index_signature(cfg)
        provider, model = sig
        if provider != "ollama" and not str(
            cfg.get(_embed_cfg_key(provider)) or ""
        ).strip():
            showWarning(
                f"Enter your {provider} API key above before indexing."
            )
            return
        note_count = mw.col.note_count() if mw.col else 0
        st = curation.index_stats()
        rebuild_note = (
            "\n\nThe embedding settings changed, so the existing index is "
            "rebuilt from scratch."
            if st["exists"] and (st["provider"], st["model"]) != sig
            else ""
        )
        where = (
            "locally via Ollama — free and private"
            if provider == "ollama"
            else f"via the {provider} API — billed to your key"
        )
        ok = QMessageBox.question(
            dlg,
            "Index cards?",
            f"Klaus will embed {note_count:,} notes with {model} ({where}). "
            "You can cancel any time — progress is saved and indexing "
            f"resumes where it stopped.{rebuild_note}\n\nContinue?",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        if provider == "ollama" and model not in ui_state["models"]:
            _pull_embedder_then_index(model)
        else:
            _run_index()

    def confirm_close() -> None:
        if op_state["active"]:
            if op_state["kind"] == "index":
                ok = QMessageBox.question(
                    dlg,
                    "Stop indexing?",
                    "Card indexing is still running.\n\n"
                    "Stop it and close? Progress is saved — indexing resumes "
                    "where it stopped next time.",
                )
                if ok != QMessageBox.StandardButton.Yes:
                    return
                ev = op_state.get("cancel")
                if ev is not None:
                    ev.set()
                dlg.accept()
                return
            if op_state["kind"] == "setup":
                # Unlike pulls, a runtime download must not keep streaming
                # invisibly after the dialog goes away — cancel it.
                ok = QMessageBox.question(
                    dlg,
                    "Cancel setup?",
                    "The local AI setup is still downloading.\n\n"
                    "Cancel it and close? (Nothing partial is kept.)",
                )
                if ok != QMessageBox.StandardButton.Yes:
                    return
                cancel_setup_download()
                dlg.accept()
                return
            label = "operation"
            if op_state["kind"] == "pull":
                label = "model pull"
            elif op_state["kind"] == "install":
                label = "Ollama install"
            ok = QMessageBox.question(
                dlg,
                "Operation in progress",
                f"A {label} is running in the background.\n\n"
                "Close anyway? (It will continue.)",
            )
            if ok != QMessageBox.StandardButton.Yes:
                return
        dlg.accept()

    auto_setup_btn.clicked.connect(start_auto_setup)
    cancel_btn.clicked.connect(cancel_setup_download)
    dlg.confirm_close_cb = confirm_close  # Esc and title-bar ✕ too
    download_btn.clicked.connect(lambda: openLink(OLLAMA_DOWNLOAD_URL))
    check_conn_btn.clicked.connect(refresh)
    settings_btn.clicked.connect(open_config)
    delete_btn.clicked.connect(delete_selected)
    refresh_btn.clicked.connect(refresh)
    pull_btn.clicked.connect(start_pull)
    close_btn.clicked.connect(confirm_close)
    auto_combo.currentIndexChanged.connect(lambda _i: save_jobs())
    ask_combo.currentIndexChanged.connect(lambda _i: save_jobs())
    claude_key_edit.editingFinished.connect(save_jobs)
    claude_model_edit.editingFinished.connect(save_jobs)
    auto_pull_btn.clicked.connect(
        lambda: pull_missing(str(auto_combo.currentData() or ""))
    )
    ask_pull_btn.clicked.connect(lambda: pull_missing(ask_selection()[1]))
    embed_fix_btn.clicked.connect(
        lambda: pull_missing(embed_model_combo.currentText().strip())
    )
    embed_provider_combo.currentIndexChanged.connect(lambda _i: save_embed())
    _embed_model_edit_widget = embed_model_combo.lineEdit()
    if _embed_model_edit_widget is not None:
        _embed_model_edit_widget.editingFinished.connect(save_embed)
    embed_model_combo.currentIndexChanged.connect(lambda _i: save_embed())
    embed_key_edit.editingFinished.connect(save_embed)
    index_btn.clicked.connect(start_index)

    rebuild_install_method_buttons()
    refresh()
    if setup:
        if stack.currentIndex() == 0:
            # One-click path: go straight to the provisioning confirm.
            QTimer.singleShot(0, start_auto_setup)
        else:
            # Server already fine — jump to getting a first model.
            QTimer.singleShot(0, maybe_auto_pull_starter)
    dlg.exec()


def open_config() -> None:
    open_settings_dialog()


def _open_chat_dock() -> None:
    from . import chat_dock

    chat_dock.toggle_chat_dock()


def on_top_toolbar_right_tray(tray_content: list[str], toolbar: Any) -> None:
    """Klaus panel button in the toolbar's native top-right tray.

    create_link both registers the pycmd handler and returns the HTML;
    the hook re-fires on every toolbar draw (sync/theme/profile), so the
    button survives rebuilds for free. The same (list, toolbar) signature
    also fits top_toolbar_did_init_links, the fallback for older Anki.
    """
    tray_content.append(
        toolbar.create_link(
            "klausChatToggle",
            "Klaus",
            _open_chat_dock,
            tip=f"Klaus ({get_config().get('chat_hotkey', 'Ctrl+Shift+K')})",
            id="klaus-chat",
        )
    )


def install_menu() -> None:
    menu = mw.form.menuTools.addMenu("Klaus")

    a_chat = QAction("Open Klaus", mw)
    try:
        a_chat.setShortcut(
            QKeySequence(str(get_config().get("chat_hotkey", "Ctrl+Shift+K")))
        )
    except Exception:
        pass
    a_chat.triggered.connect(_open_chat_dock)
    menu.addAction(a_chat)

    a_clear_tag = QAction("Clear curation tag", mw)

    def _clear_tag() -> None:
        from . import curation

        curation.clear_curation_tag(mw)

    a_clear_tag.triggered.connect(_clear_tag)
    menu.addAction(a_clear_tag)

    a_clear_pdfmatch = QAction("Clear PDF-match tag", mw)

    def _clear_pdfmatch() -> None:
        from . import retention

        retention.clear_pdfmatch_tag(mw)

    a_clear_pdfmatch.triggered.connect(_clear_pdfmatch)
    menu.addAction(a_clear_pdfmatch)

    a_settings = QAction("Settings…", mw)
    a_settings.triggered.connect(open_settings_dialog)
    menu.addAction(a_settings)

    a_models = QAction("Manage models…", mw)
    a_models.triggered.connect(manage_models_dialog)
    menu.addAction(a_models)

    a_test = QAction("Test connection", mw)

    def test() -> None:
        if client().health():
            cfg = get_config()
            showInfo(
                "Connected to Ollama.\n\n"
                f"Autocomplete: {autocomplete_model(cfg)}\n"
                f"Ask (Cmd+K): {ask_model(cfg)}"
            )
        else:
            showWarning(
                "Could not reach Ollama at "
                f"{get_config().get('endpoint')}.\n"
                "Install/start it from https://ollama.com/download"
            )

    a_test.triggered.connect(test)
    menu.addAction(a_test)


# ------------------------------ PDF import -------------------------------


def import_pdf_file(path: str) -> str | None:
    """Import one PDF into the store; returns its safe name, or None.

    Shared by every import surface (editor drop bar, deck-screen drop,
    drive window). Warnings are shown here, so callers only branch on the
    return value. Multi-PDF model: importing never replaces or deletes a
    previous PDF — save_pdf just repoints the active-PDF marker.
    """
    if not pdf_handler.PDF_AVAILABLE:
        showWarning(
            "PDF support is not enabled.\n\n"
            "Run this once in a terminal:\n"
            "    cd klausmate && pip install --target vendor pypdf\n"
            "Then restart Anki."
        )
        return None
    base = os.path.splitext(os.path.basename(path))[0]
    try:
        info = pdf_handler.save_pdf(USER_FILES, base, path)
    except Exception as e:
        showWarning(f"Could not read PDF: {e}")
        return None
    if info["page_count"] == 0:
        showWarning(
            "No text extracted from this PDF.\n"
            "It might be a scanned image — OCR is not yet supported."
        )
    # Safe names are lossy; keep the original filename for the drive's
    # tree. Never let bookkeeping break an otherwise-good import.
    try:
        from . import drive_store

        drive_store.record_import(
            USER_FILES, info["name"], os.path.basename(path)
        )
    except Exception as e:
        print(f"[klausmate] drive display-name record failed: {e}")
    tooltip(f"Klaus: loaded '{info['name']}'")
    return str(info["name"])


# ----------------------------- editor panel ------------------------------


class _PdfBar(QFrame):
    """Single-row PDF control: drop/browse, status, remove, dock toggle."""

    _BAR_HEIGHT = 34
    _TOGGLE_SIZE = 26

    def __init__(
        self,
        on_pdf: Callable[[str], None],
        on_remove: Callable[[], None],
        on_toggle: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_pdf = on_pdf
        self._on_remove = on_remove
        self._has_pdf = False
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("klausmateDropZone")
        self.setFixedHeight(self._BAR_HEIGHT)
        self.setStyleSheet(
            "#klausmateDropZone {"
            " border: 1px solid rgba(0, 0, 0, 0.12);"
            " border-radius: 6px;"
            " background: rgba(0, 0, 0, 0.03);"
            "}"
            "#klausmateDropZone[dragOver=\"true\"] {"
            " background: rgba(80, 140, 255, 0.10);"
            " border-color: rgba(80, 140, 255, 0.55);"
            "}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(8)

        # Cobalt brand badge at the far left — mirrors the "Ask" cue in the
        # Cmd+K popover so both surfaces feel like the same product.
        self._klaus_label = QLabel("Klaus")
        self._klaus_label.setStyleSheet(
            "color: rgba(58, 130, 247, 0.95);"
            " font-weight: 600;"
            " font-size: 11px;"
            " letter-spacing: 0.3px;"
            " padding: 0 6px 0 2px;"
        )
        self._klaus_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        lay.addWidget(self._klaus_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._status = QLabel("Drop lecture PDF here")
        self._status.setStyleSheet(
            "color: rgba(120, 120, 120, 0.95); font-size: 11px;"
        )
        self._status.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        lay.addWidget(self._status, 1, Qt.AlignmentFlag.AlignVCenter)

        self._action_btn = QPushButton("Browse…")
        self._action_btn.setFlat(True)
        self._action_btn.setFixedHeight(self._TOGGLE_SIZE)
        self._action_btn.setMinimumWidth(64)
        self._action_btn.setStyleSheet("font-size: 11px;")
        self._action_btn.clicked.connect(self._browse)
        lay.addWidget(self._action_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setText("◨")
        self._toggle_btn.setFixedSize(self._TOGGLE_SIZE, self._TOGGLE_SIZE)
        self._toggle_btn.setToolTip("Show PDF viewer")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setStyleSheet(
            "QToolButton {"
            " border: 1px solid rgba(120, 120, 120, 0.35);"
            " border-radius: 5px;"
            " font-size: 14px;"
            " color: rgba(80, 80, 80, 0.95);"
            " background: rgba(120, 120, 120, 0.06);"
            "}"
            "QToolButton:hover {"
            " color: rgba(58, 130, 247, 0.95);"
            " border-color: rgba(58, 130, 247, 0.45);"
            " background: rgba(58, 130, 247, 0.10);"
            "}"
            "QToolButton:checked {"
            " color: rgba(58, 130, 247, 0.95);"
            " border-color: rgba(58, 130, 247, 0.55);"
            " background: rgba(58, 130, 247, 0.14);"
            "}"
        )
        self._toggle_btn.clicked.connect(on_toggle)
        lay.addWidget(self._toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def _elide_name(self, name: str) -> str:
        try:
            w = max(80, self._status.width() - 8)
            return self.fontMetrics().elidedText(
                name, Qt.TextElideMode.ElideMiddle, w
            )
        except Exception:
            return name

    def _set_action_browse(self) -> None:
        self._has_pdf = False
        try:
            self._action_btn.clicked.disconnect()
        except Exception:
            pass
        self._action_btn.setText("Browse…")
        self._action_btn.clicked.connect(self._browse)

    def _set_action_remove(self) -> None:
        self._has_pdf = True
        try:
            self._action_btn.clicked.disconnect()
        except Exception:
            pass
        self._action_btn.setText("Remove")
        self._action_btn.clicked.connect(self._on_remove)

    def set_active_pdf(self, name: str | None) -> None:
        if name:
            self._status.setText(self._elide_name(name))
            self._status.setToolTip(name)
            self._set_action_remove()
        else:
            self._status.setText("Drop lecture PDF here")
            self._status.setToolTip("")
            self._set_action_browse()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        tip = self._status.toolTip()
        if tip:
            self._status.setText(self._elide_name(tip))

    def update_toggle(self, visible: bool) -> None:
        try:
            self._toggle_btn.setChecked(bool(visible))
            self._toggle_btn.setToolTip(
                "Hide PDF viewer" if visible else "Show PDF viewer"
            )
        except RuntimeError:
            pass

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF", "", "PDF files (*.pdf)"
        )
        if path:
            self._on_pdf(path)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:  # type: ignore[override]
        md = e.mimeData()
        if md and md.hasUrls():
            for url in md.urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    self.setProperty("dragOver", "true")
                    self.style().unpolish(self); self.style().polish(self)
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dragLeaveEvent(self, e: Any) -> None:  # type: ignore[override]
        self.setProperty("dragOver", "false")
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, e: QDropEvent) -> None:  # type: ignore[override]
        self.setProperty("dragOver", "false")
        self.style().unpolish(self); self.style().polish(self)
        md = e.mimeData()
        if not md:
            return
        for url in md.urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self._on_pdf(path)
        e.acceptProposedAction()


class _KlausmatePanel(QWidget):
    def __init__(self, editor: Editor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor = editor

        outer = QVBoxLayout(self)
        # Zero horizontal margin: Anki's editor layout already pads the
        # row, so adding our own would inset the bar relative to the Tags
        # input above it. Vertical 4 px stays for breathing room.
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)

        self._pdf_bar = _PdfBar(
            self._handle_pdf,
            self._remove_current_pdf,
            self._toggle_viewer,
            parent=self,
        )
        outer.addWidget(self._pdf_bar)
        self._refresh_pdf_status()

    def _ensure_sidebar_pdf(self) -> bool:
        """Load active PDF into the dock viewer if needed."""
        active = pdf_handler.get_active_pdf(USER_FILES)
        if not active:
            return False
        sidebar = getattr(self._editor, "_klausmate_sidebar", None)
        if sidebar is None:
            return False
        if not sidebar.is_loaded(active):
            sidebar.load_pdf(active)
        return True

    def _toggle_viewer(self) -> None:
        tabs = getattr(self._editor, "_klausmate_pdf_tabs", None)
        if tabs is None:
            tooltip("Klaus: PDF viewer is unavailable in this window")
            return
        if tabs.isVisible():
            tabs.panel_hide()
        else:
            self._ensure_sidebar_pdf()
            tabs.panel_show()
        self._update_toggle_label(tabs.isVisible())

    def _update_toggle_label(self, visible: bool) -> None:
        try:
            self._pdf_bar.update_toggle(visible)
        except RuntimeError:
            pass

    def _handle_pdf(self, path: str) -> None:
        if import_pdf_file(path) is None:
            return
        self._refresh_pdf_status()
        self._open_active_pdf()

    def _refresh_pdf_status(self) -> None:
        active = pdf_handler.get_active_pdf(USER_FILES)
        try:
            self._pdf_bar.set_active_pdf(active)
        except RuntimeError:
            pass

    def _remove_current_pdf(self) -> None:
        active = pdf_handler.get_active_pdf(USER_FILES)
        if not active:
            return
        if not askUser(f"Remove lecture PDF '{active}'?", parent=self):
            return
        pdf_handler.delete_context(USER_FILES, active)
        tabs = getattr(self._editor, "_klausmate_pdf_tabs", None)
        if tabs is not None:
            # Closing the tab switches the viewer to a neighbouring open
            # PDF, or clears + hides the dock if this was the last one.
            tabs.close_tab(active)
        else:
            sidebar = getattr(self._editor, "_klausmate_sidebar", None)
            if sidebar is not None:
                sidebar.clear()
        self._refresh_pdf_status()

    def _open_active_pdf(self) -> None:
        if not pdf_handler.get_active_pdf(USER_FILES):
            return
        tabs = getattr(self._editor, "_klausmate_pdf_tabs", None)
        if tabs is None:
            tooltip("Klaus: PDF viewer is unavailable in this window")
            return
        self._ensure_sidebar_pdf()
        tabs.panel_show()
        self._update_toggle_label(True)


class _PdfTabContainer(QWidget):
    """The PDF viewer panel, with native-feeling window management.

    One bar of chrome: ``[tabs ✕] [page n/m] [＋]``. The panel lives in
    one of three places — docked ABOVE the note-editor pane, docked BELOW
    it, or FLOATING as a normal macOS window. Docking wraps
    ``editor.widget`` in a vertical splitter (created once, kept for the
    window's lifetime), so "above" means above *that pane*, never the
    whole window.

    Window management mirrors macOS conventions:

    - **drag a tab out of the tab-bar band** (or drag any empty bar
      space) → the REAL panel floats instantly and macOS moves it live
      under the cursor (``QWindow.startSystemMove``); wide bands over
      the editor pane preview exactly where it would dock (arrow +
      caption, sized like the real 45% split). Release on a band to
      dock there, anywhere else to stay floating. Dragging an already-
      floating panel by its bar is the same native move. Drags that
      stay inside the tab bar just reorder tabs, in any direction. A
      translucent-ghost fallback covers the rare case where the OS
      refuses/drops the native move (see the drag state machine in
      ``__init__``).
    - the floating panel is a real, parentless macOS window: it shows
      in Mission Control, minimizes to the Dock, and Anki can come in
      front of it. Its red traffic light hides the panel; its lifetime
      is tied to the host window via ``_on_host_closing``.
    - **✕ on each tab** closes that PDF (the stored file survives; reopen
      it from ＋). Closing the last tab hides the panel.
    - **＋** opens another stored PDF or a new file from disk

    One viewer instance is reused across tabs; switching loads that PDF
    and repoints the active-PDF marker, so autocomplete/Ask retrieval
    always follows the visible tab. Per-tab reading position is kept for
    the session; the tab set and placement persist across restarts.
    """

    def __init__(
        self,
        editor: Editor,
        sidebar: Any,
        main_window: Any,
    ) -> None:
        super().__init__(None)
        self._editor = editor
        self._sidebar = sidebar
        self._win = main_window
        self._syncing = False
        self._last_page: dict[str, int] = {}

        # Placement state (persisted). _placed means the panel has been
        # physically put somewhere this session; until then panel_show()
        # applies the remembered placement.
        state = pdf_handler.load_panel_state(USER_FILES)
        self._placement: str = state.get("placement", "above")
        g = state.get("geom")
        self._float_geom: QRect | None = QRect(*g) if g else None
        self._placed = False

        # Drag state machine. A bar/tab drag instantly floats the REAL
        # panel and hands the move to macOS via
        # QWindow.startSystemMove(); Qt then stops delivering mouse
        # events to us, so the gesture's end is detected by a 100ms
        # heartbeat timer plus an application-level event filter (see
        # _drag_tick / _finalize_drag). On Cocoa, startSystemMove()
        # returns True even when the window never actually follows the
        # cursor (performWindowDragWithEvent: can silently no-op when
        # the NSEvent originated in the old host window) — a watchdog
        # in the heartbeat detects that and falls back to manually
        # following the cursor; the old translucent-ghost tear-off is
        # kept only for gestures after native move is proven broken.
        #
        # _drag_state ∈ {idle, pressed, native, armed, manual_follow,
        # manual_ghost}:
        #   idle          — no gesture
        #   pressed       — button down on the bar, threshold not met
        #   native        — macOS is (believed to be) moving the window
        #   armed         — drag went quiet; next definitive event ends it
        #   manual_follow — heartbeat/mouse events move the window
        #   manual_ghost  — embedded fallback: ghost follows, panel
        #                   relocates on release (pre-native behavior)
        self._press_gp: QPoint | None = None
        self._press_on_tab = False
        self._drag_state = "idle"
        # True only while WE send the synthetic tab-release below —
        # sendEvent re-enters this eventFilter, and the release branch
        # must let it pass through to the tab bar untouched instead of
        # resetting the gesture that is just starting.
        self._synthetic_release = False
        # None = untested, True = proven working, False = proven broken
        # (watchdog tripped / startSystemMove refused) → fall back.
        self._native_move_ok: bool | None = None
        self._drag_off: QPoint | None = None
        self._active_zone: str | None = None
        self._zone_overlay: QWidget | None = None
        self._ghost: QLabel | None = None
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(100)
        self._drag_timer.timeout.connect(self._drag_tick)
        self._drag_started = 0.0
        self._last_activity = 0.0
        # Direct drag evidence only: panel moveEvents while the gesture
        # owns the window, and mouse events with the left button held.
        # _last_activity (raw cursor motion) is too weak for the embed
        # freshness gate — it keeps refreshing after an unobserved
        # release; it is kept only for the armed 10s give-up cap.
        self._last_drag_evidence = 0.0
        self._last_cursor: QPoint | None = None
        self._move_seen = False
        # Where the window / cursor were when the drag machinery armed:
        # a moveEvent only counts as proof that the native move works
        # once one of them has travelled >8px — a spurious post-tear-off
        # geometry adjustment must not disarm the watchdog.
        self._drag_origin_pos: QPoint | None = None
        self._drag_start_cursor: QPoint | None = None
        self._app_filter_installed = False
        self._closed = False

        # Host lifetime: the floating panel is a PARENTLESS window (so
        # macOS treats it as a real one — Mission Control, Dock
        # minimize, can go behind Anki), which means it no longer dies
        # with the Browse/Add window that spawned it. Watch the host
        # for Close and take the panel down with it; the destroyed
        # signal is a backstop for hosts torn down without a Close.
        try:
            self._win.installEventFilter(self)
        except Exception:
            pass
        try:
            self._win.destroyed.connect(self._on_host_destroyed)
        except Exception:
            pass

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # The header is a real widget (not a bare layout) so it can take
        # mouse events: dragging its empty area moves/tears off the panel.
        self._header = QWidget(self)
        self._header.setFixedHeight(30)
        self._header.setCursor(Qt.CursorShape.OpenHandCursor)
        header = QHBoxLayout(self._header)
        header.setContentsMargins(6, 2, 6, 0)
        header.setSpacing(4)
        self._header.installEventFilter(self)

        self._tabs = QTabBar(self._header)
        self._tabs.setDocumentMode(True)
        self._tabs.setDrawBase(False)
        self._tabs.setMovable(True)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setExpanding(False)
        self._tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabMoved.connect(lambda *_: self._persist())
        # The tab bar stretches across the whole row, so it — not the
        # header — is what the user actually drags. Filter it too.
        self._tabs.installEventFilter(self)

        # Controls sit on the LEFT of the bar (Preview-style: sidebar
        # toggle at the far left), the tabs take the remaining width.
        viewer = getattr(sidebar, "_viewer", None)

        # Thumbnails-strip toggle. No checked-state bookkeeping: the
        # strip itself is the visible indicator.
        thumbs_btn = QToolButton(self._header)
        thumbs_btn.setText("◫")
        thumbs_btn.setAutoRaise(True)
        thumbs_btn.setToolTip("Show/hide page thumbnails")

        def _toggle_thumbs() -> None:
            try:
                if viewer is not None:
                    viewer.toggle_thumbnails()
            except Exception as exc:
                print(f"[klausmate] thumbnails toggle failed: {exc}")

        thumbs_btn.clicked.connect(_toggle_thumbs)
        header.addWidget(thumbs_btn)

        add_btn = QToolButton(self._header)
        add_btn.setText("＋")
        add_btn.setAutoRaise(True)
        add_btn.setToolTip("Open another PDF in a new tab")
        add_btn.clicked.connect(self._show_add_menu)
        self._add_btn = add_btn
        header.addWidget(add_btn)

        header.addWidget(self._tabs, 1)

        # The viewer's page indicator sits at the right end of the bar.
        page_label = (
            getattr(viewer, "_page_label", None) if viewer is not None else None
        )
        if page_label is not None:
            page_label.setVisible(True)
            header.addWidget(page_label)

        lay.addWidget(self._header)
        lay.addWidget(sidebar, 1)

        sidebar.on_loaded = self._on_sidebar_loaded

        # Restore last session's tab set as labels only — the document
        # itself loads lazily when a tab is selected / the panel is shown.
        self._syncing = True
        try:
            for name in pdf_handler.load_open_tabs(USER_FILES):
                if self._find_tab(name) < 0:
                    self._decorate_tab(self._tabs.addTab(name))
        finally:
            self._syncing = False

    # ---- show / hide (called by the Klaus bar toggle & chips) ----

    def panel_show(self) -> None:
        if not self._placed:
            if self._placement == "float":
                self._make_floating(self._float_geom)
            else:
                self._embed(self._placement)
        if self.isWindow():
            try:
                if self.isMinimized():
                    self.showNormal()
            except Exception:
                pass
            self.show()
            self.raise_()
        else:
            self.setVisible(True)

    def panel_hide(self) -> None:
        self.hide()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        panel = getattr(self._editor, "_klausmate_panel", None)
        if panel is not None:
            try:
                panel._update_toggle_label(True)
                panel._ensure_sidebar_pdf()
            except Exception:
                pass
        # Re-arm page-window retrieval (hideEvent cleared it).
        try:
            if self._sidebar._name is not None:
                self._sidebar._on_page_changed(
                    getattr(self._sidebar, "_current_page", 0)
                )
        except Exception:
            pass

    def hideEvent(self, ev) -> None:  # noqa: N802
        super().hideEvent(ev)
        if self.isWindow():
            self._remember_float_geom()
        try:
            self._sidebar._set_active(None)
        except Exception:
            pass
        panel = getattr(self._editor, "_klausmate_panel", None)
        if panel is not None:
            try:
                panel._update_toggle_label(False)
            except Exception:
                pass

    # ---- placement engine ----

    def _ensure_vsplit(self) -> QSplitter | None:
        """Wrap the editor pane in a vertical splitter (once per window)."""
        existing = getattr(self._editor, "_klausmate_vsplit", None)
        if existing is not None:
            return existing
        ed_w = getattr(self._editor, "widget", None)
        if ed_w is None:
            return None
        parent = ed_w.parentWidget()
        if parent is None:
            return None
        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.setChildrenCollapsible(False)
        try:
            # Inherit the pane's size policy. AddCards' fieldsArea carries
            # verticalStretch=10 — the only hint giving it ALL surplus
            # window height. QSplitter's default policy is orientation-
            # dependent (vertically Preferred when horizontal), so without
            # this the Type/Deck row balloons into blank space whenever
            # the panel docks left/right.
            vsplit.setSizePolicy(ed_w.sizePolicy())
        except Exception:
            pass
        if isinstance(parent, QSplitter):
            idx = parent.indexOf(ed_w)
            sizes = parent.sizes()
            parent.insertWidget(idx, vsplit)
            vsplit.addWidget(ed_w)  # reparents ed_w out of parent
            try:
                parent.setSizes(sizes)
            except Exception:
                pass
        else:
            lay = parent.layout()
            if lay is None:
                return None
            lay.replaceWidget(ed_w, vsplit)
            vsplit.addWidget(ed_w)
        ed_w.setVisible(True)
        self._editor._klausmate_vsplit = vsplit  # type: ignore[attr-defined]
        return vsplit

    def _embed(self, mode: str) -> None:
        """Dock the panel on one side of the editor pane. The wrapper
        splitter's orientation follows the side: above/below → vertical,
        left/right → horizontal."""
        vsplit = self._ensure_vsplit()
        if vsplit is None:
            self._make_floating(self._float_geom)
            return
        vertical = mode in ("above", "below")
        vsplit.setOrientation(
            Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
        )
        # setOrientation transposes QSplitter's size policy — re-assert the
        # inherited pane policy so the wrapper keeps absorbing the window's
        # surplus height in every orientation.
        try:
            ed_w = getattr(self._editor, "widget", None)
            if ed_w is not None:
                vsplit.setSizePolicy(ed_w.sizePolicy())
        except Exception:
            pass
        first = mode in ("above", "left")
        vsplit.insertWidget(0 if first else vsplit.count(), self)
        self.setVisible(True)
        total = max(1, vsplit.height() if vertical else vsplit.width())
        pdf_share = int(total * 0.45)
        sizes = (
            [pdf_share, total - pdf_share]
            if first
            else [total - pdf_share, pdf_share]
        )
        try:
            vsplit.setSizes(sizes)
        except Exception:
            pass
        self._placement = mode
        self._placed = True
        self._persist_state()

    def _make_floating(self, geom: QRect | None) -> None:
        """Turn the panel into a real, PARENTLESS macOS window: it shows
        in Mission Control, minimizes to the Dock, and Anki can come in
        front of it (a child window would be forced always-on-top of its
        parent). Its red ✕ still just hides the panel (default QWidget
        close), and _on_host_closing() ties its lifetime to the host.

        Sequence matters: setParent(None) → flags → geometry → show() —
        only after show() does windowHandle() exist for
        startSystemMove()."""
        self.setParent(None)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setWindowTitle("PDF — Klaus")
        if geom is not None and geom.width() > 200 and geom.height() > 200:
            self.setGeometry(geom)
        else:
            try:
                wg = self._win.geometry()
                self.setGeometry(
                    wg.x() + max(40, wg.width() - 560),
                    wg.y() + 80,
                    520,
                    640,
                )
            except Exception:
                self.resize(520, 640)
        self.show()
        self.raise_()
        self._placement = "float"
        self._placed = True
        self._persist_state()

    def _remember_float_geom(self) -> None:
        # A minimized window reports Dock-related geometry — don't let
        # that overwrite the real placement.
        try:
            if self.isMinimized():
                return
        except Exception:
            pass
        if self.isWindow():
            self._float_geom = QRect(self.geometry())

    def _persist_state(self) -> None:
        geom = None
        if self.isWindow():
            self._remember_float_geom()
        if self._float_geom is not None:
            g = self._float_geom
            geom = [g.x(), g.y(), g.width(), g.height()]
        try:
            pdf_handler.save_panel_state(
                USER_FILES, placement=self._placement, geom=geom
            )
        except Exception:
            pass

    # ---- host lifetime ----

    def _host_close_check(self) -> None:
        """Deferred from the host's Close event: only tear down when the
        close was actually accepted — the host may have evt.ignore()d it
        (e.g. AddCards' discard prompt was cancelled), in which case
        tearing down would leave live references to a dead panel."""
        try:
            still_up = bool(self._win.isVisible())
        except Exception:
            # Dead wrapper — the host is definitely gone.
            still_up = False
        if not still_up:
            try:
                self._on_host_closing()
            except Exception as exc:
                print(f"[klausmate] pdf host-close teardown failed: {exc}")

    def _on_host_closing(self) -> None:
        """The Browse/Add window that spawned this panel is closing.
        Embedded panels die with it naturally; a floating panel is
        parentless (see _make_floating) and must be taken down
        explicitly or it would linger as a zombie window."""
        if self._closed:
            return
        try:
            if self._drag_state != "idle":
                self._reset_drag()
        except Exception:
            pass
        try:
            self._persist_state()
        except Exception:
            pass
        # The drop-zone overlay is a parentless top-level window too.
        ov = self._zone_overlay
        if ov is not None:
            self._zone_overlay = None
            try:
                ov.hide()
                ov.deleteLater()
            except Exception:
                pass
        if self.isWindow():
            self._closed = True
            print("[klausmate] pdf drag: host closing — closing floating panel")
            try:
                self.close()
            except Exception:
                pass
            try:
                self.deleteLater()
            except Exception:
                pass
        # The host is really going away — drop the back-references so a
        # later editor re-init / toggle can't reach a dead widget.
        try:
            self._win._klausmate_pdf_container = None
        except Exception:
            pass
        try:
            ed = self._editor
            if getattr(ed, "_klausmate_pdf_tabs", None) is self:
                ed._klausmate_pdf_tabs = None  # type: ignore[attr-defined]
                ed._klausmate_sidebar = None  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_host_destroyed(self, *_args) -> None:
        """Backstop for hosts destroyed without a Close event. The C++
        side of our widgets may already be gone, so everything is
        guarded — worst case this is a silent no-op."""
        try:
            self._on_host_closing()
        except Exception:
            pass

    # ---- drag: tear off / move / drop-dock ----

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        t = ev.type()

        # -- host lifetime -------------------------------------------
        try:
            if obj is self._win and t == QEvent.Type.Close:
                # The host may still evt.ignore() this Close (e.g. the
                # user cancels AddCards' discard prompt), so NEVER tear
                # down synchronously — check next tick whether the
                # window actually went away.
                QTimer.singleShot(0, self._host_close_check)
                return False  # never block the host's close
        except Exception:
            pass

        # -- application-level drag finalize --------------------------
        # While macOS runs a system move, Qt may never deliver the
        # release to this widget at all. This filter (installed on the
        # QApplication only for the drag's duration) closes the gesture
        # out on the next definitive event ANYWHERE: a release, a fresh
        # press, or a mouse move with no buttons held (i.e. the release
        # happened while Qt wasn't looking). Application filters run
        # before object filters, so a new press on our own bar first
        # finalizes the old drag here, then starts cleanly below.
        if (
            self._app_filter_installed
            and not self._synthetic_release
            and self._drag_state in ("native", "manual_follow", "armed")
        ):
            try:
                if t == QEvent.Type.MouseButtonRelease:
                    self._finalize_drag(True, "app-filter release")
                elif t == QEvent.Type.MouseButtonPress:
                    self._finalize_drag(True, "app-filter press")
                elif t == QEvent.Type.MouseMove:
                    if ev.buttons() == Qt.MouseButton.NoButton:
                        self._finalize_drag(
                            True, "app-filter buttonless move"
                        )
                    elif ev.buttons() & Qt.MouseButton.LeftButton:
                        # Left button demonstrably still held → the
                        # drag is alive (feeds the freshness gate).
                        self._last_drag_evidence = time.time()
            except Exception:
                pass

        # -- bar / tab gestures ---------------------------------------
        if obj is self._header or obj is self._tabs:
            if (
                t == QEvent.Type.MouseButtonPress
                and ev.button() == Qt.MouseButton.LeftButton
            ):
                gp = ev.globalPosition().toPoint()
                self._press_gp = gp
                self._drag_state = "pressed"
                # A press on an actual tab must stay draggable-for-
                # reorder; it only becomes a panel drag once the cursor
                # leaves the tab-bar band. A press on empty tab-bar
                # space (or header margins / page label) drags the
                # panel after a small threshold.
                self._press_on_tab = (
                    obj is self._tabs
                    and self._tabs.tabAt(ev.position().toPoint()) >= 0
                )
                if self.isWindow():
                    self._drag_off = (
                        gp - self.window().frameGeometry().topLeft()
                    )
                else:
                    self._drag_off = None
                return False  # let the tab bar select/reorder normally
            if t == QEvent.Type.MouseMove and self._press_gp is not None:
                gp = ev.globalPosition().toPoint()
                state = self._drag_state
                if state == "pressed":
                    if self._press_on_tab:
                        # Tab presses tear off when the cursor leaves
                        # the tab-bar band — in ANY direction. Inside
                        # the band, drags keep reordering tabs forever.
                        try:
                            band = self._tabs.rect().adjusted(-4, -4, 4, 4)
                            escaped = not band.contains(
                                self._tabs.mapFromGlobal(gp)
                            )
                        except Exception:
                            escaped = False
                    else:
                        escaped = (gp - self._press_gp).manhattanLength() > 8
                    if not escaped:
                        return False
                    self._header.setCursor(Qt.CursorShape.ClosedHandCursor)
                    if self._press_on_tab:
                        # The tab bar started a reorder-drag; close it out
                        # with a synthetic release so it doesn't keep a
                        # half-dragged tab while we move the whole panel.
                        # (_synthetic_release keeps the reentrant filter
                        # call from resetting our gesture state.)
                        self._synthetic_release = True
                        try:
                            QApplication.sendEvent(
                                self._tabs,
                                QMouseEvent(
                                    QEvent.Type.MouseButtonRelease,
                                    QPointF(
                                        self._tabs.mapFromGlobal(gp)
                                    ),
                                    QPointF(gp),
                                    Qt.MouseButton.LeftButton,
                                    Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier,
                                ),
                            )
                        except Exception:
                            pass
                        finally:
                            self._synthetic_release = False
                    self._start_panel_drag(gp)
                    return True
                if state == "manual_ghost":
                    # Fallback tear-off: drive the ghost only — the real
                    # panel is relocated on release. Reparenting it here,
                    # mid-gesture, would destroy the NSView that owns the
                    # Cocoa drag session and kill the mouse tracking.
                    self._drag_ghost_to(gp)
                    self._update_zone(gp)
                    return True
                if state == "manual_follow":
                    # Fallback live-move for a floating panel (mouse
                    # tracking is sound here — nothing was reparented).
                    try:
                        self.window().move(
                            gp - (self._drag_off or QPoint(60, 15))
                        )
                    except Exception:
                        pass
                    self._update_zone(gp)
                    self._last_activity = time.time()
                    try:
                        if ev.buttons() & Qt.MouseButton.LeftButton:
                            self._last_drag_evidence = time.time()
                    except Exception:
                        pass
                    return True
                if state in ("native", "armed"):
                    # Shouldn't normally arrive while the OS owns the
                    # move; treat it as a sign of life either way.
                    self._last_activity = time.time()
                    try:
                        if ev.buttons() & Qt.MouseButton.LeftButton:
                            self._last_drag_evidence = time.time()
                    except Exception:
                        pass
                    if state == "armed":
                        if self._native_move_ok is False:
                            # Native move is proven broken — resume in
                            # the mode that actually works and handle
                            # THIS event as a cursor-follow move.
                            self._drag_state = "manual_follow"
                            try:
                                self.window().move(
                                    gp
                                    - (self._drag_off or QPoint(60, 15))
                                )
                            except Exception:
                                pass
                            self._update_zone(gp)
                        else:
                            self._drag_state = "native"
                    return True
                return False
            if (
                t == QEvent.Type.MouseButtonRelease
                and ev.button() == Qt.MouseButton.LeftButton
            ):
                # Only the LEFT release ends a gesture — the press that
                # started it was LeftButton-gated, so a stray middle /
                # right click mid-drag must pass through untouched.
                if self._synthetic_release:
                    # Our own synthetic tab-release passing through on
                    # its way to the tab bar — not a gesture end.
                    return False
                state = self._drag_state
                if state == "pressed":
                    self._press_gp = None
                    self._drag_state = "idle"
                    return False  # plain click: let the tab bar have it
                if state == "manual_ghost":
                    gp = ev.globalPosition().toPoint()
                    zone = self._active_zone
                    self._reset_drag()
                    print(
                        "[klausmate] pdf drag: ghost drop "
                        f"(zone={zone})"
                    )
                    if zone:
                        # Embedded → re-dock on another side directly.
                        self._embed(zone)
                    else:
                        # Float at the drop point — safe now that the
                        # button is up (no gesture left to kill).
                        self._tear_off(gp)
                    return True
                if state in ("native", "manual_follow", "armed"):
                    self._finalize_drag(True, "bar release")
                    return True
                return False
        return super().eventFilter(obj, ev)

    def _start_panel_drag(self, gp: QPoint) -> None:
        """A bar/tab drag gesture crossed its threshold — route it.

        Primary path: float the REAL panel at the cursor and hand the
        move to macOS (startSystemMove). Once _native_move_ok is False
        (startSystemMove refused, or the watchdog caught it lying),
        embedded tear-offs take the translucent-ghost path. An ALREADY-
        FLOATING panel always re-probes startSystemMove() — no reparent
        is involved, so this is the guaranteed-sound case — and the
        watchdog / moveEvent verdict lets _native_move_ok heal back to
        True (or stay False) for this session."""
        if self._native_move_ok is False and not self.isWindow():
            self._drag_state = "manual_ghost"
            print("[klausmate] pdf drag: begin (manual_ghost fallback)")
            self._drag_ghost_to(gp)
            self._update_zone(gp)
            return
        if not self.isWindow():
            self._tear_off(gp)
        started = False
        try:
            wh = self.window().windowHandle()
            if wh is not None:
                started = bool(wh.startSystemMove())
        except Exception:
            started = False
        if not started:
            # Refused outright → proven broken; this drag still works
            # via cursor-follow, future gestures use the ghost path.
            self._native_move_ok = False
            print(
                "[klausmate] pdf drag: startSystemMove refused — "
                "cursor-follow fallback"
            )
        self._arm_drag_machinery("native" if started else "manual_follow")

    def _arm_drag_machinery(self, state: str) -> None:
        """Start the heartbeat + app filter that shepherd a native (or
        cursor-follow) drag to its finalize."""
        now = time.time()
        self._drag_started = now
        self._last_activity = now
        # The gesture just crossed its threshold under a held left
        # button — that IS direct drag evidence.
        self._last_drag_evidence = now
        self._move_seen = False
        try:
            self._last_cursor = QPoint(QCursor.pos())
        except Exception:
            self._last_cursor = None
        try:
            self._drag_start_cursor = QPoint(QCursor.pos())
        except Exception:
            self._drag_start_cursor = None
        # Post-tear-off origin: a moveEvent only proves the native move
        # once the window (or cursor) has left this point by >8px.
        try:
            self._drag_origin_pos = QPoint(
                self.window().frameGeometry().topLeft()
            )
        except Exception:
            self._drag_origin_pos = None
        self._drag_state = state
        self._install_app_filter()
        if not self._drag_timer.isActive():
            self._drag_timer.start()
        print(f"[klausmate] pdf drag: begin ({state})")

    def _install_app_filter(self) -> None:
        if self._app_filter_installed:
            return
        try:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
                self._app_filter_installed = True
        except Exception:
            pass

    def _displaced_enough(self) -> bool:
        """True once the window or the cursor has demonstrably travelled
        (>8px) since the drag machinery armed — the bar a moveEvent must
        clear before it counts as proof that the native move works."""
        try:
            if self._drag_origin_pos is not None:
                d = (
                    self.window().frameGeometry().topLeft()
                    - self._drag_origin_pos
                )
                if d.manhattanLength() > 8:
                    return True
        except Exception:
            pass
        try:
            if self._drag_start_cursor is not None:
                d = QCursor.pos() - self._drag_start_cursor
                if d.manhattanLength() > 8:
                    return True
        except Exception:
            pass
        return False

    def moveEvent(self, ev) -> None:  # noqa: N802
        super().moveEvent(ev)
        # Gated strictly on the drag state: ordinary moves (title-bar
        # drags of the floating window, layout changes) stay inert.
        if self._drag_state not in ("native", "armed", "manual_follow"):
            return
        now = time.time()
        if self._drag_state == "armed":
            # Only a move backed by recent drag evidence resumes the
            # gesture. Anything else (a native title-bar drag of a
            # zombie-armed panel, an async layout adjustment) is a
            # plain user reposition — no zone tracking, no promotion.
            held = False
            try:
                held = bool(
                    QApplication.mouseButtons()
                    & Qt.MouseButton.LeftButton
                )
            except Exception:
                pass
            if not held and now - self._last_drag_evidence > 1.0:
                return
            self._drag_state = (
                "manual_follow"
                if self._native_move_ok is False
                else "native"
            )
        if not self._move_seen:
            if (
                self._drag_state == "native"
                and not self._displaced_enough()
            ):
                # A spurious async geometry adjustment right after
                # tear-off must not count as native confirmation — it
                # would set _native_move_ok and permanently disarm the
                # watchdog. Stay unconfirmed.
                return
            self._move_seen = True
            if self._drag_state == "native":
                # The window demonstrably follows → native move works.
                self._native_move_ok = True
        self._last_activity = now
        # The panel moved while the gesture owns the window — direct
        # drag evidence (feeds the freshness gate in _finalize_drag).
        self._last_drag_evidence = now
        try:
            self._update_zone(QCursor.pos())
        except Exception:
            pass

    def _drag_tick(self) -> None:
        """100ms heartbeat while a native/cursor-follow drag runs.

        startSystemMove() lies on Cocoa — it returns True even when
        performWindowDragWithEvent: silently no-ops — and during a REAL
        system move Qt receives no mouse events, so the gesture's end
        can't be observed directly. Tiers:

        1. watchdog (only until the first moveEvent): the cursor has
           clearly travelled but the window never moved → native move
           is dead; demote to cursor-follow and remember the verdict.
        2. primary end: Qt saw every button go up → finalize.
        3. staleness: nothing moved for a while → "armed"; the app
           filter finalizes on the next definitive event, a new
           moveEvent re-activates, and a 10s cap gives up WITHOUT
           embedding.
        """
        state = self._drag_state
        if state not in ("native", "manual_follow", "armed"):
            self._drag_timer.stop()
            return
        now = time.time()
        try:
            cur = QPoint(QCursor.pos())
        except Exception:
            return
        moved = self._last_cursor is not None and cur != self._last_cursor
        self._last_cursor = cur
        if moved:
            self._last_activity = now

        # 1. Watchdog.
        if (
            state == "native"
            and not self._move_seen
            and now - self._drag_started >= 0.3
            and self._press_gp is not None
            and (cur - self._press_gp).manhattanLength() > 40
        ):
            self._native_move_ok = False
            self._drag_state = state = "manual_follow"
            print(
                "[klausmate] pdf drag: watchdog — native move dead, "
                "cursor-follow fallback"
            )

        # Cursor-follow: the heartbeat IS the drag.
        if state == "manual_follow":
            try:
                self.window().move(cur - (self._drag_off or QPoint(60, 15)))
            except Exception:
                pass
            self._update_zone(cur)

        # 2. Primary end.
        try:
            buttons_up = (
                QApplication.mouseButtons() == Qt.MouseButton.NoButton
            )
        except Exception:
            buttons_up = False
        if buttons_up:
            self._finalize_drag(True, "buttons-up")
            return

        # 3. Staleness.
        if state in ("native", "manual_follow"):
            if not moved and now - self._last_activity > 0.6:
                self._drag_state = "armed"
                # A quiet gesture may already be a dead one (the
                # release can be unobservable) — drop the dock preview
                # so a stray late finalize can't embed a stale zone.
                try:
                    self._hide_zone()
                except Exception:
                    pass
                print("[klausmate] pdf drag: armed (no activity)")
        elif state == "armed":
            if moved:
                # User resumed the gesture (button still down as far as
                # Qt knows).
                self._drag_state = (
                    "manual_follow"
                    if self._native_move_ok is False
                    else "native"
                )
            elif now - self._last_activity > 10.0:
                self._finalize_drag(False, "armed 10s cap")

    def _reset_drag(self) -> None:
        """Tear down all drag machinery and return to idle."""
        try:
            if self._drag_timer.isActive():
                self._drag_timer.stop()
        except Exception:
            pass
        if self._app_filter_installed:
            try:
                app = QApplication.instance()
                if app is not None:
                    app.removeEventFilter(self)
            except Exception:
                pass
            self._app_filter_installed = False
        self._hide_zone()
        self._destroy_ghost()
        self._press_gp = None
        self._move_seen = False
        self._last_cursor = None
        self._drag_origin_pos = None
        self._drag_start_cursor = None
        self._drag_state = "idle"
        try:
            self._header.setCursor(Qt.CursorShape.OpenHandCursor)
        except Exception:
            pass

    def _finalize_drag(self, allow_embed: bool, why: str) -> None:
        """Common end for native/cursor-follow drags: tear the machinery
        down, then dock into the active zone or stay floating in place.

        Embeds are additionally gated on freshness (<2s since the last
        DIRECT drag evidence — a panel moveEvent during the gesture or
        a mouse event with the left button held; raw cursor motion is
        deliberately not enough, it keeps flowing after an unobserved
        release): the staleness tiers can fire long after the user
        actually let go, and a surprise late dock is worse than staying
        floating. Esc-to-cancel was considered and dropped — key events
        are unobservable while macOS runs a system move, so a cancel
        gesture cannot be detected reliably."""
        zone = self._active_zone
        fresh = (time.time() - self._last_drag_evidence) < 2.0
        self._reset_drag()
        print(
            f"[klausmate] pdf drag: finalize via {why} "
            f"(zone={zone}, fresh={fresh}, embed_ok={allow_embed})"
        )
        if allow_embed and zone is not None and fresh:
            self._embed(zone)
        else:
            self._persist_state()

    def _tear_off(self, gp: QPoint) -> None:
        w = max(480, self.width() or 480)
        h = max(400, self.height() or 400)
        self._drag_off = QPoint(w // 2, 15)
        self._make_floating(QRect(gp - self._drag_off, QSize(w, h)))

    def _drag_ghost_to(self, gp: QPoint) -> None:
        """Show/move the translucent drag preview under the cursor.
        FALLBACK ONLY: used when native window moves are proven broken
        (``_native_move_ok is False``) and the panel is still embedded —
        reparenting mid-gesture would kill Cocoa's mouse tracking, so
        the ghost stands in and the panel relocates on release."""
        g = self._ghost
        if g is None:
            pm = self.grab()
            if pm.width() > 420:
                pm = pm.scaledToWidth(
                    420, Qt.TransformationMode.SmoothTransformation
                )
            g = QLabel(self._win)
            g.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            g.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            g.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            g.setPixmap(pm)
            g.resize(pm.size())
            g.setWindowOpacity(0.55)
            self._ghost = g
        g.move(gp - QPoint(g.width() // 2, 12))
        if not g.isVisible():
            g.show()
            g.raise_()

    def _destroy_ghost(self) -> None:
        if self._ghost is not None:
            try:
                self._ghost.hide()
                self._ghost.deleteLater()
            except Exception:
                pass
            self._ghost = None

    _ZONE_CAPTIONS = {
        "above": "⬆  Dock above",
        "below": "⬇  Dock below",
        "left": "⬅  Dock left",
        "right": "➡  Dock right",
    }

    def _update_zone(self, gp: QPoint) -> None:
        """Track which dock zone (if any) the cursor is over and preview
        it. Detection: generous 40% bands along each edge of the editor
        pane; the central 20%×20% — and anywhere outside the pane — is
        an easy "stay floating". In a corner the proportionally nearer
        edge wins. The preview shows the TRUE post-drop layout: the 45%
        band _embed() will actually allocate."""
        zone: str | None = None
        ed_w = getattr(self._editor, "widget", None)
        if ed_w is not None and ed_w.isVisible():
            r = QRect(ed_w.mapToGlobal(QPoint(0, 0)), ed_w.size())
            if r.contains(gp):
                w, h = max(1, r.width()), max(1, r.height())
                rel_x = gp.x() - r.left()
                rel_y = gp.y() - r.top()
                in_v = rel_y <= h * 0.4 or rel_y >= h * 0.6
                in_h = rel_x <= w * 0.4 or rel_x >= w * 0.6
                # In a corner, pick the edge the cursor is proportionally
                # closest to.
                dy = min(rel_y, h - rel_y) / h
                dx = min(rel_x, w - rel_x) / w
                if in_v and (not in_h or dy <= dx):
                    zone = "above" if rel_y <= h * 0.4 else "below"
                elif in_h:
                    zone = "left" if rel_x <= w * 0.4 else "right"
        if zone == self._active_zone:
            return
        self._active_zone = zone
        if zone is None:
            if self._zone_overlay is not None:
                self._zone_overlay.hide()
            return
        try:
            self._show_zone_overlay(zone, ed_w)
        except Exception:
            pass

    def _show_zone_overlay(self, zone: str, ed_w: QWidget) -> None:
        """Place the drop-zone preview. The overlay is ONE reusable
        TOP-LEVEL window, not a child of the editor pane — during a
        native drag the panel itself is a window floating over the
        editor, and a child overlay would be covered by it."""
        ov = self._zone_overlay
        if ov is None:
            ov = QWidget(None)
            ov.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowTransparentForInput
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
            ov.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            ov.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            lab = QLabel(ov)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setStyleSheet(
                "background: rgba(58, 130, 247, 0.30);"
                "border: 2px solid rgba(58, 130, 247, 0.85);"
                "border-radius: 10px;"
                "color: white; font-size: 20px; font-weight: 600;"
            )
            box = QVBoxLayout(ov)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(lab)
            ov._klaus_zone_label = lab  # type: ignore[attr-defined]
            self._zone_overlay = ov
        try:
            ov._klaus_zone_label.setText(
                self._ZONE_CAPTIONS.get(zone, zone)
            )
        except Exception:
            pass
        origin = ed_w.mapToGlobal(QPoint(0, 0))
        ew, eh = ed_w.width(), ed_w.height()
        if zone in ("above", "below"):
            band = max(60, int(eh * 0.45))
            geo = QRect(
                origin.x(),
                origin.y() if zone == "above" else origin.y() + eh - band,
                ew,
                band,
            )
        else:
            band = max(60, int(ew * 0.45))
            geo = QRect(
                origin.x() if zone == "left" else origin.x() + ew - band,
                origin.y(),
                band,
                eh,
            )
        ov.setGeometry(geo)
        ov.show()
        ov.raise_()

    def _hide_zone(self) -> None:
        self._active_zone = None
        if self._zone_overlay is not None:
            self._zone_overlay.hide()

    # ---- per-tab ✕ ----

    def _decorate_tab(self, idx: int) -> None:
        btn = QToolButton(self._tabs)
        btn.setText("✕")
        btn.setAutoRaise(True)
        btn.setFixedSize(16, 16)
        btn.setStyleSheet("font-size: 10px; border: none;")
        btn.setToolTip("Close this PDF (keeps the stored file)")
        btn.clicked.connect(lambda _=False, b=btn: self._close_tab_of(b))
        self._tabs.setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)

    def _close_tab_of(self, btn: QToolButton) -> None:
        for i in range(self._tabs.count()):
            if self._tabs.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self._on_tab_close(i)
                return

    # ---- tab bookkeeping ----

    def _tab_names(self) -> list[str]:
        return [self._tabs.tabText(i) for i in range(self._tabs.count())]

    def _find_tab(self, name: str) -> int:
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == name:
                return i
        return -1

    def _persist(self) -> None:
        try:
            pdf_handler.save_open_tabs(USER_FILES, self._tab_names())
        except Exception:
            pass

    def _set_active_pointer(self, name: str) -> None:
        try:
            pdf_handler.set_active_pdf(USER_FILES, name)
        except Exception:
            pass
        try:
            # Recency signal for the ＋ menu's most-recent-first ordering.
            pdf_handler.touch_last_used(USER_FILES, name)
        except Exception:
            pass
        panel = getattr(self._editor, "_klausmate_panel", None)
        if panel is not None:
            try:
                panel._refresh_pdf_status()
            except Exception:
                pass

    def _on_sidebar_loaded(self, name: str) -> None:
        """Sidebar loaded a PDF (from any call site): make sure a tab
        exists for it and is selected, without re-triggering a load."""
        if not name:
            return
        self._last_page.setdefault(name, 0)
        self._syncing = True
        try:
            idx = self._find_tab(name)
            if idx < 0:
                idx = self._tabs.addTab(name)
                self._decorate_tab(idx)
            if self._tabs.currentIndex() != idx:
                self._tabs.setCurrentIndex(idx)
        finally:
            self._syncing = False
        self._persist()
        self._set_active_pointer(name)

    def _on_tab_changed(self, idx: int) -> None:
        if self._syncing or idx < 0:
            return
        name = self._tabs.tabText(idx)
        if not name:
            return
        prev = getattr(self._sidebar, "_name", None)
        if prev and prev != name:
            self._last_page[prev] = getattr(
                self._sidebar, "_current_page", 0
            )
        if self._sidebar.is_loaded(name):
            self._set_active_pointer(name)
            return
        self._sidebar.load_pdf(name)
        page = self._last_page.get(name, 0)
        if page > 0:
            # One tick so QPdfView finishes laying out the new document
            # before we jump back to the remembered position.
            QTimer.singleShot(
                0, lambda: self._sidebar.jump_to_page(page)
            )

    def _on_tab_close(self, idx: int) -> None:
        name = self._tabs.tabText(idx)
        # Removing the current tab makes QTabBar select a neighbour, which
        # fires currentChanged and loads that PDF into the viewer.
        self._tabs.removeTab(idx)
        self._last_page.pop(name, None)
        self._persist()
        if self._tabs.count() == 0:
            try:
                self._sidebar.clear()
            except Exception:
                pass
            try:
                pdf_handler.clear_active_pdf(USER_FILES)
            except Exception:
                pass
            panel = getattr(self._editor, "_klausmate_panel", None)
            if panel is not None:
                try:
                    panel._refresh_pdf_status()
                except Exception:
                    pass
            self.panel_hide()

    def close_tab(self, name: str) -> None:
        idx = self._find_tab(name)
        if idx >= 0:
            self._on_tab_close(idx)

    # ---- ＋ menu / placement ----

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        open_names = set(self._tab_names())
        stored: list[str] = []
        for n in pdf_handler.list_contexts(USER_FILES):
            base = n[:-4] if n.endswith(".txt") else n
            if base in open_names:
                continue
            if pdf_handler.pdf_path_for(USER_FILES, base):
                stored.append(base)
        # Most recently used first; PDFs never activated fall back to
        # their file mtime (ingest time), oldest last.
        try:
            last_used = pdf_handler.load_last_used(USER_FILES)
        except Exception:
            last_used = {}

        def _recency(base: str) -> float:
            ts = last_used.get(base)
            if ts is not None:
                return ts
            try:
                p = pdf_handler.pdf_path_for(USER_FILES, base)
                return os.path.getmtime(p) if p else 0.0
            except Exception:
                return 0.0

        for base in sorted(stored, key=_recency, reverse=True):
            act = menu.addAction(base)
            act.triggered.connect(
                lambda _=False, b=base: self._sidebar.load_pdf(b)
            )
        if stored:
            menu.addSeparator()
        open_act = menu.addAction("Browse…")
        open_act.triggered.connect(self._browse_new)
        menu.exec(
            self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft())
        )

    def _browse_new(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF", "", "PDF files (*.pdf)"
        )
        if not path:
            return
        panel = getattr(self._editor, "_klausmate_panel", None)
        if panel is not None:
            panel._handle_pdf(path)


def on_editor_did_init(editor: Editor) -> None:
    """Attach the Klaus panel below the tags bar, plus the tabbed PDF
    viewer panel (``_PdfTabContainer``) that docks above/below the editor
    pane or floats as its own window. The panel starts hidden and is
    toggled via the Klaus bar's button, or auto-shown when the user adds
    or opens a PDF.
    """
    try:
        widget = editor.widget
        if widget is None:
            return
        layout = widget.layout()
        if layout is None:
            return
        pdf_handler.ensure_active_pdf(USER_FILES)
        if getattr(editor, "_klausmate_panel", None) is None:
            panel = _KlausmatePanel(editor, parent=widget)
            layout.addWidget(panel)
            editor._klausmate_panel = panel  # type: ignore[attr-defined]
        if not hasattr(editor, "_klausmate_target_field_index"):
            editor._klausmate_target_field_index = None  # type: ignore[attr-defined]
        # Default state for the page-aware retrieval helper.
        if not hasattr(editor, "_klausmate_active_pdf"):
            editor._klausmate_active_pdf = None  # type: ignore[attr-defined]
        # The viewer panel needs a top-level Anki window to float against
        # and an editor pane to dock around. Both the Add window and the
        # Browser qualify; the Browser's standalone edit-current window
        # does too (any QWidget window works — no dock APIs involved).
        parent_window = getattr(editor, "parentWindow", None)
        if parent_window is None:
            return
        if getattr(editor, "_klausmate_pdf_tabs", None) is not None:
            return

        def _install_panel() -> None:
            # Deferred by one event-loop tick so the window's layout is
            # fully constructed before we wrap the editor pane.
            try:
                if getattr(editor, "_klausmate_pdf_tabs", None) is not None:
                    return
                from . import pdf_viewer as _pdf_viewer

                # Reuse a panel this window already has (editor re-init).
                existing = getattr(
                    parent_window, "_klausmate_pdf_container", None
                )
                if isinstance(existing, _PdfTabContainer):
                    sidebar = existing._sidebar
                    editor._klausmate_pdf_tabs = existing  # type: ignore[attr-defined]
                    editor._klausmate_sidebar = sidebar  # type: ignore[attr-defined]
                    existing._editor = editor
                    sidebar._editor = editor
                    active = pdf_handler.get_active_pdf(USER_FILES)
                    if active:
                        sidebar.load_pdf(active)
                    panel = getattr(editor, "_klausmate_panel", None)
                    if panel is not None:
                        panel._update_toggle_label(existing.isVisible())
                    return

                sidebar = _pdf_viewer.PdfSidebar(editor, parent=None)
                container = _PdfTabContainer(editor, sidebar, parent_window)
                container.hide()  # placed + shown on first toggle/chip
                editor._klausmate_pdf_tabs = container  # type: ignore[attr-defined]
                editor._klausmate_sidebar = sidebar  # type: ignore[attr-defined]
                parent_window._klausmate_pdf_container = container

                panel = getattr(editor, "_klausmate_panel", None)
                if panel is not None:
                    panel._update_toggle_label(False)

                active = pdf_handler.get_active_pdf(USER_FILES)
                if active:
                    sidebar.load_pdf(active)
            except Exception as e:
                print(
                    "[klausmate] PDF panel install failed: "
                    f"{type(e).__name__}: {e}"
                )
                traceback.print_exc()

        QTimer.singleShot(0, _install_panel)
    except Exception as e:
        print(f"[klausmate] editor_did_init failed: {type(e).__name__}: {e}")
        traceback.print_exc()


# ----------------------------- bootstrap ----------------------------------

mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
mw.addonManager.setConfigAction(__name__, open_config)


def _shutdown_managed_server() -> None:
    """Stop an `ollama serve` we spawned/adopted. A reused user-owned
    Ollama is never touched (ServerManager enforces that)."""
    try:
        server_manager.stop()
    except Exception as e:
        print(f"[klausmate] managed server shutdown failed: {e}")


# aboutToQuit (not profile_will_close — that fires on profile *switches*
# and the server must survive those) plus atexit as a crash-adjacent backup.
if getattr(mw, "app", None) is not None:
    mw.app.aboutToQuit.connect(_shutdown_managed_server)
atexit.register(_shutdown_managed_server)


# --------------------------- klaus panel glue -----------------------------


def _chat_dock_loaded() -> bool:
    import sys as _sys

    return f"{__name__}.chat_dock" in _sys.modules


def _chat_profile_close() -> None:
    if not _chat_dock_loaded():
        return
    try:
        from . import chat_dock

        chat_dock.on_profile_will_close()
    except Exception as e:
        print(f"[klausmate] chat profile-close failed: {e}")


def _chat_quit() -> None:
    if not _chat_dock_loaded():
        return
    try:
        from . import chat_dock

        chat_dock.on_quit()
    except Exception as e:
        print(f"[klausmate] chat quit failed: {e}")


gui_hooks.profile_will_close.append(_chat_profile_close)
if getattr(mw, "app", None) is not None:
    mw.app.aboutToQuit.connect(_chat_quit)

# Native top-right tray slot (next to sync); older Anki falls back to the
# centered link row — same hook signature either way.
if hasattr(gui_hooks, "top_toolbar_will_set_right_tray_content"):
    gui_hooks.top_toolbar_will_set_right_tray_content.append(
        on_top_toolbar_right_tray
    )
else:
    gui_hooks.top_toolbar_did_init_links.append(on_top_toolbar_right_tray)

gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
gui_hooks.webview_did_receive_js_message.append(on_js_message)
gui_hooks.editor_will_munge_html.append(strip_ghost_html)
gui_hooks.editor_will_show_context_menu.append(on_editor_context_menu)
gui_hooks.main_window_did_init.append(install_menu)
gui_hooks.main_window_did_init.append(install_preferences)
from . import curation as _curation

_curation.setup_hooks()

gui_hooks.profile_did_open.append(_migrate_config)
gui_hooks.profile_did_open.append(first_run_check)
gui_hooks.profile_did_open.append(setup_readiness_check)
gui_hooks.editor_did_init.append(on_editor_did_init)
if hasattr(gui_hooks, "browser_will_show"):
    gui_hooks.browser_will_show.append(on_browser_will_show)

# Deck-screen curation and the PDF drive install independently — a failure
# in one must not cost the user the other (or the editor features above).
try:
    from . import deck_curate as _deck_curate

    _deck_curate.setup()
except Exception as _e:
    print(f"[klausmate] deck curate setup failed: {type(_e).__name__}: {_e}")

try:
    from . import pdf_drive as _pdf_drive

    _pdf_drive.setup()
except Exception as _e:
    print(f"[klausmate] pdf drive setup failed: {type(_e).__name__}: {_e}")


# NOTE: no editor_did_focus_field hook here. That hook's signature is
# (note: Note, current_field_idx: int) — it does not provide the Editor,
# so it can't drive _set_target_field reliably. Target-field tracking is
# handled by the JS bridge instead: copilot.js sends "klausmate:focus"
# with the field name, and on_js_message receives the owning Editor as
# its context.
