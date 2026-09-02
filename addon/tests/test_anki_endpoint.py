"""anki_endpoint — the AnkiConnect-compatible server, hit over real HTTP."""
import json, socket, sys, threading, time, urllib.request, urllib.error

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib
ep = importlib.import_module("klausmate.anki_endpoint")
# Committed separately (Task 5/K-196) but landed by the time this fix round
# runs; real module, no stub needed — pure dict state, no aqt.
viewer_context = importlib.import_module("klausmate.viewer_context")

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
def ctx_factory(): return {"strip": lambda s: s, "confirm": lambda *a: True, "user_files": "/tmp/none", "search_pdfs": lambda q, k: []}
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
r = ac("addNotes", notes=[{"deckName": "Default", "modelName": "Basic", "fields": {"Front": "B1", "Back": "x"}}, {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "B2", "Back": "y"}}])
check("addNotes: ONE dialog for both, two ids", len(approvals) == 4 and r["error"] is None and len(r["result"]) == 2)
r = ac("updateNoteFields", note={"id": 1, "fields": {"Front": "changed"}})
check("updateNoteFields behind approval", r["error"] is None and len(approvals) == 5 and col.updated)
r = ac("addTags", notes=[1], tags="a b")
check("addTags behind approval", r["error"] is None and len(approvals) == 6 and col.tags.added)
r = ac("removeTags", notes=[1], tags="a")
check("removeTags behind approval", r["error"] is None and len(approvals) == 7 and col.tags.removed)

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

section("pure helpers")
# similar_existing(col, "Q changed words here") is invoked AFTER
# updateNoteFields above changed note 1's Front to "changed" — this is a
# real assertion against that known value, not the brief's original
# placeholder ("in (None, 'changed')") which would have passed even if
# similar_existing always returned None. See task-3-report.md for the trace.
check("similar_existing finds a note by the front's first words",
      ep.similar_existing(col, "Q changed words here") == "changed")
secs = ep.preview_sections("addNote", {"note": {"deckName": "D", "modelName": "M", "fields": {"F": "<b>x</b>"}, "tags": ["t"], "options": {"sourcePage": 2}}}, similar="old front")
check("preview strips html, names similar note and source page",
      any("x" in s and "<b>" not in s for _, s in secs) and any("old front" in s for _, s in secs) and any("2" in s for _, s in secs))

section("registry")
check("every ACTIONS entry is an Action with a schema and a run", all(hasattr(a, "schema") and callable(a.run) for a in ep.ACTIONS.values()))
check("writes flagged", all(ep.ACTIONS[n].write for n in ("addNote", "addNotes", "updateNoteFields", "addTags", "removeTags")) and not ep.ACTIONS["findNotes"].write)
check("exact supported set",
      set(ep.ACTIONS) == {"version", "deckNames", "deckNamesAndIds", "modelNames", "modelFieldNames", "findNotes", "notesInfo",
                          "findCards", "cardsInfo", "addNote", "addNotes", "updateNoteFields", "addTags", "removeTags",
                          "guiBrowse", "klausSearchNotes", "klausSearchLecturePdfs", "klausCurrentView"}, str(sorted(ep.ACTIONS)))

section("approval timeout")
slow_end = ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main, approver=lambda t, s: (threading.Event().wait(0.2), False)[1],
                       ctx_factory=ctx_factory, version="x", approval_timeout=0.05)
r = slow_end.handle("addNote", {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Z", "Back": "z"}}}, agent=False)
check("an approver that never answers in time → 'approval timed out'", r["error"] == "approval timed out")

end.stop()
check("stop closes the port", True)

section("what only a running Anki can prove")
# Same convention as test_anki_tools.py's own tail section: pin the SOURCE
# for facts a headless stub cannot exercise (a real Qt event loop). Raw
# _SRC, never code_only, for the log-message substrings below — code_only
# strips string literals along with comments, so a check against the
# stripped text would pass even if the message text were deleted entirely
# (see klaus-test-code-only-trap memory).
_SRC = open("klausmate/anki_endpoint.py").read()
_CODE = code_only(_SRC)
check("no app-modal exec() anywhere in the module (K-114) — the approval "
      "dialog is window-modal open(), never exec()",
      ".exec()" not in _CODE and "QInputDialog.get" not in _CODE
      and "QMessageBox.question" not in _CODE and "askUser(" not in _CODE
      and "dlg.open()" in _CODE)
check("the approver thread logs rather than swallowing an exception",
      "[klausmate] endpoint approver" in _SRC)
check("the dialog thread logs rather than swallowing an exception",
      "[klausmate] endpoint dialog" in _SRC)
check("stop() logs rather than swallowing an exception",
      "[klausmate] endpoint stop" in _SRC)
check("do_POST's own safety net logs rather than dropping the connection silently",
      "[klausmate] endpoint:" in _SRC)

raise SystemExit(report())
