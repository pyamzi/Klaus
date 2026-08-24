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

# ------------------------------------- pdf_handler: atomic writes + recency

print("== pdf_handler: atomic writes ==")

awj_path = os.path.join(tmp, "atomic_test.json")
pdf_handler._atomic_write_json(awj_path, {"a": 1})
pdf_handler._atomic_write_json(awj_path, {"b": 2})
with open(awj_path, encoding="utf-8") as f:
    on_disk = json.load(f)
check("_atomic_write_json overwrites rather than merges", on_disk == {"b": 2}, str(on_disk))
check("_atomic_write_json leaves no tmp file behind",
      not any(n.startswith(".atomic_test.json.") for n in os.listdir(tmp)))

tabs_tmp = tempfile.mkdtemp(prefix="klaus_test_tabs_")
pdf_handler.save_open_tabs(tabs_tmp, ["Foo", "Bar"])
pdf_handler.touch_last_used(tabs_tmp, "Foo")
raw_tabs = pdf_handler._load_tabs_file(tabs_tmp)
check("pdf_tabs.json round-trips through the shared atomic writer (multi-writer merge)",
      raw_tabs.get("open") == ["Foo", "Bar"] and "Foo" in raw_tabs.get("last_used", {}),
      str(raw_tabs))
check("pdf_tabs.json has no leftover tmp file",
      not any(n.startswith(".pdf_tabs.json.") for n in os.listdir(tabs_tmp)))
shutil.rmtree(tabs_tmp, ignore_errors=True)

print("== pdf_handler: recency ordering ==")

# list_by_recency: an explicit last_used touch outranks mtime, and the
# untouched fallback reads contexts/<safe>.txt (fresh at ingest time) —
# NOT pdfs/<safe>.pdf, whose mtime shutil.copy2 preserves from the
# source file.
rec_tmp = tempfile.mkdtemp(prefix="klaus_test_recency_")
rec_ctx = os.path.join(rec_tmp, "contexts")
os.makedirs(rec_ctx)
for nm in ("Old", "Middle", "New"):
    with open(os.path.join(rec_ctx, nm + ".txt"), "w", encoding="utf-8") as f:
        f.write("x")
    time.sleep(0.01)
# "Old" is the stalest by ctx mtime but gets touched last -> must lead.
pdf_handler.touch_last_used(rec_tmp, "Old")
ranked = pdf_handler.list_by_recency(rec_tmp)
check("list_by_recency: last_used outranks mtime", ranked[0] == "Old", str(ranked))
check("list_by_recency: untouched entries fall back to ctx mtime, newest first",
      ranked[1:] == ["New", "Middle"], str(ranked))
check("list_by_recency: limit caps the result",
      pdf_handler.list_by_recency(rec_tmp, limit=1) == ["Old"])

# ensure_active_pdf must repair from the same last_used ranking, not an
# independent max-mtime scan: "Middle" is the mtime-newest context, but
# "Old" is the most recently USED one, and no active pointer is set yet.
repaired = pdf_handler.ensure_active_pdf(rec_tmp)
check("ensure_active_pdf repairs from last_used rather than mtime",
      repaired == "Old", str(repaired))
shutil.rmtree(rec_tmp, ignore_errors=True)

print("== pdf_handler: save_pdf touches last_used ==")

sp_tmp = tempfile.mkdtemp(prefix="klaus_test_savepdf_")
raw_pdf = os.path.join(sp_tmp, "raw.pdf")
with open(raw_pdf, "wb") as f:
    f.write(b"%PDF-1.4\n%%EOF")
t0 = time.time()
pdf_handler.save_pdf(sp_tmp, "Old Lecture", raw_pdf)
lu1 = pdf_handler.load_last_used(sp_tmp)
check("save_pdf touches last_used on first import",
      lu1.get("Old_Lecture", 0) >= t0, str(lu1))

time.sleep(0.05)
t1 = time.time()
pdf_handler.save_pdf(sp_tmp, "Old Lecture", raw_pdf)  # re-import, same basename
lu2 = pdf_handler.load_last_used(sp_tmp)
check("re-import bumps last_used forward (doesn't keep the stale timestamp)",
      lu2.get("Old_Lecture", 0) >= t1 > lu1["Old_Lecture"],
      f"{lu1} -> {lu2}")
