"""Tests for klausmate/pdf_map.py — the embedding map window (K-123).

Pure viewport model first (transform round-trips, fit-to-view centering,
the zoom-at-cursor fixed-point invariant, hit-testing, node sizing, the
edge-subset policy, label placement, the off-view recentre rule, tooltip
text), then the glue pins on the SOURCE: the "aqt glue" divider with
nothing aqt above it, the K-114 exec() ban (and the no-focus-steal
rule), the K-115 paintEvent try/finally painter.end() guard, no literal
hex colours, WA_DeleteOnClose + the closeEvent singleton clear, and the
open_map_window / select_pdf public surface. Then stub-harness smoke
(empty-graph window, singleton fronting, the fake-graph canvas path),
and finally a REAL offscreen-PyQt6 section.

Why the last section exists: the permissive _Dummy stubs have no
geometry and paint no pixels, so the two things K-138 is actually about
— that every note reaches the note layer, and that a PDF's name appears
only while its circle is active — cannot be asserted under them. Real Qt
can, by counting ink. Because open_map_window imports aqt.qt lazily
inside itself, swapping sys.modules["aqt.qt"] is the entire bootstrap
(test_drive.py's precedent), and the section SKIPs honestly if PyQt6 is
missing.

Run: python3 tests/test_pdf_map.py
"""
from __future__ import annotations

import ast
import importlib
import inspect
import io
import math
import os
import random
import re
import shutil
import sys
import tempfile
import time
import tokenize
import types

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import ADDON, check, code_only, install, report, section  # noqa: E402

install()

pdf_map = importlib.import_module("klausmate.pdf_map")
Viewport = pdf_map.Viewport

_SRC = open(os.path.join(ADDON, "pdf_map.py")).read()
_CODE = code_only(_SRC)  # comments AND strings stripped — real code only
_TREE = ast.parse(_SRC)


def _strip_comments(src: str) -> str:
    """Comments removed, STRINGS KEPT — the hex pin must still see a
    colour literal smuggled in as a string value."""
    try:
        kept = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type != tokenize.COMMENT
        ]
        return tokenize.untokenize(kept)
    except Exception:
        return src  # unstrippable -> scan raw (stricter, never laxer)


def _func_seg(name: str) -> str:
    """Source segment of the (unique) function/method ``name``."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(_SRC, node) or ""
    return ""


def _method_seg(cls_name: str, name: str) -> str:
    """Source of ``cls_name.name`` — needed because the canvas and the
    window both define ``__init__`` inside ``open_map_window``, and a
    bare name lookup would silently pick whichever ast.walk reaches
    first."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return ast.get_source_segment(_SRC, sub) or ""
    return ""


