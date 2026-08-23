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

    def row_of(self, nid: int) -> int | None:
        try:
            return self.nids.index(nid)
        except ValueError:
            return None


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


def empty_index(provider: str, model: str) -> CardIndex:
    return CardIndex(provider=provider, model=model)


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
    manifest_path = os.path.join(dir_path, MANIFEST_FILE)
    vectors_path = os.path.join(dir_path, VECTORS_FILE)
    try:
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("version") != INDEX_VERSION:
            return None
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
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
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


def check_signature(index: CardIndex | None, signature: tuple[str, str]) -> bool:
    """True when the on-disk index matches the configured (provider, model)."""
    return index is not None and (index.provider, index.model) == signature


def stats_from_disk(dir_path: str) -> dict:
    """Status-line stats from the manifest alone — never loads the vectors."""
    try:
        with open(os.path.join(dir_path, MANIFEST_FILE), encoding="utf-8") as f:
            m = json.load(f)
        if m.get("version") != INDEX_VERSION:
            raise ValueError("version mismatch")
        return {
            "count": len(m["nids"]),
            "skipped": len(m.get("skipped") or {}),
            "updated_at": float(m.get("updated_at") or 0.0),
            "exists": True,
            "provider": str(m.get("provider") or ""),
            "model": str(m.get("model") or ""),
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {
            "count": 0,
            "skipped": 0,
            "updated_at": 0.0,
            "exists": False,
            "provider": "",
            "model": "",
        }


def stats(index: CardIndex | None) -> dict:
    if index is None:
        return {"count": 0, "skipped": 0, "updated_at": 0.0, "exists": False}
    return {
        "count": len(index.nids),
        "skipped": len(index.skipped),
        "updated_at": index.updated_at,
        "exists": True,
    }


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
    new.dims = old.dims if (old.provider, old.model) == signature else 0

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
    if (old.provider, old.model) == signature:
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
