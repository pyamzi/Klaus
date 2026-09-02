"""Klaus's own AnkiConnect-compatible endpoint, plus MCP over HTTP (Task 4).

Serves AnkiConnect's ``{action, version, params}`` protocol on ``/`` for the
ecosystem and the same actions as MCP tools on ``/mcp`` for the Claude Code
child, from ONE registry (``ACTIONS``) so the two routes cannot drift. Bound
to 127.0.0.1 on an ephemeral port with a per-start token, because a
localhost server is reachable by any local process and any browser page.

Writes never touch the collection without the user approving a PLAIN-TEXT
preview; the dialog is window-modal ``open()`` (K-114), never ``exec()``,
and the HTTP thread waits on an Event for the answer.

aqt-free above the divider: the server, the gate, the registry and every
action run against a duck-typed collection and an injected approver.
"""

from __future__ import annotations

import html
import json
import re
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

API_VERSION = 6
BODY_CAP = 4 * 1024 * 1024
READ_TIMEOUT_S = 30.0
APPROVAL_TIMEOUT_S = 120.0
TOKEN_HEADER = "X-Klaus-Token"
AGENT_HEADER = "X-Klaus-Agent"
AGENT_TAGS = ("klaus::assistant",)
_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: Any) -> str:
    return html.unescape(_TAG_RE.sub("", str(s or ""))).strip()


def _safe_int(v: Any, default: int = 0) -> int | None:
    """Best-effort int parse of caller-controlled HTTP input (a header value
    or a JSON field). Falsy input (missing header, absent/zero JSON field)
    maps to `default`, matching the pre-existing `int(x or 0)` behaviour;
    anything present but not a valid non-negative integer returns None so
    the caller answers with a clean error instead of letting a bare
    ValueError/TypeError escape onto the request thread — the same shape of
    bug the 413 drain-before-close fix already caught once in this file for
    a different caller-controlled number.
    """
    if not v:
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


@dataclass(frozen=True)
class Action:
    name: str
    mcp_name: str
    description: str
    schema: dict
    write: bool
    run: Callable[[Any, dict, dict], Any]


class ActionError(Exception):
    pass


# ---- actions -----------------------------------------------------------------

def _a_version(col, p, ctx):
    return API_VERSION

def _a_deck_names(col, p, ctx):
    return [d.name for d in col.decks.all_names_and_ids()]

def _a_deck_names_ids(col, p, ctx):
    return {d.name: d.id for d in col.decks.all_names_and_ids()}

def _a_model_names(col, p, ctx):
    return [m.name for m in col.models.all_names_and_ids()]

def _a_model_field_names(col, p, ctx):
    m = col.models.by_name(str(p.get("modelName") or ""))
    if not m:
        raise ActionError("model not found")
    return [f["name"] for f in m["flds"]]

def _a_find_notes(col, p, ctx):
    return [int(n) for n in col.find_notes(str(p.get("query") or ""))]

def _a_notes_info(col, p, ctx):
    out = []
    for nid in p.get("notes") or []:
        try:
            n = col.get_note(int(nid))
        except Exception:
            continue
        nt = n.note_type() if callable(getattr(n, "note_type", None)) else {}
        names = [f["name"] for f in (nt or {}).get("flds", [])] or list(getattr(n, "keys", lambda: [])())
        fields = {name: {"value": n[name], "order": i} for i, name in enumerate(names)}
        out.append({"noteId": int(nid), "modelName": (nt or {}).get("name", ""), "tags": list(getattr(n, "tags", [])),
                    "fields": fields, "cards": [int(c) for c in (n.card_ids() if callable(getattr(n, "card_ids", None)) else [])]})
    return out

def _a_find_cards(col, p, ctx):
    return [int(c) for c in col.find_cards(str(p.get("query") or ""))]

def _a_cards_info(col, p, ctx):
    out = []
    for cid in p.get("cards") or []:
        try:
            c = col.get_card(int(cid))
        except Exception:
            continue
        out.append({"cardId": int(cid), "noteId": int(c.nid), "deckName": col.decks.name(c.did), "queue": int(c.queue),
                    "interval": int(c.ivl), "due": int(c.due)})
    return out


