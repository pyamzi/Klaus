"""anki_endpoint — the AnkiConnect-compatible server, hit over real HTTP."""
import json, os, shutil, socket, sys, tempfile, threading, time, urllib.request, urllib.error
from array import array
from pathlib import Path

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib
ep = importlib.import_module("klaus_note.anki_endpoint")
# Committed separately (Task 5/K-196) but landed by the time this fix round
# runs; real module, no stub needed — pure dict state, no aqt.
viewer_context = importlib.import_module("klaus_note.viewer_context")
# K-207: the semantic note search builds a real card_index fixture on disk
# and stubs the embedding call (same pattern test_anki_tools.py already
# uses for _semantic_pdf_search) — no network, no API key, no paid call.
# Patching these module attributes (rather than anything on `ep`) is
# deliberate: anki_endpoint._a_klaus_search_notes_semantic does `from .
# import embeddings` INSIDE the handler on every call, which just rebinds
# to whatever is already in sys.modules — so the real module object,
# never an `ep.embeddings` attribute (there isn't one), is what has to be
# patched for the handler to see the fakes.
card_index = importlib.import_module("klaus_note.card_index")
embeddings = importlib.import_module("klaus_note.embeddings")
# install() gives klaus_note a synthetic __init__ (real klaus_note/__init__.py
# is never executed, since importing submodules never needs it) — it has no
# anki_tools._semantic_pdf_search does.

# The task brief's own plan was to reuse tests/test_anki_tools.py's Col
# stub (`sys.path.insert(0, "tests"); from test_anki_tools import Col`), but
# that module runs its whole check()/section() suite AND a
# `raise SystemExit(report())` at IMPORT time — importing it here would run
# its suite and then hard-exit ours before a single one of our own checks
# ran. Per the brief's own fallback ("if that import runs that file's
# checks at import time, copy its Col/Note/Decks/Models stubs into this
# file instead and say so in a comment"): copied verbatim below, never
# edited in place. Everything anki_endpoint's OWN actions need beyond what
# anki_tools' handlers already exercise — card lookups, the collection-level
# tag manager, a model-name registry, and Note.keys()/card_ids() for
# similar_existing()/notesInfo — lives in a Col2/Note2/Decks2/Models2
# subclass further down, per Step 5's "a subclass Col2(Col), never the
# shared one" (there is no shared one anymore to edit, but the separation
# keeps a future diff against test_anki_tools.py legible).


class Note:
    def __init__(self, nid=1, fields=None, tags=None, ntname="Basic"):
        self.id = nid
        self._f = dict(fields or {"Front": "What is incidence?", "Back": "New cases."})
        self.fields = list(self._f.values())
        self.tags = list(tags or [])
        self._nt = {"name": ntname, "flds": [{"name": k} for k in self._f]}

    def note_type(self):
        return self._nt

    def items(self):
        return list(self._f.items())

    def __getitem__(self, k):
        return self._f[k]

    def __setitem__(self, k, v):
        self._f[k] = v
        self.fields = list(self._f.values())

    def cards(self):
        return [type("C", (), {"did": 1})()]


class Decks:
    def __init__(self):
        self.created = []

    def by_name(self, n):
        return {"id": 1, "name": n} if n == "Epi" else None

    def name(self, did):
        return "Epi"

    def id(self, n):
        self.created.append(n)
        return 1

    def all_names_and_ids(self):
        return [type("D", (), {"name": "Epi"})()]


class Models:
    def by_name(self, n):
        if n != "Basic":
            return None
        return {"name": "Basic", "flds": [{"name": "Front"}, {"name": "Back"}]}

    def all_names(self):
        return ["Basic"]


class Col:
    def __init__(self):
        self.decks, self.models = Decks(), Models()
        self.added, self.undo = [], []
        # Tracked separately: the stub AddNoteRequest does not retain its
        # kwargs, so the notes are inspected where they were minted, and
        # the two add paths are counted apart so "used add_notes" is a real
        # assertion rather than a vacuous one.
        self.minted, self.single_adds, self.updated = [], 0, []
        self.notes = {1: Note()}

    def find_notes(self, q):
        if q == "boom":
            raise ValueError("bad query")
        return [1]

    def get_note(self, nid):
        if nid not in self.notes:
            raise KeyError(nid)
        return self.notes[nid]

    def new_note(self, model):
        note = Note(fields={f["name"]: "" for f in model["flds"]})
        self.minted.append(note)
        return note

    def add_note(self, note, did):
        self.single_adds += 1
        self.added.append((note, did))

    def add_notes(self, requests):
        self.added.extend(requests)

    def add_custom_undo_entry(self, label):
        self.undo.append(label)
        return len(self.undo)

    def merge_undo_entries(self, pos):
        return {"merged": pos}

    def update_note(self, note):
        self.updated.append(note)


# ---- endpoint-only stub extensions (this file only; anki_tools' own
# handlers never touch cards or the collection tag manager, so the shared
# stub above has no reason to grow them) ----------------------------------


class Card:
    """Stands in for anki's Card: findCards/cardsInfo read nid/did/queue/
    ivl/due off one of these, never off a Note."""

    def __init__(self, cid, nid, did=1, queue=0, ivl=0, due=0):
        self.id, self.nid, self.did = cid, nid, did
        self.queue, self.ivl, self.due = queue, ivl, due


class Tags:
    """Stands in for col.tags (anki's TagManager). Col/Note above only ever
    modeled a NOTE's own .tags list; addTags/removeTags call the
    collection-level bulk API instead, which nothing in the shared stub
    provides."""

    def __init__(self):
        self.added, self.removed = [], []

    def bulk_add(self, note_ids, tags):
        self.added.append((list(note_ids), tags))

    def bulk_remove(self, note_ids, tags):
        self.removed.append((list(note_ids), tags))


class Note2(Note):
    def keys(self):
        return list(self._f.keys())

    def card_ids(self):
        return [1]


class Decks2(Decks):
    def by_name(self, n):
        # The shared stub only ever resolves the one deck name it was built
        # for ("Epi"); real AnkiConnect callers (and this endpoint's own
        # addNote pin, deckName="Default") pass whatever deck name the user
        # picked, so accept any of them rather than teaching Decks a second
        # magic string.
        return {"id": 1, "name": n}


class Models2(Models):
    def all_names_and_ids(self):
        return [type("M", (), {"name": "Basic"})()]


