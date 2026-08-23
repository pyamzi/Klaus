"""Headless tests for the API-first embedding stack + PDF-retention feature.

Run: env QT_QPA_PLATFORM=offscreen python3 test_klausmate.py
"""
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from array import array
from http.server import BaseHTTPRequestHandler, HTTPServer

ADDON = "/Users/pyamzi/Documents/Github/Addons/klausmate"
APP_PACKAGES = "/Applications/Anki.app/Contents/Resources/app_packages"

# Synthetic package so relative imports inside the modules resolve.
pkg = types.ModuleType("klausmate")
pkg.__path__ = [ADDON]
pkg.__package__ = "klausmate"
sys.modules["klausmate"] = pkg

import importlib

embeddings = importlib.import_module("klausmate.embeddings")
card_index = importlib.import_module("klausmate.card_index")
pdf_handler = importlib.import_module("klausmate.pdf_handler")
pdf_index = importlib.import_module("klausmate.pdf_index")

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


# ---------------------------------------------------------------- providers

print("== provider selection ==")
check("default provider is voyage for {}", embeddings.provider_name({}) == "voyage")
check("unknown provider falls back to voyage",
      embeddings.provider_name({"embedding_provider": "banana"}) == "voyage")
check("explicit ollama respected",
      embeddings.provider_name({"embedding_provider": "ollama"}) == "ollama")
check("voyage default model",
      embeddings.embedding_model({}) == "voyage-3-lite")
check("signature", embeddings.index_signature({}) == ("voyage", "voyage-3-lite"))

print("== missing key ==")
try:
    embeddings.VoyageEmbeddings(lambda: {}).embed(["hi"])
    check("voyage no key raises", False)
except embeddings.EmbeddingError as e:
    check("voyage no key raises 401", e.status == 401)
    check("401 message mentions Manage models", "Manage models" in e.user_message())

# Mock server: scripted responses per request.
SCRIPT = []          # list of (status, body_dict_or_none, headers)
REQUESTS = []        # recorded request payloads


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        REQUESTS.append(json.loads(self.rfile.read(n).decode("utf-8")))
        status, body, headers = SCRIPT.pop(0) if SCRIPT else (200, None, {})
        if body is None:
            count = len(REQUESTS[-1].get("input") or [])
            body = {"data": [{"index": i, "embedding": [1.0, 0.0]} for i in range(count)]}
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
embeddings.VOYAGE_API_BASE = base
embeddings.OPENAI_API_BASE = base

print("== mock HTTP ==")
cfg = {"embedding_api_key_voyage": "k", "embedding_provider": "voyage"}
prov = embeddings.VoyageEmbeddings(lambda: cfg)
SCRIPT[:] = [(200, None, {})]
REQUESTS.clear()
vecs = prov.embed(["a", "b"], kind="document")
check("voyage embed returns 2 vectors", len(vecs) == 2)
check("voyage sends input_type document",
      REQUESTS[-1].get("input_type") == "document")
prov.embed(["a"], kind="query")
check("voyage sends input_type query", REQUESTS[-1].get("input_type") == "query")

SCRIPT[:] = [(429, {"error": "slow down"}, {"retry-after": "0"}), (200, None, {})]
REQUESTS.clear()
vecs = prov.embed(["a"])
check("429 retried once then succeeds", len(vecs) == 1 and len(REQUESTS) == 2)

# URLError retry: point at a closed port; expect ~1 retry then error.
embeddings.VOYAGE_API_BASE = "http://127.0.0.1:1"
t0 = time.time()
try:
    prov.embed(["a"])
    check("URLError raises", False)
except embeddings.EmbeddingError as e:
    took = time.time() - t0
    check("URLError raises EmbeddingError after retry",
          "reach" in str(e).lower() and took >= 1.9, f"took={took:.1f}s")
embeddings.VOYAGE_API_BASE = base

# batch clamp
class FakeVoyage:
    name = "voyage"
    def __init__(self):
        self.sizes = []
    def embed(self, texts, kind="document"):
        self.sizes.append(len(texts))
        return [[1.0, 0.0]] * len(texts)

fv = FakeVoyage()
list(embeddings.embed_batches(fv, ["x"] * 300, batch_size=999))
check("voyage batch clamped to 128", max(fv.sizes) == 128, str(fv.sizes))

