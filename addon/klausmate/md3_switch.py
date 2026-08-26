"""An MD3-style track-and-thumb switch, drawn from Klaus's own tokens.

Why this exists (K-material3 audit): the three Preferences toggles
(image crop, manage-Ollama, pdf.js viewer) were bare ``QCheckBox()``
squares — a checked/unchecked *checkbox* is MD2-era language for what
is semantically an on/off *switch*, and macOS agrees with MD3 here (a
Settings row uses a switch, not a checkbox). This is not an MD3-web
component drop-in (``@material/web`` is Qt-incompatible and in
maintenance mode anyway) — it is a small painted widget that follows
MD3's switch geometry and motion language while staying entirely
inside the Quiet Clinic token system: track/thumb colours come from
``theme.palette()``, so a switch recolours under all 13 accent presets
without any code here knowing they exist.

Pure geometry/colour math sits at module top, aqt-free, so it is
testable without constructing a real widget (the repo's standing rule:
Qt widgets are never constructed in headless tests). ``Md3Switch``
itself is a thin ``QCheckBox`` subclass — every existing call site
(``.isChecked()``, ``.setChecked()``, ``.toggled.connect(...)``) keeps
working unchanged; only how it paints and animates is new.

PAINT SAFETY (this widget segfaulted Anki nine times — see
``_animate_to``): never repaint while off screen, never paint into a
zero-size widget, and never leave a ``QPainter`` active. The three
rules are pinned in tests/test_md3_switch.py.
"""
from __future__ import annotations

# ── Pure geometry + colour math (aqt-free) ─────────────────────────────

# MD3's own switch spec, scaled down ~0.7x to sit comfortably in a
# settings row built for an 8px/13px control language rather than
# Android's 52x32dp track.
TRACK_W = 36
TRACK_H = 20
THUMB_OFF_D = 12  # small, centred dot when unchecked (MD3: "outline")
THUMB_ON_D = 16  # larger dot near the track's far edge when checked
THUMB_MARGIN = 4  # inset from the track's flat ends at rest


def thumb_diameter(progress: float) -> float:
    """Thumb size at ``progress`` (0 unchecked -> 1 checked), the MD3
    grow-on-select behaviour. Linear is enough at this scale; MD3's own
    spring easing lives in the animation, not the size curve."""
    p = max(0.0, min(1.0, progress))
    return THUMB_OFF_D + (THUMB_ON_D - THUMB_OFF_D) * p


def thumb_center_x(progress: float, track_w: float = TRACK_W) -> float:
    """The thumb's horizontal centre inside the track at ``progress``.

    The thumb starts centred in the left margin and ends centred in
    the right margin, growing as it travels — exactly MD3's switch
    motion (position and size interpolate together).
    """
    p = max(0.0, min(1.0, progress))
    d = thumb_diameter(p)
    left = THUMB_MARGIN + d / 2.0
    right = track_w - THUMB_MARGIN - d / 2.0
    return left + (right - left) * p


def pill_rect(
    inset: float, track_top: float = 2.0
) -> tuple[float, float, float, float, float]:
    """The track pill as ``(x, y, w, h, radius)`` at ``inset`` — ONE
    formula for the fill (inset 0), the unchecked hairline outline
    (0.5) and the focus ring (1.0), so the three strokes stay
    concentric by construction instead of by three hand-copied
    drawRoundedRect calls agreeing."""
    h = TRACK_H - 2.0 * inset
    return (inset, track_top + inset, TRACK_W - 2.0 * inset, h, h / 2.0)


def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * max(0.0, min(1.0, t)))


def _lerp_hex(off_hex: str, on_hex: str, t: float) -> str:
    """Blend two ``#rrggbb`` colours — the track crossfades rather than
    snapping, so the animation reads as one continuous motion."""
    a = off_hex.lstrip("#")
    b = on_hex.lstrip("#")
    out = [
        _lerp(int(a[i : i + 2], 16), int(b[i : i + 2], 16), t)
        for i in (0, 2, 4)
    ]
    return "#%02X%02X%02X" % tuple(out)


def track_color(c: dict, progress: float) -> str:
    """Track fill at ``progress``: `grey_light` off, the active accent
    (`blue_accent`) on — the same accent token everything else in the
    app recolours from."""
    return _lerp_hex(c["grey_light"], c["blue_accent"], progress)


def thumb_color(c: dict, progress: float) -> str:
    """Thumb fill at ``progress``: `grey_dark` off (visible against the
    light track), white on (MD3's on-primary role — high contrast
    against any saturated accent, the same choice `dialog_qss` already
    makes for primary-button text)."""
    return _lerp_hex(c["grey_dark"], "#FFFFFF", progress)


def disabled_track_color(c: dict, checked: bool) -> str:
    """A washed-out variant of the current state, never a third look —
    matches how disabled buttons/inputs behave elsewhere in the theme
    (`grey_light` fill, `text_faint` content)."""
    return c["blue_accent"] if checked else c["grey_light"]


def disabled_thumb_color(c: dict, checked: bool) -> str:
    """Sibling of :func:`disabled_track_color`, same rule: the current
    state's endpoint colour, washed out — `surface` on the grey off
    track, white on the accent on track (the enabled endpoints, minus
    the crossfade)."""
    return "#FFFFFF" if checked else c["surface"]


