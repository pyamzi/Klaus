"""The Library tree as VS Code's Explorer (K-175).

Pouya (2026-09-01): "make the library panel look like VS Code ... do a
full redesign of it", then a PyQt6 UI-design brief: a 4px grid, colours
only from tokens, both palettes, every widget state, no magic numbers.

What K-117 and K-130 had already settled stays: 22px rows of 13px type,
chevron twisties, the uppercase caption, quiet actions, the accent band.
This adds the part QSS cannot express and the part that makes an
Explorer read as one:

* **Delegate-painted rows.** Column 0 gets a full-cell band (hover or
  selected, the SAME two tokens the sheet paints in the other cells and
  in the branch cell, so a row is one bar), an indent guide at every
  ancestor's twisty column, a hand-drawn folder or page icon, and the
  item's own text painted by the style with its rect stepped past the
  icon. Columns 1-3 are not touched: sorting, tabular figures and the
  K-127 retention ink all live there and all survive.
* **Glyph actions.** VS Code's section actions are 16px icons in 22px
  hit boxes with tooltips, not words. ``GlyphButton`` is that: a
  QToolButton that lets the sheet paint its background and border
  states, then draws one of four glyphs on top.

Everything above the aqt divider is pure (points, rects, token names),
so tests pin the geometry without a QApplication and the painter code
below is a thin translation of it.

**Why hand-drawn icons and not shipped SVGs.** A QSS ``image:`` is one
file in one colour. These icons follow the item's OWN foreground (a
fully suspended PDF dims its icon with its text, K-117) and the active
palette, which is a colour per state per palette per theme. Painting
from points costs nothing and follows every colour theme for free.

**Two paint guards are load-bearing.** A QPainter left live on a widget
because an exception escaped before ``end()`` corrupts the backing
store and Qt segfaults on the next flush (K-115), so ``paintEvent``
ends its painter in a ``finally``. And an exception escaping ANY Qt
virtual (a delegate's ``paint`` included) makes PyQt6 print it and call
``qFatal`` in a bare interpreter, or hand it to Anki's excepthook as a
modal error dialog (K-183) — so ``paint`` never lets one out.
"""

from __future__ import annotations

import math

from . import theme

# ── Geometry, on the 4px grid ────────────────────────────────────────────
GRID = 4
ROW_H = 22             # VS Code's list row: K-117's ask, K-130: do not inflate
INDENT = 16            # the branch cell — one twisty box wide
ICON_BOX = 16          # codicon size
ICON_GAP = 4           # icon → label
CELL_PAD = 4           # cell edge → icon
STROKE = 1.2           # icon outline weight at 16px
GUIDE_STROKE = 1.0     # indent-guide hairline
ACTION_W = 24          # glyph action hit box
ACTION_H = 22
SASH_W = 5             # 1px hairline + a 4px grab, VS Code's sash
BAND_ALPHA = 0.16      # accent band alpha, K-130's SettingsNav value
BAND_BASE = "bg"       # the band is pre-composited over the TREE's ground

KINDS = ("new-folder", "refresh", "map", "fit")


def label_inset() -> int:
    """Where the label starts inside the name cell: past pad, icon, gap."""
    return CELL_PAD + ICON_BOX + ICON_GAP


def guide_xs(depth: int, indent: int = INDENT) -> tuple[int, ...]:
    """x (from the tree's left edge) of each ancestor's indent guide for
    a row at ``depth``: the centre of that ancestor's twisty cell, so a
    child hangs under the chevron of the folder that owns it."""
    return tuple(
        level * indent + indent // 2 for level in range(max(0, int(depth)))
    )


def icon_rect(cell_x: int, cell_y: int, cell_h: int) -> tuple[int, int, int, int]:
    """The 16px icon box, vertically centred in a name cell."""
    return (
        int(cell_x) + CELL_PAD,
        int(cell_y) + (int(cell_h) - ICON_BOX) // 2,
        ICON_BOX,
        ICON_BOX,
    )


