"""2D projection of high-dimensional unit-normalized embedding vectors.

Pure stdlib, aqt-free — importable with no Anki/Qt present at all (proven
by ``tests/test_projection.py``, which imports this module standalone).
This is the numeric foundation for the future Obsidian-like embedding map
(K-058 Phase D); this card builds only the math + graph-assembly layer,
no window/canvas.

Method: top-2 principal components by power iteration with deflation,
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
point cap and the iteration count are fixed parameters — same input +
same seed = bit-identical output.

Point cap: real note/PDF-chunk indexes can hold tens of thousands of
rows; ``max_points`` evenly stride-samples down to a size that stays
interactive in a future canvas. The stride is deterministic (same idea as
``pdf_index.stride_sample``, reimplemented locally so this module has no
project-specific imports at all).

Degenerate inputs (0 rows, 1 row, or every sampled row identical after
mean-centering) never divide by zero: the power iteration detects a
zero-norm update and stops, and axis normalization falls back to 0.0 for
every point when a component has no spread instead of inventing a range.
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

DEFAULT_MAX_POINTS = 4000
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
    max_points: int = DEFAULT_MAX_POINTS,
    seed: int = 0,
) -> tuple[list[tuple[float, float]], list[int]]:
    """Project ``rows`` to 2D via the top-2 principal components.

    ``rows`` is any sequence of equal-length, equal-dimension sequences of
    floats — typically ``memoryview`` slices of a packed ``array('f')``
    from ``card_index``/``pdf_index`` (unit vectors, but this function
    does not require that).

    Returns ``(points, indices)``: ``points[k]`` is the 2D position of
    ``rows[indices[k]]``, both axes independently normalized into
    [-1, 1]. When ``len(rows) > max_points``, an even stride sample of
    that many rows is used and ``indices`` reports exactly which —
    callers need this to map projected points back to the original row's
    identity (e.g. a note id).
    """
    n_total = len(rows)
    if n_total == 0:
        return [], []
    indices = _stride_indices(n_total, max_points)
    n = len(indices)
    d = len(rows[indices[0]])
    if d <= 0:
        return [(0.0, 0.0) for _ in indices], indices

    flat = array("d")
    for i in indices:
        row = rows[i]
        if len(row) != d:
            raise ValueError("all rows must share the same dimensionality")
        flat.extend(float(x) for x in row)
    row_mv = memoryview(flat)

    # Mean-center, one column (strided slice) at a time.
    for j in range(d):
        col = row_mv[j:n * d:d]
        m = sum(col) / n
        flat[j:n * d:d] = array("d", (x - m for x in col))
    row_mv = memoryview(flat)

    rng = random.Random(seed)
    start1 = array("d", (rng.uniform(-1.0, 1.0) for _ in range(d)))
    v1, s1 = _power_iterate(row_mv, n, d, start1)

    # Deflate: remove the v1 component from the centered data before
    # searching for the second one.
    for i in range(n):
        base = i * d
        c = s1[i]
        if c:
            row = row_mv[base:base + d]
            flat[base:base + d] = array(
                "d", (x - c * y for x, y in zip(row, v1))
            )
    row_mv = memoryview(flat)

    start2 = array("d", (rng.uniform(-1.0, 1.0) for _ in range(d)))
    _v2, s2 = _power_iterate(row_mv, n, d, start2)

    xs = _normalize_axis(s1)
    ys = _normalize_axis(s2)
    return list(zip(xs, ys)), indices
