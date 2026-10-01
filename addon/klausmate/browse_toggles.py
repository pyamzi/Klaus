"""Browse pane toggles: the self-painted sidebar / editor-column button
(``_PaneToggle``) and its visibility watcher, which the status bar
(``status_bar.py``) places at the bottom of Browse, plus the
``browser_will_show`` layout repair.

Extracted from __init__.py (K-024, slice 2 of the K-006 file split). Until
the status bar they sat in Browse's search-bar row.

This module is imported by __init__.py at package load time, so it must
never import __init__ (this package) at module load — only from inside a
function, after the package has finished loading. _pkg() below is that
lazy accessor (same pattern as curation.py's and manage_models.py's
_pkg()); it reaches a Browse helper that still lives in __init__.py:
_reset_browse_layout_to_defaults.

These buttons are NOT gated on ``klausbook_design`` — they are a
functional affordance, so they ship in native mode too, sitting directly
against stock Anki chrome. That is why the chrome here is borderless and
system-native rather than a Klaus-flavoured chip.
"""

from __future__ import annotations

from typing import Any, Callable

from .slot_guard import guarded
from aqt.qt import (
    QColor,
    QEvent,
    QObject,
    QPainter,
    QPainterPath,
    QPen,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QToolButton,
    QWidget,
)


def _pkg():
    import importlib

    return importlib.import_module(__package__)


# ── Pure geometry + copy (aqt-free) ────────────────────────────────────
#
# The icon is macOS's own sidebar symbol (SF Symbols ``sidebar.left`` /
# ``sidebar.right``): a window outline, a divider rule, and the controlled
# column FILLED while that pane is showing. Borrowing it is the
# native-citizen rule working as intended — Finder, Mail, Notes and Xcode
# all use this exact shape for this exact control, so it costs the user no
# learning and adds no new design language.
#
# It replaces the ◧/◨ TEXT GLYPHS this shipped with, which were three
# separate problems: they rendered at whatever weight and size the fallback
# font happened to pick, they carried no on/off state of their own (state
# rode entirely on an accent tint, i.e. on colour alone), and being near
# mirror images of one another they read as a single ambiguous pair rather
# than as "left pane" and "right pane".
#
# Authored on a 16-unit grid and scaled, so one set of numbers serves every
# button size and device pixel ratio.

ICON_BOX = 16.0

# Frame numbers are stroke CENTRELINES, which is what drawRoundedRect
# wants; pane_rect() insets from them by half a stroke so the fill lands
# inside the outline instead of straddling it.
FRAME_X = 1.5
FRAME_TOP = 3.0
FRAME_W = 13.0
FRAME_H = 10.0
FRAME_R = 2.5
STROKE = 1.3

# Divider position as a fraction of the frame's width. 0.36 reads as "a
# sidebar"; nearer 0.5 it would read as a split view.
PANE_FRACTION = 0.36


def stroke_width(size: float) -> float:
    """Pen width for an icon drawn at ``size``."""
    return STROKE * (size / ICON_BOX)


def frame_rect(size: float) -> tuple[float, float, float, float, float]:
    """``(x, y, w, h, radius)`` of the window outline, as stroke
    centrelines. Half a stroke sticks out beyond these bounds on every
    side, which the constants above leave room for inside the box."""
    s = size / ICON_BOX
    return FRAME_X * s, FRAME_TOP * s, FRAME_W * s, FRAME_H * s, FRAME_R * s


def divider_x(size: float, side: str) -> float:
    """X of the rule between the pane and the content area."""
    x, _y, w, _h, _r = frame_rect(size)
    frac = PANE_FRACTION if side == "left" else 1.0 - PANE_FRACTION
    return x + w * frac


def frame_inner_rect(size: float) -> tuple[float, float, float, float, float]:
    """The frame's INNER edge — the rounded region a pane fill has to stay
    inside. Inset half a stroke on every side, with the radius shrunk by
    the same amount so the inner curve stays concentric with the outer one.

    This exists because a plain rectangular fill inside a rounded frame
    pokes its square corners out past the curve; the widget clips to this
    path so the fill can never escape at any size.
    """
    x, y, w, h, r = frame_rect(size)
    half = stroke_width(size) / 2.0
    return x + half, y + half, w - 2.0 * half, h - 2.0 * half, max(r - half, 0.0)


def pane_rect(size: float, side: str) -> tuple[float, float, float, float]:
    """``(x, y, w, h)`` of the column filled while the pane is visible —
    the frame's inner rect, cut at the divider, so fill and outline meet
    without overlapping."""
    ix, iy, iw, ih, _r = frame_inner_rect(size)
    half = stroke_width(size) / 2.0
    d = divider_x(size, side)
    if side == "left":
        return ix, iy, (d - half) - ix, ih
    return d + half, iy, (ix + iw) - (d + half), ih