# ---------------------------------------------------------------- pdf_index

print("== pdf_index ==")
tmp = tempfile.mkdtemp(prefix="klaus_test_")
ctx_dir = os.path.join(tmp, "contexts")
os.makedirs(ctx_dir)

pages = [
    ("Alpha beta gamma. " * 40).strip(),   # page 1: long enough for 2+ chunks
    "",                                      # page 2: empty
    ("Delta epsilon zeta. " * 40).strip(),  # page 3
]
with open(os.path.join(ctx_dir, "Lecture_1.json"), "w") as f:
    json.dump({"pages": pages, "page_count": 3}, f)
with open(os.path.join(ctx_dir, "Lecture_1.txt"), "w") as f:
    f.write("\n\n".join(pages))

chunks = pdf_index.chunk_pages(pages, cap=1000)
check("chunks produced", len(chunks) >= 4, str(len(chunks)))
check("page attribution", {c[0] for c in chunks} == {1, 3}, str({c[0] for c in chunks}))
check("chunk text recoverable",
      all(pdf_index.chunk_text_at(pages, (p, s, ln)) == t.strip()
          for p, s, ln, t in chunks))
capped = pdf_index.chunk_pages(pages, cap=3)
check("stride cap", len(capped) == 3)

sig = pdf_index.source_signature(tmp, "Lecture 1.pdf")
check("source signature resolves via safe name", sig is not None)

idx = pdf_index.PdfIndex(
    provider="voyage", model="voyage-3-lite", pdf_name="Lecture_1",
    source_sig=sig, chunks=[(p, s, ln) for p, s, ln, _ in chunks],
)
idx.dims = 4
for i in range(len(chunks)):
    v = [0.0] * 4
    v[i % 4] = 1.0
    idx.vectors.extend(v)
    idx.embedded_rows += 1
d = pdf_index.index_dir(tmp, "Lecture 1")
pdf_index.save(idx, d)
idx2 = pdf_index.load(d)
check("save/load roundtrip", idx2 is not None and idx2.chunks == idx.chunks
      and idx2.embedded_rows == idx.embedded_rows and idx2.vectors == idx.vectors)
check("is_fresh true", pdf_index.is_fresh(idx2, sig, ("voyage", "voyage-3-lite")))
check("is_fresh false on provider change",
      not pdf_index.is_fresh(idx2, sig, ("openai", "text-embedding-3-small")))
check("is_fresh false on source change",
      not pdf_index.is_fresh(idx2, (sig[0] + 1, sig[1]), ("voyage", "voyage-3-lite")))

# resume state: fewer embedded rows than chunks
idx2.embedded_rows -= 2
del idx2.vectors[-8:]
pdf_index.save(idx2, d)
idx3 = pdf_index.load(d)
check("partial index loads with resume cursor",
      idx3 is not None and idx3.embedded_rows == len(chunks) - 2)
check("partial index is not fresh",
      not pdf_index.is_fresh(idx3, sig, ("voyage", "voyage-3-lite")))

# corrupt vectors -> load None
with open(os.path.join(d, "vectors.f32"), "ab") as f:
    f.write(b"\x00\x00\x00\x00")
check("truncated/oversized vectors -> rebuild", pdf_index.load(d) is None)

st = pdf_index.stats_from_disk(d)
check("stats_from_disk reads manifest", st["exists"] and st["chunks"] == len(chunks))

pdf_index.delete(tmp, "Lecture 1")
check("delete removes dir", not os.path.isdir(d))

# delete_context wiring
d2 = pdf_index.index_dir(tmp, "Lecture 1")
os.makedirs(d2, exist_ok=True)
with open(os.path.join(d2, "manifest.json"), "w") as f:
    f.write("{}")
pdf_handler.delete_context(tmp, "Lecture 1")
check("delete_context removes pdf_index dir", not os.path.isdir(d2))

# ---------------------------------------------------- retention (needs aqt)

print("== retention math (aqt stubbed) ==")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class _AnyOp:
    def __init__(self, *a, **k): pass
    def success(self, *a, **k): return self
    def failure(self, *a, **k): return self
    def without_collection(self): return self
    def run_in_background(self): pass