def depth_of(index) -> int:
    """How many ancestors a model index has (0 for a top-level row)."""
    depth = 0
    parent = index.parent()
    while parent.isValid():
        depth += 1
        parent = parent.parent()
    return depth


def folder_icon(x: float, y: float) -> tuple[tuple[float, float], ...]:
    """Closed outline of a tabbed folder inside the 16px box at (x, y).
    Half-pixel coordinates on purpose: a 1.2px stroke centred on .5
    fully covers one pixel column, so the edges render crisp."""
    return (
        (x + 1.5, y + 3.5),
        (x + 6.0, y + 3.5),
        (x + 7.5, y + 5.5),
        (x + 14.5, y + 5.5),
        (x + 14.5, y + 13.0),
        (x + 1.5, y + 13.0),
    )


def page_icon(x: float, y: float) -> tuple[tuple[tuple[float, float], ...], ...]:
    """A page with a turned corner: (closed outline, open fold)."""
    outline = (
        (x + 3.5, y + 1.5),
        (x + 9.5, y + 1.5),
        (x + 12.5, y + 4.5),
        (x + 12.5, y + 14.5),
        (x + 3.5, y + 14.5),
    )
    fold = ((x + 9.5, y + 1.5), (x + 9.5, y + 4.5), (x + 12.5, y + 4.5))
    return outline, fold


def glyph(kind: str, x: float, y: float) -> dict:
    """Primitives for one action glyph inside the 16px box at (x, y).

    ``polygons`` are closed, ``polylines`` open, ``lines`` are pairs,
    ``arcs`` are (x, y, w, h, start_deg, span_deg) in Qt's convention
    (counter-clockwise, 0 at three o'clock), ``dots`` are (cx, cy, r).
    """
    if kind == "new-folder":
        return {
            "polygons": [folder_icon(x, y)],
            "lines": [
                ((x + 8.0, y + 7.5), (x + 8.0, y + 11.5)),
                ((x + 6.0, y + 9.5), (x + 10.0, y + 9.5)),
            ],
        }
    if kind == "refresh":
        # A five-unit circle with its gap at the upper right, and an
        # arrowhead on the end that faces up: the arc runs
        # counter-clockwise and ends at three o'clock.
        return {
            "arcs": [(x + 3.0, y + 3.0, 10.0, 10.0, 60.0, 300.0)],
            "polylines": [((x + 10.5, y + 10.5), (x + 13.0, y + 8.0),
                           (x + 15.5, y + 10.5))],
        }
    if kind == "map":
        # Three notes and the two edges between them: K-174's
        # constellation, in miniature.
        a, b, c = (x + 4.0, y + 11.5), (x + 8.5, y + 4.5), (x + 12.5, y + 10.0)
        return {
            "dots": [(a[0], a[1], 1.6), (b[0], b[1], 1.6), (c[0], c[1], 1.6)],
            "lines": [(a, b), (b, c)],
        }
    if kind == "fit":
        return {
            "polylines": [
                ((x + 2.5, y + 6.0), (x + 2.5, y + 2.5), (x + 6.0, y + 2.5)),
                ((x + 10.0, y + 2.5), (x + 13.5, y + 2.5), (x + 13.5, y + 6.0)),
                ((x + 13.5, y + 10.0), (x + 13.5, y + 13.5), (x + 10.0, y + 13.5)),
                ((x + 6.0, y + 13.5), (x + 2.5, y + 13.5), (x + 2.5, y + 10.0)),
            ],
        }
    raise ValueError(f"unknown glyph kind: {kind!r}")


# ── Colour: tokens only ──────────────────────────────────────────────────


