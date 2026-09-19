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

ADDON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "klausmate"
)
APP_PACKAGES = "/Applications/Anki.app/Contents/Resources/app_packages"

# Synthetic package so relative imports inside the modules resolve.
pkg = types.ModuleType("klausmate")
pkg.__path__ = [ADDON]
pkg.__package__ = "klausmate"
sys.modules["klausmate"] = pkg

import importlib

# Vendored pypdf needs typing_extensions, which this machine's python3.9
# does not ship — shim it BEFORE pdf_handler's guarded import so
# BAKE_AVAILABLE matches the Anki runtime (py3.13 has it) instead of
# silently disabling every bake-path test.
try:
    import typing_extensions  # noqa: F401
except ImportError:
    import typing as _typing

    class _TESub:
        def __getitem__(self, _i):
            return _typing.Any

        def __call__(self, *a, **k):
            return _typing.Any

    class _TEModule(types.ModuleType):
        def __getattr__(self, n):
            return getattr(_typing, n, _TESub())

    sys.modules["typing_extensions"] = _TEModule("typing_extensions")

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
# OpenAI is the only embedding provider now (K-222/Task 2) — Voyage and
# Ollama are gone from embeddings.py entirely, and provider_name is a
# constant function kept only so existing callers still compile and run.
check("openai is the only provider, for any cfg",
      embeddings.provider_name({}) == "openai")
check("an unrecognized/legacy provider key changes nothing — always openai",
      embeddings.provider_name({"embedding_provider": "banana"}) == "openai")
check("an explicit ollama/voyage request is ignored too — always openai",
      embeddings.provider_name({"embedding_provider": "ollama"}) == "openai")
check("openai default model is text-embedding-3-large",
      embeddings.embedding_model({}) == "text-embedding-3-large")
check("signature carries dims, so a width change invalidates the index",
      embeddings.index_signature({}) == ("openai", "text-embedding-3-large", 0))
check("dims ARE sent for text-embedding-3-large — it's Matryoshka/dimension-capable",
      embeddings.index_signature(
          {"embedding_provider": "openai", "embedding_dimensions": 1024}
      )[2] == 1024)
# An index built at one width cannot be ranked against another, so the
# width has to reach check_signature — not merely be recorded.
_ix = card_index.empty_index("openai", "text-embedding-3-large")
_ix.dims = 1024
check("an index matches when the requested width is the one it was built at",
      card_index.check_signature(_ix, ("openai", "text-embedding-3-large", 1024)))
check("a DIFFERENT requested width forces a rebuild",
      not card_index.check_signature(_ix, ("openai", "text-embedding-3-large", 3072)))
check("width 0 means 'the model's default' and cannot disagree with an "
      "index that already has one",
      card_index.check_signature(_ix, ("openai", "text-embedding-3-large", 0)))
check("a two-tuple signature still works — existing callers are unbroken",
      card_index.check_signature(_ix, ("openai", "text-embedding-3-large")))
check("provider/model mismatch still wins regardless of width",
      not card_index.check_signature(_ix, ("voyage", "voyage-3-lite", 1024)))

# stats_from_disk has TWO exits and its callers cannot see which one they
# got. A missing or corrupt index is exactly when a caller is most likely
# to be probing, so the failure dict has to answer every key the success
# dict does — or stats["dims"] raises KeyError on the one path that needed
# an answer most. The success branch once listed "dims" TWICE and the
# failure branch not at all. pdf_index.stats_from_disk is the model: same
# keys out of both exits.
def _failure_exit(fn, path, ref_keys, payload=None, manifest=None):
    """Write ``payload`` as the manifest (when given), call ``fn(path)`` and
    return (ok, why): ok iff it took the FAILURE exit with ``ref_keys``
    intact. Caught so a regression records a FAIL instead of aborting the
    ~170 checks below — the defect under test IS an escaping exception."""
    if payload is not None:
        with open(os.path.join(path, manifest), "w", encoding="utf-8") as f:
            f.write(payload)
    try:
        st = fn(path)
    except Exception as exc:  # noqa: BLE001
        return False, f"RAISED {exc!r}"
    return set(st) == set(ref_keys) and not st["exists"], repr(st)


_sfd_tmp = tempfile.mkdtemp()
_sfd_dir = os.path.join(_sfd_tmp, "card_index")
_sfd_ix = card_index.empty_index("voyage", "voyage-3-lite", 1024)
card_index.save(_sfd_ix, _sfd_dir)
_sfd_ok = card_index.stats_from_disk(_sfd_dir)
check("stats_from_disk: a real manifest reports exists + its width",
      _sfd_ok["exists"] and _sfd_ok["dims"] == 1024, repr(_sfd_ok))
# stats_from_disk has TWO exits and its callers cannot see which one they
# got, so the failure dict must answer every key the success dict does —
# the success branch once listed "dims" TWICE and the failure branch not
# at all, and stats["dims"] raised on exactly the missing-index case.
_sfd_missing = card_index.stats_from_disk(os.path.join(_sfd_tmp, "no-such-dir"))
check("stats_from_disk: a MISSING index returns the same key set as a "
      "present one, and stats['dims'] answers 0 rather than raising",
      set(_sfd_missing) == set(_sfd_ok)
      and _sfd_missing["dims"] == 0 and not _sfd_missing["exists"],
      f"success={sorted(_sfd_ok)} failure={sorted(_sfd_missing)}")
# Every OTHER way a manifest can fail to be one takes the same exit with
# the same keys: an older INDEX_VERSION (the realistic upgrade path),
# non-JSON text, and valid JSON that is NOT an object — a truncated write
# can leave "null", and m.get() on it used to raise straight through into
# Preferences' three unguarded stats["exists"] reads.
with open(os.path.join(_sfd_dir, card_index.MANIFEST_FILE), encoding="utf-8") as f:
    _sfd_m = json.load(f)
_sfd_stale_payload = json.dumps({**_sfd_m, "version": card_index.INDEX_VERSION + 1})
for _label, _payload in (("a version-mismatched manifest", _sfd_stale_payload),
                         ("a CORRUPT (non-JSON) manifest", "{not json"),
                         ("a manifest of null", "null"),
                         ("a manifest of []", "[]"),
                         ("a manifest of a bare string", '"str"')):
    check(f"card_index.stats_from_disk: {_label} takes the failure exit "
          "with every key intact",
          *_failure_exit(card_index.stats_from_disk, _sfd_dir, _sfd_ok,
                         payload=_payload, manifest=card_index.MANIFEST_FILE))

