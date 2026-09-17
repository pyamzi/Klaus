"""Anki collection tools (search/read/create/update notes, stats, PDFs).

The tool layer both assistants call: the query assistant reads through
``search_notes`` / ``get_note`` / ``search_lecture_pdfs``, and the card
assistant writes through ``create_note`` / ``update_note`` and the batch
``add_reviewed_cards``.

Restored from the deletion in K-032 (`30847b9^`), which took it out when the
agentic chat went. One thing had rotted in the meantime:
``search_lecture_pdfs`` called ``pdf_handler.retrieve_relevant_chunks``, the
BM25 retrieval that left with autocomplete and Ask. It is semantic now,
which is also what the rest of the add-on means by "search".

Design for testability: every handler is ``handler(col, args, ctx)`` with
a duck-typed ``col`` and a ctx dict of injected capabilities, so the whole
registry runs against a stub collection outside Anki. ``execute_tool`` is
the only aqt-coupled entry point: it marshals the handler (including the
write-confirmation dialog) onto the Qt main thread and waits.

Write tools never touch the collection without the user approving a
plain-text preview dialog (plain text so note-field HTML can't spoof it).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
import time
from typing import Any, Callable

_ADDON_DIR = os.path.dirname(__file__)
_USER_FILES = os.path.join(_ADDON_DIR, "user_files")

MAX_RESULT_BYTES = 25_000
MAX_FIELD_CHARS = 4_000
MAX_PREVIEW_CHARS = 200
MAX_CHUNK_CHARS = 2_000
_CONFIRM_FIELD_CHARS = 500

WRITE_TOOLS = {"create_note", "update_note"}

# Timeouts for main-thread marshalling: writes include a human staring at
# a dialog, so they get 10 minutes; reads should be instant.
READ_TIMEOUT_S = 30.0
WRITE_TIMEOUT_S = 600.0


class ToolError(Exception):
    """User/model-facing tool failure — message is relayed to the agent."""


TOOL_SPECS: list[dict] = [
    {
        "name": "search_notes",
        "description": (
            "Search the user's Anki notes. Query uses Anki search syntax, "
            "e.g. 'deck:Pharm tag:exam heart failure'. Returns matching "
            "note ids with a short preview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Anki search syntax query",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_note",
        "description": "Fetch one note's full fields, tags, and decks by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"note_id": {"type": "integer"}},
            "required": ["note_id"],
        },
    },
    {
        "name": "get_deck_overview",
        "description": "List the user's decks with new/learn/due counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_review_stats",
        "description": "Review activity for the last N days (counts, minutes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 7,
                }
            },
        },
    },
    {
        "name": "search_lecture_pdfs",
        "description": (
            "Semantic search over the user's imported lecture PDFs: "
            "returns the best-matching page from each indexed PDF, with "
            "its text and source. Ask in plain language."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 4,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_note",
        "description": (
            "Create a new Anki note. The user sees a preview and must "
            "approve before anything is saved. Fields is a map of field "
            "name to value for the chosen note type."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "deck": {"type": "string"},
                "note_type": {"type": "string"},
                "fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
            },
            "required": ["deck", "note_type", "fields"],
        },
    },
    {
        "name": "update_note",
        "description": (
            "Update fields and/or tags of an existing note. The user sees "
            "an old→new preview and must approve before anything is saved."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer"},
                "fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["note_id"],
        },
    },
]


# ------------------------------------------------------------------ utils


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html_fallback(s: str) -> str:
    return _TAG_RE.sub("", s).replace("&nbsp;", " ").strip()


def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "…[truncated]"


def default_ctx() -> dict:
    """Capabilities for real-Anki execution (built lazily; aqt import)."""
    try:
        from anki.utils import strip_html as _sh
    except Exception:
        _sh = _strip_html_fallback
    return {
        "strip": _sh,
        "confirm": _confirm_write_dialog,
        "user_files": _USER_FILES,
        # Injected rather than imported by the handler, so the tool stays
        # runnable against a stub with no embedding provider and no network.
        "search_pdfs": _semantic_pdf_search,
    }


def _semantic_pdf_search(query: str, top_k: int, user_files: str) -> list[dict]:
    """Best-matching PAGE from each indexed lecture PDF, ranked.

    Replaces the BM25 retrieval this tool was written against. One query
    embedding is scored against every fresh per-PDF index via
    ``pdf_index.best_page``; a PDF whose index is stale or built on a
    different embedding signature is SKIPPED rather than scored, because a
    score from another embedding space is not a smaller number, it is a
    meaningless one. The hit's text is that page's ``page_store`` record —
    slide text plus any transcript said over it — falling back to the bare
    slide text when there is no record, or no PDF file to key one on.
    """
    from . import embeddings, page_store, pdf_handler, pdf_index

    pkg = __import__(__package__, fromlist=["get_config"])
    cfg = pkg.get_config() or {}
    provider = embeddings.provider_from_config(lambda: cfg)
    raw = provider.embed([query], kind="query")
    vec = embeddings.normalize(raw[0]) if raw else None
    if vec is None:
        return []
    sig = embeddings.index_signature(cfg)

    hits: list = []
    for fname in pdf_handler.list_contexts(user_files):
        name = fname[:-4] if fname.endswith(".txt") else fname
        try:
            idx = pdf_index.load(pdf_index.index_dir(user_files, name))
            src = pdf_index.source_signature(user_files, name)
            if not pdf_index.is_fresh(idx, src, sig):
                continue
            page, score = pdf_index.best_page(idx, vec)
            if page < 1 or score <= 0:
                continue
            text = ""
            safe = pdf_handler._safe_basename(name)
            path = pdf_handler.pdf_path_for(user_files, safe)
            if path:
                rec = page_store.load_record(user_files, safe, path, page - 1)
                text = page_store.combined_text(rec)
            if not text:
                pages = pdf_handler.load_pages(user_files, name) or []
                if 0 <= page - 1 < len(pages):
                    text = pages[page - 1]
            hits.append({
                "source": name,
                "page": page,
                "text": text,
                "score": float(score),
            })
        except Exception:
            # One unreadable PDF must not take the whole search with it.
            continue
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[: max(1, int(top_k))]


# --------------------------------------------------------------- handlers


def _h_search_notes(col: Any, args: dict, ctx: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query is required")
    limit = _clamp(args.get("limit"), 1, 50, 20)
    try:
        ids = list(col.find_notes(query))
    except Exception as e:
        raise ToolError(f"Invalid Anki search query: {e}") from e
    strip = ctx["strip"]
    notes = []
    for nid in ids[:limit]:
        try:
            n = col.get_note(nid)
        except Exception:
            continue
        first = strip(str(n.fields[0])) if getattr(n, "fields", None) else ""
        notes.append(
            {
                "note_id": int(nid),
                "note_type": str(n.note_type()["name"]),
                "preview": first[:MAX_PREVIEW_CHARS],
                "tags": list(n.tags),
            }
        )
    return {"total_matches": len(ids), "returned": len(notes), "notes": notes}


def _h_get_note(col: Any, args: dict, ctx: dict) -> dict:
    nid = int(args.get("note_id") or 0)
    try:
        n = col.get_note(nid)
    except Exception as e:
        raise ToolError(f"Note {nid} not found: {e}") from e
    fields = {name: _truncate(str(val), MAX_FIELD_CHARS) for name, val in n.items()}
    cards = list(n.cards())
    decks = sorted({str(col.decks.name(c.did)) for c in cards})
    return {
        "note_id": nid,
        "note_type": str(n.note_type()["name"]),
        "decks": decks,
        "tags": list(n.tags),
        "fields": fields,
        "card_count": len(cards),
    }


def _h_get_deck_overview(col: Any, args: dict, ctx: dict) -> dict:
    tree = col.sched.deck_due_tree()
    decks: list[dict] = []

    def walk(node: Any, prefix: str) -> None:
        for child in getattr(node, "children", []) or []:
            name = f"{prefix}::{child.name}" if prefix else str(child.name)
            decks.append(
                {
                    "name": name,
                    "new": int(child.new_count),
                    "learn": int(child.learn_count),
                    "due": int(child.review_count),
                }
            )
            walk(child, name)

    walk(tree, "")
    out: dict = {"decks": decks[:200]}
    if len(decks) > 200:
        out["truncated"] = True
    try:
        out["total_notes"] = int(col.note_count())
    except Exception:
        pass
    return out


def _h_get_review_stats(col: Any, args: dict, ctx: dict) -> dict:
    days = _clamp(args.get("days"), 1, 365, 7)
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    rows = col.db.all(
        "select id, time from revlog where id > ?", cutoff_ms
    )
    per_day: dict[str, dict] = {}
    total_ms = 0
    for rid, took_ms in rows:
        day = _dt.datetime.fromtimestamp(rid / 1000).date().isoformat()
        entry = per_day.setdefault(day, {"date": day, "reviews": 0, "ms": 0})
        entry["reviews"] += 1
        entry["ms"] += int(took_ms or 0)
        total_ms += int(took_ms or 0)
    days_out = [
        {
            "date": d["date"],
            "reviews": d["reviews"],
            "minutes": round(d["ms"] / 60000, 1),
        }
        for d in sorted(per_day.values(), key=lambda x: x["date"])
    ]
    return {
        "days": days,
        "total_reviews": len(rows),
        "total_time_minutes": round(total_ms / 60000, 1),
        "per_day": days_out,
    }


def _h_search_lecture_pdfs(col: Any, args: dict, ctx: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query is required")
    top_k = _clamp(args.get("top_k"), 1, 10, 4)
    search = ctx.get("search_pdfs")
    if search is None:
        raise ToolError("PDF search is not available in this context")
    try:
        chunks = search(query, top_k, ctx.get("user_files", _USER_FILES))
    except Exception as e:
        raise ToolError(f"PDF search unavailable: {e}") from e
    return {
        "chunks": [
            {
                "source": str(c.get("source") or "?"),
                "page": int(c.get("page") or 0),
                "text": _truncate(str(c.get("text") or ""), MAX_CHUNK_CHARS),
                "score": round(float(c.get("score") or 0), 2),
            }
            for c in chunks
        ]
    }


def _h_create_note(col: Any, args: dict, ctx: dict) -> dict:
    deck_name = str(args.get("deck") or "").strip()
    nt_name = str(args.get("note_type") or "").strip()
    fields = args.get("fields") or {}
    tags = [str(t) for t in (args.get("tags") or [])]
    if not deck_name or not nt_name or not isinstance(fields, dict) or not fields:
        raise ToolError("deck, note_type, and a non-empty fields map are required")

    model = col.models.by_name(nt_name)
    if model is None:
        names = ", ".join(sorted(str(m) for m in col.models.all_names()))
        raise ToolError(f"Note type '{nt_name}' not found. Available: {names}")
    deck = col.decks.by_name(deck_name)
    if deck is None:
        names = ", ".join(sorted(d.name for d in col.decks.all_names_and_ids()))
        raise ToolError(f"Deck '{deck_name}' not found. Available: {names}")

    valid = [f["name"] for f in model["flds"]]
    unknown = [k for k in fields if k not in valid]
    if unknown:
        raise ToolError(
            f"Unknown field(s) {unknown} for note type '{nt_name}'. "
            f"Valid fields: {valid}"
        )

    sections = [
        ("Deck", deck_name),
        ("Type", nt_name),
        ("Tags", ", ".join(tags) or "(none)"),
    ] + [
        (name, _truncate(str(fields[name]), _CONFIRM_FIELD_CHARS))
        for name in valid
        if name in fields
    ]
    if not ctx["confirm"]("Klaus wants to create a note", sections):
        raise ToolError("User declined the create_note action")

    note = col.new_note(model)
    for k, v in fields.items():
        note[k] = str(v)
    note.tags = tags
    col.add_note(note, deck["id"])
    return {"note_id": int(note.id), "cards_created": len(list(note.cards()))}


def _h_update_note(col: Any, args: dict, ctx: dict) -> dict:
    nid = int(args.get("note_id") or 0)
    fields = args.get("fields") or {}
    tags = args.get("tags")
    if not fields and tags is None:
        raise ToolError("Provide fields and/or tags to update")
    try:
        note = col.get_note(nid)
    except Exception as e:
        raise ToolError(f"Note {nid} not found: {e}") from e

    valid = list(dict(note.items()).keys())
    unknown = [k for k in fields if k not in valid]
    if unknown:
        raise ToolError(f"Unknown field(s) {unknown}. Valid fields: {valid}")

    changed = {
        k: v for k, v in fields.items() if str(v) != str(dict(note.items())[k])
    }
    tags_new = [str(t) for t in tags] if tags is not None else None
    tags_changed = tags_new is not None and set(tags_new) != set(note.tags)
    if not changed and not tags_changed:
        return {"note_id": nid, "updated_fields": [], "tags_changed": False}

    sections: list[tuple[str, str]] = [("Note", str(nid))]
    current = dict(note.items())
    for k, v in changed.items():
        sections.append(
            (
                f"{k} (changed)",
                "OLD: "
                + _truncate(str(current[k]), _CONFIRM_FIELD_CHARS)
                + "\nNEW: "
                + _truncate(str(v), _CONFIRM_FIELD_CHARS),
            )
        )
    if tags_changed:
        sections.append(
            ("Tags", f"OLD: {', '.join(note.tags)}\nNEW: {', '.join(tags_new)}")
        )
    if not ctx["confirm"]("Klaus wants to update a note", sections):
        raise ToolError("User declined the update_note action")

    for k, v in changed.items():
        note[k] = str(v)
    if tags_changed:
        note.tags = tags_new
    col.update_note(note)
    return {
        "note_id": nid,
        "updated_fields": sorted(changed.keys()),
        "tags_changed": bool(tags_changed),
    }


_HANDLERS: dict[str, Callable[[Any, dict, dict], dict]] = {
    "search_notes": _h_search_notes,
    "get_note": _h_get_note,
    "get_deck_overview": _h_get_deck_overview,
    "get_review_stats": _h_get_review_stats,
    "search_lecture_pdfs": _h_search_lecture_pdfs,
    "create_note": _h_create_note,
    "update_note": _h_update_note,
}


# ------------------------------------------------------------ execution


def run_tool(col: Any, name: str, arguments: dict, ctx: dict) -> tuple[str, bool]:
    """Pure execution against a (possibly stub) collection.

    Returns ``(json_text, is_error)``. Never raises.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool: {name}"}), True
    try:
        result = handler(col, arguments or {}, ctx)
    except ToolError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False), True
    except Exception as e:  # never leak tracebacks to the model
        return json.dumps({"error": f"internal error: {type(e).__name__}"}), True
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
        # Drop trailing list items until it fits.
        for key in ("notes", "chunks", "per_day", "decks"):
            items = result.get(key)
            while isinstance(items, list) and items:
                items.pop()
                result["truncated"] = True
                text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                if len(text.encode("utf-8")) <= MAX_RESULT_BYTES:
                    return text, False
        text = text.encode("utf-8")[:MAX_RESULT_BYTES].decode("utf-8", "ignore")
    return text, False