shutil.rmtree(sp_tmp, ignore_errors=True)

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

    # global-apply (K-052 rework #2): clearing per-PDF overrides so a new
    # default actually reaches PDFs the user already tuned. Pouya's real
    # library had an override on EVERY pdf, so the Preferences slider
    # changed nothing visible — the exact bug this guards against.
    retention.set_threshold("Other", 0.6)
    names = retention.threshold_override_names()
    check("override_names lists every tuned PDF", len(names) == 2)
    prefs = retention._load_prefs()
    prefs["Keeper"] = {"threshold": 0.3, "tag": "!Library::Keeper"}
    pdf_handler._atomic_write_json(retention._prefs_path(), prefs)
    cleared = retention.clear_threshold_overrides()
    check("clear returns how many overrides went", cleared == 3)
    check("cleared PDFs now follow the cfg default",
          abs(retention.get_threshold("Lecture 1", {"pdf_match_threshold": 0.5}) - 0.5) < 1e-9)
    check("non-threshold keys survive the clear",
          retention._load_prefs().get("Keeper") == {"tag": "!Library::Keeper"})
    check("entries left empty are dropped entirely",
          "Other" not in retention._load_prefs())
    check("clear on an already-clean store is a zero no-op",
          retention.clear_threshold_overrides() == 0)
    # restore the fixture the downstream delete_context checks expect
    retention.forget_prefs("Keeper")
    retention.set_threshold("Lecture 1", 0.42)

    # prefs orphan cleanup: delete_context must reach prefs.json (a
    # SIBLING of the per-PDF dirs, so its own rmtree/unlink candidates
    # can never touch it) via the real lazy retention.forget_prefs hop —
    # not a stub, since aqt is stubbed by this point in the file.
    pdf_handler.delete_context(tmp, "Lecture 1")
    check("delete_context clears the prefs.json entry (no orphaned threshold)",
          abs(retention.get_threshold("Lecture 1", {}) - retention.DEFAULT_THRESHOLD) < 1e-9)
    check("prefs.json itself no longer has the entry",
          "Lecture_1" not in retention._load_prefs())

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

print("== threshold default migration (retention._migrate_default_threshold) ==")

_ret_mod = importlib.import_module("klausmate.retention")


def _mig(cfg):
    """Run the migration with the config write stubbed out."""
    import types as _t
    real_mw = _ret_mod.mw
    written = {}
    _ret_mod.mw = _t.SimpleNamespace(
        taskman=_t.SimpleNamespace(run_on_main=lambda fn: fn())
    )
    real_pkg = _ret_mod.curation._pkg
    _ret_mod.curation._pkg = lambda: _t.SimpleNamespace(
        write_config=lambda c: written.update(c)
    )
    try:
        return _ret_mod._migrate_default_threshold(cfg)
    finally:
        _ret_mod.mw = real_mw
        _ret_mod.curation._pkg = real_pkg


_D = _ret_mod.DEFAULT_THRESHOLD

check("current default is 0.75", _D == 0.75)
check(
    "a stored 0.35 (first shipped default) moves to the current default",
    _mig({"pdf_match_threshold": 0.35})["pdf_match_threshold"] == _D,
)
check(
    "a stored 0.55 moves too, even though the OLD one-shot guard already fired",
    _mig({"pdf_match_threshold": 0.55, "_threshold_default_migrated": True})[
        "pdf_match_threshold"
    ]
    == _D,
)
check(
    "a deliberate value is never touched",
    _mig({"pdf_match_threshold": 0.42})["pdf_match_threshold"] == 0.42,
)
check(
    "re-running at the same default is a no-op",
    _mig({"pdf_match_threshold": 0.42, "_threshold_default_applied": _D})[
        "pdf_match_threshold"
    ]
    == 0.42,
)
check(
    "the retired one-shot guard is scrubbed",
    "_threshold_default_migrated" not in _mig(
        {"pdf_match_threshold": 0.55, "_threshold_default_migrated": True}
    ),
)
check(
    "a garbage stored value does not crash or overwrite blindly",
    _mig({"pdf_match_threshold": "nonsense"}).get("pdf_match_threshold") == "nonsense",
)

# ------------------------------- library root + migration (K-070) --------
#
# Scratch dirs ONLY — never klausmate/user_files/. lib_user stands in for
# user_files_dir, lib_root for the chosen Library folder; both are plain
# tempfile.mkdtemp() dirs cleaned up at the end of this section.

print("== library root + migration (K-070) ==")

lib_user = tempfile.mkdtemp(prefix="klaus_test_libuser_")
lib_root = tempfile.mkdtemp(prefix="klaus_test_libroot_")
lib_ctx = os.path.join(lib_user, "contexts")
lib_pdfs = os.path.join(lib_user, "pdfs")
os.makedirs(lib_ctx)
os.makedirs(lib_pdfs)


def _lib_mk_pdf(safe):
    with open(os.path.join(lib_ctx, safe + ".txt"), "w", encoding="utf-8") as f:
        f.write("x")
    with open(os.path.join(lib_pdfs, safe + ".pdf"), "wb") as f:
        f.write(b"%PDF-1.4\n%%EOF")


_lib_mk_pdf("Lecture_A")
_lib_mk_pdf("Lecture_B")
_lib_mk_pdf("Lecture_C")

# -- get_library_root --
check("get_library_root: unset cfg -> None", pdf_handler.get_library_root({}) is None)
check("get_library_root: non-dict cfg -> None", pdf_handler.get_library_root(None) is None)
check("get_library_root: blank string -> None",
      pdf_handler.get_library_root({"library_root": "  "}) is None)
check("get_library_root: reads the configured path",
      pdf_handler.get_library_root({"library_root": lib_root}) == lib_root)

