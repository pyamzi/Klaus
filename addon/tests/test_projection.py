"""Headless tests for K-071: klausmate/projection.py (2D PCA-ish projection
of embedding vectors) and klausmate/pdf_graph.py (map node/edge assembly
built on top of it). Both are the headless data-layer foundation for the
future Obsidian-like embedding map (K-058 Phase D) — no window/canvas here.

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

# Synthetic package so relative imports inside the modules resolve.
pkg = types.ModuleType("klausmate")
pkg.__path__ = [ADDON]
pkg.__package__ = "klausmate"
sys.modules["klausmate"] = pkg

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

points1, idx1 = projection.project(cluster_rows, max_points=4000, seed=7)
points2, idx2 = projection.project(cluster_rows, max_points=4000, seed=7)
check("same seed -> identical points", points1 == points2)
check("same seed -> identical indices", idx1 == idx2)

points3, _idx3 = projection.project(cluster_rows, max_points=4000, seed=1)
check(
    "different seed does not (trivially) reuse the same start vector",
    points3 != points1,
)

print("== projection: cluster separation ==")
cluster_a_pts = points1[:N_PER]
cluster_b_pts = points1[N_PER:]


def _centroid(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _avg_dist(pts, c):
    return sum(math.dist(p, c) for p in pts) / len(pts)


ca = _centroid(cluster_a_pts)
cb = _centroid(cluster_b_pts)
inter = math.dist(ca, cb)
intra_a = _avg_dist(cluster_a_pts, ca)
intra_b = _avg_dist(cluster_b_pts, cb)
check(
    "two well-separated 768-... err 96-d clusters land well-separated in 2D",
    inter > 3 * max(intra_a, intra_b),
    f"inter={inter:.3f} intra_a={intra_a:.3f} intra_b={intra_b:.3f}",
)

print("== projection: max_points sampling ==")
small_rows = [array("f", [float(k), float(k + 1), float(k + 2)]) for k in range(100)]
pts, idxs = projection.project(small_rows, max_points=10, seed=0)
check("sampling respects max_points count", len(pts) == 10 and len(idxs) == 10)
check(
    "sampling indices are a strictly increasing stride within range",
    idxs == sorted(set(idxs)) and len(set(idxs)) == 10 and idxs[0] == 0 and idxs[-1] < 100,
    str(idxs),
)

pts_all, idxs_all = projection.project(small_rows, max_points=1000, seed=0)
check(
    "no sampling when the input is under the cap",
    len(pts_all) == 100 and idxs_all == list(range(100)),
)

print("== projection: degenerate inputs ==")
empty_pts, empty_idx = projection.project([], max_points=10, seed=0)
check("0 rows -> empty output, no crash", empty_pts == [] and empty_idx == [])

one_pts, one_idx = projection.project(
    [array("f", [1.0, 2.0, 3.0])], max_points=10, seed=0
)
check(
    "1 row -> single point at the origin, no div-by-zero",
    one_pts == [(0.0, 0.0)] and one_idx == [0],
)

identical = [array("f", [1.0, 2.0, 3.0]) for _ in range(6)]
ident_pts, ident_idx = projection.project(identical, max_points=10, seed=0)
check(
    "identical rows -> every point collapses to the origin, no div-by-zero",
    ident_pts == [(0.0, 0.0)] * 6 and ident_idx == list(range(6)),
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
big_points, big_idx = projection.project(big_rows, max_points=4000, seed=0)
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
    agg = retention.DEFAULT_AGG

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

    matches_a = [(1, 0.90), (2, 0.85), (3, 0.50)]
    matches_b = [(5, 0.95), (6, 0.20)]
    retention.save_matches("PdfA", sig, cidx.dims, src_a, digest, agg, matches_a)
    retention.save_matches("PdfB", sig, cidx.dims, src_b, digest, agg, matches_b)
    # PdfC deliberately gets no matches.json at all.

    drive_store.record_import(tmp, "PdfA", "Physiology Lecture 1.pdf")
    drive_store.set_folder(tmp, "PdfA", "Anatomy")
    retention.set_threshold("PdfB", 0.1)  # per-PDF override: include nid 6 too

    check(
        "PdfC has no match cache on disk",
        retention.load_matches("PdfC", sig, cidx.dims, src_c, digest, agg) is None,
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
        "PdfA: default threshold (0.75) keeps nid 1 and 2, drops nid 3 (0.50)",
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
    note_xy = {n["nid"]: tuple(n["xy"]) for n in data["notes"]}
    exp_x = (note_xy[1][0] + note_xy[2][0]) / 2
    exp_y = (note_xy[1][1] + note_xy[2][1]) / 2
    got_x, got_y = pdf_by_safe["PdfA"]["xy"]
    check(
        "PdfA's node sits at the centroid of its (thresholded) matched notes",
        abs(got_x - exp_x) < 1e-9 and abs(got_y - exp_y) < 1e-9,
        f"got=({got_x},{got_y}) exp=({exp_x},{exp_y})",
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
_qpts, _ = projection.project(_quad_rows, max_points=1000, seed=0)
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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
