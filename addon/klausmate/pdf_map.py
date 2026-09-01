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

**Every note, not a seventh of them.** ``projection`` fits its
components on a stride sample and projects every row, so the graph
arrives holding the whole collection — 28,668 notes on the collection
this was measured against. **K-158 reversed the DRAWING half of that**
(see below): the graph still carries every note, but the canvas draws a
sample of them. What survives unchanged is the mechanism: the note
layer is built ONCE as world-space ``QPolygonF``s and per frame handed
to ``QTransform.map``, so the transform runs in C++ and the Python cost
per frame is the number of BANDS, not the number of dots. **The
transform must stay on the polygon, never on the painter**: a point
draw under a scaled painter with a cosmetic pen degenerates into long
horizontal strokes once the zoom is deep (rendered and confirmed),
while mapping to screen space first is exact at every zoom AND
slightly faster.

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

Two traps K-148 found by measuring AT 28,668 NOTES — both real there,
and both gone at K-158's sampled few hundred, which is why every number
in this file is stated with the count it was measured at. Depth fog as
ALPHA cost 13.8 ms a frame against 2.9 opaque; round dots cost 54.6 ms
against 3.4, because Qt strokes every cap as a real path. At 400 dots
the same measurements are 0.85 ms round against 0.27 square, and a
cached gradient sprite blitted per dot is 0.42 — cheaper than round
dots. So the constraint that made K-148's map a field of flat square
chips is simply not a constraint any more. One trap found by RENDERING
and still live: fog keyed on z came out one flat mid-grey on the real
28,668-note index, because a PCA score is Gaussian-ish and the axis is
normalized to its outliers. ``fog_shades`` spends the ramp on the
cloud's own depth histogram instead; the synthetic uniform cube it was
first tuned on hid that completely.

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

**K-158: a vibe, not a census — and one PDF at a time.** Pouya, having
looked at all 28,668 notes: "It doesn't have to show all of the nodes...
just make it simple, have a simple graph, have it zoom in onto the node
of the PDFs, and show some way of connecting how it's connected to all
of its notes. Forget about cards. Make it look like I'm accessing the
matrix." Then, on the first pass of this card: "only one PDF shows at a
time, potentially, and then it just zooms in on that section of the
cloud that hosts that PDF."

So five things changed, and the first two REVERSE K-138 and K-148.

1. **The cloud is a SAMPLE.** ``split_cloud`` takes an even stride over
   the whole collection (``SAMPLE_NOTES``) plus a stride over each PDF's
   own matched notes (``SAMPLE_PER_PDF``), and the caption says the real
   total out loud — "4 PDFs · 28,670 notes · showing 643". 28k points at
   any real zoom is a solid mass that hides the structure it is supposed
   to convey, and nothing can glow inside it. ``SAMPLE_NOTES = 0``
   restores K-138's draw-everything path, because "how many is legible"
   is a tuning question whose answer will move.
2. **The dots emit light.** Cached radial-gradient sprites, blitted
   additively, on the DARK palette in both themes — a glow on white is a
   smudge, and K-148's light-mode render was exactly that. Depth drives
   brightness AND saturation, so the far face of the cloud sinks into
   the ground as a cold navy while the near face burns near-white.
3. **The connections are the point.** A PDF's beams are trails of the
   same sprites, leaving the node's rim and bowing outward. K-148 drew
   1px lines at 0.25 alpha: measured on the exact frame Pouya
   screenshotted, that whole layer moved 0.59% of the pixels — the gate
   WAS firing (its label, which shares the gate, was drawn in the same
   frame), the edges were simply invisible.
4. **One PDF is in focus and the rest are ghosts.** PDF nodes sit at
   their matched notes' CENTROID (K-058), so files whose match sets
   overlap land on top of one another — four lit rings in a knot. The
   window opens on one (``set_initial_focus``), arrow keys step through
   them, Escape goes back to the whole cloud, and the Library's dock
   keeps being told which one by the viewer.
5. **The name is drawn by the canvas**, on its own plate, in a pass
   AFTER every node. It used to be emitted inside the depth-sorted node
   loop, so a PDF that sorted nearer painted its disc over it; and a
   native QToolTip carrying the same name fought it for the same corner.
   ``clamp_label`` has the last word on placement, because a clipped
   name has been reported three times in this module.

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
# Share of the most extreme DRAWN points, per axis per end, that the fit
# ignores (K-158). projection normalizes each axis to its own extremes,
# so a handful of PCA outliers stretched the box until the cloud anyone
# actually looks at occupied a quarter of the card.
FIT_TRIM = 0.03
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
# Hover/click hit tolerance added on top of the largest node radius.
HIT_SLOP = 4.0
# Gap in px between a node's edge and its label box. Sized to clear the
# selected node's ring (drawn at r + 3 with a 2px pen, so outer edge
# r + 4) with daylight left over.
LABEL_GAP = 9.0
# Baseline nudge that sits an 11px label on the node's centre line.
LABEL_BASELINE_DY = 4.0
# Padding around the label's plate — the name is drawn over a live star
# field now, so it carries a dark rounded backing or it is unreadable.
LABEL_PAD_X = 7.0
LABEL_PAD_Y = 5.0
LABEL_PLATE_ALPHA = 0.82
LABEL_LINE_H = 14.0
# How close the plate may come to the canvas edge. label_anchor mirrors
# only when the mirrored side FITS; when neither does it keeps the
# right-hand placement and the text runs off. clamp_label has the last
# word instead — three reports of a clipped name in this module is
# enough offset-nudging.
LABEL_EDGE_PAD = 6.0
# The unfocused PDFs: a ring at this alpha and nothing else — no core,
# no name, a fifth of the halo. Pouya, K-158: "only one PDF shows at a
# time, potentially, and then it just zooms in on that section of the
# cloud that hosts that PDF." A GHOST rather than nothing at all,
# because the collection being bigger than what you are looking at is
# the mental conception the map exists to give; deleting the others
# would read as data loss. It also makes K-058's centroid pile-up stop
# mattering: four PDFs whose matched notes overlap have nearly the same
# mean position, so four lit rings land on top of one another.
GHOST_ALPHA = 0.22
GHOST_HALO_F = 0.7
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
# ...and the share of the most extreme matches, per axis per end, the
# flight's frame ignores. Semantic matches are not a tidy blob: on the
# real library one PDF's matches span nearly the whole cloud, so the
# full bounding box IS the whole graph and the flight — floored at the
# fit scale — went nowhere. Measured before this existed: clicking the
# 2,087-match PDF zoomed by exactly 1.00x.
FLY_TRIM = 0.10