# -- mapping round-trip --
check("library_map starts empty", pdf_handler.load_library_map(lib_user) == {})
pdf_handler.save_library_map(lib_user, {"Lecture_A": "Foo/bar.pdf"})
check("library_map round-trips through save/load",
      pdf_handler.load_library_map(lib_user) == {"Lecture_A": "Foo/bar.pdf"})
with open(os.path.join(lib_user, "library_map.json"), "w", encoding="utf-8") as f:
    json.dump({"Lecture_A": "ok.pdf", "Lecture_B": 123, "Lecture_C": ""}, f)
check("library_map load drops non-string/empty values",
      pdf_handler.load_library_map(lib_user) == {"Lecture_A": "ok.pdf"})
pdf_handler.save_library_map(lib_user, {})  # reset before migration tests below

# -- unmapped fallback to legacy pdfs/ path --
legacy_a = os.path.join(lib_pdfs, "Lecture_A.pdf")
check("pdf_path_for falls back to legacy pdfs/<safe>.pdf when unmapped",
      pdf_handler.pdf_path_for(lib_user, "Lecture A", root=lib_root) == legacy_a)
check("pdf_path_for (no root passed) still resolves the legacy file",
      pdf_handler.pdf_path_for(lib_user, "Lecture A") == legacy_a)

# -- migration moves + maps --
folders = {
    "Lecture_A": {"folder": "Anatomy/Week 3", "display": "Renal Physiology (Dr. K).pdf"},
    "Lecture_B": {"folder": None, "display": "Lecture B"},
    # Lecture_C deliberately has no drive_store entry (orphan -> root, safe name).
}
mig1 = pdf_handler.migrate_to_root(lib_user, lib_root, folders)
check("migration moves every stored pdf",
      set(mig1["moved"]) == {"Lecture_A", "Lecture_B", "Lecture_C"}, str(mig1))
check("migration reports no failures", mig1["failed"] == {}, str(mig1))

expect_a = os.path.join(lib_root, "Anatomy", "Week 3", "Renal Physiology (Dr. K).pdf")
mapped1 = pdf_handler.load_library_map(lib_user)
check("mapped path follows folder + display name",
      os.path.join(lib_root, mapped1["Lecture_A"]) == expect_a, str(mapped1))
check("root-level pdf (no folder) mapped under the root itself",
      mapped1["Lecture_B"] == "Lecture B.pdf", str(mapped1))
check("orphan pdf (no drive_store entry) falls back to its safe name",
      mapped1["Lecture_C"] == "Lecture_C.pdf", str(mapped1))
check("destination file exists after the move", os.path.isfile(expect_a))
check("legacy pdfs/ copy is gone after a successful move",
      not os.path.isfile(os.path.join(lib_pdfs, "Lecture_A.pdf")))

# -- pdf_path_for after migration resolves to the root path --
check("pdf_path_for resolves the migrated file against an explicit root",
      pdf_handler.pdf_path_for(lib_user, "Lecture A", root=lib_root) == expect_a)
check("pdf_path_for with no root can no longer find the (moved) file",
      pdf_handler.pdf_path_for(lib_user, "Lecture A") is None)

# -- collision suffixing: same folder + display name -> numeric suffix --
_lib_mk_pdf("Lecture_D")
folders_collide = dict(folders)
folders_collide["Lecture_D"] = {
    "folder": "Anatomy/Week 3", "display": "Renal Physiology (Dr. K).pdf",
}
mig2 = pdf_handler.migrate_to_root(lib_user, lib_root, folders_collide)
check("colliding file still gets moved", "Lecture_D" in mig2["moved"], str(mig2))
mapped2 = pdf_handler.load_library_map(lib_user)
check("colliding display name gets a ' (1)' suffix instead of overwriting",
      mapped2["Lecture_D"].endswith("Renal Physiology (Dr. K) (1).pdf"),
      mapped2.get("Lecture_D"))
check("both colliding files exist on disk as distinct paths",
      mapped2["Lecture_A"] != mapped2["Lecture_D"]
      and os.path.isfile(os.path.join(lib_root, mapped2["Lecture_D"]))
      and os.path.isfile(os.path.join(lib_root, mapped2["Lecture_A"])))

# -- failure mid-list: earlier moves stay mapped, later ones still proceed,
#    the failed file's source is left untouched --
_lib_mk_pdf("Lecture_G")
_lib_mk_pdf("Lecture_H")
_lib_mk_pdf("Lecture_I")
folders_fail = {
    "Lecture_G": {"folder": None, "display": "G.pdf"},
    "Lecture_H": {"folder": "Broken", "display": "H.pdf"},
    "Lecture_I": {"folder": None, "display": "I.pdf"},
}
_real_copy2 = pdf_handler.shutil.copy2


def _flaky_copy2(src, dst, *a, **k):
    if "Lecture_H" in src:
        raise OSError("simulated disk failure")
    return _real_copy2(src, dst, *a, **k)


