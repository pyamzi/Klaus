"""Headless tests for K-071: klausmate/projection.py (2D PCA-ish projection
of embedding vectors) and klausmate/pdf_graph.py (map node/edge assembly
built on top of it). Both are the headless data layer under the embedding
map window (klausmate/pdf_map.py, tested separately) — no window/canvas
here.

K-138 split the sample cap: ``fit_rows`` now bounds only the rows the two
component directions are FITTED from, and every row passed in gets a
point. The section named for it pins that split from both sides — the
output is complete, and the out-of-sample rows are really projected
rather than parked somewhere.

Style matches the other suites: standalone check()/report/sys.exit runner,
synthetic package stub so the addon's relative imports resolve (see
tests/test_klausmate.py's header), aqt stubbed only for the pdf_graph
section since projection.py itself must import with NO aqt/Qt present at
all — that is the whole point of the determinism/degenerate-input tests
running before any stub exists.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_projection.py
"""
from __future__ import annotations

import importlib
import math
import os
import random
import shutil
import sys
import tempfile
import time
import types
from array import array

ADDON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "klausmate"
)

# Synthetic package so relative imports inside the modules resolve; the
# harness's, so every USER_FILES lands in scratch, never the real Library.
sys.path.insert(0, os.path.join(os.path.dirname(ADDON), ".claude", "skills", "klaus-test", "scripts"))
from anki_stubs import install_package_stub  # noqa: E402

install_package_stub()
pkg = sys.modules["klausmate"]

# projection.py must be importable with NO aqt/Qt stub in place at all —
# that is proven simply by this import succeeding before any stub exists
# anywhere in this file.
projection = importlib.import_module("klausmate.projection")
card_index = importlib.import_module("klausmate.card_index")
pdf_handler = importlib.import_module("klausmate.pdf_handler")
pdf_index = importlib.import_module("klausmate.pdf_index")
drive_store = importlib.import_module("klausmate.drive_store")
pdf_graph = importlib.import_module("klausmate.pdf_graph")

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


def _rand_unit(base, jitter, dim, rng):
    v = [base[k] + rng.gauss(0, jitter) for k in range(dim)]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / norm for x in v))


# ---------------------------------------------------------------- projection

print("== projection: determinism ==")
rng = random.Random(42)
D = 96  # small + fast for the correctness tests; the timing test below uses 768
N_PER = 60
base_a = [1.0 if k % 5 == 0 else 0.0 for k in range(D)]
base_b = [1.0 if k % 5 == 2 else 0.0 for k in range(D)]
cluster_rows = [_rand_unit(base_a, 0.03, D, rng) for _ in range(N_PER)] + [
    _rand_unit(base_b, 0.03, D, rng) for _ in range(N_PER)
]

points1, idx1 = projection.project(cluster_rows, fit_rows=4000, seed=7)
points2, idx2 = projection.project(cluster_rows, fit_rows=4000, seed=7)
check("same seed -> identical points", points1 == points2)
check("same seed -> identical indices", idx1 == idx2)

points3, _idx3 = projection.project(cluster_rows, fit_rows=4000, seed=1)
check(
    "different seed does not (trivially) reuse the same start vector",
    points3 != points1,
)

print("== projection: cluster separation ==")
cluster_a_pts = points1[:N_PER]
cluster_b_pts = points1[N_PER:]


def _centroid(pts):
    """Mean position, over however many axes a point has (two before
    K-148, three after)."""
    cols = list(zip(*pts))
    return tuple(sum(c) / len(c) for c in cols)


def _avg_dist(pts, c):
    return sum(math.dist(p, c) for p in pts) / len(pts)


ca = _centroid(cluster_a_pts)
cb = _centroid(cluster_b_pts)
inter = math.dist(ca, cb)
intra_a = _avg_dist(cluster_a_pts, ca)
intra_b = _avg_dist(cluster_b_pts, cb)
check(
    "two well-separated 768-... err 96-d clusters land well-separated in 3D",
    inter > 3 * max(intra_a, intra_b),
    f"inter={inter:.3f} intra_a={intra_a:.3f} intra_b={intra_b:.3f}",
)

print("== projection: fit_rows caps the FIT, never the output (K-138) ==")
# Pouya asked for every note on the map. The sample cap moved off the
# output and onto the component fit: rows outside the stride sample are
# still projected onto the directions it found. These pins are what stop
# a future "perf fix" from quietly reintroducing a sampled map.
small_rows = [array("f", [float(k), float(k + 1), float(k + 2)]) for k in range(100)]
pts, idxs = projection.project(small_rows, fit_rows=10, seed=0)
check(
    "a fit sample a tenth the size still returns EVERY row as a point",
    len(pts) == 100 and len(idxs) == 100,
    f"{len(pts)} points from 100 rows",
)
check(
    "indices name every row in order — nothing is dropped or reordered",
    idxs == list(range(100)),
)

pts_all, idxs_all = projection.project(small_rows, fit_rows=1000, seed=0)
check(
    "a cap wider than the input changes nothing",
    len(pts_all) == 100 and idxs_all == list(range(100)),
)
check(
    "the old output cap is gone by NAME too, so a stale caller fails loudly",
    hasattr(projection, "DEFAULT_FIT_ROWS")
    and not hasattr(projection, "DEFAULT_MAX_POINTS"),
)

# Out-of-sample rows must land where the fit says, not at some fallback.
# Two clusters, fit from 8 evenly-strided rows out of 120: if scoring
# only worked for sampled rows the cluster split would collapse.
_orng = random.Random(5)
_ocl = [_rand_unit(base_a, 0.03, D, _orng) for _ in range(60)] + [
    _rand_unit(base_b, 0.03, D, _orng) for _ in range(60)
]
_opts, _oidx = projection.project(_ocl, fit_rows=8, seed=0)
_sampled = set(projection._stride_indices(120, 8))
_oa = _centroid([p for k, p in enumerate(_opts) if k < 60 and k not in _sampled])
_ob = _centroid([p for k, p in enumerate(_opts) if k >= 60 and k not in _sampled])
check(
    "rows OUTSIDE the fit sample still separate by cluster — they are "
    "projected onto the fitted axes, not parked at a default",
    len(_opts) == 120 and math.dist(_oa, _ob) > 0.5,
    f"dist={math.dist(_oa, _ob):.3f}",
)