# ── K-158: the sample, and the light ────────────────────────────────────
# How many notes of the ambient cloud are actually DRAWN. K-138 drew
# every one of 28,668 and K-148 made that cheap; Pouya looked at the
# result and asked for the opposite — "it doesn't have to show all the
# notes... it just has to give an idea, a mental conception of what the
# embedding is". At 28k the cloud is a solid mass that hides the very
# structure it is supposed to convey, and nothing can glow inside it.
# 0 means EVERY note: the K-138 path is still reachable, because "how
# many is legible" is a tuning question whose answer will move. Raising
# it costs frame time close to linearly (measured: 400 dots 0.4 ms,
# 1,600 dots 1.2 ms, 28,668 dots 17 ms for the same glow layer).
SAMPLE_NOTES = 420
# ...and how many of a PDF's OWN matched notes are drawn on top of that
# sample. These are the notes its edges land on, so they must be drawn
# or the connections would end in empty space. 0 means every match.
SAMPLE_PER_PDF = 90
# The sample is an even STRIDE over the graph's own order, never a
# random draw: a stride thins a cloud uniformly (so its shape survives),
# it is deterministic (the map looks the same every time you open it),
# and it is what projection.py already does to pick its fit rows.
#
# Glow. K-148 measured round dots at 16x square and alpha fog at 5x
# opaque and chose flat square chips — correct at 28,668 notes, and no
# longer a constraint at a few hundred. Re-measured here at the sampled
# count (1100x660, antialiased, this machine): square drawPoints
# 0.27 ms, round drawPoints 0.85 ms, per-point QRadialGradient 2.10 ms,
# and a CACHED gradient sprite blitted per dot 0.42 ms — cheaper than
# round dots and 5x cheaper than drawing the gradient per point. So the
# note layer is sprites: build the radial gradient ONCE per tier into a
# QPixmap, then drawPixmap it. The tiers quantize the fog ramp; a dot's
# tier is its depth band's fog shade.
GLOW_TIERS = 14
# How opaque a star's core and halo are. Not 1.0: the note layer
# composites ADDITIVELY, so opaque cores saturate to flat white wherever
# three dots overlap and the cloud's dense middle loses all hue. These
# were set by rendering, at both canvas sizes — the Library's 545x185
# dock packs the whole cloud into a thumbnail and blows out first.
GLOW_CORE_ALPHA = 0.46
GLOW_HALO_ALPHA = 0.34
# Core dot radius (px) at the far and near ends of the ramp, and how
# much bigger than the core the halo sprite is drawn. The sprite is
# square, GLOW_RATIO * 2 * radius on a side, so keep the ratio modest —
# it is what the blit actually costs.
NOTE_R_FAR = 1.0
NOTE_R_NEAR = 2.7
GLOW_RATIO = 3.1
# ...and how much of that a SMALL canvas gets. fit_margin's K-143
# lesson, one layer down: a dot sized for a 900x640 window is a blot in
# the Library's 545x185 dock, where the fit packs the whole cloud into
# about 110px and every star overlaps its neighbours into one white
# lump. Rendered at both sizes; the dock is what set the floor.
# Quantized to tenths so a drag of the dock's splitter cannot thrash
# the sprite cache.
DOT_SCALE_FULL = 420.0
DOT_SCALE_FLOOR = 0.55
# The tier ramp, as mixes of palette tokens (never invented colour).
# The halo runs from "barely above the ground" at the back to the full
# accent at the front, so depth drives BOTH brightness and saturation —
# a far dot is washed into the ground, a near one is hot. The core is
# that halo mixed toward the text token, so every dot has a pale centre
# falling off into a coloured halo, which is what emission looks like.
HALO_DEEP = 0.62
HALO_FAR = 0.16
HALO_NEAR = 1.0
CORE_FAR = 0.10
CORE_NEAR = 0.75
# When a PDF is active the rest of the cloud recedes: its tiers are
# mixed this far back toward the ground so the PDF's own notes stand
# out instead of drowning in everything else.
DIM_KEEP = 0.55
# The active PDF's own notes are drawn hotter and fatter than the
# ambient cloud — they are what the flight is for.
LINK_R_BOOST = 1.5
# Edges as LIGHT, not ink — and as a TRAIL OF PARTICLES rather than a
# stroke. K-148 drew a single 1px line at 0.25 alpha and, measured on
# the frame Pouya screenshotted, the whole edge layer moved 0.59% of the
# pixels: drawn, and invisible, over 28,670 grey chips.
#
# Glowing strokes were the obvious replacement and they blow the budget.
# Measured here, 90 beams at 1100x660: an antialiased two-pass stroke is
# 6.35 ms and rises to 10.55 ms once zoom makes the beams long, because
# Qt's cost is the stroke's device-space AREA. The SAME beams as blitted
# glow sprites are 0.84 ms and — this is the part that matters — the
# cost does not move with zoom, because the particle count per beam is
# capped. Turning antialiasing off would also have been fast (2.34 ms)
# and would have put staircased 1px lines in a view whose whole job is
# to look like light. Composition mode is irrelevant either way (Plus
# 18.08 ms vs SourceOver 18.74 on the same strokes) — it was never the
# blend that was expensive, it was the rasterizer.
BEAM_STEP = 13.0
BEAM_MAX = 20
# Where along the tier ramp a beam's particles start: they grow and
# brighten from the node outward, so the light reads as travelling.
BEAM_MIN_TIER = 0.22
# Beams leave the node's RIM plus this gap, and bow this share of their
# own length sideways. Both are about the hub: particles converging on
# one point pile into a white blot and hide the node they are about,
# and straight spokes read as a diagram where a curve reads as a
# connection.
EDGE_HUB_GAP = 3.0
EDGE_BOW = 0.085
# A PDF node is a core + halo + ring, never a filled disc. Fractions of
# the node radius: the lit core, the ring's stroke, and how far the halo
# reaches past the rim.
NODE_CORE_F = 0.42
NODE_RING_W = 1.6
NODE_HALO_F = 3.4
NODE_SELECT_GAP = 5.0
# The ground: a radial lift at the centre of the card falling to the
# flat ground token at the corners. One gradient fill a frame (measured
# at 0.18 ms for 1100x660) — cheaper than caching a full-size pixmap and
# re-making it on every resize.
VIGNETTE_LIFT = 0.16
VIGNETTE_SPREAD = 0.78
# A click that moves the mouse this far (px, from where the button went
# down) is a DRAG; anything less is a click. K-148 compared each
# individual move delta against 2.0, so two pixels of trackpad finger
# drift turned a click into a pan — the PDF was never selected, nothing
# flew, and no edges drew. Measured on the real graph: a press, a
# (2, 1) jitter and a release selects nothing.
CLICK_SLOP = 4.0

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
    "Circles are PDFs, dots are notes — hover or ←→ to focus one, "
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