pdf_handler.shutil.copy2 = _flaky_copy2
try:
    mig3 = pdf_handler.migrate_to_root(lib_user, lib_root, folders_fail)
finally:
    pdf_handler.shutil.copy2 = _real_copy2

check("earlier item (G) moved despite a later failure",
      "Lecture_G" in mig3["moved"], str(mig3))
check("failing item (H) recorded as failed, not moved",
      "Lecture_H" in mig3["failed"] and "Lecture_H" not in mig3["moved"], str(mig3))
check("later item (I) still moved after the mid-list failure",
      "Lecture_I" in mig3["moved"], str(mig3))
check("failed item's legacy source is left untouched",
      os.path.isfile(os.path.join(lib_pdfs, "Lecture_H.pdf")))
mapped3 = pdf_handler.load_library_map(lib_user)
check("failed item has no mapping entry", "Lecture_H" not in mapped3, str(mapped3))
check("succeeded items on either side of the failure ARE mapped",
      {"Lecture_G", "Lecture_I"} <= set(mapped3), str(mapped3))

# -- re-run resumes: retries the failure, leaves completed ones alone --
mig4 = pdf_handler.migrate_to_root(lib_user, lib_root, folders_fail)
check("re-run completes the previously-failed file",
      "Lecture_H" in mig4["moved"], str(mig4))
check("re-run skips already-migrated files instead of re-moving them",
      "Lecture_G" in mig4["skipped"] and "Lecture_G" not in mig4["moved"], str(mig4))
mapped4 = pdf_handler.load_library_map(lib_user)
check("resumed file is now mapped", "Lecture_H" in mapped4, str(mapped4))
check("resumed file's legacy source is finally removed",
      not os.path.isfile(os.path.join(lib_pdfs, "Lecture_H.pdf")))

shutil.rmtree(lib_user, ignore_errors=True)
shutil.rmtree(lib_root, ignore_errors=True)



print("== library root: CHANGING the root moves already-migrated PDFs (K-070 rework) ==")
# Falsifies the review finding: migrate_to_root only ever looked for
# LEGACY pdfs/<safe>.pdf sources, so once a PDF lived under root A the
# Preferences "Change..." button reported it 'skipped', left the file in
# A, and pointed the mapping at a path that does not exist under B —
# pdf_path_for then returns None and the PDF is unopenable. Reproduced
# in scratch dirs before the fix; this pins it.
cr_user = tempfile.mkdtemp(prefix="klaus_test_chroot_user_")
cr_a = tempfile.mkdtemp(prefix="klaus_test_chroot_A_")
cr_b = tempfile.mkdtemp(prefix="klaus_test_chroot_B_")
os.makedirs(os.path.join(cr_user, "contexts"))
os.makedirs(os.path.join(cr_user, "pdfs"))
for _safe in ("Anat_1", "Anat_2"):
    with open(os.path.join(cr_user, "contexts", _safe + ".txt"), "w", encoding="utf-8") as f:
        f.write("x")
    with open(os.path.join(cr_user, "pdfs", _safe + ".pdf"), "wb") as f:
        f.write(b"%PDF-1.4\n" + _safe.encode() + b"\n%%EOF")

_cr_folders = {
    "Anat_1": {"folder": "Anatomy", "display": "Anatomy One.pdf"},
    "Anat_2": {"folder": None, "display": "Anat Two.pdf"},
}
_r_a = pdf_handler.migrate_to_root(cr_user, cr_a, _cr_folders)
check(
    "setup: both PDFs migrate into root A",
    sorted(_r_a["moved"]) == ["Anat_1", "Anat_2"],
    str(_r_a),
)

# The actual change-root call: old root A -> new root B.
_r_b = pdf_handler.migrate_to_root(cr_user, cr_b, _cr_folders, old_root=cr_a)
check(
    "changing the root MOVES the already-migrated PDFs (not 'skipped')",
    sorted(_r_b["moved"]) == ["Anat_1", "Anat_2"],
    str(_r_b),
)
check(
    "the PDFs now resolve under the NEW root",
    pdf_handler.pdf_path_for(cr_user, "Anat_1", root=cr_b) is not None
    and pdf_handler.pdf_path_for(cr_user, "Anat_2", root=cr_b) is not None,
)
check(
    "the folder layout is preserved under the new root",
    os.path.isfile(os.path.join(cr_b, "Anatomy", "Anatomy One.pdf")),
)
check(
    "nothing is left stranded in the old root",
    not os.path.isfile(os.path.join(cr_a, "Anatomy", "Anatomy One.pdf"))
    and not os.path.isfile(os.path.join(cr_a, "Anat Two.pdf")),
)
check(
    "the stored mapping is rewritten relative to the new root",
    pdf_handler.load_library_map(cr_user).get("Anat_1")
    == os.path.join("Anatomy", "Anatomy One.pdf"),
)
# Re-running the same change is a structural no-op (resumability).
_r_again = pdf_handler.migrate_to_root(cr_user, cr_b, _cr_folders, old_root=cr_a)
check(
    "re-running the same change-root is a no-op",
    _r_again["moved"] == [] and not _r_again["failed"],
    str(_r_again),
)
# A file already sitting at a PDF's mapped path under the new root is
# ADOPTED, not duplicated. This is the resumability property (an
# interrupted run leaves files exactly there) and it cannot be told
# apart from a stranger's file of the same name without hashing — so it
# is pinned deliberately rather than left to chance. Consequence worth
# knowing: pointing the Library at a folder that already contains a file
# at that relative path adopts it and leaves the original in the old
# root. Flagged on K-070 for Pouya.
cr_c = tempfile.mkdtemp(prefix="klaus_test_chroot_C_")
os.makedirs(os.path.join(cr_c, "Anatomy"), exist_ok=True)
with open(os.path.join(cr_c, "Anatomy", "Anatomy One.pdf"), "wb") as f:
    f.write(b"pre-existing")
