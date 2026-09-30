"""Semantic duplicate finder over the card index (K-168).

Anki already ships Find Duplicates (Browse → Notes). It reads
``select id, mid, flds from notes``, picks ONE field ordinal per notetype
and groups by the EXACT stripped string. It cannot see that two
differently worded notes teach the same fact, and it never compares
across notetypes. This module can, because ``card_index`` already holds
one unit vector per NOTE.

THE UNIT IS THE NOTE, everywhere in this file (K-118's lesson, learned
by the Library the hard way). ``card_index`` is keyed on nid; a cloze
note with c1/c2/c3 is ONE row, not three, so genuine cloze siblings are
already collapsed before this module sees anything and can never form a
pair. What DOES pair up on a shared-source deck is *sibling notes* —
separate notes carved out of one table or one mnemonic, which share
their Extra field verbatim. See "What the scores mean" below: they are
the dominant false positive and no threshold removes them.

Pure stdlib, no aqt, no numpy, no new dependency: it takes a loaded
``CardIndex`` and returns data. Everything here is importable and
testable headlessly (``tests/test_duplicates.py``).

Two shapes, two budgets
-----------------------

**A. "Duplicates of THIS note"** — ``duplicates_of``. One vector against
the index, which is exactly ``card_index.top_k``: ~0.24 s for
28,670 × 768 on Pouya's collection with ``math.sumprod``. Effectively
instant, and the common case.

**B. "Scan the whole collection"** — ``scan_index``. All-pairs is
28,670² / 2 = 411 million pairs at 768 dims. At the measured 90–105 M
MAC/s of ``math.sumprod`` that is ~58 minutes, so brute force is out.
What ships instead is a two-stage filter whose first stage costs ONE
integer operation per pair:

1. **Mean-split sign bits.** Subtract nothing, store nothing: bit j of
   note i is ``vec[i][j] > mean[j]``, packed into one Python int of
   ``dims`` bits (``sign_signatures``). Because the split point is the
   collection mean, each bit is close to balanced by construction —
   measured random-pair Hamming on Pouya's index came out at exactly
   0.5000 of 768 bits — so this is a random-hyperplane LSH whose
   hyperplanes are the coordinate axes and whose projection cost is
   ZERO. Building all 28,670 signatures takes 1.4 s; drawing 768 real
   Gaussian hyperplanes and projecting onto them would have cost
   28,670 × 768 × 768 = 17 G MAC, about three minutes.

   The axes are usable as hyperplanes only because the *centered* cloud
   is nearly isotropic — the same isotropy ``projection.py``'s docstring
   documents from the other side (three principal axes at std 0.1332,
   0.1236, 0.1190, no eigengap). Centering is what does the work:
   uncentered, these vectors sit in a narrow cone with mean pairwise
   cosine 0.535, and every blocking scheme drowns.

2. **Hamming prefilter, then exact verification.** ``(a ^ b).bit_count()``
   is one C-level int op — measured 43 ns/pair against 8.5 µs for a
   768-dim ``sumprod``, ~200× cheaper — so all 411 M pairs are screened
   in ~18 s, and only survivors pay for a real dot product. The score
   reported is always the exact cosine, never the Hamming estimate: the
   prefilter can cost recall, never precision.

Measured end to end on Pouya's live index (28,670 × 768, under
``nomic-embed-text``, the local embedding model Klaus ran on 2026-09-01
and no longer ships, python 3.14 — Anki bundles 3.13),
running this module, not a prototype of it:

    column_means            0.9 s
    sign_signatures         1.5 s
    random-pair sample      0.1 s   (cut 287 of 768; 1,436,205 candidates
                                     out of 410,970,115 pairs = 0.35%)
    sweep + exact verify   33.4 s
    ------------------------------
    scan_index             35.9 s

against **57 minutes** for the same answer by brute force (250 exact
full scans took 59.6 s, so 28,670 of them is 3,412 s) — 95× — at recall
**1.000 at every tier**: all 46 pairs ≥ 0.95, all 246 ≥ 0.90 and all 955
≥ 0.85 that exact scans of 250 random notes turned up were also found by
the filter, and ``audit_rows=40`` inside the run agreed at 180/180.

Why not banded LSH, which is the textbook answer
------------------------------------------------
Because the numbers say no. Banding needs the per-band collision
probability of a true pair, ``p**r``, to stay near 1 while a random
pair's stays near 0. On this data a cosine-0.85 pair agrees on 0.71 of
the sign bits and a random pair on 0.50. Bands of 8 bits: recall needs
L = 64 tables (512 bits, which is most of the budget) and yields
411 M × 0.222 = **91 million** candidate pairs — 100× worse than the
851,680 the flat Hamming sweep produced at recall 1.000. Bands of 16
bits with the same 768-bit budget (L = 48) collapse to 18% recall.
Banding wins when p is ~0.95; at 0.71 the flat sweep wins outright, and
it wins by being simpler.

Sorted-neighbourhood blocking on ``projection.py``'s principal
components was the other named candidate and is worse still: the fit
alone costs 29 s (K-167 measured it), and the components carry so little
of the variance that a cosine-0.85 pair — Euclidean distance 0.55 on
unit vectors — is 4 standard deviations wide on an axis whose own std is
0.133. The window would have to be most of the collection.

Choosing the cut
----------------
``hamming_cut`` is derived from a **candidate budget**, not from a
constant tuned on one model. ``scan_index`` samples random pairs,
measures their Hamming distribution, and takes the quantile that admits
about ``candidate_budget`` pairs. That bounds the verification bill in
absolute terms on any collection, and it degrades correctly: when the
collection is small enough that every pair fits in the budget the cut
opens to ``dims`` and the scan becomes exact brute force with no
prefilter at all.

A constant would have been model-specific: the cut that makes 0.359 the
right fraction for one embedding space transfers to no other, and Klaus
has already changed spaces once (the local 768-dim model these numbers
were read on, then OpenAI ``text-embedding-3-large`` at 1024 from
2026-09-15). So it is measured per run instead. ``audit_rows`` turns the guess into a number:
it exact-scans that many random notes after the sweep and reports the
recall actually achieved.

What the scores mean (calibrated on Pouya's collection, 2026-09-01)
------------------------------------------------------------------
Counts over all 411 M pairs, medical flashcards, heavy cloze,
mostly AnKing/Bootcamp-derived:

    cosine ≥ 0.95    2,067 pairs      DUPLICATE tier
    0.90 – 0.95     13,389 pairs      NEAR tier
    0.85 – 0.90     50,955 pairs      CLOSE tier

and, read from real pairs rather than assumed:

- **Cosine is not a duplicate detector; it is a "same subject matter"
  detector, and the very top of it is worse than the middle.** The 64
  pairs above 0.99 are dominated by deliberate CONTRAST pairs — "a
  decrease in SVR causes an upward shift" against "an increase in SVR
  causes a downward shift"; "proximal → medially" against "distal →
  laterally"; standard deviation against standard error. Antonyms sit
  closer in embedding space than paraphrases do. Ranking by cosine alone
  therefore puts the *least* deletable pairs on top, which is why
  ``ScanResult`` reports counts per tier and leaves the verdict to the
  caller.
- **The genuine finds — the ones Anki cannot make — are high cosine with
  LOW literal overlap.** "HDL transfers cholesteryl esters … via CETP"
  and "Cholesteryl ester inside of mature HDL may be transferred … via
  the enzyme CETP" (0.9686). "Which two anti-influenza drugs inhibit the
  M2 channels?" and "… inhibit viral uncoating?" (0.9506, both answering
  amantadine/rimantadine). "Which carcinoma seeds body cavities? Ovarian"
  and "The most common body cavity seeded by a tumor is the peritoneal
  cavity" (0.9484, different decks, no shared wording).
- **Exact-text duplicates are not the same population and are free.**
  ``exact_text_groups`` reads ``index.hashes``, which ``card_index``
  keeps anyway. On this collection it returns ZERO groups — no two notes
  have identical embeddable text — which is itself the argument for this
  module: a matcher that only sees identical strings has nothing to say
  here.

Cloze siblings, and why nothing is filtered out
-----------------------------------------------
Sibling notes from one source block are the dominant false positive, so
two structural discriminators were built and MEASURED against real pairs
before being rejected as filters:

- *Cloze-answer overlap.* Fails both ways. "Purkinje cells → GABA" and
  "Golgi cells → GABA" share an answer exactly and are not duplicates;
  the CETP pair above shares one and is. Requiring identical answer
  tokens at cosine ≥ 0.90 leaves 1,218 pairs of which a hand-read sample
  was ~2 in 10 genuine.
- *Lexical overlap* (``lexical_overlap``, kept below). Much better as a
  signal: every sampled pair above 0.85 word-set Jaccard was a sibling
  ("2 month old" against "12 month old", ECF against ICF), and every
  genuine semantic find sat under 0.40. But it cannot be a filter
  either, because the three identical "ID Structure: Medial lemniscus"
  notes are REAL duplicates at Jaccard ≈ 0.9, and a filter would delete
  exactly the pairs the user most wants.

So: nothing is suppressed. ``lexical_overlap`` is exported for the
Browse surface (K-170) to sort or badge with, and this module reports
what it measured rather than pretending to a judgement the vectors
cannot make.
"""

