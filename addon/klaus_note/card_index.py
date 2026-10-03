"""Persistent embedding index over the user's notes.

Pure stdlib, aqt-free: the caller (curation.py) extracts note text with the
collection open; everything here works on plain values, so the whole module
is testable headlessly.

Storage layout (``user_files/card_index/``):

- ``vectors.f32``   — unit vectors, row-major packed float32
- ``manifest.json`` — parallel lists (nids / mods / hashes), a skipped map
  for text-less notes, and the (provider, model, dims) signature

Change detection: **the text hash decides, the mod time only pre-filters.**
Curation's Browse preview bulk-tags notes, which bumps ``note.mod`` without
touching the text — a mod-based index would re-embed the whole result set
after every preview. Hash comparison turns that into a cheap mod refresh.

Consistency rule: a row's (mod, hash) advances only together with its
vector. A cancelled embedding run therefore leaves not-yet-embedded notes
looking "changed", and the next sync resumes exactly where it stopped.

Crash safety: vectors are written before the manifest (both via tmp +
``os.replace``). A crash in between leaves a manifest whose row count no
longer matches the vector file — ``load()`` detects that and returns None,
which callers treat as "rebuild".
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import time
from array import array
from dataclasses import dataclass, field
from typing import Callable, Iterable

INDEX_VERSION = 1
VECTORS_FILE = "vectors.f32"
MANIFEST_FILE = "manifest.json"

try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (Anki bundles 3.13)
    def _sumprod(a, b):  # type: ignore[misc]
        return sum(x * y for x, y in zip(a, b))

_WS_RE = re.compile(r"\s+")


@dataclass
class CardIndex:
    provider: str
    model: str
    dims: int = 0
    nids: list[int] = field(default_factory=list)
    mods: list[int] = field(default_factory=list)
    hashes: list[str] = field(default_factory=list)
    # nid -> (mod, hash) for notes with no embeddable text (media-only)
    skipped: dict[int, tuple[int, str]] = field(default_factory=dict)
    vectors: array = field(default_factory=lambda: array("f"))
    updated_at: float = 0.0


@dataclass
class SyncPlan:
    # (nid, mod, hash, text) — needs a fresh embedding
    to_embed: list[tuple[int, int, str, str]] = field(default_factory=list)
    # (nid, mod) — text unchanged, only the mod time moved (e.g. tag edits)
    mod_only: list[tuple[int, int]] = field(default_factory=list)
    to_delete: list[int] = field(default_factory=list)
    # (nid, mod, hash) — text is empty now
    new_skipped: list[tuple[int, int, str]] = field(default_factory=list)
    unchanged: int = 0

    def is_noop(self) -> bool:
        return not (
            self.to_embed or self.mod_only or self.to_delete or self.new_skipped
        )


def empty_index(provider: str, model: str, dims: int = 0) -> CardIndex:
    """Callers splat a signature straight in (``empty_index(*signature)``),
    so this has to accept the width the signature now carries."""
    return CardIndex(provider=provider, model=model, dims=int(dims or 0))


def text_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def note_text(fields: Iterable[str], strip_fn: Callable[[str], str], cap: int = 4000) -> str:
    """Join a note's fields into one embeddable string (may be empty)."""
    parts = []
    for f in fields:
        stripped = strip_fn(f or "").strip()
        if stripped:
            parts.append(stripped)
    text = _WS_RE.sub(" ", " \n ".join(parts)).strip()
    return text[:cap]


# ------------------------------------------------------------------- disk


def load(dir_path: str) -> CardIndex | None:
    """Load the index; None on missing/corrupt/mismatched files (= rebuild)."""
    vectors_path = os.path.join(dir_path, VECTORS_FILE)
    m = read_manifest(dir_path)
    if m is None:
        return None
    try:
        nids = [int(n) for n in m["nids"]]
        mods = [int(x) for x in m["mods"]]
        hashes = [str(h) for h in m["hashes"]]
        dims = int(m["dims"])
        if not (len(nids) == len(mods) == len(hashes)):
            return None
        vectors = array("f")
        if nids:
            if dims <= 0:
                return None
            expected = len(nids) * dims * vectors.itemsize
            if os.path.getsize(vectors_path) != expected:
                return None
            with open(vectors_path, "rb") as f:
                vectors.fromfile(f, len(nids) * dims)
        skipped = {
            int(nid): (int(v[0]), str(v[1]))
            for nid, v in (m.get("skipped") or {}).items()
        }
        return CardIndex(
            provider=str(m["provider"]),
            model=str(m["model"]),
            dims=dims,
            nids=nids,
            mods=mods,
            hashes=hashes,
            skipped=skipped,
            vectors=vectors,
            updated_at=float(m.get("updated_at") or 0.0),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(index: CardIndex, dir_path: str) -> None:
    """Atomic save: vectors first, manifest second (see module docstring)."""
    os.makedirs(dir_path, exist_ok=True)
    index.updated_at = time.time()

    vectors_path = os.path.join(dir_path, VECTORS_FILE)
    tmp = vectors_path + ".tmp"
    with open(tmp, "wb") as f:
        index.vectors.tofile(f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, vectors_path)

    manifest = {
        "version": INDEX_VERSION,
        "provider": index.provider,
        "model": index.model,
        "dims": index.dims,
        "nids": index.nids,
        "mods": index.mods,
        "hashes": index.hashes,
        "skipped": {str(nid): [mod, h] for nid, (mod, h) in index.skipped.items()},
        "updated_at": index.updated_at,
    }
    manifest_path = os.path.join(dir_path, MANIFEST_FILE)
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, manifest_path)