_r_c = pdf_handler.migrate_to_root(cr_user, cr_c, _cr_folders, old_root=cr_b)
check(
    "a file already at the mapped path in the new root is adopted, not duplicated",
    "Anat_1" in _r_c["skipped"]
    and open(os.path.join(cr_c, "Anatomy", "Anatomy One.pdf"), "rb").read()
    == b"pre-existing"
    and not os.path.isfile(os.path.join(cr_c, "Anatomy", "Anatomy One (1).pdf")),
    str(_r_c),
)

# A GENUINE collision through the change-root path: two PDFs that share
# a display name. The second one's destination filename is taken by the
# first, so it must be suffixed — never overwritten.
cl_user = tempfile.mkdtemp(prefix="klaus_test_clash_user_")
cl_a = tempfile.mkdtemp(prefix="klaus_test_clash_A_")
cl_b = tempfile.mkdtemp(prefix="klaus_test_clash_B_")
os.makedirs(os.path.join(cl_user, "contexts"))
os.makedirs(os.path.join(cl_user, "pdfs"))
for _safe, _body in (("Dup_1", b"first"), ("Dup_2", b"second")):
    with open(os.path.join(cl_user, "contexts", _safe + ".txt"), "w", encoding="utf-8") as f:
        f.write("x")
    with open(os.path.join(cl_user, "pdfs", _safe + ".pdf"), "wb") as f:
        f.write(b"%PDF-1.4\n" + _body + b"\n%%EOF")

_cl_folders = {
    "Dup_1": {"folder": "Shared", "display": "Same Name.pdf"},
    "Dup_2": {"folder": "Shared", "display": "Same Name.pdf"},
}
pdf_handler.migrate_to_root(cl_user, cl_a, _cl_folders)
_cl_b = pdf_handler.migrate_to_root(cl_user, cl_b, _cl_folders, old_root=cl_a)
check(
    "both same-named PDFs survive a root change as distinct files",
    sorted(_cl_b["moved"]) == ["Dup_1", "Dup_2"]
    and os.path.isfile(os.path.join(cl_b, "Shared", "Same Name.pdf"))
    and os.path.isfile(os.path.join(cl_b, "Shared", "Same Name (1).pdf")),
    str(_cl_b),
)
_cl_map = pdf_handler.load_library_map(cl_user)
check(
    "each keeps its own mapping and resolves independently",
    _cl_map["Dup_1"] != _cl_map["Dup_2"]
    and pdf_handler.pdf_path_for(cl_user, "Dup_1", root=cl_b) is not None
    and pdf_handler.pdf_path_for(cl_user, "Dup_2", root=cl_b) is not None,
)
check(
    "neither file's bytes were overwritten by the other",
    open(pdf_handler.pdf_path_for(cl_user, "Dup_1", root=cl_b), "rb").read()
    != open(pdf_handler.pdf_path_for(cl_user, "Dup_2", root=cl_b), "rb").read(),
)


print("== two-way folder sync (K-073): plan_rescan is pure and conservative ==")
_pr = pdf_handler.plan_rescan
check("all in place -> no-op",
      _pr({"A": "x/a.pdf"}, ["x/a.pdf"])
      == {"moves": {}, "missing": [], "new": [], "ingestable": [], "ambiguous": False})
check("unique basename elsewhere -> MOVE",
      _pr({"A": "x/a.pdf"}, ["y/a.pdf"])["moves"] == {"A": "y/a.pdf"})
check("two missing share a basename -> neither is guessed",
      _pr({"A": "x/n.pdf", "B": "y/n.pdf"}, ["z/n.pdf", "keep/other stuff.pdf"])["moves"] == {})
check("exactly-one-missing / exactly-one-new -> RENAME",
      _pr({"A": "a.pdf", "B": "b.pdf"}, ["b.pdf", "renamed.pdf"])["moves"] == {"A": "renamed.pdf"})
_amb = _pr({"A": "a.pdf", "B": "b.pdf"}, ["c.pdf", "d.pdf"])
check("two renames at once -> ambiguous, no moves, no ingest",
      _amb["ambiguous"] and _amb["moves"] == {} and _amb["ingestable"] == [],
      str(_amb))