def execute_tool(name: str, arguments: dict) -> tuple[str, bool]:
    """Real-Anki entry point — called from ToolServer's HTTP threads.

    Marshals the whole handler (including any confirmation dialog) onto
    the Qt main thread and blocks the calling worker until it finishes.
    Never call this ON the main thread — it would deadlock. The assistant
    runs its tool loop on a worker thread, which is what makes that safe.
    """
    timeout = WRITE_TIMEOUT_S if name in WRITE_TOOLS else READ_TIMEOUT_S

    def on_main() -> tuple[str, bool]:
        from aqt import mw

        if mw is None or mw.col is None:
            return (
                json.dumps(
                    {
                        "error": "Anki collection is not available right now "
                        "(syncing or profile closed) — try again shortly"
                    }
                ),
                True,
            )
        return run_tool(mw.col, name, arguments, default_ctx())

    try:
        return _run_on_main_sync(on_main, timeout)
    except TimeoutError:
        return (
            json.dumps({"error": f"Tool timed out after {int(timeout)}s"}),
            True,
        )
    except Exception as e:
        return json.dumps({"error": f"internal error: {type(e).__name__}"}), True


def _run_on_main_sync(fn: Callable[[], Any], timeout: float) -> Any:
    from aqt import mw

    box: dict[str, Any] = {}
    done = threading.Event()

    def wrapper() -> None:
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 — relayed to caller
            box["error"] = e
        finally:
            done.set()

    mw.taskman.run_on_main(wrapper)
    if not done.wait(timeout):
        raise TimeoutError
    if "error" in box:
        raise box["error"]
    return box["result"]