# ── The widget ──────────────────────────────────────────────────────────

try:
    from aqt.qt import (
        QCheckBox,
        QColor,
        QEasingCurve,
        QPainter,
        QPen,
        QPropertyAnimation,
        Qt,
        pyqtProperty,
    )
except Exception:  # pragma: no cover — degrades to plain checkbox
    QCheckBox = object  # type: ignore[assignment,misc]


class Md3Switch(QCheckBox):  # type: ignore[misc]
    """Drop-in replacement for a label-less ``QCheckBox()`` row control.

    Paints itself entirely (no QSS indicator styling applies here);
    checked-state bookkeeping is 100% inherited from ``QCheckBox`` so
    every existing call site is untouched.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(TRACK_W, TRACK_H + 4)  # +4: room for a focus ring
        self._progress = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(200)  # MD3 "standard" duration
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to)

    # -- animated property -------------------------------------------------
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        # Only ask for a repaint once we are actually on screen. A repaint
        # requested while the window is still being composited is what
        # crashed Anki (see _animate_to); when the widget is finally shown
        # Qt paints it from _progress anyway, so nothing is lost.
        if self.isVisible():
            self.update()

    progress = pyqtProperty(float, _get_progress, _set_progress)

    def _animate_to(self, checked: bool) -> None:
        """Animate toward the new state — but ONLY when already on screen.

        LIVE CRASH (2026-08-26, macOS 26.5 + Qt 6.11): the dialog builds
        its rows and then calls setChecked() to load saved settings, which
        fires `toggled` and used to start this animation immediately. The
        animation then repainted the switch WHILE the dialog window was
        still being composited for its first appearance, and Qt's Cocoa
        backing-store flush dereferenced a paint device that did not exist
        yet -> SIGSEGV in QPaintDevice::devicePixelRatio inside
        QBackingStore::flush. Bisected to this widget with a staged probe:
        a bare dialog was fine, + our stylesheet was fine, + one switch
        crashed. A control has no business animating into its initial
        state anyway, so an invisible widget jumps straight to the target.
        """
        target = 1.0 if checked else 0.0
        self._anim.stop()
        if not self.isVisible():
            self._progress = target
            return
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    # -- hit testing: the whole widget is the target, not a style-computed
    #    indicator rect (we draw no native indicator for QStyle to size) --
    def hitButton(self, pos) -> bool:  # noqa: N802 — Qt override name
        return self.rect().contains(pos)

    # -- painting ------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt override name
        try:
            from . import theme
        except Exception:
            return
        # No surface yet = nothing safe to paint on. Painting into a
        # widget with no valid size is the other way to hand Qt's flush a
        # paint device it cannot use (see _animate_to's crash note).
        if self.width() <= 0 or self.height() <= 0:
            return
        c = theme.palette(theme.night_mode())
        p = self._progress
        enabled = self.isEnabled()

        painter = QPainter(self)
        try:
            self._paint(painter, c, p, enabled)
        finally:
            # ALWAYS end the painter, even if a token lookup or a Qt call
            # above raises: a QPainter left active on a widget corrupts
            # the backing store for every later flush.
            painter.end()

    def _paint(self, painter, c: dict, p: float, enabled: bool) -> None:
        """The actual drawing, split out so paintEvent's try/finally can
        guarantee painter.end() no matter how this returns."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Track, vertically centred with room left for the focus ring.
        # All three pill strokes come from pill_rect at their inset.
        track_top = 2.0
        if enabled:
            fill = track_color(c, p)
        else:
            fill = disabled_track_color(c, p >= 0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill))
        x, y, w, h, r = pill_rect(0.0, track_top)
        painter.drawRoundedRect(x, y, w, h, r, r)
        # Unchecked track keeps a hairline outline (MD3's outlined-off
        # track) — a filled track dissolves into a light-mode fog page.
        if p < 0.999:
            outline = QPen(QColor(c["grey_mid"]))
            outline.setWidthF(1.0)
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            x, y, w, h, r = pill_rect(0.5, track_top)
            painter.drawRoundedRect(x, y, w, h, r, r)

        # Thumb: grows and slides together (MD3's signature switch move).
        d = thumb_diameter(p)
        cx = thumb_center_x(p, TRACK_W)
        cy = track_top + TRACK_H / 2.0
        thumb_fill = (
            thumb_color(c, p)
            if enabled
            else disabled_thumb_color(c, p >= 0.5)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(thumb_fill))
        painter.drawEllipse(
            float(cx - d / 2.0), float(cy - d / 2.0), float(d), float(d)
        )

        # Keyboard focus ring: this widget bypasses QStyle entirely, so
        # the shared QPushButton:focus rule in dialog_qss cannot reach
        # it — draw the same accent ring by hand (K-critique P1 parity).
        if self.hasFocus():
            ring = QPen(QColor(c["blue_bright"]))
            ring.setWidthF(1.5)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            x, y, w, h, r = pill_rect(1.0, track_top)
            painter.drawRoundedRect(x, y, w, h, r, r)
        # Deliberately NOT ended here: paintEvent's finally block owns
        # closing the painter, and ending it twice is its own corruption.