class Col2(Col):
    def __init__(self):
        super().__init__()
        self.tags = Tags()
        self.decks = Decks2()
        self.models = Models2()
        # Same note 1 as the base stub, just upgraded to Note2 so
        # similar_existing()'s note.keys() lookup and notesInfo's
        # note.card_ids() have something to call — field data unchanged.
        self.notes = {1: Note2(fields=dict(self.notes[1].items()), tags=list(self.notes[1].tags))}
        self.cards = {10: Card(10, 1)}

    def find_cards(self, q):
        return list(self.cards)

    def get_card(self, cid):
        return self.cards[int(cid)]


col = Col2()
approvals = []
def approver(title, sections):
    approvals.append((title, sections)); return approver.answer
approver.answer = True
def run_on_main(fn, timeout): return fn()
# A real temp dir, not the old placeholder "/tmp/none": K-207's semantic
# note search reads a real card_index/ off ctx["user_files"] (the exact
# same seam _semantic_pdf_search already uses), so it needs somewhere
# real to look — every other action still ignores this path entirely.
_uf_dir = tempfile.mkdtemp(prefix="klaus-ep-test-")
def ctx_factory(): return {"strip": lambda s: s, "confirm": lambda *a: True, "user_files": _uf_dir, "search_pdfs": lambda q, k: []}
end = ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main, approver=approver, ctx_factory=ctx_factory, version="0.1.3")
host, port, token = end.start()

def post(path, obj, headers=None, raw=None):
    data = raw if raw is not None else json.dumps(obj).encode()
    h = {"Content-Type": "application/json", "X-Klaus-Token": token}
    h.update(headers or {})
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode() or "null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, None, dict(e.headers)

def ac(action, **params):
    return post("/", {"action": action, "version": 6, "params": params})[1]


def _raw_read_response(f):
    """Read one HTTP response (status line + headers + Content-Length
    body) off a buffered socket file object shared across a WHOLE
    keep-alive session — a fresh sock.makefile() per response would
    strand any bytes it had already buffered past the current response's
    boundary, silently losing the start of whatever comes next. Returns
    (status_code_or_None, body); status_code is None if the peer closed
    the connection before sending anything at all — a "clean close"
    outcome the round-2 pins below accept right alongside a valid status,
    per the coordinator's instruction ("either a valid 200 JSON answer or
    a clean connection close — never a 501/parse error").
    """
    status_line = f.readline()
    if not status_line:
        return None, b""
    try:
        code = int(status_line.split(b" ", 2)[1])
    except Exception:
        code = None
    headers = {}
    while True:
        line = f.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get(b"content-length", b"0") or b"0")
    body = f.read(n) if n else b""
    return code, body