def _calls_in(fn_name: str, callee: str) -> list:
    """Every plain-name Call to ``callee`` inside the function
    ``fn_name`` — argument counts, not just "the name appears"."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            return [
                c
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == callee
            ]
    return []


# ------------------------------------------------------------- transform

section("viewport transform — world<->screen round-trips")

_VPS = [
    Viewport(1.0, 0.0, 0.0),
    Viewport(3.7, -120.5, 44.25),
    Viewport(260.0, 400.0, 300.0),
    Viewport(0.05, 9999.0, -9999.0),
]
_PTS = [(0.0, 0.0), (1.0, 1.0), (-1.0, 0.5), (0.123456789, -0.987654321)]
ok = True
for vp in _VPS:
    for wx, wy in _PTS:
        sx, sy = pdf_map.world_to_screen(vp, wx, wy)
        rx, ry = pdf_map.screen_to_world(vp, sx, sy)
        if abs(rx - wx) > 1e-9 or abs(ry - wy) > 1e-9:
            ok = False
check("world->screen->world round-trips to 1e-9 across zooms and pans", ok)
check("screen_to_world guards a degenerate zero scale",
      pdf_map.screen_to_world(Viewport(0.0, 5.0, 5.0), 50.0, 50.0) == (0.0, 0.0))

sx0, sy0 = pdf_map.world_to_screen(_VPS[2], 0.25, 0.5)
vp_p = pdf_map.pan_by(_VPS[2], 10.0, -5.0)
sx1, sy1 = pdf_map.world_to_screen(vp_p, 0.25, 0.5)
check("pan_by shifts every screen position by exactly the delta",
      abs(sx1 - sx0 - 10.0) < 1e-9 and abs(sy1 - sy0 + 5.0) < 1e-9)

# ---------------------------------------------------------- fit_to_view

section("fit_to_view — centering, margin, degenerate bounds")

vp = pdf_map.fit_to_view((-1.0, -1.0, 1.0, 1.0), (800.0, 600.0), 40.0)
check("fit scale is the constraining axis's (600-80)/2 = 260",
      abs(vp.scale - 260.0) < 1e-9)
cx, cy = pdf_map.world_to_screen(vp, 0.0, 0.0)
check("world center lands on the widget center",
      abs(cx - 400.0) < 1e-9 and abs(cy - 300.0) < 1e-9)
x_lo, y_lo = pdf_map.world_to_screen(vp, -1.0, -1.0)
x_hi, y_hi = pdf_map.world_to_screen(vp, 1.0, 1.0)
check("constraining axis touches exactly the margin",
      abs(y_lo - 40.0) < 1e-9 and abs(y_hi - 560.0) < 1e-9)
check("non-constraining axis stays centered inside its margin",
      abs((x_lo + x_hi) / 2.0 - 400.0) < 1e-9 and x_lo >= 40.0 - 1e-9)

vp_d = pdf_map.fit_to_view((0.3, 0.3, 0.3, 0.3), (800.0, 600.0), 40.0)
check("zero-span bounds (a single node) still fit: positive scale, centered",
      vp_d.scale > 0
      and abs(pdf_map.world_to_screen(vp_d, 0.3, 0.3)[0] - 400.0) < 1e-9
      and abs(pdf_map.world_to_screen(vp_d, 0.3, 0.3)[1] - 300.0) < 1e-9)
_FLAT_BOUNDS = (-1.0, -1.0, 1.0, 1.0)  # the 2D box fit_to_view frames
vp_t = pdf_map.fit_to_view(_FLAT_BOUNDS, (10.0, 10.0), 48.0)
check("a widget smaller than the margins still yields a positive scale",
      vp_t.scale > 0)

# ---- K-143: the margin has to scale with a compact canvas ----
# Found by rendering the Library dock, not by reading the code: 48px a
# side is breathing room in a 900x640 window and half the box in a
# 545x185 dock, which fit the whole graph into the 89px left over.
_M = pdf_map.FIT_MARGIN
check("a roomy canvas keeps the full FIT_MARGIN — every surface that "
      "existed before the dock fits EXACTLY as it did",
      pdf_map.fit_margin((860.0, 560.0)) == _M
      and pdf_map.fit_margin((400.0, 400.0)) == _M)
_dock = pdf_map.fit_margin((545.0, 185.0))
check("the dock's compact box caps it at a share of the SMALLER axis "
      "instead — the constraining axis is the only one fit_to_view's "
      "single scale can ever consult",
      _dock == pdf_map.FIT_MARGIN_SHARE * 185.0 and _dock < _M / 2.0,
      f"margin {_dock} in a 545x185 box")
_s_capped = pdf_map.fit_to_view(
    _FLAT_BOUNDS, (545.0, 185.0), _dock).scale
_s_full = pdf_map.fit_to_view(
    _FLAT_BOUNDS, (545.0, 185.0), _M).scale
check("...and that is worth doing: the dock fits half again as large "
      "with the capped margin (70.3 px/unit vs 44.5)",
      _s_capped > 1.5 * _s_full, f"{_s_capped:.1f} vs {_s_full:.1f}")
check("a canvas with no surface yet, or junk for a size, falls back to "
      "the constant rather than to a zero margin",
      pdf_map.fit_margin((0.0, 0.0)) == _M
      and pdf_map.fit_margin((float("nan"), 300.0)) == _M
      and pdf_map.fit_margin(("x", None)) == _M
      and pdf_map.fit_margin(()) == _M)

# -------------------------------------------------------------- zoom_at

section("zoom_at — the anchor world-point stays fixed (1e-9)")

vp = pdf_map.fit_to_view((-1.0, -1.0, 1.0, 1.0), (800.0, 600.0), 40.0)
cursor = (123.4, 456.7)
ok = True
for factor in (1.6, 0.25, 3.0, 1.0):
    before = pdf_map.screen_to_world(vp, *cursor)
    vp2 = pdf_map.zoom_at(vp, cursor, factor)
    after = pdf_map.screen_to_world(vp2, *cursor)
    if abs(after[0] - before[0]) > 1e-9 or abs(after[1] - before[1]) > 1e-9:
        ok = False
    if abs(vp2.scale - vp.scale * factor) > 1e-9 * max(1.0, vp.scale * factor):
        ok = False
check("single zooms keep the cursor's world point fixed and scale exactly", ok)

vp_c = pdf_map.zoom_at(pdf_map.zoom_at(vp, cursor, 1.5), cursor, 1.5)
w_c = pdf_map.screen_to_world(vp_c, *cursor)
w_0 = pdf_map.screen_to_world(vp, *cursor)
check("chained zooms at one cursor compound without drifting the anchor",
      abs(w_c[0] - w_0[0]) < 1e-9 and abs(w_c[1] - w_0[1]) < 1e-9
      and abs(vp_c.scale - vp.scale * 2.25) < 1e-6)

before = pdf_map.screen_to_world(vp, *cursor)
vp_max = pdf_map.zoom_at(vp, cursor, 1e12)
after = pdf_map.screen_to_world(vp_max, *cursor)
check("zoom clamps at MAX_SCALE and the anchor STILL holds",
      vp_max.scale == pdf_map.MAX_SCALE
      and abs(after[0] - before[0]) < 1e-9
      and abs(after[1] - before[1]) < 1e-9)
vp_min = pdf_map.zoom_at(Viewport(pdf_map.MIN_SCALE, 5.0, 6.0), (0.0, 0.0), 0.5)
check("zoom-out at MIN_SCALE is a no-op (ratio 1.0 — offsets untouched)",
      vp_min.scale == pdf_map.MIN_SCALE
      and vp_min.ox == 5.0 and vp_min.oy == 6.0)

# ------------------------------------------------------------- hit_test

section("hit_test — nearest, none, radius edge, junk")

nodes = [("a", 100.0, 100.0), ("b", 130.0, 100.0)]
check("nearest within radius wins",
      pdf_map.hit_test(nodes, (110.0, 100.0), 50.0) == "a")
check("outside every radius -> None",
      pdf_map.hit_test(nodes, (300.0, 300.0), 5.0) is None)
check("radius edge is INCLUSIVE (3-4-5 exactly on the rim)",
      pdf_map.hit_test([("a", 3.0, 4.0)], (0.0, 0.0), 5.0) == "a")
check("just inside the rim misses at r-epsilon",
      pdf_map.hit_test([("a", 3.0, 4.0)], (0.0, 0.0), 4.999) is None)
check("exact ties keep the first-seen node",
      pdf_map.hit_test([("a", 10.0, 0.0), ("b", -10.0, 0.0)],
                       (0.0, 0.0), 20.0) == "a")
check("empty node list -> None", pdf_map.hit_test([], (0.0, 0.0), 10.0) is None)
check("junk point / negative radius -> None, junk nodes skipped",
      pdf_map.hit_test(nodes, ("x", None), 10.0) is None
      and pdf_map.hit_test(nodes, (0.0, 0.0), -1.0) is None
      and pdf_map.hit_test([("x", "junk", 0.0), ("a", 1.0, 1.0)],
                           (0.0, 0.0), 5.0) == "a")

# ---------------------------------------------------------- node_radius

section("node_radius — sqrt growth with sane clamps")

check("zero / negative / junk / NaN counts all floor at NODE_R_MIN",
      pdf_map.node_radius(0) == pdf_map.NODE_R_MIN
      and pdf_map.node_radius(-3) == pdf_map.NODE_R_MIN
      and pdf_map.node_radius(None) == pdf_map.NODE_R_MIN
      and pdf_map.node_radius("junk") == pdf_map.NODE_R_MIN
      and pdf_map.node_radius(float("nan")) == pdf_map.NODE_R_MIN)
check("radius grows monotonically with match_count",
      pdf_map.node_radius(4) < pdf_map.node_radius(100))
check("sqrt law: 4 matches = MIN + 2*SPREAD",
      abs(pdf_map.node_radius(4)
          - (pdf_map.NODE_R_MIN + 2.0 * pdf_map.NODE_R_SPREAD)) < 1e-9)
check("a million-match monster clamps at NODE_R_MAX",
      pdf_map.node_radius(10 ** 9) == pdf_map.NODE_R_MAX)

# ------------------------------------------- edge subset / LOD / tooltip

section("edge subset, hover precedence, labels, tooltip")

_EDGES = [
    {"pdf": "a", "nid": 1, "score": 0.5},
    {"pdf": "b", "nid": 2, "score": 0.6},
    {"pdf": "a", "nid": 3, "score": 0.7},
    "not-a-dict",
]
check("pdf_note_ids: selection 'a' -> exactly its two notes, in graph "
      "order, junk rows skipped",
      pdf_map.pdf_note_ids(_EDGES, "a") == [1, 3])
check("...and a repeated nid is listed ONCE, so a stride over it is a "
      "stride over distinct points",
      pdf_map.pdf_note_ids(
          _EDGES + [{"pdf": "a", "nid": 1, "score": .9}], "a") == [1, 3])
_LINKED = {"a": [(0.0, 0.0, 0.0), (0.5, 0.1, -0.2)], "b": [(1.0, 1.0, 1.0)]}
check("links_for: the active PDF's own sampled notes are what draws",
      pdf_map.links_for(_LINKED, "a") == _LINKED["a"])
check("no selection / empty / unknown pdf -> no connections drawn",
      pdf_map.links_for(_LINKED, None) == []
      and pdf_map.links_for(_LINKED, "") == []
      and pdf_map.links_for(_LINKED, "zzz") == [])
check("K-158 retired edges_for_selection — the paint path draws to the "
      "SAMPLED notes now (2,087 glowing edges was 39.8 ms a frame, and "
      "an edge ending on a dot nobody drew is a line into nothing); a "
      "stale caller must fail loud rather than silently draw nothing",
      not hasattr(pdf_map, "edges_for_selection"))
check("hover previews over the sticky selection; falls back; both-None",
      pdf_map.active_pdf("h", "s") == "h"
      and pdf_map.active_pdf(None, "s") == "s"
      and pdf_map.active_pdf("h", None) == "h"
      and pdf_map.active_pdf(None, None) is None)
# K-138 retired the whole label level-of-detail policy. K-133 had made
# names always-on below a 12-node cap because the map opened anonymous;
# Pouya looked at that and asked for the opposite — a name only when its
# circle is hovered or selected. So labels_visible, LABEL_ZOOM and
# LABEL_MAX_NODES are gone, and with them K-133's four pins on their
# behaviour plus K-123's zoom-gate pin. What replaces them is a single
# rule with no dial to get wrong: active_pdf decides, above.
check("the label level-of-detail gate is GONE, not just bypassed — "
      "names follow the selection now, and a stale caller must fail loud",
      not hasattr(pdf_map, "labels_visible")
      and not hasattr(pdf_map, "LABEL_ZOOM")
      and not hasattr(pdf_map, "LABEL_MAX_NODES"))

# label placement: beside the node, never on it (K-133 — this half of
# K-133 survives, because the one name that IS drawn still has to clear
# its own node and mirror at the view edge)
check("a label clears its own node by radius + LABEL_GAP and rides the "
      "node's centre line",
      pdf_map.label_anchor(100.0, 50.0, 12.0)
      == (100.0 + 12.0 + pdf_map.LABEL_GAP, 50.0 + pdf_map.LABEL_BASELINE_DY))
check("the gap also clears the SELECTED node's ring (drawn at r + 3 with "
      "a 2px pen, so outer edge r + 4)",
      pdf_map.LABEL_GAP > 4.0)
check("a label that would run past the right edge mirrors to the left of "
      "its node — still off the node, still legible",
      pdf_map.label_anchor(590.0, 10.0, 8.0, 120.0, 640.0)
      == (590.0 - 8.0 - pdf_map.LABEL_GAP - 120.0, 10.0 + pdf_map.LABEL_BASELINE_DY))
check("it mirrors only when it must, and never past the LEFT edge — a "
      "name wider than the view keeps its head visible, not its tail",
      pdf_map.label_anchor(100.0, 0.0, 8.0, 120.0, 640.0)[0] == 117.0
      and pdf_map.label_anchor(30.0, 0.0, 8.0, 700.0, 640.0)[0] == 47.0)
check("no view width (or a degenerate one) = no mirror decision to make",
      pdf_map.label_anchor(600.0, 0.0, 8.0, 500.0)[0] == 617.0
      and pdf_map.label_anchor(600.0, 0.0, 8.0, 500.0, 0.0)[0] == 617.0)
check("junk coordinates degrade instead of raising mid-paint",
      pdf_map.label_anchor("x", None, "r")
      == (pdf_map.LABEL_GAP, pdf_map.LABEL_BASELINE_DY)
      and pdf_map.label_anchor(10.0, 0.0, float("nan"))[0]
      == 10.0 + pdf_map.LABEL_GAP)

# ---- recenter_for: the pure half of the select_pdf seam (K-138) ----

section("recenter_for — reveal an off-view node, leave an on-view one alone")

_VP = pdf_map.Viewport(200.0, 300.0, 240.0)  # world 0,0 at screen 300,240
_SIZE = (600.0, 480.0)
check("a node already comfortably on screen does not move the map at all",
      pdf_map.recenter_for(_VP, (0.0, 0.0), _SIZE) is _VP
      and pdf_map.recenter_for(_VP, (0.5, 0.5), _SIZE) is _VP)
_off = pdf_map.recenter_for(_VP, (5.0, -3.0), _SIZE)
check("an off-view node is centred exactly, and the ZOOM is untouched — "
      "a jump plus a scale change loses all sense of where the view went",
      _off.scale == _VP.scale
      and pdf_map.world_to_screen(_off, 5.0, -3.0) == (300.0, 240.0))
# 5px in from the left edge: inside the widget, but inside the margin.
_edge = pdf_map.screen_to_world(_VP, 5.0, 240.0)
check("the margin is a real inset: a node inside the view but within "
      "RECENTER_MARGIN of its edge still gets centred",
      pdf_map.recenter_for(_VP, _edge, _SIZE) is not _VP
      and 0.0 < pdf_map.RECENTER_MARGIN < 200.0)
check("a widget with no usable size yet centres rather than guessing",
      pdf_map.world_to_screen(
          pdf_map.recenter_for(_VP, (0.0, 0.0), (0.0, 0.0)), 0.0, 0.0)
      == (0.0, 0.0))
# Judged from a viewport where the ORIGIN is far off-view, so "returned
# unchanged" cannot be an accident of a junk point falling back to (0, 0)
# and happening to land on screen.
_VPFAR = pdf_map.Viewport(200.0, -5000.0, -5000.0)
check("a malformed world point leaves the viewport exactly as it was, "
      "rather than steering the map at some fallback coordinate",
      pdf_map.recenter_for(_VPFAR, "junk", _SIZE) is _VPFAR
      and pdf_map.recenter_for(_VPFAR, (float("nan"), 0.0), _SIZE) is _VPFAR
      and pdf_map.recenter_for(_VPFAR, (0.0,), _SIZE) is _VPFAR)

tip = pdf_map.node_lines({
    "display": "Lecture 1", "safe": "Lecture_1", "folder": "Anatomy/Week 2",
    "match_count": 37, "retention": 0.834,
})
check("the focused node's plate carries display, folder, matched NOTE "
      "count and known retention",
      tip == [
          "Lecture 1", "Folder: Anatomy/Week 2",
          "Matched notes: 37", "Retention: 83%",
      ])
check("unknown retention (headless None) is simply omitted",
      not any("Retention" in t for t in pdf_map.node_lines(
          {"display": "x", "match_count": 1, "retention": None})))
check("a bool can't cosplay as a retention score",
      not any("Retention" in t for t in pdf_map.node_lines(
          {"display": "x", "match_count": 1, "retention": True})))
check("no folder -> no Folder line; missing display falls back to safe",
      not any("Folder" in t for t in
              pdf_map.node_lines({"display": "x", "match_count": 0}))
      and pdf_map.node_lines({"safe": "S_1"})[0] == "S_1")
check("K-158: NOTHING in this view mentions cards — Pouya, 'forget about "
      "cards' — and the native QToolTip that fought the on-canvas plate "
      "for the same corner is gone with the name it carried",
      not any("card" in t.lower() for t in tip)
      and "card" not in pdf_map.HINT_TEXT.lower()
      and "card" not in pdf_map.caption_text(4, 28670, 640).lower()
      and not hasattr(pdf_map, "tooltip_text")
      and "QToolTip" not in _CODE)

# ----------------------------------------------------- bounds / parsing

section("parse_xyz, bounds_of, graph_bounds")

check("parse_xyz: lists, tuples, junk, short, NaN",
      pdf_map.parse_xyz([0.5, -0.25, 0.75]) == (0.5, -0.25, 0.75)
      and pdf_map.parse_xyz((1, 2, 3)) == (1.0, 2.0, 3.0)
      and pdf_map.parse_xyz("junk") is None
      and pdf_map.parse_xyz([1]) is None
      and pdf_map.parse_xyz([float("nan"), 0, 0]) is None
      and pdf_map.parse_xyz([0, 0, float("nan")]) is None
      and pdf_map.parse_xyz(None) is None)
check("a TWO-component row lands on the z=0 plane instead of being "
      "dropped — map_canvas is a public seam, the key held two numbers "
      "before K-148, and a graph one number short must render flat "
      "rather than render nothing",
      pdf_map.parse_xyz([0.5, -0.25]) == (0.5, -0.25, 0.0)
      and pdf_map.row_xyz({"xy": [1, 2]}) == (1.0, 2.0, 0.0)
      and pdf_map.row_xyz({"xyz": [1, 2, 3]}) == (1.0, 2.0, 3.0)
      and pdf_map.row_xyz("not a row") is None)
check("bounds_of: 3D box, junk points skipped, empty -> DEFAULT_BOUNDS",
      pdf_map.bounds_of([(0, 0, 0), (2, 3, -4), (-1, 1, 1)])
      == (-1.0, 0.0, -4.0, 2.0, 3.0, 1.0)
      and pdf_map.bounds_of([("j", 1, 0), (2, 2, 2)])
      == (2.0, 2.0, 2.0, 2.0, 2.0, 2.0)
      and pdf_map.bounds_of([]) == pdf_map.DEFAULT_BOUNDS)
check("graph_bounds spans notes AND pdf nodes on all three axes; empty "
      "graph falls back",
      pdf_map.graph_bounds({
          "notes": [{"nid": 1, "xyz": [0, 0, -1]}],
          "pdfs": [{"safe": "a", "xyz": [2, 2, 0.5]}], "edges": [],
      }) == (0.0, 0.0, -1.0, 2.0, 2.0, 0.5)
      and pdf_map.graph_bounds({}) == pdf_map.DEFAULT_BOUNDS)

# ------------------------------------------------- end-to-end pure pipe

section("end-to-end: fake graph -> fit -> hit -> zoom -> hit")

FAKE = {
    "pdfs": [
        {"safe": "lec1", "display": "Lecture 1", "folder": None,
         "threshold": 0.4, "retention": None, "xyz": [-0.5, -0.2, 0.3],
         "match_count": 2},
        {"safe": "lec2", "display": "Lecture 2", "folder": "F",
         "threshold": 0.4, "retention": 0.9, "xyz": [0.6, 0.4, -0.7],
         "match_count": 1},
    ],
    "notes": [
        {"nid": 1, "xyz": [-0.6, -0.1, 0.5]},
        {"nid": 2, "xyz": [-0.4, -0.3, 0.1]},
        {"nid": 3, "xyz": [0.6, 0.4, -0.7]},
    ],
    "edges": [
        {"pdf": "lec1", "nid": 1, "score": 0.8},
        {"pdf": "lec1", "nid": 2, "score": 0.5},
        {"pdf": "lec2", "nid": 3, "score": 0.9},
    ],
}
CAM = pdf_map.Camera()
b = pdf_map.graph_bounds(FAKE)
check("fake graph bounds, depth included",
      b == (-0.6, -0.3, -0.7, 0.6, 0.4, 0.5))
vp = pdf_map.frame_bounds(b, CAM, (640.0, 480.0))
hit_r = pdf_map.node_radius(2) + pdf_map.HIT_SLOP


def _nodes(viewport, cam=CAM):
    return [
        (p["safe"], *pdf_map.project_point(viewport, cam, *p["xyz"])[:2])
        for p in FAKE["pdfs"]
    ]


s1 = pdf_map.project_point(vp, CAM, -0.5, -0.2, 0.3)[:2]
check("hovering lec1's projected position hits lec1",
      pdf_map.hit_test(_nodes(vp), s1, hit_r) == "lec1")
c2 = pdf_map.project_point(vp, CAM, 0.6, 0.4, -0.7)[:2]
vp2 = pdf_map.zoom_at(pdf_map.zoom_at(vp, c2, 2.0), c2, 2.0)
check("after two anchored zooms lec2 is still under the cursor — the "
      "zoom anchor works on the CAMERA PLANE, so perspective and "
      "rotation ride under it untouched",
      pdf_map.hit_test(_nodes(vp2), c2, hit_r) == "lec2")
_frame = pdf_map.frame_bounds(b, CAM, (640.0, 480.0))
_us = [pdf_map.project_point(_frame, CAM, *n["xyz"])[:2]
       for n in FAKE["notes"]] + [
      pdf_map.project_point(_frame, CAM, *p["xyz"])[:2]
      for p in FAKE["pdfs"]]
check("frame_bounds frames the whole 3D cloud AT THIS POSE — every "
      "projected point lands inside the canvas, which the flat x/y box "
      "cannot promise once perspective magnifies the near face",
      all(0 <= x <= 640 and 0 <= y <= 480 for x, y in _us),
      str([(round(x), round(y)) for x, y in _us]))
check("its edge subset is exactly nid 3",
      pdf_map.pdf_note_ids(FAKE["edges"], "lec2") == [3])

# --------------------------------------------------- K-148: the camera

section("K-148 camera — projection, depth bands, fog, flight")

_C0 = pdf_map.Camera(0.0)
check("at yaw 0 on the z=0 plane the camera is the IDENTITY — the flat "
      "map is a POSE of the 3D one, not a separate code path, which is "
      "why every fit/zoom/hit rule above still holds unchanged",
      pdf_map.camera_point(_C0, 0.5, -0.25, 0.0) == (0.5, -0.25, 1.0))
_near = pdf_map.camera_point(_C0, 0.5, 0.5, 0.6)
_far = pdf_map.camera_point(_C0, 0.5, 0.5, -0.6)
check("perspective: a nearer point magnifies away from the axis, a "
      "farther one shrinks toward it, and depth reports the factor",
      _near[2] > 1.0 > _far[2]
      and _near[0] > 0.5 > _far[0]
      and abs(_near[0] - 0.5 * _near[2]) < 1e-12,
      f"near={_near} far={_far}")
_axis = pdf_map.camera_point(pdf_map.Camera(0.9), 0.0, 0.4, 0.0)
check("the rotation axis is vertical and through the origin: a point on "
      "it never moves however far the scene turns",
      abs(_axis[0]) < 1e-12 and abs(_axis[1] - 0.4) < 1e-12)
_spun = [pdf_map.camera_point(pdf_map.Camera(a), 1.0, 0.0, 0.0)[0]
         for a in (0.0, 0.4, 0.8, 1.2)]
check("...and turning the camera really does move a point that is NOT "
      "on it (the sway would otherwise be a very expensive still)",
      len(set(round(v, 9) for v in _spun)) == 4, str(_spun))
check("a junk coordinate cannot drive the divisor to zero — the paint "
      "path never raises on one malformed row",
      pdf_map.camera_point(_C0, 0.0, 0.0, 1e9)[2] > 0
      and pdf_map.camera_point(pdf_map.Camera(1.5), -1e9, 0.0, 0.0)[2] > 0)

check("band_index partitions [-1, 1] and clamps outside it rather than "
      "wrapping (a wrap would file the nearest point at the back)",
      pdf_map.band_index(-1.0) == 0
      and pdf_map.band_index(1.0) == pdf_map.DEPTH_BANDS - 1
      and pdf_map.band_index(-99.0) == 0
      and pdf_map.band_index(99.0) == pdf_map.DEPTH_BANDS - 1
      and pdf_map.band_index(0.0) == pdf_map.DEPTH_BANDS // 2)
_worst = max(abs(z - pdf_map.band_z(pdf_map.band_index(z)))
             for z in [k / 500.0 - 1.0 for k in range(1001)])
check("a band draws at its CENTRE, so the depth error is symmetric and "
      "bounded by 1/DEPTH_BANDS — the whole reason the count is 256 and "
      "not 64 (the on-screen error is scale*|sin0|*that)",
      _worst <= 1.0 / pdf_map.DEPTH_BANDS + 1e-12,
      f"worst |z - band_z| = {_worst:.6f}")
check("bands paint FAR first, and which end is far FLIPS with the sign "
      "of cos(angle) — without that the cloud turns inside out every "
      "time the rotation crosses the quarter turn",
      list(pdf_map.band_order(pdf_map.Camera(0.0), 4)) == [3, 2, 1, 0]
      and list(pdf_map.band_order(pdf_map.Camera(math.pi), 4)) == [0, 1, 2, 3])

_uniform = pdf_map.fog_shades([10] * 8)
check("fog_shades rises monotonically and stays inside "
      "[FOG_FAR, FOG_NEAR]",
      _uniform == sorted(_uniform)
      and _uniform[0] >= pdf_map.FOG_FAR - 1e-9
      and _uniform[-1] <= pdf_map.FOG_NEAR + 1e-9)
# The finding this exists for, reproduced in miniature: a Gaussian-ish
# cloud (which is what a PCA score IS) with its range stretched to the
# outliers. Spending the ramp on z would give four notes in five almost
# the same shade; spending it on the POPULATION does not.
_gauss = [1, 2, 6, 40, 300, 900, 300, 40, 6, 2, 1]
_eq = pdf_map.fog_shades(_gauss)
_bulk = _eq[4:7]  # the bands holding ~85% of the cloud
check("...and it spends the ramp where the notes actually are: on a "
      "Gaussian cloud the bulk gets most of the fog range, which a "
      "ramp keyed on z alone cannot do (rendered on the live index "
      "first — it came out one flat mid-grey)",
      _bulk[-1] - _bulk[0] > 0.45,
      f"bulk spans {_bulk[0]:.2f}..{_bulk[-1]:.2f} of "
      f"{_eq[0]:.2f}..{_eq[-1]:.2f}")
check("an empty or junk histogram cannot divide by zero mid-paint",
      pdf_map.fog_shades([]) == []
      and pdf_map.fog_shades([0, 0]) == [pdf_map.FOG_NEAR] * 2
      and len(pdf_map.fog_shades(["x", None, 4])) == 3)
check("blend_hex hits both endpoints exactly, mixes in between, and "
      "degrades to the near colour on junk rather than raising mid-paint",
      pdf_map.blend_hex("#000000", "#ffffff", 0.0) == "#000000"
      and pdf_map.blend_hex("#000000", "#ffffff", 1.0) == "#ffffff"
      and pdf_map.blend_hex("#000000", "#ffffff", 0.5) == "#808080"
      and pdf_map.blend_hex("nonsense", "#ffffff", 0.5) == "#ffffff")

# The claim camera_bounds rests on: camera_point is projective, so its
# extremes over a BOX are at the box's corners. If that were false the
# fit would clip the cloud, so test it against the inside of the box.
_cam_r = pdf_map.Camera(0.55)
_box = (-1.0, -0.8, -1.0, 1.0, 0.8, 1.0)
_cb = pdf_map.camera_bounds(_box, _cam_r)
_rr = random.Random(21)
_inside = True
for _ in range(4000):
    _u, _v, _ = pdf_map.camera_point(
        _cam_r, _rr.uniform(-1, 1), _rr.uniform(-0.8, 0.8), _rr.uniform(-1, 1))
    if not (_cb[0] - 1e-9 <= _u <= _cb[2] + 1e-9
            and _cb[1] - 1e-9 <= _v <= _cb[3] + 1e-9):
        _inside = False
        break
check("camera_bounds from the EIGHT CORNERS really does contain every "
      "point inside the box — 4,000 interior samples, none outside — "
      "which is what lets the fit be O(1) instead of O(28,668)",
      _inside, str(_cb))
check("...and it is tight, not merely safe: some corner attains each "
      "edge of it",
      any(abs(pdf_map.camera_point(_cam_r, x, y, z)[0] - _cb[0]) < 1e-9
          for x in (-1, 1) for y in (-0.8, 0.8) for z in (-1, 1)))

_a = pdf_map.Viewport(100.0, 40.0, 30.0)
_bv = pdf_map.Viewport(400.0, -900.0, -600.0)
_size = (800.0, 600.0)
check("a flight starts exactly where it was and ends exactly where it "
      "was going",
      pdf_map.lerp_viewport(_a, _bv, 0.0, _size) == _a
      and pdf_map.lerp_viewport(_a, _bv, 1.0, _size) == _bv)
_mid = pdf_map.lerp_viewport(_a, _bv, 0.5, _size)
check("zoom interpolates GEOMETRICALLY — halfway through is the "
      "geometric mean, not the arithmetic one, or the flight lurches "
      "and then crawls",
      abs(_mid.scale - math.sqrt(100.0 * 400.0)) < 1e-9,
      f"{_mid.scale} vs {math.sqrt(40000.0)}")
_wa = pdf_map.screen_to_world(_a, 400.0, 300.0)
_wb = pdf_map.screen_to_world(_bv, 400.0, 300.0)
_wm = pdf_map.screen_to_world(_mid, 400.0, 300.0)
check("...while the world point under the screen centre travels in a "
      "straight line, which is what makes it read as a camera move",
      abs(_wm[0] - (_wa[0] + _wb[0]) / 2.0) < 1e-9
      and abs(_wm[1] - (_wa[1] + _wb[1]) / 2.0) < 1e-9)
check("t outside [0, 1] cannot throw the camera past its endpoints",
      pdf_map.lerp_viewport(_a, _bv, -5.0, _size) == _a
      and pdf_map.lerp_viewport(_a, _bv, 9.0, _size) == _bv)

# --------------------------------------- K-158: the sample and the focus

section("K-158 — the sample, the caption, the focus, the clamp")

# Sampling. Pouya, after seeing all 28,668 drawn: "it doesn't have to
# show all the notes... it just has to give an idea, a mental conception
# of what the embedding is."
check("an even STRIDE, not a head or a random draw — the whole point is "
      "that a thinned cloud still has the shape of the real one",
      pdf_map.sample_indices(10, 3) == [0, 3, 6]
      and pdf_map.sample_indices(100, 4) == [0, 25, 50, 75])
check("the stride SPANS the sequence: the last index sits in the final "
      "stride, so the far end of the cloud is represented too",
      pdf_map.sample_indices(1000, 10)[-1] >= 900
      and pdf_map.sample_indices(28670, 420)[-1] >= 28600)
check("indices are strictly increasing and never repeat, at every cap "
      "from 1 to the sequence length",
      all(pdf_map.sample_indices(97, k)
          == sorted(set(pdf_map.sample_indices(97, k)))
          and len(pdf_map.sample_indices(97, k)) == k
          for k in range(1, 98)))
check("cap 0 (and any cap past the end) is EVERY index — K-138's "
      "draw-everything path stays reachable behind the constant, "
      "because 'how many is legible' is a tuning question",
      pdf_map.sample_indices(7, 0) == list(range(7))
      and pdf_map.sample_indices(7, 99) == list(range(7))
      and pdf_map.sample_indices(0, 5) == []
      and pdf_map.sample_indices("junk", 5) == [])

_SG = {
    "pdfs": [{"safe": "a", "match_count": 6}, {"safe": "b", "match_count": 2}],
    "notes": [{"nid": i, "xyz": [i / 50.0, 0.0, 0.0]} for i in range(100)]
             + [{"nid": 900, "xyz": "junk"}],
    # nid 50 and 51 are matched by BOTH, which is what makes "shown"
    # a question about distinct notes rather than a sum of link sets.
    "edges": [{"pdf": "a", "nid": i, "score": .9} for i in range(0, 12)]
             + [{"pdf": "a", "nid": i, "score": .9} for i in range(50, 52)]
             + [{"pdf": "b", "nid": i, "score": .9} for i in range(50, 52)],
}
_amb, _link, _pos, _tot, _shown = pdf_map.split_cloud(_SG, cap=20, per_pdf=4)
check("split_cloud: the ambient field is capped, each PDF's own notes "
      "are sampled separately, and the two never overlap — a PDF's "
      "connections have to land on dots that are actually drawn",
      len(_amb) == 20 and len(_link["a"]) == 4 and len(_link["b"]) == 2
      and not (set(_amb) & (set(_link["a"]) | set(_link["b"]))))
check("...while POSITIONS keep every note the graph positioned, sample "
      "or no sample: an edge endpoint and the flight's framing are "
      "about the real match set, not about what was drawn",
      len(_pos) == 100 and _tot == 100 and 900 not in _pos)
_amb2, _link2, _pos2, _tot2, _shown2 = pdf_map.split_cloud(
    _SG, cap=20, per_pdf=0)
check("...and 'shown' counts DISTINCT notes, so a note two PDFs both "
      "matched is one note in the caption even though it is blitted "
      "twice (per_pdf 0 here, so both PDFs keep the two they share)",
      set(_link2["a"]) & set(_link2["b"])
      and _shown2 == len(_amb2) + len({*_link2["a"], *_link2["b"]})
      and _shown2 < len(_amb2) + len(_link2["a"]) + len(_link2["b"]))
check("an unpositioned row is dropped rather than crashing the sample",
      pdf_map.row_nid({"nid": "7"}) == 7
      and pdf_map.row_nid({"nid": "x"}) is None
      and pdf_map.row_nid("junk") is None)

check("the caption says the REAL total and what is showing — a view "
      "that quietly drew a fraction while naming the whole would be "
      "lying about the data",
      pdf_map.caption_text(4, 28670, 643)
      == "4 PDFs · 28670 notes · showing 643")
check("...and drops the clause when nothing was left out, rather than "
      "saying 'showing 50' of 50",
      pdf_map.caption_text(1, 50, 50) == "1 PDF · 50 notes"
      and pdf_map.caption_text(1, 50, 0) == "1 PDF · 50 notes")

# The flight's frame. Trimming exists because semantic matches are not
# a tidy blob: measured on the real library, framing every match zoomed
# the biggest PDF by exactly 1.00x.
_TP = [(0.0, 0.0, 0.0)] * 8 + [(9.0, 9.0, 9.0), (-9.0, -9.0, -9.0)]
check("trimmed_bounds ignores the extreme share per axis per end, so a "
      "couple of far-flung matches cannot defeat the zoom",
      pdf_map.trimmed_bounds(_TP, 0.0) == (-9.0, -9.0, -9.0, 9.0, 9.0, 9.0)
      and pdf_map.trimmed_bounds(_TP, 0.1) == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
check("...per AXIS, not per point: a note wild on x but ordinary on y "
      "must not shrink the frame twice",
      pdf_map.trimmed_bounds(
          [(-9.0, 5.0, 0.0), (0.0, 1.0, 0.0), (0.0, 2.0, 0.0),
           (0.0, 3.0, 0.0), (0.5, 4.0, 0.0)], 0.2)
      == (0.0, 2.0, 0.0, 0.0, 4.0, 0.0))
check("it never trims itself empty: a trim that would meet in the "
      "middle is dropped, so three points still return their real box "
      "rather than one collapsed to the median",
      pdf_map.trimmed_bounds(
          [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 2.0, 2.0)], 0.4)
      == (0.0, 0.0, 0.0, 2.0, 2.0, 2.0)
      and pdf_map.trimmed_bounds([(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)], 0.45)
      == (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
      and pdf_map.trimmed_bounds([], 0.2) == pdf_map.DEFAULT_BOUNDS)

# The label clamp. label_anchor mirrors only when the mirrored side
# FITS; a clipped name has been reported three times in this module.
check("clamp_label pulls a plate back inside the canvas whatever the "
      "anchor chose — the last word on placement is a clamp, not "
      "another offset",
      pdf_map.clamp_label(1000.0, 200.0, 1100.0)
      == 1100.0 - 200.0 - pdf_map.LABEL_EDGE_PAD
      and pdf_map.clamp_label(-30.0, 200.0, 1100.0) == pdf_map.LABEL_EDGE_PAD
      and pdf_map.clamp_label(300.0, 200.0, 1100.0) == 300.0)
check("...and a plate wider than the whole canvas starts at the left "
      "edge rather than at a negative coordinate",
      pdf_map.clamp_label(500.0, 9000.0, 1100.0) == pdf_map.LABEL_EDGE_PAD
      and pdf_map.clamp_label(500.0, 100.0, 0.0) == 500.0)

# The focus. Pouya: "only one PDF shows at a time, potentially, and then
# it just zooms in on that section of the cloud that hosts that PDF."
_FP = [{"safe": "b", "match_count": 5}, {"safe": "a", "match_count": 40},
       {"safe": "c", "match_count": 5}, "junk", {"match_count": 9}]
check("focus_order is stable and most-matched first — 'next' has to "
      "mean the same thing every time you press it",
      pdf_map.focus_order(_FP) == ["a", "b", "c"]
      and pdf_map.focus_order([]) == [])
check("next_focus cycles both ways and wraps",
      pdf_map.next_focus(["a", "b", "c"], "a", 1) == "b"
      and pdf_map.next_focus(["a", "b", "c"], "c", 1) == "a"
      and pdf_map.next_focus(["a", "b", "c"], "a", -1) == "c")
check("...and entering from the whole-cloud view lands on a real PDF "
      "either way: forward at the front, back at the back",
      pdf_map.next_focus(["a", "b", "c"], None, 1) == "a"
      and pdf_map.next_focus(["a", "b", "c"], None, -1) == "c"
      and pdf_map.next_focus(["a", "b", "c"], "gone", 1) == "a"
      and pdf_map.next_focus([], "a", 1) is None)

# The tier ramp's own arithmetic (the colours are pinned on real Qt).
check("tier_index quantizes the fog ramp into STAR_TIERS steps and "
      "clamps rather than raising on the paint path",
      pdf_map.tier_index(0.0) == 0
      and pdf_map.tier_index(1.0) == pdf_map.STAR_TIERS - 1
      and pdf_map.tier_index(-5.0) == 0
      and pdf_map.tier_index(5.0) == pdf_map.STAR_TIERS - 1
      and pdf_map.tier_index("junk") == 0)
check("tier_position is each tier's MIDDLE, so neither end of the ramp "
      "is forced flat by an off-by-one",
      0.0 < pdf_map.tier_position(0) < pdf_map.tier_position(
          pdf_map.STAR_TIERS - 1) < 1.0)
check("dot_scale is 1.0 on any surface at or above DOT_SCALE_FULL and "
      "floors on a tiny one, never zero",
      pdf_map.dot_scale((900.0, 640.0)) == 1.0
      and pdf_map.dot_scale((545.0, 185.0)) == pdf_map.DOT_SCALE_FLOOR
      and pdf_map.dot_scale((0.0, 0.0)) == 1.0
      and pdf_map.dot_scale("junk") == 1.0)

# ------------------------------------- K-174: the constellation, in 3D

section("K-174 — hard points, crisp links, a slow full turn")

# Pouya, 2026-09-01, with aalampour.com open: "See how there's a
# constellation type of thing... That's what I want for the graph. I
# don't want these glowy things. I also want it to be 3D. I want each
# node on the graph to be just randomly interconnected... I like the
# shininess of the PDFs. I like that. For all the node connections with
# everything else, I don't like the blurry stuff. Just have it rotate
# slowly in 3D."
#
# The reference, measured off its own canvas (1262x818 device px for a
# 631x409 CSS box — a 2x canvas):
#   * at the star threshold the longest run of lit pixels in a row is
#     FOUR DEVICE px, i.e. 1-2 CSS px, and there is no tail of
#     mid-brightness pixels around it. A glow sprite cannot do that:
#     its falloff IS a long run of mid-brightness pixels.
#   * star blobs are 2 device px in area at the median and 23 at the
#     largest, so a handful of 3px points and a majority of 1px ones.
#   * lit pixels are 0.006% of the canvas at the star threshold and
#     0.077% counting the faintest — extremely sparse and very calm.
#   * they are NOT pure white on the glass. Zero pixels at the star
#     threshold read 255/255/255; they read 214/222/248 and 215/215/213
#     — a cool near-white, which is what the palette's own `text`
#     (#E0E0E0) over `bg` mixes to. So the design brief and the "no
#     invented colour" rule agree, which is lucky rather than clever.

_STARPAL = importlib.import_module("klausmate.theme").palette(True)


def _hexlum(h: str) -> int:
    h = h.lstrip("#")
    return sum(int(h[i:i + 2], 16) for i in (0, 2, 4))


check("the glow system is GONE by name — its tiers, its alphas, its "
      "sprite builder and its cache. These ARE 'these glowy things'",
      not any(hasattr(pdf_map, n) for n in (
          "GLOW_TIERS", "GLOW_CORE_ALPHA", "GLOW_HALO_ALPHA", "GLOW_RATIO",
          "NOTE_R_FAR", "NOTE_R_NEAR", "tier_colours", "tier_radius"))
      and "_glow_sprite" not in _CODE
      and "_ensure_sprites" not in _CODE
      and "drawPixmap" not in _CODE
      and "CompositionMode_Plus" not in _CODE)
check("...and so are the particle-trail beams — 'for all the node "
      "connections with everything else, I don't like the blurry stuff'",
      not any(hasattr(pdf_map, n) for n in (
          "BEAM_STEP", "BEAM_MAX", "BEAM_MIN_TIER", "EDGE_BOW")))

# Hardness and size. The one number that decides this look.
check("a star is a HARD point of 1 to 3 px — the reference's longest "
      "lit run is the whole brief, and 1-3px with no falloff is the "
      "only thing that produces it",
      pdf_map.STAR_SIZE_MIN == 1 and pdf_map.STAR_SIZE_MAX == 3
      and pdf_map.star_size(0.0) == 1 and pdf_map.star_size(1.0) == 3
      and all(1 <= pdf_map.star_size(i / 40.0) <= 3 for i in range(41)))
check("...the size ramp is monotonic in depth (size is half of how "
      "depth reads, now that nothing blurs)",
      [pdf_map.star_size(i / 20.0) for i in range(21)]
      == sorted(pdf_map.star_size(i / 20.0) for i in range(21)))
check("...and MOST of the ramp is small: the reference's median blob "
      "is 2 device px on a 2x canvas, so a field of 3px stars would be "
      "four times the ink it actually has",
      sum(1 for i in range(pdf_map.STAR_TIERS)
          if pdf_map.star_size(pdf_map.tier_position(i)) == 3)
      <= pdf_map.STAR_TIERS // 3)
check("a small canvas gets smaller stars and never a zero-px one — "
      "fit_margin's K-143 rule, one layer down",
      pdf_map.star_size(1.0, pdf_map.dot_scale((545.0, 185.0)))
      < pdf_map.STAR_SIZE_MAX
      and pdf_map.star_size(0.0, 0.01) == 1
      and pdf_map.star_size("junk") >= 1)

check("depth is BRIGHTNESS and SIZE, never alpha and never blur: "
      "K-148 measured alpha fog at 5x an opaque mix, and the reference "
      "gets its depth exactly this way",
      _hexlum(pdf_map.star_colour(_STARPAL, 1.0))
      > _hexlum(pdf_map.star_colour(_STARPAL, 0.0)) + 220
      and _hexlum(pdf_map.star_colour(_STARPAL, 1.0)) > 600)
check("...the near end lands on the palette's own near-white rather "
      "than on an invented 255/255/255 — which is also closer to what "
      "the reference's pixels actually measure (214/222/248)",
      pdf_map.star_colour(_STARPAL, 1.0).lower()
      == _STARPAL["text"].lower())
check("...and a focused PDF pushes the rest of the field back, so its "
      "own notes are not lost in everything else",
      _hexlum(pdf_map.star_colour(_STARPAL, 1.0, dim=True))
      < _hexlum(pdf_map.star_colour(_STARPAL, 1.0)))

# The constellation. Pouya: "each node on the graph to be just randomly
# interconnected... it looks kind of cool."
# 900 points, deliberately: at 240 the nearest-neighbour pass yields
# 137 pairs and the cap NEVER BITES, so the seeded shuffle is dead code
# and a mutation replacing it with an unseeded RNG survives the whole
# suite (found by mutating it). At 900 it yields 1,016 and the cap is
# load-bearing.
_CPTS = [(math.cos(i * 0.7) * 0.6, math.sin(i * 1.3) * 0.55,
          math.cos(i * 0.31) * 0.5) for i in range(900)]
_KNN = pdf_map.constellation_links(_CPTS)
check("the constellation is STABLE — the same collection draws the "
      "same figure every time it opens. Re-randomising per frame "
      "shimmers and reads as broken. Checked in BOTH modes and with "
      "the cap biting, which is the only path the RNG is on",
      _KNN and _KNN == pdf_map.constellation_links(list(_CPTS))
      and len(_KNN) == pdf_map.LINK_MAX
      and len(pdf_map.constellation_links(_CPTS, cap=10 ** 6)) > 900
      and pdf_map.constellation_links(_CPTS, mode="chord")
      == pdf_map.constellation_links(list(_CPTS), mode="chord"))
check("...and the cap really CAPS, at every size, in both modes — it "
      "is the frame budget and a topology that ignores it is a frame "
      "budget that ignores it too",
      all(len(pdf_map.constellation_links(_CPTS, mode=_m, cap=_c)) <= _c
          for _m in ("knn", "chord") for _c in (7, 50, 300, 900)))
check("...and the seed comes FROM THE GRAPH, so two collections do "
      "not inherit one another's constellation, and no process-random "
      "hash() is anywhere near it",
      pdf_map.link_seed(_CPTS) == pdf_map.link_seed(list(_CPTS))
      and pdf_map.link_seed(_CPTS) != pdf_map.link_seed(_CPTS[:200])
      and pdf_map.link_seed([]) == pdf_map.link_seed([]))
check("no self-links, no duplicate pairs, every index in range, and "
      "the count is capped — the cap is the frame budget",
      all(i != j and 0 <= i < len(_CPTS) and 0 <= j < len(_CPTS)
          for i, j in _KNN)
      and len({tuple(sorted(p)) for p in _KNN}) == len(_KNN)
      and len(_KNN) <= pdf_map.LINK_MAX)


def _span(pts, links):
    d = sorted(math.dist(pts[i], pts[j]) for i, j in links)
    return d[len(d) // 2] if d else 0.0


_CHORD = pdf_map.constellation_links(_CPTS, mode="chord")
check("the two topologies are genuinely different pictures: "
      "nearest-neighbour links span a fraction of what uniform random "
      "chords do. Both were rendered; the short-span one is the one "
      "that reads as a constellation",
      _span(_CPTS, _KNN) * 3.0 < _span(_CPTS, _CHORD)
      and len(_CHORD) <= pdf_map.LINK_MAX)
check("...and no nearest-neighbour link is longer than the span "
      "ceiling, so a sparse corner of the cloud is left alone rather "
      "than reaching across the card for a partner",
      all(math.dist(_CPTS[i], _CPTS[j]) <= pdf_map.LINK_MAX_SPAN + 1e-9
          for i, j in _KNN))
check("degenerate clouds do not raise on the build path",
      pdf_map.constellation_links([]) == []
      and pdf_map.constellation_links([(0.0, 0.0, 0.0)]) == []
      and pdf_map.constellation_links(_CPTS, cap=0) == []
      and pdf_map.constellation_links(_CPTS, mode="nonsense") == [])

_RAMP = [pdf_map.edge_mix(i) for i in range(pdf_map.EDGE_TAPER)]
check("the focused PDF's spokes TAPER along their own length: a ramp "
      "of at least three steps, brightest at the hub and falling to "
      "EDGE_TAIL of that at the tip. Rendered FLAT first, and 90 hard "
      "lines converging on one node is a dandelion whose far ends "
      "carry as much weight as the node they are about",
      pdf_map.EDGE_TAPER >= 3
      and _RAMP == sorted(_RAMP, reverse=True)
      and len(set(_RAMP)) == len(_RAMP)
      and abs(_RAMP[0] - pdf_map.EDGE_MIX) < 1e-9
      and abs(_RAMP[-1] - pdf_map.EDGE_MIX * pdf_map.EDGE_TAIL) < 1e-9,
      f"ramp {[round(v, 3) for v in _RAMP]}")
check("...and the ramp degrades rather than dividing by zero at one "
      "step, and clamps rather than raising on the paint path",
      pdf_map.edge_mix(0, 1) == pdf_map.EDGE_MIX
      and pdf_map.edge_mix(99) == _RAMP[-1]
      and pdf_map.edge_mix(-5) == _RAMP[0]
      and pdf_map.edge_mix("junk") == _RAMP[0])

# Rotation. "Just have it rotate slowly in 3D."
check("the 0.42 rad sway is gone and the scene TURNS — a full "
      "revolution, which is what 'rotate' means",
      not hasattr(pdf_map, "IDLE_SWING")
      and pdf_map.ROTATE_PERIOD_MS >= 30000.0)
check("...slowly: under 15 degrees a second, and under half a degree "
      "per tick so no frame jumps",
      math.degrees(2.0 * math.pi) / (pdf_map.ROTATE_PERIOD_MS / 1000.0) < 15.0
      and math.degrees(2.0 * math.pi * pdf_map.IDLE_TICK_MS
                       / pdf_map.ROTATE_PERIOD_MS) < 0.5)

# A fit that has to survive every pose, not just the resting one.
_SBOX = (-0.8, -0.5, -0.6, 0.9, 0.4, 0.7)
_SWEPT = pdf_map.sweep_bounds(_SBOX, pdf_map.Camera(0.0))
check("a rotating canvas frames the SWEPT box: at every pose of a full "
      "turn the graph still fits inside what the fit framed. A box "
      "framed at rest is 40% too small at the diagonal and the cloud "
      "swings out of the card every quarter turn",
      all(pdf_map.camera_bounds(_SBOX, pdf_map.Camera(a))[0] >= _SWEPT[0] - 1e-9
          and pdf_map.camera_bounds(_SBOX, pdf_map.Camera(a))[1] >= _SWEPT[1] - 1e-9
          and pdf_map.camera_bounds(_SBOX, pdf_map.Camera(a))[2] <= _SWEPT[2] + 1e-9
          and pdf_map.camera_bounds(_SBOX, pdf_map.Camera(a))[3] <= _SWEPT[3] + 1e-9
          for a in [i * math.pi / 32.0 for i in range(64)]))
_CUBE = (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)
check("...and it really is BIGGER than the resting pose, so the sweep "
      "is doing something rather than agreeing by accident. On the "
      "graph's own [-1,1] cube the growth is all in the VERTICAL: "
      "face-on, perspective already magnifies the near left and right "
      "corners, while turning brings the top and bottom corners "
      "forward and the box grows 37% taller",
      (pdf_map.sweep_bounds(_CUBE, pdf_map.Camera(0.0))[3]
       - pdf_map.sweep_bounds(_CUBE, pdf_map.Camera(0.0))[1])
      > (pdf_map.camera_bounds(_CUBE, pdf_map.Camera(0.0))[3]
         - pdf_map.camera_bounds(_CUBE, pdf_map.Camera(0.0))[1]) * 1.3
      and pdf_map.frame_bounds(_CUBE, pdf_map.Camera(0.0), (900.0, 640.0),
                               pdf_map.SWEEP_STEPS).scale
      < pdf_map.frame_bounds(_CUBE, pdf_map.Camera(0.0),
                             (900.0, 640.0)).scale * 0.8)
check("...and the sweep holds for a LOPSIDED box too, where the "
      "orthographic 1/cos bound alone does not: 300 random boxes, 360 "
      "poses each, none escaping",
      not [1 for _b in [
          (-0.973, -0.032, -0.982, 0.638, 0.569, 0.42),
          (-0.2, -0.9, -0.05, 0.95, 0.1, 0.99),
          (-1.0, -0.01, -1.0, 0.02, 0.01, 0.03)]
          for _a in [i * math.pi / 36.0 for i in range(72)]
          if not (
              pdf_map.camera_bounds(_b, pdf_map.Camera(_a))[0]
              >= pdf_map.sweep_bounds(_b, pdf_map.Camera(0.0))[0] - 1e-9
              and pdf_map.camera_bounds(_b, pdf_map.Camera(_a))[2]
              <= pdf_map.sweep_bounds(_b, pdf_map.Camera(0.0))[2] + 1e-9
              and pdf_map.camera_bounds(_b, pdf_map.Camera(_a))[1]
              >= pdf_map.sweep_bounds(_b, pdf_map.Camera(0.0))[1] - 1e-9
              and pdf_map.camera_bounds(_b, pdf_map.Camera(_a))[3]
              <= pdf_map.sweep_bounds(_b, pdf_map.Camera(0.0))[3] + 1e-9)])
check("frame_bounds carries the sweep, so every fit path — first fit, "
      "the Fit button, Escape, the flight — gets ONE rule rather than "
      "four",
      pdf_map.frame_bounds(_SBOX, pdf_map.Camera(0.0), (900.0, 640.0),
                           sweep=pdf_map.SWEEP_STEPS).scale
      < pdf_map.frame_bounds(_SBOX, pdf_map.Camera(0.0), (900.0, 640.0)).scale
      and pdf_map.frame_bounds(_SBOX, pdf_map.Camera(0.0), (900.0, 640.0),
                               sweep=0).scale
      == pdf_map.frame_bounds(_SBOX, pdf_map.Camera(0.0),
                              (900.0, 640.0)).scale)

# K-185 INVERTS this pin: the map used to force theme.palette(True) so
# it stayed a night sky regardless of the app's theme — the rounded
# card floating on the panel is gone, so the panel IS the ground now,
# and the always-dark special case goes with it (both palettes get
# their own night-sky-flavoured ramp via c["bg"] = host chrome).
check("K-185 retires K-174's forced-dark palette: the map no longer "
      "hard-codes theme.palette(True) anywhere — it blends outward "
      "from the HOST palette's chrome token instead, in both themes",
      "theme.palette(True)" not in _CODE)

# ------------------------------------------------------------ glue pins

section("glue pins on the source — divider, K-114, K-115, tokens")

_DIVIDER = "# ── aqt glue ──"
check("the aqt-glue divider is present", _DIVIDER in _SRC)
_head_code = code_only(_SRC.split(_DIVIDER)[0])
check("no aqt anywhere above the divider (comment/string-stripped)",
      "aqt" not in _head_code)
check("K-114: no .exec( anywhere — the window is show()-only",
      ".exec(" not in _CODE and "win.show()" in _CODE)
check("no focus steal: activateWindow appears nowhere in code",
      "activateWindow" not in _CODE)
check("no literal hex colours (comments stripped, strings KEPT)",
      re.search(r"#[0-9a-fA-F]{6}\b", _strip_comments(_SRC)) is None)
check("colours come from theme.palette tokens",
      "theme.palette(" in _CODE)

_paints = [n for n in ast.walk(_TREE)
           if isinstance(n, ast.FunctionDef) and n.name == "paintEvent"]


def _guarded(fn) -> bool:
    """True when the paintEvent holds a Try whose FINALLY ends the
    painter — the K-115 guarantee."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Try) and node.finalbody:
            for stmt in node.finalbody:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Attribute) and sub.attr == "end":
                        return True
    return False


