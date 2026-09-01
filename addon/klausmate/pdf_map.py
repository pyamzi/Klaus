"""Embedding map window (K-123, Phase D2) — the pan/zoom canvas over
``pdf_graph.build_graph_data``'s node/edge dict.

Phase D1 shipped the data: ``projection.py`` (top-3 PCA since K-148,
pure stdlib) and ``pdf_graph.build_graph_data(user_files, cfg)``
assembling ``{"pdfs", "notes", "edges"}`` from on-disk caches only. This
module is the window: notes as depth-fogged dots, PDFs as accent circles
sized by match_count and by how near they sit, edges drawn ONLY for the
hovered/selected PDF (readability), hover tooltips, left-drag pan, wheel
zoom anchored at the cursor, and a Fit reset.

K-138, Pouya's own ask, reshaped three things.

**Every note, not a seventh of them.** ``projection`` now fits its
components on a stride sample and projects every row, so the graph
arrives holding the whole collection — 28,668 notes on the collection
this was measured against. Drawing that many with the old
``drawEllipse``-per-dot loop cost 36 ms a frame (28 fps mid-drag); the
loop itself, just transforming and culling in Python, was 9 ms of it.
So the note layer is now built ONCE as a world-space ``QPolygonF`` and
per frame handed to ``QTransform.map`` — the whole 28k transformed in
C++ — then drawn with a single ``drawPoints``. Same 28,668 dots, 3 ms.
No sampling, no cap, no level-of-detail: the honest thing was to make
the draw cheap, not to draw less. **The transform must stay on the
polygon, never on the painter**: ``drawPoints`` under a scaled painter
with a cosmetic pen degenerates into long horizontal strokes once the
zoom is deep (rendered and confirmed), while mapping to screen space
first is exact at every zoom AND slightly faster.

**Names only when you ask.** K-133 shipped always-on labels below a
12-node cap because the map opened anonymous; Pouya looked at it and
asked for the opposite — a name only when its circle is hovered or
selected. So ``labels_visible``, ``LABEL_ZOOM`` and ``LABEL_MAX_NODES``
are gone and the painter names exactly ``active_pdf(hover, selected)``.
``label_anchor`` stays: that one name still has to sit beside its node
and mirror at the view edge.

**The map follows the viewer.** ``select_pdf(safe)`` is the public seam
for "the PDF viewer opened this file" — it selects that node, recentres
when it is off-view, and repaints. It is deliberately NOT wired to the
viewer here; the Library dock card does that.

K-143 made the canvas EMBEDDABLE without letting a second renderer
exist. The class body was hoisted out of ``open_map_window`` into
``_canvas_class()`` and is reached through ``map_canvas(parent,
graph=None)``; the window now instantiates that factory like any other
host, and the Library's bottom-left dock instantiates the same one. It
is still built inside a function (``QWidget`` must be a real base class
and this module must import with no Qt), and deliberately not memoized —
a cached class would freeze onto whichever ``aqt.qt`` was imported
first, which the tests swap underneath it on purpose. The canvas also
stopped declaring a minimum size: how small the map may get is the
HOST's decision (the window wants 480x360; the dock is a compact box,
and inheriting 480 would have widened the Library's whole left pane).
``graph_data()`` is public for the same card: building the graph is
16.9 s on a 28,668-note collection, so the dock builds it off the main
thread and passes it in rather than letting the factory load it.

**K-148 made it 3D, and the point of it is the vibe.** Pouya: "make that
3D and have it slightly rotate... when I press on a PDF, it zooms in on
that PDF and shows all the connections and the cards. I just want it to
be a vibe, like you're in cyberspace or the matrix. There's no purpose
other than making it look cool." That IS the requirement; it is not
standing in for something measurable.

The renderer stays native QPainter — no webview. ``map_canvas`` has two
hosts and K-143's whole point was one renderer; WebGL would either fork
it or put a Chromium GPU context in a 545x185 dock, and it would inherit
Anki's software-video-driver path anyway. Qt3D is not in Anki's bundle.

The trick that makes 3D cost nothing is DEPTH BANDS. A yaw plus a
perspective divide is, for any set of points SHARING a z, a plain 2D
projective map: the divisor ``w = (d - z*cos0) + x*sin0`` is linear in x,
which is exactly what ``QTransform``'s m13 term is for. So the note cloud
is quantized into ``DEPTH_BANDS`` slabs ONCE, and each frame issues one
matrix + one ``QTransform.map`` + one ``drawPoints`` per slab — 256
matrices in Python, not 28,668 points. Measured here, offscreen, 28,668
notes at 900x640: 2.75 ms/frame for the old 2D affine, 2.89 ms for the
full 3D with perspective and fog, 11.56 ms for the honest per-point
Python loop. The whole canvas paints in 4.4 ms; the 3D costs about a
tenth of a millisecond over the flat map it replaces.

**K-138's pinned rule gets MORE load-bearing here, not less**: the
transform goes on the POLYGON, never on the painter. A cosmetic pen under
a scaled painter degenerates ``drawPoints`` into horizontal strokes at
deep zoom — and a painter cannot carry a perspective divide to a cosmetic
pen at all.

Two traps found by measuring, both of which look free and are not.
Depth fog as ALPHA costs 13.8 ms a frame against 2.9 for the same ramp
mixed OPAQUE (5x, for a picture the eye cannot tell apart), so the fog
blends two palette tokens instead. And round dots: the identical draw
with ``RoundCap`` is 54.6 ms a frame against 3.4 — Qt strokes every cap
as a real path — so the dots stay square, and small enough not to read
as blocks. One trap found by RENDERING: fog keyed on z came out one flat
mid-grey on the real 28,668-note index, because a PCA score is
Gaussian-ish and the axis is normalized to its outliers. ``fog_shades``
spends the ramp on the cloud's own depth histogram instead; the synthetic
uniform cube it was first tuned on hid that completely.

Motion. The standalone window sways slowly around ``REST_ANGLE`` (not a
full spin: a spin sweeps through the edge-on pose where the cloud
collapses to a line, and past ~60 degrees the depth quantization starts
to show as slabs). The Library's dock renders the SAME scene STILL —
Pouya's explicit call, so nothing moves in the corner of his eye while he
works — which is why idle rotation is opt-in per host and the window is
the only caller. Clicking a PDF flies the camera to its own cluster
(``fly_to``, a ``QPropertyAnimation`` on OutCubic — md3_switch's shape);
``select_pdf``, the PDF viewer's seam, keeps its gentler K-138 contract
and never rearranges your view of a file you just opened. Anki's Reduce
Motion preference stops the sway and lands the flight in one frame; the
scene stays 3D, perspective and fog either way. And the rotation timer is
armed from ``showEvent`` through a child timer, never from the
constructor: md3_switch documents the SIGSEGV that repainting a widget
mid-composite causes.

Opening the map no longer freezes Anki (K-144, absorbed here). The window
appears immediately showing ``BUILDING_TEXT`` and a ``QueryOp`` worker
fills it in — the same shape the dock already uses — because the graph build,
26.6 s on the live collection with three components (17 s with two),
used to run inline.

Everything above the "aqt glue" divider is pure and aqt-free — the whole
viewport model (the camera, depth bands and fog ramp included:
world<->screen transform, fit-to-view, zoom-at-cursor, hit-test, node
sizing, edge-subset policy, off-node label placement, and the off-view
recentre rule) — for ``tests/test_pdf_map.py``. The glue imports aqt
lazily inside its functions (retention_history's pattern), so importing
this module never needs Qt at all.

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

Entry points: ``open_map_window(parent=None)`` (the Library's Map
button), ``map_canvas(parent, graph=None)`` + ``graph_data()`` (the
Library's dock), and ``select_pdf(safe)`` (the standalone window's
follow-the-viewer seam; the dock calls ``canvas.select`` on its own
canvas, which is where that contract actually lives). On the canvas
itself: ``set_idle_rotation(want)`` (opt-in, window only) and
``fly_to(safe)`` (what a click does).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# ── viewport model ───────────────────────────────────────────────────────

# Empty-graph fallback bounds — projection normalizes each axis to
# [-1, 1]. Six numbers since K-148: (min_x, min_y, min_z, max_x, max_y,
# max_z). The 2D four-number form still exists one layer down, as what
# the camera projects a box INTO (see camera_bounds).
DEFAULT_BOUNDS = (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)
# Pixels of breathing room fit_to_view leaves around the content bounds,
# and the share of the smaller viewport axis that caps it on a compact
# canvas (see fit_margin — 0.12 keeps 48px intact above ~400px, which is
# every surface that existed before the Library dock).
FIT_MARGIN = 48.0
FIT_MARGIN_SHARE = 0.12
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
# Gap in px between a node's edge and its label box. Sized to clear the
# selected node's ring (drawn at r + 3 with a 2px pen, so outer edge
# r + 4) with daylight left over.
LABEL_GAP = 9.0
# Baseline nudge that sits an 11px label on the node's centre line.
LABEL_BASELINE_DY = 4.0
EDGE_ALPHA = 0.25
# One standard wheel notch (angleDelta 120) zooms by 2**(120/240) ≈ 1.41.
WHEEL_ZOOM_DIVISOR = 240.0
# select_pdf recentres only when the node is outside the viewport inset
# by this much — a node already comfortably on screen must not make the
# map jump under the reader every time the PDF viewer changes file.
RECENTER_MARGIN = 24.0

# ── the camera (K-148) ───────────────────────────────────────────────────
# Eye distance from the z=0 plane, in world units. The cloud is a
# [-1, 1] cube, so the nearest possible point sits at d - sqrt(2) and the
# farthest at d + sqrt(2): at 2.6 that is a 1.19..4.01 depth range, i.e.
# the nearest dots draw ~3.4x larger than the farthest. Lower is more
# vertiginous and starts to fish-eye; higher flattens back toward the 2D
# map. Never let it approach sqrt(2), where w reaches zero and the
# projection blows up (CAM_W_FLOOR is the seatbelt, not the plan).
CAM_DISTANCE = 2.6
CAM_W_FLOOR = 0.2
# The pose the scene RESTS in — not zero, because zero is exactly the old
# flat map and the Library's dock renders this scene STILL (Pouya's
# explicit call: no idle spin while he works). A dock that never moves
# has to read as 3D in a single frame, and this is the yaw that does it.
REST_ANGLE = 0.30
# Idle rotation: a slow sway around REST_ANGLE, not a full spin. A spin
# sweeps through the edge-on pose where a flat-ish cloud collapses to a
# line — and past ~60 degrees the depth quantization below starts to
# show as slabs. A sway keeps constant parallax, never flattens, and is
# what "slightly rotate" actually asks for.
IDLE_SWING = 0.42
IDLE_PERIOD_MS = 24000.0
IDLE_TICK_MS = 33  # ~30 fps; the whole frame measures 2.9 ms
# Never repaint into a window that is still being composited — md3_switch
# documents the SIGSEGV that causes (QBackingStore::flush on a paint
# device that does not exist yet). The canvas arms its timer from
# showEvent and this delay lets the first real frame land first.
IDLE_START_DELAY_MS = 300
# How many depth slabs the note cloud is quantized into. This is THE
# trick that makes 3D affordable: every point in one slab shares a z, and
# a rotation + perspective divide over a shared z is a plain 2D
# PROJECTIVE map (w = d - z*cos0 + x*sin0 is linear in x, which is
# exactly QTransform's m13 term). So the per-frame Python work is
# DEPTH_BANDS matrices, not one per point — 28,668 dots cost 2.9 ms a
# frame, against 11.6 ms for the honest per-point Python loop.
# The price is that a point is drawn at its BAND's depth, not its own:
# the error is at most scale*|sin0|/DEPTH_BANDS pixels, so 256 bands
# keeps it under a pixel at fit zoom — below the dot size, invisible.
# Measured cost of the count itself: 2.89 ms at 64 bands, 3.11 at 256,
# 3.34 at 512. It is very nearly free, so buy the resolution.
DEPTH_BANDS = 256
# Depth fog: how far along the grey_mid->text ramp a band's dots are
# painted, from the back of the cloud to the front (see fog_shades,
# which spends that ramp on the cloud's own depth histogram rather than
# on z). FOG_GAMMA > 1 holds the middle back so only the genuinely near
# dots go to full ink. **Fog is OPAQUE colour, never alpha** — measured
# on this machine, 28,668 dots with a semi-transparent pen cost 13.8 ms
# a frame against 2.9 ms for the same ramp mixed to opaque against the
# ground. Alpha would have quietly made the 3D map 5x dearer than the 2D
# one, for a picture the eye cannot tell apart.
FOG_NEAR = 1.0
FOG_FAR = 0.06
FOG_GAMMA = 1.35
# Dot size also carries depth: the band's own perspective factor, so the
# near face of the cloud is chunkier than the far face.
DOT_DEPTH_MIN = 0.62
DOT_DEPTH_MAX = 1.45
# Click-to-fly: how long the camera takes to reach a clicked PDF, and
# how much air is left around its matched notes when it lands.
FLY_MS = 620
FLY_PADDING = 1.25

EMPTY_TEXT = "No indexed PDFs to map yet."
# Shown where the canvas would go when map_canvas() comes back None —
# Qt or theme unreachable. Rare, but a bar with a dead hole under it
# reads as a bug in the map rather than as the map being unavailable.
CANVAS_FAIL_TEXT = "The map canvas could not be created."
# What the Library's dock shows while graph_data() runs on its worker,
# and if that worker comes back empty-handed. The copy lives here with
# the other two map states so no host invents its own wording.
BUILDING_TEXT = "Building the map…"
BUILD_FAIL_TEXT = "The map could not be built."
# The header's one-line affordance (K-133): the offscreen-render audit
# found a view that named nothing and explained nothing — no hint that
# dots are notes, circles PDFs, or that the canvas pans and zooms.
# K-138 rewrote the middle clause, because hovering is now how you get a
# NAME, not just a trace — and kept it a hair shorter than K-133's, since
# a plain QLabel's layout minimum is its text width (see the window).
HINT_TEXT = (
    "Circles are PDFs, dots are notes — hover to name, "
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


# ── the camera: 3D world -> the viewport's 2D plane ──────────────────────
# The whole 3D map is this one factorization: a point's (x, y, z) becomes
# a CAMERA-PLANE (u, v) that the existing 2D Viewport then pans and zooms
# exactly as before. Everything downstream — fit, pan, zoom-at-cursor,
# hit-testing, label placement, the recentre rule — keeps working on
# (u, v) without knowing depth exists.


@dataclass(frozen=True)
class Camera:
    """Yaw around the vertical axis, plus the eye distance that sets how
    strong the perspective is. Frozen like Viewport: a new pose is a new
    Camera, which is what makes the rotation trivially testable."""

    angle: float = REST_ANGLE
    distance: float = CAM_DISTANCE


def camera_point(cam: Camera, x: float, y: float, z: float) -> tuple:
    """``(u, v, depth)`` for one world point.

    Yaw about the vertical axis, then divide by the eye distance:

        x_rot = x*cos0 + z*sin0        w = d - z_rot
        z_rot = z*cos0 - x*sin0        depth = d / w
        u = x_rot * depth              v = y * depth

    ``depth`` is the perspective magnification — exactly 1.0 on the z=0
    plane, larger toward the eye, smaller away from it — and it is what
    sizes dots and nodes and mixes the fog.

    At angle 0 and z 0 this is the identity, so the flat map is a pose of
    the 3D one rather than a separate code path: the same
    ``vp.scale`` still means the same pixels per world unit.
    """
    ct = math.cos(cam.angle)
    st = math.sin(cam.angle)
    d = float(cam.distance)
    w = d - (z * ct - x * st)
    if w < CAM_W_FLOOR:
        w = CAM_W_FLOOR  # never divide by ~0 on a junk coordinate
    depth = d / w
    return ((x * ct + z * st) * depth, y * depth, depth)


def project_point(vp: Viewport, cam: Camera, x: float, y: float, z: float):
    """``(sx, sy, depth)`` — the full world -> screen path for ONE point.

    Used for the handful of things that are not the note cloud (PDF
    nodes, edge endpoints, hit-testing). The cloud itself never comes
    through here: 28,668 Python calls a frame is the 11.6 ms loop this
    card exists to avoid.
    """
    u, v, depth = camera_point(cam, x, y, z)
    sx, sy = world_to_screen(vp, u, v)
    return (sx, sy, depth)


def band_index(z: float, bands: int = DEPTH_BANDS) -> int:
    """Which depth slab a z in [-1, 1] belongs to. Out-of-range z clamps
    into the end slabs rather than raising or wrapping."""
    if bands <= 1:
        return 0
    i = int((_num(z) + 1.0) * 0.5 * bands)
    return 0 if i < 0 else bands - 1 if i >= bands else i


def band_z(index: int, bands: int = DEPTH_BANDS) -> float:
    """The z every point in slab ``index`` is drawn at — its centre, so
    the quantization error is symmetric (±1/bands) instead of one-sided."""
    if bands <= 1:
        return 0.0
    return -1.0 + (index + 0.5) * 2.0 / bands


def band_matrix(vp: Viewport, cam: Camera, zb: float) -> tuple:
    """The nine QTransform coefficients that project a whole slab.

    THE point of the card. For a fixed z the perspective divisor

        w = (d - z*cos0) + x*sin0

    is linear in x, and a linear divisor is precisely what a projective
    3x3 matrix does — so an entire slab of points goes through Qt's own
    C++ ``QTransform.map`` in one call, with no Python per point.
    Substituting w into ``camera_point`` and folding in the viewport
    (screen = offset + scale * camera-plane) gives, with A = d - z*cos0,
    B = sin0 and S = scale*d:

        sx = ((ox*B + S*cos0)*x + (ox*A + S*z*sin0)) / (B*x + A)
        sy = ((oy*B)*x + S*y + oy*A)                 / (B*x + A)

    Returned in Qt's constructor order (m11, m12, m13, m21, m22, m23,
    m31, m32, m33), where Qt maps
    ``x' = (m11*x + m21*y + m31) / (m13*x + m23*y + m33)``.

    Returned as plain floats, not a QTransform, so the derivation is
    testable with no Qt in the room — and pinned against
    ``project_point`` on real Qt, which is the only way to catch a
    transposed pair.
    """
    ct = math.cos(cam.angle)
    st = math.sin(cam.angle)
    d = float(cam.distance)
    a = d - float(zb) * ct
    s = vp.scale * d
    return (
        vp.ox * st + s * ct, vp.oy * st, st,
        0.0, s, 0.0,
        vp.ox * a + s * float(zb) * st, vp.oy * a, a,
    )


def band_order(cam: Camera, count: int) -> range:
    """Slab indices in painter's order — farthest first.

    A slab's depth is ``z * cos0``, so which end of the stack is nearest
    flips with the sign of cos0. Without this the far half of the cloud
    would paint OVER the near half every time the sway crossed the
    quarter turn, which reads as the cloud turning inside out.
    """
    if math.cos(cam.angle) > 0:
        return range(count - 1, -1, -1)
    return range(count)


def fog_shades(counts: Sequence[int]) -> list:
    """One fog value per depth band, calibrated to the cloud's OWN depth
    histogram: ``counts`` is how many notes each band holds, near-last.

    Rendered on the live 28,668-note index before this existed and the
    whole thing came out one flat mid-grey. A PCA score is Gaussian-ish
    with long thin tails, and ``_normalize_axis`` stretches the range to
    the OUTLIERS — so on real data four notes in five sit inside the
    middle third of z, get nearly the same shade, and the depth the
    geometry is faithfully computing never reaches the eye. A synthetic
    uniform cube (what this was tuned on first) hides that completely.

    So the ramp is spent where the notes actually are: a band's shade is
    the share of the cloud lying behind it. The median-depth note lands
    mid-ramp by construction, on any cloud shape. This is the fog only —
    positions and dot sizes stay geometric, so nearer is still bigger and
    still darker, and nothing about the projection is fudged to look
    better.
    """
    total = 0
    for n in counts:
        try:
            total += max(0, int(n))
        except (TypeError, ValueError):
            continue
    if total <= 0:
        return [FOG_NEAR for _ in counts]
    out: list = []
    seen = 0
    for n in counts:
        try:
            c = max(0, int(n))
        except (TypeError, ValueError):
            c = 0
        # The band's MIDPOINT in the cumulative distribution, so the
        # nearest band is not forced to exactly 1.0 and the farthest to
        # exactly 0.0 by an off-by-one at the ends.
        t = (seen + c / 2.0) / total
        seen += c
        out.append(FOG_FAR + (FOG_NEAR - FOG_FAR) * (t ** FOG_GAMMA))
    return out


def blend_hex(far: str, near: str, t: float) -> str:
    """Two ``#rrggbb`` palette tokens mixed ``t`` of the way from ``far``
    to ``near``, as ``#rrggbb``.

    Fog HAS to be an opaque mix rather than alpha over the ground: the
    same 28,668 dots cost 13.8 ms a frame with a semi-transparent pen and
    2.9 ms with an opaque one (measured, this machine, offscreen). Both
    ends are theme tokens, so the ramp re-colours with the palette and
    this file still contains no colour of its own.
    """
    try:
        a = far.lstrip("#")
        b = near.lstrip("#")
        m = _clamp(_num(t), 0.0, 1.0)
        out = []
        for i in (0, 2, 4):
            ca = int(a[i:i + 2], 16)
            cb = int(b[i:i + 2], 16)
            out.append(int(round(ca + (cb - ca) * m)))
        return "#%02x%02x%02x" % tuple(out)
    except Exception:
        return near


def fit_margin(widget_size: Sequence[float]) -> float:
    """``FIT_MARGIN``, capped at a share of the SMALLER viewport axis.

    K-143, found by rendering the Library dock rather than by reading
    the code: FIT_MARGIN is 48 absolute pixels, sized for a 900x640
    window where it is comfortable breathing room. In the dock's compact
    box — 545x185 in the default Library — 48px a side eats 96 of 185
    and the whole graph fits into the 89px left over, a stamp adrift in
    a wide empty card. The margin has to be a fraction of the surface it
    is edging, not a constant.

    A share of ``min(w, h)`` rather than of each axis on purpose:
    ``fit_to_view`` picks ONE scale from whichever axis constrains, so
    two different margins would only ever matter through the smaller one
    anyway, and a per-axis version would silently re-centre the other.
    Below about 400px the cap bites and the margin scales down with the
    box; above it, nothing changes and every existing surface fits
    exactly as it did.
    """
    try:
        smaller = min(float(widget_size[0]), float(widget_size[1]))
    except (TypeError, ValueError, IndexError):
        return FIT_MARGIN
    if smaller != smaller or smaller <= 0:  # NaN or no surface yet
        return FIT_MARGIN
    return min(FIT_MARGIN, FIT_MARGIN_SHARE * smaller)


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


def parse_xyz(value: object) -> Optional[tuple]:
    """``[x, y, z]`` -> ``(float, float, float)``; None for anything
    malformed.

    A TWO-component row is accepted and lands on the z=0 plane. That is
    not laxity: ``map_canvas(parent, graph)`` is a public seam that hosts
    hand a dict to, the key was ``xy`` with two numbers until K-148, and
    a graph one number short should render flat rather than render
    nothing at all.
    """
    try:
        x = float(value[0])  # type: ignore[index]
        y = float(value[1])  # type: ignore[index]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    try:
        z = float(value[2])  # type: ignore[index]
    except (TypeError, ValueError, IndexError, KeyError):
        z = 0.0
    if x != x or y != y or z != z:  # NaN never gets a position
        return None
    return (x, y, z)


def row_xyz(row: object) -> Optional[tuple]:
    """One graph row's position — ``xyz`` since K-148, ``xy`` before it
    (see parse_xyz). The ONE place either spelling is read."""
    if not isinstance(row, dict):
        return None
    v = row.get("xyz")
    if v is None:
        v = row.get("xy")
    return parse_xyz(v)


def bounds_of(
    points: Iterable[Sequence], fallback: Sequence[float] = DEFAULT_BOUNDS
) -> tuple:
    """Bounding box ``(min_x, min_y, min_z, max_x, max_y, max_z)`` of
    ``points``; ``fallback`` when no point parses. Malformed points are
    skipped, not fatal — one bad row must never blank the whole map."""
    xs: list = []
    ys: list = []
    zs: list = []
    for p in points:
        xyz = parse_xyz(p)
        if xyz is not None:
            xs.append(xyz[0])
            ys.append(xyz[1])
            zs.append(xyz[2])
    if not xs:
        return tuple(float(v) for v in fallback)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def graph_bounds(graph: dict) -> tuple:
    """Bounding box over every positioned note AND pdf node in a
    ``build_graph_data`` dict (pdf centroids always lie inside the note
    cloud today, but measuring both keeps that a fact, not a load-bearing
    assumption)."""
    pts = []
    for row in list(graph.get("notes") or []) + list(graph.get("pdfs") or []):
        if isinstance(row, dict):
            pts.append(row.get("xyz", row.get("xy")))
    return bounds_of(pts)


def camera_bounds(box: Sequence[float], cam: Camera) -> tuple:
    """A 3D box projected to the camera plane: ``(min_u, min_v, max_u,
    max_v)`` — what ``fit_to_view`` needs to frame that box at this pose.

    Only the eight CORNERS are projected, and that is exact rather than a
    shortcut: ``camera_point`` is a projective map, a ratio of linear
    functions, so on a box (with the divisor nowhere zero — see
    CAM_W_FLOOR) its extremes are attained at vertices. Eight points a
    frame instead of 28,668, with no approximation to apologise for.
    """
    try:
        x0, y0, z0, x1, y1, z1 = (float(v) for v in box)
    except (TypeError, ValueError):
        x0, y0, z0, x1, y1, z1 = DEFAULT_BOUNDS
    us: list = []
    vs: list = []
    for x in (x0, x1):
        for y in (y0, y1):
            for z in (z0, z1):
                u, v, _d = camera_point(cam, x, y, z)
                us.append(u)
                vs.append(v)
    return (min(us), min(vs), max(us), max(vs))


def frame_bounds(
    box: Sequence[float], cam: Camera, widget_size: Sequence[float]
) -> Viewport:
    """The viewport that frames a 3D box at this camera pose — the ONE
    path every fit takes (initial, Fit button, click-to-fly), so the
    compact-canvas margin cap reaches all of them."""
    return fit_to_view(
        camera_bounds(box, cam), widget_size, fit_margin(widget_size)
    )


def lerp_viewport(
    a: Viewport, b: Viewport, t: float, widget_size: Sequence[float]
) -> Viewport:
    """The camera partway through a flight from ``a`` to ``b``.

    Scale interpolates GEOMETRICALLY and the world point under the screen
    centre interpolates linearly. Geometric because zoom is multiplicative
    — a linear ramp from 200 to 2000 px/unit spends most of the flight
    already arrived, which reads as a lurch and then a crawl. The easing
    curve on top is the caller's (OutCubic, md3_switch's).
    """
    m = _clamp(_num(t), 0.0, 1.0)
    w = _num(widget_size[0]) if len(widget_size) > 0 else 0.0
    h = _num(widget_size[1]) if len(widget_size) > 1 else 0.0
    sa = a.scale if a.scale > 0 else MIN_SCALE
    sb = b.scale if b.scale > 0 else MIN_SCALE
    scale = _clamp(sa * (sb / sa) ** m, MIN_SCALE, MAX_SCALE)
    cx, cy = w / 2.0, h / 2.0
    ax, ay = screen_to_world(a, cx, cy)
    bx, by = screen_to_world(b, cx, cy)
    wx = ax + (bx - ax) * m
    wy = ay + (by - ay) * m
    return Viewport(scale, cx - wx * scale, cy - wy * scale)


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


def recenter_for(
    vp: Viewport,
    world_pt: Sequence[float],
    widget_size: Sequence[float],
    margin: float = RECENTER_MARGIN,
) -> Viewport:
    """The viewport ``select_pdf`` should adopt to reveal ``world_pt``.

    ``world_pt`` is a CAMERA-PLANE point (``camera_point``'s u, v), not a
    raw 3D one: where a node sits on screen depends on the camera's pose,
    so "is it already in view" is a question about the projected point.
    Any z component is ignored rather than rejected.

    Returns ``vp`` UNCHANGED when the point already sits inside the
    widget inset by ``margin`` — following the PDF viewer must not yank
    the map out from under someone who can already see the node. When it
    is outside (or the widget has no usable size yet), the point is
    centred. The ZOOM is never touched: the reader's chosen scale is
    theirs, and a jump plus a zoom change at once loses all sense of
    where the view went.
    """
    pt = parse_xyz(world_pt)
    if pt is None:
        return vp
    w = _num(widget_size[0]) if len(widget_size) > 0 else 0.0
    h = _num(widget_size[1]) if len(widget_size) > 1 else 0.0
    sx, sy = world_to_screen(vp, pt[0], pt[1])
    m = max(0.0, _num(margin, RECENTER_MARGIN))
    if w > 2.0 * m and h > 2.0 * m:
        if m <= sx <= w - m and m <= sy <= h - m:
            return vp
    return Viewport(vp.scale, w / 2.0 - pt[0] * vp.scale,
                    h / 2.0 - pt[1] * vp.scale)


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


def graph_data() -> dict:
    """The map's data: the on-disk graph plus the live retention fill.

    Public because building it is EXPENSIVE — 16.9 s on Pouya's 28,668
    note collection (measured K-143; the PCA over the whole card index
    dominates). The standalone window has always paid that inline, but
    the Library's dock cannot: it would freeze the Library for 17 s on
    every open. So pdf_drive runs THIS off the main thread and hands the
    result to ``map_canvas(parent, graph)`` — which is exactly why that
    factory takes a graph at all.
    """
    graph = _load_graph()
    _fill_retention(graph)
    return graph


def _canvas_class():
    """Build and return the canvas class, or None if Qt is unreachable.

    The class body lives inside a function for the same reason it always
    did: ``QWidget`` has to be a real base class, and this module must
    stay importable with no Qt at all (the pure viewport model above the
    divider is tested headless). Hoisting it out of ``open_map_window``
    into its own builder is the whole K-143 change — the window and the
    Library's dock now instantiate the SAME definition instead of the
    dock growing a second renderer to drift away from this one.

    Deliberately NOT memoized. Rebuilding costs microseconds, while a
    cached class would be frozen onto whichever ``aqt.qt`` was imported
    first — and the tests swap that module underneath us on purpose
    (stub harness first, real PyQt6 after).
    """
    try:
        from aqt.qt import (
            QColor,
            QEasingCurve,
            QPainter,
            QPainterPath,
            QPen,
            QPointF,
            QPolygonF,
            QPropertyAnimation,
            QRectF,
            Qt,
            QTimer,
            QToolTip,
            QTransform,
            QWidget,
            pyqtProperty,
        )

        from . import theme
    except Exception as exc:
        print(f"[klausmate] embedding map canvas unavailable: {exc}")
        return None

    class _MapCanvas(QWidget):
        """The QPainter canvas: the whole renderer, hand-painted (no
        QtCharts/QGraphicsView in Anki's bundle worth dragging in for
        dots and lines). Colours re-read theme.palette per paint so a
        night flip catches up on the next repaint."""

        def __init__(self, graph_dict: dict, parent_widget=None) -> None:
            super().__init__(parent_widget)
            self._notes: list = []
            self._note_xyz: dict = {}
            self._pdfs: list = []
            self._pdf_xyz: dict = {}
            self._pdf_by_safe: dict = {}
            self._edges: list = []
            for n in graph_dict.get("notes") or []:
                xyz = row_xyz(n)
                if xyz is None:
                    continue
                self._notes.append(xyz)
                try:
                    self._note_xyz[int(n.get("nid"))] = xyz
                except (TypeError, ValueError):
                    continue
            for p in graph_dict.get("pdfs") or []:
                xyz = row_xyz(p)
                safe = p.get("safe") if isinstance(p, dict) else None
                if xyz is None or not safe:
                    continue
                self._pdfs.append(p)
                self._pdf_xyz[str(safe)] = xyz
                self._pdf_by_safe[str(safe)] = p
            self._edges = [
                e for e in graph_dict.get("edges") or [] if isinstance(e, dict)
            ]
            # The note layer, built ONCE in WORLD space (K-138), now as
            # one polygon PER DEPTH BAND (K-148). Every frame hands each
            # band to QTransform.map, which transforms its points in
            # C++; the Python per-dot loop this replaces is 11.6 ms a
            # frame in 3D against 2.9 for the whole banded draw. World
            # space, not screen: it is the camera and viewport that
            # change per frame, not the cloud.
            buckets: dict = {}
            for x, y, z in self._notes:
                buckets.setdefault(band_index(z), []).append(QPointF(x, y))
            self._bands = [
                (band_z(i), QPolygonF(pts))
                for i, pts in sorted(buckets.items())
            ]
            self._band_pens: list = []
            self._pens_night = None
            self._bounds = graph_bounds(graph_dict)
            # DOT_DEPTH_MAX, because a node at the front of the cloud
            # DRAWS that much bigger than node_radius says (K-148).
            # Without it the nearest — biggest, most clickable-looking —
            # circles have a dead ring around their rim.
            self._hit_radius = (
                max(node_radius(p.get("match_count")) for p in self._pdfs)
                if self._pdfs
                else NODE_R_MIN
            ) * DOT_DEPTH_MAX + HIT_SLOP

            self._vp = Viewport()
            self._cam = Camera()
            self._did_fit = False
            self._hover = None
            self._selected = None
            self._dragging = False
            self._drag_moved = False
            self._drag_last = None
            # Idle rotation is OPT-IN per host: the standalone window
            # asks for it, the Library's dock renders the same scene
            # STILL (Pouya's explicit call — nothing should be moving in
            # the corner of his eye while he works). Nothing starts here
            # either way; the timer is armed from showEvent.
            self._idle_want = False
            self._phase = 0.0
            self._idle = QTimer(self)
            self._idle.setInterval(IDLE_TICK_MS)
            self._idle.timeout.connect(self._idle_tick)
            # A CHILD timer rather than QTimer.singleShot: it is
            # destroyed with the widget, so a canvas closed during the
            # delay cannot fire a callback into a deleted C++ object.
            self._idle_arm = QTimer(self)
            self._idle_arm.setSingleShot(True)
            self._idle_arm.timeout.connect(self._idle_start_now)
            self._fly = 0.0
            self._fly_from = None
            self._fly_to = None
            self._fly_anim = QPropertyAnimation(self, b"fly", self)
            self._fly_anim.setDuration(FLY_MS)
            self._fly_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            try:
                self.setMouseTracking(True)
            except Exception as exc:
                print(f"[klausmate] map canvas setup failed: {exc}")
            # NO setMinimumSize here (K-143). How small the map may get
            # belongs to whatever is hosting it: the standalone window
            # wants 480x360, the Library's dock is a compact box that
            # would otherwise inherit a 480px floor and shove the whole
            # left pane wider. Each host sets its own, right where it
            # adds the canvas.

        # ---- motion (K-148: the first per-frame animation in Klaus) ----

        def _reduce_motion(self) -> bool:
            """Anki's own Reduce Motion preference — md3_switch's rule,
            and the third place in this addon that honours it. Nothing
            here degrades when it is on: the scene is still 3D, still
            perspective, still fogged. It simply stops moving by itself
            and arrives at a clicked PDF instead of flying there."""
            try:
                from aqt import mw

                return bool(mw.pm.reduce_motion())
            except Exception:
                return False

        def set_idle_rotation(self, want: bool) -> None:
            """Ask for (or cancel) the slow sway. The HOST decides:
            the standalone window turns it on, the Library's dock never
            does. Only an actually-visible canvas gets a running timer,
            so this can be called at any point in construction."""
            self._idle_want = bool(want)
            if self._idle_want and self.isVisible():
                self._arm_idle()
            elif not self._idle_want:
                self._idle.stop()
                self._idle_arm.stop()

        def _arm_idle(self) -> None:
            """Start the sway a beat AFTER the surface appears.

            md3_switch's SIGSEGV, which is the reason this is not a plain
            ``start()``: repainting a widget while its window is still
            being composited hands Qt's Cocoa backing-store flush a paint
            device that does not exist yet. A single-shot delay lets the
            first real frame land, and the delayed callback re-checks
            visibility because the window may be gone by then.
            """
            if not self._idle_want or self._reduce_motion():
                return
            if self._idle.isActive() or self._idle_arm.isActive():
                return
            self._idle_arm.start(IDLE_START_DELAY_MS)

        def _idle_start_now(self) -> None:
            """The delay expired — start only if this canvas is STILL
            wanted and still on screen (the window may have closed, or
            the dock been collapsed, while we waited)."""
            try:
                if self._idle_want and self.isVisible():
                    self._idle.start()
            except Exception as exc:
                print(f"[klausmate] map idle start failed: {exc}")

        def _idle_tick(self) -> None:
            """One frame of the sway: advance the phase, re-pose the
            camera, repaint. A canvas that has been hidden (another tab,
            a minimised window) stops paying for frames nobody sees."""
            try:
                if not self.isVisible():
                    self._idle.stop()
                    return
                self._phase += 2.0 * math.pi * IDLE_TICK_MS / IDLE_PERIOD_MS
                if self._phase > 2.0 * math.pi:
                    self._phase -= 2.0 * math.pi
                self._cam = Camera(
                    REST_ANGLE + IDLE_SWING * math.sin(self._phase),
                    self._cam.distance,
                )
                self.update()
            except Exception as exc:
                print(f"[klausmate] map idle tick failed: {exc}")
                self._idle.stop()

        # The flight's animated property. Qt drives 0 -> 1 through
        # OutCubic; every frame re-derives the viewport from the two
        # endpoints, so an interrupted flight (a second PDF clicked
        # mid-air) just becomes the start of the next one.
        def _get_fly(self) -> float:
            return self._fly

        def _set_fly(self, value: float) -> None:
            self._fly = float(value)
            if self._fly_from is None or self._fly_to is None:
                return
            self._vp = lerp_viewport(
                self._fly_from, self._fly_to, self._fly,
                (float(self.width()), float(self.height())),
            )
            if self.isVisible():
                self.update()

        fly = pyqtProperty(float, _get_fly, _set_fly)

        def _fly_target(self, safe: str) -> Optional[Viewport]:
            """Where the camera should land to show ``safe`` "and all the
            connections and the cards" — the box holding that PDF's node
            AND every note it matched, framed at the current pose.

            Never wider than the whole graph: clicking a PDF whose
            matches are scattered would otherwise zoom OUT past the fit,
            which is not what pressing on a thing means.
            """
            node = self._pdf_xyz.get(safe)
            if node is None:
                return None
            pts = [node]
            for e in edges_for_selection(self._edges, safe):
                try:
                    p = self._note_xyz.get(int(e.get("nid")))
                except (TypeError, ValueError):
                    continue
                if p is not None:
                    pts.append(p)
            box = bounds_of(pts)
            cx = (box[0] + box[3]) / 2.0
            cy = (box[1] + box[4]) / 2.0
            cz = (box[2] + box[5]) / 2.0
            pad = FLY_PADDING
            box = (
                cx + (box[0] - cx) * pad, cy + (box[1] - cy) * pad,
                cz + (box[2] - cz) * pad, cx + (box[3] - cx) * pad,
                cy + (box[4] - cy) * pad, cz + (box[5] - cz) * pad,
            )
            size = (float(self.width()), float(self.height()))
            target = frame_bounds(box, self._cam, size)
            floor = frame_bounds(self._bounds, self._cam, size).scale
            if target.scale < floor:
                target = frame_bounds(self._bounds, self._cam, size)
            return target

        def fly_to(self, safe: str) -> bool:
            """Fly the camera to a PDF; True when there was one to fly
            to. Pouya's ask in his own words: "when I press on a PDF, it
            zooms in on that PDF and shows all the connections and the
            cards. When I press another PDF, it zooms in on that PDF."
            """
            try:
                self._ensure_fit(float(self.width()), float(self.height()))
                target = self._fly_target(safe)
                if target is None:
                    return False
                self._fly_anim.stop()
                if self._reduce_motion() or not self.isVisible():
                    self._fly_from = self._fly_to = None
                    self._vp = target
                    self.update()
                    return True
                self._fly_from = self._vp
                self._fly_to = target
                self._fly = 0.0
                self._fly_anim.setStartValue(0.0)
                self._fly_anim.setEndValue(1.0)
                self._fly_anim.start()
                return True
            except Exception as exc:
                print(f"[klausmate] map fly failed: {exc}")
                return False

        def showEvent(self, event) -> None:  # noqa: N802 — Qt override
            try:
                self._arm_idle()
            except Exception:
                pass
            try:
                super().showEvent(event)
            except Exception:
                pass

        def hideEvent(self, event) -> None:  # noqa: N802 — Qt override
            try:
                self._idle.stop()
                self._idle_arm.stop()
            except Exception:
                pass
            try:
                super().hideEvent(event)
            except Exception:
                pass

        # ---- viewport ----

        def _apply_fit(self, w: float, h: float) -> None:
            # The fit SCALE used to be kept for the label zoom gate;
            # K-138 deleted that gate, and keeping a field named for it
            # would only mislead the next reader.
            # frame_bounds, never fit_to_view directly (K-148): the
            # graph is a 3D box and where it lands on screen depends on
            # the camera's pose. It also carries fit_margin rather than
            # the bare FIT_MARGIN constant (K-143) — 48px a side is
            # breathing room in the window and half the canvas in the
            # Library's dock — so every fit gets the cap.
            self._vp = frame_bounds(self._bounds, self._cam, (w, h))
            self._did_fit = True

        def _ensure_fit(self, w: float, h: float) -> None:
            if not self._did_fit and w > 1 and h > 1:
                self._apply_fit(w, h)

        def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
            """Keep the centre world-point centred as the surface changes.

            K-143, caught by rendering the dock at its floor: the fit
            runs ONCE and nothing touched the viewport afterwards, so
            shrinking the surface left the graph anchored where it was —
            in the dock, where dragging the splitter IS the everyday
            interaction, the picture slid out of the bottom of the box
            and took the selected node's name with it.

            Half the size delta, not a re-fit: a resize must not throw
            away the pan and zoom the reader chose (that is what the Fit
            button is for, and the standalone window resizes too). The
            first resize arrives before any fit — oldSize() is invalid
            then — and is left alone so the first paint still fits at
            the final size.
            """
            try:
                old = event.oldSize()
                if self._did_fit and old.width() > 0 and old.height() > 0:
                    self._vp = pan_by(
                        self._vp,
                        (float(self.width()) - float(old.width())) / 2.0,
                        (float(self.height()) - float(old.height())) / 2.0,
                    )
            except Exception as exc:
                print(f"[klausmate] map resize failed: {exc}")
            try:
                super().resizeEvent(event)
            except Exception:
                pass

        def fit(self) -> None:
            """The Fit button / reset: re-center the whole graph."""
            try:
                self._apply_fit(float(self.width()), float(self.height()))
                self.update()
            except Exception as exc:
                print(f"[klausmate] map fit failed: {exc}")

        def select(self, safe) -> bool:
            """Select the node named ``safe``; True when one matched.

            An unknown name (or None) CLEARS the selection rather than
            leaving the previous node ringed: the seam's whole purpose
            is "the map shows what the viewer is showing", and a stale
            highlight over a PDF you closed is a lie, not a courtesy.
            """
            try:
                key = str(safe) if safe else None
                if key is not None and key not in self._pdf_xyz:
                    key = None
                self._selected = key
                if key is not None:
                    w = float(self.width())
                    h = float(self.height())
                    self._ensure_fit(w, h)
                    u, v, _d = camera_point(self._cam, *self._pdf_xyz[key])
                    self._vp = recenter_for(self._vp, (u, v), (w, h))
                self.update()
                return key is not None
            except Exception as exc:
                print(f"[klausmate] map select failed: {exc}")
                return False

        # ---- painting ----

        def _ensure_pens(self, c: dict) -> None:
            """One pen per depth band, built once per palette.

            Colour AND width carry the depth: the far bands are mixed
            most of the way into the card's own ground so they dissolve
            into it, the near ones go to full text ink, and the dot grows
            with the band's perspective factor. Both ends are theme
            tokens, so this ramp re-colours with the palette (and with
            every accent theme) without knowing any of them exist.

            The mix is OPAQUE, never alpha: measured on this machine,
            28,668 dots cost 13.8 ms a frame through a semi-transparent
            pen and 2.9 ms through an opaque one. Depth fog by alpha
            would have made the 3D map 5x dearer than the 2D one it
            replaces, for a picture the eye cannot tell apart.
            """
            night = theme.night_mode()
            if self._band_pens and self._pens_night == night:
                return
            pens = []
            shades = fog_shades([poly.count() for _z, poly in self._bands])
            for (zb, _poly), shade in zip(self._bands, shades):
                _u, _v, dep = camera_point(Camera(0.0), 0.0, 0.0, zb)
                pen = QPen(
                    QColor(blend_hex(c["grey_mid"], c["text"], shade)),
                    NOTE_DOT_R * 2.0 * _clamp(dep, DOT_DEPTH_MIN, DOT_DEPTH_MAX),
                )
                # SQUARE, and that is a measurement rather than a taste:
                # the identical draw with RoundCap costs 54.6 ms a frame
                # against 3.4 (28,668 dots, 256 bands, this machine) —
                # Qt strokes every round cap as a real path. Keeping the
                # dots small is what stops squares reading as blocks.
                pen.setCapStyle(Qt.PenCapStyle.SquareCap)
                pens.append(pen)
            self._band_pens = pens
            self._pens_night = night

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
            cam = self._cam

            # Notes: EVERY note, one drawPoints per DEPTH BAND, farthest
            # band first. Each band's projective QTransform does the
            # rotate + perspective + world->screen pass for all of its
            # points in C++ (band_matrix derives it), so the Python cost
            # per frame is the number of BANDS, not the number of notes.
            # The transform belongs on the POLYGON, never on the painter
            # — drawPoints with a cosmetic pen under a scaled painter
            # degenerates into long horizontal strokes at deep zoom, and
            # a painter cannot carry a projective transform to a
            # cosmetic pen at all.
            if self._bands:
                self._ensure_pens(c)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for i in band_order(cam, len(self._bands)):
                    zb, poly = self._bands[i]
                    painter.setPen(self._band_pens[i])
                    painter.drawPoints(
                        QTransform(*band_matrix(vp, cam, zb)).map(poly)
                    )

            # Edges: ONLY the hovered/selected PDF's (the whole point of
            # edges_for_selection — every edge at once is a hairball).
            # This one IS still a Python per-item loop, deliberately:
            # measured at ~3.15 us per drawn edge, it costs nothing until
            # a node is active and then scales with exactly what the
            # reader asked to see — ~5 ms for the biggest PDF in Pouya's
            # library (~1,570 matches once every note is positioned), and
            # 23 ms in a synthetic worst case where one PDF matches a
            # fifth of the whole collection. Still interactive there, so
            # it did not earn the note layer's C++ treatment.
            active = active_pdf(self._hover, self._selected)
            if active and active in self._pdf_xyz:
                edge_col = QColor(c["blue_accent"])
                edge_col.setAlphaF(EDGE_ALPHA)
                painter.setPen(QPen(edge_col, 1.0))
                ax, ay, _ad = project_point(vp, cam, *self._pdf_xyz[active])
                for e in edges_for_selection(self._edges, active):
                    try:
                        nxyz = self._note_xyz.get(int(e.get("nid")))
                    except (TypeError, ValueError):
                        continue
                    if nxyz is None:
                        continue
                    bx, by, _bd = project_point(vp, cam, *nxyz)
                    painter.drawLine(QPointF(ax, ay), QPointF(bx, by))

            # PDF nodes: accent circles sized by match_count. Exactly
            # ONE name is ever drawn — the hovered or selected node's
            # (K-138, Pouya's call, reversing K-133's always-on labels).
            label_font = painter.font()
            label_font.setPixelSize(11)
            painter.setFont(label_font)
            try:
                metrics = painter.fontMetrics()
            except Exception:
                metrics = None  # widths degrade to 0 -> plain right-hand side
            # Farthest node first, for the same reason the bands are
            # ordered: a near node has to occlude a far one, or the
            # depth the fog just established comes apart.
            drawn = []
            for p in self._pdfs:
                safe = str(p.get("safe"))
                sx, sy, dep = project_point(vp, cam, *self._pdf_xyz[safe])
                drawn.append((dep, safe, p, sx, sy))
            drawn.sort(key=lambda t: t[0])
            for dep, safe, p, sx, sy in drawn:
                # Perspective sizes the node too — a PDF sitting at the
                # back of the cloud reads as smaller, not just dimmer.
                r = node_radius(p.get("match_count")) * _clamp(
                    dep, DOT_DEPTH_MIN, DOT_DEPTH_MAX
                )
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
                if safe == active:
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
            cam = self._cam
            out = []
            for safe, xyz in self._pdf_xyz.items():
                sx, sy, _dep = project_point(vp, cam, *xyz)
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
                    hit = self._hit_at(float(pos.x()), float(pos.y()))
                    self._selected = hit
                    # Pressing a PDF FLIES the camera to it (K-148);
                    # pressing empty space just clears the selection.
                    # Note this is the click path only — ``select()``,
                    # the PDF viewer's seam, keeps its gentler contract
                    # (recentre only when off-view, never touch zoom):
                    # the map following the file you opened must not
                    # also rearrange your view of it.
                    if hit is not None:
                        self.fly_to(hit)
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

    return _MapCanvas


def map_canvas(parent=None, graph=None):
    """The map canvas as a plain widget — the ONE renderer, embeddable.

    ``parent`` is the host widget (None for a free-standing canvas).
    ``graph`` is a ``pdf_graph.build_graph_data``-shaped dict; passing
    None loads one with :func:`graph_data`, which BLOCKS for as long as
    that takes (see its docstring) — every caller on the GUI thread
    should build the graph off-thread and pass it in.

    Returns the canvas, or None if Qt is unreachable or construction
    failed. Callers must handle None: the map is an optional surface and
    must never take its host down with it.

    The canvas declares no minimum size of its own — how small the map
    may get is a decision of the surface hosting it (the window wants
    480x360, the Library's dock is a compact box), not of the renderer.
    It also arrives STILL: the idle sway is opt-in per host
    (``canvas.set_idle_rotation(True)``), because the Library's dock
    shows the same scene without movement.
    """
    try:
        cls = _canvas_class()
        if cls is None:
            return None
        return cls(graph_data() if graph is None else graph, parent)
    except Exception as exc:
        print(f"[klausmate] map canvas build failed: {exc}")
        return None


def select_pdf(safe) -> bool:
    """Point the open map at the PDF named ``safe``; True when it took.

    The seam Pouya asked for in K-137 — "when I am viewing a PDF on the
    PDF viewer, it chooses that item" — deliberately left UNWIRED here.
    Whoever owns the viewer calls this; the map never reaches back into
    the viewer, so the dependency runs one way and this module stays
    openable, testable and closable on its own.

    Contract:

    - No map window open, or an empty-graph window with no canvas: a
      silent no-op returning False. The viewer must be free to call
      this on every file it opens without first asking whether the map
      exists.
    - Known ``safe`` name: that node becomes the selection (ring +
      edges + its name, since K-138 draws exactly the active node's),
      the view recentres ONLY if the node was off-screen
      (``recenter_for``), the zoom is left alone, and the canvas
      repaints. Returns True.
    - Unknown name, empty, or None: clears the selection and returns
      False — a highlight left on the PDF you just closed would be a
      lie about what you are looking at.
    - Anything at all going wrong (a C++-deleted window, a stale
      singleton) is caught and reported as False. A map that cannot
      follow along must never break the viewer that called it.
    """
    win = _instance
    if win is None:
        return False
    try:
        canvas = getattr(win, "canvas", None)
        if canvas is None:
            return False
        return bool(canvas.select(safe))
    except Exception as exc:
        print(f"[klausmate] map select_pdf failed: {exc}")
        return False


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
            QHBoxLayout,
            QLabel,
            QPushButton,
            Qt,
            QVBoxLayout,
            QWidget,
        )

        from . import theme
    except Exception as exc:
        print(f"[klausmate] embedding map unavailable: {exc}")
        return None

    class _MapWindow(QWidget):
        """Standalone top-level map window (DriveWindow's shape: a plain
        QWidget window, module-singleton lifecycle).

        Opens EMPTY and fills in when the graph lands (K-144, absorbed
        into K-148). ``graph_data()`` is 16.9 s on Pouya's 28,668-note
        collection and this window used to call it inline, so the
        Library's Map button froze Anki solid for seventeen seconds with
        nothing on screen to distinguish that from a hang. The Library's
        dock already solved this in K-143 and this is deliberately the
        SAME shape, not a second one: show the window immediately with
        ``BUILDING_TEXT``, run the build on a ``QueryOp`` worker, and
        swap the real chrome in from ``_install`` on the main thread.
        A second Map click while the build is in flight fronts this
        window (``_instance`` is set before the worker starts), so it
        can never queue a second 17 s job.
        """

        def __init__(self, parent_widget=None) -> None:
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

            self._night = night
            self.canvas = None
            self._installed = False

            outer = QVBoxLayout(self)
            outer.setContentsMargins(12, 10, 12, 12)
            outer.setSpacing(8)
            self.status = QLabel(BUILDING_TEXT, self)
            try:
                self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.status.setStyleSheet(theme.muted_label_qss(night, 13))
            except Exception:
                pass
            outer.addWidget(self.status, 1)

            self.resize(900, 640)

        def _install(self, graph_dict: dict) -> None:
            """Put the finished graph on screen — MAIN THREAD ONLY.

            The seam the worker lands in, and the one the tests drive
            directly (the dock's ``_install_map`` precedent): a stubbed
            ``QueryOp`` never runs its op, so a test that wanted a
            canvas would otherwise sit at ``BUILDING_TEXT`` forever.
            """
            if self._installed:
                return
            self._installed = True
            night = self._night
            outer = self.layout()
            pdfs = (graph_dict or {}).get("pdfs") or []
            notes = (graph_dict or {}).get("notes") or []
            if not pdfs:
                self.status.setText(EMPTY_TEXT)
                return

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
            outer.insertLayout(0, bar)
            # The SHARED renderer (K-143) — the same factory the
            # Library's dock calls. The graph is already built, so
            # nothing here loads it a second time.
            self.canvas = map_canvas(self, graph_dict)
            if self.canvas is None:
                self.status.setText(CANVAS_FAIL_TEXT)
                fit_btn.setEnabled(False)
                return
            self.status.setVisible(False)
            # The canvas has no size of its own; this window is
            # what decides how small the map may get here.
            try:
                self.canvas.setMinimumSize(480, 360)
            except Exception:
                pass
            outer.addWidget(self.canvas, 1)
            try:
                fit_btn.clicked.connect(self.canvas.fit)
            except Exception as exc:
                print(f"[klausmate] map fit wire failed: {exc}")
            # THIS window is where the scene rotates. The Library's dock
            # hosts the same canvas and never asks — Pouya's call: the
            # map is a vibe when you go looking at it, and a distraction
            # moving in the corner of the Library while he works. The
            # canvas itself starts nothing until it is genuinely visible
            # (md3_switch's compositing SIGSEGV).
            try:
                self.canvas.set_idle_rotation(True)
            except Exception as exc:
                print(f"[klausmate] map idle rotation wire failed: {exc}")

        def _build_failed(self, exc: object) -> None:
            print(f"[klausmate] map graph build failed: {exc}")
            if not self._installed:
                try:
                    self.status.setText(BUILD_FAIL_TEXT)
                except Exception:
                    pass

        def closeEvent(self, evt) -> None:  # noqa: N802 — Qt naming
            global _instance
            if _instance is self:
                _instance = None
            try:
                super().closeEvent(evt)
            except Exception:
                pass

    try:
        win = _MapWindow(parent)
        _instance = win
        win.show()  # NEVER exec() — K-114
        win.raise_()
    except Exception as exc:
        print(f"[klausmate] embedding map open failed: {exc}")
        _instance = None
        return None
    _start_build(win)
    return win


def _start_build(win) -> None:
    """Run ``graph_data()`` off the UI thread and install it in ``win``.

    The dock's ``_ensure_map`` contract exactly (K-143): parented to
    ``mw``, never to the window, because a QueryOp whose parent dies
    takes its callback down with it — the window may well be closed
    during a seventeen-second build, and this is the only place that is
    handled. ``_instance`` guards the callback instead: a window that is
    no longer the singleton has been closed, and installing a canvas
    into it would resurrect a dead surface.

    No ``mw`` at all (headless, or a profile that never opened) means
    there is no event loop to protect and no worker to run on, so the
    build happens inline. That is the ONLY path that still blocks, and
    it blocks nothing a user is looking at.
    """
    try:
        from aqt import mw
        from aqt.operations import QueryOp
    except Exception as exc:
        print(f"[klausmate] map worker unavailable: {exc}")
        mw = None
        QueryOp = None

    def done(graph: dict) -> None:
        if _instance is not win:
            return
        try:
            win._install(graph)
        except Exception as exc:
            print(f"[klausmate] map install failed: {exc}")

    def fail(exc: Exception) -> None:
        if _instance is not win:
            return
        try:
            win._build_failed(exc)
        except Exception:
            pass

    if mw is None or QueryOp is None or getattr(mw, "col", None) is None:
        done(graph_data())
        return
    try:
        op = QueryOp(parent=mw, op=lambda _col: graph_data(), success=done)
        op.failure(fail)
        op.run_in_background()
    except Exception as exc:
        print(f"[klausmate] map build could not start: {exc}")
        fail(exc)