PANE_NAMES = {"sidebar": "Sidebar", "editor": "Card Editor", "tree": "Library"}


def toggle_label(pane: str, visible: bool) -> str:
    """Help tag and accessible name for a pane toggle.

    Names the RESULT of the click rather than the mechanism — "Hide
    Sidebar" while the sidebar is showing — which is both HIG's rule for
    help tags and the exact wording of macOS's own View menu. Title case
    follows the addon's copy glossary.
    """
    verb = "Hide" if visible else "Show"
    return f"{verb} {PANE_NAMES.get(pane, 'Pane')}"


# ── The widget ─────────────────────────────────────────────────────────

# Sized for the status bar's 23px row inside its 28pt strip: a 16px icon with
# 3px of hover wash around it. At 100%: the strip resizes the button by
# bar_scale (status_bar._size) and the icon follows the button (icon_size).
BUTTON_SIZE = 22
ICON_SIZE = 16.0
CHIP_RADIUS = 6.0  # the design system's small-control radius


def icon_size(w: float, h: float) -> float:
    """The icon for a ``w``x``h`` button: ICON_SIZE at BUTTON_SIZE, scaled."""
    return ICON_SIZE * min(w, h) / BUTTON_SIZE


def is_keyboard_focus(event) -> bool:
    return event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)


