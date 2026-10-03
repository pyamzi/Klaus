"""Klaus image crop dialog — crop any image referenced by a note field.

``ImageCropDialog`` shows the image fitted to (at most) ~85% of the screen
with a rubber-band crop selection: drag to draw, drag inside to move, drag
one of the 8 handles to resize. The selection is kept in IMAGE-SPACE pixels
and mapped to widget coordinates per event, so resizing the dialog can never
corrupt the crop.

``encode_cropped`` keeps jpg/png/webp in their original format; every other
input (svg — rasterized on load, gif — first frame only, ico, ...) falls
back to PNG.
"""

from __future__ import annotations

from typing import Callable, Optional

from aqt.qt import (
    QBuffer,
    QColor,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QIODevice,
    QImage,
    QLabel,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPoint,
    QPointF,
    QPushButton,
    QRect,
    QRectF,
    QSize,
    QVBoxLayout,
    QWidget,
    Qt,
)

def _accent_color() -> QColor:
    """The crop rectangle/handles in the USER'S accent — the one moment
    of active manipulation should carry the theme, not a frozen blue."""
    try:
        from . import theme

        return QColor(theme.palette(theme.night_mode())["blue_accent"])
    except Exception:
        return QColor(58, 130, 247)


_MASK = QColor(0, 0, 0, 120)
_HANDLE_PX = 8  # logical px, drawn handle squares
_HIT_PAD = 6  # grab tolerance around edges/handles
_MIN_SEL_IMG_PX = 3  # selections smaller than this (image px) are discarded


