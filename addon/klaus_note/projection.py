"""3D projection of high-dimensional unit-normalized embedding vectors.

Pure stdlib, aqt-free — importable with no Anki/Qt present at all (proven
by ``tests/test_projection.py``, which imports this module standalone).
This is the numeric foundation under the Obsidian-like embedding map
(K-058 Phase D): ``pdf_graph`` turns these points into the map's nodes
and edges, and ``pdf_map`` draws them.

Method: top-3 principal components by power iteration with deflation,
computed directly on the (mean-centered) n x d data matrix — never
forming the d x d covariance matrix, which would cost O(n*d^2) and swamp
everything else once d=768. Each iteration instead does two O(n*d)
matrix-vector products, X @ v and X.T @ s, both driven by ``math.sumprod``
(pre-3.12 fallback below) over ``memoryview`` slices of ONE packed
``array('d')`` buffer holding the centered data row-major — the same
trick that makes ``card_index.top_k`` rank 30k x 768 rows in ~0.25s.
The X @ v direction reads contiguous row slices (``mv[i*d:(i+1)*d]``);
the X.T @ s direction reads *strided* slices of the very same buffer
(``mv[j:n*d:d]``, i.e. every d-th element starting at j) to pick out
column j — Python's memoryview supports extended-slice striding natively,
so this needs no separate transposed copy of the data.

Determinism: each component's power-iteration start vector is drawn from
``random.Random(seed)`` (never a non-deterministic source), and both the
fit-sample size and the iteration count are fixed parameters — same input
+ same seed = bit-identical output.

FIT on a sample, PROJECT everything (K-138). ``fit_rows`` caps how many
rows the component DIRECTIONS are computed from, not how many points
come out: every row in ``rows`` gets a position. The split is what makes
"show every note" affordable. Finding a direction costs
``MAX_ITERATIONS`` passes over the fit rows (two O(n*d) products each);
*using* one costs a single dot product per row. So on Pouya's 28,668-note
collection the old whole-pipeline-on-everything shape would have been
~7x the fit bill, while fitting on 4,000 evenly-strided rows and then
scoring all 28,668 adds only the scoring passes — measured at ~9% on
top of today's cost, for 7x the notes.

THE SAMPLE DOES NOT PIN THE AXES, and this docstring claimed it did
until K-167 measured it. Refitting from a DIFFERENT even 4,000 of the
same 28,670 vectors moves the median note 0.449 in these [-1, 1] units,
about 150 px on a 700 px canvas, and swaps components 2 and 3 outright
(|<v2, v2'>| = 0.45 while |<v2, v3'>| = 0.86). The reason is that the
cloud is nearly isotropic — the three axes' standard deviations on
Pouya's index are 0.1332, 0.1236 and 0.1190, so there is no eigengap to
separate them by. Only the three-dimensional SUBSPACE is stable (6-18
degrees under a resample); which orthogonal frame of it comes back is
sampling noise. Consequences worth knowing before touching anything
here: the layout is a stable picture only for an unchanged index (which
is exactly what pdf_graph's cache keys on); a cached FIT is not reusable
across an index change and pdf_graph says why at length; and K-148's
non-monotone iteration table below is this same fact seen from the
other side — power iteration separates two components at their variance
ratio per pass, and 0.93^40 is 0.05, so the third axis was never going
to converge in 40 iterations however many it was given. Making the
picture stable under a growing collection means fitting from more rows
(or from a basis that does not depend on the sample), not from a
cleverer 4,000.

That also keeps the memory flat. Only the fit sample is ever packed into
the ``array('d')`` working buffer (4,000 x 768 x 8B = 24 MB); packing all
28,668 rows would have been 176 MB. Scoring reads the caller's own rows
in place and subtracts the sample mean's contribution analytically —
``dot(x - mean, v) == dot(x, v) - dot(mean, v)`` — so no centered copy of
the full data is ever built.

THREE components, not two (K-148). Pouya asked for the map to be 3D and
"a vibe, like you're in cyberspace" — so the map needs a depth axis, and
the honest one is the next principal component rather than a decorative
z made up from the other two. It costs exactly what the second one cost:
one more deflation round, one more power iteration, and one more dot
product per row in ``_score_all`` (with the leakage corrections that go
with it). Measured on Pouya's live 28,670 x 768 card index: 17.4 s
for two components, 26.9 s for three (+55%, which is the extra power
iteration and the extra dot product per row, as predicted) — and the
whole ``build_graph_data`` around it 26.6 s. That is why BOTH of the
map's hosts build this off the UI thread now (K-143 for the Library's
dock, K-144 for the standalone window).

Re-measured K-167, same index, same machine: ``project`` 29.47 s, of
which the FIT is 29.29 s and scoring all 28,670 rows 2.06 s. So the fit
is 99.4% of this module's cost and 99.9% of the map's, which is why
``pdf_graph`` caches the answer rather than tuning the arithmetic. Do
not spend iterations to buy speed: K-167's own table shows truncating
to 25 moves points by up to 0.605 (~212 px) and does not improve
monotonically as the count rises, because of the isotropy above.

The stride is deterministic: ``_stride_indices`` walks ``n/cap`` through
the rows in order, so the same index yields the same fit sample every
time and ``pdf_graph``'s cached layout stays reproducible. It lives here
rather than being imported so this module has no project-specific
imports at all — ``pdf_index`` had a twin of it until the 2026-09-15
page-level index removed the need (one vector per page is not a
population you sample).

Degenerate inputs (0 rows, 1 row, or every sampled row identical after
mean-centering) never divide by zero: the power iteration detects a
zero-norm update and stops, and axis normalization falls back to 0.0 for
every point when a component has no spread instead of inventing a range.
A cloud with no third dimension left to find (fewer rows than components,
or a genuinely flat one) lands every point at z 0.0 — a flat plane, which
is exactly what it is, rather than noise dressed up as depth.
"""

