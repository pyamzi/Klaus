"""Persistent embedding index over one PDF's pages — one vector per page.

Pure stdlib, aqt-free — the sibling of ``card_index.py`` for the PDF side
of the retention feature. Each imported PDF gets its own directory:

Storage layout (``user_files/pdf_index/<safe_name>/``):

- ``vectors.f32``   — unit vectors, row-major packed float32, one row per
  page
- ``manifest.json`` — page table ((page_1based, text_hash) per row,
  parallel to vector rows), the (provider, model, dims) signature, the
  source file signature, and the resume cursor ``embedded_rows``
- ``matches.json``  — card-match cache, owned by retention.py (deleted with
  the directory, never read here)

Staleness: ``source_sig`` is (mtime, size) of ``contexts/<safe>.json`` —
re-importing a PDF rewrites that file and invalidates the index (the same
idiom as pdf_handler's BM25 cache). A provider/model change invalidates
via the signature, exactly like the card index. Each page's own text hash
(page_store.text_hash) is the finer-grained key retention.py's rebuild
uses to reuse a page's vector unchanged instead of re-embedding it.

Resume: the page table (page_store.page_texts) is deterministic and in
page order, so a cancelled embedding run persists ``embedded_rows`` <
len(pages); the next run re-derives the table, verifies the source
signature still matches, and continues embedding at that row. Crash
safety mirrors card_index: vectors are written before the manifest (both
tmp + ``os.replace``), and a size mismatch on load means rebuild.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from array import array
from dataclasses import dataclass, field

from . import card_index, embeddings, pdf_handler

INDEX_VERSION = 2
SUBDIR = "pdf_index"
VECTORS_FILE = "vectors.f32"
MANIFEST_FILE = "manifest.json"


@dataclass
class PdfIndex:
    provider: str
    model: str
    pdf_name: str
    dims: int = 0
    # (mtime, size) of the source contexts/<safe>.json at page-table time
    source_sig: tuple[int, int] = (0, 0)
    # (page_1based, text_hash) per page, parallel to vector rows
    pages: list[tuple[int, str]] = field(default_factory=list)
    embedded_rows: int = 0
    vectors: array = field(default_factory=lambda: array("f"))
    updated_at: float = 0.0

    def is_complete(self) -> bool:
        return bool(self.pages) and self.embedded_rows == len(self.pages)


def index_dir(user_files_dir: str, name: str) -> str:
    safe = pdf_handler._safe_basename(name)
    return os.path.join(user_files_dir, SUBDIR, safe)


def source_signature(user_files_dir: str, name: str) -> tuple[int, int] | None:
    """(mtime, size) of the PDF's extracted-text file; None when missing."""
    safe = pdf_handler._safe_basename(name)
    ctx_dir = os.path.join(user_files_dir, "contexts")
    for fname in (safe + ".json", safe + ".txt"):
        path = os.path.join(ctx_dir, fname)
        try:
            st = os.stat(path)
            return int(st.st_mtime), int(st.st_size)
        except OSError:
            continue
    return None


# ------------------------------------------------------------------- disk


def load(dir_path: str) -> PdfIndex | None:
    """Load one PDF's index; None on missing/corrupt/mismatch (= rebuild)."""
    vectors_path = os.path.join(dir_path, VECTORS_FILE)
    m = card_index.read_manifest(dir_path, INDEX_VERSION, MANIFEST_FILE)
    if m is None:
        return None
    try:
        pages = [(int(p[0]), str(p[1])) for p in m["pages"]]
        dims = int(m["dims"])
        embedded_rows = int(m.get("embedded_rows") or 0)
        if not (0 <= embedded_rows <= len(pages)):
            return None
        vectors = array("f")
        if embedded_rows:
            if dims <= 0:
                return None
            expected = embedded_rows * dims * vectors.itemsize
            if os.path.getsize(vectors_path) != expected:
                return None
            with open(vectors_path, "rb") as f:
                vectors.fromfile(f, embedded_rows * dims)
        sig = m.get("source_sig") or [0, 0]
        return PdfIndex(
            provider=str(m["provider"]),
            model=str(m["model"]),
            pdf_name=str(m.get("pdf_name") or ""),
            dims=dims,
            source_sig=(int(sig[0]), int(sig[1])),
            pages=pages,
            embedded_rows=embedded_rows,
            vectors=vectors,
            updated_at=float(m.get("updated_at") or 0.0),
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


def save(index: PdfIndex, dir_path: str) -> None:
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
        "pdf_name": index.pdf_name,
        "dims": index.dims,
        "source_sig": list(index.source_sig),
        "pages": [list(p) for p in index.pages],
        "embedded_rows": index.embedded_rows,
        "updated_at": index.updated_at,
    }
    manifest_path = os.path.join(dir_path, MANIFEST_FILE)
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, manifest_path)


def is_fresh(
    index: PdfIndex | None,
    source_sig: tuple[int, int] | None,
    signature: tuple[str, str],
) -> bool:
    """True when the index is complete and matches both the source file and
    the configured (provider, model)."""
    return (
        index is not None
        and source_sig is not None
        and index.source_sig == source_sig
        and embeddings.signature_matches(
            index.provider, index.model, index.dims, signature
        )
        and index.is_complete()
    )


# The failure exit's answer; test_klausmate pins that the success exit
# answers the same key set (card_index.stats_from_disk shipped that drift).
_EMPTY_STATS: dict = {
    "exists": False,
    "pages": 0,
    "embedded": 0,
    "complete": False,
    "provider": "",
    "model": "",
    "dims": 0,
    "updated_at": 0.0,
}


def stats_from_disk(dir_path: str) -> dict:
    """Manifest-only stats for the panel — never loads the vectors."""
    m = card_index.read_manifest(dir_path, INDEX_VERSION, MANIFEST_FILE)
    if m is None:
        return dict(_EMPTY_STATS)
    try:
        pages = m["pages"]
        embedded = int(m.get("embedded_rows") or 0)
        return {
            "exists": True,
            "pages": len(pages),
            "embedded": embedded,
            "complete": bool(pages) and embedded == len(pages),
            "provider": str(m.get("provider") or ""),
            "model": str(m.get("model") or ""),
            "dims": int(m.get("dims") or 0),
            "updated_at": float(m.get("updated_at") or 0.0),
        }
    except (KeyError, TypeError, ValueError):  # a dict, but not a manifest
        return dict(_EMPTY_STATS)


def delete(user_files_dir: str, name: str) -> None:
    """Remove one PDF's index directory (vectors, manifest, match cache)."""
    try:
        shutil.rmtree(index_dir(user_files_dir, name))
    except OSError:
        pass


try:
    from math import sumprod as _sumprod
except ImportError:  # pre-3.12 fallback (Anki bundles 3.13)
    def _sumprod(a, b):  # type: ignore[misc]
        return sum(x * y for x, y in zip(a, b))


def best_page(index: PdfIndex, vec) -> tuple[int, float]:
    """Argmax-dot row for one unit query vector; (page_1based, score), or
    (-1, 0.0) when the index is empty or the dims disagree. A zero row
    scores 0.0 and only wins when every row does."""
    dims, rows = index.dims, index.embedded_rows
    if rows <= 0 or dims <= 0:
        return (-1, 0.0)
    try:
        if len(vec) != dims:
            return (-1, 0.0)
    except TypeError:
        return (-1, 0.0)
    mv = memoryview(index.vectors)
    best_i, best = 0, float("-inf")
    for i in range(rows):
        s = _sumprod(mv[i * dims:(i + 1) * dims], vec)
        if s > best:
            best_i, best = i, s
    return (index.pages[best_i][0], float(best))