class _CropCanvas(QWidget):
    """Fitted image display with a draw/move/resize crop selection."""

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = image
        self._sel: QRect | None = None  # IMAGE-SPACE integer pixels
        self._mode = "idle"  # idle | draw | move | resize
        self._handle: str | None = None  # tl t tr r br b bl l
        self._anchor: QPoint | None = None  # image-space fixed corner
        self._grab = QPoint(0, 0)  # image-space press offset from sel.topLeft
        self.on_selection_changed: Optional[Callable[[], None]] = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ----------------------------- geometry -------------------------------

    def _fit(self) -> tuple[float, QPointF]:
        """Fit-scale and top-left offset of the displayed image.

        Recomputed per event/paint from the current widget size, so the
        image-space selection survives any dialog resize.
        """
        iw = max(1, self._image.width())
        ih = max(1, self._image.height())
        w = max(1, self.width())
        h = max(1, self.height())
        s = min(w / iw, h / ih)
        off = QPointF((w - iw * s) / 2.0, (h - ih * s) / 2.0)
        return s, off

    def _img_rect_to_widget(self, r: QRect) -> QRectF:
        s, off = self._fit()
        return QRectF(
            off.x() + r.x() * s,
            off.y() + r.y() * s,
            r.width() * s,
            r.height() * s,
        )

    def _widget_to_img(self, p: QPointF) -> QPoint:
        s, off = self._fit()
        x = round((p.x() - off.x()) / s)
        y = round((p.y() - off.y()) / s)
        x = max(0, min(self._image.width(), x))
        y = max(0, min(self._image.height(), y))
        return QPoint(x, y)

    def _handle_rects(self) -> dict[str, QRectF]:
        """Hit rects (widget coords) for the 8 resize handles."""
        if self._sel is None:
            return {}
        r = self._img_rect_to_widget(self._sel)
        side = float(_HANDLE_PX + _HIT_PAD * 2)
        cx = r.center().x()
        cy = r.center().y()
        centers = {
            "tl": QPointF(r.left(), r.top()),
            "t": QPointF(cx, r.top()),
            "tr": QPointF(r.right(), r.top()),
            "r": QPointF(r.right(), cy),
            "br": QPointF(r.right(), r.bottom()),
            "b": QPointF(cx, r.bottom()),
            "bl": QPointF(r.left(), r.bottom()),
            "l": QPointF(r.left(), cy),
        }
        return {
            k: QRectF(c.x() - side / 2, c.y() - side / 2, side, side)
            for k, c in centers.items()
        }

    def selection(self) -> QRect | None:
        """Current selection in image-space pixels, clamped to the image."""
        if self._sel is None:
            return None
        r = self._sel.intersected(
            QRect(0, 0, self._image.width(), self._image.height())
        )
        if r.isEmpty():
            return None
        return r

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 240)

    def _emit_changed(self) -> None:
        if self.on_selection_changed is not None:
            try:
                self.on_selection_changed()
            except Exception:
                pass

    # ----------------------------- mouse ----------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if self._sel is not None:
            for key, rect in self._handle_rects().items():
                if rect.contains(pos):
                    self._mode = "resize"
                    self._handle = key
                    # Fixed (opposite) corner in image space; corner handles
                    # drag the free corner, edge handles change one axis only.
                    opposite = {
                        "tl": self._sel.bottomRight(),
                        "t": self._sel.bottomRight(),
                        "tr": self._sel.bottomLeft(),
                        "r": self._sel.bottomLeft(),
                        "br": self._sel.topLeft(),
                        "b": self._sel.topLeft(),
                        "bl": self._sel.topRight(),
                        "l": self._sel.topRight(),
                    }
                    self._anchor = QPoint(opposite[key])
                    return
            if self._img_rect_to_widget(self._sel).contains(pos):
                self._mode = "move"
                self._grab = self._widget_to_img(pos) - self._sel.topLeft()
                return
        self._mode = "draw"
        self._anchor = self._widget_to_img(pos)
        self._sel = QRect(self._anchor, self._anchor)
        self.update()
        self._emit_changed()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._mode == "idle":
            self._update_hover_cursor(pos)
            return
        cur = self._widget_to_img(pos)
        if self._mode == "draw" and self._anchor is not None:
            # normalized() lets the user drag past the anchor in any direction.
            self._sel = QRect(self._anchor, cur).normalized()
        elif self._mode == "move" and self._sel is not None:
            top_left = cur - self._grab
            max_x = max(0, self._image.width() - self._sel.width())
            max_y = max(0, self._image.height() - self._sel.height())
            self._sel.moveTo(
                max(0, min(max_x, top_left.x())),
                max(0, min(max_y, top_left.y())),
            )
        elif self._mode == "resize" and self._sel is not None:
            if self._handle in ("tl", "tr", "br", "bl") and self._anchor is not None:
                self._sel = QRect(self._anchor, cur).normalized()
            elif self._handle in ("t", "b") and self._anchor is not None:
                # Rebuild from the anchored opposite edge. Mutating one
                # edge and normalizing loses the anchor as soon as the
                # cursor crosses it, collapsing the selection into a
                # sliver that chases the cursor.
                self._sel = QRect(
                    QPoint(
                        self._sel.left(),
                        min(cur.y(), self._anchor.y()),
                    ),
                    QPoint(
                        self._sel.right(),
                        max(cur.y(), self._anchor.y()),
                    ),
                )
            elif self._handle in ("l", "r") and self._anchor is not None:
                self._sel = QRect(
                    QPoint(
                        min(cur.x(), self._anchor.x()),
                        self._sel.top(),
                    ),
                    QPoint(
                        max(cur.x(), self._anchor.x()),
                        self._sel.bottom(),
                    ),
                )
        self.update()
        self._emit_changed()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._sel is not None and (
            self._sel.width() < _MIN_SEL_IMG_PX
            or self._sel.height() < _MIN_SEL_IMG_PX
        ):
            self._sel = None
        self._mode = "idle"
        self._handle = None
        self._anchor = None
        self.update()
        self._emit_changed()

    def _update_hover_cursor(self, pos: QPointF) -> None:
        cursor = Qt.CursorShape.CrossCursor
        if self._sel is not None:
            diag_f = ("tl", "br")
            diag_b = ("tr", "bl")
            hit = None
            for key, rect in self._handle_rects().items():
                if rect.contains(pos):
                    hit = key
                    break
            if hit in diag_f:
                cursor = Qt.CursorShape.SizeFDiagCursor
            elif hit in diag_b:
                cursor = Qt.CursorShape.SizeBDiagCursor
            elif hit in ("t", "b"):
                cursor = Qt.CursorShape.SizeVerCursor
            elif hit in ("l", "r"):
                cursor = Qt.CursorShape.SizeHorCursor
            elif self._img_rect_to_widget(self._sel).contains(pos):
                cursor = Qt.CursorShape.SizeAllCursor
        self.setCursor(cursor)

    # ----------------------------- paint -----------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform, True
            )
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            s, off = self._fit()
            display_rect = QRectF(
                off.x(),
                off.y(),
                self._image.width() * s,
                self._image.height() * s,
            )
            # Target-rect drawImage keeps retina crisp (painter handles the
            # devicePixelRatio for us).
            painter.drawImage(display_rect, self._image)
            if self._sel is not None:
                sel_rect = self._img_rect_to_widget(self._sel)
                # Dim everything outside the selection (odd-even hole punch).
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                path.addRect(display_rect)
                path.addRect(sel_rect)
                painter.fillPath(path, _MASK)
                painter.setPen(QPen(_accent_color(), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(sel_rect)
                # 8 handle squares.
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.setBrush(_accent_color())
                half = _HANDLE_PX / 2.0
                cx = sel_rect.center().x()
                cy = sel_rect.center().y()
                for hx, hy in (
                    (sel_rect.left(), sel_rect.top()),
                    (cx, sel_rect.top()),
                    (sel_rect.right(), sel_rect.top()),
                    (sel_rect.right(), cy),
                    (sel_rect.right(), sel_rect.bottom()),
                    (cx, sel_rect.bottom()),
                    (sel_rect.left(), sel_rect.bottom()),
                    (sel_rect.left(), cy),
                ):
                    painter.drawRect(
                        QRectF(hx - half, hy - half, _HANDLE_PX, _HANDLE_PX)
                    )
        except Exception as exc:
            # A drawing bug must degrade to "the crop preview didn't
            # draw", never to an exception escaping mid-paint (stdout,
            # not Anki's error dialog — a repainting widget would spam).
            print(f"[klaus_note] crop paint failed: {exc}")
        finally:
            # ALWAYS close the painter, however the block above exits: a
            # QPainter left live on a widget corrupts the window's
            # backing store and segfaults Qt on the next flush — the
            # md3_switch 2026-08-26 crash spree in one sentence.
            painter.end()


class ImageCropDialog(QDialog):
    """Modal crop dialog; ``cropped_image()`` after Accepted gives the crop."""

    def __init__(
        self,
        image: QImage,
        fname: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image = image
        self.setWindowTitle(f"Crop Image: {fname}")
        try:
            from aqt.utils import disable_help_button

            disable_help_button(self)
        except Exception:  # noqa: BLE001
            pass
        self.setModal(True)

        # Shared dialog chrome (theme.dialog_qss): window bg, blue-primary
        # buttons by default, SecondaryButton opt-out below — same guarded
        # pattern as manage_models.py's dialog theming.
        try:
            from . import theme

            _night = theme.night_mode()
            self.setStyleSheet(theme.dialog_qss(_night))
            _muted = theme.muted_label_qss(_night, 11)
        except Exception as exc:
            print(f"[klaus_note] crop dialog theme failed: {exc}")
            _muted = "color: rgba(140,140,140,0.95); font-size: 11px;"

        layout = QVBoxLayout(self)
        self._canvas = _CropCanvas(image, parent=self)
        layout.addWidget(self._canvas, 1)

        bottom = QHBoxLayout()
        self._size_label = QLabel("Drag to select crop area")
        self._size_label.setStyleSheet(_muted)
        bottom.addWidget(self._size_label)
        bottom.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)
        self._crop_btn = QPushButton("Crop")
        self._crop_btn.clicked.connect(self.accept)
        self._crop_btn.setDefault(True)
        self._crop_btn.setEnabled(False)
        # Platform button order; the clicks above are the wiring.
        buttons = QDialogButtonBox()
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.addButton(self._crop_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        self._canvas.on_selection_changed = self._on_selection_changed

        # Size the window so the image fits within ~85% of the screen, but
        # never upscale the window past the image's 1:1 size.
        try:
            screen_obj = (parent or self).screen()
            avail = screen_obj.availableGeometry()
            s = min(
                1.0,
                (avail.width() * 0.85) / max(1, image.width()),
                (avail.height() * 0.85 - 90) / max(1, image.height()),
            )
            self.resize(
                max(360, int(image.width() * s)),
                max(300, int(image.height() * s) + 60),
            )
        except Exception:
            self.resize(640, 480)

    def _on_selection_changed(self) -> None:
        sel = self._canvas.selection()
        self._crop_btn.setEnabled(sel is not None)
        if sel is None:
            self._size_label.setText("Drag to select crop area")
        else:
            self._size_label.setText(f"{sel.width()} × {sel.height()} px")

    def cropped_image(self) -> QImage | None:
        sel = self._canvas.selection()
        if sel is None:
            return None
        return self._image.copy(sel)


# Formats we re-encode as-is; everything else (svg — already rasterized by
# QImage on load, animated gif — first frame only, ico, ...) becomes PNG.
_KEEP_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


def encode_cropped(image: QImage, orig_ext: str) -> tuple[bytes, str]:
    """Encode ``image``; keep jpg/png/webp format, else fall back to PNG.

    Returns ``(bytes, extension-without-dot)``. Raises ``RuntimeError`` if
    Qt cannot encode the image.
    """
    ext = orig_ext.lower()
    fmt = _KEEP_FORMATS.get(ext, "PNG")
    if ext not in _KEEP_FORMATS:
        ext = "png"
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buf, fmt, 95 if fmt in ("JPEG", "WEBP") else -1)
    buf.close()
    if not ok:
        raise RuntimeError(f"could not encode cropped image as {fmt}")
    return bytes(buf.data()), ext
