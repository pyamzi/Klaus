"""Klaus PDF sidebar — single native PDF viewer and copy-page-to-clipboard."""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
import weakref

from collections import OrderedDict
from typing import Any, Callable, Optional

from aqt.editor import Editor
from aqt.utils import tooltip
from aqt.qt import (
    QAbstractItemView,
    QApplication,
    QEvent,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QKeySequence,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QScrollArea,
    QShortcut,
    QSize,
    QSizePolicy,
    QSplitter,
    Qt,
    QTimer,
    QToolButton,
    QUrl,
    QVBoxLayout,
    QWidget,
)

# Guarded separately: QDrag is only needed for dragging marquee images
# out of the viewer (N2) — the viewer must work without it.
try:
    from aqt.qt import QDrag
except Exception:  # pragma: no cover
    QDrag = None  # type: ignore

try:
    from PyQt6.QtCore import QSizeF
    from PyQt6.QtGui import (
        QColor,
        QGuiApplication,
        QIcon,
        QImage,
        QPainter,
        QPalette,
        QPen,
        QPixmap,
    )
    from PyQt6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions
except Exception:  # pragma: no cover
    QSizeF = None  # type: ignore
    QColor = None  # type: ignore
    QGuiApplication = None  # type: ignore
    QIcon = None  # type: ignore
    QImage = None  # type: ignore
    QPainter = None  # type: ignore
    QPalette = None  # type: ignore
    QPen = None  # type: ignore
    QPixmap = None  # type: ignore
    QPdfDocument = None  # type: ignore
    QPdfDocumentRenderOptions = None  # type: ignore
    QT_PDF_AVAILABLE = False
else:
    QT_PDF_AVAILABLE = True

# Guarded separately from the imports above: if only QPdfSearchModel is
# missing, the viewer must still work — just without the Cmd+F find bar.
try:
    from PyQt6.QtPdf import QPdfSearchModel
except Exception:  # pragma: no cover
    QPdfSearchModel = None  # type: ignore

try:
    from PyQt6.QtPdfWidgets import QPdfView
except Exception:  # pragma: no cover
    QPdfView = None  # type: ignore
    QT_PDF_WIDGETS_AVAILABLE = False
else:
    QT_PDF_WIDGETS_AVAILABLE = True

PDF_VIEWER_AVAILABLE = QT_PDF_AVAILABLE and QT_PDF_WIDGETS_AVAILABLE


def _page_size_points(doc: QPdfDocument, page: int) -> QSizeF:
    try:
        pt = doc.pagePointSize(page)
        if pt.isValid():
            return pt
    except Exception:
        pass
    try:
        sz = doc.pageSize(page)
        return QSizeF(float(sz.width()), float(sz.height()))
    except Exception:
        pass
    return QSizeF(612.0, 792.0)


def _page_size(doc: QPdfDocument, page: int) -> QSize:
    pt = _page_size_points(doc, page)
    return QSize(max(1, int(pt.width())), max(1, int(pt.height())))


def _render_page_pixmap(
    doc: QPdfDocument,
    page: int,
    width_px: int,
) -> QPixmap | None:
    if not QT_PDF_AVAILABLE or QPixmap is None:
        return None
    size = _page_size(doc, page)
    if size.width() <= 0:
        return None
    scale = width_px / size.width()
    render_h = max(1, int(size.height() * scale))
    render_size = QSize(width_px, render_h)
    try:
        opts = QPdfDocumentRenderOptions()
        img = doc.render(page, render_size, opts)
        if img is None or img.isNull():
            return None
        # QPdfDocument renders onto a transparent background and
        # QPdfDocumentRenderOptions has no background option, so pasted
        # page images came out see-through on dark themes. Composite the
        # render over opaque white (Format_RGB32 is inherently opaque);
        # on any failure fall back to the original image rather than
        # losing the copy.
        try:
            if QImage is not None and QPainter is not None:
                opaque = QImage(img.size(), QImage.Format.Format_RGB32)
                opaque.fill(Qt.GlobalColor.white)
                painter = QPainter(opaque)
                painter.drawImage(0, 0, img)
                painter.end()
                img = opaque
        except Exception:
            pass
        return QPixmap.fromImage(img)
    except Exception:
        return None


def copy_pdf_page_image_to_clipboard(
    doc: QPdfDocument | None,
    page: int,
) -> bool:
    """Render one page and put it on the system clipboard as an image."""
    if not QT_PDF_AVAILABLE or doc is None or QPixmap is None:
        tooltip("Klaus: PDF viewer unavailable")
        return False
    size = _page_size(doc, page)
    dpi_scale = 150.0 / 72.0
    width_px = max(400, int(size.width() * dpi_scale))
    pixmap = _render_page_pixmap(doc, page, width_px)
    if pixmap is None or pixmap.isNull():
        tooltip("Klaus: could not render page image")
        return False
    cb = QApplication.clipboard()
    if cb is None:
        return False
    try:
        from PyQt6.QtCore import QMimeData

        mime = QMimeData()
        mime.setImageData(pixmap.toImage())
        cb.setMimeData(mime)
    except Exception:
        cb.setPixmap(pixmap)
    tooltip(f"Klaus: page {page + 1} copied — paste with Cmd+V")
    return True


def _event_pos(event, target: QWidget | None = None) -> QPoint:
    if target is not None:
        try:
            if hasattr(event, "globalPosition"):
                g = event.globalPosition().toPoint()
            else:
                g = event.globalPos()
            return target.mapFromGlobal(g)
        except Exception:
            pass
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


def _selection_bounds(sel: Any) -> list[Any]:
    """Return the selection's bounding rectangles (QRectF) on the page.

    In Qt 6.x, ``QPdfSelection.bounds()`` returns ``QList<QPolygonF>`` —
    polygons, not rectangles. Earlier versions of this addon handed those
    polygons straight to ``_point_rect_to_viewport``, which called ``.x()``
    / ``.width()`` on them and silently failed in a try/except — so no
    selection highlights ever appeared. We now normalise everything to
    rectangles via each polygon's bounding box.
    """
    if sel is None or not sel.isValid():
        return []
    try:
        bounds = sel.bounds()
    except Exception:
        bounds = None
    if bounds:
        out: list[Any] = []
        for item in bounds:
            try:
                if hasattr(item, "boundingRect"):
                    out.append(item.boundingRect())
                else:
                    out.append(item)
            except Exception:
                continue
        if out:
            return out
    try:
        if hasattr(sel, "boundingRectangles"):
            rects = sel.boundingRectangles()
            if rects:
                return list(rects)
    except Exception:
        pass
    try:
        r = sel.boundingRectangle()
        if r is not None:
            return [r]
    except Exception:
        pass
    return []


def _probe_selection_at(
    doc: QPdfDocument, page: int, pt: QPointF, fast: bool = False
) -> tuple[QPointF | None, Any, int | None]:
    """Find a tiny valid selection near ``pt`` via expanding x/y probes.

    QPdfDocument.getSelection() silently returns an INVALID selection
    whenever an endpoint is farther than ~7pt from a glyph (pdfium's
    CharacterHitTolerance) — so a raw point in a margin or between
    lines resolves to nothing. It is ALSO invalid when both endpoints
    hit the same character, which makes the symmetric spans
    (0.5/1/2/4/6pt) fail inside WIDE glyphs (big-font titles): the
    whole ±6pt span fits in one glyph, while pushing both ends out of
    it exceeds the tolerance. Directional spans anchored AT ``pt``
    rescue that case — one endpoint stays on the glyph, the other
    reaches the neighbouring character. Returns ``(adjusted point,
    selection, char index under pt)`` or ``(None, None, None)``.

    ``fast=True`` trims the cascade (~1/5 of the probes) for per-
    mouse-move callers; one-time callers (press anchors, word select)
    keep the exhaustive sweep.
    """
    dys = (0.0, 2.0, -2.0) if fast else (0.0, 2.0, -2.0, 4.0, -4.0, 8.0, -8.0)
    sym_dxs = (1.0, 4.0) if fast else (0.5, 1.0, 2.0, 4.0, 6.0)
    rescue_dxs = (8.0, 16.0) if fast else (8.0, 12.0, 16.0, 24.0, 32.0)
    for dy in dys:
        y = pt.y() + dy
        for dx in sym_dxs:
            try:
                probe = doc.getSelection(
                    page,
                    QPointF(pt.x() - dx, y),
                    QPointF(pt.x() + dx, y),
                )
            except Exception:
                probe = None
            if probe is not None and probe.isValid():
                try:
                    idx = int(probe.startIndex())
                except Exception:
                    idx = None
                return QPointF(pt.x(), y), probe, idx
        # Wide-glyph rescue: forward span (char under pt is FIRST) then
        # backward span (char under pt is LAST — take endIndex - 1).
        for dx in rescue_dxs:
            try:
                probe = doc.getSelection(
                    page, QPointF(pt.x(), y), QPointF(pt.x() + dx, y)
                )
            except Exception:
                probe = None
            if probe is not None and probe.isValid():
                try:
                    idx = int(probe.startIndex())
                except Exception:
                    idx = None
                return QPointF(pt.x(), y), probe, idx
            try:
                probe = doc.getSelection(
                    page, QPointF(pt.x() - dx, y), QPointF(pt.x(), y)
                )
            except Exception:
                probe = None
            if probe is not None and probe.isValid():
                try:
                    idx = max(
                        int(probe.startIndex()), int(probe.endIndex()) - 1
                    )
                except Exception:
                    idx = None
                return QPointF(pt.x(), y), probe, idx
    return None, None, None


def _char_index_at(doc: QPdfDocument, page: int, pt: QPointF) -> int | None:
    """Character index under (near) ``pt``, or None when no glyph is close."""
    _adj, probe, idx = _probe_selection_at(doc, page, pt)
    if probe is None or idx is None:
        return None
    return idx if idx >= 0 else None


def _page_char_count(doc: QPdfDocument, page: int) -> int:
    """Character count of a page's text layer (0 when unavailable)."""
    try:
        all_sel = doc.getAllText(page)
    except Exception:
        return 0
    if all_sel is None or not all_sel.isValid():
        return 0
    try:
        end = int(all_sel.endIndex())
        if end > 0:
            return end
    except Exception:
        pass
    try:
        return len(all_sel.text() or "")
    except Exception:
        return 0


def _page_span_selection(
    doc: QPdfDocument,
    page: int,
    p1_page: int,
    p1: QPointF,
    p2_page: int,
    p2: QPointF,
) -> Any:
    """Valid QPdfSelection for one page's slice of a drag range, or None.

    Callers must pass a normalized range (p1_page <= p2_page). Corner-
    anchored getSelection() calls are unusable for continuation pages:
    pdfium returns an INVALID selection when an endpoint is >~7pt from a
    glyph, and page corners virtually never have one that close. The
    index-based APIs always work, so continuation pages select by char
    index instead: start page idx(p1)..end, middle pages getAllText,
    end page 0..idx(p2).
    """
    try:
        if page == p1_page and page == p2_page:
            sel = doc.getSelection(page, p1, p2)
        elif page == p1_page:
            idx = _char_index_at(doc, page, p1)
            count = _page_char_count(doc, page)
            if idx is None or count <= 0 or idx >= count:
                return None
            sel = doc.getSelectionAtIndex(page, idx, count - idx)
        elif page == p2_page:
            idx = _char_index_at(doc, page, p2)
            if idx is None or idx <= 0:
                return None
            sel = doc.getSelectionAtIndex(page, 0, idx)
        else:
            sel = doc.getAllText(page)
    except Exception:
        return None
    if sel is not None and sel.isValid():
        return sel
    return None


def _collect_selection_text(
    doc: QPdfDocument,
    p1_page: int,
    p1: QPointF,
    p2_page: int,
    p2: QPointF,
) -> tuple[str, Any | None]:
    """Build selection text (and last valid QPdfSelection) for a drag range."""
    if p1_page > p2_page:
        p1_page, p2_page = p2_page, p1_page
        p1, p2 = p2, p1
    parts: list[str] = []
    last_sel: Any = None
    for page in range(p1_page, p2_page + 1):
        sel = _page_span_selection(doc, page, p1_page, p1, p2_page, p2)
        if sel is not None and sel.isValid():
            last_sel = sel
            t = (sel.text() or "").strip()
            if t:
                parts.append(t)
    return ("\n".join(parts), last_sel)


def _selection_highlight_color() -> Any:
    """System selection color (Preview-style), translucent.

    Computed per paint — never cached — so macOS accent/theme switches
    apply on the next repaint. Falls back to the Klaus brand accent
    (Anki-aligned link blue #3a82f7) when the palette is unavailable.
    """
    if QColor is None:
        return None
    fallback = QColor(58, 130, 247, 140)
    if QPalette is None:
        return fallback
    try:
        c = QApplication.palette().color(QPalette.ColorRole.Highlight)
        if c is not None and c.isValid():
            c = QColor(c)
            c.setAlpha(100)
            return c
    except Exception:
        pass
    return fallback


def _run_on_main(cb: Callable[[], None]) -> None:
    """Queue ``cb`` on the Qt main thread (K-078 adoption apply). Falls
    back to a direct call only when aqt's taskman is unavailable — i.e.
    headless harnesses, where there is no other thread to conflict."""
    try:
        from aqt import mw

        if mw is not None:
            mw.taskman.run_on_main(cb)
            return
    except Exception:
        pass
    try:
        cb()
    except Exception as exc:
        print(f"[klausmate] main-thread callback failed: {exc}")


def _record_color(record: dict, fallback: str, alpha: int) -> Any:
    """QColor for an annotation record's ``color`` field (K-078) —
    adopted outside marks keep their Preview color on screen; anything
    malformed falls back (highlights: Klaus yellow, text: black)."""
    if QColor is None:
        return None
    col = None
    try:
        c = record.get("color")
        if isinstance(c, str) and c:
            col = QColor(c if c.startswith("#") else "#" + c)
            if not col.isValid():
                col = None
    except Exception:
        col = None
    if col is None:
        col = QColor(fallback)
    col.setAlpha(alpha)
    return col