# card_index.load and load_row_map answer None on failure, not a stats
# dict — same shared bug class (K-181), different exit shape, so a
# separate helper: ok iff the call returned None rather than raising.
def _none_on_corrupt(fn, path, payload, manifest) -> tuple[bool, str]:
    with open(os.path.join(path, manifest), "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        result = fn(path)
    except Exception as exc:  # noqa: BLE001
        return False, f"RAISED {exc!r}"
    return result is None, repr(result)


# The stats_from_disk loop above leaves _sfd_dir's manifest corrupted
# (each case overwrites it, and the loop never restores one) — rebuild it
# for real before using it as a positive-path fixture here.
card_index.save(_sfd_ix, _sfd_dir)
_rm_ok = card_index.load_row_map(_sfd_dir)
check("load_row_map: a real manifest reports the same rows as the index "
      "it was built from",
      _rm_ok is not None and set(_rm_ok.rows) == set(_sfd_ix.nids)
      and _rm_ok.dims == _sfd_ix.dims, repr(_rm_ok))
for _fn, _label2 in ((card_index.load, "card_index.load"),
                     (card_index.load_row_map, "load_row_map")):
    for _corrupt_label, _corrupt_payload in (
        ("a version-mismatched manifest", _sfd_stale_payload),
        ("a CORRUPT (non-JSON) manifest", "{not json"),
        ("a manifest of null", "null"),
        ("a manifest of []", "[]"),
        ("a manifest of a bare string", '"str"'),
    ):
        check(f"{_label2}: {_corrupt_label} returns None rather than "
              "raising — a truncated write can leave null/[]/a bare "
              "string, and m.get(...) on that used to raise AttributeError "
              "straight through",
              *_none_on_corrupt(_fn, _sfd_dir, _corrupt_payload,
                                card_index.MANIFEST_FILE))
shutil.rmtree(_sfd_tmp, ignore_errors=True)

# Widening index_signature from (provider, model) to (provider, model,
# dims) broke EIGHT call sites at once, and most of them failed silently:
# a two-tuple compared against a three-tuple is simply never equal, so the
# caches went permanently stale instead of raising. The fix was one shared
# comparator; this pin is what stops the next reader spelling it by hand
# again.
import os as _os, re as _re
# Only comparisons against a SIGNATURE. An index-vs-index compatibility
# check (retention._score_notes) is a different question and rightly keeps
# its own two-part test, so it can say "spaces differ" and "dimensions
# differ" as separate errors.
_SIG_SPELLINGS = _re.compile(
    r"\(\w+\.provider,\s*\w+\.model\)\s*[!=]=\s*(?:cfg_)?sig(?:nature)?\b|"
    r'\(st\["provider"\],\s*st\["model"\]\)\s*[!=]='
)
for _name in ("card_index.py", "pdf_index.py", "retention.py",
              "manage_models.py", "curation.py", "tag_sync.py"):
    _src = open(_os.path.join("klausmate", _name), encoding="utf-8").read()
    check(f"{_name} compares signatures through embeddings.signature_matches, "
          "never by hand",
          _SIG_SPELLINGS.search(_src) is None)

check("...and sent for OpenAI's v3 models, which are MRL-trained",
      embeddings.index_signature(
          {"embedding_provider": "openai",
           "embedding_model": "text-embedding-3-large",
           "embedding_dimensions": 1024}
      ) == ("openai", "text-embedding-3-large", 1024))

print("== missing key ==")
try:
    embeddings.OpenAIEmbeddings(lambda: {}).embed(["hi"])
    check("openai no key raises", False)
except embeddings.EmbeddingError as e:
    check("openai no key raises 401", e.status == 401)
    # K-236: the old copy sent the user to "Tools → Klaus → Manage models",
    # a menu K-045 folded away and K-227 finished off — a dead address on a
    # message that only ever appears when something needs fixing.
    check("401 message names the page that actually holds the key",
          "KlausMate Preferences → API keys & models" in e.user_message())

# The HTTP-level behavior (auth header, retries, dims field, batching) now
# lives entirely in openai_client.py and is covered by
# tests/test_openai_client.py — OpenAIEmbeddings.embed is a thin
# translation shim over it (see embeddings.py), so it isn't re-mocked here.
# embed_batches itself is still this module's own — provider-agnostic
# batching with no clamp (the old Voyage-specific 128 clamp is gone with
# Voyage): a fake provider is enough to pin the loop, no HTTP involved.
class FakeProvider:
    def __init__(self):
        self.sizes = []
    def embed(self, texts, kind="document"):
        self.sizes.append(len(texts))
        return [[1.0, 0.0]] * len(texts)

fp = FakeProvider()
list(embeddings.embed_batches(fp, ["x"] * 300, batch_size=999))
check("batch_size passed straight through — no provider-level clamp",
      fp.sizes == [300], str(fp.sizes))

# ---------------------------------------------------------------- pdf_index

print("== pdf_index v2: one row per page, hash-keyed ==")
# Task 5 (K-225): pdf_index moved from chunking a page's text into several
# rows to ONE vector per page, fed by page_store.py. The chunking helpers
# (stride_sample/chunk_pages/chunk_text_at) and pdf_handler._chunk_text are
# gone outright — there is no chunk table left to sample or recover text
# from.
_pi_tmp = tempfile.mkdtemp(prefix="klaus_test_pi_")
_pi_idx = pdf_index.PdfIndex(
    provider="openai", model="m", pdf_name="lec", dims=2, source_sig=(1, 2),
    pages=[(1, "aaaa"), (2, "bbbb")], embedded_rows=2,
    vectors=array("f", [1.0, 0.0, 0.0, 1.0]),
)
pdf_index.save(_pi_idx, _pi_tmp)
_pi_back = pdf_index.load(_pi_tmp)
check("pages round-trip as (page_1based, text_hash)",
      _pi_back is not None and _pi_back.pages == [(1, "aaaa"), (2, "bbbb")]
      and _pi_back.embedded_rows == 2)
with open(os.path.join(_pi_tmp, "manifest.json"), "w") as f:
    f.write(json.dumps({"version": 1, "chunks": [], "dims": 2, "provider": "x", "model": "y"}))
check("a version-1 (chunk) manifest reads as absent → rebuild",
      pdf_index.load(_pi_tmp) is None)
for _pi_label, _pi_payload in (
    ("a manifest of null", "null"),
    ("a manifest of []", "[]"),
    ("a manifest of a bare string", '"str"'),
):
    check(f"pdf_index.load: {_pi_label} returns None rather than raising "
          "— m.get(...) on a non-dict manifest used to raise AttributeError "
          "straight through (K-181)",
          *_none_on_corrupt(pdf_index.load, _pi_tmp, _pi_payload,
                            pdf_index.MANIFEST_FILE))
check("best_page is the argmax row's page, 1-based",
      pdf_index.best_page(_pi_back, [0.0, 1.0]) == (2, 1.0))
check("a zero vector never wins best_page",
      pdf_index.best_page(
          pdf_index.PdfIndex(provider="o", model="m", pdf_name="z", dims=2,
                              pages=[(1, "h")], embedded_rows=1,
                              vectors=array("f", [0.0, 0.0])),
          [1.0, 0.0],
      ) == (1, 0.0))
check("chunking helpers are gone",
      not hasattr(pdf_index, "chunk_pages")
      and not hasattr(pdf_index, "stride_sample")
      and not hasattr(pdf_index, "chunk_text_at")
      and not hasattr(pdf_handler, "_chunk_text"))
shutil.rmtree(_pi_tmp, ignore_errors=True)

print("== pdf_index: disk lifecycle ==")
tmp = tempfile.mkdtemp(prefix="klaus_test_")
ctx_dir = os.path.join(tmp, "contexts")
os.makedirs(ctx_dir)

pages = [
    ("Alpha beta gamma. " * 40).strip(),   # page 1
    "",                                      # page 2: empty
    ("Delta epsilon zeta. " * 40).strip(),  # page 3
]
with open(os.path.join(ctx_dir, "Lecture_1.json"), "w") as f:
    json.dump({"pages": pages, "page_count": 3}, f)
with open(os.path.join(ctx_dir, "Lecture_1.txt"), "w") as f:
    f.write("\n\n".join(pages))

sig = pdf_index.source_signature(tmp, "Lecture 1.pdf")
check("source signature resolves via safe name", sig is not None)

page_rows = [(i + 1, "h%d" % (i + 1)) for i in range(len(pages))]
idx = pdf_index.PdfIndex(
    provider="openai", model="text-embedding-3-large", pdf_name="Lecture_1",
    source_sig=sig, pages=list(page_rows),
)
idx.dims = 4
for i in range(len(page_rows)):
    v = [0.0] * 4
    v[i % 4] = 1.0
    idx.vectors.extend(v)
    idx.embedded_rows += 1
d = pdf_index.index_dir(tmp, "Lecture 1")
pdf_index.save(idx, d)
idx2 = pdf_index.load(d)
check("save/load roundtrip", idx2 is not None and idx2.pages == idx.pages
      and idx2.embedded_rows == idx.embedded_rows and idx2.vectors == idx.vectors)
check("is_fresh true", pdf_index.is_fresh(idx2, sig, ("openai", "text-embedding-3-large")))
check("is_fresh false on provider change",
      not pdf_index.is_fresh(idx2, sig, ("openai", "text-embedding-3-small")))
check("is_fresh false on source change",
      not pdf_index.is_fresh(idx2, (sig[0] + 1, sig[1]), ("openai", "text-embedding-3-large")))

# resume state: fewer embedded rows than pages
idx2.embedded_rows -= 2
del idx2.vectors[-8:]
pdf_index.save(idx2, d)
idx3 = pdf_index.load(d)
check("partial index loads with resume cursor",
      idx3 is not None and idx3.embedded_rows == len(page_rows) - 2)
check("partial index is not fresh",
      not pdf_index.is_fresh(idx3, sig, ("openai", "text-embedding-3-large")))

# corrupt vectors -> load None
with open(os.path.join(d, "vectors.f32"), "ab") as f:
    f.write(b"\x00\x00\x00\x00")
check("truncated/oversized vectors -> rebuild", pdf_index.load(d) is None)

st = pdf_index.stats_from_disk(d)
check("stats_from_disk reads manifest", st["exists"] and st["pages"] == len(page_rows))
# The twin: both exits answer the same keys, and every non-manifest takes
# the failure exit — the SAME five payloads card_index gets, not just one.
_pi_missing = pdf_index.stats_from_disk(os.path.join(tmp, "no-such-index"))
check("pdf_index.stats_from_disk: a missing index returns the same key set "
      "as a present one",
      set(_pi_missing) == set(st) and not _pi_missing["exists"],
      f"success={sorted(st)} failure={sorted(_pi_missing)}")
_pi_bad = os.path.join(tmp, "bad-manifest"); os.makedirs(_pi_bad)
for _label, _payload in (("a version-mismatched manifest",
                          json.dumps({"version": pdf_index.INDEX_VERSION + 1})),
                         ("a CORRUPT (non-JSON) manifest", "{not json"),
                         ("a manifest of null", "null"),
                         ("a manifest of []", "[]"),
                         ("a manifest of a bare string", '"str"')):
    check(f"pdf_index.stats_from_disk: {_label} takes the failure exit "
          "with every key intact",
          *_failure_exit(pdf_index.stats_from_disk, _pi_bad, st,
                         payload=_payload, manifest=pdf_index.MANIFEST_FILE))

pdf_index.delete(tmp, "Lecture 1")
check("delete removes dir", not os.path.isdir(d))

# delete_context wiring
d2 = pdf_index.index_dir(tmp, "Lecture 1")
os.makedirs(d2, exist_ok=True)
with open(os.path.join(d2, "manifest.json"), "w") as f:
    f.write("{}")
# PR1 review fix: user_files/pages/<safe>/ (page_store.py) is a sibling
# that delete_context never touched — a re-import under this same safe
# basename would silently inherit a stranger's slide text and transcript.
_dc_page_store = importlib.import_module("klausmate.page_store")
_dc_page_store.ensure_records(tmp, "Lecture_1", os.path.join(tmp, "Lecture 1.pdf"),
                               ["slide text"])
d3 = os.path.join(tmp, _dc_page_store.SUBDIR, "Lecture_1")
check("pages dir exists before delete (sanity — the pin below must exercise something)",
      os.path.isdir(d3))
pdf_handler.delete_context(tmp, "Lecture 1")
check("delete_context removes pdf_index dir", not os.path.isdir(d2))
check("delete_context removes the pages dir too", not os.path.isdir(d3))

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
# The fake bytes above aren't parseable PDF — stub extraction like the
# later save_pdf sections do (with the typing_extensions shim, pypdf is
# real here, matching the Anki runtime).
_orig_extract_sp = pdf_handler.extract_pages
pdf_handler.extract_pages = lambda p: ["page text"]
try:
    t0 = time.time()
    pdf_handler.save_pdf(sp_tmp, "Old Lecture", raw_pdf)
    lu1 = pdf_handler.load_last_used(sp_tmp)
    check("save_pdf touches last_used on first import",
          lu1.get("Old_Lecture", 0) >= t0, str(lu1))

    time.sleep(0.05)
    t1 = time.time()
    pdf_handler.save_pdf(sp_tmp, "Old Lecture", raw_pdf)  # re-import, same basename
    lu2 = pdf_handler.load_last_used(sp_tmp)
finally:
    pdf_handler.extract_pages = _orig_extract_sp
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
_stub("aqt.qt", QAction=object, QInputDialog=object, QMessageBox=object, qconnect=lambda *a, **k: None)
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

    # match_scores on hand-built unit vectors — one vector per PAGE now
    # (pdf_index v2): a note's score is simply its best-matching page, so
    # there is no more chunk-level "agg" (top3_mean is gone along with it).
    cidx = card_index.CardIndex(provider="openai", model="text-embedding-3-large", dims=2)
    for nid, vec in [(1, [1.0, 0.0]), (2, [0.0, 1.0]),
                     (3, [math.sqrt(0.5), math.sqrt(0.5)])]:
        cidx.nids.append(nid)
        cidx.mods.append(0)
        cidx.hashes.append("h%d" % nid)
        cidx.vectors.extend(vec)
    pidx = pdf_index.PdfIndex(provider="openai", model="text-embedding-3-large",
                              pdf_name="x", dims=2)
    for i, vec in enumerate(([1.0, 0.0], [0.0, 1.0])):
        pidx.pages.append((i + 1, "h%d" % (i + 1)))
        pidx.vectors.extend(vec)
        pidx.embedded_rows += 1
    scores_out, pages_out = retention.match_scores(pidx, cidx, floor=0.0)
    scores = dict(scores_out)
    check("best-page score: nid1 = 1.0, on page 1",
          abs(scores[1] - 1.0) < 1e-6 and pages_out[1] == 1)
    check("best-page score: nid3 = 0.707 (equidistant from both pages)",
          abs(scores[3] - math.sqrt(0.5)) < 1e-6)
    check("every scored note has a best page, 1-based",
          all(nid in pages_out and pages_out[nid] >= 1 for nid, _ in scores_out))
    floored_out, _floored_pages = retention.match_scores(pidx, cidx, floor=0.9)
    check("floor filters", set(dict(floored_out)) == {1, 2})
    check("pdf_match_agg is gone",
          not hasattr(retention, "DEFAULT_AGG")
          and "pdf_match_agg" not in open(retention.__file__).read())
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
    m_pages = {1: 1, 2: 3}
    sig2 = ("openai", "text-embedding-3-large")
    src2 = (123, 456)
    retention.save_matches("Lecture 1", sig2, 2, src2, "digest1", m, m_pages)
    got = retention.load_matches("Lecture 1", sig2, 2, src2, "digest1")
    check("matches + pages roundtrip",
          got == ([(1, 0.8), (2, 0.4)], {1: 1, 2: 3}))
    check("matches invalid on digest",
          retention.load_matches("Lecture 1", sig2, 2, src2, "other") is None)
    check("matches invalid on dims",
          retention.load_matches("Lecture 1", sig2, 3, src2, "digest1") is None)
    check("matches invalid on source sig",
          retention.load_matches("Lecture 1", sig2, 2, (9, 9), "digest1") is None)

    # MATCHES_VERSION bump (Important 3, fix round 2): the cache payload
    # gained "pages" and lost "agg" without a version bump, so a pre-K-225
    # matches.json could load as valid against a rebuilt (and page-keyed
    # differently) pdf_index. Bumping the constant is only half the pin —
    # the other half is proving a stored v1 payload actually reads as
    # absent now, mirroring how every other invalidation check above calls
    # load_matches.
    check("MATCHES_VERSION bumped to 2 (payload gained \"pages\", lost \"agg\")",
          retention.MATCHES_VERSION == 2)
    _v1_path = retention._matches_path("Lecture 1")
    with open(_v1_path, encoding="utf-8") as f:
        _v1_payload = json.load(f)
    _v1_payload["version"] = 1
    with open(_v1_path, "w", encoding="utf-8") as f:
        json.dump(_v1_payload, f)
    check("a stored v1 matches.json now reads as absent/stale, not valid",
          retention.load_matches("Lecture 1", sig2, 2, src2, "digest1") is None)
    for _lm_label, _lm_payload in (
        ("a manifest of null", "null"),
        ("a manifest of []", "[]"),
        ("a manifest of a bare string", '"str"'),
    ):
        check(f"retention.load_matches: {_lm_label} returns None rather than "
              "raising — m.get(...) on a non-dict matches.json used to raise "
              "AttributeError straight through (K-181)",
              *_none_on_corrupt(
                  lambda _p: retention.load_matches(
                      "Lecture 1", sig2, 2, src2, "digest1"),
                  os.path.dirname(_v1_path), _lm_payload,
                  os.path.basename(_v1_path)))

    print("== ensure_pdf_index: do_build's hash-reuse (mutation harness) ==")
    # Exercises do_build's REAL body end to end — _AnyOp above never calls
    # `op` at all, which is right for tests that don't care what
    # ensure_pdf_index actually computes, but wrong for proving the
    # hash-reuse skip (an unchanged page's vector is carried over rather
    # than re-embedded) has teeth. A small local QueryOp fake runs `op`
    # synchronously instead of dropping it, so do_build's own code executes
    # here — and provider_from_config/_cfg are patched just enough to
    # dodge the real aqt/config chain this stub harness doesn't have.
    class _SyncOp:
        def __init__(self, parent=None, op=None, success=None):
            self._op = op
            self._success = success
            self._failure = None

        def success(self, fn):
            self._success = fn
            return self

        def failure(self, fn):
            self._failure = fn
            return self

        def without_collection(self):
            return self

        def run_in_background(self):
            try:
                result = self._op(None)
            except Exception as exc:  # noqa: BLE001
                if self._failure:
                    self._failure(exc)
                return
            if self._success:
                self._success(result)

    class _CountingProvider:
        name = "openai"

        def __init__(self):
            self.calls = []

        def embed(self, texts, kind="document"):
            self.calls.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

    _hr_tmp = tempfile.mkdtemp(prefix="klaus_test_hr_")
    os.makedirs(os.path.join(_hr_tmp, "contexts"))
    _hr_pages = ["alpha page one", "beta page two", "gamma page three"]
    with open(os.path.join(_hr_tmp, "contexts", "HR.json"), "w") as f:
        json.dump({"pages": _hr_pages, "page_count": 3}, f)

    _hr_provider = _CountingProvider()
    _orig_queryop = retention.QueryOp
    _orig_cfg_fn = retention._cfg
    _orig_provider_from_config = embeddings.provider_from_config
    _orig_user_files = retention.USER_FILES
    retention.QueryOp = _SyncOp
    retention._cfg = lambda: {"embedding_model": "text-embedding-3-large"}
    embeddings.provider_from_config = lambda get_config: _hr_provider
    retention.USER_FILES = _hr_tmp
    try:
        _hr_built = {}
        _hr_errors = []
        retention.ensure_pdf_index(
            None, "HR",
            on_done=lambda idx: _hr_built.setdefault("idx", idx),
            on_error=lambda e: _hr_errors.append(e),
        )
        check("do_build harness: first build hit no error", _hr_errors == [],
              str(_hr_errors))
        check("first build embeds every page (3 texts, one batch)",
              len(_hr_provider.calls) == 1 and len(_hr_provider.calls[0]) == 3,
              str(_hr_provider.calls))
        check("first build's index is complete, 3 pages",
              "idx" in _hr_built and _hr_built["idx"].embedded_rows == 3
              and [p for p, _h in _hr_built["idx"].pages] == [1, 2, 3])

        # Change ONE page's text (a new context file -> a new source
        # signature, so is_fresh() no longer short-circuits and do_build's
        # own page-by-page hash comparison actually runs).
        _hr_pages[1] = "beta page two REVISED"
        with open(os.path.join(_hr_tmp, "contexts", "HR.json"), "w") as f:
            json.dump({"pages": _hr_pages, "page_count": 3}, f)
        retention.ensure_pdf_index(
            None, "HR",
            on_done=lambda idx: _hr_built.setdefault("idx2", idx),
            on_error=lambda e: _hr_errors.append(e),
        )
        check("do_build harness: second build hit no error", _hr_errors == [],
              str(_hr_errors))
        check("second build re-embeds ONLY the one changed page — every "
              "other page's vector is reused by hash, never re-sent to "
              "the provider",
              len(_hr_provider.calls) == 2 and len(_hr_provider.calls[1]) == 1,
              str(_hr_provider.calls))
        check("second build's index is still complete, 3 pages",
              "idx2" in _hr_built and _hr_built["idx2"].embedded_rows == 3
              and [p for p, _h in _hr_built["idx2"].pages] == [1, 2, 3])

        # -- a TRANSCRIPT grows (K-236 / I5) ---------------------------
        # page_store.append_segment writes the page RECORD and never
        # contexts/<safe>.json, so the source signature — the only thing
        # is_fresh() can see — does not move. do_build used to return at
        # is_fresh before any hash was compared, which made D3's "a page
        # whose transcript grew re-embeds alone" untrue: the new text was
        # never embedded and the stale hash stayed on disk forever.
        page_store = importlib.import_module("klausmate.page_store")
        pdf_handler = importlib.import_module("klausmate.pdf_handler")
        _hr_safe = pdf_handler._safe_basename("HR")
        _hr_path = pdf_handler.pdf_path_for(_hr_tmp, _hr_safe) or ""
        _hr_src_before = pdf_index.source_signature(_hr_tmp, "HR")
        _hr_hash_before = dict(_hr_built["idx2"].pages)[3]
        page_store.append_segment(_hr_tmp, _hr_safe, _hr_path, 2, 0.0, 5.0,
                                  "and this is what the lecturer said")
        check("a transcript append does not move the context file's "
              "signature — is_fresh() alone cannot see it",
              pdf_index.source_signature(_hr_tmp, "HR") == _hr_src_before)
        retention.ensure_pdf_index(
            None, "HR",
            on_done=lambda idx: _hr_built.setdefault("idx3", idx),
            on_error=lambda e: _hr_errors.append(e),
        )
        check("do_build harness: transcript build hit no error",
              _hr_errors == [], str(_hr_errors))
        check("a page whose TRANSCRIPT grew re-embeds ALONE — exactly one "
              "text reaches the provider, and it is the page that changed",
              len(_hr_provider.calls) == 3
              and len(_hr_provider.calls[2]) == 1
              and "lecturer said" in _hr_provider.calls[2][0],
              str(_hr_provider.calls[2:]))
        check("...and the index's stored hash for that page moves with it, "
              "so the next build sees the page as current",
              "idx3" in _hr_built
              and dict(_hr_built["idx3"].pages)[3] != _hr_hash_before
              and _hr_built["idx3"].embedded_rows == 3)
        retention.ensure_pdf_index(
            None, "HR",
            on_done=lambda idx: _hr_built.setdefault("idx4", idx),
            on_error=lambda e: _hr_errors.append(e),
        )
        check("...and an unchanged rebuild still embeds NOTHING — the page "
              "comparison must not cost a re-embed on every open",
              len(_hr_provider.calls) == 3, str(_hr_provider.calls[2:]))

        # -- the matches cache follows the same pages (K-236 / I5b) -----
        _m_sig = ("openai", "text-embedding-3-large")
        _m_src = pdf_index.source_signature(_hr_tmp, "HR")
        retention.save_matches("HR", _m_sig, 2, _m_src, "digestHR",
                               [(1, 0.9)], {1: 3})
        check("the matches cache hits while the pages it was ranked "
              "against are unchanged",
              retention.load_matches("HR", _m_sig, 2, _m_src, "digestHR")
              is not None)
        page_store.append_segment(_hr_tmp, _hr_safe, _hr_path, 0, 5.0, 9.0,
                                  "more words said over slide one")
        retention.ensure_pdf_index(
            None, "HR",
            on_done=lambda idx: _hr_built.setdefault("idx5", idx),
            on_error=lambda e: _hr_errors.append(e),
        )
        check("...and goes COLD once a page re-embedded under it — every "
              "other key (pdf_source_sig, the card digest, the signature) "
              "is blind to a transcript, so without the pages digest "
              "ensure_matches would serve the old ranking against the "
              "new vectors",
              retention.load_matches("HR", _m_sig, 2, _m_src, "digestHR")
              is None)
        retention.save_matches("HR", _m_sig, 2, _m_src, "digestHR",
                               [(1, 0.8)], {1: 1})
        check("...and hits again once the ranking is recomputed for them",
              retention.load_matches("HR", _m_sig, 2, _m_src, "digestHR")
              == ([(1, 0.8)], {1: 1}))
    finally:
        retention.QueryOp = _orig_queryop
        retention._cfg = _orig_cfg_fn
        embeddings.provider_from_config = _orig_provider_from_config
        retention.USER_FILES = _orig_user_files
        shutil.rmtree(_hr_tmp, ignore_errors=True)

    print("== ensure_pdf_index: cancel leaves a resumable, incomplete index "
          "(Critical 1 fix-round-2 pin) ==")
    # Regression pin for the silent-data-loss bug: do_build used to zero-fill
    # every never-embedded row AND count it as embedded, so a cancelled build
    # saved a "complete" index that was actually part garbage, and — because
    # is_fresh() then read True — never resumed. 100 distinct pages (> the
    # embed_batches BATCH_SIZE of 64) so a cancel mid-first-batch leaves a
    # real, provable gap: batch one (rows 0-63) lands, batch two never runs.
    class _CancelingProvider:
        name = "openai"

        def __init__(self, cancel_event):
            self.calls = []
            self._cancel_event = cancel_event

        def embed(self, texts, kind="document"):
            self.calls.append(list(texts))
            self._cancel_event.set()  # fires mid-batch-one, before batch two
            return [[1.0, 0.0] for _ in texts]

    _c1_total = 100
    _c1_tmp = tempfile.mkdtemp(prefix="klaus_test_c1_")
    os.makedirs(os.path.join(_c1_tmp, "contexts"))
    _c1_pages = [f"page {i} distinct text" for i in range(1, _c1_total + 1)]
    with open(os.path.join(_c1_tmp, "contexts", "C1.json"), "w") as f:
        json.dump({"pages": _c1_pages, "page_count": _c1_total}, f)

    _c1_cancel = threading.Event()
    _c1_provider = _CancelingProvider(_c1_cancel)
    _orig_queryop = retention.QueryOp
    _orig_cfg_fn = retention._cfg
    _orig_provider_from_config = embeddings.provider_from_config
    _orig_user_files = retention.USER_FILES
    retention.QueryOp = _SyncOp
    retention._cfg = lambda: {"embedding_model": "text-embedding-3-large"}
    embeddings.provider_from_config = lambda get_config: _c1_provider
    retention.USER_FILES = _c1_tmp
    try:
        _c1_built = {}
        _c1_errors = []
        retention.ensure_pdf_index(
            None, "C1",
            cancel=_c1_cancel,
            on_done=lambda idx: _c1_built.setdefault("idx", idx),
            on_error=lambda e: _c1_errors.append(e),
        )
        check("cancel pin: cancelled build hit no error", _c1_errors == [],
              str(_c1_errors))
        check("cancel pin: provider saw exactly one batch (64 pages) before "
              "the cancel stopped the second",
              len(_c1_provider.calls) == 1 and len(_c1_provider.calls[0]) == 64,
              [len(c) for c in _c1_provider.calls])

        _c1_dir = pdf_index.index_dir(_c1_tmp, "C1")
        _c1_reloaded = pdf_index.load(_c1_dir)
        check("cancel pin: reloaded index has fewer embedded rows than pages "
              "— no zero vector was substituted for the un-embedded rows",
              _c1_reloaded is not None and _c1_reloaded.embedded_rows == 64
              and _c1_reloaded.embedded_rows < _c1_total,
              None if _c1_reloaded is None else _c1_reloaded.embedded_rows)
        check("cancel pin: reloaded index is not complete",
              _c1_reloaded is not None and not _c1_reloaded.is_complete())
        _c1_sig = ("openai", "text-embedding-3-large", 0)
        _c1_src = pdf_index.source_signature(_c1_tmp, "C1")
        check("cancel pin: reloaded index is not fresh (so the next run "
              "won't short-circuit and skip resuming)",
              not pdf_index.is_fresh(_c1_reloaded, _c1_src, _c1_sig))

        # Second build, nothing cancelled this time: must resume, not restart
        # — the provider is called again ONLY for the 36 rows still missing.
        _c1_provider.calls.clear()
        _c1_cancel2 = threading.Event()
        _c1_built2 = {}
        _c1_errors2 = []
        retention.ensure_pdf_index(
            None, "C1",
            cancel=_c1_cancel2,
            on_done=lambda idx: _c1_built2.setdefault("idx", idx),
            on_error=lambda e: _c1_errors2.append(e),
        )
        check("cancel pin: resumed build hit no error", _c1_errors2 == [],
              str(_c1_errors2))
        check("cancel pin: resumed build's index is now complete, all "
              "100 pages",
              "idx" in _c1_built2 and _c1_built2["idx"].embedded_rows == _c1_total
              and _c1_built2["idx"].is_complete())
        check("cancel pin: provider re-called only for the 36 rows that "
              "were never embedded, not all 100",
              sum(len(c) for c in _c1_provider.calls) == _c1_total - 64,
              [len(c) for c in _c1_provider.calls])
    finally:
        retention.QueryOp = _orig_queryop
        retention._cfg = _orig_cfg_fn
        embeddings.provider_from_config = _orig_provider_from_config
        retention.USER_FILES = _orig_user_files
        shutil.rmtree(_c1_tmp, ignore_errors=True)

    print("== ensure_pdf_index: an empty page gets a zero vector, never text "
          "sent to the provider (Critical 2 fix-round-2 pin) ==")
    # Spec D3: "a page with empty combined_text gets a zero vector and never
    # wins best_page." A 3-page fixture whose middle page has no text at all
    # (no slide text layer, no transcript) — page_store.combined_text("") for
    # that page, exactly the image-only-slide case the review reproduced.
    class _RecordingProvider:
        name = "openai"

        def __init__(self):
            self.calls = []

        def embed(self, texts, kind="document"):
            self.calls.append(list(texts))
            # "one" -> [1,0], anything else (must be non-empty by the fix)
            # -> [0,1] — two distinguishable, already-unit vectors.
            return [([1.0, 0.0] if "one" in t else [0.0, 1.0]) for t in texts]

    _c2_tmp = tempfile.mkdtemp(prefix="klaus_test_c2_")
    os.makedirs(os.path.join(_c2_tmp, "contexts"))
    _c2_pages = ["Slide one has text", "", "Slide three has text"]
    with open(os.path.join(_c2_tmp, "contexts", "C2.json"), "w") as f:
        json.dump({"pages": _c2_pages, "page_count": 3}, f)

    _c2_provider = _RecordingProvider()
    _orig_queryop = retention.QueryOp
    _orig_cfg_fn = retention._cfg
    _orig_provider_from_config = embeddings.provider_from_config
    _orig_user_files = retention.USER_FILES
    retention.QueryOp = _SyncOp
    retention._cfg = lambda: {"embedding_model": "text-embedding-3-large"}
    embeddings.provider_from_config = lambda get_config: _c2_provider
    retention.USER_FILES = _c2_tmp
    try:
        _c2_built = {}
        _c2_errors = []
        retention.ensure_pdf_index(
            None, "C2",
            on_done=lambda idx: _c2_built.setdefault("idx", idx),
            on_error=lambda e: _c2_errors.append(e),
        )
        check("empty-page pin: build hit no error", _c2_errors == [],
              str(_c2_errors))
        _c2_all_texts = [t for batch in _c2_provider.calls for t in batch]
        check('empty-page pin: "" never reaches the provider',
              "" not in _c2_all_texts, _c2_all_texts)
        check("empty-page pin: index is complete with all 3 rows",
              "idx" in _c2_built and _c2_built["idx"].embedded_rows == 3
              and _c2_built["idx"].is_complete())

        _c2_idx = _c2_built["idx"]
        _c2_mv = memoryview(_c2_idx.vectors)
        _c2_mid = list(_c2_mv[1 * _c2_idx.dims:2 * _c2_idx.dims])
        check("empty-page pin: the empty middle page's row is an explicit "
              "zero vector", _c2_mid == [0.0] * _c2_idx.dims, _c2_mid)

        _c2_q1 = embeddings.normalize([1.0, 0.0])
        _c2_q3 = embeddings.normalize([0.0, 1.0])
        _c2_page_for_1, _c2_score_for_1 = pdf_index.best_page(_c2_idx, _c2_q1)
        _c2_page_for_3, _c2_score_for_3 = pdf_index.best_page(_c2_idx, _c2_q3)
        check("empty-page pin: best_page never returns the empty page 2, "
              "for a query matching either neighbor",
              _c2_page_for_1 == 1 and _c2_page_for_3 == 3,
              (_c2_page_for_1, _c2_page_for_3))
    finally:
        retention.QueryOp = _orig_queryop
        retention._cfg = _orig_cfg_fn
        embeddings.provider_from_config = _orig_provider_from_config
        retention.USER_FILES = _orig_user_files
        shutil.rmtree(_c2_tmp, ignore_errors=True)

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

# ------------------------------------------------- K-254: Doubtful tag +
# ------------------------------------------------- confirmed-only counts

print("== Lecture tag synchronization ==")

try:
    tag_sync = importlib.import_module("klausmate.tag_sync")
    HAVE_TAG_SYNC = True
except Exception as e:
    HAVE_TAG_SYNC = False
    print(f" SKIP tag_sync import failed: {type(e).__name__}: {e}")

if HAVE_TAG_SYNC:
    # A reserved tag from an existing collection must not rename a PDF.
    _plan = tag_sync.plan_reconcile(
        {"renal": "!Library::Renal"}, {"!Library::Doubtful"}
    )
    check("the legacy reserved tag is never a reconcile-rename candidate",
          _plan["candidates"] == [] and _plan["action"] == "reapply"
          and _plan["rename"] is None, _plan)

    # PR #4 fourth review (1): a stored lecture tag is user-derived and
    # lands inside Anki's QUERY LANGUAGE. desired_tag's sanitizer only
    # strips whitespace and "::", so a PDF named 'Lec "1" 100%_a*b\c'
    # keeps the quote (which terminates the operand), the backslash
    # (which escapes whatever follows it) and * / _ — in a tag: search
    # * matches any run and _ any single character. tag_query is the ONE
    # helper both Browse hops build their operand with.
    #
    # Anki's own rules, from the source (anki-main):
    #   rslib/src/text.rs:512-515  escape_anki_wildcards backslash-
    #     escapes exactly [\\*_];
    #   rslib/src/search/writer.rs:103-109  maybe_quote wraps in "…"
    #     after txt.replace('"', "\\\"");
    #   rslib/src/search/parser.rs:731-772  unescape() accepts
    #     \\ \" \: \( \) \- and invalid_escape_sequence's escapable set
    #     is [\\":*_()-]; \* and \_ are deliberately left for the SQL
    #     writer (its own test at parser.rs:881-884: "parser doesn't
    #     unescape \*_", consumed by text.rs to_custom_re:475-487).
    _messy = '!Library::Lec "1" 100%_a*b\\c'
    check("tag_query escapes backslash, quote and both wildcards inside "
          "one quoted tag: operand",
          tag_sync.tag_query(_messy)
          == 'tag:"!Library::Lec \\"1\\" 100%\\_a\\*b\\\\c"',
          tag_sync.tag_query(_messy))
    check("a plain tag round-trips unchanged inside tag:\"…\"",
          tag_sync.tag_query("!Library::Renal") == 'tag:"!Library::Renal"',
          tag_sync.tag_query("!Library::Renal"))

if HAVE_TAG_SYNC and HAVE_RETENTION:
    # _do_sync_one reaches retention._load_prefs()/_prefs_path() for
    # get_stored_tag/set_stored_tag — never the real user_files (global
    # constraints), so USER_FILES is patched to a scratch dir for this
    # block only, exactly like the retention section above did for tmp.
    _dbt_tmp = tempfile.mkdtemp()
    _orig_user_files = retention.USER_FILES
    retention.USER_FILES = _dbt_tmp
    try:
        class _FakeTags:
            """col.tags double: bulk_add/bulk_remove mutate the SAME
            {tag: {nid,...}} map find_notes reads, so a round trip through
            apply_membership is a real diff, not a recorded call."""

            def __init__(self, tagmap):
                self._tagmap = tagmap

            def bulk_add(self, nids, tag):
                self._tagmap.setdefault(tag, set()).update(nids)

            def bulk_remove(self, nids, tag):
                self._tagmap.setdefault(tag, set()).difference_update(nids)

        class FakeCol:
            """Minimal collection double for tag_sync's col-only helpers
            (apply_membership/apply_rename) — extended with members(), the
            test-only readback the brief asks for."""

            def __init__(self, tags=None):
                self._tagmap = {k: set(v) for k, v in (tags or {}).items()}
                self.tags = _FakeTags(self._tagmap)

            def find_notes(self, query):
                # apply_membership only ever asks 'tag:"<escaped tag>"'.
                tag = query[len('tag:"'):-1]
                return set(self._tagmap.get(tag, set()))

            def members(self, tag):
                return set(self._tagmap.get(tag, set()))

        col = FakeCol(tags={"!Library::Renal": {1, 3}})
        tag_sync._do_sync_one(col, "renal", "!Library::Renal", desired_nids={1, 2})
        check("lecture membership adds and removes notes", col.members("!Library::Renal") == {1, 2})
        _orig_folder_display = tag_sync._folder_and_display
        _orig_run_sync_op = tag_sync._run_sync_op
        _orig_cached_matches = tag_sync._cached_matches
        pkg.get_config = lambda: {"pdf_match_threshold": 0.5}
        tag_sync._folder_and_display = lambda safe: (None, "Renal")
        _captured = []
        tag_sync._run_sync_op = lambda parent, label, work, **kwargs: _captured.append(work)
        try:
            tag_sync.sync_after_threshold(None, "renal", [(1, 0.9), (2, 0.4)], 0.5)
            check("threshold sync schedules one collection operation", len(_captured) == 1)
            if _captured:
                _captured.pop()(col)
            check("threshold sync removes the below-threshold note", col.members("!Library::Renal") == {1})
            tag_sync._cached_matches = lambda safe, cfg: [(1, 0.9), (2, 0.8)]
            tag_sync.sync_after_clear_overrides(None, ["renal"])
            check("clearing overrides schedules one collection operation", len(_captured) == 1)
            if _captured:
                _captured.pop()(col)
            check("clearing overrides restores matching notes", col.members("!Library::Renal") == {1, 2})
        finally:
            tag_sync._folder_and_display = _orig_folder_display
            tag_sync._run_sync_op = _orig_run_sync_op
            tag_sync._cached_matches = _orig_cached_matches
            del pkg.get_config
    finally:
        retention.USER_FILES = _orig_user_files
        shutil.rmtree(_dbt_tmp, ignore_errors=True)

if HAVE_RETENTION:
    check("threshold counts include viewable and suspended cards",
          retention.note_card_counts([(1, .9), (2, .8), (3, .7)], .75,
                                     {1: [0], 2: [0, 2, -1], 3: [0]}) == (2, 3, 1))
    _card_r = {1: [(0.9, False)], 2: [(0.1, False)]}
    r_all = retention.pdf_retention([(1, .9), (2, .8)], .75, _card_r)
    check("retention includes every note above threshold with similarity weighting",
          r_all["matched_notes"] == 2 and r_all["matched_cards"] == 2
          and abs(r_all["retention"] - 0.5235294117647059) < 1e-9, r_all)

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

print("== K-077: foreign annotation scan/adopt (outside text + highlights) ==")
fa_uf = tempfile.mkdtemp(prefix="klaus_fa_uf_")
try:
    check("bake stack available under test shim", pdf_handler.BAKE_AVAILABLE)
    from pypdf import PdfReader as _FaReader, PdfWriter as _FaWriter
    from pypdf.annotations import FreeText as _FaFreeText, Highlight as _FaHighlight
    from pypdf.generic import ArrayObject as _FaArray, FloatObject as _FaFloat
    from pypdf.generic import NameObject as _FaName, TextStringObject as _FaString

    FA = "K77_Lecture"
    os.makedirs(os.path.join(fa_uf, "pdfs"))
    fa_working = os.path.join(fa_uf, "pdfs", FA + ".pdf")

    def fa_write_foreign(path):
        w = _FaWriter()
        w.add_blank_page(width=612, height=792)
        buf_path = path + ".base"
        with open(buf_path, "wb") as f:
            w.write(f)
        r = _FaReader(buf_path)
        w2 = _FaWriter(clone_from=r)
        # Foreign highlight over PDF-space (100,600)-(200,620), with a
        # popup note. PDF y-up: quad order UL,UR,LL,LR.
        hl = _FaHighlight(
            rect=(100, 600, 200, 620),
            quad_points=_FaArray(
                _FaFloat(v)
                for v in [100, 620, 200, 620, 100, 600, 200, 600]
            ),
        )
        hl[_FaName("/Contents")] = _FaString("margin note")
        w2.add_annotation(0, hl)
        w2.add_annotation(0, _FaFreeText(
            text="added in Preview",
            rect=(300, 500, 450, 530),
            font_size="12pt",
            font_color="000000",
            border_color=None,
            background_color=None,
        ))
        with open(path, "wb") as f:
            w2.write(f)
        os.remove(buf_path)

    fa_write_foreign(fa_working)

    found = pdf_handler.scan_foreign_annotations(fa_uf, FA)
    check("scan finds both foreign annotations", len(found) == 2, repr(found))
    fa_hl = next((x for x in found if x.get("kind") == "highlight"), None)
    fa_tx = next((x for x in found if x.get("kind") == "text"), None)
    check("scan classifies one highlight + one text",
          fa_hl is not None and fa_tx is not None, repr(found))
    # Qt-space conversion (page h=792, origin 0): y_qt = 792 - y_top.
    check("highlight rect converts PDF->Qt",
          fa_hl is not None and len(fa_hl["rects"]) == 1
          and all(abs(a - b) < 0.01 for a, b in
                  zip(fa_hl["rects"][0], [100.0, 172.0, 100.0, 20.0])),
          repr(fa_hl))
    check("highlight popup note carried", fa_hl is not None
          and fa_hl.get("note") == "margin note")
    check("text rect converts PDF->Qt",
          fa_tx is not None and len(fa_tx["rects"]) == 1
          and all(abs(a - b) < 0.01 for a, b in
                  zip(fa_tx["rects"][0], [300.0, 262.0, 150.0, 30.0])),
          repr(fa_tx))
    check("text contents carried", fa_tx is not None
          and fa_tx.get("text") == "added in Preview")

    adopted = pdf_handler.adopt_foreign_annotations(fa_uf, FA)
    check("adopt imports both", adopted == 2, adopted)
    fa_recs = pdf_handler.load_annotations(fa_uf, FA)
    check("adopted records survive the validator", len(fa_recs) == 2,
          repr(fa_recs))
    fa_rec_tx = next((r for r in fa_recs if r.get("kind") == "text"), None)
    check("text record keeps kind/text/origin through save+load",
          fa_rec_tx is not None
          and fa_rec_tx.get("text") == "added in Preview"
          and fa_rec_tx.get("origin") == "external",
          repr(fa_rec_tx))

    fa_pristine = os.path.join(fa_uf, "pdf_originals", FA + ".pdf")
    check("pristine captured on adoption", os.path.isfile(fa_pristine))
    pr = _FaReader(fa_pristine)
    pr_annots = [
        str(a.get_object().get("/Subtype"))
        for a in (pr.pages[0].get("/Annots") or [])
    ]
    check("pristine is STRIPPED of the foreign annotations",
          "/Highlight" not in pr_annots and "/FreeText" not in pr_annots,
          repr(pr_annots))

    check("re-adopt before any bake is a no-op (signature dedup)",
          pdf_handler.adopt_foreign_annotations(fa_uf, FA) == 0)

    check("bake succeeds", pdf_handler.bake_annotations(fa_uf, FA))
    # K-082 contract: bake CARRIES the outside originals verbatim and
    # never rewrites them as Klaus-marked copies — Preview's own objects
    # must survive every bake untouched.
    wr = _FaReader(fa_working)
    wr_annots = [a.get_object() for a in (wr.pages[0].get("/Annots") or [])]
    fa_marked = [o for o in wr_annots
                 if str(o.get("/NM") or "").startswith("klausmate:")]
    fa_unmarked = [o for o in wr_annots
                   if not str(o.get("/NM") or "").startswith("klausmate:")]
    check("bake writes NO marked copies of outside marks",
          fa_marked == [], repr([str(o.get("/Subtype")) for o in fa_marked]))
    check("outside originals carried through the bake",
          sorted(str(o.get("/Subtype")) for o in fa_unmarked)
          == ["/FreeText", "/Highlight"],
          repr([str(o.get("/Subtype")) for o in fa_unmarked]))
    fa_carried_hl = next(
        (o for o in fa_unmarked if str(o.get("/Subtype")) == "/Highlight"),
        None,
    )
    fa_qp = [float(v) for v in (fa_carried_hl.get("/QuadPoints") or [])] \
        if fa_carried_hl is not None else []
    check("carried highlight quad is verbatim",
          len(fa_qp) == 8 and all(
              abs(a - b) < 0.01 for a, b in
              zip(fa_qp, [100, 620, 200, 620, 100, 600, 200, 600])),
          repr(fa_qp))
    fa_res = pdf_handler.scan_working_annotations(fa_uf, FA)
    check("post-bake mirror is quiet",
          isinstance(fa_res, dict)
          and pdf_handler.mirror_foreign_annotations(fa_uf, FA, fa_res) == 0
          and len(pdf_handler.load_annotations(fa_uf, FA)) == 2)

    check("adopt after bake is a no-op",
          pdf_handler.adopt_foreign_annotations(fa_uf, FA) == 0)

    # A native Klaus highlight bakes marked — and the outside originals
    # must survive the native bake (they used to be silently wiped).
    fa_recs = pdf_handler.load_annotations(fa_uf, FA)
    fa_recs.append({
        "id": "cafe" * 8, "page": 0,
        "rects": [[50.0, 50.0, 80.0, 12.0]],
        "color": "#fadc50", "note": "",
    })
    pdf_handler.save_annotations(fa_uf, FA, fa_recs)
    check("bake with native highlight succeeds",
          pdf_handler.bake_annotations(fa_uf, FA))
    # The two carried originals ARE in a scan (unmarked, by design);
    # the marked native highlight must not be.
    check("native Klaus highlight is never scanned as foreign",
          len(pdf_handler.scan_foreign_annotations(fa_uf, FA)) == 2)
    wr2 = _FaReader(fa_working)
    wr2_annots = [a.get_object() for a in (wr2.pages[0].get("/Annots") or [])]
    check("native bake carries the outside originals too",
          sorted(
              str(o.get("/Subtype")) for o in wr2_annots
              if not str(o.get("/NM") or "").startswith("klausmate:")
          ) == ["/FreeText", "/Highlight"],
          repr([str(o.get("/Subtype")) for o in wr2_annots]))

    # K-078: the viewer scans on a daemon thread and applies on the main
    # thread — adopt must accept the pre-scanned list without re-parsing.
    fa_write_foreign(fa_working)
    os.remove(os.path.join(fa_uf, "annotations", FA + ".json"))
    fa_pre = pdf_handler.scan_foreign_annotations(fa_uf, FA)
    check("pre-scan finds the rewritten foreign pair", len(fa_pre) == 2)
    check("adopt honors a pre-scanned list",
          pdf_handler.adopt_foreign_annotations(fa_uf, FA, scanned=fa_pre) == 2)
    check("pre-scanned adopt is signature-deduped too",
          pdf_handler.adopt_foreign_annotations(fa_uf, FA, scanned=fa_pre) == 0)
    check("bake after pre-scanned adopt", pdf_handler.bake_annotations(fa_uf, FA))

    # K-082: un-baking clears KLAUS's marks only — outside marks belong
    # to the file and stay. They leave via Remove in Klaus (tombstone)
    # or deletion in Preview itself.
    pdf_handler.save_annotations(fa_uf, FA, [])
    check("un-bake succeeds", pdf_handler.bake_annotations(fa_uf, FA))
    ur = _FaReader(fa_working)
    ur_annots = [a.get_object() for a in (ur.pages[0].get("/Annots") or [])]
    check("un-bake keeps outside originals, drops Klaus marks",
          sorted(str(o.get("/Subtype")) for o in ur_annots)
          == ["/FreeText", "/Highlight"]
          and not any(
              str(o.get("/NM") or "").startswith("klausmate:")
              for o in ur_annots
          ),
          repr([str(o.get("/Subtype")) for o in ur_annots]))
except Exception as e:
    import traceback
    check("K-077 section", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(fa_uf, ignore_errors=True)

print("== K-080: Preview FreeText with no /Contents (text lives in /AP) ==")
ap_uf = tempfile.mkdtemp(prefix="klaus_ap_uf_")
try:
    from pypdf import PdfReader as _ApReader, PdfWriter as _ApWriter
    from pypdf.annotations import FreeText as _ApFreeText
    from pypdf.generic import (
        DictionaryObject as _ApDict, NameObject as _ApName,
        RectangleObject as _ApRect, StreamObject as _ApStream,
    )

    APN = "K80_Preview"
    os.makedirs(os.path.join(ap_uf, "pdfs"))
    ap_working = os.path.join(ap_uf, "pdfs", APN + ".pdf")
    w = _ApWriter()
    w.add_blank_page(width=612, height=792)
    ap_base = ap_working + ".base"
    with open(ap_base, "wb") as f:
        w.write(f)
    w2 = _ApWriter(clone_from=_ApReader(ap_base))
    w2.add_annotation(0, _ApFreeText(
        text="placeholder", rect=(300, 500, 450, 530),
        font_size="12pt", font_color="000000",
        border_color=None, background_color=None))
    # Recreate what macOS Preview actually ships (live Biostatistics.pdf,
    # K-080): NO /Contents — the text exists only as the appearance
    # stream's text-showing operators. Two Tj runs split by Td = the
    # user pressed Return once.
    ap_annot = [a.get_object() for a in w2.pages[0]["/Annots"]][-1]
    del ap_annot[_ApName("/Contents")]
    ap_st = _ApStream()
    ap_st[_ApName("/Type")] = _ApName("/XObject")
    ap_st[_ApName("/Subtype")] = _ApName("/Form")
    ap_st[_ApName("/BBox")] = _ApRect((0, 0, 150, 30))
    ap_st.set_data(
        b"BT /Helv 12 Tf 2 18 Td (added in) Tj 0 -14 Td (Preview) Tj ET"
    )
    ap_annot[_ApName("/AP")] = _ApDict(
        {_ApName("/N"): w2._add_object(ap_st)}
    )
    with open(ap_working, "wb") as f:
        w2.write(f)
    os.remove(ap_base)

    ap_found = pdf_handler.scan_foreign_annotations(ap_uf, APN)
    check("scan finds the Contents-less FreeText", len(ap_found) == 1,
          repr(ap_found))
    ap_rec = ap_found[0] if ap_found else {}
    check("text recovered from the appearance stream, line break kept",
          ap_rec.get("text") == "added in\nPreview",
          repr(ap_rec.get("text")))
    check("adopts and bakes",
          pdf_handler.adopt_foreign_annotations(ap_uf, APN, scanned=ap_found) == 1
          and pdf_handler.bake_annotations(ap_uf, APN))
    # K-082: the bake carries Preview's object VERBATIM — after the
    # round-trip it is still Contents-less (text only in /AP), unmarked.
    ap_r2 = _ApReader(ap_working)
    ap_ft = next(
        (a.get_object()
         for a in (ap_r2.pages[0].get("/Annots") or [])
         if str(a.get_object().get("/Subtype")) == "/FreeText"),
        None,
    )
    check("carried original still Contents-less (verbatim carry)",
          ap_ft is not None and ap_ft.get("/Contents") is None
          and not str(ap_ft.get("/NM") or "").startswith("klausmate:"))
    ap_res = pdf_handler.scan_working_annotations(ap_uf, APN)
    check("post-bake mirror quiet",
          isinstance(ap_res, dict)
          and pdf_handler.mirror_foreign_annotations(ap_uf, APN, ap_res) == 0)
except Exception as e:
    import traceback
    check("K-080 section", False,
          f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(ap_uf, ignore_errors=True)

print("== K-081: adoption audit (drift updates, self-heal, tombstones) ==")
au_uf = tempfile.mkdtemp(prefix="klaus_audit_uf_")
try:
    AU = "K81_Audit"
    os.makedirs(os.path.join(au_uf, "pdfs"))
    os.makedirs(os.path.join(au_uf, "pdf_originals"))
    # A pristine placeholder so adopt's capture path is satisfied without
    # a real working PDF — these tests drive adopt via `scanned` only.
    au_working = os.path.join(au_uf, "pdfs", AU + ".pdf")
    au_pristine = os.path.join(au_uf, "pdf_originals", AU + ".pdf")
    for p in (au_working, au_pristine):
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4 audit")

    # 1. THE live doubling (Preview autosaves while typing): the same
    # text box scanned twice with grown text + drifted rect must UPDATE
    # the record, not append a second one.
    gen1 = [{"kind": "text", "page": 0, "rects": [[42.5, 211.6, 87.6, 17.9]],
             "text": "This is more text", "note": "", "color": "#000000"}]
    gen2 = [{"kind": "text", "page": 0, "rects": [[45.8, 215.6, 80.9, 9.9]],
             "text": "This is more text for the output", "note": "",
             "color": "#000000"}]
    check("first adopt imports one",
          pdf_handler.adopt_foreign_annotations(au_uf, AU, scanned=gen1) == 1)
    n2 = pdf_handler.adopt_foreign_annotations(au_uf, AU, scanned=gen2)
    au_recs = pdf_handler.load_annotations(au_uf, AU)
    check("drifted rescan is ONE change, not a new record",
          n2 == 1 and len(au_recs) == 1, f"changes={n2} records={len(au_recs)}")
    check("record carries the newest text",
          au_recs and au_recs[0].get("text") == "This is more text for the output",
          repr([r.get("text") for r in au_recs]))

    # 2. Self-heal: pre-seeded overlapping external duplicates (what
    # Pouya's live json has NOW) collapse on the next adopt pass — even
    # an empty-scan one — keeping the newest.
    dupes = [
        {"id": "a" * 32, "page": 0, "rects": [[42.5, 211.6, 87.6, 17.9]],
         "color": "#000000", "note": "", "kind": "text",
         "text": "This is more text", "origin": "external"},
        {"id": "b" * 32, "page": 0, "rects": [[45.8, 215.6, 80.9, 9.9]],
         "color": "#000000", "note": "", "kind": "text",
         "text": "This is more text for the output", "origin": "external"},
    ]
    pdf_handler.save_annotations(au_uf, AU, dupes)
    healed = pdf_handler.adopt_foreign_annotations(au_uf, AU, scanned=[])
    au_recs = pdf_handler.load_annotations(au_uf, AU)
    check("empty-scan adopt collapses existing dupes",
          healed >= 1 and len(au_recs) == 1,
          f"changes={healed} records={len(au_recs)}")
    check("collapse keeps the newest generation",
          au_recs and au_recs[0].get("text") == "This is more text for the output")

    # Native records must never collapse, even overlapping.
    natives = [
        {"id": "c" * 32, "page": 3, "rects": [[10, 10, 50, 12]],
         "color": "#fadc50", "note": ""},
        {"id": "d" * 32, "page": 3, "rects": [[12, 12, 50, 12]],
         "color": "#fadc50", "note": ""},
    ]
    pdf_handler.save_annotations(au_uf, AU, natives)
    pdf_handler.adopt_foreign_annotations(au_uf, AU, scanned=[])
    check("overlapping NATIVE highlights are never collapsed",
          len(pdf_handler.load_annotations(au_uf, AU)) == 2)

    # 3. Tombstones: a deleted external record must STAY deleted when the
    # unmarked original shows up in a later scan.
    pdf_handler.save_annotations(au_uf, AU, [])
    check("re-adopt after wipe", pdf_handler.adopt_foreign_annotations(
        au_uf, AU, scanned=gen2) == 1)
    au_rec = pdf_handler.load_annotations(au_uf, AU)[0]
    pdf_handler.add_suppressed(au_uf, AU, au_rec)
    pdf_handler.save_annotations(au_uf, AU, [])
    check("tombstoned original is not re-adopted",
          pdf_handler.adopt_foreign_annotations(au_uf, AU, scanned=gen2) == 0
          and pdf_handler.load_annotations(au_uf, AU) == [])
    # 4. save_annotations must preserve the tombstones (today it drops
    # every top-level key it doesn't know).
    pdf_handler.save_annotations(au_uf, AU, [])
    with open(os.path.join(au_uf, "annotations", AU + ".json")) as f:
        au_doc = json.load(f)
    check("save_annotations preserves suppressed_external",
          bool(au_doc.get("suppressed_external")), repr(sorted(au_doc)))
except Exception as e:
    import traceback
    check("K-081 section", False,
          f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(au_uf, ignore_errors=True)

print("== K-082: mirror semantics (file owns outside marks) ==")
mi_uf = tempfile.mkdtemp(prefix="klaus_mirror_uf_")
try:
    from pypdf import PdfReader as _MiReader, PdfWriter as _MiWriter
    from pypdf.annotations import FreeText as _MiFreeText
    from pypdf.generic import (
        NameObject as _MiName, TextStringObject as _MiString,
    )

    MI = "K82_Mirror"
    os.makedirs(os.path.join(mi_uf, "pdfs"))
    mi_working = os.path.join(mi_uf, "pdfs", MI + ".pdf")

    def mi_write(texts):
        """Working file with one foreign FreeText per (text, y)."""
        w = _MiWriter()
        w.add_blank_page(width=612, height=792)
        b = mi_working + ".base"
        with open(b, "wb") as f:
            w.write(f)
        w2 = _MiWriter(clone_from=_MiReader(b))
        for text, y in texts:
            w2.add_annotation(0, _MiFreeText(
                text=text, rect=(100, y, 250, y + 24), font_size="12pt",
                font_color="000000", border_color=None,
                background_color=None))
        with open(mi_working, "wb") as f:
            w2.write(f)
        os.remove(b)

    mi_write([("first note", 600), ("second note", 500)])
    mi_res = pdf_handler.scan_working_annotations(mi_uf, MI)
    check("scan_working returns dict with page_count",
          isinstance(mi_res, dict) and mi_res.get("page_count") == 1
          and len(mi_res.get("foreign") or []) == 2, repr(mi_res))
    check("mirror imports both",
          pdf_handler.mirror_foreign_annotations(mi_uf, MI, mi_res) == 2)
    # Native record rides along and must never be touched by mirroring.
    mi_recs = pdf_handler.load_annotations(mi_uf, MI)
    mi_recs.append({"id": "f00d" * 8, "page": 0,
                    "rects": [[30.0, 30.0, 60.0, 10.0]],
                    "color": "#fadc50", "note": ""})
    pdf_handler.save_annotations(mi_uf, MI, mi_recs)

    # Preview-side delete: the second note vanishes from the file ->
    # its mirrored record must vanish too; native record stays.
    mi_write([("first note", 600)])
    mi_res = pdf_handler.scan_working_annotations(mi_uf, MI)
    check("preview delete propagates to records",
          pdf_handler.mirror_foreign_annotations(mi_uf, MI, mi_res) == 1)
    mi_recs = pdf_handler.load_annotations(mi_uf, MI)
    check("only the deleted mirror went away",
          sorted(
              (r.get("origin") or "native", r.get("text", ""))
              for r in mi_recs
          ) == [("external", "first note"), ("native", "")], repr(mi_recs))

    # A FAILED scan (None) must never mass-remove mirrored records.
    check("scan of a missing file is None, not empty",
          pdf_handler.scan_working_annotations(mi_uf, "No_Such") is None)
    check("mirror with None is a guarded no-op",
          pdf_handler.mirror_foreign_annotations(mi_uf, MI, None) == 0
          and len(pdf_handler.load_annotations(mi_uf, MI)) == 2)

    # Klaus-side delete: tombstone the remaining external record; the
    # bake must DROP the original from the carry (delete propagates to
    # the file), while the native mark bakes normally.
    mi_ext = next(r for r in pdf_handler.load_annotations(mi_uf, MI)
                  if r.get("origin") == "external")
    pdf_handler.add_suppressed(mi_uf, MI, mi_ext)
    pdf_handler.save_annotations(
        mi_uf, MI,
        [r for r in pdf_handler.load_annotations(mi_uf, MI)
         if r.get("id") != mi_ext.get("id")],
    )
    check("bake after tombstone", pdf_handler.bake_annotations(mi_uf, MI))
    mi_r = _MiReader(mi_working)
    mi_annots = [a.get_object()
                 for a in (mi_r.pages[0].get("/Annots") or [])]
    check("tombstoned original dropped from the file, native baked",
          sorted(str(o.get("/Subtype")) for o in mi_annots)
          == ["/Highlight"]
          and str(mi_annots[0].get("/NM") or "").startswith("klausmate:")
          if mi_annots else False,
          repr([(str(o.get("/Subtype")), str(o.get("/NM") or ""))
                for o in mi_annots]))

    # Legacy adopted copy (K-077 era): a klausmate-marked annot whose
    # /NM id matches an external record is that record's original —
    # mirror must not remove the record, bake must carry it verbatim.
    lg_id = "beef" * 8
    w3 = _MiWriter(clone_from=_MiReader(mi_working))
    lg_annot = _MiFreeText(
        text="legacy adopted", rect=(100, 400, 250, 424),
        font_size="12pt", font_color="000000", border_color=None,
        background_color=None)
    lg_annot[_MiName("/NM")] = _MiString("klausmate:" + lg_id)
    w3.add_annotation(0, lg_annot)
    with open(mi_working, "wb") as f:
        w3.write(f)
    lg_recs = pdf_handler.load_annotations(mi_uf, MI)
    lg_recs.append({"id": lg_id, "page": 0,
                    "rects": [[100.0, 368.0, 150.0, 24.0]],
                    "color": "#000000", "note": "", "kind": "text",
                    "text": "legacy adopted", "origin": "external"})
    pdf_handler.save_annotations(mi_uf, MI, lg_recs)
    mi_res = pdf_handler.scan_working_annotations(mi_uf, MI)
    check("marked id reported by scan",
          isinstance(mi_res, dict) and lg_id in (mi_res.get("marked_ids") or set()),
          repr(mi_res and mi_res.get("marked_ids")))
    check("legacy record survives the mirror",
          pdf_handler.mirror_foreign_annotations(mi_uf, MI, mi_res) == 0
          and any(r.get("id") == lg_id
                  for r in pdf_handler.load_annotations(mi_uf, MI)))
    check("bake carries the legacy copy",
          pdf_handler.bake_annotations(mi_uf, MI)
          and any(
              str(a.get_object().get("/NM") or "") == "klausmate:" + lg_id
              for a in (_MiReader(mi_working).pages[0].get("/Annots") or [])
          ))
except Exception as e:
    import traceback
    check("K-082 section", False,
          f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(mi_uf, ignore_errors=True)

print("== K-084: native deletes propagate; tombstone precision ==")
nd_uf = tempfile.mkdtemp(prefix="klaus_nd_uf_")
try:
    from pypdf import PdfReader as _NdReader, PdfWriter as _NdWriter
    from pypdf.generic import ArrayObject as _NdArray, NameObject as _NdName

    ND = "K84_Native"
    os.makedirs(os.path.join(nd_uf, "pdfs"))
    nd_working = os.path.join(nd_uf, "pdfs", ND + ".pdf")
    w = _NdWriter()
    w.add_blank_page(width=612, height=792)
    with open(nd_working, "wb") as f:
        w.write(f)

    ida, idb = "a1" * 16, "b2" * 16
    pdf_handler.save_annotations(nd_uf, ND, [
        {"id": ida, "page": 0, "rects": [[50.0, 100.0, 90.0, 12.0]],
         "color": "#fadc50", "note": ""},
        {"id": idb, "page": 0, "rects": [[50.0, 200.0, 90.0, 12.0]],
         "color": "#fadc50", "note": ""},
    ])
    nd_rep = {}
    check("bake reports the native ids it wrote",
          pdf_handler.bake_annotations(nd_uf, ND, report=nd_rep)
          and sorted(nd_rep.get("native_ids") or [])
          == sorted([ida, idb]), repr(nd_rep))
    pdf_handler.mark_native_baked(nd_uf, ND, nd_rep["native_ids"])

    def nd_strip(drop_ids):
        r = _NdReader(nd_working)
        w2 = _NdWriter(clone_from=r)
        for pg in w2.pages:
            raw = pg.get("/Annots")
            if raw is None:
                continue
            keep = [
                a for a in list(raw.get_object())
                if not any(
                    str(a.get_object().get("/NM") or "")
                    == "klausmate:" + d
                    for d in drop_ids
                )
            ]
            pg[_NdName("/Annots")] = _NdArray(keep)
        tmp = nd_working + ".tmp"
        with open(tmp, "wb") as f:
            w2.write(f)
        os.replace(tmp, nd_working)

    # User deletes highlight A in Preview; B survives -> the save KNEW
    # Klaus marks, so A's disappearance is deliberate.
    nd_strip([ida])
    nd_res = pdf_handler.scan_working_annotations(nd_uf, ND)
    check("native delete in Preview propagates",
          pdf_handler.mirror_foreign_annotations(nd_uf, ND, nd_res) == 1
          and [r.get("id") for r in pdf_handler.load_annotations(nd_uf, ND)]
          == [idb],
          repr(pdf_handler.load_annotations(nd_uf, ND)))

    # Unbaked record (debounce window): never removed by a mirror pass.
    idc = "c3" * 16
    nd_recs = pdf_handler.load_annotations(nd_uf, ND)
    nd_recs.append({"id": idc, "page": 0,
                    "rects": [[50.0, 300.0, 90.0, 12.0]],
                    "color": "#fadc50", "note": ""})
    pdf_handler.save_annotations(nd_uf, ND, nd_recs)
    nd_res = pdf_handler.scan_working_annotations(nd_uf, ND)
    pdf_handler.mirror_foreign_annotations(nd_uf, ND, nd_res)
    check("unbaked native record survives the mirror",
          sorted(r.get("id") for r in pdf_handler.load_annotations(nd_uf, ND))
          == sorted([idb, idc]))

    # K-087 POLICY REVERSAL: deleting the LAST Klaus mark used to be
    # refused as a possible stale-model clobber, which made a
    # single-highlight delete impossible. No content signal separates
    # the two cases, so the deletion is trusted and the record goes to
    # the recovery bucket. The unbaked record (idc) is still immune.
    nd_strip([idb])
    nd_res = pdf_handler.scan_working_annotations(nd_uf, ND)
    pdf_handler.mirror_foreign_annotations(nd_uf, ND, nd_res)
    check("deleting the last Klaus mark propagates",
          [r.get("id") for r in pdf_handler.load_annotations(nd_uf, ND)]
          == [idc],
          repr(pdf_handler.load_annotations(nd_uf, ND)))
    check("both outside deletions are recoverable from the bucket",
          [r.get("record", {}).get("id")
           for r in pdf_handler.load_removed_native(nd_uf, ND)]
          == [ida, idb],
          repr(pdf_handler.load_removed_native(nd_uf, ND)))

    # Tombstone precision: a tombstone blocks only the exact deleted
    # mark, not the neighborhood.
    ts_rec = {"id": "d4" * 16, "page": 0,
              "rects": [[100.0, 400.0, 60.0, 12.0]], "color": "#ffff00",
              "note": "", "origin": "external"}
    pdf_handler.add_suppressed(nd_uf, ND, ts_rec)
    identical = {"kind": "highlight", "page": 0,
                 "rects": [[100.0, 400.0, 60.0, 12.0]],
                 "note": "", "color": "#ffff00"}
    shifted = {"kind": "highlight", "page": 0,
               "rects": [[108.0, 400.0, 60.0, 12.0]],
               "note": "", "color": "#ffff00"}
    check("identical stale copy still blocked",
          pdf_handler.adopt_foreign_annotations(
              nd_uf, ND, scanned=[identical]) == 0)
    check("shifted NEW highlight at the same spot imports",
          pdf_handler.adopt_foreign_annotations(
              nd_uf, ND, scanned=[shifted]) == 1)

    # Expiry: a successful mirror scan with no trace of the stale copy
    # prunes the tombstone.
    nd_res = pdf_handler.scan_working_annotations(nd_uf, ND)
    pdf_handler.mirror_foreign_annotations(nd_uf, ND, nd_res)
    check("tombstone expires once the stale copy is gone",
          pdf_handler.load_suppressed(nd_uf, ND) == [],
          repr(pdf_handler.load_suppressed(nd_uf, ND)))
except Exception as e:
    import traceback
    check("K-084 section", False,
          f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(nd_uf, ignore_errors=True)

print("== K-085: satellite masking + bake omission ==")
sm_uf = tempfile.mkdtemp(prefix="klaus_sm_uf_")
try:
    from pypdf import PdfReader as _SmReader, PdfWriter as _SmWriter
    from pypdf.generic import ArrayObject as _SmArray, NameObject as _SmName

    SM = "K85_Sat"
    os.makedirs(os.path.join(sm_uf, "pdfs"))
    sm_working = os.path.join(sm_uf, "pdfs", SM + ".pdf")
    w = _SmWriter()
    w.add_blank_page(width=612, height=792)
    with open(sm_working, "wb") as f:
        w.write(f)

    idx, idb = "ee" * 16, "ff" * 16
    pdf_handler.save_annotations(sm_uf, SM, [
        {"id": idx, "page": 0, "rects": [[50.0, 100.0, 90.0, 12.0]],
         "color": "#fadc50", "note": "remember this"},
        {"id": idb, "page": 0, "rects": [[50.0, 300.0, 90.0, 12.0]],
         "color": "#fadc50", "note": ""},
    ])
    sm_rep = {}
    check("bake with note succeeds",
          pdf_handler.bake_annotations(sm_uf, SM, report=sm_rep))
    check("report lists both native ids, none omitted",
          sorted(sm_rep.get("native_ids") or []) == sorted([idx, idb])
          and sm_rep.get("omitted_native") == [], repr(sm_rep))
    check("report stat matches the written file",
          tuple(sm_rep.get("stat") or ()) == (lambda st: (
              st.st_ino, st.st_mtime_ns, st.st_size))(os.stat(sm_working)),
          repr(sm_rep.get("stat")))
    pdf_handler.mark_native_baked(sm_uf, SM, sm_rep["native_ids"])

    # Preview deletes the HIGHLIGHT of the noted record — its sticky
    # (klausmate:<id>:note) stays behind, as Preview treats them as
    # separate annotations.
    r = _SmReader(sm_working)
    w2 = _SmWriter(clone_from=r)
    for pg in w2.pages:
        raw = pg.get("/Annots")
        if raw is None:
            continue
        keep = [
            a for a in list(raw.get_object())
            if not (
                str(a.get_object().get("/NM") or "") == "klausmate:" + idx
                and str(a.get_object().get("/Subtype")) == "/Highlight"
            )
        ]
        pg[_SmName("/Annots")] = _SmArray(keep)
    tmp = sm_working + ".tmp"
    with open(tmp, "wb") as f:
        w2.write(f)
    os.replace(tmp, sm_working)

    sm_res = pdf_handler.scan_working_annotations(sm_uf, SM)
    check("orphaned sticky does NOT mask the deleted highlight",
          isinstance(sm_res, dict)
          and idx not in (sm_res.get("marked_ids") or set())
          and idb in (sm_res.get("marked_ids") or set()),
          repr(sm_res and sm_res.get("marked_ids")))

    # Resurrection race: records still hold the deleted mark when the
    # next bake fires — the bake must OMIT it, report it, and drop the
    # orphaned sticky, not regenerate them.
    sm_rep2 = {}
    check("bake succeeds post-delete",
          pdf_handler.bake_annotations(sm_uf, SM, report=sm_rep2))
    check("bake omits the externally deleted mark",
          sm_rep2.get("omitted_native") == [idx]
          and sm_rep2.get("native_ids") == [idb], repr(sm_rep2))
    sm_annots = [
        a.get_object()
        for a in (_SmReader(sm_working).pages[0].get("/Annots") or [])
    ]
    check("file regenerated without the mark or its orphan sticky",
          [str(o.get("/NM") or "") for o in sm_annots]
          == ["klausmate:" + idb],
          repr([(str(o.get("/Subtype")), str(o.get("/NM") or ""))
                for o in sm_annots]))

    # Viewer post-bake flow: drop omitted records, then ledger.
    check("remove_records drops by id",
          pdf_handler.remove_records(sm_uf, SM, sm_rep2["omitted_native"])
          == 1
          and [x.get("id") for x in pdf_handler.load_annotations(sm_uf, SM)]
          == [idb])
    pdf_handler.mark_native_baked(sm_uf, SM, sm_rep2["native_ids"])
    sm_res = pdf_handler.scan_working_annotations(sm_uf, SM)
    check("mirror settles quiet after the full flow",
          isinstance(sm_res, dict)
          and pdf_handler.mirror_foreign_annotations(sm_uf, SM, sm_res) == 0
          and [x.get("id") for x in pdf_handler.load_annotations(sm_uf, SM)]
          == [idb])
except Exception as e:
    import traceback
    check("K-085 section", False,
          f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(sm_uf, ignore_errors=True)

print("== K-086: stale mirror applies discarded; tombstone TTL ==")
st_uf = tempfile.mkdtemp(prefix="klaus_st_uf_")
try:
    from pypdf import PdfReader as _StReader, PdfWriter as _StWriter
    from pypdf.annotations import FreeText as _StFreeText

    ST = "K86_Stale"
    os.makedirs(os.path.join(st_uf, "pdfs"))
    st_working = os.path.join(st_uf, "pdfs", ST + ".pdf")

    def st_write(texts):
        w = _StWriter()
        w.add_blank_page(width=612, height=792)
        b = st_working + ".base"
        with open(b, "wb") as f:
            w.write(f)
        w2 = _StWriter(clone_from=_StReader(b))
        for text, y in texts:
            w2.add_annotation(0, _StFreeText(
                text=text, rect=(100, y, 250, y + 24), font_size="12pt",
                font_color="000000", border_color=None,
                background_color=None))
        tmp = st_working + ".tmp"
        with open(tmp, "wb") as f:
            w2.write(f)
        os.replace(tmp, st_working)
        os.remove(b)

    st_write([("mark A", 600), ("mark B", 500)])
    res_v1 = pdf_handler.scan_working_annotations(st_uf, ST)
    check("scan result carries the file fingerprint",
          isinstance(res_v1, dict) and bool(res_v1.get("stat")),
          repr(res_v1 and res_v1.get("stat")))
    # The file moves on (B deleted) while res_v1 is still in flight.
    time.sleep(0.01)
    st_write([("mark A", 600)])
    res_v2 = pdf_handler.scan_working_annotations(st_uf, ST)
    check("fresh scan applies",
          pdf_handler.mirror_foreign_annotations(st_uf, ST, res_v2) == 1
          and [r.get("text") for r in pdf_handler.load_annotations(st_uf, ST)]
          == ["mark A"])
    check("STALE scan is discarded, B is not resurrected",
          pdf_handler.mirror_foreign_annotations(st_uf, ST, res_v1) == 0
          and [r.get("text") for r in pdf_handler.load_annotations(st_uf, ST)]
          == ["mark A"],
          repr(pdf_handler.load_annotations(st_uf, ST)))

    # Tombstone TTL: an aged (or legacy ts-less) tombstone no longer
    # blocks a deliberate re-add; a fresh one still blocks resurrection.
    ghost = {"kind": "text", "page": 0,
             "rects": [[100.0, 168.0, 150.0, 24.0]],
             "text": "mark B", "note": "", "color": "#000000"}
    rec_b = {"id": "ab" * 16, "page": 0,
             "rects": [[100.0, 168.0, 150.0, 24.0]],
             "color": "#000000", "note": "", "kind": "text",
             "text": "mark B", "origin": "external"}
    pdf_handler.add_suppressed(st_uf, ST, rec_b)
    check("fresh tombstone still blocks the identical copy",
          pdf_handler.adopt_foreign_annotations(st_uf, ST, scanned=[ghost])
          == 0)
    sup = pdf_handler.load_suppressed(st_uf, ST)
    sup[-1]["ts"] = time.time() - 3600
    pdf_handler._update_doc_keys(st_uf, ST, {"suppressed_external": sup})
    check("aged tombstone no longer blocks a deliberate re-add",
          pdf_handler.adopt_foreign_annotations(st_uf, ST, scanned=[ghost])
          == 1)
except Exception as e:
    import traceback
    check("K-086 section", False,
          f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(st_uf, ignore_errors=True)

print("== K-087: Preview deletes propagate (ledger seed, no clobber guard) ==")
pv_uf = tempfile.mkdtemp(prefix="klaus_pv_uf_")
try:
    from pypdf import PdfReader as _PvReader, PdfWriter as _PvWriter

    PV = "K87_Del"
    os.makedirs(os.path.join(pv_uf, "pdfs"))
    pv_working = os.path.join(pv_uf, "pdfs", PV + ".pdf")
    w = _PvWriter()
    w.add_blank_page(width=612, height=792)
    with open(pv_working, "wb") as f:
        w.write(f)
    pv_json = os.path.join(pv_uf, "annotations", PV + ".json")

    idh = "77" * 16
    pdf_handler.save_annotations(pv_uf, PV, [
        {"id": idh, "page": 0, "rects": [[50.0, 100.0, 90.0, 12.0]],
         "color": "#fadc50", "note": ""},
    ])
    check("bake writes the mark", pdf_handler.bake_annotations(pv_uf, PV))
    # Ledger deliberately NOT recorded — the pre-K-084 situation.
    check("ledger starts empty", pdf_handler.load_baked_native(pv_uf, PV) == set())
    pv_res = pdf_handler.scan_working_annotations(pv_uf, PV)
    pdf_handler.mirror_foreign_annotations(pv_uf, PV, pv_res)
    check("ledger self-seeds from the observed mark",
          pdf_handler.load_baked_native(pv_uf, PV) == {idh},
          repr(pdf_handler.load_baked_native(pv_uf, PV)))

    # Preview deletes the ONLY Klaus mark -> zero marks left in the
    # file. K-084's clobber guard used to block this forever.
    pdf_handler._atomic_replace_from(
        os.path.join(pv_uf, "pdf_originals", PV + ".pdf"), pv_working
    )
    pv_res = pdf_handler.scan_working_annotations(pv_uf, PV)
    check("delete-them-all propagates",
          pdf_handler.mirror_foreign_annotations(pv_uf, PV, pv_res) == 1
          and pdf_handler.load_annotations(pv_uf, PV) == [])
    check("removed record is recoverable from the bucket",
          [r.get("record", {}).get("id")
           for r in pdf_handler.load_removed_native(pv_uf, PV)] == [idh],
          repr(pdf_handler.load_removed_native(pv_uf, PV)))
    check("ledger drops the removed id",
          pdf_handler.load_baked_native(pv_uf, PV) == set())

    # Legacy reconciliation: a json predating the ledger key at all.
    PL = "K87_Legacy"
    pl_working = os.path.join(pv_uf, "pdfs", PL + ".pdf")
    w = _PvWriter()
    w.add_blank_page(width=612, height=792)
    with open(pl_working, "wb") as f:
        w.write(f)
    pl_json = os.path.join(pv_uf, "annotations", PL + ".json")
    os.makedirs(os.path.dirname(pl_json), exist_ok=True)
    legacy = {"version": 1, "highlights": [
        {"id": "88" * 16, "page": 0, "rects": [[10.0, 10.0, 40.0, 12.0]],
         "color": "#fadc50", "note": ""}]}
    with open(pl_json, "w") as f:
        json.dump(legacy, f)
    # Records newer than the file (a bake still pending): KEEP.
    os.utime(pl_working, (time.time() - 60, time.time() - 60))
    pl_res = pdf_handler.scan_working_annotations(pv_uf, PL)
    pdf_handler.mirror_foreign_annotations(pv_uf, PL, pl_res)
    check("legacy file KEEPS records when the json is newer (bake pending)",
          len(pdf_handler.load_annotations(pv_uf, PL)) == 1)
    # File newer than the records: the file is authoritative.
    with open(pl_json, "w") as f:
        json.dump(legacy, f)
    os.utime(pl_json, (time.time() - 120, time.time() - 120))
    os.utime(pl_working, None)
    pl_res = pdf_handler.scan_working_annotations(pv_uf, PL)
    check("legacy leftovers removed when the pdf is newer",
          pdf_handler.mirror_foreign_annotations(pv_uf, PL, pl_res) == 1
          and pdf_handler.load_annotations(pv_uf, PL) == [])
    check("legacy reconciliation runs once (ledger key now present)",
          "baked_native_ids" in pdf_handler._load_annotation_doc(pv_uf, PL))

    # Observation-seeding in ISOLATION: ledger key present (no legacy
    # path) and this id was never recorded by a bake callback — only
    # seeing its mark in the file can make it deletable later.
    idn = "99" * 16
    pdf_handler.save_annotations(pv_uf, PL, [
        {"id": idn, "page": 0, "rects": [[20.0, 20.0, 40.0, 12.0]],
         "color": "#fadc50", "note": ""}])
    check("bake the unrecorded mark", pdf_handler.bake_annotations(pv_uf, PL))
    check("ledger does not know it yet",
          idn not in pdf_handler.load_baked_native(pv_uf, PL))
    pl_res = pdf_handler.scan_working_annotations(pv_uf, PL)
    pdf_handler.mirror_foreign_annotations(pv_uf, PL, pl_res)
    check("observing the mark seeds the ledger",
          idn in pdf_handler.load_baked_native(pv_uf, PL),
          repr(pdf_handler.load_baked_native(pv_uf, PL)))
    pdf_handler._atomic_replace_from(
        os.path.join(pv_uf, "pdf_originals", PL + ".pdf"), pl_working
    )
    pl_res = pdf_handler.scan_working_annotations(pv_uf, PL)
    check("seeded record is then deletable from outside",
          pdf_handler.mirror_foreign_annotations(pv_uf, PL, pl_res) == 1
          and pdf_handler.load_annotations(pv_uf, PL) == [])
except Exception as e:
    import traceback
    check("K-087 section", False,
          f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
finally:
    shutil.rmtree(pv_uf, ignore_errors=True)

print("== K-140: the dead editor state stays dead ==")
# _klausmate_target_field_index/_name were written at three sites and
# read at none — vestiges of autocomplete/Ask, removed in 2026-08.
# Anki's own editor.currentField is the whole mechanism; image crop
# rewrites by scanning note.fields and PDF page insert travels through
# the clipboard, so nothing downstream wants a Klaus-side copy.
_INIT_K140 = open("klausmate/__init__.py", encoding="utf-8").read()
check("no _klausmate_target_field_* ATTRIBUTE is written or read — a "
      "helpful re-add would be write-only state all over again. The "
      "_set_target_field FUNCTION is alive and is not what this pins.",
      "_klausmate_target_field" not in _INIT_K140
      and "def _set_target_field" in _INIT_K140)
check("...and the docstring says what DOES carry the target, so the "
      "next reader does not reinstate it",
      "currentField" in _INIT_K140)

print("== K-159: a baked text box keeps its size and colour ==")
# THE BUG, live: "the fonts don't render properly on the PDF viewer in
# Preview... they're always small." Vendored pypdf's FreeText builds
# /DA only inside `if border_color:` (and even then writes only a
# colour, never a font), and pdf_handler passes border_color=None
# deliberately — K-150's reasoning stands, Preview frames a text box
# only while it is selected. So /DA shipped EMPTY, size and colour
# lived only in /DS (the rich-text CSS string most readers ignore),
# and every note fell back to a reader default: small, black.
#
# MEASURED IN A RENDERER, not in a hex dump. PDFKit — the framework
# Preview itself draws with — reported, for a 24pt red record:
#     before:  font=Helvetica size=12.0  color=white 0   (i.e. black)
#     after:   font=Helvetica size=24.0  color=RGB 1 0 0
# and pdf.js (annotationMode ENABLE) agreed: defaultAppearanceData
# went from {fontSize:10, fontName:"", black} to {fontSize:24,
# fontName:"Helv", red}. /DR was tried and is NOT needed — PDFKit
# resolves /Helv with no resource dictionary and no /AcroForm.
check("the string is the PDF operator form, size then colour",
      pdf_handler.free_text_da("#ff0000", 24) == "/Helv 24 Tf 1 0 0 rg")
check("numbers are operands, not reprs — no 12.0, no 17 decimals",
      pdf_handler.free_text_da("#000000", 12.0) == "/Helv 12 Tf 0 0 0 rg"
      and pdf_handler.free_text_da("#fadc50", 13.5)
      == "/Helv 13.5 Tf 0.9804 0.8627 0.3137 rg")
check("a junk or absent colour falls back to the caller's default, "
      "never lands in the appearance string verbatim",
      pdf_handler.free_text_da(None, 12) == "/Helv 12 Tf 0 0 0 rg"
      and pdf_handler.free_text_da("rgb(1,2,3)", 12)
      == "/Helv 12 Tf 0 0 0 rg"
      and pdf_handler.free_text_da("#fff", 12) == "/Helv 12 Tf 0 0 0 rg")
try:
    _da_nonhex = pdf_handler.free_text_da("#12345g", 12)
except Exception as _da_exc:            # noqa: BLE001 - the point is that
    _da_nonhex = f"raised {_da_exc!r}"  # it must not raise
check("...including a SIX-character non-hex string — the length is "
      "not the check, the alphabet is (the shorter cases above all "
      "pass a length-only guard, so they pinned nothing on their own)",
      _da_nonhex == "/Helv 12 Tf 0 0 0 rg", repr(_da_nonhex))
check("a junk, zero, negative or non-finite size falls back to 12 — a "
      "`0 Tf` means auto-size to some readers and nothing to others",
      all(pdf_handler.text_point_size(v) == 12.0
          for v in (None, "big", 0, -3, float("nan"), float("inf"), [])))
check("a real size survives, ints and floats alike",
      pdf_handler.text_point_size(24) == 24.0
      and pdf_handler.text_point_size("18") == 18.0
      and pdf_handler.text_point_size(13.5) == 13.5)
check("one size constant feeds both appearance strings, so /DS and "
      "/DA can never disagree about a note's size",
      "font_size=f\"{pt}pt\"" in open(
          os.path.join(ADDON, "pdf_handler.py"), encoding="utf-8").read())

if not pdf_handler.BAKE_AVAILABLE:
    print("  SKIP pypdf unavailable — /DA bake round-trip unverified")
else:
    from pypdf import PdfReader as _DaReader, PdfWriter as _DaWriter
    from pypdf.annotations import FreeText as _DaFreeText

    # The hazard is REAL and still present in the vendored copy: build
    # a borderless FreeText pypdf's own way and its /DA is the empty
    # string. Without this the fix below could be guarding a case that
    # a pypdf bump had already fixed, and nobody would know.
    _da_probe = _DaFreeText(text="x", rect=(0, 0, 10, 10),
                            font_size="24pt", font_color="ff0000",
                            border_color=None, background_color=None)
    check("pypdf still writes an EMPTY /DA for a borderless box — the "
          "bug this fixes has not gone away underneath us",
          str(_da_probe.get("/DA")) == ""
          and "24pt" in str(_da_probe.get("/DS")))

    _da_uf = tempfile.mkdtemp(prefix="klaus_k159_")
    _DA_N = "K159_DA"
    os.makedirs(os.path.join(_da_uf, "pdfs"))
    _da_work = os.path.join(_da_uf, "pdfs", _DA_N + ".pdf")
    _w159 = _DaWriter()
    _w159.add_blank_page(width=612, height=792)
    with open(_da_work, "wb") as _fh159:
        _w159.write(_fh159)
    # A 24pt red note beside a 12pt black one: the pair Pouya can tell
    # apart at a glance, and the pair the renderers were checked with.
    _da_recs = [
        {"id": "e" * 32, "kind": "text", "page": 0,
         "rects": [[60.0, 80.0, 320.0, 40.0]], "text": "BIG RED 24pt",
         "note": "", "color": "#ff0000", "size": 24},
        {"id": "f" * 32, "kind": "text", "page": 0,
         "rects": [[60.0, 200.0, 220.0, 20.0]], "text": "small black 12pt",
         "note": "", "color": "#000000", "size": 12},
        {"id": "0" * 32, "kind": "text", "page": 0,
         "rects": [[60.0, 300.0, 220.0, 20.0]], "text": "junk style",
         "note": "", "color": "not-a-colour", "size": "huge"},
    ]
    pdf_handler.save_annotations(_da_uf, _DA_N, _da_recs)
    check("bake succeeds", pdf_handler.bake_annotations(_da_uf, _DA_N))
    _da_free = [
        a.get_object()
        for a in (_DaReader(_da_work).pages[0].get("/Annots") or [])
        if str(a.get_object().get("/Subtype")) == "/FreeText"
    ]
    _da_by_text = {str(o.get("/Contents")): o for o in _da_free}
    check("one FreeText per record", len(_da_free) == 3, repr(_da_by_text))
    check("the big red note carries its own size AND colour in /DA",
          str(_da_by_text["BIG RED 24pt"].get("/DA"))
          == "/Helv 24 Tf 1 0 0 rg",
          repr(str(_da_by_text["BIG RED 24pt"].get("/DA"))))
    check("the small black one carries its own, different, size",
          str(_da_by_text["small black 12pt"].get("/DA"))
          == "/Helv 12 Tf 0 0 0 rg")
    check("a junk style bakes as the 12pt black fallback rather than "
          "an unparseable operand a reader would choke on",
          str(_da_by_text["junk style"].get("/DA"))
          == "/Helv 12 Tf 0 0 0 rg")
    check("Klaus reads its OWN baked style back — before /DA existed "
          "_freetext_style saw (#000000, None) for every box, so an "
          "adopted copy of a Klaus note lost its size and colour",
          pdf_handler._freetext_style(_da_by_text["BIG RED 24pt"])
          == ("#ff0000", 24.0)
          and pdf_handler._freetext_style(
              _da_by_text["small black 12pt"]) == ("#000000", 12.0))
    # `.get("/W", -1)` rather than `["/W"]`: pypdf writes /BS only in
    # the border_color-is-None branch, so a border creeping back means
    # the key is ABSENT — and a KeyError here would abort the file
    # instead of reporting one honest failure.
    check("the border stays OFF — /DA and the border are separate "
          "concerns, and conflating them is what caused this (K-150: "
          "Preview frames a text box only while it is selected)",
          all(int((o.get("/BS") or {}).get("/W", -1)) == 0
              for o in _da_free)
          and all(o.get("/C") is None for o in _da_free),
          repr([(o.get("/BS"), o.get("/C")) for o in _da_free]))
    check("no /AcroForm or /DR was invented in the user's PDF — /Helv "
          "is a base-14 name readers resolve on their own (verified "
          "in PDFKit with neither present)",
          _DaReader(_da_work).trailer["/Root"].get("/AcroForm") is None
          and all(o.get("/DR") is None for o in _da_free))
    shutil.rmtree(_da_uf, ignore_errors=True)

print("== Task 11: the dead in-house assistant-loop modules are gone ==")
_DEL_MODS = ("llm_client", "entitlement", "assistant_session", "podcast",
             "assistant_panel")
for _dm in _DEL_MODS:
    check(f"klausmate/{_dm}.py no longer exists",
          not os.path.exists(os.path.join(ADDON, _dm + ".py")))

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEL_TESTS = tuple("test_" + m + ".py" for m in _DEL_MODS)
for _dt in _DEL_TESTS:
    check(f"tests/{_dt} no longer exists",
          not os.path.exists(os.path.join(_TESTS_DIR, _dt)))

_IMPORT_SHAPES = {
    _dm: _re.compile(
        r'import_module\(\s*["\']klausmate\.' + _re.escape(_dm) + r'["\']\s*\)'
        r'|from\s+klausmate\s+import\s+' + _re.escape(_dm) + r'\b'
        r'|from\s+klausmate\.' + _re.escape(_dm) + r'\s+import'
        r'|import\s+klausmate\.' + _re.escape(_dm) + r'\b'
    )
    for _dm in _DEL_MODS
}
for _tf in sorted(os.listdir(_TESTS_DIR)):
    if not _tf.endswith(".py") or _tf in _DEL_TESTS:
        continue
    with open(os.path.join(_TESTS_DIR, _tf), encoding="utf-8") as _fh:
        _tsrc = _fh.read()
    _hits = [_dm for _dm, _pat in _IMPORT_SHAPES.items() if _pat.search(_tsrc)]
    check(f"tests/{_tf} does not import a deleted module in its bootstrap",
          not _hits, str(_hits))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
