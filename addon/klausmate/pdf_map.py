"""Embedding map window (K-123, Phase D2) — the pan/zoom canvas over
``pdf_graph.build_graph_data``'s node/edge dict.

Phase D1 shipped the data: ``projection.py`` (top-2 PCA, pure stdlib) and
``pdf_graph.build_graph_data(user_files, cfg)`` assembling ``{"pdfs",
"notes", "edges"}`` from on-disk caches only. This module is the window:
notes as faint dots, PDFs as accent circles sized by match_count, edges
drawn ONLY for the hovered/selected PDF (readability + perf at ~4000
notes), hover tooltips, left-drag pan, wheel zoom anchored at the cursor,
and a Fit reset.

Everything above the "aqt glue" divider is pure and aqt-free — the whole
viewport model (world<->screen transform, fit-to-view, zoom-at-cursor,
hit-test, node sizing, edge-subset policy, and the count-aware label
level-of-detail + off-node label placement) —
for ``tests/test_pdf_map.py``. The glue imports aqt lazily inside its
functions (retention_history's pattern), so importing this module never
needs Qt at all.

Coordinate note: the K-058 cards describe node positions as normalized to
the unit square, but ``projection._normalize_axis`` actually emits each
axis in [-1, 1] and ``pdf_graph`` passes those through untouched. The
viewport model is deliberately range-agnostic — ``graph_bounds`` measures
the real bounding box of the data and ``fit_to_view`` works from that, so
either convention (or a future change between them) renders correctly.
``DEFAULT_BOUNDS`` (the empty-graph fallback) matches what projection
emits today.

House rules honoured here (each pinned by test): the window is shown with
``show()`` and NEVER ``exec()`` (K-114 — app-modal exec's nested event
loop is the proven macOS 26 segfault class); the one ``paintEvent`` wraps
its drawing in try/except with a ``finally: painter.end()`` (K-115 — a
QPainter left live on an exception corrupts the backing store and
segfaults Qt's next flush); every colour comes from ``theme.palette``
tokens or alpha-adjusted copies of them, never invented literals; and the
window is a module singleton with ``WA_DeleteOnClose`` whose
``closeEvent`` clears the singleton. Fronting an already-open window uses
``raise_()`` only — never activateWindow, even on explicit user action
(the reviewer's answer keys must stay where they are; lecture_view's
rule).

Entry point: ``open_map_window(parent=None)``. Nothing registers it yet —
the Library toolbar button arrives as K-124 on pdf_drive.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# ── viewport model ───────────────────────────────────────────────────────

# Empty-graph fallback bounds — projection normalizes each axis to [-1, 1].
DEFAULT_BOUNDS = (-1.0, -1.0, 1.0, 1.0)
# Pixels of breathing room fit_to_view leaves around the content bounds.
FIT_MARGIN = 48.0
# Sanity clamps on the zoom scale (pixels per world unit). Wide on
# purpose: they exist so a runaway wheel loop can't drive the transform
# into degeneracy, not to constrain normal use.
MIN_SCALE = 1.0
MAX_SCALE = 1_000_000.0
# PDF node radius: NODE_R_MIN + NODE_R_SPREAD * sqrt(match_count),
# clamped into [NODE_R_MIN, NODE_R_MAX] — sqrt so a 400-match monster
# doesn't eat the map, clamps so 0 matches still shows a visible dot.
NODE_R_MIN = 5.0
NODE_R_MAX = 22.0
NODE_R_SPREAD = 1.2
NOTE_DOT_R = 1.6
# Hover/click hit tolerance added on top of the largest node radius.
HIT_SLOP = 4.0
# Above LABEL_MAX_NODES PDFs, labels appear once zoomed in past
# LABEL_ZOOM x the fit scale. At or below it every node is named at
# EVERY zoom, fit included (K-133) — see labels_visible.
LABEL_ZOOM = 1.4
LABEL_MAX_NODES = 12
# Gap in px between a node's edge and its label box. Sized to clear the
# selected node's ring (drawn at r + 3 with a 2px pen, so outer edge
# r + 4) with daylight left over.
LABEL_GAP = 9.0
# Baseline nudge that sits an 11px label on the node's centre line.
LABEL_BASELINE_DY = 4.0
EDGE_ALPHA = 0.25
# One standard wheel notch (angleDelta 120) zooms by 2**(120/240) ≈ 1.41.
WHEEL_ZOOM_DIVISOR = 240.0

EMPTY_TEXT = "No indexed PDFs to map yet."
# The header's one-line affordance (K-133): the offscreen-render audit
# found a view that named nothing and explained nothing — no hint that
# dots are notes, circles PDFs, or that the canvas pans and zooms.
HINT_TEXT = (
    "Circles are PDFs, dots are notes — hover to trace, "
    "drag to pan, scroll to zoom"
)


@dataclass(frozen=True)
class Viewport:
    """World -> screen affine transform: ``screen = offset + world * scale``.

    ``scale`` is pixels per world unit; ``(ox, oy)`` is the screen
    position of the world origin. Frozen — every mutation below returns a
    new Viewport, which is what makes the math trivially testable.
    """

    scale: float = 1.0
    ox: float = 0.0
    oy: float = 0.0


def world_to_screen(vp: Viewport, wx: float, wy: float) -> tuple:
    return (vp.ox + float(wx) * vp.scale, vp.oy + float(wy) * vp.scale)


def screen_to_world(vp: Viewport, sx: float, sy: float) -> tuple:
    if vp.scale <= 0:
        return (0.0, 0.0)
    return ((float(sx) - vp.ox) / vp.scale, (float(sy) - vp.oy) / vp.scale)


def pan_by(vp: Viewport, dx: float, dy: float) -> Viewport:
    return Viewport(vp.scale, vp.ox + float(dx), vp.oy + float(dy))


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _num(value: object, default: float = 0.0) -> float:
    """``float(value)``, with ``default`` for junk and for NaN — the
    paint path must never raise on one malformed row."""
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return default if f != f else f


def fit_to_view(
    bounds: Sequence[float],
    widget_size: Sequence[float],
    margin: float = FIT_MARGIN,
) -> Viewport:
    """Viewport that centers ``bounds`` in ``widget_size`` with ``margin``
    px of breathing room on the constraining axis.

    Degenerate inputs never divide by zero: a zero-span axis (a single
    node, or a perfectly vertical/horizontal cloud) is treated as span
    1.0 for the scale choice while the true center is still honoured, and
    a widget smaller than twice the margin falls back to a 1px working
    area rather than a negative one.
    """
    min_x, min_y, max_x, max_y = (float(v) for v in bounds)
    w = float(widget_size[0])
    h = float(widget_size[1])
    m = float(margin)
    span_x = max_x - min_x
    span_y = max_y - min_y
    if span_x <= 0:
        span_x = 1.0
    if span_y <= 0:
        span_y = 1.0
    avail_w = max(1.0, w - 2.0 * m)
    avail_h = max(1.0, h - 2.0 * m)
    scale = _clamp(min(avail_w / span_x, avail_h / span_y), MIN_SCALE, MAX_SCALE)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    return Viewport(scale, w / 2.0 - cx * scale, h / 2.0 - cy * scale)


def zoom_at(vp: Viewport, cursor: Sequence[float], factor: float) -> Viewport:
    """Rescale, keeping the world point under ``cursor`` fixed on screen.

    Derivation: a screen point c and viewport (s, o) name the world point
    w = (c - o) / s. For w to stay under c after rescaling to s', solve
    c = o' + w * s' for the new offset:

        o' = c - w * s' = c - (c - o) * (s' / s)

    i.e. the offset moves toward the cursor by exactly the scale ratio.
    The ratio is computed from the CLAMPED new scale, so the fixed-point
    property holds even when the clamp bites (at the limit the ratio is
    1.0 and the viewport is returned unchanged).
    """
    old = vp.scale
    new = _clamp(old * float(factor), MIN_SCALE, MAX_SCALE)
    if old <= 0:
        return Viewport(new, vp.ox, vp.oy)
    ratio = new / old
    cx = float(cursor[0])
    cy = float(cursor[1])
    return Viewport(new, cx - (cx - vp.ox) * ratio, cy - (cy - vp.oy) * ratio)


# ── nodes: sizing, hit-testing, bounds ───────────────────────────────────


def node_radius(match_count: object) -> float:
    """PDF node radius in px from its match count, with sane clamps —
    garbage counts read as 0 rather than raising mid-paint."""
    try:
        n = float(match_count)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = 0.0
    if n < 0 or n != n:  # negative or NaN
        n = 0.0
    r = NODE_R_MIN + NODE_R_SPREAD * math.sqrt(n)
    return _clamp(r, NODE_R_MIN, NODE_R_MAX)


def hit_test(
    nodes: Iterable[Sequence], screen_pt: Sequence[float], radius: float
) -> Optional[object]:
    """The key of the nearest node within ``radius`` px of ``screen_pt``,
    or None. ``nodes`` is an iterable of ``(key, sx, sy)``; the radius
    boundary is inclusive; ties keep the first-seen node."""
    try:
        px = float(screen_pt[0])
        py = float(screen_pt[1])
        r = float(radius)
    except (TypeError, ValueError, IndexError):
        return None
    if r < 0:
        return None
    best = None
    best_d2 = r * r
    for key, sx, sy in nodes:
        try:
            dx = float(sx) - px
            dy = float(sy) - py
        except (TypeError, ValueError):
            continue
        d2 = dx * dx + dy * dy
        if best is None:
            if d2 <= best_d2:
                best = key
                best_d2 = d2
        elif d2 < best_d2:
            best = key
            best_d2 = d2
    return best


def parse_xy(value: object) -> Optional[tuple]:
    """``[x, y]`` -> ``(float, float)``; None for anything malformed."""
    try:
        x = float(value[0])  # type: ignore[index]
        y = float(value[1])  # type: ignore[index]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if x != x or y != y:  # NaN never gets a position
        return None
    return (x, y)


def bounds_of(
    points: Iterable[Sequence], fallback: Sequence[float] = DEFAULT_BOUNDS
) -> tuple:
    """Bounding box ``(min_x, min_y, max_x, max_y)`` of ``points``;
    ``fallback`` when no point parses. Malformed points are skipped, not
    fatal — one bad row must never blank the whole map."""
    xs: list = []
    ys: list = []
    for p in points:
        xy = parse_xy(p)
        if xy is not None:
            xs.append(xy[0])
            ys.append(xy[1])
    if not xs:
        return tuple(float(v) for v in fallback)
    return (min(xs), min(ys), max(xs), max(ys))


def graph_bounds(graph: dict) -> tuple:
    """Bounding box over every positioned note AND pdf node in a
    ``build_graph_data`` dict (pdf centroids always lie inside the note
    cloud today, but measuring both keeps that a fact, not a load-bearing
    assumption)."""
    pts = []
    for row in list(graph.get("notes") or []) + list(graph.get("pdfs") or []):
        if isinstance(row, dict):
            pts.append(row.get("xy"))
    return bounds_of(pts)


# ── selection / level-of-detail policy ───────────────────────────────────


def active_pdf(hover: Optional[str], selected: Optional[str]) -> Optional[str]:
    """Which PDF owns the edge display: the hover preview while there is
    one, the sticky selection otherwise."""
    return hover if hover is not None else selected


def edges_for_selection(edges: Iterable[dict], selected: Optional[str]) -> list:
    """The subset of ``edges`` to draw: ONLY the hovered/selected PDF's
    (readability + perf — all edges at once is hairball noise), empty
    when nothing is active."""
    if not selected:
        return []
    return [e for e in edges if isinstance(e, dict) and e.get("pdf") == selected]


def labels_visible(
    scale: float, fit_scale: float, pdf_count: Optional[int] = None
) -> bool:
    """Level-of-detail for PDF display names — COUNT-aware, not zoom-only.

    K-133: the zoom-only rule (names past ``LABEL_ZOOM`` x the fit
    scale) meant the map opened as anonymous dots, because fit is the
    only view you get on open — a map whose whole job is "which PDF
    sits where" that named nothing at the one view it shows. So a graph
    of at most ``LABEL_MAX_NODES`` PDFs is named at EVERY zoom, fit
    included: a dozen names over the cloud is a legend, not clutter.
    Above that count the zoom gate stands, and the active
    (hovered/selected) node is labelled unconditionally by the painter
    either way.

    ``pdf_count`` None means "count unknown" and keeps the pure zoom
    gate; a degenerate fit scale shows labels rather than hiding them
    forever.
    """
    if pdf_count is not None:
        try:
            n = int(pdf_count)
        except (TypeError, ValueError):
            n = -1
        if 0 <= n <= LABEL_MAX_NODES:
            return True
    if fit_scale <= 0:
        return True
    return scale >= fit_scale * LABEL_ZOOM


def label_anchor(
    sx: float,
    sy: float,
    radius: float,
    text_width: float = 0.0,
    view_width: Optional[float] = None,
    gap: float = LABEL_GAP,
) -> tuple:
    """Text-baseline anchor ``(x, y)`` for a node's label.

    The name sits BESIDE its node, never on it: x clears ``radius`` by
    ``gap`` (which also clears the selected node's ring), on the right
    by default and mirrored to the left when ``text_width`` would run
    the label past ``view_width``. When neither side fits — a name
    wider than the viewport — the right-hand placement wins, so the
    start of the name stays readable instead of its tail. y sits on the
    node's centre line. Junk coordinates degrade to 0.0 rather than
    raising mid-paint.
    """
    x = _num(sx)
    y = _num(sy)
    r = abs(_num(radius))
    g = _num(gap, LABEL_GAP)
    tw = max(0.0, _num(text_width))
    baseline = y + LABEL_BASELINE_DY
    right = x + r + g
    if view_width is not None:
        vw = _num(view_width)
        left = x - r - g - tw
        if vw > 0.0 and right + tw > vw and left >= 0.0:
            return (left, baseline)
    return (right, baseline)


def tooltip_text(pdf: dict) -> str:
    """Hover tooltip body: display name, folder when filed, match count,
    retention only when actually known (headless graphs carry None)."""
    lines = [str(pdf.get("display") or pdf.get("safe") or "PDF")]
    folder = pdf.get("folder")
    if folder:
        lines.append(f"Folder: {folder}")
    try:
        count = int(pdf.get("match_count") or 0)
    except (TypeError, ValueError):
        count = 0
    lines.append(f"Matched notes: {count}")
    r = pdf.get("retention")
    if isinstance(r, (int, float)) and not isinstance(r, bool):
        lines.append(f"Retention: {round(float(r) * 100.0)}%")
    return "\n".join(lines)


# ── aqt glue ─────────────────────────────────────────────────────────────
# Imported lazily inside the functions below (retention_history's
# pattern) so importing this module never needs Qt at all.

_instance = None  # the one open MapWindow; closeEvent clears it


def _addon_cfg() -> dict:
    """The addon config, or {} — never a stub/dummy object."""
    try:
        from aqt import mw

        cfg = mw.addonManager.getConfig(__package__) if mw is not None else None
        return cfg if isinstance(cfg, dict) else {}
    except Exception as exc:
        print(f"[klausmate] map config read failed: {exc}")
        return {}


def _load_graph() -> dict:
    """``build_graph_data`` over the live user_files, degrading to an
    empty graph — the map opening must never raise into the caller."""
    try:
        from . import curation, pdf_graph

        graph = pdf_graph.build_graph_data(curation.USER_FILES, _addon_cfg())
        if isinstance(graph, dict):
            return graph
    except Exception as exc:
        print(f"[klausmate] map graph build failed: {exc}")
    return {"pdfs": [], "notes": [], "edges": []}


def _fill_retention(graph: dict) -> None:
    """Best-effort live retention for each PDF node, in place.

    ``build_graph_data`` always leaves ``retention`` None (FSRS
    retrievability needs a collection). With one open, the graph's edges
    ARE each PDF's at-threshold matches, so one batched
    ``card_retrievability`` call over every edge nid plus the existing
    ``pdf_retention`` aggregate fills the number without re-scoring
    anything. Any failure leaves None — the tooltip simply omits the
    line (do NOT redesign retention.py for this).
    """
    try:
        from aqt import mw

        col = getattr(mw, "col", None) if mw is not None else None
        if col is None:
            return
        # Under the stub harness col is a permissive dummy, not None —
        # every call below sits inside this try, so that path degrades
        # to the printed failure line rather than a crash.
        from . import retention

        edges = [e for e in graph.get("edges") or [] if isinstance(e, dict)]
        nids = {int(e["nid"]) for e in edges if "nid" in e}
        if not nids:
            return
        card_r = retention.card_retrievability(col, nids)
        by_pdf: dict = {}
        for e in edges:
            try:
                by_pdf.setdefault(str(e["pdf"]), []).append(
                    (int(e["nid"]), float(e["score"]))
                )
            except (TypeError, ValueError, KeyError):
                continue
        for p in graph.get("pdfs") or []:
            if not isinstance(p, dict):
                continue
            matches = by_pdf.get(str(p.get("safe")))
            if not matches:
                continue
            stats = retention.pdf_retention(
                matches, float(p.get("threshold") or 0.0), card_r
            )
            p["retention"] = stats.get("retention")
    except Exception as exc:
        print(f"[klausmate] map retention fill failed: {exc}")


def open_map_window(parent=None):
    """Open (or front) the Embedding Map window; returns it or None.

    Module singleton: a second call fronts the existing window with
    ``show()`` + ``raise_()`` (explicit user action — pdf_drive's
    precedent, minus its focus steal). The window deletes on close and
    ``closeEvent`` clears the singleton, so a reopened map is always
    freshly built from the current graph.
    """
    global _instance
    if _instance is not None:
        try:
            _instance.show()
            _instance.raise_()
            return _instance
        except Exception as exc:
            # Stale after a C++-side delete (RuntimeError) — rebuild.
            print(f"[klausmate] map re-front failed, rebuilding: {exc}")
            _instance = None

    try:
        from aqt.qt import (
            QColor,
            QHBoxLayout,
            QLabel,
            QPainter,
            QPainterPath,
            QPen,
            QPointF,
            QPushButton,
            QRectF,
            Qt,
            QToolTip,
            QVBoxLayout,
            QWidget,
        )

        from . import theme
    except Exception as exc:
        print(f"[klausmate] embedding map unavailable: {exc}")
        return None

    graph = _load_graph()
    _fill_retention(graph)

    class _MapCanvas(QWidget):
        """The QPainter canvas: the whole renderer, hand-painted (no
        QtCharts/QGraphicsView in Anki's bundle worth dragging in for
        dots and lines). Colours re-read theme.palette per paint so a
        night flip catches up on the next repaint."""

        def __init__(self, graph_dict: dict, parent_widget=None) -> None:
            super().__init__(parent_widget)
            self._notes: list = []
            self._note_xy: dict = {}
            self._pdfs: list = []
            self._pdf_xy: dict = {}
            self._pdf_by_safe: dict = {}
            self._edges: list = []
            for n in graph_dict.get("notes") or []:
                if not isinstance(n, dict):
                    continue
                xy = parse_xy(n.get("xy"))
                if xy is None:
                    continue
                self._notes.append(xy)
                try:
                    self._note_xy[int(n.get("nid"))] = xy
                except (TypeError, ValueError):
                    continue
            for p in graph_dict.get("pdfs") or []:
                if not isinstance(p, dict):
                    continue
                xy = parse_xy(p.get("xy"))
                safe = p.get("safe")
                if xy is None or not safe:
                    continue
                self._pdfs.append(p)
                self._pdf_xy[str(safe)] = xy
                self._pdf_by_safe[str(safe)] = p
            self._edges = [
                e for e in graph_dict.get("edges") or [] if isinstance(e, dict)
            ]
            self._bounds = graph_bounds(graph_dict)
            self._hit_radius = (
                max(node_radius(p.get("match_count")) for p in self._pdfs)
                if self._pdfs
                else NODE_R_MIN
            ) + HIT_SLOP

            self._vp = Viewport()
            self._fit_scale = 1.0
            self._did_fit = False
            self._hover = None
            self._selected = None
            self._dragging = False
            self._drag_moved = False
            self._drag_last = None
            try:
                self.setMouseTracking(True)
                self.setMinimumSize(480, 360)
            except Exception as exc:
                print(f"[klausmate] map canvas setup failed: {exc}")

        # ---- viewport ----

        def _apply_fit(self, w: float, h: float) -> None:
            vp = fit_to_view(self._bounds, (w, h), FIT_MARGIN)
            self._vp = vp
            self._fit_scale = vp.scale
            self._did_fit = True

        def _ensure_fit(self, w: float, h: float) -> None:
            if not self._did_fit and w > 1 and h > 1:
                self._apply_fit(w, h)

        def fit(self) -> None:
            """The Fit button / reset: re-center the whole graph."""
            try:
                self._apply_fit(float(self.width()), float(self.height()))
                self.update()
            except Exception as exc:
                print(f"[klausmate] map fit failed: {exc}")

        # ---- painting ----

        def paintEvent(self, _event) -> None:  # noqa: N802 — Qt override
            # No surface yet = nothing safe to paint on.
            if self.width() <= 0 or self.height() <= 0:
                return
            painter = QPainter(self)
            try:
                self._paint(painter)
            except Exception as exc:
                # A drawing bug degrades to "the map didn't draw", never
                # to an exception escaping mid-paint.
                print(f"[klausmate] map paint failed: {exc}")
            finally:
                # ALWAYS close the painter (K-115): a QPainter left live
                # on an exception corrupts the backing store and
                # segfaults Qt's next flush.
                painter.end()

        def _paint(self, painter) -> None:
            c = theme.palette(theme.night_mode())
            w = float(self.width())
            h = float(self.height())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # The house dialog card (retention_history's language):
            # surface fill, hairline border, 12px radius; content clipped
            # to the card so panned nodes never spill past the corners.
            card = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
            painter.setPen(QPen(QColor(c["grey_light"]), 1.0))
            painter.setBrush(QColor(c["surface"]))
            painter.drawRoundedRect(card, 12.0, 12.0)
            clip = QPainterPath()
            clip.addRoundedRect(card, 12.0, 12.0)
            painter.setClipPath(clip)

            self._ensure_fit(w, h)
            vp = self._vp

            # Notes: small dots in a muted token, viewport-culled.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["grey_mid"]))
            pad = NOTE_DOT_R * 2.0
            for wx, wy in self._notes:
                sx, sy = world_to_screen(vp, wx, wy)
                if -pad <= sx <= w + pad and -pad <= sy <= h + pad:
                    painter.drawEllipse(QPointF(sx, sy), NOTE_DOT_R, NOTE_DOT_R)

            # Edges: ONLY the hovered/selected PDF's (the whole point of
            # edges_for_selection — every edge at once is a hairball).
            active = active_pdf(self._hover, self._selected)
            if active and active in self._pdf_xy:
                edge_col = QColor(c["blue_accent"])
                edge_col.setAlphaF(EDGE_ALPHA)
                painter.setPen(QPen(edge_col, 1.0))
                ax, ay = world_to_screen(vp, *self._pdf_xy[active])
                for e in edges_for_selection(self._edges, active):
                    try:
                        nxy = self._note_xy.get(int(e.get("nid")))
                    except (TypeError, ValueError):
                        continue
                    if nxy is None:
                        continue
                    bx, by = world_to_screen(vp, nxy[0], nxy[1])
                    painter.drawLine(QPointF(ax, ay), QPointF(bx, by))

            # PDF nodes: accent circles sized by match_count; labels are
            # level-of-detail (always for the active node).
            show_labels = labels_visible(
                vp.scale, self._fit_scale, len(self._pdfs)
            )
            label_font = painter.font()
            label_font.setPixelSize(11)
            painter.setFont(label_font)
            try:
                metrics = painter.fontMetrics()
            except Exception:
                metrics = None  # widths degrade to 0 -> plain right-hand side
            for p in self._pdfs:
                safe = str(p.get("safe"))
                sx, sy = world_to_screen(vp, *self._pdf_xy[safe])
                r = node_radius(p.get("match_count"))
                if (
                    sx < -2 * r
                    or sx > w + 2 * r
                    or sy < -2 * r
                    or sy > h + 2 * r
                ):
                    continue
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(
                    QColor(c["blue_bright" if safe == self._hover else "blue_accent"])
                )
                painter.drawEllipse(QPointF(sx, sy), r, r)
                if safe == self._selected:
                    painter.setPen(QPen(QColor(c["blue_bright"]), 2.0))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(sx, sy), r + 3.0, r + 3.0)
                if show_labels or safe == active:
                    name = str(p.get("display") or "")
                    if name:
                        try:
                            tw = float(metrics.horizontalAdvance(name))
                        except Exception:
                            tw = 0.0
                        lx, ly = label_anchor(sx, sy, r, tw, w)
                        painter.setPen(QColor(c["text"]))
                        painter.drawText(QPointF(lx, ly), name)

        # ---- mouse ----

        def _screen_nodes(self) -> list:
            vp = self._vp
            out = []
            for safe, xy in self._pdf_xy.items():
                sx, sy = world_to_screen(vp, xy[0], xy[1])
                out.append((safe, sx, sy))
            return out

        def _hit_at(self, px: float, py: float):
            return hit_test(self._screen_nodes(), (px, py), self._hit_radius)

        def _update_hover(self, px: float, py: float, event) -> None:
            hit = self._hit_at(px, py)
            if hit == self._hover:
                return
            self._hover = hit
            self.update()
            try:
                if hit is None:
                    QToolTip.hideText()
                else:
                    p = self._pdf_by_safe.get(hit)
                    if p is not None:
                        QToolTip.showText(
                            event.globalPosition().toPoint(),
                            tooltip_text(p),
                            self,
                        )
            except Exception:
                pass  # tooltips are best-effort chrome

        def mousePressEvent(self, event) -> None:  # noqa: N802
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    pos = event.position()
                    self._dragging = True
                    self._drag_moved = False
                    self._drag_last = (float(pos.x()), float(pos.y()))
            except Exception as exc:
                print(f"[klausmate] map press failed: {exc}")

        def mouseMoveEvent(self, event) -> None:  # noqa: N802
            try:
                pos = event.position()
                px, py = float(pos.x()), float(pos.y())
                if self._dragging and self._drag_last is not None:
                    dx = px - self._drag_last[0]
                    dy = py - self._drag_last[1]
                    if dx or dy:
                        if abs(dx) + abs(dy) >= 2.0:
                            self._drag_moved = True
                        self._vp = pan_by(self._vp, dx, dy)
                        self._drag_last = (px, py)
                        self.update()
                    return
                self._update_hover(px, py, event)
            except Exception as exc:
                print(f"[klausmate] map move failed: {exc}")

        def mouseReleaseEvent(self, event) -> None:  # noqa: N802
            try:
                if event.button() != Qt.MouseButton.LeftButton:
                    return
                was_click = self._dragging and not self._drag_moved
                self._dragging = False
                self._drag_last = None
                if was_click:
                    pos = event.position()
                    self._selected = self._hit_at(
                        float(pos.x()), float(pos.y())
                    )
                    self.update()
            except Exception as exc:
                print(f"[klausmate] map release failed: {exc}")

        def wheelEvent(self, event) -> None:  # noqa: N802
            try:
                delta = float(event.angleDelta().y())
                if not delta:
                    return
                factor = 2.0 ** (delta / WHEEL_ZOOM_DIVISOR)
                pos = event.position()
                self._vp = zoom_at(
                    self._vp, (float(pos.x()), float(pos.y())), factor
                )
                self.update()
            except Exception as exc:
                print(f"[klausmate] map wheel failed: {exc}")

        def leaveEvent(self, event) -> None:  # noqa: N802
            try:
                if self._hover is not None:
                    self._hover = None
                    self.update()
                    QToolTip.hideText()
            except Exception:
                pass
            try:
                super().leaveEvent(event)
            except Exception:
                pass

    class _MapWindow(QWidget):
        """Standalone top-level map window (DriveWindow's shape: a plain
        QWidget window, module-singleton lifecycle)."""

        def __init__(self, graph_dict: dict, parent_widget=None) -> None:
            if parent_widget is not None:
                super().__init__(parent_widget, Qt.WindowType.Window)
            else:
                super().__init__()
            night = theme.night_mode()
            c = theme.palette(night)
            self.setWindowTitle("Embedding Map")
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            except Exception:
                pass
            try:
                self.setObjectName("KlausMapWindow")
                self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                # dialog_qss styles the children (labels, buttons); the
                # one extra rule paints this non-QDialog window's own
                # ground with the same token.
                self.setStyleSheet(
                    theme.dialog_qss(night)
                    + f"\nQWidget#KlausMapWindow {{ background-color: {c['bg']}; }}"
                )
            except Exception as exc:
                print(f"[klausmate] map theme failed: {exc}")

            outer = QVBoxLayout(self)
            outer.setContentsMargins(12, 10, 12, 12)
            outer.setSpacing(8)

            pdfs = graph_dict.get("pdfs") or []
            notes = graph_dict.get("notes") or []
            if not pdfs:
                empty = QLabel(EMPTY_TEXT, self)
                try:
                    empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    empty.setStyleSheet(theme.muted_label_qss(night, 13))
                except Exception:
                    pass
                outer.addWidget(empty, 1)
                self.canvas = None
            else:
                bar = QHBoxLayout()
                bar.setSpacing(8)
                caption = QLabel(
                    f"{len(pdfs)} PDF{'s' if len(pdfs) != 1 else ''} · "
                    f"{len(notes)} note{'s' if len(notes) != 1 else ''}",
                    self,
                )
                try:
                    caption.setStyleSheet(theme.muted_label_qss(night))
                except Exception:
                    pass
                bar.addWidget(caption)
                # ONE quiet affordance line (K-133) — same muted token
                # as the caption, spaced off it so the two read as
                # separate phrases rather than one run-on caption. A
                # plain QLabel's minimum IS its text width, so this
                # raises the window's minimum width (504 -> ~625 at the
                # 11px default); accepted deliberately — the window
                # opens at 900 and a clipped half-sentence would read
                # as broken. Shorten HINT_TEXT before adding widgets.
                bar.addSpacing(10)
                hint = QLabel(HINT_TEXT, self)
                try:
                    hint.setStyleSheet(theme.muted_label_qss(night))
                except Exception:
                    pass
                bar.addWidget(hint)
                bar.addStretch(1)
                fit_btn = QPushButton("Fit", self)
                try:
                    fit_btn.setObjectName("SecondaryButton")
                    fit_btn.setToolTip("Reset zoom to show the whole map")
                except Exception:
                    pass
                bar.addWidget(fit_btn)
                outer.addLayout(bar)
                self.canvas = _MapCanvas(graph_dict, self)
                outer.addWidget(self.canvas, 1)
                try:
                    fit_btn.clicked.connect(self.canvas.fit)
                except Exception as exc:
                    print(f"[klausmate] map fit wire failed: {exc}")

            self.resize(900, 640)

        def closeEvent(self, evt) -> None:  # noqa: N802 — Qt naming
            global _instance
            if _instance is self:
                _instance = None
            try:
                super().closeEvent(evt)
            except Exception:
                pass

    try:
        win = _MapWindow(graph, parent)
        _instance = win
        win.show()  # NEVER exec() — K-114
        win.raise_()
        return win
    except Exception as exc:
        print(f"[klausmate] embedding map open failed: {exc}")
        _instance = None
        return None