check("K-115: exactly one paintEvent, guarded by try/finally painter.end()",
      len(_paints) == 1 and _guarded(_paints[0]))

check("WA_DeleteOnClose is set on the window", "WA_DeleteOnClose" in _CODE)

_closes = [n for n in ast.walk(_TREE)
           if isinstance(n, ast.FunctionDef) and n.name == "closeEvent"]


def _clears_singleton(fn) -> bool:
    has_global = any(
        isinstance(n, ast.Global) and "_instance" in n.names
        for n in ast.walk(fn)
    )
    clears = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_instance"
                for t in n.targets)
        and isinstance(n.value, ast.Constant) and n.value.value is None
        for n in ast.walk(fn)
    )
    return has_global and clears


check("closeEvent clears the module singleton (global + None assign)",
      len(_closes) == 1 and _clears_singleton(_closes[0]))

check("open_map_window(parent=None) is the public surface",
      list(inspect.signature(pdf_map.open_map_window).parameters) == ["parent"]
      and inspect.signature(pdf_map.open_map_window).parameters["parent"].default
      is None)
check("wheel zoom funnels through the anchored zoom_at math",
      "zoom_at(" in _func_seg("wheelEvent"))
check("the canvas draws connections through links_for only",
      "links_for(" in _method_seg("_MapCanvas", "_paint_edges"))
