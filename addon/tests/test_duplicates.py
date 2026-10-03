"""K-168 — the semantic duplicate finder engine.

Runs under this machine's python3 (3.9): no ``math.sumprod``, no
``int.bit_count``, so the module's two fallbacks are exercised here by
construction rather than by a flag.

The synthetic index is shaped like the real one on purpose — an
isotropic cloud pushed off the origin by a large shared mean, which is
what makes raw pairwise cosine high (0.535 on Pouya's collection) and is
the whole reason the sign signatures split at the MEAN rather than at
zero. A test built on a zero-mean cloud would pass while the shipped
code failed on real data.
"""

import importlib
import math
import os
import random
import re
import sys
import threading

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install_package_stub, report, section  # noqa: E402

install_package_stub()
card_index = importlib.import_module("klaus_note.card_index")
duplicates = importlib.import_module("klaus_note.duplicates")

SRC = open(os.path.join("klaus_note", "duplicates.py"), encoding="utf-8").read()


# --------------------------------------------------------------- fixtures


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def build_index(n=260, d=48, planted=(), seed=1, provider="ollama",
                model="nomic-embed-text:latest"):
    """A cloud with a strong shared mean, plus planted near-duplicates.

    ``planted`` is a list of (row_a, row_b, noise): row_b is rebuilt as
    row_a plus gaussian noise, so their cosine is high and controllable.
    """
    from array import array

    rng = random.Random(seed)
    offset = [rng.gauss(0, 1) for _ in range(d)]
    rows = []
    for _ in range(n):
        rows.append(_unit([offset[j] + rng.gauss(0, 0.75) for j in range(d)]))
    for a, b, noise in planted:
        rows[b] = _unit([rows[a][j] + rng.gauss(0, noise) for j in range(d)])
    ix = card_index.CardIndex(provider=provider, model=model, dims=d)
    ix.nids = [1000 + i for i in range(n)]
    ix.mods = [1 for _ in range(n)]
    ix.hashes = ["h%04d" % i for i in range(n)]
    ix.vectors = array("f")
    for r in rows:
        ix.vectors.extend(array("f", r))
    return ix


def cos(ix, a, b):
    d = ix.dims
    mv = memoryview(ix.vectors)
    return sum(
        x * y for x, y in zip(mv[a * d:(a + 1) * d], mv[b * d:(b + 1) * d])
    )


# 40 planted twins spread across the index, at noise levels that land
# them across all three tiers. Enough of the collection is involved that
# a 24-row audit sample reliably lands on some — the real index has the
# same property (every note has SOME neighbour above 0.85 far more often
# than a synthetic cloud does).
PLANTED = [(3, 7, 0.02), (11, 40, 0.06)] + [
    (5 * k, 5 * k + 2, 0.02 + 0.002 * k) for k in range(2, 40)
]
IX = build_index(planted=PLANTED)


# ------------------------------------------------------------------ tiers

section("tiers")

T = duplicates.DEFAULT_TIERS
check("0.96 is a duplicate", T.name_for(0.96) == "duplicate")
check("0.95 exactly is a duplicate (band edges are inclusive at the floor)",
      T.name_for(0.95) == "duplicate")
check("0.93 is near", T.name_for(0.93) == "near")
check("0.87 is close", T.name_for(0.87) == "close")
check("0.84 is in no tier at all", T.name_for(0.84) == "")
check("the three tiers are named in the user's own words",
      duplicates.TIER_NAMES == ("duplicate", "near", "close"))
check("the calibrated floors are the measured ones (0.95/0.90/0.85)",
      (duplicates.DUPLICATE, duplicates.NEAR, duplicates.CLOSE)
      == (0.95, 0.90, 0.85))

p = duplicates.make_pair(500, 200, 0.97)
check("a pair has ONE spelling: the smaller nid is always first",
      (p.nid_a, p.nid_b) == (200, 500))
check("...and carries its tier", p.tier == "duplicate")
check("nids() returns them in that order", p.nids() == (200, 500))


# ------------------------------------------------- shape A: one note
section("shape A — duplicates of THIS note")