from __future__ import annotations

import random
from array import array
from typing import Sequence

try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (Anki bundles 3.13; this repo's
    # plain `python3` for headless test runs may be older)
    def _sumprod(a, b):  # type: ignore[misc]
        return sum(x * y for x, y in zip(a, b))

# How many rows the component DIRECTIONS are fitted from. NOT an output
# cap — every row passed to project() gets a point regardless (K-138).
DEFAULT_FIT_ROWS = 4000
# How many principal components the map wants: x, y, and the depth axis
# K-148's 3D view rotates around. Not a knob — it is the length of every
# point tuple this module returns, and pdf_map's whole camera is written
# for three.
COMPONENTS = 3
MAX_ITERATIONS = 40
_CONVERGENCE_EPS = 1e-9


def _stride_indices(n: int, cap: int) -> list[int]:
    """Evenly sampled row indices, at most ``cap``, preserving order."""
    if cap <= 0 or n <= cap:
        return list(range(n))
    step = n / cap
    return [int(i * step) for i in range(cap)]


def _norm(v) -> float:
    return _sumprod(v, v) ** 0.5


def _matvec_row(row_mv: memoryview, n: int, d: int, v) -> array:
    """X @ v — one dot product per row, contiguous slices."""
    return array(
        "d", (_sumprod(row_mv[i * d:(i + 1) * d], v) for i in range(n))
    )


def _matvec_col(row_mv: memoryview, n: int, d: int, s) -> array:
    """X.T @ s — one dot product per column, strided slices over the same
    row-major buffer (column j lives at offsets j, j+d, j+2d, ...)."""
    return array("d", (_sumprod(s, row_mv[j:n * d:d]) for j in range(d)))


def _power_iterate(
    row_mv: memoryview, n: int, d: int, start: array
) -> tuple[array, array]:
    """One component's power iteration on the (already centered) data.

    Returns ``(v, s)``: the unit direction (length d) and its per-row
    scores (length n) — ``s[i]`` is the sampled row ``i`` projected onto
    ``v``, i.e. exactly that row's coordinate on this component.
    """
    vn = _norm(start)
    if vn > 0:
        v = array("d", (x / vn for x in start))
    else:
        v = array("d", (0.0 for _ in range(d)))
        if d:
            v[0] = 1.0
    prev_eigval = None
    for _ in range(MAX_ITERATIONS):
        s = _matvec_row(row_mv, n, d, v)
        w = _matvec_col(row_mv, n, d, s)
        wn = _norm(w)
        if wn == 0:
            break
        v = array("d", (x / wn for x in w))
        if prev_eigval is not None and (
            abs(wn - prev_eigval) <= _CONVERGENCE_EPS * max(1.0, wn)
        ):
            break
        prev_eigval = wn
    s = _matvec_row(row_mv, n, d, v)
    return v, s


def _deflate(flat: array, row_mv: memoryview, n: int, d: int, s, v) -> None:
    """Remove component ``v``'s contribution from the centered data in
    place, so the next power iteration finds the NEXT direction.

    Pulled out of ``project`` when K-148 added a third component: two
    identical copies of this loop is exactly how the second and third
    axes would quietly drift apart.
    """
    for i in range(n):
        base = i * d
        c = s[i]
        if c:
            row = row_mv[base:base + d]
            flat[base:base + d] = array(
                "d", (x - c * y for x, y in zip(row, v))
            )


# ------------------------------------------------------------- alignment
#
# K-171. The docstring above already proves the axes are not canonical:
# refitting the SAME data from a different sample can swap PC2/PC3 outright
# (no eigengap to separate them). ``align_to`` does not try to fix the fit
# — it makes the PICTURE continuous instead, by rotating (and, deliberately,
# reflecting where useful — see below) a fresh layout onto the previous one
# using whichever notes both layouts share. That is an orthogonal Procrustes
# problem: given old positions P_old and new P_new (n x 3, rows paired by
# note id), find the orthogonal R minimising ||P_new @ R - P_old||. The
# minimiser is the orthogonal polar factor of M = P_new^T @ P_old (a
# textbook Procrustes result — R = U V^T from M's SVD U*Sigma*V^T), found
# here by Higham's Newton iteration for the polar decomposition
# (R_{k+1} = (R_k + R_k^-T) / 2): a few 3x3 inverses, no eigenvalues or SVD
# routine required, and it converges to that SAME R whether R itself turns
# out to be a proper rotation (det +1) or a reflection (det -1) — which is
# exactly the choice below.
#
# Reflections ALLOWED, deliberately. A PCA frame has no chirality worth
# protecting: "this point cloud, mirrored" is not a different embedding, it
# is the same cosine-similarity structure wearing a coordinate system whose
# handedness power iteration never fixed in the first place — a start
# vector converging to -v instead of +v is already a one-axis reflection,
# and it already happens between runs with nobody noticing. Forbidding
# reflections (the usual Kabsch fix: flip the sign of the smallest singular
# vector when det(UV^T) = -1) would force a worse fit whenever the true
# correspondence between old and new frames is orientation-reversing —
# which is common here, since a PC2/PC3 swap composed with either axis's
# sign flip is already an odd permutation. Nothing downstream (pdf_map's
# camera) cares which way the frame turns, so there is no handedness to
# spend a worse fit protecting.
MIN_ALIGN_OVERLAP = 16  # A 3D rotation/reflection has 3 degrees of freedom
# and needs at least 3 non-collinear correspondences to be determined at
# all. 16 is comfortably above that floor: with only a handful of shared
# notes, the 3x3 cross-covariance matrix M is dominated by whichever couple
# of points happen to be in the overlap rather than by the cloud's real
# orientation, and aligning to it would be fitting noise, not the picture.


def _mat3_transpose(m):
    return tuple(tuple(m[r][c] for r in range(3)) for c in range(3))


def _mat3_det(m):
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _mat3_inverse(m):
    det = _mat3_det(m)
    if abs(det) < 1e-12:
        return None
    inv_det = 1.0 / det
    return (
        (
            (m[1][1] * m[2][2] - m[1][2] * m[2][1]) * inv_det,
            (m[0][2] * m[2][1] - m[0][1] * m[2][2]) * inv_det,
            (m[0][1] * m[1][2] - m[0][2] * m[1][1]) * inv_det,
        ),
        (
            (m[1][2] * m[2][0] - m[1][0] * m[2][2]) * inv_det,
            (m[0][0] * m[2][2] - m[0][2] * m[2][0]) * inv_det,
            (m[0][2] * m[1][0] - m[0][0] * m[1][2]) * inv_det,
        ),
        (
            (m[1][0] * m[2][1] - m[1][1] * m[2][0]) * inv_det,
            (m[0][1] * m[2][0] - m[0][0] * m[2][1]) * inv_det,
            (m[0][0] * m[1][1] - m[0][1] * m[1][0]) * inv_det,
        ),
    )


def _polar_orthogonal(m, iterations: int = 100, tol: float = 1e-10):
    """The orthogonal polar factor of a 3x3 matrix ``m`` — the Procrustes
    ``R`` maximising ``tr(R^T m)`` over ALL orthogonal ``R`` (rotations and
    reflections alike) — via Higham's Newton iteration. Returns ``None`` on
    a singular matrix or one that fails to settle within ``iterations``
    (degenerate correspondence geometry), never a garbage matrix.
    """
    r = m
    for _ in range(iterations):
        inv = _mat3_inverse(r)
        if inv is None:
            return None
        inv_t = _mat3_transpose(inv)
        nxt = tuple(
            tuple((r[i][j] + inv_t[i][j]) / 2.0 for j in range(3))
            for i in range(3)
        )
        diff = max(abs(nxt[i][j] - r[i][j]) for i in range(3) for j in range(3))
        r = nxt
        if diff < tol:
            return r
    return None


def align_to(
    new_points: Sequence[tuple[float, float, float]],
    new_ids: Sequence[int],
    old_points: Sequence[tuple[float, float, float]],
    old_ids: Sequence[int],
    *,
    min_overlap: int = MIN_ALIGN_OVERLAP,
) -> tuple[list[tuple[float, float, float]], bool]:
    """Rotate/reflect ``new_points`` onto ``old_points`` by the ids the two
    layouts share, so a fresh layout settles into the previous one's
    orientation instead of spinning with every resample (see the module
    docstring's isotropy finding). ``new_ids``/``old_ids`` pair positionally
    with ``new_points``/``old_points``.

    Returns ``(points, True)`` on a genuine alignment, or
    ``(list(new_points), False)`` unchanged when there is no previous
    layout, the shared overlap is under ``min_overlap``, a point is not
    3-dimensional, or the Procrustes solve is degenerate — every one of
    those is "nothing to align to", never an error.

    ``R`` is applied to EVERY point in ``new_points``, not just the
    overlap — the whole cloud turns together, or it would not be one
    coherent map. Because ``R`` is orthogonal this changes nothing about
    what the map shows: every pairwise distance within ``new_points`` is
    exactly preserved by construction (an orthogonal transform is an
    isometry), only the frame it is viewed from moves.
    """
    old_by_id = dict(zip(old_ids, old_points))
    pairs = [
        (p, old_by_id[i])
        for p, i in zip(new_points, new_ids)
        if i in old_by_id
    ]
    if len(pairs) < min_overlap or any(
        len(p) != 3 or len(q) != 3 for p, q in pairs
    ):
        return list(new_points), False
    m = [[0.0, 0.0, 0.0] for _ in range(3)]
    for new_p, old_p in pairs:
        for i in range(3):
            for j in range(3):
                m[i][j] += new_p[i] * old_p[j]
    r = _polar_orthogonal(tuple(tuple(row) for row in m))
    if r is None:
        return list(new_points), False
    aligned = [
        tuple(sum(p[i] * r[i][j] for i in range(3)) for j in range(3))
        for p in new_points
    ]
    return aligned, True


def _normalize_axis(values: Sequence[float]) -> list[float]:
    """Independently rescale one axis into [-1, 1]; 0.0 everywhere when
    the axis has no spread (never divides by a zero span)."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 0:
        return [0.0 for _ in values]
    scale = 2.0 / span
    return [((v - lo) * scale) - 1.0 for v in values]


def normalize_points(
    points: Sequence[Sequence[float]],
) -> list[tuple[float, ...]]:
    """Independently rescale every axis of ``points`` into [-1, 1] —
    ``project``'s own last step, pulled out so ``pdf_graph`` can insert
    ``align_to`` BEFORE it (K-171).

    Order matters and is the whole point: normalizing first and aligning
    second compares two boxes each independently squashed to fill
    [-1, 1] — which axis is 5% wider than which is itself sampling noise,
    so a rotation fitted between two such boxes inherits that noise and
    only partly cancels the resample defect (measured: taking a 97px
    median resample move down to just 67px, nowhere near "a few pixels").
    Aligning the RAW component scores first and normalizing the aligned
    result afterward routes around it entirely, because after a good
    alignment the rotated data is nearly the SAME cloud the old layout
    normalized from, so independently finding its extents again lands
    almost exactly where the old normalization did (measured on the same
    scenario: 1px median, 3px worst) — see ``pdf_graph.build_graph_data``.
    """
    if not points:
        return []
    cols = list(zip(*points))
    return list(zip(*(_normalize_axis(c) for c in cols)))


def project(
    rows: Sequence,
    *,
    fit_rows: int = DEFAULT_FIT_ROWS,
    seed: int = 0,
    normalize: bool = True,
) -> tuple[list[tuple[float, float, float]], list[int]]:
    """Project EVERY row to 3D via the top-3 principal components.

    ``rows`` is any sequence of equal-length, equal-dimension sequences of
    floats — typically ``memoryview`` slices of a packed ``array('f')``
    from ``card_index``/``pdf_index`` (unit vectors, but this function
    does not require that).

    Returns ``(points, indices)``: ``points[k]`` is the ``(x, y, z)``
    position of ``rows[indices[k]]``. With the default ``normalize=True``
    (every existing caller) all three axes are independently normalized
    into [-1, 1], exactly as before this function grew the flag.
    ``normalize=False`` returns the raw, unnormalized component scores
    instead — for ``pdf_graph``'s alignment step (K-171) alone, which has
    to rotate the RAW cloud onto a previous layout before normalizing (see
    ``normalize_points``'s docstring for why that order is load-bearing).
    ``indices`` is ``range(len(rows))`` — it stays in the return signature
    because callers (``pdf_graph``) zip it against ``points`` to recover
    each row's identity, and because it was a strict subset before K-138
    made every row a point.

    ``fit_rows`` bounds only the even stride sample the two component
    directions are COMPUTED from; rows outside it are still projected
    onto those directions. See the module docstring for why that split
    is what makes "every note on the map" affordable.
    """
    n_total = len(rows)
    if n_total == 0:
        return [], []
    indices = list(range(n_total))
    fit_idx = _stride_indices(n_total, fit_rows)
    n = len(fit_idx)
    d = len(rows[fit_idx[0]])
    if d <= 0:
        return [(0.0, 0.0, 0.0) for _ in indices], indices

    flat = array("d")
    for i in fit_idx:
        row = rows[i]
        if len(row) != d:
            raise ValueError("all rows must share the same dimensionality")
        flat.extend(float(x) for x in row)
    row_mv = memoryview(flat)

    # Mean-center, one column (strided slice) at a time. The mean is the
    # FIT sample's; it is kept, because every row outside the sample has
    # to be centered against the same origin to land on the same map.
    mean = array("d", (0.0 for _ in range(d)))
    for j in range(d):
        col = row_mv[j:n * d:d]
        m = sum(col) / n
        mean[j] = m
        flat[j:n * d:d] = array("d", (x - m for x in col))
    row_mv = memoryview(flat)

    rng = random.Random(seed)
    # One direction per component, each found on the data with every
    # earlier direction already deflated out of it.
    comps: list[array] = []
    for k in range(COMPONENTS):
        start = array("d", (rng.uniform(-1.0, 1.0) for _ in range(d)))
        v, s = _power_iterate(row_mv, n, d, start)
        comps.append(v)
        if k + 1 < COMPONENTS:  # nothing left to search: skip a 3M-op pass
            _deflate(flat, row_mv, n, d, s, v)
            row_mv = memoryview(flat)

    raw = _score_all(rows, d, mean, comps)
    return (normalize_points(raw) if normalize else raw), indices


def _score_all(rows: Sequence, d: int, mean: array, comps: list):
    """Every row's raw ``(x, y, z)`` component scores — NOT yet normalized
    into [-1, 1]; ``project`` (or ``pdf_graph``, when it aligns first) owns
    that step via ``normalize_points`` now, so this stays the one place
    that reads the fitted directions and nothing else.

    One dot product per row per component and no centered copy of the
    data: the sample mean's contribution is a constant per component, so
    ``dot(x - mean, v) == dot(x, v) - dot(mean, v)``.

    Each score subtracts the EARLIER components' leakage
    (``- a * v1v2``, and for the third ``- a * v1v3 - b * v2v3``), which
    is exactly what projecting onto the successively DEFLATED data did
    before every row got a point.

    Measured honestly (K-148 falsification): given the deflation above,
    those terms are STRUCTURALLY near zero, not merely small. ``_deflate``
    removes a component exactly, row by row, so the deflated data lies in
    that component's orthogonal complement — and ``X.T @ s`` can only
    ever produce directions inside it. The dot products they scale by
    come out at 1e-17, and deleting the terms changes nothing this
    module's tests can see. They stay because they are what makes the
    formula *right* rather than *right on this data*: any future change
    to how deflation works (a sampled deflation, a reordering, an
    early-out) reintroduces real non-orthogonality, and then these are
    the only thing standing between the depth axis and a copy of the
    horizontal one. What IS pinned, because it is observable, is that the
    three DIRECTIONS come back mutually orthogonal.

    A row of the wrong length is a caller bug, not a shrug: the pre-3.12
    ``_sumprod`` fallback is ``zip``-based and would silently score a
    short row against a truncated component instead.
    """
    means = [_sumprod(mean, v) for v in comps]
    # cross[k][j] = <v_j, v_k> for j < k — the leakage of every earlier
    # component into this one.
    cross = [[_sumprod(comps[j], v) for j in range(k)]
             for k, v in enumerate(comps)]
    axes: list = [array("d") for _ in comps]
    for row in rows:
        if len(row) != d:
            raise ValueError("all rows must share the same dimensionality")
        scores: list = []
        for k, v in enumerate(comps):
            s = _sumprod(row, v) - means[k]
            for j, c in enumerate(cross[k]):
                s -= scores[j] * c
            scores.append(s)
            axes[k].append(s)
    return list(zip(*axes))
