"""One record per (PDF, page): the slide's text and what was said on it.

The page is the seam every API-first capability keys on (spec D2): the
index embeds combined_text per page, the pertinence phase judges a card
against one page, the assistant reads one page, the recorder appends
transcript segments to one page. Records live at
user_files/pages/<pdf_safe>/<digest12>/<page:04d>.json; digest12 is over
the file's path, size and mtime, so a replaced PDF gets a fresh directory
rather than another file's stale transcript.

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
    try:
        st = stat(path)
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        key = path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def record_dir(user_files: str, pdf_safe: str, path: str) -> str:
    return os.path.join(user_files, SUBDIR, pdf_safe, digest12(path))


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


def ensure_records(user_files: str, pdf_safe: str, path: str, pages: list[str]) -> int:
    """Write slide_text for every page; existing segments survive. Idempotent."""
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