hits = duplicates.duplicates_of(IX, 1003, limit=5, threshold=0.5)
check("the planted twin of row 3 (nid 1007) is found",
      any(h.nid_b == 1007 or h.nid_a == 1007 for h in hits))
check("the note itself is never returned",
      all(1003 in (h.nid_a, h.nid_b) for h in hits)
      and not any(h.nid_a == h.nid_b for h in hits))
check("every returned pair is anchored on the queried note",
      all(1003 in h.nids() for h in hits))
check("results are sorted by score descending",
      all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1)))
check("limit is honoured", len(duplicates.duplicates_of(
    IX, 1003, limit=2, threshold=0.0)) == 2)
check("an unknown nid returns [] rather than raising",
      duplicates.duplicates_of(IX, 999999) == [])
check("limit 0 returns []", duplicates.duplicates_of(IX, 1003, limit=0) == [])
check("threshold is a floor on the score",
      all(h.score >= 0.9 for h in duplicates.duplicates_of(
          IX, 1003, limit=10, threshold=0.9)))

from array import array as _array  # noqa: E402

qvec = _array("f", memoryview(IX.vectors)[3 * IX.dims:4 * IX.dims])
raw = duplicates.neighbours_of_vector(IX, qvec, limit=3, threshold=0.0)
check("a loose vector gets (nid, score) tuples, not a pair with no second half",
      raw and isinstance(raw[0], tuple) and len(raw[0]) == 2)
check("without an exclusion the vector's own row is included (score 1.0)",
      abs(raw[0][1] - 1.0) < 1e-5)


# ------------------------------------------------ signatures & the cut
section("sign signatures")

means = duplicates.column_means(IX)
check("one mean per dimension", len(means) == IX.dims)
mv = memoryview(IX.vectors)
col0 = [mv[i * IX.dims] for i in range(len(IX.nids))]
check("the mean really is the column mean",
      abs(means[0] - sum(col0) / len(col0)) < 1e-5)
check("the cloud is NOT centred on the origin — the fixture reproduces the "
      "real index's off-origin geometry",
      max(abs(x) for x in means) > 0.05)

sigs = duplicates.sign_signatures(IX, means)
check("one signature per note", len(sigs) == len(IX.nids))
check("a signature never exceeds dims bits",
      all(s < (1 << IX.dims) for s in sigs))
bit_hi = (sigs[0] >> (IX.dims - 1)) & 1
check("bit 0 of the signature is 'coordinate 0 is above its mean'",
      bit_hi == int(mv[0] > means[0]))
bit_lo = sigs[5] & 1
check("...and the last bit is the last coordinate",
      bit_lo == int(mv[5 * IX.dims + IX.dims - 1] > means[IX.dims - 1]))

dist = duplicates.sample_hamming(sigs, samples=4000, seed=0)
check("the random-pair sample is sorted", dist == sorted(dist))
check("self-pairs are excluded, so distance 0 is not manufactured",
      0 not in dist or min(dist) > 0)
check("random pairs sit near half the bits — the mean split balances them",
      0.35 < (sum(dist) / len(dist)) / IX.dims < 0.65)

bits = IX.dims
total = len(IX.nids) * (len(IX.nids) - 1) // 2
check("a budget covering every pair turns the prefilter OFF (cut = dims)",
      duplicates.hamming_cut_for(dist, total, total, bits) == bits)
check("...and so does a budget larger than the collection",
      duplicates.hamming_cut_for(dist, total, total * 10, bits) == bits)
check("no sampled distribution also means no prefilter",
      duplicates.hamming_cut_for([], total, 10, bits) == bits)
