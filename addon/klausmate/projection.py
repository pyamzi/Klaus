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
top of today's cost, for 7x the notes. And a stride sample of 4,000
768-d embeddings pins the same principal axes as the full set would: the
directions are a property of the cloud's shape, which an even sample of
that size already carries.

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

The stride is deterministic (same idea as ``pdf_index.stride_sample``,
reimplemented locally so this module has no project-specific imports at
all).

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


def project(
    rows: Sequence,
    *,
    fit_rows: int = DEFAULT_FIT_ROWS,
    seed: int = 0,
) -> tuple[list[tuple[float, float, float]], list[int]]:
    """Project EVERY row to 3D via the top-3 principal components.

    ``rows`` is any sequence of equal-length, equal-dimension sequences of
    floats — typically ``memoryview`` slices of a packed ``array('f')``
    from ``card_index``/``pdf_index`` (unit vectors, but this function
    does not require that).

    Returns ``(points, indices)``: ``points[k]`` is the ``(x, y, z)``
    position of ``rows[indices[k]]``, all three axes independently
    normalized into [-1, 1]. ``indices`` is ``range(len(rows))`` — it
    stays in the return signature because callers (``pdf_graph``) zip it
    against ``points`` to recover each row's identity, and because it was
    a strict subset before K-138 made every row a point.

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

    return _score_all(rows, d, mean, comps), indices


def _score_all(rows: Sequence, d: int, mean: array, comps: list):
    """Every row's ``(x, y, z)``, each axis normalized into [-1, 1].

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
    return list(zip(*(_normalize_axis(a) for a in axes)))