class _PaneToggle(QToolButton):  # type: ignore[misc]
    """A borderless toolbar toggle that paints its own sidebar icon.

    The chrome is painted here rather than set as QSS because the old
    chip's permanent 1px border was the whole complaint: an outlined box
    in every state reads as a focus ring rather than as a toggle, and
    macOS toolbar buttons carry no frame at rest at all. So: nothing at
    rest, a soft grey wash on hover, an accent-tinted fill when on.

    State never rides on colour ALONE — the icon's column fills when the
    pane is showing, so on and off differ in shape as well as hue.

    Self-painting follows Md3Switch, the addon's other custom control, and
    inherits its two hard-won rules: every float-coordinate draw call takes
    a QRectF/QPointF (the positional overloads accept ints ONLY and raise
    TypeError on every paint otherwise), and the painter is closed in a
    ``finally`` (one left live corrupts the backing store and segfaults
    Qt's next flush).
    """

    def __init__(self, side: str, pane: str, checked: bool) -> None:
        super().__init__()
        self._side = side
        self._pane = pane
        self._hovered = False
        self._tab_focus = False
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.setAutoRaise(True)
        # Keyboard-reachable, and the ring below makes that visible. Tab
        # only: a click that took focus left a ring on the button.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._sync_copy()
        self.toggled.connect(self._sync_copy)

    @guarded
    def _sync_copy(self, *_args) -> None:
        """Re-label on every state change, including programmatic ones —
        the dock's visibilityChanged drives setChecked, so the tooltip has
        to follow that path too, not just clicks."""
        label = toggle_label(self._pane, self.isChecked())
        self.setToolTip(label)
        self.setAccessibleName(label)

    # Hover and focus are painted by hand here, so the repaints that
    # QStyle would normally trigger have to be asked for explicitly.
    def enterEvent(self, event) -> None:  # noqa: N802 — Qt override name
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt override name
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 — Qt override name
        self._tab_focus = is_keyboard_focus(event)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 — Qt override name
        self._tab_focus = False
        self.update()
        super().focusOutEvent(event)

    def show_focus(self) -> bool:
        """Draw the ring only for focus the keyboard brought: Qt hands a
        window's first Tab-focusable widget focus when it opens, and a
        ring nobody asked for read as a stuck button."""
        return self.hasFocus() and self._tab_focus

    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt override name
        try:
            from . import theme
        except Exception:
            return
        # No surface yet = nothing safe to paint on.
        if self.width() <= 0 or self.height() <= 0:
            return
        night = theme.night_mode()
        c = theme.palette(night)
        painter = QPainter(self)
        try:
            self._paint(painter, theme, c, night)
        except Exception as exc:
            # A drawing bug must degrade to "the button didn't draw", never
            # to an exception escaping mid-paint.
            print(f"[klausmate] pane toggle paint failed: {exc}")
        finally:
            painter.end()

    def _tint(self, theme, night: bool, alpha: float) -> "QColor":
        """The live accent at ``alpha``, as a QColor.

        Deliberately NOT theme.accent_rgba: that returns a CSS
        ``rgba(...)`` string for STYLESHEETS, and QColor cannot parse
        functional notation — fed one it yields an INVALID colour, which
        paints opaque black. That is exactly how this control first
        shipped (black chips under an accent icon), and no amount of
        geometry testing could see it, because the bug is in colour
        PARSING. Alpha belongs on the QColor, never in the string.
        """
        col = QColor(theme.palette(night)["blue_bright"])
        col.setAlphaF(alpha)
        return col

    def _paint(self, painter, theme, c: dict, night: bool) -> None:
        """The drawing itself, split out so paintEvent's try/finally can
        guarantee the painter is closed however this returns."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        on = self.isChecked()

        # Chrome. Nothing at rest, on or off — the filled column already
        # says "on", and a tinted chip too read as a heavy block in the bar.
        fill = None
        if not self.isEnabled():
            fill = None
        elif self.isDown():
            fill = self._tint(theme, night, 0.22)
        elif self._hovered:
            fill = QColor(c["hover_subtle"])
        if fill is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(
                QRectF(0.0, 0.0, w, h), CHIP_RADIUS, CHIP_RADIUS
            )

        # In RTL the grid mirrors the buttons, so mirror the icon with it —
        # each one must keep pointing at the pane it actually controls.
        side = self._side
        if self.isRightToLeft():
            side = "right" if side == "left" else "left"

        painter.save()
        size = icon_size(w, h)
        painter.translate(round((w - size) / 2.0), round((h - size) / 2.0))
        self._paint_icon(painter, c, on, side, size)
        painter.restore()

        if self.show_focus():
            # A self-painted widget bypasses QStyle entirely, so the shared
            # :focus rule in dialog_qss can never reach this one.
            pen = QPen(self._tint(theme, night, 0.9))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                QRectF(1.0, 1.0, w - 2.0, h - 2.0), CHIP_RADIUS, CHIP_RADIUS
            )

    def _paint_icon(self, painter, c: dict, on: bool, side: str, size: float = ICON_SIZE) -> None:
        colour = QColor(c["text"] if on else c["text_muted"])

        # Fill first, outline over it: the stroke then covers the fill's
        # outer edge instead of sitting beside it.
        if on:
            px, py, pw, ph = pane_rect(size, side)
            ix, iy, iw, ih, ir = frame_inner_rect(size)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(ix, iy, iw, ih), ir, ir)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            # Clip, or the fill's square corners poke out past the frame's
            # rounded ones — visible as a hard corner at any real size.
            painter.save()
            painter.setClipPath(clip)
            painter.drawRect(QRectF(px, py, pw, ph))
            painter.restore()

        pen = QPen(colour)
        pen.setWidthF(stroke_width(size))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        fx, fy, fw, fh, fr = frame_rect(size)
        painter.drawRoundedRect(QRectF(fx, fy, fw, fh), fr, fr)
        d = divider_x(size, side)
        painter.drawLine(QPointF(d, fy), QPointF(d, fy + fh))


class _VisibilityWatcher(QObject):
    """Calls ``on_change(visible)`` whenever ``target`` is shown or
    hidden — keeps a toggle button honest when other code (e.g. Anki's
    selection handling) flips the widget."""

    def __init__(
        self, target: QWidget, on_change: Callable[[bool], None]
    ) -> None:
        super().__init__(target)
        self._on_change = on_change
        target.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        t = ev.type()
        if t in (QEvent.Type.Show, QEvent.Type.Hide):
            try:
                self._on_change(t == QEvent.Type.Show)
            except Exception:
                pass
        return False


def on_browser_will_show(browser: Any) -> None:
    """``gui_hooks.browser_will_show`` callback: repair leftover broken
    layout state from earlier add-on builds
    (``_reset_browse_layout_to_defaults``). The sidebar / editor-column
    toggles themselves live in the status bar now (``status_bar.py``);
    ``_PaneToggle`` and ``_VisibilityWatcher`` here are what it uses.

    Earlier batches also wrapped the editor pane in a ``QDockWidget`` and
    added a View menu, plus a Browse natural-language ⌘K search that
    remapped Anki's native Mark hotkey out of the way. Those features were
    removed — the user preferred Anki's stock Browse layout, and Anki's
    native ⌘K Mark hotkey now works again. The sidebar toggle button
    re-added here does NOT touch the dock's areas/floating/features; it is
    purely a visible affordance for Anki's existing show/hide.

    Installs are deferred one event-loop tick (``QTimer.singleShot(0)``)
    so ``setupUi`` has finished wiring the form's actions and widgets
    before we touch them.
    """

    def _deferred() -> None:
        # Re-anchor the sidebar to the left and undo any zero-width
        # splitter pane. No-op on a clean profile.
        try:
            _pkg()._reset_browse_layout_to_defaults(browser)
        except Exception as exc:
            print(f"[klausmate] browse layout reset failed: {exc}")

    try:
        QTimer.singleShot(0, _deferred)
    except Exception as exc:
        print(f"[klausmate] browser_will_show defer failed: {exc}")
        # Last-ditch synchronous attempt if the singleShot itself errored.
        _deferred()


# ── The top bar's pane toggles (single window) ─────────────────────────
#
# In the single window the ◧ ◨ toggles sit in Anki's top toolbar, right of
# the Klaus logo, for whichever tab has panes (Add: the Library tree and
# the editor; Browse: the sidebar and the card editor). Decks has none, so
# the pair hides there. The toolbar is a webview: the pair is HTML in the
# left tray, a click comes back as ``PANE_CMD:<side>``, and every change
# (a click, a tab switch, a pane hidden from elsewhere, a toolbar redraw)
# re-pushes ``pane_state()`` through ``klausPanes``. Same icon as
# ``_PaneToggle``: the geometry above, emitted as SVG.

PANE_CMD = "klausmate_pane"


def _n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def pane_icon_svg(side: str) -> str:
    """``_PaneToggle``'s icon as inline SVG in ``currentColor``; the pane
    column (``.kp-fill``) is filled by CSS while that pane shows."""
    s = ICON_BOX
    fx, fy, fw, fh, fr = frame_rect(s)
    px, py, pw, ph = pane_rect(s, side)
    ix, iy, iw, ih, ir = frame_inner_rect(s)
    d, sw = divider_x(s, side), stroke_width(s)
    return (
        f'<svg width="16" height="16" viewBox="0 0 {_n(s)} {_n(s)}" aria-hidden="true">'
        f'<clipPath id="kp-clip-{side}"><rect x="{_n(ix)}" y="{_n(iy)}" width="{_n(iw)}" '
        f'height="{_n(ih)}" rx="{_n(ir)}"/></clipPath>'
        f'<rect class="kp-fill" clip-path="url(#kp-clip-{side})" x="{_n(px)}" y="{_n(py)}" '
        f'width="{_n(pw)}" height="{_n(ph)}"/>'
        f'<rect x="{_n(fx)}" y="{_n(fy)}" width="{_n(fw)}" height="{_n(fh)}" rx="{_n(fr)}" '
        f'fill="none" stroke="currentColor" stroke-width="{_n(sw)}"/>'
        f'<line x1="{_n(d)}" y1="{_n(fy)}" x2="{_n(d)}" y2="{_n(fy + fh)}" '
        f'stroke="currentColor" stroke-width="{_n(sw)}"/></svg>'
    )


_PANES_JS = """
function klausPanes(s) {
  var g = document.getElementById('klaus-panes'); if (!g) return;
  g.style.display = s.show ? '' : 'none';
  ['left', 'right'].forEach(function (k) {
    var e = document.getElementById('klaus-pane-' + k), p = s[k]; if (!e) return;
    e.style.display = p ? '' : 'none'; if (!p) return;
    e.classList.toggle('on', !!p.on);
    e.title = p.label; e.setAttribute('aria-label', p.label);
    e.setAttribute('aria-pressed', p.on ? 'true' : 'false');
  });
}
"""


def panes_css() -> str:
    """Both palettes, keyed on the classes Anki toggles on a theme switch
    (the toolbar never redraws for one; see ``theme.toolbar_css``)."""
    from . import theme

    rules = []
    for night in (False, True):
        c = theme.palette(night)
        root = ":root.night-mode" if night else ":root"
        rules.append(
            f"{root} .klaus-pane {{ color: {c['text_muted']}; }}"
            f"{root} .klaus-pane:hover, {root} .klaus-pane:focus-visible {{ background: {c['hover_subtle']}; }}"
            f"{root} .klaus-pane.on {{ color: {c['text']}; }}"
        )
    return (
        "#klaus-panes { display: inline-flex; align-items: center; gap: 2px;"
        " vertical-align: middle; margin-right: 6px; }"
        ".klaus-pane { display: inline-flex; padding: 3px; border-radius: 6px;"
        " cursor: default; outline: none; }"
        ".klaus-pane .kp-fill { fill: none; } .klaus-pane.on .kp-fill { fill: currentColor; }"
        + "".join(rules)
    )


def panes_html(state: dict) -> str:
    """The pair, hidden until ``state`` says the tab has panes."""
    import json

    links = "".join(
        f'<a id="klaus-pane-{side}" class="klaus-pane" href=# role="button" '
        f'onclick="return pycmd(\'{PANE_CMD}:{side}\')">{pane_icon_svg(side)}</a>'
        for side in ("left", "right")
    )
    return (
        f"<style>{panes_css()}</style>"
        f'<span id="klaus-panes" style="display: none">{links}</span>'
        f"<script>{_PANES_JS}klausPanes({json.dumps(state)});</script>"
    )


def _pane_widgets() -> dict:
    """``{side: (pane name, widget)}`` for the single window's tab; empty
    on Decks, with Browse closed, or without the single window."""
    try:
        from . import single_window as sw

        if not sw.is_active():
            return {}
        st = sw._state
        tab = getattr(st.host, "tab", None)
        if tab == "add" and st.add is not None:
            return {"left": ("tree", st.add.tree), "right": ("editor", st.add.editor_slot)}
        if tab == "browse" and st.browser is not None:
            from .status_bar import _editor_column

            out = {}
            dock = getattr(st.browser, "sidebarDockWidget", None)
            if dock is not None:
                out["left"] = ("sidebar", dock)
            col = _editor_column(st.browser)
            if col is not None:
                out["right"] = ("editor", col)
            return out
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] pane toggles: panes unknown: {exc}")
    return {}


def pane_state() -> dict:
    out: dict = {"show": False}
    for side, (pane, widget) in _pane_widgets().items():
        try:
            on = not widget.isHidden()
        except RuntimeError:  # deleted under us
            continue
        out[side] = {"on": on, "label": toggle_label(pane, on)}
        out["show"] = True
    return out


_watched: set = set()
_push_pending = [False]


def push_panes() -> None:
    """Re-draw the pair from the live panes, one tick later (several
    Show/Hide events arrive together), and keep watching those panes."""
    if _push_pending[0]:
        return
    _push_pending[0] = True

    def run() -> None:
        _push_pending[0] = False
        try:
            import json

            from aqt import mw

            for _pane, widget in _pane_widgets().values():
                if id(widget) not in _watched:
                    _watched.add(id(widget))
                    _VisibilityWatcher(widget, lambda _v: push_panes())
                    widget.destroyed.connect(lambda *_a, k=id(widget): _watched.discard(k))
            web = getattr(mw, "toolbarWeb", None)
            if web is not None:
                web.eval(f"window.klausPanes && klausPanes({json.dumps(pane_state())});")
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] pane toggles push failed: {exc}")

    QTimer.singleShot(0, run)


def toggle_pane(side: str) -> None:
    panes = _pane_widgets()
    pane = panes.get(side)
    if pane is None:
        return
    widget = pane[1]
    other = panes.get("right" if side == "left" else "left")
    from . import pane_keep

    pane_keep.set_visible_keeping(widget, widget.isHidden(), other[1] if other else None)
    push_panes()


def _on_left_tray(content: list, _toolbar: Any) -> None:
    """Right of the Klaus logo (top_bar puts it first; whichever hook
    runs first, the pair lands just after it)."""
    try:
        html = panes_html(pane_state())
        at = next((i + 1 for i, item in enumerate(content) if 'id="klaus-logo"' in str(item)), 0)
        content.insert(at, html)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] pane toggles failed: {exc}")


def _on_js_message(handled, message: str, _context):
    if not message.startswith(PANE_CMD + ":"):
        return handled
    side = message.split(":", 1)[1]
    if side in ("left", "right"):
        # A tick later, never inside the webchannel call (bridge_reentrancy).
        QTimer.singleShot(0, lambda: toggle_pane(side))
    return (True, None)


def _listen_to_tabs(*_args) -> None:
    """Follow tab switches (Host.listeners), once."""
    try:
        from . import single_window as sw

        host = sw._state.host
        if host is not None and _on_tab not in host.listeners:
            host.listeners.append(_on_tab)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] pane toggles: tab listener failed: {exc}")
    push_panes()


def _on_tab(_new: str, _old: str) -> None:
    push_panes()


def setup_top_bar() -> None:
    from aqt import gui_hooks

    gui_hooks.top_toolbar_will_set_left_tray_content.append(_on_left_tray)
    gui_hooks.webview_did_receive_js_message.append(_on_js_message)
    gui_hooks.top_toolbar_did_redraw.append(lambda *_a: push_panes())
    gui_hooks.profile_did_open.append(_listen_to_tabs)
    gui_hooks.browser_will_show.append(lambda *_a: push_panes())