check("deletion with nothing new -> reported missing only",
      _pr({"A": "a.pdf"}, []) == {"moves": {}, "missing": ["A"], "new": [],
                                  "ingestable": [], "ambiguous": False})
_clean_new = _pr({"A": "a.pdf"}, ["a.pdf", "fresh/drop.pdf"])
check("new file with nothing missing -> ingestable",
      _clean_new["ingestable"] == ["fresh/drop.pdf"] and not _clean_new["ambiguous"])
_mixed = _pr({"A": "gone.pdf"}, ["maybe-renamed.pdf", "maybe-new.pdf"])
check("new files while a rename is unresolved are NOT ingestable",
      _mixed["ambiguous"] and _mixed["ingestable"] == [])
check("move recognised by basename even alongside other new files",
      _pr({"A": "x/lec.pdf"}, ["y/lec.pdf", "brand/new.pdf"])["moves"] == {"A": "y/lec.pdf"})

print("== two-way folder sync (K-073): rescan_root applies to map + tree ==")
drive_store = importlib.import_module("klausmate.drive_store")
tw_user = tempfile.mkdtemp(prefix="klaus_test_twoway_user_")
tw_root = tempfile.mkdtemp(prefix="klaus_test_twoway_root_")
os.makedirs(os.path.join(tw_user, "contexts"))
os.makedirs(os.path.join(tw_user, "pdfs"))
for _safe in ("Sync_A", "Sync_B"):
    with open(os.path.join(tw_user, "contexts", _safe + ".txt"), "w", encoding="utf-8") as f:
        f.write("x")
    with open(os.path.join(tw_user, "pdfs", _safe + ".pdf"), "wb") as f:
        f.write(b"%PDF-1.4\n" + _safe.encode() + b"\n%%EOF")
drive_store.record_import(tw_user, "Sync_A", "Sync A.pdf")
drive_store.record_import(tw_user, "Sync_B", "Sync B.pdf")
drive_store.add_folder(tw_user, "Anatomy")
drive_store.set_folder(tw_user, "Sync_A", "Anatomy")
_tw_folders = drive_store.load(tw_user)["pdfs"]
pdf_handler.migrate_to_root(tw_user, tw_root, _tw_folders)

# Finder MOVE: Anatomy/Sync A.pdf -> Histology/Week 2/Sync A.pdf
os.makedirs(os.path.join(tw_root, "Histology", "Week 2"))
os.rename(os.path.join(tw_root, "Anatomy", "Sync A.pdf"),
          os.path.join(tw_root, "Histology", "Week 2", "Sync A.pdf"))
_s1 = pdf_handler.rescan_root(tw_user, tw_root, drive_store.load(tw_user)["pdfs"])
check("move applied to mapping", pdf_handler.load_library_map(tw_user)["Sync_A"]
      == os.path.join("Histology", "Week 2", "Sync A.pdf"), str(_s1))
check("move applied to the tree",
      drive_store.load(tw_user)["pdfs"]["Sync_A"]["folder"] == "Histology/Week 2")
check("a plain move leaves the display text alone",
      drive_store.load(tw_user)["pdfs"]["Sync_A"]["display"] == "Sync A.pdf")
check("PDF still resolves after the move",
      pdf_handler.pdf_path_for(tw_user, "Sync_A", root=tw_root) is not None)

# Finder RENAME: Sync B.pdf -> Better Name.pdf (same directory)
os.rename(os.path.join(tw_root, "Sync B.pdf"),
          os.path.join(tw_root, "Better Name.pdf"))
_s2 = pdf_handler.rescan_root(tw_user, tw_root, drive_store.load(tw_user)["pdfs"])
check("rename applied to mapping",
      pdf_handler.load_library_map(tw_user)["Sync_B"] == "Better Name.pdf", str(_s2))
check("rename updates the display",
      drive_store.load(tw_user)["pdfs"]["Sync_B"]["display"] == "Better Name.pdf")
check("rescan with nothing changed is a no-op",
      pdf_handler.rescan_root(tw_user, tw_root, drive_store.load(tw_user)["pdfs"])["moved"] == [])

# Finder DELETE: report, never destroy Klaus data.
os.remove(os.path.join(tw_root, "Better Name.pdf"))
_s3 = pdf_handler.rescan_root(tw_user, tw_root, drive_store.load(tw_user)["pdfs"])
check("deleted file is reported missing", _s3["missing"] == ["Sync_B"], str(_s3))
check("deletion keeps the mapping and the context",
      "Sync_B" in pdf_handler.load_library_map(tw_user)
      and os.path.isfile(os.path.join(tw_user, "contexts", "Sync_B.txt")))

print("== two-way folder sync (K-073): dropping a PDF into the folder ingests in place ==")
os.makedirs(os.path.join(tw_root, "Drops"), exist_ok=True)
with open(os.path.join(tw_root, "Drops", "Fresh Lecture.pdf"), "wb") as f:
    f.write(b"%PDF-1.4\nfresh\n%%EOF")
