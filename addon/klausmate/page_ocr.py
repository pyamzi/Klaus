"""The page in view as text and image: render, OCR through Ollama, cache.

Pouya, 2026-09-01: "I want to use GLM-OCR or something similar to get the
PDF image and text." The page renders through QPdfDocument (Anki bundles
QtPdf whichever viewer renderer is on), the PNG goes to a vision-OCR model
served by Ollama, and the markdown that comes back is cached beside the
PNG keyed by the PDF's digest and page, so a page is OCR'd once. Without an
OCR model the turn carries the PDF's own text layer and says so; the image
still goes. OCR never blocks a send: the scheduler runs it on a worker after
a 400 ms debounce and prefetches the neighbours when idle.

aqt-free above the divider; ``render_page_png`` is the one QtPdf function.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

LONG_EDGE = 1400
OCR_TIMEOUT_S = 60.0
DEBOUNCE_MS = 400
PREFETCH = (1, -1)
OCR_PROMPT = ("Transcribe this lecture slide faithfully as Markdown: keep headings, bullets, tables and "
              "equations (LaTeX); describe each figure in one line in brackets; no commentary.")


@dataclass
class PageContext:
    display: str
    page_index: int
    page_count: int
    text: str
    text_source: str        # "ocr" | "text-layer" | "none"
    png: bytes | None
    selection: str


def digest12(path: str, stat=os.stat) -> str:
    try:
        st = stat(path)
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        key = path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def cache_dir(user_files: str, pdf_safe: str, path: str) -> str:
    return os.path.join(user_files, "ocr", pdf_safe, digest12(path))


def _paths(user_files, pdf_safe, path, page_index):
    d = cache_dir(user_files, pdf_safe, path)
    return d, os.path.join(d, f"{int(page_index):04d}.md"), os.path.join(d, f"{int(page_index):04d}.png")


def cached_text(user_files: str, pdf_safe: str, path: str, page_index: int) -> str | None:
    _, md, _ = _paths(user_files, pdf_safe, path, page_index)
    try:
        with open(md, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def cached_png(user_files: str, pdf_safe: str, path: str, page_index: int) -> bytes | None:
    _, _, png = _paths(user_files, pdf_safe, path, page_index)
    try:
        with open(png, "rb") as f:
            return f.read()
    except Exception:
        return None


def _atomic(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def store(user_files: str, pdf_safe: str, path: str, page_index: int, text: str | None, png: bytes | None) -> None:
    d, md, pn = _paths(user_files, pdf_safe, path, page_index)
    os.makedirs(d, exist_ok=True)
    if text is not None:
        _atomic(md, text.encode("utf-8"))
    if png is not None:
        _atomic(pn, png)


def ocr_page(client: Any, model: str, png: bytes, timeout: float = OCR_TIMEOUT_S) -> str:
    b64 = base64.b64encode(png).decode("ascii")
    return str(client.generate(model, OCR_PROMPT, images=[b64], timeout=timeout) or "").strip()


def text_layer(user_files: str, pdf_safe: str, page_index: int, load_pages: Callable | None = None) -> str:
    if load_pages is None:
        from . import pdf_handler
        load_pages = pdf_handler.load_pages
    try:
        pages = load_pages(user_files, pdf_safe) or []
        return str(pages[page_index]) if 0 <= page_index < len(pages) else ""
    except Exception:
        return ""


def context_for(view: Any, user_files: str, render: Callable | None = None, load_pages: Callable | None = None) -> PageContext:
    if view is None or not getattr(view, "pdf_safe", ""):
        return PageContext("", 0, 0, "", "none", None, "")
    render = render or render_page_png
    text = cached_text(user_files, view.pdf_safe, view.path, view.page_index)
    source = "ocr" if text else "text-layer"
    if not text:
        text = text_layer(user_files, view.pdf_safe, view.page_index, load_pages)
        if not text:
            source = "none"
    png = cached_png(user_files, view.pdf_safe, view.path, view.page_index)
    if png is None:
        try:
            png = render(view.path, view.page_index, long_edge=LONG_EDGE)
            if png:
                store(user_files, view.pdf_safe, view.path, view.page_index, None, png)
        except Exception as exc:
            print(f"[klausmate] page render failed: {exc}")
            png = None
    return PageContext(view.display, view.page_index, view.page_count, text or "", source, png, getattr(view, "selection", "") or "")


class OcrScheduler:
    """Debounce 400 ms after the last view change, OCR the current page on a
    worker, then page+1 and page-1. Never raises; never blocks the caller."""

    def __init__(self, user_files: str, cfg_getter: Callable[[], dict], client_factory: Callable[[], Any],
                 render: Callable | None = None, clock: Callable[[], float] = time.monotonic,
                 start_thread: Callable | None = None, load_pages: Callable | None = None) -> None:
        self._uf, self._cfg, self._client = user_files, cfg_getter, client_factory
        self._render = render or render_page_png
        self._clock = clock
        self._start = start_thread or (lambda fn: threading.Thread(target=fn, daemon=True, name="klaus-ocr").start())
        self._load_pages = load_pages
        self._view: Any = None
        self._due: float | None = None
        self._busy = False
        self._timer: Any = None

    def on_view(self, view: Any) -> None:
        self._view = view
        if view is None or not getattr(view, "pdf_safe", ""):
            self._due = None
            return
        self._due = self._clock() + DEBOUNCE_MS / 1000.0
        self._arm_timer()

    def _arm_timer(self) -> None:
        """Qt-timer hook installed by the dock (aqt glue); tests call tick()."""
        if self._timer is not None:
            try:
                self._timer()
            except Exception:
                pass

    def tick(self) -> None:
        if self._due is None or self._clock() < self._due or self._busy:
            return
        cfg = self._cfg() or {}
        if not cfg.get("ocr_enabled", True) or not str(cfg.get("ocr_model") or "").strip():
            self._due = None
            return
        view = self._view
        self._due = None
        self._busy = True
        self._start(lambda: self._run(view, str(cfg.get("ocr_model"))))

    def _run(self, view: Any, model: str) -> None:
        try:
            client = self._client()
            for delta in (0, *PREFETCH):
                idx = view.page_index + delta
                if idx < 0 or (view.page_count and idx >= view.page_count):
                    continue
                if cached_text(self._uf, view.pdf_safe, view.path, idx):
                    continue
                png = cached_png(self._uf, view.pdf_safe, view.path, idx)
                if png is None:
                    png = self._render(view.path, idx, long_edge=LONG_EDGE)
                    if png:
                        store(self._uf, view.pdf_safe, view.path, idx, None, png)
                if not png:
                    continue
                try:
                    text = ocr_page(client, model, png)
                except Exception as exc:
                    print(f"[klausmate] ocr page {idx + 1} of {view.pdf_safe}: {exc}")
                    return
                if text:
                    store(self._uf, view.pdf_safe, view.path, idx, text, None)
        except Exception as exc:
            print(f"[klausmate] ocr worker: {exc}")
        finally:
            self._busy = False


# ---- QtPdf glue --------------------------------------------------------------------

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
