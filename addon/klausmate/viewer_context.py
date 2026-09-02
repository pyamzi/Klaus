"""Which PDF viewer the user is looking at, and what it shows.

Every PdfSidebar (the Library's, Browse's editor pane, the review-time
Lecture dock) reports into this registry; the assistant dock follows
``current()`` — the LAST ACTIVATED viewer that still holds a document.
Pure dict state, no Qt; callbacks run synchronously on the caller's thread
(the main thread in practice) and a raising callback is logged, never raised.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

@dataclass
class ViewState:
    viewer_id: int
    pdf_safe: str
    display: str
    path: str
    page_index: int = 0
    page_count: int = 0
    selection: str = ""

_views: dict[int, ViewState] = {}
_order: list[int] = []          # activation order, most recent last
_subs: list[Callable] = []


def reset() -> None:
    _views.clear(); _order.clear(); _subs.clear()


def _notify() -> None:
    cur = current()
    for cb in list(_subs):
        try:
            cb(cur)
        except Exception as exc:
            print(f"[klausmate] viewer_context subscriber: {exc}")


def report_document(viewer_id: int, pdf_safe: str, display: str, path: str, page_count: int) -> None:
    if pdf_safe:
        _views[viewer_id] = ViewState(viewer_id, pdf_safe, display or pdf_safe, path, 0, int(page_count or 0), "")
    else:
        _views.pop(viewer_id, None)
    _notify()


def report_page(viewer_id: int, page_index: int) -> None:
    v = _views.get(viewer_id)
    if v is None:
        return
    _views[viewer_id] = replace(v, page_index=max(0, int(page_index)))
    _notify()


def report_page_count(viewer_id: int, page_count: int) -> None:
    """Narrow catch-up for a page count learned AFTER report_document.

    pdf.js reports a provisional count from the text layer at document-
    report time and refines it once the real document object parses
    (klausmate/pdf_viewer.py's ``_on_pdfjs_count``). Unlike calling
    report_document again, this touches ONLY page_count: it does not
    reset page_index/selection to 0/"" and does not activate — a late
    count is a data correction, not new activity, and the caller must
    already have confirmed (by identity, not just presence) that this
    viewer_id's CURRENT document is still the one the count belongs to.
    A no-op, like report_page, when the viewer isn't registered."""
    v = _views.get(viewer_id)
    if v is None:
        return
    _views[viewer_id] = replace(v, page_count=max(0, int(page_count)))
    _notify()


def report_selection(viewer_id: int, text: str) -> None:
    v = _views.get(viewer_id)
    if v is None:
        return
    _views[viewer_id] = replace(v, selection=str(text or ""))
    _notify()


def activate(viewer_id: int) -> None:
    if viewer_id in _order:
        _order.remove(viewer_id)
    _order.append(viewer_id)
    _notify()


def forget(viewer_id: int) -> None:
    _views.pop(viewer_id, None)
    if viewer_id in _order:
        _order.remove(viewer_id)
    _notify()


def current() -> ViewState | None:
    for vid in reversed(_order):
        v = _views.get(vid)
        if v is not None and v.pdf_safe:
            return v
    return None


def subscribe(cb: Callable) -> Callable[[], None]:
    _subs.append(cb)
    def unsub() -> None:
        if cb in _subs:
            _subs.remove(cb)
    return unsub