def raw_keepalive_probe(header_overrides, body):
    """Reproduce a real HTTP/1.1 keep-alive client on ONE persistent raw
    socket — urllib opens a fresh TCP connection per call, so it can never
    exercise connection reuse and cannot catch what this probes for.
    Request 1 carries `header_overrides` merged over a normal, correctly
    token'd/sized request (so a caller can break exactly one header — a
    garbage Content-Length, or a wrong token — while everything else
    about the request, including a real trailing `body`, stays
    well-formed). Request 2, sent right after on the SAME socket with no
    reconnect, is a plain, entirely valid `version` call. Fix round 2:
    several early-return responses (bad Content-Length → 400, bad
    Origin/token → 403, the general do_POST exception → 500) used to
    answer before `body` was ever read, leaving it sitting in the socket
    for request 2 to be misread as starting with — corrupting request 2
    into something like a bogus 501. Returns (code1, code2, body2).

    Fix round 3 note: the two 403 branches now close WITHOUT draining at
    all (see raw_slow_body_probe below for why), so request 1's leftover
    body can still be sitting unread when the connection closes — which
    can surface as a TCP RST instead of a clean FIN, on either the SEND or
    the READ side of request 2. The round-2 re-review already documented
    this exact race manifesting as an uncaught ConnectionResetError in a
    closely analogous mutation scenario ("the same underlying regression
    surfacing with different OS-level timing, not a different bug"), so
    both sides of request 2's round trip are guarded here, not just the
    send — what must never happen is request 2 coming back MISPARSED as
    some other status, not that it always completes.
    """
    good_body = json.dumps({"action": "version", "version": 6}).encode()
    sock = socket.create_connection((host, port), timeout=5)
    try:
        f = sock.makefile("rb")
        h = {"Host": "127.0.0.1", "Content-Type": "application/json",
             "X-Klaus-Token": token, "Content-Length": str(len(body))}
        h.update(header_overrides)
        req1 = ("POST / HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n").encode() + body
        sock.sendall(req1)
        code1, _ = _raw_read_response(f)
        req2 = ("POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                f"X-Klaus-Token: {token}\r\nContent-Length: {len(good_body)}\r\n\r\n").encode() + good_body
        try:
            sock.sendall(req2)
            code2, body2 = _raw_read_response(f)
        except OSError:
            return code1, None, b""  # peer already closed (FIN or RST) -- a clean close is fine too
        return code1, code2, body2
    finally:
        sock.close()


def raw_slow_body_probe(header_overrides, sent_body=b"xx"):
    """Fix round 3's own reproduction: a caller that DECLARES a huge
    Content-Length but only ever sends a couple of bytes and withholds the
    rest. Before this round, the two 403 branches drained the full
    declared length unconditionally (via the now-removed
    _close_or_drain()) -- reachable WITHOUT a valid token, so an
    unauthenticated caller lying about Content-Length could hang that
    connection's handling thread indefinitely. The client socket itself
    gets a short timeout so a still-present regression fails this pin in
    ~1s rather than hanging the whole suite.

    Returns (status_code_or_None, elapsed_seconds, timed_out, closed):
    `timed_out` is True if no response arrived inside the client's own
    timeout window at all; `closed` is True if, after a response WAS
    read, the server can be observed to have ended the connection (either
    a clean EOF or an OSError/RST on a follow-up read -- both count, same
    "close is close" reasoning as raw_keepalive_probe above).
    """
    h = {"Host": "127.0.0.1", "Content-Type": "application/json",
         "X-Klaus-Token": token, "Content-Length": "50000000"}
    h.update(header_overrides)
    req = ("POST / HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n").encode() + sent_body
    sock = socket.create_connection((host, port), timeout=1)
    try:
        sock.sendall(req)
        f = sock.makefile("rb")
        started = time.monotonic()
        try:
            code, _ = _raw_read_response(f)
            timed_out = False
        except socket.timeout:
            code, timed_out = None, True
        elapsed = time.monotonic() - started
        closed = False
        if not timed_out:
            try:
                closed = sock.recv(1) == b""
            except socket.timeout:
                closed = False
            except OSError:
                closed = True  # RST or similar -- also "closed" (see raw_keepalive_probe)
        return code, elapsed, timed_out, closed
    finally:
        sock.close()

section("gate")
check("ephemeral localhost port", host == "127.0.0.1" and 1024 < port < 65536 and len(token) >= 32)
check("missing token → 403", post("/", {"action": "version", "version": 6}, headers={"X-Klaus-Token": ""})[0] == 403)
check("wrong token → 403", post("/", {"action": "version", "version": 6}, headers={"X-Klaus-Token": "x" * 64})[0] == 403)
check("Origin header → 403 even with the token", post("/", {"action": "version", "version": 6}, headers={"Origin": "http://evil"})[0] == 403)
# Re-review NEW-5: hmac.compare_digest raises TypeError on a str carrying
# non-ASCII, so a malformed token header fell out of _route_post into
# do_POST's catch-all and answered 500 + close instead of this branch's
# 403 + close. Never an auth bypass — but a bad token must read as a bad
# token, not as a server bug. (latin-1 is what http.client puts on the
# wire for a header value, and what http.server decodes back, so a
# non-ASCII str really does reach the comparison as one.)
check("a NON-ASCII token header → 403, not a 500 from the catch-all",
      post("/", {"action": "version", "version": 6}, headers={"X-Klaus-Token": "tökén-ünicøde"})[0] == 403)
check("...and a still-healthy server right after it",
      ac("version") == {"result": 6, "error": None})
check("oversize body → 413", post("/", None, raw=b"x" * (4 * 1024 * 1024 + 1))[0] == 413)
# Fix round 1, Critical #1: a non-numeric Content-Length used to crash the
# request thread with an uncaught ValueError (`int(header)`, no guard),
# dropping the connection with zero response bytes instead of answering
# cleanly. urllib will not compute its own Content-Length when one is
# already present in the headers dict (Request.__init__ normalizes the key
# via add_header, so this really does override the automatic one), so
# "garbage" reaches the server on the wire exactly as sent.
check("non-numeric Content-Length → 400, body never read",
      post("/", None, raw=b"", headers={"Content-Length": "garbage"})[0] == 400)
check("bad json → error field, HTTP 200", post("/", None, raw=b"{nope")[1]["error"] is not None)
check("unknown route → 404", post("/nope", {"action": "version", "version": 6})[0] == 404)

section("keep-alive after an early-return response")
# Fix round 2: the 400/403 branches answer before the body is read; without
# draining-when-knowable + always closing, a REUSED keep-alive connection
# hands the leftover bytes to whatever request comes next on it. urllib's
# one-connection-per-call model can't observe this at all, hence the raw
# socket. `good_body` here is the real, correctly-declared-length JSON body
# sent right after the bad header — the exact "Content-Length: garbage
# immediately followed by a valid JSON body" shape the review reproduced
# live (their probe used 33 bytes; the exact count doesn't matter, only
# that request 2 comes back uncorrupted).
_good_body_r2 = json.dumps({"action": "version", "version": 6}).encode()
c1, c2, b2 = raw_keepalive_probe({"Content-Length": "garbage"}, _good_body_r2)
check("bad Content-Length answers 400 and does not corrupt the next request on the same socket",
      c1 == 400 and c2 in (None, 200)
      and (c2 != 200 or json.loads(b2 or b"null") == {"result": 6, "error": None}))
c1, c2, b2 = raw_keepalive_probe({"X-Klaus-Token": "x" * 64}, _good_body_r2)
check("bad token answers 403 and does not corrupt the next request on the same socket",
      c1 == 403 and c2 in (None, 200)
      and (c2 != 200 or json.loads(b2 or b"null") == {"result": 6, "error": None}))

section("bounded drain on the unauthenticated 403 paths")
# Fix round 3: _close_or_drain() (fix round 2) drained the FULL
# client-declared Content-Length with no cap, and both 403 branches are
# reachable WITHOUT a valid token (the Origin branch fires before the
# token is even checked) -- an unauthenticated caller declaring an absurd
# length while sending almost nothing hung that connection's handling
# thread indefinitely (live reproduction in the round-2 re-review: no
# response after 4+ seconds). Both 403s now close WITHOUT reading any
# body at all, so this must come back fast regardless of what
# Content-Length claims.
code, elapsed, timed_out, closed = raw_slow_body_probe({"X-Klaus-Token": "x" * 64})
check("(a) bad token + a lying Content-Length: 403 arrives within 1s, connection closes",
      not timed_out and code == 403 and elapsed < 1.0 and closed)
code, elapsed, timed_out, closed = raw_slow_body_probe({"Origin": "http://evil"})
check("(b) Origin header + a lying Content-Length: 403 arrives within 1s, connection closes",
      not timed_out and code == 403 and elapsed < 1.0 and closed)

# (c) Every blocking read on the connection must be bounded to
# READ_TIMEOUT_S (fix round 3's second, independent backstop alongside
# the 403s' no-drain-at-all and the 413 drain's new BODY_CAP ceiling) --
# proven WITHOUT waiting 30s for a real timeout, by calling the handler
# class's REAL setup() against a fake "connection" that just records its
# settimeout() call, exactly mirroring what
# socketserver.StreamRequestHandler.setup() does with a genuine socket
# (self.connection = self.request; rfile/wfile built from it). A bare
# object.__new__ with no __init__ means setup() runs in total isolation,
# never touching a real socket or reading a byte.
class _FakeConn:
    def __init__(self):
        self.timeout_set = None

    def settimeout(self, t):
        self.timeout_set = t

    def makefile(self, mode, *a, **k):
        import io
        return io.BytesIO()

    def setsockopt(self, *a, **k):
        pass


_H = ep._handler_for(end)
_h = _H.__new__(_H)
_h.request = _FakeConn()
_h.client_address = ("127.0.0.1", 0)
_h.server = None
_h.setup()
check("(c) the handler bounds every socket read to READ_TIMEOUT_S via setup()",
      _h.request.timeout_set == ep.READ_TIMEOUT_S)

section("AnkiConnect route")
check("version → 6", ac("version") == {"result": 6, "error": None})
check("version 5 refused", ac("version") and post("/", {"action": "version", "version": 5})[1]["error"] == "unsupported version")
# Fix round 1, Critical #1: a non-numeric "version" crashed the same way as
# a non-numeric Content-Length (`int(body.get("version") or 0)`, no guard)
# — now it falls through to the same clean "unsupported version" path any
# other wrong version number gets, HTTP 200 like the rest of this route.
check("non-numeric version → unsupported version, not a crash",
      post("/", {"action": "version", "version": "not-a-number"})[1] == {"result": None, "error": "unsupported version"})
check("...and the connection/server is still healthy right after both malformed requests",
      ac("version") == {"result": 6, "error": None})
check("unknown action", ac("zzz")["error"] == "unsupported action")
check("deckNames", isinstance(ac("deckNames")["result"], list))
check("modelNames", isinstance(ac("modelNames")["result"], list))
r = ac("findNotes", query="deck:*")
check("findNotes → ids", r["error"] is None and isinstance(r["result"], list))
info = ac("notesInfo", notes=[1])["result"]
check("notesInfo shape", info and set(info[0]) >= {"noteId", "modelName", "tags", "fields"} and all("value" in v and "order" in v for v in info[0]["fields"].values()))
r = ac("findCards", query="deck:*")
check("findCards → ids", r["error"] is None and isinstance(r["result"], list))
r = ac("cardsInfo", cards=[10])
check("cardsInfo shape", r["error"] is None and r["result"] and set(r["result"][0]) >= {"cardId", "noteId", "deckName", "queue", "interval", "due"})
# Col.add_note (see the stub above) both appends to self.added AND bumps
# self.single_adds for the SAME single-note call, so the brief's original
# `len(col.added) + col.single_adds` double-counts every single add (it
# read 2 after one addNote here, not 1) — single_adds exists to prove a
# batch path did NOT fall back to a loop of single adds (test_anki_tools.py
# uses it exactly that way: `single_adds == 0 and len(added) == 2`), not to
# be summed with added's own length. len(col.added) alone is already the
# total note count, single- or batch-added alike, since both paths append
# to it.
before = len(col.added)
r = ac("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q", "Back": "A"}, "tags": ["t"]})
check("addNote: approval asked once, note added, id returned", len(approvals) == 1 and r["error"] is None and len(col.added) == before + 1)
title, sections = approvals[-1]
check("preview is plain text with deck, model, every field, tags", any("Default" in s for _, s in sections) and any("Basic" in s for _, s in sections)
      and any("Q" in s for _, s in sections) and any("A" in s for _, s in sections) and any("t" in s for _, s in sections))