def _tool_args(spec_name: str, mapping: dict) -> dict:
    """Translate AnkiConnect note params into whatever keys anki_tools' spec has."""
    from . import anki_tools
    props: dict = {}
    for s in anki_tools.TOOL_SPECS:
        if s.get("name") == spec_name:
            props = (s.get("inputSchema") or {}).get("properties") or {}
    out = {}
    for candidates, value in mapping.items():
        for k in candidates:
            if k in props:
                out[k] = value
                break
    return out


def _create_one(col, note: dict, ctx: dict, agent: bool) -> int:
    from . import anki_tools
    tags = list(note.get("tags") or [])
    if agent:
        page = (note.get("options") or {}).get("sourcePage")
        tags += list(AGENT_TAGS)
        if ctx.get("pdf_safe"):
            tags.append(f"klaus::from::{ctx['pdf_safe']}")
    args = _tool_args("create_note", {
        ("deck", "deck_name"): note.get("deckName"),
        ("notetype", "note_type", "model", "model_name"): note.get("modelName"),
        ("fields",): note.get("fields") or {},
        ("tags",): tags,
    })
    res = anki_tools._HANDLERS["create_note"](col, args, dict(ctx, confirm=lambda *a: True))
    for k in ("note_id", "noteId", "id"):
        if isinstance(res, dict) and k in res:
            return int(res[k])
    return int(res) if isinstance(res, int) else 0


def _a_add_note(col, p, ctx):
    return _create_one(col, p.get("note") or {}, ctx, bool(ctx.get("agent")))

def _a_add_notes(col, p, ctx):
    # Each note is tried on its own so one bad note (unknown deck/model/
    # field, raised as anki_tools.ToolError by the reused create_note
    # handler) cannot sink notes on either side of it — AnkiConnect's own
    # addNotes documents exactly this result shape, list[noteId or null],
    # never one error for the whole call.
    out = []
    for n in (p.get("notes") or []):
        try:
            out.append(_create_one(col, n, ctx, bool(ctx.get("agent"))))
        except Exception as exc:
            print(f"[klausmate] endpoint addNotes: {exc}")
            out.append(None)
    return out

def _a_update_note_fields(col, p, ctx):
    from . import anki_tools
    note = p.get("note") or {}
    args = _tool_args("update_note", {("note_id", "id"): int(note.get("id") or 0), ("fields",): note.get("fields") or {}})
    anki_tools._HANDLERS["update_note"](col, args, dict(ctx, confirm=lambda *a: True))
    return None

def _a_add_tags(col, p, ctx):
    col.tags.bulk_add([int(n) for n in p.get("notes") or []], str(p.get("tags") or ""))
    return None

def _a_remove_tags(col, p, ctx):
    col.tags.bulk_remove([int(n) for n in p.get("notes") or []], str(p.get("tags") or ""))
    return None

def _a_gui_browse(col, p, ctx):
    q = str(p.get("query") or "")
    opener = ctx.get("open_browse")
    if callable(opener):
        opener(q)
    return [int(n) for n in col.find_notes(q)]

def _a_klaus_search_notes(col, p, ctx):
    from . import anki_tools
    args = _tool_args("search_notes", {("query",): str(p.get("query") or ""), ("limit", "top_k", "k"): int(p.get("limit") or 20)})
    # anki_tools._h_search_notes returns {"total_matches", "returned", "notes"}
    # (its own callers want the counts); every consumer of THIS action —
    # the AnkiConnect pin (isinstance(result, list)) and the MCP tool table
    # in the design doc (`list[{noteId, score, snippet}]`) — wants the bare
    # list. Unwrap here rather than reshaping anki_tools' return, which
    # get_deck_overview/get_review_stats also share the module with.
    return anki_tools._HANDLERS["search_notes"](col, args, ctx).get("notes", [])

