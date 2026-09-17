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

Motion. The standalone window sways slowly in 3D (K-200, ``sway_angle``
— a FULL revolution from K-174 to K-200, see below; K-148 shipped a
0.42 rad sway before that, on two reasons that were checked and found
not to hold for this cloud, which is exactly why K-200 could bring a
smaller sway back with confidence). The Library's dock renders the SAME
scene STILL — Pouya's explicit call, so nothing moves in the corner of
his eye while he works — which is why idle motion is opt-in per host
and the window is the only caller, and why the FIT is per host too: a
swaying canvas frames the swept box (``sweep_bounds``) so nothing walks
out of the card at the sway's extreme, while the still dock keeps the
tighter single-pose crop. Clicking a PDF flies the camera to its own
cluster (``fly_to``, a ``QPropertyAnimation`` on OutCubic — md3_switch's
shape); ``select_pdf``, the PDF viewer's seam, keeps its gentler K-138
contract and never rearranges your view of a file you just opened.
Anki's Reduce Motion preference stops the sway and lands the flight in
one frame; the scene stays 3D, perspective and fog either way. And the
idle timer is armed from ``showEvent`` through a child timer, never
from the constructor: md3_switch documents the SIGSEGV that repainting
a widget mid-composite causes.

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
   additively, on the DARK palette in both themes. **K-174 deleted the
   sprites and kept the dark palette** — see below.
3. **The connections are the point.** A PDF's beams were trails of the
   same sprites, leaving the node's rim and bowing outward; K-174
   replaced them with crisp lines and kept the diagnosis. K-148 drew
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
5. **The name is drawn by the canvas**, in a pass AFTER every node. It
   used to be emitted inside the depth-sorted node loop, so a PDF that
   sorted nearer painted its disc over it; and a native QToolTip
   carrying the same name fought it for the same corner. ``clamp_label``
   has the last word on placement, because a clipped name has been
   reported three times in this module. **Retired at K-187**: the
   rounded, alpha-blended plate it used to sit on is gone — Pouya:
   "Can you remove the little box around it." The name now draws bare,
   ink ``c["text"]`` for the SELECTED PDF and ``c["text_muted"]`` for a
   hover-only preview, and ``node_lines`` carries only the display
   name — the folder/matched-count/retention lines the plate used to
   show live in the Library tree instead.

**K-174: a constellation, hard-edged, turning.** Pouya, with
aalampour.com open: "See how there's a constellation type of thing...
That's what I want for the graph. I don't want these glowy things. I
also want it to be 3D. I want each node on the graph to be just
randomly interconnected... I like the shininess of the PDFs. I like
that. For all the node connections with everything else, I don't like
the blurry stuff. Just have it rotate slowly in 3D."

The reference was MEASURED off its own canvas rather than described,
and one number decides the whole look: at the star threshold the
longest run of lit pixels in a row is FOUR DEVICE px on a 2x surface —
one to two CSS px — with no skirt of mid-brightness pixels around it. A
glow sprite cannot produce that, because its falloff IS a long run of
mid-brightness pixels. Star blobs there are 2 device px in area at the
median and 23 at the very largest, and lit pixels are 0.006% of the
canvas at that threshold. Two further findings corrected the brief the
card was written from: the stars are NOT pure white on the glass (zero
pixels at the star threshold are 255/255/255; they read 214/222/248 and
215/215/213, so the palette's own text token is the right family and
this file still invents no colour), and depth there is carried by ALPHA
only because a canvas floating over a CSS nebula has no ground of its
own to mix into.

So, in this file:

- The glow-sprite cache, its tiers and its alphas are GONE. A star is a
  square-capped, non-antialiased, OPAQUE pen of one to three pixels
  through ``drawPoints`` — one C++ call per depth band, and the last
  per-point Python on the cloud's paint path went with the sprites.
  Depth is ``star_colour`` (brightness) and ``star_size`` (1..3 px) and
  nothing else. Re-measured rather than inherited, because K-158 chose
  sprites over dots for a GLOW: at 520 stars over 200 bands, 900x640,
  the sprite blit is 0.341 ms and the hard drawPoints is 0.28-0.31 ms
  at every pen width in the range.
- The particle beams are GONE. Both connection layers —
  ``_paint_constellation`` and ``_paint_edges`` — are crisp 1px
  non-antialiased lines in batched ``drawLines``. K-158's 6.35 ms (and
  39.8 ms for one PDF's full 2,087 edges) was the AA rasterizer, whose
  price is the stroke's device-space AREA: never the composition mode
  (Plus 18.08 vs SourceOver 18.74 on the same strokes) and never the
  call count (per-edge drawLine and batched drawLines measure 0.154 vs
  0.153 ms at 260 segments). Hard: 0.092 ms for 90 spokes, 2.51 ms for
  all 2,087.
- ``constellation_links`` adds the random interconnections, seeded from
  the drawn cloud (``link_seed``, hand-folded because Python randomizes
  ``hash()`` per process) so a collection always draws the same figure.
  Nearest-neighbour, after rendering the alternative: uniformly random
  chords are a cross-hatch that buries the cloud and the PDF nodes.
- The sway became a full REVOLUTION (``ROTATE_PERIOD_MS``), and the fit
  that has to survive it became ``sweep_bounds``. **Retired at K-200**:
  a full turn at 72s/5 degrees a second turned out to be too gradual to
  read as motion in any one glance — the opposite of "very apparent" —
  so the revolution is a SWAY again, smaller than even K-148's own, with
  a nearer camera standing in for the parallax a wider swing used to
  supply. ``sweep_bounds`` keeps its name and its job; it just frames a
  narrower arc now.