# Axis normalization has to span every point, or an out-of-sample
# extreme would render outside the [-1, 1] box the canvas fits to.
_ext = [array("f", [float(k), 0.0, 0.0]) for k in range(21)]
_ext.append(array("f", [500.0, 0.0, 0.0]))  # index 21: never in a 4-row stride
_epts, _ = projection.project(_ext, fit_rows=4, seed=0)
_ex = [p[0] for p in _epts]
check(
    "both axes normalize over ALL points, so an out-of-sample extreme "
    "still lands on the [-1, 1] edge rather than off the map",
    len(_epts) == 22
    and abs(min(_ex) - (-1.0)) < 1e-12
    and abs(max(_ex) - 1.0) < 1e-12
    and abs(_ex[21]) == 1.0,
    f"min={min(_ex)} max={max(_ex)} last={_ex[21]}",
)

# The zip-based pre-3.12 _sumprod fallback truncates silently, so a short
# row must be caught by an explicit length check on EVERY row now that
# every row is scored — not just on the ones inside the fit sample.
_ragged = [array("f", [1.0, 0.0, 0.0])] * 4 + [array("f", [1.0, 0.0])]
try:
    projection.project(_ragged, fit_rows=2, seed=0)
    _raised = False
except ValueError:
    _raised = True
check(
    "a ragged row OUTSIDE the fit sample raises instead of scoring "
    "against a truncated component",
    _raised,
)

print("== projection: degenerate inputs ==")
empty_pts, empty_idx = projection.project([], fit_rows=10, seed=0)
check("0 rows -> empty output, no crash", empty_pts == [] and empty_idx == [])

one_pts, one_idx = projection.project(
    [array("f", [1.0, 2.0, 3.0])], fit_rows=10, seed=0
)
check(
    "1 row -> single point at the origin, no div-by-zero",
    one_pts == [(0.0, 0.0, 0.0)] and one_idx == [0],
)

identical = [array("f", [1.0, 2.0, 3.0]) for _ in range(6)]
ident_pts, ident_idx = projection.project(identical, fit_rows=10, seed=0)
check(
    "identical rows -> every point collapses to the origin, no div-by-zero",
    ident_pts == [(0.0, 0.0, 0.0)] * 6 and ident_idx == list(range(6)),
)