def band_colour(selected: bool, hover: bool, night: bool) -> str | None:
    """The row band for column 0, or None for a resting row. The SAME
    two inks the sheet paints in every other cell (theme.library_qss),
    so the delegate cannot drift from the QSS."""
    if selected:
        return theme.accent_mix(night, BAND_ALPHA, base=BAND_BASE)
    if hover:
        return theme.palette(night)["hover_subtle"]
    return None


def ink_colour(night: bool, foreground: str | None = None, enabled: bool = True) -> str:
    """Icon and glyph ink: the item's own foreground when it has one (a
    dimmed row dims its icon), the muted text token otherwise, and the
    faint token for a disabled control."""
    c = theme.palette(night)
    if not enabled:
        return c["text_faint"]
    return foreground or c["text_muted"]


def guide_colour(night: bool) -> str:
    return theme.palette(night)["grey_mid"]


# ═════════════════════════════ aqt glue below this line ═══════════════════

from aqt.qt import (  # noqa: E402
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPointF,
    QRectF,
    QSize,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    Qt,
)


def _path(points, close: bool) -> "QPainterPath":
    path = QPainterPath()
    path.moveTo(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(QPointF(*pt))
    if close:
        path.closeSubpath()
    return path


def _ink_pen(colour: "QColor", width: float) -> "QPen":
    pen = QPen(colour, width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _draw_primitives(painter: "QPainter", prims: dict, ink: "QColor") -> None:
    """Translate :func:`glyph`'s pure primitives into painter calls."""
    painter.setPen(_ink_pen(ink, STROKE))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for poly in prims.get("polygons", ()):
        painter.drawPath(_path(poly, close=True))
    for poly in prims.get("polylines", ()):
        painter.drawPath(_path(poly, close=False))
    for a, b in prims.get("lines", ()):
        painter.drawLine(QPointF(*a), QPointF(*b))
    for (ax, ay, w, h, start, span) in prims.get("arcs", ()):
        painter.drawArc(QRectF(ax, ay, w, h), int(start * 16), int(span * 16))
    if prims.get("dots"):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(ink))
        for cx, cy, r in prims["dots"]:
            painter.drawEllipse(QPointF(cx, cy), r, r)


class ExplorerDelegate(QStyledItemDelegate):  # type: ignore[misc]
    """Paints the Library tree's name column as an Explorer row.

    ``is_folder`` is injected (pdf_drive owns the folder role) so this
    module never imports pdf_drive, which imports it.
    """

    def __init__(self, night: bool, is_folder, parent=None) -> None:
        super().__init__(parent)
        self._night = bool(night)
        self._is_folder = is_folder
        c = theme.palette(self._night)
        self._band_sel = QColor(band_colour(True, False, self._night))
        self._band_hover = QColor(band_colour(False, True, self._night))
        self._guide = QColor(guide_colour(self._night))
        self._ink = QColor(c["text_muted"])

    def sizeHint(self, option, index):  # noqa: N802 — Qt naming
        try:
            size = super().sizeHint(option, index)
            return QSize(size.width(), max(size.height(), ROW_H))
        except Exception:
            return QSize(ICON_BOX, ROW_H)

    def paint(self, painter, option, index) -> None:
        try:
            if index.column() != 0:
                super().paint(painter, option, index)
                return
            self._paint_name_cell(painter, option, index)
        except Exception as exc:
            # A virtual may not raise into C++ (K-172). Fall back to the
            # plain cell so the row is never blank.
            print(f"[klausmate] explorer delegate paint failed: {exc}")
            try:
                super().paint(painter, option, index)
            except Exception:
                pass

    def _paint_name_cell(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        state = opt.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hover = bool(state & QStyle.StateFlag.State_MouseOver)
        rect = opt.rect

        # 1. The band, across the WHOLE cell. The style would only paint
        #    the rect it is handed, and that rect is stepped past the
        #    icon below, which would notch the row at the icon's edge.
        if selected:
            painter.fillRect(rect, self._band_sel)
        elif hover:
            painter.fillRect(rect, self._band_hover)

        # 2. The text, by the style: elision, the item's own font and
        #    foreground (K-127's retention ink, K-117's suspended dim)
        #    all come for free. State flags stripped so it paints no
        #    second, narrower band under the text.
        text_opt = QStyleOptionViewItem(opt)
        text_opt.rect = rect.adjusted(label_inset(), 0, 0, 0)
        text_opt.state = (
            state
            & ~QStyle.StateFlag.State_Selected
            & ~QStyle.StateFlag.State_MouseOver
        )
        text_opt.backgroundBrush = QBrush(Qt.BrushStyle.NoBrush)
        super().paint(painter, text_opt, index)

        painter.save()
        try:
            # 3. Indent guides at every ancestor's twisty column. The
            #    tree's own indentation and root decoration decide where
            #    those columns are; the pure helper only knows offsets.
            widget = getattr(option, "widget", None)
            indent = INDENT
            root_dec = True
            try:
                if widget is not None:
                    indent = int(widget.indentation()) or INDENT
                    root_dec = bool(widget.rootIsDecorated())
            except Exception:
                pass
            depth = depth_of(index)
            if depth:
                origin = rect.x() - (depth + (1 if root_dec else 0)) * indent
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                painter.setPen(QPen(self._guide, GUIDE_STROKE))
                for gx in guide_xs(depth, indent):
                    x = origin + gx
                    painter.drawLine(x, rect.top(), x, rect.bottom())

            # 4. The icon, in the item's own ink.
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            ix, iy, _, _ = icon_rect(rect.x(), rect.y(), rect.height())
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            ink = fg.color() if isinstance(fg, QBrush) else self._ink
            painter.setPen(_ink_pen(ink, STROKE))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._is_folder(index):
                painter.drawPath(_path(folder_icon(ix, iy), close=True))
            else:
                outline, fold = page_icon(ix, iy)
                painter.drawPath(_path(outline, close=True))
                painter.drawPath(_path(fold, close=False))
        finally:
            painter.restore()


class GlyphButton(QToolButton):  # type: ignore[misc]
    """A 24x22 icon action for a section caption row.

    The sheet (``QToolButton#LibraryGlyph`` in theme.library_qss) paints
    rest / hover / pressed / focus / disabled; this class paints only the
    glyph, in the ink those states call for.
    """

    def __init__(self, kind: str, tooltip: str, night: bool, parent=None) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown glyph kind: {kind!r}")
        super().__init__(parent)
        self._kind = kind
        self._night = bool(night)
        self.setObjectName("LibraryGlyph")
        self.setToolTip(tooltip)
        # The tooltip may carry a sentence; the accessible name is the verb.
        self.setAccessibleName(tooltip.split(" — ", 1)[0].rstrip("…"))
        self.setFixedSize(ACTION_W, ACTION_H)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    @property
    def kind(self) -> str:
        return self._kind

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt naming
        # The sheet's background/border first, then the glyph on top.
        try:
            super().paintEvent(event)
        except Exception as exc:
            print(f"[klausmate] glyph button base paint failed: {exc}")
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            c = theme.palette(self._night)
            lit = self.isEnabled() and (self.underMouse() or self.isDown())
            ink = QColor(ink_colour(
                self._night, c["text"] if lit else None, self.isEnabled()
            ))
            x0 = (self.width() - ICON_BOX) / 2.0
            y0 = (self.height() - ICON_BOX) / 2.0
            _draw_primitives(painter, glyph(self._kind, x0, y0), ink)
        except Exception as exc:
            print(f"[klausmate] glyph button paint failed: {exc}")
        finally:
            painter.end()


def install(tree, night: bool, is_folder) -> "ExplorerDelegate":
    """Put an ExplorerDelegate on ``tree`` and keep it alive with it."""
    delegate = ExplorerDelegate(night, is_folder, parent=tree)
    tree.setItemDelegate(delegate)
    tree._klaus_explorer = delegate
    return delegate