check("labels are placed by label_anchor, never inline arithmetic",
      len(_calls_in("_paint_label", "label_anchor")) == 1)

# ---- the note layer, and the name that follows the selection ----
_paint_seg = _method_seg("_MapCanvas", "_paint_stars")
check("K-174: a star is ONE C++ call per band — a square-capped "
      "drawPoints, no gradient, no pixmap, and no Python loop over "
      "dots. K-158's sprite blit was the last per-point Python on the "
      "cloud's paint path (0.341 ms a frame against 0.28-0.31 for the "
      "hard points that replace it)",
      "drawPoints(" in _paint_seg
      and "drawPixmap(" not in _paint_seg
      and "QRadialGradient(" not in _paint_seg
      and "for wx, wy in self._notes" not in _CODE
      and "QRadialGradient(" in _method_seg("_MapCanvas", "_paint_nodes"))
check("the world->screen pass is QTransform.map on the POLYGON, and the "
      "PAINTER is never given a transform — a point draw under a scaled "
      "painter with a cosmetic pen degenerates into long horizontal "
      "strokes at zoom, and K-148's projective form makes that rule "
      "MORE load-bearing: a painter cannot carry a perspective divide "
      "to a cosmetic pen at all",
      "QTransform(*band_matrix(vp, cam, zb)).map(poly)" in _paint_seg
      and "painter.scale(" not in _CODE
      and "setTransform" not in _CODE
      and "setWorldTransform" not in _CODE)
check("the note polygons are built ONCE, by the canvas's own band "
      "builder, in world space — the cloud does not change, the camera "
      "does",
      "QPolygonF(" in _method_seg("_MapCanvas", "_make_bands")
      and _CODE.count("QPolygonF(") == 1
      and _CODE.count("_make_bands(") == 3)
_edge_seg = _method_seg("_MapCanvas", "_paint_edges")
check("K-174: every connection is a CRISP LINE, batched into one "
      "drawLines, with no path and no per-edge call — 'for all the "
      "node connections with everything else, I don't like the blurry "
      "stuff'. K-158's 6.35 ms was the AA rasterizer, not the "
      "composition mode and not the call count; one hard pass is "
      "0.092 ms for the same 90 spokes",
      "drawLines(" in _edge_seg
      and "drawLines(" in _method_seg("_MapCanvas", "_paint_constellation")
      and "drawPixmap(" not in _edge_seg
      and "drawPath(" not in _CODE
      and "drawLine(" not in _CODE
      and _CODE.count("drawLines(") == 2)
check("...and the layer that has to be hard is drawn with "
      "antialiasing OFF, which is the LOOK and not the optimisation: "
      "an antialiased 1px point is a soft 2x2 smear, and the "
      "reference's defining measurement is that nothing there runs "
      "longer than three lit pixels with no skirt around it",
      "RenderHint.Antialiasing, False" in _method_seg("_MapCanvas",
                                                      "_paint")
      and _method_seg("_MapCanvas", "_paint").index(
          "RenderHint.Antialiasing, False")
      < _method_seg("_MapCanvas", "_paint").index("_paint_stars(")
      < _method_seg("_MapCanvas", "_paint").index("_paint_nodes("))
check("K-138 reverses K-133: the painter names exactly the ACTIVE node, "
      "with no count or zoom gate left to consult",
      "if safe != active:" in _method_seg("_MapCanvas", "_paint_label")
      and "labels_visible" not in _CODE
      and "show_labels" not in _CODE)
check("the header hint is ONE line naming both the legend and the "
      "gestures",
      "\n" not in pdf_map.HINT_TEXT
      and "PDF" in pdf_map.HINT_TEXT
      and "note" in pdf_map.HINT_TEXT
      and all(g in pdf_map.HINT_TEXT
              for g in ("hover", "drag", "pan", "scroll", "zoom")))
_hint_seg = _SRC.split("QLabel(HINT_TEXT", 1)[-1].split("addWidget(hint)", 1)[0]
check("it is drawn exactly once, from the pinned copy, in the muted token",
      _CODE.count("HINT_TEXT") == 2
      and "QLabel(HINT_TEXT" in _CODE
      and "muted_label_qss" in _hint_seg)
check("select_pdf(safe) is the public follow-the-viewer seam",
      list(inspect.signature(pdf_map.select_pdf).parameters) == ["safe"])
check("select_pdf reaches the canvas through the singleton and the one "
      "recenter_for rule — it never re-derives placement itself",
      "canvas.select(" in _func_seg("select_pdf")
      and "recenter_for(" in _method_seg("_MapCanvas", "select")
      and len(_calls_in("select", "recenter_for")) == 1)
check("K-158: the hovered/focused node's name is drawn BY THE CANVAS, "
      "on its own plate — a native QToolTip at the global cursor and a "
      "label beside the node were two boxes fighting for one corner, "
      "and the plate is the one that can be themed, positioned and "
      "clamped into view",
      "QToolTip" not in _CODE
      and "node_lines(p)" in _method_seg("_MapCanvas", "_paint_label"))
check("house logging prefix present", '"[klausmate] ' in _SRC.replace("f\"", "\""))
check("empty-state copy is pinned",
      pdf_map.EMPTY_TEXT == "No indexed PDFs to map yet."
      and "EMPTY_TEXT" in _CODE)

# ---- K-143: ONE renderer, hoisted out of the window, still Qt-free ----
section("K-143 — the embeddable canvas factory")

check("map_canvas(parent, graph=None) is the public factory the Library "
      "dock instantiates",
      list(inspect.signature(pdf_map.map_canvas).parameters)
      == ["parent", "graph"]
      and all(p.default is None
              for p in inspect.signature(pdf_map.map_canvas)
              .parameters.values()))
check("graph_data() is public too — the dock builds it OFF the main "
      "thread (16.9 s on a 28,668-note collection) and passes it in",
      list(inspect.signature(pdf_map.graph_data).parameters) == []
      and "_load_graph()" in _func_seg("graph_data")
      and "_fill_retention(" in _func_seg("graph_data"))

_canvas_defs = [n for n in ast.walk(_TREE)
                if isinstance(n, ast.ClassDef) and n.name == "_MapCanvas"]
check("there is exactly ONE canvas class in the file — the dock does "
      "not get a copy to drift away from the window's",
      len(_canvas_defs) == 1)