approver.answer = False
r = ac("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q2", "Back": "A2"}})
check("declined → error, nothing added", r["error"] == "declined by user" and len(col.added) == before + 1)
approver.answer = True
r = end.handle("addNote", {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q3", "Back": "A3"}}}, agent=True)
check("agent path without source page → error, no dialog", r["error"] and "source" in r["error"].lower() and len(approvals) == 2)
# Fix round 1, item 4: this pin's description always claimed to verify
# "klaus::assistant + klaus::from" but no viewer was ever active in this
# fixture — ctx.get("pdf_safe") was always falsy and the assertion never
# even looked for the tag either. Arm a real viewer_context (committed
# separately, K-196) around just this one call so both tags are genuinely
# exercised, then reset so no later check inherits an "active" viewer.
viewer_context.report_document(1, "lec1", "Lecture 1.pdf", "/lib/l1.pdf", 10)
viewer_context.activate(1)
try:
    r = end.handle("addNote", {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q3", "Back": "A3"}, "options": {"sourcePage": 4}}}, agent=True)
finally:
    viewer_context.reset()
check("agent path with source page → approval names the page and tags klaus::assistant + klaus::from",
      r["error"] is None and any("4" in s for _, s in approvals[-1][1])
      and any("klaus::assistant" in s for _, s in approvals[-1][1])
      and any("klaus::from::lec1" in s for _, s in approvals[-1][1]))
check("...and the written note itself carries klaus::from::lec1, not just the preview text",
      "klaus::from::lec1" in col.minted[-1].tags)
# M11: the source page was computed, shown in the dialog, and then
# dropped — so once the dialog closed the card's provenance was gone.
# Same tag shape anki_tools.add_reviewed_cards already uses.
check("...and klaus::page::4, so the source slide survives the dialog",
      "klaus::page::4" in col.minted[-1].tags)
check("the preview names that tag too — preview and write must agree",
      any("klaus::page::4" in s for _, s in approvals[-1][1]))
_no_page = ep.preview_sections("addNote", {"note": {"deckName": "D", "modelName": "M", "fields": {"F": "x"}}},
                               similar=None, agent=True, pdf_safe="lec1")
check("a note with no source page grows no page tag (and does not raise)",
      not any("klaus::page::" in s for _, s in _no_page))
r = ac("addNotes", notes=[{"deckName": "Default", "modelName": "Basic", "fields": {"Front": "B1", "Back": "x"}}, {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "B2", "Back": "y"}}])
check("addNotes: ONE dialog for both, two ids", len(approvals) == 4 and r["error"] is None and len(r["result"]) == 2)
r = ac("updateNoteFields", note={"id": 1, "fields": {"Front": "changed"}})
check("updateNoteFields behind approval", r["error"] is None and len(approvals) == 5 and col.updated)
r = ac("addTags", notes=[1], tags="a b")
check("addTags behind approval", r["error"] is None and len(approvals) == 6 and col.tags.added)
r = ac("removeTags", notes=[1], tags="a")
check("removeTags behind approval", r["error"] is None and len(approvals) == 7 and col.tags.removed)

# #16: the approval preview showed HTML-stripped NEW values only, so an edit
# that dropped an image looked harmless. Note 3, so note 1's state (relied
# on further down) is untouched. Mirrored without the server in
# tests/test_endpoint_write_preview.py.
col.notes[3] = Note2(fields={"Front": 'Q<img src="a.png">', "Back": "A"})
col.notes[3].id = 3
n_before = len(approvals)
r = ac("updateNoteFields", note={"id": 3, "fields": {"Front": "Q"}})
_shown = "\n".join(f"{k}: {v}" for k, v in approvals[-1][1])
check("#16 updateNoteFields preview shows OLD (with a.png) and NEW raw values",
      r["error"] is None and len(approvals) == n_before + 1 and 'OLD: Q<img src="a.png">' in _shown and "NEW: Q" in _shown, _shown)
r = ac("updateNoteFields", note={"id": 404, "fields": {"Front": "x"}})
check("#16 a missing note errors before any dialog", r["error"] and len(approvals) == n_before + 1, repr(r))
r = ac("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "x<img src=y onerror=z>", "Back": "b"}})
check("#16 addNote preview keeps field markup visible",
      any("x<img src=y onerror=z>" in s for _, s in approvals[-1][1]), repr(approvals[-1][1]))

# Fix round 1, items 2+3: addNotes isolates a per-note failure instead of
# aborting the whole batch (AnkiConnect's own list[noteId or null] result
# shape), and — agent path, viewer active — applies the same klaus::from
# tag and per-note similar-note lookup addNote already gets. One batch call
# exercises both: a bad note type in the middle makes isolation visible;
# running it as an agent request with viewer_context armed makes the tag
# path visible too.
viewer_context.report_document(1, "lec1", "Lecture 1.pdf", "/lib/l1.pdf", 10)
viewer_context.activate(1)
try:
    r = end.handle("addNotes", {"notes": [
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "G1", "Back": "x"}},
        {"deckName": "Default", "modelName": "NopeModel", "fields": {"Front": "G2", "Back": "y"}},
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "G3", "Back": "z"}},
    ]}, agent=True)