tight = duplicates.hamming_cut_for(dist, total, total // 100, bits)
loose = duplicates.hamming_cut_for(dist, total, total // 4, bits)
check("a smaller budget buys a tighter cut", tight < loose <= bits)
check("dims 0 cannot produce a cut", duplicates.hamming_cut_for(dist, 10, 1, 0) == 0)
check("a zero budget clamps to the tightest observed distance",
      duplicates.hamming_cut_for(dist, total, 0, bits) == dist[0])
check("a NEGATIVE budget clamps there too — unclamped, k would be a negative "
      "index and dist[-2000] is one of the LOOSEST distances in the sample",
      duplicates.hamming_cut_for(dist, total, -(total // 2), bits) == dist[0])


# ---------------------------------------------- shape B: the whole index
section("shape B — scan the whole collection")

exact = duplicates.scan_index(IX, threshold=0.85, hamming_cut=IX.dims, limit=500)
check("exact mode reports itself as exact", exact.stats.exact)
check("exact mode compares every pair", exact.stats.candidates == total)
check("the scan finds the planted near-duplicates",
      {(1003, 1007), (1011, 1040)} <= {pp.nids() for pp in exact.pairs})
check("every reported score really is >= the threshold",
      all(pp.score >= 0.85 for pp in exact.pairs))
check("every reported score is the EXACT cosine, not the Hamming estimate",
      all(abs(pp.score - cos(IX, IX.nids.index(pp.nid_a),
                             IX.nids.index(pp.nid_b))) < 1e-5
          for pp in exact.pairs))
check("pairs come back highest first",
      all(exact.pairs[i].score >= exact.pairs[i + 1].score
          for i in range(len(exact.pairs) - 1)))
check("stats.notes / dims describe the index",
      exact.stats.notes == len(IX.nids) and exact.stats.dims == IX.dims)
check("stats.pairs_total is n(n-1)/2", exact.stats.pairs_total == total)
check("tier counts add up to the pairs found",
      sum(exact.stats.counts.values()) == len(exact.pairs))

filt = duplicates.scan_index(IX, threshold=0.85, limit=500,
                             candidate_budget=total // 3, sample_size=4000)
check("the prefilter really filtered", filt.stats.candidates < total)
check("...and did not report itself as exact", not filt.stats.exact)
check("THE PREFILTER IS ONLY A FILTER: with a generous budget it returns "
      "exactly what brute force returned",
      {pp.nids() for pp in filt.pairs} == {pp.nids() for pp in exact.pairs})
check("...with identical tier counts", filt.stats.counts == exact.stats.counts)

capped = duplicates.scan_index(IX, threshold=0.85, hamming_cut=IX.dims, limit=2)
check("limit caps the returned list", len(capped.pairs) == 2)
check("...and says so", capped.stats.truncated)
check("...but the tier COUNTS still tell the truth about the whole scan",
      capped.stats.counts == exact.stats.counts)
check("the two returned pairs are the two best",
      [pp.nids() for pp in capped.pairs] == [pp.nids() for pp in exact.pairs[:2]])
check("an untruncated scan says so", not exact.stats.truncated)

seen = []
duplicates.scan_index(IX, threshold=0.85, hamming_cut=IX.dims,
                      on_progress=lambda a, b: seen.append((a, b)))
check("progress is reported", len(seen) > 1)
check("progress ends at 100%", seen[-1] == (len(IX.nids), len(IX.nids)))

ev = threading.Event()
ev.set()
stopped = duplicates.scan_index(IX, threshold=0.85, hamming_cut=IX.dims, cancel=ev)
check("a pre-set cancel event stops the scan", stopped.stats.cancelled)
check("...and a cancelled scan is LABELLED, not silently short",
      stopped.pairs == [] and stopped.stats.cancelled)
check("an uncancelled scan is not labelled cancelled", not exact.stats.cancelled)

audited = duplicates.scan_index(IX, threshold=0.85, limit=500,
                                candidate_budget=total // 3, sample_size=4000,
                                audit_rows=24)
check("the audit ran", audited.stats.audit_rows == 24)
check("the audit found pairs to check", audited.stats.audit_pairs > 0)
check("the audit reports a recall between 0 and 1",
      0.0 <= audited.stats.audit_recall <= 1.0)
check("no audit means no recall claim (None, never a made-up 1.0)",
      exact.stats.audit_recall is None)

tiny = card_index.CardIndex(provider="ollama", model="m", dims=4)
check("an empty index scans to nothing", duplicates.scan_index(tiny).pairs == [])
check("...and reports zero pairs", duplicates.scan_index(tiny).stats.pairs_total == 0)


# ------------------------------------------------------- recall property
section("recall against brute force")

# The whole correctness question: verification is exact, so the ONLY
# thing the prefilter can cost is recall. Measure it against a real
# brute-force sweep rather than asserting it.
truth = set()
n = len(IX.nids)
for i in range(n):
    for j in range(i + 1, n):
        if cos(IX, i, j) >= 0.85:
            truth.add((IX.nids[i], IX.nids[j]))
got = {pp.nids() for pp in filt.pairs}
check("brute force and the shipped scan agree pair for pair at cosine >= 0.85",
      got == truth)
check("...on a non-trivial number of pairs, spread across all three tiers "
      "(a fixture that only exercised one band would prove nothing)",
      len(truth) == 38 and filt.stats.counts
      == {"duplicate": 16, "near": 12, "close": 10})

starved = duplicates.scan_index(IX, threshold=0.85, limit=500,
                                candidate_budget=1, sample_size=4000)
check("a starved budget can only LOSE pairs, never invent them",
      {pp.nids() for pp in starved.pairs} <= truth)


# ------------------------------------------------------------ free extras
section("exact text groups, clustering, lexical overlap")

IXH = build_index(n=20, d=16, seed=4)
IXH.hashes = ["a", "b", "a", "c", "b", "a"] + ["u%d" % i for i in range(14)]
groups = duplicates.exact_text_groups(IXH)
check("identical text hashes group up",
      sorted(groups) == sorted([[1000, 1002, 1005], [1001, 1004]]))
check("singletons are not groups",
      all(len(g) > 1 for g in groups))
check("a collection with no identical text yields no groups — which is what "
      "Pouya's real index does, and the argument for this whole module",
      duplicates.exact_text_groups(IX) == [])

mk = duplicates.make_pair
clusters = duplicates.group_pairs([mk(1, 2, 0.99), mk(2, 3, 0.96), mk(8, 9, 0.91)])
check("transitive pairs collapse into one cluster", [1, 2, 3] in clusters)
check("...and a disjoint pair stays its own", [8, 9] in clusters)
check("clusters are ordered biggest first", clusters[0] == [1, 2, 3])
check("no pairs, no clusters", duplicates.group_pairs([]) == [])

check("word_set lowercases and splits on non-alphanumerics",
      duplicates.word_set("A-B, c!") == frozenset({"a", "b", "c"}))
check("identical text has overlap 1.0",
      duplicates.lexical_overlap("alpha beta", "beta alpha") == 1.0)
check("disjoint text has overlap 0.0",
      duplicates.lexical_overlap("alpha", "gamma") == 0.0)
check("half-shared text lands in between",
      abs(duplicates.lexical_overlap("a b", "b c") - 1 / 3) < 1e-9)
check("empty text is 0.0, never a division by zero",
      duplicates.lexical_overlap("", "abc") == 0.0)


# ------------------------------------------------------- calibration
section("calibration: tiers vs. the model that actually made the vectors")

check("DEFAULT_TIERS carries the signature the band edges were read off",
      duplicates.DEFAULT_TIERS.calibration == duplicates.CALIBRATION_SIGNATURE)
check("...and that signature names the local model these floors were "
      "measured under (see the module docstring): ollama/"
      "nomic-embed-text:latest @ 768 dims",
      duplicates.CALIBRATION_SIGNATURE
      == ("ollama", "nomic-embed-text:latest", 768))

calibrated_ix = build_index(n=8, d=768, provider="ollama",
                            model="nomic-embed-text:latest")
openai_ix = build_index(n=8, d=1024, provider="openai",
                        model="text-embedding-3-large")
check("an index actually built by the calibrated model reports calibrated",
      duplicates.tiers_calibrated(calibrated_ix))
check("an index built under the shipped bare default (nomic-embed-text, "
      "Ollama's alias for :latest) reports calibrated too",
      duplicates.tiers_calibrated(build_index(n=8, d=768, provider="ollama",
                                              model="nomic-embed-text")))
check("today's real index — OpenAI text-embedding-3-large at 1024 dims — "
      "reports UNCALIBRATED, which is the whole point of this card",
      not duplicates.tiers_calibrated(openai_ix))
check("no index at all is never calibrated",
      not duplicates.tiers_calibrated(None))

import contextlib  # noqa: E402
import io  # noqa: E402

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    duplicates.duplicates_of(openai_ix, openai_ix.nids[0], threshold=0.0)
    duplicates.duplicates_of(openai_ix, openai_ix.nids[0], threshold=0.0)
    duplicates.scan_index(openai_ix, threshold=0.0, hamming_cut=openai_ix.dims)
out = buf.getvalue()
check("the mismatch is logged once per distinct index signature, house "
      "style (print('[klaus_note] ...')), not once per call",
      out.count("[klaus_note]") == 1)
check("...and it names both the calibrated model and the actual one",
      "nomic-embed-text" in out and "text-embedding-3-large" in out)

buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    duplicates.duplicates_of(calibrated_ix, calibrated_ix.nids[0], threshold=0.0)
check("a calibrated index never logs a mismatch it doesn't have",
      "[klaus_note]" not in buf2.getvalue())


# ------------------------------------------------------------ house rules
section("house rules")

sig3 = ("ollama", "nomic-embed-text:latest", 768)
check("a matching provider/model passes the signature check",
      duplicates.index_is_current(IX, ("ollama", "nomic-embed-text:latest")))
check("a different model fails it",
      not duplicates.index_is_current(IX, ("ollama", "other-model")))
check("width 0 means 'whatever the model gives' and cannot disagree",
      duplicates.index_is_current(IX, ("ollama", "nomic-embed-text:latest", 0)))
check("a non-zero width that disagrees fails",
      not duplicates.index_is_current(IX, ("ollama", "nomic-embed-text:latest", 999)))
check("None is never current", not duplicates.index_is_current(None, sig3))

# The signature comparison has ONE sanctioned spelling. Widening
# index_signature to three elements broke eight hand-spelled call sites
# at once, silently — a 2-tuple compared to a 3-tuple is simply never
# equal, so every cache read as stale. test_klaus_note.py pins the same
# regex over six other modules; this is duplicates.py's copy of it.
_SIG_SPELLINGS = re.compile(
    r"\(\w+\.provider,\s*\w+\.model\)\s*[!=]=\s*(?:cfg_)?sig(?:nature)?\b|"
    r'\(st\["provider"\],\s*st\["model"\]\)\s*[!=]='
)
check("duplicates.py never hand-spells a signature comparison",
      _SIG_SPELLINGS.search(SRC) is None)
check("...it goes through card_index.check_signature, which is the one "
      "caller of embeddings.signature_matches",
      "card_index.check_signature(index, signature)" in SRC)

check("the engine imports no aqt at all — it takes data and returns data",
      not re.search(r"^\s*(import|from)\s+aqt", SRC, re.M))
check("...and no anki either", not re.search(r"^\s*(import|from)\s+anki\b", SRC, re.M))
check("no numpy: Anki's bundled Python does not have it",
      "numpy" not in SRC.replace("no numpy", ""))
check("the engine never opens a file — it cannot touch user_files",
      not re.search(r"\bopen\s*\(", SRC))
check("math.sumprod is imported with the pre-3.12 fallback the house uses",
      "from math import sumprod as _sumprod" in SRC and "ImportError" in SRC)
check("int.bit_count has a pre-3.10 fallback, or this file cannot run here",
      "bit_count" in SRC and 'bin(x).count("1")' in SRC)
check("the module compiles under 3.9's annotation rules",
      "from __future__ import annotations" in SRC.split("\n\n")[0]
      or "from __future__ import annotations" in SRC)

# The docstring carries the measured numbers this card exists to
# establish. If someone rewrites the algorithm, these have to be
# re-measured, and this pin is what makes that impossible to skip.
for token in ("28,670", "411", "nomic-embed-text", "2,067", "13,389", "50,955"):
    check("the docstring keeps the measured figure %r" % token, token in SRC)

raise SystemExit(report())