def _enclosing_func(target: ast.ClassDef):
    """The FunctionDef whose body (at any depth) holds ``target``."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and any(
            sub is target for sub in ast.walk(node)
        ):
            return node
    return None


_canvas_home = _enclosing_func(_canvas_defs[0]) if _canvas_defs else None
check("it still lives INSIDE a function — the hoist moved the class, it "
      "did not free it to module level",
      _canvas_home is not None and _canvas_home.name == "_canvas_class")


class _NoAqt:
    """Import hook that makes every ``aqt`` import fail outright."""

    def find_module(self, name, path=None):  # py<3.12 compat, harmless
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        if name == "aqt" or name.startswith("aqt."):
            raise ImportError(f"aqt is not available ({name})")
        return None


_saved_aqt = {k: v for k, v in sys.modules.items()
              if k == "aqt" or k.startswith("aqt.")}
_saved_map = sys.modules.pop("klausmate.pdf_map")
for _k in _saved_aqt:
    del sys.modules[_k]
sys.meta_path.insert(0, _NoAqt())
try:
    importlib.import_module("klausmate.pdf_map")
    _qtfree = (True, "")
except Exception as _e:  # noqa: BLE001
    _qtfree = (False, f"{type(_e).__name__}: {_e}")
finally:
    sys.meta_path.pop(0)
    sys.modules.update(_saved_aqt)
    sys.modules["klausmate.pdf_map"] = _saved_map
check("...which is the actual guarantee, checked the only honest way: "
      "with every aqt import made to FAIL, this module still imports — "
      "the pure viewport model is tested headless and the divider pin "
      "cannot see below itself",
      _qtfree[0], _qtfree[1])
check("the window reaches it through the SAME factory as the dock, "
      "never by naming the class",
      "map_canvas(self, graph_dict)" in _func_seg("open_map_window")
      and "_MapCanvas(" not in _func_seg("open_map_window"))
check("the graph still comes from the ONE loader, never from a second "
      "path of open_map_window's own",
      "graph_data()" in _func_seg("_start_build")
      and "_load_graph()" not in _func_seg("open_map_window"))

# ---- K-144 (absorbed into K-148): the 17 s build leaves the UI thread ---

check("open_map_window does not build the graph inline any more — that "
      "17 s call froze Anki solid with nothing on screen to tell it "
      "from a hang",
      "graph_data()" not in code_only(_func_seg("open_map_window")))
_sb = code_only(_func_seg("_start_build"))
check("it runs on a QueryOp worker, the dock's K-143 pattern rather "
      "than a second one",
      "QueryOp(" in _sb and "run_in_background()" in _sb
      and ".failure(" in _sb)
check("...parented to mw, NEVER to the window: a QueryOp whose parent "
      "dies takes its callback with it, and a seventeen-second build "
      "is exactly long enough to close the window it belongs to",
      "parent=mw" in _sb and "parent=win" not in _sb)
check("so the singleton is what guards the callbacks instead — landing "
      "a canvas in a window the reader already closed would resurrect "
      "a dead surface",
      _sb.count("_instance is not win") == 2)
check("a second Map click can never queue a second 17 s job: the "
      "singleton is set BEFORE the worker starts, so the second call "
      "fronts and returns",
      _func_seg("open_map_window").index("_instance = win")
      < _func_seg("open_map_window").index("_start_build(win)"))

check("the canvas class is NOT memoized: a module-level cache would "
      "freeze it onto whichever aqt.qt was imported first, and the "
      "tests swap that underneath it on purpose",
      pdf_map._canvas_class() is not pdf_map._canvas_class())

check("the canvas declares NO minimum size of its own — how small the "
      "map may get belongs to the surface hosting it (the window wants "
      "480x360, the dock is a compact box that would otherwise inherit "
      "a 480px floor and widen the whole Library pane)",
      "setMinimumSize" not in _method_seg("_MapCanvas", "__init__")
      and "setMinimumSize(480, 360)" in _func_seg("open_map_window"))
check("both fallback lines the hosts can need are pinned copy here, so "
      "no host invents its own wording",
      _CODE.count("CANVAS_FAIL_TEXT") == 2
      and "BUILDING_TEXT" in _CODE
      and "BUILD_FAIL_TEXT" in _CODE)
check("every fit goes through frame_bounds, which carries fit_margin — "
      "so the compact-canvas cap reaches the initial fit, the Fit "
      "button and the click-to-fly landing alike, and no fit anywhere "
      "forgets that the graph is a 3D box seen from a pose",
      "frame_bounds(\n                self._bounds, self._cam, (w, h), self._sweep()\n            )"
      in _method_seg("_MapCanvas", "_apply_fit")
      and "fit_margin(widget_size)" in _func_seg("frame_bounds")
      and [n for n in ast.walk(_TREE)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "fit_to_view"] and len(
          [n for n in ast.walk(_TREE)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "fit_to_view"]) == 1)
check("a resize RE-ANCHORS the view (half the delta) and never re-fits "
      "— dragging the dock's handle must not throw away the pan and "
      "zoom the reader chose; that is what the Fit button is for",
      "pan_by(" in _method_seg("_MapCanvas", "resizeEvent")
      and "_apply_fit" not in _method_seg("_MapCanvas", "resizeEvent"))

# ---- K-148: motion, and who is allowed to have it ----

_ramp_seg = _func_seg("star_colour")
check("the depth ramp is a MIX of palette tokens, not alpha over the "
      "ground — the alpha version of this ramp cost 13.8 ms a frame "
      "against 2.9 at 28,668 dots, and K-174 keeps that call: the "
      "reference reaches for alpha only because a canvas floating over "
      "a CSS nebula has no ground of its own to mix into",
      _ramp_seg.count("blend_hex(") == 3
      and "setAlpha" not in _ramp_seg
      and "setAlphaF" not in _ramp_seg)
check("...and every end of it is a palette TOKEN, so the whole star "
      "field re-colours with the accent theme and invents no colour — "
      "including the near-white core, which is `text` and NOT the "
      "255/255/255 the reference looks like and measures not to be",
      all(t in _ramp_seg for t in
          ('c["bg"]', 'c["blue_bright"]', 'c["text"]')))
check("the pen cache is keyed on the palette's own tokens, not on "
      "night_mode — the map draws in the dark palette either way, so a "
      "night flip must not rebuild while an ACCENT change must",
      'key = (c["bg"], c["blue_bright"], c["text"], scale)'
      in _method_seg("_MapCanvas", "_ensure_pens"))

_arm = _method_seg("_MapCanvas", "_arm_idle")
_show = _method_seg("_MapCanvas", "showEvent")
check("the rotation timer NEVER starts from the constructor or from "
      "the host's request — it is armed from showEvent, after a delay, "
      "and re-checks visibility when the delay expires. md3_switch "
      "documents the SIGSEGV: repainting while the window is still "
      "being composited hands Qt's flush a paint device that is not "
      "there yet",
      "_idle.start()" not in _method_seg("_MapCanvas", "__init__")
      and "_arm_idle()" in _show
      and "_idle_arm.start(IDLE_START_DELAY_MS)" in _arm
      and "isVisible()" in _method_seg("_MapCanvas", "_idle_start_now"))
check("Reduce Motion is honoured on BOTH moving paths — the idle sway "
      "never starts, and a click arrives at its PDF instead of flying "
      "there (the scene stays 3D either way; only the movement stops)",
      "_reduce_motion()" in _arm
      and "_reduce_motion()" in _method_seg("_MapCanvas", "fly_to")
      and "mw.pm.reduce_motion()"
      in _method_seg("_MapCanvas", "_reduce_motion"))
check("a hidden canvas stops paying for frames nobody can see",
      "_idle.stop()" in _method_seg("_MapCanvas", "hideEvent")
      and "isVisible()" in _method_seg("_MapCanvas", "_idle_tick"))
check("only the standalone WINDOW asks for the sway — the Library's "
      "dock renders the same scene STILL, which was Pouya's own call, "
      "so the factory must not turn it on for every host",
      _CODE.count("set_idle_rotation(True)") == 1
      and "set_idle_rotation(True)" in _func_seg("open_map_window")
      and "set_idle_rotation" not in code_only(_func_seg("map_canvas")))
check("pressing a PDF flies the camera to it, and ONLY the click path "
      "does: select() is the PDF viewer's seam and keeps its gentler "
      "contract (recentre only when off-view, never touch the zoom)",
      "fly_to(" in _method_seg("_MapCanvas", "mouseReleaseEvent")
      and "fly_to" not in _method_seg("_MapCanvas", "select")
      and "recenter_for(" in _method_seg("_MapCanvas", "select"))
check("the flight is a QPropertyAnimation on an OutCubic curve — "
      "md3_switch's shape, the one motion language this addon has",
      "QPropertyAnimation(" in _CODE
      and "QEasingCurve.Type.OutCubic" in _CODE
      and "pyqtProperty(" in _CODE)
check("what it flies TO is the PDF's node and the BULK of the notes it "
      "will actually show connected — trimmed, because framing every "
      "match left the flight zooming by 1.00x on the real library — "
      "and never wider than the whole graph",
      "links_for(" in _method_seg("_MapCanvas", "_fly_target")
      and "trimmed_bounds(pts, FLY_TRIM)" in _method_seg("_MapCanvas",
                                                         "_fly_target")
      and "frame_bounds(self._bounds" in _method_seg("_MapCanvas",
                                                     "_fly_target"))

# ----------------------------------------------------- stub-harness smoke

section("glue smoke under the stub harness")

check("select_pdf with NO map open is a silent no-op — the viewer must "
      "be free to call it on every file without asking first",
      pdf_map._instance is None and pdf_map.select_pdf("anything") is False)

curation = importlib.import_module("klausmate.curation")
tmp = tempfile.mkdtemp(prefix="klaus_map_")
_orig_uf = curation.USER_FILES
curation.USER_FILES = tmp  # NEVER the real user_files
try:
    win = pdf_map.open_map_window(None)
    check("open_map_window builds under stubs (empty-graph path)",
          win is not None)
    check("the module singleton is set", pdf_map._instance is win)
    check("it comes back with NO canvas and nothing installed — the "
          "window is on screen while the worker runs, which is the "
          "whole K-144 point (the status TEXT is asserted on real Qt "
          "below; a stub QLabel returns a dummy, not a string)",
          getattr(win, "canvas", "sentinel") is None
          and win._installed is False)
    win2 = pdf_map.open_map_window(None)
    check("a second call fronts the SAME window", win2 is win)
    win._install({"pdfs": [], "notes": [], "edges": []})
    check("an empty graph landing installs the empty state rather than "
          "a canvas",
          win.canvas is None and win._installed is True)
    win._install({"pdfs": [{"safe": "late", "xy": [0, 0]}]})
    check("a second landing cannot install twice — one worker, one "
          "chrome, however the callbacks fire",
          win.canvas is None)
    _cap, sys.stdout = sys.stdout, io.StringIO()
    try:
        _quiet = (pdf_map.select_pdf("lec1"), sys.stdout.getvalue())
    finally:
        sys.stdout = _cap
    check("an empty-graph window has no canvas, so select_pdf no-ops "
          "SILENTLY — not by raising into the blanket except and "
          "printing an error the reader can do nothing about",
          _quiet == (False, ""), repr(_quiet))
finally:
    curation.USER_FILES = _orig_uf
    pdf_map._instance = None
    shutil.rmtree(tmp, ignore_errors=True)

_orig_load = pdf_map._load_graph
_orig_fill = pdf_map._fill_retention
pdf_map._load_graph = lambda: FAKE
pdf_map._fill_retention = lambda g: None
try:
    win3 = pdf_map.open_map_window(None)
    win3._install(pdf_map.graph_data())  # the seam the worker lands in
    check("a populated graph builds the canvas window",
          win3 is not None and getattr(win3, "canvas", None) is not None)
    check("the canvas indexed both pdf nodes and every positioned note",
          set(win3.canvas._pdf_xyz) == {"lec1", "lec2"}
          and set(win3.canvas._note_xyz) == {1, 2, 3})
    # The geometry half of select_pdf needs real widget sizes, so it
    # lives in the offscreen-Qt section below. Clearing needs none —
    # but it needs something to clear, or it passes vacuously.
    win3.canvas._selected = "lec1"
    check("an unknown name CLEARS the selection rather than leaving a "
          "stale ring over a PDF you are no longer looking at",
          pdf_map.select_pdf("not-on-this-map") is False
          and win3.canvas._selected is None)
    win3.canvas._selected = "lec1"
    check("None and the empty string clear it the same way",
          pdf_map.select_pdf(None) is False
          and win3.canvas._selected is None
          and pdf_map.select_pdf("") is False)

    # ---- K-143: the factory, with no window anywhere near it ----
    _before_inst = pdf_map._instance
    _solo = pdf_map.map_canvas(None, FAKE)
    check("map_canvas builds a canvas with NO window: the dock hosts one "
          "in the Library's left pane and there is nothing to front, "
          "close, or keep as a singleton",
          _solo is not None
          and set(_solo._pdf_xyz) == {"lec1", "lec2"}
          and pdf_map._instance is _before_inst)
    # The CLEAR half needs no geometry; selecting a known node recentres
    # and so belongs in the offscreen section, same split as the window's.
    _solo._selected = "lec1"
    check("the same select() contract rides on it — select_pdf's rules "
          "live in the canvas, so the dock re-derives nothing",
          _solo.select("nope") is False and _solo._selected is None)
    _passed = {"pdfs": [], "notes": [], "edges": []}
    _loads = []
    _real_gd, pdf_map.graph_data = pdf_map.graph_data, lambda: _loads.append(1)
    try:
        pdf_map.map_canvas(None, _passed)
        check("a graph handed in is NEVER re-loaded — that is the whole "
              "point of the parameter, since loading blocks for seconds",
              _loads == [])
    finally:
        pdf_map.graph_data = _real_gd
finally:
    pdf_map._load_graph = _orig_load
    pdf_map._fill_retention = _orig_fill
    pdf_map._instance = None

# ------------------------------------------------- real offscreen Qt

section("real offscreen Qt — the note layer, the name, the viewer seam")
# PyQt6 is installed for THIS interpreter (Anki's bundled one is 3.13
# bytecode; ours is not) — test_drive.py's precedent. open_map_window
# imports aqt.qt lazily inside itself, so swapping the module in
# sys.modules is the whole bootstrap: nothing needs re-importing.
# Everything here is a claim the _Any stubs above physically cannot
# make, because _Dummy has no geometry and paints no pixels.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC  # noqa: E402
    from PyQt6 import QtGui as _QtG  # noqa: E402
    from PyQt6 import QtWidgets as _QtW  # noqa: E402

    _HAVE_QT = True
except Exception as _qt_e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — "
          "the pure model and source pins above still ran")

if _HAVE_QT:
    _qt_shim = types.ModuleType("aqt.qt")

    def _qt_getattr(name, _mods=(_QtW, _QtC, _QtG)):
        for _m in _mods:
            if hasattr(_m, name):
                return getattr(_m, name)
        if name == "qconnect":
            return lambda sig, fn: sig.connect(fn)
        raise AttributeError(name)

    _qt_shim.__getattr__ = _qt_getattr
    sys.modules["aqt.qt"] = _qt_shim

    theme = importlib.import_module("klausmate.theme")
    _orig_night = theme.night_mode
    _app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])

    def _render(widget, w, h):
        img = _QtG.QImage(w, h, _QtG.QImage.Format.Format_ARGB32)
        img.fill(0)
        widget.render(img)
        return img

    def _name_pixels(widget, w, h):
        """Count NEUTRAL bright pixels — the plate's text, and nothing
        else on this canvas.

        K-148 counted near-BLACK ink, which worked because the map drew
        on a light ground. K-158 draws in the dark palette in both
        themes, so black is now the background and the question has to
        be asked the other way round: the text token is a neutral grey
        (r == g == b), while every other lit thing here — stars, node
        core, rings, beams — is mixed from the blue accent and keeps a
        visible blue lean. The card's own 1px border is neutral too, so
        the scan insets past it.
        """
        img = _render(widget, w, h)
        n = 0
        for y in range(4, h - 4, 2):
            for x in range(4, w - 4, 2):
                c = img.pixelColor(x, y)
                if (c.alpha() > 200 and min(c.red(), c.green(), c.blue()) > 150
                        and abs(c.red() - c.blue()) <= 12):
                    n += 1
        return n

    # One PDF, NO notes: the only ink that can be dark is its name.
    NAMED = {
        "pdfs": [{"safe": "solo", "display": "Renal Physiology", "folder": None,
                  "threshold": 0.4, "retention": None, "xy": [0.0, 0.0],
                  "match_count": 9}],
        "notes": [], "edges": [],
    }
    pdf_map._fill_retention = lambda g: None
    try:
        # True, not False: K-185 retired the always-dark ground, so the
        # canvas now paints on WHICHEVER theme is forced. _name_pixels'
        # bright-neutral-pixel heuristic still assumes a dark ground
        # (that is what it is measuring against); forcing night mode
        # here keeps that assumption true rather than rewriting the
        # heuristic for a scenario this test was never about.
        theme.night_mode = lambda: True
        pdf_map._load_graph = lambda: NAMED
        w4 = pdf_map.open_map_window(None)
        check("on real Qt the window opens saying so, in words, before "
              "the worker has landed anything — K-144's whole visible "
              "difference from a seventeen-second hang",
              w4.canvas is None
              and w4.status.text() == pdf_map.BUILDING_TEXT
              and w4.isVisible())
        w4._install(pdf_map.graph_data())
        check("...and the building line is gone once the graph lands",
              not w4.status.isVisible())
        pdf_map._instance = None
        _capq, sys.stdout = sys.stdout, io.StringIO()
        try:
            _wfail = pdf_map.open_map_window(None)
            _wfail._build_failed(RuntimeError("boom"))
        finally:
            sys.stdout = _capq
        check("a worker that FAILS says so in words rather than leaving "
              "the reader watching 'Building…' forever",
              _wfail.status.text() == pdf_map.BUILD_FAIL_TEXT)
        _wfail.close()
        pdf_map._instance = w4
        w4.resize(700, 500)
        cv = w4.canvas
        cv.resize(660, 420)
        _app.processEvents()
        cv._selected = None
        cv._hover = None
        quiet = _name_pixels(cv, 660, 420)
        cv._hover = "solo"
        named = _name_pixels(cv, 660, 420)
        check("K-138 reverses K-133 ON THE PIXELS: with nothing focused "
              "the map draws no PDF name at all, and hovering the circle "
              "draws one",
              quiet == 0 and named > 0,
              f"quiet={quiet} hovered={named}")
        cv._hover = None
        cv._selected = "solo"
        check("selecting names it too — that is what the viewer seam "
              "gets, since it selects rather than hovers",
              _name_pixels(cv, 660, 420) > 0)
    finally:
        pdf_map._instance = None
        theme.night_mode = _orig_night

    # A real cloud: every note reaches the polygon, and both palettes
    # paint it without raising.
    _rng = random.Random(4)
    _notes = [{"nid": i, "xyz": [_rng.gauss(0, .3), _rng.gauss(0, .3),
                                 _rng.gauss(0, .3)]}
              for i in range(1500)]
    CLOUD = {
        "pdfs": [
            {"safe": "lec1", "display": "Lecture One", "folder": None,
             "threshold": .4, "retention": None, "xyz": [-0.5, -0.2, .35],
             "match_count": 40},
            {"safe": "lec2", "display": "Lecture Two", "folder": "F",
             "threshold": .4, "retention": None, "xyz": [0.6, 0.4, -.45],
             "match_count": 12},
        ],
        "notes": _notes,
        "edges": [{"pdf": "lec1", "nid": i, "score": .9} for i in range(40)],
    }
    try:
        for _night in (False, True):
            theme.night_mode = lambda n=_night: n
            pdf_map._load_graph = lambda: CLOUD
            w5 = pdf_map.open_map_window(None)
            w5._install(pdf_map.graph_data())
            w5.resize(900, 640)
            cv = w5.canvas
            cv.resize(860, 560)
            _app.processEvents()
            if not _night:
                _in_bands = sum(poly.count() for _i, _z, poly in cv._bands)
                _in_links = sum(
                    poly.count() for _b in cv._link_bands.values()
                    for _i, _z, poly in _b)
                check("K-158 reverses K-138: the cloud is SAMPLED, and "
                      "the caption's 'showing N' is a fact about the "
                      "picture — every dot the canvas put in a polygon "
                      "is counted, by a route that has nothing to do "
                      "with the number split_cloud returned",
                      _in_bands + _in_links == cv.shown_notes()
                      and cv.shown_notes() < len(_notes)
                      and cv.note_total() == len(_notes) == 1500,
                      f"{_in_bands} ambient + {_in_links} linked vs "
                      f"shown_notes()={cv.shown_notes()} of "
                      f"{cv.note_total()}")
                check("...and the ambient sample honours SAMPLE_NOTES "
                      "while every drawn connection lands on a drawn "
                      "dot — an edge into empty space is worse than no "
                      "edge",
                      _in_bands <= pdf_map.SAMPLE_NOTES
                      and _in_links == sum(
                          len(v) for v in cv._link_pts.values())
                      and len(cv._link_pts["lec1"])
                      == min(pdf_map.SAMPLE_PER_PDF, 40))
            _img = _QtG.QImage(860, 560, _QtG.QImage.Format.Format_ARGB32)
            _img.fill(0)
            cv.render(_img)
            _seen = {_img.pixelColor(x, y).name()
                     for y in range(0, 560, 3) for x in range(0, 860, 3)}
            check(f"the cloud paints in the {'night' if _night else 'day'} "
                  "palette (several distinct inks, nothing raised)",
                  len(_seen) > 3, str(len(_seen)))

            # ---- select_pdf's geometry half, on real widget sizes ----
            if not _night:
                cv._apply_fit(860.0, 560.0)
                _before = cv._vp
                check("select_pdf(known) selects that node and reports True",
                      pdf_map.select_pdf("lec2") is True
                      and cv._selected == "lec2")
                check("a node already in view is not chased — the map must "
                      "not jump under the reader on every file change",
                      cv._vp is _before)
                cv._vp = pdf_map.pan_by(cv._vp, -5000.0, -5000.0)
                _cw, _ch = float(cv.width()), float(cv.height())
                _sx, _sy, _ = pdf_map.project_point(
                    cv._vp, cv._cam, -0.5, -0.2, .35)
                check("(that node really was off-view first)",
                      not (0 <= _sx <= _cw and 0 <= _sy <= _ch))
                _took = pdf_map.select_pdf("lec1")
                _now = pdf_map.project_point(
                    cv._vp, cv._cam, -0.5, -0.2, .35)[:2]
                check("select_pdf recentres an off-view node and keeps the "
                      "zoom the reader chose",
                      _took is True
                      and cv._selected == "lec1"
                      and cv._vp.scale == _before.scale
                      and abs(_now[0] - _cw / 2.0) < 1e-6
                      and abs(_now[1] - _ch / 2.0) < 1e-6,
                      f"node at {_now} in a {_cw}x{_ch} canvas")
            pdf_map._instance = None

        # ---- K-143: the SAME renderer, hosted by nothing at all ----
        # The dock puts this widget in the Library's left pane, so the
        # claim that has to hold on real Qt is that a parentless canvas
        # sizes, paints and follows the viewer with no window in sight.
        # True, not False (K-185): everything below this point through
        # the end of this try — the ghost-ratio ratio check, the hard
        # star-run measurement, the sparse-field density check — reads
        # ABSOLUTE pixel brightness against a dark ground. K-185 retired
        # the always-dark canvas, so this suite forces the dark palette
        # itself now rather than getting it for free.
        theme.night_mode = lambda: True
        _dock = pdf_map.map_canvas(None, CLOUD)
        # shown, because Qt delivers no resizeEvent to a hidden widget
        # and the resize behaviour below is the point (offscreen, so
        # nothing appears anywhere)
        _dock.show()
        _dock.resize(545, 185)  # the Library's box at the default size
        _app.processEvents()
        check("a windowless canvas takes the host's size — it declares "
              "no minimum of its own, so a compact box stays compact",
              _dock.minimumWidth() == 0 and _dock.minimumHeight() == 0
              and (_dock.width(), _dock.height()) == (545, 185))
        _di = _QtG.QImage(545, 185, _QtG.QImage.Format.Format_ARGB32)
        _di.fill(0)
        _dock.render(_di)
        _dink = {_di.pixelColor(x, y).name()
                 for y in range(0, 185, 3) for x in range(0, 545, 3)}
        check("...and it paints the whole graph there (several inks, "
              "nothing raised, no window involved)", len(_dink) > 3,
              str(len(_dink)))
        _dock._apply_fit(545.0, 185.0)
        # The graph's height ON SCREEN. Not scale*2 any more: the camera
        # plane a [-1,1] cube projects onto is bigger than the cube (the
        # near face is magnified), so pixels per world unit no longer
        # equals pixels per graph.
        _cb = pdf_map.camera_bounds(_dock._bounds, _dock._cam)
        _spread = (_cb[3] - _cb[1]) * _dock._vp.scale
        check("the K-143 margin cap earns its place on the real box: the "
              "graph spans most of the 185px height instead of half of "
              "it (48px a side would have left 89)",
              _spread > 0.7 * 185.0, f"graph spans {_spread:.0f}px of 185")
        # Dragging the dock's splitter handle IS a resize, so this is the
        # everyday interaction, not an edge case. Rendered at the box's
        # 150px floor before the fix: the picture slid out of the bottom
        # of the card and took the selected node's name with it.
        _mid_before = pdf_map.screen_to_world(_dock._vp, 545 / 2.0, 185 / 2.0)
        _scale_before = _dock._vp.scale
        _dock.resize(545, 120)
        _app.processEvents()
        _mid_after = pdf_map.screen_to_world(_dock._vp, 545 / 2.0, 120 / 2.0)
        check("shrinking the box keeps the CENTRE world-point centred — "
              "the graph stays where the reader was looking instead of "
              "sliding out of the bottom",
              abs(_mid_after[0] - _mid_before[0]) < 1e-9
              and abs(_mid_after[1] - _mid_before[1]) < 1e-9,
              f"{_mid_before} -> {_mid_after}")
        check("...and it is a re-anchor, NOT a re-fit: a resize must "
              "never discard the zoom the reader chose",
              _dock._vp.scale == _scale_before)
        _dock.resize(545, 185)
        _app.processEvents()

        # ---- K-148: the depth-banded projection, ON REAL QT ----
        # THE pin of this card. band_matrix is a hand-derived projective
        # 3x3 fed straight to QTransform, and a transposed pair or a
        # swapped m13/m23 would still render *something* plausible while
        # putting every dot in the wrong place. The only honest check is
        # to make Qt map a point through the band matrix and compare it
        # with the same point through the per-point path.
        _worst = 0.0
        for _ang in (0.0, 0.30, -0.42, 0.9, 2.4, -3.0):
            _cam_t = pdf_map.Camera(_ang)
            for _vp_t in (pdf_map.Viewport(1.0, 0.0, 0.0),
                          pdf_map.Viewport(263.5, 411.0, -87.25),
                          pdf_map.Viewport(9000.0, -12000.0, 4300.0)):
                for _z in (-1.0, -0.3, 0.0, 0.55, 1.0):
                    _xf = _QtG.QTransform(
                        *pdf_map.band_matrix(_vp_t, _cam_t, _z))
                    for _x, _y in ((0.0, 0.0), (1.0, -1.0), (-0.7, 0.4)):
                        _m = _xf.map(_QtC.QPointF(_x, _y))
                        _p = pdf_map.project_point(_vp_t, _cam_t, _x, _y, _z)
                        _worst = max(_worst, abs(_m.x() - _p[0]),
                                     abs(_m.y() - _p[1]))
        check("a band's QTransform puts every point EXACTLY where the "
              "per-point projection would — 270 combinations of angle, "
              "zoom and depth agree to 1e-6, which is the only way to "
              "catch a transposed coefficient in a hand-derived "
              "projective matrix",
              _worst < 1e-6, f"worst disagreement {_worst:.3e} px")

        # A node at the front of the cloud DRAWS bigger than
        # node_radius says, so the hit radius has to know that or the
        # biggest, most clickable-looking circles get a dead rim. The
        # fixture is the case that bites: a many-match node (radius at
        # its NODE_R_MAX clamp) sitting at the near face.
        _hitc = pdf_map.map_canvas(None, {
            "pdfs": [{"safe": "big", "display": "Big", "threshold": .4,
                      "xyz": [0.0, 0.0, 1.0], "match_count": 500}],
            "notes": [{"nid": 1, "xyz": [-1, -1, -1]},
                      {"nid": 2, "xyz": [1, 1, 1]}],
            "edges": [],
        })
        _hitc.show()
        _hitc.resize(700, 460)
        _app.processEvents()
        _hitc._apply_fit(700.0, 460.0)
        _hx, _hy, _hd = pdf_map.project_point(
            _hitc._vp, _hitc._cam, *_hitc._pdf_xyz["big"])
        _hr = pdf_map.node_radius(500) * min(_hd, pdf_map.DOT_DEPTH_MAX)
        check("the rim of a NEAR node is still clickable — the hit "
              "radius follows the size perspective actually draws it "
              "at, not the flat radius",
              _hitc._hit_at(_hx + _hr - 0.5, _hy) == "big"
              and _hitc._hit_radius >= _hr,
              f"drawn r={_hr:.1f}, hit radius={_hitc._hit_radius:.1f}")

        _spin = pdf_map.map_canvas(None, CLOUD)
        _spin.show()
        _spin.resize(700, 460)
        _app.processEvents()

        def _ink(widget, w, h):
            _i = _QtG.QImage(w, h, _QtG.QImage.Format.Format_ARGB32)
            _i.fill(0)
            widget.render(_i)
            return _i

        _im_a = _ink(_spin, 700, 460)
        _spin._cam = pdf_map.Camera(pdf_map.REST_ANGLE + 0.6)
        _im_b = _ink(_spin, 700, 460)
        _moved = sum(1 for y in range(0, 460, 4) for x in range(0, 700, 4)
                     if _im_a.pixelColor(x, y) != _im_b.pixelColor(x, y))
        check("turning the camera actually MOVES the picture — the "
              "rotation reaches the pixels rather than recomputing a "
              "matrix that changes nothing",
              _moved > 200, f"{_moved} sampled pixels changed")
        # K-174: a FULL TURN, which K-148 refused on two worries. The
        # honest test of both is to render every pose and look at the
        # numbers: nothing may raise, the cloud may not collapse to a
        # line at the quarter turns, and the far half may not paint
        # over the near half when cos(angle) changes sign.
        _spread = []
        for _k in range(16):
            _spin._cam = pdf_map.Camera(2.0 * math.pi * _k / 16.0)
            _pi = _ink(_spin, 700, 460)
            _cols = [x for y in range(0, 460, 3) for x in range(0, 700, 3)
                     if _pi.pixelColor(x, y).red()
                     + _pi.pixelColor(x, y).green()
                     + _pi.pixelColor(x, y).blue() > 260]
            _spread.append((max(_cols) - min(_cols)) if _cols else 0)
        check("a FULL revolution renders at every pose and the cloud "
              "never collapses: K-148 kept a 0.42 rad sway because a "
              "spin 'sweeps through the edge-on pose where the cloud "
              "collapses to a line'. That is true of a PLANE; a PCA "
              "cloud has three components, so the narrowest pose is "
              "still most of the widest",
              min(_spread) > 0.45 * max(_spread),
              f"lit spans over 16 poses: min {min(_spread)} "
              f"max {max(_spread)}")
        _spin._cam = pdf_map.Camera()

        # Depth has to be VISIBLE, not merely computed: the near tier's
        # stars are both brighter and bigger than the far tier's, and
        # while a PDF is focused the rest of the field steps back.
        _spin._pens = {}
        _pal = theme.palette(True)
        _spin._ensure_pens(_pal)
        _far = pdf_map.star_colour(_pal, pdf_map.tier_position(0))
        _near = pdf_map.star_colour(
            _pal, pdf_map.tier_position(pdf_map.STAR_TIERS - 1))

        def _lum(hexc):
            _c = _QtG.QColor(hexc)
            return _c.red() + _c.green() + _c.blue()

        check("the far tier is dimmer AND smaller than the near one — "
              "brightness and size are the ONLY two carriers of depth "
              "left now that nothing blurs, which is exactly how the "
              "reference does it",
              _lum(_near) > _lum(_far) + 220
              and pdf_map.star_size(1.0) > pdf_map.star_size(0.0),
              f"far {_far} ({_lum(_far)}), near {_near} ({_lum(_near)})")
        check("...and the ramp travels through HUE as well as value: "
              "the far face sinks into the ground as a cold blue while "
              "the near face lands on the palette's near-white. The "
              "reference's own bright pixels are 214/222/248, not the "
              "255/255/255 they look like",
              _QtG.QColor(_far).saturation() > 60
              and _QtG.QColor(_near).value()
              > _QtG.QColor(_far).value() + 100,
              f"far sat {_QtG.QColor(_far).saturation()} val "
              f"{_QtG.QColor(_far).value()}, near sat "
              f"{_QtG.QColor(_near).saturation()} val "
              f"{_QtG.QColor(_near).value()}")
        _dim = pdf_map.star_colour(
            _pal, pdf_map.tier_position(pdf_map.STAR_TIERS - 1), dim=True)
        check("a focused PDF pushes the rest of the field BACK — the "
              "dimmed ramp is strictly darker than the lit one, which "
              "is what stops its own notes drowning in everything else",
              _lum(_dim) < _lum(_near))
        check("the cache holds PENS now, one per tier per state, and "
              "every one of them is square-capped: drawPoints paints "
              "each point as the pen's cap, and a round cap is a path "
              "Qt has to rasterize (K-148 measured that at 16x a "
              "square) AND a soft edge where the brief wants a hard one",
              len(_spin._pens) == pdf_map.STAR_TIERS * 3
              and all(pen.capStyle() == _QtC.Qt.PenCapStyle.SquareCap
                      and 1 <= pen.width() <= pdf_map.STAR_SIZE_MAX
                      for pen in _spin._pens.values()))
        _spin._pens = {}
        _spin._ensure_pens(_pal, 0.6)
        check("...and a SMALL canvas gets smaller stars (fit_margin's "
              "K-143 rule one layer down: the dock packs the whole "
              "cloud into ~110px, where a window-sized dot is a blot)",
              pdf_map.dot_scale((545.0, 185.0)) < 1.0
              and pdf_map.dot_scale((1100.0, 660.0)) == 1.0
              and _spin._pens[
                  (pdf_map.STAR_TIERS - 1, False, False)].width()
              < pdf_map.STAR_SIZE_MAX)
        _spin._pens = {}

        # ---- the timer, on a real widget ----
        _spin._reduce_motion = lambda: False
        check("a canvas nobody asked to rotate never runs a timer — the "
              "Library's dock hosts exactly this",
              not _spin._idle.isActive())
        _spin.set_idle_rotation(True)
        check("...and asking for it does not start one on the spot "
              "either: the arm is delayed past the first frame",
              not _spin._idle.isActive())
        _t_ok = []
        _timer_wait = _QtC.QEventLoop()
        _QtC.QTimer.singleShot(pdf_map.IDLE_START_DELAY_MS + 250,
                               _timer_wait.quit)
        _timer_wait.exec()
        check("once the delay expires on a visible canvas the sway is "
              "running",
              _spin._idle.isActive())
        _before_angle = _spin._cam.angle
        _spin._idle_tick()
        check("and one tick re-poses the camera",
              _spin._cam.angle != _before_angle)
        _spin.hide()
        _app.processEvents()
        check("hiding it stops the timer dead", not _spin._idle.isActive())

        _rm = pdf_map.map_canvas(None, CLOUD)
        _rm.show()
        _rm.resize(400, 300)
        _rm._reduce_motion = lambda: True
        _rm.set_idle_rotation(True)
        _rm._arm_idle()
        check("Reduce Motion: the sway never arms at all",
              not _rm._idle.isActive())
        _rm._ensure_fit(400.0, 300.0)
        _rm_before = _rm._vp
        check("...and a click ARRIVES at the PDF instead of flying "
              "there — the target is reached in one frame, with no "
              "animation left running",
              _rm.fly_to("lec1") is True
              and _rm._vp is not _rm_before
              and _rm._fly_anim.state()
              != _QtC.QAbstractAnimation.State.Running)

        # A PDF whose matches actually cluster (which is what semantic
        # matches do), beside one whose matches are scattered over the
        # whole cloud — the two ends of what clicking can mean.
        _fr = random.Random(9)
        _FLYG = {
            "pdfs": [
                {"safe": "tight", "display": "Tight", "threshold": .4,
                 "xyz": [0.45, -0.35, 0.2], "match_count": 60},
                {"safe": "spread", "display": "Spread", "threshold": .4,
                 "xyz": [0.0, 0.0, 0.0], "match_count": 60},
            ],
            "notes": ([{"nid": i, "xyz": [0.45 + _fr.gauss(0, .05),
                                          -0.35 + _fr.gauss(0, .05),
                                          0.2 + _fr.gauss(0, .05)]}
                       for i in range(60)]
                      + [{"nid": 100 + i, "xyz": [_fr.uniform(-1, 1),
                                                  _fr.uniform(-1, 1),
                                                  _fr.uniform(-1, 1)]}
                         for i in range(400)]),
            "edges": ([{"pdf": "tight", "nid": i, "score": .9}
                       for i in range(60)]
                      + [{"pdf": "spread", "nid": 100 + i, "score": .9}
                         for i in range(400)]),
        }
        _fly = pdf_map.map_canvas(None, _FLYG)
        _fly.show()
        _fly.resize(700, 460)
        _fly._reduce_motion = lambda: False
        _app.processEvents()
        _fly._ensure_fit(700.0, 460.0)
        _wide = _fly._vp.scale

        def _fly_no_trim(_safe):
            _t = pdf_map.FLY_TRIM
            pdf_map.FLY_TRIM = 0.0
            try:
                return _fly._fly_target(_safe)
            finally:
                pdf_map.FLY_TRIM = _t
        _target = _fly._fly_target("tight")
        check("the flight's destination frames the clicked PDF's own "
              "cluster, so it lands much CLOSER than the whole-graph fit",
              _target is not None and _target.scale > 3.0 * _wide,
              f"{_wide:.1f} -> {_target.scale if _target else None}")
        _spread = _fly._fly_target("spread")
        check("...and a PDF matching notes all over the collection "
              "still gets a real flight, because the frame TRIMS its "
              "wildest matches (K-158: framing every match zoomed by "
              "exactly 1.00x on the real library, which is why the "
              "screenshot Pouya sent had no structure in it)",
              _spread.scale > _wide, f"{_spread.scale:.1f} vs {_wide:.1f}")
        check("...but never zooms you OUT past everything: with the "
              "trim switched off, a PDF whose matches ARE the whole "
              "collection clamps at the whole-graph fit",
              abs(_fly_no_trim("spread").scale - _wide) < 1e-9,
              f"{_fly_no_trim('spread').scale:.1f} vs {_wide:.1f}")
        _fly.fly_to("tight")
        check("the flight starts where the camera was...",
              abs(_fly._vp.scale - _wide) < 1e-6)
        _fly._set_fly(1.0)
        check("...and ends exactly on the destination",
              abs(_fly._vp.scale - _target.scale) < 1e-6
              and abs(_fly._vp.ox - _target.ox) < 1e-6)
        _fly._fly_anim.stop()

        # A host handing us the pre-K-148 two-number rows must still get
        # a map — flat, but drawn.
        _flat = pdf_map.map_canvas(None, {
            "pdfs": [{"safe": "old", "display": "Old Shape", "xy": [0.2, 0.1],
                      "match_count": 3}],
            "notes": [{"nid": i, "xy": [i / 30.0 - 1.0, 0.2]}
                      for i in range(60)],
            "edges": [],
        })
        _flat.show()
        _flat.resize(400, 300)
        _app.processEvents()
        check("a graph in the OLD two-number shape still renders — flat, "
              "on the z=0 plane, rather than as an empty card",
              sum(poly.count() for _i, _z, poly in _flat._bands) == 60
              and set(_flat._pdf_xyz) == {"old"}
              and len(_flat._bands) == 1)

        # ---- K-158: the two bugs the screenshot showed ----

        # BUG 5, and the diagnosis that matters: the gate WAS firing.
        # The label and the edges share active_pdf, and Pouya's frame
        # had the label in it — so the edges were drawn and invisible.
        # Measured on that exact frame, the whole edge layer moved 0.59%
        # of the pixels: 1px lines at 0.25 alpha over 28,670 grey chips.
        _lit = pdf_map.map_canvas(None, CLOUD)
        _lit.show()
        _lit.resize(700, 460)
        _app.processEvents()
        _lit._ensure_fit(700.0, 460.0)
        _lit._selected = None
        _off = _render(_lit, 700, 460)
        _lit._selected = "lec1"
        _on = _render(_lit, 700, 460)
        # K-174 replaces K-158's AREA threshold with a CONTRAST one,
        # and the reason is the whole card. K-148's edge layer moved
        # 0.59% of the pixels and was invisible; K-158 answered with
        # fat glowing beams that moved 5% and set the gate there. A
        # hard 1px line is a THIRD of that area by construction — a
        # glow's skirt is most of its footprint — so an area gate
        # would now read "crisp" as "regressed". What actually
        # separates drawn-and-visible from drawn-and-invisible is how
        # HARD each pixel moved: K-148's 1px lines at 0.25 alpha over
        # grey chips could not shift a pixel by more than a few
        # levels, however many of them they touched.
        def _delta(a, b):
            return max(abs(a.red() - b.red()), abs(a.green() - b.green()),
                       abs(a.blue() - b.blue()))

        _sampled = 460 * 700
        _moved_edges = 0
        _hard_focus = 0
        for _y in range(460):
            for _x in range(700):
                _d = _delta(_off.pixelColor(_x, _y), _on.pixelColor(_x, _y))
                if _d:
                    _moved_edges += 1
                    if _d > 40:
                        _hard_focus += 1
        check("focusing a PDF has to CHANGE THE PICTURE, and change it "
              "HARD — its connections are the point of the view, and "
              "K-148's edge layer moved 0.59% of the pixels on the "
              "frame that was supposed to be all edges",
              _moved_edges > _sampled * 0.04
              and _hard_focus > _sampled * 0.01,
              f"{100.0 * _moved_edges / _sampled:.2f}% moved, "
              f"{100.0 * _hard_focus / _sampled:.2f}% by more than 40 levels")
        _real_links = pdf_map.links_for
        pdf_map.links_for = lambda linked, active: []
        try:
            _none = _render(_lit, 700, 460)
        finally:
            pdf_map.links_for = _real_links
        _beam_only = 0
        _hard_edges = 0
        for _y in range(460):
            for _x in range(700):
                _d = _delta(_on.pixelColor(_x, _y), _none.pixelColor(_x, _y))
                if _d:
                    _beam_only += 1
                    if _d > 40:
                        _hard_edges += 1
        check("...and the CONNECTION LAYER alone is a real part of it — "
              "isolated by drawing the same focused frame with the "
              "spokes removed. A THIRD of the pixels it touches move "
              "by more than 40 levels; K-148's whole layer was 1px "
              "lines at 0.25 alpha, which cannot move a pixel that far "
              "no matter how many it touches, and that is why it was "
              "drawn and invisible over 28,670 grey chips",
              _beam_only > _sampled * 0.008
              and _hard_edges > _sampled * 0.002
              and _hard_edges > 0.25 * _beam_only,
              f"{100.0 * _beam_only / _sampled:.2f}% moved, "
              f"{100.0 * _hard_edges / _sampled:.3f}% by more than 40 "
              f"({100.0 * _hard_edges / max(1, _beam_only):.0f}% of them)")

        # The spokes TAPER. Rendered flat first, and 90 hard lines all
        # converging on one node is a dandelion whose far ends carry as
        # much weight as the hub they are about. Measured as the ink
        # the edge layer adds near the node against the ink it adds far
        # from it, on the same frame.
        _ex, _ey, _ = pdf_map.project_point(
            _lit._vp, _lit._cam, *_lit._pdf_xyz["lec1"])

        def _edge_ink(r0, r1):
            _tot = 0
            _n = 0
            for _y in range(0, 460):
                for _x in range(0, 700):
                    _d = math.hypot(_x - _ex, _y - _ey)
                    if not (r0 <= _d < r1):
                        continue
                    _v = _delta(_on.pixelColor(_x, _y),
                                _none.pixelColor(_x, _y))
                    if _v:
                        _tot += _v
                        _n += 1
            return _tot / max(1, _n)

        _near_ink = _edge_ink(60.0, 120.0)
        _far_ink = _edge_ink(200.0, 300.0)
        check("...and the spokes TAPER, brightest at the hub and "
              "dissolving into the field — the honest picture (a far "
              "match is a weaker one) and the difference between a "
              "constellation with an emphasised node and a dandelion. "
              "Diluted on the pixels by two things the ratio has to "
              "live with: the node's own halo already lights the "
              "innermost ring in BOTH frames, and a spoke crossing a "
              "near-white star DARKENS it. The ramp itself is pinned "
              "exactly, in the pure section",
              _near_ink > 1.5 * _far_ink,
              f"mean delta {_near_ink:.0f} at 60-120px from the node, "
              f"{_far_ink:.0f} at 200-300px")

        # BUG 4. The offset was never the problem: label_anchor cleared
        # the node's drawn radius by 9px, and the drawn radius does not
        # move with zoom at all. The name was emitted INSIDE the
        # depth-sorted node loop, so a PDF that sorted nearer painted
        # its disc over it. On the real graph four centroids sit within
        # ~50px of each other and that is exactly what happened.
        _nodes_seg = _method_seg("_MapCanvas", "_paint_nodes")
        check("no node painter draws text — the name is a pass of its "
              "own, run after EVERY circle is down, so a nearer node "
              "can never land on top of it",
              "drawText" not in _nodes_seg
              and "drawText" in _method_seg("_MapCanvas", "_paint_label")
              and _CODE.count("drawText(") == 2)
        _paint_body = _method_seg("_MapCanvas", "_paint")
        check("...and the call order says so too: nodes, then the plate",
              _paint_body.index("_paint_nodes(")
              < _paint_body.index("_paint_label("))

        # ...and the clipping half of the same defect, checked with real
        # font metrics at every position a node can take on screen.
        _clipc = pdf_map.map_canvas(None, {
            "pdfs": [{"safe": "long", "folder": "Anatomy/Week 2",
                      "display": "Measures of Disease Frequency ELO",
                      "threshold": .4, "retention": 0.83,
                      "xyz": [0.0, 0.0, 0.0], "match_count": 40}],
            "notes": [{"nid": 1, "xyz": [0.0, 0.0, 0.0]}], "edges": [],
        })
        _clipc.show()
        _clipc.resize(700, 460)
        _app.processEvents()
        _fnt = _QtG.QFont()
        _fnt.setPixelSize(11)
        _fm = _QtG.QFontMetricsF(_fnt)
        _lines = pdf_map.node_lines(_clipc._pdfs[0])
        _tw = max(_fm.horizontalAdvance(t) for t in _lines)
        _bad = []
        for _px in range(-40, 741, 20):
            _lx, _ly = pdf_map.label_anchor(float(_px), 230.0, 22.0, _tw, 700.0)
            _lx = pdf_map.clamp_label(_lx, _tw, 700.0)
            if _lx < 0 or _lx + _tw > 700.0:
                _bad.append(_px)
        check("a real four-line plate stays inside the canvas at EVERY "
              "node position, off-screen ones included — label_anchor "
              "mirrors only when the mirrored side fits, and a name "
              "clipped at the edge has now been reported three times "
              "in this module",
              not _bad, f"clipped at node x = {_bad}")
        check("...and the painter actually goes through that clamp — "
              "the check above validates the math, this is what stops "
              "the paint path quietly skipping it",
              "clamp_label(lx, tw, w)" in _method_seg("_MapCanvas",
                                                      "_paint_label"))

        # BUG 5's other half: a click that never lands. K-148 compared
        # each individual move delta against 2.0, so a couple of pixels
        # of trackpad finger drift promoted a click to a pan — nothing
        # selected, nothing flown to, no connections drawn.
        def _mouse(kind, x, y, btn, btns):
            return _QtG.QMouseEvent(
                kind, _QtC.QPointF(x, y), _QtC.QPointF(x, y), btn, btns,
                _QtC.Qt.KeyboardModifier.NoModifier)

        _clk = pdf_map.map_canvas(None, CLOUD)
        _clk.show()
        _clk.resize(700, 460)
        _clk._reduce_motion = lambda: True
        _app.processEvents()
        _clk._ensure_fit(700.0, 460.0)
        _nx, _ny, _ = pdf_map.project_point(
            _clk._vp, _clk._cam, *_clk._pdf_xyz["lec1"])
        _clk.mousePressEvent(_mouse(
            _QtC.QEvent.Type.MouseButtonPress, _nx, _ny,
            _QtC.Qt.MouseButton.LeftButton, _QtC.Qt.MouseButton.LeftButton))
        _clk.mouseMoveEvent(_mouse(
            _QtC.QEvent.Type.MouseMove, _nx + 2, _ny + 1,
            _QtC.Qt.MouseButton.NoButton, _QtC.Qt.MouseButton.LeftButton))
        _clk.mouseReleaseEvent(_mouse(
            _QtC.QEvent.Type.MouseButtonRelease, _nx + 2, _ny + 1,
            _QtC.Qt.MouseButton.LeftButton, _QtC.Qt.MouseButton.NoButton))
        check("a click with two pixels of trackpad drift still SELECTS "
              "— the drag threshold is measured from where the button "
              "went down, not per move event",
              _clk._selected == "lec1")
        # The click above FLEW the camera, so the node has moved: ask
        # again where it is, or the drag below would "select nothing"
        # by missing rather than by being a drag.
        _clk._selected = None
        _clk._did_fit = False
        _clk._ensure_fit(700.0, 460.0)
        _nx, _ny, _ = pdf_map.project_point(
            _clk._vp, _clk._cam, *_clk._pdf_xyz["lec1"])
        check("(the node is where the drag below starts, so a failure "
              "there is about the threshold and not about a miss)",
              _clk._hit_at(_nx, _ny) == "lec1"
              and _clk._hit_at(_nx + 7, _ny) == "lec1")
        _clk.mousePressEvent(_mouse(
            _QtC.QEvent.Type.MouseButtonPress, _nx, _ny,
            _QtC.Qt.MouseButton.LeftButton, _QtC.Qt.MouseButton.LeftButton))
        for _step in range(1, 8):
            _clk.mouseMoveEvent(_mouse(
                _QtC.QEvent.Type.MouseMove, _nx + _step, _ny,
                _QtC.Qt.MouseButton.NoButton, _QtC.Qt.MouseButton.LeftButton))
        _clk.mouseReleaseEvent(_mouse(
            _QtC.QEvent.Type.MouseButtonRelease, _nx + 7, _ny,
            _QtC.Qt.MouseButton.LeftButton, _QtC.Qt.MouseButton.NoButton))
        check("...while a real drag past CLICK_SLOP is still a pan, and "
              "selects nothing",
              _clk._selected is None)

        # ---- K-158: one PDF in focus ----
        _foc = pdf_map.map_canvas(None, CLOUD)
        _foc.show()
        _foc.resize(700, 460)
        _foc._reduce_motion = lambda: True
        _app.processEvents()
        check("a canvas nobody asked to opens on the bare cloud — the "
              "Library's dock is told which PDF to show by the viewer "
              "and must not pick a different one behind the reader",
              _foc._selected is None and _foc._auto_focus is False)
        _foc.set_initial_focus(True)
        _foc._did_fit = False
        _foc._ensure_fit(700.0, 460.0)
        check("...and a host that asks LANDS on one, at the first fit — "
              "most-matched first, framed on its own region of the "
              "cloud rather than on the whole ball of dots",
              _foc._selected == "lec1"
              and _foc._vp.scale > pdf_map.frame_bounds(
                  _foc._bounds, _foc._cam, (700.0, 460.0)).scale)
        check("arrow keys step the focus and fly there — the picker for "
              "a window with no viewer to follow, and the only one that "
              "works when centroids stack PDFs on top of each other",
              _foc.step_focus(1) is True and _foc._selected == "lec2"
              and _foc.step_focus(1) is True and _foc._selected == "lec1")
        _foc.keyPressEvent(_QtG.QKeyEvent(
            _QtC.QEvent.Type.KeyPress, _QtC.Qt.Key.Key_Right.value,
            _QtC.Qt.KeyboardModifier.NoModifier))
        check("...wired to Right/Left, with Escape back to the whole "
              "cloud",
              _foc._selected == "lec2")
        _foc.keyPressEvent(_QtG.QKeyEvent(
            _QtC.QEvent.Type.KeyPress, _QtC.Qt.Key.Key_Escape.value,
            _QtC.Qt.KeyboardModifier.NoModifier))
        check("...and Escape clears it, refitting the whole graph",
              _foc._selected is None
              and abs(_foc._vp.scale - pdf_map.frame_bounds(
                  _foc._bounds, _foc._cam, (700.0, 460.0)).scale) < 1e-6)
        _foc._selected = "lec1"
        _one = _render(_foc, 700, 460)
        _foc._selected = "lec2"
        _two = _render(_foc, 700, 460)
        check("the two focuses are genuinely different pictures — one "
              "PDF lit and the rest ghosts, not the same frame with a "
              "different caption",
              sum(1 for y in range(0, 460, 3) for x in range(0, 700, 3)
                  if _one.pixelColor(x, y) != _two.pixelColor(x, y)) > 200)

        def _bright_box(img, cx, cy, r=12):
            """Bright pixels in a small box round a node.

            K-158 could ask this as an absolute ("the ambient field
            never gets there") because its stars were 46%-alpha glow
            cores. K-174's stars ARE near-white by design — that is the
            reference's whole look — so a box anywhere inside the cloud
            catches a few of them, and the honest question became a
            RATIO between the lit node and the ghost plus a control
            reading of empty sky."""
            _n = 0
            for _y in range(max(0, int(cy - r)), min(460, int(cy + r))):
                for _x in range(max(0, int(cx - r)), min(700, int(cx + r))):
                    _c = img.pixelColor(_x, _y)
                    if _c.red() + _c.green() + _c.blue() > 450:
                        _n += 1
            return _n

        _foc._selected = "lec1"
        _foc._did_fit = False
        _foc._ensure_fit(700.0, 460.0)
        _l2x, _l2y, _ = pdf_map.project_point(
            _foc._vp, _foc._cam, *_foc._pdf_xyz["lec2"])
        _ghosted = _bright_box(_render(_foc, 700, 460), _l2x, _l2y)
        _foc._selected = "lec2"
        _lit_ink = _bright_box(_render(_foc, 700, 460), _l2x, _l2y)
        _sky = max(_bright_box(_render(_foc, 700, 460), _cx, _cy)
                   for _cx, _cy in ((40, 40), (660, 40), (40, 420),
                                    (660, 420)))
        check("an UNFOCUSED PDF is a ghost, not a second lit node — "
              "PDFs sit at their matched notes' centroid (K-058), so "
              "files with overlapping matches land on top of each "
              "other and four lit rings become one unreadable knot. "
              "Asked as a RATIO because K-174's stars are near-white "
              "and a box inside the cloud catches two or three of them "
              "wherever it is put",
              _lit_ink > 40 and _lit_ink > 5 * max(1, _ghosted)
              and _ghosted < 15,
              f"ghosted {_ghosted} bright px, lit {_lit_ink}, "
              f"empty sky {_sky}")

        # ---- K-174: the constellation, ON THE PIXELS ----
        # The reference's numbers, asked of our own render. This is the
        # acceptance test the card set and it is the only one that can
        # tell a hard point from a soft one.
        _sky = pdf_map.map_canvas(None, {
            "pdfs": [], "edges": [],
            "notes": [{"nid": i, "xyz": [_rng.gauss(0, .3), _rng.gauss(0, .3),
                                         _rng.gauss(0, .3)]}
                      for i in range(1200)]})
        _sky.show()
        _sky.resize(900, 640)
        _app.processEvents()
        _sky._reduce_motion = lambda: True
        _sky._ensure_fit(900.0, 640.0)
        _si = _render(_sky, 900, 640)

        def _runs(img, w, h, th=430, inset=4):
            """Horizontal runs of lit pixels — the reference's one
            decisive measurement. Inset past the card's own 1px border,
            which is a full-width run of host-palette grey and nothing
            to do with the field."""
            out = {}
            lit = 0
            for y in range(inset, h - inset):
                run = 0
                for x in range(inset, w - inset):
                    c = img.pixelColor(x, y)
                    if c.red() + c.green() + c.blue() > th:
                        run += 1
                        lit += 1
                    else:
                        if run:
                            out[run] = out.get(run, 0) + 1
                        run = 0
                if run:
                    out[run] = out.get(run, 0) + 1
            return out, lit

        _r, _lit_px = _runs(_si, 900, 640)
        check("THE measurement, on our own render: with no PDF nodes in "
              "the frame the longest run of lit pixels in a row is at "
              "most STAR_SIZE_MAX. On aalampour.com's canvas that "
              "number is 4 device pixels on a 2x surface — 1 to 2 CSS "
              "px — and it is the whole difference between a hard point "
              "and a glow, whose falloff IS a long run of "
              "mid-brightness pixels",
              max(_r) <= pdf_map.STAR_SIZE_MAX,
              f"runs {sorted(_r.items())}")
        check("...and the field is SPARSE: under 1% of the card is lit, "
              "against the reference's 0.08%. Deliberately denser and "
              "the reason is the data — its starfield decorates a page "
              "and ours is 28,670 notes, where the reference's ~20 "
              "visible stars per megapixel would draw thirteen of them "
              "and say nothing about the embedding",
              0.02 < 100.0 * _lit_px / (900.0 * 640.0) < 1.0,
              f"{100.0 * _lit_px / (900.0 * 640.0):.3f}% lit, "
              f"{sum(_r.values())} stars")
        check("...and most of them are the SMALL sizes, as the "
              "reference's median blob (2 device px) says they should "
              "be — a field of uniform 3px stars carries four times "
              "its ink",
              _r.get(1, 0) + _r.get(2, 0) > 2 * _r.get(3, 0),
              f"1px {_r.get(1, 0)}, 2px {_r.get(2, 0)}, 3px {_r.get(3, 0)}")

        # The constellation has to REACH THE PIXELS, and it has to be
        # the same figure twice.
        _links_before = list(_sky._links)
        _with = _render(_sky, 900, 640)
        _saved, _sky._links = _sky._links, []
        _without = _render(_sky, 900, 640)
        _sky._links = _saved
        _dl = sum(1 for y in range(0, 640, 2) for x in range(0, 900, 2)
                  if _with.pixelColor(x, y) != _without.pixelColor(x, y))
        check("the interconnections reach the pixels — 'I want each "
              "node on the graph to be just randomly interconnected'",
              _dl > 300 and len(_links_before) > 60,
              f"{len(_links_before)} segments, {_dl} sampled pixels")
        _again = pdf_map.map_canvas(None, {
            "pdfs": [], "edges": [],
            "notes": [{"nid": i, "xyz": list(p)}
                      for i, p in enumerate(_sky._notes)]})
        check("...and they are STABLE: a canvas built again over the "
              "same cloud draws the same figure, because the seed is "
              "the cloud. A per-frame reroll shimmers and reads as "
              "broken",
              pdf_map.link_seed([(p[0], p[1], p[2]) for p in _sky._notes])
              == pdf_map.link_seed([(p[0], p[1], p[2])
                                    for p in _again._notes]))
        check("...and the constellation never draws over a band it did "
              "not map, so a segment can never be anchored at (0, 0)",
              all(0 <= _sa < len(_sky._draw) and 0 <= _sb < len(_sky._draw)
                  and _ka < _sky._draw[_sa][2].count()
                  and _kb < _sky._draw[_sb][2].count()
                  for _sa, _ka, _sb, _kb in _sky._links))
        _sky.hide()

        # ---- the rotation is a TURN, on a real timer path ----
        _rot = pdf_map.map_canvas(None, CLOUD)
        _rot.show()
        _rot.resize(700, 460)
        _rot._reduce_motion = lambda: False
        _app.processEvents()
        _rot._cam = pdf_map.Camera(pdf_map.REST_ANGLE)
        _seen = []
        for _ in range(2300):
            _rot._idle_tick()
            _seen.append(_rot._cam.angle)
        _swept = max(_seen) - min(_seen)
        check("the idle motion is a full REVOLUTION, not K-148's sway: "
              "2300 ticks carry the camera through more than a whole "
              "turn, and the phase only ever advances",
              _swept > 2.0 * math.pi * 0.95
              and all(_seen[i] <= _seen[i + 1] + 1e-9
                      or _seen[i + 1] < 1.0
                      for i in range(len(_seen) - 1)),
              f"swept {_swept:.2f} rad over 2300 ticks")
        check("...and it stays SLOW — those 2300 ticks are 76 seconds "
              "of wall clock, so a full turn takes more than a minute",
              2300 * pdf_map.IDLE_TICK_MS / 1000.0 > 60.0)
        _rot.hide()

        # The rotating fit has to hold every pose it will show.
        _spin2 = pdf_map.map_canvas(None, CLOUD)
        _spin2.set_idle_rotation(True)
        _spin2.show()
        _spin2.resize(700, 460)
        _app.processEvents()
        _spin2._reduce_motion = lambda: True
        _spin2._ensure_fit(700.0, 460.0)
        _escaped = []
        for _k in range(24):
            _spin2._cam = pdf_map.Camera(2.0 * math.pi * _k / 24.0)
            for _p in list(_spin2._pdf_xyz.values()) + _spin2._notes[:200]:
                _px, _py, _ = pdf_map.project_point(
                    _spin2._vp, _spin2._cam, *_p)
                if not (0 <= _px <= 700 and 0 <= _py <= 460):
                    _escaped.append((_k, round(_px), round(_py)))
        check("a canvas that ROTATES frames the swept box, so no node "
              "and no star walks out of the card at any pose of the "
              "turn — the failure this prevents is the cloud sliding "
              "off the side thirty seconds after the window opens",
              not _escaped, f"{len(_escaped)} escapes, first {_escaped[:3]}")
        _still = pdf_map.map_canvas(None, CLOUD)
        _still.show()
        _still.resize(700, 460)
        _app.processEvents()
        _still._ensure_fit(700.0, 460.0)
        check("...while the STILL canvas (the Library's dock, Pouya's "
              "explicit call) keeps K-158's tighter crop, because it "
              "only ever shows the one pose",
              _still._vp.scale > _spin2._vp.scale * 1.05,
              f"still {_still._vp.scale:.1f} vs rotating "
              f"{_spin2._vp.scale:.1f}")
        _still.hide()
        _spin2.hide()

        # ---- the frame budget ----
        # Pouya, unprompted, on K-158: "you've made it a lot faster."
        # That is a floor. The threshold here is deliberately loose —
        # it exists to catch an order-of-magnitude regression (an
        # antialiased glowing stroke layer measures 6-40 ms), not to
        # police a tenth of a millisecond on a shared machine.
        _bud = pdf_map.map_canvas(None, CLOUD)
        _bud.show()
        _bud.resize(900, 640)
        _app.processEvents()
        _bud._reduce_motion = lambda: True
        _bud._ensure_fit(900.0, 640.0)
        _bud._selected = "lec1"
        _bimg = _QtG.QImage(900, 640, _QtG.QImage.Format.Format_ARGB32)
        for _ in range(5):
            _bimg.fill(0)
            _bud.render(_bimg)
        _times = []
        for _ in range(25):
            _bimg.fill(0)
            _t0 = time.perf_counter()
            _bud.render(_bimg)
            _times.append((time.perf_counter() - _t0) * 1000.0)
        _times.sort()
        _median = _times[len(_times) // 2]
        check("a focused frame stays well inside the budget K-158 set "
              "and K-174 had to keep: measured on this machine at "
              "28,670 notes and 900x640, 1.83 ms at rest / 3.26 "
              "focused / 4.04 focused with the camera turned before "
              "this card, and 1.32 / 1.82 / 1.79 after",
              _median < 8.0, f"median {_median:.2f} ms over 25 frames")
        _bud.hide()

        # The coupling K-174 found by walking into it.
        _amb90, _lk90, _pos90, _t90, _s90 = pdf_map.split_cloud(
            _FLYG, cap=420, per_pdf=90)
        _amb140, _lk140, _pos140, _t140, _s140 = pdf_map.split_cloud(
            _FLYG, cap=420, per_pdf=140)

        def _target_scale(pts, trim):
            _b = pdf_map.trimmed_bounds(pts, trim)
            _c = [(_b[0] + _b[3]) / 2, (_b[1] + _b[4]) / 2,
                  (_b[2] + _b[5]) / 2]
            _pd = pdf_map.FLY_PADDING
            _bb = tuple(_c[i % 3] + (_b[i] - _c[i % 3]) * _pd
                        for i in range(6))
            return pdf_map.frame_bounds(
                _bb, pdf_map.Camera(), (700.0, 460.0)).scale

        _floor = pdf_map.frame_bounds(
            pdf_map.trimmed_bounds(
                [pdf_map.row_xyz(n) for n in _FLYG["notes"]],
                pdf_map.FIT_TRIM),
            pdf_map.Camera(), (700.0, 460.0)).scale
        check("SAMPLE_PER_PDF is COUPLED TO FLY_TRIM, silently, and "
              "this is the pin that says so. The flight frames the "
              "SAMPLE; drawing more of a scattered PDF's matches "
              "widens the trimmed box until the padded frame passes "
              "the whole-graph fit and the flight clamps to no zoom at "
              "all — the exact K-158 bug FLY_TRIM exists to fix. At 90 "
              "it flies, at 140 it does not, and nothing but a render "
              "would have told you",
              _target_scale(_lk90["spread"], pdf_map.FLY_TRIM) > _floor
              and _target_scale(_lk140["spread"], pdf_map.FLY_TRIM) < _floor
              and _target_scale(_lk140["spread"], 0.15) > _floor,
              f"floor {_floor:.1f}; 90 -> "
              f"{_target_scale(_lk90['spread'], pdf_map.FLY_TRIM):.1f}, "
              f"140 -> "
              f"{_target_scale(_lk140['spread'], pdf_map.FLY_TRIM):.1f}, "
              f"140 at trim .15 -> "
              f"{_target_scale(_lk140['spread'], 0.15):.1f}")

        _dock._vp = pdf_map.pan_by(_dock._vp, -5000.0, -5000.0)
        check("select() on the bare canvas is the dock's whole "
              "follow-the-viewer path, recentre included",
              _dock.select("lec1") is True
              and _dock._selected == "lec1"
              and abs(pdf_map.project_point(
                  _dock._vp, _dock._cam, -0.5, -0.2, .35)[0]
                  - 545 / 2.0) < 1e-6)
    finally:
        pdf_map._instance = None
        pdf_map._load_graph = _orig_load
        pdf_map._fill_retention = _orig_fill
        theme.night_mode = _orig_night

    # ---- K-185: the map paints on the panel's ground ----
    # `_QtG`/`_render` are this section's existing aliases; `G`/`_grab`
    # below just spell them the way these pins read most naturally.
    # `_grab` forces night mode per call so the SAME canvas construction
    # is checked against both palettes' "chrome" token.
    G = _QtG

    def _grab(canvas, night):
        cw, ch = 200, 150
        theme.night_mode = lambda: night
        canvas.resize(cw, ch)
        canvas.show()
        _app.processEvents()
        return _render(canvas, cw, ch)

    try:
        for _night in (True, False):
            _host = theme.palette(_night)
            _cv = pdf_map.map_canvas(None, FAKE)
            _img = _grab(_cv, night=_night)
            _ground = G.QColor(_host["chrome"])
            _corner = G.QColor(_img.pixel(1, 1))
            _centre_edge = G.QColor(_img.pixel(3, _img.height() // 2))
            check(f"night={_night}: the canvas corner IS the host chrome token — no rounded "
                  "card, no border pixel, no clip: the map sits on the panel",
                  (abs(_corner.red() - _ground.red()) <= 2
                   and abs(_corner.green() - _ground.green()) <= 2
                   and abs(_corner.blue() - _ground.blue()) <= 2),
                  f"corner={_corner.name()} chrome={_ground.name()}")
            check(f"night={_night}: the ground is FLAT — an edge-middle pixel equals the "
                  "corner, so the radial vignette lift is gone",
                  _corner.rgb() == _centre_edge.rgb(),
                  f"corner={_corner.name()} edge={_centre_edge.name()}")
            _cv.close()
        check("VIGNETTE_LIFT and VIGNETTE_SPREAD are gone by name — the lift was the "
              "'general glow' under the whole field",
              not hasattr(pdf_map, "VIGNETTE_LIFT") and not hasattr(pdf_map, "VIGNETTE_SPREAD"))
        check("the canvas no longer forces the dark palette: _paint reads the HOST palette "
              "(the always-dark special case of K-174 is retired)",
              "theme.palette(True)" not in _func_seg("_paint"),
              "found a hard-coded palette(True)")
    finally:
        theme.night_mode = _orig_night

raise SystemExit(report())