def check_signature(index: CardIndex | None, signature: tuple) -> bool:
    """True when the on-disk index matches the configured signature.

    Takes (provider, model) or (provider, model, dims). Dims is compared
    only when the config actually asks for a width: 0 means "whatever the
    model returns", so it cannot disagree with an index built at 3072.
    A NON-zero request must match exactly — vectors of different widths are
    not comparable, and a mismatch has to force a rebuild rather than
    silently rank against truncated neighbours.

    Tolerating the 2-tuple keeps every existing caller and the transcribed
    copy in test_dialog_logic honest without a flag day.
    """
    if index is None:
        return False
    from . import embeddings

    return embeddings.signature_matches(
        index.provider, index.model, index.dims, signature
    )


def read_manifest(
    dir_path: str,
    version: int = INDEX_VERSION,
    manifest_file: str = MANIFEST_FILE,
) -> dict | None:
    """The manifest as a dict, or None for every way it can fail to be
    one: missing, unreadable, corrupt JSON, valid JSON that is not an
    object (a truncated write can leave ``null``), or the wrong version.

    One preamble for the six manifest readers across card_index,
    pdf_index and retention (the other four still inline it — see the
    board). The not-an-object gate is ``isinstance``, the house idiom
    (drive_store.py), never a caught AttributeError: that would also
    hide an attribute typo inside the caller as "no index yet".
    """
    try:
        with open(os.path.join(dir_path, manifest_file), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(m, dict) or m.get("version") != version:
        return None
    return m


# The failure exit's answer. tests/test_klaus_note.py pins that the success
# exit answers the same key set — that pin, not a spread, is what stops
# the two exits drifting apart the way "dims" once did.
_EMPTY_STATS: dict = {
    "count": 0,
    "skipped": 0,
    "updated_at": 0.0,
    "exists": False,
    "provider": "",
    "model": "",
    "dims": 0,
}


def stats_from_disk(dir_path: str) -> dict:
    """Status-line stats from the manifest alone — never loads the vectors."""
    m = read_manifest(dir_path)
    if m is None:
        return dict(_EMPTY_STATS)
    try:
        return {
            "count": len(m["nids"]),
            "skipped": len(m.get("skipped") or {}),
            "updated_at": float(m.get("updated_at") or 0.0),
            "exists": True,
            "provider": str(m.get("provider") or ""),
            "model": str(m.get("model") or ""),
            "dims": int(m.get("dims") or 0),
        }
    except (KeyError, TypeError, ValueError):  # a dict, but not a manifest
        return dict(_EMPTY_STATS)


# ------------------------------------------------------------------- sync


def plan_sync(
    index: CardIndex | None,
    current_mods: dict[int, int],
    text_fn: Callable[[int], str],
) -> SyncPlan:
    """Diff the collection against the index.

    ``text_fn`` is only called for notes whose mod time moved or that are
    new — the common no-change case never touches note content.
    """
    plan = SyncPlan()
    known_rows = {} if index is None else {nid: i for i, nid in enumerate(index.nids)}
    known_skipped = {} if index is None else index.skipped

    for nid, mod in current_mods.items():
        if nid in known_rows:
            row = known_rows[nid]
            if index.mods[row] == mod:
                plan.unchanged += 1
                continue
            text = text_fn(nid)
            h = text_hash(text)
            if not text:
                plan.new_skipped.append((nid, mod, h))
            elif h == index.hashes[row]:
                plan.mod_only.append((nid, mod))
            else:
                plan.to_embed.append((nid, mod, h, text))
        elif nid in known_skipped:
            old_mod, _old_hash = known_skipped[nid]
            if old_mod == mod:
                plan.unchanged += 1
                continue
            text = text_fn(nid)
            h = text_hash(text)
            if not text:
                plan.new_skipped.append((nid, mod, h))  # still empty; refresh mod
            else:
                plan.to_embed.append((nid, mod, h, text))
        else:
            text = text_fn(nid)
            h = text_hash(text)
            if not text:
                plan.new_skipped.append((nid, mod, h))
            else:
                plan.to_embed.append((nid, mod, h, text))

    current = current_mods.keys()
    for nid in known_rows:
        if nid not in current:
            plan.to_delete.append(nid)
    for nid in known_skipped:
        if nid not in current:
            plan.to_delete.append(nid)
    return plan


def apply_sync(
    index: CardIndex | None,
    plan: SyncPlan,
    embedded: dict[int, array | None],
    signature: tuple[str, str],
) -> CardIndex:
    """Build a new index with the plan applied.

    ``embedded`` may cover only part of ``plan.to_embed`` (partial flush):
    un-embedded notes keep their old row/mod/hash — or stay absent — so the
    next ``plan_sync`` picks them up again. Zero-vector results (None) are
    recorded as skipped.
    """
    old = index if index is not None else empty_index(*signature)
    new = empty_index(*signature)
    from . import embeddings

    _same = embeddings.signature_matches(
        old.provider, old.model, old.dims, signature
    )
    new.dims = old.dims if _same else 0

    deleted = set(plan.to_delete)
    mod_updates = dict(plan.mod_only)
    newly_skipped = {nid: (mod, h) for nid, mod, h in plan.new_skipped}
    embeds = {
        nid: (mod, h, embedded[nid])
        for nid, mod, h, _text in plan.to_embed
        if nid in embedded
    }

    def push_row(nid: int, mod: int, h: str, vec) -> None:
        if new.dims == 0:
            new.dims = len(vec)
        elif len(vec) != new.dims:
            raise ValueError(
                f"Embedding dims changed mid-index: {len(vec)} != {new.dims}"
            )
        new.nids.append(nid)
        new.mods.append(mod)
        new.hashes.append(h)
        new.vectors.extend(vec)

    # carry forward old rows (unless deleted / re-embedded / now skipped)
    if _same:
        for i, nid in enumerate(old.nids):
            if nid in deleted or nid in embeds or nid in newly_skipped:
                continue
            row = old.vectors[i * old.dims : (i + 1) * old.dims]
            push_row(nid, mod_updates.get(nid, old.mods[i]), old.hashes[i], row)
        for nid, entry in old.skipped.items():
            if nid in deleted or nid in embeds or nid in newly_skipped:
                continue
            new.skipped[nid] = entry

    for nid, (mod, h, vec) in embeds.items():
        if vec is None:
            new.skipped[nid] = (mod, h)
        else:
            push_row(nid, mod, h, vec)
    for nid, entry in newly_skipped.items():
        new.skipped[nid] = entry
    return new


# ------------------------------------------------------------------ query


def top_k(
    index: CardIndex,
    query_vecs: list[array],
    k: int,
    allowed: set[int] | None = None,
    min_score: float = 0.0,
) -> list[tuple[int, float]]:
    """Best-scoring nids by cosine similarity (vectors are unit-normalized,
    so similarity is a plain dot product), scored as the **max over all
    query vectors** — a card matching any one PDF chunk well ranks high.

    Returns [(nid, score)] sorted by score descending, at most k entries.
    """
    if not index.nids or not query_vecs or k <= 0:
        return []
    d = index.dims
    mv = memoryview(index.vectors)
    heap: list[tuple[float, int]] = []  # min-heap of (score, nid), size ≤ k
    for i, nid in enumerate(index.nids):
        if allowed is not None and nid not in allowed:
            continue
        row = mv[i * d : (i + 1) * d]
        score = max(_sumprod(row, q) for q in query_vecs)
        if score < min_score:
            continue
        if len(heap) < k:
            heapq.heappush(heap, (score, nid))
        elif score > heap[0][0]:
            heapq.heapreplace(heap, (score, nid))
    return [(nid, score) for score, nid in sorted(heap, reverse=True)]


# ------------------------------------------------- targeted row access
# (K-119) The lecture view needs ONE note's vector per card flip; load()
# would drag the whole vectors.f32 (~90MB at 30k notes x 768 dims) into
# RAM for that. RowMap is the manifest alone; read_vector seeks a
# single row.


@dataclass
class RowMap:
    provider: str
    model: str
    dims: int
    rows: dict[int, int]
    skipped: set[int]
    updated_at: float


def load_row_map(dir_path: str) -> RowMap | None:
    """Manifest-only view of the index; None on missing/corrupt
    (load()'s tolerance, minus the vector read)."""
    m = read_manifest(dir_path)
    if m is None:
        return None
    try:
        nids = [int(n) for n in m["nids"]]
        mods = m["mods"]
        hashes = m["hashes"]
        dims = int(m["dims"])
        if not (len(nids) == len(mods) == len(hashes)):
            return None
        if nids and dims <= 0:
            return None
        return RowMap(
            provider=str(m["provider"]),
            model=str(m["model"]),
            dims=dims,
            rows={nid: i for i, nid in enumerate(nids)},
            skipped={int(k) for k in (m.get("skipped") or {})},
            updated_at=float(m.get("updated_at") or 0.0),
        )
    except (ValueError, KeyError, TypeError):
        return None


def read_vector(dir_path: str, row: int, dims: int) -> array | None:
    """One vector row by seek. The size check is the mid-rebuild guard:
    vectors.f32 is replaced atomically, but a stale RowMap can point
    past the end of a shrunk file."""
    if row < 0 or dims <= 0:
        return None
    vec = array("f")
    path = os.path.join(dir_path, VECTORS_FILE)
    try:
        if os.path.getsize(path) < (row + 1) * dims * vec.itemsize:
            return None
        with open(path, "rb") as f:
            f.seek(row * dims * vec.itemsize)
            vec.fromfile(f, dims)
        return vec
    except (OSError, EOFError, ValueError):
        return None


# ------------------------------------------------------- centering (K-302)
# Every note in a med collection shares one dominant embedding direction
# ("this is medicine"), so raw cosine piles every card of a subject into a
# narrow band near 0.75 and cannot say which LECTURE teaches it. Scoring
# after subtracting the collection's mean vector from both sides cut the
# B12 lecture's wrong-lesson heme matches 65 -> 20 at equal recall, judged
# by AnKing's #Bootcamp lesson tags. Subject-level matching (a whole-subject
# review PDF) is unchanged at equal recall. Harness in scripts/eval/.
MEAN_FILE = "mean.json"
# Below this many notes the mean is mostly the notes themselves (one note:
# the mean IS it, and centering zeroes it), so scores stay raw — and raw
# cosine at the centered default threshold over-matches. Toy collections
# only. ponytail: a flat cut; nothing measured between 3 and 43k notes.
MIN_ROWS_FOR_MEAN = 10
_mean_memo: dict[str, tuple[list, array]] = {}


def mean_vector(dir_path: str) -> array | None:
    """The card index's mean vector, cached beside it in mean.json and keyed
    on vectors.f32's (mtime_ns, size), so a rebuilt index recomputes. None
    when there is no readable index."""
    path = os.path.join(dir_path, VECTORS_FILE)
    try:
        st = os.stat(path)
    except OSError:
        return None
    stamp = [st.st_mtime_ns, st.st_size]
    memo = _mean_memo.get(dir_path)
    if memo is not None and memo[0] == stamp:
        return memo[1]  # the Lecture panel asks on every card flip
    m = read_manifest(dir_path)
    try:
        dims = int(m["dims"]) if m else 0
    except (KeyError, TypeError, ValueError):
        return None
    if dims <= 0 or st.st_size < dims * 4:
        return None
    side = os.path.join(dir_path, MEAN_FILE)
    try:
        with open(side, encoding="utf-8") as f:
            cached = json.load(f)
        if cached["stamp"] == stamp and len(cached["mean"]) == dims:
            _mean_memo[dir_path] = (stamp, array("f", cached["mean"]))
            return _mean_memo[dir_path][1]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    vecs = array("f")
    try:
        with open(path, "rb") as f:
            vecs.fromfile(f, st.st_size // vecs.itemsize)
    except (OSError, EOFError, ValueError):
        return None
    n = len(vecs) // dims
    if n < MIN_ROWS_FOR_MEAN:
        return None
    mean = array("f", (sum(vecs[j : n * dims : dims]) / n for j in range(dims)))
    tmp = side + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"stamp": stamp, "mean": list(mean)}, f)
        os.replace(tmp, side)
    except OSError:
        pass  # uncached is only slower
    _mean_memo[dir_path] = (stamp, mean)
    return mean


class Centered:
    """Cosine after subtracting ``mean`` from both (unit) vectors.

    (a-m).(b-m) = a.b - a.m - b.m + m.m, so each side's (x.m, |x-m|) is
    computed once and a pair still costs the single dot product it did.
    """

    def __init__(self, mean) -> None:
        self.mean = mean
        self.mm = _sumprod(mean, mean)

    def terms(self, vec) -> tuple[float, float] | None:
        """(vec.mean, |vec-mean|), or None for a zero row (never a match)."""
        vv = _sumprod(vec, vec)
        if vv == 0.0:
            return None
        vm = _sumprod(vec, self.mean)
        return vm, math.sqrt(max(vv - 2.0 * vm + self.mm, 0.0))

    def score(self, dot: float, a: tuple[float, float], b: tuple[float, float]) -> float:
        den = a[1] * b[1]
        if den <= 1e-12:
            return -1.0
        return (dot - a[0] - b[0] + self.mm) / den