def _a_klaus_search_pdfs(col, p, ctx):
    from . import anki_tools
    args = _tool_args("search_lecture_pdfs", {("query",): str(p.get("query") or ""), ("limit", "top_k", "k"): int(p.get("limit") or 10)})
    # Same unwrap as _a_klaus_search_notes above: _h_search_lecture_pdfs
    # returns {"chunks": [...]}; this action's result is the list itself.
    return anki_tools._HANDLERS["search_lecture_pdfs"](col, args, ctx).get("chunks", [])

def _a_klaus_current_view(col, p, ctx):
    try:
        from . import viewer_context
    except Exception:
        return None
    v = viewer_context.current()
    if v is None:
        return None
    return {"pdf": v.pdf_safe, "display": v.display, "page": v.page_index + 1, "count": v.page_count, "selection": v.selection}


def _obj(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required)}

NOTE_SCHEMA = _obj({"deck": {"type": "string"}, "model": {"type": "string"}, "fields": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}}, "source_page": {"type": "integer", "minimum": 1}},
                   ("deck", "model", "fields", "source_page"))

ACTIONS: dict[str, Action] = {a.name: a for a in (
    Action("version", "", "API version", _obj({}), False, _a_version),
    Action("deckNames", "list_decks", "List the user's decks.", _obj({}), False, _a_deck_names),
    Action("deckNamesAndIds", "", "Decks with ids.", _obj({}), False, _a_deck_names_ids),
    Action("modelNames", "list_models", "List the user's note types.", _obj({}), False, _a_model_names),
    Action("modelFieldNames", "model_fields", "Field names of a note type.", _obj({"model": {"type": "string"}}, ("model",)), False, _a_model_field_names),
    Action("findNotes", "find_notes", "Note ids matching an Anki search.", _obj({"query": {"type": "string"}}, ("query",)), False, _a_find_notes),
    Action("notesInfo", "get_notes", "Fields, tags and cards of notes by id.", _obj({"note_ids": {"type": "array", "items": {"type": "integer"}}}, ("note_ids",)), False, _a_notes_info),
    Action("findCards", "", "Card ids matching an Anki search.", _obj({"query": {"type": "string"}}, ("query",)), False, _a_find_cards),
    Action("cardsInfo", "", "Card info by id.", _obj({"cards": {"type": "array"}}, ("cards",)), False, _a_cards_info),
    Action("addNote", "add_note", "Add ONE note; the user approves a preview. Requires source_page.", NOTE_SCHEMA, True, _a_add_note),
    Action("addNotes", "", "Add several notes behind one approval.", _obj({"notes": {"type": "array"}}, ("notes",)), True, _a_add_notes),
    Action("updateNoteFields", "update_note_fields", "Update fields of a note; approved by the user.", _obj({"note_id": {"type": "integer"}, "fields": {"type": "object"}}, ("note_id", "fields")), True, _a_update_note_fields),
    Action("addTags", "add_tags", "Add tags to notes; approved.", _obj({"note_ids": {"type": "array"}, "tags": {"type": "string"}}, ("note_ids", "tags")), True, _a_add_tags),
    Action("removeTags", "remove_tags", "Remove tags from notes; approved.", _obj({"note_ids": {"type": "array"}, "tags": {"type": "string"}}, ("note_ids", "tags")), True, _a_remove_tags),
    Action("guiBrowse", "open_in_browse", "Open Anki's Browse on a search.", _obj({"query": {"type": "string"}}, ("query",)), False, _a_gui_browse),
    Action("klausSearchNotes", "search_notes", "Semantic search over the user's notes.", _obj({"query": {"type": "string"}, "limit": {"type": "integer"}}, ("query",)), False, _a_klaus_search_notes),
    Action("klausSearchLecturePdfs", "search_lecture_pdfs", "Semantic search over the indexed lecture PDFs.", _obj({"query": {"type": "string"}, "limit": {"type": "integer"}}, ("query",)), False, _a_klaus_search_pdfs),
    Action("klausCurrentView", "current_view", "What the user is viewing right now.", _obj({}), False, _a_klaus_current_view),
)}