print("== projection: rough timing on a synthetic 4000x768 input ==")
big_rng = random.Random(99)
D_BIG = 768
N_BIG = 4000
big_base_a = [1.0 if k % 7 == 0 else 0.0 for k in range(D_BIG)]
big_base_b = [1.0 if k % 7 == 3 else 0.0 for k in range(D_BIG)]
big_rows = [
    _rand_unit(big_base_a, 0.05, D_BIG, big_rng) for _ in range(N_BIG // 2)
] + [_rand_unit(big_base_b, 0.05, D_BIG, big_rng) for _ in range(N_BIG // 2)]

t0 = time.time()
big_points, big_idx = projection.project(big_rows, fit_rows=4000, seed=0)
elapsed = time.time() - t0
check(
    "4000x768 input projects to 4000 points without crashing",
    len(big_points) == 4000 and len(big_idx) == 4000,
)
big_ca = _centroid(big_points[: N_BIG // 2])
big_cb = _centroid(big_points[N_BIG // 2 :])
check(
    "4000x768: the two halves still separate",
    math.dist(big_ca, big_cb) > 0.5,
    f"dist={math.dist(big_ca, big_cb):.3f}",
)
print(f"  .. projected {N_BIG}x{D_BIG} in {elapsed:.2f}s (no numpy, no C ext)")


# --------------------------------------------------------------- pdf_graph
#
# retention.py (imported lazily, inside build_graph_data) pulls in aqt at
# its own module top via curation.py -- stub exactly what test_klausmate.py
# already stubs for the identical reason, so importing it doesn't require
# a live Anki.

print("== pdf_graph: aqt stub + scratch store ==")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class _AnyOp:
    def __init__(self, *a, **k):
        pass

    def success(self, *a, **k):
        return self

    def failure(self, *a, **k):
        return self

    def without_collection(self):
        return self

    def run_in_background(self):
        pass


aqt_mod = _stub("aqt", mw=None)
aqt_mod.dialogs = types.SimpleNamespace(open=lambda *a, **k: None)
_stub("aqt.operations", CollectionOp=_AnyOp, QueryOp=_AnyOp)
_stub(
    "aqt.utils",
    tooltip=lambda *a, **k: None,
    askUser=lambda *a, **k: False,
    showWarning=lambda *a, **k: None,
)
_stub("aqt.qt", QAction=object, QInputDialog=object, QMessageBox=object, qconnect=lambda *a, **k: None)
_stub("aqt.gui_hooks")
aqt_mod.gui_hooks = sys.modules["aqt.gui_hooks"]
_stub("anki")
_stub("anki.collection", AddNoteRequest=object)

retention = importlib.import_module("klausmate.retention")

tmp = tempfile.mkdtemp(prefix="klaus_test_projection_")
try:
    os.makedirs(os.path.join(tmp, "contexts"))

    # -- card index: 20 notes, small dims, well within max_points --------
    dims = 32
    nids = list(range(1, 21))
    rng2 = random.Random(3)
    vecs = [_rand_unit([1.0] + [0.0] * (dims - 1), 0.2, dims, rng2) for _ in nids]
    cidx = card_index.CardIndex(
        provider="voyage",
        model="voyage-3-lite",
        dims=dims,
        nids=list(nids),
        mods=[0] * len(nids),
        hashes=[f"h{n}" for n in nids],
        vectors=array("f"),
    )
    for v in vecs:
        cidx.vectors.extend(v)
    card_index.save(cidx, os.path.join(tmp, "card_index"))
    cidx = card_index.load(os.path.join(tmp, "card_index"))
    check("scratch card index round-trips", cidx is not None and len(cidx.nids) == 20)

    sig = (cidx.provider, cidx.model)
    digest = retention.card_index_digest(cidx)

    # -- three PDFs: A and B get a match cache, C never does -------------
    def _write_context(name: str) -> tuple[int, int]:
        path = os.path.join(tmp, "contexts", name + ".txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("synthetic pdf text for " + name)
        return pdf_index.source_signature(tmp, name)

    src_a = _write_context("PdfA")
    src_b = _write_context("PdfB")
    src_c = _write_context("PdfC")  # enumerated, but gets no matches.json

    retention.USER_FILES = tmp  # redirect the module-global path, same
    # pattern tests/test_klausmate.py uses to point retention at a scratch
    # dir instead of the real klausmate/user_files.

    matches_a = [(1, 0.90), (2, 0.85), (3, 0.40)]
    matches_b = [(5, 0.95), (6, 0.20)]
    retention.save_matches("PdfA", sig, cidx.dims, src_a, digest, matches_a, {})
    retention.save_matches("PdfB", sig, cidx.dims, src_b, digest, matches_b, {})
    # PdfC deliberately gets no matches.json at all.

    drive_store.record_import(tmp, "PdfA", "Physiology Lecture 1.pdf")
    drive_store.set_folder(tmp, "PdfA", "Anatomy")
    retention.set_threshold("PdfB", 0.1)  # per-PDF override: include nid 6 too

    check(
        "PdfC has no match cache on disk",
        retention.load_matches("PdfC", sig, cidx.dims, src_c, digest) is None,
    )

    data = pdf_graph.build_graph_data(tmp, {})

    print("== pdf_graph: node/edge counts ==")
    check("every note gets a positioned node", len(data["notes"]) == 20)
    check(
        "note nids match the card index exactly",
        {n["nid"] for n in data["notes"]} == set(nids),
    )
    pdf_by_safe = {p["safe"]: p for p in data["pdfs"]}
    check(
        "PdfA and PdfB have nodes, PdfC (absent cache) is skipped",
        set(pdf_by_safe) == {"PdfA", "PdfB"},
        str(sorted(pdf_by_safe)),
    )
    check(
        "PdfA: default threshold (0.45) keeps nid 1 and 2, drops nid 3 (0.40)",
        pdf_by_safe["PdfA"]["match_count"] == 2,
        str(pdf_by_safe.get("PdfA")),
    )
    check(
        "PdfA: display name + folder come from drive_store",
        pdf_by_safe["PdfA"]["display"] == "Physiology Lecture 1.pdf"
        and pdf_by_safe["PdfA"]["folder"] == "Anatomy",
    )
    check(
        "PdfB: per-PDF threshold override (0.1) keeps both nid 5 and 6",
        pdf_by_safe["PdfB"]["match_count"] == 2,
        str(pdf_by_safe.get("PdfB")),
    )
    check(
        "PDF nodes never claim a live retention score headlessly",
        all(p["retention"] is None for p in data["pdfs"]),
    )

    edges_by_pdf: dict[str, set[int]] = {}
    for e in data["edges"]:
        edges_by_pdf.setdefault(e["pdf"], set()).add(e["nid"])
    check(
        "edges: PdfA -> {1, 2} only (nid 3 below threshold)",
        edges_by_pdf.get("PdfA") == {1, 2},
        str(edges_by_pdf.get("PdfA")),
    )
    check(
        "edges: PdfB -> {5, 6} (per-PDF override applied)",
        edges_by_pdf.get("PdfB") == {5, 6},
        str(edges_by_pdf.get("PdfB")),
    )
    check("no edge references the skipped PdfC", "PdfC" not in edges_by_pdf)
    check("edge/node counts agree", len(data["edges"]) == 4 and len(data["pdfs"]) == 2)

    print("== pdf_graph: centroid consistency ==")
    note_xyz = {n["nid"]: tuple(n["xyz"]) for n in data["notes"]}
    exp = tuple(
        (note_xyz[1][k] + note_xyz[2][k]) / 2 for k in range(3)
    )
    got = tuple(pdf_by_safe["PdfA"]["xyz"])
    check(
        "PdfA's node sits at the centroid of its (thresholded) matched "
        "notes — on the DEPTH axis too, or the node would float on the "
        "z=0 plane while its own notes sat in front of and behind it",
        len(got) == 3 and all(abs(got[k] - exp[k]) < 1e-9 for k in range(3)),
        f"got={got} exp={exp}",
    )
    check(
        "every note row carries three numbers under the key xyz",
        all(len(n["xyz"]) == 3 and "xy" not in n for n in data["notes"]),
    )

    print("== pdf_graph: repeat call is stable ==")
    data2 = pdf_graph.build_graph_data(tmp, {})
    check(
        "build_graph_data is deterministic across repeated calls",
        data == data2,
    )

    print("== pdf_graph: empty card index -> empty graph, no crash ==")
    empty_tmp = tempfile.mkdtemp(prefix="klaus_test_projection_empty_")
    try:
        empty_data = pdf_graph.build_graph_data(empty_tmp, {})
        check(
            "no card index at all -> empty graph rather than a crash",
            empty_data == {"pdfs": [], "notes": [], "edges": []},
        )
    finally:
        shutil.rmtree(empty_tmp, ignore_errors=True)

finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------- pdf_graph layout cache
#
# K-167. Measured on Pouya's real 28,670-note index: build_graph_data was
# 29.5 s, of which projection.project was 29.47 s and the FIT alone 29.29 s.
# Everything else — the card index off disk, the match caches, the drive
# store — is 0.07 s put together. The layout is a pure function of the card
# index (project is seeded and deterministic by its own contract), so it is
# cached and a repeat open reads positions instead of re-deriving them.
#
# POSITIONS ONLY, deliberately: see pdf_graph's own note for the measurement
# that killed fit reuse. The cache is keyed on the card index and NOTHING
# else, so thresholds and match caches still take effect on the next open.

print("== pdf_graph: the layout cache (K-167) ==")

cache_tmp = tempfile.mkdtemp(prefix="klaus_test_projection_cache_")
try:
    C_DIMS = 24
    C_NIDS = list(range(101, 141))
    _rngc = random.Random(17)
    _cdir = os.path.join(cache_tmp, "card_index")
    _ldir = os.path.join(cache_tmp, pdf_graph.LAYOUT_SUBDIR)
    _lfile = os.path.join(_ldir, pdf_graph.LAYOUT_FILE)

    def _mk_index(provider="voyage", model="voyage-3-lite", dims=C_DIMS,
                  nids=None, extra_hash=None):
        nids = list(C_NIDS if nids is None else nids)
        ix = card_index.CardIndex(
            provider=provider, model=model, dims=dims, nids=nids,
            mods=[0] * len(nids),
            hashes=[(extra_hash or "c") + str(n) for n in nids],
            vectors=array("f"),
        )
        r = random.Random(17)
        for _ in nids:
            ix.vectors.extend(
                _rand_unit([1.0] + [0.0] * (dims - 1), 0.3, dims, r)
            )
        card_index.save(ix, _cdir)
        return ix

    _mk_index()
    os.makedirs(os.path.join(cache_tmp, "contexts"))
    retention.USER_FILES = cache_tmp

    # One PDF with a match cache, so the graph has a node whose threshold
    # can be moved later without touching the card index.
    with open(os.path.join(cache_tmp, "contexts", "PdfZ.txt"), "w",
              encoding="utf-8") as f:
        f.write("synthetic pdf text for PdfZ")
    _cz = card_index.load(_cdir)
    _sigz = (_cz.provider, _cz.model)
    retention.save_matches(
        "PdfZ", _sigz, _cz.dims, pdf_index.source_signature(cache_tmp, "PdfZ"),
        retention.card_index_digest(_cz),
        [(101, 0.95), (102, 0.90), (103, 0.40)], {},
    )

    # Count real projections rather than forbidding them: a spy that RAISED
    # would be swallowed by any try/except around the call and read as a
    # pass. A counter cannot be swallowed.
    _proj_calls: list[int] = []
    _real_project = projection.project

    def _counting_project(rows, **kw):
        _proj_calls.append(len(rows))
        return _real_project(rows, **kw)

    def _build(cfg=None):
        """One build_graph_data call -> (graph, projections it ran)."""
        before = len(_proj_calls)
        data = pdf_graph.build_graph_data(cache_tmp, cfg or {})
        return data, len(_proj_calls) - before

    projection.project = _counting_project
    try:
        cold, n_cold = _build()
        warm, n_warm = _build()

        check("a cold build runs the projection exactly once", n_cold == 1,
              f"ran {n_cold}")
        check("...and leaves a layout cache on disk", os.path.isfile(_lfile))
        check(
            "a warm build never runs the projection at all — that fit IS "
            "the 29.5 s wait this card exists to delete",
            n_warm == 0, f"ran {n_warm}",
        )
        check(
            "...and returns a BIT-IDENTICAL graph, not merely a similar "
            "one: a float32 store would move every note by ~1e-8 and this "
            "is the only pin that would notice",
            warm == cold,
        )
        check("the cached graph is not empty (it would trivially match)",
              len(cold["notes"]) == len(C_NIDS) and len(cold["pdfs"]) == 1)

        # The cache is keyed on the CARD INDEX, never on cfg or on the
        # per-PDF prefs — freezing the whole graph would make a
        # sensitivity edit invisible until the next re-embed.
        retention.set_threshold("PdfZ", 0.2)
        moved, n_moved = _build()
        check(
            "a threshold edit still lands on the very next open — the "
            "cache holds positions, not the graph",
            moved["pdfs"][0]["match_count"] == 3 and n_moved == 0,
            f"count={moved['pdfs'][0]['match_count']} projections={n_moved}",
        )
        retention.set_threshold("PdfZ", 0.75)

        # ---- invalidation -------------------------------------------
        _digest_before = retention.card_index_digest(card_index.load(_cdir))
        _mk_index(nids=C_NIDS + [999])
        _, n_added = _build()
        check("a note added to the index re-projects", n_added == 1,
              f"ran {n_added}")
        _mk_index()  # back to the original 40 notes
        _build()

        # A note EDITED rather than added: same nids, same row count, new
        # text hash. Every size and count check still agrees with the
        # stored file, so the DIGEST is the only thing that can catch it —
        # found by falsification, because deleting the digest check on its
        # own left the added-a-note pin above green.
        _mk_index(extra_hash="edited-")
        check(
            "editing note text moves the digest without moving the row "
            "count", retention.card_index_digest(card_index.load(_cdir))
            != _digest_before,
        )
        _, n_edit = _build()
        check("...and re-projects on that alone", n_edit == 1,
              f"ran {n_edit}")
        _mk_index()
        _build()

        # Re-embedding on a new model rewrites every VECTOR and no note
        # TEXT — so nids and hashes, and therefore the digest, come back
        # bit-identical. Only (provider, model, dims) moves. A cache that
        # does not gate on the signature would draw the map from another
        # embedding space's coordinates: silently wrong, never an error.
        _mk_index(model="voyage-3.5")
        check(
            "re-embedding on a new model leaves the card-index digest "
            "identical — the digest alone CANNOT see this",
            retention.card_index_digest(card_index.load(_cdir))
            == _digest_before,
        )
        _, n_model = _build()
        check("a provider/model change re-projects anyway", n_model == 1,
              f"ran {n_model}")

        # Same provider and model, narrower vectors (OpenAI's MRL widths):
        # same texts, so the same digest again, and only the width moves.
        _mk_index(model="voyage-3.5", dims=12)
        check(
            "a width change also leaves the digest identical",
            retention.card_index_digest(card_index.load(_cdir))
            == _digest_before,
        )
        _, n_dims = _build()
        check("a dims change re-projects — vectors of different widths are "
              "not the same space", n_dims == 1, f"ran {n_dims}")
        _mk_index()
        _build()

        _saved_comps = projection.COMPONENTS
        try:
            projection.COMPONENTS = 2
            _, n_two = _build()
        finally:
            projection.COMPONENTS = _saved_comps
        check("changing the component count re-projects", n_two == 1,
              f"ran {n_two}")
        _, n_three = _build()
        check("...and coming back to three does NOT reuse the 2-component "
              "file", n_three == 1, f"ran {n_three}")

        # Found by falsification: the two checks above pass with the whole
        # params key DELETED, because a component count is also a point
        # WIDTH and the size check catches it for free. These two do not
        # change any byte count at all — a retuned iteration count or fit
        # sample moves every point while the file stays perfectly
        # well-formed, and the params key is the only thing that sees it.
        # projection.py's docstring tells the next reader not to buy speed
        # with iterations; this is what stops them buying a stale map.
        for _attr, _val in (("MAX_ITERATIONS", 8), ("DEFAULT_FIT_ROWS", 12)):
            _keep = getattr(projection, _attr)
            try:
                setattr(projection, _attr, _val)
                _, _n_par = _build()
            finally:
                setattr(projection, _attr, _keep)
            check(
                f"retuning projection.{_attr} re-projects — it moves every "
                "point without moving one byte count",
                _n_par == 1, f"ran {_n_par}",
            )
            _build()  # settle the cache back at the shipping value

        # K-171: build_graph_data now aligns a freshly-projected layout
        # onto whatever PRIOR layout it can still read (see
        # projection.align_to / pdf_graph._read_prior_layout), so its
        # output is no longer a pure function of the card index alone —
        # by design, that is exactly what buys continuity across a
        # resample. Every corruption/removal test below destroys the one
        # layout file that could have served as that prior, so each of
        # them independently falls back to the SAME "no prior available"
        # answer. `good` has to be THAT answer, not whatever the cache
        # happened to hold a moment ago (which may itself be aligned to
        # something two builds back) — clearing the file first makes
        # `good` the deterministic baseline every recovery path below
        # converges to, so the old bit-identical comparison still means
        # something.
        os.remove(_lfile)
        good, _ = _build()

        # ---- corrupt / truncated / partial reads as ABSENT ------------
        _whole = open(_lfile, "rb").read()

        def _corrupt(label, payload):
            with open(_lfile, "wb") as fh:
                fh.write(payload)
            try:
                data, ran = _build()
            except Exception as exc:  # noqa: BLE001 - that IS the check
                check(f"corrupt cache ({label}) reads as absent", False,
                      f"raised {type(exc).__name__}: {exc}")
                return
            check(
                f"corrupt cache ({label}) reads as absent: re-projects and "
                "returns the right graph, never raises and never a stale "
                "picture",
                ran == 1 and data == good,
                f"projections={ran} same={data == good}",
            )

        _corrupt("truncated mid-body", _whole[: len(_whole) // 2])
        _corrupt("empty file", b"")
        _corrupt("no header newline", b'{"version": 1}')
        _corrupt("header is not json", b"not json at all\n" + _whole[-64:])
        _corrupt("body not a whole number of doubles",
                 _whole + b"\x00\x00\x00")
        _corrupt("header from a future version",
                 _whole.replace(
                     b'"version":%d' % pdf_graph.LAYOUT_VERSION,
                     b'"version":%d' % (pdf_graph.LAYOUT_VERSION + 1), 1))
        _hdr, _body = _whole.split(b"\n", 1)
        _corrupt("header row count disagrees with the body",
                 _hdr.replace(b'"rows":%d' % len(C_NIDS), b'"rows":7', 1)
                 + b"\n" + _body)
        # Internally consistent and still wrong: a header claiming 7 rows
        # with a body of exactly 7 points passes every size and checksum-
        # shaped test. Only "does this name as many rows as the index has"
        # catches it, and without that the 7 points zip against 40 nids and
        # 33 notes vanish from the map without a word.
        _corrupt("header AND body both claim 7 of the index's 40 rows",
                 _hdr.replace(b'"rows":%d' % len(C_NIDS), b'"rows":7', 1)
                 + b"\n" + _body[: 7 * projection.COMPONENTS * 8])

        # ---- a cache that cannot be WRITTEN must not break the map -----
        _build()  # restore a good cache, then take the directory away
        os.remove(_lfile)
        os.chmod(_ldir, 0o500)
        try:
            ro, ro_ran = _build()
            check(
                "an unwritable cache directory costs the fit, not the map: "
                "correct graph, no exception",
                ro == good and ro_ran == 1,
                f"same={ro == good} projections={ro_ran}",
            )
        except Exception as exc:  # noqa: BLE001
            check("an unwritable cache directory costs the fit, not the map",
                  False, f"raised {type(exc).__name__}: {exc}")
        finally:
            os.chmod(_ldir, 0o700)
    finally:
        projection.project = _real_project

    print("== pdf_graph: K-171 alignment is actually WIRED into build_graph_data ==")
    # The pure-function tests above (projection.align_to / normalize_points)
    # prove the ALGORITHM works in isolation. They prove nothing about
    # whether build_graph_data actually CALLS it — a build_graph_data that
    # silently stopped calling align_to would leave every one of those
    # tests green while the actual map kept reshuffling for the user, which
    # is the one thing this card was filed to stop. Spy on align_to itself
    # (the same counting-spy idiom this file already uses for
    # projection.project above), rather than re-deriving numeric proof a
    # second time.
    if os.path.exists(_lfile):
        os.remove(_lfile)
    _mk_index()  # fresh, known-clean state — prior tests left _lfile corrupted/removed variously

    _align_calls: list[int] = []
    _real_align_to = projection.align_to

    def _counting_align_to(*args, **kwargs):
        _align_calls.append(1)
        return _real_align_to(*args, **kwargs)

    projection.align_to = _counting_align_to
    try:
        _build()  # cold build: no layout file exists yet
        check("no prior layout on disk -> build_graph_data never calls align_to",
              len(_align_calls) == 0, f"calls={len(_align_calls)}")

        # A second "import cycle" over the SAME notes (K-171's actual
        # scenario: a re-embed, not a collection change) — extra_hash
        # changes card_index_digest so this does NOT hit the K-167 exact-
        # digest cache above (which would skip projection, and align_to
        # with it, entirely); nids/provider/model/dims stay identical so
        # _read_prior_layout's signature check still accepts the prior.
        _mk_index(extra_hash="reembed-")
        _build()
        check("a prior layout with matching signature and overlapping ids "
              "-> build_graph_data DOES call align_to",
              len(_align_calls) == 1, f"calls={len(_align_calls)}")
    finally:
        projection.align_to = _real_align_to

    print("== pdf_graph: an empty index caches nothing ==")
    _empty2 = tempfile.mkdtemp(prefix="klaus_test_projection_cache_empty_")
    try:
        pdf_graph.build_graph_data(_empty2, {})
        check(
            "no card index -> no layout directory invented beside it",
            not os.path.exists(
                os.path.join(_empty2, pdf_graph.LAYOUT_SUBDIR)
            ),
        )
    finally:
        shutil.rmtree(_empty2, ignore_errors=True)
finally:
    shutil.rmtree(cache_tmp, ignore_errors=True)

print("== pdf_graph: the cache's signature gate is not hand-spelled ==")
# Widening index_signature from (provider, model) to (provider, model, dims)
# broke EIGHT call sites at once, and silently: a two-tuple compared against
# a three-tuple is simply never equal, so every cache read as stale and the
# collection was re-embedded on a paid API. test_klausmate.py pins the six
# modules that existed then by regex; this is the same pin for the cache
# this card added, done structurally so it cannot be dodged by spelling.
import ast as _ast  # noqa: E402 - local to this section, like the AST pins
                    # in test_index_queue.py

_PG_SRC = open(os.path.join(ADDON, "pdf_graph.py"), encoding="utf-8").read()
_PG_TREE = _ast.parse(_PG_SRC)


def _fn(tree, name):
    return next(
        (n for n in _ast.walk(tree)
         if isinstance(n, _ast.FunctionDef) and n.name == name),
        None,
    )


_sig_fn = _fn(_PG_TREE, "_signature_ok")
check(
    "the layout cache's signature gate is its own named function",
    _sig_fn is not None,
)
check(
    "...and never spells an == or != itself — a hand-written tuple "
    "comparison is what read every cache as stale and silently re-embedded "
    "on a paid API when the signature grew a third element",
    _sig_fn is not None
    and not [
        n for n in _ast.walk(_sig_fn)
        if isinstance(n, _ast.Compare)
        and any(isinstance(op, (_ast.Eq, _ast.NotEq)) for op in n.ops)
    ],
)
check(
    "...it delegates to embeddings.signature_matches",
    _sig_fn is not None
    and any(
        isinstance(n, _ast.Attribute) and n.attr == "signature_matches"
        for n in _ast.walk(_sig_fn)
    ),
)
_write_fn = _fn(_PG_TREE, "_write_blob")
check(
    "the cache is written tmp-then-os.replace, retention_history's shape — "
    "a half-written layout must be impossible, not merely unlikely",
    _write_fn is not None
    and any(isinstance(n, _ast.Attribute) and n.attr == "replace"
            for n in _ast.walk(_write_fn)),
)


print("== projection: the SECOND component is pinned (deflation) ==")
# Review-added (K-071 sign-off): with the deflation step disabled, every
# other test in this file stayed green — the second axis was unpinned, so
# a regression could ship a 1-D map disguised as 2-D (all points on a
# diagonal). Build data with variance along two orthogonal directions:
# axis 1 must separate the wide split, axis 2 must still carry the
# narrow one, and the two score vectors must be (near-)uncorrelated —
# with broken deflation ys duplicates xs and |corr| -> 1.
_rngq = random.Random(7)
_D = 64
_quad_rows = []
for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        for _ in range(25):
            _row = [_rngq.gauss(0.0, 0.02) for _ in range(_D)]
            _row[0] += 3.0 * _sx   # wide split  -> PC1
            _row[1] += 1.0 * _sy   # narrow split -> PC2
            _quad_rows.append(array("f", _row))
_qpts, _ = projection.project(_quad_rows, fit_rows=1000, seed=0)
_qx = [p[0] for p in _qpts]
_qy = [p[1] for p in _qpts]


def _corr(a, b):
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va > 0 and vb > 0 else 1.0


check(
    "axis-1/axis-2 scores are uncorrelated (|corr| < 0.2)",
    abs(_corr(_qx, _qy)) < 0.2,
    f"corr={_corr(_qx, _qy):.4f}",
)
# The narrow split must be visible on axis 2: rows 0-49 carry _sy=-1,
# wait — ordering is (sx,sy): groups of 25 as (-,-)(-,+)(+,-)(+,+).
_y_neg = _qy[0:25] + _qy[50:75]
_y_pos = _qy[25:50] + _qy[75:100]
_gap = abs(sum(_y_pos) / 50 - sum(_y_neg) / 50)
_spread = max(
    1e-9,
    (sum((v - sum(_y_neg) / 50) ** 2 for v in _y_neg) / 50) ** 0.5
    + (sum((v - sum(_y_pos) / 50) ** 2 for v in _y_pos) / 50) ** 0.5,
)
check(
    "axis 2 separates the orthogonal narrow split",
    _gap > 1.5 * _spread,
    f"gap={_gap:.4f} spread={_spread:.4f}",
)

# K-138: the same guarantee for rows the fit never saw. Scoring every row
# outside the sample is new code, and the cheapest way to get it wrong is
# to hand axis 2 the FIRST component (a copy-paste away) — which reads as
# a perfectly diagonal map, i.e. |corr| -> 1, exactly the 1-D-disguised-as-2-D
# failure the test above was added to catch inside the sample.
_qpts_s, _ = projection.project(_quad_rows, fit_rows=12, seed=0)
_out = [k for k in range(len(_quad_rows))
        if k not in set(projection._stride_indices(len(_quad_rows), 12))]
_sx2 = [_qpts_s[k][0] for k in _out]
_sy2 = [_qpts_s[k][1] for k in _out]
check(
    "a 12-row fit still gives the ~88 out-of-sample rows two independent "
    "axes (|corr| < 0.2) — axis 2 is not axis 1 wearing a hat",
    len(_qpts_s) == len(_quad_rows) and abs(_corr(_sx2, _sy2)) < 0.2,
    f"corr={_corr(_sx2, _sy2):.4f}",
)

print("== projection: the THIRD component is pinned (K-148) ==")
# The map went 3D, so the depth axis needs exactly the guarantee K-071
# added for the second one: with the extra deflation round or the extra
# leakage correction dropped, every test above stays green while z comes
# back as a copy of x (or of y) — which renders as a cloud that rotates
# like a flat sheet, the 3D version of the 1-D-disguised-as-2-D bug.
# Three orthogonal splits of decreasing width: PC1 must take the widest,
# PC2 the middle, PC3 the narrowest.
check(
    "three components, named as a constant rather than a magic 3",
    projection.COMPONENTS == 3,
)
_rngo = random.Random(11)
_oct_rows = []
for _sx in (-1.0, 1.0):
    for _sy in (-1.0, 1.0):
        for _sz in (-1.0, 1.0):
            for _ in range(25):
                _row = [_rngo.gauss(0.0, 0.02) for _ in range(_D)]
                _row[0] += 3.0 * _sx    # widest  -> PC1
                _row[1] += 1.2 * _sy    # middle  -> PC2
                _row[2] += 0.5 * _sz    # narrow  -> PC3
                _oct_rows.append(array("f", _row))
_opts3, _ = projection.project(_oct_rows, fit_rows=1000, seed=0)
check(
    "every row comes back as an (x, y, z) triple",
    len(_opts3) == 200 and all(len(p) == 3 for p in _opts3),
)
_ox = [p[0] for p in _opts3]
_oy = [p[1] for p in _opts3]
_oz = [p[2] for p in _opts3]
check(
    "the depth axis has real spread — a placeholder z of 0.0 would pass "
    "the triple check above and render as a flat sheet",
    max(_oz) - min(_oz) > 1.9,
    f"z spans [{min(_oz):.3f}, {max(_oz):.3f}]",
)
check(
    "axis 3 is independent of BOTH earlier axes (|corr| < 0.2 each) — "
    "the leakage corrections are what keep it from re-carrying them",
    abs(_corr(_ox, _oz)) < 0.2 and abs(_corr(_oy, _oz)) < 0.2,
    f"corr(x,z)={_corr(_ox, _oz):.4f} corr(y,z)={_corr(_oy, _oz):.4f}",
)
# Group k has _sz = -1 for even k, +1 for odd k (innermost loop).
_z_neg = [v for k, v in enumerate(_oz) if (k // 25) % 2 == 0]
_z_pos = [v for k, v in enumerate(_oz) if (k // 25) % 2 == 1]
_zgap = abs(sum(_z_pos) / len(_z_pos) - sum(_z_neg) / len(_z_neg))
_zspread = max(
    1e-9,
    (sum((v - sum(_z_neg) / len(_z_neg)) ** 2 for v in _z_neg) / len(_z_neg)) ** 0.5
    + (sum((v - sum(_z_pos) / len(_z_pos)) ** 2 for v in _z_pos) / len(_z_pos)) ** 0.5,
)
check(
    "axis 3 separates the narrowest orthogonal split — it found the "
    "third direction, not noise",
    _zgap > 1.5 * _zspread,
    f"gap={_zgap:.4f} spread={_zspread:.4f}",
)
_opts3s, _ = projection.project(_oct_rows, fit_rows=16, seed=0)
_out3 = [k for k in range(len(_oct_rows))
         if k not in set(projection._stride_indices(len(_oct_rows), 16))]
check(
    "and rows the fit never saw get the same three independent axes — "
    "_score_all's corrections apply to every row, not to the sample",
    abs(_corr([_opts3s[k][0] for k in _out3],
              [_opts3s[k][2] for k in _out3])) < 0.2
    and abs(_corr([_opts3s[k][1] for k in _out3],
                  [_opts3s[k][2] for k in _out3])) < 0.2,
)
# The directions themselves have to be three DIFFERENT directions.
# Found by falsification: skipping the second deflation round makes the
# third power iteration return v2 again — and the output still looks
# right, because _score_all's analytic correction cancels v2 out and
# _normalize_axis then stretches the power iteration's ~1e-8 convergence
# residual (which happens to point along the true third direction) back
# to [-1, 1]. A correct-looking map resting on a rounding tail is not a
# map anyone should ship, and no test on the OUTPUT can see it. So pin
# the directions.
_seen_comps = []
_orig_score = projection._score_all


def _spy_score(rows, d, mean, comps):
    _seen_comps.append(list(comps))
    return _orig_score(rows, d, mean, comps)


try:
    projection._score_all = _spy_score
    projection.project(_oct_rows, fit_rows=1000, seed=0)
finally:
    projection._score_all = _orig_score
_v = _seen_comps[-1] if _seen_comps else []
_dots = [abs(projection._sumprod(_v[i], _v[j]))
         for i in range(len(_v)) for j in range(i)]
check(
    "the three component DIRECTIONS are mutually orthogonal — deflation "
    "actually searched fresh data each round rather than handing back a "
    "direction it had already found",
    len(_v) == 3 and _dots and max(_dots) < 1e-6,
    f"worst |v_i . v_j| = {max(_dots) if _dots else 'n/a'}",
)

# Adding depth must not MOVE the map: x and y have to come back exactly
# as the two-component version produced them, or every reader's mental
# picture of where their PDFs sit is silently rearranged by an upgrade.
_saved_k = projection.COMPONENTS
try:
    projection.COMPONENTS = 2
    _two, _ = projection.project(_oct_rows, fit_rows=1000, seed=0)
finally:
    projection.COMPONENTS = _saved_k
check(
    "the third component leaves the first two BIT-IDENTICAL — the depth "
    "axis is added in front of the existing map, it does not redraw it",
    all(p3[0] == p2[0] and p3[1] == p2[1]
        for p3, p2 in zip(_opts3, _two)),
    f"max dx={max(abs(a[0]-b[0]) for a, b in zip(_opts3, _two)):.3e}",
)

# A 2-row cloud has no third direction to find. It must come back flat,
# not carrying noise dressed up as depth.
_flat_pts, _ = projection.project(
    [array("f", [1.0, 0.0, 0.0]), array("f", [-1.0, 0.0, 0.0])],
    fit_rows=10, seed=0,
)
check(
    "a cloud with no third dimension left lands flat (z = 0) rather "
    "than inventing depth out of the power iteration's residue",
    all(abs(p[2]) < 1e-12 for p in _flat_pts),
    str(_flat_pts),
)

print("== projection: K-171 alignment fixes the resample reshuffle ==")
# K-171. The module docstring above (and pdf_graph's LAYOUT CACHE block)
# already prove the mechanism: with no eigengap between the three
# components, refitting the SAME data from a different sample can swap
# PC2/PC3 outright, moving the median note ~150px on a 700px canvas even
# though not one vector changed. Reproduce it with a synthetic cloud built
# to have exactly that property — three axes of nearly EQUAL spread
# (0.20/0.19/0.18) buried in high-dimensional noise — and show align_to
# takes the median move from "the whole map reshuffled" down to a few
# pixels, the bar the card itself sets.
_D_AL = 40
_N_AL = 2000
_CAP_AL = 250
_PX = 350.0  # a 700px canvas spans [-1, 1], so 1 normalized unit = 350px


def _make_isotropic_rows(n, d, sigmas, seed, noise=0.02):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        row = [rng.gauss(0.0, noise) for _ in range(d)]
        for k, s in enumerate(sigmas):
            row[k] = rng.gauss(0.0, s)
        out.append(array("f", row))
    return out


def _median_worst_px(pts_a, pts_b):
    dists = sorted(math.dist(p, q) for p, q in zip(pts_a, pts_b))
    n = len(dists)
    med = dists[n // 2] if n % 2 else (dists[n // 2 - 1] + dists[n // 2]) / 2
    return med * _PX, dists[-1] * _PX


_al_rows = _make_isotropic_rows(_N_AL, _D_AL, (0.20, 0.19, 0.18), seed=123)
_al_ids = list(range(_N_AL))

# "the same N vectors, only a different even-stride sample": reordering
# the SAME rows changes which vectors the stride sample lands on without
# adding, removing or editing a single one of them — the purest version of
# K-167's own experiment, and exactly what happens for free whenever the
# card index's row order shifts (e.g. an add/delete upstream of an
# otherwise-untouched note).
_al_order = list(range(_N_AL))
random.Random(7).shuffle(_al_order)
_al_rows_b = [_al_rows[i] for i in _al_order]
_al_ids_b = [_al_ids[i] for i in _al_order]

_pts_a = projection.project(_al_rows, fit_rows=_CAP_AL, seed=0)[0]
_pts_b = projection.project(_al_rows_b, fit_rows=_CAP_AL, seed=0)[0]
_by_id_b = dict(zip(_al_ids_b, _pts_b))
_pts_b_reordered = [_by_id_b[i] for i in _al_ids]

_med_before, _worst_before = _median_worst_px(_pts_a, _pts_b_reordered)
print(f"  .. unaligned: median={_med_before:.1f}px worst={_worst_before:.1f}px")
check(
    "root cause reproduced: resampling the SAME vectors reshuffles the "
    "map by tens to hundreds of pixels, matching K-167's measured ~150px "
    "median / ~391px worst on the real 28,670-note index",
    _med_before > 40.0,
    f"median={_med_before:.1f}px",
)

# THE FIX: align_to takes a fresh (unnormalized) layout and rotates it
# onto a previous one BEFORE normalize_points squashes it to [-1, 1] —
# doing it the other way around (aligning already-normalized boxes) was
# tried and measured short of the bar: on this exact scenario it only
# brought an analogous case from 97px down to 67px median (see
# normalize_points's docstring for the measurement that ruled it out).
_raw_a, _ = projection.project(
    _al_rows, fit_rows=_CAP_AL, seed=0, normalize=False
)
_raw_b, _ = projection.project(
    _al_rows_b, fit_rows=_CAP_AL, seed=0, normalize=False
)
_aligned_raw_b, _did_align = projection.align_to(
    _raw_b, _al_ids_b, _raw_a, _al_ids
)
check(
    "alignment reports it actually ran (enough overlap, solve not "
    "degenerate)",
    _did_align,
)

_norm_a = projection.normalize_points(_raw_a)
_norm_b_aligned = projection.normalize_points(_aligned_raw_b)
_by_id_b_aligned = dict(zip(_al_ids_b, _norm_b_aligned))
_pts_b_aligned_reordered = [_by_id_b_aligned[i] for i in _al_ids]

_med_after, _worst_after = _median_worst_px(_norm_a, _pts_b_aligned_reordered)
print(f"  .. aligned:   median={_med_after:.1f}px worst={_worst_after:.1f}px")
check(
    "THE FIX: aligning onto the previous layout before normalizing takes "
    "the median move from tens/hundreds of pixels down to a FEW pixels — "
    "the bar the card itself sets ('if alignment does not take that to a "
    "few pixels, it has not worked')",
    _med_after < 5.0 and _worst_after < 15.0,
    f"median={_med_after:.1f}px worst={_worst_after:.1f}px (before: "
    f"median={_med_before:.1f}px worst={_worst_before:.1f}px)",
)

print("== projection: align_to is an isometry (pairwise distances preserved) ==")
# CONSTRAINT from the card: alignment must not change WHAT is shown, only
# its orientation. Rotating (or reflecting) the whole cloud is free — an
# alignment that distorts distances is a bug, not a nicety. Pin it
# directly: every pairwise distance inside the ALIGNED set must equal the
# corresponding distance in the PRE-alignment set, to floating-point
# tolerance, because R is orthogonal by construction (R^T R = I).
_sample_idx = list(range(0, len(_raw_b), 37))[:40]
_before_pts = [_raw_b[i] for i in _sample_idx]
_after_pts = [_aligned_raw_b[i] for i in _sample_idx]
_max_drift = 0.0
for _i in range(len(_sample_idx)):
    for _j in range(_i + 1, len(_sample_idx)):
        _d_before = math.dist(_before_pts[_i], _before_pts[_j])
        _d_after = math.dist(_after_pts[_i], _after_pts[_j])
        _max_drift = max(_max_drift, abs(_d_before - _d_after))
check(
    "align_to is an isometry: every pairwise distance survives the "
    "rotation to floating-point tolerance",
    _max_drift < 1e-9,
    f"max drift={_max_drift:.3e}",
)

print("== projection: align_to degrades to unaligned rather than raising ==")
check(
    "no previous layout at all -> unaligned, not an error",
    projection.align_to([(1.0, 0.0, 0.0)], [1], [], [])
    == ([(1.0, 0.0, 0.0)], False),
)
_few_pts = [(float(k), 0.0, 0.0) for k in range(5)]
_few_ids = list(range(5))
_few_old = [(float(k) + 10.0, 0.0, 0.0) for k in range(5)]
check(
    "overlap under the floor -> unaligned, not a noise-fitted rotation",
    projection.align_to(_few_pts, _few_ids, _few_old, _few_ids)
    == (_few_pts, False),
)
# A degenerate correspondence: every old point identical (rank-0 spread),
# so M = new^T @ old is singular and there is no well-defined rotation.
_deg_new = [(float(k), float(k) * 2, float(k) * 3) for k in range(20)]
_deg_old = [(1.0, 1.0, 1.0)] * 20
_deg_pts, _deg_ok = projection.align_to(
    _deg_new, list(range(20)), _deg_old, list(range(20))
)
check(
    "a degenerate (singular) correspondence degrades to unaligned rather "
    "than dividing by a near-zero determinant",
    _deg_pts == list(_deg_new) and _deg_ok is False,
)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