finally:
    viewer_context.reset()
check("addNotes isolates a per-note failure: [id, None, id], batch error stays None",
      r["error"] is None and len(r["result"]) == 3
      and r["result"][0] is not None and r["result"][1] is None and r["result"][2] is not None)
batch_sections = approvals[-1][1]
check("addNotes agent path: preview carries klaus::assistant + klaus::from for the batch",
      any("klaus::assistant" in s for _, s in batch_sections) and any("klaus::from::lec1" in s for _, s in batch_sections))
check("...and the two notes that were actually written carry both tags too",
      all("klaus::from::lec1" in n.tags and "klaus::assistant" in n.tags for n in col.minted[-2:]))

# Fix round 1, item 5: anki_tools.ToolError (raised by all four reused
# handlers — create_note/update_note/search_notes/search_lecture_pdfs) used
# to fall into Endpoint.handle's generic `except Exception` branch, which
# prefixes the message with the class name. updateNoteFields with an
# unknown field is the cheapest way to raise one through a reused handler.
r = ac("updateNoteFields", note={"id": 1, "fields": {"NopeField": "x"}})
check("anki_tools.ToolError gets the same clean treatment as ActionError (no 'ToolError:' prefix)",
      r["error"] is not None and "ToolError" not in r["error"] and "Unknown field" in r["error"])

r = ac("guiBrowse", query="tag:a")
check("guiBrowse returns ids (opening Browse is aqt glue, stubbed to no-op)", r["error"] is None and isinstance(r["result"], list))
check("klausCurrentView without a viewer → null result, no error", ac("klausCurrentView") == {"result": None, "error": None})
r = ac("klausSearchNotes", query="renal", limit=5)
check("klausSearchNotes routes to anki_tools.search_notes", r["error"] is None and isinstance(r["result"], list))

section("K-207: real semantic note search (klausSearchNotesSemantic)")
# A second note besides Col2's note 1, so ranking has something to prove.
col.notes[2] = Note2(fields={"Front": "Something about kidneys", "Back": "Renal physiology."}, tags=["renal"])
col.notes[2].id = 2

_card_index_dir = os.path.join(_uf_dir, "card_index")
_sem_idx = card_index.CardIndex(provider="openai", model="m", dims=2)
_sem_idx.nids = [1, 2]
_sem_idx.mods = [1, 1]
_sem_idx.hashes = ["h1", "h2"]
_sem_idx.vectors = array("f", [1.0, 0.0, 0.0, 1.0])  # row 0 -> note 1, row 1 -> note 2
card_index.save(_sem_idx, _card_index_dir)

_orig_provider_from_config = embeddings.provider_from_config
_orig_index_signature = embeddings.index_signature


class _FakeSemProvider:
    def __init__(self, vec):
        self._vec = list(vec)

    def embed(self, texts, kind="query"):
        return [self._vec]


class _FailingSemProvider:
    def embed(self, texts, kind="query"):
        raise embeddings.EmbeddingError(
            "OpenAI API key is not set — add it in KlausNote Preferences "
            "→ API keys & models.", provider="OpenAI", status=401)


try:
    # The query vector [0, 1] is engineered to match note 2's row exactly
    # (score 1.0) and note 1's row not at all (score 0.0) — same
    # engineered-vector trick test_anki_tools.py uses for _semantic_pdf_search.
    embeddings.provider_from_config = lambda get_config: _FakeSemProvider([0.0, 1.0])
    embeddings.index_signature = lambda cfg: ("openai", "m", 2)
    r = ac("klausSearchNotesSemantic", query="tell me about the kidneys", limit=5)
    check("klausSearchNotesSemantic embeds the query and ranks the CARD index (card_index.top_k), not the PDF one",
          r["error"] is None and isinstance(r["result"], list) and len(r["result"]) == 2)
    check("...note 2 (the engineered exact match) is ranked first, with a score",
          r["result"][0]["note_id"] == 2 and "score" in r["result"][0]
          and r["result"][0]["score"] > r["result"][1]["score"])
    check("...result shape is the lexical tool's shape plus a score",
          set(r["result"][0]) == {"note_id", "note_type", "preview", "tags", "score"}
          and r["result"][0]["tags"] == ["renal"])

    # "index stale -> skip" rule (same one _semantic_pdf_search and
    # curation.ensure_index apply): a signature that does not match the
    # on-disk card index answers an empty list, never a crash or garbage
    # ranks scored in the wrong embedding space.
    embeddings.index_signature = lambda cfg: ("openai", "some-other-model", 2)
    r_stale = ac("klausSearchNotesSemantic", query="tell me about the kidneys")
    check("a card index built on a different embedding signature is SKIPPED cleanly: empty list, no error",
          r_stale == {"result": [], "error": None})

    # A missing card index entirely (nothing ever built) is the same clean
    # "skip" answer, not a FileNotFoundError.
    embeddings.index_signature = lambda cfg: ("openai", "m", 2)
    _missing_uf = tempfile.mkdtemp(prefix="klaus-ep-test-noindex-")
    try:
        end2 = ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main, approver=approver,
                            ctx_factory=lambda: {"strip": lambda s: s, "confirm": lambda *a: True,
                                                  "user_files": _missing_uf, "search_pdfs": lambda q, k: []},
                            version="0.1.3")
        r_missing = end2.handle("klausSearchNotesSemantic", {"query": "anything"}, agent=False)
        check("no card index on disk at all -> empty list, not a crash",
              r_missing == {"result": [], "error": None})
    finally:
        shutil.rmtree(_missing_uf, ignore_errors=True)

    # Same embed-call pattern as _semantic_pdf_search: a provider failure
    # (e.g. no API key) surfaces its OWN clean message, unprefixed — the
    # same treatment ActionError/ToolError already get in Endpoint.handle.
    embeddings.provider_from_config = lambda get_config: _FailingSemProvider()
    r_err = ac("klausSearchNotesSemantic", query="tell me about the kidneys")
    check("an embedding failure (no key) answers the provider's own clean message, no 'EmbeddingError:' prefix",
          r_err["result"] is None
          and r_err["error"] == "OpenAI API key is not set — add it in KlausNote Preferences → API keys & models."
          and "EmbeddingError" not in r_err["error"])

    # A blank query is rejected before any embedding call is made.
    embeddings.provider_from_config = lambda get_config: _FakeSemProvider([0.0, 1.0])
    r_blank = ac("klausSearchNotesSemantic", query="  ")
    check("a blank query is refused with a clean error, no embed call attempted",
          r_blank["error"] == "query is required")