def trimmed_bounds(
    points: Iterable[Sequence], trim: float = 0.0,
    fallback: Sequence[float] = DEFAULT_BOUNDS
) -> tuple:
    """``bounds_of``, ignoring the most extreme ``trim`` share of the
    points on each axis at each end.

    What the flight frames (K-158). Semantic matches are not a tidy
    blob: on the real library one PDF's matched notes span nearly the
    whole cloud, so the full bounding box of "this PDF and everything it
    reaches" is the whole graph — and the flight, floored at the fit
    scale, then went nowhere at all. Measured before this existed:
    clicking the 2,087-match PDF zoomed by exactly 1.00x.

    Trimming a fixed share per axis rather than dropping outlier POINTS:
    a note far out on x may be perfectly ordinary on y, and throwing the
    whole note away would shrink the frame twice. ``trim <= 0`` is the
    plain bounding box.
    """
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
    t = _clamp(_num(trim), 0.0, 0.45)
    out: list = []
    for axis in (xs, ys, zs):
        axis.sort()
        k = int(len(axis) * t)
        # Never trim a span away: fewer than two survivors is not a
        # box any more, it is a point, and a flight framed on a point
        # zooms to the scale clamp.
        if len(axis) - 2 * k < 2:
            k = 0
        out.append((axis[k], axis[len(axis) - 1 - k]))
    return (out[0][0], out[1][0], out[2][0],
            out[0][1], out[1][1], out[2][1])


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


def focus_order(pdfs: Iterable[dict]) -> list:
    """The PDFs' safe names in a stable focus order — most-matched
    first, ties broken by name.

    The order arrow keys step through, and the one ``focus_initial``
    picks its first from. Most-matched first because that is the file
    with the most to say about the collection, and a stable order
    because "next" has to mean the same thing every time.
    """
    rows = []
    for p in pdfs:
        if not isinstance(p, dict):
            continue
        safe = p.get("safe")
        if not safe:
            continue
        try:
            n = int(p.get("match_count") or 0)
        except (TypeError, ValueError):
            n = 0
        rows.append((-n, str(safe)))
    rows.sort()
    return [s for _n, s in rows]


def next_focus(order: Sequence, current: Optional[str], step: int = 1):
    """The next PDF to focus, cycling; ``None`` for an empty order.

    An unknown or absent ``current`` enters at the FRONT going forward
    and at the BACK going back, so the first arrow press from the
    whole-cloud view lands on a real PDF either way.
    """
    names = [str(s) for s in order]
    if not names:
        return None
    try:
        i = names.index(str(current))
    except ValueError:
        return names[0] if step >= 0 else names[-1]
    return names[(i + int(step)) % len(names)]


def links_for(linked: dict, active: Optional[str]) -> list:
    """The connections to DRAW: the active PDF's own sampled notes,
    empty when nothing is active.

    The edge-subset policy, and since K-158 it is also the cost
    ceiling. K-148 drew every edge of the active PDF — 2,087 of them for
    the biggest file in Pouya's library, measured here at 39.8 ms a
    frame once the lines became glowing two-pass strokes, ten times over
    the budget. Drawing to the SAMPLED notes instead is both the cheap
    answer and the honest one: an edge that ends on a dot nobody drew is
    a line into empty space.
    """
    if not active:
        return []
    return list(linked.get(str(active)) or [])