from __future__ import annotations

import heapq
import random
import threading
from array import array
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from . import card_index

try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (Anki bundles 3.13; this repo's
    # plain `python3` for headless test runs is 3.9)
    def _sumprod(a, b):  # type: ignore[misc]
        return sum(x * y for x, y in zip(a, b))

try:
    (0).bit_count  # noqa: B018  — 3.10+
except AttributeError:  # pragma: no cover - 3.9 test interpreter only
    def _popcount(x: int) -> int:
        return bin(x).count("1")
else:
    def _popcount(x: int) -> int:
        return x.bit_count()


# --------------------------------------------------------------- tiers

# Calibrated against Pouya's 28,670-note index on 2026-09-01, under the
# local embedding model Klaus ran then (768 dims) — see "What the scores
# mean" above: these are band edges read off real pairs, not round
# numbers. The 2026-09-15 API-first turn moved embeddings to OpenAI
# text-embedding-3-large at 1024 dims, and different models at different
# widths do not share a cosine geometry, so these edges are NOT
# transferable unchanged. There is no formula that rescales one model's
# thresholds onto another's — re-reading them needs a live pass over real
# pairs embedded by the model actually in use (K-233's follow-up, needs
# ``KLAUS_LIVE_API=1`` and a real collection; not done here, and not
# fakeable from this headless environment without shipping a confidently
# wrong number in place of an honestly stale one).
#
# What THIS module does instead: know which model it was calibrated for,
# and say so loudly when the index it is scoring was built by a different
# one. ``CALIBRATION_SIGNATURE`` names that model; ``Tiers.calibration``
# carries it; ``tiers_calibrated()`` is the one check (mirroring
# ``index_is_current`` below, same ``card_index.check_signature`` engine)
# and ``duplicates_of``/``scan_index`` print a one-line, log-once warning
# the first time they score an index that fails it.
DUPLICATE = 0.95
NEAR = 0.90
CLOSE = 0.85

TIER_NAMES = ("duplicate", "near", "close")

# The (provider, model, dims) these floors were read off — the local
# Ollama model Klaus ran before the 2026-09-15 API-first turn (deleted
# with ollama_client.py; the exact provider string is inferred from that
# module's name, not preserved anywhere still importable). Width is
# non-zero on purpose: ``signature_matches`` treats a 0 width as "any
# width", which would silently swallow the exact mismatch this exists to
# catch.
CALIBRATION_SIGNATURE: tuple[str, str, int] = ("ollama", "nomic-embed-text:latest", 768)


@dataclass(frozen=True)
class Tiers:
    """The three bands the user asked for, in his words, plus the
    (provider, model, dims) signature they were calibrated against."""

    duplicate: float = DUPLICATE
    near: float = NEAR
    close: float = CLOSE
    calibration: tuple = CALIBRATION_SIGNATURE

    def name_for(self, score: float) -> str:
        if score >= self.duplicate:
            return "duplicate"
        if score >= self.near:
            return "near"
        if score >= self.close:
            return "close"
        return ""


DEFAULT_TIERS = Tiers()

# ponytail: process-lifetime log-once set, not persisted config — a
# second profile load or a changed index re-warns, which is the point.
_warned_uncalibrated: set = set()


def tiers_calibrated(index: card_index.CardIndex | None, tiers: Tiers = DEFAULT_TIERS) -> bool:
    """True when ``index`` was actually built by the model these tiers'
    band edges were read off — never the config's target, always what is
    really on disk (``index_is_current`` below makes the same choice for
    the same reason: config can drift, the index cannot lie about itself).
    """
    return card_index.check_signature(index, tiers.calibration)


def _warn_if_uncalibrated(index: card_index.CardIndex | None, tiers: Tiers) -> None:
    """Print once per distinct (provider, model, dims) the first time it
    scores against tiers it was never calibrated for. A repeat call with
    the same signature is silent; a different index (new provider, new
    dims) warns again."""
    if index is None or tiers_calibrated(index, tiers):
        return
    key = (index.provider, index.model, index.dims)
    if key in _warned_uncalibrated:
        return
    _warned_uncalibrated.add(key)
    cal_provider, cal_model, cal_dims = tiers.calibration
    print(
        "[klausmate] duplicate tiers calibrated for "
        f"{cal_provider}/{cal_model}@{cal_dims} but this index is "
        f"{index.provider}/{index.model}@{index.dims} — tier names "
        "(duplicate/near/close) are uncalibrated for it"
    )


@dataclass(frozen=True)
class DuplicatePair:
    """Two NOTES and their exact cosine similarity.

    ``nid_a`` is always the smaller id, so a pair has one spelling and
    can be used as a dict key or deduplicated by identity.
    """

    nid_a: int
    nid_b: int
    score: float
    tier: str = ""

    def nids(self) -> tuple[int, int]:
        return (self.nid_a, self.nid_b)


def make_pair(nid_a: int, nid_b: int, score: float, tiers: Tiers = DEFAULT_TIERS):
    lo, hi = (nid_a, nid_b) if nid_a <= nid_b else (nid_b, nid_a)
    return DuplicatePair(lo, hi, float(score), tiers.name_for(score))


@dataclass
class ScanStats:
    """What the scan actually did — every number measured, none assumed."""

    notes: int = 0
    dims: int = 0
    pairs_total: int = 0
    candidates: int = 0
    hamming_bits: int = 0
    hamming_cut: int = 0
    exact: bool = False
    counts: dict = field(default_factory=dict)  # tier name -> pair count
    truncated: bool = False
    cancelled: bool = False
    audit_rows: int = 0
    audit_pairs: int = 0
    audit_found: int = 0
    tiers_calibrated: bool = False

    @property
    def audit_recall(self) -> float | None:
        """Fraction of the audit's exactly-known pairs the scan found, or
        None when no audit ran. This is the honest recall number — it is
        measured on rows drawn AFTER the cut was chosen, so it is not the
        cut's own training set."""
        if not self.audit_pairs:
            return None
        return self.audit_found / self.audit_pairs


@dataclass
class ScanResult:
    pairs: list = field(default_factory=list)
    stats: ScanStats = field(default_factory=ScanStats)


# ------------------------------------------------------- shape A: one note


def row_of(index: card_index.CardIndex, nid: int) -> int:
    """Row index for ``nid``, or -1 when the note has no vector (absent,
    or in ``skipped`` because it had no embeddable text)."""
    try:
        return index.nids.index(int(nid))
    except ValueError:
        return -1


def duplicates_of(
    index: card_index.CardIndex,
    nid: int,
    *,
    limit: int = 20,
    threshold: float = CLOSE,
    tiers: Tiers = DEFAULT_TIERS,
) -> list:
    """The notes most similar to ``nid`` — shape A, the instant one.

    One vector against the whole index via ``card_index.top_k``: ~0.24 s
    on a 28,670 × 768 index. ``nid`` itself is never returned (it would
    always score 1.0 and always rank first).

    Returns [DuplicatePair] sorted by score descending, at most ``limit``.
    An unknown / text-less nid returns [] rather than raising: the caller
    is a UI reacting to a selection, and a note with no vector is a
    normal state, not an error.
    """
    row = row_of(index, nid)
    if row < 0 or limit <= 0:
        return []
    _warn_if_uncalibrated(index, tiers)
    d = index.dims
    vec = array("f", memoryview(index.vectors)[row * d : (row + 1) * d])
    hits = neighbours_of_vector(
        index, vec, limit=limit, threshold=threshold, exclude_nid=int(nid)
    )
    return [make_pair(int(nid), other, score, tiers) for other, score in hits]


def neighbours_of_vector(
    index: card_index.CardIndex,
    vec,
    *,
    limit: int = 20,
    threshold: float = CLOSE,
    exclude_nid: int | None = None,
) -> list:
    """``duplicates_of`` for a vector that may not be in the index yet —
    a note being edited, or a draft.

    Returns [(nid, score)] rather than pairs on purpose: a loose vector
    has no note identity, so there is no honest second half of a pair to
    name. ``duplicates_of`` is the wrapper that has one.
    """
    if limit <= 0 or not index.nids:
        return []
    want = limit + (1 if exclude_nid is not None else 0)
    hits = card_index.top_k(index, [vec], want, min_score=threshold)
    out = []
    for other, score in hits:
        if exclude_nid is not None and other == exclude_nid:
            continue
        out.append((other, score))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------- shape B: the whole index


def column_means(index: card_index.CardIndex) -> array:
    """Per-coordinate mean over every row — the split point the sign
    signatures hash against. 1.5 s on 28,670 × 768."""
    d = index.dims
    n = len(index.nids)
    out = array("d", bytes(8 * d))
    if not n or d <= 0:
        return array("f", out)
    mv = memoryview(index.vectors)
    for i in range(n):
        row = mv[i * d : (i + 1) * d]
        for j in range(d):
            out[j] += row[j]
    for j in range(d):
        out[j] /= n
    # float32 so the comparison below is against the same precision the
    # vectors are stored in — a float64 mean would flip bits at random
    # for coordinates that sit exactly on it.
    return array("f", out)


def sign_signatures(index: card_index.CardIndex, means) -> list:
    """One ``dims``-bit int per NOTE: bit j set when coordinate j is above
    the collection mean. 1.4 s on 28,670 × 768; see the module docstring
    for why the coordinate axes are usable as LSH hyperplanes here."""
    d = index.dims
    n = len(index.nids)
    if not n or d <= 0:
        return []
    mv = memoryview(index.vectors)
    out = []
    push = out.append
    rng = range(d)
    for i in range(n):
        row = mv[i * d : (i + 1) * d]
        bits = 0
        for j in rng:
            bits = (bits << 1) | (row[j] > means[j])
        push(bits)
    return out


def sample_hamming(sigs: Sequence, samples: int = 200_000, seed: int = 0) -> list:
    """Sorted Hamming distances of random note pairs — the empirical
    distribution ``hamming_cut_for`` reads its quantile off. Self-pairs
    are skipped: they are distance 0 and would bias the low tail that is
    the only part being used."""
    n = len(sigs)
    if n < 2:
        return []
    rng = random.Random(seed)
    out = []
    push = out.append
    for _ in range(samples):
        a = rng.randrange(n)
        b = rng.randrange(n)
        if a == b:
            continue
        push(_popcount(sigs[a] ^ sigs[b]))
    out.sort()
    return out


def hamming_cut_for(
    dist: Sequence, pairs_total: int, candidate_budget: int, bits: int
) -> int:
    """The Hamming cut that admits roughly ``candidate_budget`` pairs.

    Read as a quantile of the sampled random-pair distribution, so it
    adapts to the embedding model instead of hardcoding a fraction
    measured on one of them. When the budget covers every pair the cut
    opens to ``bits`` — i.e. the prefilter turns itself off and the scan
    is exact brute force, which is the right answer for a collection
    small enough to afford it.
    """
    if bits <= 0:
        return 0
    if not dist or pairs_total <= 0:
        return bits
    # max(0, ...) is not hygiene: a negative budget would make k a
    # negative index, and dist[-2000] is one of the LOOSEST distances in
    # the sample — nonsense in, slowest possible scan out.
    k = int((max(0, candidate_budget) / pairs_total) * len(dist))
    if k >= len(dist):
        return bits  # the budget covers every pair: prefilter OFF
    return int(dist[k])


def _exact_neighbours(
    index: card_index.CardIndex, row: int, threshold: float
) -> list:
    """Every row scoring >= threshold against ``row`` — one honest full
    scan, used by the audit."""
    d = index.dims
    mv = memoryview(index.vectors)
    q = mv[row * d : (row + 1) * d]
    out = []
    for i in range(len(index.nids)):
        if i == row:
            continue
        s = _sumprod(mv[i * d : (i + 1) * d], q)
        if s >= threshold:
            out.append((i, s))
    return out


def scan_index(
    index: card_index.CardIndex,
    *,
    threshold: float = CLOSE,
    tiers: Tiers = DEFAULT_TIERS,
    limit: int = 2000,
    candidate_budget: int = 1_500_000,
    hamming_cut: int | None = None,
    sample_size: int = 200_000,
    audit_rows: int = 0,
    seed: int = 0,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """Every near-duplicate NOTE pair in the collection — shape B.

    ``limit`` bounds the returned list (highest score first); ``stats
    .counts`` always carries the true per-tier totals, so a truncated
    result never lies about how many there were. ``candidate_budget``
    bounds the exact-verification bill; pass ``hamming_cut=dims`` (or a
    budget above ``pairs_total``) to force an exact brute-force scan.

    ``cancel`` is checked once per row and ``on_progress(done, total)``
    called every 256 rows — the house convention from
    ``retention.match_scores``. A cancelled scan returns what it had,
    with ``stats.cancelled`` set: partial results are useful here (the
    sweep visits rows in order and each row's pairs are complete when it
    finishes), but they must be labelled.
    """
    n = len(index.nids)
    d = index.dims
    stats = ScanStats(notes=n, dims=d, pairs_total=n * (n - 1) // 2)
    stats.counts = {name: 0 for name in TIER_NAMES}
    stats.tiers_calibrated = tiers_calibrated(index, tiers)
    result = ScanResult(pairs=[], stats=stats)
    if n < 2 or d <= 0 or limit <= 0:
        return result
    _warn_if_uncalibrated(index, tiers)

    nids = index.nids
    means = column_means(index)
    sigs = sign_signatures(index, means)
    stats.hamming_bits = d

    if hamming_cut is None:
        dist = sample_hamming(sigs, samples=sample_size, seed=seed)
        cut = hamming_cut_for(dist, stats.pairs_total, candidate_budget, d)
    else:
        cut = max(0, min(int(hamming_cut), d))
    stats.hamming_cut = cut
    stats.exact = cut >= d

    mv = memoryview(index.vectors)
    # Min-heap of (score, nid_a, nid_b) capped at ``limit``; the pair
    # ids ride along so equal scores never compare DuplicatePair objects.
    heap: list = []
    candidates = 0
    for i in range(n - 1):
        if cancel is not None and cancel.is_set():
            stats.cancelled = True
            break
        if on_progress is not None and i % 256 == 0:
            on_progress(i, n)
        a = sigs[i]
        tail = sigs[i + 1 :]
        hits = [k for k, b in enumerate(tail) if _popcount(a ^ b) <= cut]
        if not hits:
            continue
        candidates += len(hits)
        row = mv[i * d : (i + 1) * d]
        for k in hits:
            j = i + 1 + k
            score = _sumprod(row, mv[j * d : (j + 1) * d])
            if score < threshold:
                continue
            name = tiers.name_for(score)
            if name:
                stats.counts[name] = stats.counts.get(name, 0) + 1
            if len(heap) < limit:
                heapq.heappush(heap, (score, nids[i], nids[j]))
            elif score > heap[0][0]:
                heapq.heapreplace(heap, (score, nids[i], nids[j]))
                stats.truncated = True
            else:
                stats.truncated = True
    if on_progress is not None:
        on_progress(n, n)
    stats.candidates = candidates
    result.pairs = [
        make_pair(a, b, s, tiers)
        for s, a, b in sorted(heap, key=lambda t: -t[0])
    ]

    if audit_rows > 0 and not stats.cancelled:
        _run_audit(index, sigs, cut, threshold, audit_rows, seed, stats)
    return result


def _run_audit(
    index: card_index.CardIndex,
    sigs: Sequence,
    cut: int,
    threshold: float,
    audit_rows: int,
    seed: int,
    stats: ScanStats,
) -> None:
    """Measure the prefilter's recall on rows the cut was NOT chosen from.

    For each audited row every neighbour at/above ``threshold`` is found
    exactly, then re-checked against the Hamming cut. Recall is the only
    thing at risk — the verification stage is exact — so this is the whole
    correctness question, answered with a number instead of an argument.
    """
    n = len(index.nids)
    # A different stream from the one that chose the cut.
    rng = random.Random(seed + 977)
    rows = rng.sample(range(n), min(audit_rows, n))
    found = 0
    total = 0
    for row in rows:
        a = sigs[row]
        for other, _score in _exact_neighbours(index, row, threshold):
            total += 1
            if _popcount(a ^ sigs[other]) <= cut:
                found += 1
    stats.audit_rows = len(rows)
    stats.audit_pairs = total
    stats.audit_found = found


# ------------------------------------------------------------ free extras


def exact_text_groups(index: card_index.CardIndex) -> list:
    """Notes whose embeddable text is byte-identical, grouped.

    ``card_index`` already stores a blake2b hash per row as its change
    detector, so this costs one pass and no arithmetic. It is a strictly
    stronger version of what Anki's Find Duplicates does with one field —
    and on Pouya's collection it returns nothing at all, which is the
    measured case for wanting the semantic scan.

    Returns [[nid, ...]] with groups of two or more, each group sorted.
    """
    seen: dict = {}
    for nid, h in zip(index.nids, index.hashes):
        seen.setdefault(h, []).append(nid)
    return [sorted(g) for g in seen.values() if len(g) > 1]


def group_pairs(pairs: Iterable) -> list:
    """Connected components over a pair list — "these five notes are all
    about the same thing" rather than ten separate rows.

    Union-find with path halving; returns [[nid, ...]] sorted by size
    descending then by first nid, so the output is stable.

    Transitive closure OVERREACHES at these thresholds and the caller
    should know it: over the 2,067 duplicate-tier pairs on Pouya's index
    this yields 1,405 clusters, and the largest is 14 notes that turn out
    to be an entire folate/B12 section of one deck — a topic, not a
    duplicate set. Pairs are the honest primitive; clusters are a summary
    view, not a delete list.
    """
    parent: dict = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pair in pairs:
        ra, rb = find(pair.nid_a), find(pair.nid_b)
        if ra != rb:
            parent[ra] = rb
    groups: dict = {}
    for nid in parent:
        groups.setdefault(find(nid), []).append(nid)
    out = [sorted(g) for g in groups.values() if len(g) > 1]
    out.sort(key=lambda g: (-len(g), g[0]))
    return out


_WORD_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789")


def word_set(text: str) -> frozenset:
    """Lowercased alphanumeric word set — the unit ``lexical_overlap``
    compares. Deliberately naive: it is a sorting signal for the UI, not
    a linguistic claim, and anything cleverer would need a tokenizer this
    module has no business owning."""
    out = []
    buf = []
    for ch in text.lower():
        if ch in _WORD_CHARS:
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return frozenset(out)


def lexical_overlap(text_a: str, text_b: str) -> float:
    """Word-set Jaccard of two notes' text, 0.0 – 1.0.

    NOT a filter (the module docstring says why at length): every sampled
    pair above 0.85 was a sibling note carved out of one shared block,
    and every genuine semantic find sat below 0.40 — but the three
    identical "ID Structure: Medial lemniscus" notes are real duplicates
    at ~0.9, so suppressing the high end would delete the best answers.
    Exported so the Browse surface can sort or badge with it.
    """
    a = word_set(text_a)
    b = word_set(text_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def index_is_current(index: card_index.CardIndex | None, signature: tuple) -> bool:
    """True when the index was built by the configured provider/model.

    Delegates to ``card_index.check_signature`` → ``embeddings
    .signature_matches``, which is the one sanctioned comparison. A
    hand-spelled tuple ``==`` reads every cache as stale (that is exactly
    how widening the signature broke eight call sites at once), and here
    it would silently score notes against vectors from another model.
    """
    return card_index.check_signature(index, signature)