- **The PDF nodes glowed, on purpose, until K-186.** "I like the
  shininess of the PDFs. I like that." A handful of nodes a frame
  could afford a real radial gradient; 28,670 notes could not, and a
  field where everything shines has nothing special in it.
  **Retired at K-186**: Pouya went on to ask for the halo gone too
  ("remove the general glow... I don't like the general glow that
  comes with it") — the shininess he meant now lives in the ring and
  lit core alone, with nothing painted between a node's own radius and
  the old halo's 3.4x reach.
- **The map stays a night sky in BOTH themes.** Inverting to dark
  points on a light ground was the live alternative and it throws away
  exactly the thing he singled out — a light source on white is a
  smudge. Only the card's own border follows the app's palette.
  **Retired at K-185**: the card, its border and this special case all
  go together — the map paints flat on the HOST palette's chrome
  token now, so each theme gets its own night-sky-flavoured ramp
  instead of the canvas forcing the dark one underneath a light panel.

**K-188: dim by default, lit under the pointer.** Pouya: "I want it to
be dim, but then, as I put the mouse over it, it lights up to normal
values... I want everything to be dim otherwise." The canvas now rests
at ``DIM_LIT`` and ramps every layer — stars, the constellation, ghost
rings — to full brightness while the cursor is over it (``enterEvent``/
``leaveEvent`` driving the animated ``lit`` property, eased like
``fly``). The chosen PDF's ring, core and lit name are exempt, always
full ("just for that one, to light up"): the same chosen/preview split
K-187 already drew for the name. ``star_colour`` gained the ``lit``
parameter as ONE mechanism for this — the same ground-ward blend
``dim`` already does, gated by a different question.

Measured on this machine, 28,670 notes, offscreen, at 900x640:
1.83 ms at rest / 3.26 focused on the 2,087-match PDF / 4.04 focused
with the camera turned BEFORE this card; 1.32 / 1.82 / 1.79 after. The
frame is now dominated by ``DEPTH_BANDS`` rather than by the point
count — at the sampled few hundred, ~250 non-empty bands hold about
three points each, so the per-band matrix is most of the 1.2 ms the
star layer costs. That matters only if ``SAMPLE_NOTES`` moves.

**K-197: every star is connected.** Pouya, back at the map: "Can you
have all the nodes be interconnected in a satisfying way... I want each
node on the graph to be just randomly interconnected." kNN alone only
ever joins a star to a NEARBY partner, so a collection whose topics
cluster far apart in the embedding drew several disconnected
constellations rather than one sky — exactly what "satisfying
interconnection" was not. ``spanning_tree`` runs Prim's algorithm once
over the same sampled cloud that feeds ``constellation_links`` — pure,
deterministic, no RNG anywhere in it, O(n^2) on the ~520-point sample
and ~25 ms there, cleanly quadratic (K-199, P1, bounds it — see
``spanning_tree``'s own docstring for the measured table), computed
once inside ``_MapCanvas.__init__`` alongside the rest of the layout
and never per frame. The new
``"constellation"`` mode — now ``LINK_MODE``'s default — unions that
backbone with the existing kNN density: the backbone bridges every gap
kNN leaves open, kNN keeps the local shape dense and irregular, and the
backbone edges are deliberately exempt from ``LINK_MAX``, since capping
them would silently re-open the very islands they exist to close.
``"knn"`` and ``"chord"`` stay reachable, unchanged, for comparison.
The draw side (``_paint_constellation``) is untouched — it already
drew whatever ``self._links`` held, so a longer, connected edge list is
still exactly one batched ``drawLines`` call and dims with ``self._lit``
like every other constellation segment.

Measured on this machine at the four-PDF, 2,800-note fixture the map
tasks share for frame timing (1100x660): the backbone adds the sampled
cloud's own point count minus one, 863 total segments here against the
old cap of 300, and the whole frame still medians 1.1 ms — comfortably
inside the 4.0 ms floor, and in the same range as K-174 through K-188
(1.38-1.95, then 0.80-1.18).

**K-200: a sway, not a turn.** Pouya, having watched the full turn:
"have the constellation do a slight rotation in 3D so that 3D-ness is
very apparent" (and, earlier, "just have it rotate slowly in 3D" — the
ask never changed; the full turn just never delivered on it. 5 degrees
a second is too little drift to notice in any one glance, and every
quarter turn flips the far half of the cloud in front of the near
half). ``sway_angle`` replaces the wrapping phase with ``REST_ANGLE +
SWAY_AMP * sin(2*pi*t/SWAY_PERIOD_MS)`` — a there-and-back motion that
keeps a visible drift going at every instant and never approaches the
±90° pose where ``band_order`` would have to flip the paint order.
``CAM_DISTANCE`` drops from 2.6 to 2.0 alongside it — a nearer eye is a
stronger perspective, which is what makes the parallax between a near
star and a far one unmistakable across such a small arc (the near/far
size ratio goes from ~3.4x to ~5.8x for the same cloud). ``sweep_bounds``
gained an ``amplitude`` parameter (default ``SWAY_AMP``) so it frames
the sway's arc instead of a full circle — a much tighter box, since the
camera no longer visits the poses a full turn used to.

Measured on the same four-PDF, 2,800-note fixture the map tasks share
for frame timing (1100x660, reduce-motion forced so the sway's own
timer never fires mid-measurement): the frame still medians 1.12-1.17
ms across repeated runs, max 1.34-1.60 ms — comfortably inside the 4.0
ms floor and in the same range as K-174 through K-197 (1.38-1.95, then
0.80-1.41). The sway costs nothing extra per frame: one call to
``sway_angle`` and one ``Camera`` construction on the idle timer's own
tick, never inside ``paintEvent`` itself.

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
import random
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
LABEL_LINE_H = 14.0
# How close the label may come to the canvas edge. label_anchor mirrors
# only when the mirrored side FITS; when neither does it keeps the
# right-hand placement and the text runs off. clamp_label has the last
# word instead — three reports of a clipped name in this module is
# enough offset-nudging.
LABEL_EDGE_PAD = 6.0
# The unfocused PDFs: a ring at this alpha (scaled further by the K-188
# pointer ramp, self._lit) and nothing else — no core, no name, and a
# smaller ring than the lit node's own (K-186: this factor used to be a
# fifth of the node's halo; the halo is gone, but the constant — and the
# ghost's size relative to the ring — was not retuned). Pouya, K-158:
# "only one PDF shows at a
# time, potentially, and then it just zooms in on that section of the
# cloud that hosts that PDF." A GHOST rather than nothing at all,
# because the collection being bigger than what you are looking at is
# the mental conception the map exists to give; deleting the others
# would read as data loss. It also makes K-058's centroid pile-up stop
# mattering: four PDFs whose matched notes overlap have nearly the same
# mean position, so four lit rings land on top of one another.
GHOST_ALPHA = 0.22
GHOST_HALO_F = 0.7
# Pouya, 2026-09-01: "I want it to be dim, but then, as I put the mouse
# over it, it lights up to normal values." The canvas rests at DIM_LIT
# and ramps the whole field to 1.0 under the pointer; LIT_MS is the
# ramp, eased like fly. The chosen PDF and its name are exempt — "just
# for that one, to light up".
DIM_LIT = 0.45
LIT_MS = 180
# One standard wheel notch (angleDelta 120) zooms by 2**(120/240) ≈ 1.41.
WHEEL_ZOOM_DIVISOR = 240.0
# select_pdf recentres only when the node is outside the viewport inset
# by this much — a node already comfortably on screen must not make the
# map jump under the reader every time the PDF viewer changes file.
RECENTER_MARGIN = 24.0

# ── the camera (K-148) ───────────────────────────────────────────────────
# Eye distance from the z=0 plane, in world units. The cloud is a
# [-1, 1] cube, so the nearest possible point sits at d - sqrt(2) and the
# farthest at d + sqrt(2): at 2.0 that is a 0.59..3.41 depth range, i.e.
# the nearest dots draw ~5.8x larger than the farthest. Lower is more
# vertiginous and starts to fish-eye; higher flattens back toward the 2D
# map. Never let it approach sqrt(2), where w reaches zero and the
# projection blows up (CAM_W_FLOOR is the seatbelt, not the plan).
# Dropped from 2.6 at K-200: a nearer eye is a stronger perspective, and
# a stronger perspective is what makes the K-200 sway's much smaller arc
# (±16 degrees, against K-174's full turn) carry visible parallax —
# the near/far size ratio goes from ~3.4x to ~5.8x for the same cloud.
CAM_DISTANCE = 2.0
CAM_W_FLOOR = 0.2
# The pose the scene RESTS in — not zero, because zero is exactly the old
# flat map and the Library's dock renders this scene STILL (Pouya's
# explicit call: no idle spin while he works). A dock that never moves
# has to read as 3D in a single frame, and this is the yaw that does it.
REST_ANGLE = 0.30
# Idle motion WAS a FULL TURN from K-174 to K-200 — Pouya: "just have it
# rotate slowly in 3D". K-148 shipped a 0.42 rad sway instead, on two
# worries that were both checked here and are both wrong for this
# cloud. "A spin sweeps through the edge-on pose where the cloud
# collapses to a line" is true of a PLANE, and a PCA cloud is not one:
# at a quarter turn you are looking down the first component at the
# second and third, which are narrower but not flat, so the field
# breathes rather than collapsing (rendered at 12 poses). "Past ~60
# degrees the depth quantization shows as slabs" was true of 256 bands
# of GLOW SPRITES, whose overlapping halos made a slab a visible plane
# of light; a slab of 1-3px hard points is 1-3px of hard points. Both
# findings carry over to K-200's SWAY without re-checking: ±SWAY_AMP is
# smaller than K-148's own 0.42 rad sway, so if a full turn never came
# near either failure mode, a sway well inside it certainly does not.
#
# K-200 replaced the full turn with a SWAY: Pouya, having watched it for
# a day, asked for "a slight rotation in 3D so that 3D-ness is very
# apparent" — 72s/5 degrees a second was too gradual to read as motion
# in any one glance, and every quarter turn flipped the far half of the
# cloud in front of the near half. A sinusoidal there-and-back around
# REST_ANGLE keeps a visible drift going at every instant and never
# leaves the ±90 degree band that keeps band_order from ever flipping.
SWAY_AMP = 0.28            # radians, ±16 degrees
SWAY_PERIOD_MS = 14000.0   # one there-and-back
IDLE_TICK_MS = 33  # ~30 fps; the whole frame measures 1.0-1.5 ms (K-174)
# How many poses the sway's fit has to hold. The graph's screen extent
# changes with the pose — a [-1,1] box is ~41% wider at the diagonal
# corner-on than face-on — so a fit computed at one angle can still let
# the cloud step outside the card at the sway's own extreme. sweep_bounds
# unions the camera-plane box over the sway's arc at this resolution and
# pads for what the sampling still misses. The pad's own derivation
# (K-174) was measured for a FULL TURN at this same step count — 1.7% of
# the frame, verified over 300 random boxes at 360 poses each — and is
# carried over unchanged (K-200: "the pad stays, the arc is still a
# sinusoid in the sample index"); the sway's arc is far narrower than a
# full circle, so the same pad is, if anything, more conservative here.
SWEEP_STEPS = 24
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
#
# **This constant is COUPLED TO FLY_TRIM and the coupling is silent**
# (found by raising it on K-174). ``_fly_target`` frames the SAMPLE,
# trimmed by FLY_TRIM and then padded by FLY_PADDING, and clamps at
# the whole-graph fit — so for a PDF whose matches are scattered over
# the collection, drawing MORE of them widens the trimmed box until
# the padded frame exceeds the graph and the flight clamps to "no
# zoom at all", which is the exact K-158 bug FLY_TRIM exists to fix.
# Measured on a 400-match uniform fixture: 90 samples fly at 1.14x,
# 110 and 140 clamp at 1.00x, and 200 flies again. Raising this
# without raising FLY_TRIM alongside it silently deletes the flight;
# tests/test_pdf_map.py pins the pair.
SAMPLE_PER_PDF = 90
# The sample is an even STRIDE over the graph's own order, never a
# random draw: a stride thins a cloud uniformly (so its shape survives),
# it is deterministic (the map looks the same every time you open it),
# and it is what projection.py already does to pick its fit rows.

# ── K-174: the constellation ────────────────────────────────────────────
# THE finding, measured off aalampour.com's own canvas rather than
# guessed at: at the star threshold the longest run of lit pixels in a
# row is FOUR DEVICE px on a 2x canvas — one to two CSS px — and there
# is no skirt of mid-brightness pixels around it. A glow sprite cannot
# produce that, because its falloff IS a long run of mid-brightness
# pixels. Star blobs there are 2 device px in area at the median and 23
# at the very largest; lit pixels are 0.006% of the canvas at the star
# threshold. So a star here is a HARD POINT of one to three pixels with
# no halo at all, and depth is carried by SIZE and BRIGHTNESS.
#
# Re-measured rather than inherited (K-158 chose sprites over dots on a
# measurement that was about GLOWS). At 520 stars over 200 bands,
# 900x640, offscreen, this machine: the K-158 sprite blit is 0.341 ms a
# frame, a non-antialiased drawPoints is 0.280 ms at pen width 1,
# 0.312 at 2 and 0.292 at 3 — the pen width is free, so the whole 1-3px
# range costs the same as one. Antialiasing a POINT is also free
# (0.309 vs 0.312) and is off anyway: it is what turns a hard point
# into a soft one.
STAR_TIERS = 12
STAR_SIZE_MIN = 1
STAR_SIZE_MAX = 3
# > 1 holds the ramp down, so only the nearest tiers reach 3px. Without
# it a third of the field is 3px and the card carries four times the
# ink the reference does. At 2.1: tiers 0-4 draw 1px, 5-9 draw 2px,
# 10-11 draw 3px.
STAR_SIZE_GAMMA = 2.1
# The star colour ramp, as mixes of palette tokens (never invented
# colour). Every star sits on a cool base — the ground lifted toward
# the accent — and is mixed from there toward the text token by depth,
# so the far face of the cloud sinks into the ground as a dim blue and
# the near face lands ON the text token, a near-white. That is not a
# compromise with the reference: its bright pixels measure 214/222/248
# and 215/215/213, NOT 255/255/255, and #E0E0E0 over #191919 is that
# family. Opaque mixes, no alpha anywhere — K-148 measured alpha fog at
# 5x an opaque ramp for a picture the eye cannot tell apart, and the
# reference only uses alpha because a canvas over a CSS nebula has no
# other way to composite.
STAR_COOL = 0.30
STAR_FAR = 0.05
STAR_NEAR = 1.0
# When a PDF is active the rest of the cloud recedes: mixed this far
# back toward the ground so the PDF's own notes stand out instead of
# drowning in everything else.
STAR_DIM_KEEP = 0.5
# The active PDF's own notes are drawn one size up and at the top of
# the brightness ramp — they are what the flight is for.
STAR_LINK_BOOST = 1
# ...and how much of the size ramp a SMALL canvas gets. fit_margin's
# K-143 lesson, one layer down: a dot sized for a 900x640 window is a
# blot in the Library's 545x185 dock, where the fit packs the whole
# cloud into about 110px. Quantized to tenths so dragging the dock's
# splitter cannot thrash anything.
DOT_SCALE_FULL = 420.0
DOT_SCALE_FLOOR = 0.55

# The random interconnections. Pouya: "I want each node on the graph to
# be just randomly interconnected... it looks kind of cool." Decorative,
# and he has twice said the map's purpose is to look cool — but it has
# to be STABLE, so the seed is derived from the drawn cloud itself
# (link_seed) and never from process-random hash().
#
# Two topologies were built and RENDERED first. "knn" joins each star
# to its nearest neighbours within LINK_MAX_SPAN; "chord" draws
# uniformly random pairs. The chord render is a cross-hatched mess that
# hides the cloud it is drawn over — every segment crosses the whole
# card — while the nearest-neighbour render is a constellation. Neither
# ships alone: kNN only ever joins a star to a NEARBY partner, so a
# collection whose topics cluster far apart in the embedding draws
# several disconnected constellations rather than one sky — not what
# "randomly interconnected" asked for once there is more than one
# cluster (K-197, Pouya looking at exactly that: "Can you have all the
# nodes be interconnected in a satisfying way"). "constellation" =
# spanning-tree backbone (connected by construction) plus the kNN
# density; "knn" and "chord" remain reachable for comparison.
LINK_MODE = "constellation"
LINK_NEIGHBOURS = 2
# World units. The drawn cloud spans about [-1, 1], so this is roughly
# a tenth of the field: far enough to find a partner in the dense
# middle, short enough that a lonely star in a sparse corner stays
# lonely instead of reaching across the card.
LINK_MAX_SPAN = 0.13
# The cap IS the frame budget, and it is generous: measured here,
# batched non-antialiased drawLines costs 0.069 ms at 120 segments,
# 0.153 at 260 and 0.537 at 1000. A seeded shuffle picks which
# candidates survive the cap, so the surviving figure is irregular
# rather than "every link in the first corner of the list".
LINK_MAX = 300
# Fold constant for link_seed — an arbitrary odd multiplier, present so
# two clouds that differ only in point order still differ in seed.
LINK_SEED = 0x4B4C4155
# How far the constellation line sits from the ground, toward the star
# colour. Very low on purpose: on the reference the links only appear
# at all below 10% opacity, and they are the thing you notice second.
LINK_MIX = 0.15
# The focused PDF's own spokes, which ARE the point of the focused view
# and are drawn much brighter than the ambient constellation. Crisp
# 1px, non-antialiased, one batched drawLines — measured at 0.092 ms
# for 90 long segments against the 6.35 ms K-158 measured for the
# antialiased glowing strokes it rejected, and 2.51 ms for all 2,087 of
# the biggest PDF's edges against K-158's 39.8 ms. The cost was never
# the composition mode and never the call count: it was the AA
# rasterizer, whose price is the stroke's device-space AREA.
EDGE_MIX = 0.55
# ...and how it TAPERS. Rendered at a flat brightness first: 140 hard
# lines all converging on one node is a dandelion, and the long reaches
# carry as much weight as the hub they are about. Split into this many
# segments per spoke, each dimmer than the last down to EDGE_TAIL of
# the hub value, the fan is dense and bright where the PDF is and
# dissolves into the field at the far end — which is also the honest
# picture, since a far match is a weaker one. Costs one setPen and one
# batched drawLines per step (0.09 ms for all 140 spokes at three
# steps), against 6.35 ms for the antialiased glowing version K-158
# measured and rejected.
EDGE_TAPER = 3
EDGE_TAIL = 0.22
# Spokes leave the node's RIM plus this gap: lines converging on one
# point swallow the node they are supposed to be about.
EDGE_HUB_GAP = 3.0
# A PDF node is a core + ring, never a filled disc. Fractions of the
# node radius: the lit core and the ring's stroke. K-174 kept a real
# radial-gradient halo here too, as "the one thing that still
# glows" — Pouya, in the same breath as "I don't want these glowy
# things": "I like the shininess of the PDFs. I like that." K-186
# retired the halo itself (Pouya: "remove the general glow... I don't
# like the general glow that comes with it") — the shininess he meant
# lives on in the ring and core that remain.
NODE_CORE_F = 0.42
NODE_CORE_MIX = 0.75
NODE_RING_W = 1.6
NODE_SELECT_GAP = 5.0
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


def sway_angle(t_ms: float, rest: float = REST_ANGLE, amp: float = SWAY_AMP,
               period_ms: float = SWAY_PERIOD_MS) -> float:
    """The camera yaw at time ``t_ms`` into the sway (K-200).

    ``rest + amp * sin(2*pi*t/period)`` — a there-and-back motion that
    keeps a visible drift going at every instant (unlike a full turn,
    which crawls at any single moment) and never reaches an angle where
    ``band_order`` would need to flip the paint order. ``_idle_tick``
    drives ``t_ms`` from ``self._phase``, an elapsed-milliseconds
    counter wrapped at ``period_ms`` — not an angle, since K-174's
    revolution.
    """
    return rest + amp * math.sin(
        2.0 * math.pi * float(t_ms) / max(1.0, float(period_ms))
    )


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


def sweep_bounds(
    box: Sequence[float], cam: Camera, steps: int = SWEEP_STEPS,
    amplitude: float = SWAY_AMP,
) -> tuple:
    """``camera_bounds`` unioned over THE SWAY'S ARC — what a canvas
    that sways has to frame (K-174, arc narrowed at K-200).

    A box's screen extent depends on the pose: a [-1, 1] cube is about
    41% wider seen corner-on than face-on, so a fit computed at the
    resting angle alone can still let the cloud step outside the card
    at the sway's own extreme. Sampled and then PADDED, rather than
    solved. Under a yaw a point at radius R traces ``u = R cos(theta -
    phi)``, so the extent is a sinusoid in the angle and N samples
    undershoot its true peak by about ``1 / cos(pi / N)``. That is the
    ORTHOGRAPHIC bound and it is not enough here: the perspective divide
    and an off-centre box between them need about half as much again
    (measured over 300 random boxes and 180 poses each, for a FULL TURN
    at K-174 — 1.053 required at 24 steps against the bound's 1.035, and
    74 of 800 box/step pairs overflowed a bare 1/cos pad). Squaring it
    held at SWEEP_STEPS on every one of 300 random boxes at 360 poses of
    a full turn, and cost 1.7% of the frame; K-200 carries the same pad
    over UNCHANGED for the sway's much narrower arc — ``amplitude *
    sin(2*pi*i/n)`` is still a sinusoid in the sample index ``i``, and a
    narrower arc is, if anything, an easier bound to hold than the full
    turn this pad was proven against. The alternative, the analytic
    swept hull of a box under a perspective divide, is a page of algebra
    to save twenty-three calls that happen once per fit.

    ``steps <= 1`` degrades to the single-pose box, which is what the
    Library's dock (still, never swaying) actually wants.
    """
    n = int(_num(steps, SWEEP_STEPS))
    if n <= 1:
        return camera_bounds(box, cam)
    amp = _num(amplitude, SWAY_AMP)
    us0: list = []
    vs0: list = []
    us1: list = []
    vs1: list = []
    for i in range(n):
        pose = Camera(cam.angle + amp * math.sin(2.0 * math.pi * i / n),
                       cam.distance)
        u0, v0, u1, v1 = camera_bounds(box, pose)
        us0.append(u0)
        vs0.append(v0)
        us1.append(u1)
        vs1.append(v1)
    u0, v0, u1, v1 = (min(us0), min(vs0), max(us1), max(vs1))
    pad = 1.0 / max(1e-6, math.cos(math.pi / max(3, n))) ** 2
    cu = (u0 + u1) / 2.0
    cv = (v0 + v1) / 2.0
    return (cu + (u0 - cu) * pad, cv + (v0 - cv) * pad,
            cu + (u1 - cu) * pad, cv + (v1 - cv) * pad)


def frame_bounds(
    box: Sequence[float],
    cam: Camera,
    widget_size: Sequence[float],
    sweep: int = 0,
) -> Viewport:
    """The viewport that frames a 3D box at this camera pose — the ONE
    path every fit takes (initial, Fit button, Escape, click-to-fly), so
    the compact-canvas margin cap reaches all of them.

    ``sweep`` > 1 frames the box over that many poses of the sway's arc
    instead of the one it is in (K-174, arc narrowed at K-200: a
    swaying canvas has to fit every pose it will show, not the pose it
    happens to start in). The default 0 is the single-pose fit the
    still dock wants.
    """
    box2 = (
        sweep_bounds(box, cam, sweep) if int(_num(sweep, 0.0)) > 1
        else camera_bounds(box, cam)
    )
    return fit_to_view(box2, widget_size, fit_margin(widget_size))


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

    Separate from ``links_for`` because the sample wants the
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


def tier_index(shade: float, tiers: int = STAR_TIERS) -> int:
    """Which star tier a band's fog shade falls in.

    The colour/size lookup is per TIER, not per band: 256 bands would
    mean 256 pens for a ramp the eye reads as a dozen steps. Clamps
    rather than raises, because this is on the paint path.
    """
    t = int(_num(tiers, STAR_TIERS))
    if t <= 1:
        return 0
    i = int(_clamp(_num(shade), 0.0, 1.0) * t)
    return t - 1 if i >= t else i


def tier_position(index: int, tiers: int = STAR_TIERS) -> float:
    """Where a tier sits on the far->near ramp, in [0, 1] — its middle,
    so the ends are not forced to exactly 0 and 1 by an off-by-one."""
    t = int(_num(tiers, STAR_TIERS))
    if t <= 1:
        return 1.0
    return _clamp((int(_num(index)) + 0.5) / t, 0.0, 1.0)


def star_colour(c: dict, pos: float, dim: bool = False, lit: float = 1.0) -> str:
    """One OPAQUE hex for a star at ramp position ``pos`` (K-174).

    A mix of palette TOKENS, so the whole field re-colours with the
    accent theme and this file still names no colour of its own. Every
    star sits on a cool base — the ground lifted toward the accent —
    and travels from there toward the text token, so the far face of
    the cloud sinks into the ground as a dim blue while the near face
    lands exactly ON ``text``, the palette's near-white.

    That last part is a measurement, not a compromise with the house
    rule. The reference's brightest pixels read 214/222/248 and
    215/215/213, and NOT ONE of them is 255/255/255 — so the DARK
    palette's own text token over its own ground is already the right
    family, and "no invented colour" and the design brief happen to
    want the same thing.

    Opaque, never alpha: K-148 measured alpha fog at 5x the cost of an
    opaque mix against the ground, for a picture the eye cannot tell
    apart. The reference reaches for alpha only because a canvas
    floating over a CSS nebula has no ground of its own to mix into.

    ``dim`` mixes back toward the ground — the ambient field while a
    PDF is focused, so its own notes are not lost in everything else.

    ``lit`` (K-188) is the whole-field pointer ramp, in [0, 1]: 1.0 (the
    default, and where the pointer rests over the canvas) leaves the
    result exactly as above, and DIM_LIT blends it back toward the
    ground the SAME way ``dim`` does — applied AFTER ``dim`` so a
    focused PDF's own notes dim from their own boosted colour, not from
    the ambient one. One mechanism, two independent callers: which
    stars are "someone's own notes" (``dim``) and whether the pointer is
    over the field at all (``lit``) are orthogonal questions.
    """
    t = _clamp(_num(pos), 0.0, 1.0)
    ground = c["bg"]
    base = blend_hex(ground, c["blue_bright"], STAR_COOL)
    out = blend_hex(base, c["text"], STAR_FAR + (STAR_NEAR - STAR_FAR) * t)
    if dim:
        out = blend_hex(ground, out, STAR_DIM_KEEP)
    keep = STAR_DIM_KEEP + (1.0 - STAR_DIM_KEEP) * _clamp(float(lit), 0.0, 1.0)
    if keep < 1.0:
        out = blend_hex(ground, out, keep)
    return out


def edge_mix(index: int, steps: int = EDGE_TAPER) -> float:
    """How far from the ground a focused PDF's spoke is painted, for
    segment ``index`` of ``steps`` along its length (K-174).

    The taper, as one number, so the ramp is testable without a render
    and the painter cannot grow a second copy of it. Brightest at the
    hub and falling to ``EDGE_TAIL`` of that at the tip: 90 hard lines
    all converging on one node is a dandelion whose far ends carry as
    much weight as the node they are about — rendered flat first, which
    is how that was found. It is also the honest picture, since a match
    at the far end of the cloud is a weaker one.
    """
    n = max(1, int(_num(steps, EDGE_TAPER)))
    i = int(_clamp(_num(index), 0.0, float(n - 1)))
    fade = 1.0 if n == 1 else 1.0 - i / (n - 1.0)
    return EDGE_MIX * (EDGE_TAIL + (1.0 - EDGE_TAIL) * fade)


def star_size(pos: float, scale: float = 1.0) -> int:
    """A star's side in WHOLE pixels, 1..3 (K-174) — the hard half of
    how depth reads now that nothing blurs.

    Integers because the point is drawn with a square-capped pen and no
    antialiasing: a fractional width is resolved by Qt into a soft
    edge, which is the exact thing the reference does not have.
    ``STAR_SIZE_GAMMA`` holds the ramp down so only the nearest tiers
    reach 3px — the reference's median blob is 2 device pixels on a 2x
    canvas, so a field of uniformly 3px stars carries four times its
    ink.
    """
    t = _clamp(_num(pos), 0.0, 1.0) ** max(0.05, STAR_SIZE_GAMMA)
    px = STAR_SIZE_MIN + (STAR_SIZE_MAX - STAR_SIZE_MIN) * t
    px *= _clamp(_num(scale, 1.0), 0.05, 1.0)
    return int(_clamp(round(px), STAR_SIZE_MIN, STAR_SIZE_MAX))


def link_seed(points: Sequence, salt: int = LINK_SEED) -> int:
    """A stable seed derived from the DRAWN CLOUD itself (K-174).

    The constellation must be the same figure every time a collection
    opens — re-rolled per frame the field shimmers, and a shimmering
    field reads as a bug rather than as a sky — and a different figure
    for a different collection. ``hash()`` cannot do either: Python
    randomizes str/bytes hashing per process, so the same library would
    draw a different constellation every launch. This folds the
    quantized coordinates by hand instead.

    Quantized to 1e-4 so a float that round-trips through the on-disk
    JSON cannot change the seed, and masked to 32 bits so the value is
    the same on every build.
    """
    h = int(salt) & 0xFFFFFFFF
    for pt in points:
        try:
            x, y, z = (float(v) for v in pt[:3])
        except (TypeError, ValueError, IndexError):
            continue
        for v in (x, y, z):
            h = (h * 16777619 + (int(round(v * 10000.0)) & 0xFFFFFFFF))
            h &= 0xFFFFFFFF
    return h


def spanning_tree(points: Sequence) -> list:
    """Prim's minimum spanning tree over Euclidean distance — the backbone
    that makes the constellation ONE figure (K-197). Pouya: "Can you have
    all the nodes be interconnected in a satisfying way... I want each
    node on the graph to be just randomly interconnected." kNN alone
    only ever joins a star to a NEARBY partner, so a collection whose
    topics cluster far apart in the embedding draws several disconnected
    constellations rather than one sky; the tree bridges every gap kNN
    leaves open.

    O(n^2) on the sampled cloud (~520 points -> ~270k distances).
    Measured (final review, 2026-09-02): ~25 ms there, cleanly
    quadratic — growing 3.7x-4x per doubling, not the sub-millisecond
    this docstring once claimed; K-199 (P1) is the card that bounds it.
    Never run this on the full index.
    Pure and deterministic — no RNG anywhere in it, unlike the kNN/chord
    modes below, which both need a seed.

    Returns ``n - 1`` unique ``(i, j)`` pairs with ``i < j`` for
    ``n >= 2``, ``[]`` otherwise (mirrors ``constellation_links``' own
    degenerate-input handling).
    """
    n = len(points)
    if n < 2:
        return []
    in_tree = [False] * n
    best = [float("inf")] * n
    link = [-1] * n
    best[0] = 0.0
    out = []
    for _ in range(n):
        u = min((i for i in range(n) if not in_tree[i]), key=lambda i: best[i])
        in_tree[u] = True
        if link[u] >= 0:
            out.append((link[u], u) if link[u] < u else (u, link[u]))
        ux, uy, uz = points[u][0], points[u][1], points[u][2]
        for v in range(n):
            if in_tree[v]:
                continue
            d = (points[v][0] - ux) ** 2 + (points[v][1] - uy) ** 2 + (points[v][2] - uz) ** 2
            if d < best[v]:
                best[v] = d
                link[v] = u
    return sorted(out)


def constellation_links(
    points: Sequence,
    mode: str = LINK_MODE,
    neighbours: int = LINK_NEIGHBOURS,
    cap: int = LINK_MAX,
    max_span: float = LINK_MAX_SPAN,
) -> list:
    """The decorative interconnections, as index pairs into ``points``.

    Pouya, K-174: "I want each node on the graph to be just randomly
    interconnected... it looks kind of cool." Purely decorative — it
    says nothing about the embedding — and he has twice said the map's
    job is to look cool, so that IS the requirement. K-197 added a
    second requirement from the same conversation, re-read: "Can you
    have all the nodes be interconnected in a satisfying way" — kNN
    alone leaves far-apart topic clusters as separate islands, which
    reads as several unrelated constellations rather than one sky.

    Three topologies, all built and RENDERED before choosing:

    - ``"knn"``: each point joined to its ``neighbours`` nearest
      partners within ``max_span``. Short segments that trace the local
      shape of the cloud — this is what reads as a constellation, and
      it is also the only version of this decoration that tells a small
      truth about the data underneath it. Leaves any sufficiently
      isolated cluster of points unconnected to the rest.
    - ``"chord"``: uniformly random pairs. Every segment crosses the
      whole card and the cloud disappears behind a cross-hatch. Kept
      reachable because it is the thing ``knn`` has to be better than,
      and because "randomly interconnected" could have meant it.
    - ``"constellation"`` (``LINK_MODE``'s default): ``spanning_tree``'s
      backbone — one minimum spanning tree over the same cloud, which
      is connected BY CONSTRUCTION — unioned with the ``"knn"`` density
      on top. The backbone edges are NEVER subject to ``cap``: they are
      what bridges a gap kNN leaves open, and capping them would
      silently re-open it. ``cap`` still bounds the kNN extras exactly
      as it always did.

    Deterministic in every mode: the RNG is seeded from the points
    themselves (``spanning_tree`` itself carries no randomness at all —
    Prim's algorithm over a fixed point order is deterministic on its
    own). The seeded shuffle BEFORE the cap matters — keeping the
    first ``cap`` candidates in index order piles every surviving
    segment into whichever corner of the cloud the sample listed first.

    Returns sorted unique ``(i, j)`` pairs with ``i < j``.
    """
    n = len(points)
    limit = int(_num(cap, 0.0))
    if n < 2 or limit <= 0:
        return []
    rng = random.Random(link_seed(points))
    pairs: set = set()
    # The backbone is unioned in AFTER the cap below, so it is never
    # subject to it — a spanning tree bridging a gap is exactly the
    # edge a random cap-shuffle would be free to drop (K-197).
    backbone: set = set()
    if mode == "constellation":
        backbone = set(spanning_tree(points))
        mode = "knn"
    if mode == "chord":
        # Bounded: a random draw over n^2 pairs is a lottery with
        # replacement, so ask for a few more than the cap and stop.
        for _ in range(limit * 3):
            if len(pairs) >= limit:
                break
            i = rng.randrange(n)
            j = rng.randrange(n)
            if i != j:
                pairs.add((i, j) if i < j else (j, i))
    elif mode == "knn":
        span = max(0.0, _num(max_span, LINK_MAX_SPAN))
        k = max(1, int(_num(neighbours, LINK_NEIGHBOURS)))
        # A uniform grid keyed on the span, so the build is linear in
        # the cloud rather than quadratic. SAMPLE_NOTES = 0 is still a
        # supported setting and it hands this every note in the
        # collection: 28,670 points squared is 400 million distance
        # evaluations, on the main thread, while the window opens.
        cell = span if span > 1e-6 else 1.0
        grid: dict = {}
        pts: list = []
        for idx, pt in enumerate(points):
            try:
                x, y, z = (float(v) for v in pt[:3])
            except (TypeError, ValueError, IndexError):
                pts.append(None)
                continue
            pts.append((x, y, z))
            grid.setdefault(
                (int(x // cell), int(y // cell), int(z // cell)), []
            ).append(idx)
        span2 = span * span
        for i, a in enumerate(pts):
            if a is None:
                continue
            cx = int(a[0] // cell)
            cy = int(a[1] // cell)
            cz = int(a[2] // cell)
            near: list = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for j in grid.get((cx + dx, cy + dy, cz + dz), ()):
                            if j == i:
                                continue
                            b = pts[j]
                            d = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                                 + (a[2] - b[2]) ** 2)
                            if d <= span2:
                                near.append((d, j))
            near.sort()
            for _d, j in near[:k]:
                pairs.add((i, j) if i < j else (j, i))
    else:
        return []
    out = sorted(pairs)
    if len(out) > limit:
        rng.shuffle(out)
        out = sorted(out[:limit])
    return sorted(backbone | set(out))


def dot_scale(widget_size: Sequence[float]) -> float:
    """How big this canvas's stars are, as a fraction of full size.

    ``fit_margin``'s rule applied to the dots themselves (K-158): the
    Library's dock is a 545x185 thumbnail of the SAME scene, and at that
    size the fit packs the whole cloud into roughly 110px — where a dot
    sized for the standalone window overlaps its neighbours into one
    white lump. Quantized to tenths so dragging the dock's splitter
    cannot thrash the pen cache.
    """
    try:
        smaller = min(float(widget_size[0]), float(widget_size[1]))
    except (TypeError, ValueError, IndexError):
        return 1.0
    if smaller != smaller or smaller <= 0:  # NaN or no surface yet
        return 1.0
    return _clamp(round(smaller / DOT_SCALE_FULL, 1), DOT_SCALE_FLOOR, 1.0)


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
    """What the canvas writes beside the focused node: the NAME, alone.
    Folder, matched count and retention left with the plate (Pouya:
    'remove the little box around it'); they live in the Library tree."""
    return [str(pdf.get("display") or pdf.get("safe") or "")]


def clamp_label(x: float, text_width: float, view_width: float,
                pad: float = LABEL_EDGE_PAD) -> float:
    """``x`` pulled back inside the canvas, whatever ``label_anchor``
    chose.

    ``label_anchor`` mirrors a label to the left when the right-hand
    placement would overrun — but only when the left placement FITS.
    When neither side fits (a wide name, a node near an edge, a node
    projected off-canvas entirely) it keeps the right-hand one and the
    text runs off the edge. That has now been reported three times in
    this module, so the last word belongs to a clamp rather than to
    another offset: the label is placed by preference and then made to
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

    K-254 review Minor 10: each PDF's own ``judged.json`` is read here
    too (guarded — same "never break the map" rule as everything else
    in this function) so the map's tooltip agrees with the Library's own
    confirmed score instead of quietly reverting to the pre-K-254
    unconfirmed one.
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

        try:
            from . import pertinence

            user_files = retention.USER_FILES
        except Exception:
            pertinence = None
            user_files = None

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
            safe = str(p.get("safe"))
            matches = by_pdf.get(safe)
            if not matches:
                continue
            rejected: set = set()
            if pertinence is not None:
                try:
                    rejected = pertinence.rejected_nids(
                        pertinence.load_judged(user_files, safe)
                    )
                except Exception as exc:
                    print(f"[klausmate] map judged.json unreadable for {safe!r}: {exc}")
            stats = retention.pdf_retention(
                matches, float(p.get("threshold") or 0.0), card_r, rejected=rejected
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
            QLineF,
            QPainter,
            QPen,
            QPointF,
            QPolygonF,
            QPropertyAnimation,
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
            self._pens: dict = {}
            self._pen_key = None
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
            # ---- K-174: the constellation ----
            # ONE flat draw list over every band of every group, sorted
            # by depth so band_order still gives painter's order across
            # the whole cloud rather than only inside one group. Each
            # entry is (band index, band z, polygon, owning PDF or
            # None), and its position in this list is the SLOT the
            # constellation's endpoints refer to.
            self._draw: list = [
                (idx, zb, poly, None) for idx, zb, poly in self._bands
            ]
            for safe, group in self._link_bands.items():
                self._draw.extend(
                    (idx, zb, poly, safe) for idx, zb, poly in group
                )
            self._draw.sort(key=lambda t: t[0])
            # The constellation is built over EVERY drawn point,
            # ambient and matched alike — a PDF's own notes floating
            # unconnected inside a linked field would read as a hole.
            # Endpoints are stored as (slot, index-in-that-polygon)
            # pairs, resolved once here, so the per-frame cost is two
            # QPolygonF lookups and one QLineF per segment and the
            # projection stays in C++ where K-138 put it.
            self._links: list = []
            try:
                flat: list = []
                addr: list = []
                for slot, (_idx, _zb, poly, _safe) in enumerate(self._draw):
                    for k in range(int(poly.count())):
                        pt = poly.at(k)
                        flat.append((pt.x(), pt.y(), _zb))
                        addr.append((slot, k))
                self._links = [
                    (addr[i][0], addr[i][1], addr[j][0], addr[j][1])
                    for i, j in constellation_links(flat, LINK_MODE)
                ]
            except Exception as exc:
                # Decoration, and the only thing here that walks the
                # polygons point by point. A map with no constellation
                # is still a map; a canvas that failed to construct is
                # a hole in the Library.
                print(f"[klausmate] map constellation unavailable: {exc}")
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
            # K-188: dim at rest, full under the pointer. Starts at
            # DIM_LIT — the FIRST paint is already dim, never a flash of
            # full brightness before the first leaveEvent ever fires.
            self._lit = DIM_LIT
            self._lit_anim = QPropertyAnimation(self, b"lit", self)
            self._lit_anim.setDuration(LIT_MS)
            self._lit_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
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
                # A SWAY since K-200, not K-174's full turn: self._phase
                # is now ELAPSED MILLISECONDS into the sway, wrapped at
                # SWAY_PERIOD_MS, and sway_angle turns that into the
                # yaw. The sway never crosses +-90 degrees, so
                # band_order's flip on the sign of cos(angle) — which
                # made a whole revolution legal — never fires; nothing
                # here relies on it firing either.
                self._phase = (self._phase + IDLE_TICK_MS) % SWAY_PERIOD_MS
                self._cam = Camera(
                    sway_angle(self._phase), self._cam.distance
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

        # The pointer ramp's animated property (K-188). Unlike ``fly`` it
        # never re-derives the viewport — repainting is enough, since
        # every colour that reads ``self._lit`` is computed fresh inside
        # ``_paint``.
        def _get_lit(self) -> float:
            return float(self._lit)

        def _set_lit(self, value: float) -> None:
            v = _clamp(float(value), 0.0, 1.0)
            if v != self._lit:
                self._lit = v
                self.update()

        lit = pyqtProperty(float, _get_lit, _set_lit)

        def set_lit_target(self, value: float) -> None:
            """Ramp the whole field to ``value`` — snap under reduce-motion,
            the same rule ``fly_to`` follows."""
            try:
                self._lit_anim.stop()
                if self._reduce_motion() or not self.isVisible():
                    self._set_lit(value)
                    return
                self._lit_anim.setStartValue(self._lit)
                self._lit_anim.setEndValue(float(value))
                self._lit_anim.start()
            except Exception as exc:
                print(f"[klausmate] map lit ramp failed: {exc}")
                self._set_lit(value)

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
            # The same swept rule as the whole-graph fit (K-174): the
            # flight lands on a cluster that then has to survive a full
            # revolution, and framing it at the pose it happened to be
            # clicked in walks it out of the card a few seconds later.
            sweep = self._sweep()
            target = frame_bounds(box, self._cam, size, sweep)
            floor = frame_bounds(self._bounds, self._cam, size, sweep).scale
            if target.scale < floor:
                target = frame_bounds(self._bounds, self._cam, size, sweep)
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
            self._vp = frame_bounds(
                self._bounds, self._cam, (w, h), self._sweep()
            )
            self._did_fit = True

        def _sweep(self) -> int:
            """How many poses this canvas's fits have to hold (K-174,
            arc narrowed at K-200).

            A SWAYING canvas frames the swept box, because it will show
            every pose of the sway's arc and a box framed at the
            resting angle alone can still leave the cloud stepping
            outside the card at the sway's own extreme. A canvas that
            never moves (the Library's dock, Pouya's explicit call)
            frames the one pose it has, and keeps K-158's tighter crop.
            """
            return SWEEP_STEPS if self._idle_want else 0

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

        def _ensure_pens(self, c: dict, scale: float = 1.0) -> None:
            """Build the star pens — one per (tier, dimmed?, matched?) —
            once per palette (K-174, replacing the glow-sprite cache).

            A star is now a square-capped pen of 1, 2 or 3 px drawn by
            ``drawPoints`` with antialiasing OFF, so there is nothing to
            pre-render: the cache holds QPens, not QPixmaps. Re-measured
            rather than inherited from K-158, which chose sprites over
            dots for a GLOW: at 520 stars over 200 bands, 900x640, the
            sprite blit is 0.341 ms a frame and the hard drawPoints is
            0.28-0.31 ms at every pen width in the range. The pen width
            is free; what it buys is the reference's hard edge.

            Keyed on the palette's actual tokens rather than on
            ``night_mode()``: ``c`` is the HOST palette since K-185 (see
            ``_paint``), so a night flip changes these tokens same as an
            ACCENT theme switch does, and keying on the tokens directly
            catches both with the one cache — no separate
            ``night_mode()`` flag to keep in step with it.

            K-188 folds the pointer ramp into the same cache: ``self._lit``
            is quantised to sixteenths (``q``) before joining the key, so
            an animated ramp rebuilds these pens at most 17 times over
            its whole 0->1 sweep rather than every single frame.
            """
            q = round(self._lit * 16) / 16.0
            key = (c["bg"], c["blue_bright"], c["text"], scale, q)
            if self._pens and self._pen_key == key:
                return
            out: dict = {}
            for i in range(STAR_TIERS):
                pos = tier_position(i)
                for dim in (False, True):
                    out[(i, dim, False)] = self._star_pen(
                        star_colour(c, pos, dim, lit=q), star_size(pos, scale)
                    )
                # A focused PDF's own notes: one size up and at the top
                # of the brightness ramp, because they are what the
                # flight is for.
                out[(i, False, True)] = self._star_pen(
                    star_colour(c, min(1.0, pos + (1.0 - pos) * 0.6), lit=q),
                    min(STAR_SIZE_MAX, star_size(pos, scale)
                        + STAR_LINK_BOOST),
                )
            self._pens = out
            self._pen_key = key

        @staticmethod
        def _star_pen(hexc: str, px: int):
            """One hard star: an opaque square-capped pen.

            SquareCap, not RoundCap: ``drawPoints`` draws each point as
            the pen's cap, and a round cap is a circle Qt has to
            rasterize as a path (K-148 measured that at 16x a square).
            A square cap with antialiasing off is a literal N-by-N block
            of one colour — which is the reference's whole look, where
            the longest run of lit pixels in a row is three.
            """
            pen = QPen(QColor(hexc), float(max(1, int(px))))
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            return pen


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
            # The map is drawn ON the panel it lives in: its colour maths
            # (star_colour, links, nodes) all blend outward from c["bg"], so
            # pointing c["bg"] at the host's chrome token makes every layer
            # composite over the real ground in BOTH palettes. The
            # always-dark palette(True) of K-174 made the map a dark card on
            # a light panel — the exact "separate box" Pouya asked to lose.
            host = theme.palette(theme.night_mode())
            c = dict(host, bg=host["chrome"])
            w = float(self.width())
            h = float(self.height())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            self._paint_ground(painter, c, w, h)

            self._ensure_fit(w, h)
            vp = self._vp
            cam = self._cam
            active = active_pdf(self._hover, self._selected)

            self._ensure_pens(c, dot_scale((w, h)))
            # ANTIALIASING OFF for the stars and every line (K-174).
            # This is the look, not an optimisation: an antialiased 1px
            # point is a soft 2x2 smear, and the reference's defining
            # measurement is that no run of lit pixels there is longer
            # than three with nothing around it. Measured free either
            # way on points (0.309 ms AA against 0.312 without), and
            # worth 40% on lines (0.153 ms against 0.248 at 260
            # segments) — so the look is free and the lines are a
            # bonus. No composition mode either: hard opaque points do
            # not stack, so SourceOver is correct and Plus was only ever
            # for halos that no longer exist.
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            mapped = self._paint_stars(painter, vp, cam, active, w, h)
            self._paint_constellation(painter, c, mapped, active)
            self._paint_edges(painter, c, vp, cam, active, w, h)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            drawn = self._paint_nodes(painter, c, vp, cam, active, w, h)
            # The name LAST, over every node (K-158). It used to be
            # emitted inside the depth-sorted node loop, right after its
            # own circle — so any PDF that sorted nearer painted its
            # disc straight over the label. On the real graph the four
            # centroids sit within ~50px of each other and that is
            # exactly what happened: label_anchor had cleared its own
            # node's rim by 9px, and a neighbour swallowed the first
            # third of the name anyway.
            self._paint_label(painter, c, drawn, active, w, h)

        def _paint_ground(self, painter, c, w, h) -> None:
            """Flat. The panel's own ground, edge to edge — no card, no
            border, no vignette. The field recedes by depth (size and
            brightness), not by a lift under it."""
            painter.fillRect(QRectF(0.0, 0.0, float(w), float(h)), QColor(c["bg"]))

        def _paint_stars(self, painter, vp, cam, active, w, h) -> list:
            """The whole note cloud as HARD POINTS, farthest slab first.

            Each band's projective QTransform does the rotate +
            perspective + world->screen pass for all of its points in
            C++ (band_matrix derives it), so the Python cost per frame
            is the number of BANDS — never a per-point projection. The
            transform belongs on the POLYGON, never on the painter:
            K-138 rendered and confirmed that a painter transform
            degenerates a point draw into long horizontal strokes at
            deep zoom, and a painter cannot carry a perspective divide
            at all.

            What changed at K-174 is only what is drawn AT each mapped
            point: one square-capped, non-antialiased, opaque pen of 1
            to 3 px through ``drawPoints`` — one C++ call per band —
            instead of K-158's Python loop blitting a glow sprite per
            dot. That per-dot loop was the last per-point Python on the
            cloud's paint path and it is gone.

            Returns the mapped polygons by slot, because the
            constellation's endpoints live in two different bands and
            re-projecting them would put the per-point loop back.
            """
            mapped: list = [None] * len(self._draw)
            for i in band_order(cam, len(self._draw)):
                idx, zb, poly, safe = self._draw[i]
                pen = self._pens.get((
                    tier_index(self._fog[idx]),
                    bool(active) and safe != active,
                    safe is not None and safe == active,
                ))
                if pen is None:
                    continue
                m = QTransform(*band_matrix(vp, cam, zb)).map(poly)
                mapped[i] = m
                painter.setPen(pen)
                painter.drawPoints(m)
            return mapped

        def _paint_constellation(self, painter, c, mapped, active) -> None:
            """The random interconnections — one batched ``drawLines``.

            Pouya, K-174: "I want each node on the graph to be just
            randomly interconnected... it looks kind of cool." The
            topology and the stability live in ``constellation_links``;
            this is only the draw, and it is deliberately the cheapest
            thing on the frame: crisp 1px, no antialiasing, opaque, one
            call. Measured at 0.153 ms for 260 segments — against the
            6.35 ms K-158 measured for the antialiased glowing strokes
            it rejected, which is why "crisp instead of blurry" is not
            the trade it looked like.

            Barely there on purpose. On the reference these links only
            resolve below 10% opacity: they are what you notice second,
            after the stars, and a constellation whose lines shout is a
            wireframe.
            """
            if not self._links:
                return
            ink = QColor(blend_hex(
                c["bg"], star_colour(c, 1.0, lit=self._lit), LINK_MIX))
            pen = QPen(ink, 1.0)
            painter.setPen(pen)
            segs = []
            for sa, ka, sb, kb in self._links:
                pa = mapped[sa]
                pb = mapped[sb]
                if pa is None or pb is None:
                    continue
                segs.append(QLineF(pa.at(ka), pb.at(kb)))
            if segs:
                painter.drawLines(segs)

        def _paint_edges(self, painter, c, vp, cam, active, w, h) -> None:
            """The focused PDF's own spokes — CRISP LINES since K-174.

            Pouya, pointing at the beams K-158 shipped: "for all the
            node connections with everything else, I don't like the
            blurry stuff." So the particle trails are gone and these
            are single non-antialiased 1px segments, batched into ONE
            ``drawLines``.

            K-158 chose particles over strokes on a measurement that
            still stands and that this replaces rather than
            contradicts: what it measured was an ANTIALIASED TWO-PASS
            GLOWING stroke (6.35 ms for 90, rising to 10.55 as zoom
            lengthens them, 39.8 ms for one PDF's full 2,087). The cost
            was the AA rasterizer, whose price is the stroke's
            device-space area — never the composition mode (Plus 18.08
            vs SourceOver 18.74 on the same strokes) and never the call
            count (per-edge drawLine and batched drawLines measure the
            same, 0.154 vs 0.153 ms at 260). One hard pass with AA off
            is 0.092 ms for the same 90 spokes, and 2.51 ms for all
            2,087 — so the budget stopped being the constraint here.

            The subset does not change: ``links_for`` draws to the
            SAMPLED notes only, and that is a correctness rule rather
            than a cost one — a spoke ending on a dot nobody drew is a
            line into empty space.

            They leave the node's RIM, not its centre: lines converging
            on one point swallow the node they are supposed to be
            about. Straight, not bowed — a curve was the beams'
            apology for being blurry.
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
            hot = star_colour(c, 1.0)
            steps = max(1, int(EDGE_TAPER))
            runs: list = [[] for _ in range(steps)]
            for nxyz in beam:
                bx, by, _bd = project_point(vp, cam, *nxyz)
                dx = bx - ax
                dy = by - ay
                span = math.hypot(dx, dy)
                if span <= gap:
                    continue  # a note inside the node's own rim
                sx = ax + dx / span * gap
                sy = ay + dy / span * gap
                rx = bx - sx
                ry = by - sy
                for t in range(steps):
                    t0 = t / steps
                    t1 = (t + 1.0) / steps
                    runs[t].append(QLineF(sx + rx * t0, sy + ry * t0,
                                          sx + rx * t1, sy + ry * t1))
            for t, segs in enumerate(runs):
                if not segs:
                    continue
                painter.setPen(QPen(QColor(blend_hex(
                    c["bg"], hot, edge_mix(t, steps))), 1.0))
                painter.drawLines(segs)


        def _paint_nodes(self, painter, c, vp, cam, active, w, h) -> list:
            """PDF nodes: ring and lit core — crisp, no halo (Pouya: "I
            don't like the general glow") — never the flat filled disc
            K-148 drew. Farthest first, for the same reason the bands
            are ordered: a near node has to occlude a far one or the
            depth the fog established comes apart.

            ONE of them is lit. The rest are GHOSTS — a faint ring and
            nothing else (K-158, Pouya: "only one PDF shows at a time,
            potentially"). That is not only taste: PDF nodes sit at the
            CENTROID of their matched notes (K-058), so files whose
            matches overlap have nearly the same position, and four lit
            rings land in a heap. Focusing one makes the pile-up stop
            mattering instead of asking the layout to solve it.

            Returns the drawn nodes (near-last) so the label pass can
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
                # Off-screen cull margin: with the halo gone, the widest
                # thing ever painted from centre is the SELECTED node's
                # ring at r + NODE_SELECT_GAP (a ghost's outer ring, at
                # r * GHOST_HALO_F < r, is always inside that).
                margin = r + NODE_SELECT_GAP
                if (
                    sx < -margin
                    or sx > w + margin
                    or sy < -margin
                    or sy > h + margin
                ):
                    continue
                pt = QPointF(sx, sy)
                # EVERY node but the focused one is a ghost — including
                # all of them when nothing is focused, which is what
                # keeps the whole-cloud view from being four overlapping
                # lit rings arguing about which is which.
                if safe != active:
                    # Ghosts dim and light with the whole field (K-188) —
                    # only the SELECTED node below is exempt.
                    gr = r * GHOST_HALO_F
                    ring = QColor(c["blue_bright"])
                    ring.setAlphaF(GHOST_ALPHA * self._lit)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(ring, 1.0))
                    painter.drawEllipse(pt, gr, gr)
                    dot = QColor(c["blue_bright"])
                    dot.setAlphaF(min(1.0, GHOST_ALPHA * 1.8 * self._lit))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(dot)
                    painter.drawEllipse(pt, gr * NODE_CORE_F, gr * NODE_CORE_F)
                    continue
                # The active (hovered-or-selected) node's ring/core dim
                # with the field too — UNLESS it is the sticky selection,
                # which is exempt (K-188, Pouya: "just for that one, to
                # light up"): the same chosen/preview split as the name
                # in _paint_label below.
                node_lit = 1.0 if safe == self._selected else self._lit
                ring = QColor(c["blue_bright"])
                ring.setAlphaF(node_lit)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(ring, NODE_RING_W))
                painter.drawEllipse(pt, r, r)
                painter.setPen(Qt.PenStyle.NoPen)
                core = QColor(blend_hex(c["blue_bright"], c["text"],
                                        NODE_CORE_MIX))
                core.setAlphaF(node_lit)
                painter.setBrush(core)
                painter.drawEllipse(pt, r * NODE_CORE_F, r * NODE_CORE_F)
                if safe == self._selected:
                    sel_ring = QColor(c["blue_bright"])
                    sel_ring.setAlphaF(0.7)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(sel_ring, 1.0))
                    painter.drawEllipse(pt, r + NODE_SELECT_GAP,
                                        r + NODE_SELECT_GAP)
            return out

        def _paint_label(self, painter, c, drawn, active, w, h) -> None:
            """Exactly ONE name, the focused node's, drawn bare: bright
            when chosen, muted while only hovered.
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
                # The chosen PDF's name is exempt from dimming (K-188),
                # exactly like its ring/core above; a hover-only preview
                # dims and lights with the rest of the field.
                lit_name = active is not None and active == self._selected
                if lit_name:
                    painter.setPen(QColor(c["text"]))
                else:
                    muted = QColor(c["text_muted"])
                    muted.setAlphaF(self._lit)
                    painter.setPen(muted)
                painter.drawText(QPointF(lx, ly), lines[0])
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
            """Hovering a node FOCUSES it for the frame — the name the
            canvas draws beside it is the whole affordance now. No
            QToolTip: a native popup at the global cursor and an
            on-canvas label beside the node were two boxes fighting for
            one corner.
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

        def enterEvent(self, event) -> None:  # noqa: N802
            try:
                self.set_lit_target(1.0)
            except Exception:
                pass
            try:
                super().enterEvent(event)
            except Exception:
                pass

        def leaveEvent(self, event) -> None:  # noqa: N802
            try:
                if self._hover is not None:
                    self._hover = None
                    self.update()
                self.set_lit_target(DIM_LIT)
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
            """Back to the whole cloud: no PDF lit, no name drawn, the
            graph framed as it opens. Escape's binding."""
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
                # dialog_qss styles the children (labels, buttons; its
                # own labels are `background: transparent`) — the one
                # extra rule paints this non-QDialog window's own ground
                # on `chrome`, the SAME token the canvas paints (see
                # `_paint` below), so the window and its canvas read as
                # one surface rather than a box-in-a-box (final review
                # I1, 2026-09-02: this rule painted `bg` here while
                # K-185 had already moved the canvas on to `chrome` for
                # the Library's sake, so only the standalone window kept
                # the "separate box" Pouya asked to lose).
                self.setStyleSheet(
                    theme.dialog_qss(night)
                    + f"\nQWidget#KlausMapWindow {{ background-color: {c['chrome']}; }}"
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
            # THIS window is where the scene sways. The Library's dock
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