aqt_mod = _stub("aqt", mw=None)
aqt_mod.dialogs = types.SimpleNamespace(open=lambda *a, **k: None)
_stub("aqt.operations", CollectionOp=_AnyOp, QueryOp=_AnyOp)
_stub("aqt.utils", tooltip=lambda *a, **k: None, askUser=lambda *a, **k: False,
      showWarning=lambda *a, **k: None)
_stub("aqt.qt", QAction=object, QInputDialog=object, qconnect=lambda *a, **k: None)
_stub("aqt.gui_hooks")
aqt_mod.gui_hooks = sys.modules["aqt.gui_hooks"]
_stub("anki")
_stub("anki.collection", AddNoteRequest=object)

try:
    retention = importlib.import_module("klausmate.retention")
    HAVE_RETENTION = True
except Exception as e:
    HAVE_RETENTION = False
    print(f" SKIP retention import failed: {type(e).__name__}: {e}")

if HAVE_RETENTION:
    r = retention.fsrs_retrievability(10.0, 0.5, 0.0)
    check("R at t=0 is 1", abs(r - 1.0) < 1e-9)
    # classic curve: at t = 9*s? No — check monotonic + dr anchor:
    # by construction R(s, decay, t=s) == 0.9 (definition of stability).
    r = retention.fsrs_retrievability(10.0, 0.5, 10.0)
    check("R at t=s is 0.90 (stability definition)", abs(r - 0.9) < 1e-9, f"{r}")
    r154 = retention.fsrs_retrievability(10.0, 0.154, 10.0)
    check("R at t=s is 0.90 for decay=0.154", abs(r154 - 0.9) < 1e-9, f"{r154}")
    check("R decreasing in t",
          retention.fsrs_retrievability(10.0, 0.5, 30.0)
          < retention.fsrs_retrievability(10.0, 0.5, 5.0))
    check("s<=0 guarded", retention.fsrs_retrievability(0.0, 0.5, 5.0) == 0.0)

    # match_scores on hand-built unit vectors
    cidx = card_index.CardIndex(provider="voyage", model="voyage-3-lite", dims=2)
    for nid, vec in [(1, [1.0, 0.0]), (2, [0.0, 1.0]),
                     (3, [math.sqrt(0.5), math.sqrt(0.5)])]:
        cidx.nids.append(nid)
        cidx.mods.append(0)
        cidx.hashes.append("h%d" % nid)
        cidx.vectors.extend(vec)
    pidx = pdf_index.PdfIndex(provider="voyage", model="voyage-3-lite",
                              pdf_name="x", dims=2)
    for vec in ([1.0, 0.0], [0.0, 1.0]):
        pidx.chunks.append((1, 0, 1))
        pidx.vectors.extend(vec)
        pidx.embedded_rows += 1
    scores = dict(retention.match_scores(pidx, cidx, agg="max", floor=0.0))
    check("max agg: nid1 = 1.0", abs(scores[1] - 1.0) < 1e-6)
    check("max agg: nid3 = 0.707", abs(scores[3] - math.sqrt(0.5)) < 1e-6)
    floored = dict(retention.match_scores(pidx, cidx, agg="max", floor=0.9))
    check("floor filters", set(floored) == {1, 2})
    t3 = dict(retention.match_scores(pidx, cidx, agg="top3_mean", floor=0.0))
    check("top3_mean of 2 chunks averages both", abs(t3[1] - 0.5) < 1e-6, f"{t3[1]}")
    try:
        bad = pdf_index.PdfIndex(provider="openai", model="x", pdf_name="x", dims=2)
        retention.match_scores(bad, cidx)
        check("signature mismatch raises", False)
    except ValueError:
        check("signature mismatch raises", True)

    # pdf_retention weighted math
    matches = [(1, 0.8), (2, 0.4), (3, 0.6)]
    card_r = {1: [(0.9, False), (0.5, False)], 2: [(1.0, False)], 3: [(0.0, True)]}
    out = retention.pdf_retention(matches, threshold=0.5, card_r=card_r)
    # matched: nid1 (sim .8, cards .9/.5), nid3 (sim .6, card R=0 new)
    exp = (0.8 * 0.9 + 0.8 * 0.5 + 0.6 * 0.0) / (0.8 + 0.8 + 0.6)
    check("weighted retention", abs(out["retention"] - exp) < 1e-9,
          f"{out['retention']} vs {exp}")
    check("matched cards", out["matched_cards"] == 3)
    check("new pct", abs(out["new_pct"] - 1 / 3) < 1e-9)
    check("priority formula",
          abs(out["priority"] - (1 - exp) * math.log1p(3)) < 1e-9)
    out2 = retention.pdf_retention(matches, threshold=0.95, card_r=card_r)
    check("no matches -> retention None", out2["retention"] is None)

    # digest stability: mod-only change keeps digest, hash change moves it
    d1 = retention.card_index_digest(cidx)
    cidx.mods[0] = 999
    check("digest ignores mods", retention.card_index_digest(cidx) == d1)
    cidx.hashes[0] = "different"
    check("digest tracks hashes", retention.card_index_digest(cidx) != d1)

    # matches.json roundtrip + invalidation (patch USER_FILES to tmp)
    retention.USER_FILES = tmp
    m = [(1, 0.8), (2, 0.4)]
    sig2 = ("voyage", "voyage-3-lite")
    src2 = (123, 456)
    retention.save_matches("Lecture 1", sig2, 2, src2, "digest1", "max", m)
    got = retention.load_matches("Lecture 1", sig2, 2, src2, "digest1", "max")
    check("matches roundtrip", got == [(1, 0.8), (2, 0.4)])
    check("matches invalid on digest",
          retention.load_matches("Lecture 1", sig2, 2, src2, "other", "max") is None)
    check("matches invalid on agg",
          retention.load_matches("Lecture 1", sig2, 2, src2, "digest1", "top3_mean") is None)
    check("matches invalid on dims",
          retention.load_matches("Lecture 1", sig2, 3, src2, "digest1", "max") is None)
    check("matches invalid on source sig",
          retention.load_matches("Lecture 1", sig2, 2, (9, 9), "digest1", "max") is None)

    # threshold prefs
    retention.set_threshold("Lecture 1", 0.42)
    check("threshold pref roundtrip",
          abs(retention.get_threshold("Lecture 1", {}) - 0.42) < 1e-9)
    check("threshold default from cfg",
          abs(retention.get_threshold("Other", {"pdf_match_threshold": 0.5}) - 0.5) < 1e-9)

    # card_retrievability against a fake col.db
    class FakeDB:
        def __init__(self, rows, revlog):
            self.rows = rows
            self.revlog = revlog
        def all(self, sql):
            if sql.startswith("select id, nid"):
                return self.rows
            return self.revlog

    class FakeCol:
        def __init__(self, rows, revlog):
            self.db = FakeDB(rows, revlog)

    now_ms = int(time.time() * 1000)
    day = 86400
    rows = [
        # cid, nid, type, ivl, data
        (11, 1, 2, 10, json.dumps({"s": 10.0, "d": 5.0, "dr": 0.9,
                                    "decay": 0.5, "lrt": time.time() - 10 * day})),
        (12, 1, 0, 0, ""),                                     # new card
        (13, 2, 2, 20, json.dumps({"s": 5.0, "d": 5.0})),      # FSRS, no lrt/decay
        (14, 3, 2, 8, "{}"),                                   # SM-2 reviewed
        (15, 4, 2, 8, ""),                                     # excluded nid
    ]
    revlog = [(13, now_ms - 5 * day * 1000), (14, now_ms - 4 * day * 1000)]
    cr = retention.card_retrievability(FakeCol(rows, revlog), {1, 2, 3})
    check("fsrs card: R(t=s)=0.9", abs(cr[1][0][0] - 0.9) < 1e-3, str(cr[1]))
    check("new card: R=0, is_new", cr[1][1] == (0.0, True))
    r13 = retention.fsrs_retrievability(5.0, 0.5, 5.0)
    check("lrt fallback via revlog", abs(cr[2][0][0] - r13) < 1e-3,
          f"{cr[2][0][0]} vs {r13}")
    r14 = retention.sm2_retrievability(8, 4.0)
    check("sm2 fallback", abs(cr[3][0][0] - r14) < 1e-3)
    check("excluded nid absent", 4 not in cr)

shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
