"""One record per (PDF, page): the slide's text and what was said on it.

The page is the seam every API-first capability keys on (spec D2): the
index embeds combined_text per page, the pertinence phase judges a card
against one page, the assistant reads one page, the recorder appends
transcript segments to one page. Records live at
user_files/pages/<pdf_safe>/<digest>/<page:04d>.json. <digest> is resolved
through a pointer file, pages/<pdf_safe>/current: normally text_digest
(pages), a hash of the document's own TEXT, so a bake
(pdf_handler.bake_annotations rewrites the file with os.replace) or a
move inside the Library — neither changes what the page says — cannot
orphan the records; a legacy digest12(path) directory found with no
pointer yet (a profile indexed before this scheme existed) is adopted in
place rather than abandoned. Only genuinely different text — a different
PDF re-imported under the same safe name — repoints at a fresh directory
(see ensure_records); the old one is left on disk until delete_context
removes it.

aqt-free above the divider; render_page_png (QtPdf) sits below it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable

VERSION = 1
SUBDIR = "pages"
LONG_EDGE = 1400

_subscribers: list[Callable[[str, int], None]] = []


def digest12(path: str, stat=os.stat) -> str:
    """Legacy identity: path+size+mtime. A bake or a move changes all
    three, which is exactly why record_dir no longer resolves on this —
    kept only to recognize and adopt a directory seeded before the
    pointer scheme existed."""
    try:
        st = stat(path)
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        key = path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def text_digest(pages: list[str]) -> str:
    """The document's identity: a hash of what the pages actually SAY,
    not the file carrying them — stable across a bake's os.replace or a
    move, since neither touches the text layer. Whitespace is collapsed
    per page before hashing so re-extracting the same text with
    different line-wrapping still resolves to the same directory."""
    normalized = "\x1f".join(" ".join(str(p or "").split()) for p in pages)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _pointer_path(user_files: str, pdf_safe: str) -> str:
    return os.path.join(user_files, SUBDIR, pdf_safe, "current")


def _read_pointer(user_files: str, pdf_safe: str) -> str | None:
    try:
        with open(_pointer_path(user_files, pdf_safe), encoding="utf-8") as f:
            digest = f.read().strip()
        return digest or None
    except OSError:
        return None


def _write_pointer(user_files: str, pdf_safe: str, digest: str) -> None:
    p = _pointer_path(user_files, pdf_safe)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(digest)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def record_dir(user_files: str, pdf_safe: str, path: str) -> str:
    """Where this PDF's page records live. The pointer file decides it
    when one exists; otherwise an on-disk legacy (path-digest) directory
    is adopted — written into the pointer so it doesn't have to be
    rediscovered next time — and failing that this is a never-seeded
    PDF, so the (not yet existing) legacy path is returned exactly as
    before."""
    base = os.path.join(user_files, SUBDIR, pdf_safe)
    pointer = _read_pointer(user_files, pdf_safe)
    if pointer:
        return os.path.join(base, pointer)
    legacy = digest12(path)
    legacy_dir = os.path.join(base, legacy)
    if os.path.isdir(legacy_dir):
        try:
            _write_pointer(user_files, pdf_safe, legacy)
        except OSError as exc:
            print(f"[klausmate] page pointer adopt failed for {pdf_safe}: {exc}")
    return legacy_dir


def record_path(user_files: str, pdf_safe: str, path: str, page_index: int) -> str:
    return os.path.join(record_dir(user_files, pdf_safe, path), f"{int(page_index):04d}.json")


def _empty() -> dict:
    return {"version": VERSION, "slide_text": "", "segments": [], "updated_at": 0.0}


def load_record(user_files: str, pdf_safe: str, path: str, page_index: int) -> dict:
    p = record_path(user_files, pdf_safe, path, page_index)
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        if not isinstance(rec, dict) or not isinstance(rec.get("segments"), list):
            raise ValueError("not a page record")
        rec.setdefault("slide_text", "")
        rec.setdefault("version", VERSION)
        return rec
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as exc:
        print(f"[klausmate] page record unreadable, treating as empty: {p}: {exc}")
        return _empty()


def _atomic_json(p: str, rec: dict) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _same_text(rec_dir: str, pages: list[str]) -> bool:
    """True when the records already in *rec_dir* say what *pages* say
    (every page's slide_text, whitespace-collapsed) — the same document
    under another directory name."""
    for i, text in enumerate(pages):
        try:
            with open(os.path.join(rec_dir, f"{int(i):04d}.json"), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            return False
        if " ".join(str((rec or {}).get("slide_text") or "").split()) != " ".join(str(text or "").split()):
            return False
    return True


def ensure_records(user_files: str, pdf_safe: str, path: str, pages: list[str]) -> int:
    """Write slide_text for every page; existing segments survive. Idempotent.

    Settles the identity pointer before seeding: adopt an on-disk legacy
    (path-digest) directory the first time one is found — a profile that
    already indexed under Plan 1 keeps its records — otherwise key on
    text_digest(pages). A pointer that already names a DIFFERENT text
    digest means the PDF itself was replaced (a different document
    re-imported under the same safe name): records move to a fresh
    directory, and the old one is left on disk until delete_context
    removes it.
    """
    td = text_digest(pages)
    base = os.path.join(user_files, SUBDIR, pdf_safe)
    pointer = _read_pointer(user_files, pdf_safe)
    if pointer is None:
        legacy = digest12(path)
        pointer = legacy if os.path.isdir(os.path.join(base, legacy)) else td
        _write_pointer(user_files, pdf_safe, pointer)
    if pointer != td:
        # The pointer names a directory that is not this text's own. Two
        # cases, told apart by CONTENT, never by name: a legacy
        # (path-digest) directory holding this same document — a record's
        # segments may already live there (a transcript taken before the
        # first index run) — is renamed onto the text digest and kept; a
        # directory whose slide text differs is a replaced document and is
        # left behind for delete_context.
        old_dir = os.path.join(base, pointer)
        if os.path.isdir(old_dir) and _same_text(old_dir, pages):
            try:
                os.replace(old_dir, os.path.join(base, td))
            except OSError as exc:
                print(f"[klausmate] page records migrate failed for {pdf_safe}: {exc}")
        _write_pointer(user_files, pdf_safe, td)
    n = 0
    for i, text in enumerate(pages):
        rec = load_record(user_files, pdf_safe, path, i)
        new_text = str(text or "")
        if rec["slide_text"] == new_text and os.path.exists(record_path(user_files, pdf_safe, path, i)):
            continue
        rec["slide_text"] = new_text
        rec["updated_at"] = time.time()
        _atomic_json(record_path(user_files, pdf_safe, path, i), rec)
        n += 1
    return n


def append_segment(user_files: str, pdf_safe: str, path: str, page_index: int,
                   t0: float, t1: float, text: str) -> dict:
    rec = load_record(user_files, pdf_safe, path, page_index)
    rec["segments"].append({"t0": float(t0), "t1": float(t1), "text": str(text)})
    rec["segments"].sort(key=lambda s: (float(s.get("t0", 0.0)), float(s.get("t1", 0.0))))
    rec["updated_at"] = time.time()
    _atomic_json(record_path(user_files, pdf_safe, path, page_index), rec)
    _notify(pdf_safe, page_index)
    return rec


def combined_text(rec: dict) -> str:
    slide = str(rec.get("slide_text") or "").strip()
    said = "\n".join(str(s.get("text") or "").strip() for s in rec.get("segments") or [] if str(s.get("text") or "").strip())
    if slide and said:
        return f"{slide}\n\n{said}"
    return slide or said


def text_hash(rec: dict) -> str:
    return hashlib.blake2b(combined_text(rec).encode("utf-8"), digest_size=8).hexdigest()


def page_texts(user_files: str, pdf_safe: str, path: str, page_count: int) -> list[tuple[int, str, str]]:
    out = []
    for i in range(int(page_count)):
        rec = load_record(user_files, pdf_safe, path, i)
        out.append((i + 1, text_hash(rec), combined_text(rec)))
    return out


def subscribe(cb: Callable[[str, int], None]) -> Callable[[], None]:
    _subscribers.append(cb)

    def unsubscribe() -> None:
        try:
            _subscribers.remove(cb)
        except ValueError:
            pass
    return unsubscribe


def _notify(pdf_safe: str, page_index: int) -> None:
    for cb in list(_subscribers):
        try:
            cb(pdf_safe, page_index)
        except Exception as exc:
            print(f"[klausmate] page_store subscriber failed: {exc}")


# ---- QtPdf glue -------------------------------------------------------------

def render_page_png(path: str, page_index: int, long_edge: int = LONG_EDGE) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice, QSize
    from PyQt6.QtPdf import QPdfDocument
    doc = QPdfDocument(None)
    doc.load(path)
    if doc.status() != QPdfDocument.Status.Ready or page_index < 0 or page_index >= doc.pageCount():
        raise RuntimeError(f"cannot render page {page_index + 1} of {path}")
    pts = doc.pagePointSize(page_index)
    w, h = max(1.0, pts.width()), max(1.0, pts.height())
    scale = float(long_edge) / max(w, h)
    img = doc.render(page_index, QSize(int(round(w * scale)), int(round(h * scale))))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())