def add_reviewed_cards(
    col: Any,
    proposals: list,
    deck_name: str,
    notetype: str,
    front_field: str = "",
    back_field: str = "",
    tag: str = "!Library::Drafted",
) -> Any:
    """Write card_forge's ACCEPTED proposals as one undoable operation.

    Separate from ``create_note`` because the unit differs. create_note is
    one note the model asked for, approved one dialog at a time. This is a
    batch the user has already reviewed card by card, and it must undo as a
    batch: accepting twelve cards and then pressing Ctrl+Z eleven times to
    take them back is not an undo, it is a punishment.

    Follows curation.py's proven pattern — add_custom_undo_entry →
    add_notes → merge_undo_entries — rather than looping col.add_note,
    which would leave one undo entry per card.

    The caller passes proposals straight from ``ReviewQueue.to_write()``, so
    nothing unaccepted can arrive here. Provenance travels with the card as
    a tag, because a card whose source is only in a review UI that has since
    closed is a card you cannot audit later.
    """
    model = col.models.by_name(notetype)
    if model is None:
        raise ToolError(f"Note type '{notetype}' not found")
    deck = col.decks.by_name(deck_name)
    if deck is None:
        raise ToolError(f"Deck '{deck_name}' not found")
    names = [f["name"] for f in model["flds"]]
    if len(names) < 2:
        raise ToolError(f"Note type '{notetype}' has fewer than two fields")
    front = front_field or names[0]
    back = back_field or names[1]
    for field in (front, back):
        if field not in names:
            raise ToolError(f"Field '{field}' not in '{notetype}': {names}")

    from anki.collection import AddNoteRequest

    if not proposals:
        return None
    pos = col.add_custom_undo_entry(
        f"Klaus: add {len(proposals)} card"
        f"{'s' if len(proposals) != 1 else ''}"
    )
    did = col.decks.id(deck_name)
    requests = []
    for proposal in proposals:
        note = col.new_note(model)
        note[front] = str(proposal.front)
        note[back] = str(proposal.back)
        tags = [tag] if tag else []
        # 1-based in the tag: a human reads it against a page number in a
        # PDF viewer, not code.
        tags += [f"page::{int(p) + 1}" for p in proposal.pages]
        note.tags = tags
        # add_notes takes AddNoteRequest, never bare notes — the deck id
        # rides with each note rather than being passed alongside.
        requests.append(AddNoteRequest(note=note, deck_id=did))
    col.add_notes(requests)
    return col.merge_undo_entries(pos)


