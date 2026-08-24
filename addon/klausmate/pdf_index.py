"""Persistent embedding index over one PDF's text chunks.

Pure stdlib, aqt-free — the sibling of ``card_index.py`` for the PDF side
of the retention feature. Each imported PDF gets its own directory:

Storage layout (``user_files/pdf_index/<safe_name>/``):

- ``vectors.f32``   — unit vectors, row-major packed float32
- ``manifest.json`` — chunk table (page / char offset / length, parallel to
  vector rows), the (provider, model, dims) signature, the source file
  signature, and the resume cursor ``embedded_rows``
- ``matches.json``  — card-match cache, owned by retention.py (deleted with
  the directory, never read here)

Staleness: ``source_sig`` is (mtime, size) of ``contexts/<safe>.json`` —
re-importing a PDF rewrites that file and invalidates the index (the same
idiom as pdf_handler's BM25 cache). A provider/model change invalidates
via the signature, exactly like the card index.

Resume: chunking is deterministic, so a cancelled embedding run persists
``embedded_rows`` < len(chunks); the next run re-chunks, verifies the
source signature and chunk table still match, and continues embedding at
that row. Crash safety mirrors card_index: vectors are written before the
manifest (both tmp + ``os.replace``), and a size mismatch on load means
rebuild.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from array import array
from dataclasses import dataclass, field

from . import pdf_handler

INDEX_VERSION = 1
SUBDIR = "pdf_index"
VECTORS_FILE = "vectors.f32"
MANIFEST_FILE = "manifest.json"


@dataclass
class PdfIndex:
    provider: str
    model: str
    pdf_name: str
    dims: int = 0
    # (mtime, size) of the source contexts/<safe>.json at chunking time
    source_sig: tuple[int, int] = (0, 0)
    # (page_1based, char_start, char_len) per chunk, parallel to vector rows
    chunks: list[tuple[int, int, int]] = field(default_factory=list)
    embedded_rows: int = 0
    vectors: array = field(default_factory=lambda: array("f"))
    updated_at: float = 0.0

    def is_complete(self) -> bool:
        return bool(self.chunks) and self.embedded_rows == len(self.chunks)


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


def stride_sample(items: list, cap: int) -> list:
    """Evenly sample ``cap`` items, keeping document order."""
    if len(items) <= cap:
        return list(items)
    step = len(items) / cap
    return [items[int(i * step)] for i in range(cap)]


def chunk_pages(pages: list[str], cap: int) -> list[tuple[int, int, int, str]]:
    """Chunk a PDF page-by-page → [(page_1based, start, length, text)].

    Per-page chunking loses cross-page-boundary chunks but is what gives
    each chunk a page attribution. Deterministic for a given input, which
    is what makes ``embedded_rows`` a valid resume cursor.
    """
    out: list[tuple[int, int, int, str]] = []
    for page_no, page_text in enumerate(pages, start=1):
        for c in pdf_handler._chunk_text(page_text or "", source=""):
            text = c["text"]
            out.append((page_no, int(c.get("start") or 0), len(text), text))
    return stride_sample(out, cap) if cap > 0 else out


def chunk_text_at(pages: list[str], chunk: tuple[int, int, int]) -> str:
    """Recover a chunk's text from the pages via its (page, start, len) key."""
    page_no, start, length = chunk
    if not (1 <= page_no <= len(pages)):
        return ""
    return (pages[page_no - 1] or "").strip()[start : start + length].strip()


# ------------------------------------------------------------------- disk


def load(dir_path: str) -> PdfIndex | None:
    """Load one PDF's index; None on missing/corrupt/mismatch (= rebuild)."""
    manifest_path = os.path.join(dir_path, MANIFEST_FILE)
    vectors_path = os.path.join(dir_path, VECTORS_FILE)
    try:
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("version") != INDEX_VERSION:
            return None
        chunks = [(int(c[0]), int(c[1]), int(c[2])) for c in m["chunks"]]
        dims = int(m["dims"])
        embedded_rows = int(m.get("embedded_rows") or 0)
        if not (0 <= embedded_rows <= len(chunks)):
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
            chunks=chunks,
            embedded_rows=embedded_rows,
            vectors=vectors,
            updated_at=float(m.get("updated_at") or 0.0),
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError):
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
        "chunks": [list(c) for c in index.chunks],
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
        and (index.provider, index.model) == signature
        and index.is_complete()
    )


def stats_from_disk(dir_path: str) -> dict:
    """Manifest-only stats for the panel — never loads the vectors."""
    try:
        with open(os.path.join(dir_path, MANIFEST_FILE), encoding="utf-8") as f:
            m = json.load(f)
        if m.get("version") != INDEX_VERSION:
            raise ValueError("version mismatch")
        chunks = m["chunks"]
        embedded = int(m.get("embedded_rows") or 0)
        return {
            "exists": True,
            "chunks": len(chunks),
            "embedded": embedded,
            "complete": bool(chunks) and embedded == len(chunks),
            "provider": str(m.get("provider") or ""),
            "model": str(m.get("model") or ""),
            "updated_at": float(m.get("updated_at") or 0.0),
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {
            "exists": False,
            "chunks": 0,
            "embedded": 0,
            "complete": False,
            "provider": "",
            "model": "",
            "updated_at": 0.0,
        }


def delete(user_files_dir: str, name: str) -> None:
    """Remove one PDF's index directory (vectors, manifest, match cache)."""
    try:
        shutil.rmtree(index_dir(user_files_dir, name))
    except OSError:
        pass