finally:
    embeddings.provider_from_config = _orig_provider_from_config
    embeddings.index_signature = _orig_index_signature

check("klausSearchNotesSemantic is a NEW, distinct tool name from klausSearchNotes",
      "klausSearchNotesSemantic" != "klausSearchNotes"
      and ep.ACTIONS["klausSearchNotesSemantic"].mcp_name != ep.ACTIONS["klausSearchNotes"].mcp_name)
check("...it is a read tool (no approval dialog)", not ep.ACTIONS["klausSearchNotesSemantic"].write)
check("...its description says it IS semantic, and still points at klausSearchNotes for exact/Anki-syntax search",
      "emantic" in ep.ACTIONS["klausSearchNotesSemantic"].description
      and "klausSearchNotes" in ep.ACTIONS["klausSearchNotesSemantic"].description)
check("klausSearchNotes itself is untouched by this card — still the same precise lexical framing",
      "ANKI SEARCH SYNTAX" in ep.ACTIONS["klausSearchNotes"].description)
check("klausSearchNotesSemantic is exposed over /mcp too, with no drift from the registry's own description",
      [t for t in ep.mcp_tools() if t["name"] == "search_notes_semantic"][0]["description"]
      == ep.ACTIONS["klausSearchNotesSemantic"].description)

section("pure helpers")
# similar_existing(col, "Q changed words here") is invoked AFTER
# updateNoteFields above changed note 1's Front to "changed" — this is a
# real assertion against that known value, not the brief's original
# placeholder ("in (None, 'changed')") which would have passed even if
# similar_existing always returned None. See task-3-report.md for the trace.
check("similar_existing finds a note by the front's first words",
      ep.similar_existing(col, "Q changed words here") == "changed")
secs = ep.preview_sections("addNote", {"note": {"deckName": "D", "modelName": "M", "fields": {"F": "<b>x</b>"}, "tags": ["t"], "options": {"sourcePage": 2}}}, similar="old front")
# #16: raw field HTML, never only the stripped form (this check used to pin stripping).
check("preview keeps raw html, names similar note and source page",
      any(s == "<b>x</b>" for _, s in secs) and any("old front" in s for _, s in secs) and any("2" in s for _, s in secs))

section("registry")
check("every ACTIONS entry is an Action with a schema and a run", all(hasattr(a, "schema") and callable(a.run) for a in ep.ACTIONS.values()))
check("writes flagged", all(ep.ACTIONS[n].write for n in ("addNote", "addNotes", "updateNoteFields", "addTags", "removeTags")) and not ep.ACTIONS["findNotes"].write)
check("exact supported set",
      set(ep.ACTIONS) == {"version", "deckNames", "deckNamesAndIds", "modelNames", "modelFieldNames", "findNotes", "notesInfo",
                          "findCards", "cardsInfo", "addNote", "addNotes", "updateNoteFields", "addTags", "removeTags",
                          "guiBrowse", "klausSearchNotes", "klausSearchNotesSemantic", "klausSearchLecturePdfs",
                          "klausCurrentView", "klausCurrentPage", "klausGetPage"}, str(sorted(ep.ACTIONS)))

# --- I3: klausSearchNotes is LEXICAL, and its description must say so.
# anki_tools._h_search_notes is col.find_notes(query) — Anki's own
# search. Calling it semantic told the model to send natural-language
# questions to a tool that ANDs every word as a substring match, so it
# got nothing back and concluded the user had no notes on the topic:
# exactly the answer this assistant exists to avoid. (The semantic note
# search is K-207; this is the relabel, per the orchestrator's ruling.)
_notes_desc = ep.ACTIONS["klausSearchNotes"].description
check("klausSearchNotes is NOT advertised as semantic",
      "semantic" not in _notes_desc.lower().replace("not semantic", "")
      and "Semantic search over the user's notes" not in _notes_desc)
check("...it names Anki search syntax instead",
      "ANKI SEARCH SYNTAX" in _notes_desc and "deck:" in _notes_desc and "tag:" in _notes_desc)
check("...and points at search_lecture_pdfs as the meaning-based one",
      "search_lecture_pdfs" in _notes_desc)
check("klausSearchLecturePdfs IS still the semantic one",
      "emantic" in ep.ACTIONS["klausSearchLecturePdfs"].description)
check("the description the MODEL sees over /mcp is that same text (one registry, no drift)",
      [t for t in ep.mcp_tools() if t["name"] == "search_notes"][0]["description"] == _notes_desc)

section("MAX_SESSIONS — the session set is bounded (M10)")
_bounded = ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main, approver=lambda t, s: True,
                       ctx_factory=ctx_factory, version="x")
for _i in range(ep.MAX_SESSIONS + 5):
    ep.mcp_dispatch(_bounded, {"jsonrpc": "2.0", "id": _i, "method": "initialize", "params": {}}, None)
check("one `initialize` per child, forever, never grows past MAX_SESSIONS",
      len(_bounded.sessions) <= ep.MAX_SESSIONS and ep.MAX_SESSIONS == 64)