class _SelectionOverlay(QWidget):
    """Draws text-selection highlights over the PDF viewport."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rects: list[QRect] = []
        # Persistent highlights (plan B) in viewport coordinates —
        # painted FIRST, i.e. beneath the live selection and marquee.
        # (rect, QColor) since K-078: adopted outside highlights keep
        # their own color on screen.
        self._highlight_rects: list[tuple[QRect, Any]] = []
        # Adopted outside text (K-078): (viewport rect, text, QColor,
        # pixel size) — the record's contents drawn inside its box.
        self._text_boxes: list[tuple[QRect, str, Any, int]] = []
        # Marquee (Option/Alt+drag copy-as-image) rectangle in viewport
        # coordinates; None hides it.
        self._marquee: QRect | None = None
        # Sticky notes (N1): (viewport anchor point, note text) per
        # annotated highlight — anchor is the first highlight rect's
        # top-right corner, re-mapped on every overlay refresh.
        self._note_boxes: list[tuple[QPoint, str]] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def set_rects(self, rects: list[QRect]) -> None:
        self._rects = rects
        self.update()

    def set_highlight_rects(self, rects: list[tuple[QRect, Any]]) -> None:
        self._highlight_rects = rects
        self.update()

    def set_text_boxes(
        self, boxes: list[tuple[QRect, str, Any, int]]
    ) -> None:
        self._text_boxes = boxes
        self.update()

    def set_note_boxes(self, notes: list[tuple[QPoint, str]]) -> None:
        self._note_boxes = notes
        self.update()

    def set_marquee(self, rect: QRect | None) -> None:
        self._marquee = rect
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if QPainter is None or (
            not self._rects
            and not self._highlight_rects
            and not self._text_boxes
            and not self._note_boxes
            and self._marquee is None
        ):
            return
        painter = QPainter(self)
        try:
            if QColor is not None and self._highlight_rects:
                # Persistent highlights go beneath everything else:
                # translucent, Preview-style, in each record's own color.
                painter.setPen(Qt.PenStyle.NoPen)
                for rect, color in self._highlight_rects:
                    painter.setBrush(color)
                    painter.drawRect(rect)
            if QColor is not None and self._text_boxes:
                self._paint_texts(painter)
            if QColor is not None and self._rects:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_selection_highlight_color())
                for rect in self._rects:
                    painter.drawRect(rect)
            if self._marquee is not None:
                self._paint_marquee(painter)
            if QColor is not None and self._note_boxes:
                self._paint_notes(painter)
        except Exception as exc:
            # A drawing bug must degrade to "the overlay didn't draw",
            # never to an exception escaping mid-paint (stdout, not
            # Anki's error dialog — a repainting widget would spam).
            print(f"[klausmate] overlay paint failed: {exc}")
        finally:
            # ALWAYS close the painter, however the block above exits: a
            # QPainter left live on a widget corrupts the window's
            # backing store and segfaults Qt on the next flush — the
            # md3_switch 2026-08-26 crash spree in one sentence.
            painter.end()

    def _paint_texts(self, painter: Any) -> None:
        """Mirrored outside text (K-078/K-083): each record's contents
        drawn in its page box, scaled with the zoom, in the record's
        color. Only EXPLICIT line breaks wrap — Preview never soft-wraps
        a FreeText, and Qt's wider font metrics used to re-wrap
        'This is a test' and clip the overflow. If the widest line still
        exceeds the box, the font shrinks to fit instead of clipping."""
        try:
            for rect, text, color, px in self._text_boxes:
                text = (text or "").strip("\n")
                if not text.strip():
                    continue
                font = painter.font()
                try:
                    font.setFamily("Helvetica")
                except Exception:
                    pass
                font.setPixelSize(max(6, int(px)))
                painter.setFont(font)
                fm = painter.fontMetrics()
                lines = text.split("\n")
                widest = max(
                    (fm.horizontalAdvance(ln) for ln in lines), default=0
                )
                if widest > rect.width() > 0 and widest > 0:
                    shrunk = max(
                        6, int(int(px) * rect.width() / widest)
                    )
                    if shrunk < font.pixelSize():
                        font.setPixelSize(shrunk)
                        painter.setFont(font)
                        fm = painter.fontMetrics()
                painter.setPen(color)
                y = rect.y() + fm.ascent()
                for ln in lines:
                    painter.drawText(rect.x(), y, ln)
                    y += fm.lineSpacing()
        except Exception:
            pass

    def _paint_notes(self, painter: Any) -> None:
        """Sticky-note boxes for annotated highlights (N1).

        Pale-yellow rounded box at each anchor, small font, word-wrapped
        and truncated to ~180px wide / ~4 lines (drawText clips to the
        box rect by default).
        """
        if not self._note_boxes or QColor is None:
            return
        try:
            font = painter.font()
            font.setPixelSize(10)
            painter.setFont(font)
            fm = painter.fontMetrics()
            line_h = max(10, fm.height())
            max_w = 180
            max_h = 4 * line_h
            flags = int(Qt.TextFlag.TextWordWrap)
            for anchor, text in self._note_boxes:
                text = (text or "").strip()
                if not text:
                    continue
                br = fm.boundingRect(
                    QRect(0, 0, max_w - 10, max_h * 3), flags, text
                )
                w = min(max_w, br.width() + 10)
                h = min(max_h, br.height()) + 6
                box = QRect(anchor.x() + 2, anchor.y() - 2, w, h)
                if QPen is not None:
                    painter.setPen(QPen(QColor(190, 170, 80)))
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 245, 170, 235))
                painter.drawRoundedRect(box, 3, 3)
                painter.setPen(QColor(70, 60, 20))
                painter.drawText(box.adjusted(5, 3, -5, -3), flags, text)
        except Exception:
            pass

    def _paint_marquee(self, painter: Any) -> None:
        """Preview-style marquee: faint fill + 1px dashed gray border."""
        if self._marquee is None or QColor is None:
            return
        try:
            fill = _selection_highlight_color()
            if fill is not None:
                fill = QColor(fill)
                fill.setAlpha(30)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawRect(self._marquee)
            if QPen is not None:
                pen = QPen(QColor(128, 128, 128))
                pen.setWidth(1)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(self._marquee)
        except Exception:
            pass


class PdfViewer(QWidget):
    """One continuous PDF view with toolbar (page indicator + copy current page)."""

    def __init__(
        self,
        on_page_changed: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_page_changed = on_page_changed
        self._doc: QPdfDocument | None = None
        self._page_count = 0
        self._page_texts: list[str] = []
        self._select_start: tuple[int, QPointF] | None = None
        self._select_end: tuple[int, QPointF] | None = None
        self._selection_text = ""
        # Task 10 (K-196): plain callback attribute, same shape as
        # on_page_changed — set by PdfSidebar after construction (never
        # passed into __init__, since only the native renderer has one),
        # so it must default to None and every call site guard it.
        self.on_selection_changed: Callable[[str], None] | None = None
        self._pdf_selection: Any = None
        self._overlay: _SelectionOverlay | None = None
        self._viewport: QWidget | None = None
        # Word/paragraph gesture state (A2-A5). _last_dblclick arms
        # triple-click detection with (monotonic time, viewport pos) of
        # the last plain double-click; _gesture_press_pos remembers where
        # a word/paragraph gesture was pressed so the release guard can
        # tell a stationary release from a drag extension.
        self._last_dblclick: tuple[float, QPoint] | None = None
        self._gesture_press_pos: QPoint | None = None
        # True only between an in-page left press and its release —
        # drag-extension of the selection is gated on it so a stale
        # anchor (press outside a page, or a finished gesture) can never
        # resurrect an old selection mid-move.
        self._drag_selecting = False
        # Word-select index/text guard: log a mismatch only once.
        self._word_guard_warned = False
        # Marquee copy-as-image state (Option/Alt+drag, plan A2).
        # _marquee_anchor is non-None only mid-drag; _marquee_rect_pts
        # (page points on _marquee_page) persists after release so the
        # context menu can re-copy the region, like Preview.
        self._marquee_page: int | None = None
        self._marquee_anchor: QPointF | None = None
        self._marquee_rect_pts: QRectF | None = None
        # Press position of a potential drag-out of the persisted
        # marquee image (N2); non-None only while the button is down.
        self._marquee_drag_origin: QPoint | None = None
        # Persistent highlights (plan B). _doc_generation is bumped on
        # every set_document because ONE QPdfDocument is reused across
        # tabs (load_pdf re-loads into the same object) — id(doc) can
        # never key a cache. _selection_page_rects retains the page-point
        # rects _update_selection computes (highlights are minted from
        # them); _annotations_name is the store key for saves.
        self._highlights: list[dict] = []
        self._annotations_name: str | None = None
        self._selection_page_rects: list[tuple[int, QRectF]] = []
        self._doc_generation = 0
        # Annotation baking (real PDF annots written into the stored
        # .pdf). Debounced by a single-shot QTimer; the actual bake runs
        # on a plain threading.Thread (files + pypdf only, no Qt).
        # _bake_pending captures (user_files, name) BY VALUE at schedule
        # time — the viewer may switch tabs before the timer fires.
        # _bake_lock guards _bake_running across UI thread and worker.
        self._bake_timer: Any = None
        # Ordered set of pending (user_files, name) jobs — a plain slot
        # would drop PDF A's bake when PDF B is annotated within the
        # same debounce window.
        self._bake_pending: dict[tuple[str, str], bool] = {}
        self._bake_lock = threading.Lock()
        self._bake_running = False
        # Single-entry cache for _document_page_geometries (last key
        # wins). Geometries are doc-coord and scroll-independent, but
        # _on_view_scrolled refreshes the highlight overlay on EVERY
        # scrollbar tick — without this, each tick pays O(pages) pdfium
        # size calls. Keyed so any layout-relevant change invalidates.
        self._page_geoms_cache: tuple[tuple, dict[int, QRectF]] | None = None
        # Per-(generation, page) getAllText bounds for the snap fallback;
        # see _page_bounds_cached.
        self._alltext_bounds_cache: dict = {}
        # Thumbnails sidebar (plan B). Every attr exists — as None —
        # even when the strip cannot be built, so all other code guards
        # on None instead of hasattr.
        self._splitter: Any = None
        self._thumb_list: Any = None
        self._thumb_cache: OrderedDict = OrderedDict()
        self._thumb_render_timer: Any = None
        self._thumb_save_timer: Any = None
        self._thumb_width = 170
        self._thumbs_visible = False
        # True when the restored strip width still needs applying once
        # the panel actually shows — at construction time the whole
        # panel is hidden/unlaid-out, so QSplitter.setSizes squeezes the
        # strip to its 120px minimum. showEvent re-applies it.
        self._thumb_width_pending = False
        # Find bar (A9). Every attr exists — as None — even when the bar
        # cannot be built (QPdfSearchModel missing, no QPdfView), so all
        # other code guards on None instead of hasattr.
        self._search_model: Any = None
        self._find_bar: QWidget | None = None
        self._find_edit: Any = None
        self._find_count_label: QLabel | None = None
        self._find_prev_btn: Any = None
        self._find_next_btn: Any = None
        self._find_close_btn: Any = None
        self._find_debounce: Any = None
        self._search_jump_pending = False
        self._current_search_index = -1
        # Fallback footer for the page indicator (K-153) — declared here
        # as None, like the find bar and the strip above, so every other
        # code path guards on None instead of hasattr. Built at the end
        # of __init__, once the view it sits under exists.
        self._page_bar: QWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # No header row of its own — the viewer renders chrome-free. The
        # page indicator is adopted into the dock's single header bar by
        # the tab container; it stays hidden if nothing adopts it.
        # ("Copy page" was removed earlier — Cmd/Ctrl+double-click copies
        # the slide as an image; plain double-click selects a word. See the
        # MouseButtonDblClick handler in eventFilter.)
        self._page_label = QLabel("", self)
        try:
            from . import theme as _theme

            self._page_label.setStyleSheet(
                _theme.muted_label_qss(_theme.night_mode(), 10)
            )
        except Exception:
            self._page_label.setStyleSheet(
                "color: rgba(100,100,100,0.95); font-size: 10px;"
            )
        self._page_label.setVisible(False)
        # Clicking the page label opens Go to Page (plan A3). The event
        # filter travels with the label when the dock header adopts it;
        # while the label is hidden/unadopted the filter stays inert.
        try:
            self._page_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self._page_label.setToolTip("Go to page (Cmd+Option+G)")
        except Exception:
            pass
        self._page_label.installEventFilter(self)

        if QPdfView is not None:
            self._pdf_view = QPdfView(self)
            self._pdf_view.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            try:
                self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            except Exception:
                self._pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
            self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            # A documentless QPdfView paints its viewport in the palette's
            # Dark/Base roles — Qt's mid-grey, a slab between two dark panes
            # (K-178). Point every role it might read at the bg token, a
            # step darker than the chrome the panels wear (Pouya: "the middle
            # area for the PDF to be darker"). Roles, not a stylesheet: the
            # view paints the gap between pages itself, from its palette.
            try:
                from . import theme as _theme

                ground = QColor(_theme.palette(_theme.night_mode())["bg"])
                pal = self._pdf_view.palette()
                for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                             QPalette.ColorRole.Dark, QPalette.ColorRole.Mid):
                    pal.setColor(role, ground)
                self._pdf_view.setPalette(pal)
                self._pdf_view.viewport().setPalette(pal)
                self._pdf_view.viewport().setAutoFillBackground(True)
            except Exception as exc:
                print(f"[klausmate] viewer ground failed: {exc}")
            try:
                nav = self._pdf_view.pageNavigator()
                if hasattr(nav, "currentPageChanged"):
                    nav.currentPageChanged.connect(self._on_nav_page_changed)
            except Exception:
                pass
            self._viewport = self._pdf_view.viewport()
            if self._viewport is not None:
                # I-beam cursor signals "this is a text-selectable region".
                try:
                    self._viewport.setCursor(Qt.CursorShape.IBeamCursor)
                except Exception:
                    pass
                self._overlay = _SelectionOverlay(self._viewport)
                self._overlay.setGeometry(self._viewport.rect())
                self._overlay.raise_()
                self._viewport.installEventFilter(self)
            self._pdf_view.installEventFilter(self)
            try:
                vsb = self._pdf_view.verticalScrollBar()
                hsb = self._pdf_view.horizontalScrollBar()
                if vsb is not None:
                    vsb.valueChanged.connect(self._on_view_scrolled)
                    # rangeChanged fires when the document layout finally
                    # settles (0 -> N). Without it, highlights restored
                    # before the first layout stay drawn with pre-layout
                    # geometry until the first scroll/resize — macOS
                    # transient scrollbars fire no Resize either.
                    vsb.rangeChanged.connect(self._on_scroll_range_changed)
                if hsb is not None:
                    hsb.valueChanged.connect(self._on_view_scrolled)
                    hsb.rangeChanged.connect(self._on_scroll_range_changed)
            except Exception:
                pass
            self._pdf_view.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu
            )
            self._pdf_view.customContextMenuRequested.connect(
                self._show_context_menu
            )
            # QAbstractScrollArea can swallow Cmd+C before the eventFilter
            # sees it. A widget-scoped QShortcut guarantees the keystroke
            # routes to _copy_selection regardless of which descendant
            # (QPdfView or its viewport) holds focus.
            try:
                copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self._pdf_view)
                copy_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                copy_sc.activated.connect(self._copy_selection)
            except Exception:
                pass
            # Cmd+A selects the current page's text (A6) — mirrors the
            # Copy shortcut above (parented on the view, not on self, so
            # Cmd+A inside the find bar's line edit keeps its native
            # select-all-text behavior).
            try:
                sa_sc = QShortcut(
                    QKeySequence.StandardKey.SelectAll, self._pdf_view
                )
                sa_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                sa_sc.activated.connect(self._select_all_current_page)
            except Exception:
                pass
            # Zoom shortcuts (A7) — on self with WidgetWithChildrenShortcut
            # so they fire whether focus sits in the view, its viewport,
            # or the find bar.
            try:
                zoom_in_sc = QShortcut(QKeySequence.StandardKey.ZoomIn, self)
                zoom_in_sc.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                zoom_in_sc.activated.connect(self._zoom_in)
                # StandardKey.ZoomIn is Ctrl/Cmd+"+", which needs Shift on
                # most layouts — also bind what users actually press.
                zoom_in_eq_sc = QShortcut(QKeySequence("Ctrl+="), self)
                zoom_in_eq_sc.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                zoom_in_eq_sc.activated.connect(self._zoom_in)
                zoom_out_sc = QShortcut(QKeySequence.StandardKey.ZoomOut, self)
                zoom_out_sc.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                zoom_out_sc.activated.connect(self._zoom_out)
                zoom_reset_sc = QShortcut(QKeySequence("Ctrl+0"), self)
                zoom_reset_sc.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                zoom_reset_sc.activated.connect(self._zoom_reset)
            except Exception:
                pass
            # Go to Page (plan A3) — Ctrl+Alt+G = Cmd+Option+G on macOS,
            # Preview's binding.
            try:
                goto_sc = QShortcut(QKeySequence("Ctrl+Alt+G"), self)
                goto_sc.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                goto_sc.activated.connect(self._prompt_go_to_page)
            except Exception:
                pass
            # Highlight the current text selection (plan B). On the view
            # (not self) so the find bar's line edit never triggers it.
            # Ctrl+Shift+A (= Cmd+Shift+A) is the primary binding;
            # Ctrl+Shift+H is kept for continuity — note Anki's Add
            # window binds Cmd+Shift+H to History, which makes the
            # QShortcut ambiguous (dead) when docked there. The
            # ShortcutOverride handling in eventFilter resolves both
            # combos deterministically while focus is in the viewer;
            # these QShortcuts remain as fallback for conflict-free
            # hosts.
            try:
                hl_sc_a = QShortcut(
                    QKeySequence("Ctrl+Shift+A"), self._pdf_view
                )
                hl_sc_a.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                hl_sc_a.activated.connect(self._add_highlight_from_selection)
                hl_sc = QShortcut(QKeySequence("Ctrl+Shift+H"), self._pdf_view)
                hl_sc.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut
                )
                hl_sc.activated.connect(self._add_highlight_from_selection)
            except Exception:
                pass
            # Cmd+F find bar (A9): lives in this widget's own VBox, above
            # the QPdfView. It must NOT touch _page_label — that label is
            # adopted into the dock header by the tab container.
            try:
                self._build_find_bar(outer)
            except Exception as exc:
                print(f"[klausmate] find bar unavailable: {exc}")
            # Thumbnails strip (plan B): [thumb list | pdf view] inside a
            # horizontal splitter; the find bar above spans both. On any
            # failure fall back to the bare view — the strip is optional.
            try:
                self._build_thumbnail_panel(outer)
            except Exception as exc:
                print(f"[klausmate] thumbnails unavailable: {exc}")
                self._splitter = None
                self._thumb_list = None
            if self._splitter is None:
                outer.addWidget(self._pdf_view, 1)
        else:
            self._pdf_view = None
            outer.addWidget(QLabel("(PDF view unavailable)"), 1)

        # Fallback slot for the page indicator (K-153). The label above
        # is normally ADOPTED into a host's header bar — but only the
        # editor panel's tab container does that, so in the Library and
        # the lecture dock the page number was built, hidden, and never
        # shown: no readout, and click-to-go-to-page unreachable (only
        # Cmd+Opt+G still worked). This slim right-aligned footer row is
        # where the label goes when nothing claims it. It stays EMPTY
        # and hidden at construction — the label is only moved in from
        # showEvent, by which time an adopting host has already taken
        # it — so we never race a host for the widget, and the viewer
        # stays chrome-free wherever a host does provide a header.
        try:
            bar = QWidget(self)
            row = QHBoxLayout(bar)
            row.setContentsMargins(8, 2, 8, 3)
            row.setSpacing(0)
            row.addStretch(1)
            bar.setVisible(False)
            outer.addWidget(bar)
            self._page_bar = bar
        except Exception as exc:
            print(f"[klausmate] in-place page bar unavailable: {exc}")

    def _show_page_label_in_place(self) -> None:
        """Put the page indicator in the viewer's own footer when no
        host adopted it (K-153).

        Adoption IS a reparent — ``_PanelBar.__init__`` calls
        ``row.addWidget(page_label)``, which makes the bar the label's
        parent — so "is it still parented to us" is the entire test, and
        it needs no cooperation from any host. Re-run on every show, so
        a host that adopts later simply takes the label back out of our
        row and the row goes away.
        """
        bar = getattr(self, "_page_bar", None)
        if bar is None or getattr(self, "_page_label", None) is None:
            return
        try:
            parent = self._page_label.parentWidget()
            if parent is not self and parent is not bar:
                # A host owns the label; keep our footer out of the way.
                bar.setVisible(False)
                return
            if parent is not bar:
                # Free-floating child of the viewer, in no layout yet —
                # so this reparent is silent (a widget already IN a
                # layout would make Qt warn and steal it).
                bar.layout().addWidget(self._page_label)
            self._update_page_label(self._current_page())
            has_pages = self._page_count > 0
            self._page_label.setVisible(has_pages)
            bar.setVisible(has_pages)
        except RuntimeError:
            pass  # adopted label died with its host header (see below)
        except Exception as exc:
            print(f"[klausmate] in-place page label failed: {exc}")

    def set_page_texts(self, texts: list[str]) -> None:
        self._page_texts = texts or []

    def set_document(self, doc: QPdfDocument | None) -> None:
        self._doc = doc
        # The SAME QPdfDocument object is reused across tabs, so a
        # generation counter — not id(doc) — keys thumbnail caches and
        # guards deferred callbacks against document swaps (plan B).
        self._doc_generation += 1
        self._clear_selection()
        self._clear_marquee()
        # Highlights belong to the previous document; the sidebar calls
        # load_annotations(name) right after this returns.
        self._highlights = []
        self._annotations_name = None
        if self._overlay is not None:
            self._overlay.set_highlight_rects([])
            self._overlay.set_text_boxes([])
        self._last_dblclick = None
        self._gesture_press_pos = None
        self._reset_find_bar(doc)
        if self._pdf_view is None:
            return
        self._pdf_view.setDocument(doc)
        try:
            self._page_count = int(doc.pageCount()) if doc is not None else 0
        except Exception:
            self._page_count = 0
        self._sync_overlay_geometry()
        self._update_page_label(self._current_page())
        # A tab switch / first load while already on screen is the other
        # moment the in-place footer's answer can change (0 pages -> n).
        self._show_page_label_in_place()
        try:
            self._thumb_cache.clear()
        except Exception:
            pass
        self._rebuild_thumbnails()
        if self._page_count > 0:
            self._on_page_changed(0)

    def clear_document(self) -> None:
        self.set_document(None)
        self._page_count = 0
        self._page_texts = []
        try:
            self._page_label.setText("")
        except RuntimeError:
            pass  # adopted label died with the dock header (see above)

    def _sync_overlay_geometry(self) -> None:
        if self._overlay is None or self._viewport is None:
            return
        self._overlay.setGeometry(self._viewport.rect())
        self._overlay.raise_()

    def _screen_resolution(self) -> float:
        """Match QPdfViewPrivate: logical DPI / 72."""
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                dpi = float(screen.logicalDotsPerInch())
                if dpi > 0:
                    return dpi / 72.0
        except Exception:
            pass
        return 96.0 / 72.0

    def _layout_zoom(self) -> float:
        if self._pdf_view is None:
            return 1.0
        try:
            z = float(self._pdf_view.zoomFactor())
            return z if z > 0 else 1.0
        except Exception:
            return 1.0

    def _layout_margins_spacing(self) -> tuple[int, int, int, int, int]:
        if self._pdf_view is None:
            return 0, 0, 0, 0, 4
        try:
            m = self._pdf_view.documentMargins()
            return m.left(), m.top(), m.right(), m.bottom(), self._pdf_view.pageSpacing()
        except Exception:
            return 0, 0, 0, 0, 4

    def _scroll_offset(self) -> tuple[int, int]:
        if self._pdf_view is None:
            return 0, 0
        sx = sy = 0
        try:
            hsb = self._pdf_view.horizontalScrollBar()
            if hsb is not None:
                sx = int(hsb.value())
        except Exception:
            pass
        try:
            vsb = self._pdf_view.verticalScrollBar()
            if vsb is not None:
                sy = int(vsb.value())
        except Exception:
            pass
        return sx, sy

    def _page_pixel_size(self, page: int) -> QSize:
        """Pixel size of one page — mirrors QPdfViewPrivate::calculateDocumentLayout.

        Thin wrapper around the float-accurate _page_float_size; kept for
        any callers that want an int QSize. The selection-coordinate
        pipeline now uses _page_float_size directly.
        """
        if self._doc is None or self._viewport is None:
            return QSize(1, 1)
        w_f, h_f = self._page_float_size(page)
        return QSize(max(1, int(round(w_f))), max(1, int(round(h_f))))

    def _empirical_avail_w(self) -> float | None:
        """Solve for Qt's actual FitToWidth scaling from the scrollbar range.

        Qt's QPdfView FitToWidth formula has changed between minor releases
        (6.5 used pageSize = pagePointSize * vp_w / page_pt_w; 6.6+ uses
        (vp_w − ml − mr) / page_pt_w). Either way, the verticalScrollBar's
        ``maximum() + viewport.height()`` equals the TRUE total content
        height Qt laid out. Given that total and the sum of the PDF's
        natural page aspect ratios, we can solve for whatever ``avail_w``
        Qt actually used:

            total = mt + avail_w * Σ(ph_i / pw_i) + (n − 1) * spacing + mb
            avail_w = (total − mt − (n − 1) * spacing − mb) / Σ(ph_i / pw_i)

        Returns None if the scrollbar isn't laid out yet (single page that
        fits in viewport, document still loading), in which case the
        caller should fall back to ``vp_w − ml − mr``.
        Result is cached keyed on (doc-id, page count, viewport width,
        vsb.maximum) so the per-page sum runs at most once per layout.
        """
        if (
            self._doc is None
            or self._pdf_view is None
            or self._viewport is None
            or self._page_count <= 0
        ):
            return None
        vsb = self._pdf_view.verticalScrollBar()
        if vsb is None:
            return None
        vsb_max = int(vsb.maximum())
        if vsb_max <= 0:
            return None  # nothing to scroll → can't derive total height
        vp_h = self._viewport.height()
        if vp_h <= 0:
            return None
        cache_key = (
            id(self._doc),
            self._page_count,
            self._viewport.width(),
            vsb_max,
        )
        cached = getattr(self, "_empirical_avail_w_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        ml, mt, mr, mb, spacing = self._layout_margins_spacing()
        sum_aspect = 0.0
        for i in range(self._page_count):
            ps = _page_size_points(self._doc, i)
            if ps.width() > 0:
                sum_aspect += ps.height() / ps.width()
        if sum_aspect <= 0:
            self._empirical_avail_w_cache = (cache_key, None)
            return None
        total = float(vsb_max) + float(vp_h)
        denom = sum_aspect
        avail_w = (total - mt - (self._page_count - 1) * spacing - mb) / denom
        if avail_w <= 0:
            self._empirical_avail_w_cache = (cache_key, None)
            return None
        self._empirical_avail_w_cache = (cache_key, avail_w)
        return avail_w

    def _page_float_size(self, page: int) -> tuple[float, float]:
        """Float pixel size for one page, matching Qt's QSizeF-based layout.

        For FitToWidth, ``avail_w`` is derived empirically from Qt's own
        scrollbar range (see _empirical_avail_w) — that makes the layout
        robust to Qt version differences in the FitToWidth formula. If
        the scrollbar isn't laid out yet (single short page), we fall
        back to the documented ``vp_w − ml − mr``.
        """
        if self._doc is None or self._viewport is None:
            return (1.0, 1.0)
        ps = _page_size_points(self._doc, page)
        pw_pt = max(1.0, float(ps.width()))
        ph_pt = max(1.0, float(ps.height()))
        sr = self._screen_resolution()
        base_w = pw_pt * sr
        base_h = ph_pt * sr
        ml, _mt, mr, _mb, _spacing = self._layout_margins_spacing()
        try:
            zoom_mode = self._pdf_view.zoomMode()
            fit_w = QPdfView.ZoomMode.FitToWidth
            fit_in = QPdfView.ZoomMode.FitInView
        except Exception:
            zoom_mode = fit_w = fit_in = None
        if zoom_mode == fit_w:
            # Prefer Qt's empirically-derived avail_w. The previous
            # documented-formula path drifted because Qt's actual formula
            # varies by minor release; the scrollbar range tells us the
            # truth Qt itself laid out with.
            avail_w = self._empirical_avail_w()
            if avail_w is None:
                avail_w = max(1.0, float(self._viewport.width() - ml - mr))
            return (avail_w, avail_w * (ph_pt / pw_pt))
        if zoom_mode == fit_in:
            avail_w = max(1.0, float(self._viewport.width() - ml - mr))
            vp_h = max(1.0, float(self._viewport.height()))
            scale = min(avail_w / base_w, vp_h / base_h)
            return (base_w * scale, base_h * scale)
        zoom = self._layout_zoom()
        return (base_w * zoom, base_h * zoom)

    def _document_page_geometries(self) -> dict[int, QRectF]:
        """Float-precision page rectangles in QPdfView document coords.

        Returns QRectF (not QRect) because Qt's own layout stores pages
        as QRectF and only quantizes at paint time. Summing float heights
        means cumulative-Y error stays at IEEE-754 precision (~1e-13 px)
        instead of accumulating ~1px per page like the prior int version.
        Selection-coordinate round trips now stay aligned with the
        rendered text however deep into the document you scroll.
        """
        if self._doc is None or self._viewport is None or self._page_count <= 0:
            return {}
        # Single-entry cache (scroll-independent — geometries are in doc
        # coords; callers apply the scroll offset themselves). The key
        # covers everything the layout derives from: document generation,
        # viewport width, zoom mode/factor, and the vertical scrollbar
        # range (which _empirical_avail_w solves FitToWidth against).
        zoom_mode: Any = None
        zoom_factor: Any = None
        try:
            if self._pdf_view is not None:
                zoom_mode = self._pdf_view.zoomMode()
                zoom_factor = float(self._pdf_view.zoomFactor())
        except Exception:
            zoom_mode = None
            zoom_factor = None
        vsb_max = -1
        try:
            if self._pdf_view is not None:
                vsb = self._pdf_view.verticalScrollBar()
                if vsb is not None:
                    vsb_max = int(vsb.maximum())
        except Exception:
            vsb_max = -1
        cache_key = (
            self._doc_generation,
            int(self._viewport.width()),
            zoom_mode,
            zoom_factor,
            vsb_max,
        )
        cached = self._page_geoms_cache
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        ml, mt, mr, _mb, spacing = self._layout_margins_spacing()
        vp_w = float(max(1, self._viewport.width()))
        sizes_f: list[tuple[float, float]] = []
        max_w_f = 0.0
        for page in range(self._page_count):
            sz = self._page_float_size(page)
            sizes_f.append(sz)
            if sz[0] > max_w_f:
                max_w_f = sz[0]
        total_width_f = max_w_f + float(ml) + float(mr)
        page_y_f = float(mt)
        geometries: dict[int, QRectF] = {}
        for page in range(self._page_count):
            pw, ph = sizes_f[page]
            page_x_f = (max(total_width_f, vp_w) - pw) / 2.0
            geometries[page] = QRectF(page_x_f, page_y_f, pw, ph)
            page_y_f += ph + float(spacing)
        self._page_geoms_cache = (cache_key, geometries)
        return geometries

    def _viewport_to_page_point(self, vp_pos: QPoint) -> tuple[int, QPointF] | None:
        if self._doc is None:
            return None
        scroll_x, scroll_y = self._scroll_offset()
        doc_pt = QPointF(
            float(vp_pos.x() + scroll_x),
            float(vp_pos.y() + scroll_y),
        )
        for page, geom in self._document_page_geometries().items():
            if not geom.contains(doc_pt):
                continue
            ps = _page_size_points(self._doc, page)
            if geom.width() <= 0 or geom.height() <= 0:
                return None
            lx = doc_pt.x() - geom.x()
            ly = doc_pt.y() - geom.y()
            return (
                page,
                QPointF(
                    lx * ps.width() / geom.width(),
                    ly * ps.height() / geom.height(),
                ),
            )
        return None

    def _point_rect_to_viewport(
        self,
        page: int,
        rect: Any,
        geoms: dict[int, QRectF] | None = None,
    ) -> QRect | None:
        """Map a page-point rect to viewport pixels.

        ``geoms`` lets batch callers (selection refresh, highlight
        overlay) pass one pre-computed ``_document_page_geometries()``
        dict so the mapping is O(pages) once, not per-rect.
        """
        if self._doc is None:
            return None
        if geoms is None:
            geoms = self._document_page_geometries()
        geom = geoms.get(page)
        if geom is None:
            return None
        ps = _page_size_points(self._doc, page)
        if ps.width() <= 0 or ps.height() <= 0:
            return None
        try:
            rx = float(rect.x())
            ry = float(rect.y())
            rw = float(rect.width())
            rh = float(rect.height())
        except Exception:
            return None
        # Pure float math through to the boundary — geom is QRectF now.
        doc_x = geom.x() + rx * geom.width() / ps.width()
        doc_y = geom.y() + ry * geom.height() / ps.height()
        doc_w = rw * geom.width() / ps.width()
        doc_h = rh * geom.height() / ps.height()
        scroll_x, scroll_y = self._scroll_offset()
        # Round to nearest, not truncate. int() floors positive floats —
        # for a doc_y of 591.7 that gave 591, putting the highlight 1px
        # above where Qt actually drew the text. round() matches Qt's
        # QRectF.toRect() behavior to within sub-pixel precision.
        return QRect(
            int(round(doc_x - scroll_x)),
            int(round(doc_y - scroll_y)),
            max(1, int(round(doc_w))),
            max(1, int(round(doc_h))),
        )

    def _on_view_scrolled(self, _value: int) -> None:
        if self._select_start is not None and self._select_end is not None:
            self._update_selection()
        if self._marquee_rect_pts is not None:
            self._update_marquee_overlay()
        # UNCONDITIONAL (plan B): highlights exist independent of any
        # live selection and must track every scroll.
        self._refresh_highlight_overlay()

    def _on_scroll_range_changed(self, *_args) -> None:
        """Scrollbar RANGE settled — layout changed, remap all overlays.

        The geometry caches key on scrollbar state that just changed
        meaning; drop them so _document_page_geometries re-derives from
        the fresh layout, then re-map highlights, the live selection and
        the marquee. Fixes first-page highlights drawn with pre-layout
        geometry after load (and selection drift after relayouts).
        """
        self._page_geoms_cache = None
        self._empirical_avail_w_cache = None
        try:
            self._refresh_highlight_overlay()
            if self._select_start is not None and self._select_end is not None:
                self._update_selection()
            if self._marquee_rect_pts is not None:
                self._update_marquee_overlay()
        except Exception:
            pass

    def _clear_selection(self) -> None:
        self._select_start = None
        self._select_end = None
        self._selection_text = ""
        self._pdf_selection = None
        self._selection_page_rects = []
        self._drag_selecting = False
        if self._overlay is not None:
            self._overlay.set_rects([])
        if self.on_selection_changed is not None:
            try:
                self.on_selection_changed(self._selection_text)
            except Exception as exc:
                print(f"[klausmate] on_selection_changed failed: {exc}")

    def _update_selection(self) -> None:
        if (
            self._doc is None
            or self._select_start is None
            or self._select_end is None
        ):
            self._clear_selection()
            return
        p1_page, p1 = self._select_start
        p2_page, p2 = self._select_end
        text, last_sel = _collect_selection_text(self._doc, p1_page, p1, p2_page, p2)
        self._selection_text = text
        self._pdf_selection = last_sel
        rects: list[QRect] = []
        # Page-point rects are retained (plan B) — persistent highlights
        # are minted from them by _add_highlight_from_selection.
        page_rects: list[tuple[int, QRectF]] = []
        geoms = self._document_page_geometries()
        # Normalize so the "start page" branch of _page_span_selection
        # always pairs with the earlier page, whichever way the user
        # dragged.
        if p1_page > p2_page:
            p1_page, p2_page = p2_page, p1_page
            p1, p2 = p2, p1
        for page in range(p1_page, p2_page + 1):
            sel = _page_span_selection(
                self._doc, page, p1_page, p1, p2_page, p2
            )
            if sel is not None and sel.isValid():
                for r in _selection_bounds(sel):
                    try:
                        page_rects.append(
                            (
                                page,
                                QRectF(
                                    float(r.x()),
                                    float(r.y()),
                                    float(r.width()),
                                    float(r.height()),
                                ),
                            )
                        )
                    except Exception:
                        pass
                    vr = self._point_rect_to_viewport(page, r, geoms)
                    if vr is not None:
                        rects.append(vr)
        self._selection_page_rects = page_rects
        if self._overlay is not None:
            self._overlay.set_rects(rects)
        if self.on_selection_changed is not None:
            try:
                self.on_selection_changed(self._selection_text)
            except Exception as exc:
                print(f"[klausmate] on_selection_changed failed: {exc}")

    # ------------------------------------------------------------------
    # Marquee copy-as-image (Option/Alt+drag, plan A2)
    # ------------------------------------------------------------------

    def _clamp_to_page_points(
        self, page: int, vp_pos: QPoint
    ) -> QPointF | None:
        """Map a viewport position to page points on ``page``, clamped.

        The marquee is pinned to its anchor page: a drag that crosses a
        page boundary (or wanders into the margin) keeps producing points
        clamped to the anchor page's bounds instead of jumping pages.
        """
        if self._doc is None:
            return None
        geom = self._document_page_geometries().get(page)
        if geom is None or geom.width() <= 0 or geom.height() <= 0:
            return None
        ps = _page_size_points(self._doc, page)
        if ps.width() <= 0 or ps.height() <= 0:
            return None
        scroll_x, scroll_y = self._scroll_offset()
        doc_x = float(vp_pos.x() + scroll_x)
        doc_y = float(vp_pos.y() + scroll_y)
        lx = min(max(doc_x - geom.x(), 0.0), geom.width())
        ly = min(max(doc_y - geom.y(), 0.0), geom.height())
        return QPointF(
            lx * ps.width() / geom.width(),
            ly * ps.height() / geom.height(),
        )

    def _clear_marquee(self) -> None:
        """Reset all marquee state and hide its overlay rectangle.

        Deliberately separate from _clear_selection: _update_selection
        calls _clear_selection internally, so folding the marquee reset
        into it would kill a persisted marquee on every selection
        refresh (scroll/zoom).
        """
        self._marquee_page = None
        self._marquee_anchor = None
        self._marquee_rect_pts = None
        self._marquee_drag_origin = None
        if self._overlay is not None:
            self._overlay.set_marquee(None)

    def _update_marquee_overlay(self) -> None:
        """Re-map the marquee's page-point rect into viewport coords."""
        if self._overlay is None:
            return
        if self._marquee_page is None or self._marquee_rect_pts is None:
            self._overlay.set_marquee(None)
            return
        vr = self._point_rect_to_viewport(
            self._marquee_page, self._marquee_rect_pts
        )
        self._overlay.set_marquee(vr)

    def _marquee_rect_from_drag(self, vp_pos: QPoint) -> QRectF | None:
        """Normalized page-point rect from the anchor to ``vp_pos``."""
        if self._marquee_page is None or self._marquee_anchor is None:
            return None
        cur = self._clamp_to_page_points(self._marquee_page, vp_pos)
        if cur is None:
            return None
        anchor = self._marquee_anchor
        x0, x1 = sorted((float(anchor.x()), float(cur.x())))
        y0, y1 = sorted((float(anchor.y()), float(cur.y())))
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def _render_marquee_image(self) -> Any:
        """Render the persisted marquee region to a QImage (or None).

        Full-page render via _render_page_pixmap (already composited
        over opaque white) at 150 DPI like the page copy, then cropped
        with QImage.copy(). Pixel scales derive from the ACTUAL rendered
        image size — not the requested one — so renderer rounding can't
        skew the crop. Shared by clipboard copy and drag-out (N2).
        """
        if (
            self._doc is None
            or self._marquee_page is None
            or self._marquee_rect_pts is None
            or QImage is None
        ):
            return None
        page = self._marquee_page
        rect_pts = self._marquee_rect_pts
        size = _page_size(self._doc, page)
        dpi_scale = 150.0 / 72.0
        width_px = max(400, int(size.width() * dpi_scale))
        pixmap = _render_page_pixmap(self._doc, page, width_px)
        if pixmap is None or pixmap.isNull():
            print("[klausmate] marquee render: page render failed")
            return None
        try:
            img = pixmap.toImage()
        except Exception:
            return None
        if img is None or img.isNull():
            return None
        page_pts = _page_size_points(self._doc, page)
        pw = float(page_pts.width())
        ph = float(page_pts.height())
        if pw <= 0 or ph <= 0:
            return None
        sx = img.width() / pw
        sy = img.height() / ph
        px_rect = QRect(
            int(round(rect_pts.x() * sx)),
            int(round(rect_pts.y() * sy)),
            int(round(rect_pts.width() * sx)),
            int(round(rect_pts.height() * sy)),
        )
        px_rect = px_rect.intersected(QRect(0, 0, img.width(), img.height()))
        if px_rect.width() <= 1 or px_rect.height() <= 1:
            return None
        try:
            cropped = img.copy(px_rect)
        except Exception:
            return None
        if cropped is None or cropped.isNull():
            return None
        return cropped

    def _copy_marquee_image(self) -> bool:
        """Copy the marquee region of its page to the clipboard as an image."""
        cropped = self._render_marquee_image()
        if cropped is None:
            return False
        cb = QApplication.clipboard()
        if cb is None:
            return False
        try:
            from PyQt6.QtCore import QMimeData

            mime = QMimeData()
            mime.setImageData(cropped)
            cb.setMimeData(mime)
        except Exception:
            try:
                if QPixmap is None:
                    return False
                cb.setPixmap(QPixmap.fromImage(cropped))
            except Exception:
                return False
        # The ONE tooltip the marquee is allowed — it's a capture action
        # like the page copy, not a selection.
        tooltip("Klaus: selection copied as image — paste with Cmd+V")
        return True

    def _start_marquee_image_drag(self) -> None:
        """Drag the persisted marquee region out as an image (N2).

        Started from a left press inside the marquee followed by a move
        beyond QApplication.startDragDistance. The QMimeData carries the
        rendered region image so dropping into an Anki note field (or
        any image-accepting target) pastes the figure. The marquee is
        kept after the drag, like Preview.
        """
        if QDrag is None or self._viewport is None:
            return
        img = self._render_marquee_image()
        if img is None:
            return
        try:
            from PyQt6.QtCore import QMimeData

            drag = QDrag(self._viewport)
            mime = QMimeData()
            mime.setImageData(img)
            drag.setMimeData(mime)
            try:
                if QPixmap is not None:
                    pm = QPixmap.fromImage(img)
                    if not pm.isNull() and (
                        pm.width() > 220 or pm.height() > 160
                    ):
                        pm = pm.scaled(
                            220,
                            160,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    if not pm.isNull():
                        drag.setPixmap(pm)
            except Exception:
                pass
            drag.exec(Qt.DropAction.CopyAction)
        except Exception as exc:
            print(f"[klausmate] marquee image drag failed: {exc}")

    # ------------------------------------------------------------------
    # Persistent highlights (plan B)
    # ------------------------------------------------------------------

    def scroll_position(self) -> tuple[int, int] | None:
        """Current (vertical, horizontal) scrollbar values — captured
        before an external-change reload so the reader keeps their
        place (K-078)."""
        try:
            return (
                int(self._pdf_view.verticalScrollBar().value()),
                int(self._pdf_view.horizontalScrollBar().value()),
            )
        except Exception:
            return None

    def restore_scroll_position(self, pos: tuple[int, int]) -> None:
        try:
            self._pdf_view.verticalScrollBar().setValue(int(pos[0]))
            self._pdf_view.horizontalScrollBar().setValue(int(pos[1]))
        except Exception:
            pass

    def load_annotations(self, name: str) -> None:
        """Load persisted highlights for ``name`` and paint them.

        Public — PdfSidebar.load_pdf calls this right after
        set_document. The overlay is refreshed immediately AND once more
        one tick deferred: FitToWidth layout isn't settled right after
        set_document, so the first mapping can land on stale geometry.
        """
        self._annotations_name = name
        if self._doc is None:
            self._highlights = []
            self._refresh_highlight_overlay()
            return
        try:
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            self._highlights = pdf_handler.load_annotations(USER_FILES, name)
            # Self-heal a stale bake: if the annotations json is newer
            # than the stored pdf (bake lost to a quit mid-debounce or a
            # dropped pending job), re-bake now. After a successful bake
            # the pdf is always newer, so this can't loop.
            try:
                import os as _os

                jpath = pdf_handler.annotations_path_for(USER_FILES, name)
                ppath = pdf_handler.pdf_path_for(USER_FILES, name)
                if (
                    ppath
                    and _os.path.isfile(jpath)
                    and _os.path.getmtime(jpath)
                    > _os.path.getmtime(ppath) + 1.0
                ):
                    print(
                        f"[klausmate] bake stale for {name} — re-baking"
                    )
                    self._schedule_bake(USER_FILES, name)
            except Exception:
                pass
        except Exception as exc:
            print(f"[klausmate] load annotations failed: {exc}")
            self._highlights = []
        self._refresh_highlight_overlay()
        gen = self._doc_generation
        try:
            QTimer.singleShot(0, lambda: self._deferred_highlight_remap(gen))
        except Exception:
            pass
        self._start_foreign_mirror(name)

    def _deferred_highlight_remap(self, gen: int) -> None:
        """One-tick-later remap, dropped if the document swapped since."""
        if self._doc_generation != gen:
            return
        try:
            self._refresh_highlight_overlay()
        except Exception:
            pass

    def _apply_mirror(self, name: str, res: dict) -> None:
        """Main-thread half of the mirror (K-082): records follow the
        file for outside marks — adds, in-place updates, removals.
        Schedules NO bake: the file is already correct for those marks,
        and baking here would re-feed the watcher loop."""
        try:
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            changed = pdf_handler.mirror_foreign_annotations(
                USER_FILES, name, res
            )
            if not changed:
                return
            if self._annotations_name == name:
                self._highlights = pdf_handler.load_annotations(
                    USER_FILES, name
                )
                self._refresh_highlight_overlay()
                tooltip(f"Klaus: synced {changed} outside change(s)")
        except Exception as exc:
            print(f"[klausmate] mirror apply failed: {exc}")

    def _start_foreign_mirror(self, name: str) -> None:
        """Mirror outside text/highlights for the loaded PDF (K-082).
        The pypdf scan and the one-time pristine capture run on a daemon
        thread — a multi-MB parse must never block the UI — while the
        merge/save hops back to the main thread so it cannot race the
        synchronous _save_annotations writes."""
        try:
            from . import pdf_handler
            from . import USER_FILES  # type: ignore
        except Exception:
            return
        if not getattr(pdf_handler, "BAKE_AVAILABLE", False):
            return

        def _worker() -> None:
            try:
                res = pdf_handler.scan_working_annotations(
                    USER_FILES, name
                )
                if res is None:
                    return
                if res.get("foreign"):
                    working = pdf_handler._working_pdf_path(
                        USER_FILES, name
                    )
                    if not pdf_handler._capture_pristine_stripped(
                        USER_FILES, name, working
                    ):
                        return
                _run_on_main(lambda: self._apply_mirror(name, res))
            except Exception as exc:
                print(f"[klausmate] mirror scan failed: {exc}")

        try:
            threading.Thread(
                target=_worker, name="klausmate-mirror", daemon=True
            ).start()
        except Exception as exc:
            print(f"[klausmate] mirror thread failed to start: {exc}")

    def _save_annotations(self) -> None:
        """Synchronous write-through (rare, tiny — see pdf_handler)."""
        if self._annotations_name is None:
            return
        try:
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            pdf_handler.save_annotations(
                USER_FILES, self._annotations_name, self._highlights
            )
            # The json is on disk — (re)arm the debounced bake that
            # writes real PDF annotations into the stored .pdf.
            self._schedule_bake(USER_FILES, self._annotations_name)
        except Exception as exc:
            print(f"[klausmate] save annotations failed: {exc}")

    def _schedule_bake(self, user_files_dir: str, name: str) -> None:
        """Debounce a PDF-annotation bake (~500ms, restarted on every
        change — K-085 dropped it from 1200ms so Klaus edits reach the
        file, and Preview, in well under a second). Args are captured
        by value NOW — the viewer may switch
        tabs before the timer fires, and the bake must target the pdf
        whose annotations just changed. Pending jobs are a SET (ordered
        dict): annotating PDF A then PDF B inside one debounce window
        bakes BOTH."""
        self._bake_pending[(user_files_dir, name)] = True
        try:
            if self._bake_timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(500)
                timer.timeout.connect(self._on_bake_timer)
                self._bake_timer = timer
            self._bake_timer.start()
        except Exception as exc:
            print(f"[klausmate] could not schedule bake: {exc}")

    def _on_bake_timer(self) -> None:
        """Debounce fired — spawn the bake worker.

        If a bake is already in flight, re-arm the timer instead of
        overlapping: the running bake reads the json it saw at start, so
        the re-armed pass picks up whatever changed mid-bake. The worker
        touches only files + pypdf — no Qt objects — so a plain
        threading.Thread keeps the UI free (12MB clone+write can take a
        second)."""
        if not self._bake_pending:
            return
        with self._bake_lock:
            if self._bake_running:
                try:
                    if self._bake_timer is not None:
                        self._bake_timer.start()
                except Exception:
                    pass
                return
            self._bake_running = True
        jobs = list(self._bake_pending.keys())
        self._bake_pending.clear()

        def _worker() -> None:
            try:
                from . import pdf_handler

                for user_files_dir, name in jobs:
                    try:
                        print(f"[klausmate] bake started: {name}")
                        rep: dict = {}
                        ok = pdf_handler.bake_annotations(
                            user_files_dir, name, report=rep
                        )
                        print(
                            f"[klausmate] bake finished: {name} "
                            f"({'ok' if ok else 'FAILED'})"
                        )
                        if ok:
                            # Main thread, in order: pin the fingerprint
                            # of the file WE wrote (K-078/K-085), drop
                            # records for marks the bake omitted as
                            # externally deleted (resurrection race),
                            # refresh overlays, then the ledger.
                            def _post(
                                d=user_files_dir,
                                n=name,
                                r=dict(rep),
                            ) -> None:
                                _refresh_stats_for(n, r.get("stat"))
                                try:
                                    from . import pdf_handler as _ph

                                    omitted = r.get("omitted_native") or []
                                    if omitted:
                                        _ph.remove_records(d, n, omitted)
                                        _reload_records_for(n)
                                    _ph.mark_native_baked(
                                        d, n, r.get("native_ids") or []
                                    )
                                except Exception as exc:
                                    print(
                                        "[klausmate] post-bake sync "
                                        f"failed: {exc}"
                                    )

                            _run_on_main(_post)
                    except Exception as exc:
                        print(
                            f"[klausmate] bake worker error for "
                            f"{name}: {exc}"
                        )
            finally:
                with self._bake_lock:
                    self._bake_running = False

        try:
            threading.Thread(
                target=_worker, name="klausmate-bake", daemon=True
            ).start()
        except Exception as exc:
            with self._bake_lock:
                self._bake_running = False
            print(f"[klausmate] bake thread failed to start: {exc}")

    def _refresh_highlight_overlay(self) -> None:
        """Re-map every highlight's page-point rects into viewport px.

        Also re-maps each non-empty note's anchor (the first rect's
        top-right corner, stored in page points) so sticky-note boxes
        (N1) track scroll/zoom exactly like the highlight rects.
        """
        if self._overlay is None:
            return
        if not self._highlights or self._doc is None:
            self._overlay.set_highlight_rects([])
            self._overlay.set_text_boxes([])
            self._overlay.set_note_boxes([])
            return
        geoms = self._document_page_geometries()
        rects: list[tuple[QRect, Any]] = []
        texts: list[tuple[QRect, str, Any, int]] = []
        notes: list[tuple[QPoint, str]] = []
        for hl in self._highlights:
            page = hl.get("page")
            is_text = hl.get("kind") == "text"
            first_vr: QRect | None = None
            for r in hl.get("rects", []):
                try:
                    rf = QRectF(
                        float(r[0]), float(r[1]), float(r[2]), float(r[3])
                    )
                except Exception:
                    continue
                vr = self._point_rect_to_viewport(page, rf, geoms)
                if vr is None:
                    continue
                if is_text:
                    # Adopted outside text (K-078): rects[0] is the box;
                    # font pixel size = page-point size x current zoom.
                    scale = (
                        vr.width() / rf.width() if rf.width() > 0 else 1.0
                    )
                    px = int(round(float(hl.get("size") or 12.0) * scale))
                    texts.append((
                        vr,
                        str(hl.get("text") or ""),
                        _record_color(hl, "#000000", 255),
                        px,
                    ))
                    break
                rects.append((vr, _record_color(hl, "#fadc50", 110)))
                if first_vr is None:
                    first_vr = vr
            try:
                note = str(hl.get("note") or "").strip()
            except Exception:
                note = ""
            if note and first_vr is not None:
                notes.append(
                    (QPoint(first_vr.right(), first_vr.top()), note)
                )
        self._overlay.set_highlight_rects(rects)
        self._overlay.set_text_boxes(texts)
        self._overlay.set_note_boxes(notes)

    def _add_highlight_from_selection(self) -> None:
        """Turn the live text selection into persistent highlights.

        Groups the retained selection rects by page (multi-page
        selection → one record per page), saves synchronously, then —
        like Preview — the highlight replaces the live selection.
        Without a selection, a tooltip explains the no-op instead of
        failing silently (image-only/scanned PDFs never produce one).
        """
        if self._doc is None:
            return
        if not self._selection_page_rects:
            tooltip("Klaus: select text first, then highlight")
            return
        by_page: dict[int, list[list[float]]] = {}
        for page, rf in self._selection_page_rects:
            try:
                by_page.setdefault(int(page), []).append(
                    [
                        float(rf.x()),
                        float(rf.y()),
                        float(rf.width()),
                        float(rf.height()),
                    ]
                )
            except Exception:
                continue
        if not by_page:
            return
        for page in sorted(by_page):
            self._highlights.append(
                {
                    "id": uuid.uuid4().hex,
                    "page": page,
                    "rects": by_page[page],
                    "color": "#fadc50",
                }
            )
        self._save_annotations()
        self._clear_selection()
        self._refresh_highlight_overlay()
        tooltip("Klaus: highlight added")

    def _highlight_at(
        self, page: int, pt: QPointF, tol: float = 3.0
    ) -> str | None:
        """Id of the topmost highlight under ``pt`` on ``page`` (±tol pts)."""
        for hl in reversed(self._highlights):
            if hl.get("page") != page:
                continue
            for r in hl.get("rects", []):
                try:
                    x, y, w, h = (float(v) for v in r)
                except Exception:
                    continue
                if (
                    x - tol <= pt.x() <= x + w + tol
                    and y - tol <= pt.y() <= y + h + tol
                ):
                    hl_id = hl.get("id")
                    return hl_id if isinstance(hl_id, str) else None
        return None

    def _remove_highlight(self, hl_id: str) -> None:
        removed = [h for h in self._highlights if h.get("id") == hl_id]
        self._highlights = [
            h for h in self._highlights if h.get("id") != hl_id
        ]
        if removed:
            # A deleted ADOPTED mark must stay deleted (K-081): the
            # unmarked original can still be in the file (bake pending,
            # or Preview re-saving its stale model) — tombstone it so
            # the next scan doesn't resurrect it.
            try:
                rec = removed[0]
                if (
                    rec.get("origin") == "external"
                    and self._annotations_name
                ):
                    from . import pdf_handler
                    from . import USER_FILES  # type: ignore

                    pdf_handler.add_suppressed(
                        USER_FILES, self._annotations_name, rec
                    )
            except Exception as exc:
                print(f"[klausmate] tombstone failed: {exc}")
            self._save_annotations()
            self._refresh_highlight_overlay()

    def _highlight_record(self, hl_id: str) -> dict | None:
        for hl in self._highlights:
            if hl.get("id") == hl_id:
                return hl
        return None

    def _edit_highlight_note(self, hl_id: str) -> None:
        """Add/edit the sticky note on one highlight (N1).

        QInputDialog only — multi-line when the binding provides
        getMultiLineText, single-line getText otherwise. An emptied
        note removes the sticky box (record keeps ``note: ""``).
        """
        if QInputDialog is None:
            return
        record = self._highlight_record(hl_id)
        if record is None:
            return
        existing = str(record.get("note") or "")
        try:
            if hasattr(QInputDialog, "getMultiLineText"):
                text, ok = QInputDialog.getMultiLineText(
                    self, "Highlight Note", "Note:", existing
                )
            else:
                text, ok = QInputDialog.getText(
                    self,
                    "Highlight Note",
                    "Note:",
                    QLineEdit.EchoMode.Normal,
                    existing,
                )
        except Exception as exc:
            print(f"[klausmate] note dialog failed: {exc}")
            return
        if not ok:
            return
        record["note"] = str(text).strip()
        self._save_annotations()
        self._refresh_highlight_overlay()

    def _copy_selection(self) -> bool:
        """Explicit copy (Cmd+C / context menu) — silent, like Preview."""
        text = (self._selection_text or "").strip()
        if text:
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(text)
                return True
        sel = self._pdf_selection
        if sel is not None and sel.isValid():
            try:
                if hasattr(sel, "copyToClipboard"):
                    sel.copyToClipboard()
                    return True
            except Exception:
                pass
        return False

    def _triple_click_pending(self, vp_pos: QPoint) -> bool:
        """True if a double-click armed us recently enough — and close
        enough — that the incoming click is the third of a triple-click."""
        armed = self._last_dblclick
        if armed is None:
            return False
        t0, pos0 = armed
        try:
            interval_ms = int(QApplication.doubleClickInterval())
        except Exception:
            interval_ms = 400
        if (time.monotonic() - t0) * 1000.0 > interval_ms:
            return False
        try:
            slop = 2 * int(QApplication.startDragDistance())
        except Exception:
            slop = 8
        if abs(vp_pos.x() - pos0.x()) > slop or abs(vp_pos.y() - pos0.y()) > slop:
            return False
        return True

    def _page_bounds_cached(self, page: int) -> list:
        """getAllText bounds rects (as float tuples) for a page, cached
        per document generation — the snap fallback runs on every drag
        move, and an uncached getAllText+scan per move is measurable
        jank on long drags."""
        gen = getattr(self, "_doc_generation", 0)
        cache = self._alltext_bounds_cache
        if cache.get("gen") != gen:
            cache.clear()
            cache["gen"] = gen
        rects = cache.get(page)
        if rects is None:
            sel = None
            if self._doc is not None:
                try:
                    sel = self._doc.getAllText(page)
                except Exception:
                    sel = None
            rects = []
            for r in _selection_bounds(sel):
                try:
                    rects.append(
                        (
                            float(r.x()),
                            float(r.y()),
                            float(r.width()),
                            float(r.height()),
                        )
                    )
                except Exception:
                    continue
            cache[page] = rects
        return rects

    def _snap_to_char(
        self, page: int, pt: QPointF, fast: bool = False
    ) -> QPointF | None:
        """Snap ``pt`` to a point pdfium resolves to a character.

        getSelection() endpoints farther than ~7pt from a glyph yield an
        INVALID selection, so raw press/drag points in margins or line
        gaps select nothing. Expanding probes in x AND y find nearby
        text first; if nothing is within probing range, fall back to
        the nearest cached getAllText bounds rect and clamp to its
        nearest in-text point (edge-inset, vertically centered).
        ``fast`` trims the probe cascade for per-mouse-move callers.
        """
        if self._doc is None:
            return None
        doc = self._doc
        adj, probe, _idx = _probe_selection_at(doc, page, pt, fast=fast)
        if probe is not None and adj is not None:
            return adj
        # Fallback: nearest glyph-run rect on the page (cached).
        best: Any = None
        best_d: float | None = None
        for rx, ry, rw, rh in self._page_bounds_cached(page):
            cx = min(max(pt.x(), rx), rx + rw)
            cy = min(max(pt.y(), ry), ry + rh)
            d = (cx - pt.x()) ** 2 + (cy - pt.y()) ** 2
            if best_d is None or d < best_d:
                best_d = d
                best = (rx, ry, rw, rh)
        if best is None:
            return None
        rx, ry, rw, rh = best
        left = rx + 1.0
        right = max(left, rx + rw - 1.0)
        return QPointF(
            min(max(pt.x(), left), right), ry + rh / 2.0
        )

    def _extend_selection_to(self, vp_pos: QPoint) -> None:
        """Move the live selection endpoint to ``vp_pos`` (text-snapped).

        When the new endpoint does not resolve to a valid selection
        (overshoot past a line end, margin, whitespace), the LAST valid
        endpoint is kept instead of blanking the live selection — the
        blue rects never flicker out mid-drag.
        """
        if self._select_start is None:
            return
        hit = self._viewport_to_page_point(vp_pos)
        if hit is None:
            # Outside every page (dark area): keep the current endpoint.
            return
        page, pt = hit
        snapped = self._snap_to_char(page, pt, fast=True)
        new_end = (page, snapped if snapped is not None else pt)
        prev_end = self._select_end
        prev_text = self._selection_text
        prev_rects = self._selection_page_rects
        self._select_end = new_end
        self._update_selection()
        if (
            not self._selection_text
            and not self._selection_page_rects
            and prev_end is not None
            and (prev_text or prev_rects)
        ):
            self._select_end = prev_end
            self._update_selection()

    def _apply_selection_direct(self, page: int, sel: Any) -> bool:
        """Populate the selection state straight from a QPdfSelection.

        Bypasses the corner-point getSelection pipeline (unusable for
        synthetic endpoints — see _snap_to_char) while anchoring
        _select_start/_select_end on the first/last glyph rects so the
        scroll/zoom remap through _update_selection keeps working.
        """
        if self._doc is None or sel is None or not sel.isValid():
            return False
        try:
            text = sel.text() or ""
        except Exception:
            text = ""
        rects = _selection_bounds(sel)
        if not text.strip() or not rects:
            return False
        first = rects[0]
        last = rects[-1]
        try:
            start_pt = QPointF(
                float(first.x()) + 0.1,
                float(first.y()) + float(first.height()) / 2.0,
            )
            end_pt = QPointF(
                float(last.x()) + float(last.width()) - 0.1,
                float(last.y()) + float(last.height()) / 2.0,
            )
        except Exception:
            return False
        self._select_start = (page, start_pt)
        self._select_end = (page, end_pt)
        self._selection_text = text
        self._pdf_selection = sel
        page_rects: list[tuple[int, QRectF]] = []
        vp_rects: list[QRect] = []
        geoms = self._document_page_geometries()
        for r in rects:
            try:
                page_rects.append(
                    (
                        page,
                        QRectF(
                            float(r.x()),
                            float(r.y()),
                            float(r.width()),
                            float(r.height()),
                        ),
                    )
                )
            except Exception:
                continue
            vr = self._point_rect_to_viewport(page, r, geoms)
            if vr is not None:
                vp_rects.append(vr)
        self._selection_page_rects = page_rects
        if self._overlay is not None:
            self._overlay.set_rects(vp_rects)
        if self.on_selection_changed is not None:
            try:
                self.on_selection_changed(self._selection_text)
            except Exception as exc:
                print(f"[klausmate] on_selection_changed failed: {exc}")
        return True

    def _nearest_page_at(self, vp_pos: QPoint) -> int | None:
        """Page whose laid-out geometry is nearest to ``vp_pos``.

        Used for presses that land OUTSIDE every page rect (the dark
        area around the document) so gestures like the Alt+drag marquee
        can clamp to the closest page instead of silently no-opping.
        """
        if self._doc is None:
            return None
        scroll_x, scroll_y = self._scroll_offset()
        doc_x = float(vp_pos.x() + scroll_x)
        doc_y = float(vp_pos.y() + scroll_y)
        best_page: int | None = None
        best_d: float | None = None
        for page, geom in self._document_page_geometries().items():
            try:
                cx = min(max(doc_x, geom.x()), geom.x() + geom.width())
                cy = min(max(doc_y, geom.y()), geom.y() + geom.height())
            except Exception:
                continue
            d = (cx - doc_x) ** 2 + (cy - doc_y) ** 2
            if best_d is None or d < best_d:
                best_d = d
                best_page = page
        return best_page

    def _select_word_at(self, page: int, pt: QPointF) -> bool:
        """Preview-style word selection at a page point (A3).

        Returns True when a word was selected; False is always a silent
        no-op (whitespace click, no text layer, or an index mismatch).
        """
        if self._doc is None:
            return False
        doc = self._doc
        # 1. Expanding probes (shared helper — includes the directional
        # wide-glyph rescue) resolve which character was double-clicked.
        idx = _char_index_at(doc, page, pt)
        if idx is None or idx < 0:
            return False
        # 2. Scan out to whitespace boundaries in the page's full text.
        try:
            all_sel = doc.getAllText(page)
            ftext = all_sel.text() if all_sel is not None else ""
        except Exception:
            return False
        if not ftext or idx >= len(ftext):
            return False
        ws = idx
        we = idx
        steps = 0
        while ws > 0 and not ftext[ws - 1].isspace() and steps < 200:
            ws -= 1
            steps += 1
        steps = 0
        while we < len(ftext) and not ftext[we].isspace() and steps < 200:
            we += 1
            steps += 1
        if ws == we:
            return False  # double-clicked whitespace — no-op
        # 3. Exact word selection by character index.
        try:
            word_sel = doc.getSelectionAtIndex(page, ws, we - ws)
        except Exception:
            return False
        if word_sel is None or not word_sel.isValid():
            return False
        try:
            word_text = word_sel.text() or ""
        except Exception:
            return False
        # pdfium char indices and QString UTF-16 offsets can diverge on
        # non-BMP characters (surrogate pairs — a known TODO in Qt's
        # qpdfdocument.cpp). On a mismatch, trust word_sel itself — its
        # text and bounds are self-consistent — instead of a silent
        # no-op that makes double-click look dead on such PDFs.
        if not word_text:
            return False
        if word_text != ftext[ws:we]:
            if not self._word_guard_warned:
                self._word_guard_warned = True
                print(
                    "[klausmate] word select index/text mismatch "
                    f"(page {page}: {word_text!r} != {ftext[ws:we]!r}); "
                    "using pdfium selection directly"
                )
            return self._apply_selection_direct(page, word_sel)
        # 4. Anchor into the existing point-based selection pipeline so
        # scroll refresh, the overlay, Cmd+C and drag-extension all work
        # unchanged.
        rects = _selection_bounds(word_sel)
        if not rects:
            return False
        try:
            first = rects[0]
            last = rects[-1]
            start_pt = QPointF(
                float(first.x()) + 0.1,
                float(first.y()) + float(first.height()) / 2.0,
            )
            end_pt = QPointF(
                float(last.x()) + float(last.width()) - 0.1,
                float(last.y()) + float(last.height()) / 2.0,
            )
        except Exception:
            return False
        self._select_start = (page, start_pt)
        self._select_end = (page, end_pt)
        self._update_selection()
        return True

    _PARAGRAPH_GAP_RE = re.compile(r"\r?\n(?:[ \t]*\r?\n)+")

    def _select_paragraph_at(self, page: int, pt: QPointF) -> bool:
        """Triple-click paragraph selection (A4) — index space.

        The previous geometric version probed edge-to-edge lines
        getSelection((0,y),(page_w,y)); both endpoints sit in the
        margins, beyond pdfium's ~7pt glyph tolerance, so it NEVER
        selected anything. Now: probe the char index under the click,
        expand in getAllText(page).text() to the block delimited by
        blank lines, select by index, and anchor glyph-based (like
        _select_word_at) so scroll remaps keep working.
        """
        if self._doc is None:
            return False
        doc = self._doc
        idx = _char_index_at(doc, page, pt)
        if idx is None:
            return False
        try:
            all_sel = doc.getAllText(page)
            ftext = all_sel.text() if all_sel is not None else ""
        except Exception:
            return False
        if not ftext:
            return False
        if idx >= len(ftext):
            idx = len(ftext) - 1
        # Block boundaries: blank-line separators (>=2 consecutive line
        # breaks, optional intra-gap spaces/tabs). Pages without blank
        # lines yield the whole page — acceptable for slide-style PDFs.
        block_start = 0
        block_end = len(ftext)
        try:
            for m in self._PARAGRAPH_GAP_RE.finditer(ftext):
                if m.end() <= idx:
                    block_start = m.end()
                elif m.start() > idx:
                    block_end = m.start()
                    break
                else:
                    # Click landed inside the gap itself — take the
                    # preceding block.
                    block_end = m.start()
                    break
        except Exception:
            pass
        while block_start < block_end and ftext[block_start].isspace():
            block_start += 1
        while block_end > block_start and ftext[block_end - 1].isspace():
            block_end -= 1
        if block_end <= block_start:
            return False
        try:
            block_sel = doc.getSelectionAtIndex(
                page, block_start, block_end - block_start
            )
        except Exception:
            return False
        return self._apply_selection_direct(page, block_sel)

    def _select_all_current_page(self) -> None:
        """Cmd+A: select all text on the current page (A6).

        Uses getAllText(page) directly: the previous corner-anchored
        getSelection((0,0),(w,h)) was ALWAYS invalid (pdfium requires
        endpoints within ~7pt of a glyph; page corners never are), so
        Cmd+A silently selected nothing.
        """
        if self._doc is None:
            tooltip("Klaus: no PDF loaded")
            return
        page = self._current_page()
        try:
            all_sel = self._doc.getAllText(page)
        except Exception:
            all_sel = None
        if (
            all_sel is None
            or not all_sel.isValid()
            or not (all_sel.text() or "").strip()
        ):
            tooltip("Klaus: no selectable text on this page")
            return
        if not self._apply_selection_direct(page, all_sel):
            tooltip("Klaus: no selectable text on this page")

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        copy_act = menu.addAction("Copy")
        copy_act.setEnabled(bool(self._selection_text.strip()))
        # Re-copy a persisted Option/Alt+drag marquee (plan A2).
        marquee_act = menu.addAction("Copy Selection as Image")
        marquee_act.setEnabled(self._marquee_rect_pts is not None)
        # Persistent highlight from the live selection (plan B). Stays
        # disabled on image-only/scanned PDFs — no text selection there.
        highlight_act = menu.addAction("Highlight")
        highlight_act.setEnabled(bool(self._selection_page_rects))
        page = self._current_page()
        # Prefer the slide actually under the right-click for the image
        # copy; fall back to the current page if the mapping fails. The
        # same hit doubles as the Remove Highlight hit-test (plan B).
        img_page = page
        hit: tuple[int, QPointF] | None = None
        try:
            if self._viewport is not None:
                vp_pos = self._viewport.mapFromGlobal(
                    self._pdf_view.mapToGlobal(pos)
                )
                hit = self._viewport_to_page_point(vp_pos)
                if hit is not None:
                    img_page = hit[0]
        except Exception:
            hit = None
        remove_hl_act = None
        note_act = None
        hl_hit_id: str | None = None
        if hit is not None:
            try:
                hl_hit_id = self._highlight_at(hit[0], hit[1])
            except Exception:
                hl_hit_id = None
            if hl_hit_id is not None:
                rec = None
                try:
                    rec = self._highlight_record(hl_hit_id)
                except Exception:
                    rec = None
                if rec is not None and rec.get("kind") == "text":
                    # Adopted outside text (K-078): deletable, no sticky.
                    remove_hl_act = menu.addAction("Remove Text")
                else:
                    # Sticky note on the highlight under the cursor (N1).
                    has_note = bool(
                        rec is not None and str(rec.get("note") or "").strip()
                    )
                    note_act = menu.addAction(
                        "Edit note…" if has_note else "Add note…"
                    )
                    remove_hl_act = menu.addAction("Remove Highlight")
        fallback = (
            self._page_texts[page] if 0 <= page < len(self._page_texts) else ""
        )
        page_act = menu.addAction("Copy Page Text")
        page_act.setEnabled(bool(fallback.strip()))
        # Discoverability twin of Cmd/Ctrl+double-click (A2).
        slide_act = menu.addAction("Copy Slide as Image")
        slide_act.setEnabled(self._doc is not None and self._page_count > 0)
        menu.addSeparator()
        # Zoom lived only on ⌘+/−/0 with no visible affordance anywhere
        # (critique P3) — the menu is its discoverable twin. The "\t"
        # right-aligns the key hint without registering a shortcut.
        zoom_in_act = menu.addAction("Zoom In\t⌘+")
        zoom_out_act = menu.addAction("Zoom Out\t⌘−")
        zoom_reset_act = menu.addAction("Actual Size\t⌘0")
        chosen = menu.exec(self._pdf_view.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == copy_act:
            self._copy_selection()
        elif chosen == marquee_act:
            self._copy_marquee_image()
        elif chosen == highlight_act:
            self._add_highlight_from_selection()
        elif note_act is not None and chosen == note_act:
            if hl_hit_id is not None:
                self._edit_highlight_note(hl_hit_id)
        elif remove_hl_act is not None and chosen == remove_hl_act:
            if hl_hit_id is not None:
                self._remove_highlight(hl_hit_id)
        elif chosen == page_act and fallback.strip():
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(fallback.strip())
                tooltip("Klaus: page text copied")
        elif chosen == slide_act and self._doc is not None:
            copy_pdf_page_image_to_clipboard(self._doc, img_page)
        elif chosen == zoom_in_act:
            self._zoom_in()
        elif chosen == zoom_out_act:
            self._zoom_out()
        elif chosen == zoom_reset_act:
            self._zoom_reset()

    def _match_shortcut_combo(self, event) -> str | None:
        """Name of OUR shortcut combo for a key event, or None.

        Host windows bind the same keys as window-scope shortcuts
        (Browse: Ctrl+F find, Ctrl+G/Ctrl+Alt+G filtered deck,
        Ctrl+Shift+G grade; Add: Ctrl+Shift+H history), which makes Qt
        declare the QShortcuts AMBIGUOUS — they emit nothing and the
        keys go dead when the viewer is docked. eventFilter consumes
        QEvent.ShortcutOverride for these combos while focus is inside
        the viewer, so the KeyPress is delivered to the widget and
        handled here deterministically.
        """
        try:
            key = event.key()
            mods = event.modifiers()
        except Exception:
            return None
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
        if not ctrl or meta:
            return None
        find_available = self._find_bar is not None
        if key == Qt.Key.Key_F and not shift and not alt:
            return "find" if find_available else None
        if key == Qt.Key.Key_G and alt and not shift:
            return "goto"
        if key == Qt.Key.Key_G and not alt and find_available:
            return "find_prev" if shift else "find_next"
        if key == Qt.Key.Key_A and shift and not alt:
            return "highlight"
        if key == Qt.Key.Key_H and shift and not alt:
            return "highlight"
        return None

    def _dispatch_shortcut_combo(self, combo: str) -> bool:
        """Run the action for a combo matched by _match_shortcut_combo."""
        try:
            if combo == "find":
                self._show_find_bar()
                return True
            if combo == "find_next":
                self._find_next_shortcut()
                return True
            if combo == "find_prev":
                self._find_prev_shortcut()
                return True
            if combo == "goto":
                self._prompt_go_to_page()
                return True
            if combo == "highlight":
                self._add_highlight_from_selection()
                return True
        except Exception as exc:
            print(f"[klausmate] shortcut dispatch failed ({combo}): {exc}")
            # The ShortcutOverride was already consumed — swallow the
            # key rather than leaking it half-handled to the host.
            return True
        return False

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if self._pdf_view is None:
            return super().eventFilter(obj, event)
        if self._find_edit is not None and obj is self._find_edit:
            if event.type() == QEvent.Type.ShortcutOverride:
                # Host-window QActions (Browse: Ctrl+F/Ctrl+G/…) make
                # our QShortcuts ambiguous when docked (F6). Claiming
                # the override delivers the KeyPress to the edit, where
                # the branch below dispatches it. Only find-cycling
                # combos — highlight must never fire from the find bar.
                combo = self._match_shortcut_combo(event)
                if combo in ("find", "find_next", "find_prev"):
                    event.accept()
                    return True
                return False
            if event.type() == QEvent.Type.KeyPress:
                combo = self._match_shortcut_combo(event)
                if combo in ("find", "find_next", "find_prev"):
                    if self._dispatch_shortcut_combo(combo):
                        event.accept()
                        return True
                try:
                    key = event.key()
                    mods = event.modifiers()
                except Exception:
                    return False
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if mods & Qt.KeyboardModifier.ShiftModifier:
                        self._find_prev()
                    else:
                        self._find_next()
                    return True
                if key == Qt.Key.Key_Escape:
                    self._close_find_bar()
                    return True
            return False
        if obj is self._page_label:
            # Go to Page via the page label (plan A3). The filter travels
            # with the label into the dock header; it is inert while the
            # label is hidden/unadopted. Press/DblClick MUST be consumed —
            # otherwise the header's drag filter starts a panel drag from
            # a label click — and the prompt fires on Release.
            lbl_et = event.type()
            if lbl_et in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
            ):
                return bool(self._page_label.isVisible())
            if lbl_et == QEvent.Type.MouseButtonRelease:
                if not self._page_label.isVisible():
                    return False
                try:
                    # Standard button semantics: only fire when the cursor
                    # is still over the label at release — dragging off
                    # and releasing cancels instead of opening the prompt.
                    if (
                        event.button() == Qt.MouseButton.LeftButton
                        and self._page_label.rect().contains(
                            _event_pos(event, self._page_label)
                        )
                    ):
                        self._prompt_go_to_page()
                except Exception:
                    pass
                return True
            return False
        if obj is self._pdf_view and event.type() == QEvent.Type.Resize:
            self._sync_overlay_geometry()
            # Mirror _set_custom_zoom: a resize relayouts the pages, so
            # the live text selection must be re-mapped too or its blue
            # rects desync from the text until the next scroll.
            if self._select_start is not None and self._select_end is not None:
                self._update_selection()
            self._refresh_highlight_overlay()
            return False
        if obj is self._pdf_view and event.type() == QEvent.Type.NativeGesture:
            # Trackpad pinch zoom (plan A3); other gestures propagate.
            if self._handle_native_gesture(event):
                return True
        if (
            obj is self._pdf_view
            and event.type() == QEvent.Type.ShortcutOverride
        ):
            # Claim OUR combos before Qt's shortcut maps see them (F6):
            # docked hosts bind the same keys window-wide (Browse:
            # Ctrl+F/Ctrl+G/Ctrl+Alt+G/Ctrl+Shift+G; Add: Ctrl+Shift+H)
            # which turns the QShortcuts ambiguous — dead. Accepting
            # the override routes the KeyPress to the widget instead,
            # handled deterministically below.
            if self._match_shortcut_combo(event) is not None:
                event.accept()
                return True
        if obj is self._pdf_view and event.type() == QEvent.Type.KeyPress:
            if (
                QKeySequence is not None
                and event.matches(QKeySequence.StandardKey.Copy)
            ):
                if self._copy_selection():
                    event.accept()
                    return True
                # No selection: don't swallow the keystroke.
            combo = self._match_shortcut_combo(event)
            if combo is not None and self._dispatch_shortcut_combo(combo):
                event.accept()
                return True
            if self._handle_nav_key(event):
                event.accept()
                return True
        if self._viewport is not None and obj is self._viewport:
            et = event.type()
            if et == QEvent.Type.Resize:
                self._sync_overlay_geometry()
                # Mirror _set_custom_zoom: re-map the live text selection
                # alongside marquee + highlights, or its blue rects
                # desync from the text until the next scroll.
                if self._select_start is not None and self._select_end is not None:
                    self._update_selection()
                if self._marquee_rect_pts is not None:
                    self._update_marquee_overlay()
                self._refresh_highlight_overlay()
                return False
            if et == QEvent.Type.NativeGesture:
                # Trackpad pinch zoom (plan A3); other gestures propagate.
                return self._handle_native_gesture(event)
            if et == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    vp_pos = _event_pos(event, self._viewport)
                    try:
                        mods = event.modifiers()
                    except Exception:
                        mods = Qt.KeyboardModifier.NoModifier
                    ctrl_held = bool(
                        mods & Qt.KeyboardModifier.ControlModifier
                    )
                    alt_held = bool(mods & Qt.KeyboardModifier.AltModifier)
                    if alt_held and not ctrl_held:
                        # Option/Alt+press starts a marquee (plan A2) —
                        # checked BEFORE triple-click so a fast
                        # click…Alt+click can't paragraph-select. Disarm
                        # all click-gesture state; text drag and marquee
                        # are mutually exclusive by state (_select_start
                        # vs _marquee_anchor).
                        self._last_dblclick = None
                        self._gesture_press_pos = None
                        self._clear_selection()
                        self._clear_marquee()
                        hit = self._viewport_to_page_point(vp_pos)
                        if hit is not None:
                            page = hit[0]
                        else:
                            # Alt+press OUTSIDE every page (F9): clamp
                            # to the nearest page and start the marquee
                            # there instead of a silent no-op.
                            page = self._nearest_page_at(vp_pos)
                        if page is not None:
                            anchor = self._clamp_to_page_points(
                                page, vp_pos
                            )
                            if anchor is not None:
                                self._marquee_page = page
                                self._marquee_anchor = anchor
                                self._marquee_rect_pts = QRectF(
                                    anchor.x(), anchor.y(), 0.0, 0.0
                                )
                                self._update_marquee_overlay()
                        return True
                    # A left press INSIDE a persisted marquee arms a
                    # potential drag-out of the region image (N2) — it
                    # must NOT start a text selection or clear the
                    # marquee; the clear happens on release if no drag
                    # materializes.
                    if (
                        not ctrl_held
                        and self._marquee_rect_pts is not None
                        and self._marquee_anchor is None
                        and self._marquee_page is not None
                    ):
                        try:
                            mvr = self._point_rect_to_viewport(
                                self._marquee_page, self._marquee_rect_pts
                            )
                        except Exception:
                            mvr = None
                        if mvr is not None and mvr.contains(vp_pos):
                            self._marquee_drag_origin = vp_pos
                            self._last_dblclick = None
                            self._gesture_press_pos = None
                            return True
                    # ANY plain left press clears a persisted marquee,
                    # like Preview collapsing the old selection.
                    self._clear_marquee()
                    # Triple-click detection is sequence-agnostic (Qt is
                    # commonly reported to deliver the third click as a
                    # plain Press — Press, Release, DblClick, Release,
                    # Press — but that isn't documented for every
                    # platform, so the DblClick branch below checks too).
                    # Ctrl/Cmd held means a modifier slide-copy gesture is
                    # in progress — never treat it as a triple-click.
                    if not ctrl_held and self._triple_click_pending(vp_pos):
                        self._last_dblclick = None
                        hit = self._viewport_to_page_point(vp_pos)
                        if hit is not None and self._select_paragraph_at(
                            hit[0], hit[1]
                        ):
                            self._gesture_press_pos = vp_pos
                            self._drag_selecting = True
                            return True
                        # Genuine triple-click whose paragraph select
                        # failed (no text under the click): KEEP the
                        # existing word selection — never fall through
                        # to the selection-clearing plain-click path.
                        if self._selection_text or self._selection_page_rects:
                            self._gesture_press_pos = vp_pos
                            return True
                    # A slow or moved third click falls through to a
                    # normal single click.
                    self._last_dblclick = None
                    hit = self._viewport_to_page_point(vp_pos)
                    if hit is not None:
                        self._pdf_view.setFocus(Qt.FocusReason.MouseFocusReason)
                        self._gesture_press_pos = None
                        page, page_pt = hit
                        # Snap the anchor to the nearest text (F4): a
                        # drag starting in a margin or between lines
                        # then selects from the nearest glyph instead
                        # of never resolving to a selection.
                        snapped = self._snap_to_char(page, page_pt)
                        anchor = (
                            page,
                            snapped if snapped is not None else page_pt,
                        )
                        self._select_start = anchor
                        self._select_end = anchor
                        self._drag_selecting = True
                        self._update_selection()
                        return True
                    # Press OUTSIDE every page (dark area): Preview's
                    # click-to-deselect. Also drops all gesture state so
                    # a stale anchor can never resurrect an old
                    # selection when the drag re-enters a page.
                    self._gesture_press_pos = None
                    self._clear_selection()
                    return False
            if et == QEvent.Type.MouseMove:
                if (
                    self._marquee_drag_origin is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                ):
                    # Armed drag-out of the persisted marquee (N2):
                    # start the QDrag once the press has travelled
                    # beyond the platform drag threshold.
                    pos = _event_pos(event, self._viewport)
                    origin = self._marquee_drag_origin
                    try:
                        dist = int(QApplication.startDragDistance())
                    except Exception:
                        dist = 4
                    if (
                        abs(pos.x() - origin.x()) > dist
                        or abs(pos.y() - origin.y()) > dist
                    ):
                        self._marquee_drag_origin = None
                        self._start_marquee_image_drag()
                    return True
                if (
                    self._marquee_anchor is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                ):
                    # Marquee drag (plan A2). State-driven: releasing
                    # Alt mid-drag keeps the gesture a marquee until
                    # mouse release.
                    rect = self._marquee_rect_from_drag(
                        _event_pos(event, self._viewport)
                    )
                    if rect is not None:
                        self._marquee_rect_pts = rect
                        self._update_marquee_overlay()
                    return True
                if (
                    self._drag_selecting
                    and self._select_start is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                ):
                    # Gated on _drag_selecting (set only by an in-page
                    # press) so a stale anchor can never resurrect an
                    # old selection; the endpoint is text-snapped and
                    # keeps the last valid position on overshoot (F4).
                    self._extend_selection_to(
                        _event_pos(event, self._viewport)
                    )
                    return True
                return False
            if et == QEvent.Type.MouseButtonRelease:
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and self._marquee_drag_origin is not None
                ):
                    # Press inside the persisted marquee that never
                    # became a drag-out (N2): plain click — clear the
                    # marquee like any other left click would have.
                    self._marquee_drag_origin = None
                    self._clear_marquee()
                    return True
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and self._marquee_anchor is not None
                ):
                    # Marquee finalize (plan A2): a <3pt drag on either
                    # axis is an accidental Alt+click — clear silently;
                    # otherwise copy the region and persist the marquee
                    # for the context menu, like Preview.
                    rect = self._marquee_rect_from_drag(
                        _event_pos(event, self._viewport)
                    )
                    self._marquee_anchor = None
                    if (
                        rect is None
                        or rect.width() < 3.0
                        or rect.height() < 3.0
                    ):
                        self._clear_marquee()
                        return True
                    self._marquee_rect_pts = rect
                    self._update_marquee_overlay()
                    self._copy_marquee_image()
                    return True
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and self._select_start is not None
                ):
                    was_drag = self._drag_selecting
                    self._drag_selecting = False
                    vp_pos = _event_pos(event, self._viewport)
                    gesture_pos = self._gesture_press_pos
                    if gesture_pos is not None:
                        self._gesture_press_pos = None
                        try:
                            slop = int(QApplication.startDragDistance())
                        except Exception:
                            slop = 4
                        if (
                            abs(vp_pos.x() - gesture_pos.x()) <= slop
                            and abs(vp_pos.y() - gesture_pos.y()) <= slop
                        ):
                            # Stationary release after a word/paragraph
                            # gesture (A5): keep that selection instead
                            # of collapsing _select_end to the click
                            # point. Selection stays silent — copy is
                            # explicit (Cmd+C / context menu).
                            return True
                        # Moved release: fall through to the normal
                        # finalize so the drag extension sticks.
                    if was_drag:
                        # Text-snapped finalize (F4): an overshoot past
                        # the line end keeps the last valid endpoint
                        # instead of blanking the selection.
                        self._extend_selection_to(vp_pos)
                    else:
                        hit = self._viewport_to_page_point(vp_pos)
                        if hit is not None:
                            self._select_end = hit
                        self._update_selection()
                    return True
                return False
            if et == QEvent.Type.MouseButtonDblClick:
                if event.button() == Qt.MouseButton.LeftButton:
                    vp_pos = _event_pos(event, self._viewport)
                    try:
                        mods = event.modifiers()
                    except Exception:
                        mods = Qt.KeyboardModifier.NoModifier
                    ctrl_held = bool(
                        mods & Qt.KeyboardModifier.ControlModifier
                    )
                    if not ctrl_held and bool(
                        mods & Qt.KeyboardModifier.AltModifier
                    ):
                        # Alt+double-click is a no-op (plan A2): never
                        # word-select while the marquee modifier is down.
                        # Disarm all click-gesture state like the Alt+press
                        # branch does — a plain click followed quickly by
                        # Alt+press arrives as this DblClick, and leaving
                        # _select_start armed would turn the ensuing
                        # Alt-drag into a TEXT drag instead of a marquee.
                        self._last_dblclick = None
                        self._gesture_press_pos = None
                        self._clear_selection()
                        self._clear_marquee()
                        return True
                    # Sequence-agnostic triple-click check (see the
                    # MouseButtonPress branch above); disabled while
                    # Ctrl/Cmd is held so a modifier slide-copy right
                    # after a plain double-click can't paragraph-select.
                    if not ctrl_held and self._triple_click_pending(vp_pos):
                        self._last_dblclick = None
                        hit = self._viewport_to_page_point(vp_pos)
                        if hit is not None and self._select_paragraph_at(
                            hit[0], hit[1]
                        ):
                            self._gesture_press_pos = vp_pos
                            self._drag_selecting = True
                            return True
                        # Failed paragraph select on a genuine triple-
                        # click: KEEP the existing word selection (F2)
                        # instead of degrading to a re-word-select.
                        if self._selection_text or self._selection_page_rects:
                            self._gesture_press_pos = vp_pos
                            return True
                    hit = self._viewport_to_page_point(vp_pos)
                    if hit is not None and self._doc is not None:
                        page, page_pt = hit
                        if ctrl_held:
                            # Cmd (macOS) / Ctrl (Windows) + double-click
                            # copies the slide as an image (A2). Plain
                            # double-click is word selection now.
                            self._last_dblclick = None  # disarm triple
                            self._clear_selection()
                            copy_pdf_page_image_to_clipboard(self._doc, page)
                            return True
                        # Plain double-click: Preview-style word select.
                        # Arm triple-click regardless of whether a word
                        # was hit so triple-clicking a paragraph's
                        # whitespace still selects the paragraph.
                        self._last_dblclick = (time.monotonic(), vp_pos)
                        if self._select_word_at(page, page_pt):
                            self._gesture_press_pos = vp_pos
                            # In-page press gesture: allow the drag
                            # extension until release (F4 gating).
                            self._drag_selecting = True
                        return True
                return False
            if et == QEvent.Type.ShortcutOverride:
                # Same F6 override claim as the _pdf_view branch — the
                # viewport can hold focus on some platforms.
                if self._match_shortcut_combo(event) is not None:
                    event.accept()
                    return True
                return False
            if et == QEvent.Type.KeyPress:
                if (
                    QKeySequence is not None
                    and event.matches(QKeySequence.StandardKey.Copy)
                ):
                    if self._copy_selection():
                        event.accept()
                        return True
                combo = self._match_shortcut_combo(event)
                if combo is not None and self._dispatch_shortcut_combo(combo):
                    event.accept()
                    return True
                if self._handle_nav_key(event):
                    event.accept()
                    return True
        return super().eventFilter(obj, event)

    def _effective_zoom(self) -> float:
        """The zoom factor the user *sees* right now, in any zoom mode.

        In FitToWidth mode ``zoomFactor()`` is unrelated to the layout,
        so derive the visual zoom from the laid-out page width
        (``_page_float_size`` / (page_pt_w x ``_screen_resolution``)).
        That way the first Cmd+= step scales from what's on screen
        instead of jumping to 1.25x of a stale factor.
        """
        if self._pdf_view is None or self._doc is None or self._page_count <= 0:
            return 1.0
        try:
            if self._pdf_view.zoomMode() == QPdfView.ZoomMode.Custom:
                return self._layout_zoom()
        except Exception:
            return self._layout_zoom()
        try:
            page = self._current_page()
            w_f, _h_f = self._page_float_size(page)
            ps = _page_size_points(self._doc, page)
            base_w = max(1.0, float(ps.width())) * self._screen_resolution()
            if base_w > 0 and w_f > 0:
                return w_f / base_w
        except Exception:
            pass
        return self._layout_zoom()

    def _set_custom_zoom(self, zoom: float) -> None:
        if self._pdf_view is None:
            return
        zoom = max(0.25, min(5.0, float(zoom)))
        try:
            # Factor first, then mode: while still in FitToWidth the
            # factor change is invisible, so the mode switch applies the
            # new zoom in a single relayout.
            self._pdf_view.setZoomFactor(zoom)
            self._pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        except Exception:
            return
        # The FitToWidth avail_w cache keys on scrollbar state that just
        # changed meaning — drop it so geometry re-derives cleanly.
        self._empirical_avail_w_cache = None
        if self._select_start is not None and self._select_end is not None:
            self._update_selection()
        if self._marquee_rect_pts is not None:
            self._update_marquee_overlay()
        self._refresh_highlight_overlay()

    def _zoom_in(self) -> None:
        if self._pdf_view is None or self._doc is None:
            return
        self._set_custom_zoom(self._effective_zoom() * 1.25)

    def _zoom_out(self) -> None:
        if self._pdf_view is None or self._doc is None:
            return
        self._set_custom_zoom(self._effective_zoom() / 1.25)

    def _zoom_reset(self) -> None:
        """Cmd+0: back to the default fit-width layout."""
        if self._pdf_view is None:
            return
        try:
            self._pdf_view.setZoomFactor(1.0)
            self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        except Exception:
            return
        self._empirical_avail_w_cache = None
        if self._select_start is not None and self._select_end is not None:
            self._update_selection()
        if self._marquee_rect_pts is not None:
            self._update_marquee_overlay()
        self._refresh_highlight_overlay()

    def _handle_native_gesture(self, event) -> bool:
        """Trackpad pinch zoom (plan A3).

        Returns True only for a consumed ZoomNativeGesture; every other
        gesture type propagates. ``event.value()`` is the incremental
        zoom delta; a value ≤ −1 would flip the sign, so the factor is
        floored at 0.2.
        """
        try:
            if (
                event.gestureType()
                != Qt.NativeGestureType.ZoomNativeGesture
            ):
                return False
        except Exception:
            return False
        if self._pdf_view is None or self._doc is None:
            return False
        try:
            value = float(event.value())
        except Exception:
            return False
        factor = max(0.2, 1.0 + value)
        self._set_custom_zoom(self._effective_zoom() * factor)
        return True

    def _handle_nav_key(self, event) -> bool:
        """PgUp/PgDn/Home/End page navigation (A8).

        Returns True when the key was consumed. Plain keys only —
        Ctrl/Cmd-modified presses are left alone, and arrows stay with
        QPdfView's native scrolling.
        """
        if self._pdf_view is None or self._page_count <= 0:
            return False
        try:
            mods = event.modifiers()
            if mods & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.MetaModifier
            ):
                return False
            key = event.key()
        except Exception:
            return False
        page = self._current_page()
        if key == Qt.Key.Key_PageUp:
            target = page - 1
        elif key == Qt.Key.Key_PageDown:
            target = page + 1
        elif key == Qt.Key.Key_Home:
            target = 0
        elif key == Qt.Key.Key_End:
            target = self._page_count - 1
        else:
            return False
        self.go_to_page(max(0, min(target, self._page_count - 1)))
        return True

    def _current_page(self) -> int:
        if self._pdf_view is None:
            return 0
        try:
            return int(self._pdf_view.pageNavigator().currentPage())
        except Exception:
            return 0

    def go_to_page(self, page: int) -> None:
        """Jump the view to the top of ``page`` (0-based)."""
        if self._pdf_view is None:
            return
        try:
            nav = self._pdf_view.pageNavigator()
            try:
                nav.jump(int(page), QPointF(0, 0))
            except TypeError:
                # Older PyQt6 bindings require the zoom argument.
                nav.jump(int(page), QPointF(0, 0), nav.currentZoom())
        except Exception:
            pass

    def _prompt_go_to_page(self) -> None:
        """Go to Page dialog (plan A3) — Cmd+Option+G / page-label click.

        Silent no-op without a document, mirroring Preview.
        """
        if (
            self._doc is None
            or self._page_count <= 0
            or QInputDialog is None
        ):
            return
        try:
            value, ok = QInputDialog.getInt(
                self,
                "Go to Page",
                f"Page (1–{self._page_count}):",
                self._current_page() + 1,
                1,
                self._page_count,
            )
        except Exception:
            return
        if ok:
            self.go_to_page(int(value) - 1)

    def _on_nav_page_changed(self, page: int) -> None:
        self._update_page_label(page)
        self._sync_thumb_selection(page)
        self._on_page_changed(page)

    def _update_page_label(self, page: int) -> None:
        try:
            if self._page_count <= 0:
                self._page_label.setText("")
                return
            page = max(0, min(page, self._page_count - 1))
            self._page_label.setText(f"Page {page + 1} / {self._page_count}")
        except RuntimeError:
            # The dock header ADOPTS this label (see __init__), so the
            # host window can destroy it while this viewer object outlives
            # the teardown race — seen live 2026-08-24. A dead label only
            # costs the page readout; never let it poison a nav signal.
            pass

    # ------------------------------------------------------------------
    # Cmd+F find bar (A9)
    # ------------------------------------------------------------------

    def _build_find_bar(self, outer: QVBoxLayout) -> None:
        """Build the find bar and search model.

        Only runs when QPdfSearchModel imported successfully; otherwise
        every find attr stays None and the feature silently degrades.
        The caller adds the QPdfView to ``outer`` *after* this, so the
        bar sits above the view inside PdfViewer's own VBox.
        """
        if (
            QPdfSearchModel is None
            or QLineEdit is None
            or QTimer is None
            or self._pdf_view is None
        ):
            return
        try:
            self._search_model = QPdfSearchModel(self)
            # Native match highlighting: QPdfView draws the model's
            # results itself once the search model is attached.
            self._pdf_view.setSearchModel(self._search_model)
        except Exception:
            self._search_model = None
            return
        try:
            self._search_model.countChanged.connect(
                self._on_search_count_changed
            )
        except Exception:
            pass
        bar = QWidget(self)
        try:
            from . import theme as _theme

            _night = _theme.night_mode()
            bar.setObjectName("KlausFindBar")
            bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            bar.setStyleSheet(_theme.find_bar_qss(_night))
        except Exception as exc:
            _theme = None  # type: ignore[assignment]
            _night = False
            print(f"[klausmate] find bar theme failed: {exc}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(4)
        self._find_edit = QLineEdit(bar)
        self._find_edit.setPlaceholderText("Find in PDF…")
        try:
            self._find_edit.setClearButtonEnabled(True)
        except Exception:
            pass
        self._find_edit.textChanged.connect(self._on_find_text_changed)
        # Enter / Shift+Enter / Esc are handled in eventFilter.
        self._find_edit.installEventFilter(self)
        lay.addWidget(self._find_edit, 1)
        self._find_count_label = QLabel("", bar)
        try:
            self._find_count_label.setStyleSheet(
                _theme.muted_label_qss(_night, 10)  # type: ignore[union-attr]
            )
        except Exception:
            self._find_count_label.setStyleSheet(
                "color: rgba(100,100,100,0.95); font-size: 10px;"
            )
        lay.addWidget(self._find_count_label)
        self._find_prev_btn = QToolButton(bar)
        self._find_prev_btn.setText("‹")
        self._find_prev_btn.setToolTip("Previous match (Shift+Enter)")
        self._find_prev_btn.clicked.connect(self._find_prev)
        lay.addWidget(self._find_prev_btn)
        self._find_next_btn = QToolButton(bar)
        self._find_next_btn.setText("›")
        self._find_next_btn.setToolTip("Next match (Enter)")
        self._find_next_btn.clicked.connect(self._find_next)
        lay.addWidget(self._find_next_btn)
        self._find_close_btn = QToolButton(bar)
        self._find_close_btn.setText("✕")
        self._find_close_btn.setToolTip("Close (Esc)")
        self._find_close_btn.clicked.connect(self._close_find_bar)
        lay.addWidget(self._find_close_btn)
        bar.setVisible(False)
        self._find_bar = bar
        outer.addWidget(bar)
        # Debounced live search: typing restarts a 250ms single-shot.
        self._find_debounce = QTimer(self)
        self._find_debounce.setSingleShot(True)
        self._find_debounce.setInterval(250)
        self._find_debounce.timeout.connect(self._apply_search_string)
        try:
            find_sc = QShortcut(QKeySequence.StandardKey.Find, self)
            find_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            find_sc.activated.connect(self._show_find_bar)
        except Exception:
            pass
        # Cmd+G / Cmd+Shift+G (F3 elsewhere) cycle matches (plan A3).
        # Registered here — not in __init__ — so they only exist when
        # the find bar itself could be built.
        try:
            find_next_sc = QShortcut(
                QKeySequence.StandardKey.FindNext, self
            )
            find_next_sc.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            find_next_sc.activated.connect(self._find_next_shortcut)
            find_prev_sc = QShortcut(
                QKeySequence.StandardKey.FindPrevious, self
            )
            find_prev_sc.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            find_prev_sc.activated.connect(self._find_prev_shortcut)
        except Exception:
            pass

    def _show_find_bar(self) -> None:
        if self._find_bar is None or self._find_edit is None:
            return
        self._find_bar.setVisible(True)
        try:
            self._find_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self._find_edit.selectAll()
        except Exception:
            pass
        # Esc clears the model's search string but keeps the visible query
        # text; re-apply it on reopen so Enter cycles immediately instead
        # of being dead until the text is edited.
        try:
            txt = self._find_edit.text()
            if (
                txt
                and self._search_model is not None
                and txt != (self._search_model.searchString() or "")
            ):
                self._apply_search_string()
        except Exception:
            pass

    def _close_find_bar(self) -> None:
        """Esc: clear the search, hide the bar, refocus the PDF."""
        if self._find_bar is None:
            return
        try:
            if self._find_debounce is not None:
                self._find_debounce.stop()
        except Exception:
            pass
        self._search_jump_pending = False
        self._current_search_index = -1
        try:
            if self._search_model is not None:
                self._search_model.setSearchString("")
        except Exception:
            pass
        try:
            if self._pdf_view is not None:
                self._pdf_view.setCurrentSearchResultIndex(-1)
        except Exception:
            pass
        if self._find_count_label is not None:
            self._find_count_label.setText("")
        self._find_bar.setVisible(False)
        try:
            if self._pdf_view is not None:
                self._pdf_view.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def _reset_find_bar(self, doc: QPdfDocument | None) -> None:
        """Document changed: point the search model at it, clear state."""
        if self._search_model is None:
            return
        try:
            if self._find_debounce is not None:
                self._find_debounce.stop()
        except Exception:
            pass
        if self._find_edit is not None:
            try:
                self._find_edit.blockSignals(True)
                self._find_edit.clear()
            except Exception:
                pass
            finally:
                try:
                    self._find_edit.blockSignals(False)
                except Exception:
                    pass
        self._search_jump_pending = False
        self._current_search_index = -1
        try:
            self._search_model.setSearchString("")
        except Exception:
            pass
        try:
            self._search_model.setDocument(doc)
        except Exception:
            pass
        try:
            if self._pdf_view is not None:
                self._pdf_view.setCurrentSearchResultIndex(-1)
        except Exception:
            pass
        if self._find_count_label is not None:
            self._find_count_label.setText("")
        if self._find_bar is not None:
            self._find_bar.setVisible(False)

    def _on_find_text_changed(self, _text: str) -> None:
        if self._find_debounce is not None:
            try:
                self._find_debounce.start()
            except Exception:
                pass

    def _flush_pending_search(self) -> None:
        """Enter before the debounce fired: apply the search right away."""
        t = self._find_debounce
        if t is None:
            return
        try:
            if t.isActive():
                t.stop()
                self._apply_search_string()
        except Exception:
            pass

    def _apply_search_string(self) -> None:
        if self._search_model is None or self._find_edit is None:
            return
        try:
            text = self._find_edit.text()
        except Exception:
            return
        try:
            if text == (self._search_model.searchString() or ""):
                # setSearchString would no-op (no countChanged fires), so
                # resetting the index / arming the jump here would desync
                # from the view and yank it back to match #1 later.
                return
        except Exception:
            pass
        self._current_search_index = -1
        # QPdfSearchModel populates incrementally — never read count()
        # right after setSearchString. The countChanged handler jumps to
        # the first result as soon as one exists.
        self._search_jump_pending = bool(text)
        try:
            self._search_model.setSearchString(text)
        except Exception:
            return
        if not text:
            self._search_jump_pending = False
            if self._find_count_label is not None:
                self._find_count_label.setText("")
            try:
                if self._pdf_view is not None:
                    self._pdf_view.setCurrentSearchResultIndex(-1)
            except Exception:
                pass

    def _on_search_count_changed(self, *_args) -> None:
        if self._search_model is None:
            return
        try:
            count = int(self._search_model.count())
        except Exception:
            count = 0
        if count > 0 and self._search_jump_pending:
            self._search_jump_pending = False
            self._jump_to_result(0)
            return  # _jump_to_result refreshed the label
        self._update_find_count_label(count)

    def _update_find_count_label(self, count: int) -> None:
        if self._find_count_label is None:
            return
        if count <= 0:
            has_text = False
            try:
                has_text = bool(
                    self._find_edit is not None and self._find_edit.text()
                )
            except Exception:
                pass
            self._find_count_label.setText("0 matches" if has_text else "")
        elif self._current_search_index >= 0:
            self._find_count_label.setText(
                f"{self._current_search_index + 1} of {count}"
            )
        else:
            self._find_count_label.setText(f"{count} matches")

    def _jump_to_result(self, index: int) -> None:
        if self._search_model is None or self._pdf_view is None:
            return
        try:
            count = int(self._search_model.count())
        except Exception:
            return
        if count <= 0:
            return
        index = index % count  # next/prev cycle modulo count
        self._current_search_index = index
        self._search_jump_pending = False
        try:
            self._pdf_view.setCurrentSearchResultIndex(index)
        except Exception:
            pass
        try:
            link = self._search_model.resultAtIndex(index)
            if link is not None and link.isValid():
                self._pdf_view.pageNavigator().jump(link)
        except Exception:
            pass
        self._update_find_count_label(count)

    def _find_next(self) -> None:
        self._flush_pending_search()
        base = self._current_search_index
        self._jump_to_result(base + 1 if base >= 0 else 0)

    def _find_prev(self) -> None:
        self._flush_pending_search()
        base = self._current_search_index
        # From "no current result", Shift+Enter lands on the last match.
        self._jump_to_result(base - 1 if base >= 0 else -1)

    def _find_next_shortcut(self) -> None:
        """Cmd+G: next match — silent no-op while the bar is hidden."""
        if self._find_bar is None or not self._find_bar.isVisible():
            return
        self._find_next()

    def _find_prev_shortcut(self) -> None:
        """Cmd+Shift+G: previous match — silent while the bar is hidden."""
        if self._find_bar is None or not self._find_bar.isVisible():
            return
        self._find_prev()

    # ------------------------------------------------------------------
    # Thumbnails sidebar (plan B)
    # ------------------------------------------------------------------

    def _build_thumbnail_panel(self, outer: QVBoxLayout) -> None:
        """Build the thumbnails list + splitter around the QPdfView.

        Raises when the widgets are unavailable so the caller can fall
        back to adding the bare view. NoFocus keeps PgUp/Home with the
        pdf view; per-pixel scroll makes the strip feel native.
        """
        if (
            QSplitter is None
            or QListWidget is None
            or self._pdf_view is None
        ):
            raise RuntimeError("thumbnail widgets unavailable")
        lst = QListWidget(self)
        try:
            from . import theme as _theme

            lst.setObjectName("KlausThumbStrip")
            lst.setStyleSheet(_theme.thumb_strip_qss(_theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] thumb strip theme failed: {exc}")
        try:
            lst.setViewMode(QListView.ViewMode.ListMode)
        except Exception:
            pass
        lst.setIconSize(QSize(140, 190))
        lst.setUniformItemSizes(True)
        try:
            lst.setVerticalScrollMode(
                QAbstractItemView.ScrollMode.ScrollPerPixel
            )
        except Exception:
            pass
        lst.setMinimumWidth(120)
        lst.setMaximumWidth(280)
        lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            lst.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        except Exception:
            pass
        lst.itemClicked.connect(self._on_thumb_clicked)
        try:
            vsb = lst.verticalScrollBar()
            if vsb is not None:
                vsb.valueChanged.connect(self._on_thumb_scrolled)
        except Exception:
            pass
        self._thumb_list = lst

        # Debounced lazy rendering (80ms after the last strip scroll).
        # Timers are created BEFORE the splitter goes into the layout so
        # any construction failure still leaves the layout untouched and
        # the caller's bare-view fallback stays clean.
        self._thumb_render_timer = QTimer(self)
        self._thumb_render_timer.setSingleShot(True)
        self._thumb_render_timer.setInterval(80)
        self._thumb_render_timer.timeout.connect(self._render_visible_thumbs)
        # Debounced width persistence (500ms after the last splitter move).
        self._thumb_save_timer = QTimer(self)
        self._thumb_save_timer.setSingleShot(True)
        self._thumb_save_timer.setInterval(500)
        self._thumb_save_timer.timeout.connect(self._persist_thumbs_state)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)
        split.addWidget(lst)
        split.addWidget(self._pdf_view)
        try:
            split.setStretchFactor(0, 0)
            split.setStretchFactor(1, 1)
        except Exception:
            pass
        split.splitterMoved.connect(self._on_splitter_moved)
        self._splitter = split
        outer.addWidget(split, 1)

        # Restore last session's strip state (defaults hidden / 170px).
        state: dict = {}
        try:
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            state = pdf_handler.load_thumbs_state(USER_FILES)
        except Exception:
            state = {}
        self._thumbs_visible = bool(state.get("thumbs_visible", False))
        self._thumb_width = int(state.get("thumbs_width", 170))
        lst.setVisible(self._thumbs_visible)
        if self._thumbs_visible:
            # Splitter sizes only stick after layout — one tick deferred.
            # The whole panel is typically still hidden here, so even the
            # deferred apply lands before real layout and QSplitter
            # squeezes the strip to its 120px minimum; the pending flag
            # makes showEvent re-apply the saved width once visible.
            self._thumb_width_pending = True
            try:
                QTimer.singleShot(
                    0, lambda: self._apply_thumb_width(self._thumb_width)
                )
            except Exception:
                pass

    def _apply_thumb_width(self, width: int) -> None:
        split = self._splitter
        lst = self._thumb_list
        if split is None or lst is None or not self._thumbs_visible:
            return
        try:
            total = max(1, int(split.width()))
            width = max(120, min(280, int(width)))
            split.setSizes([width, max(1, total - width)])
        except Exception:
            pass

    def toggle_thumbnails(self, visible: bool | None = None) -> bool:
        """Show/hide the thumbnails strip; returns the new visibility.

        Public — the tab container's ◫ header button calls this. No
        checked-state bookkeeping anywhere: the strip itself is the
        indicator.
        """
        lst = self._thumb_list
        if lst is None:
            return False
        if visible is None:
            visible = not self._thumbs_visible
        visible = bool(visible)
        self._thumbs_visible = visible
        try:
            lst.setVisible(visible)
        except Exception:
            pass
        if visible:
            if self._doc is not None and lst.count() != self._page_count:
                self._rebuild_thumbnails()
            self._sync_thumb_selection(self._current_page())
            try:
                QTimer.singleShot(
                    0, lambda: self._apply_thumb_width(self._thumb_width)
                )
            except Exception:
                pass
            self._arm_thumb_render()
        # Show path persists ONLY visibility: splitter.sizes()[0] read
        # right after setVisible(True) is a transient (pre-layout) width
        # that would clobber the remembered one before the deferred
        # _apply_thumb_width above gets to use it.
        self._persist_thumbs_state(include_width=not visible)
        return visible

    def _thumb_placeholder(self) -> Any:
        """Shared gray placeholder pixmap so row heights are stable."""
        if QPixmap is None or QColor is None:
            return None
        w, h = 140, 190
        try:
            if self._doc is not None and self._page_count > 0:
                ps = _page_size_points(self._doc, 0)
                if ps.width() > 0:
                    h = max(
                        20,
                        min(
                            190,
                            int(round(140.0 * float(ps.height()) / float(ps.width()))),
                        ),
                    )
        except Exception:
            pass
        try:
            pm = QPixmap(w, h)
            pm.fill(QColor(224, 224, 224))
            return pm
        except Exception:
            return None

    def _rebuild_thumbnails(self) -> None:
        """Seed one placeholder row per page; real renders come lazily."""
        lst = self._thumb_list
        if lst is None:
            return
        try:
            lst.blockSignals(True)
            lst.clear()
        except Exception:
            pass
        finally:
            try:
                lst.blockSignals(False)
            except Exception:
                pass
        if self._doc is None or self._page_count <= 0:
            return
        placeholder = self._thumb_placeholder()
        for page in range(self._page_count):
            try:
                item = QListWidgetItem(f"{page + 1}")
                if placeholder is not None and QIcon is not None:
                    item.setIcon(QIcon(placeholder))
                lst.addItem(item)
            except Exception:
                continue
        self._sync_thumb_selection(self._current_page())
        self._arm_thumb_render()

    def _arm_thumb_render(self) -> None:
        t = self._thumb_render_timer
        if t is None:
            return
        try:
            t.start()
        except Exception:
            pass

    def _on_thumb_scrolled(self, _value: int) -> None:
        self._arm_thumb_render()

    def _render_thumb_pixmap(self, page: int) -> Any:
        """Retina-crisp render: 140 logical px wide at devicePixelRatio."""
        if self._doc is None:
            return None
        try:
            dpr = float(self.devicePixelRatioF())
        except Exception:
            dpr = 1.0
        if dpr <= 0:
            dpr = 1.0
        width_px = max(1, int(140 * dpr))
        pm = _render_page_pixmap(self._doc, page, width_px)
        if pm is None or pm.isNull():
            return None
        try:
            pm.setDevicePixelRatio(dpr)
        except Exception:
            pass
        return pm

    def _render_visible_thumbs(self) -> None:
        """Render thumbs for the visible row range ±2, max 3 per tick.

        Re-arms itself when more remain, so a long strip fills without
        janking the UI. Every result is guarded against a document swap
        landing mid-render (generation check).
        """
        lst = self._thumb_list
        if (
            lst is None
            or not lst.isVisible()
            or self._doc is None
            or self._page_count <= 0
            or lst.count() <= 0
        ):
            return
        gen = self._doc_generation
        # devicePixelRatio is part of the cache key: dragging the window
        # between a 1x and a Retina display must not serve wrong-dpr
        # (blurry or oversized) thumbs from a stale cache.
        try:
            dpr = float(self.devicePixelRatioF())
        except Exception:
            dpr = 1.0
        if dpr <= 0:
            dpr = 1.0
        dpr_key = int(round(dpr * 100))
        try:
            row_h = max(1, int(lst.sizeHintForRow(0)))
        except Exception:
            row_h = 100
        first, last = 0, lst.count() - 1
        try:
            vp = lst.viewport()
            top_item = lst.itemAt(4, 1)
            if top_item is not None:
                first = lst.row(top_item)
            bottom_item = lst.itemAt(4, max(0, vp.height() - 2))
            if bottom_item is not None:
                last = lst.row(bottom_item)
            else:
                last = first + (vp.height() // row_h) + 1
        except Exception:
            first, last = 0, lst.count() - 1
        first = max(0, first - 2)
        last = max(first, min(lst.count() - 1, last + 2))
        rendered = 0
        pending = False
        for row in range(first, last + 1):
            key = (gen, row, dpr_key)
            pm = self._thumb_cache.get(key)
            if pm is None:
                if rendered >= 3:
                    pending = True
                    break
                pm = self._render_thumb_pixmap(row)
                # A doc swap can land mid-render — drop stale results.
                if self._doc_generation != gen or self._doc is None:
                    return
                if pm is None:
                    continue
                rendered += 1
                try:
                    self._thumb_cache[key] = pm
                    while len(self._thumb_cache) > 200:
                        self._thumb_cache.popitem(last=False)
                except Exception:
                    pass
            else:
                # LRU touch.
                try:
                    self._thumb_cache.move_to_end(key)
                except Exception:
                    pass
            item = lst.item(row)
            if item is not None and QIcon is not None:
                try:
                    item.setIcon(QIcon(pm))
                except Exception:
                    pass
        if pending:
            self._arm_thumb_render()

    def _on_thumb_clicked(self, item) -> None:
        lst = self._thumb_list
        if lst is None or item is None:
            return
        try:
            row = int(lst.row(item))
        except Exception:
            return
        if row >= 0:
            self.go_to_page(row)

    def _sync_thumb_selection(self, page: int) -> None:
        """Track the current page — EnsureVisible, not center, so the
        strip never fights manual scrolling."""
        lst = self._thumb_list
        if lst is None or lst.count() <= 0:
            return
        page = max(0, min(int(page), lst.count() - 1))
        try:
            lst.blockSignals(True)
            lst.setCurrentRow(page)
            item = lst.item(page)
            if item is not None:
                lst.scrollToItem(
                    item, QAbstractItemView.ScrollHint.EnsureVisible
                )
        except Exception:
            pass
        finally:
            try:
                lst.blockSignals(False)
            except Exception:
                pass

    def _on_splitter_moved(self, *_args) -> None:
        t = self._thumb_save_timer
        if t is None:
            return
        try:
            t.start()
        except Exception:
            pass

    def _persist_thumbs_state(self, include_width: bool = True) -> None:
        # include_width=False lets the toggle show path save visibility
        # without snapshotting a transient pre-layout splitter width.
        if self._thumb_list is None:
            return
        width = None
        if include_width:
            try:
                if self._splitter is not None and self._thumbs_visible:
                    sizes = self._splitter.sizes()
                    if sizes and int(sizes[0]) > 0:
                        width = int(sizes[0])
                        self._thumb_width = width
            except Exception:
                width = None
        try:
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            pdf_handler.save_thumbs_state(
                USER_FILES, visible=self._thumbs_visible, width=width
            )
        except Exception as exc:
            print(f"[klausmate] save thumbs state failed: {exc}")

    def showEvent(self, ev) -> None:  # noqa: N802
        # Thumb renders skip while the panel is hidden (renders racing a
        # hidden widget are wasted work) — catch up when it appears.
        super().showEvent(ev)
        if self._thumb_width_pending:
            # Construction-time width restore ran while the panel was
            # hidden and got squeezed to the minimum — now that the
            # panel is shown and laid out, re-apply the saved width.
            self._thumb_width_pending = False
            try:
                QTimer.singleShot(
                    0, lambda: self._apply_thumb_width(self._thumb_width)
                )
            except Exception:
                pass
        # Highlights restored while the panel was hidden were mapped
        # against pre-layout geometry (F8) — drop the layout caches and
        # remap all overlays now that the panel is actually visible.
        self._page_geoms_cache = None
        self._empirical_avail_w_cache = None
        try:
            self._refresh_highlight_overlay()
            if self._select_start is not None and self._select_end is not None:
                self._update_selection()
            if self._marquee_rect_pts is not None:
                self._update_marquee_overlay()
        except Exception:
            pass
        # Adoption (or not) is settled by now — every host that wants the
        # page indicator has taken it during its own construction, which
        # runs before the panel is ever shown.
        self._show_page_label_in_place()
        self._arm_thumb_render()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        # A taller panel exposes more strip rows; debounced, so cheap.
        super().resizeEvent(ev)
        self._arm_thumb_render()


# Every live PdfSidebar, weakly held (K-078): the library watcher asks
# them all to reload when their working PDF changed on disk. Weak so a
# closed Library window's sidebar can be collected.
_open_sidebars: "weakref.WeakSet" = weakref.WeakSet()


def cleanup_all_sidebars() -> None:
    """Backstop for the AnkiWebView-hook leak (see PdfSidebar.cleanup).

    The explicit teardown paths (Library close, editor panel close)
    cover the common cases; this sweeps every live sidebar on profile
    switch and on quit so a path nobody enumerated still can't leave a
    dangling webview in Anki's theme_did_change hook. Idempotent —
    cleanup() is safe to call twice."""
    for sb in list(_open_sidebars):
        try:
            sb.cleanup()
        except Exception as exc:
            print(f"[klausmate] sidebar cleanup sweep failed: {exc}")


def _stat_of(path: str) -> tuple | None:
    """(inode, mtime_ns, size) — the external-change fingerprint. The
    inode is what actually flips on a Preview save (atomic replace) and
    on a Finder move; mtime/size catch in-place rewrites."""
    try:
        st = os.stat(path)
        return (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def poll_external_changes() -> None:
    """Called from pdf_drive's watcher tick (K-078). Each open sidebar
    checks its own file fingerprint and reloads if it changed — always
    one tick deferred, never inside the caller's event delivery
    (K-072 lesson). Never raises."""
    for sb in list(_open_sidebars):
        try:
            QTimer.singleShot(0, sb.reload_if_externally_changed)
        except Exception:
            pass


def _refresh_stats_for(name: str, stat: tuple | None = None) -> None:
    """Re-fingerprint every sidebar showing ``name`` — called after a
    successful bake so Klaus's OWN write to the working file never
    reads as an external change (without this, every highlight edit
    would reload the viewer ~2s later via the watcher).

    ``stat`` is the fingerprint of the file the bake actually wrote
    (K-085): stat'ing the path here instead could swallow a Preview
    save that landed between the bake's os.replace and this callback —
    it would be recorded as "current" and never mirrored."""
    for sb in list(_open_sidebars):
        try:
            if getattr(sb, "_name", None) != name:
                continue
            if stat is not None:
                sb._file_stat = tuple(stat)
                continue
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            path = pdf_handler.pdf_path_for(USER_FILES, name)
            if path:
                sb._file_stat = _stat_of(path)
        except Exception:
            pass


def _reload_records_for(name: str) -> None:
    """Refresh the overlay of every viewer showing ``name`` from the
    records on disk (K-085: after the post-bake callback removed marks
    that were deleted externally)."""
    for sb in list(_open_sidebars):
        try:
            v = getattr(sb, "_viewer", None)
            if v is None or getattr(v, "_annotations_name", None) != name:
                continue
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            v._highlights = pdf_handler.load_annotations(USER_FILES, name)
            v._refresh_highlight_overlay()
        except Exception:
            pass


class PdfSidebar(QWidget):
    """Right-side sidebar: one scrollable PDF document."""

    def __init__(self, editor: Editor, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # The panel styles ITSELF (K-153), exactly as the find bar and
        # the thumb strip already do — those two are the only parts of
        # the viewer that looked identical in all three hosts, and that
        # is precisely because they never depended on which window they
        # landed in. This widget used to carry no sheet and no styled
        # background, so it painted nothing and the host showed through
        # every gap. Applied here, on the one widget every host wraps,
        # rather than in any host: no host can forget it, both renderers
        # (QPdfView and pdf.js) sit inside it, and a fourth host gets
        # the look for free. See theme.pdf_panel_qss for each rule.
        try:
            from . import theme as _theme

            self.setObjectName("KlausPdfPanel")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setStyleSheet(_theme.pdf_panel_qss(_theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] pdf panel theme failed: {exc}")
        self._editor = editor
        self._name: Optional[str] = None
        # External-change fingerprint of the loaded working PDF (K-078).
        self._file_stat: tuple | None = None
        try:
            _open_sidebars.add(self)
        except Exception:
            pass
        self._doc: Optional[QPdfDocument] = None
        self._page_count = 0
        self._current_page = 0
        # Task 10 (K-196) fix round 1: which document _on_pdfjs_count's
        # eventual callback belongs to. Set in load_pdf's pdf.js branch
        # at the same moment as self._name; _on_pdfjs_count compares the
        # two by IDENTITY (not just "is self._name truthy") before
        # touching viewer_context, so a late count for a document this
        # sidebar has since left cannot resurrect it.
        self._pending_count_name: Optional[str] = None
        # Set by the tab container so every load — regardless of which
        # call site triggered it — is reflected in the tab bar.
        self.on_loaded: Optional[Callable[[str], None]] = None

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Renderer selection (K-095): config pdf_renderer == "pdfjs"
        # swaps in the webview/pdf.js viewer; anything else (or any
        # failure reading config) stays on the proven QPdfView path.
        self._renderer = "native"
        try:
            from . import pdfjs_viewer as _pdfjs

            if _pdfjs.PDFJS_AVAILABLE:
                from aqt import mw as _mw

                cfg = _mw.addonManager.getConfig(__package__) or {}
                self._renderer = _pdfjs.renderer_from_config(cfg)
        except Exception as exc:
            print(f"[klausmate] renderer flag read failed: {exc}")

        if self._renderer == "pdfjs":
            from . import pdfjs_viewer as _pdfjs

            self._doc = None
            self._viewer = _pdfjs.PdfJsViewer(
                on_page_changed=self.notify_page_changed,
                parent=self,
            )
            self._viewer.on_selection = self._report_selection
            outer.addWidget(self._viewer, 1)
            self._fallback_label = None
        elif PDF_VIEWER_AVAILABLE and QPdfDocument is not None:
            self._doc = QPdfDocument(self)
            self._viewer = PdfViewer(
                on_page_changed=self.notify_page_changed,
                parent=self,
            )
            self._viewer.on_selection_changed = self._report_selection
            outer.addWidget(self._viewer, 1)
            self._fallback_label = None
        else:
            self._viewer = None
            self._doc = None
            self._fallback_label = QLabel(
                "PDF viewer is unavailable on this Anki build.\n"
                "Klaus will still index it for curation and retention scoring.",
                self,
            )
            self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._fallback_label.setWordWrap(True)
            outer.addWidget(self._fallback_label, 1)

        # Transcript strip (Plan 2 D6, K-258): a Qt widget under the page
        # for the native renderer; pdf.js draws its own copy of this same
        # strip INSIDE the page via the bridge instead (set_transcript
        # below dispatches on which one applies). Every attribute exists
        # — as None — even when the strip cannot be built, matching this
        # file's own convention for optional UI (the find bar, the
        # thumbnail strip above).
        self._transcript: QWidget | None = None
        self._transcript_chevron: QToolButton | None = None
        self._transcript_scroll: QScrollArea | None = None
        self._transcript_label: QLabel | None = None
        self._transcript_unsubscribe: Callable[[], None] | None = None
        if self._renderer != "pdfjs":
            try:
                self._build_transcript_strip(outer)
            except Exception as exc:
                print(f"[klausmate] transcript strip unavailable: {exc}")
        try:
            from . import page_store as _page_store

            self._transcript_unsubscribe = _page_store.subscribe(
                self._on_page_store_notify
            )
        except Exception as exc:
            print(f"[klausmate] transcript subscribe failed: {exc}")

    def _build_transcript_strip(self, outer: QVBoxLayout) -> None:
        """Build the collapsible native-renderer transcript strip
        (hidden until ``set_transcript`` has text to show): a
        "Transcript" chevron over a capped-height ``QScrollArea``
        holding the page's spoken-over text. Steals no focus and binds
        no shortcut of its own — a plain checkable button and a plain
        label."""
        from . import theme as _theme

        strip = QWidget(self)
        strip.setObjectName("KlausTranscriptStrip")
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        strip.setStyleSheet(_theme.transcript_strip_qss(_theme.night_mode()))
        lay = QVBoxLayout(strip)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(2)

        chevron = QToolButton(strip)
        chevron.setCheckable(True)
        chevron.setChecked(True)
        chevron.setText("▾ Transcript")
        chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        chevron.setAutoRaise(True)
        # Fix round 1 (M1): DECLARED, not just defaulted — Qt's own
        # QToolButton default (TabFocus, no click-focus bit) already
        # keeps a mouse click here off the viewer's focus chain, but a
        # default is not an invariant. This file's own established
        # pattern for exactly this "don't let an ancillary widget steal
        # the viewer's shortcuts" concern (see the thumbnail list at
        # `lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)`).
        chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        chevron.toggled.connect(self._on_transcript_chevron_toggled)
        lay.addWidget(chevron)

        scroll = QScrollArea(strip)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(120)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # fix round 1 (M1)
        label = QLabel("", scroll)
        label.setWordWrap(True)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        label.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # fix round 1 (M1)
        scroll.setWidget(label)
        lay.addWidget(scroll)

        strip.setVisible(False)
        outer.addWidget(strip)
        self._transcript = strip
        self._transcript_chevron = chevron
        self._transcript_scroll = scroll
        self._transcript_label = label

    def _on_transcript_chevron_toggled(self, checked: bool) -> None:
        if self._transcript_scroll is not None:
            self._transcript_scroll.setVisible(checked)
        if self._transcript_chevron is not None:
            self._transcript_chevron.setText(
                "▾ Transcript" if checked else "▸ Transcript"
            )

    def set_transcript(self, page_index: int, text: str) -> None:
        """Show *text* as *page_index*'s transcript: the native strip
        when this sidebar built one, or (pdf.js) push it into the page
        itself over the bridge — the ``klausSetTranscript`` call.
        ``page_index`` mirrors that bridge call's own signature;
        callers (``_refresh_transcript``, the page_store subscription)
        already only reach this for the sidebar's own current page.
        """
        text = str(text or "").strip()
        if self._transcript is not None and self._transcript_label is not None:
            self._transcript_label.setText(text)
            self._transcript.setVisible(bool(text))
            return
        if self._renderer == "pdfjs" and self._viewer is not None:
            try:
                self._viewer.set_transcript(page_index, text)
            except Exception as exc:
                print(f"[klausmate] pdfjs transcript push failed: {exc}")

    def _refresh_transcript(self) -> None:
        """Pull the current page's transcript out of page_store and
        show it (or hide the strip when there is none) — the one path
        both a page change and a page_store notification for this
        PDF funnel through. The SLIDE text is deliberately excluded:
        this strip is what was SAID over the page, not the page itself."""
        text = ""
        if self._name is not None:
            try:
                from . import page_store as _page_store
                from . import pdf_handler as _pdf_handler
                from . import USER_FILES  # type: ignore

                path = _pdf_handler.pdf_path_for(USER_FILES, self._name) or ""
                rec = _page_store.load_record(
                    USER_FILES, self._name, path, self._current_page
                )
                text = "\n".join(
                    str(seg.get("text") or "").strip()
                    for seg in rec.get("segments") or []
                    if str(seg.get("text") or "").strip()
                )
            except Exception as exc:
                print(f"[klausmate] transcript refresh failed: {exc}")
                text = ""
        self.set_transcript(self._current_page, text)

    def _on_page_store_notify(self, pdf_safe: str, page_index: int) -> None:
        """page_store.subscribe callback: refresh only for THIS
        sidebar's own PDF and only while the notified page is the one
        actually on screen — a recorder appending a segment to a page
        the user has since scrolled past must not repaint over it.

        Marshalled through _run_on_main (K-257 fix round 1, cross-task):
        page_store.append_segment calls this synchronously, and the
        lecture recorder's Uploader calls append_segment from its own
        daemon worker thread — so, once Task 5 wired a recorder that
        actually appends segments, this callback started touching
        self._transcript/_transcript_label off the main thread. The
        whole body is deferred (not just the widget touch) so the
        pdf_safe/page_index check itself reads the freshest self._name/
        self._current_page at the moment it actually runs, not whatever
        they were on the worker thread a moment earlier.
        """
        def _apply() -> None:
            if pdf_safe == self._name and page_index == self._current_page:
                self._refresh_transcript()

        _run_on_main(_apply)

    def notify_page_changed(self, page: int) -> None:
        self._on_page_changed(page)

    def _report_selection(self, text: str) -> None:
        """Task 10 (K-196): forward a live selection into viewer_context.

        One method wired as BOTH renderers' selection hook (native
        ``on_selection_changed``, pdf.js ``on_selection``) — same
        payload shape (plain text), same registry call, so there is
        only one guarded viewer_context call site to keep in sync.
        """
        try:
            from . import viewer_context

            viewer_context.report_selection(id(self), text)
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def is_loaded(self, name: str | None = None) -> bool:
        if self._name is None or self._page_count <= 0:
            return False
        if name is not None and self._name != name:
            return False
        return True

    def load_pdf(self, name: str) -> None:
        from . import pdf_handler
        from . import USER_FILES  # type: ignore

        path = pdf_handler.pdf_path_for(USER_FILES, name)
        if not path:
            if self._fallback_label is not None:
                self._fallback_label.setText(
                    f"The raw PDF for '{name}' is not stored.\n"
                    "Re-add it via the editor's PDF panel or the Library to enable the viewer."
                )
            self._name = None
            self._file_stat = None
            self._set_active(None)
            self._refresh_transcript()
            return
        self._file_stat = _stat_of(path)

        if self._renderer == "pdfjs" and self._viewer is not None:
            # pdf.js path: the webview loads from bytes; page count
            # arrives async over the bridge (on_count refines the
            # text-pages approximation used until then).
            self._name = name
            # Task 10 (K-196) fix round 1: the name THIS load belongs to,
            # captured now so the eventual async count callback can tell
            # a late count for an abandoned load apart from a fresh one.
            self._pending_count_name = name
            pages_text = pdf_handler.load_pages(USER_FILES, name) or []
            self._page_count = len(pages_text)
            self._viewer.set_page_texts(pages_text)
            self._viewer.on_count = self._on_pdfjs_count
            self._viewer.load_path(path, name)
            # Same contract as the native branch: annotations restore
            # right after the document feed (the viewer re-pushes them
            # on the page's async "ready", so ordering is safe).
            try:
                self._viewer.load_annotations(name)
            except Exception as exc:
                print(f"[klausmate] annotations restore failed: {exc}")
            self._on_page_changed(0)
            self._notify_loaded(name)
            return

        if not PDF_VIEWER_AVAILABLE or self._doc is None:
            self._name = name
            pages = pdf_handler.load_pages(USER_FILES, name) or []
            self._page_count = len(pages)
            if self._page_count > 0:
                self._set_active((name, (0, min(2, self._page_count - 1))))
            self._refresh_transcript()  # fix round 1 (M2)
            self._notify_loaded(name)
            return

        try:
            self._doc.load(path)
        except Exception:
            try:
                self._doc.load(QUrl.fromLocalFile(path))
            except Exception:
                self._set_active(None)
                return

        self._name = name
        try:
            self._page_count = int(self._doc.pageCount())
        except Exception:
            self._page_count = 0

        pages_text = pdf_handler.load_pages(USER_FILES, name) or []
        if self._viewer is not None:
            self._viewer.set_page_texts(pages_text)
            self._viewer.set_document(self._doc)
            # Persistent highlights (plan B) — right after set_document,
            # which just reset them for the previous tab's document.
            try:
                self._viewer.load_annotations(name)
            except Exception as exc:
                print(f"[klausmate] annotations restore failed: {exc}")
        self._on_page_changed(0)
        self._notify_loaded(name)

    def _on_pdfjs_count(self, count: int) -> None:
        """Task 10 (K-196) fix round 1: the async pdf.js count refines
        the text-layer estimate report_document (already fired from
        _notify_loaded) used — but this callback is registered once per
        load and can still arrive AFTER the sidebar has moved on to a
        different document (a fast reload-before-count race). Guarded on
        IDENTITY, not presence: self._name == self._pending_count_name
        is "this count still belongs to the document that is actually
        showing", not just "some document happens to be loaded". A
        stale count is a complete no-op — it must not touch
        self._page_count (that would be reporting a foreign page count
        as this sidebar's own) and, critically, must not call
        viewer_context.activate() or reset page/selection the way a
        full _report_document() re-call would: it goes through the
        narrower report_page_count instead, which touches only
        page_count in place."""
        if count > 0 and self._name and self._name == self._pending_count_name:
            self._page_count = count
            try:
                from . import viewer_context

                viewer_context.report_page_count(id(self), self._page_count)
            except Exception as exc:
                print(f"[klausmate] viewer_context: {exc}")

    def _report_document(self) -> None:
        """Task 10 (K-196): tell viewer_context which document this
        sidebar shows and mark it the active one. Called once a
        document is actually on screen (every load_pdf success path
        funnels through _notify_loaded). _on_pdfjs_count's later,
        narrower catch-up goes through report_page_count instead — see
        its own docstring for why re-calling this one would be wrong."""
        try:
            from . import drive_store, pdf_handler, viewer_context
            from . import USER_FILES  # type: ignore

            display = drive_store.display_name(USER_FILES, self._name) or self._name
            path = pdf_handler.pdf_path_for(USER_FILES, self._name) or ""
            viewer_context.report_document(
                id(self), self._name, display, path, self._page_count
            )
            viewer_context.activate(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def _notify_loaded(self, name: str) -> None:
        self._report_document()
        cb = self.on_loaded
        if cb is None:
            return
        try:
            cb(name)
        except Exception:
            pass

    def reload_if_externally_changed(self) -> None:
        """React to the shown PDF changing on disk (K-078/K-082).

        An annotation-only edit (page count unchanged — the common
        Preview case) mirrors the records WITHOUT reloading the
        document: the viewer never renders the annotation layer, so the
        page pixels are identical and a reload would only flicker. A
        page-count change means real content editing and does the full
        reload. Cheap no-op when nothing changed. Never raises."""
        try:
            try:
                self.isVisible()
            except RuntimeError:
                return  # C++ side already deleted
            name = self._name
            if name is None or self._file_stat is None:
                return
            from . import pdf_handler
            from . import USER_FILES  # type: ignore

            path = pdf_handler.pdf_path_for(USER_FILES, name)
            if not path:
                return
            st = _stat_of(path)
            if st is None or st == self._file_stat:
                return
            self._file_stat = st
            v = self._viewer
            if v is None or not getattr(
                pdf_handler, "BAKE_AVAILABLE", False
            ):
                self._full_external_reload(name)
                return

            def _worker() -> None:
                try:
                    res = pdf_handler.scan_working_annotations(
                        USER_FILES, name
                    )
                    if res is None:
                        return
                    if int(res.get("page_count") or 0) != int(
                        self._page_count or 0
                    ):
                        _run_on_main(
                            lambda: self._full_external_reload(name)
                        )
                        return
                    if res.get("foreign"):
                        working = pdf_handler._working_pdf_path(
                            USER_FILES, name
                        )
                        if not pdf_handler._capture_pristine_stripped(
                            USER_FILES, name, working
                        ):
                            return
                    _run_on_main(lambda: v._apply_mirror(name, res))
                except Exception as exc:
                    print(f"[klausmate] external mirror failed: {exc}")

            threading.Thread(
                target=_worker, name="klausmate-extmirror", daemon=True
            ).start()
        except Exception as exc:
            print(f"[klausmate] external reload failed: {exc}")

    def _full_external_reload(self, name: str) -> None:
        """Content actually changed: reload the document, keeping the
        reader's scroll position."""
        try:
            try:
                self.isVisible()
            except RuntimeError:
                return
            if self._name != name:
                return
            print(
                f"[klausmate] {name} changed on disk — reloading viewer"
            )
            pos = None
            try:
                if self._viewer is not None:
                    pos = self._viewer.scroll_position()
            except Exception:
                pos = None
            self.load_pdf(name)
            if pos is not None and self._viewer is not None:
                v = self._viewer
                gen = getattr(v, "_doc_generation", None)
                saved = pos

                def _restore() -> None:
                    try:
                        if getattr(v, "_doc_generation", None) == gen:
                            v.restore_scroll_position(saved)
                    except Exception:
                        pass

                try:
                    QTimer.singleShot(0, _restore)
                except Exception:
                    pass
        except Exception as exc:
            print(f"[klausmate] external reload failed: {exc}")

    def jump_to_page(self, page: int) -> None:
        if self._viewer is None or self._page_count <= 0:
            return
        page = max(0, min(int(page), self._page_count - 1))
        self._viewer.go_to_page(page)

    def cleanup(self) -> None:
        """Release renderer resources before this widget tree is
        destroyed. Duck-typed: only the pdf.js renderer needs it (it
        owns an AnkiWebView, which must be unregistered from Anki's
        global hooks — see PdfJsViewer.cleanup); QPdfView has nothing
        to release. Call from every path that tears a sidebar down."""
        v = self._viewer
        fn = getattr(v, "cleanup", None) if v is not None else None
        if fn is not None:
            try:
                fn()
            except Exception as exc:
                print(f"[klausmate] viewer cleanup failed: {exc}")
        unsub, self._transcript_unsubscribe = self._transcript_unsubscribe, None
        if unsub is not None:
            try:
                unsub()
            except Exception as exc:
                print(f"[klausmate] transcript unsubscribe failed: {exc}")
        try:
            from . import viewer_context

            viewer_context.forget(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def clear(self) -> None:
        self._name = None
        self._page_count = 0
        self._current_page = 0
        if self._viewer is not None:
            self._viewer.clear_document()
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
        self._set_active(None)
        self._refresh_transcript()
        try:
            from . import viewer_context

            viewer_context.forget(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def _on_page_changed(self, page: int) -> None:
        if self._name is None or self._page_count <= 0:
            return
        try:
            page = int(page)
        except (TypeError, ValueError):
            return
        last = max(0, self._page_count - 1)
        start = max(0, page - 1)
        end = min(last, page + 1)
        self._current_page = max(0, min(page, last))
        self._set_active((self._name, (start, end)))
        self._refresh_transcript()
        try:
            from . import viewer_context

            viewer_context.report_page(id(self), self._current_page)
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def _set_active(self, value) -> None:
        if self._editor is None:
            return
        try:
            setattr(self._editor, "_klausmate_active_pdf", value)
        except Exception:
            pass

    def showEvent(self, ev) -> None:  # noqa: N802
        # Task 10 (K-196): the assistant dock follows viewer_context's
        # last-ACTIVATED viewer — the Library's, Browse's editor pane and
        # the Lecture dock all reuse this one widget, so becoming visible
        # (a tab switch, an unhide) is "the user is looking at this one"
        # regardless of which host it lives in.
        super().showEvent(ev)
        try:
            from . import viewer_context

            viewer_context.activate(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        # Same seam as showEvent: a click into an already-visible sidebar
        # (e.g. the user switches focus between two open panes without
        # either one being re-shown) still moves it to "current".
        super().mousePressEvent(ev)
        try:
            from . import viewer_context

            viewer_context.activate(id(self))
        except Exception as exc:
            print(f"[klausmate] viewer_context: {exc}")