# Restore Sync_B first so the new file is unambiguous.
with open(os.path.join(tw_root, "Better Name.pdf"), "wb") as f:
    f.write(b"%PDF-1.4\nSync_B\n%%EOF")
_orig_extract = pdf_handler.extract_pages
pdf_handler.extract_pages = lambda p: ["synthetic page text"]
try:
    _s4 = pdf_handler.rescan_root(tw_user, tw_root, drive_store.load(tw_user)["pdfs"])
finally:
    pdf_handler.extract_pages = _orig_extract
check("dropped PDF is ingested", _s4["ingested"] == ["Fresh_Lecture"], str(_s4))
check("ingest maps the file WHERE IT IS (no copy made)",
      pdf_handler.load_library_map(tw_user)["Fresh_Lecture"]
      == os.path.join("Drops", "Fresh Lecture.pdf")
      and not os.path.isfile(os.path.join(tw_user, "pdfs", "Fresh_Lecture.pdf")))
check("ingest wrote the context and the tree entry",
      os.path.isfile(os.path.join(tw_user, "contexts", "Fresh_Lecture.txt"))
      and drive_store.load(tw_user)["pdfs"]["Fresh_Lecture"]["folder"] == "Drops")
check("ingested PDF resolves through pdf_path_for",
      pdf_handler.pdf_path_for(tw_user, "Fresh_Lecture", root=tw_root) is not None)

print("== single-copy imports (K-073): save_pdf writes straight into the root ==")
sc_user = tempfile.mkdtemp(prefix="klaus_test_single_user_")
sc_root = tempfile.mkdtemp(prefix="klaus_test_single_root_")
sc_src = os.path.join(tempfile.mkdtemp(prefix="klaus_test_single_src_"), "My Notes.pdf")
with open(sc_src, "wb") as f:
    f.write(b"%PDF-1.4\nv1\n%%EOF")
_orig_extract = pdf_handler.extract_pages
pdf_handler.extract_pages = lambda p: ["page"]
try:
    _info = pdf_handler.save_pdf(sc_user, "My Notes", sc_src, root=sc_root)
    check("import lands in the root under its original filename",
          os.path.isfile(os.path.join(sc_root, "My Notes.pdf")), str(_info))
    check("NO copy appears in the legacy pdfs/ store",
          not os.path.isfile(os.path.join(sc_user, "pdfs", _info["name"] + ".pdf")))
    check("import is mapped",
          pdf_handler.load_library_map(sc_user)[_info["name"]] == "My Notes.pdf")
    # Re-import the same name: replace in place, never a second copy.
    with open(sc_src, "wb") as f:
        f.write(b"%PDF-1.4\nv2 longer body\n%%EOF")
    pdf_handler.save_pdf(sc_user, "My Notes", sc_src, root=sc_root)
    check("re-import replaces the SAME file in place",
          open(os.path.join(sc_root, "My Notes.pdf"), "rb").read()
          == b"%PDF-1.4\nv2 longer body\n%%EOF"
          and not os.path.isfile(os.path.join(sc_root, "My Notes (1).pdf")))
    # Root unavailable -> graceful legacy fallback, import never fails.
    _info2 = pdf_handler.save_pdf(
        sc_user, "Other Deck", sc_src, root=os.path.join(sc_root, "gone-subdir")
    )
    check("missing root falls back to the legacy store",
          os.path.isfile(os.path.join(sc_user, "pdfs", _info2["name"] + ".pdf")))
finally:
    pdf_handler.extract_pages = _orig_extract


print("== rescan repairs tree drift even when the mapping never changed (live bug) ==")
# Pouya's exact 18:07 state: migration had already synced the mapping to
# disk, then the stale !Library tags pulled the TREE back to the old
# layout. A moves-only rescan no-ops forever (the mapping is consistent)
# while tree and Finder disagree. The tree must follow the mapping for
# every entry, unconditionally.
dr_user = tempfile.mkdtemp(prefix="klaus_test_drift_user_")
dr_root = tempfile.mkdtemp(prefix="klaus_test_drift_root_")
os.makedirs(os.path.join(dr_user, "contexts"))
for _safe in ("Bio", "Meas"):
    with open(os.path.join(dr_user, "contexts", _safe + ".txt"), "w", encoding="utf-8") as f:
        f.write("x")
os.makedirs(os.path.join(dr_root, "Bootcamp"))
with open(os.path.join(dr_root, "Bootcamp", "Bio.pdf"), "wb") as f:
    f.write(b"%PDF")
with open(os.path.join(dr_root, "Meas.pdf"), "wb") as f:
    f.write(b"%PDF")
# Mapping already matches disk...
pdf_handler.save_library_map(dr_user, {"Bio": os.path.join("Bootcamp", "Bio.pdf"),
                                       "Meas": "Meas.pdf"})