MCP_TO_ACTION = {a.mcp_name: a.name for a in ACTIONS.values() if a.mcp_name}


def mcp_args_to_params(action: str, args: dict) -> dict:
    """The MCP tools take flat, snake_case args; the actions take AnkiConnect params."""
    a = dict(args or {})
    if action in ("addNote",):
        return {"note": {"deckName": a.get("deck"), "modelName": a.get("model"), "fields": a.get("fields") or {},
                         "tags": a.get("tags") or [], "options": {"sourcePage": a.get("source_page")}}}
    if action == "updateNoteFields":
        return {"note": {"id": a.get("note_id"), "fields": a.get("fields") or {}}}
    if action in ("addTags", "removeTags"):
        return {"notes": a.get("note_ids") or [], "tags": a.get("tags") or ""}
    if action == "notesInfo":
        return {"notes": a.get("note_ids") or []}
    if action == "modelFieldNames":
        return {"modelName": a.get("model")}
    return a


# ---- MCP over HTTP (Task 4) ---------------------------------------------------

PROTOCOL_VERSION = "2025-06-18"

def mcp_tools() -> list[dict]:
    return [{"name": a.mcp_name, "description": a.description, "inputSchema": a.schema}
            for a in ACTIONS.values() if a.mcp_name]


def mcp_dispatch(end: "Endpoint", body: Any, session: str | None) -> tuple[int, Any, dict]:
    """One JSON-RPC message → (http status, json body or None, extra headers)."""
    if not isinstance(body, dict):
        return 200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}, {}
    rid = body.get("id")
    method = str(body.get("method") or "")
    params = body.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        # JSON-RPC 2.0 formally permits params to be an Array (by-position)
        # as well as an Object — legal-shaped input, not garbage — but every
        # branch below calls params.get(...), which assumes an Object.
        # Fix round 1 (review Important #1): this used to fall through to
        # do_POST's generic safety net as an uncaught AttributeError,
        # answering a non-JSON-RPC-shaped HTTP 500 instead of a clean,
        # spec-shaped error the caller can parse the same way as any other
        # JSON-RPC failure.
        return 200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "invalid params: expected an object"}}, {}
    if method == "notifications/initialized":
        return 202, None, {}
    if method == "initialize":
        sid = secrets.token_hex(8)
        end.sessions.add(sid)
        res = {"protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
               "capabilities": {"tools": {}}, "serverInfo": {"name": "klaus", "version": end.version}}
        return 200, {"jsonrpc": "2.0", "id": rid, "result": res}, {"Mcp-Session-Id": sid}
    if method == "ping":
        return 200, {"jsonrpc": "2.0", "id": rid, "result": {}}, {}
    if method == "tools/list":
        return 200, {"jsonrpc": "2.0", "id": rid, "result": {"tools": mcp_tools()}}, {}
    if method == "tools/call":
        name = str(params.get("name") or "")
        action = MCP_TO_ACTION.get(name)
        if action is None:
            out = {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
        else:
            r = end.handle(action, mcp_args_to_params(action, params.get("arguments") or {}), agent=True)
            if r.get("error"):
                out = {"content": [{"type": "text", "text": str(r["error"])}], "isError": True}
            else:
                out = {"content": [{"type": "text", "text": json.dumps(r.get("result"))}], "isError": False}
        return 200, {"jsonrpc": "2.0", "id": rid, "result": out}, {}
    return 200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}}, {}


# ---- previews ----------------------------------------------------------------

def similar_existing(col, front: str) -> str | None:
    words = strip_html(front).split()[:8]
    if not words:
        return None
    q = " ".join(re.sub(r"[^\w]", "", w) for w in words if re.sub(r"[^\w]", "", w))
    if not q:
        return None
    try:
        ids = list(col.find_notes(q))[:1]
        if not ids:
            return None
        n = col.get_note(int(ids[0]))
        names = list(getattr(n, "keys", lambda: [])())
        return strip_html(n[names[0]]) if names else str(ids[0])
    except Exception:
        return None