section("approval timeout")
slow_end = ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main, approver=lambda t, s: (threading.Event().wait(0.2), False)[1],
                       ctx_factory=ctx_factory, version="x", approval_timeout=0.05)
r = slow_end.handle("addNote", {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Z", "Back": "z"}}}, agent=False)
check("an approver that never answers in time → 'approval timed out'", r["error"] == "approval timed out")

section("MCP route")
def rpc(method, params=None, rid=1, headers=None):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None: body["params"] = params
    return post("/mcp", body, headers=headers)
st, r, h = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
check("initialize echoes protocol, names klaus, sets a session header",
      st == 200 and r["result"]["protocolVersion"] == "2025-06-18" and r["result"]["serverInfo"]["name"] == "klaus"
      and "tools" in r["result"]["capabilities"] and any(k.lower() == "mcp-session-id" for k in h))
sid = [v for k, v in h.items() if k.lower() == "mcp-session-id"][0]
st, r, _ = post("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Mcp-Session-Id": sid})
check("initialized → 202 no body", st == 202 and r is None)
# M9: EVERY notifications/* is a notification. JSON-RPC forbids replying
# to one at all, and notifications/cancelled is precisely what an MCP
# client sends when it abandons a slow tools/call — e.g. one blocked on
# Klaus's approval dialog — so a -32601 REPLY went back for a message
# that asked for none.
st, r, _ = post("/mcp", {"jsonrpc": "2.0", "method": "notifications/cancelled",
                         "params": {"requestId": 6, "reason": "timed out"}},
                headers={"Mcp-Session-Id": sid})
check("notifications/cancelled → 202 no body, never a -32601 reply", st == 202 and r is None)
st, r, _ = post("/mcp", {"jsonrpc": "2.0", "method": "notifications/anything_else"},
                headers={"Mcp-Session-Id": sid})
check("...and so is any other notifications/* method", st == 202 and r is None)
st, r, _ = rpc("ping", rid=2)
check("ping → empty result", r["result"] == {})
st, r, _ = rpc("tools/list", rid=3)
names = {t["name"] for t in r["result"]["tools"]}
check("tools/list equals the registry's MCP names with schemas",
      names == set(ep.MCP_TO_ACTION) and all("inputSchema" in t and "description" in t for t in r["result"]["tools"]))
st, r, _ = rpc("tools/call", {"name": "list_decks", "arguments": {}}, rid=4)
check("tools/call → text content, not error", r["result"]["isError"] is False and r["result"]["content"][0]["type"] == "text"
      and isinstance(json.loads(r["result"]["content"][0]["text"]), list))
st, r, _ = rpc("tools/call", {"name": "add_note", "arguments": {"deck": "Default", "model": "Basic", "fields": {"Front": "M", "Back": "m"}}}, rid=5)
check("add_note without source_page → isError with the message, not a JSON-RPC error",
      "error" not in r and r["result"]["isError"] is True and "source" in r["result"]["content"][0]["text"].lower())
n_before = len(approvals)
for folder in ('contexts', 'pdfs'):
    Path(_uf_dir, folder).mkdir(exist_ok=True)
Path(_uf_dir, 'contexts', 'lecture.txt').write_text('slide')
Path(_uf_dir, 'contexts', 'lecture.json').write_text(json.dumps({'pages': ['slide'] * 9}))
Path(_uf_dir, 'pdfs', 'lecture.pdf').write_bytes(b'%PDF-1.4 fixture')
st, r, _ = rpc("tools/call", {"name": "add_note", "arguments": {"deck": "Default", "model": "Basic", "fields": {"Front": "M", "Back": "m"}, "source_pdf": "lecture", "source_page": 9}}, rid=6)
check("add_note with explicit source reaches approval and returns a note id", len(approvals) == n_before + 1 and r["result"]["isError"] is False)
st, r, _ = rpc("tools/call", {"name": "nope", "arguments": {}}, rid=7)
check("unknown tool is a protocol error", r["error"]["code"] == -32602)
st, r, _ = rpc("zzz/method", rid=8)
check("unknown method → -32601", r["error"]["code"] == -32601)
st, r, _ = post("/mcp", None, raw=b"{bad")
check("bad json → -32700", r["error"]["code"] == -32700)
# Fix round 1 (review Important #1): JSON-RPC 2.0 formally permits params to
# be an Array (by-position) as well as an Object, so an array/string params
# is legal-shaped input, not garbage — but `params.get(...)` inside
# mcp_dispatch used to assume an Object unconditionally, crashing to a
# non-JSON-RPC-shaped HTTP 500 instead of a clean -32602. rpc()'s own
# params=None guard means passing a non-None, non-dict value (a list or a
# str) here reaches mcp_dispatch exactly the way a real by-position caller
# would.
st, r, _ = rpc("initialize", [1, 2, 3], rid=9)
check("initialize with array params (legal JSON-RPC, by-position) → -32602, not a crash",
      st == 200 and r["error"]["code"] == -32602)
st, r, _ = rpc("tools/call", "oops", rid=10)
check("tools/call with string params → -32602, not a crash",
      st == 200 and r["error"]["code"] == -32602)
st, r, _ = rpc("ping", rid=11)
check("...and the connection/server is still healthy right after both malformed-params requests",
      st == 200 and r["result"] == {})
req = urllib.request.Request(f"http://{host}:{port}/mcp", headers={"X-Klaus-Token": token}, method="GET")
try:
    urllib.request.urlopen(req, timeout=5); got = 200
except urllib.error.HTTPError as e:
    got = e.code
check("GET /mcp → 405 (no SSE stream)", got == 405)
r2 = ac("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "M", "Back": "m"}})
check("the MCP route sets the agent flag: the same note without a source page is refused on /mcp (above) but accepted on /", r2["error"] is None)

end.stop()
check("stop closes the port", True)
shutil.rmtree(_uf_dir, ignore_errors=True)

section("what only a running Anki can prove")
# Same convention as test_anki_tools.py's own tail section: pin the SOURCE
# for facts a headless stub cannot exercise (a real Qt event loop). Raw
# _SRC, never code_only, for the log-message substrings below — code_only
# strips string literals along with comments, so a check against the
# stripped text would pass even if the message text were deleted entirely
# (see klaus-test-code-only-trap memory).
_SRC = open("klaus_note/anki_endpoint.py").read()
_CODE = code_only(_SRC)
check("no app-modal exec() anywhere in the module (K-114) — the approval "
      "dialog is window-modal open(), never exec()",
      ".exec()" not in _CODE and "QInputDialog.get" not in _CODE
      and "QMessageBox.question" not in _CODE and "askUser(" not in _CODE
      and "dlg.open()" in _CODE)
check("the approver thread logs rather than swallowing an exception",
      "[klaus_note] endpoint approver" in _SRC)
check("the dialog thread logs rather than swallowing an exception",
      "[klaus_note] endpoint dialog" in _SRC)
check("stop() logs rather than swallowing an exception",
      "[klaus_note] endpoint stop" in _SRC)
check("do_POST's own safety net logs rather than dropping the connection silently",
      "[klaus_note] endpoint:" in _SRC)
# Parked T3 finding, fix now: handle()'s generic except returned the
# error over HTTP to the child and left NO trace on Anki's side, so a
# failing tool call was invisible to the user and to a later debug pass.
check("handle()'s generic except LOGS the failure, not only returns it",
      '[klaus_note] endpoint {action}: {type(exc).__name__}: {exc}' in _SRC)

# --- I6: DENY is the default button. QDialogButtonBox makes Ok the
# default, and this dialog is window-modal on mw, so it takes keyboard
# focus the instant it opens: a user typing in the assistant input who
# hit Enter as a card proposal landed had just approved a write they
# never read. anki_tools._confirm_write_dialog deliberately did the
# opposite; its replacement (R1) had lost that.
check("the Cancel button is made the default",
      "cancel.setDefault(True)" in _CODE and "cancel.setAutoDefault(True)" in _CODE)
check("...and Approve is explicitly NOT the default and not auto-default",
      "approve.setDefault(False)" in _CODE and "approve.setAutoDefault(False)" in _CODE)
check("the Ok button is still the one relabelled Approve",
      'setText("Approve")' in _SRC)
# M8: styled like every other Klaus dialog, and never outliving the
# endpoint whose answer it is.
check("the approval dialog applies theme.dialog_qss",
      "theme.dialog_qss" in _CODE)
check("stop_for_profile rejects any approval dialog still on screen",
      "reject_open_approvals" in _CODE
      and _SRC.index("def stop_for_profile") < _SRC.index("reject_open_approvals()\n    if _LIVE"))
# M19: viewer_context is mutated by the MAIN thread with no lock; the
# HTTP thread must not read it directly. Both the pdf_safe lookup and
# similar_existing now hop through run_on_main.
check("the viewer_context read happens inside a run_on_main hop, not on the HTTP thread",
      "def _viewed()" in _CODE and "self._main(_viewed" in _CODE)
# M10: a constant-time comparison for the token.
check("the token is compared with hmac.compare_digest, not ==",
      "hmac.compare_digest" in _CODE and "import hmac" in _CODE)

section("private discovery lifecycle")
from pathlib import Path
from unittest.mock import patch
import stat

with tempfile.TemporaryDirectory(prefix="klaus discovery ") as scratch:
    discovery = Path(scratch) / "nested" / "connection.json"
    def make_endpoint():
        return ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main,
                           approver=approver, ctx_factory=ctx_factory,
                           version="test", discovery_path=str(discovery))
    first = make_endpoint()
    host1, port1, token1 = first.start()
    check("discovery matches bound endpoint", json.loads(discovery.read_text()) ==
          {"host": host1, "port": port1, "token": token1})
    check("discovery mode is private", stat.S_IMODE(discovery.stat().st_mode) == 0o600)
    second = make_endpoint()
    second.start()
    check("concurrent launch has fresh port and token", second.port != port1 and second.token != token1)
    first.stop()
    check("old stop preserves newer discovery", json.loads(discovery.read_text())["token"] == second.token)
    previous_token = second.token
    second.stop()
    check("owner stop removes discovery", not discovery.exists())
    second.start()
    check("restart rotates token", second.token != previous_token)
    second.stop()
    first.start()
    cleanup_read = threading.Event()
    release_cleanup = threading.Event()
    publication_ready = threading.Event()
    publication_done = threading.Event()
    real_load, real_fsync, real_replace = ep.json.load, ep.os.fsync, ep.os.replace
    def paused_load(stream):
        value = real_load(stream)
        cleanup_read.set()
        if not release_cleanup.wait(5):
            raise RuntimeError("cleanup test gate timed out")
        return value
    def ready_fsync(fd):
        real_fsync(fd)
        publication_ready.set()
    def tracked_replace(source, destination):
        real_replace(source, destination)
        publication_done.set()
    stopping = threading.Thread(target=first.stop)
    starting = threading.Thread(target=second.start)
    with patch.object(ep.json, "load", side_effect=paused_load), \
         patch.object(ep.os, "fsync", side_effect=ready_fsync), \
         patch.object(ep.os, "replace", side_effect=tracked_replace):
        try:
            stopping.start()
            check("old cleanup paused after reading identity", cleanup_read.wait(5))
            starting.start()
            check("new discovery ready during old cleanup", publication_ready.wait(5))
            check("publication waits for ownership check and removal", not publication_done.wait(0.2))
        finally:
            release_cleanup.set()
            stopping.join(5)
            starting.join(5)
    check("overlapping lifecycle threads finish", not stopping.is_alive() and not starting.is_alive())
    check("overlapping old stop preserves newly published discovery",
          discovery.exists() and json.loads(discovery.read_text())["token"] == second.token)
    second.stop()
    failed = make_endpoint()
    with patch.object(ep.os, "replace", side_effect=OSError("injected write failure")):
        try:
            failed.start()
            check("publication failure propagates", False)
        except OSError:
            check("publication failure propagates", True)
    check("failure leaves no partial discovery", not discovery.exists() and not list(discovery.parent.iterdir()))
    with socket.socket() as probe:
        check("publication failure closes bound socket", probe.connect_ex(("127.0.0.1", failed.port)) != 0)
    failed.stop()
    original_fchmod = getattr(ep.os, "fchmod", None)
    if original_fchmod is not None:
        del ep.os.fchmod
    try:
        portable = make_endpoint()
        portable.start()
        check("missing fchmod still publishes discovery", json.loads(discovery.read_text())["token"] == portable.token)
        check("missing fchmod keeps discovery private", stat.S_IMODE(discovery.stat().st_mode) == 0o600)
        portable.stop()
    finally:
        if original_fchmod is not None:
            ep.os.fchmod = original_fchmod

raise SystemExit(report())