def sample_indices(total: object, cap: object) -> list:
    """Up to ``cap`` indices into a sequence of ``total`` items, spread
    by an even STRIDE — ``[i * total // cap for i in range(cap)]``.

    ``cap <= 0`` (or a cap at least as large as the sequence) returns
    every index, which is how ``SAMPLE_NOTES = 0`` keeps K-138's
    draw-everything path reachable behind a constant.

    Stride rather than a random draw for three reasons. It thins a cloud
    UNIFORMLY, so the shape survives the thinning — the whole point of
    sampling here is that the picture still says what the embedding
    looks like. It is deterministic, so the map is the same picture
    every time it opens rather than a different one each session. And it
    is what ``projection.py`` already does to choose its fit rows, so
    the two samples are drawn the same way.

    Indices are strictly increasing and never repeat: ``i * total //
    cap`` is monotonic and, with ``cap <= total``, gains at least one
    per step.
    """
    n = int(_num(total, 0.0))
    k = int(_num(cap, 0.0))
    if n <= 0:
        return []
    if k <= 0 or k >= n:
        return list(range(n))
    return [i * n // k for i in range(k)]


def pdf_note_ids(edges: Iterable[dict], safe: object) -> list:
    """The note ids one PDF's edges reach, in graph order, deduplicated.

    Separate from ``edges_for_selection`` because the sample wants the
    NOTES (each once, so a stride over them is a stride over distinct
    points), while the painter wants the edges."""
    key = str(safe) if safe is not None else None
    out: list = []
    seen: set = set()
    for e in edges:
        if not isinstance(e, dict) or str(e.get("pdf")) != key:
            continue
        try:
            nid = int(e["nid"])
        except (TypeError, ValueError, KeyError):
            continue
        if nid not in seen:
            seen.add(nid)
            out.append(nid)
    return out


def row_nid(row: object) -> Optional[int]:
    """A note row's nid as an int, or None — the ONE place a graph row's
    id is parsed, so the sample and the edge lookup agree on what
    counts as the same note."""
    if not isinstance(row, dict):
        return None
    try:
        return int(row["nid"])
    except (TypeError, ValueError, KeyError):
        return None


def split_cloud(
    graph: dict, cap: int = SAMPLE_NOTES, per_pdf: int = SAMPLE_PER_PDF
) -> tuple:
    """The drawn cloud: ``(ambient, linked, positions, total, shown)``.

    - ``ambient``: ``[(x, y, z), ...]`` — the stride sample of the whole
      collection. This is the shape of the embedding, thinned until you
      can see through it.
    - ``linked``: ``{safe: [(x, y, z), ...]}`` — a stride sample of each
      PDF's OWN matched notes, drawn hot when that PDF is active. These
      are separate from ``ambient`` (never both) because a PDF's edges
      have to land on dots that are actually on screen: an edge ending
      in empty space is worse than no edge.
    - ``positions``: ``{nid: (x, y, z)}`` for EVERY positioned note, not
      just the drawn ones — an edge's endpoint is a real position
      whether or not its dot was sampled, and ``_fly_target`` frames the
      PDF's true match set rather than the sample's bounding box.
    - ``total``: how many notes the graph really held, which is what the
      caption says out loud.
    - ``shown``: how many DISTINCT notes are drawn. A note two PDFs both
      matched sits in both link sets and is blitted twice (same place,
      one slightly brighter dot); it is one note, and the caption counts
      it once.

    One function so the canvas and the caption cannot disagree about
    what "showing 780" means; the test still has an independent route to
    the same number, by counting the points the canvas actually put in
    its polygons.
    """
    rows = [n for n in (graph.get("notes") or []) if row_xyz(n) is not None]
    positions: dict = {}
    for n in rows:
        nid = row_nid(n)
        if nid is not None:
            positions[nid] = row_xyz(n)
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    linked: dict = {}
    taken: set = set()
    for p in graph.get("pdfs") or []:
        if not isinstance(p, dict):
            continue
        nids = [n for n in pdf_note_ids(edges, p.get("safe")) if n in positions]
        picked = [nids[i] for i in sample_indices(len(nids), per_pdf)]
        linked[str(p.get("safe"))] = [positions[n] for n in picked]
        taken.update(picked)
    rest = [row_xyz(n) for n in rows if row_nid(n) not in taken]
    ambient = [rest[i] for i in sample_indices(len(rest), cap)]
    return (ambient, linked, positions, len(rows), len(ambient) + len(taken))


def caption_text(pdf_count: int, note_total: int, shown: int) -> str:
    """The window's caption — "4 PDFs · 28,670 notes · showing 780".

    The "showing" clause is the point: the map draws a SAMPLE now, and a
    view that quietly showed a fraction while naming the whole would be
    lying about the data. It is omitted only when nothing was left out.
    Nothing here says "cards" — K-158, Pouya: "forget about cards".
    """
    p = max(0, int(_num(pdf_count, 0.0)))
    n = max(0, int(_num(note_total, 0.0)))
    s = max(0, int(_num(shown, 0.0)))
    out = (f"{p} PDF{'s' if p != 1 else ''} · "
           f"{n} note{'s' if n != 1 else ''}")
    if 0 < s < n:
        out += f" · showing {s}"
    return out


def tier_index(shade: float, tiers: int = GLOW_TIERS) -> int:
    """Which glow tier a band's fog shade falls in.

    The sprite cache is per TIER, not per band: 256 bands would mean 256
    pixmaps for a ramp the eye reads as a dozen steps. Clamps rather
    than raises, because this is on the paint path.
    """
    t = int(_num(tiers, GLOW_TIERS))
    if t <= 1:
        return 0
    i = int(_clamp(_num(shade), 0.0, 1.0) * t)
    return t - 1 if i >= t else i


def tier_position(index: int, tiers: int = GLOW_TIERS) -> float:
    """Where a tier sits on the far->near ramp, in [0, 1] — its middle,
    so the ends are not forced to exactly 0 and 1 by an off-by-one."""
    t = int(_num(tiers, GLOW_TIERS))
    if t <= 1:
        return 1.0
    return _clamp((int(_num(index)) + 0.5) / t, 0.0, 1.0)


def tier_colours(c: dict, pos: float, dim: bool = False) -> tuple:
    """``(halo, core)`` hex for a tier at ramp position ``pos``.

    Both are mixes of palette TOKENS, so the whole star field re-colours
    with the accent theme and this file still names no colour of its
    own. The halo runs from a shade barely above the ground at the back
    to the full accent at the front — depth drives brightness AND
    saturation, because mixing toward a grey ground desaturates as it
    darkens. The core is that halo mixed toward the text token: a pale
    centre falling off into a coloured halo, which is what a light
    source looks like and what a flat chip never will.

    ``dim`` mixes both back toward the ground — the ambient cloud while
    a PDF is active, so its own notes are not lost in everything else.
    """
    t = _clamp(_num(pos), 0.0, 1.0)
    ground = c["bg"]
    # Navy at the back, accent at the front: the ramp travels through
    # HUE as well as brightness, so the far face of the cloud sinks into
    # the ground as a cold deep blue instead of a grey version of the
    # near face. Three accent-family tokens, no invented colour.
    deep = blend_hex(ground, c["blue_pressed"], HALO_DEEP)
    halo = blend_hex(deep, c["blue_bright"],
                     HALO_FAR + (HALO_NEAR - HALO_FAR) * t)
    core = blend_hex(halo, c["text"], CORE_FAR + (CORE_NEAR - CORE_FAR) * t)
    if dim:
        halo = blend_hex(ground, halo, DIM_KEEP)
        core = blend_hex(ground, core, DIM_KEEP)
    return (halo, core)


def dot_scale(widget_size: Sequence[float]) -> float:
    """How big this canvas's stars are, as a fraction of full size.

    ``fit_margin``'s rule applied to the dots themselves (K-158): the
    Library's dock is a 545x185 thumbnail of the SAME scene, and at that
    size the fit packs the whole cloud into roughly 110px — where a dot
    sized for the standalone window overlaps its neighbours into one
    white lump. Quantized to tenths so dragging the dock's splitter
    cannot thrash the sprite cache.
    """
    try:
        smaller = min(float(widget_size[0]), float(widget_size[1]))
    except (TypeError, ValueError, IndexError):
        return 1.0
    if smaller != smaller or smaller <= 0:  # NaN or no surface yet
        return 1.0
    return _clamp(round(smaller / DOT_SCALE_FULL, 1), DOT_SCALE_FLOOR, 1.0)


def tier_radius(pos: float, boost: float = 1.0) -> float:
    """The core dot radius (px) for a tier — the near face of the cloud
    is chunkier than the far face, which is the size half of depth."""
    t = _clamp(_num(pos), 0.0, 1.0)
    return (NOTE_R_FAR + (NOTE_R_NEAR - NOTE_R_FAR) * t) * max(
        0.1, _num(boost, 1.0)
    )


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


def node_lines(pdf: dict) -> list:
    """The focused PDF's plate: display name, folder when filed, matched
    NOTE count, retention only when actually known (headless graphs
    carry None). Never a card count — K-158, Pouya: "forget about
    cards".

    This used to be ``tooltip_text``, fed to ``QToolTip.showText``.
    K-158 replaced the native tooltip with a plate the canvas draws
    itself, because the two were fighting: a popup positioned at the
    global cursor and a label positioned beside the node stacked on top
    of each other in the same corner, twice, in two different type
    styles. One name, drawn once, by whoever owns the surface.
    """
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
    return lines


def clamp_label(x: float, text_width: float, view_width: float,
                pad: float = LABEL_EDGE_PAD) -> float:
    """``x`` pulled back inside the canvas, whatever ``label_anchor``
    chose.

    ``label_anchor`` mirrors a label to the left when the right-hand
    placement would overrun — but only when the left placement FITS.
    When neither side fits (a wide plate, a node near an edge, a node
    projected off-canvas entirely) it keeps the right-hand one and the
    text runs off the edge. That has now been reported three times in
    this module, so the last word belongs to a clamp rather than to
    another offset: the plate is placed by preference and then made to
    be on screen.
    """
    tw = max(0.0, _num(text_width))
    vw = _num(view_width)
    p = max(0.0, _num(pad, LABEL_EDGE_PAD))
    if vw <= 0.0:
        return _num(x)
    return _clamp(_num(x), p, max(p, vw - tw - p))


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
            QPixmap,
            QPointF,
            QPolygonF,
            QPropertyAnimation,
            QRadialGradient,
            QRectF,
            Qt,
            QTimer,
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
            # K-158: the cloud is a SAMPLE now. ``_note_xyz`` still holds
            # every positioned note (edges and the flight's framing work
            # off the real match set, not off the sample), while
            # ``_notes`` is only what gets drawn.
            (ambient, self._link_pts, self._note_xyz,
             self._note_total, self._shown) = split_cloud(graph_dict)
            self._notes: list = list(ambient)
            self._pdfs: list = []
            self._pdf_xyz: dict = {}
            self._pdf_by_safe: dict = {}
            for p in graph_dict.get("pdfs") or []:
                xyz = row_xyz(p)
                safe = p.get("safe") if isinstance(p, dict) else None
                if xyz is None or not safe:
                    continue
                self._pdfs.append(p)
                self._pdf_xyz[str(safe)] = xyz
                self._pdf_by_safe[str(safe)] = p
            # The note layer, built ONCE in WORLD space (K-138), as one
            # polygon PER DEPTH BAND (K-148). Every frame hands each band
            # to QTransform.map, which transforms its points in C++;
            # the Python per-dot loop this replaces is 11.6 ms a frame in
            # 3D against 2.9 for the whole banded draw. World space, not
            # screen: it is the camera and viewport that change per
            # frame, not the cloud. K-158 adds a SECOND set of bands per
            # PDF — its own matched notes, so they can be lit separately
            # from the ambient field without a per-point test in the
            # paint loop.
            self._bands = self._make_bands(self._notes)
            self._link_bands: dict = {
                safe: self._make_bands(pts)
                for safe, pts in self._link_pts.items()
            }
            self._sprites: dict = {}
            self._sprite_key = None
            # ONE fog ramp for both band sets, spent on the COMBINED
            # depth histogram (fog_shades' K-148 lesson: a PCA score is
            # Gaussian-ish, so a ramp keyed on z comes out one flat
            # grey). Indexed by band index, so a linked note and the
            # ambient note beside it read at the same depth.
            hist = [0] * DEPTH_BANDS
            for group in [self._bands] + list(self._link_bands.values()):
                for idx, _zb, poly in group:
                    hist[idx] += poly.count()
            self._fog = fog_shades(hist)
            # The fit frames what is DRAWN, trimmed of its wildest
            # outliers (K-158). graph_bounds measures all 28,670 raw
            # positions, and projection normalizes each axis to its own
            # extremes — so a handful of PCA outliers stretched the box
            # until the cloud everyone actually looks at sat in a
            # quarter of the card with empty space all round it.
            self._bounds = trimmed_bounds(
                self._notes
                + [pt for pts in self._link_pts.values() for pt in pts]
                + list(self._pdf_xyz.values()),
                FIT_TRIM,
            )
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
            self._drag_origin = None
            # Idle rotation is OPT-IN per host: the standalone window
            # asks for it, the Library's dock renders the same scene
            # STILL (Pouya's explicit call — nothing should be moving in
            # the corner of his eye while he works). Nothing starts here
            # either way; the timer is armed from showEvent.
            self._idle_want = False
            # Which PDF the map opens ON. Opt-in per host, like the
            # sway: the standalone window lands on one so the map is
            # never a nameless ball of dots, while the Library's dock is
            # told by ``select`` which file the viewer has open and must
            # not pick a different one behind the reader's back.
            self._focus_order = focus_order(self._pdfs)
            self._auto_focus = False
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
                # Arrow keys step the focus (see step_focus), so the
                # canvas has to be able to hold focus at all.
                self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            except Exception as exc:
                print(f"[klausmate] map canvas setup failed: {exc}")
            # NO setMinimumSize here (K-143). How small the map may get
            # belongs to whatever is hosting it: the standalone window
            # wants 480x360, the Library's dock is a compact box that
            # would otherwise inherit a 480px floor and shove the whole
            # left pane wider. Each host sets its own, right where it
            # adds the canvas.

        @staticmethod
        def _make_bands(points) -> list:
            """Quantize a set of world points into depth slabs —
            ``[(band index, band z, QPolygonF), ...]`` ascending, empty
            slabs omitted. The band INDEX is kept (K-158) because two
            band sets now share one fog ramp and have to look it up."""
            buckets: dict = {}
            for x, y, z in points:
                buckets.setdefault(band_index(z), []).append(QPointF(x, y))
            return [
                (i, band_z(i), QPolygonF(pts))
                for i, pts in sorted(buckets.items())
            ]

        def shown_notes(self) -> int:
            """How many distinct notes this canvas actually draws — what
            the window's caption reports, so "showing N" is a fact about
            the picture rather than a guess about it."""
            return int(self._shown)

        def note_total(self) -> int:
            """How many notes the graph held, sample or no sample."""
            return int(self._note_total)

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

        def set_initial_focus(self, want: bool) -> None:
            """Ask the map to open ON a PDF rather than on the bare
            cloud (Pouya, K-158: "only one PDF shows at a time... and it
            zooms in on that section of the cloud that hosts that PDF").

            Applied at the FIRST fit, not here and not from a timer: the
            landing needs the canvas's real size, and the first fit is
            exactly the moment that size is known. No animation either —
            it is where the map opens, not somewhere it flies to.
            """
            self._auto_focus = bool(want)

        def focus_initial(self) -> bool:
            """Land on the most-matched PDF, instantly. True if there
            was one to land on."""
            if not self._focus_order:
                return False
            safe = self._focus_order[0]
            target = self._fly_target(safe)
            if target is None:
                return False
            self._selected = safe
            self._vp = target
            return True

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
            """Where the camera should land to show ``safe`` and how it
            reaches its notes — the box holding that PDF's node and the
            bulk of its matches, framed at the current pose.

            The BULK, not all of them (K-158, ``trimmed_bounds``): a
            PDF's matches spray across the whole cloud, and framing
            their full extent left the flight zooming by 1.00x on the
            real library — arriving exactly where it started, which is
            why the view Pouya screenshotted had no structure in it.

            Never wider than the whole graph: clicking a PDF whose
            matches are scattered would otherwise zoom OUT past the fit,
            which is not what pressing on a thing means.
            """
            node = self._pdf_xyz.get(safe)
            if node is None:
                return None
            # The SAMPLED notes, which are exactly the ones the flight
            # will show connected — framing matches nobody draws would
            # be framing an invisible set.
            pts = links_for(self._link_pts, safe)
            # The node itself is never trimmed away — it is the thing
            # you clicked, and a frame that loses it is not a flight to
            # it. So it is unioned in AFTER the trim.
            hub = bounds_of([node])
            box = trimmed_bounds(pts, FLY_TRIM) if pts else hub
            box = (
                min(box[0], hub[0]), min(box[1], hub[1]),
                min(box[2], hub[2]), max(box[3], hub[3]),
                max(box[4], hub[4]), max(box[5], hub[5]),
            )
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
                # The opening focus rides the first fit (see
                # set_initial_focus): the only moment the canvas both
                # has its real size and has not yet been posed by
                # anyone. Guarded on _selected so a host that already
                # called select() keeps its own choice.
                if self._auto_focus and self._selected is None:
                    self.focus_initial()

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

        @staticmethod
        def _glow_sprite(halo: str, core: str, radius: float):
            """One star, pre-rendered: a pale core falling off into a
            coloured halo, on transparent ground.

            THE reason the map can glow at all. K-148 measured round
            dots at 16x square and alpha fog at 5x opaque and chose flat
            square chips — right at 28,668 notes, and simply not a
            constraint at the sampled few hundred. Re-measured at 400
            dots (1100x660, antialiased): a QRadialGradient drawn PER
            POINT is 2.10 ms a frame, while building it once into a
            QPixmap and blitting that per point is 0.42 ms — cheaper
            even than round drawPoints (0.85 ms), because a blit
            rasterizes no path at all. So the gradient is built here,
            once per tier per palette, and the paint path only ever
            blits.
            """
            px = max(4, int(round(radius * 2.0 * GLOW_RATIO)))
            pm = QPixmap(px, px)
            pm.fill(QColor(0, 0, 0, 0))
            p = QPainter(pm)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                mid = px / 2.0
                grad = QRadialGradient(mid, mid, mid)
                # Semi-transparent on purpose: under additive blending
                # a fully opaque core saturates to flat white wherever
                # three dots overlap, and the cloud's dense middle —
                # the most interesting part of it — loses every trace of
                # hue. Rendered and confirmed at both canvas sizes; the
                # dock, which packs the whole cloud into 545x185, blew
                # out to a featureless white blob.
                hot = QColor(core)
                hot.setAlphaF(GLOW_CORE_ALPHA)
                edge = QColor(halo)
                edge.setAlphaF(GLOW_HALO_ALPHA)
                fade = QColor(halo)
                fade.setAlpha(0)
                soft = QColor(halo)
                soft.setAlphaF(GLOW_HALO_ALPHA * 0.45)
                # Core out to the dot's own radius, then the halo
                # falling to nothing at the sprite's rim.
                inner = _clamp(1.0 / (2.0 * GLOW_RATIO), 0.02, 0.45)
                grad.setColorAt(0.0, hot)
                grad.setColorAt(inner, hot)
                grad.setColorAt(min(0.99, inner * 1.9), edge)
                grad.setColorAt(min(0.995, inner * 3.4), soft)
                grad.setColorAt(1.0, fade)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(grad)
                p.drawEllipse(QRectF(0.0, 0.0, float(px), float(px)))
            finally:
                p.end()  # K-115: never leave a painter live
            return pm

        def _ensure_sprites(self, c: dict, scale: float = 1.0) -> None:
            """Build the star sprites — one per (tier, dimmed?) plus one
            per tier for a PDF's own notes — once per palette.

            Keyed on the palette's actual tokens rather than on
            ``night_mode()``: the map draws in the DARK palette whatever
            the app's theme is (see ``_paint``), so a night flip changes
            nothing here, while switching ACCENT theme changes every
            colour in the ramp and must rebuild.
            """
            key = (c["bg"], c["blue_bright"], c["text"], scale)
            if self._sprites and self._sprite_key == key:
                return
            out: dict = {}
            for i in range(GLOW_TIERS):
                pos = tier_position(i)
                for dim in (False, True):
                    halo, core = tier_colours(c, pos, dim)
                    out[(i, dim, False)] = self._glow_sprite(
                        halo, core, tier_radius(pos, scale)
                    )
                halo, core = tier_colours(c, pos)
                out[(i, False, True)] = self._glow_sprite(
                    halo, core, tier_radius(pos, LINK_R_BOOST * scale)
                )
            self._sprites = out
            self._sprite_key = key

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
            # THE MAP IS A LIGHTBOX: it draws in the DARK palette in both
            # themes (K-158). Emission needs a dark ground — a glow on
            # white is a smudge, and the light-mode render of K-148 was
            # exactly that, a grey stain on paper. Still every colour a
            # theme token, so accent themes recolour the whole star field
            # for free; only the card's own border follows the app's
            # palette, so the panel edge still belongs to the window it
            # sits in.
            c = theme.palette(True)
            host = theme.palette(theme.night_mode())
            w = float(self.width())
            h = float(self.height())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            card = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
            self._paint_ground(painter, c, host, card, w, h)

            self._ensure_fit(w, h)
            vp = self._vp
            cam = self._cam
            active = active_pdf(self._hover, self._selected)

            self._ensure_sprites(c, dot_scale((w, h)))
            # Additive light for everything that emits: overlapping
            # halos STACK into a brighter core instead of flatly
            # occluding each other, which is what makes a cloud of
            # points read as a nebula rather than as confetti. Measured
            # free (0.42 ms either way at 400 dots).
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Plus
            )
            # The ambient field first, dimmed while a PDF is active so
            # its own notes are not lost in everything else (K-158's
            # sixth critique: "the blob has no structure").
            self._blit_bands(painter, vp, cam, self._bands,
                             dim=bool(active), link=False, w=w, h=h)
            for safe, bands in self._link_bands.items():
                self._blit_bands(painter, vp, cam, bands,
                                 dim=bool(active) and safe != active,
                                 link=safe == active, w=w, h=h)
            self._paint_edges(painter, vp, cam, active, w, h)
            drawn = self._paint_nodes(painter, c, vp, cam, active, w, h)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            # The name LAST, over every node (K-158). It used to be
            # emitted inside the depth-sorted node loop, right after its
            # own circle — so any PDF that sorted nearer painted its
            # disc straight over the label. On the real graph the four
            # centroids sit within ~50px of each other and that is
            # exactly what happened: label_anchor had cleared its own
            # node's rim by 9px, and a neighbour swallowed the first
            # third of the name anyway.
            self._paint_label(painter, c, drawn, active, w, h)

        def _paint_ground(self, painter, c, host, card, w, h) -> None:
            """The card and the space inside it — a radial lift at the
            centre falling to the flat ground token at the corners, so
            the field has somewhere to recede INTO. One gradient fill a
            frame; content is clipped to the card so panned nodes never
            spill past the rounded corners."""
            painter.setPen(QPen(QColor(host["grey_light"]), 1.0))
            lift = QRadialGradient(
                w / 2.0, h / 2.0, max(w, h) * VIGNETTE_SPREAD
            )
            lift.setColorAt(
                0.0, QColor(blend_hex(c["bg"], c["blue_bright"], VIGNETTE_LIFT))
            )
            lift.setColorAt(1.0, QColor(c["bg"]))
            painter.setBrush(lift)
            painter.drawRoundedRect(card, 12.0, 12.0)
            clip = QPainterPath()
            clip.addRoundedRect(card, 12.0, 12.0)
            painter.setClipPath(clip)

        def _blit_bands(self, painter, vp, cam, bands, dim, link, w, h) -> None:
            """One band set, farthest slab first, as pre-rendered stars.

            Each band's projective QTransform does the rotate +
            perspective + world->screen pass for all of its points in
            C++ (band_matrix derives it), so the Python cost per frame is
            the number of BANDS plus one blit per visible dot — never a
            per-point projection. The transform belongs on the POLYGON,
            never on the painter: K-138 rendered and confirmed that a
            painter transform degenerates a point draw at deep zoom, and
            a painter cannot carry a perspective divide at all.
            """
            for i in band_order(cam, len(bands)):
                idx, zb, poly = bands[i]
                sprite = self._sprites.get(
                    (tier_index(self._fog[idx]), dim and not link, link)
                )
                if sprite is None:
                    continue
                half = sprite.width() / 2.0
                mapped = QTransform(*band_matrix(vp, cam, zb)).map(poly)
                for k in range(mapped.count()):
                    pt = mapped.at(k)
                    x = pt.x()
                    y = pt.y()
                    if x < -half or x > w + half or y < -half or y > h + half:
                        continue  # off-card dots cost nothing but a compare
                    painter.drawPixmap(int(x - half), int(y - half), sprite)

        def _paint_edges(self, painter, vp, cam, active, w, h) -> None:
            """The connections — the POINT of the view since K-158, and
            drawn as light rather than as ink.

            Only the hovered/selected PDF's, through ``links_for``
            (every edge at once is a hairball, and 2,087 of them cost
            39.8 ms a frame). Each beam is a TRAIL OF GLOW SPRITES, not
            a stroke: measured at 90 beams, an antialiased two-pass
            stroke is 6.35 ms and grows to 10.55 ms as zoom lengthens
            the beams, while the same beams as blitted particles are
            0.84 ms and do not move with zoom at all, because the
            particle count per beam is capped. The particles also read
            better — light travelling along a path rather than a wire
            drawn between two points.

            Each beam LEAVES THE RIM, not the centre, and bows on its
            way out: particles converging on one point pile into a white
            blot and swallow the node they are supposed to be about, and
            straight spokes read as a diagram where a curve reads as a
            connection. Particles grow and brighten outward along the
            tier ramp, so the light has a direction.

            K-148's edges were 1px at 0.25 alpha, and on the exact frame
            Pouya screenshotted that whole layer moved 0.59% of the
            pixels. The gate WAS firing — the label, which shares it,
            was drawn in the same frame. The edges were simply invisible.
            """
            if not active or active not in self._pdf_xyz:
                return
            beam = links_for(self._link_pts, active)
            if not beam:
                return
            p = self._pdf_by_safe.get(active) or {}
            ax, ay, ad = project_point(vp, cam, *self._pdf_xyz[active])
            gap = node_radius(p.get("match_count")) * _clamp(
                ad, DOT_DEPTH_MIN, DOT_DEPTH_MAX
            ) + EDGE_HUB_GAP
            # The particle ramp, resolved ONCE a frame: an ordinal in
            # 0..BEAM_MAX-1 straight to its sprite, so the inner loop
            # does one index and one blit.
            ramp = []
            for i in range(BEAM_MAX):
                pos = BEAM_MIN_TIER + (1.0 - BEAM_MIN_TIER) * (
                    (i + 1.0) / BEAM_MAX
                )
                spr = self._sprites.get((tier_index(pos), False, True))
                if spr is None:
                    return
                ramp.append((spr, spr.width() / 2.0))
            for nxyz in beam:
                bx, by, _bd = project_point(vp, cam, *nxyz)
                dx = bx - ax
                dy = by - ay
                span = math.hypot(dx, dy)
                if span <= gap:
                    continue  # a note inside the node's own rim
                ux = dx / span
                uy = dy / span
                sx = ax + ux * gap
                sy = ay + uy * gap
                # Quadratic control point: perpendicular to the beam,
                # proportional to its length, so long reaches curve and
                # short ones stay nearly straight.
                bow = (span - gap) * EDGE_BOW
                cx = (sx + bx) / 2.0 - uy * bow
                cy = (sy + by) / 2.0 + ux * bow
                k = int((span - gap) / BEAM_STEP)
                k = 2 if k < 2 else BEAM_MAX if k > BEAM_MAX else k
                step = BEAM_MAX / float(k)
                for i in range(k):
                    t = (i + 1.0) / (k + 1.0)
                    m = 1.0 - t
                    px = m * m * sx + 2.0 * m * t * cx + t * t * bx
                    py = m * m * sy + 2.0 * m * t * cy + t * t * by
                    spr, half = ramp[int(i * step)]
                    px -= half
                    py -= half
                    if px < -half or px > w or py < -half or py > h:
                        continue
                    painter.drawPixmap(int(px), int(py), spr)

        def _paint_nodes(self, painter, c, vp, cam, active, w, h) -> list:
            """PDF nodes as light sources: halo, ring, lit core — never
            the flat filled disc K-148 drew. Farthest first, for the
            same reason the bands are ordered: a near node has to occlude
            a far one or the depth the fog established comes apart.

            ONE of them is lit. The rest are GHOSTS — a faint ring and
            nothing else (K-158, Pouya: "only one PDF shows at a time,
            potentially"). That is not only taste: PDF nodes sit at the
            CENTROID of their matched notes (K-058), so files whose
            matches overlap have nearly the same position, and four lit
            rings land in a heap. Focusing one makes the pile-up stop
            mattering instead of asking the layout to solve it.

            Returns the drawn nodes (near-last) so the plate pass can
            place exactly one name AFTER every circle is down.
            """
            drawn = []
            for p in self._pdfs:
                safe = str(p.get("safe"))
                sx, sy, dep = project_point(vp, cam, *self._pdf_xyz[safe])
                drawn.append((dep, safe, p, sx, sy))
            drawn.sort(key=lambda t: t[0])
            out = []
            for dep, safe, p, sx, sy in drawn:
                # Perspective sizes the node too — a PDF at the back of
                # the cloud reads as smaller, not just dimmer.
                r = node_radius(p.get("match_count")) * _clamp(
                    dep, DOT_DEPTH_MIN, DOT_DEPTH_MAX
                )
                out.append((safe, p, sx, sy, r))
                if (
                    sx < -NODE_HALO_F * r
                    or sx > w + NODE_HALO_F * r
                    or sy < -NODE_HALO_F * r
                    or sy > h + NODE_HALO_F * r
                ):
                    continue
                pt = QPointF(sx, sy)
                # EVERY node but the focused one is a ghost — including
                # all of them when nothing is focused, which is what
                # keeps the whole-cloud view from being four overlapping
                # lit rings arguing about which is which.
                if safe != active:
                    gr = r * GHOST_HALO_F
                    ring = QColor(c["blue_bright"])
                    ring.setAlphaF(GHOST_ALPHA)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(ring, 1.0))
                    painter.drawEllipse(pt, gr, gr)
                    dot = QColor(c["blue_bright"])
                    dot.setAlphaF(min(1.0, GHOST_ALPHA * 1.8))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(dot)
                    painter.drawEllipse(pt, gr * NODE_CORE_F, gr * NODE_CORE_F)
                    continue
                halo_r = r * NODE_HALO_F
                halo = QRadialGradient(sx, sy, halo_r)
                edge = QColor(c["blue_bright"])
                edge.setAlphaF(0.55)
                fade = QColor(c["blue_bright"])
                fade.setAlpha(0)
                halo.setColorAt(0.0, edge)
                halo.setColorAt(1.0 / NODE_HALO_F, edge)
                halo.setColorAt(1.0, fade)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(pt, halo_r, halo_r)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(c["blue_bright"]), NODE_RING_W))
                painter.drawEllipse(pt, r, r)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(
                    QColor(blend_hex(c["blue_bright"], c["text"], CORE_NEAR))
                )
                painter.drawEllipse(pt, r * NODE_CORE_F, r * NODE_CORE_F)
                if safe == self._selected:
                    ring = QColor(c["blue_bright"])
                    ring.setAlphaF(0.7)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(ring, 1.0))
                    painter.drawEllipse(pt, r + NODE_SELECT_GAP,
                                        r + NODE_SELECT_GAP)
            return out

        def _paint_label(self, painter, c, drawn, active, w, h) -> None:
            """Exactly ONE plate, the focused node's (K-138), drawn by
            the canvas itself.

            It carries what the hover tooltip used to: name, folder,
            matched notes, retention when known. The native QToolTip is
            gone — a popup positioned at the global cursor and a label
            positioned beside the node stacked in the same corner, two
            text boxes in two type styles saying the same name.

            Placed by ``label_anchor`` and then CLAMPED into the canvas
            by ``clamp_label``: the anchor mirrors only when the mirrored
            side fits, and a name clipped at the right edge has now been
            reported three times here.
            """
            if not active:
                return
            for safe, p, sx, sy, r in drawn:
                if safe != active:
                    continue
                lines = node_lines(p)
                if not lines:
                    return
                font = painter.font()
                font.setPixelSize(11)
                painter.setFont(font)
                try:
                    fm = painter.fontMetrics()
                    tw = max(float(fm.horizontalAdvance(t)) for t in lines)
                except Exception:
                    tw = 0.0  # widths degrade to the plain right-hand side
                lx, ly = label_anchor(sx, sy, r, tw, w)
                bh = LABEL_LINE_H * (len(lines) - 1)
                lx = clamp_label(lx, tw, w)
                ly = _clamp(ly, LABEL_LINE_H + LABEL_EDGE_PAD,
                            max(LABEL_LINE_H, h - bh - LABEL_EDGE_PAD))
                plate = QColor(c["bg"])
                plate.setAlphaF(LABEL_PLATE_ALPHA)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(plate)
                painter.drawRoundedRect(
                    QRectF(lx - LABEL_PAD_X, ly - 11.0 - LABEL_PAD_Y,
                           tw + 2.0 * LABEL_PAD_X,
                           bh + 14.0 + 2.0 * LABEL_PAD_Y),
                    5.0, 5.0,
                )
                painter.setPen(QColor(c["text"]))
                painter.drawText(QPointF(lx, ly), lines[0])
                painter.setPen(QColor(c["text_muted"]))
                for i, line in enumerate(lines[1:], start=1):
                    painter.drawText(QPointF(lx, ly + LABEL_LINE_H * i), line)
                return

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
            """Hovering a node FOCUSES it for the frame — the plate the
            canvas draws is the whole affordance now. No QToolTip: a
            native popup at the global cursor and an on-canvas plate
            beside the node were two boxes fighting for one corner.
            """
            hit = self._hit_at(px, py)
            if hit == self._hover:
                return
            self._hover = hit
            self.update()

        def mousePressEvent(self, event) -> None:  # noqa: N802
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    pos = event.position()
                    self._dragging = True
                    self._drag_moved = False
                    self._drag_last = (float(pos.x()), float(pos.y()))
                    self._drag_origin = self._drag_last
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
                        # Measured from where the button went DOWN, not
                        # per move event (K-158). K-148 compared each
                        # individual delta against 2.0, so two pixels of
                        # trackpad finger drift promoted a click to a
                        # drag: the PDF was never selected, nothing flew,
                        # and the connections — the whole point of the
                        # view — never drew.
                        ox, oy = self._drag_origin or self._drag_last
                        if math.hypot(px - ox, py - oy) >= CLICK_SLOP:
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
                self._drag_origin = None
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
            except Exception:
                pass
            try:
                super().leaveEvent(event)
            except Exception:
                pass

        # ---- keyboard: stepping the focus ----

        def step_focus(self, direction: int) -> bool:
            """Focus the next (or previous) PDF and fly there.

            The standalone window's picker, and deliberately NOT a new
            signal: the Library's dock is already told which PDF to
            focus by ``select``, driven by whichever file the viewer has
            open. A window with no viewer needs its own answer, and
            arrow keys are the one that also solves the clicking
            problem — PDF nodes sit at their matches' centroid (K-058),
            so files with overlapping match sets stack into one knot of
            rings that cannot be picked apart with a mouse at all.
            """
            try:
                nxt = next_focus(self._focus_order, self._selected, direction)
                if nxt is None:
                    return False
                self._selected = nxt
                self._hover = None
                self.fly_to(nxt)
                return True
            except Exception as exc:
                print(f"[klausmate] map focus step failed: {exc}")
                return False

        def clear_focus(self) -> None:
            """Back to the whole cloud: no PDF lit, no plate, the graph
            framed as it opens. Escape's binding."""
            try:
                self._selected = None
                self._hover = None
                self._fly_anim.stop()
                self._fly_from = self._fly_to = None
                self.fit()
            except Exception as exc:
                print(f"[klausmate] map focus clear failed: {exc}")

        def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt override
            try:
                key = event.key()
                if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
                    if self.step_focus(1):
                        return
                elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
                    if self.step_focus(-1):
                        return
                elif key == Qt.Key.Key_Escape:
                    self.clear_focus()
                    return
            except Exception as exc:
                print(f"[klausmate] map key failed: {exc}")
            try:
                super().keyPressEvent(event)
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

            # The SHARED renderer (K-143) — the same factory the
            # Library's dock calls. The graph is already built, so
            # nothing here loads it a second time. Built BEFORE the bar
            # since K-158, because the caption's "showing N" is a fact
            # about the picture and the canvas is what knows it.
            self.canvas = map_canvas(self, graph_dict)
            shown = len(notes)
            try:
                if self.canvas is not None:
                    shown = self.canvas.shown_notes()
            except Exception:
                pass

            bar = QHBoxLayout()
            bar.setSpacing(8)
            caption = QLabel(caption_text(len(pdfs), len(notes), shown), self)
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
            # ...and it opens ON a PDF (K-158). The Library's dock does
            # not: the file its viewer has open is the focus there, and
            # picking a different one behind the reader would be the map
            # contradicting the thing it is meant to follow.
            try:
                self.canvas.set_initial_focus(True)
            except Exception as exc:
                print(f"[klausmate] map initial focus wire failed: {exc}")

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