def _note_sections(note: dict, similar: str | None, agent: bool, pdf_safe: str | None = None) -> list[tuple[str, str]]:
    secs = [("Deck", str(note.get("deckName") or "")), ("Note type", str(note.get("modelName") or ""))]
    for k, v in (note.get("fields") or {}).items():
        secs.append((str(k), strip_html(v)))
    tags = list(note.get("tags") or []) + (list(AGENT_TAGS) if agent else [])
    if agent and pdf_safe:
        tags.append(f"klaus::from::{pdf_safe}")
    if tags:
        secs.append(("Tags", " ".join(tags)))
    page = (note.get("options") or {}).get("sourcePage")
    if page:
        secs.append(("Source page", str(page)))
    if similar:
        secs.append(("Similar existing note", similar))
    return secs


def preview_sections(action: str, params: dict, similar: str | list | None = None, agent: bool = False,
                      pdf_safe: str | None = None) -> list[tuple[str, str]]:
    if action == "addNote":
        return _note_sections(params.get("note") or {}, similar, agent, pdf_safe)
    if action == "addNotes":
        notes = params.get("notes") or []
        # `similar` is a per-note list here — Endpoint.handle looks one up
        # for EVERY note in the batch, not just the first, so a single
        # shared string would be wrong for every note but the first. A
        # plain string/None (as every direct caller other than
        # Endpoint.handle passes) falls back to "no similar note for
        # anyone" rather than raising.
        sims = similar if isinstance(similar, list) else [None] * len(notes)
        out: list[tuple[str, str]] = []
        for i, n in enumerate(notes, 1):
            out.append((f"Note {i}", ""))
            out += _note_sections(n, sims[i - 1] if i - 1 < len(sims) else None, agent, pdf_safe)
        return out
    if action == "updateNoteFields":
        note = params.get("note") or {}
        return [("Note id", str(note.get("id")))] + [(str(k), strip_html(v)) for k, v in (note.get("fields") or {}).items()]
    if action in ("addTags", "removeTags"):
        return [("Notes", ", ".join(str(n) for n in params.get("notes") or [])), ("Tags", str(params.get("tags") or ""))]
    return [(action, json.dumps(params)[:2000])]


# ---- the endpoint --------------------------------------------------------------