def _confirm_write_dialog(title: str, sections: list[tuple[str, str]]) -> bool:
    """Modal approval dialog. Main thread only (called via execute_tool).

    Plain-text QPlainTextEdit — note-field HTML renders inert, so the
    model can't dress a destructive change up as something harmless.
    """
    from aqt import mw
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QLabel,
        QPlainTextEdit,
        QVBoxLayout,
    )

    dlg = QDialog(mw)
    dlg.setWindowTitle("Klaus — approval needed")
    lay = QVBoxLayout(dlg)
    head = QLabel(title)
    head.setStyleSheet("font-weight: 600; font-size: 14px;")
    lay.addWidget(head)
    body = QPlainTextEdit()
    body.setReadOnly(True)
    body.setMinimumSize(460, 260)
    body.setPlainText(
        "\n".join(f"── {name} ──\n{value}" for name, value in sections)
    )
    lay.addWidget(body)
    btns = QDialogButtonBox()
    approve = btns.addButton("Approve", QDialogButtonBox.ButtonRole.AcceptRole)
    deny = btns.addButton("Deny", QDialogButtonBox.ButtonRole.RejectRole)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    deny.setDefault(True)
    approve.setAutoDefault(False)
    lay.addWidget(btns)
    return dlg.exec() == QDialog.DialogCode.Accepted