# ...but the tree says the OPPOSITE (stale-tag layout).
drive_store.record_import(dr_user, "Bio", "Bio.pdf")
drive_store.record_import(dr_user, "Meas", "Meas.pdf")
drive_store.set_folder(dr_user, "Meas", "Bootcamp")
_dr = pdf_handler.rescan_root(dr_user, dr_root, drive_store.load(dr_user)["pdfs"])
check("no moves planned (mapping was already consistent)", _dr["moved"] == [], str(_dr))
check("tree drift is repaired anyway",
      sorted(_dr["tree_changed"]) == ["Bio", "Meas"], str(_dr))
_dr_tree = drive_store.load(dr_user)["pdfs"]
check("tree now matches the disk, both directions",
      _dr_tree["Bio"]["folder"] == "Bootcamp" and _dr_tree["Meas"]["folder"] is None)
check("repaired safes are handed to the tag sync (tree_changed drives tags)",
      set(_dr["tree_changed"]) == {"Bio", "Meas"})
_dr2 = pdf_handler.rescan_root(dr_user, dr_root, drive_store.load(dr_user)["pdfs"])
check("second rescan is fully quiet (converged)",
      _dr2["moved"] == [] and _dr2["tree_changed"] == [])


print("== Anki -> disk file moves (K-075) ==")
ad_user = tempfile.mkdtemp(prefix="klaus_test_ad_user_")
ad_root = tempfile.mkdtemp(prefix="klaus_test_ad_root_")
os.makedirs(os.path.join(ad_user, "contexts"))
os.makedirs(os.path.join(ad_root, "Anatomy"))
with open(os.path.join(ad_root, "Lec One.pdf"), "wb") as f:
    f.write(b"%PDF-one")
with open(os.path.join(ad_root, "Anatomy", "Lec Two.pdf"), "wb") as f:
    f.write(b"%PDF-two")
pdf_handler.save_library_map(ad_user, {"Lec_One": "Lec One.pdf",
                                       "Lec_Two": os.path.join("Anatomy", "Lec Two.pdf")})

_m1 = pdf_handler.move_mapped_file(ad_user, ad_root, "Lec_One", "Anatomy/Week 1")
check("tree move relocates the file on disk",
      _m1 == os.path.join("Anatomy", "Week 1", "Lec One.pdf")
      and os.path.isfile(os.path.join(ad_root, "Anatomy", "Week 1", "Lec One.pdf"))
      and not os.path.isfile(os.path.join(ad_root, "Lec One.pdf")), str(_m1))
check("move to root works too",
      pdf_handler.move_mapped_file(ad_user, ad_root, "Lec_Two", None) == "Lec Two.pdf"
      and os.path.isfile(os.path.join(ad_root, "Lec Two.pdf")))
check("already-in-place move is a no-op returning the rel",
      pdf_handler.move_mapped_file(ad_user, ad_root, "Lec_Two", None) == "Lec Two.pdf")
check("unmapped safe -> None, nothing thrown",
      pdf_handler.move_mapped_file(ad_user, ad_root, "Ghost", "Anywhere") is None)
# Collision: another file already holds the destination name.
with open(os.path.join(ad_root, "Anatomy", "Week 1", "Lec Two.pdf"), "wb") as f:
    f.write(b"squatter")
_m2 = pdf_handler.move_mapped_file(ad_user, ad_root, "Lec_Two", "Anatomy/Week 1")
check("destination collision suffixes, never overwrites",
      _m2 == os.path.join("Anatomy", "Week 1", "Lec Two (1).pdf")
      and open(os.path.join(ad_root, "Anatomy", "Week 1", "Lec Two.pdf"), "rb").read() == b"squatter")

print("== Anki -> disk renames (K-075) ==")
_r1 = pdf_handler.rename_mapped_file(ad_user, ad_root, "Lec_One", "Renamed Lecture")
check("display rename renames the file (with .pdf appended)",
      _r1 == os.path.join("Anatomy", "Week 1", "Renamed Lecture.pdf")
      and os.path.isfile(os.path.join(ad_root, "Anatomy", "Week 1", "Renamed Lecture.pdf")))
check("same-name rename is a no-op",
      pdf_handler.rename_mapped_file(ad_user, ad_root, "Lec_One", "Renamed Lecture.pdf") == _r1)

print("== Anki -> disk folder renames (K-075) ==")
check("folder rename moves the directory and rewrites mapping rels",
      pdf_handler.rename_mapped_folder(ad_user, ad_root, "Anatomy/Week 1", "Anatomy/Intro Week")
      and os.path.isdir(os.path.join(ad_root, "Anatomy", "Intro Week"))
      and pdf_handler.load_library_map(ad_user)["Lec_One"]
      == os.path.join("Anatomy", "Intro Week", "Renamed Lecture.pdf"))
os.makedirs(os.path.join(ad_root, "Clash"))
check("rename refuses to merge into an existing directory",
      pdf_handler.rename_mapped_folder(ad_user, ad_root, "Anatomy", "Clash") is False
      and os.path.isdir(os.path.join(ad_root, "Anatomy")))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