class Endpoint:
    def __init__(self, *, col_getter, run_on_main, approver, ctx_factory, version: str,
                 approval_timeout: float = APPROVAL_TIMEOUT_S, read_timeout: float = READ_TIMEOUT_S) -> None:
        self._col, self._main, self._approve, self._ctx = col_getter, run_on_main, approver, ctx_factory
        self.version = version
        self._approval_timeout, self._read_timeout = approval_timeout, read_timeout
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0
        self.token = ""
        self.sessions: set[str] = set()

    def start(self) -> tuple[str, int, str]:
        self.token = secrets.token_hex(32)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        srv.daemon_threads = True
        self._srv = srv
        self.port = srv.server_address[1]
        self._thread = threading.Thread(target=srv.serve_forever, name="klaus-endpoint", daemon=True)
        self._thread.start()
        return "127.0.0.1", self.port, self.token

    def stop(self) -> None:
        if self._srv is not None:
            try:
                self._srv.shutdown()
                self._srv.server_close()
            except Exception as exc:
                print(f"[klausmate] endpoint stop: {exc}")
            self._srv = None

    def handle(self, action: str, params: dict, agent: bool) -> dict:
        from . import anki_tools
        a = ACTIONS.get(action)
        if a is None:
            return {"result": None, "error": "unsupported action"}
        params = params or {}
        try:
            col = self._col()
            ctx = dict(self._ctx() or {}, agent=agent)
            if a.write:
                if agent and action == "addNote" and not ((params.get("note") or {}).get("options") or {}).get("sourcePage"):
                    return {"result": None, "error": "source page required: add_note needs source_page (the slide the card came from)"}
                # Resolved BEFORE the preview is built (and thus before the
                # dialog is even shown), and for BOTH add actions: this used
                # to run only for addNote, and only AFTER _ask() answered —
                # meaning the preview could never have shown klaus::from
                # even with an active viewer, and addNotes never got it at
                # all. Preview and the actual write must agree on which PDF
                # a card came from, so this has to happen once, up front.
                if action in ("addNote", "addNotes"):
                    try:
                        from . import viewer_context
                        v = viewer_context.current()
                        if v is not None:
                            ctx["pdf_safe"] = v.pdf_safe
                    except Exception:
                        pass
                similar = None
                if action == "addNote":
                    fields = (params.get("note") or {}).get("fields") or {}
                    first = next(iter(fields.values()), "")
                    similar = self._main(lambda: similar_existing(col, first), self._read_timeout)
                elif action == "addNotes":
                    notes = params.get("notes") or []
                    def _sims():
                        out = []
                        for n in notes:
                            fields = n.get("fields") or {}
                            first = next(iter(fields.values()), "")
                            out.append(similar_existing(col, first))
                        return out
                    similar = self._main(_sims, self._read_timeout)
                sections = preview_sections(action, params, similar, agent, ctx.get("pdf_safe"))
                title = {"addNote": "Klaus wants to add a card", "addNotes": "Klaus wants to add cards",
                         "updateNoteFields": "Klaus wants to edit a note"}.get(action, f"Klaus wants to run {action}")
                answer = self._ask(title, sections)
                if answer is None:
                    return {"result": None, "error": "approval timed out"}
                if answer is False:
                    return {"result": None, "error": "declined by user"}
            result = self._main(lambda: a.run(col, params, ctx), self._approval_timeout if a.write else self._read_timeout)
            return {"result": result, "error": None}
        except ActionError as exc:
            return {"result": None, "error": str(exc)}
        except anki_tools.ToolError as exc:
            # Same clean, unprefixed treatment as ActionError above: four
            # reused anki_tools handlers (create_note/update_note/
            # search_notes/search_lecture_pdfs) raise this, and without this
            # clause it fell into the generic branch below, prefixing an
            # otherwise-clean message with "ToolError: ".
            return {"result": None, "error": str(exc)}
        except TimeoutError:
            return {"result": None, "error": "timed out"}
        except Exception as exc:
            return {"result": None, "error": f"{type(exc).__name__}: {exc}"}

    def _ask(self, title: str, sections: list) -> bool | None:
        box: dict = {}
        done = threading.Event()
        def go():
            try:
                box["a"] = bool(self._approve(title, sections))
            except Exception as exc:
                print(f"[klausmate] endpoint approver: {exc}")
                box["a"] = False
            finally:
                done.set()
        threading.Thread(target=go, daemon=True).start()
        if not done.wait(self._approval_timeout):
            return None
        return box.get("a", False)


def _handler_for(end: Endpoint):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            # Bounds EVERY blocking read on this connection's socket — the
            # normal body read below, the 413 drain, the next
            # handle_one_request()'s own readline() while idle on
            # keep-alive — to READ_TIMEOUT_S. Fix round 3: nothing bounded
            # this before, and a caller that declares a huge Content-Length
            # while sending only a couple of bytes could otherwise block
            # this thread forever regardless of whether it was even
            # authenticated. A resulting socket.timeout/OSError is caught
            # either by do_POST's own try/except below (closing + logging,
            # never a bare traceback) or, for a timeout while idly waiting
            # on the NEXT request line, by http.server's own built-in
            # handle_one_request() timeout handling.
            self.connection.settimeout(READ_TIMEOUT_S)

        def log_message(self, *a):
            pass

        def _send(self, status: int, obj: Any, extra: dict | None = None) -> None:
            data = b"" if obj is None else json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if data:
                self.wfile.write(data)

        def do_GET(self):
            self._send(405, {"error": "POST only"})

        def do_POST(self):
            # Belt-and-suspenders around the two guards inside _route_post
            # (a malformed Content-Length, a malformed JSON "version"): any
            # OTHER exception this thread hits — a bug neither of those two
            # anticipates — must still answer the connection instead of
            # dying into socketserver's default handle_error, which prints
            # a bare traceback to stderr and drops the connection with zero
            # response bytes. That silent drop is exactly what an unguarded
            # int() cast used to do here for a bad Content-Length/version.
            try:
                self._route_post()
            except Exception as exc:
                print(f"[klausmate] endpoint: {exc}")
                # Unknown how much of the declared body (if any) was read
                # when this fired, so — same reasoning as the 400 branch
                # below — there is nothing safe to drain. Force the
                # connection closed so a reused keep-alive socket can never
                # inherit whatever position the read was left at; without
                # this, HTTP/1.1 keep-alive would hand the NEXT request on
                # this socket a corrupted read position (fix round 2: this
                # is the same failure shape the 400 and 403 branches below
                # were found to have — an early return that answers before
                # the body is consumed, leaving leftover bytes for the next
                # request on this socket to be misread as its own
                # request-line).
                self.close_connection = True
                try:
                    self._send(500, {"error": "internal server error"})
                except Exception:
                    pass

        def _route_post(self):
            if self.headers.get("Origin"):
                # Unauthenticated — reached before the token is even
                # checked. There is nothing safe to drain here: fix round
                # 2 added an unconditional drain-then-close on this branch
                # (the now-removed _close_or_drain) to protect a REUSED
                # keep-alive connection's next request, but a caller with
                # no valid token can declare ANY Content-Length, and
                # draining an attacker-chosen amount with no cap turned
                # into an indefinite per-thread hang (fix round 3, live
                # reproduction: a declared ~50MB length with only 2 bytes
                # actually sent never returned). The 413 path below is
                # safe to drain specifically because reaching it requires
                # an ALREADY-VALID token; this branch does not, so it just
                # closes without reading anything at all.
                self.close_connection = True
                return self._send(403, {"error": "browser origins are refused"})
            if self.headers.get(TOKEN_HEADER, "") != end.token:
                # Same reasoning as the Origin branch above — no drain,
                # just close.
                self.close_connection = True
                return self._send(403, {"error": "bad token"})
            n = _safe_int(self.headers.get("Content-Length"))
            if n is None:
                # Nothing safe to drain — an unparsable Content-Length
                # means the declared body size is itself unknown, so
                # closing is the only correct move (draining an unknown
                # amount risks blocking forever on a read that never
                # completes). Without this, a reused keep-alive connection
                # would hand the client's still-unread trailing bytes to
                # whatever request comes next on this socket, corrupting
                # it — reproduced live in fix round 2's review: a clean 400
                # here followed by a well-formed request on the SAME
                # socket came back a bogus 501, because the server misread
                # the leftover bytes as that request's own request-line.
                self.close_connection = True
                return self._send(400, {"error": "bad content-length"})
            if n > BODY_CAP:
                # Drain what the client declared it would send, CAPPED at
                # BODY_CAP (fix round 3: draining the full, possibly
                # enormous declared length was the same unbounded-read
                # shape the two 403 branches above no longer do at all —
                # this path only still drains because it requires an
                # ALREADY-token-AUTHED caller, so a reused keep-alive
                # connection is worth protecting from a TCP RST the way
                # the 403s' never-authenticated callers are not; capping
                # the amount removes the unbounded-time/bandwidth cost
                # while close_connection=True still forces the connection
                # closed regardless of how much was actually drained).
                # settimeout() in setup() is the second, independent
                # backstop: even a capped drain still blocks on
                # self.rfile.read() until BODY_CAP bytes actually arrive,
                # which now times out at READ_TIMEOUT_S rather than
                # hanging if the caller never sends that much.
                self._drain(min(n, BODY_CAP))
                self.close_connection = True
                return self._send(413, {"error": "body too large"})
            raw = self.rfile.read(n) if n else b""
            if self.path == "/":
                return self._ankiconnect(raw)
            if self.path == "/mcp":
                return self._mcp(raw)
            return self._send(404, {"error": "no such route"})

        def _drain(self, n: int) -> None:
            remaining = n
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _ankiconnect(self, raw: bytes) -> None:
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return self._send(200, {"result": None, "error": "invalid JSON"})
            if not isinstance(body, dict):
                return self._send(200, {"result": None, "error": "invalid request"})
            if _safe_int(body.get("version")) != API_VERSION:
                return self._send(200, {"result": None, "error": "unsupported version"})
            agent = self.headers.get(AGENT_HEADER) == "1"
            out = end.handle(str(body.get("action") or ""), body.get("params") or {}, agent)
            self._send(200, out)

        def _mcp(self, raw: bytes) -> None:
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return self._send(200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            status, out, extra = mcp_dispatch(end, body, self.headers.get("Mcp-Session-Id"))
            self._send(status, out, extra)
    return H


# ---- aqt glue --------------------------------------------------------------------

_LIVE: Endpoint | None = None


def current() -> Endpoint | None:
    return _LIVE


def _run_on_main_sync(fn: Callable, timeout: float):
    from aqt import mw
    box: dict = {}
    done = threading.Event()
    def wrapper():
        try:
            box["r"] = fn()
        except BaseException as e:
            box["e"] = e
        finally:
            done.set()
    mw.taskman.run_on_main(wrapper)
    if not done.wait(timeout):
        raise TimeoutError("main thread did not answer")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def qt_approver(title: str, sections: list) -> bool:
    """Window-modal open() on the main thread; the calling thread waits on an Event."""
    from aqt import mw
    from aqt.qt import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout
    box: dict = {}
    done = threading.Event()
    def show():
        try:
            dlg = QDialog(mw)
            dlg.setWindowTitle(title)
            dlg.setWindowModality(__import__("aqt.qt", fromlist=["Qt"]).Qt.WindowModality.WindowModal)
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel(title))
            text = QPlainTextEdit(dlg)
            text.setReadOnly(True)
            text.setPlainText("\n".join(f"{k}: {v}" if k else v for k, v in sections))
            lay.addWidget(text)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Approve")
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            lay.addWidget(buttons)
            def finished(code):
                box["a"] = code == QDialog.DialogCode.Accepted
                done.set()
                dlg.deleteLater()
            dlg.finished.connect(finished)
            box["dlg"] = dlg
            dlg.open()
        except Exception as exc:
            print(f"[klausmate] endpoint dialog: {exc}")
            box["a"] = False
            done.set()
    mw.taskman.run_on_main(show)
    if not done.wait(APPROVAL_TIMEOUT_S):
        mw.taskman.run_on_main(lambda: box.get("dlg") and box["dlg"].reject())
        return False
    return bool(box.get("a"))


def _open_browse(query: str) -> None:
    from aqt import dialogs, mw
    b = dialogs.open("Browser", mw)
    b.search_for(query)


def start_for_profile() -> Endpoint | None:
    global _LIVE
    from aqt import mw
    from . import anki_tools
    stop_for_profile()
    try:
        version = str((mw.addonManager.addon_meta(__package__.split(".")[0]) or {}).get("human_version") or "")
    except Exception:
        version = ""
    def ctx_factory():
        c = anki_tools.default_ctx()
        c["open_browse"] = lambda q: mw.taskman.run_on_main(lambda: _open_browse(q))
        return c
    end = Endpoint(col_getter=lambda: mw.col, run_on_main=_run_on_main_sync, approver=qt_approver, ctx_factory=ctx_factory, version=version)
    end.start()
    _LIVE = end
    print(f"[klausmate] endpoint on 127.0.0.1:{end.port}")
    return end


def stop_for_profile() -> None:
    global _LIVE
    if _LIVE is not None:
        _LIVE.stop()
        _LIVE = None
